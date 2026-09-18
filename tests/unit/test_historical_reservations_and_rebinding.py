"""ADR-0054: historical (superseded-workload) reservations read as evidence, and the
registration-historical rebinding of a verification cell -- on fakes, synthetic records and a
temporary store only.

Two narrow decisions. A reservation whose acquisition workload was compiled under the
superseded v1 plan contract is **evidence of a launch that happened**: the store reads it
through an explicit historical parser, the runner binds the preserved launch record and
ledger row to it and derives ``HISTORICAL``, and nothing can reserve, recover, execute or
pass it. A cell whose launched binding the runner derives ``HISTORICAL`` solely because
the registration in force no longer names its target may receive a fresh identity: the
previous cells document is preserved byte for byte, the new binding names what it
superseded, and every prior record stays untouched. Everything else -- a current PASSED
cell, a PREPARED one, an unlaunched or malformed binding, the same registration, a spent
identity -- refuses before any specification is written. **Mocked results are not AWS
verification.**
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from test_production_launch_script import launch
from test_production_verification_cells import (
    BINDING,
    SCRIPT,
    _bootstrap_passed_on_fakes,
    _Cells,
    _refused_receipt_lines,
    _verification_argv,
    runner,
)

from fixtures.production_launch import ACQ, BLD, ledger_document, ledger_row, specification_for
from fixtures.production_runtime import CANARIES, PLAN_DIGEST, RUN_ID, encode, slice_document
from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar import launch_records as lr
from kalpamani.data.production.sharadar import launch_store as ls
from kalpamani.data.production.sharadar import verification_cells as vc
from kalpamani.data.production.sharadar.entry import TaskOutcome

pytestmark = pytest.mark.unit

NOW: Final = datetime(2026, 9, 18, 16, 0, tzinfo=UTC)
#: A v1 plan digest: a digest the v2 compiler never produces for any slice (never typed as
#: a real value; the historical parser only requires a digest).
V1_PLAN_DIGEST: Final = "89" * 32
#: The v1 slice shape historical run 1 and the 2026-09-17 acquisition verification launches
#: carried: 96 requests over a 16 MiB ceiling -- not compilable under pagination v2.
V1_SLICE: Final[dict[str, Any]] = {
    **slice_document(),
    "request_count": 96,
    "max_response_bytes": 16 * 1024 * 1024,
}


# ---------------------------------------------------------------------------
# Fixtures: a v1 reservation from a v2 specification
# ---------------------------------------------------------------------------


def _v1_specification_document(
    identity: str = "verify-" + RUN_ID, *, inputs: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A verification specification whose workload is the superseded v1 shape."""
    specification = specification_for(
        actor=ACQ, kind="verification", identity=identity, inputs=inputs
    ).document()
    specification["workload"] = {"slice": dict(V1_SLICE), "plan_digest": V1_PLAN_DIGEST}
    return specification


def _v1_reservation_document(specification: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": lr.RECORD_SCHEMA_VERSION,
        "contract_id": ls.RESERVATION_CONTRACT_ID,
        "identity": specification["identity"],
        "actor": specification["actor"],
        "kind": specification["kind"],
        "specification_digest": sha256_hex(canonical_bytes(specification)),
        "specification": specification,
        "reserved_at": NOW.isoformat(),
    }


def _v1_reservation_bytes(**changes: Any) -> bytes:
    document = _v1_reservation_document(_v1_specification_document())
    document.update(changes)
    return canonical_bytes(document)


def _v1_ledger_row(identity: str, outcome: str = "VERIFIED") -> dict[str, Any]:
    return ledger_row(
        identity,
        actor=ACQ,
        kind="verification",
        outcome=outcome,
        slice=dict(V1_SLICE),
        plan_digest=V1_PLAN_DIGEST,
    )


# ---------------------------------------------------------------------------
# A. The historical parser and the store
# ---------------------------------------------------------------------------


def test_a_supported_v1_reservation_reads_as_historical_evidence_and_nothing_else() -> None:
    raw = _v1_reservation_bytes()
    with pytest.raises(ls.StoreError) as strict:
        ls.parse_reservation(raw)
    assert strict.value.defect is ls.StoreDefect.RESERVATION_MALFORMED
    historical = ls.parse_reservation_for_evidence(raw)
    assert type(historical) is ls.HistoricalReservation
    assert "Reservation" not in [base.__name__ for base in ls.HistoricalReservation.__mro__[1:]]
    assert historical.workload_contract_id == lr.SUPERSEDED_WORKLOAD_CONTRACT_ID
    assert historical.workload_contract_id == "kalpamani-production-acquisition-plan/v1"
    document = json.loads(raw)
    assert historical.specification_digest == document["specification_digest"]
    assert historical.specification.digest == document["specification_digest"]
    assert historical.stored_sha256 == sha256_hex(raw)
    # The workload is exactly what was stored: never recompiled, reinterpreted or upgraded.
    assert historical.specification.workload == {
        "slice": dict(V1_SLICE),
        "plan_digest": V1_PLAN_DIGEST,
    }
    assert historical.specification.workload["plan_digest"] != PLAN_DIGEST
    # Its documents are the stored ones; its reprs carry no value.
    assert historical.specification.document() == document["specification"]
    for text in (repr(historical), repr(historical.historical)):
        assert "v1" in text and historical.identity not in text
    for canary in CANARIES:
        assert canary not in repr(historical)
    # Neither type may be subclassed.
    for kind in (ls.HistoricalReservation, lr.HistoricalSpecification):
        with pytest.raises(TypeError):
            type("Sub", (kind,), {})


def test_a_current_v2_reservation_reads_unchanged_through_both_paths() -> None:
    specification = specification_for(actor=ACQ, kind="verification", identity="verify-" + RUN_ID)
    reservation = ls.Reservation(
        identity=specification.identity,
        actor=ACQ,
        kind=lr.LaunchKind.VERIFICATION,
        specification=specification,
        reserved_at=NOW,
    )
    raw = canonical_bytes(reservation.document())
    strict = ls.parse_reservation(raw)
    evidence = ls.parse_reservation_for_evidence(raw)
    assert type(evidence) is ls.Reservation and evidence == strict
    # A current document is never read as historical.
    with pytest.raises(lr.LaunchRecordError) as refused:
        lr.parse_historical_specification(specification.document())
    assert refused.value.defect is lr.LaunchRecordDefect.WORKLOAD_CURRENT


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda d: d.__setitem__("contract_id", "kalpamani-launch-reservation/v9"),
            id="unknown_contract",
        ),
        pytest.param(lambda d: d.__setitem__("schema_version", 2), id="unknown_schema"),
        pytest.param(
            lambda d: d["specification"].__setitem__("contract_id", "other/v1"),
            id="unknown_specification_contract",
        ),
        pytest.param(
            lambda d: d["specification"]["workload"].pop("plan_digest"), id="v1_without_plan_digest"
        ),
        pytest.param(
            lambda d: d["specification"]["workload"].__setitem__("plan_digest", "not-a-digest"),
            id="v1_plan_digest_not_a_digest",
        ),
        pytest.param(
            lambda d: d["specification"]["workload"].__setitem__("extra", 1),
            id="v1_extra_workload_field",
        ),
        pytest.param(
            lambda d: d["specification"]["workload"]["slice"].__setitem__("request_count", 0),
            id="v1_slice_malformed",
        ),
        pytest.param(
            lambda d: d["specification"]["workload"]["slice"].pop("datasets"),
            id="v1_slice_missing_field",
        ),
        pytest.param(lambda d: d["specification"].pop("placement"), id="v1_missing_block"),
        pytest.param(
            lambda d: d.__setitem__("specification_digest", "00" * 32), id="digest_mismatch"
        ),
        pytest.param(
            lambda d: d.__setitem__("identity", "verify-someone-else"), id="identity_mismatch"
        ),
        pytest.param(lambda d: d.__setitem__("actor", "build"), id="actor_mismatch"),
        pytest.param(lambda d: d.__setitem__("kind", "production"), id="kind_mismatch"),
        pytest.param(lambda d: d.pop("reserved_at"), id="envelope_field_missing"),
    ],
)
def test_an_unsupported_or_malformed_v1_reservation_is_refused_by_both_reads(mutate: Any) -> None:
    document = _v1_reservation_document(_v1_specification_document())
    mutate(document)
    raw = canonical_bytes(document)
    for parse in (ls.parse_reservation, ls.parse_reservation_for_evidence):
        with pytest.raises(ls.StoreError) as refused:
            parse(raw)
        assert refused.value.defect is ls.StoreDefect.RESERVATION_MALFORMED
    # Corrupted bytes and the wrong type refuse too.
    for bad in (raw[:-7], b"\xff" + raw, raw.decode().replace('"', "'").encode()):
        with pytest.raises(ls.StoreError):
            ls.parse_reservation_for_evidence(bad)
    with pytest.raises(ls.StoreError):
        ls.parse_reservation_for_evidence(json.loads(raw))


def test_a_build_specification_has_no_superseded_shape() -> None:
    specification = specification_for(actor=BLD, kind="verification", identity="verify-" + RUN_ID)
    document = specification.document()
    document["workload"] = {"runs": [{"identity": RUN_ID}]}  # malformed under every contract
    with pytest.raises(lr.LaunchRecordError) as refused:
        lr.parse_historical_specification(document)
    assert refused.value.defect is lr.LaunchRecordDefect.FIELD_MALFORMED


def test_historical_reservations_are_never_executable_recoverable_or_reservable(
    tmp_path: Path,
) -> None:
    store = ls.LaunchStore(ledger_path=tmp_path / "ledger.json", records_dir=tmp_path / "records")
    identity = "verify-" + RUN_ID
    (tmp_path / "ledger.json").write_bytes(encode(ledger_document([_v1_ledger_row(identity)])))
    store.reservations_path.mkdir()
    raw = _v1_reservation_bytes()
    store.reservation_path(identity).write_bytes(raw)
    # The strict reads -- what reserve, recover, execute and the verdict use -- refuse.
    with pytest.raises(ls.StoreError) as strict:
        store.reservation(identity)
    assert strict.value.defect is ls.StoreDefect.RESERVATION_MALFORMED
    with pytest.raises(ls.StoreError):
        store.reservations()
    # The evidence reads return it, typed historical.
    evidence = store.evidence_reservation(identity)
    assert type(evidence) is ls.HistoricalReservation
    assert [type(r) for r in store.evidence_reservations()] == [ls.HistoricalReservation]
    # A reservation over that identity is refused (the file exists) and the bytes never move.
    ledger, _digest = store.read_ledger()
    with pytest.raises(ls.StoreError) as taken:
        store.reserve(
            ls.Reservation(
                identity=identity,
                actor=ACQ,
                kind=lr.LaunchKind.VERIFICATION,
                specification=specification_for(actor=ACQ, kind="verification", identity=identity),
                reserved_at=NOW,
            )
        )
    assert taken.value.defect is ls.StoreDefect.RESERVATION_EXISTS
    assert store.reservation_path(identity).read_bytes() == raw
    # With a ledger row it is reconciled history, not interrupted work.
    assert store.unreconciled(ledger) == []
    # The launch tool's own reads are the strict ones: recovery and the verdict go through
    # ``store.reservation`` and nothing here widened them.
    source = Path(launch.__file__).read_text(encoding="utf-8")
    assert "evidence_reservation(" not in source
    assert source.count("store.reservation(") >= 3


def test_an_orphaned_historical_reservation_is_a_hard_refusal(tmp_path: Path) -> None:
    store = ls.LaunchStore(ledger_path=tmp_path / "ledger.json", records_dir=tmp_path / "records")
    identity = "verify-" + RUN_ID
    (tmp_path / "ledger.json").write_bytes(encode(ledger_document([])))
    store.reservations_path.mkdir()
    store.reservation_path(identity).write_bytes(_v1_reservation_bytes())
    ledger, _digest = store.read_ledger()
    with pytest.raises(ls.StoreError) as refused:
        store.unreconciled(ledger)
    assert refused.value.defect is ls.StoreDefect.RESERVATION_ORPHANED
    # A current reservation without a row stays what it was: interrupted work, listed.
    current = specification_for(actor=ACQ, kind="verification", identity="verify-other-" + RUN_ID)
    store.reservation_path(identity).unlink()
    store.reserve(
        ls.Reservation(
            identity=current.identity,
            actor=ACQ,
            kind=lr.LaunchKind.VERIFICATION,
            specification=current,
            reserved_at=NOW,
        )
    )
    assert store.unreconciled(ledger) == [current.identity]


# ---------------------------------------------------------------------------
# B. The derivation: historical evidence is HISTORICAL, never current, never a pass
# ---------------------------------------------------------------------------


def _historical_chain(
    *, release_mode: str = "NORMAL"
) -> tuple[ls.HistoricalReservation, lr.LaunchRecord, dict[str, Any], vc.PreparedCell]:
    from test_production_launch_script import _launch_record

    from kalpamani.data.production.sharadar.entry import EXIT_STATUS, TaskEntry
    from kalpamani.data.production.sharadar.release import ReleaseMode

    identity = "verify-" + RUN_ID
    mode = ReleaseMode(release_mode)
    document = _v1_specification_document(identity)
    document["release_mode"] = mode.value
    historical = ls.parse_reservation_for_evidence(
        canonical_bytes(_v1_reservation_document(document))
    )
    assert type(historical) is ls.HistoricalReservation
    record = _launch_record(
        entry=TaskEntry.ACQUISITION_VERIFY,
        identity=identity,
        harness=None,
        kind=lr.LaunchKind.VERIFICATION,
        specification=historical.specification,
    )
    cell_id = {
        "NORMAL": "R1-ACQ-BOOTSTRAP",
        "WITHHELD": "R1-ACQ-NO-RELEASE",
        "MISMATCHED": "R1-ACQ-RELEASE-MISMATCH",
    }[release_mode]
    expected = vc.definition(cell_id).expected_outcome
    record = lr.LaunchRecord(
        **{
            **{f: getattr(record, f) for f in lr.LaunchRecord.__slots__},
            "release_mode": mode,
            "observed_exit_code": EXIT_STATUS[
                TaskOutcome.VERIFIED_BOOTSTRAP if expected is None else expected
            ],
        }
    )
    row = _v1_ledger_row(identity, "VERIFIED" if expected is None else "REFUSED")
    prepared = vc.PreparedCell(
        cell_id=cell_id,
        identity=identity,
        specification_digest=historical.specification_digest,
        prepared_at=NOW,
    )
    return historical, record, row, prepared


def test_historical_evidence_derives_historical_and_is_never_counted_current() -> None:
    from test_production_verification_cells import _evidence, _r3_record

    r3_record = _r3_record()
    for release_mode in ("NORMAL", "WITHHELD", "MISMATCHED"):
        historical, record, row, prepared = _historical_chain(release_mode=release_mode)
        fields: dict[str, Any] = {
            "rows": [ledger_row(RUN_ID), row],
            "launch_records": {historical.identity: record},
            "r3_record": r3_record,
            "inputs_digest": r3_record.digest,
        }
        if release_mode != "NORMAL":
            fields["negative_evidence"] = {
                historical.specification_digest: (
                    vc.NegativeLaunchEvidence(
                        cell_id=prepared.cell_id,
                        actor=ACQ,
                        identity=historical.identity,
                        specification_digest=historical.specification_digest,
                        release_mode=historical.specification.release_mode,
                        receipt_outcome=vc.definition(prepared.cell_id).expected_outcome,  # type: ignore[arg-type]
                        counts={"s3_operations": 0, "secret_retrievals": 0, "provider_requests": 0},
                        released=False,
                        recorded_at=NOW,
                    ),
                )
            }
        evidence = _evidence(**fields)
        with_historical = vc.RecordedEvidence(
            **{f: getattr(evidence, f) for f in vc.RecordedEvidence.__dataclass_fields__},
        )
        with_historical = vc.RecordedEvidence(
            **{
                **{f: getattr(evidence, f) for f in vc.RecordedEvidence.__dataclass_fields__},
                "historical_reservations": {historical.identity: historical},
            }
        )
        states = vc.derive_states(with_historical, {prepared.cell_id: prepared})
        state = states[prepared.cell_id]
        assert state.status is vc.CellStatus.HISTORICAL, state.reason
        assert "kalpamani-production-acquisition-plan/v1" in state.reason
        assert "re-verification" in state.reason
        assert vc.aggregate(states) is vc.AggregateStatus.INCOMPLETE
        # Without the historical reservation the same chain is UNBOUND -- never PASSED.
        states = vc.derive_states(evidence, {prepared.cell_id: prepared})
        assert states[prepared.cell_id].status is vc.CellStatus.UNBOUND
        # A record that does not bind to the historical reservation is UNBOUND too.
        broken = lr.LaunchRecord(
            **{
                **{f: getattr(record, f) for f in lr.LaunchRecord.__slots__},
                "plan_digest": "77" * 32,
            }
        )
        states = vc.derive_states(
            vc.RecordedEvidence(
                **{
                    **{
                        f: getattr(with_historical, f)
                        for f in vc.RecordedEvidence.__dataclass_fields__
                    },
                    "launch_records": {historical.identity: broken},
                }
            ),
            {prepared.cell_id: prepared},
        )
        assert states[prepared.cell_id].status is vc.CellStatus.UNBOUND


def test_the_prepared_cells_document_carries_a_closed_supersession_link() -> None:
    link = vc.SupersededBinding(
        identity="verify-" + RUN_ID,
        specification_digest="ab" * 32,
        reservation_sha256="cd" * 32,
        cells_document_sha256="ef" * 32,
        registration_sha256="12" * 32,
        superseded_at=NOW,
    )
    prepared = vc.PreparedCell(
        cell_id="R1-ACQ-BOOTSTRAP",
        identity="verify-fresh-" + RUN_ID,
        specification_digest="34" * 32,
        prepared_at=NOW,
        supersedes=link,
    )
    document = vc.cells_document([prepared])
    assert document["cells"]["R1-ACQ-BOOTSTRAP"]["supersedes"]["prior_evidence"] == "HISTORICAL"
    assert vc.parse_cells_document(canonical_bytes(document)) == {"R1-ACQ-BOOTSTRAP": prepared}
    # Without the link the block is exactly the accepted one.
    plain = vc.PreparedCell(
        cell_id="R1-ACQ-BOOTSTRAP",
        identity="verify-fresh-" + RUN_ID,
        specification_digest="34" * 32,
        prepared_at=NOW,
    )
    assert set(plain.document()) == {"cell_id", "identity", "specification_digest", "prepared_at"}
    mutations: list[Callable[[dict[str, Any]], Any]] = [
        lambda d: d["cells"]["R1-ACQ-BOOTSTRAP"]["supersedes"].__setitem__(
            "prior_evidence", "PASSED"
        ),
        lambda d: d["cells"]["R1-ACQ-BOOTSTRAP"]["supersedes"].__setitem__(
            "identity", "verify-fresh-" + RUN_ID
        ),
        lambda d: d["cells"]["R1-ACQ-BOOTSTRAP"]["supersedes"].pop("reservation_sha256"),
        lambda d: d["cells"]["R1-ACQ-BOOTSTRAP"]["supersedes"].__setitem__("extra", 1),
        lambda d: d["cells"]["R1-ACQ-BOOTSTRAP"]["supersedes"].__setitem__(
            "registration_sha256", "xyz"
        ),
        lambda d: d["cells"]["R1-ACQ-BOOTSTRAP"].__setitem__("supersedes", []),
    ]
    for mutate in mutations:
        broken: dict[str, Any] = copy.deepcopy(document)
        mutate(broken)
        with pytest.raises(vc.CellsDocumentError):
            vc.parse_cells_document(canonical_bytes(broken))


# ---------------------------------------------------------------------------
# C. The runner on a real (temporary) store
# ---------------------------------------------------------------------------


def _seed_v1_history(cells: _Cells, identity: str, *, with_row: bool = True) -> bytes:
    """Bind ``R1-ACQ-BOOTSTRAP`` to a v1 launch: reservation, launch record, ledger row."""
    from test_production_launch_script import _launch_record

    from kalpamani.data.production.sharadar.entry import EXIT_STATUS, TaskEntry

    scenario = cells.scenario
    inputs = json.loads(scenario.inputs.read_bytes())
    document = _v1_specification_document(identity, inputs=inputs)
    raw = canonical_bytes(_v1_reservation_document(document))
    store = scenario.store()
    store.reservations_path.mkdir(exist_ok=True)
    store.reservation_path(identity).write_bytes(raw)
    historical = ls.parse_reservation_for_evidence(raw)
    assert type(historical) is ls.HistoricalReservation
    record = _launch_record(
        entry=TaskEntry.ACQUISITION_VERIFY,
        identity=identity,
        harness=None,
        kind=lr.LaunchKind.VERIFICATION,
        specification=historical.specification,
        configuration_digest=historical.specification.target.configuration_digest,
    )
    record = lr.LaunchRecord(
        **{
            **{f: getattr(record, f) for f in lr.LaunchRecord.__slots__},
            "observed_exit_code": EXIT_STATUS[TaskOutcome.VERIFIED_BOOTSTRAP],
        }
    )
    scenario.records.mkdir(exist_ok=True)
    (scenario.records / f"launch-record-{identity}.json").write_bytes(
        canonical_bytes(record.document())
    )
    if with_row:
        ledger = json.loads(scenario.ledger.read_bytes())
        ledger["rows"].append(_v1_ledger_row(identity))
        scenario.ledger.write_bytes(encode(ledger))
    runner.write_prepared(
        store,
        {
            "R1-ACQ-BOOTSTRAP": vc.PreparedCell(
                cell_id="R1-ACQ-BOOTSTRAP",
                identity=identity,
                specification_digest=historical.specification_digest,
                prepared_at=NOW,
            )
        },
    )
    return raw


def _change_registration(cells: _Cells, actor: Any = ACQ) -> None:
    """A new image for the actor's verification target: the registration now in force differs."""
    document = json.loads(cells.scenario.inputs.read_bytes())
    target = document["actors"][actor.value]["verification"]
    target["image_digest"] = "sha256:" + "99" * 32
    target["task_definition"]["image_digest"] = "sha256:" + "99" * 32
    cells.scenario.inputs.write_bytes(encode(document))


def test_the_runner_classifies_a_real_v1_reservation_historical_under_a_new_registration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cells = _Cells(tmp_path)
    identity = "verify-" + RUN_ID
    raw = _seed_v1_history(cells, identity)
    # Under the registration the v1 launch was made against, a superseded workload bound to
    # the registered target is a contradiction: refused, never classified.
    assert cells.main(*cells.base()) == runner.EXIT_REFUSED_RECORDS
    assert runner.SENTENCES["refused_records"] in capsys.readouterr().out
    _change_registration(cells)
    assert cells.main(*cells.base()) == runner.EXIT_MATRIX
    out = capsys.readouterr().out
    assert "cell=R1-ACQ-BOOTSTRAP ref=R-1 kind=RUNTIME_LAUNCH status=HISTORICAL" in out
    assert "status=PASSED" not in out.split("cell=R4")[0].replace(
        "cell=R3 ref=R-3 kind=CONTROL_R3 status=PASSED", ""
    )
    assert "aggregate=INCOMPLETE" in out
    assert cells.scenario.clients.constructions == []
    assert cells.scenario.store().reservation_path(identity).read_bytes() == raw
    for canary in (*CANARIES, identity):
        assert canary not in out


def test_the_runner_refuses_an_orphaned_or_uncorroborated_v1_reservation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cells = _Cells(tmp_path)
    identity = "verify-" + RUN_ID
    _seed_v1_history(cells, identity, with_row=False)
    _change_registration(cells)
    assert cells.main(*cells.base()) == runner.EXIT_REFUSED_RECORDS
    capsys.readouterr()
    # A row that does not carry the reservation's workload is not corroboration.
    ledger = json.loads(cells.scenario.ledger.read_bytes())
    ledger["rows"].append(_v1_ledger_row(identity) | {"plan_digest": "66" * 32})
    cells.scenario.ledger.write_bytes(encode(ledger))
    assert cells.main(*cells.base()) == runner.EXIT_REFUSED_RECORDS
    assert cells.scenario.clients.constructions == []


def _passed_build_trio(
    cells: _Cells, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> dict[str, str]:
    """The three build R-1 cells PASSED on fakes; returns cell id -> identity."""
    scenario = cells.scenario
    fresh_descriptions = copy.deepcopy(scenario.ecs.descriptions)
    identities = {"R1-BLD-BOOTSTRAP": "verify-synthetic-production-build-0010"}
    _bootstrap_passed_on_fakes(cells, capsys, argv, identities["R1-BLD-BOOTSTRAP"])
    for cell_id, suffix, exit_code, outcome in (
        ("R1-BLD-NO-RELEASE", "0011", 15, TaskOutcome.REFUSED_NO_RELEASE),
        ("R1-BLD-RELEASE-MISMATCH", "0012", 16, TaskOutcome.REFUSED_RELEASE_MISMATCH),
    ):
        negative = "verify-synthetic-production-build-" + suffix
        identities[cell_id] = negative
        assert (
            cells.main(*cells.base(), "--prepare-cell", cell_id, "--identity", negative, *argv)
            == runner.EXIT_PREPARED
        )
        digest = capsys.readouterr().out.split("specification_digest=")[1].split()[0]
        scenario.authorize(identity=negative, specification_digest=digest)
        scenario.ecs.descriptions = copy.deepcopy(fresh_descriptions)
        scenario.ecs.descriptions[-1]["containers"][0]["exitCode"] = exit_code
        assert (
            cells.main(
                *cells.base(),
                "--execute-cell",
                cell_id,
                *argv,
                "--authorization",
                str(scenario.authorization),
                runner.AUTHORIZATION_FLAG,
            )
            == launch.EXIT_LAUNCH_TERMINAL
        )
        capsys.readouterr()
        record_path = next(
            path
            for path in scenario.files("launch-record")
            if lr.parse_launch_record(path.read_bytes()).identity == negative
        )
        record = lr.parse_launch_record(record_path.read_bytes())
        lines = scenario.root / f"receipt-{suffix}.txt"
        lines.write_text(_refused_receipt_lines(record, outcome), "utf-8")
        assert (
            cells.main(
                *cells.base(),
                "--complete-cell",
                cell_id,
                "--launch-record",
                str(record_path),
                "--receipt-lines",
                str(lines),
            )
            == launch.EXIT_ROW_COMPLETED
        )
        assert (
            f"cell={cell_id} ref=R-1 kind=NEGATIVE_LAUNCH status=PASSED" in capsys.readouterr().out
        )
    return identities


def _snapshot(scenario: Any) -> dict[Path, bytes]:
    """Every record, reservation and the ledger, by path."""
    root = scenario.ledger.parent
    return {
        path: path.read_bytes()
        for path in sorted(root.rglob("*.json"))
        if not path.name.endswith(runner.CELLS_SUFFIX)
        and runner.CELLS_SUPERSEDED_INFIX not in path.name
        and path.name not in ("launch-inputs.json", "authorization.json")
    }


def test_a_registration_historical_cell_is_rebound_and_everything_is_preserved(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cells = _Cells(tmp_path, actor=BLD, ledger_rows=[])
    scenario = cells.scenario
    argv = _verification_argv(scenario)
    bootstrap = "verify-synthetic-production-build-0010"
    digest, record_path, _record = _bootstrap_passed_on_fakes(cells, capsys, argv, bootstrap)
    before = _snapshot(scenario)
    cells_path = scenario.ledger.with_name("ledger.json" + runner.CELLS_SUFFIX)
    cells_before = cells_path.read_bytes()
    specifications_before = len(scenario.files("launch-specification"))
    reservation_path = scenario.store().reservation_path(bootstrap)

    # Same registration: a PASSED cell is never rebound (ADR-0052 s.2.3), nothing is written.
    fresh = "verify-synthetic-production-build-0030"
    assert (
        cells.main(*cells.base(), "--prepare-cell", "R1-BLD-BOOTSTRAP", "--identity", fresh, *argv)
        == runner.EXIT_REFUSED_CELL_STATE
    )
    capsys.readouterr()
    assert len(scenario.files("launch-specification")) == specifications_before
    assert cells_path.read_bytes() == cells_before and _snapshot(scenario) == before

    # The registration changes: the cell reads HISTORICAL, and only then may it be rebound.
    _change_registration(cells, BLD)
    registration_sha256 = sha256_hex(scenario.inputs.read_bytes())
    assert cells.main(*cells.base()) == runner.EXIT_MATRIX
    out = capsys.readouterr().out
    assert "cell=R1-BLD-BOOTSTRAP ref=R-1 kind=RUNTIME_LAUNCH status=HISTORICAL" in out
    assert (
        cells.main(*cells.base(), "--prepare-cell", "R1-BLD-BOOTSTRAP", "--identity", fresh, *argv)
        == runner.EXIT_PREPARED
    )
    out = capsys.readouterr().out
    new_digest = out.split("specification_digest=")[1].split()[0]
    assert new_digest != digest and f"supersedes={bootstrap}" in out
    # Every prior record, reservation and ledger row is byte for byte what it was.
    assert _snapshot(scenario) == {
        **before,
        **{p: b for p, b in _snapshot(scenario).items() if p not in before},
    }
    assert all(_snapshot(scenario)[path] == raw for path, raw in before.items())
    assert reservation_path.read_bytes() == before[reservation_path]
    assert record_path.read_bytes() == before[record_path]
    assert len(scenario.files("launch-specification")) == specifications_before + 1
    # The previous cells document is preserved beside the ledger, byte for byte.
    preserved = sorted(
        scenario.ledger.parent.glob("ledger.json" + runner.CELLS_SUPERSEDED_INFIX + "*.json")
    )
    assert len(preserved) == 1 and preserved[0].read_bytes() == cells_before
    # The new binding names what it superseded, digest-bound.
    binding = cells.cells()["R1-BLD-BOOTSTRAP"]
    assert binding["identity"] == fresh and binding["specification_digest"] == new_digest
    assert binding["supersedes"] == {
        "identity": bootstrap,
        "specification_digest": digest,
        "reservation_sha256": sha256_hex(before[reservation_path]),
        "cells_document_sha256": sha256_hex(cells_before),
        "registration_sha256": registration_sha256,
        "prior_evidence": "HISTORICAL",
        "superseded_at": scenario.clock.now().isoformat(),
    }
    # The matrix: the cell is PREPARED under the fresh identity; the old pass counts for nothing;
    # the corroboration cell stays prerequisite-bound.
    assert cells.main(*cells.base()) == runner.EXIT_MATRIX
    out = capsys.readouterr().out
    assert "cell=R1-BLD-BOOTSTRAP ref=R-1 kind=RUNTIME_LAUNCH status=PREPARED" in out
    assert "cell=R2-BLD-CORROBORATION ref=R-2 kind=RUNTIME_LAUNCH status=BLOCKED" in out
    assert "cell=R2-BLD-ISOLATION ref=R-2 kind=ISOLATION_VERDICT status=BLOCKED" in out
    assert "aggregate=INCOMPLETE" in out
    assert len(scenario.ecs.names("run_task")) == 1  # the one historical launch; none since
    # Now PREPARED: a second rebind over another fresh identity is refused, nothing written.
    assert (
        cells.main(
            *cells.base(),
            "--prepare-cell",
            "R1-BLD-BOOTSTRAP",
            "--identity",
            "verify-synthetic-production-build-0031",
            *argv,
        )
        == runner.EXIT_REFUSED_CELL_STATE
    )
    capsys.readouterr()
    assert cells.cells()["R1-BLD-BOOTSTRAP"]["identity"] == fresh
    assert len(scenario.files("launch-specification")) == specifications_before + 1
    # The spent prior identity, and the fresh one already bound, are refused for any cell.
    for spent in (bootstrap, fresh):
        assert (
            cells.main(
                *cells.base(), "--prepare-cell", "R1-BLD-NO-RELEASE", "--identity", spent, *argv
            )
            != runner.EXIT_PREPARED
        )
        capsys.readouterr()
        assert "R1-BLD-NO-RELEASE" not in cells.cells()
    assert len(scenario.files("launch-specification")) == specifications_before + 1


def test_a_malformed_or_incomplete_history_is_never_rebound_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cells = _Cells(tmp_path, actor=BLD, ledger_rows=[])
    scenario = cells.scenario
    argv = _verification_argv(scenario)
    bootstrap = "verify-synthetic-production-build-0010"
    _digest, record_path, _record = _bootstrap_passed_on_fakes(cells, capsys, argv, bootstrap)
    _change_registration(cells, BLD)
    cells_path = scenario.ledger.with_name("ledger.json" + runner.CELLS_SUFFIX)
    cells_before = cells_path.read_bytes()
    specifications = len(scenario.files("launch-specification"))
    reservation_path = scenario.store().reservation_path(bootstrap)
    reservation_raw = reservation_path.read_bytes()
    fresh = "verify-synthetic-production-build-0030"
    prepare = [*cells.base(), "--prepare-cell", "R1-BLD-BOOTSTRAP", "--identity", fresh, *argv]

    def nothing_written() -> None:
        assert len(scenario.files("launch-specification")) == specifications
        assert cells_path.read_bytes() == cells_before
        assert not list(
            scenario.ledger.parent.glob("ledger.json" + runner.CELLS_SUPERSEDED_INFIX + "*")
        )

    # A corrupted prior reservation: the evidence read refuses before anything is written.
    reservation_path.write_bytes(reservation_raw[:-3] + b"xx}")
    assert cells.main(*prepare) == runner.EXIT_REFUSED_RECORDS
    capsys.readouterr()
    nothing_written()
    reservation_path.write_bytes(reservation_raw)
    # A prior launch record that no longer binds: the chain is UNBOUND, not HISTORICAL.
    record_raw = record_path.read_bytes()
    record_path.unlink()
    assert cells.main(*prepare) == runner.EXIT_REFUSED_CELL_STATE
    capsys.readouterr()
    nothing_written()
    record_path.write_bytes(record_raw)
    # A prior identity never launched (binding without a row or reservation): refused.
    runner.write_prepared(
        scenario.store(),
        {
            "R1-BLD-BOOTSTRAP": vc.PreparedCell(
                cell_id="R1-BLD-BOOTSTRAP",
                identity="verify-synthetic-production-build-0099",
                specification_digest="ab" * 32,
                prepared_at=NOW,
            )
        },
    )
    cells_before = cells_path.read_bytes()
    assert cells.main(*prepare) == runner.EXIT_REFUSED_CELL_STATE
    capsys.readouterr()
    nothing_written()


def test_an_interrupted_rebind_leaves_no_authoritative_half_binding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    cells = _Cells(tmp_path, actor=BLD, ledger_rows=[])
    scenario = cells.scenario
    argv = _verification_argv(scenario)
    bootstrap = "verify-synthetic-production-build-0010"
    _bootstrap_passed_on_fakes(cells, capsys, argv, bootstrap)
    _change_registration(cells, BLD)
    cells_path = scenario.ledger.with_name("ledger.json" + runner.CELLS_SUFFIX)
    cells_before = cells_path.read_bytes()
    specifications = len(scenario.files("launch-specification"))
    fresh = "verify-synthetic-production-build-0030"
    prepare = [*cells.base(), "--prepare-cell", "R1-BLD-BOOTSTRAP", "--identity", fresh, *argv]
    original = runner.write_prepared

    def interrupted(store: Any, prepared: dict[str, Any]) -> None:
        raise runner.CellsRefusalError("refused_records", runner.EXIT_REFUSED_RECORDS)

    monkeypatch.setattr(runner, "write_prepared", interrupted)
    assert cells.main(*prepare) == runner.EXIT_REFUSED_RECORDS
    capsys.readouterr()
    # The specification written before the interruption is removed; the previous binding
    # stays authoritative; the preserved copy of the cells document is byte-identical.
    assert len(scenario.files("launch-specification")) == specifications
    assert cells_path.read_bytes() == cells_before
    preserved = sorted(
        scenario.ledger.parent.glob("ledger.json" + runner.CELLS_SUPERSEDED_INFIX + "*")
    )
    assert [p.read_bytes() for p in preserved] == [cells_before]
    assert scenario.store().lock_path.exists() is False
    # The rebind then succeeds under the same fresh identity: nothing was consumed.
    monkeypatch.setattr(runner, "write_prepared", original)
    assert cells.main(*prepare) == runner.EXIT_PREPARED
    capsys.readouterr()
    assert cells.cells()["R1-BLD-BOOTSTRAP"]["identity"] == fresh
    assert len(scenario.files("launch-specification")) == specifications + 1


def test_the_six_cell_lifecycle_after_a_registration_change_on_fakes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The build trio PASSED under one registration; the registration changes; each of the
    three reads HISTORICAL; each is rebound with a fresh identity and a new specification;
    the negatives are blocked behind the unpassed new bootstrap; R-2 stays blocked."""
    cells = _Cells(tmp_path, actor=BLD, ledger_rows=[])
    scenario = cells.scenario
    argv = _verification_argv(scenario)
    identities = _passed_build_trio(cells, capsys, argv)
    before = _snapshot(scenario)
    _change_registration(cells, BLD)
    assert cells.main(*cells.base()) == runner.EXIT_MATRIX
    out = capsys.readouterr().out
    for cell_id in identities:
        assert f"cell={cell_id} " in out and f"cell={cell_id} ref=R-1" in out
        line = next(line for line in out.splitlines() if line.startswith(f"cell={cell_id} "))
        assert "status=HISTORICAL" in line, line
    digests: dict[str, str] = {}
    for index, cell_id in enumerate(
        ("R1-BLD-BOOTSTRAP", "R1-BLD-NO-RELEASE", "R1-BLD-RELEASE-MISMATCH")
    ):
        fresh = f"verify-synthetic-production-build-004{index}"
        assert (
            cells.main(*cells.base(), "--prepare-cell", cell_id, "--identity", fresh, *argv)
            == runner.EXIT_PREPARED
        )
        out = capsys.readouterr().out
        digests[cell_id] = out.split("specification_digest=")[1].split()[0]
        assert f"supersedes={identities[cell_id]}" in out
        assert cells.cells()[cell_id]["identity"] == fresh
        assert cells.cells()[cell_id]["supersedes"]["identity"] == identities[cell_id]
    assert len(set(digests.values())) == 3
    assert all(_snapshot(scenario)[path] == raw for path, raw in before.items())
    assert cells.main(*cells.base()) == runner.EXIT_MATRIX
    out = capsys.readouterr().out
    assert "cell=R1-BLD-BOOTSTRAP ref=R-1 kind=RUNTIME_LAUNCH status=PREPARED" in out
    assert "cell=R1-BLD-NO-RELEASE ref=R-1 kind=NEGATIVE_LAUNCH status=BLOCKED" in out
    assert "cell=R1-BLD-RELEASE-MISMATCH ref=R-1 kind=NEGATIVE_LAUNCH status=BLOCKED" in out
    assert "cell=R2-BLD-CORROBORATION ref=R-2 kind=RUNTIME_LAUNCH status=BLOCKED" in out
    assert "aggregate=INCOMPLETE" in out
    assert len(scenario.ecs.names("run_task")) == 3  # the three historical launches; none since
    # R-2 stays prerequisite-bound: BLOCKED behind the unpassed new bootstrap, and its
    # execution refuses on the prerequisite whatever authorization is offered.
    assert cells.main(
        *cells.base(),
        "--execute-cell",
        "R2-BLD-CORROBORATION",
        *argv,
        "--authorization",
        str(scenario.authorization),
        runner.AUTHORIZATION_FLAG,
    ) in {runner.EXIT_REFUSED_PREREQUISITE, runner.EXIT_REFUSED_CELL_STATE}
    capsys.readouterr()
    assert len(scenario.ecs.names("run_task")) == 3


# ---------------------------------------------------------------------------
# D. Mutation controls: the regressions catch the guards being removed
# ---------------------------------------------------------------------------


def _mutant(tmp_path: Path, name: str, old: str, new: str) -> Any:
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.count(old) == 1, old
    path = tmp_path / f"{name}.py"
    path.write_text(source.replace(old, new), encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _rebind_argv(cells: _Cells, argv: list[str], identity: str) -> list[str]:
    return [*cells.base(), "--prepare-cell", "R1-BLD-BOOTSTRAP", "--identity", identity, *argv]


def test_mutation_controls_for_the_rebinding_guards(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    cells = _Cells(tmp_path, actor=BLD, ledger_rows=[])
    scenario = cells.scenario
    argv = _verification_argv(scenario)
    bootstrap = "verify-synthetic-production-build-0010"
    _bootstrap_passed_on_fakes(cells, capsys, argv, bootstrap)
    fields = scenario.fields()
    fields["r3_binding_source"] = lambda: BINDING
    cells_path = scenario.ledger.with_name("ledger.json" + runner.CELLS_SUFFIX)

    # 1. The historical-only guard removed. A second scenario whose bootstrap is LAUNCHED
    #    (row from the exit code, receipt never verified) under a changed registration:
    #    the registration differs, so only the guard stands between it and a rebind. The
    #    intact runner refuses; the mutant admits.
    launched = _Cells(tmp_path / "launched", actor=BLD, ledger_rows=[])
    launched_argv = _verification_argv(launched.scenario)
    launched_identity = "verify-synthetic-production-build-0070"
    assert (
        launched.main(
            *launched.base(),
            "--prepare-cell",
            "R1-BLD-BOOTSTRAP",
            "--identity",
            launched_identity,
            *launched_argv,
        )
        == runner.EXIT_PREPARED
    )
    launched_digest = capsys.readouterr().out.split("specification_digest=")[1].split()[0]
    launched.scenario.authorize(identity=launched_identity, specification_digest=launched_digest)
    launched.scenario.ecs.descriptions[-1]["containers"][0]["exitCode"] = 18
    assert (
        launched.main(
            *launched.base(),
            "--execute-cell",
            "R1-BLD-BOOTSTRAP",
            *launched_argv,
            "--authorization",
            str(launched.scenario.authorization),
            runner.AUTHORIZATION_FLAG,
        )
        == launch.EXIT_LAUNCH_TERMINAL
    )
    capsys.readouterr()
    _change_registration(launched, BLD)
    launched_fields = launched.scenario.fields()
    launched_fields["r3_binding_source"] = lambda: BINDING
    assert runner.main(launched.base(), **launched_fields) == runner.EXIT_MATRIX
    assert (
        "cell=R1-BLD-BOOTSTRAP ref=R-1 kind=RUNTIME_LAUNCH status=LAUNCHED"
        in capsys.readouterr().out
    )
    launched_cells_path = launched.scenario.ledger.with_name("ledger.json" + runner.CELLS_SUFFIX)
    launched_cells_before = launched_cells_path.read_bytes()
    assert (
        runner.main(
            _rebind_argv(launched, launched_argv, "verify-synthetic-production-build-0071"),
            **launched_fields,
        )
        == runner.EXIT_REFUSED_CELL_STATE
    )
    capsys.readouterr()
    assert launched_cells_path.read_bytes() == launched_cells_before
    guard = _mutant(
        tmp_path,
        "mutant_guard",
        "    if state is None or state.status is not vc.CellStatus.HISTORICAL:\n",
        "    if False:\n",
    )
    assert (
        guard.main(
            _rebind_argv(launched, launched_argv, "verify-synthetic-production-build-0072"),
            **launched_fields,
        )
        == guard.EXIT_PREPARED
    )
    capsys.readouterr()
    assert launched_cells_path.read_bytes() != launched_cells_before  # the mutant rebound it

    # 2. The registration-inequality rule removed in the derivation (a changed registration
    #    no longer makes the evidence historical): the cell reads PASSED and the rebind
    #    that the intact code admits is refused -- the property the regression names.
    _change_registration(cells, BLD)
    monkeypatch.setattr(vc, "_historical", lambda cell, evidence, reservation, prepared: None)
    assert runner.main(cells.base(), **fields) == runner.EXIT_MATRIX
    assert (
        "cell=R1-BLD-BOOTSTRAP ref=R-1 kind=RUNTIME_LAUNCH status=PASSED" in capsys.readouterr().out
    )
    assert (
        runner.main(_rebind_argv(cells, argv, "verify-synthetic-production-build-0062"), **fields)
        == runner.EXIT_REFUSED_CELL_STATE
    )
    capsys.readouterr()
    monkeypatch.undo()
    assert runner.main(cells.base(), **fields) == runner.EXIT_MATRIX
    assert (
        "cell=R1-BLD-BOOTSTRAP ref=R-1 kind=RUNTIME_LAUNCH status=HISTORICAL"
        in capsys.readouterr().out
    )

    # 3. The preservation link dropped: the rebound binding no longer names what it superseded.
    link = _mutant(
        tmp_path,
        "mutant_link",
        "                    supersedes=vc.SupersededBinding(\n",
        "                    supersedes=None and vc.SupersededBinding(\n",
    )
    snapshot = {p: p.read_bytes() for p in scenario.ledger.parent.rglob("*") if p.is_file()}
    assert (
        link.main(_rebind_argv(cells, argv, "verify-synthetic-production-build-0063"), **fields)
        == link.EXIT_PREPARED
    )
    capsys.readouterr()
    assert "supersedes" not in json.loads(cells_path.read_bytes())["cells"]["R1-BLD-BOOTSTRAP"]
    for path, raw in snapshot.items():
        path.write_bytes(raw)
    for path in scenario.ledger.parent.rglob("*"):
        if path.is_file() and path not in snapshot:
            path.unlink()
    assert (
        runner.main(_rebind_argv(cells, argv, "verify-synthetic-production-build-0064"), **fields)
        == runner.EXIT_PREPARED
    )
    capsys.readouterr()
    assert (
        json.loads(cells_path.read_bytes())["cells"]["R1-BLD-BOOTSTRAP"]["supersedes"]["identity"]
        == bootstrap
    )
    for path, raw in snapshot.items():
        path.write_bytes(raw)
    for path in scenario.ledger.parent.rglob("*"):
        if path.is_file() and path not in snapshot:
            path.unlink()

    # 4. The write ordering inverted: the specification written before the checks leaves a
    #    stray record on a refusal. The intact runner leaves none.
    ordering = _mutant(
        tmp_path,
        "mutant_order",
        "    try:\n        with store.locked(now=lambda: now):\n",
        "    launch.write_specification(launch_arguments, prepared, now=now)\n"
        "    try:\n        with store.locked(now=lambda: now):\n",
    )
    # The refusal case: the ``launched`` scenario's cell is now PREPARED under the mutant
    # guard's rebind, so a further fresh identity is refused before any write.
    stray_argv = _rebind_argv(launched, launched_argv, "verify-synthetic-production-build-0073")
    specifications = len(launched.scenario.files("launch-specification"))
    assert ordering.main(stray_argv, **launched_fields) == ordering.EXIT_REFUSED_CELL_STATE
    capsys.readouterr()
    assert len(launched.scenario.files("launch-specification")) == specifications + 1  # the stray
    launched.scenario.files("launch-specification")[-1].unlink()
    assert runner.main(stray_argv, **launched_fields) == runner.EXIT_REFUSED_CELL_STATE
    capsys.readouterr()
    assert len(launched.scenario.files("launch-specification")) == specifications


# ---------------------------------------------------------------------------
# E. Deployment impact: the task path never touches these workstation modules
# ---------------------------------------------------------------------------


def test_no_task_entry_imports_the_changed_workstation_paths() -> None:
    from kalpamani.data.production.sharadar import entry

    closure: set[str] = set()
    pending = [entry.__name__]
    import importlib

    while pending:
        name = pending.pop()
        if name in closure:
            continue
        closure.add(name)
        module = importlib.import_module(name)
        for value in vars(module).values():
            candidate = (
                getattr(value, "__module__", None)
                if not hasattr(value, "__file__")
                else getattr(value, "__name__", None)
            )
            if (
                isinstance(candidate, str)
                and candidate.startswith("kalpamani.")
                and candidate not in closure
            ):
                pending.append(candidate)
    assert "kalpamani.data.production.sharadar.launch_store" not in closure
    assert "kalpamani.data.production.sharadar.verification_cells" not in closure
    assert "kalpamani.data.production.sharadar.launch_records" not in closure
