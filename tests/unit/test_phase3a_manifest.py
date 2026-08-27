"""Reproducibility manifests and deterministic ``run_id``.

The claim being tested is the strong one: a recorded result can be regenerated
from its manifest alone, **or the attempt fails loudly**. Failing loudly is half
the value -- a silent re-derivation against changed data is how a research
programme accumulates results it cannot defend.
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Any, cast

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.canonical import content_hash
from kalpamani.data.contracts.errors import ManifestRefusedError
from kalpamani.data.contracts.manifest import (
    MANIFEST_VERSION,
    CodeProvenance,
    ConsumedArtifact,
    CoverageEvidence,
    DatasetReference,
    InputInventory,
    OriginExclusion,
    QualitySummary,
    ResearchManifest,
    UnavailableDomain,
    emit_manifest,
)
from kalpamani.data.contracts.profiles import (
    DatasetResolutionEvidence,
    ProfileResolutionConfig,
    TimingBasis,
)
from kalpamani.data.contracts.vocabulary import (
    CoverageScope,
    DatasetGapPolicy,
    GlobalProfileResolution,
    InformationSetProfile,
    LimitationToken,
    RevisionView,
)
from kalpamani.data.curate.resolution_run import evidence_limitation_tokens

pytestmark = pytest.mark.unit

PUBLIC = InformationSetProfile.PUBLIC_PIT
PROVIDER_REALISTIC = InformationSetProfile.PROVIDER_REALISTIC_PIT
FORWARD = InformationSetProfile.FORWARD_SYSTEM

COMMIT = "0123456789abcdef0123456789abcdef01234567"
AS_OF = datetime(2026, 8, 26, 13, 0, tzinfo=UTC)


def _evidence(dataset: str, policy: DatasetGapPolicy) -> DatasetResolutionEvidence:
    bounded = policy is DatasetGapPolicy.BOUND
    excluded = 10 if policy is DatasetGapPolicy.EXCLUDE else 0
    return DatasetResolutionEvidence(
        dataset=dataset,
        policy=policy,
        rows_considered=10,
        public_rows_applicable=10,
        public_basis=TimingBasis.EXACT,
        public_exact_rows=10 - excluded,
        public_bounded_rows=0,
        public_excluded_rows=excluded,
        public_unresolved_rows=0,
        provider_rows_applicable=10,
        provider_basis=TimingBasis.BOUND if bounded else TimingBasis.EXACT,
        provider_exact_rows=0 if bounded else 10 - excluded,
        provider_bounded_rows=10 if bounded else 0,
        provider_excluded_rows=excluded,
        provider_unresolved_rows=0,
        excluded_rows=excluded,
        reason=f"synthetic {policy.value} evidence",
    )


def _coverage(*, failing: int = 0, minimum: str = "0.9948") -> CoverageEvidence:
    return CoverageEvidence(
        domain="price_bar",
        coverage_scope=CoverageScope.PER_SESSION,
        min_coverage_fraction=Decimal("0.99"),
        minimum_observed_partition_coverage=Decimal(minimum),
        total_partitions=8,
        failing_partitions=failing,
    )


def _tokens(
    config: ProfileResolutionConfig,
    evidence: tuple[DatasetResolutionEvidence, ...],
) -> tuple[LimitationToken, ...]:
    """The tokens this run's **evidence** obliges, never the ones its config declared."""
    return evidence_limitation_tokens(
        evidence, downgraded=config.resolved_profile is not config.requested_profile
    )


def _evidence_for(
    config: ProfileResolutionConfig,
) -> tuple[DatasetResolutionEvidence, ...]:
    return tuple(_evidence(entry.dataset, entry.policy) for entry in config.dataset_resolutions)


def _default_tokens() -> tuple[LimitationToken, ...]:
    config = phase3a.resolution()
    return _tokens(config, _evidence_for(config))


def _manifest(**overrides: object) -> ResearchManifest:
    config = cast(
        ProfileResolutionConfig, overrides.pop("profile_resolution", phase3a.resolution())
    )
    evidence = tuple(_evidence(entry.dataset, entry.policy) for entry in config.dataset_resolutions)
    base: dict[str, object] = {
        "code": CodeProvenance(
            commit_sha=COMMIT, working_tree_clean=True, config_version="research/synthetic.a1"
        ),
        "as_of_cutoff": AS_OF,
        "backtest_start": date(2019, 6, 24),
        "backtest_end": date(2021, 1, 5),
        "profile_resolution": config,
        "revision_view": RevisionView.AS_KNOWN_AT_AS_OF,
        "dataset_resolution_evidence": evidence,
        "required_inputs": (_coverage(),),
        "datasets": (
            DatasetReference(
                dataset_version=phase3a.DATASET_VERSION,
                layer="GOLD",
                content_hash="sha256:abc",
                publication_manifest_hash="sha256:publication",
                resolved_profile=config.resolved_profile,
            ),
        ),
        "inputs": _inventory(),
        "definitions": {"universe_definition_version": phase3a.UNIVERSE_DEFINITION_VERSION},
        "limitations": _tokens(config, evidence),
        "quality": QualitySummary(blocking_issues_open=0, warnings_open=2),
        "random_seed": 20260826,
        "result_artifact_hash": content_hash(RESULT_BYTES.decode("utf-8")),
    }
    base.update(overrides)
    return ResearchManifest(**base)  # type: ignore[arg-type]


RESULT_BYTES = b'{"result": "synthetic"}'


def _inventory(**overrides: object) -> InputInventory:
    base: dict[str, object] = {
        "direct_source_datasets": tuple(
            entry.dataset for entry in phase3a.resolution().dataset_resolutions
        ),
        "dataset_manifest_hashes": {phase3a.DATASET_VERSION: "sha256:publication"},
        "quality_report_hash": "sha256:quality",
        "result_artifact_hash": content_hash(RESULT_BYTES.decode("utf-8")),
    }
    base.update(overrides)
    return InputInventory(**base)  # type: ignore[arg-type]


def _emit(manifest: ResearchManifest, *, result_bytes: bytes = RESULT_BYTES) -> ResearchManifest:
    return emit_manifest(manifest, result_bytes=result_bytes)


# ---------------------------------------------------------------------------
# run_id
# ---------------------------------------------------------------------------


def test_a_wrong_manifest_version_refuses() -> None:
    """A schema version the writer does not recognise is not written optimistically."""
    with pytest.raises(ManifestRefusedError, match="manifest_version"):
        _emit(_manifest(manifest_version=MANIFEST_VERSION + 1))


def test_a_non_utc_as_of_cutoff_is_normalised_at_construction() -> None:
    """Two spellings of one cutoff must not be two cutoffs."""
    shifted = _manifest(as_of_cutoff=AS_OF.astimezone(timezone(timedelta(hours=5, minutes=30))))
    assert shifted.as_of_cutoff == AS_OF
    assert shifted.as_of_cutoff.utcoffset() == timedelta(0)
    assert shifted.run_id == _manifest().run_id


def test_a_naive_as_of_cutoff_cannot_be_constructed() -> None:
    with pytest.raises(TypeError, match="naive datetime"):
        _manifest(as_of_cutoff=datetime(2026, 8, 26, 13, 0))


def test_duplicate_dataset_resolution_evidence_refuses() -> None:
    """Two sets of counts for one dataset cannot both describe it."""
    config = phase3a.resolution()
    doubled = (*_evidence_for(config), _evidence("price_bar", DatasetGapPolicy.NONE))
    with pytest.raises(ManifestRefusedError, match="appears more than once"):
        _emit(_manifest(dataset_resolution_evidence=doubled))


def test_a_dataset_reference_keyed_to_another_profile_refuses() -> None:
    """Artifacts follow the resolved profile; a mismatch hides a downgrade."""
    manifest = _manifest(
        datasets=(
            DatasetReference(
                dataset_version=phase3a.DATASET_VERSION,
                layer="GOLD",
                content_hash="sha256:abc",
                publication_manifest_hash="sha256:publication",
                resolved_profile=FORWARD,
            ),
        )
    )
    with pytest.raises(ManifestRefusedError, match="artifacts follow the resolved profile"):
        _emit(manifest)


def test_a_revisable_source_consumed_without_a_revision_view_refuses() -> None:
    """Which revision a query wanted is never an implicit answer."""
    manifest = _manifest(
        revision_view=None,
        inputs=_inventory(revisable_datasets_consumed=("listing",)),
    )
    with pytest.raises(ManifestRefusedError, match="no revision_view"):
        _emit(manifest)


def test_a_consumed_artifact_absent_from_the_manifest_refuses() -> None:
    """Dataset versions alone cannot reproduce a result that read an artifact."""
    manifest = _manifest(inputs=_inventory(consumed_artifact_ids=("adj-missing",)))
    with pytest.raises(ManifestRefusedError, match="absent from"):
        _emit(manifest)


def test_definitions_are_deep_frozen_so_run_id_cannot_drift() -> None:
    """Mutate-after-hash is structurally impossible, not merely checked for."""
    manifest = _manifest(definitions={"universe_definition_version": "universe/v1"})
    before = manifest.run_id
    with pytest.raises(TypeError):
        cast("Any", manifest.definitions)["universe_definition_version"] = "universe/v2"
    assert manifest.run_id == before
    assert isinstance(manifest.definitions, MappingProxyType)


def test_run_id_is_stable_across_repeated_reads() -> None:
    manifest = _manifest()
    assert len({manifest.run_id for _ in range(5)}) == 1


def test_a_provider_availability_token_needs_bounded_or_excluded_rows() -> None:
    """Evidence, not configuration: a BOUND that bounded nothing is not an event."""
    config = phase3a.resolution()
    inert = tuple(
        DatasetResolutionEvidence(
            dataset=entry.dataset,
            policy=entry.policy,
            rows_considered=10,
            public_rows_applicable=10,
            public_basis=TimingBasis.EXACT,
            public_exact_rows=10,
            public_bounded_rows=0,
            public_excluded_rows=0,
            public_unresolved_rows=0,
            provider_rows_applicable=10,
            provider_basis=TimingBasis.EXACT,
            provider_exact_rows=10,
            provider_bounded_rows=0,
            provider_excluded_rows=0,
            provider_unresolved_rows=0,
            excluded_rows=0,
            reason="nothing was bounded or excluded",
        )
        for entry in config.dataset_resolutions
    )
    assert _tokens(config, inert) == ()
    assert _emit(_manifest(dataset_resolution_evidence=inert, limitations=())) is not None

    with pytest.raises(ManifestRefusedError, match="claimed with no evidence behind it"):
        _emit(
            _manifest(
                dataset_resolution_evidence=inert,
                limitations=(LimitationToken.PROVIDER_AVAILABILITY_UNKNOWN,),
            )
        )


def test_a_caller_cannot_shorten_the_input_inventory() -> None:
    """The evidence rules run against what the run read, not what a caller admits.

    The shape this replaces took the inventory as arguments, so passing empty
    lists satisfied every closure rule. An inventory the query path produces
    cannot be shortened by omission.
    """
    from dataclasses import fields as dataclass_fields

    signature_fields = {f.name for f in dataclass_fields(ResearchManifest)}
    assert "inputs" in signature_fields, "The manifest owns its inventory."

    parameters = set(inspect.signature(emit_manifest).parameters)
    assert not parameters & {
        "directly_read_datasets",
        "consumed_artifact_ids",
        "revisable_datasets_consumed",
    }, "No side-channel input lists remain on the emission boundary."


def test_an_empty_result_hash_refuses() -> None:
    with pytest.raises(ManifestRefusedError, match="result_artifact_hash is empty"):
        _emit(_manifest(result_artifact_hash=""))


def test_a_result_hash_that_does_not_match_the_bytes_refuses() -> None:
    """The manifest must describe the result that was produced, not another one."""
    with pytest.raises(ManifestRefusedError, match="does not match the emitted result bytes"):
        _emit(_manifest(), result_bytes=b'{"result": "something else"}')


def test_a_dataset_read_without_a_reference_refuses() -> None:
    manifest = _manifest(
        inputs=_inventory(
            dataset_manifest_hashes={
                phase3a.DATASET_VERSION: "sha256:publication",
                "gold/unreferenced": "sha256:other",
            }
        )
    )
    with pytest.raises(ManifestRefusedError, match="no DatasetReference"):
        _emit(manifest)


def test_a_dataset_referenced_at_another_publication_refuses() -> None:
    """Two builds can share a version string and be different datasets."""
    manifest = _manifest(
        inputs=_inventory(dataset_manifest_hashes={phase3a.DATASET_VERSION: "sha256:different"})
    )
    with pytest.raises(ManifestRefusedError, match="was read at publication"):
        _emit(manifest)


def test_duplicate_dataset_references_refuse() -> None:
    reference = DatasetReference(
        dataset_version=phase3a.DATASET_VERSION,
        layer="GOLD",
        content_hash="sha256:abc",
        publication_manifest_hash="sha256:publication",
        resolved_profile=PUBLIC,
    )
    with pytest.raises(ManifestRefusedError, match="appear more than once"):
        _emit(_manifest(datasets=(reference, reference)))


def test_the_publication_hash_enters_run_id() -> None:
    """A version string is not an identity; the publication it names is."""
    baseline = _manifest().run_id
    other = _manifest(
        datasets=(
            DatasetReference(
                dataset_version=phase3a.DATASET_VERSION,
                layer="GOLD",
                content_hash="sha256:abc",
                publication_manifest_hash="sha256:a-different-build",
                resolved_profile=PUBLIC,
            ),
        ),
        inputs=_inventory(
            dataset_manifest_hashes={phase3a.DATASET_VERSION: "sha256:a-different-build"}
        ),
    ).run_id
    assert baseline != other


def test_run_id_is_deterministic_and_derived_not_generated() -> None:
    """No ``uuid4()``. No timestamps. Same inputs, same id."""
    first = _manifest().run_id
    second = _manifest().run_id
    assert first == second
    assert first.startswith("rs-")


def test_run_id_ignores_wall_clock_execution_time() -> None:
    """Hashing when a run happened into its identity would make every re-run a new run."""
    inputs = _manifest().run_id_inputs()
    rendered = str(inputs)
    assert "started_at" not in rendered
    assert "completed_at" not in rendered


def test_profile_resolution_changes_run_id() -> None:
    """Two runs that resolved the same query differently must not share an identity."""
    bound_and_exclude = _manifest().run_id
    reversed_policies = _manifest(
        profile_resolution=phase3a.resolution(requested=PROVIDER_REALISTIC)
    ).run_id
    downgraded = _manifest(
        profile_resolution=phase3a.resolution(
            requested=PROVIDER_REALISTIC, downgrade=GlobalProfileResolution.DOWNGRADE
        )
    ).run_id
    assert len({bound_and_exclude, reversed_policies, downgraded}) == 3


def test_two_runs_differing_only_in_how_one_gap_was_resolved_are_two_runs() -> None:
    """``EXCLUDE`` and ``BOUND`` admit different rows, so they cannot share an id.

    This is the sharper claim: not "a different profile is a different run", but
    "the same query, the same profile, one dataset resolved the other way".
    """
    from kalpamani.data.contracts.profiles import DatasetGapResolution, ProfileResolutionConfig

    def config(policy: DatasetGapPolicy) -> ProfileResolutionConfig:
        return ProfileResolutionConfig(
            requested_profile=PROVIDER_REALISTIC,
            resolution_policy_version=phase3a.RESOLUTION_POLICY_VERSION,
            dataset_resolutions=(
                DatasetGapResolution(dataset="listing", policy=policy, reason="synthetic"),
            ),
        )

    bound = _manifest(
        profile_resolution=config(DatasetGapPolicy.BOUND),
        limitations=_tokens(
            config(DatasetGapPolicy.BOUND), _evidence_for(config(DatasetGapPolicy.BOUND))
        ),
    )
    excluded = _manifest(
        profile_resolution=config(DatasetGapPolicy.EXCLUDE),
        limitations=_tokens(
            config(DatasetGapPolicy.EXCLUDE), _evidence_for(config(DatasetGapPolicy.EXCLUDE))
        ),
    )
    assert bound.run_id != excluded.run_id


def test_a_changed_resolution_policy_version_changes_run_id() -> None:
    """Which policy chose a resolution is part of what a run is."""
    from kalpamani.data.contracts.profiles import ProfileResolutionConfig

    baseline = _manifest().run_id
    other = _manifest(
        profile_resolution=ProfileResolutionConfig(
            requested_profile=PUBLIC,
            resolution_policy_version="profres/other",
            dataset_resolutions=phase3a.resolution().dataset_resolutions,
        )
    ).run_id
    assert baseline != other


def test_the_whole_resolution_map_enters_run_id_not_a_summary() -> None:
    inputs = _manifest().run_id_inputs()
    canonical = phase3a.resolution().canonical_map()
    assert inputs["dataset_provider_gap_resolutions"] == list(canonical)
    assert len(canonical) == len(phase3a.resolution().dataset_resolutions)


def test_the_same_query_under_two_profiles_is_two_runs() -> None:
    public = _manifest().run_id
    forward = _manifest(profile_resolution=phase3a.resolution(requested=FORWARD)).run_id
    assert public != forward


def test_artifact_first_built_time_enters_run_id_only_under_forward_system() -> None:
    """Two runs over identical dataset versions can legitimately differ under it."""
    artifact_a = ConsumedArtifact(
        artifact_id="adj-1",
        entity="adjusted_bar_artifact",
        output_validity="INTERVAL",
        derivation_spec_version="adj/a1.1",
        artifact_content_hash="sha256:series",
        artifact_first_built_time=datetime(2026, 8, 20, 11, 0, tzinfo=UTC),
        lineage_selectors=(("price_bar", "gold/v1", "scope=SEC-0001"),),
    )
    artifact_b = ConsumedArtifact(
        artifact_id=artifact_a.artifact_id,
        entity=artifact_a.entity,
        output_validity=artifact_a.output_validity,
        derivation_spec_version=artifact_a.derivation_spec_version,
        artifact_content_hash=artifact_a.artifact_content_hash,
        artifact_first_built_time=datetime(2026, 8, 21, 11, 0, tzinfo=UTC),
        lineage_selectors=artifact_a.lineage_selectors,
    )

    public_a = _manifest(consumed_artifacts=(artifact_a,)).run_id
    public_b = _manifest(consumed_artifacts=(artifact_b,)).run_id
    assert public_a == public_b, "Under PUBLIC_PIT an artifact is as available as its inputs."

    forward_config = phase3a.resolution(requested=FORWARD)
    forward_a = _manifest(
        profile_resolution=forward_config, consumed_artifacts=(artifact_a,)
    ).run_id
    forward_b = _manifest(
        profile_resolution=forward_config, consumed_artifacts=(artifact_b,)
    ).run_id
    assert forward_a != forward_b


def test_the_manifest_declares_its_schema_version() -> None:
    assert _manifest().manifest_version == MANIFEST_VERSION


# ---------------------------------------------------------------------------
# Emission preconditions
# ---------------------------------------------------------------------------


def test_a_well_formed_manifest_is_emitted() -> None:
    """NEGATIVE CONTROL. The refusal rules must not block a correct run."""
    assert _emit(_manifest()) is not None


def test_a_dirty_working_tree_refuses() -> None:
    manifest = _manifest(
        code=CodeProvenance(
            commit_sha=COMMIT, working_tree_clean=False, config_version="research/synthetic.a1"
        )
    )
    with pytest.raises(ManifestRefusedError, match="working tree is dirty"):
        _emit(manifest)


def test_an_open_blocking_issue_refuses() -> None:
    manifest = _manifest(quality=QualitySummary(blocking_issues_open=1, warnings_open=0))
    with pytest.raises(ManifestRefusedError, match="BLOCKING quality issue"):
        _emit(manifest)


def test_a_missing_profile_resolution_cannot_be_constructed() -> None:
    """The strongest form of "required": not expressible, rather than checked."""
    with pytest.raises(TypeError):
        ResearchManifest(  # type: ignore[call-arg]
            code=CodeProvenance(commit_sha=COMMIT, working_tree_clean=True, config_version="c"),
            as_of_cutoff=AS_OF,
            revision_view=RevisionView.AS_KNOWN_AT_AS_OF,
            quality=QualitySummary(blocking_issues_open=0, warnings_open=0),
            inputs=_inventory(),
        )


def test_a_missing_as_of_cutoff_cannot_be_constructed() -> None:
    with pytest.raises(TypeError):
        ResearchManifest(  # type: ignore[call-arg]
            code=CodeProvenance(commit_sha=COMMIT, working_tree_clean=True, config_version="c"),
            profile_resolution=phase3a.resolution(),
            revision_view=RevisionView.AS_KNOWN_AT_AS_OF,
            quality=QualitySummary(blocking_issues_open=0, warnings_open=0),
            inputs=_inventory(),
        )


def test_a_latest_restated_run_may_not_call_itself_a_backtest() -> None:
    manifest = _manifest(
        revision_view=RevisionView.LATEST_RESTATED,
        limitations=(
            *_default_tokens(),
            LimitationToken.NON_PIT_RESTATED_VIEW,
        ),
    )
    with pytest.raises(ManifestRefusedError, match="may not be described as a backtest"):
        _emit(manifest)


def test_a_directly_read_dataset_absent_from_the_evidence_refuses() -> None:
    manifest = _manifest()
    manifest = _manifest(inputs=_inventory(direct_source_datasets=("fundamental_fact",)))
    with pytest.raises(ManifestRefusedError, match="absent from the per-dataset"):
        _emit(manifest)


def test_unreconciled_per_axis_counts_refuse() -> None:
    """The axes reconcile independently; one bad axis is enough."""
    config = phase3a.resolution()
    broken = DatasetResolutionEvidence(
        dataset="price_bar",
        policy=DatasetGapPolicy.NONE,
        rows_considered=10,
        public_rows_applicable=10,
        public_basis=TimingBasis.EXACT,
        public_exact_rows=3,
        public_bounded_rows=0,
        public_excluded_rows=0,
        public_unresolved_rows=0,
        provider_rows_applicable=10,
        provider_basis=TimingBasis.EXACT,
        provider_exact_rows=10,
        provider_bounded_rows=0,
        provider_excluded_rows=0,
        provider_unresolved_rows=0,
        excluded_rows=0,
        reason="deliberately unreconciled",
    )
    others = tuple(
        _evidence(entry.dataset, entry.policy)
        for entry in config.dataset_resolutions
        if entry.dataset != "price_bar"
    )
    manifest = _manifest(dataset_resolution_evidence=(broken, *others))
    with pytest.raises(ManifestRefusedError, match="public-axis counts do not reconcile"):
        _emit(manifest)


def test_a_required_input_failing_its_coverage_contract_refuses() -> None:
    """ "Not completely empty" is not "sufficient"."""
    manifest = _manifest(required_inputs=(_coverage(failing=34),))
    with pytest.raises(ManifestRefusedError, match="REQUIRED_INPUT_UNAVAILABLE"):
        _emit(manifest)


def test_a_partition_minimum_below_its_threshold_refuses() -> None:
    manifest = _manifest(required_inputs=(_coverage(minimum="0.5000"),))
    with pytest.raises(ManifestRefusedError, match="REQUIRED_INPUT_UNAVAILABLE"):
        _emit(manifest)


def test_a_per_scope_input_evidenced_by_a_row_count_refuses() -> None:
    """Averaging a failing partition away is the move the scope exists to prevent."""
    manifest = _manifest(
        required_inputs=(
            CoverageEvidence(
                domain="price_bar",
                coverage_scope=CoverageScope.PER_SESSION,
                min_rows=1_000,
                observed_rows=2_000,
            ),
        )
    )
    with pytest.raises(ManifestRefusedError, match="without the evidence its scope requires"):
        _emit(manifest)


def test_a_whole_domain_input_evidenced_by_a_fraction_refuses() -> None:
    """There is no natural denominator for "the whole domain"."""
    manifest = _manifest(
        required_inputs=(
            CoverageEvidence(
                domain="listing",
                coverage_scope=CoverageScope.WHOLE_DOMAIN,
                min_rows=1,
                observed_rows=7,
                min_coverage_fraction=Decimal("0.9"),
            ),
        )
    )
    with pytest.raises(ManifestRefusedError, match="wrong scope's fields"):
        _emit(manifest)


def test_a_whole_domain_input_meeting_its_row_count_passes() -> None:
    """NEGATIVE CONTROL N17. A met contract is not a breach."""
    manifest = _manifest(
        required_inputs=(
            CoverageEvidence(
                domain="listing",
                coverage_scope=CoverageScope.WHOLE_DOMAIN,
                min_rows=1,
                observed_rows=7,
            ),
        )
    )
    assert _emit(manifest) is not None


def test_a_limitation_token_with_no_evidence_refuses() -> None:
    manifest = _manifest(
        limitations=(
            *_default_tokens(),
            LimitationToken.ORIGIN_INELIGIBLE_ROWS_EXCLUDED,
        )
    )
    with pytest.raises(ManifestRefusedError, match="claimed with no evidence behind it"):
        _emit(manifest)


def test_a_zero_row_exclusion_is_not_evidence_of_an_exclusion() -> None:
    """A domain that was never populated is not a domain whose rows were excluded."""
    manifest = _manifest(
        origin_exclusions=(
            OriginExclusion(dataset="price_bar", information_origin="PROVIDER_DERIVED", rows=0),
        ),
        limitations=(
            *_default_tokens(),
            LimitationToken.ORIGIN_INELIGIBLE_ROWS_EXCLUDED,
        ),
    )
    with pytest.raises(ManifestRefusedError, match="no evidence behind it"):
        _emit(manifest)


def test_a_positive_exclusion_with_its_token_passes() -> None:
    manifest = _manifest(
        origin_exclusions=(
            OriginExclusion(dataset="price_bar", information_origin="PROVIDER_DERIVED", rows=2),
        ),
        limitations=(
            *_default_tokens(),
            LimitationToken.ORIGIN_INELIGIBLE_ROWS_EXCLUDED,
        ),
    )
    assert _emit(manifest) is not None


def test_a_bound_resolution_without_its_token_refuses() -> None:
    """A ``BOUND`` that is not declared is a bound nobody can find."""
    manifest = _manifest(limitations=())
    with pytest.raises(ManifestRefusedError, match="required by this run's evidence"):
        _emit(manifest)


def test_a_downgrade_carries_its_token() -> None:
    config = phase3a.resolution(
        requested=PROVIDER_REALISTIC, downgrade=GlobalProfileResolution.DOWNGRADE
    )
    assert LimitationToken.PROFILE_DOWNGRADED_TO_PUBLIC in _tokens(config, _evidence_for(config))
    manifest = _manifest(
        profile_resolution=config, limitations=_tokens(config, _evidence_for(config))
    )
    assert _emit(manifest) is not None
    assert manifest.resolved_profile is PUBLIC
    assert manifest.requested_profile is PROVIDER_REALISTIC


def test_an_unavailable_domain_must_carry_its_limitation() -> None:
    manifest = _manifest(
        unavailable_domains=(
            UnavailableDomain(
                domain="analyst_estimate_snapshot",
                reason="NO_QUALIFIED_SOURCE",
                limitation=LimitationToken.SINGLE_SOURCE_UNVERIFIED,
            ),
        )
    )
    with pytest.raises(ManifestRefusedError, match="declared unavailable but its limitation"):
        _emit(manifest)


def test_an_unapproved_bound_or_hash_mismatch_refuses() -> None:
    with pytest.raises(ManifestRefusedError, match="unapproved bound was relied upon"):
        emit_manifest(
            _manifest(),
            result_bytes=RESULT_BYTES,
            unapproved_bounds_relied_upon=["price_bar:SESSION_CLOSE_PLUS_LAG"],
        )
    with pytest.raises(ManifestRefusedError, match="content hash failed to verify"):
        emit_manifest(
            _manifest(),
            result_bytes=RESULT_BYTES,
            hash_mismatches=["gold/synthetic.a1.1"],
        )


def test_every_refused_precondition_is_reported_at_once() -> None:
    """A reader fixing one failure should not rediscover the next four one run at a time."""
    manifest = _manifest(
        code=CodeProvenance(
            commit_sha="", working_tree_clean=False, config_version="research/synthetic.a1"
        ),
        quality=QualitySummary(blocking_issues_open=3, warnings_open=0),
        required_inputs=(_coverage(failing=1),),
    )
    with pytest.raises(ManifestRefusedError) as raised:
        _emit(manifest)
    message = str(raised.value)
    assert "working tree is dirty" in message
    assert "no code commit is recorded" in message
    assert "BLOCKING quality issue" in message
    assert "REQUIRED_INPUT_UNAVAILABLE" in message
