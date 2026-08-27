"""Resolved fact-time anchors, and the domain aliases that feed them.

:mod:`kalpamani.data.contracts.resolution` answers *when could this have been
known*. This module answers the other half -- *when did the fact happen* -- and
the two together are what the class invariants compare.

Reading raw fields for the second half was a real defect in an earlier revision
of the plan: a date-only announcement with a perfectly good approved upper bound
had a null ``announcement_time``, so its invariant silently did not run and the
row was waved through. An anchor that resolves the same exact-then-approved-bound
way the availability axes do fixes that, and the table below makes the outcome
mechanical:

======================================  ==========================================
case                                    outcome
======================================  ==========================================
exact announcement time                 accepted, and the invariant **is checked**
date-only with an **approved** bound    accepted, checked against the bound
neither exact nor approved bound        **BLOCKING** -- nothing to check against
an **unapproved** bound                 **BLOCKING** -- approval is what makes a
                                        bound usable, here as everywhere
======================================  ==========================================

**Domain aliases are declared, not implied.** Several entities name their anchor
for the domain rather than for the class -- ``bar_end_time``,
``publication_time``, ``snapshot_time``. :data:`DOMAIN_ANCHOR_ALIASES` is the
contract's own table (contract 7.4) as data, so an implementation reads it rather
than inferring it, and a test can prove that no declared class is left without a
mapped anchor. A temporal invariant that silently skips because an alias was
never mapped is worse than no invariant, because it reports success.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from kalpamani.data.contracts.envelope import FactAnchor
from kalpamani.data.contracts.vocabulary import AnnouncementBoundDerivation, TemporalFactClass


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainAnchorAlias:
    """One entity's domain-named field, and the class anchor it serves as."""

    entity: str
    field_name: str
    serves_as: TemporalFactClass


#: Contract 7.4, as data. Every entry is an entity whose anchor field is named
#: for its domain rather than for its temporal class.
DOMAIN_ANCHOR_ALIASES: Final[tuple[DomainAnchorAlias, ...]] = (
    DomainAnchorAlias(
        entity="source_document",
        field_name="publication_time",
        serves_as=TemporalFactClass.RETROSPECTIVE,
    ),
    DomainAnchorAlias(
        entity="analyst_revision",
        field_name="revision_time",
        serves_as=TemporalFactClass.RETROSPECTIVE,
    ),
    DomainAnchorAlias(
        entity="price_bar",
        field_name="bar_end_time",
        serves_as=TemporalFactClass.RETROSPECTIVE,
    ),
    DomainAnchorAlias(
        entity="analyst_estimate_snapshot",
        field_name="snapshot_time",
        serves_as=TemporalFactClass.SAMPLED_STATE,
    ),
    DomainAnchorAlias(
        entity="earnings_consensus_snapshot",
        field_name="snapshot_time",
        serves_as=TemporalFactClass.SAMPLED_STATE,
    ),
    DomainAnchorAlias(
        entity="earnings_schedule_estimate",
        field_name="snapshot_time",
        serves_as=TemporalFactClass.SAMPLED_STATE,
    ),
)


def alias_for(entity: str) -> DomainAnchorAlias | None:
    """The declared domain alias for ``entity``, or ``None`` if it names its anchor directly."""
    for alias in DOMAIN_ANCHOR_ALIASES:
        if alias.entity == entity:
            return alias
    return None


def retrospective_fact_anchor(anchor: FactAnchor) -> datetime | None:
    """When a retrospective fact occurred.

    A retrospective fact is observed at or after it occurs, so there is nothing
    to bound: either the observation instant is known or the row has no anchor.
    """
    if anchor.temporal_fact_class is not TemporalFactClass.RETROSPECTIVE:
        return None
    return anchor.observation_time


def announced_forward_fact_anchor(
    anchor: FactAnchor,
    approved_bound_derivations: frozenset[AnnouncementBoundDerivation],
) -> datetime | None:
    """When an announced-forward fact was announced.

    Exact announcement time, else an **approved** announcement upper bound, else
    ``None``. An unapproved bound resolves to ``None`` -- and a ``None`` here is
    what makes check 4.0A.11 fire, which is the point.
    """
    if anchor.temporal_fact_class is not TemporalFactClass.ANNOUNCED_FORWARD:
        return None
    if anchor.announcement_time is not None:
        return anchor.announcement_time
    if (
        anchor.announcement_time_upper_bound is not None
        and anchor.announcement_bound_derivation in approved_bound_derivations
    ):
        return anchor.announcement_time_upper_bound
    return None


def sampled_state_fact_anchor(anchor: FactAnchor) -> datetime | None:
    """When a sampled state was sampled."""
    if anchor.temporal_fact_class is not TemporalFactClass.SAMPLED_STATE:
        return None
    return anchor.sample_time


def resolved_fact_anchor(
    anchor: FactAnchor,
    approved_bound_derivations: frozenset[AnnouncementBoundDerivation],
) -> datetime | None:
    """Dispatch to the anchor function for ``anchor``'s declared class.

    Returns ``None`` when the declared class has no usable anchor -- which is a
    BLOCKING finding, never a reason to skip the invariant -- and also when its
    vocabulary is not exact. A plain string equal to a ``TemporalFactClass``
    member is not that member: it satisfies every equality test in the system and
    differs only where someone reads ``.value``, so treating it as typed is how an
    untyped anchor comes to look resolved.
    """
    if type(anchor.temporal_fact_class) is not TemporalFactClass or (
        type(anchor.announcement_bound_derivation) is not AnnouncementBoundDerivation
    ):
        return None
    match anchor.temporal_fact_class:
        case TemporalFactClass.RETROSPECTIVE:
            return retrospective_fact_anchor(anchor)
        case TemporalFactClass.ANNOUNCED_FORWARD:
            return announced_forward_fact_anchor(anchor, approved_bound_derivations)
        case TemporalFactClass.SAMPLED_STATE:
            return sampled_state_fact_anchor(anchor)


__all__ = [
    "DOMAIN_ANCHOR_ALIASES",
    "DomainAnchorAlias",
    "alias_for",
    "announced_forward_fact_anchor",
    "resolved_fact_anchor",
    "retrospective_fact_anchor",
    "sampled_state_fact_anchor",
]
