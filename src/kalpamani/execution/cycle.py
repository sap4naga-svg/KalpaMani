"""The Phase 2 cycle orchestration (ADR-0004 §16).

Every decision Phase 2 makes lives here: when to arm, what recovery may
re-dispatch, how a broker event is applied, when to halt. The LEAN algorithm
supplies broker I/O through :class:`BrokerPort` and nothing else.

Why this is not in ``main.py``
------------------------------
It was, and that was the problem. ``main.py`` cannot be imported outside a LEAN
container, so its orchestration could only ever be checked by reading it. Tests
exercised the coordinator directly and re-created the sequence alongside it,
which is how a review found an integration test performing transitions
production never did: the tests passed while production skipped steps.

With the sequence here, a test drives **the same code the container runs**. The
only thing left in ``main.py`` is translation -- LEAN types in, ``BrokerPort``
calls out.

Three separate notions of "stop"
--------------------------------
Conflating these is how a system either resumes when it should not, or goes
blind when it should not:

``TradeState.FAILED``
    The *lifecycle* verdict for this trade. Terminal, durable, never resumes.
``OperationalHalt``
    Whether this *deployment* may take new normal action. Durable when the cause
    is a safety violation (see :mod:`kalpamani.execution.halt`).
broker fact ingestion
    **Never** stops. An order already at the broker keeps acknowledging, filling,
    cancelling and rejecting after a halt, and each of those is true whatever we
    have concluded. Dropping them would not stop any of it happening -- it would
    only stop us knowing.

The one action permitted while halted is protecting a position that has actually
filled. It reduces risk rather than taking it, and it is guarded: the account is
re-proven at the send fence, and broker truth must reconcile first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from kalpamani.broker.orders import OrderRequest
from kalpamani.common.capital import DEFAULT_STRATEGY_CAPITAL_USD, StrategyCapital
from kalpamani.common.settings import Settings
from kalpamani.execution.coordinator import PendingOrder, Phase2Coordinator
from kalpamani.execution.envelope import (
    PHASE2_QUANTITY,
    PHASE2_SYMBOL,
    ExecutionArmRequest,
)
from kalpamani.execution.halt import (
    HaltKind,
    HaltStore,
    OperationalHalt,
    classify_halt,
)
from kalpamani.execution.identity import is_valid_client_order_id
from kalpamani.execution.lifecycle import TradeState
from kalpamani.execution.reconciliation import BrokerView
from kalpamani.execution.session import SessionVerificationError, verify_paper_session
from kalpamani.execution.state_store import TradeRecord
from kalpamani.execution.trading_window import (
    TradingWindowError,
    assert_within_certification_window,
)


class EventStatus(StrEnum):
    """A LEAN ``OrderStatus``, already classified by the adapter.

    The adapter compares LEAN's enum members exactly -- LEAN defines **both**
    ``CANCEL_PENDING`` and ``CANCELED``, and a substring match on the status name
    would treat a pending cancellation as a confirmed one, letting the close
    proceed while the stop was still live.
    """

    SUBMITTED = "SUBMITTED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELED = "CANCELED"
    INVALID = "INVALID"
    #: A fill event carrying a non-zero filled quantity.
    FILL = "FILL"
    #: Anything else, including a zero-quantity event. Recorded, never acted on.
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class OrderEventFacts:
    """One broker event, normalised. No LEAN type crosses this boundary."""

    client_order_id: str
    status: EventStatus
    fill_quantity: int = 0
    fill_price: Decimal = Decimal(0)
    #: Stable per-order event identity, so repeated delivery is a true no-op.
    fill_id: str = ""


class BrokerPort(Protocol):
    """Broker I/O, as the LEAN adapter provides it."""

    def view(self) -> BrokerView:
        """Broker truth: positions and every open order, ours and foreign."""
        ...

    def submit(self, request: OrderRequest) -> None:
        """Place the order. Called only after its send fence is durable."""
        ...

    def cancel(self, client_order_id: str) -> None:
        """Ask the broker to cancel one of our orders. Never a foreign order."""
        ...

    def reference_price(self) -> Decimal:
        """Latest observed price for the Phase 2 symbol."""
        ...

    def broker_equity_usd(self) -> Decimal:
        """Broker-reported equity. Observed for reconciliation; never sizes anything."""
        ...

    def regular_session_open(self) -> bool:
        """Whether the exchange's REGULAR session is open, excluding extended hours."""
        ...

    def exchange_local_time(self) -> time:
        """Exchange-local clock time."""
        ...

    def minutes_to_regular_close(self) -> float | None:
        """Minutes until today's ACTUAL regular close, or ``None`` if unknown."""
        ...

    def log(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...


class Phase2Cycle:
    """Drives one Phase 2 certification: arm, protect, reconcile, exit, flat."""

    def __init__(
        self,
        coordinator: Phase2Coordinator,
        port: BrokerPort,
        halt_store: HaltStore,
        *,
        settings: Settings,
        test_mode: bool = False,
        arm_flag: bool = False,
        confirmation: str = "",
        exit_requested: bool = False,
        armed_fingerprint: str = "",
        capital: StrategyCapital | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._port = port
        self._halt_store = halt_store
        self._settings = settings
        self._test_mode = test_mode
        self._arm_flag = arm_flag
        self._confirmation = confirmation
        self._exit_requested = exit_requested
        self._armed_fingerprint = armed_fingerprint
        self._capital = capital or StrategyCapital()

        #: A durable halt is read at construction, so a restart does NOT resume.
        self._halt: OperationalHalt | None = halt_store.get()
        self._session_logged = False
        self._recovery_logged = False
        self._entries_submitted_this_session = 0

    # -- Status ------------------------------------------------------------

    @property
    def halted(self) -> bool:
        return self._halt is not None

    @property
    def halt(self) -> OperationalHalt | None:
        return self._halt

    @property
    def entries_submitted_this_session(self) -> int:
        return self._entries_submitted_this_session

    def start(self) -> None:
        """Report a halt recovered from durable state, before anything runs."""
        if self._halt is None:
            return
        self._port.error(
            f"[PHASE2-HALT] a durable operational halt is in force: {self._halt.reason}"
        )
        self._port.error(
            "[PHASE2-HALT] normal progression does NOT resume merely because the process "
            "restarted. Reconcile against the broker by hand, then clear it deliberately "
            "with `scripts/phase2_arm.py --clear-halt`."
        )

    # -- The reconciliation cycle -------------------------------------------

    def on_cycle(self) -> None:
        """Reconcile first, always. Only then consider acting."""
        if self.halted:
            return
        try:
            record = self._coordinator.load()

            if record is None:
                broker = self._port.view()
                self._log_state(broker, "no-trade")
                self._maybe_arm(broker)
                return

            # An existing trade is bound to the account it was ARMED against.
            # Re-prove that binding against the session connected RIGHT NOW,
            # before any broker state is inspected or acted upon.
            evidence = self._coordinator.assert_session_binding(record)
            if not self._session_logged:
                self._session_logged = True
                self._port.log(
                    f"[SESSION-BOUND] same PAPER account as armed: {evidence.describe()}"
                )

            broker = self._port.view()

            if record.state is TradeState.FAILED:
                # The durable record of this is TradeState.FAILED itself, which
                # halts every future cycle on its own. A second durable halt
                # would only add a manual chore for a condition that is already
                # permanent, so this halt is session-scoped.
                self._raise_halt(
                    f"durable lifecycle is FAILED: {record.failure_reason or '(no reason)'}. "
                    "Refusing to resume normal progression.",
                    kind=HaltKind.SESSION,
                )
                return

            if not self._recovery_logged:
                self._recovery_logged = True
                self._log_recovery(record)
                # Recovery verifies the account, adopts broker evidence and
                # reconciles BEFORE it concludes anything may be re-sent.
                plan = self._coordinator.assess_recovery(record, broker)
                record = plan.record
                self._port.log(f"[RECOVERY] dispatch assessment: {plan.describe()}")
                if plan.redispatch:
                    for pending in plan.redispatch:
                        self._port.error(
                            f"[RECOVERY] {pending.request.role.value} intent was never FENCED, "
                            "so it was never sent; re-dispatch is provably not a duplicate"
                        )
                        record = self._dispatch(pending)
                    # END THE CYCLE HERE. `broker` was captured BEFORE these
                    # orders existed, so confirming them against it would report
                    # a stop we just sent as missing -- a false UNPROTECTED
                    # POSITION, and a halt for a system that is working. The next
                    # cycle takes a fresh snapshot; the acknowledgement also
                    # arrives as its own event.
                    self._port.log(
                        "[RECOVERY] re-dispatched; ending this cycle. Confirmation waits for a "
                        "FRESH broker snapshot -- this one predates the order."
                    )
                    return

            self._log_state(broker, record.state.value)
            # reconcile() may adopt broker evidence and return a NEWER record
            # (SEND_FENCED -> ACKNOWLEDGED). Use the returned one.
            record = self._coordinator.reconcile(record, broker)
            self._port.log(f"[RECONCILE] {record.describe()}")
            self._progress(record, broker)
        except Exception as exc:
            self._raise_halt(f"{type(exc).__name__}: {exc}", error=exc)

    def _log_recovery(self, record: TradeRecord) -> None:
        self._port.log(f"[RECOVERY] recovered {record.describe()}")
        self._port.log(f"[RECOVERY] entry_orders_before_restart={record.entry_count}")
        self._port.log(
            f"[RECOVERY] entry_orders_submitted_this_session={self._entries_submitted_this_session}"
        )
        self._port.log("[IDEMPOTENCY-PASS] recovery adopts existing state; no entry replay")

    def _log_state(self, broker: BrokerView, context: str) -> None:
        self._port.log(
            f"[RECONCILE:{context}] spy_position={broker.position_quantity(PHASE2_SYMBOL)} "
            f"owned_open_orders={len(broker.orders_owned_by(self._coordinator.identity))} "
            f"broker_equity_usd={self._port.broker_equity_usd()} "
            f"strategy_capital_usd={DEFAULT_STRATEGY_CAPITAL_USD}"
        )

    # -- Arming -------------------------------------------------------------

    def _maybe_arm(self, broker: BrokerView) -> None:
        """Open the order path only if every gate passes. Otherwise stay read-only."""
        evidence = self._coordinator.current_session()

        if not (self._test_mode and self._arm_flag):
            # Even disarmed, prove and report the session. This is exactly what
            # the disarmed dry run is for.
            verify_paper_session(evidence)
            self._port.log(f"[RECONCILE] session verified PAPER: {evidence.describe()}")
            self._port.log(f"[RECONCILE] execution window eligible: {self._window_eligible()}")
            return

        # No position AND no working order on the symbol, from ANY source. A
        # foreign SPY order would make ownership of the resulting position
        # ambiguous, at which point our stop could sell what we do not hold.
        self._coordinator.assert_eligible_to_arm(broker)

        # The armed account must BE the deployed account. The binding is
        # REQUIRED: an absent one aborts rather than disabling the check.
        if not self._armed_fingerprint:
            self._raise_halt(
                "The arm carries no account binding, so it cannot be verified against the "
                "deployment. Re-arm with scripts/phase2_arm.py.",
                kind=HaltKind.MANUAL_CLEARANCE_REQUIRED,
            )
            return
        verify_paper_session(evidence, expected_fingerprint=self._armed_fingerprint)
        self._port.log(f"[PHASE2-ARM] session verified PAPER: {evidence.describe()}")

        # Regular hours, enforced. Checked BEFORE authorize(), so an ineligible
        # time never consumes the one-time arm -- a mistimed launch costs
        # nothing and simply stays read-only.
        if not self._window_eligible():
            return

        price = self._port.reference_price()
        if price <= 0:
            self._port.log("[PHASE2-ARM] waiting for a valid SPY price before arming")
            return

        request = ExecutionArmRequest(
            confirmation=self._confirmation,
            settings=self._settings,
            session_evidence=evidence,
            symbol=PHASE2_SYMBOL,
            quantity=PHASE2_QUANTITY,
            reference_price=price,
            phase2_test_mode=self._test_mode,
            explicit_execution_arm=self._arm_flag,
        )
        record = self._coordinator.authorize(request, evidence, capital=self._capital)
        self._port.log("=" * 78)
        self._port.log(f"[TRADE-INTENT] authorized {record.describe()}")
        self._port.log(f"[TRADE-INTENT] reference_price={price} notional={request.notional_usd}")
        self._port.log("=" * 78)

        pending = self._coordinator.begin_entry(record)
        self._dispatch(pending)
        self._entries_submitted_this_session += 1

    def _window_eligible(self) -> bool:
        """Whether the exchange calendar AND the clock both permit an entry now.

        The exchange answers the calendar question -- holidays, half days, early
        closes -- because only it knows. The close is *derived*, never assumed:
        on a 13:00 half day the window shuts at 12:30 without anyone editing a
        constant.
        """
        try:
            assert_within_certification_window(
                self._port.exchange_local_time(),
                regular_session_open=self._port.regular_session_open(),
                minutes_to_close=self._port.minutes_to_regular_close(),
            )
        except TradingWindowError as exc:
            self._port.log(f"[PHASE2-ARM] entry not eligible: {exc}")
            return False
        return True

    # -- Broker events ------------------------------------------------------

    def on_order_event(self, facts: OrderEventFacts) -> None:
        """Apply one broker event. Deliberately NOT gated on the halt latch.

        A halt blocks new normal decisions. It must not make us blind: an order
        already on the wire can still acknowledge, fill, cancel or reject
        afterwards, and each of those is broker truth that has to be recorded.
        """
        tag = facts.client_order_id
        if not is_valid_client_order_id(tag) or not self._coordinator.identity.owns(tag):
            return  # not ours
        try:
            record = self._coordinator.load()
            if record is None:
                self._raise_halt(
                    f"Order event for {tag} with no durable trade record.",
                    kind=HaltKind.MANUAL_CLEARANCE_REQUIRED,
                )
                return

            # ACCOUNT-BIND INGESTION. A client order id proves only that *some*
            # session issued an order with that identifier; it says nothing
            # about which account this event arrived from. Applying it without
            # proving the account would let the fills of one account become the
            # lifecycle of another.
            try:
                self._coordinator.assert_session_binding(record)
            except SessionVerificationError as exc:
                self._port.error(f"[ACCOUNT-BINDING FAILURE] {exc}")
                self._port.error(
                    f"[ACCOUNT-BINDING FAILURE] event for {tag} was NOT applied to the trade "
                    "record. The lifecycle belongs to a different account. Reconcile both "
                    "accounts by hand."
                )
                self._raise_halt(
                    f"ACCOUNT-BINDING FAILURE while ingesting an event for {tag}.",
                    kind=HaltKind.MANUAL_CLEARANCE_REQUIRED,
                )
                return

            self._port.log(
                f"[ORDER-EVENT] order={tag} status={facts.status.value} qty={facts.fill_quantity}"
            )
            self._apply_event(record, facts)
        except Exception as exc:
            self._raise_halt(f"order-event handling failed: {type(exc).__name__}: {exc}", error=exc)

    def _apply_event(self, record: TradeRecord, facts: OrderEventFacts) -> None:
        tag = facts.client_order_id
        identity = self._coordinator.identity

        if facts.status is EventStatus.CANCEL_PENDING:
            self._port.log(
                f"[EXIT-REQUEST] {tag} CANCEL_PENDING -- NOT confirmation; still working"
            )
            return

        if facts.status is EventStatus.CANCELED:
            # Role-aware. An unrequested protective cancellation, a cancelled
            # ENTRY, and a cancelled EXIT over an open long each mean something
            # different. The coordinator persists FAILED before raising where
            # protection was lost.
            before = record.orders.get(tag)
            expected = bool(before and before.cancel_requested)
            record = self._coordinator.on_order_cancelled(record, tag)
            if expected:
                self._port.log(f"[EXIT-REQUEST] requested cancellation CONFIRMED for {tag}")
            else:
                self._raise_halt(
                    f"{tag} was CANCELED without KalpaMani requesting it. Lifecycle latched "
                    f"{record.state.value}.",
                    kind=HaltKind.MANUAL_CLEARANCE_REQUIRED,
                )
            return

        if facts.status is EventStatus.INVALID:
            # Raises UnprotectedPositionError when a long is exposed; for an
            # ENTRY it returns after latching FAILED. Either way the session
            # must stop.
            self._coordinator.on_order_rejected(record, tag)
            self._raise_halt(
                f"broker REJECTED {tag} (OrderStatus.INVALID). No retry, ever.",
                kind=HaltKind.MANUAL_CLEARANCE_REQUIRED,
            )
            return

        if facts.status is EventStatus.SUBMITTED:
            self._coordinator.acknowledge(record, tag)
            return

        if facts.status is not EventStatus.FILL or facts.fill_quantity <= 0:
            return

        quantity = abs(int(facts.fill_quantity))

        if tag == identity.entry_order_id:
            # ONE durable write: the entry fill, the lifecycle transition, the
            # protective intent and its stop price (from the ACTUAL fill price)
            # all land together. There is therefore no durable moment with an
            # open long and no protective intent.
            record, protection = self._coordinator.apply_entry_fill_and_prepare_protection(
                record,
                client_order_id=tag,
                fill_id=facts.fill_id,
                fill_quantity=quantity,
                fill_price=facts.fill_price,
            )
            self._port.log(
                f"[FILL] {tag} filled={record.filled_quantity} "
                f"long={record.open_long_quantity} price={facts.fill_price} "
                f"fill_id={facts.fill_id}"
            )
            if protection is None:
                self._port.log("[PROTECTION-SUBMIT] skipped: nothing to protect")
            else:
                self._port.log("[PROTECTION-SUBMIT] intent + stop price durable; fencing now")
                self._dispatch_protection(record, protection)
            return

        record = self._coordinator.on_fill(
            record, client_order_id=tag, fill_id=facts.fill_id, fill_quantity=quantity
        )
        self._port.log(
            f"[FILL] {tag} filled={record.filled_quantity} long={record.open_long_quantity} "
            f"price={facts.fill_price} fill_id={facts.fill_id}"
        )
        if tag == identity.protective_order_id:
            self._port.log("[EXIT-FILL] protective stop filled; the long is closed by the stop")

    # -- Dispatch -----------------------------------------------------------

    def _dispatch(self, pending: PendingOrder) -> TradeRecord:
        """Acquire the durable SEND FENCE, and only then call the broker.

        The fence goes first. No transaction spans the broker call and the record
        of it, so writing the record afterwards would leave INTENT_RECORDED after
        a successful send -- and recovery would then conclude "never sent" and
        issue a second order. For a stop or an exit that is a second SELL and a
        possible short.

        ``fence_dispatch`` also re-proves the account binding, so this is the
        last gate every single order passes through.
        """
        request = pending.request
        record = self._coordinator.fence_dispatch(pending.record, request.client_order_id)
        self._port.log(f"[{request.role.value}-FENCED] {request.client_order_id} fence durable")
        self._port.log(f"[{request.role.value}-SUBMIT] {request.describe()}")
        self._port.submit(request)
        return record

    def _dispatch_protection(self, record: TradeRecord, protection: PendingOrder) -> None:
        """Protect a position that actually filled -- halted or failed or not.

        An entry that has already filled is a real long. Declining to protect it
        because progression stopped would leave it naked, which is the outcome
        stopping is meant to avoid. So protection is the one action that survives
        both an operational halt and a FAILED lifecycle, and only as a guarded,
        deterministic risk-reducing step:

        * the fill and the protective intent are already durable (one write);
        * the account is re-proven at the send fence, immediately before the call;
        * and when progression has stopped, broker truth must reconcile first.

        It never submits another ENTRY, never clears the halt, and never resumes
        autonomous trading. If protection cannot be dispatched safely, the
        position is surfaced as UNPROTECTED for manual handling.
        """
        stopped = self.halted or record.state is TradeState.FAILED
        if stopped:
            try:
                self._coordinator.reconcile(record, self._port.view())
            except Exception as exc:
                self._port.error(
                    f"[UNPROTECTED-POSITION] an entry filled after progression stopped, but "
                    f"broker state is ambiguous ({type(exc).__name__}: {exc}). Refusing to "
                    "send a stop against a position we cannot confirm."
                )
                self._port.error(
                    "[UNPROTECTED-POSITION] PROTECT OR CLOSE THE POSITION MANUALLY. No "
                    "further automatic action will be taken."
                )
                self._raise_halt(
                    "UNPROTECTED POSITION: an entry filled after progression stopped and "
                    "protection could not be placed safely.",
                    kind=HaltKind.MANUAL_CLEARANCE_REQUIRED,
                )
                return
            self._port.error(
                "[POST-HALT-PROTECT] an entry filled after progression stopped. Dispatching "
                "the protective stop as a deterministic risk-reducing action; progression "
                "REMAINS stopped and no second entry is possible."
            )
        self._dispatch(protection)

    # -- Progression --------------------------------------------------------

    def _progress(self, record: TradeRecord, broker: BrokerView) -> None:
        """Advance only where broker truth supports it. Every write via the coordinator.

        Note what is NOT here: any check of the execution window. The window
        gates the ENTRY, because a market order needs a liquid session. Gating
        protection or an exit on the clock would refuse to reduce risk because
        of the time of day.
        """
        identity = self._coordinator.identity

        if record.state is TradeState.PROTECTION_SUBMITTED and record.open_long_quantity > 0:
            record = self._coordinator.confirm_protection(record, broker)
            self._port.log("[PROTECTION-ACK] broker confirms protection matches filled quantity")

        if self._exit_requested and record.open_long_quantity > 0:
            if record.state is TradeState.PROTECTED:
                record = self._coordinator.request_exit(record)
                self._port.log("[EXIT-REQUEST] exit requested")

            if broker.open_protective_quantity(identity) > 0:
                record, should_cancel = self._coordinator.begin_protection_cancel(record)
                if should_cancel:
                    self._port.cancel(identity.protective_order_id)
                    self._port.log("[EXIT-REQUEST] cancel requested ONCE; awaiting CANCELED event")
                else:
                    self._port.log("[EXIT-REQUEST] awaiting broker cancellation confirmation")
                return

            if record.state is TradeState.EXIT_REQUESTED:
                self._dispatch(self._coordinator.begin_exit(record, broker))
                return

        if record.state is TradeState.CLOSED:
            record = self._coordinator.finalize(record, broker)
            self._port.log("[FINAL-RECONCILE] flat: no position, no open KalpaMani orders")
            self._port.log(f"[FINAL-RECONCILE] {record.describe()}")

    # -- Halting ------------------------------------------------------------

    def _raise_halt(
        self,
        reason: str,
        *,
        error: BaseException | None = None,
        kind: HaltKind | None = None,
    ) -> None:
        """Latch normal progression off. Broker events keep being ingested.

        A halt whose cause is a safety violation is persisted and survives a
        restart; anything else halts this deployment only. See
        :func:`kalpamani.execution.halt.classify_halt`.
        """
        halt = OperationalHalt(reason=reason, kind=kind or classify_halt(error))
        self._halt_store.put(halt)  # a no-op for a session-scoped halt
        self._halt = halt
        self._port.error(f"[PHASE2-ABORT] {reason}")
        self._port.error(
            "[PHASE2-ABORT] Normal progression halted: no new entry, no autonomous trading. "
            "Broker events for orders already sent are still recorded, and a position that "
            "fills after this point will still be protected."
        )
        if halt.manual_clear_required:
            self._port.error(
                "[PHASE2-ABORT] This halt SURVIVES restart. Reconcile against the broker by "
                "hand, then clear it deliberately with `scripts/phase2_arm.py --clear-halt`."
            )


__all__ = ["BrokerPort", "EventStatus", "OrderEventFacts", "Phase2Cycle"]
