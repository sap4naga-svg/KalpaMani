"""The permission tool's rehearsal modes end to end, with the path monkeypatched OPEN for
the test and nothing else (ADR-0049 s.3; proposed ADR-0050): prepare, authorize, launch
over fakes, collect the receipt from a fake stream, complete, clean up, read. Every refusal
the tool makes before a client exists is exercised the same way. The tracked constant stays
False; only this process's copy is patched, and only inside these tests."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import production_deletion_rehearsal_tool as rt
import pytest
from test_production_deletion_rehearsal import _prerequisite_attempt, _with_prerequisite
from test_production_deletion_rehearsal_path import (
    LAUNCHER_ARN,
    REHEARSAL_REVISION_ARN,
    TASK_IDENTITY_ARN,
    _binding_document,
    _inputs,
    _launch_fakes,
    _LaunchFakes,
    _TaskFakes,
)
from test_production_permission_cells import (
    DENIED,
    NO_CONTENT,
    NOT_FOUND,
    OK,
    FakePermissionClient,
    _Tool,
    tool,
)

from fixtures.production_launch import FakeLogs, FakeSts
from fixtures.production_runtime import ACCOUNT, NOW, TASK_ARN, TASK_ID
from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar import deletion_rehearsal as dr
from kalpamani.data.production.sharadar import deletion_rehearsal_launch as dl
from kalpamani.data.production.sharadar import deletion_rehearsal_task as dt
from kalpamani.data.production.sharadar.r3_verification import ObservedClass


@dataclass
class _RehearsalClients:
    """The launch clients the tool asks for, each held to the rehearsal launcher's profile."""

    launch: _LaunchFakes
    logs_fake: FakeLogs = field(default_factory=FakeLogs)
    sts_fake: FakeSts = field(default_factory=lambda: FakeSts(LAUNCHER_ARN))
    constructions: list[tuple[str, str]] = field(default_factory=list)

    def _held(self, service: str, profile: str) -> None:
        assert profile == dr.REHEARSAL_LAUNCHER_PROFILE, (service, profile)
        self.constructions.append((service, profile))

    def sts(self, profile: str) -> Any:
        self._held("sts", profile)
        return self.sts_fake

    def ecs(self, profile: str) -> Any:
        self._held("ecs", profile)
        return self.launch.ecs

    def ec2(self, profile: str) -> Any:
        self._held("ec2", profile)
        return self.launch.ec2

    def ssm(self, profile: str) -> Any:
        self._held("ssm", profile)
        return self.launch.ssm

    def logs(self, profile: str) -> Any:
        self._held("logs", profile)
        return self.logs_fake


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> None:
    """The path OPEN for this process only; the tracked constant is False and stays so."""
    assert dr.REHEARSAL_PATH_OPEN is False
    monkeypatch.setattr(dr, "REHEARSAL_PATH_OPEN", True)


def _tool(tmp_path: Path) -> _Tool:
    t = _with_prerequisite(tmp_path)
    t.env["AWS_PROFILE"] = dr.REHEARSAL_LAUNCHER_PROFILE
    return t


def _inputs_file(t: _Tool, **overrides: Any) -> Path:
    path = t.root / "rehearsal-launch-inputs.json"
    document = _inputs().document()
    document.update(overrides)
    path.write_bytes(canonical_bytes(document))
    return path


def _run(t: _Tool, *argv: str, **overrides: Any) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = t.main(*argv, **overrides)
    return code, buffer.getvalue()


def _prepare(t: _Tool, subcell: str) -> str:
    code, out = _run(t, "--prepare-rehearsal", subcell, *t.base())
    assert code == tool.EXIT_PREPARED, out
    assert rt.SENTENCES["rehearsal_prepared"] in out
    return out.split("statement_sha256=")[1].split()[0]


def _rehearse(
    t: _Tool, subcell: str, clients: _RehearsalClients, inputs: Path, authorization: Path
) -> tuple[int, str]:
    return _run(
        t,
        "--rehearse-deletion",
        subcell,
        *t.base(),
        "--rehearsal-inputs",
        str(inputs),
        "--authorization",
        str(authorization),
        tool.AUTHORIZATION_FLAG,
        launch_clients=clients,
        monotonic=clients.launch.clock.monotonic,
        sleep=clients.launch.clock.sleep,
        now=clients.launch.clock.now,
    )


def _task_receipt(t: _Tool, launch: dl.RehearsalLaunchRecord, s3: FakePermissionClient) -> str:
    """The receipt the task emits for the tool's own launch: run over the exact input bytes
    the launcher put (captured from the fake channel) and a release naming this task."""
    fakes = _TaskFakes(s3=s3)
    fakes.clock.seconds = (launch.launched_at - NOW).total_seconds()
    fakes.ssm.values[dr.REHEARSAL_BINDING_PARAMETER] = _binding_document()
    fakes.ssm.values[dr.REHEARSAL_INPUT_PARAMETER] = t.rehearsal_input_bytes  # type: ignore[attr-defined]
    issued = fakes.clock.now()
    fakes.ssm.values[dr.REHEARSAL_RELEASE_PARAMETER] = dt.RehearsalRelease(
        identity=launch.identity,
        task_arn=TASK_ARN,
        task_definition_arn=REHEARSAL_REVISION_ARN,
        image_digest=launch.image_digest,
        input_digest=launch.input_digest,
        issued_at=issued,
        expires_at=issued + timedelta(minutes=5),
    ).render()
    receipt = fakes.run().receipt
    assert receipt.outcome is dt.RehearsalTaskOutcome.REHEARSED
    return receipt.line()


def _launched(t: _Tool, clients: _RehearsalClients) -> dl.RehearsalLaunchRecord:
    launch = dl.parse_rehearsal_launch_record(t.files("rehearsal-launch-record")[-1].read_bytes())
    put = next(
        kw
        for name, kw in clients.launch.ssm.calls
        if name == "put_parameter" and kw["Name"] == dr.REHEARSAL_INPUT_PARAMETER
    )
    t.rehearsal_input_bytes = put["Value"].encode("utf-8")  # type: ignore[attr-defined]
    return launch


def _logs_pages(line: str) -> list[dict[str, Any]]:
    """One page carrying the receipt, then the end of the stream (repeated)."""
    return [
        {
            "events": [{"message": "bootstrap"}, {"message": line}],
            "nextForwardToken": "end",
        },
        {"events": [], "nextForwardToken": "end"},
    ]


class TestRehearsalModesOpen:
    def test_the_sequence_end_to_end_over_fakes(self, tmp_path: Path, opened: None) -> None:
        t = _tool(tmp_path)
        attempt = _prerequisite_attempt(t)
        inputs = _inputs_file(t)
        # R8-GET: prepare, authorize, launch, collect from the stream, complete.
        digest = _prepare(t, "R8-GET")
        [statement_path] = t.files("rehearsal-statement")
        statement = dt.parse_rehearsal_statement(statement_path.read_bytes())
        assert statement.digest == digest and statement.subcell_id == "R8-GET"
        authorization = t.authorize("R8-GET", digest, name="rehearsal-auth-get.json")
        clients = _RehearsalClients(launch=_launch_fakes())
        code, out = _rehearse(t, "R8-GET", clients, inputs, authorization)
        assert code == rt.EXIT_REHEARSAL_LAUNCHED, out
        assert "rehearsal launch=LAUNCHED subcell=R8-GET run_tasks=1" in out
        assert rt.SENTENCES["rehearsal_launched"] in out
        assert [c[0] for c in clients.constructions] == ["sts", "ecs", "ec2", "ssm", "sts"]
        assert clients.sts_fake.calls == 2
        launch = _launched(t, clients)
        assert launch.observed_exit_code == 50 and launch.statement_sha256 == digest
        assert t.scenario.store().is_consumed(
            dr.REHEARSAL_CONSUMPTION_KIND, launch.authorization_sha256
        )
        # A second launch of the same statement: the pending launch is completed first.
        clients2 = _RehearsalClients(launch=_launch_fakes())
        code, out = _rehearse(t, "R8-GET", clients2, inputs, authorization)
        assert code == tool.EXIT_REFUSED_COMPLETION and clients2.constructions == []
        line = _task_receipt(t, launch, FakePermissionClient(DENIED))
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
        assert code == tool.EXIT_EXECUTED, out
        assert "collection=COLLECTED" in out and "status=PASSED" in out
        assert rt.SENTENCES["rehearsal_passed"] in out
        assert clients.constructions[-2:] == [
            ("sts", dr.REHEARSAL_LAUNCHER_PROFILE),
            ("logs", dr.REHEARSAL_LAUNCHER_PROFILE),
        ]
        assert clients.logs_fake.calls and all(
            c["logStreamName"] == f"{dr.REHEARSAL_STREAM_PREFIX}/{dr.REHEARSAL_CONTAINER}/{TASK_ID}"
            for c in clients.logs_fake.calls
        )
        assert len(t.files("receipt-collection")) == 1
        [record_path] = t.files("rehearsal-record")
        record = dr.parse_rehearsal_record(record_path.read_bytes())
        assert record.outcome is dr.RehearsalOutcome.PASS and record.identity_verified
        assert record.observed == (ObservedClass.DENIED_OTHER,)
        # The same authorization again: consumed, and nothing pending to complete.
        clients3 = _RehearsalClients(launch=_launch_fakes())
        code, out = _rehearse(t, "R8-GET", clients3, inputs, authorization)
        assert code == tool.EXIT_REFUSED_AUTHORIZATION_CONSUMED, out
        assert clients3.launch.ecs.calls == [] and clients3.launch.ssm.calls == []
        # R8-LIST-AND-DELETE: preparable only now; launched; completed from hand-read lines.
        digest2 = _prepare(t, "R8-LIST-AND-DELETE")
        authorization2 = t.authorize("R8-LIST-AND-DELETE", digest2, name="rehearsal-auth-del.json")
        clients4 = _RehearsalClients(launch=_launch_fakes())
        clients4.launch.clock.seconds = 1000.0
        code, out = _rehearse(t, "R8-LIST-AND-DELETE", clients4, inputs, authorization2)
        assert code == rt.EXIT_REHEARSAL_LAUNCHED, out
        launch2 = _launched(t, clients4)
        line2 = _task_receipt(t, launch2, FakePermissionClient(OK, NO_CONTENT))
        lines = t.root / "receipt-lines.txt"
        lines.write_text(f"deletion rehearsal REHEARSED\n{line2}\n", encoding="utf-8")
        code, out = _run(
            t,
            "--complete-rehearsal",
            "R8-LIST-AND-DELETE",
            *t.base(),
            "--receipt-lines",
            str(lines),
            now=clients4.launch.clock.now,
        )
        assert code == tool.EXIT_CLEANUP_UNRESOLVED, out
        assert "status=CLEANUP_UNRESOLVED" in out and "deleted=yes" in out
        assert rt.SENTENCES["rehearsal_cleanup_unresolved"] in out
        records = [dr.parse_rehearsal_record(p.read_bytes()) for p in t.files("rehearsal-record")]
        assert [r.subcell_id for r in records] == ["R8-GET", "R8-LIST-AND-DELETE"]
        # The same lines again: nothing pending, refused, no second record.
        code, out = _run(
            t,
            "--complete-rehearsal",
            "R8-LIST-AND-DELETE",
            *t.base(),
            "--receipt-lines",
            str(lines),
        )
        assert code == tool.EXIT_REFUSED_COMPLETION and len(t.files("rehearsal-record")) == 2
        # The control principal's later verified cleanup confirms the key absent: PASSED.
        control = t.control(tmp_path)
        control.clock.seconds = clients4.launch.clock.seconds + 60.0
        assert t.cleanup(control, [NO_CONTENT, NOT_FOUND]) == tool.EXIT_EXECUTED
        status, _ = dr.derive_rehearsal(
            records[1], t.evidence().cleanups, prerequisite_attempt=attempt
        )
        assert status is dr.RehearsalStatus.PASSED
        # Nothing was executed through the permission client factory, and the two R-8
        # subcells stay BLOCKED in the derived matrix whatever the records say.
        assert all(profile != dr.REHEARSAL_LAUNCHER_PROFILE for profile, _ in t.constructions)
        from kalpamani.data.production.sharadar import permission_cells as pc

        state = pc.derive_subcell(pc.subcell("R8-GET"), t.evidence(), r1_passed={})
        assert state.status is pc.SubcellStatus.BLOCKED

    def test_every_refusal_before_a_client(self, tmp_path: Path, opened: None) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        # The sequence: R8-LIST-AND-DELETE is not preparable before R8-GET is recorded.
        code, out = _run(t, "--prepare-rehearsal", "R8-LIST-AND-DELETE", *t.base())
        assert code == tool.EXIT_REFUSED_PREREQUISITE and t.files("rehearsal-statement") == []
        code, _ = _run(t, "--prepare-rehearsal", "R4-PUT-PAYLOAD-HUMAN", *t.base())
        assert code == tool.EXIT_REFUSED_SUBCELL
        # A launch without a prepared statement, or with an authorization for another.
        digest = _prepare(t, "R8-GET")
        other = t.authorize("R8-GET", "ab" * 32, name="rehearsal-auth-other.json")
        clients = _RehearsalClients(launch=_launch_fakes())
        code, _ = _rehearse(t, "R8-GET", clients, inputs, other)
        assert code == tool.EXIT_REFUSED_PREPARATION and clients.constructions == []
        authorization = t.authorize("R8-GET", digest, name="rehearsal-auth-get.json")
        # The wrong profile: refused before any client, nothing consumed.
        t.env["AWS_PROFILE"] = "kalpamani-production-acquisition"
        code, _ = _rehearse(t, "R8-GET", clients, inputs, authorization)
        assert code == tool.EXIT_REFUSED_IDENTITY and clients.constructions == []
        t.env["AWS_PROFILE"] = dr.REHEARSAL_LAUNCHER_PROFILE
        # The wrong identity under the right profile: refused by the sequence, nothing
        # consumed, no ECS or SSM call.
        wrong = _RehearsalClients(launch=_launch_fakes(), sts_fake=FakeSts(TASK_IDENTITY_ARN))
        code, _ = _rehearse(t, "R8-GET", wrong, inputs, authorization)
        assert code == tool.EXIT_REFUSED_IDENTITY
        assert wrong.launch.ecs.calls == [] and wrong.launch.ssm.calls == []
        assert not t.scenario.store().consumptions(dr.REHEARSAL_CONSUMPTION_KIND)
        # Inputs of another account, another family, a malformed file: refused before
        # identity and before any client.
        for name, document_overrides, raw in (
            (
                "account",
                {"cluster_arn": _inputs().cluster_arn.replace(ACCOUNT, "111111111111")},
                None,
            ),
            (
                "family",
                {
                    "task_definition_arn": REHEARSAL_REVISION_ARN.replace(
                        dr.REHEARSAL_FAMILY, "kalpamani-production-acquire"
                    )
                },
                None,
            ),
            ("malformed", {}, b"{not json"),
        ):
            path = t.root / f"inputs-{name}.json"
            if raw is not None:
                path.write_bytes(raw)
            else:
                document = _inputs().document()
                document.update(document_overrides)
                path.write_bytes(canonical_bytes(document))
            clients = _RehearsalClients(launch=_launch_fakes())
            code, out = _rehearse(t, "R8-GET", clients, path, authorization)
            assert code == tool.EXIT_REFUSED_BINDING, name
            assert rt.SENTENCES["refused_rehearsal_inputs"] in out and clients.constructions == []
        # Flags and paths: each mode takes exactly its own.
        for argv in (
            (
                "--rehearse-deletion",
                "R8-GET",
                "--rehearsal-inputs",
                str(inputs),
                "--authorization",
                str(authorization),
            ),
            (
                "--rehearse-deletion",
                "R8-GET",
                "--authorization",
                str(authorization),
                tool.AUTHORIZATION_FLAG,
            ),
            ("--prepare-rehearsal", "R8-GET", tool.AUTHORIZATION_FLAG),
            ("--collect-rehearsal-receipt", "R8-GET", "--rehearsal-inputs", str(inputs)),
            ("--complete-rehearsal", "R8-GET"),
            (
                "--complete-rehearsal",
                "R8-GET",
                "--receipt-lines",
                str(inputs),
                "--prepare-rehearsal",
                "R8-GET",
            ),
            ("--rehearsal-inputs", str(inputs)),
        ):
            code, out = _run(t, *argv, *t.base())
            assert code == tool.EXIT_REFUSED_ARGUMENTS, argv
        # Nothing to complete or collect: refused, no client.
        code, _ = _run(
            t, "--complete-rehearsal", "R8-GET", *t.base(), "--receipt-lines", str(inputs)
        )
        assert code == tool.EXIT_REFUSED_COMPLETION
        clients = _RehearsalClients(launch=_launch_fakes())
        code, _ = _run(
            t,
            "--collect-rehearsal-receipt",
            "R8-GET",
            *t.base(),
            "--rehearsal-inputs",
            str(inputs),
            tool.COLLECT_FLAG,
            launch_clients=clients,
        )
        assert code == tool.EXIT_REFUSED_COMPLETION and clients.constructions == []
        # A launch the sequence refused (RunTask denied): recorded as not launched, the
        # authorization consumed, the reservation kept; then nothing is pending.
        refused = _RehearsalClients(launch=_launch_fakes())
        refused.launch.ecs.run_failure = "AccessDeniedException"
        code, out = _rehearse(t, "R8-GET", refused, inputs, authorization)
        assert code == rt.EXIT_REHEARSAL_NOT_LAUNCHED and "launch=LAUNCH_REFUSED" in out
        assert rt.SENTENCES["rehearsal_not_launched"] in out
        assert (
            len(t.files("rehearsal-reservation")) == 1 and t.files("rehearsal-launch-record") == []
        )
        assert t.scenario.store().consumptions(dr.REHEARSAL_CONSUMPTION_KIND)
        code, _ = _rehearse(
            t, "R8-GET", _RehearsalClients(launch=_launch_fakes()), inputs, authorization
        )
        assert code == tool.EXIT_REFUSED_AUTHORIZATION_CONSUMED
        # A malformed rehearsal record refuses every mode that reads the records.
        (t.scenario.records / "rehearsal-record-20260912T140000Z-ffff.json").write_bytes(b"{")
        code, out = _run(t, "--prepare-rehearsal", "R8-GET", *t.base())
        assert code == rt.EXIT_REFUSED_REHEARSAL_RECORDS
        assert rt.SENTENCES["refused_rehearsal_records"] in out

    def test_a_receipt_that_does_not_verify_completes_nothing(
        self, tmp_path: Path, opened: None
    ) -> None:
        t = _tool(tmp_path)
        inputs = _inputs_file(t)
        digest = _prepare(t, "R8-GET")
        authorization = t.authorize("R8-GET", digest, name="rehearsal-auth-get.json")
        clients = _RehearsalClients(launch=_launch_fakes())
        code, _ = _rehearse(t, "R8-GET", clients, inputs, authorization)
        assert code == rt.EXIT_REHEARSAL_LAUNCHED
        launch = _launched(t, clients)
        # A refused task (no release): its receipt is bound and verifies, and completes
        # nothing -- the exit the launcher observed (50) contradicts it first.
        fakes = _TaskFakes()
        fakes.ssm.values[dr.REHEARSAL_BINDING_PARAMETER] = _binding_document()
        fakes.ssm.values[dr.REHEARSAL_INPUT_PARAMETER] = t.rehearsal_input_bytes  # type: ignore[attr-defined]
        refused = fakes.run().receipt
        assert refused.outcome is dt.RehearsalTaskOutcome.REFUSED_RELEASE
        lines = t.root / "refused-lines.txt"
        lines.write_text(refused.line() + "\n", encoding="utf-8")
        code, out = _run(
            t, "--complete-rehearsal", "R8-GET", *t.base(), "--receipt-lines", str(lines)
        )
        assert code == tool.EXIT_REFUSED_COMPLETION and "EXIT_CONTRADICTS" in out
        assert t.files("rehearsal-record") == []
        # Another task's receipt (another input): refused by the verifier, through the
        # collector too (RECEIPT_REJECTED, recorded, not completed), then the right one.
        other_fakes = _TaskFakes()
        other_fakes.ssm.values[dr.REHEARSAL_BINDING_PARAMETER] = _binding_document()
        other_input = json.loads(t.rehearsal_input_bytes)  # type: ignore[attr-defined]
        other_input["authorization_sha256"] = "ee" * 32
        other_fakes.ssm.values[dr.REHEARSAL_INPUT_PARAMETER] = canonical_bytes(other_input)
        issued = other_fakes.clock.now()
        other_fakes.ssm.values[dr.REHEARSAL_RELEASE_PARAMETER] = dt.RehearsalRelease(
            identity=launch.identity,
            task_arn=TASK_ARN,
            task_definition_arn=REHEARSAL_REVISION_ARN,
            image_digest=launch.image_digest,
            input_digest=sha256_hex(canonical_bytes(other_input)),
            issued_at=issued,
            expires_at=issued + timedelta(minutes=5),
        ).render()
        foreign = other_fakes.run().receipt
        assert foreign.outcome is dt.RehearsalTaskOutcome.REHEARSED
        lines.write_text(foreign.line() + "\n", encoding="utf-8")
        code, out = _run(
            t, "--complete-rehearsal", "R8-GET", *t.base(), "--receipt-lines", str(lines)
        )
        assert code == tool.EXIT_REFUSED_COMPLETION and "RECEIPT_REFUSED" in out
        clients.logs_fake.answers = _logs_pages(foreign.line())
        collect = (
            "--collect-rehearsal-receipt",
            "R8-GET",
            *t.base(),
            "--rehearsal-inputs",
            str(inputs),
            tool.COLLECT_FLAG,
        )
        code, out = _run(
            t,
            *collect,
            launch_clients=clients,
            monotonic=clients.launch.clock.monotonic,
            sleep=clients.launch.clock.sleep,
            now=clients.launch.clock.now,
        )
        assert code == tool.EXIT_COLLECTION_NOT_COLLECTED and "collection=RECEIPT_REJECTED" in out
        assert len(t.files("receipt-collection")) == 1 and t.files("rehearsal-record") == []
        line = _task_receipt(t, launch, FakePermissionClient(DENIED))
        clients.logs_fake.answers = _logs_pages(line)
        code, out = _run(
            t,
            *collect,
            launch_clients=clients,
            monotonic=clients.launch.clock.monotonic,
            sleep=clients.launch.clock.sleep,
            now=clients.launch.clock.now,
        )
        assert code == tool.EXIT_EXECUTED and "status=PASSED" in out
        assert len(t.files("receipt-collection")) == 2 and len(t.files("rehearsal-record")) == 1
