"""Bronze publication: identity, append-only, classification, metadata hygiene.

The publication path is where a vendor payload first becomes a stored artifact,
so it is where four things have to be true at once:

**Identity is the bytes.** The same payload publishes to the same address; a
payload differing by one byte publishes to a different one. A payload is never
parsed on the way in, so a malformed future response is still preservable as
evidence -- which is exactly when evidence matters.

**Publication is append-only and idempotent.** Re-publishing an identical
retrieval writes nothing and is not an error. Restating one retrieval with
different metadata is refused, because one retrieval happened once.

**Vendor material is LICENSED, structurally.** There is no argument on the
publication path that routes a provider payload to the control store.

**No credential, URL, query string or cloud identifier is ever recorded.** The
realistic way one would arrive is a caller-supplied note, so the guard runs on
every publication rather than on the day someone remembers it.

Everything here is synthetic. No provider was contacted, and the payloads were
never a vendor response.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fixtures import sharadar_provider as syn
from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.errors import (
    ObjectAlreadyExistsError,
    ProviderMetadataDisclosureError,
)
from kalpamani.data.contracts.vocabulary import DataClassification, IngestionStatus
from kalpamani.data.ingest.bronze import RetrievalMetadata, build_ingestion_run
from kalpamani.data.ingest.publication import (
    ACQUISITION_RECORD_FIELDS,
    FORBIDDEN_RECORD_SUBSTRINGS,
    acquisition_record,
    publish_bronze_payload,
    require_no_disclosure,
)
from kalpamani.data.ingest.sharadar.bronze import (
    publish_sharadar_payload,
    sharadar_retrieval_metadata,
)
from kalpamani.data.ingest.sharadar.datasets import PROVIDER, SNAPSHOT_RANGE
from kalpamani.data.objectstore import InMemoryResearchObjectStore

pytestmark = pytest.mark.unit


def publish(
    store: InMemoryResearchObjectStore,
    *,
    payload: bytes = syn.SYNTHETIC_PAYLOAD,
    run_id: str = syn.INGESTION_RUN_ID,
    is_backfill: bool = False,
    notes: str = "",
) -> object:
    """Publish one synthetic Sharadar payload through the provider bridge."""
    return publish_sharadar_payload(
        store=store,
        request=syn.stocks_request(),
        payload=payload,
        retrieved_at=syn.RETRIEVED_AT,
        ingestion_run_id=run_id,
        source_schema_version=syn.SOURCE_SCHEMA_VERSION,
        is_backfill=is_backfill,
        notes=notes,
    )


def retrieval(run_id: str = syn.INGESTION_RUN_ID) -> RetrievalMetadata:
    return sharadar_retrieval_metadata(
        request=syn.stocks_request(),
        retrieved_at=syn.RETRIEVED_AT,
        ingestion_run_id=run_id,
        source_schema_version=syn.SOURCE_SCHEMA_VERSION,
    )


# ---------------------------------------------------------------------------
# F -- content-addressed identity and append-only publication
# ---------------------------------------------------------------------------


def test_the_payload_is_stored_byte_for_byte() -> None:
    store = InMemoryResearchObjectStore()
    published = publish_sharadar_payload(
        store=store,
        request=syn.stocks_request(),
        payload=syn.SYNTHETIC_PAYLOAD,
        retrieved_at=syn.RETRIEVED_AT,
        ingestion_run_id=syn.INGESTION_RUN_ID,
        source_schema_version=syn.SOURCE_SCHEMA_VERSION,
        is_backfill=False,
    )
    assert store.read(published.payload_key) == syn.SYNTHETIC_PAYLOAD
    assert published.content_sha256 == sha256_hex(syn.SYNTHETIC_PAYLOAD)
    assert published.byte_count == len(syn.SYNTHETIC_PAYLOAD)


def test_the_same_bytes_publish_to_the_same_address() -> None:
    first = publish(InMemoryResearchObjectStore())
    second = publish(InMemoryResearchObjectStore())
    assert first.payload_key.logical_key == second.payload_key.logical_key  # type: ignore[attr-defined]
    assert first.content_sha256 == second.content_sha256  # type: ignore[attr-defined]


def test_one_byte_of_difference_publishes_to_a_different_address() -> None:
    store = InMemoryResearchObjectStore()
    first = publish(store)
    second = publish(store, payload=syn.SYNTHETIC_PAYLOAD_ONE_BYTE_DIFFERENT, run_id="run-0002")
    assert first.payload_key.logical_key != second.payload_key.logical_key  # type: ignore[attr-defined]
    assert len(store.snapshot()) == 4


def test_republishing_an_identical_retrieval_writes_nothing() -> None:
    store = InMemoryResearchObjectStore()
    first = publish(store)
    second = publish(store)
    assert first.payload_written is True  # type: ignore[attr-defined]
    assert first.acquisition_written is True  # type: ignore[attr-defined]
    assert second.payload_written is False  # type: ignore[attr-defined]
    assert second.acquisition_written is False  # type: ignore[attr-defined]
    assert len(store.snapshot()) == 2


def test_a_second_run_over_unchanged_bytes_is_a_new_acquisition_not_a_new_payload() -> None:
    """We did fetch it twice, and there is still only one payload."""
    store = InMemoryResearchObjectStore()
    publish(store, run_id="synthetic-run-0001")
    second = publish(store, run_id="synthetic-run-0002")
    assert second.payload_written is False  # type: ignore[attr-defined]
    assert second.acquisition_written is True  # type: ignore[attr-defined]
    assert len(store.snapshot()) == 3


def test_restating_one_retrieval_with_different_metadata_is_refused() -> None:
    """One retrieval happened once; a later restatement would describe a non-event."""
    store = InMemoryResearchObjectStore()
    publish(store, is_backfill=False)
    with pytest.raises(ObjectAlreadyExistsError, match="append-only"):
        publish(store, is_backfill=True)


def test_a_payload_is_never_parsed_before_publication() -> None:
    """A malformed future response must still be preservable as evidence."""
    store = InMemoryResearchObjectStore()
    malformed = b"\x00\xff not valid utf-8 \xfe truncated,"
    published = publish(store, payload=malformed)
    assert store.read(published.payload_key) == malformed  # type: ignore[attr-defined]


def test_the_acquisition_record_names_a_payload_that_exists() -> None:
    """The record is written last, so its existence proves the payload landed."""
    store = InMemoryResearchObjectStore()
    published = publish(store)
    record = canonical_bytes(
        acquisition_record(
            retrieval=retrieval(),
            content_sha256=published.content_sha256,  # type: ignore[attr-defined]
            byte_count=published.byte_count,  # type: ignore[attr-defined]
            is_backfill=False,
        )
    )
    assert store.read(published.acquisition_key) == record  # type: ignore[attr-defined]
    assert store.exists(key=published.payload_key) is True  # type: ignore[attr-defined]


def test_the_logical_layout_separates_payloads_from_acquisitions_per_provider() -> None:
    store = InMemoryResearchObjectStore()
    published = publish(store)
    digest = published.content_sha256  # type: ignore[attr-defined]
    assert sorted(store.snapshot()) == [
        f"licensed/bronze/sharadar/stocks/acquisitions/{digest}/{syn.INGESTION_RUN_ID}.json",
        f"licensed/bronze/sharadar/stocks/objects/sha256/{digest}",
    ]


# ---------------------------------------------------------------------------
# G -- classification
# ---------------------------------------------------------------------------


def test_every_published_object_is_licensed() -> None:
    store = InMemoryResearchObjectStore()
    published = publish(store)
    for key in (published.payload_key, published.acquisition_key):  # type: ignore[attr-defined]
        assert key.classification is DataClassification.LICENSED
        assert key.logical_key.startswith("licensed/")
    assert all(name.startswith("licensed/") for name in store.snapshot())


def test_the_publication_path_has_no_argument_that_reaches_the_control_store() -> None:
    """The structural half: a CONTROL destination is not expressible from here."""
    import inspect

    for function in (publish_bronze_payload, publish_sharadar_payload):
        parameters = set(inspect.signature(function).parameters)
        assert not parameters & {"classification", "control", "attestation", "destination"}


def test_the_record_declares_its_own_classification() -> None:
    record = acquisition_record(
        retrieval=retrieval(), content_sha256="0" * 64, byte_count=1, is_backfill=False
    )
    assert record["classification"] == DataClassification.LICENSED.value


# ---------------------------------------------------------------------------
# H -- metadata hygiene
# ---------------------------------------------------------------------------


def test_the_recorded_field_set_is_exactly_the_allowlist() -> None:
    record = acquisition_record(
        retrieval=retrieval(), content_sha256="0" * 64, byte_count=7, is_backfill=True
    )
    assert set(record) == ACQUISITION_RECORD_FIELDS
    assert record["provider"] == PROVIDER
    assert record["dataset"] == "stocks"
    assert record["requested_range"] == "2021-08-28/2026-08-27"
    assert record["is_backfill"] is True


def test_a_snapshot_dataset_records_a_named_range_rather_than_an_empty_one() -> None:
    """An empty range would read as an unknown window rather than an absent one."""
    metadata = sharadar_retrieval_metadata(
        request=syn.tickers_request(),
        retrieved_at=syn.RETRIEVED_AT,
        ingestion_run_id=syn.INGESTION_RUN_ID,
        source_schema_version=syn.SOURCE_SCHEMA_VERSION,
    )
    assert metadata.requested_range == SNAPSHOT_RANGE


@pytest.mark.parametrize(
    "note",
    [
        "fetched via https://api.example.invalid/v1/data",
        "used api_key=synthetic-fake-not-a-real-sharadar-key-0001",
        "written to arn:aws:s3:::some-bucket",
        "Authorization: Bearer synthetic-token",
        "aws_secret set for the run",
    ],
)
def test_a_disclosing_note_is_refused_at_write_time(note: str) -> None:
    """Metadata outlives the process that wrote it, so this is a refusal, not a filter."""
    store = InMemoryResearchObjectStore()
    with pytest.raises(ProviderMetadataDisclosureError):
        publish(store, notes=note)
    assert store.snapshot() == {}


def test_the_refusal_names_the_field_and_never_quotes_the_value() -> None:
    """An error that republished the disclosure would defeat its own purpose."""
    with pytest.raises(ProviderMetadataDisclosureError) as caught:
        require_no_disclosure(
            acquisition_record(
                retrieval=sharadar_retrieval_metadata(
                    request=syn.stocks_request(),
                    retrieved_at=syn.RETRIEVED_AT,
                    ingestion_run_id=syn.INGESTION_RUN_ID,
                    source_schema_version=syn.SOURCE_SCHEMA_VERSION,
                    notes="key was api_key=synthetic-fake-secret-value-here",
                ),
                content_sha256="0" * 64,
                byte_count=1,
                is_backfill=False,
            )
        )
    assert "synthetic-fake-secret-value-here" not in str(caught.value)
    assert "notes" in str(caught.value)


def test_a_field_outside_the_allowlist_is_refused() -> None:
    record = acquisition_record(
        retrieval=retrieval(), content_sha256="0" * 64, byte_count=1, is_backfill=False
    )
    record["request_url"] = "anything"
    with pytest.raises(ProviderMetadataDisclosureError, match="Unexpected field"):
        require_no_disclosure(record)


def test_the_stored_record_carries_no_credential_url_or_cloud_identifier() -> None:
    store = InMemoryResearchObjectStore()
    published = publish(store, notes="synthetic ingestion note")
    stored = store.read(published.acquisition_key).decode("utf-8").lower()  # type: ignore[attr-defined]
    for marker in FORBIDDEN_RECORD_SUBSTRINGS:
        assert marker not in stored
    assert syn.SYNTHETIC_CREDENTIAL_VALUE not in stored
    assert "sharadar.com" not in stored


def test_an_ingestion_run_reuses_the_repository_vocabulary_and_stays_clean() -> None:
    """The run record already exists in the A1 contract; a parallel one would drift."""
    store = InMemoryResearchObjectStore()
    published = publish(store, is_backfill=True)
    run = build_ingestion_run(
        retrieval=published.retrieval,  # type: ignore[attr-defined]
        started_at=datetime(2026, 8, 28, 13, 44, tzinfo=UTC),
        completed_at=datetime(2026, 8, 28, 13, 45, tzinfo=UTC),
        artifacts=(),
        record_count=0,
        new_record_count=0,
        is_backfill=True,
        code_commit_sha="synthetic-commit",
        config_version="synthetic-config-v0",
    )
    assert run.provider == PROVIDER
    assert run.dataset == "stocks"
    assert run.is_backfill is True
    assert run.status is IngestionStatus.SUCCESS
    rendered = canonical_bytes(
        {
            "provider": run.provider,
            "dataset": run.dataset,
            "requested_range": run.requested_range,
            "ingestion_run_id": run.ingestion_run_id,
        }
    ).decode("utf-8")
    for marker in FORBIDDEN_RECORD_SUBSTRINGS:
        assert marker not in rendered.lower()
