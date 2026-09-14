"""The owner-side launch tool (proposed ADR-0045), on fakes only.

Refuses by default; every record parsed closed; the specification the owner authorized is
the one that runs; the identity is reserved durably before any client; the human bootstrap
under both profiles before any adapter; one launch, one ledger row written atomically,
sanitized evidence under names that cannot collide; a misplaced task stopped with no
release; an ambiguous outcome recorded without a retry; an interrupted attempt recovered
and never relaunched; the receipt the owner hands back completes the row; the R-2 verdict
derived from evidence and recorded. **Mocked results are not AWS verification**: this tool
has never run against AWS.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_build import RUN_1, RUN_1_AT, configuration, slice_for_run
from fixtures.production_entry import ORIGIN_ADDRESSES, AcquisitionHarness, VerificationHarness
from fixtures.production_launch import (
    ACQ,
    BLD,
    FakeClients,
    FakeSts,
    authorization_document,
    launch_inputs_document,
    ledger_document,
    ledger_row,
    specification_digest_for,
)
from fixtures.production_runtime import (
    BUILD_ID,
    CANARIES,
    COMMIT,
    IMAGE_DIGEST,
    INTERFACE_ID,
    NOW,
    OTHER_RUN_ID,
    OTHER_SECURITY_GROUP,
    RUN_ID,
    SECURITY_GROUPS,
    SUBNET_ID,
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
from kalpamani.data.production.sharadar import launch_store as ls
from kalpamani.data.production.sharadar import probe as pp
from kalpamani.data.production.sharadar.compiled import (
    build_compiled_configuration,
    configuration_digest_of,
)
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
    """Owner records under a synthetic private root, fakes, and one invocation.

    The launch-inputs record registers the digests of the three configuration files the
    scenario writes, so every target is bound to a real file; the authorization names the
    specification those records produce.
    """

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
        self.root.mkdir(parents=True, exist_ok=True)
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
        self.inputs = self.root / "launch-inputs.json"
        self.register_targets()
        self.authorization = self.root / "authorization.json"
        self.authorize()

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

    def inputs_document(self) -> dict[str, Any]:
        """The launch-inputs record registering this scenario's three configuration files."""
        document = launch_inputs_document()
        actors = document["actors"]
        actors[self.actor.value]["production"]["configuration_digest"] = configuration_digest_of(
            self.production_configuration.read_bytes()
        )
        actors[self.actor.value]["verification"]["configuration_digest"] = configuration_digest_of(
            self.verification_configuration.read_bytes()
        )
        actors["acquisition"]["production"]["configuration_digest"] = configuration_digest_of(
            self.acquisition_configuration.read_bytes()
            if self.actor is BLD
            else self.production_configuration.read_bytes()
        )
        return document

    def register_targets(self, **overrides: Any) -> None:
        document = self.inputs_document()
        document.update(overrides)
        self.inputs.write_bytes(encode(document))

    def specification_digest(self) -> str:
        try:
            return specification_digest_for(
                actor=self.actor,
                kind=self.kind,
                identity=self.identity,
                ledger=json.loads(self.ledger.read_bytes()),
                inputs=json.loads(self.inputs.read_bytes()),
                slice_doc=json.loads(self.slice.read_bytes()) if self.actor is ACQ else None,
            )
        except lr.LaunchRecordError:
            # A scenario whose records refuse the launch has no specification; the
            # authorization then names a digest nothing can match.
            return "00" * 32

    def authorize(self, **overrides: Any) -> None:
        """Write an authorization naming this scenario's specification (or overrides)."""
        document = authorization_document(
            actor=self.actor,
            kind=self.kind,
            identity=self.identity,
            specification_digest=self.specification_digest(),
        )
        document.update(overrides)
        self.authorization.write_bytes(encode(document))

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

    def fields(self, **overrides: Any) -> dict[str, Any]:
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
        return fields_

    def run(self, *extra: str, authorized: bool = True, **overrides: Any) -> int:
        exit_code: int = launch.main(
            self.argv(*extra, authorized=authorized), **self.fields(**overrides)
        )
        return exit_code

    def mode(self, *argv: str, **overrides: Any) -> int:
        """A completion, recovery or verdict invocation on this scenario's records."""
        base = [
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
        ]
        exit_code: int = launch.main([*base, *argv], **self.fields(**overrides))
        return exit_code

    def ledger_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = json.loads(self.ledger.read_bytes())["rows"]
        return rows

    def files(self, prefix: str) -> list[Path]:
        return sorted(self.records.glob(f"{prefix}-*.json")) if self.records.exists() else []

    def evidence(self) -> dict[str, Any]:
        files = self.files("launch-evidence")
        assert len(files) == 1
        document: dict[str, Any] = json.loads(files[0].read_bytes())
        return document

    def record(self) -> dict[str, Any] | None:
        files = self.files("launch-record")
        assert len(files) <= 1
        return None if not files else json.loads(files[0].read_bytes())

    def reservation(self) -> dict[str, Any] | None:
        path = self.records / ls.RESERVATIONS_DIRECTORY / f"{self.identity}.json"
        return None if not path.exists() else json.loads(path.read_bytes())

    @property
    def lock(self) -> Path:
        return self.ledger.with_name("ledger.json.lock")


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


def test_without_the_flag_the_specification_is_written_and_nothing_is_constructed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _Scenario(tmp_path)
    assert scenario.run(authorized=False) == launch.EXIT_PREPARED
    out = capsys.readouterr().out
    assert launch.SENTENCES["prepared"] in out and "actor=acquisition kind=production" in out
    assert f"specification_digest={scenario.specification_digest()}" in out
    assert scenario.clients.constructions == [] and scenario.ecs.calls == []
    assert scenario.ledger_rows() == [] and scenario.reservation() is None
    specifications = scenario.files("launch-specification")
    assert len(specifications) == 1
    document = json.loads(specifications[0].read_bytes())
    assert document["contract_id"] == lr.SPECIFICATION_CONTRACT_ID
    assert document["identity"] == RUN_ID and document["workload"]["slice"] == slice_document()
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
        ["--recover"],  # recovery never launches
        ["--reachability-evidence", "x"],  # evidence belongs to the verdict mode
        ["--isolation-verdict", "--launch-record", "x", "--receipt-lines", "y"],  # and no flag
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
    assert scenario.run() == launch.EXIT_REFUSED_RECORDS
    assert scenario.clients.constructions == []


class TestAuthorizationBinding:
    """PR #104 review finding 2: the authorization binds the whole specification."""

    def test_the_flag_alone_and_a_mismatched_authorization_refuse(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        scenario = _Scenario(tmp_path)
        scenario.authorize(kind="verification")
        assert scenario.run() == launch.EXIT_REFUSED_AUTHORIZATION
        assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_authorization"]
        assert scenario.clients.constructions == [] and scenario.reservation() is None
        argv = scenario.argv()
        index = argv.index("--authorization")
        del argv[index : index + 2]
        assert launch.main(argv, clients=scenario.clients, root_source=lambda: scenario.root) == (
            launch.EXIT_REFUSED_ARGUMENTS
        )

    def test_a_changed_slice_under_the_same_authorization_refuses(self, tmp_path: Path) -> None:
        scenario = _Scenario(tmp_path)
        scenario.slice.write_bytes(
            encode(
                slice_document(windows={"actions": "2024-01-01/2024-12-31", "tickers": "SNAPSHOT"})
            )
        )
        assert scenario.run() == launch.EXIT_REFUSED_AUTHORIZATION
        assert scenario.clients.constructions == [] and scenario.reservation() is None
        assert scenario.ledger_rows() == []

    def test_a_changed_registered_target_under_the_same_authorization_refuses(
        self, tmp_path: Path
    ) -> None:
        scenario = _Scenario(tmp_path)
        document = scenario.inputs_document()
        document["actors"]["acquisition"]["production"]["image_digest"] = "sha256:" + "00" * 32
        document["actors"]["acquisition"]["production"]["task_definition"]["image_digest"] = (
            "sha256:" + "00" * 32
        )
        scenario.inputs.write_bytes(encode(document))
        assert scenario.run() == launch.EXIT_REFUSED_AUTHORIZATION
        assert scenario.clients.constructions == []

    def test_a_changed_build_run_selection_under_the_same_authorization_refuses(
        self, tmp_path: Path
    ) -> None:
        scenario = _Scenario(
            tmp_path, actor=BLD, ledger_rows=[ledger_row(RUN_ID), ledger_row(OTHER_RUN_ID)]
        )
        argv = scenario.argv()
        argv[argv.index("--run-identity") + 1] = OTHER_RUN_ID
        assert launch.main(argv, **scenario.fields()) == launch.EXIT_REFUSED_AUTHORIZATION
        assert scenario.clients.constructions == []

    def test_a_changed_placement_under_the_same_authorization_refuses(self, tmp_path: Path) -> None:
        scenario = _Scenario(tmp_path)
        scenario.register_targets(platform_version="1.3.0")
        assert scenario.run() == launch.EXIT_REFUSED_AUTHORIZATION
        assert scenario.clients.constructions == []

    def test_freshness_is_revalidated_before_the_launch(self, tmp_path: Path) -> None:
        scenario = _Scenario(tmp_path)
        scenario.authorize(expires_at=(NOW + timedelta(seconds=3)).isoformat())
        # Valid at preparation and admission; the bootstrap advances the clock past expiry.
        real_sts = scenario.clients.sts

        def slow_sts(profile: str) -> Any:
            scenario.clock.seconds += 2.0
            return real_sts(profile)

        scenario.clients.sts = slow_sts  # type: ignore[method-assign]
        assert scenario.run() == launch.EXIT_REFUSED_AUTHORIZATION
        assert scenario.ecs.calls == []
        # The identity was reserved before the bootstrap, so it is consumed even so.
        assert scenario.reservation() is not None and scenario.ledger_rows() == []

    def test_a_production_launch_needs_the_r3_reference_and_a_verification_does_not(
        self, tmp_path: Path
    ) -> None:
        scenario = _Scenario(tmp_path)
        scenario.register_targets(r3_verification_digest=None)
        assert scenario.run() == launch.EXIT_REFUSED_RECORDS
        assert scenario.clients.constructions == []
        verify = _Scenario(tmp_path / "v", kind="verification", exit_code=18)
        verify.register_targets(r3_verification_digest=None)
        verify.authorize()
        assert verify.run() == launch.EXIT_LAUNCH_TERMINAL
        assert len(verify.ecs.names("run_task")) == 1


# ---------------------------------------------------------------------------
# Equivalence, bound to the registered counterparts (finding 3)
# ---------------------------------------------------------------------------


def test_a_non_equivalent_verification_configuration_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _Scenario(tmp_path, kind="verification")
    scenario.verification_configuration.write_bytes(
        _compiled(TaskEntry.ACQUISITION_VERIFY, origin_addresses=["198.51.100.7"])
    )
    scenario.register_targets()
    scenario.authorize()
    assert scenario.run() == launch.EXIT_REFUSED_EQUIVALENCE
    assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_equivalence"]
    assert scenario.clients.constructions == [] and scenario.reservation() is None


def test_an_unrelated_production_file_is_refused_against_its_registered_target(
    tmp_path: Path,
) -> None:
    """PR #104 review finding 3: before the fix this launched (exit 0)."""
    scenario = _Scenario(tmp_path, kind="verification")
    unrelated = ["198.51.100.20", "198.51.100.21"]
    scenario.production_configuration.write_bytes(
        _compiled(TaskEntry.ACQUISITION, origin_addresses=unrelated)
    )
    scenario.verification_configuration.write_bytes(
        _compiled(TaskEntry.ACQUISITION_VERIFY, origin_addresses=unrelated)
    )
    # Only the verification side is registered: the production file is not its target's.
    document = scenario.inputs_document()
    document["actors"]["acquisition"]["production"]["configuration_digest"] = (
        configuration_digest_of(_compiled(TaskEntry.ACQUISITION))
    )
    scenario.inputs.write_bytes(encode(document))
    scenario.authorize()
    assert scenario.run() == launch.EXIT_REFUSED_EQUIVALENCE
    assert scenario.clients.constructions == []


def test_a_verification_file_the_record_did_not_register_is_refused(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, kind="verification")
    scenario.verification_configuration.write_bytes(
        _compiled(TaskEntry.ACQUISITION_VERIFY, generated_at=RUN_1_AT)
    )
    assert scenario.run() == launch.EXIT_REFUSED_EQUIVALENCE
    assert scenario.clients.constructions == []


def test_a_build_verification_needs_its_registered_acquisition_file(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, actor=BLD, kind="verification")
    scenario.acquisition_configuration.write_bytes(
        _compiled(TaskEntry.ACQUISITION, origin_addresses=["198.51.100.9"])
    )
    assert scenario.run() == launch.EXIT_REFUSED_EQUIVALENCE
    assert scenario.clients.constructions == []


def test_a_task_definition_declaration_that_differs_refuses(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, kind="verification")
    document = scenario.inputs_document()
    document["actors"]["acquisition"]["verification"]["task_definition"]["work_tmpfs"] = False
    scenario.inputs.write_bytes(encode(document))
    scenario.authorize()
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
    # Reserved before the bootstrap: consumed, and recoverable.
    assert scenario.reservation() is not None
    assert scenario.run() == launch.EXIT_REFUSED_RECOVERY_PENDING


@pytest.mark.parametrize("actor", (ACQ, BLD), ids=lambda a: a.value)
@pytest.mark.parametrize("kind", ("production", "verification"))
def test_one_launch_one_row_and_sanitized_evidence(
    tmp_path: Path, actor: ProductionActor, kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = 18 if kind == "verification" else 0
    scenario = _Scenario(tmp_path, actor=actor, kind=kind, exit_code=exit_code)
    expected_specification = scenario.specification_digest()
    assert scenario.run() == launch.EXIT_LAUNCH_TERMINAL
    out = capsys.readouterr().out
    assert launch.SENTENCES["launched"] in out
    for canary in CANARIES:
        assert canary not in out
    constants = constants_for(actor)
    assert len(scenario.ecs.names("run_task")) == 1
    assert scenario.clients.human_ssm.names("put_parameter") == [constants.input_parameter]
    assert scenario.clients.launcher_ssm.names("put_parameter") == [constants.release_parameter]
    assert scenario.clients.human_ssm.values == {} and scenario.clients.launcher_ssm.values == {}
    assert {p for _, p in scenario.clients.constructions} == {
        constants.profile,
        constants.launcher_profile,
    }
    rows = scenario.ledger_rows()
    seeded = 0 if actor is ACQ else 1
    assert len(rows) == seeded + 1 and rows[-1]["identity"] == scenario.identity
    assert rows[-1]["kind"] == kind and rows[-1]["evidence"] == "EXIT_CODE_ONLY"
    assert rows[-1]["outcome"] == ("VERIFIED" if kind == "verification" else "COMPLETED")
    assert (rows[-1]["slice"] == slice_document()) if actor is ACQ else (rows[-1]["slice"] is None)
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
    assert record["network_interface_id"] == INTERFACE_ID and record["subnet_id"] == SUBNET_ID
    expected_revision = (
        verification_revision_arn(actor) if kind == "verification" else revision_arn(actor)
    )
    assert record["task_definition_arn"] == expected_revision
    reservation = scenario.reservation()
    assert reservation is not None
    assert reservation["specification_digest"] == expected_specification
    # Provisional: not buildable; a second launch of the same identity refuses.
    row = lr.parse_owner_ledger(scenario.ledger.read_bytes()).row(scenario.identity)
    assert row is not None and not row.buildable
    assert scenario.run() == launch.EXIT_REFUSED_RECORDS
    assert len(scenario.ecs.names("run_task")) == 1
    assert not scenario.lock.exists()


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
    record = scenario.record()
    assert record is not None and record["network_interface_id"] is None


def test_an_ambiguous_outcome_is_recorded_once_and_never_retried(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, never_stops=True)
    assert scenario.run() == launch.EXIT_LAUNCH_NOT_TERMINAL
    evidence = scenario.evidence()
    assert evidence["outcome"] == "OBSERVATION_TIMEOUT" and evidence["exit_codes"] == []
    assert evidence["counts"]["run_task"] == 1
    assert scenario.ledger_rows()[0]["outcome"] == "HALTED"
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
# Durable reservation, interruption and recovery (finding 1)
# ---------------------------------------------------------------------------


def _interrupting_clock(scenario: _Scenario, at_call: int) -> Any:
    real_now = scenario.clock.now
    state = {"calls": 0}

    def interrupted_now() -> Any:
        state["calls"] += 1
        if state["calls"] == at_call:
            raise KeyboardInterrupt("simulated interruption")
        return real_now()

    return interrupted_now


class TestReservation:
    def test_the_reservation_is_written_before_any_client_and_survives_an_interruption(
        self, tmp_path: Path
    ) -> None:
        scenario = _Scenario(tmp_path)
        # Clock reads: 1 prepare, 2 authorization, 3 the reservation lock, 4 reserved_at,
        # 5 launched_at (the bootstrap and adapters lie between 4 and 5).
        with pytest.raises(KeyboardInterrupt):
            scenario.run(now=_interrupting_clock(scenario, 5))
        assert scenario.reservation() is not None and scenario.ledger_rows() == []
        assert scenario.ecs.calls == []
        assert not scenario.lock.exists()
        # Every later attempt on any identity refuses until the owner recovers.
        assert scenario.run() == launch.EXIT_REFUSED_RECOVERY_PENDING
        other = _Scenario(tmp_path, identity=OTHER_RUN_ID)
        assert other.run() == launch.EXIT_REFUSED_RECOVERY_PENDING
        assert scenario.ecs.calls == [] and other.ecs.calls == []

    def test_an_interruption_after_run_task_keeps_the_identity_consumed(
        self, tmp_path: Path
    ) -> None:
        """PR #104 review finding 1: before the fix the identity was launched again."""
        scenario = _Scenario(tmp_path)
        # 6 the input's expiry, 7 the release's verified_at -- after RunTask and placement.
        with pytest.raises(KeyboardInterrupt):
            scenario.run(now=_interrupting_clock(scenario, 7))
        assert len(scenario.ecs.names("run_task")) == 1
        assert scenario.ledger_rows() == [] and scenario.reservation() is not None
        assert scenario.run() == launch.EXIT_REFUSED_RECOVERY_PENDING
        assert len(scenario.ecs.names("run_task")) == 1
        # Recovery records the identity as consumed and launches nothing.
        assert scenario.mode("--recover") == launch.EXIT_RECOVERED
        rows = scenario.ledger_rows()
        assert len(rows) == 1 and rows[0]["identity"] == RUN_ID
        assert rows[0]["outcome"] == "HALTED" and rows[0]["evidence"] == "EXIT_CODE_ONLY"
        # No launch record was written before the interruption, so the recovered row
        # carries no slice: it is consumed and never buildable, which is the point.
        assert rows[0]["kind"] == "production" and rows[0]["slice"] is None
        assert len(scenario.ecs.names("run_task")) == 1
        # And it is never launched again, nor recovered twice; the reservation stays.
        assert scenario.run() == launch.EXIT_REFUSED_RECORDS
        assert scenario.mode("--recover") == launch.EXIT_REFUSED_RECORDS
        assert len(scenario.ecs.names("run_task")) == 1
        assert scenario.reservation() is not None

    def test_recovery_refuses_an_identity_that_was_never_reserved(self, tmp_path: Path) -> None:
        scenario = _Scenario(tmp_path)
        assert scenario.mode("--recover") == launch.EXIT_REFUSED_RECORDS
        assert scenario.ledger_rows() == []

    def test_an_evidence_write_failure_leaves_the_reservation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scenario = _Scenario(tmp_path)
        real = ls.LaunchStore.write_record

        def failing(self: Any, prefix: str, document: Any, *, at: Any) -> Any:
            if prefix == "launch-evidence":
                raise ls.StoreError(ls.StoreDefect.WRITE_FAILED)
            return real(self, prefix, document, at=at)

        monkeypatch.setattr(ls.LaunchStore, "write_record", failing)
        assert scenario.run() == launch.EXIT_INTERRUPTED_AFTER_LAUNCH
        assert len(scenario.ecs.names("run_task")) == 1
        assert scenario.ledger_rows() == [] and scenario.reservation() is not None
        assert not scenario.lock.exists()
        monkeypatch.setattr(ls.LaunchStore, "write_record", real)
        assert scenario.run() == launch.EXIT_REFUSED_RECOVERY_PENDING
        assert scenario.mode("--recover") == launch.EXIT_RECOVERED
        assert scenario.ledger_rows()[0]["outcome"] == "HALTED"
        assert len(scenario.ecs.names("run_task")) == 1

    def test_a_ledger_write_failure_leaves_the_reservation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scenario = _Scenario(tmp_path)

        def failing(self: Any, ledger: Any, *, expected_digest: str) -> None:
            raise ls.StoreError(ls.StoreDefect.WRITE_FAILED)

        monkeypatch.setattr(ls.LaunchStore, "replace_ledger", failing)
        assert scenario.run() == launch.EXIT_INTERRUPTED_AFTER_LAUNCH
        assert scenario.ledger_rows() == [] and scenario.reservation() is not None
        assert len(scenario.files("launch-evidence")) == 1  # written before the ledger

    def test_a_reservation_that_cannot_be_persisted_refuses_before_any_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scenario = _Scenario(tmp_path)

        def failing(self: Any, reservation: Any) -> None:
            raise ls.StoreError(ls.StoreDefect.WRITE_FAILED)

        monkeypatch.setattr(ls.LaunchStore, "reserve", failing)
        assert scenario.run() == launch.EXIT_REFUSED_RECORDS
        assert scenario.clients.constructions == [] and scenario.ecs.calls == []

    def test_a_reservation_already_present_refuses_before_any_client(self, tmp_path: Path) -> None:
        """Two processes prepared against one ledger: the second finds the first's reservation."""
        scenario = _Scenario(tmp_path)
        store = ls.LaunchStore(ledger_path=scenario.ledger, records_dir=scenario.records)
        store.reserve(
            ls.Reservation(
                identity=RUN_ID,
                actor=ACQ,
                kind=lr.LaunchKind.PRODUCTION,
                specification_digest=scenario.specification_digest(),
                reserved_at=NOW,
            )
        )
        assert scenario.run() == launch.EXIT_REFUSED_RECOVERY_PENDING
        assert scenario.clients.constructions == [] and scenario.ecs.calls == []
        # Even with the ledger row present (the first process finished), the second refuses
        # on the ledger, and the reservation file itself refuses a duplicate creation.
        with pytest.raises(ls.StoreError, match="RESERVATION_EXISTS"):
            store.reserve(
                ls.Reservation(
                    identity=RUN_ID,
                    actor=ACQ,
                    kind=lr.LaunchKind.PRODUCTION,
                    specification_digest="ab" * 32,
                    reserved_at=NOW,
                )
            )

    def test_concurrent_distinct_identities_each_launch_once(self, tmp_path: Path) -> None:
        first = _Scenario(tmp_path)
        assert first.run() == launch.EXIT_LAUNCH_TERMINAL
        second = _Scenario(tmp_path, identity=OTHER_RUN_ID, ledger_rows=first.ledger_rows())
        second.clock.seconds = 15.0  # the same recorded second as the first launch
        assert second.run() == launch.EXIT_LAUNCH_TERMINAL
        assert [row["identity"] for row in first.ledger_rows()] == [RUN_ID, OTHER_RUN_ID]
        assert len(first.files("launch-evidence")) == 2
        assert len(first.files("launch-record")) == 2
        assert sorted(p.name for p in (first.records / "reservations").glob("*.json")) == [
            f"{RUN_ID}.json",
            f"{OTHER_RUN_ID}.json",
        ]
        # The second input carried the first identity as spent.
        assert second.clients.human_ssm.calls[0][1]["Name"] == constants_for(ACQ).input_parameter

    def test_a_held_ledger_lock_refuses_and_is_never_removed(self, tmp_path: Path) -> None:
        scenario = _Scenario(tmp_path)
        scenario.lock.write_bytes(b"{}")
        assert scenario.run() == launch.EXIT_REFUSED_LEDGER_LOCKED
        assert scenario.lock.exists() and scenario.clients.constructions == []
        assert scenario.mode("--recover") == launch.EXIT_REFUSED_LEDGER_LOCKED
        assert scenario.lock.exists()


# ---------------------------------------------------------------------------
# Completing the row from the receipt the owner hands back
# ---------------------------------------------------------------------------


def _launch_record(
    *,
    entry: TaskEntry,
    identity: str,
    harness: Any,
    kind: lr.LaunchKind,
    configuration_digest: str | None = None,
) -> lr.LaunchRecord:
    actor = ACQ if entry in (TaskEntry.ACQUISITION, TaskEntry.ACQUISITION_VERIFY) else BLD
    return lr.LaunchRecord(
        entry=entry,
        kind=kind,
        identity=identity,
        task_arn=TASK_ARN,
        task_definition_arn=(
            verification_revision_arn(actor)
            if kind is lr.LaunchKind.VERIFICATION
            else revision_arn(actor)
        ),
        image_digest=IMAGE_DIGEST,
        configuration_digest=(
            compiled_task(actor).configuration_digest
            if configuration_digest is None
            else configuration_digest
        ),
        code_commit=compiled_task(actor).code_commit,
        input_digest=input_digest(harness.input_bytes),
        slice=parse_slice(slice_for_run(1)) if actor is ACQ else None,
        plan_digest="ab" * 32 if actor is ACQ else None,
        launched_at=RUN_1_AT,
        recorded_at=RUN_1_AT + timedelta(minutes=5),
        network_interface_id=INTERFACE_ID,
        subnet_id=SUBNET_ID,
    )


class TestCompleteRow:
    def _completed_scenario(self, tmp_path: Path) -> tuple[_Scenario, Path, Path]:
        from kalpamani.data.production.sharadar.identities import LedgerSpentIdentities

        harness = AcquisitionHarness(spent=LedgerSpentIdentities([]))
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.COMPLETED
        scenario = _Scenario(tmp_path, identity=RUN_1)
        record = _launch_record(
            entry=TaskEntry.ACQUISITION,
            identity=RUN_1,
            harness=harness,
            kind=lr.LaunchKind.PRODUCTION,
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

    def _argv(self, record: Path, lines: Path) -> list[str]:
        return ["--complete-row", "--launch-record", str(record), "--receipt-lines", str(lines)]

    def test_the_verified_receipt_completes_the_row(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        scenario, record, lines = self._completed_scenario(tmp_path)
        assert scenario.mode(*self._argv(record, lines)) == launch.EXIT_ROW_COMPLETED
        assert capsys.readouterr().out.strip() == launch.SENTENCES["row_completed"]
        row = lr.parse_owner_ledger(scenario.ledger.read_bytes()).row(RUN_1)
        assert row is not None and row.buildable
        assert scenario.clients.constructions == []
        assert not scenario.lock.exists()
        # Never twice.
        assert scenario.mode(*self._argv(record, lines)) == launch.EXIT_REFUSED_RECORDS

    def test_a_receipt_that_does_not_belong_to_the_record_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        scenario, record, lines = self._completed_scenario(tmp_path)
        document = json.loads(record.read_bytes())
        document["input_digest"] = "cd" * 32
        record.write_bytes(encode(document))
        assert scenario.mode(*self._argv(record, lines)) == launch.EXIT_REFUSED_RECORDS
        assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_records"]
        row = lr.parse_owner_ledger(scenario.ledger.read_bytes()).row(RUN_1)
        assert row is not None and row.evidence is lr.LedgerEvidence.EXIT_CODE_ONLY

    def test_the_arguments_must_name_the_recorded_launch(self, tmp_path: Path) -> None:
        scenario, record, lines = self._completed_scenario(tmp_path)
        scenario.identity = RUN_ID
        assert scenario.mode(*self._argv(record, lines)) == launch.EXIT_REFUSED_RECORDS

    def test_completion_under_a_held_lock_refuses(self, tmp_path: Path) -> None:
        scenario, record, lines = self._completed_scenario(tmp_path)
        scenario.lock.write_bytes(b"{}")
        assert scenario.mode(*self._argv(record, lines)) == launch.EXIT_REFUSED_LEDGER_LOCKED


# ---------------------------------------------------------------------------
# The R-2 isolation verdict, derived and recorded (finding 4)
# ---------------------------------------------------------------------------


def _reachability_evidence(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": 1,
        "contract_id": pp.REACHABILITY_EVIDENCE_CONTRACT_ID,
        "analysis_id": "nia-0123456789abcdef0",
        "path_id": "nip-0123456789abcdef0",
        "status": "succeeded",
        "network_path_found": False,
        "start_date": (RUN_1_AT + timedelta(minutes=1)).isoformat(),
        "source_interface_id": INTERFACE_ID,
        "destination_ip": min(ORIGIN_ADDRESSES),
        "destination_port": 443,
        "protocol": "tcp",
        "explanations": [
            {
                "explanation_code": "NO_ROUTE_TO_DESTINATION",
                "component_kind": "ROUTE_TABLE",
                "component_id": "rtb-0123456789abcdef0",
                "subnet_id": SUBNET_ID,
            }
        ],
    }
    document.update(overrides)
    return document


class TestIsolationVerdict:
    def _verify_scenario(
        self, tmp_path: Path, *, result: pp.ProbeResult = pp.ProbeResult.TIMED_OUT
    ) -> tuple[_Scenario, Path, Path]:
        from fixtures.production_entry import FakeProbe
        from fixtures.production_runtime import compiled_verification_task
        from kalpamani.data.production.sharadar.metadata import CompiledTask
        from kalpamani.data.production.sharadar.release import build_release_document

        scenario = _Scenario(tmp_path, actor=BLD, kind="verification")
        # The task carried the scenario's verification file: its compiled configuration
        # digest, and the release that attested it, are that file's digest.
        file_digest = configuration_digest_of(scenario.verification_configuration.read_bytes())
        harness = VerificationHarness(entry=TaskEntry.BUILD_VERIFY, probe=FakeProbe(result))
        scenario.identity = harness.identity
        base = compiled_verification_task(BLD)
        compiled = CompiledTask(
            actor=BLD,
            family=base.family,
            code_commit=base.code_commit,
            configuration_digest=file_digest,
        )
        constants = constants_for(BLD)
        harness.ssm.values[constants.release_parameter] = build_release_document(
            actor=BLD,
            task_arn=TASK_ARN,
            task_definition_arn=verification_revision_arn(BLD),
            image_digest=IMAGE_DIGEST,
            configuration_digest=file_digest,
            identity=harness.identity,
            input_digest=input_digest(harness.input_bytes),
            network_interface_id=INTERFACE_ID,
            subnet_id=SUBNET_ID,
            verified_at=harness.clock.now() - timedelta(seconds=10),
        )
        receipt = harness.run(configuration=harness.configuration(compiled=compiled))
        assert receipt.outcome is TaskOutcome.VERIFIED_BOOTSTRAP and receipt.probe is not None
        record = _launch_record(
            entry=TaskEntry.BUILD_VERIFY,
            identity=harness.identity,
            harness=harness,
            kind=lr.LaunchKind.VERIFICATION,
            configuration_digest=file_digest,
        )
        ledger = lr.append_row(
            lr.OwnerLedger(rows=()),
            lr.provisional_ledger_row(record, outcome="VERIFIED", completed_at=record.recorded_at),
        )
        scenario.ledger.write_bytes(encode(ledger.document()))
        record_path = scenario.root / "launch-record.json"
        record_path.write_bytes(encode(record.document()))
        lines_path = scenario.root / "receipt.txt"
        lines_path.write_text("\n".join(receipt.render()) + "\n", encoding="utf-8")
        return scenario, record_path, lines_path

    def _argv(
        self, scenario: _Scenario, record: Path, lines: Path, evidence: Path | None
    ) -> list[str]:
        argv = [
            "--isolation-verdict",
            "--launch-record",
            str(record),
            "--receipt-lines",
            str(lines),
            "--verification-configuration",
            str(scenario.verification_configuration),
        ]
        if evidence is not None:
            argv += ["--reachability-evidence", str(evidence)]
        return argv

    def _verdict(self, scenario: _Scenario) -> dict[str, Any]:
        files = scenario.files("isolation-verdict")
        assert len(files) == 1
        document: dict[str, Any] = json.loads(files[0].read_bytes())
        return document

    def test_without_evidence_the_verdict_is_inconclusive_and_recorded(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        scenario, record, lines = self._verify_scenario(tmp_path)
        assert scenario.mode(*self._argv(scenario, record, lines, None)) == (
            launch.EXIT_VERDICT_RECORDED
        )
        out = capsys.readouterr().out
        assert "isolation_verdict=INCONCLUSIVE reason=NO_CORROBORATION" in out
        document = self._verdict(scenario)
        assert document["verdict"]["verdict"] == "INCONCLUSIVE"
        assert document["evidence_supplied"] is False
        assert document["probe"]["result"] == "TIMED_OUT"
        text = json.dumps(document)
        for canary in CANARIES:
            assert canary not in text
        assert min(ORIGIN_ADDRESSES) not in text and INTERFACE_ID not in text
        assert scenario.clients.constructions == []

    def test_bound_evidence_verifies(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        scenario, record, lines = self._verify_scenario(tmp_path)
        evidence = scenario.root / "reachability.json"
        evidence.write_bytes(encode(_reachability_evidence()))
        assert scenario.mode(*self._argv(scenario, record, lines, evidence)) == (
            launch.EXIT_VERDICT_RECORDED
        )
        assert "isolation_verdict=VERIFIED reason=CORROBORATED" in capsys.readouterr().out
        assert self._verdict(scenario)["verdict"] == {
            "verdict": "VERIFIED",
            "reason": "CORROBORATED",
            "blocking_components": ["ROUTE_TABLE"],
            "analysis_bound": True,
        }

    @pytest.mark.parametrize(
        ("reason", "overrides"),
        [
            ("SOURCE_MISMATCH", {"source_interface_id": "eni-0fedcba9876543210"}),
            ("DESTINATION_MISMATCH", {"destination_ip": max(ORIGIN_ADDRESSES)}),
            ("DESTINATION_MISMATCH", {"destination_port": 8443}),
            (
                "ANALYSIS_OUTSIDE_TASK_WINDOW",
                {"start_date": (RUN_1_AT + timedelta(hours=2)).isoformat()},
            ),
            (
                "ANALYSIS_OUTSIDE_TASK_WINDOW",
                {"start_date": (RUN_1_AT - timedelta(minutes=1)).isoformat()},
            ),
            ("ANALYSIS_NOT_SUCCEEDED", {"status": "running"}),
            ("PATH_FOUND_CONTRADICTS_OBSERVATION", {"network_path_found": True}),
            (
                "UNSUPPORTED_EXPLANATION",
                {
                    "explanations": [
                        {
                            "explanation_code": "NO_PATH",
                            "component_kind": None,
                            "component_id": None,
                            "subnet_id": None,
                        }
                    ]
                },
            ),
            ("UNSUPPORTED_EXPLANATION", {"explanations": []}),
            (
                "COMPONENT_OUTSIDE_PLACEMENT",
                {
                    "explanations": [
                        {
                            "explanation_code": "ENI_SG_RULES_MISMATCH",
                            "component_kind": "SECURITY_GROUP",
                            "component_id": OTHER_SECURITY_GROUP,
                            "subnet_id": None,
                        }
                    ]
                },
            ),
        ],
    )
    def test_every_unbound_or_unsupported_corroboration_stays_inconclusive(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        reason: str,
        overrides: dict[str, Any],
    ) -> None:
        scenario, record, lines = self._verify_scenario(tmp_path)
        evidence = scenario.root / "reachability.json"
        evidence.write_bytes(encode(_reachability_evidence(**overrides)))
        assert scenario.mode(*self._argv(scenario, record, lines, evidence)) == (
            launch.EXIT_VERDICT_RECORDED
        )
        assert f"isolation_verdict=INCONCLUSIVE reason={reason}" in capsys.readouterr().out

    def test_a_security_group_block_inside_the_placement_verifies(self, tmp_path: Path) -> None:
        scenario, record, lines = self._verify_scenario(tmp_path)
        evidence = scenario.root / "reachability.json"
        evidence.write_bytes(
            encode(
                _reachability_evidence(
                    explanations=[
                        {
                            "explanation_code": "SG_HAS_NO_RULES",
                            "component_kind": "SECURITY_GROUP",
                            "component_id": SECURITY_GROUPS[0],
                            "subnet_id": None,
                        }
                    ]
                )
            )
        )
        assert scenario.mode(*self._argv(scenario, record, lines, evidence)) == (
            launch.EXIT_VERDICT_RECORDED
        )
        assert self._verdict(scenario)["verdict"]["blocking_components"] == ["SECURITY_GROUP"]

    def test_an_observed_connection_fails_whatever_the_model_says(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        scenario, record, lines = self._verify_scenario(tmp_path, result=pp.ProbeResult.CONNECTED)
        evidence = scenario.root / "reachability.json"
        evidence.write_bytes(encode(_reachability_evidence()))
        assert scenario.mode(*self._argv(scenario, record, lines, evidence)) == (
            launch.EXIT_VERDICT_RECORDED
        )
        assert "isolation_verdict=FAILED reason=OBSERVED_CONNECTION" in capsys.readouterr().out

    def test_malformed_evidence_and_an_unbound_configuration_refuse(self, tmp_path: Path) -> None:
        scenario, record, lines = self._verify_scenario(tmp_path)
        evidence = scenario.root / "reachability.json"
        evidence.write_bytes(encode(_reachability_evidence(status="done")))
        assert scenario.mode(*self._argv(scenario, record, lines, evidence)) == (
            launch.EXIT_REFUSED_RECORDS
        )
        assert scenario.files("isolation-verdict") == []
        # A verification file other than the one the task carried does not bind.
        scenario.verification_configuration.write_bytes(
            _compiled(TaskEntry.BUILD_VERIFY, origin_addresses=["198.51.100.4"])
        )
        assert scenario.mode(*self._argv(scenario, record, lines, None)) == (
            launch.EXIT_REFUSED_RECORDS
        )

    def test_a_production_record_has_no_verdict(self, tmp_path: Path) -> None:
        from kalpamani.data.production.sharadar.identities import LedgerSpentIdentities

        harness = AcquisitionHarness(spent=LedgerSpentIdentities([]))
        receipt = harness.run()
        scenario = _Scenario(tmp_path, identity=RUN_1)
        record = _launch_record(
            entry=TaskEntry.ACQUISITION,
            identity=RUN_1,
            harness=harness,
            kind=lr.LaunchKind.PRODUCTION,
        )
        record_path = scenario.root / "launch-record.json"
        record_path.write_bytes(encode(record.document()))
        lines_path = scenario.root / "receipt.txt"
        lines_path.write_text("\n".join(receipt.render()) + "\n", encoding="utf-8")
        argv = [
            "--isolation-verdict",
            "--launch-record",
            str(record_path),
            "--receipt-lines",
            str(lines_path),
            "--verification-configuration",
            str(scenario.verification_configuration),
        ]
        assert scenario.mode(*argv) == launch.EXIT_REFUSED_RECORDS
