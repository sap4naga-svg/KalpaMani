"""Synthetic fixtures for the Sharadar provider boundary.

**Entirely hand-authored and fictitious.** No vendor row, no vendor worked
example, no sampled response and nothing from the private qualification appears
here or is reachable from here. The tickers are invented and are not listed
securities; the payloads are opaque byte strings that were never a CSV, because
Bronze publication treats a payload as bytes and parsing one would be testing a
thing this slice does not do.

**The credential values are unmistakably fake and say so in the value itself.**
The vendor's published test token is deliberately *not* used: it belongs to the
manual qualification harness under ``scripts/``, and letting it appear on the
production surface is how a key literal becomes ordinary.

The transports here are the only "network" any test touches. They open no socket,
resolve no name and know no host -- they return what a test queued and record what
they were asked for.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime

from kalpamani.data.ingest.sharadar.credentials import SharadarCredential
from kalpamani.data.ingest.sharadar.datasets import (
    DateWindow,
    Page,
    ResponseFormat,
    SharadarDataset,
    SharadarRequest,
)
from kalpamani.data.ingest.sharadar.transport import (
    TransportResponse,
    TransportUnavailableError,
)

#: A fake credential whose value announces that it is fake.
SYNTHETIC_CREDENTIAL_VALUE = "synthetic-fake-not-a-real-sharadar-key-0001"

#: A second one, so a test can prove that redaction is not matching one literal.
OTHER_SYNTHETIC_CREDENTIAL_VALUE = "synthetic-fake-not-a-real-sharadar-key-0002"

#: An invented symbol. Not a listed security, and chosen so it cannot collide.
SYNTHETIC_TICKER = "ZZQA"

#: Opaque synthetic payloads. Two of them differ by exactly one byte, which is what
#: makes "a changed payload is a new content address" falsifiable rather than
#: merely asserted.
SYNTHETIC_PAYLOAD = b"synthetic-opaque-provider-payload-0001"
SYNTHETIC_PAYLOAD_ONE_BYTE_DIFFERENT = b"synthetic-opaque-provider-payload-0002"

#: A fixed instant. Nothing in these fixtures reads a clock, so two runs of the
#: suite produce byte-identical records and therefore identical content addresses.
RETRIEVED_AT = datetime(2026, 8, 28, 13, 45, 0, tzinfo=UTC)

SOURCE_SCHEMA_VERSION = "synthetic-schema-v0"
INGESTION_RUN_ID = "synthetic-run-0001"


def credential(value: str = SYNTHETIC_CREDENTIAL_VALUE) -> SharadarCredential:
    """A credential holding an unmistakably fake value."""
    return SharadarCredential(value)


def window(start: date = date(2021, 8, 28), end: date = date(2026, 8, 27)) -> DateWindow:
    """An explicit five-year window. Stated, never defaulted."""
    return DateWindow(start=start, end=end)


def page(limit: int = 500, skip: int = 0) -> Page:
    """Explicit pagination, well below the vendor's silent 10000-row ceiling."""
    return Page(limit=limit, skip=skip)


def stocks_request(
    *,
    ticker: str = SYNTHETIC_TICKER,
    response_format: ResponseFormat = ResponseFormat.CSV,
) -> SharadarRequest:
    """A windowed daily-price request."""
    return SharadarRequest(
        dataset=SharadarDataset.STOCKS,
        ticker=ticker,
        response_format=response_format,
        page=page(),
        window=window(),
    )


def actions_request(ticker: str = SYNTHETIC_TICKER) -> SharadarRequest:
    """A windowed corporate-actions request."""
    return SharadarRequest(
        dataset=SharadarDataset.ACTIONS,
        ticker=ticker,
        response_format=ResponseFormat.CSV,
        page=page(),
        window=window(),
    )


def tickers_request(ticker: str = SYNTHETIC_TICKER) -> SharadarRequest:
    """A snapshot security-metadata request. No window, because there is no time axis."""
    return SharadarRequest(
        dataset=SharadarDataset.TICKERS,
        ticker=ticker,
        response_format=ResponseFormat.CSV,
        page=page(),
        window=None,
    )


class ManualClock:
    """A clock that advances only when the injected sleeper is called.

    Pacing and backoff are then provable without spending the wall-clock time
    they describe -- and a test that took ten seconds to prove a ten-second backoff
    is a test that eventually gets deleted.
    """

    def __init__(self, start: float = 0.0) -> None:
        """Start at ``start`` with nothing slept."""
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        """The current fake monotonic reading."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Record the sleep and advance the clock by exactly that much."""
        self.sleeps.append(seconds)
        self.now += seconds


class ScriptedTransport:
    """Returns queued outcomes in order, and records what it was asked for.

    A queued :class:`~kalpamani.data.ingest.sharadar.transport.TransportUnavailableError`
    is raised rather than returned, which is how a network-level failure is
    expressed at this boundary.

    It holds no host, opens no socket and resolves no name. Its only external
    effect is appending to its own lists.
    """

    def __init__(self, outcomes: Sequence[TransportResponse | TransportUnavailableError]) -> None:
        """Queue ``outcomes``, oldest first."""
        self._outcomes = list(outcomes)
        self.urls: list[str] = []
        self.headers: list[Mapping[str, str]] = []
        self.timeouts: list[float] = []

    @property
    def call_count(self) -> int:
        """How many times the transport was asked for a response."""
        return len(self.urls)

    def get(
        self, *, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> TransportResponse:
        """Return (or raise) the next queued outcome, recording the call."""
        self.urls.append(url)
        self.headers.append(dict(headers))
        self.timeouts.append(timeout_seconds)
        if not self._outcomes:
            raise AssertionError("the scripted transport ran out of queued outcomes")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, TransportUnavailableError):
            raise outcome
        return outcome


def ok(payload: bytes = SYNTHETIC_PAYLOAD) -> TransportResponse:
    """A successful response carrying ``payload``."""
    return TransportResponse(status=200, body=payload)


def failing(status: int) -> TransportResponse:
    """A failing response with an empty body, as the real transport produces."""
    return TransportResponse(status=status, body=b"")


__all__ = [
    "INGESTION_RUN_ID",
    "OTHER_SYNTHETIC_CREDENTIAL_VALUE",
    "RETRIEVED_AT",
    "SOURCE_SCHEMA_VERSION",
    "SYNTHETIC_CREDENTIAL_VALUE",
    "SYNTHETIC_PAYLOAD",
    "SYNTHETIC_PAYLOAD_ONE_BYTE_DIFFERENT",
    "SYNTHETIC_TICKER",
    "ManualClock",
    "ScriptedTransport",
    "actions_request",
    "credential",
    "failing",
    "ok",
    "page",
    "stocks_request",
    "tickers_request",
    "window",
]
