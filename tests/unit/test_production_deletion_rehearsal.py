"""The deletion rehearsal path (ADR-0048 s.4; ADR-0049 s.3): implemented offline over
the real evidence, store and engine with a fake acting as the deletion role, and CLOSED -- the
catalogue keeps the two R-8 subcells BLOCKED, the tool refuses the rehearsal, and only these
tests drive the engine. Every answer here is a fake's; nothing reaches AWS."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import pytest
from test_production_permission_cells import (
    DENIED,
    NO_CONTENT,
    NOT_FOUND,
    OK,
    FakePermissionClient,
    _Tool,
    tool,
)

from kalpamani.data.production.sharadar import deletion_rehearsal as dr
from kalpamani.data.production.sharadar import permission_cells as pc
from kalpamani.data.production.sharadar import r3_verification as r3
from kalpamani.data.production.sharadar.launch_store import StoreDefect, StoreError

TIMEOUT: Final = r3.Observation(status=None, transport_failure="timeout")


def _with_prerequisite(tmp_path: Path) -> _Tool:
    """A tool whose R-4 human PutObject subcell is executed, MATCHED and bound -- the one
    record a rehearsal may derive its target from."""
    t = _Tool(tmp_path)
    assert t.execute("R4-PUT-PAYLOAD-HUMAN", [OK]) == tool.EXIT_EXECUTED
    return t


_stamps = iter(f"20260912T14{n:02d}00Z-abcd" for n in range(60))


def _prepared(t: _Tool, subcell: str, *, earlier: tuple[str, ...] = ()) -> dr.RehearsalStatement:
    """A statement under a fresh session stamp (so each rehearsal has its own authorization)."""
    return dr.prepare_rehearsal(subcell, t.evidence(), stamp=next(_stamps), earlier=earlier)


def _authorize_and_consume(t: _Tool, statement: dr.RehearsalStatement) -> str:
    """The owner's authorization for the statement, consumed durably before any operation."""
    authorization = t.authorize(
        statement.subcell_id, statement.digest, name=f"{statement.digest[:16]}.json"
    )
    parsed = pc.parse_permission_authorization(
        authorization.read_bytes(),
        subcell_id=statement.subcell_id,
        statement_sha256=statement.digest,
        now=t.clock.now(),
    )
    t.scenario.store().consume(
        dr.REHEARSAL_CONSUMPTION_KIND,
        parsed.digest,
        {"subcell_id": statement.subcell_id, "statement_sha256": statement.digest},
    )
    return parsed.digest


def _rehearse(
    t: _Tool,
    statement: dr.RehearsalStatement,
    client: FakePermissionClient,
    *,
    verified: bool = True,
) -> dr.RehearsalRecord:
    digest = _authorize_and_consume(t, statement)
    return dr.rehearse_subcell(
        statement,
        authorization_sha256=digest,
        client=client,
        identity_verified=verified,
        now=t.clock.now(),
        finished=t.clock.now(),
    )


def _prerequisite_attempt(t: _Tool) -> str:
    record = pc.parse_permission_record(t.files("permission-record")[0].read_bytes())
    return record.attempt_sha256


class TestClosed:
    def test_the_path_is_implemented_and_closed(self, tmp_path: Path, capsys: Any) -> None:
        assert dr.REHEARSAL_PATH_OPEN is False and dr.rehearsal_blocked()
        for subcell in dr.REHEARSAL_SEQUENCE:
            cell = pc.subcell(subcell)
            assert cell.layer is pc.Layer.BLOCKED and cell.principal is pc.Principal.DELETION_ROLE
            assert cell.requires == (dr.REHEARSAL_PREREQUISITE,)
            assert cell.blocked_on == pc.DELETION_DEPENDENCY
        assert "ADR-0049 s.3" in pc.DELETION_DEPENDENCY and "D-1" in pc.DELETION_DEPENDENCY
        # The tool refuses the rehearsal before any path or flag is read.
        t = _Tool(tmp_path)
        assert t.main("--rehearse-deletion", "R8-GET") == tool.EXIT_REFUSED_REHEARSAL_CLOSED
        assert tool.SENTENCES["refused_rehearsal_closed"] in capsys.readouterr().out
        assert t.main("--rehearse-deletion", "R8-GET", *t.base(), tool.AUTHORIZATION_FLAG) == (
            tool.EXIT_REFUSED_REHEARSAL_CLOSED
        )
        # The two subcells stay BLOCKED in the derived matrix whatever the records say.
        state = pc.derive_subcell(pc.subcell("R8-GET"), t.evidence(), r1_passed={})
        assert state.status is pc.SubcellStatus.BLOCKED
        # The resources the decision would declare are named exactly; they are DECLARED
        # inert (proposed ADR-0050) in exactly one file, behind a variable whose default
        # is false, and none exists.
        assert dr.REHEARSAL_FAMILY == "kalpamani-deletion-rehearsal"
        assert dr.REHEARSAL_LAUNCHER_PERMISSION_SET == "KalpaManiDeletionRehearse"
        assert dr.REHEARSAL_STREAM_PREFIX == "production-" + dr.REHEARSAL_CONTAINER
        assert all(
            p.startswith(dr.REHEARSAL_PARAMETER_PREFIX)
            for p in (
                dr.REHEARSAL_BINDING_PARAMETER,
                dr.REHEARSAL_INPUT_PARAMETER,
                dr.REHEARSAL_RELEASE_PARAMETER,
            )
        )
        from kalpamani.data.production.sharadar.entry import TaskEntry

        assert dr.REHEARSAL_ENTRY not in {e.value for e in TaskEntry}
        infra = Path(__file__).resolve().parents[2] / "infra/aws/research-data-plane"
        naming = sorted(
            p.name
            for p in infra.glob("*.tf")
            if dr.REHEARSAL_FAMILY in p.read_text(encoding="utf-8")
        )
        assert naming == ["production_deletion_rehearsal.tf"]
        variables = (infra / "production_variables.tf").read_text(encoding="utf-8")
        assert 'variable "deletion_rehearsal_open"' in variables
        assert "default     = false" in variables.split('variable "deletion_rehearsal_open"')[1]


class TestTarget:
    def test_the_target_is_the_bound_r4_record_s_synthetic_object_and_nothing_else(
        self, tmp_path: Path
    ) -> None:
        t = _with_prerequisite(tmp_path)
        target = dr.rehearsal_target(t.evidence())
        record = pc.parse_permission_record(t.files("permission-record")[0].read_bytes())
        assert target.key == record.created_key and target.bucket == record.created_bucket
        assert target.prerequisite_sha256 == record.digest
        assert "objects/sha256" not in repr(target)
        # No record: no target. A record that does not bind (its attempt gone): no target.
        with pytest.raises(dr.RehearsalError) as none:
            dr.rehearsal_target(_Tool(tmp_path / "empty").evidence())
        assert none.value.defect is dr.RehearsalDefect.PREREQUISITE_UNBOUND
        attempt = t.files("permission-attempt")[0]
        kept = attempt.read_bytes()
        attempt.unlink()
        with pytest.raises(dr.RehearsalError) as unbound:
            dr.rehearsal_target(t.evidence())
        assert unbound.value.defect is dr.RehearsalDefect.PREREQUISITE_UNBOUND
        attempt.write_bytes(kept)
        # A key that is not the synthetic marker's content address is never a target.
        path = t.files("permission-record")[0]
        document = json.loads(path.read_bytes())
        document["created_key"] = "bronze/sharadar/tickers/production/objects/sha256/" + "ab" * 32
        path.write_bytes(json.dumps(document).encode())
        with pytest.raises(dr.RehearsalError):
            dr.rehearsal_target(t.evidence())
        # A record whose object a verified cleanup already settled: no target.
        t2 = _with_prerequisite(tmp_path / "settled")
        control = t2.control(tmp_path / "settled")
        assert t2.cleanup(control, [NO_CONTENT, NOT_FOUND]) == tool.EXIT_EXECUTED
        with pytest.raises(dr.RehearsalError) as settled:
            dr.rehearsal_target(t2.evidence())
        assert settled.value.defect is dr.RehearsalDefect.PREREQUISITE_SETTLED


class TestSequenceAndAuthorization:
    def test_the_read_refusal_precedes_the_deletion_and_each_needs_its_own_consumed_authorization(
        self, tmp_path: Path
    ) -> None:
        t = _with_prerequisite(tmp_path)
        with pytest.raises(dr.RehearsalError) as early:
            _prepared(t, "R8-LIST-AND-DELETE")
        assert early.value.defect is dr.RehearsalDefect.SEQUENCE_VIOLATED
        with pytest.raises(dr.RehearsalError):
            _prepared(t, "R4-SECRET-GET-HUMAN")
        first = _prepared(t, "R8-GET")
        assert first.document()["principal"] == "DELETION_ROLE"
        assert first.document()["sequence_position"] == 0
        assert first.document()["target_sha256"] == first.target.digest
        second = _prepared(t, "R8-LIST-AND-DELETE", earlier=("R8-GET",))
        assert second.document()["sequence_position"] == 1 and second.digest != first.digest
        # The authorization binds the statement digest; a second consumption refuses.
        digest = _authorize_and_consume(t, first)
        with pytest.raises(StoreError) as consumed:
            t.scenario.store().consume(dr.REHEARSAL_CONSUMPTION_KIND, digest, {})
        assert consumed.value.defect is StoreDefect.AUTHORIZATION_CONSUMED
        assert t.scenario.store().is_consumed(dr.REHEARSAL_CONSUMPTION_KIND, digest)
        # An authorization for another statement is not this one's.
        with pytest.raises(ValueError):
            pc.parse_permission_authorization(
                t.authorize("R8-GET", "77" * 32, name="other.json").read_bytes(),
                subcell_id="R8-GET",
                statement_sha256=first.digest,
                now=t.clock.now(),
            )


class TestEngine:
    def test_the_read_refusal_passes_on_a_denial_and_fails_on_a_body(self, tmp_path: Path) -> None:
        t = _with_prerequisite(tmp_path)
        statement = _prepared(t, "R8-GET")
        client = FakePermissionClient(DENIED)
        record = _rehearse(t, statement, client)
        assert record.outcome is dr.RehearsalOutcome.PASS and record.operations == 1
        assert [c[0] for c in client.calls] == ["get_object"]
        assert client.calls[0][1] == {
            "bucket": statement.target.bucket,
            "key": statement.target.key,
        }
        assert not record.deleted and not record.object_open
        status, _ = dr.derive_rehearsal(record, (), prerequisite_attempt=_prerequisite_attempt(t))
        assert status is dr.RehearsalStatus.PASSED
        # A body: the role could read -- FAIL. A timeout decides nothing.
        record = _rehearse(t, _prepared(t, "R8-GET"), FakePermissionClient(OK))
        assert record.outcome is dr.RehearsalOutcome.FAIL
        assert (
            dr.derive_rehearsal(record, (), prerequisite_attempt="x")[0]
            is dr.RehearsalStatus.FAILED
        )
        record = _rehearse(t, _prepared(t, "R8-GET"), FakePermissionClient(TIMEOUT))
        assert record.outcome is dr.RehearsalOutcome.INCONCLUSIVE
        assert (
            dr.derive_rehearsal(record, (), prerequisite_attempt="x")[0]
            is dr.RehearsalStatus.INCONCLUSIVE
        )
        # An unverified identity never passes.
        record = _rehearse(t, _prepared(t, "R8-GET"), FakePermissionClient(DENIED), verified=False)
        assert (
            dr.derive_rehearsal(record, (), prerequisite_attempt="x")[0]
            is dr.RehearsalStatus.INCONCLUSIVE
        )
        # The record round-trips closed.
        parsed = dr.parse_rehearsal_record(json.dumps(record.document()).encode())
        assert parsed == record
        broken = record.document()
        broken["operations"] = 2
        with pytest.raises(ValueError):
            dr.parse_rehearsal_record(broken)

    def test_list_and_delete_passes_only_when_the_control_principal_confirms_the_removal(
        self, tmp_path: Path
    ) -> None:
        t = _with_prerequisite(tmp_path)
        attempt = _prerequisite_attempt(t)
        statement = _prepared(t, "R8-LIST-AND-DELETE", earlier=("R8-GET",))
        client = FakePermissionClient(OK, NO_CONTENT)
        record = _rehearse(t, statement, client)
        assert [c[0] for c in client.calls] == ["list_objects", "delete_object"]
        assert client.calls[1][1]["key"] == statement.target.key
        assert record.outcome is dr.RehearsalOutcome.PASS and record.deleted and record.object_open
        status, reason = dr.derive_rehearsal(record, (), prerequisite_attempt=attempt)
        assert status is dr.RehearsalStatus.CLEANUP_UNRESOLVED and "not confirmed" in reason
        # The control principal's cleanup confirms the exact key absent: PASSED.
        control = t.control(tmp_path)
        assert t.cleanup(control, [NO_CONTENT, NOT_FOUND]) == tool.EXIT_EXECUTED
        cleanups = t.evidence().cleanups
        status, _ = dr.derive_rehearsal(record, cleanups, prerequisite_attempt=attempt)
        assert status is dr.RehearsalStatus.PASSED
        # An unverified cleanup pass confirms nothing; residue stays residue.
        unverified = pc.PermissionCleanup(
            stamp=cleanups[0].stamp,
            keys=cleanups[0].keys,
            tasks=(),
            deferred=(),
            residue=(),
            budget_exhausted=False,
            operations=cleanups[0].operations,
            binding=cleanups[0].binding,
            identity_verified=False,
            recorded_at=cleanups[0].recorded_at,
        )
        assert dr.derive_rehearsal(record, (unverified,), prerequisite_attempt=attempt)[0] is (
            dr.RehearsalStatus.CLEANUP_UNRESOLVED
        )

    def test_a_denied_list_issues_no_delete_and_an_ambiguous_delete_decides_nothing(
        self, tmp_path: Path
    ) -> None:
        t = _with_prerequisite(tmp_path)
        attempt = _prerequisite_attempt(t)
        statement = _prepared(t, "R8-LIST-AND-DELETE", earlier=("R8-GET",))
        client = FakePermissionClient(DENIED)
        record = _rehearse(t, statement, client)
        assert [c[0] for c in client.calls] == ["list_objects"]
        assert record.outcome is dr.RehearsalOutcome.FAIL and not record.object_open
        # Ambiguous delete: possibly deleted, INCONCLUSIVE, settled only by the control.
        client = FakePermissionClient(OK, TIMEOUT)
        record = _rehearse(t, _prepared(t, "R8-LIST-AND-DELETE", earlier=("R8-GET",)), client)
        assert record.outcome is dr.RehearsalOutcome.INCONCLUSIVE
        assert record.possibly_deleted and not record.deleted and record.object_open
        assert dr.derive_rehearsal(record, (), prerequisite_attempt=attempt)[0] is (
            dr.RehearsalStatus.CLEANUP_UNRESOLVED
        )
        control = t.control(tmp_path)
        assert t.cleanup(control, [NO_CONTENT, NOT_FOUND]) == tool.EXIT_EXECUTED
        # Confirmed removed, but the delete's own answer decided nothing.
        status, _ = dr.derive_rehearsal(record, t.evidence().cleanups, prerequisite_attempt=attempt)
        assert status is dr.RehearsalStatus.INCONCLUSIVE
        # A cleanup that could not confirm the key absent: RESIDUE.
        t2 = _with_prerequisite(tmp_path / "residue")
        attempt2 = _prerequisite_attempt(t2)
        record2 = _rehearse(
            t2,
            _prepared(t2, "R8-LIST-AND-DELETE", earlier=("R8-GET",)),
            FakePermissionClient(OK, NO_CONTENT),
        )
        control2 = t2.control(tmp_path / "residue")
        assert t2.cleanup(control2, [TIMEOUT, TIMEOUT]) == tool.EXIT_CLEANUP_UNRESOLVED
        status, _ = dr.derive_rehearsal(
            record2, t2.evidence().cleanups, prerequisite_attempt=attempt2
        )
        assert status is dr.RehearsalStatus.RESIDUE
