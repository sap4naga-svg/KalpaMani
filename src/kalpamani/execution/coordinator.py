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

from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

from kalpamani.broker.orders import OrderRequest, OrderSide, OrderType
from kalpamani.common.capital import StrategyCapital
from kalpamani.execution.envelope import (
    MANUAL_CLOSE_REASON,
    PHASE2_QUANTITY,
    PHASE2_RUN_1_NATURAL_KEY,
    PHASE2_SYMBOL,
    ExecutionArmRequest,
    assert_arm_not_reusable,
    authorize_trade_intent,
    protective_stop_price,
)
from kalpamani.execution.identity import OrderRole, TradeIdentity
from kalpamani.execution.lifecycle import TERMINAL_STATES, TradeState, transition
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
    SessionVerificationError,
    arm_receipt_paths,
    assert_arm_available,
    assert_arm_matches_record,
    load_session_evidence,
    verify_paper_session,
    write_arm_receipt,
)
from kalpamani.execution.state_store import (
    DispatchState,
    ResolutionKind,
    StaleWriteError,
    TradeRecord,
    TradeStateStore,
    apply_fill,
    confirm_cancel,
    fence_dispatch,
    mark_acknowledged,
    mark_rejected,
    record_broker_ids,
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
        session_provider: Callable[[], BrokerSessionEvidence] = load_session_evidence,
    ) -> None:
        self._store = store
        self._identity = identity
        # Receipts are scoped to THIS run, so a consumed receipt from a failed
        # run survives as evidence without being read as this run's arm.
        self._receipt_paths = arm_receipt_paths(
            storage_root,
            project_root,
            identity.trade_intent_id,
            legacy=identity.natural_key == PHASE2_RUN_1_NATURAL_KEY,
        )
        #: Reads the CURRENT brokerage session from LEAN's own deployment
        #: configuration. Injected so tests can present a different session --
        #: a LIVE account, or a second paper account -- and prove that nothing
        #: reaches the broker. It defaults to the real reader, so production
        #: cannot accidentally get a permissive stub.
        self._session_provider = session_provider

    @property
    def identity(self) -> TradeIdentity:
        return self._identity

    @property
    def receipt_paths(self) -> tuple[Path, ...]:
        return self._receipt_paths

    # -- Recovery ----------------------------------------------------------

    def load(self) -> TradeRecord | None:
        """Load the trade record, failing closed on any contradictory arm evidence.

        Three separate checks, because each catches something the others cannot:

        * receipts must agree with **each other** (a partial write, a stale mount);
        * a consumed receipt must not exist with **no** trade record (lost state
          that would otherwise look like a virgin first run);
        * receipts must agree with the **record** -- same intent, same account
          binding, same consumed flag. Two receipts that agree with each other
          but describe a different trade are still contradictory evidence.
        """
        record = self._store.get(self._identity.trade_intent_id)
        assert_arm_available(self._receipt_paths, trade_state_present=record is not None)
        if record is not None:
            assert_arm_matches_record(
                self._receipt_paths,
                trade_intent_id=record.trade_intent_id,
                account_fingerprint_value=record.account_fingerprint,
                arm_consumed=record.arm_consumed,
            )
            assert_arm_not_reusable(record)
        return record

    def any_records_exist(self) -> bool:
        """Whether ANY certification run has durable state. Used by halt clearance."""
        return bool(self._store.all_records())

    # -- Session binding ---------------------------------------------------

    def current_session(self) -> BrokerSessionEvidence:
        """Read the CURRENT brokerage session from the deployment configuration.

        The single source callers use, so nothing can quietly consult a
        different one. There is no fallback: if it cannot be read, it raises.
        """
        return self._session_provider()

    def assert_session_binding(self, record: TradeRecord) -> BrokerSessionEvidence:
        """Prove the CURRENT session is the same PAPER account this trade was armed on.

        Verifying the session once, at arming time, is not enough. Arming happens
        only when no trade exists; every later cycle -- recovery, reconciliation,
        a protective re-dispatch, an exit -- runs against whatever session the
        process is connected to *now*. Without this, the sequence is:

            paper account A fills the entry
            the protective intent is durable but unfenced
            the process restarts against account B
            recovery sees a local unfenced intent and dispatches it into B

        A local record knows nothing about B, so nothing else would stop it.

        Returns:
            The verified evidence, so callers can log it without reading it twice.

        Raises:
            SessionVerificationError: if the record carries no binding, if the
                session is LIVE or unclassifiable, or if it is a different
                account from the one armed.
        """
        evidence = self.current_session()
        if not record.account_fingerprint:
            raise SessionVerificationError(
                f"Trade {record.trade_intent_id} carries no account binding, so the connected "
                "session cannot be proven to be the account it was armed against. Failing "
                "closed: an unbound record must never reach a broker."
            )
        verify_paper_session(evidence, expected_fingerprint=record.account_fingerprint)
        return evidence

    def _guard_broker_input(self, record: TradeRecord) -> None:
        """Refuse to mutate an account-bound record from a foreign session.

        Every durable write driven by broker input goes through here. An order
        event carries a tag, and a tag proves only that *some* session issued an
        order with that identifier -- it says nothing about which account the
        event arrived from. Without this, an event delivered while connected to a
        second paper account (or a live one) would be applied to a trade that
        belongs to a different account entirely, and the fills of one account
        would silently become the lifecycle of another.

        Raises:
            SessionVerificationError: if the session is not the armed account.
        """
        self.assert_session_binding(record)

    def _ledger_only(self, record: TradeRecord) -> bool:
        """Whether broker facts may still be recorded but the lifecycle may not move.

        ``FAILED`` and ``RECONCILED`` are terminal, and correctly so -- a failed
        lifecycle must never resume. But broker facts keep arriving after a
        failure: an order dispatched before the halt can still fill, and that
        fill is true whatever the lifecycle concluded. Attempting the normal
        transition would raise ``LifecycleError``, and the fill would never
        become durable -- leaving a real position that this process cannot see.

        So in a terminal state the record still accepts facts (fills,
        acknowledgements, cancellations, rejections) and simply does not
        transition. Terminal stays terminal.
        """
        return record.state in TERMINAL_STATES

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
        identity, record = authorize_trade_intent(
            request, self._store, identity=self._identity, capital=capital
        )
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
        """Verify the session, then acquire and persist the SEND FENCE.

        The last thing that runs before a broker call, and therefore the right
        place for the last check. Defence in depth: a verification performed
        several methods earlier proves the session was right *then*, and every
        order still has to pass through here.

        The order of operations is deliberate:

        1. re-read the CURRENT durable record -- not the caller's copy;
        2. refuse a stale caller (it is holding a view that has since moved on);
        3. prove the connected session is the armed PAPER account;
        4. persist the fence;
        5. *then* the caller contacts the broker.

        Step 4 stays before the broker call. That is the round-4 fence and it is
        not negotiable: writing it afterwards would leave ``INTENT_RECORDED``
        after a successful send, and recovery would issue a second order.

        Raises:
            SessionVerificationError: if the session is not the armed account.
            StaleWriteError: if the caller's record is behind durable state.
        """
        stored = self._store.require(record.trade_intent_id)
        if stored.revision > record.revision:
            raise StaleWriteError(
                f"Refusing to dispatch {client_order_id} from a stale record: durable revision "
                f"{stored.revision} is ahead of the caller's {record.revision}. The caller is "
                "acting on a view of the trade that has since moved on. Re-read and retry."
            )
        self.assert_session_binding(stored)
        return self._store.put(fence_dispatch(stored, client_order_id))

    def acknowledge(
        self,
        record: TradeRecord,
        client_order_id: str,
        *,
        broker_order_ids: tuple[str, ...] = (),
    ) -> TradeRecord:
        """Record a broker acknowledgement for one order (LEAN ``SUBMITTED``).

        Faster than waiting for the next reconciliation cycle to adopt it, and
        the same transition either way.
        """
        self._guard_broker_input(record)
        order = record.orders.get(client_order_id)
        if order is None or order.dispatch not in (
            DispatchState.INTENT_RECORDED,
            DispatchState.SEND_FENCED,
        ):
            return record
        updated = mark_acknowledged(record, client_order_id, broker_order_ids=broker_order_ids)
        updated = self._store.put(updated)
        return updated

    def adopt_broker_evidence(self, record: TradeRecord, broker: BrokerView) -> TradeRecord:
        """Promote dispatched orders the broker confirms are working.

        This is what closes the ambiguous window: an order we merely attempted
        becomes ACKNOWLEDGED the moment the broker shows it, and only then does
        it count as working protection.
        """
        self._guard_broker_input(record)
        updated = record
        for order in broker.orders_owned_by(self._identity):
            local = updated.orders.get(order.client_order_id)
            if local is None or not order.is_open:
                continue
            if local.dispatch not in (DispatchState.INTENT_RECORDED, DispatchState.SEND_FENCED):
                # Already confirmed. Still adopt identity if it was not captured.
                updated = record_broker_ids(updated, order.client_order_id, order.broker_order_ids)
                continue
            # Capture broker-native identity from positive broker evidence.
            # This is the value that survives a restart, and the first
            # certification run stranded a position precisely because it was
            # never written down.
            updated = mark_acknowledged(
                updated, order.client_order_id, broker_order_ids=order.broker_order_ids
            )
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

    # -- Manual resolution -------------------------------------------------

    def resolve_manually(self, record: TradeRecord, broker: BrokerView) -> TradeRecord:
        """Record that a HUMAN closed the broker position after a failed run.

        This never touches the broker. It writes down a fact a human has already
        established, and only once that fact is re-verified here: the same PAPER
        account, no position, and no working order on the symbol from any source.

        The trade becomes terminal **FAILED**, not RECONCILED. The automated
        lifecycle did not close this position and saying otherwise would turn the
        durable record of a failed certification into a false one. Everything the
        run produced -- the entry fill, the protective order, the broker
        evidence, the failure history, the revisions, the identifiers -- is left
        exactly as it was.

        Raises:
            SessionVerificationError: if this is not the armed account.
            ReconciliationError: if the broker is not actually flat for the symbol.
        """
        self.assert_session_binding(record)
        try:
            self.assert_eligible_to_arm(broker)
        except ReconciliationError as exc:
            raise ReconciliationError(
                "Refusing to record a manual resolution: the broker is NOT flat for "
                f"{PHASE2_SYMBOL}. {exc} A manual close is recorded only after it has "
                "actually happened."
            ) from exc

        state = record.state
        if state is not TradeState.FAILED:
            state = transition(state, TradeState.FAILED)
        updated = replace(
            record,
            state=state,
            failure_reason=record.failure_reason or MANUAL_CLOSE_REASON,
            resolution=ResolutionKind.MANUAL_BROKER_CLOSE,
            resolution_reason=MANUAL_CLOSE_REASON,
        )
        return self._store.put(updated)

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
        self._guard_broker_input(record)
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
        if not self._ledger_only(prepared):
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
        self._guard_broker_input(record)
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
        self._guard_broker_input(record)
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
        if self._ledger_only(record):
            return record  # fact recorded; a terminal lifecycle does not resume
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
        if self._ledger_only(record):
            return record  # fact recorded; a terminal lifecycle does not resume
        if record.open_long_quantity > 0:
            return record
        return replace(record, state=transition(record.state, TradeState.CLOSED))

    # -- Protection --------------------------------------------------------

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
        self._guard_broker_input(record)
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
        self._guard_broker_input(record)
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

        Ordering
        --------
        Recovery is the only path that can put an order on the wire without a
        human, so the safety checks run *before* it concludes anything:

            prove the same PAPER account
                -> adopt positive broker evidence
                -> reconcile position and protection against the broker
                -> only then decide what may be re-dispatched

        Reconciling last would have meant deciding to re-send while local and
        broker views still disagreed -- exactly the state in which "the broker
        does not have it" is not a claim anyone can make.

        Raises:
            SessionVerificationError: if the session is not the armed account.
            ReconciliationError: on any fenced-but-unconfirmed order, an unfenced
                ENTRY, or any disagreement with broker truth.
        """
        # STEP 1. The account, before anything is read from broker state.
        self.assert_session_binding(record)

        # STEP 2-3. Broker truth, with positive evidence adopted.
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

        # STEP 4. Reconcile BEFORE deciding anything may be re-sent. A
        # contradictory position is not a state to act from: re-dispatching a
        # stop for a position the broker does not show could sell what we do not
        # hold, and that is a short.
        reconcile(adopted, self._identity, broker)

        # STEP 5. Only now.
        broker_long = broker.position_quantity(adopted.symbol)
        broker_protective = broker.open_protective_quantity(self._identity)

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
            if adopted.open_long_quantity != broker_long:
                raise ReconciliationError(
                    f"Refusing to re-dispatch {order.role.value} {order.client_order_id}: local "
                    f"long {adopted.open_long_quantity} does not match the broker position "
                    f"{broker_long} for {adopted.symbol}. A SELL sized from a position the "
                    "broker does not confirm could open a short."
                )
            if broker_protective > 0:
                raise ReconciliationError(
                    f"Refusing to re-dispatch {order.role.value} {order.client_order_id}: the "
                    f"broker already shows {broker_protective} unit(s) of working protection "
                    "for this execution. A second SELL alongside it is a duplicate."
                )
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
