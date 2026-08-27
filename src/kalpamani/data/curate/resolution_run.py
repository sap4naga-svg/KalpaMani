"""The resolution execution boundary.

``ProfileResolutionConfig`` is not audit-only configuration. It is applied here,
once, to the source rows a run directly consumes -- **before** curation, before
any artifact is built, and before anything is served:

```
source rows
    -> resolve_run_inputs        per directly consumed source dataset
    -> resolved rows + evidence  persisted with the build
    -> Gold build                consumes only the resolved rows
    -> PointInTimeReader         verifies the persisted resolution against its own config
```

Each policy does something real, not something recorded:

``BOUND``
    actually writes the approved provider upper bound onto the row, **before** it
    is evaluated. A row bounded after evaluation would have been admitted on
    timing it did not have.
``EXCLUDE``
    actually removes the rows and records a positive excluded count. A declared
    exclusion with zero rows removed is a claim with nothing behind it.
``NONE`` **with an unresolved provider time**
    is not a silent pass-through. The rows stay and the run **refuses by name**
    with :class:`UnresolvedProviderAvailabilityError`, carrying check
    ``4.3.2_unresolved_provider_availability``.
``DOWNGRADE``
    is global and has already changed ``resolved_profile`` before any of the
    above runs, so the whole run is public-PIT from the first filter onward.

There is deliberately no path that skips this step and still yields a valid
result: the Gold build takes :class:`ResolvedRunInputs`, not raw rows, and the
reader refuses a dataset whose persisted resolution disagrees with its config.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from kalpamani.data.contracts.errors import UnresolvedProviderAvailabilityError
from kalpamani.data.contracts.profiles import (
    DatasetResolutionEvidence,
    ProfileResolutionConfig,
    resolve_dataset_gap,
)
from kalpamani.data.contracts.resolution import (
    BoundApprovals,
    SourceRecord,
    resolved_provider_time,
)
from kalpamani.data.contracts.vocabulary import (
    DatasetGapPolicy,
    InformationOrigin,
    InformationSetProfile,
    LimitationToken,
)

#: The named check a `NONE` policy over unresolved provider timing triggers.
UNRESOLVED_PROVIDER_CHECK = "4.3.2_unresolved_provider_availability"


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedRunInputs:
    """The rows a run may build from, and the evidence for what resolution did.

    Both mappings are deep-frozen: the evidence must still describe the rows when
    the manifest is emitted, not whatever a later caller substituted.
    """

    resolved_profile: InformationSetProfile
    requested_profile: InformationSetProfile
    resolution_policy_version: str
    by_dataset: Mapping[str, tuple[SourceRecord, ...]]
    evidence: tuple[DatasetResolutionEvidence, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "by_dataset", MappingProxyType(dict(sorted(self.by_dataset.items())))
        )

    def rows(self, dataset: str) -> tuple[SourceRecord, ...]:
        """The resolved rows for one dataset.

        Raises:
            KeyError: if the dataset was not resolved. A caller reaching for rows
                that never went through resolution is the failure mode this whole
                module exists to prevent, so it is loud rather than empty.
        """
        if dataset not in self.by_dataset:
            raise KeyError(
                f"dataset {dataset!r} did not go through resolution. Every directly consumed "
                "source dataset is resolved before curation; reaching around that step would "
                "admit rows on timing the run never established."
            )
        return self.by_dataset[dataset]

    def evidence_for(self, dataset: str) -> DatasetResolutionEvidence:
        """The recorded evidence for one dataset."""
        for entry in self.evidence:
            if entry.dataset == dataset:
                return entry
        raise KeyError(dataset)

    def limitation_tokens(self) -> tuple[LimitationToken, ...]:
        """Tokens this run's **evidence** obliges, not tokens its config declared."""
        return evidence_limitation_tokens(
            self.evidence,
            downgraded=self.resolved_profile is not self.requested_profile,
        )


def evidence_limitation_tokens(
    evidence: Sequence[DatasetResolutionEvidence],
    *,
    downgraded: bool,
    origin_excluded_rows: int = 0,
) -> tuple[LimitationToken, ...]:
    """Derive limitation tokens from positive evidence alone.

    A token is a claim about what happened in this run. Emitting one because a
    policy was *declared* -- rather than because rows were actually bounded or
    excluded -- puts a claim in the manifest with nothing behind it, which is
    exactly what the evidence rules exist to prevent.
    """
    tokens: list[LimitationToken] = []
    bounded_provider = any(entry.provider_bounded_rows > 0 for entry in evidence)
    bounded_public = any(entry.public_bounded_rows > 0 for entry in evidence)
    excluded = any(entry.excluded_rows > 0 for entry in evidence)

    if excluded or bounded_provider:
        tokens.append(LimitationToken.PROVIDER_AVAILABILITY_UNKNOWN)
    if bounded_provider:
        tokens.append(LimitationToken.PROVIDER_TIME_BOUNDED)
    if bounded_public:
        tokens.append(LimitationToken.PUBLIC_TIME_BOUNDED)
    if downgraded:
        tokens.append(LimitationToken.PROFILE_DOWNGRADED_TO_PUBLIC)
    if origin_excluded_rows > 0:
        tokens.append(LimitationToken.ORIGIN_INELIGIBLE_ROWS_EXCLUDED)
    return tuple(tokens)


def resolve_run_inputs(
    datasets: Mapping[str, Sequence[SourceRecord]],
    *,
    config: ProfileResolutionConfig,
    approvals: BoundApprovals,
) -> ResolvedRunInputs:
    """Apply the run's per-dataset resolution to every directly consumed dataset.

    Raises:
        ProfileResolutionError: if a dataset is consumed without an entry in the
            resolution map. The map is a complete inventory of direct source
            reads, not a list of the problematic ones.
        UnresolvedProviderAvailabilityError: if a dataset's policy is ``NONE``
            while rows in it have no resolvable provider time under
            ``PROVIDER_REALISTIC_PIT``.
    """
    missing = sorted(name for name in datasets if not config.has_entry_for(name))
    if missing:
        raise UnresolvedProviderAvailabilityError(
            f"datasets {missing} are consumed directly but absent from "
            "dataset_provider_gap_resolutions. The map is a complete inventory of direct "
            "source reads, not a list of the problematic ones."
        )

    resolved: dict[str, tuple[SourceRecord, ...]] = {}
    evidence: list[DatasetResolutionEvidence] = []

    for name in sorted(datasets):
        outcome = resolve_dataset_gap(
            list(datasets[name]), dataset=name, config=config, approvals=approvals
        )
        resolved[name] = outcome.records
        evidence.append(outcome.evidence)

    _refuse_unresolved(resolved, config=config, approvals=approvals)

    return ResolvedRunInputs(
        resolved_profile=config.resolved_profile,
        requested_profile=config.requested_profile,
        resolution_policy_version=config.resolution_policy_version,
        by_dataset=resolved,
        evidence=tuple(evidence),
    )


def _refuse_unresolved(
    resolved: Mapping[str, tuple[SourceRecord, ...]],
    *,
    config: ProfileResolutionConfig,
    approvals: BoundApprovals,
) -> None:
    if config.resolved_profile is not InformationSetProfile.PROVIDER_REALISTIC_PIT:
        return
    offenders: list[str] = []
    for name, rows in sorted(resolved.items()):
        if config.policy_for(name) is not DatasetGapPolicy.NONE:
            continue
        unresolved = sum(
            1
            for row in rows
            if row.envelope.information_origin is not InformationOrigin.SYSTEM_OBSERVED
            and resolved_provider_time(row, approvals) is None
        )
        if unresolved:
            offenders.append(f"{name} ({unresolved} rows)")
    if offenders:
        raise UnresolvedProviderAvailabilityError(
            f"{UNRESOLVED_PROVIDER_CHECK}: {', '.join(offenders)} have no resolvable provider "
            "time under PROVIDER_REALISTIC_PIT while their declared policy is NONE. A gap "
            "that is neither bounded, excluded nor downgraded is not resolved, and serving "
            "the rows anyway would admit them on timing the run never established."
        )


__all__ = [
    "UNRESOLVED_PROVIDER_CHECK",
    "ResolvedRunInputs",
    "evidence_limitation_tokens",
    "resolve_run_inputs",
]
