"""Acquisition and assessment end to end, against synthetic fakes only.

**Nothing here contacts Sharadar, AWS or any network.** The credential is a
self-labelled synthetic string, the bucket is a synthetic name, the transport is a
dictionary that returns invented CSV, and the S3 client is a dictionary with the
conditional-write semantics the real backend enforces.

The point of this file is the *numbers*. Every operation count in the accepted
arithmetic is produced by running the real code and read off counters, so a change
that quietly issues an extra request, an extra write or a single object-byte read on
the acquisition path fails here rather than in production.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from fixtures.sharadar_empirical import (
    EXECUTION_ID,
    SYNTHETIC_BUCKET,
    SYNTHETIC_SUBJECTS,
    FakeS3Client,
    FixedClock,
    PagedTransport,
    client_error,
    credential,
    synthetic_inventory,
)
from kalpamani.data.ingest.sharadar.client import Pacer
from kalpamani.data.qualify.sharadar.acquisition import (
    NO_RETRY_POLICY,
    AcquisitionStatus,
    run_empirical_acquisition,
)
from kalpamani.data.qualify.sharadar.assessment import (
    AssessmentError,
    AssessmentStatus,
    locator_logical_key,
    run_assessment,
)
from kalpamani.data.qualify.sharadar.locator import locator_key_segments
from kalpamani.data.qualify.sharadar.read import LicensedObjectReader

ASSESSMENT_ID = "synthetic-assess-a"


def _pacer() -> Pacer:
    return Pacer(min_interval=0.0, clock=lambda: 0.0, sleeper=lambda _seconds: None)


def _acquire(
    *, s3: FakeS3Client | None = None, transport: PagedTransport | None = None
) -> tuple[FakeS3Client, PagedTransport, Any]:
    client = s3 if s3 is not None else FakeS3Client()
    wire = transport if transport is not None else PagedTransport()
    result = run_empirical_acquisition(
        credential=credential(),
        transport=wire,
        pacer=_pacer(),
        s3_client=client,
        licensed_bucket=SYNTHETIC_BUCKET,
        clock=FixedClock(),
        inventory=synthetic_inventory(),
        execution_id=EXECUTION_ID,
    )
    return client, wire, result


def _reader(s3: FakeS3Client) -> LicensedObjectReader:
    return LicensedObjectReader(client=s3, licensed_bucket=SYNTHETIC_BUCKET)


# -- acquisition: the accepted numbers ----------------------------------------


def test_a_complete_acquisition_issues_exactly_forty_eight_provider_requests() -> None:
    _, transport, result = _acquire()
    assert transport.call_count == 48
    assert result.counts.provider_request_count == 48
    assert result.status is AcquisitionStatus.COMPLETED


def test_requests_are_issued_sequentially_in_the_plan_s_canonical_order() -> None:
    _, transport, _ = _acquire()
    # tickers, then stocks, then actions; each dataset's subjects in sorted order.
    datasets = [
        next(name for name in ("tickers", "stocks", "actions") if f"/{name}?" in url)
        for url in transport.urls
    ]
    assert datasets == ["tickers"] * 16 + ["stocks"] * 16 + ["actions"] * 16


def test_the_retry_policy_permits_exactly_one_attempt() -> None:
    assert NO_RETRY_POLICY.max_attempts == 1
    assert NO_RETRY_POLICY.backoff_seconds == ()


def test_a_complete_acquisition_writes_three_bronze_objects_per_request_plus_one_locator() -> None:
    s3, _, result = _acquire()
    assert result.counts.put_object_count == 3 * 48 + 1 == 145
    assert result.locator_attempts == 1
    assert len(s3.put_calls) == 145


def test_the_acquisition_path_performs_no_object_byte_read_listing_or_control_call() -> None:
    s3, _, result = _acquire()
    assert s3.get_calls == []
    assert result.counts.get_object_count == 0
    assert result.counts.list_operation_count == 0
    assert result.counts.control_operation_count == 0
    assert not hasattr(s3, "list_objects_v2")


def test_the_head_object_count_stays_inside_its_bound() -> None:
    s3, _, result = _acquire()
    assert result.counts.head_object_count == len(s3.head_calls)
    assert result.counts.head_object_count <= 3 * 48 + 1


def test_the_total_s3_operations_are_inside_the_accepted_envelope() -> None:
    _, _, result = _acquire()
    assert 145 <= result.counts.total_s3_operations <= 292


def test_every_written_object_is_licensed_and_none_is_control() -> None:
    s3, _, _ = _acquire()
    for key in s3.objects:
        assert key.startswith(("bronze/", "qualification/"))
        assert "control" not in key.lower()


def test_the_acquisition_writes_no_local_file(tmp_path: Any) -> None:
    before = set(tmp_path.iterdir())
    _acquire()
    assert set(tmp_path.iterdir()) == before


def test_a_provider_failure_halts_and_publishes_a_partial_locator() -> None:
    s3, _, result = _acquire(transport=PagedTransport(fail_after=10))
    assert result.status is AcquisitionStatus.PARTIAL
    assert result.counts.completed_requests == 10
    assert result.counts.put_object_count == 3 * 10 + 1
    document = json.loads(s3.objects["/".join(locator_key_segments(EXECUTION_ID))])
    assert document["completeness"] == "PARTIAL"
    assert document["completed_request_count"] == 10
    assert document["planned_request_count"] == 48


def test_a_locator_that_cannot_be_published_leaves_the_evidence_unaddressable() -> None:
    locator_key = "/".join(locator_key_segments(EXECUTION_ID))
    # A client-shaped error, so the real backend classifier is what turns it into
    # a definitive refusal. Raising an already-classified refusal would bypass the
    # classifier and prove nothing about it.
    s3 = FakeS3Client(fail_puts={locator_key: client_error("AccessDenied")})
    _, _, result = _acquire(s3=s3)
    assert result.status is AcquisitionStatus.LOCATOR_NOT_PUBLISHED
    assert result.addressable is False
    assert locator_key not in s3.objects


def test_the_public_result_carries_no_subject_key_digest_or_bucket() -> None:
    _, _, result = _acquire()
    rendered = f"{result!r} {result.counts!r}"
    for subject in SYNTHETIC_SUBJECTS:
        assert subject not in rendered
    assert SYNTHETIC_BUCKET not in rendered
    assert "licensed/" not in rendered


# -- assessment: the exact formulas -------------------------------------------


def test_a_complete_assessment_reads_two_r_plus_one_objects() -> None:
    s3, _, _ = _acquire()
    reader = _reader(s3)
    result = run_assessment(
        reader=reader, execution_id=EXECUTION_ID, assessment_id=ASSESSMENT_ID, clock=FixedClock()
    )
    assert result.status is AssessmentStatus.COMPLETED
    assert result.counts.get_object_count == 2 * 48 + 1 == 97
    assert result.counts.put_object_count == 1
    assert result.counts.head_object_count == 0
    assert result.counts.total_s3_operations == 98


def test_the_assessment_never_retrieves_an_acquisition_claim() -> None:
    s3, _, _ = _acquire()
    reader = _reader(s3)
    run_assessment(
        reader=reader, execution_id=EXECUTION_ID, assessment_id=ASSESSMENT_ID, clock=FixedClock()
    )
    claim_reads = [key for key in s3.get_calls if "_acquisition_claims" in key]
    assert claim_reads == []


def test_the_assessment_makes_no_provider_request_and_retrieves_no_credential() -> None:
    s3, _, _ = _acquire()
    result = run_assessment(
        reader=_reader(s3),
        execution_id=EXECUTION_ID,
        assessment_id=ASSESSMENT_ID,
        clock=FixedClock(),
    )
    assert result.counts.provider_request_count == 0
    assert result.counts.credential_retrieval_count == 0


def test_the_assessment_performs_no_listing_and_no_control_operation() -> None:
    s3, _, _ = _acquire()
    result = run_assessment(
        reader=_reader(s3),
        execution_id=EXECUTION_ID,
        assessment_id=ASSESSMENT_ID,
        clock=FixedClock(),
    )
    assert result.counts.list_operation_count == 0
    assert result.counts.control_operation_count == 0
    assert not hasattr(s3, "list_objects_v2")


def test_the_assessment_publishes_exactly_one_private_report() -> None:
    s3, _, _ = _acquire()
    run_assessment(
        reader=_reader(s3),
        execution_id=EXECUTION_ID,
        assessment_id=ASSESSMENT_ID,
        clock=FixedClock(),
    )
    reports = [key for key in s3.objects if key.startswith("qualification/sharadar/reports/")]
    assert reports == [f"qualification/sharadar/reports/{EXECUTION_ID}/{ASSESSMENT_ID}.json"]


def test_the_published_report_carries_the_nine_tests_and_no_verdict() -> None:
    s3, _, _ = _acquire()
    run_assessment(
        reader=_reader(s3),
        execution_id=EXECUTION_ID,
        assessment_id=ASSESSMENT_ID,
        clock=FixedClock(),
    )
    key = f"qualification/sharadar/reports/{EXECUTION_ID}/{ASSESSMENT_ID}.json"
    document = json.loads(s3.objects[key])
    assert [entry["test"] for entry in document["tests"]] == [f"P{i}" for i in range(1, 10)]
    rendered = json.dumps(document)
    for forbidden in ("PROCEED", "APPROVED", "QUALIFIED", "recommendation", "readiness"):
        assert forbidden not in rendered
    for subject in SYNTHETIC_SUBJECTS:
        assert subject not in rendered


def test_the_locator_is_addressed_from_the_execution_identity_alone() -> None:
    assert locator_logical_key(EXECUTION_ID) == (
        f"licensed/qualification/sharadar/locators/{EXECUTION_ID}.json"
    )


# -- assessment refusals fail closed ------------------------------------------


def test_a_missing_locator_refuses_and_reads_no_payload() -> None:
    s3 = FakeS3Client()
    reader = _reader(s3)
    with pytest.raises(AssessmentError) as raised:
        run_assessment(
            reader=reader,
            execution_id=EXECUTION_ID,
            assessment_id=ASSESSMENT_ID,
            clock=FixedClock(),
        )
    assert raised.value.status is AssessmentStatus.REFUSED_LOCATOR
    assert reader.get_object_count == 1
    assert reader.put_object_count == 0


def test_a_partial_locator_is_refused_and_no_payload_is_read() -> None:
    s3, _, _ = _acquire(transport=PagedTransport(fail_after=10))
    reader = _reader(s3)
    with pytest.raises(AssessmentError) as raised:
        run_assessment(
            reader=reader,
            execution_id=EXECUTION_ID,
            assessment_id=ASSESSMENT_ID,
            clock=FixedClock(),
        )
    assert raised.value.status is AssessmentStatus.REFUSED_LOCATOR
    # Exactly the refused-locator envelope: one GetObject and nothing else.
    assert reader.get_object_count == 1
    assert reader.put_object_count == 0
    assert reader.head_object_count == 0
    assert s3.get_calls == ["/".join(locator_key_segments(EXECUTION_ID))]


def test_an_assessment_for_another_execution_identity_is_refused() -> None:
    s3, _, _ = _acquire()
    reader = _reader(s3)
    with pytest.raises(AssessmentError) as raised:
        run_assessment(
            reader=reader,
            execution_id="synthetic-empirical-b",
            assessment_id=ASSESSMENT_ID,
            clock=FixedClock(),
        )
    assert raised.value.status is AssessmentStatus.REFUSED_LOCATOR


def test_a_tampered_payload_refuses_on_integrity_before_it_is_parsed() -> None:
    s3, _, _ = _acquire()
    payload_keys = [key for key in s3.objects if "/objects/sha256/" in key]
    s3.objects[payload_keys[0]] = b"ticker,date,close\nTAMPERED,1998-01-05,1\n"
    reader = _reader(s3)
    with pytest.raises(AssessmentError) as raised:
        run_assessment(
            reader=reader,
            execution_id=EXECUTION_ID,
            assessment_id=ASSESSMENT_ID,
            clock=FixedClock(),
        )
    assert raised.value.status is AssessmentStatus.REFUSED_INTEGRITY
    assert reader.put_object_count == 0


def test_a_record_contradicting_its_locator_entry_refuses_on_integrity() -> None:
    s3, _, _ = _acquire()
    record_keys = sorted(key for key in s3.objects if "/acquisitions/" in key)
    original = json.loads(s3.objects[record_keys[0]])
    original["dataset"] = "actions"
    # Re-published under the same name with different content: the digest check in
    # the reader is what catches it, before any interpretation happens.
    s3.objects[record_keys[0]] = json.dumps(original).encode("utf-8")
    with pytest.raises(AssessmentError) as raised:
        run_assessment(
            reader=_reader(s3),
            execution_id=EXECUTION_ID,
            assessment_id=ASSESSMENT_ID,
            clock=FixedClock(),
        )
    assert raised.value.status is AssessmentStatus.REFUSED_INTEGRITY


def test_an_unparseable_payload_refuses_on_evidence_and_publishes_no_report() -> None:
    # Published through the real acquisition path, so every digest, record and
    # locator entry stays mutually consistent and the **parser** is genuinely what
    # refuses. Editing a stored object afterwards would trip the integrity check
    # one stage earlier and prove nothing about the parser.
    ragged = b"ticker,date,close" + b"\n" + b"Z,1998-01-05" + b"\n"
    s3, _, result = _acquire(transport=PagedTransport(body_override=ragged))
    assert result.status is AcquisitionStatus.COMPLETED

    reader = _reader(s3)
    with pytest.raises(AssessmentError) as raised:
        run_assessment(
            reader=reader,
            execution_id=EXECUTION_ID,
            assessment_id=ASSESSMENT_ID,
            clock=FixedClock(),
        )
    assert raised.value.status is AssessmentStatus.REFUSED_EVIDENCE
    assert reader.put_object_count == 0


def test_no_assessment_refusal_carries_a_key_subject_or_bucket() -> None:
    s3 = FakeS3Client()
    with pytest.raises(AssessmentError) as raised:
        run_assessment(
            reader=_reader(s3),
            execution_id=EXECUTION_ID,
            assessment_id=ASSESSMENT_ID,
            clock=FixedClock(),
        )
    rendered = f"{raised.value} {raised.value!r} {raised.value.args}"
    for subject in SYNTHETIC_SUBJECTS:
        assert subject not in rendered
    assert SYNTHETIC_BUCKET not in rendered
    assert "licensed/" not in rendered


# -- the ADR-0017 surface is untouched ----------------------------------------


def test_the_earlier_authenticated_entry_point_is_not_imported_or_reused() -> None:
    from pathlib import Path

    import kalpamani.data.qualify.sharadar.acquisition as acquisition_module
    import kalpamani.data.qualify.sharadar.assessment as assessment_module

    for module in (acquisition_module, assessment_module):
        assert module.__file__ is not None
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "sharadar_authenticated_qualification" not in source
        assert "sharadar_private_qualification" not in source
