"""Bronze immutability and local analytical storage.

Every test writes into a pytest ``tmp_path``. Nothing here touches
``.runtime/data``, and nothing opens a network connection -- there is no network
client in this slice to open one with.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.canonical import (
    canonical_json,
    content_hash,
    sha256_hex,
)
from kalpamani.data.contracts.errors import ArtifactIntegrityError, BronzeIntegrityError
from kalpamani.data.contracts.serde import (
    decode_corporate_action,
    decode_listing,
    decode_market_session,
    decode_price_bar,
    decode_security_attribute,
    decode_ticker_history,
    encode_corporate_action,
    encode_listing,
    encode_market_session,
    encode_price_bar,
    encode_security_attribute,
    encode_ticker_history,
)
from kalpamani.data.contracts.vocabulary import StorageLayer
from kalpamani.data.ingest.bronze import BronzeStore, RetrievalMetadata, build_ingestion_run
from kalpamani.data.storage import DEFAULT_DATA_ROOT, LocalTableStore

pytestmark = pytest.mark.unit

INGEST_DATE = date(2026, 8, 26)


def _retrieval(dataset: str = "daily_bars") -> RetrievalMetadata:
    return RetrievalMetadata(
        provider=phase3a.PROVIDER,
        dataset=dataset,
        requested_range="2019-06-24..2019-06-28",
        retrieved_at=datetime(2026, 8, 26, 11, 0, tzinfo=UTC),
        source_schema_version="synthetic/1",
    )


# ---------------------------------------------------------------------------
# Bronze
# ---------------------------------------------------------------------------


def test_writing_identical_bytes_twice_is_idempotent(tmp_path: Path) -> None:
    """A re-run is not a new acquisition, and must not be reported as one."""
    store = BronzeStore(tmp_path)
    payload = phase3a.bronze_payload()

    first = store.write(payload=payload, retrieval=_retrieval(), ingest_date=INGEST_DATE)
    second = store.write(payload=payload, retrieval=_retrieval(), ingest_date=INGEST_DATE)

    assert first.was_written is True
    assert second.was_written is False
    assert first.content_sha256 == second.content_sha256 == sha256_hex(payload)
    assert first.path == second.path
    assert store.verify(second)


def test_different_bytes_create_a_distinct_artifact(tmp_path: Path) -> None:
    """A re-fetch returning different bytes is a NEW artifact, never a replacement.

    That is what makes a vendor backfill visible instead of silent.
    """
    store = BronzeStore(tmp_path)
    original = phase3a.bronze_payload()
    revised = original.replace(b'"100.00"', b'"100.50"')
    assert revised != original

    first = store.write(payload=original, retrieval=_retrieval(), ingest_date=INGEST_DATE)
    second = store.write(payload=revised, retrieval=_retrieval(), ingest_date=INGEST_DATE)

    assert first.content_sha256 != second.content_sha256
    assert first.path != second.path
    assert first.path.exists() and second.path.exists(), (
        "Bronze is append-only: the earlier acquisition survives the later one."
    )
    assert store.read(first.path) == original
    assert store.read(second.path) == revised


def test_an_identity_holding_different_bytes_is_refused(tmp_path: Path) -> None:
    """Two different payloads cannot share one identity, and overwriting is not a fix."""
    store = BronzeStore(tmp_path)
    payload = phase3a.bronze_payload()
    artifact = store.write(payload=payload, retrieval=_retrieval(), ingest_date=INGEST_DATE)

    artifact.path.write_bytes(gzip.compress(b'{"bars": []}', 9, mtime=0))
    with pytest.raises(BronzeIntegrityError, match="already holds different bytes"):
        store.write(payload=payload, retrieval=_retrieval(), ingest_date=INGEST_DATE)


def test_identity_is_the_uncompressed_payload_not_the_stored_file(tmp_path: Path) -> None:
    """The documented hashing contract, asserted rather than described."""
    store = BronzeStore(tmp_path)
    payload = phase3a.bronze_payload()
    artifact = store.write(payload=payload, retrieval=_retrieval(), ingest_date=INGEST_DATE)

    assert artifact.content_sha256 == sha256_hex(payload)
    assert artifact.content_sha256 != sha256_hex(artifact.path.read_bytes())
    assert artifact.path.name.startswith(artifact.content_sha256)


def test_compression_is_deterministic_so_a_rewrite_is_byte_identical(tmp_path: Path) -> None:
    """Without a fixed mtime the compressed bytes embed a clock."""
    payload = phase3a.bronze_payload()
    first = BronzeStore(tmp_path / "a").write(
        payload=payload, retrieval=_retrieval(), ingest_date=INGEST_DATE
    )
    second = BronzeStore(tmp_path / "b").write(
        payload=payload, retrieval=_retrieval(), ingest_date=INGEST_DATE
    )
    assert first.path.read_bytes() == second.path.read_bytes()


def test_acquisition_metadata_is_stored_outside_the_payload(tmp_path: Path) -> None:
    """Identity is a property of what the vendor sent, not of when we asked."""
    store = BronzeStore(tmp_path)
    payload = phase3a.bronze_payload()
    artifact = store.write(payload=payload, retrieval=_retrieval(), ingest_date=INGEST_DATE)

    assert artifact.metadata_path.exists()
    metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
    assert metadata["provider"] == phase3a.PROVIDER
    assert metadata["requested_range"] == "2019-06-24..2019-06-28"
    assert b"requested_range" not in payload, (
        "Metadata inside the payload would change the bytes and therefore the identity."
    )


def test_no_temporary_file_survives_a_write(tmp_path: Path) -> None:
    store = BronzeStore(tmp_path)
    artifact = store.write(
        payload=phase3a.bronze_payload(), retrieval=_retrieval(), ingest_date=INGEST_DATE
    )
    leftovers = sorted(artifact.path.parent.glob(".tmp-*"))
    assert leftovers == []


def test_an_ingestion_run_records_every_bronze_hash(tmp_path: Path) -> None:
    store = BronzeStore(tmp_path)
    artifact = store.write(
        payload=phase3a.bronze_payload(), retrieval=_retrieval(), ingest_date=INGEST_DATE
    )
    run = build_ingestion_run(
        ingestion_run_id="ing-synthetic-0001",
        retrieval=_retrieval(),
        started_at=datetime(2026, 8, 26, 11, 0, tzinfo=UTC),
        completed_at=datetime(2026, 8, 26, 11, 1, tzinfo=UTC),
        artifacts=(artifact,),
        record_count=5,
        new_record_count=5,
        is_backfill=True,
        code_commit_sha="0123456789abcdef0123456789abcdef01234567",
        config_version="research/synthetic.a1",
    )
    assert run.bronze_artifact_hashes == (artifact.content_sha256,)
    assert "uuid" not in run.ingestion_run_id


def test_importing_the_storage_modules_creates_nothing(tmp_path: Path) -> None:
    """A path value is not a directory. Binding a store touches no disk."""
    assert not Path(DEFAULT_DATA_ROOT).exists() or Path(DEFAULT_DATA_ROOT).is_dir()
    root = tmp_path / "never-created"
    BronzeStore(root)
    LocalTableStore(root)
    assert not root.exists()


# ---------------------------------------------------------------------------
# Local analytical storage
# ---------------------------------------------------------------------------


def test_a_table_is_byte_identical_across_two_builds(tmp_path: Path) -> None:
    """Determinism is what makes every "reproduces bit-identically" claim meaningful."""
    rows = [encode_price_bar(bar) for bar in phase3a.daily_bars()]
    shuffled = list(reversed(rows))

    first = LocalTableStore(tmp_path / "a").write_table(
        layer=StorageLayer.GOLD, dataset_version="v1", entity="price_bar", rows=rows
    )
    second = LocalTableStore(tmp_path / "b").write_table(
        layer=StorageLayer.GOLD, dataset_version="v1", entity="price_bar", rows=shuffled
    )
    assert first.content_hash == second.content_hash
    assert first.path.read_bytes() == second.path.read_bytes(), (
        "Row order in memory is not meaning. A store whose bytes depended on iteration "
        "order would make identity a coincidence."
    )


def test_rewriting_a_table_with_different_content_is_refused(tmp_path: Path) -> None:
    """Dataset versions are superseded, never mutated."""
    store = LocalTableStore(tmp_path)
    rows = [encode_price_bar(bar) for bar in phase3a.daily_bars()]
    store.write_table(layer=StorageLayer.GOLD, dataset_version="v1", entity="price_bar", rows=rows)
    with pytest.raises(ArtifactIntegrityError, match="superseded, never mutated"):
        store.write_table(
            layer=StorageLayer.GOLD, dataset_version="v1", entity="price_bar", rows=rows[:-1]
        )


def test_rewriting_a_table_with_identical_content_is_idempotent(tmp_path: Path) -> None:
    store = LocalTableStore(tmp_path)
    rows = [encode_price_bar(bar) for bar in phase3a.daily_bars()]
    first = store.write_table(
        layer=StorageLayer.GOLD, dataset_version="v1", entity="price_bar", rows=rows
    )
    second = store.write_table(
        layer=StorageLayer.GOLD, dataset_version="v1", entity="price_bar", rows=rows
    )
    assert first.content_hash == second.content_hash
    assert store.verify_table(second)


def test_reading_a_table_that_does_not_exist_is_a_refusal(tmp_path: Path) -> None:
    """An absent table is a refusal, not an empty result."""
    store = LocalTableStore(tmp_path)
    with pytest.raises(ArtifactIntegrityError, match="refusal, not an empty result"):
        store.read_table(layer=StorageLayer.GOLD, dataset_version="v1", entity="price_bar")


def test_a_tampered_table_fails_verification(tmp_path: Path) -> None:
    store = LocalTableStore(tmp_path)
    artifact = store.write_table(
        layer=StorageLayer.GOLD,
        dataset_version="v1",
        entity="price_bar",
        rows=[encode_price_bar(bar) for bar in phase3a.daily_bars()],
    )
    assert store.verify_table(artifact)
    artifact.path.write_bytes(artifact.path.read_bytes().replace(b"100.00", b"999.00"))
    assert not store.verify_table(artifact)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("records", "encode", "decode"),
    [
        (phase3a.daily_bars(), encode_price_bar, decode_price_bar),
        (phase3a.minute_bars(), encode_price_bar, decode_price_bar),
        (phase3a.corporate_actions(), encode_corporate_action, decode_corporate_action),
        (phase3a.sessions(), encode_market_session, decode_market_session),
        (phase3a.listings(), encode_listing, decode_listing),
        (phase3a.attributes(), encode_security_attribute, decode_security_attribute),
        (phase3a.ticker_history(), encode_ticker_history, decode_ticker_history),
    ],
)
def test_every_entity_with_a_decoder_round_trips_exactly(
    records: tuple[object, ...],
    encode: object,
    decode: object,
) -> None:
    """A table that decodes to something else lets a hash verify while values drift."""
    for record in records:
        assert decode(encode(record)) == record  # type: ignore[operator]


def test_canonical_rendering_refuses_a_naive_datetime() -> None:
    with pytest.raises(TypeError, match="naive datetime"):
        canonical_json({"when": datetime(2020, 1, 1, 12, 0)})


def test_canonical_rendering_refuses_a_float() -> None:
    """Prices are Decimal so a hash is a property of the value, not of the binary form."""
    with pytest.raises(TypeError, match="Refusing to canonicalise a float"):
        canonical_json({"price": 100.1})


def test_a_date_is_never_promoted_to_an_instant() -> None:
    assert canonical_json({"d": date(2019, 6, 24)}) != canonical_json(
        {"d": datetime(2019, 6, 24, tzinfo=UTC)}
    )


def test_mapping_key_order_does_not_change_a_content_hash() -> None:
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})
