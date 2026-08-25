# region imports
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from AlgorithmImports import *

from kalpamani.broker.account import BrokerAccountMode, BrokerAccountSnapshot
from kalpamani.common.capital import DEFAULT_STRATEGY_CAPITAL_USD, StrategyCapital
from kalpamani.common.environment import Environment
from kalpamani.common.settings import LIVE_TRADING_HARD_DISABLED, Settings
from kalpamani.execution.envelope import (
    PHASE2_INTENT_NATURAL_KEY,
    PHASE2_QUANTITY,
    PHASE2_SYMBOL,
    ExecutionArmRequest,
    assert_arm_not_reusable,
    authorize_trade_intent,
    describe_envelope,
    protective_stop_price,
)
from kalpamani.execution.identity import OrderRole, TradeIdentity, is_valid_client_order_id
from kalpamani.execution.lifecycle import TradeState, transition
from kalpamani.execution.reconciliation import (
    BrokerOrderView,
    BrokerPositionView,
    BrokerView,
    assert_flat,
    assert_protected,
    plan_exit,
    reconcile,
    required_protection_quantity,
)
from kalpamani.execution.state_store import (
    JsonTradeStateStore,
    apply_fill,
    record_order_intent,
)

# endregion

# ---------------------------------------------------------------------------
# KalpaMani -- Phase 2 controlled IBKR Paper order lifecycle certification
#
# This is EXECUTION PLUMBING CERTIFICATION, not a strategy. It exists to prove:
#   arm -> BUY 1 SPY -> ack -> fill -> protect actual filled qty -> reconcile
#   -> restart -> recover WITHOUT duplicating -> controlled exit -> flat.
#
# Normal startup is READ/RECONCILE ONLY. No order is submitted unless an
# explicit, one-time human arm is present. Once consumed, the arm is spent
# durably; a restart recovers and reconciles, it never re-submits.
#
# The safety logic lives in the `kalpamani` package -- the same code the unit
# tests cover -- rather than being duplicated here, so it cannot drift.
#
# ADR-0003: there is no broker-side backstop. IBAutomater disables IB Gateway's
# [Read-Only API] and bypasses its order precautions on every start. The guards
# in this file and in kalpamani.execution are the ONLY guards.
# ---------------------------------------------------------------------------

#: Where durable trade state lives inside the container. Mapped to the untracked
#: runtime workspace on the host.
STATE_PATH = Path("/Storage/phase2_trade_state.json")

#: How often to reconcile against broker truth, in minutes.
RECONCILE_INTERVAL_MINUTES = 1


class Phase2OrderLifecycle(QCAlgorithm):
    """Certifies the order lifecycle. One share of SPY, once, then flat."""

    # -- Setup -------------------------------------------------------------

    def initialize(self) -> None:
        if not self.live_mode:
            self.set_start_date(2024, 1, 2)
            self.set_end_date(2024, 1, 5)
            self.set_cash(int(DEFAULT_STRATEGY_CAPITAL_USD))

        self._symbol = self.add_equity(
            PHASE2_SYMBOL, Resolution.MINUTE, extended_market_hours=True
        ).symbol

        self._store = JsonTradeStateStore(STATE_PATH)
        self._identity = TradeIdentity.derive(PHASE2_INTENT_NATURAL_KEY, attempt=1)
        self._settings = Settings(environment=Environment.PAPER)

        # Operator inputs. Absent by default -- that is what makes normal
        # startup read-only.
        self._test_mode = self._flag("phase2_test_mode")
        self._arm_flag = self._flag("explicit_execution_arm")
        self._confirmation = self.get_parameter("phase2_confirmation") or ""
        self._exit_requested = self._flag("phase2_exit_requested")

        self._entry_submitted_this_session = 0
        self._reconciled_once = False
        self._armed_and_authorized = False
        self._aborted = False

        self.log("=" * 78)
        self.log("KalpaMani Phase 2 -- CONTROLLED IBKR PAPER ORDER LIFECYCLE")
        self.log(f"[PHASE2-ARM] envelope: {describe_envelope()}")
        self.log(f"[PHASE2-ARM] identity: {self._identity.describe()}")
        self.log(f"[PHASE2-ARM] test_mode={self._test_mode} arm_flag={self._arm_flag}")
        self.log(f"[PHASE2-ARM] exit_requested={self._exit_requested}")
        self.log(f"[PHASE2-ARM] live_trading_hard_disabled={LIVE_TRADING_HARD_DISABLED}")
        self.log(f"[PHASE2-ARM] strategy_capital_usd={DEFAULT_STRATEGY_CAPITAL_USD}")
        self.log("[PHASE2-ARM] Broker state is NOT read here; LEAN applies brokerage cash")
        self.log("[PHASE2-ARM] after initialize() returns. Reconciliation runs on a schedule.")
        self.log("=" * 78)

        # Everything happens on the schedule, after brokerage setup completes.
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.every(timedelta(minutes=RECONCILE_INTERVAL_MINUTES)),
            self._on_cycle,
        )

    def _flag(self, name: str) -> bool:
        raw = self.get_parameter(name)
        return str(raw).strip().lower() == "true" if raw is not None else False

    # -- Broker observation -------------------------------------------------

    def _account_snapshot(self) -> BrokerAccountSnapshot:
        """Read broker account state, classifying paper-vs-live from the id."""
        account_id = ""
        try:
            account_id = str(self.portfolio.cash_book.account_currency or "")
        except Exception:
            account_id = ""
        # LEAN exposes the brokerage account id on the live job; fall back to the
        # configured id when unavailable. Mode is derived, never assumed.
        configured = self.get_parameter("ibkr_account_id") or account_id
        return BrokerAccountSnapshot(
            account_id=str(configured),
            mode=BrokerAccountMode.classify(str(configured)),
            equity_usd=Decimal(str(self.portfolio.total_portfolio_value)),
            cash_usd=Decimal(str(self.portfolio.cash)),
            holdings_count=sum(1 for h in self.portfolio.values() if h.invested),
            open_orders_count=len(self.transactions.get_open_orders()),
        )

    def _broker_view(self) -> BrokerView:
        """Build a reconciliation view from broker truth, not from local belief."""
        positions = tuple(
            BrokerPositionView(symbol=str(h.symbol.value), quantity=int(h.quantity))
            for h in self.portfolio.values()
            if h.invested
        )
        open_orders = []
        for order in self.transactions.get_open_orders():
            tag = str(order.tag or "")
            if not is_valid_client_order_id(tag):
                continue  # someone else's order: never adopted, never touched
            open_orders.append(
                BrokerOrderView(
                    client_order_id=tag,
                    symbol=str(order.symbol.value),
                    side="BUY" if order.quantity > 0 else "SELL",
                    quantity=abs(int(order.quantity)),
                    is_open=True,
                )
            )
        return BrokerView(positions=positions, open_orders=tuple(open_orders))

    # -- Main cycle ---------------------------------------------------------

    def _on_cycle(self) -> None:
        """Reconcile first, always. Only then consider acting."""
        if self._aborted:
            return
        try:
            record = self._store.get(self._identity.trade_intent_id)
            broker = self._broker_view()

            if record is None:
                self._log_broker_state(broker, "no-trade")
                self._maybe_arm(broker)
                return

            # A record exists: this is recovery or continuation. Reconcile before
            # anything else, and never re-arm.
            assert_arm_not_reusable(record)
            if not self._reconciled_once:
                self.log(f"[RECOVERY] recovered {record.describe()}")
                self.log(f"[RECOVERY] entry_orders_before_restart={record.entry_count}")
                self.log(
                    "[RECOVERY] entry_orders_submitted_this_session="
                    f"{self._entry_submitted_this_session}"
                )
                self.log("[IDEMPOTENCY-PASS] recovery adopts existing state; no entry replay")
                self._reconciled_once = True

            self._reconcile(record, broker)
            self._progress(record, broker)
        except Exception as exc:
            self._abort(f"{type(exc).__name__}: {exc}")

    def _log_broker_state(self, broker: BrokerView, context: str) -> None:
        self.log(
            f"[RECONCILE:{context}] spy_position={broker.position_quantity(PHASE2_SYMBOL)} "
            f"owned_open_orders={len(broker.orders_owned_by(self._identity))} "
            f"broker_equity_usd={self.portfolio.total_portfolio_value} "
            f"strategy_capital_usd={DEFAULT_STRATEGY_CAPITAL_USD}"
        )

    # -- Arming -------------------------------------------------------------

    def _maybe_arm(self, broker: BrokerView) -> None:
        """Open the order path only if every gate passes. Otherwise stay read-only."""
        if not (self._test_mode and self._arm_flag):
            return

        if broker.position_quantity(PHASE2_SYMBOL) != 0:
            self._abort(
                f"Pre-order reconciliation found an existing {PHASE2_SYMBOL} position "
                f"({broker.position_quantity(PHASE2_SYMBOL)}). Not ours to assume; not "
                "liquidating it. Resolve manually before arming."
            )
            return
        if broker.orders_owned_by(self._identity):
            self._abort("Pre-order reconciliation found existing KalpaMani orders.")
            return

        snapshot = self._account_snapshot()
        price = Decimal(str(self.securities[self._symbol].price))
        if price <= 0:
            self.log("[PHASE2-ARM] waiting for a valid SPY price before arming")
            return

        request = ExecutionArmRequest(
            confirmation=self._confirmation,
            settings=self._settings,
            broker_snapshot=snapshot,
            symbol=PHASE2_SYMBOL,
            quantity=PHASE2_QUANTITY,
            reference_price=price,
            phase2_test_mode=self._test_mode,
            explicit_execution_arm=self._arm_flag,
        )
        identity, record = authorize_trade_intent(request, self._store, capital=StrategyCapital())
        self._identity = identity
        self._armed_and_authorized = True

        self.log("=" * 78)
        self.log(f"[TRADE-INTENT] authorized {record.describe()}")
        self.log(f"[TRADE-INTENT] account_mode={snapshot.mode.value} price={price}")
        self.log(f"[TRADE-INTENT] notional_usd={request.notional_usd}")
        self.log("=" * 78)

        self._store.put(record)  # arm consumed durably BEFORE any broker contact
        self._submit_entry(record)

    # -- Entry --------------------------------------------------------------

    def _submit_entry(self, record) -> None:
        """Submit the single entry order, write-ahead-logged before it is sent."""
        if record.entry_count >= 1 or self._entry_submitted_this_session >= 1:
            self._abort("Refusing a second entry order.")
            return

        client_order_id = self._identity.entry_order_id
        pending = record_order_intent(
            record,
            client_order_id=client_order_id,
            role=OrderRole.ENTRY,
            symbol=PHASE2_SYMBOL,
            side="BUY",
            quantity=PHASE2_QUANTITY,
        )
        pending = replace(pending, state=transition(pending.state, TradeState.ENTRY_SUBMITTED))
        self._store.put(pending)  # durable BEFORE submission

        self.log(f"[ENTRY-SUBMIT] BUY {PHASE2_QUANTITY} {PHASE2_SYMBOL} as {client_order_id}")
        self.market_order(self._symbol, PHASE2_QUANTITY, tag=client_order_id)
        self._entry_submitted_this_session += 1

    # -- Fills and protection ----------------------------------------------

    def on_order_event(self, order_event: OrderEvent) -> None:
        """Apply fills idempotently and protect the ACTUAL filled quantity."""
        if self._aborted:
            return
        try:
            order = self.transactions.get_order_by_id(order_event.order_id)
            tag = str(order.tag or "")
            if not is_valid_client_order_id(tag) or not self._identity.owns(tag):
                return  # not ours

            self.log(
                f"[ENTRY-ACK] order={tag} status={order_event.status} "
                f"fill_qty={order_event.fill_quantity} fill_price={order_event.fill_price}"
            )
            if int(order_event.fill_quantity) == 0:
                return

            record = self._store.require(self._identity.trade_intent_id)
            fill_id = f"{order_event.order_id}:{order_event.utc_time.isoformat()}"
            record = apply_fill(
                record,
                client_order_id=tag,
                fill_id=fill_id,
                fill_quantity=abs(int(order_event.fill_quantity)),
            )
            self.log(
                f"[FILL] {tag} filled={record.filled_quantity} "
                f"price={order_event.fill_price} fill_id={fill_id}"
            )

            if tag == self._identity.entry_order_id:
                record = self._advance_after_entry_fill(record)
                self._store.put(record)
                self._protect(record, Decimal(str(order_event.fill_price)))
            else:
                self._store.put(record)
        except Exception as exc:
            self._abort(f"order-event handling failed: {type(exc).__name__}: {exc}")

    def _advance_after_entry_fill(self, record):
        """Walk the legal intermediate states rather than jumping over them."""
        state = record.state
        if state is TradeState.ENTRY_SUBMITTED:
            state = transition(state, TradeState.ENTRY_ACKNOWLEDGED)
        if state is TradeState.ENTRY_ACKNOWLEDGED:
            target = (
                TradeState.FILLED
                if record.filled_quantity >= record.requested_quantity
                else TradeState.PARTIALLY_FILLED
            )
            state = transition(state, target)
        elif state is TradeState.PARTIALLY_FILLED and (
            record.filled_quantity >= record.requested_quantity
        ):
            state = transition(state, TradeState.FILLED)
        return replace(record, state=state)

    def _protect(self, record, fill_price: Decimal) -> None:
        """Submit protection for the actual filled quantity. Zero fill -> no stop."""
        quantity = required_protection_quantity(record)
        if quantity <= 0:
            self.log("[PROTECTION-SUBMIT] skipped: zero filled quantity, nothing to protect")
            return
        if record.order_for_role(OrderRole.PROTECTIVE) is not None:
            self.log("[IDEMPOTENCY-PASS] protection already recorded; not duplicating")
            return

        stop_price = protective_stop_price(fill_price)
        client_order_id = self._identity.protective_order_id
        pending = record_order_intent(
            record,
            client_order_id=client_order_id,
            role=OrderRole.PROTECTIVE,
            symbol=PHASE2_SYMBOL,
            side="SELL",
            quantity=quantity,
        )
        pending = replace(
            pending,
            state=transition(pending.state, TradeState.PROTECTION_SUBMITTED),
            protected_quantity=quantity,
        )
        self._store.put(pending)

        self.log(
            f"[PROTECTION-SUBMIT] SELL {quantity} {PHASE2_SYMBOL} stop={stop_price} "
            f"as {client_order_id}  (TEST PARAMETER -- NOT PRODUCTION STRATEGY LOGIC)"
        )
        self.stop_market_order(self._symbol, -quantity, stop_price, tag=client_order_id)

    # -- Reconciliation and progression ------------------------------------

    def _reconcile(self, record, broker: BrokerView) -> None:
        self._log_broker_state(broker, record.state.value)
        result = reconcile(record, self._identity, broker)
        self.log(f"[RECONCILE] {result.describe()}")

    def _progress(self, record, broker: BrokerView) -> None:
        """Advance the lifecycle only where broker truth supports it."""
        if record.open_long_quantity > 0:
            assert_protected(record, self._identity, broker)
            self.log("[PROTECTION-ACK] broker confirms protection matches filled quantity")

        if self._exit_requested and record.open_long_quantity > 0:
            plan = plan_exit(record, self._identity, broker)
            self.log(f"[EXIT-REQUEST] {plan.describe()}")
            if plan.cancel_client_order_id is not None:
                self._cancel(plan.cancel_client_order_id)
                self.log("[EXIT-REQUEST] protection cancellation requested; will verify next cycle")
                return
            self.log(f"[EXIT-SUBMIT] SELL {plan.exit_quantity} {PHASE2_SYMBOL}")
            self.market_order(self._symbol, -plan.exit_quantity, tag=plan.exit_client_order_id)

        if record.open_long_quantity == 0 and record.entry_count == 1:
            assert_flat(record, self._identity, broker)
            self.log("[FINAL-RECONCILE] flat: no position, no open KalpaMani orders")

    def _cancel(self, client_order_id: str) -> None:
        for order in self.transactions.get_open_orders():
            if str(order.tag or "") == client_order_id:
                self.transactions.cancel_order(order.id)
                self.log(f"[EXIT-REQUEST] cancel requested for {client_order_id}")

    # -- Failure ------------------------------------------------------------

    def _abort(self, reason: str) -> None:
        """Halt Phase 2. Never retries, never submits another entry."""
        self._aborted = True
        self.error(f"[PHASE2-ABORT] {reason}")
        self.error("[PHASE2-ABORT] Halting. No further orders will be submitted this session.")

    # -- Shutdown -----------------------------------------------------------

    def on_end_of_algorithm(self) -> None:
        holdings = sum(1 for h in self.portfolio.values() if h.invested)
        open_orders = len(self.transactions.get_open_orders())
        spy_quantity = int(self.portfolio[self._symbol].quantity)

        self.log("=" * 78)
        self.log("KalpaMani Phase 2 -- SHUTDOWN RECONCILIATION")
        self.log(f"  entry orders submitted this session : {self._entry_submitted_this_session}")
        self.log(f"  armed this session                  : {self._armed_and_authorized}")
        self.log(f"  aborted                             : {self._aborted}")
        self.log(f"  {PHASE2_SYMBOL} position                        : {spy_quantity}")
        self.log(f"  holdings                            : {holdings}")
        self.log(f"  open orders                         : {open_orders}")
        self.log(f"  total orders                        : {self.transactions.orders_count}")
        self.log(f"  strategy capital                    : USD {DEFAULT_STRATEGY_CAPITAL_USD}")
        self.log(
            f"  broker equity observed              : USD {self.portfolio.total_portfolio_value}"
        )
        if spy_quantity < 0:
            self.error("  RESULT: ACCIDENTAL SHORT POSITION. Investigate immediately.")
        elif spy_quantity == 0 and open_orders == 0:
            self.log("  RESULT: FLAT. No position, no open orders.")
        else:
            self.log("  RESULT: position and/or orders remain; see runbook before restarting.")
        self.log("=" * 78)
