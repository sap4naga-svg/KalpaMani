"""Research-build processing: after the barrier, verified inputs, Silver, Gold, manifest last.

**Everything before the first data-plane operation is the accepted bootstrap.**
:func:`run_production_build` calls
:func:`~kalpamani.data.production.sharadar.runner.run_task_bootstrap` for the build actor
and proceeds only on ``RELEASED``: binding, input, self-check, identity proof and the
placement release barrier have all passed with zero S3, secret and provider operations.
The build actor **has no secret and no provider**: this module takes no secrets client,
no credential and no provider adapter, and offers no parameter through which one could
arrive.

**The order is the contract.** Verified inputs (locators by exact name, then only what
they name, digest and byte count verified before parsing) -> Silver normalization
through the accepted parser -> availability bounds under the accepted derivations ->
per-session membership at the decision cutoff -> quality checks and Gold assembly ->
publication of Silver, then Gold, then the manifest **last** and only after every write
is confirmed. Each stage refuses closed; a refusal reports what stopped and how many
operations were spent, and publishes no manifest.

**Every dependency is injected**, and every count reported is what the injected fakes
were asked: a get-only client for reads, a put-only client for writes, an injected
monotonic clock and wall clock, a pinned configuration. **Mocked results are not AWS
verification.**

**No strategy signal, no order, no backtest.** The Gold layer is adjusted bars,
membership and corporate-action facts, with their provenance; nothing here ranks,
sizes or trades.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.production.sharadar.availability import resolve
from kalpamani.data.production.sharadar.build_inputs import (
    BuildInputDefect,
    BuildInputError,
    verify_build_inputs,
)
from kalpamani.data.production.sharadar.build_manifest import (
    BuildConfiguration,
    ManifestDisposition,
    PublicationHalt,
    PublicationResult,
    publish_build,
)
from kalpamani.data.production.sharadar.gold import GoldDefect, GoldError, build_gold
from kalpamani.data.production.sharadar.identities import SpentIdentityRegistry
from kalpamani.data.production.sharadar.inputs import BuildInput
from kalpamani.data.production.sharadar.locator import PayloadDisposition, ProductionLocatorReader
from kalpamani.data.production.sharadar.metadata import CompiledTask
from kalpamani.data.production.sharadar.outcomes import OperationCounts, RunnerOutcome
from kalpamani.data.production.sharadar.runner import (
    RunnerAdapters,
    RunnerReport,
    run_task_bootstrap,
)
from kalpamani.data.production.sharadar.silver import SilverError, normalize
from kalpamani.data.production.sharadar.universe import build_universe
from kalpamani.data.production.sharadar.vocabulary import ProductionActor
from kalpamani.data.qualify.sharadar.operations import AcquisitionDeadline, CountingS3Client
from kalpamani.data.qualify.sharadar.publication import LicensedWriteOnlyPublisher

#: One actual elapsed-time deadline over the whole build, on the injected monotonic
#: clock: reads, parsing, computation and publication. A safety bound on elapsed time.
BUILD_DEADLINE_SECONDS: Final = 3600.0


class BuildStatus(StrEnum):
    """The one verdict of a research build. Closed, never a data verdict.

    ``COMPLETED`` requires every artifact write confirmed, no unknown state and a
    ``PUBLISHED`` manifest. Everything else names what stopped short.
    """

    COMPLETED = "COMPLETED"
    REFUSED_BOOTSTRAP = "REFUSED_BOOTSTRAP"
    REFUSED_INPUTS = "REFUSED_INPUTS"
    REFUSED_NORMALIZATION = "REFUSED_NORMALIZATION"
    REFUSED_TIMING = "REFUSED_TIMING"
    REFUSED_QUALITY = "REFUSED_QUALITY"
    REFUSED_VERIFICATION = "REFUSED_VERIFICATION"
    HALTED = "HALTED"
    MANIFEST_NAME_OCCUPIED = "MANIFEST_NAME_OCCUPIED"
    MANIFEST_STATE_UNKNOWN = "MANIFEST_STATE_UNKNOWN"
    MANIFEST_REFUSED = "MANIFEST_REFUSED"


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildAdapters:
    """Everything build processing touches after the barrier, injected."""

    s3: Any
    configuration: BuildConfiguration
    monotonic: Callable[[], float]
    clock: Callable[[], datetime]


class _AdmittingGetClient:
    """Admit every read against the build deadline, then forward it. Nothing else."""

    __slots__ = ("_client", "_deadline")

    def __init__(self, client: Any, *, deadline: AcquisitionDeadline) -> None:
        if not callable(getattr(client, "get_object", None)):
            raise TypeError("a read client must provide a callable get_object")
        self._client = client
        self._deadline = deadline

    def get_object(self, **kwargs: Any) -> Any:
        self._deadline.admit_s3_operation()
        return self._client.get_object(**kwargs)


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildReport:
    """The sanitized result of one research build. Counts observed, never planned."""

    status: BuildStatus
    bootstrap: RunnerReport
    defect: str | None
    objects_read: int
    artifacts_written: int
    artifacts_already_present: int
    publication_state_unknown: bool
    manifest: ManifestDisposition
    publication: PublicationResult | None
    counts: OperationCounts
    empty_reason: str | None

    def __post_init__(self) -> None:
        """A report must describe one possible build."""
        if type(self.status) is not BuildStatus:
            raise TypeError("status must be an exact BuildStatus member")
        completed = self.status is BuildStatus.COMPLETED
        if completed and (
            self.defect is not None
            or self.publication_state_unknown
            or self.manifest is not ManifestDisposition.PUBLISHED
        ):
            raise ValueError("COMPLETED requires confirmed writes, a known state and a manifest")
        if self.manifest is ManifestDisposition.PUBLISHED and not completed:
            raise ValueError("a published manifest is a completed build")
        if (
            self.manifest is ManifestDisposition.STATE_UNKNOWN
            and not self.publication_state_unknown
        ):
            raise ValueError("an uncertain manifest write is uncertain publication state")

    def __repr__(self) -> str:
        """Status and counts only."""
        return (
            f"BuildReport(status={self.status.value!r}, read={self.objects_read}, "
            f"written={self.artifacts_written}, manifest={self.manifest.value!r})"
        )


def run_production_build(
    *,
    compiled: CompiledTask,
    bootstrap: RunnerAdapters,
    registry: SpentIdentityRegistry,
    processing: BuildAdapters,
) -> BuildReport:
    """Bootstrap, barrier, then one bounded build and one manifest last.

    Returns a report on every path once the bootstrap has passed; a refused build's
    accounting is the point.
    """
    if type(processing) is not BuildAdapters:
        raise TypeError("processing must be an exact BuildAdapters")
    report = run_task_bootstrap(
        actor=ProductionActor.BUILD, compiled=compiled, adapters=bootstrap, registry=registry
    )
    if report.outcome is not RunnerOutcome.RELEASED:
        return BuildReport(
            status=BuildStatus.REFUSED_BOOTSTRAP,
            bootstrap=report,
            defect=None,
            objects_read=0,
            artifacts_written=0,
            artifacts_already_present=0,
            publication_state_unknown=False,
            manifest=ManifestDisposition.NOT_ATTEMPTED,
            publication=None,
            counts=report.counts,
            empty_reason=None,
        )
    assert report.binding is not None
    assert type(report.admitted_input) is BuildInput
    binding, admitted = report.binding, report.admitted_input
    configuration = processing.configuration

    deadline = AcquisitionDeadline(
        monotonic=processing.monotonic, deadline_seconds=BUILD_DEADLINE_SECONDS
    )
    reader = ProductionLocatorReader(
        client=_AdmittingGetClient(processing.s3, deadline=deadline),
        licensed_bucket=binding.licensed_bucket_name,
    )
    counting_s3 = CountingS3Client(processing.s3, deadline=deadline)
    publisher = LicensedWriteOnlyPublisher(
        client=counting_s3, licensed_bucket=binding.licensed_bucket_name
    )
    deadline.arm()

    def counts() -> OperationCounts:
        base = report.counts
        return OperationCounts(
            parameter_reads=base.parameter_reads,
            parameter_creates=base.parameter_creates,
            parameter_deletes=base.parameter_deletes,
            run_task=base.run_task,
            describe_tasks=base.describe_tasks,
            describe_network_interfaces=base.describe_network_interfaces,
            stop_task=base.stop_task,
            identity_calls=base.identity_calls,
            s3_operations=reader.get_object_count + counting_s3.put_object_count,
            secret_retrievals=0,
            provider_requests=0,
        )

    def refused(status: BuildStatus, defect: str) -> BuildReport:
        return BuildReport(
            status=status,
            bootstrap=report,
            defect=defect,
            objects_read=reader.get_object_count,
            artifacts_written=0,
            artifacts_already_present=0,
            publication_state_unknown=False,
            manifest=ManifestDisposition.NOT_ATTEMPTED,
            publication=None,
            counts=counts(),
            empty_reason=None,
        )

    # Stage 7a: verified inputs -- locators by name, exact reads, provenance cross-checks.
    try:
        inputs = verify_build_inputs(admitted, reader=reader)
    except BuildInputError as error:
        input_defect = error.defect
        if deadline.exhausted:
            input_defect = BuildInputDefect.DEADLINE_EXHAUSTED
        return refused(BuildStatus.REFUSED_INPUTS, input_defect.value)

    # Stage 7b: Silver, availability, membership, Gold. Pure computation, no I/O.
    try:
        silver = normalize(inputs, schemas=configuration.schemas)
    except SilverError as error:
        return refused(BuildStatus.REFUSED_NORMALIZATION, error.defect.value)
    resolved = resolve(silver, evidence=configuration.evidence, calendar=configuration.calendar)
    universe = build_universe(
        resolved,
        rule=configuration.rule,
        calendar=configuration.calendar,
        sessions=configuration.decision_sessions,
        as_of=configuration.as_of,
    )
    identity_blocking = sum(
        silver.by_dataset(dataset).unmapped_symbols + silver.by_dataset(dataset).ambiguous_symbols
        for dataset in ("stocks", "actions")
    )
    try:
        gold = build_gold(
            resolved,
            universe=universe,
            calendar=configuration.calendar,
            as_of=configuration.as_of,
            identity_blocking=identity_blocking,
            jump_ratio=configuration.jump_ratio,
            tolerance=configuration.reconciliation_tolerance,
        )
    except GoldError as error:
        status = {
            GoldDefect.REFUSED_TIMING: BuildStatus.REFUSED_TIMING,
            GoldDefect.REFUSED_QUALITY: BuildStatus.REFUSED_QUALITY,
            GoldDefect.REFUSED_VERIFICATION: BuildStatus.REFUSED_VERIFICATION,
        }[error.defect]
        return refused(status, error.defect.value)

    # Stage 7c: publication -- Silver, Gold, then the manifest last.
    publication = publish_build(
        publisher=publisher,
        inputs=inputs,
        silver=silver,
        resolved=resolved,
        universe=universe,
        gold=gold,
        configuration=configuration,
        completed_at=processing.clock(),
        deadline_exhausted=lambda: deadline.exhausted,
    )
    written = sum(
        1 for item in publication.artifacts if item.disposition is PayloadDisposition.WRITTEN
    )
    present = sum(
        1
        for item in publication.artifacts
        if item.disposition is PayloadDisposition.ALREADY_PRESENT
    )
    defect: str | None = None
    if publication.halt is not None:
        status = BuildStatus.HALTED
        defect = publication.halt.value
    elif publication.manifest is ManifestDisposition.PUBLISHED:
        status = BuildStatus.COMPLETED
    elif publication.manifest is ManifestDisposition.NAME_OCCUPIED:
        status = BuildStatus.MANIFEST_NAME_OCCUPIED
    elif publication.manifest is ManifestDisposition.STATE_UNKNOWN:
        status = BuildStatus.MANIFEST_STATE_UNKNOWN
    else:
        status = BuildStatus.MANIFEST_REFUSED
        defect = PublicationHalt.PUBLICATION_REFUSED.value
    return BuildReport(
        status=status,
        bootstrap=report,
        defect=defect,
        objects_read=reader.get_object_count,
        artifacts_written=written,
        artifacts_already_present=present,
        publication_state_unknown=publication.publication_state_unknown,
        manifest=publication.manifest,
        publication=publication,
        counts=counts(),
        empty_reason=gold.empty_reason,
    )


__all__ = [
    "BUILD_DEADLINE_SECONDS",
    "BuildAdapters",
    "BuildReport",
    "BuildStatus",
    "run_production_build",
]
