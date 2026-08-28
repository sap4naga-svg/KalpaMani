"""The licensed S3 object store, proven against a synthetic client. **No socket opens.**

The adapter has never run against AWS and is not authorized to. What can be
established without a credential is nonetheless most of what matters, because the
properties that make this store safe are properties of the *requests it builds*
and the *answers it refuses to guess at*:

* **append-only is one conditional request**, not a look-then-write race;
* **integrity is SHA-256**, never an ETag;
* **an occupied name is resolved from metadata**, never by downloading bytes;
* **anything unverifiable fails closed** — never "probably the same", never
  "treat as absent";
* **a permission failure is not absence**;
* **nothing from the backend escapes** — not a bucket, a key, a URL, a request id
  or a credential fragment.

Every fixture is invented. No real bucket name, credential, provider payload or
vendor row appears here.
"""

from __future__ import annotations

import base64
import threading
from hashlib import sha256
from typing import Any

import pytest

from fixtures.fake_s3 import (
    LEAK_CANARIES,
    SYNTHETIC_BUCKET,
    FakeS3Client,
    SyntheticClientError,
)
from kalpamani.data.contracts.canonical import sha256_hex
from kalpamani.data.contracts.errors import (
    ObjectAlreadyExistsError,
    ObjectClassificationError,
    ObjectContentMismatchError,
    ObjectPayloadTypeError,
    ObjectStoreBackendError,
)
from kalpamani.data.contracts.vocabulary import (
    DataClassification,
    ObjectStoreFailure,
    ObjectStoreOperation,
)
from kalpamani.data.objectstore import ObjectKey, ResearchObjectStore, physical_key
from kalpamani.data.storage.s3 import (
    CHECKSUM_ALGORITHM,
    CONTENT_TYPE,
    SERVER_SIDE_ENCRYPTION,
    S3ResearchObjectStore,
    checksum_of,
    classify_backend_failure,
)

pytestmark = pytest.mark.unit

PAYLOAD = b"synthetic-opaque-provider-payload-0001"
OTHER = b"synthetic-opaque-provider-payload-0002"


def store(client: FakeS3Client | None = None) -> tuple[S3ResearchObjectStore, FakeS3Client]:
    """A store bound to a synthetic client and an invented bucket name."""
    fake = client if client is not None else FakeS3Client()
    return S3ResearchObjectStore(client=fake, licensed_bucket=SYNTHETIC_BUCKET), fake


def key(payload: bytes = PAYLOAD, *segments: str) -> ObjectKey:
    parts = segments or ("bronze", "provider", "dataset", "objects", "sha256", sha256_hex(payload))
    return ObjectKey.licensed(*parts, payload=payload)


# ---------------------------------------------------------------------------
# Construction and boundaries
# ---------------------------------------------------------------------------


def test_a_valid_client_and_bucket_are_accepted() -> None:
    backing, _ = store()
    assert isinstance(backing, S3ResearchObjectStore)


@pytest.mark.parametrize(
    "bucket",
    [
        "s3://synthetic-fake-not-a-real-bucket",
        "arn:aws:s3:::synthetic-fake-not-a-real-bucket",
        "synthetic-fake-not-a-real-bucket/prefix",
        "Synthetic-Fake-Not-A-Real-Bucket",
        "ab",
        "a" * 64,
        "-leading-hyphen",
        "trailing-hyphen-",
        "",
        None,
        7,
    ],
)
def test_an_invalid_bucket_is_refused_without_being_echoed(bucket: Any) -> None:
    """An ARN or an ``s3://`` URI is not a bucket name, and a refusal is not a place
    to print one: a bucket name is a private identifier under CLAUDE.md §3."""
    with pytest.raises(ObjectStoreBackendError) as caught:
        S3ResearchObjectStore(client=FakeS3Client(), licensed_bucket=bucket)
    rendered = str(caught.value)
    assert caught.value.failure is ObjectStoreFailure.INVALID_CONFIGURATION
    assert caught.value.operation is ObjectStoreOperation.BIND
    assert "synthetic" not in rendered
    assert "arn:" not in rendered and "s3://" not in rendered
    assert rendered == "research object store BIND: INVALID_CONFIGURATION"


@pytest.mark.parametrize("client", [None, object(), "client", 7])
def test_a_client_that_cannot_serve_the_two_operations_is_refused(client: Any) -> None:
    """Reported as a binding fault, not as a failed request: nothing was sent."""
    with pytest.raises(ObjectStoreBackendError) as caught:
        S3ResearchObjectStore(client=client, licensed_bucket=SYNTHETIC_BUCKET)
    assert caught.value.operation is ObjectStoreOperation.BIND
    assert caught.value.failure is ObjectStoreFailure.INVALID_CONFIGURATION


def test_the_repr_names_no_bucket_and_no_client() -> None:
    backing, fake = store()
    rendered = repr(backing)
    assert rendered == "S3ResearchObjectStore(classification=LICENSED)"
    assert SYNTHETIC_BUCKET not in rendered
    assert repr(fake) not in rendered


def test_the_store_exposes_exactly_the_protocol_surface() -> None:
    """No read, no list, no delete, no copy, no overwrite — not even privately."""
    surface = {name for name in vars(S3ResearchObjectStore) if not name.startswith("_")}
    assert surface == {"put_if_absent", "exists"}
    for forbidden in (
        "read",
        "get",
        "get_object",
        "list",
        "list_prefix",
        "list_objects",
        "delete",
        "delete_object",
        "copy",
        "overwrite",
        "replace",
        "snapshot",
    ):
        assert not hasattr(S3ResearchObjectStore, forbidden)


def test_the_store_satisfies_the_research_object_store_protocol() -> None:
    backing: ResearchObjectStore = store()[0]
    assert backing.put_if_absent(key=key(), payload=PAYLOAD).stored is True


def test_control_remains_unpublishable_through_this_store() -> None:
    """There is no classification parameter, and a CONTROL key cannot be built."""
    with pytest.raises(ObjectClassificationError, match="not publishable in this slice"):
        ObjectKey(
            classification=DataClassification.CONTROL,
            segments=("bronze", "x"),
            content_sha256=sha256_hex(PAYLOAD),
        )
    import inspect

    parameters = set(inspect.signature(S3ResearchObjectStore.__init__).parameters)
    assert not parameters & {"classification", "control", "attestation", "bucket_for"}


# ---------------------------------------------------------------------------
# First publication
# ---------------------------------------------------------------------------


def test_a_first_publication_sends_exactly_the_intended_request() -> None:
    backing, fake = store()
    published = key()
    outcome = backing.put_if_absent(key=published, payload=PAYLOAD)

    assert outcome.stored is True
    assert outcome.byte_count == len(PAYLOAD)
    assert len(fake.put_calls) == 1
    sent = fake.put_calls[0]

    assert sent["Bucket"] == SYNTHETIC_BUCKET
    assert sent["Body"] == PAYLOAD
    assert type(sent["Body"]) is bytes
    assert sent["ContentLength"] == len(PAYLOAD)
    assert sent["ContentType"] == CONTENT_TYPE
    assert sent["ChecksumAlgorithm"] == CHECKSUM_ALGORITHM
    assert sent["ServerSideEncryption"] == SERVER_SIDE_ENCRYPTION
    assert sent["IfNoneMatch"] == "*"


def test_the_physical_key_is_the_segments_without_the_classification_prefix() -> None:
    """The classification selects the store; repeating it inside would name the
    object ``<licensed-bucket>/licensed/...`` — stated twice, once as routing and
    once as a directory."""
    backing, fake = store()
    published = key()
    backing.put_if_absent(key=published, payload=PAYLOAD)

    location = fake.put_calls[0]["Key"]
    assert location == physical_key(published)
    assert location == "/".join(published.segments)
    assert not location.startswith("licensed/")
    assert published.logical_key == f"licensed/{location}"


def test_the_outcome_key_keeps_the_logical_identity_and_names_no_bucket() -> None:
    backing, _ = store()
    outcome = backing.put_if_absent(key=key(), payload=PAYLOAD)
    assert outcome.key.logical_key.startswith("licensed/")
    for marker in (SYNTHETIC_BUCKET, "s3://", "arn:", "amazonaws"):
        assert marker not in outcome.key.logical_key
        assert marker not in repr(outcome)


def test_the_checksum_is_canonical_base64_of_the_key_digest() -> None:
    backing, fake = store()
    published = key()
    backing.put_if_absent(key=published, payload=PAYLOAD)

    sent = fake.put_calls[0]["ChecksumSHA256"]
    assert sent == base64.b64encode(sha256(PAYLOAD).digest()).decode("ascii")
    assert sent == checksum_of(published.content_sha256)
    assert base64.b64decode(sent, validate=True).hex() == published.content_sha256


def test_no_etag_acl_or_public_option_is_ever_sent() -> None:
    """An ETag is a multipart-dependent token, not a content hash."""
    backing, fake = store()
    backing.put_if_absent(key=key(), payload=PAYLOAD)
    sent = fake.put_calls[0]
    for forbidden in ("ACL", "GrantRead", "GrantFullControl", "IfMatch", "Tagging", "ETag"):
        assert forbidden not in sent


def test_a_first_publication_performs_no_preflight_head() -> None:
    """HEAD-then-PUT is a race: another writer can land between them, and on a
    bucket with no versioning the resulting overwrite is unrecoverable."""
    backing, fake = store()
    backing.put_if_absent(key=key(), payload=PAYLOAD)
    assert fake.head_calls == []
    assert len(fake.put_calls) == 1


def test_the_admission_rules_are_the_same_as_the_in_memory_store() -> None:
    backing, fake = store()
    with pytest.raises(ObjectClassificationError, match="exact ObjectKey"):
        backing.put_if_absent(key="not-a-key", payload=PAYLOAD)  # type: ignore[arg-type]
    with pytest.raises(ObjectPayloadTypeError, match="exact bytes"):
        backing.put_if_absent(key=key(), payload=bytearray(PAYLOAD))  # type: ignore[arg-type]
    with pytest.raises(ObjectContentMismatchError, match="hashes to"):
        backing.put_if_absent(key=key(), payload=OTHER)
    assert fake.put_calls == [], "nothing may reach the backend after a refusal"


# ---------------------------------------------------------------------------
# Idempotency and collision
# ---------------------------------------------------------------------------


def test_an_identical_republication_is_idempotent_and_writes_nothing_new() -> None:
    backing, fake = store()
    published = key()
    first = backing.put_if_absent(key=published, payload=PAYLOAD)
    second = backing.put_if_absent(key=published, payload=PAYLOAD)

    assert first.stored is True
    assert second.stored is False
    assert second.byte_count == len(PAYLOAD)
    assert len(fake.objects) == 1
    assert fake.body_of(physical_key(published)) == PAYLOAD
    # Two conditional attempts, one verification, and no third write.
    assert len(fake.put_calls) == 2
    assert len(fake.head_calls) == 1


def test_different_content_under_one_logical_name_is_refused() -> None:
    backing, fake = store()
    first = key()
    backing.put_if_absent(key=first, payload=PAYLOAD)

    forged = ObjectKey(
        classification=first.classification,
        segments=first.segments,
        content_sha256=sha256_hex(OTHER),
    )
    with pytest.raises(ObjectAlreadyExistsError, match="append-only"):
        backing.put_if_absent(key=forged, payload=OTHER)

    assert fake.body_of(physical_key(first)) == PAYLOAD, "the winner must survive"
    assert len(fake.objects) == 1


def test_no_overwrite_request_follows_a_collision() -> None:
    """Every write this store makes is conditional. There is no unconditional retry."""
    backing, fake = store()
    published = key()
    backing.put_if_absent(key=published, payload=PAYLOAD)
    backing.put_if_absent(key=published, payload=PAYLOAD)
    with pytest.raises(ObjectAlreadyExistsError):
        backing.put_if_absent(
            key=ObjectKey(
                classification=published.classification,
                segments=published.segments,
                content_sha256=sha256_hex(OTHER),
            ),
            payload=OTHER,
        )
    assert all(call.get("IfNoneMatch") == "*" for call in fake.put_calls)


@pytest.mark.parametrize(
    "response",
    [
        {"ContentLength": len(PAYLOAD)},  # no checksum at all
        {"ChecksumSHA256": "", "ContentLength": len(PAYLOAD)},
        {"ChecksumSHA256": "not-base64!!", "ContentLength": len(PAYLOAD)},
        {"ChecksumSHA256": base64.b64encode(b"short").decode(), "ContentLength": len(PAYLOAD)},
        {"ChecksumSHA256": base64.b64encode(sha256(PAYLOAD).digest()).decode()},  # no length
        {
            "ChecksumSHA256": base64.b64encode(sha256(PAYLOAD).digest()).decode(),
            "ContentLength": -1,
        },
        {
            "ChecksumSHA256": base64.b64encode(sha256(PAYLOAD).digest()).decode(),
            "ContentLength": "38",
        },
        "not a mapping",
        None,
    ],
)
def test_an_occupied_name_that_cannot_be_verified_fails_closed(response: Any) -> None:
    """Not "probably the same", not "treat as absent", and not "download and see"."""
    backing, fake = store()
    published = key()
    backing.put_if_absent(key=published, payload=PAYLOAD)
    fake.head_override.append(response)

    with pytest.raises(ObjectStoreBackendError) as caught:
        backing.put_if_absent(key=published, payload=PAYLOAD)
    assert caught.value.failure is ObjectStoreFailure.INVALID_RESPONSE
    assert caught.value.operation is ObjectStoreOperation.HEAD


def test_a_precondition_failure_followed_by_an_absent_head_fails_closed() -> None:
    """Both cannot be true of one moment, and the retry that "fixes" it is an overwrite."""
    backing, fake = store()
    published = key()
    backing.put_if_absent(key=published, payload=PAYLOAD)
    fake.fail_head.append(SyntheticClientError("404", operation="HeadObject"))

    with pytest.raises(ObjectStoreBackendError) as caught:
        backing.put_if_absent(key=published, payload=PAYLOAD)
    assert caught.value.failure is ObjectStoreFailure.INVALID_RESPONSE


def test_a_length_mismatch_on_an_occupied_name_is_a_collision_not_an_idempotent_write() -> None:
    backing, fake = store()
    published = key()
    backing.put_if_absent(key=published, payload=PAYLOAD)
    fake.head_override.append(
        {
            "ChecksumSHA256": base64.b64encode(sha256(PAYLOAD).digest()).decode("ascii"),
            "ContentLength": len(PAYLOAD) + 1,
        }
    )
    with pytest.raises(ObjectAlreadyExistsError):
        backing.put_if_absent(key=published, payload=PAYLOAD)


@pytest.mark.parametrize(
    "code,failure",
    [
        ("AccessDenied", ObjectStoreFailure.ACCESS_DENIED),
        ("SlowDown", ObjectStoreFailure.THROTTLED),
        ("InternalError", ObjectStoreFailure.TRANSIENT),
        ("SomethingNobodyExpected", ObjectStoreFailure.UNKNOWN),
    ],
)
def test_a_backend_failure_on_put_becomes_a_typed_refusal(
    code: str, failure: ObjectStoreFailure
) -> None:
    backing, fake = store()
    fake.fail_put.append(SyntheticClientError(code))
    with pytest.raises(ObjectStoreBackendError) as caught:
        backing.put_if_absent(key=key(), payload=PAYLOAD)
    assert caught.value.failure is failure
    assert caught.value.operation is ObjectStoreOperation.PUT


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------


def test_exists_is_false_for_a_genuinely_absent_object() -> None:
    backing, fake = store()
    assert backing.exists(key=key()) is False
    assert fake.head_calls[0]["ChecksumMode"] == "ENABLED"


def test_exists_is_true_when_the_digest_matches() -> None:
    backing, _ = store()
    published = key()
    backing.put_if_absent(key=published, payload=PAYLOAD)
    assert backing.exists(key=published) is True


def test_exists_is_false_when_the_name_holds_a_different_digest() -> None:
    """The object asked about is not there. That is not the same as the name being free."""
    backing, _ = store()
    published = key()
    backing.put_if_absent(key=published, payload=PAYLOAD)
    forged = ObjectKey(
        classification=published.classification,
        segments=published.segments,
        content_sha256=sha256_hex(OTHER),
    )
    assert backing.exists(key=forged) is False
    with pytest.raises(ObjectAlreadyExistsError):
        backing.put_if_absent(key=forged, payload=OTHER)


@pytest.mark.parametrize(
    "code,failure",
    [
        ("AccessDenied", ObjectStoreFailure.ACCESS_DENIED),
        ("SlowDown", ObjectStoreFailure.THROTTLED),
        ("ServiceUnavailable", ObjectStoreFailure.TRANSIENT),
        ("Whatever", ObjectStoreFailure.UNKNOWN),
    ],
)
def test_exists_refuses_rather_than_reporting_absence(
    code: str, failure: ObjectStoreFailure
) -> None:
    """A permission failure is not absence: answering False would let a
    misconfigured role re-publish over objects it simply could not see."""
    backing, fake = store()
    fake.fail_head.append(SyntheticClientError(code, operation="HeadObject"))
    with pytest.raises(ObjectStoreBackendError) as caught:
        backing.exists(key=key())
    assert caught.value.failure is failure


@pytest.mark.parametrize(
    "response",
    [
        {"ContentLength": 38},
        {"ChecksumSHA256": "not-base64!!", "ContentLength": 38},
        {"ChecksumSHA256": base64.b64encode(sha256(PAYLOAD).digest()).decode()},
        {
            "ChecksumSHA256": base64.b64encode(sha256(PAYLOAD).digest()).decode(),
            "ContentLength": "38",
        },
        {"ETag": '"synthetic-fake-etag"'},
    ],
)
def test_exists_refuses_a_malformed_or_checksum_free_response(response: Any) -> None:
    backing, fake = store()
    fake.head_override.append(response)
    with pytest.raises(ObjectStoreBackendError) as caught:
        backing.exists(key=key())
    assert caught.value.failure is ObjectStoreFailure.INVALID_RESPONSE


def test_exists_never_uses_an_etag_for_identity() -> None:
    backing, fake = store()
    published = key()
    backing.put_if_absent(key=published, payload=PAYLOAD)
    # A response whose ETag matches but whose checksum names other content.
    fake.head_override.append(
        {
            "ETag": '"synthetic-fake-etag"',
            "ChecksumSHA256": base64.b64encode(sha256(OTHER).digest()).decode("ascii"),
            "ContentLength": len(OTHER),
        }
    )
    assert backing.exists(key=published) is False


def test_exists_refuses_a_key_that_is_not_exact() -> None:
    backing, fake = store()
    with pytest.raises(ObjectClassificationError, match="exact ObjectKey"):
        backing.exists(key="not-a-key")  # type: ignore[arg-type]
    assert fake.head_calls == []


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def _publish_concurrently(
    backing: S3ResearchObjectStore, work: list[tuple[ObjectKey, bytes]]
) -> tuple[list[Any], list[BaseException]]:
    """Run every publication on its own thread and collect what came back."""
    outcomes: list[Any] = []
    failures: list[BaseException] = []
    barrier = threading.Barrier(len(work))
    guard = threading.Lock()

    def run(published: ObjectKey, payload: bytes) -> None:
        barrier.wait()
        try:
            outcome = backing.put_if_absent(key=published, payload=payload)
        except BaseException as exc:  # the test is about which one, so catch all
            with guard:
                failures.append(exc)
        else:
            with guard:
                outcomes.append(outcome)

    threads = [threading.Thread(target=run, args=item) for item in work]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    return outcomes, failures


def test_two_concurrent_identical_publications_store_exactly_one_object() -> None:
    """One writer wins; the other proves the stored bytes identical and reports so."""
    backing, fake = store()
    published = key()
    outcomes, failures = _publish_concurrently(backing, [(published, PAYLOAD)] * 2)

    assert failures == []
    assert sorted(outcome.stored for outcome in outcomes) == [False, True]
    assert len(fake.objects) == 1
    assert fake.body_of(physical_key(published)) == PAYLOAD


def test_two_concurrent_different_payloads_leave_one_object_and_one_refusal() -> None:
    """The loser must be refused, never allowed to overwrite the winner."""
    backing, fake = store()
    first = key(PAYLOAD, "bronze", "provider", "dataset", "contested")
    second = ObjectKey(
        classification=first.classification,
        segments=first.segments,
        content_sha256=sha256_hex(OTHER),
    )
    outcomes, failures = _publish_concurrently(backing, [(first, PAYLOAD), (second, OTHER)])

    assert len(fake.objects) == 1
    assert [outcome.stored for outcome in outcomes] == [True]
    assert len(failures) == 1
    assert isinstance(failures[0], ObjectAlreadyExistsError)
    stored = fake.body_of(physical_key(first))
    assert stored in (PAYLOAD, OTHER)


# ---------------------------------------------------------------------------
# Error disclosure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["AccessDenied", "SlowDown", "InternalError", "Whatever"])
def test_nothing_from_the_backend_escapes_a_translated_refusal(
    code: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The synthetic error deliberately carries a bucket, a key, a URL, a request
    id and credential-shaped text. None of it may survive translation."""
    backing, fake = store()
    fake.fail_put.append(SyntheticClientError(code))
    with pytest.raises(ObjectStoreBackendError) as caught:
        backing.put_if_absent(key=key(), payload=PAYLOAD)

    surfaces = [
        str(caught.value),
        repr(caught.value),
        str(caught.value.args),
        str(getattr(caught.value, "operation", "")),
        str(getattr(caught.value, "failure", "")),
    ]
    captured = capsys.readouterr()
    surfaces.extend([captured.out, captured.err])

    for surface in surfaces:
        for canary in LEAK_CANARIES:
            assert canary not in surface

    assert caught.value.__cause__ is None, "the SDK exception must not be chained"
    assert caught.value.__suppress_context__ is True


def test_the_refusal_carries_only_an_operation_and_a_failure() -> None:
    error = ObjectStoreBackendError(
        operation=ObjectStoreOperation.HEAD, failure=ObjectStoreFailure.ACCESS_DENIED
    )
    assert set(ObjectStoreBackendError.__slots__) == {"operation", "failure"}
    assert str(error) == "research object store HEAD: ACCESS_DENIED"


def test_a_classifier_never_raises_on_a_hostile_exception() -> None:
    """Classification runs inside exception handling; it must not fail there."""

    class HostileError(Exception):
        @property
        def response(self) -> Any:
            raise RuntimeError("classification must not trust this")

    assert classify_backend_failure(HostileError()) is ObjectStoreFailure.UNKNOWN
    assert classify_backend_failure(RuntimeError("no response attribute")) is (
        ObjectStoreFailure.UNKNOWN
    )
    assert classify_backend_failure(SyntheticClientError("AccessDenied")) is (
        ObjectStoreFailure.ACCESS_DENIED
    )
