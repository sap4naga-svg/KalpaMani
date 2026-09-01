"""ADR-0020: the request-scoped qualification payload identity.

Three questions, and they are deliberately separated:

- **is the name right** -- the pure builder, the canonical ordinal and what the name
  is forbidden to contain;
- **does the acquisition write it** -- the router that binds the accepted Bronze
  triple to it, without acquiring a single read;
- **does the assessment insist on it** -- the reconstruction that must match exactly
  before any payload byte is retrieved.

Synthetic throughout: invented subjects, invented bytes, inert clients. No provider
request, no AWS call, no licensed row, no private value.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.sharadar_empirical import (
    EXECUTION_ID,
    EXECUTION_ID_A,
    EXECUTION_ID_B,
    LEAK_CANARIES,
    RUN_B_INSTANT,
    RUN_INSTANT,
    SYNTHETIC_BUCKET,
    SYNTHETIC_SUBJECTS,
    FakeMonotonic,
    FakeS3Client,
    FixedClock,
    PagedTransport,
    credential,
    is_qualification_payload_key,
    synthetic_inventory,
)
from kalpamani.data.contracts.canonical import sha256_hex
from kalpamani.data.contracts.errors import ObjectStoreError
from kalpamani.data.contracts.vocabulary import DataClassification
from kalpamani.data.ingest.sharadar.qualification import CANONICAL_DATASET_ORDER
from kalpamani.data.objectstore import ObjectKey, physical_key
from kalpamani.data.qualify.sharadar.acquisition import (
    AcquisitionStatus,
    run_empirical_acquisition,
)
from kalpamani.data.qualify.sharadar.assessment import (
    AssessmentError,
    AssessmentStatus,
    run_combined_assessment,
)
from kalpamani.data.qualify.sharadar.plan import EMPIRICAL_REQUEST_COUNT, build_empirical_plan
from kalpamani.data.qualify.sharadar.publication import (
    LicensedWriteOnlyPublisher,
    NameOccupiedError,
    QualificationKeyError,
    QualificationPayloadRouter,
    qualification_payload_key,
    request_ordinal_map,
    request_ordinal_segment,
)
from kalpamani.data.qualify.sharadar.read import LicensedObjectReader

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "kalpamani"

PAYLOAD: Final = b"synthetic-qualification-payload"
DIGEST = sha256_hex(PAYLOAD)
OTHER_DIGEST = sha256_hex(b"a different synthetic qualification payload")
ASSESSMENT_ID = "synthetic-assessment-0001"


# -- helpers -------------------------------------------------------------------


def _key(
    *,
    dataset: str = "stocks",
    execution_id: str = EXECUTION_ID,
    request_ordinal: int = 0,
    content_sha256: str = DIGEST,
) -> ObjectKey:
    return qualification_payload_key(
        dataset=dataset,
        execution_id=execution_id,
        request_ordinal=request_ordinal,
        content_sha256=content_sha256,
    )


def _coordinates() -> list[tuple[str, str, int]]:
    """The locked inventory's request coordinates, from the plan itself."""
    plan = build_empirical_plan(
        inventory=synthetic_inventory(), execution_id=EXECUTION_ID, instant=RUN_INSTANT
    )
    return [
        (request.dataset.value, request.ticker, request.page.skip)
        for request in plan.plan.requests()
    ]


def _acquire(
    *,
    s3: FakeS3Client,
    execution_id: str = EXECUTION_ID,
    instant: Any = RUN_INSTANT,
    transport: PagedTransport | None = None,
) -> Any:
    monotonic = FakeMonotonic()
    variant = "B" if execution_id == EXECUTION_ID_B else "A"
    return run_empirical_acquisition(
        credential=credential(),
        transport=transport if transport is not None else PagedTransport(byte_variant=variant),
        monotonic=monotonic,
        sleeper=monotonic.sleep,
        s3_client=s3,
        licensed_bucket=SYNTHETIC_BUCKET,
        clock=FixedClock(instant=instant),
        inventory=synthetic_inventory(),
        execution_id=execution_id,
    )


def _acquire_pair() -> FakeS3Client:
    s3 = FakeS3Client()
    assert _acquire(s3=s3, execution_id=EXECUTION_ID_A).status is AcquisitionStatus.COMPLETED
    assert (
        _acquire(s3=s3, execution_id=EXECUTION_ID_B, instant=RUN_B_INSTANT).status
        is AcquisitionStatus.COMPLETED
    )
    return s3


def _assess(s3: FakeS3Client) -> Any:
    return run_combined_assessment(
        reader=LicensedObjectReader(client=s3, licensed_bucket=SYNTHETIC_BUCKET),
        run_a_execution_id=EXECUTION_ID_A,
        run_b_execution_id=EXECUTION_ID_B,
        assessment_id=ASSESSMENT_ID,
        clock=FixedClock(),
    )


def _locator_physical_key(execution_id: str) -> str:
    # Physical, not logical: the classification is the bucket, so it is not a segment.
    return f"qualification/sharadar/locators/{execution_id}.json"


# -- 1. the name ---------------------------------------------------------------


def test_the_key_has_the_exact_accepted_path_shape() -> None:
    # Spelled as a literal, not assembled from the module's own constants: a shape
    # built from the same pieces the builder uses would agree with any rename.
    assert _key().logical_key == (
        f"licensed/bronze/sharadar/stocks/qualification/{EXECUTION_ID}/requests/00/sha256/{DIGEST}"
    )


def test_the_key_stays_licensed_bronze_with_the_digest_last() -> None:
    key = _key(request_ordinal=47)
    assert key.classification is DataClassification.LICENSED
    assert key.logical_key.startswith("licensed/bronze/")
    assert key.segments[-1] == DIGEST
    assert key.segments[-2] == "sha256"
    assert key.content_sha256 == DIGEST


def test_the_same_execution_ordinal_and_bytes_derive_the_same_key() -> None:
    # Determinism is what makes a retry of one publication target one name.
    assert _key().logical_key == _key().logical_key


def test_identical_bytes_at_two_ordinals_in_one_execution_derive_two_keys() -> None:
    assert _key(request_ordinal=0).logical_key != _key(request_ordinal=1).logical_key


def test_identical_bytes_at_one_ordinal_in_two_executions_derive_two_keys() -> None:
    assert (
        _key(execution_id=EXECUTION_ID_A).logical_key
        != _key(execution_id=EXECUTION_ID_B).logical_key
    )


def test_changed_bytes_change_the_digest_and_the_key() -> None:
    assert DIGEST != OTHER_DIGEST
    assert _key().logical_key != _key(content_sha256=OTHER_DIGEST).logical_key


def test_the_whole_locked_inventory_derives_48_distinct_keys_from_one_digest() -> None:
    # The defect, stated as its own test: one digest, 48 governed requests, and the
    # superseded derivation produced one name per dataset.
    keys = {
        _key(dataset=dataset, request_ordinal=ordinal).logical_key
        for ordinal in range(EMPIRICAL_REQUEST_COUNT)
        for dataset in ("stocks",)
    }
    assert len(keys) == EMPIRICAL_REQUEST_COUNT


def test_the_ordinal_segment_is_two_digits_and_sorts_as_it_counts() -> None:
    segments = [request_ordinal_segment(ordinal) for ordinal in range(EMPIRICAL_REQUEST_COUNT)]
    assert segments[0] == "00"
    assert segments[-1] == "47"
    assert all(len(segment) == 2 and segment.isdigit() for segment in segments)
    assert sorted(segments) == segments


@pytest.mark.parametrize("ordinal", [-1, EMPIRICAL_REQUEST_COUNT, 100, True, 1.0, "00", None])
def test_an_ordinal_outside_the_locked_inventory_fails_closed(ordinal: object) -> None:
    with pytest.raises(QualificationKeyError):
        request_ordinal_segment(ordinal)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("content_sha256", DIGEST.upper()),
        ("content_sha256", DIGEST[:63]),
        ("content_sha256", "not-a-digest"),
        ("dataset", "../escape"),
        ("dataset", ""),
        ("execution_id", "con"),
        ("execution_id", "_reserved"),
        ("execution_id", "a/b"),
    ],
)
def test_a_malformed_component_fails_closed(field: str, value: str) -> None:
    with pytest.raises(QualificationKeyError):
        _key(**{field: value})  # type: ignore[arg-type]


def test_no_private_value_can_appear_in_a_derived_key() -> None:
    # Every subject in the synthetic inventory, every leak canary, the bucket and the
    # requested window -- none of them is an input to the derivation, so none of them
    # can be in the output. Asserted over the whole locked inventory rather than one
    # sample key.
    ordinals = request_ordinal_map(_coordinates())
    rendered = " ".join(
        _key(dataset=dataset, request_ordinal=ordinal).logical_key
        for (dataset, _, _), ordinal in ordinals.items()
    )
    for canary in (*LEAK_CANARIES, *SYNTHETIC_SUBJECTS, SYNTHETIC_BUCKET, "1998-01-01"):
        assert canary not in rendered
    for forbidden in ("api_key", "apiKey", "?", "&", "https", "amazonaws"):
        assert forbidden not in rendered


# -- 2. the canonical ordinal --------------------------------------------------


def test_the_ordinal_map_is_the_locked_inventory_mapped_one_to_one() -> None:
    ordinals = request_ordinal_map(_coordinates())
    assert len(ordinals) == EMPIRICAL_REQUEST_COUNT == 48
    assert sorted(ordinals.values()) == list(range(EMPIRICAL_REQUEST_COUNT))


def test_the_ordinal_map_agrees_with_the_plans_own_emission_order() -> None:
    # The two derivations that must never drift: the acquisition binds ordinals from
    # this map, and the plan is what the runtime iterates. A disagreement would name
    # objects after requests other than the ones that produced them.
    coordinates = _coordinates()
    ordinals = request_ordinal_map(coordinates)
    assert [ordinals[coordinate] for coordinate in coordinates] == list(
        range(EMPIRICAL_REQUEST_COUNT)
    )


def test_the_ordinal_map_ignores_input_order() -> None:
    coordinates = _coordinates()
    shuffled = list(reversed(coordinates))
    rotated = coordinates[17:] + coordinates[:17]
    assert shuffled != coordinates
    assert request_ordinal_map(shuffled) == request_ordinal_map(coordinates)
    assert request_ordinal_map(rotated) == request_ordinal_map(coordinates)


def test_the_ordinal_map_orders_dataset_then_subject_then_page() -> None:
    ordinals = request_ordinal_map(_coordinates())
    ordered = sorted(ordinals, key=lambda coordinate: ordinals[coordinate])
    dataset_rank = {dataset.value: index for index, dataset in enumerate(CANONICAL_DATASET_ORDER)}
    ranked = [(dataset_rank[dataset], subject, skip) for dataset, subject, skip in ordered]
    assert ranked == sorted(ranked)


@pytest.mark.parametrize(
    "coordinates",
    [
        [],
        [("stocks", "AAA", 0)],
        [("stocks", "AAA", 0)] * EMPIRICAL_REQUEST_COUNT,
        [("fundamentals", "AAA", index) for index in range(EMPIRICAL_REQUEST_COUNT)],
        [("stocks", "AAA", -index) for index in range(EMPIRICAL_REQUEST_COUNT)],
    ],
)
def test_an_inventory_that_is_not_the_locked_one_has_no_ordinal_map(
    coordinates: list[tuple[str, str, int]],
) -> None:
    with pytest.raises(QualificationKeyError):
        request_ordinal_map(coordinates)


# -- 3. the router writes it, and reads nothing --------------------------------


class _RecordingClient(FakeS3Client):
    """A client that really can read, and fails the test the moment it is asked."""

    def get_object_attributes(self, **kwargs: object) -> object:
        raise AssertionError("get_object_attributes was called")

    def list_objects_v2(self, **kwargs: object) -> object:
        raise AssertionError("list_objects_v2 was called")

    def delete_object(self, **kwargs: object) -> object:
        raise AssertionError("delete_object was called")

    def copy_object(self, **kwargs: object) -> object:
        raise AssertionError("copy_object was called")


def _router(
    client: FakeS3Client, *, execution_id: str = EXECUTION_ID
) -> QualificationPayloadRouter:
    publisher = LicensedWriteOnlyPublisher(client=client, licensed_bucket=SYNTHETIC_BUCKET)
    return QualificationPayloadRouter(
        publisher=publisher,
        execution_id=execution_id,
        ordinals={
            f"{execution_id}.{index:024d}": index for index in range(EMPIRICAL_REQUEST_COUNT)
        },
    )


#: A stand-in for the accepted claim and record bodies. Their own content address is
#: the hash of *these* bytes; the digest in their path is the **payload's**, which is
#: exactly the distinction the router reads them for.
SIDECAR: Final = b"{}"


def _claim_key(index: int, digest: str = DIGEST) -> ObjectKey:
    return ObjectKey(
        classification=DataClassification.LICENSED,
        segments=("bronze", "_acquisition_claims", digest, f"{EXECUTION_ID}.{index:024d}.json"),
        content_sha256=sha256_hex(SIDECAR),
    )


def _incoming_payload_key(digest: str = DIGEST) -> ObjectKey:
    return ObjectKey(
        classification=DataClassification.LICENSED,
        segments=("bronze", "sharadar", "stocks", "objects", "sha256", digest),
        content_sha256=digest,
    )


def _record_key(index: int, digest: str = DIGEST) -> ObjectKey:
    return ObjectKey(
        classification=DataClassification.LICENSED,
        segments=(
            "bronze",
            "sharadar",
            "stocks",
            "acquisitions",
            digest,
            f"{EXECUTION_ID}.{index:024d}.json",
        ),
        content_sha256=sha256_hex(SIDECAR),
    )


def test_the_router_exposes_one_operation_and_no_read() -> None:
    router = _router(_RecordingClient())
    for forbidden in (
        "head_object",
        "get_object",
        "get_object_attributes",
        "list_objects_v2",
        "exists",
        "delete_object",
        "copy_object",
    ):
        assert not hasattr(router, forbidden)
    assert callable(router.put_if_absent)


def test_the_router_renames_the_payload_and_forwards_the_other_two() -> None:
    client = _RecordingClient()
    router = _router(client)
    payload = b"synthetic-qualification-payload"
    router.put_if_absent(key=_claim_key(0), payload=SIDECAR)
    outcome = router.put_if_absent(key=_incoming_payload_key(), payload=payload)
    router.put_if_absent(key=_record_key(0), payload=SIDECAR)

    assert outcome.key.logical_key == _key(request_ordinal=0).logical_key
    assert physical_key(_key(request_ordinal=0)) in client.objects
    assert physical_key(_incoming_payload_key()) not in client.objects
    # The claim and the record keep their accepted names, byte for byte.
    assert physical_key(_claim_key(0)) in client.objects
    assert physical_key(_record_key(0)) in client.objects
    assert client.head_calls == [] and client.get_calls == []


def test_the_router_never_reads_even_when_the_client_can() -> None:
    client = _RecordingClient()
    router = _router(client)
    for index in range(3):
        digest = sha256_hex(f"payload-{index}".encode())
        router.put_if_absent(key=_claim_key(index, digest), payload=SIDECAR)
        router.put_if_absent(key=_incoming_payload_key(digest), payload=f"payload-{index}".encode())
        router.put_if_absent(key=_record_key(index, digest), payload=SIDECAR)
    assert client.head_calls == []
    assert client.get_calls == []


def test_an_occupied_payload_name_still_fails_closed_through_the_router() -> None:
    client = _RecordingClient()
    client.objects[physical_key(_key(request_ordinal=0))] = b"whatever is there"
    router = _router(client)
    router.put_if_absent(key=_claim_key(0), payload=SIDECAR)
    with pytest.raises(NameOccupiedError):
        router.put_if_absent(key=_incoming_payload_key(), payload=PAYLOAD)
    # ADR-0019 unchanged: nothing was read to decide what occupies the name.
    assert client.head_calls == []
    assert client.get_calls == []


def test_one_governed_request_cannot_yield_two_accepted_terminal_payloads() -> None:
    client = _RecordingClient()
    router = _router(client)
    payload = b"synthetic-qualification-payload"
    router.put_if_absent(key=_claim_key(0), payload=SIDECAR)
    router.put_if_absent(key=_incoming_payload_key(), payload=payload)
    router.put_if_absent(key=_record_key(0), payload=SIDECAR)
    before = len(client.put_calls)

    # The same governed request presented again: refused before any write.
    with pytest.raises(QualificationKeyError):
        router.put_if_absent(key=_claim_key(0), payload=SIDECAR)
    assert len(client.put_calls) == before


@pytest.mark.parametrize(
    "sequence",
    [
        ["payload"],
        ["record"],
        ["claim", "record"],
        ["claim", "claim"],
        ["claim", "payload", "payload"],
    ],
)
def test_a_triple_presented_out_of_order_is_refused(sequence: list[str]) -> None:
    client = _RecordingClient()
    router = _router(client)
    steps = {
        "claim": (_claim_key(0), SIDECAR),
        "payload": (_incoming_payload_key(), PAYLOAD),
        "record": (_record_key(0), SIDECAR),
    }
    with pytest.raises(QualificationKeyError):
        for step in sequence:
            key, body = steps[step]
            router.put_if_absent(key=key, payload=body)


def test_an_identity_outside_the_locked_plan_is_refused_before_any_write() -> None:
    client = _RecordingClient()
    router = _router(client)
    stranger = ObjectKey(
        classification=DataClassification.LICENSED,
        segments=("bronze", "_acquisition_claims", DIGEST, "some-other-execution.0001.json"),
        content_sha256=DIGEST,
    )
    with pytest.raises(QualificationKeyError):
        router.put_if_absent(key=stranger, payload=SIDECAR)
    assert client.put_calls == []


def test_a_key_that_is_not_one_of_the_three_bronze_shapes_is_refused() -> None:
    client = _RecordingClient()
    router = _router(client)
    alien = ObjectKey(
        classification=DataClassification.LICENSED,
        segments=("qualification", "sharadar", "locators", "anything.json"),
        content_sha256=DIGEST,
    )
    with pytest.raises(QualificationKeyError):
        router.put_if_absent(key=alien, payload=SIDECAR)
    assert client.put_calls == []


def test_a_router_refusal_discloses_nothing() -> None:
    client = _RecordingClient()
    router = _router(client)
    with pytest.raises(QualificationKeyError) as raised:
        router.put_if_absent(key=_incoming_payload_key(), payload=PAYLOAD)
    refusal = raised.value
    rendered = f"{refusal} {refusal!r}"
    for canary in (
        *LEAK_CANARIES,
        *SYNTHETIC_SUBJECTS,
        SYNTHETIC_BUCKET,
        DIGEST,
        EXECUTION_ID,
        "licensed/",
        "bronze/",
    ):
        assert canary not in rendered
    assert isinstance(refusal, ObjectStoreError)
    assert not isinstance(refusal, NameOccupiedError)
    assert repr(router) == (
        "QualificationPayloadRouter(classification=LICENSED, direction=WRITE_ONLY)"
    )


# -- 4. the assessment insists on it -------------------------------------------


def _tamper_locator(s3: FakeS3Client, execution_id: str, mutate: Any) -> None:
    """Rewrite one locator's first entry in place, in the fake store only."""
    import json

    key = _locator_physical_key(execution_id)
    document = json.loads(s3.objects[key].decode("utf-8"))
    mutate(document["entries"][0])
    s3.objects[key] = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_a_complete_pair_assesses_and_reads_each_payload_exactly_once() -> None:
    s3 = _acquire_pair()
    before = len(s3.get_calls)
    _assess(s3)
    reads = s3.get_calls[before:]
    payload_reads = [key for key in reads if is_qualification_payload_key(key)]
    assert len(payload_reads) == 2 * EMPIRICAL_REQUEST_COUNT == 96
    assert len(set(payload_reads)) == 96
    assert len(reads) == 194


@pytest.mark.parametrize(
    "field",
    ["execution", "ordinal", "dataset", "provider", "digest"],
)
def test_a_recorded_payload_key_that_is_not_the_reconstruction_is_refused(field: str) -> None:
    s3 = _acquire_pair()
    before_get = len(s3.get_calls)
    before_put = len(s3.put_calls)

    def mutate(entry: dict[str, Any]) -> None:
        parts = entry["payload_key"].split("/")
        # licensed/bronze/<provider>/<dataset>/qualification/<execution>/requests/<NN>/sha256/<d>
        if field == "execution":
            parts[5] = EXECUTION_ID_B
        elif field == "ordinal":
            parts[7] = "07"
        elif field == "dataset":
            parts[3] = "actions" if parts[3] != "actions" else "stocks"
        elif field == "provider":
            parts[2] = "other-provider"
        else:
            parts[9] = OTHER_DIGEST
        entry["payload_key"] = "/".join(parts)

    _tamper_locator(s3, EXECUTION_ID_A, mutate)

    with pytest.raises(AssessmentError) as raised:
        _assess(s3)
    assert raised.value.status is AssessmentStatus.REFUSED_INTEGRITY
    # **Refused before any evidence is read**: two locator reads, and nothing else.
    assert len(s3.get_calls) - before_get == 2
    assert len(s3.put_calls) == before_put


def test_a_locator_whose_coordinates_have_no_canonical_ordinal_is_refused() -> None:
    """A duplicated request coordinate has no ordinal, and none is invented.

    Mutated **identically in both locators**, deliberately. Changing one alone makes
    the two request inventories disagree, and the pair gate refuses that first with
    ``REFUSED_LOCATOR`` -- a real earlier refusal, but not this one. Keeping the pair
    consistent is what forces the run past that gate and onto the ordinal map.
    """
    import json

    s3 = _acquire_pair()
    before_get = len(s3.get_calls)

    for execution_id in (EXECUTION_ID_A, EXECUTION_ID_B):
        key = _locator_physical_key(execution_id)
        document = json.loads(s3.objects[key].decode("utf-8"))
        entries = document["entries"]
        for field in ("dataset", "subject", "page_skip", "page_limit"):
            entries[0][field] = entries[1][field]
        s3.objects[key] = json.dumps(document, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )

    with pytest.raises(AssessmentError) as raised:
        _assess(s3)
    assert raised.value.status is AssessmentStatus.REFUSED_INTEGRITY
    assert len(s3.get_calls) - before_get == 2


def test_a_matching_name_over_different_bytes_is_still_refused() -> None:
    # The key check is addressing, not integrity, and this is the half that proves it:
    # the recorded name is untouched and correct, and only the stored bytes changed.
    s3 = _acquire_pair()
    payload_keys = [key for key in s3.objects if is_qualification_payload_key(key)]
    assert payload_keys
    s3.objects[sorted(payload_keys)[0]] = b"ticker,date,close\nTAMPERED,1998-01-05,1\n"
    with pytest.raises(AssessmentError) as raised:
        _assess(s3)
    assert raised.value.status is AssessmentStatus.REFUSED_INTEGRITY


def test_an_integrity_refusal_discloses_no_key_digest_ordinal_or_subject() -> None:
    s3 = _acquire_pair()

    def mutate(entry: dict[str, Any]) -> None:
        parts = entry["payload_key"].split("/")
        parts[7] = "07"
        entry["payload_key"] = "/".join(parts)

    _tamper_locator(s3, EXECUTION_ID_A, mutate)
    with pytest.raises(AssessmentError) as raised:
        _assess(s3)
    rendered = f"{raised.value} {raised.value!r} {raised.value.status.value}"
    for canary in (*LEAK_CANARIES, *SYNTHETIC_SUBJECTS, SYNTHETIC_BUCKET, DIGEST, "requests/"):
        assert canary not in rendered


# -- 5. isolation --------------------------------------------------------------


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


ADR_0017_MODULES = (
    SRC / "data" / "ingest" / "sharadar" / "composition.py",
    SRC / "data" / "ingest" / "sharadar" / "runtime.py",
    SRC / "data" / "ingest" / "sharadar" / "bronze.py",
    SRC / "data" / "ingest" / "publication.py",
    SRC / "data" / "storage" / "s3.py",
)


@pytest.mark.parametrize("path", ADR_0017_MODULES, ids=lambda path: path.name)
def test_the_qualification_identity_is_unreachable_from_adr_0017(path: Path) -> None:
    # Structural, not aspirational: the ADR-0017 path and the shared store import no
    # part of the qualification package, so they cannot acquire a request-scoped key.
    for imported in _imports(path):
        assert not imported.startswith("kalpamani.data.qualify")
    source = path.read_text(encoding="utf-8")
    for forbidden in (
        "qualification_payload_key",
        "QualificationPayloadRouter",
        "request_ordinal_map",
    ):
        assert forbidden not in source


def test_the_shared_content_addressed_builder_is_unchanged() -> None:
    # ADR-0020 amends the qualification payload identity and nothing else, so the
    # general-purpose builder must still produce the accepted content-addressed name.
    from datetime import UTC, datetime

    from kalpamani.data.contracts.vocabulary import AcquisitionMode
    from kalpamani.data.ingest.bronze import RetrievalMetadata
    from kalpamani.data.ingest.publication import bronze_payload_key

    payload = b"synthetic-shared-bronze-payload"
    retrieval = RetrievalMetadata(
        provider="sharadar",
        dataset="stocks",
        requested_range="1998-01-01/2026-08-31",
        retrieved_at=datetime(2026, 9, 1, tzinfo=UTC),
        source_schema_version="v1",
        ingestion_run_id="some-run.0123456789abcdef01234567",
        acquisition_mode=AcquisitionMode.QUALIFICATION,
    )
    assert bronze_payload_key(retrieval=retrieval, payload=payload).logical_key == (
        f"licensed/bronze/sharadar/stocks/objects/sha256/{sha256_hex(payload)}"
    )
