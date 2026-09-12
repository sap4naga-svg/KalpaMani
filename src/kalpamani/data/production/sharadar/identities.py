"""Spent run identities: the preliminary check, and what it is not.

ADR-0035 §3.1 makes an execution identity single-use and keeps the completed-slice
ledger an **owner-only private artifact** on the workstation; ADR-0036 §2.6 has the
task refuse *an input whose run identity is already spent*. Two guards therefore
exist, and this module keeps them distinct on purpose:

1. **The preliminary check** -- :class:`SpentIdentityRegistry`, answered from a
   ledger the caller holds. It is a courtesy refusal made **before** any provider
   or S3 operation, and it is only as current as the ledger it reads. An in-memory
   or file-backed answer **does not prevent concurrent reuse**: two processes could
   both read *unspent* and both proceed.
2. **The durable protection** -- the conditional, create-only ``PutObject`` of the
   first acquisition claim, whose key binds the run identity and the request
   ordinal (ADR-0019, ADR-0037). A second run under a spent identity finds that
   name occupied and halts with ``PUBLICATION_CONFLICT``, whatever the registry
   said. That is the guard concurrent reuse actually meets, and it is the
   **server's** decision, not this module's.

**Unavailable or ambiguous is a refusal.** A registry that raises, returns a
non-member, or answers ``UNAVAILABLE`` refuses the input as
``IDENTITY_STATUS_UNAVAILABLE``; the run does not proceed on the strength of the
durable guard alone, because a refusal that costs nothing is preferable to a
claim write that costs an S3 operation to be told the same thing.

**The write-only boundary is preserved.** No implementation here reads S3, lists
a prefix or probes an object: the only sources are what the caller hands in.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Protocol

from kalpamani.data.production.sharadar.keys import RUN_ID_RE


class SpentStatus(StrEnum):
    """What a registry knows about one run identity. Closed."""

    UNSPENT = "UNSPENT"
    SPENT = "SPENT"
    UNAVAILABLE = "UNAVAILABLE"


class SpentIdentityRegistry(Protocol):
    """One question: has this run identity been used? Answered, refused, or unknown."""

    def status(self, run_identity: str) -> SpentStatus:
        """The identity's status. Raising is treated as ``UNAVAILABLE``."""
        ...


class LedgerSpentIdentities:
    """A registry over the identities an owner ledger records as used.

    Built from an iterable the caller obtained under its own trust boundary -- on
    the workstation, the ADR-0023 private root; nowhere else in this cycle. Every
    identity must satisfy the run-identity grammar, so a malformed ledger refuses to
    become a registry rather than silently answering ``UNSPENT`` for everything.

    **This is the preliminary check only** (see the module docstring).
    """

    __slots__ = ("_spent",)

    def __init__(self, spent: Iterable[str]) -> None:
        """Bind the ledger's identities. Malformed entries refuse the registry."""
        identities: set[str] = set()
        for identity in spent:
            if type(identity) is not str or not RUN_ID_RE.match(identity):
                raise ValueError("a ledger identity does not match the run-identity grammar")
            identities.add(identity)
        self._spent = frozenset(identities)

    def __repr__(self) -> str:
        """The count only. **Never an identity.**"""
        return f"LedgerSpentIdentities(count={len(self._spent)})"

    def status(self, run_identity: str) -> SpentStatus:
        """``SPENT`` if the ledger records it, else ``UNSPENT``. Never ``UNAVAILABLE``."""
        if type(run_identity) is not str or not RUN_ID_RE.match(run_identity):
            return SpentStatus.UNAVAILABLE
        return SpentStatus.SPENT if run_identity in self._spent else SpentStatus.UNSPENT


class UnavailableSpentIdentities:
    """The registry a task holds when no ledger reaches it: every answer refuses.

    The task-side source of spent identities is an owner decision that has not
    been taken (the task cannot read the workstation ledger, and the acquisition
    actor cannot read S3). Until it is, a task answers ``UNAVAILABLE`` for every
    identity and therefore refuses every input -- honestly, rather than proceeding
    on an in-memory guess.
    """

    __slots__ = ()

    def status(self, run_identity: str) -> SpentStatus:
        """``UNAVAILABLE``, always."""
        return SpentStatus.UNAVAILABLE


def spent_status_of(registry: SpentIdentityRegistry, run_identity: str) -> SpentStatus:
    """The registry's answer, reduced to a closed member; anything else is ``UNAVAILABLE``."""
    try:
        answer = registry.status(run_identity)
    except Exception:
        return SpentStatus.UNAVAILABLE
    return answer if type(answer) is SpentStatus else SpentStatus.UNAVAILABLE


__all__ = [
    "LedgerSpentIdentities",
    "SpentIdentityRegistry",
    "SpentStatus",
    "UnavailableSpentIdentities",
    "spent_status_of",
]
