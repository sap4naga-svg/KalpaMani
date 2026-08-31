"""The private report: licensed, owner-only, never a recommendation, never local.

The report is the one artifact that carries evidence, so the tests that matter most
are about what it must **not** contain and where it must **not** go.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from fixtures.sharadar_empirical import (
    ACTIONS_CSV,
    STOCKS_CSV,
    SYNTHETIC_BUCKET,
    SYNTHETIC_SUBJECTS,
    TICKERS_CSV,
)
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.qualify.sharadar import report as report_module
from kalpamani.data.qualify.sharadar.evaluator import (
    CrossRunSubjectEvidence,
    SubjectEvidence,
    evaluate_combined,
)
from kalpamani.data.qualify.sharadar.evaluator import (
    TestResult as PerTestResult,  # aliased: pytest tries to collect a Test* class
)
from kalpamani.data.qualify.sharadar.parser import PagePair, parse_payload
from kalpamani.data.qualify.sharadar.report import (
    DELETION_OBLIGATION,
    MAX_REPORT_BYTES,
    REPORT_SCHEMA_VERSION,
    REPORT_SEGMENTS,
    RETENTION_BASIS,
    ReportDefect,
    ReportError,
    ReportEvidence,
    build_report_document,
    report_key_segments,
    report_object_key,
    serialize_report,
)

CREATED_AT = datetime(2026, 8, 30, 18, 0, 0, tzinfo=UTC)
RUN_A = "synthetic-empirical-a"
RUN_B = "synthetic-empirical-b"
ASSESSMENT = "synthetic-assess-a"

_BODIES = {
    SharadarDataset.TICKERS: TICKERS_CSV,
    SharadarDataset.STOCKS: STOCKS_CSV,
    SharadarDataset.ACTIONS: ACTIONS_CSV,
}


def _evidence() -> tuple[SubjectEvidence, ...]:
    pairs = {
        dataset: PagePair(
            dataset=dataset,
            first=parse_payload(body, dataset=dataset),
            second=parse_payload(body.split(b"\n", 1)[0] + b"\n", dataset=dataset),
        )
        for dataset, body in _BODIES.items()
    }
    return (SubjectEvidence(pairs=pairs),)


def _cross_run_evidence() -> tuple[CrossRunSubjectEvidence, ...]:
    """The same synthetic subject seen twice, which is what a combined report holds."""
    return tuple(CrossRunSubjectEvidence(first=subject, second=subject) for subject in _evidence())


def _report_evidence(**overrides: object) -> ReportEvidence:
    fields: dict[str, object] = {
        "run_a_execution_id": RUN_A,
        "run_b_execution_id": RUN_B,
        "assessment_id": ASSESSMENT,
        "run_a_plan_digest": "d" * 64,
        "run_b_plan_digest": "e" * 64,
        "inventory_digest": "b" * 64,
        "source_schema_version": "sharadar-empirical-v1",
        "planned_request_count": 48,
        "run_a_completed_request_count": 48,
        "run_b_completed_request_count": 48,
        "run_a_date": "2026-08-30",
        "run_b_date": "2026-09-08",
        "separation_days": 9,
        "objects_read": 194,
        "excluded_pair_count": 0,
        "observed_schema_digests": ("c" * 64,),
    }
    fields.update(overrides)
    return ReportEvidence(**fields)  # type: ignore[arg-type]


def _document() -> dict[str, Any]:
    return build_report_document(
        evidence=_report_evidence(),
        results=evaluate_combined(_cross_run_evidence()),
        created_at=CREATED_AT,
    )


# -- location and identity ----------------------------------------------------


def test_the_report_lives_under_the_licensed_qualification_reports_prefix() -> None:
    assert report_key_segments(
        run_a_execution_id=RUN_A, run_b_execution_id=RUN_B, assessment_id=ASSESSMENT
    ) == (
        "qualification",
        "sharadar",
        "reports",
        RUN_A,
        RUN_B,
        f"{ASSESSMENT}.json",
    )
    assert REPORT_SEGMENTS == ("qualification", "sharadar", "reports")


def test_the_key_preserves_run_a_then_run_b_order() -> None:
    forward = report_key_segments(
        run_a_execution_id=RUN_A, run_b_execution_id=RUN_B, assessment_id=ASSESSMENT
    )
    reversed_pair = report_key_segments(
        run_a_execution_id=RUN_B, run_b_execution_id=RUN_A, assessment_id=ASSESSMENT
    )
    # A report filed under the reversed pair would describe a comparison nobody
    # made, so the two must not share a name.
    assert forward != reversed_pair
    assert forward[3:5] == (RUN_A, RUN_B)


def test_identical_execution_identities_are_refused_at_key_construction() -> None:
    with pytest.raises(ReportError) as raised:
        report_key_segments(
            run_a_execution_id=RUN_A, run_b_execution_id=RUN_A, assessment_id=ASSESSMENT
        )
    assert raised.value.defect is ReportDefect.IDENTITY_MALFORMED


def test_the_key_carries_a_separate_assessment_identity() -> None:
    first = report_key_segments(
        run_a_execution_id=RUN_A, run_b_execution_id=RUN_B, assessment_id="assess-one"
    )
    second = report_key_segments(
        run_a_execution_id=RUN_A, run_b_execution_id=RUN_B, assessment_id="assess-two"
    )
    # Re-assessment of one pair is the cheap operation this design exists to make
    # possible, so a second assessment must not collide with the first.
    assert first != second
    assert first[:-1] == second[:-1]


def test_a_windows_device_name_identity_is_refused_at_key_construction() -> None:
    with pytest.raises(ReportError) as raised:
        report_key_segments(run_a_execution_id=RUN_A, run_b_execution_id=RUN_B, assessment_id="aux")
    assert raised.value.defect is ReportDefect.IDENTITY_MALFORMED


def test_the_report_key_is_licensed() -> None:
    payload = serialize_report(_document())
    key = report_object_key(
        run_a_execution_id=RUN_A,
        run_b_execution_id=RUN_B,
        assessment_id=ASSESSMENT,
        payload=payload,
    )
    assert key.logical_key.startswith("licensed/qualification/sharadar/reports/")


# -- contents -----------------------------------------------------------------


def test_the_report_carries_the_accepted_contents() -> None:
    document = _document()
    assert document["schema_version"] == REPORT_SCHEMA_VERSION
    assert document["classification"] == "LICENSED"
    assert document["retention_basis"] == RETENTION_BASIS
    assert document["deletion_obligation"] == DELETION_OBLIGATION
    assert document["created_at"] == CREATED_AT.isoformat()
    assert document["profile"] == "PROVIDER_REALISTIC_PIT"
    assert document["acquisition_mode"] == "QUALIFICATION"


def test_the_report_binds_the_evidence_by_digest() -> None:
    evidence = _document()["evidence"]
    # Two distinct values, so a crossed field-to-key mapping would show. The builder
    # does not enforce the pair rule -- the combined assessor does, and it refuses a
    # pair whose plan digests differ before any record or payload is read.
    assert evidence["run_a_plan_digest"] == "d" * 64
    assert evidence["run_b_plan_digest"] == "e" * 64
    assert evidence["inventory_digest"] == "b" * 64
    assert evidence["observed_schema_digests"] == ["c" * 64]


def test_the_report_carries_all_nine_tests_with_both_ceilings() -> None:
    tests = _document()["tests"]
    assert isinstance(tests, list)
    assert [entry["test"] for entry in tests] == [f"P{index}" for index in range(1, 10)]
    for entry in tests:
        assert "ceiling" in entry
        assert "single_execution_ceiling" in entry
        assert isinstance(entry["limbs"], list)


def test_the_report_carries_per_limb_reasons_and_measurements() -> None:
    tests = _document()["tests"]
    limbs = [limb for entry in tests for limb in entry["limbs"]]
    assert limbs
    for limb in limbs:
        assert set(limb) == {"limb", "status", "reason", "measurements"}
        for measurement in limb["measurements"]:
            assert set(measurement) == {"name", "kind", "value"}


# -- what it must never contain -----------------------------------------------


def test_the_report_carries_no_aggregate_verdict_or_provider_selection() -> None:
    rendered = json.dumps(_document())
    for forbidden in (
        "PROCEED",
        "HOLD",
        "REJECT",
        "QUALIFIED",
        "APPROVED",
        "READY",
        "recommendation",
        "provider_selection",
        "readiness",
        "verdict",
        "overall",
        "aggregate",
    ):
        assert forbidden not in rendered


def test_the_report_names_no_security() -> None:
    rendered = json.dumps(_document())
    for subject in SYNTHETIC_SUBJECTS:
        assert subject not in rendered


def test_the_report_names_no_bucket_account_url_or_credential() -> None:
    rendered = json.dumps(_document())
    for forbidden in (SYNTHETIC_BUCKET, "amazonaws.com", "https://", "api_key"):
        assert forbidden not in rendered


def test_the_report_carries_no_vendor_row() -> None:
    rendered = json.dumps(_document())
    # A distinctive value from every synthetic body.
    for value in ("900001", "10.25", "Synthetic Holdings", "closeunadj"):
        assert value not in rendered


def test_the_report_has_no_free_text_field() -> None:
    document = _document()
    assert set(document["evidence"]) == {
        "run_a_execution_id",
        "run_b_execution_id",
        "assessment_id",
        "run_a_plan_digest",
        "run_b_plan_digest",
        "inventory_digest",
        "source_schema_version",
        "planned_request_count",
        "run_a_completed_request_count",
        "run_b_completed_request_count",
        "run_a_date",
        "run_b_date",
        "separation_days",
        "objects_read",
        "excluded_pair_count",
        "observed_schema_digests",
    }
    for field in document:
        for forbidden in ("note", "comment", "message", "description", "recommendation"):
            assert forbidden not in field


# -- serialisation ------------------------------------------------------------


def test_the_report_serialises_deterministically() -> None:
    assert serialize_report(_document()) == serialize_report(_document())


def test_the_report_is_inside_its_size_ceiling() -> None:
    assert 0 < len(serialize_report(_document())) <= MAX_REPORT_BYTES


def test_an_oversize_report_is_refused() -> None:
    with pytest.raises(ReportError) as raised:
        serialize_report({"padding": "x" * (MAX_REPORT_BYTES + 10)})
    assert raised.value.defect is ReportDefect.TOO_LARGE


def test_a_naive_creation_instant_is_refused() -> None:
    with pytest.raises(ReportError) as raised:
        build_report_document(
            evidence=_report_evidence(),
            results=evaluate_combined(_cross_run_evidence()),
            created_at=datetime(2026, 8, 30, 18, 0, 0),
        )
    assert raised.value.defect is ReportDefect.FIELD_MALFORMED


def test_results_that_are_not_test_results_are_refused() -> None:
    # Deliberately the wrong type: the point of the test is the refusal, so the
    # violation is cast at the call site rather than hidden behind an ignore.
    wrong = cast(tuple[PerTestResult, ...], (object(),))
    with pytest.raises(ReportError) as raised:
        build_report_document(evidence=_report_evidence(), results=wrong, created_at=CREATED_AT)
    assert raised.value.defect is ReportDefect.RESULTS_MALFORMED


def test_an_empty_result_set_is_refused() -> None:
    with pytest.raises(ReportError) as raised:
        build_report_document(evidence=_report_evidence(), results=(), created_at=CREATED_AT)
    assert raised.value.defect is ReportDefect.RESULTS_MALFORMED


# -- no local copy ------------------------------------------------------------


def test_the_module_writes_no_local_file_and_offers_no_output_path() -> None:
    source = Path(report_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "write_text",
        "write_bytes",
        "mkdir",
        "tempfile",
        "open(",
        ".runtime/",
        "output_path",
    ):
        assert forbidden not in source


def test_the_module_constructs_no_sdk_client_and_names_no_cloud() -> None:
    source = Path(report_module.__file__).read_text(encoding="utf-8")
    for forbidden in ("boto3", "botocore", "amazonaws", "Session(", "CONTROL"):
        assert forbidden not in source
