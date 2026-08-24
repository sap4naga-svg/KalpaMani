"""KalpaMani runtime settings and the live-trading authorization gates.

TWO INDEPENDENT GATES
---------------------
Live brokerage execution is deliberately NOT reachable by setting a single
value. Enabling it requires both of the following to be true:

    Gate 1 -- environment selection:   ``Environment.LIVE`` is selected.
    Gate 2 -- independent authorization: a separate, out-of-band authorization
              mechanism approves live execution.

Gate 2 is intentionally NOT IMPLEMENTED during bootstrap, and
:data:`LIVE_TRADING_HARD_DISABLED` short-circuits the whole question. Any code
that tries to enable or perform live execution fails closed with
:class:`~kalpamani.common.errors.LiveTradingDisabledError`.

This is why ``KALPAMANI_ENV=live`` is not a foot-gun: it is accepted as a
declaration of intent, it is reported honestly, and it still authorizes
nothing.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Final, NoReturn

from kalpamani.common.capital import DEFAULT_STRATEGY_CAPITAL_USD, StrategyCapital
from kalpamani.common.environment import DEFAULT_ENVIRONMENT, Environment
from kalpamani.common.errors import ConfigurationError, LiveTradingDisabledError

#: Master compile-time kill switch for live brokerage execution.
#:
#: This stays ``True`` until an explicitly approved future deployment phase.
#: Flipping it is a governed change: it requires an approved ADR, a working
#: Gate-2 authorization mechanism, and written human sign-off. It is annotated
#: as ``Final[bool]`` rather than ``Final`` so that the surrounding safety
#: checks remain type-checked live code rather than being narrowed away.
LIVE_TRADING_HARD_DISABLED: Final[bool] = True

#: Environment variable names. Kept in one place so the docs, ``.env.example``
#: and the loader cannot drift apart.
ENV_VAR_ENVIRONMENT: Final = "KALPAMANI_ENV"
ENV_VAR_STRATEGY_CAPITAL_USD: Final = "KALPAMANI_STRATEGY_CAPITAL_USD"
ENV_VAR_DEPLOYMENT_NAME: Final = "KALPAMANI_DEPLOYMENT_NAME"

_DEFAULT_DEPLOYMENT_NAME: Final = "local-dev"


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable runtime configuration for a KalpaMani process."""

    environment: Environment = DEFAULT_ENVIRONMENT
    capital: StrategyCapital = field(default_factory=StrategyCapital)
    deployment_name: str = _DEFAULT_DEPLOYMENT_NAME

    # -- Safety posture ----------------------------------------------------

    @property
    def live_trading_enabled(self) -> bool:
        """Whether live brokerage execution is permitted. Always ``False`` now.

        Both gates must pass. Gate 2 does not exist yet and
        :data:`LIVE_TRADING_HARD_DISABLED` is set, so this is ``False`` for
        every possible configuration, including ``KALPAMANI_ENV=live``.
        """
        if LIVE_TRADING_HARD_DISABLED:
            return False
        # Gate 1 alone is never sufficient. When Gate 2 is implemented under an
        # approved ADR, it is evaluated here -- and it must be an independent
        # authorization source, not another environment variable.
        return self.environment.is_live and _live_execution_authorized()

    @property
    def broker_connection_permitted(self) -> bool:
        """Whether connecting to a brokerage is permitted in this configuration.

        At bootstrap no brokerage connectivity is implemented at all, so this
        only describes intent. Live connections stay refused regardless.
        """
        if self.environment.is_live:
            return self.live_trading_enabled
        return self.environment.permits_broker_connection

    @property
    def order_submission_permitted(self) -> bool:
        """Whether order submission is permitted. Always ``False`` at bootstrap.

        Automated paper orders require a separately approved phase, and live
        orders additionally require both gates.
        """
        return False

    @property
    def strategy_capital_usd(self) -> Decimal:
        """Authoritative allocated strategy capital in USD.

        Never sourced from the broker. See :mod:`kalpamani.common.capital`.
        """
        return self.capital.allocated_usd

    def describe_safety_posture(self) -> str:
        """Render a short, secret-free summary suitable for logs and startup banners."""
        return (
            f"KalpaMani [{self.deployment_name}] "
            f"environment={self.environment.value} "
            f"strategy_capital_usd={self.strategy_capital_usd} "
            f"live_trading_enabled={self.live_trading_enabled} "
            f"order_submission_permitted={self.order_submission_permitted}"
        )


def _live_execution_authorized() -> bool:
    """Gate 2 -- the independent live-execution authorization check.

    Deliberately unimplemented. It returns ``False`` so that even if
    :data:`LIVE_TRADING_HARD_DISABLED` were cleared by mistake, live execution
    would still be refused.
    """
    return False


def require_live_execution_permitted(settings: Settings) -> None:
    """Assert that live execution is permitted, or fail closed.

    Every future code path that would place a live brokerage order must call
    this first.

    Raises:
        LiveTradingDisabledError: always, during bootstrap.
    """
    if not settings.live_trading_enabled:
        raise LiveTradingDisabledError(
            "Live trading is hard-disabled. "
            f"environment={settings.environment.value}, "
            f"hard_disabled={LIVE_TRADING_HARD_DISABLED}. "
            "Selecting Environment.LIVE does not authorize live execution: a second, "
            "independent authorization gate is required and is not implemented. "
            "Enabling live trading is a governed change requiring an approved ADR and "
            "written human sign-off."
        )


def enable_live_trading(*, reason: str) -> NoReturn:
    """Refuse, loudly, any programmatic attempt to enable live trading.

    There is deliberately no supported in-process way to turn live trading on.
    This function exists so that the attempt fails with an explanatory error
    instead of a subtle mis-configuration.

    Args:
        reason: Why the caller wanted live trading. Recorded in the error to
            make the audit trail obvious.

    Raises:
        LiveTradingDisabledError: always.
    """
    raise LiveTradingDisabledError(
        f"Refusing to enable live trading (requested reason: {reason!r}). "
        "Live trading cannot be enabled programmatically. It requires an approved "
        "deployment phase, an approved ADR, a working independent authorization gate, "
        "and written human sign-off."
    )


def _parse_capital(raw: str) -> Decimal:
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, ValueError) as exc:
        raise ConfigurationError(
            f"{ENV_VAR_STRATEGY_CAPITAL_USD}={raw!r} is not a valid decimal amount."
        ) from exc
    if value <= 0:
        raise ConfigurationError(f"{ENV_VAR_STRATEGY_CAPITAL_USD} must be positive, got {value}.")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build :class:`Settings` from environment variables, defaulting safely.

    Strategy capital is read from configuration only. There is deliberately no
    code path here that consults a brokerage.

    Args:
        env: Mapping to read from. Defaults to :data:`os.environ`. Injectable so
            tests never mutate real process state.

    Raises:
        ConfigurationError: if a supplied value is malformed. We never silently
            fall back to a default when the operator has stated an intent.
    """
    source: Mapping[str, str] = os.environ if env is None else env

    raw_environment = source.get(ENV_VAR_ENVIRONMENT)
    environment = (
        DEFAULT_ENVIRONMENT if raw_environment is None else Environment.parse(raw_environment)
    )

    raw_capital = source.get(ENV_VAR_STRATEGY_CAPITAL_USD)
    allocated = DEFAULT_STRATEGY_CAPITAL_USD if raw_capital is None else _parse_capital(raw_capital)

    deployment_name = source.get(ENV_VAR_DEPLOYMENT_NAME, _DEFAULT_DEPLOYMENT_NAME)

    return Settings(
        environment=environment,
        capital=StrategyCapital(allocated_usd=allocated),
        deployment_name=deployment_name,
    )


__all__ = [
    "ENV_VAR_DEPLOYMENT_NAME",
    "ENV_VAR_ENVIRONMENT",
    "ENV_VAR_STRATEGY_CAPITAL_USD",
    "LIVE_TRADING_HARD_DISABLED",
    "Settings",
    "enable_live_trading",
    "load_settings",
    "require_live_execution_permitted",
]
