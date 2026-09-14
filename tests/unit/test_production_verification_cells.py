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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from test_production_launch_script import (
    TestIsolationVerdict,
    _launch_record,
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
    specification_for,
)
from fixtures.production_runtime import CANARIES, RUN_ID, encode
from kalpamani.data.contracts.canonical import canonical_bytes
from kalpamani.data.production.sharadar import launch_records as lr
from kalpamani.data.production.sharadar import launch_store as ls
from kalpamani.data.production.sharadar import probe as pp
from kalpamani.data.production.sharadar import r3_verification as r3
from kalpamani.data.production.sharadar import verification_cells as vc
from kalpamani.data.production.sharadar.entry import TaskEntry
from kalpamani.data.production.sharadar.probe import IsolationVerdict, VerdictReason

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
    verdicts: dict[str, tuple[pp.IsolationVerdictDocument, ...]] | None = None,
    malformed_verdicts: set[str] | None = None,
    unreadable_verdicts: int = 0,
    reservations: dict[str, ls.Reservation] | None = None,
    launch_records: dict[str, lr.LaunchRecord] | None = None,
    r3_record: r3.R3Record | None = None,
    r3_binding: r3.R3Binding | None = BINDING,
    inputs_digest: str | None = None,
    inputs: lr.LaunchInputs | None = None,
) -> vc.RecordedEvidence:
    return vc.RecordedEvidence(
        ledger=lr.parse_owner_ledger(encode(ledger_document(rows or []))),
        unreconciled=frozenset(unreconciled or set()),
        verdicts=verdicts or {},
        malformed_verdicts=frozenset(malformed_verdicts or set()),
        unreadable_verdicts=unreadable_verdicts,
        reservations=reservations or {},
        launch_records=launch_records or {},
        unreadable_launch_records=0,
        inputs=_inputs(inputs_digest) if inputs is None else inputs,
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


class _Chain:
    """A complete, bound evidence chain for one runtime cell on the fixtures' records."""

    def __init__(self, actor: Any = BLD, *, inputs: dict[str, Any] | None = None) -> None:
        self.actor = actor
        self.identity = "verify-" + RUN_ID
        self.cell_id = "R1-BLD-BOOTSTRAP" if actor is BLD else "R1-ACQ-BOOTSTRAP"
        self.entry = TaskEntry.BUILD_VERIFY if actor is BLD else TaskEntry.ACQUISITION_VERIFY
        self.inputs_document = launch_inputs_document() if inputs is None else inputs
        self.specification = specification_for(
            actor=actor,
            kind="verification",
            identity=self.identity,
            inputs=self.inputs_document,
            ledger=ledger_document([ledger_row(RUN_ID)]),
        )
        self.reservation = ls.Reservation(
            identity=self.identity,
            actor=actor,
            kind=lr.LaunchKind.VERIFICATION,
            specification=self.specification,
            reserved_at=NOW,
        )
        self.record = _launch_record(
            entry=self.entry,
            identity=self.identity,
            harness=None,
            kind=lr.LaunchKind.VERIFICATION,
            specification=self.specification,
        )
        self.row = ledger_row(self.identity, actor=actor, kind="verification", outcome="VERIFIED")

    def prepared(self, digest: str | None = None) -> dict[str, vc.PreparedCell]:
        return {
            self.cell_id: vc.PreparedCell(
                cell_id=self.cell_id,
                identity=self.identity,
                specification_digest=self.specification.digest if digest is None else digest,
                prepared_at=NOW,
            )
        }

    def evidence(self, **overrides: Any) -> vc.RecordedEvidence:
        record = _r3_record()
        fields: dict[str, Any] = {
            "rows": [ledger_row(RUN_ID), self.row],
            "reservations": {self.identity: self.reservation},
            "launch_records": {self.identity: self.record},
            "r3_record": record,
            "inputs": lr.parse_launch_inputs(
                encode({**self.inputs_document, "r3_verification_digest": record.digest})
            ),
        }
        fields.update(overrides)
        return _evidence(**fields)


def _verdict_document(
    chain: _Chain,
    reason: VerdictReason,
    *,
    result: pp.ProbeResult = pp.ProbeResult.TIMED_OUT,
    supplied: bool | None = None,
    components: tuple[pp.BlockingComponent, ...] = (),
    recorded_at: datetime = NOW,
) -> dict[str, Any]:
    """A verdict document as the launch tool writes it, consistent by construction."""
    verdict, bound = pp.REASON_VERDICT[reason]
    attempted = reason is not VerdictReason.NO_ATTEMPT
    probe = pp.ProbeObservation(
        resolution=pp.ProbeResolution.RESOLVED_IN_SET
        if attempted
        else pp.ProbeResolution.RESOLVED_OUTSIDE_SET,
        result=result if attempted else pp.ProbeResult.NOT_ATTEMPTED,
        attempts=1 if attempted else 0,
        destination_digest="ab" * 32 if attempted else None,
    )
    if supplied is None:
        supplied = reason not in {
            VerdictReason.NO_CORROBORATION,
            VerdictReason.NO_ATTEMPT,
            VerdictReason.DESTINATION_UNBOUND,
            VerdictReason.OBSERVED_CONNECTION,
        }
    if reason is VerdictReason.CORROBORATED and not components:
        components = (pp.BlockingComponent.ROUTE_TABLE,)
    return {
        "schema_version": 1,
        "contract_id": pp.ISOLATION_VERDICT_CONTRACT_ID,
        "actor": chain.actor.value,
        "kind": "verification",
        "specification_digest": chain.specification.digest,
        "probe": probe.document(),
        "verdict": pp.IsolationVerdictRecord(
            verdict=verdict,
            reason=reason,
            blocking_components=frozenset(components),
            analysis_bound=bound,
        ).document(),
        "evidence_supplied": supplied,
        "recorded_at": recorded_at.isoformat(),
    }


def _parsed(*documents: dict[str, Any]) -> tuple[pp.IsolationVerdictDocument, ...]:
    return tuple(pp.parse_isolation_verdict_document(canonical_bytes(d)) for d in documents)


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
    # Receipt-verified but unbound (no reservation, no launch record): never passed.
    row = ledger_row(
        "verify-" + RUN_ID, kind="verification", outcome="VERIFIED", evidence="RECEIPT_VERIFIED"
    )
    states = vc.derive_states(_evidence(**base, rows=[row]), prepared)
    assert states["R1-ACQ-BOOTSTRAP"].status is vc.CellStatus.UNBOUND
    assert vc.aggregate(states) is vc.AggregateStatus.INCOMPLETE
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
    chain = _Chain(ACQ)
    states = vc.derive_states(
        chain.evidence(
            r3_record=None, inputs=lr.parse_launch_inputs(encode(chain.inputs_document))
        ),
        chain.prepared(),
    )
    assert states["R1-ACQ-BOOTSTRAP"].status is vc.CellStatus.PASSED
    assert states["R3"].status is vc.CellStatus.BLOCKED


class TestEvidenceChain:
    """PR #105 review finding 2: a receipt-verified row passes only through its bound chain."""

    def test_a_correctly_bound_current_chain_passes(self) -> None:
        for actor in (BLD, ACQ):
            chain = _Chain(actor)
            states = vc.derive_states(chain.evidence(), chain.prepared())
            assert states[chain.cell_id].status is vc.CellStatus.PASSED, actor
            assert "bound to its reservation" in states[chain.cell_id].reason

    def test_a_reservation_for_another_specification_does_not_bind(self) -> None:
        chain = _Chain()
        states = vc.derive_states(chain.evidence(), chain.prepared(digest="ef" * 32))
        assert states[chain.cell_id].status is vc.CellStatus.UNBOUND
        assert "reservation" in states[chain.cell_id].reason
        other = ls.Reservation(
            identity=chain.identity,
            actor=BLD,
            kind=lr.LaunchKind.VERIFICATION,
            specification=specification_for(
                actor=BLD,
                kind="verification",
                identity=chain.identity,
                inputs=launch_inputs_document(platform_version="1.3.0"),
            ),
            reserved_at=NOW,
        )
        states = vc.derive_states(
            chain.evidence(reservations={chain.identity: other}), chain.prepared()
        )
        assert states[chain.cell_id].status is vc.CellStatus.UNBOUND

    def test_a_missing_reservation_or_launch_record_does_not_bind(self) -> None:
        chain = _Chain()
        states = vc.derive_states(chain.evidence(reservations={}), chain.prepared())
        assert states[chain.cell_id].status is vc.CellStatus.UNBOUND
        states = vc.derive_states(chain.evidence(launch_records={}), chain.prepared())
        assert states[chain.cell_id].status is vc.CellStatus.UNBOUND
        assert "launch record" in states[chain.cell_id].reason

    def test_a_substituted_launch_record_does_not_bind(self) -> None:
        chain = _Chain()
        for field, value in (
            ("specification_digest", "cd" * 32),
            ("image_digest", "sha256:" + "00" * 32),
            ("code_commit", "f" * 40),
            ("network_interface_id", None),
        ):
            document = chain.record.document()
            document[field] = value
            if field == "network_interface_id":
                document["subnet_id"] = None
                document["security_group_ids"] = None
            substituted = lr.parse_launch_record(encode(document))
            states = vc.derive_states(
                chain.evidence(launch_records={chain.identity: substituted}), chain.prepared()
            )
            assert states[chain.cell_id].status is vc.CellStatus.UNBOUND, field

    def test_a_changed_registered_target_or_placement_makes_the_success_historical(
        self,
    ) -> None:
        chain = _Chain()

        def new_image(d: dict[str, Any]) -> None:
            target = d["actors"]["build"]["verification"]
            target["image_digest"] = "sha256:" + "00" * 32
            target["task_definition"]["image_digest"] = "sha256:" + "00" * 32

        for change in (
            new_image,
            lambda d: d["actors"]["build"]["verification"].__setitem__("code_commit", "f" * 40),
            lambda d: d["actors"]["build"].__setitem__("subnet_id", "subnet-0fedcba9876543210"),
            lambda d: d.__setitem__("platform_version", "1.3.0"),
        ):
            inputs = launch_inputs_document()
            change(inputs)
            r3_record = _r3_record()
            inputs["r3_verification_digest"] = r3_record.digest
            states = vc.derive_states(
                chain.evidence(inputs=lr.parse_launch_inputs(encode(inputs))), chain.prepared()
            )
            assert states[chain.cell_id].status is vc.CellStatus.HISTORICAL
            assert "re-verification" in states[chain.cell_id].reason
            assert vc.aggregate(states) is vc.AggregateStatus.INCOMPLETE
            # The isolation cell is blocked behind a historical bootstrap.
            assert states["R2-BLD-ISOLATION"].status is vc.CellStatus.BLOCKED

    def test_the_verdict_cell_accepts_only_closed_consistent_documents(self) -> None:
        chain = _Chain()
        digest = chain.specification.digest
        # The minimal forged shape the runner once accepted does not parse.
        with pytest.raises(ValueError):
            pp.parse_isolation_verdict_document(
                canonical_bytes(
                    {
                        "contract_id": pp.ISOLATION_VERDICT_CONTRACT_ID,
                        "specification_digest": digest,
                        "verdict": {"verdict": "VERIFIED"},
                    }
                )
            )
        # Malformed evidence for this launch is reported, never ignored.
        states = vc.derive_states(chain.evidence(malformed_verdicts={digest}), chain.prepared())
        assert states["R2-BLD-ISOLATION"].status is vc.CellStatus.UNBOUND
        states = vc.derive_states(chain.evidence(unreadable_verdicts=1), chain.prepared())
        assert states["R2-BLD-ISOLATION"].status is vc.CellStatus.UNBOUND
        # A document for another actor or kind does not bind.
        foreign = _verdict_document(chain, VerdictReason.CORROBORATED)
        foreign["actor"] = "acquisition"
        states = vc.derive_states(
            chain.evidence(verdicts={digest: _parsed(foreign)}), chain.prepared()
        )
        assert states["R2-BLD-ISOLATION"].status is vc.CellStatus.UNBOUND

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d["verdict"].__setitem__("verdict", "VERIFIED"),  # over NO_CORROBORATION
            lambda d: d["verdict"].__setitem__("analysis_bound", True),
            lambda d: d["verdict"].__setitem__("blocking_components", ["ROUTE_TABLE"]),
            lambda d: d.__setitem__("evidence_supplied", True),  # NO_CORROBORATION + evidence
            lambda d: d["probe"].__setitem__("result", "CONNECTED"),  # CONNECTED not FAILED
            lambda d: d["probe"].__setitem__("attempts", 0),
            lambda d: d.pop("probe"),
            lambda d: d.pop("recorded_at"),
            lambda d: d.__setitem__("extra", 1),
            lambda d: d.__setitem__("contract_id", "kalpamani-isolation-verdict/v2"),
        ],
    )
    def test_a_contradictory_or_incomplete_verdict_document_is_refused(self, mutate: Any) -> None:
        document = _verdict_document(_Chain(), VerdictReason.NO_CORROBORATION)
        assert pp.parse_isolation_verdict_document(canonical_bytes(document))
        mutate(document)
        with pytest.raises(ValueError):
            pp.parse_isolation_verdict_document(canonical_bytes(document))

    def test_a_corroborated_verdict_over_an_observed_connection_is_refused(self) -> None:
        document = _verdict_document(
            _Chain(), VerdictReason.CORROBORATED, result=pp.ProbeResult.CONNECTED
        )
        with pytest.raises(ValueError):
            pp.parse_isolation_verdict_document(canonical_bytes(document))
        failed = _verdict_document(
            _Chain(), VerdictReason.OBSERVED_CONNECTION, result=pp.ProbeResult.CONNECTED
        )
        assert pp.parse_isolation_verdict_document(canonical_bytes(failed)).verdict.verdict is (
            IsolationVerdict.FAILED
        )

    def test_verdict_records_resolve_deterministically(self) -> None:
        chain = _Chain()
        digest = chain.specification.digest
        no_corroboration = _verdict_document(chain, VerdictReason.NO_CORROBORATION)
        corroborated = _verdict_document(
            chain, VerdictReason.CORROBORATED, recorded_at=NOW + timedelta(hours=1)
        )
        failed = _verdict_document(
            chain, VerdictReason.OBSERVED_CONNECTION, result=pp.ProbeResult.CONNECTED
        )
        stale = _verdict_document(chain, VerdictReason.ANALYSIS_OUTSIDE_TASK_WINDOW)
        path_found = _verdict_document(chain, VerdictReason.PATH_FOUND_CONTRADICTS_OBSERVATION)

        def status(*documents: dict[str, Any]) -> vc.CellStatus:
            states = vc.derive_states(
                chain.evidence(verdicts={digest: _parsed(*documents)}), chain.prepared()
            )
            return states["R2-BLD-ISOLATION"].status

        assert status() is vc.CellStatus.UNEXECUTED
        assert status(no_corroboration) is vc.CellStatus.INCONCLUSIVE
        # A later corroboration for the same launch resolves the insufficiency.
        assert status(no_corroboration, corroborated) is vc.CellStatus.PASSED
        assert status(no_corroboration, stale, corroborated) is vc.CellStatus.PASSED
        # Wrong-source, wrong-destination or stale evidence alone never promotes.
        assert status(no_corroboration, stale) is vc.CellStatus.INCONCLUSIVE
        # An observed connection is never erased by a later success label, in any order.
        assert status(failed, corroborated) is vc.CellStatus.FAILED
        assert status(corroborated, failed) is vc.CellStatus.FAILED
        # A modelled path against the observation is a contradiction a corroboration
        # cannot resolve.
        assert status(path_found, corroborated) is vc.CellStatus.UNBOUND
        # Records carrying different probe blocks are not one launch's.
        other_probe = _verdict_document(
            chain, VerdictReason.CORROBORATED, result=pp.ProbeResult.CONNECTION_REFUSED
        )
        assert status(no_corroboration, other_probe) is vc.CellStatus.UNBOUND


def test_the_isolation_cell_is_separate_from_bootstrap_and_stays_inconclusive_uncorroborated() -> (
    None
):
    record = _r3_record()
    identity = "verify-" + RUN_ID
    prepared = _prepared(**{"R1-BLD-BOOTSTRAP": identity})
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
    # A receipt-verified row with no chain behind it is unbound; the verdict stays blocked.
    states = vc.derive_states(_evidence(**base, rows=[passed]), prepared)
    assert states["R1-BLD-BOOTSTRAP"].status is vc.CellStatus.UNBOUND
    assert states["R2-BLD-ISOLATION"].status is vc.CellStatus.BLOCKED
    chain = _Chain()
    states = vc.derive_states(chain.evidence(), chain.prepared())
    assert states["R1-BLD-BOOTSTRAP"].status is vc.CellStatus.PASSED
    assert states["R2-BLD-ISOLATION"].status is vc.CellStatus.UNEXECUTED
    # Bootstrap passed through its chain: the verdict cell follows the documents.
    chain = _Chain()
    for reason, result, status in (
        (VerdictReason.NO_CORROBORATION, pp.ProbeResult.TIMED_OUT, vc.CellStatus.INCONCLUSIVE),
        (VerdictReason.OBSERVED_CONNECTION, pp.ProbeResult.CONNECTED, vc.CellStatus.FAILED),
        (VerdictReason.CORROBORATED, pp.ProbeResult.TIMED_OUT, vc.CellStatus.PASSED),
    ):
        document = _verdict_document(chain, reason, result=result)
        states = vc.derive_states(
            chain.evidence(verdicts={chain.specification.digest: _parsed(document)}),
            chain.prepared(),
        )
        assert states["R2-BLD-ISOLATION"].status is status, reason
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
        vc.CellStatus.HISTORICAL,
        vc.CellStatus.UNBOUND,
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
    # The launch record the launch tool would have written into the records directory.
    scenario.records.mkdir(parents=True, exist_ok=True)
    (scenario.records / "launch-record-20260905T020500Z-0001.json").write_bytes(
        record_path.read_bytes()
    )
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
    run_tasks = len(scenario.ecs.names("run_task"))
    # Wrong-source, stale or contradictory evidence for the same launch does not promote.
    evidence = scenario.root / "reachability.json"
    for label, override in (
        ("other interface", {"source_interface_id": "eni-0fedcba9876543210"}),
        ("stale", {"start_date": (NOW + timedelta(days=30)).isoformat()}),
    ):
        evidence.write_bytes(encode(_reachability_evidence(**override)))
        assert (
            cells.main(*verdict, "--reachability-evidence", str(evidence))
            == launch.EXIT_VERDICT_RECORDED
        ), label
        out = capsys.readouterr().out
        assert "cell=R2-BLD-ISOLATION ref=R-2 kind=ISOLATION_VERDICT status=INCONCLUSIVE" in out
    # Then qualifying, bound corroboration for the SAME launch resolves the insufficiency:
    # no relaunch, no new probe, every earlier record kept.
    evidence.write_bytes(encode(_reachability_evidence()))
    assert (
        cells.main(*verdict, "--reachability-evidence", str(evidence))
        == launch.EXIT_VERDICT_RECORDED
    )
    out = capsys.readouterr().out
    assert "cell=R2-BLD-ISOLATION ref=R-2 kind=ISOLATION_VERDICT status=PASSED" in out
    assert len(scenario.files("isolation-verdict")) == 4
    assert len(scenario.ecs.names("run_task")) == run_tasks
    assert scenario.clients.constructions == []
    # A passed verdict cell is not re-evaluated again.
    assert (
        cells.main(*verdict, "--reachability-evidence", str(evidence))
        == runner.EXIT_REFUSED_CELL_STATE
    )


def test_the_runner_parses_every_verdict_record_and_reports_malformed_ones(
    tmp_path: Path,
) -> None:
    """Records are parsed closed; a forged shape is malformed evidence, never a verdict."""
    cells = _Cells(tmp_path)
    store = cells.scenario.store()
    chain = _Chain()
    digest = chain.specification.digest
    store.write_record(
        "isolation-verdict", _verdict_document(chain, VerdictReason.NO_CORROBORATION), at=NOW
    )
    store.write_record(
        "isolation-verdict",
        _verdict_document(chain, VerdictReason.CORROBORATED, recorded_at=NOW + timedelta(hours=1)),
        at=NOW + timedelta(hours=1),
    )
    verdicts, malformed, unreadable = runner._verdicts(store)
    assert [d.verdict.reason for d in verdicts[digest]] == [
        VerdictReason.NO_CORROBORATION,
        VerdictReason.CORROBORATED,
    ]
    assert malformed == frozenset() and unreadable == 0
    # The minimal shape once accepted: reported against its digest, not ignored.
    store.write_record(
        "isolation-verdict",
        {
            "contract_id": pp.ISOLATION_VERDICT_CONTRACT_ID,
            "specification_digest": "ef" * 32,
            "verdict": {"verdict": "VERIFIED"},
        },
        at=NOW + timedelta(hours=2),
    )
    (store._records_dir / "isolation-verdict-20260914T200000Z-deadbeef.json").write_bytes(b"{")
    verdicts, malformed, unreadable = runner._verdicts(store)
    assert malformed == frozenset({"ef" * 32}) and unreadable == 1
    assert set(verdicts) == {digest}
