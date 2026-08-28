"""Bronze publication onto a :class:`~kalpamani.data.objectstore.ResearchObjectStore`.

**Provider-neutral, and it stays that way.** This module receives bytes a caller
already holds and the record of how they were acquired. It has no HTTP client, no
credential, no provider knowledge and no vendor vocabulary -- which is why a
provider adapter can be built on top of it without any of that leaking down, and
why a static test refuses this file if a vendor name ever appears in it.

It is the object-store counterpart of :mod:`kalpamani.data.ingest.bronze`, which
publishes to a local filesystem. The layouts are deliberately parallel and the
invariants are the same: a payload is stored byte for byte exactly as received,
named by the SHA-256 of its contents, and never overwritten.

**Three objects per acquisition, and both the namespaces and the order matter.**

.. code-block:: text

    licensed/bronze/_acquisition_claims/<digest>/<run-id>.json   <- GLOBAL, provider-independent
    licensed/bronze/<provider>/<dataset>/objects/sha256/<digest>
    licensed/bronze/<provider>/<dataset>/acquisitions/<digest>/<run-id>.json

**The claim exists because acquisition identity is global.** The Bronze contract
says ``(payload digest, ingestion run id)`` names **one** retrieval -- not one per
provider, and not one per dataset. The filesystem writer enforces that by
scanning every partition for the identity before writing. This store has no
listing surface, deliberately: a producer that could enumerate the store could
enumerate what a vendor sent. So the global fact is given a **global name**
instead, in a namespace no provider can occupy, and the store's own append-only
refusal does the enforcing. Two different providers claiming one
``(digest, run id)`` write different bytes to the same claim name, and the second
is refused.

**The claim is a reservation, not completion evidence.** It is written *first*,
before the payload, so a contradictory second claim is refused before any bytes
land. The provider-scoped acquisition record is written *last*, and its existence
is what marks the acquisition complete.

That ordering is forced. The filesystem writer marks completion with a durable
``PENDING`` record that is later replaced by ``COMPLETE``, and **that two-phase
pattern is structurally unavailable here**, because an append-only
``put_if_absent`` store has no *replace* -- a ``PENDING`` record could never be
advanced. Record-last is what works, and it is the safer of the two orderings: an
interrupted run can leave a claim or a payload that nothing completes, which is
detectable and inert, but it can never leave a record naming a payload that does
not exist. Re-running the same identity finishes it, because every write on the
path is idempotent for identical content.

**Everything published here is LICENSED, and nothing else is publishable at all.**
:meth:`~kalpamani.data.objectstore.ObjectKey.licensed` is the store's only
constructor in this slice. The claim and the acquisition record are licensed too
-- not because either could reconstruct a vendor row, but because clearing an
artifact to a store that *survives* a vendor deletion needs a structured,
durably-bound attestation, and this slice builds none. Deferring costs nothing:
they sit inside the deletion surface, which is the conservative side.

**Durable metadata carries no free text, and every field is checked against its
own contract rather than a shape.** :func:`acquisition_record` emits a closed
field set. Tokens and identifiers are matched by grammar; the two fields that
carry meaning beyond their shape are **parsed**. A requested range must name real
calendar dates that do not run backwards, or be one of :data:`NAMED_RANGES`; a
retrieval instant must parse, be offset-aware UTC, and be the canonical spelling
of itself. A pattern that counts digits admits ``2026-13-45`` and every inverted
range there is, and would then have recorded either as a description of what was
fetched.

Types are checked with ``type(...) is``, so a ``bool`` cannot pass as an ``int``
and a ``StrEnum`` member -- itself a ``str`` subclass -- cannot pass as the
classification string. What is written is bytes on a disk: it must *be* the
value, not something that currently compares equal to it.

A substring blocklist cannot prove the absence of an arbitrary credential, query
string, bucket or cloud identifier; a closed field set whose members are parsed
can. ``RetrievalMetadata.notes`` belongs to the A1 filesystem writer and **is
never read on this path**, so there is no field here for human text to travel in.

**No provider row is parsed before publication.** A payload is opaque bytes. A
future provider response that is malformed, truncated or in an unexpected format
is still preservable as Bronze evidence, which is exactly when the evidence
matters most.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.errors import ProviderMetadataDisclosureError
from kalpamani.data.contracts.vocabulary import AcquisitionMode, DataClassification
from kalpamani.data.ingest.bronze import RetrievalMetadata
from kalpamani.data.objectstore import (
    ObjectKey,
    PutOutcome,
    ResearchObjectStore,
    immutable_payload,
)

#: The namespace holding the global acquisition claims. A **reserved segment
#: inside** ``bronze/``, not a sibling of it, for two reasons that pull the same
#: way.
#:
#: **Collision is refused by grammar.** It begins with an underscore, and
#: :func:`~kalpamani.data.contracts.paths.safe_component` requires an externally
#: supplied identifier to start with a letter or a digit -- so no provider can
#: ever be named ``_acquisition_claims``. The reservation holds without anyone
#: having to remember it.
#:
#: **Deletion already covers it.** The vendor-data deletion runbook deletes every
#: object under ``bronze/``, so claims are inside the 30-day surface with no
#: change to the runbook, ADR-0007's layout or the deletion role's permissions.
#: A new top-level prefix would have been an "unexpected prefix" finding in that
#: runbook's Step 3, and reconciling it would have meant editing the deletion
#: procedure to accommodate a storage detail -- the wrong direction of travel.
CLAIM_NAMESPACE: Final = "_acquisition_claims"

#: The Bronze namespace. Provider-scoped, so each vendor's deletion surface stays
#: separable.
BRONZE_NAMESPACE: Final = "bronze"

#: The field set an acquisition record may carry. An exact allowlist, not a
#: forbidden list: a forbidden list has to anticipate the field nobody thought of,
#: and an allowlist refuses it by default.
ACQUISITION_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "byte_count",
        "classification",
        "content_sha256",
        "acquisition_mode",
        "dataset",
        "ingestion_run_id",
        "provider",
        "requested_range",
        "retrieved_at",
        "source_schema_version",
    }
)

#: The three permitted durable acquisition-mode tokens, as plain strings.
#:
#: Derived from the vocabulary rather than restated, so a fourth member could not
#: appear in one place and not the other -- and so this list cannot silently
#: admit a token the enum does not define.
_ACQUISITION_MODE_TOKENS: Final[frozenset[str]] = frozenset(
    str(member.value) for member in AcquisitionMode
)

#: The field set a global acquisition claim may carry. Narrower still: a claim
#: exists to make one identity unique, so it holds only what that identity binds.
CLAIM_FIELDS: Final[frozenset[str]] = frozenset(
    {"content_sha256", "dataset", "ingestion_run_id", "provider"}
)

#: A provider or dataset token. Lowercase, no spaces, no punctuation beyond dash
#: and underscore -- a grammar that cannot spell a URL, a query string, an ARN or
#: a sentence.
_TOKEN: Final = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

#: A schema version or ingestion-run identifier.
_IDENTIFIER: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: A content address. 64 lowercase hex characters, and nothing else.
_DIGEST: Final = re.compile(r"^[0-9a-f]{64}$")

#: The shape of a range that names dates, checked before either date is parsed.
_DATE_RANGE: Final = re.compile(r"^(\d{4}-\d{2}-\d{2})/(\d{4}-\d{2}-\d{2})$")

#: Range tokens admitted for a dataset that has no time axis. A closed vocabulary
#: of one, held here in the neutral layer so a provider cannot invent a second.
#: An empty range would read as an *unknown* window rather than an absent one.
NAMED_RANGES: Final[frozenset[str]] = frozenset({"SNAPSHOT"})

#: Fields validated by pattern alone. Everything else below gets parsed, because a
#: pattern that admits ``2026-13-45`` is a pattern that has not checked the value.
_FIELD_GRAMMAR: Final[dict[str, re.Pattern[str]]] = {
    "provider": _TOKEN,
    "dataset": _TOKEN,
    "source_schema_version": _IDENTIFIER,
    "ingestion_run_id": _IDENTIFIER,
    "content_sha256": _DIGEST,
}


def _requested_range_defect(value: str) -> str | None:
    """Why ``value`` is not a usable requested range, or ``None``.

    Parsed, not merely matched. ``2026-13-45/2026-02-30`` satisfies any pattern
    that counts digits, and an inverted range satisfies every pattern there is --
    both would then be recorded as a description of what was fetched.
    """
    if value in NAMED_RANGES:
        return None
    matched = _DATE_RANGE.match(value)
    if matched is None:
        return "is neither an explicit YYYY-MM-DD/YYYY-MM-DD range nor a named range token"
    try:
        start = date.fromisoformat(matched.group(1))
        end = date.fromisoformat(matched.group(2))
    except ValueError:
        return "names a date that does not exist on the calendar"
    if start > end:
        return "starts after it ends"
    return None


def _retrieved_at_defect(value: str) -> str | None:
    """Why ``value`` is not a canonical UTC instant, or ``None``.

    Three separate requirements, and each has been a real defect somewhere: it
    must *parse*; it must be timezone-aware **and** UTC, because a naive or
    offset instant recorded as UTC moves an acquisition in time; and it must be
    the canonical spelling, so one instant has one rendering and therefore one
    content hash.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return "is not a parseable ISO-8601 instant"
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return "is not an offset-aware UTC instant"
    if parsed.isoformat() != value:
        return "is not the canonical spelling of the instant it names"
    return None


#: Substrings that must never appear in a recorded acquisition.
#:
#: **Secondary, and no longer load-bearing.** The per-field grammars above admit
#: no character any of these needs, so this scan is unreachable for a value that
#: passed them. It is kept as defence in depth and as a legible statement of what
#: is being kept out -- not as the control. A blocklist cannot prove an arbitrary
#: credential is absent; a grammar that admits neither ``:`` nor ``/`` nor a space
#: can.
FORBIDDEN_RECORD_SUBSTRINGS: Final[tuple[str, ...]] = (
    "api_key",
    "apikey",
    "api-key",
    "://",
    "arn:aws:",
    "authorization",
    "bearer ",
    "aws_access",
    "aws_secret",
    "secret_key",
    "session_token",
    "password",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class BronzePublication:
    """One payload published, and the acquisition that produced this call.

    ``payload_written`` is ``False`` when the identical payload was already
    stored. That is an ordinary idempotent re-publication -- the same bytes
    arriving twice -- and it is reported separately from ``claim_written`` and
    ``acquisition_written`` so a caller can tell "already had these bytes" from
    "already recorded this exact retrieval".

    **The acquisition mode is not repeated here.** It is on ``retrieval``, which
    this already carries, and a second copy would be a second place to state one
    fact -- with no way to resolve the case where they disagree (ADR-0013).
    """

    claim_key: ObjectKey
    payload_key: ObjectKey
    acquisition_key: ObjectKey
    content_sha256: str
    byte_count: int
    claim_written: bool
    payload_written: bool
    acquisition_written: bool
    retrieval: RetrievalMetadata


def acquisition_claim_key(*, payload_digest: str, run_id: str, claim: bytes) -> ObjectKey:
    """The **global** logical key of one acquisition identity. Always LICENSED.

    Provider-independent by construction: nothing about the provider or the
    dataset appears in the name, so two providers claiming one
    ``(digest, run id)`` land on the same name and the second is refused.

    **Provider attribution is inside the object, not in the name, and the
    consequence is stated rather than glossed.** The deletion role can list and
    delete by name; it cannot ``GetObject``. So claims are deletable **wholesale**
    with the rest of ``bronze/`` -- which is what a termination requires -- but they
    are **not** independently attributable to one provider by that role. A
    hypothetical single-provider purge could delete ``bronze/<provider>/`` by
    prefix and would have to treat the claim namespace as all-or-nothing. This
    slice does not claim provider-separated deletion for claims, because the
    layout does not provide it.
    """
    return ObjectKey.licensed(
        BRONZE_NAMESPACE, CLAIM_NAMESPACE, payload_digest, f"{run_id}.json", payload=claim
    )


def acquisition_claim(*, retrieval: RetrievalMetadata, content_sha256: str) -> dict[str, Any]:
    """What one acquisition identity binds: a digest, a run, a provider, a dataset.

    Deliberately minimal. A claim is not a receipt -- it is the evidence that this
    ``(digest, run id)`` belongs to this provider and dataset and to no other, so
    it holds exactly the four values that statement is about. Any field that could
    legitimately differ between two writes of the same identity would turn a
    genuine contradiction into an ordinary-looking mismatch.
    """
    return {
        "content_sha256": content_sha256,
        "ingestion_run_id": retrieval.ingestion_run_id,
        "provider": retrieval.provider,
        "dataset": retrieval.dataset,
    }


def bronze_payload_key(*, retrieval: RetrievalMetadata, payload: bytes) -> ObjectKey:
    """The deterministic logical key of one Bronze payload. Always LICENSED.

    **The one genuinely content-addressed namespace in this system**: the digest
    is in the path, so identical bytes land in one place and changed bytes land in
    another.

    Scoped under ``<provider>/<dataset>`` rather than global. Cross-provider
    de-duplication would be tempting -- identical bytes are identical bytes -- but
    it would merge two vendors' payloads into one object under one licence, and a
    deletion obligation arriving for one vendor would then have to destroy the
    other's evidence or fail to be honoured. Acquisition *identity* is global;
    payload *storage* is per-provider, and the two namespaces above are how both
    are true at once.
    """
    digest = sha256_hex(payload)
    return ObjectKey.licensed(
        BRONZE_NAMESPACE,
        retrieval.provider,
        retrieval.dataset,
        "objects",
        "sha256",
        digest,
        payload=payload,
    )


def bronze_acquisition_key(
    *, retrieval: RetrievalMetadata, payload_digest: str, record: bytes
) -> ObjectKey:
    """The deterministic logical key of one acquisition record. Always LICENSED.

    Provider-scoped, and named by ``(digest, run id)`` rather than by its own
    content -- so re-recording that identity with different metadata lands on an
    occupied name and is refused. One retrieval happened once; restating it later
    would make the record describe an event that did not occur.
    """
    return ObjectKey.licensed(
        BRONZE_NAMESPACE,
        retrieval.provider,
        retrieval.dataset,
        "acquisitions",
        payload_digest,
        f"{retrieval.ingestion_run_id}.json",
        payload=record,
    )


def acquisition_record(
    *,
    retrieval: RetrievalMetadata,
    content_sha256: str,
    byte_count: int,
) -> dict[str, Any]:
    """The recorded account of one retrieval. A closed field set, nothing free-form.

    ``acquisition_mode`` states what the retrieval **was** -- a bounded provider
    validation, a historical production load, or an incremental refresh -- and it
    is recorded beside the payload rather than only on the run that produced it.
    It is read from ``retrieval`` and there is **no parameter for it**, because a
    record whose mode could differ from its retrieval's would be two claims about
    one act.

    The value serialised is the member's plain ``str`` token, not the member: a
    record is bytes on a disk, and a ``StrEnum`` is a ``str`` *subclass* whose
    identity is not what a later reader would get back.

    ``RetrievalMetadata.notes`` is **not** read. It belongs to the A1 filesystem
    writer; on this path there is no field for human text, which is why no filter
    is needed to keep human text out.
    """
    return {
        "provider": retrieval.provider,
        "dataset": retrieval.dataset,
        "requested_range": retrieval.requested_range,
        "retrieved_at": retrieval.retrieved_at.isoformat(),
        "source_schema_version": retrieval.source_schema_version,
        "ingestion_run_id": retrieval.ingestion_run_id,
        "content_sha256": content_sha256,
        "byte_count": byte_count,
        "acquisition_mode": str(retrieval.acquisition_mode.value),
        "classification": DataClassification.LICENSED.value,
    }


def require_recordable(record: dict[str, Any], *, allowed: frozenset[str]) -> None:
    """Refuse a durable record whose fields are not exactly what they must be.

    Every field is checked against **its own** contract: a lowercase token, a
    closed range grammar, a UTC instant, a 64-hex digest, a non-negative ``int``,
    an exact ``bool``, the LICENSED classification. Type is checked with
    ``type(...) is`` rather than ``isinstance``, so a ``bool`` cannot pass as an
    ``int`` and a ``str`` subclass cannot pass as a ``str``.

    Raises:
        ProviderMetadataDisclosureError: naming the field, **never the value**. An
            error that quoted the disclosure would republish it.
    """
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise ProviderMetadataDisclosureError(
            f"A durable record may only carry {sorted(allowed)}. Unexpected field(s): "
            f"{unexpected}. The field set is an allowlist because a forbidden list has to "
            "anticipate the field nobody thought of."
        )
    missing = sorted(allowed - set(record))
    if missing:
        raise ProviderMetadataDisclosureError(
            f"A durable record is incomplete; missing field(s): {missing}."
        )

    for field_name, value in sorted(record.items()):
        grammar = _FIELD_GRAMMAR.get(field_name)
        if grammar is not None:
            if type(value) is not str or not grammar.match(value):
                raise ProviderMetadataDisclosureError(
                    f"Durable field {field_name!r} does not satisfy its grammar. A field whose "
                    "format is not structurally constrained is a place a credential, a URL or "
                    "a query string can be written, and no blocklist can prove otherwise."
                )
        elif field_name == "requested_range":
            if type(value) is not str:
                raise ProviderMetadataDisclosureError(
                    "Durable field 'requested_range' must be an exact str."
                )
            defect = _requested_range_defect(value)
            if defect is not None:
                raise ProviderMetadataDisclosureError(f"Durable field 'requested_range' {defect}.")
        elif field_name == "retrieved_at":
            if type(value) is not str:
                raise ProviderMetadataDisclosureError(
                    "Durable field 'retrieved_at' must be an exact str."
                )
            defect = _retrieved_at_defect(value)
            if defect is not None:
                raise ProviderMetadataDisclosureError(f"Durable field 'retrieved_at' {defect}.")
        elif field_name == "byte_count":
            if type(value) is not int or value < 0:
                raise ProviderMetadataDisclosureError(
                    "Durable field 'byte_count' must be a non-negative int."
                )
        elif field_name == "acquisition_mode":
            # Exact plain ``str`` against the three permitted tokens. A
            # ``StrEnum`` member is a ``str`` subclass and is refused for the
            # same reason ``classification`` refuses one: what is written must be
            # the value, not something that currently compares equal to it.
            #
            # There is no boolean branch here and no conversion from one. The
            # retired ``is_backfill`` key is not in the allowlist, so a record
            # carrying it -- alone or beside this field -- is refused before this
            # point (ADR-0013).
            if type(value) is not str or value not in _ACQUISITION_MODE_TOKENS:
                raise ProviderMetadataDisclosureError(
                    "Durable field 'acquisition_mode' must be exactly one of "
                    "QUALIFICATION, BACKFILL or UPDATE, as a plain str."
                )
        elif field_name == "classification":
            # Exact plain str, so a StrEnum member -- itself a str subclass -- and a
            # custom equality object are both refused. A record is bytes on a
            # disk: what is written must be the value, not something that
            # currently compares equal to it.
            if type(value) is not str or value != DataClassification.LICENSED.value:
                raise ProviderMetadataDisclosureError(
                    "Durable field 'classification' must be the exact string "
                    f"{DataClassification.LICENSED.value!r} on this path."
                )
        else:  # pragma: no cover - unreachable while the allowlists are covered above
            raise ProviderMetadataDisclosureError(
                f"Durable field {field_name!r} has no declared contract to be checked against."
            )

    # Secondary, and unreachable for a value that satisfied the grammars above.
    # Kept as defence in depth and as a legible statement of what is kept out.
    for field_name, value in sorted(record.items()):
        if type(value) is not str:
            continue
        lowered = value.lower()
        for marker in FORBIDDEN_RECORD_SUBSTRINGS:
            if marker in lowered:  # pragma: no cover - the grammars admit no such value
                raise ProviderMetadataDisclosureError(
                    f"Durable field {field_name!r} carries {marker!r}."
                )


def publish_bronze_payload(
    *,
    store: ResearchObjectStore,
    payload: bytes,
    retrieval: RetrievalMetadata,
) -> BronzePublication:
    """Claim the acquisition identity, publish ``payload``, then record it.

    Claim first, so a contradictory identity is refused before any bytes land.
    Payload second. Acquisition record last, so a record can never name a payload
    that does not exist. Every write is idempotent for identical content, so
    re-publishing an identical retrieval writes nothing and is not an error.

    Raises:
        ObjectAlreadyExistsError: if this ``(digest, run id)`` is already claimed
            by a different provider or dataset, if the payload name holds
            different bytes, or if this acquisition identity is already recorded
            with different metadata.
        ProviderMetadataDisclosureError: if the claim or the record would carry a
            field outside its allowlist, or a value outside its grammar.
    """
    payload = immutable_payload(payload)
    digest = sha256_hex(payload)

    claim = acquisition_claim(retrieval=retrieval, content_sha256=digest)
    require_recordable(claim, allowed=CLAIM_FIELDS)
    claim_bytes = canonical_bytes(claim)
    claim_key = acquisition_claim_key(
        payload_digest=digest, run_id=retrieval.ingestion_run_id, claim=claim_bytes
    )

    record = acquisition_record(retrieval=retrieval, content_sha256=digest, byte_count=len(payload))
    require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)
    record_bytes = canonical_bytes(record)

    payload_key = bronze_payload_key(retrieval=retrieval, payload=payload)
    acquisition_key = bronze_acquisition_key(
        retrieval=retrieval, payload_digest=digest, record=record_bytes
    )

    claim_outcome: PutOutcome = store.put_if_absent(key=claim_key, payload=claim_bytes)
    payload_outcome: PutOutcome = store.put_if_absent(key=payload_key, payload=payload)
    acquisition_outcome: PutOutcome = store.put_if_absent(key=acquisition_key, payload=record_bytes)

    return BronzePublication(
        claim_key=claim_key,
        payload_key=payload_key,
        acquisition_key=acquisition_key,
        content_sha256=digest,
        byte_count=payload_outcome.byte_count,
        claim_written=claim_outcome.stored,
        payload_written=payload_outcome.stored,
        acquisition_written=acquisition_outcome.stored,
        retrieval=retrieval,
    )


__all__ = [
    "ACQUISITION_RECORD_FIELDS",
    "BRONZE_NAMESPACE",
    "CLAIM_FIELDS",
    "CLAIM_NAMESPACE",
    "FORBIDDEN_RECORD_SUBSTRINGS",
    "NAMED_RANGES",
    "BronzePublication",
    "acquisition_claim",
    "acquisition_claim_key",
    "acquisition_record",
    "bronze_acquisition_key",
    "bronze_payload_key",
    "publish_bronze_payload",
    "require_recordable",
]
