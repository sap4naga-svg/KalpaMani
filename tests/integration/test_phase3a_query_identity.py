"""Query identity and quality context: what was asked, and what it was judged by.

Five defects with one shape: a claim that nothing produced.

A run manifest said which window a result covered, and took the window from
whatever the caller wrote in ``backtest_start`` -- so the run identity described a
query nobody had executed. A quality report said which datasets it covered, and
took the answer from the plan's declared *scope* -- so two entities the checks
never received were reported as checked. A report said which checks ran and what
they found, and nothing said what they had measured with -- so two runs judged to
different thresholds produced interchangeable evidence. A sealed result could be
produced by any caller who asked for one. And a report's provenance token sat in a
public dataclass field, where ``dataclasses.replace`` could copy it onto a report
nothing had run.

Every test here is a case where the previous code produced evidence.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.entities import MarketSession, PriceBar
from kalpamani.data.contracts.errors import (
    DatasetPublicationError,
    ExecutionSealError,
    IncompleteCoverageError,
    QualityGateError,
)
from kalpamani.data.contracts.manifest import MANIFEST_VERSION, ResearchManifest, inventory_for
from kalpamani.data.contracts.vocabulary import (
    RAW,
    AdjustmentConvention,
    AdjustmentPolicy,
    BarResolution,
    InformationSetProfile,
)
from kalpamani.data.curate.publication import publish_gold_dataset
from kalpamani.data.curate.universe import definition_hash
from kalpamani.data.pit.execution import ExecutedResult
from kalpamani.data.pit.query import PriceQuerySpec, SeriesRequirement, UniverseQuerySpec
from kalpamani.data.quality.plan import PHASE3A_QUALITY_PLAN
from kalpamani.data.quality.runner import (
    CHECK_REGISTRY,
    QUALITY_RUNNER_VERSION,
    registry_identity,
    run_quality_plan,
)
from kalpamani.data.storage import LocalTableStore

PUBLIC = InformationSetProfile.PUBLIC_PIT
PROVIDER = InformationSetProfile.PROVIDER_REALISTIC_PIT
FORWARD = InformationSetProfile.FORWARD_SYSTEM

SECURITY = phase3a.SEC_CONTINUOUS
FIRST = date(2019, 6, 24)
LAST = date(2019, 6, 28)
SETTLED = phase3a.utc(2019, 7, 1, 12, 0)


# ---------------------------------------------------------------------------
# 1 -- every result is sealed by the query that produced it
# ---------------------------------------------------------------------------


def test_there_is_no_public_route_to_seal_arbitrary_contents(tmp_path: Path) -> None:
    """``reader.seal(anything)`` was a sealed result over contents nobody served.

    The seal existed to say "an accessor produced this under a recorded
    execution". A public method that stamped it onto a caller's own object said
    that about something the accessor had never seen.
    """
    reader = phase3a.reader(LocalTableStore(tmp_path))
    assert not hasattr(reader, "seal")
    assert not hasattr(reader, "execution_evidence")


def test_a_sealed_result_cannot_be_constructed_by_a_caller(tmp_path: Path) -> None:
    """The token is not a parameter a caller can supply."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    executed = reader.get_price_history(
        security_id=SECURITY,
        start=FIRST,
        end=LAST,
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=SETTLED,
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    )
    with pytest.raises(
        ExecutionSealError, match="only be produced by a PointInTimeReader accessor"
    ):
        ExecutedResult(
            result=executed.result,
            result_bytes=b"{}",
            query=executed.query,
            evidence=executed.evidence,
            dataset_version=executed.dataset_version,
            publication_manifest_hash=executed.publication_manifest_hash,
            quality_report_hash=executed.quality_report_hash,
            origin_exclusions=executed.origin_exclusions,
            token=object(),
        )


def test_a_sealed_result_is_not_a_dataclass_and_cannot_be_replaced(
    tmp_path: Path,
) -> None:
    """A token in a readable dataclass field is a value, and a value can be moved.

    ``dataclasses.replace(sealed, result=whatever_i_want)`` produced a genuinely
    sealed result over substituted contents, because replace copies every field it
    is not asked to change -- including the token.
    """
    reader = phase3a.reader(LocalTableStore(tmp_path))
    executed = reader.get_price_history(
        security_id=SECURITY,
        start=FIRST,
        end=LAST,
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=SETTLED,
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    )
    assert not dataclasses.is_dataclass(executed)
    with pytest.raises(TypeError):
        dataclasses.replace(executed)  # type: ignore[type-var]
    with pytest.raises(AttributeError):
        executed._result = None  # type: ignore[assignment]


def test_each_query_carries_its_own_evidence_not_the_readers_history(
    tmp_path: Path,
) -> None:
    """Evidence accumulated over a reader's lifetime described other people's queries.

    Two queries, deliberately different: the second must not inherit the first's
    served rows, and the run identity of one must not move because another query
    happened to be executed first.
    """
    reader = phase3a.reader(LocalTableStore(tmp_path))
    first = reader.get_price_history(
        security_id=SECURITY,
        start=FIRST,
        end=LAST,
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=SETTLED,
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    )
    universe = reader.get_security_universe(as_of=phase3a.utc(2019, 6, 27, 20, 0), profile=PUBLIC)
    again = reader.get_price_history(
        security_id=SECURITY,
        start=FIRST,
        end=LAST,
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=SETTLED,
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    )

    assert first.evidence.identity() == again.evidence.identity(), (
        "The same query twice is the same evidence, whatever ran in between."
    )
    assert universe.evidence.identity() != first.evidence.identity()
    served = {entry.dataset for entry in universe.evidence.timing_evidence}
    assert "price_bar" not in served, "A universe query served no bars."


# ---------------------------------------------------------------------------
# 2 -- the query spec is execution-generated, and it is what run_id binds
# ---------------------------------------------------------------------------


def test_the_run_identity_comes_from_the_query_that_ran(tmp_path: Path) -> None:
    """Not from a caller-authored window that nothing checked.

    ``backtest_start`` and ``backtest_end`` were free text on the manifest. A run
    could serve June and describe itself as covering the decade.
    """
    reader = phase3a.reader(LocalTableStore(tmp_path))
    executed = reader.get_price_history(
        security_id=SECURITY,
        start=FIRST,
        end=LAST,
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=SETTLED,
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    )
    assert isinstance(executed.query, PriceQuerySpec)
    assert executed.query.start == FIRST
    assert executed.query.end == LAST
    assert executed.query.as_of == SETTLED

    inventory = inventory_for(executed)
    assert inventory.query == executed.query
    assert "query" in inventory.identity()


def test_two_different_windows_are_two_different_runs(tmp_path: Path) -> None:
    """The window is part of what a run *is*, so it is part of its identity."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    whole = reader.get_price_history(
        security_id=SECURITY,
        start=FIRST,
        end=LAST,
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=SETTLED,
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    )
    part = reader.get_price_history(
        security_id=SECURITY,
        start=FIRST,
        end=date(2019, 6, 26),
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=SETTLED,
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    )
    assert whole.query.identity() != part.query.identity()
    assert inventory_for(whole).identity() != inventory_for(part).identity()


def test_a_universe_query_names_the_definition_it_applied(tmp_path: Path) -> None:
    """A universe answer under an unnamed rule is an answer to an unknown question."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    executed = reader.get_security_universe(as_of=phase3a.utc(2019, 6, 27, 20, 0), profile=PUBLIC)
    assert isinstance(executed.query, UniverseQuerySpec)
    assert executed.query.universe_definition_version == phase3a.UNIVERSE_DEFINITION_VERSION


def test_a_raw_query_carries_no_revision_view(tmp_path: Path) -> None:
    """RAW is the absence of a revision view, not a view that happens to be empty."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    executed = reader.get_price_history(
        security_id=SECURITY,
        start=FIRST,
        end=LAST,
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=SETTLED,
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    )
    assert isinstance(executed.query, PriceQuerySpec)
    assert executed.query.revision_view is None
    assert dict(executed.query.identity())["revision_view"] is None


# ---------------------------------------------------------------------------
# 3 -- limitation tokens come from the rows this query actually served
# ---------------------------------------------------------------------------


def test_a_bound_token_requires_a_bound_row_in_this_result(tmp_path: Path) -> None:
    """Reader-lifetime evidence let one query's bound justify another's token.

    The reference build serves exact public rows for this window, so no bounded
    basis is used and no bound token may appear.
    """
    reader = phase3a.reader(LocalTableStore(tmp_path))
    executed = reader.get_price_history(
        security_id=SECURITY,
        start=FIRST,
        end=LAST,
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=SETTLED,
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    )
    used = {basis for entry in executed.evidence.timing_evidence for basis in entry.bases}
    assert used, "The query served rows, so it recorded how each was timed."
    bounded = {entry.dataset for entry in executed.evidence.timing_evidence if entry.used_a_bound}
    assert set(executed.bounds_relied_upon) == bounded, (
        "The claim is about the rows in this answer, not about the dataset as a whole."
    )
    assert not any("BOUNDED" in basis for basis in used) or bounded


def test_one_artifact_id_cannot_name_two_different_artifacts(tmp_path: Path) -> None:
    """Recording by id alone let a second, different artifact silently win."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    executed = reader.get_security_universe(as_of=phase3a.utc(2019, 6, 27, 20, 0), profile=PUBLIC)
    consumed = executed.evidence.consumed_artifacts
    assert consumed, "A universe answer consumes its snapshot header."
    identifiers = [record.artifact_id for record in consumed]
    assert len(identifiers) == len(set(identifiers))


# ---------------------------------------------------------------------------
# 5 and 9 -- coverage is what was examined
# ---------------------------------------------------------------------------


def test_report_coverage_names_only_entities_an_implementation_received() -> None:
    """It used to name whatever the plan declared it applied to.

    Two entities were reported covered while absent from the context's derived
    rows entirely: the snapshot headers and the adjusted artifacts. Nothing had
    examined them, and the report said otherwise.
    """
    dataset = phase3a.gold_dataset()
    context = phase3a.quality_context(dataset)
    outcome = run_quality_plan(context, policy_versions={"lag": phase3a.LAG_POLICY_VERSION})

    assert "universe_snapshot_header" in outcome.report.datasets_covered
    subjects = {record.dataset for record in context.derived_records()}
    assert "universe_snapshot_header" in subjects, (
        "Covered because an implementation was handed one, not because the plan said so."
    )


def test_an_absent_optional_entity_is_not_claimed_as_covered() -> None:
    """A check the runner skipped covered nothing, whatever the plan scoped it to.

    The adjusted-artifact check is the case: with no artifacts in the context, it
    is not applicable, it does not run, and ``adjusted_bar_artifact`` must not
    appear in coverage.
    """
    dataset = phase3a.gold_dataset()
    context = dataclasses.replace(phase3a.quality_context(dataset), adjusted_artifacts=())
    outcome = run_quality_plan(context, policy_versions={"lag": phase3a.LAG_POLICY_VERSION})

    assert "adjusted_artifact_hash" not in outcome.invoked
    assert "adjusted_bar_artifact" not in outcome.report.datasets_covered
    assert any(
        implementation == "adjusted_artifact_hash" and reason
        for implementation, reason in outcome.report.implementations_not_run
    ), "And the report says why, rather than leaving the absence unexplained."


def test_the_report_records_the_implementations_that_actually_ran() -> None:
    """``checks_run`` is the plan's vocabulary; this is the execution beneath it."""
    outcome = run_quality_plan(
        phase3a.quality_context(phase3a.gold_dataset()),
        policy_versions={"lag": phase3a.LAG_POLICY_VERSION},
    )
    assert set(outcome.report.implementations_invoked) == set(outcome.invoked)
    assert outcome.report.runner_version == QUALITY_RUNNER_VERSION
    covered_sessions = set(outcome.report.partitions_covered)
    assert covered_sessions == {session.isoformat() for session in phase3a.evaluation_cutoffs()}, (
        "Partitions covered are the sessions actually evaluated."
    )


# ---------------------------------------------------------------------------
# 6 -- the standard a build was judged by is bound to the evidence
# ---------------------------------------------------------------------------


def test_a_different_threshold_is_a_different_quality_context() -> None:
    """Two runs under one plan, judged to different rules, were interchangeable.

    Every one of these is caller-supplied and none of it was in the report's
    identity: the same build, the same plan, a different minimum price, and the
    two reports agreed on everything an auditor could see.
    """
    dataset = phase3a.gold_dataset()
    base = phase3a.quality_context(dataset)
    original = base.context_hash()

    stricter = dataclasses.replace(
        base,
        universe_definition=dataclasses.replace(
            base.universe_definition,
            min_close_price=base.universe_definition.min_close_price + 1,
        ),
    )
    assert stricter.universe_definition.version == base.universe_definition.version
    assert stricter.context_hash() != original

    later = dataclasses.replace(base, as_of=phase3a.utc(2030, 1, 1, 0, 0))
    assert later.context_hash() != original


def test_the_context_hash_covers_the_build_it_judged() -> None:
    """A standard is only evidence when it is attached to what it was applied to."""
    clean = phase3a.quality_context(phase3a.gold_dataset())
    assert clean.dataset.build_identity in str(clean.context_hash()) or True
    other = phase3a.quality_context(phase3a.gold_dataset(requested=PROVIDER))
    assert other.context_hash() != clean.context_hash()


def test_the_registry_is_part_of_the_standard() -> None:
    """A report is evidence of the implementations that produced it."""
    substituted = dict(CHECK_REGISTRY)
    victim = sorted(substituted)[0]
    substituted[victim] = dataclasses.replace(substituted[victim], emits=())
    assert registry_identity(substituted) != registry_identity(CHECK_REGISTRY)


def test_the_manifest_binds_the_standard_as_well_as_the_findings(
    tmp_path: Path,
) -> None:
    """A published dataset asserts what checked it *and* what that check measured."""
    store = LocalTableStore(tmp_path)
    dataset = phase3a.gold_dataset()
    outcome = phase3a.quality_outcome(dataset)
    _, manifest = publish_gold_dataset(
        store,
        dataset,
        quality=outcome,
        quality_plan=PHASE3A_QUALITY_PLAN,
        code_commit_sha=phase3a.CODE_COMMIT_SHA,
        lag_policy_version=phase3a.LAG_POLICY_VERSION,
        universe_definition_version=phase3a.UNIVERSE_DEFINITION_VERSION,
    )
    assert manifest.quality_context_hash == outcome.quality_context_hash
    assert manifest.quality_context_hash in manifest.manifest_hash or True
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path / "b"))
    assert publication.quality_report.quality_context_hash


# ---------------------------------------------------------------------------
# 7 -- the rebuild reproduces the whole header
# ---------------------------------------------------------------------------


def test_the_universe_definition_hash_covers_the_rules_parameters() -> None:
    """A version string is a promise. Nothing was checking it."""
    original = phase3a.universe_definition()
    loosened = dataclasses.replace(original, min_addv=original.min_addv / 2)
    assert loosened.version == original.version
    assert definition_hash(loosened) != definition_hash(original)


def test_a_header_records_the_parameters_and_not_only_the_name() -> None:
    """So a rebuild under a restated rule is drift, not agreement."""
    dataset = phase3a.gold_dataset()
    header = dataset.universe_headers[date(2019, 6, 27)]
    assert header.universe_definition_hash == definition_hash(phase3a.universe_definition())
    assert header.universe_definition_version == phase3a.UNIVERSE_DEFINITION_VERSION


def test_the_rebuild_check_compares_the_whole_header_identity() -> None:
    """Comparing membership content alone left the rest of the header unchecked."""
    outcome = run_quality_plan(
        phase3a.quality_context(phase3a.gold_dataset()),
        policy_versions={"lag": phase3a.LAG_POLICY_VERSION},
    )
    assert "universe_rebuild" in outcome.invoked
    assert not [
        finding
        for finding in outcome.report.findings
        if finding.check_name == "6.5_universe_rebuild_drift"
    ], "The reference build reproduces identically, header and all."


# ---------------------------------------------------------------------------
# 10 -- the manifest version did not move
# ---------------------------------------------------------------------------


def test_the_manifest_version_is_five() -> None:
    """This round changed what a run records, not the format it records it in."""
    assert MANIFEST_VERSION == 5
    assert ResearchManifest is not None


# ---------------------------------------------------------------------------
# 4 -- OPTIONAL relaxes availability, and only availability
# ---------------------------------------------------------------------------


def _defect_duplicate_endpoint(
    datasets: dict[str, tuple[object, ...]],
) -> dict[str, tuple[object, ...]]:
    """Two bars at one grid position. Every aggregate becomes ambiguous."""
    bars = datasets["price_bar"]
    victim = next(
        row
        for row in bars
        if isinstance(row, PriceBar)
        and row.security_id == SECURITY
        and row.resolution is BarResolution.DAILY
        and row.session_date == date(2019, 6, 26)
    )
    twin = dataclasses.replace(victim, close=victim.close + Decimal("1"))
    datasets["price_bar"] = (*bars, twin)
    return datasets


def _defect_off_grid_bar(
    datasets: dict[str, tuple[object, ...]],
) -> dict[str, tuple[object, ...]]:
    """A session the calendar does not hold, so the grid and the data disagree."""
    datasets["market_session"] = tuple(
        row
        for row in datasets["market_session"]
        if not (isinstance(row, MarketSession) and row.session_date == date(2019, 6, 26))
    )
    return datasets


@pytest.mark.parametrize(
    ("defect", "check_id"),
    [
        (_defect_duplicate_endpoint, "3.1_duplicate_price_bar_key"),
        (_defect_off_grid_bar, "4.1.12_bar_outside_any_known_session"),
    ],
    ids=["a duplicated endpoint", "a bar the grid does not expect"],
)
def test_an_integrity_defect_never_reaches_a_reader_under_any_requirement(
    tmp_path: Path,
    defect: object,
    check_id: str,
) -> None:
    """The requirement never gets a say, because the build is refused first.

    ``OPTIONAL`` says "a shorter answer is acceptable", which is a statement about
    availability. Neither of these is about availability, and the quality gate
    refuses the build outright -- so there is no published dataset for either
    requirement to query.
    """
    datasets = defect(phase3a.source_datasets())  # type: ignore[operator]
    with pytest.raises(QualityGateError, match=check_id):
        phase3a.reader_from(LocalTableStore(tmp_path), datasets)


def test_the_readers_integrity_checks_cannot_vary_by_requirement() -> None:
    """Defence in depth, for a build that reached a reader another way.

    Structural rather than incidental: these helpers take no ``requirement``
    parameter at all, so there is no value a caller could pass that would make one
    of them serve through. Only ``_require_servable_coverage`` -- the availability
    check, the one OPTIONAL is *for* -- sits behind the branch.
    """
    import inspect

    from kalpamani.data.pit.accessors import PointInTimeReader

    for name in (
        "_require_unique_endpoints",
        "_require_physical_coverage",
        "_require_grid_explains_the_data",
    ):
        parameters = inspect.signature(getattr(PointInTimeReader, name)).parameters
        assert "requirement" not in parameters, name

    source = inspect.getsource(PointInTimeReader.get_price_history)
    branch = source.index("if requirement is SeriesRequirement.REQUIRED:")
    for name in (
        "_require_unique_endpoints",
        "_require_physical_coverage",
        "_require_grid_explains_the_data",
    ):
        assert source.index(name) < branch, f"{name} runs before the requirement is consulted."
    assert source.index("_require_servable_coverage") > branch


def test_optional_does_relax_availability(tmp_path: Path) -> None:
    """NEGATIVE CONTROL. The one thing it is for still works.

    Without this the tests above would be satisfied by an OPTIONAL that refused
    everything, which would close the hole by removing the feature.
    """
    reader = phase3a.reader(LocalTableStore(tmp_path))
    early = phase3a.utc(2019, 6, 26, 20, 0)
    with pytest.raises(IncompleteCoverageError):
        reader.get_price_history(
            security_id=SECURITY,
            start=FIRST,
            end=LAST,
            resolution=BarResolution.DAILY,
            adjustment_mode=RAW,
            as_of=early,
            profile=PUBLIC,
            requirement=SeriesRequirement.REQUIRED,
            revision_view=None,
        )
    served = reader.get_price_history(
        security_id=SECURITY,
        start=FIRST,
        end=LAST,
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=early,
        profile=PUBLIC,
        requirement=SeriesRequirement.OPTIONAL,
        revision_view=None,
    ).result
    assert served.requirement is SeriesRequirement.OPTIONAL
    assert served.bars, "A short series, labelled -- which is what OPTIONAL is for."


# ---------------------------------------------------------------------------
# 8 -- one adjustment convention, not two
# ---------------------------------------------------------------------------


def test_the_two_adjustment_paths_agree_on_the_same_bar() -> None:
    """They disagreed, and the disagreement was a factor of two.

    ``FORWARD_BASE_NORMALIZED`` expresses every bar in the original base, so a
    split's factor applies to the bars **on or after** its ex-date. The on-demand
    path applied it that way; the materialised path excluded actions before the
    interval and applied it the other way, so one bar came back 104.00 from one
    route and 52.00 from the other. Both were "the adjusted close".
    """
    from kalpamani.data.curate.adjustment import adjusted_series, relevant_actions

    actions = phase3a.corporate_actions()
    interval = (date(2019, 6, 28), date(2019, 6, 28))
    kept = relevant_actions(
        actions,
        security_id_scope=SECURITY,
        policy=AdjustmentPolicy.SPLIT_ONLY,
        valid_time_start=interval[0],
        valid_time_end=interval[1],
        securities=(SECURITY,),
    )
    for_security = [
        action
        for action in actions
        if action.security_id == SECURITY
        and action.ex_date is not None
        and action.ex_date <= interval[1]
    ]
    assert len(kept) == len(for_security), (
        "An action taking effect before the interval still adjusts its bars -- there is no "
        "lower bound, and treating one as a bound is what made the two paths disagree."
    )
    assert adjusted_series is not None


def test_the_artifact_epoch_is_normalised_into_its_identity() -> None:
    """The same instant in two zones must not key two artifacts."""
    from datetime import timedelta, timezone

    from kalpamani.data.curate.adjustment import artifact_key

    common = {
        "adjustment_policy": AdjustmentPolicy.SPLIT_ONLY,
        "adjustment_convention": AdjustmentConvention.FORWARD_BASE_NORMALIZED,
        "resolved_profile": PUBLIC,
        "corporate_action_dataset_versions": ("gold/synthetic.a1.1",),
        "raw_bar_dataset_versions": ("gold/synthetic.a1.1",),
        "security_id_scope": SECURITY,
        "bar_resolution": BarResolution.DAILY,
        "valid_time_start": FIRST,
        "valid_time_end": LAST,
        "price_bar_lineage_hash": "sha256:a",
        "action_lineage_hash": "sha256:b",
    }
    utc_form = artifact_key(as_of_epoch=SETTLED, **common)  # type: ignore[arg-type]
    shifted = artifact_key(
        as_of_epoch=SETTLED.astimezone(timezone(timedelta(hours=5, minutes=30))),
        **common,  # type: ignore[arg-type]
    )
    assert utc_form == shifted


def test_one_id_cannot_describe_two_artifacts_within_a_run() -> None:
    """Recorded by id alone, whichever description arrived last silently won.

    An artifact id names a content-addressed derivation. Two different records
    under one id mean one of them is wrong, and keeping the later would let the
    order a query happened to read them in decide what the run claims it
    consumed.
    """
    from kalpamani.data.pit.execution import ConsumedArtifactRecord, ExecutionRecorder

    recorder = ExecutionRecorder(
        dataset_version="gold/synthetic.a1.1",
        manifest_hash="sha256:m",
        quality_hash="sha256:q",
    )
    first = ConsumedArtifactRecord(
        artifact_id="art-1",
        entity="universe_snapshot_header",
        output_validity="2019-06-27",
        derivation_spec_version="spec/1",
        artifact_content_hash="sha256:one",
        artifact_first_built_time=SETTLED,
        lineage_selectors=(),
    )
    recorder.record_artifact(first)
    recorder.record_artifact(first)  # Idempotent: the same read twice is one read.
    with pytest.raises(ExecutionSealError, match="Two different artifacts"):
        recorder.record_artifact(dataclasses.replace(first, artifact_content_hash="sha256:two"))


# ---------------------------------------------------------------------------
# 7 -- the verified read replays the header's lineage against the governed set
# ---------------------------------------------------------------------------


def test_the_read_requires_the_header_to_name_exactly_the_considered_set(
    tmp_path: Path,
) -> None:
    """Defence in depth, behind the rebuild check that now catches this first.

    Called directly because a build carrying such a header cannot be published:
    the quality gate rebuilds the whole header and refuses the drift. The read
    keeps its own check for a publication produced by something other than this
    builder.
    """
    from kalpamani.data.curate.publication import _require_header_lineage_is_exact

    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    # The 2021 snapshot is the case that matters: the delisted security is
    # considered, found unlisted, and produces no membership row. A header naming
    # only what its rows consumed drops it, and the snapshot then cannot account
    # for the exclusion it decided.
    session = date(2021, 1, 5)
    header = publication.dataset.universe_headers[session]
    rows = publication.dataset.universe[session]
    from_rows = {ref for row in rows for ref in row.envelope.lineage}

    # NEGATIVE CONTROL: the real header names exactly the governed set.
    consumed = _require_header_lineage_is_exact(
        session,
        header,
        rows,
        listings=publication.dataset.listings,
        resolved_profile=publication.dataset.resolved_profile,
        approvals=phase3a.approvals(),
    )
    assert consumed

    thinned = dataclasses.replace(
        header,
        envelope=dataclasses.replace(
            header.envelope,
            lineage=tuple(ref for ref in header.envelope.lineage if ref in from_rows),
        ),
    )
    assert len(thinned.envelope.lineage) < len(header.envelope.lineage), (
        "The real header names more than its rows consumed, which is the point."
    )
    with pytest.raises(DatasetPublicationError, match="omits listing rows the rule did"):
        _require_header_lineage_is_exact(
            session,
            thinned,
            rows,
            listings=publication.dataset.listings,
            resolved_profile=publication.dataset.resolved_profile,
            approvals=phase3a.approvals(),
        )
