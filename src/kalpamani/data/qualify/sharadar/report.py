"""The canonical private report. **LICENSED, owner-only, and never a recommendation.**

```text
licensed/qualification/sharadar/reports/<run-a-execution-id>/<run-b-execution-id>/<assessment-id>.json
```

**Three separately validated path segments, in fixed Run A / Run B order.** One
combined assessment covers both acquisition executions, so the report is addressed
by both -- and the order is part of the address rather than a convention, because a
report filed under the reversed pair would describe a comparison nobody made.
:func:`report_key_segments` refuses identical execution identities: a pair that is
one run twice is not a cross-run comparison, and it must not be able to acquire a
name that says it is.

**One report per combined assessment.** There is no preliminary Run A report in this
architecture, and adding one would be another decision and another authorization.

**The assessment identity is separate from the execution identities, and that is
what makes re-assessment cheap.** Without it, a report write that failed ambiguously
would leave the name occupied by unknown content and block re-assessment of that
pair permanently -- while re-assessment is precisely the operation this whole
architecture exists to make possible, since it makes zero provider requests. A new
assessment identity is the remedy, and the report write is therefore **never
retried**.

**No routine local copy exists, and none can.** There is no output-path option, no
temporary file and no local write anywhere in this module: the report is
serialized in memory and handed to the conditional publisher. An uncontrolled local
copy is structurally impossible rather than discouraged.

**It carries no provider-selection recommendation, and nothing that reads as one.**
There is no aggregate verdict, no readiness value, no G1 or G2 field and no word in
the schema that could be mistaken for permission. A test asserts the absence of
every such spelling.

**It carries no security name.** The evaluator aggregates across subjects and emits
counts, so no ticker travels into a measurement -- and the report schema has no field
one could arrive through. The inventory is bound by digest instead, which proves
*which* inventory produced the evidence without disclosing it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes
from kalpamani.data.contracts.paths import path_segment
from kalpamani.data.contracts.vocabulary import AcquisitionMode, DataClassification
from kalpamani.data.ingest.sharadar.datasets import PROVIDER
from kalpamani.data.ingest.sharadar.qualification import PERMITTED_PROFILE
from kalpamani.data.objectstore import ObjectKey
from kalpamani.data.qualify.sharadar.evaluator import TestResult

#: The report namespace, inside the licensed ``qualification/`` prefix the deletion
#: runbook already deletes wholesale.
REPORT_SEGMENTS: Final[tuple[str, ...]] = ("qualification", "sharadar", "reports")

#: The one schema version this package writes.
REPORT_SCHEMA_VERSION: Final = "kalpamani-sharadar-empirical-report-v1"

#: At most 1 MiB. A report of nine tests and their limbs is a few kilobytes; the
#: ceiling exists so a defect that multiplied entries cannot publish an enormous
#: object into a licensed bucket that has no versioning to recover from.
MAX_REPORT_BYTES: Final = 1024 * 1024

#: Why this artifact is retained, and under what obligation. Closed tokens rather
#: than prose, so the retention basis is a value a program can check rather than a
#: sentence somebody has to read.
RETENTION_BASIS: Final = "SHARADAR_PERSONAL_USE_LICENSE_PRIVATE_EVALUATION"
DELETION_OBLIGATION: Final = "LICENSED_PREFIX_DELETION_WITHIN_30_DAYS_OF_TERMINATION"


class ReportDefect(StrEnum):
    """Why a report was refused. Closed, and carrying no value."""

    IDENTITY_MALFORMED = "IDENTITY_MALFORMED"
    RESULTS_MALFORMED = "RESULTS_MALFORMED"
    FIELD_MALFORMED = "FIELD_MALFORMED"
    TOO_LARGE = "TOO_LARGE"


class ReportError(Exception):
    """A refusal carrying exactly one :class:`ReportDefect`, raised ``from None``."""

    __slots__ = ("defect",)

    def __init__(self, defect: ReportDefect) -> None:
        """Bind the defect. The message is the member's token, nothing more."""
        if type(defect) is not ReportDefect:  # pragma: no cover - type guard
            raise TypeError("a defect must be an exact ReportDefect member")
        super().__init__(defect.value)
        self.defect = defect


def _refuse(defect: ReportDefect) -> ReportError:
    return ReportError(defect)


def report_key_segments(
    *, run_a_execution_id: str, run_b_execution_id: str, assessment_id: str
) -> tuple[str, ...]:
    """The report's key segments. **No listing is involved, and none is possible.**

    Three segments, in fixed Run A then Run B then assessment order. Each identity
    passes the existing path-segment grammar separately -- a joined identity would
    let a separator inside one of them redraw the boundary between two -- and that
    grammar refuses a leading underscore, a reserved prefix, a trailing dot and a
    Windows device name at any extension.

    Raises:
        ReportError: ``IDENTITY_MALFORMED`` if any identity cannot name an object,
            or if the two execution identities are the same. **One run twice is not
            a cross-run comparison**, and it may not acquire a name that says it is.
    """
    if (
        type(run_a_execution_id) is not str
        or type(run_b_execution_id) is not str
        or type(assessment_id) is not str
    ):
        raise _refuse(ReportDefect.IDENTITY_MALFORMED) from None
    if run_a_execution_id == run_b_execution_id:
        raise _refuse(ReportDefect.IDENTITY_MALFORMED) from None
    try:
        run_a = path_segment(run_a_execution_id, kind="execution")
        run_b = path_segment(run_b_execution_id, kind="execution")
        assessment = path_segment(f"{assessment_id}.json", kind="assessment")
    except Exception:
        raise _refuse(ReportDefect.IDENTITY_MALFORMED) from None
    return (*REPORT_SEGMENTS, run_a, run_b, assessment)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportEvidence:
    """What the report says the evidence was, all of it bound by digest.

    Every field here is an identity or a count. **None of them is a security name,
    a bucket, an account, a credential, a provider URL or a vendor row**, and there
    is no field one could arrive through.
    """

    run_a_execution_id: str
    run_b_execution_id: str
    assessment_id: str
    #: The comparable half of the plan, shared by both runs, and each run's own
    #: per-execution digest. Three values rather than one, because the
    #: per-execution digests bind the window and the identity and therefore
    #: differ by design -- recording only a shared digest would hide what each
    #: run actually asked for.
    plan_shape_digest: str
    run_a_plan_digest: str
    run_b_plan_digest: str
    inventory_digest: str
    source_schema_version: str
    #: Per execution, and equal across the pair by the combined assessor's own
    #: admission rules -- which is why one field describes both.
    planned_request_count: int
    run_a_completed_request_count: int
    run_b_completed_request_count: int
    #: The two accepted run dates and the separation between them, in calendar days.
    #: Recorded because the eight-day rule is what makes the comparison meaningful,
    #: and a report that asserted a cross-run result without saying how far apart the
    #: runs were would be asking a reader to take the interval on trust.
    run_a_date: str
    run_b_date: str
    separation_days: int
    objects_read: int
    excluded_pair_count: int
    observed_schema_digests: tuple[str, ...]

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so evidence identity cannot be restated."""
        raise TypeError("ReportEvidence may not be subclassed")


def build_report_document(
    *,
    evidence: ReportEvidence,
    results: tuple[TestResult, ...],
    created_at: datetime,
) -> dict[str, Any]:
    """The complete private report document for one assessment.

    Raises:
        ReportError: ``RESULTS_MALFORMED`` for anything that is not an exact tuple
            of :class:`~kalpamani.data.qualify.sharadar.evaluator.TestResult`;
            ``FIELD_MALFORMED`` for a naive creation instant or malformed evidence.
    """
    if type(evidence) is not ReportEvidence:
        raise _refuse(ReportDefect.FIELD_MALFORMED) from None
    if type(results) is not tuple or not results:
        raise _refuse(ReportDefect.RESULTS_MALFORMED) from None
    for result in results:
        if type(result) is not TestResult:
            raise _refuse(ReportDefect.RESULTS_MALFORMED) from None
    if type(created_at) is not datetime or created_at.tzinfo is None:
        raise _refuse(ReportDefect.FIELD_MALFORMED) from None

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "classification": DataClassification.LICENSED.value,
        "provider": PROVIDER,
        "acquisition_mode": AcquisitionMode.QUALIFICATION.value,
        "profile": PERMITTED_PROFILE.value,
        "created_at": created_at.astimezone(UTC).isoformat(),
        "retention_basis": RETENTION_BASIS,
        "deletion_obligation": DELETION_OBLIGATION,
        "evidence": {
            "run_a_execution_id": evidence.run_a_execution_id,
            "run_b_execution_id": evidence.run_b_execution_id,
            "assessment_id": evidence.assessment_id,
            "plan_shape_digest": evidence.plan_shape_digest,
            "run_a_plan_digest": evidence.run_a_plan_digest,
            "run_b_plan_digest": evidence.run_b_plan_digest,
            "inventory_digest": evidence.inventory_digest,
            "source_schema_version": evidence.source_schema_version,
            "planned_request_count": evidence.planned_request_count,
            "run_a_completed_request_count": evidence.run_a_completed_request_count,
            "run_b_completed_request_count": evidence.run_b_completed_request_count,
            "run_a_date": evidence.run_a_date,
            "run_b_date": evidence.run_b_date,
            "separation_days": evidence.separation_days,
            "objects_read": evidence.objects_read,
            "excluded_pair_count": evidence.excluded_pair_count,
            "observed_schema_digests": list(evidence.observed_schema_digests),
        },
        "tests": [
            {
                "test": result.test.value,
                "status": result.status.value,
                "ceiling": result.ceiling.value,
                "single_execution_ceiling": result.single_execution_ceiling.value,
                "evidence_scope": result.evidence_scope.value,
                "limbs": [
                    {
                        "limb": limb.limb.value,
                        "status": limb.status.value,
                        "reason": limb.reason.value,
                        "measurements": [
                            {
                                "name": measurement.name.value,
                                "kind": measurement.kind.value,
                                "value": measurement.value,
                            }
                            for measurement in limb.measurements
                        ],
                    }
                    for limb in result.limbs
                ],
            }
            for result in results
        ],
    }


def serialize_report(document: dict[str, Any]) -> bytes:
    """Canonical bytes for one report, refused above the size ceiling.

    Raises:
        ReportError: ``TOO_LARGE`` above :data:`MAX_REPORT_BYTES`.
    """
    payload = canonical_bytes(document)
    if len(payload) > MAX_REPORT_BYTES:
        raise _refuse(ReportDefect.TOO_LARGE) from None
    return payload


def report_object_key(
    *,
    run_a_execution_id: str,
    run_b_execution_id: str,
    assessment_id: str,
    payload: bytes,
) -> ObjectKey:
    """The LICENSED key one combined report payload is published under."""
    return ObjectKey.licensed(
        *report_key_segments(
            run_a_execution_id=run_a_execution_id,
            run_b_execution_id=run_b_execution_id,
            assessment_id=assessment_id,
        ),
        payload=payload,
    )


__all__ = [
    "DELETION_OBLIGATION",
    "MAX_REPORT_BYTES",
    "REPORT_SCHEMA_VERSION",
    "REPORT_SEGMENTS",
    "RETENTION_BASIS",
    "ReportDefect",
    "ReportError",
    "ReportEvidence",
    "build_report_document",
    "report_key_segments",
    "report_object_key",
    "serialize_report",
]
