"""The strategy health machine: the one asymmetry, enforced rather than trusted.

Reducing or disabling new entries is automatic; restoring them past a governed
suspension is not. These tests hold the transition table to that rule from both
directions, and confirm ``RETIRED`` is terminal.
"""

from __future__ import annotations

import pytest

from kalpamani.strategies.brain.health import classify_transition, is_automatic
from kalpamani.strategies.brain.vocabulary import HealthState

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("state_from", "target"),
    [
        (HealthState.HEALTHY, HealthState.WATCH),
        (HealthState.WATCH, HealthState.DEGRADED),
        (HealthState.DEGRADED, HealthState.NEW_ENTRIES_REDUCED),
        (HealthState.DEGRADED, HealthState.NEW_ENTRIES_DISABLED),
        (HealthState.DEGRADED, HealthState.SUSPENDED),
        (HealthState.NEW_ENTRIES_REDUCED, HealthState.NEW_ENTRIES_DISABLED),
        (HealthState.NEW_ENTRIES_DISABLED, HealthState.SUSPENDED),
        (HealthState.WATCH, HealthState.HEALTHY),  # the one automatic recovery
    ],
)
def test_degradation_and_mild_recovery_are_automatic(
    state_from: HealthState, target: HealthState
) -> None:
    assert is_automatic(state_from, target)


@pytest.mark.parametrize(
    ("state_from", "target"),
    [
        (HealthState.SUSPENDED, HealthState.HEALTHY),
        (HealthState.SUSPENDED, HealthState.WATCH),
        (HealthState.NEW_ENTRIES_DISABLED, HealthState.HEALTHY),
        (HealthState.NEW_ENTRIES_REDUCED, HealthState.HEALTHY),
        (HealthState.DEGRADED, HealthState.HEALTHY),
    ],
)
def test_restoring_new_entries_requires_a_human(
    state_from: HealthState, target: HealthState
) -> None:
    outcome = classify_transition(state_from, target)
    assert outcome.permitted
    assert outcome.requires_human
    assert not is_automatic(state_from, target)


def test_leaving_suspended_is_never_automatic() -> None:
    for target in HealthState:
        if target is HealthState.SUSPENDED:
            continue
        assert not is_automatic(HealthState.SUSPENDED, target)


def test_retired_is_terminal() -> None:
    for target in HealthState:
        if target is HealthState.RETIRED:
            continue
        outcome = classify_transition(HealthState.RETIRED, target)
        assert not outcome.permitted


def test_every_non_terminal_state_may_be_retired_by_a_human() -> None:
    for state_from in HealthState:
        if state_from is HealthState.RETIRED:
            continue
        outcome = classify_transition(state_from, HealthState.RETIRED)
        assert outcome.permitted
        assert outcome.requires_human


def test_a_disallowed_jump_is_refused() -> None:
    # HEALTHY cannot jump straight to SUSPENDED; degradation is stepwise from HEALTHY.
    assert not classify_transition(HealthState.HEALTHY, HealthState.SUSPENDED).permitted
