"""The exploratory dataset, its benchmark and the publication bridge (M0 §11.4, ADR-0051 §3).

An :class:`ExploratoryDataset` is what one research run reads: the ``AS_DATED``-resolved layer,
the membership decided under the accepted clauses, the calendar, the benchmark series built
from that membership, and the identity of every input. It is published as an
:class:`~kalpamani.data.exploratory.contracts.ExploratoryPublication` whose ``content_digest``
is the dataset's canonical digest and whose provenance names the production build manifest
(or the synthetic Silver fixture) it was derived from. **It is never an A1
``VerifiedPublication``** and cannot be handed to the accepted reader or gate: nothing here
constructs, subclasses or imitates one.

Benchmark A (M0 §11.4, ``M0-EW-UNIVERSE``): for session ``t`` the member set fixed at
``decision_time(t)`` -- decided from data through ``t-1`` -- and each member's split-only
close return ``close_t / close_{t-1} - 1``; ``I_t = I_{t-1} x (1 + mean r)``, ``I_0 = 100`` at
the first session. **Same-period facts never decide inclusion**: a member with no bar at
``t`` (or at ``t-1``) contributes ``0`` and is counted (``BENCHMARK_MISSING_BAR``); the
total-loss sensitivity treats that contribution as ``-100 %``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

from kalpamani.data.contracts.entities import PriceBarValues
from kalpamani.data.exploratory.contracts import (
    ExploratoryProvenance,
    ExploratoryPublication,
)
from kalpamani.data.exploratory.resolution import (
    ExploratoryResolvedLayer,
    ExploratoryResolvedRow,
    session_close,
)
from kalpamani.data.exploratory.vocabulary import (
    ExploratoryDerivation,
    ExploratoryLimitation,
    ExploratoryProfile,
)
from kalpamani.data.production.sharadar.sessions import SessionCalendar
from kalpamani.data.production.sharadar.universe import ACTION_SPLIT, UniverseSnapshot
from kalpamani.data.qualify.sharadar.parser import date_field, decimal_field

BENCHMARK_A_ID: Final = "M0-EW-UNIVERSE"
BENCHMARK_A_VERSION: Final = "m0-ew-universe-v1"
DATASET_CONTRACT: Final = "kalpamani-exploratory-dataset/v1"
INDEX_BASE: Final = Decimal("100")
_ONE: Final = Decimal(1)
_ZERO: Final = Decimal(0)
_PLACES: Final = Decimal("0.000001")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_PLACES)


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkPoint:
    """One session of the benchmark: its level, the member count and the missing-bar count."""

    session_date: date
    level: Decimal
    members: int
    missing_bars: int
    #: The level under the total-loss sensitivity (a missing bar is -100 %).
    level_total_loss: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkSeries:
    """Benchmark A over the calendar, with its construction record."""

    benchmark_id: str
    version: str
    points: tuple[BenchmarkPoint, ...]

    def bars(
        self, *, calendar: SessionCalendar, total_loss: bool = False
    ) -> tuple[PriceBarValues, ...]:
        """The index as a bar series the module can consume (open = high = low = close)."""
        out: list[PriceBarValues] = []
        for point in self.points:
            close = session_close(calendar, point.session_date)
            assert close is not None
            level = point.level_total_loss if total_loss else point.level
            out.append(
                PriceBarValues(
                    security_id=self.benchmark_id,
                    session_date=point.session_date,
                    bar_end_time=close,
                    open=level,
                    high=level,
                    low=level,
                    close=level,
                    volume=0,
                )
            )
        return tuple(out)

    def document(self) -> dict[str, Any]:
        """The closed construction record."""
        return {
            "benchmark_id": self.benchmark_id,
            "version": self.version,
            "points": [
                {
                    "session_date": p.session_date.isoformat(),
                    "level": str(p.level),
                    "level_total_loss": str(p.level_total_loss),
                    "members": p.members,
                    "missing_bars": p.missing_bars,
                }
                for p in self.points
            ],
        }

    @property
    def digest(self) -> str:
        """SHA-256 over the canonical construction record."""
        return hashlib.sha256(
            json.dumps(self.document(), sort_keys=True, separators=(",", ":")).encode("ascii")
        ).hexdigest()


def _bars_by_security(
    layer: ExploratoryResolvedLayer,
) -> dict[str, dict[date, ExploratoryResolvedRow]]:
    """The current revision of each ``(security, session)`` bar: highest revision wins."""
    out: dict[str, dict[date, ExploratoryResolvedRow]] = {}
    for item in layer.stocks:
        session = date_field(item.row.fields.get("date"))
        if session is None:
            continue
        held = out.setdefault(item.row.security_id, {})
        current = held.get(session)
        if current is None or item.row.revision_sequence > current.row.revision_sequence:
            held[session] = item
    return out


def unadjusted_close(row: ExploratoryResolvedRow) -> Decimal | None:
    """``closeunadj`` where present, else ``close`` -- the accepted preference."""
    value = decimal_field(row.row.fields.get("closeunadj"))
    return value if value is not None else decimal_field(row.row.fields.get("close"))


def split_factors(layer: ExploratoryResolvedLayer) -> dict[str, list[tuple[date, Decimal]]]:
    """Per security, every split ``(ex-date, ratio)`` from the actions, ascending by date."""
    out: dict[str, list[tuple[date, Decimal]]] = {}
    for item in layer.actions:
        fields = item.row.fields
        if fields.get("action") != ACTION_SPLIT:
            continue
        when = date_field(fields.get("date"))
        ratio = decimal_field(fields.get("value"))
        if when is None or ratio is None or ratio <= 0:
            continue
        out.setdefault(item.row.security_id, []).append((when, ratio))
    for splits in out.values():
        splits.sort()
    return out


def split_adjusted_factor(
    splits: list[tuple[date, Decimal]], session: date, *, through: date
) -> Decimal:
    """The forward-base-normalized factor for a bar at ``session`` as served at ``through``.

    Bars on or after the latest split are unchanged; earlier bars are divided by the product
    of every split ratio whose ex-date lies in ``(session, through]``. The accepted
    ``SPLIT_ONLY`` / ``FORWARD_BASE_NORMALIZED`` convention: today's price is today's price.
    """
    factor = _ONE
    for ex_date, ratio in splits:
        if session < ex_date <= through:
            factor *= ratio
    return factor


@dataclass(frozen=True, slots=True, kw_only=True)
class ExploratoryDataset:
    """What one research run reads. Research-only; never an A1 publication."""

    layer: ExploratoryResolvedLayer
    membership: UniverseSnapshot
    calendar: SessionCalendar
    benchmark: BenchmarkSeries
    as_of: datetime
    source_manifest_digest: str
    #: Memoized derived views (bars per security, benchmark bars). Never part of identity,
    #: equality or the digest; a pure function of the frozen fields above.
    cache: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def members_at(self, session: date) -> tuple[str, ...]:
        """The member set fixed at ``decision_time(session)``, sorted."""
        if "members" not in self.cache:
            members: dict[date, list[str]] = {}
            for row in self.membership.rows:
                if row.is_member:
                    members.setdefault(row.session_date, []).append(row.security_id)
            self.cache["members"] = {k: tuple(sorted(v)) for k, v in members.items()}
        members_by_session: dict[date, tuple[str, ...]] = self.cache["members"]
        return members_by_session.get(session, ())

    def benchmark_bars(self) -> tuple[PriceBarValues, ...]:
        """The benchmark as a bar series, memoized."""
        if "benchmark_bars" not in self.cache:
            self.cache["benchmark_bars"] = self.benchmark.bars(calendar=self.calendar)
        bars: tuple[PriceBarValues, ...] = self.cache["benchmark_bars"]
        return bars

    def _series(self, security_id: str, segment: int) -> tuple[PriceBarValues, ...]:
        """Every bar of ``security_id`` adjusted as of any ``through`` that lies after the
        first ``segment`` splits and before the next -- memoized per ``(security, segment)``.

        The forward-base factor of a bar at ``s`` served at ``through`` is the product of the
        ratios of splits with ``s < ex <= through``; it depends on ``through`` only through
        *which* splits have occurred, so one series per segment is exact.
        """
        key = f"series:{security_id}:{segment}"
        cached: tuple[PriceBarValues, ...] | None = self.cache.get(key)
        if cached is not None:
            return cached
        if "bars_by_security" not in self.cache:
            self.cache["bars_by_security"] = _bars_by_security(self.layer)
            self.cache["splits"] = split_factors(self.layer)
        held = self.cache["bars_by_security"].get(security_id, {})
        splits = self.cache["splits"].get(security_id, [])[:segment]
        out: list[PriceBarValues] = []
        for session in sorted(held):
            row = held[session]
            close = unadjusted_close(row)
            open_ = decimal_field(row.row.fields.get("open"))
            high = decimal_field(row.row.fields.get("high"))
            low = decimal_field(row.row.fields.get("low"))
            volume = decimal_field(row.row.fields.get("volume"))
            end = session_close(self.calendar, session)
            if None in (close, open_, high, low, volume) or end is None:
                continue
            assert close is not None and open_ is not None and high is not None
            assert low is not None and volume is not None
            factor = _ONE
            for ex_date, ratio in splits:
                if session < ex_date:
                    factor *= ratio
            out.append(
                PriceBarValues(
                    security_id=security_id,
                    session_date=session,
                    bar_end_time=end,
                    open=_q(open_ / factor),
                    high=_q(high / factor),
                    low=_q(low / factor),
                    close=_q(close / factor),
                    volume=int(volume * factor),
                )
            )
        series = tuple(out)
        self.cache[key] = series
        return series

    def raw_bars(self, security_id: str) -> tuple[PriceBarValues, ...]:
        """Every bar of ``security_id`` on its **own** session's basis -- the unadjusted prices
        and volume as delivered. This is what execution reads: a fill at ``open(s)`` is the
        price of session ``s``, and no split effective after ``s`` may reach back into it."""
        return self._series(security_id, 0)

    def split_factor_between(self, security_id: str, session: date, through: date) -> Decimal:
        """The product of the split ratios of ``security_id`` with ex-date in
        ``(session, through]`` -- the factor that carries a level stated on ``session``'s basis
        onto ``through``'s basis (divide by it)."""
        if "splits" not in self.cache:
            self.cache["bars_by_security"] = _bars_by_security(self.layer)
            self.cache["splits"] = split_factors(self.layer)
        return split_adjusted_factor(
            self.cache["splits"].get(security_id, []), session, through=through
        )

    def splits_between(
        self, security_id: str, after: date | None, through: date
    ) -> tuple[tuple[date, Decimal], ...]:
        """The splits of ``security_id`` with ex-date in ``(after, through]``, ascending."""
        if "splits" not in self.cache:
            self.cache["bars_by_security"] = _bars_by_security(self.layer)
            self.cache["splits"] = split_factors(self.layer)
        return tuple(
            (ex_date, ratio)
            for ex_date, ratio in self.cache["splits"].get(security_id, [])
            if (after is None or ex_date > after) and ex_date <= through
        )

    def bars_through(
        self, security_id: str, through: date, *, count: int | None = None
    ) -> tuple[PriceBarValues, ...]:
        """The split-only adjusted bars of ``security_id`` with session <= ``through``.

        Every bar served is bounded at its own close (``AS_DATED``), so a bar dated ``through``
        is admissible only at or after ``close(through)`` -- the caller's cutoff decides.
        """
        if "splits" not in self.cache:
            self.cache["bars_by_security"] = _bars_by_security(self.layer)
            self.cache["splits"] = split_factors(self.layer)
        splits = self.cache["splits"].get(security_id, [])
        segment = sum(1 for ex_date, _ in splits if ex_date <= through)
        series = self._series(security_id, segment)
        lo, hi = 0, len(series)
        while lo < hi:
            mid = (lo + hi) // 2
            if series[mid].session_date <= through:
                lo = mid + 1
            else:
                hi = mid
        out = series[:lo]
        if count is not None:
            out = out[-count:]
        return out

    def document(self) -> dict[str, Any]:
        """The closed dataset document -- the content the publication digests."""
        return {
            "contract_id": DATASET_CONTRACT,
            "layer_digest": self.layer.digest,
            "membership": {
                "rule": self.membership.rule.document(),
                "rows": [row.document() for row in self.membership.rows],
                "census": [c.document() for c in self.membership.census],
                "undecidable_sessions": [
                    d.isoformat() for d in self.membership.undecidable_sessions
                ],
            },
            "calendar_version": self.calendar.version,
            "benchmark": self.benchmark.document(),
            "as_of": self.as_of.isoformat(),
            "source_manifest_digest": self.source_manifest_digest,
        }

    @property
    def content_digest(self) -> str:
        """SHA-256 over the canonical dataset document."""
        return hashlib.sha256(
            json.dumps(self.document(), sort_keys=True, separators=(",", ":")).encode("ascii")
        ).hexdigest()


def build_benchmark_a(
    layer: ExploratoryResolvedLayer, membership: UniverseSnapshot, *, calendar: SessionCalendar
) -> BenchmarkSeries:
    """Benchmark A over every calendar session (M0 §11.4)."""
    bars = _bars_by_security(layer)
    splits = split_factors(layer)
    members_by_session: dict[date, list[str]] = {}
    for row in membership.rows:
        if row.is_member:
            members_by_session.setdefault(row.session_date, []).append(row.security_id)
    level = INDEX_BASE
    level_total = INDEX_BASE
    points: list[BenchmarkPoint] = []
    previous: date | None = None
    for session in calendar.sessions:
        today = session.session_date
        members = sorted(members_by_session.get(today, []))
        returns: list[Decimal] = []
        returns_total: list[Decimal] = []
        missing = 0
        for security_id in members:
            held = bars.get(security_id, {})
            now_row = held.get(today)
            then_row = held.get(previous) if previous is not None else None
            now = unadjusted_close(now_row) if now_row is not None else None
            then = unadjusted_close(then_row) if then_row is not None else None
            if now is None or then is None or then <= 0 or previous is None:
                missing += 1
                returns.append(_ZERO)
                returns_total.append(-_ONE)
                continue
            # Both closes on the same forward base: only splits between the two sessions differ.
            factor = split_adjusted_factor(splits.get(security_id, []), previous, through=today)
            r = _q(now / (then / factor) - _ONE)
            returns.append(r)
            returns_total.append(r)
        if members:
            level = _q(level * (_ONE + sum(returns, _ZERO) / Decimal(len(members))))
            level_total = _q(
                level_total * (_ONE + sum(returns_total, _ZERO) / Decimal(len(members)))
            )
        points.append(
            BenchmarkPoint(
                session_date=today,
                level=level,
                level_total_loss=level_total,
                members=len(members),
                missing_bars=missing,
            )
        )
        previous = today
    return BenchmarkSeries(
        benchmark_id=BENCHMARK_A_ID, version=BENCHMARK_A_VERSION, points=tuple(points)
    )


def publish(
    dataset: ExploratoryDataset,
    *,
    publication_id: str,
    limitations: frozenset[ExploratoryLimitation],
) -> ExploratoryPublication:
    """The exploratory publication naming this dataset -- never an A1 ``VerifiedPublication``."""
    if type(dataset) is not ExploratoryDataset:
        raise TypeError("dataset must be an exact ExploratoryDataset")
    return ExploratoryPublication(
        publication_id=publication_id,
        content_digest=dataset.content_digest,
        provenance=ExploratoryProvenance(
            profile=ExploratoryProfile.EXPLORATORY_HINDSIGHT,
            derivation=ExploratoryDerivation.AS_DATED,
            limitations=limitations,
            source_manifest_digest=dataset.source_manifest_digest,
        ),
    )


__all__ = [
    "BENCHMARK_A_ID",
    "BENCHMARK_A_VERSION",
    "DATASET_CONTRACT",
    "BenchmarkPoint",
    "BenchmarkSeries",
    "ExploratoryDataset",
    "build_benchmark_a",
    "publish",
    "split_adjusted_factor",
    "split_factors",
    "unadjusted_close",
]
