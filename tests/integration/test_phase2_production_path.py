"""Production-path orchestration tests: drive the real coordinator, not a re-creation.

These call the *same* :class:`Phase2Coordinator` methods `main.py` calls, and
every durable write is the production one. Each test corresponds to a defect a
review identified.

The dispatch protocol under test:

    pending = coordinator.begin_*(...)      # intent durably recorded
    coordinator.fence_dispatch(...)         # SEND FENCE durable -- BEFORE the call
    broker.submit(pending)                  # the broker call
    coordinator.reconcile(...)              # broker evidence adopted -> ACKNOWLEDGED
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from kalpamani.common.environment import Environment
from kalpamani.common.settings import Settings
from kalpamani.execution.coordinator import PendingOrder, Phase2Coordinator
from kalpamani.execution.envelope import (
    PHASE2_CONFIRMATION_PHRASE,
    PHASE2_INTENT_NATURAL_KEY,
    PHASE2_QUANTITY,
    PHASE2_SYMBOL,
    ExecutionArmRequest,
)
from kalpamani.execution.identity import OrderRole, TradeIdentity
from kalpamani.execution.lifecycle import LifecycleError, TradeState
from kalpamani.execution.reconciliation import (
    BrokerOrderView,
    BrokerPositionView,
    BrokerView,
    OwnershipBasis,
    ReconciliationError,
    UnprotectedPositionError,
)
from kalpamani.execution.session import (
    ArmReceipt,
    ArmReceiptError,
    BrokerSessionEvidence,
    SessionVerificationError,
    account_fingerprint,
    assert_arm_available,
    verify_paper_session,
    write_arm_receipt,
)
from kalpamani.execution.state_store import (
    DispatchState,
    JsonTradeStateStore,
    StaleWriteError,
    TradeRecord,
)

pytestmark = pytest.mark.integration

SPY_PRICE = Decimal("766.38")
PAPER_ACCOUNT_ID = "DU1234567"
#: A SECOND paper account. Same broker, same mode, different account -- the case
#: a mode-only check cannot see.
OTHER_PAPER_ACCOUNT_ID = "DU7654321"
LIVE_ACCOUNT_ID = "U7654321"


def evidence(
    account_id: str = PAPER_ACCOUNT_ID, trading_mode: str = "paper"
) -> BrokerSessionEvidence:
    return BrokerSessionEvidence(
        account_id=account_id, trading_mode=trading_mode, source="test-deployment-config"
    )


def arm_request() -> ExecutionArmRequest:
    return ExecutionArmRequest(
        confirmation=PHASE2_CONFIRMATION_PHRASE,
        settings=Settings(environment=Environment.PAPER),
        session_evidence=evidence(),
        symbol=PHASE2_SYMBOL,
        quantity=PHASE2_QUANTITY,
        reference_price=SPY_PRICE,
        phase2_test_mode=True,
        explicit_execution_arm=True,
    )


class Broker:
    """In-memory broker double. Counts submissions and cancel requests by role."""

    def __init__(self) -> None:
        self.position = 0
        self.working: dict[str, BrokerOrderView] = {}
        self.submissions: list[tuple[OrderRole, str]] = []
        self.cancel_requests: list[str] = []

    def submit(self, pending: PendingOrder) -> None:
        request = pending.request
        self.submissions.append((request.role, request.client_order_id))
        self.working[request.client_order_id] = BrokerOrderView(
            ownership=OwnershipBasis.TAG,
            client_order_id=request.client_order_id,
            symbol=request.symbol,
            side=request.side.value,
            quantity=request.quantity,
            is_open=True,
        )

    def fill(self, client_order_id: str, quantity: int) -> None:
        order = self.working.pop(client_order_id)
        self.position += quantity if order.side == "BUY" else -quantity

    def request_cancel(self, client_order_id: str) -> None:
        """Record the request. The order keeps working until `confirm_cancel`."""
        self.cancel_requests.append(client_order_id)

    def confirm_cancel(self, client_order_id: str) -> None:
        self.working.pop(client_order_id, None)

    def count(self, role: OrderRole) -> int:
        return sum(1 for r, _ in self.submissions if r is role)

    def view(self) -> BrokerView:
        return BrokerView(
            positions=(BrokerPositionView(PHASE2_SYMBOL, self.position),),
            open_orders=tuple(self.working.values()),
        )


def make_coordinator(
    tmp_path: Path, *, account_id: str = PAPER_ACCOUNT_ID, trading_mode: str = "paper"
) -> tuple[Phase2Coordinator, JsonTradeStateStore, Path, Path]:
    """A coordinator whose CURRENT session is the given account.

    The session provider stands in for LEAN's deployment configuration, so a
    test can present a different account -- LIVE, or a second paper account --
    and prove nothing reaches the broker.
    """
    storage = tmp_path / "storage"
    project = tmp_path / "project"
    storage.mkdir()
    project.mkdir()
    store = JsonTradeStateStore(storage / "phase2_trade_state.json")
    identity = TradeIdentity.derive(PHASE2_INTENT_NATURAL_KEY, attempt=1)
    coordinator = Phase2Coordinator(
        store,
        identity,
        storage_root=storage,
        project_root=project,
        session_provider=lambda: evidence(account_id, trading_mode),
    )
    return coordinator, store, storage, project


def dispatch(coordinator: Phase2Coordinator, broker: Broker, pending: PendingOrder) -> TradeRecord:
    """The full production dispatch protocol, as main.py performs it.

    FENCE FIRST, then the broker call. That ordering is the whole point.
    """
    record = coordinator.fence_dispatch(pending.record, pending.request.client_order_id)
    broker.submit(pending)
    return record


def fence_only(coordinator: Phase2Coordinator, pending: PendingOrder) -> TradeRecord:
    """Acquire the fence and stop -- simulating a crash before the broker call."""
    return coordinator.fence_dispatch(pending.record, pending.request.client_order_id)


def drive_to_protected(coordinator: Phase2Coordinator, broker: Broker) -> TradeRecord:
    """Run the real production path up to a broker-confirmed PROTECTED position.

    This is THE happy path every downstream lifecycle, failure and restart test
    builds on, so it uses the exact orchestration `main.py` performs -- entry
    fill and protective intent in ONE atomic call. It previously used the older
    ``on_fill`` + ``plan_protection`` pair, which meant a large part of the suite
    was validating a second, pseudo-production sequence that production no longer
    takes.
    """
    record = coordinator.authorize(arm_request(), evidence())

    pending = coordinator.begin_entry(record)
    record = dispatch(coordinator, broker, pending)
    broker.fill(pending.request.client_order_id, PHASE2_QUANTITY)

    record, protection = coordinator.apply_entry_fill_and_prepare_protection(
        record,
        client_order_id=pending.request.client_order_id,
        fill_id="7-1",
        fill_quantity=PHASE2_QUANTITY,
        fill_price=SPY_PRICE,
    )
    assert protection is not None

    record = dispatch(coordinator, broker, protection)
    record = coordinator.reconcile(record, broker.view())  # adopts -> ACKNOWLEDGED
    return coordinator.confirm_protection(record, broker.view())


# ---------------------------------------------------------------------------
# Lifecycle transitions are actually PERSISTED
# ---------------------------------------------------------------------------


def test_production_path_persists_every_lifecycle_transition(tmp_path: Path) -> None:
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    record = coordinator.authorize(arm_request(), evidence())
    assert store.require(identity.trade_intent_id).state is TradeState.AUTHORIZED

    pending = coordinator.begin_entry(record)
    assert store.require(identity.trade_intent_id).state is TradeState.ENTRY_SUBMITTED
    record = dispatch(coordinator, broker, pending)

    # ONE write. There is deliberately no durable moment where the long is
    # filled and no protective intent exists, so FILLED is not observable here.
    record, protection = fill_entry_atomically(coordinator, broker, record)
    assert protection is not None
    assert record.filled_quantity == 1
    assert store.require(identity.trade_intent_id).state is TradeState.PROTECTION_SUBMITTED
    record = dispatch(coordinator, broker, protection)
    record = coordinator.reconcile(record, broker.view())
    record = coordinator.confirm_protection(record, broker.view())
    assert store.require(identity.trade_intent_id).state is TradeState.PROTECTED

    record = coordinator.request_exit(record)
    assert store.require(identity.trade_intent_id).state is TradeState.EXIT_REQUESTED

    record, should_cancel = coordinator.begin_protection_cancel(record)
    assert should_cancel is True
    broker.request_cancel(identity.protective_order_id)
    broker.confirm_cancel(identity.protective_order_id)
    record = coordinator.on_order_cancelled(record, identity.protective_order_id)
    assert store.require(identity.trade_intent_id).protected_quantity == 0

    exit_order = coordinator.begin_exit(record, broker.view())
    assert store.require(identity.trade_intent_id).state is TradeState.EXIT_SUBMITTED
    record = dispatch(coordinator, broker, exit_order)
    broker.fill(identity.exit_order_id, 1)
    record = coordinator.on_fill(
        record, client_order_id=identity.exit_order_id, fill_id="9-1", fill_quantity=1
    )
    assert store.require(identity.trade_intent_id).state is TradeState.CLOSED

    record = coordinator.finalize(record, broker.view())
    assert store.require(identity.trade_intent_id).state is TradeState.RECONCILED
    assert broker.position == 0
    assert broker.count(OrderRole.ENTRY) == 1


# ---------------------------------------------------------------------------
# Round 3 item 1 -- CANCEL_PENDING is NOT CANCELED
# ---------------------------------------------------------------------------


def test_cancel_pending_does_not_confirm_cancellation(tmp_path: Path) -> None:
    """LEAN emits CANCEL_PENDING before CANCELED. Only the latter may confirm.

    `main.py` calls confirm only on an exact CANCELED status, so a pending
    cancellation must leave durable state completely unchanged.
    """
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)

    record = coordinator.request_exit(record)
    record, _ = coordinator.begin_protection_cancel(record)
    broker.request_cancel(identity.protective_order_id)  # CANCEL_PENDING: still working

    persisted = store.require(identity.trade_intent_id)
    protective = persisted.orders[identity.protective_order_id]
    assert protective.cancel_requested is True
    assert protective.dispatch is DispatchState.ACKNOWLEDGED, "still working, NOT cancelled"
    assert persisted.protected_quantity == 1
    coordinator.reconcile(persisted, broker.view())  # must still agree

    with pytest.raises(ReconciliationError):
        coordinator.begin_exit(persisted, broker.view())


def test_canceled_confirms_cancellation(tmp_path: Path) -> None:
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)
    record = coordinator.request_exit(record)
    record, _ = coordinator.begin_protection_cancel(record)

    broker.confirm_cancel(identity.protective_order_id)
    record = coordinator.on_order_cancelled(record, identity.protective_order_id)

    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.protective_order_id].dispatch is DispatchState.CANCELLED
    assert persisted.protected_quantity == 0
    coordinator.reconcile(persisted, broker.view())
    assert coordinator.begin_exit(persisted, broker.view()).request.quantity == 1


def test_cancelling_a_foreign_order_id_is_ignored(tmp_path: Path) -> None:
    """An event for an order we do not have on record must change nothing."""
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)

    unchanged = coordinator.on_order_cancelled(record, "km-deadbeef-EXIT-0")
    assert unchanged is record

    persisted = store.require(identity.trade_intent_id)
    protective = persisted.orders[identity.protective_order_id]
    assert protective.dispatch is DispatchState.ACKNOWLEDGED
    assert persisted.protected_quantity == 1


# ---------------------------------------------------------------------------
# Round 3 item 2 -- the broker cancel is requested exactly once
# ---------------------------------------------------------------------------


def test_cancel_requested_exactly_once_across_many_cycles(tmp_path: Path) -> None:
    """Repeated cycles while cancellation is pending must not re-ask the broker."""
    coordinator, _, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)
    record = coordinator.request_exit(record)

    for _ in range(10):  # ten reconciliation cycles, cancellation still pending
        record, should_cancel = coordinator.begin_protection_cancel(record)
        if should_cancel:
            broker.request_cancel(identity.protective_order_id)

    assert broker.cancel_requests == [identity.protective_order_id]
    assert len(broker.cancel_requests) == 1


# ---------------------------------------------------------------------------
# Round 3 item 3 -- dispatch-gap recovery at all three boundaries
# ---------------------------------------------------------------------------


def test_protective_intent_never_dispatched_is_reported_unprotected(tmp_path: Path) -> None:
    """Crash between the protective write-ahead and the broker call.

    The old model called this "submitted" and looked healthy. It must instead be
    recognised as an UNPROTECTED long, with a safe deterministic re-dispatch.
    """
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    record = coordinator.authorize(arm_request(), evidence())
    pending = coordinator.begin_entry(record)
    record = dispatch(coordinator, broker, pending)
    record, protection = fill_entry_atomically(coordinator, broker, record)
    assert protection is not None  # intent recorded... and then we crash.

    persisted = store.require(identity.trade_intent_id)
    protective = persisted.orders[identity.protective_order_id]
    assert protective.dispatch is DispatchState.INTENT_RECORDED
    assert persisted.protected_quantity == 0, "an undispatched intent is NOT protection"

    plan = coordinator.assess_recovery(persisted, broker.view())
    assert any("UNPROTECTED" in note for note in plan.notes)
    assert [p.request.role for p in plan.redispatch] == [OrderRole.PROTECTIVE]
    assert plan.redispatch[0].request.stop_price is not None


def test_exit_intent_never_dispatched_is_redispatched(tmp_path: Path) -> None:
    """The gap the previous round left: an unprotected long with no exit sent."""
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)
    record = coordinator.request_exit(record)
    record, _ = coordinator.begin_protection_cancel(record)
    broker.confirm_cancel(identity.protective_order_id)
    record = coordinator.on_order_cancelled(record, identity.protective_order_id)

    coordinator.begin_exit(record, broker.view())  # recorded, then we crash

    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.exit_order_id].dispatch is DispatchState.INTENT_RECORDED

    plan = coordinator.assess_recovery(persisted, broker.view())
    assert [p.request.role for p in plan.redispatch] == [OrderRole.EXIT]
    assert any("EXIT intent never fenced" in n for n in plan.notes)
    assert broker.count(OrderRole.EXIT) == 0, "still not sent twice"


def test_entry_intent_never_dispatched_fails_closed(tmp_path: Path) -> None:
    """No position is at risk, so re-entering is a human decision, not an automatic one."""
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    record = coordinator.authorize(arm_request(), evidence())
    coordinator.begin_entry(record)  # recorded, then we crash

    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.entry_order_id].dispatch is DispatchState.INTENT_RECORDED
    with pytest.raises(ReconciliationError, match="never fenced"):
        coordinator.assess_recovery(persisted, broker.view())


def test_ambiguous_dispatch_never_resends(tmp_path: Path) -> None:
    """Dispatch attempted, broker silent. The order may be live: never resend."""
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    record = coordinator.authorize(arm_request(), evidence())
    pending = coordinator.begin_entry(record)
    # Fence acquired; the broker shows nothing and never acknowledged.
    coordinator.fence_dispatch(pending.record, identity.entry_order_id)

    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.entry_order_id].dispatch_outcome_unknown is True
    with pytest.raises(ReconciliationError, match="Send fence held"):
        coordinator.assess_recovery(persisted, broker.view())
    assert broker.count(OrderRole.ENTRY) == 0


def test_broker_evidence_promotes_dispatched_order_to_acknowledged(tmp_path: Path) -> None:
    """Reconciliation is what resolves the ambiguous window."""
    coordinator, _, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    record = coordinator.authorize(arm_request(), evidence())
    pending = coordinator.begin_entry(record)
    record = dispatch(coordinator, broker, pending)
    assert record.orders[identity.entry_order_id].dispatch is DispatchState.SEND_FENCED

    record = coordinator.adopt_broker_evidence(record, broker.view())
    assert record.orders[identity.entry_order_id].dispatch is DispatchState.ACKNOWLEDGED


# ---------------------------------------------------------------------------
# Round 3 item 5 -- INVALID / rejected orders
# ---------------------------------------------------------------------------


def test_rejected_protective_order_is_unprotected_position(tmp_path: Path) -> None:
    coordinator, _, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    record = coordinator.authorize(arm_request(), evidence())
    pending = coordinator.begin_entry(record)
    record = dispatch(coordinator, broker, pending)
    record, protection = fill_entry_atomically(coordinator, broker, record)
    assert protection is not None
    record = dispatch(coordinator, broker, protection)

    with pytest.raises(UnprotectedPositionError, match="REJECTED"):
        coordinator.on_order_rejected(record, identity.protective_order_id)


def test_rejected_exit_order_with_open_long_is_unprotected_position(tmp_path: Path) -> None:
    coordinator, _, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)
    record = coordinator.request_exit(record)
    record, _ = coordinator.begin_protection_cancel(record)
    broker.confirm_cancel(identity.protective_order_id)
    record = coordinator.on_order_cancelled(record, identity.protective_order_id)
    exit_order = coordinator.begin_exit(record, broker.view())
    record = dispatch(coordinator, broker, exit_order)

    with pytest.raises(UnprotectedPositionError, match="REJECTED"):
        coordinator.on_order_rejected(record, identity.exit_order_id)


def test_rejected_entry_is_not_an_unprotected_position(tmp_path: Path) -> None:
    """No fill, no position, no exposure -- and never an automatic second entry."""
    coordinator, _, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    record = coordinator.authorize(arm_request(), evidence())
    pending = coordinator.begin_entry(record)
    record = dispatch(coordinator, broker, pending)

    record = coordinator.on_order_rejected(record, identity.entry_order_id)
    assert record.orders[identity.entry_order_id].dispatch is DispatchState.REJECTED
    assert record.open_long_quantity == 0
    # A rejected entry still counts as an entry: no automatic second one, ever.
    with pytest.raises(ReconciliationError, match="second entry"):
        coordinator.begin_entry(record)


# ---------------------------------------------------------------------------
# Round 3 item 4 -- the arm receipt is genuinely redundant
# ---------------------------------------------------------------------------


def sample_receipt() -> ArmReceipt:
    return ArmReceipt(
        trade_intent_id="ti-test",
        account_fingerprint=account_fingerprint(PAPER_ACCOUNT_ID),
        consumed=True,
    )


def test_both_receipt_locations_written_and_verified(tmp_path: Path) -> None:
    paths = (tmp_path / "a" / "r.json", tmp_path / "b" / "r.json")
    write_arm_receipt(sample_receipt(), paths)
    for path in paths:
        assert path.is_file()
        assert ArmReceipt.from_json(path.read_text(encoding="utf-8")) == sample_receipt()


@pytest.mark.parametrize("blocked_index", [0, 1])
def test_arm_refused_if_either_location_cannot_be_written(
    tmp_path: Path, blocked_index: int
) -> None:
    """A partial write is not redundancy, so it must refuse rather than proceed."""
    good = tmp_path / "good" / "r.json"
    blocker = tmp_path / "blocker"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    blocked = blocker / "r.json"

    paths = (blocked, good) if blocked_index == 0 else (good, blocked)
    with pytest.raises(ArmReceiptError):
        write_arm_receipt(sample_receipt(), paths)


def test_receipts_disagreeing_on_consumed_fail_closed(tmp_path: Path) -> None:
    """One says consumed, one says not. That ambiguity could permit a replay."""
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(sample_receipt().to_json(), encoding="utf-8")
    b.write_text(
        ArmReceipt(
            trade_intent_id="ti-test",
            account_fingerprint=account_fingerprint(PAPER_ACCOUNT_ID),
            consumed=False,
        ).to_json(),
        encoding="utf-8",
    )
    with pytest.raises(ArmReceiptError, match="disagree"):
        assert_arm_available((a, b), trade_state_present=True)


def test_matching_receipts_with_state_present_pass(tmp_path: Path) -> None:
    paths = (tmp_path / "a.json", tmp_path / "b.json")
    write_arm_receipt(sample_receipt(), paths)
    assert_arm_available(paths, trade_state_present=True)


@pytest.mark.parametrize("lost_index", [0, 1])
def test_losing_either_receipt_still_catches_lost_trade_state(
    tmp_path: Path, lost_index: int
) -> None:
    paths = (tmp_path / "a.json", tmp_path / "b.json")
    write_arm_receipt(sample_receipt(), paths)
    paths[lost_index].unlink()
    with pytest.raises(ArmReceiptError, match="CONSUMED"):
        assert_arm_available(paths, trade_state_present=False)


def test_lost_trade_state_with_consumed_arm_fails_closed(tmp_path: Path) -> None:
    coordinator, _store, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    drive_to_protected(coordinator, broker)

    (storage / "phase2_trade_state.json").unlink()
    restarted = restart(storage, project)
    with pytest.raises(ArmReceiptError, match="CONSUMED"):
        restarted.load()


def test_clean_first_run_is_permitted(tmp_path: Path) -> None:
    coordinator, _, _, _ = make_coordinator(tmp_path)
    assert coordinator.load() is None


# ---------------------------------------------------------------------------
# Protective stop fill, duplicates, restart
# ---------------------------------------------------------------------------


def test_protective_stop_fill_closes_the_long_without_an_exit_order(tmp_path: Path) -> None:
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)
    assert broker.position == 1

    broker.fill(identity.protective_order_id, 1)
    record = coordinator.on_fill(
        record, client_order_id=identity.protective_order_id, fill_id="8-1", fill_quantity=1
    )

    assert broker.position == 0
    assert record.open_long_quantity == 0
    assert record.protective_fill_quantity == 1
    assert store.require(identity.trade_intent_id).state is TradeState.CLOSED

    with pytest.raises(ReconciliationError):
        coordinator.begin_exit(record, broker.view())
    assert broker.count(OrderRole.EXIT) == 0

    record = coordinator.finalize(record, broker.view())
    assert record.state is TradeState.RECONCILED
    assert broker.position == 0


def test_duplicate_order_event_is_a_true_noop(tmp_path: Path) -> None:
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = coordinator.authorize(arm_request(), evidence())
    pending = coordinator.begin_entry(record)
    record = dispatch(coordinator, broker, pending)
    broker.fill(identity.entry_order_id, 1)

    for _ in range(5):
        record, _ = coordinator.apply_entry_fill_and_prepare_protection(
            record,
            client_order_id=identity.entry_order_id,
            fill_id="7-1",
            fill_quantity=1,
            fill_price=SPY_PRICE,
        )
    assert record.filled_quantity == 1
    assert sum(1 for o in record.orders.values() if o.role is OrderRole.PROTECTIVE) == 1
    assert store.require(identity.trade_intent_id).filled_quantity == 1


def test_restart_after_protection_submits_no_further_entry(tmp_path: Path) -> None:
    coordinator, _, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    drive_to_protected(coordinator, broker)
    entries_before = broker.count(OrderRole.ENTRY)

    restarted = restart(storage, project)
    recovered = restarted.load()
    assert recovered is not None
    assert recovered.state is TradeState.PROTECTED
    restarted.reconcile(recovered, broker.view())

    with pytest.raises(ReconciliationError):
        restarted.begin_entry(recovered)
    assert broker.count(OrderRole.ENTRY) - entries_before == 0


# ---------------------------------------------------------------------------
# Round 4 -- the send fence. Crash on EITHER side of the broker call must
# never produce a second order.
# ---------------------------------------------------------------------------


def restart(
    storage: Path,
    project: Path,
    *,
    account_id: str = PAPER_ACCOUNT_ID,
    trading_mode: str = "paper",
) -> Phase2Coordinator:
    """A brand-new coordinator over the same durable state: a restarted process.

    ``account_id`` is the session the restarted process finds itself connected
    to, which is not necessarily the one the trade was armed against.
    """
    return Phase2Coordinator(
        JsonTradeStateStore(storage / "phase2_trade_state.json"),
        TradeIdentity.derive(PHASE2_INTENT_NATURAL_KEY, attempt=1),
        storage_root=storage,
        project_root=project,
        session_provider=lambda: evidence(account_id, trading_mode),
    )


def test_entry_fenced_broker_received_then_crash_sends_no_second_entry(
    tmp_path: Path,
) -> None:
    """Fence -> broker HAS the order -> crash. Recovery must adopt, never resend."""
    coordinator, _, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    record = coordinator.authorize(arm_request(), evidence())
    pending = coordinator.begin_entry(record)
    coordinator.fence_dispatch(pending.record, identity.entry_order_id)
    broker.submit(pending)  # IBKR has it
    # ...and the process dies here, with nothing written after the call.

    resumed = restart(storage, project)
    recovered = resumed.load()
    assert recovered is not None
    assert recovered.orders[identity.entry_order_id].dispatch is DispatchState.SEND_FENCED

    plan = resumed.assess_recovery(recovered, broker.view())
    assert plan.redispatch == (), "positive broker evidence: adopt, never resend"
    assert plan.record.orders[identity.entry_order_id].dispatch is DispatchState.ACKNOWLEDGED
    assert broker.count(OrderRole.ENTRY) == 1


def test_protective_fenced_broker_received_then_crash_sends_no_second_stop(
    tmp_path: Path,
) -> None:
    """The dangerous one: a second stop on a 1-share long can end up short."""
    coordinator, _, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    record = coordinator.authorize(arm_request(), evidence())
    pending = coordinator.begin_entry(record)
    record = dispatch(coordinator, broker, pending)
    record, protection = fill_entry_atomically(coordinator, broker, record)
    assert protection is not None
    coordinator.fence_dispatch(protection.record, identity.protective_order_id)
    broker.submit(protection)  # IBKR has the stop
    # ...crash.

    resumed = restart(storage, project)
    recovered = resumed.load()
    assert recovered is not None
    plan = resumed.assess_recovery(recovered, broker.view())

    assert plan.redispatch == (), "must NOT send a second protective stop"
    assert broker.count(OrderRole.PROTECTIVE) == 1
    assert broker.position == 1, "still exactly one long share; no short"


def test_exit_fenced_broker_received_then_crash_sends_no_second_sell(
    tmp_path: Path,
) -> None:
    """A second SELL against a 1-share long would open a short."""
    coordinator, _, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)
    record = coordinator.request_exit(record)
    record, _ = coordinator.begin_protection_cancel(record)
    broker.confirm_cancel(identity.protective_order_id)
    record = coordinator.on_order_cancelled(record, identity.protective_order_id)

    exit_order = coordinator.begin_exit(record, broker.view())
    coordinator.fence_dispatch(exit_order.record, identity.exit_order_id)
    broker.submit(exit_order)  # IBKR has the SELL
    # ...crash.

    resumed = restart(storage, project)
    recovered = resumed.load()
    assert recovered is not None
    plan = resumed.assess_recovery(recovered, broker.view())

    assert plan.redispatch == (), "must NOT send a second SELL"
    assert broker.count(OrderRole.EXIT) == 1
    assert broker.position == 1, "no short"


@pytest.mark.parametrize("role", ["ENTRY", "PROTECTIVE", "EXIT"])
def test_fenced_then_crash_before_broker_call_also_halts(tmp_path: Path, role: str) -> None:
    """Fence held, broker never called. Indistinguishable from the above, so it halts.

    This conservative stop is intentional: durable state cannot tell the two
    apart, and guessing wrong in the other direction sends a duplicate.
    """
    coordinator, _, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    record = coordinator.authorize(arm_request(), evidence())
    if role == "ENTRY":
        pending = coordinator.begin_entry(record)
    else:
        record = dispatch(coordinator, broker, coordinator.begin_entry(record))
        record, protection = fill_entry_atomically(coordinator, broker, record)
        assert protection is not None
        if role == "PROTECTIVE":
            pending = protection
        else:
            record = dispatch(coordinator, broker, protection)
            record = coordinator.reconcile(record, broker.view())
            record = coordinator.confirm_protection(record, broker.view())
            record = coordinator.request_exit(record)
            record, _ = coordinator.begin_protection_cancel(record)
            broker.confirm_cancel(identity.protective_order_id)
            record = coordinator.on_order_cancelled(record, identity.protective_order_id)
            pending = coordinator.begin_exit(record, broker.view())

    submissions_before = len(broker.submissions)
    fence_only(coordinator, pending)  # fence durable, broker NEVER called
    # ...crash.

    resumed = restart(storage, project)
    recovered = resumed.load()
    assert recovered is not None
    with pytest.raises(ReconciliationError, match="Send fence held"):
        resumed.assess_recovery(recovered, broker.view())
    assert len(broker.submissions) == submissions_before, "nothing auto-resent"


# ---------------------------------------------------------------------------
# Round 5 -- the entry fill and its protective intent are ONE durable write
# ---------------------------------------------------------------------------


def fill_entry_atomically(
    coordinator: Phase2Coordinator, broker: Broker, record: TradeRecord
) -> tuple[TradeRecord, PendingOrder | None]:
    """Entry fill processed exactly as production does it."""
    identity = coordinator.identity
    broker.fill(identity.entry_order_id, 1)
    return coordinator.apply_entry_fill_and_prepare_protection(
        record,
        client_order_id=identity.entry_order_id,
        fill_id="7-1",
        fill_quantity=1,
        fill_price=SPY_PRICE,
    )


def entered(coordinator: Phase2Coordinator, broker: Broker) -> TradeRecord:
    record = coordinator.authorize(arm_request(), evidence())
    return dispatch(coordinator, broker, coordinator.begin_entry(record))


def test_entry_fill_and_protective_intent_are_one_durable_write(tmp_path: Path) -> None:
    """After an entry fill there is no durable state with a long and no protection."""
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    record = entered(coordinator, broker)
    record, protection = fill_entry_atomically(coordinator, broker, record)
    assert protection is not None

    persisted = store.require(identity.trade_intent_id)
    assert persisted.open_long_quantity == 1
    assert persisted.state is TradeState.PROTECTION_SUBMITTED
    protective = persisted.orders[identity.protective_order_id]
    assert protective.dispatch is DispatchState.INTENT_RECORDED
    assert protective.stop_price is not None
    assert Decimal(protective.stop_price) == (SPY_PRICE * Decimal("0.90")).quantize(Decimal("0.01"))
    assert persisted.protected_quantity == 0, "an unfenced intent is not protection"


def test_crash_after_atomic_write_before_protective_fence_recovers(tmp_path: Path) -> None:
    """The exact window: fill+intent durable, crash before the protective fence."""
    coordinator, store, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    record = entered(coordinator, broker)
    fill_entry_atomically(coordinator, broker, record)
    # ...crash, before the protective order is fenced or sent.

    resumed = restart(storage, project)
    recovered = resumed.load()
    assert recovered is not None
    assert recovered.open_long_quantity == 1
    assert recovered.orders[identity.protective_order_id].dispatch is DispatchState.INTENT_RECORDED
    assert recovered.protected_quantity == 0
    assert recovered.orders[identity.protective_order_id].stop_price is not None

    plan = resumed.assess_recovery(recovered, broker.view())
    assert len(plan.redispatch) == 1
    pending = plan.redispatch[0]
    assert pending.request.role is OrderRole.PROTECTIVE
    # Reconstructed from durable state, NOT from a fresh market price.
    assert pending.request.stop_price == (SPY_PRICE * Decimal("0.90")).quantize(Decimal("0.01"))

    after = dispatch(resumed, broker, pending)
    after = resumed.reconcile(after, broker.view())
    assert after.protected_quantity == 1
    assert broker.count(OrderRole.ENTRY) == 1, "no second entry"
    assert broker.count(OrderRole.PROTECTIVE) == 1
    assert broker.position == 1, "no short"
    assert store.require(identity.trade_intent_id).protected_quantity == 1


def test_crash_before_atomic_write_does_not_fabricate_the_fill(tmp_path: Path) -> None:
    """Entry fenced and sent, crash before the fill is processed. Fail closed."""
    coordinator, _, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    entered(coordinator, broker)
    broker.fill(identity.entry_order_id, 1)  # broker filled; we never processed it
    # ...crash before any durable fill write.

    resumed = restart(storage, project)
    recovered = resumed.load()
    assert recovered is not None
    assert recovered.open_long_quantity == 0, "no fill was fabricated"
    assert recovered.order_for_role(OrderRole.PROTECTIVE) is None

    # The entry is fenced and the broker shows no open order (it filled), so the
    # outcome is not conclusively resolvable from state alone: halt.
    with pytest.raises(ReconciliationError, match="Send fence held"):
        resumed.assess_recovery(recovered, broker.view())
    assert broker.count(OrderRole.ENTRY) == 1, "entry never resent"


def test_duplicate_entry_fill_event_creates_one_protective_intent(tmp_path: Path) -> None:
    coordinator, _, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = entered(coordinator, broker)

    record, first = fill_entry_atomically(coordinator, broker, record)
    assert first is not None
    for _ in range(4):
        record, repeat = coordinator.apply_entry_fill_and_prepare_protection(
            record,
            client_order_id=identity.entry_order_id,
            fill_id="7-1",
            fill_quantity=1,
            fill_price=SPY_PRICE,
        )
        assert repeat is None, "duplicate event must not produce a second protective order"
    assert record.filled_quantity == 1


# ---------------------------------------------------------------------------
# Round 5 -- dispatch state is monotonic; stale records cannot regress it
# ---------------------------------------------------------------------------


def test_stale_record_cannot_regress_acknowledged_back_to_fenced(tmp_path: Path) -> None:
    """A record captured before reconciliation must not undo broker evidence."""
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    record = coordinator.authorize(arm_request(), evidence())
    pending = coordinator.begin_entry(record)
    stale = dispatch(coordinator, broker, pending)  # SEND_FENCED
    fresh = coordinator.reconcile(stale, broker.view())
    assert fresh.orders[identity.entry_order_id].dispatch is DispatchState.ACKNOWLEDGED

    # Replaying the older step with the stale object must be REFUSED loudly.
    # A field-level guard is not enough: writing the whole stale record would
    # roll back every field, including the broker evidence just adopted.
    with pytest.raises(StaleWriteError):
        coordinator.fence_dispatch(stale, identity.entry_order_id)
    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.entry_order_id].dispatch is DispatchState.ACKNOWLEDGED


def test_reconcile_returns_the_adopted_record(tmp_path: Path) -> None:
    """main.py must use the returned record; this proves there is one to use."""
    coordinator, _, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = coordinator.authorize(arm_request(), evidence())
    record = dispatch(coordinator, broker, coordinator.begin_entry(record))

    returned = coordinator.reconcile(record, broker.view())
    assert returned is not record
    assert returned.orders[identity.entry_order_id].dispatch is DispatchState.ACKNOWLEDGED


# ---------------------------------------------------------------------------
# Round 5 -- ENTRY INVALID latches the lifecycle to FAILED
# ---------------------------------------------------------------------------


def test_entry_invalid_latches_lifecycle_failed(tmp_path: Path) -> None:
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = entered(coordinator, broker)

    record = coordinator.on_order_rejected(record, identity.entry_order_id)
    assert record.state is TradeState.FAILED
    assert record.failure_reason is not None and "REJECTED" in record.failure_reason
    assert store.require(identity.trade_intent_id).state is TradeState.FAILED

    # Terminal means terminal: nothing may proceed from here.
    with pytest.raises(ReconciliationError):
        coordinator.begin_entry(record)


def test_naked_long_without_protective_intent_fails_closed(tmp_path: Path) -> None:
    """Unreachable by design, but if durable state ever shows it, halt."""
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = entered(coordinator, broker)
    record, _ = fill_entry_atomically(coordinator, broker, record)

    # Forcibly strip the protective intent, simulating corrupted/legacy state.
    stripped = replace(
        record, orders={identity.entry_order_id: record.orders[identity.entry_order_id]}
    )
    stripped = store.put(stripped)
    assert stripped.open_long_quantity == 1
    with pytest.raises(ReconciliationError, match="NAKED LONG"):
        coordinator.assess_recovery(stripped, broker.view())


# ---------------------------------------------------------------------------
# Round 5 -- account binding is REQUIRED, never disabled by absence
# ---------------------------------------------------------------------------


def test_missing_fingerprint_cannot_disable_the_binding_check() -> None:
    """Passing None would silently drop the check. The runtime must never do that."""
    deployed = evidence(PAPER_ACCOUNT_ID)
    # A correct binding passes.
    verify_paper_session(deployed, expected_fingerprint=account_fingerprint(PAPER_ACCOUNT_ID))
    # A wrong one is refused.
    with pytest.raises(SessionVerificationError, match="does not match"):
        verify_paper_session(deployed, expected_fingerprint=account_fingerprint("DU9999999"))


def test_arm_status_requires_fingerprint_to_report_armed(tmp_path: Path) -> None:
    """Flags and phrase alone are NOT armed: an unbound arm cannot be verified."""
    import json as _json

    from kalpamani.execution.envelope import PHASE2_CONFIRMATION_PHRASE as PHRASE

    def armed(params: dict[str, str]) -> bool:
        binding = str(params.get("phase2_account_fingerprint", "") or "")
        return (
            str(params.get("phase2_test_mode", "")).lower() == "true"
            and str(params.get("explicit_execution_arm", "")).lower() == "true"
            and params.get("phase2_confirmation") == PHRASE
            and bool(binding)
        )

    base = {
        "phase2_test_mode": "true",
        "explicit_execution_arm": "true",
        "phase2_confirmation": PHRASE,
    }
    assert armed(base) is False, "flags + phrase without a binding is NOT armed"
    assert armed({**base, "phase2_account_fingerprint": ""}) is False
    bound = {**base, "phase2_account_fingerprint": account_fingerprint(PAPER_ACCOUNT_ID)}
    assert armed(bound) is True

    # And the shape the arm script writes must not contain a raw account id.
    written = _json.dumps(bound)
    assert PAPER_ACCOUNT_ID not in written
    assert "ibkr_account_id" not in written


# ---------------------------------------------------------------------------
# Round 6 -- expected vs UNEXPECTED protective cancellation
# ---------------------------------------------------------------------------


def test_expected_protective_cancellation_continues_the_exit(tmp_path: Path) -> None:
    """cancel_requested=True + CANCELED = the controlled exit. Carry on."""
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)
    record = coordinator.request_exit(record)
    record, _ = coordinator.begin_protection_cancel(record)
    broker.confirm_cancel(identity.protective_order_id)

    record = coordinator.on_order_cancelled(record, identity.protective_order_id)

    assert record.state is TradeState.EXIT_REQUESTED, "still progressing, not failed"
    assert record.protected_quantity == 0
    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.protective_order_id].dispatch is DispatchState.CANCELLED
    assert coordinator.begin_exit(persisted, broker.view()).request.quantity == 1


def test_unexpected_protective_cancellation_fails_closed(tmp_path: Path) -> None:
    """Protection vanished without us asking. The long is bare: FAILED + abort."""
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)
    assert record.orders[identity.protective_order_id].cancel_requested is False

    broker.confirm_cancel(identity.protective_order_id)  # cancelled by someone else
    with pytest.raises(UnprotectedPositionError, match="without KalpaMani requesting"):
        coordinator.on_order_cancelled(record, identity.protective_order_id)

    persisted = store.require(identity.trade_intent_id)
    assert persisted.state is TradeState.FAILED, "durable FAILED, not merely raised"
    assert persisted.protected_quantity == 0
    assert persisted.open_long_quantity == 1
    assert persisted.failure_reason is not None


def test_unexpected_protective_cancellation_survives_restart(tmp_path: Path) -> None:
    coordinator, _, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)
    broker.confirm_cancel(identity.protective_order_id)
    with pytest.raises(UnprotectedPositionError):
        coordinator.on_order_cancelled(record, identity.protective_order_id)

    resumed = restart(storage, project)
    recovered = resumed.load()
    assert recovered is not None
    assert recovered.state is TradeState.FAILED, "restart must not resume normal progression"
    with pytest.raises(LifecycleError):
        resumed.request_exit(recovered)


# ---------------------------------------------------------------------------
# Round 6 -- ENTRY and EXIT cancellations are handled explicitly
# ---------------------------------------------------------------------------


def test_entry_cancelled_with_no_fill_is_terminal(tmp_path: Path) -> None:
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = entered(coordinator, broker)

    record = coordinator.on_order_cancelled(record, identity.entry_order_id)

    assert record.state is TradeState.FAILED
    assert store.require(identity.trade_intent_id).state is TradeState.FAILED
    with pytest.raises(ReconciliationError):
        coordinator.begin_entry(record)
    assert broker.count(OrderRole.ENTRY) == 1, "never retried"


def test_exit_cancelled_while_long_is_unprotected_position(tmp_path: Path) -> None:
    """Protection was already removed to permit the close, so the long is bare."""
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)
    record = coordinator.request_exit(record)
    record, _ = coordinator.begin_protection_cancel(record)
    broker.confirm_cancel(identity.protective_order_id)
    record = coordinator.on_order_cancelled(record, identity.protective_order_id)
    exit_order = coordinator.begin_exit(record, broker.view())
    record = dispatch(coordinator, broker, exit_order)

    broker.confirm_cancel(identity.exit_order_id)
    with pytest.raises(UnprotectedPositionError, match="EXIT"):
        coordinator.on_order_cancelled(record, identity.exit_order_id)

    persisted = store.require(identity.trade_intent_id)
    assert persisted.state is TradeState.FAILED
    assert persisted.open_long_quantity == 1
    assert broker.count(OrderRole.EXIT) == 1, "no automatic second EXIT"


# ---------------------------------------------------------------------------
# Round 6 -- PROTECTIVE / EXIT INVALID persist FAILED before raising
# ---------------------------------------------------------------------------


def test_protective_invalid_persists_failed_before_raising(tmp_path: Path) -> None:
    coordinator, store, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = entered(coordinator, broker)
    record, protection = fill_entry_atomically(coordinator, broker, record)
    assert protection is not None
    record = dispatch(coordinator, broker, protection)

    with pytest.raises(UnprotectedPositionError, match="REJECTED"):
        coordinator.on_order_rejected(record, identity.protective_order_id)

    persisted = store.require(identity.trade_intent_id)
    assert persisted.state is TradeState.FAILED
    assert persisted.open_long_quantity == 1

    resumed = restart(storage, project)
    recovered = resumed.load()
    assert recovered is not None
    assert recovered.state is TradeState.FAILED, "terminal across restart"


def test_exit_invalid_persists_failed_before_raising(tmp_path: Path) -> None:
    coordinator, store, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)
    record = coordinator.request_exit(record)
    record, _ = coordinator.begin_protection_cancel(record)
    broker.confirm_cancel(identity.protective_order_id)
    record = coordinator.on_order_cancelled(record, identity.protective_order_id)
    exit_order = coordinator.begin_exit(record, broker.view())
    record = dispatch(coordinator, broker, exit_order)

    with pytest.raises(UnprotectedPositionError, match="REJECTED"):
        coordinator.on_order_rejected(record, identity.exit_order_id)

    persisted = store.require(identity.trade_intent_id)
    assert persisted.state is TradeState.FAILED

    resumed = restart(storage, project)
    recovered = resumed.load()
    assert recovered is not None
    assert recovered.state is TradeState.FAILED


# ---------------------------------------------------------------------------
# Round 6 -- ANY working order on the symbol blocks arming
# ---------------------------------------------------------------------------


def foreign_order(symbol: str, side: str, quantity: int = 100) -> BrokerOrderView:
    """An order KalpaMani did not create -- identity deliberately opaque."""
    return BrokerOrderView(
        client_order_id="<foreign-0>",
        symbol=symbol,
        side=side,
        quantity=quantity,
        is_open=True,
    )


def test_clean_account_is_eligible_to_arm(tmp_path: Path) -> None:
    coordinator, _, _, _ = make_coordinator(tmp_path)
    view = BrokerView(positions=(BrokerPositionView(PHASE2_SYMBOL, 0),), open_orders=())
    coordinator.assert_eligible_to_arm(view)  # must not raise


def test_foreign_order_on_another_symbol_does_not_block(tmp_path: Path) -> None:
    """We only refuse ambiguity on OUR symbol; an AAPL order is irrelevant."""
    coordinator, _, _, _ = make_coordinator(tmp_path)
    view = BrokerView(
        positions=(BrokerPositionView(PHASE2_SYMBOL, 0),),
        open_orders=(foreign_order("AAPL", "SELL"),),
    )
    coordinator.assert_eligible_to_arm(view)  # must not raise


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_foreign_spy_order_blocks_arming(tmp_path: Path, side: str) -> None:
    """A manual SPY order makes ownership ambiguous. Refuse; never cancel it."""
    coordinator, _, _, _ = make_coordinator(tmp_path)
    view = BrokerView(
        positions=(BrokerPositionView(PHASE2_SYMBOL, 0),),
        open_orders=(foreign_order(PHASE2_SYMBOL, side),),
    )
    with pytest.raises(ReconciliationError, match="ownership would be ambiguous"):
        coordinator.assert_eligible_to_arm(view)


def test_existing_kalpamani_spy_order_blocks_arming(tmp_path: Path) -> None:
    coordinator, _, _, _ = make_coordinator(tmp_path)
    identity = coordinator.identity
    view = BrokerView(
        positions=(BrokerPositionView(PHASE2_SYMBOL, 0),),
        open_orders=(
            BrokerOrderView(
                identity.entry_order_id,
                PHASE2_SYMBOL,
                "BUY",
                1,
                is_open=True,
                ownership=OwnershipBasis.TAG,
            ),
        ),
    )
    with pytest.raises(ReconciliationError):
        coordinator.assert_eligible_to_arm(view)


def test_existing_spy_position_blocks_arming(tmp_path: Path) -> None:
    coordinator, _, _, _ = make_coordinator(tmp_path)
    view = BrokerView(positions=(BrokerPositionView(PHASE2_SYMBOL, 5),))
    with pytest.raises(ReconciliationError, match="Existing SPY position"):
        coordinator.assert_eligible_to_arm(view)


def test_foreign_order_details_are_not_exposed(tmp_path: Path) -> None:
    """The refusal reports counts, not somebody else's order details."""
    coordinator, _, _, _ = make_coordinator(tmp_path)
    view = BrokerView(
        positions=(BrokerPositionView(PHASE2_SYMBOL, 0),),
        open_orders=(foreign_order(PHASE2_SYMBOL, "SELL", quantity=12345),),
    )
    with pytest.raises(ReconciliationError) as excinfo:
        coordinator.assert_eligible_to_arm(view)
    message = str(excinfo.value)
    assert "12345" not in message, "foreign order size must not be logged"
    assert "1 non-KalpaMani" in message


# ---------------------------------------------------------------------------
# Round 7 -- the trade is bound to an ACCOUNT, and the binding is re-proven
# on every cycle and again at the dispatch boundary
# ---------------------------------------------------------------------------


def unfenced_protective(tmp_path: Path) -> tuple[Phase2Coordinator, Broker, Path, Path]:
    """A durable state with an open long and a protective intent never sent."""
    coordinator, _, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    record = entered(coordinator, broker)
    _record, protection = fill_entry_atomically(coordinator, broker, record)
    assert protection is not None
    return coordinator, broker, storage, project


def long_only_view(long: int, identity: TradeIdentity) -> BrokerView:
    """Broker truth with a position and no working orders."""
    return BrokerView(positions=(BrokerPositionView(PHASE2_SYMBOL, long),), open_orders=())


def test_authorized_record_carries_the_account_fingerprint(tmp_path: Path) -> None:
    coordinator, store, _, _ = make_coordinator(tmp_path)
    record = coordinator.authorize(arm_request(), evidence())

    assert record.account_fingerprint == account_fingerprint(PAPER_ACCOUNT_ID)
    persisted = store.require(coordinator.identity.trade_intent_id)
    assert persisted.account_fingerprint == account_fingerprint(PAPER_ACCOUNT_ID)
    assert PAPER_ACCOUNT_ID not in persisted.describe(), "the raw id is never persisted or logged"


def test_unbound_record_fails_closed_at_the_binding_check(tmp_path: Path) -> None:
    """A record with no account binding must never reach a broker."""
    coordinator, _, _, _ = make_coordinator(tmp_path)
    record = coordinator.authorize(arm_request(), evidence())
    unbound = replace(record, account_fingerprint=None)

    with pytest.raises(SessionVerificationError, match="no account binding"):
        coordinator.assert_session_binding(unbound)


@pytest.mark.parametrize(
    ("account_id", "trading_mode", "expected"),
    [
        (LIVE_ACCOUNT_ID, "live", "requires 'paper'"),
        ("XX999", "", "Phase 2 requires"),
        (OTHER_PAPER_ACCOUNT_ID, "paper", "does not match the deployed"),
    ],
    ids=["live", "unknown", "different-paper"],
)
def test_session_binding_rejects_live_unknown_and_other_paper_accounts(
    tmp_path: Path, account_id: str, trading_mode: str, expected: str
) -> None:
    coordinator, _, storage, project = make_coordinator(tmp_path)
    record = coordinator.authorize(arm_request(), evidence())

    resumed = restart(storage, project, account_id=account_id, trading_mode=trading_mode)
    with pytest.raises(SessionVerificationError, match=expected):
        resumed.assert_session_binding(record)


def test_dispatch_boundary_refuses_a_wrong_session(tmp_path: Path) -> None:
    """Defence in depth: the fence itself re-proves the account, so no order can
    leave on the strength of a check made several methods earlier."""
    coordinator, _, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    record = coordinator.authorize(arm_request(), evidence())
    pending = coordinator.begin_entry(record)

    wrong = restart(storage, project, account_id=OTHER_PAPER_ACCOUNT_ID)
    with pytest.raises(SessionVerificationError):
        wrong.fence_dispatch(pending.record, pending.request.client_order_id)

    persisted = JsonTradeStateStore(storage / "phase2_trade_state.json").require(
        coordinator.identity.trade_intent_id
    )
    entry = persisted.orders[coordinator.identity.entry_order_id]
    assert entry.dispatch is DispatchState.INTENT_RECORDED, "no fence, therefore no broker call"
    assert broker.submissions == []


# ---------------------------------------------------------------------------
# Round 7 -- recovery verifies the account and reconciles BEFORE it re-dispatches
# ---------------------------------------------------------------------------


def test_recovery_against_a_live_account_submits_nothing(tmp_path: Path) -> None:
    """A. Armed on PAPER account A; restart evidence says LIVE."""
    _coordinator, broker, storage, project = unfenced_protective(tmp_path)
    submissions_before = len(broker.submissions)

    resumed = restart(storage, project, account_id=LIVE_ACCOUNT_ID, trading_mode="live")
    recovered = resumed.load()
    assert recovered is not None
    with pytest.raises(SessionVerificationError):
        resumed.assess_recovery(recovered, broker.view())

    assert len(broker.submissions) == submissions_before, "zero broker submissions"


def test_recovery_against_a_different_paper_account_submits_nothing(tmp_path: Path) -> None:
    """B. Armed on PAPER account A; restart lands on PAPER account B."""
    _coordinator, broker, storage, project = unfenced_protective(tmp_path)
    submissions_before = len(broker.submissions)

    resumed = restart(storage, project, account_id=OTHER_PAPER_ACCOUNT_ID)
    recovered = resumed.load()
    assert recovered is not None
    with pytest.raises(SessionVerificationError, match="does not match the deployed"):
        resumed.assess_recovery(recovered, broker.view())

    assert len(broker.submissions) == submissions_before, "zero broker submissions"


def test_unfenced_protective_is_not_redispatched_when_broker_shows_no_position(
    tmp_path: Path,
) -> None:
    """C. Local long=1, broker long=0. A stop for a position the broker does not
    show could sell what we do not hold."""
    _coordinator, broker, storage, project = unfenced_protective(tmp_path)
    submissions_before = len(broker.submissions)

    resumed = restart(storage, project)
    recovered = resumed.load()
    assert recovered is not None
    with pytest.raises(ReconciliationError):
        resumed.assess_recovery(recovered, long_only_view(0, resumed.identity))

    assert len(broker.submissions) == submissions_before


def test_unfenced_exit_is_not_redispatched_when_broker_shows_no_position(
    tmp_path: Path,
) -> None:
    """D. Same rule for the closing SELL."""
    coordinator, _, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)
    record = coordinator.request_exit(record)
    record, _ = coordinator.begin_protection_cancel(record)
    broker.confirm_cancel(identity.protective_order_id)
    record = coordinator.on_order_cancelled(record, identity.protective_order_id)
    coordinator.begin_exit(record, broker.view())  # intent recorded, never fenced
    submissions_before = len(broker.submissions)

    resumed = restart(storage, project)
    recovered = resumed.load()
    assert recovered is not None
    with pytest.raises(ReconciliationError):
        resumed.assess_recovery(recovered, long_only_view(0, resumed.identity))

    assert len(broker.submissions) == submissions_before


def test_recovery_redispatches_exactly_once_when_everything_agrees(tmp_path: Path) -> None:
    """E. Same PAPER account, matching broker state: one permitted dispatch."""
    coordinator, broker, storage, project = unfenced_protective(tmp_path)
    identity = coordinator.identity
    submissions_before = len(broker.submissions)

    resumed = restart(storage, project)
    recovered = resumed.load()
    assert recovered is not None
    plan = resumed.assess_recovery(recovered, broker.view())

    assert len(plan.redispatch) == 1
    assert plan.redispatch[0].request.client_order_id == identity.protective_order_id
    for pending in plan.redispatch:
        dispatch(resumed, broker, pending)
    assert len(broker.submissions) == submissions_before + 1

    # And a SECOND recovery pass must not send it again: it is fenced now.
    again = restart(storage, project)
    once_more = again.load()
    assert once_more is not None
    with pytest.raises(ReconciliationError, match="Send fence held"):
        again.assess_recovery(
            once_more, BrokerView(positions=(BrokerPositionView(PHASE2_SYMBOL, 1),), open_orders=())
        )
    assert len(broker.submissions) == submissions_before + 1


# ---------------------------------------------------------------------------
# Round 7 -- a halt blocks NEW normal activity; it does not erase broker truth
# ---------------------------------------------------------------------------


def test_entry_filling_after_a_halt_is_recorded_and_protected(tmp_path: Path) -> None:
    """The production sequence main.py runs when an already-dispatched ENTRY
    fills after normal progression has been halted.

    Dropping the event would leave the fill unrecorded, no protective intent,
    and a naked long at the broker this process cannot see.
    """
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    record = entered(coordinator, broker)  # ENTRY fenced and sent
    normal_progression_halted = True  # an unrelated error halts the algorithm

    # The event still arrives, and is still ingested.
    record, protection = fill_entry_atomically(coordinator, broker, record)
    assert protection is not None

    # Risk-reducing, and only when broker truth is unambiguous (main.py's
    # _dispatch_protection).
    coordinator.reconcile(record, broker.view())
    dispatch(coordinator, broker, protection)

    persisted = store.require(identity.trade_intent_id)
    assert persisted.open_long_quantity == 1, "the fill is durable"
    assert sum(1 for o in persisted.orders.values() if o.role is OrderRole.PROTECTIVE) == 1
    assert broker.count(OrderRole.PROTECTIVE) == 1, "exactly one protection order"
    assert broker.count(OrderRole.ENTRY) == 1, "no second entry"
    assert normal_progression_halted, "normal progression stays halted"


def test_protection_is_refused_after_a_halt_when_broker_state_is_ambiguous(
    tmp_path: Path,
) -> None:
    """If the position cannot be confirmed, surface UNPROTECTED rather than
    sending a stop against something we cannot see."""
    coordinator, _, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    record = entered(coordinator, broker)
    record, protection = fill_entry_atomically(coordinator, broker, record)
    assert protection is not None

    with pytest.raises(ReconciliationError):
        coordinator.reconcile(record, long_only_view(0, coordinator.identity))
    assert broker.count(OrderRole.PROTECTIVE) == 0
