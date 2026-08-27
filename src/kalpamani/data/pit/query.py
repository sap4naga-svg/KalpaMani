"""What a query asked, recorded by the accessor that answered it.

A result is not reproducible from its numbers. "The adjusted close for SEC-0001
over June 2019" is not one question -- it is a question per resolution, per
adjustment convention, per revision view, per information-set profile and per
``as_of`` -- and a manifest that records the answer without recording which of
those was asked describes a result nobody can re-derive.

The manifest used to take that description from the caller, in fields like
``backtest_start`` and ``definitions``. Those are a *narrative* about the run.
They can be written to say anything, they are never compared to what executed,
and a run whose narrative and execution disagree is exactly the unreproducible
result that looks reproducible.

A :class:`QuerySpec` is written by the accessor, from the arguments it actually
served, and travels with the sealed result into the inventory, the manifest and
``run_id``. Two runs that asked different questions cannot share an identity.

**The vocabulary is closed.** Both spec kinds are frozen, canonical and
exhaustive for the accessors this slice implements; a third accessor adds a third
kind rather than widening one of these into a bag of optional fields, because an
optional field is a question nobody has to answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Literal

from kalpamani.data.contracts.instants import normalize_instant
from kalpamani.data.contracts.vocabulary import (
    AdjustmentConvention,
    AdjustmentPolicy,
    BarResolution,
    InformationSetProfile,
    RevisionView,
)


class SeriesRequirement(Enum):
    """Whether a caller will accept a series shorter than the range it asked for.

    Named explicitly at every call site, like every other decision a historical
    query makes. A truncated series is indistinguishable from a complete one once
    it is a list of numbers, so whether one is acceptable is the caller's
    question to answer out loud.

    ``OPTIONAL`` relaxes **availability only**. It never relaxes the integrity of
    the data underneath: a missing bar, an off-grid bar, an undeterminable grid or
    a duplicated endpoint refuse under both, because those are defects in the
    dataset rather than facts about what a query at this ``as_of`` was entitled to
    see.
    """

    #: Every expected endpoint must survive point-in-time filtering, or refuse.
    REQUIRED = "REQUIRED"
    #: A series short by *availability* is an acceptable answer. It is labelled.
    OPTIONAL = "OPTIONAL"


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceQuerySpec:
    """Every choice that decides what a price series means."""

    kind: Literal["price_history"] = "price_history"
    security_id: str
    start: date
    end: date
    resolution: BarResolution
    #: ``RAW`` or ``ADJUSTED``. The policy and convention below are populated only
    #: for the second, because a raw series conveys neither.
    adjustment_mode: str
    adjustment_policy: AdjustmentPolicy | None
    adjustment_convention: AdjustmentConvention | None
    requirement: SeriesRequirement
    #: Canonical identity of the listing and calendar rows that produced this
    #: series' expected endpoint grid. Two runs can expect the same endpoints from
    #: different evidence -- a re-stated listing, a corrected calendar -- and
    #: without this they were the same question with the same answer.
    grid_basis_hash: str
    #: ``None`` for a raw series, and that is a fact rather than an omission: a
    #: raw series reads no revisable row, so reporting a view would say the query
    #: honoured something it never consulted.
    revision_view: RevisionView | None
    as_of: datetime
    requested_profile: InformationSetProfile
    resolved_profile: InformationSetProfile

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", normalize_instant(self.as_of))

    def identity(self) -> dict[str, object]:
        """The canonical form ``run_id`` hashes."""
        return {
            "kind": self.kind,
            "security_id": self.security_id,
            "start": self.start,
            "end": self.end,
            "resolution": self.resolution.value,
            "adjustment_mode": self.adjustment_mode,
            "adjustment_policy": (
                None if self.adjustment_policy is None else self.adjustment_policy.value
            ),
            "adjustment_convention": (
                None if self.adjustment_convention is None else self.adjustment_convention.value
            ),
            "requirement": self.requirement.value,
            "grid_basis_hash": self.grid_basis_hash,
            "revision_view": None if self.revision_view is None else self.revision_view.value,
            "as_of": self.as_of,
            "requested_profile": self.requested_profile.value,
            "resolved_profile": self.resolved_profile.value,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class UniverseQuerySpec:
    """Every choice that decides which universe snapshot was served.

    The snapshot's own identity is part of the question's answer, not merely of
    its result: two runs asking for "the universe as of 2021" against builds whose
    2021 snapshots differ asked the same question and got different answers, and
    only these two fields tell them apart.
    """

    kind: Literal["security_universe"] = "security_universe"
    as_of: datetime
    requested_profile: InformationSetProfile
    resolved_profile: InformationSetProfile
    session_date: date
    evaluation_cutoff: datetime
    snapshot_artifact_id: str
    snapshot_content_hash: str
    #: Always absent. A universe snapshot is not a revisable fact, so there is no
    #: revision to choose -- and the field exists so that saying so is a value the
    #: manifest can check rather than a convention it has to know.
    revision_view: RevisionView | None = None
    #: The rule the served snapshot was built under -- its name **and** its
    #: parameters. A caller-authored definition string described a rule the query
    #: had not necessarily applied, and a version alone does not distinguish two
    #: builds that used different thresholds under one name.
    universe_definition_version: str
    universe_definition_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", normalize_instant(self.as_of))
        object.__setattr__(self, "evaluation_cutoff", normalize_instant(self.evaluation_cutoff))

    def identity(self) -> dict[str, object]:
        """The canonical form ``run_id`` hashes."""
        return {
            "kind": self.kind,
            "as_of": self.as_of,
            "requested_profile": self.requested_profile.value,
            "resolved_profile": self.resolved_profile.value,
            "session_date": self.session_date,
            "evaluation_cutoff": self.evaluation_cutoff,
            "snapshot_artifact_id": self.snapshot_artifact_id,
            "snapshot_content_hash": self.snapshot_content_hash,
            "universe_definition_version": self.universe_definition_version,
            "universe_definition_hash": self.universe_definition_hash,
        }


#: What an accessor recorded about the question it answered.
QuerySpec = PriceQuerySpec | UniverseQuerySpec


__all__ = [
    "PriceQuerySpec",
    "QuerySpec",
    "SeriesRequirement",
    "UniverseQuerySpec",
]
