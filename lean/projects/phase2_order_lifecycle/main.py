# region imports
# NOTE: `import decimal`, deliberately NOT `from decimal import Decimal`.
# `from AlgorithmImports import *` below rebinds the bare name `Decimal` to
# .NET's System.Decimal, whose constructor rejects a str -- so `Decimal(str(x))`
# raises TypeError inside the container while working perfectly in every test.
# Import order cannot save us: isort puts stdlib imports above the star import,
# so the shadowing always wins. Referencing `decimal.Decimal` sidesteps it,
# because only the attribute name is exported, not the module name.
import decimal
from pathlib import Path

from AlgorithmImports import *

from kalpamani.common.capital import DEFAULT_STRATEGY_CAPITAL_USD, StrategyCapital
from kalpamani.common.environment import Environment
from kalpamani.common.settings import LIVE_TRADING_HARD_DISABLED, Settings
from kalpamani.execution.coordinator import Phase2Coordinator
from kalpamani.execution.cycle import EventStatus, OrderEventFacts, Phase2Cycle
from kalpamani.execution.envelope import (
    PHASE2_SYMBOL,
    certification_identity,
    describe_envelope,
    require_run_number,
)
from kalpamani.execution.halt import JsonHaltStore, halt_state_path
from kalpamani.execution.reconciliation import (
    BrokerOrderView,
    BrokerPositionView,
    BrokerView,
)
from kalpamani.execution.state_store import JsonTradeStateStore
from kalpamani.execution.trading_window import PHASE2_TIME_ZONE, describe_window

# endregion

# ---------------------------------------------------------------------------
# KalpaMani -- Phase 2 controlled IBKR Paper order lifecycle certification
#
# EXECUTION PLUMBING CERTIFICATION, not a strategy.
#
# This file is an ADAPTER. It holds NO lifecycle logic and makes NO decisions:
# it translates LEAN types into kalpamani.execution.cycle calls and back again.
# Every decision -- when to arm, what recovery may re-dispatch, how an event is
# applied, when to halt -- lives in Phase2Cycle, which is importable and driven
# directly by the test suite. That split exists because this file cannot be
# imported outside a LEAN container: logic living here could only ever be
# reviewed by reading it, and a review found exactly that gap.
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


class LeanBrokerPort:
    """Broker I/O for Phase2Cycle, expressed in LEAN's API.

    The whole LEAN surface Phase 2 touches is here, and nothing here decides
    anything.
    """

    def __init__(self, algorithm, symbol) -> None:
        self._algorithm = algorithm
        self._symbol = symbol

    # -- Observation --------------------------------------------------------

    def view(self) -> BrokerView:
        """Broker truth: positions, and EVERY open order -- ours and foreign.

        Ownership is NOT decided here. The adapter reports raw identity and the
        cycle resolves it against durable state, because only durable state
        knows which broker ids are ours.
        """
        algorithm = self._algorithm
        positions = tuple(
            BrokerPositionView(symbol=str(h.symbol.value), quantity=int(h.quantity))
            for h in algorithm.portfolio.values()
            if h.invested
        )
        open_orders = tuple(
            self._order_view(order) for order in algorithm.transactions.get_open_orders()
        )
        return BrokerView(positions=positions, open_orders=open_orders)

    def _order_view(self, order) -> BrokerOrderView:
        """One LEAN order as raw identity plus attributes.

        `Order.Tag` is where our client order id lives, and LEAN does not send it
        to IBKR -- so an order LEAN re-hydrates after a restart comes back with a
        BLANK tag. `Order.BrokerId` is the value that survives, observed
        identical across a real IBKR Paper reconnect. `Order.Id` does NOT survive;
        it is reassigned, so it is reported only for addressing a cancellation
        within this process.
        """
        return BrokerOrderView(
            client_order_id="",  # resolved by the cycle, never by the adapter
            symbol=str(order.symbol.value),
            side="BUY" if order.quantity > 0 else "SELL",
            quantity=abs(int(order.quantity)),
            is_open=True,
            tag=str(order.tag or ""),
            broker_order_ids=tuple(str(b) for b in (order.broker_id or []) if str(b)),
            lean_order_id=str(order.id),
            order_type=str(order.type),
            stop_price=(
                str(order.stop_price) if getattr(order, "stop_price", None) is not None else None
            ),
        )

    def reference_price(self) -> decimal.Decimal:
        return decimal.Decimal(str(self._algorithm.securities[self._symbol].price))

    def broker_equity_usd(self) -> decimal.Decimal:
        """Observed for reconciliation only. It never sizes anything."""
        return decimal.Decimal(str(self._algorithm.portfolio.total_portfolio_value))

    # -- Exchange calendar --------------------------------------------------

    def regular_session_open(self) -> bool:
        """Regular session only -- `is_market_open` excludes extended hours."""
        return bool(self._algorithm.is_market_open(self._symbol))

    def exchange_local_time(self):
        return self._algorithm.time.time()

    def minutes_to_regular_close(self):
        """Minutes to today's ACTUAL regular close, from the exchange calendar.

        Derived, never assumed, so a 13:00 half day shortens the window by
        itself. Returns None if the calendar cannot answer, which the window
        treats as a refusal: an unknown close is not a distant one.
        """
        try:
            now = self._algorithm.time
            hours = self._algorithm.securities[self._symbol].exchange.hours
            close = hours.get_next_market_close(now, False)
            return (close - now).total_seconds() / 60.0
        except Exception as exc:
            self.error(f"[WINDOW] exchange calendar could not report today's close: {exc}")
            return None

    # -- Action -------------------------------------------------------------

    def submit(self, request) -> None:
        """Place the order. Only ever reached after its send fence is durable."""
        if request.stop_price is None:
            self._algorithm.market_order(
                self._symbol, request.signed_quantity, tag=request.client_order_id
            )
        else:
            self._algorithm.stop_market_order(
                self._symbol,
                request.signed_quantity,
                float(request.stop_price),
                tag=request.client_order_id,
            )

    def cancel(self, lean_order_id: str) -> None:
        """Cancel exactly the LEAN order the cycle resolved as ours.

        Addressed by LEAN order id. Never by tag -- gone after a restart -- and
        never by symbol or shape, which could be a stranger's order.
        """
        self._algorithm.transactions.cancel_order(int(lean_order_id))

    # -- Reporting ----------------------------------------------------------

    def log(self, message: str) -> None:
        self._algorithm.log(message)

    def error(self, message: str) -> None:
        self._algorithm.error(message)


class Phase2OrderLifecycle(QCAlgorithm):
    """Certifies the order lifecycle. One share of SPY, once, then flat."""

    # -- Setup -------------------------------------------------------------

    def initialize(self) -> None:
        # Pin the algorithm time zone so `self.time` is unambiguously the
        # exchange-local time the certification window is expressed in. LEAN
        # already defaults US equities to New York; stating it removes the
        # assumption rather than relying on it.
        self.set_time_zone(PHASE2_TIME_ZONE)

        if not self.live_mode:
            self.set_start_date(2024, 1, 2)
            self.set_end_date(2024, 1, 5)
            self.set_cash(int(DEFAULT_STRATEGY_CAPITAL_USD))

        self._symbol = self.add_equity(
            PHASE2_SYMBOL, Resolution.MINUTE, extended_market_hours=True
        ).symbol

        # The certification RUN is a deliberate human choice, never derived and
        # never auto-incremented after a failure. Each run gets a genuinely
        # different deterministic identity, so a failed run keeps its evidence
        # and the next attempt cannot inherit it.
        #
        # There is NO default. `or 1` used to sit here, which meant a deployment
        # with no run selected would quietly run as run 1 -- a completed
        # certification whose identity is audit evidence. A missing, empty or
        # malformed selector raises out of initialize() and LEAN refuses to
        # start, which is the correct failure for "we do not know what this
        # deployment is".
        run_number = require_run_number(self.get_parameter("phase2_run_number"))
        identity = certification_identity(run_number)
        coordinator = Phase2Coordinator(
            JsonTradeStateStore(STATE_PATH),
            identity,
            storage_root=STORAGE_ROOT,
            project_root=PROJECT_ROOT,
        )
        self._port = LeanBrokerPort(self, self._symbol)
        self._cycle = Phase2Cycle(
            coordinator,
            self._port,
            JsonHaltStore(halt_state_path(STORAGE_ROOT)),
            settings=Settings(environment=Environment.PAPER),
            test_mode=self._flag("phase2_test_mode"),
            arm_flag=self._flag("explicit_execution_arm"),
            confirmation=self.get_parameter("phase2_confirmation") or "",
            exit_requested=self._flag("phase2_exit_requested"),
            armed_fingerprint=self.get_parameter("phase2_account_fingerprint") or "",
            capital=StrategyCapital(),
            manual_resolution_requested=self._flag("phase2_manual_resolution"),
            resolution_confirmation=self.get_parameter("phase2_resolution_confirmation") or "",
        )

        self.log("=" * 78)
        self.log("KalpaMani Phase 2 -- CONTROLLED IBKR PAPER ORDER LIFECYCLE")
        self.log(f"[PHASE2-ARM] envelope: {describe_envelope()}")
        self.log(f"[PHASE2-ARM] certification_run={run_number}")
        self.log(f"[PHASE2-ARM] identity: {identity.describe()}")
        self.log(f"[PHASE2-ARM] execution_window={describe_window()}")
        self.log(f"[PHASE2-ARM] live_trading_hard_disabled={LIVE_TRADING_HARD_DISABLED}")
        self.log(f"[PHASE2-ARM] strategy_capital_usd={DEFAULT_STRATEGY_CAPITAL_USD}")
        self.log(f"[PHASE2-ARM] durable_state={STATE_PATH}")
        self.log("[PHASE2-ARM] Broker state is NOT read here; LEAN applies brokerage cash")
        self.log("[PHASE2-ARM] after initialize() returns. Work happens on the schedule.")
        self.log("=" * 78)

        # Surfaces a durable operational halt, which a restart does NOT clear.
        self._cycle.start()

        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.every(timedelta(minutes=RECONCILE_INTERVAL_MINUTES)),
            self._cycle.on_cycle,
        )

    def _flag(self, name: str) -> bool:
        raw = self.get_parameter(name)
        return str(raw).strip().lower() == "true" if raw is not None else False

    # -- Order events -------------------------------------------------------

    def on_order_event(self, order_event: OrderEvent) -> None:
        """Translate a LEAN OrderEvent and hand it to the cycle.

        Deliberately NOT gated on anything. Whether an event may act is the
        cycle's decision; whether it is *recorded* is not negotiable -- an order
        already at the broker keeps filling after a halt, and dropping the event
        would not stop that, only our knowledge of it.
        """
        order = self.transactions.get_order_by_id(order_event.order_id)
        self._cycle.on_order_event(
            OrderEventFacts(
                # The whole order, not just an id: after a restart the tag is
                # blank and the cycle must re-establish ownership from the
                # broker-native id.
                order=self._port._order_view(order),
                status=self._classify(order_event),
                fill_quantity=int(order_event.fill_quantity),
                fill_price=decimal.Decimal(str(order_event.fill_price)),
                # Stable event identity: LEAN's per-order OrderEvent.id, so
                # repeated delivery of the same event is a true no-op.
                fill_id=f"{order_event.order_id}-{order_event.id}",
            )
        )

    def _classify(self, order_event: OrderEvent) -> EventStatus:
        """Map LEAN's OrderStatus by EXACT enum identity.

        LEAN defines BOTH CANCEL_PENDING and CANCELED. Substring matching on the
        status name would treat a pending cancellation as a confirmed one, and
        let the close proceed while the stop was still live.
        """
        status = order_event.status
        if status == OrderStatus.CANCEL_PENDING:
            return EventStatus.CANCEL_PENDING
        if status == OrderStatus.CANCELED:
            return EventStatus.CANCELED
        if status == OrderStatus.INVALID:
            return EventStatus.INVALID
        if status == OrderStatus.SUBMITTED:
            return EventStatus.SUBMITTED
        if int(order_event.fill_quantity) != 0:
            return EventStatus.FILL
        return EventStatus.OTHER

    # -- Shutdown -----------------------------------------------------------

    def on_end_of_algorithm(self) -> None:
        open_orders = len(self.transactions.get_open_orders())
        spy_quantity = int(self.portfolio[self._symbol].quantity)
        halt = self._cycle.halt

        self.log("=" * 78)
        self.log("KalpaMani Phase 2 -- SHUTDOWN RECONCILIATION")
        self.log(
            f"  entry orders submitted this session : {self._cycle.entries_submitted_this_session}"
        )
        self.log(f"  operational halt                    : {halt.describe() if halt else 'none'}")
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
