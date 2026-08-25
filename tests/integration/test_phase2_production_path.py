"""Production-path orchestration tests: drive the real coordinator, not a re-creation.

The first Phase 2 review found that the earlier integration test performed state
transitions `main.py` never did. The tests passed while production silently
omitted steps. These tests exist so that cannot recur: they call the *same*
:class:`Phase2Coordinator` methods `main.py` calls, and every durable write is
the production one.

Each test below corresponds to a defect that review identified.
"""

from __future__ import annotations

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
from kalpamani.execution.lifecycle import TradeState
from kalpamani.execution.reconciliation import (
    BrokerOrderView,
    BrokerPositionView,
    BrokerView,
    ReconciliationError,
)
from kalpamani.execution.session import ArmReceiptError, BrokerSessionEvidence
from kalpamani.execution.state_store import (
    JsonTradeStateStore,
    StateStoreError,
    TradeRecord,
)

pytestmark = pytest.mark.integration

SPY_PRICE = Decimal("766.38")
PAPER_ACCOUNT_ID = "DU1234567"


def evidence(account_id: str = PAPER_ACCOUNT_ID) -> BrokerSessionEvidence:
    return BrokerSessionEvidence(
        account_id=account_id, trading_mode="paper", source="test-deployment-config"
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
    """In-memory broker double. Counts every submission by role."""

    def __init__(self) -> None:
        self.position = 0
        self.working: dict[str, BrokerOrderView] = {}
        self.submissions: list[tuple[OrderRole, str]] = []

    def submit(self, pending: PendingOrder) -> None:
        request = pending.request
        self.submissions.append((request.role, request.client_order_id))
        self.working[request.client_order_id] = BrokerOrderView(
            client_order_id=request.client_order_id,
            symbol=request.symbol,
            side=request.side.value,
            quantity=request.quantity,
            is_open=True,
        )

    def fill(self, client_order_id: str, quantity: int) -> None:
        order = self.working.pop(client_order_id)
        self.position += quantity if order.side == "BUY" else -quantity

    def cancel(self, client_order_id: str) -> None:
        self.working.pop(client_order_id, None)

    def count(self, role: OrderRole) -> int:
        return sum(1 for r, _ in self.submissions if r is role)

    def view(self) -> BrokerView:
        return BrokerView(
            positions=(BrokerPositionView(PHASE2_SYMBOL, self.position),),
            open_orders=tuple(self.working.values()),
        )


def make_coordinator(tmp_path: Path) -> tuple[Phase2Coordinator, JsonTradeStateStore, Path, Path]:
    storage = tmp_path / "storage"
    project = tmp_path / "project"
    storage.mkdir()
    project.mkdir()
    store = JsonTradeStateStore(storage / "phase2_trade_state.json")
    identity = TradeIdentity.derive(PHASE2_INTENT_NATURAL_KEY, attempt=1)
    coordinator = Phase2Coordinator(store, identity, storage_root=storage, project_root=project)
    return coordinator, store, storage, project


def drive_to_protected(coordinator: Phase2Coordinator, broker: Broker) -> TradeRecord:
    """Run the real production path up to a confirmed PROTECTED position."""
    record = coordinator.authorize(arm_request(), evidence())

    pending = coordinator.begin_entry(record)
    broker.submit(pending)
    broker.fill(pending.request.client_order_id, PHASE2_QUANTITY)
    record = coordinator.on_fill(
        pending.record,
        client_order_id=pending.request.client_order_id,
        fill_id="7-1",
        fill_quantity=PHASE2_QUANTITY,
    )

    protection = coordinator.plan_protection(record, SPY_PRICE)
    assert protection is not None
    broker.submit(protection)
    record = coordinator.confirm_protection(protection.record, broker.view())
    return record


# ---------------------------------------------------------------------------
# Review item 4 -- production lifecycle transitions are actually PERSISTED
# ---------------------------------------------------------------------------


def test_production_path_persists_every_lifecycle_transition(tmp_path: Path) -> None:
    """The durable record must reflect each state, not merely log it."""
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity

    record = coordinator.authorize(arm_request(), evidence())
    assert store.require(identity.trade_intent_id).state is TradeState.AUTHORIZED

    pending = coordinator.begin_entry(record)
    assert store.require(identity.trade_intent_id).state is TradeState.ENTRY_SUBMITTED
    broker.submit(pending)
    broker.fill(pending.request.client_order_id, 1)

    record = coordinator.on_fill(
        pending.record,
        client_order_id=pending.request.client_order_id,
        fill_id="7-1",
        fill_quantity=1,
    )
    assert store.require(identity.trade_intent_id).state is TradeState.FILLED

    protection = coordinator.plan_protection(record, SPY_PRICE)
    assert protection is not None
    assert store.require(identity.trade_intent_id).state is TradeState.PROTECTION_SUBMITTED
    broker.submit(protection)

    record = coordinator.confirm_protection(protection.record, broker.view())
    assert store.require(identity.trade_intent_id).state is TradeState.PROTECTED

    record = coordinator.request_exit(record)
    assert store.require(identity.trade_intent_id).state is TradeState.EXIT_REQUESTED

    record = coordinator.request_protection_cancel(record)
    broker.cancel(identity.protective_order_id)
    record = coordinator.confirm_protection_cancel(record)
    assert store.require(identity.trade_intent_id).protected_quantity == 0

    exit_order = coordinator.begin_exit(record, broker.view())
    assert store.require(identity.trade_intent_id).state is TradeState.EXIT_SUBMITTED
    broker.submit(exit_order)
    broker.fill(exit_order.request.client_order_id, 1)

    record = coordinator.on_fill(
        exit_order.record,
        client_order_id=exit_order.request.client_order_id,
        fill_id="9-1",
        fill_quantity=1,
    )
    assert store.require(identity.trade_intent_id).state is TradeState.CLOSED

    record = coordinator.finalize(record, broker.view())
    final = store.require(identity.trade_intent_id)
    assert final.state is TradeState.RECONCILED
    assert broker.position == 0
    assert broker.count(OrderRole.ENTRY) == 1


# ---------------------------------------------------------------------------
# Review item 2 -- cancellation REQUEST is not cancellation CONFIRMATION
# ---------------------------------------------------------------------------


def test_cancel_request_does_not_mark_protection_cancelled(tmp_path: Path) -> None:
    """Requested-but-still-working must reconcile cleanly and must not allow a close."""
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)

    record = coordinator.request_exit(record)
    record = coordinator.request_protection_cancel(record)

    # Broker still working the stop. Internal must still say protected, so that
    # reconciliation AGREES rather than manufacturing a mismatch.
    persisted = store.require(identity.trade_intent_id)
    assert persisted.protected_quantity == 1
    assert persisted.orders[identity.protective_order_id].cancel_requested is True
    assert persisted.orders[identity.protective_order_id].cancelled is False
    coordinator.reconcile(persisted, broker.view())  # must not raise

    # And the close must be refused while the stop can still fire.
    with pytest.raises(ReconciliationError):
        coordinator.begin_exit(persisted, broker.view())
    assert broker.count(OrderRole.EXIT) == 0


def test_cancel_confirmation_updates_state_and_enables_close(tmp_path: Path) -> None:
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)

    record = coordinator.request_exit(record)
    record = coordinator.request_protection_cancel(record)
    broker.cancel(identity.protective_order_id)
    record = coordinator.confirm_protection_cancel(record)

    persisted = store.require(identity.trade_intent_id)
    assert persisted.orders[identity.protective_order_id].cancelled is True
    assert persisted.protected_quantity == 0
    coordinator.reconcile(persisted, broker.view())  # must not raise

    exit_order = coordinator.begin_exit(persisted, broker.view())
    assert exit_order.request.quantity == 1


# ---------------------------------------------------------------------------
# Review item 3 -- the exit order is write-ahead-logged
# ---------------------------------------------------------------------------


def test_exit_order_is_recorded_before_submission(tmp_path: Path) -> None:
    """The durable EXIT record must exist before the broker call, so its fill applies."""
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)
    record = coordinator.request_exit(record)
    record = coordinator.request_protection_cancel(record)
    broker.cancel(identity.protective_order_id)
    record = coordinator.confirm_protection_cancel(record)

    exit_order = coordinator.begin_exit(record, broker.view())

    persisted = store.require(identity.trade_intent_id)
    assert identity.exit_order_id in persisted.orders
    assert persisted.orders[identity.exit_order_id].role is OrderRole.EXIT
    assert persisted.orders[identity.exit_order_id].submitted is True

    # The fill therefore applies against a known order rather than being rejected.
    broker.submit(exit_order)
    broker.fill(identity.exit_order_id, 1)
    closed = coordinator.on_fill(
        exit_order.record,
        client_order_id=identity.exit_order_id,
        fill_id="9-1",
        fill_quantity=1,
    )
    assert closed.state is TradeState.CLOSED
    assert closed.open_long_quantity == 0


def test_reconnect_between_write_ahead_and_submission_creates_no_second_sell(
    tmp_path: Path,
) -> None:
    """Crash after the durable write, before the broker call. Recovery must not re-sell."""
    coordinator, _store, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)
    record = coordinator.request_exit(record)
    record = coordinator.request_protection_cancel(record)
    broker.cancel(identity.protective_order_id)
    record = coordinator.confirm_protection_cancel(record)

    coordinator.begin_exit(record, broker.view())  # written, deliberately NOT submitted
    assert broker.count(OrderRole.EXIT) == 0

    # Restart.
    restarted = Phase2Coordinator(
        JsonTradeStateStore(storage / "phase2_trade_state.json"),
        TradeIdentity.derive(PHASE2_INTENT_NATURAL_KEY, attempt=1),
        storage_root=storage,
        project_root=project,
    )
    recovered = restarted.load()
    assert recovered is not None
    assert recovered.state is TradeState.EXIT_SUBMITTED

    # A second write-ahead for the same exit is refused, so no second SELL.
    with pytest.raises(StateStoreError):
        restarted.begin_exit(recovered, broker.view())
    assert broker.count(OrderRole.EXIT) == 0


# ---------------------------------------------------------------------------
# Review item 5 -- a protective stop fill is a valid exit route
# ---------------------------------------------------------------------------


def test_protective_stop_fill_closes_the_long_without_an_exit_order(tmp_path: Path) -> None:
    """entry 1 -> protection 1 -> stop fills -> flat, no extra SELL, no short."""
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = drive_to_protected(coordinator, broker)
    assert broker.position == 1

    # The stop fires.
    broker.fill(identity.protective_order_id, 1)
    record = coordinator.on_fill(
        record,
        client_order_id=identity.protective_order_id,
        fill_id="8-1",
        fill_quantity=1,
    )

    assert broker.position == 0
    assert record.open_long_quantity == 0, "a filled stop closes the long"
    assert record.protective_fill_quantity == 1
    assert record.state is TradeState.CLOSED
    assert store.require(identity.trade_intent_id).state is TradeState.CLOSED

    # No exit order may be planned for a position that no longer exists.
    with pytest.raises(ReconciliationError):
        coordinator.begin_exit(record, broker.view())
    assert broker.count(OrderRole.EXIT) == 0

    record = coordinator.finalize(record, broker.view())
    assert record.state is TradeState.RECONCILED
    assert broker.position == 0, "no accidental short"


# ---------------------------------------------------------------------------
# Review item 8 -- a consumed arm plus lost trade state must fail closed
# ---------------------------------------------------------------------------


def test_lost_trade_state_with_consumed_arm_fails_closed(tmp_path: Path) -> None:
    """The exact failure mode: armed config, wiped state, would-be virgin run."""
    coordinator, _store, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    drive_to_protected(coordinator, broker)

    state_file = storage / "phase2_trade_state.json"
    assert state_file.exists()
    state_file.unlink()  # mis-mounted object store / wiped runtime directory

    restarted = Phase2Coordinator(
        JsonTradeStateStore(state_file),
        TradeIdentity.derive(PHASE2_INTENT_NATURAL_KEY, attempt=1),
        storage_root=storage,
        project_root=project,
    )
    with pytest.raises(ArmReceiptError, match="already CONSUMED"):
        restarted.load()


def test_receipt_survives_loss_of_either_single_location(tmp_path: Path) -> None:
    """Receipts live on two mounts; losing one must still fail closed."""
    coordinator, _, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    drive_to_protected(coordinator, broker)

    (storage / "phase2_trade_state.json").unlink()
    (storage / "phase2_arm_receipt.json").unlink()  # object store wiped entirely

    restarted = Phase2Coordinator(
        JsonTradeStateStore(storage / "phase2_trade_state.json"),
        TradeIdentity.derive(PHASE2_INTENT_NATURAL_KEY, attempt=1),
        storage_root=storage,
        project_root=project,
    )
    with pytest.raises(ArmReceiptError):
        restarted.load()  # the project-side receipt still catches it


def test_clean_first_run_is_permitted(tmp_path: Path) -> None:
    """No receipt, no state: a genuine first run must not be blocked."""
    coordinator, _, _, _ = make_coordinator(tmp_path)
    assert coordinator.load() is None


# ---------------------------------------------------------------------------
# Review items 6 & 9 -- duplicate events and restart remain no-ops
# ---------------------------------------------------------------------------


def test_duplicate_order_event_is_a_true_noop(tmp_path: Path) -> None:
    """The same (order_id, event_id) delivered repeatedly changes nothing."""
    coordinator, store, _, _ = make_coordinator(tmp_path)
    broker = Broker()
    identity = coordinator.identity
    record = coordinator.authorize(arm_request(), evidence())
    pending = coordinator.begin_entry(record)
    broker.submit(pending)
    broker.fill(identity.entry_order_id, 1)

    record = pending.record
    for _ in range(5):
        record = coordinator.on_fill(
            record, client_order_id=identity.entry_order_id, fill_id="7-1", fill_quantity=1
        )
    assert record.filled_quantity == 1
    assert store.require(identity.trade_intent_id).filled_quantity == 1


def test_restart_after_protection_submits_no_further_entry(tmp_path: Path) -> None:
    coordinator, _, storage, project = make_coordinator(tmp_path)
    broker = Broker()
    drive_to_protected(coordinator, broker)
    entries_before = broker.count(OrderRole.ENTRY)

    restarted = Phase2Coordinator(
        JsonTradeStateStore(storage / "phase2_trade_state.json"),
        TradeIdentity.derive(PHASE2_INTENT_NATURAL_KEY, attempt=1),
        storage_root=storage,
        project_root=project,
    )
    recovered = restarted.load()
    assert recovered is not None
    assert recovered.state is TradeState.PROTECTED

    with pytest.raises(ReconciliationError):
        restarted.begin_entry(recovered)

    assert broker.count(OrderRole.ENTRY) - entries_before == 0
