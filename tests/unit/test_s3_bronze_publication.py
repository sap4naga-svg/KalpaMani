"""The neutral Bronze publisher, run against the synthetic S3 store. **No socket opens.**

The publisher was written against the ``ResearchObjectStore`` protocol and has
only ever been exercised against the in-memory backend. This runs the *same*
publisher, unchanged, through the S3 adapter and a synthetic client — which is
the only way to establish that the protocol was a real seam rather than a shape
that happened to fit one implementation.

What it proves:

* the three-object layout lands at the right **physical** keys, with the
  classification prefix consumed by the bucket rather than repeated inside it;
* the write order still holds — claim, payload, record last;
* an identical replay is idempotent all the way down;
* payload bytes stay opaque and exact;
* **no CONTROL object is written**;
* **no bucket value reaches acquisition metadata or a** ``PutOutcome``.

Every payload is invented. No vendor row appears here.
"""

from __future__ import annotations

import json

import pytest

from fixtures import sharadar_provider as syn
from fixtures.fake_s3 import SYNTHETIC_BUCKET, FakeS3Client
from kalpamani.data.contracts.canonical import sha256_hex
from kalpamani.data.contracts.vocabulary import DataClassification
from kalpamani.data.ingest.publication import BRONZE_NAMESPACE, CLAIM_NAMESPACE, BronzePublication
from kalpamani.data.ingest.sharadar.bronze import publish_sharadar_payload
from kalpamani.data.storage.s3 import S3ResearchObjectStore

pytestmark = pytest.mark.unit


def publish(
    backing: S3ResearchObjectStore,
    *,
    payload: bytes = syn.SYNTHETIC_PAYLOAD,
    run_id: str = syn.INGESTION_RUN_ID,
    is_backfill: bool = False,
) -> BronzePublication:
    """One synthetic Sharadar acquisition, published through the S3 adapter."""
    return publish_sharadar_payload(
        store=backing,
        request=syn.stocks_request(),
        payload=payload,
        retrieved_at=syn.RETRIEVED_AT,
        ingestion_run_id=run_id,
        source_schema_version=syn.SOURCE_SCHEMA_VERSION,
        is_backfill=is_backfill,
    )


def store() -> tuple[S3ResearchObjectStore, FakeS3Client]:
    fake = FakeS3Client()
    return S3ResearchObjectStore(client=fake, licensed_bucket=SYNTHETIC_BUCKET), fake


def test_the_three_objects_land_at_the_expected_physical_keys() -> None:
    backing, fake = store()
    published = publish(backing)
    digest = published.content_sha256
    run = syn.INGESTION_RUN_ID

    assert fake.stored_keys == [
        f"{BRONZE_NAMESPACE}/{CLAIM_NAMESPACE}/{digest}/{run}.json",
        f"{BRONZE_NAMESPACE}/sharadar/stocks/acquisitions/{digest}/{run}.json",
        f"{BRONZE_NAMESPACE}/sharadar/stocks/objects/sha256/{digest}",
    ]


def test_the_classification_prefix_is_consumed_by_the_bucket_not_repeated_inside_it() -> None:
    backing, fake = store()
    published = publish(backing)

    for location in fake.stored_keys:
        assert not location.startswith("licensed/")
    # The logical identities keep it; only the physical locations drop it.
    for logical in (published.claim_key, published.payload_key, published.acquisition_key):
        assert logical.logical_key.startswith("licensed/")
        assert logical.logical_key == f"licensed/{'/'.join(logical.segments)}"


def test_the_global_claim_is_provider_independent_in_its_physical_key() -> None:
    backing, fake = store()
    published = publish(backing)
    claim = f"{BRONZE_NAMESPACE}/{CLAIM_NAMESPACE}/{published.content_sha256}/"
    location = next(name for name in fake.stored_keys if name.startswith(claim))
    assert "sharadar" not in location
    assert "stocks" not in location


def test_the_acquisition_record_is_written_last() -> None:
    """Its existence is what marks the acquisition complete, so it must not
    precede the bytes it names."""
    backing, fake = store()
    published = publish(backing)
    order = [call["Key"] for call in fake.put_calls]
    digest = published.content_sha256

    claim = f"{BRONZE_NAMESPACE}/{CLAIM_NAMESPACE}/{digest}/{syn.INGESTION_RUN_ID}.json"
    payload = f"{BRONZE_NAMESPACE}/sharadar/stocks/objects/sha256/{digest}"
    record = f"{BRONZE_NAMESPACE}/sharadar/stocks/acquisitions/{digest}/{syn.INGESTION_RUN_ID}.json"
    assert order == [claim, payload, record]


def test_the_payload_bytes_stay_opaque_and_exact() -> None:
    backing, fake = store()
    malformed = b"\x00\xff not valid utf-8 \xfe truncated,"
    published = publish(backing, payload=malformed)
    location = f"{BRONZE_NAMESPACE}/sharadar/stocks/objects/sha256/{published.content_sha256}"
    assert fake.body_of(location) == malformed
    assert sha256_hex(fake.body_of(location)) == published.content_sha256


def test_an_identical_replay_is_idempotent_all_the_way_down() -> None:
    backing, fake = store()
    first = publish(backing)
    second = publish(backing)

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
    assert len(fake.objects) == 3
    assert len(fake.put_calls) == 6, "three conditional attempts per publication"


def test_no_control_object_is_written() -> None:
    backing, fake = store()
    published = publish(backing)
    for logical in (published.claim_key, published.payload_key, published.acquisition_key):
        assert logical.classification is DataClassification.LICENSED
    for location in fake.stored_keys:
        assert not location.startswith("control/")
        assert "control" not in location.split("/")


def test_no_bucket_value_reaches_metadata_or_the_publication_result() -> None:
    backing, fake = store()
    published = publish(backing)

    record_key = next(name for name in fake.stored_keys if "/acquisitions/" in name)
    record = json.loads(fake.body_of(record_key).decode("utf-8"))
    claim_key = next(name for name in fake.stored_keys if CLAIM_NAMESPACE in name)
    claim = json.loads(fake.body_of(claim_key).decode("utf-8"))

    surfaces = [
        json.dumps(record),
        json.dumps(claim),
        repr(published),
        published.payload_key.logical_key,
        published.claim_key.logical_key,
        published.acquisition_key.logical_key,
    ]
    for surface in surfaces:
        for marker in (SYNTHETIC_BUCKET, "s3://", "arn:", "amazonaws", "Bucket"):
            assert marker not in surface

    assert "notes" not in record
    assert record["classification"] == DataClassification.LICENSED.value


def test_a_second_run_over_unchanged_bytes_adds_a_claim_and_a_record_only() -> None:
    backing, fake = store()
    publish(backing, run_id="synthetic-run-0001")
    second = publish(backing, run_id="synthetic-run-0002")
    assert second.payload_written is False
    assert second.claim_written is True
    assert second.acquisition_written is True
    assert len(fake.objects) == 5


def test_every_object_is_written_conditionally_and_encrypted() -> None:
    backing, fake = store()
    publish(backing)
    for call in fake.put_calls:
        assert call["IfNoneMatch"] == "*"
        assert call["ServerSideEncryption"] == "AES256"
        assert call["ChecksumAlgorithm"] == "SHA256"
