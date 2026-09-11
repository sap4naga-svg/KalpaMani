"""Negative controls added by the independent review of the offline Brain foundation.

Each test here pins a defect the review demonstrated against the submitted head and
the correction that closed it. They are kept in one file so the review record can
point at them, and so each stays a control against the *original* failure rather
than a restatement of the happy path:

* the identifier grammar admitted a trailing newline -- ``$`` matches before one --
  so "no whitespace" was one control character short of true;
* an AI ``challenger_verdict`` that was not a closed member was read as "not
  falsified", so an unschematized AI output passed as an acceptance, and a bare
  string spelling ``FALSIFIED`` was silently ignored; a naive or non-datetime
  ``produced_at`` raised ``TypeError`` from the staleness comparison instead of
  journaling ``BLOCKED_AI``;
* a benchmark series shorter than the factor window raised a contract error from
  inside the module instead of returning ``BLOCKED_DATA`` at the coverage stage,
  and a benchmark on a different session grid was compared as if it were the same;
* a peer attributed twice was counted twice, and the attribution ranks depended on
  the order the caller happened to supply the peers in;
* the Breakout Long ratio thresholds accepted a ``float``;
* the journal omitted the Research and Challenger output references, the resolved
  profile and the risk-context tags the specification's section 27 lists.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from fixtures import brain_equity as fx
from kalpamani.strategies.brain.compiler import compile_candidate
from kalpamani.strategies.brain.consolidation import PeerConclusion, consolidate
from kalpamani.strategies.brain.errors import BrainContractError
from kalpamani.strategies.brain.gate import run_reality_gate
from kalpamani.strategies.brain.identity import candidate_id, require_identifier
from kalpamani.strategies.brain.journal import journal_record
from kalpamani.strategies.brain.vocabulary import (
    AlphaFamily,
    ChallengerVerdict,
    CompilerStage,
    DecisionState,
    Direction,
    ModuleVerdict,
    ReasonCode,
)
from kalpamani.strategies.breakout.long import BreakoutLong, BreakoutLongParameters

pytestmark = pytest.mark.unit

MODULE = BreakoutLong(fx.TEST_PARAMS)


# -- the identifier grammar ---------------------------------------------------------------


@pytest.mark.parametrize("value", ["abc\n", "abc\r\n", "sha256:ab\n", "a\n"])
def test_a_trailing_newline_is_not_an_identifier(value: str) -> None:
    with pytest.raises(BrainContractError):
        require_identifier(value, field="probe")


def test_a_candidate_id_with_a_trailing_newline_is_refused() -> None:
    scenario = fx.build_scenario()
    intent = compile_candidate(scenario.inputs, MODULE)
    with pytest.raises(BrainContractError):
        dataclasses.replace(intent, candidate_id=intent.candidate_id + "\n")


def test_candidate_id_derivation_refuses_a_trailing_newline_in_any_part() -> None:
    with pytest.raises(BrainContractError):
        candidate_id(
            security_id="SEC-1\n",
            direction="LONG",
            strategy_id="s",
            strategy_version="v",
            as_of_time=fx.build_scenario().as_of,
            environment="research",
            evidence_reference="e",
        )


# -- AI evidence: the schema stage is total over what the compiler reads -----------------


def test_a_bare_string_falsified_verdict_removes_the_candidate() -> None:
    """The verdict is read through the closed vocabulary: a bare string that spells the
    member is the member, and the Challenger's removal is honoured rather than dropped."""
    scenario = fx.build_scenario()
    record = dataclasses.replace(
        fx.fresh_ai(scenario.as_of),
        challenger_verdict="FALSIFIED",  # type: ignore[arg-type]
    )
    intent = compile_candidate(fx.build_scenario(ai=record).inputs, MODULE)
    assert intent.status is DecisionState.REJECTED
    assert intent.reason_codes == (ReasonCode.AI_CHALLENGER_FALSIFIED,)


@pytest.mark.parametrize("verdict", ["BANANA", "not_falsified", "", 1, object()])
def test_an_unrecognised_verdict_is_malformed_not_accepted(verdict: object) -> None:
    """Before the correction every value here passed as "not falsified" and the candidate
    reached READY_FOR_RISK_REVIEW on unschematized AI output."""
    scenario = fx.build_scenario()
    record = dataclasses.replace(
        fx.fresh_ai(scenario.as_of),
        challenger_verdict=verdict,  # type: ignore[arg-type]
    )
    intent = compile_candidate(fx.build_scenario(ai=record).inputs, MODULE)
    assert intent.status is DecisionState.BLOCKED_AI
    assert intent.reason_codes == (ReasonCode.AI_EVIDENCE_MALFORMED,)
    assert intent.concluded_at_stage is CompilerStage.AI_SCHEMA_AND_PROVENANCE


@pytest.mark.parametrize(
    "produced_at",
    [datetime(2021, 1, 1, 0, 0), "2021-01-01T00:00:00Z", 0, Decimal(1)],
)
def test_a_malformed_production_instant_blocks_ai_rather_than_crashing(
    produced_at: object,
) -> None:
    scenario = fx.build_scenario()
    record = dataclasses.replace(
        fx.fresh_ai(scenario.as_of),
        produced_at=produced_at,  # type: ignore[arg-type]
    )
    intent = compile_candidate(fx.build_scenario(ai=record).inputs, MODULE)
    assert intent.status is DecisionState.BLOCKED_AI
    assert intent.reason_codes == (ReasonCode.AI_EVIDENCE_MALFORMED,)


def test_ai_output_produced_after_the_decision_instant_is_stale() -> None:
    scenario = fx.build_scenario()
    record = dataclasses.replace(
        fx.fresh_ai(scenario.as_of), produced_at=scenario.as_of + timedelta(seconds=1)
    )
    intent = compile_candidate(fx.build_scenario(ai=record).inputs, MODULE)
    assert intent.status is DecisionState.BLOCKED_AI
    assert intent.reason_codes == (ReasonCode.AI_EVIDENCE_STALE,)


def test_a_falsifying_verdict_still_cannot_rescue_and_a_valid_one_still_cannot_either() -> None:
    """Both verdict values leave a deterministic refusal exactly where it was."""
    for verdict in (ChallengerVerdict.NOT_FALSIFIED, ChallengerVerdict.FALSIFIED):
        scenario = fx.build_scenario()
        record = dataclasses.replace(fx.fresh_ai(scenario.as_of), challenger_verdict=verdict)
        intent = compile_candidate(
            fx.build_scenario(universe_member=False, ai=record).inputs, MODULE
        )
        assert intent.status is DecisionState.REJECTED
        assert intent.reason_codes == (ReasonCode.UNIVERSE_NON_MEMBER,)
        assert intent.concluded_at_stage is CompilerStage.POINT_IN_TIME_REALITY_GATE


# -- the benchmark: coverage and grid -----------------------------------------------------


def test_a_benchmark_shorter_than_the_factor_window_is_blocked_data_not_a_crash() -> None:
    scenario = fx.build_scenario()
    assert scenario.inputs.benchmark_history is not None
    short = dataclasses.replace(
        scenario.inputs.benchmark_history, bars=scenario.benchmark_bars[-5:]
    )
    inputs = dataclasses.replace(scenario.inputs, benchmark_history=short)
    intent = compile_candidate(inputs, MODULE)
    assert intent.status is DecisionState.BLOCKED_DATA
    assert intent.reason_codes == (ReasonCode.INSUFFICIENT_HISTORY,)
    assert intent.concluded_at_stage is CompilerStage.REQUIRED_DATA_COVERAGE


def test_a_benchmark_shorter_than_required_but_long_enough_for_the_security_still_blocks() -> None:
    """The security satisfies coverage on its own; the benchmark is what falls short."""
    scenario = fx.build_scenario()
    required = MODULE.spec.data.required_history_sessions
    assert len(scenario.security_bars) >= required
    assert scenario.inputs.benchmark_history is not None
    short = dataclasses.replace(
        scenario.inputs.benchmark_history, bars=scenario.benchmark_bars[-(required - 1) :]
    )
    intent = compile_candidate(
        dataclasses.replace(scenario.inputs, benchmark_history=short), MODULE
    )
    assert intent.status is DecisionState.BLOCKED_DATA
    assert intent.reason_codes == (ReasonCode.INSUFFICIENT_HISTORY,)


def test_a_benchmark_on_a_different_session_grid_is_refused_at_the_gate() -> None:
    """Same length, ordered, no duplicate -- but one session the security did not trade.

    The fifth synthetic session is a Friday; moving it to the Saturday keeps the
    benchmark ordered and unique, so only the grid comparison can catch it.
    """
    scenario = fx.build_scenario()
    assert scenario.inputs.benchmark_history is not None
    bars = list(scenario.benchmark_bars)
    friday = bars[4]
    assert friday.session_date.weekday() == 4
    bars[4] = dataclasses.replace(
        friday,
        session_date=friday.session_date + timedelta(days=1),
        bar_end_time=friday.bar_end_time + timedelta(days=1),
    )
    shifted = dataclasses.replace(scenario.inputs.benchmark_history, bars=tuple(bars))
    outcome = run_reality_gate(
        dataclasses.replace(scenario.inputs, benchmark_history=shifted), MODULE.spec
    )
    assert not outcome.admitted
    assert outcome.reason is ReasonCode.SESSION_GRID_MISMATCH
    assert outcome.state is DecisionState.BLOCKED_DATA


def test_a_benchmark_longer_than_the_security_on_the_same_trailing_grid_is_admitted() -> None:
    """The grid rule is over the overlap: extra earlier benchmark history is not a defect."""
    scenario = fx.build_scenario()
    assert scenario.inputs.benchmark_history is not None
    earlier = fx._bar(fx.BENCHMARK_ID, 0, Decimal("100"), 100_000)
    # Prepend one bar dated before the first security bar by rebuilding the grid one
    # index earlier: the fixture's index-0 session is the security's first session, so
    # shift every benchmark bar one index later and add a new index-0 bar.
    rebuilt = [
        fx._bar(fx.BENCHMARK_ID, index + 1, bar.close, bar.volume)
        for index, bar in enumerate(scenario.benchmark_bars)
    ]
    security = [
        fx._bar(fx.SECURITY_ID, index + 1, bar.close, bar.volume)
        for index, bar in enumerate(scenario.security_bars)
    ]
    as_of = fx._as_of_for(len(security))
    price = dataclasses.replace(
        scenario.inputs.price_history, bars=tuple(security), provenance=fx._provenance(as_of)
    )
    benchmark = dataclasses.replace(
        scenario.inputs.benchmark_history,
        bars=(earlier, *rebuilt),
        provenance=fx._provenance(as_of),
    )
    inputs = dataclasses.replace(
        scenario.inputs,
        as_of_time=as_of,
        evaluation_session=security[-1].session_date,
        price_history=price,
        benchmark_history=benchmark,
        universe=None,
        event_context=None,
        market_context=None,
    )
    spec = dataclasses.replace(
        MODULE.spec,
        data=dataclasses.replace(
            MODULE.spec.data,
            required_domains=frozenset(
                {
                    d
                    for d in MODULE.spec.data.required_domains
                    if d.value in {"PRICE_BARS", "BENCHMARK_BARS"}
                }
            ),
        ),
        permissions=dataclasses.replace(
            MODULE.spec.permissions,
            market_prerequisite=MODULE.spec.permissions.gap_prerequisite.__class__("OPTIONAL"),
            event_prerequisite=MODULE.spec.permissions.gap_prerequisite.__class__("OPTIONAL"),
        ),
    )
    outcome = run_reality_gate(inputs, spec)
    assert outcome.admitted, outcome.reason
    assert len(outcome.benchmark_bars) == len(outcome.bars) + 1


# -- peers: distinct, and canonically ordered --------------------------------------------


def _peer(strategy_id: str, direction: Direction = Direction.LONG) -> PeerConclusion:
    return PeerConclusion(
        strategy_id=strategy_id,
        strategy_version=f"{strategy_id}/r1",
        strategy_module=strategy_id,
        trade_template=f"{strategy_id}-template",
        alpha_family=AlphaFamily.MOMENTUM_CONTINUATION,
        direction=direction,
        verdict=ModuleVerdict.TRIGGERED,
    )


def test_a_peer_attributed_twice_is_refused() -> None:
    peer = _peer("pullback-long")
    with pytest.raises(BrainContractError):
        compile_candidate(fx.build_scenario().inputs, MODULE, peers=(peer, peer))


def test_a_peer_carrying_the_primary_modules_own_id_is_refused() -> None:
    with pytest.raises(BrainContractError):
        compile_candidate(fx.build_scenario().inputs, MODULE, peers=(_peer("breakout-long"),))


def test_a_peer_of_the_wrong_type_is_refused() -> None:
    with pytest.raises(BrainContractError):
        compile_candidate(
            fx.build_scenario().inputs,
            MODULE,
            peers=("pullback-long",),  # type: ignore[arg-type]
        )
    with pytest.raises(BrainContractError):
        consolidate(
            spec=MODULE.spec,
            primary_direction=Direction.LONG,
            primary_verdict=ModuleVerdict.TRIGGERED,
            peers=[_peer("pullback-long")],  # type: ignore[arg-type]
        )


def test_peer_order_does_not_change_the_attribution() -> None:
    a, b = _peer("pead-long"), _peer("pullback-long")
    first = compile_candidate(fx.build_scenario().inputs, MODULE, peers=(a, b))
    second = compile_candidate(fx.build_scenario().inputs, MODULE, peers=(b, a))
    assert first == second
    assert [c.strategy_id for c in first.strategy.contributing] == [
        "breakout-long",
        "pead-long",
        "pullback-long",
    ]
    assert [c.rank for c in first.strategy.contributing] == [1, 2, 3]


def test_a_bare_string_direction_on_a_peer_is_normalised_before_comparison() -> None:
    """``"SHORT"`` is the SHORT member and contradicts; ``"LONG"`` agrees. Before the
    correction both compared unequal by identity and the outcome was accidental."""
    agreeing = dataclasses.replace(
        _peer("pullback-long"),
        direction="LONG",  # type: ignore[arg-type]
    )
    intent = compile_candidate(fx.build_scenario().inputs, MODULE, peers=(agreeing,))
    assert intent.status is DecisionState.READY_FOR_RISK_REVIEW
    opposing = dataclasses.replace(
        _peer("deterioration-short"),
        direction="SHORT",  # type: ignore[arg-type]
    )
    intent = compile_candidate(fx.build_scenario().inputs, MODULE, peers=(opposing,))
    assert intent.status is DecisionState.BLOCKED_CONTRADICTION
    with pytest.raises(BrainContractError):
        dataclasses.replace(_peer("x"), direction="SIDEWAYS")  # type: ignore[arg-type]


# -- Breakout Long parameters: Decimal, and only Decimal ---------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "max_base_compactness",
        "min_relative_volume",
        "min_relative_strength",
        "max_entry_gap",
        "min_average_dollar_volume",
    ],
)
def test_a_float_threshold_is_refused(field: str) -> None:
    with pytest.raises(BrainContractError):
        BreakoutLongParameters(**{field: 0.15})  # type: ignore[arg-type]


def test_a_non_finite_or_negative_bound_is_refused() -> None:
    with pytest.raises(BrainContractError):
        BreakoutLongParameters(max_entry_gap=Decimal("NaN"))
    with pytest.raises(BrainContractError):
        BreakoutLongParameters(max_base_compactness=Decimal("-0.1"))
    with pytest.raises(BrainContractError):
        BreakoutLongParameters(min_relative_volume=Decimal("0"))
    with pytest.raises(BrainContractError):
        BreakoutLongParameters(trend_sessions=0)


# -- the journal carries what section 27 lists ---------------------------------------------


def test_the_journal_carries_the_ai_output_references_and_risk_tags() -> None:
    intent = compile_candidate(fx.build_scenario(with_ai=True).inputs, MODULE)
    assert intent.status is DecisionState.READY_FOR_RISK_REVIEW
    record = journal_record(intent)
    assert record.ai_research_output_reference == "ai/research/synthetic.1"
    assert record.ai_challenger_output_reference == "ai/challenger/synthetic.1"
    assert record.resolved_profile == fx.PROFILE.value
    assert record.evaluation_session == intent.evaluation_session
    assert record.stages_passed == intent.stages_passed
    assert "family_exposure=MOMENTUM_CONTINUATION" in record.risk_context_tags
    assert "market_permission=PERMITTED" in record.risk_context_tags
    assert "earnings_carry=NOT_PERMITTED" in record.risk_context_tags
    # Tags are closed values and identifiers -- never a number and never prose.
    for tag in record.risk_context_tags:
        name, value = tag.split("=", 1)
        require_identifier(name, field="tag")
        require_identifier(value, field="tag")


def test_a_refusal_before_evidence_journals_no_tags_and_no_ai_references() -> None:
    intent = compile_candidate(fx.build_scenario(with_event=False).inputs, MODULE)
    assert intent.status is DecisionState.BLOCKED_DATA
    record = journal_record(intent)
    assert record.risk_context_tags == ()
    assert record.ai_research_output_reference is None
    assert record.resolved_profile is None
    assert record.stages_passed == ()


def test_the_record_hash_covers_the_added_fields() -> None:
    intent = compile_candidate(fx.build_scenario(with_ai=True).inputs, MODULE)
    record = journal_record(intent)
    altered = dataclasses.replace(record, ai_challenger_output_reference="ai/challenger/other")
    assert altered.record_hash != record.record_hash
    altered = dataclasses.replace(record, risk_context_tags=())
    assert altered.record_hash != record.record_hash
