"""The permission-subcell client over SDK clients, shared by the workstation and the probe task.

One class implements :class:`~permission_cells.PermissionClient` over whatever SDK clients an
injected ``client_for(service)`` returns: the workstation tool hands in a profile-pinned
session's clients (ADR-0047), the probe task's entrypoint hands in the task's isolated,
container-credentialed clients restricted to the **one** service its subcell's operation
names (proposed ADR-0048). Every operation is one SDK call, classified into an
:class:`~r3_verification.Observation` by status, error code and the documented message
context, and the response body -- a secret's value, an object's bytes -- is **never read**.

The request shapes are the documented ones: a conditional ``PutObject`` with
``IfNoneMatch="*"``; ``ListObjectsV2`` with ``MaxKeys=1``; ``GetParameter`` with decryption
(a parameter the principal may not decrypt is a refusal, which is the point);
``PutParameter`` with ``Overwrite=False``; ``RunTask`` as the accepted launcher sends it
plus ``startedBy``; ``ListTasks`` by ``startedBy`` alone; ``ExecuteCommand`` with the
required ``interactive=True``. No SDK is imported anywhere in this module: backend errors are
classified structurally, as the platform classifies them everywhere.

**Mocked results are not AWS verification.** Every result in this repository's tests is an
intercepted transport's or a counting fake's.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

from kalpamani.data.production.sharadar.permission_cells import MAX_RETURNED_TASKS, Operation
from kalpamani.data.production.sharadar.r3_verification import Observation

#: The one service each operation is issued to.
OPERATION_SERVICE: Final[dict[Operation, str]] = {
    Operation.S3_PUT_CONDITIONAL: "s3",
    Operation.S3_GET: "s3",
    Operation.S3_LIST: "s3",
    Operation.S3_DELETE: "s3",
    Operation.SECRET_GET: "secretsmanager",
    Operation.SECRET_DESCRIBE: "secretsmanager",
    Operation.SSM_GET: "ssm",
    Operation.SSM_PUT: "ssm",
    Operation.ECS_RUN_TASK: "ecs",
    Operation.ECS_RUN_TASK_ROLE_OVERRIDE: "ecs",
    Operation.ECS_DESCRIBE_TASKS: "ecs",
    Operation.EC2_DESCRIBE_INTERFACES: "ec2",
    Operation.ECS_EXECUTE_COMMAND: "ecs",
}


class SdkPermissionClient:
    """Every permission operation over injected SDK clients. One call each.

    ``client_for`` returns the SDK client of one service name (``s3``, ``secretsmanager``,
    ``ssm``, ``ecs``); it is called lazily, once per service, so a subcell constructs
    only the service it uses. A factory that refuses a service (the probe task's, for any
    service but its operation's) makes that operation unissuable, which classifies as an
    exception -- ``AMBIGUOUS``, never a permission answer.
    """

    __slots__ = ("_client_for", "_clients")

    def __init__(self, client_for: Callable[[str], Any]) -> None:
        self._client_for = client_for
        self._clients: dict[str, Any] = {}

    def __repr__(self) -> str:
        return "SdkPermissionClient()"

    def _client(self, service: str) -> Any:
        if service not in self._clients:
            self._clients[service] = self._client_for(service)
        return self._clients[service]

    def _call(self, service: str, operation: str, **kwargs: Any) -> Observation:
        # Backend exceptions are classified structurally -- the SDK's ``ClientError``
        # carries ``response``; its transport errors are known by name -- so no module
        # under ``src/`` imports the SDK (the data platform stays free of it).
        try:
            response = getattr(self._client(service), operation)(**kwargs)
        except Exception as error:
            payload = getattr(error, "response", None)
            if isinstance(payload, dict):
                return Observation(
                    status=payload.get("ResponseMetadata", {}).get("HTTPStatusCode"),
                    code=str(payload.get("Error", {}).get("Code", "")),
                    message=str(payload.get("Error", {}).get("Message", "")),
                )
            name = type(error).__name__
            if name in ("ConnectTimeoutError", "ReadTimeoutError"):
                return Observation(status=None, transport_failure="timeout")
            if name == "EndpointConnectionError":
                return Observation(status=None, transport_failure="network")
            if name == "NoCredentialsError":
                return Observation(status=None, code="NoCredentialsError")
            return Observation(status=None, code="Exception")
        if not isinstance(response, dict):
            return Observation(status=None, code="InvalidResponse")
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if operation == "run_task":
            tasks = response.get("tasks") or []
            failures = response.get("failures") or []
            # Every returned task is accounted for, whatever the failure entries beside
            # it say: a task in the answer is a task that may be running. A 200 carrying
            # only failure entries started nothing it told us about; that is an
            # ambiguous launch (not a denial), and the cleanup lists by the tag.
            arns = tuple(
                str(task.get("taskArn", ""))
                for task in tasks[:MAX_RETURNED_TASKS]
                if str(task.get("taskArn", ""))
            )
            if not arns:
                return Observation(status=None, code="RunTaskFailureEntry", failures=len(failures))
            return Observation(status=status, task_arns=arns, failures=len(failures))
        if operation == "list_tasks":
            arns = tuple(str(arn) for arn in (response.get("taskArns") or [])[:MAX_RETURNED_TASKS])
            token = response.get("nextToken")
            return Observation(
                status=status,
                task_arns=arns,
                next_token=str(token) if isinstance(token, str) and token else None,
            )
        if operation == "describe_tasks":
            statuses = tuple(
                (str(task.get("taskArn", "")), str(task.get("lastStatus", "")))
                for task in (response.get("tasks") or [])[:MAX_RETURNED_TASKS]
            )
            return Observation(status=status, task_statuses=statuses)
        return Observation(status=status)

    def put_object(self, bucket: str, key: str, body: bytes, *, if_none_match: bool) -> Observation:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key, "Body": body}
        if if_none_match:
            kwargs["IfNoneMatch"] = "*"
        return self._call("s3", "put_object", **kwargs)

    def get_object(self, bucket: str, key: str) -> Observation:
        return self._call("s3", "get_object", Bucket=bucket, Key=key)

    def head_object(self, bucket: str, key: str) -> Observation:
        return self._call("s3", "head_object", Bucket=bucket, Key=key)

    def delete_object(self, bucket: str, key: str) -> Observation:
        return self._call("s3", "delete_object", Bucket=bucket, Key=key)

    def list_objects(self, bucket: str) -> Observation:
        return self._call("s3", "list_objects_v2", Bucket=bucket, MaxKeys=1)

    def get_secret_value(self, secret_id: str) -> Observation:
        # The value, if the service returns one, is never read: the response is
        # classified by status and dropped.
        return self._call("secretsmanager", "get_secret_value", SecretId=secret_id)

    def describe_secret(self, secret_id: str) -> Observation:
        return self._call("secretsmanager", "describe_secret", SecretId=secret_id)

    def get_parameter(self, name: str) -> Observation:
        return self._call("ssm", "get_parameter", Name=name, WithDecryption=True)

    def put_parameter(self, name: str, value: str) -> Observation:
        return self._call(
            "ssm", "put_parameter", Name=name, Value=value, Type="String", Overwrite=False
        )

    def run_task(
        self,
        *,
        cluster_arn: str,
        task_definition_arn: str,
        task_role_arn: str | None,
        started_by: str,
        subnet_id: str,
        security_group_ids: tuple[str, ...],
        assign_public_ip: bool,
        platform_version: str,
    ) -> Observation:
        # The same request shape the accepted launcher sends (compute.run_task_request):
        # FARGATE needs an awsvpc placement, and a request without one fails on its
        # parameters before any policy is evaluated -- not a permission test. The tag
        # lets the cleanup find a task an ambiguous answer may have started.
        kwargs: dict[str, Any] = {
            "cluster": cluster_arn,
            "taskDefinition": task_definition_arn,
            "count": 1,
            "launchType": "FARGATE",
            "platformVersion": platform_version,
            "networkConfiguration": {
                "awsvpcConfiguration": {
                    "subnets": [subnet_id],
                    "securityGroups": list(security_group_ids),
                    "assignPublicIp": "ENABLED" if assign_public_ip else "DISABLED",
                }
            },
            "enableExecuteCommand": False,
            "startedBy": started_by,
        }
        if task_role_arn is not None:
            kwargs["overrides"] = {"taskRoleArn": task_role_arn}
        return self._call("ecs", "run_task", **kwargs)

    def stop_task(self, *, cluster_arn: str, task_arn: str) -> Observation:
        return self._call(
            "ecs",
            "stop_task",
            cluster=cluster_arn,
            task=task_arn,
            reason="kalpamani permission subcell: unexpected launch stopped",
        )

    def list_tasks(
        self, *, cluster_arn: str, started_by: str, next_token: str | None
    ) -> Observation:
        # One page, filtered by startedBy and by nothing else: the ListTasks contract makes
        # startedBy the only filter when it is used (no desiredStatus, family, serviceName,
        # launchType or containerInstance beside it). The engine follows the token within
        # its bound.
        kwargs: dict[str, Any] = {
            "cluster": cluster_arn,
            "startedBy": started_by,
            "maxResults": MAX_RETURNED_TASKS,
        }
        if next_token is not None:
            kwargs["nextToken"] = next_token
        return self._call("ecs", "list_tasks", **kwargs)

    def describe_tasks(self, *, cluster_arn: str, task_arns: tuple[str, ...]) -> Observation:
        return self._call("ecs", "describe_tasks", cluster=cluster_arn, tasks=list(task_arns))

    def execute_command(self, *, cluster_arn: str, task_arn: str) -> Observation:
        # The documented request: ``command`` and ``interactive`` are required, and ECS
        # "only supports initiating interactive sessions, so you must specify true" --
        # ``interactive=False`` is an invalid request the service refuses on its
        # parameters before any policy is evaluated, not a permission test (proposed
        # ADR-0048). A session that a 200 would open is closed by stopping the task.
        return self._call(
            "ecs",
            "execute_command",
            cluster=cluster_arn,
            task=task_arn,
            command="/bin/true",
            interactive=True,
        )


def single_service_client(
    operation: Operation, client_for: Callable[[str], Any]
) -> SdkPermissionClient:
    """A client that can reach the one service ``operation`` names, and no other.

    The probe task's factory (proposed ADR-0048): a subcell that issues ``GetSecretValue``
    holds a Secrets Manager client and nothing else; an S3 subcell holds an S3 client and
    nothing else. Any other service is refused before an SDK client exists.
    """
    service = OPERATION_SERVICE[operation]

    def restricted(name: str) -> Any:
        if name != service:
            raise ValueError("the probe holds the one service its operation names")
        return client_for(name)

    return SdkPermissionClient(restricted)


__all__ = ["OPERATION_SERVICE", "SdkPermissionClient", "single_service_client"]
