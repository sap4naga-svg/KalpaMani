"""Closed outcome vocabularies and integer counts (ADR-0036 §2.9, §2.12 step 8).

Public output is **allowlisted sentences plus integer counts**: no key, digest,
identifier, subject, ARN or vendor row. Every outcome below is a closed member,
every count is an ``int``, and the two report types refuse to be constructed with
anything else. A cleanup failure is reported **beside** the primary outcome, never
in place of it: the run's own verdict is preserved, and the cleanup that failed is
named by stage and failure category only.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Final

from kalpamani.data.production.sharadar.parameters import ParameterFailure


class RunnerOutcome(StrEnum):
    """The task-side sequence's one verdict. Closed.

    ``HALTED_PROCESSING_NOT_IMPLEMENTED`` is the honest terminal state of this
    cycle: the release barrier passed and **no acquisition or build processing
    exists to run**, so the runner halts with zero data-plane operations rather
    than claiming any.
    """

    REFUSED_ENVIRONMENT = "REFUSED_ENVIRONMENT"
    REFUSED_BINDING = "REFUSED_BINDING"
    REFUSED_INPUT = "REFUSED_INPUT"
    REFUSED_SELF_CHECK = "REFUSED_SELF_CHECK"
    REFUSED_IDENTITY = "REFUSED_IDENTITY"
    REFUSED_NO_RELEASE = "REFUSED_NO_RELEASE"
    REFUSED_RELEASE_MISMATCH = "REFUSED_RELEASE_MISMATCH"
    REFUSED_RELEASE_READ = "REFUSED_RELEASE_READ"
    HALTED_PROCESSING_NOT_IMPLEMENTED = "HALTED_PROCESSING_NOT_IMPLEMENTED"


class LaunchOutcome(StrEnum):
    """The launch tool's one verdict per authorized run. Closed."""

    REFUSED_IDENTITY = "REFUSED_IDENTITY"
    REFUSED_INPUT_EXISTS = "REFUSED_INPUT_EXISTS"
    REFUSED_INPUT_WRITE = "REFUSED_INPUT_WRITE"
    REFUSED_LAUNCH = "REFUSED_LAUNCH"
    REFUSED_PLACEMENT_UNVERIFIED = "REFUSED_PLACEMENT_UNVERIFIED"
    MISPLACED = "MISPLACED"
    REFUSED_RELEASE_EXISTS = "REFUSED_RELEASE_EXISTS"
    REFUSED_RELEASE_WRITE = "REFUSED_RELEASE_WRITE"
    OBSERVATION_FAILED = "OBSERVATION_FAILED"
    OBSERVATION_TIMEOUT = "OBSERVATION_TIMEOUT"
    TASK_TERMINAL = "TASK_TERMINAL"


class PlacementIncident(StrEnum):
    """What placement verification found wrong. Closed; names no identifier."""

    REVISION_MISMATCH = "REVISION_MISMATCH"
    SUBNET_MISMATCH = "SUBNET_MISMATCH"
    SECURITY_GROUP_MISMATCH = "SECURITY_GROUP_MISMATCH"
    PUBLIC_IP_MISMATCH = "PUBLIC_IP_MISMATCH"
    INTERFACE_UNRESOLVED = "INTERFACE_UNRESOLVED"


class CleanupStage(StrEnum):
    """Which prescribed cleanup operation failed. Closed."""

    DELETE_RELEASE = "DELETE_RELEASE"
    DELETE_INPUT = "DELETE_INPUT"
    STOP_TASK = "STOP_TASK"


@dataclass(frozen=True, slots=True, kw_only=True)
class CleanupFailure:
    """One cleanup operation that did not succeed: the stage and the category."""

    stage: CleanupStage
    failure: ParameterFailure | str

    def __post_init__(self) -> None:
        """Two closed tokens, nothing else."""
        if type(self.stage) is not CleanupStage:
            raise TypeError("stage must be an exact CleanupStage member")
        if type(self.failure) is not ParameterFailure and type(self.failure) is not str:
            raise TypeError("failure must be a closed category token")


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationCounts:
    """Integer counts of what was asked of each adapter. Observed, never planned."""

    parameter_reads: int = 0
    parameter_creates: int = 0
    parameter_deletes: int = 0
    run_task: int = 0
    describe_tasks: int = 0
    describe_network_interfaces: int = 0
    stop_task: int = 0
    identity_calls: int = 0
    s3_operations: int = 0
    secret_retrievals: int = 0
    provider_requests: int = 0

    def __post_init__(self) -> None:
        """Every count is a non-negative exact ``int``."""
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or value < 0:
                raise TypeError(f"{field.name} must be a non-negative int")

    @property
    def data_plane_operations(self) -> int:
        """S3, secret and provider operations together: the barrier guards these."""
        return self.s3_operations + self.secret_retrievals + self.provider_requests


#: The allowlisted sentence for each runner outcome. One per member; a test
#: asserts totality, so a new member cannot ship without a sentence.
RUNNER_SENTENCES: Final[dict[RunnerOutcome, str]] = {
    RunnerOutcome.REFUSED_ENVIRONMENT: (
        "production runner refused: the task environment is not clean"
    ),
    RunnerOutcome.REFUSED_BINDING: (
        "production runner refused: the runtime binding did not validate"
    ),
    RunnerOutcome.REFUSED_INPUT: "production runner refused: the input did not validate",
    RunnerOutcome.REFUSED_SELF_CHECK: "production runner refused: the task self-check did not pass",
    RunnerOutcome.REFUSED_IDENTITY: "production runner refused: the identity proof did not pass",
    RunnerOutcome.REFUSED_NO_RELEASE: "production runner refused: no placement release arrived",
    RunnerOutcome.REFUSED_RELEASE_MISMATCH: (
        "production runner refused: the placement release did not match"
    ),
    RunnerOutcome.REFUSED_RELEASE_READ: (
        "production runner refused: the placement release could not be read"
    ),
    RunnerOutcome.HALTED_PROCESSING_NOT_IMPLEMENTED: (
        "production runner halted: release verified; processing is not implemented"
    ),
}

LAUNCH_SENTENCES: Final[dict[LaunchOutcome, str]] = {
    LaunchOutcome.REFUSED_IDENTITY: "production launch refused: the identity proof did not pass",
    LaunchOutcome.REFUSED_INPUT_EXISTS: (
        "production launch refused: an input parameter already exists"
    ),
    LaunchOutcome.REFUSED_INPUT_WRITE: (
        "production launch refused: the input could not be materialized"
    ),
    LaunchOutcome.REFUSED_LAUNCH: "production launch refused: the task could not be started",
    LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED: (
        "production launch refused: placement could not be verified"
    ),
    LaunchOutcome.MISPLACED: "production launch stopped: the task was misplaced",
    LaunchOutcome.REFUSED_RELEASE_EXISTS: (
        "production launch refused: a release parameter already exists"
    ),
    LaunchOutcome.REFUSED_RELEASE_WRITE: (
        "production launch refused: the release could not be written"
    ),
    LaunchOutcome.OBSERVATION_FAILED: "production launch: the task could not be observed",
    LaunchOutcome.OBSERVATION_TIMEOUT: (
        "production launch: the task did not reach a terminal state in time"
    ),
    LaunchOutcome.TASK_TERMINAL: "production launch: the task reached a terminal state",
}


def runner_sentence(outcome: RunnerOutcome) -> str:
    """The one allowlisted sentence for a runner outcome. An exact member only."""
    if type(outcome) is not RunnerOutcome:
        raise TypeError("outcome must be an exact RunnerOutcome member")
    return RUNNER_SENTENCES[outcome]


def launch_sentence(outcome: LaunchOutcome) -> str:
    """The one allowlisted sentence for a launch outcome. An exact member only."""
    if type(outcome) is not LaunchOutcome:
        raise TypeError("outcome must be an exact LaunchOutcome member")
    return LAUNCH_SENTENCES[outcome]


def count_lines(counts: OperationCounts) -> tuple[str, ...]:
    """``name=<int>`` lines, one per count, in declaration order. Integers only."""
    if type(counts) is not OperationCounts:
        raise TypeError("counts must be an exact OperationCounts")
    return tuple(f"{field.name}={getattr(counts, field.name)}" for field in fields(counts))


__all__ = [
    "LAUNCH_SENTENCES",
    "RUNNER_SENTENCES",
    "CleanupFailure",
    "CleanupStage",
    "LaunchOutcome",
    "OperationCounts",
    "PlacementIncident",
    "RunnerOutcome",
    "count_lines",
    "launch_sentence",
    "runner_sentence",
]
