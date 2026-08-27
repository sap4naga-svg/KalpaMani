"""Deterministic information-set profile resolution.

A run names the profile it **asked for** and the profile it **got**. When a
``DOWNGRADE`` fires those differ, and every downstream artefact follows the
resolved one.

**Scope is the whole point, and an earlier revision of the plan flattened it.**

===============  ==========  =====================================================
resolution       scope       effect
===============  ==========  =====================================================
``EXCLUDE``      dataset     the dataset's unresolvable records do not participate
``BOUND``        dataset     an approved conservative upper bound stands in; the
                             exact provider time **stays null**
``DOWNGRADE``    **run**     the entire run executes under ``PUBLIC_PIT``
===============  ==========  =====================================================

A run legitimately bounds one feed and excludes another -- that is the ordinary
case. Recording one scalar resolution for the whole run made those two runs
indistinguishable in the manifest and collided in ``run_id``, so the per-dataset
map is canonical, ordered, and enters run identity **in full**. Two runs that
resolved the same query differently admit different rows and must not share an
identity.

There is no ``DECLARE``. It served a row on public timing while labelling the
result provider-realistic, which is exactly the profile mixing the contract
forbids: a rule cannot both permit and prohibit the same act.

``BOUND`` is genuinely conservative -- we cannot have been served a row before we
first saw it, so ``system_first_seen_time`` is a sound *upper bound* on provider
availability. It can only ever delay a record, never advance it. It is recorded
as a bound, leaving ``provider_available_time`` null, so a bounded row is never
mistaken for a precisely-stamped one and a backfill stays inadmissible in the
past by construction rather than by vigilance.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

from kalpamani.data.contracts.canonical import content_hash
from kalpamani.data.contracts.envelope import SourceEnvelope
from kalpamani.data.contracts.errors import ProfileResolutionError
from kalpamani.data.contracts.resolution import (
    BoundApprovals,
    PitRecord,
    SourceRecord,
    resolved_provider_time,
    resolved_public_time,
)
from kalpamani.data.contracts.vocabulary import (
    DatasetGapPolicy,
    GlobalProfileResolution,
    InformationOrigin,
    InformationSetProfile,
    ProviderBoundDerivation,
)

RecordT = TypeVar("RecordT", bound=SourceRecord)


class TimingBasis(StrEnum):
    """What governed a dataset's timing on one axis, for manifest evidence."""

    EXACT = "EXACT"
    BOUND = "BOUND"
    MIXED = "MIXED"
    NOT_APPLICABLE = "N/A"


@dataclass(frozen=True, slots=True, kw_only=True)
class DatasetGapResolution:
    """The declared policy for one dataset's unknown provider availability."""

    dataset: str
    policy: DatasetGapPolicy
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileResolutionConfig:
    """How a run resolves its requested profile. Canonical and hashable.

    Validated at construction because an ambiguous resolution is not a warning:
    two datasets with two policies under one name would make the manifest's
    per-dataset evidence unreadable.
    """

    requested_profile: InformationSetProfile
    global_profile_resolution: GlobalProfileResolution = GlobalProfileResolution.NONE
    resolution_policy_version: str
    dataset_resolutions: tuple[DatasetGapResolution, ...] = ()

    def __post_init__(self) -> None:
        names = [entry.dataset for entry in self.dataset_resolutions]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ProfileResolutionError(
                f"Datasets resolved more than once: {duplicates}. Each dataset has exactly "
                "one policy; two entries would make the manifest's per-dataset counts "
                "unreconcilable."
            )
        if not self.resolution_policy_version:
            raise ProfileResolutionError(
                "resolution_policy_version is required. Which policy chose a resolution is "
                "part of run identity, and an unnamed policy cannot be reproduced."
            )

    @property
    def resolved_profile(self) -> InformationSetProfile:
        """The profile the run actually executes under.

        A ``DOWNGRADE`` relabels the **whole run** ``PUBLIC_PIT``, before any
        filtering, anchoring or artifact construction happens.
        """
        if self.global_profile_resolution is GlobalProfileResolution.DOWNGRADE:
            return InformationSetProfile.PUBLIC_PIT
        return self.requested_profile

    def policy_for(self, dataset: str) -> DatasetGapPolicy:
        """The declared policy for ``dataset``, defaulting to ``NONE``."""
        for entry in self.dataset_resolutions:
            if entry.dataset == dataset:
                return entry.policy
        return DatasetGapPolicy.NONE

    def has_entry_for(self, dataset: str) -> bool:
        """Whether ``dataset`` appears in the map at all."""
        return any(entry.dataset == dataset for entry in self.dataset_resolutions)

    def canonical_map(self) -> tuple[tuple[str, str, str], ...]:
        """The dataset-ordered map that enters ``run_id`` **in full**, not as a summary."""
        return tuple(
            (entry.dataset, entry.policy.value, entry.reason)
            for entry in sorted(self.dataset_resolutions, key=lambda e: e.dataset)
        )

    #: There is deliberately no ``limitation_tokens()`` here. A token is a claim
    #: about what a run *did*, and a declared policy is not evidence that it did
    #: anything: ``BOUND`` on a dataset with no gaps bounds nothing, and
    #: ``EXCLUDE`` that removes no rows excluded nothing. Tokens come from
    #: :func:`kalpamani.data.curate.resolution_run.evidence_limitation_tokens`,
    #: which reads the counts.


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolutionReceipt:
    """Proof that a specific set of rows went through a specific resolution.

    A build is publishable only if it can say **which policy admitted its rows**.
    A dataset assembled from arbitrary rows cannot, however correct those rows
    happen to be -- and "correct rows, unknown provenance" is precisely the shape
    that looks fine in review and cannot be reproduced afterwards.

    The receipt hash covers the requested and resolved profiles, the global
    resolution, the **complete canonical policy map including each reason**, the
    policy version, the per-dataset evidence, and the identity of every resolved
    row. Reasons are in deliberately: two runs that bounded the same dataset for
    different stated reasons resolved it differently, and a hash blind to that
    would call them the same run.
    """

    requested_profile: InformationSetProfile
    resolved_profile: InformationSetProfile
    global_profile_resolution: GlobalProfileResolution
    resolution_policy_version: str
    canonical_map: tuple[tuple[str, str, str], ...]
    evidence_fingerprint: tuple[tuple[str, ...], ...]
    row_identity_fingerprint: tuple[tuple[str, str], ...]

    @property
    def receipt_hash(self) -> str:
        """Derived, not generated. Same resolution, same receipt."""
        return content_hash(
            {
                "requested_profile": self.requested_profile.value,
                "resolved_profile": self.resolved_profile.value,
                "global_profile_resolution": self.global_profile_resolution.value,
                "resolution_policy_version": self.resolution_policy_version,
                "canonical_map": [list(entry) for entry in self.canonical_map],
                "evidence_fingerprint": [list(entry) for entry in self.evidence_fingerprint],
                "row_identity_fingerprint": [
                    list(entry) for entry in self.row_identity_fingerprint
                ],
            }
        )

    def agrees_with(self, config: ProfileResolutionConfig) -> bool:
        """Whether this receipt was produced by exactly ``config``.

        Compares the **complete** canonical map, reasons included -- not policy
        names and a version string. An entry present in one and absent in the
        other is a disagreement, in either direction.
        """
        return (
            self.requested_profile is config.requested_profile
            and self.resolved_profile is config.resolved_profile
            and self.global_profile_resolution is config.global_profile_resolution
            and self.resolution_policy_version == config.resolution_policy_version
            and self.canonical_map == config.canonical_map()
        )


def evidence_fingerprint(
    evidence: Sequence[DatasetResolutionEvidence],
) -> tuple[tuple[str, ...], ...]:
    """A canonical rendering of per-dataset evidence, for the receipt hash."""
    return tuple(
        sorted(
            (
                entry.dataset,
                entry.policy.value,
                str(entry.rows_considered),
                str(entry.public_rows_applicable),
                entry.public_basis.value,
                str(entry.public_exact_rows),
                str(entry.public_bounded_rows),
                str(entry.public_excluded_rows),
                str(entry.public_unresolved_rows),
                str(entry.provider_rows_applicable),
                entry.provider_basis.value,
                str(entry.provider_exact_rows),
                str(entry.provider_bounded_rows),
                str(entry.provider_excluded_rows),
                str(entry.provider_unresolved_rows),
                str(entry.excluded_rows),
                entry.reason,
            )
            for entry in evidence
        )
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class DatasetResolutionEvidence:
    """Per-dataset, per-axis counts. The axes reconcile **independently**.

    A dataset may be bounded on one axis and exact on the other, so one shared
    set of counts could not describe it.
    """

    dataset: str
    policy: DatasetGapPolicy
    rows_considered: int
    #: How many of ``rows_considered`` have a public axis at all. A dataset
    #: holding both authoritative-public and provider-derived rows has a
    #: different denominator per axis, and one shared count could not describe
    #: it: the axes would never reconcile, or would reconcile by accident.
    public_rows_applicable: int
    public_basis: TimingBasis
    public_exact_rows: int
    public_bounded_rows: int
    public_excluded_rows: int
    #: Applicable to the axis, but neither exact, bounded nor excluded. Under
    #: PUBLIC_PIT a provider gap is simply not required, so these are ordinary;
    #: under PROVIDER_REALISTIC_PIT the resolution boundary has already refused
    #: them. Counting them is what lets the axis reconcile honestly rather than
    #: by leaving rows out of the arithmetic.
    public_unresolved_rows: int
    provider_rows_applicable: int
    provider_basis: TimingBasis
    provider_exact_rows: int
    provider_bounded_rows: int
    provider_excluded_rows: int
    provider_unresolved_rows: int
    excluded_rows: int
    reason: str

    def public_axis_reconciles(self) -> bool:
        """``exact + bounded + excluded + unresolved == applicable``, public axis."""
        total = (
            self.public_exact_rows
            + self.public_bounded_rows
            + self.public_excluded_rows
            + self.public_unresolved_rows
        )
        return total == self.public_rows_applicable

    def provider_axis_reconciles(self) -> bool:
        """``exact + bounded + excluded + unresolved == applicable``, provider axis."""
        total = (
            self.provider_exact_rows
            + self.provider_bounded_rows
            + self.provider_excluded_rows
            + self.provider_unresolved_rows
        )
        return total == self.provider_rows_applicable


@dataclass(frozen=True, slots=True, kw_only=True)
class GapResolutionOutcome(Generic[RecordT]):
    """The records a resolution admits, and the evidence for what it did."""

    records: tuple[RecordT, ...]
    evidence: DatasetResolutionEvidence


def bound_provider_time(envelope: SourceEnvelope) -> SourceEnvelope:
    """Apply ``BOUND`` to one source envelope.

    Sets ``provider_available_upper_bound`` from ``system_first_seen_time`` with
    ``FIRST_SEEN_UPPER_BOUND``, and **leaves the exact field null**. It claims
    only that the provider offered the row no later than then -- which is true,
    and weaker than claiming the provider published at that instant.

    Raises:
        ProfileResolutionError: for a ``SYSTEM_OBSERVED`` row. There is no
            provider, so bounding a provider time would invent one.
    """
    if envelope.information_origin is InformationOrigin.SYSTEM_OBSERVED:
        raise ProfileResolutionError(
            "Refusing to BOUND a SYSTEM_OBSERVED record. BOUND bounds a provider time that "
            "exists but is unstated; it does not manufacture one for a record that has no "
            "provider at all."
        )
    if envelope.provider_available_time is not None:
        return envelope
    return SourceEnvelope(
        information_origin=envelope.information_origin,
        public_available_time=envelope.public_available_time,
        public_available_upper_bound=envelope.public_available_upper_bound,
        public_time_derivation=envelope.public_time_derivation,
        public_bound_derivation=envelope.public_bound_derivation,
        provider_available_time=None,
        provider_available_upper_bound=envelope.system_first_seen_time,
        provider_time_derivation=envelope.provider_time_derivation,
        provider_bound_derivation=ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND,
        system_first_seen_time=envelope.system_first_seen_time,
        anchor=envelope.anchor,
        revision_sequence=envelope.revision_sequence,
        valid_from=envelope.valid_from,
        valid_to=envelope.valid_to,
        source_id=envelope.source_id,
        vendor_record_id=envelope.vendor_record_id,
        ingestion_time=envelope.ingestion_time,
        dataset_version=envelope.dataset_version,
        quality_status=envelope.quality_status,
        provider=envelope.provider,
    )


def resolve_dataset_gap(
    records: Sequence[RecordT],
    *,
    dataset: str,
    config: ProfileResolutionConfig,
    approvals: BoundApprovals,
) -> GapResolutionOutcome[RecordT]:
    """Apply ``dataset``'s declared policy to ``records`` and record the evidence.

    Only ``PROVIDER_REALISTIC_PIT`` has a provider gap to resolve. Under the
    other two resolved profiles the policy is inert and the evidence says so --
    which is still recorded, because a complete inventory of direct source reads
    is what makes the map checkable.
    """
    policy = config.policy_for(dataset)
    resolved_profile = config.resolved_profile
    kept: list[RecordT] = []
    excluded: list[RecordT] = []

    for record in records:
        envelope = record.envelope
        needs_resolution = (
            resolved_profile is InformationSetProfile.PROVIDER_REALISTIC_PIT
            and resolved_provider_time(record, approvals) is None
            and envelope.information_origin is not InformationOrigin.SYSTEM_OBSERVED
        )
        if not needs_resolution:
            kept.append(record)
            continue
        match policy:
            case DatasetGapPolicy.EXCLUDE:
                excluded.append(record)
            case DatasetGapPolicy.BOUND:
                kept.append(record.with_envelope(bound_provider_time(envelope)))
            case DatasetGapPolicy.NONE:
                # Unresolved and undeclared. Kept so the resolution boundary can
                # refuse it by name, rather than disappearing here without
                # evidence.
                kept.append(record)

    return GapResolutionOutcome(
        records=tuple(kept),
        evidence=_evidence(
            dataset=dataset,
            policy=policy,
            considered=records,
            kept=kept,
            excluded=excluded,
            approvals=approvals,
            reason=_reason_for(config, dataset),
        ),
    )


def _reason_for(config: ProfileResolutionConfig, dataset: str) -> str:
    for entry in config.dataset_resolutions:
        if entry.dataset == dataset:
            return entry.reason
    return "no provider-timing gap declared for this dataset"


def _evidence(
    *,
    dataset: str,
    policy: DatasetGapPolicy,
    considered: Sequence[PitRecord],
    kept: Sequence[PitRecord],
    excluded: Sequence[PitRecord],
    approvals: BoundApprovals,
    reason: str,
) -> DatasetResolutionEvidence:
    """Count each axis against its own applicable rows.

    A dataset holding both authoritative-public and provider-derived rows has a
    different denominator per axis. One shared ``rows_considered`` would make the
    axes fail to reconcile on any mixed dataset -- or, worse, reconcile by
    coincidence on a dataset where they should not.
    """
    public_applicable = sum(1 for row in considered if _has_public_axis(row))
    provider_applicable = sum(1 for row in considered if _has_provider_axis(row))
    public_excluded = sum(1 for row in excluded if _has_public_axis(row))
    provider_excluded = sum(1 for row in excluded if _has_provider_axis(row))

    public_exact = public_bounded = 0
    provider_exact = provider_bounded = 0
    for record in kept:
        envelope = record.envelope
        if not isinstance(envelope, SourceEnvelope):
            continue
        if _has_public_axis(record):
            if envelope.public_available_time is not None:
                public_exact += 1
            elif resolved_public_time(record, approvals) is not None:
                public_bounded += 1
        if _has_provider_axis(record):
            if envelope.provider_available_time is not None:
                provider_exact += 1
            elif resolved_provider_time(record, approvals) is not None:
                provider_bounded += 1

    return DatasetResolutionEvidence(
        dataset=dataset,
        policy=policy,
        rows_considered=len(considered),
        public_rows_applicable=public_applicable,
        public_basis=_basis(bool(public_applicable), public_exact, public_bounded),
        public_exact_rows=public_exact,
        public_bounded_rows=public_bounded,
        public_excluded_rows=public_excluded,
        public_unresolved_rows=(
            public_applicable - public_exact - public_bounded - public_excluded
        ),
        provider_rows_applicable=provider_applicable,
        provider_basis=_basis(bool(provider_applicable), provider_exact, provider_bounded),
        provider_exact_rows=provider_exact,
        provider_bounded_rows=provider_bounded,
        provider_excluded_rows=provider_excluded,
        provider_unresolved_rows=(
            provider_applicable - provider_exact - provider_bounded - provider_excluded
        ),
        excluded_rows=len(excluded),
        reason=reason,
    )


def _has_public_axis(record: PitRecord) -> bool:
    envelope = record.envelope
    if not isinstance(envelope, SourceEnvelope):
        return False
    return envelope.information_origin is InformationOrigin.AUTHORITATIVE_PUBLIC


def _has_provider_axis(record: PitRecord) -> bool:
    envelope = record.envelope
    if not isinstance(envelope, SourceEnvelope):
        return False
    return envelope.information_origin is not InformationOrigin.SYSTEM_OBSERVED


def _basis(applicable: bool, exact: int, bounded: int) -> TimingBasis:
    if not applicable:
        return TimingBasis.NOT_APPLICABLE
    if exact and bounded:
        return TimingBasis.MIXED
    if bounded:
        return TimingBasis.BOUND
    return TimingBasis.EXACT


__all__ = [
    "DatasetGapResolution",
    "DatasetResolutionEvidence",
    "GapResolutionOutcome",
    "ProfileResolutionConfig",
    "ResolutionReceipt",
    "TimingBasis",
    "bound_provider_time",
    "evidence_fingerprint",
    "resolve_dataset_gap",
]
