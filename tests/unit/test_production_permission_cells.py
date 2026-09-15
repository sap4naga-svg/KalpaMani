"""The R-4 .. R-9 permission subcells (ADR-0047), on fakes and synthetic records only.

Every subcell traces to an ADR-0036 s.3 phrase; a task-role or deletion-role subcell is
BLOCKED with its exact dependency and a human role never stands in for it; one operation
per subcell with one bounded reaction; an unexpected launch is stopped and recorded; records
parse closed and bind to the current declaration and registration; an inversion never
disappears; cleanup is confirmed or reported as residue; the tool refuses by default and
constructs no client before the flag, the profile and the identity proof. **Mocked results
are not AWS verification.**
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from test_production_launch_script import _Scenario as _LaunchScenario
from test_production_launch_script import _security

from fixtures.production_launch import ACQ, BLD, launch_inputs_document
from fixtures.production_runtime import (
    ACCOUNT,
    CANARIES,
    CLUSTER_ARN,
    NOW,
    FakeClock,
    encode,
    human_identity_arn,
    launcher_identity_arn,
    verification_revision_arn,
)
from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar import permission_cells as pc
from kalpamani.data.production.sharadar import r3_verification as r3
from kalpamani.data.production.sharadar import verification_cells as vc
from kalpamani.data.production.sharadar.launch_records import parse_launch_inputs
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for
from kalpamani.data.qualify.sharadar import runtime_binding as rb

pytestmark = pytest.mark.unit

REPO_ROOT: Final = Path(__file__).resolve().parents[2]


def _module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tool = _module(
    "production_permission_cells", REPO_ROOT / "scripts" / "production_permission_cells.py"
)
runner = _module(
    "production_verification_cells", REPO_ROOT / "scripts" / "production_verification_cells.py"
)

BUCKET: Final = "synthetic-licensed-bucket"
CONTROL_BUCKET: Final = "synthetic-control-bucket"
STAMP: Final = "20260914T180000Z-abcd"
TARGETS: Final = pc.PermissionTargets(
    foundation_task_role_arn=f"arn:aws:iam::{ACCOUNT}:role/synthetic-foundation-task",
    qualification_secret_arn=(
        f"arn:aws:secretsmanager:us-east-1:{ACCOUNT}:secret:synthetic/qualification-AbCdEf"
    ),
    control_bucket_name=CONTROL_BUCKET,
)
BINDING: Final = pc.PermissionBinding(
    environment_binding_sha256="ab" * 32,
    policy_declaration_sha256="cd" * 32,
    registration_sha256="ef" * 32,
    targets_sha256=TARGETS.digest,
    partition="aws",
    region="us-east-1",
)
OTHER_BINDING: Final = pc.PermissionBinding(
    environment_binding_sha256="ab" * 32,
    policy_declaration_sha256="99" * 32,
    registration_sha256="ef" * 32,
    targets_sha256=TARGETS.digest,
    partition="aws",
    region="us-east-1",
)
INPUTS: Final = parse_launch_inputs(encode(launch_inputs_document()))
SECRET_NAME: Final = "synthetic/production/sharadar"  # noqa: S105 - a name, not a value
CONTEXT: Final = pc.PermissionContext(
    binding=BINDING,
    licensed_bucket=BUCKET,
    inputs=INPUTS,
    targets=TARGETS,
    production_secret=SECRET_NAME,
)
OTHER_CONTEXT: Final = pc.PermissionContext(
    binding=OTHER_BINDING,
    licensed_bucket=BUCKET,
    inputs=INPUTS,
    targets=TARGETS,
    production_secret=SECRET_NAME,
)
TASK_ARN: Final = f"{CLUSTER_ARN.replace(':cluster/', ':task/')}/{'a' * 32}"


def _resolve(cell: pc.Subcell) -> pc.ResolvedTarget:
    return pc.resolve_target(
        cell,
        stamp=STAMP,
        licensed_bucket=BUCKET,
        inputs=INPUTS,
        targets=TARGETS,
        production_secret=SECRET_NAME,
    )


class FakePermissionClient:
    """Answers every operation from a script of observations; records what was asked."""

    def __init__(self, *answers: r3.Observation) -> None:
        self.answers = list(answers)
        #: Answers per operation name, consulted before the ordered script.
        self.by_operation: dict[str, list[r3.Observation]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.attempt_files_seen: list[int] = []
        self.records_dir: Path | None = None

    def _next(self, operation: str, /, **kwargs: Any) -> r3.Observation:
        self.calls.append((operation, kwargs))
        if self.records_dir is not None:
            self.attempt_files_seen.append(len(list(self.records_dir.glob("permission-attempt-*"))))
        if self.by_operation.get(operation):
            return self.by_operation[operation].pop(0)
        if not self.answers:
            return r3.Observation(status=403, code="AccessDenied", message="denied")
        return self.answers.pop(0)

    def put_object(self, bucket: str, key: str, body: bytes, *, if_none_match: bool) -> Any:
        assert body == pc.SYNTHETIC_MARKER
        return self._next("put_object", bucket=bucket, key=key, if_none_match=if_none_match)

    def get_object(self, bucket: str, key: str) -> Any:
        return self._next("get_object", bucket=bucket, key=key)

    def head_object(self, bucket: str, key: str) -> Any:
        return self._next("head_object", bucket=bucket, key=key)

    def delete_object(self, bucket: str, key: str) -> Any:
        return self._next("delete_object", bucket=bucket, key=key)

    def list_objects(self, bucket: str) -> Any:
        return self._next("list_objects", bucket=bucket)

    def get_secret_value(self, secret_id: str) -> Any:
        return self._next("get_secret_value", secret_id=secret_id)

    def describe_secret(self, secret_id: str) -> Any:
        return self._next("describe_secret", secret_id=secret_id)

    def get_parameter(self, name: str) -> Any:
        return self._next("get_parameter", name=name)

    def put_parameter(self, name: str, value: str) -> Any:
        return self._next("put_parameter", name=name, value=value)

    def run_task(self, **kwargs: Any) -> Any:
        return self._next("run_task", **kwargs)

    def stop_task(self, *, cluster_arn: str, task_arn: str) -> Any:
        return self._next("stop_task", cluster_arn=cluster_arn, task_arn=task_arn)

    def list_tasks(self, *, cluster_arn: str, started_by: str, next_token: str | None) -> Any:
        return self._next(
            "list_tasks", cluster_arn=cluster_arn, started_by=started_by, next_token=next_token
        )

    def describe_tasks(self, *, cluster_arn: str, task_arns: tuple[str, ...]) -> Any:
        return self._next("describe_tasks", cluster_arn=cluster_arn, task_arns=task_arns)

    def execute_command(self, *, cluster_arn: str, task_arn: str) -> Any:
        return self._next("execute_command", cluster_arn=cluster_arn, task_arn=task_arn)


OK = r3.Observation(status=200)
NO_CONTENT = r3.Observation(status=204)
NOT_FOUND = r3.Observation(status=404, code="404")
DENIED = r3.Observation(status=403, code="AccessDenied", message="denied")
TIMEOUT = r3.Observation(status=None, transport_failure="timeout")
LAUNCHED = r3.Observation(status=200, task_arns=(TASK_ARN,))
STOPPED = r3.Observation(status=200, task_statuses=((TASK_ARN, "STOPPED"),))
RUNNING = r3.Observation(status=200, task_statuses=((TASK_ARN, "RUNNING"),))
LISTED_NONE = r3.Observation(status=200, task_arns=())
LISTED_ONE = r3.Observation(status=200, task_arns=(TASK_ARN,))
AUTH_DIGEST: Final = "11" * 32
STATEMENT_DIGEST: Final = "22" * 32


def _attempt(cell_id: str, **fields: Any) -> pc.PermissionAttempt:
    """An attempt for ``cell_id`` under BINDING, fields overridable."""
    cell = pc.subcell(cell_id)
    target = _resolve(cell) if not cell.requires else None
    base: dict[str, Any] = {
        "subcell_id": cell.subcell_id,
        "principal": cell.principal,
        "stamp": STAMP,
        "authorization_sha256": AUTH_DIGEST,
        "statement_sha256": STATEMENT_DIGEST,
        "bucket": target.bucket if cell.creates and target is not None else None,
        "key": target.key if cell.creates and target is not None else None,
        "started_at": NOW,
        "binding": BINDING,
    }
    base.update(fields)
    return pc.PermissionAttempt(**base)


def _record(cell_id: str, **fields: Any) -> pc.PermissionRecord:
    """A MATCHED record for ``cell_id`` under BINDING, fields overridable.

    ``attempt`` (an attempt) binds the record to it by digest; ``prerequisites`` names the
    bound prerequisite records; a ``created_key`` names its bucket.
    """
    cell = pc.subcell(cell_id)
    matched = (
        pc.ObservedClass.DENIED_OTHER
        if cell.expectation is pc.Expectation.DENIED
        else pc._SUCCESS_CLASS[cell.operation]
    )
    attempt: pc.PermissionAttempt | None = fields.pop("attempt", None)
    prerequisites: dict[str, pc.PermissionRecord] = fields.pop("prerequisites", {})
    base: dict[str, Any] = {
        "subcell_id": cell.subcell_id,
        "cell_id": cell.cell_id,
        "principal": cell.principal,
        "operation": cell.operation,
        "target": cell.target,
        "expectation": cell.expectation,
        "stamp": STAMP if attempt is None else attempt.stamp,
        "attempt_sha256": AUTH_DIGEST if attempt is None else attempt.digest,
        "authorization_sha256": AUTH_DIGEST if attempt is None else attempt.authorization_sha256,
        "prerequisites": {k: v.digest for k, v in prerequisites.items()},
        "observed": matched,
        "outcome": pc.SubcellOutcome.MATCHED,
        "created_bucket": None,
        "created_key": None,
        "possibly_created": False,
        "started_task_ids": (),
        "stop_acknowledged_ids": (),
        "started_by": (
            pc.started_by_of(STAMP if attempt is None else attempt.stamp)
            if cell.operation in pc._LAUNCHING
            else None
        ),
        "possibly_started": False,
        "operations": 1,
        "identity_verified": True,
        "started_at": NOW if attempt is None else attempt.started_at,
        "finished_at": (NOW if attempt is None else attempt.started_at) + timedelta(seconds=1),
        "binding": BINDING if attempt is None else attempt.binding,
    }
    if fields.get("created_key") is not None and "created_bucket" not in fields:
        fields["created_bucket"] = BUCKET
    base.update(fields)
    return pc.PermissionRecord(**base)


def _run(
    cell: pc.Subcell,
    client: Any,
    *,
    target: pc.ResolvedTarget | None = None,
    attempt: pc.PermissionAttempt | None = None,
    now: datetime | None = None,
) -> pc.PermissionRecord:
    """``run_subcell`` on a fresh attempt for ``cell``."""
    attempt = _attempt(cell.subcell_id) if attempt is None else attempt
    return pc.run_subcell(
        cell,
        target=_resolve(cell) if target is None else target,
        attempt=attempt,
        prerequisites={},
        client=client,
        identity_verified=True,
        now=attempt.started_at + timedelta(seconds=2) if now is None else now,
    )


@dataclass(frozen=True)
class _Bound:
    """A recorded result with every component the validator binds it through."""

    record: pc.PermissionRecord
    attempt: pc.PermissionAttempt
    statement: pc.PermissionStatement
    consumption: pc.PermissionConsumption
    prerequisites: dict[str, pc.PermissionRecord]


def _bound(
    cell_id: str,
    *,
    context: pc.PermissionContext = CONTEXT,
    stamp: str = STAMP,
    started_at: datetime = NOW,
    prerequisites: dict[str, pc.PermissionRecord] | None = None,
    created: bool | None = None,
    **record_fields: Any,
) -> _Bound:
    """The complete chain for one result of ``cell_id`` under ``context``, consistent.

    ``created`` forces the created key on (``True``) or off (``False``); by default a
    creating subcell whose observed class is its success class records the target key.
    """
    cell = pc.subcell(cell_id)
    prerequisites = dict(prerequisites or {})
    target = context.resolve(cell, stamp=stamp, prerequisites=prerequisites)
    statement = pc.statement_for(
        cell,
        target=target,
        stamp=stamp,
        binding=context.binding,
        targets_sha256=context.binding.targets_sha256,
        prerequisites=prerequisites,
        prepared_at=started_at - timedelta(minutes=10),
    )
    authorization = pc.PermissionAuthorization(
        subcell_id=cell_id,
        statement_sha256=statement.digest,
        issued_at=started_at - timedelta(minutes=5),
        expires_at=started_at + timedelta(hours=1),
    )
    attempt = pc.PermissionAttempt(
        subcell_id=cell_id,
        principal=cell.principal,
        stamp=stamp,
        authorization_sha256=authorization.digest,
        statement_sha256=statement.digest,
        bucket=target.bucket if cell.creates else None,
        key=target.key if cell.creates else None,
        started_at=started_at,
        binding=context.binding,
    )
    consumption = pc.PermissionConsumption(
        subcell_id=cell_id,
        statement_sha256=statement.digest,
        authorization_sha256=authorization.digest,
        consumed_at=started_at,
    )
    fields: dict[str, Any] = dict(record_fields)
    observed = fields.get("observed")
    success = observed is None or observed is pc._SUCCESS_CLASS[cell.operation]
    if created is None:
        created = cell.creates and success and cell.expectation is pc.Expectation.ALLOWED
        if cell.creates and observed is pc.ObservedClass.OK_200:
            created = True
    if created:
        fields.setdefault("created_key", target.key)
        fields.setdefault("created_bucket", target.bucket)
    record = _record(
        cell_id,
        attempt=attempt,
        prerequisites=prerequisites,
        binding=context.binding,
        **fields,
    )
    return _Bound(
        record=record,
        attempt=attempt,
        statement=statement,
        consumption=consumption,
        prerequisites=prerequisites,
    )


def _cleanup_for(
    *records: pc.PermissionRecord,
    recorded_at: datetime | None = None,
    confirmed: bool = True,
    tasks_stopped: bool = True,
    discovered: tuple[str, ...] = (),
    identity_verified: bool = True,
) -> pc.PermissionCleanup:
    """A cleanup settling every open object and launch of ``records`` by identity.

    ``discovered`` are the tasks the discovery listed for a launch that recorded none
    (an ambiguous launch); with none discovered the launch stays unresolved residue.
    """
    keys = []
    task_blocks = []
    residue: list[str] = []
    for r in records:
        if r.created_key is not None:
            assert r.created_bucket is not None
            keys.append(
                pc.CleanupKey(
                    bucket=r.created_bucket,
                    key=r.created_key,
                    attempt_sha256=r.attempt_sha256,
                    delete_observed=pc.ObservedClass.OK_204,
                    confirmation_observed=(
                        pc.ObservedClass.NOT_FOUND_404 if confirmed else pc.ObservedClass.OK_200
                    ),
                    confirmed_absent=confirmed,
                )
            )
            if not confirmed:
                residue.append(r.created_key)
        if r.launch_open:
            assert r.started_by is not None
            ids = r.started_task_ids or discovered
            listings = 1
            block = pc.CleanupTasks(
                attempt_sha256=r.attempt_sha256,
                started_by=r.started_by,
                listings=listings,
                list_observed=pc.ObservedClass.OK_200,
                discovery_failed=False,
                discovery_incomplete=False,
                task_ids=ids,
                stopped_ids=ids if tasks_stopped else (),
                residue_ids=() if tasks_stopped else ids,
                operations=listings + len(ids) + (0 if tasks_stopped else len(ids)),
            )
            task_blocks.append(block)
            if not tasks_stopped:
                residue.extend(f"task:{i}" for i in ids)
            elif not ids:
                residue.append(f"launch:{r.started_by}:undiscovered")
    return pc.PermissionCleanup(
        stamp="20260914T200000Z-0c1e",
        keys=tuple(keys),
        tasks=tuple(task_blocks),
        deferred=(),
        residue=tuple(residue),
        operations=2 * len(keys) + sum(b.operations for b in task_blocks),
        budget_exhausted=False,
        identity_verified=identity_verified,
        recorded_at=(NOW + timedelta(hours=1)) if recorded_at is None else recorded_at,
        binding=BINDING,
    )


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


class TestCatalogue:
    def test_every_subcell_traces_to_a_permission_cell_and_an_adr_0036_phrase(self) -> None:
        permission_cells = {
            c.cell_id for c in vc.REQUIRED_CELLS if c.kind is vc.CellKind.PERMISSION_MATRIX
        }
        assert {s.cell_id for s in pc.SUBCELLS} == permission_cells
        for s in pc.SUBCELLS:
            ref = f"R-{s.cell_id[1]}"
            assert s.trace.startswith(f"{ref} must "), s.subcell_id
            assert "must succeed" in s.trace or "must be refused" in s.trace
            assert (s.trace.split(": ", 1)[0].endswith("must succeed")) == (
                s.expectation is pc.Expectation.ALLOWED
            ), s.subcell_id
        assert len({s.subcell_id for s in pc.SUBCELLS}) == len(pc.SUBCELLS)

    def test_task_roles_and_the_deletion_role_are_blocked_with_their_dependency(self) -> None:
        # ADR-0048: the task-role subcells are executed by the permission-probe
        # launch (L3_TASK), the ExecuteCommand subcells against the actor's own held probe
        # task (L3_HELD_TASK); only the deletion role stays BLOCKED, on the governance
        # decision its dependency names.
        for s in pc.SUBCELLS:
            if s.principal in (pc.Principal.ACQUISITION_TASK, pc.Principal.BUILD_TASK):
                assert s.layer is pc.Layer.L3_TASK and s.blocked_on is None
                assert pc.PRINCIPAL_PROFILE[s.principal] is None
                # The same operation exists under the human role as its own subcell, never
                # as evidence for the task role; a task subcell reads the object the human
                # prerequisite created.
                twin = pc.subcell(s.subcell_id.replace("-TASK", "-HUMAN"))
                assert twin.principal in (pc.Principal.ACQUISITION_HUMAN, pc.Principal.BUILD_HUMAN)
                assert all(r.endswith("-HUMAN") for r in s.requires)
            elif s.principal is pc.Principal.DELETION_ROLE:
                assert s.layer is pc.Layer.BLOCKED and s.blocked_on == pc.DELETION_DEPENDENCY
                assert "ADR-0048" in s.blocked_on and "governance decision" in s.blocked_on
            elif s.operation is pc.Operation.ECS_EXECUTE_COMMAND:
                assert s.layer is pc.Layer.L3_HELD_TASK and s.blocked_on is None
                assert s.target is pc.TargetKind.OWN_TASK
            else:
                assert s.layer is not pc.Layer.BLOCKED and s.blocked_on is None
        by_layer = {layer: sum(1 for s in pc.SUBCELLS if s.layer is layer) for layer in pc.Layer}
        assert by_layer[pc.Layer.BLOCKED] == 2
        assert by_layer[pc.Layer.L3_RUNTIME] == 56
        assert by_layer[pc.Layer.L3_TASK] == 32
        assert by_layer[pc.Layer.L3_HELD_TASK] == 2
        assert by_layer[pc.Layer.L3_BY_R1] == 6
        assert pc.PROBE_LAYERS == {pc.Layer.L3_TASK, pc.Layer.L3_HELD_TASK}
        assert pc.EXECUTABLE_LAYERS == {pc.Layer.L3_RUNTIME, *pc.PROBE_LAYERS}

    def test_the_launchers_positive_operations_are_evidenced_by_r1_only(self) -> None:
        by_r1 = [s for s in pc.SUBCELLS if s.layer is pc.Layer.L3_BY_R1]
        assert len(by_r1) == 6 and all(s.cell_id == "R6-LAUNCHERS" for s in by_r1)
        assert all(s.expectation is pc.Expectation.ALLOWED for s in by_r1)
        with pytest.raises(ValueError):
            _run(by_r1[0], FakePermissionClient())

    def test_prerequisites_name_existing_creating_subcells(self) -> None:
        for s in pc.SUBCELLS:
            for required in s.requires:
                dependency = pc.subcell(required)
                assert dependency.creates and dependency.expectation is pc.Expectation.ALLOWED
                assert dependency.layer is pc.Layer.L3_RUNTIME
        with pytest.raises(ValueError):
            pc.subcell("R4-NOTHING")


# ---------------------------------------------------------------------------
# Targets, decisions, the engine
# ---------------------------------------------------------------------------


class TestTargets:
    def test_synthetic_keys_lie_exactly_in_their_namespaces(self) -> None:
        run_id = pc.synthetic_run_id(STAMP)
        digest = sha256_hex(pc.SYNTHETIC_MARKER)
        expectations = {
            "R4-PUT-PAYLOAD-HUMAN": f"bronze/sharadar/tickers/production/objects/sha256/{digest}",
            "R4-PUT-RECORD-HUMAN": (
                f"bronze/sharadar/tickers/production/acquisitions/{digest}/{run_id}.01.json"
            ),
            "R4-PUT-CLAIM-HUMAN": f"bronze/_production_claims/{digest}/{run_id}.01.json",
            "R4-PUT-INDEX-HUMAN": f"bronze/sharadar/_indexes/{run_id}.json",
            "R5-PUT-SILVER-HUMAN": f"silver/sharadar/tickers/objects/sha256/{digest}",
            "R5-PUT-GOLD-HUMAN": f"gold/sharadar/verification/objects/sha256/{digest}",
            "R5-PUT-MANIFEST-HUMAN": f"manifests/sharadar/builds/{run_id}.json",
            "R4-PUT-QUALIFICATION-HUMAN": f"qualification/sharadar/_verification/{STAMP}/marker",
        }
        for subcell_id, key in expectations.items():
            target = _resolve(pc.subcell(subcell_id))
            assert target.bucket == BUCKET and target.key == key, subcell_id
        control = _resolve(pc.subcell("R4-PUT-CONTROL-HUMAN"))
        assert control.bucket == CONTROL_BUCKET and control.key == f"_verification/{STAMP}/marker"
        assert _resolve(pc.subcell("R4-LIST-HUMAN")).key is None
        with pytest.raises(ValueError):
            pc.synthetic_run_id("not-a-stamp")
        # Every synthetic key lies inside a namespace the tracked declarations name.
        policies = (
            REPO_ROOT / "infra" / "aws" / "research-data-plane" / "production_policies.tf"
        ).read_text(encoding="utf-8")
        storage = (REPO_ROOT / "infra" / "aws" / "research-data-plane" / "storage.tf").read_text(
            encoding="utf-8"
        )
        for key in expectations.values():
            prefix = key.split("/")[0] + "/"
            assert f"/{prefix}" in policies or f"/{prefix}" in storage, key
        assert "/_verification/*" in storage

    def test_a_dependent_read_takes_the_exact_object_its_prerequisite_created(self) -> None:
        """PR #106 correction 1, finding 2: never a key derived from the reader's own stamp."""
        put = pc.subcell("R4-PUT-RECORD-HUMAN")
        get = pc.subcell("R5-GET-RECORD-HUMAN")
        created = _record(put.subcell_id, created_key=_resolve(put).key)
        assert created.created_key is not None
        target = pc.resolve_target(
            get,
            stamp="20260914T190000Z-ffff",
            licensed_bucket=BUCKET,
            inputs=INPUTS,
            targets=TARGETS,
            production_secret=None,
            prerequisites={put.subcell_id: created},
        )
        assert target.bucket == BUCKET and target.key == created.created_key
        assert pc.synthetic_run_id("20260914T190000Z-ffff") not in target.key
        # Without a bound MATCHED record naming its object, the read has no target.
        for wrong in (
            {},
            {put.subcell_id: _record(put.subcell_id)},
            {
                put.subcell_id: _record(
                    "R4-PUT-PAYLOAD-HUMAN",
                    created_key=_resolve(pc.subcell("R4-PUT-PAYLOAD-HUMAN")).key,
                )
            },
        ):
            with pytest.raises(ValueError):
                pc.resolve_target(
                    get,
                    stamp=STAMP,
                    licensed_bucket=BUCKET,
                    inputs=INPUTS,
                    targets=TARGETS,
                    production_secret=None,
                    prerequisites=wrong,
                )

    def test_launch_targets_carry_the_registered_placement_and_a_digest(self) -> None:
        target = _resolve(pc.subcell("R6-ACQ-RUN-OTHER-REVISION"))
        assert target.subnet_id == INPUTS.subnet_ids[ACQ]
        assert target.security_group_ids == tuple(INPUTS.security_group_ids[ACQ])
        assert (
            target.assign_public_ip is True and target.platform_version == INPUTS.platform_version
        )
        build = _resolve(pc.subcell("R6-BLD-RUN-OTHER-CLUSTER"))
        assert build.assign_public_ip is False and build.subnet_id == INPUTS.subnet_ids[BLD]
        assert target.digest != build.digest and len(target.digest) == 64
        assert TASK_ARN not in repr(target)

    def test_launch_targets_are_the_registered_ones_or_derivations_the_policy_cannot_name(
        self,
    ) -> None:
        own = verification_revision_arn(ACQ)
        assert _resolve(pc.subcell("R6-ACQ-RUN-OWN-REVISION")).task_definition_arn == own
        other_actor = _resolve(pc.subcell("R6-ACQ-RUN-OTHER-ACTOR")).task_definition_arn
        assert other_actor == verification_revision_arn(BLD)
        other_revision = _resolve(pc.subcell("R6-ACQ-RUN-OTHER-REVISION")).task_definition_arn
        assert other_revision == own.replace(":7", ":8") and other_revision != own
        other_family = _resolve(pc.subcell("R6-ACQ-RUN-OTHER-FAMILY")).task_definition_arn
        assert other_family is not None and other_family != own and other_family != other_actor
        other_cluster = _resolve(pc.subcell("R6-ACQ-RUN-OTHER-CLUSTER"))
        assert other_cluster.cluster_arn != CLUSTER_ARN and other_cluster.task_definition_arn == own
        override = _resolve(pc.subcell("R6-BLD-OVERRIDE-OTHER-ROLE"))
        assert override.task_role_arn == INPUTS.task_role_arns[ProductionActor.ACQUISITION]
        foundation = _resolve(pc.subcell("R9-ACQ-OVERRIDE-FOUNDATION-ROLE"))
        assert foundation.task_role_arn == TARGETS.foundation_task_role_arn
        secret = _resolve(pc.subcell("R4-SECRET-GET-HUMAN"))
        assert secret.name == SECRET_NAME
        assert _resolve(pc.subcell("R4-SECRET-GET-QUALIFICATION-HUMAN")).name == (
            TARGETS.qualification_secret_arn
        )
        assert _resolve(pc.subcell("R4-SSM-GET-OTHER-HUMAN")).name == (
            constants_for(BLD).binding_parameter
        )
        assert _resolve(pc.subcell("R5-SSM-GET-ACQUISITION-HUMAN")).name == (
            constants_for(ACQ).binding_parameter
        )
        with pytest.raises(ValueError):
            pc.resolve_target(
                pc.subcell("R4-SECRET-GET-HUMAN"),
                stamp=STAMP,
                licensed_bucket=BUCKET,
                inputs=INPUTS,
                targets=TARGETS,
                production_secret=None,
            )
        assert "synthetic" not in repr(_resolve(pc.subcell("R4-PUT-PAYLOAD-HUMAN")))

    def test_the_targets_document_is_closed(self) -> None:
        document = {
            "schema_version": 1,
            "contract_id": pc.PERMISSION_TARGETS_CONTRACT_ID,
            "foundation_task_role_arn": TARGETS.foundation_task_role_arn,
            "qualification_secret_arn": TARGETS.qualification_secret_arn,
            "control_bucket_name": CONTROL_BUCKET,
        }
        assert pc.parse_permission_targets(canonical_bytes(document)) == TARGETS
        mutations: tuple[Callable[[dict[str, Any]], object], ...] = (
            lambda d: d.__setitem__("foundation_task_role_arn", "not-an-arn"),
            lambda d: d.__setitem__("qualification_secret_arn", "not-an-arn"),
            lambda d: d.__setitem__("control_bucket_name", "Bad Bucket"),
            lambda d: d.pop("control_bucket_name"),
            lambda d: d.__setitem__("extra", 1),
        )
        for mutate in mutations:
            broken = dict(document)
            mutate(broken)
            with pytest.raises(ValueError):
                pc.parse_permission_targets(canonical_bytes(broken))
        assert TARGETS.foundation_task_role_arn not in repr(TARGETS)


class TestDecisions:
    @pytest.mark.parametrize(
        ("expectation", "observed", "outcome"),
        [
            (pc.Expectation.ALLOWED, pc.ObservedClass.OK_200, pc.SubcellOutcome.MATCHED),
            (pc.Expectation.ALLOWED, pc.ObservedClass.DENIED_OTHER, pc.SubcellOutcome.INVERTED),
            (
                pc.Expectation.ALLOWED,
                pc.ObservedClass.DENIED_IDENTITY_POLICY,
                pc.SubcellOutcome.INVERTED,
            ),
            (pc.Expectation.ALLOWED, pc.ObservedClass.NOT_FOUND_404, pc.SubcellOutcome.UNDECIDED),
            (pc.Expectation.ALLOWED, pc.ObservedClass.TIMEOUT, pc.SubcellOutcome.UNDECIDED),
            (pc.Expectation.DENIED, pc.ObservedClass.DENIED_OTHER, pc.SubcellOutcome.MATCHED),
            (
                pc.Expectation.DENIED,
                pc.ObservedClass.DENIED_RESOURCE_POLICY,
                pc.SubcellOutcome.MATCHED,
            ),
            (pc.Expectation.DENIED, pc.ObservedClass.OK_200, pc.SubcellOutcome.INVERTED),
            (
                pc.Expectation.DENIED,
                pc.ObservedClass.AUTHENTICATION_FAILURE,
                pc.SubcellOutcome.UNDECIDED,
            ),
            (pc.Expectation.DENIED, pc.ObservedClass.NO_SUCH_BUCKET, pc.SubcellOutcome.UNDECIDED),
            (pc.Expectation.DENIED, pc.ObservedClass.AMBIGUOUS, pc.SubcellOutcome.UNDECIDED),
            (pc.Expectation.DENIED, pc.ObservedClass.NOT_FOUND_404, pc.SubcellOutcome.UNDECIDED),
        ],
    )
    def test_a_classified_answer_decides_one_outcome(
        self,
        expectation: pc.Expectation,
        observed: pc.ObservedClass,
        outcome: pc.SubcellOutcome,
    ) -> None:
        cell = pc.subcell(
            "R4-PUT-PAYLOAD-HUMAN" if expectation is pc.Expectation.ALLOWED else "R4-LIST-HUMAN"
        )
        assert pc.decide(cell, observed) is outcome

    def test_a_delete_matches_204_and_nothing_else(self) -> None:
        cell = pc.subcell("R4-DELETE-OWN-WRITE-HUMAN")
        assert cell.expectation is pc.Expectation.DENIED
        assert pc.decide(cell, pc.ObservedClass.OK_204) is pc.SubcellOutcome.INVERTED
        assert pc.decide(cell, pc.ObservedClass.OK_200) is pc.SubcellOutcome.UNDECIDED


class TestEngine:
    def test_one_operation_one_record_created_key_on_success(self) -> None:
        cell = pc.subcell("R4-PUT-PAYLOAD-HUMAN")
        client = FakePermissionClient(OK)
        attempt = _attempt(cell.subcell_id)
        record = _run(cell, client, attempt=attempt)
        assert record.outcome is pc.SubcellOutcome.MATCHED and record.operations == 1
        assert record.created_key == _resolve(cell).key and record.created_bucket == BUCKET
        assert record.attempt_sha256 == attempt.digest and not record.possibly_created
        assert record.started_task_ids == () and not record.possibly_started
        assert [c[0] for c in client.calls] == ["put_object"]
        assert client.calls[0][1]["if_none_match"] is True
        assert pc.parse_permission_record(canonical_bytes(record.document())) == record

    def test_a_refused_put_creates_nothing_and_an_allowed_put_refused_is_inverted(self) -> None:
        cell = pc.subcell("R4-PUT-SILVER-HUMAN")  # DENIED, creates
        record = _run(cell, FakePermissionClient(DENIED))
        assert record.outcome is pc.SubcellOutcome.MATCHED and record.created_key is None
        assert not record.possibly_created
        inverted = _run(cell, FakePermissionClient(OK))
        # An unexpected success is an inversion AND an object: the key is recorded for cleanup.
        assert inverted.outcome is pc.SubcellOutcome.INVERTED
        assert inverted.created_key == _resolve(cell).key
        allowed = pc.subcell("R4-PUT-PAYLOAD-HUMAN")
        refused = _run(allowed, FakePermissionClient(DENIED))
        assert refused.outcome is pc.SubcellOutcome.INVERTED and refused.created_key is None

    def test_an_ambiguous_write_is_recorded_as_possibly_committed(self) -> None:
        """PR #106 correction 1, finding 3: a timeout leaves the object open for the cleanup."""
        cell = pc.subcell("R4-PUT-PAYLOAD-HUMAN")
        for answer in (
            TIMEOUT,
            r3.Observation(status=None, transport_failure="network"),
            r3.Observation(status=412, code="PreconditionFailed"),
            r3.Observation(status=503, code="SlowDown"),
        ):
            record = _run(cell, FakePermissionClient(answer))
            assert record.outcome is pc.SubcellOutcome.UNDECIDED, answer
            assert record.created_key is None and record.possibly_created, answer
            assert record.object_open
            assert pc.parse_permission_record(canonical_bytes(record.document())) == record
        # A definitive refusal or a missing bucket committed nothing.
        for answer in (DENIED, r3.Observation(status=404, code="NoSuchBucket")):
            record = _run(cell, FakePermissionClient(answer))
            assert not record.possibly_created and not record.object_open
        # And a record cannot claim a possibly committed write its class rules out.
        document = _run(cell, FakePermissionClient(DENIED)).document()
        document["possibly_created"] = True
        with pytest.raises(ValueError):
            pc.parse_permission_record(canonical_bytes(document))

    def test_an_unexpected_launch_is_stopped_at_once_and_recorded(self) -> None:
        cell = pc.subcell("R9-ACQ-OVERRIDE-FOUNDATION-ROLE")
        client = FakePermissionClient(LAUNCHED, OK)
        attempt = _attempt(cell.subcell_id)
        record = _run(cell, client, attempt=attempt)
        assert record.outcome is pc.SubcellOutcome.INVERTED and record.operations == 2
        assert record.started_task_ids == ("a" * 32,)
        assert record.stop_acknowledged_ids == ("a" * 32,)
        assert record.started_by == pc.started_by_of(attempt.stamp)
        assert record.launch_open and not record.possibly_started
        assert [c[0] for c in client.calls] == ["run_task", "stop_task"]
        run = client.calls[0][1]
        assert run["task_role_arn"] == TARGETS.foundation_task_role_arn
        assert run["started_by"] == record.started_by and run["subnet_id"] == INPUTS.subnet_ids[ACQ]
        assert run["security_group_ids"] == tuple(INPUTS.security_group_ids[ACQ])
        assert run["platform_version"] == INPUTS.platform_version and run["assign_public_ip"]
        assert client.calls[1][1]["task_arn"] == TASK_ARN
        # A stop that is refused is recorded as not acknowledged; still INVERTED, still open.
        client = FakePermissionClient(LAUNCHED, DENIED)
        record = _run(cell, client)
        assert record.stop_acknowledged_ids == () and record.outcome is pc.SubcellOutcome.INVERTED
        assert pc.parse_permission_record(canonical_bytes(record.document())) == record
        # Every returned task is accounted for, up to the bound, whatever failure entries
        # came beside them (PR #106 correction 1, finding 4).
        many = r3.Observation(
            status=200,
            task_arns=tuple(TASK_ARN[:-1] + c for c in "0123456"),
            failures=1,
        )
        client = FakePermissionClient(many, OK, OK, DENIED, OK)
        record = _run(cell, client)
        assert len(record.started_task_ids) == pc.MAX_RETURNED_TASKS
        assert record.operations == 1 + pc.MAX_RETURNED_TASKS
        assert len(record.stop_acknowledged_ids) == 3
        assert [c[0] for c in client.calls].count("stop_task") == pc.MAX_RETURNED_TASKS
        assert pc.parse_permission_record(canonical_bytes(record.document())) == record
        # The expected refusal: one operation, no task, MATCHED, nothing open.
        client = FakePermissionClient(DENIED)
        record = _run(cell, client)
        assert record.outcome is pc.SubcellOutcome.MATCHED and len(client.calls) == 1
        assert not record.launch_open
        assert record.digest and TASK_ARN not in json.dumps(record.document())

    def test_an_ambiguous_launch_is_recorded_as_possibly_started_and_never_retried(self) -> None:
        """PR #106 correction 1, finding 4: no blind RunTask retry; the cleanup lists by tag."""
        cell = pc.subcell("R6-ACQ-RUN-OTHER-REVISION")
        for answer in (
            TIMEOUT,
            r3.Observation(status=None, code="RunTaskFailureEntry", failures=1),
            r3.Observation(status=None, transport_failure="network"),
        ):
            client = FakePermissionClient(answer)
            record = _run(cell, client)
            assert record.outcome is pc.SubcellOutcome.UNDECIDED and record.possibly_started
            assert record.started_task_ids == () and record.launch_open
            assert [c[0] for c in client.calls] == ["run_task"]
            assert pc.parse_permission_record(canonical_bytes(record.document())) == record
        record = _run(cell, FakePermissionClient(DENIED))
        assert not record.possibly_started and not record.launch_open

    def test_a_transport_failure_decides_nothing(self) -> None:
        cell = pc.subcell("R5-LIST-HUMAN")
        record = _run(cell, FakePermissionClient(TIMEOUT))
        assert record.outcome is pc.SubcellOutcome.UNDECIDED
        assert record.observed is pc.ObservedClass.TIMEOUT
        assert not record.object_open and not record.launch_open

    def test_the_record_contract_refuses_contradictions(self) -> None:
        record = _record("R4-LIST-HUMAN")
        document = record.document()
        assert pc.parse_permission_record(canonical_bytes(document)) == record
        contradictions: tuple[tuple[Callable[[dict[str, Any]], object], str], ...] = (
            (lambda d: d.__setitem__("outcome", "INVERTED"), "outcome contradicts the class"),
            (lambda d: d.__setitem__("operation", "S3_GET"), "contradicts the subcell definition"),
            (lambda d: d.__setitem__("created_key", "silver/x"), "created key without a success"),
            (lambda d: d.__setitem__("operations", 3), "operations without tasks"),
            (lambda d: d.__setitem__("started_task_ids", ["a" * 32]), "a task on a non-launch"),
            (lambda d: d.__setitem__("started_by", "x"), "a tag on a non-launch"),
            (lambda d: d.__setitem__("attempt_sha256", "zz"), "attempt digest"),
            (lambda d: d.__setitem__("prerequisites", {"R4-PUT-PAYLOAD-HUMAN": "ab" * 32}), "prq"),
            (lambda d: d.__setitem__("stamp", "nope"), "stamp"),
            (lambda d: d.__setitem__("identity_verified", "yes"), "identity flag"),
            (lambda d: d.__setitem__("subcell_id", "R4-NOTHING"), "unknown subcell"),
            (lambda d: d["binding"].__setitem__("registration_sha256", "zz"), "binding digest"),
            (lambda d: d.__setitem__("extra", 1), "closed fields"),
        )
        for mutate, why in contradictions:
            broken = json.loads(json.dumps(document))
            mutate(broken)
            with pytest.raises(ValueError):
                pc.parse_permission_record(canonical_bytes(broken))
            del why

    def test_cleanup_confirms_each_key_or_reports_residue_within_the_budget(self) -> None:
        objects = tuple(
            pc.ObjectToSettle(bucket=b, key=k, attempt_sha256=a)
            for b, k, a in (
                (BUCKET, "silver/a", "a1" * 32),
                (BUCKET, "gold/b", "b2" * 32),
                (CONTROL_BUCKET, "_verification/c", "c3" * 32),
            )
        )
        client = FakePermissionClient(NO_CONTENT, NOT_FOUND, NO_CONTENT, OK, DENIED, NOT_FOUND)
        cleanup = pc.run_cleanup(
            objects,
            (),
            client=client,
            stamp=STAMP,
            deferred=("silver/kept",),
            binding=BINDING,
            identity_verified=True,
            now=NOW,
            budget=6,
        )
        assert cleanup.confirmed_keys == {"silver/a", "_verification/c"}
        assert cleanup.residue == ("gold/b",) and cleanup.operations == 6
        assert cleanup.deferred == ("silver/kept",) and not cleanup.budget_exhausted
        assert cleanup.settles_object("a1" * 32, BUCKET, "silver/a")
        assert not cleanup.settles_object("zz" * 32, BUCKET, "silver/a")  # another attempt
        assert not cleanup.settles_object("b2" * 32, BUCKET, "gold/b")
        assert client.calls[4][1]["bucket"] == CONTROL_BUCKET
        assert pc.parse_permission_cleanup(canonical_bytes(cleanup.document())) == cleanup
        # The budget is never exceeded: keys beyond it are residue, untouched.
        client = FakePermissionClient(NO_CONTENT, NOT_FOUND)
        exhausted = pc.run_cleanup(
            objects,
            (),
            client=client,
            stamp=STAMP,
            deferred=(),
            binding=BINDING,
            identity_verified=True,
            now=NOW,
            budget=2,
        )
        assert exhausted.budget_exhausted and exhausted.residue == ("gold/b", "_verification/c")
        assert len(client.calls) == 2
        # A cleanup record that claims a confirmation its class contradicts is refused.
        broken = cleanup.document()
        broken["keys"][1]["confirmed_absent"] = True
        with pytest.raises(ValueError):
            pc.parse_permission_cleanup(canonical_bytes(broken))

    def test_cleanup_settles_tasks_by_bounded_discovery_describing_and_stopping(self) -> None:
        """PR #106 corrections 1 and 2, finding 4/2: termination evidence, never absence."""
        launch = pc.TasksToSettle(
            attempt_sha256="d4" * 32,
            started_by=pc.started_by_of(STAMP),
            cluster_arn=CLUSTER_ARN,
            known_task_ids=("a" * 32,),
        )

        def cleanup_with(client: FakePermissionClient, *launches: pc.TasksToSettle) -> Any:
            return pc.run_cleanup(
                (),
                launches,
                client=client,
                stamp=STAMP,
                deferred=(),
                binding=BINDING,
                identity_verified=True,
                now=NOW,
                budget=60,
            )

        # Known task, discovery (one listing by the tag alone) lists nothing new, the task
        # described STOPPED.
        client = FakePermissionClient(LISTED_NONE, STOPPED)
        cleanup = cleanup_with(client, launch)
        calls = [c[0] for c in client.calls]
        assert calls == ["list_tasks", "describe_tasks"]
        listing = client.calls[0][1]
        assert set(listing) == {"cluster_arn", "started_by", "next_token"}
        assert listing["started_by"] == launch.started_by and listing["next_token"] is None
        block = cleanup.tasks[0]
        assert block.listings == 1 and block.stopped_ids == ("a" * 32,) and block.settled
        assert not block.discovery_failed and not block.discovery_incomplete
        assert cleanup.settles_tasks("d4" * 32, ("a" * 32,)) and cleanup.residue == ()
        assert cleanup.operations == 2
        assert pc.parse_permission_cleanup(canonical_bytes(cleanup.document())) == cleanup
        # Still RUNNING: stopped once more, residue, not settled.
        client = FakePermissionClient(LISTED_NONE, RUNNING, OK)
        cleanup = cleanup_with(client, launch)
        assert [c[0] for c in client.calls][-2:] == ["describe_tasks", "stop_task"]
        assert cleanup.tasks[0].residue_ids == ("a" * 32,)
        assert cleanup.residue == ("task:" + "a" * 32,)
        assert not cleanup.settles_tasks("d4" * 32, ("a" * 32,))
        # An ambiguous launch with no known task and nothing discovered: NOT settled --
        # an empty discovery is never proof of absence (finding 2 of correction 2).
        unknown = pc.TasksToSettle(
            attempt_sha256="e5" * 32,
            started_by=pc.started_by_of(STAMP),
            cluster_arn=CLUSTER_ARN,
            known_task_ids=(),
        )
        client = FakePermissionClient(LISTED_NONE)
        cleanup = cleanup_with(client, unknown)
        block = cleanup.tasks[0]
        assert len(client.calls) == 1
        assert block.undiscovered and not block.settled and block.residue_ids == ()
        assert cleanup.residue == (f"launch:{unknown.started_by}:undiscovered",)
        assert not cleanup.settles_tasks("e5" * 32, ())
        assert pc.parse_permission_cleanup(canonical_bytes(cleanup.document())) == cleanup
        # Empty, then visible: a later pass discovers the task (ECS still returning it by
        # the tag) and settles it on STOPPED evidence.
        client = FakePermissionClient(LISTED_ONE, STOPPED)
        cleanup = cleanup_with(client, unknown)
        assert cleanup.tasks[0].task_ids == ("a" * 32,) and cleanup.tasks[0].settled
        assert cleanup.settles_tasks("e5" * 32, ()) and cleanup.residue == ()
        # Persistent empty discovery across passes stays unresolved every time -- a task
        # that stopped before ECS returned it by the tag is never discovered here, and
        # the launch is never settled by that absence (the limitation is documented).
        for _ in range(3):
            cleanup = cleanup_with(FakePermissionClient(LISTED_NONE), unknown)
            assert not cleanup.tasks[0].settled and cleanup.residue
        # A listing that does not answer is a failed discovery: residue, never an absence.
        client = FakePermissionClient(DENIED)
        cleanup = cleanup_with(client, unknown)
        assert len(client.calls) == 1 and cleanup.tasks[0].discovery_failed
        assert cleanup.residue == (f"launch:{unknown.started_by}:failed",)
        assert not cleanup.settles_tasks("e5" * 32, ())
        # A paginated listing is followed within its bound; a token remaining beyond it is
        # an incomplete discovery: the tasks found are still described, nothing is settled.
        paged = r3.Observation(status=200, task_arns=(), next_token="more")  # noqa: S106 - a page token
        paged_task = r3.Observation(
            status=200,
            task_arns=(TASK_ARN,),
            next_token="more",  # noqa: S106 - a page token
        )
        client = FakePermissionClient(paged, paged_task, paged, STOPPED)
        cleanup = cleanup_with(client, unknown)
        listing_calls = [c for c in client.calls if c[0] == "list_tasks"]
        assert len(listing_calls) == pc.DISCOVERY_MAX_PAGES
        assert [c[1]["next_token"] for c in listing_calls] == [None, "more", "more"]
        assert cleanup.tasks[0].discovery_incomplete and not cleanup.tasks[0].settled
        assert cleanup.tasks[0].stopped_ids == ("a" * 32,)
        assert cleanup.residue == (f"launch:{unknown.started_by}:incomplete",)
        # Budget: a launch beyond it is residue, untouched.
        client = FakePermissionClient()
        cleanup = pc.run_cleanup(
            (),
            (launch, unknown),
            client=client,
            stamp=STAMP,
            deferred=(),
            binding=BINDING,
            identity_verified=True,
            now=NOW,
            budget=pc.CLEANUP_OPERATIONS_PER_TASK_MAX,
        )
        assert (
            cleanup.budget_exhausted
            and f"launch:{unknown.started_by}:undiscovered" in cleanup.residue
        )
        # A cleanup record cannot claim a task both stopped and residue, nor a settled
        # discovery that found nothing off the residue, nor a failed discovery beside OK.
        good = cleanup_with(FakePermissionClient(LISTED_NONE, STOPPED), launch)
        assert good.tasks[0].settled and good.residue == ()
        for mutate in (
            lambda d: d["tasks"][0].__setitem__("stopped_ids", []),
            lambda d: d["tasks"][0].__setitem__("discovery_failed", True),
            lambda d: (
                d["tasks"][0].__setitem__("task_ids", []),
                d["tasks"][0].__setitem__("stopped_ids", []),
                d["tasks"][0].__setitem__("operations", 1),
                d.__setitem__("operations", 1),
            ),
        ):
            broken = good.document()
            mutate(broken)
            with pytest.raises(ValueError):
                pc.parse_permission_cleanup(canonical_bytes(broken))
        # Correction 1 of PR #109: a deletion-rehearsal launch is settled by this same
        # rule under its own tag; the record round-trips, and any other tag stays refused.
        assert pc.CLEANUP_STARTED_BY_PREFIXES == ("kalpamani-permission-", "kalpamani-rehearsal-")
        rehearsal = pc.TasksToSettle(
            attempt_sha256="f6" * 32,
            started_by="kalpamani-rehearsal-" + STAMP,
            cluster_arn=CLUSTER_ARN,
            known_task_ids=(),
        )
        cleanup = cleanup_with(FakePermissionClient(LISTED_ONE, STOPPED), rehearsal)
        assert cleanup.tasks[0].started_by == rehearsal.started_by and cleanup.tasks[0].settled
        assert cleanup.settles_tasks("f6" * 32, ())
        assert pc.parse_permission_cleanup(canonical_bytes(cleanup.document())) == cleanup
        foreign = cleanup.document()
        foreign["tasks"][0]["started_by"] = "kalpamani-production-" + STAMP
        with pytest.raises(ValueError):
            pc.parse_permission_cleanup(canonical_bytes(foreign))


# ---------------------------------------------------------------------------
# Deriving subcells and cells
# ---------------------------------------------------------------------------


def _evidence(
    *items: pc.PermissionRecord | _Bound,
    attempts: tuple[pc.PermissionAttempt, ...] = (),
    statements: tuple[pc.PermissionStatement, ...] = (),
    consumptions: tuple[pc.PermissionConsumption, ...] = (),
    cleanups: tuple[pc.PermissionCleanup, ...] = (),
    context: pc.PermissionContext | None = CONTEXT,
    malformed: int = 0,
) -> pc.PermissionEvidence:
    """Evidence from bound chains (every component) and bare records (the record alone)."""
    grouped: dict[str, list[pc.PermissionRecord]] = {}
    grouped_attempts: dict[str, list[pc.PermissionAttempt]] = {}
    grouped_statements: dict[str, list[pc.PermissionStatement]] = {}
    consumed: dict[str, pc.PermissionConsumption] = {}
    for item in items:
        if isinstance(item, _Bound):
            grouped.setdefault(item.record.subcell_id, []).append(item.record)
            grouped_attempts.setdefault(item.attempt.subcell_id, []).append(item.attempt)
            grouped_statements.setdefault(item.statement.subcell_id, []).append(item.statement)
            consumed[item.consumption.authorization_sha256] = item.consumption
        else:
            grouped.setdefault(item.subcell_id, []).append(item)
    for a in attempts:
        grouped_attempts.setdefault(a.subcell_id, []).append(a)
    for s in statements:
        grouped_statements.setdefault(s.subcell_id, []).append(s)
    for c in consumptions:
        consumed[c.authorization_sha256] = c
    return pc.PermissionEvidence(
        records={k: tuple(v) for k, v in grouped.items()},
        attempts={k: tuple(v) for k, v in grouped_attempts.items()},
        statements={k: tuple(v) for k, v in grouped_statements.items()},
        consumptions=consumed,
        cleanups=cleanups,
        malformed=malformed,
        context=context,
    )


R1: Final = {ProductionActor.ACQUISITION: False, ProductionActor.BUILD: False}


class TestDerivation:
    def test_a_bound_result_under_the_current_context_passes(self) -> None:
        cell = pc.subcell("R4-LIST-HUMAN")
        state = pc.derive_subcell(cell, _evidence(_bound(cell.subcell_id)), r1_passed=R1)
        assert state.status is pc.SubcellStatus.PASSED
        assert pc.derive_subcell(cell, _evidence(), r1_passed=R1).status is (
            pc.SubcellStatus.UNEXECUTED
        )

    def test_a_record_alone_never_passes(self) -> None:
        """PR #106 correction 2, finding 1: a result binds only through its whole chain."""
        cell = pc.subcell("R4-LIST-HUMAN")
        state = pc.derive_subcell(cell, _evidence(_record(cell.subcell_id)), r1_passed=R1)
        assert state.status is pc.SubcellStatus.UNBOUND
        assert pc.ChainDefect.ATTEMPT_MISSING.value in state.reason
        # Each component missing, substituted or contradicting: UNBOUND with the defect.
        good = _bound(cell.subcell_id)
        other = _bound(cell.subcell_id, stamp="20260914T170000Z-0000")
        cases: list[tuple[str, pc.PermissionEvidence]] = [
            (
                "ATTEMPT_MISSING",
                _evidence(
                    good.record, statements=(good.statement,), consumptions=(good.consumption,)
                ),
            ),
            (
                "STATEMENT_MISSING",
                _evidence(good.record, attempts=(good.attempt,), consumptions=(good.consumption,)),
            ),
            (
                "STATEMENT_MISSING",
                _evidence(
                    good.record,
                    attempts=(good.attempt,),
                    statements=(other.statement,),
                    consumptions=(good.consumption,),
                ),
            ),
            (
                "CONSUMPTION_MISSING",
                _evidence(good.record, attempts=(good.attempt,), statements=(good.statement,)),
            ),
            (
                "CONSUMPTION_MISSING",
                _evidence(
                    good.record,
                    attempts=(good.attempt,),
                    statements=(good.statement,),
                    consumptions=(other.consumption,),
                ),
            ),
            (
                "CONSUMPTION_MISMATCH",
                _evidence(
                    good.record,
                    attempts=(good.attempt,),
                    statements=(good.statement,),
                    consumptions=(
                        pc.PermissionConsumption(
                            subcell_id=cell.subcell_id,
                            statement_sha256=other.statement.digest,
                            authorization_sha256=good.consumption.authorization_sha256,
                            consumed_at=good.consumption.consumed_at,
                        ),
                    ),
                ),
            ),
            (
                "CONSUMPTION_MISMATCH",
                _evidence(
                    good.record,
                    attempts=(good.attempt,),
                    statements=(good.statement,),
                    consumptions=(
                        pc.PermissionConsumption(
                            subcell_id=cell.subcell_id,
                            statement_sha256=good.statement.digest,
                            authorization_sha256=good.consumption.authorization_sha256,
                            consumed_at=good.attempt.started_at + timedelta(seconds=1),
                        ),
                    ),
                ),
            ),
            (
                "ATTEMPT_MISMATCH",
                _evidence(
                    _record(
                        cell.subcell_id,
                        attempt=good.attempt,
                        authorization_sha256="77" * 32,
                    ),
                    attempts=(good.attempt,),
                    statements=(good.statement,),
                    consumptions=(good.consumption,),
                ),
            ),
        ]
        for defect, evidence in cases:
            state = pc.derive_subcell(cell, evidence, r1_passed=R1)
            assert state.status is pc.SubcellStatus.UNBOUND, defect
            assert defect in state.reason, (defect, state.reason)
        no_context = pc.derive_subcell(cell, _evidence(good, context=None), r1_passed=R1)
        assert (
            no_context.status is pc.SubcellStatus.UNBOUND
            and "no current binding" in no_context.reason
        )
        with pytest.raises(pc.ChainError) as raised:
            pc.bind_result(good.record, _evidence(good, context=None))
        assert raised.value.defect is pc.ChainDefect.NO_CONTEXT
        # Another attempt of the same subcell in place of the record's own: that attempt
        # is unanswered (INTERRUPTED), and the record still binds to nothing.
        substituted = _evidence(
            good.record,
            attempts=(other.attempt,),
            statements=(good.statement,),
            consumptions=(good.consumption,),
        )
        assert pc.derive_subcell(cell, substituted, r1_passed=R1).status is (
            pc.SubcellStatus.INTERRUPTED
        )
        with pytest.raises(pc.ChainError) as raised:
            pc.bind_result(good.record, substituted)
        assert raised.value.defect is pc.ChainDefect.ATTEMPT_MISSING
        # The exact target: a statement whose target digest is not what the context resolves
        # now is TARGET_MISMATCH; a subcell whose target cannot be resolved from the current
        # inputs (no acquisition configuration for the production secret) is UNRESOLVABLE --
        # a missing current input never preserves a PASSED.
        wrong_target = pc.PermissionStatement(
            **{
                **{
                    f: getattr(good.statement, f)
                    for f in pc.PermissionStatement.__slots__
                    if f != "target_sha256"
                },
                "target_sha256": "55" * 32,
            }
        )
        attempt = pc.PermissionAttempt(
            **{
                **{
                    f: getattr(good.attempt, f)
                    for f in pc.PermissionAttempt.__slots__
                    if f != "statement_sha256"
                },
                "statement_sha256": wrong_target.digest,
            }
        )
        consumption = pc.PermissionConsumption(
            subcell_id=cell.subcell_id,
            statement_sha256=wrong_target.digest,
            authorization_sha256=attempt.authorization_sha256,
            consumed_at=attempt.started_at,
        )
        record = _record(cell.subcell_id, attempt=attempt)
        state = pc.derive_subcell(
            cell,
            _evidence(
                record,
                attempts=(attempt,),
                statements=(wrong_target,),
                consumptions=(consumption,),
            ),
            r1_passed=R1,
        )
        assert state.status is pc.SubcellStatus.UNBOUND and "TARGET_MISMATCH" in state.reason
        secret = pc.subcell("R4-SECRET-GET-HUMAN")
        chain = _bound(secret.subcell_id)
        assert pc.derive_subcell(secret, _evidence(chain), r1_passed=R1).status is (
            pc.SubcellStatus.PASSED
        )
        without_configuration = pc.PermissionContext(
            binding=BINDING,
            licensed_bucket=BUCKET,
            inputs=INPUTS,
            targets=TARGETS,
            production_secret=None,
        )
        state = pc.derive_subcell(
            secret, _evidence(chain, context=without_configuration), r1_passed=R1
        )
        assert state.status is pc.SubcellStatus.UNBOUND and "TARGET_UNRESOLVABLE" in state.reason

    def test_changed_targets_or_declarations_make_every_result_historical(self) -> None:
        """PR #106 correction 2, finding 1: the binding covers the owner's targets document."""
        cell = pc.subcell("R4-PUT-CONTROL-HUMAN")
        chain = _bound(cell.subcell_id)
        assert pc.derive_subcell(cell, _evidence(chain), r1_passed=R1).status is (
            pc.SubcellStatus.PASSED
        )
        changed = pc.PermissionTargets(
            foundation_task_role_arn=TARGETS.foundation_task_role_arn,
            qualification_secret_arn=TARGETS.qualification_secret_arn,
            control_bucket_name="another-control-bucket",
        )
        renewed_binding = pc.PermissionBinding(
            **{**BINDING.document(), "targets_sha256": changed.digest}
        )
        renewed = pc.PermissionContext(
            binding=renewed_binding,
            licensed_bucket=BUCKET,
            inputs=INPUTS,
            targets=changed,
            production_secret=SECRET_NAME,
        )
        state = pc.derive_subcell(cell, _evidence(chain, context=renewed), r1_passed=R1)
        assert state.status is pc.SubcellStatus.HISTORICAL
        assert "targets_sha256" in pc.PermissionBinding.__slots__
        # Re-executed under the changed targets, the new chain passes and the old stays history.
        again = _bound(cell.subcell_id, context=renewed, stamp="20260914T190000Z-1111")
        assert pc.derive_subcell(
            cell, _evidence(chain, again, context=renewed), r1_passed=R1
        ).status is (pc.SubcellStatus.PASSED)

    def test_an_inversion_never_disappears_under_the_same_binding(self) -> None:
        cell = pc.subcell("R4-LIST-HUMAN")
        inverted = _bound(
            cell.subcell_id, observed=pc.ObservedClass.OK_200, outcome=pc.SubcellOutcome.INVERTED
        )
        later = _bound(
            cell.subcell_id,
            stamp="20260914T190000Z-2222",
            started_at=NOW + timedelta(hours=1),
            finished_at=NOW + timedelta(hours=1),
        )
        state = pc.derive_subcell(cell, _evidence(inverted, later), r1_passed=R1)
        assert state.status is pc.SubcellStatus.FAILED and "OK_200" in state.reason
        # Under a new binding (a corrected declaration) the inversion is historical and the
        # bound result under the new binding decides.
        renewed = _bound(cell.subcell_id, context=OTHER_CONTEXT)
        state = pc.derive_subcell(
            cell, _evidence(inverted, renewed, context=OTHER_CONTEXT), r1_passed=R1
        )
        assert state.status is pc.SubcellStatus.PASSED

    def test_other_binding_undecided_interrupted_and_unverified_identity(self) -> None:
        cell = pc.subcell("R4-LIST-HUMAN")
        stale = pc.derive_subcell(
            cell, _evidence(_bound(cell.subcell_id, context=OTHER_CONTEXT)), r1_passed=R1
        )
        assert stale.status is pc.SubcellStatus.HISTORICAL
        undecided = _bound(
            cell.subcell_id, observed=pc.ObservedClass.TIMEOUT, outcome=pc.SubcellOutcome.UNDECIDED
        )
        assert pc.derive_subcell(cell, _evidence(undecided), r1_passed=R1).status is (
            pc.SubcellStatus.UNDECIDED
        )
        attempt = _attempt(cell.subcell_id, started_at=NOW + timedelta(hours=2))
        state = pc.derive_subcell(
            cell, _evidence(_bound(cell.subcell_id), attempts=(attempt,)), r1_passed=R1
        )
        assert state.status is pc.SubcellStatus.INTERRUPTED
        assert pc.derive_subcell(cell, _evidence(attempts=(attempt,)), r1_passed=R1).status is (
            pc.SubcellStatus.INTERRUPTED
        )
        # Attempts and records join by the attempt's digest, never by order: a record for
        # ANOTHER attempt, however much later, does not answer this one (finding 3).
        earlier = _bound(cell.subcell_id, started_at=NOW - timedelta(hours=2))
        assert pc.derive_subcell(cell, _evidence(earlier), r1_passed=R1).status is (
            pc.SubcellStatus.PASSED
        )
        other = _attempt(cell.subcell_id, started_at=NOW - timedelta(hours=3))
        assert (
            pc.derive_subcell(cell, _evidence(earlier, attempts=(other,)), r1_passed=R1).status
            is pc.SubcellStatus.INTERRUPTED
        )
        unverified = _bound(cell.subcell_id, identity_verified=False)
        assert pc.derive_subcell(cell, _evidence(unverified), r1_passed=R1).status is (
            pc.SubcellStatus.UNBOUND
        )
        assert (
            pc.derive_subcell(
                cell, _evidence(_bound(cell.subcell_id), malformed=1), r1_passed=R1
            ).status
            is pc.SubcellStatus.UNBOUND
        )
        assert (
            pc.derive_subcell(
                cell, _evidence(_bound(cell.subcell_id), context=None), r1_passed=R1
            ).status
            is pc.SubcellStatus.UNBOUND
        )
        assert pc.parse_permission_attempt(canonical_bytes(attempt.document())) == attempt

    def test_prerequisite_objects_and_cleanup_are_required(self) -> None:
        get = pc.subcell("R5-GET-PAYLOAD-HUMAN")
        put = pc.subcell("R4-PUT-PAYLOAD-HUMAN")
        put_chain = _bound(put.subcell_id)
        put_record = put_chain.record
        assert put_record.created_key is not None
        get_chain = _bound(
            get.subcell_id,
            stamp="20260914T190000Z-3333",
            started_at=NOW + timedelta(minutes=5),
            finished_at=NOW + timedelta(minutes=6),
            prerequisites={put.subcell_id: put_record},
        )
        # The exact bound prerequisite record must be present and bound itself: absent,
        # another record, or the same record without its chain, is unbound.
        assert pc.derive_subcell(get, _evidence(get_chain), r1_passed=R1).status is (
            pc.SubcellStatus.UNBOUND
        )
        other = _bound(put.subcell_id, stamp="20260914T170000Z-0000")
        assert pc.derive_subcell(get, _evidence(other, get_chain), r1_passed=R1).status is (
            pc.SubcellStatus.UNBOUND
        )
        assert (
            pc.derive_subcell(get, _evidence(put_record, get_chain), r1_passed=R1).status
            is pc.SubcellStatus.UNBOUND
        )
        state = pc.derive_subcell(get, _evidence(put_chain, get_chain), r1_passed=R1)
        assert state.status is pc.SubcellStatus.PASSED
        # The creating subcell itself waits for its object to be confirmed removed -- by a
        # cleanup naming ITS attempt and ITS exact object, recorded no earlier than it.
        assert pc.derive_subcell(put, _evidence(put_chain), r1_passed=R1).status is (
            pc.SubcellStatus.CLEANUP_UNRESOLVED
        )
        cleanup = _cleanup_for(put_record)
        assert pc.derive_subcell(
            put, _evidence(put_chain, cleanups=(cleanup,)), r1_passed=R1
        ).status is (pc.SubcellStatus.PASSED)
        unresolved = _cleanup_for(put_record, confirmed=False)
        assert (
            pc.derive_subcell(
                put, _evidence(put_chain, cleanups=(unresolved,)), r1_passed=R1
            ).status
            is pc.SubcellStatus.CLEANUP_UNRESOLVED
        )
        before = _cleanup_for(put_record, recorded_at=NOW - timedelta(minutes=1))
        assert (
            pc.derive_subcell(put, _evidence(put_chain, cleanups=(before,)), r1_passed=R1).status
            is pc.SubcellStatus.CLEANUP_UNRESOLVED
        )
        foreign = _record(
            put.subcell_id,
            created_key=put_record.created_key,
            stamp="20260914T170000Z-0000",
            attempt_sha256="99" * 32,
        )
        assert (
            pc.derive_subcell(
                put, _evidence(put_chain, cleanups=(_cleanup_for(foreign),)), r1_passed=R1
            ).status
            is pc.SubcellStatus.CLEANUP_UNRESOLVED
        )
        # A cleanup entry naming the attempt but ANOTHER key does not settle it.
        elsewhere = pc.PermissionCleanup(
            **{
                **{f: getattr(cleanup, f) for f in pc.PermissionCleanup.__slots__ if f != "keys"},
                "keys": (
                    pc.CleanupKey(
                        bucket=BUCKET,
                        key="silver/elsewhere",
                        attempt_sha256=put_record.attempt_sha256,
                        delete_observed=pc.ObservedClass.OK_204,
                        confirmation_observed=pc.ObservedClass.NOT_FOUND_404,
                        confirmed_absent=True,
                    ),
                ),
            }
        )
        assert (
            pc.derive_subcell(put, _evidence(put_chain, cleanups=(elsewhere,)), r1_passed=R1).status
            is pc.SubcellStatus.CLEANUP_UNRESOLVED
        )
        # A possibly committed write stays open until settled; the UNDECIDED result stays.
        open_chain = _bound(
            put.subcell_id,
            stamp="20260914T190000Z-4444",
            observed=pc.ObservedClass.TIMEOUT,
            outcome=pc.SubcellOutcome.UNDECIDED,
            possibly_created=True,
            created=False,
        )
        assert pc.derive_subcell(put, _evidence(open_chain), r1_passed=R1).status is (
            pc.SubcellStatus.CLEANUP_UNRESOLVED
        )
        assert open_chain.attempt.key is not None
        settled = pc.PermissionCleanup(
            stamp="20260914T200000Z-0c1e",
            keys=(
                pc.CleanupKey(
                    bucket=BUCKET,
                    key=open_chain.attempt.key,
                    attempt_sha256=open_chain.attempt.digest,
                    delete_observed=pc.ObservedClass.OK_204,
                    confirmation_observed=pc.ObservedClass.NOT_FOUND_404,
                    confirmed_absent=True,
                ),
            ),
            tasks=(),
            deferred=(),
            residue=(),
            operations=2,
            budget_exhausted=False,
            identity_verified=True,
            recorded_at=NOW + timedelta(hours=1),
            binding=BINDING,
        )
        state = pc.derive_subcell(put, _evidence(open_chain, cleanups=(settled,)), r1_passed=R1)
        assert state.status is pc.SubcellStatus.UNDECIDED and "TIMEOUT" in state.reason

    def test_an_unverified_cleanup_settles_nothing(self) -> None:
        """PR #106 correction 3, finding 2: identity_verified=false confirms no cleanup."""
        put = pc.subcell("R4-PUT-PAYLOAD-HUMAN")
        chain = _bound(put.subcell_id)
        verified = _cleanup_for(chain.record)
        unverified = _cleanup_for(chain.record, identity_verified=False)
        assert verified.document() | {"identity_verified": False} == unverified.document()
        assert pc.derive_subcell(
            put, _evidence(chain, cleanups=(verified,)), r1_passed=R1
        ).status is (pc.SubcellStatus.PASSED)
        state = pc.derive_subcell(put, _evidence(chain, cleanups=(unverified,)), r1_passed=R1)
        assert state.status is pc.SubcellStatus.CLEANUP_UNRESOLVED
        assert "unverified cleanup record is present and settles nothing" in state.reason
        assert not unverified.admissible_for(BINDING, not_before=chain.record.finished_at)
        assert verified.admissible_for(BINDING, not_before=chain.record.finished_at)
        # The unverified record is preserved: it parses, it is listed, it settles nothing;
        # a verified pass beside it settles as before.
        assert pc.parse_permission_cleanup(canonical_bytes(unverified.document())) == unverified
        assert (
            pc.derive_subcell(
                put, _evidence(chain, cleanups=(unverified, verified)), r1_passed=R1
            ).status
            is pc.SubcellStatus.PASSED
        )
        # A dependent's prerequisite is still available after an unverified cleanup (the
        # object was never confirmed removed), and unavailable after a verified one.
        get = pc.subcell("R5-GET-PAYLOAD-HUMAN")
        available = _evidence(chain, cleanups=(unverified,))
        assert pc.unsettled_reason(pc.bind_result(chain.record, available), available.cleanups)
        gone = _evidence(chain, cleanups=(verified,))
        assert pc.unsettled_reason(pc.bind_result(chain.record, gone), gone.cleanups) is None
        del get
        # The launch case: an unverified cleanup confirms no termination.
        launch = pc.subcell("R6-ACQ-RUN-OTHER-REVISION")
        launched = _bound(
            launch.subcell_id,
            observed=pc.ObservedClass.OK_200,
            outcome=pc.SubcellOutcome.INVERTED,
            started_task_ids=("a" * 32,),
            stop_acknowledged_ids=("a" * 32,),
            operations=2,
        )
        unverified_launch = _cleanup_for(launched.record, identity_verified=False)
        state = pc.derive_subcell(
            launch, _evidence(launched, cleanups=(unverified_launch,)), r1_passed=R1
        )
        assert state.status is pc.SubcellStatus.FAILED
        assert "termination NOT confirmed" in state.reason and "unverified cleanup" in state.reason
        assert (
            "termination confirmed"
            in pc.derive_subcell(
                launch, _evidence(launched, cleanups=(_cleanup_for(launched.record),)), r1_passed=R1
            ).reason
        )

    def test_a_started_task_is_settled_only_by_a_confirmed_stop(self) -> None:
        """PR #106 correction 1 (finding 4) and 2 (finding 2): termination evidence only."""
        cell = pc.subcell("R6-ACQ-RUN-OTHER-REVISION")
        launched = _bound(
            cell.subcell_id,
            observed=pc.ObservedClass.OK_200,
            outcome=pc.SubcellOutcome.INVERTED,
            started_task_ids=("a" * 32,),
            stop_acknowledged_ids=("a" * 32,),
            operations=2,
        )
        state = pc.derive_subcell(cell, _evidence(launched), r1_passed=R1)
        assert state.status is pc.SubcellStatus.FAILED
        assert (
            "termination NOT confirmed" in state.reason and "1 stop(s) acknowledged" in state.reason
        )
        confirmed = pc.derive_subcell(
            cell, _evidence(launched, cleanups=(_cleanup_for(launched.record),)), r1_passed=R1
        )
        assert confirmed.status is pc.SubcellStatus.FAILED
        assert "termination confirmed by a later cleanup" in confirmed.reason
        unstopped = _cleanup_for(launched.record, tasks_stopped=False)
        state = pc.derive_subcell(cell, _evidence(launched, cleanups=(unstopped,)), r1_passed=R1)
        assert "termination NOT confirmed" in state.reason
        # An ambiguous launch (possibly started) is open until a task is discovered AND
        # confirmed STOPPED; an empty discovery settles nothing (finding 2).
        ambiguous = _bound(
            cell.subcell_id,
            stamp="20260914T190000Z-5555",
            observed=pc.ObservedClass.TIMEOUT,
            outcome=pc.SubcellOutcome.UNDECIDED,
            possibly_started=True,
        )
        assert pc.derive_subcell(cell, _evidence(ambiguous), r1_passed=R1).status is (
            pc.SubcellStatus.CLEANUP_UNRESOLVED
        )
        empty = _cleanup_for(ambiguous.record)
        state = pc.derive_subcell(cell, _evidence(ambiguous, cleanups=(empty,)), r1_passed=R1)
        assert state.status is pc.SubcellStatus.CLEANUP_UNRESOLVED
        assert "not proof of absence" in state.reason
        discovered = _cleanup_for(ambiguous.record, discovered=("b" * 32,))
        assert (
            pc.derive_subcell(
                cell, _evidence(ambiguous, cleanups=(discovered,)), r1_passed=R1
            ).status
            is pc.SubcellStatus.UNDECIDED
        )
        # A cleanup naming the attempt but another tag, or a stopped set that does not
        # cover every started task, settles nothing.
        assert launched.record.started_by is not None
        other_tag = pc.CleanupTasks(
            **{
                **{
                    f: getattr(_cleanup_for(launched.record).tasks[0], f)
                    for f in pc.CleanupTasks.__slots__
                    if f != "started_by"
                },
                "started_by": pc.started_by_of("20260914T170000Z-0000"),
            }
        )
        mismatched = pc.PermissionCleanup(
            **{
                **{
                    f: getattr(_cleanup_for(launched.record), f)
                    for f in pc.PermissionCleanup.__slots__
                    if f != "tasks"
                },
                "tasks": (other_tag,),
            }
        )
        state = pc.derive_subcell(cell, _evidence(launched, cleanups=(mismatched,)), r1_passed=R1)
        assert "termination NOT confirmed" in state.reason

    def test_r1_evidenced_and_blocked_subcells(self) -> None:
        own = pc.subcell("R6-BLD-RUN-OWN-REVISION")
        assert pc.derive_subcell(own, _evidence(), r1_passed=R1).status is (
            pc.SubcellStatus.AWAITING_R1
        )
        passed = pc.derive_subcell(own, _evidence(), r1_passed={**R1, ProductionActor.BUILD: True})
        assert passed.status is pc.SubcellStatus.PASSED
        # A task subcell with no record is UNEXECUTED (ADR-0048), never PASSED;
        # the deletion role's subcell is BLOCKED with its dependency.
        task = pc.derive_subcell(pc.subcell("R4-SECRET-GET-TASK"), _evidence(), r1_passed=R1)
        assert task.status is pc.SubcellStatus.UNEXECUTED
        blocked = pc.derive_subcell(pc.subcell("R8-GET"), _evidence(), r1_passed=R1)
        assert blocked.status is pc.SubcellStatus.BLOCKED and blocked.reason == (
            pc.DELETION_DEPENDENCY
        )


class TestMatrix:
    """The permission cells inside the verification matrix (ADR-0047)."""

    @staticmethod
    def _states(evidence: pc.PermissionEvidence, **r1: bool) -> dict[str, vc.CellState]:
        """The whole matrix with ``evidence`` and the R-1 bootstrap cells passed as asked."""
        from test_production_verification_cells import _Chain, _r3_record
        from test_production_verification_cells import _evidence as cells_evidence

        from fixtures.production_launch import ledger_row
        from fixtures.production_runtime import OTHER_RUN_ID, RUN_ID

        chains = {
            "build": _Chain(BLD),
            "acquisition": _Chain(ACQ, identity="verify-" + OTHER_RUN_ID),
        }
        passed = [c for name, c in chains.items() if r1.get(name, False)]
        record = _r3_record()
        inputs = chains["build"].evidence().inputs
        full = cells_evidence(
            rows=[ledger_row(RUN_ID), *[c.row for c in passed]],
            reservations={c.identity: c.reservation for c in passed},
            launch_records={c.identity: c.record for c in passed},
            r3_record=record,
            inputs=inputs,
        )
        full = vc.RecordedEvidence(
            **{f: getattr(full, f) for f in vc.RecordedEvidence.__slots__ if f != "permission"},
            permission=evidence,
        )
        prepared = {c.cell_id: c.prepared()[c.cell_id] for c in passed}
        return vc.derive_states(full, prepared)

    def test_r7_and_r9_pass_only_with_every_subcell_bound_under_the_binding(self) -> None:
        r7 = [_bound(s.subcell_id) for s in pc.subcells_of("R7-QUALIFICATION")]
        states = self._states(_evidence(*r7[:-1]))
        assert states["R7-QUALIFICATION"].status is vc.CellStatus.UNEXECUTED
        assert len(states["R7-QUALIFICATION"].subcells) == 12
        states = self._states(_evidence(*r7))
        assert states["R7-QUALIFICATION"].status is vc.CellStatus.PASSED
        assert states["R9-FOUNDATION-TASK"].status is vc.CellStatus.UNEXECUTED
        r9 = [_bound(s.subcell_id) for s in pc.subcells_of("R9-FOUNDATION-TASK")]
        states = self._states(_evidence(*r7, *r9))
        assert states["R9-FOUNDATION-TASK"].status is vc.CellStatus.PASSED
        # One stale record among bound ones: HISTORICAL, never PASSED.
        stale = [*r7[:-1], _bound(r7[-1].record.subcell_id, context=OTHER_CONTEXT)]
        states = self._states(_evidence(*stale))
        assert states["R7-QUALIFICATION"].status is vc.CellStatus.HISTORICAL
        assert vc.aggregate(states) is vc.AggregateStatus.INCOMPLETE
        # One record among bound chains that lacks its chain: UNBOUND, never PASSED.
        states = self._states(_evidence(*r7[:-1], r7[-1].record))
        assert states["R7-QUALIFICATION"].status is vc.CellStatus.UNBOUND

    def test_r4_stays_blocked_by_its_task_subcells_however_the_human_ones_read(self) -> None:
        # ADR-0048: R-4's task subcells are UNEXECUTED until their probe runs --
        # the cell never passes on its human half alone -- and R-8 stays BLOCKED.
        human = [
            _bound(s.subcell_id)
            for s in pc.subcells_of("R4-ACQUISITION")
            if s.layer is pc.Layer.L3_RUNTIME and not s.requires
        ]
        states = self._states(_evidence(*human))
        # The human creators' objects are unsettled (INCONCLUSIVE by precedence) and the
        # task subcells UNEXECUTED; neither reads PASSED.
        assert states["R4-ACQUISITION"].status is vc.CellStatus.INCONCLUSIVE
        assert states["R8-DELETION"].status is vc.CellStatus.BLOCKED
        assert pc.DELETION_DEPENDENCY in states["R8-DELETION"].reason
        lines = vc.matrix_lines(states)
        assert any(
            line.strip().startswith("subcell=R4-SECRET-GET-TASK status=UNEXECUTED")
            for line in lines
        )
        assert any(line.strip().startswith("subcell=R8-GET status=BLOCKED") for line in lines)

    def test_an_inverted_subcell_fails_its_cell_and_the_aggregate(self) -> None:
        r9 = pc.subcells_of("R9-FOUNDATION-TASK")
        inverted = _bound(
            r9[0].subcell_id,
            observed=pc.ObservedClass.OK_200,
            outcome=pc.SubcellOutcome.INVERTED,
            started_task_ids=("a" * 32,),
            stop_acknowledged_ids=("a" * 32,),
            operations=2,
        )
        states = self._states(_evidence(inverted, _bound(r9[1].subcell_id)))
        assert states["R9-FOUNDATION-TASK"].status is vc.CellStatus.FAILED
        assert "termination NOT confirmed" in states["R9-FOUNDATION-TASK"].reason
        assert vc.aggregate(states) is vc.AggregateStatus.FAILED

    def test_r6_positive_subcells_follow_the_r1_bootstrap_cells(self) -> None:
        negatives = [
            _bound(s.subcell_id)
            for s in pc.subcells_of("R6-LAUNCHERS")
            if s.layer is pc.Layer.L3_RUNTIME
        ]
        states = self._states(_evidence(*negatives))
        assert states["R6-LAUNCHERS"].status is vc.CellStatus.UNEXECUTED
        awaiting = [
            s for s in states["R6-LAUNCHERS"].subcells if s.status is pc.SubcellStatus.AWAITING_R1
        ]
        assert len(awaiting) == 6
        states = self._states(_evidence(*negatives), build=True, acquisition=True)
        assert states["R1-BLD-BOOTSTRAP"].status is vc.CellStatus.PASSED
        # The two ExecuteCommand subcells are executed against the actor's own held probe
        # task (ADR-0048): UNEXECUTED until then, so R-6 as a whole stays
        # UNEXECUTED however its other subcells read -- never PASSED on them alone.
        assert states["R6-LAUNCHERS"].status is vc.CellStatus.UNEXECUTED
        held = [
            s
            for s in states["R6-LAUNCHERS"].subcells
            if pc.subcell(s.subcell_id).layer is pc.Layer.L3_HELD_TASK
        ]
        assert len(held) == 2 and all(s.status is pc.SubcellStatus.UNEXECUTED for s in held)


# ---------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------


class _Tool:
    """The permission tool on the launch scenario's private root, every seam injected."""

    def __init__(
        self, tmp_path: Path, principal: pc.Principal = pc.Principal.ACQUISITION_HUMAN
    ) -> None:
        actor = pc.PRINCIPAL_ACTOR[principal] or ACQ
        self.scenario = _LaunchScenario(tmp_path, actor=actor, kind="verification")
        self.root = self.scenario.root
        self.declarations = tmp_path / "declarations"
        self.declarations.mkdir()
        (self.declarations / "production_iam.tf").write_text("synthetic", encoding="utf-8")
        (self.declarations / "storage.tf").write_text("synthetic storage", encoding="utf-8")
        self.targets = self.root / "permission-targets.json"
        self.targets.write_bytes(
            encode(
                {
                    "schema_version": 1,
                    "contract_id": pc.PERMISSION_TARGETS_CONTRACT_ID,
                    "foundation_task_role_arn": TARGETS.foundation_task_role_arn,
                    "qualification_secret_arn": TARGETS.qualification_secret_arn,
                    "control_bucket_name": CONTROL_BUCKET,
                }
            )
        )
        self.client = FakePermissionClient()
        self.client.records_dir = self.scenario.records
        self.constructions: list[tuple[str, str]] = []
        self.identity_calls: list[str] = []
        self.gate_calls: list[str] = []
        self.clock = FakeClock()
        profile = pc.PRINCIPAL_PROFILE[principal] or ""
        self.env = {
            "AWS_PROFILE": profile,
            rb.ENVIRONMENT_BINDING_ENV_VAR: str(self.root / "environment.json"),
            tool.TARGETS_ENV_VAR: str(self.targets),
            constants_for(ACQ).binding_env_var: str(self.root / "binding-acq.json"),
            constants_for(BLD).binding_env_var: str(self.root / "binding-bld.json"),
        }
        from fixtures.production_runtime import binding_document

        (self.root / "binding-acq.json").write_bytes(encode(binding_document(ACQ)))
        (self.root / "binding-bld.json").write_bytes(encode(binding_document(BLD)))

    def caller_identity(self, profile: str) -> object:
        self.identity_calls.append(profile)
        from fixtures.production_runtime import caller_identity

        for actor in (ACQ, BLD):
            constants = constants_for(actor)
            if profile == constants.profile:
                return caller_identity(human_identity_arn(actor))
            if profile == constants.launcher_profile:
                return caller_identity(launcher_identity_arn(actor))
        raise AssertionError("no identity for this profile")

    def factory(self, profile: str, region: str) -> Any:
        self.constructions.append((profile, region))
        return self.client

    def environment_binding(self, **_kw: Any) -> rb.QualificationEnvironmentBinding:
        return rb.QualificationEnvironmentBinding(
            target_account_id=ACCOUNT,
            licensed_bucket_name=BUCKET,
            partition=rb.EXPECTED_PARTITION,
            region=rb.EXPECTED_REGION,
            digest="ab" * 32,
        )

    def base(self) -> list[str]:
        return [
            "--ledger",
            str(self.scenario.ledger),
            "--launch-inputs",
            str(self.scenario.inputs),
            "--records-dir",
            str(self.scenario.records),
            "--acquisition-configuration",
            str(self.scenario.acquisition_configuration),
        ]

    def _gate(self, name: str) -> None:
        self.gate_calls.append(name)

    def fields(self, **overrides: Any) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "env": self.env,
            "modules": {},
            "now": self.clock.now,
            "client_factory": self.factory,
            "caller_identity": self.caller_identity,
            "foundation_gate": lambda: self._gate("foundation"),
            "qualification_gate": self._gate,
            "expected_account": lambda: ACCOUNT,
            "load_environment_binding": self.environment_binding,
            "read_private": lambda path: Path(path).read_bytes(),
            "root_source": lambda: self.root,
            "security_of": _security,
            "declaration_dir": self.declarations,
        }
        fields.update(overrides)
        return fields

    def main(self, *argv: str, **overrides: Any) -> int:
        code: int = tool.main(list(argv), **self.fields(**overrides))
        return code

    def files(self, prefix: str) -> list[Path]:
        return sorted(self.scenario.records.glob(f"{prefix}-*.json"))

    def prepare(self, subcell: str, **overrides: Any) -> str:
        """``--prepare-subcell``: the statement digest it printed."""
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = self.main("--prepare-subcell", subcell, *self.base(), **overrides)
        assert code == tool.EXIT_PREPARED, buffer.getvalue()
        return buffer.getvalue().split("statement_sha256=")[1].split()[0]

    def authorize(
        self,
        subcell: str,
        statement_sha256: str,
        *,
        name: str = "permission-authorization.json",
        hours: int = 2,
    ) -> Path:
        """The owner's authorization file for ``statement_sha256``, valid from now."""
        path = self.root / name
        now = self.clock.now()
        path.write_bytes(
            encode(
                {
                    "schema_version": 1,
                    "contract_id": pc.PERMISSION_AUTHORIZATION_CONTRACT_ID,
                    "subcell_id": subcell,
                    "statement_sha256": statement_sha256,
                    "issued_at": now.isoformat(),
                    "expires_at": (now + timedelta(hours=hours)).isoformat(),
                }
            )
        )
        return path

    def execute_argv(self, subcell: str, authorization: Path) -> list[str]:
        return [
            "--execute-subcell",
            subcell,
            *self.base(),
            "--authorization",
            str(authorization),
            tool.AUTHORIZATION_FLAG,
        ]

    def execute(self, subcell: str, answers: list[Any], **overrides: Any) -> int:
        """Prepare, authorize and execute ``subcell`` with the fake answering ``answers``."""
        authorization = self.authorize(subcell, self.prepare(subcell))
        self.client.answers = list(answers)
        return self.main(*self.execute_argv(subcell, authorization), **overrides)

    def control(self, tmp_path: Path) -> _Tool:
        """The control principal's tool over this scenario, for the cleanup."""
        control = _Tool(tmp_path / "control", pc.Principal.CONTROL)
        control.scenario = self.scenario
        control.root = self.root
        control.declarations = self.declarations
        control.client.records_dir = self.scenario.records
        control.env = {**self.env, "AWS_PROFILE": r3.CONTROL_PROFILE}
        return control

    def cleanup(self, control: _Tool, answers: list[Any]) -> int:
        control.client.answers = list(answers)
        return control.main("--cleanup", *self.base(), tool.CLEANUP_FLAG)

    def context(self) -> pc.PermissionContext:
        """The permission context the tool admits over this scenario, built its own way."""
        from kalpamani.data.production.sharadar.compiled import parse_compiled_configuration

        configuration, _digest = parse_compiled_configuration(
            self.scenario.acquisition_configuration.read_bytes()
        )
        registration = self.scenario.inputs.read_bytes()
        context: pc.PermissionContext = tool.permission_context(
            self.environment_binding(),
            registration_bytes=registration,
            inputs=parse_launch_inputs(registration),
            targets=pc.parse_permission_targets(self.targets.read_bytes()),
            production_secret=configuration.secret_identifier,
            directory=self.declarations,
        )
        return context

    def evidence(self) -> pc.PermissionEvidence:
        evidence: pc.PermissionEvidence = runner.permission_evidence(
            self.scenario.store(), self.context()
        )
        return evidence


def test_the_plan_prints_the_catalogue_and_constructs_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    t = _Tool(tmp_path)
    assert t.main() == tool.EXIT_PLANNED
    out = capsys.readouterr().out
    assert out.count("subcell=") == len(pc.SUBCELLS) and tool.SENTENCES["planned"] in out
    assert t.main("--cell", "R9-FOUNDATION-TASK") == tool.EXIT_PLANNED
    assert capsys.readouterr().out.count("subcell=") == 2
    assert t.main("--subcell", "R4-SECRET-GET-TASK") == tool.EXIT_PLANNED
    assert "layer=L3_TASK" in capsys.readouterr().out
    assert t.main("--subcell", "R8-GET") == tool.EXIT_PLANNED
    assert "blocked_on: " + pc.DELETION_DEPENDENCY[:40] in capsys.readouterr().out
    assert t.main("--cell", "R0") == tool.EXIT_REFUSED_ARGUMENTS
    assert t.constructions == [] and t.identity_calls == [] and t.client.calls == []
    for canary in CANARIES:
        assert canary not in out


@pytest.mark.parametrize("flag", sorted(tool.REFUSED_OPTIONS))
def test_refused_options_and_contradictory_arguments(tmp_path: Path, flag: str) -> None:
    t = _Tool(tmp_path)
    authorization = tmp_path / "auth.json"
    authorization.write_bytes(b"{}")
    assert t.main(flag) == tool.EXIT_REFUSED_ARGUMENTS
    assert t.main(tool.AUTHORIZATION_FLAG) == tool.EXIT_REFUSED_ARGUMENTS
    assert t.main("--execute-subcell", "R4-LIST-HUMAN", *t.base()) == tool.EXIT_REFUSED_ARGUMENTS
    # An execution without an authorization file is refused before anything else.
    assert t.main("--execute-subcell", "R4-LIST-HUMAN", *t.base(), tool.AUTHORIZATION_FLAG) == (
        tool.EXIT_REFUSED_ARGUMENTS
    )
    assert t.main("--execute-subcell", "R4-LIST-HUMAN", tool.AUTHORIZATION_FLAG) == (
        tool.EXIT_REFUSED_ARGUMENTS
    )
    assert (
        t.main(
            *t.execute_argv("R4-LIST-HUMAN", authorization),
            "--cleanup",
        )
        == tool.EXIT_REFUSED_ARGUMENTS
    )
    # Preparation takes no flag and no authorization.
    assert t.main("--prepare-subcell", "R4-LIST-HUMAN", *t.base(), tool.AUTHORIZATION_FLAG) == (
        tool.EXIT_REFUSED_ARGUMENTS
    )
    assert t.main(
        "--prepare-subcell", "R4-LIST-HUMAN", *t.base(), "--authorization", str(authorization)
    ) == (tool.EXIT_REFUSED_ARGUMENTS)
    assert t.constructions == [] and t.identity_calls == []


def test_execution_refuses_before_any_client_on_automation_profile_identity_and_layer(
    tmp_path: Path,
) -> None:
    t = _Tool(tmp_path)
    authorization = t.authorize("R4-LIST-HUMAN", t.prepare("R4-LIST-HUMAN"))
    execute = t.execute_argv("R4-LIST-HUMAN", authorization)
    assert t.main(*execute, modules={"pytest": object()}) == tool.EXIT_REFUSED_EXECUTION_CONTEXT
    assert t.main(*execute, env={**t.env, "AWS_PROFILE": "default"}) == tool.EXIT_REFUSED_IDENTITY
    assert t.main(*execute, env={**t.env, "AWS_PROFILE": constants_for(BLD).profile}) == (
        tool.EXIT_REFUSED_IDENTITY
    )
    assert t.identity_calls == []
    from fixtures.production_runtime import caller_identity

    assert (
        t.main(*execute, caller_identity=lambda _p: caller_identity(launcher_identity_arn(ACQ)))
        == tool.EXIT_REFUSED_IDENTITY
    )
    for blocked in ("R6-ACQ-RUN-OWN-REVISION", "R8-GET"):
        assert t.main(*t.execute_argv(blocked, authorization)) == tool.EXIT_REFUSED_SUBCELL
        assert t.main("--prepare-subcell", blocked, *t.base()) == tool.EXIT_REFUSED_SUBCELL
    assert t.main(*t.execute_argv("R4-NOTHING", authorization)) == tool.EXIT_REFUSED_SUBCELL
    # A probe-layer subcell (ADR-0048) on a registration with no probe target:
    # preparation refuses at the binding; execution proves both identities first and,
    # with no launch clients admitted, refuses at the identity -- no client, no record.
    for probe in ("R4-SECRET-GET-TASK", "R6-ACQ-EXECUTE-COMMAND"):
        assert t.main("--prepare-subcell", probe, *t.base()) == tool.EXIT_REFUSED_BINDING
        assert t.main(*t.execute_argv(probe, authorization)) == tool.EXIT_REFUSED_IDENTITY
    assert t.files("permission-attempt") == [] and t.files("launch-record") == []
    # A refused binding, targets file or declaration: still no client, no record.
    assert (
        t.main(*execute, load_environment_binding=lambda **_kw: None) == tool.EXIT_REFUSED_BINDING
    )
    assert t.main(*execute, env={**t.env, tool.TARGETS_ENV_VAR: str(tmp_path / "none")}) == (
        tool.EXIT_REFUSED_BINDING
    )
    assert t.main(*execute, declaration_dir=tmp_path / "missing") == tool.EXIT_REFUSED_DECLARATION
    assert t.constructions == [] and t.client.calls == []
    assert t.files("permission-attempt") == [] and t.files("permission-record") == []
    # Every refusal above happened before the authorization was consumed.
    assert not any(t.scenario.ledger.parent.glob("*.consumed/*"))


def test_one_subcell_executes_under_a_consumed_authorization_with_the_attempt_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    t = _Tool(tmp_path)
    digest = t.prepare("R4-LIST-HUMAN")
    capsys.readouterr()
    statement = pc.parse_permission_statement(t.files("permission-statement")[0].read_bytes())
    assert statement.digest == digest and statement.prerequisites == {}
    assert statement.targets_sha256 == pc.parse_permission_targets(t.targets.read_bytes()).digest
    assert t.constructions == [] and t.identity_calls == [] and t.client.calls == []
    authorization = t.authorize("R4-LIST-HUMAN", digest)
    t.client.answers = [DENIED]
    execute = t.execute_argv("R4-LIST-HUMAN", authorization)
    assert t.main(*execute) == tool.EXIT_EXECUTED
    out = capsys.readouterr().out
    assert "outcome=MATCHED" in out and tool.SENTENCES["executed"] in out
    assert t.identity_calls == [constants_for(ACQ).profile]
    assert t.constructions == [(constants_for(ACQ).profile, "us-east-1")]
    assert [c[0] for c in t.client.calls] == ["list_objects"]
    # The attempt record existed when the fake was called; the record followed it.
    assert t.client.attempt_files_seen == [1]
    assert len(t.files("permission-attempt")) == 1 and len(t.files("permission-record")) == 1
    record = pc.parse_permission_record(t.files("permission-record")[0].read_bytes())
    attempt = pc.parse_permission_attempt(t.files("permission-attempt")[0].read_bytes())
    assert record.outcome is pc.SubcellOutcome.MATCHED and attempt.stamp == record.stamp
    assert record.attempt_sha256 == attempt.digest and record.stamp == statement.stamp
    assert attempt.statement_sha256 == digest and record.binding == attempt.binding
    assert record.binding.registration_sha256 == sha256_hex(t.scenario.inputs.read_bytes())
    assert record.binding.policy_declaration_sha256 == pc.declaration_digest(
        tool.declaration_paths(t.declarations)
    )
    # The authorization is consumed beside the ledger, named by its own digest.
    parsed = pc.parse_permission_authorization(
        authorization.read_bytes(),
        subcell_id="R4-LIST-HUMAN",
        statement_sha256=digest,
        now=t.clock.now(),
    )
    store = t.scenario.store()
    assert record.authorization_sha256 == parsed.digest
    assert store.is_consumed(tool.CONSUMPTION_KIND, parsed.digest)
    assert store.consumed_path(tool.CONSUMPTION_KIND, parsed.digest).parent.parent == (
        t.scenario.ledger.parent
    )
    for canary in (*CANARIES, BUCKET):
        assert canary not in out
    # --check-record reads it back; a mangled file is refused.
    assert t.main("--check-record", str(t.files("permission-record")[0])) == tool.EXIT_CHECKED
    (tmp_path / "broken.json").write_bytes(b"{")
    assert t.main("--check-record", str(tmp_path / "broken.json")) == tool.EXIT_CHECK_REFUSED


def test_an_authorization_is_consumed_once_whatever_follows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PR #106 correction 1, finding 1: one execution per authorization, durably."""
    t = _Tool(tmp_path)
    digest = t.prepare("R4-LIST-HUMAN")
    authorization = t.authorize("R4-LIST-HUMAN", digest)
    t.client.answers = [DENIED]
    execute = t.execute_argv("R4-LIST-HUMAN", authorization)
    assert t.main(*execute) == tool.EXIT_EXECUTED
    # Repeated: refused, no identity call needed to say so, no operation.
    calls = len(t.client.calls)
    assert t.main(*execute) == tool.EXIT_REFUSED_AUTHORIZATION_CONSUMED
    assert len(t.client.calls) == calls and len(t.files("permission-attempt")) == 1
    # From another records directory holding a copy of the statement, the same ledger:
    # still consumed -- the consumption lives beside the ledger, not under the records.
    elsewhere = t.root / "elsewhere"
    elsewhere.mkdir()
    for path in t.files("permission-statement"):
        (elsewhere / path.name).write_bytes(path.read_bytes())
    argv = [a if a != str(t.scenario.records) else str(elsewhere) for a in execute]
    assert t.main(*argv) == tool.EXIT_REFUSED_AUTHORIZATION_CONSUMED
    assert len(t.client.calls) == calls and not list(elsewhere.glob("permission-attempt-*"))
    # After an interruption between consumption and the attempt: consumed stays consumed.
    second = t.authorize("R4-LIST-HUMAN", t.prepare("R4-LIST-HUMAN"), name="second.json")
    original = t.scenario.store().__class__.write_record

    def interrupted(self: Any, prefix: str, document: Any, *, at: Any) -> Any:
        if prefix == "permission-attempt":
            from kalpamani.data.production.sharadar.launch_store import StoreDefect, StoreError

            raise StoreError(StoreDefect.WRITE_FAILED)
        return original(self, prefix, document, at=at)

    import kalpamani.data.production.sharadar.launch_store as ls

    ls.LaunchStore.write_record = interrupted  # type: ignore[method-assign]
    try:
        assert t.main(*t.execute_argv("R4-LIST-HUMAN", second)) == tool.EXIT_REFUSED_RECORD_WRITE
    finally:
        ls.LaunchStore.write_record = original  # type: ignore[method-assign]
    assert len(t.client.calls) == calls
    assert t.main(*t.execute_argv("R4-LIST-HUMAN", second)) == (
        tool.EXIT_REFUSED_AUTHORIZATION_CONSUMED
    )
    # A new preparation and a new authorization execute again; the old one never does.
    third = t.authorize("R4-LIST-HUMAN", t.prepare("R4-LIST-HUMAN"), name="third.json")
    t.client.answers = [DENIED]
    assert t.main(*t.execute_argv("R4-LIST-HUMAN", third)) == tool.EXIT_EXECUTED
    assert t.main(*execute) == tool.EXIT_REFUSED_AUTHORIZATION_CONSUMED
    capsys.readouterr()


def test_an_authorization_binds_the_statement_and_changed_targets_invalidate_it(
    tmp_path: Path,
) -> None:
    """PR #106 correction 1, finding 1: the statement is recomputed at execution."""
    t = _Tool(tmp_path)
    digest = t.prepare("R4-PUT-CONTROL-HUMAN")
    # Another subcell's statement, a wrong digest, a stale or a future authorization refuse.
    other = t.authorize("R4-LIST-HUMAN", t.prepare("R4-LIST-HUMAN"), name="other.json")
    assert t.main(*t.execute_argv("R4-PUT-CONTROL-HUMAN", other)) == (
        tool.EXIT_REFUSED_AUTHORIZATION
    )
    wrong = t.authorize("R4-PUT-CONTROL-HUMAN", "ff" * 32, name="wrong.json")
    assert t.main(*t.execute_argv("R4-PUT-CONTROL-HUMAN", wrong)) == (tool.EXIT_REFUSED_PREPARATION)
    expired = t.authorize("R4-PUT-CONTROL-HUMAN", digest, name="expired.json", hours=1)
    t.clock.seconds += 2 * 3600
    assert t.main(*t.execute_argv("R4-PUT-CONTROL-HUMAN", expired)) == (
        tool.EXIT_REFUSED_AUTHORIZATION
    )
    assert t.client.calls == [] and not list(t.scenario.ledger.parent.glob("*.consumed/*"))
    # The private targets document changed after preparation: the statement no longer
    # recomputes, and the authorization for the old statement is refused unconsumed.
    good = t.authorize("R4-PUT-CONTROL-HUMAN", digest, name="good.json")
    t.targets.write_bytes(
        t.targets.read_bytes().replace(b"synthetic-control-bucket", b"another-control-bucket")
    )
    assert t.main(*t.execute_argv("R4-PUT-CONTROL-HUMAN", good)) == tool.EXIT_REFUSED_PREPARATION
    assert t.client.calls == [] and not list(t.scenario.ledger.parent.glob("*.consumed/*"))
    # Prepared again against the changed targets, a new authorization executes once.
    renewed = t.authorize(
        "R4-PUT-CONTROL-HUMAN", t.prepare("R4-PUT-CONTROL-HUMAN"), name="renewed.json"
    )
    t.client.answers = [DENIED]
    assert t.main(*t.execute_argv("R4-PUT-CONTROL-HUMAN", renewed)) == tool.EXIT_EXECUTED
    assert t.client.calls[0][1]["bucket"] == "another-control-bucket"


def test_a_dependent_subcell_reads_the_exact_object_and_the_cleanup_defers_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PR #106 correction 1, finding 2: prerequisites bound before, kept until, then removed."""
    t = _Tool(tmp_path, pc.Principal.BUILD_HUMAN)
    # The dependent cannot be prepared while its prerequisite object does not exist.
    assert t.main("--prepare-subcell", "R5-GET-PAYLOAD-HUMAN", *t.base()) == (
        tool.EXIT_REFUSED_PREREQUISITE
    )
    creator = _Tool(tmp_path / "creator", pc.Principal.ACQUISITION_HUMAN)
    creator.scenario, creator.root, creator.declarations = t.scenario, t.root, t.declarations
    creator.client.records_dir = t.scenario.records
    creator.env = {**t.env, "AWS_PROFILE": constants_for(ACQ).profile}
    assert creator.execute("R4-PUT-PAYLOAD-HUMAN", [OK]) == tool.EXIT_EXECUTED
    created = pc.parse_permission_record(creator.files("permission-record")[0].read_bytes())
    assert created.created_key is not None
    # Prepared now: the statement names the creating record by digest, and the target
    # the read will address is exactly the created object -- not a key of its own stamp.
    digest = t.prepare("R5-GET-PAYLOAD-HUMAN")
    statement = next(
        s
        for s in (
            pc.parse_permission_statement(f.read_bytes()) for f in t.files("permission-statement")
        )
        if s.subcell_id == "R5-GET-PAYLOAD-HUMAN"
    )
    assert statement.digest == digest
    assert statement.prerequisites == {"R4-PUT-PAYLOAD-HUMAN": created.digest}
    # The cleanup keeps the object while the prepared dependent has not run (deferred),
    # and reads nothing else as residue.
    control = t.control(tmp_path)
    assert t.cleanup(control, []) == tool.EXIT_EXECUTED
    assert "deferred=1 residue=0 operations=0" in capsys.readouterr().out
    assert control.client.calls == []
    authorization = t.authorize("R5-GET-PAYLOAD-HUMAN", digest)
    t.client.answers = [OK]
    assert t.main(*t.execute_argv("R5-GET-PAYLOAD-HUMAN", authorization)) == tool.EXIT_EXECUTED
    read = t.client.calls[-1]
    assert read[0] == "get_object" and read[1]["key"] == created.created_key
    assert read[1]["bucket"] == created.created_bucket
    record = next(
        r
        for r in (pc.parse_permission_record(f.read_bytes()) for f in t.files("permission-record"))
        if r.subcell_id == "R5-GET-PAYLOAD-HUMAN"
    )
    assert record.prerequisites == {"R4-PUT-PAYLOAD-HUMAN": created.digest}
    # Now the cleanup removes it, naming the creating attempt; both subcells then pass.
    assert t.cleanup(control, [NO_CONTENT, NOT_FOUND]) == tool.EXIT_EXECUTED
    out = capsys.readouterr().out
    assert "keys=1 confirmed=1" in out and "deferred=0 residue=0" in out
    cleanups = [pc.parse_permission_cleanup(f.read_bytes()) for f in t.files("permission-cleanup")]
    assert sorted(len(c.keys) for c in cleanups) == [0, 1]
    settled = next(c for c in cleanups if c.keys)
    assert settled.keys[0].attempt_sha256 == created.attempt_sha256 and settled.deferred == ()
    assert next(c for c in cleanups if not c.keys).deferred == (created.created_key,)
    evidence = t.evidence()
    for subcell in ("R4-PUT-PAYLOAD-HUMAN", "R5-GET-PAYLOAD-HUMAN"):
        assert pc.derive_subcell(pc.subcell(subcell), evidence, r1_passed=R1).status is (
            pc.SubcellStatus.PASSED
        ), subcell
    # An unverified copy of that cleanup record beside the verified one changes nothing;
    # with ONLY an unverified record (PR #106 correction 3), the object is not confirmed
    # removed: the creator stays CLEANUP_UNRESOLVED, the dependent can be prepared against
    # the object again, and the next verified pass settles it again rather than skipping it.
    settled_path = next(
        f for f in t.files("permission-cleanup") if pc.parse_permission_cleanup(f.read_bytes()).keys
    )
    original = settled_path.read_bytes()
    document = json.loads(original)
    document["identity_verified"] = False
    settled_path.write_bytes(encode(document))
    try:
        unverified_evidence = t.evidence()
        assert (
            pc.derive_subcell(
                pc.subcell("R4-PUT-PAYLOAD-HUMAN"), unverified_evidence, r1_passed=R1
            ).status
            is pc.SubcellStatus.CLEANUP_UNRESOLVED
        )
        assert t.main("--prepare-subcell", "R5-GET-PAYLOAD-HUMAN", *t.base()) == tool.EXIT_PREPARED
        control.client.by_operation = {"delete_object": [NO_CONTENT], "head_object": [NOT_FOUND]}
        assert t.cleanup(control, []) == tool.EXIT_EXECUTED
        assert "keys=0 confirmed=0" not in capsys.readouterr().out
    finally:
        settled_path.write_bytes(original)
    # Once removed (by a verified pass), the dependent cannot be prepared or executed
    # against it again.
    assert t.main("--prepare-subcell", "R5-GET-PAYLOAD-HUMAN", *t.base()) == (
        tool.EXIT_REFUSED_PREREQUISITE
    )
    again = t.authorize("R5-GET-PAYLOAD-HUMAN", digest, name="again.json")
    assert t.main(*t.execute_argv("R5-GET-PAYLOAD-HUMAN", again)) == (
        tool.EXIT_REFUSED_PREREQUISITE
    )


def test_an_inverted_or_undecided_subcell_is_recorded_and_exits_accordingly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    t = _Tool(tmp_path, pc.Principal.ACQUISITION_LAUNCHER)
    assert t.execute("R9-ACQ-OVERRIDE-FOUNDATION-ROLE", [LAUNCHED, OK]) == tool.EXIT_INVERTED
    out = capsys.readouterr().out
    assert (
        "tasks_started=1 stops_acknowledged=1 possibly_started=no termination_confirmed=no" in out
    )
    assert [c[0] for c in t.client.calls] == ["run_task", "stop_task"]
    run = t.client.calls[0][1]
    assert run["subnet_id"] == INPUTS.subnet_ids[ACQ] and run["assign_public_ip"] is True
    assert run["started_by"].startswith("kalpamani-permission-")
    assert t.identity_calls == [constants_for(ACQ).launcher_profile]
    assert t.execute("R9-ACQ-OVERRIDE-FOUNDATION-ROLE", [TIMEOUT]) == tool.EXIT_UNDECIDED
    out = capsys.readouterr().out
    assert "possibly_started=yes" in out and TASK_ARN not in out
    assert [c[0] for c in t.client.calls] == ["run_task", "stop_task", "run_task"]


def test_cleanup_settles_objects_ambiguous_writes_interrupted_attempts_and_tasks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PR #106 correction 1, findings 3 and 4, through the tool on real files."""
    t = _Tool(tmp_path)
    assert t.execute("R4-PUT-PAYLOAD-HUMAN", [OK]) == tool.EXIT_EXECUTED
    created = pc.parse_permission_record(t.files("permission-record")[0].read_bytes())
    assert created.subcell_id == "R4-PUT-PAYLOAD-HUMAN"
    # An ambiguous write: possibly committed, tracked for the cleanup by its attempt.
    assert t.execute("R4-PUT-INDEX-HUMAN", [TIMEOUT]) == tool.EXIT_UNDECIDED
    ambiguous = next(
        r
        for r in (pc.parse_permission_record(f.read_bytes()) for f in t.files("permission-record"))
        if r.subcell_id == "R4-PUT-INDEX-HUMAN"
    )
    assert ambiguous.possibly_created and ambiguous.created_key is None
    # An interrupted attempt (no record) for a creating subcell.
    cell = pc.subcell("R4-PUT-CLAIM-HUMAN")
    interrupted = pc.PermissionAttempt(
        subcell_id=cell.subcell_id,
        principal=cell.principal,
        stamp=created.stamp,
        authorization_sha256="ab" * 32,
        statement_sha256="cd" * 32,
        bucket=BUCKET,
        key=_resolve(cell).key,
        started_at=t.clock.now(),
        binding=created.binding,
    )
    t.scenario.store().write_record(
        "permission-attempt", interrupted.document(), at=interrupted.started_at
    )
    # An unexpected launch under the launcher, and an ambiguous one.
    launcher = _Tool(tmp_path / "launcher", pc.Principal.ACQUISITION_LAUNCHER)
    launcher.scenario, launcher.root, launcher.declarations = t.scenario, t.root, t.declarations
    launcher.client.records_dir = t.scenario.records
    launcher.env = {**t.env, "AWS_PROFILE": constants_for(ACQ).launcher_profile}
    assert launcher.execute("R6-ACQ-RUN-OTHER-REVISION", [LAUNCHED, OK]) == tool.EXIT_INVERTED
    assert launcher.execute("R6-ACQ-RUN-OTHER-FAMILY", [TIMEOUT]) == tool.EXIT_UNDECIDED
    capsys.readouterr()
    control = t.control(tmp_path)
    # Three objects (created, possibly created, interrupted), then two launches: the
    # recorded task listed by its tag (nothing new), described STOPPED; the ambiguous
    # launch listed by its tag, nothing found -- which settles NOTHING: an empty
    # discovery is not proof of absence, and the pass is UNRESOLVED.
    control.client.by_operation = {
        "delete_object": [NO_CONTENT] * 3,
        "head_object": [NOT_FOUND] * 3,
        "list_tasks": [LISTED_NONE] * 2,
        "describe_tasks": [STOPPED],
    }
    assert t.cleanup(control, []) == tool.EXIT_CLEANUP_UNRESOLVED
    out = capsys.readouterr().out
    assert "keys=3 confirmed=3 launches=2 tasks_known=1 tasks_stopped=1" in out
    assert "deferred=0 residue=1 operations=9" in out
    assert control.gate_calls == ["foundation"] and control.identity_calls == []
    assert control.constructions == [(r3.CONTROL_PROFILE, "us-east-1")]
    deleted = sorted(c[1]["key"] for c in control.client.calls if c[0] == "delete_object")
    assert created.created_key is not None and interrupted.key is not None
    assert created.created_key in deleted and interrupted.key in deleted and len(deleted) == 3
    # The possibly committed index key is the one the attempt named for that stamp.
    index_attempt = next(
        pc.parse_permission_attempt(p.read_bytes())
        for p in t.files("permission-attempt")
        if pc.parse_permission_attempt(p.read_bytes()).digest == ambiguous.attempt_sha256
    )
    assert index_attempt.key in deleted and index_attempt.key is not None
    assert index_attempt.key.startswith("bronze/sharadar/_indexes/")
    listed = [c[1]["started_by"] for c in control.client.calls if c[0] == "list_tasks"]
    assert len(listed) == 2 and all(s.startswith("kalpamani-permission-") for s in listed)
    assert all(
        set(c[1]) == {"cluster_arn", "started_by", "next_token"}
        for c in control.client.calls
        if c[0] == "list_tasks"
    )
    described = [c for c in control.client.calls if c[0] == "describe_tasks"]
    assert len(described) == 1 and described[0][1]["task_arns"] == (TASK_ARN,)
    cleanup = pc.parse_permission_cleanup(t.files("permission-cleanup")[-1].read_bytes())
    assert {k.attempt_sha256 for k in cleanup.keys} == {
        created.attempt_sha256,
        ambiguous.attempt_sha256,
        interrupted.digest,
    }
    # The matrix: the creator PASSED (created and confirmed removed by its own attempt's
    # entry); the ambiguous one stays UNDECIDED (its result is preserved, its object
    # settled); the launch FAILED with termination confirmed; the ambiguous launch stays
    # CLEANUP_UNRESOLVED -- nothing discovered, nothing settled.
    evidence = t.evidence()
    states = {
        s: pc.derive_subcell(pc.subcell(s), evidence, r1_passed=R1)
        for s in (
            "R4-PUT-PAYLOAD-HUMAN",
            "R4-PUT-INDEX-HUMAN",
            "R4-PUT-CLAIM-HUMAN",
            "R6-ACQ-RUN-OTHER-REVISION",
            "R6-ACQ-RUN-OTHER-FAMILY",
        )
    }
    assert states["R4-PUT-PAYLOAD-HUMAN"].status is pc.SubcellStatus.PASSED
    assert states["R4-PUT-INDEX-HUMAN"].status is pc.SubcellStatus.UNDECIDED
    assert states["R4-PUT-CLAIM-HUMAN"].status is pc.SubcellStatus.INTERRUPTED
    assert states["R6-ACQ-RUN-OTHER-REVISION"].status is pc.SubcellStatus.FAILED
    assert "termination confirmed" in states["R6-ACQ-RUN-OTHER-REVISION"].reason
    assert states["R6-ACQ-RUN-OTHER-FAMILY"].status is pc.SubcellStatus.CLEANUP_UNRESOLVED
    assert "not proof of absence" in states["R6-ACQ-RUN-OTHER-FAMILY"].reason
    # A second pass: the objects and the confirmed launch are settled by identity and
    # left alone; the ambiguous launch is discovered again -- this time the task is
    # visible under STOPPED (delayed visibility) and its termination is confirmed.
    control.client.by_operation = {
        "list_tasks": [LISTED_ONE],
        "describe_tasks": [STOPPED],
    }
    assert t.cleanup(control, []) == tool.EXIT_EXECUTED
    assert "keys=0 confirmed=0 launches=1 tasks_known=1 tasks_stopped=1" in capsys.readouterr().out
    evidence = t.evidence()
    assert pc.derive_subcell(
        pc.subcell("R6-ACQ-RUN-OTHER-FAMILY"), evidence, r1_passed=R1
    ).status is (pc.SubcellStatus.UNDECIDED)
    # A third pass has nothing left to settle.
    assert t.cleanup(control, []) == tool.EXIT_EXECUTED
    assert "keys=0 confirmed=0 launches=0" in capsys.readouterr().out
    # Residue: a delete refused and a task still RUNNING leave residue; the exit says so.
    assert t.execute("R4-PUT-RECORD-HUMAN", [OK]) == tool.EXIT_EXECUTED
    assert launcher.execute("R6-ACQ-RUN-OTHER-CLUSTER", [LAUNCHED, DENIED]) == tool.EXIT_INVERTED
    capsys.readouterr()
    control.client.by_operation = {
        "delete_object": [DENIED],
        "head_object": [OK],
        "list_tasks": [LISTED_NONE],
        "describe_tasks": [RUNNING],
        "stop_task": [OK],
    }
    assert t.cleanup(control, []) == tool.EXIT_CLEANUP_UNRESOLVED
    out = capsys.readouterr().out
    assert "residue=2" in out and "tasks_stopped=0" in out
    evidence = t.evidence()
    state = pc.derive_subcell(pc.subcell("R6-ACQ-RUN-OTHER-CLUSTER"), evidence, r1_passed=R1)
    assert state.status is pc.SubcellStatus.FAILED and "termination NOT confirmed" in state.reason
    assert pc.derive_subcell(pc.subcell("R4-PUT-RECORD-HUMAN"), evidence, r1_passed=R1).status is (
        pc.SubcellStatus.CLEANUP_UNRESOLVED
    )
    # The wrong flag for the mode, or the wrong profile: refused before any client.
    assert control.main("--cleanup", *t.base(), tool.AUTHORIZATION_FLAG) == (
        tool.EXIT_REFUSED_ARGUMENTS
    )
    assert t.main("--cleanup", *t.base(), tool.CLEANUP_FLAG) == tool.EXIT_REFUSED_IDENTITY


def test_the_matrix_passes_r7_only_through_complete_bound_chains(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PR #106 correction 2, finding 1, through the public runner on real files.

    Every R-7 subcell is prepared, authorized and executed by the tool (the fakes refusing
    each write and each parameter put), so the records directory holds the complete chain
    -- statement, consumed authorization beside the ledger, attempt, record -- and the
    cell runner reads R-7 PASSED. Then, one component at a time: missing, substituted or
    contradicting, the cell reads UNBOUND; a changed targets document reads HISTORICAL; a
    missing targets document (no current context) reads UNBOUND. Records alone never pass.
    """
    from test_production_verification_cells import _Cells

    cells = _Cells(tmp_path)
    scenario = cells.scenario
    scenario.records.mkdir(parents=True, exist_ok=True)
    tools: dict[pc.Principal, _Tool] = {}
    for principal in (
        pc.Principal.QUALIFICATION_ACQUISITION,
        pc.Principal.QUALIFICATION_ASSESSMENT,
    ):
        t = _Tool(tmp_path / principal.value.lower(), principal)
        t.scenario, t.root = scenario, scenario.root
        t.client.records_dir = scenario.records
        t.env[rb.ENVIRONMENT_BINDING_ENV_VAR] = str(scenario.root / "environment.json")
        tools[principal] = t
    first = next(iter(tools.values()))
    for t in tools.values():
        t.declarations = first.declarations
        t.targets = first.targets
        t.env[tool.TARGETS_ENV_VAR] = str(first.targets)
    for s in pc.subcells_of("R7-QUALIFICATION"):
        t = tools[s.principal]
        assert t.execute(s.subcell_id, [DENIED]) == tool.EXIT_EXECUTED, s.subcell_id
    capsys.readouterr()

    def context_source(_arguments: Any) -> pc.PermissionContext:
        return first.context()

    matrix = [*cells.base()]
    assert cells.main(*matrix, permission_context_source=context_source) == runner.EXIT_MATRIX
    out = capsys.readouterr().out
    assert "cell=R7-QUALIFICATION ref=R-7 kind=PERMISSION_MATRIX status=PASSED" in out
    assert "  subcell=R7-ACQ-PUT-SILVER status=PASSED" in out
    assert "cell=R4-ACQUISITION ref=R-4 kind=PERMISSION_MATRIX status=UNEXECUTED" in out
    assert "cell=R6-LAUNCHERS ref=R-6 kind=PERMISSION_MATRIX status=UNEXECUTED" in out
    assert "cell=R8-DELETION ref=R-8 kind=PERMISSION_MATRIX status=BLOCKED" in out
    assert scenario.clients.constructions == []
    for canary in (*CANARIES, BUCKET):
        assert canary not in out

    def status_of(**overrides: Any) -> str:
        code = cells.main(*matrix, permission_context_source=context_source, **overrides)
        assert code == runner.EXIT_MATRIX
        text = capsys.readouterr().out
        line = next(ln for ln in text.splitlines() if ln.startswith("cell=R7-QUALIFICATION "))
        return line.split("status=")[1].split()[0]

    store = scenario.store()
    statements = sorted(scenario.records.glob("permission-statement-*.json"))
    attempts = sorted(scenario.records.glob("permission-attempt-*.json"))
    consumed = sorted(store.consumed_path(tool.CONSUMPTION_KIND, "0" * 64).parent.glob("*.json"))
    assert len(statements) == 12 and len(attempts) == 12 and len(consumed) == 12

    def withheld(path: Path) -> None:
        aside = path.with_suffix(".aside")
        path.rename(aside)
        try:
            assert status_of() == "UNBOUND", path.name
        finally:
            aside.rename(path)

    # Missing: an attempt, a statement, a consumption -- each alone makes the cell UNBOUND.
    withheld(attempts[0])
    withheld(statements[0])
    withheld(consumed[0])
    assert status_of() == "PASSED"
    # Substituted: a statement of the same subcell for another stamp in place of the one
    # the attempt names; a consumption for another statement; a record whose
    # authorization digest is not its attempt's.
    original = statements[0].read_bytes()
    document = json.loads(original)
    document["stamp"] = "20260914T170000Z-0000"
    statements[0].write_bytes(encode(document))
    try:
        assert status_of() == "UNBOUND"
    finally:
        statements[0].write_bytes(original)
    original = consumed[0].read_bytes()
    document = json.loads(original)
    document["statement_sha256"] = "55" * 32
    consumed[0].write_bytes(encode(document))
    try:
        assert status_of() == "UNBOUND"
    finally:
        consumed[0].write_bytes(original)
    record_path = sorted(scenario.records.glob("permission-record-*.json"))[0]
    original = record_path.read_bytes()
    document = json.loads(original)
    document["authorization_sha256"] = "66" * 32
    record_path.write_bytes(encode(document))
    try:
        assert status_of() == "UNBOUND"
    finally:
        record_path.write_bytes(original)
    assert status_of() == "PASSED"
    # Changed targets: every chain was made under the old targets document -- HISTORICAL,
    # never PASSED; a missing targets document is no current context -- UNBOUND.
    original = first.targets.read_bytes()
    first.targets.write_bytes(
        original.replace(b"synthetic-control-bucket", b"another-control-bucket")
    )
    try:
        assert status_of() == "HISTORICAL"
    finally:
        first.targets.write_bytes(original)
    first.targets.rename(first.targets.with_suffix(".aside"))
    try:
        assert status_of() == "UNBOUND"
    finally:
        first.targets.with_suffix(".aside").rename(first.targets)
    assert status_of() == "PASSED"
    # A cleanup whose identity is not verified confirms nothing through the runner either
    # (PR #106 correction 3): the R-7 writes were refused, so no object is open there --
    # exercise the rule on an object the acquisition human is allowed to create.
    creator = _Tool(tmp_path / "creator", pc.Principal.ACQUISITION_HUMAN)
    creator.scenario, creator.root = scenario, scenario.root
    creator.client.records_dir = scenario.records
    creator.declarations, creator.targets = first.declarations, first.targets
    creator.env[rb.ENVIRONMENT_BINDING_ENV_VAR] = str(scenario.root / "environment.json")
    creator.env[tool.TARGETS_ENV_VAR] = str(first.targets)
    from fixtures.production_runtime import binding_document

    (scenario.root / "binding-acq.json").write_bytes(encode(binding_document(ACQ)))
    creator.env[constants_for(ACQ).binding_env_var] = str(scenario.root / "binding-acq.json")
    assert creator.execute("R4-PUT-PAYLOAD-HUMAN", [OK]) == tool.EXIT_EXECUTED
    capsys.readouterr()

    def subcell_status(subcell_id: str) -> str:
        code = cells.main(*matrix, permission_context_source=context_source)
        assert code == runner.EXIT_MATRIX
        text = capsys.readouterr().out
        line = next(
            ln for ln in text.splitlines() if ln.strip().startswith(f"subcell={subcell_id} ")
        )
        return line.split("status=")[1].split()[0]

    assert subcell_status("R4-PUT-PAYLOAD-HUMAN") == "CLEANUP_UNRESOLVED"
    control = creator.control(tmp_path)
    control.client.by_operation = {"delete_object": [NO_CONTENT], "head_object": [NOT_FOUND]}
    assert creator.cleanup(control, []) == tool.EXIT_EXECUTED
    capsys.readouterr()
    assert subcell_status("R4-PUT-PAYLOAD-HUMAN") == "PASSED"  # created, confirmed removed
    cleanup_path = next(
        f
        for f in sorted(scenario.records.glob("permission-cleanup-*.json"))
        if pc.parse_permission_cleanup(f.read_bytes()).keys
    )
    original = cleanup_path.read_bytes()
    document = json.loads(original)
    document["identity_verified"] = False
    cleanup_path.write_bytes(encode(document))
    try:
        assert subcell_status("R4-PUT-PAYLOAD-HUMAN") == "CLEANUP_UNRESOLVED"
    finally:
        cleanup_path.write_bytes(original)
    assert subcell_status("R4-PUT-PAYLOAD-HUMAN") == "PASSED"
    # Records alone -- the shape the earlier test supplied -- never pass.
    for path in [*statements, *attempts]:
        path.rename(path.with_suffix(".aside"))
    assert status_of() == "UNBOUND"
    # A malformed permission file makes every permission subcell UNBOUND, never ignored.
    (scenario.records / "permission-record-20260914T180000Z-ffff.json").write_bytes(b"{}")
    assert status_of() == "UNBOUND"


# ---------------------------------------------------------------------------
# The real SDK adapter, at the transport
# ---------------------------------------------------------------------------


class _CountingTransport:
    """Replaces botocore's HTTP session: every send is one transport attempt."""

    def __init__(self) -> None:
        self.sends = 0
        self.requests: list[Any] = []
        self.script: list[Any] = []

    def send(self, request: Any) -> Any:
        import io

        from botocore.awsrequest import AWSResponse  # type: ignore[import-untyped]

        self.sends += 1
        self.requests.append(request)
        answer = self.script.pop(0) if self.script else (200, b"")
        if isinstance(answer, BaseException):
            raise answer
        status, body = answer
        raw = io.BytesIO(body)
        raw.stream = lambda **_kw: iter([body])  # type: ignore[attr-defined]
        return AWSResponse(request.url, status, {"content-type": "application/json"}, raw)


def _synthetic_session(_profile: str, region: str) -> Any:
    import boto3  # type: ignore[import-untyped]

    return boto3.Session(
        aws_access_key_id="SYNTHETIC00000000000",
        aws_secret_access_key="synthetic-secret-key-never-a-credential",  # noqa: S106
        region_name=region,
    )


def _xml_error(code: str) -> bytes:
    return f"<Error><Code>{code}</Code><Message>synthetic</Message></Error>".encode()


class TestBoto3Adapter:
    def _adapter(self, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, _CountingTransport]:
        import boto3

        original = boto3.Session

        def refuse_profiles(*args: Any, **kwargs: Any) -> Any:
            if "profile_name" in kwargs:
                raise AssertionError("a test must never build a session from a profile")
            return original(*args, **kwargs)

        monkeypatch.setattr(boto3, "Session", refuse_profiles)
        adapter = tool._Boto3PermissionClient(
            "kalpamani-production-acquisition", "us-east-1", session_factory=_synthetic_session
        )
        transport = _CountingTransport()
        original_client = adapter._profile_client

        def client(service: str) -> Any:
            built = original_client(service)
            built._endpoint.http_session = transport
            return built

        adapter._client_for = client
        return adapter, transport

    def test_every_service_call_is_one_attempt_with_the_documented_parameters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter, transport = self._adapter(monkeypatch)
        transport.script = [(403, _xml_error("AccessDenied"))]
        observation = adapter.put_object(
            BUCKET, "silver/x", pc.SYNTHETIC_MARKER, if_none_match=True
        )
        assert r3.classify(observation) is r3.ObservedClass.DENIED_OTHER and transport.sends == 1
        headers = {k.lower(): v for k, v in transport.requests[-1].headers.items()}
        assert headers["if-none-match"] in ("*", b"*")
        transport.script = [(503, _xml_error("SlowDown"))]
        assert r3.classify(adapter.get_object(BUCKET, "silver/x")) is r3.ObservedClass.THROTTLED
        assert transport.sends == 2  # a retryable answer is NOT retried
        service_calls: tuple[Callable[[], Any], ...] = (
            lambda: adapter.list_objects(BUCKET),
            lambda: adapter.delete_object(BUCKET, "silver/x"),
            lambda: adapter.head_object(BUCKET, "silver/x"),
            lambda: adapter.get_secret_value(TARGETS.qualification_secret_arn),
            lambda: adapter.describe_secret(TARGETS.qualification_secret_arn),
            lambda: adapter.get_parameter("/kalpamani/production/x"),
            lambda: adapter.put_parameter("/kalpamani/production/x", "marker"),
            lambda: adapter.execute_command(cluster_arn=CLUSTER_ARN, task_arn=TASK_ARN),
            lambda: adapter.list_tasks(
                cluster_arn=CLUSTER_ARN, started_by="kalpamani-permission-x", next_token=None
            ),
            lambda: adapter.describe_tasks(cluster_arn=CLUSTER_ARN, task_arns=(TASK_ARN,)),
        )
        for service_call in service_calls:
            before = transport.sends
            transport.script = [(403, b'{"__type":"AccessDeniedException","message":"synthetic"}')]
            observation = service_call()
            assert transport.sends == before + 1
            assert r3.classify(observation) in (
                r3.ObservedClass.DENIED_OTHER,
                r3.ObservedClass.AMBIGUOUS,
            )
        for service in ("s3", "secretsmanager", "ssm", "ecs"):
            client = adapter._clients[service]
            assert client.meta.config.retries["total_max_attempts"] == 1

    #: ListTasks request members that are filters: startedBy must be the only one used.
    LIST_TASKS_OTHER_FILTERS: Final[frozenset[str]] = frozenset(
        {"desiredStatus", "family", "serviceName", "launchType", "containerInstance"}
    )

    def _assert_list_tasks_contract(self, request: Any, *, next_token: str | None) -> None:
        """The documented, compatible ListTasks request: the tag as the ONLY filter."""
        assert request.headers["X-Amz-Target"] == b"AmazonEC2ContainerServiceV20141113.ListTasks"
        body = json.loads(request.body)
        assert body["cluster"] == CLUSTER_ARN and body["startedBy"].startswith(
            "kalpamani-permission-"
        )
        assert body["maxResults"] == pc.MAX_RETURNED_TASKS
        assert not (set(body) & self.LIST_TASKS_OTHER_FILTERS), sorted(body)
        expected = {"cluster", "startedBy", "maxResults"} | ({"nextToken"} if next_token else set())
        assert set(body) == expected, sorted(body)
        if next_token is not None:
            assert body["nextToken"] == next_token

    def _run_task(self, adapter: Any, *, task_role_arn: str | None = None) -> Any:
        return adapter.run_task(
            cluster_arn=CLUSTER_ARN,
            task_definition_arn=verification_revision_arn(ACQ),
            task_role_arn=task_role_arn,
            started_by="kalpamani-permission-20260914T180000Z-abcd",
            subnet_id=INPUTS.subnet_ids[ACQ],
            security_group_ids=tuple(INPUTS.security_group_ids[ACQ]),
            assign_public_ip=True,
            platform_version=INPUTS.platform_version,
        )

    def test_run_task_answers_carry_every_task_and_the_request_carries_its_placement(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PR #106 correction 1, finding 4: at the real adapter, at the transport."""
        adapter, transport = self._adapter(monkeypatch)
        transport.script = [
            (200, json.dumps({"tasks": [{"taskArn": TASK_ARN}], "failures": []}).encode())
        ]
        launched = self._run_task(adapter, task_role_arn=TARGETS.foundation_task_role_arn)
        assert launched.task_arns == (TASK_ARN,) and r3.classify(launched) is (
            r3.ObservedClass.OK_200
        )
        body = json.loads(transport.requests[-1].body)
        assert body["overrides"] == {"taskRoleArn": TARGETS.foundation_task_role_arn}
        assert body["count"] == 1 and body["launchType"] == "FARGATE"
        assert body["platformVersion"] == INPUTS.platform_version
        assert body["networkConfiguration"] == {
            "awsvpcConfiguration": {
                "subnets": [INPUTS.subnet_ids[ACQ]],
                "securityGroups": list(INPUTS.security_group_ids[ACQ]),
                "assignPublicIp": "ENABLED",
            }
        }
        assert body["startedBy"] == "kalpamani-permission-20260914T180000Z-abcd"
        assert body["enableExecuteCommand"] is False
        # A task beside a failure entry is still a task: the ARN is preserved.
        other = TASK_ARN[:-1] + "b"
        transport.script = [
            (
                200,
                json.dumps(
                    {
                        "tasks": [{"taskArn": TASK_ARN}, {"taskArn": other}],
                        "failures": [{"arn": other, "reason": "RESOURCE:MEMORY"}],
                    }
                ).encode(),
            )
        ]
        mixed = self._run_task(adapter)
        assert mixed.task_arns == (TASK_ARN, other) and mixed.failures == 1
        assert r3.classify(mixed) is r3.ObservedClass.OK_200
        assert "overrides" not in json.loads(transport.requests[-1].body)
        # Only failure entries: no task named, an ambiguous launch (never a denial).
        transport.script = [
            (200, json.dumps({"tasks": [], "failures": [{"reason": "synthetic"}]}).encode())
        ]
        failed = self._run_task(adapter)
        assert failed.task_arns == () and r3.classify(failed) is r3.ObservedClass.AMBIGUOUS
        assert failed.failures == 1
        transport.script = [(200, json.dumps({"task": {"taskArn": TASK_ARN}}).encode())]
        assert r3.classify(adapter.stop_task(cluster_arn=CLUSTER_ARN, task_arn=TASK_ARN)) is (
            r3.ObservedClass.OK_200
        )
        # ListTasks by the tag and by NOTHING else (PR #106 correction 3: the contract makes
        # startedBy the only filter when it is used), page by page; DescribeTasks carries
        # the documented fields. An empty page settles nothing (the engine decides that); a
        # page with a token is reported through next_token.
        transport.script = [(200, json.dumps({"taskArns": []}).encode())]
        empty = adapter.list_tasks(
            cluster_arn=CLUSTER_ARN, started_by="kalpamani-permission-x", next_token=None
        )
        assert empty.task_arns == () and empty.next_token is None
        self._assert_list_tasks_contract(transport.requests[-1], next_token=None)
        transport.script = [
            (200, json.dumps({"taskArns": [TASK_ARN], "nextToken": "page-2"}).encode())
        ]
        listed = adapter.list_tasks(
            cluster_arn=CLUSTER_ARN,
            started_by="kalpamani-permission-x",
            next_token="page-1",  # noqa: S106 - a page token
        )
        assert listed.task_arns == (TASK_ARN,)
        assert listed.next_token == "page-2"  # noqa: S105 - a page token
        self._assert_list_tasks_contract(transport.requests[-1], next_token="page-1")  # noqa: S106
        transport.script = [
            (200, json.dumps({"tasks": [{"taskArn": TASK_ARN, "lastStatus": "STOPPED"}]}).encode())
        ]
        described = adapter.describe_tasks(cluster_arn=CLUSTER_ARN, task_arns=(TASK_ARN,))
        assert described.task_statuses == ((TASK_ARN, "STOPPED"),)
        assert json.loads(transport.requests[-1].body)["tasks"] == [TASK_ARN]
        assert transport.sends == 7  # one attempt per operation, no retry anywhere

    def test_an_ambiguous_launch_is_settled_at_the_adapter_only_by_a_discovered_stopped_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PR #106 correction 2, finding 2, with the real adapter at the transport."""
        adapter, transport = self._adapter(monkeypatch)
        launch = pc.TasksToSettle(
            attempt_sha256="e5" * 32,
            started_by="kalpamani-permission-20260914T180000Z-abcd",
            cluster_arn=CLUSTER_ARN,
            known_task_ids=(),
        )

        def settle() -> Any:
            return pc.run_cleanup(
                (),
                (launch,),
                client=adapter,
                stamp=STAMP,
                deferred=(),
                binding=BINDING,
                identity_verified=True,
                now=NOW,
                budget=60,
            )

        empty = (200, json.dumps({"taskArns": []}).encode())
        # Persistent empty discovery: one listing by the tag alone, nothing settled.
        transport.script = [empty]
        cleanup = settle()
        assert (
            transport.sends == 1 and cleanup.tasks[0].undiscovered and not cleanup.tasks[0].settled
        )
        assert cleanup.residue == (f"launch:{launch.started_by}:undiscovered",)
        self._assert_list_tasks_contract(transport.requests[-1], next_token=None)
        # Empty, then visible on a later pass (ECS still returning the task by its tag);
        # described STOPPED: settled by that evidence.
        transport.script = [
            (200, json.dumps({"taskArns": [TASK_ARN]}).encode()),
            (200, json.dumps({"tasks": [{"taskArn": TASK_ARN, "lastStatus": "STOPPED"}]}).encode()),
        ]
        cleanup = settle()
        assert cleanup.tasks[0].task_ids == ("a" * 32,) and cleanup.tasks[0].settled
        assert cleanup.settles_tasks("e5" * 32, ()) and transport.sends == 3
        self._assert_list_tasks_contract(transport.requests[-2], next_token=None)
        # A paginated discovery follows the token, still with the tag as the only filter;
        # a token remaining beyond the bound is an incomplete discovery.
        paged = (200, json.dumps({"taskArns": [], "nextToken": "t1"}).encode())
        transport.script = [paged, paged, paged]
        cleanup = settle()
        assert cleanup.tasks[0].discovery_incomplete and not cleanup.tasks[0].settled
        assert transport.sends == 6
        self._assert_list_tasks_contract(transport.requests[-1], next_token="t1")  # noqa: S106
        # Discovery refused: failed, residue, nothing described, nothing settled.
        transport.script = [(403, b'{"__type":"AccessDeniedException","message":"synthetic"}')]
        cleanup = settle()
        assert cleanup.tasks[0].discovery_failed and transport.sends == 7
        assert cleanup.residue == (f"launch:{launch.started_by}:failed",)
        # Discovered but still RUNNING: stopped once, residue -- a stop is not a termination.
        transport.script = [
            (200, json.dumps({"taskArns": [TASK_ARN]}).encode()),
            (200, json.dumps({"tasks": [{"taskArn": TASK_ARN, "lastStatus": "RUNNING"}]}).encode()),
            (200, json.dumps({"task": {"taskArn": TASK_ARN}}).encode()),
        ]
        cleanup = settle()
        assert cleanup.tasks[0].residue_ids == ("a" * 32,) and not cleanup.tasks[0].settled
        assert cleanup.residue == ("task:" + "a" * 32,) and transport.sends == 10
        # Every ListTasks the cleanup sent used the tag as its only filter, and no RunTask
        # was ever sent by the cleanup.
        for request in transport.requests:
            target = request.headers.get("X-Amz-Target") or b""
            assert b"RunTask" not in target
            if target == b"AmazonEC2ContainerServiceV20141113.ListTasks":
                body = json.loads(request.body)
                assert not (set(body) & self.LIST_TASKS_OTHER_FILTERS), sorted(body)
        from botocore.exceptions import ReadTimeoutError  # type: ignore[import-untyped]

        transport.script = [ReadTimeoutError(endpoint_url="https://synthetic")]
        assert r3.classify(adapter.list_objects(BUCKET)) is r3.ObservedClass.TIMEOUT
