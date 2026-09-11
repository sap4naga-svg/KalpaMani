"""The Brain's typed contracts refuse at construction what a later reader would misread.

These are the guards on the records themselves: the identifier grammar that keeps
prose out of every string field, the finite-Decimal rule that keeps floats out of
every number, the structural exclusion that keeps a size or an order out of
``CandidateIntent``, and the ``StrategySpec`` consistency rules that keep a
research parameter from quietly authorizing Paper or live operation.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from kalpamani.common.environment import Environment
from kalpamani.strategies.brain.errors import BrainContractError
from kalpamani.strategies.brain.identity import (
    candidate_id,
    require_finite_decimal,
    require_identifier,
    require_instant,
)
from kalpamani.strategies.brain.intent import CandidateIntent, LevelReference, TradeThesis
from kalpamani.strategies.brain.spec import StrategySpec
from kalpamani.strategies.brain.vocabulary import (
    EntryCondition,
    InvalidationCondition,
    LifecycleStage,
    StopReferenceKind,
)
from kalpamani.strategies.breakout.long import BreakoutLong, build_spec

pytestmark = pytest.mark.unit

AS_OF = datetime(2021, 6, 1, 23, 0, tzinfo=UTC)


# -- the identifier grammar keeps prose out of every string field -----------------------


@pytest.mark.parametrize(
    "value",
    ["a sentence with spaces", "sell 100 shares", "", "x" * 201, "line\nbreak", "tab\there"],
)
def test_the_identifier_grammar_refuses_prose(value: str) -> None:
    with pytest.raises(BrainContractError):
        require_identifier(value, field="f")


@pytest.mark.parametrize("value", ["breakout-long/r1", "sha256:abc123", "SEC-0001", "a.b_c+d"])
def test_the_identifier_grammar_admits_an_identifier(value: str) -> None:
    assert require_identifier(value, field="f") == value


def test_a_refused_identifier_is_not_quoted_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """A value refused for being free text must not be copied into the error that refuses it."""
    free_text = "this looks like a leaked instruction"
    with pytest.raises(BrainContractError) as excinfo:
        require_identifier(free_text, field="f")
    assert free_text not in str(excinfo.value)


def test_a_float_is_refused_where_a_decimal_is_required() -> None:
    with pytest.raises(BrainContractError):
        require_finite_decimal(1.5, field="f")


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_a_non_finite_decimal_is_refused(value: Decimal) -> None:
    with pytest.raises(BrainContractError):
        require_finite_decimal(value, field="f")


def test_a_naive_instant_is_refused() -> None:
    with pytest.raises(BrainContractError):
        require_instant(datetime(2021, 1, 1, 12, 0), field="f")


def test_candidate_id_is_derived_and_reproducible() -> None:
    kwargs = {
        "security_id": "SEC-1",
        "direction": "LONG",
        "strategy_id": "breakout-long",
        "strategy_version": "breakout-long/r1",
        "as_of_time": AS_OF,
        "environment": "research",
        "evidence_reference": "sha256_abcdef",
    }
    first = candidate_id(**kwargs)  # type: ignore[arg-type]
    assert first == candidate_id(**kwargs)  # type: ignore[arg-type]
    assert first.startswith("ci-")
    # A different instant is a different decision.
    changed = candidate_id(**{**kwargs, "as_of_time": datetime(2021, 6, 2, 23, 0, tzinfo=UTC)})  # type: ignore[arg-type]
    assert changed != first


# -- the CandidateIntent structural exclusion -------------------------------------------


#: Meanings a CandidateIntent may never carry, and a field name that would carry each.
#: The point is not that these names are absent by accident -- it is that the record has
#: no field of any of these meanings at all, checked against the actual field set.
FORBIDDEN_FIELD_SUBSTRINGS = (
    "shares",
    "quantity",
    "dollar",
    "position_size",
    "size",
    "order_type",
    "route",
    "client_order",
    "broker_order",
    "credential",
    "account_number",
    "password",
    "token",
)


def _all_field_names(record_type: type) -> set[str]:
    names: set[str] = set()
    for field in fields(record_type):
        names.add(field.name)
    return names


def test_candidate_intent_has_no_field_of_a_forbidden_meaning() -> None:
    names = _all_field_names(CandidateIntent)
    for forbidden in FORBIDDEN_FIELD_SUBSTRINGS:
        offenders = [name for name in names if forbidden in name.lower()]
        assert offenders == [], f"{forbidden!r} appears in CandidateIntent fields: {offenders}"


def test_candidate_intent_cannot_be_subclassed() -> None:
    """A subclass could add a field of a forbidden meaning; the type refuses one."""
    with pytest.raises(TypeError):

        class _Sneaky(CandidateIntent):
            pass


def test_the_thesis_stop_is_a_reference_not_an_order() -> None:
    """The technical stop names a level; it has no order type, route, size or identity."""
    stop = LevelReference(
        kind=StopReferenceKind.BASE_LOW,
        level=Decimal("99.5"),
        derived_from_first_session=date(2021, 1, 4),
        derived_from_last_session=date(2021, 1, 8),
    )
    names = _all_field_names(LevelReference)
    for forbidden in ("order", "route", "size", "quantity", "shares"):
        assert not any(forbidden in name.lower() for name in names)
    thesis = TradeThesis(
        entry_condition=EntryCondition.CLOSE_ABOVE_BASE_HIGH_WITH_VOLUME_CONFIRMATION,
        entry_reference_level=Decimal("100.5"),
        invalidation_condition=InvalidationCondition.CLOSE_BELOW_BASE_LOW,
        technical_stop_reference=stop,
        expected_holding_sessions=10,
        minimum_holding_sessions=2,
        maximum_holding_sessions=30,
    )
    assert thesis.technical_stop_reference.level == Decimal("99.5")


def test_a_long_thesis_invalidation_must_sit_below_the_entry() -> None:
    stop = LevelReference(
        kind=StopReferenceKind.BASE_LOW,
        level=Decimal("101"),
        derived_from_first_session=date(2021, 1, 4),
        derived_from_last_session=date(2021, 1, 8),
    )
    with pytest.raises(BrainContractError):
        TradeThesis(
            entry_condition=EntryCondition.CLOSE_ABOVE_BASE_HIGH_WITH_VOLUME_CONFIRMATION,
            entry_reference_level=Decimal("100"),
            invalidation_condition=InvalidationCondition.CLOSE_BELOW_BASE_LOW,
            technical_stop_reference=stop,
            expected_holding_sessions=10,
            minimum_holding_sessions=2,
            maximum_holding_sessions=30,
        )


# -- the StrategySpec consistency rules --------------------------------------------------


def test_the_breakout_spec_is_research_stage_and_research_only() -> None:
    spec = build_spec()
    assert spec.lifecycle_stage is LifecycleStage.REGISTERED_HYPOTHESIS
    assert spec.authorized_environments == frozenset({Environment.RESEARCH})


def test_a_research_stage_spec_cannot_authorize_paper() -> None:
    """PAPER is the first order-producing stage; a research version may not reach it."""
    with pytest.raises(BrainContractError):
        _spec_with(authorized_environments=frozenset({Environment.RESEARCH, Environment.PAPER}))


def test_a_research_stage_spec_cannot_authorize_live() -> None:
    with pytest.raises(BrainContractError):
        _spec_with(authorized_environments=frozenset({Environment.RESEARCH, Environment.LIVE}))


def test_a_spec_whose_history_is_shorter_than_its_factors_is_refused() -> None:
    with pytest.raises(BrainContractError):
        _spec_with_short_history()


def test_the_breakout_module_reports_its_own_spec() -> None:
    module = BreakoutLong()
    assert module.spec.strategy_id == "breakout-long"
    assert module.spec.direction.value == "LONG"


def _spec_with(**overrides: object) -> StrategySpec:
    """Rebuild the breakout spec with one field overridden, to test a single rule."""
    base = build_spec()
    import dataclasses

    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


def _spec_with_short_history() -> StrategySpec:
    import dataclasses

    base = build_spec()
    data = dataclasses.replace(base.data, required_history_sessions=1)
    return dataclasses.replace(base, data=data)
