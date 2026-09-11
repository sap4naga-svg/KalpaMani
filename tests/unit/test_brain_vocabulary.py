"""The closed vocabularies, and the names each refuses.

A vocabulary is only closed while a value outside it is refused. These tests hold the
decision-state vocabulary to its eight members and confirm the five instruction-shaped
names are refused *by name*, not merely omitted; and they hold the compiler-stage order
to the accepted thirteen.
"""

from __future__ import annotations

import pytest

from kalpamani.strategies.brain.errors import BrainContractError
from kalpamani.strategies.brain.vocabulary import (
    COMPILER_STAGE_ORDER,
    CompilerStage,
    DecisionState,
    closed_member,
    require_decision_state,
)

pytestmark = pytest.mark.unit

DECISION_STATES = {
    "READY_FOR_RISK_REVIEW",
    "WATCHLIST",
    "REJECTED",
    "BLOCKED_DATA",
    "BLOCKED_EVENT",
    "BLOCKED_AI",
    "BLOCKED_CONTRADICTION",
    "BLOCKED_BORROW",
}
FORBIDDEN_STATES = ["MAYBE", "BUY", "SELL", "EXECUTE", "APPROVED_ORDER"]


def test_the_decision_vocabulary_is_exactly_the_eight_members() -> None:
    assert {state.value for state in DecisionState} == DECISION_STATES


@pytest.mark.parametrize("name", FORBIDDEN_STATES)
def test_an_instruction_shaped_state_is_refused_by_name(name: str) -> None:
    with pytest.raises(BrainContractError, match="refused by name"):
        require_decision_state(name)


def test_an_unknown_state_is_refused_as_unknown() -> None:
    with pytest.raises(BrainContractError, match="closed"):
        require_decision_state("SOMETHING_ELSE")


@pytest.mark.parametrize("state", sorted(DECISION_STATES))
def test_each_member_round_trips_through_the_admission_check(state: str) -> None:
    assert require_decision_state(state).value == state


def test_closed_member_resolves_a_bare_string_and_refuses_an_unknown_one() -> None:
    assert closed_member(DecisionState, "WATCHLIST") is DecisionState.WATCHLIST
    assert closed_member(DecisionState, "nope") is None
    assert closed_member(DecisionState, 5) is None


def test_the_compiler_has_thirteen_stages_in_the_accepted_order() -> None:
    assert len(COMPILER_STAGE_ORDER) == 13
    assert COMPILER_STAGE_ORDER[0] is CompilerStage.POINT_IN_TIME_REALITY_GATE
    assert COMPILER_STAGE_ORDER[-1] is CompilerStage.IMMUTABLE_REASON_CODE_CONSTRUCTION
    # no duplicates, and every stage present exactly once
    assert len(set(COMPILER_STAGE_ORDER)) == 13
    assert set(COMPILER_STAGE_ORDER) == set(CompilerStage)
