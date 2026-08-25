"""Trade lifecycle states and validated transitions (ADR-0004 §6).

This is a safety mechanism, not documentation. Transitions are explicit and
checked; an undeclared transition raises rather than being permitted "because
the code got there somehow".

Two rules do most of the work:

* ``FAILED`` and ``RECONCILED`` are **terminal**. Nothing leaves them.
* A state this version of the code does not recognise is treated as
  **contradictory** and fails closed. It is never coerced to the nearest known
  state -- silently downgrading an unknown state is how a system resumes acting
  on a position it does not understand.
"""

from __future__ import annotations

from enum import StrEnum

from kalpamani.common.errors import SafetyViolationError


class LifecycleError(SafetyViolationError):
    """An illegal, unknown or contradictory lifecycle transition was attempted."""


class TradeState(StrEnum):
    """States a Phase 2 trade lifecycle may occupy."""

    CREATED = "CREATED"
    AUTHORIZED = "AUTHORIZED"
    ENTRY_SUBMITTED = "ENTRY_SUBMITTED"
    ENTRY_ACKNOWLEDGED = "ENTRY_ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    PROTECTION_SUBMITTED = "PROTECTION_SUBMITTED"
    PROTECTED = "PROTECTED"
    RECOVERING = "RECOVERING"
    EXIT_REQUESTED = "EXIT_REQUESTED"
    EXIT_SUBMITTED = "EXIT_SUBMITTED"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"
    FAILED = "FAILED"

    @classmethod
    def parse(cls, raw: str) -> TradeState:
        """Parse a persisted state name, failing closed on anything unrecognised.

        Raises:
            LifecycleError: if ``raw`` is not a known state. Durable state
                written by a newer or corrupted version must halt this process,
                not be approximated.
        """
        for member in cls:
            if member.value == raw:
                return member
        raise LifecycleError(
            f"Unknown lifecycle state {raw!r}. Refusing to coerce it to a known state: an "
            "unrecognised state means this process cannot reason about the position."
        )


#: States from which the lifecycle can never move again.
TERMINAL_STATES: frozenset[TradeState] = frozenset({TradeState.RECONCILED, TradeState.FAILED})

#: States in which a broker position may exist and therefore must be protected
#: or reconciled before anything else happens.
POSITION_BEARING_STATES: frozenset[TradeState] = frozenset(
    {
        TradeState.PARTIALLY_FILLED,
        TradeState.FILLED,
        TradeState.PROTECTION_SUBMITTED,
        TradeState.PROTECTED,
        TradeState.EXIT_REQUESTED,
        TradeState.EXIT_SUBMITTED,
    }
)

#: States in which a fill has occurred but protection is not yet confirmed.
#: Lingering here is the highest-severity Phase 2 condition: UNPROTECTED POSITION.
UNPROTECTED_STATES: frozenset[TradeState] = frozenset(
    {TradeState.PARTIALLY_FILLED, TradeState.FILLED, TradeState.PROTECTION_SUBMITTED}
)

_S = TradeState

#: The complete transition table. Anything not listed here is illegal.
#: Every non-terminal state may go to FAILED -- failing closed is always legal.
_ALLOWED: dict[TradeState, frozenset[TradeState]] = {
    _S.CREATED: frozenset({_S.AUTHORIZED, _S.FAILED}),
    _S.AUTHORIZED: frozenset({_S.ENTRY_SUBMITTED, _S.RECOVERING, _S.FAILED}),
    _S.ENTRY_SUBMITTED: frozenset({_S.ENTRY_ACKNOWLEDGED, _S.RECOVERING, _S.FAILED}),
    _S.ENTRY_ACKNOWLEDGED: frozenset(
        {_S.PARTIALLY_FILLED, _S.FILLED, _S.CLOSED, _S.RECOVERING, _S.FAILED}
    ),
    _S.PARTIALLY_FILLED: frozenset(
        {_S.PARTIALLY_FILLED, _S.FILLED, _S.PROTECTION_SUBMITTED, _S.RECOVERING, _S.FAILED}
    ),
    _S.FILLED: frozenset({_S.PROTECTION_SUBMITTED, _S.RECOVERING, _S.FAILED}),
    _S.PROTECTION_SUBMITTED: frozenset({_S.PROTECTED, _S.RECOVERING, _S.FAILED}),
    _S.PROTECTED: frozenset({_S.EXIT_REQUESTED, _S.RECOVERING, _S.FAILED}),
    # RECOVERING may only be left after successful broker reconciliation, which
    # lands it back on whichever position-bearing state the broker confirms.
    _S.RECOVERING: frozenset(
        {
            _S.AUTHORIZED,
            _S.ENTRY_SUBMITTED,
            _S.ENTRY_ACKNOWLEDGED,
            _S.PARTIALLY_FILLED,
            _S.FILLED,
            _S.PROTECTION_SUBMITTED,
            _S.PROTECTED,
            _S.EXIT_REQUESTED,
            _S.EXIT_SUBMITTED,
            _S.CLOSED,
            _S.RECONCILED,
            _S.FAILED,
        }
    ),
    _S.EXIT_REQUESTED: frozenset({_S.EXIT_SUBMITTED, _S.RECOVERING, _S.FAILED}),
    _S.EXIT_SUBMITTED: frozenset({_S.CLOSED, _S.RECOVERING, _S.FAILED}),
    _S.CLOSED: frozenset({_S.RECONCILED, _S.RECOVERING, _S.FAILED}),
    # Terminal.
    _S.RECONCILED: frozenset(),
    _S.FAILED: frozenset(),
}


def allowed_transitions(state: TradeState) -> frozenset[TradeState]:
    """States reachable in one step from ``state``."""
    return _ALLOWED[state]


def is_terminal(state: TradeState) -> bool:
    return state in TERMINAL_STATES


def requires_protection(state: TradeState) -> bool:
    """Whether a position may exist that is not yet confirmed protected."""
    return state in UNPROTECTED_STATES


def may_hold_position(state: TradeState) -> bool:
    """Whether a broker position may exist in this state."""
    return state in POSITION_BEARING_STATES


def validate_transition(current: TradeState, target: TradeState) -> None:
    """Assert that ``current -> target`` is legal, or fail closed.

    Raises:
        LifecycleError: if the transition is undeclared, or if ``current`` is
            terminal. Terminal means terminal: a RECONCILED trade that starts
            moving again is a contradiction, not a recovery.
    """
    if current in TERMINAL_STATES:
        raise LifecycleError(
            f"{current.value} is terminal; refusing transition to {target.value}. A terminal "
            "lifecycle that resumes indicates contradictory state, not progress."
        )
    permitted = _ALLOWED[current]
    if target not in permitted:
        allowed = ", ".join(sorted(s.value for s in permitted)) or "(none)"
        raise LifecycleError(
            f"Illegal lifecycle transition {current.value} -> {target.value}. "
            f"Permitted from {current.value}: {allowed}."
        )


def transition(current: TradeState, target: TradeState) -> TradeState:
    """Validate and perform a transition, returning the new state."""
    validate_transition(current, target)
    return target


__all__ = [
    "POSITION_BEARING_STATES",
    "TERMINAL_STATES",
    "UNPROTECTED_STATES",
    "LifecycleError",
    "TradeState",
    "allowed_transitions",
    "is_terminal",
    "may_hold_position",
    "requires_protection",
    "transition",
    "validate_transition",
]
