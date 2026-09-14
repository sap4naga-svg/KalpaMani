"""The two verification entries: the accepted bootstrap, then nothing (proposed ADR-0045).

**Not accepted, not in force.** ADR-0036 R-1/R-2 ask for a task that "reaches step 6a of §2.12
and exits with the closed verification-only code". The production entries cannot do that: a
released bootstrap continues directly into processing (ADR-0043). A verification entry composes
**the same** :func:`~kalpamani.data.production.sharadar.runner.run_task_bootstrap` -- environment,
binding, input, self-check, identity proof, release barrier -- with the accepted pre-entry checks
before it, and then **stops**: ``VERIFIED_BOOTSTRAP``, a non-zero exit, one receipt.

**What a verification entry cannot do, by construction.** Its factories have no Secrets Manager
client, no provider transport and no S3 client -- there is no field one could arrive through --
so a verification task performs zero ``GetSecretValue``, zero provider API requests and zero
data-plane S3 operations; it never enters ``run_production_acquisition`` or
``run_production_build``; and it never writes the durable run reservation, so the identity its
input names is **not spent** by it. Nothing here reimplements or relaxes a bootstrap check.

**The build verification entry probes, and does not conclude.** After the barrier it makes the
bounded provider-origin probe of :mod:`~kalpamani.data.production.sharadar.probe` -- one TCP
connection attempt, no bytes -- and records the *observation* in its receipt. The isolation verdict
is the launch tool's and the owner's, under the proposed ADR's corroboration rule; a
``VERIFIED_BOOTSTRAP`` outcome never implies an R-2 pass.

**Nothing here is a real client.** The factories are what the image entrypoint hands in; the tests
hand in fakes, and **mocked results are not AWS or provider verification**.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from kalpamani.data.production.sharadar.entry import (
    BOOTSTRAP_OUTCOME,
    ENTRY_ACTOR,
    VERIFICATION_ENTRIES,
    EntryConfiguration,
    TaskEntry,
    TaskOutcome,
    TaskReceipt,
    pre_entry_refusal,
    refusal_receipt,
    run_cleanup,
)
from kalpamani.data.production.sharadar.outcomes import OperationCounts, RunnerOutcome
from kalpamani.data.production.sharadar.parameters import SsmLikeClient, SsmParameterAdapter
from kalpamani.data.production.sharadar.probe import ProbeAdapter, run_origin_probe
from kalpamani.data.production.sharadar.runner import RunnerAdapters, run_task_bootstrap
from kalpamani.data.production.sharadar.task_clients import (
    StsCallerIdentityAdapter,
    StsLikeClient,
    origin_address_refusal,
)
from kalpamani.data.production.sharadar.task_metadata import MetadataFetch, fetch_task_metadata


@dataclass(frozen=True, slots=True, kw_only=True)
class VerificationFactories:
    """Everything a verification entry may touch. **No secret, no transport, no S3.**

    ``probe`` is the build verification entry's connection adapter and must be ``None``
    for the acquisition verification entry, which makes no connection of any kind.
    """

    environment_names: Callable[[], Iterable[str]]
    environment: Callable[[str], str | None]
    metadata_fetch: MetadataFetch
    ssm: Callable[[], SsmLikeClient]
    sts: Callable[[], StsLikeClient]
    resolve_origin: Callable[[str], Iterable[object]]
    probe: ProbeAdapter | None
    now: Callable[[], datetime]
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]
    cleanup: Callable[[], None] | None = None


def _bootstrap_adapters(factories: VerificationFactories) -> RunnerAdapters:
    """Call the two client factories once and wrap them. Raises on any factory failure."""
    parameters = SsmParameterAdapter(ssm=factories.ssm())
    identity = StsCallerIdentityAdapter(sts=factories.sts())
    environment = factories.environment
    fetch = factories.metadata_fetch
    return RunnerAdapters(
        environment_names=factories.environment_names,
        parameters=parameters,
        metadata=lambda: fetch_task_metadata(environment=environment, fetch=fetch),
        caller_identity=identity,
        now=factories.now,
        monotonic=factories.monotonic,
        sleep=factories.sleep,
    )


def run_verification_entry(
    *, entry: TaskEntry, configuration: EntryConfiguration, factories: VerificationFactories
) -> TaskReceipt:
    """One verification entry, start to receipt. Never raises; never processes."""
    if entry not in VERIFICATION_ENTRIES:
        raise ValueError("run_verification_entry runs a verification entry only")
    if type(factories) is not VerificationFactories:
        return refusal_receipt(entry, TaskOutcome.REFUSED_CONFIGURATION)
    cleanup = factories.cleanup

    refused = pre_entry_refusal(
        entry=entry,
        configuration=configuration,
        environment_names=factories.environment_names,
        environment=factories.environment,
    )
    if refused is not None:
        return refusal_receipt(entry, refused, cleanup=cleanup, configuration=configuration)
    # Both verification entries carry the compiled origin address set: the acquisition
    # one for the accepted origin check, the build one as the probe destination set.
    if not configuration.origin_addresses:
        return refusal_receipt(
            entry, TaskOutcome.REFUSED_CONFIGURATION, cleanup=cleanup, configuration=configuration
        )
    if (entry is TaskEntry.BUILD_VERIFY) != (factories.probe is not None):
        return refusal_receipt(
            entry, TaskOutcome.REFUSED_CONFIGURATION, cleanup=cleanup, configuration=configuration
        )
    if entry is TaskEntry.ACQUISITION_VERIFY and (
        origin_address_refusal(
            compiled=configuration.origin_addresses, resolve=factories.resolve_origin
        )
        is not None
    ):
        return refusal_receipt(
            entry, TaskOutcome.REFUSED_ORIGIN, cleanup=cleanup, configuration=configuration
        )

    try:
        adapters = _bootstrap_adapters(factories)
    except Exception:
        return refusal_receipt(
            entry, TaskOutcome.REFUSED_DEPENDENCY, cleanup=cleanup, configuration=configuration
        )

    try:
        report = run_task_bootstrap(
            actor=ENTRY_ACTOR[entry],
            compiled=configuration.compiled,
            adapters=adapters,
            registry=None,
        )
    except Exception:
        return TaskReceipt(
            entry=entry,
            outcome=TaskOutcome.UNCLASSIFIED,
            runner=None,
            counts=OperationCounts(),
            counts_observed=False,
            cleanup_failures=run_cleanup(cleanup),
            code_commit=configuration.compiled.code_commit,
            configuration_digest=configuration.compiled.configuration_digest,
        )

    runner: RunnerOutcome = report.outcome
    if runner is not RunnerOutcome.RELEASED:
        return TaskReceipt(
            entry=entry,
            outcome=BOOTSTRAP_OUTCOME[runner],
            runner=runner,
            counts=report.counts,
            counts_observed=True,
            cleanup_failures=run_cleanup(cleanup),
            code_commit=configuration.compiled.code_commit,
            configuration_digest=configuration.compiled.configuration_digest,
        )

    # Released. A production entry would now reserve, retrieve and acquire, or read
    # and build. A verification entry does neither: it observes (build) and stops.
    probe = None
    if entry is TaskEntry.BUILD_VERIFY:
        assert factories.probe is not None
        probe = run_origin_probe(
            compiled=configuration.origin_addresses,
            resolve=factories.resolve_origin,
            adapter=factories.probe,
        )
    return TaskReceipt(
        entry=entry,
        outcome=TaskOutcome.VERIFIED_BOOTSTRAP,
        runner=runner,
        counts=report.counts,
        counts_observed=True,
        cleanup_failures=run_cleanup(cleanup),
        code_commit=configuration.compiled.code_commit,
        configuration_digest=configuration.compiled.configuration_digest,
        evidence=report.evidence,
        probe=probe,
    )


__all__ = ["VerificationFactories", "run_verification_entry"]
