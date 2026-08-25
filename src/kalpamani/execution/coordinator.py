"""The Phase 2 production orchestration path (ADR-0004 §6).

Every lifecycle transition and every durable write lives here, so the LEAN
algorithm and the tests exercise **the same code**. The first review of Phase 2
found the opposite arrangement -- an integration test that performed transitions
`main.py` never did -- which meant the tests could pass while production omitted
steps entirely. This module exists to make that class of gap impossible.

`main.py` supplies broker I/O and nothing else: it asks the coordinator what to
do, performs the LEAN call, and hands events back. It holds no lifecycle logic.

Every method that changes state **persists before returning**. Nothing important
is carried in memory.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

from kalpamani.broker.orders import OrderRequest, OrderSide, OrderType
from kalpamani.common.capital import StrategyCapital
from kalpamani.execution.envelope import (
    PHASE2_QUANTITY,
    PHASE2_SYMBOL,
    ExecutionArmRequest,
    assert_arm_not_reusable,
    authorize_trade_intent,
    protective_stop_price,
)
from kalpamani.execution.identity import OrderRole, TradeIdentity
from kalpamani.execution.lifecycle import TradeState, transition
from kalpamani.execution.reconciliation import (
    BrokerView,
    ReconciliationError,
    assert_flat,
    assert_protected,
    assert_safe_to_close,
    plan_exit,
    reconcile,
    required_protection_quantity,
)
from kalpamani.execution.session import (
    ArmReceipt,
    BrokerSessionEvidence,
    arm_receipt_paths,
    assert_arm_available,
    verify_paper_session,
    write_arm_receipt,
)
from kalpamani.execution.state_store import (
    TradeRecord,
    TradeStateStore,
    apply_fill,
    confirm_cancel,
    record_order_intent,
    request_cancel,
)


@dataclass(frozen=True, slots=True)
class PendingOrder:
    """An order the coordinator has durably recorded and wants submitted.

    Returned only *after* the write-ahead record is persisted, so a caller that
    receives one can submit it knowing the intent already survives a crash.
    """

    request: OrderRequest
    record: TradeRecord


class Phase2Coordinator:
    """Drives the Phase 2 lifecycle. All transitions and writes happen here."""

    def __init__(
        self,
        store: TradeStateStore,
        identity: TradeIdentity,
        *,
        storage_root: Path,
        project_root: Path,
    ) -> None:
        self._store = store
        self._identity = identity
        self._receipt_paths = arm_receipt_paths(storage_root, project_root)

    @property
    def identity(self) -> TradeIdentity:
        return self._identity

    @property
    def receipt_paths(self) -> tuple[Path, ...]:
        return self._receipt_paths

    # -- Recovery ----------------------------------------------------------

    def load(self) -> TradeRecord | None:
        """Load the trade record, failing closed if a consumed arm lost its state.

        Raises:
            ArmReceiptError: if a receipt records the arm as consumed but no
                trade record exists. Missing state is *missing*, not absent, and
                must never read as "first run, safe to arm".
        """
        record = self._store.get(self._identity.trade_intent_id)
        assert_arm_available(self._receipt_paths, trade_state_present=record is not None)
        if record is not None:
            assert_arm_not_reusable(record)
        return record

    # -- Arming ------------------------------------------------------------

    def authorize(
        self,
        request: ExecutionArmRequest,
        evidence: BrokerSessionEvidence,
        *,
        capital: StrategyCapital | None = None,
    ) -> TradeRecord:
        """Verify the session, consume the arm, and persist -- before any broker call.

        The receipt is written to two independent mounts *before* the trade
        record, so even a failure between the two leaves evidence that an arm was
        issued.
        """
        verify_paper_session(evidence)
        identity, record = authorize_trade_intent(request, self._store, capital=capital)
        self._identity = identity

        write_arm_receipt(
            ArmReceipt(
                trade_intent_id=identity.trade_intent_id,
                account_fingerprint=evidence.fingerprint,
                consumed=True,
            ),
            self._receipt_paths,
        )
        self._store.put(record)
        return record

    # -- Entry -------------------------------------------------------------

    def begin_entry(self, record: TradeRecord) -> PendingOrder:
        """Write-ahead-record the single entry order, then hand it back to submit."""
        if record.entry_count >= 1:
            raise ReconciliationError(
                f"Execution {record.execution_id} already has an entry order. Refusing a "
                "second entry."
            )
        pending = record_order_intent(
            record,
            client_order_id=self._identity.entry_order_id,
            role=OrderRole.ENTRY,
            symbol=PHASE2_SYMBOL,
            side="BUY",
            quantity=PHASE2_QUANTITY,
        )
        pending = replace(pending, state=transition(pending.state, TradeState.ENTRY_SUBMITTED))
        self._store.put(pending)
        return PendingOrder(
            request=OrderRequest(
                client_order_id=self._identity.entry_order_id,
                symbol=PHASE2_SYMBOL,
                side=OrderSide.BUY,
                quantity=PHASE2_QUANTITY,
                order_type=OrderType.MARKET,
                role=OrderRole.ENTRY,
            ),
            record=pending,
        )

    # -- Fills -------------------------------------------------------------

    def on_fill(
        self,
        record: TradeRecord,
        *,
        client_order_id: str,
        fill_id: str,
        fill_quantity: int,
    ) -> TradeRecord:
        """Apply a fill idempotently and advance the lifecycle to match it."""
        updated = apply_fill(
            record,
            client_order_id=client_order_id,
            fill_id=fill_id,
            fill_quantity=fill_quantity,
        )
        if updated is record:  # duplicate event: a true no-op
            return record

        order = updated.orders[client_order_id]
        if order.role is OrderRole.ENTRY:
            updated = self._advance_after_entry_fill(updated)
        elif order.role in (OrderRole.PROTECTIVE, OrderRole.EXIT):
            updated = self._advance_after_closing_fill(updated)

        self._store.put(updated)
        return updated

    def _advance_after_entry_fill(self, record: TradeRecord) -> TradeRecord:
        state = record.state
        if state is TradeState.ENTRY_SUBMITTED:
            state = transition(state, TradeState.ENTRY_ACKNOWLEDGED)
        if state is TradeState.ENTRY_ACKNOWLEDGED:
            state = transition(
                state,
                TradeState.FILLED
                if record.filled_quantity >= record.requested_quantity
                else TradeState.PARTIALLY_FILLED,
            )
        elif state is TradeState.PARTIALLY_FILLED and (
            record.filled_quantity >= record.requested_quantity
        ):
            state = transition(state, TradeState.FILLED)
        return replace(record, state=state)

    def _advance_after_closing_fill(self, record: TradeRecord) -> TradeRecord:
        """A protective or exit fill that flattens the long moves us to CLOSED.

        A protective stop firing is a legitimate exit route, not an edge case.
        Recognising it here is what stops the system from later trying to sell a
        position the stop already sold -- which would open a short.
        """
        if record.open_long_quantity > 0:
            return record
        return replace(record, state=transition(record.state, TradeState.CLOSED))

    # -- Protection --------------------------------------------------------

    def plan_protection(self, record: TradeRecord, fill_price: Decimal) -> PendingOrder | None:
        """Write-ahead-record protection for the ACTUAL filled quantity.

        Returns ``None`` when nothing should be submitted: zero filled, or
        protection already recorded. A stop for a position that does not exist
        would itself be capable of opening a short.
        """
        quantity = required_protection_quantity(record)
        if quantity <= 0:
            return None
        if record.order_for_role(OrderRole.PROTECTIVE) is not None:
            return None

        stop_price = protective_stop_price(fill_price)
        pending = record_order_intent(
            record,
            client_order_id=self._identity.protective_order_id,
            role=OrderRole.PROTECTIVE,
            symbol=PHASE2_SYMBOL,
            side="SELL",
            quantity=quantity,
        )
        pending = replace(pending, state=transition(pending.state, TradeState.PROTECTION_SUBMITTED))
        self._store.put(pending)
        return PendingOrder(
            request=OrderRequest(
                client_order_id=self._identity.protective_order_id,
                symbol=PHASE2_SYMBOL,
                side=OrderSide.SELL,
                quantity=quantity,
                order_type=OrderType.STOP_MARKET,
                role=OrderRole.PROTECTIVE,
                stop_price=stop_price,
            ),
            record=pending,
        )

    def confirm_protection(self, record: TradeRecord, broker: BrokerView) -> TradeRecord:
        """Promote to PROTECTED only once the broker confirms the working stop."""
        assert_protected(record, self._identity, broker)
        if record.state is not TradeState.PROTECTION_SUBMITTED:
            return record
        updated = replace(record, state=transition(record.state, TradeState.PROTECTED))
        self._store.put(updated)
        return updated

    # -- Exit --------------------------------------------------------------

    def request_exit(self, record: TradeRecord) -> TradeRecord:
        """Move to EXIT_REQUESTED and persist."""
        if record.state is TradeState.EXIT_REQUESTED:
            return record
        updated = replace(record, state=transition(record.state, TradeState.EXIT_REQUESTED))
        self._store.put(updated)
        return updated

    def request_protection_cancel(self, record: TradeRecord) -> TradeRecord:
        """Record that cancellation was ASKED FOR. The stop is still working."""
        protective = record.order_for_role(OrderRole.PROTECTIVE)
        if protective is None or protective.cancel_requested:
            return record
        updated = request_cancel(record, protective.client_order_id)
        self._store.put(updated)
        return updated

    def confirm_protection_cancel(self, record: TradeRecord) -> TradeRecord:
        """Record the broker's CONFIRMED cancellation.

        Only this drops ``protected_quantity`` to zero and makes the close
        eligible. Marking it on the request would let the exit proceed while a
        live stop could still fire.
        """
        protective = record.order_for_role(OrderRole.PROTECTIVE)
        if protective is None or protective.cancelled:
            return record
        updated = confirm_cancel(record, protective.client_order_id)
        self._store.put(updated)
        return updated

    def begin_exit(self, record: TradeRecord, broker: BrokerView) -> PendingOrder:
        """Write-ahead-record the closing SELL, once protection is provably gone.

        Raises:
            ReconciliationError: if a protective order is still working, or the
                exit would exceed the position.
        """
        plan = plan_exit(record, self._identity, broker)
        assert_safe_to_close(plan, self._identity, broker)

        pending = record_order_intent(
            record,
            client_order_id=plan.exit_client_order_id,
            role=OrderRole.EXIT,
            symbol=plan.symbol,
            side="SELL",
            quantity=plan.exit_quantity,
        )
        pending = replace(pending, state=transition(pending.state, TradeState.EXIT_SUBMITTED))
        self._store.put(pending)
        return PendingOrder(
            request=OrderRequest(
                client_order_id=plan.exit_client_order_id,
                symbol=plan.symbol,
                side=OrderSide.SELL,
                quantity=plan.exit_quantity,
                order_type=OrderType.MARKET,
                role=OrderRole.EXIT,
            ),
            record=pending,
        )

    # -- Reconciliation ----------------------------------------------------

    def reconcile(self, record: TradeRecord, broker: BrokerView) -> TradeRecord:
        """Compare against broker truth. Raises on disagreement."""
        reconcile(record, self._identity, broker)
        return record

    def finalize(self, record: TradeRecord, broker: BrokerView) -> TradeRecord:
        """Reach RECONCILED only once the broker confirms flat.

        Raises:
            ReconciliationError: if any position or working order remains,
                including an accidental short.
        """
        assert_flat(record, self._identity, broker)
        if record.state is TradeState.RECONCILED:
            return record
        updated = replace(record, state=transition(record.state, TradeState.RECONCILED))
        self._store.put(updated)
        return updated

    # -- Failure -----------------------------------------------------------

    def fail(self, record: TradeRecord, reason: str) -> TradeRecord:
        """Latch the lifecycle to FAILED and persist the reason."""
        if record.state is TradeState.FAILED:
            return record
        updated = replace(
            record, state=transition(record.state, TradeState.FAILED), failure_reason=reason
        )
        self._store.put(updated)
        return updated


__all__ = ["PendingOrder", "Phase2Coordinator"]
