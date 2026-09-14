"""The owner-side launch tool (proposed ADR-0045), on fakes only.

Refuses by default; every record parsed closed; the human bootstrap under both profiles
before any adapter; one launch, one ledger row, sanitized evidence; a misplaced task
stopped with no release; an ambiguous outcome recorded without a retry; a consumed
identity never launched again; the receipt the owner hands back completes the row.
**Mocked results are not AWS verification**: this tool has never run against AWS.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_build import RUN_1, RUN_1_AT, configuration, slice_for_run
from fixtures.production_entry import ORIGIN_ADDRESSES, AcquisitionHarness
from fixtures.production_launch import (
    ACQ,
    BLD,
    FakeClients,
    FakeSts,
    authorization_document,
    launch_inputs_document,
    ledger_document,
    ledger_row,
)
from fixtures.production_runtime import (
    BUILD_ID,
    CANARIES,
    COMMIT,
    CONFIGURATION_DIGEST,
    IMAGE_DIGEST,
    NOW,
    OTHER_SECURITY_GROUP,
    RUN_ID,
    TASK_ARN,
    TREE,
    FakeClock,
    FakeEc2,
    FakeEcs,
    binding_document,
    compiled_task,
    encode,
    human_identity_arn,
    interface_entry,
    revision_arn,
    slice_document,
    task_entry,
    verification_revision_arn,
)
from kalpamani.data.production.sharadar import launch_records as lr
from kalpamani.data.production.sharadar.compiled import build_compiled_configuration
from kalpamani.data.production.sharadar.entry import TaskEntry, TaskOutcome
from kalpamani.data.production.sharadar.inputs import input_digest, parse_slice
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for
from kalpamani.data.qualify.sharadar import runtime_binding as rb

pytestmark = pytest.mark.unit

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
SCRIPT: Final = REPO_ROOT / "scripts" / "production_launch.py"
SOURCE: Final = SCRIPT.read_text(encoding="utf-8")
CURRENT: Final = "S-1-5-21-0-0-0-1001"
VERIFY_ID: Final = "verify-" + RUN_ID


def _module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        pytest.fail("the launch tool could not be loaded")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses with postponed annotations resolve their module through sys.modules.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


launch = _module("production_launch", SCRIPT)


def _security(_path: Path) -> rb.FileSecurity:
    return rb.FileSecurity(
        current_principal=CURRENT,
        owner=CURRENT,
        inheritance_disabled=True,
        allow_principals=(CURRENT,),
        deny_principals=(),
    )


def _compiled(entry: TaskEntry, **overrides: Any) -> bytes:
    fields_: dict[str, Any] = {
        "entry": entry,
        "code_commit": COMMIT,
        "code_tree": TREE,
        "generated_at": NOW,
    }
    if entry is TaskEntry.ACQUISITION:
        fields_["secret_name"] = "synthetic/production/sharadar"  # noqa: S105 - a name
        fields_["origin_addresses"] = sorted(ORIGIN_ADDRESSES)
    elif entry is TaskEntry.BUILD:
        fields_["build_configuration"] = configuration()
    else:
        fields_["origin_addresses"] = sorted(ORIGIN_ADDRESSES)
    fields_.update(overrides)
    return build_compiled_configuration(**fields_)


class _Scenario:
    """Owner records under a synthetic private root, fakes, and one invocation."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        actor: ProductionActor = ACQ,
        kind: str = "production",
        identity: str | None = None,
        ledger_rows: list[dict[str, Any]] | None = None,
        exit_code: int | None = 0,
        misplace: bool = False,
        never_stops: bool = False,
    ) -> None:
        self.actor = actor
        self.kind = kind
        self.root = tmp_path / "KalpaMani" / "private"
        self.root.mkdir(parents=True)
        default_identity = RUN_ID if actor is ACQ else BUILD_ID
        if kind == "verification":
            default_identity = "verify-" + default_identity
        self.identity = default_identity if identity is None else identity
        self.records = self.root / "records"
        self.ledger = self.root / "ledger.json"
        rows = (
            ledger_rows
            if ledger_rows is not None
            else ([ledger_row(RUN_ID)] if actor is BLD else [])
        )
        self.ledger.write_bytes(encode(ledger_document(rows)))
        self.inputs = self.root / "launch-inputs.json"
        self.inputs.write_bytes(encode(launch_inputs_document()))
        self.authorization = self.root / "authorization.json"
        self.authorization.write_bytes(
            encode(authorization_document(actor=actor, kind=kind, identity=self.identity))
        )
        self.slice = self.root / "slice.json"
        self.slice.write_bytes(encode(slice_document()))
        self.binding = self.root / "binding.json"
        self.binding.write_bytes(encode(binding_document(actor)))
        self.environment = {constants_for(actor).binding_env_var: str(self.binding)}.get
        self.production_configuration = self.root / "production.json"
        self.verification_configuration = self.root / "verification.json"
        self.acquisition_configuration = self.root / "acquisition.json"
        production_entry = TaskEntry.ACQUISITION if actor is ACQ else TaskEntry.BUILD
        verify_entry = TaskEntry.ACQUISITION_VERIFY if actor is ACQ else TaskEntry.BUILD_VERIFY
        self.production_configuration.write_bytes(_compiled(production_entry))
        self.verification_configuration.write_bytes(_compiled(verify_entry))
        self.acquisition_configuration.write_bytes(_compiled(TaskEntry.ACQUISITION))
        # The launch-inputs record registers the verification file's digest and commit.
        if kind == "verification":
            from kalpamani.data.production.sharadar.compiled import configuration_digest_of

            document = launch_inputs_document()
            document["actors"][actor.value]["verification"]["configuration_digest"] = (
                configuration_digest_of(self.verification_configuration.read_bytes())
            )
            self.inputs.write_bytes(encode(document))

        revision = (
            verification_revision_arn(actor) if kind == "verification" else revision_arn(actor)
        )

        def entry(status: str, **kw: Any) -> dict[str, Any]:
            document = task_entry(actor, status=status, **kw)
            document["taskDefinitionArn"] = revision
            return document

        descriptions = [
            entry("PENDING", attachment_status="ATTACHED"),
            entry("RUNNING", attachment_status="ATTACHED"),
        ]
        if never_stops:
            descriptions.append(entry("RUNNING", attachment_status="ATTACHED"))
        else:
            descriptions.append(entry("STOPPED", attachment_status="ATTACHED", exit_code=exit_code))
        self.ecs = FakeEcs(
            run_response={
                "tasks": [
                    entry(
                        "PROVISIONING",
                        attachment_status="PRECREATED",
                        interface_id=None,
                        subnet_id=None,
                    )
                ],
                "failures": [],
            },
            descriptions=descriptions,
        )
        public_ip = "203.0.113.10" if actor is ACQ else None
        self.ec2 = FakeEc2(
            interface=(
                interface_entry(public_ip=public_ip, groups=(OTHER_SECURITY_GROUP,))
                if misplace
                else interface_entry(public_ip=public_ip)
            )
        )
        self.clients = FakeClients(actor=actor, ecs_fake=self.ecs, ec2_fake=self.ec2)
        self.clock = FakeClock()

    def argv(self, *extra: str, authorized: bool = True) -> list[str]:
        argv = [
            "--actor",
            self.actor.value,
            "--kind",
            self.kind,
            "--identity",
            self.identity,
            "--ledger",
            str(self.ledger),
            "--launch-inputs",
            str(self.inputs),
            "--records-dir",
            str(self.records),
            "--authorization",
            str(self.authorization),
        ]
        if self.actor is ACQ:
            argv += ["--slice", str(self.slice)]
        else:
            argv += ["--run-identity", RUN_ID]
        if self.kind == "verification":
            argv += [
                "--production-configuration",
                str(self.production_configuration),
                "--verification-configuration",
                str(self.verification_configuration),
            ]
            if self.actor is BLD:
                argv += ["--acquisition-configuration", str(self.acquisition_configuration)]
        if authorized:
            argv.append(launch.AUTHORIZATION_FLAG)
        return argv + list(extra)

    def run(self, *extra: str, authorized: bool = True, **overrides: Any) -> int:
        fields_: dict[str, Any] = {
            "clients": self.clients,
            "environment": self.environment,
            "now": self.clock.now,
            "monotonic": self.clock.monotonic,
            "sleep": self.clock.sleep,
            "root_source": lambda: self.root,
            "security_of": _security,
        }
        fields_.update(overrides)
        exit_code: int = launch.main(self.argv(*extra, authorized=authorized), **fields_)
        return exit_code

    def ledger_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = json.loads(self.ledger.read_bytes())["rows"]
        return rows

    def evidence(self) -> dict[str, Any]:
        files = sorted(self.records.glob("launch-evidence-*.json"))
        assert len(files) == 1
        document: dict[str, Any] = json.loads(files[0].read_bytes())
        return document

    def record(self) -> dict[str, Any] | None:
        files = sorted(self.records.glob("launch-record-*.json"))
        assert len(files) <= 1
        return None if not files else json.loads(files[0].read_bytes())


# ---------------------------------------------------------------------------
# Dormant on import, refused by default
# ---------------------------------------------------------------------------


def test_no_kalpamani_or_sdk_import_happens_at_module_level() -> None:
    for node in ast.parse(SOURCE).body:
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith(("kalpamani", "boto3", "botocore"))
        if isinstance(node, ast.Import):
            assert not any(
                a.name.startswith(("kalpamani", "boto3", "botocore")) for a in node.names
            )


def test_the_sdk_is_named_only_inside_the_real_client_factory() -> None:
    tree = ast.parse(SOURCE)
    owners: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for inner in ast.walk(node):
                if isinstance(inner, ast.ImportFrom | ast.Import):
                    names = (
                        [inner.module or ""]
                        if isinstance(inner, ast.ImportFrom)
                        else [a.name for a in inner.names]
                    )
                    if any(n.startswith(("boto3", "botocore")) for n in names):
                        owners.append(node.name)
    assert set(owners) == {"_Boto3Clients"}


@pytest.mark.parametrize("flag", sorted(launch.REFUSED_FLAGS))
def test_refused_spellings_are_refused_before_parsing(
    tmp_path: Path, flag: str, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _Scenario(tmp_path)
    assert scenario.run(flag) == launch.EXIT_REFUSED_ARGUMENTS
    assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_arguments"]
    assert scenario.clients.constructions == []


def test_without_the_flag_the_launch_is_prepared_and_nothing_is_constructed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _Scenario(tmp_path)
    assert scenario.run(authorized=False) == launch.EXIT_PREPARED
    out = capsys.readouterr().out
    assert launch.SENTENCES["prepared"] in out and "actor=acquisition kind=production" in out
    assert scenario.clients.constructions == [] and scenario.ecs.calls == []
    assert scenario.ledger_rows() == [] and not scenario.records.exists()
    for canary in CANARIES:
        assert canary not in out
    assert RUN_ID not in out


@pytest.mark.parametrize(
    "extra",
    [
        ["--run-identity", RUN_ID],  # an acquisition launch takes a slice, not run identities
        ["--production-configuration", "x"],  # configuration files belong to verification
        ["--complete-row"],  # completion needs its record and receipt
        ["--complete-row", "--launch-record", "x", "--receipt-lines", "y"],  # and no flag
    ],
)
def test_contradictory_arguments_are_refused(tmp_path: Path, extra: list[str]) -> None:
    scenario = _Scenario(tmp_path)
    assert scenario.run(*extra) == launch.EXIT_REFUSED_ARGUMENTS
    assert scenario.clients.constructions == []


def test_records_outside_the_private_root_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _Scenario(tmp_path)
    outside = tmp_path / "elsewhere.json"
    outside.write_bytes(scenario.ledger.read_bytes())
    argv = scenario.argv()
    argv[argv.index("--ledger") + 1] = str(outside)
    assert launch.main(argv, clients=scenario.clients, root_source=lambda: scenario.root) == (
        launch.EXIT_REFUSED_CONTAINMENT
    )
    assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_containment"]
    assert scenario.clients.constructions == []


# ---------------------------------------------------------------------------
# Records and authorization
# ---------------------------------------------------------------------------


def test_a_consumed_identity_is_refused_for_either_kind(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, ledger_rows=[ledger_row(RUN_ID, outcome="REFUSED")])
    assert scenario.run() == launch.EXIT_REFUSED_RECORDS
    assert scenario.clients.constructions == [] and scenario.ecs.calls == []
    verify = _Scenario(
        tmp_path / "v",
        kind="verification",
        ledger_rows=[ledger_row(VERIFY_ID, kind="verification", outcome="VERIFIED")],
    )
    assert verify.run() == launch.EXIT_REFUSED_RECORDS
    assert verify.clients.constructions == []


def test_a_verification_launch_never_takes_a_production_identity(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, kind="verification", identity=RUN_ID)
    scenario.authorization.write_bytes(
        encode(authorization_document(actor=ACQ, kind="verification", identity=RUN_ID))
    )
    assert scenario.run() == launch.EXIT_REFUSED_RECORDS
    assert scenario.clients.constructions == []


def test_the_authorization_must_name_this_launch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _Scenario(tmp_path)
    scenario.authorization.write_bytes(
        encode(authorization_document(actor=ACQ, kind="verification", identity=RUN_ID))
    )
    assert scenario.run() == launch.EXIT_REFUSED_AUTHORIZATION
    assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_authorization"]
    assert scenario.clients.constructions == []
    # Without a record at all, the flag alone is not authorization.
    argv = scenario.argv()
    index = argv.index("--authorization")
    del argv[index : index + 2]
    assert launch.main(argv, clients=scenario.clients, root_source=lambda: scenario.root) == (
        launch.EXIT_REFUSED_ARGUMENTS
    )


def test_a_non_equivalent_verification_configuration_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _Scenario(tmp_path, kind="verification")
    scenario.verification_configuration.write_bytes(
        _compiled(TaskEntry.ACQUISITION_VERIFY, origin_addresses=["198.51.100.7"])
    )
    assert scenario.run() == launch.EXIT_REFUSED_EQUIVALENCE
    assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_equivalence"]
    assert scenario.clients.constructions == []


def test_a_verification_file_the_record_did_not_register_is_refused(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, kind="verification")
    # Equivalent to production, but not the file whose digest the launch inputs register.
    scenario.verification_configuration.write_bytes(
        _compiled(TaskEntry.ACQUISITION_VERIFY, generated_at=RUN_1_AT)
    )
    assert scenario.run() == launch.EXIT_REFUSED_EQUIVALENCE
    assert scenario.clients.constructions == []


# ---------------------------------------------------------------------------
# The authorized branch
# ---------------------------------------------------------------------------


def test_a_refused_bootstrap_stops_before_any_adapter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _Scenario(tmp_path)
    scenario.clients.launcher_sts = FakeSts(human_identity_arn(ACQ))  # the wrong role
    assert scenario.run() == launch.EXIT_REFUSED_BOOTSTRAP
    assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_bootstrap"]
    assert [s for s, _ in scenario.clients.constructions] == ["sts", "sts"]
    assert scenario.ecs.calls == [] and scenario.ledger_rows() == []


@pytest.mark.parametrize("actor", (ACQ, BLD), ids=lambda a: a.value)
@pytest.mark.parametrize("kind", ("production", "verification"))
def test_one_launch_one_row_and_sanitized_evidence(
    tmp_path: Path, actor: ProductionActor, kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = 18 if kind == "verification" else 0
    scenario = _Scenario(tmp_path, actor=actor, kind=kind, exit_code=exit_code)
    assert scenario.run() == launch.EXIT_LAUNCH_TERMINAL
    out = capsys.readouterr().out
    assert launch.SENTENCES["launched"] in out
    for canary in CANARIES:
        assert canary not in out
    constants = constants_for(actor)
    # Exactly one RunTask, under the launcher profile; the input under the human one.
    assert len(scenario.ecs.names("run_task")) == 1
    assert scenario.clients.human_ssm.names("put_parameter") == [constants.input_parameter]
    assert scenario.clients.launcher_ssm.names("put_parameter") == [constants.release_parameter]
    assert scenario.clients.human_ssm.values == {} and scenario.clients.launcher_ssm.values == {}
    assert {p for _, p in scenario.clients.constructions} == {
        constants.profile,
        constants.launcher_profile,
    }
    rows = scenario.ledger_rows()
    seeded = 0 if actor is ACQ else 1  # a build launches over one completed acquisition row
    assert len(rows) == seeded + 1 and rows[-1]["identity"] == scenario.identity
    assert rows[-1]["kind"] == kind and rows[-1]["evidence"] == "EXIT_CODE_ONLY"
    assert rows[-1]["outcome"] == ("VERIFIED" if kind == "verification" else "COMPLETED")
    if actor is ACQ:
        assert rows[-1]["slice"] == slice_document()
    else:
        assert rows[-1]["slice"] is None
    evidence = scenario.evidence()
    assert evidence["outcome"] == "TASK_TERMINAL" and evidence["exit_codes"] == [exit_code]
    assert evidence["counts"]["run_task"] == 1 and evidence["cleanup_failures"] == []
    text = json.dumps(evidence)
    for canary in CANARIES:
        assert canary not in text
    assert scenario.identity not in text and "arn:" not in text
    record = scenario.record()
    assert record is not None and record["identity"] == scenario.identity
    assert record["task_arn"] == TASK_ARN and record["kind"] == kind
    expected_revision = (
        verification_revision_arn(actor) if kind == "verification" else revision_arn(actor)
    )
    assert record["task_definition_arn"] == expected_revision
    # The row is provisional: it is not buildable, and the tool refuses to launch it again.
    ledger = lr.parse_owner_ledger(scenario.ledger.read_bytes())
    row = ledger.row(scenario.identity)
    assert row is not None and not row.buildable
    scenario.records.mkdir(exist_ok=True)
    assert scenario.run() == launch.EXIT_REFUSED_RECORDS
    assert len(scenario.ecs.names("run_task")) == 1


def test_a_verification_image_that_exits_zero_is_recorded_as_halted(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, kind="verification", exit_code=0)
    assert scenario.run() == launch.EXIT_LAUNCH_TERMINAL
    assert scenario.ledger_rows()[0]["outcome"] == "HALTED"


def test_a_misplaced_task_is_stopped_with_no_release_and_the_row_says_so(
    tmp_path: Path,
) -> None:
    scenario = _Scenario(tmp_path, misplace=True)
    assert scenario.run() == launch.EXIT_LAUNCH_NOT_TERMINAL
    assert len(scenario.ecs.names("stop_task")) == 1
    assert scenario.ecs.names("stop_task")[0]["task"] == TASK_ARN
    assert scenario.clients.launcher_ssm.names("put_parameter") == []
    evidence = scenario.evidence()
    assert evidence["outcome"] == "MISPLACED" and evidence["incident"] == "SECURITY_GROUP_MISMATCH"
    rows = scenario.ledger_rows()
    assert rows[0]["outcome"] == "MISPLACED" and rows[0]["evidence"] == "EXIT_CODE_ONLY"
    assert scenario.record() is not None  # a task started; the record holds it


def test_an_ambiguous_outcome_is_recorded_once_and_never_retried(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, never_stops=True)
    assert scenario.run() == launch.EXIT_LAUNCH_NOT_TERMINAL
    evidence = scenario.evidence()
    assert evidence["outcome"] == "OBSERVATION_TIMEOUT" and evidence["exit_codes"] == []
    assert evidence["counts"]["run_task"] == 1
    assert scenario.ledger_rows()[0]["outcome"] == "HALTED"
    # The identity is consumed: a second invocation refuses before any client exists.
    before = list(scenario.clients.constructions)
    assert scenario.run() == launch.EXIT_REFUSED_RECORDS
    assert scenario.clients.constructions == before
    assert len(scenario.ecs.names("run_task")) == 1


def test_a_launch_that_never_started_still_consumes_the_identity(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    scenario.ecs.run_failure = "AccessDeniedException"
    assert scenario.run() == launch.EXIT_LAUNCH_NOT_TERMINAL
    evidence = scenario.evidence()
    assert evidence["outcome"] == "REFUSED_LAUNCH" and evidence["task_started"] is False
    assert scenario.record() is None
    rows = scenario.ledger_rows()
    assert rows[0]["outcome"] == "REFUSED" and rows[0]["identity"] == RUN_ID
    # The input was deleted under the human profile: the create-only guard is clean.
    assert scenario.clients.human_ssm.values == {}


def test_cleanup_failures_are_visible_beside_the_outcome(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    constants = constants_for(ACQ)
    scenario.clients.human_ssm.delete_failures[constants.input_parameter] = "AccessDeniedException"
    assert scenario.run() == launch.EXIT_LAUNCH_TERMINAL
    evidence = scenario.evidence()
    assert evidence["outcome"] == "TASK_TERMINAL"
    assert evidence["cleanup_failures"] == ["DELETE_INPUT:ACCESS_DENIED"]
    assert scenario.ledger_rows()[0]["outcome"] == "COMPLETED"


def test_the_workstation_client_configuration_is_one_attempt_with_finite_timeouts() -> None:
    config = launch.workstation_client_config()
    assert config["retries"] == {"total_max_attempts": 1, "mode": "standard"}
    assert config["connect_timeout"] > 0 and config["read_timeout"] > 0


# ---------------------------------------------------------------------------
# Completing the row from the receipt the owner hands back
# ---------------------------------------------------------------------------


class TestCompleteRow:
    def _completed_scenario(self, tmp_path: Path) -> tuple[_Scenario, Path, Path]:
        from kalpamani.data.production.sharadar.identities import LedgerSpentIdentities

        harness = AcquisitionHarness(spent=LedgerSpentIdentities([]))
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.COMPLETED
        scenario = _Scenario(tmp_path, identity=RUN_1)
        record = lr.LaunchRecord(
            entry=TaskEntry.ACQUISITION,
            kind=lr.LaunchKind.PRODUCTION,
            identity=RUN_1,
            task_arn=TASK_ARN,
            task_definition_arn=revision_arn(ACQ),
            image_digest=IMAGE_DIGEST,
            configuration_digest=CONFIGURATION_DIGEST,
            code_commit=compiled_task(ACQ).code_commit,
            input_digest=input_digest(harness.input_bytes),
            slice=parse_slice(slice_for_run(1)),
            plan_digest="ab" * 32,
            launched_at=RUN_1_AT,
        )
        ledger = lr.append_row(
            lr.OwnerLedger(rows=()),
            lr.provisional_ledger_row(record, outcome="COMPLETED", completed_at=RUN_1_AT),
        )
        scenario.ledger.write_bytes(encode(ledger.document()))
        record_path = scenario.root / "launch-record.json"
        record_path.write_bytes(encode(record.document()))
        lines_path = scenario.root / "receipt.txt"
        lines_path.write_text("\n".join(receipt.render()) + "\n", encoding="utf-8")
        return scenario, record_path, lines_path

    def _argv(self, scenario: _Scenario, record: Path, lines: Path) -> list[str]:
        return [
            "--actor",
            "acquisition",
            "--kind",
            "production",
            "--identity",
            RUN_1,
            "--ledger",
            str(scenario.ledger),
            "--launch-inputs",
            str(scenario.inputs),
            "--records-dir",
            str(scenario.records),
            "--complete-row",
            "--launch-record",
            str(record),
            "--receipt-lines",
            str(lines),
        ]

    def test_the_verified_receipt_completes_the_row(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        scenario, record, lines = self._completed_scenario(tmp_path)
        argv = self._argv(scenario, record, lines)
        assert launch.main(argv, clients=scenario.clients, root_source=lambda: scenario.root) == (
            launch.EXIT_ROW_COMPLETED
        )
        assert capsys.readouterr().out.strip() == launch.SENTENCES["row_completed"]
        row = lr.parse_owner_ledger(scenario.ledger.read_bytes()).row(RUN_1)
        assert row is not None and row.buildable
        assert scenario.clients.constructions == []
        # Never twice.
        assert launch.main(argv, clients=scenario.clients, root_source=lambda: scenario.root) == (
            launch.EXIT_REFUSED_RECORDS
        )

    def test_a_receipt_that_does_not_belong_to_the_record_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        scenario, record, lines = self._completed_scenario(tmp_path)
        document = json.loads(record.read_bytes())
        document["input_digest"] = "cd" * 32
        record.write_bytes(encode(document))
        ledger = json.loads(scenario.ledger.read_bytes())
        scenario.ledger.write_bytes(encode(ledger))
        assert (
            launch.main(
                self._argv(scenario, record, lines),
                clients=scenario.clients,
                root_source=lambda: scenario.root,
            )
            == launch.EXIT_REFUSED_RECORDS
        )
        assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_records"]
        row = lr.parse_owner_ledger(scenario.ledger.read_bytes()).row(RUN_1)
        assert row is not None and row.evidence is lr.LedgerEvidence.EXIT_CODE_ONLY

    def test_the_arguments_must_name_the_recorded_launch(self, tmp_path: Path) -> None:
        scenario, record, lines = self._completed_scenario(tmp_path)
        argv = self._argv(scenario, record, lines)
        argv[argv.index("--identity") + 1] = RUN_ID
        assert launch.main(argv, clients=scenario.clients, root_source=lambda: scenario.root) == (
            launch.EXIT_REFUSED_RECORDS
        )
