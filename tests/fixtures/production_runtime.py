"""Synthetic fixtures for the ADR-0036 / ADR-0037 production runtime foundations.

**Entirely hand-authored and fictitious.** The account is all zeros, the bucket
announces itself as synthetic, every ARN, subnet, security group, interface and
task id is invented, and no vendor row, private value or real deployment
identifier appears here or is reachable from here.

The fakes below are the only "services" any production-runtime test touches.
They open no socket and know no host: each returns what a test queued and
records what it was asked for, so a test can count operations rather than infer
them.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar.bindings import BINDING_SCHEMA_VERSION
from kalpamani.data.production.sharadar.compute import CompiledLaunch
from kalpamani.data.production.sharadar.inputs import INPUT_SCHEMA_VERSION, ledger_digest
from kalpamani.data.production.sharadar.keys import (
    production_acquisition_key,
    production_payload_key,
)
from kalpamani.data.production.sharadar.locator import LOCATOR_SCHEMA_VERSION
from kalpamani.data.production.sharadar.metadata import CompiledTask
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for

# ---------------------------------------------------------------------------
# Synthetic identifiers. Every one is invented and matches no deployment.
# ---------------------------------------------------------------------------

ACCOUNT: Final = "000000000000"
OTHER_ACCOUNT: Final = "999999999999"
REGION: Final = "us-east-1"
BUCKET: Final = "synthetic-licensed-bucket-zz"
COMMIT: Final = "0123456789abcdef0123456789abcdef01234567"
TREE: Final = "89abcdef0123456789abcdef0123456789abcdef"
ENVELOPE: Final = "0123456789abcdef" * 4
PLAN_DIGEST: Final = "ab" * 32
OTHER_PLAN_DIGEST: Final = "cd" * 32
IMAGE_DIGEST: Final = "sha256:" + "ef" * 32

RUN_ID: Final = "synthetic-production-run-0001"
OTHER_RUN_ID: Final = "synthetic-production-run-0002"
BUILD_ID: Final = "synthetic-production-build-0001"

CLUSTER_NAME: Final = "synthetic-research-cluster"
CLUSTER_ARN: Final = f"arn:aws:ecs:{REGION}:{ACCOUNT}:cluster/{CLUSTER_NAME}"
TASK_ID: Final = "0123456789abcdef0123456789abcdef"
OTHER_TASK_ID: Final = "fedcba9876543210fedcba9876543210"
TASK_ARN: Final = f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/{CLUSTER_NAME}/{TASK_ID}"
OTHER_TASK_ARN: Final = f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/{CLUSTER_NAME}/{OTHER_TASK_ID}"
EXECUTION_ROLE_ARN: Final = f"arn:aws:iam::{ACCOUNT}:role/synthetic-task-execution"
KEY_ARN: Final = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/00000000-0000-4000-8000-000000000000"
SUBNET_ID: Final = "subnet-0123456789abcdef0"
OTHER_SUBNET_ID: Final = "subnet-0fedcba9876543210"
INTERFACE_ID: Final = "eni-0123456789abcdef0"
SECURITY_GROUPS: Final[tuple[str, ...]] = ("sg-0123456789abcdef0", "sg-0123456789abcdef1")
OTHER_SECURITY_GROUP: Final = "sg-0fedcba9876543210"
PLATFORM_VERSION: Final = "1.4.0"
REVISION: Final = 7

NOW: Final = datetime(2026, 9, 12, 14, 0, 0, tzinfo=UTC)

#: Every synthetic private value, so a leak scan cannot drift from the scenarios.
CANARIES: Final[tuple[str, ...]] = (
    ACCOUNT,
    OTHER_ACCOUNT,
    BUCKET,
    COMMIT,
    TREE,
    ENVELOPE,
    PLAN_DIGEST,
    RUN_ID,
    BUILD_ID,
    TASK_ID,
    TASK_ARN,
    SUBNET_ID,
    INTERFACE_ID,
    *SECURITY_GROUPS,
)


def revision_arn(actor: ProductionActor, revision: int = REVISION) -> str:
    """The synthetic task-definition ARN of ``actor``'s family at ``revision``."""
    family = constants_for(actor).task_family
    return f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/{family}:{revision}"


def task_role_arn(actor: ProductionActor) -> str:
    """The synthetic task-role ARN of ``actor``."""
    return f"arn:aws:iam::{ACCOUNT}:role/{constants_for(actor).task_role_name}"


def task_identity_arn(actor: ProductionActor, task_id: str = TASK_ID) -> str:
    """The STS assumed-role ARN a task running as ``actor`` reports."""
    return f"arn:aws:sts::{ACCOUNT}:assumed-role/{constants_for(actor).task_role_name}/{task_id}"


def human_identity_arn(actor: ProductionActor, suffix: str = "0123456789abcdef") -> str:
    """The STS assumed-role ARN ``actor``'s generated permission-set role reports."""
    role = f"AWSReservedSSO_{constants_for(actor).permission_set}_{suffix}"
    return f"arn:aws:sts::{ACCOUNT}:assumed-role/{role}/synthetic.operator"


def launcher_identity_arn(actor: ProductionActor, suffix: str = "0123456789abcdef") -> str:
    """The STS assumed-role ARN ``actor``'s launcher permission-set role reports."""
    role = f"AWSReservedSSO_{constants_for(actor).launcher_permission_set}_{suffix}"
    return f"arn:aws:sts::{ACCOUNT}:assumed-role/{role}/synthetic.operator"


def caller_identity(arn: str, account: str = ACCOUNT) -> dict[str, str]:
    """A decoded ``sts:GetCallerIdentity`` response."""
    return {"UserId": "AROAEXAMPLE:synthetic", "Account": account, "Arn": arn}


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def binding_document(actor: ProductionActor, **overrides: Any) -> dict[str, Any]:
    """A complete, valid synthetic binding for ``actor``, fields overridable."""
    constants = constants_for(actor)
    document: dict[str, Any] = {
        "schema_version": BINDING_SCHEMA_VERSION,
        "binding_kind": constants.binding_kind,
        "contract_id": constants.binding_contract_id,
        "aws_partition": "aws",
        "aws_region": REGION,
        "target_account_id": ACCOUNT,
        constants.profile_field: constants.profile,
        "licensed_bucket_name": BUCKET,
        "provenance": {
            "implementation_commit": COMMIT,
            "implementation_tree": TREE,
            "environment_binding_sha256": ENVELOPE,
        },
    }
    document.update(overrides)
    return document


def slice_document(**overrides: Any) -> dict[str, Any]:
    """A valid synthetic slice: two datasets, two requests, a 4 MiB ceiling."""
    document: dict[str, Any] = {
        "datasets": ["actions", "tickers"],
        "windows": {"actions": "1998-01-01/2026-09-11", "tickers": "SNAPSHOT"},
        "request_count": 2,
        "max_response_bytes": 4 * 1024 * 1024,
    }
    document.update(overrides)
    return document


def acquisition_input_document(**overrides: Any) -> dict[str, Any]:
    """A valid synthetic acquisition input, issued one hour before ``NOW``."""
    document: dict[str, Any] = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "contract_id": constants_for(ProductionActor.ACQUISITION).input_contract_id,
        "run_identity": RUN_ID,
        "slice": slice_document(),
        "plan_digest": PLAN_DIGEST,
        "issued_at": (NOW - timedelta(hours=1)).isoformat(),
        "expires_at": (NOW + timedelta(hours=23)).isoformat(),
    }
    document.update(overrides)
    return document


def ledger_row_document(run_identity: str = RUN_ID, **overrides: Any) -> dict[str, Any]:
    """A valid synthetic completed ledger row."""
    document: dict[str, Any] = {
        "run_identity": run_identity,
        "slice": slice_document(),
        "plan_digest": PLAN_DIGEST,
        "outcome": "COMPLETED",
        "launched_at": (NOW - timedelta(days=2)).isoformat(),
        "completed_at": (NOW - timedelta(days=2, hours=-1)).isoformat(),
    }
    document.update(overrides)
    return document


def build_input_document(
    rows: list[dict[str, Any]] | None = None, **overrides: Any
) -> dict[str, Any]:
    """A valid synthetic build input over ``rows`` (default: one row for ``RUN_ID``)."""
    runs = [ledger_row_document()] if rows is None else rows
    document: dict[str, Any] = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "contract_id": constants_for(ProductionActor.BUILD).input_contract_id,
        "build_identity": BUILD_ID,
        "runs": runs,
        "ledger_digest": ledger_digest(runs),
        "issued_at": (NOW - timedelta(hours=1)).isoformat(),
        "expires_at": (NOW + timedelta(hours=23)).isoformat(),
    }
    document.update(overrides)
    return document


def encode(document: object) -> bytes:
    """Canonical bytes, as a launch tool would materialize them."""
    return canonical_bytes(document)


def loose_encode(document: object) -> bytes:
    """Non-canonical bytes, so a digest over bytes is provably over *these* bytes."""
    return json.dumps(document, indent=1).encode("utf-8")


#: Synthetic opaque payloads and records for the locator scenarios.
PAYLOADS: Final[tuple[bytes, ...]] = (
    b"synthetic-opaque-production-payload-0001",
    b"synthetic-opaque-production-payload-0002",
)
RECORDS: Final[tuple[bytes, ...]] = (
    b'{"synthetic":"production-record-0001"}',
    b'{"synthetic":"production-record-0002"}',
)


def locator_entry(
    ordinal: int, dataset: str, payload: bytes, record: bytes, run_id: str = RUN_ID
) -> dict[str, Any]:
    """One valid locator entry, with keys built by the real production builders."""
    payload_key = production_payload_key(dataset=dataset, payload=payload)
    record_key = production_acquisition_key(
        dataset=dataset, payload_digest=payload_key.content_sha256, run_id=run_id, record=record
    )
    window = "SNAPSHOT" if dataset == "tickers" else "1998-01-01/2026-09-11"
    return {
        "ordinal": ordinal,
        "dataset": dataset,
        "payload_key": payload_key.logical_key,
        "payload_sha256": payload_key.content_sha256,
        "payload_bytes": len(payload),
        "record_key": record_key.logical_key,
        "record_sha256": record_key.content_sha256,
        "record_bytes": len(record),
        "request": {"window": window, "page_offset": 0, "page_limit": 10000},
    }


def locator_document(run_id: str = RUN_ID, **overrides: Any) -> dict[str, Any]:
    """A complete, valid synthetic run locator over two entries."""
    entries = [
        locator_entry(0, "actions", PAYLOADS[0], RECORDS[0], run_id),
        locator_entry(1, "tickers", PAYLOADS[1], RECORDS[1], run_id),
    ]
    document: dict[str, Any] = {
        "schema_version": LOCATOR_SCHEMA_VERSION,
        "run_id": run_id,
        "plan_digest": PLAN_DIGEST,
        "slice": slice_document(),
        "acquisition_mode": "BACKFILL",
        "started_at": (NOW - timedelta(days=2)).isoformat(),
        "completed_at": (NOW - timedelta(days=2, hours=-1)).isoformat(),
        "completeness": "COMPLETE",
        "publication_state_unknown": False,
        "planned_requests": 2,
        "completed_requests": 2,
        "entries": entries,
    }
    document.update(overrides)
    return document


def metadata_document(actor: ProductionActor, **overrides: Any) -> dict[str, Any]:
    """A task metadata v4 task document with the documented fields."""
    document: dict[str, Any] = {
        "Cluster": CLUSTER_ARN,
        "TaskARN": TASK_ARN,
        "Family": constants_for(actor).task_family,
        "Revision": str(REVISION),
        "Containers": [{"Name": "runner", "ImageID": IMAGE_DIGEST}],
    }
    document.update(overrides)
    return document


def compiled_task(actor: ProductionActor) -> CompiledTask:
    """The compiled task of ``actor``."""
    return CompiledTask(
        actor=actor,
        family=constants_for(actor).task_family,
        revision=REVISION,
        image_digest=IMAGE_DIGEST,
    )


def compiled_launch(actor: ProductionActor, **overrides: Any) -> CompiledLaunch:
    """The compiled launch of ``actor``, fields overridable."""
    fields_: dict[str, Any] = {
        "actor": actor,
        "cluster_arn": CLUSTER_ARN,
        "task_definition_arn": revision_arn(actor),
        "task_role_arn": task_role_arn(actor),
        "execution_role_arn": EXECUTION_ROLE_ARN,
        "subnet_id": SUBNET_ID,
        "security_group_ids": SECURITY_GROUPS,
        "assign_public_ip": actor is ProductionActor.ACQUISITION,
        "platform_version": PLATFORM_VERSION,
        "binding_key_arn": KEY_ARN,
    }
    fields_.update(overrides)
    return CompiledLaunch(**fields_)


# ---------------------------------------------------------------------------
# Fakes. Each records what it was asked and returns what a test queued.
# ---------------------------------------------------------------------------


class FakeClientError(Exception):
    """A ``botocore``-shaped client error: carries ``response["Error"]["Code"]``."""

    def __init__(self, code: str) -> None:
        super().__init__(f"synthetic client error {code}")
        self.response = {"Error": {"Code": code, "Message": "synthetic backend message"}}


@dataclass
class FakeSsm:
    """An SSM-shaped fake: a name-keyed store with create-only semantics."""

    values: dict[str, bytes] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    get_failures: dict[str, str] = field(default_factory=dict)
    put_failures: dict[str, str] = field(default_factory=dict)
    delete_failures: dict[str, str] = field(default_factory=dict)
    before_get: Callable[[str], None] | None = None

    def get_parameter(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_parameter", kwargs))
        name = kwargs["Name"]
        if self.before_get is not None:
            self.before_get(name)
        if name in self.get_failures:
            raise FakeClientError(self.get_failures[name])
        if name not in self.values:
            raise FakeClientError("ParameterNotFound")
        return {"Parameter": {"Name": name, "Value": self.values[name].decode("utf-8")}}

    def put_parameter(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("put_parameter", kwargs))
        name = kwargs["Name"]
        if name in self.put_failures:
            raise FakeClientError(self.put_failures[name])
        if kwargs.get("Overwrite"):
            raise AssertionError("the channel must never overwrite")
        if name in self.values:
            raise FakeClientError("ParameterAlreadyExists")
        self.values[name] = kwargs["Value"].encode("utf-8")
        return {"Version": 1, "Tier": kwargs.get("Tier")}

    def delete_parameter(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete_parameter", kwargs))
        name = kwargs["Name"]
        if name in self.delete_failures:
            raise FakeClientError(self.delete_failures[name])
        if name not in self.values:
            raise FakeClientError("ParameterNotFound")
        del self.values[name]
        return {}

    def names(self, operation: str) -> list[str]:
        """The parameter names one operation was asked for, in order."""
        return [kwargs["Name"] for name, kwargs in self.calls if name == operation]


def task_entry(
    actor: ProductionActor,
    *,
    status: str,
    attachment_status: str | None = "ATTACHED",
    subnet_id: str | None = SUBNET_ID,
    interface_id: str | None = INTERFACE_ID,
    task_arn: str = TASK_ARN,
    revision: int = REVISION,
    exit_code: int | None = None,
) -> dict[str, Any]:
    """One ``DescribeTasks`` task entry with the documented fields."""
    entry: dict[str, Any] = {
        "taskArn": task_arn,
        "taskDefinitionArn": revision_arn(actor, revision),
        "lastStatus": status,
        "containers": [{"name": "runner", "exitCode": exit_code}]
        if exit_code is not None
        else [{"name": "runner"}],
    }
    if attachment_status is not None:
        details: list[dict[str, str]] = []
        if subnet_id is not None:
            details.append({"name": "subnetId", "value": subnet_id})
        if interface_id is not None:
            details.append({"name": "networkInterfaceId", "value": interface_id})
        details.append({"name": "privateIPv4Address", "value": "10.0.0.1"})
        entry["attachments"] = [
            {
                "id": "att-1",
                "type": "ElasticNetworkInterface",
                "status": attachment_status,
                "details": details,
            }
        ]
    return entry


@dataclass
class FakeEcs:
    """An ECS-shaped fake: one queued ``RunTask`` answer, a queue of descriptions."""

    run_response: dict[str, Any] | None = None
    run_failure: str | None = None
    descriptions: list[dict[str, Any]] = field(default_factory=list)
    describe_failure: str | None = None
    stop_failure: str | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def run_task(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("run_task", kwargs))
        if self.run_failure is not None:
            raise FakeClientError(self.run_failure)
        if self.run_response is None:
            raise AssertionError("no run_task response queued")
        return self.run_response

    def describe_tasks(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("describe_tasks", kwargs))
        if self.describe_failure is not None:
            raise FakeClientError(self.describe_failure)
        if not self.descriptions:
            raise AssertionError("no describe_tasks response queued")
        entry = self.descriptions.pop(0) if len(self.descriptions) > 1 else self.descriptions[0]
        return {"tasks": [entry], "failures": []}

    def stop_task(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("stop_task", kwargs))
        if self.stop_failure is not None:
            raise FakeClientError(self.stop_failure)
        return {"task": {"taskArn": kwargs["task"]}}

    def names(self, operation: str) -> list[dict[str, Any]]:
        return [kwargs for name, kwargs in self.calls if name == operation]


def interface_entry(
    *,
    interface_id: str = INTERFACE_ID,
    subnet_id: str = SUBNET_ID,
    groups: tuple[str, ...] = SECURITY_GROUPS,
    public_ip: str | None = None,
) -> dict[str, Any]:
    """One ``DescribeNetworkInterfaces`` entry with the documented fields."""
    entry: dict[str, Any] = {
        "NetworkInterfaceId": interface_id,
        "SubnetId": subnet_id,
        "Groups": [{"GroupId": group, "GroupName": "synthetic"} for group in groups],
    }
    if public_ip is not None:
        entry["Association"] = {"PublicIp": public_ip, "IpOwnerId": "amazon"}
    return entry


@dataclass
class FakeEc2:
    """An EC2-shaped fake with one queued interface description."""

    interface: dict[str, Any] | None = None
    failure: str | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def describe_network_interfaces(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("describe_network_interfaces", kwargs))
        if self.failure is not None:
            raise FakeClientError(self.failure)
        if self.interface is None:
            raise AssertionError("no interface queued")
        return {"NetworkInterfaces": [self.interface]}


@dataclass
class FakeClock:
    """An injectable monotonic clock and a sleep that advances it."""

    seconds: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.seconds

    def sleep(self, duration: float) -> None:
        self.sleeps.append(duration)
        self.seconds += duration

    def now(self) -> datetime:
        return NOW + timedelta(seconds=self.seconds)


@dataclass
class FakeS3Get:
    """A get-only S3-shaped fake: a key-keyed byte store, every read recorded."""

    objects: dict[str, bytes] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)
    failure: str | None = None

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.failure is not None:
            raise FakeClientError(self.failure)
        key = kwargs["Key"]
        if key not in self.objects:
            raise FakeClientError("NoSuchKey")
        return {"Body": _Body(self.objects[key])}


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0

    def read(self, size: int) -> bytes:
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def digest_of(payload: bytes) -> str:
    """The SHA-256 of synthetic bytes."""
    return sha256_hex(payload)
