"""The quality report: typed evidence that the checks ran, and what they found.

A dataset is publishable only if it can say **which checks ran, which did not,
and what they found**. That is a different claim from "nobody passed me an issue
list", and the difference is the whole point of this module.

The shape it replaces was fail-open: a reader constructed with no issues was a
clean reader, so a caller obtained a publishable result by omitting evidence
rather than by producing it. Absence of a finding and absence of a check look
identical from the outside, and only one of them means anything.

Three properties make the report load-bearing:

**It is required, not optional.** Publication takes one. There is no default and
no empty fallback.

**It has an identity.** ``report_hash`` covers the policy versions, every check
that ran, every check that did **not** run, and every finding. It is bound into
the dataset manifest, so a published dataset and its quality evidence cannot
drift apart -- swapping the report changes the dataset's identity.

**Checks not run are recorded, never quietly skipped.** A check that cannot run
is declared. A check that silently covered less than it claims is worse than no
check, because it converts an unknown into a false assurance.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType

from kalpamani.data.contracts.canonical import canonical_bytes, content_hash, sha256_hex
from kalpamani.data.contracts.errors import QualityGateError
from kalpamani.data.contracts.instants import normalize_instant
from kalpamani.data.contracts.vocabulary import QualitySeverity
from kalpamani.data.quality.checks import QualityFinding


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckNotRun:
    """A check that could not run, and why. Declared, never silently skipped."""

    check_name: str
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class FindingRecord:
    """One finding, with an identity a manifest can cite."""

    check_name: str
    severity: QualitySeverity
    dataset: str
    detail: str
    security_id: str | None = None
    session_date: date | None = None

    @property
    def finding_hash(self) -> str:
        """Content hash of the finding. Two runs finding the same thing agree."""
        return content_hash(
            {
                "check_name": self.check_name,
                "severity": self.severity.value,
                "dataset": self.dataset,
                "detail": self.detail,
                "security_id": self.security_id,
                "session_date": self.session_date,
            }
        )

    @classmethod
    def of(cls, finding: QualityFinding) -> FindingRecord:
        """Record a finding produced by the deterministic checks."""
        return cls(
            check_name=finding.check_name,
            severity=finding.severity,
            dataset=finding.dataset,
            detail=finding.detail,
            security_id=finding.security_id,
            session_date=finding.session_date,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class QualityReport:
    """What the checks did, for one build, before it was published.

    Produced **after resolution and before publication**: the rows it describes
    are the resolved rows, because checking raw rows would report on a set that
    is not the one being published.
    """

    #: The versioned plan this report is evidence against. Without it the report
    #: says what ran but nothing says what should have.
    plan_version: str
    policy_versions: Mapping[str, str]
    checks_run: tuple[str, ...]
    checks_not_run: tuple[CheckNotRun, ...]
    findings: tuple[FindingRecord, ...]
    datasets_covered: tuple[str, ...]
    partitions_covered: tuple[str, ...] = ()
    produced_at: datetime
    #: The token of whatever produced this report. Only the quality runner holds
    #: the one publication accepts, so a hand-built report stays constructible --
    #: adversarial tests need one -- and is still distinguishable from a run.
    #: Deliberately outside ``report_hash``: it is provenance, not content, and
    #: two identical check runs are one report however they were obtained.
    produced_by: object = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_versions", MappingProxyType(dict(sorted(self.policy_versions.items())))
        )
        object.__setattr__(self, "produced_at", normalize_instant(self.produced_at))
        if not self.checks_run:
            raise QualityGateError(
                "A quality report that ran no checks is not evidence of quality. If nothing "
                "could run, say so in checks_not_run and record why -- absence of a finding "
                "and absence of a check are different claims."
            )

    @property
    def blocking(self) -> tuple[FindingRecord, ...]:
        """Findings that refuse every dependent result."""
        return tuple(f for f in self.findings if f.severity is QualitySeverity.BLOCKING)

    @property
    def warnings(self) -> tuple[FindingRecord, ...]:
        """Findings a human should look at. Results stay valid but are labelled."""
        return tuple(f for f in self.findings if f.severity is QualitySeverity.WARNING)

    @property
    def passed(self) -> bool:
        """Whether the build may be published at all."""
        return not self.blocking

    @property
    def report_hash(self) -> str:
        """Identity of this report. Bound into the dataset manifest.

        Deliberately excludes ``produced_at``: when the checks ran is not part of
        what they found, and hashing it would make two identical check runs two
        different reports. That omission is why the manifest **also** binds
        :func:`report_file_hash` over the exact persisted bytes -- the logical
        hash proves the findings did not change, and only the file hash proves
        the stored file did not.
        """
        return content_hash(
            {
                "plan_version": self.plan_version,
                "policy_versions": dict(self.policy_versions),
                "checks_run": sorted(self.checks_run),
                "checks_not_run": sorted(
                    [item.check_name, item.reason] for item in self.checks_not_run
                ),
                "findings": sorted(finding.finding_hash for finding in self.findings),
                "datasets_covered": sorted(self.datasets_covered),
                "partitions_covered": sorted(self.partitions_covered),
            }
        )

    def require_publishable(self, *, dataset_version: str) -> None:
        """Refuse publication while a BLOCKING finding stands.

        Raises:
            QualityGateError: naming every blocking check. A BLOCKING issue open
                against a dataset makes every dependent result invalid -- the
                result is refused, not annotated, and the earliest place to
                refuse it is before the build exists to be cited.
        """
        blocking = self.blocking
        if not blocking:
            return
        names = sorted({finding.check_name for finding in blocking})
        raise QualityGateError(
            f"Refusing to publish {dataset_version}: {len(blocking)} open BLOCKING quality "
            f"finding(s) stand against it ({names}). A BLOCKING issue makes every dependent "
            "result invalid, and a published dataset is what later results cite."
        )

    def blocking_for(self, datasets: Sequence[str]) -> tuple[FindingRecord, ...]:
        """Blocking findings against any of ``datasets``. Empty means empty."""
        if not datasets:
            return self.blocking
        wanted = set(datasets)
        return tuple(finding for finding in self.blocking if finding.dataset in wanted)


def report_from_findings(
    findings: Sequence[QualityFinding],
    *,
    plan_version: str,
    policy_versions: Mapping[str, str],
    checks_run: Sequence[str],
    checks_not_run: Sequence[CheckNotRun] = (),
    datasets_covered: Sequence[str],
    partitions_covered: Sequence[str] = (),
    produced_at: datetime,
    produced_by: object = None,
) -> QualityReport:
    """Build a report from the deterministic checks' output.

    ``produced_by`` carries through whatever produced the report. The quality
    runner passes its own token; anything else leaves it unset, and publication
    can then tell a report that was run from one that was described.
    """
    return QualityReport(
        plan_version=plan_version,
        policy_versions=dict(policy_versions),
        checks_run=tuple(sorted(set(checks_run))),
        checks_not_run=tuple(checks_not_run),
        findings=tuple(FindingRecord.of(finding) for finding in findings),
        datasets_covered=tuple(sorted(set(datasets_covered))),
        partitions_covered=tuple(sorted(set(partitions_covered))),
        produced_at=produced_at,
        produced_by=produced_by,
    )


def encode_quality_report(report: QualityReport) -> dict[str, object]:
    """Encode a report for persistence beside the dataset it gates."""
    return {
        "plan_version": report.plan_version,
        "policy_versions": dict(report.policy_versions),
        "checks_run": list(report.checks_run),
        "checks_not_run": [
            {"check_name": item.check_name, "reason": item.reason} for item in report.checks_not_run
        ],
        "findings": [
            {
                "check_name": finding.check_name,
                "severity": finding.severity.value,
                "dataset": finding.dataset,
                "detail": finding.detail,
                "security_id": finding.security_id,
                "session_date": (
                    None if finding.session_date is None else finding.session_date.isoformat()
                ),
            }
            for finding in report.findings
        ],
        "datasets_covered": list(report.datasets_covered),
        "partitions_covered": list(report.partitions_covered),
        "produced_at": report.produced_at.isoformat(),
        "report_hash": report.report_hash,
    }


def decode_quality_report(body: Mapping[str, object]) -> QualityReport:
    """Decode a persisted report, refusing one whose hash does not reconcile."""
    findings = tuple(
        FindingRecord(
            check_name=str(row["check_name"]),
            severity=QualitySeverity(str(row["severity"])),
            dataset=str(row["dataset"]),
            detail=str(row["detail"]),
            security_id=None if row["security_id"] is None else str(row["security_id"]),
            session_date=(
                None
                if row["session_date"] is None
                else date.fromisoformat(str(row["session_date"]))
            ),
        )
        for row in list(body["findings"])  # type: ignore[call-overload]
    )
    report = QualityReport(
        plan_version=str(body["plan_version"]),
        policy_versions={
            str(key): str(value)
            for key, value in dict(body["policy_versions"]).items()  # type: ignore[call-overload]
        },
        checks_run=tuple(str(item) for item in list(body["checks_run"])),  # type: ignore[call-overload]
        checks_not_run=tuple(
            CheckNotRun(check_name=str(row["check_name"]), reason=str(row["reason"]))
            for row in list(body["checks_not_run"])  # type: ignore[call-overload]
        ),
        findings=findings,
        datasets_covered=tuple(str(item) for item in list(body["datasets_covered"])),  # type: ignore[call-overload]
        partitions_covered=tuple(str(item) for item in list(body["partitions_covered"])),  # type: ignore[call-overload]
        produced_at=datetime.fromisoformat(str(body["produced_at"])),
    )
    recorded = str(body["report_hash"])
    if report.report_hash != recorded:
        raise QualityGateError(
            f"The persisted quality report does not reconcile with its own hash (recorded "
            f"{recorded}, recomputed {report.report_hash}). A report that can be edited after "
            "the dataset was gated on it is not a gate."
        )
    return report


def report_file_hash(report: QualityReport) -> str:
    """Hash of the **exact bytes** a report is persisted as.

    ``report_hash`` deliberately omits ``produced_at``, which leaves a gap: two
    files differing only in that field share a logical hash, so an edited file
    could still satisfy the manifest. The manifest binds this hash as well, so
    every byte of the stored report is covered by something.
    """
    return sha256_hex(canonical_bytes(encode_quality_report(report)))


__all__ = [
    "CheckNotRun",
    "FindingRecord",
    "QualityReport",
    "decode_quality_report",
    "encode_quality_report",
    "report_file_hash",
    "report_from_findings",
]
