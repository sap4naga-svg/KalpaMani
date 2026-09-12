"""The acquisition task entry: compose the accepted path, run it once, receipt.

**Order, before anything is built** (ADR-0036 §2.12 steps 4-7, preceded by three
compiled checks): the configuration must be this entry's and carry a usable secret
identifier and a non-empty compiled origin address set; the credential environment
must be a task's; the pinned provider origin must resolve inside the compiled set.
Each refuses with zero clients constructed. Only then are the injected factories
called -- SSM, STS, S3, Secrets Manager, transport -- and only then does the accepted
:func:`~kalpamani.data.production.sharadar.processing.run_production_acquisition`
run: bootstrap, barrier, durable reservation, one credential, the bounded run, one
locator last. Nothing about that path is reimplemented here; it is composed.

**Capabilities are narrowed at the seam.** The S3 client is wrapped put-only before
processing sees it; the provider is the accepted adapter over the injected transport,
one attempt, counting actual transport invocations; the spent-identity registry is
the injected one or, when none is configured, the accepted ``UnavailableSpentIdentities``
-- which refuses every input, honestly, until the owner decides the task-side source
(ADR-0043 proposes one; it is not accepted).

**Nothing here is a real client.** The factories are what the image entrypoint hands
in; the tests hand in fakes, and **mocked results are not AWS or provider verification**.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from kalpamani.data.ingest.sharadar.secrets import SecretsClient, is_usable_secret_identifier
from kalpamani.data.ingest.sharadar.transport import SharadarTransport
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
from kalpamani.data.production.sharadar.identities import (
    SpentIdentityRegistry,
    UnavailableSpentIdentities,
)
from kalpamani.data.production.sharadar.outcomes import OperationCounts, RunnerOutcome
from kalpamani.data.production.sharadar.parameters import SsmLikeClient, SsmParameterAdapter
from kalpamani.data.production.sharadar.processing import (
    AcquisitionStatus,
    ProcessingAdapters,
    run_production_acquisition,
)
from kalpamani.data.production.sharadar.provider import SharadarProductionProvider
from kalpamani.data.production.sharadar.runner import RunnerAdapters
from kalpamani.data.production.sharadar.task_clients import (
    PutOnlyS3Client,
    StsCallerIdentityAdapter,
    StsLikeClient,
    origin_address_refusal,
)
from kalpamani.data.production.sharadar.task_metadata import MetadataFetch, fetch_task_metadata

#: How a post-bootstrap acquisition status becomes a task outcome. ``REFUSED_BOOTSTRAP``
#: is deliberately absent: it is refined to the bootstrap's own refusal. A test asserts
#: that the two together cover every status.
ACQUISITION_OUTCOME: Final[dict[AcquisitionStatus, TaskOutcome]] = {
    AcquisitionStatus.COMPLETED: TaskOutcome.COMPLETED,
    AcquisitionStatus.REFUSED_RESERVATION: TaskOutcome.REFUSED_RESERVATION,
    AcquisitionStatus.REFUSED_CREDENTIAL: TaskOutcome.REFUSED_CREDENTIAL,
    AcquisitionStatus.HALTED: TaskOutcome.ACQUISITION_HALTED,
    AcquisitionStatus.LOCATOR_NOT_PUBLISHED: TaskOutcome.LOCATOR_NOT_PUBLISHED,
    AcquisitionStatus.LOCATOR_STATE_UNKNOWN: TaskOutcome.LOCATOR_STATE_UNKNOWN,
    AcquisitionStatus.LOCATOR_NAME_OCCUPIED: TaskOutcome.LOCATOR_NAME_OCCUPIED,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionFactories:
    """Everything the acquisition entry may touch, as zero-argument factories.

    Each factory is called at most once, after every compiled check has passed, and
    what it returns is wrapped before any processing module sees it. ``spent_identities``
    is the task-side preliminary source, ``None`` meaning *none is configured*.
    """

    environment_names: Callable[[], Iterable[str]]
    environment: Callable[[str], str | None]
    metadata_fetch: MetadataFetch
    ssm: Callable[[], SsmLikeClient]
    sts: Callable[[], StsLikeClient]
    s3: Callable[[], Any]
    secrets: Callable[[], SecretsClient]
    transport: Callable[[], SharadarTransport]
    resolve_origin: Callable[[str], Iterable[object]]
    spent_identities: SpentIdentityRegistry | None
    now: Callable[[], datetime]
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]
    cleanup: Callable[[], None] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class _Composed:
    bootstrap: RunnerAdapters
    processing: ProcessingAdapters


def _compose(configuration: EntryConfiguration, factories: AcquisitionFactories) -> _Composed:
    """Call each factory once and wrap what it returns. Raises on any factory failure."""
    assert configuration.secret_identifier is not None
    parameters = SsmParameterAdapter(ssm=factories.ssm())
    identity = StsCallerIdentityAdapter(sts=factories.sts())
    s3 = PutOnlyS3Client(factories.s3())
    secrets = factories.secrets()
    provider = SharadarProductionProvider(transport=factories.transport())
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
    processing = ProcessingAdapters(
        secrets=secrets,
        secret_id=configuration.secret_identifier,
        provider=provider,
        s3=s3,
        monotonic=factories.monotonic,
        sleeper=factories.sleep,
        clock=factories.now,
    )
    return _Composed(bootstrap=bootstrap, processing=processing)


def run_acquisition_entry(
    *, configuration: EntryConfiguration, factories: AcquisitionFactories
) -> TaskReceipt:
    """The acquisition entry, start to receipt. Never raises."""
    entry = TaskEntry.ACQUISITION
    if type(factories) is not AcquisitionFactories:
        return refusal_receipt(entry, TaskOutcome.REFUSED_CONFIGURATION)
    cleanup = factories.cleanup

    refused = pre_entry_refusal(
        entry=entry, configuration=configuration, environment_names=factories.environment_names
    )
    if refused is not None:
        return refusal_receipt(entry, refused, cleanup=cleanup)
    if not is_usable_secret_identifier(configuration.secret_identifier):
        return refusal_receipt(entry, TaskOutcome.REFUSED_CONFIGURATION, cleanup=cleanup)
    if not configuration.origin_addresses:
        return refusal_receipt(entry, TaskOutcome.REFUSED_CONFIGURATION, cleanup=cleanup)
    if (
        origin_address_refusal(
            compiled=configuration.origin_addresses, resolve=factories.resolve_origin
        )
        is not None
    ):
        return refusal_receipt(entry, TaskOutcome.REFUSED_ORIGIN, cleanup=cleanup)

    try:
        composed = _compose(configuration, factories)
    except Exception:
        return refusal_receipt(entry, TaskOutcome.REFUSED_DEPENDENCY, cleanup=cleanup)
    registry: SpentIdentityRegistry = (
        UnavailableSpentIdentities()
        if factories.spent_identities is None
        else factories.spent_identities
    )

    try:
        report = run_production_acquisition(
            compiled=configuration.compiled,
            bootstrap=composed.bootstrap,
            registry=registry,
            processing=composed.processing,
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
    if report.status is AcquisitionStatus.REFUSED_BOOTSTRAP:
        outcome = BOOTSTRAP_OUTCOME[runner]
    else:
        outcome = ACQUISITION_OUTCOME[report.status]
    return TaskReceipt(
        entry=entry,
        outcome=outcome,
        runner=runner,
        counts=report.counts,
        counts_observed=True,
        cleanup_failures=run_cleanup(cleanup),
    )


__all__ = ["ACQUISITION_OUTCOME", "AcquisitionFactories", "run_acquisition_entry"]
