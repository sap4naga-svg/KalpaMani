"""Bronze publication: identity, append-only, classification, metadata hygiene.

The publication path is where a vendor payload first becomes a stored artifact,
so it is where five things have to be true at once:

**Identity is the bytes.** The same payload publishes to the same address; a
payload differing by one byte publishes to a different one. A payload is never
parsed on the way in, so a malformed future response is still preservable as
evidence -- which is exactly when evidence matters.

**Acquisition identity is global.** ``(digest, run id)`` names one retrieval, not
one per provider and not one per dataset. The store has no listing surface, so the
global fact gets a global *name* and the store's append-only refusal enforces it.

**Publication is append-only and idempotent.** Re-publishing an identical
retrieval writes nothing and is not an error. Restating one retrieval with
different metadata is refused, because one retrieval happened once.

**Vendor material is LICENSED, structurally.** There is no argument on the
publication path that routes a provider payload to the control store.

**Durable metadata has no free-text field at all.** Not a filtered one -- an
absent one. Every field that is written is checked against its own grammar, and
none of those grammars admits a space, a colon or a slash outside a date.

Everything here is synthetic. No provider was contacted, and the payloads were
never a vendor response.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime

import pytest

from fixtures import sharadar_provider as syn
from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.errors import (
    ObjectAlreadyExistsError,
    ObjectPayloadTypeError,
    ProviderMetadataDisclosureError,
)
from kalpamani.data.contracts.vocabulary import (
    AcquisitionMode,
    DataClassification,
    IngestionStatus,
)
from kalpamani.data.ingest.bronze import RetrievalMetadata, build_ingestion_run
from kalpamani.data.ingest.publication import (
    ACQUISITION_RECORD_FIELDS,
    CLAIM_FIELDS,
    CLAIM_NAMESPACE,
    FORBIDDEN_RECORD_SUBSTRINGS,
    BronzePublication,
    acquisition_claim,
    acquisition_record,
    publish_bronze_payload,
    require_recordable,
)
from kalpamani.data.ingest.sharadar.bronze import (
    publish_sharadar_payload,
    sharadar_retrieval_metadata,
)
from kalpamani.data.ingest.sharadar.datasets import PROVIDER, SNAPSHOT_RANGE
from kalpamani.data.objectstore import InMemoryResearchObjectStore

pytestmark = pytest.mark.unit

#: Three objects land per acquisition: the global claim, the payload, the record.
OBJECTS_PER_ACQUISITION = 3


def publish(
    store: InMemoryResearchObjectStore,
    *,
    payload: bytes = syn.SYNTHETIC_PAYLOAD,
    run_id: str = syn.INGESTION_RUN_ID,
    acquisition_mode: AcquisitionMode = AcquisitionMode.QUALIFICATION,
) -> BronzePublication:
    """Publish one synthetic Sharadar payload through the provider bridge."""
    return publish_sharadar_payload(
        store=store,
        request=syn.stocks_request(),
        payload=payload,
        retrieved_at=syn.RETRIEVED_AT,
        ingestion_run_id=run_id,
        source_schema_version=syn.SOURCE_SCHEMA_VERSION,
        acquisition_mode=acquisition_mode,
    )


def retrieval(
    *,
    run_id: str = syn.INGESTION_RUN_ID,
    provider: str = PROVIDER,
    dataset: str = "stocks",
    notes: str = "",
) -> RetrievalMetadata:
    """A retrieval record. ``notes`` is settable so a test can prove it is unused."""
    return RetrievalMetadata(
        provider=provider,
        dataset=dataset,
        requested_range="2021-08-28/2026-08-27",
        retrieved_at=syn.RETRIEVED_AT,
        source_schema_version=syn.SOURCE_SCHEMA_VERSION,
        ingestion_run_id=run_id,
        acquisition_mode=AcquisitionMode.QUALIFICATION,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# F -- content-addressed identity and append-only publication
# ---------------------------------------------------------------------------


def test_the_payload_is_stored_byte_for_byte() -> None:
    store = InMemoryResearchObjectStore()
    published = publish(store)
    assert store.read(published.payload_key) == syn.SYNTHETIC_PAYLOAD
    assert published.content_sha256 == sha256_hex(syn.SYNTHETIC_PAYLOAD)
    assert published.byte_count == len(syn.SYNTHETIC_PAYLOAD)


def test_the_same_bytes_publish_to_the_same_address() -> None:
    first = publish(InMemoryResearchObjectStore())
    second = publish(InMemoryResearchObjectStore())
    assert first.payload_key.logical_key == second.payload_key.logical_key
    assert first.content_sha256 == second.content_sha256


def test_one_byte_of_difference_publishes_to_a_different_address() -> None:
    store = InMemoryResearchObjectStore()
    first = publish(store)
    second = publish(
        store, payload=syn.SYNTHETIC_PAYLOAD_ONE_BYTE_DIFFERENT, run_id="synthetic-run-0002"
    )
    assert first.payload_key.logical_key != second.payload_key.logical_key
    assert len(store.snapshot()) == 2 * OBJECTS_PER_ACQUISITION


def test_republishing_an_identical_retrieval_writes_nothing() -> None:
    store = InMemoryResearchObjectStore()
    first = publish(store)
    second = publish(store)
    assert (first.claim_written, first.payload_written, first.acquisition_written) == (
        True,
        True,
        True,
    )
    assert (second.claim_written, second.payload_written, second.acquisition_written) == (
        False,
        False,
        False,
    )
    assert len(store.snapshot()) == OBJECTS_PER_ACQUISITION


def test_a_second_run_over_unchanged_bytes_is_a_new_acquisition_not_a_new_payload() -> None:
    """We did fetch it twice, and there is still only one payload."""
    store = InMemoryResearchObjectStore()
    publish(store, run_id="synthetic-run-0001")
    second = publish(store, run_id="synthetic-run-0002")
    assert second.payload_written is False
    assert second.claim_written is True
    assert second.acquisition_written is True
    assert len(store.snapshot()) == OBJECTS_PER_ACQUISITION + 2


def test_restating_one_retrieval_with_a_different_mode_is_refused() -> None:
    """One retrieval happened once, and it was one kind of act.

    The mode is the metadata most likely to be restated -- a later run deciding
    the same fetch was "really" a backfill -- so it is the one this test uses. A
    restatement describes a non-event, and append-only storage refuses it.
    """
    store = InMemoryResearchObjectStore()
    publish(store, acquisition_mode=AcquisitionMode.QUALIFICATION)
    with pytest.raises(ObjectAlreadyExistsError, match="append-only"):
        publish(store, acquisition_mode=AcquisitionMode.BACKFILL)


def test_restating_one_retrieval_with_the_same_mode_is_idempotent() -> None:
    """The control for the test above: identical metadata is an ordinary repeat."""
    store = InMemoryResearchObjectStore()
    first = publish(store, acquisition_mode=AcquisitionMode.UPDATE)
    second = publish(store, acquisition_mode=AcquisitionMode.UPDATE)
    assert first.acquisition_written is True
    assert (second.claim_written, second.payload_written, second.acquisition_written) == (
        False,
        False,
        False,
    )


@pytest.mark.parametrize("mode", list(AcquisitionMode))
def test_every_mode_publishes_under_licensed_and_records_its_own_token(
    mode: AcquisitionMode,
) -> None:
    """All three modes are constructible by a neutral synthetic caller, and each
    records exactly its own token."""
    store = InMemoryResearchObjectStore()
    published = publish(store, acquisition_mode=mode, run_id=f"synthetic-run-{mode.value.lower()}")
    record = json.loads(store.read(published.acquisition_key).decode("utf-8"))
    assert record["acquisition_mode"] == mode.value
    assert record["classification"] == DataClassification.LICENSED.value
    assert published.retrieval.acquisition_mode is mode
    for key in (published.claim_key, published.payload_key, published.acquisition_key):
        assert key.classification is DataClassification.LICENSED


def test_a_payload_is_never_parsed_before_publication() -> None:
    """A malformed future response must still be preservable as evidence."""
    store = InMemoryResearchObjectStore()
    malformed = b"\x00\xff not valid utf-8 \xfe truncated,"
    published = publish(store, payload=malformed)
    assert store.read(published.payload_key) == malformed


def test_the_acquisition_record_names_a_payload_that_exists() -> None:
    """The record is written last, so its existence proves the payload landed."""
    store = InMemoryResearchObjectStore()
    published = publish(store)
    expected = canonical_bytes(
        acquisition_record(
            retrieval=published.retrieval,
            content_sha256=published.content_sha256,
            byte_count=published.byte_count,
        )
    )
    assert store.read(published.acquisition_key) == expected
    assert store.exists(key=published.payload_key) is True


def test_the_logical_layout_separates_the_claim_the_payload_and_the_record() -> None:
    store = InMemoryResearchObjectStore()
    published = publish(store)
    digest = published.content_sha256
    run = syn.INGESTION_RUN_ID
    assert sorted(store.snapshot()) == [
        f"licensed/bronze/{CLAIM_NAMESPACE}/{digest}/{run}.json",
        f"licensed/bronze/sharadar/stocks/acquisitions/{digest}/{run}.json",
        f"licensed/bronze/sharadar/stocks/objects/sha256/{digest}",
    ]


# ---------------------------------------------------------------------------
# Global acquisition identity
# ---------------------------------------------------------------------------


def test_the_claim_namespace_is_provider_independent() -> None:
    """Nothing about the provider or the dataset appears in the claim's name."""
    store = InMemoryResearchObjectStore()
    published = publish(store)
    assert published.claim_key.logical_key.startswith(f"licensed/bronze/{CLAIM_NAMESPACE}/")
    assert "sharadar" not in published.claim_key.logical_key
    assert "stocks" not in published.claim_key.logical_key


def test_an_identical_claim_is_idempotent() -> None:
    store = InMemoryResearchObjectStore()
    metadata = retrieval()
    first = publish_bronze_payload(store=store, payload=syn.SYNTHETIC_PAYLOAD, retrieval=metadata)
    second = publish_bronze_payload(store=store, payload=syn.SYNTHETIC_PAYLOAD, retrieval=metadata)
    assert first.claim_written is True
    assert second.claim_written is False


def test_the_same_digest_and_run_under_a_different_provider_is_refused() -> None:
    """The defect this namespace exists to prevent: one retrieval, two providers."""
    store = InMemoryResearchObjectStore()
    publish_bronze_payload(
        store=store,
        payload=syn.SYNTHETIC_PAYLOAD,
        retrieval=retrieval(provider="sharadar"),
    )
    with pytest.raises(ObjectAlreadyExistsError, match="append-only"):
        publish_bronze_payload(
            store=store,
            payload=syn.SYNTHETIC_PAYLOAD,
            retrieval=retrieval(provider="othervendor"),
        )


def test_the_same_digest_and_run_under_a_different_dataset_is_refused() -> None:
    store = InMemoryResearchObjectStore()
    publish_bronze_payload(
        store=store,
        payload=syn.SYNTHETIC_PAYLOAD,
        retrieval=retrieval(dataset="stocks"),
    )
    with pytest.raises(ObjectAlreadyExistsError, match="append-only"):
        publish_bronze_payload(
            store=store,
            payload=syn.SYNTHETIC_PAYLOAD,
            retrieval=retrieval(dataset="actions"),
        )


def test_a_different_run_over_the_same_digest_is_a_permitted_new_acquisition() -> None:
    """A second retrieval of unchanged bytes is an ordinary event, not a conflict."""
    store = InMemoryResearchObjectStore()
    publish_bronze_payload(
        store=store,
        payload=syn.SYNTHETIC_PAYLOAD,
        retrieval=retrieval(run_id="synthetic-run-0001"),
    )
    second = publish_bronze_payload(
        store=store,
        payload=syn.SYNTHETIC_PAYLOAD,
        retrieval=retrieval(run_id="synthetic-run-0002"),
    )
    assert second.claim_written is True
    assert second.payload_written is False


def test_the_claim_binds_exactly_the_four_values_the_identity_is_about() -> None:
    claim = acquisition_claim(retrieval=retrieval(), content_sha256="0" * 64)
    assert (
        set(claim)
        == CLAIM_FIELDS
        == {
            "content_sha256",
            "ingestion_run_id",
            "provider",
            "dataset",
        }
    )


def test_the_claim_is_written_before_the_payload() -> None:
    """A contradictory identity must be refused before any vendor bytes land.

    The second provider's payload key is a *different* name -- storage is
    provider-scoped -- so nothing but the claim can refuse it. If the claim were
    written after the payload, the refused run would still have left a payload
    under the second provider's prefix, inside that vendor's deletion surface,
    with no acquisition record to explain it.
    """
    store = InMemoryResearchObjectStore()
    publish_bronze_payload(
        store=store,
        payload=syn.SYNTHETIC_PAYLOAD,
        retrieval=retrieval(provider="sharadar"),
    )
    before = dict(store.snapshot())
    with pytest.raises(ObjectAlreadyExistsError):
        publish_bronze_payload(
            store=store,
            payload=syn.SYNTHETIC_PAYLOAD,
            retrieval=retrieval(provider="othervendor"),
        )
    assert store.snapshot() == before, "the refused run must leave nothing behind"
    assert not any("othervendor" in name for name in store.snapshot())


# ---------------------------------------------------------------------------
# G -- classification
# ---------------------------------------------------------------------------


def test_every_published_object_is_licensed() -> None:
    store = InMemoryResearchObjectStore()
    published = publish(store)
    for key in (published.claim_key, published.payload_key, published.acquisition_key):
        assert key.classification is DataClassification.LICENSED
        assert key.logical_key.startswith("licensed/")
    assert all(name.startswith("licensed/") for name in store.snapshot())


def test_the_publication_path_has_no_argument_that_reaches_the_control_store() -> None:
    """The structural half: a CONTROL destination is not expressible from here."""
    for function in (publish_bronze_payload, publish_sharadar_payload):
        parameters = set(inspect.signature(function).parameters)
        assert not parameters & {"classification", "control", "attestation", "destination"}


def test_the_record_declares_its_own_classification() -> None:
    record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
    assert record["classification"] == DataClassification.LICENSED.value


# ---------------------------------------------------------------------------
# H -- durable metadata has no free-text field
# ---------------------------------------------------------------------------


def test_the_recorded_field_set_is_exactly_the_allowlist_and_excludes_notes() -> None:
    record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=7)
    assert set(record) == ACQUISITION_RECORD_FIELDS
    assert "notes" not in record
    assert record["provider"] == PROVIDER
    assert record["dataset"] == "stocks"
    assert record["requested_range"] == "2021-08-28/2026-08-27"
    assert record["acquisition_mode"] == "QUALIFICATION"
    assert type(record["acquisition_mode"]) is str, (
        "a StrEnum member is not what a reader gets back"
    )


def test_the_provider_bridge_offers_no_notes_parameter() -> None:
    """Not offering a parameter beats accepting one and dropping it."""
    for function in (publish_sharadar_payload, sharadar_retrieval_metadata):
        assert "notes" not in inspect.signature(function).parameters


def test_a_note_on_the_retrieval_never_reaches_the_durable_record() -> None:
    """``RetrievalMetadata.notes`` belongs to the A1 filesystem writer, not this path."""
    store = InMemoryResearchObjectStore()
    smuggled = "api_key=synthetic-fake-secret https://elsewhere.invalid/?x=1"
    published = publish_bronze_payload(
        store=store,
        payload=syn.SYNTHETIC_PAYLOAD,
        retrieval=retrieval(notes=smuggled),
    )
    for key in (published.claim_key, published.acquisition_key):
        stored = store.read(key).decode("utf-8")
        assert "notes" not in stored
        assert smuggled not in stored
        assert "synthetic-fake-secret" not in stored


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "sharadar https://elsewhere.invalid"),
        ("provider", "Sharadar"),
        ("dataset", "stocks?api_key=x"),
        ("requested_range", "2021-08-28/2026-08-27 (five years, key in query)"),
        ("requested_range", "arn:aws:s3:::a-bucket"),
        ("source_schema_version", "v0 with a free-form note"),
        ("ingestion_run_id", "run 0001"),
        ("content_sha256", "not-a-digest"),
        ("content_sha256", "A" * 64),
        ("retrieved_at", "2026-08-28 13:45:00"),
        ("classification", "CONTROL"),
    ],
)
def test_a_durable_field_outside_its_grammar_is_refused(field: str, value: str) -> None:
    """Each field is checked against its own contract, not against a blocklist."""
    record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
    record[field] = value
    with pytest.raises(ProviderMetadataDisclosureError):
        require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)


@pytest.mark.parametrize("value", [True, -1, "7", 1.0])
def test_a_byte_count_that_is_not_a_non_negative_int_is_refused(value: object) -> None:
    """``True`` is an ``int`` in Python, and a byte count of ``True`` is nobody's intent."""
    record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
    record["byte_count"] = value
    with pytest.raises(ProviderMetadataDisclosureError, match="byte_count"):
        require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        1,
        0,
        None,
        "qualification",
        "Qualification",
        "BACKFILL ",
        "HISTORICAL",
        "",
        AcquisitionMode.QUALIFICATION,
    ],
)
def test_an_acquisition_mode_that_is_not_an_exact_permitted_token_is_refused(
    value: object,
) -> None:
    """Booleans are named first, because the retired representation was one and a
    conversion from it is exactly what must not exist (ADR-0013). The enum member
    is refused too: a record is bytes on a disk, and a ``StrEnum`` is a ``str``
    *subclass* whose identity is not what a later reader gets back."""
    record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
    record["acquisition_mode"] = value
    with pytest.raises(ProviderMetadataDisclosureError, match="acquisition_mode"):
        require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)


def test_the_retired_boolean_key_is_refused_outright() -> None:
    """No compatibility reader, and no conversion. The key is simply not in the
    allowlist, so a record carrying it cannot be written."""
    assert "is_backfill" not in ACQUISITION_RECORD_FIELDS
    record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
    record["is_backfill"] = False
    with pytest.raises(ProviderMetadataDisclosureError):
        require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)


def test_a_record_carrying_both_representations_is_refused() -> None:
    """The dual-write case, refused by the allowlist rather than by a rule that
    would have to notice the pairing."""
    record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
    assert record["acquisition_mode"] == "QUALIFICATION"
    record["is_backfill"] = False
    with pytest.raises(ProviderMetadataDisclosureError):
        require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)


def test_a_str_subclass_cannot_pass_as_a_durable_string_field() -> None:
    """``type(...) is str``, so a subclass with an overridden ``__eq__`` cannot slip through."""

    class Sneaky(str):
        def __eq__(self, other: object) -> bool:
            return True

        def __hash__(self) -> int:
            return hash(str(self))

    record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
    record["provider"] = Sneaky("sharadar")
    with pytest.raises(ProviderMetadataDisclosureError, match="provider"):
        require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)


def test_an_extra_field_is_refused() -> None:
    record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
    record["request_url"] = "anything"
    with pytest.raises(ProviderMetadataDisclosureError, match="Unexpected field"):
        require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)


def test_a_missing_field_is_refused() -> None:
    record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
    del record["requested_range"]
    with pytest.raises(ProviderMetadataDisclosureError, match="missing field"):
        require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)


def test_the_refusal_names_the_field_and_never_quotes_the_value() -> None:
    """An error that republished the disclosure would defeat its own purpose."""
    record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
    record["source_schema_version"] = "api_key=synthetic-fake-secret-value-here"
    with pytest.raises(ProviderMetadataDisclosureError) as caught:
        require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)
    assert "synthetic-fake-secret-value-here" not in str(caught.value)
    assert "source_schema_version" in str(caught.value)


def test_a_snapshot_dataset_records_a_named_range_rather_than_an_empty_one() -> None:
    """An empty range would read as an unknown window rather than an absent one."""
    metadata = sharadar_retrieval_metadata(
        request=syn.tickers_request(),
        retrieved_at=syn.RETRIEVED_AT,
        ingestion_run_id=syn.INGESTION_RUN_ID,
        acquisition_mode=AcquisitionMode.QUALIFICATION,
        source_schema_version=syn.SOURCE_SCHEMA_VERSION,
    )
    assert metadata.requested_range == SNAPSHOT_RANGE
    record = acquisition_record(retrieval=metadata, content_sha256="0" * 64, byte_count=1)
    require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)


@pytest.mark.parametrize(
    "value,why",
    [
        ("2026-13-01/2026-12-31", "impossible month"),
        ("2026-02-30/2026-03-01", "impossible day"),
        ("2026-08-27/2021-08-28", "inverted range"),
        ("2026-08-27", "a single date is not a range"),
        ("SNAPSHOTS", "not the named token"),
        ("snapshot", "the named token is not case-folded"),
        ("2026-8-27/2026-08-28", "not zero-padded"),
        ("", "empty"),
    ],
)
def test_a_requested_range_is_parsed_rather_than_pattern_matched(value: str, why: str) -> None:
    """A pattern that counts digits admits 2026-13-45 and every inverted range."""
    record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
    record["requested_range"] = value
    with pytest.raises(ProviderMetadataDisclosureError, match="requested_range"):
        require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)


@pytest.mark.parametrize("value", ["2021-08-28/2026-08-27", "2026-08-27/2026-08-27", "SNAPSHOT"])
def test_a_valid_requested_range_still_passes(value: str) -> None:
    """The negative control: the parser must not refuse what it exists to admit."""
    record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
    record["requested_range"] = value
    require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)


@pytest.mark.parametrize(
    "value,why",
    [
        ("2026-08-28T13:45:00", "naive: no offset at all"),
        ("2026-08-28T13:45:00-05:00", "offset-aware but not UTC"),
        ("2026-08-28T13:45:00Z", "not the canonical spelling isoformat produces"),
        ("2026-08-28T25:00:00+00:00", "impossible hour"),
        ("2026-02-30T00:00:00+00:00", "impossible day"),
        ("not an instant", "unparseable"),
    ],
)
def test_a_retrieval_instant_is_parsed_and_required_to_be_canonical_utc(
    value: str, why: str
) -> None:
    """A naive or offset instant recorded as UTC moves an acquisition in time, and a
    second spelling of one instant is a second content hash."""
    record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
    record["retrieved_at"] = value
    with pytest.raises(ProviderMetadataDisclosureError, match="retrieved_at"):
        require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)


@pytest.mark.parametrize("value", ["2026-08-28T13:45:00+00:00", "2026-08-28T13:45:00.123456+00:00"])
def test_a_canonical_utc_instant_still_passes(value: str) -> None:
    record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
    record["retrieved_at"] = value
    require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)


def test_the_classification_must_be_an_exact_string_not_something_equal_to_one() -> None:
    """A ``StrEnum`` member is a ``str`` subclass, and a record is bytes on a disk."""

    class AlwaysEqual(str):
        def __eq__(self, other: object) -> bool:
            return True

        def __hash__(self) -> int:
            return hash("LICENSED")

    for value in (DataClassification.LICENSED, AlwaysEqual("LICENSED"), "CONTROL", None):
        record = acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
        record["classification"] = value
        with pytest.raises(ProviderMetadataDisclosureError, match="classification"):
            require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)


@pytest.mark.parametrize("payload", [bytearray(b"synthetic"), memoryview(b"synthetic"), "s"])
def test_publication_requires_exact_immutable_payload_bytes(payload: object) -> None:
    """A buffer the caller keeps could change after it was hashed and filed."""
    store = InMemoryResearchObjectStore()
    with pytest.raises(ObjectPayloadTypeError, match="exact bytes"):
        publish_bronze_payload(
            store=store,
            payload=payload,  # type: ignore[arg-type]
            retrieval=retrieval(),
        )
    assert store.snapshot() == {}


def test_the_provider_bridge_also_requires_exact_bytes() -> None:
    store = InMemoryResearchObjectStore()
    with pytest.raises(ObjectPayloadTypeError):
        publish(store, payload=bytearray(syn.SYNTHETIC_PAYLOAD))  # type: ignore[arg-type]
    assert store.snapshot() == {}


def test_the_stored_record_carries_no_credential_url_or_cloud_identifier() -> None:
    store = InMemoryResearchObjectStore()
    published = publish(store)
    stored = store.read(published.acquisition_key).decode("utf-8").lower()
    for marker in FORBIDDEN_RECORD_SUBSTRINGS:
        assert marker not in stored
    assert syn.SYNTHETIC_CREDENTIAL_VALUE not in stored
    assert "sharadar.com" not in stored


def test_an_ingestion_run_reuses_the_repository_vocabulary_and_stays_clean() -> None:
    """The run record already exists in the A1 contract; a parallel one would drift."""
    store = InMemoryResearchObjectStore()
    published = publish(store)
    run = build_ingestion_run(
        retrieval=published.retrieval,
        started_at=datetime(2026, 8, 28, 13, 44, tzinfo=UTC),
        completed_at=datetime(2026, 8, 28, 13, 45, tzinfo=UTC),
        artifacts=(),
        record_count=0,
        new_record_count=0,
        code_commit_sha="synthetic-commit",
        config_version="synthetic-config-v0",
    )
    assert run.provider == PROVIDER
    assert run.dataset == "stocks"
    assert run.acquisition_mode is AcquisitionMode.QUALIFICATION
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
