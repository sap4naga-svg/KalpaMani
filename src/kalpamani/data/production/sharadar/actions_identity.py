"""The schema-bound canonical full-row actions event identity (ADR-0053 §12).

**The vendor actions table carries no event identity, so the row is the event.** The
qualification evidence recorded under D-20 (44 and 83 rows per year window sharing
``ticker``, ``date`` and ``action`` with differing content) shows that the coarse key
``(security, date, action)`` is not an identity of anything the vendor delivers. The
accepted contract ``sharadar-actions-event-identity/v1`` therefore binds every accepted
typed field of the governed actions schema, in documented field order, into one
canonical serialization and takes its SHA-256 as the event identity. Two rows that
share ticker, date and action remain distinct when any other governed field differs;
**exact duplicate full rows are refused, never silently deduplicated**; a digest
collision -- two different canonical rows with one identity -- is refused as a
collision, never merged.

**The seven fields are derived, not typed.** The governed schema is the accepted
Route-A actions digest, and it is the accepted parser's order-sensitive digest of
exactly ``date, action, ticker, name, value, contraticker, contraname``; a test holds
the two equal, so the field list here cannot drift from the digest it claims to serve.
A row under any other header is refused as ungoverned.

**Normalization is typed and lossless.** ``date`` is an ISO calendar date, re-rendered
from the parsed value; ``value`` must be a decimal literal and is carried as the exact
delivered text (no rescaling, no binary float); every other field is the exact
delivered text, untrimmed and unfolded; an absent value is ``null``, and an absent
``date``, ``action`` or ``ticker`` is refused because the accepted parser requires them.

This is the accepted implementation the §12.7 tests specified against a reference
implementation that lived only in the test module; that reference is promoted here and
the tests now import this module. Nothing here reads a payload from anywhere but its
caller, and nothing here reaches a provider, a store or a credential.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

from kalpamani.data.contracts.canonical import canonical_bytes
from kalpamani.data.qualify.sharadar.parser import schema_digest_of

#: The accepted contract identifier. Bound into every canonical row.
ACTIONS_IDENTITY_CONTRACT_ID: Final = "sharadar-actions-event-identity/v1"

#: The governed actions schema, in accepted order (ADR-0053 §12.3).
ACTIONS_IDENTITY_FIELDS: Final = (
    "date",
    "action",
    "ticker",
    "name",
    "value",
    "contraticker",
    "contraname",
)
#: The accepted Route-A actions schema digest: the parser's order-sensitive digest of
#: exactly the seven fields above. Held equal to ``schema_digest_of(ACTIONS_IDENTITY_FIELDS)``
#: by a test, and asserted here at import so the two cannot drift silently.
ACCEPTED_ACTIONS_SCHEMA_DIGEST: Final = (
    "f2de54a58d32d33efb87647b1b62e6768175cb720bad6e7a2991fbba23a1fa72"
)
assert schema_digest_of(ACTIONS_IDENTITY_FIELDS) == ACCEPTED_ACTIONS_SCHEMA_DIGEST

#: The fields the accepted parser requires on every actions row. An absent value in
#: one of these is not an event; it is a malformed row.
_REQUIRED: Final[frozenset[str]] = frozenset({"date", "action", "ticker"})


class ActionsIdentityDefect(StrEnum):
    """Why a row or a row set was refused. Closed; never a value, never a row."""

    ACTIONS_SCHEMA_NOT_GOVERNED = "ACTIONS_SCHEMA_NOT_GOVERNED"
    ACTIONS_REQUIRED_FIELD_NULL = "ACTIONS_REQUIRED_FIELD_NULL"
    ACTIONS_DATE_MALFORMED = "ACTIONS_DATE_MALFORMED"
    ACTIONS_VALUE_NOT_DECIMAL = "ACTIONS_VALUE_NOT_DECIMAL"
    ACTIONS_DUPLICATE_EVENT = "ACTIONS_DUPLICATE_EVENT"
    ACTIONS_IDENTITY_COLLISION = "ACTIONS_IDENTITY_COLLISION"


class ActionsIdentityRefusalError(Exception):
    """One closed defect, raised ``from None``. The message is the token, nothing more."""

    __slots__ = ("defect",)

    def __init__(self, defect: ActionsIdentityDefect) -> None:
        if type(defect) is not ActionsIdentityDefect:
            raise TypeError("defect must be an exact ActionsIdentityDefect member")
        self.defect = defect
        super().__init__(defect.value)


def _refuse(defect: ActionsIdentityDefect) -> ActionsIdentityRefusalError:
    return ActionsIdentityRefusalError(defect)


def normalize_field(name: str, value: str | None) -> str | None:
    """The typed normalization of §12.3: date, decimal literal, exact strings, null."""
    if value is None:
        if name in _REQUIRED:
            raise _refuse(ActionsIdentityDefect.ACTIONS_REQUIRED_FIELD_NULL) from None
        return None
    if type(value) is not str:
        raise _refuse(ActionsIdentityDefect.ACTIONS_SCHEMA_NOT_GOVERNED) from None
    if name == "date":
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            raise _refuse(ActionsIdentityDefect.ACTIONS_DATE_MALFORMED) from None
    if name == "value":
        try:
            Decimal(value)
        except InvalidOperation:
            raise _refuse(ActionsIdentityDefect.ACTIONS_VALUE_NOT_DECIMAL) from None
        return value  # the exact delivered literal; no rescaling, no float
    return value  # exact delivered text; no trimming, folding or Unicode normalization


def canonical_row(row: dict[str, str | None], *, schema_digest: str) -> bytes:
    """§12.4(1): a list of pairs in accepted order, bound to the contract and the schema.

    Raises:
        ActionsIdentityRefusalError: ``ACTIONS_SCHEMA_NOT_GOVERNED`` for a schema digest
            other than the accepted one or a row not carrying exactly the seven fields;
            the typed refusals of :func:`normalize_field`.
    """
    if schema_digest != ACCEPTED_ACTIONS_SCHEMA_DIGEST or type(row) is not dict:
        raise _refuse(ActionsIdentityDefect.ACTIONS_SCHEMA_NOT_GOVERNED) from None
    if set(row) != set(ACTIONS_IDENTITY_FIELDS):
        raise _refuse(ActionsIdentityDefect.ACTIONS_SCHEMA_NOT_GOVERNED) from None
    fields = [[name, normalize_field(name, row[name])] for name in ACTIONS_IDENTITY_FIELDS]
    return canonical_bytes(
        {"contract": ACTIONS_IDENTITY_CONTRACT_ID, "schema": schema_digest, "fields": fields}
    )


def event_identity(row: dict[str, str | None], *, schema_digest: str) -> str:
    """§12.4(2): the SHA-256 of the canonical row, as 64 lowercase hex characters."""
    return hashlib.sha256(canonical_row(row, schema_digest=schema_digest)).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class AdmittedEvent:
    """One admitted event: its identity and the canonical bytes that produced it."""

    identity: str
    canonical: bytes

    def __repr__(self) -> str:
        """Nothing: the canonical bytes carry a vendor row."""
        return "AdmittedEvent()"


class EventAdmission:
    """§12.4(4)-(7): admit events one at a time; refuse exact duplicates and collisions.

    Scoped by the caller -- one instance per acquisition run and dataset group, so a
    row re-observed by a *later* run is that run's own admission and never a duplicate
    of an earlier one.
    """

    __slots__ = ("_seen",)

    def __init__(self) -> None:
        self._seen: dict[str, bytes] = {}

    def admit(self, row: dict[str, str | None], *, schema_digest: str) -> AdmittedEvent:
        """Admit one row, or refuse it.

        Raises:
            ActionsIdentityRefusalError: ``ACTIONS_DUPLICATE_EVENT`` for an exact repeat
                of an admitted canonical row; ``ACTIONS_IDENTITY_COLLISION`` for a
                different canonical row under an already-admitted identity; the
                canonicalization refusals.
        """
        canonical = canonical_row(row, schema_digest=schema_digest)
        identity = hashlib.sha256(canonical).hexdigest()
        previous = self._seen.get(identity)
        if previous is not None:
            if previous == canonical:
                raise _refuse(ActionsIdentityDefect.ACTIONS_DUPLICATE_EVENT) from None
            raise _refuse(ActionsIdentityDefect.ACTIONS_IDENTITY_COLLISION) from None
        self._seen[identity] = canonical
        return AdmittedEvent(identity=identity, canonical=canonical)

    @property
    def admitted_count(self) -> int:
        """How many distinct events this admission has admitted."""
        return len(self._seen)


def admit_events(
    rows: list[dict[str, str | None]], *, schema_digest: str
) -> tuple[tuple[str, bytes], ...]:
    """Admit a whole row set at once, ordered by canonical bytes. A convenience over
    :class:`EventAdmission` for callers that hold the group in memory."""
    admission = EventAdmission()
    admitted = [admission.admit(row, schema_digest=schema_digest) for row in rows]
    return tuple(sorted(((e.identity, e.canonical) for e in admitted), key=lambda item: item[1]))


__all__ = [
    "ACCEPTED_ACTIONS_SCHEMA_DIGEST",
    "ACTIONS_IDENTITY_CONTRACT_ID",
    "ACTIONS_IDENTITY_FIELDS",
    "ActionsIdentityDefect",
    "ActionsIdentityRefusalError",
    "AdmittedEvent",
    "EventAdmission",
    "admit_events",
    "canonical_row",
    "event_identity",
    "normalize_field",
]
