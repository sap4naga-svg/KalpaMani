"""Historical universe construction -- the survivorship control.

Membership is **built once per session and stored**. It is never recomputed at
query time and never derived by filtering today's listed securities. That single
rule is what stops the defect that is otherwise invisible: a 2018 backtest run
over the securities that still exist in 2026 will look excellent, and nothing in
its output will say why.

Four properties this module has to have, and each is tested:

**Determinism.** The same inputs, rule version and resolved profile produce
byte-identical membership. A rebuild that drifts means the rule was reading
something it did not declare.

**Admissibility.** Every evaluation input is checked against the session's own
cutoff -- the regular open, since a universe has to be known before trading
starts. An input whose governing availability is later than that cutoff is
refused, not quietly used. This is check 6.6, and it exists precisely because
"universe construction quietly uses current data" is the easiest mistake in the
whole system to make and the hardest to see afterwards.

**Refusal over an empty answer.** A build whose required inputs are all
inadmissible under the resolved profile does not produce a zero-security market.
It produces **no snapshot**, with :class:`RequiredInputUnavailableError` naming
the domains and the reason. The distinction is load-bearing: a universe that
could not be computed and a universe that genuinely selected nobody look
identical downstream and mean opposite things. A rule that legitimately selects
no securities from admissible inputs still publishes -- as a valid snapshot whose
rows are all non-members, each carrying its exclusion reason.

**Exact lineage.** Each membership row records only the inputs that decided
*that security*: one listing revision, one attribute row, and that security's own
bars. Attaching the whole admissible input set to every row would make lineage
true and useless -- a changed bar for some other security would look like a
changed input for this one.

Thresholds here are **versioned synthetic parameters proving the mechanism**.
Blueprint s.4's production thresholds are not implemented over real data, because
there is no real data and no provider.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal

from kalpamani.data.contracts.canonical import content_hash
from kalpamani.data.contracts.dataset import UniverseSnapshotHeader
from kalpamani.data.contracts.entities import (
    Listing,
    PriceBar,
    SecurityAttribute,
    UniverseMembership,
)
from kalpamani.data.contracts.envelope import (
    DerivedEnvelope,
    LineageRef,
    OutputValidityDeclaration,
)
from kalpamani.data.contracts.errors import RequiredInputUnavailableError
from kalpamani.data.contracts.instants import normalize_instant
from kalpamani.data.contracts.resolution import (
    BoundApprovals,
    PitRecord,
    decision_available_time,
    is_eligible,
)
from kalpamani.data.contracts.vocabulary import (
    BarResolution,
    Exchange,
    InformationSetProfile,
    ListingFactKind,
    UniverseExclusionReason,
)
from kalpamani.data.curate.lineage import (
    attribute_selector,
    bar_lineage_refs,
    lineage_fingerprint,
    listing_selector,
)

#: Version of the eligibility computation itself, distinct from the rule version.
UNIVERSE_SPEC_VERSION = "universe-build/a1.2"

#: The input domains a universe build declares REQUIRED. Emptying any of them is
#: a refusal, not a smaller universe.
REQUIRED_UNIVERSE_DOMAINS = ("listing", "security_attribute", "price_bar")

_MONEY = Decimal("0.01")


@dataclass(frozen=True, slots=True, kw_only=True)
class UniverseDefinition:
    """A versioned eligibility rule. Changing it produces a new version.

    It does not retroactively change history: a snapshot records the version that
    produced it, so an old snapshot stays the answer the old rule gave.
    """

    version: str
    min_close_price: Decimal
    min_addv: Decimal
    min_history_sessions: int
    addv_window_sessions: int
    eligible_exchanges: frozenset[Exchange]
    eligible_security_types: frozenset[str]
    #: Declared but unsatisfiable in this slice -- its input is a Phase-3B
    #: fundamental. A definition that sets it is refused rather than approximated.
    min_market_cap: Decimal | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class UniverseBuildInputs:
    """Everything a universe build reads.

    Deliberately carries no dataset-version fields. Each row already knows which
    source build it came from, and lineage reads that: a Gold version stores a
    copy of a row, and a copy does not become the source.
    """

    listings: tuple[Listing, ...]
    attributes: tuple[SecurityAttribute, ...]
    bars: tuple[PriceBar, ...]


def _admissible(
    record: PitRecord,
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
    cutoff: datetime,
) -> bool:
    if not is_eligible(record, resolved_profile):
        return False
    available = decision_available_time(record, resolved_profile, approvals)
    return available is not None and available <= cutoff


def _admissible_bars(
    bars: Sequence[PriceBar],
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
    cutoff: datetime,
) -> tuple[PriceBar, ...]:
    return tuple(
        bar
        for bar in bars
        if bar.resolution is BarResolution.DAILY
        and _admissible(bar, resolved_profile, approvals, cutoff)
    )


def _admissible_listings(
    listings: Sequence[Listing],
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
    cutoff: datetime,
) -> tuple[Listing, ...]:
    return tuple(
        listing for listing in listings if _admissible(listing, resolved_profile, approvals, cutoff)
    )


def _admissible_attributes(
    attributes: Sequence[SecurityAttribute],
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
    cutoff: datetime,
) -> tuple[SecurityAttribute, ...]:
    return tuple(
        attribute
        for attribute in attributes
        if _admissible(attribute, resolved_profile, approvals, cutoff)
    )


def current_listings(listings: Sequence[Listing]) -> tuple[Listing, ...]:
    """The listing revision that stood at the cutoff, one per listing and fact kind.

    A delisting is not a correction to the row that said the security was listed:
    it is a later revision of the same fact, available only once it happened. Both
    rows are admissible after the delisting, and taking the highest admissible
    revision is what stops the open-ended earlier row from claiming the security
    is still listed years later. This is ``AS_KNOWN_AT_AS_OF`` applied to
    listings -- the normative historical view, stated rather than assumed.
    """
    latest: dict[tuple[str, str], Listing] = {}
    for listing in listings:
        key = (listing.listing_id, listing.listing_fact_kind.value)
        held = latest.get(key)
        if held is None:
            latest[key] = listing
            continue
        if listing.envelope.revision_sequence > held.envelope.revision_sequence:
            latest[key] = listing
        elif listing.envelope.revision_sequence == held.envelope.revision_sequence and (
            listing != held
        ):
            raise RequiredInputUnavailableError(
                "REQUIRED_INPUT_UNAVAILABLE: two different rows share listing "
                f"{listing.listing_id!r} kind {listing.listing_fact_kind.value} at revision "
                f"{listing.envelope.revision_sequence}. Contradictory evidence at one revision "
                "has no later revision to supersede it, and choosing between them by "
                "iteration order would make membership depend on table order."
            )
    return tuple(sorted(latest.values(), key=lambda item: (item.security_id, item.listing_id)))


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotBuild:
    """One session's membership rows, and the listing states the rule considered.

    The considered set is returned rather than recomputed by the caller because
    the snapshot header's lineage depends on it, and a header whose lineage was
    derived by running the admissibility rules a second time would be evidence
    about a second run.
    """

    rows: tuple[UniverseMembership, ...]
    considered_listings: tuple[Listing, ...]
    #: Per required domain: rows supplied, and rows admissible at the cutoff. The
    #: build's own account of what it had to work with.
    required_domain_coverage: tuple[tuple[str, int, int], ...] = ()


def build_universe_snapshot(
    inputs: UniverseBuildInputs,
    *,
    session_date: date,
    evaluation_cutoff: datetime,
    definition: UniverseDefinition,
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
    artifact_first_built_time: datetime,
    ingestion_time: datetime,
    dataset_version: str,
) -> SnapshotBuild:
    """Build the stored membership snapshot for one session.

    ``evaluation_cutoff`` is the session's own regular open: a universe has to be
    known before the session it governs begins. Every input is filtered against
    it, so an input published during or after the session cannot influence
    membership.

    Raises:
        RequiredInputUnavailableError: if the definition declares a threshold
            whose input domain is not available in this slice, or if any REQUIRED
            input domain that was supplied is emptied by eligibility or
            availability filtering under ``resolved_profile``. The second case is
            the one that matters: an unbuildable universe is **not** a
            zero-security market, and publishing an empty snapshot would make the
            two indistinguishable.
    """
    if definition.min_market_cap is not None:
        raise RequiredInputUnavailableError(
            "REQUIRED_INPUT_UNAVAILABLE: universe definition "
            f"{definition.version} declares min_market_cap, whose input (shares outstanding) "
            "is a Phase-3B fundamental and has no admissible rows in this slice. Computing "
            "the universe without it would publish a different rule under the same "
            "universe_definition_version, and nothing downstream would say so."
        )

    admissible_bars = _admissible_bars(inputs.bars, resolved_profile, approvals, evaluation_cutoff)
    admissible_listings = _admissible_listings(
        inputs.listings, resolved_profile, approvals, evaluation_cutoff
    )
    admissible_attributes = _admissible_attributes(
        inputs.attributes, resolved_profile, approvals, evaluation_cutoff
    )

    supplied = {
        "listing": len(inputs.listings),
        "security_attribute": len(inputs.attributes),
        "price_bar": sum(1 for bar in inputs.bars if bar.resolution is BarResolution.DAILY),
    }
    admissible = {
        "listing": len(admissible_listings),
        "security_attribute": len(admissible_attributes),
        "price_bar": len(admissible_bars),
    }
    _require_inputs(
        session_date=session_date,
        resolved_profile=resolved_profile,
        evaluation_cutoff=evaluation_cutoff,
        supplied=supplied,
        admissible=admissible,
    )
    coverage = tuple((domain, supplied[domain], admissible[domain]) for domain in sorted(supplied))

    # The window the rule actually looks at for prior history: everything ending
    # before the session's own evaluation cutoff. A bar for this session ends at
    # the close, which is after the open, so it falls outside -- which is exactly
    # the boundary `_evaluate` draws with `bar.session_date < session_date`.
    #
    # Bounded below by the earliest admissible bar rather than left open, because
    # an unbounded window would claim more than the build looked at.
    history_window = _history_window(inputs.bars, evaluation_cutoff)
    bar_publications = sorted({bar.envelope.dataset_version for bar in inputs.bars})

    rows: list[UniverseMembership] = []
    considered: list[Listing] = []
    for listing in current_listings(admissible_listings):
        if listing.listing_fact_kind is not ListingFactKind.STATE:
            # A CHANGE_ANNOUNCEMENT says a listing is about to change. It is not
            # a listing state, and treating it as one would let an announced
            # future delisting decide today's membership.
            continue
        considered.append(listing)
        if not listing.is_listed_on(session_date):
            continue
        decision = _evaluate(
            security_id=listing.security_id,
            listing=listing,
            session_date=session_date,
            definition=definition,
            bars=admissible_bars,
            attributes=admissible_attributes,
        )
        lineage = _lineage_for(
            decision,
            listing=listing,
            history_window=history_window,
            bar_publications=bar_publications,
            resolved_profile=resolved_profile,
        )
        attribute_rows = () if decision.attribute is None else (decision.attribute,)
        consumed: tuple[PitRecord, ...] = (listing, *attribute_rows, *decision.history)
        rows.append(
            UniverseMembership(
                session_date=session_date,
                security_id=listing.security_id,
                universe_definition_version=definition.version,
                resolved_profile=resolved_profile,
                is_member=decision.is_member,
                price_at_eval=decision.price,
                market_cap_at_eval=None,
                addv_at_eval=decision.addv,
                history_sessions_at_eval=decision.history_sessions,
                exclusion_reason=decision.reason,
                is_common_stock_eligible=decision.is_common_stock_eligible,
                inputs=consumed,
                envelope=DerivedEnvelope(
                    lineage=lineage,
                    artifact_first_built_time=artifact_first_built_time,
                    derivation_spec_version=f"{UNIVERSE_SPEC_VERSION}+{definition.version}",
                    artifact_content_hash=membership_content_hash(
                        session_date=session_date,
                        security_id=listing.security_id,
                        definition_version=definition.version,
                        resolved_profile=resolved_profile,
                        is_member=decision.is_member,
                        price_at_eval=decision.price,
                        market_cap_at_eval=None,
                        addv_at_eval=decision.addv,
                        history_sessions_at_eval=decision.history_sessions,
                        exclusion_reason=(
                            None if decision.reason is None else decision.reason.value
                        ),
                        is_common_stock_eligible=decision.is_common_stock_eligible,
                        lineage=lineage,
                    ),
                    validity=OutputValidityDeclaration.session_scoped(session_date),
                    ingestion_time=ingestion_time,
                    dataset_version=dataset_version,
                ),
            )
        )
    return SnapshotBuild(
        rows=tuple(rows),
        considered_listings=tuple(considered),
        required_domain_coverage=coverage,
    )


def _require_inputs(
    *,
    session_date: date,
    resolved_profile: InformationSetProfile,
    evaluation_cutoff: datetime,
    supplied: dict[str, int],
    admissible: dict[str, int],
) -> None:
    """Refuse the build when a REQUIRED domain has no admissible rows.

    **Both** cases refuse, and the earlier implementation checked only the
    second: a domain supplied with nothing at all is exactly as unavailable as
    one filtered down to nothing. Treating "never supplied" as acceptable would
    make a build over an entirely absent listing table produce a confident
    zero-security universe.

    Publishing an empty snapshot instead would let a profile that cannot reach
    back before we existed answer a historical question with a zero-security
    market -- the substitution the contract forbids, wearing an empty result
    rather than the wrong profile's answer.
    """
    unavailable = {
        domain: (supplied.get(domain, 0), admissible.get(domain, 0))
        for domain in REQUIRED_UNIVERSE_DOMAINS
        if admissible.get(domain, 0) == 0
    }
    if not unavailable:
        return
    detail = {
        domain: f"supplied={counts[0]}, admissible={counts[1]}"
        for domain, counts in unavailable.items()
    }
    raise RequiredInputUnavailableError(
        "REQUIRED_INPUT_UNAVAILABLE: the universe build for "
        f"{session_date.isoformat()} under {resolved_profile.value} has no admissible rows in "
        f"{sorted(unavailable)} at the evaluation cutoff {evaluation_cutoff.isoformat()} "
        f"({detail}). A domain never supplied is exactly as unavailable as one filtered to "
        "nothing. The snapshot is unavailable, not empty: a universe that could not be "
        "computed and one that genuinely selected nobody look identical downstream and mean "
        "opposite things."
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class _Decision:
    security_id: str
    is_member: bool
    reason: UniverseExclusionReason | None
    price: Decimal | None
    addv: Decimal | None
    history_sessions: int
    is_common_stock_eligible: bool
    #: Exactly the rows this decision read.
    attribute: SecurityAttribute | None
    history: tuple[PriceBar, ...]


def _history_window(
    bars: Sequence[PriceBar],
    evaluation_cutoff: datetime,
) -> tuple[datetime, datetime]:
    """The instant window a no-history claim is made about.

    Upper bound is the session's own evaluation cutoff -- a universe is known
    before the session it governs opens, so a bar ending after that was not
    available to the decision. Lower bound is the earliest bar the build holds,
    because a claim reaching further back than the build looked would assert more
    than it checked.
    """
    upper = normalize_instant(evaluation_cutoff)
    endpoints = [normalize_instant(bar.bar_end_time) for bar in bars]
    lower = min(endpoints) if endpoints else upper
    return (min(lower, upper), upper)


def _evaluate(
    *,
    security_id: str,
    listing: Listing,
    session_date: date,
    definition: UniverseDefinition,
    bars: Sequence[PriceBar],
    attributes: Sequence[SecurityAttribute],
) -> _Decision:
    prior = (
        bar for bar in bars if bar.security_id == security_id and bar.session_date < session_date
    )
    history = tuple(sorted(prior, key=lambda bar: bar.session_date))
    price = history[-1].close if history else None
    window = history[-definition.addv_window_sessions :] if history else ()
    addv = _average_dollar_volume(window)
    attribute = _attribute_on(attributes, security_id, "security_type", session_date)
    if attribute is None:
        # Absent evidence is not evidence of the wrong type. Labelling it
        # SECURITY_TYPE would publish "this is not a common stock" as a finding
        # when the truth is that nothing said what it is.
        raise RequiredInputUnavailableError(
            "REQUIRED_INPUT_UNAVAILABLE: no admissible security_type evidence for "
            f"{security_id} on {session_date.isoformat()}. A missing attribute is an "
            "unanswerable question, not a SECURITY_TYPE exclusion."
        )
    security_type = attribute.value
    common_eligible = security_type in definition.eligible_security_types

    reason: UniverseExclusionReason | None = None
    if listing.exchange not in definition.eligible_exchanges:
        reason = UniverseExclusionReason.EXCHANGE
    elif not common_eligible:
        reason = UniverseExclusionReason.SECURITY_TYPE
    elif len(history) < definition.min_history_sessions:
        reason = UniverseExclusionReason.HISTORY
    elif price is None or price < definition.min_close_price:
        reason = UniverseExclusionReason.PRICE
    elif addv is None or addv < definition.min_addv:
        reason = UniverseExclusionReason.ADDV

    return _Decision(
        security_id=security_id,
        is_member=reason is None,
        reason=reason,
        price=price,
        addv=addv,
        history_sessions=len(history),
        is_common_stock_eligible=common_eligible,
        attribute=attribute,
        history=history,
    )


def _lineage_for(
    decision: _Decision,
    *,
    listing: Listing,
    history_window: tuple[datetime, datetime],
    bar_publications: Sequence[str],
    resolved_profile: InformationSetProfile,
) -> tuple[LineageRef, ...]:
    """Exactly the rows that decided this security, in the versions they came from.

    A price history spanning two immutable source versions produces two
    references, not one that quietly averages them: replaying a single reference
    would look for every bar in one version and either miss them or find the
    wrong ones.

    A security with **no** prior bars produces a negative-coverage reference
    instead. ``history_window`` is the window the rule actually looked at, and
    ``bar_publications`` are the builds it looked in, so replay can search for a
    bar that would contradict the decision rather than accepting a sentinel that
    resolved to nothing whatever the store held.
    """
    refs = [
        LineageRef.of(
            entity="listing",
            dataset_version=listing.envelope.dataset_version,
            selector=listing_selector(listing),
        )
    ]
    if decision.attribute is not None:
        refs.append(
            LineageRef.of(
                entity="security_attribute",
                dataset_version=decision.attribute.envelope.dataset_version,
                selector=attribute_selector(decision.attribute),
            )
        )
    refs.extend(
        bar_lineage_refs(
            decision.security_id,
            BarResolution.DAILY,
            decision.history,
            absence_window=history_window,
            absence_versions=bar_publications,
            absence_profile=resolved_profile,
        )
    )
    return tuple(refs)


def membership_content_hash(
    *,
    session_date: date,
    security_id: str,
    definition_version: str,
    resolved_profile: InformationSetProfile,
    is_member: bool,
    price_at_eval: Decimal | None,
    market_cap_at_eval: Decimal | None,
    addv_at_eval: Decimal | None,
    history_sessions_at_eval: int,
    exclusion_reason: str | None,
    is_common_stock_eligible: bool,
    lineage: Sequence[LineageRef],
) -> str:
    """Hash the whole decision, not just its outcome.

    Every value that could differ between two builds while the row still called
    itself the same membership row is in here, including the canonical lineage. A
    hash over the outcome alone would verify while the evidence behind it drifted.
    """
    return content_hash(
        {
            "session_date": session_date,
            "security_id": security_id,
            "universe_definition_version": definition_version,
            "resolved_profile": resolved_profile.value,
            "is_member": is_member,
            "price_at_eval": price_at_eval,
            "market_cap_at_eval": market_cap_at_eval,
            "addv_at_eval": addv_at_eval,
            "history_sessions_at_eval": history_sessions_at_eval,
            "exclusion_reason": exclusion_reason,
            "is_common_stock_eligible": is_common_stock_eligible,
            "lineage": [list(item) for item in lineage_fingerprint(lineage)],
        }
    )


def membership_hash_of(row: UniverseMembership) -> str:
    """Recompute the content hash a stored membership row should carry."""
    return membership_content_hash(
        session_date=row.session_date,
        security_id=row.security_id,
        definition_version=row.universe_definition_version,
        resolved_profile=row.resolved_profile,
        is_member=row.is_member,
        price_at_eval=row.price_at_eval,
        market_cap_at_eval=row.market_cap_at_eval,
        addv_at_eval=row.addv_at_eval,
        history_sessions_at_eval=row.history_sessions_at_eval,
        exclusion_reason=None if row.exclusion_reason is None else row.exclusion_reason.value,
        is_common_stock_eligible=row.is_common_stock_eligible,
        lineage=row.envelope.lineage,
    )


def _average_dollar_volume(bars: Sequence[PriceBar]) -> Decimal | None:
    if not bars:
        return None
    total = sum((bar.close * Decimal(bar.volume) for bar in bars), Decimal(0))
    return (total / Decimal(len(bars))).quantize(_MONEY, rounding=ROUND_HALF_EVEN)


def _attribute_on(
    attributes: Sequence[SecurityAttribute],
    security_id: str,
    attribute: str,
    on: date,
) -> SecurityAttribute | None:
    """The one attribute row in force on ``on``, or ``None`` if there is none.

    Raises:
        RequiredInputUnavailableError: if two rows are in force at once. An
            overlapping attribute history is contradictory evidence, not a
            preference to be resolved by iteration order -- picking the first
            would make membership depend on table order.
    """
    matches = [
        row
        for row in attributes
        if row.security_id == security_id
        and row.attribute == attribute
        and row.valid_from <= on
        and (row.valid_to is None or on <= row.valid_to)
    ]
    if len(matches) > 1:
        raise RequiredInputUnavailableError(
            f"REQUIRED_INPUT_UNAVAILABLE: {len(matches)} {attribute!r} rows are in force for "
            f"{security_id} on {on.isoformat()} "
            f"(valid_from {[row.valid_from.isoformat() for row in matches]}). Overlapping "
            "attribute evidence is contradictory, and resolving it by iteration order would "
            "make membership depend on table order."
        )
    return matches[0] if matches else None


def build_snapshot_header(
    rows: Sequence[UniverseMembership],
    *,
    session_date: date,
    definition: UniverseDefinition,
    resolved_profile: InformationSetProfile,
    evaluation_cutoff: datetime,
    considered_listings: Sequence[Listing],
    required_domain_coverage: Sequence[tuple[str, int, int]] = (),
    artifact_first_built_time: datetime,
    ingestion_time: datetime,
    dataset_version: str,
) -> UniverseSnapshotHeader:
    """Record that this session's snapshot was **built**, rows or no rows.

    A snapshot whose rule legitimately selected nobody has zero member rows; a
    session that was never built has zero rows too. Only the header separates
    them, and the separation is the difference between "nobody qualified" and
    "we cannot answer".

    The header is a derived artifact, so it carries the lineage the build read:
    every membership decision's exact inputs **and** every listing state the rule
    considered, whether or not it produced a row. ``required_domain_coverage``
    records what each required domain supplied and how much of it was admissible,
    so a zero-row snapshot can be read alongside what the rule had to work with.

    Raises:
        RequiredInputUnavailableError: if no listing-state row was considered at
            all. A snapshot with no lineage asserts that nobody was listed on
            evidence it cannot name, and "we saw no listing states" is not the
            same finding as "nobody was listed".
    """
    lineage = _snapshot_lineage(rows, considered_listings=considered_listings)
    if not lineage:
        raise RequiredInputUnavailableError(
            f"REQUIRED_INPUT_UNAVAILABLE: no listing-state row was available for "
            f"{session_date.isoformat()} under {resolved_profile.value}, so the snapshot has "
            "no lineage. A zero-row snapshot means the rule selected nobody; without evidence "
            "it read, it would instead mean we never looked."
        )
    content = snapshot_content_hash(rows)
    spec_version = f"{UNIVERSE_SPEC_VERSION}+{definition.version}"
    return UniverseSnapshotHeader(
        session_date=session_date,
        universe_definition_version=definition.version,
        resolved_profile=resolved_profile,
        evaluation_cutoff=evaluation_cutoff,
        row_count=len(rows),
        snapshot_content_hash=content,
        derivation_spec_version=spec_version,
        required_domain_coverage=tuple(sorted(required_domain_coverage)),
        envelope=DerivedEnvelope(
            lineage=lineage,
            artifact_first_built_time=artifact_first_built_time,
            derivation_spec_version=spec_version,
            artifact_content_hash=content,
            validity=OutputValidityDeclaration.session_scoped(session_date),
            ingestion_time=ingestion_time,
            dataset_version=dataset_version,
        ),
        status="COMPLETE",
    )


def _snapshot_lineage(
    rows: Sequence[UniverseMembership],
    *,
    considered_listings: Sequence[Listing],
) -> tuple[LineageRef, ...]:
    """Every input the snapshot as a whole read, deduplicated and ordered.

    Both halves, always: every membership decision's exact lineage, **and** every
    listing state the rule considered -- including those that produced no row.

    The considered set used to be attached only when the membership lineage was
    empty, which is precisely backwards. The evidence for "this security was
    looked at and did not qualify" appeared only when nothing qualified at all,
    and disappeared the moment one other security did. A security the rule
    examined and excluded is part of what the snapshot decided either way.
    """
    refs: set[LineageRef] = set()
    for row in rows:
        refs.update(row.envelope.lineage)
    for listing in considered_listings:
        refs.add(
            LineageRef.of(
                entity="listing",
                dataset_version=listing.envelope.dataset_version,
                selector=listing_selector(listing),
            )
        )
    return tuple(sorted(refs, key=lambda ref: (ref.entity, ref.dataset_version, ref.selector)))


def snapshot_content_hash(rows: Sequence[UniverseMembership]) -> str:
    """A hash over the whole snapshot, so a rebuild can be compared bit for bit."""
    return content_hash(sorted(membership_hash_of(row) for row in rows))


__all__ = [
    "REQUIRED_UNIVERSE_DOMAINS",
    "UNIVERSE_SPEC_VERSION",
    "SnapshotBuild",
    "UniverseBuildInputs",
    "UniverseDefinition",
    "build_snapshot_header",
    "build_universe_snapshot",
    "current_listings",
    "membership_content_hash",
    "membership_hash_of",
    "snapshot_content_hash",
]
