"""The resolution execution boundary.

``ProfileResolutionConfig`` is not audit-only configuration. It is applied here,
once, to the source rows a run directly consumes -- **before** curation, before
any artifact is built, and before anything is served:

```
source rows
    -> resolve_run_inputs        per directly consumed source dataset
    -> ResolvedRunInputs         resolved rows + evidence + a signed receipt
    -> build_gold_dataset        the only sanctioned Gold constructor
    -> publish_gold_dataset      verifies the receipt against the rows
    -> PointInTimeReader         reads only a verified publication
```

Each policy does something real, not something recorded:

``BOUND``
    writes the approved provider upper bound onto the row **before** it is
    evaluated, and then **verifies** that the bound actually resolved. A bound
    whose derivation is not approved for its dataset resolves nothing, so
    applying ``BOUND`` and moving on would admit a row on timing the run never
    established. That case refuses.
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

**The receipt is what makes this unbypassable.** A run leaves here with a
deterministic hash over its profiles, its complete canonical policy map
(reasons included), its evidence and the identity of every resolved row. Gold
cannot be built without one, and publication verifies it against the rows it is
about to write. A dataset assembled from arbitrary rows has no receipt, so
nothing can say which policy admitted them -- and "correct rows, unknown
provenance" is the shape that passes review and cannot be reproduced afterwards.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from kalpamani.data.contracts.errors import UnresolvedProviderAvailabilityError
from kalpamani.data.contracts.profiles import (
    DatasetResolutionEvidence,
    ProfileResolutionConfig,
    ResolutionReceipt,
    evidence_fingerprint,
    resolve_dataset_gap,
)
from kalpamani.data.contracts.resolution import (
    BoundApprovals,
    SourceRecord,
    resolved_provider_time,
)
from kalpamani.data.contracts.row_identity import row_fingerprint
from kalpamani.data.contracts.vocabulary import (
    DatasetGapPolicy,
    InformationOrigin,
    InformationSetProfile,
    LimitationToken,
)

#: The named check an unresolved provider gap triggers, whatever the policy.
UNRESOLVED_PROVIDER_CHECK = "4.3.2_unresolved_provider_availability"


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedRunInputs:
    """The rows a run may build from, the evidence, and the receipt binding them.

    Both mappings are deep-frozen: the evidence must still describe the rows when
    the manifest is emitted, not whatever a later caller substituted.
    """

    receipt: ResolutionReceipt
    by_dataset: Mapping[str, tuple[SourceRecord, ...]]
    evidence: tuple[DatasetResolutionEvidence, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "by_dataset", MappingProxyType(dict(sorted(self.by_dataset.items())))
        )

    @property
    def resolved_profile(self) -> InformationSetProfile:
        """The profile this run actually executed under."""
        return self.receipt.resolved_profile

    @property
    def requested_profile(self) -> InformationSetProfile:
        """What the caller asked for. Audit evidence only."""
        return self.receipt.requested_profile

    @property
    def resolution_policy_version(self) -> str:
        """Which policy chose these resolutions."""
        return self.receipt.resolution_policy_version

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


def resolved_row_fingerprint(
    by_dataset: Mapping[str, Sequence[SourceRecord]],
) -> tuple[tuple[str, ...], ...]:
    """A content-bound fingerprint over every resolved row.

    Names alone were not enough: the same source id carrying a corrected price or
    a revised availability time produced the same fingerprint, so a substituted
    row could be published as though resolution had seen it. Each identity now
    carries the row's full canonical content hash.
    """
    records: list[SourceRecord] = []
    for rows in by_dataset.values():
        records.extend(rows)
    return row_fingerprint(records)


def resolve_run_inputs(
    datasets: Mapping[str, Sequence[SourceRecord]],
    *,
    config: ProfileResolutionConfig,
    approvals: BoundApprovals,
) -> ResolvedRunInputs:
    """Apply the run's per-dataset resolution and issue a receipt.

    Raises:
        UnresolvedProviderAvailabilityError: if a dataset is consumed without an
            entry in the resolution map; if a row's ``dataset`` disagrees with the
            key it was filed under; if a row appears under two dataset groups; or
            if any row's provider timing is still unresolved after its policy ran.
    """
    missing = sorted(name for name in datasets if not config.has_entry_for(name))
    if missing:
        raise UnresolvedProviderAvailabilityError(
            f"datasets {missing} are consumed directly but absent from "
            "dataset_provider_gap_resolutions. The map is a complete inventory of direct "
            "source reads, not a list of the problematic ones."
        )
    _require_consistent_grouping(datasets)

    resolved: dict[str, tuple[SourceRecord, ...]] = {}
    evidence: list[DatasetResolutionEvidence] = []

    for name in sorted(datasets):
        outcome = resolve_dataset_gap(
            list(datasets[name]), dataset=name, config=config, approvals=approvals
        )
        resolved[name] = outcome.records
        evidence.append(outcome.evidence)

    _require_resolved(resolved, config=config, approvals=approvals)

    return ResolvedRunInputs(
        receipt=ResolutionReceipt(
            requested_profile=config.requested_profile,
            resolved_profile=config.resolved_profile,
            global_profile_resolution=config.global_profile_resolution,
            resolution_policy_version=config.resolution_policy_version,
            canonical_map=config.canonical_map(),
            evidence_fingerprint=evidence_fingerprint(evidence),
            row_fingerprint=resolved_row_fingerprint(resolved),
        ),
        by_dataset=resolved,
        evidence=tuple(evidence),
    )


def _require_consistent_grouping(datasets: Mapping[str, Sequence[SourceRecord]]) -> None:
    """Every row must belong to the dataset it was filed under, and to only one.

    A row filed under the wrong key is resolved by the wrong policy and evidenced
    against the wrong counts -- and nothing downstream would notice, because the
    counts would still reconcile.
    """
    misfiled: list[str] = []
    for name, rows in sorted(datasets.items()):
        for row in rows:
            if row.dataset != name:
                misfiled.append(f"{row.envelope.source_id!r} is {row.dataset!r} under {name!r}")
    if misfiled:
        raise UnresolvedProviderAvailabilityError(
            f"{len(misfiled)} row(s) are filed under a dataset key they do not belong to: "
            f"{misfiled[:5]}. A misfiled row is resolved by the wrong policy and counted "
            "against the wrong evidence, and the counts still reconcile."
        )

    seen: dict[int, str] = {}
    duplicated: list[str] = []
    for name, rows in sorted(datasets.items()):
        for row in rows:
            previous = seen.get(id(row))
            if previous is not None and previous != name:
                duplicated.append(f"{row.envelope.source_id!r} in {previous!r} and {name!r}")
            seen[id(row)] = name
    if duplicated:
        raise UnresolvedProviderAvailabilityError(
            f"row(s) appear in more than one dataset group: {duplicated[:5]}. One row belongs "
            "to one dataset; appearing twice would resolve it twice and count it twice."
        )


def _require_resolved(
    resolved: Mapping[str, tuple[SourceRecord, ...]],
    *,
    config: ProfileResolutionConfig,
    approvals: BoundApprovals,
) -> None:
    """Every surviving row must have resolvable provider timing. Including under BOUND.

    ``BOUND`` writes a bound; it does not guarantee the bound *resolves*. A bound
    whose derivation is not approved for its dataset resolves nothing, so a run
    that applied ``BOUND`` and moved on would serve rows on timing it never
    established -- with the policy name in the manifest making it look handled.
    """
    if config.resolved_profile is not InformationSetProfile.PROVIDER_REALISTIC_PIT:
        return
    offenders: list[str] = []
    for name, rows in sorted(resolved.items()):
        policy = config.policy_for(name)
        unresolved = sum(
            1
            for row in rows
            if row.envelope.information_origin is not InformationOrigin.SYSTEM_OBSERVED
            and resolved_provider_time(row, approvals) is None
        )
        if unresolved:
            offenders.append(f"{name} (policy {policy.value}, {unresolved} rows)")
    if offenders:
        raise UnresolvedProviderAvailabilityError(
            f"{UNRESOLVED_PROVIDER_CHECK}: {', '.join(offenders)} have no resolvable provider "
            "time under PROVIDER_REALISTIC_PIT after their policy ran. A declared BOUND whose "
            "derivation is not approved for its dataset resolves nothing, and a declared NONE "
            "over a gap resolves nothing either. Serving the rows anyway would admit them on "
            "timing the run never established."
        )


def excluded_datasets(evidence: Sequence[DatasetResolutionEvidence]) -> tuple[str, ...]:
    """Datasets whose rows were removed entirely by ``EXCLUDE``."""
    return tuple(
        sorted(
            entry.dataset
            for entry in evidence
            if entry.policy is DatasetGapPolicy.EXCLUDE and entry.excluded_rows > 0
        )
    )


__all__ = [
    "UNRESOLVED_PROVIDER_CHECK",
    "ResolvedRunInputs",
    "evidence_limitation_tokens",
    "excluded_datasets",
    "resolve_run_inputs",
    "resolved_row_fingerprint",
]
