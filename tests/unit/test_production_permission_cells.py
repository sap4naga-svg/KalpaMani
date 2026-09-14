"""The R-4 .. R-9 permission subcells (proposed ADR-0047), on fakes and synthetic records only.

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
from datetime import timedelta
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
    partition="aws",
    region="us-east-1",
)
OTHER_BINDING: Final = pc.PermissionBinding(
    environment_binding_sha256="ab" * 32,
    policy_declaration_sha256="99" * 32,
    registration_sha256="ef" * 32,
    partition="aws",
    region="us-east-1",
)
INPUTS: Final = parse_launch_inputs(encode(launch_inputs_document()))
SECRET_NAME: Final = "synthetic/production/sharadar"  # noqa: S105 - a name, not a value
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
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.attempt_files_seen: list[int] = []
        self.records_dir: Path | None = None

    def _next(self, operation: str, /, **kwargs: Any) -> r3.Observation:
        self.calls.append((operation, kwargs))
        if self.records_dir is not None:
            self.attempt_files_seen.append(len(list(self.records_dir.glob("permission-attempt-*"))))
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

    def run_task(
        self, *, cluster_arn: str, task_definition_arn: str, task_role_arn: str | None
    ) -> Any:
        return self._next(
            "run_task",
            cluster_arn=cluster_arn,
            task_definition_arn=task_definition_arn,
            task_role_arn=task_role_arn,
        )

    def stop_task(self, *, cluster_arn: str, task_arn: str) -> Any:
        return self._next("stop_task", cluster_arn=cluster_arn, task_arn=task_arn)

    def execute_command(self, *, cluster_arn: str, task_arn: str) -> Any:
        return self._next("execute_command", cluster_arn=cluster_arn, task_arn=task_arn)


OK = r3.Observation(status=200)
NO_CONTENT = r3.Observation(status=204)
NOT_FOUND = r3.Observation(status=404, code="404")
DENIED = r3.Observation(status=403, code="AccessDenied", message="denied")
TIMEOUT = r3.Observation(status=None, transport_failure="timeout")
LAUNCHED = r3.Observation(status=200, task_arn=TASK_ARN)


def _record(cell_id: str, **fields: Any) -> pc.PermissionRecord:
    """A MATCHED record for ``cell_id`` under BINDING, fields overridable."""
    cell = pc.subcell(cell_id)
    matched = (
        pc.ObservedClass.DENIED_OTHER
        if cell.expectation is pc.Expectation.DENIED
        else pc._SUCCESS_CLASS[cell.operation]
    )
    base: dict[str, Any] = {
        "subcell_id": cell.subcell_id,
        "cell_id": cell.cell_id,
        "principal": cell.principal,
        "operation": cell.operation,
        "target": cell.target,
        "expectation": cell.expectation,
        "stamp": STAMP,
        "observed": matched,
        "outcome": pc.SubcellOutcome.MATCHED,
        "created_key": None,
        "started_task_id": None,
        "stop_acknowledged": None,
        "operations": 1,
        "identity_verified": True,
        "started_at": NOW,
        "finished_at": NOW + timedelta(seconds=1),
        "binding": BINDING,
    }
    base.update(fields)
    return pc.PermissionRecord(**base)


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
        for s in pc.SUBCELLS:
            if s.principal in (pc.Principal.ACQUISITION_TASK, pc.Principal.BUILD_TASK):
                assert s.layer is pc.Layer.BLOCKED and s.blocked_on == pc.TASK_PROBE_DEPENDENCY
                assert pc.PRINCIPAL_PROFILE[s.principal] is None
                # The same operation exists under the human role as its own subcell, never
                # as evidence for the task role.
                twin = pc.subcell(s.subcell_id.replace("-TASK", "-HUMAN"))
                assert twin.principal in (pc.Principal.ACQUISITION_HUMAN, pc.Principal.BUILD_HUMAN)
            elif s.principal is pc.Principal.DELETION_ROLE:
                assert s.layer is pc.Layer.BLOCKED and s.blocked_on == pc.DELETION_DEPENDENCY
            else:
                assert s.layer is not pc.Layer.BLOCKED and s.blocked_on is None
        assert sum(1 for s in pc.SUBCELLS if s.layer is pc.Layer.BLOCKED) == 34
        assert sum(1 for s in pc.SUBCELLS if s.layer is pc.Layer.L3_RUNTIME) == 58

    def test_the_launchers_positive_operations_are_evidenced_by_r1_only(self) -> None:
        by_r1 = [s for s in pc.SUBCELLS if s.layer is pc.Layer.L3_BY_R1]
        assert len(by_r1) == 6 and all(s.cell_id == "R6-LAUNCHERS" for s in by_r1)
        assert all(s.expectation is pc.Expectation.ALLOWED for s in by_r1)
        with pytest.raises(ValueError):
            pc.run_subcell(
                by_r1[0],
                target=_resolve(by_r1[0]),
                client=FakePermissionClient(),
                stamp=STAMP,
                binding=BINDING,
                identity_verified=True,
                now=NOW,
                started_at=NOW,
            )

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
        record = pc.run_subcell(
            cell,
            target=_resolve(cell),
            client=client,
            stamp=STAMP,
            binding=BINDING,
            identity_verified=True,
            now=NOW + timedelta(seconds=2),
            started_at=NOW,
        )
        assert record.outcome is pc.SubcellOutcome.MATCHED and record.operations == 1
        assert record.created_key == _resolve(cell).key and record.started_task_id is None
        assert [c[0] for c in client.calls] == ["put_object"]
        assert client.calls[0][1]["if_none_match"] is True
        assert pc.parse_permission_record(canonical_bytes(record.document())) == record

    def test_a_refused_put_creates_nothing_and_an_allowed_put_refused_is_inverted(self) -> None:
        cell = pc.subcell("R4-PUT-SILVER-HUMAN")  # DENIED, creates
        record = pc.run_subcell(
            cell,
            target=_resolve(cell),
            client=FakePermissionClient(DENIED),
            stamp=STAMP,
            binding=BINDING,
            identity_verified=True,
            now=NOW,
            started_at=NOW,
        )
        assert record.outcome is pc.SubcellOutcome.MATCHED and record.created_key is None
        inverted = pc.run_subcell(
            cell,
            target=_resolve(cell),
            client=FakePermissionClient(OK),
            stamp=STAMP,
            binding=BINDING,
            identity_verified=True,
            now=NOW,
            started_at=NOW,
        )
        # An unexpected success is an inversion AND an object: the key is recorded for cleanup.
        assert inverted.outcome is pc.SubcellOutcome.INVERTED
        assert inverted.created_key == _resolve(cell).key
        allowed = pc.subcell("R4-PUT-PAYLOAD-HUMAN")
        refused = pc.run_subcell(
            allowed,
            target=_resolve(allowed),
            client=FakePermissionClient(DENIED),
            stamp=STAMP,
            binding=BINDING,
            identity_verified=True,
            now=NOW,
            started_at=NOW,
        )
        assert refused.outcome is pc.SubcellOutcome.INVERTED and refused.created_key is None

    def test_an_unexpected_launch_is_stopped_at_once_and_recorded(self) -> None:
        cell = pc.subcell("R9-ACQ-OVERRIDE-FOUNDATION-ROLE")
        client = FakePermissionClient(LAUNCHED, OK)
        record = pc.run_subcell(
            cell,
            target=_resolve(cell),
            client=client,
            stamp=STAMP,
            binding=BINDING,
            identity_verified=True,
            now=NOW,
            started_at=NOW,
        )
        assert record.outcome is pc.SubcellOutcome.INVERTED and record.operations == 2
        assert record.started_task_id == "a" * 32 and record.stop_acknowledged is True
        assert [c[0] for c in client.calls] == ["run_task", "stop_task"]
        assert client.calls[0][1]["task_role_arn"] == TARGETS.foundation_task_role_arn
        assert client.calls[1][1]["task_arn"] == TASK_ARN
        # A stop that is refused is recorded as not acknowledged; still INVERTED.
        client = FakePermissionClient(LAUNCHED, DENIED)
        record = pc.run_subcell(
            cell,
            target=_resolve(cell),
            client=client,
            stamp=STAMP,
            binding=BINDING,
            identity_verified=True,
            now=NOW,
            started_at=NOW,
        )
        assert record.stop_acknowledged is False and record.outcome is pc.SubcellOutcome.INVERTED
        assert pc.parse_permission_record(canonical_bytes(record.document())) == record
        # The expected refusal: one operation, no task, MATCHED.
        client = FakePermissionClient(DENIED)
        record = pc.run_subcell(
            cell,
            target=_resolve(cell),
            client=client,
            stamp=STAMP,
            binding=BINDING,
            identity_verified=True,
            now=NOW,
            started_at=NOW,
        )
        assert record.outcome is pc.SubcellOutcome.MATCHED and len(client.calls) == 1
        assert record.digest and TASK_ARN not in json.dumps(record.document())

    def test_a_transport_failure_decides_nothing(self) -> None:
        cell = pc.subcell("R5-LIST-HUMAN")
        record = pc.run_subcell(
            cell,
            target=_resolve(cell),
            client=FakePermissionClient(TIMEOUT),
            stamp=STAMP,
            binding=BINDING,
            identity_verified=True,
            now=NOW,
            started_at=NOW,
        )
        assert record.outcome is pc.SubcellOutcome.UNDECIDED
        assert record.observed is pc.ObservedClass.TIMEOUT

    def test_the_record_contract_refuses_contradictions(self) -> None:
        record = _record("R4-LIST-HUMAN")
        document = record.document()
        assert pc.parse_permission_record(canonical_bytes(document)) == record
        contradictions: tuple[tuple[Callable[[dict[str, Any]], object], str], ...] = (
            (lambda d: d.__setitem__("outcome", "INVERTED"), "outcome contradicts the class"),
            (lambda d: d.__setitem__("operation", "S3_GET"), "contradicts the subcell definition"),
            (lambda d: d.__setitem__("created_key", "silver/x"), "created key without a success"),
            (lambda d: d.__setitem__("operations", 3), "budget"),
            (lambda d: d.__setitem__("started_task_id", "a" * 32), "task id without a stop flag"),
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
        keys = ((BUCKET, "silver/a"), (BUCKET, "gold/b"), (CONTROL_BUCKET, "_verification/c"))
        client = FakePermissionClient(NO_CONTENT, NOT_FOUND, NO_CONTENT, OK, DENIED, NOT_FOUND)
        cleanup = pc.run_cleanup(
            keys,
            client=client,
            stamp=STAMP,
            binding=BINDING,
            identity_verified=True,
            now=NOW,
            budget=6,
        )
        assert cleanup.confirmed_keys == {"silver/a", "_verification/c"}
        assert cleanup.residue == ("gold/b",) and cleanup.operations == 6
        assert not cleanup.budget_exhausted
        assert client.calls[4][1]["bucket"] == CONTROL_BUCKET
        assert pc.parse_permission_cleanup(canonical_bytes(cleanup.document())) == cleanup
        # The budget is never exceeded: keys beyond it are residue, untouched.
        client = FakePermissionClient(NO_CONTENT, NOT_FOUND)
        exhausted = pc.run_cleanup(
            keys,
            client=client,
            stamp=STAMP,
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


# ---------------------------------------------------------------------------
# Deriving subcells and cells
# ---------------------------------------------------------------------------


def _evidence(
    *records: pc.PermissionRecord,
    attempts: tuple[pc.PermissionAttempt, ...] = (),
    cleanups: tuple[pc.PermissionCleanup, ...] = (),
    binding: pc.PermissionBinding | None = BINDING,
    malformed: int = 0,
) -> pc.PermissionEvidence:
    grouped: dict[str, list[pc.PermissionRecord]] = {}
    for r in records:
        grouped.setdefault(r.subcell_id, []).append(r)
    grouped_attempts: dict[str, list[pc.PermissionAttempt]] = {}
    for a in attempts:
        grouped_attempts.setdefault(a.subcell_id, []).append(a)
    return pc.PermissionEvidence(
        records={k: tuple(v) for k, v in grouped.items()},
        attempts={k: tuple(v) for k, v in grouped_attempts.items()},
        cleanups=cleanups,
        malformed=malformed,
        binding=binding,
    )


R1: Final = {ProductionActor.ACQUISITION: False, ProductionActor.BUILD: False}


class TestDerivation:
    def test_a_matched_record_under_the_current_binding_passes(self) -> None:
        cell = pc.subcell("R4-LIST-HUMAN")
        state = pc.derive_subcell(cell, _evidence(_record(cell.subcell_id)), r1_passed=R1)
        assert state.status is pc.SubcellStatus.PASSED
        assert pc.derive_subcell(cell, _evidence(), r1_passed=R1).status is (
            pc.SubcellStatus.UNEXECUTED
        )

    def test_an_inversion_never_disappears_under_the_same_binding(self) -> None:
        cell = pc.subcell("R4-LIST-HUMAN")
        inverted = _record(
            cell.subcell_id, observed=pc.ObservedClass.OK_200, outcome=pc.SubcellOutcome.INVERTED
        )
        later = _record(
            cell.subcell_id,
            started_at=NOW + timedelta(hours=1),
            finished_at=NOW + timedelta(hours=1),
        )
        state = pc.derive_subcell(cell, _evidence(inverted, later), r1_passed=R1)
        assert state.status is pc.SubcellStatus.FAILED and "OK_200" in state.reason
        # Under a new binding (a corrected declaration) the inversion is historical and the
        # matched record under the new binding decides.
        renewed = _record(cell.subcell_id, binding=OTHER_BINDING)
        state = pc.derive_subcell(
            cell, _evidence(inverted, renewed, binding=OTHER_BINDING), r1_passed=R1
        )
        assert state.status is pc.SubcellStatus.PASSED

    def test_other_binding_undecided_interrupted_and_unverified_identity(self) -> None:
        cell = pc.subcell("R4-LIST-HUMAN")
        stale = pc.derive_subcell(
            cell, _evidence(_record(cell.subcell_id, binding=OTHER_BINDING)), r1_passed=R1
        )
        assert stale.status is pc.SubcellStatus.HISTORICAL
        undecided = _record(
            cell.subcell_id, observed=pc.ObservedClass.TIMEOUT, outcome=pc.SubcellOutcome.UNDECIDED
        )
        assert pc.derive_subcell(cell, _evidence(undecided), r1_passed=R1).status is (
            pc.SubcellStatus.UNDECIDED
        )
        attempt = pc.PermissionAttempt(
            subcell_id=cell.subcell_id,
            principal=cell.principal,
            stamp=STAMP,
            key=None,
            started_at=NOW + timedelta(hours=2),
            binding=BINDING,
        )
        state = pc.derive_subcell(
            cell, _evidence(_record(cell.subcell_id), attempts=(attempt,)), r1_passed=R1
        )
        assert state.status is pc.SubcellStatus.INTERRUPTED
        assert pc.derive_subcell(cell, _evidence(attempts=(attempt,)), r1_passed=R1).status is (
            pc.SubcellStatus.INTERRUPTED
        )
        unverified = _record(cell.subcell_id, identity_verified=False)
        assert pc.derive_subcell(cell, _evidence(unverified), r1_passed=R1).status is (
            pc.SubcellStatus.UNBOUND
        )
        assert (
            pc.derive_subcell(
                cell, _evidence(_record(cell.subcell_id), malformed=1), r1_passed=R1
            ).status
            is pc.SubcellStatus.UNBOUND
        )
        assert (
            pc.derive_subcell(
                cell, _evidence(_record(cell.subcell_id), binding=None), r1_passed=R1
            ).status
            is pc.SubcellStatus.UNBOUND
        )
        assert pc.parse_permission_attempt(canonical_bytes(attempt.document())) == attempt

    def test_prerequisite_objects_and_cleanup_are_required(self) -> None:
        get = pc.subcell("R5-GET-PAYLOAD-HUMAN")
        put = pc.subcell("R4-PUT-PAYLOAD-HUMAN")
        get_record = _record(get.subcell_id, started_at=NOW + timedelta(minutes=5))
        # Read before the object existed: unbound.
        assert pc.derive_subcell(get, _evidence(get_record), r1_passed=R1).status is (
            pc.SubcellStatus.UNBOUND
        )
        key = _resolve(put).key
        put_record = _record(put.subcell_id, created_key=key)
        state = pc.derive_subcell(get, _evidence(put_record, get_record), r1_passed=R1)
        assert state.status is pc.SubcellStatus.PASSED
        # The creating subcell itself waits for its object to be confirmed removed.
        assert pc.derive_subcell(put, _evidence(put_record), r1_passed=R1).status is (
            pc.SubcellStatus.CLEANUP_UNRESOLVED
        )
        assert key is not None
        cleanup = pc.PermissionCleanup(
            stamp=STAMP,
            keys=(
                pc.CleanupKey(
                    key=key,
                    delete_observed=pc.ObservedClass.OK_204,
                    confirmation_observed=pc.ObservedClass.NOT_FOUND_404,
                    confirmed_absent=True,
                ),
            ),
            residue=(),
            operations=2,
            budget_exhausted=False,
            identity_verified=True,
            recorded_at=NOW + timedelta(hours=1),
            binding=BINDING,
        )
        assert pc.derive_subcell(
            put, _evidence(put_record, cleanups=(cleanup,)), r1_passed=R1
        ).status is (pc.SubcellStatus.PASSED)
        unresolved = pc.PermissionCleanup(
            stamp=STAMP,
            keys=(
                pc.CleanupKey(
                    key=key,
                    delete_observed=pc.ObservedClass.DENIED_OTHER,
                    confirmation_observed=pc.ObservedClass.OK_200,
                    confirmed_absent=False,
                ),
            ),
            residue=(key,),
            operations=2,
            budget_exhausted=False,
            identity_verified=True,
            recorded_at=NOW + timedelta(hours=1),
            binding=BINDING,
        )
        assert (
            pc.derive_subcell(
                put, _evidence(put_record, cleanups=(unresolved,)), r1_passed=R1
            ).status
            is pc.SubcellStatus.CLEANUP_UNRESOLVED
        )

    def test_r1_evidenced_and_blocked_subcells(self) -> None:
        own = pc.subcell("R6-BLD-RUN-OWN-REVISION")
        assert pc.derive_subcell(own, _evidence(), r1_passed=R1).status is (
            pc.SubcellStatus.AWAITING_R1
        )
        passed = pc.derive_subcell(own, _evidence(), r1_passed={**R1, ProductionActor.BUILD: True})
        assert passed.status is pc.SubcellStatus.PASSED
        blocked = pc.derive_subcell(pc.subcell("R4-SECRET-GET-TASK"), _evidence(), r1_passed=R1)
        assert blocked.status is pc.SubcellStatus.BLOCKED and blocked.reason == (
            pc.TASK_PROBE_DEPENDENCY
        )


class TestMatrix:
    """The permission cells inside the verification matrix (proposed ADR-0047)."""

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

    def test_r7_and_r9_pass_only_with_every_subcell_matched_under_the_binding(self) -> None:
        r7 = [_record(s.subcell_id) for s in pc.subcells_of("R7-QUALIFICATION")]
        states = self._states(_evidence(*r7[:-1]))
        assert states["R7-QUALIFICATION"].status is vc.CellStatus.UNEXECUTED
        assert len(states["R7-QUALIFICATION"].subcells) == 12
        states = self._states(_evidence(*r7))
        assert states["R7-QUALIFICATION"].status is vc.CellStatus.PASSED
        assert states["R9-FOUNDATION-TASK"].status is vc.CellStatus.UNEXECUTED
        r9 = [_record(s.subcell_id) for s in pc.subcells_of("R9-FOUNDATION-TASK")]
        states = self._states(_evidence(*r7, *r9))
        assert states["R9-FOUNDATION-TASK"].status is vc.CellStatus.PASSED
        # One stale record among matched ones: HISTORICAL, never PASSED.
        stale = [*r7[:-1], _record(r7[-1].subcell_id, binding=OTHER_BINDING)]
        states = self._states(_evidence(*stale))
        assert states["R7-QUALIFICATION"].status is vc.CellStatus.HISTORICAL
        assert vc.aggregate(states) is vc.AggregateStatus.INCOMPLETE

    def test_r4_stays_blocked_by_its_task_subcells_however_the_human_ones_read(self) -> None:
        human = [
            _record(s.subcell_id)
            for s in pc.subcells_of("R4-ACQUISITION")
            if s.layer is pc.Layer.L3_RUNTIME
        ]
        states = self._states(_evidence(*human))
        assert states["R4-ACQUISITION"].status is vc.CellStatus.BLOCKED
        assert pc.TASK_PROBE_DEPENDENCY in states["R4-ACQUISITION"].reason
        assert states["R8-DELETION"].status is vc.CellStatus.BLOCKED
        assert pc.DELETION_DEPENDENCY in states["R8-DELETION"].reason
        lines = vc.matrix_lines(states)
        assert any(
            line.strip().startswith("subcell=R4-SECRET-GET-TASK status=BLOCKED") for line in lines
        )

    def test_an_inverted_subcell_fails_its_cell_and_the_aggregate(self) -> None:
        r9 = pc.subcells_of("R9-FOUNDATION-TASK")
        inverted = _record(
            r9[0].subcell_id,
            observed=pc.ObservedClass.OK_200,
            outcome=pc.SubcellOutcome.INVERTED,
            started_task_id="a" * 32,
            stop_acknowledged=True,
            operations=2,
        )
        states = self._states(_evidence(inverted, _record(r9[1].subcell_id)))
        assert states["R9-FOUNDATION-TASK"].status is vc.CellStatus.FAILED
        assert "a task was started and stopped" in states["R9-FOUNDATION-TASK"].reason
        assert vc.aggregate(states) is vc.AggregateStatus.FAILED

    def test_r6_positive_subcells_follow_the_r1_bootstrap_cells(self) -> None:
        negatives = [
            _record(s.subcell_id)
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
        assert states["R6-LAUNCHERS"].status is vc.CellStatus.PASSED


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
    assert "blocked_on: " + pc.TASK_PROBE_DEPENDENCY[:40] in capsys.readouterr().out
    assert t.main("--cell", "R0") == tool.EXIT_REFUSED_ARGUMENTS
    assert t.constructions == [] and t.identity_calls == [] and t.client.calls == []
    for canary in CANARIES:
        assert canary not in out


@pytest.mark.parametrize("flag", sorted(tool.REFUSED_OPTIONS))
def test_refused_options_and_contradictory_arguments(tmp_path: Path, flag: str) -> None:
    t = _Tool(tmp_path)
    assert t.main(flag) == tool.EXIT_REFUSED_ARGUMENTS
    assert t.main(tool.AUTHORIZATION_FLAG) == tool.EXIT_REFUSED_ARGUMENTS
    assert t.main("--execute-subcell", "R4-LIST-HUMAN", *t.base()) == tool.EXIT_REFUSED_ARGUMENTS
    assert t.main("--execute-subcell", "R4-LIST-HUMAN", tool.AUTHORIZATION_FLAG) == (
        tool.EXIT_REFUSED_ARGUMENTS
    )
    assert (
        t.main(
            "--execute-subcell", "R4-LIST-HUMAN", *t.base(), tool.AUTHORIZATION_FLAG, "--cleanup"
        )
        == tool.EXIT_REFUSED_ARGUMENTS
    )
    assert t.constructions == [] and t.identity_calls == []


def test_execution_refuses_before_any_client_on_automation_profile_identity_and_layer(
    tmp_path: Path,
) -> None:
    t = _Tool(tmp_path)
    execute = ["--execute-subcell", "R4-LIST-HUMAN", *t.base(), tool.AUTHORIZATION_FLAG]
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
    assert t.main(
        "--execute-subcell", "R4-SECRET-GET-TASK", *t.base(), tool.AUTHORIZATION_FLAG
    ) == (tool.EXIT_REFUSED_SUBCELL)
    assert t.main(
        "--execute-subcell", "R6-ACQ-RUN-OWN-REVISION", *t.base(), tool.AUTHORIZATION_FLAG
    ) == (tool.EXIT_REFUSED_SUBCELL)
    assert t.main("--execute-subcell", "R4-NOTHING", *t.base(), tool.AUTHORIZATION_FLAG) == (
        tool.EXIT_REFUSED_SUBCELL
    )
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


def test_one_subcell_executes_with_the_attempt_written_before_the_operation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    t = _Tool(tmp_path)
    t.client.answers = [DENIED]
    execute = ["--execute-subcell", "R4-LIST-HUMAN", *t.base(), tool.AUTHORIZATION_FLAG]
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
    assert record.binding == attempt.binding and record.identity_verified
    assert record.binding.registration_sha256 == sha256_hex(t.scenario.inputs.read_bytes())
    assert record.binding.policy_declaration_sha256 == pc.declaration_digest(
        tool.declaration_paths(t.declarations)
    )
    for canary in (*CANARIES, BUCKET):
        assert canary not in out
    # --check-record reads it back; a mangled file is refused.
    assert t.main("--check-record", str(t.files("permission-record")[0])) == tool.EXIT_CHECKED
    (tmp_path / "broken.json").write_bytes(b"{")
    assert t.main("--check-record", str(tmp_path / "broken.json")) == tool.EXIT_CHECK_REFUSED


def test_an_inverted_or_undecided_subcell_is_recorded_and_exits_accordingly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    t = _Tool(tmp_path, pc.Principal.ACQUISITION_LAUNCHER)
    t.client.answers = [LAUNCHED, OK]
    execute = [
        "--execute-subcell",
        "R9-ACQ-OVERRIDE-FOUNDATION-ROLE",
        *t.base(),
        tool.AUTHORIZATION_FLAG,
    ]
    assert t.main(*execute) == tool.EXIT_INVERTED
    out = capsys.readouterr().out
    assert "unexpected_task_started=yes stop_acknowledged=yes" in out
    assert [c[0] for c in t.client.calls] == ["run_task", "stop_task"]
    assert t.identity_calls == [constants_for(ACQ).launcher_profile]
    t.client.answers = [TIMEOUT]
    assert t.main(*execute) == tool.EXIT_UNDECIDED
    assert TASK_ARN not in capsys.readouterr().out


def test_cleanup_runs_under_the_control_principal_over_every_recorded_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    t = _Tool(tmp_path)
    t.client.answers = [OK]
    put = ["--execute-subcell", "R4-PUT-PAYLOAD-HUMAN", *t.base(), tool.AUTHORIZATION_FLAG]
    assert t.main(*put) == tool.EXIT_EXECUTED
    capsys.readouterr()
    # An interrupted attempt (no record) for a creating subcell: its key is cleaned too.
    cell = pc.subcell("R4-PUT-INDEX-HUMAN")
    record = pc.parse_permission_record(t.files("permission-record")[0].read_bytes())
    attempt = pc.PermissionAttempt(
        subcell_id=cell.subcell_id,
        principal=cell.principal,
        stamp=record.stamp,
        key=_resolve(cell).key,
        started_at=t.clock.now() + timedelta(minutes=1),
        binding=record.binding,
    )
    t.scenario.store().write_record("permission-attempt", attempt.document(), at=attempt.started_at)
    control = _Tool(tmp_path / "control", pc.Principal.CONTROL)
    control.scenario = t.scenario
    control.root = t.root
    control.client.records_dir = t.scenario.records
    control.env = {**t.env, "AWS_PROFILE": r3.CONTROL_PROFILE}
    control.client.answers = [NO_CONTENT, NOT_FOUND, NO_CONTENT, NOT_FOUND]
    cleanup = ["--cleanup", *t.base(), tool.CLEANUP_FLAG]
    assert control.main(*cleanup, declaration_dir=t.declarations) == tool.EXIT_EXECUTED
    out = capsys.readouterr().out
    assert "cleanup keys=2 confirmed=2 residue=0 operations=4" in out
    assert control.gate_calls == ["foundation"] and control.identity_calls == []
    assert control.constructions == [(r3.CONTROL_PROFILE, "us-east-1")]
    deleted = sorted(c[1]["key"] for c in control.client.calls if c[0] == "delete_object")
    assert record.created_key is not None and attempt.key is not None
    assert deleted == sorted([record.created_key, attempt.key])
    # The matrix now reads the creating subcell PASSED (created and confirmed removed).
    evidence = runner.permission_evidence(t.scenario.store(), record.binding)
    assert (
        pc.derive_subcell(pc.subcell("R4-PUT-PAYLOAD-HUMAN"), evidence, r1_passed=R1).status
        is pc.SubcellStatus.PASSED
    )
    # Residue: a delete refused leaves the key unresolved and the cleanup exit says so.
    control.client.answers = [DENIED, OK, DENIED, OK]
    assert control.main(*cleanup, declaration_dir=t.declarations) == tool.EXIT_CLEANUP_UNRESOLVED
    assert "residue=2" in capsys.readouterr().out
    # The wrong flag for the mode, or the wrong profile: refused before any client.
    assert control.main("--cleanup", *t.base(), tool.AUTHORIZATION_FLAG) == (
        tool.EXIT_REFUSED_ARGUMENTS
    )
    assert t.main(*cleanup) == tool.EXIT_REFUSED_IDENTITY


def test_the_matrix_reads_permission_records_from_the_records_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from test_production_verification_cells import _Cells

    cells = _Cells(tmp_path)
    store = cells.scenario.store()
    binding = pc.PermissionBinding(
        environment_binding_sha256="ab" * 32,
        policy_declaration_sha256=pc.declaration_digest(tool.declaration_paths()),
        registration_sha256=sha256_hex(cells.scenario.inputs.read_bytes()),
        partition="aws",
        region="us-east-1",
    )
    for s in pc.subcells_of("R7-QUALIFICATION"):
        store.write_record(
            "permission-record", _record(s.subcell_id, binding=binding).document(), at=NOW
        )
    assert cells.main(*cells.base()) == runner.EXIT_MATRIX
    out = capsys.readouterr().out
    assert "cell=R7-QUALIFICATION ref=R-7 kind=PERMISSION_MATRIX status=PASSED" in out
    assert "  subcell=R7-ACQ-PUT-SILVER status=PASSED" in out
    assert "cell=R4-ACQUISITION ref=R-4 kind=PERMISSION_MATRIX status=BLOCKED" in out
    assert cells.scenario.clients.constructions == []
    # A malformed permission file makes every permission subcell UNBOUND, never ignored.
    (cells.scenario.records / "permission-record-20260914T180000Z-ffff.json").write_bytes(b"{}")
    assert cells.main(*cells.base()) == runner.EXIT_MATRIX
    out = capsys.readouterr().out
    assert "cell=R7-QUALIFICATION ref=R-7 kind=PERMISSION_MATRIX status=UNBOUND" in out


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

        def client(service: str) -> Any:
            built = tool._Boto3PermissionClient._client(adapter, service)
            built._endpoint.http_session = transport
            return built

        adapter._client = client
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

    def test_run_task_answers_carry_the_task_arn_and_failure_entries_decide_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter, transport = self._adapter(monkeypatch)
        transport.script = [
            (200, json.dumps({"tasks": [{"taskArn": TASK_ARN}], "failures": []}).encode())
        ]
        launched = adapter.run_task(
            cluster_arn=CLUSTER_ARN,
            task_definition_arn=verification_revision_arn(ACQ),
            task_role_arn=TARGETS.foundation_task_role_arn,
        )
        assert launched.task_arn == TASK_ARN and r3.classify(launched) is r3.ObservedClass.OK_200
        body = json.loads(transport.requests[-1].body)
        assert body["overrides"] == {"taskRoleArn": TARGETS.foundation_task_role_arn}
        assert body["count"] == 1
        transport.script = [
            (200, json.dumps({"tasks": [], "failures": [{"reason": "synthetic"}]}).encode())
        ]
        failed = adapter.run_task(
            cluster_arn=CLUSTER_ARN,
            task_definition_arn=verification_revision_arn(ACQ),
            task_role_arn=None,
        )
        assert failed.task_arn is None and r3.classify(failed) is r3.ObservedClass.AMBIGUOUS
        assert "overrides" not in json.loads(transport.requests[-1].body)
        transport.script = [(200, json.dumps({"task": {"taskArn": TASK_ARN}}).encode())]
        assert r3.classify(adapter.stop_task(cluster_arn=CLUSTER_ARN, task_arn=TASK_ARN)) is (
            r3.ObservedClass.OK_200
        )
        from botocore.exceptions import ReadTimeoutError  # type: ignore[import-untyped]

        transport.script = [ReadTimeoutError(endpoint_url="https://synthetic")]
        assert r3.classify(adapter.list_objects(BUCKET)) is r3.ObservedClass.TIMEOUT
