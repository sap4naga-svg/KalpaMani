"""Read-only brokerage account boundary (ADR-0002).

This is the *entire* brokerage surface KalpaMani exposes during Phase 1, and it
is deliberately incapable of expressing an order. There is no submit, cancel,
modify or liquidate method here, and adding one is an ADR-level change rather
than an ordinary code change.

The boundary exists to keep two things apart:

    the broker owns *what is*        -- positions, cash, open orders, fills
    KalpaMani config owns *what is allowed* -- strategy capital, risk budgets

Neither may overwrite the other. In particular, a broker-reported equity of
USD 1,000,000 on the IBKR Paper account must never become the USD 80,000 of
allocated strategy capital.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from kalpamani.common.capital import StrategyCapital
from kalpamani.common.errors import BrokerModeError

#: IBKR paper account identifier prefixes. Checked before the live prefixes,
#: because a paper identifier such as "DU1234567" also ends in a live-looking
#: "U1234567" if matched carelessly.
_PAPER_PREFIXES = ("DU", "DF", "DI")

#: IBKR live account identifier prefixes.
_LIVE_PREFIXES = ("U", "F", "I")


class BrokerAccountMode(StrEnum):
    """Whether a connected brokerage account is simulated or real money."""

    PAPER = "paper"
    LIVE = "live"
    #: The identifier did not match a known pattern. Treated as a hard failure,
    #: never as an implicit "probably paper".
    UNKNOWN = "unknown"

    @classmethod
    def classify(cls, account_id: str) -> BrokerAccountMode:
        """Classify an IBKR account identifier without trusting it blindly.

        Returns :attr:`UNKNOWN` for anything unrecognised, so that callers are
        forced to fail closed rather than guess.
        """
        candidate = account_id.strip().upper()
        if not candidate:
            return cls.UNKNOWN
        if candidate.startswith(_PAPER_PREFIXES):
            return cls.PAPER
        if candidate.startswith(_LIVE_PREFIXES):
            return cls.LIVE
        return cls.UNKNOWN

    @property
    def is_paper(self) -> bool:
        return self is BrokerAccountMode.PAPER


def redact_account_id(account_id: str) -> str:
    """Mask an account identifier for logs, keeping only its mode-bearing prefix.

    ``"DU1234567"`` becomes ``"DU*******"``. Enough to prove the account is a
    paper account; not enough to identify it. Account identifiers are treated as
    operational metadata that we prefer never to write down.
    """
    candidate = account_id.strip().upper()
    if not candidate:
        return "<empty>"
    prefix_len = 2 if candidate.startswith(_PAPER_PREFIXES) else 1
    return candidate[:prefix_len] + "*" * max(len(candidate) - prefix_len, 0)


@dataclass(frozen=True, slots=True)
class BrokerAccountSnapshot:
    """An immutable, read-only observation of brokerage account state.

    Every field here is broker-authoritative *reality*. None of it is ever an
    input to position sizing.
    """

    account_id: str
    mode: BrokerAccountMode
    equity_usd: Decimal
    cash_usd: Decimal
    holdings_count: int
    open_orders_count: int

    @property
    def redacted_account_id(self) -> str:
        """Log-safe form of the account identifier."""
        return redact_account_id(self.account_id)

    @property
    def is_flat(self) -> bool:
        """Whether the account holds no positions and no open orders."""
        return self.holdings_count == 0 and self.open_orders_count == 0

    def describe(self) -> str:
        """Render a log-safe summary. Never includes the full account id."""
        return (
            f"broker account={self.redacted_account_id} mode={self.mode.value} "
            f"equity_usd={self.equity_usd} cash_usd={self.cash_usd} "
            f"holdings={self.holdings_count} open_orders={self.open_orders_count}"
        )


def require_paper_account(snapshot: BrokerAccountSnapshot) -> None:
    """Assert the connected account is a paper account, or fail closed.

    Called before any brokerage interaction proceeds. Both a live account and an
    unclassifiable one raise: ambiguity about paper-vs-live is an abort
    condition, not a warning.

    Raises:
        BrokerModeError: if the account is live or its mode is unknown.
    """
    if snapshot.mode is BrokerAccountMode.PAPER:
        return
    raise BrokerModeError(
        f"Refusing to proceed: connected account {snapshot.redacted_account_id} has mode "
        f"{snapshot.mode.value!r}, but only {BrokerAccountMode.PAPER.value!r} is permitted. "
        "Live trading is hard-disabled and an unrecognised account identifier is treated "
        "as a failure, never as an assumed paper account."
    )


def reconcile_capital(
    snapshot: BrokerAccountSnapshot,
    capital: StrategyCapital,
) -> StrategyCapital:
    """Record broker equity against allocated capital, leaving the allocation intact.

    This is the single supported route by which a brokerage balance enters
    KalpaMani. It returns a new :class:`~kalpamani.common.capital.StrategyCapital`
    whose ``allocated_usd`` is unchanged -- observing USD 1,000,000 of simulated
    paper equity still leaves USD 80,000 of strategy capital.

    Raises:
        BrokerModeError: if the account is not a paper account.
        CapitalIntegrityError: if the broker cannot fund the allocation.
    """
    require_paper_account(snapshot)
    return capital.observe_broker_equity(snapshot.equity_usd)


@runtime_checkable
class ReadOnlyBrokerAccount(Protocol):
    """The read-only brokerage capability available in Phase 1.

    Intentionally minimal. It can observe account state and nothing else: there
    is no method here that submits, modifies, cancels or liquidates anything,
    and none may be added without a new ADR.
    """

    def account_snapshot(self) -> BrokerAccountSnapshot:
        """Return the current broker-authoritative account state."""
        ...


__all__ = [
    "BrokerAccountMode",
    "BrokerAccountSnapshot",
    "ReadOnlyBrokerAccount",
    "reconcile_capital",
    "redact_account_id",
    "require_paper_account",
]
