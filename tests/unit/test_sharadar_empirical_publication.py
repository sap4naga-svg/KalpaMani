"""The ADR-0019 write-only acquisition boundary, driven end to end.

Everything here is about one rule and its consequences: **an acquisition-side
conditional ``PutObject`` answered ``412`` fails closed**, and nothing on that path
ever reads an object or its metadata. The rule is not asserted from a constant; it
is produced by running the real acquisition against fakes that record every call
they were asked for, and the recordings are what the counts are read from.

Three things this file is careful about:

- **The hostile fake can read.** ``FakeS3Client`` implements ``head_object`` and
  ``get_object``, and one subclass here adds ``get_object_attributes`` and
  ``list_objects_v2`` that raise. "Zero reads" therefore means *nobody asked*, not
  *nobody could*.
- **The occupied-name statuses claim nothing about content.** A ``412`` establishes
  that a name was taken. Every assertion about what the run then says is written to
  fail if a word like *identical*, *different* or *already present* comes back.
- **Two accepted consequences are modelled rather than avoided**, in the two tests
  named for them: ADR-0019 halts a run on *any* occupied name, including the benign
  repeated-bytes case ADR-0018's design used to absorb.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

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
    client_error,
    credential,
    synthetic_inventory,
)
from kalpamani.data.contracts.errors import (
    ObjectAlreadyExistsError,
    ObjectStoreBackendError,
    ObjectStoreError,
)
from kalpamani.data.contracts.vocabulary import ObjectStoreFailure, ObjectStoreOperation
from kalpamani.data.objectstore import ObjectKey
from kalpamani.data.qualify.sharadar.acquisition import (
    AcquisitionStatus,
    run_empirical_acquisition,
)
from kalpamani.data.qualify.sharadar.locator import locator_key_segments
from kalpamani.data.qualify.sharadar.operations import (
    OBJECTS_PER_ACQUISITION,
    LocatorPublicationStatus,
)
from kalpamani.data.qualify.sharadar.plan import (
    ACQUISITION_DEADLINE_SECONDS,
    BRONZE_OPERATION_ADMISSION_SECONDS,
    LOCATOR_ATTEMPT_ADMISSION_SECONDS,
    LOCATOR_CONSTRUCTION_ALLOWANCE_SECONDS,
    LOCATOR_OPERATION_ADMISSION_SECONDS,
    LOCATOR_TERMINAL_RESERVE_SECONDS,
    MIN_REQUEST_INTERVAL_SECONDS,
    PROVIDER_REQUEST_ADMISSION_SECONDS,
    S3_OPERATION_CEILING_SECONDS,
    TIMEOUT_SECONDS,
    EmpiricalPlanError,
    validate_deadline_constants,
)
from kalpamani.data.qualify.sharadar.publication import (
    LicensedWriteOnlyPublisher,
    NameOccupiedError,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUALIFY_SHARADAR = PROJECT_ROOT / "src" / "kalpamani" / "data" / "qualify" / "sharadar"
PUBLICATION = QUALIFY_SHARADAR / "publication.py"


class HostileS3Client(FakeS3Client):
    """A client that really can read, and is never asked to.

    ``FakeS3Client`` already implements ``head_object`` and ``get_object`` and
    records every call; these two raise instead, so a listing or an attributes call
    fails the test at the point of the call rather than in a count afterwards.
    """

    def get_object_attributes(self, **kwargs: object) -> object:
        raise AssertionError("get_object_attributes was called on the acquisition path")

    def list_objects_v2(self, **kwargs: object) -> object:
        raise AssertionError("list_objects_v2 was called on the acquisition path")


def _acquire(
    *,
    s3: FakeS3Client | None = None,
    transport: PagedTransport | None = None,
    execution_id: str = EXECUTION_ID,
    instant: Any = RUN_INSTANT,
    monotonic: FakeMonotonic | None = None,
) -> tuple[FakeS3Client, PagedTransport, Any]:
    """One real acquisition, against fakes that record what they were asked for."""
    clock = monotonic if monotonic is not None else FakeMonotonic()
    client = s3 if s3 is not None else HostileS3Client()
    variant = "B" if execution_id == EXECUTION_ID_B else "A"
    wire = transport if transport is not None else PagedTransport(byte_variant=variant)
    result = run_empirical_acquisition(
        credential=credential(),
        transport=wire,
        monotonic=clock,
        sleeper=clock.sleep,
        s3_client=client,
        licensed_bucket=SYNTHETIC_BUCKET,
        clock=FixedClock(instant),
        inventory=synthetic_inventory(),
        execution_id=execution_id,
    )
    return client, wire, result


def _first_publication_keys() -> tuple[str, str, str]:
    """The claim, payload and record keys of the **first** request of a clean run.

    Learned by running, rather than reconstructed: a key this file derived itself
    could drift from the one the accepted publisher actually writes, and the tests
    below would then be scripting a collision at a name nothing uses.
    """
    s3, _, result = _acquire()
    assert result.status is AcquisitionStatus.COMPLETED
    claim, payload, record = s3.put_calls[:OBJECTS_PER_ACQUISITION]
    assert "_acquisition_claims/" in claim
    assert "/objects/sha256/" in payload
    assert "/acquisitions/" in record
    return claim, payload, record


def _locator_key(execution_id: str = EXECUTION_ID) -> str:
    return "/".join(locator_key_segments(execution_id))


def _occupied_at(key: str) -> FakeS3Client:
    """A store whose conditional write of exactly ``key`` is answered ``412``."""
    return HostileS3Client(fail_puts={key: client_error("PreconditionFailed")})


def _assert_no_object_read(s3: FakeS3Client) -> None:
    """Nobody asked the client to read anything, by its own recording."""
    assert s3.head_calls == []
    assert s3.get_calls == []


# -- the complete run: the accepted ADR-0019 envelope --------------------------


def test_a_complete_run_writes_one_hundred_and_forty_five_objects_and_reads_none() -> None:
    s3, wire, result = _acquire()
    assert result.status is AcquisitionStatus.COMPLETED
    assert wire.call_count == 48
    assert result.counts.completed_requests == 48
    assert result.counts.put_object_count == 145
    assert result.counts.head_object_count == 0
    assert result.counts.get_object_count == 0
    assert result.counts.total_s3_operations == 145
    assert result.locator_attempts == 1
    # Read from the fake's own recordings, not from the fields above.
    assert len(s3.put_calls) == 145
    assert len(s3.put_calls) == OBJECTS_PER_ACQUISITION * 48 + 1
    _assert_no_object_read(s3)


def test_a_retried_locator_reaches_at_most_one_hundred_and_forty_seven_and_still_reads_none() -> (
    None
):
    """Two retries buy two more writes, and not one metadata read.

    The locator's first two conditional writes are refused with a throttling error,
    which leaves the condition unresolved and is the only thing a retry may follow.
    The third succeeds.
    """
    key = _locator_key()
    throttled = client_error("SlowDown")

    class _ThrottleTwice(HostileS3Client):
        def __init__(self) -> None:
            super().__init__()
            self.locator_attempts = 0

        def put_object(self, **kwargs: Any) -> dict[str, Any]:
            if kwargs["Key"] == key:
                self.locator_attempts += 1
                if self.locator_attempts <= 2:
                    self.put_calls.append(kwargs["Key"])
                    raise throttled
            return super().put_object(**kwargs)

    s3 = _ThrottleTwice()
    _, _, result = _acquire(s3=s3)
    assert result.status is AcquisitionStatus.COMPLETED
    assert result.locator_attempts == 3
    assert result.counts.put_object_count == 147
    assert 145 <= result.counts.put_object_count <= 147
    assert result.counts.head_object_count == 0
    assert result.counts.get_object_count == 0
    assert result.counts.total_s3_operations == 147
    _assert_no_object_read(s3)


# -- a Bronze 412 fails closed, at each of the three artefacts -----------------


@pytest.mark.parametrize("artefact", ["claim", "payload", "record"])
def test_a_bronze_collision_at_any_artefact_yields_bronze_name_occupied(artefact: str) -> None:
    keys = dict(zip(("claim", "payload", "record"), _first_publication_keys(), strict=True))
    s3 = _occupied_at(keys[artefact])
    _, _, result = _acquire(s3=s3)
    assert result.status is AcquisitionStatus.BRONZE_NAME_OCCUPIED
    _assert_no_object_read(s3)


@pytest.mark.parametrize("index", [0, 1, 2])
def test_a_bronze_collision_stops_every_later_bronze_operation(index: int) -> None:
    """The publication step stops where it collided, and the run stops with it.

    ``publish_bronze_payload`` writes the claim, the payload and the record in three
    separate conditional invocations with no short-circuit, so the count of Bronze
    writes that actually happened is exactly the position of the collision.
    """
    keys = _first_publication_keys()
    s3 = _occupied_at(keys[index])
    _, _, result = _acquire(s3=s3)
    assert result.status is AcquisitionStatus.BRONZE_NAME_OCCUPIED
    bronze = [key for key in s3.put_calls if "/locators/" not in key]
    assert len(bronze) == index + 1
    assert bronze == list(keys[: index + 1])
    assert result.counts.completed_requests == 0


@pytest.mark.parametrize("index", [0, 1, 2])
def test_no_provider_request_begins_after_a_bronze_collision(index: int) -> None:
    keys = _first_publication_keys()
    s3 = _occupied_at(keys[index])
    _, wire, result = _acquire(s3=s3)
    assert result.status is AcquisitionStatus.BRONZE_NAME_OCCUPIED
    assert wire.call_count == 1
    assert result.counts.provider_request_count == 1


def test_a_bronze_collision_reads_nothing_and_adopts_nothing() -> None:
    keys = _first_publication_keys()
    s3 = _occupied_at(keys[1])
    _, _, result = _acquire(s3=s3)
    assert result.status is AcquisitionStatus.BRONZE_NAME_OCCUPIED
    _assert_no_object_read(s3)
    # The occupied payload name holds nothing this run put there, and the run makes
    # no claim about what does hold it.
    assert keys[1] not in s3.objects


def test_a_partial_locator_after_a_bronze_collision_records_no_collided_object() -> None:
    """A halt is not a rollback, and it is not an invitation to invent evidence.

    Whatever completed before the collision stays published and stays recorded. The
    request that collided never became a completed acquisition, so it has no entry
    at all -- not an entry marked incomplete, and certainly not one calling the
    occupied object verified or retained.
    """
    import json

    keys = _first_publication_keys()
    # Collide on the *second* request, so there is a completed one to record.
    s3, _, complete = _acquire()
    second_payload = [key for key in s3.put_calls if "/objects/sha256/" in key][1]
    assert complete.status is AcquisitionStatus.COMPLETED

    collided = _occupied_at(second_payload)
    _, _, result = _acquire(s3=collided)
    assert result.status is AcquisitionStatus.BRONZE_NAME_OCCUPIED
    assert result.locator_attempts == 1

    document = json.loads(collided.objects[_locator_key()])
    assert document["completeness"] == "PARTIAL"
    assert document["planned_request_count"] == 48
    assert document["completed_request_count"] == 1
    assert len(document["entries"]) == 1
    rendered = json.dumps(document)
    assert second_payload.rsplit("/", 1)[-1] not in rendered
    _assert_no_object_read(collided)
    assert keys[0] in collided.objects


# -- a locator 412 fails closed ------------------------------------------------


def test_a_locator_collision_yields_locator_name_occupied() -> None:
    s3 = _occupied_at(_locator_key())
    _, _, result = _acquire(s3=s3)
    assert result.status is AcquisitionStatus.LOCATOR_NAME_OCCUPIED
    assert result.locator_attempts == 1
    _assert_no_object_read(s3)


def test_a_locator_collision_is_not_published_retained_or_addressable() -> None:
    s3 = _occupied_at(_locator_key())
    _, _, result = _acquire(s3=s3)
    assert result.addressable is False
    assert _locator_key() not in s3.objects
    assert LocatorPublicationStatus.NAME_OCCUPIED.value == "NAME_OCCUPIED"
    assert not hasattr(LocatorPublicationStatus, "ALREADY_PRESENT")
    assert not hasattr(LocatorPublicationStatus, "COLLISION")
    assert not hasattr(AcquisitionStatus, "LOCATOR_COLLISION")


def test_a_definitively_refused_locator_still_reports_locator_not_published() -> None:
    """The accepted closed result for *no truthful locator* is unchanged.

    ADR-0019 replaced the collision outcome; it did not touch this one. A refusal
    that resolves the condition without writing leaves the evidence unaddressable,
    and the run says exactly that rather than claiming a locator exists.
    """
    s3 = HostileS3Client(fail_puts={_locator_key(): client_error("AccessDenied")})
    _, _, result = _acquire(s3=s3)
    assert result.status is AcquisitionStatus.LOCATOR_NOT_PUBLISHED
    assert result.addressable is False
    assert _locator_key() not in s3.objects
    _assert_no_object_read(s3)


# -- the two accepted consequences, modelled rather than avoided ---------------


def test_two_identical_payloads_in_one_run_halt_with_bronze_name_occupied() -> None:
    """ADR-0019 §4.2 and §11, reproduced: a *benign* repeat is a halt.

    The completeness probe legitimately answers header-only for every subject, so
    within one dataset those eight responses are byte-identical -- and the Bronze
    payload object is content-addressed per dataset, so they are one name. Under
    ADR-0018 the second write resolved to *already present* and the run continued.
    It cannot now: the metadata read that proved it identical is gone, so the second
    write fails closed and the run halts.

    This is the accepted cost, recorded rather than absorbed. It is why every other
    complete-run fixture in the suite publishes byte-distinct responses.
    """
    s3 = HostileS3Client()
    _, wire, result = _acquire(s3=s3, transport=PagedTransport(byte_variant=""))
    assert result.status is AcquisitionStatus.BRONZE_NAME_OCCUPIED
    assert result.counts.completed_requests < 48
    assert wire.call_count < 48
    _assert_no_object_read(s3)


def test_a_second_run_republishing_identical_bytes_halts_with_bronze_name_occupied() -> None:
    """The same consequence across a pair of runs, which is where it bites hardest.

    Run B re-observes the same subjects eight days later. Where the observation is
    unchanged -- an untouched ``tickers`` snapshot, say -- its bytes are Run A's
    bytes, and the content-addressed payload name is already occupied. Run B halts.
    """
    s3 = HostileS3Client()
    _, _, first = _acquire(
        s3=s3, transport=PagedTransport(byte_variant="A"), execution_id=EXECUTION_ID_A
    )
    assert first.status is AcquisitionStatus.COMPLETED
    _, _, second = _acquire(
        s3=s3,
        transport=PagedTransport(byte_variant="A"),
        execution_id=EXECUTION_ID_B,
        instant=RUN_B_INSTANT,
    )
    assert second.status is AcquisitionStatus.BRONZE_NAME_OCCUPIED
    _assert_no_object_read(s3)


# -- the occupied-name statuses disclose nothing -------------------------------


@pytest.mark.parametrize(
    "status", [AcquisitionStatus.BRONZE_NAME_OCCUPIED, AcquisitionStatus.LOCATOR_NAME_OCCUPIED]
)
def test_an_occupied_name_status_carries_no_private_value(status: AcquisitionStatus) -> None:
    rendered = f"{status} {status!r} {status.value}"
    for canary in (*LEAK_CANARIES, *SYNTHETIC_SUBJECTS, SYNTHETIC_BUCKET):
        assert canary not in rendered
    assert "licensed/" not in rendered
    assert "sha256" not in rendered


@pytest.mark.parametrize(
    "status", [AcquisitionStatus.BRONZE_NAME_OCCUPIED, AcquisitionStatus.LOCATOR_NAME_OCCUPIED]
)
def test_an_occupied_name_status_claims_nothing_about_the_stored_content(
    status: AcquisitionStatus,
) -> None:
    token = status.value.lower()
    assert "occupied" in token
    for forbidden in ("identical", "different", "already_present", "adopted", "collision"):
        assert forbidden not in token


def test_a_collision_result_discloses_no_key_digest_or_subject() -> None:
    keys = _first_publication_keys()
    s3 = _occupied_at(keys[1])
    _, _, result = _acquire(s3=s3)
    rendered = f"{result} {result!r} {result.counts!r} {result.status!r}"
    for canary in (*LEAK_CANARIES, *SYNTHETIC_SUBJECTS, SYNTHETIC_BUCKET):
        assert canary not in rendered
    assert "licensed/" not in rendered
    assert keys[1] not in rendered


def test_the_name_occupied_error_says_only_that_the_name_was_occupied() -> None:
    error = NameOccupiedError()
    assert isinstance(error, ObjectStoreError)
    assert not isinstance(error, ObjectAlreadyExistsError)
    rendered = f"{error} {error!r} {error.args}"
    assert "occupied" in rendered
    for forbidden in ("identical", "different", "already present", "adopt", SYNTHETIC_BUCKET):
        assert forbidden not in rendered
    for canary in LEAK_CANARIES:
        assert canary not in rendered


# -- the write-only publisher itself ------------------------------------------


PAYLOAD = b"synthetic-write-only-bytes"
KEY = ObjectKey.licensed("qualification", "sharadar", "locators", "x.json", payload=PAYLOAD)


class RecordingPutClient:
    """A client with **one** method, which is the whole point of the protocol."""

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._failure = failure

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        if self._failure is not None:
            raise self._failure
        return {"ETag": "synthetic"}


def _publisher(client: Any) -> LicensedWriteOnlyPublisher:
    return LicensedWriteOnlyPublisher(client=client, licensed_bucket=SYNTHETIC_BUCKET)


def test_the_publisher_issues_exactly_one_conditional_put_with_the_accepted_shape() -> None:
    from kalpamani.data.storage.s3 import (
        CHECKSUM_ALGORITHM,
        CONTENT_TYPE,
        SERVER_SIDE_ENCRYPTION,
        checksum_of,
    )

    client = RecordingPutClient()
    outcome = _publisher(client).put_if_absent(key=KEY, payload=PAYLOAD)
    assert outcome.stored is True
    assert outcome.byte_count == len(PAYLOAD)
    assert len(client.calls) == 1
    request = client.calls[0]
    assert request["Bucket"] == SYNTHETIC_BUCKET
    assert request["Body"] == PAYLOAD
    assert request["ContentLength"] == len(PAYLOAD)
    assert request["ContentType"] == CONTENT_TYPE
    assert request["ChecksumAlgorithm"] == CHECKSUM_ALGORITHM
    assert request["ChecksumSHA256"] == checksum_of(KEY.content_sha256)
    assert request["ServerSideEncryption"] == SERVER_SIDE_ENCRYPTION
    assert request["IfNoneMatch"] == "*"


def test_the_publisher_reaches_no_success_other_than_a_write() -> None:
    """There is no ``stored=False`` on this path, so no caller can read one.

    ``stored=False`` meant *identical content was already present*, which required
    the metadata read ADR-0019 removed.
    """
    client = RecordingPutClient()
    publisher = _publisher(client)
    for index in range(3):
        payload = f"synthetic-{index}".encode()
        key = ObjectKey.licensed("qualification", "sharadar", "x", payload=payload)
        assert publisher.put_if_absent(key=key, payload=payload).stored is True


def test_the_publisher_raises_name_occupied_on_a_precondition_failure() -> None:
    client = RecordingPutClient(failure=client_error("PreconditionFailed"))
    publisher = _publisher(client)
    with pytest.raises(NameOccupiedError):
        publisher.put_if_absent(key=KEY, payload=PAYLOAD)
    assert publisher.name_occupied is True
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    ("code", "failure"),
    [
        ("AccessDenied", ObjectStoreFailure.ACCESS_DENIED),
        ("SlowDown", ObjectStoreFailure.THROTTLED),
        ("InternalError", ObjectStoreFailure.TRANSIENT),
        ("ConditionalRequestConflict", ObjectStoreFailure.TRANSIENT),
        ("SomethingNobodyHasHeardOf", ObjectStoreFailure.UNKNOWN),
    ],
)
def test_every_other_backend_refusal_keeps_the_accepted_closed_taxonomy(
    code: str, failure: ObjectStoreFailure
) -> None:
    """The classification is the shared one, and a 409 is still not an occupied name."""
    client = RecordingPutClient(failure=client_error(code))
    publisher = _publisher(client)
    with pytest.raises(ObjectStoreBackendError) as raised:
        publisher.put_if_absent(key=KEY, payload=PAYLOAD)
    assert raised.value.operation is ObjectStoreOperation.PUT
    assert raised.value.failure is failure
    assert publisher.name_occupied is False
    # No hidden retry: one refusal, one invocation.
    assert len(client.calls) == 1


def test_a_backend_refusal_never_echoes_the_bucket_key_or_message() -> None:
    client = RecordingPutClient(failure=client_error("AccessDenied"))
    with pytest.raises(ObjectStoreBackendError) as raised:
        _publisher(client).put_if_absent(key=KEY, payload=PAYLOAD)
    rendered = f"{raised.value} {raised.value!r} {raised.value.args}"
    assert SYNTHETIC_BUCKET not in rendered
    assert "licensed/" not in rendered
    assert raised.value.__cause__ is None


def test_the_publisher_requires_only_put_object() -> None:
    class _WriteOnly:
        def put_object(self, **kwargs: Any) -> dict[str, Any]:
            return {"ETag": "synthetic"}

    assert _publisher(_WriteOnly()) is not None

    class _NoPut:
        def head_object(self, **kwargs: Any) -> dict[str, Any]:
            return {}

    with pytest.raises(ObjectStoreBackendError) as raised:
        _publisher(_NoPut())
    assert raised.value.operation is ObjectStoreOperation.BIND


@pytest.mark.parametrize(
    "bucket", ["AB", "A_BAD_BUCKET", "s3://bucket", "arn:aws:s3:::bucket", "bucket/with/path"]
)
def test_the_publisher_refuses_a_bucket_value_without_echoing_it(bucket: str) -> None:
    with pytest.raises(ObjectStoreBackendError) as raised:
        LicensedWriteOnlyPublisher(client=RecordingPutClient(), licensed_bucket=bucket)
    assert raised.value.operation is ObjectStoreOperation.BIND
    assert bucket not in f"{raised.value} {raised.value!r}"


def test_the_publisher_bucket_pattern_matches_the_shared_store_s() -> None:
    """Spelled here, bound by a test -- the drift an import would have hidden."""
    from kalpamani.data.qualify.sharadar import publication
    from kalpamani.data.storage import s3 as shared

    assert publication._BUCKET_NAME.pattern == shared._BUCKET_NAME.pattern


def test_the_publisher_exposes_exactly_one_public_method() -> None:
    surface = {
        name
        for name, member in vars(LicensedWriteOnlyPublisher).items()
        if not name.startswith("_") and callable(member)
    }
    assert surface == {"put_if_absent"}
    data = {
        name
        for name, member in vars(LicensedWriteOnlyPublisher).items()
        if not name.startswith("_") and not callable(member)
    }
    assert data == {"name_occupied"}
    for forbidden in (
        "exists",
        "head_object",
        "get_object",
        "get_object_attributes",
        "list_objects_v2",
        "delete_object",
        "copy_object",
    ):
        assert not hasattr(LicensedWriteOnlyPublisher, forbidden)


def test_the_publisher_repr_names_neither_bucket_nor_client() -> None:
    rendered = repr(_publisher(RecordingPutClient()))
    assert SYNTHETIC_BUCKET not in rendered
    assert "WRITE_ONLY" in rendered


# -- structure: the module is inert, and the runtime never needs a read --------


def test_importing_the_publication_module_does_nothing() -> None:
    """Every module-level statement is an import, an assignment or a definition."""
    tree = ast.parse(PUBLICATION.read_text(encoding="utf-8"))
    for node in tree.body:
        assert isinstance(
            node,
            ast.Import
            | ast.ImportFrom
            | ast.Assign
            | ast.AnnAssign
            | ast.ClassDef
            | ast.FunctionDef
            | ast.Expr,
        )
        if isinstance(node, ast.Expr):
            assert isinstance(node.value, ast.Constant)


def test_the_publication_module_names_no_sdk_environment_or_file_access() -> None:
    # Over the executable source: the docstring may say the protocol is satisfied by
    # a ``boto3`` client without the module importing or constructing one.
    tree = ast.parse(PUBLICATION.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                node.body.pop(0)
    source = ast.unparse(tree)
    for forbidden in (
        "boto3",
        "botocore",
        "os.environ",
        "open(",
        "socket",
        "Session(",
        "read_text",
        "write_text",
    ):
        assert forbidden not in source


def test_nothing_the_runtime_or_the_bronze_publisher_calls_needs_a_read() -> None:
    """What makes the one cast in ``acquisition.py`` safe, checked mechanically.

    The accepted runtime's parameter is annotated with the two-method neutral store
    protocol, and the write-only publisher implements one of the two. That is sound
    only while nothing on the path actually calls the other, so this parses both
    modules and asserts no ``.exists`` attribute access anywhere in either.
    """
    src = PROJECT_ROOT / "src" / "kalpamani" / "data"
    for module in (src / "ingest" / "sharadar" / "runtime.py", src / "ingest" / "publication.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr == "exists"
        ]
        assert offenders == [], f"{module.name} reaches .exists at {offenders}"


# -- the corrected deadline arithmetic ----------------------------------------


def test_the_per_request_admission_requirement_is_exactly_three_operation_ceilings() -> None:
    assert PROVIDER_REQUEST_ADMISSION_SECONDS == pytest.approx(
        TIMEOUT_SECONDS + 3 * S3_OPERATION_CEILING_SECONDS + LOCATOR_TERMINAL_RESERVE_SECONDS
    )


def test_the_locator_reserve_covers_exactly_three_writes_and_the_construction() -> None:
    minimum = 3 * S3_OPERATION_CEILING_SECONDS + LOCATOR_CONSTRUCTION_ALLOWANCE_SECONDS
    assert LOCATOR_TERMINAL_RESERVE_SECONDS >= minimum
    # One below the rule is refused rather than clamped.
    with pytest.raises(EmpiricalPlanError):
        validate_deadline_constants(locator_reserve_seconds=minimum - 0.5)
    validate_deadline_constants(locator_reserve_seconds=minimum)


def test_the_feasibility_rule_uses_three_operation_ceilings_and_not_six() -> None:
    """``T_req + P + 3 * T_s3 + L <= D``, driven at the boundary from both sides."""
    cycle = (
        TIMEOUT_SECONDS
        + MIN_REQUEST_INTERVAL_SECONDS
        + 3 * S3_OPERATION_CEILING_SECONDS
        + LOCATOR_TERMINAL_RESERVE_SECONDS
    )
    validate_deadline_constants(deadline_seconds=cycle)
    with pytest.raises(EmpiricalPlanError):
        validate_deadline_constants(deadline_seconds=cycle - 0.5)
    # Under the retired six-ceiling rule this same deadline would have been refused,
    # so the assertion is about the rule rather than about the compiled numbers.
    retired = cycle + 3 * S3_OPERATION_CEILING_SECONDS
    assert retired > cycle


def test_the_bronze_and_locator_admission_thresholds_are_unchanged() -> None:
    assert BRONZE_OPERATION_ADMISSION_SECONDS == pytest.approx(
        S3_OPERATION_CEILING_SECONDS + LOCATOR_TERMINAL_RESERVE_SECONDS
    )
    assert LOCATOR_OPERATION_ADMISSION_SECONDS == pytest.approx(S3_OPERATION_CEILING_SECONDS)
    assert LOCATOR_ATTEMPT_ADMISSION_SECONDS == pytest.approx(
        LOCATOR_CONSTRUCTION_ALLOWANCE_SECONDS + S3_OPERATION_CEILING_SECONDS
    )
    assert ACQUISITION_DEADLINE_SECONDS == 1_800.0


def test_the_retired_six_ceiling_admission_is_gone_from_the_executable_source() -> None:
    """No production module still enforces the ADR-0018 per-request obligation."""
    package = QUALIFY_SHARADAR
    pattern = re.compile(r"(?<![\d.])[64]\s*\*\s*S3_OPERATION_CEILING_SECONDS")
    for module in sorted(package.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    node.body.pop(0)
        assert not pattern.search(ast.unparse(tree)), module.name
