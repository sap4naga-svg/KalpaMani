"""The strategy health state machine (specification section 13).

The one asymmetry is the whole point, and it is enforced here rather than
trusted: **reducing or disabling new entries is automatic; restoring them is
not.** Degradation may advance one step at a time or jump straight to
``NEW_ENTRIES_DISABLED`` or ``SUSPENDED`` under a preapproved safety rule.
Recovery toward ``HEALTHY`` past a governed suspension is never automatic --
leaving ``SUSPENDED`` needs human authority, and ``RETIRED`` is terminal.

This module is a pure transition table. It runs no research, mutates no
parameter and takes no automatic recovery: a degradation produces a research
queue entry (recorded by the caller), never a reparameterisation. Automatic
reparameterisation in response to recent losses is curve-fitting at production
speed, and it is forbidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from kalpamani.strategies.brain.errors import BrainContractError
from kalpamani.strategies.brain.vocabulary import HealthState

#: Automatic degradation transitions. Each may be taken by automation under a
#: preapproved rule. Note the jumps: ``DEGRADED`` and either new-entry state may
#: go straight to ``SUSPENDED`` when a safety rule demands it.
_AUTOMATIC_DEGRADATIONS: Final[dict[HealthState, frozenset[HealthState]]] = {
    HealthState.HEALTHY: frozenset({HealthState.WATCH}),
    HealthState.WATCH: frozenset({HealthState.HEALTHY, HealthState.DEGRADED}),
    HealthState.DEGRADED: frozenset(
        {HealthState.NEW_ENTRIES_REDUCED, HealthState.NEW_ENTRIES_DISABLED, HealthState.SUSPENDED}
    ),
    HealthState.NEW_ENTRIES_REDUCED: frozenset(
        {HealthState.NEW_ENTRIES_DISABLED, HealthState.SUSPENDED}
    ),
    HealthState.NEW_ENTRIES_DISABLED: frozenset({HealthState.SUSPENDED}),
    HealthState.SUSPENDED: frozenset(),
    HealthState.RETIRED: frozenset(),
}

#: The states automation may recover *to* automatically, and only from the two
#: mild states. ``WATCH -> HEALTHY`` is the one automatic recovery permitted:
#: it restores nothing that was disabled. Everything past ``DEGRADED`` needs a
#: human. ``NEW_ENTRIES_REDUCED`` recovering to ``DEGRADED`` would be restoring a
#: reduction, so it is not automatic either.
_AUTOMATIC_RECOVERIES: Final[dict[HealthState, frozenset[HealthState]]] = {
    HealthState.WATCH: frozenset({HealthState.HEALTHY}),
}

#: Human-authority transitions: recovery past a governed suspension, and
#: retirement. These are not taken by automation, ever. Every non-terminal state
#: may additionally be retired by a human, folded in below.
_HUMAN_TRANSITIONS: Final[dict[HealthState, frozenset[HealthState]]] = {
    state: (targets | frozenset({HealthState.RETIRED}))
    for state, targets in {
        HealthState.HEALTHY: frozenset(),
        HealthState.WATCH: frozenset(),
        HealthState.DEGRADED: frozenset({HealthState.WATCH, HealthState.HEALTHY}),
        HealthState.NEW_ENTRIES_REDUCED: frozenset({HealthState.WATCH, HealthState.HEALTHY}),
        HealthState.NEW_ENTRIES_DISABLED: frozenset(
            {HealthState.NEW_ENTRIES_REDUCED, HealthState.WATCH, HealthState.HEALTHY}
        ),
        HealthState.SUSPENDED: frozenset(
            {
                HealthState.NEW_ENTRIES_DISABLED,
                HealthState.NEW_ENTRIES_REDUCED,
                HealthState.WATCH,
                HealthState.HEALTHY,
            }
        ),
    }.items()
}


@dataclass(frozen=True, slots=True, kw_only=True)
class TransitionOutcome:
    """Whether a transition is permitted, and by whom."""

    permitted: bool
    requires_human: bool
    reason: str


def classify_transition(from_state: HealthState, target: HealthState) -> TransitionOutcome:
    """Classify moving from ``from_state`` to ``target``. Never performs it.

    Returns whether the transition is permitted and, if so, whether it needs
    human authority. ``RETIRED`` is terminal; no transition leaves it.
    """
    if not isinstance(from_state, HealthState) or not isinstance(target, HealthState):
        raise BrainContractError("Health transitions are between HealthState members.")
    if from_state is target:
        return TransitionOutcome(permitted=True, requires_human=False, reason="no change")
    if from_state is HealthState.RETIRED:
        return TransitionOutcome(
            permitted=False, requires_human=False, reason="RETIRED is terminal"
        )
    if target in _AUTOMATIC_DEGRADATIONS.get(from_state, frozenset()):
        return TransitionOutcome(
            permitted=True, requires_human=False, reason="automatic degradation"
        )
    if target in _AUTOMATIC_RECOVERIES.get(from_state, frozenset()):
        return TransitionOutcome(
            permitted=True, requires_human=False, reason="automatic mild recovery"
        )
    if target in _HUMAN_TRANSITIONS.get(from_state, frozenset()):
        return TransitionOutcome(
            permitted=True, requires_human=True, reason="human authority required"
        )
    return TransitionOutcome(
        permitted=False, requires_human=False, reason="not a permitted transition"
    )


def is_automatic(from_state: HealthState, target: HealthState) -> bool:
    """Whether automation may take this transition without human authority."""
    outcome = classify_transition(from_state, target)
    return outcome.permitted and not outcome.requires_human


__all__ = ["TransitionOutcome", "classify_transition", "is_automatic"]
