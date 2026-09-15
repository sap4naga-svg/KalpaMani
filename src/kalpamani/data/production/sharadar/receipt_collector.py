"""The bounded receipt collector (proposed ADR-0049 s.2; the collection ADR-0044 s.4 deferred).

A task's receipt is one closed line on its log stream. Until now the owner hand-read it and
handed it to the tools (``--receipt-lines``). The collector reads it **from the exact stream
the launch record and the registered task-definition evidence name** -- the research log
group and the stream prefix the owner transcribed from the applied revision, the container
the entry runs in, and the launch record's own task id -- and hands the line to **the same
verifier and the same completion** the hand-read path uses. A caller supplies no stream;
nothing here is a second route to a completed row or a PASSED subcell.

Bounded, and what its bounds mean:

- **request limits** -- at most :data:`COLLECT_MAX_REQUESTS` ``GetLogEvents`` requests per
  collection, read in passes of at most :data:`COLLECT_MAX_PAGES` pages, each page the
  service's own ceiling (10,000 events or 1 MiB); at most :data:`COLLECT_MAX_EVENTS`
  events scanned; at most :data:`COLLECT_CEILING_SECONDS` elapsed on an injected monotonic
  clock. **Every limit is checked before a request is issued**: the request count, the
  event count and the elapsed time each refuse the next request when reached, and a page
  whose events would cross the event ceiling is scanned only up to it. **The one limit
  this module cannot enforce is a request already in flight**: an issued request completes,
  or fails, within the client's own connect and read timeouts (the workstation client
  configuration: finite, and one attempt in total), so the elapsed time of a collection may
  exceed the ceiling by at most one request's in-flight time;
- **effective SDK retries: zero** -- the logs client is built with one attempt in total
  (``total_max_attempts = 1``); a throttled or failed request is recorded, never retried
  inside the SDK, and the collector itself re-issues nothing within a pass;
- **a complete scan, and only a complete scan, establishes uniqueness** -- the stream is
  read from its head until the forward token repeats (the documented end of the stream as
  delivered so far) and, after one poll interval, a re-read from that token delivers nothing
  new: that closes the **observation window**. Exactly one distinct receipt-shaped line in
  a complete scan is a candidate; a receipt-shaped line seen in a scan the budget cut short
  is ``SCAN_INCOMPLETE`` -- it establishes nothing, and the line is not kept. Two distinct
  receipt-shaped lines are ``CONTRADICTORY_RECEIPTS`` whether or not the scan completed;
- **delayed delivery** -- the ``awslogs`` driver delivers events with lag, and the window
  closes on the stream *as delivered* by ``finished_at``: an event delivered after the
  window closed was not observed. That is why a collection is performed only after the
  launcher observed the task's terminal state (nothing more is written once it stopped),
  why the window is recorded on every record (``started_at``, ``finished_at``,
  ``scan_complete``), and why ``COLLECTED`` means *unique within the observed window*;
- **validated before it is kept** -- the candidate line must decode as the closed receipt
  document and verify against the launch record's expectation (task, revision, image,
  identity, input, configuration, commit) **before** anything of it is persisted. A line
  that does not is ``RECEIPT_REJECTED``: the record keeps the closed defect and the line's
  byte count, never the text. **A successful read is still not a verification**: the
  completion re-verifies the kept line exactly as a hand-read one, and checks it against
  the observed terminal exit;
- **an exhausted budget proves that no receipt was obtained within it**, not that none
  exists: ``NO_RECEIPT_WITHIN_BUDGET``, ``STREAM_NOT_FOUND_WITHIN_BUDGET`` and
  ``SCAN_INCOMPLETE`` are collection outcomes, never receipt verdicts, and a later
  collection may still find the line.

Only a verified receipt line is kept (it is the closed receipt document: tokens, counts,
digests -- no key, identifier, subject or row); every other event is counted and never
stored, so no arbitrary log content leaves the stream through this module. Real client
construction lives in the tools' authorized branches; this module imports no SDK.

**The collection record** (:data:`COLLECTION_CONTRACT_ID`) is closed:
:func:`parse_collection_record` admits exactly its fields, and :func:`admit_collection_records`
is the one cache rule both tools apply -- every record about this launch is read, each is
held to the launch record
digest and to the derived destination, a kept line is re-verified against the expectation,
two different kept lines are a contradiction that refuses, and a rejected or exhausted
attempt never blocks: the next collection reads the stream again and its record is written
beside the earlier ones. **A recorded ``CONTRADICTORY_RECEIPTS`` is never superseded**: while
it stands, no collection is made and no kept line is reused for that launch, whatever was
recorded before or after it and in whatever order. The one way past it is explicit and
evidence-bound -- the owner reads the stream, completes from a hand-read receipt while
acknowledging the contradiction record by its digest, and the tool writes a **disposition**
(:data:`DISPOSITION_CONTRACT_ID`) binding that digest, the launch record and the receipt it
completed from; the contradiction record stays exactly as written. **The disposition's receipt
binding constrains every later step**: once a disposition names receipt A, the launch is bound
to A -- a hand-read completion offering another line is refused, a kept line other than A is
refused, a collection reads nothing, and two dispositions naming different receipts refuse
as conflicting. An interrupted resolution (the disposition written, the completion not whole)
is therefore repeatable only with A, and a completed resolution is whole; the two are told
apart by the completion's own evidence, never by the disposition alone. No rule here chooses
between two lines, and no later collection resolves anything. Nothing is removed, and
nothing is chosen by filename order.

**Mocked results are not AWS verification.** Every page in this repository's tests is a fake's.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Protocol

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar.documents import decode_document, exact_str
from kalpamani.data.production.sharadar.entry import TaskEntry
from kalpamani.data.production.sharadar.receipts import (
    RECEIPT_LINE_PREFIX,
    ReceiptDefect,
    ReceiptError,
    ReceiptExpectation,
    decode_receipt_line,
    verify_receipt,
)

#: The research log group every production family writes to (``logging.tf``): the owner's
#: ``name_prefix`` between two fixed segments.
LOG_GROUP_RE: Final = re.compile(r"/kalpamani/[a-z0-9][a-z0-9-]{1,30}[a-z0-9]/research")
#: Each entry's container name and stream prefix in the declaration (``production_compute.tf``):
#: the container is the entry's short name, the prefix is ``production-`` + the container.
CONTAINER_OF_ENTRY: Final[dict[TaskEntry, str]] = {
    TaskEntry.ACQUISITION: "acquire",
    TaskEntry.BUILD: "build",
    TaskEntry.ACQUISITION_VERIFY: "acquire-verify",
    TaskEntry.BUILD_VERIFY: "build-verify",
    TaskEntry.ACQUISITION_PROBE: "acquire-probe",
    TaskEntry.BUILD_PROBE: "build-probe",
}
STREAM_PREFIX_OF_ENTRY: Final[dict[TaskEntry, str]] = {
    entry: f"production-{container}" for entry, container in CONTAINER_OF_ENTRY.items()
}
_TASK_ID_RE: Final = re.compile(r"[0-9a-f]{32}")

COLLECT_MAX_PAGES: Final = 16
COLLECT_MAX_REQUESTS: Final = 40
COLLECT_MAX_EVENTS: Final = 20_000
COLLECT_POLL_SECONDS: Final = 15.0
COLLECT_CEILING_SECONDS: Final = 300.0
#: The logs client is built with exactly one attempt in total: effective SDK retries 0.
LOGS_TOTAL_MAX_ATTEMPTS: Final = 1
LOGS_RETRY_MODE: Final = "standard"
COLLECTION_CONTRACT_ID: Final = "kalpamani-receipt-collection/v1"
#: The disposition of one recorded contradiction: written by a hand-read completion that
#: acknowledged it, never by a collection.
DISPOSITION_CONTRACT_ID: Final = "kalpamani-collection-disposition/v1"
#: The largest collection record the parser reads.
MAX_COLLECTION_RECORD_BYTES: Final = 64 * 1024
_LOG_STREAM_RE: Final = re.compile(r"production-[a-z-]+/[a-z-]+/[0-9a-f]{32}")
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")


class CollectorDefect(StrEnum):
    """Why a destination could not be derived. Closed."""

    LOG_GROUP_MALFORMED = "LOG_GROUP_MALFORMED"
    DESTINATION_UNREGISTERED = "DESTINATION_UNREGISTERED"
    DESTINATION_NOT_THE_ENTRY_S = "DESTINATION_NOT_THE_ENTRY_S"
    TASK_ID_MALFORMED = "TASK_ID_MALFORMED"


class CollectorError(ValueError):
    """A destination that does not derive, and why."""

    def __init__(self, defect: CollectorDefect) -> None:
        super().__init__(defect.value)
        self.defect = defect


@dataclass(frozen=True, slots=True, kw_only=True)
class LogDestination:
    """The registered log destination of one task-definition revision: the group and the
    stream prefix the owner transcribed from the applied revision, and the container name.
    Validated against the declaration's rule for the entry before any stream is named."""

    log_group: str
    stream_prefix: str
    container: str

    def __post_init__(self) -> None:
        if (
            type(self.log_group) is not str
            or LOG_GROUP_RE.fullmatch(self.log_group) is None
            or self.container not in CONTAINER_OF_ENTRY.values()
            or self.stream_prefix != f"production-{self.container}"
        ):
            raise CollectorError(CollectorDefect.LOG_GROUP_MALFORMED)

    def document(self) -> dict[str, Any]:
        return {
            "log_group": self.log_group,
            "stream_prefix": self.stream_prefix,
            "container": self.container,
        }

    def __repr__(self) -> str:
        return f"LogDestination(container={self.container!r})"


_DESTINATION_FIELDS: Final[frozenset[str]] = frozenset({"log_group", "stream_prefix", "container"})


def parse_log_destination(raw: object) -> LogDestination:
    """A registered log destination block, closed, or ``CollectorError``."""
    if type(raw) is not dict or set(raw) != _DESTINATION_FIELDS:
        raise CollectorError(CollectorDefect.LOG_GROUP_MALFORMED)
    values = {name: exact_str(raw[name]) for name in _DESTINATION_FIELDS}
    if any(value is None for value in values.values()):
        raise CollectorError(CollectorDefect.LOG_GROUP_MALFORMED)
    return LogDestination(
        log_group=values["log_group"] or "",
        stream_prefix=values["stream_prefix"] or "",
        container=values["container"] or "",
    )


def destination_for(entry: TaskEntry, registered: LogDestination | None) -> LogDestination:
    """The destination a launch of ``entry`` writes to: the registered one, held to the entry.

    A registration that names no destination refuses (nothing is inferred from a family
    name alone); one whose container or prefix is another entry's refuses -- the
    collector never reads a stream the registered evidence does not name for this entry.
    """
    if type(entry) is not TaskEntry:
        raise TypeError("entry must be an exact TaskEntry")
    if registered is None:
        raise CollectorError(CollectorDefect.DESTINATION_UNREGISTERED)
    if (
        registered.container != CONTAINER_OF_ENTRY[entry]
        or registered.stream_prefix != STREAM_PREFIX_OF_ENTRY[entry]
    ):
        raise CollectorError(CollectorDefect.DESTINATION_NOT_THE_ENTRY_S)
    return registered


def log_stream_name(destination: LogDestination, task_id: str) -> str:
    """The ``awslogs`` stream of one task: ``<prefix>/<container>/<task-id>``."""
    if type(task_id) is not str or _TASK_ID_RE.fullmatch(task_id) is None:
        raise CollectorError(CollectorDefect.TASK_ID_MALFORMED)
    return f"{destination.stream_prefix}/{destination.container}/{task_id}"


@dataclass(frozen=True, slots=True, kw_only=True)
class LogPage:
    """One ``GetLogEvents`` answer as the collector reads it: the messages, the forward token,
    or the closed failure. Messages are scanned and never kept beyond the receipt line."""

    status: int | None
    events: tuple[str, ...] = ()
    next_forward_token: str | None = None
    code: str | None = None
    transport_failure: str | None = None


class LogsClient(Protocol):
    """The one logs operation the collector uses."""

    def get_log_events(
        self, *, log_group_name: str, log_stream_name: str, next_token: str | None
    ) -> LogPage: ...


class CollectionOutcome(StrEnum):
    """What one collection established. Closed; never a receipt verdict."""

    #: A complete scan, exactly one distinct receipt line, verified against the launch.
    COLLECTED = "COLLECTED"
    #: A complete scan, exactly one distinct receipt-shaped line, refused by the verifier;
    #: the closed defect is kept, the text is not.
    RECEIPT_REJECTED = "RECEIPT_REJECTED"
    #: A receipt-shaped line was seen, and the budget ended the scan before the stream's
    #: end was observed: nothing is established, and the line is not kept.
    SCAN_INCOMPLETE = "SCAN_INCOMPLETE"
    NO_RECEIPT_WITHIN_BUDGET = "NO_RECEIPT_WITHIN_BUDGET"
    STREAM_NOT_FOUND_WITHIN_BUDGET = "STREAM_NOT_FOUND_WITHIN_BUDGET"
    CONTRADICTORY_RECEIPTS = "CONTRADICTORY_RECEIPTS"
    DENIED = "DENIED"
    THROTTLED = "THROTTLED"
    FAILED = "FAILED"


_DENIAL_CODES: Final[frozenset[str]] = frozenset({"AccessDeniedException", "AccessDenied"})
_THROTTLE_CODES: Final[frozenset[str]] = frozenset({"ThrottlingException", "Throttling"})
_ABSENT_CODES: Final[frozenset[str]] = frozenset({"ResourceNotFoundException"})


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectedReceipt:
    """The sanitized result of one collection: the outcome, the counts, the observation
    window and, when a complete scan found exactly one verified receipt line, that line --
    the closed receipt document, nothing else. A rejected line leaves its closed defect
    and its byte count; no other line, and no other event, is ever carried."""

    outcome: CollectionOutcome
    log_group: str
    log_stream: str
    requests: int
    pages: int
    events_scanned: int
    distinct_receipt_lines: int
    scan_complete: bool
    receipt_line: str | None
    rejection: ReceiptDefect | None
    rejected_receipt_bytes: int | None
    started_at: datetime
    finished_at: datetime
    elapsed_ms: int

    def __post_init__(self) -> None:
        collected = self.outcome is CollectionOutcome.COLLECTED
        rejected = self.outcome is CollectionOutcome.RECEIPT_REJECTED
        if collected != (self.receipt_line is not None):
            raise ValueError("a receipt line is present exactly when one was collected")
        if rejected != (self.rejection is not None):
            raise ValueError("a rejection is present exactly when a line was rejected")
        if rejected != (self.rejected_receipt_bytes is not None):
            raise ValueError("a rejected line's byte count is present exactly when rejected")
        if (collected or rejected) and not self.scan_complete:
            raise ValueError("only a complete scan establishes one line")
        if self.receipt_line is not None and not self.receipt_line.startswith(RECEIPT_LINE_PREFIX):
            raise ValueError("a collected line is a receipt line")
        if self.outcome is CollectionOutcome.SCAN_INCOMPLETE and self.scan_complete:
            raise ValueError("an incomplete scan is not complete")

    def document(self, *, identity: str, launch_record_sha256: str) -> dict[str, Any]:
        """The collection record: the evidence a verification needs, and no other event."""
        return {
            "contract_id": COLLECTION_CONTRACT_ID,
            "identity": identity,
            "launch_record_sha256": launch_record_sha256,
            "log_group": self.log_group,
            "log_stream": self.log_stream,
            "outcome": self.outcome.value,
            "requests": self.requests,
            "pages": self.pages,
            "events_scanned": self.events_scanned,
            "distinct_receipt_lines": self.distinct_receipt_lines,
            "scan_complete": self.scan_complete,
            "receipt_line": self.receipt_line,
            "rejection": None if self.rejection is None else self.rejection.value,
            "rejected_receipt_bytes": self.rejected_receipt_bytes,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "elapsed_ms": self.elapsed_ms,
        }

    def digest(self, *, identity: str, launch_record_sha256: str) -> str:
        return sha256_hex(
            canonical_bytes(
                self.document(identity=identity, launch_record_sha256=launch_record_sha256)
            )
        )

    def summary(self) -> str:
        """The one line the tools print: outcome and counts, never content."""
        return (
            f"collection={self.outcome.value} requests={self.requests} pages={self.pages} "
            f"events_scanned={self.events_scanned} "
            f"distinct_receipt_lines={self.distinct_receipt_lines} "
            f"scan_complete={str(self.scan_complete).lower()}"
        )

    def __repr__(self) -> str:
        return f"CollectedReceipt(outcome={self.outcome.value!r}, requests={self.requests})"


def collect_receipt(
    *,
    destination: LogDestination,
    task_id: str,
    expectation: ReceiptExpectation,
    client: LogsClient,
    now: Callable[[], datetime],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
) -> CollectedReceipt:
    """Read the task's stream for its one receipt line, bounded; keep it only verified.

    Pages are read from the head with the forward token in passes of at most
    ``COLLECT_MAX_PAGES``; a page whose token equals the one it was asked with is the end
    of the stream as delivered so far. Every limit -- requests, events, elapsed time -- is
    checked **before** a request is issued, and a page is scanned only up to the event
    ceiling. Once the end is observed with no receipt-shaped line, delivery lag is waited
    out at the poll interval within the ceiling; a stream not yet created is the same
    wait. Once the end is observed with exactly one distinct receipt-shaped line, one
    more poll interval passes and the stream is re-read from the end token: a re-read that
    delivers nothing new closes the observation window, and only then is the line decoded
    and verified against ``expectation`` -- kept when it verifies (``COLLECTED``), its
    closed defect kept when it does not (``RECEIPT_REJECTED``). A denial, a throttle or a
    transport failure ends the collection at once with its own outcome -- the SDK retried
    nothing, and the collector retries nothing. Two distinct receipt-shaped lines are
    contradictory and refuse; the same line delivered twice is one line. A budget that
    ends the scan before the end was observed establishes nothing (``SCAN_INCOMPLETE``
    when a line was seen, exhaustion otherwise).
    """
    if type(expectation) is not ReceiptExpectation:
        raise TypeError("expectation must be an exact ReceiptExpectation")
    stream = log_stream_name(destination, task_id)
    started_at = now()
    started = monotonic()
    token: str | None = None
    requests = pages = scanned = 0
    seen: dict[str, None] = {}
    outcome: CollectionOutcome | None = None
    stream_absent = False
    awaiting_confirmation = False

    def elapsed() -> float:
        return max(0.0, monotonic() - started)

    def finish(
        final: CollectionOutcome,
        *,
        scan_complete: bool,
        line: str | None = None,
        rejection: ReceiptDefect | None = None,
        rejected_bytes: int | None = None,
    ) -> CollectedReceipt:
        return CollectedReceipt(
            outcome=final,
            log_group=destination.log_group,
            log_stream=stream,
            requests=requests,
            pages=pages,
            events_scanned=scanned,
            distinct_receipt_lines=len(seen),
            scan_complete=scan_complete,
            receipt_line=line,
            rejection=rejection,
            rejected_receipt_bytes=rejected_bytes,
            started_at=started_at,
            finished_at=now(),
            elapsed_ms=int(elapsed() * 1000),
        )

    def bound_reached() -> bool:
        return (
            requests >= COLLECT_MAX_REQUESTS
            or scanned >= COLLECT_MAX_EVENTS
            or elapsed() >= COLLECT_CEILING_SECONDS
        )

    while True:
        # One pass: pages from the current token until the end is observed, a page is
        # cut at the event ceiling, or a bound refuses the next request.
        end_observed = False
        new_events = 0
        for _ in range(COLLECT_MAX_PAGES):
            if bound_reached():
                break
            page = client.get_log_events(
                log_group_name=destination.log_group, log_stream_name=stream, next_token=token
            )
            requests += 1
            if page.transport_failure is not None:
                outcome = CollectionOutcome.FAILED
                break
            if page.code in _DENIAL_CODES or page.status == 403:
                outcome = CollectionOutcome.DENIED
                break
            if page.code in _THROTTLE_CODES or page.status == 429:
                outcome = CollectionOutcome.THROTTLED
                break
            if page.code in _ABSENT_CODES or page.status == 404:
                stream_absent = True
                break
            if page.status != 200 or page.code:
                outcome = CollectionOutcome.FAILED
                break
            pages += 1
            stream_absent = False
            truncated = False
            for message in page.events:
                if scanned >= COLLECT_MAX_EVENTS:
                    truncated = True
                    break
                scanned += 1
                new_events += 1
                if type(message) is str and message.startswith(RECEIPT_LINE_PREFIX):
                    seen.setdefault(message, None)
            if truncated or len(seen) > 1:
                # The ceiling cut the page, or a second distinct line contradicts the
                # first: nothing further is requested.
                break
            repeated = page.next_forward_token is None or page.next_forward_token == token
            token = page.next_forward_token if page.next_forward_token is not None else token
            if repeated:
                end_observed = True
                break
        if outcome is not None:
            return finish(outcome, scan_complete=False)
        if len(seen) > 1:
            return finish(CollectionOutcome.CONTRADICTORY_RECEIPTS, scan_complete=end_observed)
        if end_observed and len(seen) == 1:
            if awaiting_confirmation and new_events == 0:
                # The window is closed: the re-read after the poll delivered nothing new.
                line = next(iter(seen))
                try:
                    verify_receipt(decode_receipt_line(line), expectation=expectation)
                except ReceiptError as error:
                    return finish(
                        CollectionOutcome.RECEIPT_REJECTED,
                        scan_complete=True,
                        rejection=error.defect,
                        rejected_bytes=len(line.encode("utf-8", "surrogatepass")),
                    )
                return finish(CollectionOutcome.COLLECTED, scan_complete=True, line=line)
            awaiting_confirmation = True
        else:
            awaiting_confirmation = False
        # The next request needs budget for a poll interval when the end was observed
        # (delivery lag), and none when the pass ended on its page bound (more is there).
        wait = COLLECT_POLL_SECONDS if end_observed or stream_absent else 0.0
        if bound_reached() or elapsed() + wait > COLLECT_CEILING_SECONDS:
            if seen:
                return finish(CollectionOutcome.SCAN_INCOMPLETE, scan_complete=False)
            return finish(
                CollectionOutcome.STREAM_NOT_FOUND_WITHIN_BUDGET
                if stream_absent
                else CollectionOutcome.NO_RECEIPT_WITHIN_BUDGET,
                scan_complete=False,
            )
        if wait:
            sleep(wait)


# ---------------------------------------------------------------------------
# The collection record: one closed parser, one cache-admission rule
# ---------------------------------------------------------------------------


class CollectionRecordDefect(StrEnum):
    """Why a collection record, or the set of records about one launch, is refused."""

    RECORD_MALFORMED = "RECORD_MALFORMED"
    LAUNCH_MISMATCH = "LAUNCH_MISMATCH"
    DESTINATION_MISMATCH = "DESTINATION_MISMATCH"
    RECEIPT_UNVERIFIABLE = "RECEIPT_UNVERIFIABLE"
    CONTRADICTORY_RECORDS = "CONTRADICTORY_RECORDS"
    #: A CONTRADICTORY_RECEIPTS record about this launch has no disposition.
    CONTRADICTION_UNRESOLVED = "CONTRADICTION_UNRESOLVED"
    #: A disposition names a contradiction record that does not exist for this launch.
    DISPOSITION_UNBOUND = "DISPOSITION_UNBOUND"
    #: Two dispositions of this launch name different receipts.
    CONFLICTING_DISPOSITIONS = "CONFLICTING_DISPOSITIONS"
    #: A line offered or kept for this launch is not the receipt its disposition bound.
    RECEIPT_SUBSTITUTED = "RECEIPT_SUBSTITUTED"


class CollectionRecordError(ValueError):
    def __init__(self, defect: CollectionRecordDefect) -> None:
        super().__init__(defect.value)
        self.defect = defect


_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "contract_id",
        "identity",
        "launch_record_sha256",
        "log_group",
        "log_stream",
        "outcome",
        "requests",
        "pages",
        "events_scanned",
        "distinct_receipt_lines",
        "scan_complete",
        "receipt_line",
        "rejection",
        "rejected_receipt_bytes",
        "started_at",
        "finished_at",
        "elapsed_ms",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionRecord:
    """One collection record as parsed: closed fields, bound to a launch and a stream."""

    identity: str
    launch_record_sha256: str
    log_group: str
    log_stream: str
    outcome: CollectionOutcome
    requests: int
    pages: int
    events_scanned: int
    distinct_receipt_lines: int
    scan_complete: bool
    receipt_line: str | None
    rejection: ReceiptDefect | None
    rejected_receipt_bytes: int | None
    started_at: datetime
    finished_at: datetime
    elapsed_ms: int

    def __repr__(self) -> str:
        return f"CollectionRecord(outcome={self.outcome.value!r})"


def _refuse(defect: CollectionRecordDefect) -> CollectionRecordError:
    return CollectionRecordError(defect)


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
    return value


def _instant(value: object) -> datetime:
    text = exact_str(value)
    if text is None:
        raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise _refuse(CollectionRecordDefect.RECORD_MALFORMED) from None
    if parsed.tzinfo is None:
        raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
    return parsed


def is_collection_record(raw: object) -> bool:
    """Whether a decoded document claims to be a collection record (contract id only)."""
    return type(raw) is dict and raw.get("contract_id") == COLLECTION_CONTRACT_ID


def parse_collection_record(raw: object) -> CollectionRecord:
    """The one closed reading of a collection record, or ``CollectionRecordError``.

    Bytes are decoded under the record ceiling; a document must carry exactly the
    contract's fields with their exact types; a kept line exists exactly for ``COLLECTED``
    and must decode as the closed receipt document (its binding is the admission rule's);
    a rejection exists exactly for ``RECEIPT_REJECTED`` and names a closed defect; a
    complete scan is claimed exactly where the contract allows one.
    """
    document: Any = raw
    if isinstance(raw, bytes | bytearray):
        try:
            document = decode_document(bytes(raw), max_bytes=MAX_COLLECTION_RECORD_BYTES)
        except Exception:
            raise _refuse(CollectionRecordDefect.RECORD_MALFORMED) from None
    if type(document) is not dict or set(document) != _RECORD_FIELDS:
        raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
    if document["contract_id"] != COLLECTION_CONTRACT_ID:
        raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
    identity = exact_str(document["identity"])
    digest = exact_str(document["launch_record_sha256"])
    group = exact_str(document["log_group"])
    stream = exact_str(document["log_stream"])
    outcome_text = exact_str(document["outcome"])
    if (
        not identity
        or digest is None
        or _SHA256_RE.fullmatch(digest) is None
        or group is None
        or LOG_GROUP_RE.fullmatch(group) is None
        or stream is None
        or _LOG_STREAM_RE.fullmatch(stream) is None
        or outcome_text is None
        or outcome_text not in CollectionOutcome.__members__.values()
    ):
        raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
    outcome = CollectionOutcome(outcome_text)
    if type(document["scan_complete"]) is not bool:
        raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
    scan_complete: bool = document["scan_complete"]
    line = document["receipt_line"]
    rejection_text = document["rejection"]
    rejected_bytes = document["rejected_receipt_bytes"]
    collected = outcome is CollectionOutcome.COLLECTED
    rejected = outcome is CollectionOutcome.RECEIPT_REJECTED
    if collected != (line is not None) or rejected != (rejection_text is not None):
        raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
    if rejected != (rejected_bytes is not None):
        raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
    if (collected or rejected) and not scan_complete:
        raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
    if outcome is CollectionOutcome.SCAN_INCOMPLETE and scan_complete:
        raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
    if line is not None:
        if exact_str(line) is None:
            raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
        try:
            decode_receipt_line(line)
        except ReceiptError:
            raise _refuse(CollectionRecordDefect.RECORD_MALFORMED) from None
    rejection: ReceiptDefect | None = None
    if rejection_text is not None:
        text = exact_str(rejection_text)
        if text is None or text not in ReceiptDefect.__members__.values():
            raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
        rejection = ReceiptDefect(text)
        _count(rejected_bytes)
    return CollectionRecord(
        identity=identity,
        launch_record_sha256=digest,
        log_group=group,
        log_stream=stream,
        outcome=outcome,
        requests=_count(document["requests"]),
        pages=_count(document["pages"]),
        events_scanned=_count(document["events_scanned"]),
        distinct_receipt_lines=_count(document["distinct_receipt_lines"]),
        scan_complete=scan_complete,
        receipt_line=line,
        rejection=rejection,
        rejected_receipt_bytes=rejected_bytes,
        started_at=_instant(document["started_at"]),
        finished_at=_instant(document["finished_at"]),
        elapsed_ms=_count(document["elapsed_ms"]),
    )


def collection_record_sha256(document: dict[str, Any]) -> str:
    """The digest by which a disposition names one collection record (canonical bytes)."""
    return sha256_hex(canonical_bytes(document))


class ContradictionDisposition(StrEnum):
    """How a recorded contradiction was disposed. Closed: one member, one route."""

    HAND_READ_COMPLETION = "HAND_READ_COMPLETION"


_DISPOSITION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "contract_id",
        "identity",
        "launch_record_sha256",
        "contradiction_sha256",
        "receipt_line_sha256",
        "disposition",
        "recorded_at",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionDisposition:
    """One disposition: the contradiction record it names (by digest), the launch it belongs
    to, and the digest of the hand-read receipt line the owner completed from."""

    identity: str
    launch_record_sha256: str
    contradiction_sha256: str
    receipt_line_sha256: str
    disposition: ContradictionDisposition
    recorded_at: datetime

    def document(self) -> dict[str, Any]:
        return {
            "contract_id": DISPOSITION_CONTRACT_ID,
            "identity": self.identity,
            "launch_record_sha256": self.launch_record_sha256,
            "contradiction_sha256": self.contradiction_sha256,
            "receipt_line_sha256": self.receipt_line_sha256,
            "disposition": self.disposition.value,
            "recorded_at": self.recorded_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"CollectionDisposition(disposition={self.disposition.value!r})"


def is_collection_disposition(raw: object) -> bool:
    return type(raw) is dict and raw.get("contract_id") == DISPOSITION_CONTRACT_ID


def parse_collection_disposition(raw: object) -> CollectionDisposition:
    """The one closed reading of a disposition record, or ``CollectionRecordError``."""
    document: Any = raw
    if isinstance(raw, bytes | bytearray):
        try:
            document = decode_document(bytes(raw), max_bytes=MAX_COLLECTION_RECORD_BYTES)
        except Exception:
            raise _refuse(CollectionRecordDefect.RECORD_MALFORMED) from None
    if type(document) is not dict or set(document) != _DISPOSITION_FIELDS:
        raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
    if document["contract_id"] != DISPOSITION_CONTRACT_ID:
        raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
    identity = exact_str(document["identity"])
    digests = [exact_str(document[n]) for n in ("launch_record_sha256", "contradiction_sha256")]
    digests.append(exact_str(document["receipt_line_sha256"]))
    disposition_text = exact_str(document["disposition"])
    if (
        not identity
        or any(d is None or _SHA256_RE.fullmatch(d) is None for d in digests)
        or disposition_text is None
        or disposition_text not in ContradictionDisposition.__members__.values()
    ):
        raise _refuse(CollectionRecordDefect.RECORD_MALFORMED)
    return CollectionDisposition(
        identity=identity,
        launch_record_sha256=digests[0] or "",
        contradiction_sha256=digests[1] or "",
        receipt_line_sha256=digests[2] or "",
        disposition=ContradictionDisposition(disposition_text),
        recorded_at=_instant(document["recorded_at"]),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ContradictionStatus:
    """The recorded contradictions of one launch: the digests still unresolved, the digests
    a disposition already names, and the one receipt line (by digest) every disposition
    bound the launch to -- ``None`` while nothing is disposed."""

    unresolved: tuple[str, ...]
    disposed: tuple[str, ...]
    bound_receipt_sha256: str | None

    def admits_line(self, line: str) -> bool:
        """Whether a receipt line is the one the launch is bound to (or nothing binds it)."""
        return (
            self.bound_receipt_sha256 is None
            or sha256_hex(line.encode("utf-8", "surrogatepass")) == self.bound_receipt_sha256
        )

    def __repr__(self) -> str:
        return (
            f"ContradictionStatus(unresolved={len(self.unresolved)}, "
            f"disposed={len(self.disposed)}, bound={self.bound_receipt_sha256 is not None})"
        )


def _read_records(
    payloads: Iterable[bytes],
    *,
    identity: str,
    launch_record_sha256: str,
    destination: LogDestination | None,
    task_id: str | None,
) -> tuple[list[tuple[CollectionRecord, str]], list[CollectionDisposition]]:
    """Every collection record and every disposition about this identity, each held to the
    launch record digest (and, when a destination is given, to the derived stream)."""
    stream = (
        None if destination is None or task_id is None else log_stream_name(destination, task_id)
    )
    records: list[tuple[CollectionRecord, str]] = []
    dispositions: list[CollectionDisposition] = []
    for payload in payloads:
        try:
            document = decode_document(payload, max_bytes=MAX_COLLECTION_RECORD_BYTES)
        except Exception:  # noqa: S112 - undecodable: not a record about this launch
            continue
        if type(document) is not dict or document.get("identity") != identity:
            continue
        if is_collection_disposition(document):
            disposition = parse_collection_disposition(document)
            if disposition.launch_record_sha256 != launch_record_sha256:
                raise _refuse(CollectionRecordDefect.LAUNCH_MISMATCH)
            dispositions.append(disposition)
            continue
        if not is_collection_record(document):
            continue
        record = parse_collection_record(document)
        if record.launch_record_sha256 != launch_record_sha256:
            raise _refuse(CollectionRecordDefect.LAUNCH_MISMATCH)
        if stream is not None and (
            record.log_group != destination.log_group or record.log_stream != stream  # type: ignore[union-attr]
        ):
            raise _refuse(CollectionRecordDefect.DESTINATION_MISMATCH)
        records.append((record, collection_record_sha256(document)))
    records.sort(key=lambda item: (item[0].started_at, item[0].finished_at))
    return records, dispositions


def _contradiction_status(
    records: list[tuple[CollectionRecord, str]], dispositions: list[CollectionDisposition]
) -> ContradictionStatus:
    contradictions = {
        digest
        for record, digest in records
        if record.outcome is CollectionOutcome.CONTRADICTORY_RECEIPTS
    }
    named = {d.contradiction_sha256 for d in dispositions}
    if named - contradictions:
        raise _refuse(CollectionRecordDefect.DISPOSITION_UNBOUND)
    bound = {d.receipt_line_sha256 for d in dispositions}
    if len(bound) > 1:
        raise _refuse(CollectionRecordDefect.CONFLICTING_DISPOSITIONS)
    status = ContradictionStatus(
        unresolved=tuple(sorted(contradictions - named)),
        disposed=tuple(sorted(contradictions & named)),
        bound_receipt_sha256=next(iter(bound)) if bound else None,
    )
    # A kept line that is not the bound receipt is a substitution, whichever route reads
    # the records: refused here, before any read or completion mutation.
    for record, _digest in records:
        if record.receipt_line is not None and not status.admits_line(record.receipt_line):
            raise _refuse(CollectionRecordDefect.RECEIPT_SUBSTITUTED)
    return status


def contradiction_status(
    payloads: Iterable[bytes], *, identity: str, launch_record_sha256: str
) -> ContradictionStatus:
    """The hand-read completion's view: which recorded contradictions of this launch still
    need the owner's acknowledgement, which a disposition already names, and the receipt
    line the dispositions bound the launch to. Malformed or misbound records refuse; a
    disposition naming no recorded contradiction refuses; dispositions naming different
    receipts refuse."""
    records, dispositions = _read_records(
        payloads,
        identity=identity,
        launch_record_sha256=launch_record_sha256,
        destination=None,
        task_id=None,
    )
    return _contradiction_status(records, dispositions)


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionAdmission:
    """What the records about one launch establish: the one verified line to reuse (or
    none), and every admitted record, oldest window first."""

    reusable_line: str | None
    records: tuple[CollectionRecord, ...]
    #: The receipt line (by digest) a disposition bound the launch to: a resolution begun
    #: by a hand-read completion; only that line completes the launch, and a collection
    #: reads nothing while it stands.
    bound_receipt_sha256: str | None = None

    @property
    def attempts(self) -> int:
        return len(self.records)

    def __repr__(self) -> str:
        reusable = self.reusable_line is not None
        return f"CollectionAdmission(attempts={self.attempts}, reusable={reusable})"


def admit_collection_records(
    payloads: Iterable[bytes],
    *,
    identity: str,
    launch_record_sha256: str,
    destination: LogDestination,
    task_id: str,
    expectation: ReceiptExpectation,
) -> CollectionAdmission:
    """The one cache-admission rule both tools apply over every ``receipt-collection`` and
    ``collection-disposition`` file.

    A payload that is not a record about this identity is not this launch's evidence and
    is ignored (another launch's, or not a record). A record about this identity must parse
    closed (``RECORD_MALFORMED``), name this launch record's digest (``LAUNCH_MISMATCH``)
    and this launch's derived group and stream (``DESTINATION_MISMATCH``); a disposition
    must name a recorded contradiction (``DISPOSITION_UNBOUND``). **A recorded
    ``CONTRADICTORY_RECEIPTS`` without a disposition refuses** (``CONTRADICTION_UNRESOLVED``)
    -- no later collection, no earlier or later ``COLLECTED`` record and no ordering
    supersedes it. A disposed contradiction binds the launch to the receipt its
    disposition names (``bound_receipt_sha256``): a kept line that is not that receipt is
    ``RECEIPT_SUBSTITUTED``, and dispositions naming different receipts are
    ``CONFLICTING_DISPOSITIONS``. Otherwise a kept line must verify against the expectation
    (``RECEIPT_UNVERIFIABLE``); two different kept lines are ``CONTRADICTORY_RECORDS``.
    Nothing is chosen by filename order: every record is read, and the reusable line is
    the one line every ``COLLECTED`` record agrees on. Rejected, exhausted and incomplete
    attempts are history that never blocks a new collection.
    """
    records, dispositions = _read_records(
        payloads,
        identity=identity,
        launch_record_sha256=launch_record_sha256,
        destination=destination,
        task_id=task_id,
    )
    status = _contradiction_status(records, dispositions)
    if status.unresolved:
        raise _refuse(CollectionRecordDefect.CONTRADICTION_UNRESOLVED)
    kept: dict[str, None] = {}
    for record, _digest in records:
        if record.receipt_line is None:
            continue
        try:
            verify_receipt(decode_receipt_line(record.receipt_line), expectation=expectation)
        except ReceiptError:
            raise _refuse(CollectionRecordDefect.RECEIPT_UNVERIFIABLE) from None
        kept.setdefault(record.receipt_line, None)
    if len(kept) > 1:
        raise _refuse(CollectionRecordDefect.CONTRADICTORY_RECORDS)
    return CollectionAdmission(
        reusable_line=next(iter(kept)) if kept else None,
        records=tuple(record for record, _digest in records),
        bound_receipt_sha256=status.bound_receipt_sha256,
    )


class SdkLogsClient:
    """The logs operation over an injected client factory; structural error classification.

    The factory is the tool's (a profile-pinned session with one attempt in total); this
    class imports no SDK. A ``ClientError`` carries ``response``; a transport error is
    known by its type name; anything else is a failed page.
    """

    __slots__ = ("_client", "_client_for")

    def __init__(self, client_for: Callable[[str], Any]) -> None:
        self._client_for = client_for
        self._client: Any = None

    def __repr__(self) -> str:
        return "SdkLogsClient()"

    def get_log_events(
        self, *, log_group_name: str, log_stream_name: str, next_token: str | None
    ) -> LogPage:
        if self._client is None:
            self._client = self._client_for("logs")
        kwargs: dict[str, Any] = {
            "logGroupName": log_group_name,
            "logStreamName": log_stream_name,
            "startFromHead": True,
        }
        if next_token is not None:
            kwargs["nextToken"] = next_token
        try:
            response = self._client.get_log_events(**kwargs)
        except Exception as error:
            payload = getattr(error, "response", None)
            if isinstance(payload, dict):
                return LogPage(
                    status=payload.get("ResponseMetadata", {}).get("HTTPStatusCode"),
                    code=str(payload.get("Error", {}).get("Code", "")) or "Exception",
                )
            name = type(error).__name__
            if name in ("ConnectTimeoutError", "ReadTimeoutError"):
                return LogPage(status=None, transport_failure="timeout")
            if name == "EndpointConnectionError":
                return LogPage(status=None, transport_failure="network")
            return LogPage(status=None, code=name or "Exception")
        if not isinstance(response, dict):
            return LogPage(status=None, code="InvalidResponse")
        events = tuple(
            str(event.get("message", ""))
            for event in (response.get("events") or [])
            if isinstance(event, dict)
        )
        forward = response.get("nextForwardToken")
        return LogPage(
            status=response.get("ResponseMetadata", {}).get("HTTPStatusCode"),
            events=events,
            next_forward_token=str(forward) if isinstance(forward, str) and forward else None,
        )


__all__ = [
    "COLLECTION_CONTRACT_ID",
    "COLLECT_CEILING_SECONDS",
    "COLLECT_MAX_EVENTS",
    "COLLECT_MAX_PAGES",
    "COLLECT_MAX_REQUESTS",
    "COLLECT_POLL_SECONDS",
    "CONTAINER_OF_ENTRY",
    "DISPOSITION_CONTRACT_ID",
    "LOGS_RETRY_MODE",
    "LOGS_TOTAL_MAX_ATTEMPTS",
    "LOG_GROUP_RE",
    "MAX_COLLECTION_RECORD_BYTES",
    "STREAM_PREFIX_OF_ENTRY",
    "CollectedReceipt",
    "CollectionAdmission",
    "CollectionDisposition",
    "CollectionOutcome",
    "CollectionRecord",
    "CollectionRecordDefect",
    "CollectionRecordError",
    "CollectorDefect",
    "CollectorError",
    "ContradictionDisposition",
    "ContradictionStatus",
    "LogDestination",
    "LogPage",
    "LogsClient",
    "SdkLogsClient",
    "admit_collection_records",
    "collect_receipt",
    "collection_record_sha256",
    "contradiction_status",
    "destination_for",
    "is_collection_disposition",
    "is_collection_record",
    "log_stream_name",
    "parse_collection_disposition",
    "parse_collection_record",
    "parse_log_destination",
]
