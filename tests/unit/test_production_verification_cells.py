"""The verification cell matrix and its runner, on fakes and synthetic records only.

The matrix is derived from what was durably recorded -- the ledger, the reservations
beside it, the verdict records, the R-3 record, the launch-inputs record -- so an
interrupted or resumed run is reconciled rather than remembered; a failed prerequisite
blocks its dependants; one identity and one authorization per cell; nothing is retried;
the aggregate is never VERIFIED while a cell is blocked, launched-without-receipt,
inconclusive or unexecuted. **Mocked results are not AWS verification.**
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from test_production_launch_script import (
    TestIsolationVerdict,
    _reachability_evidence,
    _Scenario,
    launch,
)

from fixtures.production_launch import (
    ACQ,
    BLD,
    authorization_document,
    launch_inputs_document,
    ledger_document,
    ledger_row,
)
from fixtures.production_runtime import CANARIES, RUN_ID, encode
from kalpamani.data.contracts.canonical import canonical_bytes
from kalpamani.data.production.sharadar import launch_records as lr
from kalpamani.data.production.sharadar import r3_verification as r3
from kalpamani.data.production.sharadar import verification_cells as vc
from kalpamani.data.production.sharadar.probe import IsolationVerdict

pytestmark = pytest.mark.unit

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
SCRIPT: Final = REPO_ROOT / "scripts" / "production_verification_cells.py"
NOW: Final = datetime(2026, 9, 14, 18, 0, tzinfo=UTC)
ENVELOPE: Final = "ab" * 32
DECLARATION: Final = "cd" * 32
BINDING: Final = r3.R3Binding(
    environment_binding_sha256=ENVELOPE,
    policy_declaration_sha256=DECLARATION,
    partition="aws",
    region="us-east-1",
)


def _module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = _module("production_verification_cells", SCRIPT)


class _VerifiedBucket:
    """A bucket under the accepted policy: the R-3 expected path, nothing else."""

    def put_object(self, key: str, body: bytes, *, if_none_match: bool) -> r3.Observation:
        if if_none_match:
            return r3.Observation(status=200)
        return r3.Observation(
            status=403, code="AccessDenied", message="explicit deny in a resource-based policy"
        )

    def head_object(self, key: str) -> r3.Observation:
        return r3.Observation(status=404, code="404")

    def copy_object(self, source_key: str, key: str, *, if_none_match: bool) -> r3.Observation:
        return r3.Observation(
            status=403, code="AccessDenied", message="explicit deny in a resource-based policy"
        )

    def create_multipart_upload(self, key: str) -> r3.Observation:
        return r3.Observation(
            status=403, code="AccessDenied", message="explicit deny in a resource-based policy"
        )

    def delete_object(self, key: str) -> r3.Observation:
        return r3.Observation(status=204)

    def abort_multipart_upload(self, key: str, upload_id: str) -> r3.Observation:
        return r3.Observation(status=204)

    def list_parts(self, key: str, upload_id: str) -> r3.Observation:
        return r3.Observation(status=404, code="NoSuchUpload")


def _r3_record(verified: bool = True) -> r3.R3Record:
    bucket: Any = _VerifiedBucket()
    if not verified:

        class _Leaky(_VerifiedBucket):
            def put_object(self, key: str, body: bytes, *, if_none_match: bool) -> r3.Observation:
                return r3.Observation(status=200)

        bucket = _Leaky()
    return r3.run_r3(bucket, binding=BINDING, now=lambda: NOW, stamp="20260914T180000Z-abcd")


def _inputs(r3_digest: str | None) -> lr.LaunchInputs:
    return lr.parse_launch_inputs(encode(launch_inputs_document(r3_verification_digest=r3_digest)))


def _evidence(
    *,
    rows: list[dict[str, Any]] | None = None,
    unreconciled: set[str] | None = None,
    verdicts: dict[str, IsolationVerdict] | None = None,
    r3_record: r3.R3Record | None = None,
    r3_binding: r3.R3Binding | None = BINDING,
    inputs_digest: str | None = None,
) -> vc.RecordedEvidence:
    return vc.RecordedEvidence(
        ledger=lr.parse_owner_ledger(encode(ledger_document(rows or []))),
        unreconciled=frozenset(unreconciled or set()),
        verdicts=verdicts or {},
        inputs=_inputs(inputs_digest),
        r3_record=r3_record,
        r3_binding=r3_binding,
    )


def _prepared(**cells: str) -> dict[str, vc.PreparedCell]:
    return {
        cell_id: vc.PreparedCell(
            cell_id=cell_id, identity=identity, specification_digest="ef" * 32, prepared_at=NOW
        )
        for cell_id, identity in cells.items()
    }


# ---------------------------------------------------------------------------
# The matrix
# ---------------------------------------------------------------------------


def test_the_required_cells_are_enumerated_from_the_accepted_contracts() -> None:
    ids = [cell.cell_id for cell in vc.REQUIRED_CELLS]
    assert ids[:4] == ["R3", "R1-ACQ-BOOTSTRAP", "R1-BLD-BOOTSTRAP", "R2-BLD-ISOLATION"]
    assert {c.cell_ref for c in vc.REQUIRED_CELLS} == {f"R-{n}" for n in range(1, 10)}
    for cell in vc.REQUIRED_CELLS:
        for dependency in cell.depends_on:
            assert dependency in vc.CELL_BY_ID and ids.index(dependency) < ids.index(cell.cell_id)
        assert cell.authorization and cell.execution
    assert vc.definition("R2-BLD-ISOLATION").depends_on == ("R1-BLD-BOOTSTRAP",)
    assert all(
        c.depends_on == ("R3",) for c in vc.REQUIRED_CELLS if c.kind is vc.CellKind.RUNTIME_LAUNCH
    )
    with pytest.raises(ValueError):
        vc.definition("R0")
    text = json.dumps([c.document() for c in vc.REQUIRED_CELLS])
    for canary in CANARIES:
        assert canary not in text


def test_without_an_r3_record_every_dependant_is_blocked_and_the_aggregate_incomplete() -> None:
    states = vc.derive_states(_evidence(), {})
    assert states["R3"].status is vc.CellStatus.BLOCKED
    for cell_id in ("R1-ACQ-BOOTSTRAP", "R1-BLD-BOOTSTRAP", "R2-BLD-ISOLATION", "R4-ACQUISITION"):
        assert states[cell_id].status is vc.CellStatus.BLOCKED, cell_id
    assert vc.aggregate(states) is vc.AggregateStatus.INCOMPLETE
    lines = vc.matrix_lines(states)
    assert lines[0] == "cell=R3 ref=R-3 kind=CONTROL_R3 status=BLOCKED"
    assert lines[-1].startswith("aggregate=INCOMPLETE")


def test_the_r3_cell_passes_only_with_attesting_verified_evidence_named_by_the_inputs() -> None:
    record = _r3_record()
    # Verified, attesting, but the launch inputs do not name it: stage b not attested.
    states = vc.derive_states(_evidence(r3_record=record, inputs_digest="a3" * 32), {})
    assert states["R3"].status is vc.CellStatus.BLOCKED
    # Verified, named, but the declaration moved on: the record does not attest.
    changed = r3.R3Binding(
        environment_binding_sha256=ENVELOPE,
        policy_declaration_sha256="ff" * 32,
        partition="aws",
        region="us-east-1",
    )
    states = vc.derive_states(
        _evidence(r3_record=record, r3_binding=changed, inputs_digest=record.digest), {}
    )
    assert states["R3"].status is vc.CellStatus.BLOCKED
    # No binding could be computed: blocked, never passed.
    states = vc.derive_states(
        _evidence(r3_record=record, r3_binding=None, inputs_digest=record.digest), {}
    )
    assert states["R3"].status is vc.CellStatus.BLOCKED
    # A record that did not verify: failed.
    leaky = _r3_record(verified=False)
    states = vc.derive_states(_evidence(r3_record=leaky, inputs_digest=leaky.digest), {})
    assert states["R3"].status is vc.CellStatus.FAILED
    assert vc.aggregate(states) is vc.AggregateStatus.FAILED
    # Everything in place.
    states = vc.derive_states(_evidence(r3_record=record, inputs_digest=record.digest), {})
    assert states["R3"].status is vc.CellStatus.PASSED
    assert states["R1-ACQ-BOOTSTRAP"].status is vc.CellStatus.UNEXECUTED
    assert states["R4-ACQUISITION"].status is vc.CellStatus.UNEXECUTED
    for cell_id in ("R1-ACQ-NO-RELEASE", "R1-BLD-RELEASE-MISMATCH"):
        assert states[cell_id].status is vc.CellStatus.BLOCKED
        assert "withholds" in states[cell_id].reason
    assert vc.aggregate(states) is vc.AggregateStatus.INCOMPLETE


def test_runtime_cell_states_are_derived_from_the_ledger_and_the_reservations() -> None:
    record = _r3_record()
    base: dict[str, Any] = {"r3_record": record, "inputs_digest": record.digest}
    prepared = _prepared(**{"R1-ACQ-BOOTSTRAP": "verify-" + RUN_ID})
    states = vc.derive_states(_evidence(**base), prepared)
    assert states["R1-ACQ-BOOTSTRAP"].status is vc.CellStatus.PREPARED
    # Reserved but unrecorded: interrupted, recover, never relaunch.
    states = vc.derive_states(_evidence(**base, unreconciled={"verify-" + RUN_ID}), prepared)
    assert states["R1-ACQ-BOOTSTRAP"].status is vc.CellStatus.INTERRUPTED
    assert "--recover" in states["R1-ACQ-BOOTSTRAP"].reason
    # A row from the exit code only cannot pass.
    row = ledger_row(
        "verify-" + RUN_ID, kind="verification", outcome="VERIFIED", evidence="EXIT_CODE_ONLY"
    )
    states = vc.derive_states(_evidence(**base, rows=[row]), prepared)
    assert states["R1-ACQ-BOOTSTRAP"].status is vc.CellStatus.LAUNCHED
    assert vc.aggregate(states) is vc.AggregateStatus.INCOMPLETE
    # Receipt-verified: passed.
    row = ledger_row(
        "verify-" + RUN_ID, kind="verification", outcome="VERIFIED", evidence="RECEIPT_VERIFIED"
    )
    states = vc.derive_states(_evidence(**base, rows=[row]), prepared)
    assert states["R1-ACQ-BOOTSTRAP"].status is vc.CellStatus.PASSED
    # Refused and halted rows.
    for outcome, status in (("REFUSED", vc.CellStatus.REFUSED), ("HALTED", vc.CellStatus.FAILED)):
        row = ledger_row(
            "verify-" + RUN_ID, kind="verification", outcome=outcome, evidence="EXIT_CODE_ONLY"
        )
        states = vc.derive_states(_evidence(**base, rows=[row]), prepared)
        assert states["R1-ACQ-BOOTSTRAP"].status is status
    # A row of another actor under this identity contradicts the cell.
    row = ledger_row(
        "verify-" + RUN_ID,
        actor=BLD,
        kind="verification",
        outcome="VERIFIED",
        evidence="RECEIPT_VERIFIED",
        with_slice=False,
    )
    states = vc.derive_states(_evidence(**base, rows=[row]), prepared)
    assert states["R1-ACQ-BOOTSTRAP"].status is vc.CellStatus.FAILED
    # A launched cell keeps its recorded state even when R-3 is later blocked.
    row = ledger_row(
        "verify-" + RUN_ID, kind="verification", outcome="VERIFIED", evidence="RECEIPT_VERIFIED"
    )
    states = vc.derive_states(_evidence(rows=[row]), prepared)
    assert states["R1-ACQ-BOOTSTRAP"].status is vc.CellStatus.PASSED
    assert states["R3"].status is vc.CellStatus.BLOCKED


def test_the_isolation_cell_is_separate_from_bootstrap_and_stays_inconclusive_uncorroborated() -> (
    None
):
    record = _r3_record()
    identity = "verify-" + RUN_ID
    prepared = _prepared(**{"R1-BLD-BOOTSTRAP": identity})
    digest = prepared["R1-BLD-BOOTSTRAP"].specification_digest
    passed = ledger_row(
        identity,
        actor=BLD,
        kind="verification",
        outcome="VERIFIED",
        evidence="RECEIPT_VERIFIED",
        with_slice=False,
    )
    launched = ledger_row(
        identity,
        actor=BLD,
        kind="verification",
        outcome="VERIFIED",
        evidence="EXIT_CODE_ONLY",
        with_slice=False,
    )
    base: dict[str, Any] = {"r3_record": record, "inputs_digest": record.digest}
    # Bootstrap launched but not receipt-verified: the verdict is blocked.
    states = vc.derive_states(_evidence(**base, rows=[launched]), prepared)
    assert states["R2-BLD-ISOLATION"].status is vc.CellStatus.BLOCKED
    # Bootstrap passed, no verdict yet.
    states = vc.derive_states(_evidence(**base, rows=[passed]), prepared)
    assert states["R1-BLD-BOOTSTRAP"].status is vc.CellStatus.PASSED
    assert states["R2-BLD-ISOLATION"].status is vc.CellStatus.UNEXECUTED
    for verdict, status in (
        (IsolationVerdict.INCONCLUSIVE, vc.CellStatus.INCONCLUSIVE),
        (IsolationVerdict.FAILED, vc.CellStatus.FAILED),
        (IsolationVerdict.VERIFIED, vc.CellStatus.PASSED),
    ):
        states = vc.derive_states(
            _evidence(**base, rows=[passed], verdicts={digest: verdict}), prepared
        )
        assert states["R2-BLD-ISOLATION"].status is status, verdict
    # A verified verdict never makes the aggregate VERIFIED while other cells are blocked.
    assert vc.aggregate(states) is vc.AggregateStatus.INCOMPLETE


def test_the_aggregate_is_verified_only_when_every_cell_passed() -> None:
    all_passed = {
        cell.cell_id: vc.CellState(
            cell_id=cell.cell_id,
            status=vc.CellStatus.PASSED,
            reason="",
            identity=None,
            specification_digest=None,
        )
        for cell in vc.REQUIRED_CELLS
    }
    assert vc.aggregate(all_passed) is vc.AggregateStatus.VERIFIED
    for status in (
        vc.CellStatus.LAUNCHED,
        vc.CellStatus.INCONCLUSIVE,
        vc.CellStatus.BLOCKED,
        vc.CellStatus.UNEXECUTED,
    ):
        mixed = dict(all_passed)
        mixed["R2-BLD-ISOLATION"] = vc.CellState(
            cell_id="R2-BLD-ISOLATION",
            status=status,
            reason="",
            identity=None,
            specification_digest=None,
        )
        assert vc.aggregate(mixed) is vc.AggregateStatus.INCOMPLETE, status
    # The real matrix can never be VERIFIED in this cycle: the negative cells are blocked.
    record = _r3_record()
    states = vc.derive_states(_evidence(r3_record=record, inputs_digest=record.digest), {})
    assert vc.aggregate(states) is not vc.AggregateStatus.VERIFIED


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["cells"]["R1-ACQ-BOOTSTRAP"].__setitem__("identity", RUN_ID),  # not verify-
        lambda d: d["cells"].__setitem__("R3", dict(d["cells"]["R1-ACQ-BOOTSTRAP"], cell_id="R3")),
        lambda d: d["cells"].__setitem__(
            "R1-BLD-BOOTSTRAP", dict(d["cells"]["R1-ACQ-BOOTSTRAP"], cell_id="R1-BLD-BOOTSTRAP")
        ),
        lambda d: d["cells"]["R1-ACQ-BOOTSTRAP"].__setitem__("specification_digest", "xyz"),
        lambda d: d["cells"]["R1-ACQ-BOOTSTRAP"].__setitem__("cell_id", "R1-BLD-BOOTSTRAP"),
        lambda d: d.__setitem__("contract_id", "kalpamani-verification-cells/v2"),
        lambda d: d.__setitem__("extra", 1),
    ],
)
def test_the_prepared_cells_document_is_closed(mutate: Any) -> None:
    prepared = _prepared(**{"R1-ACQ-BOOTSTRAP": "verify-" + RUN_ID})
    document = vc.cells_document(prepared.values())
    assert vc.parse_cells_document(canonical_bytes(document)) == prepared
    mutate(document)
    with pytest.raises(vc.CellsDocumentError):
        vc.parse_cells_document(canonical_bytes(document))


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------


class _Cells:
    """A launch-tool scenario plus the runner's records: an R-3 record, cells beside the ledger."""

    def __init__(self, tmp_path: Path, **scenario_kw: Any) -> None:
        self.scenario = _Scenario(tmp_path, kind="verification", exit_code=18, **scenario_kw)
        self.r3 = self.scenario.root / "r3-record.json"
        self.record = _r3_record()
        self.r3.write_bytes(canonical_bytes(self.record.document()))
        # The launch inputs name the R-3 record's digest: stage b attested.
        inputs = self.scenario.inputs_document()
        inputs["r3_verification_digest"] = self.record.digest
        self.scenario.inputs.write_bytes(encode(inputs))
        self.scenario.authorize()

    def base(self, *, with_r3: bool = True) -> list[str]:
        argv = [
            "--ledger",
            str(self.scenario.ledger),
            "--launch-inputs",
            str(self.scenario.inputs),
            "--records-dir",
            str(self.scenario.records),
        ]
        if with_r3:
            argv += ["--r3-record", str(self.r3)]
        return argv

    def cell_argv(self) -> list[str]:
        s = self.scenario
        argv = [
            "--production-configuration",
            str(s.production_configuration),
            "--verification-configuration",
            str(s.verification_configuration),
        ]
        if s.actor is ACQ:
            argv += ["--slice", str(s.slice)]
        else:
            argv += [
                "--run-identity",
                RUN_ID,
                "--acquisition-configuration",
                str(s.acquisition_configuration),
            ]
        return argv

    def main(self, *argv: str, **overrides: Any) -> int:
        fields = self.scenario.fields(**overrides)
        fields["r3_binding_source"] = lambda: BINDING
        code: int = runner.main(list(argv), **fields)
        return code

    def cells(self) -> dict[str, Any]:
        path = self.scenario.ledger.with_name("ledger.json" + runner.CELLS_SUFFIX)
        return json.loads(path.read_bytes())["cells"] if path.exists() else {}


def test_the_default_matrix_derives_from_records_and_constructs_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cells = _Cells(tmp_path)
    assert cells.main(*cells.base()) == runner.EXIT_MATRIX
    out = capsys.readouterr().out
    assert "cell=R3 ref=R-3 kind=CONTROL_R3 status=PASSED" in out
    assert "cell=R1-ACQ-BOOTSTRAP ref=R-1 kind=RUNTIME_LAUNCH status=UNEXECUTED" in out
    assert "cell=R1-ACQ-NO-RELEASE ref=R-1 kind=NEGATIVE_LAUNCH status=BLOCKED" in out
    assert "aggregate=INCOMPLETE" in out and runner.SENTENCES["matrix"] in out
    assert cells.scenario.clients.constructions == [] and cells.scenario.ecs.calls == []
    assert cells.cells() == {}
    for canary in (*CANARIES, cells.scenario.identity):
        assert canary not in out
    # Without the R-3 record every runtime cell is blocked.
    assert cells.main(*cells.base(with_r3=False)) == runner.EXIT_MATRIX
    out = capsys.readouterr().out
    assert "cell=R3 ref=R-3 kind=CONTROL_R3 status=BLOCKED" in out
    assert "cell=R1-ACQ-BOOTSTRAP ref=R-1 kind=RUNTIME_LAUNCH status=BLOCKED" in out


@pytest.mark.parametrize("flag", sorted(runner.REFUSED_FLAGS))
def test_refused_flags_and_contradictory_arguments_refuse_before_anything(
    tmp_path: Path, flag: str
) -> None:
    cells = _Cells(tmp_path)
    assert cells.main(*cells.base(), flag) == runner.EXIT_REFUSED_ARGUMENTS
    assert cells.main(*cells.base(), runner.AUTHORIZATION_FLAG) == runner.EXIT_REFUSED_ARGUMENTS
    assert cells.main(*cells.base(), "--prepare-cell", "R3", "--identity", "verify-x") == (
        runner.EXIT_REFUSED_ARGUMENTS
    )
    assert cells.main(
        *cells.base(), "--prepare-cell", "R1-ACQ-BOOTSTRAP", "--identity", RUN_ID
    ) == (runner.EXIT_REFUSED_ARGUMENTS)
    assert cells.scenario.clients.constructions == []


def test_prepare_records_the_cell_beside_the_ledger_and_execute_needs_its_authorization(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cells = _Cells(tmp_path)
    identity = cells.scenario.identity
    prepare = [
        *cells.base(),
        "--prepare-cell",
        "R1-ACQ-BOOTSTRAP",
        "--identity",
        identity,
        *cells.cell_argv(),
    ]
    assert cells.main(*prepare) == runner.EXIT_PREPARED
    out = capsys.readouterr().out
    digest = cells.scenario.specification_digest()
    assert f"cell=R1-ACQ-BOOTSTRAP specification_digest={digest}" in out
    assert cells.cells() == {
        "R1-ACQ-BOOTSTRAP": {
            "cell_id": "R1-ACQ-BOOTSTRAP",
            "identity": identity,
            "specification_digest": digest,
            "prepared_at": cells.scenario.clock.now().isoformat(),
        }
    }
    assert len(cells.scenario.files("launch-specification")) == 1
    assert cells.scenario.clients.constructions == [] and cells.scenario.ecs.calls == []
    assert cells.main(*cells.base()) == runner.EXIT_MATRIX
    assert (
        "cell=R1-ACQ-BOOTSTRAP ref=R-1 kind=RUNTIME_LAUNCH status=PREPARED"
        in capsys.readouterr().out
    )
    # The same identity cannot be prepared for another cell.
    other = [
        *cells.base(),
        "--prepare-cell",
        "R1-BLD-BOOTSTRAP",
        "--identity",
        identity,
        *cells.cell_argv(),
    ]
    assert cells.main(*other) != runner.EXIT_PREPARED
    # Execute: no flag, no authorization, an authorization for another specification --
    # each refused before any client.
    execute = [*cells.base(), "--execute-cell", "R1-ACQ-BOOTSTRAP", *cells.cell_argv()]
    assert cells.main(*execute) == runner.EXIT_REFUSED_ARGUMENTS
    assert cells.main(*execute, runner.AUTHORIZATION_FLAG) == runner.EXIT_REFUSED_ARGUMENTS
    foreign = cells.scenario.root / "foreign-authorization.json"
    foreign.write_bytes(
        encode(
            authorization_document(
                actor=ACQ, kind="verification", identity=identity, specification_digest="00" * 32
            )
        )
    )
    assert cells.main(*execute, "--authorization", str(foreign), runner.AUTHORIZATION_FLAG) == (
        runner.EXIT_REFUSED_AUTHORIZATION
    )
    assert cells.scenario.clients.constructions == []
    # A blocked prerequisite (no R-3 record) refuses before any client.
    blocked = [*cells.base(with_r3=False), "--execute-cell", "R1-ACQ-BOOTSTRAP", *cells.cell_argv()]
    assert (
        cells.main(
            *blocked,
            "--authorization",
            str(cells.scenario.authorization),
            runner.AUTHORIZATION_FLAG,
        )
        == runner.EXIT_REFUSED_PREREQUISITE
    )
    assert cells.scenario.clients.constructions == []
    # The real thing: the launch tool's authorized branch, once, on fakes.
    assert (
        cells.main(
            *execute,
            "--authorization",
            str(cells.scenario.authorization),
            runner.AUTHORIZATION_FLAG,
        )
        == launch.EXIT_LAUNCH_TERMINAL
    )
    out = capsys.readouterr().out
    assert len(cells.scenario.ecs.names("run_task")) == 1
    assert "cell=R1-ACQ-BOOTSTRAP ref=R-1 kind=RUNTIME_LAUNCH status=LAUNCHED" in out
    assert "aggregate=INCOMPLETE" in out
    rows = cells.scenario.ledger_rows()
    assert rows[0]["identity"] == identity and rows[0]["outcome"] == "VERIFIED"
    # Never twice: the cell is LAUNCHED, not PREPARED.
    assert (
        cells.main(
            *execute,
            "--authorization",
            str(cells.scenario.authorization),
            runner.AUTHORIZATION_FLAG,
        )
        == runner.EXIT_REFUSED_CELL_STATE
    )
    assert len(cells.scenario.ecs.names("run_task")) == 1
    # Completing needs a receipt; a wrong receipt refuses through the launch tool.
    record_path = cells.scenario.files("launch-record")[0]
    lines = cells.scenario.root / "receipt.txt"
    lines.write_text("not a receipt\n", encoding="utf-8")
    complete = [
        *cells.base(),
        "--complete-cell",
        "R1-ACQ-BOOTSTRAP",
        "--launch-record",
        str(record_path),
        "--receipt-lines",
        str(lines),
    ]
    assert cells.main(*complete) == launch.EXIT_REFUSED_RECORDS
    assert cells.main(*cells.base()) == runner.EXIT_MATRIX
    assert "status=LAUNCHED" in capsys.readouterr().out


def test_an_interrupted_cell_is_reconciled_and_never_relaunched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from test_production_launch_script import _interrupting_clock

    cells = _Cells(tmp_path)
    identity = cells.scenario.identity
    prepare = [
        *cells.base(),
        "--prepare-cell",
        "R1-ACQ-BOOTSTRAP",
        "--identity",
        identity,
        *cells.cell_argv(),
    ]
    assert cells.main(*prepare) == runner.EXIT_PREPARED
    execute = [
        *cells.base(),
        "--execute-cell",
        "R1-ACQ-BOOTSTRAP",
        *cells.cell_argv(),
        "--authorization",
        str(cells.scenario.authorization),
        runner.AUTHORIZATION_FLAG,
    ]
    with pytest.raises(KeyboardInterrupt):
        cells.main(*execute, now=_interrupting_clock(cells.scenario, 7))
    assert len(cells.scenario.ecs.names("run_task")) == 1
    capsys.readouterr()
    assert cells.main(*cells.base()) == runner.EXIT_MATRIX
    out = capsys.readouterr().out
    assert "cell=R1-ACQ-BOOTSTRAP ref=R-1 kind=RUNTIME_LAUNCH status=INTERRUPTED" in out
    # Execution refuses (not PREPARED); the launch tool's recovery records the row.
    assert cells.main(*execute) == runner.EXIT_REFUSED_CELL_STATE
    assert len(cells.scenario.ecs.names("run_task")) == 1
    assert cells.scenario.mode("--recover") == launch.EXIT_RECOVERED
    capsys.readouterr()
    assert cells.main(*cells.base()) == runner.EXIT_MATRIX
    assert (
        "cell=R1-ACQ-BOOTSTRAP ref=R-1 kind=RUNTIME_LAUNCH status=FAILED" in capsys.readouterr().out
    )
    assert cells.main(*execute) == runner.EXIT_REFUSED_CELL_STATE
    assert len(cells.scenario.ecs.names("run_task")) == 1


def test_a_held_ledger_lock_refuses_preparation(tmp_path: Path) -> None:
    cells = _Cells(tmp_path)
    cells.scenario.lock.write_bytes(b"{}")
    prepare = [
        *cells.base(),
        "--prepare-cell",
        "R1-ACQ-BOOTSTRAP",
        "--identity",
        cells.scenario.identity,
        *cells.cell_argv(),
    ]
    assert cells.main(*prepare) == runner.EXIT_REFUSED_LEDGER_LOCKED
    assert cells.cells() == {} and cells.scenario.lock.exists()


def test_the_build_verdict_cell_follows_its_bootstrap_cell_and_stays_inconclusive_uncorroborated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The verdict path composed end to end: receipt completion, then the verdict."""
    case = TestIsolationVerdict()
    scenario, record_path, lines_path = case._verify_scenario(tmp_path)
    cells = _Cells.__new__(_Cells)
    cells.scenario = scenario
    cells.record = _r3_record()
    cells.r3 = scenario.root / "r3-record.json"
    cells.r3.write_bytes(canonical_bytes(cells.record.document()))
    reservation = scenario.reservation()
    assert reservation is not None
    # The prepared-cells record names the launch the scenario made.
    path = scenario.ledger.with_name("ledger.json" + runner.CELLS_SUFFIX)
    path.write_bytes(
        canonical_bytes(
            vc.cells_document(
                [
                    vc.PreparedCell(
                        cell_id="R1-BLD-BOOTSTRAP",
                        identity=scenario.identity,
                        specification_digest=reservation["specification_digest"],
                        prepared_at=NOW,
                    )
                ]
            )
        )
    )
    assert cells.main(*cells.base()) == runner.EXIT_MATRIX
    out = capsys.readouterr().out
    assert "cell=R1-BLD-BOOTSTRAP ref=R-1 kind=RUNTIME_LAUNCH status=LAUNCHED" in out
    assert "cell=R2-BLD-ISOLATION ref=R-2 kind=ISOLATION_VERDICT status=BLOCKED" in out
    verdict = [
        *cells.base(),
        "--verdict-cell",
        "R2-BLD-ISOLATION",
        "--launch-record",
        str(record_path),
        "--receipt-lines",
        str(lines_path),
        "--verification-configuration",
        str(scenario.verification_configuration),
    ]
    # The verdict is blocked until the bootstrap cell's receipt verified.
    assert cells.main(*verdict) == runner.EXIT_REFUSED_PREREQUISITE
    complete = [
        *cells.base(),
        "--complete-cell",
        "R1-BLD-BOOTSTRAP",
        "--launch-record",
        str(record_path),
        "--receipt-lines",
        str(lines_path),
    ]
    assert cells.main(*complete) == launch.EXIT_ROW_COMPLETED
    out = capsys.readouterr().out
    assert "cell=R1-BLD-BOOTSTRAP ref=R-1 kind=RUNTIME_LAUNCH status=PASSED" in out
    assert "cell=R2-BLD-ISOLATION ref=R-2 kind=ISOLATION_VERDICT status=UNEXECUTED" in out
    # Without a corroboration the verdict stays INCONCLUSIVE, and the aggregate INCOMPLETE.
    assert cells.main(*verdict) == launch.EXIT_VERDICT_RECORDED
    out = capsys.readouterr().out
    assert "cell=R2-BLD-ISOLATION ref=R-2 kind=ISOLATION_VERDICT status=INCONCLUSIVE" in out
    assert "aggregate=INCOMPLETE" in out
    # A verdict cell is recorded once; a second verdict with evidence cannot promote it.
    evidence = scenario.root / "reachability.json"
    evidence.write_bytes(encode(_reachability_evidence()))
    assert (
        cells.main(*verdict, "--reachability-evidence", str(evidence))
        == runner.EXIT_REFUSED_CELL_STATE
    )
    assert scenario.clients.constructions == []


def test_a_verified_verdict_never_overrides_a_recorded_failure(tmp_path: Path) -> None:
    """Two verdict records for one launch: the lower one governs."""
    from kalpamani.data.production.sharadar import launch_records as records

    cells = _Cells(tmp_path)
    store = cells.scenario.store()
    for verdict in ("VERIFIED", "FAILED"):
        store.write_record(
            "isolation-verdict",
            {
                "schema_version": records.RECORD_SCHEMA_VERSION,
                "contract_id": "kalpamani-isolation-verdict/v1",
                "specification_digest": "ef" * 32,
                "verdict": {"verdict": verdict},
            },
            at=NOW,
        )
    found = runner._verdicts(store)
    assert found == {"ef" * 32: IsolationVerdict.FAILED}
