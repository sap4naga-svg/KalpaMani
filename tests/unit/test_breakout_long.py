"""Breakout Long: the factor computations, and the module's eligibility and trigger.

The module's numbers are research parameters, so these tests do not assert that any
value is *correct* -- there is no correct value without data. They assert that the
computations are deterministic and windowed as documented, and that the module's
boundaries fall exactly where its parameters put them: a strict close above the base
high triggers, the base high itself does not, and each eligibility rule refuses on its
own axis.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from kalpamani.data.contracts.entities import PriceBarValues
from kalpamani.strategies.brain import factors
from kalpamani.strategies.brain.errors import BrainContractError
from kalpamani.strategies.brain.vocabulary import ModuleVerdict, ReasonCode
from kalpamani.strategies.breakout.long import BreakoutLong, BreakoutLongParameters

pytestmark = pytest.mark.unit


def _bar(index: int, close: str, volume: int, *, spread: str = "0.5") -> PriceBarValues:
    day = date(2021, 1, 4) + timedelta(days=index)
    c = Decimal(close)
    s = Decimal(spread)
    return PriceBarValues(
        security_id="SEC-1",
        session_date=day,
        bar_end_time=datetime(day.year, day.month, day.day, 21, tzinfo=UTC),
        open=c,
        high=c + s,
        low=c - s,
        close=c,
        volume=volume,
    )


def _series(closes: list[str], volumes: list[int]) -> tuple[PriceBarValues, ...]:
    return tuple(_bar(i, c, v) for i, (c, v) in enumerate(zip(closes, volumes, strict=True)))


# -- the factor computations ------------------------------------------------------------


def test_simple_return_is_close_to_close_over_the_window() -> None:
    bars = _series(["100", "110", "121"], [1, 1, 1])
    assert factors.simple_return(bars, 2) == Decimal("0.21")


def test_moving_average_uses_the_window_including_the_evaluation_bar() -> None:
    bars = _series(["10", "20", "30", "40"], [1, 1, 1, 1])
    assert factors.moving_average_close(bars, 3) == Decimal("30")


def test_base_range_excludes_the_evaluation_bar() -> None:
    bars = _series(["100", "100", "100", "130"], [1, 1, 1, 1])
    base = factors.base_range(bars, 3)
    # highs are close + 0.5; the evaluation bar (130) is excluded, so the high is 100.5.
    assert base.high == Decimal("100.5")
    assert base.low == Decimal("99.5")


def test_relative_volume_is_evaluation_over_baseline_mean() -> None:
    bars = _series(["100", "100", "100", "100"], [100, 100, 100, 300])
    assert factors.relative_volume(bars, 3) == Decimal("3")


def test_a_window_longer_than_the_series_is_refused_not_shortened() -> None:
    bars = _series(["100", "101"], [1, 1])
    with pytest.raises(BrainContractError):
        factors.moving_average_close(bars, 5)


def test_the_factor_computations_are_pure_and_reproducible() -> None:
    bars = _series(["90", "95", "100", "105"], [10, 20, 30, 40])
    assert factors.simple_return(bars, 3) == factors.simple_return(bars, 3)
    assert factors.average_dollar_volume(bars, 3) == factors.average_dollar_volume(bars, 3)


# -- the module's eligibility and trigger -----------------------------------------------

#: A small, readable window for the module tests. The production default is unchanged.
PARAMS = BreakoutLongParameters(
    trend_sessions=5,
    base_sessions=5,
    relative_strength_sessions=5,
    volume_baseline_sessions=5,
    liquidity_sessions=5,
    high_proximity_sessions=5,
    min_average_dollar_volume=Decimal("1000"),
)


def _eligible_setup(breakout_close: str, breakout_volume: int) -> tuple[PriceBarValues, ...]:
    # rising leg, then a flat compact base, then the evaluation bar.
    closes = ["80", "84", "88", "92", "96", "100", "100", "100", "100", "100", breakout_close]
    volumes = [1000] * 10 + [breakout_volume]
    return _series(closes, volumes)


def _flat_benchmark(length: int) -> tuple[PriceBarValues, ...]:
    return _series(["100"] * length, [1000] * length)


def test_a_strict_close_above_the_base_high_with_volume_triggers() -> None:
    bars = _eligible_setup("101", 3000)
    result = BreakoutLong(PARAMS).evaluate(bars, _flat_benchmark(len(bars)))
    assert result.verdict is ModuleVerdict.TRIGGERED
    assert result.trigger is not None
    assert result.reason_codes == (ReasonCode.BREAKOUT_CONFIRMED,)
    assert result.trigger.entry_reference_level == Decimal("100.5")  # the base high
    assert result.trigger.stop_reference_level == Decimal("99.5")  # the base low


def test_a_close_exactly_at_the_base_high_does_not_trigger() -> None:
    """The boundary is strict: at the resistance is not through it."""
    bars = _eligible_setup("100.5", 3000)
    result = BreakoutLong(PARAMS).evaluate(bars, _flat_benchmark(len(bars)))
    assert result.verdict is ModuleVerdict.SETUP_NOT_TRIGGERED
    assert ReasonCode.BREAKOUT_NOT_CONFIRMED in result.reason_codes


def test_a_breakout_without_volume_confirmation_does_not_trigger() -> None:
    bars = _eligible_setup("101", 1000)  # volume equals the baseline: no confirmation
    result = BreakoutLong(PARAMS).evaluate(bars, _flat_benchmark(len(bars)))
    assert result.verdict is ModuleVerdict.SETUP_NOT_TRIGGERED
    assert ReasonCode.VOLUME_NOT_CONFIRMED in result.reason_codes


def test_a_security_not_outperforming_the_benchmark_is_ineligible() -> None:
    bars = _eligible_setup("101", 3000)
    strong_benchmark = _series(["100"] * (len(bars) - 1) + ["200"], [1000] * len(bars))
    result = BreakoutLong(PARAMS).evaluate(bars, strong_benchmark)
    assert result.verdict is ModuleVerdict.INELIGIBLE
    assert ReasonCode.RELATIVE_STRENGTH_NOT_POSITIVE in result.reason_codes


def test_a_wide_base_is_ineligible() -> None:
    closes = ["80", "84", "88", "92", "96", "100", "70", "130", "90", "110", "131"]
    volumes = [1000] * 10 + [3000]
    result = BreakoutLong(PARAMS).evaluate(_series(closes, volumes), _flat_benchmark(11))
    assert result.verdict is ModuleVerdict.INELIGIBLE
    assert ReasonCode.BASE_NOT_COMPACT in result.reason_codes


def test_an_illiquid_setup_is_ineligible() -> None:
    params = BreakoutLongParameters(
        trend_sessions=5,
        base_sessions=5,
        relative_strength_sessions=5,
        volume_baseline_sessions=5,
        liquidity_sessions=5,
        high_proximity_sessions=5,
        min_average_dollar_volume=Decimal("100000000"),  # far above the fixture's dollar volume
    )
    bars = _eligible_setup("101", 3000)
    result = BreakoutLong(params).evaluate(bars, _flat_benchmark(len(bars)))
    assert result.verdict is ModuleVerdict.INELIGIBLE
    assert ReasonCode.LIQUIDITY_BELOW_MINIMUM in result.reason_codes


def test_a_large_entry_gap_is_a_gap_constraint() -> None:
    # eligible base, but the evaluation bar opens far above the prior close.
    closes = ["80", "84", "88", "92", "96", "100", "100", "100", "100", "100", "101"]
    volumes = [1000] * 10 + [3000]
    bars = list(_series(closes, volumes))
    last = bars[-1]
    import dataclasses

    bars[-1] = dataclasses.replace(last, open=Decimal("130"), high=Decimal("131"))
    result = BreakoutLong(PARAMS).evaluate(tuple(bars), _flat_benchmark(11))
    assert result.verdict is ModuleVerdict.GAP_CONSTRAINT
    assert ReasonCode.ENTRY_GAP_EXCEEDS_LIMIT in result.reason_codes


def test_the_module_evaluation_is_reproducible() -> None:
    bars = _eligible_setup("101", 3000)
    module = BreakoutLong(PARAMS)
    first = module.evaluate(bars, _flat_benchmark(len(bars)))
    second = module.evaluate(bars, _flat_benchmark(len(bars)))
    assert first.verdict is second.verdict
    assert [v.value for v in first.factor_snapshot] == [v.value for v in second.factor_snapshot]
