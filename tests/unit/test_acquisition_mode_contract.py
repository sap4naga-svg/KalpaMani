"""The acquisition-mode contract, and the complete absence of what it replaced.

ADR-0013 replaced a provider-neutral ``is_backfill: bool`` with a closed
three-member vocabulary. The boolean could express only two of the three things a
retrieval can be, so a bounded provider-validation run had to claim to be a
production backfill or an incremental production update — and neither was true.

This is a **breaking pre-data correction**. No real Services Data has ever been
ingested under the retired schema, so there is nothing to migrate and nothing to
read back. That is why there is no compatibility reader here, no alias, no
conversion, no default and no dual-write — and why several tests below exist
purely to prove those absences rather than any behaviour.

Everything here is synthetic and offline. No network, AWS, credential, provider
or real-data path is constructible from this file.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from kalpamani.data.contracts.canonical import sha256_hex
from kalpamani.data.contracts.entities import IngestionRun
from kalpamani.data.contracts.errors import (
    AcquisitionIncompleteError,
    ObjectAlreadyExistsError,
)
from kalpamani.data.contracts.vocabulary import (
    AcquisitionMode,
    IngestionStatus,
)
from kalpamani.data.ingest.bronze import (
    ACQUISITION_COMPLETE,
    ACQUISITION_MODE_FIELD,
    ACQUISITION_PENDING,
    BronzeStore,
    RetrievalMetadata,
    _acquisition_body,
    _record_shape_problems,
    build_ingestion_run,
)
from kalpamani.data.ingest.bronze import (
    ACQUISITION_RECORD_FIELDS as LOCAL_ACQUISITION_RECORD_FIELDS,
)
from kalpamani.data.ingest.publication import (
    ACQUISITION_RECORD_FIELDS,
    BronzePublication,
    acquisition_record,
    publish_bronze_payload,
    require_recordable,
)
from kalpamani.data.ingest.sharadar.bronze import (
    publish_sharadar_payload,
    sharadar_retrieval_metadata,
)
from kalpamani.data.objectstore import InMemoryResearchObjectStore

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
INSTANT = datetime(2026, 8, 28, 13, 45, 0, tzinfo=UTC)
INGEST_DATE = date(2026, 8, 28)
SYNTHETIC_PAYLOAD = b"synthetic-opaque-payload"


def retrieval(
    mode: AcquisitionMode = AcquisitionMode.QUALIFICATION, **overrides: Any
) -> RetrievalMetadata:
    fields: dict[str, Any] = {
        "provider": "synthetic",
        "dataset": "stocks",
        "requested_range": "2024-01-02/2024-03-28",
        "retrieved_at": INSTANT,
        "source_schema_version": "synthetic-schema-v0",
        "ingestion_run_id": "synthetic-run-0001",
        "acquisition_mode": mode,
    }
    fields.update(overrides)
    return RetrievalMetadata(**fields)


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------


def test_the_vocabulary_has_exactly_three_members() -> None:
    """No `UNKNOWN`, no `NONE`, no generic historical mode, no extension point.

    Each would be a place for a caller who had not decided to record that they
    had not decided, and a durable record whose mode means "we did not say" is
    worse than one that could not be written.
    """
    assert [member.value for member in AcquisitionMode] == [
        "QUALIFICATION",
        "BACKFILL",
        "UPDATE",
    ]
    assert len(AcquisitionMode) == 3


@pytest.mark.parametrize("forbidden", ["UNKNOWN", "NONE", "HISTORICAL", "OTHER", "DEFAULT"])
def test_no_escape_hatch_member_exists(forbidden: str) -> None:
    assert forbidden not in {member.name for member in AcquisitionMode}


def test_the_vocabulary_is_exported_from_the_neutral_surface() -> None:
    from kalpamani.data.contracts import vocabulary

    assert "AcquisitionMode" in vocabulary.__all__


# ---------------------------------------------------------------------------
# Exact-member enforcement, with no default anywhere
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        0,
        1,
        None,
        "QUALIFICATION",
        "qualification",
        "Backfill",
        "UPDATE ",
        "HISTORICAL",
        "",
        ["QUALIFICATION"],
    ],
)
def test_retrieval_metadata_refuses_anything_but_an_exact_member(value: Any) -> None:
    """Booleans first: the retired representation was one, and accepting it would
    be the conversion ADR-0013 forbids."""
    with pytest.raises(AcquisitionIncompleteError, match="acquisition_mode"):
        retrieval(acquisition_mode=value)


def test_a_str_subclass_spelling_a_mode_is_refused() -> None:
    """A subclass can override `__eq__`, so a value that compares equal to a
    member is not a statement anybody made."""

    class Sneaky(str):
        def __eq__(self, other: object) -> bool:
            return True

        __hash__ = str.__hash__

    with pytest.raises(AcquisitionIncompleteError):
        retrieval(acquisition_mode=Sneaky("QUALIFICATION"))


@pytest.mark.parametrize("mode", list(AcquisitionMode))
def test_every_member_is_accepted(mode: AcquisitionMode) -> None:
    assert retrieval(mode).acquisition_mode is mode


def test_retrieval_metadata_has_no_default_mode() -> None:
    """A retrieval whose intent nobody stated is a retrieval nobody governed."""
    field = {f.name: f for f in dataclasses.fields(RetrievalMetadata)}["acquisition_mode"]
    assert field.default is dataclasses.MISSING
    assert field.default_factory is dataclasses.MISSING
    with pytest.raises(TypeError):
        RetrievalMetadata(  # type: ignore[call-arg]
            provider="synthetic",
            dataset="stocks",
            requested_range="2024-01-02/2024-03-28",
            retrieved_at=INSTANT,
            source_schema_version="synthetic-schema-v0",
            ingestion_run_id="synthetic-run-0001",
        )


@pytest.mark.parametrize(
    "function", [acquisition_record, publish_bronze_payload, publish_sharadar_payload]
)
def test_no_publication_api_defaults_the_mode(function: Any) -> None:
    """Either the parameter does not exist -- because the mode comes from the
    retrieval -- or it exists and is required."""
    parameter = inspect.signature(function).parameters.get("acquisition_mode")
    if parameter is not None:
        assert parameter.default is inspect.Parameter.empty


def test_the_provider_bridge_requires_an_explicit_mode() -> None:
    """A bridge is the last place that could invent one."""
    parameter = inspect.signature(sharadar_retrieval_metadata).parameters["acquisition_mode"]
    assert parameter.default is inspect.Parameter.empty
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


# ---------------------------------------------------------------------------
# The single source of truth
# ---------------------------------------------------------------------------


def test_the_ingestion_run_takes_its_mode_from_the_retrieval() -> None:
    """No second parameter, so there is no case where two copies disagree."""
    assert "acquisition_mode" not in inspect.signature(build_ingestion_run).parameters
    run = build_ingestion_run(
        retrieval=retrieval(AcquisitionMode.BACKFILL),
        started_at=INSTANT,
        completed_at=INSTANT,
        artifacts=(),
        record_count=0,
        new_record_count=0,
        code_commit_sha="synthetic-commit",
        config_version="synthetic-config-v0",
    )
    assert run.acquisition_mode is AcquisitionMode.BACKFILL


def test_the_publication_result_does_not_duplicate_the_mode() -> None:
    """It already carries the retrieval, and a second copy would be a second
    place to state one fact."""
    names = {field.name for field in dataclasses.fields(BronzePublication)}
    assert "acquisition_mode" not in names
    assert "is_backfill" not in names
    assert "retrieval" in names


def test_the_ingestion_run_refuses_a_non_member() -> None:
    with pytest.raises(ValueError, match="acquisition_mode"):
        IngestionRun(
            ingestion_run_id="synthetic-run-0001",
            provider="synthetic",
            dataset="stocks",
            started_at=INSTANT,
            completed_at=INSTANT,
            status=IngestionStatus.SUCCESS,
            requested_range="2024-01-02/2024-03-28",
            record_count=0,
            new_record_count=0,
            acquisition_mode="BACKFILL",  # type: ignore[arg-type]
            bronze_artifact_hashes=(),
            code_commit_sha="synthetic-commit",
            config_version="synthetic-config-v0",
        )


def test_counts_and_ranges_never_determine_the_mode() -> None:
    """A run that returned many old rows is not thereby a backfill.

    The same retrieval built with wildly different counts and an ancient range
    keeps the mode it was given, because the mode is a statement about what was
    asked for rather than an observation of what arrived.
    """
    for record_count, new_count, requested in (
        (0, 0, "2024-01-02/2024-03-28"),
        (1_000_000, 1_000_000, "1990-01-01/2026-08-27"),
        (5, 0, "SNAPSHOT"),
    ):
        run = build_ingestion_run(
            retrieval=retrieval(AcquisitionMode.UPDATE, requested_range=requested),
            started_at=INSTANT,
            completed_at=INSTANT,
            artifacts=(),
            record_count=record_count,
            new_record_count=new_count,
            code_commit_sha="synthetic-commit",
            config_version="synthetic-config-v0",
        )
        assert run.acquisition_mode is AcquisitionMode.UPDATE


# ---------------------------------------------------------------------------
# The durable record
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", list(AcquisitionMode))
def test_the_exact_durable_acquisition_record_for_each_mode(mode: AcquisitionMode) -> None:
    """The whole shape is pinned, not just the new field.

    There is no metadata schema-version field on this record, and
    ``source_schema_version`` describes the *provider's* payload schema rather
    than this record's, so it must not be repurposed. Pinning the exact shape
    here is what makes a future change to it visible (ADR-0013).
    """
    record = acquisition_record(retrieval=retrieval(mode), content_sha256="0" * 64, byte_count=7)
    assert record == {
        "provider": "synthetic",
        "dataset": "stocks",
        "requested_range": "2024-01-02/2024-03-28",
        "retrieved_at": "2026-08-28T13:45:00+00:00",
        "source_schema_version": "synthetic-schema-v0",
        "ingestion_run_id": "synthetic-run-0001",
        "content_sha256": "0" * 64,
        "byte_count": 7,
        "acquisition_mode": mode.value,
        "classification": "LICENSED",
    }
    require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)


def test_the_serialised_mode_is_a_plain_string_not_an_enum_member() -> None:
    """A record is bytes on a disk, and a `StrEnum` is a `str` subclass whose
    identity is not what a later reader gets back."""
    record = acquisition_record(
        retrieval=retrieval(AcquisitionMode.BACKFILL), content_sha256="0" * 64, byte_count=1
    )
    assert type(record["acquisition_mode"]) is str
    assert json.loads(json.dumps(record))["acquisition_mode"] == "BACKFILL"


def test_the_retired_key_is_not_in_the_allowlist() -> None:
    assert "is_backfill" not in ACQUISITION_RECORD_FIELDS
    assert "acquisition_mode" in ACQUISITION_RECORD_FIELDS


@pytest.mark.parametrize("mode", list(AcquisitionMode))
def test_the_object_store_record_is_what_the_builder_produced(mode: AcquisitionMode) -> None:
    """What the store holds is exactly what the record builder emitted.

    Named for what it checks. An earlier revision called this a local/object-store
    comparison, which it was not: both sides came from ``acquisition_record``, the
    object-store builder. The genuine cross-store comparison is
    ``test_the_two_stores_agree_on_the_shared_acquisition_fields`` below.
    """
    store = InMemoryResearchObjectStore()
    published = publish_bronze_payload(
        store=store,
        payload=SYNTHETIC_PAYLOAD,
        retrieval=retrieval(mode, ingestion_run_id=f"synthetic-run-{mode.value.lower()}"),
    )
    stored = json.loads(store.read(published.acquisition_key).decode("utf-8"))
    assert stored == acquisition_record(
        retrieval=published.retrieval,
        content_sha256=published.content_sha256,
        byte_count=published.byte_count,
    )
    assert stored["acquisition_mode"] == mode.value
    assert "is_backfill" not in stored


# ---------------------------------------------------------------------------
# The filesystem store, which the first revision of this migration missed
# ---------------------------------------------------------------------------
#
# `RetrievalMetadata` carried the mode and the object-store record emitted it,
# but `_acquisition_body` still returned the pre-migration local shape. The local
# store therefore recorded no mode at all -- and because `_require_same_retrieval`
# compares every field except `status`, restating one acquisition under a
# *different* mode was accepted instead of refused. Nothing caught it, because no
# test constructed a filesystem record.


def local_write(
    root: Path,
    mode: AcquisitionMode,
    *,
    run_id: str = "synthetic-run-0001",
) -> tuple[BronzeStore, Path]:
    """One synthetic acquisition, written through a real filesystem store."""
    store = BronzeStore(root)
    artifact = store.write(
        payload=SYNTHETIC_PAYLOAD,
        retrieval=retrieval(mode, ingestion_run_id=run_id),
        ingest_date=INGEST_DATE,
    )
    return store, artifact.acquisition_path


@pytest.mark.parametrize("mode", list(AcquisitionMode))
def test_the_filesystem_record_carries_the_exact_mode_token(
    mode: AcquisitionMode, tmp_path: Path
) -> None:
    """Read back from disk, not from the builder that wrote it."""
    _, path = local_write(tmp_path, mode)
    record = json.loads(path.read_text(encoding="utf-8"))

    assert "acquisition_mode" in record
    assert type(record["acquisition_mode"]) is str
    assert record["acquisition_mode"] == mode.value
    assert "is_backfill" not in record
    assert record["status"] == ACQUISITION_COMPLETE


@pytest.mark.parametrize("status", [ACQUISITION_PENDING, ACQUISITION_COMPLETE])
def test_both_record_states_carry_the_same_mode(status: str) -> None:
    """A PENDING record that omitted the mode would let a repair complete an
    acquisition whose declared intent was never written down."""
    body = _acquisition_body(
        retrieval(AcquisitionMode.BACKFILL),
        "0" * 64,
        7,
        INGEST_DATE,
        status=status,
    )
    assert body["acquisition_mode"] == "BACKFILL"
    assert type(body["acquisition_mode"]) is str
    assert "is_backfill" not in body


def test_the_filesystem_body_reads_the_mode_only_from_the_retrieval() -> None:
    """No second parameter, so there is no second source to disagree."""
    parameters = set(inspect.signature(_acquisition_body).parameters)
    assert "acquisition_mode" not in parameters
    assert "is_backfill" not in parameters


@pytest.mark.parametrize("mode", list(AcquisitionMode))
def test_the_same_local_identity_with_the_same_mode_is_idempotent(
    mode: AcquisitionMode, tmp_path: Path
) -> None:
    store, path = local_write(tmp_path, mode)
    before = path.read_bytes()
    again = store.write(
        payload=SYNTHETIC_PAYLOAD,
        retrieval=retrieval(mode, ingestion_run_id="synthetic-run-0001"),
        ingest_date=INGEST_DATE,
    )
    assert again.content_written is False
    assert path.read_bytes() == before


def test_the_same_local_identity_with_a_different_mode_is_refused(tmp_path: Path) -> None:
    """The contradiction the first revision could not detect.

    ``_require_same_retrieval`` compares every field except ``status``, so once
    the mode is in the body a restatement under a different one is caught by
    machinery that already existed -- which is why the fix is one field rather
    than a new rule.
    """
    store, path = local_write(tmp_path, AcquisitionMode.QUALIFICATION)
    before = path.read_bytes()

    with pytest.raises(AcquisitionIncompleteError, match="acquisition_mode"):
        store.write(
            payload=SYNTHETIC_PAYLOAD,
            retrieval=retrieval(AcquisitionMode.BACKFILL, ingestion_run_id="synthetic-run-0001"),
            ingest_date=INGEST_DATE,
        )

    assert path.read_bytes() == before, "the refused attempt must leave the record untouched"


def object_store_snapshot(store: InMemoryResearchObjectStore) -> dict[str, tuple[bytes, str]]:
    """Every stored object as (payload, admitted digest), keyed by logical name.

    The payload alone would not be a complete snapshot: the store admits an object
    under a digest and serves reads against it, so a changed digest with unchanged
    bytes is a real difference this must be able to see.
    """
    return {
        name: (payload, store.stored_digest(name) or "")
        for name, payload in store.snapshot().items()
    }


def test_the_object_store_refuses_the_same_change() -> None:
    """The same property on the other storage path, so neither is the only one
    that holds it -- and the store is unchanged afterwards.

    The ADR claims a contradictory attempt leaves the stored record alone on
    **both** paths. Asserting only that the call raises would leave that claim
    resting on the exception, which says nothing about what the store did before
    reaching it: a publication appends a claim, a payload and an acquisition
    record, so a partial write is exactly the failure worth ruling out.
    """
    store = InMemoryResearchObjectStore()
    publish_bronze_payload(
        store=store,
        payload=SYNTHETIC_PAYLOAD,
        retrieval=retrieval(AcquisitionMode.QUALIFICATION),
    )
    before = object_store_snapshot(store)
    assert before, "the first publication must have stored something to compare against"

    with pytest.raises(ObjectAlreadyExistsError):
        publish_bronze_payload(
            store=store,
            payload=SYNTHETIC_PAYLOAD,
            retrieval=retrieval(AcquisitionMode.BACKFILL),
        )

    after = object_store_snapshot(store)
    assert set(after) == set(before), "the refused attempt added or removed an object"
    assert after == before, "the refused attempt changed stored bytes or a stored digest"


#: What both stores must agree on. Everything else is envelope.
SHARED_ACQUISITION_FIELDS = (
    "provider",
    "dataset",
    "requested_range",
    "retrieved_at",
    "source_schema_version",
    "ingestion_run_id",
    "content_sha256",
    "byte_count",
    "acquisition_mode",
)


@pytest.mark.parametrize("mode", list(AcquisitionMode))
def test_the_two_stores_agree_on_the_shared_acquisition_fields(
    mode: AcquisitionMode, tmp_path: Path
) -> None:
    """A real filesystem record against a real object-store record.

    **Not** a whole-record equality: the two envelopes differ on purpose, and
    asserting they are identical would either be false or force one store to
    carry the other's fields. What must agree is the acquisition metadata they
    both describe.
    """
    _, path = local_write(tmp_path, mode, run_id=f"synthetic-run-{mode.value.lower()}")
    local = json.loads(path.read_text(encoding="utf-8"))

    remote_store = InMemoryResearchObjectStore()
    published = publish_bronze_payload(
        store=remote_store,
        payload=SYNTHETIC_PAYLOAD,
        retrieval=retrieval(mode, ingestion_run_id=f"synthetic-run-{mode.value.lower()}"),
    )
    remote = json.loads(remote_store.read(published.acquisition_key).decode("utf-8"))

    for field in SHARED_ACQUISITION_FIELDS:
        assert local[field] == remote[field], f"{field} disagrees between the two stores"
    assert local["acquisition_mode"] == remote["acquisition_mode"] == mode.value
    assert "is_backfill" not in local and "is_backfill" not in remote


# ---------------------------------------------------------------------------
# Completeness verification, which round 1 left fail-open
# ---------------------------------------------------------------------------
#
# Round 1 put the mode into the record. It did not make anything *check* the
# record. `_require_same_retrieval` compares the mode only during a republish, so
# a COMPLETE record already on disk could carry no mode, an unknown one, a
# non-string one, the retired key instead of the new field, or both keys at once,
# and `require_complete()` would still pass it. Malformed durable metadata has to
# be discoverable by reading the store, not by writing to it again.


def record_path(store: BronzeStore, mode: AcquisitionMode, run_id: str) -> Path:
    """The on-disk acquisition record for one synthetic write."""
    return store.acquisition_path(
        provider="synthetic",
        dataset="stocks",
        ingest_date=INGEST_DATE,
        digest=sha256_hex(SYNTHETIC_PAYLOAD),
        ingestion_run_id=run_id,
    )


def completed(
    tmp_path: Path, mode: AcquisitionMode = AcquisitionMode.QUALIFICATION
) -> tuple[BronzeStore, Path, bytes]:
    """A store holding one valid COMPLETE acquisition, and that record's exact bytes."""
    store, path = local_write(tmp_path, mode)
    return store, path, path.read_bytes()


def verify(store: BronzeStore) -> None:
    store.require_complete(provider="synthetic", dataset="stocks", ingest_date=INGEST_DATE)


def audit(store: BronzeStore) -> tuple[str, ...]:
    return store.audit_acquisitions(provider="synthetic", dataset="stocks", ingest_date=INGEST_DATE)


def rewrite(path: Path, mutate: Any) -> None:
    """Tamper with the durable record in place, exactly as a bad writer would."""
    record = json.loads(path.read_text(encoding="utf-8"))
    mutate(record)
    path.write_text(json.dumps(record), encoding="utf-8")


@pytest.mark.parametrize("mode", list(AcquisitionMode))
def test_verification_accepts_a_valid_complete_record_for_every_mode(
    mode: AcquisitionMode, tmp_path: Path
) -> None:
    store, _, _ = completed(tmp_path, mode)
    assert audit(store) == ()
    verify(store)  # must not raise


def test_a_record_with_no_acquisition_mode_is_refused(tmp_path: Path) -> None:
    """The exact defect round 1 left behind: a record written before the mode
    existed would have verified clean forever."""
    store, path, _ = completed(tmp_path)
    rewrite(path, lambda record: record.pop(ACQUISITION_MODE_FIELD))

    problems = audit(store)
    assert problems, "a record with no acquisition mode must be an audit problem"
    assert any("missing required field" in problem for problem in problems)
    with pytest.raises(AcquisitionIncompleteError):
        verify(store)


#: Every way a durable mode can be wrong, each refused on its own.
#:
#: ``"qualification"`` and ``"QUALIFICATION "`` are the two near-misses that a
#: forgiving reader would normalise; they are refusals here, because a reader that
#: repairs its input decides what the record meant.
INVALID_MODES: tuple[tuple[str, Any], ...] = (
    ("unknown-token", "UNKNOWN"),
    ("wrong-case", "qualification"),
    ("trailing-space", "QUALIFICATION "),
    ("false", False),
    ("null", None),
    ("integer", 1),
)


@pytest.mark.parametrize(("label", "value"), INVALID_MODES, ids=[case[0] for case in INVALID_MODES])
def test_each_invalid_durable_mode_is_refused_on_its_own(
    label: str, value: Any, tmp_path: Path
) -> None:
    store, path, _ = completed(tmp_path)
    rewrite(path, lambda record: record.__setitem__(ACQUISITION_MODE_FIELD, value))

    assert audit(store), f"{label} was accepted by the audit"
    with pytest.raises(AcquisitionIncompleteError):
        verify(store)


def test_a_str_subclass_mode_is_refused_where_it_could_arrive() -> None:
    """JSON never yields a ``str`` subclass, so this cannot reach the verifier
    through a file -- which is exactly why the check is on the shape helper
    rather than only on decoded input. A subclass compares equal to its token and
    would otherwise pass an ``in`` test while being a different type.
    """

    class Hostile(str):
        pass

    valid = _acquisition_body(retrieval(), "0" * 64, 1, INGEST_DATE, status=ACQUISITION_COMPLETE)
    assert _record_shape_problems(valid) == []

    tampered = dict(valid)
    tampered[ACQUISITION_MODE_FIELD] = Hostile("QUALIFICATION")
    assert tampered[ACQUISITION_MODE_FIELD] == "QUALIFICATION"
    assert _record_shape_problems(tampered), "a str subclass is not an exact built-in str"


def test_a_valid_mode_beside_the_retired_key_is_refused(tmp_path: Path) -> None:
    """A dual-written record is refused rather than read past.

    Two representations of one fact is the dual-write ADR-0013 rejected, and the
    case that matters is the one where they disagree.
    """
    store, path, _ = completed(tmp_path)
    rewrite(path, lambda record: record.__setitem__("is_backfill", False))

    assert audit(store), "acquisition_mode plus the retired key must be refused"
    with pytest.raises(AcquisitionIncompleteError):
        verify(store)


def test_the_retired_key_alone_is_refused(tmp_path: Path) -> None:
    """A record written entirely under the retired schema. There is no reader for
    it, and none is added: it is republished, not translated."""
    store, path, _ = completed(tmp_path)

    def retire(record: dict[str, Any]) -> None:
        record.pop(ACQUISITION_MODE_FIELD)
        record["is_backfill"] = False

    rewrite(path, retire)

    problems = audit(store)
    assert any("missing required field" in problem for problem in problems)
    assert any("does not define" in problem for problem in problems)
    with pytest.raises(AcquisitionIncompleteError):
        verify(store)


def test_an_arbitrary_undefined_field_is_refused(tmp_path: Path) -> None:
    """The allowlist is closed, so the retired key needs no special case: it is
    refused as one undefined field among any others."""
    store, path, _ = completed(tmp_path)
    rewrite(path, lambda record: record.__setitem__("synthetic_extra", "value"))

    assert any("does not define" in problem for problem in audit(store))
    with pytest.raises(AcquisitionIncompleteError):
        verify(store)


def test_the_allowlist_is_the_exact_written_shape_and_excludes_the_retired_key() -> None:
    written = set(
        _acquisition_body(retrieval(), "0" * 64, 1, INGEST_DATE, status=ACQUISITION_COMPLETE)
    )
    assert written == set(LOCAL_ACQUISITION_RECORD_FIELDS)
    assert "is_backfill" not in LOCAL_ACQUISITION_RECORD_FIELDS
    assert ACQUISITION_MODE_FIELD in LOCAL_ACQUISITION_RECORD_FIELDS


def test_a_malformed_record_is_refused_without_any_republish_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verification must not depend on writing.

    Before this round the only thing that compared the mode ran inside
    :meth:`BronzeStore.write`, so discovering a bad record meant attempting to
    publish over it. Here ``write`` is made to explode: if verification reaches
    it, the test fails loudly rather than passing for the wrong reason.
    """
    store, path, _ = completed(tmp_path)
    rewrite(path, lambda record: record.__setitem__(ACQUISITION_MODE_FIELD, "UNKNOWN"))

    def forbidden(*_: Any, **__: Any) -> None:
        raise AssertionError("verification attempted a republish")

    monkeypatch.setattr(BronzeStore, "write", forbidden)

    assert audit(store)
    with pytest.raises(AcquisitionIncompleteError):
        verify(store)


def test_restoring_the_exact_record_makes_verification_pass_again(tmp_path: Path) -> None:
    """The refusal is a property of the bytes on disk, not a latch."""
    store, path, original = completed(tmp_path)
    verify(store)

    rewrite(path, lambda record: record.__setitem__(ACQUISITION_MODE_FIELD, "UNKNOWN"))
    with pytest.raises(AcquisitionIncompleteError):
        verify(store)

    path.write_bytes(original)
    assert path.read_bytes() == original
    assert audit(store) == ()
    verify(store)


#: A value no message may repeat. Distinctive enough that a substring test is
#: meaningful, and shaped like the thing that would actually hurt.
LEAK_CANARY = "CANARY-a1b2c3-do-not-echo"


def test_a_malformed_mode_value_never_reaches_the_audit_or_the_exception(
    tmp_path: Path,
) -> None:
    """A durable record can hold anything a bad writer put there, so the value is
    the one piece of text a verification message must not repeat."""
    store, path, _ = completed(tmp_path)
    rewrite(path, lambda record: record.__setitem__(ACQUISITION_MODE_FIELD, LEAK_CANARY))

    problems = audit(store)
    assert problems
    assert not any(LEAK_CANARY in problem for problem in problems)

    with pytest.raises(AcquisitionIncompleteError) as raised:
        verify(store)
    assert LEAK_CANARY not in str(raised.value)


def test_an_undefined_field_name_is_counted_rather_than_repeated(tmp_path: Path) -> None:
    """A key this store did not write is uncontrolled text too, not only a value."""
    store, path, _ = completed(tmp_path)
    rewrite(path, lambda record: record.__setitem__(LEAK_CANARY, "x"))

    problems = audit(store)
    assert any("does not define" in problem for problem in problems)
    assert not any(LEAK_CANARY in problem for problem in problems)
    with pytest.raises(AcquisitionIncompleteError) as raised:
        verify(store)
    assert LEAK_CANARY not in str(raised.value)


def test_the_two_envelopes_differ_deliberately_and_the_difference_is_named() -> None:
    """Documented rather than hidden.

    The filesystem record carries ``status``, ``ingest_date`` and ``notes``: it
    completes in two steps and is repaired in place, and ``notes`` belongs to the
    A1 writer. The object-store record carries ``classification`` and
    deliberately has **no** free-text field, because durable metadata on that path
    has no place for human text.
    """
    local_only = {"status", "ingest_date", "notes"}
    remote_only = {"classification"}

    local_fields = set(
        _acquisition_body(retrieval(), "0" * 64, 1, INGEST_DATE, status=ACQUISITION_COMPLETE)
    )
    remote_fields = set(
        acquisition_record(retrieval=retrieval(), content_sha256="0" * 64, byte_count=1)
    )

    assert local_fields - remote_fields == local_only
    assert remote_fields - local_fields == remote_only
    assert set(SHARED_ACQUISITION_FIELDS) == local_fields & remote_fields
    assert "notes" not in remote_fields, "the object-store record has no free-text field"


def test_the_three_write_order_is_unchanged() -> None:
    """Claim, payload, acquisition record -- the migration touched none of it."""
    store = InMemoryResearchObjectStore()
    published = publish_bronze_payload(
        store=store, payload=b"synthetic-opaque-payload", retrieval=retrieval()
    )
    assert published.claim_key.logical_key.startswith("licensed/bronze/_acquisition_claims/")
    assert "/objects/sha256/" in published.payload_key.logical_key
    assert "/acquisitions/" in published.acquisition_key.logical_key
    assert (
        published.claim_written,
        published.payload_written,
        published.acquisition_written,
    ) == (True, True, True)


# ---------------------------------------------------------------------------
# The retired representation is gone from executable code
# ---------------------------------------------------------------------------


def _python_files(root: Path) -> list[Path]:
    return [p for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts]


def _executable(path: Path) -> str:
    """The module's code with every docstring removed.

    A raw scan would fire on the prose explaining what was retired, which would
    either weaken the guard or forbid explaining why it exists.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


#: Every way the retired name could still be executable: an identifier, an
#: attribute, a parameter, a dataclass field, a dict key, an export.
LEGACY_NAMES = ("is_backfill", "QUALIFICATION_IS_BACKFILL", "IS_BACKFILL")


@pytest.mark.parametrize("path", _python_files(SRC), ids=lambda p: p.name)
def test_no_source_module_carries_the_retired_identifier(path: Path) -> None:
    """Checked against docstring-stripped code, so the three places that *explain*
    the retirement do not weaken the guard."""
    code = _executable(path)
    for name in LEGACY_NAMES:
        assert name not in code, f"{path.relative_to(PROJECT_ROOT)} still names {name}"


def test_no_module_exports_the_retired_constant() -> None:
    import kalpamani.data.ingest.sharadar as provider
    from kalpamani.data.ingest.sharadar import runtime

    for module in (provider, runtime):
        assert not hasattr(module, "QUALIFICATION_IS_BACKFILL")
        assert "QUALIFICATION_IS_BACKFILL" not in getattr(module, "__all__", ())


def test_no_alias_property_or_converter_exists() -> None:
    """No deprecated property, no boolean-to-mode function, no dual-write."""
    for cls in (RetrievalMetadata, IngestionRun, BronzePublication):
        assert not hasattr(cls, "is_backfill")
        names = {field.name for field in dataclasses.fields(cls)}
        assert "is_backfill" not in names
    for path in _python_files(SRC):
        code = _executable(path)
        for converter in ("bool(", "from_bool", "to_bool", "as_backfill", "legacy_mode"):
            if converter == "bool(" and "objectstore" in path.name:
                continue
            assert f"acquisition_mode={converter}" not in code


def test_the_qualification_runtime_records_the_single_source_mode() -> None:
    """The runtime states the mode once, through the constant that owns it.

    An earlier revision asserted the runtime named ``AcquisitionMode.QUALIFICATION``
    *directly*. That was right while the runtime was the only place stating it,
    and wrong once ADR-0014's composition root stated it too: two independent
    spellings of one fact is a dual-write, and the interesting case is the one
    where they disagree. The constant now lives in ``qualification.py``; what
    this checks is that the runtime uses it and resolves to QUALIFICATION.
    """
    from kalpamani.data.ingest.sharadar import qualification
    from kalpamani.data.ingest.sharadar import runtime as module

    assert qualification.QUALIFICATION_ACQUISITION_MODE is AcquisitionMode.QUALIFICATION
    code = _executable(Path(module.__file__))
    assert "acquisition_mode=QUALIFICATION_ACQUISITION_MODE" in code
    assert "AcquisitionMode.BACKFILL" not in code
    assert "AcquisitionMode.UPDATE" not in code


def test_no_mode_is_inferred_from_data() -> None:
    """The mode is a statement, never a derivation.

    Checked structurally rather than by searching for words: "derive it from the
    data" is written as a conditional expression, so no assignment to
    ``acquisition_mode`` -- as a keyword argument, a name or an attribute -- may
    be one. A text scan would have to guess at every phrasing of a range check,
    a count comparison or a coverage lookup.
    """
    for path in _python_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "acquisition_mode":
                assert not isinstance(node.value, ast.IfExp), (
                    f"{path.name}:{node.value.lineno} derives the mode conditionally"
                )
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    named = isinstance(target, ast.Name) and target.id == "acquisition_mode"
                    attributed = (
                        isinstance(target, ast.Attribute) and target.attr == "acquisition_mode"
                    )
                    if named or attributed:
                        assert not isinstance(node.value, ast.IfExp)
