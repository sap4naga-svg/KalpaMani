"""The point-in-time reality gate's admissibility checks, and the audit journal.

The gate tests confirm the refusals that keep a non-point-in-time result out of a
decision. The journal tests confirm the audit record carries references and never a
vendor row, and that it is a deterministic function of the intent.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest

from fixtures import brain_equity as fx
from kalpamani.data.contracts.vocabulary import InformationSetProfile
from kalpamani.strategies.brain.compiler import compile_candidate
from kalpamani.strategies.brain.gate import forward_horizon_session, run_reality_gate
from kalpamani.strategies.brain.journal import journal_record
from kalpamani.strategies.brain.vocabulary import DecisionState, ReasonCode
from kalpamani.strategies.breakout.long import BreakoutLong

pytestmark = pytest.mark.unit

MODULE = BreakoutLong(fx.TEST_PARAMS)


# -- the gate ---------------------------------------------------------------------------


def test_the_gate_admits_a_clean_scenario() -> None:
    scenario = fx.build_scenario()
    outcome = run_reality_gate(scenario.inputs, MODULE.spec)
    assert outcome.admitted
    assert outcome.reason is None
    assert len(outcome.bars) == len(scenario.security_bars)


def test_the_gate_refuses_a_wrong_security_result() -> None:
    scenario = fx.build_scenario()
    wrong = dataclasses.replace(scenario.inputs.price_history, security_id="SEC-OTHER")
    outcome = run_reality_gate(fx.with_price(scenario, wrong).inputs, MODULE.spec)
    assert not outcome.admitted
    assert outcome.reason is ReasonCode.SECURITY_MISMATCH


def test_the_gate_refuses_a_public_pit_result_for_a_provider_realistic_strategy() -> None:
    scenario = fx.build_scenario()
    provenance = dataclasses.replace(
        scenario.inputs.price_history.provenance,
        requested_profile=InformationSetProfile.PUBLIC_PIT,
        resolved_profile=InformationSetProfile.PUBLIC_PIT,
    )
    price = dataclasses.replace(scenario.inputs.price_history, provenance=provenance)
    outcome = run_reality_gate(fx.with_price(scenario, price).inputs, MODULE.spec)
    assert not outcome.admitted
    assert outcome.reason is ReasonCode.PROFILE_MISMATCH


def test_the_gate_refuses_missing_lineage() -> None:
    scenario = fx.build_scenario()
    provenance = dataclasses.replace(scenario.inputs.price_history.provenance, manifest_hash="")
    price = dataclasses.replace(scenario.inputs.price_history, provenance=provenance)
    outcome = run_reality_gate(fx.with_price(scenario, price).inputs, MODULE.spec)
    assert not outcome.admitted
    assert outcome.reason is ReasonCode.LINEAGE_INCOMPLETE


def test_the_gate_refuses_missing_quality_evidence() -> None:
    scenario = fx.build_scenario()
    provenance = dataclasses.replace(
        scenario.inputs.price_history.provenance, quality_report_hash=""
    )
    price = dataclasses.replace(scenario.inputs.price_history, provenance=provenance)
    outcome = run_reality_gate(fx.with_price(scenario, price).inputs, MODULE.spec)
    assert not outcome.admitted
    assert outcome.reason is ReasonCode.QUALITY_EVIDENCE_MISSING


def test_a_universe_snapshot_for_the_wrong_session_blocks() -> None:
    scenario = fx.build_scenario()
    assert scenario.inputs.universe is not None
    universe = dataclasses.replace(
        scenario.inputs.universe, session_date=scenario.evaluation_session - timedelta(days=7)
    )
    inputs = dataclasses.replace(scenario.inputs, universe=universe)
    outcome = run_reality_gate(inputs, MODULE.spec)
    assert not outcome.admitted
    assert outcome.reason is ReasonCode.UNIVERSE_SNAPSHOT_SESSION_MISMATCH


def test_event_coverage_short_of_the_holding_horizon_blocks() -> None:
    scenario = fx.build_scenario()
    assert scenario.inputs.event_context is not None
    short = dataclasses.replace(
        scenario.inputs.event_context,
        coverage_through_session=scenario.evaluation_session,  # covers nothing forward
    )
    inputs = dataclasses.replace(scenario.inputs, event_context=short)
    outcome = run_reality_gate(inputs, MODULE.spec)
    assert not outcome.admitted
    assert outcome.reason is ReasonCode.EVENT_EVIDENCE_UNRESOLVED


def test_the_forward_horizon_is_a_conservative_calendar_projection() -> None:
    """It errs long: a 30-session horizon spans well beyond 30 calendar days."""
    from datetime import date

    projected = forward_horizon_session(date(2021, 1, 4), 30)
    assert (projected - date(2021, 1, 4)).days > 30


# -- the journal ------------------------------------------------------------------------


def test_the_journal_carries_references_not_rows() -> None:
    intent = compile_candidate(fx.build_scenario().inputs, MODULE)
    record = journal_record(intent)
    assert record.status is DecisionState.READY_FOR_RISK_REVIEW
    assert record.strategy_version == "breakout-long/r1-research"
    # Lineage is identifiers; a dataset version and manifest hash are references.
    assert any("gold/synthetic.brain.1" == ref for ref in record.lineage_references)
    assert record.factor_vector_reference is not None
    # No bar value or vendor row can be in the record: every field is an identifier,
    # an enum, an instant or a tuple of those. The record hashes deterministically.
    assert record.record_hash == journal_record(intent).record_hash


def test_a_blocked_intent_still_journals_its_reason() -> None:
    intent = compile_candidate(fx.build_scenario(universe_member=False).inputs, MODULE)
    record = journal_record(intent)
    assert record.status is DecisionState.REJECTED
    assert ReasonCode.UNIVERSE_NON_MEMBER in record.reason_codes
