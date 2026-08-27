"""Silver normalisation: Bronze bytes to normalised source facts.

**Silver is where vendor semantics stop.** Above this layer nothing knows which
vendor supplied anything, except through the provenance envelope carried for
audit. Tickers become ``security_id``; local timestamps become UTC instants with
their exact-or-bound derivation named; vendor revision conventions become
``revision_sequence`` rows.

Two rules do most of the work here, and both exist because their absence
produces look-ahead that no later check can recover:

**A session date is an exchange-calendar key, never a truncated UTC timestamp.**
A 20:00 ET bar belongs to that session and to the *next* UTC day, so deriving the
session from the instant is a full day of look-ahead. Normalisation therefore
takes a calendar and looks the session up; a bar whose instant falls in no known
session is refused rather than guessed at.

**Availability is derived by the ladder, never copied from a vendor field.** An
exact rule writes an exact field; anything approximate writes a bound field and
names its derivation. A daily bar that is officially disseminated carries no
per-bar publication instant, so its public timing is a
``SESSION_CLOSE_PLUS_LAG`` **bound** -- not an exact time that happens to look
precise.

The payload shape this module parses is **KalpaMani's own vendor-neutral Bronze
envelope**, not any provider's format. No provider has been selected (gate G1),
so there is no vendor payload to map, and inventing one would be guessing at a
decision that has not been made.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from kalpamani.data.contracts.entities import MarketSession, PriceBar
from kalpamani.data.contracts.envelope import FactAnchor, SourceEnvelope
from kalpamani.data.contracts.errors import PointInTimeError
from kalpamani.data.contracts.vocabulary import (
    BAR_CONSTRUCTION_ORIGIN,
    BarConstruction,
    BarResolution,
    ProviderBoundDerivation,
    ProviderTimeDerivation,
    PublicBoundDerivation,
    PublicTimeDerivation,
    QualityStatus,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionCalendar:
    """A lookup from instant to exchange session. Never a truncation.

    Built from :class:`~kalpamani.data.contracts.entities.MarketSession` rows,
    which are themselves point-in-time facts with their own availability.
    """

    sessions: tuple[MarketSession, ...]

    def session_of(self, instant: datetime) -> date | None:
        """The session ``instant`` belongs to, or ``None`` if it falls in none."""
        for session in self.sessions:
            if session.contains(instant):
                return session.session_date
        return None

    def session_on(self, session_date: date) -> MarketSession | None:
        """The session row for ``session_date``, if the calendar has one."""
        for session in self.sessions:
            if session.session_date == session_date:
                return session
        return None

    def trading_sessions(self) -> tuple[MarketSession, ...]:
        """Sessions on which trading actually occurred, in date order."""
        return tuple(
            sorted(
                (s for s in self.sessions if not s.is_holiday),
                key=lambda s: s.session_date,
            )
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class BarLagPolicy:
    """The declared, versioned lag that bounds an officially disseminated bar.

    A lag is an approximation with a name and a version, not a default. It writes
    an upper **bound**, never an exact field, and every result that depended on
    it reports so.
    """

    lag_policy_version: str
    session_close_lag: timedelta


def normalize_price_bars(
    payload: bytes,
    *,
    calendar: SessionCalendar,
    lag_policy: BarLagPolicy,
    provider: str,
    dataset_version: str,
    ingestion_time: datetime,
    system_first_seen_time: datetime,
    provider_available_time: datetime | None,
    bronze_sha256: str,
) -> tuple[PriceBar, ...]:
    """Turn Bronze payload bytes into normalised raw :class:`PriceBar` facts.

    ``provider_available_time`` is exact when the caller established it by a file
    drop and ``None`` otherwise; a ``None`` is left as a **gap** for the profile
    resolution to handle by ``EXCLUDE``, ``BOUND`` or ``DOWNGRADE``, and is never
    filled in here from something that merely resembles it.

    Raises:
        PointInTimeError: if a bar's endpoint belongs to no known session. The
            session key is not derivable from the instant, and guessing it is a
            full day of look-ahead.
    """
    decoded: Any = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, Mapping):
        raise PointInTimeError("Bronze payload is not an object; refusing to guess its shape.")
    rows: Sequence[Any] = decoded["bars"]

    bars: list[PriceBar] = []
    for row in rows:
        bar_end_time = _instant(row["bar_end_time"])
        session_date = calendar.session_of(bar_end_time)
        if session_date is None:
            raise PointInTimeError(
                f"Bar ending {bar_end_time.isoformat()} falls in no known exchange session. "
                "A session date is a calendar key, never a truncated UTC timestamp -- "
                "deriving one here would be a full day of look-ahead."
            )
        session = calendar.session_on(session_date)
        assert session is not None

        construction = BarConstruction(row["bar_construction"])
        bars.append(
            PriceBar(
                security_id=row["security_id"],
                resolution=BarResolution(row["resolution"]),
                bar_end_time=bar_end_time,
                bar_start_time=_instant(row["bar_start_time"]),
                session_date=session_date,
                open=Decimal(row["open"]),
                high=Decimal(row["high"]),
                low=Decimal(row["low"]),
                close=Decimal(row["close"]),
                volume=int(row["volume"]),
                curation_source=f"bronze:{bronze_sha256}",
                bar_construction=construction,
                envelope=SourceEnvelope(
                    information_origin=BAR_CONSTRUCTION_ORIGIN[construction],
                    # No per-bar publication instant exists, so public timing is a
                    # declared bound, and the exact field stays null.
                    public_available_time=None,
                    public_available_upper_bound=(
                        session.regular_close + lag_policy.session_close_lag
                        if construction is BarConstruction.OFFICIAL_DISSEMINATED
                        else None
                    ),
                    public_time_derivation=(
                        PublicTimeDerivation.UNKNOWN
                        if construction is BarConstruction.OFFICIAL_DISSEMINATED
                        else PublicTimeDerivation.NOT_APPLICABLE
                    ),
                    public_bound_derivation=(
                        PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG
                        if construction is BarConstruction.OFFICIAL_DISSEMINATED
                        else PublicBoundDerivation.NONE
                    ),
                    provider_available_time=provider_available_time,
                    provider_time_derivation=(
                        ProviderTimeDerivation.FILE_DROP
                        if provider_available_time is not None
                        else ProviderTimeDerivation.UNKNOWN
                    ),
                    provider_bound_derivation=ProviderBoundDerivation.NONE,
                    system_first_seen_time=system_first_seen_time,
                    # The declared domain alias: bar_end_time IS the retrospective
                    # anchor, so "a bar cannot be available before it closed" is a
                    # real check at either resolution.
                    anchor=FactAnchor.retrospective(bar_end_time),
                    source_id=f"{row['security_id']}:{row['resolution']}:{row['bar_end_time']}",
                    ingestion_time=ingestion_time,
                    dataset_version=dataset_version,
                    quality_status=QualityStatus.OK,
                    provider=provider,
                ),
            )
        )
    return tuple(bars)


def _instant(raw: object) -> datetime:
    if not isinstance(raw, str):
        raise PointInTimeError(f"Expected an ISO instant, got {type(raw).__name__}.")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        raise PointInTimeError(
            f"Bronze payload instant {raw!r} carries no offset. Local wall-clock times are "
            "never stored without one; a fixed offset is never assumed."
        )
    return parsed


__all__ = [
    "BarLagPolicy",
    "SessionCalendar",
    "normalize_price_bars",
]
