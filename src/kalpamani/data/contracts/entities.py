"""The Phase-3A conceptual entity subset, as immutable typed contracts.

Vendor-neutral. Nothing here knows which provider supplied anything, except
through the provenance envelope carried for audit.

Only the Phase-3A subset is defined (``conceptual-schema.md`` 1, 1a, 2-7, 7a, 16,
17, 18). Filings, fundamentals, earnings, estimates, transcripts and borrow are
Phase-3B and 3C and are **not** defined here: a schema with no data behind it is
a promise, and this slice is not authorized to make Phase-3B promises.

Two structural rules run through every entity:

**One row, one origin, one class, one envelope** (schema 0.0). If two values on a
row can change at different times, for different reasons, from different
sources, they are two facts. They may share an identifier; they may not share an
envelope. ``listing`` is the visible case: a delisting *announced* on Monday and
*effective* on Friday is two facts, so ``listing_fact_kind`` is a primary-key
part rather than a hint.

**A source entity never contains a derived row.** Raw bars and bars we resampled
are separate entities (:class:`PriceBar` and
:class:`AggregatedPriceBarArtifact`), because a resampled bar carrying the source
envelope could satisfy neither set of rules.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Self

from kalpamani.data.contracts.envelope import DerivedEnvelope, SourceEnvelope
from kalpamani.data.contracts.instants import normalize_instant
from kalpamani.data.contracts.resolution import PitRecord
from kalpamani.data.contracts.vocabulary import (
    AdjustmentConvention,
    AdjustmentPolicy,
    BarConstruction,
    BarResolution,
    CorporateActionType,
    DelistingReason,
    Exchange,
    InformationSetProfile,
    IngestionStatus,
    IssueStatus,
    ListingFactKind,
    QualitySeverity,
    StorageLayer,
    TemporalFactClass,
    TickerChangeReason,
    UniverseExclusionReason,
)


def _normalize_instants(target: object, *names: str) -> None:
    """Rewrite each named instant field in place to canonical UTC at construction.

    An entity cannot retain the offset the ingestion process happened to hold:
    two spellings of one instant would otherwise store different bytes and hash
    to different identities.
    """
    for name in names:
        value = getattr(target, name)
        if value is not None:
            object.__setattr__(target, name, normalize_instant(value))


# ---------------------------------------------------------------------------
# Bases
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceFact:
    """Base for every entity carrying the source envelope."""

    dataset: str
    envelope: SourceEnvelope

    def with_envelope(self, envelope: SourceEnvelope) -> Self:
        """Return a copy carrying ``envelope``. Rows are never mutated in place."""
        return dataclasses.replace(self, envelope=envelope)


@dataclass(frozen=True, slots=True, kw_only=True)
class DerivedArtifact:
    """Base for every entity carrying the derived envelope.

    ``inputs`` are the resolved records consumed; ``envelope.lineage`` is the
    replayable description of them. Both exist because availability needs the
    first and reproducibility needs the second.
    """

    dataset: str
    envelope: DerivedEnvelope
    inputs: tuple[PitRecord, ...]


# ---------------------------------------------------------------------------
# 1 / 1a -- identity and attributes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class Security(DerivedArtifact):
    """Canonical internal identity. ``EVENT_REFERENCED`` / ``DERIVED_ARTIFACT``.

    The ``security_id`` is *ours*: we assign it by resolving external evidence
    into one durable identity. That is a derivation, not an observation.

    ``is_common_stock_eligible`` is deliberately **not** here. Eligibility is a
    versioned rule applied to attributes, not a property of a company, so it
    lives with the rule -- on :class:`UniverseMembership`, keyed by
    ``universe_definition_version``.
    """

    dataset: str = "security"
    security_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SecurityAttribute(SourceFact):
    """Externally sourced, time-varying attribute. ``SAMPLED_STATE``, origin per row."""

    dataset: str = "security_attribute"
    security_id: str
    attribute: str
    valid_from: date
    valid_to: date | None = None
    value: str

    @property
    def primary_key(self) -> tuple[str, str, date]:
        """``(security_id, attribute, valid_from)``."""
        return (self.security_id, self.attribute, self.valid_from)


# ---------------------------------------------------------------------------
# 2 -- listing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class Listing(SourceFact):
    """A listing state, or an announcement that one is about to change.

    ``listing_fact_kind`` is a primary-key part so the two facts cannot collapse
    into one row, and it selects which anchor a check reads: ``STATE`` is
    ``RETROSPECTIVE`` and anchored on ``observation_time``;
    ``CHANGE_ANNOUNCEMENT`` is ``ANNOUNCED_FORWARD`` and anchored on the
    announcement.
    """

    dataset: str = "listing"
    listing_id: str
    security_id: str
    exchange: Exchange
    listing_start: date
    listing_end: date | None = None
    delisting_reason: DelistingReason | None = None
    successor_security_id: str | None = None
    listing_fact_kind: ListingFactKind

    @property
    def primary_key(self) -> tuple[str, str]:
        """``(listing_id, listing_fact_kind)``."""
        return (self.listing_id, self.listing_fact_kind.value)

    def is_listed_on(self, session_date: date) -> bool:
        """Whether this listing state covers ``session_date``.

        Only a ``STATE`` row describes a listing; an announcement describes a
        change that has not happened yet.
        """
        if self.listing_fact_kind is not ListingFactKind.STATE:
            return False
        if session_date < self.listing_start:
            return False
        return self.listing_end is None or session_date <= self.listing_end


# ---------------------------------------------------------------------------
# 3 -- ticker history
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class TickerHistory(SourceFact):
    """Ticker-to-security mapping over time. ``RETROSPECTIVE`` / ``AUTHORITATIVE_PUBLIC``.

    Keyed on ``(ticker, valid_from)`` because **tickers are recycled**. For any
    ``(ticker, date)`` there is at most one ``security_id``; an overlap is
    BLOCKING, because an overlap makes every join on that ticker ambiguous.
    """

    dataset: str = "ticker_history"
    security_id: str
    ticker: str
    valid_from: date
    valid_to: date | None = None
    change_reason: TickerChangeReason | None = None

    @property
    def primary_key(self) -> tuple[str, date]:
        """``(ticker, valid_from)``."""
        return (self.ticker, self.valid_from)

    def covers(self, on: date) -> bool:
        """Whether this mapping is in force on ``on``."""
        if on < self.valid_from:
            return False
        return self.valid_to is None or on <= self.valid_to


# ---------------------------------------------------------------------------
# 5 -- market session
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketSession(SourceFact):
    """One exchange session. ``ANNOUNCED_FORWARD`` / ``AUTHORITATIVE_PUBLIC``.

    Calendars are published in advance, which is exactly why the blanket
    "availability must not precede observation" rule was wrong: a 2027 holiday
    schedule known in 2026 is a correct, non-leaking fact.

    ``session_date`` is the canonical session key. It is **never** derived by
    truncating a UTC instant: a 20:00 ET print belongs to that session and to the
    next UTC day, and confusing the two is a full day of look-ahead.
    """

    dataset: str = "market_session"
    exchange: Exchange
    session_date: date
    regular_open: datetime
    regular_close: datetime
    extended_open: datetime
    extended_close: datetime
    is_half_day: bool = False
    is_holiday: bool = False

    def __post_init__(self) -> None:
        _normalize_instants(
            self, "regular_open", "regular_close", "extended_open", "extended_close"
        )

    @property
    def primary_key(self) -> tuple[str, date]:
        """``(exchange, session_date)``."""
        return (self.exchange.value, self.session_date)

    def contains(self, instant: datetime) -> bool:
        """Whether ``instant`` falls inside this session's extended hours."""
        return self.extended_open <= instant <= self.extended_close


# ---------------------------------------------------------------------------
# 6 / 6a -- bars
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceBar(SourceFact):
    """A raw traded bar. The canonical curated Gold record.

    Keyed on ``(security_id, resolution, bar_end_time)``. An earlier revision
    keyed on ``(security_id, session_date, resolution)``, which **cannot
    represent minute bars at all** -- every minute of a session collided on one
    row. Identity is now the bar's own endpoint; ``session_date`` remains the
    exchange-calendar join key, and the two are deliberately different things.

    Only raw bars are facts. Adjusted series are computed, and if materialised
    live in :class:`AdjustedBarArtifact` -- never here, and never as an extra
    column.

    ``information_origin`` is per row and follows ``bar_construction``: a
    consolidated-tape bar is an authoritative public fact; a bar the vendor
    aggregated from its own trade collection is the vendor's construction. Which
    applies to purchased bars is established by provider qualification (test P9),
    not assumed -- and if it turns out to be the latter, price data and
    everything derived from it are ineligible under ``PUBLIC_PIT``.
    """

    dataset: str = "price_bar"
    security_id: str
    resolution: BarResolution
    bar_end_time: datetime
    bar_start_time: datetime
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    trade_count: int | None = None
    vwap: Decimal | None = None
    is_stale: bool = False
    had_halt: bool = False
    curation_source: str
    bar_construction: BarConstruction

    def __post_init__(self) -> None:
        _normalize_instants(self, "bar_end_time", "bar_start_time")

    @property
    def primary_key(self) -> tuple[str, str, datetime]:
        """``(security_id, resolution, bar_end_time)``."""
        return (self.security_id, self.resolution.value, self.bar_end_time)

    @property
    def observation_time(self) -> datetime:
        """The declared ``RETROSPECTIVE`` anchor: a bar cannot be available before it closed."""
        return self.bar_end_time


@dataclass(frozen=True, slots=True, kw_only=True)
class AggregatedPriceBarArtifact(DerivedArtifact):
    """Bars **we** built by resampling finer-grained rows we hold. ``INTERVAL``.

    Its eligibility is the intersection of its inputs': resampling
    provider-aggregated minute bars cannot produce a publicly-available daily bar.
    """

    dataset: str = "aggregated_price_bar_artifact"
    artifact_id: str
    security_id_scope: str
    target_resolution: BarResolution
    source_resolution: BarResolution
    resolved_profile: InformationSetProfile
    series: tuple[PriceBarValues, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceBarValues:
    """The numeric payload of one bar in a derived series. Not a fact on its own."""

    security_id: str
    session_date: date
    bar_end_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    def __post_init__(self) -> None:
        _normalize_instants(self, "bar_end_time")


# ---------------------------------------------------------------------------
# 7 / 7a -- corporate actions and adjustment
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class CorporateAction(SourceFact):
    """An announced corporate action. ``ANNOUNCED_FORWARD`` / ``AUTHORITATIVE_PUBLIC``.

    ``ex_date`` and the other effective dates **may be far later than
    availability. That is correct, not a violation** -- it is the entire class.

    Two rules that read alike and are not:

    - **Availability** derives from the announcement, never from ``ex_date``. A
      split announced 1 May is knowable on 2 May.
    - **Adjustment** may only be applied to bars from ``ex_date`` onward, and
      only if the action was admissible at ``as_of``. Knowing about a future
      split and applying it are two different operations, and only the second is
      look-ahead.
    """

    dataset: str = "corporate_action"
    action_id: str
    security_id: str
    action_type: CorporateActionType
    announcement_date: date | None = None
    ex_date: date | None = None
    record_date: date | None = None
    pay_date: date | None = None
    effective_date: date | None = None
    ratio: Decimal | None = None
    cash_amount: Decimal | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AdjustedBarArtifact(DerivedArtifact):
    """A materialised adjusted series. ``INTERVAL`` / ``DERIVED_ARTIFACT``, not a fact.

    **It is a cache, and it must behave like one.** Recomputing from the key must
    reproduce ``artifact_content_hash`` bit-identically; a mismatch is BLOCKING,
    not a cache miss. No adjusted series exists anywhere in the system that is
    not keyed this way.

    ``as_of_epoch`` is part of the key because "the adjusted close on a date" is
    not a number -- it is a number *per information set*. Storing one of them
    without its key is how a research programme ends up with two truths and no
    way to tell which it used.
    """

    dataset: str = "adjusted_bar_artifact"
    artifact_id: str
    adjustment_policy: AdjustmentPolicy
    #: How the factor is applied, not merely which actions it covers. Part of the
    #: key, because two conventions over the same actions are two different series.
    adjustment_convention: AdjustmentConvention
    resolved_profile: InformationSetProfile
    as_of_epoch: datetime
    corporate_action_dataset_version: str
    raw_bar_dataset_version: str
    security_id_scope: str
    series: tuple[PriceBarValues, ...]

    def __post_init__(self) -> None:
        _normalize_instants(self, "as_of_epoch")


# ---------------------------------------------------------------------------
# 4 -- universe membership
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class UniverseMembership(DerivedArtifact):
    """The survivorship control. ``SESSION_SCOPED`` / ``DERIVED_ARTIFACT``.

    Stored per session, **never recomputed at query time** and never derived by
    filtering today's listed securities. A security delisted before a date is
    absent from that date's snapshot; one delisted after it is present.

    The stored evaluation inputs are not redundant. They make a membership
    decision auditable years later, and let a quality check confirm the rule was
    applied to data admissible at that session rather than to current data.
    """

    dataset: str = "universe_membership"
    session_date: date
    security_id: str
    universe_definition_version: str
    resolved_profile: InformationSetProfile
    is_member: bool
    price_at_eval: Decimal | None = None
    market_cap_at_eval: Decimal | None = None
    addv_at_eval: Decimal | None = None
    history_sessions_at_eval: int = 0
    exclusion_reason: UniverseExclusionReason | None = None
    is_common_stock_eligible: bool = False

    @property
    def primary_key(self) -> tuple[date, str, str, str]:
        """``(session_date, security_id, universe_definition_version, resolved_profile)``."""
        return (
            self.session_date,
            self.security_id,
            self.universe_definition_version,
            self.resolved_profile.value,
        )


# ---------------------------------------------------------------------------
# 16 / 17 / 18 -- operational metadata (no availability envelope)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class IngestionRun:
    """The act that fetched something. Immutable once written.

    ``is_backfill`` is what distinguishes a vendor backfill from an update, and
    the distinction is what the profile model exists to act on.
    """

    ingestion_run_id: str
    provider: str
    dataset: str
    started_at: datetime
    completed_at: datetime
    status: IngestionStatus
    requested_range: str
    record_count: int
    new_record_count: int
    is_backfill: bool
    bronze_artifact_hashes: tuple[str, ...]
    code_commit_sha: str
    config_version: str

    def __post_init__(self) -> None:
        _normalize_instants(self, "started_at", "completed_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class DataQualityIssue:
    """A quality finding as **data**, not a log line.

    It has to be queryable, because the code that refuses to serve a result
    queries it (contract 10, rule 8).

    Suppression is a human act with a name on it: ``SUPPRESSED`` without both
    ``suppressed_by`` and ``suppression_reason`` is itself a defect.
    """

    issue_id: str
    check_name: str
    severity: QualitySeverity
    dataset: str
    detected_at: datetime
    detail: str
    status: IssueStatus = IssueStatus.OPEN
    security_id: str | None = None
    session_date: date | None = None
    ingestion_run_id: str | None = None
    suppression_reason: str | None = None
    suppressed_by: str | None = None

    def __post_init__(self) -> None:
        _normalize_instants(self, "detected_at")

    @property
    def is_blocking_open(self) -> bool:
        """Whether this issue currently refuses every dependent result."""
        return self.severity is QualitySeverity.BLOCKING and self.status is IssueStatus.OPEN


@dataclass(frozen=True, slots=True, kw_only=True)
class DatasetVersion:
    """The unit of reproducibility. Versions are superseded, **never mutated**.

    ``resolved_profile`` is named for what it is: an artifact is built under the
    profile the run actually resolved to, so a downgraded run produces
    ``PUBLIC_PIT`` artifacts.
    """

    dataset_version: str
    layer: StorageLayer
    built_at: datetime
    built_from_run_ids: tuple[str, ...]
    code_commit_sha: str
    content_hash: str
    lag_policy_version: str
    resolved_profile: InformationSetProfile | None = None
    #: Which policy resolved this build's provider-timing gaps. Part of what the
    #: build *is*, so a reader can refuse a dataset resolved under another policy.
    resolution_policy_version: str | None = None
    universe_definition_version: str | None = None
    corporate_action_dataset_version: str | None = None
    adjustment_policy: AdjustmentPolicy | None = None
    is_published: bool = True
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        _normalize_instants(self, "built_at")


# ---------------------------------------------------------------------------
# Declared temporal semantics, as data
# ---------------------------------------------------------------------------

#: The class each Phase-3A **source** entity declares. Per row where the entity
#: genuinely carries more than one kind of fact, in which case the value is
#: ``None`` here and the row's own anchor decides.
SOURCE_ENTITY_TEMPORAL_CLASS: dict[str, TemporalFactClass | None] = {
    "security_attribute": TemporalFactClass.SAMPLED_STATE,
    "listing": None,  # per row, selected by listing_fact_kind
    "ticker_history": TemporalFactClass.RETROSPECTIVE,
    "market_session": TemporalFactClass.ANNOUNCED_FORWARD,
    "price_bar": TemporalFactClass.RETROSPECTIVE,
    "corporate_action": TemporalFactClass.ANNOUNCED_FORWARD,
}

#: The validity each Phase-3A **derived** entity declares.
DERIVED_ENTITY_OUTPUT_VALIDITY: dict[str, str] = {
    "security": "EVENT_REFERENCED",
    "aggregated_price_bar_artifact": "INTERVAL",
    "adjusted_bar_artifact": "INTERVAL",
    "universe_membership": "SESSION_SCOPED",
}


__all__ = [
    "DERIVED_ENTITY_OUTPUT_VALIDITY",
    "SOURCE_ENTITY_TEMPORAL_CLASS",
    "AdjustedBarArtifact",
    "AggregatedPriceBarArtifact",
    "CorporateAction",
    "DataQualityIssue",
    "DatasetVersion",
    "DerivedArtifact",
    "IngestionRun",
    "Listing",
    "MarketSession",
    "PriceBar",
    "PriceBarValues",
    "Security",
    "SecurityAttribute",
    "SourceFact",
    "TickerHistory",
    "UniverseMembership",
]
