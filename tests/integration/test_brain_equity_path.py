"""The Brain over a genuine point-in-time reader, not a hand-built result.

The unit tests drive the Brain with synthetic ``BarSeriesResult`` values. This one
proves the consumer boundary end to end: a real
:class:`~kalpamani.data.pit.accessors.PointInTimeReader`, over the real synthetic
publication and its verified-read path, produces the price and benchmark series, and
the Brain consumes them (production unwraps ``reader.get_price_history(...).result``
the same way) and returns a valid closed ``CandidateIntent`` whose lineage references
the actual dataset.

The outcome here is ``REJECTED`` -- over this five-session window the security did not
out-return the benchmark -- and that is fine: the point is that the Brain reads genuine
reader output and reaches a valid, reproducible decision, not that this fixture triggers
a breakout. The status is asserted exactly, so the test cannot pass on *any* member of
the closed vocabulary.

The second half drives the **refusal** branches with genuine reader output rather than a
hand-built result: a series the reader served at a different ``as_of``, a series that
ends before the evaluation session, a window shorter than the version requires, a
publication that resolved under a downgraded profile, and a result under the wrong
profile. Each must be a journaled ``BLOCKED_DATA`` with the accepted reason code, and
the kernel itself must refuse to serve a bar that was not yet available -- so future
evidence never reaches the Brain at all.
"""

from __future__ import annotations

import dataclasses
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from fixtures import phase3a
from kalpamani.common.environment import Environment
from kalpamani.data.contracts.entities import PriceBarValues
from kalpamani.data.contracts.errors import IncompleteCoverageError
from kalpamani.data.contracts.vocabulary import (
    AdjustmentConvention,
    AdjustmentMode,
    AdjustmentPolicy,
    BarResolution,
    GlobalProfileResolution,
    InformationSetProfile,
    RevisionView,
)
from kalpamani.data.pit.accessors import BarSeriesResult, PointInTimeReader
from kalpamani.data.pit.query import SeriesRequirement
from kalpamani.data.storage import LocalTableStore
from kalpamani.strategies.brain.compiler import compile_candidate
from kalpamani.strategies.brain.evidence import EvaluationInputs
from kalpamani.strategies.brain.factors import FactorDefinition
from kalpamani.strategies.brain.intent import CandidateIntent
from kalpamani.strategies.brain.module import ModuleEvaluation
from kalpamani.strategies.brain.spec import (
    DataRequirements,
    Permissions,
    ResearchGovernance,
    RiskTags,
    StrategySpec,
)
from kalpamani.strategies.brain.vocabulary import (
    COMPILER_STAGE_ORDER,
    AlphaFamily,
    CompilerStage,
    DataDomain,
    DecisionState,
    Direction,
    FactorFamily,
    LifecycleStage,
    ReasonCode,
    Requirement,
)
from kalpamani.strategies.breakout.long import (
    FACTOR_DEFINITION_VERSION,
    BreakoutLong,
    BreakoutLongParameters,
)

pytestmark = pytest.mark.integration

PROFILE = InformationSetProfile.PUBLIC_PIT
ADJUSTMENT = AdjustmentMode.adjusted(
    AdjustmentPolicy.SPLIT_ONLY, AdjustmentConvention.FORWARD_BASE_NORMALIZED
)
#: The synthetic calendar is available under PUBLIC_PIT from this instant; the dense
#: 2019 session cluster is the one long enough for even a tiny research window.
AS_OF = phase3a.utc(2019, 6, 28, 21, 0)
START = date(2019, 6, 24)
END = date(2019, 6, 28)

#: A tiny research window, so the dense five-session cluster suffices. Stated as a
#: fixture convenience; the module's production default window is unchanged.
PARAMS = BreakoutLongParameters(
    trend_sessions=2,
    base_sessions=2,
    relative_strength_sessions=2,
    volume_baseline_sessions=2,
    liquidity_sessions=2,
    high_proximity_sessions=2,
    min_average_dollar_volume=Decimal("0"),
)


def _price_only_spec(
    required_profile: InformationSetProfile = PROFILE,
) -> StrategySpec:
    """A research-stage spec requiring only the price and benchmark the reader can serve.

    The module's own spec additionally requires universe, event and market context,
    which the synthetic publication cannot supply for this window under a single
    ``as_of``. This spec keeps the same factor identity and research staging while
    narrowing the required evidence to what a genuine reader produces here.
    ``required_profile`` is a parameter so a profile-mismatch control can declare a
    profile the reader did not serve.
    """
    definitions = (
        FactorDefinition(
            factor_id="trend-ma-close",
            version=FACTOR_DEFINITION_VERSION,
            family=FactorFamily.PRICE_MOMENTUM,
            lookback_sessions=2,
        ),
    )
    return StrategySpec(
        strategy_id="breakout-long",
        alpha_family=AlphaFamily.MOMENTUM_CONTINUATION,
        strategy_module="breakout-long",
        trade_template="base-breakout-close-confirmation",
        version="breakout-long/integration-research",
        lifecycle_stage=LifecycleStage.REGISTERED_HYPOTHESIS,
        authorized_environments=frozenset({Environment.RESEARCH}),
        direction=Direction.LONG,
        expected_holding_sessions=10,
        minimum_holding_sessions=2,
        maximum_holding_sessions=30,
        data=DataRequirements(
            required_profile=required_profile,
            revision_view=RevisionView.AS_KNOWN_AT_AS_OF,
            adjustment_mode=ADJUSTMENT,
            resolution=BarResolution.DAILY,
            required_domains=frozenset({DataDomain.PRICE_BARS, DataDomain.BENCHMARK_BARS}),
            optional_domains=frozenset(),
            required_history_sessions=3,
        ),
        permissions=Permissions(
            market_prerequisite=Requirement.NOT_APPLICABLE,
            event_prerequisite=Requirement.NOT_APPLICABLE,
            gap_prerequisite=Requirement.OPTIONAL,
            borrow_prerequisite=Requirement.NOT_APPLICABLE,
            ai_requirement=Requirement.NOT_APPLICABLE,
            rank_requirement=Requirement.OPTIONAL,
        ),
        factor_definitions=definitions,
        factor_definition_version=FACTOR_DEFINITION_VERSION,
        parameters_hash="breakout-long.integration.params/1",
        manifest_version="breakout-long.integration.manifest/1",
        configuration_identity="breakout-long.integration.config/1",
        model_version=None,
        prompt_version=None,
        risk_tags=RiskTags(
            family_exposure=AlphaFamily.MOMENTUM_CONTINUATION,
            factor_exposures=(FactorFamily.PRICE_MOMENTUM,),
            capacity_reference="breakout-long.integration.capacity/unmeasured",
            risk_policy_compatibility="momentum-continuation.long/integration",
        ),
        research=ResearchGovernance(
            hypothesis_id="H-breakout-long-integration",
            baseline_id="ranked-entry-baseline",
            trial_budget=1,
            success_criteria_reference="protocol.integration.success/unset",
            failure_criteria_reference="protocol.integration.failure/unset",
        ),
    )


class _PriceOnlyBreakout:
    """The Breakout Long factor logic under the narrowed integration spec."""

    def __init__(self, required_profile: InformationSetProfile = PROFILE) -> None:
        self._breakout = BreakoutLong(PARAMS)
        self._spec = _price_only_spec(required_profile)

    @property
    def spec(self) -> StrategySpec:
        return self._spec

    def evaluate(
        self,
        bars: tuple[PriceBarValues, ...],
        benchmark: tuple[PriceBarValues, ...],
    ) -> ModuleEvaluation:
        return self._breakout.evaluate(bars, benchmark)


def _reader(
    *,
    requested: InformationSetProfile = PROFILE,
    downgrade: GlobalProfileResolution = GlobalProfileResolution.NONE,
) -> PointInTimeReader:
    store = LocalTableStore(Path(tempfile.mkdtemp(prefix="brain-integration-")))
    return phase3a.reader(store, requested=requested, downgrade=downgrade)


def _series(
    reader: PointInTimeReader,
    security_id: str,
    *,
    start: date = START,
    end: date = END,
    as_of: datetime = AS_OF,
    profile: InformationSetProfile = PROFILE,
) -> BarSeriesResult:
    return reader.get_price_history(
        security_id=security_id,
        start=start,
        end=end,
        resolution=BarResolution.DAILY,
        adjustment_mode=ADJUSTMENT,
        as_of=as_of,
        profile=profile,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=RevisionView.AS_KNOWN_AT_AS_OF,
    ).result


def _inputs(
    *,
    price: BarSeriesResult | None = None,
    benchmark: BarSeriesResult | None = None,
    as_of: datetime = AS_OF,
    evaluation_session: date | None = None,
) -> EvaluationInputs:
    if price is None or benchmark is None:
        reader = _reader()
        price = price if price is not None else _series(reader, phase3a.SEC_CONTINUOUS)
        benchmark = benchmark if benchmark is not None else _series(reader, phase3a.SEC_RENAMED)
    return EvaluationInputs(
        as_of_time=as_of,
        environment=Environment.RESEARCH,
        security_id=phase3a.SEC_CONTINUOUS,
        evaluation_session=(
            evaluation_session if evaluation_session is not None else price.bars[-1].session_date
        ),
        price_history=price,
        benchmark_history=benchmark,
    )


def test_the_brain_consumes_a_genuine_reader_result_and_reaches_a_valid_decision() -> None:
    intent = compile_candidate(_inputs(), _PriceOnlyBreakout())
    # The exact outcome, not merely "some member of the vocabulary": over this window the
    # security did not out-return the benchmark, so eligibility refuses at stage five.
    assert intent.status is DecisionState.REJECTED
    assert intent.reason_codes == (ReasonCode.RELATIVE_STRENGTH_NOT_POSITIVE,)
    assert intent.concluded_at_stage is CompilerStage.STRATEGY_AND_MODULE_ELIGIBILITY
    assert intent.evidence is not None
    # The lineage references the real published dataset the reader served.
    assert intent.evidence.lineage.price_dataset_version == phase3a.DATASET_VERSION
    assert intent.evidence.coverage.resolved_profile is PROFILE
    assert intent.evidence.coverage.sessions_available == 5


def test_the_decision_over_real_reader_output_is_reproducible() -> None:
    first = compile_candidate(_inputs(), _PriceOnlyBreakout())
    second = compile_candidate(_inputs(), _PriceOnlyBreakout())
    assert first.candidate_id == second.candidate_id
    assert first.status is second.status
    assert first.reason_codes == second.reason_codes


def test_the_brain_output_carries_no_size_or_order_over_real_data() -> None:
    """The consumer boundary holds on genuine data: the terminal output is a status."""
    intent = compile_candidate(_inputs(), _PriceOnlyBreakout())
    # Whatever the status, the record is a CandidateIntent -- no size, no order field
    # exists on it. The structural guarantee is checked exhaustively in the unit tests;
    # here we confirm the real-data decision is that same type and nothing else.
    assert type(intent).__name__ == "CandidateIntent"
    assert intent.thesis is None or intent.thesis.technical_stop_reference.level > 0


# -- the refusal branches, over genuine reader output --------------------------------------


def _blocked(intent: CandidateIntent, reason: ReasonCode, stage: CompilerStage) -> None:
    assert intent.status is DecisionState.BLOCKED_DATA
    assert intent.reason_codes == (reason,)
    assert intent.concluded_at_stage is stage
    assert intent.stages_passed == COMPILER_STAGE_ORDER[: COMPILER_STAGE_ORDER.index(stage)]


def test_a_reader_result_served_at_another_as_of_is_not_evidence_for_this_decision() -> None:
    """The result answered ``AS_OF``; a decision an hour later may not reuse it."""
    intent = compile_candidate(_inputs(as_of=AS_OF + timedelta(hours=1)), _PriceOnlyBreakout())
    _blocked(intent, ReasonCode.EVIDENCE_AS_OF_MISMATCH, CompilerStage.POINT_IN_TIME_REALITY_GATE)


def test_a_reader_series_that_stops_before_the_evaluation_session_is_stale() -> None:
    """A genuine four-session series is not "the most recent available" for a fifth."""
    reader = _reader()
    price = _series(reader, phase3a.SEC_CONTINUOUS, end=date(2019, 6, 27))
    benchmark = _series(reader, phase3a.SEC_RENAMED, end=date(2019, 6, 27))
    intent = compile_candidate(
        _inputs(price=price, benchmark=benchmark, evaluation_session=END), _PriceOnlyBreakout()
    )
    _blocked(intent, ReasonCode.STALE_PRICE_HISTORY, CompilerStage.POINT_IN_TIME_REALITY_GATE)


def test_a_reader_window_shorter_than_the_version_requires_blocks_at_coverage() -> None:
    reader = _reader()
    price = _series(reader, phase3a.SEC_CONTINUOUS, start=date(2019, 6, 27))
    benchmark = _series(reader, phase3a.SEC_RENAMED, start=date(2019, 6, 27))
    intent = compile_candidate(_inputs(price=price, benchmark=benchmark), _PriceOnlyBreakout())
    _blocked(intent, ReasonCode.INSUFFICIENT_HISTORY, CompilerStage.REQUIRED_DATA_COVERAGE)


def test_a_benchmark_the_reader_served_shorter_than_the_security_blocks_at_coverage() -> None:
    """A short benchmark is a coverage refusal, never a raised error from inside a factor."""
    reader = _reader()
    price = _series(reader, phase3a.SEC_CONTINUOUS)
    benchmark = _series(reader, phase3a.SEC_RENAMED, start=date(2019, 6, 27))
    intent = compile_candidate(_inputs(price=price, benchmark=benchmark), _PriceOnlyBreakout())
    _blocked(intent, ReasonCode.INSUFFICIENT_HISTORY, CompilerStage.REQUIRED_DATA_COVERAGE)


def test_a_bar_not_yet_available_at_as_of_never_reaches_the_brain() -> None:
    """Future evidence is refused by the kernel itself: a REQUIRED series with a bar the
    ``as_of`` could not see is not served short, it is refused, so nothing exists for the
    Brain to be handed."""
    reader = _reader()
    with pytest.raises(IncompleteCoverageError):
        _series(reader, phase3a.SEC_CONTINUOUS, as_of=phase3a.utc(2019, 6, 27, 21, 0))


def test_a_result_under_the_wrong_profile_is_refused_for_a_provider_realistic_version() -> None:
    """The reader served PUBLIC_PIT; a version declaring PROVIDER_REALISTIC_PIT may not
    read it as its own profile."""
    module = _PriceOnlyBreakout(InformationSetProfile.PROVIDER_REALISTIC_PIT)
    intent = compile_candidate(_inputs(), module)
    _blocked(intent, ReasonCode.PROFILE_MISMATCH, CompilerStage.POINT_IN_TIME_REALITY_GATE)


def test_a_genuinely_downgraded_publication_is_refused() -> None:
    """A real publication resolved under a downgrade: requested PROVIDER_REALISTIC_PIT,
    resolved PUBLIC_PIT, with the kernel's own limitation token. The Brain refuses it
    rather than reading the downgraded series as the profile it asked for."""
    requested = InformationSetProfile.PROVIDER_REALISTIC_PIT
    reader = _reader(requested=requested, downgrade=GlobalProfileResolution.DOWNGRADE)
    price = _series(reader, phase3a.SEC_CONTINUOUS, profile=requested)
    benchmark = _series(reader, phase3a.SEC_RENAMED, profile=requested)
    assert price.provenance.was_downgraded  # the fixture really downgraded
    module = _PriceOnlyBreakout(requested)
    intent = compile_candidate(_inputs(price=price, benchmark=benchmark), module)
    _blocked(intent, ReasonCode.PROFILE_DOWNGRADED, CompilerStage.POINT_IN_TIME_REALITY_GATE)


def test_a_hand_altered_reader_result_is_not_rescued_by_its_provenance() -> None:
    """A result whose bars were replaced after the reader served it carries the reader's
    provenance and none of its content guarantees; the gate inspects the bars themselves."""
    reader = _reader()
    price = _series(reader, phase3a.SEC_CONTINUOUS)
    later = dataclasses.replace(price.bars[-1], bar_end_time=AS_OF + timedelta(minutes=1))
    altered = dataclasses.replace(price, bars=(*price.bars[:-1], later))
    intent = compile_candidate(_inputs(price=altered), _PriceOnlyBreakout())
    _blocked(intent, ReasonCode.OBSERVATION_AFTER_AS_OF, CompilerStage.POINT_IN_TIME_REALITY_GATE)
