"""The build task entry: compose the accepted build path, run it once, receipt.

**What this module cannot hold** (ADR-0036 §2.3, acceptance guard A-8): no secrets
boundary, no credential type, no provider transport and no provider adapter are
imported here, and :class:`BuildFactories` has no field through which one could
arrive. The build's S3 client is wrapped read-write -- ``get_object`` and ``put_object``
and nothing else -- before processing sees it, and the exact reads it performs are the
accepted locator reader's, by name, digest and byte count.

**Order** (ADR-0036 §2.12 steps 4-7): the configuration must be this entry's and carry
a build configuration; the credential environment must be a task's; then the injected
factories are called -- SSM, STS, S3 -- and the accepted
:func:`~kalpamani.data.production.sharadar.build_processing.run_production_build`
runs: bootstrap, barrier, verified inputs, Silver, Gold, manifest last. Nothing about
that path is reimplemented here; it is composed. The spent-identity registry is not a
build concern and the accepted ``UnavailableSpentIdentities`` is passed, unconsulted.

**Mocked results are not AWS verification.**
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from kalpamani.data.production.sharadar.build_processing import (
    BuildAdapters,
    BuildStatus,
    run_production_build,
)
from kalpamani.data.production.sharadar.entry import (
    BOOTSTRAP_OUTCOME,
    EntryConfiguration,
    TaskEntry,
    TaskOutcome,
    TaskReceipt,
    pre_entry_refusal,
    refusal_receipt,
    run_cleanup,
)
from kalpamani.data.production.sharadar.identities import UnavailableSpentIdentities
from kalpamani.data.production.sharadar.outcomes import OperationCounts, RunnerOutcome
from kalpamani.data.production.sharadar.parameters import SsmLikeClient, SsmParameterAdapter
from kalpamani.data.production.sharadar.runner import RunnerAdapters
from kalpamani.data.production.sharadar.task_clients import (
    ReadWriteS3Client,
    StsCallerIdentityAdapter,
    StsLikeClient,
)
from kalpamani.data.production.sharadar.task_metadata import MetadataFetch, fetch_task_metadata

#: How a post-bootstrap build status becomes a task outcome. ``REFUSED_BOOTSTRAP`` is
#: deliberately absent: it is refined to the bootstrap's own refusal. A test asserts
#: that the two together cover every status.
BUILD_OUTCOME: Final[dict[BuildStatus, TaskOutcome]] = {
    BuildStatus.COMPLETED: TaskOutcome.COMPLETED,
    BuildStatus.REFUSED_INPUTS: TaskOutcome.REFUSED_INPUTS,
    BuildStatus.REFUSED_NORMALIZATION: TaskOutcome.REFUSED_NORMALIZATION,
    BuildStatus.REFUSED_TIMING: TaskOutcome.REFUSED_TIMING,
    BuildStatus.REFUSED_QUALITY: TaskOutcome.REFUSED_QUALITY,
    BuildStatus.REFUSED_VERIFICATION: TaskOutcome.REFUSED_VERIFICATION,
    BuildStatus.HALTED: TaskOutcome.BUILD_HALTED,
    BuildStatus.MANIFEST_NAME_OCCUPIED: TaskOutcome.MANIFEST_NAME_OCCUPIED,
    BuildStatus.MANIFEST_STATE_UNKNOWN: TaskOutcome.MANIFEST_STATE_UNKNOWN,
    BuildStatus.MANIFEST_REFUSED: TaskOutcome.MANIFEST_REFUSED,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildFactories:
    """Everything the build entry may touch. **No secret, no transport, no provider.**"""

    environment_names: Callable[[], Iterable[str]]
    environment: Callable[[str], str | None]
    metadata_fetch: MetadataFetch
    ssm: Callable[[], SsmLikeClient]
    sts: Callable[[], StsLikeClient]
    s3: Callable[[], Any]
    now: Callable[[], datetime]
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]
    cleanup: Callable[[], None] | None = None


def _compose(
    configuration: EntryConfiguration, factories: BuildFactories
) -> tuple[RunnerAdapters, BuildAdapters]:
    """Call each factory once and wrap what it returns. Raises on any factory failure."""
    assert configuration.build_configuration is not None
    parameters = SsmParameterAdapter(ssm=factories.ssm())
    identity = StsCallerIdentityAdapter(sts=factories.sts())
    s3 = ReadWriteS3Client(factories.s3())
    environment = factories.environment
    fetch = factories.metadata_fetch
    bootstrap = RunnerAdapters(
        environment_names=factories.environment_names,
        parameters=parameters,
        metadata=lambda: fetch_task_metadata(environment=environment, fetch=fetch),
        caller_identity=identity,
        now=factories.now,
        monotonic=factories.monotonic,
        sleep=factories.sleep,
    )
    processing = BuildAdapters(
        s3=s3,
        configuration=configuration.build_configuration,
        monotonic=factories.monotonic,
        clock=factories.now,
    )
    return bootstrap, processing


def run_build_entry(*, configuration: EntryConfiguration, factories: BuildFactories) -> TaskReceipt:
    """The build entry, start to receipt. Never raises."""
    entry = TaskEntry.BUILD
    if type(factories) is not BuildFactories:
        return refusal_receipt(entry, TaskOutcome.REFUSED_CONFIGURATION)
    cleanup = factories.cleanup

    refused = pre_entry_refusal(
        entry=entry, configuration=configuration, environment_names=factories.environment_names
    )
    if refused is not None:
        return refusal_receipt(entry, refused, cleanup=cleanup)
    if configuration.build_configuration is None:
        return refusal_receipt(entry, TaskOutcome.REFUSED_CONFIGURATION, cleanup=cleanup)

    try:
        bootstrap, processing = _compose(configuration, factories)
    except Exception:
        return refusal_receipt(entry, TaskOutcome.REFUSED_DEPENDENCY, cleanup=cleanup)

    try:
        report = run_production_build(
            compiled=configuration.compiled,
            bootstrap=bootstrap,
            registry=UnavailableSpentIdentities(),
            processing=processing,
        )
    except Exception:
        return TaskReceipt(
            entry=entry,
            outcome=TaskOutcome.UNCLASSIFIED,
            runner=None,
            counts=OperationCounts(),
            counts_observed=False,
            cleanup_failures=run_cleanup(cleanup),
        )

    runner: RunnerOutcome = report.bootstrap.outcome
    if report.status is BuildStatus.REFUSED_BOOTSTRAP:
        outcome = BOOTSTRAP_OUTCOME[runner]
    else:
        outcome = BUILD_OUTCOME[report.status]
    return TaskReceipt(
        entry=entry,
        outcome=outcome,
        runner=runner,
        counts=report.counts,
        counts_observed=True,
        cleanup_failures=run_cleanup(cleanup),
    )


__all__ = ["BUILD_OUTCOME", "BuildFactories", "run_build_entry"]
