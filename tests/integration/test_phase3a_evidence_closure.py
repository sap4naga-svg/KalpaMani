"""Evidence closure: the routes by which a valid-looking result could still be obtained.

Earlier rounds made the contract enforceable. This one closes the gaps where the
enforcement checked something *adjacent* to the claim rather than the claim
itself -- a fingerprint over names rather than contents, a receipt reconstructed
from empty tuples, a key that two different artifacts could share, a "repair"
inferred from circumstance.

Each test here corresponds to a way the previous code would have said yes.
"""

from __future__ import annotations

import dataclasses
import gzip
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.dataset import GoldDataset, UniverseSnapshotHeader
from kalpamani.data.contracts.envelope import DerivedEnvelope, LineageRef
from kalpamani.data.contracts.errors import (
    AcquisitionIncompleteError,
    ArtifactIntegrityError,
    BuildBoundaryError,
    DatasetPublicationError,
    EnvelopeError,
    IncompleteCoverageError,
    MissingHistoricalSnapshotError,
    QualityGateError,
    QueryRangeError,
    UnsafePathComponentError,
)
from kalpamani.data.contracts.manifest import InputInventory, emit_manifest, inventory_for
from kalpamani.data.contracts.paths import (
    internal_filename,
    safe_component,
    safe_relative_path,
)
from kalpamani.data.contracts.profiles import (
    DatasetResolutionEvidence,
    TimingBasis,
    map_evidence_disagreements,
)
from kalpamani.data.contracts.row_identity import row_fingerprint, source_row_identity
from kalpamani.data.contracts.vocabulary import (
    RAW,
    AdjustmentMode,
    AdjustmentPolicy,
    BarResolution,
    DatasetGapPolicy,
    Exchange,
    InformationSetProfile,
    ListingFactKind,
    OutputValidity,
    RevisionView,
    StorageLayer,
)
from kalpamani.data.curate.adjustment import (
    ADJUSTMENT_CONVENTION,
    action_lineage_hash,
    artifact_id_for,
    artifact_key,
    bar_lineage_hash,
    build_adjusted_bar_artifact,
    source_versions,
    verify_adjusted_bar_artifact,
)
from kalpamani.data.curate.build import build_gold_dataset
from kalpamani.data.curate.lineage import (
    NEGATIVE_COVERAGE_ENTITY,
    attribute_selector,
    bar_lineage_refs,
    bar_selector,
    listing_selector,
    resolve_lineage,
)
from kalpamani.data.curate.publication import (
    GOLD_ENTITIES,
    MANIFEST_NAME,
    VerifiedPublication,
    compute_manifest_hash,
    publish_gold_dataset,
    read_published_dataset,
    verification_seal,
)
from kalpamani.data.curate.resolution_run import resolve_run_inputs
from kalpamani.data.curate.universe import build_snapshot_header, current_listings
from kalpamani.data.ingest.bronze import (
    ACQUISITION_COMPLETE,
    ACQUISITION_PENDING,
    BronzeStore,
    RetrievalMetadata,
)
from kalpamani.data.pit.accessors import PointInTimeReader
from kalpamani.data.pit.query import PriceQuerySpec, SeriesRequirement
from kalpamani.data.quality.checks import check_universe_snapshots, subsequently_delisted
from kalpamani.data.quality.plan import PHASE3A_QUALITY_PLAN, CheckRequirement, plan_for
from kalpamani.data.quality.report import CheckNotRun, report_from_findings
from kalpamani.data.quality.runner import QUALITY_RUNNER_VERSION
from kalpamani.data.storage import LocalTableStore

PUBLIC = InformationSetProfile.PUBLIC_PIT
FORWARD = InformationSetProfile.FORWARD_SYSTEM
INGEST_DATE = date(2026, 8, 26)


def _subject() -> str:
    """The identity of the reference build a hand-written report claims to describe."""
    return phase3a.gold_dataset().build_identity


_SUBJECT = _subject()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rebuild(dataset: GoldDataset, **overrides: Any) -> GoldDataset:
    """The same build with some part of it swapped, bypassing the sanctioned path.

    Which is the whole point: publication has to catch what a caller could do to a
    build after resolution saw it.
    """
    base: dict[str, Any] = {
        "dataset_version": dataset.dataset_version,
        "build_time": dataset.build_time,
        "coverage_start": dataset.coverage_start,
        "coverage_end": dataset.coverage_end,
        "resolved_profile": dataset.resolved_profile,
        "resolution_policy_version": dataset.resolution_policy_version,
        "resolution_receipt": dataset.resolution_receipt,
        "resolution_evidence": dataset.resolution_evidence,
        "sessions": dataset.sessions,
        "listings": dataset.listings,
        "attributes": dataset.attributes,
        "tickers": dataset.tickers,
        "bars": dataset.bars,
        "actions": dataset.actions,
        "universe": dataset.universe,
        "universe_headers": dataset.universe_headers,
    }
    base.update(overrides)
    return GoldDataset(**base)


def _publish(store: LocalTableStore, dataset: GoldDataset, **kwargs: Any) -> Any:
    return publish_gold_dataset(
        store,
        dataset,
        quality=kwargs.pop("quality", phase3a.quality_outcome(dataset)),
        quality_plan=kwargs.pop("quality_plan", PHASE3A_QUALITY_PLAN),
        code_commit_sha=phase3a.CODE_COMMIT_SHA,
        lag_policy_version=phase3a.LAG_POLICY_VERSION,
        universe_definition_version=phase3a.UNIVERSE_DEFINITION_VERSION,
        source_ingestion_run_ids=(phase3a.INGESTION_RUN_ID,),
        **kwargs,
    )


def _substituted_bar(dataset: GoldDataset, **changes: Any) -> tuple[Any, ...]:
    """The build's bars with the first daily bar altered, identifiers untouched."""
    target = next(bar for bar in dataset.bars if bar.resolution is BarResolution.DAILY)
    replaced = dataclasses.replace(target, **changes)
    return tuple(replaced if bar is target else bar for bar in dataset.bars)


# ---------------------------------------------------------------------------
# 1 -- the receipt is bound to row contents, not to row names
# ---------------------------------------------------------------------------


def test_a_row_identity_carries_its_contents_not_only_its_names() -> None:
    """Two rows sharing every identifier but differing in value are two identities."""
    bar = next(b for b in phase3a.daily_bars())
    corrected = dataclasses.replace(bar, close=bar.close + Decimal("1.00"))

    original = source_row_identity(bar)
    changed = source_row_identity(corrected)
    assert original[:6] == changed[:6], "Every name is identical."
    assert original[6] != changed[6], "And the content hash is not."


def test_a_substituted_price_under_the_same_source_id_is_refused(tmp_path: Path) -> None:
    """The substitution a name-only fingerprint could not see."""
    dataset = phase3a.gold_dataset()
    tampered = _rebuild(dataset, bars=_substituted_bar(dataset, close=Decimal("999.99")))

    assert len(row_fingerprint(tampered.bars)) == len(row_fingerprint(dataset.bars))
    with pytest.raises(BuildBoundaryError, match="a row's contents differ"):
        _publish(LocalTableStore(tmp_path), tampered)


def test_a_changed_availability_time_under_the_same_source_id_is_refused(
    tmp_path: Path,
) -> None:
    """A timing substitution is a substitution. It moves what a query may see."""
    dataset = phase3a.gold_dataset()
    target = next(bar for bar in dataset.bars if bar.resolution is BarResolution.DAILY)
    supplied = target.envelope.provider_available_time
    assert supplied is not None, "The fixture's daily bars carry an exact provider time."
    envelope = dataclasses.replace(
        target.envelope, provider_available_time=supplied - timedelta(days=1)
    )
    tampered = _rebuild(dataset, bars=_substituted_bar(dataset, envelope=envelope))

    with pytest.raises(BuildBoundaryError, match="a row's contents differ"):
        _publish(LocalTableStore(tmp_path), tampered)


def test_a_row_from_a_different_source_version_is_refused(tmp_path: Path) -> None:
    """A matching key from another build is not the row resolution admitted."""
    dataset = phase3a.gold_dataset()
    target = next(bar for bar in dataset.bars if bar.resolution is BarResolution.DAILY)
    envelope = dataclasses.replace(target.envelope, dataset_version="gold/synthetic.a1.2")
    tampered = _rebuild(dataset, bars=_substituted_bar(dataset, envelope=envelope))

    with pytest.raises(BuildBoundaryError, match="a row's contents differ"):
        _publish(LocalTableStore(tmp_path), tampered)


def test_evidence_swapped_after_resolution_is_refused(tmp_path: Path) -> None:
    """The counts the receipt was taken over are part of what it attests."""
    dataset = phase3a.gold_dataset()
    first, *rest = dataset.resolution_evidence
    swapped = dataclasses.replace(first, reason="a different stated reason")
    tampered = _rebuild(dataset, resolution_evidence=(swapped, *rest))

    with pytest.raises(BuildBoundaryError, match="evidence fingerprint differs"):
        _publish(LocalTableStore(tmp_path), tampered)


def test_evidence_whose_policy_contradicts_the_map_is_refused(tmp_path: Path) -> None:
    """The map says what a run decided; the evidence says what it did."""
    dataset = phase3a.gold_dataset()
    declared = {entry[0]: entry for entry in dataset.resolution_receipt.canonical_map}
    bound = next(entry for entry in dataset.resolution_evidence if entry.dataset in declared)
    other_policy = next(
        entry.policy for entry in dataset.resolution_evidence if entry.policy is not bound.policy
    )
    contradicted = dataclasses.replace(bound, policy=other_policy)

    problems = map_evidence_disagreements(dataset.resolution_receipt.canonical_map, (contradicted,))
    assert any("evidenced under" in problem for problem in problems)

    tampered = _rebuild(
        dataset,
        resolution_evidence=tuple(
            contradicted if entry is bound else entry for entry in dataset.resolution_evidence
        ),
    )
    with pytest.raises(BuildBoundaryError, match="evidenced under"):
        _publish(LocalTableStore(tmp_path), tampered)


def test_a_tampered_receipt_hash_in_the_manifest_is_refused(tmp_path: Path) -> None:
    """The read recomputes the receipt; it does not reconstruct an agreeable one.

    The earlier read path rebuilt the receipt with empty fingerprints, so the
    recorded hash could only ever agree with itself.
    """
    store = LocalTableStore(tmp_path)
    _publish(store, phase3a.gold_dataset())
    path = (
        store.version_root(layer=StorageLayer.GOLD, dataset_version=phase3a.DATASET_VERSION)
        / MANIFEST_NAME
    )
    body = json.loads(path.read_text(encoding="utf-8"))
    body["resolution_receipt_hash"] = "sha256:" + "0" * 64
    path.write_text(json.dumps(body), encoding="utf-8")

    with pytest.raises(DatasetPublicationError, match="does not reconcile with its own hash"):
        read_published_dataset(
            store,
            dataset_version=phase3a.DATASET_VERSION,
            config=phase3a.resolution(),
            approvals=phase3a.approvals(),
        )


def test_a_receipt_hash_tampered_with_a_recomputed_manifest_is_still_refused(
    tmp_path: Path,
) -> None:
    """Repairing the manifest hash does not repair the claim it covers."""
    store = LocalTableStore(tmp_path)
    _, manifest = _publish(store, phase3a.gold_dataset())
    forged = dataclasses.replace(
        manifest, resolution_receipt_hash="sha256:" + "0" * 64, manifest_hash=""
    )
    forged = dataclasses.replace(forged, manifest_hash=compute_manifest_hash(forged))

    path = (
        store.version_root(layer=StorageLayer.GOLD, dataset_version=phase3a.DATASET_VERSION)
        / MANIFEST_NAME
    )
    body = json.loads(path.read_text(encoding="utf-8"))
    body["resolution_receipt_hash"] = forged.resolution_receipt_hash
    body["manifest_hash"] = forged.manifest_hash
    path.write_text(json.dumps(body), encoding="utf-8")

    with pytest.raises(DatasetPublicationError, match="does not recompute its resolution receipt"):
        read_published_dataset(
            store,
            dataset_version=phase3a.DATASET_VERSION,
            config=phase3a.resolution(),
            approvals=phase3a.approvals(),
        )


# ---------------------------------------------------------------------------
# 2 -- lineage names the version a row came from
# ---------------------------------------------------------------------------


def test_a_history_spanning_four_source_versions_produces_four_references() -> None:
    """A single reference would look for every endpoint in one version."""
    bars = phase3a.daily_bars()[:4]
    versioned = tuple(
        dataclasses.replace(
            bar, envelope=dataclasses.replace(bar.envelope, dataset_version=f"gold/source.{index}")
        )
        for index, bar in enumerate(bars)
    )
    refs = bar_lineage_refs(versioned[0].security_id, BarResolution.DAILY, versioned)
    assert len(refs) == 4
    assert {ref.dataset_version for ref in refs} == {f"gold/source.{i}" for i in range(4)}


# ---------------------------------------------------------------------------
# 6 -- dataset_version selects the candidate; it is not checked afterwards
# ---------------------------------------------------------------------------

_OTHER_VERSION = "gold/synthetic.a1.2"


def _in_other_version(rows: tuple[Any, ...]) -> tuple[Any, ...]:
    """The same rows as they would appear in a second immutable build."""
    return tuple(
        dataclasses.replace(
            row, envelope=dataclasses.replace(row.envelope, dataset_version=_OTHER_VERSION)
        )
        for row in rows
    )


def _replay(
    ref: LineageRef,
    *,
    listings: tuple[Any, ...] = (),
    attributes: tuple[Any, ...] = (),
    bars: tuple[Any, ...] = (),
) -> tuple[Any, ...]:
    return resolve_lineage(
        (ref,),
        listings=listings,
        attributes=attributes,
        bars=bars,
        resolved_profile=PUBLIC,
        approvals=phase3a.approvals(),
    )


def test_the_same_listing_key_in_two_versions_resolves_the_named_one() -> None:
    """Matching on the key alone found both and refused as ambiguous."""
    listing = phase3a.listings()[0]
    both = (*phase3a.listings(), *_in_other_version(phase3a.listings()))
    ref = LineageRef.of(
        entity="listing",
        dataset_version=phase3a.LISTING_DATASET_VERSION,
        selector=listing_selector(listing),
    )
    resolved = _replay(ref, listings=both)
    assert len(resolved) == 1
    assert resolved[0].envelope.dataset_version == phase3a.LISTING_DATASET_VERSION

    later = LineageRef.of(
        entity="listing", dataset_version=_OTHER_VERSION, selector=listing_selector(listing)
    )
    assert _replay(later, listings=both)[0].envelope.dataset_version == _OTHER_VERSION


def test_the_same_attribute_key_in_two_versions_resolves_the_named_one() -> None:
    attribute = phase3a.attributes()[0]
    both = (*phase3a.attributes(), *_in_other_version(phase3a.attributes()))
    ref = LineageRef.of(
        entity="security_attribute",
        dataset_version=_OTHER_VERSION,
        selector=attribute_selector(attribute),
    )
    resolved = _replay(ref, attributes=both)
    assert len(resolved) == 1
    assert resolved[0].envelope.dataset_version == _OTHER_VERSION


def test_the_same_bar_endpoint_in_two_versions_resolves_the_named_one() -> None:
    """A corrected price in a later build is not the bar the artifact read."""
    bars = tuple(bar for bar in phase3a.daily_bars() if bar.security_id == phase3a.SEC_CONTINUOUS)
    corrected = tuple(
        dataclasses.replace(bar, close=bar.close + Decimal("5.00"))
        for bar in _in_other_version(bars)
    )
    both = (*bars, *corrected)
    ref = LineageRef.of(
        entity="price_bar",
        dataset_version=phase3a.BAR_DATASET_VERSION,
        selector=bar_selector(phase3a.SEC_CONTINUOUS, BarResolution.DAILY, bars),
    )
    resolved = _replay(ref, bars=both)
    assert len(resolved) == len(bars)
    assert {row.envelope.dataset_version for row in resolved} == {phase3a.BAR_DATASET_VERSION}
    assert [row.close for row in resolved] == [bar.close for bar in bars]


def test_a_duplicate_within_the_named_version_is_still_refused() -> None:
    """Version scoping narrows the search; it does not excuse an ambiguous key."""
    bars = tuple(bar for bar in phase3a.daily_bars() if bar.security_id == phase3a.SEC_CONTINUOUS)[
        :1
    ]
    ref = LineageRef.of(
        entity="price_bar",
        dataset_version=phase3a.BAR_DATASET_VERSION,
        selector=bar_selector(phase3a.SEC_CONTINUOUS, BarResolution.DAILY, bars),
    )
    with pytest.raises(ArtifactIntegrityError, match="within dataset version"):
        _replay(ref, bars=(*bars, *bars))


def test_a_key_present_only_in_another_version_is_refused() -> None:
    """ "Absent from the named build" is a different finding from "absent"."""
    listing = phase3a.listings()[0]
    ref = LineageRef.of(
        entity="listing",
        dataset_version=phase3a.LISTING_DATASET_VERSION,
        selector=listing_selector(listing),
    )
    with pytest.raises(ArtifactIntegrityError, match="in dataset version"):
        _replay(ref, listings=_in_other_version(phase3a.listings()))


# ---------------------------------------------------------------------------
# 7 -- an absence is proved, not asserted
# ---------------------------------------------------------------------------

#: A window that contains SEC-0001's 2019-06-24 bar, for the absence tests below.
_ABSENCE_WINDOW = (phase3a.utc(2019, 6, 20), phase3a.utc(2019, 6, 25, 13, 30))


def _absence_ref(
    security_id: str,
    *,
    window: tuple[datetime, datetime] = _ABSENCE_WINDOW,
    versions: tuple[str, ...] = (phase3a.BAR_DATASET_VERSION,),
    profile: InformationSetProfile = PUBLIC,
) -> LineageRef:
    refs = bar_lineage_refs(
        security_id,
        BarResolution.DAILY,
        (),
        absence_window=window,
        absence_versions=versions,
        absence_profile=profile,
    )
    assert len(refs) == 1
    return refs[0]


def _replay_absence(
    ref: LineageRef,
    *,
    bars: tuple[Any, ...] | None = None,
    profile: InformationSetProfile = PUBLIC,
) -> None:
    resolve_lineage(
        (ref,),
        listings=(),
        attributes=(),
        bars=phase3a.bars() if bars is None else bars,
        resolved_profile=profile,
        approvals=phase3a.approvals(),
    )


def test_an_empty_history_is_recorded_as_a_governed_absence() -> None:
    """ "No prior bars" is a claim about a window, a build and a profile."""
    ref = _absence_ref("SEC-NOBODY")
    assert ref.entity == NEGATIVE_COVERAGE_ENTITY
    assert ref.dataset_version == phase3a.BAR_DATASET_VERSION
    selector = dict(ref.selector)
    assert selector["window_start"] == _ABSENCE_WINDOW[0].isoformat()
    assert selector["window_end"] == _ABSENCE_WINDOW[1].isoformat()
    assert selector["resolved_profile"] == PUBLIC.value


def test_a_no_history_claim_with_no_window_is_refused() -> None:
    """The sentinel it replaces resolved to nothing whatever the store held."""
    with pytest.raises(ArtifactIntegrityError, match="unfalsifiable in both directions"):
        bar_lineage_refs("SEC-NOBODY", BarResolution.DAILY, ())


def test_a_genuine_absence_replays() -> None:
    """NEGATIVE CONTROL. A security the fixture has no bars for."""
    _replay_absence(_absence_ref("SEC-NOBODY"))


def test_a_bar_inside_the_governed_window_refuses_the_absence() -> None:
    """The decision was made on the belief that this security had no usable history."""
    ref = _absence_ref(phase3a.SEC_CONTINUOUS)
    with pytest.raises(ArtifactIntegrityError, match="says no DAILY bar was admissible"):
        _replay_absence(ref)


def test_a_bar_outside_the_governed_window_does_not_invalidate_the_absence() -> None:
    """The window is what the decision looked at; a later bar says nothing about it."""
    _replay_absence(
        _absence_ref(
            phase3a.SEC_CONTINUOUS,
            window=(phase3a.utc(2019, 6, 1), phase3a.utc(2019, 6, 20)),
        )
    )


def test_the_same_absence_against_another_publication_refuses() -> None:
    """An absence is a fact about particular builds, not about the world."""
    ref = _absence_ref("SEC-NOBODY", versions=("gold/some-other-build.1",))
    other = tuple(
        dataclasses.replace(
            bar,
            security_id="SEC-NOBODY",
            envelope=dataclasses.replace(bar.envelope, dataset_version="gold/some-other-build.1"),
        )
        for bar in phase3a.daily_bars()
        if bar.security_id == phase3a.SEC_CONTINUOUS
    )
    with pytest.raises(ArtifactIntegrityError, match="says no DAILY bar was admissible"):
        _replay_absence(ref, bars=other)


def test_a_bar_the_profile_could_not_use_does_not_invalidate_the_absence() -> None:
    """A PROVIDER_DERIVED bar was never history a PUBLIC_PIT decision could use.

    This is the case that made the first version of the check wrong: it searched
    every stored row, so a correct build was refused for a bar the rule could not
    have seen.
    """
    reuser_bars = tuple(
        bar for bar in phase3a.daily_bars() if bar.security_id == phase3a.SEC_TICKER_REUSER
    )
    assert reuser_bars, "The fixture's provider-aggregated security has bars."
    window = (phase3a.utc(2021, 1, 1), phase3a.utc(2021, 1, 5, 14, 30))
    _replay_absence(_absence_ref(phase3a.SEC_TICKER_REUSER, window=window))


def test_an_absence_replayed_under_another_profile_is_refused() -> None:
    """It would test a different claim than the one that was made."""
    ref = _absence_ref("SEC-NOBODY", profile=PUBLIC)
    with pytest.raises(ArtifactIntegrityError, match="is being replayed under"):
        _replay_absence(ref, profile=FORWARD)


def test_membership_lineage_never_names_the_gold_version_it_was_written_into() -> None:
    """A Gold build stores a copy of a row, and a copy does not become the source."""
    datasets = phase3a.source_datasets()
    renamed = {
        "listing": "gold/source-listing.7",
        "security_attribute": "gold/source-attribute.7",
        "price_bar": "gold/source-bar.7",
    }
    for name, version in renamed.items():
        datasets[name] = tuple(
            dataclasses.replace(
                row, envelope=dataclasses.replace(row.envelope, dataset_version=version)
            )
            for row in datasets[name]
        )
    resolved = resolve_run_inputs(
        datasets, config=phase3a.resolution(), approvals=phase3a.approvals()
    )
    dataset = build_gold_dataset(
        resolved,
        dataset_version="gold/final.7",
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

    versions = {
        ref.dataset_version
        for rows in dataset.universe.values()
        for row in rows
        for ref in row.envelope.lineage
    }
    assert "gold/final.7" not in versions, "The Gold version is not a source of anything."
    assert versions <= set(renamed.values())
    assert len(versions & set(renamed.values())) == 3, "All three source versions are named."


# ---------------------------------------------------------------------------
# 3 -- a verified publication cannot be assembled at a call site
# ---------------------------------------------------------------------------


def test_a_hand_assembled_triplet_cannot_become_a_verified_publication(tmp_path: Path) -> None:
    """Its hashes agree with each other, which is not agreeing with storage."""
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    with pytest.raises(DatasetPublicationError, match="only be produced by read_published_dataset"):
        VerifiedPublication(
            dataset=publication.dataset,
            manifest=publication.manifest,
            quality_report=publication.quality_report,
            verification_seal=publication.verification_seal,
            verified_by=object(),
        )


def test_the_verified_read_is_the_only_route_to_a_reader(tmp_path: Path) -> None:
    """And the seal it stamps names the artifacts the verification covered."""
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    assert isinstance(publication, VerifiedPublication)
    assert publication.verification_seal == verification_seal(
        publication.manifest, publication.quality_report, publication.dataset
    )
    assert publication.dataset_version == phase3a.DATASET_VERSION


# ---------------------------------------------------------------------------
# 4 -- the quality plan closes the report
# ---------------------------------------------------------------------------


def test_a_report_running_one_harmless_check_cannot_publish(tmp_path: Path) -> None:
    """A single check finding nothing looks exactly like a complete clean pass."""
    thin = report_from_findings(
        (),
        plan_version=PHASE3A_QUALITY_PLAN.plan_version,
        subject_build_identity=_SUBJECT,
        quality_context_hash="hand-authored, not a run",
        runner_version=QUALITY_RUNNER_VERSION,
        policy_versions={"lag": "x", "market": "y", "survivorship": "z"},
        checks_run=("5_market_data",),
        datasets_covered=phase3a.QUALITY_COVERAGE,
        produced_at=phase3a.BUILD_TIME,
    )
    with pytest.raises(QualityGateError, match="the plan expects checks"):
        PHASE3A_QUALITY_PLAN.validate(thin, published_tables=GOLD_ENTITIES)


def test_a_required_check_cannot_be_declared_away(tmp_path: Path) -> None:
    """NOT_RUN is permitted only where the plan says this slice cannot run it."""
    declared = report_from_findings(
        (),
        plan_version=PHASE3A_QUALITY_PLAN.plan_version,
        subject_build_identity=_SUBJECT,
        quality_context_hash="hand-authored, not a run",
        runner_version=QUALITY_RUNNER_VERSION,
        policy_versions={"lag": "x", "market": "y", "survivorship": "z"},
        checks_run=tuple(
            check.check_id
            for check in PHASE3A_QUALITY_PLAN.checks
            if check.requirement is CheckRequirement.REQUIRED
            and check.check_id != "6_identity_and_universe"
        ),
        checks_not_run=(
            CheckNotRun(check_name="6_identity_and_universe", reason="skipped for speed"),
            CheckNotRun(check_name="7_cross_provider_reconciliation", reason="one source only"),
        ),
        datasets_covered=phase3a.QUALITY_COVERAGE,
        produced_at=phase3a.BUILD_TIME,
    )
    with pytest.raises(QualityGateError, match="is REQUIRED and was declared not-run"):
        PHASE3A_QUALITY_PLAN.validate(declared, published_tables=GOLD_ENTITIES)


def test_a_published_table_nothing_covered_is_refused(tmp_path: Path) -> None:
    """A table nothing checked was published unchecked."""
    uncovered = report_from_findings(
        (),
        plan_version=PHASE3A_QUALITY_PLAN.plan_version,
        subject_build_identity=_SUBJECT,
        quality_context_hash="hand-authored, not a run",
        runner_version=QUALITY_RUNNER_VERSION,
        policy_versions={"lag": "x", "market": "y", "survivorship": "z"},
        checks_run=tuple(
            check.check_id
            for check in PHASE3A_QUALITY_PLAN.checks
            if check.requirement is CheckRequirement.REQUIRED
        ),
        checks_not_run=(
            CheckNotRun(check_name="7_cross_provider_reconciliation", reason="one source only"),
        ),
        datasets_covered=tuple(
            name for name in phase3a.QUALITY_COVERAGE if name != "universe_snapshot_header"
        ),
        produced_at=phase3a.BUILD_TIME,
    )
    with pytest.raises(QualityGateError, match="are not in datasets_covered"):
        PHASE3A_QUALITY_PLAN.validate(uncovered, published_tables=GOLD_ENTITIES)


def test_the_persisted_report_bytes_are_bound_to_the_manifest(tmp_path: Path) -> None:
    """The logical hash omits produced_at, so only the file hash covers the file."""
    store = LocalTableStore(tmp_path)
    _, manifest = _publish(store, phase3a.gold_dataset())
    assert manifest.quality_report_file_hash
    assert manifest.quality_report_file_hash != manifest.quality_report_hash
    assert manifest.quality_plan_version == PHASE3A_QUALITY_PLAN.plan_version


def test_a_publication_naming_an_unknown_plan_refuses_on_read() -> None:
    """Validating against the current plan would compare it to the wrong expectation."""
    with pytest.raises(QualityGateError, match="is unknown to this code"):
        plan_for("phase3a.quality-plan.from-the-future")


# ---------------------------------------------------------------------------
# 5 -- the snapshot header is a derived artifact
# ---------------------------------------------------------------------------


def _header(publication: VerifiedPublication, session: date) -> UniverseSnapshotHeader:
    return publication.dataset.universe_headers[session]


def test_a_snapshot_header_carries_lineage_and_an_identity(tmp_path: Path) -> None:
    """A zero-row snapshot was the one assertion with nothing behind it."""
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    header = _header(publication, date(2019, 6, 27))
    assert header.envelope.lineage, "It names what the build read."
    assert header.header_identity_hash
    assert header.is_complete
    assert header.envelope.artifact_content_hash == header.snapshot_content_hash


def test_a_header_whose_identity_was_edited_is_refused(tmp_path: Path) -> None:
    store = LocalTableStore(tmp_path)
    _publish(store, phase3a.gold_dataset())
    path = store.table_path(
        layer=StorageLayer.GOLD,
        dataset_version=phase3a.DATASET_VERSION,
        entity="universe_snapshot_header",
    )
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    rows[0]["row_count"] = rows[0]["row_count"] + 1
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8"
    )
    with pytest.raises(DatasetPublicationError, match="hashes to"):
        read_published_dataset(
            store,
            dataset_version=phase3a.DATASET_VERSION,
            config=phase3a.resolution(),
            approvals=phase3a.approvals(),
        )


def test_a_header_declaring_a_wider_validity_than_one_session_is_refused() -> None:
    """A universe snapshot governs exactly one session."""
    publication_free_header = phase3a.gold_dataset().universe_headers[date(2019, 6, 27)]
    envelope = dataclasses.replace(
        publication_free_header.envelope,
        validity=dataclasses.replace(
            publication_free_header.envelope.validity,
            output_validity=OutputValidity.INTERVAL,
        ),
    )
    with pytest.raises(EnvelopeError, match="validity"):
        dataclasses.replace(publication_free_header, envelope=envelope)


def test_a_header_that_miscounts_its_rows_is_refused(tmp_path: Path) -> None:
    """A zero-row snapshot is legitimate; a header that miscounts is not."""
    dataset = phase3a.gold_dataset()
    session = date(2019, 6, 27)
    universe = {key: () if key == session else rows for key, rows in dataset.universe.items()}
    store = LocalTableStore(tmp_path)
    _publish(store, _rebuild(dataset, universe=universe))
    with pytest.raises(DatasetPublicationError, match="rows and 0 were stored"):
        read_published_dataset(
            store,
            dataset_version=phase3a.DATASET_VERSION,
            config=phase3a.resolution(),
            approvals=phase3a.approvals(),
        )


def test_a_partial_header_is_never_published(tmp_path: Path) -> None:
    """A partial snapshot answers with a subset and nothing in the answer says so.

    Caught at publication now rather than on read: the rebuild reproduces the
    header's whole identity, and status is part of it. The read's own COMPLETE
    check remains as defence for a snapshot assembled by something other than this
    builder.
    """
    dataset = phase3a.gold_dataset()
    session = date(2019, 6, 27)
    header = dataset.universe_headers[session]
    partial = dataclasses.replace(header, status="PARTIAL")
    headers = {**dataset.universe_headers, session: partial}
    tampered = _rebuild(dataset, universe_headers=headers)
    with pytest.raises(QualityGateError, match=r"6\.5_universe_rebuild_drift"):
        _publish(LocalTableStore(tmp_path), tampered)


def test_a_zero_row_snapshot_is_not_served_before_it_was_built(tmp_path: Path) -> None:
    """Under FORWARD_SYSTEM we did not know the rule selected nobody. We knew nothing.

    The zero-row case is the one with no membership rows to carry the constraint,
    so before the header became a derived artifact this query was answered with an
    empty universe and nothing said it was an answer about the future.

    The snapshot is a genuine empty selection -- only the delisted security's
    listings are supplied, and the session is after it delisted -- rather than a
    published snapshot with its rows removed. That construction no longer survives
    publication at all: the quality runner rebuilds the snapshot and finds the
    drift.
    """
    publication = phase3a.zero_row_publication(LocalTableStore(tmp_path), requested=FORWARD)
    session = date(2021, 1, 5)
    header = publication.dataset.universe_headers[session]
    assert header.row_count == 0
    assert header.envelope.artifact_first_built_time == phase3a.ARTIFACT_FIRST_BUILT

    reader = PointInTimeReader(
        publication,
        resolution=phase3a.resolution(requested=FORWARD),
        approvals=phase3a.approvals(),
    )
    with pytest.raises(MissingHistoricalSnapshotError, match="first built at"):
        reader.get_security_universe(
            as_of=phase3a.ARTIFACT_FIRST_BUILT - timedelta(minutes=1), profile=FORWARD
        )


def test_the_same_zero_row_snapshot_is_a_real_answer_once_it_exists(
    tmp_path: Path,
) -> None:
    """NEGATIVE CONTROL. "Nobody qualified" is an answer, and it is served as one."""
    publication = phase3a.zero_row_publication(LocalTableStore(tmp_path), requested=FORWARD)
    reader = PointInTimeReader(
        publication,
        resolution=phase3a.resolution(requested=FORWARD),
        approvals=phase3a.approvals(),
    )
    result = reader.get_security_universe(as_of=phase3a.BUILD_TIME, profile=FORWARD).result
    assert result.session_date == date(2021, 1, 5)
    assert result.members == ()
    assert result.non_members == ()


def test_a_snapshot_with_no_listing_state_evidence_refuses() -> None:
    """ "We saw no listing states" is not the same finding as "nobody was listed"."""
    with pytest.raises(Exception, match="REQUIRED_INPUT_UNAVAILABLE"):
        build_snapshot_header(
            (),
            session_date=date(2019, 6, 27),
            definition=phase3a.universe_definition(),
            resolved_profile=PUBLIC,
            evaluation_cutoff=phase3a.session_open(date(2019, 6, 27)),
            considered_listings=(),
            artifact_first_built_time=phase3a.ARTIFACT_FIRST_BUILT,
            ingestion_time=phase3a.INGESTION_TIME,
            dataset_version=phase3a.DATASET_VERSION,
        )


# ---------------------------------------------------------------------------
# 6 -- the adjusted artifact key admits no collision
# ---------------------------------------------------------------------------

_SCOPE = phase3a.SEC_CONTINUOUS
_VALID_START = date(2019, 6, 24)
_VALID_END = date(2019, 6, 28)
_AS_OF = phase3a.utc(2019, 7, 1, 12, 0)


def _bars_for(security_id: str = _SCOPE) -> tuple[Any, ...]:
    return tuple(
        bar
        for bar in phase3a.daily_bars()
        if bar.security_id == security_id and _VALID_START <= bar.session_date <= _VALID_END
    )


def _artifact(**overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "adjustment_policy": AdjustmentPolicy.SPLIT_ONLY,
        "adjustment_convention": ADJUSTMENT_CONVENTION,
        "resolved_profile": PUBLIC,
        "as_of_epoch": _AS_OF,
        "approvals": phase3a.approvals(),
        "security_id_scope": _SCOPE,
        "valid_time_start": _VALID_START,
        "valid_time_end": _VALID_END,
        "artifact_first_built_time": phase3a.ARTIFACT_FIRST_BUILT,
        "ingestion_time": phase3a.INGESTION_TIME,
        "dataset_version": phase3a.DATASET_VERSION,
    }
    bars = overrides.pop("bars", _bars_for())
    kwargs.update(overrides)
    return build_adjusted_bar_artifact(bars, phase3a.corporate_actions(), **kwargs)


def test_two_intervals_over_the_same_versions_are_two_artifacts() -> None:
    """One month of a security and one year of it are not the same artifact."""
    whole = _artifact()
    shorter = _artifact(bars=_bars_for()[:3], valid_time_end=date(2019, 6, 26))
    assert whole.artifact_id != shorter.artifact_id


def test_two_bar_subsets_of_one_version_are_two_artifacts() -> None:
    """Dataset versions say which builds were read, not which rows."""
    full = _artifact()
    subset = _artifact(bars=_bars_for()[1:])
    assert full.artifact_id != subset.artifact_id
    assert bar_lineage_hash(_bars_for()) != bar_lineage_hash(_bars_for()[1:])


def test_the_bar_resolution_is_part_of_the_key() -> None:
    """A daily series and a minute series over one span are different numbers."""

    def identity(resolution: BarResolution) -> str:
        return artifact_id_for(
            artifact_key(
                adjustment_policy=AdjustmentPolicy.SPLIT_ONLY,
                adjustment_convention=ADJUSTMENT_CONVENTION,
                resolved_profile=PUBLIC,
                as_of_epoch=_AS_OF,
                corporate_action_dataset_versions=(),
                raw_bar_dataset_versions=source_versions(_bars_for()),
                security_id_scope=_SCOPE,
                bar_resolution=resolution,
                valid_time_start=_VALID_START,
                valid_time_end=_VALID_END,
                price_bar_lineage_hash=bar_lineage_hash(_bars_for()),
                action_lineage_hash=action_lineage_hash(()),
            )
        )

    assert identity(BarResolution.DAILY) != identity(BarResolution.MINUTE)


def test_artifact_lineage_names_endpoints_rather_than_a_range() -> None:
    """A predicate would re-evaluate whatever matches now."""
    artifact = _artifact()
    bar_refs = [ref for ref in artifact.envelope.lineage if ref.entity == "price_bar"]
    assert bar_refs
    for ref in bar_refs:
        assert set(dict(ref.selector)) == {"security_id", "resolution", "bar_end_times"}


def test_a_range_predicate_selector_is_refused_at_verification() -> None:
    """The shape the earlier lineage used, held to the rule it broke."""
    artifact = _artifact()
    predicate = LineageRef.of(
        entity="price_bar",
        dataset_version=phase3a.BAR_DATASET_VERSION,
        selector={"scope": _SCOPE, "sessions": "2019-06-24..2019-06-28"},
    )
    envelope = dataclasses.replace(artifact.envelope, lineage=(predicate,))
    with pytest.raises(ArtifactIntegrityError, match="missing"):
        verify_adjusted_bar_artifact(
            dataclasses.replace(artifact, envelope=envelope),
            _bars_for(),
            phase3a.corporate_actions(),
            approvals=phase3a.approvals(),
        )


def test_verification_recomputes_from_only_the_rows_the_lineage_names() -> None:
    """An artifact that reproduces from a different input set has not reproduced."""
    artifact = _artifact()
    verify_adjusted_bar_artifact(
        artifact,
        (*_bars_for(), *_bars_for(phase3a.SEC_DELISTED)),
        phase3a.corporate_actions(),
        approvals=phase3a.approvals(),
    )


def test_an_artifact_whose_identity_no_longer_follows_from_its_lineage_is_refused() -> None:
    artifact = _artifact()
    forged = dataclasses.replace(artifact, artifact_id="adj-0000000000000000")
    with pytest.raises(ArtifactIntegrityError, match="does not rebuild its own identity"):
        verify_adjusted_bar_artifact(
            forged, _bars_for(), phase3a.corporate_actions(), approvals=phase3a.approvals()
        )


# ---------------------------------------------------------------------------
# 7 -- Bronze acquisition state
# ---------------------------------------------------------------------------


def _retrieval(run_id: str = "ing-closure-0001") -> RetrievalMetadata:
    return RetrievalMetadata(
        provider="synthetic",
        dataset="price_bar",
        requested_range="2019-06-24..2019-06-28",
        retrieved_at=phase3a.INGESTION_TIME,
        source_schema_version="synthetic/1",
        ingestion_run_id=run_id,
    )


def test_a_second_run_over_existing_content_is_not_a_repair(tmp_path: Path) -> None:
    """Every second acquisition of unchanged data used to be logged as a recovery."""
    store = BronzeStore(tmp_path)
    payload = phase3a.bronze_payload()
    first = store.write(payload=payload, retrieval=_retrieval(), ingest_date=INGEST_DATE)
    assert (first.content_written, first.acquisition_written, first.repaired) == (
        True,
        True,
        False,
    )

    second = store.write(
        payload=payload, retrieval=_retrieval("ing-closure-0002"), ingest_date=INGEST_DATE
    )
    assert (second.content_written, second.acquisition_written, second.repaired) == (
        False,
        True,
        False,
    )


def test_completing_a_pending_acquisition_is_the_only_repair(tmp_path: Path) -> None:
    """Repair is a state on disk, not an inference from what happens to be missing."""
    store = BronzeStore(tmp_path)
    payload = phase3a.bronze_payload()
    artifact = store.write(payload=payload, retrieval=_retrieval(), ingest_date=INGEST_DATE)

    # Exactly the state a crash between the two writes leaves behind.
    body = json.loads(artifact.acquisition_path.read_text(encoding="utf-8"))
    body["status"] = ACQUISITION_PENDING
    artifact.acquisition_path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    artifact.path.unlink()

    repaired = store.write(payload=payload, retrieval=_retrieval(), ingest_date=INGEST_DATE)
    assert repaired.repaired is True
    assert repaired.content_written is True
    stored = json.loads(repaired.acquisition_path.read_text(encoding="utf-8"))
    assert stored["status"] == ACQUISITION_COMPLETE


def test_a_pending_acquisition_refuses_the_partition(tmp_path: Path) -> None:
    """An interrupted retrieval is finished by re-running it, not by ignoring it."""
    store = BronzeStore(tmp_path)
    artifact = store.write(
        payload=phase3a.bronze_payload(), retrieval=_retrieval(), ingest_date=INGEST_DATE
    )
    body = json.loads(artifact.acquisition_path.read_text(encoding="utf-8"))
    body["status"] = ACQUISITION_PENDING
    artifact.acquisition_path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")

    with pytest.raises(AcquisitionIncompleteError, match="still PENDING"):
        store.require_complete(provider="synthetic", dataset="price_bar", ingest_date=INGEST_DATE)


def test_an_acquisition_identity_is_globally_unique(tmp_path: Path) -> None:
    """Two partitions claiming one retrieval are two stories about when it arrived."""
    store = BronzeStore(tmp_path)
    payload = phase3a.bronze_payload()
    store.write(payload=payload, retrieval=_retrieval(), ingest_date=INGEST_DATE)

    with pytest.raises(AcquisitionIncompleteError, match="already recorded at"):
        store.write(payload=payload, retrieval=_retrieval(), ingest_date=date(2026, 8, 27))


def test_an_idempotent_rewrite_still_verifies_the_content(tmp_path: Path) -> None:
    """Returning early on a COMPLETE record would leave a replaced payload unexamined."""
    store = BronzeStore(tmp_path)
    payload = phase3a.bronze_payload()
    artifact = store.write(payload=payload, retrieval=_retrieval(), ingest_date=INGEST_DATE)
    artifact.path.write_bytes(gzip.compress(b'{"bars": []}', 9, mtime=0))

    with pytest.raises(Exception, match="already holds different bytes"):
        store.write(payload=payload, retrieval=_retrieval(), ingest_date=INGEST_DATE)


# ---------------------------------------------------------------------------
# 8 -- every filesystem name route
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "..",
        ".",
        "a/b",
        "a\\b",
        "CON",
        "con.json",
        "NUL",
        "com1",
        "COM9.txt",
        "lpt3",
        "trailing.",
        "trailing ",
        "_staging-x",
        ".tmp-x",
        "",
    ],
)
def test_a_hostile_path_component_is_refused(value: str) -> None:
    """Refused rather than sanitised: rewriting maps two identifiers onto one path."""
    with pytest.raises(UnsafePathComponentError):
        safe_component(value, kind="test value")


@pytest.mark.parametrize("value", ["/etc/passwd", "C:\\windows", "a//b", "gold/../escape"])
def test_a_hostile_relative_path_is_refused(value: str) -> None:
    with pytest.raises(UnsafePathComponentError):
        safe_relative_path(value, kind="dataset_version")


@pytest.mark.parametrize(
    "value",
    [
        "_dataset_manifest.json/../../escape",
        "_anything.json",
        "_dataset_manifest.jsonx",
        "dataset_manifest.json",
    ],
)
def test_an_internal_filename_outside_the_allowlist_is_refused(value: str) -> None:
    """A prefix rule would have waved the first of these straight through."""
    with pytest.raises(UnsafePathComponentError):
        internal_filename(value)


def test_staged_bytes_accept_only_this_packages_own_files(tmp_path: Path) -> None:
    store = LocalTableStore(tmp_path)
    with pytest.raises(UnsafePathComponentError):
        store.write_staged_bytes(
            layer=StorageLayer.GOLD,
            dataset_version="gold/x.1",
            name="_dataset_manifest.json/../../escape",
            payload=b"{}",
        )


# ---------------------------------------------------------------------------
# 9 -- the inventory is generated by execution
# ---------------------------------------------------------------------------


def test_the_input_inventory_is_produced_by_the_query_path(tmp_path: Path) -> None:
    """A dataset the query path did not record is a bug here, not a caller's choice."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    priced = reader.get_price_history(
        security_id=phase3a.SEC_CONTINUOUS,
        start=date(2019, 6, 24),
        end=date(2019, 6, 28),
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=phase3a.utc(2019, 7, 1, 12, 0),
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    )
    universe = reader.get_security_universe(as_of=phase3a.utc(2019, 6, 28, 12, 0), profile=PUBLIC)

    assert priced.evidence.direct_source_datasets == ("price_bar",)
    assert universe.evidence.direct_source_datasets == (), (
        "universe_membership is a derived artifact, not a source dataset. Recording it as one "
        "made the manifest demand provider-resolution evidence for a table nobody publishes "
        "resolution evidence about."
    )
    assert universe.evidence.consumed_artifact_ids, "The snapshot it read is an artifact."
    assert priced.evidence.consumed_artifact_ids == (), (
        "And a price query consumed none, which the price query's own evidence says -- it does "
        "not inherit the universe query's."
    )
    assert priced.quality_report_hash == reader.quality_report.report_hash

    inventory = inventory_for(priced)
    assert inventory.direct_source_datasets == priced.evidence.direct_source_datasets
    assert inventory.unapproved_bounds_relied_upon == ()


def test_a_raw_series_does_not_record_corporate_actions(tmp_path: Path) -> None:
    """A raw series does not consult them, so recording one would be a false read.

    It would also be self-defeating: every directly-read dataset must carry
    provider-resolution evidence, so a dataset the run never opened would have to
    be evidenced anyway.
    """
    reader = phase3a.reader(LocalTableStore(tmp_path))
    executed = reader.get_price_history(
        security_id=phase3a.SEC_CONTINUOUS,
        start=date(2019, 6, 24),
        end=date(2019, 6, 28),
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=phase3a.utc(2019, 7, 1, 12, 0),
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    )
    evidence = executed.evidence
    assert evidence.direct_source_datasets == ("price_bar",)
    assert evidence.revisable_datasets_consumed == ()


def test_an_adjusted_series_records_corporate_actions_and_a_revision_view(
    tmp_path: Path,
) -> None:
    """It does read them, and which revision it used is part of the answer."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    executed = reader.get_price_history(
        security_id=phase3a.SEC_CONTINUOUS,
        start=date(2019, 6, 24),
        end=date(2019, 6, 28),
        resolution=BarResolution.DAILY,
        adjustment_mode=AdjustmentMode.adjusted(AdjustmentPolicy.SPLIT_ONLY, ADJUSTMENT_CONVENTION),
        as_of=phase3a.utc(2019, 7, 1, 12, 0),
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=RevisionView.AS_KNOWN_AT_AS_OF,
    )
    evidence = executed.evidence
    assert set(evidence.direct_source_datasets) == {"price_bar", "corporate_action"}
    assert evidence.revisable_datasets_consumed == ("corporate_action",)
    assert executed.result.provenance.revision_view is RevisionView.AS_KNOWN_AT_AS_OF
    query = executed.query
    assert isinstance(query, PriceQuerySpec)
    assert query.revision_view is RevisionView.AS_KNOWN_AT_AS_OF


def test_an_adjusted_series_without_a_revision_view_is_refused(tmp_path: Path) -> None:
    """A restated ratio changes every adjusted number after its ex-date."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    with pytest.raises(QueryRangeError, match="must name its revision_view"):
        reader.get_price_history(
            security_id=phase3a.SEC_CONTINUOUS,
            start=date(2019, 6, 24),
            end=date(2019, 6, 28),
            resolution=BarResolution.DAILY,
            adjustment_mode=AdjustmentMode.adjusted(
                AdjustmentPolicy.SPLIT_ONLY, ADJUSTMENT_CONVENTION
            ),
            as_of=phase3a.utc(2019, 7, 1, 12, 0),
            profile=PUBLIC,
            requirement=SeriesRequirement.REQUIRED,
            revision_view=None,
        )


def test_a_raw_series_naming_a_revision_view_is_refused(tmp_path: Path) -> None:
    """It would report that the query honoured a view it never consulted."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    with pytest.raises(QueryRangeError, match="reads no corporate actions"):
        reader.get_price_history(
            security_id=phase3a.SEC_CONTINUOUS,
            start=date(2019, 6, 24),
            end=date(2019, 6, 28),
            resolution=BarResolution.DAILY,
            adjustment_mode=RAW,
            as_of=phase3a.utc(2019, 7, 1, 12, 0),
            profile=PUBLIC,
            requirement=SeriesRequirement.REQUIRED,
            revision_view=RevisionView.AS_KNOWN_AT_AS_OF,
        )


def test_the_result_hash_covers_the_exact_bytes(tmp_path: Path) -> None:
    """Decoding first made two different payloads that decode alike one identity."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    executed = reader.get_security_universe(as_of=phase3a.utc(2019, 6, 28, 12, 0), profile=PUBLIC)
    evidence = executed.evidence
    first = InputInventory.from_execution(evidence, result_bytes=b"\xff\xfe")
    second = InputInventory.from_execution(evidence, result_bytes=b"\xff\xfd")
    assert first.result_artifact_hash != second.result_artifact_hash


def test_emit_manifest_no_longer_accepts_a_side_channel() -> None:
    """The only party that could report an unapproved bound was the one hiding it."""
    import inspect

    parameters = inspect.signature(emit_manifest).parameters
    assert "unapproved_bounds_relied_upon" not in parameters
    assert "hash_mismatches" not in parameters
    assert set(parameters) == {"manifest", "result_bytes", "executed"}, (
        "`executed` is the sealed result the manifest is checked against -- the opposite of a "
        "side channel, since only the reader can produce one."
    )


# ---------------------------------------------------------------------------
# 10 -- honest evidence, and survivorship measured from the build
# ---------------------------------------------------------------------------


def _evidence(**overrides: Any) -> DatasetResolutionEvidence:
    base: dict[str, Any] = {
        "dataset": "price_bar",
        "policy": DatasetGapPolicy.NONE,
        "rows_considered": 4,
        "public_rows_applicable": 4,
        "public_basis": TimingBasis.NONE_RETAINED,
        "public_exact_rows": 0,
        "public_bounded_rows": 0,
        "public_excluded_rows": 4,
        "public_unresolved_rows": 0,
        "provider_rows_applicable": 0,
        "provider_basis": TimingBasis.NOT_APPLICABLE,
        "provider_exact_rows": 0,
        "provider_bounded_rows": 0,
        "provider_excluded_rows": 0,
        "provider_unresolved_rows": 0,
        "excluded_rows": 4,
        "reason": "synthetic",
    }
    base.update(overrides)
    return DatasetResolutionEvidence(**base)


def test_an_axis_with_nothing_retained_does_not_claim_exact_timing() -> None:
    """A manifest said the timing was exact on the strength of zero exact rows."""
    entry = _evidence()
    assert entry.public_basis is TimingBasis.NONE_RETAINED, (
        "Rows were applicable and none survived -- which is neither EXACT (a basis "
        "derived from nothing) nor NOT_APPLICABLE (no row on this axis existed)."
    )
    assert entry.public_rows_applicable > 0
    assert entry.public_exact_rows == 0


def test_a_manifest_claiming_exact_timing_with_no_exact_rows_is_refused(
    tmp_path: Path,
) -> None:
    dataset = phase3a.gold_dataset()
    first, *rest = dataset.resolution_evidence
    dishonest = dataclasses.replace(
        first,
        public_basis=TimingBasis.EXACT,
        public_exact_rows=0,
        public_bounded_rows=0,
        public_excluded_rows=first.public_rows_applicable,
        public_unresolved_rows=0,
    )
    store = LocalTableStore(tmp_path)
    tampered = _rebuild(dataset, resolution_evidence=(dishonest, *rest))
    with pytest.raises(BuildBoundaryError, match="evidence fingerprint differs"):
        _publish(store, tampered)


def test_survivorship_counts_only_delistings_after_the_snapshot() -> None:
    """A security already gone cannot be evidence that this snapshot's members left."""
    listings = phase3a.listings()
    after_delisting = subsequently_delisted(
        listings, after_session=date(2019, 6, 30), horizon=date(2030, 1, 1)
    )
    assert phase3a.SEC_DELISTED not in after_delisting, "It delisted on 2019-06-28."
    assert phase3a.SEC_RENAMED in after_delisting, "Its 2023 delisting is still ahead."

    before_delisting = subsequently_delisted(
        listings, after_session=date(2019, 6, 1), horizon=date(2030, 1, 1)
    )
    assert phase3a.SEC_DELISTED in before_delisting


def test_the_survivorship_horizon_comes_from_the_verified_build(tmp_path: Path) -> None:
    """Not from an argument, which is the point: there is no argument left to move."""
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    assert publication.dataset.build_time == publication.manifest.build_time

    findings = check_universe_snapshots(
        publication.dataset,
        approvals=phase3a.approvals(),
        evaluation_cutoffs=phase3a.evaluation_cutoffs(),
    )
    assert findings == ()


def test_empty_deep_history_snapshots_do_not_raise_the_alarm() -> None:
    """An empty snapshot says nothing about who later disappeared."""
    dataset = phase3a.gold_dataset()
    emptied = _rebuild(
        dataset,
        build_time=phase3a.utc(2030, 1, 1, 12),
        universe={session: () for session in dataset.universe},
    )
    findings = check_universe_snapshots(
        emptied,
        approvals=phase3a.approvals(),
        evaluation_cutoffs=phase3a.evaluation_cutoffs(),
    )
    assert findings == (), (
        "Two empty deep-history snapshots used to be enough to raise 6.4 on their own."
    )


# ---------------------------------------------------------------------------
# 11 -- the dense minute path, end to end
# ---------------------------------------------------------------------------


def _minute_series(reader: Any, *, start: date, end: date) -> Any:
    return reader.get_price_history(
        security_id=phase3a.DENSE_MINUTE_SECURITY,
        start=start,
        end=end,
        resolution=BarResolution.MINUTE,
        adjustment_mode=RAW,
        as_of=phase3a.utc(2021, 6, 1, 12, 0),
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    ).result


def test_a_complete_minute_grid_is_published_read_and_served(tmp_path: Path) -> None:
    """The accepting path, proven end to end rather than at the grid function.

    A full regular session and a half day, generated from the venue calendar,
    published, verified on read, and served whole.
    """
    reader = phase3a.dense_minute_reader(LocalTableStore(tmp_path))
    result = _minute_series(reader, start=date(2019, 6, 28), end=date(2019, 7, 3))

    expected = len(phase3a.minute_endpoints_for(date(2019, 6, 28))) + len(
        phase3a.minute_endpoints_for(date(2019, 7, 3))
    )
    assert expected == 390 + 210
    assert len(result.bars) == expected
    assert result.bars[0].bar_end_time == phase3a.utc(2019, 6, 28, 13, 31)
    assert result.bars[-1].bar_end_time == phase3a.utc(2019, 7, 3, 17, 0)
    assert result.resolution is BarResolution.MINUTE


def test_one_missing_minute_endpoint_refuses_the_whole_series(tmp_path: Path) -> None:
    """One minute bar in a session is not evidence that the session was observed."""
    dropped = phase3a.utc(2019, 6, 28, 17, 0)
    reader = phase3a.dense_minute_reader(LocalTableStore(tmp_path), omit=dropped)
    with pytest.raises(IncompleteCoverageError, match="expected endpoint"):
        _minute_series(reader, start=date(2019, 6, 28), end=date(2019, 7, 3))


def test_the_grid_comes_from_the_calendar_not_from_the_bars(tmp_path: Path) -> None:
    """A half day recorded as an ordinary session refuses a genuinely complete series."""
    reader = phase3a.dense_minute_reader(
        LocalTableStore(tmp_path), calendar=phase3a.sessions_with_a_full_length_half_day()
    )
    with pytest.raises(IncompleteCoverageError, match="expected endpoint"):
        _minute_series(reader, start=date(2019, 7, 3), end=date(2019, 7, 3))


def test_the_half_day_is_served_on_its_own_terms(tmp_path: Path) -> None:
    """NEGATIVE CONTROL. A shorter session is short on purpose, not by omission."""
    reader = phase3a.dense_minute_reader(LocalTableStore(tmp_path))
    result = _minute_series(reader, start=date(2019, 7, 3), end=date(2019, 7, 3))
    assert len(result.bars) == 210
    assert result.bars[-1].bar_end_time == phase3a.utc(2019, 7, 3, 17, 0)


# ---------------------------------------------------------------------------
# Cross-cutting: what the published tables are, so coverage stays closed
# ---------------------------------------------------------------------------


def test_every_published_table_is_named_by_the_quality_coverage() -> None:
    """The plan compares them; this states the expectation the fixture encodes."""
    assert set(GOLD_ENTITIES) <= set(phase3a.QUALITY_COVERAGE)


def test_a_derived_header_lineage_names_only_listing_evidence_for_an_empty_snapshot() -> None:
    """Which is precisely the evidence for "nobody qualified"."""
    dataset = phase3a.gold_dataset()
    considered = [
        listing
        for listing in current_listings(dataset.listings)
        if listing.listing_fact_kind is ListingFactKind.STATE
    ]
    header = build_snapshot_header(
        (),
        session_date=date(2019, 6, 27),
        definition=phase3a.universe_definition(),
        resolved_profile=PUBLIC,
        evaluation_cutoff=phase3a.session_open(date(2019, 6, 27)),
        considered_listings=considered,
        artifact_first_built_time=phase3a.ARTIFACT_FIRST_BUILT,
        ingestion_time=phase3a.INGESTION_TIME,
        dataset_version=phase3a.DATASET_VERSION,
    )
    assert header.row_count == 0
    assert {ref.entity for ref in header.envelope.lineage} == {"listing"}
    assert isinstance(header.envelope, DerivedEnvelope)


def test_the_calendar_grid_is_venue_specific() -> None:
    """NYSE and NASDAQ keep the same hours here, and are still separate rows."""
    nasdaq = phase3a.minute_endpoints_for(date(2019, 7, 3), Exchange.NASDAQ)
    nyse = phase3a.minute_endpoints_for(date(2019, 7, 3), Exchange.NYSE)
    assert nasdaq == nyse
    assert nasdaq[-1] == datetime.fromisoformat("2019-07-03T17:00:00+00:00")


def test_a_verified_publication_cannot_be_edited_after_verification(
    tmp_path: Path,
) -> None:
    """The seal covers the build, not only the hashes that describe it.

    ``dataclasses.replace`` re-runs the seal check but carried the token through,
    and a seal over the manifest, report and receipt hashes agreed with a dataset
    whose rows had been removed -- because none of those hashes is about the rows.
    """
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    dataset = publication.dataset
    for label, mutated in (
        (
            "emptied universe",
            dataclasses.replace(dataset, universe={session: () for session in dataset.universe}),
        ),
        ("dropped bar", dataclasses.replace(dataset, bars=dataset.bars[:-1])),
        ("dropped listing", dataclasses.replace(dataset, listings=dataset.listings[:-1])),
    ):
        with pytest.raises(DatasetPublicationError, match="does not describe the artifacts"):
            dataclasses.replace(publication, dataset=mutated)
        assert mutated.build_identity != dataset.build_identity, label
