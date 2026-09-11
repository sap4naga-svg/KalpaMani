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
a breakout.
"""

from __future__ import annotations

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from fixtures import phase3a
from kalpamani.common.environment import Environment
from kalpamani.data.contracts.entities import PriceBarValues
from kalpamani.data.contracts.vocabulary import (
    AdjustmentConvention,
    AdjustmentMode,
    AdjustmentPolicy,
    BarResolution,
    InformationSetProfile,
    RevisionView,
)
from kalpamani.data.pit.accessors import BarSeriesResult, PointInTimeReader
from kalpamani.data.pit.query import SeriesRequirement
from kalpamani.data.storage import LocalTableStore
from kalpamani.strategies.brain.compiler import compile_candidate
from kalpamani.strategies.brain.evidence import EvaluationInputs
from kalpamani.strategies.brain.factors import FactorDefinition
from kalpamani.strategies.brain.module import ModuleEvaluation
from kalpamani.strategies.brain.spec import (
    DataRequirements,
    Permissions,
    ResearchGovernance,
    RiskTags,
    StrategySpec,
)
from kalpamani.strategies.brain.vocabulary import (
    AlphaFamily,
    DataDomain,
    DecisionState,
    Direction,
    FactorFamily,
    LifecycleStage,
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
START, END = date(2019, 6, 24), date(2019, 6, 28)

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


def _price_only_spec() -> StrategySpec:
    """A research-stage spec requiring only the price and benchmark the reader can serve.

    The module's own spec additionally requires universe, event and market context,
    which the synthetic publication cannot supply for this window under a single
    ``as_of``. This spec keeps the same factor identity and research staging while
    narrowing the required evidence to what a genuine reader produces here.
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
            required_profile=PROFILE,
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

    def __init__(self) -> None:
        self._breakout = BreakoutLong(PARAMS)
        self._spec = _price_only_spec()

    @property
    def spec(self) -> StrategySpec:
        return self._spec

    def evaluate(
        self,
        bars: tuple[PriceBarValues, ...],
        benchmark: tuple[PriceBarValues, ...],
    ) -> ModuleEvaluation:
        return self._breakout.evaluate(bars, benchmark)


def _reader() -> PointInTimeReader:
    store = LocalTableStore(Path(tempfile.mkdtemp(prefix="brain-integration-")))
    return phase3a.reader(store, requested=PROFILE)


def _series(reader: PointInTimeReader, security_id: str) -> BarSeriesResult:
    return reader.get_price_history(
        security_id=security_id,
        start=START,
        end=END,
        resolution=BarResolution.DAILY,
        adjustment_mode=ADJUSTMENT,
        as_of=AS_OF,
        profile=PROFILE,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=RevisionView.AS_KNOWN_AT_AS_OF,
    ).result


def _inputs() -> EvaluationInputs:
    reader = _reader()
    price = _series(reader, phase3a.SEC_CONTINUOUS)
    benchmark = _series(reader, phase3a.SEC_RENAMED)
    return EvaluationInputs(
        as_of_time=AS_OF,
        environment=Environment.RESEARCH,
        security_id=phase3a.SEC_CONTINUOUS,
        evaluation_session=price.bars[-1].session_date,
        price_history=price,
        benchmark_history=benchmark,
    )


def test_the_brain_consumes_a_genuine_reader_result_and_reaches_a_valid_decision() -> None:
    intent = compile_candidate(_inputs(), _PriceOnlyBreakout())
    assert isinstance(intent.status, DecisionState)  # a member of the closed vocabulary
    assert intent.evidence is not None
    # The lineage references the real published dataset the reader served.
    assert intent.evidence.lineage.price_dataset_version == phase3a.DATASET_VERSION
    assert intent.evidence.coverage.resolved_profile is PROFILE


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
