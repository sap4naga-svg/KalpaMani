"""The bridge from a Sharadar request to provider-neutral Bronze publication.

Deliberately thin. Everything about *how* an object is stored -- content
addressing, append-only identity, idempotency, the LICENSED classification, the
disclosure guard -- lives in :mod:`kalpamani.data.ingest.publication` and is
vendor-neutral. What belongs here, and only here, is the translation of vendor
vocabulary into the repository's: which dataset was asked for, over which range.

That is the boundary ADR-0005 and the A1 kernel are built around. A provider
adapter feeds source evidence *into* the point-in-time architecture; it does not
get to define how the architecture stores it. If a future provider needs a
different storage rule, that is a change to the neutral layer under review, not a
second storage implementation growing quietly inside a vendor package.

**No credential and no URL crosses this boundary.** The metadata built here
records the dataset name and the requested range -- both derived from the typed
request, neither from the wire. The neutral publisher re-checks that on every
call, so this module being careful is not the only thing standing between a query
string and a stored record.

**This module does not fetch.** It takes bytes a caller already holds. Fetching
and publishing are separate calls because combining them would create the runner
this slice is not authorized to build.
"""

from __future__ import annotations

from datetime import datetime

from kalpamani.data.ingest.bronze import RetrievalMetadata
from kalpamani.data.ingest.publication import BronzePublication, publish_bronze_payload
from kalpamani.data.ingest.sharadar.datasets import PROVIDER, SharadarRequest
from kalpamani.data.objectstore import ResearchObjectStore


def sharadar_retrieval_metadata(
    *,
    request: SharadarRequest,
    retrieved_at: datetime,
    ingestion_run_id: str,
    source_schema_version: str,
) -> RetrievalMetadata:
    """Describe one Sharadar retrieval in the repository's own vocabulary.

    ``requested_range`` comes from the typed request rather than from the URL, so
    the record says what was asked for without carrying how it was asked.
    ``SNAPSHOT`` is recorded for ``tickers``, which the vendor states has no time
    axis (`PSR-SHD-119`) -- an empty range there would read as an unknown window
    rather than an absent one.

    **There is no ``notes`` parameter, deliberately.** ``RetrievalMetadata.notes``
    exists for the A1 filesystem writer and is never read by the object-store
    publisher, so a free-text note has no durable destination on this path. Not
    offering the parameter is better than accepting one and dropping it.
    """
    return RetrievalMetadata(
        provider=PROVIDER,
        dataset=request.dataset.value,
        requested_range=request.requested_range,
        retrieved_at=retrieved_at,
        source_schema_version=source_schema_version,
        ingestion_run_id=ingestion_run_id,
    )


def publish_sharadar_payload(
    *,
    store: ResearchObjectStore,
    request: SharadarRequest,
    payload: bytes,
    retrieved_at: datetime,
    ingestion_run_id: str,
    source_schema_version: str,
    is_backfill: bool,
) -> BronzePublication:
    """Publish one Sharadar payload byte for byte, with its acquisition record.

    The payload is opaque here: it is not decoded, parsed or validated. A vendor
    response that is truncated, malformed or in an unexpected encoding is still
    preserved as evidence, which is precisely the case where evidence matters.

    Raises:
        ObjectAlreadyExistsError: if this ``(digest, run id)`` is already claimed
            by a different provider or dataset, or if this acquisition identity is
            already recorded with different metadata.
        ProviderMetadataDisclosureError: if a durable field falls outside its
            declared grammar.
    """
    retrieval = sharadar_retrieval_metadata(
        request=request,
        retrieved_at=retrieved_at,
        ingestion_run_id=ingestion_run_id,
        source_schema_version=source_schema_version,
    )
    return publish_bronze_payload(
        store=store, payload=payload, retrieval=retrieval, is_backfill=is_backfill
    )


__all__ = ["publish_sharadar_payload", "sharadar_retrieval_metadata"]
