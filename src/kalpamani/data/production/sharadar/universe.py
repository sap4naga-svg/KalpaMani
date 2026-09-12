"""Historical universe membership -- ADR-0035 §3.4, the survivorship control.

**Built per session at one instant and stored, never filtered from today's listings.**
Membership for session ``d`` is fixed at ``decision_time(d) = open(d) - margin``, and
may consume only row versions whose governing availability under
``PROVIDER_REALISTIC_PIT`` is ``<= decision_time(d)``. Session ``d``'s own bar does not
exist at that instant, so **no clause reads it**: every price, volume and history clause
reads bars through ``d-1`` only, and whether ``d``'s bar later arrived, or the security
was delisted during ``d``, is a completeness question answered afterwards and never a
rewrite of ``membership(d)`` (C-1, C-3).

**Every attribute clause reads the revision admissible at the cutoff, or nothing.** The
``tickers`` snapshot has no dated history for exchange, security type, listing bounds,
sector or industry. For a session before the first admissible snapshot revision the
exchange and security-type clauses are **indeterminate**, and the security is excluded
with ``ATTRIBUTE_UNAVAILABLE`` rather than admitted on a value observed years later
(A-1). Today's attributes are never historical truth.

**The exclusion vocabulary is closed, and two of its members are proposed.**
``ATTRIBUTE_UNAVAILABLE`` and ``UNRESOLVED_CORPORATE_ACTION`` are members ADR-0035 proposes
for :class:`~kalpamani.data.contracts.vocabulary.UniverseExclusionReason` and the accepted
vocabulary does not carry. This module keeps them in a **build-local** vocabulary
(:class:`BuildExclusionReason`) whose accepted members mirror the accepted enum member for
member, so a membership row records which vocabulary its reason comes from and the
accepted contract is neither redefined nor widened here. The proposed amendment is
ADR-0039; nothing here is effective as contract vocabulary until it is.

**The rule is versioned and its parameters are carried, never compiled in silently.**
``breakout-long-v1``: listing life contains ``d``; exchange in the eligible set; a
domestic common stock; a bar for ``d-1`` and for ``N_history`` sessions before it, each
admissible at the cutoff; unadjusted close on ``d-1`` at or above the price floor;
average daily dollar volume over the trailing window at or above the ADDV floor; and no
spinoff ex-date on or before ``d`` (ADR-0035 §3.6). The first failing clause, in that
order, is the recorded reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.vocabulary import UniverseExclusionReason
from kalpamani.data.production.sharadar.availability import ResolvedLayer, ResolvedRow
from kalpamani.data.production.sharadar.sessions import DEFAULT_DECISION_MARGIN, SessionCalendar
from kalpamani.data.qualify.sharadar.parser import date_field, decimal_field

#: The universe rule version. Part of every manifest and of the build ``run_id``.
UNIVERSE_RULE_VERSION: Final = "breakout-long-v1"

#: Vendor exchange codes admitted by the exchange clause (NYSE, NASDAQ, NYSE American),
#: and vendor category values admitted by the security-type clause. Public vendor
#: vocabulary, pinned as rule parameters.
DEFAULT_ELIGIBLE_EXCHANGES: Final[frozenset[str]] = frozenset({"NYSE", "NASDAQ", "NYSEMKT"})
DEFAULT_COMMON_STOCK_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "Domestic Common Stock",
        "Domestic Common Stock Primary Class",
        "Domestic Common Stock Secondary Class",
    }
)

#: Vendor action tokens consumed by the listing-life and spinoff clauses.
ACTION_LISTED: Final = "listed"
ACTION_DELISTED: Final = "delisted"
ACTION_SPINOFF: Final = "spinoff"
ACTION_SPLIT: Final = "split"

#: The most sessions one build decides. A ceiling on work.
MAX_DECISION_SESSIONS: Final = 400


class BuildExclusionReason(StrEnum):
    """Why a security is not a member on a session. **Build-local**, closed.

    The first six mirror the accepted vocabulary member for member; the last two are
    the members ADR-0035 §3.4 and §3.6 propose (ADR-0039) and the accepted contract
    does not carry.
    """

    PRICE = "PRICE"
    MARKET_CAP = "MARKET_CAP"
    ADDV = "ADDV"
    HISTORY = "HISTORY"
    EXCHANGE = "EXCHANGE"
    SECURITY_TYPE = "SECURITY_TYPE"
    ATTRIBUTE_UNAVAILABLE = "ATTRIBUTE_UNAVAILABLE"
    UNRESOLVED_CORPORATE_ACTION = "UNRESOLVED_CORPORATE_ACTION"


#: The build-local members that are also accepted contract members.
ACCEPTED_EXCLUSIONS: Final[frozenset[BuildExclusionReason]] = frozenset(
    BuildExclusionReason(member.value) for member in UniverseExclusionReason
)
#: The build-local members ADR-0039 proposes. Implemented here, effective nowhere else.
PROPOSED_EXCLUSIONS: Final[frozenset[BuildExclusionReason]] = frozenset(
    {
        BuildExclusionReason.ATTRIBUTE_UNAVAILABLE,
        BuildExclusionReason.UNRESOLVED_CORPORATE_ACTION,
    }
)


def exclusion_vocabulary(reason: BuildExclusionReason) -> str:
    """Which vocabulary a reason belongs to: ``accepted`` or ``proposed-adr-0039``."""
    return "accepted" if reason in ACCEPTED_EXCLUSIONS else "proposed-adr-0039"


@dataclass(frozen=True, slots=True, kw_only=True)
class UniverseRule:
    """The versioned rule and its parameters. Configuration, carried in the manifest."""

    version: str = UNIVERSE_RULE_VERSION
    decision_margin: timedelta = DEFAULT_DECISION_MARGIN
    history_sessions: int = 20
    addv_window_sessions: int = 20
    price_floor: Decimal = Decimal("5")
    addv_floor: Decimal = Decimal("1000000")
    eligible_exchanges: frozenset[str] = DEFAULT_ELIGIBLE_EXCHANGES
    common_stock_categories: frozenset[str] = DEFAULT_COMMON_STOCK_CATEGORIES

    def __post_init__(self) -> None:
        if self.version != UNIVERSE_RULE_VERSION:
            raise ValueError("this module implements exactly one universe rule version")
        if self.decision_margin <= timedelta(0):
            raise ValueError("the decision margin is positive")
        if self.history_sessions < 1 or self.addv_window_sessions < 1:
            raise ValueError("window lengths are positive")
        if self.addv_window_sessions > self.history_sessions + 1:
            raise ValueError("the ADDV window cannot exceed the history the rule requires")
        if self.price_floor < 0 or self.addv_floor < 0:
            raise ValueError("floors are non-negative")

    def document(self) -> dict[str, Any]:
        """The rule parameters as the manifest records them."""
        return {
            "universe_rule_version": self.version,
            "decision_margin_seconds": int(self.decision_margin.total_seconds()),
            "history_sessions": self.history_sessions,
            "addv_window_sessions": self.addv_window_sessions,
            "price_floor": str(self.price_floor),
            "addv_floor": str(self.addv_floor),
            "eligible_exchanges": sorted(self.eligible_exchanges),
            "common_stock_categories": sorted(self.common_stock_categories),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class MembershipRow:
    """One ``(session, security)`` decision, with the inputs it consumed."""

    session_date: date
    security_id: str
    decision_time: datetime
    is_member: bool
    exclusion_reason: BuildExclusionReason | None
    price_at_eval: Decimal | None
    addv_at_eval: Decimal | None
    history_sessions_at_eval: int
    attribute_revision: str | None
    bars_consumed: tuple[str, ...]

    def __repr__(self) -> str:
        """Membership only. **Never an identity.**"""
        return f"MembershipRow(is_member={self.is_member})"

    def document(self) -> dict[str, Any]:
        """The closed membership document. Deterministic field order."""
        return {
            "session_date": self.session_date.isoformat(),
            "security_id": self.security_id,
            "decision_time": self.decision_time.isoformat(),
            "is_member": self.is_member,
            "exclusion_reason": None
            if self.exclusion_reason is None
            else self.exclusion_reason.value,
            "exclusion_vocabulary": (
                None
                if self.exclusion_reason is None
                else exclusion_vocabulary(self.exclusion_reason)
            ),
            "price_at_eval": None if self.price_at_eval is None else str(self.price_at_eval),
            "addv_at_eval": None if self.addv_at_eval is None else str(self.addv_at_eval),
            "history_sessions_at_eval": self.history_sessions_at_eval,
            "attribute_revision": self.attribute_revision,
            "bars_consumed": list(self.bars_consumed),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionCensus:
    """Per decision session: how determinable the attribute clauses were."""

    session_date: date
    securities: int
    attribute_determinable: int
    attribute_unavailable: int
    members: int

    def document(self) -> dict[str, Any]:
        """The census entry the manifest records. Counts only."""
        return {
            "session_date": self.session_date.isoformat(),
            "securities": self.securities,
            "attribute_determinable": self.attribute_determinable,
            "attribute_unavailable": self.attribute_unavailable,
            "members": self.members,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class UniverseSnapshot:
    """Every membership decision of one build, in canonical order, with the census."""

    rule: UniverseRule
    rows: tuple[MembershipRow, ...]
    census: tuple[SessionCensus, ...]
    undecidable_sessions: tuple[date, ...]

    def __repr__(self) -> str:
        """Counts only."""
        return f"UniverseSnapshot(rows={len(self.rows)}, sessions={len(self.census)})"


class _Facts:
    """Row versions indexed for one security, filtered at each cutoff on demand."""

    __slots__ = ("actions", "attributes", "bars")

    def __init__(self) -> None:
        self.attributes: list[ResolvedRow] = []
        self.bars: dict[date, list[ResolvedRow]] = {}
        self.actions: list[ResolvedRow] = []


def _index(layer: ResolvedLayer) -> dict[str, _Facts]:
    facts: dict[str, _Facts] = {}
    for row in layer.tickers:
        facts.setdefault(row.row.security_id, _Facts()).attributes.append(row)
    for row in layer.stocks:
        session = date_field(row.row.fields.get("date"))
        if session is None:
            continue
        facts.setdefault(row.row.security_id, _Facts()).bars.setdefault(session, []).append(row)
    for row in layer.actions:
        facts.setdefault(row.row.security_id, _Facts()).actions.append(row)
    return facts


def _latest_admissible(rows: list[ResolvedRow], *, cutoff: datetime) -> ResolvedRow | None:
    """The admissible version served: latest governing time, then highest revision."""
    admissible = [row for row in rows if row.availability.governing_time <= cutoff]
    if not admissible:
        return None
    return max(
        admissible,
        key=lambda row: (row.availability.governing_time, row.row.revision_sequence),
    )


def _admissible_actions(
    rows: list[ResolvedRow], *, cutoff: datetime, action: str
) -> list[tuple[date, ResolvedRow]]:
    out: list[tuple[date, ResolvedRow]] = []
    for row in rows:
        if row.availability.governing_time > cutoff:
            continue
        if row.row.fields.get("action") != action:
            continue
        when = date_field(row.row.fields.get("date"))
        if when is not None:
            out.append((when, row))
    return out


def _unadjusted_close(bar: ResolvedRow) -> Decimal | None:
    value = decimal_field(bar.row.fields.get("closeunadj"))
    return value if value is not None else decimal_field(bar.row.fields.get("close"))


def _dollar_volume(bar: ResolvedRow) -> Decimal | None:
    close = _unadjusted_close(bar)
    volume = decimal_field(bar.row.fields.get("volume"))
    if close is None or volume is None:
        return None
    return close * volume


def _listing_contains(
    facts: _Facts, attribute: ResolvedRow, *, cutoff: datetime, through: date
) -> bool:
    """Listed on or before ``through`` and not delisted on or before it."""
    fields = attribute.row.fields
    first = date_field(fields.get("firstpricedate"))
    last = date_field(fields.get("lastpricedate"))
    listed_events = [
        when for when, _ in _admissible_actions(facts.actions, cutoff=cutoff, action=ACTION_LISTED)
    ]
    delisted_events = [
        when
        for when, _ in _admissible_actions(facts.actions, cutoff=cutoff, action=ACTION_DELISTED)
    ]
    listed_by = min([d for d in [first, *listed_events] if d is not None], default=None)
    if listed_by is None or listed_by > through:
        return False
    if any(when <= through for when in delisted_events):
        return False
    delisted_flag = (fields.get("isdelisted") or "").upper() == "Y"
    return not (delisted_flag and last is not None and last <= through)


def _decide(
    security_id: str,
    facts: _Facts,
    *,
    session: date,
    cutoff: datetime,
    previous: date,
    rule: UniverseRule,
    calendar: SessionCalendar,
) -> MembershipRow:
    def excluded(
        reason: BuildExclusionReason,
        *,
        price: Decimal | None = None,
        addv: Decimal | None = None,
        history: int = 0,
        attribute: str | None = None,
        bars: tuple[str, ...] = (),
    ) -> MembershipRow:
        return MembershipRow(
            session_date=session,
            security_id=security_id,
            decision_time=cutoff,
            is_member=False,
            exclusion_reason=reason,
            price_at_eval=price,
            addv_at_eval=addv,
            history_sessions_at_eval=history,
            attribute_revision=attribute,
            bars_consumed=bars,
        )

    attribute = _latest_admissible(facts.attributes, cutoff=cutoff)
    if attribute is None:
        return excluded(BuildExclusionReason.ATTRIBUTE_UNAVAILABLE)
    attribute_id = attribute.row.content_sha256
    exchange = attribute.row.fields.get("exchange")
    category = attribute.row.fields.get("category")
    if exchange is None or category is None:
        return excluded(BuildExclusionReason.ATTRIBUTE_UNAVAILABLE, attribute=attribute_id)
    if exchange not in rule.eligible_exchanges:
        return excluded(BuildExclusionReason.EXCHANGE, attribute=attribute_id)
    if category not in rule.common_stock_categories:
        return excluded(BuildExclusionReason.SECURITY_TYPE, attribute=attribute_id)
    if not _listing_contains(facts, attribute, cutoff=cutoff, through=previous):
        return excluded(BuildExclusionReason.HISTORY, attribute=attribute_id)
    spinoffs = _admissible_actions(facts.actions, cutoff=cutoff, action=ACTION_SPINOFF)
    if any(when <= session for when, _ in spinoffs):
        return excluded(BuildExclusionReason.UNRESOLVED_CORPORATE_ACTION, attribute=attribute_id)

    # History: d-1 and N_history sessions before it, each with an admissible bar.
    needed = calendar.trailing(previous, count=rule.history_sessions + 1)
    consumed: list[tuple[date, ResolvedRow]] = []
    for when in needed:
        bar = _latest_admissible(facts.bars.get(when, []), cutoff=cutoff)
        if bar is None:
            break
        consumed.append((when, bar))
    history = len(consumed)
    bar_ids = tuple(f"{when.isoformat()}:{bar.row.content_sha256}" for when, bar in consumed)
    if len(needed) < rule.history_sessions + 1 or history < rule.history_sessions + 1:
        return excluded(
            BuildExclusionReason.HISTORY, history=history, attribute=attribute_id, bars=bar_ids
        )
    last_bar = consumed[-1][1]
    price = _unadjusted_close(last_bar)
    if price is None or price < rule.price_floor:
        return excluded(
            BuildExclusionReason.PRICE,
            price=price,
            history=history,
            attribute=attribute_id,
            bars=bar_ids,
        )
    window = consumed[-rule.addv_window_sessions :]
    maybe_volumes = [_dollar_volume(bar) for _, bar in window]
    volumes = [value for value in maybe_volumes if value is not None]
    if len(volumes) != len(maybe_volumes):
        return excluded(
            BuildExclusionReason.ADDV,
            price=price,
            history=history,
            attribute=attribute_id,
            bars=bar_ids,
        )
    addv = sum(volumes, Decimal(0)) / Decimal(len(volumes))
    if addv < rule.addv_floor:
        return excluded(
            BuildExclusionReason.ADDV,
            price=price,
            addv=addv,
            history=history,
            attribute=attribute_id,
            bars=bar_ids,
        )
    return MembershipRow(
        session_date=session,
        security_id=security_id,
        decision_time=cutoff,
        is_member=True,
        exclusion_reason=None,
        price_at_eval=price,
        addv_at_eval=addv,
        history_sessions_at_eval=history,
        attribute_revision=attribute_id,
        bars_consumed=bar_ids,
    )


def build_universe(
    layer: ResolvedLayer,
    *,
    rule: UniverseRule,
    calendar: SessionCalendar,
    sessions: tuple[date, ...],
    as_of: datetime,
) -> UniverseSnapshot:
    """Decide membership for every requested session. Deterministic; reads no ``d`` bar.

    A requested date that is not a calendar session, or has no previous session, is
    **undecidable** and recorded as such -- never decided on a guessed cutoff. Every
    decision consumes only facts admissible at ``min(decision_time(d), as_of)``: a
    build never holds a fact bounded after its own ``as_of``, whatever session it is
    deciding.
    """
    if type(layer) is not ResolvedLayer or type(rule) is not UniverseRule:
        raise TypeError("layer and rule must be exact")
    if type(calendar) is not SessionCalendar:
        raise TypeError("calendar must be an exact SessionCalendar")
    if len(sessions) > MAX_DECISION_SESSIONS or list(sessions) != sorted(set(sessions)):
        raise ValueError("sessions are distinct, ascending and bounded")
    if type(as_of) is not datetime or as_of.tzinfo is None:
        raise TypeError("as_of must be an aware datetime")
    facts = _index(layer)
    securities = sorted(facts)
    rows: list[MembershipRow] = []
    census: list[SessionCensus] = []
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
            decided = _decide(
                security_id,
                facts[security_id],
                session=session,
                cutoff=cutoff,
                previous=previous,
                rule=rule,
                calendar=calendar,
            )
            rows.append(decided)
            if decided.exclusion_reason is BuildExclusionReason.ATTRIBUTE_UNAVAILABLE:
                unavailable += 1
            else:
                determinable += 1
            members += int(decided.is_member)
        census.append(
            SessionCensus(
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


__all__ = [
    "ACCEPTED_EXCLUSIONS",
    "ACTION_DELISTED",
    "ACTION_LISTED",
    "ACTION_SPINOFF",
    "ACTION_SPLIT",
    "DEFAULT_COMMON_STOCK_CATEGORIES",
    "DEFAULT_ELIGIBLE_EXCHANGES",
    "MAX_DECISION_SESSIONS",
    "PROPOSED_EXCLUSIONS",
    "UNIVERSE_RULE_VERSION",
    "BuildExclusionReason",
    "MembershipRow",
    "SessionCensus",
    "UniverseRule",
    "UniverseSnapshot",
    "build_universe",
    "exclusion_vocabulary",
]
