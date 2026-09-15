"""The bounded receipt collector (proposed ADR-0049 s.2): the destination derived from the
bound launch and the registered evidence, the bounded read with every documented answer
-- a complete scan and only a complete scan establishing one line, every limit held at
the request boundary, the candidate verified before it is kept -- the closed collection
record and the one cache-admission rule, the SDK client's serialized request and effective
retry count at an intercepted transport, and the two tools completing from a collected
line through exactly the hand-read path. Every page here is a fake's; nothing reaches AWS."""

# ruff: noqa: S105, S106 -- pagination tokens are not credentials

from __future__ import annotations

import dataclasses
import functools
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
from kalpamani.data.production.sharadar.receipts import (
    RECEIPT_LINE_PREFIX,
    ReceiptDefect,
    ReceiptExpectation,
)
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for

ACQ: Final = ProductionActor.ACQUISITION
GROUP: Final = "/kalpamani/synthetic/research"
#: The acquisition entry's destination: the collection unit tests verify against a real
#: acquisition launch record, so the stream is the production acquisition container's.
DESTINATION: Final = rc.LogDestination(
    log_group=GROUP, stream_prefix="production-acquire", container="acquire"
)
PROBE_DESTINATION: Final = rc.LogDestination(
    log_group=GROUP, stream_prefix="production-acquire-probe", container="acquire-probe"
)
STREAM: Final = f"production-acquire/acquire/{TASK_ID}"
#: Receipt-shaped lines that are not receipts: prefixed, closed-looking, unverifiable.
RECEIPT: Final = RECEIPT_LINE_PREFIX + '{"synthetic": "receipt"}'
OTHER_RECEIPT: Final = RECEIPT_LINE_PREFIX + '{"synthetic": "another"}'
SENSITIVE: Final = "SYNTHETIC-SENSITIVE-VALUE-0123456789"


@functools.cache
def _verified() -> tuple[str, ReceiptExpectation, ReceiptExpectation]:
    """A genuine receipt line, the expectation it verifies against, and another launch's
    expectation (another input digest) it does not: from the real acquisition harness."""
    from test_production_launch_records import TestCompletion

    receipt, record = TestCompletion()._acquisition_receipt()
    line = next(x for x in receipt.render() if x.startswith(RECEIPT_LINE_PREFIX))
    expectation = record.expectation()
    return line, expectation, dataclasses.replace(expectation, input_digest="cd" * 32)


def _line() -> str:
    return _verified()[0]


def _expectation() -> ReceiptExpectation:
    return _verified()[1]


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


def _collect(
    pages: Any, clock: FakeClock | None = None, *, expectation: ReceiptExpectation | None = None
) -> rc.CollectedReceipt:
    clock = clock or FakeClock()
    return rc.collect_receipt(
        destination=DESTINATION,
        task_id=TASK_ID,
        expectation=expectation or _expectation(),
        client=pages,
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


def _document(collected: rc.CollectedReceipt, **overrides: Any) -> dict[str, Any]:
    document = collected.document(
        identity="run-20260912T140000Z-abcd", launch_record_sha256="ab" * 32
    )
    document.update(overrides)
    return document


def _payload(document: dict[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True).encode()


def _admit(payloads: list[bytes], **overrides: Any) -> rc.CollectionAdmission:
    arguments: dict[str, Any] = {
        "identity": "run-20260912T140000Z-abcd",
        "launch_record_sha256": "ab" * 32,
        "destination": DESTINATION,
        "task_id": TASK_ID,
        "expectation": _expectation(),
    }
    arguments.update(overrides)
    return rc.admit_collection_records(payloads, **arguments)


# ---------------------------------------------------------------------------
# The destination: derived, never supplied
# ---------------------------------------------------------------------------


class TestDestination:
    def test_the_stream_is_derived_from_the_registered_evidence_and_the_task_id(self) -> None:
        assert (
            rc.log_stream_name(PROBE_DESTINATION, TASK_ID)
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
            rc.log_stream_name(PROBE_DESTINATION, "not-a-task-id")

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
        assert target.task_definition.log_destination == PROBE_DESTINATION
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
    def test_pagination_ends_on_the_repeated_token_and_the_window_is_confirmed(self) -> None:
        # Three pages to the end, then one poll interval and one re-read from the end
        # token delivering nothing new: the observation window closes, and the one line
        # verifies and is collected.
        clock = FakeClock()
        pages = _Pages([_page("a", token="t1"), _page("b", _line(), token="t2"), _page(token="t2")])
        collected = _collect(pages, clock)
        assert collected.outcome is rc.CollectionOutcome.COLLECTED and collected.scan_complete
        assert collected.receipt_line == _line() and collected.requests == 4
        assert collected.pages == 4 and collected.events_scanned == 3
        assert [c["token"] for c in pages.calls] == [None, "t1", "t2", "t2"]
        assert clock.sleeps == [rc.COLLECT_POLL_SECONDS]
        assert all(c["stream"] == STREAM and c["group"] == GROUP for c in pages.calls)
        assert collected.elapsed_ms == int(rc.COLLECT_POLL_SECONDS * 1000)
        assert "synthetic" not in repr(collected) and collected.rejection is None

    def test_delayed_delivery_is_polled_from_the_last_token_within_the_ceiling(self) -> None:
        clock = FakeClock()
        pages = _Pages(
            [_page(token="t0"), _page(token="t0"), _page(_line(), token="t1"), _page(token="t1")]
        )
        collected = _collect(pages, clock)
        assert collected.outcome is rc.CollectionOutcome.COLLECTED and collected.requests == 5
        assert clock.sleeps == [rc.COLLECT_POLL_SECONDS, rc.COLLECT_POLL_SECONDS]
        assert [c["token"] for c in pages.calls] == [None, "t0", "t0", "t1", "t1"]
        # A line delivered late, during the confirmation re-read, keeps the scan open: the
        # window closes only after a re-read that delivers nothing new.
        pages = _Pages(
            [
                _page(_line(), token="t1"),
                _page(token="t1"),
                _page("late noise", token="t2"),
                _page(token="t2"),
            ]
        )
        collected = _collect(pages, FakeClock())
        assert collected.outcome is rc.CollectionOutcome.COLLECTED and collected.requests == 5
        assert collected.events_scanned == 2

    def test_an_exhausted_budget_proves_only_that_nothing_was_obtained_within_it(self) -> None:
        clock = FakeClock()
        pages = _Pages([_page("noise", token="t0"), _page(token="t0")])
        collected = _collect(pages, clock)
        assert collected.outcome is rc.CollectionOutcome.NO_RECEIPT_WITHIN_BUDGET
        assert collected.receipt_line is None and collected.requests <= rc.COLLECT_MAX_REQUESTS
        assert not collected.scan_complete
        assert clock.monotonic() <= rc.COLLECT_CEILING_SECONDS
        assert sum(clock.sleeps) + rc.COLLECT_POLL_SECONDS > rc.COLLECT_CEILING_SECONDS
        # Requests are bounded even when every page carries a fresh token, and a pass that
        # ends on its page bound continues without sleeping (more is there to read).
        counter = {"n": 0}

        class Endless:
            def get_log_events(self, **kwargs: Any) -> rc.LogPage:
                counter["n"] += 1
                return _page("x", token=f"t{counter['n']}")

        clock = FakeClock()
        collected = _collect(Endless(), clock)
        assert collected.outcome is rc.CollectionOutcome.NO_RECEIPT_WITHIN_BUDGET
        assert collected.requests == rc.COLLECT_MAX_REQUESTS and clock.sleeps == []

    def test_a_partial_scan_never_establishes_one_line(self) -> None:
        # Finding 1: a valid line on page 1 and a contradictory line beyond the 16-page
        # pass. The pass bound is a chunk, not the end of the stream: the scan continues
        # into the next pass, reaches the contradiction, and refuses.
        pages = _Pages(
            [_page(_line(), token="t1")]
            + [_page("noise", token=f"t{i}") for i in range(2, 17)]
            + [_page(OTHER_RECEIPT, token="t17"), _page(token="t17")]
        )
        collected = _collect(pages)
        assert collected.outcome is rc.CollectionOutcome.CONTRADICTORY_RECEIPTS
        assert collected.requests == 17 and collected.receipt_line is None
        assert len(pages.answers) == 1  # the end was never requested; the contradiction was
        # The same line seen, and the request budget spent before the end was observed:
        # SCAN_INCOMPLETE -- nothing established, no line kept, the scan not complete.
        counter = {"n": 0}

        class Endless:
            def get_log_events(self, **kwargs: Any) -> rc.LogPage:
                counter["n"] += 1
                return _page(_line() if counter["n"] == 1 else "x", token=f"t{counter['n']}")

        collected = _collect(Endless())
        assert collected.outcome is rc.CollectionOutcome.SCAN_INCOMPLETE
        assert collected.requests == rc.COLLECT_MAX_REQUESTS and not collected.scan_complete
        assert collected.receipt_line is None and collected.distinct_receipt_lines == 1
        document = _document(collected)
        assert document["receipt_line"] is None and document["scan_complete"] is False
        # Control: the same line with the end observed inside the budget is collected.
        pages = _Pages(
            [_page(_line(), token="t1")]
            + [_page("x", token=f"t{i}") for i in range(2, 30)]
            + [_page(token="t30"), _page(token="t30")]
        )
        collected = _collect(pages)
        assert collected.outcome is rc.CollectionOutcome.COLLECTED and collected.requests == 32

    def test_the_event_ceiling_cuts_the_page_and_the_scan_is_incomplete(self) -> None:
        # Finding 1: one page crossing the 20,000-event ceiling with a valid line beyond
        # the ceiling and a contradiction on the next page. Scanning stops at the ceiling
        # (the line beyond it is never read), no further request is issued, and nothing
        # is established.
        big = _page(*(["noise"] * 20_000 + [_line()]), token="t1")
        pages = _Pages([big, _page(OTHER_RECEIPT, token="t2"), _page(token="t2")])
        collected = _collect(pages)
        assert collected.outcome is rc.CollectionOutcome.NO_RECEIPT_WITHIN_BUDGET
        assert collected.requests == 1 and collected.events_scanned == rc.COLLECT_MAX_EVENTS
        assert collected.distinct_receipt_lines == 0 and collected.receipt_line is None
        # A line seen before the ceiling is cut is still not established.
        big = _page(*([_line()] + ["noise"] * 20_000), token="t1")
        collected = _collect(_Pages([big, _page(token="t1")]))
        assert collected.outcome is rc.CollectionOutcome.SCAN_INCOMPLETE
        assert collected.requests == 1 and collected.distinct_receipt_lines == 1
        # Control: 19,999 events and the line fit under the ceiling and are collected.
        fits = _page(*(["noise"] * 19_998 + [_line()]), token="t1")
        collected = _collect(_Pages([fits, _page(token="t1")]))
        assert collected.outcome is rc.CollectionOutcome.COLLECTED
        assert collected.events_scanned == 19_999

    def test_slow_requests_stop_at_the_elapsed_ceiling(self) -> None:
        # Finding 1: every request takes 100 s. The ceiling is checked before each request
        # (at 0, 100 and 200 s); the fourth is never issued, whatever the pass bound.
        clock = FakeClock()

        class Slow(_Pages):
            def get_log_events(self, **kwargs: Any) -> rc.LogPage:
                clock.seconds += 100.0
                return super().get_log_events(**kwargs)

        pages = Slow([_page("noise", token=f"t{i}") for i in range(1, 30)])
        collected = _collect(pages, clock)
        assert collected.requests == 3 and clock.seconds == 300.0
        assert collected.outcome is rc.CollectionOutcome.NO_RECEIPT_WITHIN_BUDGET
        assert collected.elapsed_ms == 300_000
        # A request in flight is the one limit the collector cannot cut: a 1,000 s answer
        # is recorded as such, and nothing follows it.
        clock = FakeClock()

        class Stalled(_Pages):
            def get_log_events(self, **kwargs: Any) -> rc.LogPage:
                clock.seconds += 1_000.0
                return super().get_log_events(**kwargs)

        collected = _collect(Stalled([_page(_line(), token="t1"), _page(token="t1")]), clock)
        assert collected.requests == 1 and collected.elapsed_ms == 1_000_000
        assert collected.outcome is rc.CollectionOutcome.SCAN_INCOMPLETE
        # Control: 60 s requests reach the end and confirm the window within the ceiling.
        clock = FakeClock()

        class Fine(_Pages):
            def get_log_events(self, **kwargs: Any) -> rc.LogPage:
                clock.seconds += 60.0
                return super().get_log_events(**kwargs)

        collected = _collect(Fine([_page(_line(), token="t1"), _page(token="t1")]), clock)
        assert collected.outcome is rc.CollectionOutcome.COLLECTED and collected.requests == 3

    def test_a_stream_not_yet_created_is_waited_for_and_then_reported(self) -> None:
        pages = _Pages([_page(status=404, code="ResourceNotFoundException")])
        collected = _collect(pages)
        assert collected.outcome is rc.CollectionOutcome.STREAM_NOT_FOUND_WITHIN_BUDGET
        assert collected.pages == 0 and collected.requests > 1
        pages = _Pages(
            [
                _page(status=404, code="ResourceNotFoundException"),
                _page(_line(), token="t"),
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
            assert collected.receipt_line is None and not collected.scan_complete

    def test_duplicate_lines_are_one_and_distinct_lines_are_contradictory(self) -> None:
        pages = _Pages(
            [_page(_line(), _line(), token="t"), _page(_line(), token="t"), _page(token="t")]
        )
        collected = _collect(pages)
        assert (
            collected.outcome is rc.CollectionOutcome.COLLECTED
            and collected.distinct_receipt_lines == 1
        )
        pages = _Pages(
            [_page(_line(), token="t"), _page(OTHER_RECEIPT, token="t2"), _page(token="t2")]
        )
        collected = _collect(pages)
        assert collected.outcome is rc.CollectionOutcome.CONTRADICTORY_RECEIPTS
        assert collected.receipt_line is None and collected.distinct_receipt_lines == 2

    def test_a_line_is_verified_before_it_is_kept_and_a_rejected_one_leaves_no_text(self) -> None:
        # Finding 2: receipt-prefixed malformed text carrying a synthetic sensitive value,
        # a genuine receipt of another launch, and a closed document with one unexpected
        # field carrying the value -- each read in a complete scan, each refused by the
        # verifier before anything is persisted, each recorded as its closed defect and
        # byte count only.
        malformed = RECEIPT_LINE_PREFIX + "not json " + SENSITIVE
        document = json.loads(_line()[len(RECEIPT_LINE_PREFIX) :])
        document["synthetic_secret"] = SENSITIVE
        extra = RECEIPT_LINE_PREFIX + json.dumps(document)
        for line, defect, expectation in (
            (malformed, ReceiptDefect.DOCUMENT_MALFORMED, None),
            (_line(), ReceiptDefect.BINDING_MISMATCH, _verified()[2]),
            (extra, ReceiptDefect.FIELD_UNKNOWN, None),
            (RECEIPT, ReceiptDefect.FIELD_UNKNOWN, None),
        ):
            collected = _collect(
                _Pages([_page(line, token="t"), _page(token="t")]), expectation=expectation
            )
            assert collected.outcome is rc.CollectionOutcome.RECEIPT_REJECTED, defect
            assert collected.rejection is defect and collected.scan_complete
            assert collected.receipt_line is None
            assert collected.rejected_receipt_bytes == len(line.encode())
            rendered = json.dumps(_document(collected))
            assert SENSITIVE not in rendered and "synthetic_secret" not in rendered
            assert "input_digest" not in rendered
        # Control: the genuine line of this launch is kept, once, exactly as delivered.
        collected = _collect(_Pages([_page(_line(), token="t"), _page(token="t")]))
        assert collected.outcome is rc.CollectionOutcome.COLLECTED
        assert collected.receipt_line == _line() and collected.rejection is None
        with pytest.raises(TypeError):
            rc.collect_receipt(
                destination=DESTINATION,
                task_id=TASK_ID,
                expectation=None,  # type: ignore[arg-type]
                client=_Pages([_page(token="t")]),
                now=FakeClock().now,
                monotonic=FakeClock().monotonic,
                sleep=lambda _s: None,
            )

    def test_the_collection_record_carries_the_line_and_no_other_event(self) -> None:
        pages = _Pages([_page("secret-looking noise", _line(), token="t"), _page(token="t")])
        collected = _collect(pages)
        document = _document(collected)
        assert document["contract_id"] == rc.COLLECTION_CONTRACT_ID
        assert "noise" not in json.dumps(document) and document["receipt_line"] == _line()
        assert document["events_scanned"] == 2 and document["log_stream"] == STREAM
        assert document["scan_complete"] is True and document["rejection"] is None
        assert document["started_at"] < document["finished_at"]
        for outcome, line, rejection, scan_complete in (
            (rc.CollectionOutcome.COLLECTED, None, None, True),
            (rc.CollectionOutcome.COLLECTED, _line(), None, False),
            (rc.CollectionOutcome.RECEIPT_REJECTED, None, None, True),
            (rc.CollectionOutcome.SCAN_INCOMPLETE, None, None, True),
            (rc.CollectionOutcome.NO_RECEIPT_WITHIN_BUDGET, None, ReceiptDefect.NO_RECEIPT, False),
        ):
            with pytest.raises(ValueError):
                rc.CollectedReceipt(
                    outcome=outcome,
                    log_group=GROUP,
                    log_stream=STREAM,
                    requests=1,
                    pages=1,
                    events_scanned=1,
                    distinct_receipt_lines=1,
                    scan_complete=scan_complete,
                    receipt_line=line,
                    rejection=rejection,
                    rejected_receipt_bytes=None if rejection is None else 1,
                    started_at=collected.started_at,
                    finished_at=collected.finished_at,
                    elapsed_ms=0,
                )


# ---------------------------------------------------------------------------
# The collection record: one closed parser, one cache-admission rule
# ---------------------------------------------------------------------------


class TestCollectionRecords:
    def _collected(self) -> rc.CollectedReceipt:
        return _collect(_Pages([_page(_line(), token="t"), _page(token="t")]))

    def _rejected(self) -> rc.CollectedReceipt:
        return _collect(_Pages([_page(RECEIPT, token="t"), _page(token="t")]))

    def test_the_parser_reads_exactly_the_contract_and_refuses_everything_else(self) -> None:
        collected = self._collected()
        record = rc.parse_collection_record(_payload(_document(collected)))
        assert record.outcome is rc.CollectionOutcome.COLLECTED
        assert record.receipt_line == _line() and record.scan_complete
        assert record.log_stream == STREAM and record.launch_record_sha256 == "ab" * 32
        rejected = rc.parse_collection_record(_document(self._rejected()))
        assert rejected.rejection is ReceiptDefect.FIELD_UNKNOWN
        assert rejected.rejected_receipt_bytes == len(RECEIPT.encode())
        assert "synthetic" not in repr(record) + repr(rejected)
        bad: list[dict[str, Any]] = [
            _document(collected, extra="x"),
            {k: v for k, v in _document(collected).items() if k != "elapsed_ms"},
            _document(collected, contract_id="kalpamani-receipt-collection/v0"),
            _document(collected, identity=""),
            _document(collected, launch_record_sha256="zz" * 32),
            _document(collected, log_group="/other/group"),
            _document(collected, log_stream="production-acquire/acquire/not-a-task"),
            _document(collected, outcome="VERIFIED"),
            _document(collected, scan_complete="true"),
            _document(collected, scan_complete=False),
            _document(collected, receipt_line=None),
            _document(collected, receipt_line="not a receipt line"),
            _document(collected, receipt_line=RECEIPT_LINE_PREFIX + "{broken"),
            _document(collected, rejection="DOCUMENT_MALFORMED"),
            _document(collected, requests=-1),
            _document(collected, requests=1.0),
            _document(collected, started_at="2026-09-15T00:00:00"),
            _document(collected, started_at="soon"),
            _document(self._rejected(), rejection=None),
            _document(self._rejected(), rejection="SOMETHING_ELSE"),
            _document(self._rejected(), rejected_receipt_bytes=None),
            _document(self._rejected(), receipt_line=RECEIPT),
        ]
        for document in bad:
            with pytest.raises(rc.CollectionRecordError) as refusal:
                rc.parse_collection_record(document)
            assert refusal.value.defect is rc.CollectionRecordDefect.RECORD_MALFORMED
        with pytest.raises(rc.CollectionRecordError):
            rc.parse_collection_record(b"{not json")
        with pytest.raises(rc.CollectionRecordError):
            rc.parse_collection_record(b"x" * (rc.MAX_COLLECTION_RECORD_BYTES + 1))
        assert rc.is_collection_record(_document(collected)) and not rc.is_collection_record({})

    def test_the_admission_rule_reads_every_record_and_chooses_nothing_by_order(self) -> None:
        collected = _document(self._collected())
        # Two distinct lines that both verify: the same receipt document serialized with
        # another key order is a different line, and a contradiction, not a duplicate.
        document = json.loads(_line()[len(RECEIPT_LINE_PREFIX) :])
        reordered = RECEIPT_LINE_PREFIX + json.dumps(dict(reversed(list(document.items()))))
        assert reordered != _line()
        other = dict(collected, receipt_line=reordered)
        # Finding 3: two COLLECTED records with different lines refuse in either order.
        for payloads in (
            [_payload(collected), _payload(other)],
            [_payload(other), _payload(collected)],
        ):
            with pytest.raises(rc.CollectionRecordError) as refusal:
                _admit(payloads)
            assert refusal.value.defect is rc.CollectionRecordDefect.CONTRADICTORY_RECORDS
        # Finding 3: a COLLECTED record whose line does not verify against this launch
        # refuses -- it cannot be reused, and it is not silently skipped.
        with pytest.raises(rc.CollectionRecordError) as refusal:
            _admit([_payload(collected)], expectation=_verified()[2])
        assert refusal.value.defect is rc.CollectionRecordDefect.RECEIPT_UNVERIFIABLE
        # A record about this identity bound to another launch record or another stream.
        with pytest.raises(rc.CollectionRecordError) as refusal:
            _admit([_payload(dict(collected, launch_record_sha256="cd" * 32))])
        assert refusal.value.defect is rc.CollectionRecordDefect.LAUNCH_MISMATCH
        for change in (
            {"log_group": "/kalpamani/other/research"},
            {"log_stream": f"production-acquire/acquire/{'f' * 32}"},
        ):
            with pytest.raises(rc.CollectionRecordError) as refusal:
                _admit([_payload(dict(collected, **change))])
            assert refusal.value.defect is rc.CollectionRecordDefect.DESTINATION_MISMATCH
        # A malformed record about this identity refuses; not-a-record and another
        # identity's record are ignored.
        with pytest.raises(rc.CollectionRecordError) as refusal:
            _admit([_payload(dict(collected, scan_complete=False))])
        assert refusal.value.defect is rc.CollectionRecordDefect.RECORD_MALFORMED
        admission = _admit(
            [b"{not json", b"{}", _payload(dict(collected, identity="run-20260912T140000Z-ffff"))]
        )
        assert admission.reusable_line is None and admission.attempts == 0
        # Control: identical COLLECTED records agree; rejected, exhausted and incomplete
        # attempts are history that never blocks, whatever their filename order.
        rejected = _document(self._rejected())
        incomplete = _document(
            _collect(
                _Pages(
                    [
                        _page(_line(), token="t1"),
                        _page(_line(), token="t2"),
                        _page(status=403, code="AccessDeniedException"),
                    ]
                )
            )
        )
        assert incomplete["outcome"] == "DENIED" and incomplete["receipt_line"] is None
        admission = _admit([_payload(rejected), _payload(incomplete)])
        assert admission.reusable_line is None and admission.attempts == 2
        admission = _admit([_payload(rejected), _payload(collected), _payload(collected)])
        assert admission.reusable_line == _line() and admission.attempts == 3
        assert "synthetic" not in repr(admission)

    def test_a_recorded_contradiction_is_never_superseded_without_a_disposition(self) -> None:
        # Correction 2: a CONTRADICTORY_RECEIPTS record about the launch refuses admission
        # whatever was recorded before or after it, in whatever order -- a later single
        # valid line, or a COLLECTED record placed beside it, supersedes nothing.
        collected = _document(self._collected())
        contradiction = _document(
            _collect(
                _Pages([_page(_line(), token="t"), _page(RECEIPT, token="t2"), _page(token="t2")])
            )
        )
        assert contradiction["outcome"] == "CONTRADICTORY_RECEIPTS"
        assert (
            contradiction["receipt_line"] is None and contradiction["distinct_receipt_lines"] == 2
        )
        for payloads in (
            [_payload(contradiction)],
            [_payload(contradiction), _payload(collected)],
            [_payload(collected), _payload(contradiction)],
            [_payload(collected), _payload(contradiction), _payload(collected)],
        ):
            with pytest.raises(rc.CollectionRecordError) as refusal:
                _admit(payloads)
            assert refusal.value.defect is rc.CollectionRecordDefect.CONTRADICTION_UNRESOLVED
        status = rc.contradiction_status(
            [_payload(collected), _payload(contradiction)],
            identity=collected["identity"],
            launch_record_sha256=collected["launch_record_sha256"],
        )
        digest = rc.collection_record_sha256(contradiction)
        assert status.unresolved == (digest,) and status.disposed == ()
        # The explicit, evidence-bound disposition: names the contradiction record by its
        # digest, the launch, and the hand-read receipt line it was completed from. With it
        # the launch is admitted again and the contradiction record is untouched.
        disposition = rc.CollectionDisposition(
            identity=collected["identity"],
            launch_record_sha256=collected["launch_record_sha256"],
            contradiction_sha256=digest,
            receipt_line_sha256="ab" * 32,
            disposition=rc.ContradictionDisposition.HAND_READ_COMPLETION,
            recorded_at=self._collected().finished_at,
        ).document()
        assert rc.parse_collection_disposition(_payload(disposition)).contradiction_sha256 == digest
        admission = _admit([_payload(contradiction), _payload(disposition), _payload(collected)])
        assert admission.reusable_line == _line() and admission.attempts == 2
        status = rc.contradiction_status(
            [_payload(contradiction), _payload(disposition)],
            identity=collected["identity"],
            launch_record_sha256=collected["launch_record_sha256"],
        )
        assert status.unresolved == () and status.disposed == (digest,)
        # A disposition naming no recorded contradiction, or another launch: refused.
        with pytest.raises(rc.CollectionRecordError) as refusal:
            _admit([_payload(dict(disposition, contradiction_sha256="cd" * 32))])
        assert refusal.value.defect is rc.CollectionRecordDefect.DISPOSITION_UNBOUND
        with pytest.raises(rc.CollectionRecordError) as refusal:
            _admit(
                [
                    _payload(contradiction),
                    _payload(dict(disposition, launch_record_sha256="cd" * 32)),
                ]
            )
        assert refusal.value.defect is rc.CollectionRecordDefect.LAUNCH_MISMATCH
        for bad in (
            dict(disposition, disposition="AUTOMATIC"),
            dict(disposition, receipt_line_sha256="short"),
            {k: v for k, v in disposition.items() if k != "recorded_at"},
            dict(disposition, extra=1),
        ):
            with pytest.raises(rc.CollectionRecordError) as refusal:
                rc.parse_collection_disposition(bad)
            assert refusal.value.defect is rc.CollectionRecordDefect.RECORD_MALFORMED
        # Control: exhausted and rejected attempts stay history that never blocks.
        admission = _admit([_payload(_document(self._rejected())), _payload(collected)])
        assert admission.reusable_line == _line()
        assert not rc.is_collection_disposition(contradiction) and rc.is_collection_disposition(
            disposition
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


def _once(*lines: str, stream: str | None = None) -> Any:
    """A stream as the service delivers it: the lines on the first read from the head,
    the same end token every time, and nothing new on a re-read from that token."""

    def answer(kwargs: dict[str, Any]) -> dict[str, Any]:
        assert kwargs["logGroupName"] == GROUP and kwargs["startFromHead"] is True
        if stream is not None:
            assert kwargs["logStreamName"] == stream
        events = [] if kwargs.get("nextToken") == "f/end" else [{"message": m} for m in lines]
        return {"events": events, "nextForwardToken": "f/end"}

    return answer


def _stream_answer(t: _ProbeTool, *lines: str) -> Any:
    return _once(*lines, stream=f"production-acquire-probe/acquire-probe/{TASK_ID}")


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
    assert "collection=COLLECTED requests=3" in out and tool.SENTENCES["completed"] in out
    assert "scan_complete=true" in out and "bootstrap line" not in out
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
    assert document["scan_complete"] is True and document["rejection"] is None
    assert rc.parse_collection_record(collections[0].read_bytes()).outcome.value == "COLLECTED"
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
    # A collected receipt of another statement or attempt, and a malformed line: each read
    # in a complete scan, each refused by the verifier before anything of it is kept --
    # RECEIPT_REJECTED with the closed defect, no text -- nothing completed, and the next
    # collection reads the stream again (the record never blocks). The verifier is the
    # hand-read path's; a line it refuses is never persisted as a receipt.
    rejected_cases: list[tuple[str, str, str]] = [
        ("malformed", RECEIPT_LINE_PREFIX + "{not json " + SENSITIVE, "DOCUMENT_MALFORMED"),
        ("text", RECEIPT_LINE_PREFIX + '"' + SENSITIVE + '"', "DOCUMENT_MALFORMED"),
    ]
    for name, wrong, defect in rejected_cases:
        t = _launched(tmp_path / name, subcell)
        capsys.readouterr()
        t.launch_clients.logs_fake.answers = [_stream_answer(t, wrong)]
        argv = ["--collect-receipt", subcell, *t.base(), tool.COLLECT_FLAG]
        assert t.main(*argv) == tool.EXIT_COLLECTION_NOT_COLLECTED, name
        out = capsys.readouterr().out
        assert "collection=RECEIPT_REJECTED" in out and SENSITIVE not in out
        assert t.files("permission-record") == [] and t.files("probe-receipt") == []
        records = [
            rc.parse_collection_record(p.read_bytes()) for p in t.files("receipt-collection")
        ]
        assert [r.outcome.value for r in records] == ["RECEIPT_REJECTED"]
        assert records[0].rejection is not None and records[0].rejection.value == defect
        assert records[0].receipt_line is None
        for path in t.scenario.records.iterdir():
            assert SENSITIVE not in path.read_text(encoding="utf-8", errors="replace"), name
            assert "77777777" not in path.read_text(encoding="utf-8", errors="replace"), name
        assert t.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
        # Recovery: the stream now delivers the launch's own line, and the next collection
        # reads it (the rejected record stays beside the new one).
        good = _receipt_line_of(t.receipt_lines(TaskOutcome.PROBE_MATCHED, created=True))
        t.launch_clients.logs_fake.answers = [_stream_answer(t, good)]
        reads = len(t.launch_clients.logs_fake.calls)
        assert t.main(*argv) == tool.EXIT_COMPLETED, name
        capsys.readouterr()
        assert len(t.launch_clients.logs_fake.calls) > reads
        outcomes = sorted(
            json.loads(p.read_bytes())["outcome"] for p in t.files("receipt-collection")
        )
        assert outcomes == ["COLLECTED", "RECEIPT_REJECTED"]
    # A closed receipt document that verifies against the launch record (structure and
    # binding) but names another statement or attempt, or reports an exit the launcher
    # never observed: collected -- it is closed evidence of the contradiction, and holds
    # no arbitrary text -- and the completion refuses it exactly as a hand-read one,
    # repeatably; the recorded line is reused and the stream is not read again.
    contradicting: list[tuple[str, dict[str, Any]]] = [
        ("statement", {"statement_sha256": "77" * 32}),
        ("attempt", {"attempt_sha256": "88" * 32}),
        (
            "exit",
            {
                "task_outcome": TaskOutcome.PROBE_UNDECIDED,
                "observed": pc.ObservedClass.AMBIGUOUS,
                "outcome": pc.SubcellOutcome.UNDECIDED,
            },
        ),
    ]
    for name, block in contradicting:
        t = _launched(tmp_path / name, subcell)
        capsys.readouterr()
        block = dict(block)
        task_outcome = block.pop("task_outcome", TaskOutcome.PROBE_MATCHED)
        wrong = _receipt_line_of(t.receipt_lines(task_outcome, created=True, **block))
        t.launch_clients.logs_fake.answers = [_stream_answer(t, wrong)]
        argv = ["--collect-receipt", subcell, *t.base(), tool.COLLECT_FLAG]
        for _ in range(2):
            assert t.main(*argv) == tool.EXIT_REFUSED_COMPLETION, name
            capsys.readouterr()
            assert t.files("permission-record") == [] and t.files("probe-receipt") == []
            recorded = [
                json.loads(p.read_bytes())["outcome"] for p in t.files("receipt-collection")
            ]
            assert recorded == ["COLLECTED"]
            assert t.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
            t.launch_clients.logs_fake.answers = [AssertionError("the recorded line is reused")]
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
    # The good line completes; the created object is the attempt's exact key; the four
    # earlier attempts stay beside the collection that completed.
    good = _receipt_line_of(t.receipt_lines(TaskOutcome.PROBE_MATCHED, created=True))
    logs.answers = [_stream_answer(t, good)]
    assert t.main(*argv) == tool.EXIT_COMPLETED
    capsys.readouterr()
    assert len(t.files("receipt-collection")) == 5
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
    t2.launch_clients.logs_fake.answers = [_once(held_line)]
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
    # A launch the launcher never observed at its terminal state is not collected (the
    # owner completes it by hand, after the task stopped); then, without a registered
    # destination: refused before any read.
    assert scenario.mode(*argv) == launch.EXIT_REFUSED_RECORDS
    assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_records"]
    _observed(record, 0)
    assert scenario.mode(*argv) == launch.EXIT_REFUSED_RECORDS
    assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_destination"]
    assert ("logs", constants_for(ACQ).launcher_profile) not in scenario.clients.constructions
    inputs["actors"]["acquisition"]["production"]["task_definition"]["log_destination"] = (
        log_destination_document("kalpamani-production-acquire")
    )
    scenario.inputs.write_bytes(encode(inputs))
    scenario.clients.logs_fake.answers = [
        _once("noise", line, stream=f"production-acquire/acquire/{TASK_ID}")
    ]
    assert scenario.mode(*argv) == launch.EXIT_ROW_COMPLETED
    out = capsys.readouterr().out
    assert "collection=COLLECTED requests=3" in out and launch.SENTENCES["row_completed"] in out
    assert "scan_complete=true" in out
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


def _launch_scenario(tmp_path: Path) -> tuple[Any, Any, Path, str, list[str]]:
    """The launch tool's completed acquisition launch with its destination registered:
    the scenario, the launch module, the record path, the genuine line and the argv."""
    import production_launch as launch
    from test_production_launch_script import TestCompleteRow

    from fixtures.production_runtime import encode

    scenario, record, lines = TestCompleteRow()._completed_scenario(tmp_path)
    inputs = json.loads(scenario.inputs.read_bytes())
    inputs["actors"]["acquisition"]["production"]["task_definition"]["log_destination"] = (
        log_destination_document("kalpamani-production-acquire")
    )
    scenario.inputs.write_bytes(encode(inputs))
    _observed(record, 0)
    argv = [
        "--complete-row",
        "--launch-record",
        str(record),
        "--collect-receipt",
        launch.COLLECT_FLAG,
    ]
    return scenario, launch, record, _receipt_line_of(lines), argv


def _observed(record: Path, exit_code: int | None) -> None:
    """The launch record with the exit the launcher observed at the terminal state."""
    from fixtures.production_runtime import encode

    document = json.loads(record.read_bytes())
    document["observed_exit_code"] = exit_code
    record.write_bytes(encode(document))


def _stream(*pages: list[str], tail: str = "f/end") -> list[Any]:
    """Queued GetLogEvents answers: one per page with a fresh token, then the end."""
    answers: list[Any] = [
        {"events": [{"message": m} for m in page], "nextForwardToken": f"f/{i}"}
        for i, page in enumerate(pages, start=1)
    ]
    answers.append({"events": [], "nextForwardToken": tail if not pages else f"f/{len(pages)}"})
    return answers


def test_an_incomplete_scan_completes_nothing_through_either_tool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Finding 1, the permission tool: a valid line on page 1, a contradictory line on
    # page 17 (beyond the 16-page pass). The scan continues past the pass bound, finds
    # the contradiction and refuses: nothing completed, no line kept.
    subcell = "R4-SECRET-GET-TASK"
    t = _launched(tmp_path / "contradiction", subcell)
    capsys.readouterr()
    good = _receipt_line_of(t.receipt_lines(TaskOutcome.PROBE_MATCHED))
    bad = _receipt_line_of(t.receipt_lines(TaskOutcome.PROBE_MATCHED, statement_sha256="77" * 32))
    pages = [[good]] + [["noise"]] * 15 + [[bad]]
    t.launch_clients.logs_fake.answers = _stream(*pages)
    argv = ["--collect-receipt", subcell, *t.base(), tool.COLLECT_FLAG]
    assert t.main(*argv) == tool.EXIT_COLLECTION_NOT_COLLECTED
    out = capsys.readouterr().out
    assert "collection=CONTRADICTORY_RECEIPTS requests=17" in out and "scan_complete=false" in out
    assert (
        t.files("permission-record") == []
        and t.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
    )
    record = rc.parse_collection_record(t.files("receipt-collection")[0].read_bytes())
    assert record.receipt_line is None and record.distinct_receipt_lines == 2
    # The same line seen, and the request budget spent before the end: SCAN_INCOMPLETE,
    # nothing kept, nothing completed -- and the next collection reads again.
    t2 = _launched(tmp_path / "incomplete", subcell)
    capsys.readouterr()
    good2 = _receipt_line_of(t2.receipt_lines(TaskOutcome.PROBE_MATCHED))
    endless = [[good2]] + [["noise"]] * 60
    t2.launch_clients.logs_fake.answers = _stream(*endless)
    assert t2.main("--collect-receipt", subcell, *t2.base(), tool.COLLECT_FLAG) == (
        tool.EXIT_COLLECTION_NOT_COLLECTED
    )
    out = capsys.readouterr().out
    assert f"collection=SCAN_INCOMPLETE requests={rc.COLLECT_MAX_REQUESTS}" in out
    assert t2.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
    assert (
        rc.parse_collection_record(t2.files("receipt-collection")[0].read_bytes()).receipt_line
        is None
    )
    # Control: the same line with the end observed within the budget completes.
    t2.launch_clients.logs_fake.answers = _stream([good2], *([["noise"]] * 20))
    assert (
        t2.main("--collect-receipt", subcell, *t2.base(), tool.COLLECT_FLAG) == tool.EXIT_COMPLETED
    )
    assert "collection=COLLECTED requests=23" in capsys.readouterr().out
    # Finding 1, the launch tool: the same shapes through --complete-row --collect-receipt.
    # (A recorded contradiction blocks every later collection of its launch -- correction
    # 2 -- so it takes a launch of its own.)
    contradicted, launch, _record, cline, cargv = _launch_scenario(tmp_path / "contradicted")
    contradiction = RECEIPT_LINE_PREFIX + '{"synthetic": "contradiction"}'
    contradicted.clients.logs_fake.answers = _stream([cline], *([["noise"]] * 15), [contradiction])
    assert contradicted.mode(*cargv) == launch.EXIT_COLLECTION_NOT_COLLECTED
    assert "collection=CONTRADICTORY_RECEIPTS requests=17" in capsys.readouterr().out
    scenario, launch, record_path, line, largv = _launch_scenario(tmp_path / "launch")
    scenario.clients.logs_fake.answers = _stream([line], *([["noise"]] * 60))
    assert scenario.mode(*largv) == launch.EXIT_COLLECTION_NOT_COLLECTED
    assert "collection=SCAN_INCOMPLETE" in capsys.readouterr().out
    from fixtures.production_build import RUN_1

    row = lr.parse_owner_ledger(scenario.ledger.read_bytes()).row(RUN_1)
    assert row is not None and row.evidence is lr.LedgerEvidence.EXIT_CODE_ONLY
    for path in scenario.files("receipt-collection"):
        assert rc.parse_collection_record(path.read_bytes()).receipt_line is None
    # Control: the end observed within the budget completes the row.
    scenario.clients.logs_fake.answers = _stream(["noise"], [line])
    assert scenario.mode(*largv) == launch.EXIT_ROW_COMPLETED
    capsys.readouterr()
    row = lr.parse_owner_ledger(scenario.ledger.read_bytes()).row(RUN_1)
    assert row is not None and row.buildable
    # No collection before the launcher observed the terminal state.
    _observed(record_path, None)
    scenario.clients.logs_fake.answers = [AssertionError("no read before the terminal state")]
    assert scenario.mode(*largv) == launch.EXIT_REFUSED_RECORDS


def test_rejected_content_leaves_only_closed_metadata_through_either_tool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Finding 2: receipt-prefixed malformed text and a closed document with one unexpected
    # field, each carrying a synthetic sensitive value: nothing of it reaches any file or
    # stdout; the record carries the closed defect and the byte count.
    subcell = "R4-SECRET-GET-TASK"
    t = _launched(tmp_path / "probe", subcell)
    capsys.readouterr()
    good = _receipt_line_of(t.receipt_lines(TaskOutcome.PROBE_MATCHED))
    document = json.loads(good[len(RECEIPT_LINE_PREFIX) :])
    document["synthetic_secret"] = SENSITIVE
    argv = ["--collect-receipt", subcell, *t.base(), tool.COLLECT_FLAG]
    for line, defect in (
        (RECEIPT_LINE_PREFIX + "not json " + SENSITIVE, "DOCUMENT_MALFORMED"),
        (RECEIPT_LINE_PREFIX + json.dumps(document), "FIELD_UNKNOWN"),
    ):
        t.launch_clients.logs_fake.answers = [_stream_answer(t, line)]
        assert t.main(*argv) == tool.EXIT_COLLECTION_NOT_COLLECTED, defect
        out = capsys.readouterr().out
        assert "collection=RECEIPT_REJECTED" in out and SENSITIVE not in out
        for path in t.scenario.records.iterdir():
            assert SENSITIVE not in path.read_text(encoding="utf-8", errors="replace")
        record = rc.parse_collection_record(t.files("receipt-collection")[-1].read_bytes())
        assert record.rejection is not None and record.rejection.value == defect
        assert record.receipt_line is None
        assert record.rejected_receipt_bytes == len(line.encode())
        assert t.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
    # Control: the launch's own line completes, the two rejected attempts beside it.
    t.launch_clients.logs_fake.answers = [_stream_answer(t, good)]
    assert t.main(*argv) == tool.EXIT_COMPLETED
    capsys.readouterr()
    assert len(t.files("receipt-collection")) == 3
    # The launch tool.
    scenario, launch, _record_path, line, largv = _launch_scenario(tmp_path / "launch")
    scenario.clients.logs_fake.answers = [_once(RECEIPT_LINE_PREFIX + "{broken " + SENSITIVE)]
    assert scenario.mode(*largv) == launch.EXIT_COLLECTION_NOT_COLLECTED
    out = capsys.readouterr().out
    assert "collection=RECEIPT_REJECTED" in out and SENSITIVE not in out
    for path in scenario.records.iterdir():
        assert SENSITIVE not in path.read_text(encoding="utf-8", errors="replace")
    scenario.clients.logs_fake.answers = [_once(line)]
    assert scenario.mode(*largv) == launch.EXIT_ROW_COMPLETED


def test_cached_collection_records_are_admitted_by_one_rule_through_either_tool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Finding 3, the permission tool: two COLLECTED records for the same launch carrying
    # different verified lines refuse in either filename order; nothing is chosen.
    subcell = "R4-SECRET-GET-TASK"
    t = _launched(tmp_path / "probe", subcell)
    capsys.readouterr()
    good = _receipt_line_of(t.receipt_lines(TaskOutcome.PROBE_MATCHED))
    document = json.loads(good[len(RECEIPT_LINE_PREFIX) :])
    reordered = RECEIPT_LINE_PREFIX + json.dumps(dict(reversed(list(document.items()))))
    t.launch_clients.logs_fake.answers = [_stream_answer(t, "noise")]
    argv = ["--collect-receipt", subcell, *t.base(), tool.COLLECT_FLAG]
    assert t.main(*argv) == tool.EXIT_COLLECTION_NOT_COLLECTED
    capsys.readouterr()
    template = json.loads(t.files("receipt-collection")[0].read_bytes())

    def cached(stamp: str, **fields: Any) -> Path:
        path = t.scenario.records / f"receipt-collection-{stamp}-0000.json"
        path.write_bytes(json.dumps(dict(template, **fields), sort_keys=True).encode())
        return path

    a = cached("20260101T000000Z", outcome="COLLECTED", scan_complete=True, receipt_line=reordered)
    cached("20260102T000000Z", outcome="COLLECTED", scan_complete=True, receipt_line=good)
    t.launch_clients.logs_fake.answers = [AssertionError("no read while the records contradict")]
    for _ in range(2):
        assert t.main(*argv) == tool.EXIT_REFUSED_COLLECTION_RECORDS
        assert tool.SENTENCES["refused_collection_records"] in capsys.readouterr().out
        a = a.rename(t.scenario.records / "receipt-collection-20260103T000000Z-0000.json")
    assert t.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
    a.unlink()
    # One verified COLLECTED record beside history: reused, the stream not read.
    assert t.main(*argv) == tool.EXIT_COMPLETED
    capsys.readouterr()
    # A record about this identity bound to another launch record, another stream, or
    # malformed, and a COLLECTED record whose line does not verify: each refuses.
    t2 = _launched(tmp_path / "bound", subcell)
    capsys.readouterr()
    t2.launch_clients.logs_fake.answers = [_stream_answer(t2, "noise")]
    argv2 = ["--collect-receipt", subcell, *t2.base(), tool.COLLECT_FLAG]
    assert t2.main(*argv2) == tool.EXIT_COLLECTION_NOT_COLLECTED
    capsys.readouterr()
    base = json.loads(t2.files("receipt-collection")[0].read_bytes())
    stray = t2.scenario.records / "receipt-collection-20260104T000000Z-0000.json"
    for fields in (
        {"launch_record_sha256": "cd" * 32},
        {"log_stream": f"production-acquire-probe/acquire-probe/{'f' * 32}"},
        {"scan_complete": "yes"},
        {
            "outcome": "COLLECTED",
            "scan_complete": True,
            "receipt_line": good.replace("acquisition", "build", 1),
        },
    ):
        stray.write_bytes(json.dumps(dict(base, **fields), sort_keys=True).encode())
        assert t2.main(*argv2) == tool.EXIT_REFUSED_COLLECTION_RECORDS, fields
        capsys.readouterr()
    stray.unlink()
    # Recovery after a rejected attempt: the stream is read again and completes.
    t2.launch_clients.logs_fake.answers = [_stream_answer(t2, RECEIPT_LINE_PREFIX + "{bad")]
    assert t2.main(*argv2) == tool.EXIT_COLLECTION_NOT_COLLECTED
    capsys.readouterr()
    good2 = _receipt_line_of(t2.receipt_lines(TaskOutcome.PROBE_MATCHED))
    t2.launch_clients.logs_fake.answers = [_stream_answer(t2, good2)]
    assert t2.main(*argv2) == tool.EXIT_COMPLETED
    capsys.readouterr()
    outcomes = sorted(json.loads(p.read_bytes())["outcome"] for p in t2.files("receipt-collection"))
    assert outcomes == ["COLLECTED", "NO_RECEIPT_WITHIN_BUDGET", "RECEIPT_REJECTED"]
    # Finding 3, the launch tool: the same rule, the same refusal, either order.
    scenario, launch, _record_path, line, largv = _launch_scenario(tmp_path / "launch")
    scenario.clients.logs_fake.answers = [{"events": [], "nextForwardToken": "f"}]
    assert scenario.mode(*largv) == launch.EXIT_COLLECTION_NOT_COLLECTED
    capsys.readouterr()
    template = json.loads(scenario.files("receipt-collection")[0].read_bytes())
    ldoc = json.loads(line[len(RECEIPT_LINE_PREFIX) :])
    lreordered = RECEIPT_LINE_PREFIX + json.dumps(dict(reversed(list(ldoc.items()))))
    first = scenario.records / "receipt-collection-20260101T000000Z-0000.json"
    first.write_bytes(
        json.dumps(
            dict(template, outcome="COLLECTED", scan_complete=True, receipt_line=lreordered)
        ).encode()
    )
    (scenario.records / "receipt-collection-20260102T000000Z-0000.json").write_bytes(
        json.dumps(
            dict(template, outcome="COLLECTED", scan_complete=True, receipt_line=line)
        ).encode()
    )
    scenario.clients.logs_fake.answers = [AssertionError("no read while the records contradict")]
    for _ in range(2):
        assert scenario.mode(*largv) == launch.EXIT_REFUSED_COLLECTION_RECORDS
        assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_collection_records"]
        first = first.rename(scenario.records / "receipt-collection-20260103T000000Z-0000.json")
    first.unlink()
    assert scenario.mode(*largv) == launch.EXIT_ROW_COMPLETED


def _reordered(line: str) -> str:
    """The same receipt document as a different line: a contradiction, not a duplicate."""
    document = json.loads(line[len(RECEIPT_LINE_PREFIX) :])
    return RECEIPT_LINE_PREFIX + json.dumps(dict(reversed(list(document.items()))))


def _contradiction_digest(records: list[Path]) -> str:
    [path] = [
        p for p in records if json.loads(p.read_bytes())["outcome"] == "CONTRADICTORY_RECEIPTS"
    ]
    return rc.collection_record_sha256(json.loads(path.read_bytes()))


def test_a_recorded_contradiction_is_never_superseded_through_either_tool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Correction 2, the permission tool: CONTRADICTORY_RECEIPTS recorded; a later collection
    # returning one valid line, and a COLLECTED record placed beside it in either order,
    # each refuse -- the stream is not read again, nothing completes.
    subcell = "R4-SECRET-GET-TASK"
    t = _launched(tmp_path / "probe", subcell)
    capsys.readouterr()
    good = _receipt_line_of(t.receipt_lines(TaskOutcome.PROBE_MATCHED))
    argv = ["--collect-receipt", subcell, *t.base(), tool.COLLECT_FLAG]
    logs = t.launch_clients.logs_fake
    logs.answers = [_stream_answer(t, good, _reordered(good))]
    assert t.main(*argv) == tool.EXIT_COLLECTION_NOT_COLLECTED
    assert "collection=CONTRADICTORY_RECEIPTS" in capsys.readouterr().out
    contradiction = t.files("receipt-collection")[0]
    original = contradiction.read_bytes()
    logs.answers = [_stream_answer(t, good)]
    reads = len(logs.calls)
    for _ in range(2):
        assert t.main(*argv) == tool.EXIT_REFUSED_CONTRADICTION_UNRESOLVED
        assert tool.SENTENCES["refused_contradiction_unresolved"] in capsys.readouterr().out
    assert len(logs.calls) == reads and len(t.files("receipt-collection")) == 1
    template = json.loads(original)
    collected = dict(
        template,
        outcome="COLLECTED",
        scan_complete=True,
        distinct_receipt_lines=1,
        receipt_line=good,
    )
    for stamp in ("20200101T000000Z", "20990101T000000Z"):
        beside = t.scenario.records / f"receipt-collection-{stamp}-0000.json"
        beside.write_bytes(json.dumps(collected, sort_keys=True).encode())
        assert t.main(*argv) == tool.EXIT_REFUSED_CONTRADICTION_UNRESOLVED, stamp
        capsys.readouterr()
        beside.unlink()
    assert len(logs.calls) == reads and t.status(subcell) is pc.SubcellStatus.AWAITING_RECEIPT
    # The hand-read completion: refused without the acknowledgement, refused with a digest
    # that names no recorded contradiction, refused with the flag beside a collection; with
    # the contradiction record's digest it completes and writes one disposition bound to
    # that digest, the launch record and the receipt line -- the contradiction record is
    # byte-for-byte as written.
    receipt = t.receipt_lines(TaskOutcome.PROBE_MATCHED)
    digest = _contradiction_digest(t.files("receipt-collection"))
    assert t.complete(subcell, receipt) == tool.EXIT_REFUSED_CONTRADICTION_UNRESOLVED
    capsys.readouterr()
    assert (
        t.complete(
            subcell,
            receipt,
        )
        == tool.EXIT_REFUSED_CONTRADICTION_UNRESOLVED
    )
    capsys.readouterr()
    assert (
        t.main(
            "--complete-subcell",
            subcell,
            *t.base(),
            "--receipt-lines",
            str(receipt),
            tool.ACKNOWLEDGE_FLAG,
            "cd" * 32,
        )
        == tool.EXIT_REFUSED_CONTRADICTION_UNRESOLVED
    )
    capsys.readouterr()
    assert t.main(*argv, tool.ACKNOWLEDGE_FLAG, digest) == tool.EXIT_REFUSED_ARGUMENTS
    assert (
        t.main(
            "--complete-subcell",
            subcell,
            *t.base(),
            "--receipt-lines",
            str(receipt),
            tool.ACKNOWLEDGE_FLAG,
            "not-a-digest",
        )
        == tool.EXIT_REFUSED_ARGUMENTS
    )
    capsys.readouterr()
    assert t.files("collection-disposition") == []
    acknowledged = [
        "--complete-subcell",
        subcell,
        *t.base(),
        "--receipt-lines",
        str(receipt),
        tool.ACKNOWLEDGE_FLAG,
        digest,
    ]
    assert t.main(*acknowledged) == tool.EXIT_COMPLETED
    capsys.readouterr()
    dispositions = t.files("collection-disposition")
    assert len(dispositions) == 1
    disposition = rc.parse_collection_disposition(dispositions[0].read_bytes())
    assert disposition.contradiction_sha256 == digest
    assert disposition.disposition is rc.ContradictionDisposition.HAND_READ_COMPLETION
    from kalpamani.data.contracts.canonical import sha256_hex

    assert disposition.receipt_line_sha256 == sha256_hex(_receipt_line_of(receipt).encode())
    launch_record = lr.parse_launch_record(t.files("launch-record")[0].read_bytes())
    assert disposition.launch_record_sha256 == pc.launch_record_digest(launch_record)
    assert contradiction.read_bytes() == original and len(t.files("receipt-collection")) == 1
    assert t.status(subcell) is pc.SubcellStatus.CLEANUP_UNRESOLVED
    # Repeatable: the same acknowledged completion, and the plain one, both say it is whole
    # and write nothing more; a collection afterwards is admitted (the contradiction is
    # disposed) and says the same.
    assert t.main(*acknowledged) == tool.EXIT_COMPLETION_RECORDED
    capsys.readouterr()
    assert t.complete(subcell, receipt) == tool.EXIT_COMPLETION_RECORDED
    capsys.readouterr()
    logs.answers = [AssertionError("no read after a disposed contradiction")]
    assert t.main(*argv) == tool.EXIT_COMPLETION_RECORDED
    capsys.readouterr()
    assert len(t.files("collection-disposition")) == 1
    # Control: exhausted and rejected attempts stay retryable as designed.
    t2 = _launched(tmp_path / "retry", subcell)
    capsys.readouterr()
    good2 = _receipt_line_of(t2.receipt_lines(TaskOutcome.PROBE_MATCHED))
    argv2 = ["--collect-receipt", subcell, *t2.base(), tool.COLLECT_FLAG]
    for answer in (_stream_answer(t2), _stream_answer(t2, RECEIPT_LINE_PREFIX + "{bad")):
        t2.launch_clients.logs_fake.answers = [answer]
        assert t2.main(*argv2) == tool.EXIT_COLLECTION_NOT_COLLECTED
        capsys.readouterr()
    t2.launch_clients.logs_fake.answers = [_stream_answer(t2, good2)]
    assert t2.main(*argv2) == tool.EXIT_COMPLETED
    capsys.readouterr()
    assert t2.files("collection-disposition") == []
    # Correction 2, the launch tool: the same rule, the same refusal (exit 18), the same
    # disposition through --complete-row --receipt-lines.
    scenario, launch, record_path, line, largv = _launch_scenario(tmp_path / "launch")
    scenario.clients.logs_fake.answers = [_once(line, _reordered(line))]
    assert scenario.mode(*largv) == launch.EXIT_COLLECTION_NOT_COLLECTED
    assert "collection=CONTRADICTORY_RECEIPTS" in capsys.readouterr().out
    contradiction = scenario.files("receipt-collection")[0]
    original = contradiction.read_bytes()
    scenario.clients.logs_fake.answers = [_once(line)]
    reads = len(scenario.clients.logs_fake.calls)
    assert scenario.mode(*largv) == launch.EXIT_REFUSED_CONTRADICTION_UNRESOLVED
    assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_contradiction_unresolved"]
    template = json.loads(original)
    collected = dict(
        template,
        outcome="COLLECTED",
        scan_complete=True,
        distinct_receipt_lines=1,
        receipt_line=line,
    )
    for stamp in ("20200101T000000Z", "20990101T000000Z"):
        beside = scenario.records / f"receipt-collection-{stamp}-0000.json"
        beside.write_bytes(json.dumps(collected, sort_keys=True).encode())
        assert scenario.mode(*largv) == launch.EXIT_REFUSED_CONTRADICTION_UNRESOLVED, stamp
        capsys.readouterr()
        beside.unlink()
    assert len(scenario.clients.logs_fake.calls) == reads
    from fixtures.production_build import RUN_1

    row = lr.parse_owner_ledger(scenario.ledger.read_bytes()).row(RUN_1)
    assert row is not None and row.evidence is lr.LedgerEvidence.EXIT_CODE_ONLY
    lines = scenario.root / "receipt.txt"
    hand = ["--complete-row", "--launch-record", str(record_path), "--receipt-lines", str(lines)]
    digest = _contradiction_digest(scenario.files("receipt-collection"))
    assert scenario.mode(*hand) == launch.EXIT_REFUSED_CONTRADICTION_UNRESOLVED
    assert (
        scenario.mode(*hand, launch.ACKNOWLEDGE_FLAG, "cd" * 32)
        == launch.EXIT_REFUSED_CONTRADICTION_UNRESOLVED
    )
    assert scenario.mode(*largv, launch.ACKNOWLEDGE_FLAG, digest) == launch.EXIT_REFUSED_ARGUMENTS
    assert scenario.mode(*hand, launch.ACKNOWLEDGE_FLAG, "x") == launch.EXIT_REFUSED_ARGUMENTS
    capsys.readouterr()
    assert scenario.files("collection-disposition") == []
    assert scenario.mode(*hand, launch.ACKNOWLEDGE_FLAG, digest) == launch.EXIT_ROW_COMPLETED
    capsys.readouterr()
    row = lr.parse_owner_ledger(scenario.ledger.read_bytes()).row(RUN_1)
    assert row is not None and row.buildable
    dispositions = scenario.files("collection-disposition")
    assert len(dispositions) == 1
    disposition = rc.parse_collection_disposition(dispositions[0].read_bytes())
    assert disposition.contradiction_sha256 == digest
    assert disposition.receipt_line_sha256 == sha256_hex(line.encode())
    assert contradiction.read_bytes() == original
    # Never twice, with or without the flag; a collection afterwards is admitted and refuses
    # only because the row is complete.
    assert scenario.mode(*hand, launch.ACKNOWLEDGE_FLAG, digest) == launch.EXIT_REFUSED_RECORDS
    assert scenario.mode(*hand) == launch.EXIT_REFUSED_RECORDS
    scenario.clients.logs_fake.answers = [AssertionError("no read after a disposed contradiction")]
    assert scenario.mode(*largv) == launch.EXIT_REFUSED_RECORDS
    capsys.readouterr()
    assert len(scenario.files("collection-disposition")) == 1


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
