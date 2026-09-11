"""Deterministic factor computations over point-in-time bars.

Pure functions on ``Decimal``. No float ever enters: a float in a hashed
record makes identity a property of a binary representation, and the kernel's
canonical serialiser refuses one. Every result is quantised to a fixed number
of places so that the same bars produce the same digits on any machine.

**These are computations, not factor selections.** The accepted specification
names factor *families* and their contracts (section 5) and deliberately no
formula. Which of these computations, at which lookback, is *the* production
factor for a family is a research decision recorded in a strategy version --
and the strategy version that uses them today is a research-stage one. Nothing
here claims a factor predicts anything.

Conventions. A series is ordered oldest to newest and its last bar is the
**evaluation bar** -- the session whose close the decision rests on. "Prior"
windows exclude the evaluation bar, so a base high is the resistance the
evaluation close is compared against rather than a level that already contains
it. Every function refuses a series too short for its window rather than
computing over what happens to be there.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from itertools import pairwise
from typing import Final

from kalpamani.data.contracts.entities import PriceBarValues
from kalpamani.strategies.brain.errors import BrainContractError
from kalpamani.strategies.brain.identity import (
    require_finite_decimal,
    require_identifier,
    require_positive_int,
)
from kalpamani.strategies.brain.vocabulary import FactorFamily, closed_member

#: Ten decimal places. Enough for a ratio of two prices to be exact to a tick
#: in every realistic case, and fixed so that hashes are stable.
FACTOR_QUANTUM: Final = Decimal("0.0000000001")

_ONE: Final = Decimal(1)


def quantized(value: Decimal) -> Decimal:
    """``value`` at :data:`FACTOR_QUANTUM`, banker's rounding."""
    return value.quantize(FACTOR_QUANTUM, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True, kw_only=True)
class FactorDefinition:
    """The identity of one factor computation at one version (section 5.3).

    ``lookback_sessions`` is the number of bars, **including** the evaluation
    bar, the computation needs. A factor whose definition version is not pinned
    may not inform a candidate, so ``version`` is validated as an identifier.
    """

    factor_id: str
    version: str
    family: FactorFamily
    lookback_sessions: int

    def __post_init__(self) -> None:
        require_identifier(self.factor_id, field="factor_id")
        require_identifier(self.version, field="version")
        family = closed_member(FactorFamily, self.family)
        if family is None:
            raise BrainContractError("Field 'family' must be a FactorFamily member.")
        object.__setattr__(self, "family", family)
        require_positive_int(self.lookback_sessions, field="lookback_sessions")

    @property
    def reference(self) -> str:
        """``factor_id@version`` -- how the factor is cited in a record."""
        return f"{self.factor_id}@{self.version}"


@dataclass(frozen=True, slots=True, kw_only=True)
class FactorValue:
    """One computed factor, bound to the definition that computed it."""

    definition: FactorDefinition
    value: Decimal

    def __post_init__(self) -> None:
        if type(self.definition) is not FactorDefinition:
            raise BrainContractError("Field 'definition' must be a FactorDefinition.")
        object.__setattr__(
            self, "value", quantized(require_finite_decimal(self.value, field="value"))
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class BaseRange:
    """The consolidation range over the sessions before the evaluation bar."""

    high: Decimal
    low: Decimal
    first_session: date
    last_session: date
    sessions: int

    @property
    def compactness(self) -> Decimal:
        """``(high - low) / high``: zero for a flat range, larger for a wide one."""
        return quantized((self.high - self.low) / self.high)


def _require_window(bars: Sequence[PriceBarValues], needed: int, *, what: str) -> None:
    if needed < 1:
        raise BrainContractError(f"{what}: the window must cover at least one session.")
    if len(bars) < needed:
        raise BrainContractError(
            f"{what}: {needed} bars are needed and {len(bars)} were supplied. A factor is "
            "never computed over a shorter window than its definition names."
        )


def simple_return(bars: Sequence[PriceBarValues], sessions: int) -> Decimal:
    """The close-to-close return over ``sessions`` sessions ending at the evaluation bar."""
    _require_window(bars, sessions + 1, what="simple_return")
    start = bars[-1 - sessions].close
    if start <= 0:
        raise BrainContractError("simple_return: the starting close must be positive.")
    return quantized(bars[-1].close / start - _ONE)


def moving_average_close(bars: Sequence[PriceBarValues], sessions: int) -> Decimal:
    """The arithmetic mean close over the last ``sessions`` bars, evaluation bar included."""
    _require_window(bars, sessions, what="moving_average_close")
    total = sum((bar.close for bar in bars[-sessions:]), Decimal(0))
    return quantized(total / Decimal(sessions))


def base_range(bars: Sequence[PriceBarValues], sessions: int) -> BaseRange:
    """The high/low range of the ``sessions`` bars **before** the evaluation bar."""
    _require_window(bars, sessions + 1, what="base_range")
    window = bars[-1 - sessions : -1]
    high = max(bar.high for bar in window)
    low = min(bar.low for bar in window)
    if high <= 0 or low <= 0:
        raise BrainContractError("base_range: prices in the base must be positive.")
    return BaseRange(
        high=high,
        low=low,
        first_session=window[0].session_date,
        last_session=window[-1].session_date,
        sessions=sessions,
    )


def relative_volume(bars: Sequence[PriceBarValues], baseline_sessions: int) -> Decimal:
    """Evaluation-bar volume over the mean volume of the ``baseline_sessions`` before it."""
    _require_window(bars, baseline_sessions + 1, what="relative_volume")
    baseline = bars[-1 - baseline_sessions : -1]
    mean = Decimal(sum(bar.volume for bar in baseline)) / Decimal(baseline_sessions)
    if mean <= 0:
        raise BrainContractError(
            "relative_volume: the baseline traded no volume, so a ratio to it is undefined."
        )
    return quantized(Decimal(bars[-1].volume) / mean)


def high_proximity(bars: Sequence[PriceBarValues], sessions: int) -> Decimal:
    """Evaluation close over the highest high of the last ``sessions`` bars, inclusive.

    One is at the high; below one is below it. The 52-week form is this
    computation at a 252-session lookback.
    """
    _require_window(bars, sessions, what="high_proximity")
    highest = max(bar.high for bar in bars[-sessions:])
    if highest <= 0:
        raise BrainContractError("high_proximity: the highest high must be positive.")
    return quantized(bars[-1].close / highest)


def overnight_gap_fraction(previous_close: Decimal, session_open: Decimal) -> Decimal:
    """``open / previous close - 1``: the overnight move a holder could not exit through."""
    if previous_close <= 0:
        raise BrainContractError("overnight_gap_fraction: the previous close must be positive.")
    return quantized(session_open / previous_close - _ONE)


def entry_gap_fraction(bars: Sequence[PriceBarValues]) -> Decimal:
    """The evaluation bar's own overnight gap."""
    _require_window(bars, 2, what="entry_gap_fraction")
    return overnight_gap_fraction(bars[-2].close, bars[-1].open)


def max_abs_overnight_gap(bars: Sequence[PriceBarValues], sessions: int) -> Decimal:
    """The largest absolute overnight gap across the last ``sessions`` transitions.

    A reference estimate of gap risk for the risk context: what the security
    has already done overnight, not a forecast of what it will do.
    """
    _require_window(bars, sessions + 1, what="max_abs_overnight_gap")
    window = bars[-1 - sessions :]
    largest = Decimal(0)
    for previous, following in pairwise(window):
        gap = abs(overnight_gap_fraction(previous.close, following.open))
        largest = max(largest, gap)
    return quantized(largest)


def average_dollar_volume(bars: Sequence[PriceBarValues], sessions: int) -> Decimal:
    """Mean ``close x volume`` over the ``sessions`` bars **before** the evaluation bar.

    A liquidity measure of the setup, not of the signal bar: the breakout
    session's own volume is what the template confirms on, and letting it into
    the liquidity screen would let one session qualify a security that never
    trades.
    """
    _require_window(bars, sessions + 1, what="average_dollar_volume")
    window = bars[-1 - sessions : -1]
    total = sum((bar.close * Decimal(bar.volume) for bar in window), Decimal(0))
    return quantized(total / Decimal(sessions))


__all__ = [
    "FACTOR_QUANTUM",
    "BaseRange",
    "FactorDefinition",
    "FactorValue",
    "average_dollar_volume",
    "base_range",
    "entry_gap_fraction",
    "high_proximity",
    "max_abs_overnight_gap",
    "moving_average_close",
    "overnight_gap_fraction",
    "quantized",
    "relative_volume",
    "simple_return",
]
