"""End-to-end simulation of the Phase 2 lifecycle, with no broker involved.

This walks the exact sequence the LEAN algorithm performs:

    arm -> entry -> ack -> fill -> protect actual filled qty -> reconcile
        -> RESTART -> recover -> prove no duplicate entry
        -> cancel protection -> exit -> flat -> RECONCILED

It exists so the plumbing is proven before a single real order exists. The
broker is a small in-memory double; every other component is the production
code the algorithm imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path

import pytest

from kalpamani.broker.account import BrokerAccountMode, BrokerAccountSnapshot
from kalpamani.broker.orders import OrderRequest, OrderSide, OrderType
from kalpamani.common.environment import Environment
from kalpamani.common.settings import Settings
from kalpamani.execution.envelope import (
    PHASE2_CONFIRMATION_PHRASE,
    PHASE2_QUANTITY,
    PHASE2_SYMBOL,
    ExecutionArmError,
    ExecutionArmRequest,
    assert_arm_not_reusable,
    authorize_trade_intent,
    protective_stop_price,
)
from kalpamani.execution.identity import OrderRole
from kalpamani.execution.lifecycle import TradeState, transition
from kalpamani.execution.reconciliation import (
    BrokerOrderView,
    BrokerPositionView,
    BrokerView,
    ReconciliationError,
    assert_flat,
    assert_protected,
    assert_safe_to_close,
    plan_exit,
    reconcile,
    required_protection_quantity,
)
from kalpamani.execution.state_store import (
    JsonTradeStateStore,
    apply_fill,
    record_order_intent,
)

pytestmark = pytest.mark.integration

SPY_PRICE = Decimal("766.38")


@dataclass
class FakeBroker:
    """Minimal in-memory broker double.

    Records every submission so the test can assert exactly how many entry
    orders were ever sent -- the single most important Phase 2 number.
    """

    position: int = 0
    submitted: list[OrderRequest] = field(default_factory=list)
    open_orders: dict[str, OrderRequest] = field(default_factory=dict)

    def submit(self, request: OrderRequest) -> None:
        self.submitted.append(request)
        self.open_orders[request.client_order_id] = request

    def fill(self, client_order_id: str, quantity: int) -> None:
        request = self.open_orders.pop(client_order_id)
        self.position += quantity if request.side is OrderSide.BUY else -quantity

    def cancel(self, client_order_id: str) -> None:
        self.open_orders.pop(client_order_id, None)

    @property
    def entry_submissions(self) -> int:
        return sum(1 for r in self.submitted if r.role is OrderRole.ENTRY)

    def view(self) -> BrokerView:
        return BrokerView(
            positions=(BrokerPositionView(PHASE2_SYMBOL, self.position),),
            open_orders=tuple(
                BrokerOrderView(
                    client_order_id=r.client_order_id,
                    symbol=r.symbol,
                    side=r.side.value,
                    quantity=r.quantity,
                    is_open=True,
                )
                for r in self.open_orders.values()
            ),
        )


def paper_snapshot() -> BrokerAccountSnapshot:
    return BrokerAccountSnapshot(
        account_id="DU1234567",
        mode=BrokerAccountMode.PAPER,
        equity_usd=Decimal("1000000"),
        cash_usd=Decimal("1000000"),
        holdings_count=0,
        open_orders_count=0,
    )


def arm_request() -> ExecutionArmRequest:
    return ExecutionArmRequest(
        confirmation=PHASE2_CONFIRMATION_PHRASE,
        settings=Settings(environment=Environment.PAPER),
        broker_snapshot=paper_snapshot(),
        symbol=PHASE2_SYMBOL,
        quantity=PHASE2_QUANTITY,
        reference_price=SPY_PRICE,
        phase2_test_mode=True,
        explicit_execution_arm=True,
    )


def test_full_phase2_lifecycle_with_restart(tmp_path: Path) -> None:
    """The whole certification sequence, including the restart idempotency proof."""
    state_path = tmp_path / "phase2_state.json"
    store = JsonTradeStateStore(state_path)
    broker = FakeBroker()

    # -- ARM ---------------------------------------------------------------
    identity, record = authorize_trade_intent(arm_request(), store)
    assert record.state is TradeState.AUTHORIZED
    assert record.arm_consumed is True
    store.put(record)  # arm consumed durably BEFORE any broker contact

    # -- ENTRY (write-ahead, then submit) ----------------------------------
    record = record_order_intent(
        record,
        client_order_id=identity.entry_order_id,
        role=OrderRole.ENTRY,
        symbol=PHASE2_SYMBOL,
        side="BUY",
        quantity=PHASE2_QUANTITY,
    )
    record = replace(record, state=transition(record.state, TradeState.ENTRY_SUBMITTED))
    store.put(record)
    broker.submit(
        OrderRequest(
            client_order_id=identity.entry_order_id,
            symbol=PHASE2_SYMBOL,
            side=OrderSide.BUY,
            quantity=PHASE2_QUANTITY,
            order_type=OrderType.MARKET,
            role=OrderRole.ENTRY,
        )
    )
    assert broker.entry_submissions == 1

    # -- FILL --------------------------------------------------------------
    broker.fill(identity.entry_order_id, PHASE2_QUANTITY)
    record = apply_fill(
        record,
        client_order_id=identity.entry_order_id,
        fill_id="fill-1",
        fill_quantity=PHASE2_QUANTITY,
    )
    record = replace(record, state=transition(record.state, TradeState.ENTRY_ACKNOWLEDGED))
    record = replace(record, state=transition(record.state, TradeState.FILLED))
    store.put(record)
    assert record.filled_quantity == 1
    assert broker.position == 1

    # -- PROTECT actual filled quantity ------------------------------------
    quantity = required_protection_quantity(record)
    assert quantity == 1
    stop = protective_stop_price(SPY_PRICE)
    record = record_order_intent(
        record,
        client_order_id=identity.protective_order_id,
        role=OrderRole.PROTECTIVE,
        symbol=PHASE2_SYMBOL,
        side="SELL",
        quantity=quantity,
    )
    record = replace(
        record,
        state=transition(record.state, TradeState.PROTECTION_SUBMITTED),
        protected_quantity=quantity,
    )
    store.put(record)
    broker.submit(
        OrderRequest(
            client_order_id=identity.protective_order_id,
            symbol=PHASE2_SYMBOL,
            side=OrderSide.SELL,
            quantity=quantity,
            order_type=OrderType.STOP_MARKET,
            role=OrderRole.PROTECTIVE,
            stop_price=stop,
        )
    )

    # -- RECONCILE ---------------------------------------------------------
    assert_protected(record, identity, broker.view())
    record = replace(record, state=transition(record.state, TradeState.PROTECTED))
    store.put(record)
    assert reconcile(record, identity, broker.view()).matches is True

    entry_orders_before_restart = broker.entry_submissions
    assert entry_orders_before_restart == 1

    # ======================================================================
    # RESTART. A brand-new store object and a fresh identity derivation stand
    # in for a restarted process. Nothing is carried in memory.
    # ======================================================================
    del store, record

    from kalpamani.execution.envelope import PHASE2_INTENT_NATURAL_KEY
    from kalpamani.execution.identity import TradeIdentity

    recovered_identity = TradeIdentity.derive(PHASE2_INTENT_NATURAL_KEY, attempt=1)
    assert recovered_identity == identity  # ids reproduce exactly

    recovered_store = JsonTradeStateStore(state_path)
    recovered = recovered_store.require(recovered_identity.trade_intent_id)

    assert_arm_not_reusable(recovered)
    assert recovered.entry_count == 1
    assert recovered.state is TradeState.PROTECTED

    # Recovery reconciles; it does not replay intent.
    assert reconcile(recovered, recovered_identity, broker.view()).matches is True
    assert_protected(recovered, recovered_identity, broker.view())

    # Re-arming is refused outright.
    with pytest.raises(ExecutionArmError):
        authorize_trade_intent(arm_request(), recovered_store)

    entry_orders_after_restart = broker.entry_submissions - entry_orders_before_restart
    assert entry_orders_after_restart == 0, "restart must never replay the entry"

    # -- CONTROLLED EXIT: cancel protection FIRST --------------------------
    recovered = replace(recovered, state=transition(recovered.state, TradeState.EXIT_REQUESTED))
    plan = plan_exit(recovered, recovered_identity, broker.view())
    assert plan.cancel_client_order_id == recovered_identity.protective_order_id
    assert plan.exit_quantity == 1

    # Closing while the stop is still live must be refused.
    with pytest.raises(ReconciliationError):
        assert_safe_to_close(plan, recovered_identity, broker.view())

    broker.cancel(recovered_identity.protective_order_id)
    recovered = replace(
        recovered,
        orders={
            **recovered.orders,
            recovered_identity.protective_order_id: replace(
                recovered.orders[recovered_identity.protective_order_id], cancelled=True
            ),
        },
        protected_quantity=0,
    )
    assert_safe_to_close(plan, recovered_identity, broker.view())  # now safe

    # -- EXIT --------------------------------------------------------------
    recovered = record_order_intent(
        recovered,
        client_order_id=recovered_identity.exit_order_id,
        role=OrderRole.EXIT,
        symbol=PHASE2_SYMBOL,
        side="SELL",
        quantity=plan.exit_quantity,
    )
    recovered = replace(recovered, state=transition(recovered.state, TradeState.EXIT_SUBMITTED))
    recovered_store.put(recovered)
    broker.submit(
        OrderRequest(
            client_order_id=recovered_identity.exit_order_id,
            symbol=PHASE2_SYMBOL,
            side=OrderSide.SELL,
            quantity=plan.exit_quantity,
            order_type=OrderType.MARKET,
            role=OrderRole.EXIT,
        )
    )
    broker.fill(recovered_identity.exit_order_id, plan.exit_quantity)
    recovered = apply_fill(
        recovered,
        client_order_id=recovered_identity.exit_order_id,
        fill_id="fill-exit-1",
        fill_quantity=plan.exit_quantity,
    )
    recovered = replace(recovered, state=transition(recovered.state, TradeState.CLOSED))
    recovered_store.put(recovered)

    # -- FINAL ACCEPTANCE --------------------------------------------------
    assert broker.position == 0
    assert recovered.open_long_quantity == 0
    assert_flat(recovered, recovered_identity, broker.view())

    recovered = replace(recovered, state=transition(recovered.state, TradeState.RECONCILED))
    recovered_store.put(recovered)

    final = JsonTradeStateStore(state_path).require(recovered_identity.trade_intent_id)
    assert final.state is TradeState.RECONCILED
    assert final.entry_count == 1
    assert broker.entry_submissions == 1, "exactly one entry order across the entire lifecycle"


def test_zero_fill_lifecycle_creates_no_protection(tmp_path: Path) -> None:
    """An entry that never fills must not produce a stop, which could open a short."""
    store = JsonTradeStateStore(tmp_path / "state.json")
    identity, record = authorize_trade_intent(arm_request(), store)
    record = record_order_intent(
        record,
        client_order_id=identity.entry_order_id,
        role=OrderRole.ENTRY,
        symbol=PHASE2_SYMBOL,
        side="BUY",
        quantity=PHASE2_QUANTITY,
    )
    record = replace(record, state=transition(record.state, TradeState.ENTRY_SUBMITTED))
    store.put(record)

    assert required_protection_quantity(record) == 0
    broker = FakeBroker(position=0)
    assert_flat(record, identity, broker.view())


def test_duplicate_fill_events_produce_one_protection_quantity(tmp_path: Path) -> None:
    """Repeated delivery of the same fill must not inflate protection."""
    store = JsonTradeStateStore(tmp_path / "state.json")
    identity, record = authorize_trade_intent(arm_request(), store)
    record = record_order_intent(
        record,
        client_order_id=identity.entry_order_id,
        role=OrderRole.ENTRY,
        symbol=PHASE2_SYMBOL,
        side="BUY",
        quantity=PHASE2_QUANTITY,
    )
    for _ in range(4):
        record = apply_fill(
            record,
            client_order_id=identity.entry_order_id,
            fill_id="the-same-fill",
            fill_quantity=1,
        )
    assert record.filled_quantity == 1
    assert required_protection_quantity(record) == 1
