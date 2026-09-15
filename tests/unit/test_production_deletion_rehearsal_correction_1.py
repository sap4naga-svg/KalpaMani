"""Correction 1 of PR #109 (ADR-0050 s.8): the three review findings, each
reproduced on the reviewed head through the public tool and closed here.

1. Reservations and unresolved-launch recovery are anchored beside the canonical ledger
   with the whole specification; an unsettled attempt blocks every launch -- across records
   directories and new authorizations -- before anything is consumed; RunTask is never
   retried; uncertain cleanup stays unsettled.
2. One evidence-binding rule for completion and prerequisite admission: consumption,
   reservation, registered specification, launch, retained verified receipt and result must
   form one chain for exactly the deletion target; missing, substituted or conflicting
   evidence does not qualify; completion recovery is repeatable.
3. The accepted contradiction/disposition rules apply to the hand-read rehearsal completion
   as to collection and cache reuse: a hand receipt never silently supersedes a recorded
   contradiction, and the receipt binding survives interruptions.

Every answer is a fake's; the path is monkeypatched OPEN for this process only.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import production_deletion_rehearsal_tool as rt
import pytest
from test_production_deletion_rehearsal_path import _launch_fakes
from test_production_deletion_rehearsal_tool import (
    _inputs_file,
    _launched,
    _logs_pages,
    _prepare,
    _RehearsalClients,
    _rehearse,
    _run,
    _task_receipt,
    _tool,
)
from test_production_permission_cells import (
    DENIED,
    LISTED_NONE,
    LISTED_ONE,
    STOPPED,
    TIMEOUT,
    FakePermissionClient,
    _Tool,
    tool,
)

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar import deletion_rehearsal as dr
from kalpamani.data.production.sharadar import deletion_rehearsal_launch as dl
from kalpamani.data.production.sharadar import launch_store


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> None:
    assert dr.REHEARSAL_PATH_OPEN is False
    monkeypatch.setattr(dr, "REHEARSAL_PATH_OPEN", True)


def _launched_get(t: _Tool, inputs: Path, name: str = "auth.json") -> tuple[Any, str]:
    """R8-GET prepared, authorized and launched over fakes: the launch record and the line."""
    digest = _prepare(t, "R8-GET")
    authorization = t.authorize("R8-GET", digest, name=name)
    clients = _RehearsalClients(launch=_launch_fakes())
    code, out = _rehearse(t, "R8-GET", clients, inputs, authorization)
    assert code == rt.EXIT_REHEARSAL_LAUNCHED, out
    launch = _launched(t, clients)
    return launch, _task_receipt(t, launch, FakePermissionClient(DENIED))


def _complete_by_hand(t: _Tool, line: str, *extra: str, **overrides: Any) -> tuple[int, str]:
    lines = t.root / "lines.txt"
    lines.write_text(line + "\n", encoding="utf-8")
    return _run(
        t,
        "--complete-rehearsal",
        "R8-GET",
        *t.base(),
        "--receipt-lines",
        str(lines),
        *extra,
        **overrides,
    )


def _another_records_dir(t: _Tool) -> list[str]:
    """The tool's base arguments over a second records directory on the same ledger, with
    the permission records copied so the R-4 target still binds there."""
    other = t.root / "records-2"
    other.mkdir()
    for path in t.scenario.records.glob("permission-*.json"):
        shutil.copy(path, other / path.name)
    return [str(other) if a == str(t.scenario.records) else a for a in t.base()]


class _InterruptingEcs:
    """An ECS fake whose RunTask starts the task and then the process dies."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls = inner.calls

    def run_task(self, **kwargs: Any) -> Any:
        self.inner.run_task(**kwargs)
        raise KeyboardInterrupt

    def describe_tasks(self, **kwargs: Any) -> Any:
        return self.inner.describe_tasks(**kwargs)

    def stop_task(self, **kwargs: Any) -> Any:
        return self.inner.stop_task(**kwargs)


# ---------------------------------------------------------------------------
# Finding 1
# ---------------------------------------------------------------------------


class TestFinding1AnchoredReservationsAndRecovery:
    def test_an_ambiguous_launch_blocks_every_launch_until_a_verified_cleanup_settles_it(
        self, tmp_path: Path, opened: None
    ) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        digest = _prepare(t, "R8-GET")
        authorization = t.authorize("R8-GET", digest, name="auth-1.json")
        ambiguous = _RehearsalClients(launch=_launch_fakes())
        ambiguous.launch.ecs.run_failure = "ServerException"
        code, out = _rehearse(t, "R8-GET", ambiguous, inputs, authorization)
        assert code == rt.EXIT_REHEARSAL_NOT_LAUNCHED and "launch=LAUNCH_AMBIGUOUS" in out
        assert sum(1 for c in ambiguous.launch.ecs.calls if c[0] == "run_task") == 1
        store = t.scenario.store()
        # Anchored beside the canonical ledger, never under the records directory, with the
        # whole specification and the tag the cleanup lists by.
        assert t.files("rehearsal-reservation") == []
        [reservation] = dl.rehearsal_reservations(store).values()
        assert store.anchor_path(dl.REHEARSAL_RESERVATIONS_ANCHOR, reservation.identity).exists()
        assert (
            reservation.specification.inputs.task_definition_arn
            == dl.parse_rehearsal_launch_inputs(inputs.read_bytes()).task_definition_arn
        )
        [resolution] = dl.rehearsal_resolutions(store).values()
        assert resolution.task_state is dl.RehearsalTaskState.UNKNOWN
        # A new statement under a new authorization: refused before anything is consumed,
        # with no client call -- and from another records directory over the same ledger.
        main_authorization = None
        for label, base in (("main", t.base()), ("other", _another_records_dir(t))):
            code, out = _run(t, "--prepare-rehearsal", "R8-GET", *base)
            assert code == tool.EXIT_PREPARED
            digest2 = out.split("statement_sha256=")[1].split()[0]
            authorization2 = t.authorize("R8-GET", digest2, name=f"auth-{label}.json")
            if label == "main":
                main_authorization = authorization2
            again = _RehearsalClients(launch=_launch_fakes())
            code, out = _run(
                t,
                "--rehearse-deletion",
                "R8-GET",
                *base,
                "--rehearsal-inputs",
                str(inputs),
                "--authorization",
                str(authorization2),
                tool.AUTHORIZATION_FLAG,
                launch_clients=again,
            )
            assert code == tool.EXIT_REFUSED_RECOVERY_PENDING, out
            assert rt.SENTENCES["refused_rehearsal_recovery_pending"] in out
            assert again.launch.ecs.calls == [] and again.launch.ssm.calls == []
            assert len(store.consumptions(dr.REHEARSAL_CONSUMPTION_KIND)) == 1
        # Recovery does not apply to a resolved (ambiguous) attempt: nothing to recover.
        code, out = _run(t, "--recover-rehearsal-launch", "R8-GET", *t.base())
        assert code == tool.EXIT_REFUSED_RECOVERY
        assert main_authorization is not None
        # An uncertain cleanup (the listing by the tag timed out) preserves the block. The
        # R-4 object is answered with timeouts too, so it stays the rehearsal's target.
        control = t.control(tmp_path)
        control.clock.seconds = 1000.0
        assert t.cleanup(control, [TIMEOUT, TIMEOUT, TIMEOUT]) == tool.EXIT_CLEANUP_UNRESOLVED
        listed = [c for c in control.client.calls if c[0] == "list_tasks"]
        assert listed and listed[0][1]["started_by"] == reservation.started_by
        assert listed[0][1]["cluster_arn"] == reservation.cluster_arn
        assert len(dl.unsettled_rehearsals(store, t.evidence().cleanups)) == 1
        again = _RehearsalClients(launch=_launch_fakes())
        code, out = _rehearse(t, "R8-GET", again, inputs, main_authorization)
        assert code == tool.EXIT_REFUSED_RECOVERY_PENDING and again.launch.ecs.calls == []
        # A verified cleanup that discovers the task by the tag and confirms it stopped
        # settles the reservation; the next launch proceeds -- and RunTask was never
        # retried for the ambiguous attempt.
        control.clock.seconds += 60.0
        assert t.cleanup(control, [TIMEOUT, TIMEOUT, LISTED_ONE, STOPPED]) == (
            tool.EXIT_CLEANUP_UNRESOLVED  # the object's residue; the task is settled
        )
        assert dl.unsettled_rehearsals(store, t.evidence().cleanups) == []
        code, out = _rehearse(t, "R8-GET", again, inputs, main_authorization)
        assert code == rt.EXIT_REHEARSAL_LAUNCHED, out
        assert sum(1 for c in ambiguous.launch.ecs.calls if c[0] == "run_task") == 1

    def test_an_interrupted_launch_is_recovered_offline_and_stays_unsettled_until_cleanup(
        self, tmp_path: Path, opened: None
    ) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        digest = _prepare(t, "R8-GET")
        authorization = t.authorize("R8-GET", digest, name="auth-1.json")
        clients = _RehearsalClients(launch=_launch_fakes())
        clients.launch.ecs = _InterruptingEcs(clients.launch.ecs)  # type: ignore[assignment]
        with pytest.raises(KeyboardInterrupt):
            _rehearse(t, "R8-GET", clients, inputs, authorization)
        store = t.scenario.store()
        [reservation] = dl.rehearsal_reservations(store).values()
        assert dl.rehearsal_resolutions(store) == {}
        [unsettled] = dl.unsettled_rehearsals(store)
        assert unsettled.needs_recovery
        # Blocked, whatever the authorization; the recovery records the attribution
        # offline (no client), with the task state UNKNOWN; still blocked until the cleanup.
        digest2 = _prepare(t, "R8-GET")
        authorization2 = t.authorize("R8-GET", digest2, name="auth-2.json")
        again = _RehearsalClients(launch=_launch_fakes())
        code, out = _rehearse(t, "R8-GET", again, inputs, authorization2)
        assert code == tool.EXIT_REFUSED_RECOVERY_PENDING and again.launch.ecs.calls == []
        code, out = _run(t, "--recover-rehearsal-launch", "R8-GET", *t.base(), client_factory=None)
        assert code == tool.EXIT_RECOVERED, out
        assert f"started_by={reservation.started_by}" in out and "task_state=UNKNOWN" in out
        assert rt.SENTENCES["rehearsal_recovered"] in out
        [resolution] = dl.rehearsal_resolutions(store).values()
        assert resolution.outcome == dl.RECOVERED_INTERRUPTED
        assert resolution.task_state is dl.RehearsalTaskState.UNKNOWN
        code, out = _run(t, "--recover-rehearsal-launch", "R8-GET", *t.base())
        assert code == tool.EXIT_REFUSED_RECOVERY
        code, out = _rehearse(t, "R8-GET", again, inputs, authorization2)
        assert code == tool.EXIT_REFUSED_RECOVERY_PENDING and again.launch.ecs.calls == []
        # The accepted cleanup rule governs the settlement: a listing that finds nothing under
        # the tag settles nothing (the run may have started under a status the page did not
        # show), so the launch stays unresolved and still refused -- uncertain cleanup is
        # preserved as unresolved, never resolved by absence.
        control = t.control(tmp_path)
        control.clock.seconds = 1000.0
        assert t.cleanup(control, [TIMEOUT, TIMEOUT, LISTED_NONE]) == tool.EXIT_CLEANUP_UNRESOLVED
        assert len(dl.unsettled_rehearsals(store, t.evidence().cleanups)) == 1
        code, out = _rehearse(t, "R8-GET", again, inputs, authorization2)
        assert code == tool.EXIT_REFUSED_RECOVERY_PENDING and again.launch.ecs.calls == []
        # A later cleanup discovers the task under the tag and stops it: settled by
        # observation; only then does a launch proceed (under the still-unconsumed auth-2).
        control.clock.seconds = 2000.0
        assert t.cleanup(control, [TIMEOUT, TIMEOUT, LISTED_ONE, STOPPED]) == (
            tool.EXIT_CLEANUP_UNRESOLVED
        )
        assert dl.unsettled_rehearsals(store, t.evidence().cleanups) == []
        code, out = _rehearse(t, "R8-GET", again, inputs, authorization2)
        assert code == rt.EXIT_REHEARSAL_LAUNCHED, out

    def test_a_reservation_is_exclusive_and_a_malformed_anchor_refuses(
        self, tmp_path: Path, opened: None
    ) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        launch, _line = _launched_get(t, inputs)
        store = t.scenario.store()
        # The same identity cannot be reserved twice, whatever the records directory.
        with pytest.raises(launch_store.StoreError) as refusal:
            store.anchor(dl.REHEARSAL_RESERVATIONS_ANCHOR, launch.identity, {"x": 1})
        assert refusal.value.defect is launch_store.StoreDefect.ANCHOR_EXISTS
        # A malformed reservation beside the ledger refuses every mode rather than unblocks.
        store.anchor(dl.REHEARSAL_RESERVATIONS_ANCHOR, "rehearsal-20260912T150100Z-ffff", {"x": 1})
        code, _out = _run(t, "--prepare-rehearsal", "R8-GET", *t.base())
        assert code == rt.EXIT_REFUSED_REHEARSAL_RECORDS


# ---------------------------------------------------------------------------
# Finding 2
# ---------------------------------------------------------------------------


class TestFinding2OneEvidenceBindingRule:
    def test_missing_substituted_or_conflicting_evidence_does_not_qualify(
        self, tmp_path: Path, opened: None
    ) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        launch, line = _launched_get(t, inputs)
        store = t.scenario.store()
        consumed = store.consumed_path(dr.REHEARSAL_CONSUMPTION_KIND, launch.authorization_sha256)
        reservation_path = store.anchor_path(dl.REHEARSAL_RESERVATIONS_ANCHOR, launch.identity)
        [launch_path] = t.files("rehearsal-launch-record")
        # The consumption removed: the completion refuses, and writes nothing.
        kept = consumed.read_bytes()
        consumed.unlink()
        code, out = _complete_by_hand(t, line)
        assert code == tool.EXIT_REFUSED_COMPLETION and "CONSUMPTION_MISSING" in out
        assert t.files("rehearsal-record") == [] and t.files("rehearsal-receipt") == []
        consumed.write_bytes(kept)
        # The consumption naming another statement: conflicting.
        consumed.write_bytes(
            canonical_bytes({"subcell_id": "R8-GET", "statement_sha256": "ab" * 32})
        )
        code, out = _complete_by_hand(t, line)
        assert code == tool.EXIT_REFUSED_COMPLETION and "CONSUMPTION_CONFLICTS" in out
        consumed.write_bytes(kept)
        # The reservation substituted (another specification): the launch no longer binds.
        original = reservation_path.read_bytes()
        document = json.loads(original)
        document["specification"]["stamp"] = "20260912T150100Z-ffff"
        document["identity"] = "rehearsal-20260912T150100Z-ffff"
        reservation_path.unlink()
        store.anchor(dl.REHEARSAL_RESERVATIONS_ANCHOR, launch.identity, document)
        code, out = _complete_by_hand(t, line)
        assert code == rt.EXIT_REFUSED_REHEARSAL_RECORDS  # the anchor no longer names its identity
        reservation_path.write_bytes(original)
        # The launch record's reservation digest tampered: SPECIFICATION_MISMATCH.
        launch_document = json.loads(launch_path.read_bytes())
        launch_document["reservation_sha256"] = "cd" * 32
        launch_path.write_bytes(canonical_bytes(launch_document))
        code, out = _complete_by_hand(t, line)
        assert code == tool.EXIT_REFUSED_COMPLETION and "SPECIFICATION_MISMATCH" in out
        launch_path.write_bytes(
            canonical_bytes(
                json.loads(launch_path.read_bytes())
                | {"reservation_sha256": launch.reservation_sha256}
            )
        )
        # A second, conflicting launch record for the identity: nothing is chosen.
        other = dict(json.loads(launch_path.read_bytes()))
        other["observed_exit_code"] = 57
        duplicate = launch_path.with_name(launch_path.name.replace(".json", "-dup.json"))
        duplicate.write_bytes(canonical_bytes(other))
        code, out = _complete_by_hand(t, line)
        assert code == tool.EXIT_REFUSED_COMPLETION
        duplicate.unlink()
        # The valid control: completed, the receipt retained, the result bound.
        code, out = _complete_by_hand(t, line)
        assert code == tool.EXIT_EXECUTED and "status=PASSED" in out
        [record_path] = t.files("rehearsal-record")
        [receipt_path] = t.files("rehearsal-receipt")
        record = dr.parse_rehearsal_record(record_path.read_bytes())
        evidence = dl.parse_rehearsal_receipt_evidence(receipt_path.read_bytes())
        assert evidence.launch_record_sha256 == launch.digest
        bound = dl.bind_rehearsal_result(
            record,
            target=record.target,
            consumptions=store.consumptions(dr.REHEARSAL_CONSUMPTION_KIND),
            reservations=dl.rehearsal_reservations(store).values(),
            launches=[launch],
            receipts=[evidence],
        )
        assert bound.launch == launch and bound.receipt == evidence
        # The retained receipt removed, or substituted by another launch's: the record no
        # longer qualifies as the GET prerequisite (R8-LIST-AND-DELETE is not preparable).
        kept_receipt = receipt_path.read_bytes()
        receipt_path.unlink()
        code, out = _run(t, "--prepare-rehearsal", "R8-LIST-AND-DELETE", *t.base())
        assert code == tool.EXIT_REFUSED_PREREQUISITE
        substituted = json.loads(kept_receipt)
        substituted["launch_record_sha256"] = "ef" * 32
        receipt_path.write_bytes(canonical_bytes(substituted))
        code, out = _run(t, "--prepare-rehearsal", "R8-LIST-AND-DELETE", *t.base())
        assert code == tool.EXIT_REFUSED_PREREQUISITE
        receipt_path.write_bytes(kept_receipt)
        code, out = _run(t, "--prepare-rehearsal", "R8-LIST-AND-DELETE", *t.base())
        assert code == tool.EXIT_PREPARED

    def test_the_get_prerequisite_must_concern_the_exact_deletion_target(
        self, tmp_path: Path, opened: None
    ) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        _launch, line = _launched_get(t, inputs)
        assert _complete_by_hand(t, line)[0] == tool.EXIT_EXECUTED
        [record_path] = t.files("rehearsal-record")
        original = record_path.read_bytes()
        document = json.loads(original)
        document["target"]["key"] = document["target"]["key"][:-4] + "ffff"
        record_path.write_bytes(canonical_bytes(document))
        code, _out = _run(t, "--prepare-rehearsal", "R8-LIST-AND-DELETE", *t.base())
        assert code == tool.EXIT_REFUSED_PREREQUISITE
        record_path.write_bytes(original)
        code, _out = _run(t, "--prepare-rehearsal", "R8-LIST-AND-DELETE", *t.base())
        assert code == tool.EXIT_PREPARED
        # The rule itself: a record for another target is TARGET_MISMATCH.
        record = dr.parse_rehearsal_record(original)
        other = dr.RehearsalTarget(
            bucket=record.target.bucket,
            key=record.target.key[:-4] + "ffff",
            prerequisite_sha256=record.target.prerequisite_sha256,
        )
        with pytest.raises(dl.RehearsalBindingError) as refusal:
            dl.bind_rehearsal_result(
                record,
                target=other,
                consumptions={},
                reservations=(),
                launches=(),
                receipts=(),
            )
        assert refusal.value.defect is dl.RehearsalBindingDefect.TARGET_MISMATCH

    def test_completion_recovery_is_repeatable(self, tmp_path: Path, opened: None) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        launch, line = _launched_get(t, inputs)
        # Interrupted after the record, before the retained receipt: the same receipt
        # writes exactly the missing evidence; another receipt refuses; then whole.
        assert _complete_by_hand(t, line)[0] == tool.EXIT_EXECUTED
        [receipt_path] = t.files("rehearsal-receipt")
        receipt_path.unlink()
        assert t.files("rehearsal-receipt") == [] and len(t.files("rehearsal-record")) == 1
        other = _task_receipt(t, launch, FakePermissionClient(TIMEOUT))
        code, _out = _complete_by_hand(t, other)
        assert code == tool.EXIT_REFUSED_COMPLETION and t.files("rehearsal-receipt") == []
        code, _out = _complete_by_hand(t, line)
        assert code == tool.EXIT_EXECUTED
        assert len(t.files("rehearsal-record")) == 1 and len(t.files("rehearsal-receipt")) == 1
        code, _out = _complete_by_hand(t, line)
        assert code == tool.EXIT_COMPLETION_RECORDED
        assert len(t.files("rehearsal-record")) == 1 and len(t.files("rehearsal-receipt")) == 1
        # Interrupted after the retained receipt, before the record: the same repair.
        [record_path] = t.files("rehearsal-record")
        record_path.unlink()
        code, _out = _complete_by_hand(t, other)
        assert code == tool.EXIT_REFUSED_COMPLETION and t.files("rehearsal-record") == []
        code, _out = _complete_by_hand(t, line)
        assert code == tool.EXIT_EXECUTED
        assert len(t.files("rehearsal-record")) == 1 and len(t.files("rehearsal-receipt")) == 1


# ---------------------------------------------------------------------------
# Finding 3
# ---------------------------------------------------------------------------


class TestFinding3ContradictionsOnTheHandPath:
    def _contradiction(self, t: _Tool, inputs: Path) -> tuple[Any, str, str, _RehearsalClients]:
        digest = _prepare(t, "R8-GET")
        authorization = t.authorize("R8-GET", digest, name="auth.json")
        clients = _RehearsalClients(launch=_launch_fakes())
        assert _rehearse(t, "R8-GET", clients, inputs, authorization)[0] == 0
        launch = _launched(t, clients)
        line = _task_receipt(t, launch, FakePermissionClient(DENIED))
        other = line[:-3] + '0"}'
        clients.logs_fake.answers = [
            {"events": [{"message": line}, {"message": other}], "nextForwardToken": "end"},
            {"events": [], "nextForwardToken": "end"},
        ]
        code, out = _run(
            t,
            "--collect-rehearsal-receipt",
            "R8-GET",
            *t.base(),
            "--rehearsal-inputs",
            str(inputs),
            tool.COLLECT_FLAG,
            launch_clients=clients,
            monotonic=clients.launch.clock.monotonic,
            sleep=clients.launch.clock.sleep,
            now=clients.launch.clock.now,
        )
        assert code == tool.EXIT_COLLECTION_NOT_COLLECTED and "CONTRADICTORY_RECEIPTS" in out
        [collection] = t.files("receipt-collection")
        return launch, line, sha256_hex(collection.read_bytes()), clients

    def test_a_hand_receipt_never_silently_supersedes_a_recorded_contradiction(
        self, tmp_path: Path, opened: None
    ) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        launch, line, contradiction, clients = self._contradiction(t, inputs)
        # Without the acknowledgement, or with the wrong digest: refused, nothing written.
        code, out = _complete_by_hand(t, line)
        assert code == tool.EXIT_REFUSED_CONTRADICTION_UNRESOLVED
        code, out = _complete_by_hand(t, line, tool.ACKNOWLEDGE_FLAG, "ab" * 32)
        assert code == tool.EXIT_REFUSED_CONTRADICTION_UNRESOLVED
        assert t.files("rehearsal-record") == [] and t.files("collection-disposition") == []
        # A second collection does not resolve it either.
        clients.logs_fake.answers = _logs_pages(line)
        code, out = _run(
            t,
            "--collect-rehearsal-receipt",
            "R8-GET",
            *t.base(),
            "--rehearsal-inputs",
            str(inputs),
            tool.COLLECT_FLAG,
            launch_clients=clients,
            monotonic=clients.launch.clock.monotonic,
            sleep=clients.launch.clock.sleep,
            now=clients.launch.clock.now,
        )
        assert code == tool.EXIT_REFUSED_CONTRADICTION_UNRESOLVED
        # Acknowledged by digest: completed, disposed beside the record, bound to this receipt.
        code, out = _complete_by_hand(t, line, tool.ACKNOWLEDGE_FLAG, contradiction)
        assert code == tool.EXIT_EXECUTED, out
        [disposition_path] = t.files("collection-disposition")
        disposition = json.loads(disposition_path.read_bytes())
        assert disposition["contradiction_sha256"] == contradiction
        assert disposition["receipt_line_sha256"] == sha256_hex(line.encode("utf-8"))
        assert disposition["launch_record_sha256"] == launch.digest
        assert len(t.files("rehearsal-record")) == 1 and len(t.files("rehearsal-receipt")) == 1

    def test_the_receipt_binding_survives_interruptions(self, tmp_path: Path, opened: None) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        launch, line, contradiction, clients = self._contradiction(t, inputs)
        assert (
            _complete_by_hand(t, line, tool.ACKNOWLEDGE_FLAG, contradiction)[0]
            == tool.EXIT_EXECUTED
        )
        # Interrupted after the disposition and before the record and the receipt: the
        # disposition binds the launch to receipt A -- receipt B refuses everywhere, the
        # collector included; receipt A finishes the completion.
        for path in [*t.files("rehearsal-record"), *t.files("rehearsal-receipt")]:
            path.unlink()
        other = _task_receipt(t, launch, FakePermissionClient(TIMEOUT))
        code, _out = _complete_by_hand(t, other, tool.ACKNOWLEDGE_FLAG, contradiction)
        assert code == tool.EXIT_REFUSED_RECEIPT_BINDING
        clients.logs_fake.answers = _logs_pages(other)
        code, _out = _run(
            t,
            "--collect-rehearsal-receipt",
            "R8-GET",
            *t.base(),
            "--rehearsal-inputs",
            str(inputs),
            tool.COLLECT_FLAG,
            launch_clients=clients,
        )
        assert code == tool.EXIT_REFUSED_RECEIPT_BINDING
        assert t.files("rehearsal-record") == [] and len(t.files("collection-disposition")) == 1
        code, _out = _complete_by_hand(t, line, tool.ACKNOWLEDGE_FLAG, contradiction)
        assert code == tool.EXIT_EXECUTED
        assert len(t.files("rehearsal-record")) == 1 and len(t.files("collection-disposition")) == 1
        # Repeated with the same acknowledgement: already whole, nothing changed.
        code, _out = _complete_by_hand(t, line, tool.ACKNOWLEDGE_FLAG, contradiction)
        assert code == tool.EXIT_COMPLETION_RECORDED
        assert len(t.files("collection-disposition")) == 1

    def test_the_acknowledgement_flag_belongs_to_the_hand_path_only(
        self, tmp_path: Path, opened: None
    ) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        for argv in (
            ("--prepare-rehearsal", "R8-GET", tool.ACKNOWLEDGE_FLAG, "ab" * 32),
            (
                "--collect-rehearsal-receipt",
                "R8-GET",
                "--rehearsal-inputs",
                str(inputs),
                tool.COLLECT_FLAG,
                tool.ACKNOWLEDGE_FLAG,
                "ab" * 32,
            ),
            (
                "--complete-rehearsal",
                "R8-GET",
                "--receipt-lines",
                str(inputs),
                tool.ACKNOWLEDGE_FLAG,
                "not-a-digest",
            ),
        ):
            code, _out = _run(t, *argv, *t.base())
            assert code == tool.EXIT_REFUSED_ARGUMENTS, argv
