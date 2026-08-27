"""The Phase-3A synthetic reference dataset.

**Entirely fictitious.** Four invented securities, an invented exchange calendar,
invented prices. Nothing here is derived from, copied from or modelled on any
vendor's data, and no result computed from it is evidence about a real security,
a real market or any provider's fitness. It exists to prove that the contract can
be *mechanised*, which is a different claim from proving that anyone's data
satisfies it.

Small, legible and **adversarial**. Every entry earns its place by making some
guarantee falsifiable:

=====================================  ====================================================
what                                   which guarantee it makes falsifiable
=====================================  ====================================================
``SEC-0001`` continuously listed        the base case, and the split-adjustment proof
``SEC-0002`` ticker ``KTHN`` -> ``KTHX``  identity survives a rename
``SEC-0003`` delisted 2019-06-28        survivorship: present before, absent after
``SEC-0004`` reuses ticker ``OBSQ``     a recycled ticker is legal; an overlap is not
half-day session 2019-07-03             an early close is calendar data, never assumed
two minute bars in one session          bar identity is the endpoint, not the session date
split announced 06-25, ex-date 06-27    knowing and applying are different operations
split announced after an earlier cutoff a query at 06-24 must not see it
exact / bounded, public / provider      all four timing shapes resolve correctly
one ``PROVIDER_DERIVED`` bar            ineligible under ``PUBLIC_PIT``, and counted
one ``SYSTEM_OBSERVED`` attribute       eligible only under ``FORWARD_SYSTEM``
listing revisions 0 and 1               a delisting is a later revision, not a correction
=====================================  ====================================================

Every instant is fixed. There is no clock anywhere in this module, because a
fixture that reads one cannot prove determinism.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from kalpamani.data.contracts.dataset import GoldDataset
from kalpamani.data.contracts.entities import (
    CorporateAction,
    Listing,
    MarketSession,
    PriceBar,
    Security,
    SecurityAttribute,
    SourceFact,
    TickerHistory,
    UniverseMembership,
)
from kalpamani.data.contracts.envelope import (
    DerivedEnvelope,
    FactAnchor,
    LineageRef,
    OutputValidityDeclaration,
    SourceEnvelope,
)
from kalpamani.data.contracts.profiles import (
    DatasetGapResolution,
    ProfileResolutionConfig,
)
from kalpamani.data.contracts.resolution import ApprovedBoundPolicy, BoundApprovals
from kalpamani.data.contracts.vocabulary import (
    AnnouncementBoundDerivation,
    BarConstruction,
    BarResolution,
    CorporateActionType,
    DatasetGapPolicy,
    DelistingReason,
    Exchange,
    GlobalProfileResolution,
    InformationOrigin,
    InformationSetProfile,
    ListingFactKind,
    ProviderBoundDerivation,
    ProviderTimeDerivation,
    PublicBoundDerivation,
    PublicTimeDerivation,
    TickerChangeReason,
)
from kalpamani.data.curate.build import build_gold_dataset
from kalpamani.data.curate.publication import (
    GOLD_ENTITIES,
    VerifiedPublication,
    publish_gold_dataset,
    read_published_dataset,
)
from kalpamani.data.curate.resolution_run import ResolvedRunInputs, resolve_run_inputs
from kalpamani.data.curate.universe import UniverseBuildInputs, UniverseDefinition
from kalpamani.data.pit.accessors import PointInTimeReader
from kalpamani.data.quality.checks import (
    DEFAULT_MARKET_THRESHOLDS,
    DEFAULT_SURVIVORSHIP_POLICY,
    QualityFinding,
)
from kalpamani.data.quality.plan import PHASE3A_QUALITY_PLAN, CheckRequirement
from kalpamani.data.quality.report import CheckNotRun, QualityReport, report_from_findings
from kalpamani.data.storage import LocalTableStore

# ---------------------------------------------------------------------------
# Identities and constants
# ---------------------------------------------------------------------------

PROVIDER = "synthetic-a1"
DATASET_VERSION = "gold/synthetic.a1.1"
LISTING_DATASET_VERSION = "gold/synthetic.a1.1"
ATTRIBUTE_DATASET_VERSION = "gold/synthetic.a1.1"
BAR_DATASET_VERSION = "gold/synthetic.a1.1"
ACTION_DATASET_VERSION = "gold/synthetic.a1.1"

SEC_CONTINUOUS = "SEC-0001"
SEC_RENAMED = "SEC-0002"
SEC_DELISTED = "SEC-0003"
SEC_TICKER_REUSER = "SEC-0004"

LAG_POLICY_VERSION = "lag/synthetic.a1"
RESOLUTION_POLICY_VERSION = "profres/synthetic.a1"
UNIVERSE_DEFINITION_VERSION = "universe/synthetic.a1"

#: Fixed, never read from a clock.
INGESTION_TIME = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
FIRST_SEEN = datetime(2026, 8, 20, 6, 0, tzinfo=UTC)
ARTIFACT_FIRST_BUILT = datetime(2026, 8, 26, 12, 30, tzinfo=UTC)
BUILD_TIME = datetime(2026, 8, 26, 13, 0, tzinfo=UTC)

#: The declared lag that bounds an officially disseminated daily bar.
SESSION_CLOSE_LAG = timedelta(minutes=30)
#: How long after the close the provider drops its file. An exact time.
PROVIDER_FILE_DROP_LAG = timedelta(minutes=45)

COVERAGE_START = date(2019, 6, 24)
COVERAGE_END = date(2021, 1, 5)


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """A fixed UTC instant. Every timestamp in this fixture goes through here."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

#: (session_date, regular_open, regular_close, is_half_day). Summer sessions are
#: 13:30-20:00 UTC and winter ones 14:30-21:00 UTC, because the venue keeps local
#: hours and the offset moves. Nothing here assumes a fixed offset.
_SESSION_SPECS: tuple[tuple[date, tuple[int, int], tuple[int, int], bool], ...] = (
    (date(2019, 6, 24), (13, 30), (20, 0), False),
    (date(2019, 6, 25), (13, 30), (20, 0), False),
    (date(2019, 6, 26), (13, 30), (20, 0), False),
    (date(2019, 6, 27), (13, 30), (20, 0), False),
    (date(2019, 6, 28), (13, 30), (20, 0), False),
    (date(2019, 7, 3), (13, 30), (17, 0), True),
    (date(2021, 1, 4), (14, 30), (21, 0), False),
    (date(2021, 1, 5), (14, 30), (21, 0), False),
)


def _source_envelope(
    *,
    origin: InformationOrigin,
    anchor: FactAnchor,
    public_exact: datetime | None = None,
    public_bound: datetime | None = None,
    public_time_derivation: PublicTimeDerivation = PublicTimeDerivation.UNKNOWN,
    public_bound_derivation: PublicBoundDerivation = PublicBoundDerivation.NONE,
    provider_exact: datetime | None = None,
    provider_bound: datetime | None = None,
    provider_time_derivation: ProviderTimeDerivation = ProviderTimeDerivation.UNKNOWN,
    provider_bound_derivation: ProviderBoundDerivation = ProviderBoundDerivation.NONE,
    first_seen: datetime = FIRST_SEEN,
    source_id: str,
    revision_sequence: int = 0,
) -> SourceEnvelope:
    return SourceEnvelope(
        information_origin=origin,
        public_available_time=public_exact,
        public_available_upper_bound=public_bound,
        public_time_derivation=public_time_derivation,
        public_bound_derivation=public_bound_derivation,
        provider_available_time=provider_exact,
        provider_available_upper_bound=provider_bound,
        provider_time_derivation=provider_time_derivation,
        provider_bound_derivation=provider_bound_derivation,
        system_first_seen_time=first_seen,
        anchor=anchor,
        revision_sequence=revision_sequence,
        source_id=source_id,
        ingestion_time=INGESTION_TIME,
        dataset_version=DATASET_VERSION,
        provider=PROVIDER,
    )


#: Both venues in the fixture keep the same hours. They are separate calendar
#: rows because coverage is checked per exchange: a NASDAQ security is not
#: required to have bars on an NYSE-only session, and one shared calendar would
#: either fault it for absences that are not absences or -- worse -- leave it with
#: no required sessions at all and silently check nothing.
_CALENDAR_EXCHANGES = (Exchange.NYSE, Exchange.NASDAQ)


def sessions() -> tuple[MarketSession, ...]:
    """The exchange calendar, per venue. Announced forward, with an exact time."""
    out: list[MarketSession] = []
    for session_date, (open_h, open_m), (close_h, close_m), half in _SESSION_SPECS:
        regular_open = utc(session_date.year, session_date.month, session_date.day, open_h, open_m)
        regular_close = utc(
            session_date.year, session_date.month, session_date.day, close_h, close_m
        )
        announced = utc(session_date.year - 1, 9, 15, 12, 0)
        for exchange in _CALENDAR_EXCHANGES:
            out.append(
                MarketSession(
                    exchange=exchange,
                    session_date=session_date,
                    regular_open=regular_open,
                    regular_close=regular_close,
                    extended_open=regular_open - timedelta(hours=5, minutes=30),
                    extended_close=regular_close + timedelta(hours=4),
                    is_half_day=half,
                    is_holiday=False,
                    envelope=_source_envelope(
                        origin=InformationOrigin.AUTHORITATIVE_PUBLIC,
                        anchor=FactAnchor.announced_forward(announcement_time=announced),
                        public_exact=announced,
                        public_time_derivation=PublicTimeDerivation.AUTHORITATIVE_TIMESTAMP,
                        # No feed-publication instant: the calendar dataset's
                        # declared policy is BOUND, and the bound is applied by
                        # the resolution step rather than written here.
                        provider_time_derivation=ProviderTimeDerivation.UNKNOWN,
                        source_id=f"calendar:{exchange.value}:{session_date.isoformat()}",
                    ),
                )
            )
    return tuple(out)


def session_close(session_date: date, exchange: Exchange = Exchange.NYSE) -> datetime:
    """The regular close of one fixture session. Both venues keep the same hours."""
    for session in sessions():
        if session.session_date == session_date and session.exchange is exchange:
            return session.regular_close
    raise KeyError(session_date)


def session_open(session_date: date, exchange: Exchange = Exchange.NYSE) -> datetime:
    """The regular open of one fixture session -- also its universe evaluation cutoff."""
    for session in sessions():
        if session.session_date == session_date and session.exchange is exchange:
            return session.regular_open
    raise KeyError(session_date)


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------


def _listing_state(
    *,
    listing_id: str,
    security_id: str,
    exchange: Exchange,
    listing_start: date,
    listing_end: date | None,
    delisting_reason: DelistingReason | None,
    observed: datetime,
    revision_sequence: int,
) -> Listing:
    return Listing(
        listing_id=listing_id,
        security_id=security_id,
        exchange=exchange,
        listing_start=listing_start,
        listing_end=listing_end,
        delisting_reason=delisting_reason,
        listing_fact_kind=ListingFactKind.STATE,
        envelope=_source_envelope(
            origin=InformationOrigin.AUTHORITATIVE_PUBLIC,
            anchor=FactAnchor.retrospective(observed),
            public_exact=observed,
            public_time_derivation=PublicTimeDerivation.AUTHORITATIVE_TIMESTAMP,
            provider_exact=observed + timedelta(hours=1),
            provider_time_derivation=ProviderTimeDerivation.VENDOR_STAMPED,
            source_id=f"{listing_id}:r{revision_sequence}",
            revision_sequence=revision_sequence,
        ),
    )


def listings() -> tuple[Listing, ...]:
    """Listing states, with a delisting modelled as a **later revision**.

    Revision 0 says the security is listed and is available from the listing date.
    Revision 1 says the listing ended, and is available only from the day it did.
    A single row carrying the end date from the beginning would let a 2019 query
    know about a 2023 delisting.
    """
    return (
        _listing_state(
            listing_id="LST-0001",
            security_id=SEC_CONTINUOUS,
            exchange=Exchange.NYSE,
            listing_start=date(2015, 1, 2),
            listing_end=None,
            delisting_reason=None,
            observed=utc(2015, 1, 2, 13, 0),
            revision_sequence=0,
        ),
        _listing_state(
            listing_id="LST-0002",
            security_id=SEC_RENAMED,
            exchange=Exchange.NASDAQ,
            listing_start=date(2016, 3, 1),
            listing_end=None,
            delisting_reason=None,
            observed=utc(2016, 3, 1, 13, 0),
            revision_sequence=0,
        ),
        _listing_state(
            listing_id="LST-0002",
            security_id=SEC_RENAMED,
            exchange=Exchange.NASDAQ,
            listing_start=date(2016, 3, 1),
            listing_end=date(2023, 5, 10),
            delisting_reason=DelistingReason.MERGER,
            observed=utc(2023, 5, 10, 20, 0),
            revision_sequence=1,
        ),
        _listing_state(
            listing_id="LST-0003",
            security_id=SEC_DELISTED,
            exchange=Exchange.NYSE,
            listing_start=date(2014, 5, 5),
            listing_end=None,
            delisting_reason=None,
            observed=utc(2014, 5, 5, 13, 0),
            revision_sequence=0,
        ),
        _listing_state(
            listing_id="LST-0003",
            security_id=SEC_DELISTED,
            exchange=Exchange.NYSE,
            listing_start=date(2014, 5, 5),
            listing_end=date(2019, 6, 28),
            delisting_reason=DelistingReason.MERGER,
            observed=utc(2019, 6, 28, 20, 0),
            revision_sequence=1,
        ),
        _listing_state(
            listing_id="LST-0004",
            security_id=SEC_TICKER_REUSER,
            exchange=Exchange.NASDAQ,
            listing_start=date(2021, 1, 4),
            listing_end=None,
            delisting_reason=None,
            observed=utc(2021, 1, 4, 13, 0),
            revision_sequence=0,
        ),
        # An ANNOUNCED_FORWARD row on the same entity: the venue said on 21 June
        # that the listing would end on 28 June. Different fact, different anchor,
        # different primary key part.
        Listing(
            listing_id="LST-0003",
            security_id=SEC_DELISTED,
            exchange=Exchange.NYSE,
            listing_start=date(2014, 5, 5),
            listing_end=date(2019, 6, 28),
            delisting_reason=DelistingReason.MERGER,
            listing_fact_kind=ListingFactKind.CHANGE_ANNOUNCEMENT,
            envelope=_source_envelope(
                origin=InformationOrigin.AUTHORITATIVE_PUBLIC,
                anchor=FactAnchor.announced_forward(announcement_time=utc(2019, 6, 21, 21, 0)),
                public_exact=utc(2019, 6, 21, 21, 0),
                public_time_derivation=PublicTimeDerivation.AUTHORITATIVE_TIMESTAMP,
                provider_exact=utc(2019, 6, 21, 22, 0),
                provider_time_derivation=ProviderTimeDerivation.VENDOR_STAMPED,
                source_id="LST-0003:announcement",
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------


def attributes() -> tuple[SecurityAttribute, ...]:
    """Security types, plus one deliberately ``SYSTEM_OBSERVED`` row.

    The system-observed row carries a **different attribute** on purpose. It is
    eligible only under ``FORWARD_SYSTEM``, so putting it on ``security_type``
    would silently empty the universe's type input under the other two profiles --
    which is a real failure mode, but not the one this fixture is for.
    """
    rows: list[SecurityAttribute] = []
    starts = {
        SEC_CONTINUOUS: date(2015, 1, 2),
        SEC_RENAMED: date(2016, 3, 1),
        SEC_DELISTED: date(2014, 5, 5),
        SEC_TICKER_REUSER: date(2021, 1, 4),
    }
    for security_id, valid_from in starts.items():
        sampled = utc(valid_from.year, valid_from.month, valid_from.day, 14, 0)
        rows.append(
            SecurityAttribute(
                security_id=security_id,
                attribute="security_type",
                valid_from=valid_from,
                value="COMMON_STOCK",
                envelope=_source_envelope(
                    origin=InformationOrigin.AUTHORITATIVE_PUBLIC,
                    anchor=FactAnchor.sampled_state(sampled),
                    public_exact=sampled,
                    public_time_derivation=PublicTimeDerivation.AUTHORITATIVE_TIMESTAMP,
                    provider_exact=sampled + timedelta(hours=1),
                    provider_time_derivation=ProviderTimeDerivation.VENDOR_STAMPED,
                    source_id=f"attr:{security_id}:security_type",
                ),
            )
        )
    rows.append(
        SecurityAttribute(
            security_id=SEC_CONTINUOUS,
            attribute="market_status_observed",
            valid_from=date(2019, 6, 24),
            value="ACTIVE",
            envelope=_source_envelope(
                origin=InformationOrigin.SYSTEM_OBSERVED,
                anchor=FactAnchor.sampled_state(utc(2019, 6, 24, 15, 0)),
                public_time_derivation=PublicTimeDerivation.NOT_APPLICABLE,
                provider_time_derivation=ProviderTimeDerivation.NOT_APPLICABLE,
                first_seen=utc(2019, 6, 24, 15, 0),
                source_id="poll:SEC-0001:market_status",
            ),
        )
    )
    return tuple(rows)


def securities() -> tuple[Security, ...]:
    """Canonical identity as a derived artifact over the listing evidence."""
    by_security = {
        SEC_CONTINUOUS: "LST-0001",
        SEC_RENAMED: "LST-0002",
        SEC_DELISTED: "LST-0003",
        SEC_TICKER_REUSER: "LST-0004",
    }
    out: list[Security] = []
    for security_id, listing_id in by_security.items():
        evidence = tuple(
            row
            for row in listings()
            if row.listing_id == listing_id
            and row.listing_fact_kind is ListingFactKind.STATE
            and row.envelope.revision_sequence == 0
        )
        out.append(
            Security(
                security_id=security_id,
                inputs=evidence,
                envelope=DerivedEnvelope(
                    lineage=(
                        LineageRef.of(
                            entity="listing",
                            dataset_version=LISTING_DATASET_VERSION,
                            selector={"listing_id": listing_id, "revision_sequence": "0"},
                        ),
                    ),
                    artifact_first_built_time=ARTIFACT_FIRST_BUILT,
                    derivation_spec_version="identity/a1.1",
                    artifact_content_hash=f"sha256:identity-{security_id}",
                    validity=OutputValidityDeclaration.event_referenced((listing_id,)),
                    ingestion_time=INGESTION_TIME,
                    dataset_version=DATASET_VERSION,
                ),
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# Ticker history
# ---------------------------------------------------------------------------


def _ticker(
    *,
    ticker: str,
    security_id: str,
    valid_from: date,
    valid_to: date | None,
    reason: TickerChangeReason | None,
) -> TickerHistory:
    observed = utc(valid_from.year, valid_from.month, valid_from.day, 13, 0)
    return TickerHistory(
        security_id=security_id,
        ticker=ticker,
        valid_from=valid_from,
        valid_to=valid_to,
        change_reason=reason,
        envelope=_source_envelope(
            origin=InformationOrigin.AUTHORITATIVE_PUBLIC,
            anchor=FactAnchor.retrospective(observed),
            public_exact=observed,
            public_time_derivation=PublicTimeDerivation.AUTHORITATIVE_TIMESTAMP,
            source_id=f"ticker:{ticker}:{valid_from.isoformat()}",
        ),
    )


def ticker_history() -> tuple[TickerHistory, ...]:
    """A rename, and a ticker legitimately recycled by a different security later.

    The recycled ``OBSQ`` must **pass**: tickers are reused, and a check that
    blocked it would be blocking correct data. Only an *overlap* is a defect --
    see :func:`overlapping_ticker_history`.
    """
    return (
        _ticker(
            ticker="VRDL",
            security_id=SEC_CONTINUOUS,
            valid_from=date(2015, 1, 2),
            valid_to=None,
            reason=None,
        ),
        _ticker(
            ticker="KTHN",
            security_id=SEC_RENAMED,
            valid_from=date(2016, 3, 1),
            valid_to=date(2020, 11, 30),
            reason=None,
        ),
        _ticker(
            ticker="KTHX",
            security_id=SEC_RENAMED,
            valid_from=date(2020, 12, 1),
            valid_to=None,
            reason=TickerChangeReason.RENAME,
        ),
        _ticker(
            ticker="OBSQ",
            security_id=SEC_DELISTED,
            valid_from=date(2014, 5, 5),
            valid_to=date(2019, 6, 28),
            reason=None,
        ),
        _ticker(
            ticker="OBSQ",
            security_id=SEC_TICKER_REUSER,
            valid_from=date(2021, 1, 4),
            valid_to=None,
            reason=None,
        ),
    )


def overlapping_ticker_history() -> tuple[TickerHistory, ...]:
    """Adversarial: ``OBSQ`` mapped to two securities on overlapping dates."""
    return (
        *ticker_history(),
        _ticker(
            ticker="OBSQ",
            security_id=SEC_TICKER_REUSER,
            valid_from=date(2019, 1, 1),
            valid_to=None,
            reason=None,
        ),
    )


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------

#: (security, session, close). Open/high/low are derived from the close so the
#: numbers stay legible and the OHLC invariant holds by construction.
_DAILY_CLOSES: tuple[tuple[str, date, str], ...] = (
    (SEC_CONTINUOUS, date(2019, 6, 24), "100.00"),
    (SEC_CONTINUOUS, date(2019, 6, 25), "101.00"),
    (SEC_CONTINUOUS, date(2019, 6, 26), "102.00"),
    # 2-for-1 split, ex-date 2019-06-27: the traded price halves. The adjusted
    # series must re-express it in base terms and be continuous again.
    (SEC_CONTINUOUS, date(2019, 6, 27), "51.00"),
    (SEC_CONTINUOUS, date(2019, 6, 28), "52.00"),
    (SEC_CONTINUOUS, date(2021, 1, 4), "60.00"),
    (SEC_CONTINUOUS, date(2021, 1, 5), "61.00"),
    (SEC_RENAMED, date(2019, 6, 24), "40.00"),
    (SEC_RENAMED, date(2019, 6, 25), "41.00"),
    (SEC_RENAMED, date(2019, 6, 26), "42.00"),
    (SEC_RENAMED, date(2019, 6, 27), "43.00"),
    (SEC_RENAMED, date(2019, 6, 28), "44.00"),
    (SEC_RENAMED, date(2021, 1, 4), "30.00"),
    # 3-for-1 split, ex-date 2021-01-05.
    (SEC_RENAMED, date(2021, 1, 5), "10.10"),
    (SEC_DELISTED, date(2019, 6, 24), "15.00"),
    (SEC_DELISTED, date(2019, 6, 25), "15.50"),
    (SEC_DELISTED, date(2019, 6, 26), "16.00"),
    (SEC_DELISTED, date(2019, 6, 27), "16.20"),
    (SEC_DELISTED, date(2019, 6, 28), "16.40"),
    (SEC_TICKER_REUSER, date(2021, 1, 4), "25.00"),
    (SEC_TICKER_REUSER, date(2021, 1, 5), "25.50"),
)

_DAILY_VOLUME = 1_000_000


def _bar_envelope(
    *,
    construction: BarConstruction,
    bar_end_time: datetime,
    session_close_time: datetime,
    source_id: str,
) -> SourceEnvelope:
    if construction is BarConstruction.OFFICIAL_DISSEMINATED:
        return _source_envelope(
            origin=InformationOrigin.AUTHORITATIVE_PUBLIC,
            anchor=FactAnchor.retrospective(bar_end_time),
            public_bound=session_close_time + SESSION_CLOSE_LAG,
            public_time_derivation=PublicTimeDerivation.UNKNOWN,
            public_bound_derivation=PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG,
            provider_exact=session_close_time + PROVIDER_FILE_DROP_LAG,
            provider_time_derivation=ProviderTimeDerivation.FILE_DROP,
            source_id=source_id,
        )
    return _source_envelope(
        origin=InformationOrigin.PROVIDER_DERIVED,
        anchor=FactAnchor.retrospective(bar_end_time),
        public_time_derivation=PublicTimeDerivation.NOT_APPLICABLE,
        provider_exact=session_close_time + PROVIDER_FILE_DROP_LAG,
        provider_time_derivation=ProviderTimeDerivation.FILE_DROP,
        source_id=source_id,
    )


def daily_bars() -> tuple[PriceBar, ...]:
    """Officially disseminated daily bars: bounded public timing, exact provider timing."""
    out: list[PriceBar] = []
    for security_id, session_date, close_text in _DAILY_CLOSES:
        close = Decimal(close_text)
        end = session_close(session_date)
        # The ticker-reuser's bars are provider-aggregated, and its listed range
        # is fully covered. That combination is the one case where a series can
        # be complete and still entirely ineligible under PUBLIC_PIT -- which is
        # a refusal, not a short series.
        construction = (
            BarConstruction.PROVIDER_AGGREGATED
            if security_id == SEC_TICKER_REUSER
            else BarConstruction.OFFICIAL_DISSEMINATED
        )
        out.append(
            PriceBar(
                security_id=security_id,
                resolution=BarResolution.DAILY,
                bar_end_time=end,
                bar_start_time=session_open(session_date),
                session_date=session_date,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=_DAILY_VOLUME,
                curation_source="synthetic:daily",
                bar_construction=construction,
                envelope=_bar_envelope(
                    construction=construction,
                    bar_end_time=end,
                    session_close_time=end,
                    source_id=f"bar:{security_id}:D:{session_date.isoformat()}",
                ),
            )
        )
    return tuple(out)


def minute_bars() -> tuple[PriceBar, ...]:
    """Two distinct minute bars inside one session.

    Under the old ``(security_id, session_date, resolution)`` key these collided
    on one row. Identity is the bar's own endpoint, so they do not.

    They are ``PROVIDER_AGGREGATED`` -- the provider built them from trades it
    collected -- which makes them ``PROVIDER_DERIVED`` and therefore **ineligible
    under PUBLIC_PIT**. That is not a defect in the fixture; it is the exact
    consequence provider test P9 exists to establish.
    """
    session_date = date(2019, 6, 26)
    out: list[PriceBar] = []
    for offset, close_text in ((0, "41.90"), (1, "41.95")):
        start = utc(2019, 6, 26, 15, 30 + offset)
        end = start + timedelta(minutes=1)
        close = Decimal(close_text)
        out.append(
            PriceBar(
                security_id=SEC_RENAMED,
                resolution=BarResolution.MINUTE,
                bar_end_time=end,
                bar_start_time=start,
                session_date=session_date,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1_500,
                curation_source="synthetic:minute",
                bar_construction=BarConstruction.PROVIDER_AGGREGATED,
                envelope=_bar_envelope(
                    construction=BarConstruction.PROVIDER_AGGREGATED,
                    bar_end_time=end,
                    session_close_time=session_close(session_date),
                    source_id=f"bar:{SEC_RENAMED}:M:{end.isoformat()}",
                ),
            )
        )
    return tuple(out)


def bars() -> tuple[PriceBar, ...]:
    """Every raw bar in the fixture."""
    return (*daily_bars(), *minute_bars())


# ---------------------------------------------------------------------------
# Corporate actions
# ---------------------------------------------------------------------------


def corporate_actions() -> tuple[CorporateAction, ...]:
    """One exactly-timed announcement, one date-only announcement with an approved bound.

    Both are announced **before** their ex-date, which is the whole
    ``ANNOUNCED_FORWARD`` class: an effective date later than availability is
    correct, not a violation. And the first is announced *after* an earlier
    ``as_of`` of 2019-06-24, so a query at that cutoff must not see it.
    """
    return (
        CorporateAction(
            action_id="CA-0001",
            security_id=SEC_CONTINUOUS,
            action_type=CorporateActionType.SPLIT,
            announcement_date=date(2019, 6, 25),
            ex_date=date(2019, 6, 27),
            ratio=Decimal(2),
            envelope=_source_envelope(
                origin=InformationOrigin.AUTHORITATIVE_PUBLIC,
                anchor=FactAnchor.announced_forward(announcement_time=utc(2019, 6, 25, 20, 15)),
                public_exact=utc(2019, 6, 25, 20, 15),
                public_time_derivation=PublicTimeDerivation.AUTHORITATIVE_TIMESTAMP,
                provider_exact=utc(2019, 6, 25, 22, 0),
                provider_time_derivation=ProviderTimeDerivation.VENDOR_STAMPED,
                source_id="CA-0001",
            ),
        ),
        CorporateAction(
            action_id="CA-0002",
            security_id=SEC_RENAMED,
            action_type=CorporateActionType.SPLIT,
            announcement_date=date(2021, 1, 4),
            ex_date=date(2021, 1, 5),
            ratio=Decimal(3),
            envelope=_source_envelope(
                origin=InformationOrigin.AUTHORITATIVE_PUBLIC,
                # Date only: no exact instant exists for us, so both the
                # availability axis and the class anchor resolve from an approved
                # bound rather than being waved through as null.
                anchor=FactAnchor.announced_forward(
                    announcement_time_upper_bound=utc(2021, 1, 5, 1, 0),
                    announcement_bound_derivation=AnnouncementBoundDerivation.DATE_PLUS_LAG,
                ),
                public_bound=utc(2021, 1, 5, 1, 0),
                public_time_derivation=PublicTimeDerivation.UNKNOWN,
                public_bound_derivation=PublicBoundDerivation.DATE_PLUS_LAG,
                provider_exact=utc(2021, 1, 5, 2, 0),
                provider_time_derivation=ProviderTimeDerivation.VENDOR_STAMPED,
                source_id="CA-0002",
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Run configuration
# ---------------------------------------------------------------------------


def approvals() -> BoundApprovals:
    """Which bound derivations this run approves, per dataset.

    Nothing is approved by default. A dataset absent from this mapping has no
    approved bound at all, and a bound it carries cannot resolve its axis.
    """
    return BoundApprovals(
        by_dataset={
            "price_bar": ApprovedBoundPolicy(
                public=frozenset({PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG}),
            ),
            "corporate_action": ApprovedBoundPolicy(
                public=frozenset({PublicBoundDerivation.DATE_PLUS_LAG}),
                announcement=frozenset({AnnouncementBoundDerivation.DATE_PLUS_LAG}),
            ),
            "market_session": ApprovedBoundPolicy(
                provider=frozenset({ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND}),
            ),
        }
    )


#: Every dataset a run reads directly, so the resolution map is a complete
#: inventory rather than a list of the problematic ones.
DIRECTLY_READ_DATASETS = (
    "corporate_action",
    "listing",
    "market_session",
    "price_bar",
    "security_attribute",
    "ticker_history",
)

#: What the quality report covers: every source dataset plus every table the
#: build publishes. The plan compares this against the publication, so a table
#: nothing checked cannot be published as though something had.
QUALITY_COVERAGE = tuple(sorted(set(DIRECTLY_READ_DATASETS) | set(GOLD_ENTITIES)))


def resolution(
    *,
    requested: InformationSetProfile = InformationSetProfile.PUBLIC_PIT,
    downgrade: GlobalProfileResolution = GlobalProfileResolution.NONE,
) -> ProfileResolutionConfig:
    """The run's profile resolution: ``BOUND`` for one dataset, ``EXCLUDE`` for another.

    That combination is the ordinary case, and it is exactly what a single scalar
    resolution could not express.
    """
    return ProfileResolutionConfig(
        requested_profile=requested,
        global_profile_resolution=downgrade,
        resolution_policy_version=RESOLUTION_POLICY_VERSION,
        dataset_resolutions=(
            DatasetGapResolution(
                dataset="corporate_action",
                policy=DatasetGapPolicy.NONE,
                reason="the provider stamps action rows, so provider timing is exact",
            ),
            DatasetGapResolution(
                dataset="listing",
                policy=DatasetGapPolicy.NONE,
                reason="the venue notice feed is vendor-stamped, so provider timing is exact",
            ),
            DatasetGapResolution(
                dataset="market_session",
                policy=DatasetGapPolicy.BOUND,
                reason=(
                    "the calendar feed carries no feed-publication instant; bounded from "
                    "system_first_seen_time, which can only delay a row, never advance it"
                ),
            ),
            DatasetGapResolution(
                dataset="price_bar",
                policy=DatasetGapPolicy.NONE,
                reason="the provider publishes dated file drops, so provider timing is exact",
            ),
            DatasetGapResolution(
                dataset="security_attribute",
                policy=DatasetGapPolicy.NONE,
                reason="attribute rows are vendor-stamped",
            ),
            DatasetGapResolution(
                dataset="ticker_history",
                policy=DatasetGapPolicy.EXCLUDE,
                reason=(
                    "the ticker feed has no usable provider timing at all, and no bound can "
                    "be derived for it"
                ),
            ),
        ),
    )


def universe_definition() -> UniverseDefinition:
    """A versioned **synthetic** rule. Not Blueprint s.4, and not over real data."""
    return UniverseDefinition(
        version=UNIVERSE_DEFINITION_VERSION,
        min_close_price=Decimal(10),
        min_addv=Decimal(1_000_000),
        min_history_sessions=2,
        addv_window_sessions=3,
        eligible_exchanges=frozenset({Exchange.NYSE, Exchange.NASDAQ}),
        eligible_security_types=frozenset({"COMMON_STOCK"}),
    )


#: The sessions the fixture records universe snapshots for: one before the
#: delisting and one after, which is what makes survivorship falsifiable.
SNAPSHOT_SESSIONS = (date(2019, 6, 27), date(2021, 1, 5))


def evaluation_cutoffs() -> dict[date, datetime]:
    """Each snapshot session's own cutoff: a universe is known before trading starts."""
    return {session: session_open(session) for session in SNAPSHOT_SESSIONS}


def universe_inputs() -> UniverseBuildInputs:
    """Everything a universe build reads.

    No dataset-version arguments: each row already knows which source build it
    came from, and lineage reads that rather than being told.
    """
    return UniverseBuildInputs(
        listings=listings(),
        attributes=attributes(),
        bars=bars(),
    )


def universe_snapshots(
    *,
    resolved_profile: InformationSetProfile = InformationSetProfile.PUBLIC_PIT,
) -> dict[date, tuple[UniverseMembership, ...]]:
    """Build both stored snapshots under one resolved profile, via the build path.

    Deliberately routed through :func:`gold_dataset` rather than calling the
    builder directly, so a test can never exercise a universe the resolution step
    did not produce.
    """
    return dict(gold_dataset(requested=resolved_profile).universe)


def source_datasets() -> dict[str, tuple[SourceFact, ...]]:
    """Every directly consumed source dataset, keyed by name.

    This is what goes through resolution. Nothing downstream sees raw rows.
    """
    return {
        "corporate_action": corporate_actions(),
        "listing": listings(),
        "market_session": sessions(),
        "price_bar": bars(),
        "security_attribute": attributes(),
        "ticker_history": ticker_history(),
    }


def resolved_inputs(
    *,
    requested: InformationSetProfile = InformationSetProfile.PUBLIC_PIT,
    downgrade: GlobalProfileResolution = GlobalProfileResolution.NONE,
) -> ResolvedRunInputs:
    """Run the source rows through the resolution boundary, as a build must."""
    return resolve_run_inputs(
        source_datasets(),
        config=resolution(requested=requested, downgrade=downgrade),
        approvals=approvals(),
    )


def gold_dataset(
    *,
    requested: InformationSetProfile = InformationSetProfile.PUBLIC_PIT,
    downgrade: GlobalProfileResolution = GlobalProfileResolution.NONE,
) -> GoldDataset:
    """The complete curated build a point-in-time query is served from.

    Built through :func:`build_gold_dataset` from resolved rows, never assembled
    by hand: the receipt has to account for every row, and a dataset with no
    receipt is unpublishable.
    """
    resolved = resolved_inputs(requested=requested, downgrade=downgrade)
    return build_gold_dataset(
        resolved,
        dataset_version=DATASET_VERSION,
        build_time=BUILD_TIME,
        coverage_start=COVERAGE_START,
        coverage_end=COVERAGE_END,
        universe_definition=universe_definition(),
        universe_sessions=SNAPSHOT_SESSIONS,
        evaluation_cutoffs=evaluation_cutoffs(),
        approvals=approvals(),
        artifact_first_built_time=ARTIFACT_FIRST_BUILT,
        ingestion_time=INGESTION_TIME,
    )


def quality_report(
    *,
    findings: Sequence[QualityFinding] = (),
) -> QualityReport:
    """A passed quality report for the synthetic build.

    Synthetic tests construct one explicitly, but it goes through the same
    publication contract as any other: the gate is not bypassed, it is satisfied.
    """
    return report_from_findings(
        findings,
        plan_version=PHASE3A_QUALITY_PLAN.plan_version,
        policy_versions={
            "market": DEFAULT_MARKET_THRESHOLDS.version,
            "survivorship": DEFAULT_SURVIVORSHIP_POLICY.version,
            "lag": LAG_POLICY_VERSION,
        },
        checks_run=tuple(
            check.check_id
            for check in PHASE3A_QUALITY_PLAN.checks
            if check.requirement is CheckRequirement.REQUIRED
        ),
        checks_not_run=(
            CheckNotRun(
                check_name="7_cross_provider_reconciliation",
                reason="only one source is licensed in this slice, so the check cannot run",
            ),
        ),
        datasets_covered=QUALITY_COVERAGE,
        partitions_covered=tuple(session.isoformat() for session in SNAPSHOT_SESSIONS),
        produced_at=BUILD_TIME,
    )


def publish(
    store: LocalTableStore,
    *,
    requested: InformationSetProfile = InformationSetProfile.PUBLIC_PIT,
    downgrade: GlobalProfileResolution = GlobalProfileResolution.NONE,
    report: QualityReport | None = None,
) -> VerifiedPublication:
    """Build, publish and read back -- the whole sanctioned path in one call."""
    dataset = gold_dataset(requested=requested, downgrade=downgrade)
    gate = report if report is not None else quality_report()
    publish_gold_dataset(
        store,
        dataset,
        quality_report=gate,
        quality_plan=PHASE3A_QUALITY_PLAN,
        code_commit_sha=CODE_COMMIT_SHA,
        lag_policy_version=LAG_POLICY_VERSION,
        universe_definition_version=UNIVERSE_DEFINITION_VERSION,
        source_ingestion_run_ids=(INGESTION_RUN_ID,),
    )
    return read_published_dataset(
        store,
        dataset_version=DATASET_VERSION,
        config=resolution(requested=requested, downgrade=downgrade),
        approvals=approvals(),
    )


def build_verified_synthetic_publication(
    store: LocalTableStore,
    *,
    requested: InformationSetProfile = InformationSetProfile.PUBLIC_PIT,
    downgrade: GlobalProfileResolution = GlobalProfileResolution.NONE,
    report: QualityReport | None = None,
) -> VerifiedPublication:
    """The named synthetic factory for a verified publication.

    Every test that needs one goes through here, and here goes through the real
    publication and verified-read path. There is deliberately no shortcut that
    stamps a seal onto a hand-assembled triplet: a test able to fabricate one
    would be testing a route production does not have.
    """
    return publish(store, requested=requested, downgrade=downgrade, report=report)


def reader(
    store: LocalTableStore,
    *,
    requested: InformationSetProfile = InformationSetProfile.PUBLIC_PIT,
    downgrade: GlobalProfileResolution = GlobalProfileResolution.NONE,
    report: QualityReport | None = None,
) -> PointInTimeReader:
    """A reader over a verified publication. There is no unverified route."""
    publication = build_verified_synthetic_publication(
        store, requested=requested, downgrade=downgrade, report=report
    )
    return PointInTimeReader(
        publication,
        resolution=resolution(requested=requested, downgrade=downgrade),
        approvals=approvals(),
    )


# ---------------------------------------------------------------------------
# Bronze payload
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The dense minute path
# ---------------------------------------------------------------------------

#: The security whose minute grid is generated in full. NASDAQ-listed and
#: continuously listed across both sessions, so its own venue calendar decides
#: what "complete" means.
DENSE_MINUTE_SECURITY = SEC_RENAMED

#: One ordinary session and one half day, adjacent. The pair is the point: a
#: grid derived from the bars themselves would call both complete, and only a
#: grid derived from the calendar can tell that the half day is shorter on
#: purpose rather than short by omission.
DENSE_MINUTE_SESSIONS = (date(2019, 6, 28), date(2019, 7, 3))


def minute_endpoints_for(
    session_date: date, exchange: Exchange = Exchange.NASDAQ
) -> tuple[datetime, ...]:
    """Every minute endpoint the calendar implies for one session."""
    open_time = session_open(session_date, exchange)
    close_time = session_close(session_date, exchange)
    points: list[datetime] = []
    point = open_time + timedelta(minutes=1)
    while point <= close_time:
        points.append(point)
        point += timedelta(minutes=1)
    return tuple(points)


def dense_minute_bars(
    *,
    session_dates: Sequence[date] = DENSE_MINUTE_SESSIONS,
    omit: datetime | None = None,
) -> tuple[PriceBar, ...]:
    """A complete minute grid, generated from the calendar rather than listed.

    Written as a generator over the session's own endpoints because a hand-listed
    grid is a second, silent definition of what a complete session is -- and the
    one place it disagreed with the calendar would be the one case worth testing.

    ``omit`` drops exactly one endpoint, which is how the incomplete case is
    produced without changing anything else about the series.
    """
    out: list[PriceBar] = []
    for session_date in session_dates:
        close_time = session_close(session_date, Exchange.NASDAQ)
        for index, end in enumerate(minute_endpoints_for(session_date)):
            if omit is not None and end == omit:
                continue
            close = Decimal("40.00") + Decimal(index) / Decimal(100)
            out.append(
                PriceBar(
                    security_id=DENSE_MINUTE_SECURITY,
                    resolution=BarResolution.MINUTE,
                    bar_end_time=end,
                    bar_start_time=end - timedelta(minutes=1),
                    session_date=session_date,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    volume=1_000,
                    curation_source="synthetic:minute-dense",
                    bar_construction=BarConstruction.OFFICIAL_DISSEMINATED,
                    envelope=_bar_envelope(
                        construction=BarConstruction.OFFICIAL_DISSEMINATED,
                        bar_end_time=end,
                        session_close_time=close_time,
                        source_id=f"bar:{DENSE_MINUTE_SECURITY}:M1:{end.isoformat()}",
                    ),
                )
            )
    return tuple(out)


def sessions_with_a_full_length_half_day() -> tuple[MarketSession, ...]:
    """The calendar with the half day recorded as an ordinary session.

    A deliberately wrong calendar. The bars are unchanged and genuinely complete
    for a half day; only the venue's own hours are misstated, which is what makes
    the resulting refusal evidence that the grid comes from the calendar.
    """
    out: list[MarketSession] = []
    for session in sessions():
        if session.session_date != date(2019, 7, 3):
            out.append(session)
            continue
        out.append(
            MarketSession(
                exchange=session.exchange,
                session_date=session.session_date,
                regular_open=session.regular_open,
                regular_close=utc(2019, 7, 3, 20, 0),
                extended_open=session.extended_open,
                extended_close=session.extended_close,
                is_half_day=False,
                is_holiday=False,
                envelope=session.envelope,
            )
        )
    return tuple(out)


def dense_minute_publication(
    store: LocalTableStore,
    *,
    omit: datetime | None = None,
    calendar: Sequence[MarketSession] | None = None,
) -> VerifiedPublication:
    """Publish and verify a build whose minute grid is complete for both sessions."""
    datasets = source_datasets()
    datasets["price_bar"] = (*bars(), *dense_minute_bars(omit=omit))
    if calendar is not None:
        datasets["market_session"] = tuple(calendar)
    resolved = resolve_run_inputs(
        datasets,
        config=resolution(),
        approvals=approvals(),
    )
    dataset = build_gold_dataset(
        resolved,
        dataset_version=DATASET_VERSION,
        build_time=BUILD_TIME,
        coverage_start=COVERAGE_START,
        coverage_end=COVERAGE_END,
        universe_definition=universe_definition(),
        universe_sessions=SNAPSHOT_SESSIONS,
        evaluation_cutoffs=evaluation_cutoffs(),
        approvals=approvals(),
        artifact_first_built_time=ARTIFACT_FIRST_BUILT,
        ingestion_time=INGESTION_TIME,
    )
    publish_gold_dataset(
        store,
        dataset,
        quality_report=quality_report(),
        quality_plan=PHASE3A_QUALITY_PLAN,
        code_commit_sha=CODE_COMMIT_SHA,
        lag_policy_version=LAG_POLICY_VERSION,
        universe_definition_version=UNIVERSE_DEFINITION_VERSION,
        source_ingestion_run_ids=(INGESTION_RUN_ID,),
    )
    return read_published_dataset(
        store,
        dataset_version=DATASET_VERSION,
        config=resolution(),
        approvals=approvals(),
    )


def dense_minute_reader(
    store: LocalTableStore,
    *,
    omit: datetime | None = None,
    calendar: Sequence[MarketSession] | None = None,
) -> PointInTimeReader:
    """A reader over the dense-minute publication."""
    return PointInTimeReader(
        dense_minute_publication(store, omit=omit, calendar=calendar),
        resolution=resolution(),
        approvals=approvals(),
    )


INGESTION_RUN_ID = "ing-synthetic-a1-0001"
CODE_COMMIT_SHA = "0123456789abcdef0123456789abcdef01234567"


def bronze_payload() -> bytes:
    """A vendor-neutral Bronze payload for the continuously listed security.

    This is **KalpaMani's own envelope**, not any provider's format. No provider
    has been selected, so there is no vendor payload shape to map, and inventing
    one would be guessing at a decision nobody has made.
    """
    rows = [
        {
            "security_id": security_id,
            "resolution": BarResolution.DAILY.value,
            "bar_end_time": session_close(session_date).isoformat(),
            "bar_start_time": session_open(session_date).isoformat(),
            "open": close_text,
            "high": close_text,
            "low": close_text,
            "close": close_text,
            "volume": _DAILY_VOLUME,
            "bar_construction": BarConstruction.OFFICIAL_DISSEMINATED.value,
        }
        for security_id, session_date, close_text in _DAILY_CLOSES
        if security_id == SEC_CONTINUOUS and session_date.year == 2019
    ]
    return json.dumps({"bars": rows}, sort_keys=True, separators=(",", ":")).encode("utf-8")
