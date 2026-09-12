"""The launch tool's sequence: input, one launch, placement, release, observe, cleanup.

ADR-0036 §2.12, steps 0, 1, 1a and 10, on the owner's workstation, under two
profiles: the actor's **human** permission set materializes the input and deletes
it afterwards; the actor's **launcher** permission set starts the task, verifies
placement, writes the release, observes the task and deletes the release. Each
profile's operations are bracketed by its own identity proof, and the proof is
injected -- this module makes no identity call of its own.

What the sequence guarantees, each with a test behind it:

- **create-only input materialization** -- an existing input parameter refuses the
  whole run before any launch (the stale-input guard);
- **exactly one launch**, with the compiled request and no override;
- **placement verification** from documented fields -- ``DescribeTasks`` for the
  attachment's subnet and the revision, ``DescribeNetworkInterfaces`` for the
  security groups and the public-IP association -- and ``StopTask`` on **this
  task only** when any of them mismatches, with **no release written**;
- **create-only release** after verification, bound to the exact task,
  revision, identity and input digest;
- **bounded observation** until the task's terminal state;
- **prescribed cleanup** -- one ``DeleteParameter`` on the release under the
  launcher profile, one on the input under the human profile -- whose failures are
  reported **beside** the primary outcome, never in place of it.

**Every count reported is the count of requests the adapters actually issued**,
read from the adapters' own counters at the end, never planned and never
incremented ahead of a request: a mismatch that returns before the EC2 lookup
reports zero ``DescribeNetworkInterfaces`` calls, and a request an adapter
refuses locally is not counted as issued.

**An identity proof that raises is a closed outcome, not an escaping
exception.** Before the input exists it is ``REFUSED_IDENTITY_UNAVAILABLE``;
during cleanup it is a cleanup failure for that stage alone, and the other
stage's own proof is still attempted. Cleanup runs in a ``finally`` block, so
nothing raised after the input was created can bypass it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from kalpamani.data.production.sharadar.compute import (
    CompiledLaunch,
    ComputeError,
    Ec2InterfaceAdapter,
    EcsTaskAdapter,
    TaskDescription,
)
from kalpamani.data.production.sharadar.inputs import MAX_INPUT_VALIDITY, input_digest
from kalpamani.data.production.sharadar.keys import RUN_ID_RE
from kalpamani.data.production.sharadar.outcomes import (
    CLEANUP_IDENTITY_REFUSED,
    CLEANUP_IDENTITY_UNAVAILABLE,
    CleanupFailure,
    CleanupStage,
    LaunchOutcome,
    OperationCounts,
    PlacementIncident,
)
from kalpamani.data.production.sharadar.parameters import (
    ParameterError,
    ParameterFailure,
    SsmParameterAdapter,
)
from kalpamani.data.production.sharadar.release import (
    ReleaseError,
    build_release_document,
)
from kalpamani.data.production.sharadar.vocabulary import (
    MAX_ADVANCED_PARAMETER_BYTES,
    IdentityPath,
    constants_for,
)

#: Compiled polling bounds. Placement is checked as soon as the attachment reports
#: ``ATTACHED``; observation waits for the terminal state. Lowerable, never raisable.
PLACEMENT_POLL_INTERVAL_SECONDS: Final = 5.0
PLACEMENT_CEILING_SECONDS: Final = 120.0
OBSERVE_POLL_INTERVAL_SECONDS: Final = 15.0
OBSERVE_CEILING_SECONDS: Final = 3600.0

#: The lifecycle ``Expiration`` each parameter rides with: input 24 h, release 1 h.
INPUT_EXPIRATION: Final = MAX_INPUT_VALIDITY
RELEASE_EXPIRATION: Final = timedelta(hours=1)

#: The closed ``StopTask`` reason tokens. No identifier is ever part of one.
STOP_REASON_MISPLACED: Final = "kalpamani-placement-mismatch"
STOP_REASON_RELEASE_EXISTS: Final = "kalpamani-stale-release"


@dataclass(frozen=True, slots=True, kw_only=True)
class LaunchAuthorization:
    """One owner-authorized run: the input bytes the human profile materializes.

    The identity is the run or build identity the input names; it is supplied
    beside the bytes because the release must name it and the tool does not
    parse the input it carries -- the task does, under its own contract.
    """

    identity: str
    input_bytes: bytes

    def __post_init__(self) -> None:
        """A well-formed identity and an input within the advanced-tier ceiling."""
        if type(self.identity) is not str or not RUN_ID_RE.match(self.identity):
            raise ValueError("the identity does not match the run-identity grammar")
        if type(self.input_bytes) is not bytes or not self.input_bytes:
            raise ValueError("the input must be non-empty bytes")
        if len(self.input_bytes) > MAX_ADVANCED_PARAMETER_BYTES:
            raise ValueError("the input exceeds the advanced-tier ceiling")

    def __repr__(self) -> str:
        """The byte count only."""
        return f"LaunchAuthorization(bytes={len(self.input_bytes)})"


@dataclass(frozen=True, slots=True, kw_only=True)
class LaunchAdapters:
    """The injected adapters the sequence drives. Two parameter channels, on purpose.

    ``human_parameters`` operates under the actor's human profile and touches only
    the input parameter; ``launcher_parameters`` operates under the launcher
    profile and touches only the release parameter. The sequence never crosses
    them, and a test proves each channel saw only its own parameter name.
    """

    ecs: EcsTaskAdapter
    ec2: Ec2InterfaceAdapter
    human_parameters: SsmParameterAdapter
    launcher_parameters: SsmParameterAdapter


@dataclass(frozen=True, slots=True, kw_only=True)
class LaunchHandle:
    """The one task this sequence started. Its ARN is held and never rendered."""

    task_arn: str

    def __repr__(self) -> str:
        """A fixed token."""
        return "LaunchHandle(<redacted>)"


@dataclass(frozen=True, slots=True, kw_only=True)
class LaunchReport:
    """The sanitized result: one outcome, counts, incident and cleanup failures.

    ``task_exit_codes`` are the containers' integer exit codes as ECS reported
    them at the terminal state, ``None`` where ECS reported none. They are the
    task's *process* status, never a claim about what it did.
    """

    outcome: LaunchOutcome
    counts: OperationCounts
    incident: PlacementIncident | None
    cleanup_failures: tuple[CleanupFailure, ...]
    task_started: bool
    task_exit_codes: tuple[int | None, ...]
    handle: LaunchHandle | None

    def __post_init__(self) -> None:
        """Closed members and integers only; a handle exactly when a task started."""
        if type(self.outcome) is not LaunchOutcome:
            raise TypeError("outcome must be an exact LaunchOutcome member")
        if type(self.counts) is not OperationCounts:
            raise TypeError("counts must be an exact OperationCounts")
        if self.incident is not None and type(self.incident) is not PlacementIncident:
            raise TypeError("incident must be an exact PlacementIncident member or None")
        if any(type(failure) is not CleanupFailure for failure in self.cleanup_failures):
            raise TypeError("cleanup failures must be exact CleanupFailure values")
        if self.task_started != (self.handle is not None):
            raise ValueError("a handle is present exactly when a task started")
        if (self.outcome is LaunchOutcome.MISPLACED) != (self.incident is not None):
            raise ValueError("an incident is present exactly when the outcome is MISPLACED")

    def __repr__(self) -> str:
        """Outcome and counts of failures. **Never a handle.**"""
        return (
            f"LaunchReport(outcome={self.outcome.value!r}, "
            f"cleanup_failures={len(self.cleanup_failures)})"
        )


class _AbortedError(Exception):
    """Internal: the sequence stops with this outcome. Never escapes the module."""

    def __init__(self, outcome: LaunchOutcome, incident: PlacementIncident | None = None) -> None:
        super().__init__(outcome.value)
        self.outcome = outcome
        self.incident = incident


class _ProofVerdict(StrEnum):
    """What one identity-proof invocation came back with. Closed; carries no text."""

    PASSED = "PASSED"
    REFUSED = "REFUSED"
    UNAVAILABLE = "UNAVAILABLE"


def _proof_verdict(
    identity_proof: Callable[[IdentityPath], str | None], path: IdentityPath
) -> _ProofVerdict:
    """Invoke the injected proof once and reduce whatever it does to a closed verdict.

    A proof that raises -- an STS failure, a profile that will not resolve, a bug in
    the injected callable -- is ``UNAVAILABLE``. **Nothing it raised survives**: the
    exception is neither stored nor rendered, so its text cannot reach a report.
    """
    try:
        reason = identity_proof(path)
    except Exception:
        return _ProofVerdict.UNAVAILABLE
    return _ProofVerdict.PASSED if reason is None else _ProofVerdict.REFUSED


@dataclass(frozen=True, slots=True, kw_only=True)
class _AdapterCounts:
    """A snapshot of the adapters' own request counters."""

    run_task: int
    describe_tasks: int
    describe_network_interfaces: int
    stop_task: int
    parameter_creates: int
    parameter_deletes: int
    parameter_reads: int

    @classmethod
    def of(cls, adapters: LaunchAdapters) -> _AdapterCounts:
        return cls(
            run_task=adapters.ecs.run_count,
            describe_tasks=adapters.ecs.describe_count,
            describe_network_interfaces=adapters.ec2.describe_count,
            stop_task=adapters.ecs.stop_count,
            parameter_creates=adapters.human_parameters.put_count
            + adapters.launcher_parameters.put_count,
            parameter_deletes=adapters.human_parameters.delete_count
            + adapters.launcher_parameters.delete_count,
            parameter_reads=adapters.human_parameters.get_count
            + adapters.launcher_parameters.get_count,
        )


def _placement_incident(
    compiled: CompiledLaunch, task: TaskDescription, adapters: LaunchAdapters
) -> PlacementIncident | None:
    """The first mismatch placement verification finds, or ``None`` when it passes."""
    if task.task_definition_arn != compiled.task_definition_arn:
        return PlacementIncident.REVISION_MISMATCH
    attachment = task.attachment
    if attachment is None or attachment.network_interface_id is None:
        return PlacementIncident.INTERFACE_UNRESOLVED
    if attachment.subnet_id != compiled.subnet_id:
        return PlacementIncident.SUBNET_MISMATCH
    try:
        interface = adapters.ec2.describe_interface(attachment.network_interface_id)
    except ComputeError:
        return PlacementIncident.INTERFACE_UNRESOLVED
    if interface.subnet_id != compiled.subnet_id:
        return PlacementIncident.SUBNET_MISMATCH
    if interface.security_group_ids != frozenset(compiled.security_group_ids):
        return PlacementIncident.SECURITY_GROUP_MISMATCH
    if interface.public_ip_present is not compiled.assign_public_ip:
        return PlacementIncident.PUBLIC_IP_MISMATCH
    return None


def launch_authorized_run(
    *,
    compiled: CompiledLaunch,
    adapters: LaunchAdapters,
    authorization: LaunchAuthorization,
    identity_proof: Callable[[IdentityPath], str | None],
    now: Callable[[], datetime],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
) -> LaunchReport:
    """Run the whole launch sequence for one authorized run; one sanitized report.

    ``identity_proof`` is invoked with ``HUMAN`` before the input is materialized and
    before it is deleted, and with ``LAUNCHER`` before the launch and before the
    release is deleted -- the before-and-after check each profile carries. A
    refusal at any proof stops the sequence with ``REFUSED_IDENTITY`` and a proof
    that raises stops it with ``REFUSED_IDENTITY_UNAVAILABLE``; at a cleanup proof
    either is a cleanup failure for that stage alone, and the primary outcome stands.
    """
    if type(compiled) is not CompiledLaunch or type(adapters) is not LaunchAdapters:
        raise TypeError("compiled and adapters must be exact values")
    if type(authorization) is not LaunchAuthorization:
        raise TypeError("authorization must be an exact LaunchAuthorization")
    constants = constants_for(compiled.actor)
    before = _AdapterCounts.of(adapters)
    identity_calls = 0
    incident: PlacementIncident | None = None
    handle: LaunchHandle | None = None
    exit_codes: tuple[int | None, ...] = ()
    cleanup: list[CleanupFailure] = []
    input_materialized = False
    release_written = False

    def prove(path: IdentityPath) -> None:
        nonlocal identity_calls
        identity_calls += 1
        verdict = _proof_verdict(identity_proof, path)
        if verdict is _ProofVerdict.REFUSED:
            raise _AbortedError(LaunchOutcome.REFUSED_IDENTITY)
        if verdict is _ProofVerdict.UNAVAILABLE:
            raise _AbortedError(LaunchOutcome.REFUSED_IDENTITY_UNAVAILABLE)

    def elapsed_since(start: float) -> float:
        return max(0.0, monotonic() - start)

    def stop_own_task(reason: str) -> None:
        """``StopTask`` on the task this sequence started, and on no other."""
        assert handle is not None
        try:
            adapters.ecs.stop_task(handle.task_arn, reason=reason)
        except ComputeError as error:
            cleanup.append(
                CleanupFailure(stage=CleanupStage.STOP_TASK, failure=error.failure.value)
            )

    def cleanup_stage(stage: CleanupStage, path: IdentityPath, delete: Callable[[], None]) -> None:
        """One prescribed cleanup: its own identity proof, then one delete.

        Independent of every other stage. A proof that refuses or raises, and a
        delete that refuses, each become one recorded failure for **this** stage
        and nothing else; the next stage still runs its own proof.
        """
        nonlocal identity_calls
        identity_calls += 1
        verdict = _proof_verdict(identity_proof, path)
        if verdict is _ProofVerdict.REFUSED:
            cleanup.append(CleanupFailure(stage=stage, failure=CLEANUP_IDENTITY_REFUSED))
            return
        if verdict is _ProofVerdict.UNAVAILABLE:
            cleanup.append(CleanupFailure(stage=stage, failure=CLEANUP_IDENTITY_UNAVAILABLE))
            return
        try:
            delete()
        except ParameterError as error:
            cleanup.append(CleanupFailure(stage=stage, failure=error.failure))

    def prescribed_cleanup() -> None:
        """Step 10, always: each stage attempted on its own, in the prescribed order."""
        if release_written:
            cleanup_stage(
                CleanupStage.DELETE_RELEASE,
                IdentityPath.LAUNCHER,
                lambda: adapters.launcher_parameters.delete_parameter(constants.release_parameter),
            )
        if input_materialized:
            cleanup_stage(
                CleanupStage.DELETE_INPUT,
                IdentityPath.HUMAN,
                lambda: adapters.human_parameters.delete_parameter(constants.input_parameter),
            )

    outcome: LaunchOutcome
    try:
        # Step 0: the human profile materializes the input, create-only.
        prove(IdentityPath.HUMAN)
        try:
            adapters.human_parameters.create_parameter(
                constants.input_parameter,
                authorization.input_bytes,
                key_id=compiled.binding_key_arn,
                expires_at_iso=(now() + INPUT_EXPIRATION).isoformat(),
            )
        except ParameterError as error:
            if error.failure is ParameterFailure.ALREADY_EXISTS:
                raise _AbortedError(LaunchOutcome.REFUSED_INPUT_EXISTS) from None
            raise _AbortedError(LaunchOutcome.REFUSED_INPUT_WRITE) from None
        input_materialized = True
        digest = input_digest(authorization.input_bytes)

        # Step 1: the launcher profile starts exactly one task.
        prove(IdentityPath.LAUNCHER)
        try:
            task_arn = adapters.ecs.run_task()
        except ComputeError:
            raise _AbortedError(LaunchOutcome.REFUSED_LAUNCH) from None
        handle = LaunchHandle(task_arn=task_arn)

        # Step 1a: placement, as soon as the attachment reports ATTACHED.
        started = monotonic()
        task: TaskDescription | None = None
        while True:
            try:
                task = adapters.ecs.describe_task(task_arn)
            except ComputeError:
                raise _AbortedError(LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED) from None
            attached = task.attachment is not None and task.attachment.status == "ATTACHED"
            if attached or task.stopped:
                break
            if elapsed_since(started) + PLACEMENT_POLL_INTERVAL_SECONDS > PLACEMENT_CEILING_SECONDS:
                stop_own_task(STOP_REASON_MISPLACED)
                raise _AbortedError(LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED)
            sleep(PLACEMENT_POLL_INTERVAL_SECONDS)
        if task.attachment is None or task.attachment.status != "ATTACHED":
            # Stopped before an interface was ever attached: nothing to verify.
            exit_codes = task.exit_codes
            raise _AbortedError(LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED)
        found = _placement_incident(compiled, task, adapters)
        if found is not None:
            # Misplaced: stop this task, write no release, record the incident. The
            # stop is issued even if the task already reached RUNNING or STOPPED.
            stop_own_task(STOP_REASON_MISPLACED)
            raise _AbortedError(LaunchOutcome.MISPLACED, found)
        assert task.attachment.network_interface_id is not None
        assert task.attachment.subnet_id is not None
        if task.stopped:
            # Placement verified, but the task is already terminal: a release
            # would name a task that can no longer read it, so none is written.
            exit_codes = task.exit_codes
            raise _AbortedError(LaunchOutcome.TASK_TERMINAL)

        # Step 1a, completed: the launcher profile writes the release, create-only.
        verified_at = now()
        try:
            release = build_release_document(
                actor=compiled.actor,
                task_arn=task_arn,
                task_definition_arn=task.task_definition_arn,
                identity=authorization.identity,
                input_digest=digest,
                network_interface_id=task.attachment.network_interface_id,
                subnet_id=task.attachment.subnet_id,
                verified_at=verified_at,
            )
        except ReleaseError:
            stop_own_task(STOP_REASON_MISPLACED)
            raise _AbortedError(LaunchOutcome.REFUSED_RELEASE_WRITE) from None
        try:
            adapters.launcher_parameters.create_parameter(
                constants.release_parameter,
                release,
                key_id=compiled.binding_key_arn,
                expires_at_iso=(verified_at + RELEASE_EXPIRATION).isoformat(),
            )
        except ParameterError as error:
            if error.failure is ParameterFailure.ALREADY_EXISTS:
                stop_own_task(STOP_REASON_RELEASE_EXISTS)
                raise _AbortedError(LaunchOutcome.REFUSED_RELEASE_EXISTS) from None
            stop_own_task(STOP_REASON_RELEASE_EXISTS)
            raise _AbortedError(LaunchOutcome.REFUSED_RELEASE_WRITE) from None
        release_written = True

        # Step 9, observed: wait for the terminal state, bounded.
        observe_started = monotonic()
        while True:
            try:
                task = adapters.ecs.describe_task(task_arn)
            except ComputeError:
                raise _AbortedError(LaunchOutcome.OBSERVATION_FAILED) from None
            if task.stopped:
                exit_codes = task.exit_codes
                break
            if (
                elapsed_since(observe_started) + OBSERVE_POLL_INTERVAL_SECONDS
                > OBSERVE_CEILING_SECONDS
            ):
                raise _AbortedError(LaunchOutcome.OBSERVATION_TIMEOUT)
            sleep(OBSERVE_POLL_INTERVAL_SECONDS)
        outcome = LaunchOutcome.TASK_TERMINAL
    except _AbortedError as aborted:
        outcome = aborted.outcome
        incident = aborted.incident
    finally:
        # Step 10: prescribed cleanup, whatever stopped the sequence -- a closed
        # outcome or an exception nothing above classified. Each stage records its
        # own failure; the outcome, when there is one, stands.
        prescribed_cleanup()

    after = _AdapterCounts.of(adapters)
    counts = OperationCounts(
        parameter_reads=after.parameter_reads - before.parameter_reads,
        parameter_creates=after.parameter_creates - before.parameter_creates,
        parameter_deletes=after.parameter_deletes - before.parameter_deletes,
        run_task=after.run_task - before.run_task,
        describe_tasks=after.describe_tasks - before.describe_tasks,
        describe_network_interfaces=(
            after.describe_network_interfaces - before.describe_network_interfaces
        ),
        stop_task=after.stop_task - before.stop_task,
        identity_calls=identity_calls,
    )
    return LaunchReport(
        outcome=outcome,
        counts=counts,
        incident=incident,
        cleanup_failures=tuple(cleanup),
        task_started=handle is not None,
        task_exit_codes=exit_codes,
        handle=handle,
    )


__all__ = [
    "INPUT_EXPIRATION",
    "OBSERVE_CEILING_SECONDS",
    "OBSERVE_POLL_INTERVAL_SECONDS",
    "PLACEMENT_CEILING_SECONDS",
    "PLACEMENT_POLL_INTERVAL_SECONDS",
    "RELEASE_EXPIRATION",
    "STOP_REASON_MISPLACED",
    "STOP_REASON_RELEASE_EXISTS",
    "LaunchAdapters",
    "LaunchAuthorization",
    "LaunchHandle",
    "LaunchReport",
    "launch_authorized_run",
]
