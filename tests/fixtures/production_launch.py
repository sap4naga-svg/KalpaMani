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
    CLUSTER_ARN,
    COMMIT,
    CONFIGURATION_DIGEST,
    EXECUTION_ROLE_ARN,
    IMAGE_DIGEST,
    KEY_ARN,
    NOW,
    PLAN_DIGEST,
    PLATFORM_VERSION,
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
)
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for

ACQ = ProductionActor.ACQUISITION
BLD = ProductionActor.BUILD


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


def target_document(actor: ProductionActor, *, verification: bool = False) -> dict[str, Any]:
    """One registered revision with its image-gate values."""
    return {
        "task_definition_arn": (
            verification_revision_arn(actor) if verification else revision_arn(actor)
        ),
        "image_digest": IMAGE_DIGEST,
        "configuration_digest": CONFIGURATION_DIGEST,
        "code_commit": COMMIT,
    }


def launch_inputs_document(*, verification: bool = True, **overrides: Any) -> dict[str, Any]:
    """A synthetic launch-inputs record for both actors, verification targets optional."""
    document: dict[str, Any] = {
        "schema_version": RECORD_SCHEMA_VERSION,
        "contract_id": LAUNCH_INPUTS_CONTRACT_ID,
        "cluster_arn": CLUSTER_ARN,
        "execution_role_arn": EXECUTION_ROLE_ARN,
        "binding_key_arn": KEY_ARN,
        "platform_version": PLATFORM_VERSION,
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


def authorization_document(
    *, actor: ProductionActor, kind: str, identity: str, **overrides: Any
) -> dict[str, Any]:
    """The owner's written authorization for one launch, valid around ``NOW``."""
    document: dict[str, Any] = {
        "schema_version": RECORD_SCHEMA_VERSION,
        "contract_id": AUTHORIZATION_CONTRACT_ID,
        "actor": actor.value,
        "kind": kind,
        "identity": identity,
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
    "FakeClients",
    "FakeSts",
    "authorization_document",
    "launch_inputs_document",
    "ledger_document",
    "ledger_row",
    "target_document",
]
