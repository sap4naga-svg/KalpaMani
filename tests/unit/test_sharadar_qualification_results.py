"""Result structures are checked at construction, not merely annotated.

:class:`RequestOutcome` and :class:`QualificationRunResult` are exported and
described as safe to log. An annotation is a static claim: it stops a type
checker, and stops nothing at run time. A caller — or a future edit — can build
either with a string subclass, a negative count, a wrong profile or a summary that
contradicts its own detail, and the object would be handed on as evidence.

So both validate every field against its own contract, and the result re-derives
every count from ``outcomes`` and refuses a record whose summary and detail
disagree. **A summary nobody checked is the part of a report that goes wrong
quietly.**

Every refusal is one closed-vocabulary failure raised ``from None``. Nothing here
opens a socket, and nothing here is real.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from fixtures.sharadar_runtime import RUN_INSTANT, SUBJECT_A
from kalpamani.data.contracts.canonical import sha256_hex
from kalpamani.data.contracts.vocabulary import DataClassification, InformationSetProfile
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.ingest.sharadar.qualification import (
    MAX_PAGES_PER_REQUEST,
    MAX_RUN_BYTES,
    PERMITTED_PROFILE,
)
from kalpamani.data.ingest.sharadar.runtime import (
    AcquisitionDisposition,
    QualificationFailure,
    QualificationOutcome,
    QualificationRunResult,
    QualificationRuntimeError,
    RequestOutcome,
    classify_publication,
)

pytestmark = pytest.mark.unit

DIGEST = sha256_hex(b"synthetic-opaque-qualification-payload-0001")
ACQUISITION = "synthetic-exec-0001.3e352984ee2a177fa4b9e3eb"


def outcome(**overrides: Any) -> RequestOutcome:
    fields: dict[str, Any] = {
        "dataset": SharadarDataset.TICKERS,
        "subject": SUBJECT_A,
        "page_skip": 0,
        "page_limit": 500,
        "acquisition_id": ACQUISITION,
        "content_sha256": DIGEST,
        "byte_count": 42,
        "retrieved_at": RUN_INSTANT,
        "claim_written": True,
        "payload_written": True,
        "acquisition_written": True,
        "disposition": AcquisitionDisposition.FULLY_NEW,
        "classification": DataClassification.LICENSED,
        "profile": PERMITTED_PROFILE,
    }
    fields.update(overrides)
    return RequestOutcome(**fields)


def result(**overrides: Any) -> QualificationRunResult:
    one = outcome()
    fields: dict[str, Any] = {
        "outcome": QualificationOutcome.COMPLETED,
        "failure": None,
        "planned_requests": 1,
        "completed_requests": 1,
        "acquisitions_recorded": 1,
        "payloads_reused": 0,
        "already_complete": 0,
        "fetched_payload_bytes": one.byte_count,
        "published_payload_bytes": one.byte_count,
        "run_byte_ceiling": MAX_RUN_BYTES,
        "outcomes": (one,),
        "partial": False,
        "publication_state_unknown": False,
    }
    fields.update(overrides)
    return QualificationRunResult(**fields)


def test_the_baseline_fixtures_are_valid() -> None:
    """A negative-test file whose positive case is broken proves nothing."""
    assert outcome().disposition is AcquisitionDisposition.FULLY_NEW
    assert result().outcome is QualificationOutcome.COMPLETED


# ---------------------------------------------------------------------------
# RequestOutcome
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("dataset", "tickers"),
        ("dataset", None),
        ("dataset", 7),
        ("subject", "zzqa"),
        ("subject", ""),
        ("subject", "ZZ QA"),
        ("subject", 7),
        ("page_skip", -1),
        ("page_skip", True),
        ("page_skip", 1.0),
        ("page_limit", 0),
        ("page_limit", -5),
        ("page_limit", "500"),
        ("acquisition_id", ""),
        ("acquisition_id", "Has-Upper"),
        ("acquisition_id", "x" * 65),
        ("acquisition_id", 7),
        ("content_sha256", "not-a-digest"),
        ("content_sha256", DIGEST.upper()),
        ("content_sha256", DIGEST[:-1]),
        ("content_sha256", 7),
        ("byte_count", -1),
        ("byte_count", "42"),
        ("retrieved_at", None),
        ("retrieved_at", "2026-08-28T15:30:00Z"),
        ("retrieved_at", datetime(2026, 8, 28, 15, 30, 0)),
        ("claim_written", 1),
        ("payload_written", "yes"),
        ("acquisition_written", None),
        ("disposition", "FULLY_NEW"),
        ("disposition", None),
        ("classification", DataClassification.CONTROL),
        ("classification", "LICENSED"),
        ("profile", InformationSetProfile.PUBLIC_PIT),
        ("profile", InformationSetProfile.FORWARD_SYSTEM),
        ("profile", "PROVIDER_REALISTIC_PIT"),
    ],
)
def test_a_malformed_outcome_field_is_refused(field: str, value: Any) -> None:
    with pytest.raises(QualificationRuntimeError) as caught:
        outcome(**{field: value})
    assert caught.value.failure is QualificationFailure.RESULT_MALFORMED
    assert caught.value.__cause__ is None


def test_a_string_subclass_subject_is_refused() -> None:
    """A subclass can override `__eq__` after passing a grammar check."""

    class Sneaky(str):
        def __eq__(self, other: object) -> bool:
            return True

        __hash__ = str.__hash__

    with pytest.raises(QualificationRuntimeError):
        outcome(subject=Sneaky(SUBJECT_A))


def test_a_string_subclass_digest_is_refused() -> None:
    class Sneaky(str):
        pass

    with pytest.raises(QualificationRuntimeError):
        outcome(content_sha256=Sneaky(DIGEST))


def test_a_disposition_that_contradicts_its_flags_is_refused() -> None:
    """A record whose summary disagrees with the three facts it summarises is a
    record that contradicts itself."""
    with pytest.raises(QualificationRuntimeError):
        outcome(
            claim_written=False,
            payload_written=False,
            acquisition_written=False,
            disposition=AcquisitionDisposition.FULLY_NEW,
        )


@pytest.mark.parametrize(
    "flags,expected",
    [
        ((True, True, True), AcquisitionDisposition.FULLY_NEW),
        ((True, False, True), AcquisitionDisposition.PAYLOAD_REUSED),
        ((False, False, False), AcquisitionDisposition.ALREADY_COMPLETE),
        ((False, True, True), AcquisitionDisposition.COMPLETED_PRIOR_PARTIAL),
        ((True, True, False), AcquisitionDisposition.COMPLETED_PRIOR_PARTIAL),
        ((False, False, True), AcquisitionDisposition.COMPLETED_PRIOR_PARTIAL),
        ((True, False, False), AcquisitionDisposition.COMPLETED_PRIOR_PARTIAL),
        ((False, True, False), AcquisitionDisposition.COMPLETED_PRIOR_PARTIAL),
    ],
)
def test_every_combination_of_write_dispositions_classifies(
    flags: tuple[bool, bool, bool], expected: AcquisitionDisposition
) -> None:
    """Eight combinations, four categories, and no combination left undefined."""
    claim, payload, acquisition = flags
    assert (
        classify_publication(
            claim_written=claim, payload_written=payload, acquisition_written=acquisition
        )
        is expected
    )
    assert (
        outcome(
            claim_written=claim,
            payload_written=payload,
            acquisition_written=acquisition,
            disposition=expected,
        ).disposition
        is expected
    )


def test_a_non_utc_aware_instant_is_refused() -> None:
    """The runtime normalises to UTC before building an outcome, so a
    non-UTC instant here means something bypassed that."""
    elsewhere = RUN_INSTANT.astimezone(timezone(timedelta(hours=-5)))
    with pytest.raises(QualificationRuntimeError):
        outcome(retrieved_at=elsewhere)


def test_an_outcome_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    built = outcome()
    with pytest.raises(FrozenInstanceError):
        built.byte_count = 0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# QualificationRunResult: the summary must be the detail, recomputed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("outcome", "COMPLETED"),
        ("outcome", None),
        ("failure", "STORAGE_REFUSED"),
        ("outcomes", [outcome()]),
        ("outcomes", (object(),)),
        ("outcomes", None),
        ("partial", 0),
        ("publication_state_unknown", "no"),
        ("planned_requests", -1),
        ("planned_requests", True),
        ("completed_requests", "1"),
        ("acquisitions_recorded", -2),
        ("fetched_payload_bytes", -1),
        ("published_payload_bytes", -1),
        ("run_byte_ceiling", 0),
        ("run_byte_ceiling", MAX_RUN_BYTES + 1),
        ("run_byte_ceiling", "many"),
    ],
)
def test_a_malformed_result_field_is_refused(field: str, value: Any) -> None:
    with pytest.raises(QualificationRuntimeError) as caught:
        result(**{field: value})
    assert caught.value.failure is QualificationFailure.RESULT_MALFORMED


def test_a_completed_count_that_disagrees_with_the_outcomes_is_refused() -> None:
    with pytest.raises(QualificationRuntimeError):
        result(completed_requests=2, planned_requests=2)


def test_more_completed_than_planned_is_refused() -> None:
    with pytest.raises(QualificationRuntimeError):
        result(planned_requests=0, completed_requests=1)


def test_published_bytes_must_equal_the_completed_outcomes() -> None:
    with pytest.raises(QualificationRuntimeError):
        result(published_payload_bytes=999, fetched_payload_bytes=999)


def test_fetched_bytes_may_exceed_published_bytes() -> None:
    """A payload that arrived and then failed to publish was still delivered."""
    one = outcome()
    built = QualificationRunResult(
        outcome=QualificationOutcome.HALTED,
        failure=QualificationFailure.STORAGE_REFUSED,
        planned_requests=3,
        completed_requests=1,
        acquisitions_recorded=1,
        payloads_reused=0,
        already_complete=0,
        fetched_payload_bytes=one.byte_count * 2,
        published_payload_bytes=one.byte_count,
        run_byte_ceiling=MAX_RUN_BYTES,
        outcomes=(one,),
        partial=True,
        publication_state_unknown=True,
    )
    assert built.fetched_payload_bytes > built.published_payload_bytes


def test_fetched_bytes_below_published_bytes_is_refused() -> None:
    """Everything published was fetched first, so the reverse is impossible."""
    with pytest.raises(QualificationRuntimeError):
        result(fetched_payload_bytes=1)


def test_fetched_bytes_above_the_run_ceiling_are_refused() -> None:
    with pytest.raises(QualificationRuntimeError):
        result(
            fetched_payload_bytes=100,
            published_payload_bytes=42,
            run_byte_ceiling=50,
        )


@pytest.mark.parametrize("field", ["acquisitions_recorded", "payloads_reused", "already_complete"])
def test_a_derived_count_that_disagrees_with_the_outcomes_is_refused(field: str) -> None:
    with pytest.raises(QualificationRuntimeError):
        result(**{field: 7})


def test_completed_cannot_carry_a_failure() -> None:
    with pytest.raises(QualificationRuntimeError):
        result(failure=QualificationFailure.STORAGE_REFUSED)


def test_completed_cannot_be_partial() -> None:
    with pytest.raises(QualificationRuntimeError):
        result(partial=True)


def test_completed_cannot_have_unfinished_planned_requests() -> None:
    """The invariant that stops a halted run masquerading as a completed one."""
    with pytest.raises(QualificationRuntimeError):
        result(planned_requests=3)


def test_completed_cannot_have_an_unknown_publication_state() -> None:
    with pytest.raises(QualificationRuntimeError):
        result(publication_state_unknown=True)


def test_halted_must_name_a_failure_and_be_partial() -> None:
    halted: dict[str, Any] = {
        "outcome": QualificationOutcome.HALTED,
        "failure": QualificationFailure.STORAGE_REFUSED,
        "partial": True,
        "planned_requests": 3,
    }
    assert QualificationRunResult(**{**_baseline(), **halted}).partial is True
    with pytest.raises(QualificationRuntimeError):
        QualificationRunResult(**{**_baseline(), **halted, "failure": None})
    with pytest.raises(QualificationRuntimeError):
        QualificationRunResult(**{**_baseline(), **halted, "partial": False})


def test_a_halted_result_with_more_completed_than_planned_is_refused() -> None:
    """Checked in the HALTED branch specifically, not inherited from COMPLETED."""
    with pytest.raises(QualificationRuntimeError):
        QualificationRunResult(**{**_baseline(), "planned_requests": 0})


def test_a_halted_result_that_completed_everything_it_planned_is_refused() -> None:
    """A halted run that finished its whole plan is a completed run wearing a
    failure code. Nothing in the earlier invariants forbade it."""
    with pytest.raises(QualificationRuntimeError):
        QualificationRunResult(**{**_baseline(), "planned_requests": 1})


def test_duplicated_acquisition_identities_are_refused() -> None:
    """Two retrievals cannot share one identity: that is the point of deriving
    one per request, and durable evidence like this cannot exist."""
    first = outcome()
    second = outcome(page_skip=500)
    assert first.acquisition_id == second.acquisition_id
    with pytest.raises(QualificationRuntimeError):
        QualificationRunResult(
            **{
                **_baseline(),
                "planned_requests": 3,
                "completed_requests": 2,
                "acquisitions_recorded": 2,
                "outcomes": (first, second),
                "fetched_payload_bytes": first.byte_count * 2,
                "published_payload_bytes": first.byte_count * 2,
            }
        )


def test_duplicated_request_coordinates_are_refused_even_with_distinct_ids() -> None:
    """Checked separately from the identity: a bug in the derivation would give
    one coordinate two identities, and an identity-only check would report that
    as two retrievals."""
    first = outcome()
    second = outcome(acquisition_id="synthetic-exec-0001.ffffffffffffffffffffffff")
    assert first.acquisition_id != second.acquisition_id
    coordinate = (first.dataset, first.subject, first.page_limit, first.page_skip)
    assert coordinate == (second.dataset, second.subject, second.page_limit, second.page_skip)
    with pytest.raises(QualificationRuntimeError):
        QualificationRunResult(
            **{
                **_baseline(),
                "planned_requests": 3,
                "completed_requests": 2,
                "acquisitions_recorded": 2,
                "outcomes": (first, second),
                "fetched_payload_bytes": first.byte_count * 2,
                "published_payload_bytes": first.byte_count * 2,
            }
        )


@pytest.mark.parametrize(
    "skip,limit",
    [
        (1, 500),  # off the generated grid
        (250, 500),
        (500 * MAX_PAGES_PER_REQUEST, 500),  # beyond the page ceiling
        (500 * (MAX_PAGES_PER_REQUEST + 3), 500),
    ],
)
def test_a_page_offset_off_the_generated_grid_is_refused(skip: int, limit: int) -> None:
    """Pages walk `skip = index * limit` below the page ceiling. An offset off
    that grid describes a request no plan produced."""
    with pytest.raises(QualificationRuntimeError):
        outcome(page_skip=skip, page_limit=limit)


def test_a_page_limit_above_the_vendors_documented_maximum_is_refused() -> None:
    from kalpamani.data.ingest.sharadar.datasets import MAX_PAGE_LIMIT

    with pytest.raises(QualificationRuntimeError):
        outcome(page_limit=MAX_PAGE_LIMIT + 1)


def test_refused_must_be_empty() -> None:
    empty: dict[str, Any] = {
        "outcome": QualificationOutcome.REFUSED,
        "failure": None,
        "planned_requests": 4,
        "completed_requests": 0,
        "acquisitions_recorded": 0,
        "payloads_reused": 0,
        "already_complete": 0,
        "fetched_payload_bytes": 0,
        "published_payload_bytes": 0,
        "run_byte_ceiling": MAX_RUN_BYTES,
        "outcomes": (),
        "partial": False,
        "publication_state_unknown": False,
    }
    assert QualificationRunResult(**empty).outcome is QualificationOutcome.REFUSED
    for contradiction in (
        {"failure": QualificationFailure.STORAGE_REFUSED},
        {"partial": True},
        {"publication_state_unknown": True},
        {
            "outcomes": (outcome(),),
            "completed_requests": 1,
            "acquisitions_recorded": 1,
            "fetched_payload_bytes": outcome().byte_count,
            "published_payload_bytes": outcome().byte_count,
        },
    ):
        with pytest.raises(QualificationRuntimeError):
            QualificationRunResult(**{**empty, **contradiction})


def test_an_unknown_publication_state_only_belongs_to_a_halted_run() -> None:
    with pytest.raises(QualificationRuntimeError):
        result(publication_state_unknown=True)


def test_a_result_carries_no_caller_controlled_text() -> None:
    from dataclasses import fields

    names = {field.name for field in fields(QualificationRunResult)}
    assert not names & {"message", "error", "detail", "notes", "url", "bucket", "payload"}


def test_a_result_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    built = result()
    with pytest.raises(FrozenInstanceError):
        built.partial = True  # type: ignore[misc]


def _baseline() -> dict[str, Any]:
    one = outcome()
    return {
        "outcome": QualificationOutcome.HALTED,
        "failure": QualificationFailure.STORAGE_REFUSED,
        "planned_requests": 3,
        "completed_requests": 1,
        "acquisitions_recorded": 1,
        "payloads_reused": 0,
        "already_complete": 0,
        "fetched_payload_bytes": one.byte_count,
        "published_payload_bytes": one.byte_count,
        "run_byte_ceiling": MAX_RUN_BYTES,
        "outcomes": (one,),
        "partial": True,
        "publication_state_unknown": False,
    }


def test_a_result_error_is_sanitized_and_unchained() -> None:
    error = QualificationRuntimeError(QualificationFailure.RESULT_MALFORMED)
    assert str(error) == "sharadar qualification runtime refused: RESULT_MALFORMED"
    assert error.__cause__ is None
    assert set(QualificationRuntimeError.__slots__) == {"failure"}


def test_utc_is_the_only_admitted_zone() -> None:
    assert RUN_INSTANT.tzinfo is UTC
