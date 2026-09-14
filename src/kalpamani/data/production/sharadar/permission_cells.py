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
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
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
                Layer.L3_RUNTIME,
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
    """One subcell's exact target, resolved for one session stamp. Never rendered whole."""

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

    def __repr__(self) -> str:
        """The kind only."""
        return f"ResolvedTarget(kind={self.kind.value!r})"


def synthetic_run_id(stamp: str) -> str:
    """The run identity every synthetic Bronze object of one session names."""
    if _STAMP_RE.fullmatch(stamp) is None:
        raise ValueError("a session stamp is required")
    return f"verification-{stamp}"


def resolve_target(
    cell: Subcell,
    *,
    stamp: str,
    licensed_bucket: str,
    inputs: LaunchInputs,
    targets: PermissionTargets,
    production_secret: str | None,
) -> ResolvedTarget:
    """The exact target of ``cell`` for this session, from the bindings and registration.

    Every synthetic S3 key is a real key shape of its namespace (built by the accepted key
    builders) carrying the session stamp in its run identity and the marker's digest as its
    content address, so it lies exactly where the policy statement under test applies and
    nowhere a production object could be. Launch targets are the registered ones (own) or
    deterministic derivations of them (another revision, another cluster) that the exact-
    resource policies cannot name.
    """
    actor = PRINCIPAL_ACTOR[cell.principal]
    digest = sha256_hex(SYNTHETIC_MARKER)
    run_id = synthetic_run_id(stamp)
    kind = cell.target
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
    if kind is TargetKind.OWN_REVISION or kind is TargetKind.OWN_TASK:
        return ResolvedTarget(kind=kind, cluster_arn=cluster, task_definition_arn=own)
    if kind is TargetKind.OTHER_ACTOR_REVISION:
        return ResolvedTarget(
            kind=kind,
            cluster_arn=cluster,
            task_definition_arn=inputs.targets[
                (other_actor, LaunchKind.VERIFICATION)
            ].task_definition_arn,
        )
    if kind is TargetKind.OTHER_REVISION:
        return ResolvedTarget(
            kind=kind,
            cluster_arn=cluster,
            task_definition_arn=f"{match.group(1)}{match.group(2)}:{int(match.group(3)) + 1}",
        )
    if kind is TargetKind.OTHER_FAMILY:
        return ResolvedTarget(
            kind=kind,
            cluster_arn=cluster,
            task_definition_arn=f"{match.group(1)}{match.group(2)}-verification-other:1",
        )
    if kind is TargetKind.OTHER_CLUSTER:
        cluster_match = _CLUSTER_ARN_RE.fullmatch(cluster)
        if cluster_match is None:
            raise ValueError("the registered cluster is not a cluster ARN")
        return ResolvedTarget(
            kind=kind,
            cluster_arn=f"{cluster_match.group(1)}{cluster_match.group(2)}-verification-other",
            task_definition_arn=own,
        )
    if kind is TargetKind.OTHER_ACTOR_TASK_ROLE:
        return ResolvedTarget(
            kind=kind,
            cluster_arn=cluster,
            task_definition_arn=own,
            task_role_arn=inputs.task_role_arns[other_actor],
        )
    if kind is TargetKind.FOUNDATION_TASK_ROLE:
        return ResolvedTarget(
            kind=kind,
            cluster_arn=cluster,
            task_definition_arn=own,
            task_role_arn=targets.foundation_task_role_arn,
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
        self, *, cluster_arn: str, task_definition_arn: str, task_role_arn: str | None
    ) -> Observation: ...
    def stop_task(self, *, cluster_arn: str, task_arn: str) -> Observation: ...
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
#: The RunTask operations, whose unexpected success is a task to stop.
_LAUNCHING: Final[frozenset[Operation]] = frozenset(
    {Operation.ECS_RUN_TASK, Operation.ECS_RUN_TASK_ROLE_OVERRIDE}
)
#: Operations per executed subcell: the operation, plus one StopTask on an unexpected launch.
SUBCELL_OPERATION_BUDGET: Final = 2
#: Cleanup operations per created key: one DeleteObject and one HeadObject.
CLEANUP_OPERATIONS_PER_KEY: Final = 2


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


PERMISSION_ATTEMPT_CONTRACT_ID: Final = "kalpamani-permission-attempt/v1"
PERMISSION_RECORD_CONTRACT_ID: Final = "kalpamani-permission-record/v1"
PERMISSION_CLEANUP_CONTRACT_ID: Final = "kalpamani-permission-cleanup/v1"
MAX_PERMISSION_RECORD_BYTES: Final = 32 * 1024


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionBinding:
    """What a permission record binds its evidence to. Digests only.

    ``policy_declaration_sha256`` is :func:`declaration_digest` over the tracked
    production declarations (the identity policies, bootstrap policies, permission sets,
    task roles and the bucket-policy statements) -- a change to any of them makes every
    permission record HISTORICAL, exactly as ADR-0036 s.3 and readiness s.4.6 require;
    ``registration_sha256`` is the digest of the launch-inputs record the targets were
    resolved from.
    """

    environment_binding_sha256: str
    policy_declaration_sha256: str
    registration_sha256: str
    partition: str
    region: str

    def document(self) -> dict[str, Any]:
        return {
            "environment_binding_sha256": self.environment_binding_sha256,
            "policy_declaration_sha256": self.policy_declaration_sha256,
            "registration_sha256": self.registration_sha256,
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
    }
    if type(document) is not dict or set(document) != fields_:
        raise ValueError("permission binding: closed field set")
    values = {name: exact_str(document[name]) for name in fields_}
    if any(v is None for v in values.values()):
        raise ValueError("permission binding: field")
    for name in ("environment_binding_sha256", "policy_declaration_sha256", "registration_sha256"):
        if hex_digest(values[name]) is None:
            raise ValueError("permission binding: digest")
    return PermissionBinding(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionAttempt:
    """Written **before** the operation: what is attempted, and the key it may create."""

    subcell_id: str
    principal: Principal
    stamp: str
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
            "key": self.key,
            "started_at": self.started_at.isoformat(),
            "binding": self.binding.document(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionRecord:
    """What one executed subcell established. Classes, counts, digests -- no value."""

    subcell_id: str
    cell_id: str
    principal: Principal
    operation: Operation
    target: TargetKind
    expectation: Expectation
    stamp: str
    observed: ObservedClass
    outcome: SubcellOutcome
    #: The physical key this subcell may have created (present when ``creates``).
    created_key: str | None
    #: For a launching operation that unexpectedly started a task: its id and whether
    #: the immediate StopTask was acknowledged.
    started_task_id: str | None
    stop_acknowledged: bool | None
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
            "observed": self.observed.value,
            "outcome": self.outcome.value,
            "created_key": self.created_key,
            "started_task_id": self.started_task_id,
            "stop_acknowledged": self.stop_acknowledged,
            "operations": self.operations,
            "identity_verified": self.identity_verified,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "binding": self.binding.document(),
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.document()))


@dataclass(frozen=True, slots=True, kw_only=True)
class CleanupKey:
    """One key the cleanup attempted: what the delete and the confirmation answered."""

    key: str
    delete_observed: ObservedClass
    confirmation_observed: ObservedClass | None
    confirmed_absent: bool

    def document(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "delete_observed": self.delete_observed.value,
            "confirmation_observed": (
                None if self.confirmation_observed is None else self.confirmation_observed.value
            ),
            "confirmed_absent": self.confirmed_absent,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionCleanup:
    """One cleanup pass by the control principal over every key the session created."""

    stamp: str
    keys: tuple[CleanupKey, ...]
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


def _issue(cell: Subcell, target: ResolvedTarget, client: PermissionClient) -> Observation:
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
        return client.run_task(
            cluster_arn=target.cluster_arn,
            task_definition_arn=target.task_definition_arn,
            task_role_arn=target.task_role_arn,
        )
    if op is Operation.ECS_EXECUTE_COMMAND:
        assert target.cluster_arn is not None
        # No task of ours is running to execute into; the refusal is what is expected,
        # and a task ARN of a well-formed shape on our cluster is enough to ask for it.
        return client.execute_command(cluster_arn=target.cluster_arn, task_arn=_no_task(target))
    raise ValueError("an R-1-evidenced operation is never issued here")


def bucket_of(target: TargetKind, *, licensed_bucket: str, control_bucket: str) -> str:
    """The bucket a created key of ``target`` lives in: the CONTROL bucket for its one kind."""
    return control_bucket if target is TargetKind.CONTROL_BUCKET_OBJECT else licensed_bucket


def _no_task(target: ResolvedTarget) -> str:
    """A well-formed task ARN on the target cluster that names no task of ours."""
    assert target.cluster_arn is not None
    match = _CLUSTER_ARN_RE.fullmatch(target.cluster_arn)
    assert match is not None
    return f"{match.group(1).replace(':cluster/', ':task/')}{match.group(2)}/{'0' * 32}"


def run_subcell(
    cell: Subcell,
    *,
    target: ResolvedTarget,
    client: PermissionClient,
    stamp: str,
    binding: PermissionBinding,
    identity_verified: bool,
    now: datetime,
    started_at: datetime,
) -> PermissionRecord:
    """Execute one subcell: one operation, one decision, one bounded reaction.

    The caller has already written the attempt record and verified the principal's
    identity (``identity_verified`` records that it did). A DENIED launch that started a
    task is stopped at once -- the one extra operation the budget allows -- and the record
    carries the task id and the acknowledgement; the subcell is INVERTED either way.
    """
    if cell.layer is not Layer.L3_RUNTIME:
        raise ValueError("only an L3 runtime subcell is executed")
    observation = _issue(cell, target, client)
    observed = classify(observation)
    outcome = decide(cell, observed)
    operations = 1
    started_task_id: str | None = None
    stop_acknowledged: bool | None = None
    if cell.operation in _LAUNCHING and observed is ObservedClass.OK_200:
        task_arn = observation.task_arn
        match = TASK_ARN_RE.fullmatch(task_arn or "")
        started_task_id = match.group(3) if match else "unknown"
        assert target.cluster_arn is not None
        if task_arn is not None:
            stop = client.stop_task(cluster_arn=target.cluster_arn, task_arn=task_arn)
            operations += 1
            stop_acknowledged = classify(stop) is ObservedClass.OK_200
        else:
            stop_acknowledged = False
        outcome = SubcellOutcome.INVERTED
    created = (
        target.key
        if cell.creates and observed is ObservedClass.OK_200 and target.key is not None
        else None
    )
    return PermissionRecord(
        subcell_id=cell.subcell_id,
        cell_id=cell.cell_id,
        principal=cell.principal,
        operation=cell.operation,
        target=cell.target,
        expectation=cell.expectation,
        stamp=stamp,
        observed=observed,
        outcome=outcome,
        created_key=created,
        started_task_id=started_task_id,
        stop_acknowledged=stop_acknowledged,
        operations=operations,
        identity_verified=identity_verified,
        started_at=started_at,
        finished_at=now,
        binding=binding,
    )


def run_cleanup(
    keys: tuple[tuple[str, str], ...],
    *,
    client: PermissionClient,
    stamp: str,
    binding: PermissionBinding,
    identity_verified: bool,
    now: datetime,
    budget: int,
) -> PermissionCleanup:
    """The control principal removes every ``(bucket, key)`` and confirms each absent.

    Two operations per key inside ``budget``; a key whose confirmation is not ``404`` --
    or that the budget did not reach -- is residue. Cleanup restores the buckets; it never
    changes what a subcell established.
    """
    done: list[CleanupKey] = []
    residue: list[str] = []
    operations = 0
    exhausted = False
    for bucket, key in keys:
        if operations + CLEANUP_OPERATIONS_PER_KEY > budget:
            exhausted = True
            residue.append(key)
            continue
        delete = classify(client.delete_object(bucket, key))
        operations += 1
        confirmation = classify(client.head_object(bucket, key))
        operations += 1
        confirmed = confirmation is ObservedClass.NOT_FOUND_404
        done.append(
            CleanupKey(
                key=key,
                delete_observed=delete,
                confirmation_observed=confirmation,
                confirmed_absent=confirmed,
            )
        )
        if not confirmed:
            residue.append(key)
    return PermissionCleanup(
        stamp=stamp,
        keys=tuple(done),
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
        "observed",
        "outcome",
        "created_key",
        "started_task_id",
        "stop_acknowledged",
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
        "key",
        "started_at",
        "binding",
    }
)
_CLEANUP_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "stamp",
        "keys",
        "residue",
        "operations",
        "budget_exhausted",
        "identity_verified",
        "recorded_at",
        "binding",
    }
)


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
    started_task_id = d["started_task_id"]
    stop = d["stop_acknowledged"]
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
        or (started_task_id is not None and exact_str(started_task_id) is None)
        or (stop is not None and type(stop) is not bool)
        or (started_task_id is None) != (stop is None)
    ):
        raise ValueError("permission record: field")
    # The outcome must be the one the class decides; a record cannot claim otherwise.
    expected = decide(cell, observed)
    if started_task_id is not None:
        expected = SubcellOutcome.INVERTED
    if outcome is not expected:
        raise ValueError("permission record: outcome contradicts the observed class")
    created = _optional_key(d["created_key"])
    if created is not None and not (cell.creates and observed is ObservedClass.OK_200):
        raise ValueError("permission record: a created key without a creating success")
    return PermissionRecord(
        subcell_id=cell_id,
        cell_id=cell.cell_id,
        principal=principal,
        operation=operation,
        target=target,
        expectation=expectation,
        stamp=stamp,
        observed=observed,
        outcome=outcome,
        created_key=created,
        started_task_id=started_task_id,
        stop_acknowledged=stop,
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
    return PermissionAttempt(
        subcell_id=cell_id,
        principal=principal,
        stamp=stamp,
        key=_optional_key(d["key"]),
        started_at=started_at,
        binding=_binding_from(d["binding"]),
    )


def parse_permission_cleanup(raw: object) -> PermissionCleanup:
    """A cleanup record, parsed closed; residue must agree with the keys."""
    d = _document(raw, PERMISSION_CLEANUP_CONTRACT_ID, _CLEANUP_FIELDS)
    stamp = exact_str(d["stamp"])
    recorded_at = instant(d["recorded_at"])
    if (
        stamp is None
        or _STAMP_RE.fullmatch(stamp) is None
        or recorded_at is None
        or type(d["keys"]) is not list
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
            "key",
            "delete_observed",
            "confirmation_observed",
            "confirmed_absent",
        }:
            raise ValueError("permission cleanup: key block")
        key = _optional_key(block["key"])
        if key is None or type(block["confirmed_absent"]) is not bool:
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
                key=key,
                delete_observed=_member(ObservedClass, block["delete_observed"]),
                confirmation_observed=confirmation,
                confirmed_absent=confirmed,
            )
        )
    residue = tuple(_optional_key(r) or "" for r in d["residue"])
    if any(not r for r in residue):
        raise ValueError("permission cleanup: residue")
    unconfirmed = {k.key for k in keys if not k.confirmed_absent}
    if not unconfirmed <= set(residue):
        raise ValueError("permission cleanup: an unconfirmed key is not residue")
    if d["operations"] != CLEANUP_OPERATIONS_PER_KEY * len(keys):
        raise ValueError("permission cleanup: operations")
    return PermissionCleanup(
        stamp=stamp,
        keys=tuple(keys),
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
    """Every permission record, attempt and cleanup the runner read, and the current binding."""

    records: dict[str, tuple[PermissionRecord, ...]] = field(default_factory=dict)
    attempts: dict[str, tuple[PermissionAttempt, ...]] = field(default_factory=dict)
    cleanups: tuple[PermissionCleanup, ...] = ()
    malformed: int = 0
    binding: PermissionBinding | None = None


def derive_subcell(
    cell: Subcell,
    evidence: PermissionEvidence,
    *,
    r1_passed: dict[ProductionActor, bool],
) -> SubcellState:
    """One subcell's state from the records, bound to the current binding.

    A record for another binding is HISTORICAL. Among records for the current binding
    the latest by start decides, except that an INVERTED record is never superseded by a
    later MATCHED one under the same binding (an observed failure does not disappear when
    later evidence arrives); a created key must be confirmed removed by a cleanup under
    the same binding. An attempt with no record after it is INTERRUPTED.
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
                reason="no current binding to hold the recorded evidence to",
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
    if not records:
        if attempts:
            return SubcellState(
                subcell_id=cell.subcell_id,
                status=SubcellStatus.INTERRUPTED,
                reason="an attempt was recorded and no result followed it; the cleanup "
                "removes the key it named, and the subcell is not re-executed automatically",
            )
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
    # Every attempt under this binding must be answered by a record started at or after it.
    latest_record_start = max(r.started_at for r in records)
    if any(a.started_at > latest_record_start for a in attempts):
        return SubcellState(
            subcell_id=cell.subcell_id,
            status=SubcellStatus.INTERRUPTED,
            reason="a later attempt was recorded and no result followed it",
        )
    if any(r.outcome is SubcellOutcome.INVERTED for r in records):
        inverted = [r for r in records if r.outcome is SubcellOutcome.INVERTED][-1]
        detail = ""
        if inverted.started_task_id is not None:
            detail = (
                "; a task was started and stopped"
                if inverted.stop_acknowledged
                else "; a task was started and the stop was NOT acknowledged"
            )
        return SubcellState(
            subcell_id=cell.subcell_id,
            status=SubcellStatus.FAILED,
            reason=f"observed {inverted.observed.value} against {cell.expectation.value}{detail}",
        )
    latest = sorted(records, key=lambda r: r.started_at)[-1]
    if latest.outcome is SubcellOutcome.UNDECIDED:
        return SubcellState(
            subcell_id=cell.subcell_id,
            status=SubcellStatus.UNDECIDED,
            reason=f"the last answer decided nothing ({latest.observed.value})",
        )
    if not latest.identity_verified:
        return SubcellState(
            subcell_id=cell.subcell_id,
            status=SubcellStatus.UNBOUND,
            reason="the record does not attest that the principal's identity was verified",
        )
    for required in cell.requires:
        dependency = SUBCELL_BY_ID[required]
        required_records = [
            r
            for r in evidence.records.get(required, ())
            if r.binding == binding and r.outcome is SubcellOutcome.MATCHED
        ]
        if not required_records or required_records[-1].started_at > latest.started_at:
            return SubcellState(
                subcell_id=cell.subcell_id,
                status=SubcellStatus.UNBOUND,
                reason=f"its prerequisite object from {dependency.subcell_id} was not "
                "established before it under this binding",
            )
    created = {r.created_key for r in records if r.created_key is not None}
    if created:
        confirmed: set[str] = set()
        for cleanup in evidence.cleanups:
            if cleanup.binding == binding:
                confirmed |= cleanup.confirmed_keys
        if not created <= confirmed:
            return SubcellState(
                subcell_id=cell.subcell_id,
                status=SubcellStatus.CLEANUP_UNRESOLVED,
                reason="an object this subcell created is not confirmed removed "
                "(scripts/production_permission_cells.py --cleanup)",
            )
    return SubcellState(
        subcell_id=cell.subcell_id,
        status=SubcellStatus.PASSED,
        reason=f"observed {latest.observed.value} as expected under the current binding",
    )


__all__ = [
    "CLEANUP_OPERATIONS_PER_KEY",
    "DELETION_DEPENDENCY",
    "MAX_PERMISSION_RECORD_BYTES",
    "MAX_PERMISSION_TARGETS_BYTES",
    "PERMISSION_ATTEMPT_CONTRACT_ID",
    "PERMISSION_CLEANUP_CONTRACT_ID",
    "PERMISSION_RECORD_CONTRACT_ID",
    "PERMISSION_TARGETS_CONTRACT_ID",
    "PRINCIPAL_ACTOR",
    "PRINCIPAL_PROFILE",
    "SUBCELLS",
    "SUBCELL_BY_ID",
    "SUBCELL_OPERATION_BUDGET",
    "SYNTHETIC_MARKER",
    "TASK_PROBE_DEPENDENCY",
    "CleanupKey",
    "Expectation",
    "Layer",
    "Operation",
    "PermissionAttempt",
    "PermissionBinding",
    "PermissionCleanup",
    "PermissionClient",
    "PermissionEvidence",
    "PermissionRecord",
    "PermissionTargets",
    "Principal",
    "ResolvedTarget",
    "Subcell",
    "SubcellOutcome",
    "SubcellState",
    "SubcellStatus",
    "TargetKind",
    "bucket_of",
    "decide",
    "declaration_digest",
    "derive_subcell",
    "parse_permission_attempt",
    "parse_permission_cleanup",
    "parse_permission_record",
    "parse_permission_targets",
    "resolve_target",
    "run_cleanup",
    "run_subcell",
    "subcell",
    "subcells_of",
    "synthetic_run_id",
]
