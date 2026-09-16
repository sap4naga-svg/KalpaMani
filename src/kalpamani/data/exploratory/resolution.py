"""``AS_DATED`` resolution and exploratory membership (ADR-0051 §2.1, M0 specification §12.1).

**Separate from production P-2/P-3 by construction.** The accepted resolver
(``kalpamani.data.production.sharadar.availability``) bounds every row version at an
observed or evidenced instant and refuses any other derivation. This module bounds a row
version at an **assumed** instant taken from the row's own date:

* a ``stocks`` bar at the **close of its own session** (``open_at + REGULAR_SESSION``);
* a ``tickers`` attribute **at all times** (one instant before the first calendar session);
* an ``actions`` row at the **open of the first session on or after its date** -- the
  accepted public-bound rule -- or never, when the calendar cannot place it.

The result is an :class:`ExploratoryResolvedLayer` whose rows carry an
:class:`ExploratoryAvailability` -- **not** the accepted ``Availability``, which cannot
express ``AS_DATED``. Membership then reuses the accepted ``breakout-long-v1`` clauses
**unchanged**: :func:`decide_membership` mirrors ``universe.build_universe``'s session loop
(which refuses a non-accepted layer by exact type, correctly) and hands every decision to the
accepted clause function, whose clauses read only ``row.row`` (the Silver ``RowVersion``)
and ``row.availability.governing_time`` -- exactly the two things the exploratory row
provides. A conformance test holds that, given equal bounds, the exploratory path and the
accepted path decide identically; the only thing that differs is where the bound comes from,
and that is the whole point.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final, cast

import kalpamani.data.production.sharadar.universe as universe
from kalpamani.data.exploratory.vocabulary import (
    AvailabilityBasis,
    ExploratoryDerivation,
    ExploratoryProfile,
)
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.production.sharadar.availability import ResolvedLayer
from kalpamani.data.production.sharadar.sessions import SessionCalendar
from kalpamani.data.production.sharadar.silver import RowVersion, SilverLayer
from kalpamani.data.production.sharadar.universe import UniverseRule, UniverseSnapshot

#: The regular NYSE session length; the close is ``open_at + REGULAR_SESSION``. Early closes
#: are not modelled by this slice (M0 §12.1).
REGULAR_SESSION: Final = timedelta(hours=6, minutes=30)

#: An action the calendar cannot place is never admissible. The sentinel is aware and far
#: enough that no cutoff reaches it.
NEVER: Final = datetime(9999, 12, 31, tzinfo=UTC)

#: The exploratory resolution policy identity, recorded on every publication.
EXPLORATORY_RESOLUTION_VERSION: Final = "exploratory-as-dated-v1"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExploratoryAvailability:
    """The assumed bound one row version is served under. Research-only."""

    profile: ExploratoryProfile
    derivation: ExploratoryDerivation
    basis: AvailabilityBasis
    governing_time: datetime
    #: The instant the row was actually retrieved (P-2's bound) -- carried as evidence of how
    #: far the assumption reaches back, never used as the bound here.
    system_first_seen_time: datetime

    def __post_init__(self) -> None:
        if self.profile is not ExploratoryProfile.EXPLORATORY_HINDSIGHT:
            raise ValueError("exploratory availability carries the exploratory profile")
        if self.derivation is not ExploratoryDerivation.AS_DATED:
            raise ValueError("exploratory availability carries the AS_DATED derivation")
        if self.basis is not AvailabilityBasis.ASSUMED_HISTORICAL:
            raise ValueError("exploratory availability is assumed, never evidenced")
        if self.governing_time.tzinfo is None or self.system_first_seen_time.tzinfo is None:
            raise ValueError("instants are aware")

    def document(self) -> dict[str, Any]:
        """The closed document carried beside every exploratory row."""
        return {
            "profile": self.profile.value,
            "derivation": self.derivation.value,
            "availability_basis": self.basis.value,
            "governing_time": self.governing_time.isoformat(),
            "system_first_seen_time": self.system_first_seen_time.isoformat(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ExploratoryResolvedRow:
    """One Silver row version and the assumed bound it is served under."""

    row: RowVersion
    availability: ExploratoryAvailability

    def __repr__(self) -> str:
        """Derivation only."""
        return f"ExploratoryResolvedRow(derivation={self.availability.derivation.value!r})"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExploratoryResolvedLayer:
    """Every Silver row version with its assumed bound, per dataset, in Silver order."""

    tickers: tuple[ExploratoryResolvedRow, ...]
    stocks: tuple[ExploratoryResolvedRow, ...]
    actions: tuple[ExploratoryResolvedRow, ...]
    calendar_version: str
    resolution_version: str = EXPLORATORY_RESOLUTION_VERSION
    unplaceable_actions: int = 0

    def by_dataset(self, dataset: str) -> tuple[ExploratoryResolvedRow, ...]:
        """The rows of one dataset."""
        return {
            SharadarDataset.TICKERS.value: self.tickers,
            SharadarDataset.STOCKS.value: self.stocks,
            SharadarDataset.ACTIONS.value: self.actions,
        }[dataset]

    @property
    def digest(self) -> str:
        """SHA-256 over the canonical resolved document (rows, bounds, versions)."""
        return hashlib.sha256(
            json.dumps(self.document(), sort_keys=True, separators=(",", ":")).encode("ascii")
        ).hexdigest()

    def document(self) -> dict[str, Any]:
        """The closed document: every row's key, content and assumed bound."""
        return {
            "resolution_version": self.resolution_version,
            "calendar_version": self.calendar_version,
            "unplaceable_actions": self.unplaceable_actions,
            "rows": {
                name: [
                    {
                        "security_id": item.row.security_id,
                        "row_key": list(item.row.row_key),
                        "revision_sequence": item.row.revision_sequence,
                        "content_sha256": item.row.content_sha256,
                        "availability": item.availability.document(),
                    }
                    for item in rows
                ]
                for name, rows in (
                    ("tickers", self.tickers),
                    ("stocks", self.stocks),
                    ("actions", self.actions),
                )
            },
        }


def session_close(calendar: SessionCalendar, session_date: date) -> datetime | None:
    """``open_at + REGULAR_SESSION`` for a calendar session, else ``None``."""
    opened = calendar.open_at(session_date)
    return None if opened is None else opened + REGULAR_SESSION


def _first_open_on_or_after(calendar: SessionCalendar, when: date) -> datetime | None:
    for session in calendar.sessions:
        if session.session_date >= when:
            return session.open_at
    return None


def _always(calendar: SessionCalendar) -> datetime:
    return calendar.sessions[0].open_at - timedelta(days=1)


def _bound_for(row: RowVersion, calendar: SessionCalendar) -> datetime | None:
    """The assumed bound of one row, or ``None`` when the calendar cannot place it."""
    if row.dataset == SharadarDataset.TICKERS.value:
        return _always(calendar)
    text = row.fields.get("date")
    try:
        when = date.fromisoformat(text) if text is not None else None
    except ValueError:
        when = None
    if when is None:
        return None
    if row.dataset == SharadarDataset.STOCKS.value:
        return session_close(calendar, when)
    return _first_open_on_or_after(calendar, when)


def resolve_as_dated(layer: SilverLayer, *, calendar: SessionCalendar) -> ExploratoryResolvedLayer:
    """Bound every Silver row version at its assumed instant. Deterministic; no clock."""
    if type(layer) is not SilverLayer:
        raise TypeError("layer must be an exact SilverLayer")
    if type(calendar) is not SessionCalendar:
        raise TypeError("calendar must be an exact SessionCalendar")
    unplaceable = 0

    def resolve_rows(rows: tuple[RowVersion, ...]) -> tuple[ExploratoryResolvedRow, ...]:
        nonlocal unplaceable
        out: list[ExploratoryResolvedRow] = []
        for row in rows:
            bound = _bound_for(row, calendar)
            if bound is None:
                unplaceable += 1
                bound = NEVER
            out.append(
                ExploratoryResolvedRow(
                    row=row,
                    availability=ExploratoryAvailability(
                        profile=ExploratoryProfile.EXPLORATORY_HINDSIGHT,
                        derivation=ExploratoryDerivation.AS_DATED,
                        basis=AvailabilityBasis.ASSUMED_HISTORICAL,
                        governing_time=bound,
                        system_first_seen_time=row.system_first_seen_time,
                    ),
                )
            )
        return tuple(out)

    tickers = resolve_rows(layer.tickers.rows)
    stocks = resolve_rows(layer.stocks.rows)
    actions = resolve_rows(layer.actions.rows)
    return ExploratoryResolvedLayer(
        tickers=tickers,
        stocks=stocks,
        actions=actions,
        calendar_version=calendar.version,
        unplaceable_actions=unplaceable,
    )


def decide_membership(
    layer: ExploratoryResolvedLayer,
    *,
    rule: UniverseRule,
    calendar: SessionCalendar,
    sessions: tuple[date, ...],
    as_of: datetime,
) -> UniverseSnapshot:
    """The accepted ``breakout-long-v1`` clauses over exploratory bounds.

    ``universe.build_universe`` refuses any layer that is not the accepted
    ``ResolvedLayer`` -- correctly: that exact-type check is part of the isolation. So this
    function mirrors its session loop exactly (decision time, previous session, undecidable
    sessions, the ``min(decision, as_of)`` cutoff, the census) and hands each decision to the
    accepted clause function ``universe._decide`` **unchanged**, through the accepted index
    ``universe._index``. Both read only ``row.row`` (the Silver ``RowVersion``) and
    ``row.availability.governing_time``, which :class:`ExploratoryResolvedRow` carries; the
    cast is the one place a research-typed layer reaches accepted code, and a conformance
    test holds the two paths equal under equal bounds. The 252-session history clause,
    the decision cutoff ``open(d) - margin`` and every exclusion reason are the accepted ones.
    """
    if type(layer) is not ExploratoryResolvedLayer or type(rule) is not UniverseRule:
        raise TypeError("layer and rule must be exact")
    if type(calendar) is not SessionCalendar:
        raise TypeError("calendar must be an exact SessionCalendar")
    if len(sessions) > universe.MAX_DECISION_SESSIONS or list(sessions) != sorted(set(sessions)):
        raise ValueError("sessions are distinct, ascending and bounded")
    if type(as_of) is not datetime or as_of.tzinfo is None:
        raise TypeError("as_of must be an aware datetime")
    facts = universe._index(cast(ResolvedLayer, layer))  # the accepted clauses, unchanged
    securities = sorted(facts)
    rows: list[universe.MembershipRow] = []
    census: list[universe.SessionCensus] = []
    undecidable: list[date] = []
    for session in sessions:
        decision = calendar.decision_time(session, margin=rule.decision_margin)
        previous = calendar.previous(session)
        if decision is None or previous is None:
            undecidable.append(session)
            continue
        cutoff = min(decision, as_of)
        determinable = unavailable = members = 0
        for security_id in securities:
            decided = universe._decide(  # the accepted clauses, unchanged
                security_id,
                facts[security_id],
                session=session,
                cutoff=cutoff,
                previous=previous,
                rule=rule,
                calendar=calendar,
            )
            rows.append(decided)
            if decided.exclusion_reason is universe.BuildExclusionReason.ATTRIBUTE_UNAVAILABLE:
                unavailable += 1
            else:
                determinable += 1
            members += int(decided.is_member)
        census.append(
            universe.SessionCensus(
                session_date=session,
                securities=len(securities),
                attribute_determinable=determinable,
                attribute_unavailable=unavailable,
                members=members,
            )
        )
    return UniverseSnapshot(
        rule=rule, rows=tuple(rows), census=tuple(census), undecidable_sessions=tuple(undecidable)
    )


def decide_membership_all(
    layer: ExploratoryResolvedLayer,
    *,
    rule: UniverseRule,
    calendar: SessionCalendar,
    as_of: datetime,
) -> UniverseSnapshot:
    """Membership for every calendar session, decided in blocks of the accepted per-call
    bound (``MAX_DECISION_SESSIONS``) and concatenated in calendar order. No clause changes."""
    sessions = tuple(s.session_date for s in calendar.sessions)
    rows: list[universe.MembershipRow] = []
    census: list[universe.SessionCensus] = []
    undecidable: list[date] = []
    step = universe.MAX_DECISION_SESSIONS
    for start in range(0, len(sessions), step):
        block = decide_membership(
            layer,
            rule=rule,
            calendar=calendar,
            sessions=sessions[start : start + step],
            as_of=as_of,
        )
        rows.extend(block.rows)
        census.extend(block.census)
        undecidable.extend(block.undecidable_sessions)
    return UniverseSnapshot(
        rule=rule, rows=tuple(rows), census=tuple(census), undecidable_sessions=tuple(undecidable)
    )


__all__ = [
    "EXPLORATORY_RESOLUTION_VERSION",
    "NEVER",
    "REGULAR_SESSION",
    "ExploratoryAvailability",
    "ExploratoryResolvedLayer",
    "ExploratoryResolvedRow",
    "decide_membership",
    "decide_membership_all",
    "resolve_as_dated",
    "session_close",
]
