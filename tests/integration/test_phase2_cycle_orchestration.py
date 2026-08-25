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
from kalpamani.execution.halt import HaltKind, JsonHaltStore, halt_state_path
from kalpamani.execution.identity import OrderRole, TradeIdentity
from kalpamani.execution.lifecycle import TradeState
from kalpamani.execution.reconciliation import (
    BrokerOrderView,
    BrokerPositionView,
    BrokerView,
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
        self.working: dict[str, BrokerOrderView] = {}
        self.submitted: list[OrderRequest] = []
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
            open_orders=tuple(self.working.values()),
        )

    def submit(self, request: OrderRequest) -> None:
        self.submitted.append(request)
        self.working[request.client_order_id] = BrokerOrderView(
            client_order_id=request.client_order_id,
            symbol=request.symbol,
            side=request.side.value,
            quantity=request.quantity,
            is_open=True,
        )

    def cancel(self, client_order_id: str) -> None:
        self.cancelled.append(client_order_id)

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
        order = self.working.pop(client_order_id)
        self.position += quantity if order.side == "BUY" else -quantity

    def confirm_cancel(self, client_order_id: str) -> None:
        self.working.pop(client_order_id, None)

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


def fill_event(client_order_id: str, quantity: int = 1, fill_id: str = "7-1") -> OrderEventFacts:
    return OrderEventFacts(
        client_order_id=client_order_id,
        status=EventStatus.FILL,
        fill_quantity=quantity,
        fill_price=SPY_PRICE,
        fill_id=fill_id,
    )


def status_event(client_order_id: str, status: EventStatus) -> OrderEventFacts:
    return OrderEventFacts(client_order_id=client_order_id, status=status)


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
    cycle.on_order_event(fill_event(identity.entry_order_id))
    assert port.count(OrderRole.PROTECTIVE) == 1
    protective = port.submitted[-1]
    assert protective.stop_price == (SPY_PRICE * Decimal("0.90")).quantize(Decimal("0.01"))

    # Cycle 2: a fresh snapshot shows the stop working, so it is adopted.
    cycle.on_cycle()
    assert store.require(identity.trade_intent_id).state is TradeState.PROTECTED

    # The operator redeploys asking for the exit. Same durable state.
    exiting, _, _ = make_cycle(tmp_path, port, exit_requested=True)
    exiting.on_cycle()
    assert port.cancelled == [identity.protective_order_id]

    # CANCEL_PENDING is not confirmation.
    exiting.on_order_event(status_event(identity.protective_order_id, EventStatus.CANCEL_PENDING))
    assert store.require(identity.trade_intent_id).protected_quantity == 1

    port.confirm_cancel(identity.protective_order_id)
    exiting.on_order_event(status_event(identity.protective_order_id, EventStatus.CANCELED))
    assert store.require(identity.trade_intent_id).protected_quantity == 0
    assert not exiting.halted, "a REQUESTED cancellation is expected, not a failure"

    exiting.on_cycle()
    assert port.count(OrderRole.EXIT) == 1

    port.fill(identity.exit_order_id, 1)
    exiting.on_order_event(fill_event(identity.exit_order_id, fill_id="9-1"))
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
    cycle.on_order_event(fill_event(identity.entry_order_id))
    cycle.on_cycle()

    # The session is now closed outright -- no entry could be authorised.
    port.session_open, port.minutes_to_close = False, None

    exiting, _, _ = make_cycle(tmp_path, port, exit_requested=True)
    exiting.on_cycle()
    assert port.cancelled == [identity.protective_order_id]
    port.confirm_cancel(identity.protective_order_id)
    exiting.on_order_event(status_event(identity.protective_order_id, EventStatus.CANCELED))
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
    foreign.on_order_event(fill_event(identity.entry_order_id))

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
    cycle.on_order_event(fill_event(identity.entry_order_id))

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
    cycle.on_order_event(fill_event(identity.entry_order_id))

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
    cycle.on_order_event(fill_event(identity.entry_order_id))
    cycle.on_cycle()

    record = store.require(identity.trade_intent_id)
    coordinator.fail(record, "an unrelated durable failure")

    # The stop fires after the failure. That closes the long, and pretending
    # otherwise would leave us believing we still hold it.
    port.fill(identity.protective_order_id, 1)
    cycle.on_order_event(fill_event(identity.protective_order_id, fill_id="8-1"))

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
    cycle.on_order_event(fill_event(identity.entry_order_id))

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
    cycle.on_order_event(fill_event(identity.entry_order_id))
    cycle.on_cycle()

    # The stop is cancelled by someone else. Protection vanished; that is a
    # safety violation and needs a human.
    port.confirm_cancel(identity.protective_order_id)
    cycle.on_order_event(status_event(identity.protective_order_id, EventStatus.CANCELED))
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


def test_a_transient_halt_does_not_become_a_permanent_chore(tmp_path: Path) -> None:
    """Not every hiccup should need a human. An operator who has to clear a halt
    after each blip stops reading them."""
    port = FakePort()
    cycle, _, _ = make_cycle(tmp_path, port)
    port.fail_next_view = RuntimeError("transport blip")
    cycle.on_cycle()
    assert cycle.halted
    assert cycle.halt is not None and cycle.halt.kind is HaltKind.SESSION

    resumed, _, _ = make_cycle(tmp_path, port)
    assert not resumed.halted, "a restart may retry a transient fault"
    resumed.on_cycle()
    assert port.count(OrderRole.ENTRY) == 1


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
