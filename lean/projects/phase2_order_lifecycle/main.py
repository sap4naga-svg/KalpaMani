# region imports
from decimal import Decimal
from pathlib import Path

from AlgorithmImports import *

from kalpamani.common.capital import DEFAULT_STRATEGY_CAPITAL_USD, StrategyCapital
from kalpamani.common.environment import Environment
from kalpamani.common.settings import LIVE_TRADING_HARD_DISABLED, Settings
from kalpamani.execution.coordinator import PendingOrder, Phase2Coordinator
from kalpamani.execution.envelope import (
    PHASE2_INTENT_NATURAL_KEY,
    PHASE2_QUANTITY,
    PHASE2_SYMBOL,
    ExecutionArmRequest,
    describe_envelope,
)
from kalpamani.execution.identity import TradeIdentity, is_valid_client_order_id
from kalpamani.execution.lifecycle import TradeState
from kalpamani.execution.reconciliation import (
    BrokerOrderView,
    BrokerPositionView,
    BrokerView,
)
from kalpamani.execution.session import (
    account_fingerprint,
    load_session_evidence,
    verify_paper_session,
)
from kalpamani.execution.state_store import JsonTradeStateStore

# endregion

# ---------------------------------------------------------------------------
# KalpaMani -- Phase 2 controlled IBKR Paper order lifecycle certification
#
# EXECUTION PLUMBING CERTIFICATION, not a strategy.
#
# This file holds NO lifecycle logic. It performs broker I/O and hands events to
# Phase2Coordinator, which owns every state transition and every durable write.
# That split is deliberate: the first Phase 2 review found an integration test
# performing transitions this file never did, so the tests passed while
# production skipped steps. Now both call the same coordinator.
#
# Normal startup is READ/RECONCILE ONLY. No order is submitted without an
# explicit one-time arm, and the arm is consumed durably before any broker call.
#
# ADR-0003: IBAutomater disables IB Gateway's [Read-Only API] and bypasses its
# order precautions on every start. There is NO broker-side backstop. The guards
# in kalpamani.execution are the only guards.
# ---------------------------------------------------------------------------

#: Durable state, on the object-store mount. Verified against the LEAN CLI:
#: `/Storage` binds to `<cli-root>/storage`, i.e. `.runtime/lean/storage/`.
STORAGE_ROOT = Path("/Storage")
STATE_PATH = STORAGE_ROOT / "phase2_trade_state.json"

#: The project directory mount, used as the second, independent arm-receipt
#: location so losing one mount cannot look like a first run.
PROJECT_ROOT = Path("/LeanCLI")

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

        identity = TradeIdentity.derive(PHASE2_INTENT_NATURAL_KEY, attempt=1)
        self._coordinator = Phase2Coordinator(
            JsonTradeStateStore(STATE_PATH),
            identity,
            storage_root=STORAGE_ROOT,
            project_root=PROJECT_ROOT,
        )
        self._settings = Settings(environment=Environment.PAPER)

        self._test_mode = self._flag("phase2_test_mode")
        self._arm_flag = self._flag("explicit_execution_arm")
        self._confirmation = self.get_parameter("phase2_confirmation") or ""
        self._exit_requested = self._flag("phase2_exit_requested")

        self._entries_submitted_this_session = 0
        self._recovery_logged = False
        self._aborted = False

        self.log("=" * 78)
        self.log("KalpaMani Phase 2 -- CONTROLLED IBKR PAPER ORDER LIFECYCLE")
        self.log(f"[PHASE2-ARM] envelope: {describe_envelope()}")
        self.log(f"[PHASE2-ARM] identity: {identity.describe()}")
        self.log(f"[PHASE2-ARM] test_mode={self._test_mode} arm_flag={self._arm_flag}")
        self.log(f"[PHASE2-ARM] exit_requested={self._exit_requested}")
        self.log(f"[PHASE2-ARM] live_trading_hard_disabled={LIVE_TRADING_HARD_DISABLED}")
        self.log(f"[PHASE2-ARM] strategy_capital_usd={DEFAULT_STRATEGY_CAPITAL_USD}")
        self.log(f"[PHASE2-ARM] durable_state={STATE_PATH}")
        self.log("[PHASE2-ARM] Broker state is NOT read here; LEAN applies brokerage cash")
        self.log("[PHASE2-ARM] after initialize() returns. Work happens on the schedule.")
        self.log("=" * 78)

        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.every(timedelta(minutes=RECONCILE_INTERVAL_MINUTES)),
            self._on_cycle,
        )

    def _flag(self, name: str) -> bool:
        raw = self.get_parameter(name)
        return str(raw).strip().lower() == "true" if raw is not None else False

    # -- Broker observation -------------------------------------------------

    def _broker_view(self) -> BrokerView:
        """Build a reconciliation view from broker truth, not local belief."""
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

    def _submit(self, pending: PendingOrder) -> None:
        """Perform the LEAN call for an order the coordinator already recorded."""
        request = pending.request
        self.log(f"[{request.role.value}-SUBMIT] {request.describe()}")
        if request.stop_price is None:
            self.market_order(self._symbol, request.signed_quantity, tag=request.client_order_id)
        else:
            self.stop_market_order(
                self._symbol,
                request.signed_quantity,
                float(request.stop_price),
                tag=request.client_order_id,
            )

    # -- Main cycle ---------------------------------------------------------

    def _on_cycle(self) -> None:
        """Reconcile first, always. Only then consider acting."""
        if self._aborted:
            return
        try:
            record = self._coordinator.load()
            broker = self._broker_view()

            if record is None:
                self._log_state(broker, "no-trade")
                self._maybe_arm(broker)
                return

            if not self._recovery_logged:
                self._recovery_logged = True
                self.log(f"[RECOVERY] recovered {record.describe()}")
                self.log(f"[RECOVERY] entry_orders_before_restart={record.entry_count}")
                self.log(
                    "[RECOVERY] entry_orders_submitted_this_session="
                    f"{self._entries_submitted_this_session}"
                )
                self.log("[IDEMPOTENCY-PASS] recovery adopts existing state; no entry replay")

            self._log_state(broker, record.state.value)
            self._coordinator.reconcile(record, broker)
            self.log(f"[RECONCILE] {record.describe()}")
            self._progress(record, broker)
        except Exception as exc:
            self._abort(f"{type(exc).__name__}: {exc}")

    def _log_state(self, broker: BrokerView, context: str) -> None:
        self.log(
            f"[RECONCILE:{context}] spy_position={broker.position_quantity(PHASE2_SYMBOL)} "
            f"owned_open_orders={len(broker.orders_owned_by(self._coordinator.identity))} "
            f"broker_equity_usd={self.portfolio.total_portfolio_value} "
            f"strategy_capital_usd={DEFAULT_STRATEGY_CAPITAL_USD}"
        )

    # -- Arming -------------------------------------------------------------

    def _maybe_arm(self, broker: BrokerView) -> None:
        """Open the order path only if every gate passes. Otherwise stay read-only.

        Session evidence comes from LEAN's own deployment configuration -- never
        from an algorithm parameter, and with no fallback. If it cannot be read,
        the session cannot be proven paper and Phase 2 aborts.
        """
        evidence = load_session_evidence()

        if not (self._test_mode and self._arm_flag):
            # Even disarmed, prove and report the session. This is exactly what
            # the disarmed dry run is for.
            verify_paper_session(evidence)
            self.log(f"[RECONCILE] session verified PAPER: {evidence.describe()}")
            return

        if broker.position_quantity(PHASE2_SYMBOL) != 0:
            self._abort(
                f"Pre-order reconciliation found an existing {PHASE2_SYMBOL} position "
                f"({broker.position_quantity(PHASE2_SYMBOL)}). Not ours to assume, and not "
                "liquidating it. Resolve manually before arming."
            )
            return
        if broker.orders_owned_by(self._coordinator.identity):
            self._abort("Pre-order reconciliation found existing KalpaMani orders.")
            return

        # The armed account must BE the deployed account. The arm script derives
        # its value from this same deployment config, so the two cannot be
        # independent values that disagree -- and this re-checks it anyway.
        armed_account = self.get_parameter("ibkr_account_id") or ""
        expected = account_fingerprint(armed_account) if armed_account else None
        verify_paper_session(evidence, expected_fingerprint=expected)
        self.log(f"[PHASE2-ARM] session verified PAPER: {evidence.describe()}")

        price = Decimal(str(self.securities[self._symbol].price))
        if price <= 0:
            self.log("[PHASE2-ARM] waiting for a valid SPY price before arming")
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
        record = self._coordinator.authorize(request, evidence, capital=StrategyCapital())
        self.log("=" * 78)
        self.log(f"[TRADE-INTENT] authorized {record.describe()}")
        self.log(f"[TRADE-INTENT] reference_price={price} notional={request.notional_usd}")
        self.log("=" * 78)

        pending = self._coordinator.begin_entry(record)
        self._submit(pending)
        self._entries_submitted_this_session += 1

    # -- Order events -------------------------------------------------------

    def on_order_event(self, order_event: OrderEvent) -> None:
        """Route broker events to the coordinator. No lifecycle logic here."""
        if self._aborted:
            return
        try:
            order = self.transactions.get_order_by_id(order_event.order_id)
            tag = str(order.tag or "")
            if not is_valid_client_order_id(tag) or not self._coordinator.identity.owns(tag):
                return  # not ours

            status = str(order_event.status)
            self.log(f"[ENTRY-ACK] order={tag} status={status} qty={order_event.fill_quantity}")

            record = self._coordinator.load()
            if record is None:
                self._abort(f"Order event for {tag} with no durable trade record.")
                return

            if "cancel" in status.lower():
                self._coordinator.confirm_protection_cancel(record)
                self.log(f"[EXIT-REQUEST] cancellation CONFIRMED by broker for {tag}")
                return

            if int(order_event.fill_quantity) == 0:
                return

            # Stable event identity: LEAN's per-order OrderEvent.id, confirmed
            # present on this version via the QuantConnect stubs. Repeated
            # delivery of the same event is therefore a true no-op.
            fill_id = f"{order_event.order_id}-{order_event.id}"
            record = self._coordinator.on_fill(
                record,
                client_order_id=tag,
                fill_id=fill_id,
                fill_quantity=abs(int(order_event.fill_quantity)),
            )
            self.log(
                f"[FILL] {tag} filled={record.filled_quantity} long={record.open_long_quantity} "
                f"price={order_event.fill_price} fill_id={fill_id}"
            )

            if tag == self._coordinator.identity.entry_order_id:
                protection = self._coordinator.plan_protection(
                    record, Decimal(str(order_event.fill_price))
                )
                if protection is None:
                    self.log("[PROTECTION-SUBMIT] skipped: nothing filled, nothing to protect")
                else:
                    self._submit(protection)
            elif tag == self._coordinator.identity.protective_order_id:
                self.log("[EXIT-FILL] protective stop filled; the long is closed by the stop")
        except Exception as exc:
            self._abort(f"order-event handling failed: {type(exc).__name__}: {exc}")

    # -- Progression --------------------------------------------------------

    def _progress(self, record, broker: BrokerView) -> None:
        """Advance only where broker truth supports it. Every write via the coordinator."""
        identity = self._coordinator.identity

        if record.state is TradeState.PROTECTION_SUBMITTED and record.open_long_quantity > 0:
            record = self._coordinator.confirm_protection(record, broker)
            self.log("[PROTECTION-ACK] broker confirms protection matches filled quantity")

        if self._exit_requested and record.open_long_quantity > 0:
            if record.state is TradeState.PROTECTED:
                record = self._coordinator.request_exit(record)
                self.log("[EXIT-REQUEST] exit requested")

            if broker.open_protective_quantity(identity) > 0:
                record = self._coordinator.request_protection_cancel(record)
                self._cancel(identity.protective_order_id)
                self.log("[EXIT-REQUEST] cancel requested; awaiting broker CONFIRMATION")
                return

            if record.state is TradeState.EXIT_REQUESTED:
                pending = self._coordinator.begin_exit(record, broker)
                self._submit(pending)
                return

        if record.state is TradeState.CLOSED:
            record = self._coordinator.finalize(record, broker)
            self.log("[FINAL-RECONCILE] flat: no position, no open KalpaMani orders")
            self.log(f"[FINAL-RECONCILE] {record.describe()}")

    def _cancel(self, client_order_id: str) -> None:
        for order in self.transactions.get_open_orders():
            if str(order.tag or "") == client_order_id:
                self.transactions.cancel_order(order.id)

    # -- Failure ------------------------------------------------------------

    def _abort(self, reason: str) -> None:
        self._aborted = True
        self.error(f"[PHASE2-ABORT] {reason}")
        self.error("[PHASE2-ABORT] Halting. No further orders will be submitted this session.")

    # -- Shutdown -----------------------------------------------------------

    def on_end_of_algorithm(self) -> None:
        open_orders = len(self.transactions.get_open_orders())
        spy_quantity = int(self.portfolio[self._symbol].quantity)

        self.log("=" * 78)
        self.log("KalpaMani Phase 2 -- SHUTDOWN RECONCILIATION")
        self.log(f"  entry orders submitted this session : {self._entries_submitted_this_session}")
        self.log(f"  aborted                             : {self._aborted}")
        self.log(f"  {PHASE2_SYMBOL} position                        : {spy_quantity}")
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
