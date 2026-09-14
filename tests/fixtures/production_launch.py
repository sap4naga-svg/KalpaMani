"""Synthetic owner records for the launch tool (proposed ADR-0045). **Fakes only.**

Every value is the runtime fixtures' synthetic one: a twelve-zero account, invented
ARNs, digests spelled from repeating hex. Nothing here is a real account, bucket,
profile session or task.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from fixtures.production_runtime import (
    BUILD_ID,
    CLUSTER_ARN,
    COMMIT,
    CONFIGURATION_DIGEST,
    EXECUTION_ROLE_ARN,
    IMAGE_DIGEST,
    KEY_ARN,
    NOW,
    PLAN_DIGEST,
    PLATFORM_VERSION,
    REVISION,
    RUN_ID,
    SECURITY_GROUPS,
    SUBNET_ID,
    FakeEc2,
    FakeEcs,
    FakeSsm,
    caller_identity,
    human_identity_arn,
    launcher_identity_arn,
    revision_arn,
    slice_document,
    task_role_arn,
    verification_revision_arn,
)
from kalpamani.data.production.sharadar.launch_records import (
    AUTHORIZATION_CONTRACT_ID,
    LAUNCH_INPUTS_CONTRACT_ID,
    LEDGER_CONTRACT_ID,
    RECORD_SCHEMA_VERSION,
    LaunchKind,
    LaunchSpecification,
    build_specification,
    parse_launch_inputs,
    parse_owner_ledger,
)
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for

ACQ = ProductionActor.ACQUISITION
BLD = ProductionActor.BUILD

#: Synthetic evidence references: the R-3 record's digest and each target's generation record.
R3_DIGEST = "a3" * 32
GENERATION_RECORD_DIGESTS = {
    (ACQ, False): "1a" * 32,
    (ACQ, True): "1b" * 32,
    (BLD, False): "2a" * 32,
    (BLD, True): "2b" * 32,
}


def ledger_row(
    identity: str,
    *,
    actor: ProductionActor = ACQ,
    kind: str = "production",
    outcome: str = "COMPLETED",
    evidence: str = "RECEIPT_VERIFIED",
    with_slice: bool | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """One synthetic owner-ledger row; an acquisition row carries the slice by default."""
    carries = (actor is ACQ) if with_slice is None else with_slice
    document: dict[str, Any] = {
        "identity": identity,
        "actor": actor.value,
        "kind": kind,
        "outcome": outcome,
        "evidence": evidence,
        "launched_at": (NOW - timedelta(days=2)).isoformat(),
        "completed_at": (NOW - timedelta(days=2, hours=-1)).isoformat(),
        "slice": slice_document() if carries else None,
        "plan_digest": PLAN_DIGEST if carries else None,
    }
    document.update(overrides)
    return document


def ledger_document(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A synthetic owner ledger over ``rows`` (default: empty)."""
    return {
        "schema_version": RECORD_SCHEMA_VERSION,
        "contract_id": LEDGER_CONTRACT_ID,
        "rows": [] if rows is None else rows,
    }


def task_definition_document(
    actor: ProductionActor, *, verification: bool = False, **overrides: Any
) -> dict[str, Any]:
    """The owner's transcription of one registered revision (synthetic)."""
    constants = constants_for(actor)
    family = constants.verification_task_family if verification else constants.task_family
    document: dict[str, Any] = {
        "family": family,
        "revision": REVISION,
        "task_role_arn": task_role_arn(actor),
        "execution_role_arn": EXECUTION_ROLE_ARN,
        "cpu": 1024,
        "memory": 2048,
        "network_mode": "awsvpc",
        "operating_system_family": "LINUX",
        "cpu_architecture": "X86_64",
        "user": "10001:10001",
        "readonly_root_filesystem": True,
        "work_tmpfs": True,
        "command": family,
        "image_digest": IMAGE_DIGEST,
    }
    document.update(overrides)
    return document


def target_document(
    actor: ProductionActor,
    *,
    verification: bool = False,
    configuration_digest: str = CONFIGURATION_DIGEST,
    **overrides: Any,
) -> dict[str, Any]:
    """One registered revision with its image-gate values and task-definition evidence."""
    document: dict[str, Any] = {
        "task_definition_arn": (
            verification_revision_arn(actor) if verification else revision_arn(actor)
        ),
        "image_digest": IMAGE_DIGEST,
        "configuration_digest": configuration_digest,
        "code_commit": COMMIT,
        "generation_record_digest": GENERATION_RECORD_DIGESTS[(actor, verification)],
        "task_definition": task_definition_document(actor, verification=verification),
    }
    document.update(overrides)
    return document


def launch_inputs_document(*, verification: bool = True, **overrides: Any) -> dict[str, Any]:
    """A synthetic launch-inputs record for both actors, verification targets optional."""
    document: dict[str, Any] = {
        "schema_version": RECORD_SCHEMA_VERSION,
        "contract_id": LAUNCH_INPUTS_CONTRACT_ID,
        "cluster_arn": CLUSTER_ARN,
        "execution_role_arn": EXECUTION_ROLE_ARN,
        "binding_key_arn": KEY_ARN,
        "platform_version": PLATFORM_VERSION,
        "r3_verification_digest": R3_DIGEST,
        "actors": {
            actor.value: {
                "task_role_arn": task_role_arn(actor),
                "subnet_id": SUBNET_ID,
                "security_group_ids": list(SECURITY_GROUPS),
                "production": target_document(actor),
                "verification": (
                    target_document(actor, verification=True) if verification else None
                ),
            }
            for actor in ProductionActor
        },
    }
    document.update(overrides)
    return document


def specification_for(
    *,
    actor: ProductionActor,
    kind: str,
    identity: str,
    ledger: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    slice_doc: dict[str, Any] | None = None,
    run_identities: list[str] | None = None,
) -> LaunchSpecification:
    """The specification the fixtures' records produce for one launch."""
    from kalpamani.data.contracts.canonical import canonical_bytes

    rows = [ledger_row(RUN_ID)] if actor is BLD else []
    parsed_ledger = parse_owner_ledger(
        canonical_bytes(ledger_document(rows) if ledger is None else ledger)
    )
    parsed_inputs = parse_launch_inputs(
        canonical_bytes(launch_inputs_document() if inputs is None else inputs)
    )
    return build_specification(
        ledger=parsed_ledger,
        inputs=parsed_inputs,
        actor=actor,
        kind=LaunchKind(kind),
        identity=identity,
        slice_document=(slice_document() if slice_doc is None else slice_doc)
        if actor is ACQ
        else None,
        run_identities=([RUN_ID] if run_identities is None else run_identities)
        if actor is BLD
        else None,
    )


def specification_digest_for(**fields: Any) -> str:
    """The specification digest the fixtures' records produce for one launch."""
    return specification_for(**fields).digest


def authorization_document(
    *,
    actor: ProductionActor,
    kind: str,
    identity: str,
    specification_digest: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """The owner's written authorization for one launch specification, valid around ``NOW``."""
    document: dict[str, Any] = {
        "schema_version": RECORD_SCHEMA_VERSION,
        "contract_id": AUTHORIZATION_CONTRACT_ID,
        "actor": actor.value,
        "kind": kind,
        "identity": identity,
        "specification_digest": (
            specification_digest_for(actor=actor, kind=kind, identity=identity)
            if specification_digest is None
            else specification_digest
        ),
        "issued_at": (NOW - timedelta(hours=1)).isoformat(),
        "expires_at": (NOW + timedelta(hours=3)).isoformat(),
    }
    document.update(overrides)
    return document


@dataclass
class FakeSts:
    """An STS-shaped fake answering one identity; every call is counted."""

    arn: str
    calls: int = 0

    def get_caller_identity(self) -> dict[str, str]:
        self.calls += 1
        return caller_identity(self.arn)


@dataclass
class FakeClients:
    """A :class:`ClientFactory` over the runtime fakes, one object per profile.

    ``constructions`` records every ``(service, profile)`` the tool asked for, so a
    test can prove the refusing paths asked for nothing.
    """

    actor: ProductionActor
    ecs_fake: FakeEcs
    ec2_fake: FakeEc2
    human_ssm: FakeSsm = field(default_factory=FakeSsm)
    launcher_ssm: FakeSsm = field(default_factory=FakeSsm)
    human_sts: FakeSts | None = None
    launcher_sts: FakeSts | None = None
    constructions: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.human_sts is None:
            self.human_sts = FakeSts(human_identity_arn(self.actor))
        if self.launcher_sts is None:
            self.launcher_sts = FakeSts(launcher_identity_arn(self.actor))

    def _profile_kind(self, profile: str) -> str:
        constants = constants_for(self.actor)
        if profile == constants.profile:
            return "human"
        if profile == constants.launcher_profile:
            return "launcher"
        raise AssertionError("the tool asked for a profile that is not this actor's")

    def sts(self, profile: str) -> Any:
        self.constructions.append(("sts", profile))
        assert self.human_sts is not None and self.launcher_sts is not None
        return self.human_sts if self._profile_kind(profile) == "human" else self.launcher_sts

    def ecs(self, profile: str) -> Any:
        self.constructions.append(("ecs", profile))
        assert self._profile_kind(profile) == "launcher"
        return self.ecs_fake

    def ec2(self, profile: str) -> Any:
        self.constructions.append(("ec2", profile))
        assert self._profile_kind(profile) == "launcher"
        return self.ec2_fake

    def ssm(self, profile: str) -> Any:
        self.constructions.append(("ssm", profile))
        return self.human_ssm if self._profile_kind(profile) == "human" else self.launcher_ssm


__all__ = [
    "ACQ",
    "BLD",
    "BUILD_ID",
    "GENERATION_RECORD_DIGESTS",
    "R3_DIGEST",
    "FakeClients",
    "FakeSts",
    "authorization_document",
    "launch_inputs_document",
    "ledger_document",
    "ledger_row",
    "specification_digest_for",
    "target_document",
    "task_definition_document",
]
