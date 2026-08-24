"""Runtime environments for KalpaMani.

Three environments are distinguished from day one (Blueprint V2.1, section 16:
"Separate research, paper and live environments"):

RESEARCH
    No brokerage connection. No orders. Backtests and offline analysis only.
    This is the default, because it is the only environment that cannot touch
    a broker even in principle.

PAPER
    IBKR Paper only. Automated order submission may be introduced in a later
    explicitly approved phase; it is not available at bootstrap.

LIVE
    IBKR live brokerage. HARD-DISABLED. Selecting this environment does NOT
    authorize live execution -- see :mod:`kalpamani.common.settings`.
"""

from __future__ import annotations

from enum import StrEnum

from kalpamani.common.errors import ConfigurationError


class Environment(StrEnum):
    """The deployment environment KalpaMani is running in."""

    RESEARCH = "research"
    PAPER = "paper"
    LIVE = "live"

    @classmethod
    def parse(cls, raw: str) -> Environment:
        """Parse a case-insensitive environment name.

        Raises:
            ConfigurationError: if ``raw`` is not a known environment. We fail
                loudly rather than silently falling back, so that a typo can
                never be mistaken for a deliberate choice.
        """
        candidate = raw.strip().lower()
        for member in cls:
            if member.value == candidate:
                return member
        known = ", ".join(member.value for member in cls)
        raise ConfigurationError(
            f"Unknown KalpaMani environment {raw!r}. Expected one of: {known}."
        )

    @property
    def is_live(self) -> bool:
        """Whether this environment names the live brokerage.

        Note: this is only the FIRST of two independent gates. It never by
        itself authorizes live execution.
        """
        return self is Environment.LIVE

    @property
    def permits_broker_connection(self) -> bool:
        """Whether a brokerage connection is conceptually in scope.

        RESEARCH never connects to a broker. This says nothing about whether
        connectivity is implemented (at bootstrap, none is).
        """
        return self in (Environment.PAPER, Environment.LIVE)

    @property
    def permits_order_submission(self) -> bool:
        """Whether order submission is conceptually in scope for this environment.

        RESEARCH can never submit orders. PAPER and LIVE additionally require
        phase approval, and LIVE additionally requires the second authorization
        gate, so this is a necessary but never a sufficient condition.
        """
        return self in (Environment.PAPER, Environment.LIVE)


#: The safe default. Chosen because RESEARCH cannot reach a broker at all.
DEFAULT_ENVIRONMENT: Environment = Environment.RESEARCH

__all__ = ["DEFAULT_ENVIRONMENT", "Environment"]
