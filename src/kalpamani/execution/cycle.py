"""The Phase 2 cycle orchestration (ADR-0004 §16).

Every decision Phase 2 makes lives here: when to arm, what recovery may
re-dispatch, how a broker event is applied, when to halt. The LEAN algorithm
supplies broker I/O through :class:`BrokerPort` and nothing else.

The adapter contract
--------------------
Three layers, each with one job, and the boundary between them matters:

``LeanBrokerPort`` (in ``main.py``)
    Translates LEAN types. **Preserves ``OrderEvent.fill_quantity`` including its
    SIGN.** It must never call ``abs()``: the sign is broker semantics, and
    throwing it away here would discard a safety signal before anyone could check
    it.
:class:`Phase2Cycle`
    Validates the sign against the durable order -- a BUY must fill positive, a
    SELL negative -- and only then drops it.
:mod:`kalpamani.execution.state_store`
    Receives **absolute** quantities only. ``open_long_quantity`` derives
    direction from the order's *role*, not from the arithmetic sign, so a signed
    quantity reaching it would double-count direction.

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
    PHASE2_MANUAL_RESOLUTION_PHRASE,
    PHASE2_QUANTITY,
    PHASE2_SYMBOL,
    ExecutionArmRequest,
)
from kalpamani.execution.halt import (
    ExecutionRisk,
    HaltKind,
    HaltStore,
    OperationalHalt,
    classify_halt,
)
from kalpamani.execution.identity import OrderRole
from kalpamani.execution.lifecycle import TradeState
from kalpamani.execution.reconciliation import (
    BrokerOrderView,
    BrokerView,
    OwnershipError,
    resolve_broker_view,
    resolve_ownership,
)
from kalpamani.execution.session import SessionVerificationError, verify_paper_session
from kalpamani.execution.state_store import (
    DispatchState,
    StateStoreError,
    TradeRecord,
    absolute_fill_quantity,
)
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
    #: A fill event carrying a non-zero filled quantity, of EITHER sign.
    FILL = "FILL"
    #: Anything else, including a zero-quantity event. Recorded, never acted on.
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class OrderEventFacts:
    """One broker event, normalised. No LEAN type crosses this boundary.

    Carries the ORDER, not just an id, because after a restart the LEAN tag is
    blank and ownership has to be re-established from the broker-native id. The
    adapter supplies raw identity; the cycle resolves it.
    """

    order: BrokerOrderView
    status: EventStatus
    #: SIGNED, exactly as LEAN reports it: a BUY fills positive, a SELL negative.
    #: The adapter must NOT take its absolute value -- the sign is a safety
    #: signal, validated here against the durable order before it is dropped.
    fill_quantity: int = 0
    fill_price: Decimal = Decimal(0)
    #: Stable per-order event identity, so repeated delivery is a true no-op.
    fill_id: str = ""


class BrokerPort(Protocol):
    """Broker I/O, as the LEAN adapter provides it."""

    def view(self) -> BrokerView:
        """Broker truth: positions and every open order, ours and foreign.

        Returns RAW views -- tag, broker ids, LEAN order id and attributes -- with
        ownership unresolved. The cycle resolves them against durable state.
        """
        ...

    def submit(self, request: OrderRequest) -> None:
        """Place the order. Called only after its send fence is durable."""
        ...

    def cancel(self, lean_order_id: str) -> None:
        """Cancel exactly the LEAN order with this process-local id.

        Addressed by LEAN order id, never by tag or symbol: after a restart the
        tag is gone, and "the first SELL stop on SPY" could be a stranger's.
        """
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
        manual_resolution_requested: bool = False,
        resolution_confirmation: str = "",
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
        self._manual_resolution_requested = manual_resolution_requested
        self._resolution_confirmation = resolution_confirmation
        self._resolution_attempted = False

        #: A durable halt is read at construction, so a restart does NOT resume.
        self._halt: OperationalHalt | None = halt_store.get()
        self._session_logged = False
        self._recovery_logged = False
        self._entries_submitted_this_session = 0
        #: Whether broker truth was successfully read in the current cycle.
        #: Reported on the failure path; see ExecutionRisk.
        self._broker_state_established = True
        self._diagnosed = False
        self._restart_checkpoint_passed = False

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
        if self._manual_resolution_requested:
            # A repair action, so it runs DESPITE the halt -- the halt is exactly
            # what it exists to resolve. It never touches the broker.
            self._attempt_manual_resolution()
            return
        if self.halted:
            self._diagnose_identity_once()
            return
        self._broker_state_established = False
        try:
            record = self._coordinator.load()

            if record is None:
                broker = self._resolved_view(None)
                self._broker_state_established = True
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

            broker = self._resolved_view(record)
            self._broker_state_established = True

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

    def _attempt_manual_resolution(self) -> None:
        """Record a human broker close against a failed run. Once, then stop.

        Writes down a fact a human established, after re-verifying it here. It
        submits nothing, cancels nothing and modifies nothing at the broker.
        """
        if self._resolution_attempted:
            return
        self._resolution_attempted = True
        try:
            if self._resolution_confirmation != PHASE2_MANUAL_RESOLUTION_PHRASE:
                self._port.error(
                    "[MANUAL-RESOLVE] REFUSED: the confirmation phrase does not match. "
                    "Acknowledging a manual cleanup is a deliberate act."
                )
                return
            if not self.halted:
                self._port.error(
                    "[MANUAL-RESOLVE] REFUSED: no operational halt is in force. This action "
                    "exists to close out a FAILED run, not a healthy one."
                )
                return

            record = self._coordinator.load()
            if record is None:
                self._port.error(
                    "[MANUAL-RESOLVE] REFUSED: there is no durable trade record to resolve."
                )
                return

            broker = self._resolved_view(record)
            self._port.log(
                f"[MANUAL-RESOLVE] broker check: {PHASE2_SYMBOL} position="
                f"{broker.position_quantity(PHASE2_SYMBOL)} "
                f"open_orders_any_source={broker.open_order_count_for_symbol(PHASE2_SYMBOL)}"
            )
            resolved = self._coordinator.resolve_manually(record, broker)
            self._port.log(f"[MANUAL-RESOLVE] recorded: {resolved.describe()}")
            self._port.log(
                "[MANUAL-RESOLVE] the run is terminal FAILED and stays FAILED. It is NOT "
                "reconciled: the automated lifecycle did not close this position."
            )
            self._port.log(
                "[MANUAL-RESOLVE] clear the halt deliberately, then authorise a NEW "
                "certification run with its own run number."
            )
        except Exception as exc:
            self._port.error(f"[MANUAL-RESOLVE] REFUSED: {type(exc).__name__}: {exc}")

    def _diagnose_identity_once(self) -> None:
        """Read-only identity report, emitted once while halted.

        A halt stops decisions, not observation. An operator staring at a halted
        deployment needs to know whether the orders actually open at the broker
        can be recognised as ours at all -- and that question is answerable
        without touching anything.

        Writes nothing. Orders nothing. Cancels nothing. Reports conclusions
        only: no broker id, no tag value, no account identifier.
        """
        if self._diagnosed:
            return
        self._diagnosed = True
        try:
            record = self._coordinator.load()
            raw = self._port.view()
            self._port.log(f"[IDENTITY-DIAG] open orders at the broker: {len(raw.open_orders)}")
            for index, order in enumerate(raw.open_orders):
                try:
                    resolved, basis = resolve_ownership(order, record, self._coordinator.identity)
                except OwnershipError as exc:
                    self._port.error(f"[IDENTITY-DIAG] order {index}: CONTRADICTORY -- {exc}")
                    continue
                self._port.log(
                    f"[IDENTITY-DIAG] order {index}: symbol={order.symbol} side={order.side} "
                    f"qty={order.quantity} type={order.order_type} "
                    f"tag_present={bool(order.tag)} "
                    f"broker_id_present={bool(order.broker_order_ids)} "
                    f"lean_id_present={bool(order.lean_order_id)} "
                    f"resolved={'YES' if resolved else 'NO'} basis={basis.value}"
                )
            for durable in record.orders.values() if record else ():
                self._port.log(
                    f"[IDENTITY-DIAG] durable {durable.role.value}: dispatch="
                    f"{durable.dispatch.value} broker_identity_recorded="
                    f"{'YES' if durable.has_broker_identity else 'NO'}"
                )
        except Exception as exc:
            self._port.error(f"[IDENTITY-DIAG] unavailable: {type(exc).__name__}: {exc}")

    def _resolved_view(self, record: TradeRecord | None) -> BrokerView:
        """Broker truth with every open order attributed, or marked foreign."""
        return resolve_broker_view(self._port.view(), record, self._coordinator.identity)

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
        try:
            record = self._coordinator.load()
            if record is None:
                return  # nothing of ours can exist yet

            # OWNERSHIP FIRST. After a restart the tag is blank, so an event for
            # our own protective stop arrives anonymous. Resolve it the same way
            # reconciliation does -- tag, then broker id, then attribute
            # validation -- or do not apply it at all.
            try:
                tag, _basis = resolve_ownership(facts.order, record, self._coordinator.identity)
            except OwnershipError as exc:
                self._port.error(f"[UNRESOLVED-EVENT] {exc}")
                self._raise_halt(
                    f"contradictory ownership for a broker event: {exc}",
                    kind=HaltKind.MANUAL_CLEARANCE_REQUIRED,
                )
                return
            if tag is None:
                self._unattributed_event(record, facts)
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
            self._apply_event(record, facts, tag)
        except Exception as exc:
            self._raise_halt(f"order-event handling failed: {type(exc).__name__}: {exc}", error=exc)

    def _unattributed_event(self, record: TradeRecord, facts: OrderEventFacts) -> None:
        """An event we cannot prove is ours. Never applied.

        Usually harmless -- a foreign order on another symbol. But an
        unattributable event on OUR symbol while we hold a position could be the
        very order that protects us, arriving without identity, and continuing
        as though nothing happened would be guessing.
        """
        if facts.order.symbol != record.symbol or record.open_long_quantity <= 0:
            return
        self._port.error(
            f"[UNRESOLVED-EVENT] a {facts.status.value} event on {record.symbol} could not be "
            "attributed by tag or by broker id, while a KalpaMani position is open. It was "
            "NOT applied."
        )
        self._raise_halt(
            f"unattributable {facts.status.value} event on {record.symbol} while long "
            f"{record.open_long_quantity}.",
            kind=HaltKind.MANUAL_CLEARANCE_REQUIRED,
        )

    def _apply_event(self, record: TradeRecord, facts: OrderEventFacts, tag: str) -> None:
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
            # Capture the broker-native id here: it is the identity that will
            # survive the next restart, and the only chance to record it.
            self._coordinator.acknowledge(
                record, tag, broker_order_ids=facts.order.broker_order_ids
            )
            return

        if facts.status is not EventStatus.FILL or facts.fill_quantity == 0:
            return

        # LEAN fill quantities are SIGNED. Testing `> 0` here silently discarded
        # every protective and exit SELL fill, leaving durable state convinced it
        # still held a position the broker had already closed -- and the next
        # reconciliation halting on a disagreement it had caused itself.
        #
        # The sign is a safety signal, so it is validated against the recorded
        # order before it is dropped. Only the absolute quantity reaches the
        # accounting layer, which derives direction from the role.
        order = record.orders.get(tag)
        if order is None:
            self._raise_halt(
                f"Fill for {tag}, which this execution has no record of submitting.",
                kind=HaltKind.MANUAL_CLEARANCE_REQUIRED,
            )
            return
        try:
            quantity = absolute_fill_quantity(order, int(facts.fill_quantity))
        except StateStoreError as exc:
            self._port.error(f"[CONTRADICTORY-FILL] {exc}")
            self._raise_halt(
                f"contradictory broker fill for {tag}: {exc}",
                kind=HaltKind.MANUAL_CLEARANCE_REQUIRED,
            )
            return

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
                self._coordinator.reconcile(record, self._resolved_view(record))
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

        if record.state is TradeState.PROTECTED and record.open_long_quantity > 0:
            self._assert_restart_ready(record, broker)

        if self._exit_requested and record.open_long_quantity > 0:
            if record.state is TradeState.PROTECTED:
                record = self._coordinator.request_exit(record)
                self._port.log("[EXIT-REQUEST] exit requested")

            if broker.open_protective_quantity(identity) > 0:
                # Address the cancellation at the CURRENT re-hydrated order, found
                # by resolved identity. Never by tag (gone after a restart), never
                # by symbol, never "the first SELL stop" -- that could be a
                # stranger's order.
                target = broker.owned_order(identity.protective_order_id)
                if target is None or not target.lean_order_id:
                    self._raise_halt(
                        "the protective order shows as working but could not be addressed for "
                        "cancellation; refusing to cancel anything else.",
                        kind=HaltKind.MANUAL_CLEARANCE_REQUIRED,
                    )
                    return
                record, should_cancel = self._coordinator.begin_protection_cancel(record)
                if should_cancel:
                    self._port.cancel(target.lean_order_id)
                    self._port.log(
                        f"[EXIT-REQUEST] cancel requested ONCE for the protective order "
                        f"(resolved by {target.ownership.value}); awaiting CANCELED event"
                    )
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

    def _current_risk(self) -> ExecutionRisk:
        """What is at stake right now, read defensively.

        Only ever called on a failure path, so it must not raise. If durable
        state cannot even be read, that *is* the answer: maximum risk.
        """
        try:
            record = self._coordinator.load()
        except Exception:
            return ExecutionRisk.unknown()
        if record is None:
            return ExecutionRisk.nothing_at_stake(
                broker_state_established=self._broker_state_established
            )
        return ExecutionRisk.from_record(
            record, broker_state_established=self._broker_state_established
        )

    def _assert_restart_ready(self, record: TradeRecord, broker: BrokerView) -> None:
        """Refuse to be restartable until the position could be recovered.

        A restart is only survivable if the protective order can be recognised
        afterwards, and that requires its broker-native id to be durable BEFORE
        the process stops. Run 1 stopped without it and stranded a live protected
        position -- recoverable by no amount of later cleverness, because the
        identity was simply never written down.

        Checked once per deployment, on reaching PROTECTED. On failure the
        deployment halts: it does not cancel the stop, and it does not proceed to
        a restart that could not be recovered from.
        """
        if self._restart_checkpoint_passed:
            return
        identity = self._coordinator.identity
        protective = record.order_for_role(OrderRole.PROTECTIVE)
        owned = [
            o
            for o in broker.orders_owned_by(identity)
            if o.client_order_id == identity.protective_order_id
        ]
        problems: list[str] = []
        if record.open_long_quantity != PHASE2_QUANTITY:
            problems.append(f"long={record.open_long_quantity}")
        if broker.open_protective_quantity(identity) != PHASE2_QUANTITY:
            problems.append(f"broker_protective={broker.open_protective_quantity(identity)}")
        if record.protected_quantity != PHASE2_QUANTITY:
            problems.append(f"internal_protective={record.protected_quantity}")
        if protective is None or protective.dispatch is not DispatchState.ACKNOWLEDGED:
            problems.append("protective not ACKNOWLEDGED")
        if len(owned) != 1:
            problems.append(f"owned_protective_orders={len(owned)}")
        if protective is None or not protective.has_broker_identity:
            problems.append("durable protective broker identity ABSENT")

        if problems:
            self._port.error("[RESTART-CHECKPOINT] NOT restart-safe: " + "; ".join(problems) + ".")
            self._raise_halt(
                "the protective order could not be proven recoverable across a restart. "
                "Halting BEFORE creating another unrecoverable state. The stop is left "
                "untouched.",
                kind=HaltKind.MANUAL_CLEARANCE_REQUIRED,
            )
            return

        self._restart_checkpoint_passed = True
        self._port.log(
            "[RESTART-CHECKPOINT] long=1 broker_protective=1 internal_protective=1 "
            "protective_dispatch=ACKNOWLEDGED owned_protective_orders=1 "
            "protective_broker_identity=RECORDED -- restart is survivable"
        )

    def _raise_halt(
        self,
        reason: str,
        *,
        error: BaseException | None = None,
        kind: HaltKind | None = None,
    ) -> None:
        """Latch normal progression off. Broker events keep being ingested.

        The halt is durable whenever anything is at stake, and whenever the
        failure is one this code does not recognise. Only an enumerated benign
        pre-trade transient halts the session alone. See
        :func:`kalpamani.execution.halt.classify_halt`.
        """
        risk = self._current_risk()
        halt = OperationalHalt(reason=reason, kind=kind or classify_halt(error, risk))
        self._halt_store.put(halt)  # a no-op for a session-scoped halt
        self._halt = halt
        self._port.error(f"[PHASE2-ABORT] {reason}")
        self._port.error(f"[PHASE2-ABORT] execution risk: {risk.describe()}")
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
