"""The deletion rehearsal launch: the launcher's side of the path, offline (ADR-0049 s.3).

The rehearsal launcher (the ``KalpaManiDeletionRehearse`` permission set, a human) starts one
task of the rehearsal family -- whose task role **is** the deletion role -- and never acts
as that role itself. This module is that sequence and its evidence: the owner-registered
**launch inputs** (the exact rehearsal revision, image, cluster, placement, the two roles
the launcher may pass), the **compiled launch**, the launcher's identity rule, the durable
**consumption** of the owner's authorization and the **reservation** written before
``RunTask``, the input and release parameters, the bounded observation to the terminal
state, the **launch record**, and the **completion** that rebuilds the rehearsal record from
the verified receipt under the launcher's own binding.

Ordered so that nothing mutates before the identity is proven and the authorization is
consumed, so an ambiguous ``RunTask`` is recorded and never retried, so a misplaced task is
stopped and never released, and so no evidence is ever removed. The launch inputs are a
contract of their own, not a change to the accepted launch-inputs contract (whose actors are
exactly the two ADR-0036 actors); the deletion role is not a production actor.

**The path is CLOSED** (:data:`deletion_rehearsal.REHEARSAL_PATH_OPEN`): the tool refuses
the rehearsal modes before any path or client, and the only callers here are tests over
fakes. **Mocked results are not AWS verification.**
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar.compute import (
    CLUSTER_ARN_RE,
    KMS_KEY_ARN_RE,
    LAUNCH_TYPE,
    PLATFORM_VERSION_RE,
    ROLE_ARN_RE,
    SECURITY_GROUP_ID_RE,
    ComputeError,
    ComputeFailure,
    ComputeOperation,
    Ec2InterfaceAdapter,
    EcsLikeClient,
    TaskDescription,
    _parse_task,
    classify_compute_failure,
)
from kalpamani.data.production.sharadar.deletion_rehearsal import (
    REHEARSAL_CONSUMPTION_KIND,
    REHEARSAL_CONTAINER,
    REHEARSAL_FAMILY,
    REHEARSAL_INPUT_PARAMETER,
    REHEARSAL_LAUNCHER_PERMISSION_SET,
    REHEARSAL_RELEASE_PARAMETER,
    REHEARSAL_SEQUENCE,
    REHEARSAL_STREAM_PREFIX,
    RehearsalOutcome,
    RehearsalRecord,
    RehearsalStatement,
    RehearsalTarget,
)
from kalpamani.data.production.sharadar.deletion_rehearsal_task import (
    MAX_INPUT_VALIDITY,
    MAX_RELEASE_VALIDITY,
    RehearsalContractError,
    RehearsalExpectation,
    RehearsalInput,
    RehearsalRelease,
    RehearsalTaskOutcome,
    rehearsal_identity,
    verify_rehearsal_receipt,
)
from kalpamani.data.production.sharadar.documents import (
    decode_document,
    exact_str,
    hex_digest,
    instant,
)
from kalpamani.data.production.sharadar.identity import (
    generated_role_suffix,
    parse_assumed_role_arn,
)
from kalpamani.data.production.sharadar.launch_records import RECORD_SCHEMA_VERSION
from kalpamani.data.production.sharadar.launch_store import LaunchStore, StoreDefect, StoreError
from kalpamani.data.production.sharadar.parameters import (
    ParameterError,
    ParameterFailure,
    SsmParameterAdapter,
)
from kalpamani.data.production.sharadar.permission_cells import (
    MAX_PERMISSION_RECORD_BYTES,
    PermissionBinding,
    PermissionCleanup,
    _binding_from,
)
from kalpamani.data.production.sharadar.r3_verification import ObservedClass
from kalpamani.data.production.sharadar.receipt_collector import LogDestination
from kalpamani.data.production.sharadar.release import (
    NETWORK_INTERFACE_ID_RE,
    SUBNET_ID_RE,
    TASK_DEFINITION_ARN_RE,
)

REHEARSAL_LAUNCH_INPUTS_CONTRACT_ID: Final = "kalpamani-deletion-rehearsal-launch-inputs/v1"
REHEARSAL_RESERVATION_CONTRACT_ID: Final = "kalpamani-deletion-rehearsal-reservation/v1"
REHEARSAL_LAUNCH_RECORD_CONTRACT_ID: Final = "kalpamani-deletion-rehearsal-launch-record/v1"
REHEARSAL_RESOLUTION_CONTRACT_ID: Final = "kalpamani-deletion-rehearsal-resolution/v1"
REHEARSAL_RECEIPT_EVIDENCE_CONTRACT_ID: Final = "kalpamani-deletion-rehearsal-receipt-evidence/v1"
#: The two anchor kinds beside the canonical ledger (``LaunchStore.anchor``): every
#: reservation, and every resolution of one, is anchored there by identity -- exclusive,
#: never removed, seen from every records directory over that ledger.
REHEARSAL_RESERVATIONS_ANCHOR: Final = "rehearsal_reservations"
REHEARSAL_RESOLUTIONS_ANCHOR: Final = "rehearsal_resolutions"
#: The one resolution outcome the recovery writes, beside the launch outcomes.
RECOVERED_INTERRUPTED: Final = "RECOVERED_INTERRUPTED"
#: The ``startedBy`` tag a rehearsal launch carries, so the control principal's cleanup
#: discovers the task exactly as it discovers a probe task.
REHEARSAL_STARTED_BY_PREFIX: Final = "kalpamani-rehearsal-"
#: The observation bounds after RunTask: the accepted 5 s poll; at most 120 reads / 600 s.
OBSERVATION_POLL_SECONDS: Final = 5.0
MAX_OBSERVATION_READS: Final = 120
OBSERVATION_CEILING_SECONDS: Final = 600.0
_IMAGE_DIGEST_RE: Final = re.compile(r"sha256:[0-9a-f]{64}")
_STAMP_RE: Final = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{4}")
_TASK_ID_RE: Final = re.compile(r"[0-9a-f]{32}")


class RehearsalLaunchDefect(StrEnum):
    """Why launch inputs or a compiled launch are refused. Closed, value-free."""

    INPUTS_MALFORMED = "INPUTS_MALFORMED"
    NOT_THE_REHEARSAL_FAMILY = "NOT_THE_REHEARSAL_FAMILY"
    ROLE_NOT_THE_DELETION_ROLE = "ROLE_NOT_THE_DELETION_ROLE"
    ACCOUNTS_DIFFER = "ACCOUNTS_DIFFER"
    STAMP_MALFORMED = "STAMP_MALFORMED"
    RECORD_MALFORMED = "RECORD_MALFORMED"


class RehearsalLaunchError(ValueError):
    def __init__(self, defect: RehearsalLaunchDefect) -> None:
        super().__init__(defect.value)
        self.defect = defect


def _refuse(defect: RehearsalLaunchDefect) -> RehearsalLaunchError:
    return RehearsalLaunchError(defect)


# ---------------------------------------------------------------------------
# The owner-registered launch inputs, and the compiled launch
# ---------------------------------------------------------------------------

_INPUTS_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "cluster_arn",
        "task_definition_arn",
        "image_digest",
        "execution_role_arn",
        "deletion_role_arn",
        "subnet_id",
        "security_group_ids",
        "platform_version",
        "binding_key_arn",
        "log_destination",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalLaunchInputs:
    """What the owner registers once the rehearsal resources are applied: the exact
    revision and image, the cluster and placement (the build subnet: no internet route),
    the two roles the launcher may pass, the binding key and the log destination. All
    constants; every ARN in one account; the family and the role held to their names."""

    cluster_arn: str
    task_definition_arn: str
    image_digest: str
    execution_role_arn: str
    deletion_role_arn: str
    subnet_id: str
    security_group_ids: tuple[str, ...]
    platform_version: str
    binding_key_arn: str
    log_destination: LogDestination

    def __post_init__(self) -> None:
        cluster = CLUSTER_ARN_RE.fullmatch(self.cluster_arn or "")
        definition = TASK_DEFINITION_ARN_RE.fullmatch(self.task_definition_arn or "")
        execution = ROLE_ARN_RE.fullmatch(self.execution_role_arn or "")
        deletion = ROLE_ARN_RE.fullmatch(self.deletion_role_arn or "")
        key = KMS_KEY_ARN_RE.fullmatch(self.binding_key_arn or "")
        if (
            cluster is None
            or definition is None
            or execution is None
            or deletion is None
            or key is None
            or _IMAGE_DIGEST_RE.fullmatch(self.image_digest or "") is None
            or SUBNET_ID_RE.fullmatch(self.subnet_id or "") is None
            or PLATFORM_VERSION_RE.fullmatch(self.platform_version or "") is None
            or type(self.security_group_ids) is not tuple
            or not self.security_group_ids
            or any(SECURITY_GROUP_ID_RE.fullmatch(g or "") is None for g in self.security_group_ids)
            or type(self.log_destination) is not LogDestination
        ):
            raise _refuse(RehearsalLaunchDefect.INPUTS_MALFORMED)
        if definition.group(2) != REHEARSAL_FAMILY:
            raise _refuse(RehearsalLaunchDefect.NOT_THE_REHEARSAL_FAMILY)
        if not deletion.group(2).endswith("-licensed-data-deletion"):
            raise _refuse(RehearsalLaunchDefect.ROLE_NOT_THE_DELETION_ROLE)
        if (
            self.log_destination.container != REHEARSAL_CONTAINER
            or self.log_destination.stream_prefix != REHEARSAL_STREAM_PREFIX
        ):
            raise _refuse(RehearsalLaunchDefect.INPUTS_MALFORMED)
        accounts = {
            cluster.group(1),
            definition.group(1),
            execution.group(1),
            deletion.group(1),
            key.group(1),
        }
        if len(accounts) != 1:
            raise _refuse(RehearsalLaunchDefect.ACCOUNTS_DIFFER)

    @property
    def cluster_name(self) -> str:
        return self.cluster_arn.rsplit("/", 1)[1]

    @property
    def deletion_role_name(self) -> str:
        return self.deletion_role_arn.rsplit("/", 1)[1]

    @property
    def account(self) -> str:
        match = CLUSTER_ARN_RE.fullmatch(self.cluster_arn)
        assert match is not None
        return match.group(1)

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": REHEARSAL_LAUNCH_INPUTS_CONTRACT_ID,
            "cluster_arn": self.cluster_arn,
            "task_definition_arn": self.task_definition_arn,
            "image_digest": self.image_digest,
            "execution_role_arn": self.execution_role_arn,
            "deletion_role_arn": self.deletion_role_arn,
            "subnet_id": self.subnet_id,
            "security_group_ids": list(self.security_group_ids),
            "platform_version": self.platform_version,
            "binding_key_arn": self.binding_key_arn,
            "log_destination": self.log_destination.document(),
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.document()))

    def __repr__(self) -> str:
        return "RehearsalLaunchInputs(<redacted>)"


def parse_rehearsal_launch_inputs(raw: object) -> RehearsalLaunchInputs:
    """The launch inputs, parsed closed, or refuse."""
    from kalpamani.data.production.sharadar.receipt_collector import (
        CollectorError,
        parse_log_destination,
    )

    document = raw if type(raw) is dict else _decode(raw)
    if type(document) is not dict or set(document) != _INPUTS_FIELDS:
        raise _refuse(RehearsalLaunchDefect.INPUTS_MALFORMED)
    if (
        document["schema_version"] != RECORD_SCHEMA_VERSION
        or document["contract_id"] != REHEARSAL_LAUNCH_INPUTS_CONTRACT_ID
    ):
        raise _refuse(RehearsalLaunchDefect.INPUTS_MALFORMED)
    strings = {
        name: exact_str(document[name])
        for name in (
            "cluster_arn",
            "task_definition_arn",
            "image_digest",
            "execution_role_arn",
            "deletion_role_arn",
            "subnet_id",
            "platform_version",
            "binding_key_arn",
        )
    }
    groups = document["security_group_ids"]
    if any(v is None for v in strings.values()) or type(groups) is not list:
        raise _refuse(RehearsalLaunchDefect.INPUTS_MALFORMED)
    if any(exact_str(g) is None for g in groups):
        raise _refuse(RehearsalLaunchDefect.INPUTS_MALFORMED)
    try:
        destination = parse_log_destination(document["log_destination"])
    except CollectorError:
        raise _refuse(RehearsalLaunchDefect.INPUTS_MALFORMED) from None
    return RehearsalLaunchInputs(
        cluster_arn=str(strings["cluster_arn"]),
        task_definition_arn=str(strings["task_definition_arn"]),
        image_digest=str(strings["image_digest"]),
        execution_role_arn=str(strings["execution_role_arn"]),
        deletion_role_arn=str(strings["deletion_role_arn"]),
        subnet_id=str(strings["subnet_id"]),
        security_group_ids=tuple(str(g) for g in groups),
        platform_version=str(strings["platform_version"]),
        binding_key_arn=str(strings["binding_key_arn"]),
        log_destination=destination,
    )


def _decode(raw: object) -> dict[str, Any]:
    try:
        return decode_document(raw, max_bytes=MAX_PERMISSION_RECORD_BYTES)
    except Exception:
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED) from None


@dataclass(frozen=True, slots=True, kw_only=True)
class CompiledRehearsalLaunch:
    """One rehearsal launch as ``RunTask`` receives it: the registered inputs and the
    session stamp as the ``startedBy`` tag. No ``overrides``: the task role is the
    task definition's -- the deletion role -- and nothing the launcher passes changes it."""

    inputs: RehearsalLaunchInputs
    stamp: str

    def __post_init__(self) -> None:
        if type(self.inputs) is not RehearsalLaunchInputs:
            raise _refuse(RehearsalLaunchDefect.INPUTS_MALFORMED)
        if type(self.stamp) is not str or _STAMP_RE.fullmatch(self.stamp) is None:
            raise _refuse(RehearsalLaunchDefect.STAMP_MALFORMED)

    @property
    def started_by(self) -> str:
        return REHEARSAL_STARTED_BY_PREFIX + self.stamp

    @property
    def identity(self) -> str:
        return rehearsal_identity(self.stamp)

    def request(self) -> dict[str, Any]:
        """The exact ``RunTask`` keyword arguments: no ``overrides`` key, no
        ``enableExecuteCommand``, the tag the cleanup lists by."""
        return {
            "cluster": self.inputs.cluster_arn,
            "taskDefinition": self.inputs.task_definition_arn,
            "count": 1,
            "launchType": LAUNCH_TYPE,
            "platformVersion": self.inputs.platform_version,
            "networkConfiguration": {
                "awsvpcConfiguration": {
                    "subnets": [self.inputs.subnet_id],
                    "securityGroups": list(self.inputs.security_group_ids),
                    "assignPublicIp": "DISABLED",
                }
            },
            "enableExecuteCommand": False,
            "startedBy": self.started_by,
        }

    def document(self) -> dict[str, Any]:
        """The whole specification a reservation retains: the registered inputs and the stamp."""
        return {"inputs": self.inputs.document(), "stamp": self.stamp}

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.document()))

    def __repr__(self) -> str:
        return "CompiledRehearsalLaunch(<redacted>)"


def parse_compiled_rehearsal_launch(raw: object) -> CompiledRehearsalLaunch:
    """A retained specification back into the compiled launch, or refuse."""
    if type(raw) is not dict or set(raw) != {"inputs", "stamp"}:
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    stamp = exact_str(raw["stamp"])
    if stamp is None:
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    try:
        inputs = parse_rehearsal_launch_inputs(canonical_bytes(raw["inputs"]))
        return CompiledRehearsalLaunch(inputs=inputs, stamp=stamp)
    except (RehearsalLaunchError, TypeError, ValueError):
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED) from None


class RehearsalEcs:
    """``RunTask`` once, ``DescribeTasks`` and ``StopTask`` on that one task, over an
    injected ECS-shaped client, for one compiled rehearsal launch."""

    __slots__ = ("_compiled", "_ecs", "describe_count", "run_count", "stop_count")

    def __init__(self, *, ecs: EcsLikeClient, compiled: CompiledRehearsalLaunch) -> None:
        for method in ("run_task", "describe_tasks", "stop_task"):
            if not callable(getattr(ecs, method, None)):
                raise ComputeError(
                    operation=ComputeOperation.RUN_TASK,
                    failure=ComputeFailure.INVALID_CONFIGURATION,
                )
        self._ecs = ecs
        self._compiled = compiled
        self.run_count = 0
        self.describe_count = 0
        self.stop_count = 0

    def run_task(self) -> str:
        self.run_count += 1
        try:
            response = self._ecs.run_task(**self._compiled.request())
        except Exception as exception:
            raise ComputeError(
                operation=ComputeOperation.RUN_TASK, failure=classify_compute_failure(exception)
            ) from None
        if not isinstance(response, Mapping):
            raise ComputeError(
                operation=ComputeOperation.RUN_TASK, failure=ComputeFailure.INVALID_RESPONSE
            )
        failures, tasks = response.get("failures"), response.get("tasks")
        if (
            (isinstance(failures, list) and failures)
            or not isinstance(tasks, list)
            or len(tasks) != 1
        ):
            raise ComputeError(
                operation=ComputeOperation.RUN_TASK, failure=ComputeFailure.INVALID_RESPONSE
            )
        try:
            return _parse_task(tasks[0], cluster_name=self._compiled.inputs.cluster_name).task_arn
        except ComputeError:
            raise ComputeError(
                operation=ComputeOperation.RUN_TASK, failure=ComputeFailure.INVALID_RESPONSE
            ) from None

    def describe_task(self, task_arn: str) -> TaskDescription:
        self.describe_count += 1
        try:
            response = self._ecs.describe_tasks(
                cluster=self._compiled.inputs.cluster_arn, tasks=[task_arn]
            )
        except Exception as exception:
            raise ComputeError(
                operation=ComputeOperation.DESCRIBE_TASKS,
                failure=classify_compute_failure(exception),
            ) from None
        tasks = response.get("tasks") if isinstance(response, Mapping) else None
        if not isinstance(tasks, list) or len(tasks) != 1:
            raise ComputeError(
                operation=ComputeOperation.DESCRIBE_TASKS, failure=ComputeFailure.INVALID_RESPONSE
            )
        described = _parse_task(tasks[0], cluster_name=self._compiled.inputs.cluster_name)
        if described.task_arn != task_arn:
            raise ComputeError(
                operation=ComputeOperation.DESCRIBE_TASKS, failure=ComputeFailure.INVALID_RESPONSE
            )
        return described

    def stop_task(self, task_arn: str, *, reason: str) -> None:
        self.stop_count += 1
        try:
            self._ecs.stop_task(
                cluster=self._compiled.inputs.cluster_arn, task=task_arn, reason=reason
            )
        except Exception as exception:
            raise ComputeError(
                operation=ComputeOperation.STOP_TASK, failure=classify_compute_failure(exception)
            ) from None


# ---------------------------------------------------------------------------
# The launcher's identity
# ---------------------------------------------------------------------------


def rehearsal_launcher_identity_verified(caller: Mapping[str, str], *, account: str) -> bool:
    """Whether ``caller`` (``GetCallerIdentity``'s documented fields) is exactly the
    rehearsal launcher: the generated role of ``KalpaManiDeletionRehearse`` in the bound
    account. Structure, not provenance; nothing else is admitted."""
    parsed = parse_assumed_role_arn(caller.get("Arn"))
    if parsed is None or caller.get("Account") != account or parsed.account != account:
        return False
    return generated_role_suffix(REHEARSAL_LAUNCHER_PERMISSION_SET, parsed.role_name) is not None


# ---------------------------------------------------------------------------
# The reservation and the launch record
# ---------------------------------------------------------------------------

_RESERVATION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "identity",
        "subcell_id",
        "statement_sha256",
        "authorization_sha256",
        "specification_sha256",
        "specification",
        "reserved_at",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalReservation:
    """Anchored beside the canonical ledger before ``RunTask`` (correction 1): the identity,
    the subcell, the statement, the authorization consumed and the WHOLE compiled
    specification -- the registered inputs and the stamp, so the cluster, the revision,
    the placement and the ``startedBy`` tag an interrupted or ambiguous launch is
    discovered by are read back from here alone. Exclusive by identity; never removed;
    seen from every records directory over the ledger."""

    identity: str
    subcell_id: str
    statement_sha256: str
    authorization_sha256: str
    specification: CompiledRehearsalLaunch
    reserved_at: datetime

    def __post_init__(self) -> None:
        if self.specification.identity != self.identity:
            raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)

    @property
    def specification_sha256(self) -> str:
        return self.specification.digest

    @property
    def started_by(self) -> str:
        """The tag the cleanup lists by."""
        return self.specification.started_by

    @property
    def cluster_arn(self) -> str:
        return self.specification.inputs.cluster_arn

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": REHEARSAL_RESERVATION_CONTRACT_ID,
            "identity": self.identity,
            "subcell_id": self.subcell_id,
            "statement_sha256": self.statement_sha256,
            "authorization_sha256": self.authorization_sha256,
            "specification_sha256": self.specification_sha256,
            "specification": self.specification.document(),
            "reserved_at": self.reserved_at.isoformat(),
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.document()))

    def __repr__(self) -> str:
        return f"RehearsalReservation(subcell={self.subcell_id!r})"


def parse_rehearsal_reservation(raw: object) -> RehearsalReservation:
    document = raw if type(raw) is dict else _decode(raw)
    if type(document) is not dict or set(document) != _RESERVATION_FIELDS:
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    if (
        document["schema_version"] != RECORD_SCHEMA_VERSION
        or document["contract_id"] != REHEARSAL_RESERVATION_CONTRACT_ID
    ):
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    identity = exact_str(document["identity"])
    subcell = exact_str(document["subcell_id"])
    digests = [
        hex_digest(document[n])
        for n in ("statement_sha256", "authorization_sha256", "specification_sha256")
    ]
    reserved = instant(document["reserved_at"])
    if (
        identity is None
        or subcell not in REHEARSAL_SEQUENCE
        or any(d is None for d in digests)
        or reserved is None
    ):
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    specification = parse_compiled_rehearsal_launch(document["specification"])
    # The retained specification's own digest is the one the reservation names.
    if specification.digest != digests[2] or specification.identity != identity:
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    return RehearsalReservation(
        identity=identity,
        subcell_id=subcell,
        statement_sha256=str(digests[0]),
        authorization_sha256=str(digests[1]),
        specification=specification,
        reserved_at=reserved,
    )


# ---------------------------------------------------------------------------
# The resolution of a reservation, and what stays unsettled
# ---------------------------------------------------------------------------


class RehearsalTaskState(StrEnum):
    """What a resolution establishes about the task the reservation may have started."""

    #: ``RunTask`` was never issued, or answered a definitive refusal: no task exists.
    NOT_STARTED = "NOT_STARTED"
    #: A task was started and the launcher stopped it (a misplacement, a stale release).
    STOPPED = "STOPPED"
    #: A task was started and observed at its terminal state.
    OBSERVED_TERMINAL = "OBSERVED_TERMINAL"
    #: A task was started and NOT observed terminal (observation exhausted, or a stop
    #: that failed): only the cleanup settles it.
    STARTED_NOT_TERMINAL = "STARTED_NOT_TERMINAL"
    #: Whether a task exists is not established (an ambiguous ``RunTask``; an
    #: interruption recovered offline): only the cleanup, listing by the tag, settles it.
    UNKNOWN = "UNKNOWN"


#: The states a resolution settles by itself; every other stays unsettled until a later
#: verified cleanup pass names the reservation and confirms its tasks stopped.
_SELF_SETTLED: Final[frozenset[RehearsalTaskState]] = frozenset(
    {
        RehearsalTaskState.NOT_STARTED,
        RehearsalTaskState.STOPPED,
        RehearsalTaskState.OBSERVED_TERMINAL,
    }
)

_RESOLUTION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "identity",
        "reservation_sha256",
        "outcome",
        "task_state",
        "task_id",
        "launch_record_sha256",
        "resolved_at",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalResolution:
    """How one reservation ended: anchored beside the ledger by the launch sequence at
    every terminal outcome after the reservation, or by the offline recovery of an
    interrupted one. Exactly one per identity; never rewritten."""

    identity: str
    reservation_sha256: str
    outcome: str
    task_state: RehearsalTaskState
    task_id: str | None
    launch_record_sha256: str | None
    resolved_at: datetime

    def __post_init__(self) -> None:
        known = {m.value for m in RehearsalLaunchOutcome} | {RECOVERED_INTERRUPTED}
        if self.outcome not in known:
            raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)

    @property
    def self_settled(self) -> bool:
        return self.task_state in _SELF_SETTLED

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": REHEARSAL_RESOLUTION_CONTRACT_ID,
            "identity": self.identity,
            "reservation_sha256": self.reservation_sha256,
            "outcome": self.outcome,
            "task_state": self.task_state.value,
            "task_id": self.task_id,
            "launch_record_sha256": self.launch_record_sha256,
            "resolved_at": self.resolved_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"RehearsalResolution(outcome={self.outcome!r})"


def parse_rehearsal_resolution(raw: object) -> RehearsalResolution:
    document = raw if type(raw) is dict else _decode(raw)
    if type(document) is not dict or set(document) != _RESOLUTION_FIELDS:
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    if (
        document["schema_version"] != RECORD_SCHEMA_VERSION
        or document["contract_id"] != REHEARSAL_RESOLUTION_CONTRACT_ID
    ):
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    identity = exact_str(document["identity"])
    reservation = hex_digest(document["reservation_sha256"])
    outcome = exact_str(document["outcome"])
    state = exact_str(document["task_state"])
    task_id = document["task_id"]
    launch = document["launch_record_sha256"]
    resolved = instant(document["resolved_at"])
    if (
        identity is None
        or reservation is None
        or outcome is None
        or state not in {m.value for m in RehearsalTaskState}
        or (task_id is not None and _TASK_ID_RE.fullmatch(str(exact_str(task_id) or "")) is None)
        or (launch is not None and hex_digest(launch) is None)
        or resolved is None
    ):
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    try:
        return RehearsalResolution(
            identity=identity,
            reservation_sha256=str(reservation),
            outcome=outcome,
            task_state=RehearsalTaskState(str(state)),
            task_id=None if task_id is None else str(task_id),
            launch_record_sha256=None if launch is None else str(launch),
            resolved_at=resolved,
        )
    except RehearsalLaunchError:
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED) from None


def rehearsal_reservations(store: LaunchStore) -> dict[str, RehearsalReservation]:
    """Every reservation anchored beside the ledger, by identity; a malformed one refuses."""
    found: dict[str, RehearsalReservation] = {}
    for name, raw in store.anchored(REHEARSAL_RESERVATIONS_ANCHOR).items():
        reservation = parse_rehearsal_reservation(raw)
        if reservation.identity != name:
            raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
        found[name] = reservation
    return found


def rehearsal_resolutions(store: LaunchStore) -> dict[str, RehearsalResolution]:
    """Every resolution anchored beside the ledger, by identity; a malformed one refuses."""
    found: dict[str, RehearsalResolution] = {}
    for name, raw in store.anchored(REHEARSAL_RESOLUTIONS_ANCHOR).items():
        resolution = parse_rehearsal_resolution(raw)
        if resolution.identity != name:
            raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
        found[name] = resolution
    return found


@dataclass(frozen=True, slots=True, kw_only=True)
class UnsettledRehearsal:
    """One reservation that still blocks every rehearsal launch: unresolved (no
    resolution -- recovery required), or resolved with a task state only a later verified
    cleanup settles."""

    reservation: RehearsalReservation
    resolution: RehearsalResolution | None

    @property
    def needs_recovery(self) -> bool:
        return self.resolution is None


def unsettled_rehearsals(
    store: LaunchStore, cleanups: Iterable[PermissionCleanup] = ()
) -> list[UnsettledRehearsal]:
    """Every reservation beside the ledger that is not settled, by identity.

    A reservation with no resolution is interrupted work (the process died between the
    reservation and its terminal outcome) and needs ``recover_rehearsal_launch``. A
    resolution whose task state is not self-settled (``UNKNOWN``,
    ``STARTED_NOT_TERMINAL``) stays unsettled until a verified cleanup pass recorded after
    it names the reservation's digest and confirms its known tasks stopped -- uncertain
    cleanup is preserved as unsettled, never assumed. Every unsettled reservation blocks
    every rehearsal launch, whatever the subcell, the records directory or the
    authorization; a malformed reservation or resolution refuses rather than unblocks.
    """
    resolutions = rehearsal_resolutions(store)
    passes = list(cleanups)
    found: list[UnsettledRehearsal] = []
    for identity, reservation in rehearsal_reservations(store).items():
        resolution = resolutions.get(identity)
        if resolution is None:
            found.append(UnsettledRehearsal(reservation=reservation, resolution=None))
            continue
        if resolution.reservation_sha256 != reservation.digest:
            raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
        if resolution.self_settled:
            continue
        known = () if resolution.task_id is None else (resolution.task_id,)
        if any(
            c.identity_verified
            and c.recorded_at >= resolution.resolved_at
            and c.settles_tasks(reservation.digest, known)
            for c in passes
        ):
            continue
        found.append(UnsettledRehearsal(reservation=reservation, resolution=resolution))
    return found


def recover_rehearsal_launch(
    store: LaunchStore, reservation: RehearsalReservation, *, now: datetime
) -> RehearsalResolution:
    """Resolve an interrupted reservation offline: ``RECOVERED_INTERRUPTED`` with the task
    state ``UNKNOWN``. Nothing is launched, nothing is retried, nothing is inferred about
    the task: the cleanup discovers it by the reservation's tag on its cluster and, only
    once it confirms every discovered task stopped, the reservation stops blocking."""
    if reservation.identity in rehearsal_resolutions(store):
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    resolution = RehearsalResolution(
        identity=reservation.identity,
        reservation_sha256=reservation.digest,
        outcome=RECOVERED_INTERRUPTED,
        task_state=RehearsalTaskState.UNKNOWN,
        task_id=None,
        launch_record_sha256=None,
        resolved_at=now,
    )
    store.anchor(REHEARSAL_RESOLUTIONS_ANCHOR, reservation.identity, resolution.document())
    return resolution


class RehearsalLaunchOutcome(StrEnum):
    """What the launch sequence established. Closed."""

    #: The task started, was placed as compiled, released, and observed to its terminal
    #: state; the launch record carries the exit the launcher observed.
    LAUNCHED = "LAUNCHED"
    REFUSED_IDENTITY = "REFUSED_IDENTITY"
    #: An earlier reservation beside the ledger is unsettled: recovery, or the cleanup,
    #: comes first. Refused before anything is consumed.
    REFUSED_RECOVERY_PENDING = "REFUSED_RECOVERY_PENDING"
    REFUSED_CONSUMED = "REFUSED_CONSUMED"
    #: The identity is already reserved beside the ledger (the same stamp reserved before);
    #: the authorization is consumed, nothing is launched.
    REFUSED_RESERVED = "REFUSED_RESERVED"
    REFUSED_INPUT_EXISTS = "REFUSED_INPUT_EXISTS"
    LAUNCH_REFUSED = "LAUNCH_REFUSED"
    #: ``RunTask`` answered ambiguously: a task may exist; the reservation stays; no retry.
    LAUNCH_AMBIGUOUS = "LAUNCH_AMBIGUOUS"
    MISPLACED = "MISPLACED"
    STALE_RELEASE = "STALE_RELEASE"
    #: The task was released but not observed to its terminal state within the bounds.
    OBSERVATION_EXHAUSTED = "OBSERVATION_EXHAUSTED"


_LAUNCH_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "reservation_sha256",
        "schema_version",
        "contract_id",
        "identity",
        "subcell_id",
        "statement_sha256",
        "authorization_sha256",
        "specification_sha256",
        "outcome",
        "task_arn",
        "task_definition_arn",
        "image_digest",
        "input_digest",
        "network_interface_id",
        "subnet_id",
        "security_group_ids",
        "observed_exit_code",
        "launched_at",
        "recorded_at",
        "binding",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalLaunchRecord:
    """What the launcher observed of one launch: the task, the revision and image ECS
    reported, the placement verified, the exit observed at the terminal state, and the
    statement, authorization and binding the launch was made under."""

    identity: str
    subcell_id: str
    statement_sha256: str
    authorization_sha256: str
    specification_sha256: str
    reservation_sha256: str
    outcome: RehearsalLaunchOutcome
    task_arn: str
    task_definition_arn: str
    image_digest: str
    input_digest: str
    network_interface_id: str
    subnet_id: str
    security_group_ids: tuple[str, ...]
    observed_exit_code: int | None
    launched_at: datetime
    recorded_at: datetime
    binding: PermissionBinding

    @property
    def task_id(self) -> str:
        return self.task_arn.rsplit("/", 1)[1]

    def expectation(self) -> RehearsalExpectation:
        return RehearsalExpectation(
            task_id=self.task_id,
            task_definition_arn=self.task_definition_arn,
            image_digest=self.image_digest,
            identity=self.identity,
            input_digest=self.input_digest,
            statement_sha256=self.statement_sha256,
            authorization_sha256=self.authorization_sha256,
        )

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": REHEARSAL_LAUNCH_RECORD_CONTRACT_ID,
            "identity": self.identity,
            "subcell_id": self.subcell_id,
            "statement_sha256": self.statement_sha256,
            "authorization_sha256": self.authorization_sha256,
            "specification_sha256": self.specification_sha256,
            "reservation_sha256": self.reservation_sha256,
            "outcome": self.outcome.value,
            "task_arn": self.task_arn,
            "task_definition_arn": self.task_definition_arn,
            "image_digest": self.image_digest,
            "input_digest": self.input_digest,
            "network_interface_id": self.network_interface_id,
            "subnet_id": self.subnet_id,
            "security_group_ids": list(self.security_group_ids),
            "observed_exit_code": self.observed_exit_code,
            "launched_at": self.launched_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
            "binding": self.binding.document(),
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.document()))

    def __repr__(self) -> str:
        return f"RehearsalLaunchRecord(outcome={self.outcome.value!r})"


def parse_rehearsal_launch_record(raw: object) -> RehearsalLaunchRecord:
    document = raw if type(raw) is dict else _decode(raw)
    if type(document) is not dict or set(document) != _LAUNCH_RECORD_FIELDS:
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    if (
        document["schema_version"] != RECORD_SCHEMA_VERSION
        or document["contract_id"] != REHEARSAL_LAUNCH_RECORD_CONTRACT_ID
    ):
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    strings = {
        n: exact_str(document[n])
        for n in (
            "identity",
            "subcell_id",
            "outcome",
            "task_arn",
            "task_definition_arn",
            "image_digest",
            "network_interface_id",
            "subnet_id",
        )
    }
    digests = {
        n: hex_digest(document[n])
        for n in (
            "statement_sha256",
            "authorization_sha256",
            "specification_sha256",
            "reservation_sha256",
            "input_digest",
        )
    }
    groups = document["security_group_ids"]
    exit_code = document["observed_exit_code"]
    launched, recorded = instant(document["launched_at"]), instant(document["recorded_at"])
    if (
        any(v is None for v in strings.values())
        or any(v is None for v in digests.values())
        or strings["subcell_id"] not in REHEARSAL_SEQUENCE
        or strings["outcome"] not in {m.value for m in RehearsalLaunchOutcome}
        or TASK_DEFINITION_ARN_RE.fullmatch(str(strings["task_definition_arn"])) is None
        or _IMAGE_DIGEST_RE.fullmatch(str(strings["image_digest"])) is None
        or NETWORK_INTERFACE_ID_RE.fullmatch(str(strings["network_interface_id"])) is None
        or SUBNET_ID_RE.fullmatch(str(strings["subnet_id"])) is None
        or type(groups) is not list
        or any(exact_str(g) is None for g in groups)
        or (exit_code is not None and (type(exit_code) is not int or not 0 <= exit_code <= 255))
        or launched is None
        or recorded is None
    ):
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    try:
        binding = _binding_from(document["binding"])
    except Exception:
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED) from None
    return RehearsalLaunchRecord(
        identity=str(strings["identity"]),
        subcell_id=str(strings["subcell_id"]),
        statement_sha256=str(digests["statement_sha256"]),
        authorization_sha256=str(digests["authorization_sha256"]),
        specification_sha256=str(digests["specification_sha256"]),
        reservation_sha256=str(digests["reservation_sha256"]),
        outcome=RehearsalLaunchOutcome(str(strings["outcome"])),
        task_arn=str(strings["task_arn"]),
        task_definition_arn=str(strings["task_definition_arn"]),
        image_digest=str(strings["image_digest"]),
        input_digest=str(digests["input_digest"]),
        network_interface_id=str(strings["network_interface_id"]),
        subnet_id=str(strings["subnet_id"]),
        security_group_ids=tuple(str(g) for g in groups),
        observed_exit_code=exit_code,
        launched_at=launched,
        recorded_at=recorded,
        binding=binding,
    )


# ---------------------------------------------------------------------------
# The launch sequence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalLaunchAdapters:
    """The injected adapters the launcher drives: ECS, EC2 and the two parameter channels
    (the input under the launcher's own profile -- the rehearsal launcher materializes its
    own input, there being no human deletion profile -- and the release under the same)."""

    ecs: RehearsalEcs
    ec2: Ec2InterfaceAdapter
    parameters: SsmParameterAdapter


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalLaunchReport:
    """The sanitized result: the outcome, counts, the record when one was written, and
    every cleanup failure beside the outcome."""

    outcome: RehearsalLaunchOutcome
    run_tasks: int
    describes: int
    stops: int
    parameter_puts: int
    parameter_deletes: int
    record: RehearsalLaunchRecord | None
    cleanup_failures: tuple[str, ...]

    def __repr__(self) -> str:
        return f"RehearsalLaunchReport(outcome={self.outcome.value!r})"


STOP_REASON_MISPLACED: Final = "kalpamani-rehearsal-placement-mismatch"
STOP_REASON_STALE_RELEASE: Final = "kalpamani-rehearsal-stale-release"


def launch_rehearsal(
    statement: RehearsalStatement,
    *,
    authorization_sha256: str,
    authorization_document: dict[str, Any],
    store: LaunchStore,
    compiled: CompiledRehearsalLaunch,
    adapters: RehearsalLaunchAdapters,
    caller_identity: Callable[[], Mapping[str, str]],
    now: Callable[[], datetime],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    cleanups: Iterable[PermissionCleanup] = (),
) -> RehearsalLaunchReport:
    """One rehearsal launch, ordered so that nothing mutates before identity and consumption.

    1. The launcher's identity (``KalpaManiDeletionRehearse`` in the compiled account),
       else refuse with nothing consumed and nothing written.
    2. The authorization consumed durably beside the ledger; a second execution refuses.
    3. The reservation written beside the records.
    4. The input parameter created (create-only; an existing one refuses -- the
       consumption stays, nothing launched).
    5. ``RunTask`` once; a definitive refusal is recorded, an ambiguous answer is
       ``LAUNCH_AMBIGUOUS`` and never retried.
    6. Placement verified from ``DescribeTasks`` and ``DescribeNetworkInterfaces``
       (the compiled subnet and groups, no public IP); a misplaced task is stopped and
       never released.
    7. The release created (create-only; a stale one stops the task).
    8. The task observed to its terminal state within the bounds; the exit recorded.
    9. The release and the input deleted; every failure reported beside the outcome.
    10. The launch record written.
    """
    if statement.subcell_id not in REHEARSAL_SEQUENCE or compiled.stamp != statement.stamp:
        raise _refuse(RehearsalLaunchDefect.STAMP_MALFORMED)
    inputs = compiled.inputs
    counts = {"run": 0, "describe": 0, "stop": 0, "put": 0, "delete": 0}
    failures: list[str] = []

    def report(
        outcome: RehearsalLaunchOutcome, record: RehearsalLaunchRecord | None = None
    ) -> RehearsalLaunchReport:
        return RehearsalLaunchReport(
            outcome=outcome,
            run_tasks=counts["run"],
            describes=counts["describe"],
            stops=counts["stop"],
            parameter_puts=counts["put"],
            parameter_deletes=counts["delete"],
            record=record,
            cleanup_failures=tuple(failures),
        )

    try:
        caller = caller_identity()
    except Exception:
        return report(RehearsalLaunchOutcome.REFUSED_IDENTITY)
    if not rehearsal_launcher_identity_verified(caller, account=inputs.account):
        return report(RehearsalLaunchOutcome.REFUSED_IDENTITY)
    # Correction 1: an unsettled reservation beside the ledger -- interrupted work awaiting
    # recovery, or a task only the cleanup settles -- blocks every launch, before anything
    # is consumed, whatever the subcell, the records directory or the authorization.
    if unsettled_rehearsals(store, cleanups):
        return report(RehearsalLaunchOutcome.REFUSED_RECOVERY_PENDING)
    try:
        store.consume(REHEARSAL_CONSUMPTION_KIND, authorization_sha256, authorization_document)
    except StoreError as error:
        if error.defect is StoreDefect.AUTHORIZATION_CONSUMED:
            return report(RehearsalLaunchOutcome.REFUSED_CONSUMED)
        raise
    identity = compiled.identity
    reservation = RehearsalReservation(
        identity=identity,
        subcell_id=statement.subcell_id,
        statement_sha256=statement.digest,
        authorization_sha256=authorization_sha256,
        specification=compiled,
        reserved_at=now(),
    )
    # The reservation is anchored beside the canonical ledger, exclusively, with the whole
    # specification, BEFORE any client call: an interruption anywhere after this line is
    # attributable from the anchor alone, and the identity can never be reserved twice.
    try:
        store.anchor(REHEARSAL_RESERVATIONS_ANCHOR, identity, reservation.document())
    except StoreError as error:
        if error.defect is StoreDefect.ANCHOR_EXISTS:
            return report(RehearsalLaunchOutcome.REFUSED_RESERVED)
        raise

    def resolve(
        outcome: RehearsalLaunchOutcome,
        state: RehearsalTaskState,
        *,
        task_id: str | None = None,
        record: RehearsalLaunchRecord | None = None,
    ) -> RehearsalLaunchReport:
        """Anchor the resolution of this reservation, then report. Never rewritten."""
        resolution = RehearsalResolution(
            identity=identity,
            reservation_sha256=reservation.digest,
            outcome=outcome.value,
            task_state=state,
            task_id=task_id,
            launch_record_sha256=None if record is None else record.digest,
            resolved_at=now(),
        )
        try:
            store.anchor(REHEARSAL_RESOLUTIONS_ANCHOR, identity, resolution.document())
        except StoreError as error:
            failures.append(f"resolution:{error.defect.value}")
        return report(outcome, record)

    issued = now()
    rehearsal_input = RehearsalInput(
        identity=identity,
        statement=statement,
        authorization_sha256=authorization_sha256,
        issued_at=issued,
        expires_at=issued + MAX_INPUT_VALIDITY,
    )
    input_bytes = rehearsal_input.render()
    counts["put"] += 1
    try:
        adapters.parameters.create_parameter(
            REHEARSAL_INPUT_PARAMETER,
            input_bytes,
            key_id=inputs.binding_key_arn,
            expires_at_iso=rehearsal_input.expires_at.isoformat(),
        )
    except ParameterError as error:
        if error.failure is ParameterFailure.ALREADY_EXISTS:
            return resolve(
                RehearsalLaunchOutcome.REFUSED_INPUT_EXISTS, RehearsalTaskState.NOT_STARTED
            )
        return resolve(RehearsalLaunchOutcome.LAUNCH_REFUSED, RehearsalTaskState.NOT_STARTED)
    launched_at = now()
    counts["run"] += 1
    try:
        task_arn = adapters.ecs.run_task()
    except ComputeError as error:
        _delete(adapters, REHEARSAL_INPUT_PARAMETER, counts, failures)
        if error.failure in (
            ComputeFailure.TRANSIENT,
            ComputeFailure.THROTTLED,
            ComputeFailure.UNKNOWN,
            ComputeFailure.INVALID_RESPONSE,
        ):
            # A task may exist: UNKNOWN, settled only by the cleanup listing the tag.
            return resolve(RehearsalLaunchOutcome.LAUNCH_AMBIGUOUS, RehearsalTaskState.UNKNOWN)
        return resolve(RehearsalLaunchOutcome.LAUNCH_REFUSED, RehearsalTaskState.NOT_STARTED)
    task_id = task_arn.rsplit("/", 1)[1]
    started = monotonic()
    reads = 0

    def exhausted() -> bool:
        return (
            reads >= MAX_OBSERVATION_READS or monotonic() - started >= OBSERVATION_CEILING_SECONDS
        )

    # Placement: the attachment's interface, then the interface itself.
    described: TaskDescription | None = None
    interface_id: str | None = None
    while not exhausted():
        reads += 1
        counts["describe"] += 1
        try:
            described = adapters.ecs.describe_task(task_arn)
        except ComputeError:
            described = None
            break
        attachment = described.attachment
        if attachment is not None and attachment.network_interface_id is not None:
            interface_id = attachment.network_interface_id
            break
        if described.stopped:
            break
        sleep(OBSERVATION_POLL_SECONDS)

    def stopped_state() -> RehearsalTaskState:
        stopped = _stop(adapters, task_arn, STOP_REASON_MISPLACED, counts, failures)
        return RehearsalTaskState.STOPPED if stopped else RehearsalTaskState.STARTED_NOT_TERMINAL

    if described is None or interface_id is None or described.stopped:
        state = stopped_state()
        _delete(adapters, REHEARSAL_INPUT_PARAMETER, counts, failures)
        return resolve(RehearsalLaunchOutcome.MISPLACED, state, task_id=task_id)
    try:
        interface = adapters.ec2.describe_interface(interface_id)
    except ComputeError:
        state = stopped_state()
        _delete(adapters, REHEARSAL_INPUT_PARAMETER, counts, failures)
        return resolve(RehearsalLaunchOutcome.MISPLACED, state, task_id=task_id)
    revision = described.task_definition_arn
    images = [d for d in described.image_digests if d is not None]
    if (
        interface.subnet_id != inputs.subnet_id
        or interface.security_group_ids != frozenset(inputs.security_group_ids)
        or interface.public_ip_present
        or revision != inputs.task_definition_arn
        or images != [inputs.image_digest]
    ):
        state = stopped_state()
        _delete(adapters, REHEARSAL_INPUT_PARAMETER, counts, failures)
        return resolve(RehearsalLaunchOutcome.MISPLACED, state, task_id=task_id)
    release_issued = now()
    release = RehearsalRelease(
        identity=identity,
        task_arn=task_arn,
        task_definition_arn=revision,
        image_digest=inputs.image_digest,
        input_digest=sha256_hex(input_bytes),
        issued_at=release_issued,
        expires_at=release_issued + MAX_RELEASE_VALIDITY,
    )
    counts["put"] += 1
    try:
        adapters.parameters.create_parameter(
            REHEARSAL_RELEASE_PARAMETER,
            release.render(),
            key_id=inputs.binding_key_arn,
            expires_at_iso=release.expires_at.isoformat(),
        )
    except ParameterError:
        stopped = _stop(adapters, task_arn, STOP_REASON_STALE_RELEASE, counts, failures)
        _delete(adapters, REHEARSAL_INPUT_PARAMETER, counts, failures)
        return resolve(
            RehearsalLaunchOutcome.STALE_RELEASE,
            RehearsalTaskState.STOPPED if stopped else RehearsalTaskState.STARTED_NOT_TERMINAL,
            task_id=task_id,
        )
    # Observe to the terminal state.
    terminal: TaskDescription | None = None
    while not exhausted():
        reads += 1
        counts["describe"] += 1
        try:
            current = adapters.ecs.describe_task(task_arn)
        except ComputeError:
            break
        if current.stopped:
            terminal = current
            break
        sleep(OBSERVATION_POLL_SECONDS)
    _delete(adapters, REHEARSAL_RELEASE_PARAMETER, counts, failures)
    _delete(adapters, REHEARSAL_INPUT_PARAMETER, counts, failures)
    outcome = (
        RehearsalLaunchOutcome.LAUNCHED
        if terminal is not None
        else RehearsalLaunchOutcome.OBSERVATION_EXHAUSTED
    )
    exit_code = None
    if terminal is not None and terminal.exit_codes and terminal.exit_codes[0] is not None:
        exit_code = terminal.exit_codes[0]
    record = RehearsalLaunchRecord(
        identity=identity,
        subcell_id=statement.subcell_id,
        statement_sha256=statement.digest,
        authorization_sha256=authorization_sha256,
        specification_sha256=compiled.digest,
        reservation_sha256=reservation.digest,
        outcome=outcome,
        task_arn=task_arn,
        task_definition_arn=revision,
        image_digest=inputs.image_digest,
        input_digest=sha256_hex(input_bytes),
        network_interface_id=interface_id,
        subnet_id=inputs.subnet_id,
        security_group_ids=tuple(inputs.security_group_ids),
        observed_exit_code=exit_code,
        launched_at=launched_at,
        recorded_at=now(),
        binding=statement.binding,
    )
    store.write_record("rehearsal-launch-record", record.document(), at=record.recorded_at)
    return resolve(
        outcome,
        RehearsalTaskState.OBSERVED_TERMINAL
        if terminal is not None
        else RehearsalTaskState.STARTED_NOT_TERMINAL,
        task_id=task_id,
        record=record,
    )


def _stop(
    adapters: RehearsalLaunchAdapters,
    task_arn: str,
    reason: str,
    counts: dict[str, int],
    failures: list[str],
) -> bool:
    """Stop the task; whether the stop was acknowledged (a failure is reported, not hidden)."""
    counts["stop"] += 1
    try:
        adapters.ecs.stop_task(task_arn, reason=reason)
    except ComputeError as error:
        failures.append(f"stop_task:{error.failure.value}")
        return False
    return True


def _delete(
    adapters: RehearsalLaunchAdapters, name: str, counts: dict[str, int], failures: list[str]
) -> None:
    counts["delete"] += 1
    try:
        adapters.parameters.delete_parameter(name)
    except ParameterError as error:
        if error.failure is not ParameterFailure.NOT_FOUND:
            failures.append(f"delete_parameter:{error.failure.value}")


# ---------------------------------------------------------------------------
# The retained receipt, and the one evidence-binding rule (correction 1)
# ---------------------------------------------------------------------------

_RECEIPT_EVIDENCE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "identity",
        "subcell_id",
        "statement_sha256",
        "launch_record_sha256",
        "receipt",
        "received_at",
        "binding",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalReceiptEvidence:
    """One rehearsal launch's verified receipt, retained beside its record: the decoded
    document exactly as verified, bound to the launch record by digest. Re-verified on
    every read, never chosen among candidates."""

    identity: str
    subcell_id: str
    statement_sha256: str
    launch_record_sha256: str
    receipt: dict[str, Any]
    received_at: datetime
    binding: PermissionBinding

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": REHEARSAL_RECEIPT_EVIDENCE_CONTRACT_ID,
            "identity": self.identity,
            "subcell_id": self.subcell_id,
            "statement_sha256": self.statement_sha256,
            "launch_record_sha256": self.launch_record_sha256,
            "receipt": self.receipt,
            "received_at": self.received_at.isoformat(),
            "binding": self.binding.document(),
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.document()))

    def __repr__(self) -> str:
        return f"RehearsalReceiptEvidence(subcell={self.subcell_id!r})"


def parse_rehearsal_receipt_evidence(raw: object) -> RehearsalReceiptEvidence:
    document = raw if type(raw) is dict else _decode(raw)
    if type(document) is not dict or set(document) != _RECEIPT_EVIDENCE_FIELDS:
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    if (
        document["schema_version"] != RECORD_SCHEMA_VERSION
        or document["contract_id"] != REHEARSAL_RECEIPT_EVIDENCE_CONTRACT_ID
    ):
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    identity = exact_str(document["identity"])
    subcell = exact_str(document["subcell_id"])
    statement = hex_digest(document["statement_sha256"])
    launch = hex_digest(document["launch_record_sha256"])
    received = instant(document["received_at"])
    receipt = document["receipt"]
    if (
        identity is None
        or subcell not in REHEARSAL_SEQUENCE
        or statement is None
        or launch is None
        or received is None
        or type(receipt) is not dict
    ):
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED)
    try:
        binding = _binding_from(document["binding"])
    except Exception:
        raise _refuse(RehearsalLaunchDefect.RECORD_MALFORMED) from None
    return RehearsalReceiptEvidence(
        identity=identity,
        subcell_id=subcell,
        statement_sha256=str(statement),
        launch_record_sha256=str(launch),
        receipt=dict(receipt),
        received_at=received,
        binding=binding,
    )


class RehearsalBindingDefect(StrEnum):
    """Why a rehearsal result does not bind to its evidence. Closed; value-free."""

    CONSUMPTION_MISSING = "CONSUMPTION_MISSING"
    CONSUMPTION_CONFLICTS = "CONSUMPTION_CONFLICTS"
    RESERVATION_MISSING = "RESERVATION_MISSING"
    RESERVATION_CONFLICTS = "RESERVATION_CONFLICTS"
    SPECIFICATION_MISMATCH = "SPECIFICATION_MISMATCH"
    LAUNCH_MISSING = "LAUNCH_MISSING"
    LAUNCH_CONFLICTS = "LAUNCH_CONFLICTS"
    LAUNCH_NOT_TERMINAL = "LAUNCH_NOT_TERMINAL"
    RECEIPT_MISSING = "RECEIPT_MISSING"
    RECEIPT_CONFLICTS = "RECEIPT_CONFLICTS"
    RECEIPT_REFUSED = "RECEIPT_REFUSED"
    RESULT_CONTRADICTS = "RESULT_CONTRADICTS"
    TARGET_MISMATCH = "TARGET_MISMATCH"
    IDENTITY_NOT_VERIFIED = "IDENTITY_NOT_VERIFIED"


class RehearsalBindingError(ValueError):
    def __init__(self, defect: RehearsalBindingDefect) -> None:
        super().__init__(defect.value)
        self.defect = defect


@dataclass(frozen=True, slots=True, kw_only=True)
class BoundRehearsal:
    """One rehearsal result bound as a chain to every piece of evidence it rests on."""

    record: RehearsalRecord
    reservation: RehearsalReservation
    launch: RehearsalLaunchRecord
    receipt: RehearsalReceiptEvidence

    def __repr__(self) -> str:
        return f"BoundRehearsal(subcell={self.record.subcell_id!r})"


def _one(
    items: list[Any], missing: RehearsalBindingDefect, conflicts: RehearsalBindingDefect
) -> Any:
    if not items:
        raise RehearsalBindingError(missing)
    first = items[0]
    if any(item != first for item in items[1:]):
        raise RehearsalBindingError(conflicts)
    return first


def bind_rehearsal_result(
    record: RehearsalRecord,
    *,
    target: RehearsalTarget,
    consumptions: Mapping[str, bytes],
    reservations: Iterable[RehearsalReservation],
    launches: Iterable[RehearsalLaunchRecord],
    receipts: Iterable[RehearsalReceiptEvidence],
) -> BoundRehearsal:
    """The one rule under which a rehearsal record qualifies as a result -- applied by the
    completion before it writes, and by the prerequisite admission before `R8-GET`'s PASS
    admits `R8-LIST-AND-DELETE` (correction 1).

    The record binds only when every link exists exactly once and agrees: the
    authorization consumed beside the ledger (its consumption document naming this subcell
    and statement); the reservation anchored beside the ledger for the record's stamp,
    statement and authorization; the launch record of that identity, LAUNCHED and observed
    terminal, naming that reservation by digest and the reservation's own specification;
    the retained receipt bound to that launch record by digest, re-verified against the
    launch's expectation, REHEARSED, with the exit the launcher observed, and establishing
    exactly what the record says (classes, outcome, flags, counts, statement, authorization,
    target, stamp, a verified identity); and the record's target equal to ``target`` -- the
    exact object the caller is deciding about. Missing, substituted, duplicated or
    conflicting evidence refuses; nothing is chosen among candidates.
    """
    identity = rehearsal_identity(record.stamp)
    if record.target != target:
        raise RehearsalBindingError(RehearsalBindingDefect.TARGET_MISMATCH)
    if not record.identity_verified:
        raise RehearsalBindingError(RehearsalBindingDefect.IDENTITY_NOT_VERIFIED)
    consumed = consumptions.get(record.authorization_sha256)
    if consumed is None:
        raise RehearsalBindingError(RehearsalBindingDefect.CONSUMPTION_MISSING)
    try:
        consumption = decode_document(consumed, max_bytes=MAX_PERMISSION_RECORD_BYTES)
    except Exception:
        raise RehearsalBindingError(RehearsalBindingDefect.CONSUMPTION_CONFLICTS) from None
    if (
        consumption.get("subcell_id") != record.subcell_id
        or consumption.get("statement_sha256") != record.statement_sha256
    ):
        raise RehearsalBindingError(RehearsalBindingDefect.CONSUMPTION_CONFLICTS)
    reservation: RehearsalReservation = _one(
        [
            r
            for r in reservations
            if r.identity == identity
            and r.statement_sha256 == record.statement_sha256
            and r.authorization_sha256 == record.authorization_sha256
            and r.subcell_id == record.subcell_id
        ],
        RehearsalBindingDefect.RESERVATION_MISSING,
        RehearsalBindingDefect.RESERVATION_CONFLICTS,
    )
    launch: RehearsalLaunchRecord = _one(
        [
            launch
            for launch in launches
            if launch.identity == identity
            and launch.statement_sha256 == record.statement_sha256
            and launch.authorization_sha256 == record.authorization_sha256
        ],
        RehearsalBindingDefect.LAUNCH_MISSING,
        RehearsalBindingDefect.LAUNCH_CONFLICTS,
    )
    if (
        launch.reservation_sha256 != reservation.digest
        or launch.specification_sha256 != reservation.specification_sha256
        or launch.task_definition_arn != reservation.specification.inputs.task_definition_arn
        or launch.image_digest != reservation.specification.inputs.image_digest
        or launch.binding != record.binding
    ):
        raise RehearsalBindingError(RehearsalBindingDefect.SPECIFICATION_MISMATCH)
    if launch.outcome is not RehearsalLaunchOutcome.LAUNCHED or launch.observed_exit_code is None:
        raise RehearsalBindingError(RehearsalBindingDefect.LAUNCH_NOT_TERMINAL)
    receipt: RehearsalReceiptEvidence = _one(
        [
            evidence
            for evidence in receipts
            if evidence.launch_record_sha256 == launch.digest and evidence.identity == identity
        ],
        RehearsalBindingDefect.RECEIPT_MISSING,
        RehearsalBindingDefect.RECEIPT_CONFLICTS,
    )
    if receipt.statement_sha256 != record.statement_sha256 or receipt.binding != record.binding:
        raise RehearsalBindingError(RehearsalBindingDefect.RECEIPT_CONFLICTS)
    try:
        established = complete_rehearsal(
            launch,
            receipt.receipt,
            statement=RehearsalStatement(
                subcell_id=record.subcell_id,
                target=record.target,
                stamp=record.stamp,
                binding=record.binding,
            ),
        )
    except RehearsalCompletionError:
        raise RehearsalBindingError(RehearsalBindingDefect.RECEIPT_REFUSED) from None
    if established.document() != record.document():
        raise RehearsalBindingError(RehearsalBindingDefect.RESULT_CONTRADICTS)
    return BoundRehearsal(record=record, reservation=reservation, launch=launch, receipt=receipt)


# ---------------------------------------------------------------------------
# Completion: the rehearsal record from the verified receipt
# ---------------------------------------------------------------------------


class RehearsalCompletionDefect(StrEnum):
    """Why a receipt does not complete a launch. Closed."""

    LAUNCH_NOT_TERMINAL = "LAUNCH_NOT_TERMINAL"
    RECEIPT_REFUSED = "RECEIPT_REFUSED"
    EXIT_CONTRADICTS = "EXIT_CONTRADICTS"
    TASK_REFUSED = "TASK_REFUSED"
    STATEMENT_CONTRADICTS = "STATEMENT_CONTRADICTS"
    IDENTITY_NOT_VERIFIED = "IDENTITY_NOT_VERIFIED"


class RehearsalCompletionError(ValueError):
    def __init__(self, defect: RehearsalCompletionDefect) -> None:
        super().__init__(defect.value)
        self.defect = defect


def complete_rehearsal(
    launch: RehearsalLaunchRecord,
    receipt_document: object,
    *,
    statement: RehearsalStatement,
) -> RehearsalRecord:
    """The rehearsal record one launch established, from its verified receipt.

    The launch must have been observed to its terminal state; the receipt must verify
    against the launch record's expectation (task, revision, image, identity, input,
    statement, authorization), report the exit the launcher observed, be a REHEARSED
    receipt (a task that refused established nothing and completes nothing), carry the
    statement's own subcell, target and stamp, and say the task proved its identity.
    The record is rebuilt under the launch's binding; the receipt supplies classes and
    counts only.
    """
    if launch.outcome is not RehearsalLaunchOutcome.LAUNCHED or launch.observed_exit_code is None:
        raise RehearsalCompletionError(RehearsalCompletionDefect.LAUNCH_NOT_TERMINAL)
    if statement.digest != launch.statement_sha256:
        raise RehearsalCompletionError(RehearsalCompletionDefect.STATEMENT_CONTRADICTS)
    try:
        verified = verify_rehearsal_receipt(receipt_document, expectation=launch.expectation())
    except RehearsalContractError:
        raise RehearsalCompletionError(RehearsalCompletionDefect.RECEIPT_REFUSED) from None
    if verified.exit_code != launch.observed_exit_code:
        raise RehearsalCompletionError(RehearsalCompletionDefect.EXIT_CONTRADICTS)
    if verified.outcome is not RehearsalTaskOutcome.REHEARSED or verified.block is None:
        raise RehearsalCompletionError(RehearsalCompletionDefect.TASK_REFUSED)
    block = verified.block
    target = block["target"]
    if (
        block["subcell_id"] != statement.subcell_id
        or block["stamp"] != statement.stamp
        or target != statement.target.document()
    ):
        raise RehearsalCompletionError(RehearsalCompletionDefect.STATEMENT_CONTRADICTS)
    if block["identity_verified"] is not True:
        raise RehearsalCompletionError(RehearsalCompletionDefect.IDENTITY_NOT_VERIFIED)
    return RehearsalRecord(
        subcell_id=statement.subcell_id,
        statement_sha256=launch.statement_sha256,
        authorization_sha256=launch.authorization_sha256,
        target=RehearsalTarget(
            bucket=str(target["bucket"]),
            key=str(target["key"]),
            prerequisite_sha256=str(target["prerequisite_sha256"]),
        ),
        observed=tuple(ObservedClass(str(o)) for o in block["observed"]),
        outcome=RehearsalOutcome(str(block["outcome"])),
        deleted=bool(block["deleted"]),
        possibly_deleted=bool(block["possibly_deleted"]),
        operations=int(block["operations"]),
        identity_verified=True,
        stamp=statement.stamp,
        started_at=launch.launched_at,
        finished_at=launch.recorded_at,
        binding=launch.binding,
    )


__all__ = [
    "MAX_OBSERVATION_READS",
    "OBSERVATION_CEILING_SECONDS",
    "OBSERVATION_POLL_SECONDS",
    "RECOVERED_INTERRUPTED",
    "REHEARSAL_LAUNCH_INPUTS_CONTRACT_ID",
    "REHEARSAL_LAUNCH_RECORD_CONTRACT_ID",
    "REHEARSAL_RECEIPT_EVIDENCE_CONTRACT_ID",
    "REHEARSAL_RESERVATIONS_ANCHOR",
    "REHEARSAL_RESERVATION_CONTRACT_ID",
    "REHEARSAL_RESOLUTIONS_ANCHOR",
    "REHEARSAL_RESOLUTION_CONTRACT_ID",
    "REHEARSAL_STARTED_BY_PREFIX",
    "STOP_REASON_MISPLACED",
    "STOP_REASON_STALE_RELEASE",
    "BoundRehearsal",
    "CompiledRehearsalLaunch",
    "RehearsalBindingDefect",
    "RehearsalBindingError",
    "RehearsalCompletionDefect",
    "RehearsalCompletionError",
    "RehearsalEcs",
    "RehearsalLaunchAdapters",
    "RehearsalLaunchDefect",
    "RehearsalLaunchError",
    "RehearsalLaunchInputs",
    "RehearsalLaunchOutcome",
    "RehearsalLaunchRecord",
    "RehearsalLaunchReport",
    "RehearsalReceiptEvidence",
    "RehearsalReservation",
    "RehearsalResolution",
    "RehearsalTaskState",
    "UnsettledRehearsal",
    "bind_rehearsal_result",
    "complete_rehearsal",
    "launch_rehearsal",
    "parse_compiled_rehearsal_launch",
    "parse_rehearsal_launch_inputs",
    "parse_rehearsal_launch_record",
    "parse_rehearsal_receipt_evidence",
    "parse_rehearsal_reservation",
    "parse_rehearsal_resolution",
    "recover_rehearsal_launch",
    "rehearsal_launcher_identity_verified",
    "rehearsal_reservations",
    "rehearsal_resolutions",
    "unsettled_rehearsals",
]
