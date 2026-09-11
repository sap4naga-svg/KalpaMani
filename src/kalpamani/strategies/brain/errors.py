"""The Brain's refusals.

Two kinds of failure exist in the Brain, and they are kept apart on purpose.

A **contract refusal** happens at construction: an unknown decision state, a
schema mismatch, a forbidden field, a free-text value where an identifier is
required, a naive instant. These raise :class:`BrainContractError` and never
produce a record, because a record built from a value the contract refuses is
a record whose meaning cannot be relied on (specification section 26).

A **decision refusal** happens inside the compiler and produces a
``CandidateIntent`` whose status is one of the closed blocked or rejected
states, with reason codes. It does not raise, because a refusal whose reason is
not recorded is indistinguishable from a crash.
"""

from __future__ import annotations

from kalpamani.common.errors import KalpaManiError


class BrainContractError(KalpaManiError):
    """A Brain record or input was refused at construction.

    Raised, never returned. The exception carries closed vocabulary members
    and identifiers only -- no bar values, no vendor row and no free text
    copied from an input -- so that a refusal cannot become a disclosure.
    """


__all__ = ["BrainContractError"]
