"""The bounded receipt collector (proposed ADR-0049 s.2): the destination derived from the
bound launch and the registered evidence, the bounded read with every documented answer,
the SDK client's serialized request and effective retry count at an intercepted transport,
and the two tools completing from a collected line through exactly the hand-read path.
Every page here is a fake's; nothing reaches AWS."""

# ruff: noqa: S105, S106 -- pagination tokens are not credentials

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import pytest
from test_production_permission_cells import (
    OK,
    _CountingTransport,
    _synthetic_session,
    runner,
    tool,
)
from test_production_permission_probe import (
    HELD_BLOCK,
    LISTED_PROBE,
    STOPPED,
    _Crash,
    _crash_store,
    _ProbeTool,
)

from fixtures.production_launch import log_destination_document
from fixtures.production_runtime import TASK_ID, FakeClock
from kalpamani.data.production.sharadar import launch_records as lr
from kalpamani.data.production.sharadar import permission_cells as pc
from kalpamani.data.production.sharadar import receipt_collector as rc
from kalpamani.data.production.sharadar.entry import TaskEntry, TaskOutcome
from kalpamani.data.production.sharadar.receipts import RECEIPT_LINE_PREFIX
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for

ACQ: Final = ProductionActor.ACQUISITION
GROUP: Final = "/kalpamani/synthetic/research"
DESTINATION: Final = rc.LogDestination(
    log_group=GROUP, stream_prefix="production-acquire-probe", container="acquire-probe"
)
RECEIPT: Final = RECEIPT_LINE_PREFIX + '{"synthetic": "receipt"}'
OTHER_RECEIPT: Final = RECEIPT_LINE_PREFIX + '{"synthetic": "another"}'


def _page(*events: str, token: str | None = None, status: int = 200, **rest: Any) -> rc.LogPage:
    return rc.LogPage(status=status, events=tuple(events), next_forward_token=token, **rest)


@dataclass
class _Pages:
    """A protocol-level fake: one queued page per request, the last repeating."""

    answers: list[rc.LogPage] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def get_log_events(
        self, *, log_group_name: str, log_stream_name: str, next_token: str | None
    ) -> rc.LogPage:
        self.calls.append({"group": log_group_name, "stream": log_stream_name, "token": next_token})
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def _collect(pages: _Pages, clock: FakeClock | None = None) -> rc.CollectedReceipt:
    clock = clock or FakeClock()
    return rc.collect_receipt(
        destination=DESTINATION,
        task_id=TASK_ID,
        client=pages,
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


# ---------------------------------------------------------------------------
# The destination: derived, never supplied
# ---------------------------------------------------------------------------


class TestDestination:
    def test_the_stream_is_derived_from_the_registered_evidence_and_the_task_id(self) -> None:
        assert (
            rc.log_stream_name(DESTINATION, TASK_ID)
            == f"production-acquire-probe/acquire-probe/{TASK_ID}"
        )
        registered = rc.parse_log_destination(
            log_destination_document("kalpamani-production-acquire-probe")
        )
        assert rc.destination_for(TaskEntry.ACQUISITION_PROBE, registered) == registered
        for entry in TaskEntry:
            assert rc.STREAM_PREFIX_OF_ENTRY[entry] == "production-" + rc.CONTAINER_OF_ENTRY[entry]
        with pytest.raises(rc.CollectorError) as unregistered:
            rc.destination_for(TaskEntry.ACQUISITION_PROBE, None)
        assert unregistered.value.defect is rc.CollectorDefect.DESTINATION_UNREGISTERED
        # Another entry's destination is never this entry's stream.
        with pytest.raises(rc.CollectorError) as other:
            rc.destination_for(TaskEntry.BUILD_PROBE, registered)
        assert other.value.defect is rc.CollectorDefect.DESTINATION_NOT_THE_ENTRY_S
        with pytest.raises(rc.CollectorError):
            rc.log_stream_name(DESTINATION, "not-a-task-id")

    def test_a_malformed_destination_is_refused_at_the_registration(self) -> None:
        for bad in (
            {
                "log_group": "/other/group",
                "stream_prefix": "production-acquire",
                "container": "acquire",
            },
            {"log_group": GROUP, "stream_prefix": "production-build", "container": "acquire"},
            {"log_group": GROUP, "stream_prefix": "production-acquire", "container": "shell"},
            {"log_group": GROUP, "stream_prefix": "production-acquire"},
            {
                "log_group": GROUP,
                "stream_prefix": "production-acquire",
                "container": "acquire",
                "x": 1,
            },
        ):
            with pytest.raises(rc.CollectorError):
                rc.parse_log_destination(bad)
        # The task-definition evidence carries it as its one optional block, or not at all.
        from fixtures.production_launch import launch_inputs_document, task_definition_document

        document = launch_inputs_document(probe=True)
        evidence = document["actors"]["acquisition"]["permission_probe"]["task_definition"]
        evidence["log_destination"] = log_destination_document("kalpamani-production-acquire-probe")
        inputs = lr.parse_launch_inputs(json.dumps(document).encode())
        target = inputs.targets[(ACQ, lr.LaunchKind.PERMISSION_PROBE)]
        assert target.task_definition.log_destination == DESTINATION
        assert lr.parse_launch_inputs(json.dumps(launch_inputs_document()).encode())
        assert task_definition_document(ACQ, log_destination=True)["log_destination"][
            "container"
        ] == ("acquire")
        evidence["log_destination"] = {"log_group": "/x", "stream_prefix": "p", "container": "c"}
        with pytest.raises(lr.LaunchRecordError):
            lr.parse_launch_inputs(json.dumps(document).encode())


# ---------------------------------------------------------------------------
# The bounded read
# ---------------------------------------------------------------------------


class TestCollection:
    def test_pagination_ends_on_the_repeated_token_and_the_line_is_collected(self) -> None:
        pages = _Pages([_page("a", token="t1"), _page("b", RECEIPT, token="t2"), _page(token="t2")])
        collected = _collect(pages)
        assert collected.outcome is rc.CollectionOutcome.COLLECTED
        assert collected.receipt_line == RECEIPT and collected.requests == 3
        assert collected.pages == 3 and collected.events_scanned == 3
        assert [c["token"] for c in pages.calls] == [None, "t1", "t2"]
        assert all(
            c["stream"] == f"production-acquire-probe/acquire-probe/{TASK_ID}" for c in pages.calls
        )
        assert all(c["group"] == GROUP for c in pages.calls)
        assert "synthetic" not in repr(collected)

    def test_delayed_delivery_is_polled_from_the_last_token_within_the_ceiling(self) -> None:
        clock = FakeClock()
        pages = _Pages(
            [_page(token="t0"), _page(token="t0"), _page(RECEIPT, token="t1"), _page(token="t1")]
        )
        collected = _collect(pages, clock)
        assert collected.outcome is rc.CollectionOutcome.COLLECTED and collected.requests == 4
        assert clock.sleeps == [rc.COLLECT_POLL_SECONDS]
        assert [c["token"] for c in pages.calls] == [None, "t0", "t0", "t1"]

    def test_an_exhausted_budget_proves_only_that_nothing_was_obtained_within_it(self) -> None:
        clock = FakeClock()
        pages = _Pages([_page("noise", token="t0"), _page(token="t0")])
        collected = _collect(pages, clock)
        assert collected.outcome is rc.CollectionOutcome.NO_RECEIPT_WITHIN_BUDGET
        assert collected.receipt_line is None and collected.requests <= rc.COLLECT_MAX_REQUESTS
        assert clock.monotonic() <= rc.COLLECT_CEILING_SECONDS
        assert sum(clock.sleeps) + rc.COLLECT_POLL_SECONDS > rc.COLLECT_CEILING_SECONDS
        # Requests are bounded even when every page carries a fresh token.
        counter = {"n": 0}

        class Endless:
            def get_log_events(self, **kwargs: Any) -> rc.LogPage:
                counter["n"] += 1
                return _page("x", token=f"t{counter['n']}")

        collected = _collect(Endless())  # type: ignore[arg-type]
        assert collected.outcome is rc.CollectionOutcome.NO_RECEIPT_WITHIN_BUDGET
        assert collected.requests == rc.COLLECT_MAX_REQUESTS

    def test_a_stream_not_yet_created_is_waited_for_and_then_reported(self) -> None:
        pages = _Pages([_page(status=404, code="ResourceNotFoundException")])
        collected = _collect(pages)
        assert collected.outcome is rc.CollectionOutcome.STREAM_NOT_FOUND_WITHIN_BUDGET
        assert collected.pages == 0 and collected.requests > 1
        pages = _Pages(
            [
                _page(status=404, code="ResourceNotFoundException"),
                _page(RECEIPT, token="t"),
                _page(token="t"),
            ]
        )
        assert _collect(pages).outcome is rc.CollectionOutcome.COLLECTED

    def test_denial_throttling_and_failure_end_the_collection_after_one_request(self) -> None:
        for page, outcome in (
            (_page(status=403, code="AccessDeniedException"), rc.CollectionOutcome.DENIED),
            (_page(status=400, code="ThrottlingException"), rc.CollectionOutcome.THROTTLED),
            (rc.LogPage(status=None, transport_failure="timeout"), rc.CollectionOutcome.FAILED),
            (_page(status=500, code="ServiceUnavailableException"), rc.CollectionOutcome.FAILED),
        ):
            collected = _collect(_Pages([page]))
            assert collected.outcome is outcome and collected.requests == 1, outcome
            assert collected.receipt_line is None

    def test_duplicate_lines_are_one_and_distinct_lines_are_contradictory(self) -> None:
        pages = _Pages([_page(RECEIPT, RECEIPT, token="t"), _page(RECEIPT, token="t")])
        collected = _collect(pages)
        assert (
            collected.outcome is rc.CollectionOutcome.COLLECTED
            and collected.distinct_receipt_lines == 1
        )
        pages = _Pages(
            [_page(RECEIPT, token="t"), _page(OTHER_RECEIPT, token="t2"), _page(token="t2")]
        )
        collected = _collect(pages)
        assert collected.outcome is rc.CollectionOutcome.CONTRADICTORY_RECEIPTS
        assert collected.receipt_line is None and collected.distinct_receipt_lines == 2

    def test_the_collection_record_carries_the_line_and_no_other_event(self) -> None:
        pages = _Pages([_page("secret-looking noise", RECEIPT, token="t"), _page(token="t")])
        collected = _collect(pages)
        document = collected.document(
            identity="probe-20260912T140000Z-abcd", launch_record_sha256="ab" * 32
        )
        assert document["contract_id"] == rc.COLLECTION_CONTRACT_ID
        assert "noise" not in json.dumps(document) and document["receipt_line"] == RECEIPT
        assert document["events_scanned"] == 2 and document["log_stream"].endswith(TASK_ID)
        with pytest.raises(ValueError):
            rc.CollectedReceipt(
                outcome=rc.CollectionOutcome.COLLECTED,
                log_group=GROUP,
                log_stream="s",
                requests=1,
                pages=1,
                events_scanned=1,
                distinct_receipt_lines=1,
                receipt_line=None,
                started_at=collected.started_at,
                finished_at=collected.finished_at,
            )


# ---------------------------------------------------------------------------
# The SDK client at an intercepted transport
# ---------------------------------------------------------------------------


class TestSdkLogsClient:
    def _client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[rc.SdkLogsClient, _CountingTransport]:
        import boto3  # type: ignore[import-untyped]
        import production_launch as launch

        original = boto3.Session

        def synthetic(*args: Any, **kwargs: Any) -> Any:
            # The tool pins a profile; the test replaces the session with synthetic
            # credentials (the replacement itself builds a plain session).
            if "profile_name" in kwargs:
                return _synthetic_session(kwargs["profile_name"], kwargs["region_name"])
            return original(*args, **kwargs)

        monkeypatch.setattr(boto3, "Session", synthetic)
        clients = launch._Boto3Clients()
        transport = _CountingTransport()
        built = clients.logs(constants_for(ACQ).launcher_profile)
        built._endpoint.http_session = transport
        assert built.meta.config.retries == {"total_max_attempts": 1, "mode": "standard"}
        return rc.SdkLogsClient(lambda _service: built), transport

    def test_the_serialized_request_and_the_effective_retry_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, transport = self._client(monkeypatch)
        transport.script = [
            (
                200,
                json.dumps(
                    {"events": [{"message": "x"}, {"message": RECEIPT}], "nextForwardToken": "f/1"}
                ).encode(),
            )
        ]
        page = client.get_log_events(
            log_group_name=GROUP, log_stream_name="p/c/" + TASK_ID, next_token=None
        )
        assert (
            page.status == 200
            and page.events == ("x", RECEIPT)
            and page.next_forward_token == "f/1"
        )
        request = transport.requests[-1]
        assert request.headers["X-Amz-Target"] == b"Logs_20140328.GetLogEvents"
        body = json.loads(request.body)
        assert body == {
            "logGroupName": GROUP,
            "logStreamName": "p/c/" + TASK_ID,
            "startFromHead": True,
        }
        transport.script = [(200, json.dumps({"events": [], "nextForwardToken": "f/1"}).encode())]
        client.get_log_events(
            log_group_name=GROUP, log_stream_name="p/c/" + TASK_ID, next_token="f/1"
        )
        assert json.loads(transport.requests[-1].body)["nextToken"] == "f/1"
        # A throttle, a 5xx and a denial are each exactly one transport attempt: the SDK
        # retried nothing (total_max_attempts 1), and the page says which.
        for status, code in (
            (400, "ThrottlingException"),
            (503, "ServiceUnavailableException"),
            (400, "AccessDeniedException"),
        ):
            before = transport.sends
            transport.script = [
                (status, json.dumps({"__type": code, "message": "synthetic"}).encode())
            ]
            page = client.get_log_events(log_group_name=GROUP, log_stream_name="s", next_token=None)
            assert transport.sends == before + 1 and page.code == code, code
        transport.script = [ConnectionError("synthetic")]
        page = client.get_log_events(log_group_name=GROUP, log_stream_name="s", next_token=None)
        assert page.status is None and page.code is not None
        for key in ("AKIA", "SYNTHETIC00000000000"):
            assert key not in repr(client)


# ---------------------------------------------------------------------------
# The permission tool: a probe launch completed from its collected receipt
# ---------------------------------------------------------------------------


def _register_destination(t: _ProbeTool) -> None:
    document = json.loads(t.scenario.inputs.read_bytes())
    for name, actor in (("acquisition", ACQ), ("build", ProductionActor.BUILD)):
        family = constants_for(actor).probe_task_family
        document["actors"][name]["permission_probe"]["task_definition"]["log_destination"] = (
            log_destination_document(family)
        )
    t.scenario.inputs.write_bytes(json.dumps(document).encode())


def _receipt_line_of(path: Path) -> str:
    return next(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(RECEIPT_LINE_PREFIX)
    )


def _stream_answer(t: _ProbeTool, *lines: str) -> Any:
    expected = f"production-acquire-probe/acquire-probe/{TASK_ID}"

    def answer(kwargs: dict[str, Any]) -> dict[str, Any]:
        assert kwargs["logGroupName"] == GROUP and kwargs["logStreamName"] == expected
        assert kwargs["startFromHead"] is True
        return {"events": [{"message": m} for m in lines], "nextForwardToken": "f/end"}

    return answer


def test_a_probe_subcell_completes_from_its_collected_receipt_through_the_hand_read_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    t = _ProbeTool(tmp_path)
    _register_destination(t)
    subcell = "R4-SECRET-GET-TASK"
    authorization = t.authorize(subcell, t.prepare(subcell))
    assert t.main(*t.execute_argv(subcell, authorization)) == tool.EXIT_PROBE_LAUNCHED
    capsys.readouterr()
    line = _receipt_line_of(t.receipt_lines(TaskOutcome.PROBE_MATCHED))
    logs = t.launch_clients.logs_fake
    logs.answers = [_stream_answer(t, "bootstrap line", line)]
    argv = ["--collect-receipt", subcell, *t.base(), tool.COLLECT_FLAG]
    assert t.main(*argv) == tool.EXIT_COMPLETED
    out = capsys.readouterr().out
    assert "collection=COLLECTED requests=2" in out and tool.SENTENCES["completed"] in out
    assert "bootstrap line" not in out
    # The logs client was built for the launcher profile only, after its identity proof.
    assert ("logs", constants_for(ACQ).launcher_profile) in t.launch_clients.constructions
    assert [c[0] for c in t.launch_clients.constructions if c[0] == "logs"] == ["logs"]
    # The same evidence the hand-read completion writes: the record, the receipt
    # evidence, the completed row -- plus the collection record, which keeps the line and
    # no other event.
    assert len(t.files("permission-record")) == 1 and len(t.files("probe-receipt")) == 1
    collections = t.files("receipt-collection")
    assert len(collections) == 1
    document = json.loads(collections[0].read_bytes())
    assert document["receipt_line"] == line and "bootstrap line" not in json.dumps(document)
    row = t.scenario.store().read_ledger()[0].rows[-1]
    assert row.evidence is lr.LedgerEvidence.RECEIPT_VERIFIED
    assert t.status(subcell) is pc.SubcellStatus.CLEANUP_UNRESOLVED
    control = t.control(tmp_path)
    control.client.by_operation = {"list_tasks": [LISTED_PROBE], "describe_tasks": [STOPPED]}
    assert t.cleanup(control, []) == tool.EXIT_EXECUTED
    assert t.status(subcell) is pc.SubcellStatus.PASSED
    # Repeated: the recorded collection is reused, the stream is not read again, and the
    # completion says it is whole.
    logs.answers = [AssertionError("the stream must not be read again")]
    assert t.main(*argv) == tool.EXIT_COMPLETION_RECORDED
    capsys.readouterr()
    assert len(t.files("receipt-collection")) == 1
    # The flag and the mode belong together; the hand-read file is not a collection.
    assert t.main("--collect-receipt", subcell, *t.base()) == tool.EXIT_REFUSED_ARGUMENTS
    assert t.main(*t.base(), tool.COLLECT_FLAG) == tool.EXIT_REFUSED_ARGUMENTS
    assert t.main(*argv, "--receipt-lines", "x") == tool.EXIT_REFUSED_ARGUMENTS
    assert t.main(*argv, modules={"pytest": object()}) == tool.EXIT_REFUSED_EXECUTION_CONTEXT


def _launched(base: Path, subcell: str) -> _ProbeTool:
    """A probe launched for ``subcell`` with the destination registered, awaiting its receipt."""
    t = _ProbeTool(base)
    _register_destination(t)
    authorization = t.authorize(subcell, t.prepare(subcell))
    assert t.main(*t.execute_argv(subcell, authorization)) == tool.EXIT_PROBE_LAUNCHED
    return t


def test_a_collected_line_is_verified_like_a_hand_read_one_and_never_weaker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subcell = "R4-PUT-PAYLOAD-TASK"
    # A collected receipt of another statement or attempt, a malformed line, and an exit
    # the launcher never observed: each read successfully, each refused by the verifier
    # exactly as a hand-read one, the collection recorded, nothing completed. (A recorded
    # COLLECTED line is what the stream holds and is reused, so each case is its own
    # launch.)
    cases: list[tuple[str, Any]] = [
        ("statement", {"statement_sha256": "77" * 32}),
        ("attempt", {"attempt_sha256": "88" * 32}),
        ("malformed", None),
        (
            "exit",
            {
                "task_outcome": TaskOutcome.PROBE_UNDECIDED,
                "observed": pc.ObservedClass.AMBIGUOUS,
                "outcome": pc.SubcellOutcome.UNDECIDED,
            },
        ),
    ]
    for name, block in cases:
        t = _launched(tmp_path / name, subcell)
        capsys.readouterr()
        if block is None:
            wrong = RECEIPT_LINE_PREFIX + "{not json"
        else:
            block = dict(block)
            task_outcome = block.pop("task_outcome", TaskOutcome.PROBE_MATCHED)
            wrong = _receipt_line_of(t.receipt_lines(task_outcome, created=True, **block))
        t.launch_clients.logs_fake.answers = [_stream_answer(t, wrong)]
        argv = ["--collect-receipt", subcell, *t.base(), tool.COLLECT_FLAG]
        assert t.main(*argv) == tool.EXIT_REFUSED_COMPLETION, name
        capsys.readouterr()
        assert t.files("permission-record") == [] and t.files("probe-receipt") == []
        recorded = [json.loads(p.read_bytes())["outcome"] for p in t.files("receipt-collection")]
        assert recorded == ["COLLECTED"]
        assert t.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
    # Nothing within the budget, a denial, a throttle, a stream not yet created: recorded,
    # nothing completed, the subcell stays AWAITING_RECEIPT, and nothing is established
    # about whether a receipt exists; the next collection reads the stream again.
    t = _launched(tmp_path / "budget", subcell)
    capsys.readouterr()
    logs = t.launch_clients.logs_fake
    argv = ["--collect-receipt", subcell, *t.base(), tool.COLLECT_FLAG]
    for answer, outcome in (
        ({"events": [], "nextForwardToken": "f/0"}, "NO_RECEIPT_WITHIN_BUDGET"),
        (_client_error("AccessDeniedException"), "DENIED"),
        (_client_error("ThrottlingException"), "THROTTLED"),
        (_client_error("ResourceNotFoundException"), "STREAM_NOT_FOUND_WITHIN_BUDGET"),
    ):
        logs.answers = [answer]
        before = len(logs.calls)
        assert t.main(*argv) == tool.EXIT_COLLECTION_NOT_COLLECTED, outcome
        out = capsys.readouterr().out
        assert f"collection={outcome}" in out and tool.SENTENCES["collection_not_collected"] in out
        if outcome in ("DENIED", "THROTTLED"):
            assert len(logs.calls) == before + 1  # one request, no retry
        assert t.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
    recorded = [json.loads(p.read_bytes())["outcome"] for p in t.files("receipt-collection")]
    assert sorted(recorded) == sorted(
        ["NO_RECEIPT_WITHIN_BUDGET", "DENIED", "THROTTLED", "STREAM_NOT_FOUND_WITHIN_BUDGET"]
    )
    # The good line completes; the created object is the attempt's exact key.
    good = _receipt_line_of(t.receipt_lines(TaskOutcome.PROBE_MATCHED, created=True))
    logs.answers = [_stream_answer(t, good)]
    assert t.main(*argv) == tool.EXIT_COMPLETED
    capsys.readouterr()
    record = pc.parse_permission_record(t.files("permission-record")[0].read_bytes())
    attempt = pc.parse_permission_attempt(t.files("permission-attempt")[0].read_bytes())
    assert record.created_key == attempt.key
    # A registration without a destination for the probe entry refuses before any read.
    t2 = _ProbeTool(tmp_path / "unregistered")
    authorization = t2.authorize(subcell, t2.prepare(subcell))
    assert t2.main(*t2.execute_argv(subcell, authorization)) == tool.EXIT_PROBE_LAUNCHED
    capsys.readouterr()
    t2.launch_clients.logs_fake.answers = [
        AssertionError("no read without a registered destination")
    ]
    assert (
        t2.main("--collect-receipt", subcell, *t2.base(), tool.COLLECT_FLAG)
        == tool.EXIT_REFUSED_DESTINATION
    )
    assert ("logs", constants_for(ACQ).launcher_profile) not in t2.launch_clients.constructions


def _client_error(code: str) -> Any:
    class SyntheticClientError(Exception):
        response: dict[str, Any] = {  # noqa: RUF012 - a per-call class
            "Error": {"Code": code, "Message": "synthetic"},
            "ResponseMetadata": {"HTTPStatusCode": 400},
        }

    return SyntheticClientError(code)


def test_collection_is_repeatable_after_partial_writes_and_preserves_failed_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    t = _ProbeTool(tmp_path)
    _register_destination(t)
    subcell = "R4-SECRET-GET-TASK"
    authorization = t.authorize(subcell, t.prepare(subcell))
    assert t.main(*t.execute_argv(subcell, authorization)) == tool.EXIT_PROBE_LAUNCHED
    capsys.readouterr()
    line = _receipt_line_of(t.receipt_lines(TaskOutcome.PROBE_MATCHED))
    logs = t.launch_clients.logs_fake
    logs.answers = [_stream_answer(t, line)]
    argv = ["--collect-receipt", subcell, *t.base(), tool.COLLECT_FLAG]
    # Interrupted after the collection record, before the permission record.
    _crash_store(
        monkeypatch, "write_record", when=lambda prefix, *_a, **_k: prefix == "permission-record"
    )
    with pytest.raises(_Crash):
        t.main(*argv)
    monkeypatch.undo()
    capsys.readouterr()
    assert len(t.files("receipt-collection")) == 1 and t.files("permission-record") == []
    assert t.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
    # The repeat reuses the recorded collection (no read), and completes.
    reads = len(logs.calls)
    assert t.main(*argv) == tool.EXIT_COMPLETED
    capsys.readouterr()
    assert len(logs.calls) == reads and len(t.files("receipt-collection")) == 1
    assert len(t.files("permission-record")) == 1 and len(t.files("probe-receipt")) == 1
    # An INVERTED held subcell keeps its FAILED reading; the collection completes its
    # evidence and changes nothing about the verdict.
    t2 = _ProbeTool(tmp_path / "held")
    _register_destination(t2)
    held = "R6-ACQ-EXECUTE-COMMAND"
    t2.ecs.descriptions = t2.descriptions(44)
    authorization = t2.authorize(held, t2.prepare(held))
    t2.client.by_operation = {"execute_command": [OK], "stop_task": [OK]}
    assert t2.main(*t2.execute_argv(held, authorization)) == tool.EXIT_INVERTED
    capsys.readouterr()
    assert t2.status(held) is pc.SubcellStatus.FAILED
    held_line = _receipt_line_of(t2.receipt_lines(TaskOutcome.PROBE_HELD, **HELD_BLOCK))
    t2.launch_clients.logs_fake.answers = [
        lambda kwargs: {"events": [{"message": held_line}], "nextForwardToken": "f"}
    ]
    assert t2.main("--collect-receipt", held, *t2.base(), tool.COLLECT_FLAG) == tool.EXIT_COMPLETED
    assert "outcome=INVERTED" in capsys.readouterr().out
    capsys.readouterr()
    assert t2.status(held) is pc.SubcellStatus.FAILED and len(t2.files("probe-receipt")) == 1


# ---------------------------------------------------------------------------
# The launch tool: a production launch's row completed from its collected receipt
# ---------------------------------------------------------------------------


def test_the_launch_tool_completes_a_row_from_the_collected_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import production_launch as launch
    from test_production_launch_script import TestCompleteRow

    from fixtures.production_build import RUN_1
    from fixtures.production_runtime import encode

    scenario, record, lines = TestCompleteRow()._completed_scenario(tmp_path)
    line = _receipt_line_of(lines)
    inputs = json.loads(scenario.inputs.read_bytes())
    argv = [
        "--complete-row",
        "--launch-record",
        str(record),
        "--collect-receipt",
        launch.COLLECT_FLAG,
    ]
    # Without a registered destination: refused before any read.
    assert scenario.mode(*argv) == launch.EXIT_REFUSED_RECORDS
    assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_destination"]
    assert ("logs", constants_for(ACQ).launcher_profile) not in scenario.clients.constructions
    inputs["actors"]["acquisition"]["production"]["task_definition"]["log_destination"] = (
        log_destination_document("kalpamani-production-acquire")
    )
    scenario.inputs.write_bytes(encode(inputs))
    expected_stream = f"production-acquire/acquire/{TASK_ID}"

    def answer(kwargs: dict[str, Any]) -> dict[str, Any]:
        assert kwargs["logStreamName"] == expected_stream and kwargs["logGroupName"] == GROUP
        return {"events": [{"message": "noise"}, {"message": line}], "nextForwardToken": "f"}

    scenario.clients.logs_fake.answers = [answer]
    assert scenario.mode(*argv) == launch.EXIT_ROW_COMPLETED
    out = capsys.readouterr().out
    assert "collection=COLLECTED" in out and launch.SENTENCES["row_completed"] in out
    row = lr.parse_owner_ledger(scenario.ledger.read_bytes()).row(RUN_1)
    assert row is not None and row.buildable
    # The launcher identity was proven before the logs client existed; the collection
    # record is beside the launch records with the line and no other event.
    kinds = [c[0] for c in scenario.clients.constructions]
    assert kinds.index("sts") < kinds.index("logs")
    collections = sorted(scenario.records.glob("receipt-collection-*.json"))
    assert len(collections) == 1 and "noise" not in collections[0].read_text(encoding="utf-8")
    # Never twice; the mode needs its flag, and refuses a hand-read file beside it.
    assert scenario.mode(*argv) == launch.EXIT_REFUSED_RECORDS
    assert scenario.mode("--complete-row", "--launch-record", str(record), "--collect-receipt") == (
        launch.EXIT_REFUSED_ARGUMENTS
    )
    assert scenario.mode(*argv, "--receipt-lines", str(lines)) == launch.EXIT_REFUSED_ARGUMENTS


def test_the_runner_reads_no_collection_record_as_permission_evidence(tmp_path: Path) -> None:
    """A collection record is launch-side evidence, not a permission record: the runner's
    permission evidence ignores its prefix and counts nothing malformed for it."""
    t = _ProbeTool(tmp_path)
    t.scenario.records.mkdir(parents=True, exist_ok=True)
    (t.scenario.records / "receipt-collection-20260101T000000Z-0000.json").write_text(
        "{}", encoding="utf-8"
    )
    evidence = runner.permission_evidence(t.scenario.store(), t.context())
    assert evidence.malformed == 0
