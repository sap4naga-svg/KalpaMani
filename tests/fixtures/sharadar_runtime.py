"""Synthetic fixtures for the Sharadar qualification runtime. **Nothing here is real.**

Every subject is invented and is not a listed security. Every payload is an opaque
byte string that was never a CSV, because the runtime treats a payload as bytes
and parsing one would be testing something this slice does not do. No vendor row,
worked example, sampled response or private qualification output appears here or
is reachable from here.

The clock is fixed, so two runs of the suite produce byte-identical acquisition
records and therefore identical content addresses. The recording store is an
in-memory dictionary with the same admission and collision rules the real one
enforces -- it is built on the shipped in-memory backend rather than reimplementing
those rules, so a test cannot pass against a store that is wrong about them.

**No socket, no AWS SDK, no credential and no bucket appears anywhere in this
file.**
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from fixtures.sharadar_provider import ManualClock, ScriptedTransport, credential
from kalpamani.data.ingest.sharadar.client import Pacer, RetryPolicy, SharadarClient
from kalpamani.data.ingest.sharadar.datasets import DateWindow, SharadarDataset
from kalpamani.data.ingest.sharadar.qualification import (
    DatasetPlan,
    QualificationLimits,
    QualificationPlan,
    QualificationSubject,
)
from kalpamani.data.ingest.sharadar.transport import (
    DEFAULT_MAX_RESPONSE_BYTES,
    TransportResponse,
    TransportUnavailableError,
)
from kalpamani.data.objectstore import (
    InMemoryResearchObjectStore,
    ObjectKey,
    PutOutcome,
)

#: Invented symbols. None is a listed security, and each is shaped so it cannot
#: collide with one.
SUBJECT_A = "ZZQA"
SUBJECT_B = "ZZQB"
SUBJECT_C = "ZZQC"

#: Opaque synthetic payloads, one per planned request in the common fixtures.
PAYLOAD_A = b"synthetic-opaque-qualification-payload-0001"
PAYLOAD_B = b"synthetic-opaque-qualification-payload-0002"
PAYLOAD_C = b"synthetic-opaque-qualification-payload-0003"

#: A fixed instant. Nothing here reads a wall clock.
RUN_INSTANT = datetime(2026, 8, 28, 15, 30, 0, tzinfo=UTC)

#: Two explicit execution identities. There is **no default** on the plan, so a
#: fixture that wants one has to name it -- which is the point.
EXECUTION_ID = "synthetic-exec-0001"
OTHER_EXECUTION_ID = "synthetic-exec-0002"
SCHEMA_VERSION = "synthetic-qualification-schema-v0"

#: Text that must never escape into a runtime error or a run result. Every value
#: appears somewhere a dependency could leak it, so a test that finds none of them
#: has proven the sanitisation rather than asserted it.
LEAK_CANARIES = (
    "api_key=",
    "synthetic-fake-not-a-real-sharadar-key",
    "https://",
    "api.sharadar.com",
    "synthetic-fake-not-a-real-bucket",
    "amazonaws.com",
    "SYNTHETICFAKEREQ0001",
)


class FixedClock:
    """A clock that always answers the same aware instant."""

    def __init__(self, instant: datetime = RUN_INSTANT) -> None:
        """Answer ``instant`` on every call."""
        self.instant = instant
        self.calls = 0

    def now(self) -> datetime:
        """The fixed instant, recording that it was asked."""
        self.calls += 1
        return self.instant


class BadClock:
    """A clock that answers something that is not an aware datetime."""

    def __init__(self, answer: object = None) -> None:
        """Answer ``answer``, whatever it is."""
        self.answer = answer

    def now(self) -> object:
        """Whatever this clock was built with."""
        return self.answer


class RaisingClock:
    """A clock that raises, carrying text that must not escape."""

    def now(self) -> datetime:
        """Raise something leaky."""
        raise RuntimeError("api_key=synthetic-fake-not-a-real-sharadar-key-0001 at https://x")


class RecordingStore:
    """The shipped in-memory store, wrapped so a test can see what was asked.

    Wrapping rather than reimplementing matters: admission, content addressing,
    idempotency and collision refusal are the real ones, so a runtime test cannot
    pass against a store that is wrong about them.
    """

    def __init__(self) -> None:
        """An empty store with an empty call log."""
        self._store = InMemoryResearchObjectStore()
        self.put_keys: list[str] = []

    def put_if_absent(self, *, key: ObjectKey, payload: bytes) -> PutOutcome:
        """Record the logical key, then delegate."""
        self.put_keys.append(key.logical_key)
        return self._store.put_if_absent(key=key, payload=payload)

    def exists(self, *, key: ObjectKey) -> bool:
        """Delegate."""
        return self._store.exists(key=key)

    @property
    def call_count(self) -> int:
        """How many publications were attempted."""
        return len(self.put_keys)


class RefusingStore:
    """A store that raises the given exception on every publication."""

    def __init__(self, error: BaseException) -> None:
        """Raise ``error`` from every ``put_if_absent``."""
        self.error = error
        self.call_count = 0

    def put_if_absent(self, *, key: ObjectKey, payload: bytes) -> PutOutcome:
        """Raise."""
        self.call_count += 1
        raise self.error

    def exists(self, *, key: ObjectKey) -> bool:
        """Never reached in these tests."""
        return False


class LeakyClient:
    """A stand-in that is not a ``SharadarClient``. Used to prove the type check."""

    max_attempts = 1

    def fetch(self, request: object) -> bytes:
        """Never reached: the runtime refuses this object at construction."""
        raise AssertionError("a non-exact client must never be called")


def client(
    outcomes: Sequence[TransportResponse | TransportUnavailableError],
    *,
    max_attempts: int = 1,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> tuple[SharadarClient, ScriptedTransport]:
    """A real client wired to a scripted transport and a manual clock.

    The client is genuine -- pacing, retries, redaction and the exact-type checks
    are the shipped ones. Only the transport is synthetic, and it opens no socket.
    """
    transport = ScriptedTransport(outcomes, max_response_bytes=max_response_bytes)
    manual = ManualClock()
    policy = RetryPolicy(
        max_attempts=max_attempts, backoff_seconds=tuple(1.0 for _ in range(max_attempts - 1))
    )
    built = SharadarClient(
        credential=credential(),
        transport=transport,
        pacer=Pacer(min_interval=0.0, clock=manual.time, sleeper=manual.sleep),
        retry_policy=policy,
    )
    return built, transport


def window(start: date = date(2024, 1, 2), end: date = date(2024, 3, 28)) -> DateWindow:
    """An explicit window. Stated, never defaulted."""
    return DateWindow(start=start, end=end)


def subjects(*tickers: str) -> tuple[QualificationSubject, ...]:
    """Explicit subjects, in the order given."""
    return tuple(QualificationSubject(ticker) for ticker in tickers)


def snapshot_plan(*tickers: str, **overrides: object) -> QualificationPlan:
    """A one-dataset snapshot plan: ``tickers`` only, no window, one page each."""
    fields: dict[str, object] = {
        "subjects": subjects(*(tickers or (SUBJECT_A,))),
        "datasets": (DatasetPlan(dataset=SharadarDataset.TICKERS),),
        "limits": QualificationLimits(),
        "execution_id": EXECUTION_ID,
        "source_schema_version": SCHEMA_VERSION,
    }
    fields.update(overrides)
    return QualificationPlan(**fields)  # type: ignore[arg-type]


def three_dataset_plan(*tickers: str, **overrides: object) -> QualificationPlan:
    """All three Stage-3A datasets for the given subjects, one page each."""
    fields: dict[str, object] = {
        "subjects": subjects(*(tickers or (SUBJECT_A,))),
        "datasets": (
            DatasetPlan(dataset=SharadarDataset.TICKERS),
            DatasetPlan(dataset=SharadarDataset.STOCKS, window=window()),
            DatasetPlan(dataset=SharadarDataset.ACTIONS, window=window()),
        ),
        "limits": QualificationLimits(),
        "execution_id": EXECUTION_ID,
        "source_schema_version": SCHEMA_VERSION,
    }
    fields.update(overrides)
    return QualificationPlan(**fields)  # type: ignore[arg-type]


class SteppingClock:
    """A clock that advances by one second on every read.

    What a *real* clock does, and therefore the fixture that makes the absence of
    a resume visible: two executions of one plan record two different instants, so
    the second acquisition record differs from the first under an occupied name
    and is refused.
    """

    def __init__(self, start: datetime = RUN_INSTANT) -> None:
        """Begin at ``start``."""
        self.instant = start
        self.calls = 0

    def now(self) -> datetime:
        """The next instant, one second on from the last."""
        self.calls += 1
        current = self.instant
        self.instant = self.instant + timedelta(seconds=1)
        return current


class StagedFailureStore:
    """The real in-memory store, made to fail on the *nth* publication write.

    A Bronze publication appends three objects -- claim, payload, acquisition
    record -- so "the store failed" is three different situations with three
    different amounts of durable residue. Injecting at a chosen write is the only
    way to test what the runtime says about each.
    """

    def __init__(self, *, fail_on_write: int, error: BaseException) -> None:
        """Serve writes normally until ``fail_on_write``, then raise ``error``."""
        self._store = InMemoryResearchObjectStore()
        self.fail_on_write = fail_on_write
        self.error = error
        self.put_keys: list[str] = []

    def put_if_absent(self, *, key: ObjectKey, payload: bytes) -> PutOutcome:
        """Delegate, unless this is the write that must fail."""
        self.put_keys.append(key.logical_key)
        if len(self.put_keys) == self.fail_on_write:
            raise self.error
        return self._store.put_if_absent(key=key, payload=payload)

    def exists(self, *, key: ObjectKey) -> bool:
        """Delegate."""
        return self._store.exists(key=key)

    @property
    def call_count(self) -> int:
        """How many publications were attempted."""
        return len(self.put_keys)


__all__ = [
    "EXECUTION_ID",
    "LEAK_CANARIES",
    "OTHER_EXECUTION_ID",
    "PAYLOAD_A",
    "PAYLOAD_B",
    "PAYLOAD_C",
    "RUN_INSTANT",
    "SCHEMA_VERSION",
    "SUBJECT_A",
    "SUBJECT_B",
    "SUBJECT_C",
    "BadClock",
    "FixedClock",
    "LeakyClient",
    "RaisingClock",
    "RecordingStore",
    "RefusingStore",
    "StagedFailureStore",
    "SteppingClock",
    "client",
    "snapshot_plan",
    "subjects",
    "three_dataset_plan",
    "window",
]
