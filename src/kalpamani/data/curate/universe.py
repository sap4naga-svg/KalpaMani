"""Historical universe construction -- the survivorship control.

Membership is **built once per session and stored**. It is never recomputed at
query time and never derived by filtering today's listed securities. That single
rule is what stops the defect that is otherwise invisible: a 2018 backtest run
over the securities that still exist in 2026 will look excellent, and nothing in
its output will say why.

Three properties this module has to have, and each is tested:

**Determinism.** The same inputs, rule version and resolved profile produce
byte-identical membership. A rebuild that drifts means the rule was reading
something it did not declare.

**Admissibility.** Every evaluation input is checked against the session's own
cutoff -- the regular open, since a universe has to be known before trading
starts. An input whose governing availability is later than that cutoff is
refused, not quietly used. This is check 6.6, and it exists precisely because
"universe construction quietly uses current data" is the easiest mistake in the
whole system to make and the hardest to see afterwards.

**Refusal over substitution.** A definition that declares a threshold whose input
domain does not exist is **refused**. In this slice that is the market-cap
threshold: shares outstanding is a Phase-3B fundamental, so a definition naming
``min_market_cap`` has no admissible input for it. Computing the universe anyway
would publish a different rule under the declared ``universe_definition_version``
and nothing downstream would say so.

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
from kalpamani.data.contracts.resolution import (
    BoundApprovals,
    PitRecord,
    decision_available_time,
    is_eligible,
)
from kalpamani.data.contracts.serde import encode_universe_membership
from kalpamani.data.contracts.vocabulary import (
    BarResolution,
    Exchange,
    InformationSetProfile,
    UniverseExclusionReason,
)

#: Version of the eligibility computation itself, distinct from the rule version.
UNIVERSE_SPEC_VERSION = "universe-build/a1.1"

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
    """Everything a snapshot is built from, named so lineage can be complete."""

    listings: tuple[Listing, ...]
    attributes: tuple[SecurityAttribute, ...]
    bars: tuple[PriceBar, ...]
    listing_dataset_version: str
    attribute_dataset_version: str
    bar_dataset_version: str


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


def admissible_inputs(
    *,
    listings: Sequence[Listing],
    attributes: Sequence[SecurityAttribute],
    bars: Sequence[PriceBar],
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
    evaluation_cutoff: datetime,
) -> tuple[PitRecord, ...]:
    """The exact input set a universe build at ``evaluation_cutoff`` consumes.

    Shared by the builder and by lineage replay on read, so the two cannot
    diverge. A rebuild reads what the build read because it runs the same
    function, not because two implementations agree today.
    """
    return (
        *_admissible_listings(listings, resolved_profile, approvals, evaluation_cutoff),
        *_admissible_attributes(attributes, resolved_profile, approvals, evaluation_cutoff),
        *_admissible_bars(bars, resolved_profile, approvals, evaluation_cutoff),
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
        if held is None or listing.envelope.revision_sequence > held.envelope.revision_sequence:
            latest[key] = listing
    return tuple(sorted(latest.values(), key=lambda item: (item.security_id, item.listing_id)))


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
) -> tuple[UniverseMembership, ...]:
    """Build the stored membership snapshot for one session.

    ``evaluation_cutoff`` is the session's own regular open: a universe has to be
    known before the session it governs begins. Every input is filtered against
    it, so an input published during or after the session cannot influence
    membership.

    Raises:
        RequiredInputUnavailableError: if the definition declares a threshold
            whose input domain is not available in this slice.
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

    consumed: tuple[PitRecord, ...] = admissible_inputs(
        listings=inputs.listings,
        attributes=inputs.attributes,
        bars=inputs.bars,
        resolved_profile=resolved_profile,
        approvals=approvals,
        evaluation_cutoff=evaluation_cutoff,
    )
    lineage = (
        LineageRef.of(
            entity="listing",
            dataset_version=inputs.listing_dataset_version,
            selector={"session": session_date.isoformat()},
        ),
        LineageRef.of(
            entity="security_attribute",
            dataset_version=inputs.attribute_dataset_version,
            selector={"attributes": "security_type", "session": session_date.isoformat()},
        ),
        LineageRef.of(
            entity="price_bar",
            dataset_version=inputs.bar_dataset_version,
            selector={
                "resolution": BarResolution.DAILY.value,
                "through": session_date.isoformat(),
            },
        ),
    )

    rows: list[UniverseMembership] = []
    for listing in current_listings(admissible_listings):
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
                    derivation_spec_version=(f"{UNIVERSE_SPEC_VERSION}+{definition.version}"),
                    artifact_content_hash=content_hash(
                        {
                            "session_date": session_date,
                            "security_id": listing.security_id,
                            "definition": definition.version,
                            "resolved_profile": resolved_profile.value,
                            "is_member": decision.is_member,
                        }
                    ),
                    validity=OutputValidityDeclaration.session_scoped(session_date),
                    ingestion_time=ingestion_time,
                    dataset_version=dataset_version,
                ),
            )
        )
    return tuple(rows)


@dataclass(frozen=True, slots=True, kw_only=True)
class _Decision:
    is_member: bool
    reason: UniverseExclusionReason | None
    price: Decimal | None
    addv: Decimal | None
    history_sessions: int
    is_common_stock_eligible: bool


def _evaluate(
    *,
    security_id: str,
    listing: Listing,
    session_date: date,
    definition: UniverseDefinition,
    bars: Sequence[PriceBar],
    attributes: Sequence[SecurityAttribute],
) -> _Decision:
    history = tuple(
        sorted(
            (
                bar
                for bar in bars
                if bar.security_id == security_id and bar.session_date < session_date
            ),
            key=lambda bar: bar.session_date,
        )
    )
    price = history[-1].close if history else None
    window = history[-definition.addv_window_sessions :] if history else ()
    addv = _average_dollar_volume(window)
    security_type = _attribute_on(attributes, security_id, "security_type", session_date)
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
        is_member=reason is None,
        reason=reason,
        price=price,
        addv=addv,
        history_sessions=len(history),
        is_common_stock_eligible=common_eligible,
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
) -> str | None:
    for row in attributes:
        if row.security_id != security_id or row.attribute != attribute:
            continue
        if row.valid_from <= on and (row.valid_to is None or on <= row.valid_to):
            return row.value
    return None


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


def snapshot_content_hash(rows: Sequence[UniverseMembership]) -> str:
    """A hash over the whole snapshot, so a rebuild can be compared bit for bit."""
    return content_hash([encode_universe_membership(row) for row in rows])


__all__ = [
    "UNIVERSE_SPEC_VERSION",
    "UniverseBuildInputs",
    "UniverseDefinition",
    "admissible_inputs",
    "build_universe_snapshot",
    "current_listings",
    "snapshot_content_hash",
]
