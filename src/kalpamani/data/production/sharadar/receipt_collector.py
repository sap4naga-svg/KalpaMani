"""The bounded receipt collector (proposed ADR-0049 s.2; the collection ADR-0044 s.4 deferred).

A task's receipt is one closed line on its log stream. Until now the owner hand-read it and
handed it to the tools (``--receipt-lines``). The collector reads it **from the exact stream
the launch record and the registered task-definition evidence name** -- the research log
group and the stream prefix the owner transcribed from the applied revision, the container
the entry runs in, and the launch record's own task id -- and hands the line to **the same
verifier and the same completion** the hand-read path uses. A caller supplies no stream;
nothing here is a second route to a completed row or a PASSED subcell.

Bounded, and what its bounds mean:

- **request limits** -- at most :data:`COLLECT_MAX_PAGES` ``GetLogEvents`` pages per pass and
  :data:`COLLECT_MAX_REQUESTS` requests per collection, each page the service's own ceiling
  (10,000 events or 1 MiB); at most :data:`COLLECT_MAX_EVENTS` events scanned; polling for
  delayed delivery at :data:`COLLECT_POLL_SECONDS` for at most :data:`COLLECT_CEILING_SECONDS`
  on an injected monotonic clock;
- **effective SDK retries: zero** -- the logs client is built with one attempt in total
  (``total_max_attempts = 1``); a throttled or failed request is recorded, never retried
  inside the SDK, and the collector itself re-issues nothing within a pass;
- **a successful read is not a verification** -- a collected line still has to verify against
  the launch record's expectation (task, revision, image, identity, input, configuration,
  commit) and against the observed terminal exit, exactly as a hand-read one;
- **an exhausted budget proves that no receipt was obtained within it**, not that none exists:
  ``NO_RECEIPT_WITHIN_BUDGET`` and ``STREAM_NOT_FOUND_WITHIN_BUDGET`` are collection
  outcomes, never receipt verdicts, and a later collection may still find the line.

Only the receipt line is kept (it is the closed receipt document: tokens, counts, digests --
no key, identifier, subject or row); every other event is counted and never stored, so no
arbitrary log content leaves the stream through this module. Real client construction lives
in the tools' authorized branches; this module imports no SDK.

**Mocked results are not AWS verification.** Every page in this repository's tests is a fake's.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Protocol

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar.documents import exact_str
from kalpamani.data.production.sharadar.entry import TaskEntry
from kalpamani.data.production.sharadar.receipts import RECEIPT_LINE_PREFIX

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

    COLLECTED = "COLLECTED"
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
    """The sanitized result of one collection: the outcome, the counts and, when exactly one
    distinct receipt line was found, that line -- the closed receipt document, nothing else."""

    outcome: CollectionOutcome
    log_group: str
    log_stream: str
    requests: int
    pages: int
    events_scanned: int
    distinct_receipt_lines: int
    receipt_line: str | None
    started_at: datetime
    finished_at: datetime

    def __post_init__(self) -> None:
        if (self.outcome is CollectionOutcome.COLLECTED) != (self.receipt_line is not None):
            raise ValueError("a receipt line is present exactly when one was collected")
        if self.receipt_line is not None and not self.receipt_line.startswith(RECEIPT_LINE_PREFIX):
            raise ValueError("a collected line is a receipt line")

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
            "receipt_line": self.receipt_line,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
        }

    def digest(self, *, identity: str, launch_record_sha256: str) -> str:
        return sha256_hex(
            canonical_bytes(
                self.document(identity=identity, launch_record_sha256=launch_record_sha256)
            )
        )

    def __repr__(self) -> str:
        return f"CollectedReceipt(outcome={self.outcome.value!r}, requests={self.requests})"


def collect_receipt(
    *,
    destination: LogDestination,
    task_id: str,
    client: LogsClient,
    now: Callable[[], datetime],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
) -> CollectedReceipt:
    """Read the task's stream for its one receipt line, bounded; never verify it here.

    Pages are read from the head with the forward token; a page whose token equals the
    one it was asked with is the end of the stream as delivered so far (the documented
    signal), and every further poll continues from that token. Delivery lag is waited out
    at the poll interval within the ceiling; a stream not yet created is the same wait. A
    denial, a throttle or a transport failure ends the collection at once with its own
    outcome -- the SDK retried nothing, and the collector retries nothing. Two distinct
    receipt lines are contradictory and refuse; the same line delivered twice is one line.
    Exhaustion says only that nothing was obtained within the budget.
    """
    stream = log_stream_name(destination, task_id)
    started_at = now()
    started = monotonic()
    token: str | None = None
    requests = pages = scanned = 0
    seen: dict[str, None] = {}
    outcome: CollectionOutcome | None = None

    def finish(final: CollectionOutcome) -> CollectedReceipt:
        line = next(iter(seen)) if final is CollectionOutcome.COLLECTED else None
        return CollectedReceipt(
            outcome=final,
            log_group=destination.log_group,
            log_stream=stream,
            requests=requests,
            pages=pages,
            events_scanned=scanned,
            distinct_receipt_lines=len(seen),
            receipt_line=line,
            started_at=started_at,
            finished_at=now(),
        )

    while True:
        # One pass: pages from the current token until the token repeats or a bound holds.
        stream_absent = False
        for _ in range(COLLECT_MAX_PAGES):
            if requests >= COLLECT_MAX_REQUESTS:
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
            for message in page.events:
                scanned += 1
                if type(message) is str and message.startswith(RECEIPT_LINE_PREFIX):
                    seen.setdefault(message, None)
            repeated = page.next_forward_token is None or page.next_forward_token == token
            token = page.next_forward_token if page.next_forward_token is not None else token
            if repeated or scanned >= COLLECT_MAX_EVENTS:
                break
        if outcome is not None:
            return finish(outcome)
        if len(seen) == 1:
            return finish(CollectionOutcome.COLLECTED)
        if len(seen) > 1:
            return finish(CollectionOutcome.CONTRADICTORY_RECEIPTS)
        exhausted = (
            requests >= COLLECT_MAX_REQUESTS
            or scanned >= COLLECT_MAX_EVENTS
            or max(0.0, monotonic() - started) + COLLECT_POLL_SECONDS > COLLECT_CEILING_SECONDS
        )
        if exhausted:
            return finish(
                CollectionOutcome.STREAM_NOT_FOUND_WITHIN_BUDGET
                if stream_absent
                else CollectionOutcome.NO_RECEIPT_WITHIN_BUDGET
            )
        sleep(COLLECT_POLL_SECONDS)


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
    "LOGS_RETRY_MODE",
    "LOGS_TOTAL_MAX_ATTEMPTS",
    "LOG_GROUP_RE",
    "STREAM_PREFIX_OF_ENTRY",
    "CollectedReceipt",
    "CollectionOutcome",
    "CollectorDefect",
    "CollectorError",
    "LogDestination",
    "LogPage",
    "LogsClient",
    "SdkLogsClient",
    "collect_receipt",
    "destination_for",
    "log_stream_name",
    "parse_log_destination",
]
