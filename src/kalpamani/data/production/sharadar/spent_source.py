"""A task-side spent-identity document: the **proposed** offline contract (ADR-0043 §3).

**Proposed, not accepted.** The task-side source of spent run identities is an owner
decision ADR-0036 §2.6 left open: the task cannot read the workstation ledger, and the
acquisition actor cannot read S3 (ADR-0019). Until that decision is taken, a task holds
:class:`~kalpamani.data.production.sharadar.identities.UnavailableSpentIdentities` and
refuses every input. This module changes none of that. It states one candidate
contract precisely enough to be tested, so the decision can be taken against a shape
rather than a sketch, and it is wired to nothing: no parameter name, no IAM statement
and no entrypoint reads it.

**The candidate.** A closed document the acquisition human actor materializes from the
owner ledger beside the input, delivered through the same channel as the input --
which would require the task bootstrap policy to name a fourth parameter, a widening
this cycle does not make -- and read by the task before the input is admitted:

```text
schema_version   1              contract_id   kalpamani-spent-identities/v1
actor            acquisition    spent         the ledger's run identities, sorted, distinct
issued_at        the ledger's time of reading      expires_at   <= issued_at + 24 h
spent_digest     SHA-256 over the canonical spent list -- integrity, not secrecy
```

**Failure behaviour is the accepted one.** A document that is missing, oversize,
malformed, stale, contradictory or wrongly digested does not become an ``UNSPENT``
answer for anything: the registry it would have produced is replaced by the accepted
``UnavailableSpentIdentities``, and the input is refused. This is still only the
preliminary check; the durable conditional run reservation (ADR-0038) remains the
guard against concurrent reuse and is untouched.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar.bindings import ParameterReader, decode_parameter_document
from kalpamani.data.production.sharadar.documents import exact_int, exact_str
from kalpamani.data.production.sharadar.identities import (
    LedgerSpentIdentities,
    SpentIdentityRegistry,
    SpentStatus,
    UnavailableSpentIdentities,
)
from kalpamani.data.production.sharadar.keys import RUN_ID_RE
from kalpamani.data.production.sharadar.vocabulary import (
    MAX_ADVANCED_PARAMETER_BYTES,
    ProductionActor,
)

SPENT_SCHEMA_VERSION: Final = 1
SPENT_CONTRACT_ID: Final = "kalpamani-spent-identities/v1"
#: The longest a spent-identity document may be valid for; the input's own ceiling.
MAX_SPENT_VALIDITY: Final = timedelta(hours=24)
#: The most identities one document may carry within the advanced-tier ceiling.
MAX_SPENT_IDENTITIES: Final = 128

_FIELDS: Final[frozenset[str]] = frozenset(
    {"schema_version", "contract_id", "actor", "issued_at", "expires_at", "spent", "spent_digest"}
)


class SpentDocumentDefect(StrEnum):
    """Why a spent-identity document was refused. Closed; carries no value."""

    NOT_AN_OBJECT = "NOT_AN_OBJECT"
    FIELD_UNKNOWN = "FIELD_UNKNOWN"
    FIELD_MISSING = "FIELD_MISSING"
    SCHEMA_VERSION = "SCHEMA_VERSION"
    CONTRACT_ID = "CONTRACT_ID"
    ACTOR = "ACTOR"
    TIMESTAMP_MALFORMED = "TIMESTAMP_MALFORMED"
    STALE = "STALE"
    VALIDITY_TOO_LONG = "VALIDITY_TOO_LONG"
    SPENT_MALFORMED = "SPENT_MALFORMED"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"


class SpentDocumentError(Exception):
    """A refusal built from one closed member and nothing else."""

    __slots__ = ("defect",)

    def __init__(self, defect: SpentDocumentDefect) -> None:
        """Carry the defect."""
        if type(defect) is not SpentDocumentDefect:
            raise TypeError("defect must be an exact SpentDocumentDefect member")
        self.defect = defect
        super().__init__(f"spent-identity document: {defect.value}")


def _refuse(defect: SpentDocumentDefect) -> SpentDocumentError:
    return SpentDocumentError(defect)


def spent_digest(spent: list[str]) -> str:
    """The SHA-256 over the canonical serialization of the sorted identity list."""
    return sha256_hex(canonical_bytes(sorted(spent)))


def _instant(raw: object) -> datetime:
    text = exact_str(raw)
    if text is None:
        raise _refuse(SpentDocumentDefect.TIMESTAMP_MALFORMED)
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise _refuse(SpentDocumentDefect.TIMESTAMP_MALFORMED) from None
    if value.tzinfo is None:
        raise _refuse(SpentDocumentDefect.TIMESTAMP_MALFORMED)
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class SpentIdentityDocument:
    """One validated document: the identities, and the window it is good for."""

    spent: frozenset[str]
    issued_at: datetime
    expires_at: datetime

    def __repr__(self) -> str:
        """The count only. **Never an identity.**"""
        return f"SpentIdentityDocument(count={len(self.spent)})"

    def registry(self) -> SpentIdentityRegistry:
        """The accepted ledger registry over these identities."""
        return LedgerSpentIdentities(sorted(self.spent))


def parse_spent_identity_document(document: object, *, now: datetime) -> SpentIdentityDocument:
    """Validate one spent-identity document against the proposed contract, or refuse."""
    if type(document) is not dict:
        raise _refuse(SpentDocumentDefect.NOT_AN_OBJECT)
    payload: dict[str, Any] = document
    names = set(payload)
    if names - _FIELDS:
        raise _refuse(SpentDocumentDefect.FIELD_UNKNOWN)
    if _FIELDS - names:
        raise _refuse(SpentDocumentDefect.FIELD_MISSING)
    if exact_int(payload["schema_version"]) != SPENT_SCHEMA_VERSION:
        raise _refuse(SpentDocumentDefect.SCHEMA_VERSION)
    if payload["contract_id"] != SPENT_CONTRACT_ID:
        raise _refuse(SpentDocumentDefect.CONTRACT_ID)
    if payload["actor"] != ProductionActor.ACQUISITION.value:
        raise _refuse(SpentDocumentDefect.ACTOR)
    issued_at = _instant(payload["issued_at"])
    expires_at = _instant(payload["expires_at"])
    if expires_at <= issued_at or expires_at - issued_at > MAX_SPENT_VALIDITY:
        raise _refuse(SpentDocumentDefect.VALIDITY_TOO_LONG)
    if type(now) is not datetime or now.tzinfo is None:
        raise _refuse(SpentDocumentDefect.TIMESTAMP_MALFORMED)
    if not issued_at <= now < expires_at:
        raise _refuse(SpentDocumentDefect.STALE)
    spent = payload["spent"]
    if type(spent) is not list or len(spent) > MAX_SPENT_IDENTITIES:
        raise _refuse(SpentDocumentDefect.SPENT_MALFORMED)
    identities: list[str] = []
    for identity in spent:
        if type(identity) is not str or not RUN_ID_RE.match(identity):
            raise _refuse(SpentDocumentDefect.SPENT_MALFORMED)
        identities.append(identity)
    if identities != sorted(set(identities)):
        raise _refuse(SpentDocumentDefect.SPENT_MALFORMED)
    if payload["spent_digest"] != spent_digest(identities):
        raise _refuse(SpentDocumentDefect.DIGEST_MISMATCH)
    return SpentIdentityDocument(
        spent=frozenset(identities), issued_at=issued_at, expires_at=expires_at
    )


def build_spent_identity_document(
    spent: list[str], *, issued_at: datetime, expires_at: datetime
) -> dict[str, Any]:
    """The document the writer side would materialize. Digested, sorted, closed."""
    identities = sorted(set(spent))
    document = {
        "schema_version": SPENT_SCHEMA_VERSION,
        "contract_id": SPENT_CONTRACT_ID,
        "actor": ProductionActor.ACQUISITION.value,
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "spent": identities,
        "spent_digest": spent_digest(identities),
    }
    parse_spent_identity_document(document, now=issued_at)
    return document


def load_spent_identities(
    *, reader: ParameterReader, parameter: str, now: Callable[[], datetime]
) -> SpentIdentityRegistry:
    """The registry a task would hold: the document's, or the accepted unavailable one.

    **Wired to nothing.** No entrypoint calls this, no parameter name is compiled for
    it, and the task bootstrap policy names no parameter it could read. It exists so
    the failure behaviour -- every defect becomes ``UNAVAILABLE``, never ``UNSPENT``
    -- is a tested property of the proposed contract rather than an intention.
    """
    try:
        raw = reader.read_parameter(parameter)
        document = decode_parameter_document(raw, max_bytes=MAX_ADVANCED_PARAMETER_BYTES)
        return parse_spent_identity_document(document, now=now()).registry()
    except Exception:
        return UnavailableSpentIdentities()


__all__ = [
    "MAX_SPENT_IDENTITIES",
    "MAX_SPENT_VALIDITY",
    "SPENT_CONTRACT_ID",
    "SPENT_SCHEMA_VERSION",
    "SpentDocumentDefect",
    "SpentDocumentError",
    "SpentIdentityDocument",
    "SpentStatus",
    "build_spent_identity_document",
    "load_spent_identities",
    "parse_spent_identity_document",
    "spent_digest",
]
