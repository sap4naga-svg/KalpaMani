"""Synthetic fixtures for the M0 exploratory path. **SYNTHETIC / EXPLORATORY_HINDSIGHT.**

One calendar of 572 sessions (weekdays from 2024-06-03 with four synthetic holidays), eighteen
obviously fictional securities whose price paths are *scripted* -- no random walk -- so every
rule of M0 §11-§14 is exercised by construction:

* ``ZZAA``  breakout in development → held to the 20-session time exit;
* ``ZZBB``  breakout → a gap below the base low → stop executed next open, more than 1R lost;
* ``ZZCC``  breakout → bars stop, a ``delisted`` action dated the first missing session →
  terminal recognition at that open from the admissible action;
* ``ZZDD``  breakout → one bar missing mid-hold with no action → held, counted, then time exit;
* ``ZZEE``  breakout → the next open gaps 12 % → ``SKIPPED_ENTRY_GAP``;
* ``ZZTA…ZZTM`` thirteen tight-base breakouts on one development session → the thirteenth is
  ``SKIPPED_CASH``; the same thirteen with wide bases on one validation session → the
  eleventh is ``SKIPPED_RISK_CAPACITY``;
* ``ZZCC`` also carries a 2:1 split in the warm-up so the split-only adjustment is exercised.

Every bar is flat at its scripted level except where the script says otherwise; every security
is NYSE / Domestic Common Stock, listed before the calendar, with ADDV ≈ 2,000,000.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Final

from kalpamani.data.exploratory.dataset import ExploratoryDataset, build_benchmark_a
from kalpamani.data.exploratory.resolution import decide_membership_all, resolve_as_dated
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.production.sharadar.pagination import PaginationSummary
from kalpamani.data.production.sharadar.sessions import Session, SessionCalendar
from kalpamani.data.production.sharadar.silver import (
    Provenance,
    RowVersion,
    SilverDataset,
    SilverLayer,
)
from kalpamani.data.production.sharadar.universe import UniverseRule

CALENDAR_VERSION: Final = "synthetic-calendar-m0-v1"
HOLIDAYS: Final = frozenset(
    {date(2024, 7, 4), date(2024, 12, 25), date(2025, 7, 4), date(2025, 12, 25)}
)
RETRIEVED_AT: Final = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
AS_OF: Final = datetime(2026, 9, 21, 0, 0, tzinfo=UTC)
SPLIT_EX: Final = date(2024, 9, 3)  # ZZCC's 2:1 split, inside the warm-up

SCENARIO: Final = ("ZZAA", "ZZBB", "ZZCC", "ZZDD", "ZZEE")
TIGHT: Final = tuple(f"ZZT{c}" for c in "ABCDEFGHIJKLM")
SYMBOLS: Final = SCENARIO + TIGHT


def calendar() -> SessionCalendar:
    """572 synthetic sessions, 13:30Z opens."""
    sessions: list[Session] = []
    day = date(2024, 6, 3)
    while len(sessions) < 572:
        if day.weekday() < 5 and day not in HOLIDAYS:
            sessions.append(
                Session(
                    session_date=day,
                    open_at=datetime(day.year, day.month, day.day, 13, 30, tzinfo=UTC),
                )
            )
        day += timedelta(days=1)
    return SessionCalendar(version=CALENDAR_VERSION, sessions=tuple(sessions))


def rule() -> UniverseRule:
    """The M0 s.14 fixture rule: 252 sessions of history, ADDV window 20, floors 5 / 1,000,000."""
    return UniverseRule(history_sessions=252, addv_window_sessions=20)


@dataclass(frozen=True)
class Bar:
    open: str
    high: str
    low: str
    close: str
    volume: str = "100000"


def flat(level: str, *, volume: str = "100000") -> Bar:
    p = Decimal(level)
    return Bar(
        str(p - Decimal("0.10")), str(p + Decimal("0.20")), str(p - Decimal("0.30")), level, volume
    )


def breakout(level: str) -> Bar:
    """Close above the flat base's high (level + 0.20) on 2.5x volume; open at the prior close."""
    p = Decimal(level)
    return Bar(level, str(p * Decimal("1.05")), level, str(p * Decimal("1.04")), "250000")


def wide_base(level: str, k: int) -> Bar:
    """A 14 % range with a stable close: the intraday low sits 14 % under the high, so the
    base low (the stop) is far from the entry while the closes -- and the equal-weight
    benchmark built from them -- stay flat."""
    del k
    p = Decimal(level)
    return Bar(level, str(p + Decimal("0.05")), str(p * Decimal("0.86")), level)


def scripted_bars(
    symbol: str, sessions: tuple[date, ...], phases: dict[str, tuple[date, ...]]
) -> dict[date, Bar]:
    """The scripted path of one security over every session (a missing session is absent)."""
    dev = phases["development"]
    val = phases["validation"]
    index = {d: i for i, d in enumerate(sessions)}
    bars: dict[date, Bar] = {d: flat("20.00") for d in sessions}
    if symbol == "ZZCC":
        # Pre-split levels are doubled so the forward-base-normalized series is flat at 20.
        for d in sessions:
            if d < SPLIT_EX:
                bars[d] = flat("40.00", volume="50000")
    if symbol in SCENARIO:
        d0 = dev[5]
        i0 = index[d0]
        bars[d0] = breakout("20.00")
        after = sessions[i0 + 1 :]
        if symbol == "ZZAA":
            for k, d in enumerate(after[:40]):
                bars[d] = flat(str(Decimal("20.80") + Decimal("0.05") * (k + 1)))
        elif symbol == "ZZBB":
            bars[after[0]] = flat("20.80")
            bars[after[1]] = flat("20.80")
            bars[after[2]] = Bar("18.70", "18.90", "18.20", "18.30")  # gap below the base low 19.70
            bars[after[3]] = Bar("18.32", "18.50", "18.00", "18.10")  # the exit open
            for d in after[4:40]:
                bars[d] = flat("18.10")
        elif symbol == "ZZCC":
            for d in after[:5]:
                bars[d] = flat("20.80")
            for d in after[5:]:
                del bars[d]  # bars stop; the delisted action is dated after[5]
        elif symbol == "ZZDD":
            for d in after[:40]:
                bars[d] = flat("20.80")
            del bars[after[6]]  # one missing bar, no action
        elif symbol == "ZZEE":
            bars[after[0]] = Bar("23.30", "23.50", "23.00", "23.20")  # a 12 % gap at the next open
            for d in after[1:40]:
                bars[d] = flat("23.20")
    if symbol in TIGHT:
        d1 = dev[60]
        i1 = index[d1]
        # A tight base: flat 20.00 has range 0.50 / 20.20 = 2.5 %; cap-bound sizing, planned
        # risk ≈ 6400 x (fill - 19.70) / fill ≈ 350, so twelve fit the cash and thirteen do not.
        bars[d1] = breakout("20.00")
        # The executing open sits just above the base low, so the planned risk is small
        # (about 70) and twelve positions exhaust the cash before the open-risk cap binds.
        bars[sessions[i1 + 1]] = Bar("19.90", "21.00", "19.85", "20.82", "100000")
        for k, d in enumerate(sessions[i1 + 2 : i1 + 41]):
            bars[d] = flat(str(Decimal("20.82") + Decimal("0.02") * (k + 1)))
        for d in sessions[i1 + 41 :]:
            bars[d] = flat("21.60")
        d2 = val[40]
        i2 = index[d2]
        # A wide (14 %) base under 21.60: the planned risk is about 400 per position, so the
        # eleventh candidate exceeds the 4,000 open-risk cap.
        for k, d in enumerate(sessions[i2 - 20 : i2]):
            bars[d] = wide_base("21.60", k)
        bars[d2] = Bar(
            "21.65", "23.00", "21.60", "22.90", "250000"
        )  # above the wide base high 21.65
        for k, d in enumerate(sessions[i2 + 1 : i2 + 41]):
            bars[d] = flat(str(Decimal("22.90") + Decimal("0.02") * (k + 1)))
        for d in sessions[i2 + 41 :]:
            bars[d] = flat("23.70")
    return bars


def _provenance(dataset: str, ordinal: int) -> Provenance:
    return Provenance(
        run_id="synthetic-m0-run-01",
        ordinal=ordinal,
        payload_sha256=hashlib.sha256(f"{dataset}:{ordinal}".encode()).hexdigest(),
        schema_digest=hashlib.sha256(f"schema:{dataset}".encode()).hexdigest(),
        acquisition_mode="BACKFILL",
        retrieved_at=RETRIEVED_AT,
    )


def _row(
    dataset: str, key: tuple[str, ...], symbol: str, fields: dict[str, str | None], ordinal: int
) -> RowVersion:
    content = hashlib.sha256(repr(sorted(fields.items())).encode()).hexdigest()
    return RowVersion(
        dataset=dataset,
        row_key=key,
        security_id=f"sharadar:{permaticker(symbol)}",
        symbol=symbol,
        revision_sequence=1,
        content_sha256=content,
        fields=fields,
        provenance=_provenance(dataset, ordinal),
        system_first_seen_time=RETRIEVED_AT,
        content_first_seen_time=RETRIEVED_AT,
        observed_at=(RETRIEVED_AT,),
    )


def permaticker(symbol: str) -> str:
    return str(900000 + SYMBOLS.index(symbol))


def security_id(symbol: str) -> str:
    return f"sharadar:{permaticker(symbol)}"


def phases_of(cal: SessionCalendar) -> dict[str, tuple[date, ...]]:
    """The §11.1 phases over this calendar (mirrors ``m0.phases_for`` for the fixture script)."""
    s = tuple(x.session_date for x in cal.sessions)
    end = len(s)
    out: dict[str, tuple[date, ...]] = {}
    for name, count in (
        ("tail", 30),
        ("validation", 126),
        ("purge", 30),
        ("development", 126),
        ("warm_up", 253),
    ):
        out[name] = s[end - count : end]
        end -= count
    return out


def silver_layer(cal: SessionCalendar | None = None) -> SilverLayer:
    """The synthetic Silver layer, built directly as row versions (no acquisition path)."""
    cal = cal or calendar()
    sessions = tuple(x.session_date for x in cal.sessions)
    phases = phases_of(cal)
    tickers: list[RowVersion] = []
    stocks: list[RowVersion] = []
    actions: list[RowVersion] = []
    ordinal = 0
    for symbol in SYMBOLS:
        tickers.append(
            _row(
                SharadarDataset.TICKERS.value,
                (permaticker(symbol),),
                symbol,
                {
                    "table": "SEP",
                    "permaticker": permaticker(symbol),
                    "ticker": symbol,
                    "name": f"Synthetic {symbol} Corp",
                    "exchange": "NYSE",
                    "isdelisted": "Y" if symbol == "ZZCC" else "N",
                    "category": "Domestic Common Stock",
                    "sector": "Synthetic Sector",
                    "industry": "Synthetic Industry",
                    "lastupdated": "2026-09-19",
                    "firstpricedate": "2010-01-04",
                    "lastpricedate": "2026-09-18",
                },
                ordinal,
            )
        )
        ordinal += 1
        bars = scripted_bars(symbol, sessions, phases)
        for day in sessions:
            bar = bars.get(day)
            if bar is None:
                continue
            stocks.append(
                _row(
                    SharadarDataset.STOCKS.value,
                    (day.isoformat(),),
                    symbol,
                    {
                        "ticker": symbol,
                        "date": day.isoformat(),
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "closeadj": bar.close,
                        "closeunadj": bar.close,
                        "lastupdated": "2026-09-19",
                    },
                    ordinal,
                )
            )
            ordinal += 1
    dev = phases["development"]
    d0 = dev[5]
    i0 = sessions.index(d0)
    delisting_date = sessions[i0 + 6]  # the first session ZZCC has no bar
    actions.append(
        _row(
            SharadarDataset.ACTIONS.value,
            (delisting_date.isoformat(), "delisted"),
            "ZZCC",
            {
                "date": delisting_date.isoformat(),
                "action": "delisted",
                "ticker": "ZZCC",
                "name": "Synthetic ZZCC Corp",
                "value": "",
                "contraticker": "",
                "contraname": "",
            },
            ordinal,
        )
    )
    ordinal += 1
    actions.append(
        _row(
            SharadarDataset.ACTIONS.value,
            (SPLIT_EX.isoformat(), "split"),
            "ZZCC",
            {
                "date": SPLIT_EX.isoformat(),
                "action": "split",
                "ticker": "ZZCC",
                "name": "Synthetic ZZCC Corp",
                "value": "2",
                "contraticker": "",
                "contraname": "",
            },
            ordinal,
        )
    )

    def dataset(name: str, rows: list[RowVersion]) -> SilverDataset:
        return SilverDataset(
            dataset=name,
            rows=tuple(rows),
            schema_digests=(hashlib.sha256(f"schema:{name}".encode()).hexdigest(),),
            duplicate_rows=0,
            unmapped_symbols=0,
            ambiguous_symbols=0,
            rows_excluded_for_identity=0,
        )

    return SilverLayer(
        tickers=dataset(SharadarDataset.TICKERS.value, tickers),
        stocks=dataset(SharadarDataset.STOCKS.value, stocks),
        actions=dataset(SharadarDataset.ACTIONS.value, actions),
        schemas_version="synthetic-schemas-v1",
        pagination=PaginationSummary(
            policy_version="synthetic", groups_admitted={}, groups_empty={}
        ),
    )


def source_digest() -> str:
    """The digest a synthetic dataset names as its source: the fixture's identity, no manifest."""
    return hashlib.sha256(b"synthetic-m0-silver-fixture-v1").hexdigest()


def dataset(cal: SessionCalendar | None = None) -> ExploratoryDataset:
    """Silver → AS_DATED → membership → benchmark A → dataset."""
    cal = cal or calendar()
    layer = resolve_as_dated(silver_layer(cal), calendar=cal)
    membership = decide_membership_all(layer, rule=rule(), calendar=cal, as_of=AS_OF)
    benchmark = build_benchmark_a(layer, membership, calendar=cal)
    return ExploratoryDataset(
        layer=layer,
        membership=membership,
        calendar=cal,
        benchmark=benchmark,
        as_of=AS_OF,
        source_manifest_digest=source_digest(),
    )


__all__ = [
    "AS_OF",
    "CALENDAR_VERSION",
    "SCENARIO",
    "SPLIT_EX",
    "SYMBOLS",
    "TIGHT",
    "calendar",
    "dataset",
    "permaticker",
    "phases_of",
    "rule",
    "security_id",
    "silver_layer",
    "source_digest",
]
