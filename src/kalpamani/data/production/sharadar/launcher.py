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

Every count reported is observed, never planned.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
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
    refusal at any proof stops the sequence with ``REFUSED_IDENTITY``; a refusal at
    a cleanup proof is a cleanup failure and the primary outcome stands.
    """
    if type(compiled) is not CompiledLaunch or type(adapters) is not LaunchAdapters:
        raise TypeError("compiled and adapters must be exact values")
    if type(authorization) is not LaunchAuthorization:
        raise TypeError("authorization must be an exact LaunchAuthorization")
    constants = constants_for(compiled.actor)
    counts = OperationCounts()
    incident: PlacementIncident | None = None
    handle: LaunchHandle | None = None
    exit_codes: tuple[int | None, ...] = ()
    cleanup: list[CleanupFailure] = []
    input_materialized = False
    release_written = False

    def prove(path: IdentityPath) -> None:
        nonlocal counts
        counts = replace(counts, identity_calls=counts.identity_calls + 1)
        if identity_proof(path) is not None:
            raise _AbortedError(LaunchOutcome.REFUSED_IDENTITY)

    def elapsed_since(start: float) -> float:
        return max(0.0, monotonic() - start)

    def stop_own_task(reason: str) -> None:
        """``StopTask`` on the task this sequence started, and on no other."""
        nonlocal counts
        assert handle is not None
        counts = replace(counts, stop_task=counts.stop_task + 1)
        try:
            adapters.ecs.stop_task(handle.task_arn, reason=reason)
        except ComputeError as error:
            cleanup.append(
                CleanupFailure(stage=CleanupStage.STOP_TASK, failure=error.failure.value)
            )

    outcome: LaunchOutcome
    try:
        # Step 0: the human profile materializes the input, create-only.
        prove(IdentityPath.HUMAN)
        counts = replace(counts, parameter_creates=counts.parameter_creates + 1)
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
        counts = replace(counts, run_task=counts.run_task + 1)
        try:
            task_arn = adapters.ecs.run_task()
        except ComputeError:
            raise _AbortedError(LaunchOutcome.REFUSED_LAUNCH) from None
        handle = LaunchHandle(task_arn=task_arn)

        # Step 1a: placement, as soon as the attachment reports ATTACHED.
        started = monotonic()
        task: TaskDescription | None = None
        while True:
            counts = replace(counts, describe_tasks=counts.describe_tasks + 1)
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
        counts = replace(counts, describe_network_interfaces=counts.describe_network_interfaces + 1)
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
        counts = replace(counts, parameter_creates=counts.parameter_creates + 1)
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
            counts = replace(counts, describe_tasks=counts.describe_tasks + 1)
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

    # Step 10: prescribed cleanup. Each failure is recorded; the outcome stands.
    if release_written:
        counts = replace(counts, identity_calls=counts.identity_calls + 1)
        if identity_proof(IdentityPath.LAUNCHER) is not None:
            cleanup.append(
                CleanupFailure(stage=CleanupStage.DELETE_RELEASE, failure="IDENTITY_REFUSED")
            )
        else:
            counts = replace(counts, parameter_deletes=counts.parameter_deletes + 1)
            try:
                adapters.launcher_parameters.delete_parameter(constants.release_parameter)
            except ParameterError as error:
                cleanup.append(
                    CleanupFailure(stage=CleanupStage.DELETE_RELEASE, failure=error.failure)
                )
    if input_materialized:
        counts = replace(counts, identity_calls=counts.identity_calls + 1)
        if identity_proof(IdentityPath.HUMAN) is not None:
            cleanup.append(
                CleanupFailure(stage=CleanupStage.DELETE_INPUT, failure="IDENTITY_REFUSED")
            )
        else:
            counts = replace(counts, parameter_deletes=counts.parameter_deletes + 1)
            try:
                adapters.human_parameters.delete_parameter(constants.input_parameter)
            except ParameterError as error:
                cleanup.append(
                    CleanupFailure(stage=CleanupStage.DELETE_INPUT, failure=error.failure)
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
