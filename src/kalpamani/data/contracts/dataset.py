"""A curated Gold dataset: what a point-in-time query is served from.

A plain, immutable container of contract entities. It lives in ``contracts``
because both the curation layer that writes it and the point-in-time layer that
reads it need it, and neither should have to import the other.

**A universe snapshot is stored here, not recomputed.** ``universe`` is a mapping
from session date to the membership rows recorded for that session. A query for a
session the mapping has no entry for is a **refusal**, never an empty result: an
empty universe and an unanswerable question look identical in a result set and
mean opposite things.

``coverage_start`` is what makes "before our data begins" answerable. Without it a
query reaching further back than the dataset goes returns nothing and looks like a
market with no securities in it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from kalpamani.data.contracts.entities import (
    CorporateAction,
    Listing,
    MarketSession,
    PriceBar,
    SecurityAttribute,
    TickerHistory,
    UniverseMembership,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class GoldDataset:
    """One published, versioned curated build."""

    dataset_version: str
    build_time: datetime
    coverage_start: date
    coverage_end: date
    sessions: tuple[MarketSession, ...] = ()
    listings: tuple[Listing, ...] = ()
    attributes: tuple[SecurityAttribute, ...] = ()
    tickers: tuple[TickerHistory, ...] = ()
    bars: tuple[PriceBar, ...] = ()
    actions: tuple[CorporateAction, ...] = ()
    universe: Mapping[date, tuple[UniverseMembership, ...]] = field(default_factory=dict)

    def bars_for(self, security_id: str) -> tuple[PriceBar, ...]:
        """Every raw bar for one security, in canonical order."""
        return tuple(
            sorted(
                (bar for bar in self.bars if bar.security_id == security_id),
                key=lambda bar: bar.bar_end_time,
            )
        )

    def actions_for(self, security_id: str) -> tuple[CorporateAction, ...]:
        """Every corporate action for one security, in canonical order."""
        return tuple(
            sorted(
                (action for action in self.actions if action.security_id == security_id),
                key=lambda action: action.action_id,
            )
        )

    def session_on(self, session_date: date) -> MarketSession | None:
        """The calendar row for one session, if the dataset holds it."""
        for session in self.sessions:
            if session.session_date == session_date:
                return session
        return None


__all__ = ["GoldDataset"]
