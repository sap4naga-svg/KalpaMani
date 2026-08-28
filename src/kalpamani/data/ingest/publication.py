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

**Two objects per acquisition, and the order is load-bearing.**

.. code-block:: text

    licensed/bronze/<provider>/<dataset>/objects/sha256/<digest>
    licensed/bronze/<provider>/<dataset>/acquisitions/<digest>/<run-id>.json

The payload goes first, the acquisition record second, and the record's existence
is what marks the acquisition complete.

The filesystem store solves the same problem with a durable ``PENDING`` record
that is later replaced by ``COMPLETE``. **That two-phase pattern is structurally
unavailable here**, because an append-only ``put_if_absent`` store has no
"replace" -- a ``PENDING`` record could never be advanced. Writing the record last
is the ordering that works under append-only semantics *and* is the safer of the
two: an interrupted run can leave a payload nothing explains, which is detectable
and inert, but it can never leave a record naming a payload that does not exist.
An acquisition record is therefore evidence that the bytes it names landed.

**Everything published here is LICENSED, and there is no argument that changes
it.** The key builders call :meth:`~kalpamani.data.objectstore.ObjectKey.licensed`,
which takes no classification parameter. The acquisition record is licensed too
-- not because it could reconstruct a vendor row, but because promoting a receipt
to the control store is a decision that needs an explicit attestation, and this
slice does not make it. Deferring it costs nothing: the record sits inside the
vendor deletion surface, which is the conservative side.

**Nothing about the request is ever recorded.** :func:`acquisition_record` emits a
fixed field set, and :func:`require_no_disclosure` refuses the result if a
credential, a URL, a query string or a cloud identifier has reached it through
any of them. A caller-supplied ``notes`` string is the realistic way one would
arrive, so the check runs on every publication rather than on the day someone
remembers it.

**No provider row is parsed before publication.** A payload is opaque bytes. A
future provider response that is malformed, truncated or in an unexpected format
is still preservable as Bronze evidence, which is exactly when the evidence
matters most.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.errors import ProviderMetadataDisclosureError
from kalpamani.data.contracts.vocabulary import DataClassification
from kalpamani.data.ingest.bronze import RetrievalMetadata
from kalpamani.data.objectstore import ObjectKey, PutOutcome, ResearchObjectStore

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
        "notes",
        "provider",
        "requested_range",
        "retrieved_at",
        "source_schema_version",
    }
)

#: Substrings that must never appear in a recorded acquisition. A credential
#: travels in the query string for at least one candidate provider, so a URL and a
#: query string are as disclosing as the key itself. The cloud markers are here
#: because a bucket name or an ARN in a committed-adjacent artifact is the
#: identifier hazard CLAUDE.md §3 and §4.24 exist to prevent.
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
    arriving twice -- and it is reported separately from
    ``acquisition_written`` so a caller can tell "already had these bytes" from
    "already recorded this exact retrieval".
    """

    payload_key: ObjectKey
    acquisition_key: ObjectKey
    content_sha256: str
    byte_count: int
    payload_written: bool
    acquisition_written: bool
    retrieval: RetrievalMetadata
    is_backfill: bool


def bronze_payload_key(*, retrieval: RetrievalMetadata, payload: bytes) -> ObjectKey:
    """The deterministic logical key of one Bronze payload. Always LICENSED.

    Scoped under ``<provider>/<dataset>`` rather than keyed by digest alone.
    Global de-duplication would be tempting -- identical bytes are identical bytes
    -- but it would merge two vendors' payloads into one object under one licence,
    and a deletion obligation that arrives for one vendor would then have to
    destroy the other's evidence or fail to be honoured. Per-provider scoping
    keeps each vendor's deletion surface separable.
    """
    digest = sha256_hex(payload)
    return ObjectKey.licensed(
        "bronze",
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

    ``(payload_digest, ingestion_run_id)`` names one retrieval, so re-recording
    that identity with different metadata lands on an occupied key and is refused
    by the store. One retrieval happened once; restating it later would make the
    record describe an event that did not occur.
    """
    return ObjectKey.licensed(
        "bronze",
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
    """The recorded account of one retrieval. A fixed field set, nothing derived.

    ``is_backfill`` is what distinguishes a vendor backfill from an update, and
    the distinction is what the profile model exists to act on -- so it is
    recorded beside the payload rather than only on the run that produced it.
    """
    return {
        "provider": retrieval.provider,
        "dataset": retrieval.dataset,
        "requested_range": retrieval.requested_range,
        "retrieved_at": retrieval.retrieved_at.isoformat(),
        "source_schema_version": retrieval.source_schema_version,
        "ingestion_run_id": retrieval.ingestion_run_id,
        "notes": retrieval.notes,
        "content_sha256": content_sha256,
        "byte_count": byte_count,
        "is_backfill": is_backfill,
        "classification": DataClassification.LICENSED.value,
    }


def require_no_disclosure(record: dict[str, Any]) -> None:
    """Refuse an acquisition record carrying anything that must not be stored.

    Raises:
        ProviderMetadataDisclosureError: if the record has a field outside
            :data:`ACQUISITION_RECORD_FIELDS`, or any value containing a
            credential, a URL, a query string or a cloud identifier. The message
            names the field, never the value -- an error that quoted the
            disclosure would republish it.
    """
    unexpected = sorted(set(record) - ACQUISITION_RECORD_FIELDS)
    if unexpected:
        raise ProviderMetadataDisclosureError(
            f"An acquisition record may only carry {sorted(ACQUISITION_RECORD_FIELDS)}. "
            f"Unexpected field(s): {unexpected}. The field set is an allowlist because a "
            "forbidden list has to anticipate the field nobody thought of."
        )
    for field_name, value in sorted(record.items()):
        if not isinstance(value, str):
            continue
        lowered = value.lower()
        for marker in FORBIDDEN_RECORD_SUBSTRINGS:
            if marker in lowered:
                raise ProviderMetadataDisclosureError(
                    f"Acquisition record field {field_name!r} carries {marker!r}. A credential, "
                    "a request URL, a query string and a cloud identifier are never recorded: "
                    "metadata outlives the process that wrote it, so this is refused at write "
                    "time rather than redacted afterwards."
                )


def publish_bronze_payload(
    *,
    store: ResearchObjectStore,
    payload: bytes,
    retrieval: RetrievalMetadata,
    is_backfill: bool,
) -> BronzePublication:
    """Publish ``payload`` and the record of how it was acquired.

    Payload first, acquisition record second, so a record can never name a payload
    that does not exist. Both objects are LICENSED, and both puts are idempotent:
    re-publishing an identical retrieval writes nothing and is not an error.

    Raises:
        ObjectAlreadyExistsError: if this acquisition identity already exists with
            different metadata, or if the payload key holds different bytes.
        ProviderMetadataDisclosureError: if the acquisition record would carry a
            credential, a URL, a query string or a cloud identifier.
    """
    digest = sha256_hex(payload)
    payload_key = bronze_payload_key(retrieval=retrieval, payload=payload)

    record = acquisition_record(
        retrieval=retrieval,
        content_sha256=digest,
        byte_count=len(payload),
        is_backfill=is_backfill,
    )
    require_no_disclosure(record)
    record_bytes = canonical_bytes(record)
    acquisition_key = bronze_acquisition_key(
        retrieval=retrieval, payload_digest=digest, record=record_bytes
    )

    payload_outcome: PutOutcome = store.put_if_absent(key=payload_key, payload=payload)
    acquisition_outcome: PutOutcome = store.put_if_absent(key=acquisition_key, payload=record_bytes)

    return BronzePublication(
        payload_key=payload_key,
        acquisition_key=acquisition_key,
        content_sha256=digest,
        byte_count=payload_outcome.byte_count,
        payload_written=payload_outcome.stored,
        acquisition_written=acquisition_outcome.stored,
        retrieval=retrieval,
        is_backfill=is_backfill,
    )


__all__ = [
    "ACQUISITION_RECORD_FIELDS",
    "FORBIDDEN_RECORD_SUBSTRINGS",
    "BronzePublication",
    "acquisition_record",
    "bronze_acquisition_key",
    "bronze_payload_key",
    "publish_bronze_payload",
    "require_no_disclosure",
]
