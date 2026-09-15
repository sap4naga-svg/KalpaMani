"""The two permission-probe entries: the accepted bootstrap, then one operation (ADR-0048).

**Not accepted, not in force.** ADR-0047 expands ADR-0036 s.3's R-4 and R-5 rows into subcells
under the human principal **and** under the task role, and names the task-role half as
blocked on "a task-side permission probe entry: one closed verification entry that issues
exactly one operation under the task role and prints a receipt". This is that entry.

A probe entry composes **the same**
:func:`~kalpamani.data.production.sharadar.runner.run_task_bootstrap` -- environment,
binding, input, self-check, identity proof, release barrier -- with the accepted pre-entry
checks before it, admitting the **probe input** contract in place of the
actor's production input (the same parameter, the same digest, a closed document naming one
catalogued subcell and its exact bound target). After the barrier it does exactly one of two
things and then stops with a non-zero exit:

- **issues the one operation** the input names, through the same engine the workstation tool
  uses (:func:`~permission_cells.issue_subcell`) over the one client the operation needs,
  built only now from the task's own credentials -- ``PROBE_MATCHED`` / ``PROBE_INVERTED`` /
  ``PROBE_UNDECIDED`` (exit 41 / 42 / 43); or
- **holds**, issuing nothing, for the bounded window the input names, so the launcher can make
  its ``ExecuteCommand`` refusal check against an attributable running task of its own actor
  -- ``PROBE_HELD`` (exit 44).

**What a probe entry cannot do, by construction.** Its factories hold no provider transport,
no spent-identity source and no build configuration; it never enters production processing,
never writes the run reservation, never retries, and never issues a second operation. The one
client it builds is the one service the subcell's operation names, with one transport attempt.
The receipt carries the classified answer and the counts as a closed block
(:class:`~permission_probe.PermissionProbeObservation`) -- never the value a ``GetSecretValue``
or ``GetObject`` returned, never a key, name or ARN.

**A permission answer is not a permission record.** The workstation completes the subcell's
record only from this receipt, verified against the launch record it holds; a probe that
refused before its operation carries no observation, and its subcell stays where the attempt
left it.

**Nothing here is a real client.** The factories are what the image entrypoint hands in; the
tests hand in fakes, and **mocked results are not AWS verification**.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from kalpamani.data.production.sharadar.entry import (
    BOOTSTRAP_OUTCOME,
    ENTRY_ACTOR,
    PROBE_ENTRIES,
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
from kalpamani.data.production.sharadar.permission_cells import (
    PRINCIPAL_ACTOR,
    Layer,
    Operation,
    PermissionClient,
    Subcell,
    issue_subcell,
    resolved_target_from,
    subcell,
)
from kalpamani.data.production.sharadar.permission_probe import (
    PROBE_HOLD_CEILING_SECONDS,
    PROBE_HOLD_POLL_SECONDS,
    PermissionProbeInput,
    PermissionProbeObservation,
    SubcellOutcome,
)
from kalpamani.data.production.sharadar.r3_verification import ObservedClass
from kalpamani.data.production.sharadar.runner import RunnerAdapters, run_task_bootstrap
from kalpamani.data.production.sharadar.task_clients import (
    StsCallerIdentityAdapter,
    StsLikeClient,
)
from kalpamani.data.production.sharadar.task_metadata import MetadataFetch, fetch_task_metadata


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionProbeFactories:
    """Everything a probe entry may touch. **No transport, no spent identities, no build.**

    ``operation_client`` builds the one permission client for the one operation the
    subcell names, from the task's own credential source, and is called at most once,
    after the barrier. A held probe never calls it.
    """

    environment_names: Callable[[], Iterable[str]]
    environment: Callable[[str], str | None]
    metadata_fetch: MetadataFetch
    ssm: Callable[[], SsmLikeClient]
    sts: Callable[[], StsLikeClient]
    operation_client: Callable[[Operation], PermissionClient]
    now: Callable[[], datetime]
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]
    cleanup: Callable[[], None] | None = None


def _bootstrap_adapters(factories: PermissionProbeFactories) -> RunnerAdapters:
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


_PROBE_OUTCOME: dict[SubcellOutcome, TaskOutcome] = {
    SubcellOutcome.MATCHED: TaskOutcome.PROBE_MATCHED,
    SubcellOutcome.INVERTED: TaskOutcome.PROBE_INVERTED,
    SubcellOutcome.UNDECIDED: TaskOutcome.PROBE_UNDECIDED,
}


def _probe_cell(entry: TaskEntry, admitted: PermissionProbeInput) -> Subcell | None:
    """The catalogued subcell this probe may exercise for ``entry``, or ``None``.

    The input contract already held the subcell to its actor; this is the entry's own
    check that the subcell is of **its** actor and of a probe layer, made again here
    because the entry is what issues the operation.
    """
    try:
        cell = subcell(admitted.subcell_id)
    except ValueError:
        return None
    if PRINCIPAL_ACTOR[cell.principal] is not ENTRY_ACTOR[entry]:
        return None
    if cell.layer is Layer.L3_TASK and not admitted.held:
        return cell
    if cell.layer is Layer.L3_HELD_TASK and admitted.held:
        return cell
    return None


def _hold(admitted: PermissionProbeInput, factories: PermissionProbeFactories) -> int:
    """Hold for the input's window on the monotonic clock; the seconds actually held."""
    ceiling = float(min(admitted.hold_seconds, PROBE_HOLD_CEILING_SECONDS))
    start = factories.monotonic()
    while True:
        elapsed = max(0.0, factories.monotonic() - start)
        if elapsed >= ceiling:
            return int(elapsed)
        factories.sleep(min(PROBE_HOLD_POLL_SECONDS, ceiling - elapsed))


def run_permission_probe_entry(
    *, entry: TaskEntry, configuration: EntryConfiguration, factories: PermissionProbeFactories
) -> TaskReceipt:
    """One probe entry, start to receipt. Never raises; never processes."""
    if entry not in PROBE_ENTRIES:
        raise ValueError("run_permission_probe_entry runs a probe entry only")
    if type(factories) is not PermissionProbeFactories:
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
    if configuration.origin_addresses or configuration.secret_identifier is not None:
        return refusal_receipt(
            entry, TaskOutcome.REFUSED_CONFIGURATION, cleanup=cleanup, configuration=configuration
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
            probe=True,
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

    # Released. The admitted input is the probe input; the subcell it names is this
    # entry's actor's, of a probe layer, or the input was not this probe's to act on.
    admitted = report.admitted_input
    cell = None if type(admitted) is not PermissionProbeInput else _probe_cell(entry, admitted)
    if cell is None or admitted is None:
        return TaskReceipt(
            entry=entry,
            outcome=TaskOutcome.REFUSED_INPUT,
            runner=runner,
            counts=report.counts,
            counts_observed=True,
            cleanup_failures=run_cleanup(cleanup),
            code_commit=configuration.compiled.code_commit,
            configuration_digest=configuration.compiled.configuration_digest,
            evidence=report.evidence,
        )
    assert type(admitted) is PermissionProbeInput

    def receipt(outcome: TaskOutcome, observation: PermissionProbeObservation) -> TaskReceipt:
        return TaskReceipt(
            entry=entry,
            outcome=outcome,
            runner=runner,
            counts=report.counts,
            counts_observed=True,
            cleanup_failures=run_cleanup(cleanup),
            code_commit=configuration.compiled.code_commit,
            configuration_digest=configuration.compiled.configuration_digest,
            evidence=report.evidence,
            permission=observation,
        )

    if admitted.held:
        # The attributable running task the launcher's check needs: hold, issue nothing.
        held = _hold(admitted, factories)
        return receipt(
            TaskOutcome.PROBE_HELD,
            PermissionProbeObservation(
                subcell_id=cell.subcell_id,
                statement_sha256=admitted.statement_sha256,
                attempt_sha256=admitted.attempt_sha256,
                stamp=admitted.stamp,
                observed=ObservedClass.NOT_EXERCISED,
                outcome=SubcellOutcome.UNDECIDED,
                created=False,
                possibly_created=False,
                operations=0,
                held_seconds=max(held, 1),
            ),
        )

    # The one operation, against the exact target the input carries -- the target the
    # statement bound -- over the one client the operation needs, built only now.
    try:
        target = resolved_target_from(admitted.target)
        if target.kind is not cell.target:
            raise ValueError("target kind")
        client = factories.operation_client(cell.operation)
    except Exception:
        return TaskReceipt(
            entry=entry,
            outcome=TaskOutcome.REFUSED_DEPENDENCY,
            runner=runner,
            counts=report.counts,
            counts_observed=True,
            cleanup_failures=run_cleanup(cleanup),
            code_commit=configuration.compiled.code_commit,
            configuration_digest=configuration.compiled.configuration_digest,
            evidence=report.evidence,
        )
    issue = issue_subcell(cell, target=target, client=client, stamp=admitted.stamp)
    observation = issue.observation(
        subcell_id=cell.subcell_id,
        statement_sha256=admitted.statement_sha256,
        attempt_sha256=admitted.attempt_sha256,
        stamp=admitted.stamp,
    )
    return receipt(_PROBE_OUTCOME[issue.outcome], observation)


__all__ = ["PermissionProbeFactories", "run_permission_probe_entry"]
