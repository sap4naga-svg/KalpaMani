"""The enforcement boundaries, tested where they can actually be bypassed.

Each test below targets a route by which a caller could once have obtained a
valid-looking result without producing the evidence for it. They are grouped by
the boundary they defend rather than by module, because the question each answers
is "can this be got around?" and not "does this function work?".
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.dataset import GoldDataset
from kalpamani.data.contracts.errors import (
    BuildBoundaryError,
    DatasetPublicationError,
    QualityGateError,
    RequiredInputUnavailableError,
    UnresolvedProviderAvailabilityError,
    UnsafePathComponentError,
)
from kalpamani.data.contracts.profiles import (
    DatasetGapResolution,
    ProfileResolutionConfig,
)
from kalpamani.data.contracts.resolution import ApprovedBoundPolicy, BoundApprovals
from kalpamani.data.contracts.vocabulary import (
    DatasetGapPolicy,
    GlobalProfileResolution,
    InformationSetProfile,
    ProviderBoundDerivation,
)
from kalpamani.data.curate.build import build_gold_dataset, dataset_row_fingerprint
from kalpamani.data.curate.publication import publish_gold_dataset
from kalpamani.data.curate.resolution_run import resolve_run_inputs
from kalpamani.data.curate.universe import (
    UniverseBuildInputs,
    build_universe_snapshot,
    current_listings,
)
from kalpamani.data.quality.plan import PHASE3A_QUALITY_PLAN
from kalpamani.data.quality.report import CheckNotRun, QualityReport, report_from_findings
from kalpamani.data.storage import LocalTableStore

pytestmark = pytest.mark.unit

PUBLIC = InformationSetProfile.PUBLIC_PIT
PROVIDER_REALISTIC = InformationSetProfile.PROVIDER_REALISTIC_PIT


# ---------------------------------------------------------------------------
# The build boundary
# ---------------------------------------------------------------------------


def test_gold_cannot_be_built_without_resolved_inputs() -> None:
    """A build takes ``ResolvedRunInputs``, not rows. There is no other door."""
    import inspect

    parameters = list(inspect.signature(build_gold_dataset).parameters)
    assert parameters[0] == "resolved"
    annotation = inspect.signature(build_gold_dataset).parameters["resolved"].annotation
    assert "ResolvedRunInputs" in str(annotation)


def test_a_build_missing_a_resolved_dataset_is_refused() -> None:
    """Reaching around resolution for one dataset is reaching around it entirely."""
    partial = resolve_run_inputs(
        {"price_bar": phase3a.bars()},
        config=ProfileResolutionConfig(
            requested_profile=PUBLIC,
            resolution_policy_version=phase3a.RESOLUTION_POLICY_VERSION,
            dataset_resolutions=(
                DatasetGapResolution(
                    dataset="price_bar", policy=DatasetGapPolicy.NONE, reason="synthetic"
                ),
            ),
        ),
        approvals=phase3a.approvals(),
    )
    with pytest.raises(BuildBoundaryError, match="did not go through resolve_run_inputs"):
        build_gold_dataset(
            partial,
            dataset_version=phase3a.DATASET_VERSION,
            build_time=phase3a.BUILD_TIME,
            coverage_start=phase3a.COVERAGE_START,
            coverage_end=phase3a.COVERAGE_END,
            universe_definition=phase3a.universe_definition(),
            universe_sessions=phase3a.SNAPSHOT_SESSIONS,
            evaluation_cutoffs=phase3a.evaluation_cutoffs(),
            approvals=phase3a.approvals(),
            artifact_first_built_time=phase3a.ARTIFACT_FIRST_BUILT,
            ingestion_time=phase3a.INGESTION_TIME,
        )


def test_a_row_filed_under_the_wrong_dataset_key_is_refused() -> None:
    """A misfiled row is resolved by the wrong policy and counted against the wrong evidence.

    The counts still reconcile, which is exactly why nothing downstream would
    notice.
    """
    datasets = dict(phase3a.source_datasets())
    datasets["price_bar"] = (*datasets["price_bar"], *phase3a.listings()[:1])
    with pytest.raises(UnresolvedProviderAvailabilityError, match="filed under a dataset key"):
        resolve_run_inputs(datasets, config=phase3a.resolution(), approvals=phase3a.approvals())


def test_a_row_in_two_dataset_groups_is_refused() -> None:
    datasets = dict(phase3a.source_datasets())
    shared = datasets["listing"][0]
    datasets["market_session"] = (*datasets["market_session"], shared)
    with pytest.raises(UnresolvedProviderAvailabilityError):
        resolve_run_inputs(datasets, config=phase3a.resolution(), approvals=phase3a.approvals())


def test_raw_gold_rows_cannot_be_published(tmp_path: Path) -> None:
    """A dataset whose receipt does not account for its rows is unpublishable.

    Substituting a row after resolution is the concrete version of "correct rows,
    unknown provenance": everything type-checks, every test the build itself runs
    passes, and nothing can say which policy admitted the substitute.
    """
    dataset = phase3a.gold_dataset()
    tampered = GoldDataset(
        dataset_version=dataset.dataset_version,
        build_time=dataset.build_time,
        coverage_start=dataset.coverage_start,
        coverage_end=dataset.coverage_end,
        resolved_profile=dataset.resolved_profile,
        resolution_policy_version=dataset.resolution_policy_version,
        resolution_receipt=dataset.resolution_receipt,
        resolution_evidence=dataset.resolution_evidence,
        sessions=dataset.sessions,
        listings=dataset.listings,
        attributes=dataset.attributes,
        tickers=dataset.tickers,
        bars=dataset.bars[:-1],  # one row quietly dropped
        actions=dataset.actions,
        universe=dataset.universe,
        universe_headers=dataset.universe_headers,
    )
    assert dataset_row_fingerprint(tampered) != tampered.resolution_receipt.row_fingerprint
    with pytest.raises(BuildBoundaryError, match="does not describe this build"):
        publish_gold_dataset(
            LocalTableStore(tmp_path),
            tampered,
            quality_report=phase3a.quality_report(),
            quality_plan=PHASE3A_QUALITY_PLAN,
            code_commit_sha=phase3a.CODE_COMMIT_SHA,
            lag_policy_version=phase3a.LAG_POLICY_VERSION,
            universe_definition_version=phase3a.UNIVERSE_DEFINITION_VERSION,
        )


def test_a_receipt_is_deterministic_and_covers_the_reasons() -> None:
    """Two runs that bounded the same dataset for different reasons resolved it differently."""
    first = phase3a.resolved_inputs().receipt
    again = phase3a.resolved_inputs().receipt
    assert first.receipt_hash == again.receipt_hash

    restated = ProfileResolutionConfig(
        requested_profile=PUBLIC,
        resolution_policy_version=phase3a.RESOLUTION_POLICY_VERSION,
        dataset_resolutions=tuple(
            DatasetGapResolution(
                dataset=entry.dataset, policy=entry.policy, reason="a different stated reason"
            )
            for entry in phase3a.resolution().dataset_resolutions
        ),
    )
    other = resolve_run_inputs(
        phase3a.source_datasets(), config=restated, approvals=phase3a.approvals()
    ).receipt
    assert other.receipt_hash != first.receipt_hash
    assert not other.agrees_with(phase3a.resolution())


# ---------------------------------------------------------------------------
# BOUND must actually resolve
# ---------------------------------------------------------------------------


def test_an_unapproved_bound_refuses_at_the_resolution_boundary() -> None:
    """``BOUND`` writes a bound; it does not guarantee the bound resolves.

    A bound whose derivation is not approved for its dataset resolves nothing, so
    applying the policy and moving on would serve rows on timing the run never
    established -- with the policy name in the manifest making it look handled.
    """
    unapproved = BoundApprovals(
        by_dataset={
            "price_bar": phase3a.approvals().for_dataset("price_bar"),
            "corporate_action": phase3a.approvals().for_dataset("corporate_action"),
            # market_session's FIRST_SEEN_UPPER_BOUND is deliberately not approved.
            "market_session": ApprovedBoundPolicy(),
        }
    )
    with pytest.raises(
        UnresolvedProviderAvailabilityError,
        match=r"4\.3\.2_unresolved_provider_availability",
    ):
        resolve_run_inputs(
            phase3a.source_datasets(),
            config=phase3a.resolution(requested=PROVIDER_REALISTIC),
            approvals=unapproved,
        )


def test_an_approved_bound_resolves_and_is_evidenced() -> None:
    """NEGATIVE CONTROL. The approved case must not be caught by the same rule."""
    resolved = phase3a.resolved_inputs(requested=PROVIDER_REALISTIC)
    evidence = resolved.evidence_for("market_session")
    assert evidence.policy is DatasetGapPolicy.BOUND
    assert evidence.provider_bounded_rows == len(phase3a.sessions())
    assert evidence.provider_unresolved_rows == 0
    for row in resolved.rows("market_session"):
        assert (
            row.envelope.provider_bound_derivation is ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND
        )


def test_every_axis_reconciles_on_the_reference_build() -> None:
    """Mixed-origin datasets have a different denominator per axis."""
    for evidence in phase3a.resolved_inputs(requested=PROVIDER_REALISTIC).evidence:
        assert evidence.public_axis_reconciles(), evidence.dataset
        assert evidence.provider_axis_reconciles(), evidence.dataset


# ---------------------------------------------------------------------------
# The quality gate
# ---------------------------------------------------------------------------


def test_a_report_that_ran_no_checks_is_not_evidence() -> None:
    with pytest.raises(QualityGateError, match="ran no checks"):
        report_from_findings(
            (),
            plan_version=PHASE3A_QUALITY_PLAN.plan_version,
            policy_versions={"market": "x"},
            checks_run=(),
            datasets_covered=("price_bar",),
            produced_at=phase3a.BUILD_TIME,
        )


def test_checks_that_could_not_run_are_declared() -> None:
    """A check that silently covered less than it claims is worse than no check."""
    report = phase3a.quality_report()
    assert report.checks_not_run
    assert all(item.reason for item in report.checks_not_run)
    assert "7_cross_provider_reconciliation" in {item.check_name for item in report.checks_not_run}


def test_the_report_hash_ignores_when_the_checks_ran() -> None:
    """Two identical check runs are one report, whenever they happened."""
    first = phase3a.quality_report()
    later = report_from_findings(
        (),
        plan_version=first.plan_version,
        policy_versions=dict(first.policy_versions),
        checks_run=first.checks_run,
        checks_not_run=tuple(
            CheckNotRun(check_name=item.check_name, reason=item.reason)
            for item in first.checks_not_run
        ),
        datasets_covered=first.datasets_covered,
        partitions_covered=first.partitions_covered,
        produced_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert later.report_hash == first.report_hash


def test_the_report_hash_changes_with_a_finding() -> None:
    from kalpamani.data.contracts.vocabulary import QualitySeverity
    from kalpamani.data.quality.checks import QualityFinding

    warned = phase3a.quality_report(
        findings=(
            QualityFinding(
                check_name="5.2_non_positive_price_or_negative_volume",
                severity=QualitySeverity.WARNING,
                dataset="price_bar",
                detail="synthetic",
            ),
        )
    )
    assert warned.report_hash != phase3a.quality_report().report_hash
    assert warned.passed, "A warning does not block; it labels."


def test_a_publication_requires_a_quality_report() -> None:
    """There is no default and no empty fallback."""
    import inspect

    parameter = inspect.signature(publish_gold_dataset).parameters["quality_report"]
    assert parameter.default is inspect.Parameter.empty
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_a_reader_takes_no_issue_list_at_all() -> None:
    """A caller cannot obtain a clean reader by omitting evidence."""
    import inspect

    from kalpamani.data.curate.publication import VerifiedPublication
    from kalpamani.data.pit.accessors import PointInTimeReader

    parameters = inspect.signature(PointInTimeReader.__init__).parameters
    assert "open_issues" not in parameters
    assert "quality_report" not in parameters, (
        "The report is no longer a separate argument -- passing it beside a dataset and a "
        "manifest is exactly the hand-assembled triplet the reader must not accept."
    )
    assert parameters["publication"].annotation in {
        VerifiedPublication,
        "VerifiedPublication",
    }
    assert parameters["publication"].default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# Universe semantics
# ---------------------------------------------------------------------------


def _inputs(**overrides: object) -> UniverseBuildInputs:
    base: dict[str, object] = {
        "listings": phase3a.listings(),
        "attributes": phase3a.attributes(),
        "bars": phase3a.bars(),
    }
    base.update(overrides)
    return UniverseBuildInputs(**base)  # type: ignore[arg-type]


def _build(inputs: UniverseBuildInputs) -> object:
    return build_universe_snapshot(
        inputs,
        session_date=date(2019, 6, 27),
        evaluation_cutoff=phase3a.session_open(date(2019, 6, 27)),
        definition=phase3a.universe_definition(),
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
        artifact_first_built_time=phase3a.ARTIFACT_FIRST_BUILT,
        ingestion_time=phase3a.INGESTION_TIME,
        dataset_version=phase3a.DATASET_VERSION,
    )


def test_a_required_domain_never_supplied_is_as_unavailable_as_one_emptied() -> None:
    """Both cases refuse. Checking only the second lets an absent table look answered."""
    with pytest.raises(RequiredInputUnavailableError, match="supplied=0"):
        _build(_inputs(attributes=()))


def test_missing_security_type_is_not_mislabelled_as_the_wrong_type() -> None:
    """Absent evidence is not evidence of the wrong type.

    Labelling it ``SECURITY_TYPE`` would publish "this is not a common stock" as
    a finding when the truth is that nothing said what it is.
    """
    partial = tuple(
        attribute
        for attribute in phase3a.attributes()
        if not (
            attribute.attribute == "security_type"
            and attribute.security_id == phase3a.SEC_CONTINUOUS
        )
    )
    with pytest.raises(RequiredInputUnavailableError, match="no admissible security_type"):
        _build(_inputs(attributes=partial))


def test_overlapping_attribute_evidence_is_refused() -> None:
    """Resolving contradiction by iteration order would make membership table-order dependent."""
    original = next(
        attribute
        for attribute in phase3a.attributes()
        if attribute.attribute == "security_type"
        and attribute.security_id == phase3a.SEC_CONTINUOUS
    )
    duplicate = type(original)(
        security_id=original.security_id,
        attribute=original.attribute,
        valid_from=date(2015, 6, 1),
        value="PREFERRED",
        envelope=original.envelope,
    )
    with pytest.raises(RequiredInputUnavailableError, match="in force"):
        _build(_inputs(attributes=(*phase3a.attributes(), duplicate)))


def test_contradictory_listing_revisions_are_refused() -> None:
    """Two different rows at one revision have no later revision to supersede them."""
    original = next(listing for listing in phase3a.listings() if listing.listing_id == "LST-0001")
    contradictory = type(original)(
        listing_id=original.listing_id,
        security_id=original.security_id,
        exchange=original.exchange,
        listing_start=date(2016, 1, 4),
        listing_end=None,
        delisting_reason=None,
        listing_fact_kind=original.listing_fact_kind,
        envelope=original.envelope,
    )
    with pytest.raises(RequiredInputUnavailableError, match="Contradictory evidence"):
        current_listings((*phase3a.listings(), contradictory))


def test_an_announcement_is_not_a_listing_state() -> None:
    """An announced future delisting must not decide today's membership."""
    rows = phase3a.universe_snapshots()[date(2019, 6, 27)]
    assert phase3a.SEC_DELISTED in {row.security_id for row in rows}, (
        "The security is listed on this session; only its CHANGE_ANNOUNCEMENT says otherwise, "
        "and an announcement is not a state."
    )


def test_a_snapshot_header_records_a_session_that_was_built() -> None:
    dataset = phase3a.gold_dataset()
    for session in phase3a.SNAPSHOT_SESSIONS:
        header = dataset.universe_headers[session]
        assert header.status == "COMPLETE"
        assert header.row_count == len(dataset.universe[session])
        assert header.resolved_profile is dataset.resolved_profile
        assert header.evaluation_cutoff == phase3a.session_open(session)


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


def test_a_hostile_dataset_version_never_reaches_the_filesystem(tmp_path: Path) -> None:
    from kalpamani.data.contracts.vocabulary import StorageLayer

    store = LocalTableStore(tmp_path)
    for hostile in ("../escape", "/absolute", "gold/../escape"):
        with pytest.raises(UnsafePathComponentError):
            store.version_root(layer=StorageLayer.GOLD, dataset_version=hostile)


def test_a_hostile_entity_never_reaches_the_filesystem(tmp_path: Path) -> None:
    from kalpamani.data.contracts.vocabulary import StorageLayer

    store = LocalTableStore(tmp_path)
    with pytest.raises(UnsafePathComponentError):
        store.table_path(layer=StorageLayer.GOLD, dataset_version="gold/v1", entity="../escape")


# ---------------------------------------------------------------------------
# Publication identity
# ---------------------------------------------------------------------------


def _publish_variant(store: LocalTableStore, dataset: GoldDataset) -> str:
    _, manifest = publish_gold_dataset(
        store,
        dataset,
        quality_report=phase3a.quality_report(),
        quality_plan=PHASE3A_QUALITY_PLAN,
        code_commit_sha=phase3a.CODE_COMMIT_SHA,
        lag_policy_version=phase3a.LAG_POLICY_VERSION,
        universe_definition_version=phase3a.UNIVERSE_DEFINITION_VERSION,
    )
    return manifest.manifest_hash


def test_coverage_profile_and_policy_all_change_publication_identity(tmp_path: Path) -> None:
    """Two manifests differing in any of them cannot share a dataset identity."""
    baseline = phase3a.gold_dataset()
    baseline_hash = _publish_variant(LocalTableStore(tmp_path / "base"), baseline)

    narrower = GoldDataset(
        dataset_version=baseline.dataset_version,
        build_time=baseline.build_time,
        coverage_start=baseline.coverage_start,
        coverage_end=date(2020, 12, 31),
        resolved_profile=baseline.resolved_profile,
        resolution_policy_version=baseline.resolution_policy_version,
        resolution_receipt=baseline.resolution_receipt,
        resolution_evidence=baseline.resolution_evidence,
        sessions=baseline.sessions,
        listings=baseline.listings,
        attributes=baseline.attributes,
        tickers=baseline.tickers,
        bars=baseline.bars,
        actions=baseline.actions,
        universe=baseline.universe,
        universe_headers=baseline.universe_headers,
    )
    assert _publish_variant(LocalTableStore(tmp_path / "narrow"), narrower) != baseline_hash

    downgraded = phase3a.gold_dataset(
        requested=PROVIDER_REALISTIC, downgrade=GlobalProfileResolution.DOWNGRADE
    )
    assert _publish_variant(LocalTableStore(tmp_path / "down"), downgraded) != baseline_hash


def test_a_quality_report_change_changes_publication_identity(tmp_path: Path) -> None:
    """The evidence is part of what a published dataset is."""
    from kalpamani.data.contracts.vocabulary import QualitySeverity
    from kalpamani.data.quality.checks import QualityFinding

    dataset = phase3a.gold_dataset()
    plain = _publish_variant(LocalTableStore(tmp_path / "plain"), dataset)

    _, warned_manifest = publish_gold_dataset(
        LocalTableStore(tmp_path / "warned"),
        dataset,
        quality_report=phase3a.quality_report(
            findings=(
                QualityFinding(
                    check_name="5.2_non_positive_price_or_negative_volume",
                    severity=QualitySeverity.WARNING,
                    dataset="price_bar",
                    detail="synthetic",
                ),
            )
        ),
        quality_plan=PHASE3A_QUALITY_PLAN,
        code_commit_sha=phase3a.CODE_COMMIT_SHA,
        lag_policy_version=phase3a.LAG_POLICY_VERSION,
        universe_definition_version=phase3a.UNIVERSE_DEFINITION_VERSION,
    )
    assert warned_manifest.manifest_hash != plain


def test_a_row_count_that_does_not_match_the_table_is_refused(tmp_path: Path) -> None:
    """A count that does not match what is there makes completeness unfalsifiable."""
    from kalpamani.data.contracts.vocabulary import StorageLayer
    from kalpamani.data.curate.publication import read_published_dataset

    store = LocalTableStore(tmp_path)
    dataset = phase3a.gold_dataset()
    publish_gold_dataset(
        store,
        dataset,
        quality_report=phase3a.quality_report(),
        quality_plan=PHASE3A_QUALITY_PLAN,
        code_commit_sha=phase3a.CODE_COMMIT_SHA,
        lag_policy_version=phase3a.LAG_POLICY_VERSION,
        universe_definition_version=phase3a.UNIVERSE_DEFINITION_VERSION,
    )
    path = store.table_path(
        layer=StorageLayer.GOLD, dataset_version=dataset.dataset_version, entity="price_bar"
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

    with pytest.raises(DatasetPublicationError, match="hashes to"):
        read_published_dataset(
            store,
            dataset_version=dataset.dataset_version,
            config=phase3a.resolution(),
            approvals=phase3a.approvals(),
        )


def test_a_quality_report_is_required_for_a_reader(tmp_path: Path) -> None:
    """The three come back together, and the reader will not take two of them."""
    store = LocalTableStore(tmp_path)
    publication = phase3a.publish(store)
    dataset, manifest, report = (
        publication.dataset,
        publication.manifest,
        publication.quality_report,
    )
    assert isinstance(report, QualityReport)
    assert manifest.quality_report_hash == report.report_hash
    assert dataset.resolution_receipt.resolved_profile is manifest.resolved_profile
