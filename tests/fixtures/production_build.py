"""Synthetic fixtures for the offline research-build processing tests.

Everything here is invented: symbols beginning ``ZZ``, six-digit ``permaticker`` values
in the 100000 range, a synthetic exchange calendar with explicit UTC opens, and vendor
rows typed by this repository. **No vendor row, no real security and no real
credential appears here**, and no fake reaches a network.

The store is populated by the **real acquisition path**: :func:`acquire` runs
:func:`~kalpamani.data.production.sharadar.processing.run_production_acquisition`
against a coordinate-answering provider fake, so the locators, payloads and records the
build reads are exactly what the accepted acquisition writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from fixtures.production_runtime import (
    BUILD_ID,
    COMMIT,
    INTERFACE_ID,
    SUBNET_ID,
    TASK_ARN,
    FakeClientError,
    FakeSsm,
    binding_document,
    build_input_document,
    caller_identity,
    compiled_task,
    encode,
    ledger_row_document,
    metadata_document,
    revision_arn,
    task_identity_arn,
)
from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.ingest.sharadar.credentials import SharadarCredential
from kalpamani.data.production.sharadar import build_processing as bp
from kalpamani.data.production.sharadar import processing as pp
from kalpamani.data.production.sharadar.availability import AvailabilityEvidence
from kalpamani.data.production.sharadar.build_manifest import BuildConfiguration
from kalpamani.data.production.sharadar.identities import LedgerSpentIdentities
from kalpamani.data.production.sharadar.inputs import (
    INPUT_SCHEMA_VERSION,
    input_digest,
    ledger_digest,
    parse_slice,
)
from kalpamani.data.production.sharadar.parameters import SsmParameterAdapter
from kalpamani.data.production.sharadar.plan import ProductionRequest, plan_digest_for
from kalpamani.data.production.sharadar.release import build_release_document
from kalpamani.data.production.sharadar.runner import RunnerAdapters
from kalpamani.data.production.sharadar.sessions import Session, SessionCalendar
from kalpamani.data.production.sharadar.silver import AcceptedSchemas
from kalpamani.data.production.sharadar.universe import UniverseRule
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for
from kalpamani.data.qualify.sharadar.parser import schema_digest_of

ACQ: Final = ProductionActor.ACQUISITION
BUILD: Final = ProductionActor.BUILD
SECRET_ID: Final = "synthetic/production/sharadar"  # noqa: S105 - an identifier, not a secret
SECRET_VALUE: Final = "synthetic-fake-not-a-real-sharadar-key-0009"  # noqa: S105

RUN_1: Final = "synthetic-build-source-run-0001"
RUN_2: Final = "synthetic-build-source-run-0002"
RUN_1_AT: Final = datetime(2026, 9, 5, 2, 0, tzinfo=UTC)
RUN_2_AT: Final = datetime(2026, 9, 15, 2, 0, tzinfo=UTC)

# --- vendor-shaped headers ----------------------------------------------------------

TICKERS_HEADER: Final = (
    "table",
    "permaticker",
    "ticker",
    "name",
    "exchange",
    "isdelisted",
    "category",
    "sector",
    "industry",
    "lastupdated",
    "firstpricedate",
    "lastpricedate",
)
STOCKS_HEADER: Final = (
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "closeadj",
    "closeunadj",
    "lastupdated",
)
ACTIONS_HEADER: Final = ("date", "action", "ticker", "name", "value", "contraticker", "contraname")

SCHEMAS: Final = AcceptedSchemas(
    version="synthetic-accepted-schemas-v1",
    digests={
        "tickers": frozenset({schema_digest_of(TICKERS_HEADER)}),
        "stocks": frozenset({schema_digest_of(STOCKS_HEADER)}),
        "actions": frozenset({schema_digest_of(ACTIONS_HEADER)}),
    },
)


def csv(header: tuple[str, ...], rows: list[tuple[str, ...]]) -> bytes:
    """A CSV payload with CRLF line endings, as a vendor would deliver one."""
    lines = [",".join(header)] + [",".join(row) for row in rows]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


# --- the synthetic securities ---------------------------------------------------------

COMMON: Final = "Domestic Common Stock"


@dataclass(frozen=True)
class Security:
    symbol: str
    permaticker: str
    exchange: str
    category: str = COMMON
    isdelisted: str = "N"
    firstpricedate: str = "2010-01-04"
    lastpricedate: str = "2026-09-14"

    @property
    def security_id(self) -> str:
        return f"sharadar:{self.permaticker}"

    def ticker_row(self, lastupdated: str) -> tuple[str, ...]:
        return (
            "SEP",
            self.permaticker,
            self.symbol,
            f"Synthetic {self.symbol} Corp",
            self.exchange,
            self.isdelisted,
            self.category,
            "Synthetic Sector",
            "Synthetic Industry",
            lastupdated,
            self.firstpricedate,
            self.lastpricedate,
        )


ZZAA: Final = Security("ZZAA", "100001", "NYSE")  # member; 2:1 split ex 2026-09-03
ZZBB: Final = Security("ZZBB", "100002", "NASDAQ")  # history delivered late (C-2)
ZZCC: Final = Security("ZZCC", "100003", "OTC")  # EXCHANGE
ZZDD: Final = Security("ZZDD", "100004", "NYSE", category="ETF")  # SECURITY_TYPE
ZZEE_1: Final = Security("ZZEE", "100005", "NYSE")  # ambiguous symbol ...
ZZEE_2: Final = Security("ZZEE", "100006", "NYSE")  # ... two permatickers
ZZFF: Final = Security("ZZFF", "100007", "NYSE")  # spinoff ex 2026-09-03
ZZGG: Final = Security("ZZGG", "100008", "NYSE")  # price below the floor
ZZHH: Final = Security("ZZHH", "100009", "NYSE")  # delisting event dated 2026-09-14 (C-3)

SECURITIES: Final = (ZZAA, ZZBB, ZZCC, ZZDD, ZZEE_1, ZZEE_2, ZZFF, ZZGG, ZZHH)

SESSIONS_2026: Final = (
    date(2026, 8, 24),
    date(2026, 8, 25),
    date(2026, 8, 26),
    date(2026, 8, 27),
    date(2026, 8, 28),
    date(2026, 8, 31),
    date(2026, 9, 1),
    date(2026, 9, 2),
    date(2026, 9, 3),
    date(2026, 9, 4),
    date(2026, 9, 14),
    date(2026, 9, 15),
)
BAR_SESSIONS_RUN_1: Final = SESSIONS_2026[5:10]  # 08-31 .. 09-04
SPLIT_EX: Final = date(2026, 9, 3)
SPINOFF_EX: Final = date(2026, 9, 3)
DELISTING_DATE: Final = date(2026, 9, 14)


def calendar(*, with_2019: bool = True) -> SessionCalendar:
    """The synthetic calendar: 13:30Z opens, so ``decision_time(d)`` is 13:00Z."""
    dates = ((date(2019, 3, 4), date(2019, 3, 5)) if with_2019 else ()) + SESSIONS_2026
    return SessionCalendar(
        version="synthetic-calendar-v1",
        sessions=tuple(
            Session(session_date=d, open_at=datetime(d.year, d.month, d.day, 13, 30, tzinfo=UTC))
            for d in dates
        ),
    )


def rule() -> UniverseRule:
    """Three history sessions, a three-session ADDV window, a 5.00 floor, 1,000,000 ADDV."""
    return UniverseRule(
        history_sessions=3,
        addv_window_sessions=3,
        price_floor=Decimal("5"),
        addv_floor=Decimal("1000000"),
    )


def _bar(
    security: Security,
    session: date,
    *,
    close: str,
    closeadj: str,
    volume: str = "100000",
    lastupdated: str = "2026-09-04",
) -> tuple[str, ...]:
    c = Decimal(close)
    return (
        security.symbol,
        session.isoformat(),
        str(c - Decimal("0.10")),
        str(c + Decimal("0.20")),
        str(c - Decimal("0.30")),
        close,
        volume,
        closeadj,
        close,
        lastupdated,
    )


#: ZZAA closes: 20.00, 20.40, 20.80 then a 2:1 split, 10.50, 10.60. The vendor's
#: back-adjusted closeadj halves the pre-split closes; the repository's forward series
#: doubles the post-split ones. Both are proportional, so reconciliation passes.
ZZAA_CLOSES: Final = {
    date(2026, 8, 31): ("20.00", "10.00"),
    date(2026, 9, 1): ("20.40", "10.20"),
    date(2026, 9, 2): ("20.80", "10.40"),
    date(2026, 9, 3): ("10.50", "10.50"),
    date(2026, 9, 4): ("10.60", "10.60"),
    date(2026, 9, 14): ("10.70", "10.70"),
}
#: ZZAA's 2026-09-02 bar is re-delivered by run 2 with a different close (T-1 / V-1).
ZZAA_REVISED_0902: Final = ("20.90", "10.45")

FLAT_CLOSE: Final = ("12.00", "12.00")


def stocks_rows(session: date, *, run: int) -> list[tuple[str, ...]]:
    """The synthetic cross-section for one session, as run 1 or run 2 delivers it."""
    rows: list[tuple[str, ...]] = []
    if session in ZZAA_CLOSES:
        close, adj = ZZAA_CLOSES[session]
        if run == 2 and session == date(2026, 9, 2):
            close, adj = ZZAA_REVISED_0902
        rows.append(_bar(ZZAA, session, close=close, closeadj=adj))
    if session in SESSIONS_2026[5:11]:
        # ZZBB's 09-02 .. 09-04 bars exist only in run 2; 08-31 and 09-01 in both.
        if not (run == 1 and session >= date(2026, 9, 2)):
            rows.append(_bar(ZZBB, session, close=FLAT_CLOSE[0], closeadj=FLAT_CLOSE[1]))
        for security in (ZZCC, ZZDD, ZZEE_1, ZZFF):
            rows.append(_bar(security, session, close=FLAT_CLOSE[0], closeadj=FLAT_CLOSE[1]))
        rows.append(_bar(ZZGG, session, close="3.00", closeadj="3.00"))
        if session < DELISTING_DATE:
            rows.append(_bar(ZZHH, session, close=FLAT_CLOSE[0], closeadj=FLAT_CLOSE[1]))
    return rows


def tickers_rows(*, lastupdated: str) -> list[tuple[str, ...]]:
    return [security.ticker_row(lastupdated) for security in SECURITIES]


def actions_rows(*, run: int) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = [
        (SPLIT_EX.isoformat(), "split", ZZAA.symbol, "Synthetic ZZAA Corp", "2", "", ""),
        (SPINOFF_EX.isoformat(), "spinoff", ZZFF.symbol, "Synthetic ZZFF Corp", "0.25", "ZZFX", ""),
        (
            date(2026, 8, 20).isoformat(),
            "dividend",
            ZZBB.symbol,
            "Synthetic ZZBB Corp",
            "0.10",
            "",
            "",
        ),
    ]
    if run == 2:
        rows.append(
            (DELISTING_DATE.isoformat(), "delisted", ZZHH.symbol, "Synthetic ZZHH Corp", "", "", "")
        )
    return rows


# --- slices -----------------------------------------------------------------------------


def slice_with_stocks_window(run: int, window: str) -> dict[str, Any]:
    """A run's slice with its ``stocks`` window replaced (request count recomputed)."""
    start, end = (date.fromisoformat(part) for part in window.split("/"))
    days = (end - start).days + 1
    doc = dict(slice_for_run(run))
    doc["windows"] = dict(doc["windows"], stocks=window)
    doc["request_count"] = 2 + days * 2 + 4
    return doc


def slice_for_run(run: int) -> dict[str, Any]:
    """Run 1 covers 08-31..09-04 (16 requests); run 2 covers 09-02..09-14 (32 requests)."""
    if run == 1:
        stocks_window, count = "2026-08-31/2026-09-04", 2 + 5 * 2 + 4
    else:
        stocks_window, count = "2026-09-02/2026-09-14", 2 + 13 * 2 + 4
    return {
        "acquisition_mode": "BACKFILL",
        "datasets": ["actions", "stocks", "tickers"],
        "windows": {
            "actions": "2026-08-01/2026-09-14",
            "stocks": stocks_window,
            "tickers": "SNAPSHOT",
        },
        "request_count": count,
        "max_response_bytes": 4 * 1024 * 1024,
    }


def responses_for_run(
    run: int, slice_doc: dict[str, Any] | None = None
) -> dict[tuple[str, str, int], bytes]:
    """Every request coordinate of a run mapped to the bytes the synthetic vendor answers."""
    out: dict[tuple[str, str, int], bytes] = {}
    slice_doc = slice_for_run(run) if slice_doc is None else slice_doc
    lastupdated = "2026-09-04" if run == 1 else "2026-09-14"
    out[("actions", slice_doc["windows"]["actions"], 0)] = csv(
        ACTIONS_HEADER, actions_rows(run=run)
    )
    out[("actions", slice_doc["windows"]["actions"], 10000)] = csv(ACTIONS_HEADER, [])
    start, end = (date.fromisoformat(part) for part in slice_doc["windows"]["stocks"].split("/"))
    day = start
    while day <= end:
        window = f"{day.isoformat()}/{day.isoformat()}"
        rows = stocks_rows(day, run=run) if day in SESSIONS_2026 else []
        out[("stocks", window, 0)] = csv(STOCKS_HEADER, rows)
        out[("stocks", window, 10000)] = csv(STOCKS_HEADER, [])
        day += timedelta(days=1)
    out[("tickers", "SNAPSHOT", 0)] = csv(TICKERS_HEADER, tickers_rows(lastupdated=lastupdated))
    for offset in (10000, 20000, 30000):
        out[("tickers", "SNAPSHOT", offset)] = csv(TICKERS_HEADER, [])
    return out


# --- fakes -------------------------------------------------------------------------------


@dataclass
class FakeS3Store:
    """A get-and-put S3-shaped fake with create-only puts and injectable failures."""

    objects: dict[str, bytes] = field(default_factory=dict)
    puts: list[str] = field(default_factory=list)
    gets: list[str] = field(default_factory=list)
    fail_put_on: dict[str, str] = field(default_factory=dict)
    fail_put_after: int | None = None
    fail_put_code: str = "InternalError"
    fail_get_on: dict[str, str] = field(default_factory=dict)

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        self.puts.append(key)
        assert kwargs["IfNoneMatch"] == "*" and kwargs["ServerSideEncryption"] == "AES256"
        if key in self.fail_put_on:
            raise FakeClientError(self.fail_put_on[key])
        if self.fail_put_after is not None and len(self.puts) > self.fail_put_after:
            raise FakeClientError(self.fail_put_code)
        if key in self.objects:
            raise FakeClientError("PreconditionFailed")
        self.objects[key] = kwargs["Body"]
        return {
            "ETag": '"synthetic"',
            "ChecksumSHA256": kwargs["ChecksumSHA256"],
            "ChecksumType": "FULL_OBJECT",
        }

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        self.gets.append(key)
        if key in self.fail_get_on:
            raise FakeClientError(self.fail_get_on[key])
        if key not in self.objects:
            raise FakeClientError("NoSuchKey")
        return {"Body": _Body(self.objects[key])}

    def keys_under(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0

    def read(self, size: int) -> bytes:
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class FakeSecrets:
    def __init__(self) -> None:
        self.calls = 0

    def get_secret_value(self, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        return {"SecretString": SECRET_VALUE, "ARN": kwargs.get("SecretId")}


@dataclass
class CoordinateProvider:
    """Answers each request by its coordinates; records every request."""

    responses: dict[tuple[str, str, int], bytes]
    calls: list[tuple[int, str, str, int]] = field(default_factory=list)

    def fetch(self, request: ProductionRequest, *, credential: SharadarCredential) -> bytes:
        self.calls.append((request.ordinal, request.dataset, request.window, request.page_offset))
        credential.reveal()
        return self.responses[(request.dataset, request.window, request.page_offset)]


@dataclass
class ShiftedClock:
    """An injectable monotonic clock and wall clock anchored at ``base``."""

    base: datetime
    seconds: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.seconds

    def sleep(self, duration: float) -> None:
        self.sleeps.append(duration)
        self.seconds += duration

    def now(self) -> datetime:
        return self.base + timedelta(seconds=self.seconds)


# --- the acquisition that populates the store ----------------------------------------


def acquire(
    store: FakeS3Store,
    *,
    run_id: str,
    run: int,
    at: datetime,
    responses: dict[tuple[str, str, int], bytes] | None = None,
    slice_doc: dict[str, Any] | None = None,
) -> pp.AcquisitionReport:
    """Run the real acquisition path for one synthetic run into ``store``."""
    constants = constants_for(ACQ)
    slice_doc = slice_for_run(run) if slice_doc is None else slice_doc
    covered = parse_slice(slice_doc)
    digest = plan_digest_for(covered, acquisition_mode=AcquisitionMode.BACKFILL)
    input_document = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "contract_id": constants.input_contract_id,
        "run_identity": run_id,
        "slice": slice_doc,
        "plan_digest": digest,
        "issued_at": (at - timedelta(hours=1)).isoformat(),
        "expires_at": (at + timedelta(hours=23)).isoformat(),
    }
    input_bytes = encode(input_document)
    ssm = FakeSsm()
    ssm.values[constants.binding_parameter] = encode(binding_document(ACQ))
    ssm.values[constants.input_parameter] = input_bytes
    ssm.values[constants.release_parameter] = build_release_document(
        actor=ACQ,
        task_arn=TASK_ARN,
        task_definition_arn=revision_arn(ACQ),
        identity=run_id,
        input_digest=input_digest(input_bytes),
        network_interface_id=INTERFACE_ID,
        subnet_id=SUBNET_ID,
        verified_at=at - timedelta(seconds=10),
    )
    clock = ShiftedClock(base=at)
    provider = CoordinateProvider(
        responses=responses_for_run(run) if responses is None else responses
    )
    report = pp.run_production_acquisition(
        compiled=compiled_task(ACQ),
        bootstrap=RunnerAdapters(
            environment_names=lambda: ["PATH", "ECS_CONTAINER_METADATA_URI_V4"],
            parameters=SsmParameterAdapter(ssm=ssm),
            metadata=lambda: metadata_document(ACQ),
            caller_identity=lambda: caller_identity(task_identity_arn(ACQ)),
            now=clock.now,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        ),
        registry=LedgerSpentIdentities([]),
        processing=pp.ProcessingAdapters(
            secrets=FakeSecrets(),
            secret_id=SECRET_ID,
            provider=provider,
            s3=store,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
            clock=clock.now,
        ),
    )
    assert report.status is pp.AcquisitionStatus.COMPLETED, report
    return report


def ledger_row(
    run_id: str, run: int, at: datetime, slice_doc: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The owner's ledger row for one synthetic run."""
    slice_doc = slice_for_run(run) if slice_doc is None else slice_doc
    covered = parse_slice(slice_doc)
    return ledger_row_document(
        run_id,
        slice=slice_doc,
        plan_digest=plan_digest_for(covered, acquisition_mode=AcquisitionMode.BACKFILL),
        launched_at=(at - timedelta(minutes=5)).isoformat(),
        completed_at=(at + timedelta(hours=1)).isoformat(),
    )


def populated_store(*, runs: tuple[int, ...] = (1, 2)) -> FakeS3Store:
    """A store holding the requested synthetic runs, written by the real acquisition."""
    store = FakeS3Store()
    if 1 in runs:
        acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT)
    if 2 in runs:
        acquire(store, run_id=RUN_2, run=2, at=RUN_2_AT)
    return store


# --- the build scenario ------------------------------------------------------------------

AS_OF: Final = datetime(2026, 9, 16, 0, 0, tzinfo=UTC)
BUILD_NOW: Final = datetime(2026, 9, 16, 1, 0, tzinfo=UTC)
DECISION_SESSIONS: Final = (date(2026, 9, 14), date(2026, 9, 15))


def configuration(
    *,
    as_of: datetime = AS_OF,
    sessions: tuple[date, ...] = DECISION_SESSIONS,
    evidence: AvailabilityEvidence | None = None,
    universe_rule: UniverseRule | None = None,
    session_calendar: SessionCalendar | None = None,
) -> BuildConfiguration:
    return BuildConfiguration(
        schemas=SCHEMAS,
        calendar=calendar() if session_calendar is None else session_calendar,
        evidence=AvailabilityEvidence(version="synthetic-evidence-v0")
        if evidence is None
        else evidence,
        rule=rule() if universe_rule is None else universe_rule,
        decision_sessions=sessions,
        as_of=as_of,
        commit=COMMIT,
    )


class BuildScenario:
    """One build task over a populated store, with every adapter injected."""

    def __init__(
        self,
        store: FakeS3Store,
        *,
        runs: tuple[tuple[str, int, datetime], ...] = ((RUN_1, 1, RUN_1_AT), (RUN_2, 2, RUN_2_AT)),
        config: BuildConfiguration | None = None,
        build_id: str = BUILD_ID,
        now: datetime = BUILD_NOW,
        release: bool = True,
        slices: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        constants = constants_for(BUILD)
        rows = [ledger_row(run_id, run, at, (slices or {}).get(run_id)) for run_id, run, at in runs]
        self.ssm = FakeSsm()
        self.ssm.values[constants.binding_parameter] = encode(binding_document(BUILD))
        self.input_bytes = encode(
            build_input_document(
                rows,
                build_identity=build_id,
                ledger_digest=ledger_digest(rows),
                issued_at=(now - timedelta(hours=1)).isoformat(),
                expires_at=(now + timedelta(hours=23)).isoformat(),
            )
        )
        self.ssm.values[constants.input_parameter] = self.input_bytes
        if release:
            self.ssm.values[constants.release_parameter] = build_release_document(
                actor=BUILD,
                task_arn=TASK_ARN,
                task_definition_arn=revision_arn(BUILD),
                identity=build_id,
                input_digest=input_digest(self.input_bytes),
                network_interface_id=INTERFACE_ID,
                subnet_id=SUBNET_ID,
                verified_at=now - timedelta(seconds=10),
            )
        self.clock = ShiftedClock(base=now)
        self.store = store
        self.config = configuration() if config is None else config
        self._gets_before = len(store.gets)
        self._puts_before = len(store.puts)

    def run(self) -> bp.BuildReport:
        return bp.run_production_build(
            compiled=compiled_task(BUILD),
            bootstrap=RunnerAdapters(
                environment_names=lambda: ["PATH", "ECS_CONTAINER_METADATA_URI_V4"],
                parameters=SsmParameterAdapter(ssm=self.ssm),
                metadata=lambda: metadata_document(BUILD),
                caller_identity=lambda: caller_identity(task_identity_arn(BUILD)),
                now=self.clock.now,
                monotonic=self.clock.monotonic,
                sleep=self.clock.sleep,
            ),
            registry=LedgerSpentIdentities([]),
            processing=bp.BuildAdapters(
                s3=self.store,
                configuration=self.config,
                monotonic=self.clock.monotonic,
                clock=self.clock.now,
            ),
        )

    def data_plane_calls(self) -> tuple[int, int]:
        """(gets, puts) this scenario's build asked the store for."""
        return (len(self.store.gets) - self._gets_before, len(self.store.puts) - self._puts_before)


__all__ = [
    "ACTIONS_HEADER",
    "AS_OF",
    "BUILD_NOW",
    "DECISION_SESSIONS",
    "DELISTING_DATE",
    "RUN_1",
    "RUN_1_AT",
    "RUN_2",
    "RUN_2_AT",
    "SCHEMAS",
    "SECURITIES",
    "SESSIONS_2026",
    "SPINOFF_EX",
    "SPLIT_EX",
    "STOCKS_HEADER",
    "TICKERS_HEADER",
    "ZZAA",
    "ZZAA_CLOSES",
    "ZZAA_REVISED_0902",
    "ZZBB",
    "ZZCC",
    "ZZDD",
    "ZZEE_1",
    "ZZEE_2",
    "ZZFF",
    "ZZGG",
    "ZZHH",
    "BuildScenario",
    "CoordinateProvider",
    "FakeS3Store",
    "ShiftedClock",
    "acquire",
    "calendar",
    "configuration",
    "csv",
    "ledger_row",
    "populated_store",
    "responses_for_run",
    "rule",
    "slice_for_run",
    "slice_with_stocks_window",
    "stocks_rows",
    "tickers_rows",
]
