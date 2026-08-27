"""The research manifest, and the deterministic ``run_id`` derived from it.

> **No result is reproducible merely because the Python code is
> version-controlled.**

A commit SHA pins the *transformation*. It says nothing about the *inputs*, and
in a point-in-time system the inputs are the part that moves: vendors backfill,
restatements arrive, universes get rebuilt, lag policies get tuned. A backtest
rerun six months later against "the same code" will read a different world and
produce a different number, and without a manifest there is no way to tell that
from a genuine regression.

``run_id`` is **derived, not generated** -- a hash over the load-bearing inputs.
No ``uuid4()``, no timestamps in an identity. A derived id means two runs claiming
to be the same run can be checked against each other rather than merely asserted
to match, and it means any change to what the run actually read produces a
different id.

**Refusal, not annotation.** Emission fails on a dirty tree, a missing profile, an
open BLOCKING issue, an unreconciled dataset, an unapproved bound, a coverage
breach, a hash mismatch or a token without evidence. That is the same trade
ADR-0004 made throughout: an unreproducible result that *looks* reproducible is
the unrecoverable one, because it gets cited later by someone who was not in the
room.

**Nothing load-bearing arrives through a side channel.** ``emit_manifest`` used
to take ``unapproved_bounds_relied_upon`` and ``hash_mismatches`` as arguments,
which meant the only way a manifest learned that a bound was unapproved or a hash
failed was for the caller to volunteer it -- the one party with a reason to stay
quiet was the one being asked. Both now come from
:class:`~kalpamani.data.pit.execution.ExecutionEvidence`, produced by the query
path while it executed.

**Every limitation token needs positive evidence in the same manifest.** A token
is a claim about this run, and a reader must be able to find what it refers to
without leaving the file. A domain that was never populated is not a domain whose
rows were excluded.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.errors import ManifestRefusedError
from kalpamani.data.contracts.instants import is_canonical_instant, normalize_instant
from kalpamani.data.contracts.profiles import (
    DatasetResolutionEvidence,
    ProfileResolutionConfig,
)
from kalpamani.data.contracts.vocabulary import (
    CoverageScope,
    InformationSetProfile,
    LimitationToken,
    RevisionView,
)

if TYPE_CHECKING:  # pragma: no cover - only the type checker needs this
    from kalpamani.data.pit.execution import ExecutionEvidence

#: The manifest schema this module writes and reads.
#:
#: Deliberately still 4. The ``run_id`` inputs grew this round -- the inventory
#: now carries the unapproved bounds and hash mismatches the run recorded -- and a
#: version that does not move when the identity inputs move is a fair criticism.
#: But 4 is the version an **accepted planning document** defines, and changing it
#: is a change to that document rather than to this module. It is recorded as an
#: acceptance limitation instead of decided here.
MANIFEST_VERSION = 4


@dataclass(frozen=True, slots=True, kw_only=True)
class CodeProvenance:
    """What produced the result, and whether anyone else could reproduce it."""

    commit_sha: str
    working_tree_clean: bool
    config_version: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CoverageEvidence:
    """Proof that a required input's coverage contract passed.

    **The partition minimum decides, not an aggregate.** A ``PER_SECURITY`` input
    at 97% overall with securities below threshold has failed; averaging them away
    is precisely the move the scope exists to prevent. ``WHOLE_DOMAIN`` takes a
    row-count contract instead, because there is no natural denominator for "the
    whole domain" and inventing one makes the threshold uninterpretable.
    """

    domain: str
    coverage_scope: CoverageScope
    min_coverage_fraction: Decimal | None = None
    minimum_observed_partition_coverage: Decimal | None = None
    total_partitions: int | None = None
    failing_partitions: int | None = None
    min_rows: int | None = None
    observed_rows: int | None = None

    def evidence_is_complete(self) -> bool:
        """Whether the fields this scope requires are all present."""
        if self.coverage_scope is CoverageScope.WHOLE_DOMAIN:
            return self.min_rows is not None and self.observed_rows is not None
        return (
            self.min_coverage_fraction is not None
            and self.minimum_observed_partition_coverage is not None
            and self.total_partitions is not None
            and self.failing_partitions is not None
        )

    def uses_the_wrong_evidence(self) -> bool:
        """Whether a scope was evidenced with the other scope's fields."""
        if self.coverage_scope is CoverageScope.WHOLE_DOMAIN:
            return self.min_coverage_fraction is not None
        return self.min_rows is not None

    def passes(self) -> bool:
        """Whether the contract is met. Incomplete evidence never passes."""
        if not self.evidence_is_complete() or self.uses_the_wrong_evidence():
            return False
        if self.coverage_scope is CoverageScope.WHOLE_DOMAIN:
            assert self.observed_rows is not None and self.min_rows is not None
            return self.observed_rows >= self.min_rows
        assert self.failing_partitions is not None
        assert self.minimum_observed_partition_coverage is not None
        assert self.min_coverage_fraction is not None
        return (
            self.failing_partitions == 0
            and self.minimum_observed_partition_coverage >= self.min_coverage_fraction
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class UnavailableDomain:
    """A domain that was never populated -- which is not a domain whose rows were excluded."""

    domain: str
    reason: str
    limitation: LimitationToken


@dataclass(frozen=True, slots=True, kw_only=True)
class OriginExclusion:
    """Rows dropped because their origin is ineligible under the resolved profile."""

    dataset: str
    information_origin: str
    rows: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsumedArtifact:
    """A derived artifact this run read, pinned well enough to reproduce.

    Dataset versions alone are not sufficient. Under ``FORWARD_SYSTEM`` an
    artifact's availability depends on when it was *first* built, so two runs over
    identical dataset versions can legitimately differ -- and a ``run_id`` blind to
    first-built history would call them the same run and make an irreproducible
    result look reproducible.
    """

    artifact_id: str
    entity: str
    output_validity: str
    derivation_spec_version: str
    artifact_content_hash: str
    artifact_first_built_time: datetime
    lineage_selectors: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class DatasetReference:
    """A dataset version the run read, with the hash that pins its contents."""

    dataset_version: str
    layer: str
    content_hash: str
    #: The publication manifest hash. Two builds with the same version string but
    #: different coverage, profile or policy evidence are different datasets, and
    #: only this tells them apart.
    publication_manifest_hash: str
    resolved_profile: InformationSetProfile | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class QualitySummary:
    """What the checks found, and what they did not run.

    ``checks_not_run`` is not optional politeness. A check that cannot run is
    declared, never quietly skipped: a check that silently covered less than it
    claims is worse than no check, because it converts an unknown into a false
    assurance.
    """

    blocking_issues_open: int
    warnings_open: int
    checks_not_run: tuple[str, ...] = ()
    #: Identity of the report these counts came from. Cross-checked against the
    #: inventory, so a summary cannot describe one report while the run read
    #: another.
    quality_report_hash: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class InputInventory:
    """What a run actually read, recorded by the query path rather than declared.

    The shape this replaces took ``directly_read_datasets=[]`` and friends as
    arguments, which meant a caller obtained a valid manifest by passing empty
    lists -- the evidence rules were enforced against whatever the caller chose to
    admit. An inventory the run *produces* cannot be shortened by omission: if the
    query path did not record a dataset, that is a bug in the query path, not a
    caller's prerogative.

    Build one with :meth:`from_execution`. Constructing it field by field is still
    possible in tests, but the production route runs through the verified query
    path, which is the only thing that knows what was read.

    Every collection is a tuple and every mapping is frozen, because ``run_id``
    hashes them and an identity that can change after it is taken is not an
    identity.
    """

    direct_source_datasets: tuple[str, ...] = ()
    dataset_manifest_hashes: Mapping[str, str] = field(default_factory=dict)
    consumed_artifact_ids: tuple[str, ...] = ()
    revisable_datasets_consumed: tuple[str, ...] = ()
    bounds_relied_upon: tuple[str, ...] = ()
    #: Bounds the run leant on whose derivation was not approved for their
    #: dataset. Recorded by execution; refusing on it is not optional.
    unapproved_bounds_relied_upon: tuple[str, ...] = ()
    #: Content hashes that failed to verify while the run executed.
    hash_mismatches: tuple[str, ...] = ()
    origin_exclusion_rows: int = 0
    quality_report_hash: str = ""
    result_artifact_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dataset_manifest_hashes",
            MappingProxyType(dict(sorted(self.dataset_manifest_hashes.items()))),
        )
        object.__setattr__(
            self, "direct_source_datasets", tuple(sorted(set(self.direct_source_datasets)))
        )
        object.__setattr__(
            self, "consumed_artifact_ids", tuple(sorted(set(self.consumed_artifact_ids)))
        )
        object.__setattr__(
            self,
            "revisable_datasets_consumed",
            tuple(sorted(set(self.revisable_datasets_consumed))),
        )
        object.__setattr__(self, "bounds_relied_upon", tuple(sorted(set(self.bounds_relied_upon))))
        object.__setattr__(
            self,
            "unapproved_bounds_relied_upon",
            tuple(sorted(set(self.unapproved_bounds_relied_upon))),
        )
        object.__setattr__(self, "hash_mismatches", tuple(sorted(set(self.hash_mismatches))))

    @classmethod
    def from_execution(
        cls,
        evidence: ExecutionEvidence,
        *,
        result_bytes: bytes,
    ) -> InputInventory:
        """Build an inventory from what a run recorded while it executed.

        ``result_artifact_hash`` is the SHA-256 of the **exact result bytes**. An
        earlier version decoded them to text first, which meant two byte strings
        that decode alike shared an identity -- and any payload that is not valid
        UTF-8 had no honest hash at all.
        """
        return cls(
            direct_source_datasets=evidence.direct_source_datasets,
            dataset_manifest_hashes=dict(evidence.dataset_manifest_hashes),
            consumed_artifact_ids=evidence.consumed_artifact_ids,
            revisable_datasets_consumed=evidence.revisable_datasets_consumed,
            bounds_relied_upon=evidence.bounds_relied_upon,
            unapproved_bounds_relied_upon=evidence.unapproved_bounds_relied_upon,
            hash_mismatches=evidence.hash_mismatches,
            origin_exclusion_rows=evidence.origin_exclusion_rows,
            quality_report_hash=evidence.quality_report_hash,
            result_artifact_hash=sha256_hex(result_bytes),
        )

    def identity(self) -> dict[str, object]:
        """The inventory as ``run_id`` inputs. Canonical and complete."""
        return {
            "direct_source_datasets": list(self.direct_source_datasets),
            "dataset_manifest_hashes": dict(self.dataset_manifest_hashes),
            "consumed_artifact_ids": list(self.consumed_artifact_ids),
            "revisable_datasets_consumed": list(self.revisable_datasets_consumed),
            "bounds_relied_upon": list(self.bounds_relied_upon),
            "unapproved_bounds_relied_upon": list(self.unapproved_bounds_relied_upon),
            "hash_mismatches": list(self.hash_mismatches),
            "origin_exclusion_rows": self.origin_exclusion_rows,
            "quality_report_hash": self.quality_report_hash,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchManifest:
    """Everything needed to regenerate a result, or to fail loudly trying."""

    manifest_version: int = MANIFEST_VERSION
    code: CodeProvenance
    as_of_cutoff: datetime
    backtest_start: date | None = None
    backtest_end: date | None = None
    profile_resolution: ProfileResolutionConfig
    revision_view: RevisionView | None
    dataset_resolution_evidence: tuple[DatasetResolutionEvidence, ...] = ()
    origin_exclusions: tuple[OriginExclusion, ...] = ()
    required_inputs: tuple[CoverageEvidence, ...] = ()
    optional_inputs: tuple[CoverageEvidence, ...] = ()
    unavailable_domains: tuple[UnavailableDomain, ...] = ()
    consumed_artifacts: tuple[ConsumedArtifact, ...] = ()
    datasets: tuple[DatasetReference, ...] = ()
    definitions: Mapping[str, str] = field(default_factory=dict)
    limitations: tuple[LimitationToken, ...] = ()
    quality: QualitySummary
    #: What the run actually read. Produced by the query path, not declared.
    inputs: InputInventory
    random_seed: int | None = None
    result_artifact_hash: str = ""

    def __post_init__(self) -> None:
        # Deep-freeze and canonicalise. `run_id` is a hash over these values, so
        # a mapping that can be mutated after construction would let an id stop
        # describing the manifest that carries it. Making that structurally
        # impossible is worth more than checking for it.
        object.__setattr__(
            self, "definitions", MappingProxyType(dict(sorted(self.definitions.items())))
        )
        object.__setattr__(self, "as_of_cutoff", normalize_instant(self.as_of_cutoff))

    @property
    def requested_profile(self) -> InformationSetProfile:
        """What the caller asked for. Audit evidence only."""
        return self.profile_resolution.requested_profile

    @property
    def resolved_profile(self) -> InformationSetProfile:
        """What the run actually executed under. Everything downstream follows this."""
        return self.profile_resolution.resolved_profile

    def run_id_inputs(self) -> dict[str, object]:
        """The load-bearing inputs ``run_id`` hashes.

        Deliberately excludes wall-clock execution timestamps. Hashing when a run
        happened into its logical identity would make every re-run a different
        run, which is the opposite of what an identity is for.
        """
        return {
            "manifest_version": self.manifest_version,
            "code_commit_sha": self.code.commit_sha,
            "config_version": self.code.config_version,
            "as_of_cutoff": self.as_of_cutoff,
            "backtest_start": self.backtest_start,
            "backtest_end": self.backtest_end,
            "requested_profile": self.requested_profile.value,
            "resolved_profile": self.resolved_profile.value,
            "global_profile_resolution": (self.profile_resolution.global_profile_resolution.value),
            "resolution_policy_version": self.profile_resolution.resolution_policy_version,
            "dataset_provider_gap_resolutions": list(self.profile_resolution.canonical_map()),
            "revision_view": None if self.revision_view is None else self.revision_view.value,
            "datasets": sorted(
                [
                    d.dataset_version,
                    d.layer,
                    "" if d.resolved_profile is None else d.resolved_profile.value,
                    d.content_hash,
                    d.publication_manifest_hash,
                ]
                for d in self.datasets
            ),
            "inputs": self.inputs.identity(),
            "consumed_artifacts": sorted(
                _artifact_identity(artifact, self.resolved_profile)
                for artifact in self.consumed_artifacts
            ),
            "definitions": dict(sorted(self.definitions.items())),
            "random_seed": self.random_seed,
        }

    @property
    def run_id(self) -> str:
        """Derived, not generated. Same inputs, same id."""
        return "rs-" + sha256_hex(canonical_bytes(self.run_id_inputs()))[:16]


def _artifact_identity(
    artifact: ConsumedArtifact,
    resolved_profile: InformationSetProfile,
) -> list[object]:
    identity: list[object] = [
        artifact.artifact_id,
        artifact.artifact_content_hash,
        artifact.derivation_spec_version,
        [list(selector) for selector in artifact.lineage_selectors],
    ]
    if resolved_profile is InformationSetProfile.FORWARD_SYSTEM:
        identity.append(artifact.artifact_first_built_time.isoformat())
    return identity


#: Which evidence each limitation token requires in the same manifest.
_TOKEN_EVIDENCE: dict[LimitationToken, str] = {
    LimitationToken.ORIGIN_INELIGIBLE_ROWS_EXCLUDED: "an origin_exclusions entry with rows > 0",
    LimitationToken.PROVIDER_AVAILABILITY_UNKNOWN: "excluded_rows > 0 or provider_bounded_rows > 0",
    LimitationToken.PROVIDER_TIME_BOUNDED: "provider_bounded_rows > 0 somewhere",
    LimitationToken.PUBLIC_TIME_BOUNDED: "public_bounded_rows > 0 somewhere",
    LimitationToken.PROFILE_DOWNGRADED_TO_PUBLIC: "global_profile_resolution DOWNGRADE",
    LimitationToken.NON_PIT_RESTATED_VIEW: "revision_view LATEST_RESTATED",
}


def emit_manifest(manifest: ResearchManifest, *, result_bytes: bytes) -> ResearchManifest:
    """Validate every precondition and return the manifest, or refuse.

    Returning the manifest rather than a bare ``None`` keeps the call site honest:
    a caller either has a validated manifest or has an exception, never a
    half-checked object it might publish anyway.

    Raises:
        ManifestRefusedError: naming every precondition that failed. All of them,
            not the first -- a reader fixing one failure should not have to
            rediscover the next four one run at a time.
    """
    problems: list[str] = []

    if manifest.manifest_version != MANIFEST_VERSION:
        problems.append(
            f"manifest_version is {manifest.manifest_version}; this code emits "
            f"{MANIFEST_VERSION}. A schema version the writer does not recognise is refused "
            "rather than written optimistically"
        )
    if not is_canonical_instant(manifest.as_of_cutoff):
        problems.append(
            "as_of_cutoff is not a canonical UTC instant; a cutoff whose zone is ambiguous "
            "cannot be compared to an availability time"
        )
    if not isinstance(manifest.definitions, MappingProxyType):
        problems.append(
            "definitions is a mutable mapping; run_id hashes it, so it must be frozen before "
            "the id is taken"
        )

    inventory = manifest.inputs
    if not manifest.result_artifact_hash:
        problems.append(
            "result_artifact_hash is empty; a result nothing identifies cannot be checked "
            "against the manifest that claims to describe it"
        )
    elif sha256_hex(result_bytes) != manifest.result_artifact_hash:
        problems.append(
            "result_artifact_hash does not match the emitted result bytes; the manifest "
            "describes a result other than the one produced. The hash is taken over the exact "
            "bytes, not over a decoded string: decoding first made two different payloads that "
            "decode alike share an identity"
        )
    if inventory.result_artifact_hash and inventory.result_artifact_hash != (
        manifest.result_artifact_hash
    ):
        problems.append(
            "the inventory recorded a different result hash than the manifest declares; the "
            "run produced one result and the manifest describes another"
        )
    if not inventory.quality_report_hash:
        problems.append("the input inventory records no quality-report identity")
    elif (
        manifest.quality.quality_report_hash
        and manifest.quality.quality_report_hash != inventory.quality_report_hash
    ):
        problems.append(
            f"the quality summary describes report {manifest.quality.quality_report_hash!r} "
            f"while the run read {inventory.quality_report_hash!r}; the counts and the "
            "evidence are about different reports"
        )

    recorded_exclusions = sum(item.rows for item in manifest.origin_exclusions)
    if inventory.origin_exclusion_rows != recorded_exclusions:
        problems.append(
            f"the run excluded {inventory.origin_exclusion_rows} row(s) for origin "
            f"ineligibility and the manifest itemises {recorded_exclusions}; a limitation "
            "whose magnitude is misstated is not evidence of that limitation"
        )

    evidenced_bounds = {
        entry.dataset
        for entry in manifest.dataset_resolution_evidence
        if entry.provider_bounded_rows or entry.public_bounded_rows
    }
    unevidenced = sorted(set(inventory.bounds_relied_upon) - evidenced_bounds)
    if unevidenced:
        problems.append(
            f"the run leant on bounded availability for {unevidenced}, which the resolution "
            "evidence records no bounded rows for; one of the two is wrong and nothing "
            "downstream could say which"
        )

    duplicate_datasets = sorted(
        {
            reference.dataset_version
            for reference in manifest.datasets
            if [d.dataset_version for d in manifest.datasets].count(reference.dataset_version) > 1
        }
    )
    if duplicate_datasets:
        problems.append(f"dataset references {duplicate_datasets} appear more than once")
    duplicate_artifacts = sorted(
        {
            artifact.artifact_id
            for artifact in manifest.consumed_artifacts
            if [a.artifact_id for a in manifest.consumed_artifacts].count(artifact.artifact_id) > 1
        }
    )
    if duplicate_artifacts:
        problems.append(f"consumed artifacts {duplicate_artifacts} appear more than once")
    for artifact in manifest.consumed_artifacts:
        if not is_canonical_instant(artifact.artifact_first_built_time):
            problems.append(
                f"consumed artifact {artifact.artifact_id!r} records a non-canonical "
                "artifact_first_built_time"
            )

    seen_datasets: set[str] = set()
    for entry in manifest.dataset_resolution_evidence:
        if entry.dataset in seen_datasets:
            problems.append(
                f"dataset {entry.dataset!r} appears more than once in the resolution "
                "evidence; two sets of counts for one dataset cannot both describe it"
            )
        seen_datasets.add(entry.dataset)

    for reference in manifest.datasets:
        if (
            reference.resolved_profile is not None
            and reference.resolved_profile is not manifest.resolved_profile
        ):
            problems.append(
                f"dataset {reference.dataset_version!r} is keyed to "
                f"{reference.resolved_profile.value} while the run resolved to "
                f"{manifest.resolved_profile.value}; artifacts follow the resolved profile"
            )

    if inventory.revisable_datasets_consumed and manifest.revision_view is None:
        problems.append(
            f"revisable sources {list(inventory.revisable_datasets_consumed)} were consumed "
            "with no revision_view; which revision a query wanted is never an implicit answer"
        )

    recorded_artifacts = {artifact.artifact_id for artifact in manifest.consumed_artifacts}
    missing_artifacts = sorted(set(inventory.consumed_artifact_ids) - recorded_artifacts)
    if missing_artifacts:
        problems.append(
            f"derived artifacts {missing_artifacts} were consumed but are absent from "
            "derived_artifacts; dataset versions alone cannot reproduce a result that read "
            "them"
        )

    referenced_versions = {reference.dataset_version for reference in manifest.datasets}
    unpinned = sorted(set(inventory.dataset_manifest_hashes) - referenced_versions)
    if unpinned:
        problems.append(
            f"datasets {unpinned} were read but have no DatasetReference; a version with no "
            "publication hash cannot be told apart from another build of the same name"
        )
    for reference in manifest.datasets:
        recorded = inventory.dataset_manifest_hashes.get(reference.dataset_version)
        if recorded is not None and recorded != reference.publication_manifest_hash:
            problems.append(
                f"dataset {reference.dataset_version!r} was read at publication "
                f"{recorded!r} but is referenced at {reference.publication_manifest_hash!r}"
            )

    if not manifest.code.working_tree_clean:
        problems.append(
            "the working tree is dirty; an uncommitted change is not reproducible by anyone else"
        )
    if not manifest.code.commit_sha:
        problems.append("no code commit is recorded")
    if manifest.quality.blocking_issues_open:
        problems.append(
            f"{manifest.quality.blocking_issues_open} BLOCKING quality issue(s) are open "
            "against inputs this run touched; every dependent result is refused, not "
            "annotated"
        )
    if manifest.revision_view is RevisionView.LATEST_RESTATED:
        problems.append(
            "revision_view is LATEST_RESTATED, which ignores as_of entirely; the result may "
            "not be described as a backtest"
        )

    problems.extend(_check_resolution_evidence(manifest, inventory.direct_source_datasets))
    problems.extend(_check_coverage(manifest))
    problems.extend(_check_tokens(manifest))

    for bound in inventory.unapproved_bounds_relied_upon:
        problems.append(
            f"an unapproved bound was relied upon: {bound}. Recorded by the run, not declared "
            "by the caller"
        )
    for mismatch in inventory.hash_mismatches:
        problems.append(f"a content hash failed to verify during execution: {mismatch}")

    if problems:
        raise ManifestRefusedError(
            "Refusing to emit a research manifest, so the result is inadmissible:\n  - "
            + "\n  - ".join(problems)
        )
    return manifest


def _check_resolution_evidence(
    manifest: ResearchManifest,
    directly_read_datasets: Sequence[str],
) -> list[str]:
    problems: list[str] = []
    evidenced = {entry.dataset for entry in manifest.dataset_resolution_evidence}
    for dataset in sorted(set(directly_read_datasets)):
        if dataset not in evidenced:
            problems.append(
                f"dataset {dataset!r} was read directly but is absent from the per-dataset "
                "resolution evidence; the map is a complete inventory of direct source "
                "reads, not a list of the problematic ones"
            )
        if not manifest.profile_resolution.has_entry_for(dataset):
            problems.append(f"dataset {dataset!r} has no entry in dataset_provider_gap_resolutions")
    for entry in manifest.dataset_resolution_evidence:
        if not entry.public_axis_reconciles():
            problems.append(
                f"dataset {entry.dataset!r} public-axis counts do not reconcile: "
                f"{entry.public_exact_rows} exact + {entry.public_bounded_rows} bounded + "
                f"{entry.excluded_rows} excluded != {entry.rows_considered} considered"
            )
        if not entry.provider_axis_reconciles():
            problems.append(
                f"dataset {entry.dataset!r} provider-axis counts do not reconcile: "
                f"{entry.provider_exact_rows} exact + {entry.provider_bounded_rows} bounded + "
                f"{entry.excluded_rows} excluded != {entry.rows_considered} considered"
            )
    return problems


def _check_coverage(manifest: ResearchManifest) -> list[str]:
    problems: list[str] = []
    for evidence in manifest.required_inputs:
        if not evidence.evidence_is_complete():
            problems.append(
                f"required input {evidence.domain!r} ({evidence.coverage_scope.value}) is "
                "recorded without the evidence its scope requires"
            )
            continue
        if evidence.uses_the_wrong_evidence():
            problems.append(
                f"required input {evidence.domain!r} is evidenced with the wrong scope's "
                "fields; a PER_* input needs a partition minimum, a WHOLE_DOMAIN input needs "
                "a row count"
            )
            continue
        if not evidence.passes():
            problems.append(
                f"REQUIRED_INPUT_UNAVAILABLE: {evidence.domain!r} failed its "
                f"{evidence.coverage_scope.value} coverage contract "
                f"(minimum observed {evidence.minimum_observed_partition_coverage}, "
                f"threshold {evidence.min_coverage_fraction}, "
                f"failing partitions {evidence.failing_partitions}, "
                f"observed rows {evidence.observed_rows}, min rows {evidence.min_rows})"
            )
    return problems


def _check_tokens(manifest: ResearchManifest) -> list[str]:
    problems: list[str] = []
    tokens = set(manifest.limitations)
    evidence = manifest.dataset_resolution_evidence

    # Evidence, never configuration. A declared BOUND that bounded nothing and a
    # declared EXCLUDE that excluded nothing are not events, and a token emitted
    # for one is a claim with nothing behind it.
    have: dict[LimitationToken, bool] = {
        LimitationToken.ORIGIN_INELIGIBLE_ROWS_EXCLUDED: any(
            item.rows > 0 for item in manifest.origin_exclusions
        ),
        LimitationToken.PROVIDER_AVAILABILITY_UNKNOWN: any(
            entry.excluded_rows > 0 or entry.provider_bounded_rows > 0 for entry in evidence
        ),
        LimitationToken.PROVIDER_TIME_BOUNDED: any(
            entry.provider_bounded_rows > 0 for entry in evidence
        ),
        LimitationToken.PUBLIC_TIME_BOUNDED: any(
            entry.public_bounded_rows > 0 for entry in evidence
        ),
        LimitationToken.PROFILE_DOWNGRADED_TO_PUBLIC: (
            manifest.resolved_profile is not manifest.requested_profile
        ),
        LimitationToken.NON_PIT_RESTATED_VIEW: (
            manifest.revision_view is RevisionView.LATEST_RESTATED
        ),
    }

    for token, requirement in _TOKEN_EVIDENCE.items():
        if token in tokens and not have[token]:
            problems.append(
                f"limitation {token.value} is claimed with no evidence behind it; it "
                f"requires {requirement}"
            )
        if token not in tokens and have[token]:
            problems.append(
                f"limitation {token.value} is required by this run's evidence but is absent "
                "from the limitations block"
            )

    for domain in manifest.unavailable_domains:
        if domain.limitation not in tokens:
            problems.append(
                f"domain {domain.domain!r} is declared unavailable but its limitation "
                f"{domain.limitation.value} is absent from the limitations block"
            )
    return problems


__all__ = [
    "MANIFEST_VERSION",
    "CodeProvenance",
    "ConsumedArtifact",
    "CoverageEvidence",
    "DatasetReference",
    "InputInventory",
    "OriginExclusion",
    "QualitySummary",
    "ResearchManifest",
    "UnavailableDomain",
    "emit_manifest",
]
