"""Synthetic fixtures for the private empirical qualification package.

**Everything here is hand-authored and fictitious.** No vendor row, no vendor
worked example, no sampled response and nothing from any private evaluation appears
here or is reachable from here.

**The subjects are unmistakably fictional and are not listed securities.** They are
shaped ``ZZ-SYNTH-NN``, which satisfies the accepted subject grammar while being a
form no US listing uses. The real eight-subject inventory is an owner-only,
git-ignored file that **must never exist in a test**, so every fixture here builds a
synthetic one in memory and the real loader is exercised only through a temporary
path a test created itself.

**The CSV payloads are invented.** They carry the column names the vendor documents
in prose, because the parser's contract is written against those names -- and they
carry invented values, because a value is a vendor row and a vendor row may not be
in this repository.

**No socket, no AWS SDK, no credential, no bucket and no clock read appears here.**
The fake S3 client is a dictionary with the same conditional-write and metadata
semantics the real backend enforces.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

from fixtures.sharadar_provider import credential
from kalpamani.data.contracts.canonical import sha256_hex
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.qualify.sharadar.inventory import (
    CANONICAL_SUBJECT_CLASSES,
    INVENTORY_SCHEMA_VERSION,
    PrivateInventory,
    parse_private_inventory,
)

__all__ = [
    "ACTIONS_CSV",
    "EMPTY_PAGE_CSV",
    "EXECUTION_ID",
    "EXECUTION_ID_A",
    "EXECUTION_ID_B",
    "LEAK_CANARIES",
    "RUN_B_INSTANT",
    "RUN_INSTANT",
    "RUN_SEPARATION_DAYS",
    "STOCKS_CSV",
    "SYNTHETIC_BUCKET",
    "SYNTHETIC_SUBJECTS",
    "TICKERS_CSV",
    "FakeMonotonic",
    "FakeS3Client",
    "FixedClock",
    "PagedTransport",
    "client_error",
    "credential",
    "csv_for",
    "inventory_document",
    "synthetic_inventory",
]

#: Eight invented symbols, one per accepted subject class. Not listed securities,
#: and shaped so they cannot collide with one.
SYNTHETIC_SUBJECTS: tuple[str, ...] = tuple(f"ZZ-SYNTH-{index:02d}" for index in range(1, 9))

#: A synthetic bucket name that announces it is not real.
SYNTHETIC_BUCKET = "synthetic-fake-not-a-real-bucket"

#: A fixed instant. Nothing here reads a wall clock, so two runs of the suite build
#: byte-identical records and therefore identical content addresses.
RUN_INSTANT = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)

#: Two explicit execution identities, one per acquisition run. There is no default
#: anywhere, which is the point. ``EXECUTION_ID`` is the Run A spelling, kept because
#: every single-execution fixture in the suite already names it.
EXECUTION_ID_A = "synthetic-empirical-a"
EXECUTION_ID_B = "synthetic-empirical-b"
EXECUTION_ID = EXECUTION_ID_A

#: How far apart the two synthetic runs are, in calendar days. One more than the
#: accepted minimum, so a test that tightens the rule by a day still passes and a
#: test that needs a *refused* separation has to say so explicitly.
RUN_SEPARATION_DAYS = 9

#: Run B's fixed instant, nine calendar days after Run A's.
RUN_B_INSTANT = RUN_INSTANT + timedelta(days=RUN_SEPARATION_DAYS)

#: Text that must never escape into a public outcome, a refusal or a report. Each
#: value is placed somewhere a dependency could leak it, so a test that finds none of
#: them has proven the sanitisation rather than asserted it.
LEAK_CANARIES = (
    "api_key=",
    "synthetic-fake-not-a-real-sharadar-key",
    "https://",
    "api.sharadar.com",
    SYNTHETIC_BUCKET,
    "amazonaws.com",
    *SYNTHETIC_SUBJECTS,
)

#: Invented CSV bodies carrying the documented column names and invented values.
TICKERS_CSV = (
    b"ticker,permaticker,isdelisted,firstpricedate,lastpricedate,category\n"
    b"ZZ-SYNTH-01,900001,N,1998-01-05,2026-08-28,Domestic Common Stock\n"
)
STOCKS_CSV = (
    b"ticker,date,open,high,low,close,closeadj,closeunadj,volume,lastupdated\n"
    b"ZZ-SYNTH-01,1998-01-05,10.00,10.50,9.75,10.25,5.125,10.25,100000,2026-08-29\n"
    b"ZZ-SYNTH-01,1998-01-06,10.25,10.75,10.00,10.50,5.250,10.50,120000,2026-08-29\n"
)
ACTIONS_CSV = (
    b"date,action,ticker,name,value,contraticker,contraname\n"
    b"2011-06-09,split,ZZ-SYNTH-01,Synthetic Holdings,2.0,,\n"
    b"2012-02-08,dividend,ZZ-SYNTH-01,Synthetic Holdings,0.38,,\n"
    b"2015-07-01,spinoff,ZZ-SYNTH-01,Synthetic Holdings,0.25,ZZ-SYNTH-03,Synthetic Spun\n"
)

#: A header-only page. **Valid, and not a fault**: a delisted name queried outside
#: its listing life legitimately returns no rows, and it is also the completeness
#: probe's expected answer.
EMPTY_PAGE_CSV = b"ticker,permaticker,isdelisted,firstpricedate,lastpricedate,category\n"

_CSV_BY_DATASET: dict[SharadarDataset, bytes] = {
    SharadarDataset.TICKERS: TICKERS_CSV,
    SharadarDataset.STOCKS: STOCKS_CSV,
    SharadarDataset.ACTIONS: ACTIONS_CSV,
}

#: The header-only counterpart of each body, for the second page of every pair.
_EMPTY_BY_DATASET: dict[SharadarDataset, bytes] = {
    dataset: body.split(b"\n", 1)[0] + b"\n" for dataset, body in _CSV_BY_DATASET.items()
}


def csv_for(dataset: SharadarDataset, *, subject: str, page_skip: int) -> bytes:
    """One synthetic page body for a subject and dataset.

    The subject is substituted into the invented rows so two subjects produce
    different bytes -- which is what makes "one request, one durable acquisition"
    falsifiable rather than accidentally true because every payload was identical.

    The second page is header-only, which is the completeness probe's expected
    answer and the shape a complete first page implies.
    """
    if page_skip:
        return _EMPTY_BY_DATASET[dataset]
    return _CSV_BY_DATASET[dataset].replace(b"ZZ-SYNTH-01", subject.encode("ascii"))


def inventory_document(subjects: tuple[str, ...] = SYNTHETIC_SUBJECTS) -> dict[str, Any]:
    """A well-formed inventory document, one subject per accepted class."""
    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "subjects": [
            {"subject_class": name.value, "ticker": ticker}
            for name, ticker in zip(CANONICAL_SUBJECT_CLASSES, subjects, strict=True)
        ],
    }


def synthetic_inventory(subjects: tuple[str, ...] = SYNTHETIC_SUBJECTS) -> PrivateInventory:
    """A validated inventory built in memory. **No file is created or read.**"""
    return parse_private_inventory(inventory_document(subjects))


class FixedClock:
    """A clock that always answers the same aware instant."""

    def __init__(self, instant: datetime = RUN_INSTANT) -> None:
        """Bind the instant this clock always reports."""
        self._instant = instant

    def now(self) -> datetime:
        """The fixed instant."""
        return self._instant


class FakeMonotonic:
    """A monotonic clock a test drives, and the sleeper that advances it.

    Real monotonic time is exactly what a deadline test must not wait for. This
    advances only when something advances it -- a sleep, a scripted per-operation
    cost, or an explicit :meth:`advance` -- so an 1,800-second budget is exercised in
    microseconds and the arithmetic under test is the real arithmetic.

    **It is not a calendar.** It has no date, no timezone and no relationship to
    ``datetime``, which is the property the deadline depends on.
    """

    __slots__ = ("reading", "sleep_calls")

    def __init__(self, start: float = 0.0) -> None:
        """Start the reading, with no sleeps recorded."""
        self.reading = start
        self.sleep_calls: list[float] = []

    def __call__(self) -> float:
        """The current reading. Never decreases unless a test makes it."""
        return self.reading

    def sleep(self, seconds: float) -> None:
        """Advance the reading by ``seconds``, and record the call."""
        self.sleep_calls.append(float(seconds))
        self.reading += float(seconds)

    def advance(self, seconds: float) -> None:
        """Advance the reading without recording a sleep."""
        self.reading += float(seconds)


class PagedTransport:
    """Returns a synthetic CSV page per request, and records what it was asked for.

    It holds no host, opens no socket and resolves no name. The response body is
    chosen from the query string's own ``ticker`` and ``skip`` values, so a plan that
    walked its pages wrongly produces visibly wrong bytes rather than passing.
    """

    def __init__(
        self,
        *,
        max_response_bytes: int = 4 * 1024 * 1024,
        fail_after: int = -1,
        body_override: bytes | None = None,
        monotonic: FakeMonotonic | None = None,
        seconds_per_request: float = 0.0,
    ) -> None:
        """Declare a ceiling, optionally fail after ``fail_after``, optionally
        return one fixed body for every request.

        ``body_override`` exists so a test can publish a payload the parser must
        refuse **through the real acquisition path**, which keeps every digest,
        record and locator entry mutually consistent. Editing a stored object
        afterwards would trip the integrity check instead, and prove nothing
        about the parser.
        """
        self._max_response_bytes = max_response_bytes
        self._fail_after = fail_after
        self._body_override = body_override
        self._monotonic = monotonic
        self._seconds_per_request = float(seconds_per_request)
        self.urls: list[str] = []

    @property
    def max_response_bytes(self) -> int:
        """What a real transport declares, so a client budgets the same way."""
        return self._max_response_bytes

    @property
    def call_count(self) -> int:
        """How many times the transport was asked for a response."""
        return len(self.urls)

    def get(self, *, url: str, headers: Any, timeout_seconds: float) -> Any:
        """Return a synthetic page chosen from the request's own parameters."""
        from kalpamani.data.ingest.sharadar.transport import (
            TransportResponse as Response,
        )
        from kalpamani.data.ingest.sharadar.transport import (
            TransportUnavailableError,
        )

        self.urls.append(url)
        if self._monotonic is not None and self._seconds_per_request:
            # A request that really took time, so a deadline test measures the same
            # thing production would: elapsed monotonic seconds, not a call count.
            self._monotonic.advance(self._seconds_per_request)
        if 0 <= self._fail_after < len(self.urls):
            from kalpamani.data.ingest.sharadar.redaction import SharadarErrorCode

            raise TransportUnavailableError(SharadarErrorCode.REQUEST_MALFORMED)

        dataset = SharadarDataset.TICKERS
        for candidate in SharadarDataset:
            if f"/{candidate.value}?" in url or f"/{candidate.value}/" in url:
                dataset = candidate
                break
        subject = next((name for name in SYNTHETIC_SUBJECTS if name in url), SYNTHETIC_SUBJECTS[0])
        skip = 0
        for fragment in url.split("&"):
            if fragment.startswith("skip="):
                skip = int(fragment.removeprefix("skip="))
        if self._body_override is not None:
            return Response(status=200, body=self._body_override)
        return Response(status=200, body=csv_for(dataset, subject=subject, page_skip=skip))


class FakeS3Client:
    """A dictionary with the conditional-write semantics the real backend enforces.

    ``put_object`` honours ``IfNoneMatch="*"``, answering ``412`` for an occupied
    name; ``head_object`` answers a ``FULL_OBJECT`` SHA-256 and a content length;
    ``get_object`` returns a readable body. It counts nothing itself -- the counting
    wrapper under test does that, which is what makes the counts a measurement of the
    wrapper rather than of the fixture.

    **There is deliberately no ``list_objects_v2``, ``delete_object`` or
    ``copy_object``**, so a test cannot accidentally prove a capability that must not
    exist.
    """

    def __init__(
        self,
        *,
        fail_puts: dict[str, Exception] | None = None,
        monotonic: FakeMonotonic | None = None,
        seconds_per_operation: float = 0.0,
    ) -> None:
        """Start empty, optionally scripted to fail keys or to cost elapsed time."""
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[str] = []
        self.head_calls: list[str] = []
        self.get_calls: list[str] = []
        self._fail_puts = dict(fail_puts or {})
        self._monotonic = monotonic
        self._seconds_per_operation = float(seconds_per_operation)

    def _spend(self) -> None:
        """Advance the injected monotonic clock by this operation's scripted cost."""
        if self._monotonic is not None and self._seconds_per_operation:
            self._monotonic.advance(self._seconds_per_operation)

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        """Conditionally store one object, or raise the scripted failure."""
        key = kwargs["Key"]
        self.put_calls.append(key)
        self._spend()
        scripted = self._fail_puts.get(key)
        if scripted is not None:
            raise scripted
        if kwargs.get("IfNoneMatch") == "*" and key in self.objects:
            raise _client_error("PreconditionFailed")
        self.objects[key] = kwargs["Body"]
        return {"ETag": "synthetic"}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        """Answer metadata for a stored object, or raise a not-found error."""
        key = kwargs["Key"]
        self.head_calls.append(key)
        self._spend()
        if key not in self.objects:
            raise _client_error("404")
        payload = self.objects[key]
        return {
            "ChecksumType": "FULL_OBJECT",
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(sha256_hex(payload))).decode("ascii"),
            "ContentLength": len(payload),
        }

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        """Return a readable body for a stored object, or raise a not-found error."""
        key = kwargs["Key"]
        self.get_calls.append(key)
        if key not in self.objects:
            raise _client_error("NoSuchKey")
        return {"Body": _Body(self.objects[key]), "ContentLength": len(self.objects[key])}


class _Body:
    """A minimal readable stream over fixed bytes."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0

    def read(self, size: int = -1) -> bytes:
        """Return up to ``size`` bytes, advancing the offset."""
        if size < 0:
            chunk = self._payload[self._offset :]
            self._offset = len(self._payload)
            return chunk
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def client_error(code: str) -> Exception:
    """An exception shaped the way the backend classifier reads one.

    Public, because a test that wants to drive a *classified* backend failure has
    to raise something the real classifier can read. Raising an already-classified
    refusal instead would bypass the classifier and prove nothing about it.
    """
    return _client_error(code)


def _client_error(code: str) -> Exception:
    """An exception shaped the way the backend classifier reads one."""

    class _ClientError(Exception):
        def __init__(self) -> None:
            super().__init__(f"synthetic {code}")
            self.response = {"Error": {"Code": code}}

    return _ClientError()
