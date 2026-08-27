"""A curated Gold dataset: what a point-in-time query is served from.

An immutable container of contract entities. It lives in ``contracts`` because
both the curation layer that writes it and the point-in-time layer that reads it
need it, and neither should have to import the other.

**It carries the receipt that says which policy admitted its rows.** A dataset
assembled from arbitrary rows has none, and a build nobody can account for is not
publishable however correct its rows happen to be. ``resolved_profile`` and
``resolution_policy_version`` are properties of the build, not of the caller
reading it: a dataset curated under ``PUBLIC_PIT`` cannot answer a
``PROVIDER_REALISTIC_PIT`` question, and a reader configured differently is
refused rather than served something relabelled.

**A universe snapshot is stored here, not recomputed.** ``universe`` maps a
session date to the membership rows recorded for it, and ``universe_headers``
records that the session was *built* -- including when it legitimately produced
no rows. Without a header a zero-row snapshot vanishes the moment the membership
table is flattened, and "the rule selected nobody" becomes indistinguishable from
"no snapshot exists". Those are opposite answers.

**Frozen means frozen.** Mappings are wrapped in ``MappingProxyType`` at
construction, so ``frozen=True`` does not merely wrap a dict anyone can mutate
afterwards. An artifact whose contents can change after its hash was taken is not
an artifact.
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
from kalpamani.data.contracts.instants import normalize_instant
from kalpamani.data.contracts.profiles import DatasetResolutionEvidence, ResolutionReceipt
from kalpamani.data.contracts.vocabulary import InformationSetProfile


@dataclass(frozen=True, slots=True, kw_only=True)
class UniverseSnapshotHeader:
    """Evidence that a universe snapshot was **built** for a session.

    Separate from the membership rows on purpose. A snapshot whose rule
    legitimately selected nobody has zero member rows, and a session that was
    never built has zero rows too. Only the header distinguishes them, and the
    distinction is the difference between "nobody qualified" and "we cannot
    answer".
    """

    session_date: date
    universe_definition_version: str
    resolved_profile: InformationSetProfile
    evaluation_cutoff: datetime
    row_count: int
    snapshot_content_hash: str
    derivation_spec_version: str
    status: str = "COMPLETE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluation_cutoff", normalize_instant(self.evaluation_cutoff))


@dataclass(frozen=True, slots=True, kw_only=True)
class GoldDataset:
    """One curated build, carrying the receipt that accounts for its rows."""

    dataset_version: str
    build_time: datetime
    coverage_start: date
    coverage_end: date
    #: The profile this build actually resolved to. A downgraded run produces
    #: PUBLIC_PIT artifacts, because that is what it computed.
    resolved_profile: InformationSetProfile
    #: Which policy resolved this build's provider-timing gaps.
    resolution_policy_version: str
    #: Proof of which policy admitted these rows. Publication verifies it.
    resolution_receipt: ResolutionReceipt
    resolution_evidence: tuple[DatasetResolutionEvidence, ...] = ()
    sessions: tuple[MarketSession, ...] = ()
    listings: tuple[Listing, ...] = ()
    attributes: tuple[SecurityAttribute, ...] = ()
    tickers: tuple[TickerHistory, ...] = ()
    bars: tuple[PriceBar, ...] = ()
    actions: tuple[CorporateAction, ...] = ()
    universe: Mapping[date, tuple[UniverseMembership, ...]] = field(default_factory=dict)
    universe_headers: Mapping[date, UniverseSnapshotHeader] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Deep-freeze: a frozen dataclass wrapping a mutable dict is not frozen.
        object.__setattr__(self, "universe", MappingProxyType(dict(sorted(self.universe.items()))))
        object.__setattr__(
            self,
            "universe_headers",
            MappingProxyType(dict(sorted(self.universe_headers.items()))),
        )
        object.__setattr__(self, "build_time", normalize_instant(self.build_time))

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

    def trading_sessions_between(
        self,
        start: date,
        end: date,
        *,
        exchange: str | None = None,
    ) -> tuple[date, ...]:
        """Session dates on which the venue traded, within an inclusive range.

        ``exchange`` matters: a security listed on one venue is not required to
        have bars on another venue's sessions, and pooling calendars would fault
        it for absences that are not absences.
        """
        return tuple(
            sorted(
                session.session_date
                for session in self.sessions
                if not session.is_holiday
                and start <= session.session_date <= end
                and (exchange is None or session.exchange.value == exchange)
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

    def snapshot_was_built(self, session_date: date) -> bool:
        """Whether a universe snapshot exists for this session, rows or no rows."""
        return session_date in self.universe_headers

    def built_snapshot_sessions(self) -> tuple[date, ...]:
        """Every session a snapshot was built for, in order."""
        return tuple(sorted(self.universe_headers))


__all__ = ["GoldDataset", "UniverseSnapshotHeader"]
