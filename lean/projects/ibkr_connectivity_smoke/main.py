# region imports
from AlgorithmImports import *

# endregion

# ---------------------------------------------------------------------------
# KalpaMani -- Phase 1 IBKR Paper connectivity smoke test
#
# PURPOSE: prove the pipe works. KalpaMani -> LEAN -> IBKR Paper -> market data
# -> account state -> clean shutdown.
#
# THIS ALGORITHM SUBMITS NO ORDERS. There is deliberately no order-submission
# API anywhere in this file -- no market_order, limit_order, stop_market_order,
# stop_limit_order, set_holdings, liquidate, buy or sell. A static test in
# tests/unit/test_phase1_broker_safety.py fails the build if one appears.
#
# It is a connectivity proof, not a strategy. Nothing here generates alpha, and
# delayed market data is acceptable for this purpose. No performance claim may
# ever be based on this project.
# ---------------------------------------------------------------------------

#: KalpaMani allocated strategy capital, in USD.
#:
#: This is a CONFIGURED HUMAN ALLOCATION. It is deliberately NOT read from the
#: brokerage. The IBKR Paper account reports roughly USD 1,000,000 of simulated
#: equity; sizing against that instead of this number would inflate every
#: position by 12.5x.
#:
#: This constant is duplicated from kalpamani.common.capital because the LEAN
#: Docker container does not have the kalpamani package installed. A unit test
#: asserts the two values can never drift apart.
KALPAMANI_STRATEGY_CAPITAL_USD = 80000

#: Exactly one highly liquid U.S. equity ETF. One symbol, by design.
SMOKE_TEST_TICKER = "SPY"

#: How many data events between periodic account observations.
ACCOUNT_OBSERVATION_INTERVAL = 60

#: Minutes between scheduled account observations. Scheduled rather than
#: data-driven so broker state is still proven when the market is closed.
OBSERVATION_INTERVAL_MINUTES = 1


class IbkrConnectivitySmoke(QCAlgorithm):
    """Read-only IBKR Paper connectivity proof. Submits nothing, holds nothing."""

    def initialize(self) -> None:
        # In live mode LEAN ignores dates and uses real brokerage cash. These
        # are set only so the project also loads in backtest mode, where no
        # broker exists at all. Nothing derives sizing from either value --
        # this algorithm does not size anything.
        if not self.live_mode:
            self.set_start_date(2024, 1, 2)
            self.set_end_date(2024, 1, 5)
            self.set_cash(KALPAMANI_STRATEGY_CAPITAL_USD)

        # Exactly one subscription.
        # extended_market_hours=True so a connectivity run started outside regular
        # trading hours can still receive data. Purely a data-subscription setting;
        # it grants no order capability and changes no leverage.
        self._symbol = self.add_equity(
            SMOKE_TEST_TICKER, Resolution.MINUTE, extended_market_hours=True
        ).symbol

        self._data_event_count = 0
        self._first_data_event_logged = False
        self._order_events_seen = 0
        self._observation_count = 0
        self._capital_separation_logged = False

        self.log("=" * 78)
        self.log("KalpaMani Phase 1 -- IBKR PAPER CONNECTIVITY SMOKE TEST")
        self.log("MODE: READ-ONLY. This algorithm submits NO orders and creates NO positions.")
        self.log(f"live_mode={self.live_mode}")
        self.log(f"Subscribed symbol: {self._symbol.value} (resolution=Minute)")
        self.log(f"KalpaMani allocated strategy capital: USD {KALPAMANI_STRATEGY_CAPITAL_USD:,}")
        self.log("=" * 78)

        # Deliberately NOT observing broker state here.
        #
        # Verified 2026-08-24: LEAN calls initialize() BEFORE it applies brokerage
        # cash. Engine log ordering was:
        #     00:13:48.876  BrokerageSetupHandler.Setup(): Initializing algorithm...
        #     00:13:49.037  BrokerageSetupHandler.Setup(): Setting USD cash to 1000000.00
        # Reading self.portfolio here returns LEAN's default placeholder (100,000),
        # not the broker balance, and reporting that as "broker state" would be a
        # fabricated number presented as fact. Observation happens on a schedule
        # instead, once setup has completed.
        self.log(
            "[BROKER-STATE:initialize] NOT READ -- brokerage cash is applied after "
            "initialize() returns. Broker state is observed on a schedule instead."
        )

        # Observe on a timer rather than from on_data, so account state is proven
        # even when the market is closed and no bars arrive.
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.every(timedelta(minutes=OBSERVATION_INTERVAL_MINUTES)),
            self._scheduled_observation,
        )

    # -- Market data --------------------------------------------------------

    def on_data(self, data: Slice) -> None:
        """Receive market data. Observes only; never acts."""
        self._data_event_count += 1

        bar = data.bars.get(self._symbol) if data.bars is not None else None

        if not self._first_data_event_logged and bar is not None:
            self._first_data_event_logged = True
            self.log("-" * 78)
            self.log("[MARKET-DATA] FIRST EVENT RECEIVED -- data pipeline is live.")
            self.log(f"[MARKET-DATA]   symbol      : {self._symbol.value}")
            self.log(f"[MARKET-DATA]   bar time    : {bar.end_time}")
            self.log(f"[MARKET-DATA]   algo utc    : {self.utc_time}")
            self.log(f"[MARKET-DATA]   close       : {bar.close}")
            self.log(f"[MARKET-DATA]   volume      : {bar.volume}")
            self.log("-" * 78)
            self._observe_broker_account("first-market-data-event")
            if not self._capital_separation_logged:
                self._capital_separation_logged = True
                self._log_capital_separation()

        if self._data_event_count % ACCOUNT_OBSERVATION_INTERVAL == 0:
            self._observe_broker_account(f"data-event-{self._data_event_count}")

    # -- Brokerage observation ---------------------------------------------

    def _scheduled_observation(self) -> None:
        """Observe broker state on the algorithm clock, independent of market data.

        This is what proves the account is readable during a connectivity test
        run outside market hours, when no bar will ever arrive.
        """
        self._observation_count += 1
        self._observe_broker_account(f"scheduled-{self._observation_count}")
        if not self._capital_separation_logged:
            self._capital_separation_logged = True
            self._log_capital_separation()

    def _observe_broker_account(self, context: str) -> None:
        """Log broker-authoritative account state. READ ONLY.

        Every value read here is observation for reconciliation and alerting.
        None of it is ever an input to position sizing -- this algorithm sizes
        nothing, and no future code may size from these fields either.
        """
        broker_equity_observed_usd = self.portfolio.total_portfolio_value
        broker_cash_observed_usd = self.portfolio.cash
        holdings_count = sum(1 for h in self.portfolio.values() if h.invested)
        open_orders_count = len(self.transactions.get_open_orders())

        self.log(
            f"[BROKER-STATE:{context}] "
            f"equity_usd={broker_equity_observed_usd} "
            f"cash_usd={broker_cash_observed_usd} "
            f"holdings={holdings_count} "
            f"open_orders={open_orders_count}"
        )

        if holdings_count != 0:
            self.error(
                f"[SAFETY] Expected zero holdings during a read-only connectivity test, "
                f"found {holdings_count}. KalpaMani did not create them; investigate the "
                f"account before proceeding."
            )
        if open_orders_count != 0:
            self.error(
                f"[SAFETY] Expected zero open orders during a read-only connectivity test, "
                f"found {open_orders_count}. KalpaMani submitted none; investigate."
            )

    def _log_capital_separation(self) -> None:
        """Demonstrate that broker equity and strategy capital are distinct.

        This is the single most important assertion in Phase 1.
        """
        broker_equity_observed_usd = self.portfolio.total_portfolio_value
        strategy_capital_usd = KALPAMANI_STRATEGY_CAPITAL_USD
        difference = broker_equity_observed_usd - strategy_capital_usd

        self.log("=" * 78)
        self.log("[CAPITAL-SEPARATION] Broker equity is NOT KalpaMani strategy capital.")
        self.log(
            f"[CAPITAL-SEPARATION]   broker reported equity : USD {broker_equity_observed_usd}"
        )
        self.log(f"[CAPITAL-SEPARATION]   KalpaMani allocation   : USD {strategy_capital_usd}")
        self.log(f"[CAPITAL-SEPARATION]   unallocated difference : USD {difference}")

        if broker_equity_observed_usd == strategy_capital_usd:
            self.log(
                "[CAPITAL-SEPARATION]   NOTE: the two happen to be equal in this run. "
                "They remain independent concepts regardless."
            )
        else:
            ratio = float(broker_equity_observed_usd) / float(strategy_capital_usd)
            self.log(
                f"[CAPITAL-SEPARATION]   CONFIRMED DISTINCT: broker equity is {ratio:.2f}x the "
                f"KalpaMani allocation. Sizing against broker equity would have inflated every "
                f"position by that factor."
            )
        self.log(
            "[CAPITAL-SEPARATION]   KalpaMani strategy capital remains USD "
            f"{strategy_capital_usd:,} and is unaffected by the brokerage balance."
        )
        self.log("=" * 78)

    # -- Connectivity state -------------------------------------------------

    def on_brokerage_message(self, message: BrokerageMessageEvent) -> None:
        self.log(f"[BROKERAGE-MESSAGE] type={message.type} code={message.code} {message.message}")

    def on_brokerage_disconnect(self) -> None:
        self.error("[BROKERAGE] DISCONNECTED from IBKR Paper.")

    def on_brokerage_reconnect(self) -> None:
        self.log("[BROKERAGE] RECONNECTED to IBKR Paper.")

    def on_order_event(self, order_event: OrderEvent) -> None:
        """Safety net. KalpaMani submits nothing, so this must never fire."""
        self._order_events_seen += 1
        self.error(
            "[SAFETY-VIOLATION] An order event was received during a read-only "
            f"connectivity test: {order_event}. KalpaMani has no order-submission path in "
            "Phase 1. Investigate immediately."
        )

    # -- Shutdown / reconciliation -----------------------------------------

    def on_end_of_algorithm(self) -> None:
        """Final reconciliation. Reports, never liquidates."""
        holdings_count = sum(1 for h in self.portfolio.values() if h.invested)
        open_orders_count = len(self.transactions.get_open_orders())
        total_orders = self.transactions.orders_count

        self.log("=" * 78)
        self.log("KalpaMani Phase 1 -- SHUTDOWN RECONCILIATION")
        self.log(f"  market-data events received : {self._data_event_count}")
        self.log(f"  first data event observed   : {self._first_data_event_logged}")
        self.log(f"  orders submitted by KalpaMani: {total_orders}  (MUST be 0)")
        self.log(f"  order events seen           : {self._order_events_seen}  (MUST be 0)")
        self.log(f"  holdings at shutdown        : {holdings_count}  (MUST be 0)")
        self.log(f"  open orders at shutdown     : {open_orders_count}  (MUST be 0)")
        self.log(f"  broker equity observed      : USD {self.portfolio.total_portfolio_value}")
        self.log(f"  KalpaMani strategy capital  : USD {KALPAMANI_STRATEGY_CAPITAL_USD:,}")

        if total_orders == 0 and holdings_count == 0 and open_orders_count == 0:
            self.log("  RESULT: CLEAN. KalpaMani created no orders and no positions.")
        else:
            self.error("  RESULT: NOT CLEAN. Investigate before any further phase.")
        self.log("=" * 78)
