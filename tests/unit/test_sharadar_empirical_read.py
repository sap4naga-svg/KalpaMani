"""The exact-object read surface: narrow by construction, verified before parsing.

The most important tests here are the ones that prove an **absence** -- no listing, no
delete, no copy, no arbitrary by-name read of anything but the locator. An absence is
what stops this component becoming the search capability the architecture removes, and
an absence has to be checked rather than intended.
"""

from __future__ import annotations

import pytest

from fixtures.sharadar_empirical import SYNTHETIC_BUCKET, FakeS3Client
from kalpamani.data.contracts.canonical import sha256_hex
from kalpamani.data.contracts.vocabulary import ObjectStoreFailure
from kalpamani.data.objectstore import ObjectKey
from kalpamani.data.qualify.sharadar.locator import LOCATOR_SEGMENTS
from kalpamani.data.qualify.sharadar.read import (
    LOCATOR_KEY_PREFIX,
    MAX_READ_BYTES,
    ExactObjectReference,
    LicensedObjectReader,
    LicensedReadError,
    ReadFailure,
    ReadOperation,
)

PAYLOAD = b"synthetic-opaque-object-bytes"
DIGEST = sha256_hex(PAYLOAD)
KEY = ObjectKey.licensed(
    "bronze", "sharadar", "stocks", "objects", "sha256", DIGEST, payload=PAYLOAD
)


def _reader(client: FakeS3Client | None = None) -> tuple[LicensedObjectReader, FakeS3Client]:
    backing = client if client is not None else FakeS3Client()
    return LicensedObjectReader(client=backing, licensed_bucket=SYNTHETIC_BUCKET), backing


def _stored() -> tuple[LicensedObjectReader, FakeS3Client]:
    reader, client = _reader()
    client.objects["bronze/sharadar/stocks/objects/sha256/" + DIGEST] = PAYLOAD
    return reader, client


def _reference(**overrides: object) -> ExactObjectReference:
    fields: dict[str, object] = {
        "logical_key": KEY.logical_key,
        "expected_sha256": DIGEST,
        "expected_bytes": len(PAYLOAD),
    }
    fields.update(overrides)
    return ExactObjectReference(**fields)  # type: ignore[arg-type]


# -- what the surface cannot do ----------------------------------------------


def test_the_reader_exposes_no_listing_delete_or_copy() -> None:
    reader, _ = _reader()
    for forbidden in (
        "list_objects_v2",
        "list_objects",
        "delete_object",
        "copy_object",
        "put_bucket_policy",
    ):
        assert not hasattr(reader, forbidden)


def test_the_reader_exposes_no_credential_or_provider_surface() -> None:
    reader, _ = _reader()
    for forbidden in ("get_secret_value", "credential", "transport", "fetch"):
        assert not hasattr(reader, forbidden)


def test_the_assessment_protocol_declares_exactly_three_operations() -> None:
    from kalpamani.data.qualify.sharadar.read import AssessmentS3Client

    declared = {
        name
        for name in vars(AssessmentS3Client)
        if not name.startswith("_") and callable(getattr(AssessmentS3Client, name, None))
    }
    assert declared == {"get_object", "put_object", "head_object"}


def test_the_writer_side_protocol_is_not_widened() -> None:
    from kalpamani.data.storage.s3 import S3Client

    assert not hasattr(S3Client, "get_object")


def test_the_research_object_store_protocol_is_not_widened() -> None:
    from kalpamani.data.objectstore import ResearchObjectStore

    for forbidden in ("get_object", "read", "list_objects_v2", "delete"):
        assert not hasattr(ResearchObjectStore, forbidden)


# -- exact reads -------------------------------------------------------------


def test_an_exact_read_returns_the_verified_bytes() -> None:
    reader, _ = _stored()
    assert reader.read_exact(_reference()) == PAYLOAD
    assert reader.get_object_count == 1


def test_a_wrong_expected_digest_refuses_before_the_bytes_are_returned() -> None:
    reader, _ = _stored()
    with pytest.raises(LicensedReadError) as raised:
        reader.read_exact(_reference(expected_sha256="0" * 64))
    assert raised.value.failure is ReadFailure.INTEGRITY_MISMATCH


def test_a_wrong_expected_byte_count_refuses() -> None:
    reader, _ = _stored()
    with pytest.raises(LicensedReadError) as raised:
        reader.read_exact(_reference(expected_bytes=len(PAYLOAD) + 1))
    assert raised.value.failure is ReadFailure.INTEGRITY_MISMATCH


def test_a_reference_above_the_ceiling_is_refused_before_the_request() -> None:
    reader, client = _reader()
    with pytest.raises(LicensedReadError) as raised:
        reader.read_exact(_reference(expected_bytes=MAX_READ_BYTES + 1))
    assert raised.value.failure is ReadFailure.TOO_LARGE
    assert client.get_calls == []
    assert reader.get_object_count == 0


def test_a_missing_object_is_reported_as_not_found() -> None:
    reader, _ = _reader()
    with pytest.raises(LicensedReadError) as raised:
        reader.read_exact(_reference())
    assert raised.value.failure is ReadFailure.NOT_FOUND


def test_a_key_outside_the_licensed_prefix_is_refused() -> None:
    with pytest.raises(LicensedReadError) as raised:
        _reference(logical_key="control/somewhere/else")
    assert raised.value.failure is ReadFailure.INVALID_KEY


@pytest.mark.parametrize(
    "digest",
    [
        "",
        "abc",
        "X" * 64,
        "0" * 63,
        "g" * 64,
    ],
)
def test_a_malformed_expected_digest_is_refused_at_construction(digest: str) -> None:
    with pytest.raises(LicensedReadError):
        _reference(expected_sha256=digest)


def test_a_negative_byte_count_is_refused_at_construction() -> None:
    with pytest.raises(LicensedReadError):
        _reference(expected_bytes=-1)


def test_a_reference_may_not_be_subclassed() -> None:
    with pytest.raises(TypeError):

        class _Relaxed(ExactObjectReference):
            pass


# -- the one by-name read ----------------------------------------------------


def test_the_locator_may_be_read_by_name_without_a_digest() -> None:
    reader, client = _reader()
    key = "/".join(LOCATOR_SEGMENTS) + "/synthetic-a.json"
    client.objects[key] = b'{"schema_version": "x"}'
    payload = reader.read_locator_by_name(logical_key=f"licensed/{key}", max_bytes=1024)
    assert payload == b'{"schema_version": "x"}'
    assert reader.get_object_count == 1


def test_the_by_name_read_refuses_any_key_outside_the_locator_prefix() -> None:
    reader, client = _reader()
    with pytest.raises(LicensedReadError) as raised:
        reader.read_locator_by_name(logical_key=KEY.logical_key, max_bytes=1024)
    assert raised.value.failure is ReadFailure.INVALID_KEY
    assert client.get_calls == []


def test_the_locator_prefix_constant_agrees_with_the_locator_module() -> None:
    assert LOCATOR_KEY_PREFIX == "licensed/" + "/".join(LOCATOR_SEGMENTS) + "/"


def test_the_by_name_read_bounds_the_body_while_reading() -> None:
    reader, client = _reader()
    key = "/".join(LOCATOR_SEGMENTS) + "/synthetic-a.json"
    client.objects[key] = b"x" * 4096
    with pytest.raises(LicensedReadError) as raised:
        reader.read_locator_by_name(logical_key=f"licensed/{key}", max_bytes=100)
    assert raised.value.failure is ReadFailure.TOO_LARGE


def test_an_unusable_ceiling_is_refused() -> None:
    reader, client = _reader()
    key = f"licensed/{'/'.join(LOCATOR_SEGMENTS)}/synthetic-a.json"
    for ceiling in (0, -1, MAX_READ_BYTES + 1):
        with pytest.raises(LicensedReadError):
            reader.read_locator_by_name(logical_key=key, max_bytes=ceiling)
    assert client.get_calls == []


# -- the one conditional report write ----------------------------------------


def _report_key(payload: bytes) -> ObjectKey:
    return ObjectKey.licensed(
        "qualification", "sharadar", "reports", "exec-a", "assess-a.json", payload=payload
    )


def test_a_report_is_published_conditionally_and_reports_that_it_wrote() -> None:
    reader, client = _reader()
    payload = b'{"report": "synthetic"}'
    assert reader.publish_report(key=_report_key(payload), payload=payload) is True
    assert reader.put_object_count == 1
    assert reader.head_object_count == 0
    assert client.put_calls == ["qualification/sharadar/reports/exec-a/assess-a.json"]


def test_republishing_identical_report_content_resolves_by_metadata_and_writes_nothing() -> None:
    reader, _client = _reader()
    payload = b'{"report": "synthetic"}'
    reader.publish_report(key=_report_key(payload), payload=payload)
    assert reader.publish_report(key=_report_key(payload), payload=payload) is False
    assert reader.put_object_count == 2
    assert reader.head_object_count == 1


def test_a_report_name_holding_different_content_is_a_collision() -> None:
    reader, _client = _reader()
    first = b'{"report": "one"}'
    reader.publish_report(key=_report_key(first), payload=first)
    key = _report_key(first)
    second = b'{"report": "two"}'
    forged = ObjectKey(
        classification=key.classification,
        segments=key.segments,
        content_sha256=sha256_hex(second),
    )
    with pytest.raises(LicensedReadError) as raised:
        reader.publish_report(key=forged, payload=second)
    assert raised.value.failure is ReadFailure.COLLISION


def test_a_payload_that_does_not_hash_to_its_key_is_refused_before_the_write() -> None:
    reader, client = _reader()
    payload = b'{"report": "synthetic"}'
    with pytest.raises(LicensedReadError) as raised:
        reader.publish_report(key=_report_key(payload), payload=b"different")
    assert raised.value.failure is ReadFailure.INTEGRITY_MISMATCH
    assert client.put_calls == []


# -- binding and disclosure --------------------------------------------------


def test_a_bad_bucket_value_is_refused_without_echoing_it() -> None:
    # An over-long value, so the "not echoed" check is about a distinctive string
    # rather than about two characters that appear in half the English language.
    rejected = "synthetic-fake-not-a-real-bucket-and-far-too-long-to-be-a-valid-one"
    with pytest.raises(LicensedReadError) as raised:
        LicensedObjectReader(client=FakeS3Client(), licensed_bucket=rejected)
    rendered = f"{raised.value} {raised.value!r} {raised.value.args}"
    assert raised.value.failure is ReadFailure.INVALID_CONFIGURATION
    assert rejected not in rendered
    assert "licensed read BIND" in rendered


def test_a_client_that_cannot_serve_the_three_operations_is_refused() -> None:
    with pytest.raises(LicensedReadError) as raised:
        LicensedObjectReader(client=object(), licensed_bucket=SYNTHETIC_BUCKET)  # type: ignore[arg-type]
    assert raised.value.failure is ReadFailure.INVALID_CONFIGURATION


def test_the_reader_repr_names_no_bucket_client_or_key() -> None:
    reader, _ = _reader()
    rendered = repr(reader)
    assert SYNTHETIC_BUCKET not in rendered
    assert "get=0" in rendered


def test_no_refusal_carries_the_bucket_the_key_or_a_backend_message() -> None:
    reader, _ = _reader()
    with pytest.raises(LicensedReadError) as raised:
        reader.read_exact(_reference())
    rendered = f"{raised.value} {raised.value!r} {raised.value.args}"
    assert SYNTHETIC_BUCKET not in rendered
    assert DIGEST not in rendered
    assert "bronze/" not in rendered
    assert "synthetic 404" not in rendered


def test_the_backend_failure_mapping_is_total_over_the_shared_vocabulary() -> None:
    from kalpamani.data.qualify.sharadar.read import _BACKEND_FAILURE

    assert set(_BACKEND_FAILURE) == set(ObjectStoreFailure)


def test_the_read_operation_vocabulary_includes_get_which_the_writer_side_lacks() -> None:
    from kalpamani.data.contracts.vocabulary import ObjectStoreOperation

    assert ReadOperation.GET.value == "GET"
    assert "GET" not in {member.value for member in ObjectStoreOperation}
