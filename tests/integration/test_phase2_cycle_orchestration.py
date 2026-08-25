"""End-to-end orchestration tests: drive the REAL cycle, not a re-creation.

These construct :class:`~kalpamani.execution.cycle.Phase2Cycle` -- the same
object the LEAN algorithm schedules -- and call ``on_cycle`` and
``on_order_event`` exactly as the adapter does. Nothing about the sequence is
re-implemented here, so a test cannot pass while production takes a different
path. That gap was a real finding: an earlier suite exercised the coordinator
directly and proved a lifecycle production never ran.

The only substitution is :class:`FakePort`, which stands in for LEAN's broker
I/O and records what was actually sent.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import time
from decimal import Decimal
from pathlib import Path

import pytest

from kalpamani.broker.orders import OrderRequest
from kalpamani.common.environment import Environment
from kalpamani.common.settings import Settings
from kalpamani.execution.coordinator import Phase2Coordinator
from kalpamani.execution.cycle import EventStatus, OrderEventFacts, Phase2Cycle
from kalpamani.execution.envelope import (
    PHASE2_CONFIRMATION_PHRASE,
    PHASE2_INTENT_NATURAL_KEY,
    PHASE2_SYMBOL,
)
from kalpamani.execution.halt import (
    HaltClearanceError,
    HaltKind,
    JsonHaltStore,
    assert_halt_clearable,
    halt_state_path,
)
from kalpamani.execution.identity import OrderRole, TradeIdentity
from kalpamani.execution.lifecycle import TradeState
from kalpamani.execution.reconciliation import (
    BrokerOrderView,
    BrokerPositionView,
    BrokerView,
    OwnershipBasis,
)
from kalpamani.execution.session import BrokerSessionEvidence, account_fingerprint
from kalpamani.execution.state_store import DispatchState, JsonTradeStateStore, TradeRecord

pytestmark = pytest.mark.integration

SPY_PRICE = Decimal("766.38")
PAPER_ACCOUNT_ID = "DU1234567"
OTHER_PAPER_ACCOUNT_ID = "DU7654321"
LIVE_ACCOUNT_ID = "U7654321"
MIDDAY = time(12, 0)
NORMAL_CLOSE_MINUTES = 240.0


def evidence(
    account_id: str = PAPER_ACCOUNT_ID, trading_mode: str = "paper"
) -> BrokerSessionEvidence:
    return BrokerSessionEvidence(
        account_id=account_id, trading_mode=trading_mode, source="test-deployment-config"
    )


class FakePort:
    """LEAN's broker I/O, recorded rather than performed."""

    def __init__(self) -> None:
        self.position = 0
        #: Every order ever submitted, keyed by the durable client order id.
        #: The VIEWS carry raw identity only -- the adapter never resolves.
        self.orders: dict[str, BrokerOrderView] = {}
        self.open_ids: set[str] = set()
        self.cancelled_lean_ids: list[str] = []
        self.submitted: list[OrderRequest] = []
        #: LEAN order ids are process-local and reassigned on restart; broker
        #: ids are not. Modelled separately, because that difference is the
        #: whole point of the ownership resolver.
        self._next_lean_id = 1
        self._next_broker_id = 3
        self.cancelled: list[str] = []
        self.logs: list[str] = []
        self.errors: list[str] = []
        self.price = SPY_PRICE
        self.session_open = True
        self.now = MIDDAY
        self.minutes_to_close: float | None = NORMAL_CLOSE_MINUTES
        #: Raised once by the next view(), to simulate an unrelated fault.
        self.fail_next_view: Exception | None = None

    # -- BrokerPort ---------------------------------------------------------

    def view(self) -> BrokerView:
        if self.fail_next_view is not None:
            error, self.fail_next_view = self.fail_next_view, None
            raise error
        return BrokerView(
            positions=(BrokerPositionView(PHASE2_SYMBOL, self.position),),
            open_orders=tuple(self.orders[cid] for cid in sorted(self.open_ids)),
        )

    def submit(self, request: OrderRequest) -> None:
        self.submitted.append(request)
        self.orders[request.client_order_id] = BrokerOrderView(
            client_order_id="",  # raw: the adapter never resolves ownership
            symbol=request.symbol,
            side=request.side.value,
            quantity=request.quantity,
            is_open=True,
            tag=request.client_order_id,
            broker_order_ids=(str(self._next_broker_id),),
            lean_order_id=str(self._next_lean_id),
            order_type="Market" if request.stop_price is None else "StopMarket",
            stop_price=str(request.stop_price) if request.stop_price is not None else None,
        )
        self.open_ids.add(request.client_order_id)
        self._next_lean_id += 1
        self._next_broker_id += 1

    def cancel(self, lean_order_id: str) -> None:
        self.cancelled_lean_ids.append(lean_order_id)
        self.cancelled.append(lean_order_id)

    def reference_price(self) -> Decimal:
        return self.price

    def broker_equity_usd(self) -> Decimal:
        return Decimal("1000000")  # the IBKR paper balance; never sizes anything

    def regular_session_open(self) -> bool:
        return self.session_open

    def exchange_local_time(self) -> time:
        return self.now

    def minutes_to_regular_close(self) -> float | None:
        return self.minutes_to_close

    def log(self, message: str) -> None:
        self.logs.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)

    # -- Test helpers -------------------------------------------------------

    def fill(self, client_order_id: str, quantity: int) -> None:
        order = self.orders[client_order_id]
        self.open_ids.discard(client_order_id)
        self.position += quantity if order.side == "BUY" else -quantity

    def confirm_cancel(self, client_order_id: str) -> None:
        self.open_ids.discard(client_order_id)

    def rehydrate(self) -> None:
        """Model what LEAN actually does on a restart, as observed at IBKR.

        The tag is NOT sent to IBKR, so an order LEAN rebuilds from the broker
        comes back with a BLANK tag and a NEWLY ASSIGNED LEAN order id. The
        broker id is the same value it had before. Reproduced from a real
        reconnect: the stop kept its broker id and lost everything else.
        """
        next_lean_id = 1
        for cid in sorted(self.open_ids):
            self.orders[cid] = replace(self.orders[cid], tag="", lean_order_id=str(next_lean_id))
            next_lean_id += 1

    def count(self, role: OrderRole) -> int:
        return sum(1 for r in self.submitted if r.role is role)

    def said(self, needle: str) -> bool:
        return any(needle in line for line in self.logs + self.errors)


def make_cycle(
    tmp_path: Path,
    port: FakePort,
    *,
    account_id: str = PAPER_ACCOUNT_ID,
    trading_mode: str = "paper",
    armed: bool = True,
    exit_requested: bool = False,
) -> tuple[Phase2Cycle, Phase2Coordinator, JsonTradeStateStore]:
    """A cycle over ``tmp_path``. Calling it twice models a process restart."""
    storage = tmp_path / "storage"
    project = tmp_path / "project"
    storage.mkdir(exist_ok=True)
    project.mkdir(exist_ok=True)
    store = JsonTradeStateStore(storage / "phase2_trade_state.json")
    coordinator = Phase2Coordinator(
        store,
        TradeIdentity.derive(PHASE2_INTENT_NATURAL_KEY, attempt=1),
        storage_root=storage,
        project_root=project,
        session_provider=lambda: evidence(account_id, trading_mode),
    )
    cycle = Phase2Cycle(
        coordinator,
        port,
        JsonHaltStore(halt_state_path(storage)),
        settings=Settings(environment=Environment.PAPER),
        test_mode=armed,
        arm_flag=armed,
        confirmation=PHASE2_CONFIRMATION_PHRASE if armed else "",
        exit_requested=exit_requested,
        armed_fingerprint=account_fingerprint(PAPER_ACCOUNT_ID) if armed else "",
    )
    cycle.start()
    return cycle, coordinator, store


def fill_event(
    port: FakePort, client_order_id: str, quantity: int, fill_id: str = "7-1"
) -> OrderEventFacts:
    """A LEAN fill event. ``quantity`` is SIGNED and has no default, deliberately.

    LEAN reports a BUY fill positive and a SELL fill negative. The old fixture
    defaulted to ``+1`` for both, which is precisely why a defect that discarded
    every protective and exit SELL fill sat here undetected: the tests were
    feeding the cycle a direction the broker never sends. Every call site now
    has to state the sign the broker would actually report.
    """
    return OrderEventFacts(
        order=port.orders[client_order_id],
        status=EventStatus.FILL,
        fill_quantity=quantity,
        fill_price=SPY_PRICE,
        fill_id=fill_id,
    )


def status_event(port: FakePort, client_order_id: str, status: EventStatus) -> OrderEventFacts:
    return OrderEventFacts(order=port.orders[client_order_id], status=status)


# ---------------------------------------------------------------------------
# The initial happy path, start to flat, through the real cycle
# ---------------------------------------------------------------------------


def test_happy_path_arms_protects_exits_and_reconciles(tmp_path: Path) -> None:
    port = FakePort()
    cycle, coordinator, store = make_cycle(tmp_path, port)
    identity = coordinator.identity

    # Cycle 1: nothing exists, every gate passes, the entry goes out.
    cycle.on_cycle()
    assert port.count(OrderRole.ENTRY) == 1
    assert store.require(identity.trade_intent_id).state is TradeState.ENTRY_SUBMITTED

    # The entry fills. Fill, lifecycle and protective intent land together, and
    # the stop is dispatched from the SAME event.
    port.fill(identity.entry_order_id, 1)
    cycle.on_order_event(fill_event(port, identity.entry_order_id, +1))
    assert port.count(OrderRole.PROTECTIVE) == 1
    protective = port.submitted[-1]
    assert protective.stop_price == (SPY_PRICE * Decimal("0.90")).quantize(Decimal("0.01"))

    # Cycle 2: a fresh snapshot shows the stop working, so it is adopted.
    cycle.on_cycle()
    assert store.require(identity.trade_intent_id).state is TradeState.PROTECTED

    # The operator redeploys asking for the exit. Same durable state.
    exiting, _, _ = make_cycle(tmp_path, port, exit_requested=True)
    exiting.on_cycle()
    # Addressed by the RESOLVED LEAN order id, not by tag or by shape.
    assert port.cancelled_lean_ids == [port.orders[identity.protective_order_id].lean_order_id]

    # CANCEL_PENDING is not confirmation.
    exiting.on_order_event(
        status_event(port, identity.protective_order_id, EventStatus.CANCEL_PENDING)
    )
    assert store.require(identity.trade_intent_id).protected_quantity == 1

    port.confirm_cancel(identity.protective_order_id)
    exiting.on_order_event(status_event(port, identity.protective_order_id, EventStatus.CANCELED))
    assert store.require(identity.trade_intent_id).protected_quantity == 0
    assert not exiting.halted, "a REQUESTED cancellation is expected, not a failure"

    exiting.on_cycle()
    assert port.count(OrderRole.EXIT) == 1

    port.fill(identity.exit_order_id, 1)
    exiting.on_order_event(fill_event(port, identity.exit_order_id, -1, fill_id="9-1"))
    exiting.on_cycle()

    assert store.require(identity.trade_intent_id).state is TradeState.RECONCILED
    assert port.position == 0
    assert port.count(OrderRole.ENTRY) == 1, "exactly one entry, ever"
    assert not exiting.halted


def test_a_disarmed_cycle_reads_and_reconciles_but_never_orders(tmp_path: Path) -> None:
    port = FakePort()
    cycle, _, store = make_cycle(tmp_path, port, armed=False)

    for _ in range(3):
        cycle.on_cycle()

    assert port.submitted == []
    assert store.all_records() == []
    assert port.said("session verified PAPER")
    assert not cycle.halted


# ---------------------------------------------------------------------------
# Round 8 item 5 -- the window gates the ENTRY only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "minutes", "open_", "why"),
    [
        (time(9, 30), 390.0, True, "opening auction"),
        (time(12, 59), 1.0, True, "13:00 early close"),
        (time(12, 0), 240.0, False, "holiday"),
        (time(12, 0), None, True, "calendar cannot answer"),
    ],
)
def test_an_ineligible_window_stays_read_only_and_does_not_consume_the_arm(
    tmp_path: Path, now: time, minutes: float | None, open_: bool, why: str
) -> None:
    port = FakePort()
    port.now, port.minutes_to_close, port.session_open = now, minutes, open_
    cycle, _, store = make_cycle(tmp_path, port)

    cycle.on_cycle()

    assert port.submitted == [], why
    assert store.all_records() == [], "the one-time arm was NOT consumed"
    assert port.said("entry not eligible")
    assert not cycle.halted, "an ineligible time is not a failure; it is simply not yet"

    # The window opens. The same deployment then arms, with no re-arming needed.
    port.now, port.minutes_to_close, port.session_open = MIDDAY, NORMAL_CLOSE_MINUTES, True
    cycle.on_cycle()
    assert port.count(OrderRole.ENTRY) == 1


def test_the_exit_is_never_gated_on_the_window(tmp_path: Path) -> None:
    """Refusing to reduce risk because of the clock is not a safety gate."""
    port = FakePort()
    cycle, coordinator, _ = make_cycle(tmp_path, port)
    identity = coordinator.identity
    cycle.on_cycle()
    port.fill(identity.entry_order_id, 1)
    cycle.on_order_event(fill_event(port, identity.entry_order_id, +1))
    cycle.on_cycle()

    # The session is now closed outright -- no entry could be authorised.
    port.session_open, port.minutes_to_close = False, None

    exiting, _, _ = make_cycle(tmp_path, port, exit_requested=True)
    exiting.on_cycle()
    # Addressed by the RESOLVED LEAN order id, not by tag or by shape.
    assert port.cancelled_lean_ids == [port.orders[identity.protective_order_id].lean_order_id]
    port.confirm_cancel(identity.protective_order_id)
    exiting.on_order_event(status_event(port, identity.protective_order_id, EventStatus.CANCELED))
    exiting.on_cycle()
    assert port.count(OrderRole.EXIT) == 1, "the exit must not wait for market hours"


# ---------------------------------------------------------------------------
# Round 8 item 3 -- recovery ends the cycle; confirmation waits for a fresh view
# ---------------------------------------------------------------------------


def entry_filled_protection_unsent(
    tmp_path: Path, port: FakePort
) -> tuple[Phase2Coordinator, TradeRecord]:
    """Entry filled, protective intent durable, never fenced -- then a crash."""
    cycle, coordinator, store = make_cycle(tmp_path, port)
    identity = coordinator.identity
    cycle.on_cycle()
    port.fill(identity.entry_order_id, 1)
    record = store.require(identity.trade_intent_id)
    record, protection = coordinator.apply_entry_fill_and_prepare_protection(
        record,
        client_order_id=identity.entry_order_id,
        fill_id="7-1",
        fill_quantity=1,
        fill_price=SPY_PRICE,
    )
    assert protection is not None
    assert record.orders[identity.protective_order_id].dispatch is DispatchState.INTENT_RECORDED
    return coordinator, record


def test_recovery_dispatches_the_stop_and_does_not_judge_it_from_a_stale_snapshot(
    tmp_path: Path,
) -> None:
    """The snapshot recovery reads predates the order it sends.

    Confirming a just-sent stop against a broker view captured before it existed
    reports it as missing -- a false UNPROTECTED POSITION, and a durable halt for
    a system that is working correctly.
    """
    port = FakePort()
    coordinator, _ = entry_filled_protection_unsent(tmp_path, port)
    identity = coordinator.identity

    resumed, _, store = make_cycle(tmp_path, port)
    resumed.on_cycle()

    assert port.count(OrderRole.PROTECTIVE) == 1, "recovery sent the stop exactly once"
    assert not resumed.halted, "the cycle must not judge the order it just sent"
    # Recovery legitimately DIAGNOSES the intent as unprotected -- that is the
    # reason it re-dispatches. What must not appear is the FAILURE: an
    # UNPROTECTED POSITION raised by confirming the stop against a stale view.
    assert not port.said("UNPROTECTED POSITION"), "no false unprotected failure"
    assert not port.said("UNPROTECTED-POSITION")
    assert port.said("FRESH broker snapshot")
    assert store.require(identity.trade_intent_id).state is TradeState.PROTECTION_SUBMITTED

    # The NEXT cycle sees a fresh view, adopts the acknowledgement and confirms.
    resumed.on_cycle()
    assert port.count(OrderRole.PROTECTIVE) == 1, "still exactly one"
    assert store.require(identity.trade_intent_id).state is TradeState.PROTECTED
    assert not resumed.halted


# ---------------------------------------------------------------------------
# Round 8 items 1-2 -- ingestion is account-bound, and survives FAILED
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("account_id", "trading_mode"),
    [(LIVE_ACCOUNT_ID, "live"), (OTHER_PAPER_ACCOUNT_ID, "paper"), ("XX999", "")],
    ids=["live", "different-paper", "unknown"],
)
def test_an_event_from_a_foreign_session_cannot_mutate_the_trade(
    tmp_path: Path, account_id: str, trading_mode: str
) -> None:
    port = FakePort()
    cycle, coordinator, store = make_cycle(tmp_path, port)
    identity = coordinator.identity
    cycle.on_cycle()
    before = store.require(identity.trade_intent_id)

    # The process comes back connected somewhere else. The tag still looks like
    # ours -- a tag proves nothing about which account the event came from.
    foreign, _, _ = make_cycle(tmp_path, port, account_id=account_id, trading_mode=trading_mode)
    port.fill(identity.entry_order_id, 1)
    foreign.on_order_event(fill_event(port, identity.entry_order_id, +1))

    after = store.require(identity.trade_intent_id)
    assert after == before, "the account-bound record must be untouched"
    assert after.filled_quantity == 0
    assert foreign.halted
    assert foreign.halt is not None and foreign.halt.manual_clear_required
    assert port.said("ACCOUNT-BINDING FAILURE")
    assert port.count(OrderRole.PROTECTIVE) == 0


def test_an_entry_filling_after_a_halt_is_recorded_and_protected(tmp_path: Path) -> None:
    """A halt stops new decisions. It must not make us blind to a real position."""
    port = FakePort()
    cycle, coordinator, store = make_cycle(tmp_path, port)
    identity = coordinator.identity
    cycle.on_cycle()
    assert port.count(OrderRole.ENTRY) == 1

    port.fail_next_view = RuntimeError("transport blip")
    cycle.on_cycle()
    assert cycle.halted

    # The entry -- already at the broker -- now fills.
    port.fill(identity.entry_order_id, 1)
    cycle.on_order_event(fill_event(port, identity.entry_order_id, +1))

    persisted = store.require(identity.trade_intent_id)
    assert persisted.open_long_quantity == 1, "the fill is durable"
    assert sum(1 for o in persisted.orders.values() if o.role is OrderRole.PROTECTIVE) == 1
    assert port.count(OrderRole.PROTECTIVE) == 1, "exactly one stop"
    assert port.count(OrderRole.ENTRY) == 1, "no second entry"
    assert cycle.halted, "progression REMAINS halted"
    assert port.said("POST-HALT-PROTECT")


def test_a_late_entry_fill_after_FAILED_is_still_recorded_and_protected(  # noqa: N802
    tmp_path: Path,
) -> None:
    """FAILED is terminal for the LIFECYCLE. Broker facts keep arriving anyway.

    Before this, the fill tried to advance FAILED -> PROTECTION_SUBMITTED, raised
    LifecycleError, and neither the fill nor the protective intent ever became
    durable -- leaving a real long this process could not see.
    """
    port = FakePort()
    cycle, coordinator, store = make_cycle(tmp_path, port)
    identity = coordinator.identity
    cycle.on_cycle()

    record = store.require(identity.trade_intent_id)
    coordinator.fail(record, "an unrelated durable failure")
    assert store.require(identity.trade_intent_id).state is TradeState.FAILED

    port.fill(identity.entry_order_id, 1)
    cycle.on_order_event(fill_event(port, identity.entry_order_id, +1))

    persisted = store.require(identity.trade_intent_id)
    assert persisted.state is TradeState.FAILED, "terminal stays terminal"
    assert persisted.open_long_quantity == 1, "the broker fact is durable"
    assert sum(1 for o in persisted.orders.values() if o.role is OrderRole.PROTECTIVE) == 1
    assert port.count(OrderRole.PROTECTIVE) == 1, "one stop, as risk reduction"
    assert port.count(OrderRole.ENTRY) == 1, "never a second entry"

    # And a restart does not resume: the lifecycle is still FAILED.
    resumed, _, _ = make_cycle(tmp_path, port)
    resumed.on_cycle()
    assert resumed.halted
    assert port.count(OrderRole.ENTRY) == 1


def test_late_protective_and_exit_fills_after_FAILED_remain_recordable(  # noqa: N802
    tmp_path: Path,
) -> None:
    port = FakePort()
    cycle, coordinator, store = make_cycle(tmp_path, port)
    identity = coordinator.identity
    cycle.on_cycle()
    port.fill(identity.entry_order_id, 1)
    cycle.on_order_event(fill_event(port, identity.entry_order_id, +1))
    cycle.on_cycle()

    record = store.require(identity.trade_intent_id)
    coordinator.fail(record, "an unrelated durable failure")

    # The stop fires after the failure. That closes the long, and pretending
    # otherwise would leave us believing we still hold it.
    port.fill(identity.protective_order_id, 1)
    cycle.on_order_event(fill_event(port, identity.protective_order_id, -1, fill_id="8-1"))

    persisted = store.require(identity.trade_intent_id)
    assert persisted.state is TradeState.FAILED
    assert persisted.protective_fill_quantity == 1
    assert persisted.open_long_quantity == 0, "the stop closed the long"
    assert port.position == 0


def test_protection_after_a_halt_is_refused_when_broker_truth_is_ambiguous(
    tmp_path: Path,
) -> None:
    port = FakePort()
    cycle, coordinator, store = make_cycle(tmp_path, port)
    identity = coordinator.identity
    cycle.on_cycle()

    port.fail_next_view = RuntimeError("transport blip")
    cycle.on_cycle()
    assert cycle.halted

    # The entry fills at the broker, but the broker view disagrees: no position.
    cycle.on_order_event(fill_event(port, identity.entry_order_id, +1))

    assert port.count(OrderRole.PROTECTIVE) == 0, "no stop against a position we cannot confirm"
    assert port.said("UNPROTECTED-POSITION")
    assert port.said("MANUALLY")
    assert store.require(identity.trade_intent_id).open_long_quantity == 1, "fact still recorded"


# ---------------------------------------------------------------------------
# Round 8 item 4 -- a safety halt survives a restart
# ---------------------------------------------------------------------------


def test_a_safety_halt_survives_a_restart_and_does_not_resume(tmp_path: Path) -> None:
    port = FakePort()
    cycle, coordinator, _ = make_cycle(tmp_path, port)
    identity = coordinator.identity
    cycle.on_cycle()
    port.fill(identity.entry_order_id, 1)
    cycle.on_order_event(fill_event(port, identity.entry_order_id, +1))
    cycle.on_cycle()

    # The stop is cancelled by someone else. Protection vanished; that is a
    # safety violation and needs a human.
    port.confirm_cancel(identity.protective_order_id)
    cycle.on_order_event(status_event(port, identity.protective_order_id, EventStatus.CANCELED))
    assert cycle.halted
    assert cycle.halt is not None and cycle.halt.kind is HaltKind.MANUAL_CLEARANCE_REQUIRED

    submitted_before = len(port.submitted)
    resumed, _, _ = make_cycle(tmp_path, port)
    assert resumed.halted, "a restart does NOT clear a safety halt"
    resumed.on_cycle()
    resumed.on_cycle()
    assert len(port.submitted) == submitted_before, "nothing new was sent"
    assert port.said("does NOT resume merely because the process restarted")

    # Explicit human clearance is the only way out.
    JsonHaltStore(halt_state_path(tmp_path / "storage")).clear()
    cleared, _, _ = make_cycle(tmp_path, port)
    assert not cleared.halted


def test_an_ENUMERATED_pre_trade_transient_does_not_become_a_permanent_chore(  # noqa: N802
    tmp_path: Path,
) -> None:
    """Not every hiccup should need a human. An operator who has to clear a halt
    after each blip stops reading them.

    The allowlist is by TYPE and applies only before anything exists to lose:
    a cold-start data-farm connection error, with no record, no arm consumed and
    no order anywhere.
    """
    port = FakePort()
    cycle, _, store = make_cycle(tmp_path, port)
    port.fail_next_view = ConnectionError("IB data farm not yet available")
    cycle.on_cycle()

    assert cycle.halted
    assert cycle.halt is not None and cycle.halt.kind is HaltKind.SESSION
    assert store.all_records() == [], "nothing was at stake"

    resumed, _, _ = make_cycle(tmp_path, port)
    assert not resumed.halted, "a restart may retry an enumerated transient"
    resumed.on_cycle()
    assert port.count(OrderRole.ENTRY) == 1


def test_an_UNKNOWN_exception_halts_durably_even_before_any_trade(  # noqa: N802
    tmp_path: Path,
) -> None:
    """`not a SafetyViolationError => transient` was fail-open. This is the fix.

    The exception type here is the one that actually bit: .NET System.Decimal
    shadowing Python's inside the container, raising TypeError from a line that
    passes every test on the dev machine.
    """
    port = FakePort()
    cycle, _, store = make_cycle(tmp_path, port)
    port.fail_next_view = TypeError("No method matches given arguments for .ctor")
    cycle.on_cycle()

    assert cycle.halted
    assert cycle.halt is not None and cycle.halt.kind is HaltKind.MANUAL_CLEARANCE_REQUIRED

    resumed, _, _ = make_cycle(tmp_path, port)
    assert resumed.halted, "an unrecognised failure does NOT clear itself on restart"
    resumed.on_cycle()
    resumed.on_cycle()
    assert port.submitted == [], "no order of any kind"
    assert store.all_records() == []


def test_an_unexpected_exception_with_a_trade_at_risk_halts_durably(tmp_path: Path) -> None:
    """The sequence this policy exists for.

    PAPER session, trade authorised, ENTRY fenced and sent, then an unexpected
    runtime fault. The entry may be live at the broker; a restart must not shrug
    and carry on.
    """
    port = FakePort()
    cycle, coordinator, store = make_cycle(tmp_path, port)
    identity = coordinator.identity

    cycle.on_cycle()
    assert port.count(OrderRole.ENTRY) == 1
    record = store.require(identity.trade_intent_id)
    assert record.arm_consumed
    assert record.orders[identity.entry_order_id].send_fenced

    port.fail_next_view = TypeError("unexpected fault on a broker path")
    cycle.on_cycle()
    assert cycle.halted
    assert cycle.halt is not None and cycle.halt.kind is HaltKind.MANUAL_CLEARANCE_REQUIRED
    assert port.said("execution risk:")
    assert port.said("SURVIVES restart")

    # Restart. The halt is still in force and nothing progresses on its own.
    submitted_before = len(port.submitted)
    resumed, _, _ = make_cycle(tmp_path, port)
    assert resumed.halted, "the halt is durable"
    resumed.on_cycle()
    resumed.on_cycle()
    assert len(port.submitted) == submitted_before, "no recovery progression, no second entry"
    assert port.count(OrderRole.ENTRY) == 1
    assert store.require(identity.trade_intent_id).state is TradeState.ENTRY_SUBMITTED

    # The gates run before any clearance, and they REFUSE here: the entry still
    # holds an unresolved send fence, so nobody can yet say whether it is live.
    with pytest.raises(HaltClearanceError, match="unresolved SEND FENCE"):
        assert_halt_clearable(store.require(identity.trade_intent_id), evidence())

    # The operator reconciles against IBKR by hand; the broker confirms the
    # order exists, which resolves the ambiguity the fence stood for.
    resumed.on_order_event(status_event(port, identity.entry_order_id, EventStatus.SUBMITTED))
    assert (
        store.require(identity.trade_intent_id).orders[identity.entry_order_id].dispatch
        is DispatchState.ACKNOWLEDGED
    ), "the ingestion path stays alive through a halt"

    caveats = assert_halt_clearable(store.require(identity.trade_intent_id), evidence())
    assert caveats
    JsonHaltStore(halt_state_path(tmp_path / "storage")).clear()
    cleared, _, _ = make_cycle(tmp_path, port)
    assert not cleared.halted


@pytest.mark.parametrize(
    "error",
    [ConnectionError("data farm"), TimeoutError("socket")],
    ids=["connection", "timeout"],
)
def test_even_an_enumerated_transient_is_durable_once_a_trade_exists(
    tmp_path: Path, error: Exception
) -> None:
    """The allowlist is pre-trade ONLY. Once anything is at stake it does not apply."""
    port = FakePort()
    cycle, _, _ = make_cycle(tmp_path, port)
    cycle.on_cycle()  # a trade now exists and the entry is fenced

    port.fail_next_view = error
    cycle.on_cycle()
    assert cycle.halt is not None and cycle.halt.kind is HaltKind.MANUAL_CLEARANCE_REQUIRED

    resumed, _, _ = make_cycle(tmp_path, port)
    assert resumed.halted


def test_clearing_a_halt_cannot_revive_a_FAILED_trade(tmp_path: Path) -> None:  # noqa: N802
    """The phrase lifts the DEPLOYMENT latch. It does not lift a lifecycle verdict."""
    port = FakePort()
    cycle, coordinator, store = make_cycle(tmp_path, port)
    identity = coordinator.identity
    cycle.on_cycle()
    port.fill(identity.entry_order_id, 1)
    cycle.on_order_event(fill_event(port, identity.entry_order_id, +1))
    cycle.on_cycle()

    coordinator.fail(store.require(identity.trade_intent_id), "a durable failure")
    cycle.on_cycle()
    assert cycle.halted

    JsonHaltStore(halt_state_path(tmp_path / "storage")).clear()
    submitted_before = len(port.submitted)

    cleared, _, _ = make_cycle(tmp_path, port)
    # Read into locals: narrowing the property would make the second assertion
    # look statically impossible to mypy, when it is exactly the point.
    latch_lifted = cleared.halted
    assert not latch_lifted, "the deployment latch is gone"
    cleared.on_cycle()
    cleared.on_cycle()

    halted_again = cleared.halted
    assert halted_again, "...and the cycle halts again on the FAILED lifecycle"
    assert len(port.submitted) == submitted_before, "no progression, no new order"
    assert store.require(identity.trade_intent_id).state is TradeState.FAILED


def test_clearing_is_refused_while_a_position_is_unprotected(tmp_path: Path) -> None:
    """An unprotected position must not become autonomous by clearing a halt."""
    port = FakePort()
    cycle, coordinator, store = make_cycle(tmp_path, port)
    identity = coordinator.identity
    cycle.on_cycle()
    port.fill(identity.entry_order_id, 1)

    record = store.require(identity.trade_intent_id)
    record, _ = coordinator.apply_entry_fill_and_prepare_protection(
        record,
        client_order_id=identity.entry_order_id,
        fill_id="7-1",
        fill_quantity=1,
        fill_price=SPY_PRICE,
    )
    assert record.open_long_quantity == 1 and record.protected_quantity == 0

    with pytest.raises(HaltClearanceError, match="UNPROTECTED POSITION"):
        assert_halt_clearable(record, evidence())


def test_an_unbound_record_cannot_be_acted_on(tmp_path: Path) -> None:
    port = FakePort()
    cycle, coordinator, store = make_cycle(tmp_path, port)
    cycle.on_cycle()

    record = store.require(coordinator.identity.trade_intent_id)
    store.put(replace(record, account_fingerprint=None))

    resumed, _, _ = make_cycle(tmp_path, port)
    resumed.on_cycle()
    assert resumed.halted
    assert port.count(OrderRole.PROTECTIVE) == 0


# ---------------------------------------------------------------------------
# Round 10 -- LEAN fill quantities are SIGNED
#
# The defect: `_apply_event` filtered on `fill_quantity <= 0`, so every
# protective and exit SELL fill was silently discarded. Durable state went on
# believing it held a position the broker had already closed, and the next
# reconciliation halted on a disagreement the system had caused itself.
# ---------------------------------------------------------------------------


def test_A_entry_fill_positive_records_and_protects(tmp_path: Path) -> None:  # noqa: N802
    port = FakePort()
    cycle, coordinator, store = make_cycle(tmp_path, port)
    identity = coordinator.identity
    cycle.on_cycle()

    port.fill(identity.entry_order_id, 1)
    cycle.on_order_event(fill_event(port, identity.entry_order_id, +1))

    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.entry_order_id].filled_quantity == 1
    assert persisted.open_long_quantity == 1
    assert sum(1 for o in persisted.orders.values() if o.role is OrderRole.PROTECTIVE) == 1
    assert port.count(OrderRole.PROTECTIVE) == 1
    assert not cycle.halted


def test_B_exit_fill_negative_closes_the_position(tmp_path: Path) -> None:  # noqa: N802
    """The reproduction from the review: EXIT SELL -1 left the record at long 1."""
    port = FakePort()
    cycle, coordinator, store = make_cycle(tmp_path, port)
    identity = coordinator.identity
    cycle.on_cycle()
    port.fill(identity.entry_order_id, 1)
    cycle.on_order_event(fill_event(port, identity.entry_order_id, +1))
    cycle.on_cycle()

    exiting, _, _ = make_cycle(tmp_path, port, exit_requested=True)
    exiting.on_cycle()
    port.confirm_cancel(identity.protective_order_id)
    exiting.on_order_event(status_event(port, identity.protective_order_id, EventStatus.CANCELED))
    exiting.on_cycle()
    assert port.count(OrderRole.EXIT) == 1

    port.fill(identity.exit_order_id, 1)  # the broker goes flat
    exiting.on_order_event(fill_event(port, identity.exit_order_id, -1))

    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.exit_order_id].filled_quantity == 1
    assert persisted.open_long_quantity == 0
    assert persisted.state is TradeState.CLOSED

    exiting.on_cycle()  # fresh snapshot
    assert store.require(identity.trade_intent_id).state is TradeState.RECONCILED
    assert not exiting.halted
    assert port.position == 0, "flat, and never short"


def test_C_protective_fill_negative_closes_the_position(tmp_path: Path) -> None:  # noqa: N802
    """A stop that fires is a legitimate exit -- and must not trigger a second SELL."""
    port = FakePort()
    cycle, coordinator, store = make_cycle(tmp_path, port)
    identity = coordinator.identity
    cycle.on_cycle()
    port.fill(identity.entry_order_id, 1)
    cycle.on_order_event(fill_event(port, identity.entry_order_id, +1))
    cycle.on_cycle()
    assert store.require(identity.trade_intent_id).state is TradeState.PROTECTED

    port.fill(identity.protective_order_id, 1)  # the stop fires; broker goes flat
    cycle.on_order_event(fill_event(port, identity.protective_order_id, -1, fill_id="8-1"))

    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.protective_order_id].filled_quantity == 1
    assert persisted.protective_fill_quantity == 1
    assert persisted.open_long_quantity == 0
    assert persisted.state is TradeState.CLOSED

    exiting, _, _ = make_cycle(tmp_path, port, exit_requested=True)
    exiting.on_cycle()
    assert port.count(OrderRole.EXIT) == 0, "no SELL for a position the stop already sold"
    assert store.require(identity.trade_intent_id).state is TradeState.RECONCILED
    assert not exiting.halted
    assert port.position == 0, "flat, and never short"


def at_entry_filled(tmp_path: Path, port: FakePort) -> tuple[Phase2Cycle, Phase2Coordinator]:
    cycle, coordinator, _ = make_cycle(tmp_path, port)
    cycle.on_cycle()
    port.fill(coordinator.identity.entry_order_id, 1)
    cycle.on_order_event(fill_event(port, coordinator.identity.entry_order_id, +1))
    cycle.on_cycle()
    return cycle, coordinator


def test_D_entry_filling_NEGATIVE_is_refused(tmp_path: Path) -> None:  # noqa: N802
    """A BUY that reports a short fill means our record and the broker disagree."""
    port = FakePort()
    cycle, coordinator, store = make_cycle(tmp_path, port)
    identity = coordinator.identity
    cycle.on_cycle()

    cycle.on_order_event(fill_event(port, identity.entry_order_id, -1))

    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.entry_order_id].filled_quantity == 0, "not applied"
    assert persisted.open_long_quantity == 0
    assert cycle.halted
    assert cycle.halt is not None and cycle.halt.kind is HaltKind.MANUAL_CLEARANCE_REQUIRED
    assert port.said("CONTRADICTORY-FILL")
    assert port.count(OrderRole.PROTECTIVE) == 0


def test_E_protective_filling_POSITIVE_is_refused(tmp_path: Path) -> None:  # noqa: N802
    port = FakePort()
    cycle, coordinator = at_entry_filled(tmp_path, port)
    identity = coordinator.identity
    store = JsonTradeStateStore(tmp_path / "storage" / "phase2_trade_state.json")

    cycle.on_order_event(fill_event(port, identity.protective_order_id, +1, fill_id="8-1"))

    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.protective_order_id].filled_quantity == 0, "not applied"
    assert persisted.open_long_quantity == 1, "the long is untouched"
    assert cycle.halted
    assert cycle.halt is not None and cycle.halt.kind is HaltKind.MANUAL_CLEARANCE_REQUIRED
    assert port.said("CONTRADICTORY-FILL")


def test_F_exit_filling_POSITIVE_is_refused(tmp_path: Path) -> None:  # noqa: N802
    port = FakePort()
    _cycle, coordinator = at_entry_filled(tmp_path, port)
    identity = coordinator.identity
    store = JsonTradeStateStore(tmp_path / "storage" / "phase2_trade_state.json")

    exiting, _, _ = make_cycle(tmp_path, port, exit_requested=True)
    exiting.on_cycle()
    port.confirm_cancel(identity.protective_order_id)
    exiting.on_order_event(status_event(port, identity.protective_order_id, EventStatus.CANCELED))
    exiting.on_cycle()
    assert port.count(OrderRole.EXIT) == 1

    exiting.on_order_event(fill_event(port, identity.exit_order_id, +1, fill_id="9-1"))

    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.exit_order_id].filled_quantity == 0, "not applied"
    assert persisted.open_long_quantity == 1
    assert exiting.halted
    assert exiting.halt is not None and exiting.halt.kind is HaltKind.MANUAL_CLEARANCE_REQUIRED
    assert port.said("CONTRADICTORY-FILL")


def test_G_a_repeated_signed_SELL_fill_is_a_true_no_op(tmp_path: Path) -> None:  # noqa: N802
    port = FakePort()
    cycle, coordinator = at_entry_filled(tmp_path, port)
    identity = coordinator.identity
    store = JsonTradeStateStore(tmp_path / "storage" / "phase2_trade_state.json")

    port.fill(identity.protective_order_id, 1)
    for _ in range(4):
        cycle.on_order_event(fill_event(port, identity.protective_order_id, -1, fill_id="8-1"))

    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.protective_order_id].filled_quantity == 1
    assert persisted.open_long_quantity == 0
    assert persisted.state is TradeState.CLOSED
    assert not cycle.halted
    assert port.position == 0


# ---------------------------------------------------------------------------
# Round 11 -- ownership after a restart, when the LEAN tag is gone
#
# Reproduced from a real IBKR Paper reconnect: LEAN re-hydrated our protective
# stop correctly, but the tag -- where the client order id lives -- is never
# sent to IBKR, so it came back blank with a NEW LEAN order id. Only the broker
# id was the same. Ownership by tag alone stranded a live protected position.
# ---------------------------------------------------------------------------


def protected_then_restarted(
    tmp_path: Path, port: FakePort
) -> tuple[Phase2Cycle, Phase2Coordinator, JsonTradeStateStore]:
    """Drive to PROTECTED, then model LEAN losing the tag on a restart."""
    cycle, coordinator, store = make_cycle(tmp_path, port)
    identity = coordinator.identity
    cycle.on_cycle()
    port.fill(identity.entry_order_id, 1)
    cycle.on_order_event(fill_event(port, identity.entry_order_id, +1))
    cycle.on_cycle()
    assert store.require(identity.trade_intent_id).state is TradeState.PROTECTED

    durable = store.require(identity.trade_intent_id).orders[identity.protective_order_id]
    assert durable.broker_order_ids, "the broker id must be captured BEFORE the restart"

    port.rehydrate()
    assert port.orders[identity.protective_order_id].tag == "", "the tag is gone"
    resumed, resumed_coordinator, _ = make_cycle(tmp_path, port)
    return resumed, resumed_coordinator, store


def test_a_tagless_rehydrated_protective_is_recognised_by_broker_id(tmp_path: Path) -> None:
    """The live failure, now passing. Read-only: nothing is sent."""
    port = FakePort()
    resumed, coordinator, store = protected_then_restarted(tmp_path, port)
    identity = coordinator.identity
    submitted_before = len(port.submitted)

    resumed.on_cycle()
    resumed.on_cycle()

    resolved = resumed._resolved_view(store.require(identity.trade_intent_id))
    owned = resolved.orders_owned_by(identity)
    assert [o.client_order_id for o in owned] == [identity.protective_order_id]
    assert owned[0].ownership is OwnershipBasis.BROKER_ID
    assert resolved.open_protective_quantity(identity) == 1

    persisted = store.require(identity.trade_intent_id)
    assert persisted.state is TradeState.PROTECTED
    assert persisted.protected_quantity == 1
    assert not resumed.halted, "reconciliation agrees again"
    assert len(port.submitted) == submitted_before, "zero re-dispatch, zero new ENTRY"
    assert port.cancelled_lean_ids == [], "zero cancellations"
    assert port.count(OrderRole.EXIT) == 0


def test_a_tagless_protective_CANCELED_event_maps_to_the_durable_order(  # noqa: N802
    tmp_path: Path,
) -> None:
    port = FakePort()
    resumed, coordinator, store = protected_then_restarted(tmp_path, port)
    identity = coordinator.identity
    resumed.on_cycle()

    # Someone cancels it at the broker. The event arrives with no tag.
    port.confirm_cancel(identity.protective_order_id)
    resumed.on_order_event(status_event(port, identity.protective_order_id, EventStatus.CANCELED))

    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.protective_order_id].dispatch is DispatchState.CANCELLED
    assert persisted.protected_quantity == 0
    assert persisted.state is TradeState.FAILED, "unrequested: protection vanished"
    assert resumed.halted


def test_a_tagless_protective_negative_fill_closes_the_long(tmp_path: Path) -> None:
    """The stop fires after a restart. It must still close the position."""
    port = FakePort()
    resumed, coordinator, store = protected_then_restarted(tmp_path, port)
    identity = coordinator.identity
    resumed.on_cycle()

    port.fill(identity.protective_order_id, 1)
    resumed.on_order_event(fill_event(port, identity.protective_order_id, -1, fill_id="8-1"))

    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.protective_order_id].filled_quantity == 1
    assert persisted.open_long_quantity == 0
    assert persisted.state is TradeState.CLOSED
    assert port.position == 0, "flat, never short"

    exiting, _, _ = make_cycle(tmp_path, port, exit_requested=True)
    exiting.on_cycle()
    assert port.count(OrderRole.EXIT) == 0, "no SELL for what the stop already sold"


def test_a_tagless_protective_INVALID_event_maps_and_fails_closed(  # noqa: N802
    tmp_path: Path,
) -> None:
    port = FakePort()
    resumed, coordinator, store = protected_then_restarted(tmp_path, port)
    identity = coordinator.identity
    resumed.on_cycle()

    resumed.on_order_event(status_event(port, identity.protective_order_id, EventStatus.INVALID))

    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.protective_order_id].dispatch is DispatchState.REJECTED
    assert persisted.state is TradeState.FAILED
    assert persisted.open_long_quantity == 1
    assert resumed.halted
    assert resumed.halt is not None and resumed.halt.manual_clear_required


def test_cancellation_after_a_restart_targets_the_rehydrated_order(tmp_path: Path) -> None:
    """Addressed by the CURRENT LEAN order id, resolved from the broker id."""
    port = FakePort()
    _resumed, coordinator, _store = protected_then_restarted(tmp_path, port)
    identity = coordinator.identity
    new_lean_id = port.orders[identity.protective_order_id].lean_order_id

    exiting, _, _ = make_cycle(tmp_path, port, exit_requested=True)
    exiting.on_cycle()

    assert port.cancelled_lean_ids == [new_lean_id]
    assert not exiting.halted


def test_a_foreign_identical_stop_is_never_cancelled(tmp_path: Path) -> None:
    """Same symbol, same side, same quantity, same stop price -- and not ours."""
    port = FakePort()
    resumed, coordinator, store = protected_then_restarted(tmp_path, port)
    identity = coordinator.identity
    ours = port.orders[identity.protective_order_id]

    # A stranger's stop that is indistinguishable by shape.
    port.orders["foreign-stop"] = replace(
        ours, tag="", broker_order_ids=("9999",), lean_order_id="77"
    )
    port.open_ids.add("foreign-stop")

    resolved = resumed._resolved_view(store.require(identity.trade_intent_id))
    foreign = [o for o in resolved.open_orders if o.lean_order_id == "77"]
    assert len(foreign) == 1
    assert foreign[0].ownership is OwnershipBasis.NONE
    assert foreign[0].client_order_id.startswith("<foreign-")

    exiting, _, _ = make_cycle(tmp_path, port, exit_requested=True)
    exiting.on_cycle()
    assert "77" not in port.cancelled_lean_ids, "a stranger order must never be cancelled"
