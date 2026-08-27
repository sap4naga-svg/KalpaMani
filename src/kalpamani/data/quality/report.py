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

**It names the build it is about.** A report proves the checks ran; on its own it
does not say what they ran over. A clean build's report satisfies the plan,
carries a genuine runner seal, and would gate a *different* build entirely --
which is the same shape of failure as evidence a caller wrote, arrived at from the
other direction. ``subject_build_identity`` is the build's own identity hash, and
publication refuses a report that names another.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
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


class TableCoverage(StrEnum):
    """What a check actually did with one published table.

    ``datasets_covered`` collapsed three different situations into one bit. A
    table an implementation traversed and found full, a table it traversed and
    found empty, and a table nothing opened at all are three different statements
    about a published dataset, and only the first two are coverage.

    The middle one is the reason this is not a Boolean. A zero-row table is not
    automatically uncovered -- a check that walked it and found nothing did check
    it -- but it must not be silently reported as though rows had been examined,
    because "we looked and there was nothing" and "we looked at everything" read
    identically in a report that only lists names.
    """

    EXAMINED_WITH_ROWS = "EXAMINED_WITH_ROWS"
    EXAMINED_EMPTY = "EXAMINED_EMPTY"
    GOVERNED_NOT_RUN = "GOVERNED_NOT_RUN"


@dataclass(frozen=True, slots=True, kw_only=True)
class QualityContextDescriptor:
    """**What** a build was judged against, in full, not merely a hash of it.

    A hash proves that two contexts differ. It does not tell an auditor what
    either one was, and an auditor holding a published dataset cannot reconstruct
    a minimum price, an approved bound derivation or a survivorship window from
    sixty-four hex characters. Persisting only the hash made the standard
    tamper-evident and unreadable at the same time -- which answers "was this
    changed?" while leaving "what was it?" unanswerable.

    Every field is caller-supplied and therefore worth recording: the thresholds
    the checks measured with, the approvals that decided which bounds could
    resolve an axis, the cutoffs each snapshot was evaluated at, and the runner,
    plan and registry that produced the verdict.

    Deep-frozen and canonical, so :meth:`identity` is stable and the value cannot
    drift after a report has hashed it.
    """

    requested_profile: str
    resolved_profile: str
    global_profile_resolution: str
    resolution_policy_version: str
    #: ``(dataset, policy, reason)`` for every dataset, reasons included: two runs
    #: that bounded one dataset for different stated reasons resolved it
    #: differently and admitted different rows.
    resolution_map: tuple[tuple[str, str, str], ...]
    #: ``(dataset, public derivations, provider derivations, announcement
    #: derivations)``. An unapproved bound cannot resolve an axis, so this decides
    #: which rows exist at all.
    approvals: tuple[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...]
    #: ``(session, evaluation cutoff)``, normalised to UTC.
    evaluation_cutoffs: tuple[tuple[str, str], ...]
    universe_definition_version: str
    universe_definition_hash: str
    #: Every parameter of the rule, spelled out. The version is a name; these are
    #: the thresholds, and a name that outlives a threshold change is why the hash
    #: exists.
    universe_definition_parameters: tuple[tuple[str, str], ...]
    as_of: str
    market_thresholds_version: str
    market_thresholds: tuple[tuple[str, str], ...]
    survivorship_policy_version: str
    survivorship_policy: tuple[tuple[str, str], ...]
    adjusted_artifacts: tuple[tuple[str, str], ...]
    plan_version: str
    runner_version: str
    registry_identity: str
    build_identity: str

    def canonical(self) -> dict[str, object]:
        """The exact form :meth:`identity` hashes and persistence writes."""
        return {
            "requested_profile": self.requested_profile,
            "resolved_profile": self.resolved_profile,
            "global_profile_resolution": self.global_profile_resolution,
            "resolution_policy_version": self.resolution_policy_version,
            "resolution_map": [list(entry) for entry in self.resolution_map],
            "approvals": [
                [dataset, list(public), list(provider), list(announcement)]
                for dataset, public, provider, announcement in self.approvals
            ],
            "evaluation_cutoffs": [list(entry) for entry in self.evaluation_cutoffs],
            "universe_definition_version": self.universe_definition_version,
            "universe_definition_hash": self.universe_definition_hash,
            "universe_definition_parameters": [
                list(entry) for entry in self.universe_definition_parameters
            ],
            "as_of": self.as_of,
            "market_thresholds_version": self.market_thresholds_version,
            "market_thresholds": [list(entry) for entry in self.market_thresholds],
            "survivorship_policy_version": self.survivorship_policy_version,
            "survivorship_policy": [list(entry) for entry in self.survivorship_policy],
            "adjusted_artifacts": [list(entry) for entry in self.adjusted_artifacts],
            "plan_version": self.plan_version,
            "runner_version": self.runner_version,
            "registry_identity": self.registry_identity,
            "build_identity": self.build_identity,
        }

    def identity(self) -> str:
        """The ``quality_context_hash`` a report and a dataset manifest carry."""
        return content_hash(self.canonical())


def decode_quality_context(body: Mapping[str, object]) -> QualityContextDescriptor:
    """Decode a persisted descriptor. The caller checks it against its hash."""

    def pairs(key: str) -> tuple[tuple[str, str], ...]:
        return tuple(
            (str(entry[0]), str(entry[1]))
            for entry in list(body[key])  # type: ignore[call-overload]
        )

    return QualityContextDescriptor(
        requested_profile=str(body["requested_profile"]),
        resolved_profile=str(body["resolved_profile"]),
        global_profile_resolution=str(body["global_profile_resolution"]),
        resolution_policy_version=str(body["resolution_policy_version"]),
        resolution_map=tuple(
            (str(entry[0]), str(entry[1]), str(entry[2]))
            for entry in list(body["resolution_map"])  # type: ignore[call-overload]
        ),
        approvals=tuple(
            (
                str(entry[0]),
                tuple(str(item) for item in entry[1]),
                tuple(str(item) for item in entry[2]),
                tuple(str(item) for item in entry[3]),
            )
            for entry in list(body["approvals"])  # type: ignore[call-overload]
        ),
        evaluation_cutoffs=pairs("evaluation_cutoffs"),
        universe_definition_version=str(body["universe_definition_version"]),
        universe_definition_hash=str(body["universe_definition_hash"]),
        universe_definition_parameters=pairs("universe_definition_parameters"),
        as_of=str(body["as_of"]),
        market_thresholds_version=str(body["market_thresholds_version"]),
        market_thresholds=pairs("market_thresholds"),
        survivorship_policy_version=str(body["survivorship_policy_version"]),
        survivorship_policy=pairs("survivorship_policy"),
        adjusted_artifacts=pairs("adjusted_artifacts"),
        plan_version=str(body["plan_version"]),
        runner_version=str(body["runner_version"]),
        registry_identity=str(body["registry_identity"]),
        build_identity=str(body["build_identity"]),
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
    #: The build this report is evidence **about**. Without it the report says
    #: what ran but nothing says what it ran over, and a clean build's report
    #: would gate a defective one.
    subject_build_identity: str
    #: Canonical identity of everything the build was judged **against**: the
    #: profile resolution, the approved bounds, the evaluation cutoffs, the
    #: universe rule's actual parameters, the market and survivorship thresholds,
    #: the adjusted artifacts, the runner, the plan and the registry.
    #:
    #: A report said which checks ran and what they found, and nothing said what
    #: they measured with. Two runs over one build under one plan with different
    #: minimum prices and different approved bounds produced interchangeable
    #: evidence, and the standard a build passed was unrecoverable from the
    #: evidence that it passed.
    quality_context_hash: str
    #: The standard itself, readable. ``quality_context_hash`` is its identity, and
    #: an identity alone cannot be audited: it says a threshold did not change
    #: without ever saying what the threshold was.
    quality_context: QualityContextDescriptor
    #: The runner that produced this report.
    runner_version: str
    #: The check implementations actually invoked, and the governed reason each
    #: uninvoked one did not run. ``checks_run`` is the plan's vocabulary; this is
    #: the execution beneath it, and a check id can be absent because no
    #: implementation applied rather than because nothing exists.
    implementations_invoked: tuple[str, ...] = ()
    implementations_not_run: tuple[tuple[str, str], ...] = ()
    #: ``(entity, TableCoverage)`` for every published table, plus the governed
    #: reason where nothing ran. ``datasets_covered`` is a list of names and says
    #: nothing about whether a named table had rows in it.
    table_coverage: tuple[tuple[str, str, str], ...] = ()
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
        examined = {
            entity
            for entity, state, _ in self.table_coverage
            if state != TableCoverage.GOVERNED_NOT_RUN.value
        }
        # Compared over the entities the per-table evidence speaks about. The
        # coverage list also names ``run``, which is the run itself rather than a
        # table, and a symmetric difference over that would fault every report.
        described = {entity for entity, _, _ in self.table_coverage}
        listed = set(self.datasets_covered) & described
        if self.table_coverage and examined != listed:
            missing = sorted(listed ^ examined)
            raise QualityGateError(
                f"The report's coverage list and its per-table evidence disagree about "
                f"{missing}. One of them is a summary of the other, so a disagreement means "
                "the summary is not describing this run."
            )
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
                "subject_build_identity": self.subject_build_identity,
                # The whole descriptor, not only its identity. Hashing the hash
                # would bind the standard only as strongly as a value a caller
                # could have written; hashing the canonical form binds the thing.
                "quality_context": self.quality_context.canonical(),
                "quality_context_hash": self.quality_context_hash,
                "runner_version": self.runner_version,
                "implementations_invoked": sorted(self.implementations_invoked),
                "implementations_not_run": sorted(
                    list(entry) for entry in self.implementations_not_run
                ),
                "table_coverage": sorted(list(entry) for entry in self.table_coverage),
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
    subject_build_identity: str,
    quality_context: QualityContextDescriptor,
    runner_version: str,
    implementations_invoked: Sequence[str] = (),
    implementations_not_run: Sequence[tuple[str, str]] = (),
    table_coverage: Sequence[tuple[str, str, str]] = (),
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
        subject_build_identity=subject_build_identity,
        quality_context=quality_context,
        quality_context_hash=quality_context.identity(),
        runner_version=runner_version,
        implementations_invoked=tuple(implementations_invoked),
        implementations_not_run=tuple(implementations_not_run),
        table_coverage=tuple(table_coverage),
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
        "subject_build_identity": report.subject_build_identity,
        "quality_context": report.quality_context.canonical(),
        "quality_context_hash": report.quality_context_hash,
        "runner_version": report.runner_version,
        "implementations_invoked": list(report.implementations_invoked),
        "implementations_not_run": [list(entry) for entry in report.implementations_not_run],
        "table_coverage": [list(entry) for entry in report.table_coverage],
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
    descriptor = decode_quality_context(dict(body["quality_context"]))  # type: ignore[call-overload]
    recorded_context = str(body["quality_context_hash"])
    if descriptor.identity() != recorded_context:
        raise QualityGateError(
            f"The persisted quality context does not reconcile with its own hash (recorded "
            f"{recorded_context}, recomputed {descriptor.identity()}). A standard that can be "
            "edited after the build was judged against it is not a standard."
        )
    report = QualityReport(
        plan_version=str(body["plan_version"]),
        subject_build_identity=str(body["subject_build_identity"]),
        quality_context=descriptor,
        quality_context_hash=str(body["quality_context_hash"]),
        runner_version=str(body["runner_version"]),
        implementations_invoked=tuple(
            str(item)
            for item in list(body["implementations_invoked"])  # type: ignore[call-overload]
        ),
        implementations_not_run=tuple(
            (str(entry[0]), str(entry[1]))
            for entry in list(body["implementations_not_run"])  # type: ignore[call-overload]
        ),
        table_coverage=tuple(
            (str(entry[0]), str(entry[1]), str(entry[2]))
            for entry in list(body["table_coverage"])  # type: ignore[call-overload]
        ),
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
    "QualityContextDescriptor",
    "QualityReport",
    "TableCoverage",
    "decode_quality_context",
    "decode_quality_report",
    "encode_quality_report",
    "report_file_hash",
    "report_from_findings",
]
