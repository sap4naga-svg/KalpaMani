"""Strategy capital and the risk-budget parameters derived from it.

CRITICAL DESIGN RULE
--------------------
KalpaMani strategy capital is a deliberate human allocation decision. It is
NOT the broker-reported account equity, and broker equity must never silently
become strategy capital.

    Broker account equity        (observed; informational only)
            |
            v
    KalpaMani allocated strategy capital   (authoritative; USD 80,000)
            |
            v
    Strategy risk budgets

The IBKR paper account may report a simulated USD 1,000,000 balance. Sizing
against that number instead of the allocated USD 80,000 would inflate every
position by 12.5x. :class:`StrategyCapital` is frozen and exposes no path by
which an observed broker equity can overwrite ``allocated_usd``.

The percentages below are configuration defaults and research parameters drawn
from Blueprint V2.1 section 10. They are NOT performance expectations, and this
module is NOT the risk engine -- it only holds the parameters the future
deterministic risk engine will consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal

from kalpamani.common.errors import CapitalIntegrityError

#: Capital allocated to KalpaMani strategies at bootstrap, in USD.
#: Deliberately distinct from any broker account balance.
DEFAULT_STRATEGY_CAPITAL_USD: Decimal = Decimal("80000")

_ONE_HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class RiskParameters:
    """Initial deterministic risk parameters (Blueprint V2.1, section 10).

    All values are percentages of ALLOCATED STRATEGY CAPITAL, never of broker
    equity.
    """

    #: Planned risk per long trade. 0.50% of USD 80,000 = USD 400.
    long_risk_per_trade_pct: Decimal = Decimal("0.50")
    #: Planned risk per short trade -- half the long risk. 0.25% = USD 200.
    short_risk_per_trade_pct: Decimal = Decimal("0.25")
    #: Maximum simultaneous open planned risk. ~5% = USD 4,000.
    max_open_planned_risk_pct: Decimal = Decimal("5.00")
    #: Maximum single position. Blueprint range is ~8-10%; 10% = USD 8,000 is
    #: the hard cap, 8% (USD 6,400) is the intended working target.
    max_position_pct: Decimal = Decimal("10.00")
    #: Target working ceiling for a single position, inside ``max_position_pct``.
    target_max_position_pct: Decimal = Decimal("8.00")
    #: Initial gross short exposure cap. <=25% = USD 20,000.
    max_gross_short_exposure_pct: Decimal = Decimal("25.00")
    #: Gross exposure ceiling. 100% means NO leverage, per Blueprint V2.1.
    max_gross_exposure_pct: Decimal = Decimal("100.00")

    def __post_init__(self) -> None:
        if self.max_gross_exposure_pct > _ONE_HUNDRED:
            raise CapitalIntegrityError(
                "Leverage is disabled for KalpaMani V1: max_gross_exposure_pct must not "
                f"exceed 100%, got {self.max_gross_exposure_pct}%."
            )
        if self.short_risk_per_trade_pct > self.long_risk_per_trade_pct:
            raise CapitalIntegrityError(
                "Short planned risk per trade must not exceed long planned risk per trade."
            )
        if self.target_max_position_pct > self.max_position_pct:
            raise CapitalIntegrityError("target_max_position_pct must not exceed max_position_pct.")

    @property
    def leverage_enabled(self) -> bool:
        """Whether any leverage is permitted. Always False for V1."""
        return self.max_gross_exposure_pct > _ONE_HUNDRED


@dataclass(frozen=True, slots=True)
class StrategyCapital:
    """The authoritative capital allocated to KalpaMani, plus derived budgets.

    ``allocated_usd`` is the single source of truth for every risk budget.
    ``observed_broker_equity_usd`` is recorded for reconciliation and alerting
    only and never participates in sizing.
    """

    allocated_usd: Decimal = DEFAULT_STRATEGY_CAPITAL_USD
    risk: RiskParameters = field(default_factory=RiskParameters)
    #: Last broker-reported equity, if any. Informational only. Never sizes a trade.
    observed_broker_equity_usd: Decimal | None = None

    def __post_init__(self) -> None:
        if self.allocated_usd <= 0:
            raise CapitalIntegrityError(
                f"Allocated strategy capital must be positive, got {self.allocated_usd}."
            )

    # -- Derived risk budgets, all denominated in allocated capital ---------

    def _pct_of_allocated(self, pct: Decimal) -> Decimal:
        return self.allocated_usd * pct / _ONE_HUNDRED

    @property
    def long_risk_per_trade_usd(self) -> Decimal:
        """Planned risk per long trade in USD. USD 400 at bootstrap."""
        return self._pct_of_allocated(self.risk.long_risk_per_trade_pct)

    @property
    def short_risk_per_trade_usd(self) -> Decimal:
        """Planned risk per short trade in USD. USD 200 at bootstrap."""
        return self._pct_of_allocated(self.risk.short_risk_per_trade_pct)

    @property
    def max_open_planned_risk_usd(self) -> Decimal:
        """Maximum simultaneous open planned risk in USD. USD 4,000 at bootstrap."""
        return self._pct_of_allocated(self.risk.max_open_planned_risk_pct)

    @property
    def max_position_usd(self) -> Decimal:
        """Hard cap on a single position in USD. USD 8,000 at bootstrap."""
        return self._pct_of_allocated(self.risk.max_position_pct)

    @property
    def target_max_position_usd(self) -> Decimal:
        """Working target ceiling for a single position. USD 6,400 at bootstrap."""
        return self._pct_of_allocated(self.risk.target_max_position_pct)

    @property
    def max_gross_short_exposure_usd(self) -> Decimal:
        """Cap on gross short exposure in USD. USD 20,000 at bootstrap."""
        return self._pct_of_allocated(self.risk.max_gross_short_exposure_pct)

    @property
    def max_gross_exposure_usd(self) -> Decimal:
        """Cap on gross exposure in USD. USD 80,000 at bootstrap (no leverage)."""
        return self._pct_of_allocated(self.risk.max_gross_exposure_pct)

    # -- Broker equity handling --------------------------------------------

    def observe_broker_equity(self, broker_equity_usd: Decimal) -> StrategyCapital:
        """Record broker-reported equity WITHOUT changing allocated capital.

        This is the only supported way to bring a broker balance into the
        system. It returns a new :class:`StrategyCapital` whose
        ``allocated_usd`` is the same value as before.

        Args:
            broker_equity_usd: Equity the brokerage reports, e.g. an IBKR paper
                NetLiquidation of USD 1,000,000.

        Returns:
            A new instance with the observation recorded and allocated capital
            unchanged.

        Raises:
            CapitalIntegrityError: if the broker cannot actually fund the
                allocation. Under-funding fails closed rather than silently
                shrinking risk budgets.
        """
        if broker_equity_usd < self.allocated_usd:
            raise CapitalIntegrityError(
                f"Broker equity {broker_equity_usd} USD is below allocated strategy capital "
                f"{self.allocated_usd} USD. Refusing to trade an under-funded allocation."
            )
        return replace(self, observed_broker_equity_usd=broker_equity_usd)

    @property
    def unallocated_broker_equity_usd(self) -> Decimal | None:
        """Broker equity that is deliberately NOT available to KalpaMani.

        Returns ``None`` until a broker equity has been observed.
        """
        if self.observed_broker_equity_usd is None:
            return None
        return self.observed_broker_equity_usd - self.allocated_usd


__all__ = [
    "DEFAULT_STRATEGY_CAPITAL_USD",
    "RiskParameters",
    "StrategyCapital",
]
