"""The Phase 2 production orchestration path (ADR-0004 §6).

Every lifecycle transition and every durable write lives here, so the LEAN
algorithm and the tests exercise **the same code**. `main.py` supplies broker
I/O and nothing else: it asks the coordinator what to do, performs the LEAN
call, tells the coordinator the call was attempted, and hands events back.

The dispatch protocol `main.py` must follow, in order:

    pending = coordinator.begin_*(...)     # intent durably recorded
    coordinator.fence_dispatch(...)        # SEND FENCE durable -- BEFORE the call
    broker_call(pending.request)           # the LEAN call

The fence goes first on purpose. No transaction spans "call the broker" and
"record that we called it", so whichever order those happen in, a crash can fall
between them. Writing the fence afterwards would leave ``INTENT_RECORDED`` after
a successful send, and recovery would then conclude "never sent" and issue a
second order -- for a protective stop or an exit, that is a second SELL and a
possible short.

With the fence first, ``INTENT_RECORDED`` is a claim we can actually defend, and
``SEND_FENCED`` says only "a send may have occurred". A crash on either side of
the broker call looks the same from durable state, and both halt for a human.
Safety over automatic liveness.
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
    UnprotectedPositionError,
    assert_flat,
    assert_protected,
    assert_safe_to_close,
    assert_symbol_has_no_open_orders,
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
    DispatchState,
    TradeRecord,
    TradeStateStore,
    apply_fill,
    confirm_cancel,
    fence_dispatch,
    mark_acknowledged,
    mark_rejected,
    record_order_intent,
    request_cancel,
)


@dataclass(frozen=True, slots=True)
class PendingOrder:
    """An order the coordinator has durably recorded and wants dispatched.

    Returned only *after* the write-ahead record is persisted, so a caller that
    receives one can dispatch it knowing the intent already survives a crash.
    """

    request: OrderRequest
    record: TradeRecord


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    """What recovery concluded, and what still needs dispatching."""

    record: TradeRecord
    redispatch: tuple[PendingOrder, ...] = ()
    notes: tuple[str, ...] = ()

    def describe(self) -> str:
        ids = ",".join(p.request.client_order_id for p in self.redispatch) or "(none)"
        return f"redispatch={ids} notes={'; '.join(self.notes) or '(none)'}"


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
        """Load the trade record, failing closed if a consumed arm lost its state."""
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

        The receipt must be written and verified at **every** configured location
        before the arm counts as consumed; a partial write refuses to arm.
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
        record = self._store.put(record)
        return record

    # -- Dispatch bookkeeping ----------------------------------------------

    def fence_dispatch(self, record: TradeRecord, client_order_id: str) -> TradeRecord:
        """Acquire and persist the SEND FENCE. Call this BEFORE the broker call.

        Returns only once the fence is durable, so the caller may then contact
        the broker knowing that a crash at any later point cannot be mistaken for
        "never sent".
        """
        updated = fence_dispatch(record, client_order_id)
        updated = self._store.put(updated)
        return updated

    def acknowledge(self, record: TradeRecord, client_order_id: str) -> TradeRecord:
        """Record a broker acknowledgement for one order (LEAN ``SUBMITTED``).

        Faster than waiting for the next reconciliation cycle to adopt it, and
        the same transition either way.
        """
        order = record.orders.get(client_order_id)
        if order is None or order.dispatch not in (
            DispatchState.INTENT_RECORDED,
            DispatchState.SEND_FENCED,
        ):
            return record
        updated = mark_acknowledged(record, client_order_id)
        updated = self._store.put(updated)
        return updated

    def adopt_broker_evidence(self, record: TradeRecord, broker: BrokerView) -> TradeRecord:
        """Promote dispatched orders the broker confirms are working.

        This is what closes the ambiguous window: an order we merely attempted
        becomes ACKNOWLEDGED the moment the broker shows it, and only then does
        it count as working protection.
        """
        updated = record
        for order in broker.orders_owned_by(self._identity):
            local = updated.orders.get(order.client_order_id)
            if local is None or not order.is_open:
                continue
            if local.dispatch in (DispatchState.INTENT_RECORDED, DispatchState.SEND_FENCED):
                updated = mark_acknowledged(updated, order.client_order_id)
        if updated is not record:
            updated = self._store.put(updated)
        return updated

    # -- Entry -------------------------------------------------------------

    def assert_eligible_to_arm(self, broker: BrokerView) -> None:
        """Refuse to arm while anything is working on the Phase 2 symbol.

        Raises:
            ReconciliationError: if the symbol has a position, or ANY open order
                from any source.
        """
        held = broker.position_quantity(PHASE2_SYMBOL)
        if held != 0:
            raise ReconciliationError(
                f"Existing {PHASE2_SYMBOL} position ({held}) found before arming. Not ours to "
                "assume, and not liquidating it. Resolve manually."
            )
        assert_symbol_has_no_open_orders(broker, PHASE2_SYMBOL, self._identity)

    def begin_entry(self, record: TradeRecord) -> PendingOrder:
        """Write-ahead-record the single entry order, then hand it back to dispatch."""
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
        pending = self._store.put(pending)
        return PendingOrder(request=self._entry_request(), record=pending)

    def _entry_request(self) -> OrderRequest:
        return OrderRequest(
            client_order_id=self._identity.entry_order_id,
            symbol=PHASE2_SYMBOL,
            side=OrderSide.BUY,
            quantity=PHASE2_QUANTITY,
            order_type=OrderType.MARKET,
            role=OrderRole.ENTRY,
        )

    # -- Fills and rejections ----------------------------------------------

    def apply_entry_fill_and_prepare_protection(
        self,
        record: TradeRecord,
        *,
        client_order_id: str,
        fill_id: str,
        fill_quantity: int,
        fill_price: Decimal,
    ) -> tuple[TradeRecord, PendingOrder | None]:
        """Record an ENTRY fill and create its protective intent in ONE durable write.

        These were two writes. A crash between them left a durable state with an
        open long and **no protective order at all** -- which recovery could not
        even see, because it inspects existing orders. The long could stay naked
        indefinitely.

        Building the whole record in memory and persisting once removes that
        state entirely: after an entry fill is processed there is no durable
        moment where ``open_long_quantity > 0`` and no protective intent exists.

        The stop price is derived from the **actual fill price** and persisted as
        part of the protective intent, so recovery reconstructs the exact stop
        without asking the market for a fresh price.

        Returns:
            The persisted record, and the protective order to fence and dispatch
            (``None`` when there is nothing to protect or protection already
            exists).
        """
        filled = apply_fill(
            record,
            client_order_id=client_order_id,
            fill_id=fill_id,
            fill_quantity=fill_quantity,
        )
        if filled is record:  # duplicate fill event: a true no-op
            return record, None

        filled = self._advance_after_entry_fill(filled)

        quantity = required_protection_quantity(filled)
        if quantity <= 0 or filled.order_for_role(OrderRole.PROTECTIVE) is not None:
            filled = self._store.put(filled)
            return filled, None

        stop_price = protective_stop_price(fill_price)
        prepared = record_order_intent(
            filled,
            client_order_id=self._identity.protective_order_id,
            role=OrderRole.PROTECTIVE,
            symbol=PHASE2_SYMBOL,
            side="SELL",
            quantity=quantity,
            stop_price=str(stop_price),
        )
        prepared = replace(
            prepared, state=transition(prepared.state, TradeState.PROTECTION_SUBMITTED)
        )

        # THE atomic write: entry fill, lifecycle, protective intent and durable
        # stop price all land together or not at all.
        prepared = self._store.put(prepared)

        return prepared, PendingOrder(
            request=self._protective_request(quantity, stop_price), record=prepared
        )

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

        updated = self._store.put(updated)
        return updated

    def on_order_rejected(self, record: TradeRecord, client_order_id: str) -> TradeRecord:
        """Handle ``OrderStatus.INVALID`` on one of our orders.

        A rejected PROTECTIVE or EXIT order while a long is open is the
        highest-severity Phase 2 condition. It is never answered with another
        ENTRY.

        Raises:
            UnprotectedPositionError: if a long is exposed by the rejection.
        """
        updated = mark_rejected(record, client_order_id)
        updated = self._store.put(updated)

        order = updated.orders[client_order_id]
        if order.role is OrderRole.ENTRY:
            # No retry, ever. Latch the lifecycle so nothing downstream proceeds.
            return self.fail(
                updated,
                f"ENTRY {client_order_id} was REJECTED by the broker (OrderStatus.INVALID). "
                "Phase 2 never answers a rejection with a second entry.",
            )
        if updated.open_long_quantity > 0:
            return self._fail_unprotected(
                updated,
                f"{order.role.value} order {client_order_id} was REJECTED by the broker "
                "(OrderStatus.INVALID).",
            )
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

        Returns ``None`` when nothing should be dispatched: zero filled, or
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
            stop_price=str(stop_price),
        )
        pending = replace(pending, state=transition(pending.state, TradeState.PROTECTION_SUBMITTED))
        pending = self._store.put(pending)
        return PendingOrder(request=self._protective_request(quantity, stop_price), record=pending)

    def _protective_request(self, quantity: int, stop_price: Decimal) -> OrderRequest:
        return OrderRequest(
            client_order_id=self._identity.protective_order_id,
            symbol=PHASE2_SYMBOL,
            side=OrderSide.SELL,
            quantity=quantity,
            order_type=OrderType.STOP_MARKET,
            role=OrderRole.PROTECTIVE,
            stop_price=stop_price,
        )

    def confirm_protection(self, record: TradeRecord, broker: BrokerView) -> TradeRecord:
        """Promote to PROTECTED only once the broker confirms the working stop."""
        assert_protected(record, self._identity, broker)
        if record.state is not TradeState.PROTECTION_SUBMITTED:
            return record
        updated = replace(record, state=transition(record.state, TradeState.PROTECTED))
        updated = self._store.put(updated)
        return updated

    # -- Exit --------------------------------------------------------------

    def request_exit(self, record: TradeRecord) -> TradeRecord:
        """Move to EXIT_REQUESTED and persist."""
        if record.state is TradeState.EXIT_REQUESTED:
            return record
        updated = replace(record, state=transition(record.state, TradeState.EXIT_REQUESTED))
        updated = self._store.put(updated)
        return updated

    def begin_protection_cancel(self, record: TradeRecord) -> tuple[TradeRecord, bool]:
        """Decide whether a broker cancel should be issued, exactly once.

        Returns ``(record, should_dispatch_cancel)``. Once a cancellation has
        been requested, further cycles return ``False`` -- repeating the request
        every cycle would defeat the durable distinction and spam the broker.
        """
        protective = record.order_for_role(OrderRole.PROTECTIVE)
        if protective is None:
            return record, False
        if protective.cancel_requested:
            return record, False  # already asked; awaiting CANCELED confirmation
        updated = request_cancel(record, protective.client_order_id)
        updated = self._store.put(updated)
        return updated, True

    def on_order_cancelled(self, record: TradeRecord, client_order_id: str) -> TradeRecord:
        """Handle a broker-CONFIRMED cancellation, with role-aware consequences.

        Not all cancellations mean the same thing, and treating them alike is how
        a position quietly loses its protection.

        PROTECTIVE
            Expected **only** when we asked for it. An unrequested cancellation
            means protection vanished underneath an open position.
        ENTRY
            Never retried. The execution is finished.
        EXIT
            Cancelled while a long remains means the position is bare, because
            protection was already removed to permit the close.

        Raises:
            UnprotectedPositionError: whenever the cancellation leaves an open
                long with no broker-confirmed protection.
        """
        order = record.orders.get(client_order_id)
        if order is None:
            return record  # not ours
        if order.dispatch is DispatchState.CANCELLED:
            return record  # already applied

        was_requested = order.cancel_requested
        updated = self._store.put(confirm_cancel(record, client_order_id))

        if order.role is OrderRole.PROTECTIVE:
            if was_requested:
                return updated  # the controlled exit sequence; carry on
            return self._fail_unprotected(
                updated,
                f"PROTECTIVE order {client_order_id} was CANCELED by the broker without "
                "KalpaMani requesting it; protection disappeared underneath the position.",
            )

        if order.role is OrderRole.ENTRY:
            if updated.open_long_quantity > 0:
                return self._fail_unprotected(
                    updated, f"ENTRY {client_order_id} was CANCELED while a long is held."
                )
            return self.fail(
                updated,
                f"ENTRY {client_order_id} was CANCELED by the broker. Phase 2 never retries an "
                "entry, so this execution is finished.",
            )

        # EXIT: protection was already removed to permit the close.
        if updated.open_long_quantity > 0:
            return self._fail_unprotected(
                updated,
                f"EXIT {client_order_id} was CANCELED while {updated.open_long_quantity} "
                f"{updated.symbol} is still held, and protection was already removed.",
            )
        return updated

    def _fail_unprotected(self, record: TradeRecord, reason: str) -> TradeRecord:
        """Persist FAILED *first*, then surface the unprotected position.

        Ordering matters. Raising before persisting would leave durable state
        that still looks healthy, and a restart would resume normal progression
        on a position with no protection.
        """
        failed = self.fail(record, reason)
        raise UnprotectedPositionError(
            f"UNPROTECTED POSITION: {reason} Long={failed.open_long_quantity} "
            f"{failed.symbol}, broker-confirmed protection=0. Lifecycle latched FAILED. "
            "Do NOT submit another entry; protect or close the position manually."
        )

    def begin_exit(self, record: TradeRecord, broker: BrokerView) -> PendingOrder:
        """Write-ahead-record the closing SELL, once protection is provably gone."""
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
        pending = self._store.put(pending)
        return PendingOrder(
            request=self._exit_request(plan.exit_quantity, plan.symbol), record=pending
        )

    def _exit_request(self, quantity: int, symbol: str) -> OrderRequest:
        return OrderRequest(
            client_order_id=self._identity.exit_order_id,
            symbol=symbol,
            side=OrderSide.SELL,
            quantity=quantity,
            order_type=OrderType.MARKET,
            role=OrderRole.EXIT,
        )

    # -- Reconciliation and recovery ---------------------------------------

    def reconcile(self, record: TradeRecord, broker: BrokerView) -> TradeRecord:
        """Adopt broker evidence, then compare. Raises on disagreement."""
        adopted = self.adopt_broker_evidence(record, broker)
        reconcile(adopted, self._identity, broker)
        return adopted

    def assess_recovery(self, record: TradeRecord, broker: BrokerView) -> RecoveryPlan:
        """Classify every order's dispatch gap and decide what is safe to do.

        Case A -- **unfenced**: the intent was recorded but the send fence was
        never acquired, so the dispatcher never committed to contacting the
        broker. This is the one case where "the broker does not have it" is a
        defensible claim, and re-dispatch is provably not a duplicate. For a
        PROTECTIVE or EXIT covering an open long it is also the only way out of
        an unprotected position, so it is done. For an ENTRY it is not: nothing
        is at risk, and re-entering is the decision we least want a machine to
        make unattended.

        Case B -- **fenced, unconfirmed**: the fence is held and the broker has
        confirmed nothing. A send may have occurred. Absence from the open-order
        list is *not* evidence it never arrived -- it may have filled, been
        cancelled, or simply not be visible yet. Never resend; fail closed for
        human reconciliation.

        Positive broker evidence is adopted first, which is what resolves the
        common case without human involvement.

        Raises:
            ReconciliationError: on any fenced-but-unconfirmed order, or an
                unfenced ENTRY.
        """
        adopted = self.adopt_broker_evidence(record, broker)
        notes: list[str] = []
        redispatch: list[PendingOrder] = []

        fenced = adopted.fenced_unconfirmed_orders()
        if fenced:
            ids = ", ".join(f"{o.role.value}:{o.client_order_id}" for o in fenced)
            raise ReconciliationError(
                f"Send fence held with no broker confirmation for {ids}. A send MAY have "
                "occurred -- a crash before the broker call and a crash after it are "
                "indistinguishable from here, and absence from the open-order list is not "
                "evidence the order never arrived. Refusing to resend: reconcile against the "
                "broker's order history by hand."
            )

        if adopted.open_long_quantity > 0 and adopted.order_for_role(OrderRole.PROTECTIVE) is None:
            raise ReconciliationError(
                f"NAKED LONG: {adopted.open_long_quantity} {adopted.symbol} is held with no "
                "protective intent of any kind on record. The entry fill and its protection "
                "are written atomically, so this state should be unreachable; its presence "
                "means durable state cannot be trusted. Protect or close the position by "
                "hand before restarting."
            )

        for order in adopted.unfenced_orders():
            if order.role is OrderRole.ENTRY:
                raise ReconciliationError(
                    f"ENTRY {order.client_order_id} was recorded but never fenced, so it was "
                    "never sent. No position is at risk, and re-entering is not a decision to "
                    "take unattended. Resolve manually."
                )
            if adopted.open_long_quantity <= 0:
                notes.append(f"{order.role.value} intent is moot: no open long")
                continue
            if order.role is OrderRole.PROTECTIVE:
                notes.append("PROTECTIVE intent never fenced (never sent): UNPROTECTED")
                redispatch.append(
                    PendingOrder(
                        request=self._protective_request(
                            order.quantity, Decimal(str(order.stop_price))
                        ),
                        record=adopted,
                    )
                )
            elif order.role is OrderRole.EXIT:
                notes.append("EXIT intent never fenced (never sent): position still open")
                redispatch.append(
                    PendingOrder(
                        request=self._exit_request(order.quantity, order.symbol),
                        record=adopted,
                    )
                )

        return RecoveryPlan(record=adopted, redispatch=tuple(redispatch), notes=tuple(notes))

    def finalize(self, record: TradeRecord, broker: BrokerView) -> TradeRecord:
        """Reach RECONCILED only once the broker confirms flat."""
        assert_flat(record, self._identity, broker)
        if record.state is TradeState.RECONCILED:
            return record
        updated = replace(record, state=transition(record.state, TradeState.RECONCILED))
        updated = self._store.put(updated)
        return updated

    # -- Failure -----------------------------------------------------------

    def fail(self, record: TradeRecord, reason: str) -> TradeRecord:
        """Latch the lifecycle to FAILED and persist the reason."""
        if record.state is TradeState.FAILED:
            return record
        updated = replace(
            record, state=transition(record.state, TradeState.FAILED), failure_reason=reason
        )
        updated = self._store.put(updated)
        return updated


__all__ = ["PendingOrder", "Phase2Coordinator", "RecoveryPlan"]
