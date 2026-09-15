"""The R-4 .. R-9 permission subcells (ADR-0036 s.3; proposed ADR-0047).

ADR-0036 s.3 states each of R-4 .. R-9 as one row: a principal, what must succeed and what
must be refused. A row is not executable; this module expands each row into **subcells**,
each one operation by one principal against one exact target class with one expectation,
traced to the phrase of the row it comes from. The tool (``scripts/production_permission_cells.py``)
executes one subcell per authorized invocation; the cell runner derives the cell's state
from the records the tool wrote and passes a cell only when **every** subcell of it is
matched at runtime (L3) against the binding, declaration and registration now in force and
every object a subcell created is confirmed removed.

**What is decided here and what is not.** A subcell's layer says what can decide it:
``L3_RUNTIME`` -- one real request under the principal's own profile, counted; ``L3_BY_R1``
-- the launcher's positive operations, which the R-1 bootstrap launch already performs and
records (no second task is started to prove them); ``BLOCKED`` -- a subcell no accepted
mechanism can execute: a task-role subcell needs a task-side probe entry (ADR-0047 s.5
describes its contract; it is not implemented), and the deletion role has no execution path
(no human may assume it and no deletion task definition exists). A blocked subcell blocks
its cell; simulation (L2) is not executed by this module and could never pass a subcell.

**Expectations are decided by classification.** An ``ALLOWED`` operation matches only the
success class the operation returns (``200``, ``204``); a ``DENIED`` operation matches only
an access denial (identity-based, resource-based, or an access denial without context --
each is a refusal; which policy refused is not what these cells decide). A timeout, a
network failure, an authentication failure, a missing bucket, a throttle or an ambiguous
answer decides nothing: the record reads ``UNDECIDED`` and the subcell stays unexercised.

**Unexpected success is accounted for.** A ``DENIED`` ``RunTask`` that starts a task is an
inversion **and** a resource: the engine stops that task at once and the record carries the
task id and whether the stop was acknowledged; a ``DENIED`` write that succeeded is an
inversion and an object the cleanup must remove. Every created key is recorded before the
operation (the attempt record) and again after it, so an interrupted attempt leaves a name
the cleanup can remove.

**Mocked results are not AWS verification.** Every result in this repository's tests is a
counting fake's.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.objectstore import physical_key
from kalpamani.data.production.sharadar.documents import (
    decode_document,
    exact_str,
    hex_digest,
    instant,
)
from kalpamani.data.production.sharadar.keys import (
    production_acquisition_key_for_digest,
    production_claim_key,
    production_payload_key_for_digest,
    run_locator_key,
)
from kalpamani.data.production.sharadar.launch_records import (
    RECORD_SCHEMA_VERSION,
    LaunchInputs,
    LaunchKind,
)
from kalpamani.data.production.sharadar.r3_verification import (
    CONTROL_PROFILE,
    Observation,
    ObservedClass,
    classify,
)
from kalpamani.data.production.sharadar.release import TASK_ARN_RE
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for
from kalpamani.data.qualify.sharadar.runtime_binding import (
    EXPECTED_ACQUISITION_PROFILE,
    EXPECTED_ASSESSMENT_PROFILE,
)

# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------


class Principal(StrEnum):
    """Who issues the operation. Closed; each maps to exactly one profile or to none."""

    ACQUISITION_HUMAN = "ACQUISITION_HUMAN"
    BUILD_HUMAN = "BUILD_HUMAN"
    ACQUISITION_LAUNCHER = "ACQUISITION_LAUNCHER"
    BUILD_LAUNCHER = "BUILD_LAUNCHER"
    ACQUISITION_TASK = "ACQUISITION_TASK"
    BUILD_TASK = "BUILD_TASK"
    QUALIFICATION_ACQUISITION = "QUALIFICATION_ACQUISITION"
    QUALIFICATION_ASSESSMENT = "QUALIFICATION_ASSESSMENT"
    DELETION_ROLE = "DELETION_ROLE"
    CONTROL = "CONTROL"


#: The workstation profile each human principal is reached through; ``None`` for a
#: principal no human profile reaches (a task role, the deletion role).
PRINCIPAL_PROFILE: Final[dict[Principal, str | None]] = {
    Principal.ACQUISITION_HUMAN: constants_for(ProductionActor.ACQUISITION).profile,
    Principal.BUILD_HUMAN: constants_for(ProductionActor.BUILD).profile,
    Principal.ACQUISITION_LAUNCHER: constants_for(ProductionActor.ACQUISITION).launcher_profile,
    Principal.BUILD_LAUNCHER: constants_for(ProductionActor.BUILD).launcher_profile,
    Principal.ACQUISITION_TASK: None,
    Principal.BUILD_TASK: None,
    Principal.QUALIFICATION_ACQUISITION: EXPECTED_ACQUISITION_PROFILE,
    Principal.QUALIFICATION_ASSESSMENT: EXPECTED_ASSESSMENT_PROFILE,
    Principal.DELETION_ROLE: None,
    Principal.CONTROL: CONTROL_PROFILE,
}

#: The production actor a principal acts for, where it acts for one.
PRINCIPAL_ACTOR: Final[dict[Principal, ProductionActor | None]] = {
    Principal.ACQUISITION_HUMAN: ProductionActor.ACQUISITION,
    Principal.ACQUISITION_LAUNCHER: ProductionActor.ACQUISITION,
    Principal.ACQUISITION_TASK: ProductionActor.ACQUISITION,
    Principal.BUILD_HUMAN: ProductionActor.BUILD,
    Principal.BUILD_LAUNCHER: ProductionActor.BUILD,
    Principal.BUILD_TASK: ProductionActor.BUILD,
    Principal.QUALIFICATION_ACQUISITION: None,
    Principal.QUALIFICATION_ASSESSMENT: None,
    Principal.DELETION_ROLE: None,
    Principal.CONTROL: None,
}


class Operation(StrEnum):
    """The one operation a subcell issues. Closed."""

    S3_PUT_CONDITIONAL = "S3_PUT_CONDITIONAL"
    S3_GET = "S3_GET"
    S3_LIST = "S3_LIST"
    S3_DELETE = "S3_DELETE"
    SECRET_GET = "SECRET_GET"  # noqa: S105 - a vocabulary token, not a value
    SECRET_DESCRIBE = "SECRET_DESCRIBE"  # noqa: S105 - a vocabulary token, not a value
    SSM_GET = "SSM_GET"
    SSM_PUT = "SSM_PUT"
    ECS_RUN_TASK = "ECS_RUN_TASK"
    ECS_RUN_TASK_ROLE_OVERRIDE = "ECS_RUN_TASK_ROLE_OVERRIDE"
    ECS_DESCRIBE_TASKS = "ECS_DESCRIBE_TASKS"
    EC2_DESCRIBE_INTERFACES = "EC2_DESCRIBE_INTERFACES"
    ECS_EXECUTE_COMMAND = "ECS_EXECUTE_COMMAND"


class TargetKind(StrEnum):
    """The exact target class an operation is aimed at. Closed; resolved at execution."""

    BRONZE_PRODUCTION_PAYLOAD = "BRONZE_PRODUCTION_PAYLOAD"
    BRONZE_PRODUCTION_RECORD = "BRONZE_PRODUCTION_RECORD"
    PRODUCTION_CLAIM = "PRODUCTION_CLAIM"
    RUN_INDEX = "RUN_INDEX"
    SILVER_OBJECT = "SILVER_OBJECT"
    GOLD_OBJECT = "GOLD_OBJECT"
    MANIFEST_OBJECT = "MANIFEST_OBJECT"
    QUALIFICATION_OBJECT = "QUALIFICATION_OBJECT"
    CONTROL_BUCKET_OBJECT = "CONTROL_BUCKET_OBJECT"
    LICENSED_BUCKET = "LICENSED_BUCKET"
    PRODUCTION_SECRET = "PRODUCTION_SECRET"  # noqa: S105 - a vocabulary token, not a value
    QUALIFICATION_SECRET = "QUALIFICATION_SECRET"  # noqa: S105 - a vocabulary token, not a value
    OWN_BINDING_PARAMETER = "OWN_BINDING_PARAMETER"
    OTHER_ACTOR_BINDING_PARAMETER = "OTHER_ACTOR_BINDING_PARAMETER"
    ACQUISITION_BINDING_PARAMETER = "ACQUISITION_BINDING_PARAMETER"
    OWN_REVISION = "OWN_REVISION"
    OTHER_ACTOR_REVISION = "OTHER_ACTOR_REVISION"
    OTHER_REVISION = "OTHER_REVISION"
    OTHER_FAMILY = "OTHER_FAMILY"
    OTHER_CLUSTER = "OTHER_CLUSTER"
    OTHER_ACTOR_TASK_ROLE = "OTHER_ACTOR_TASK_ROLE"
    FOUNDATION_TASK_ROLE = "FOUNDATION_TASK_ROLE"
    OWN_TASK = "OWN_TASK"


class Expectation(StrEnum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"


class Layer(StrEnum):
    """What can decide the subcell (ADR-0036 s.3's layers)."""

    L3_RUNTIME = "L3_RUNTIME"
    L3_BY_R1 = "L3_BY_R1"
    BLOCKED = "BLOCKED"


class SubcellOutcome(StrEnum):
    """What one executed subcell established."""

    MATCHED = "MATCHED"
    INVERTED = "INVERTED"
    UNDECIDED = "UNDECIDED"


#: The exact dependency of every blocked subcell, by principal kind.
TASK_PROBE_DEPENDENCY: Final = (
    "a task-side permission probe entry (proposed ADR-0047 s.5): one closed verification "
    "entry that issues exactly one operation under the task role and prints a receipt; "
    "not implemented, and a human role is never a substitute for a task role"
)
DELETION_DEPENDENCY: Final = (
    "the deletion role has no execution path: no human may assume it and no deletion task "
    "definition exists (ADR-0007); its rehearsal is a separately authorized runbook step"
)
EXECUTE_COMMAND_DEPENDENCY: Final = (
    "a running task of this actor to execute into: ExecuteCommand against a task that does "
    "not exist is not a meaningful permission test, a task of ours runs only during an "
    "authorized R-1 launch, and executing into it during that launch is a later decision"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Subcell:
    """One executable (or blocked) subcell of a permission cell."""

    subcell_id: str
    cell_id: str
    principal: Principal
    operation: Operation
    target: TargetKind
    expectation: Expectation
    layer: Layer
    #: The ADR-0036 s.3 phrase this subcell is traced to.
    trace: str
    #: Subcells whose created object this one reads; each must be MATCHED first.
    requires: tuple[str, ...] = ()
    #: Whether a MATCHED (or inverted) operation may leave an object behind.
    creates: bool = False
    #: The exact dependency when the layer is BLOCKED.
    blocked_on: str | None = None

    def __post_init__(self) -> None:
        """A blocked subcell names its dependency; an executable one names none."""
        if (self.layer is Layer.BLOCKED) != (self.blocked_on is not None):
            raise ValueError("a blocked subcell names exactly its dependency")
        if self.layer is Layer.L3_BY_R1 and self.expectation is not Expectation.ALLOWED:
            raise ValueError("the R-1 launch evidences allowed launcher operations only")

    def document(self) -> dict[str, Any]:
        """The closed definition block."""
        return {
            "subcell_id": self.subcell_id,
            "cell_id": self.cell_id,
            "principal": self.principal.value,
            "operation": self.operation.value,
            "target": self.target.value,
            "expectation": self.expectation.value,
            "layer": self.layer.value,
            "trace": self.trace,
            "requires": list(self.requires),
            "creates": self.creates,
            "blocked_on": self.blocked_on,
        }


def _human_and_task(
    cell_id: str,
    prefix: str,
    human: Principal,
    task: Principal,
    operation: Operation,
    target: TargetKind,
    expectation: Expectation,
    trace: str,
    *,
    requires: tuple[str, ...] = (),
    creates: bool = False,
) -> tuple[Subcell, Subcell]:
    """The same operation under the human principal (L3) and the task role (blocked)."""
    return (
        Subcell(
            subcell_id=f"{prefix}-HUMAN",
            cell_id=cell_id,
            principal=human,
            operation=operation,
            target=target,
            expectation=expectation,
            layer=Layer.L3_RUNTIME,
            trace=trace,
            requires=requires,
            creates=creates,
        ),
        Subcell(
            subcell_id=f"{prefix}-TASK",
            cell_id=cell_id,
            principal=task,
            operation=operation,
            target=target,
            expectation=expectation,
            layer=Layer.BLOCKED,
            trace=trace,
            requires=tuple(r.replace("-HUMAN", "-HUMAN") for r in requires),
            creates=creates,
            blocked_on=TASK_PROBE_DEPENDENCY,
        ),
    )


_AH, _AT = Principal.ACQUISITION_HUMAN, Principal.ACQUISITION_TASK
_BH, _BT = Principal.BUILD_HUMAN, Principal.BUILD_TASK
_AL, _BL = Principal.ACQUISITION_LAUNCHER, Principal.BUILD_LAUNCHER
_ALLOW, _DENY = Expectation.ALLOWED, Expectation.DENIED

SUBCELLS: Final[tuple[Subcell, ...]] = (
    # ---- R-4: acquisition (human and task) ---------------------------------------------
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-SECRET-GET",
        _AH,
        _AT,
        Operation.SECRET_GET,
        TargetKind.PRODUCTION_SECRET,
        _ALLOW,
        "R-4 must succeed: GetSecretValue on the one secret",
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-PUT-PAYLOAD",
        _AH,
        _AT,
        Operation.S3_PUT_CONDITIONAL,
        TargetKind.BRONZE_PRODUCTION_PAYLOAD,
        _ALLOW,
        "R-4 must succeed: conditional PutObject to each production Bronze prefix (payloads)",
        creates=True,
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-PUT-RECORD",
        _AH,
        _AT,
        Operation.S3_PUT_CONDITIONAL,
        TargetKind.BRONZE_PRODUCTION_RECORD,
        _ALLOW,
        "R-4 must succeed: conditional PutObject to each production Bronze prefix (records)",
        creates=True,
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-PUT-CLAIM",
        _AH,
        _AT,
        Operation.S3_PUT_CONDITIONAL,
        TargetKind.PRODUCTION_CLAIM,
        _ALLOW,
        "R-4 must succeed: conditional PutObject to each production Bronze prefix (claims)",
        creates=True,
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-PUT-INDEX",
        _AH,
        _AT,
        Operation.S3_PUT_CONDITIONAL,
        TargetKind.RUN_INDEX,
        _ALLOW,
        "R-4 must succeed: conditional PutObject to _indexes/",
        creates=True,
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-GET-OWN-WRITE",
        _AH,
        _AT,
        Operation.S3_GET,
        TargetKind.BRONZE_PRODUCTION_PAYLOAD,
        _DENY,
        "R-4 must be refused: GetObject on its own write",
        requires=("R4-PUT-PAYLOAD-HUMAN",),
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-LIST",
        _AH,
        _AT,
        Operation.S3_LIST,
        TargetKind.LICENSED_BUCKET,
        _DENY,
        "R-4 must be refused: ListBucket",
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-DELETE-OWN-WRITE",
        _AH,
        _AT,
        Operation.S3_DELETE,
        TargetKind.BRONZE_PRODUCTION_PAYLOAD,
        _DENY,
        "R-4 must be refused: DeleteObject",
        requires=("R4-PUT-PAYLOAD-HUMAN",),
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-PUT-SILVER",
        _AH,
        _AT,
        Operation.S3_PUT_CONDITIONAL,
        TargetKind.SILVER_OBJECT,
        _DENY,
        "R-4 must be refused: PutObject to silver/",
        creates=True,
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-PUT-GOLD",
        _AH,
        _AT,
        Operation.S3_PUT_CONDITIONAL,
        TargetKind.GOLD_OBJECT,
        _DENY,
        "R-4 must be refused: PutObject to gold/",
        creates=True,
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-PUT-MANIFEST",
        _AH,
        _AT,
        Operation.S3_PUT_CONDITIONAL,
        TargetKind.MANIFEST_OBJECT,
        _DENY,
        "R-4 must be refused: PutObject to manifests/",
        creates=True,
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-PUT-QUALIFICATION",
        _AH,
        _AT,
        Operation.S3_PUT_CONDITIONAL,
        TargetKind.QUALIFICATION_OBJECT,
        _DENY,
        "R-4 must be refused: PutObject to any qualification prefix",
        creates=True,
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-PUT-CONTROL",
        _AH,
        _AT,
        Operation.S3_PUT_CONDITIONAL,
        TargetKind.CONTROL_BUCKET_OBJECT,
        _DENY,
        "R-4 must be refused: PutObject to the CONTROL bucket",
        creates=True,
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-SECRET-GET-QUALIFICATION",
        _AH,
        _AT,
        Operation.SECRET_GET,
        TargetKind.QUALIFICATION_SECRET,
        _DENY,
        "R-4 must be refused: GetSecretValue on the qualification secret",
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-SECRET-DESCRIBE",
        _AH,
        _AT,
        Operation.SECRET_DESCRIBE,
        TargetKind.PRODUCTION_SECRET,
        _DENY,
        "R-4 must be refused: DescribeSecret",
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-SSM-GET-OTHER",
        _AH,
        _AT,
        Operation.SSM_GET,
        TargetKind.OTHER_ACTOR_BINDING_PARAMETER,
        _DENY,
        "R-4 must be refused: ssm:GetParameter on the other actor's parameters",
    ),
    *_human_and_task(
        "R4-ACQUISITION",
        "R4-SSM-PUT-BINDING",
        _AH,
        _AT,
        Operation.SSM_PUT,
        TargetKind.OWN_BINDING_PARAMETER,
        _DENY,
        "R-4 must be refused: ssm:PutParameter on any binding parameter",
    ),
    # ---- R-5: build (human and task) ---------------------------------------------------
    *_human_and_task(
        "R5-BUILD",
        "R5-GET-PAYLOAD",
        _BH,
        _BT,
        Operation.S3_GET,
        TargetKind.BRONZE_PRODUCTION_PAYLOAD,
        _ALLOW,
        "R-5 must succeed: exact GetObject on a Bronze payload",
        requires=("R4-PUT-PAYLOAD-HUMAN",),
    ),
    *_human_and_task(
        "R5-BUILD",
        "R5-GET-RECORD",
        _BH,
        _BT,
        Operation.S3_GET,
        TargetKind.BRONZE_PRODUCTION_RECORD,
        _ALLOW,
        "R-5 must succeed: exact GetObject on a Bronze record",
        requires=("R4-PUT-RECORD-HUMAN",),
    ),
    *_human_and_task(
        "R5-BUILD",
        "R5-GET-LOCATOR",
        _BH,
        _BT,
        Operation.S3_GET,
        TargetKind.RUN_INDEX,
        _ALLOW,
        "R-5 must succeed: exact GetObject on a locator",
        requires=("R4-PUT-INDEX-HUMAN",),
    ),
    *_human_and_task(
        "R5-BUILD",
        "R5-PUT-SILVER",
        _BH,
        _BT,
        Operation.S3_PUT_CONDITIONAL,
        TargetKind.SILVER_OBJECT,
        _ALLOW,
        "R-5 must succeed: conditional PutObject to silver/",
        creates=True,
    ),
    *_human_and_task(
        "R5-BUILD",
        "R5-PUT-GOLD",
        _BH,
        _BT,
        Operation.S3_PUT_CONDITIONAL,
        TargetKind.GOLD_OBJECT,
        _ALLOW,
        "R-5 must succeed: conditional PutObject to gold/",
        creates=True,
    ),
    *_human_and_task(
        "R5-BUILD",
        "R5-PUT-MANIFEST",
        _BH,
        _BT,
        Operation.S3_PUT_CONDITIONAL,
        TargetKind.MANIFEST_OBJECT,
        _ALLOW,
        "R-5 must succeed: conditional PutObject to manifests/",
        creates=True,
    ),
    *_human_and_task(
        "R5-BUILD",
        "R5-GET-OWN-OUTPUT",
        _BH,
        _BT,
        Operation.S3_GET,
        TargetKind.SILVER_OBJECT,
        _ALLOW,
        "R-5 must succeed: GetObject on its own output",
        requires=("R5-PUT-SILVER-HUMAN",),
    ),
    *_human_and_task(
        "R5-BUILD",
        "R5-SECRET-GET",
        _BH,
        _BT,
        Operation.SECRET_GET,
        TargetKind.PRODUCTION_SECRET,
        _DENY,
        "R-5 must be refused: GetSecretValue on any secret",
    ),
    *_human_and_task(
        "R5-BUILD",
        "R5-LIST",
        _BH,
        _BT,
        Operation.S3_LIST,
        TargetKind.LICENSED_BUCKET,
        _DENY,
        "R-5 must be refused: ListBucket",
    ),
    *_human_and_task(
        "R5-BUILD",
        "R5-GET-CLAIM",
        _BH,
        _BT,
        Operation.S3_GET,
        TargetKind.PRODUCTION_CLAIM,
        _DENY,
        "R-5 must be refused: GetObject on a claim",
        requires=("R4-PUT-CLAIM-HUMAN",),
    ),
    *_human_and_task(
        "R5-BUILD",
        "R5-PUT-BRONZE",
        _BH,
        _BT,
        Operation.S3_PUT_CONDITIONAL,
        TargetKind.BRONZE_PRODUCTION_PAYLOAD,
        _DENY,
        "R-5 must be refused: PutObject to bronze/*",
        creates=True,
    ),
    *_human_and_task(
        "R5-BUILD",
        "R5-DELETE",
        _BH,
        _BT,
        Operation.S3_DELETE,
        TargetKind.SILVER_OBJECT,
        _DENY,
        "R-5 must be refused: DeleteObject",
        requires=("R5-PUT-SILVER-HUMAN",),
    ),
    *_human_and_task(
        "R5-BUILD",
        "R5-PUT-QUALIFICATION",
        _BH,
        _BT,
        Operation.S3_PUT_CONDITIONAL,
        TargetKind.QUALIFICATION_OBJECT,
        _DENY,
        "R-5 must be refused: any qualification prefix",
        creates=True,
    ),
    *_human_and_task(
        "R5-BUILD",
        "R5-PUT-CONTROL",
        _BH,
        _BT,
        Operation.S3_PUT_CONDITIONAL,
        TargetKind.CONTROL_BUCKET_OBJECT,
        _DENY,
        "R-5 must be refused: the CONTROL bucket",
        creates=True,
    ),
    *_human_and_task(
        "R5-BUILD",
        "R5-SSM-GET-ACQUISITION",
        _BH,
        _BT,
        Operation.SSM_GET,
        TargetKind.ACQUISITION_BINDING_PARAMETER,
        _DENY,
        "R-5 must be refused: ssm:GetParameter on the acquisition parameters",
    ),
    # ---- R-6: each launcher -----------------------------------------------------------
    *(
        Subcell(
            subcell_id=f"R6-{short}-{name}",
            cell_id="R6-LAUNCHERS",
            principal=launcher,
            operation=operation,
            target=target,
            expectation=expectation,
            layer=layer,
            trace=trace,
            blocked_on=EXECUTE_COMMAND_DEPENDENCY if layer is Layer.BLOCKED else None,
        )
        for short, launcher in (("ACQ", _AL), ("BLD", _BL))
        for name, operation, target, expectation, layer, trace in (
            (
                "RUN-OWN-REVISION",
                Operation.ECS_RUN_TASK,
                TargetKind.OWN_REVISION,
                _ALLOW,
                Layer.L3_BY_R1,
                "R-6 must succeed: RunTask of its own actor's exact revision on the one "
                "cluster with count = 1 (evidenced by the R-1 bootstrap launch)",
            ),
            (
                "DESCRIBE-OWN-TASK",
                Operation.ECS_DESCRIBE_TASKS,
                TargetKind.OWN_TASK,
                _ALLOW,
                Layer.L3_BY_R1,
                "R-6 must succeed: DescribeTasks (evidenced by the R-1 bootstrap launch)",
            ),
            (
                "DESCRIBE-INTERFACE",
                Operation.EC2_DESCRIBE_INTERFACES,
                TargetKind.OWN_TASK,
                _ALLOW,
                Layer.L3_BY_R1,
                "R-6 must succeed: DescribeNetworkInterfaces on the task's interface "
                "(evidenced by the R-1 bootstrap launch)",
            ),
            (
                "RUN-OTHER-ACTOR",
                Operation.ECS_RUN_TASK,
                TargetKind.OTHER_ACTOR_REVISION,
                _DENY,
                Layer.L3_RUNTIME,
                "R-6 must be refused: RunTask of the other actor's definition",
            ),
            (
                "RUN-OTHER-REVISION",
                Operation.ECS_RUN_TASK,
                TargetKind.OTHER_REVISION,
                _DENY,
                Layer.L3_RUNTIME,
                "R-6 must be refused: RunTask of another revision",
            ),
            (
                "RUN-OTHER-FAMILY",
                Operation.ECS_RUN_TASK,
                TargetKind.OTHER_FAMILY,
                _DENY,
                Layer.L3_RUNTIME,
                "R-6 must be refused: RunTask of another family",
            ),
            (
                "RUN-OTHER-CLUSTER",
                Operation.ECS_RUN_TASK,
                TargetKind.OTHER_CLUSTER,
                _DENY,
                Layer.L3_RUNTIME,
                "R-6 must be refused: RunTask on another cluster",
            ),
            (
                "OVERRIDE-OTHER-ROLE",
                Operation.ECS_RUN_TASK_ROLE_OVERRIDE,
                TargetKind.OTHER_ACTOR_TASK_ROLE,
                _DENY,
                Layer.L3_RUNTIME,
                "R-6 must be refused: a taskRoleArn override naming the other actor's task "
                "role (iam:PassRole refused)",
            ),
            (
                "EXECUTE-COMMAND",
                Operation.ECS_EXECUTE_COMMAND,
                TargetKind.OWN_TASK,
                _DENY,
                Layer.BLOCKED,
                "R-6 must be refused: ExecuteCommand",
            ),
        )
    ),
    # ---- R-7: qualification actors ----------------------------------------------------
    *(
        Subcell(
            subcell_id=f"R7-{short}-{name}",
            cell_id="R7-QUALIFICATION",
            principal=principal,
            operation=operation,
            target=target,
            expectation=_DENY,
            layer=Layer.L3_RUNTIME,
            trace=trace,
            creates=operation is Operation.S3_PUT_CONDITIONAL,
        )
        for short, principal in (
            ("ACQ", Principal.QUALIFICATION_ACQUISITION),
            ("ASSESS", Principal.QUALIFICATION_ASSESSMENT),
        )
        for name, operation, target, trace in (
            (
                "PUT-BRONZE-PRODUCTION",
                Operation.S3_PUT_CONDITIONAL,
                TargetKind.BRONZE_PRODUCTION_PAYLOAD,
                "R-7 must be refused: any production prefix (bronze/sharadar/* outside "
                "qualification/)",
            ),
            (
                "PUT-INDEX",
                Operation.S3_PUT_CONDITIONAL,
                TargetKind.RUN_INDEX,
                "R-7 must be refused: any production prefix (_indexes/)",
            ),
            (
                "PUT-SILVER",
                Operation.S3_PUT_CONDITIONAL,
                TargetKind.SILVER_OBJECT,
                "R-7 must be refused: any production prefix (silver/)",
            ),
            (
                "PUT-GOLD",
                Operation.S3_PUT_CONDITIONAL,
                TargetKind.GOLD_OBJECT,
                "R-7 must be refused: any production prefix (gold/)",
            ),
            (
                "PUT-MANIFEST",
                Operation.S3_PUT_CONDITIONAL,
                TargetKind.MANIFEST_OBJECT,
                "R-7 must be refused: any production prefix (manifests/)",
            ),
            (
                "SSM-GET-PRODUCTION",
                Operation.SSM_GET,
                TargetKind.ACQUISITION_BINDING_PARAMETER,
                "R-7 must be refused: any production parameter",
            ),
        )
    ),
    # ---- R-8: the deletion role -------------------------------------------------------
    Subcell(
        subcell_id="R8-LIST-AND-DELETE",
        cell_id="R8-DELETION",
        principal=Principal.DELETION_ROLE,
        operation=Operation.S3_DELETE,
        target=TargetKind.BRONZE_PRODUCTION_PAYLOAD,
        expectation=_ALLOW,
        layer=Layer.BLOCKED,
        trace="R-8 must succeed: list and delete under the widened prefixes (rehearsal "
        "against synthetic objects only)",
        blocked_on=DELETION_DEPENDENCY,
    ),
    Subcell(
        subcell_id="R8-GET",
        cell_id="R8-DELETION",
        principal=Principal.DELETION_ROLE,
        operation=Operation.S3_GET,
        target=TargetKind.BRONZE_PRODUCTION_PAYLOAD,
        expectation=_DENY,
        layer=Layer.BLOCKED,
        trace="R-8 must be refused: GetObject anywhere",
        blocked_on=DELETION_DEPENDENCY,
    ),
    # ---- R-9: the foundation task role ------------------------------------------------
    *(
        Subcell(
            subcell_id=f"R9-{short}-OVERRIDE-FOUNDATION-ROLE",
            cell_id="R9-FOUNDATION-TASK",
            principal=launcher,
            operation=Operation.ECS_RUN_TASK_ROLE_OVERRIDE,
            target=TargetKind.FOUNDATION_TASK_ROLE,
            expectation=_DENY,
            layer=Layer.L3_RUNTIME,
            trace="R-9 must be refused: not passable by either launcher (iam:PassRole refused "
            "by NotResource)",
        )
        for short, launcher in (("ACQ", _AL), ("BLD", _BL))
    ),
)

SUBCELL_BY_ID: Final[dict[str, Subcell]] = {s.subcell_id: s for s in SUBCELLS}
assert len(SUBCELL_BY_ID) == len(SUBCELLS)
for _subcell in SUBCELLS:
    for _required in _subcell.requires:
        assert _required in SUBCELL_BY_ID, _required


def subcells_of(cell_id: str) -> tuple[Subcell, ...]:
    """The subcells of one permission cell, in catalogue order."""
    return tuple(s for s in SUBCELLS if s.cell_id == cell_id)


def subcell(subcell_id: str) -> Subcell:
    """The definition of ``subcell_id``, or refuse."""
    try:
        return SUBCELL_BY_ID[subcell_id]
    except KeyError:
        raise ValueError("unknown permission subcell") from None


# ---------------------------------------------------------------------------
# Targets: the owner-held values no accepted binding carries, and the resolved target
# ---------------------------------------------------------------------------

PERMISSION_TARGETS_CONTRACT_ID: Final = "kalpamani-permission-targets/v1"
MAX_PERMISSION_TARGETS_BYTES: Final = 8 * 1024
_TARGETS_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "foundation_task_role_arn",
        "qualification_secret_arn",
        "control_bucket_name",
    }
)
_ROLE_ARN_RE: Final = re.compile(r"arn:aws[a-z-]*:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]{1,512}")
_SECRET_ARN_RE: Final = re.compile(
    r"arn:aws[a-z-]*:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:[A-Za-z0-9/_+=.@-]{1,512}"
)
_BUCKET_RE: Final = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")
_CLUSTER_ARN_RE: Final = re.compile(
    r"(arn:aws[a-z-]*:ecs:[a-z0-9-]+:[0-9]{12}:cluster/)([A-Za-z0-9_-]{1,255})"
)
_REVISION_ARN_RE: Final = re.compile(
    r"(arn:aws[a-z-]*:ecs:[a-z0-9-]+:[0-9]{12}:task-definition/)([A-Za-z0-9_-]{1,255}):([0-9]+)"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionTargets:
    """The three owner-held values the subcells need and no accepted binding carries.

    Read from a private file under the owner's root, never from the command line; never
    rendered. The foundation task role is R-9's target; the qualification secret is R-4's
    refused secret; the CONTROL bucket is the refused bucket of R-4 and R-5.
    """

    foundation_task_role_arn: str
    qualification_secret_arn: str
    control_bucket_name: str

    def __repr__(self) -> str:
        """No value."""
        return "PermissionTargets(...)"

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": PERMISSION_TARGETS_CONTRACT_ID,
            "foundation_task_role_arn": self.foundation_task_role_arn,
            "qualification_secret_arn": self.qualification_secret_arn,
            "control_bucket_name": self.control_bucket_name,
        }

    @property
    def digest(self) -> str:
        """The SHA-256 of the canonical document: what a statement binds the targets by."""
        return sha256_hex(canonical_bytes(self.document()))


def parse_permission_targets(raw: object) -> PermissionTargets:
    """The private targets document, parsed closed, or ``ValueError``."""
    document = (
        raw if type(raw) is dict else decode_document(raw, max_bytes=MAX_PERMISSION_TARGETS_BYTES)
    )
    if type(document) is not dict or set(document) != _TARGETS_FIELDS:
        raise ValueError("permission targets: closed field set")
    if (
        document["schema_version"] != RECORD_SCHEMA_VERSION
        or document["contract_id"] != PERMISSION_TARGETS_CONTRACT_ID
    ):
        raise ValueError("permission targets: contract")
    role = exact_str(document["foundation_task_role_arn"])
    secret = exact_str(document["qualification_secret_arn"])
    bucket = exact_str(document["control_bucket_name"])
    if (
        role is None
        or _ROLE_ARN_RE.fullmatch(role) is None
        or secret is None
        or _SECRET_ARN_RE.fullmatch(secret) is None
        or bucket is None
        or _BUCKET_RE.fullmatch(bucket) is None
    ):
        raise ValueError("permission targets: field")
    return PermissionTargets(
        foundation_task_role_arn=role, qualification_secret_arn=secret, control_bucket_name=bucket
    )


#: The fixed synthetic marker every created object carries. Never a vendor row.
SYNTHETIC_MARKER: Final = b"kalpamani-permission-synthetic-marker-" + b"0" * 26
assert len(SYNTHETIC_MARKER) == 64
#: The dataset every synthetic Bronze key names.
_SYNTHETIC_DATASET: Final = "tickers"
_STAMP_RE: Final = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{4}")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedTarget:
    """One subcell's exact target, resolved for one session stamp. Never rendered whole.

    ``digest`` is the SHA-256 of the canonical target document -- what a statement and
    therefore an authorization binds: the exact bucket and key, name or ARN, and for a
    launch the cluster, definition, override role and the network placement the request
    carries.
    """

    kind: TargetKind
    #: For an S3 operation: the bucket and the physical key (``None`` for a listing).
    bucket: str | None = None
    key: str | None = None
    #: For a secret, parameter, cluster/definition or role: the exact name or ARN.
    name: str | None = None
    #: For a launch: the cluster, the task definition and (an override) the task role.
    cluster_arn: str | None = None
    task_definition_arn: str | None = None
    task_role_arn: str | None = None
    #: For a launch: the placement the request must carry (FARGATE / awsvpc).
    subnet_id: str | None = None
    security_group_ids: tuple[str, ...] = ()
    assign_public_ip: bool | None = None
    platform_version: str | None = None

    def __repr__(self) -> str:
        """The kind only."""
        return f"ResolvedTarget(kind={self.kind.value!r})"

    def document(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "bucket": self.bucket,
            "key": self.key,
            "name": self.name,
            "cluster_arn": self.cluster_arn,
            "task_definition_arn": self.task_definition_arn,
            "task_role_arn": self.task_role_arn,
            "subnet_id": self.subnet_id,
            "security_group_ids": list(self.security_group_ids),
            "assign_public_ip": self.assign_public_ip,
            "platform_version": self.platform_version,
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.document()))


def synthetic_run_id(stamp: str) -> str:
    """The run identity every synthetic Bronze object of one session names."""
    if _STAMP_RE.fullmatch(stamp) is None:
        raise ValueError("a session stamp is required")
    return f"verification-{stamp}"


def started_by_of(stamp: str) -> str:
    """The ``startedBy`` every launching subcell of one session tags its request with.

    An ambiguous launch answer -- a timeout, a network failure, a failure entry -- leaves
    the question *did a task start?* open; the cleanup answers it by listing the cluster's
    tasks by this tag, never by launching again.
    """
    if _STAMP_RE.fullmatch(stamp) is None:
        raise ValueError("a session stamp is required")
    return f"kalpamani-permission-{stamp}"


def resolve_target(
    cell: Subcell,
    *,
    stamp: str,
    licensed_bucket: str,
    inputs: LaunchInputs,
    targets: PermissionTargets,
    production_secret: str | None,
    prerequisites: Mapping[str, PermissionRecord] | None = None,
) -> ResolvedTarget:
    """The exact target of ``cell`` for this session, from the bindings and registration.

    Every synthetic S3 key is a real key shape of its namespace (built by the accepted key
    builders) carrying the session stamp in its run identity and the marker's digest as its
    content address, so it lies exactly where the policy statement under test applies and
    nowhere a production object could be. **A subcell that reads or deletes an object a
    prerequisite subcell created takes the exact bucket and key that prerequisite's bound
    record established** -- never a key derived from its own stamp -- so the object it
    exercises is the one that exists. Launch targets are the registered ones (own) or
    deterministic derivations of them (another revision, another cluster) that the exact-
    resource policies cannot name, each with the actor's registered placement.
    """
    actor = PRINCIPAL_ACTOR[cell.principal]
    digest = sha256_hex(SYNTHETIC_MARKER)
    run_id = synthetic_run_id(stamp)
    kind = cell.target
    if cell.requires:
        required = cell.requires[0]
        record = (prerequisites or {}).get(required)
        if (
            record is None
            or record.subcell_id != required
            or record.outcome is not SubcellOutcome.MATCHED
            or record.created_key is None
            or record.created_bucket is None
            or record.target is not kind
        ):
            raise ValueError("the prerequisite object is not established by a bound record")
        return ResolvedTarget(kind=kind, bucket=record.created_bucket, key=record.created_key)
    if kind is TargetKind.BRONZE_PRODUCTION_PAYLOAD:
        key = production_payload_key_for_digest(dataset=_SYNTHETIC_DATASET, content_sha256=digest)
        return ResolvedTarget(kind=kind, bucket=licensed_bucket, key=physical_key(key))
    if kind is TargetKind.BRONZE_PRODUCTION_RECORD:
        key = production_acquisition_key_for_digest(
            dataset=_SYNTHETIC_DATASET,
            payload_digest=digest,
            run_id=run_id,
            ordinal=1,
            content_sha256=digest,
        )
        return ResolvedTarget(kind=kind, bucket=licensed_bucket, key=physical_key(key))
    if kind is TargetKind.PRODUCTION_CLAIM:
        key = production_claim_key(
            payload_digest=digest, run_id=run_id, ordinal=1, claim=SYNTHETIC_MARKER
        )
        return ResolvedTarget(kind=kind, bucket=licensed_bucket, key=physical_key(key))
    if kind is TargetKind.RUN_INDEX:
        key = run_locator_key(run_id=run_id, payload=SYNTHETIC_MARKER)
        return ResolvedTarget(kind=kind, bucket=licensed_bucket, key=physical_key(key))
    if kind in (TargetKind.SILVER_OBJECT, TargetKind.GOLD_OBJECT, TargetKind.MANIFEST_OBJECT):
        namespace = {
            TargetKind.SILVER_OBJECT: "silver/sharadar/tickers/objects/sha256",
            TargetKind.GOLD_OBJECT: "gold/sharadar/verification/objects/sha256",
            TargetKind.MANIFEST_OBJECT: "manifests/sharadar/builds",
        }[kind]
        suffix = f"{run_id}.json" if kind is TargetKind.MANIFEST_OBJECT else digest
        return ResolvedTarget(kind=kind, bucket=licensed_bucket, key=f"{namespace}/{suffix}")
    if kind is TargetKind.QUALIFICATION_OBJECT:
        return ResolvedTarget(
            kind=kind,
            bucket=licensed_bucket,
            key=f"qualification/sharadar/_verification/{stamp}/marker",
        )
    if kind is TargetKind.CONTROL_BUCKET_OBJECT:
        return ResolvedTarget(
            kind=kind, bucket=targets.control_bucket_name, key=f"_verification/{stamp}/marker"
        )
    if kind is TargetKind.LICENSED_BUCKET:
        return ResolvedTarget(kind=kind, bucket=licensed_bucket)
    if kind is TargetKind.PRODUCTION_SECRET:
        if production_secret is None:
            raise ValueError("the production secret is named by the acquisition configuration")
        return ResolvedTarget(kind=kind, name=production_secret)
    if kind is TargetKind.QUALIFICATION_SECRET:
        return ResolvedTarget(kind=kind, name=targets.qualification_secret_arn)
    if kind is TargetKind.OWN_BINDING_PARAMETER:
        assert actor is not None
        return ResolvedTarget(kind=kind, name=constants_for(actor).binding_parameter)
    if kind is TargetKind.OTHER_ACTOR_BINDING_PARAMETER:
        assert actor is not None
        other = (
            ProductionActor.BUILD
            if actor is ProductionActor.ACQUISITION
            else ProductionActor.ACQUISITION
        )
        return ResolvedTarget(kind=kind, name=constants_for(other).binding_parameter)
    if kind is TargetKind.ACQUISITION_BINDING_PARAMETER:
        return ResolvedTarget(
            kind=kind, name=constants_for(ProductionActor.ACQUISITION).binding_parameter
        )
    # Launch targets.
    assert actor is not None
    other_actor = (
        ProductionActor.BUILD
        if actor is ProductionActor.ACQUISITION
        else ProductionActor.ACQUISITION
    )
    own = inputs.targets[(actor, LaunchKind.VERIFICATION)].task_definition_arn
    match = _REVISION_ARN_RE.fullmatch(own)
    if match is None:
        raise ValueError("the registered revision is not a task-definition ARN")
    cluster = inputs.cluster_arn
    placement: dict[str, Any] = {
        "subnet_id": inputs.subnet_ids[actor],
        "security_group_ids": tuple(inputs.security_group_ids[actor]),
        "assign_public_ip": actor is ProductionActor.ACQUISITION,
        "platform_version": inputs.platform_version,
    }
    if kind is TargetKind.OWN_REVISION or kind is TargetKind.OWN_TASK:
        return ResolvedTarget(kind=kind, cluster_arn=cluster, task_definition_arn=own, **placement)
    if kind is TargetKind.OTHER_ACTOR_REVISION:
        return ResolvedTarget(
            kind=kind,
            cluster_arn=cluster,
            task_definition_arn=inputs.targets[
                (other_actor, LaunchKind.VERIFICATION)
            ].task_definition_arn,
            **placement,
        )
    if kind is TargetKind.OTHER_REVISION:
        return ResolvedTarget(
            kind=kind,
            cluster_arn=cluster,
            task_definition_arn=f"{match.group(1)}{match.group(2)}:{int(match.group(3)) + 1}",
            **placement,
        )
    if kind is TargetKind.OTHER_FAMILY:
        return ResolvedTarget(
            kind=kind,
            cluster_arn=cluster,
            task_definition_arn=f"{match.group(1)}{match.group(2)}-verification-other:1",
            **placement,
        )
    if kind is TargetKind.OTHER_CLUSTER:
        cluster_match = _CLUSTER_ARN_RE.fullmatch(cluster)
        if cluster_match is None:
            raise ValueError("the registered cluster is not a cluster ARN")
        return ResolvedTarget(
            kind=kind,
            cluster_arn=f"{cluster_match.group(1)}{cluster_match.group(2)}-verification-other",
            task_definition_arn=own,
            **placement,
        )
    if kind is TargetKind.OTHER_ACTOR_TASK_ROLE:
        return ResolvedTarget(
            kind=kind,
            cluster_arn=cluster,
            task_definition_arn=own,
            task_role_arn=inputs.task_role_arns[other_actor],
            **placement,
        )
    if kind is TargetKind.FOUNDATION_TASK_ROLE:
        return ResolvedTarget(
            kind=kind,
            cluster_arn=cluster,
            task_definition_arn=own,
            task_role_arn=targets.foundation_task_role_arn,
            **placement,
        )
    raise ValueError("unresolvable target kind")  # pragma: no cover - closed vocabulary


# ---------------------------------------------------------------------------
# The client protocol, the engine, the records
# ---------------------------------------------------------------------------


class PermissionClient(Protocol):
    """One profile's clients, each operation one call with one transport attempt."""

    def put_object(
        self, bucket: str, key: str, body: bytes, *, if_none_match: bool
    ) -> Observation: ...
    def get_object(self, bucket: str, key: str) -> Observation: ...
    def head_object(self, bucket: str, key: str) -> Observation: ...
    def delete_object(self, bucket: str, key: str) -> Observation: ...
    def list_objects(self, bucket: str) -> Observation: ...
    def get_secret_value(self, secret_id: str) -> Observation: ...
    def describe_secret(self, secret_id: str) -> Observation: ...
    def get_parameter(self, name: str) -> Observation: ...
    def put_parameter(self, name: str, value: str) -> Observation: ...
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
    ) -> Observation: ...
    def stop_task(self, *, cluster_arn: str, task_arn: str) -> Observation: ...
    def list_tasks(
        self, *, cluster_arn: str, started_by: str, next_token: str | None
    ) -> Observation: ...
    def describe_tasks(self, *, cluster_arn: str, task_arns: tuple[str, ...]) -> Observation: ...
    def execute_command(self, *, cluster_arn: str, task_arn: str) -> Observation: ...


#: The success class each operation expects when ALLOWED.
_SUCCESS_CLASS: Final[dict[Operation, ObservedClass]] = {
    Operation.S3_PUT_CONDITIONAL: ObservedClass.OK_200,
    Operation.S3_GET: ObservedClass.OK_200,
    Operation.S3_LIST: ObservedClass.OK_200,
    Operation.S3_DELETE: ObservedClass.OK_204,
    Operation.SECRET_GET: ObservedClass.OK_200,
    Operation.SECRET_DESCRIBE: ObservedClass.OK_200,
    Operation.SSM_GET: ObservedClass.OK_200,
    Operation.SSM_PUT: ObservedClass.OK_200,
    Operation.ECS_RUN_TASK: ObservedClass.OK_200,
    Operation.ECS_RUN_TASK_ROLE_OVERRIDE: ObservedClass.OK_200,
    Operation.ECS_DESCRIBE_TASKS: ObservedClass.OK_200,
    Operation.EC2_DESCRIBE_INTERFACES: ObservedClass.OK_200,
    Operation.ECS_EXECUTE_COMMAND: ObservedClass.OK_200,
}
#: The classes that decide a DENIED expectation as matched: an access denial, whichever
#: policy refused. Which policy refused is R-3's question, not these cells'.
_DENIAL_CLASSES: Final[frozenset[ObservedClass]] = frozenset(
    {
        ObservedClass.DENIED_RESOURCE_POLICY,
        ObservedClass.DENIED_IDENTITY_POLICY,
        ObservedClass.DENIED_OTHER,
    }
)
#: The classes that decide nothing: the request never got an authorization answer.
_UNDECIDED_CLASSES: Final[frozenset[ObservedClass]] = frozenset(
    {
        ObservedClass.AUTHENTICATION_FAILURE,
        ObservedClass.NO_SUCH_BUCKET,
        ObservedClass.THROTTLED,
        ObservedClass.TIMEOUT,
        ObservedClass.NETWORK_FAILURE,
        ObservedClass.AMBIGUOUS,
        ObservedClass.NOT_EXERCISED,
    }
)
#: The classes after which a write or a launch definitely did NOT commit: the request was
#: refused before it acted, or it addressed nothing. Every other non-success class leaves
#: the question open, and an open question is a possibly committed write (or launch) the
#: cleanup must settle.
_DEFINITELY_NOT_COMMITTED: Final[frozenset[ObservedClass]] = frozenset(
    {
        *_DENIAL_CLASSES,
        ObservedClass.AUTHENTICATION_FAILURE,
        ObservedClass.NO_SUCH_BUCKET,
        ObservedClass.NOT_FOUND_404,
        ObservedClass.NOT_IMPLEMENTED_501,
        ObservedClass.NO_SUCH_UPLOAD,
    }
)
#: The RunTask operations, whose unexpected success is a task to stop.
_LAUNCHING: Final[frozenset[Operation]] = frozenset(
    {Operation.ECS_RUN_TASK, Operation.ECS_RUN_TASK_ROLE_OVERRIDE}
)
#: A ``RunTask`` with ``count = 1`` returns at most one task; every task an answer carries
#: is accounted for up to this bound, and an answer carrying more is not credited beyond it.
MAX_RETURNED_TASKS: Final = 4
#: Operations per executed subcell: the operation, plus one StopTask per returned task.
SUBCELL_OPERATION_BUDGET: Final = 1 + MAX_RETURNED_TASKS
#: Cleanup operations per created key: one DeleteObject and one HeadObject.
CLEANUP_OPERATIONS_PER_KEY: Final = 2
#: Bounded discovery of a launching attempt's tasks: the cluster is listed by the attempt's
#: ``startedBy`` tag and by nothing else -- the ``ListTasks`` contract makes ``startedBy``
#: the only filter when it is used, so no ``desiredStatus``, ``family``, ``serviceName``,
#: ``launchType`` or ``containerInstance`` accompanies it -- following ``nextToken`` for at
#: most this many pages. A page bound reached with a token remaining is an INCOMPLETE
#: discovery; a listing that did not answer is a FAILED discovery; a complete discovery
#: that found nothing is NOT proof of absence -- the launch stays unresolved. **A task that
#: stopped before discovery is discoverable only while ECS still returns it** (recently
#: stopped tasks may appear; older ones do not, and listing them by status would need a
#: second filter the contract refuses beside ``startedBy``): such a launch stays
#: unresolved, and the mechanism that would settle it is outside this decision (s.5).
DISCOVERY_MAX_PAGES: Final = 3
#: Cleanup operations per launching attempt: the discovery listings, then per task one
#: DescribeTasks and, when it is not STOPPED, one StopTask.
CLEANUP_OPERATIONS_PER_TASK_MAX: Final = DISCOVERY_MAX_PAGES + 2 * MAX_RETURNED_TASKS
#: The ECS ``lastStatus`` that alone confirms a task is no longer running.
TASK_STOPPED_STATUS: Final = "STOPPED"


def decide(cell: Subcell, observed: ObservedClass) -> SubcellOutcome:
    """The outcome one classified answer establishes for ``cell``."""
    if observed in _UNDECIDED_CLASSES:
        return SubcellOutcome.UNDECIDED
    success = observed is _SUCCESS_CLASS[cell.operation]
    denied = observed in _DENIAL_CLASSES
    if cell.expectation is Expectation.ALLOWED:
        if success:
            return SubcellOutcome.MATCHED
        return SubcellOutcome.INVERTED if denied else SubcellOutcome.UNDECIDED
    if denied:
        return SubcellOutcome.MATCHED
    return SubcellOutcome.INVERTED if success else SubcellOutcome.UNDECIDED


PERMISSION_STATEMENT_CONTRACT_ID: Final = "kalpamani-permission-statement/v1"
PERMISSION_AUTHORIZATION_CONTRACT_ID: Final = "kalpamani-permission-authorization/v1"
PERMISSION_CONSUMPTION_CONTRACT_ID: Final = "kalpamani-permission-consumption/v1"
PERMISSION_ATTEMPT_CONTRACT_ID: Final = "kalpamani-permission-attempt/v1"
PERMISSION_RECORD_CONTRACT_ID: Final = "kalpamani-permission-record/v1"
PERMISSION_CLEANUP_CONTRACT_ID: Final = "kalpamani-permission-cleanup/v1"
MAX_PERMISSION_RECORD_BYTES: Final = 32 * 1024
#: An authorization is for now: it expires, and a stale one is refused.
MAX_AUTHORIZATION_VALIDITY: Final = timedelta(hours=24)


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionBinding:
    """What a permission record binds its evidence to. Digests only.

    ``policy_declaration_sha256`` is :func:`declaration_digest` over the tracked
    production declarations (the identity policies, bootstrap policies, permission sets,
    task roles and the bucket-policy statements) -- a change to any of them makes every
    permission record HISTORICAL, exactly as ADR-0036 s.3 and readiness s.4.6 require;
    ``registration_sha256`` is the digest of the launch-inputs record the targets were
    resolved from; ``targets_sha256`` is the digest of the owner's private targets document
    (the foundation task role, the qualification secret, the CONTROL bucket) the targets
    were resolved from -- a changed targets document changes the binding, and every record
    made under the old one is HISTORICAL. A binding cannot be computed without every one
    of its inputs present now, so a missing input holds every recorded result UNBOUND
    rather than preserving a PASSED.
    """

    environment_binding_sha256: str
    policy_declaration_sha256: str
    registration_sha256: str
    targets_sha256: str
    partition: str
    region: str

    def document(self) -> dict[str, Any]:
        return {
            "environment_binding_sha256": self.environment_binding_sha256,
            "policy_declaration_sha256": self.policy_declaration_sha256,
            "registration_sha256": self.registration_sha256,
            "targets_sha256": self.targets_sha256,
            "partition": self.partition,
            "region": self.region,
        }


def declaration_digest(paths: Iterable[Path]) -> str:
    """One digest over the named declaration files: each name, then its bytes, in order."""
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.name):
        digest.update(path.name.encode("utf-8") + b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def _binding_from(document: object) -> PermissionBinding:
    fields_ = {
        "environment_binding_sha256",
        "policy_declaration_sha256",
        "partition",
        "region",
        "registration_sha256",
        "targets_sha256",
    }
    if type(document) is not dict or set(document) != fields_:
        raise ValueError("permission binding: closed field set")
    values = {name: exact_str(document[name]) for name in fields_}
    if any(v is None for v in values.values()):
        raise ValueError("permission binding: field")
    for name in (
        "environment_binding_sha256",
        "policy_declaration_sha256",
        "registration_sha256",
        "targets_sha256",
    ):
        if hex_digest(values[name]) is None:
            raise ValueError("permission binding: digest")
    return PermissionBinding(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionContext:
    """What is admitted NOW: the binding and everything a target is resolved from.

    Built by the tool (execution, cleanup) and by the cell runner (derivation) from the
    same inputs -- the environment binding, the tracked declarations, the launch-inputs
    registration, the private targets document and, when present, the acquisition
    configuration -- so the one validator below holds every recorded result to the same
    current state. Never rendered.
    """

    binding: PermissionBinding
    licensed_bucket: str
    inputs: LaunchInputs
    targets: PermissionTargets
    production_secret: str | None

    def __repr__(self) -> str:
        return "PermissionContext(...)"

    def resolve(
        self, cell: Subcell, *, stamp: str, prerequisites: Mapping[str, PermissionRecord]
    ) -> ResolvedTarget:
        """The exact target of ``cell`` for ``stamp`` from what is admitted now."""
        return resolve_target(
            cell,
            stamp=stamp,
            licensed_bucket=self.licensed_bucket,
            inputs=self.inputs,
            targets=self.targets,
            production_secret=self.production_secret,
            prerequisites=prerequisites,
        )


def _prerequisites_from(document: object) -> dict[str, str]:
    """``{required subcell id: the digest of its bound record}``, closed."""
    if type(document) is not dict:
        raise ValueError("permission record: prerequisites")
    out: dict[str, str] = {}
    for name, value in document.items():
        if type(name) is not str or name not in SUBCELL_BY_ID or hex_digest(value) is None:
            raise ValueError("permission record: prerequisites")
        out[name] = str(value)
    return out


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionStatement:
    """The reviewable statement of one subcell execution: what an authorization binds.

    Written by ``--prepare-subcell``: the subcell (principal, operation, target class), the
    exact resolved target's digest, the session stamp the target was resolved for, the
    binding (environment, declarations, registration), the digest of the private targets
    document the target came from, and the bound prerequisite records (by digest) whose
    objects the operation reads. Execution recomputes it and refuses any difference, so
    a changed target, targets document, declaration, registration or prerequisite is
    not what the owner authorized.
    """

    subcell_id: str
    principal: Principal
    operation: Operation
    target: TargetKind
    target_sha256: str
    stamp: str
    binding: PermissionBinding
    targets_sha256: str
    prerequisites: dict[str, str]
    prepared_at: datetime

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": PERMISSION_STATEMENT_CONTRACT_ID,
            "subcell_id": self.subcell_id,
            "principal": self.principal.value,
            "operation": self.operation.value,
            "target": self.target.value,
            "target_sha256": self.target_sha256,
            "stamp": self.stamp,
            "binding": self.binding.document(),
            "targets_sha256": self.targets_sha256,
            "prerequisites": dict(sorted(self.prerequisites.items())),
            "prepared_at": self.prepared_at.isoformat(),
        }

    @property
    def digest(self) -> str:
        """The SHA-256 of the canonical document -- the value an authorization names."""
        return sha256_hex(canonical_bytes(self.document()))


def statement_for(
    cell: Subcell,
    *,
    target: ResolvedTarget,
    stamp: str,
    binding: PermissionBinding,
    targets_sha256: str,
    prerequisites: Mapping[str, PermissionRecord],
    prepared_at: datetime,
) -> PermissionStatement:
    """The statement of executing ``cell`` against ``target`` under ``binding`` now."""
    return PermissionStatement(
        subcell_id=cell.subcell_id,
        principal=cell.principal,
        operation=cell.operation,
        target=cell.target,
        target_sha256=target.digest,
        stamp=stamp,
        binding=binding,
        targets_sha256=targets_sha256,
        prerequisites={required: prerequisites[required].digest for required in cell.requires},
        prepared_at=prepared_at,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionAuthorization:
    """The owner's written authorization for exactly one execution of one statement."""

    subcell_id: str
    statement_sha256: str
    issued_at: datetime
    expires_at: datetime

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": PERMISSION_AUTHORIZATION_CONTRACT_ID,
            "subcell_id": self.subcell_id,
            "statement_sha256": self.statement_sha256,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    @property
    def digest(self) -> str:
        """The SHA-256 of the canonical document -- what the store consumes."""
        return sha256_hex(canonical_bytes(self.document()))

    def valid_at(self, now: datetime) -> bool:
        return self.issued_at <= now < self.expires_at


class AuthorizationDefect(StrEnum):
    """Why an authorization does not admit an execution. Closed."""

    MALFORMED = "MALFORMED"
    SUBCELL_MISMATCH = "SUBCELL_MISMATCH"
    STATEMENT_MISMATCH = "STATEMENT_MISMATCH"
    NOT_YET_VALID = "NOT_YET_VALID"
    EXPIRED = "EXPIRED"


_AUTHORIZATION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "subcell_id",
        "statement_sha256",
        "issued_at",
        "expires_at",
    }
)


def parse_permission_authorization(
    raw: object, *, subcell_id: str, statement_sha256: str | None, now: datetime
) -> PermissionAuthorization:
    """The authorization for THIS subcell and THIS statement, valid now, or ``ValueError``.

    The statement digest is the one preparation printed and execution recomputes; an
    authorization naming any other refuses before anything is consumed. ``None`` reads
    the digest the authorization names without holding it yet (execution then finds the
    prepared statement it names, recomputes it, and holds the digest to the result).
    """
    try:
        d = _document(raw, PERMISSION_AUTHORIZATION_CONTRACT_ID, _AUTHORIZATION_FIELDS)
    except ValueError:
        raise ValueError(AuthorizationDefect.MALFORMED.value) from None
    cell_id = exact_str(d["subcell_id"])
    digest = hex_digest(d["statement_sha256"])
    issued_at = instant(d["issued_at"])
    expires_at = instant(d["expires_at"])
    if (
        cell_id is None
        or digest is None
        or issued_at is None
        or expires_at is None
        or expires_at <= issued_at
        or expires_at - issued_at > MAX_AUTHORIZATION_VALIDITY
    ):
        raise ValueError(AuthorizationDefect.MALFORMED.value)
    if cell_id != subcell_id:
        raise ValueError(AuthorizationDefect.SUBCELL_MISMATCH.value)
    if statement_sha256 is not None and digest != statement_sha256:
        raise ValueError(AuthorizationDefect.STATEMENT_MISMATCH.value)
    if now < issued_at:
        raise ValueError(AuthorizationDefect.NOT_YET_VALID.value)
    if now >= expires_at:
        raise ValueError(AuthorizationDefect.EXPIRED.value)
    return PermissionAuthorization(
        subcell_id=cell_id, statement_sha256=digest, issued_at=issued_at, expires_at=expires_at
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionConsumption:
    """The durable consumption of one authorization, written beside the ledger.

    Created exclusively (``LaunchStore.consume``) before the attempt it admits and never
    removed; a record binds only when the consumption of its authorization exists, names
    its subcell and statement, and was consumed no later than the attempt started.
    """

    subcell_id: str
    statement_sha256: str
    authorization_sha256: str
    consumed_at: datetime

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": PERMISSION_CONSUMPTION_CONTRACT_ID,
            "subcell_id": self.subcell_id,
            "statement_sha256": self.statement_sha256,
            "authorization_sha256": self.authorization_sha256,
            "consumed_at": self.consumed_at.isoformat(),
        }


_CONSUMPTION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "subcell_id",
        "statement_sha256",
        "authorization_sha256",
        "consumed_at",
    }
)


def parse_permission_consumption(raw: object) -> PermissionConsumption:
    """A consumption record, parsed closed."""
    d = _document(raw, PERMISSION_CONSUMPTION_CONTRACT_ID, _CONSUMPTION_FIELDS)
    cell_id = exact_str(d["subcell_id"])
    consumed_at = instant(d["consumed_at"])
    if cell_id is None or cell_id not in SUBCELL_BY_ID or consumed_at is None:
        raise ValueError("permission consumption: field")
    return PermissionConsumption(
        subcell_id=cell_id,
        statement_sha256=_digest_field(d["statement_sha256"]),
        authorization_sha256=_digest_field(d["authorization_sha256"]),
        consumed_at=consumed_at,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionAttempt:
    """Written **before** the operation: what is attempted, and the object it may create.

    ``digest`` is the attempt's identity: the record that answers it names it, and the
    cleanup entry that settles its object names it. Two attempts are never joined by
    their order in time.
    """

    subcell_id: str
    principal: Principal
    stamp: str
    authorization_sha256: str
    statement_sha256: str
    bucket: str | None
    key: str | None
    started_at: datetime
    binding: PermissionBinding

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": PERMISSION_ATTEMPT_CONTRACT_ID,
            "subcell_id": self.subcell_id,
            "principal": self.principal.value,
            "stamp": self.stamp,
            "authorization_sha256": self.authorization_sha256,
            "statement_sha256": self.statement_sha256,
            "bucket": self.bucket,
            "key": self.key,
            "started_at": self.started_at.isoformat(),
            "binding": self.binding.document(),
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.document()))


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionRecord:
    """What one executed subcell established. Classes, counts, digests -- no value.

    ``created_key`` is the object the operation definitely created; ``possibly_created``
    says the answer left the write open (a timeout, a network failure, an ambiguous
    status) and the cleanup must settle the same key; ``started_task_ids`` are every task
    a launching answer returned, ``stop_acknowledged_ids`` those whose immediate StopTask
    was acknowledged -- **an acknowledgement is not a termination**, which only a later
    ``DescribeTasks`` in the cleanup confirms -- and ``possibly_started`` says the launching
    answer left the launch open, so the cleanup lists the cluster by ``started_by``.
    """

    subcell_id: str
    cell_id: str
    principal: Principal
    operation: Operation
    target: TargetKind
    expectation: Expectation
    stamp: str
    attempt_sha256: str
    authorization_sha256: str
    prerequisites: dict[str, str]
    observed: ObservedClass
    outcome: SubcellOutcome
    #: The physical bucket and key this subcell definitely created (when ``creates``).
    created_bucket: str | None
    created_key: str | None
    possibly_created: bool
    #: For a launching operation: every returned task, the acknowledged stops, the tag.
    started_task_ids: tuple[str, ...]
    stop_acknowledged_ids: tuple[str, ...]
    started_by: str | None
    possibly_started: bool
    operations: int
    identity_verified: bool
    started_at: datetime
    finished_at: datetime
    binding: PermissionBinding

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": PERMISSION_RECORD_CONTRACT_ID,
            "subcell_id": self.subcell_id,
            "cell_id": self.cell_id,
            "principal": self.principal.value,
            "operation": self.operation.value,
            "target": self.target.value,
            "expectation": self.expectation.value,
            "stamp": self.stamp,
            "attempt_sha256": self.attempt_sha256,
            "authorization_sha256": self.authorization_sha256,
            "prerequisites": dict(sorted(self.prerequisites.items())),
            "observed": self.observed.value,
            "outcome": self.outcome.value,
            "created_bucket": self.created_bucket,
            "created_key": self.created_key,
            "possibly_created": self.possibly_created,
            "started_task_ids": list(self.started_task_ids),
            "stop_acknowledged_ids": list(self.stop_acknowledged_ids),
            "started_by": self.started_by,
            "possibly_started": self.possibly_started,
            "operations": self.operations,
            "identity_verified": self.identity_verified,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "binding": self.binding.document(),
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.document()))

    @property
    def object_open(self) -> bool:
        """Whether an object of this record still needs settling by the cleanup."""
        return self.created_key is not None or self.possibly_created

    @property
    def launch_open(self) -> bool:
        """Whether a task of this record still needs settling by the cleanup."""
        return bool(self.started_task_ids) or self.possibly_started


@dataclass(frozen=True, slots=True, kw_only=True)
class CleanupKey:
    """One object the cleanup settled: the exact bucket and key, and the attempt it answers."""

    bucket: str
    key: str
    attempt_sha256: str
    delete_observed: ObservedClass
    confirmation_observed: ObservedClass | None
    confirmed_absent: bool

    def document(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "key": self.key,
            "attempt_sha256": self.attempt_sha256,
            "delete_observed": self.delete_observed.value,
            "confirmation_observed": (
                None if self.confirmation_observed is None else self.confirmation_observed.value
            ),
            "confirmed_absent": self.confirmed_absent,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class CleanupTasks:
    """One launching attempt's tasks: bounded discovery, then describing and stopping.

    ``task_ids`` are the tasks known for the attempt (recorded, or discovered by its
    ``started_by`` tag under each desired status, page by page); ``stopped_ids`` those a
    ``DescribeTasks`` answered ``STOPPED``; every other known task is residue, stopped once
    more here and still not confirmed. ``listings`` counts the discovery calls;
    ``discovery_failed`` says one did not answer; ``discovery_incomplete`` says a page bound
    was reached with a token remaining. **A launch is settled only by termination
    evidence for every task it is known to have started; a discovery that found nothing
    settles nothing** -- delayed visibility, an incomplete listing and a refused listing
    all look the same as absence, so absence is never concluded.
    """

    attempt_sha256: str
    started_by: str
    listings: int
    list_observed: ObservedClass
    discovery_failed: bool
    discovery_incomplete: bool
    task_ids: tuple[str, ...]
    stopped_ids: tuple[str, ...]
    residue_ids: tuple[str, ...]
    operations: int

    def document(self) -> dict[str, Any]:
        return {
            "attempt_sha256": self.attempt_sha256,
            "started_by": self.started_by,
            "listings": self.listings,
            "list_observed": self.list_observed.value,
            "discovery_failed": self.discovery_failed,
            "discovery_incomplete": self.discovery_incomplete,
            "task_ids": list(self.task_ids),
            "stopped_ids": list(self.stopped_ids),
            "residue_ids": list(self.residue_ids),
            "operations": self.operations,
        }

    @property
    def undiscovered(self) -> bool:
        """No task known or discovered: the launch stays unresolved, never absent."""
        return not self.task_ids

    @property
    def settled(self) -> bool:
        """Discovery complete and answered, at least one task known, every one STOPPED."""
        return (
            not self.discovery_failed
            and not self.discovery_incomplete
            and bool(self.task_ids)
            and not self.residue_ids
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionCleanup:
    """One cleanup pass by the control principal over every object and task the session left.

    ``deferred`` are objects kept on purpose: a prepared, not yet recorded subcell still
    needs them; ``residue`` are objects not confirmed absent and tasks not confirmed
    stopped -- both stay recorded, and a residue is never an absence.
    """

    stamp: str
    keys: tuple[CleanupKey, ...]
    tasks: tuple[CleanupTasks, ...]
    deferred: tuple[str, ...]
    residue: tuple[str, ...]
    operations: int
    budget_exhausted: bool
    identity_verified: bool
    recorded_at: datetime
    binding: PermissionBinding

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": PERMISSION_CLEANUP_CONTRACT_ID,
            "stamp": self.stamp,
            "keys": [k.document() for k in self.keys],
            "tasks": [t.document() for t in self.tasks],
            "deferred": list(self.deferred),
            "residue": list(self.residue),
            "operations": self.operations,
            "budget_exhausted": self.budget_exhausted,
            "identity_verified": self.identity_verified,
            "recorded_at": self.recorded_at.isoformat(),
            "binding": self.binding.document(),
        }

    @property
    def confirmed_keys(self) -> frozenset[str]:
        return frozenset(k.key for k in self.keys if k.confirmed_absent)

    def admissible_for(self, binding: PermissionBinding, *, not_before: datetime) -> bool:
        """Whether this pass can settle anything recorded under ``binding`` at ``not_before``.

        The one rule every consumer of cleanup evidence applies: the same binding, recorded
        no earlier than the result it would settle, and **the control principal's identity
        verified** -- a cleanup record that does not attest to its principal's identity is
        preserved for reporting and settles nothing, whatever keys or tasks it names.
        """
        return self.binding == binding and self.identity_verified and self.recorded_at >= not_before

    def settles_object(self, attempt_sha256: str, bucket: str, key: str) -> bool:
        """Whether this pass confirmed THIS attempt's object absent."""
        return any(
            k.attempt_sha256 == attempt_sha256
            and k.bucket == bucket
            and k.key == key
            and k.confirmed_absent
            for k in self.keys
        )

    def settles_attempt(self, attempt_sha256: str) -> bool:
        """Whether this pass confirmed the object THIS attempt named absent (the key the
        attempt record carried -- a possibly committed write knows no key of its own)."""
        return any(k.attempt_sha256 == attempt_sha256 and k.confirmed_absent for k in self.keys)

    def settles_tasks(self, attempt_sha256: str, task_ids: Iterable[str]) -> bool:
        """Whether this pass confirmed every task of THIS attempt stopped."""
        wanted = set(task_ids)
        return any(
            t.attempt_sha256 == attempt_sha256 and t.settled and wanted <= set(t.stopped_ids)
            for t in self.tasks
        )


def _issue(
    cell: Subcell, target: ResolvedTarget, client: PermissionClient, stamp: str
) -> Observation:
    """Exactly one operation against the resolved target."""
    op = cell.operation
    if op is Operation.S3_PUT_CONDITIONAL:
        assert target.bucket is not None and target.key is not None
        return client.put_object(target.bucket, target.key, SYNTHETIC_MARKER, if_none_match=True)
    if op is Operation.S3_GET:
        assert target.bucket is not None and target.key is not None
        return client.get_object(target.bucket, target.key)
    if op is Operation.S3_DELETE:
        assert target.bucket is not None and target.key is not None
        return client.delete_object(target.bucket, target.key)
    if op is Operation.S3_LIST:
        assert target.bucket is not None
        return client.list_objects(target.bucket)
    if op is Operation.SECRET_GET:
        assert target.name is not None
        return client.get_secret_value(target.name)
    if op is Operation.SECRET_DESCRIBE:
        assert target.name is not None
        return client.describe_secret(target.name)
    if op is Operation.SSM_GET:
        assert target.name is not None
        return client.get_parameter(target.name)
    if op is Operation.SSM_PUT:
        assert target.name is not None
        return client.put_parameter(target.name, SYNTHETIC_MARKER.decode("ascii"))
    if op in _LAUNCHING:
        assert target.cluster_arn is not None and target.task_definition_arn is not None
        assert target.subnet_id is not None and target.platform_version is not None
        assert target.assign_public_ip is not None and target.security_group_ids
        return client.run_task(
            cluster_arn=target.cluster_arn,
            task_definition_arn=target.task_definition_arn,
            task_role_arn=target.task_role_arn,
            started_by=started_by_of(stamp),
            subnet_id=target.subnet_id,
            security_group_ids=target.security_group_ids,
            assign_public_ip=target.assign_public_ip,
            platform_version=target.platform_version,
        )
    raise ValueError("an R-1-evidenced or blocked operation is never issued here")


def bucket_of(target: TargetKind, *, licensed_bucket: str, control_bucket: str) -> str:
    """The bucket a created key of ``target`` lives in: the CONTROL bucket for its one kind."""
    return control_bucket if target is TargetKind.CONTROL_BUCKET_OBJECT else licensed_bucket


def _task_id(task_arn: str) -> str:
    match = TASK_ARN_RE.fullmatch(task_arn)
    return match.group(3) if match else "unknown"


def run_subcell(
    cell: Subcell,
    *,
    target: ResolvedTarget,
    attempt: PermissionAttempt,
    prerequisites: Mapping[str, str],
    client: PermissionClient,
    identity_verified: bool,
    now: datetime,
) -> PermissionRecord:
    """Execute one subcell: one operation, one decision, one bounded reaction.

    The caller has already consumed the authorization, written ``attempt`` and verified
    the principal's identity (``identity_verified`` records that it did). A DENIED launch
    that started tasks stops each returned task at once -- the extra operations the budget
    allows -- and the record carries every task id and the acknowledged stops; an answer
    that left a write or a launch open is recorded as possibly committed so the cleanup
    settles it. The subcell is INVERTED on any started task.
    """
    if cell.layer is not Layer.L3_RUNTIME:
        raise ValueError("only an L3 runtime subcell is executed")
    observation = _issue(cell, target, client, attempt.stamp)
    observed = classify(observation)
    outcome = decide(cell, observed)
    operations = 1
    started: list[str] = []
    acknowledged: list[str] = []
    possibly_started = False
    started_by: str | None = None
    if cell.operation in _LAUNCHING:
        started_by = started_by_of(attempt.stamp)
        returned = tuple(observation.task_arns)[:MAX_RETURNED_TASKS]
        if returned:
            assert target.cluster_arn is not None
            for task_arn in returned:
                task_id = _task_id(task_arn)
                started.append(task_id)
                stop = client.stop_task(cluster_arn=target.cluster_arn, task_arn=task_arn)
                operations += 1
                if classify(stop) is ObservedClass.OK_200:
                    acknowledged.append(task_id)
            outcome = SubcellOutcome.INVERTED
        elif observed not in _DEFINITELY_NOT_COMMITTED and observed is not ObservedClass.OK_200:
            possibly_started = True
        elif observed is ObservedClass.OK_200:
            # A 200 that returned no task started nothing it told us about; the cleanup
            # still lists by the tag, because a task not in the answer is not a task
            # that does not exist.
            possibly_started = True
    created_key: str | None = None
    created_bucket: str | None = None
    possibly_created = False
    if cell.creates and target.key is not None:
        if observed is ObservedClass.OK_200:
            created_key, created_bucket = target.key, target.bucket
        elif observed not in _DEFINITELY_NOT_COMMITTED:
            possibly_created = True
    return PermissionRecord(
        subcell_id=cell.subcell_id,
        cell_id=cell.cell_id,
        principal=cell.principal,
        operation=cell.operation,
        target=cell.target,
        expectation=cell.expectation,
        stamp=attempt.stamp,
        attempt_sha256=attempt.digest,
        authorization_sha256=attempt.authorization_sha256,
        prerequisites=dict(prerequisites),
        observed=observed,
        outcome=outcome,
        created_bucket=created_bucket,
        created_key=created_key,
        possibly_created=possibly_created,
        started_task_ids=tuple(started),
        stop_acknowledged_ids=tuple(acknowledged),
        started_by=started_by,
        possibly_started=possibly_started,
        operations=operations,
        identity_verified=identity_verified,
        started_at=attempt.started_at,
        finished_at=now,
        binding=attempt.binding,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ObjectToSettle:
    """One object the cleanup must settle: exact bucket and key, and the attempt it answers."""

    bucket: str
    key: str
    attempt_sha256: str


@dataclass(frozen=True, slots=True, kw_only=True)
class TasksToSettle:
    """One launching attempt the cleanup must settle: its tag, cluster and known tasks."""

    attempt_sha256: str
    started_by: str
    cluster_arn: str
    known_task_ids: tuple[str, ...]


def run_cleanup(
    objects: tuple[ObjectToSettle, ...],
    tasks: tuple[TasksToSettle, ...],
    *,
    client: PermissionClient,
    stamp: str,
    deferred: tuple[str, ...],
    binding: PermissionBinding,
    identity_verified: bool,
    now: datetime,
    budget: int,
) -> PermissionCleanup:
    """The control principal settles every object and every launch the session left open.

    Two operations per object inside ``budget``; per launching attempt one ``ListTasks``
    by its tag, then per known or listed task one ``DescribeTasks`` and, unless it answers
    ``STOPPED``, one ``StopTask``. An object whose confirmation is not ``404``, a task not
    confirmed ``STOPPED``, or anything the budget did not reach is residue. Cleanup
    restores the buckets and the cluster; it never changes what a subcell established.
    """
    done: list[CleanupKey] = []
    settled_tasks: list[CleanupTasks] = []
    residue: list[str] = []
    operations = 0
    exhausted = False
    for item in objects:
        if operations + CLEANUP_OPERATIONS_PER_KEY > budget:
            exhausted = True
            residue.append(item.key)
            continue
        delete = classify(client.delete_object(item.bucket, item.key))
        operations += 1
        confirmation = classify(client.head_object(item.bucket, item.key))
        operations += 1
        confirmed = confirmation is ObservedClass.NOT_FOUND_404
        done.append(
            CleanupKey(
                bucket=item.bucket,
                key=item.key,
                attempt_sha256=item.attempt_sha256,
                delete_observed=delete,
                confirmation_observed=confirmation,
                confirmed_absent=confirmed,
            )
        )
        if not confirmed:
            residue.append(item.key)
    for launch in tasks:
        if operations + CLEANUP_OPERATIONS_PER_TASK_MAX > budget:
            exhausted = True
            residue.extend(f"task:{t}" for t in launch.known_task_ids)
            if not launch.known_task_ids:
                residue.append(f"launch:{launch.started_by}:undiscovered")
            continue
        cluster_match = _CLUSTER_ARN_RE.fullmatch(launch.cluster_arn)
        known = list(launch.known_task_ids)
        listings = 0
        worst = ObservedClass.OK_200
        failed = False
        incomplete = False
        token: str | None = None
        for _page in range(DISCOVERY_MAX_PAGES):
            listed = client.list_tasks(
                cluster_arn=launch.cluster_arn, started_by=launch.started_by, next_token=token
            )
            operations += 1
            listings += 1
            observed = classify(listed)
            if observed is not ObservedClass.OK_200:
                failed = True
                worst = observed
                break
            for task_arn in tuple(listed.task_arns)[:MAX_RETURNED_TASKS]:
                task_id = _task_id(task_arn)
                if task_id not in known and len(known) < MAX_RETURNED_TASKS:
                    known.append(task_id)
            token = listed.next_token
            if token is None:
                break
        else:
            incomplete = True
        stopped: list[str] = []
        left: list[str] = []
        for task_id in known:
            task_arn = (
                f"{cluster_match.group(1).replace(':cluster/', ':task/')}"
                f"{cluster_match.group(2)}/{task_id}"
                if cluster_match
                else task_id
            )
            described = client.describe_tasks(cluster_arn=launch.cluster_arn, task_arns=(task_arn,))
            operations += 1
            status = dict(described.task_statuses).get(task_arn)
            if classify(described) is ObservedClass.OK_200 and status == TASK_STOPPED_STATUS:
                stopped.append(task_id)
                continue
            client.stop_task(cluster_arn=launch.cluster_arn, task_arn=task_arn)
            operations += 1
            left.append(task_id)
        block = CleanupTasks(
            attempt_sha256=launch.attempt_sha256,
            started_by=launch.started_by,
            listings=listings,
            list_observed=worst,
            discovery_failed=failed,
            discovery_incomplete=incomplete,
            task_ids=tuple(known),
            stopped_ids=tuple(stopped),
            residue_ids=tuple(left),
            operations=listings + len(known) + len(left),
        )
        residue.extend(f"task:{t}" for t in left)
        if not block.settled and not left:
            residue.append(
                f"launch:{launch.started_by}:"
                + ("failed" if failed else "incomplete" if incomplete else "undiscovered")
            )
        settled_tasks.append(block)
    return PermissionCleanup(
        stamp=stamp,
        keys=tuple(done),
        tasks=tuple(settled_tasks),
        deferred=deferred,
        residue=tuple(residue),
        operations=operations,
        budget_exhausted=exhausted,
        identity_verified=identity_verified,
        recorded_at=now,
        binding=binding,
    )


# ---------------------------------------------------------------------------
# Parsing the records back
# ---------------------------------------------------------------------------

_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "subcell_id",
        "cell_id",
        "principal",
        "operation",
        "target",
        "expectation",
        "stamp",
        "attempt_sha256",
        "authorization_sha256",
        "prerequisites",
        "observed",
        "outcome",
        "created_bucket",
        "created_key",
        "possibly_created",
        "started_task_ids",
        "stop_acknowledged_ids",
        "started_by",
        "possibly_started",
        "operations",
        "identity_verified",
        "started_at",
        "finished_at",
        "binding",
    }
)
_ATTEMPT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "subcell_id",
        "principal",
        "stamp",
        "authorization_sha256",
        "statement_sha256",
        "bucket",
        "key",
        "started_at",
        "binding",
    }
)
_STATEMENT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "subcell_id",
        "principal",
        "operation",
        "target",
        "target_sha256",
        "stamp",
        "binding",
        "targets_sha256",
        "prerequisites",
        "prepared_at",
    }
)
_CLEANUP_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "stamp",
        "keys",
        "tasks",
        "deferred",
        "residue",
        "operations",
        "budget_exhausted",
        "identity_verified",
        "recorded_at",
        "binding",
    }
)
_TASK_ID_RE: Final = re.compile(r"[0-9a-f]{32}|unknown")


def _document(raw: object, contract_id: str, fields_: frozenset[str]) -> dict[str, Any]:
    document = (
        raw if type(raw) is dict else decode_document(raw, max_bytes=MAX_PERMISSION_RECORD_BYTES)
    )
    if type(document) is not dict or set(document) != fields_:
        raise ValueError("permission record: closed field set")
    if (
        document["schema_version"] != RECORD_SCHEMA_VERSION
        or document["contract_id"] != contract_id
    ):
        raise ValueError("permission record: contract")
    return document


def _member(enum: Any, value: object) -> Any:
    text = exact_str(value)
    if text is None or text not in {m.value for m in enum}:
        raise ValueError("permission record: vocabulary")
    return enum(text)


def _optional_key(value: object) -> str | None:
    if value is None:
        return None
    text = exact_str(value)
    if text is None or len(text) > 1024 or "\n" in text:
        raise ValueError("permission record: key")
    return text


def _optional_bucket(value: object) -> str | None:
    if value is None:
        return None
    text = exact_str(value)
    if text is None or _BUCKET_RE.fullmatch(text) is None:
        raise ValueError("permission record: bucket")
    return text


def _task_ids(value: object) -> tuple[str, ...]:
    if type(value) is not list or len(value) > MAX_RETURNED_TASKS:
        raise ValueError("permission record: task ids")
    out: list[str] = []
    for item in value:
        text = exact_str(item)
        if text is None or _TASK_ID_RE.fullmatch(text) is None or text in out:
            raise ValueError("permission record: task ids")
        out.append(text)
    return tuple(out)


def _digest_field(value: object) -> str:
    digest = hex_digest(value)
    if digest is None:
        raise ValueError("permission record: digest")
    return digest


def parse_permission_record(raw: object) -> PermissionRecord:
    """A permission record, parsed closed and held consistent with its subcell."""
    d = _document(raw, PERMISSION_RECORD_CONTRACT_ID, _RECORD_FIELDS)
    cell_id = exact_str(d["subcell_id"])
    if cell_id is None or cell_id not in SUBCELL_BY_ID:
        raise ValueError("permission record: subcell")
    cell = SUBCELL_BY_ID[cell_id]
    principal = _member(Principal, d["principal"])
    operation = _member(Operation, d["operation"])
    target = _member(TargetKind, d["target"])
    expectation = _member(Expectation, d["expectation"])
    if (
        d["cell_id"] != cell.cell_id
        or principal is not cell.principal
        or operation is not cell.operation
        or target is not cell.target
        or expectation is not cell.expectation
    ):
        raise ValueError("permission record: contradicts the subcell definition")
    stamp = exact_str(d["stamp"])
    observed = _member(ObservedClass, d["observed"])
    outcome = _member(SubcellOutcome, d["outcome"])
    started_at = instant(d["started_at"])
    finished_at = instant(d["finished_at"])
    started_task_ids = _task_ids(d["started_task_ids"])
    acknowledged = _task_ids(d["stop_acknowledged_ids"])
    started_by = d["started_by"]
    launching = cell.operation in _LAUNCHING
    if (
        stamp is None
        or _STAMP_RE.fullmatch(stamp) is None
        or started_at is None
        or finished_at is None
        or finished_at < started_at
        or type(d["operations"]) is not int
        or type(d["operations"]) is bool
        or not 1 <= d["operations"] <= SUBCELL_OPERATION_BUDGET
        or type(d["identity_verified"]) is not bool
        or type(d["possibly_created"]) is not bool
        or type(d["possibly_started"]) is not bool
        or not set(acknowledged) <= set(started_task_ids)
        or (started_by is not None and started_by != started_by_of(stamp))
        or (launching != (started_by is not None))
        or (not launching and (started_task_ids or d["possibly_started"]))
        or d["operations"] != 1 + len(started_task_ids)
    ):
        raise ValueError("permission record: field")
    prerequisites = _prerequisites_from(d["prerequisites"])
    if set(prerequisites) != set(cell.requires):
        raise ValueError("permission record: prerequisites contradict the subcell definition")
    # The outcome must be the one the class decides; a record cannot claim otherwise.
    expected = decide(cell, observed)
    if started_task_ids:
        expected = SubcellOutcome.INVERTED
    if outcome is not expected:
        raise ValueError("permission record: outcome contradicts the observed class")
    created = _optional_key(d["created_key"])
    created_bucket = _optional_bucket(d["created_bucket"])
    if (created is None) != (created_bucket is None):
        raise ValueError("permission record: a created key names its bucket")
    if created is not None and not (cell.creates and observed is ObservedClass.OK_200):
        raise ValueError("permission record: a created key without a creating success")
    if d["possibly_created"] and (
        not cell.creates
        or observed is ObservedClass.OK_200
        or observed in _DEFINITELY_NOT_COMMITTED
    ):
        raise ValueError("permission record: possibly created contradicts the observed class")
    if d["possibly_started"] and (
        not launching or started_task_ids or observed in _DEFINITELY_NOT_COMMITTED
    ):
        raise ValueError("permission record: possibly started contradicts the observed class")
    return PermissionRecord(
        subcell_id=cell_id,
        cell_id=cell.cell_id,
        principal=principal,
        operation=operation,
        target=target,
        expectation=expectation,
        stamp=stamp,
        attempt_sha256=_digest_field(d["attempt_sha256"]),
        authorization_sha256=_digest_field(d["authorization_sha256"]),
        prerequisites=prerequisites,
        observed=observed,
        outcome=outcome,
        created_bucket=created_bucket,
        created_key=created,
        possibly_created=d["possibly_created"],
        started_task_ids=started_task_ids,
        stop_acknowledged_ids=acknowledged,
        started_by=started_by,
        possibly_started=d["possibly_started"],
        operations=d["operations"],
        identity_verified=d["identity_verified"],
        started_at=started_at,
        finished_at=finished_at,
        binding=_binding_from(d["binding"]),
    )


def parse_permission_attempt(raw: object) -> PermissionAttempt:
    """An attempt record, parsed closed."""
    d = _document(raw, PERMISSION_ATTEMPT_CONTRACT_ID, _ATTEMPT_FIELDS)
    cell_id = exact_str(d["subcell_id"])
    if cell_id is None or cell_id not in SUBCELL_BY_ID:
        raise ValueError("permission attempt: subcell")
    principal = _member(Principal, d["principal"])
    if principal is not SUBCELL_BY_ID[cell_id].principal:
        raise ValueError("permission attempt: principal")
    stamp = exact_str(d["stamp"])
    started_at = instant(d["started_at"])
    if stamp is None or _STAMP_RE.fullmatch(stamp) is None or started_at is None:
        raise ValueError("permission attempt: field")
    key = _optional_key(d["key"])
    bucket = _optional_bucket(d["bucket"])
    if (key is None) != (bucket is None):
        raise ValueError("permission attempt: a key names its bucket")
    return PermissionAttempt(
        subcell_id=cell_id,
        principal=principal,
        stamp=stamp,
        authorization_sha256=_digest_field(d["authorization_sha256"]),
        statement_sha256=_digest_field(d["statement_sha256"]),
        bucket=bucket,
        key=key,
        started_at=started_at,
        binding=_binding_from(d["binding"]),
    )


def parse_permission_statement(raw: object) -> PermissionStatement:
    """A statement record, parsed closed and held consistent with its subcell."""
    d = _document(raw, PERMISSION_STATEMENT_CONTRACT_ID, _STATEMENT_FIELDS)
    cell_id = exact_str(d["subcell_id"])
    if cell_id is None or cell_id not in SUBCELL_BY_ID:
        raise ValueError("permission statement: subcell")
    cell = SUBCELL_BY_ID[cell_id]
    principal = _member(Principal, d["principal"])
    operation = _member(Operation, d["operation"])
    target = _member(TargetKind, d["target"])
    if (
        principal is not cell.principal
        or operation is not cell.operation
        or target is not cell.target
    ):
        raise ValueError("permission statement: contradicts the subcell definition")
    stamp = exact_str(d["stamp"])
    prepared_at = instant(d["prepared_at"])
    if stamp is None or _STAMP_RE.fullmatch(stamp) is None or prepared_at is None:
        raise ValueError("permission statement: field")
    prerequisites = _prerequisites_from(d["prerequisites"])
    if set(prerequisites) != set(cell.requires):
        raise ValueError("permission statement: prerequisites contradict the subcell definition")
    return PermissionStatement(
        subcell_id=cell_id,
        principal=principal,
        operation=operation,
        target=target,
        target_sha256=_digest_field(d["target_sha256"]),
        stamp=stamp,
        binding=_binding_from(d["binding"]),
        targets_sha256=_digest_field(d["targets_sha256"]),
        prerequisites=prerequisites,
        prepared_at=prepared_at,
    )


def parse_permission_cleanup(raw: object) -> PermissionCleanup:
    """A cleanup record, parsed closed; residue must agree with the keys and tasks."""
    d = _document(raw, PERMISSION_CLEANUP_CONTRACT_ID, _CLEANUP_FIELDS)
    stamp = exact_str(d["stamp"])
    recorded_at = instant(d["recorded_at"])
    if (
        stamp is None
        or _STAMP_RE.fullmatch(stamp) is None
        or recorded_at is None
        or type(d["keys"]) is not list
        or type(d["tasks"]) is not list
        or type(d["deferred"]) is not list
        or type(d["residue"]) is not list
        or type(d["operations"]) is not int
        or type(d["operations"]) is bool
        or d["operations"] < 0
        or type(d["budget_exhausted"]) is not bool
        or type(d["identity_verified"]) is not bool
    ):
        raise ValueError("permission cleanup: field")
    keys: list[CleanupKey] = []
    for block in d["keys"]:
        if type(block) is not dict or set(block) != {
            "bucket",
            "key",
            "attempt_sha256",
            "delete_observed",
            "confirmation_observed",
            "confirmed_absent",
        }:
            raise ValueError("permission cleanup: key block")
        key = _optional_key(block["key"])
        bucket = _optional_bucket(block["bucket"])
        if key is None or bucket is None or type(block["confirmed_absent"]) is not bool:
            raise ValueError("permission cleanup: key block")
        confirmation = (
            None
            if block["confirmation_observed"] is None
            else _member(ObservedClass, block["confirmation_observed"])
        )
        confirmed = confirmation is ObservedClass.NOT_FOUND_404
        if block["confirmed_absent"] is not confirmed:
            raise ValueError("permission cleanup: confirmation contradicts the class")
        keys.append(
            CleanupKey(
                bucket=bucket,
                key=key,
                attempt_sha256=_digest_field(block["attempt_sha256"]),
                delete_observed=_member(ObservedClass, block["delete_observed"]),
                confirmation_observed=confirmation,
                confirmed_absent=confirmed,
            )
        )
    tasks: list[CleanupTasks] = []
    task_operations = 0
    for block in d["tasks"]:
        if type(block) is not dict or set(block) != {
            "attempt_sha256",
            "started_by",
            "listings",
            "list_observed",
            "discovery_failed",
            "discovery_incomplete",
            "task_ids",
            "stopped_ids",
            "residue_ids",
            "operations",
        }:
            raise ValueError("permission cleanup: task block")
        started_by = exact_str(block["started_by"])
        task_ids = _task_ids(block["task_ids"])
        stopped = _task_ids(block["stopped_ids"])
        left = _task_ids(block["residue_ids"])
        listings = block["listings"]
        max_listings = DISCOVERY_MAX_PAGES
        if (
            started_by is None
            or not started_by.startswith("kalpamani-permission-")
            or type(block["operations"]) is not int
            or type(block["operations"]) is bool
            or type(listings) is not int
            or type(listings) is bool
            or not 1 <= listings <= max_listings
            or type(block["discovery_failed"]) is not bool
            or type(block["discovery_incomplete"]) is not bool
            or set(stopped) | set(left) != set(task_ids)
            or set(stopped) & set(left)
            or block["operations"] != listings + len(task_ids) + len(left)
        ):
            raise ValueError("permission cleanup: task block")
        block_parsed = CleanupTasks(
            attempt_sha256=_digest_field(block["attempt_sha256"]),
            started_by=started_by,
            listings=listings,
            list_observed=_member(ObservedClass, block["list_observed"]),
            discovery_failed=block["discovery_failed"],
            discovery_incomplete=block["discovery_incomplete"],
            task_ids=task_ids,
            stopped_ids=stopped,
            residue_ids=left,
            operations=block["operations"],
        )
        if block_parsed.discovery_failed == (block_parsed.list_observed is ObservedClass.OK_200):
            raise ValueError("permission cleanup: discovery contradicts the class")
        task_operations += block["operations"]
        tasks.append(block_parsed)
    residue = tuple(_optional_key(r) or "" for r in d["residue"])
    deferred = tuple(_optional_key(r) or "" for r in d["deferred"])
    if any(not r for r in residue) or any(not r for r in deferred):
        raise ValueError("permission cleanup: residue")
    unconfirmed = {k.key for k in keys if not k.confirmed_absent}
    unconfirmed |= {f"task:{t}" for block in tasks for t in block.residue_ids}
    for block in tasks:
        if not block.settled and not block.residue_ids:
            reason = (
                "failed"
                if block.discovery_failed
                else "incomplete"
                if block.discovery_incomplete
                else "undiscovered"
            )
            unconfirmed.add(f"launch:{block.started_by}:{reason}")
    if not unconfirmed <= set(residue):
        raise ValueError("permission cleanup: an unsettled key, task or launch is not residue")
    if d["operations"] != CLEANUP_OPERATIONS_PER_KEY * len(keys) + task_operations:
        raise ValueError("permission cleanup: operations")
    return PermissionCleanup(
        stamp=stamp,
        keys=tuple(keys),
        tasks=tuple(tasks),
        deferred=deferred,
        residue=residue,
        operations=d["operations"],
        budget_exhausted=d["budget_exhausted"],
        identity_verified=d["identity_verified"],
        recorded_at=recorded_at,
        binding=_binding_from(d["binding"]),
    )


# ---------------------------------------------------------------------------
# Deriving the state of one subcell and one cell
# ---------------------------------------------------------------------------


class SubcellStatus(StrEnum):
    """The derived state of one subcell. Closed."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    UNEXECUTED = "UNEXECUTED"
    UNDECIDED = "UNDECIDED"
    INTERRUPTED = "INTERRUPTED"
    BLOCKED = "BLOCKED"
    HISTORICAL = "HISTORICAL"
    UNBOUND = "UNBOUND"
    CLEANUP_UNRESOLVED = "CLEANUP_UNRESOLVED"
    AWAITING_R1 = "AWAITING_R1"


@dataclass(frozen=True, slots=True, kw_only=True)
class SubcellState:
    subcell_id: str
    status: SubcellStatus
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionEvidence:
    """Every permission record, attempt, statement, consumption and cleanup the runner read,
    and the context (binding and resolvable targets) everything is held to now."""

    records: dict[str, tuple[PermissionRecord, ...]] = field(default_factory=dict)
    attempts: dict[str, tuple[PermissionAttempt, ...]] = field(default_factory=dict)
    statements: dict[str, tuple[PermissionStatement, ...]] = field(default_factory=dict)
    consumptions: dict[str, PermissionConsumption] = field(default_factory=dict)
    cleanups: tuple[PermissionCleanup, ...] = ()
    malformed: int = 0
    context: PermissionContext | None = None

    @property
    def binding(self) -> PermissionBinding | None:
        return None if self.context is None else self.context.binding


class ChainDefect(StrEnum):
    """Why a recorded result is not bound to its attempt, statement and consumption. Closed."""

    NO_CONTEXT = "NO_CONTEXT"
    OTHER_BINDING = "OTHER_BINDING"
    ATTEMPT_MISSING = "ATTEMPT_MISSING"
    ATTEMPT_MISMATCH = "ATTEMPT_MISMATCH"
    STATEMENT_MISSING = "STATEMENT_MISSING"
    STATEMENT_MISMATCH = "STATEMENT_MISMATCH"
    PREREQUISITE_UNBOUND = "PREREQUISITE_UNBOUND"
    TARGET_UNRESOLVABLE = "TARGET_UNRESOLVABLE"
    TARGET_MISMATCH = "TARGET_MISMATCH"
    CONSUMPTION_MISSING = "CONSUMPTION_MISSING"
    CONSUMPTION_MISMATCH = "CONSUMPTION_MISMATCH"


class ChainError(ValueError):
    """A recorded result that does not bind, and why."""

    def __init__(self, defect: ChainDefect) -> None:
        super().__init__(defect.value)
        self.defect = defect


@dataclass(frozen=True, slots=True, kw_only=True)
class BoundChain:
    """One recorded result with every component it binds to, validated together."""

    record: PermissionRecord
    attempt: PermissionAttempt
    statement: PermissionStatement
    consumption: PermissionConsumption
    target: ResolvedTarget
    prerequisites: dict[str, PermissionRecord]


def bind_result(
    record: PermissionRecord, evidence: PermissionEvidence, *, _depth: int = 0
) -> BoundChain:
    """The one validator: a result binds only through its whole chain, or ``ChainError``.

    Required, and held to each other: the current context (no context, no binding);
    the record under the current binding; the attempt the record names by digest, for
    the same subcell, principal, stamp, start, authorization and binding; the statement
    the attempt names by digest, for the same subcell, principal, operation, target
    class, stamp, binding, targets document and prerequisites; every prerequisite the
    statement names as the exact bound record it was prepared against (itself bound
    through its own chain, established before this one, its object created); the exact
    target recomputed NOW from the context and equal to the statement's digest, with
    the attempt's and the record's object the target's; and the durable consumption of
    the authorization, naming this subcell and statement, consumed no later than the
    attempt started. A digest-shaped field alone binds nothing.
    """
    context = evidence.context
    if context is None:
        raise ChainError(ChainDefect.NO_CONTEXT)
    binding = context.binding
    if record.binding != binding:
        raise ChainError(ChainDefect.OTHER_BINDING)
    cell = SUBCELL_BY_ID[record.subcell_id]
    attempts = [
        a for a in evidence.attempts.get(record.subcell_id, ()) if a.digest == record.attempt_sha256
    ]
    if len(attempts) != 1:
        raise ChainError(ChainDefect.ATTEMPT_MISSING)
    attempt = attempts[0]
    if (
        attempt.subcell_id != record.subcell_id
        or attempt.principal is not record.principal
        or attempt.stamp != record.stamp
        or attempt.started_at != record.started_at
        or attempt.authorization_sha256 != record.authorization_sha256
        or attempt.binding != binding
    ):
        raise ChainError(ChainDefect.ATTEMPT_MISMATCH)
    statements = [
        s
        for s in evidence.statements.get(record.subcell_id, ())
        if s.digest == attempt.statement_sha256
    ]
    if len(statements) != 1:
        raise ChainError(ChainDefect.STATEMENT_MISSING)
    statement = statements[0]
    if (
        statement.subcell_id != record.subcell_id
        or statement.principal is not cell.principal
        or statement.operation is not cell.operation
        or statement.target is not cell.target
        or statement.stamp != record.stamp
        or statement.binding != binding
        or statement.targets_sha256 != binding.targets_sha256
        or statement.prerequisites != record.prerequisites
    ):
        raise ChainError(ChainDefect.STATEMENT_MISMATCH)
    prerequisites: dict[str, PermissionRecord] = {}
    for required, digest in statement.prerequisites.items():
        if _depth > len(SUBCELLS):  # pragma: no cover - the catalogue has no cycles
            raise ChainError(ChainDefect.PREREQUISITE_UNBOUND)
        candidates = [
            r
            for r in evidence.records.get(required, ())
            if r.digest == digest
            and r.outcome is SubcellOutcome.MATCHED
            and r.created_key is not None
            and r.started_at <= record.started_at
        ]
        if len(candidates) != 1:
            raise ChainError(ChainDefect.PREREQUISITE_UNBOUND)
        try:
            bind_result(candidates[0], evidence, _depth=_depth + 1)
        except ChainError:
            raise ChainError(ChainDefect.PREREQUISITE_UNBOUND) from None
        prerequisites[required] = candidates[0]
    try:
        target = context.resolve(cell, stamp=statement.stamp, prerequisites=prerequisites)
    except (ValueError, KeyError):
        raise ChainError(ChainDefect.TARGET_UNRESOLVABLE) from None
    if target.digest != statement.target_sha256:
        raise ChainError(ChainDefect.TARGET_MISMATCH)
    expected_key = target.key if cell.creates else None
    expected_bucket = target.bucket if cell.creates else None
    if attempt.key != expected_key or attempt.bucket != expected_bucket:
        raise ChainError(ChainDefect.ATTEMPT_MISMATCH)
    if record.created_key is not None and (
        record.created_key != target.key or record.created_bucket != target.bucket
    ):
        raise ChainError(ChainDefect.TARGET_MISMATCH)
    if cell.operation in _LAUNCHING and record.started_by != started_by_of(record.stamp):
        raise ChainError(ChainDefect.ATTEMPT_MISMATCH)
    consumption = evidence.consumptions.get(record.authorization_sha256)
    if consumption is None:
        raise ChainError(ChainDefect.CONSUMPTION_MISSING)
    if (
        consumption.subcell_id != record.subcell_id
        or consumption.statement_sha256 != statement.digest
        or consumption.authorization_sha256 != record.authorization_sha256
        or consumption.consumed_at > attempt.started_at
    ):
        raise ChainError(ChainDefect.CONSUMPTION_MISMATCH)
    return BoundChain(
        record=record,
        attempt=attempt,
        statement=statement,
        consumption=consumption,
        target=target,
        prerequisites=prerequisites,
    )


def unsettled_reason(chain: BoundChain, cleanups: Iterable[PermissionCleanup]) -> str | None:
    """Why the bound result's object or launch is not yet settled, or ``None`` when it is.

    A cleanup settles a bound result only by naming its attempt and its exact object --
    the bucket and key the chain's target names -- or its exact launch (the attempt and
    its ``startedBy`` tag, every task the record started confirmed STOPPED, discovery
    complete and answered), and only when it is admissible
    (:meth:`PermissionCleanup.admissible_for`: the same binding, recorded no earlier than
    the record, the control principal's identity verified). A cleanup that found no task
    settles nothing; a cleanup whose identity is not verified settles nothing.
    """
    record = chain.record
    later = [c for c in cleanups if c.admissible_for(record.binding, not_before=record.finished_at)]
    unverified = any(
        c.binding == record.binding
        and c.recorded_at >= record.finished_at
        and not c.identity_verified
        for c in cleanups
    )
    note = " (an unverified cleanup record is present and settles nothing)" if unverified else ""
    if record.object_open:
        bucket, key = chain.target.bucket, chain.target.key
        if bucket is None or key is None:
            return "an object is open but the bound target names no object"
        if not any(c.settles_object(chain.attempt.digest, bucket, key) for c in later):
            return (
                "an object this attempt created or may have created is not confirmed removed "
                "by a later cleanup naming this attempt and this exact object" + note
            )
    if record.launch_open:
        settled = any(
            t.attempt_sha256 == chain.attempt.digest
            and t.started_by == record.started_by
            and t.settled
            and set(record.started_task_ids) <= set(t.stopped_ids)
            for c in later
            for t in c.tasks
        )
        if not settled:
            if record.started_task_ids:
                return (
                    "a task this attempt started is not confirmed STOPPED by a later cleanup "
                    "naming this attempt (a stop acknowledgement is not a termination)" + note
                )
            return (
                "no task of the ambiguous launch has been discovered and confirmed STOPPED; "
                "an empty, failed or incomplete discovery is not proof of absence" + note
            )
    return None


def derive_subcell(
    cell: Subcell,
    evidence: PermissionEvidence,
    *,
    r1_passed: dict[ProductionActor, bool],
) -> SubcellState:
    """One subcell's state from the records, bound to the current binding.

    A record for another binding is HISTORICAL. Attempts and records are joined by the
    attempt's digest, never by their order: an attempt no record names is INTERRUPTED,
    whatever came after it. Among records for the current binding the latest by start
    decides, except that an INVERTED record is never superseded by a later MATCHED one
    under the same binding (an observed failure does not disappear when later evidence
    arrives); every object or launch a record left open must be settled by a later
    cleanup naming that attempt; every prerequisite the record names must be the exact
    bound record it was prepared against.
    """
    if cell.layer is Layer.BLOCKED:
        assert cell.blocked_on is not None
        return SubcellState(
            subcell_id=cell.subcell_id, status=SubcellStatus.BLOCKED, reason=cell.blocked_on
        )
    if cell.layer is Layer.L3_BY_R1:
        actor = PRINCIPAL_ACTOR[cell.principal]
        assert actor is not None
        if r1_passed.get(actor):
            return SubcellState(
                subcell_id=cell.subcell_id,
                status=SubcellStatus.PASSED,
                reason="evidenced by the PASSED R-1 bootstrap launch of this actor",
            )
        return SubcellState(
            subcell_id=cell.subcell_id,
            status=SubcellStatus.AWAITING_R1,
            reason="evidenced only by a PASSED R-1 bootstrap launch of this actor",
        )
    binding = evidence.binding
    if binding is None:
        if evidence.records.get(cell.subcell_id) or evidence.attempts.get(cell.subcell_id):
            return SubcellState(
                subcell_id=cell.subcell_id,
                status=SubcellStatus.UNBOUND,
                reason="no current binding (environment, declarations, registration, targets) "
                "to hold the recorded evidence to",
            )
        return SubcellState(
            subcell_id=cell.subcell_id,
            status=SubcellStatus.UNEXECUTED,
            reason="no record (scripts/production_permission_cells.py --execute-subcell)",
        )
    if evidence.malformed:
        return SubcellState(
            subcell_id=cell.subcell_id,
            status=SubcellStatus.UNBOUND,
            reason="malformed or unreadable permission evidence in the records",
        )
    records = [r for r in evidence.records.get(cell.subcell_id, ()) if r.binding == binding]
    stale = [r for r in evidence.records.get(cell.subcell_id, ()) if r.binding != binding]
    attempts = [a for a in evidence.attempts.get(cell.subcell_id, ()) if a.binding == binding]
    answered = {r.attempt_sha256 for r in records}
    if any(a.digest not in answered for a in attempts):
        return SubcellState(
            subcell_id=cell.subcell_id,
            status=SubcellStatus.INTERRUPTED,
            reason="an attempt was recorded and no result names it; the cleanup settles "
            "the object it named, and the subcell is not re-executed automatically",
        )
    if not records:
        if stale:
            return SubcellState(
                subcell_id=cell.subcell_id,
                status=SubcellStatus.HISTORICAL,
                reason="recorded under another binding, declaration or registration; "
                "re-exercise is required",
            )
        return SubcellState(
            subcell_id=cell.subcell_id,
            status=SubcellStatus.UNEXECUTED,
            reason="no record (scripts/production_permission_cells.py --execute-subcell)",
        )
    if any(r.outcome is SubcellOutcome.INVERTED for r in records):
        inverted = [r for r in records if r.outcome is SubcellOutcome.INVERTED][-1]
        detail = ""
        if inverted.started_task_ids:
            try:
                unsettled = unsettled_reason(bind_result(inverted, evidence), evidence.cleanups)
            except ChainError as error:
                unsettled = f"unbound ({error.defect.value})"
            detail = (
                f"; {len(inverted.started_task_ids)} task(s) started, "
                f"{len(inverted.stop_acknowledged_ids)} stop(s) acknowledged, termination "
                + ("confirmed by a later cleanup" if unsettled is None else "NOT confirmed")
                + (
                    " (an unverified cleanup record is present and settles nothing)"
                    if unsettled is not None and "unverified cleanup" in unsettled
                    else ""
                )
            )
        return SubcellState(
            subcell_id=cell.subcell_id,
            status=SubcellStatus.FAILED,
            reason=f"observed {inverted.observed.value} against {cell.expectation.value}{detail}",
        )
    latest = sorted(records, key=lambda r: r.started_at)[-1]
    if not latest.identity_verified:
        return SubcellState(
            subcell_id=cell.subcell_id,
            status=SubcellStatus.UNBOUND,
            reason="the record does not attest that the principal's identity was verified",
        )
    chains: list[BoundChain] = []
    for record in records:
        try:
            chains.append(bind_result(record, evidence))
        except ChainError as error:
            return SubcellState(
                subcell_id=cell.subcell_id,
                status=SubcellStatus.UNBOUND,
                reason=f"the recorded result does not bind to its attempt, statement, "
                f"target and consumed authorization ({error.defect.value})",
            )
    for chain in chains:
        unsettled = unsettled_reason(chain, evidence.cleanups)
        if unsettled is not None:
            return SubcellState(
                subcell_id=cell.subcell_id,
                status=SubcellStatus.CLEANUP_UNRESOLVED,
                reason=f"{unsettled} (scripts/production_permission_cells.py --cleanup)",
            )
    if latest.outcome is SubcellOutcome.UNDECIDED:
        return SubcellState(
            subcell_id=cell.subcell_id,
            status=SubcellStatus.UNDECIDED,
            reason=f"the last answer decided nothing ({latest.observed.value})",
        )
    return SubcellState(
        subcell_id=cell.subcell_id,
        status=SubcellStatus.PASSED,
        reason=f"observed {latest.observed.value} as expected under the current binding",
    )


__all__ = [
    "CLEANUP_OPERATIONS_PER_KEY",
    "CLEANUP_OPERATIONS_PER_TASK_MAX",
    "DELETION_DEPENDENCY",
    "DISCOVERY_MAX_PAGES",
    "EXECUTE_COMMAND_DEPENDENCY",
    "MAX_AUTHORIZATION_VALIDITY",
    "MAX_PERMISSION_RECORD_BYTES",
    "MAX_PERMISSION_TARGETS_BYTES",
    "MAX_RETURNED_TASKS",
    "PERMISSION_ATTEMPT_CONTRACT_ID",
    "PERMISSION_AUTHORIZATION_CONTRACT_ID",
    "PERMISSION_CLEANUP_CONTRACT_ID",
    "PERMISSION_CONSUMPTION_CONTRACT_ID",
    "PERMISSION_RECORD_CONTRACT_ID",
    "PERMISSION_STATEMENT_CONTRACT_ID",
    "PERMISSION_TARGETS_CONTRACT_ID",
    "PRINCIPAL_ACTOR",
    "PRINCIPAL_PROFILE",
    "SUBCELLS",
    "SUBCELL_BY_ID",
    "SUBCELL_OPERATION_BUDGET",
    "SYNTHETIC_MARKER",
    "TASK_PROBE_DEPENDENCY",
    "TASK_STOPPED_STATUS",
    "AuthorizationDefect",
    "BoundChain",
    "ChainDefect",
    "ChainError",
    "CleanupKey",
    "CleanupTasks",
    "Expectation",
    "Layer",
    "ObjectToSettle",
    "ObservedClass",
    "Operation",
    "PermissionAttempt",
    "PermissionAuthorization",
    "PermissionBinding",
    "PermissionCleanup",
    "PermissionClient",
    "PermissionConsumption",
    "PermissionContext",
    "PermissionEvidence",
    "PermissionRecord",
    "PermissionStatement",
    "PermissionTargets",
    "Principal",
    "ResolvedTarget",
    "Subcell",
    "SubcellOutcome",
    "SubcellState",
    "SubcellStatus",
    "TargetKind",
    "TasksToSettle",
    "bind_result",
    "bucket_of",
    "decide",
    "declaration_digest",
    "derive_subcell",
    "parse_permission_attempt",
    "parse_permission_authorization",
    "parse_permission_cleanup",
    "parse_permission_consumption",
    "parse_permission_record",
    "parse_permission_statement",
    "parse_permission_targets",
    "resolve_target",
    "run_cleanup",
    "run_subcell",
    "started_by_of",
    "statement_for",
    "subcell",
    "subcells_of",
    "synthetic_run_id",
    "unsettled_reason",
]
