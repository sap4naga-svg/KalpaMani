"""The deletion rehearsal path end to end, offline (ADR-0048 s.4; ADR-0049 s.3; proposed
ADR-0050): the task under the actual deletion-role execution model (binding, input, identity,
release, then the operations), the launcher (identity, durable consumption, reservation,
input, one RunTask, placement, release, observation, record), the completion that rebuilds the
record from the verified receipt, the collector over the rehearsal receipt, and the reading
with the control principal's cleanup. Every answer is a fake's; nothing reaches AWS; the path
stays CLOSED."""

# ruff: noqa: S105, S106 -- pagination tokens are not credentials

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from test_production_deletion_rehearsal import (
    TIMEOUT,
    _prerequisite_attempt,
    _with_prerequisite,
)
from test_production_permission_cells import (
    BUCKET,
    DENIED,
    NO_CONTENT,
    NOT_FOUND,
    OK,
    FakePermissionClient,
    _Tool,
    tool,
)

from fixtures.production_runtime import (
    ACCOUNT,
    CLUSTER_ARN,
    EXECUTION_ROLE_ARN,
    IMAGE_DIGEST,
    INTERFACE_ID,
    KEY_ARN,
    NOW,
    REGION,
    SECURITY_GROUPS,
    SUBNET_ID,
    TASK_ARN,
    TASK_ID,
    FakeClock,
    FakeEc2,
    FakeEcs,
    FakeSsm,
    caller_identity,
    interface_entry,
    task_entry,
)
from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar import deletion_rehearsal as dr
from kalpamani.data.production.sharadar import deletion_rehearsal_launch as dl
from kalpamani.data.production.sharadar import deletion_rehearsal_task as dt
from kalpamani.data.production.sharadar import permission_cells as pc
from kalpamani.data.production.sharadar import receipt_collector as rc
from kalpamani.data.production.sharadar.compute import Ec2InterfaceAdapter
from kalpamani.data.production.sharadar.metadata import TaskMetadata
from kalpamani.data.production.sharadar.parameters import SsmParameterAdapter
from kalpamani.data.production.sharadar.r3_verification import ObservedClass
from kalpamani.data.production.sharadar.receipts import RECEIPT_LINE_PREFIX, ReceiptError
from kalpamani.data.production.sharadar.vocabulary import ProductionActor

ACQ: Final = ProductionActor.ACQUISITION
DELETION_ROLE_NAME: Final = "synthetic-licensed-data-deletion"
DELETION_ROLE_ARN: Final = f"arn:aws:iam::{ACCOUNT}:role/{DELETION_ROLE_NAME}"
REHEARSAL_REVISION_ARN: Final = (
    f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/{dr.REHEARSAL_FAMILY}:3"
)
LOG_GROUP: Final = "/kalpamani/synthetic/research"
STAMP: Final = "20260912T150000Z-abcd"
OTHER_STAMP_IDENTITY: Final = "rehearsal-20260912T150000Z-ffff"
LAUNCHER_ARN: Final = (
    f"arn:aws:sts::{ACCOUNT}:assumed-role/"
    f"AWSReservedSSO_{dr.REHEARSAL_LAUNCHER_PERMISSION_SET}_0123456789abcdef/owner"
)
TASK_IDENTITY_ARN: Final = f"arn:aws:sts::{ACCOUNT}:assumed-role/{DELETION_ROLE_NAME}/{TASK_ID}"
CONTAINER_VARIABLE: Final = "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"
TASK_ENVIRONMENT: Final[dict[str, str]] = {
    CONTAINER_VARIABLE: "/v2/credentials/synthetic-0001",
    "ECS_CONTAINER_METADATA_URI_V4": "http://169.254.170.2/v4/synthetic",
}


def _destination() -> rc.LogDestination:
    return rc.LogDestination(
        log_group=LOG_GROUP,
        stream_prefix=dr.REHEARSAL_STREAM_PREFIX,
        container=dr.REHEARSAL_CONTAINER,
    )


def _inputs(**overrides: Any) -> dl.RehearsalLaunchInputs:
    fields_: dict[str, Any] = {
        "cluster_arn": CLUSTER_ARN,
        "task_definition_arn": REHEARSAL_REVISION_ARN,
        "image_digest": IMAGE_DIGEST,
        "execution_role_arn": EXECUTION_ROLE_ARN,
        "deletion_role_arn": DELETION_ROLE_ARN,
        "subnet_id": SUBNET_ID,
        "security_group_ids": SECURITY_GROUPS,
        "platform_version": "1.4.0",
        "binding_key_arn": KEY_ARN,
        "log_destination": _destination(),
    }
    fields_.update(overrides)
    return dl.RehearsalLaunchInputs(**fields_)


def _binding_document(**overrides: Any) -> bytes:
    """The rehearsal runtime binding: the R-4 record's bucket, the deletion role's name."""
    document: dict[str, Any] = {
        "schema_version": 1,
        "binding_kind": dt.REHEARSAL_BINDING_KIND,
        "contract_id": dr.REHEARSAL_BINDING_CONTRACT_ID,
        "aws_partition": "aws",
        "aws_region": REGION,
        "target_account_id": ACCOUNT,
        "licensed_bucket_name": BUCKET,
        "deletion_role_name": DELETION_ROLE_NAME,
        "provenance": {
            "implementation_commit": "ab" * 20,
            "implementation_tree": "cd" * 20,
            "environment_binding_sha256": "ef" * 32,
        },
    }
    document.update(overrides)
    return json.dumps(document).encode()


def _metadata(**overrides: Any) -> TaskMetadata:
    fields_: dict[str, Any] = {
        "task_arn": TASK_ARN,
        "family": dr.REHEARSAL_FAMILY,
        "revision": 3,
        "image_ids": (IMAGE_DIGEST,),
    }
    fields_.update(overrides)
    return TaskMetadata(**fields_)


def _statement(tmp_path: Path, subcell: str = "R8-GET") -> tuple[_Tool, dr.RehearsalStatement]:
    """A prepared statement over a real R-4 prerequisite, under the session stamp."""
    t = _with_prerequisite(tmp_path)
    earlier = ("R8-GET",) if subcell != "R8-GET" else ()
    statement = dr.prepare_rehearsal(subcell, t.evidence(), stamp=STAMP, earlier=earlier)
    return t, statement


def _line_document(receipt: dt.RehearsalReceipt) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(receipt.line()[len(RECEIPT_LINE_PREFIX) :])
    return document


# ---------------------------------------------------------------------------
# The task
# ---------------------------------------------------------------------------


@dataclass
class _TaskFakes:
    """The task's injected world: parameters, identity, the S3 fake, a clock."""

    ssm: FakeSsm = field(default_factory=FakeSsm)
    clock: FakeClock = field(default_factory=FakeClock)
    s3: FakePermissionClient = field(default_factory=lambda: FakePermissionClient(DENIED))
    identity: dict[str, str] = field(default_factory=lambda: caller_identity(TASK_IDENTITY_ARN))
    environment: dict[str, str] = field(default_factory=lambda: dict(TASK_ENVIRONMENT))
    metadata: TaskMetadata = field(default_factory=_metadata)
    s3_builds: int = 0

    def build_s3(self) -> FakePermissionClient:
        self.s3_builds += 1
        return self.s3

    def adapters(self) -> dt.RehearsalTaskAdapters:
        return dt.RehearsalTaskAdapters(
            environment_names=lambda: list(self.environment),
            environment=self.environment.get,
            metadata=lambda: self.metadata,
            parameters=SsmParameterAdapter(ssm=self.ssm),
            caller_identity=lambda: dict(self.identity),
            s3=self.build_s3,
            now=self.clock.now,
            monotonic=self.clock.monotonic,
            sleep=self.clock.sleep,
        )

    def run(self, argv: list[str] | None = None) -> dt.RehearsalTaskResult:
        return dt.run_rehearsal_task(
            [dr.REHEARSAL_ENTRY] if argv is None else argv, self.adapters()
        )


def _materialize(
    fakes: _TaskFakes,
    statement: dr.RehearsalStatement,
    *,
    authorization: str = "aa" * 32,
    release: bool = True,
) -> dt.RehearsalInput:
    """The binding, the input and (by default) a release for exactly this task."""
    fakes.ssm.values[dr.REHEARSAL_BINDING_PARAMETER] = _binding_document()
    rehearsal_input = dt.RehearsalInput(
        identity=dt.rehearsal_identity(statement.stamp),
        statement=statement,
        authorization_sha256=authorization,
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    fakes.ssm.values[dr.REHEARSAL_INPUT_PARAMETER] = rehearsal_input.render()
    if release:
        _release(fakes, rehearsal_input)
    return rehearsal_input


def _release(fakes: _TaskFakes, rehearsal_input: dt.RehearsalInput, **overrides: Any) -> None:
    issued = fakes.clock.now()
    fields_: dict[str, Any] = {
        "identity": rehearsal_input.identity,
        "task_arn": TASK_ARN,
        "task_definition_arn": REHEARSAL_REVISION_ARN,
        "image_digest": IMAGE_DIGEST,
        "input_digest": sha256_hex(rehearsal_input.render()),
        "issued_at": issued,
        "expires_at": issued + timedelta(minutes=5),
    }
    fields_.update(overrides)
    fakes.ssm.values[dr.REHEARSAL_RELEASE_PARAMETER] = dt.RehearsalRelease(**fields_).render()


def _expectation(rehearsal_input: dt.RehearsalInput) -> dt.RehearsalExpectation:
    return dt.RehearsalExpectation(
        task_id=TASK_ID,
        task_definition_arn=REHEARSAL_REVISION_ARN,
        image_digest=IMAGE_DIGEST,
        identity=rehearsal_input.identity,
        input_digest=sha256_hex(rehearsal_input.render()),
        statement_sha256=rehearsal_input.statement.digest,
        authorization_sha256=rehearsal_input.authorization_sha256,
    )


class TestRehearsalTask:
    def test_the_task_rehearses_the_read_refusal_under_the_deletion_role(
        self, tmp_path: Path
    ) -> None:
        _t, statement = _statement(tmp_path)
        fakes = _TaskFakes()
        rehearsal_input = _materialize(fakes, statement)
        result = fakes.run()
        receipt = result.receipt
        assert receipt.outcome is dt.RehearsalTaskOutcome.REHEARSED and receipt.exit_code == 50
        assert result.parameter_reads == 2 and result.identity_calls == 1
        assert result.release_reads == 1 and result.s3_clients_built == 1
        assert fakes.s3_builds == 1
        assert [c[0] for c in fakes.s3.calls] == ["get_object"]
        assert fakes.s3.calls[0][1] == {
            "bucket": statement.target.bucket,
            "key": statement.target.key,
        }
        record = receipt.record
        assert record is not None and record.outcome is dr.RehearsalOutcome.PASS
        assert record.identity_verified and record.statement_sha256 == statement.digest
        # The one line: the shared prefix, the closed document, the digest; verified
        # against what the launcher knows, and refused against anything else.
        lines = receipt.render()
        assert lines[0] == "deletion rehearsal REHEARSED"
        assert lines[1].startswith(RECEIPT_LINE_PREFIX)
        document = _line_document(receipt)
        expectation = _expectation(rehearsal_input)
        verified = dt.verify_rehearsal_receipt(document, expectation=expectation)
        assert verified.outcome is dt.RehearsalTaskOutcome.REHEARSED and verified.block is not None
        assert verified.block["observed"] == ["DENIED_OTHER"] and verified.block["operations"] == 1
        assert "started_at" not in verified.block and "binding" not in verified.block
        for change in (
            {"receipt_digest": "00" * 32},
            {"exit_code": 51},
            {"outcome": "REFUSED_RELEASE"},
            {"binding_digest": "11" * 32},
            {"note": "x"},
            {"entry": "kalpamani-production-acquire"},
        ):
            with pytest.raises(dt.RehearsalContractError):
                dt.verify_rehearsal_receipt(dict(document, **change), expectation=expectation)
        with pytest.raises(dt.RehearsalContractError) as refusal:
            dt.verify_rehearsal_receipt(
                document, expectation=replace(expectation, task_id="f" * 32)
            )
        assert refusal.value.defect is dt.RehearsalContractDefect.RECEIPT_BINDING_MISMATCH
        with pytest.raises(dt.RehearsalContractError) as refusal:
            dt.verify_rehearsal_receipt(
                document, expectation=replace(expectation, statement_sha256="22" * 32)
            )
        assert refusal.value.defect is dt.RehearsalContractDefect.RECEIPT_STATEMENT_MISMATCH
        # No role name, ARN or account in the rendered line beyond the target's closed fields.
        assert DELETION_ROLE_NAME not in lines[1] and ACCOUNT not in lines[1]

    def test_the_list_and_delete_subcell_issues_the_two_operations_in_order(
        self, tmp_path: Path
    ) -> None:
        _t, statement = _statement(tmp_path, "R8-LIST-AND-DELETE")
        fakes = _TaskFakes(s3=FakePermissionClient(OK, NO_CONTENT))
        _materialize(fakes, statement)
        record = fakes.run().receipt.record
        assert record is not None and record.deleted and record.outcome is dr.RehearsalOutcome.PASS
        assert [c[0] for c in fakes.s3.calls] == ["list_objects", "delete_object"]
        assert fakes.s3.calls[1][1]["key"] == statement.target.key
        # An ambiguous delete: possibly deleted, INCONCLUSIVE, one attempt, no retry.
        fakes = _TaskFakes(s3=FakePermissionClient(OK, TIMEOUT))
        _materialize(fakes, statement)
        record = fakes.run().receipt.record
        assert record is not None and record.possibly_deleted and not record.deleted
        assert record.outcome is dr.RehearsalOutcome.INCONCLUSIVE
        assert [c[0] for c in fakes.s3.calls] == ["list_objects", "delete_object"]

    def test_every_refusal_comes_before_the_operations_and_builds_no_client(
        self, tmp_path: Path
    ) -> None:
        _t, statement = _statement(tmp_path)
        exit_of = dt.REHEARSAL_EXIT_STATUS
        # Entry: exactly one closed token.
        fakes = _TaskFakes()
        _materialize(fakes, statement)
        for argv in ([], ["kalpamani-production-acquire"], [dr.REHEARSAL_ENTRY, "extra"]):
            result = fakes.run(argv)
            assert result.receipt.outcome is dt.RehearsalTaskOutcome.REFUSED_ENTRY
            assert result.parameter_reads == 0 and fakes.s3_builds == 0
        assert result.receipt.exit_code == exit_of[dt.RehearsalTaskOutcome.REFUSED_ENTRY]
        # Credential environment: a workstation variable present, or the container one absent.
        for environment in (
            {**TASK_ENVIRONMENT, "AWS_PROFILE": "x"},
            {k: v for k, v in TASK_ENVIRONMENT.items() if k != CONTAINER_VARIABLE},
            {**TASK_ENVIRONMENT, CONTAINER_VARIABLE: "http://169.254.170.2/v2/credentials/x"},
        ):
            fakes = _TaskFakes(environment=environment)
            _materialize(fakes, statement)
            result = fakes.run()
            assert result.receipt.outcome is dt.RehearsalTaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT
            assert result.parameter_reads == 0 and result.identity_calls == 0
        # Metadata: two containers, or a foreign image digest.
        for metadata in (
            _metadata(image_ids=(IMAGE_DIGEST, IMAGE_DIGEST)),
            _metadata(image_ids=("not-a-digest",)),
        ):
            fakes = _TaskFakes(metadata=metadata)
            _materialize(fakes, statement)
            assert fakes.run().receipt.outcome is dt.RehearsalTaskOutcome.REFUSED_METADATA
        # Binding: absent, malformed, another partition, a foreign field, another kind.
        for binding in (
            None,
            b"{not json",
            _binding_document(aws_partition="aws-cn"),
            _binding_document(extra="x"),
            _binding_document(binding_kind="production_acquisition"),
            _binding_document(contract_id="kalpamani-research-build-runtime-binding/v1"),
        ):
            fakes = _TaskFakes()
            _materialize(fakes, statement)
            if binding is None:
                del fakes.ssm.values[dr.REHEARSAL_BINDING_PARAMETER]
            else:
                fakes.ssm.values[dr.REHEARSAL_BINDING_PARAMETER] = binding
            result = fakes.run()
            assert result.receipt.outcome is dt.RehearsalTaskOutcome.REFUSED_BINDING
            assert result.parameter_reads == 1 and result.identity_calls == 0
        # Input: absent, expired, a tampered statement (digest recomputed), another identity.
        fakes = _TaskFakes()
        _materialize(fakes, statement)
        del fakes.ssm.values[dr.REHEARSAL_INPUT_PARAMETER]
        assert fakes.run().receipt.outcome is dt.RehearsalTaskOutcome.REFUSED_INPUT
        fakes = _TaskFakes()
        _materialize(fakes, statement)
        fakes.clock.seconds += 2 * 3600
        assert fakes.run().receipt.outcome is dt.RehearsalTaskOutcome.REFUSED_INPUT
        fakes = _TaskFakes()
        rehearsal_input = _materialize(fakes, statement)
        tampered = rehearsal_input.document()
        tampered["statement"]["target"]["key"] = statement.target.key.replace("a", "b", 1)
        fakes.ssm.values[dr.REHEARSAL_INPUT_PARAMETER] = canonical_bytes(tampered)
        assert fakes.run().receipt.outcome is dt.RehearsalTaskOutcome.REFUSED_INPUT
        fakes = _TaskFakes()
        rehearsal_input = _materialize(fakes, statement)
        wrong_identity = dict(rehearsal_input.document(), identity=OTHER_STAMP_IDENTITY)
        fakes.ssm.values[dr.REHEARSAL_INPUT_PARAMETER] = canonical_bytes(wrong_identity)
        assert fakes.run().receipt.outcome is dt.RehearsalTaskOutcome.REFUSED_INPUT
        # Target: the statement names another bucket than the bound one.
        fakes = _TaskFakes()
        _materialize(fakes, statement)
        fakes.ssm.values[dr.REHEARSAL_BINDING_PARAMETER] = _binding_document(
            licensed_bucket_name="another-synthetic-bucket"
        )
        result = fakes.run()
        assert result.receipt.outcome is dt.RehearsalTaskOutcome.REFUSED_TARGET
        assert result.identity_calls == 0
        # Identity: another role, another session, another account, the human launcher's
        # generated role, an IAM role ARN -- each refused with no release read and no client.
        for arn, account in (
            (f"arn:aws:sts::{ACCOUNT}:assumed-role/synthetic-other-role/{TASK_ID}", ACCOUNT),
            (f"arn:aws:sts::{ACCOUNT}:assumed-role/{DELETION_ROLE_NAME}/{'f' * 32}", ACCOUNT),
            (
                f"arn:aws:sts::111111111111:assumed-role/{DELETION_ROLE_NAME}/{TASK_ID}",
                "111111111111",
            ),
            (LAUNCHER_ARN, ACCOUNT),
            (DELETION_ROLE_ARN, ACCOUNT),
        ):
            fakes = _TaskFakes(identity=caller_identity(arn, account))
            _materialize(fakes, statement)
            result = fakes.run()
            assert result.receipt.outcome is dt.RehearsalTaskOutcome.REFUSED_IDENTITY, arn
            assert result.identity_calls == 1 and result.release_reads == 0
            assert fakes.s3_builds == 0
        # Release: absent within the bounds (5 s polls, 60 reads, 300 s), another task's,
        # expired, malformed -- each REFUSED_RELEASE with no client built.
        fakes = _TaskFakes()
        _materialize(fakes, statement, release=False)
        result = fakes.run()
        assert result.receipt.outcome is dt.RehearsalTaskOutcome.REFUSED_RELEASE
        assert result.release_reads == 60 and fakes.clock.monotonic() <= 300.0
        assert all(s == 5.0 for s in fakes.clock.sleeps) and fakes.s3_builds == 0
        for change in (
            {"task_arn": TASK_ARN.replace(TASK_ID, "f" * 32)},
            {"task_definition_arn": REHEARSAL_REVISION_ARN.replace(":3", ":4")},
            {"image_digest": "sha256:" + "ab" * 32},
            {"input_digest": "cd" * 32},
            {"identity": OTHER_STAMP_IDENTITY},
        ):
            fakes = _TaskFakes()
            rehearsal_input = _materialize(fakes, statement, release=False)
            _release(fakes, rehearsal_input, **change)
            result = fakes.run()
            assert result.receipt.outcome is dt.RehearsalTaskOutcome.REFUSED_RELEASE, change
            assert result.release_reads == 1 and fakes.s3_builds == 0
        fakes = _TaskFakes()
        rehearsal_input = _materialize(fakes, statement, release=False)
        _release(fakes, rehearsal_input)
        fakes.clock.seconds += 600.0
        assert fakes.run().receipt.outcome is dt.RehearsalTaskOutcome.REFUSED_RELEASE
        fakes = _TaskFakes()
        _materialize(fakes, statement, release=False)
        fakes.ssm.values[dr.REHEARSAL_RELEASE_PARAMETER] = b"{broken"
        assert fakes.run().receipt.outcome is dt.RehearsalTaskOutcome.REFUSED_RELEASE
        # A refused receipt carries no record, is bound once the input was read, verifies
        # against the launch and never reads REHEARSED.
        fakes = _TaskFakes()
        rehearsal_input = _materialize(fakes, statement, release=False)
        receipt = fakes.run().receipt
        assert receipt.record is None and receipt.binding_digest is not None
        verified = dt.verify_rehearsal_receipt(
            _line_document(receipt), expectation=_expectation(rehearsal_input)
        )
        assert verified.outcome is dt.RehearsalTaskOutcome.REFUSED_RELEASE
        assert verified.block is None and verified.exit_code == 57
        with pytest.raises(ValueError, match="record is present exactly"):
            dt.RehearsalReceipt(
                outcome=dt.RehearsalTaskOutcome.REHEARSED, binding_digest="ab" * 32, record=None
            )

    def test_the_contracts_are_closed(self, tmp_path: Path) -> None:
        _t, statement = _statement(tmp_path)
        fakes = _TaskFakes()
        rehearsal_input = _materialize(fakes, statement)
        parsed = dt.parse_rehearsal_input(rehearsal_input.render(), now=fakes.clock.now())
        assert parsed.statement.digest == statement.digest
        assert parsed.identity == rehearsal_input.identity
        binding = dt.parse_rehearsal_runtime_binding(_binding_document())
        assert binding.deletion_role_name == DELETION_ROLE_NAME
        assert "synthetic" not in repr(binding) and "synthetic" not in repr(parsed)
        assert dt.rehearsal_identity(STAMP) == "rehearsal-" + STAMP
        with pytest.raises(ValueError):
            dt.rehearsal_identity("not-a-stamp")
        with pytest.raises(dt.RehearsalContractError) as refusal:
            dt.parse_rehearsal_input(
                rehearsal_input.render(), now=fakes.clock.now() + timedelta(days=2)
            )
        assert refusal.value.defect is dt.RehearsalContractDefect.INPUT_EXPIRED
        long_lived = dict(
            rehearsal_input.document(),
            expires_at=(fakes.clock.now() + timedelta(days=3)).isoformat(),
        )
        with pytest.raises(dt.RehearsalContractError) as refusal:
            dt.parse_rehearsal_input(canonical_bytes(long_lived), now=fakes.clock.now())
        assert refusal.value.defect is dt.RehearsalContractDefect.INPUT_MALFORMED
        release = dt.parse_rehearsal_release(
            fakes.ssm.values[dr.REHEARSAL_RELEASE_PARAMETER],
            expectation=_expectation(rehearsal_input),
            now=fakes.clock.now(),
        )
        assert release.identity == rehearsal_input.identity and "synthetic" not in repr(release)
        assert dt.REHEARSAL_EXIT_STATUS[dt.RehearsalTaskOutcome.REHEARSED] == 50
        assert set(dt.REHEARSAL_EXIT_STATUS.values()) == set(range(50, 60))


# ---------------------------------------------------------------------------
# The launcher
# ---------------------------------------------------------------------------


@dataclass
class _LaunchFakes:
    ecs: FakeEcs = field(default_factory=FakeEcs)
    ec2: FakeEc2 = field(default_factory=FakeEc2)
    ssm: FakeSsm = field(default_factory=FakeSsm)
    clock: FakeClock = field(default_factory=FakeClock)
    identity: dict[str, str] = field(default_factory=lambda: caller_identity(LAUNCHER_ARN))
    identity_calls: int = 0

    def caller(self) -> dict[str, str]:
        self.identity_calls += 1
        return dict(self.identity)


def _task(status: str, **overrides: Any) -> dict[str, Any]:
    """One DescribeTasks entry of the rehearsal family's revision."""
    entry = task_entry(ACQ, status=status, **overrides)
    entry["taskDefinitionArn"] = REHEARSAL_REVISION_ARN
    return entry


def _launch_fakes(exit_code: int | None = 50) -> _LaunchFakes:
    fakes = _LaunchFakes()
    fakes.ecs.run_response = {
        "tasks": [_task("PROVISIONING", attachment_status=None)],
        "failures": [],
    }
    fakes.ecs.descriptions = [
        _task("PENDING"),
        _task("RUNNING"),
        _task("STOPPED", exit_code=exit_code),
    ]
    fakes.ec2.interface = interface_entry()
    return fakes


def _prepared_again(t: _Tool) -> dr.RehearsalStatement:
    """Another R8-GET statement over the same prerequisite, under a fresh stamp."""
    return dr.prepare_rehearsal("R8-GET", t.evidence(), stamp="20260912T150100Z-abce")


def _launch(
    t: _Tool,
    statement: dr.RehearsalStatement,
    fakes: _LaunchFakes,
    *,
    inputs: dl.RehearsalLaunchInputs | None = None,
) -> tuple[dl.RehearsalLaunchReport, str]:
    """Authorize the statement, then launch it over the fakes: the report and the
    authorization digest."""
    authorization = t.authorize(
        statement.subcell_id, statement.digest, name=f"{statement.digest[:16]}.json"
    )
    parsed = pc.parse_permission_authorization(
        authorization.read_bytes(),
        subcell_id=statement.subcell_id,
        statement_sha256=statement.digest,
        now=t.clock.now(),
    )
    compiled = dl.CompiledRehearsalLaunch(inputs=inputs or _inputs(), stamp=statement.stamp)
    adapters = dl.RehearsalLaunchAdapters(
        ecs=dl.RehearsalEcs(ecs=fakes.ecs, compiled=compiled),
        ec2=Ec2InterfaceAdapter(ec2=fakes.ec2),
        parameters=SsmParameterAdapter(ssm=fakes.ssm),
    )
    report = dl.launch_rehearsal(
        statement,
        authorization_sha256=parsed.digest,
        authorization_document=parsed.document(),
        store=t.scenario.store(),
        compiled=compiled,
        adapters=adapters,
        caller_identity=fakes.caller,
        now=fakes.clock.now,
        monotonic=fakes.clock.monotonic,
        sleep=fakes.clock.sleep,
    )
    return report, parsed.digest


class TestRehearsalLaunch:
    def test_the_launch_inputs_are_closed_and_held_to_the_family_and_the_role(self) -> None:
        inputs = _inputs()
        parsed = dl.parse_rehearsal_launch_inputs(canonical_bytes(inputs.document()))
        assert parsed == inputs and parsed.deletion_role_name == DELETION_ROLE_NAME
        assert parsed.account == ACCOUNT and "synthetic" not in repr(parsed)
        acquire_revision = (
            f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/kalpamani-production-acquire:3"
        )
        for change, defect in (
            (
                {"task_definition_arn": acquire_revision},
                dl.RehearsalLaunchDefect.NOT_THE_REHEARSAL_FAMILY,
            ),
            (
                {"deletion_role_arn": f"arn:aws:iam::{ACCOUNT}:role/synthetic-research"},
                dl.RehearsalLaunchDefect.ROLE_NOT_THE_DELETION_ROLE,
            ),
            (
                {"cluster_arn": CLUSTER_ARN.replace(ACCOUNT, "111111111111")},
                dl.RehearsalLaunchDefect.ACCOUNTS_DIFFER,
            ),
            ({"image_digest": "latest"}, dl.RehearsalLaunchDefect.INPUTS_MALFORMED),
            ({"security_group_ids": ()}, dl.RehearsalLaunchDefect.INPUTS_MALFORMED),
            (
                {
                    "log_destination": rc.LogDestination(
                        log_group=LOG_GROUP,
                        stream_prefix="production-acquire",
                        container="acquire",
                    )
                },
                dl.RehearsalLaunchDefect.INPUTS_MALFORMED,
            ),
        ):
            with pytest.raises(dl.RehearsalLaunchError) as refusal:
                _inputs(**change)
            assert refusal.value.defect is defect, change
        with pytest.raises(dl.RehearsalLaunchError):
            dl.parse_rehearsal_launch_inputs(canonical_bytes({**inputs.document(), "extra": 1}))
        # The compiled request: no overrides, no ExecuteCommand, no public IP, the tag.
        compiled = dl.CompiledRehearsalLaunch(inputs=inputs, stamp=STAMP)
        request = compiled.request()
        assert "overrides" not in request and request["enableExecuteCommand"] is False
        network = request["networkConfiguration"]["awsvpcConfiguration"]
        assert network["assignPublicIp"] == "DISABLED" and network["subnets"] == [SUBNET_ID]
        assert request["startedBy"] == "kalpamani-rehearsal-" + STAMP and request["count"] == 1
        assert request["taskDefinition"] == REHEARSAL_REVISION_ARN
        assert compiled.identity == "rehearsal-" + STAMP
        with pytest.raises(dl.RehearsalLaunchError):
            dl.CompiledRehearsalLaunch(inputs=inputs, stamp="bad")
        # The launcher's identity: the generated role of the rehearsal set in the account.
        assert dl.rehearsal_launcher_identity_verified(
            caller_identity(LAUNCHER_ARN), account=ACCOUNT
        )
        for arn, account in (
            (LAUNCHER_ARN, "111111111111"),
            (
                f"arn:aws:sts::{ACCOUNT}:assumed-role/"
                "AWSReservedSSO_KalpaManiProductionAcquireLaunch_0123456789abcdef/owner",
                ACCOUNT,
            ),
            (TASK_IDENTITY_ARN, ACCOUNT),
            (f"arn:aws:iam::{ACCOUNT}:user/owner", ACCOUNT),
        ):
            assert not dl.rehearsal_launcher_identity_verified(
                caller_identity(arn, account), account=ACCOUNT
            )

    def test_a_launch_consumes_before_it_mutates_and_records_what_it_observed(
        self, tmp_path: Path
    ) -> None:
        t, statement = _statement(tmp_path)
        fakes = _launch_fakes()
        report, digest = _launch(t, statement, fakes)
        assert report.outcome is dl.RehearsalLaunchOutcome.LAUNCHED and report.record is not None
        assert report.run_tasks == 1 and report.stops == 0 and report.cleanup_failures == ()
        assert report.parameter_puts == 2 and report.parameter_deletes == 2
        assert fakes.identity_calls == 1
        store = t.scenario.store()
        assert store.is_consumed(dr.REHEARSAL_CONSUMPTION_KIND, digest)
        # The order of the mutations: consumption, reservation, input, RunTask, release.
        assert fakes.ssm.names("put_parameter") == [
            dr.REHEARSAL_INPUT_PARAMETER,
            dr.REHEARSAL_RELEASE_PARAMETER,
        ]
        assert fakes.ssm.names("delete_parameter") == [
            dr.REHEARSAL_RELEASE_PARAMETER,
            dr.REHEARSAL_INPUT_PARAMETER,
        ]
        assert fakes.ssm.values == {}
        assert [c[0] for c in fakes.ecs.calls] == ["run_task"] + ["describe_tasks"] * 3
        run_kwargs = fakes.ecs.calls[0][1]
        assert "overrides" not in run_kwargs
        assert run_kwargs["taskDefinition"] == REHEARSAL_REVISION_ARN
        # Correction 1: the reservation and its resolution are anchored beside the canonical
        # ledger (never under the records directory), the reservation retaining the whole
        # specification; the launch record names the reservation by digest.
        assert t.files("rehearsal-reservation") == []
        [reservation] = dl.rehearsal_reservations(store).values()
        assert reservation.statement_sha256 == statement.digest
        assert reservation.authorization_sha256 == digest
        assert reservation.specification.digest == reservation.specification_sha256
        assert reservation.started_by == "kalpamani-rehearsal-" + STAMP
        assert reservation.cluster_arn == CLUSTER_ARN
        [resolution] = dl.rehearsal_resolutions(store).values()
        assert resolution.reservation_sha256 == reservation.digest
        assert resolution.task_state is dl.RehearsalTaskState.OBSERVED_TERMINAL
        assert resolution.task_id == TASK_ID and resolution.outcome == "LAUNCHED"
        assert dl.unsettled_rehearsals(store) == []
        record = report.record
        assert record.reservation_sha256 == reservation.digest
        assert resolution.launch_record_sha256 == record.digest
        assert record.observed_exit_code == 50 and record.task_id == TASK_ID
        assert record.task_definition_arn == REHEARSAL_REVISION_ARN
        assert record.image_digest == IMAGE_DIGEST
        assert record.subnet_id == SUBNET_ID and record.network_interface_id == INTERFACE_ID
        [path] = t.files("rehearsal-launch-record")
        assert dl.parse_rehearsal_launch_record(path.read_bytes()) == record
        # The release named exactly this task, this revision, this image, this input.
        release_put = next(
            kw
            for name, kw in fakes.ssm.calls
            if name == "put_parameter" and kw["Name"] == dr.REHEARSAL_RELEASE_PARAMETER
        )
        assert release_put["Overwrite"] is False and release_put["KeyId"] == KEY_ARN
        release = dt.parse_rehearsal_release(
            release_put["Value"].encode(),
            expectation=record.expectation(),
            now=fakes.clock.now() - timedelta(seconds=1),
        )
        assert release.task_arn == TASK_ARN
        # A second launch under the same authorization refuses before any mutation: the
        # consumption is the durable guard.
        fakes2 = _launch_fakes()
        report2, _ = _launch(t, statement, fakes2)
        assert report2.outcome is dl.RehearsalLaunchOutcome.REFUSED_CONSUMED
        assert report2.run_tasks == 0 and fakes2.ecs.calls == [] and fakes2.ssm.calls == []
        assert len(dl.rehearsal_reservations(store)) == 1

    def test_refusals_and_interruptions_leave_evidence_and_never_retry(
        self, tmp_path: Path
    ) -> None:
        # The launcher is not the rehearsal set: nothing consumed, nothing written.
        t, statement = _statement(tmp_path / "identity")
        fakes = _launch_fakes()
        fakes.identity = caller_identity(TASK_IDENTITY_ARN)
        report, digest = _launch(t, statement, fakes)
        assert report.outcome is dl.RehearsalLaunchOutcome.REFUSED_IDENTITY
        assert not t.scenario.store().is_consumed(dr.REHEARSAL_CONSUMPTION_KIND, digest)
        assert fakes.ecs.calls == [] and fakes.ssm.calls == []
        assert t.files("rehearsal-reservation") == []
        # A stale input parameter: consumed and reserved, nothing launched.
        t, statement = _statement(tmp_path / "stale-input")
        fakes = _launch_fakes()
        fakes.ssm.values[dr.REHEARSAL_INPUT_PARAMETER] = b"stale"
        report, digest = _launch(t, statement, fakes)
        assert report.outcome is dl.RehearsalLaunchOutcome.REFUSED_INPUT_EXISTS
        assert report.run_tasks == 0
        assert t.scenario.store().is_consumed(dr.REHEARSAL_CONSUMPTION_KIND, digest)
        assert len(dl.rehearsal_reservations(t.scenario.store())) == 1
        [resolution] = dl.rehearsal_resolutions(t.scenario.store()).values()
        assert resolution.task_state is dl.RehearsalTaskState.NOT_STARTED
        assert t.files("rehearsal-launch-record") == []
        # RunTask refused definitively, and RunTask ambiguous: recorded, no retry, the
        # input removed, the reservation kept, the authorization spent.
        for failure, outcome in (
            ("AccessDeniedException", dl.RehearsalLaunchOutcome.LAUNCH_REFUSED),
            ("ServerException", dl.RehearsalLaunchOutcome.LAUNCH_AMBIGUOUS),
        ):
            t, statement = _statement(tmp_path / failure)
            fakes = _launch_fakes()
            fakes.ecs.run_failure = failure
            report, digest = _launch(t, statement, fakes)
            assert report.outcome is outcome and report.run_tasks == 1
            assert [c[0] for c in fakes.ecs.calls] == ["run_task"]
            assert fakes.ssm.values == {}
            assert t.scenario.store().is_consumed(dr.REHEARSAL_CONSUMPTION_KIND, digest)
            assert t.files("rehearsal-launch-record") == []
            [resolution] = dl.rehearsal_resolutions(t.scenario.store()).values()
            assert resolution.outcome == outcome.value
            if outcome is dl.RehearsalLaunchOutcome.LAUNCH_AMBIGUOUS:
                # A task may exist: UNKNOWN, unsettled until a verified cleanup; the next
                # launch on this ledger refuses before consuming anything.
                assert resolution.task_state is dl.RehearsalTaskState.UNKNOWN
                assert len(dl.unsettled_rehearsals(t.scenario.store())) == 1
                again = _launch_fakes()
                report2, digest2 = _launch(t, _prepared_again(t), again)
                assert report2.outcome is dl.RehearsalLaunchOutcome.REFUSED_RECOVERY_PENDING
                assert again.ecs.calls == [] and again.ssm.calls == []
                assert not t.scenario.store().is_consumed(dr.REHEARSAL_CONSUMPTION_KIND, digest2)
            else:
                assert resolution.task_state is dl.RehearsalTaskState.NOT_STARTED
                assert dl.unsettled_rehearsals(t.scenario.store()) == []
        # Misplaced (another subnet), a public IP, another revision, another image: stopped,
        # never released, no launch record. Correction 2: the stop is acknowledged AND the
        # exact task is then observed STOPPED (the queued descriptions end STOPPED), which is
        # what settles the reservation -- never the acknowledgement alone.
        for name in ("subnet", "public-ip", "revision", "image"):
            fakes = _launch_fakes()
            if name == "subnet":
                fakes.ec2.interface = interface_entry(subnet_id="subnet-0fedcba9876543210")
            elif name == "public-ip":
                fakes.ec2.interface = interface_entry(public_ip="203.0.113.7")
            elif name == "revision":
                running = _task("RUNNING")
                running["taskDefinitionArn"] = REHEARSAL_REVISION_ARN.replace(":3", ":9")
                fakes.ecs.descriptions = [running, _task("STOPPED", exit_code=None)]
            else:
                fakes.ecs.descriptions = [
                    _task("RUNNING", image_digest="sha256:" + "ab" * 32),
                    _task("STOPPED", exit_code=None),
                ]
            t, statement = _statement(tmp_path / name)
            report, _ = _launch(t, statement, fakes)
            assert report.outcome is dl.RehearsalLaunchOutcome.MISPLACED, name
            calls = [c[0] for c in fakes.ecs.calls]
            assert report.stops == 1 and calls.count("stop_task") == 1
            assert calls[calls.index("stop_task") + 1 :] == ["describe_tasks"] * (
                len(calls) - calls.index("stop_task") - 1
            )
            assert calls[-1] == "describe_tasks"
            assert fakes.ecs.names("stop_task")[0]["reason"] == dl.STOP_REASON_MISPLACED
            assert dr.REHEARSAL_RELEASE_PARAMETER not in fakes.ssm.names("put_parameter")
            assert fakes.ssm.values == {} and t.files("rehearsal-launch-record") == []
            [resolution] = dl.rehearsal_resolutions(t.scenario.store()).values()
            assert resolution.task_state is dl.RehearsalTaskState.STOPPED
            assert (
                resolution.task_id == TASK_ID and dl.unsettled_rehearsals(t.scenario.store()) == []
            )
        # A stale release: stopped and observed STOPPED, no launch record.
        t, statement = _statement(tmp_path / "stale-release")
        fakes = _launch_fakes()
        fakes.ssm.values[dr.REHEARSAL_RELEASE_PARAMETER] = b"stale"
        report, _ = _launch(t, statement, fakes)
        assert report.outcome is dl.RehearsalLaunchOutcome.STALE_RELEASE and report.stops == 1
        assert fakes.ecs.names("stop_task")[0]["reason"] == dl.STOP_REASON_STALE_RELEASE
        stale_calls = [c[0] for c in fakes.ecs.calls]
        assert stale_calls.count("stop_task") == 1 and stale_calls[-1] == "describe_tasks"
        assert t.files("rehearsal-launch-record") == []
        [resolution] = dl.rehearsal_resolutions(t.scenario.store()).values()
        assert resolution.task_state is dl.RehearsalTaskState.STOPPED
        assert resolution.task_id == TASK_ID and dl.unsettled_rehearsals(t.scenario.store()) == []
        # Observation exhausted: released, the task never seen stopped within 120 reads /
        # 600 s; the record says so with no exit, and completes nothing.
        t, statement = _statement(tmp_path / "exhausted")
        fakes = _launch_fakes()
        fakes.ecs.descriptions = [_task("RUNNING")]
        report, _ = _launch(t, statement, fakes)
        assert report.outcome is dl.RehearsalLaunchOutcome.OBSERVATION_EXHAUSTED
        assert report.record is not None and report.record.observed_exit_code is None
        [resolution] = dl.rehearsal_resolutions(t.scenario.store()).values()
        assert resolution.task_state is dl.RehearsalTaskState.STARTED_NOT_TERMINAL
        assert len(dl.unsettled_rehearsals(t.scenario.store())) == 1
        assert report.describes <= dl.MAX_OBSERVATION_READS
        assert fakes.clock.monotonic() <= dl.OBSERVATION_CEILING_SECONDS
        assert fakes.ssm.values == {}
        with pytest.raises(dl.RehearsalCompletionError) as refusal:
            dl.complete_rehearsal(report.record, {}, statement=statement)
        assert refusal.value.defect is dl.RehearsalCompletionDefect.LAUNCH_NOT_TERMINAL
        # A task that stopped without an exit code: LAUNCHED with no observed exit, and
        # equally completes nothing.
        t, statement = _statement(tmp_path / "no-exit")
        report, _ = _launch(t, statement, _launch_fakes(exit_code=None))
        assert report.outcome is dl.RehearsalLaunchOutcome.LAUNCHED
        assert report.record is not None and report.record.observed_exit_code is None
        with pytest.raises(dl.RehearsalCompletionError) as refusal:
            dl.complete_rehearsal(report.record, {}, statement=statement)
        assert refusal.value.defect is dl.RehearsalCompletionDefect.LAUNCH_NOT_TERMINAL
        # A cleanup failure is reported beside the outcome, never hidden.
        t, statement = _statement(tmp_path / "cleanup")
        fakes = _launch_fakes()
        fakes.ssm.delete_failures[dr.REHEARSAL_INPUT_PARAMETER] = "InternalServerError"
        report, _ = _launch(t, statement, fakes)
        assert report.outcome is dl.RehearsalLaunchOutcome.LAUNCHED
        assert report.cleanup_failures == ("delete_parameter:TRANSIENT",)


# ---------------------------------------------------------------------------
# Completion, the reading, and the collector
# ---------------------------------------------------------------------------


def _task_run_for(
    launch: dl.RehearsalLaunchRecord,
    statement: dr.RehearsalStatement,
    s3: FakePermissionClient,
    *,
    release: bool = True,
) -> tuple[dt.RehearsalReceipt, dl.RehearsalLaunchRecord]:
    """The receipt the task emits for this launch, run over the input the launcher
    materialized (rebuilt here field for field), and the launch record bound to those
    input bytes -- the launcher's own record carries the digest of the bytes it put."""
    fakes = _TaskFakes(s3=s3)
    fakes.ssm.values[dr.REHEARSAL_BINDING_PARAMETER] = _binding_document()
    rehearsal_input = dt.RehearsalInput(
        identity=launch.identity,
        statement=statement,
        authorization_sha256=launch.authorization_sha256,
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    fakes.ssm.values[dr.REHEARSAL_INPUT_PARAMETER] = rehearsal_input.render()
    if release:
        _release(fakes, rehearsal_input)
    receipt = fakes.run().receipt
    bound = replace(launch, input_digest=sha256_hex(rehearsal_input.render()))
    return receipt, bound


class TestCompletionAndReading:
    def test_the_verified_receipt_completes_the_launch_and_the_control_confirms(
        self, tmp_path: Path
    ) -> None:
        t, statement = _statement(tmp_path, "R8-LIST-AND-DELETE")
        attempt = _prerequisite_attempt(t)
        fakes = _launch_fakes()
        report, _ = _launch(t, statement, fakes)
        launch = report.record
        assert launch is not None
        receipt, bound_launch = _task_run_for(
            launch, statement, FakePermissionClient(OK, NO_CONTENT)
        )
        assert receipt.outcome is dt.RehearsalTaskOutcome.REHEARSED
        document = _line_document(receipt)
        record = dl.complete_rehearsal(bound_launch, document, statement=statement)
        assert record.outcome is dr.RehearsalOutcome.PASS and record.deleted
        assert record.identity_verified and record.statement_sha256 == statement.digest
        assert record.authorization_sha256 == launch.authorization_sha256
        assert record.binding == statement.binding and record.target == statement.target
        assert record.started_at == launch.launched_at
        assert record.finished_at == launch.recorded_at
        assert dr.parse_rehearsal_record(canonical_bytes(record.document())) == record
        # The launcher's own record (unbound input digest) refuses the same receipt:
        # a receipt is held to the input bytes the launch record names.
        with pytest.raises(dl.RehearsalCompletionError) as refusal:
            dl.complete_rehearsal(launch, document, statement=statement)
        assert refusal.value.defect is dl.RehearsalCompletionDefect.RECEIPT_REFUSED
        other_statement = dr.prepare_rehearsal("R8-GET", t.evidence(), stamp=STAMP)
        # Acknowledged is not confirmed: CLEANUP_UNRESOLVED until the control principal's
        # verified cleanup, later than the record, confirms the exact key absent; then PASSED.
        status, _ = dr.derive_rehearsal(record, (), prerequisite_attempt=attempt)
        assert status is dr.RehearsalStatus.CLEANUP_UNRESOLVED
        control = t.control(tmp_path)
        control.clock.seconds = fakes.clock.seconds + 60.0
        assert t.cleanup(control, [NO_CONTENT, NOT_FOUND]) == tool.EXIT_EXECUTED
        cleanups = t.evidence().cleanups
        status, _ = dr.derive_rehearsal(record, cleanups, prerequisite_attempt=attempt)
        assert status is dr.RehearsalStatus.PASSED
        # Once the control settled the object, no further rehearsal can be prepared on it.
        with pytest.raises(dr.RehearsalError) as settled:
            dr.prepare_rehearsal("R8-GET", t.evidence(), stamp=STAMP)
        assert settled.value.defect is dr.RehearsalDefect.PREREQUISITE_SETTLED
        # The cleanup's own success is never the deletion role's: a record whose delete
        # was denied stays FAILED however the control cleaned up afterwards.
        denied = replace(
            record,
            observed=(ObservedClass.OK_200, ObservedClass.DENIED_OTHER),
            outcome=dr.RehearsalOutcome.FAIL,
            deleted=False,
        )
        assert dr.derive_rehearsal(denied, cleanups, prerequisite_attempt=attempt)[0] is (
            dr.RehearsalStatus.FAILED
        )
        # Every refusal of the completion; none writes a record.
        wrong_exit = replace(bound_launch, observed_exit_code=57)
        with pytest.raises(dl.RehearsalCompletionError) as refusal:
            dl.complete_rehearsal(wrong_exit, document, statement=statement)
        assert refusal.value.defect is dl.RehearsalCompletionDefect.EXIT_CONTRADICTS
        refused, refused_launch = _task_run_for(
            launch, statement, FakePermissionClient(), release=False
        )
        assert refused.outcome is dt.RehearsalTaskOutcome.REFUSED_RELEASE
        with pytest.raises(dl.RehearsalCompletionError) as refusal:
            dl.complete_rehearsal(
                replace(refused_launch, observed_exit_code=57),
                _line_document(refused),
                statement=statement,
            )
        assert refusal.value.defect is dl.RehearsalCompletionDefect.TASK_REFUSED
        with pytest.raises(dl.RehearsalCompletionError) as refusal:
            dl.complete_rehearsal(bound_launch, document, statement=other_statement)
        assert refusal.value.defect is dl.RehearsalCompletionDefect.STATEMENT_CONTRADICTS
        with pytest.raises(dl.RehearsalCompletionError) as refusal:
            dl.complete_rehearsal(
                bound_launch, dict(document, receipt_digest="00" * 32), statement=statement
            )
        assert refusal.value.defect is dl.RehearsalCompletionDefect.RECEIPT_REFUSED
        # A block whose identity was not verified is refused even under a valid digest.
        unverified = dict(document)
        unverified["rehearsal"] = dict(document["rehearsal"], identity_verified=False)
        body = {k: v for k, v in unverified.items() if k != "receipt_digest"}
        unverified["receipt_digest"] = sha256_hex(canonical_bytes(body))
        with pytest.raises(dl.RehearsalCompletionError) as refusal:
            dl.complete_rehearsal(bound_launch, unverified, statement=statement)
        assert refusal.value.defect is dl.RehearsalCompletionDefect.IDENTITY_NOT_VERIFIED
        assert t.files("rehearsal-record") == []

    def test_an_ambiguous_deletion_stays_open_until_the_control_settles_it(
        self, tmp_path: Path
    ) -> None:
        t, statement = _statement(tmp_path, "R8-LIST-AND-DELETE")
        attempt = _prerequisite_attempt(t)
        fakes = _launch_fakes()
        report, _ = _launch(t, statement, fakes)
        assert report.record is not None
        receipt, bound = _task_run_for(report.record, statement, FakePermissionClient(OK, TIMEOUT))
        record = dl.complete_rehearsal(bound, _line_document(receipt), statement=statement)
        assert record.outcome is dr.RehearsalOutcome.INCONCLUSIVE and record.possibly_deleted
        assert dr.derive_rehearsal(record, (), prerequisite_attempt=attempt)[0] is (
            dr.RehearsalStatus.CLEANUP_UNRESOLVED
        )
        # A cleanup that could not settle the key: RESIDUE; one that confirms it absent
        # settles the object and the reading is still INCONCLUSIVE -- the delete decided
        # nothing, and the control's removal is not the deletion role's.
        control = t.control(tmp_path)
        control.clock.seconds = fakes.clock.seconds + 60.0
        assert t.cleanup(control, [TIMEOUT, TIMEOUT]) == tool.EXIT_CLEANUP_UNRESOLVED
        status, reason = dr.derive_rehearsal(
            record, t.evidence().cleanups, prerequisite_attempt=attempt
        )
        assert status is dr.RehearsalStatus.RESIDUE and "could not confirm" in reason
        control.clock.seconds += 60.0
        assert t.cleanup(control, [NO_CONTENT, NOT_FOUND]) == tool.EXIT_EXECUTED
        status, _ = dr.derive_rehearsal(record, t.evidence().cleanups, prerequisite_attempt=attempt)
        assert status is dr.RehearsalStatus.INCONCLUSIVE

    def test_the_collector_collects_the_rehearsal_receipt_through_the_same_rules(
        self, tmp_path: Path
    ) -> None:
        t, statement = _statement(tmp_path)
        fakes = _launch_fakes()
        report, _ = _launch(t, statement, fakes)
        assert report.record is not None
        receipt, bound = _task_run_for(report.record, statement, FakePermissionClient(DENIED))
        expectation = bound.expectation()
        line = receipt.line()
        stream = f"{dr.REHEARSAL_STREAM_PREFIX}/{dr.REHEARSAL_CONTAINER}/{TASK_ID}"

        class _Pages:
            def __init__(self) -> None:
                self.streams: list[str] = []

            def get_log_events(
                self, *, log_group_name: str, log_stream_name: str, next_token: str | None
            ) -> rc.LogPage:
                self.streams.append(log_stream_name)
                if next_token == "end":
                    return rc.LogPage(status=200, events=(), next_forward_token="end")
                return rc.LogPage(
                    status=200, events=("bootstrap line", line), next_forward_token="end"
                )

        clock = FakeClock()
        pages = _Pages()
        collected = rc.collect_receipt(
            destination=_destination(),
            task_id=TASK_ID,
            verify=dt.rehearsal_receipt_verifier(expectation),
            client=pages,
            now=clock.now,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
        assert collected.outcome is rc.CollectionOutcome.COLLECTED
        assert collected.receipt_line == line and collected.log_stream == stream
        assert pages.streams and set(pages.streams) == {stream}
        # The same collector refuses another launch's expectation: RECEIPT_REJECTED with the
        # closed defect, the text not kept; and the admission rule reuses the kept line.
        rejected = rc.collect_receipt(
            destination=_destination(),
            task_id=TASK_ID,
            verify=dt.rehearsal_receipt_verifier(replace(expectation, task_id="f" * 32)),
            client=_Pages(),
            now=clock.now,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
        assert rejected.outcome is rc.CollectionOutcome.RECEIPT_REJECTED
        assert rejected.receipt_line is None
        assert rejected.rejection is not None and rejected.rejection.value == "BINDING_MISMATCH"
        document = collected.document(identity=bound.identity, launch_record_sha256=bound.digest)
        admission = rc.admit_collection_records(
            [canonical_bytes(document)],
            identity=bound.identity,
            launch_record_sha256=bound.digest,
            destination=_destination(),
            task_id=TASK_ID,
            verify=dt.rehearsal_receipt_verifier(expectation),
        )
        assert admission.reusable_line == line
        # The verified line completes the launch: the same record, from the collector's copy.
        record = dl.complete_rehearsal(
            bound, json.loads(line[len(RECEIPT_LINE_PREFIX) :]), statement=statement
        )
        assert record.outcome is dr.RehearsalOutcome.PASS and record.observed == (
            ObservedClass.DENIED_OTHER,
        )
        with pytest.raises(TypeError):
            rc.collect_receipt(
                destination=_destination(),
                task_id=TASK_ID,
                client=_Pages(),
                now=clock.now,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )
        with pytest.raises(ReceiptError):
            dt.rehearsal_receipt_verifier(expectation)(RECEIPT_LINE_PREFIX + "{not json")


# ---------------------------------------------------------------------------
# The path stays CLOSED
# ---------------------------------------------------------------------------


def test_the_public_path_is_closed_before_any_client_and_the_constants_agree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert dr.REHEARSAL_PATH_OPEN is False and dr.rehearsal_blocked()
    assert dr.REHEARSAL_CONTAINER == rc.REHEARSAL_CONTAINER == "deletion-rehearsal"
    assert dr.REHEARSAL_STREAM_PREFIX == "production-" + dr.REHEARSAL_CONTAINER
    assert set(dt.REHEARSAL_EXIT_STATUS.values()).isdisjoint({0, 2, 3, 4, 5, 6, 41, 42, 43, 44})
    t = _with_prerequisite(tmp_path)
    capsys.readouterr()
    before = (list(t.constructions), list(t.identity_calls), list(t.gate_calls))

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("no client may be built while the path is closed")

    for argv in (
        ("--rehearse-deletion", "R8-GET"),
        ("--complete-rehearsal", "R8-GET", "--receipt-lines", str(tmp_path / "absent")),
        ("--collect-rehearsal-receipt", "R8-GET", tool.COLLECT_FLAG),
    ):
        assert t.main(*argv, *t.base(), tool.AUTHORIZATION_FLAG, client_factory=refuse) == (
            tool.EXIT_REFUSED_REHEARSAL_CLOSED
        ), argv
        assert tool.SENTENCES["refused_rehearsal_closed"] in capsys.readouterr().out
    assert (t.constructions, t.identity_calls, t.gate_calls) == before
    # Naming the rehearsal inputs alone is refused the same way, before the parser's other
    # rules: nothing about the rehearsal is read while the path is closed.
    assert t.main("--rehearsal-inputs", str(tmp_path / "absent"), *t.base()) == (
        tool.EXIT_REFUSED_REHEARSAL_CLOSED
    )
