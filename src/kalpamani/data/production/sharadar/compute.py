"""The compute adapters: one task launch, task description, interface description.

The launch tool touches ECS for exactly three operations -- ``RunTask``,
``DescribeTasks`` and ``StopTask`` -- and EC2 for one, ``DescribeNetworkInterfaces``
(ADR-0036 §2.9). Each adapter here takes an injected client-shaped object,
constructs the exact request the ADR prescribes, and reduces the response to the
documented fields the launch tool reads and nothing else.

**The request shape is the preventive control.** :func:`run_task_request` sends
``count = 1``, the compiled task-definition revision, the one cluster, the
compiled per-actor subnet, security groups and public-IP setting, and **no
``overrides`` key at all** -- no command, no environment, no role. A test asserts
the exact keyword set, so an override cannot be added without the test naming it.

These adapters have only ever been exercised against synthetic fakes. **No AWS
request has been sent through them**, and nothing here constructs a client.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol

from kalpamani.data.production.sharadar.release import (
    NETWORK_INTERFACE_ID_RE,
    SUBNET_ID_RE,
    TASK_ARN_RE,
    TASK_DEFINITION_ARN_RE,
)
from kalpamani.data.production.sharadar.vocabulary import (
    EXPECTED_PARTITION,
    EXPECTED_REGION,
    ProductionActor,
    constants_for,
)


class ComputeOperation(StrEnum):
    """What the adapter was doing when it refused."""

    RUN_TASK = "RUN_TASK"
    DESCRIBE_TASKS = "DESCRIBE_TASKS"
    STOP_TASK = "STOP_TASK"
    DESCRIBE_NETWORK_INTERFACES = "DESCRIBE_NETWORK_INTERFACES"


class ComputeFailure(StrEnum):
    """Why a compute operation refused. Closed and coarse."""

    ACCESS_DENIED = "ACCESS_DENIED"
    NOT_FOUND = "NOT_FOUND"
    THROTTLED = "THROTTLED"
    TRANSIENT = "TRANSIENT"
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    UNKNOWN = "UNKNOWN"


class ComputeError(Exception):
    """A refusal built from two closed vocabulary members and nothing else."""

    __slots__ = ("failure", "operation")

    def __init__(self, *, operation: ComputeOperation, failure: ComputeFailure) -> None:
        """Carry an operation and a failure category."""
        if type(operation) is not ComputeOperation or type(failure) is not ComputeFailure:
            raise TypeError("operation and failure must be exact members")
        self.operation = operation
        self.failure = failure
        super().__init__(f"compute {operation.value}: {failure.value}")


def _refuse(operation: ComputeOperation, failure: ComputeFailure) -> ComputeError:
    return ComputeError(operation=operation, failure=failure)


_DENIED_CODES: Final[frozenset[str]] = frozenset(
    {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}
)
_NOT_FOUND_CODES: Final[frozenset[str]] = frozenset(
    {"ClusterNotFoundException", "InvalidNetworkInterfaceID.NotFound", "ResourceNotFoundException"}
)
_THROTTLED_CODES: Final[frozenset[str]] = frozenset(
    {"ThrottlingException", "Throttling", "RequestLimitExceeded", "TooManyRequestsException"}
)
_TRANSIENT_CODES: Final[frozenset[str]] = frozenset(
    {"ServerException", "InternalError", "ServiceUnavailable", "RequestTimeout"}
)
_INVALID_CODES: Final[frozenset[str]] = frozenset(
    {"InvalidParameterException", "ClientException", "InvalidParameterValue", "ValidationError"}
)


def _error_code(exception: BaseException) -> str:
    try:
        response = getattr(exception, "response", None)
        if not isinstance(response, Mapping):
            return ""
        error = response.get("Error")
        if not isinstance(error, Mapping):
            return ""
        code = error.get("Code")
        return code if type(code) is str else ""
    except Exception:
        return ""


def classify_compute_failure(exception: BaseException) -> ComputeFailure:
    """Reduce a backend exception to one closed category. Nothing survives it."""
    code = _error_code(exception)
    if code in _DENIED_CODES:
        return ComputeFailure.ACCESS_DENIED
    if code in _NOT_FOUND_CODES:
        return ComputeFailure.NOT_FOUND
    if code in _THROTTLED_CODES:
        return ComputeFailure.THROTTLED
    if code in _TRANSIENT_CODES:
        return ComputeFailure.TRANSIENT
    if code in _INVALID_CODES:
        return ComputeFailure.INVALID_REQUEST
    return ComputeFailure.UNKNOWN


#: Identifier grammars the compiled launch is held to.
CLUSTER_ARN_RE: Final = re.compile(
    rf"arn:{EXPECTED_PARTITION}:ecs:{EXPECTED_REGION}:([0-9]{{12}}):cluster/([A-Za-z0-9_-]{{1,255}})"
)
ROLE_ARN_RE: Final = re.compile(
    rf"arn:{EXPECTED_PARTITION}:iam::([0-9]{{12}}):role/([A-Za-z0-9+=,.@_/-]{{1,512}})"
)
SECURITY_GROUP_ID_RE: Final = re.compile(r"sg-[0-9a-f]{8,17}")
KMS_KEY_ARN_RE: Final = re.compile(
    rf"arn:{EXPECTED_PARTITION}:kms:{EXPECTED_REGION}:([0-9]{{12}}):key/[0-9a-f-]{{36}}"
)
PLATFORM_VERSION_RE: Final = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+|LATEST")

#: The one launch type. A production task is never EC2-hosted.
LAUNCH_TYPE: Final = "FARGATE"


@dataclass(frozen=True, slots=True, kw_only=True)
class CompiledLaunch:
    """Everything the launch tool compiles for one actor's launch. All constants.

    The task-definition ARN is the **exact revision** Terraform recorded; the
    subnet, security groups and public-IP setting are the per-actor network
    matrix of ADR-0036 §2.8 -- a public IP for the acquisition task, none for the
    build task. A compiled launch that breaks its own actor's rules refuses to
    exist.
    """

    actor: ProductionActor
    cluster_arn: str
    task_definition_arn: str
    task_role_arn: str
    execution_role_arn: str
    subnet_id: str
    security_group_ids: tuple[str, ...]
    assign_public_ip: bool
    platform_version: str
    binding_key_arn: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("CompiledLaunch may not be subclassed")

    def __post_init__(self) -> None:
        """Hold every constant to its grammar and to the actor's rules."""
        if type(self.actor) is not ProductionActor:
            raise ValueError("actor must be an exact ProductionActor member")
        constants = constants_for(self.actor)
        cluster = CLUSTER_ARN_RE.fullmatch(self.cluster_arn or "")
        definition = TASK_DEFINITION_ARN_RE.fullmatch(self.task_definition_arn or "")
        task_role = ROLE_ARN_RE.fullmatch(self.task_role_arn or "")
        execution_role = ROLE_ARN_RE.fullmatch(self.execution_role_arn or "")
        if cluster is None or definition is None or task_role is None or execution_role is None:
            raise ValueError("a compiled ARN does not match its grammar")
        if definition.group(2) != constants.task_family:
            raise ValueError("the compiled task definition is not this actor's family")
        if task_role.group(2) != constants.task_role_name:
            raise ValueError("the compiled task role is not this actor's task role")
        accounts = {
            cluster.group(1),
            definition.group(1),
            task_role.group(1),
            execution_role.group(1),
        }
        if len(accounts) != 1:
            raise ValueError("compiled ARNs name more than one account")
        if not SUBNET_ID_RE.fullmatch(self.subnet_id or ""):
            raise ValueError("the compiled subnet id does not match its grammar")
        if type(self.security_group_ids) is not tuple or not self.security_group_ids:
            raise ValueError("at least one compiled security group is required")
        if any(not SECURITY_GROUP_ID_RE.fullmatch(group) for group in self.security_group_ids):
            raise ValueError("a compiled security group id does not match its grammar")
        if type(self.assign_public_ip) is not bool:
            raise ValueError("assign_public_ip must be a bool")
        expected_public = self.actor is ProductionActor.ACQUISITION
        if self.assign_public_ip is not expected_public:
            raise ValueError("the public-IP setting contradicts the actor's network matrix")
        if not PLATFORM_VERSION_RE.fullmatch(self.platform_version or "") or (
            self.platform_version == "LATEST"
        ):
            raise ValueError("the platform version must be pinned")
        if not KMS_KEY_ARN_RE.fullmatch(self.binding_key_arn or ""):
            raise ValueError("the compiled binding key ARN does not match its grammar")

    def __repr__(self) -> str:
        """The actor only. **Never an ARN or an identifier.**"""
        return f"CompiledLaunch(actor={self.actor.value!r})"

    @property
    def cluster_name(self) -> str:
        """The cluster's name segment, for matching a task ARN's cluster."""
        match = CLUSTER_ARN_RE.fullmatch(self.cluster_arn)
        assert match is not None
        return match.group(2)


def run_task_request(compiled: CompiledLaunch) -> dict[str, Any]:
    """The exact ``RunTask`` keyword arguments, and **no ``overrides`` key**."""
    if type(compiled) is not CompiledLaunch:
        raise _refuse(ComputeOperation.RUN_TASK, ComputeFailure.INVALID_CONFIGURATION)
    return {
        "cluster": compiled.cluster_arn,
        "taskDefinition": compiled.task_definition_arn,
        "count": 1,
        "launchType": LAUNCH_TYPE,
        "platformVersion": compiled.platform_version,
        "networkConfiguration": {
            "awsvpcConfiguration": {
                "subnets": [compiled.subnet_id],
                "securityGroups": list(compiled.security_group_ids),
                "assignPublicIp": "ENABLED" if compiled.assign_public_ip else "DISABLED",
            }
        },
        "enableExecuteCommand": False,
    }


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskAttachment:
    """The documented fields of one ``ElasticNetworkInterface`` attachment."""

    status: str
    network_interface_id: str | None
    subnet_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskDescription:
    """The documented fields of one ``DescribeTasks`` entry the launch tool reads."""

    task_arn: str
    task_definition_arn: str
    last_status: str
    attachment: TaskAttachment | None
    exit_codes: tuple[int | None, ...]

    def __repr__(self) -> str:
        """Status only. **Never an ARN.**"""
        return f"TaskDescription(last_status={self.last_status!r})"

    @property
    def stopped(self) -> bool:
        """Whether the task reached the one terminal status."""
        return self.last_status == "STOPPED"


@dataclass(frozen=True, slots=True, kw_only=True)
class InterfaceDescription:
    """The documented fields of one ``DescribeNetworkInterfaces`` entry."""

    network_interface_id: str
    subnet_id: str | None
    security_group_ids: frozenset[str]
    public_ip_present: bool

    def __repr__(self) -> str:
        """Counts and one flag. **Never an identifier.**"""
        return (
            f"InterfaceDescription(groups={len(self.security_group_ids)}, "
            f"public_ip={self.public_ip_present})"
        )


class EcsLikeClient(Protocol):
    """The three ECS operations the launch tool uses."""

    def run_task(self, **kwargs: Any) -> Any:
        """Start tasks."""
        ...

    def describe_tasks(self, **kwargs: Any) -> Any:
        """Describe tasks."""
        ...

    def stop_task(self, **kwargs: Any) -> Any:
        """Stop one task."""
        ...


class Ec2LikeClient(Protocol):
    """The one EC2 operation the launch tool uses."""

    def describe_network_interfaces(self, **kwargs: Any) -> Any:
        """Describe network interfaces."""
        ...


def _parse_task(entry: object, *, cluster_name: str) -> TaskDescription:
    if not isinstance(entry, Mapping):
        raise _refuse(ComputeOperation.DESCRIBE_TASKS, ComputeFailure.INVALID_RESPONSE)
    task_arn = entry.get("taskArn")
    definition = entry.get("taskDefinitionArn")
    status = entry.get("lastStatus")
    if type(task_arn) is not str or not TASK_ARN_RE.fullmatch(task_arn):
        raise _refuse(ComputeOperation.DESCRIBE_TASKS, ComputeFailure.INVALID_RESPONSE)
    if TASK_ARN_RE.fullmatch(task_arn).group(2) != cluster_name:  # type: ignore[union-attr]
        raise _refuse(ComputeOperation.DESCRIBE_TASKS, ComputeFailure.INVALID_RESPONSE)
    if type(definition) is not str or not TASK_DEFINITION_ARN_RE.fullmatch(definition):
        raise _refuse(ComputeOperation.DESCRIBE_TASKS, ComputeFailure.INVALID_RESPONSE)
    if type(status) is not str or not status:
        raise _refuse(ComputeOperation.DESCRIBE_TASKS, ComputeFailure.INVALID_RESPONSE)

    attachment: TaskAttachment | None = None
    raw_attachments = entry.get("attachments")
    if isinstance(raw_attachments, list):
        for raw in raw_attachments:
            if not isinstance(raw, Mapping) or raw.get("type") != "ElasticNetworkInterface":
                continue
            details = raw.get("details")
            values: dict[str, str] = {}
            if isinstance(details, list):
                for detail in details:
                    if isinstance(detail, Mapping):
                        name, value = detail.get("name"), detail.get("value")
                        if type(name) is str and type(value) is str:
                            values[name] = value
            attachment_status = raw.get("status")
            interface = values.get("networkInterfaceId")
            subnet = values.get("subnetId")
            attachment = TaskAttachment(
                status=attachment_status if type(attachment_status) is str else "",
                network_interface_id=(
                    interface
                    if interface and NETWORK_INTERFACE_ID_RE.fullmatch(interface)
                    else None
                ),
                subnet_id=subnet if subnet and SUBNET_ID_RE.fullmatch(subnet) else None,
            )
            break

    exit_codes: list[int | None] = []
    containers = entry.get("containers")
    if isinstance(containers, list):
        for container in containers:
            code = container.get("exitCode") if isinstance(container, Mapping) else None
            exit_codes.append(code if type(code) is int else None)
    return TaskDescription(
        task_arn=task_arn,
        task_definition_arn=definition,
        last_status=status,
        attachment=attachment,
        exit_codes=tuple(exit_codes),
    )


class EcsTaskAdapter:
    """``RunTask`` once, ``DescribeTasks`` and ``StopTask`` on one task, over an injected client."""

    __slots__ = ("_compiled", "_ecs", "describe_count", "run_count", "stop_count")

    def __init__(self, *, ecs: EcsLikeClient, compiled: CompiledLaunch) -> None:
        """Bind an injected client-shaped object and one compiled launch."""
        for method in ("run_task", "describe_tasks", "stop_task"):
            if not callable(getattr(ecs, method, None)):
                raise _refuse(ComputeOperation.RUN_TASK, ComputeFailure.INVALID_CONFIGURATION)
        if type(compiled) is not CompiledLaunch:
            raise _refuse(ComputeOperation.RUN_TASK, ComputeFailure.INVALID_CONFIGURATION)
        self._ecs = ecs
        self._compiled = compiled
        self.run_count = 0
        self.describe_count = 0
        self.stop_count = 0

    def run_task(self) -> str:
        """Start **one** task with the compiled request; the task ARN it returns.

        A response that reports a failure entry, more or fewer than one task, or a
        task ARN outside the compiled cluster is ``INVALID_RESPONSE``: the tool
        refuses to proceed with a task it cannot identify exactly.
        """
        self.run_count += 1
        try:
            response = self._ecs.run_task(**run_task_request(self._compiled))
        except Exception as exception:
            raise _refuse(ComputeOperation.RUN_TASK, classify_compute_failure(exception)) from None
        if not isinstance(response, Mapping):
            raise _refuse(ComputeOperation.RUN_TASK, ComputeFailure.INVALID_RESPONSE)
        failures = response.get("failures")
        tasks = response.get("tasks")
        if (
            (isinstance(failures, list) and failures)
            or not isinstance(tasks, list)
            or len(tasks) != 1
        ):
            raise _refuse(ComputeOperation.RUN_TASK, ComputeFailure.INVALID_RESPONSE)
        try:
            described = _parse_task(tasks[0], cluster_name=self._compiled.cluster_name)
        except ComputeError:
            raise _refuse(ComputeOperation.RUN_TASK, ComputeFailure.INVALID_RESPONSE) from None
        return described.task_arn

    def describe_task(self, task_arn: str) -> TaskDescription:
        """``DescribeTasks`` on exactly this one task."""
        self.describe_count += 1
        try:
            response = self._ecs.describe_tasks(
                cluster=self._compiled.cluster_arn, tasks=[task_arn]
            )
        except Exception as exception:
            raise _refuse(
                ComputeOperation.DESCRIBE_TASKS, classify_compute_failure(exception)
            ) from None
        tasks = response.get("tasks") if isinstance(response, Mapping) else None
        if not isinstance(tasks, list) or len(tasks) != 1:
            raise _refuse(ComputeOperation.DESCRIBE_TASKS, ComputeFailure.INVALID_RESPONSE)
        described = _parse_task(tasks[0], cluster_name=self._compiled.cluster_name)
        if described.task_arn != task_arn:
            raise _refuse(ComputeOperation.DESCRIBE_TASKS, ComputeFailure.INVALID_RESPONSE)
        return described

    def stop_task(self, task_arn: str, *, reason: str) -> None:
        """``StopTask`` on exactly this one task, with a closed reason token."""
        self.stop_count += 1
        try:
            self._ecs.stop_task(cluster=self._compiled.cluster_arn, task=task_arn, reason=reason)
        except Exception as exception:
            raise _refuse(ComputeOperation.STOP_TASK, classify_compute_failure(exception)) from None


class Ec2InterfaceAdapter:
    """``DescribeNetworkInterfaces`` on exactly one interface, over an injected client."""

    __slots__ = ("_ec2", "describe_count")

    def __init__(self, *, ec2: Ec2LikeClient) -> None:
        """Bind an injected client-shaped object."""
        if not callable(getattr(ec2, "describe_network_interfaces", None)):
            raise _refuse(
                ComputeOperation.DESCRIBE_NETWORK_INTERFACES, ComputeFailure.INVALID_CONFIGURATION
            )
        self._ec2 = ec2
        self.describe_count = 0

    def describe_interface(self, network_interface_id: str) -> InterfaceDescription:
        """The documented fields of one interface: subnet, groups, public-IP association."""
        operation = ComputeOperation.DESCRIBE_NETWORK_INTERFACES
        if not NETWORK_INTERFACE_ID_RE.fullmatch(network_interface_id or ""):
            raise _refuse(operation, ComputeFailure.INVALID_REQUEST)
        self.describe_count += 1
        try:
            response = self._ec2.describe_network_interfaces(
                NetworkInterfaceIds=[network_interface_id]
            )
        except Exception as exception:
            raise _refuse(operation, classify_compute_failure(exception)) from None
        interfaces = response.get("NetworkInterfaces") if isinstance(response, Mapping) else None
        if not isinstance(interfaces, list) or len(interfaces) != 1:
            raise _refuse(operation, ComputeFailure.INVALID_RESPONSE)
        entry = interfaces[0]
        if (
            not isinstance(entry, Mapping)
            or entry.get("NetworkInterfaceId") != network_interface_id
        ):
            raise _refuse(operation, ComputeFailure.INVALID_RESPONSE)
        groups = entry.get("Groups")
        if not isinstance(groups, list):
            raise _refuse(operation, ComputeFailure.INVALID_RESPONSE)
        group_ids: set[str] = set()
        for group in groups:
            group_id = group.get("GroupId") if isinstance(group, Mapping) else None
            if type(group_id) is not str or not SECURITY_GROUP_ID_RE.fullmatch(group_id):
                raise _refuse(operation, ComputeFailure.INVALID_RESPONSE)
            group_ids.add(group_id)
        subnet = entry.get("SubnetId")
        association = entry.get("Association")
        public_ip = association.get("PublicIp") if isinstance(association, Mapping) else None
        return InterfaceDescription(
            network_interface_id=network_interface_id,
            subnet_id=subnet if type(subnet) is str and SUBNET_ID_RE.fullmatch(subnet) else None,
            security_group_ids=frozenset(group_ids),
            public_ip_present=type(public_ip) is str and bool(public_ip),
        )


__all__ = [
    "CLUSTER_ARN_RE",
    "KMS_KEY_ARN_RE",
    "LAUNCH_TYPE",
    "PLATFORM_VERSION_RE",
    "ROLE_ARN_RE",
    "SECURITY_GROUP_ID_RE",
    "CompiledLaunch",
    "ComputeError",
    "ComputeFailure",
    "ComputeOperation",
    "Ec2InterfaceAdapter",
    "Ec2LikeClient",
    "EcsLikeClient",
    "EcsTaskAdapter",
    "InterfaceDescription",
    "TaskAttachment",
    "TaskDescription",
    "classify_compute_failure",
    "run_task_request",
]
