"""A curated Gold dataset: what a point-in-time query is served from.

A plain, immutable container of contract entities. It lives in ``contracts``
because both the curation layer that writes it and the point-in-time layer that
reads it need it, and neither should have to import the other.

**It carries the resolution it was built under.** ``resolved_profile`` and
``resolution_policy_version`` are properties of the build, not of the caller
reading it: a dataset curated under ``PUBLIC_PIT`` cannot answer a
``PROVIDER_REALISTIC_PIT`` question, and a reader configured differently is
refused rather than served. The per-dataset resolution evidence travels with it
for the same reason -- a run cannot claim a resolution the build did not apply.

**A universe snapshot is stored here, not recomputed.** ``universe`` is a mapping
from session date to the membership rows recorded for that session. A query for a
session the mapping has no entry for is a **refusal**, never an empty result: an
empty universe and an unanswerable question look identical in a result set and
mean opposite things.

**Frozen means frozen.** The mapping is wrapped in a ``MappingProxyType`` at
construction, so ``frozen=True`` does not merely wrap a dict anyone can mutate
afterwards. An artifact whose contents can change after its hash was taken is not
an artifact.

``coverage_start`` and ``coverage_end`` are what make "outside our data"
answerable. Without them a query reaching past what the build holds returns
nothing and looks like a market with no securities in it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from types import MappingProxyType

from kalpamani.data.contracts.entities import (
    CorporateAction,
    Listing,
    MarketSession,
    PriceBar,
    SecurityAttribute,
    TickerHistory,
    UniverseMembership,
)
from kalpamani.data.contracts.profiles import DatasetResolutionEvidence
from kalpamani.data.contracts.vocabulary import InformationSetProfile


@dataclass(frozen=True, slots=True, kw_only=True)
class GoldDataset:
    """One published, versioned curated build."""

    dataset_version: str
    build_time: datetime
    coverage_start: date
    coverage_end: date
    #: The profile this build actually resolved to. A downgraded run produces
    #: PUBLIC_PIT artifacts, because that is what it computed.
    resolved_profile: InformationSetProfile
    #: Which policy resolved this build's provider-timing gaps.
    resolution_policy_version: str
    resolution_evidence: tuple[DatasetResolutionEvidence, ...] = ()
    sessions: tuple[MarketSession, ...] = ()
    listings: tuple[Listing, ...] = ()
    attributes: tuple[SecurityAttribute, ...] = ()
    tickers: tuple[TickerHistory, ...] = ()
    bars: tuple[PriceBar, ...] = ()
    actions: tuple[CorporateAction, ...] = ()
    universe: Mapping[date, tuple[UniverseMembership, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Deep-freeze: a frozen dataclass wrapping a mutable dict is not frozen.
        object.__setattr__(
            self,
            "universe",
            MappingProxyType(dict(sorted(self.universe.items()))),
        )

    def bars_for(self, security_id: str, resolution: str | None = None) -> tuple[PriceBar, ...]:
        """Raw bars for one security, optionally at one resolution, in canonical order.

        ``resolution`` is not optional in practice -- the query layer always
        passes it, because a series mixing daily and minute rows is not a series.
        It stays optional here only for whole-security integrity checks.
        """
        selected = (
            bar
            for bar in self.bars
            if bar.security_id == security_id
            and (resolution is None or bar.resolution.value == resolution)
        )
        return tuple(sorted(selected, key=lambda bar: bar.bar_end_time))

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

    def trading_sessions_between(self, start: date, end: date) -> tuple[date, ...]:
        """Session dates on which the venue traded, within an inclusive range."""
        return tuple(
            sorted(
                session.session_date
                for session in self.sessions
                if not session.is_holiday and start <= session.session_date <= end
            )
        )

    def knows_security(self, security_id: str) -> bool:
        """Whether the dataset holds any evidence of this security at all.

        A security the dataset has never heard of is a question it cannot answer.
        A security it knows that simply did not trade is an answer.
        """
        if any(listing.security_id == security_id for listing in self.listings):
            return True
        if any(bar.security_id == security_id for bar in self.bars):
            return True
        return any(attribute.security_id == security_id for attribute in self.attributes)


__all__ = ["GoldDataset"]
