"""The deterministic private locator: closed schema, exact bindings, fail-closed.

Two kinds of check live here.

**Behavioural.** A real acquisition is driven against synthetic fakes, and the
locator it produces is decoded and cross-checked -- so "every object is bound by exact
key, digest and byte count" is something this file reads back rather than a claim it
repeats.

**Adversarial.** Every field of the schema is corrupted in turn and the refusal is
asserted, because a validator nobody attacked is a validator that has not been tested.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from fixtures.sharadar_empirical import (
    EXECUTION_ID,
    LEAK_CANARIES,
    RUN_INSTANT,
    SYNTHETIC_BUCKET,
    SYNTHETIC_SUBJECTS,
    FakeS3Client,
    FixedClock,
    PagedTransport,
    credential,
    synthetic_inventory,
)
from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.ingest.bronze import RetrievalMetadata
from kalpamani.data.ingest.publication import bronze_payload_key
from kalpamani.data.ingest.sharadar.client import Pacer
from kalpamani.data.qualify.sharadar.acquisition import run_empirical_acquisition
from kalpamani.data.qualify.sharadar.locator import (
    LOCATOR_ENTRY_FIELDS,
    LOCATOR_FIELDS,
    LOCATOR_SCHEMA_VERSION,
    MAX_LOCATOR_BYTES,
    Completeness,
    LocatorDefect,
    LocatorError,
    ObjectDisposition,
    decode_locator,
    locator_key_segments,
    payload_key_for,
    serialize_locator,
    validate_locator_document,
)
from kalpamani.data.qualify.sharadar.plan import build_empirical_plan


def _pacer() -> Pacer:
    return Pacer(min_interval=0.0, clock=lambda: 0.0, sleeper=lambda _seconds: None)


def _acquire() -> tuple[FakeS3Client, Any]:
    s3 = FakeS3Client()
    result = run_empirical_acquisition(
        credential=credential(),
        transport=PagedTransport(),
        pacer=_pacer(),
        s3_client=s3,
        licensed_bucket=SYNTHETIC_BUCKET,
        clock=FixedClock(),
        inventory=synthetic_inventory(),
        execution_id=EXECUTION_ID,
    )
    return s3, result


def _locator_bytes(s3: FakeS3Client) -> bytes:
    key = "/".join(locator_key_segments(EXECUTION_ID))
    return s3.objects[key]


def _document(s3: FakeS3Client) -> dict[str, Any]:
    decoded: dict[str, Any] = json.loads(_locator_bytes(s3).decode("utf-8"))
    return decoded


def test_the_locator_lives_under_the_licensed_qualification_prefix() -> None:
    assert locator_key_segments(EXECUTION_ID) == (
        "qualification",
        "sharadar",
        "locators",
        f"{EXECUTION_ID}.json",
    )


def test_a_windows_device_name_execution_identity_is_refused_at_key_construction() -> None:
    with pytest.raises(LocatorError) as raised:
        locator_key_segments("con")
    assert raised.value.defect is LocatorDefect.IDENTITY_MISMATCH


def test_exactly_one_locator_is_published_per_execution() -> None:
    s3, _ = _acquire()
    locators = [key for key in s3.objects if key.startswith("qualification/sharadar/locators/")]
    assert len(locators) == 1


def test_the_locator_is_published_last_after_every_acquisition_write() -> None:
    s3, _ = _acquire()
    locator_key = "/".join(locator_key_segments(EXECUTION_ID))
    assert s3.put_calls[-1] == locator_key
    assert locator_key not in s3.put_calls[:-1]


def test_the_locator_records_the_accepted_closed_field_set() -> None:
    s3, _ = _acquire()
    assert set(_document(s3)) == LOCATOR_FIELDS


def test_every_entry_records_the_accepted_closed_field_set() -> None:
    s3, _ = _acquire()
    for entry in _document(s3)["entries"]:
        assert set(entry) == LOCATOR_ENTRY_FIELDS


def test_the_locator_binds_the_plan_and_the_inventory_by_digest() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    plan = build_empirical_plan(
        inventory=synthetic_inventory(), execution_id=EXECUTION_ID, instant=RUN_INSTANT
    )
    assert document["inventory_digest"] == plan.inventory_digest
    assert len(document["plan_digest"]) == 64


def test_the_locator_records_the_planned_and_completed_counts() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    assert document["planned_request_count"] == 48
    assert document["completed_request_count"] == 48
    assert document["completeness"] == Completeness.COMPLETE.value
    assert document["publication_state_unknown"] is False


def test_the_locator_declares_the_qualification_mode_and_the_permitted_profile() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    assert document["acquisition_mode"] == AcquisitionMode.QUALIFICATION.value
    assert document["profile"] == "PROVIDER_REALISTIC_PIT"
    assert document["classification"] == "LICENSED"


def test_public_pit_is_not_expressible_in_a_locator() -> None:
    s3, _ = _acquire()
    assert "PUBLIC_PIT" not in _locator_bytes(s3).decode("utf-8")


def test_every_entry_binds_three_objects_by_key_digest_and_byte_count() -> None:
    s3, _ = _acquire()
    for entry in _document(s3)["entries"]:
        for role in ("claim", "payload", "record"):
            key = entry[f"{role}_key"]
            digest = entry[f"{role}_sha256"]
            count = entry[f"{role}_bytes"]
            assert key.startswith("licensed/bronze/")
            assert len(digest) == 64
            assert count >= 0
            stored = s3.objects[key.removeprefix("licensed/")]
            assert len(stored) == count
            if role == "payload":
                assert sha256_hex(stored) == digest


def test_every_recorded_key_and_digest_matches_what_was_actually_stored() -> None:
    s3, _ = _acquire()
    for entry in _document(s3)["entries"]:
        for role in ("claim", "record"):
            stored = s3.objects[entry[f"{role}_key"].removeprefix("licensed/")]
            assert sha256_hex(stored) == entry[f"{role}_sha256"]


def test_the_derived_payload_key_equals_the_accepted_builder_s_key() -> None:
    # The one key rebuilt from a name and a digest rather than from bytes, bound here
    # to the accepted builder so a layout change in either fails rather than drifts.
    payload = b"synthetic-opaque-payload-for-key-derivation"
    retrieval = RetrievalMetadata(
        provider="sharadar",
        dataset="stocks",
        requested_range="1998-01-01/2026-08-29",
        retrieved_at=RUN_INSTANT,
        source_schema_version="sharadar-empirical-v1",
        ingestion_run_id="synthetic-empirical-a.0123456789abcdef01234567",
        acquisition_mode=AcquisitionMode.QUALIFICATION,
    )
    accepted = bronze_payload_key(retrieval=retrieval, payload=payload)
    derived = payload_key_for(dataset="stocks", content_sha256=sha256_hex(payload))
    assert derived.logical_key == accepted.logical_key
    assert derived.content_sha256 == accepted.content_sha256


def test_every_entry_carries_a_distinct_acquisition_identity() -> None:
    s3, _ = _acquire()
    identities = [entry["acquisition_id"] for entry in _document(s3)["entries"]]
    assert len(set(identities)) == len(identities) == 48


def test_dispositions_are_the_closed_two_member_vocabulary() -> None:
    s3, _ = _acquire()
    permitted = {member.value for member in ObjectDisposition}
    assert permitted == {"WRITTEN", "ALREADY_PRESENT"}
    for entry in _document(s3)["entries"]:
        for role in ("claim", "payload", "record"):
            assert entry[f"{role}_disposition"] in permitted


def test_payload_reuse_across_subjects_is_recorded_as_already_present() -> None:
    # The header-only completeness probe returns identical bytes for every subject,
    # so the second and later ones legitimately reuse one payload object.
    s3, _ = _acquire()
    dispositions = [entry["payload_disposition"] for entry in _document(s3)["entries"]]
    assert ObjectDisposition.ALREADY_PRESENT.value in dispositions
    assert ObjectDisposition.WRITTEN.value in dispositions


def test_the_locator_is_inside_its_size_ceiling() -> None:
    s3, _ = _acquire()
    assert 0 < len(_locator_bytes(s3)) <= MAX_LOCATOR_BYTES


def test_the_locator_serialises_deterministically() -> None:
    first, _ = _acquire()
    second, _ = _acquire()
    assert _locator_bytes(first) == _locator_bytes(second)


def test_the_locator_carries_no_bucket_account_url_or_credential() -> None:
    s3, _ = _acquire()
    text = _locator_bytes(s3).decode("utf-8")
    for canary in LEAK_CANARIES:
        if canary in SYNTHETIC_SUBJECTS:
            # Subjects are legitimate private content of a LICENSED locator.
            continue
        assert canary not in text


def test_the_locator_carries_no_free_text_field() -> None:
    for field in LOCATOR_FIELDS | LOCATOR_ENTRY_FIELDS:
        for forbidden in ("note", "notes", "comment", "message", "description", "reason"):
            assert forbidden not in field


def test_a_size_ceiling_refusal_happens_at_serialisation() -> None:
    oversized = {"padding": "x" * (MAX_LOCATOR_BYTES + 10)}
    with pytest.raises(LocatorError) as raised:
        serialize_locator(oversized)
    assert raised.value.defect is LocatorDefect.TOO_LARGE


# -- adversarial validation --------------------------------------------------


def _refuses(document: object, execution_id: str = EXECUTION_ID) -> LocatorDefect:
    with pytest.raises(LocatorError) as raised:
        validate_locator_document(document, execution_id=execution_id)
    return raised.value.defect


def test_a_valid_locator_round_trips_through_decode() -> None:
    s3, _ = _acquire()
    locator = decode_locator(_locator_bytes(s3), execution_id=EXECUTION_ID)
    assert locator.assessable is True
    assert locator.completeness is Completeness.COMPLETE
    assert len(locator.entries) == 48


def test_an_unknown_top_level_field_is_refused_rather_than_ignored() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["extra"] = "value"
    assert _refuses(document) is LocatorDefect.FIELD_UNKNOWN


def test_a_missing_top_level_field_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    del document["plan_digest"]
    assert _refuses(document) is LocatorDefect.FIELD_MISSING


def test_a_wrong_schema_version_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["schema_version"] = "something-else"
    assert _refuses(document) is LocatorDefect.SCHEMA_VERSION_UNKNOWN


def test_a_locator_describing_another_execution_is_refused() -> None:
    s3, _ = _acquire()
    assert _refuses(_document(s3), execution_id="synthetic-other-x") is (
        LocatorDefect.IDENTITY_MISMATCH
    )


def test_a_public_pit_profile_claim_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["profile"] = "PUBLIC_PIT"
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


def test_a_non_qualification_acquisition_mode_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["acquisition_mode"] = "BACKFILL"
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


def test_a_control_classification_claim_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["classification"] = "CONTROL"
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


def test_an_entry_count_disagreeing_with_the_completed_count_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["entries"] = document["entries"][:-1]
    assert _refuses(document) is LocatorDefect.ENTRY_COUNT_INCONSISTENT


def test_a_duplicated_acquisition_identity_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["entries"][1]["acquisition_id"] = document["entries"][0]["acquisition_id"]
    document["entries"][1]["record_key"] = document["entries"][0]["record_key"]
    assert _refuses(document) is LocatorDefect.ENTRY_DUPLICATED


def test_a_completed_count_above_the_planned_count_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["planned_request_count"] = 10
    assert _refuses(document) is LocatorDefect.RESULT_INCONSISTENT


def test_a_complete_locator_that_did_not_complete_every_request_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["planned_request_count"] = 60
    document["completeness"] = Completeness.COMPLETE.value
    assert _refuses(document) is LocatorDefect.RESULT_INCONSISTENT


@pytest.mark.parametrize("field", ["claim_sha256", "payload_sha256", "record_sha256"])
def test_a_malformed_digest_is_refused(field: str) -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["entries"][0][field] = "not-a-digest"
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


@pytest.mark.parametrize("field", ["claim_bytes", "payload_bytes", "record_bytes"])
def test_a_negative_byte_count_is_refused(field: str) -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["entries"][0][field] = -1
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


def test_an_unknown_disposition_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["entries"][0]["payload_disposition"] = "MAYBE"
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


def test_an_unknown_entry_field_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["entries"][0]["note"] = "why"
    assert _refuses(document) is LocatorDefect.FIELD_UNKNOWN


def test_a_completion_instant_before_the_start_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["run_completed_at"] = "1998-01-01T00:00:00+00:00"
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


def test_a_naive_instant_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["run_started_at"] = "2026-08-30T12:00:00"
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


def test_invalid_utf8_locator_bytes_are_refused_rather_than_replaced() -> None:
    with pytest.raises(LocatorError) as raised:
        decode_locator(b"\xff\xfe not json", execution_id=EXECUTION_ID)
    assert raised.value.defect is LocatorDefect.ENCODING_INVALID


def test_locator_bytes_over_the_ceiling_are_refused_before_decoding() -> None:
    with pytest.raises(LocatorError) as raised:
        decode_locator(b"x" * (MAX_LOCATOR_BYTES + 1), execution_id=EXECUTION_ID)
    assert raised.value.defect is LocatorDefect.TOO_LARGE


def test_malformed_json_is_refused() -> None:
    with pytest.raises(LocatorError) as raised:
        decode_locator(b"{not json", execution_id=EXECUTION_ID)
    assert raised.value.defect is LocatorDefect.DOCUMENT_MALFORMED


def test_a_partial_locator_validates_but_is_not_assessable() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["completeness"] = Completeness.PARTIAL.value
    document["planned_request_count"] = 60
    locator = validate_locator_document(document, execution_id=EXECUTION_ID)
    assert locator.completeness is Completeness.PARTIAL
    assert locator.assessable is False


def test_an_ambiguous_publication_state_makes_a_locator_unassessable() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["publication_state_unknown"] = True
    locator = validate_locator_document(document, execution_id=EXECUTION_ID)
    assert locator.assessable is False


def test_no_locator_refusal_carries_a_key_digest_or_subject() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["entries"][0]["payload_sha256"] = "x" * 64
    with pytest.raises(LocatorError) as raised:
        validate_locator_document(document, execution_id=EXECUTION_ID)
    rendered = f"{raised.value} {raised.value!r} {raised.value.args}"
    for subject in SYNTHETIC_SUBJECTS:
        assert subject not in rendered
    assert "licensed/" not in rendered
    assert SYNTHETIC_BUCKET not in rendered


def test_the_serialised_locator_is_canonical_bytes_of_its_document() -> None:
    s3, _ = _acquire()
    assert _locator_bytes(s3) == canonical_bytes(_document(s3))


def test_the_schema_version_constant_is_the_one_written() -> None:
    s3, _ = _acquire()
    assert _document(s3)["schema_version"] == LOCATOR_SCHEMA_VERSION
