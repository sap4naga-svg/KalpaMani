"""``CandidateIntent`` -- the terminal output of the Brain, and the whole of it.

Specification section 6, as a type. Every record here is frozen, slotted and
subclass-refusing; every string is an identifier under one grammar; every
number is a finite ``Decimal``; every state is a closed vocabulary member. A
record that fails any of those is refused at construction, never repaired.

**What is structurally absent.** There is no field whose meaning is a share
count, a dollar amount, a final position size, an order type, a route, a
client order id, a broker order id, a credential, an account number or an
execution instruction -- and no field that could carry one by another name:
the identifier grammar admits no whitespace, so no sentence fits anywhere. A
downstream layer that wanted to read Brain output as a broker ticket would
find nothing to read. The technical stop is a :class:`LevelReference` -- a
level and where it came from -- and constructing a protective order from it
is execution's work under ADR-0004.

**What a status requires.** ``READY_FOR_RISK_REVIEW`` may be constructed only
with every stage passed, every evidence section present and no contradiction.
``WATCHLIST`` requires the thesis and the evidence that support it. Blocked and
rejected states carry their reason codes and the stage that concluded them,
and may leave later sections empty because those stages never ran.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TypeVar

from kalpamani.common.environment import Environment
from kalpamani.data.contracts.vocabulary import InformationSetProfile, LimitationToken
from kalpamani.strategies.brain.errors import BrainContractError
from kalpamani.strategies.brain.evidence import ShortContext
from kalpamani.strategies.brain.factors import FactorValue
from kalpamani.strategies.brain.identity import (
    CANDIDATE_ID_PATTERN,
    require_finite_decimal,
    require_identifier,
    require_instant,
    require_non_negative_int,
    require_optional_identifier,
    require_positive_int,
    require_unit_interval,
)
from kalpamani.strategies.brain.vocabulary import (
    COMPILER_STAGE_ORDER,
    DETERMINISTIC_REFUSAL_STATES,
    AlphaFamily,
    CompilerStage,
    DecisionState,
    Direction,
    EarningsCarryPermission,
    EntryCondition,
    EventTimestampQuality,
    FactorFamily,
    InvalidationCondition,
    MarketPermission,
    ModuleVerdict,
    RankState,
    ReasonCode,
    Requirement,
    SectorClusterState,
    StopReferenceKind,
    closed_member,
    require_decision_state,
)

Member = TypeVar("Member", bound=StrEnum)


def _member(vocabulary: type[Member], value: object, *, field: str) -> Member:
    member = closed_member(vocabulary, value)
    if member is None:
        raise BrainContractError(f"Field {field!r} must be a {vocabulary.__name__} member.")
    return member


def _optional_member(vocabulary: type[Member], value: object, *, field: str) -> Member | None:
    return None if value is None else _member(vocabulary, value, field=field)


def _date(value: object, *, field: str) -> date:
    if type(value) is not date:
        raise BrainContractError(f"Field {field!r} must be a calendar date, not an instant.")
    return value


def _optional_date(value: object, *, field: str) -> date | None:
    return None if value is None else _date(value, field=field)


def _refuse_subclass(name: str) -> None:
    raise TypeError(f"{name} may not be subclassed: a subclass could add a field.")


# ---------------------------------------------------------------------------
# Strategy attribution
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleAttribution:
    """One contributing module's evidence path, preserved through consolidation."""

    strategy_id: str
    strategy_version: str
    trade_template: str
    verdict: ModuleVerdict
    rank: int

    def __init_subclass__(cls, **kwargs: object) -> None:
        _refuse_subclass("ModuleAttribution")

    def __post_init__(self) -> None:
        require_identifier(self.strategy_id, field="strategy_id")
        require_identifier(self.strategy_version, field="strategy_version")
        require_identifier(self.trade_template, field="trade_template")
        object.__setattr__(self, "verdict", _member(ModuleVerdict, self.verdict, field="verdict"))
        require_positive_int(self.rank, field="rank")


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyAttribution:
    """Family, module, template and pinned versions, with every contributing path."""

    alpha_family: AlphaFamily
    strategy_id: str
    strategy_module: str
    trade_template: str
    strategy_version: str
    factor_definition_version: str
    contributing: tuple[ModuleAttribution, ...]

    def __init_subclass__(cls, **kwargs: object) -> None:
        _refuse_subclass("StrategyAttribution")

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "alpha_family", _member(AlphaFamily, self.alpha_family, field="alpha_family"))
        require_identifier(self.strategy_id, field="strategy_id")
        require_identifier(self.strategy_module, field="strategy_module")
        require_identifier(self.trade_template, field="trade_template")
        require_identifier(self.strategy_version, field="strategy_version")
        require_identifier(self.factor_definition_version, field="factor_definition_version")
        contributing = tuple(self.contributing)
        if not contributing or any(type(c) is not ModuleAttribution for c in contributing):
            raise BrainContractError("contributing must be a non-empty tuple of ModuleAttribution.")
        ranks = [c.rank for c in contributing]
        if ranks != list(range(1, len(ranks) + 1)):
            raise BrainContractError("contributing attributions must be ranked 1..n without gaps.")
        if contributing[0].strategy_id != self.strategy_id:
            raise BrainContractError("The primary attribution must be the candidate's own module.")
        set_(self, "contributing", contributing)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class RankEvidence:
    """Cross-sectional rank and its metadata, or an explicit statement that none exists."""

    state: RankState
    rank: int | None
    population: int | None

    def __init_subclass__(cls, **kwargs: object) -> None:
        _refuse_subclass("RankEvidence")

    def __post_init__(self) -> None:
        state = _member(RankState, self.state, field="state")
        object.__setattr__(self, "state", state)
        if state is RankState.COMPUTED:
            rank = require_positive_int(self.rank, field="rank")
            population = require_positive_int(self.population, field="population")
            if rank > population:
                raise BrainContractError("A rank cannot exceed the population it was taken from.")
        elif self.rank is not None or self.population is not None:
            raise BrainContractError("A NOT_COMPUTED rank carries no rank and no population.")


@dataclass(frozen=True, slots=True, kw_only=True)
class CoverageEvidence:
    """What history the decision had, under which profile, from which publication."""

    sessions_available: int
    sessions_required: int
    first_session: date
    last_session: date
    resolved_profile: InformationSetProfile
    dataset_version: str
    manifest_hash: str
    quality_report_hash: str
    limitations: tuple[LimitationToken, ...]

    def __init_subclass__(cls, **kwargs: object) -> None:
        _refuse_subclass("CoverageEvidence")

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        require_non_negative_int(self.sessions_available, field="sessions_available")
        require_positive_int(self.sessions_required, field="sessions_required")
        set_(self, "first_session", _date(self.first_session, field="first_session"))
        set_(self, "last_session", _date(self.last_session, field="last_session"))
        if self.first_session > self.last_session:
            raise BrainContractError("first_session must not follow last_session.")
        set_(
            self,
            "resolved_profile",
            _member(InformationSetProfile, self.resolved_profile, field="resolved_profile"),
        )
        require_identifier(self.dataset_version, field="dataset_version")
        require_identifier(self.manifest_hash, field="manifest_hash")
        require_identifier(self.quality_report_hash, field="quality_report_hash")
        set_(
            self,
            "limitations",
            tuple(_member(LimitationToken, v, field="limitations") for v in self.limitations),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class LineageReferences:
    """Every source the decision read, by identity. References, never rows."""

    price_dataset_version: str
    price_manifest_hash: str
    price_quality_report_hash: str
    benchmark_security_id: str | None
    benchmark_dataset_version: str | None
    benchmark_manifest_hash: str | None
    universe_snapshot_artifact_id: str | None
    universe_snapshot_content_hash: str | None
    universe_definition_version: str | None
    event_source_reference: str | None
    market_context_version: str | None
    market_regime_reference: str | None

    def __init_subclass__(cls, **kwargs: object) -> None:
        _refuse_subclass("LineageReferences")

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name.startswith("price_"):
                require_identifier(value, field=field.name)
            else:
                require_optional_identifier(value, field=field.name)


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceSummary:
    """The factor snapshot, its reference, the rank, the coverage and the lineage."""

    factor_snapshot: tuple[FactorValue, ...]
    factor_vector_reference: str
    setup_quality: tuple[FactorValue, ...]
    rank: RankEvidence
    coverage: CoverageEvidence
    lineage: LineageReferences

    def __init_subclass__(cls, **kwargs: object) -> None:
        _refuse_subclass("EvidenceSummary")

    def __post_init__(self) -> None:
        snapshot = tuple(self.factor_snapshot)
        if not snapshot or any(type(v) is not FactorValue for v in snapshot):
            raise BrainContractError("factor_snapshot must be a non-empty tuple of FactorValue.")
        if len({v.definition.factor_id for v in snapshot}) != len(snapshot):
            raise BrainContractError("factor_snapshot must not repeat a factor id.")
        object.__setattr__(self, "factor_snapshot", snapshot)
        require_identifier(self.factor_vector_reference, field="factor_vector_reference")
        quality = tuple(self.setup_quality)
        if any(v not in snapshot for v in quality):
            raise BrainContractError("setup_quality must be drawn from the factor snapshot.")
        object.__setattr__(self, "setup_quality", quality)
        if type(self.rank) is not RankEvidence:
            raise BrainContractError("Field 'rank' must be a RankEvidence.")
        if type(self.coverage) is not CoverageEvidence:
            raise BrainContractError("Field 'coverage' must be a CoverageEvidence.")
        if type(self.lineage) is not LineageReferences:
            raise BrainContractError("Field 'lineage' must be a LineageReferences.")


# ---------------------------------------------------------------------------
# AI, thesis, risk context
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class AiEvidenceReference:
    """References to AI output and its provenance -- or an explicit statement of none.

    A ``NOT_REQUIRED`` reference with no output records that the version needs
    no AI evidence. A reference carrying output must carry all of its
    provenance: source publish time, model version, prompt version, schema
    version, confidence and evidence quality (section 14.3).
    """

    requirement: Requirement
    research_output_reference: str | None
    challenger_output_reference: str | None
    source_publish_time: datetime | None
    model_version: str | None
    prompt_version: str | None
    schema_version: str | None
    confidence: Decimal | None
    evidence_quality: Decimal | None

    def __init_subclass__(cls, **kwargs: object) -> None:
        _refuse_subclass("AiEvidenceReference")

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        requirement = _member(Requirement, self.requirement, field="requirement")
        set_(self, "requirement", requirement)
        provenance = (
            self.research_output_reference,
            self.challenger_output_reference,
            self.source_publish_time,
            self.model_version,
            self.prompt_version,
            self.schema_version,
            self.confidence,
            self.evidence_quality,
        )
        if all(value is None for value in provenance):
            if requirement is Requirement.REQUIRED:
                raise BrainContractError("A REQUIRED AI reference must carry the AI output.")
            return
        if any(value is None for value in provenance):
            raise BrainContractError(
                "An AI reference carrying output must carry all of its provenance: both output "
                "references, the source publish time, the model, prompt and schema versions, "
                "the confidence and the evidence quality."
            )
        require_identifier(self.research_output_reference, field="research_output_reference")
        require_identifier(self.challenger_output_reference, field="challenger_output_reference")
        set_(
            self,
            "source_publish_time",
            require_instant(self.source_publish_time, field="source_publish_time"),
        )
        require_identifier(self.model_version, field="model_version")
        require_identifier(self.prompt_version, field="prompt_version")
        require_identifier(self.schema_version, field="schema_version")
        set_(self, "confidence", require_unit_interval(self.confidence, field="confidence"))
        set_(
            self,
            "evidence_quality",
            require_unit_interval(self.evidence_quality, field="evidence_quality"),
        )

    @property
    def carries_output(self) -> bool:
        """Whether any AI output is referenced."""
        return self.research_output_reference is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class LevelReference:
    """A price level and where it came from. A reference, never an order."""

    kind: StopReferenceKind
    level: Decimal
    derived_from_first_session: date
    derived_from_last_session: date

    def __init_subclass__(cls, **kwargs: object) -> None:
        _refuse_subclass("LevelReference")

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "kind", _member(StopReferenceKind, self.kind, field="kind"))
        level = require_finite_decimal(self.level, field="level")
        if level <= 0:
            raise BrainContractError("A level reference must be a positive price.")
        set_(
            self,
            "derived_from_first_session",
            _date(self.derived_from_first_session, field="derived_from_first_session"),
        )
        set_(
            self,
            "derived_from_last_session",
            _date(self.derived_from_last_session, field="derived_from_last_session"),
        )
        if self.derived_from_first_session > self.derived_from_last_session:
            raise BrainContractError("A level's derivation window must be ordered.")


@dataclass(frozen=True, slots=True, kw_only=True)
class TradeThesis:
    """Why enter now, what would invalidate it, and for how long (section 6.1)."""

    entry_condition: EntryCondition
    entry_reference_level: Decimal
    invalidation_condition: InvalidationCondition
    technical_stop_reference: LevelReference
    expected_holding_sessions: int
    minimum_holding_sessions: int
    maximum_holding_sessions: int

    def __init_subclass__(cls, **kwargs: object) -> None:
        _refuse_subclass("TradeThesis")

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(
            self,
            "entry_condition",
            _member(EntryCondition, self.entry_condition, field="entry_condition"),
        )
        level = require_finite_decimal(self.entry_reference_level, field="entry_reference_level")
        if level <= 0:
            raise BrainContractError("entry_reference_level must be a positive price.")
        set_(
            self,
            "invalidation_condition",
            _member(
                InvalidationCondition, self.invalidation_condition, field="invalidation_condition"
            ),
        )
        if type(self.technical_stop_reference) is not LevelReference:
            raise BrainContractError("technical_stop_reference must be a LevelReference.")
        if self.technical_stop_reference.level >= level:
            raise BrainContractError(
                "The invalidation level of a long thesis must lie below its entry reference."
            )
        require_positive_int(self.minimum_holding_sessions, field="minimum_holding_sessions")
        require_positive_int(self.maximum_holding_sessions, field="maximum_holding_sessions")
        require_positive_int(self.expected_holding_sessions, field="expected_holding_sessions")
        if not (
            self.minimum_holding_sessions
            <= self.expected_holding_sessions
            <= self.maximum_holding_sessions
        ):
            raise BrainContractError("expected_holding_sessions must lie within its horizon.")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskContext:
    """What downstream risk logic must know. Context and tags -- never a size."""

    upcoming_event_flag: bool
    next_event_session: date | None
    event_timestamp_quality: EventTimestampQuality
    gap_risk_estimate: Decimal
    entry_gap_fraction: Decimal
    earnings_carry_permission: EarningsCarryPermission
    liquidity_average_dollar_volume: Decimal
    family_exposure: AlphaFamily
    factor_exposures: tuple[FactorFamily, ...]
    sector_cluster: SectorClusterState
    sector_cluster_reference: str | None
    market_permission_version: str | None
    market_permission: MarketPermission | None

    def __init_subclass__(cls, **kwargs: object) -> None:
        _refuse_subclass("RiskContext")

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        if type(self.upcoming_event_flag) is not bool:
            raise BrainContractError("upcoming_event_flag must be a bool.")
        set_(
            self,
            "next_event_session",
            _optional_date(self.next_event_session, field="next_event_session"),
        )
        set_(
            self,
            "event_timestamp_quality",
            _member(
                EventTimestampQuality, self.event_timestamp_quality, field="event_timestamp_quality"
            ),
        )
        gap = require_finite_decimal(self.gap_risk_estimate, field="gap_risk_estimate")
        if gap < 0:
            raise BrainContractError(
                "gap_risk_estimate is an absolute fraction and cannot be negative."
            )
        require_finite_decimal(self.entry_gap_fraction, field="entry_gap_fraction")
        set_(
            self,
            "earnings_carry_permission",
            _member(
                EarningsCarryPermission,
                self.earnings_carry_permission,
                field="earnings_carry_permission",
            ),
        )
        liquidity = require_finite_decimal(
            self.liquidity_average_dollar_volume, field="liquidity_average_dollar_volume"
        )
        if liquidity < 0:
            raise BrainContractError("liquidity_average_dollar_volume cannot be negative.")
        set_(
            self,
            "family_exposure",
            _member(AlphaFamily, self.family_exposure, field="family_exposure"),
        )
        exposures = tuple(
            _member(FactorFamily, value, field="factor_exposures")
            for value in self.factor_exposures
        )
        if not exposures:
            raise BrainContractError("factor_exposures must name at least one family.")
        set_(self, "factor_exposures", exposures)
        cluster = _member(SectorClusterState, self.sector_cluster, field="sector_cluster")
        set_(self, "sector_cluster", cluster)
        reference = require_optional_identifier(
            self.sector_cluster_reference, field="sector_cluster_reference"
        )
        if (cluster is SectorClusterState.RESOLVED) != (reference is not None):
            raise BrainContractError(
                "A resolved sector cluster carries a reference; an unresolved one none."
            )
        version = require_optional_identifier(
            self.market_permission_version, field="market_permission_version"
        )
        permission = _optional_member(
            MarketPermission, self.market_permission, field="market_permission"
        )
        if (version is None) != (permission is None):
            raise BrainContractError("Market permission and its version are recorded together.")
        set_(self, "market_permission", permission)


# ---------------------------------------------------------------------------
# The intent
# ---------------------------------------------------------------------------


#: Statuses at which a real setup stands: the evidence and risk context were
#: established even though the candidate is not (yet) handed on. ``WATCHLIST``
#: carries a thesis only when it reached one -- an eligible-but-untriggered
#: setup has no confirmed entry level, a deferred market has one.
_SETUP_STANDS_STATES = frozenset({DecisionState.READY_FOR_RISK_REVIEW, DecisionState.WATCHLIST})


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateIntent:
    """An immutable typed record: the terminal output of the Brain (section 6).

    ``concluded_at_stage`` is the compiler stage that produced ``status``;
    ``stages_passed`` are the stages before it, in the accepted order. A
    ``READY_FOR_RISK_REVIEW`` intent has passed all twelve validations and
    concluded at the thirteenth.
    """

    candidate_id: str
    security_id: str
    as_of_time: datetime
    evaluation_session: date
    direction: Direction
    environment: Environment
    strategy: StrategyAttribution
    status: DecisionState
    reason_codes: tuple[ReasonCode, ...]
    concluded_at_stage: CompilerStage
    stages_passed: tuple[CompilerStage, ...]
    contradictions: tuple[ReasonCode, ...]
    evidence: EvidenceSummary | None
    ai: AiEvidenceReference
    thesis: TradeThesis | None
    risk_context: RiskContext | None
    short_context: ShortContext | None

    def __init_subclass__(cls, **kwargs: object) -> None:
        _refuse_subclass("CandidateIntent")

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        if (
            type(self.candidate_id) is not str
            or CANDIDATE_ID_PATTERN.fullmatch(self.candidate_id) is None
        ):
            raise BrainContractError("candidate_id must be a derived 'ci-<16 hex>' identifier.")
        require_identifier(self.security_id, field="security_id")
        set_(self, "as_of_time", require_instant(self.as_of_time, field="as_of_time"))
        set_(
            self,
            "evaluation_session",
            _date(self.evaluation_session, field="evaluation_session"),
        )
        set_(self, "direction", _member(Direction, self.direction, field="direction"))
        set_(self, "environment", _member(Environment, self.environment, field="environment"))
        if type(self.strategy) is not StrategyAttribution:
            raise BrainContractError("Field 'strategy' must be a StrategyAttribution.")
        status = require_decision_state(self.status)
        set_(self, "status", status)
        reasons = tuple(_member(ReasonCode, r, field="reason_codes") for r in self.reason_codes)
        if not reasons or len(set(reasons)) != len(reasons):
            raise BrainContractError("reason_codes must be a non-empty tuple without repeats.")
        set_(self, "reason_codes", reasons)
        concluded = _member(CompilerStage, self.concluded_at_stage, field="concluded_at_stage")
        set_(self, "concluded_at_stage", concluded)
        passed = tuple(_member(CompilerStage, s, field="stages_passed") for s in self.stages_passed)
        expected = COMPILER_STAGE_ORDER[: COMPILER_STAGE_ORDER.index(concluded)]
        if passed != expected:
            raise BrainContractError(
                "stages_passed must be exactly the accepted stages before the concluding one, in "
                "order. A later stage never runs after an earlier refusal."
            )
        set_(self, "stages_passed", passed)
        contradictions = tuple(
            _member(ReasonCode, r, field="contradictions") for r in self.contradictions
        )
        set_(self, "contradictions", contradictions)
        if self.evidence is not None and type(self.evidence) is not EvidenceSummary:
            raise BrainContractError("Field 'evidence' must be an EvidenceSummary or None.")
        if type(self.ai) is not AiEvidenceReference:
            raise BrainContractError("Field 'ai' must be an AiEvidenceReference.")
        if self.thesis is not None and type(self.thesis) is not TradeThesis:
            raise BrainContractError("Field 'thesis' must be a TradeThesis or None.")
        if self.risk_context is not None and type(self.risk_context) is not RiskContext:
            raise BrainContractError("Field 'risk_context' must be a RiskContext or None.")
        if self.short_context is not None and type(self.short_context) is not ShortContext:
            raise BrainContractError("Field 'short_context' must be a ShortContext or None.")
        self._require_status_consistency(status, concluded)

    def _require_status_consistency(self, status: DecisionState, concluded: CompilerStage) -> None:
        if status in _SETUP_STANDS_STATES:
            if self.evidence is None or self.risk_context is None:
                raise BrainContractError(
                    f"A {status.value} intent must carry its evidence and risk context."
                )
        if status is DecisionState.READY_FOR_RISK_REVIEW:
            if self.thesis is None:
                raise BrainContractError("A READY_FOR_RISK_REVIEW intent must carry its thesis.")
            if concluded is not CompilerStage.IMMUTABLE_REASON_CODE_CONSTRUCTION:
                raise BrainContractError(
                    "READY_FOR_RISK_REVIEW is produced only by the final stage, after every "
                    "other validation passed."
                )
            if ReasonCode.ALL_DETERMINISTIC_REQUIREMENTS_SATISFIED not in self.reason_codes:
                raise BrainContractError(
                    "A READY intent records that every requirement was satisfied."
                )
            if self.contradictions:
                raise BrainContractError("A READY intent carries no unresolved contradiction.")
            if self.direction is Direction.SHORT and (
                self.short_context is None or not self.short_context.is_fully_qualified
            ):
                raise BrainContractError(
                    "A READY short intent must carry a fully qualified short context."
                )
        elif concluded is CompilerStage.IMMUTABLE_REASON_CODE_CONSTRUCTION:
            raise BrainContractError("Only READY_FOR_RISK_REVIEW concludes at the final stage.")
        if self.direction is Direction.LONG and self.short_context is not None:
            raise BrainContractError("A LONG intent carries no short context.")

    @property
    def is_deterministic_refusal(self) -> bool:
        """Whether the deterministic pipeline refused this candidate (section 14.3)."""
        return self.status in DETERMINISTIC_REFUSAL_STATES


__all__ = [
    "AiEvidenceReference",
    "CandidateIntent",
    "CoverageEvidence",
    "EvidenceSummary",
    "LevelReference",
    "LineageReferences",
    "ModuleAttribution",
    "RankEvidence",
    "RiskContext",
    "StrategyAttribution",
    "TradeThesis",
]
