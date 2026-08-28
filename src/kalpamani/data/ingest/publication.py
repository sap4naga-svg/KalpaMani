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

    licensed/acquisition-claims/<digest>/<run-id>.json      <- GLOBAL, provider-independent
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

**Everything published here is LICENSED, and there is no argument that changes
it.** The key builders call :meth:`~kalpamani.data.objectstore.ObjectKey.licensed`,
which takes no classification parameter. The claim and the acquisition record are
licensed too -- not because either could reconstruct a vendor row, but because
promoting a receipt to the control store is a decision that needs an explicit
attestation, and this slice does not make it. Deferring costs nothing: they sit
inside the vendor deletion surface, which is the conservative side.

**Durable metadata carries no free text, and that is a structural property rather
than a filter.** :func:`acquisition_record` emits a closed field set, and every
field is validated against *its own* format -- a lowercase provider token, a
closed range grammar, a UTC instant, a 64-hex digest, an exact ``bool``. A
substring blocklist cannot prove the absence of an arbitrary credential, query
string, bucket or cloud identifier; a grammar that admits neither spaces nor
punctuation can. ``RetrievalMetadata.notes`` belongs to the A1 filesystem writer
and **is never read on this path**, so there is no field here for human text to
travel in.

**No provider row is parsed before publication.** A payload is opaque bytes. A
future provider response that is malformed, truncated or in an unexpected format
is still preservable as Bronze evidence, which is exactly when the evidence
matters most.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.errors import ProviderMetadataDisclosureError
from kalpamani.data.contracts.vocabulary import DataClassification
from kalpamani.data.ingest.bronze import RetrievalMetadata
from kalpamani.data.objectstore import ObjectKey, PutOutcome, ResearchObjectStore

#: The top-level namespace holding the global acquisition claims. A **sibling** of
#: ``bronze`` rather than a child of it, so no provider name can ever collide with
#: it: providers live under ``bronze/<provider>/``, and nothing else is written
#: directly under the classification prefix.
CLAIM_NAMESPACE: Final = "acquisition-claims"

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
        "dataset",
        "ingestion_run_id",
        "is_backfill",
        "provider",
        "requested_range",
        "retrieved_at",
        "source_schema_version",
    }
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

#: A requested range: either an explicit inclusive date range, or a single named
#: token for a dataset with no time axis. Nothing else, so "range" cannot become
#: a place to write a note.
_RANGE: Final = re.compile(r"^(?:\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}|[A-Z][A-Z0-9_]{0,31})$")

#: A UTC instant as :meth:`datetime.datetime.isoformat` renders it after
#: normalisation. The offset is required and must be ``+00:00``.
_INSTANT: Final = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+00:00$")

#: A schema version or ingestion-run identifier.
_IDENTIFIER: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: A content address. 64 lowercase hex characters, and nothing else.
_DIGEST: Final = re.compile(r"^[0-9a-f]{64}$")

#: Every recordable string field and the grammar it must satisfy.
_FIELD_GRAMMAR: Final[dict[str, re.Pattern[str]]] = {
    "provider": _TOKEN,
    "dataset": _TOKEN,
    "requested_range": _RANGE,
    "retrieved_at": _INSTANT,
    "source_schema_version": _IDENTIFIER,
    "ingestion_run_id": _IDENTIFIER,
    "content_sha256": _DIGEST,
}

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
    is_backfill: bool


def acquisition_claim_key(*, payload_digest: str, run_id: str, claim: bytes) -> ObjectKey:
    """The **global** logical key of one acquisition identity. Always LICENSED.

    Provider-independent by construction: nothing about the provider or the
    dataset appears in the name, so two providers claiming one
    ``(digest, run id)`` land on the same name and the second is refused.
    """
    return ObjectKey.licensed(CLAIM_NAMESPACE, payload_digest, f"{run_id}.json", payload=claim)


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
    is_backfill: bool,
) -> dict[str, Any]:
    """The recorded account of one retrieval. A closed field set, nothing free-form.

    ``is_backfill`` is what distinguishes a vendor backfill from an update, and
    the distinction is what the profile model exists to act on -- so it is
    recorded beside the payload rather than only on the run that produced it.

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
        "is_backfill": is_backfill,
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
        elif field_name == "byte_count":
            if type(value) is not int or value < 0:
                raise ProviderMetadataDisclosureError(
                    "Durable field 'byte_count' must be a non-negative int."
                )
        elif field_name == "is_backfill":
            if type(value) is not bool:
                raise ProviderMetadataDisclosureError(
                    "Durable field 'is_backfill' must be an exact bool."
                )
        elif field_name == "classification":
            if value != DataClassification.LICENSED.value:
                raise ProviderMetadataDisclosureError(
                    "Durable field 'classification' must be LICENSED on this path."
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
    is_backfill: bool,
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
    digest = sha256_hex(payload)

    claim = acquisition_claim(retrieval=retrieval, content_sha256=digest)
    require_recordable(claim, allowed=CLAIM_FIELDS)
    claim_bytes = canonical_bytes(claim)
    claim_key = acquisition_claim_key(
        payload_digest=digest, run_id=retrieval.ingestion_run_id, claim=claim_bytes
    )

    record = acquisition_record(
        retrieval=retrieval,
        content_sha256=digest,
        byte_count=len(payload),
        is_backfill=is_backfill,
    )
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
        is_backfill=is_backfill,
    )


__all__ = [
    "ACQUISITION_RECORD_FIELDS",
    "BRONZE_NAMESPACE",
    "CLAIM_FIELDS",
    "CLAIM_NAMESPACE",
    "FORBIDDEN_RECORD_SUBSTRINGS",
    "BronzePublication",
    "acquisition_claim",
    "acquisition_claim_key",
    "acquisition_record",
    "bronze_acquisition_key",
    "bronze_payload_key",
    "publish_bronze_payload",
    "require_recordable",
]
