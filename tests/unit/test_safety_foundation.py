"""Safety tests for the KalpaMani configuration foundation.

These tests exist to make the non-negotiable safety rules executable rather
than aspirational. If any of them fail, the system is unsafe to run.

Covered:
    1. The default environment is not live.
    2. Live trading is disabled.
    3. Strategy capital is exactly USD 80,000.
    4. Simulated broker equity cannot overwrite strategy capital.
    5. Accidentally selecting LIVE cannot authorize live execution.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from kalpamani.common.capital import (
    DEFAULT_STRATEGY_CAPITAL_USD,
    RiskParameters,
    StrategyCapital,
)
from kalpamani.common.environment import DEFAULT_ENVIRONMENT, Environment
from kalpamani.common.errors import (
    CapitalIntegrityError,
    ConfigurationError,
    LiveTradingDisabledError,
    SafetyViolationError,
)
from kalpamani.common.settings import (
    ENV_VAR_ENVIRONMENT,
    ENV_VAR_STRATEGY_CAPITAL_USD,
    LIVE_TRADING_HARD_DISABLED,
    Settings,
    enable_live_trading,
    load_settings,
    require_live_execution_permitted,
)

#: The simulated balance an IBKR paper account is expected to report. It must
#: never become KalpaMani strategy capital.
IBKR_PAPER_SIMULATED_EQUITY_USD = Decimal("1000000")

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 1. Default mode is not live
# ---------------------------------------------------------------------------


def test_default_environment_is_research() -> None:
    assert DEFAULT_ENVIRONMENT is Environment.RESEARCH


def test_default_environment_is_not_live() -> None:
    assert not DEFAULT_ENVIRONMENT.is_live


def test_settings_default_environment_is_not_live() -> None:
    settings = Settings()
    assert settings.environment is Environment.RESEARCH
    assert not settings.environment.is_live


def test_load_settings_with_empty_environment_defaults_to_research() -> None:
    settings = load_settings(env={})
    assert settings.environment is Environment.RESEARCH
    assert not settings.environment.is_live


def test_research_environment_permits_no_broker_and_no_orders() -> None:
    assert not Environment.RESEARCH.permits_broker_connection
    assert not Environment.RESEARCH.permits_order_submission


def test_unknown_environment_name_fails_loudly_rather_than_defaulting() -> None:
    with pytest.raises(ConfigurationError):
        load_settings(env={ENV_VAR_ENVIRONMENT: "liv"})


# ---------------------------------------------------------------------------
# 2. Live trading is disabled
# ---------------------------------------------------------------------------


def test_live_trading_is_hard_disabled_at_module_level() -> None:
    assert LIVE_TRADING_HARD_DISABLED is True


def test_live_trading_disabled_in_default_settings() -> None:
    assert Settings().live_trading_enabled is False


def test_order_submission_is_never_permitted_at_bootstrap() -> None:
    for environment in Environment:
        settings = Settings(environment=environment)
        assert settings.order_submission_permitted is False


def test_enable_live_trading_fails_closed() -> None:
    with pytest.raises(LiveTradingDisabledError):
        enable_live_trading(reason="test attempts to enable live trading")


def test_enable_live_trading_error_is_a_safety_violation() -> None:
    with pytest.raises(SafetyViolationError):
        enable_live_trading(reason="safety hierarchy check")


def test_require_live_execution_permitted_raises_in_every_environment() -> None:
    for environment in Environment:
        with pytest.raises(LiveTradingDisabledError):
            require_live_execution_permitted(Settings(environment=environment))


# ---------------------------------------------------------------------------
# 3. Strategy capital is exactly USD 80,000
# ---------------------------------------------------------------------------


def test_default_strategy_capital_is_exactly_80000_usd() -> None:
    assert DEFAULT_STRATEGY_CAPITAL_USD == Decimal("80000")
    assert DEFAULT_STRATEGY_CAPITAL_USD == 80000


def test_settings_strategy_capital_is_exactly_80000_usd() -> None:
    assert Settings().strategy_capital_usd == Decimal("80000")


def test_loaded_settings_strategy_capital_is_exactly_80000_usd() -> None:
    assert load_settings(env={}).strategy_capital_usd == Decimal("80000")


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [
        ("long_risk_per_trade_usd", Decimal("400")),
        ("short_risk_per_trade_usd", Decimal("200")),
        ("max_open_planned_risk_usd", Decimal("4000")),
        ("max_position_usd", Decimal("8000")),
        ("target_max_position_usd", Decimal("6400")),
        ("max_gross_short_exposure_usd", Decimal("20000")),
        ("max_gross_exposure_usd", Decimal("80000")),
    ],
)
def test_risk_budgets_derive_from_80000_usd(attribute: str, expected: Decimal) -> None:
    """Blueprint V2.1 section 10 budgets, denominated in allocated capital."""
    capital = StrategyCapital()
    assert getattr(capital, attribute) == expected


def test_no_leverage_by_default() -> None:
    assert RiskParameters().leverage_enabled is False
    assert StrategyCapital().max_gross_exposure_usd == StrategyCapital().allocated_usd


def test_leverage_cannot_be_configured_for_v1() -> None:
    with pytest.raises(CapitalIntegrityError):
        RiskParameters(max_gross_exposure_pct=Decimal("150"))


def test_non_positive_strategy_capital_is_rejected() -> None:
    with pytest.raises(CapitalIntegrityError):
        StrategyCapital(allocated_usd=Decimal("0"))


def test_malformed_capital_env_var_fails_loudly() -> None:
    with pytest.raises(ConfigurationError):
        load_settings(env={ENV_VAR_STRATEGY_CAPITAL_USD: "eighty thousand"})


# ---------------------------------------------------------------------------
# 4. Simulated broker equity cannot overwrite strategy capital
# ---------------------------------------------------------------------------


def test_observing_ibkr_paper_equity_does_not_change_strategy_capital() -> None:
    capital = StrategyCapital()
    reconciled = capital.observe_broker_equity(IBKR_PAPER_SIMULATED_EQUITY_USD)

    assert reconciled.allocated_usd == Decimal("80000")
    assert reconciled.observed_broker_equity_usd == IBKR_PAPER_SIMULATED_EQUITY_USD
    # The original object is untouched as well.
    assert capital.allocated_usd == Decimal("80000")


def test_risk_budgets_ignore_simulated_broker_equity() -> None:
    """The 1,000,000 paper balance must not inflate sizing by 12.5x."""
    reconciled = StrategyCapital().observe_broker_equity(IBKR_PAPER_SIMULATED_EQUITY_USD)

    assert reconciled.long_risk_per_trade_usd == Decimal("400")
    assert reconciled.short_risk_per_trade_usd == Decimal("200")
    assert reconciled.max_position_usd == Decimal("8000")
    assert reconciled.max_gross_exposure_usd == Decimal("80000")


def test_unallocated_broker_equity_is_reported_but_unusable() -> None:
    reconciled = StrategyCapital().observe_broker_equity(IBKR_PAPER_SIMULATED_EQUITY_USD)
    assert reconciled.unallocated_broker_equity_usd == Decimal("920000")


def test_strategy_capital_is_immutable() -> None:
    capital = StrategyCapital()
    with pytest.raises(dataclasses.FrozenInstanceError):
        capital.allocated_usd = IBKR_PAPER_SIMULATED_EQUITY_USD  # type: ignore[misc]


def test_settings_are_immutable() -> None:
    settings = Settings()
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.environment = Environment.LIVE  # type: ignore[misc]


def test_underfunded_broker_account_fails_closed() -> None:
    """A broker that cannot fund the allocation must not silently shrink budgets."""
    with pytest.raises(CapitalIntegrityError):
        StrategyCapital().observe_broker_equity(Decimal("50000"))


def test_broker_equity_is_absent_until_explicitly_observed() -> None:
    capital = StrategyCapital()
    assert capital.observed_broker_equity_usd is None
    assert capital.unallocated_broker_equity_usd is None


# ---------------------------------------------------------------------------
# 5. Accidentally selecting LIVE cannot authorize live execution
# ---------------------------------------------------------------------------


def test_selecting_live_environment_does_not_enable_live_trading() -> None:
    settings = Settings(environment=Environment.LIVE)
    assert settings.environment is Environment.LIVE
    assert settings.live_trading_enabled is False


def test_live_env_var_does_not_enable_live_trading() -> None:
    settings = load_settings(env={ENV_VAR_ENVIRONMENT: "live"})
    assert settings.environment is Environment.LIVE
    assert settings.live_trading_enabled is False
    assert settings.order_submission_permitted is False


def test_live_environment_does_not_permit_broker_connection() -> None:
    settings = Settings(environment=Environment.LIVE)
    assert settings.broker_connection_permitted is False


def test_live_environment_execution_check_still_fails_closed() -> None:
    settings = load_settings(env={ENV_VAR_ENVIRONMENT: "LIVE"})
    with pytest.raises(LiveTradingDisabledError):
        require_live_execution_permitted(settings)


def test_no_combination_of_settings_enables_live_trading() -> None:
    """Exhaustive sweep: no reachable configuration turns live trading on."""
    for environment in Environment:
        for capital_usd in (Decimal("80000"), IBKR_PAPER_SIMULATED_EQUITY_USD):
            settings = Settings(
                environment=environment,
                capital=StrategyCapital(allocated_usd=capital_usd),
            )
            assert settings.live_trading_enabled is False


# ---------------------------------------------------------------------------
# Safety posture reporting must never leak secrets
# ---------------------------------------------------------------------------


def test_safety_posture_is_reported_honestly() -> None:
    posture = Settings().describe_safety_posture()
    assert "environment=research" in posture
    assert "strategy_capital_usd=80000" in posture
    assert "live_trading_enabled=False" in posture


def test_safety_posture_reports_live_selection_without_authorizing_it() -> None:
    posture = Settings(environment=Environment.LIVE).describe_safety_posture()
    assert "environment=live" in posture
    assert "live_trading_enabled=False" in posture
