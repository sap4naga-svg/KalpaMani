"""Closed vocabularies of the Strategy Brain.

Every vocabulary here is **closed**: a value outside it is a defect, not an
extension point. They are the mechanical form of the accepted Brain
specification (``docs/phase4/strategy-brain-specification.md``), and they live
in one module because a vocabulary duplicated in two places eventually
disagrees with itself.

Two of them carry a refusal list as well as a member list. The decision
states (specification section 7) exclude ``MAYBE``, ``BUY``, ``SELL``,
``EXECUTE`` and ``APPROVED_ORDER`` **by name**, because each reads as an
instruction and the Brain issues none. A vocabulary that merely omitted them
would invite the next author to add one; :func:`require_decision_state`
refuses them explicitly so the omission is a rule rather than an accident.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, TypeVar

from kalpamani.strategies.brain.errors import BrainContractError

Member = TypeVar("Member", bound=StrEnum)


def closed_member(vocabulary: type[Member], value: object) -> Member | None:
    """The exact member ``value`` names, or ``None``.

    Lookup goes through a table keyed by exact ``str`` data, so a bare string
    that happens to equal a member's value resolves to the member, an unknown
    string resolves to nothing, and no code belonging to ``value`` runs.
    """
    if isinstance(value, vocabulary):
        return value
    if type(value) is not str:
        return None
    table = {str.__str__(member): member for member in vocabulary}
    return table.get(value)


# ---------------------------------------------------------------------------
# Decision states (specification section 7)
# ---------------------------------------------------------------------------


class DecisionState(StrEnum):
    """The closed eight-member decision vocabulary.

    ``READY_FOR_RISK_REVIEW`` is not an approval to trade. It records the
    absence of a deterministic objection; portfolio and risk decide
    independently, and frequently refuse.
    """

    READY_FOR_RISK_REVIEW = "READY_FOR_RISK_REVIEW"
    WATCHLIST = "WATCHLIST"
    REJECTED = "REJECTED"
    BLOCKED_DATA = "BLOCKED_DATA"
    BLOCKED_EVENT = "BLOCKED_EVENT"
    BLOCKED_AI = "BLOCKED_AI"
    BLOCKED_CONTRADICTION = "BLOCKED_CONTRADICTION"
    BLOCKED_BORROW = "BLOCKED_BORROW"


#: States that read as instructions. Refused by name, never merely omitted.
FORBIDDEN_DECISION_STATE_NAMES: Final[frozenset[str]] = frozenset(
    {"MAYBE", "BUY", "SELL", "EXECUTE", "APPROVED_ORDER"}
)

#: The states in which the deterministic pipeline refused the candidate. A
#: deterministic failure cannot be rescued by AI (section 14.3); this set is
#: what "deterministic failure" means mechanically.
DETERMINISTIC_REFUSAL_STATES: Final[frozenset[DecisionState]] = frozenset(
    {
        DecisionState.REJECTED,
        DecisionState.BLOCKED_DATA,
        DecisionState.BLOCKED_EVENT,
        DecisionState.BLOCKED_BORROW,
        DecisionState.BLOCKED_CONTRADICTION,
    }
)


def require_decision_state(value: object) -> DecisionState:
    """``value`` as a :class:`DecisionState`, or a refusal at construction.

    Raises:
        BrainContractError: if ``value`` names no member. An instruction-shaped
            name is refused with its own message, so a reader can see that the
            omission is deliberate.
    """
    member = closed_member(DecisionState, value)
    if member is not None:
        return member
    if isinstance(value, str) and value in FORBIDDEN_DECISION_STATE_NAMES:
        raise BrainContractError(
            f"Decision state {value!r} is refused by name. It reads as an instruction, and the "
            "Brain issues none: its output is a status handed to portfolio and risk."
        )
    raise BrainContractError(
        f"Unknown decision state {value!r}. The vocabulary is closed; a state is added only "
        "where tracked architecture clearly requires it, through an ADR."
    )


# ---------------------------------------------------------------------------
# Direction, family, lifecycle, health
# ---------------------------------------------------------------------------


class Direction(StrEnum):
    """Which side of the market a candidate is on."""

    LONG = "LONG"
    SHORT = "SHORT"


class AlphaFamily(StrEnum):
    """Why a return exists economically (specification section 3.1)."""

    MOMENTUM_CONTINUATION = "MOMENTUM_CONTINUATION"
    EVENT_INFORMATION_DRIFT = "EVENT_INFORMATION_DRIFT"
    FUNDAMENTAL_DETERIORATION = "FUNDAMENTAL_DETERIORATION"


class LifecycleStage(StrEnum):
    """The strategy lifecycle (section 10). No code, backtest or AI output advances it."""

    IDEA = "IDEA"
    REGISTERED_HYPOTHESIS = "REGISTERED_HYPOTHESIS"
    TAXONOMY_OVERLAP_REVIEW = "TAXONOMY_OVERLAP_REVIEW"
    DATA_FEASIBILITY = "DATA_FEASIBILITY"
    BASELINE_RESEARCH = "BASELINE_RESEARCH"
    LOCKED_OUT_OF_SAMPLE_VALIDATION = "LOCKED_OUT_OF_SAMPLE_VALIDATION"
    SHADOW = "SHADOW"
    AUTOMATED_PAPER = "AUTOMATED_PAPER"
    MICRO_LIVE_CANARY = "MICRO_LIVE_CANARY"
    SCALED = "SCALED"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


#: Stages at which a version may produce a candidate at all. ``IDEA`` has no
#: registered hypothesis to evaluate against; ``SUSPENDED`` requires human
#: authority to leave; ``RETIRED`` is terminal for that version.
CANDIDATE_PRODUCING_STAGES: Final[frozenset[LifecycleStage]] = frozenset(
    {
        LifecycleStage.REGISTERED_HYPOTHESIS,
        LifecycleStage.TAXONOMY_OVERLAP_REVIEW,
        LifecycleStage.DATA_FEASIBILITY,
        LifecycleStage.BASELINE_RESEARCH,
        LifecycleStage.LOCKED_OUT_OF_SAMPLE_VALIDATION,
        LifecycleStage.SHADOW,
        LifecycleStage.AUTOMATED_PAPER,
        LifecycleStage.MICRO_LIVE_CANARY,
        LifecycleStage.SCALED,
        LifecycleStage.WATCH,
    }
)

#: Stages at which order-producing Paper operation may be authorized for a
#: version. ``AUTOMATED_PAPER`` is the first order-producing stage (section 10),
#: and reaching it requires human approval (section 25).
PAPER_ELIGIBLE_STAGES: Final[frozenset[LifecycleStage]] = frozenset(
    {
        LifecycleStage.AUTOMATED_PAPER,
        LifecycleStage.MICRO_LIVE_CANARY,
        LifecycleStage.SCALED,
        LifecycleStage.WATCH,
    }
)

#: Stages at which live operation may be authorized for a version. Live trading
#: is hard-disabled system-wide regardless; this is the lifecycle's own bound.
LIVE_ELIGIBLE_STAGES: Final[frozenset[LifecycleStage]] = frozenset(
    {LifecycleStage.MICRO_LIVE_CANARY, LifecycleStage.SCALED, LifecycleStage.WATCH}
)


class HealthState(StrEnum):
    """The strategy health machine (section 13)."""

    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    DEGRADED = "DEGRADED"
    NEW_ENTRIES_REDUCED = "NEW_ENTRIES_REDUCED"
    NEW_ENTRIES_DISABLED = "NEW_ENTRIES_DISABLED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


# ---------------------------------------------------------------------------
# The compiler stages (section 15), in order
# ---------------------------------------------------------------------------


class CompilerStage(StrEnum):
    """The thirteen validations of the deterministic decision compiler."""

    POINT_IN_TIME_REALITY_GATE = "POINT_IN_TIME_REALITY_GATE"
    AUTHORIZED_STRATEGY_VERSION = "AUTHORIZED_STRATEGY_VERSION"
    FACTOR_DEFINITION_VERSION = "FACTOR_DEFINITION_VERSION"
    REQUIRED_DATA_COVERAGE = "REQUIRED_DATA_COVERAGE"
    STRATEGY_AND_MODULE_ELIGIBILITY = "STRATEGY_AND_MODULE_ELIGIBILITY"
    TRADE_TEMPLATE_MATCH = "TRADE_TEMPLATE_MATCH"
    DUPLICATE_EXPOSURE_CONSOLIDATION = "DUPLICATE_EXPOSURE_CONSOLIDATION"
    AI_SCHEMA_AND_PROVENANCE = "AI_SCHEMA_AND_PROVENANCE"
    UNRESOLVED_CONTRADICTIONS = "UNRESOLVED_CONTRADICTIONS"
    MARKET_PERMISSION_CONTEXT = "MARKET_PERMISSION_CONTEXT"
    EVENT_AND_GAP_CONTEXT = "EVENT_AND_GAP_CONTEXT"
    SHORT_BORROW_PREREQUISITE = "SHORT_BORROW_PREREQUISITE"
    IMMUTABLE_REASON_CODE_CONSTRUCTION = "IMMUTABLE_REASON_CODE_CONSTRUCTION"


#: The accepted order. A later stage never runs after an earlier refusal.
COMPILER_STAGE_ORDER: Final[tuple[CompilerStage, ...]] = (
    CompilerStage.POINT_IN_TIME_REALITY_GATE,
    CompilerStage.AUTHORIZED_STRATEGY_VERSION,
    CompilerStage.FACTOR_DEFINITION_VERSION,
    CompilerStage.REQUIRED_DATA_COVERAGE,
    CompilerStage.STRATEGY_AND_MODULE_ELIGIBILITY,
    CompilerStage.TRADE_TEMPLATE_MATCH,
    CompilerStage.DUPLICATE_EXPOSURE_CONSOLIDATION,
    CompilerStage.AI_SCHEMA_AND_PROVENANCE,
    CompilerStage.UNRESOLVED_CONTRADICTIONS,
    CompilerStage.MARKET_PERMISSION_CONTEXT,
    CompilerStage.EVENT_AND_GAP_CONTEXT,
    CompilerStage.SHORT_BORROW_PREREQUISITE,
    CompilerStage.IMMUTABLE_REASON_CODE_CONSTRUCTION,
)


# ---------------------------------------------------------------------------
# Reason codes: closed, deterministic, never prose
# ---------------------------------------------------------------------------


class ReasonCode(StrEnum):
    """Every reason a candidate may carry. Closed; a status explains itself with these."""

    # -- the point-in-time reality gate --
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EVIDENCE_AS_OF_MISMATCH = "EVIDENCE_AS_OF_MISMATCH"
    SECURITY_MISMATCH = "SECURITY_MISMATCH"
    PROFILE_MISMATCH = "PROFILE_MISMATCH"
    PROFILE_DOWNGRADED = "PROFILE_DOWNGRADED"
    NON_POINT_IN_TIME_LIMITATION = "NON_POINT_IN_TIME_LIMITATION"
    RESOLUTION_MISMATCH = "RESOLUTION_MISMATCH"
    ADJUSTMENT_MODE_MISMATCH = "ADJUSTMENT_MODE_MISMATCH"
    LINEAGE_INCOMPLETE = "LINEAGE_INCOMPLETE"
    QUALITY_EVIDENCE_MISSING = "QUALITY_EVIDENCE_MISSING"
    OBSERVATION_AFTER_AS_OF = "OBSERVATION_AFTER_AS_OF"
    OBSERVATIONS_MISORDERED = "OBSERVATIONS_MISORDERED"
    DUPLICATE_OBSERVATION = "DUPLICATE_OBSERVATION"
    INVALID_BAR_VALUES = "INVALID_BAR_VALUES"
    STALE_PRICE_HISTORY = "STALE_PRICE_HISTORY"
    SESSION_GRID_MISMATCH = "SESSION_GRID_MISMATCH"
    UNIVERSE_SNAPSHOT_SESSION_MISMATCH = "UNIVERSE_SNAPSHOT_SESSION_MISMATCH"
    EVENT_EVIDENCE_UNRESOLVED = "EVENT_EVIDENCE_UNRESOLVED"
    MARKET_CONTEXT_UNRESOLVED = "MARKET_CONTEXT_UNRESOLVED"
    MARKET_CONTEXT_VERSION_UNPINNED = "MARKET_CONTEXT_VERSION_UNPINNED"
    # -- strategy version and factor definitions --
    STRATEGY_VERSION_MISMATCH = "STRATEGY_VERSION_MISMATCH"
    ENVIRONMENT_NOT_AUTHORIZED = "ENVIRONMENT_NOT_AUTHORIZED"
    LIFECYCLE_STAGE_NOT_CANDIDATE_PRODUCING = "LIFECYCLE_STAGE_NOT_CANDIDATE_PRODUCING"
    FACTOR_DEFINITION_VERSION_MISMATCH = "FACTOR_DEFINITION_VERSION_MISMATCH"
    # -- coverage --
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    # -- eligibility --
    UNIVERSE_NON_MEMBER = "UNIVERSE_NON_MEMBER"
    DIRECTION_NOT_SUPPORTED = "DIRECTION_NOT_SUPPORTED"
    TREND_NOT_ESTABLISHED = "TREND_NOT_ESTABLISHED"
    RELATIVE_STRENGTH_NOT_POSITIVE = "RELATIVE_STRENGTH_NOT_POSITIVE"
    BASE_NOT_COMPACT = "BASE_NOT_COMPACT"
    LIQUIDITY_BELOW_MINIMUM = "LIQUIDITY_BELOW_MINIMUM"
    # -- template --
    BREAKOUT_CONFIRMED = "BREAKOUT_CONFIRMED"
    BREAKOUT_NOT_CONFIRMED = "BREAKOUT_NOT_CONFIRMED"
    VOLUME_NOT_CONFIRMED = "VOLUME_NOT_CONFIRMED"
    # -- consolidation and contradictions --
    SINGLE_ATTRIBUTION = "SINGLE_ATTRIBUTION"
    CONSOLIDATED_ATTRIBUTIONS = "CONSOLIDATED_ATTRIBUTIONS"
    DIRECTION_CONTRADICTION = "DIRECTION_CONTRADICTION"
    # -- AI evidence --
    AI_EVIDENCE_NOT_REQUIRED = "AI_EVIDENCE_NOT_REQUIRED"
    AI_EVIDENCE_MISSING = "AI_EVIDENCE_MISSING"
    AI_EVIDENCE_MALFORMED = "AI_EVIDENCE_MALFORMED"
    AI_EVIDENCE_STALE = "AI_EVIDENCE_STALE"
    AI_EVIDENCE_ACCEPTED = "AI_EVIDENCE_ACCEPTED"
    AI_CHALLENGER_FALSIFIED = "AI_CHALLENGER_FALSIFIED"
    # -- market permission --
    MARKET_PERMISSION_GRANTED = "MARKET_PERMISSION_GRANTED"
    MARKET_ENTRY_DEFERRED = "MARKET_ENTRY_DEFERRED"
    MARKET_PERMISSION_DENIED = "MARKET_PERMISSION_DENIED"
    # -- event and gap --
    NO_KNOWN_EVENT_WITHIN_HORIZON = "NO_KNOWN_EVENT_WITHIN_HORIZON"
    EVENT_WITHIN_HOLDING_HORIZON = "EVENT_WITHIN_HOLDING_HORIZON"
    ENTRY_GAP_EXCEEDS_LIMIT = "ENTRY_GAP_EXCEEDS_LIMIT"
    # -- borrow --
    BORROW_NOT_APPLICABLE_LONG = "BORROW_NOT_APPLICABLE_LONG"
    BORROW_CONTEXT_MISSING = "BORROW_CONTEXT_MISSING"
    BORROW_STATE_UNKNOWN = "BORROW_STATE_UNKNOWN"
    BORROW_QUALIFIED = "BORROW_QUALIFIED"
    # -- completion --
    ALL_DETERMINISTIC_REQUIREMENTS_SATISFIED = "ALL_DETERMINISTIC_REQUIREMENTS_SATISFIED"


# ---------------------------------------------------------------------------
# Evidence and context vocabularies
# ---------------------------------------------------------------------------


class DataDomain(StrEnum):
    """A kind of evidence a strategy version may declare required or optional."""

    PRICE_BARS = "PRICE_BARS"
    BENCHMARK_BARS = "BENCHMARK_BARS"
    UNIVERSE_MEMBERSHIP = "UNIVERSE_MEMBERSHIP"
    EVENT_CALENDAR = "EVENT_CALENDAR"
    MARKET_PERMISSION = "MARKET_PERMISSION"
    SECTOR_CLASSIFICATION = "SECTOR_CLASSIFICATION"
    AI_RESEARCH = "AI_RESEARCH"
    BORROW = "BORROW"


class EvidenceState(StrEnum):
    """Whether a context record resolved its question. ``UNAVAILABLE`` blocks; it never defaults."""

    RESOLVED = "RESOLVED"
    UNAVAILABLE = "UNAVAILABLE"


class Requirement(StrEnum):
    """Whether a strategy version needs a kind of evidence."""

    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MarketPermission(StrEnum):
    """What the versioned market context permits for new entries on one side."""

    PERMITTED = "PERMITTED"
    DEFERRED = "DEFERRED"
    DENIED = "DENIED"


class EventTimestampQuality(StrEnum):
    """How precisely an upcoming event's time is known (section 19)."""

    EXACT = "EXACT"
    DATE_ONLY = "DATE_ONLY"
    UNKNOWN = "UNKNOWN"


class EarningsCarryPermission(StrEnum):
    """Whether a position may be carried through a scheduled earnings event.

    Only ``NOT_PERMITTED`` exists: Breakout and Pullback do not carry through
    earnings unless a separately researched and separately authorized rule
    permits it (section 19), and no such rule exists.
    """

    NOT_PERMITTED = "NOT_PERMITTED"


class RankState(StrEnum):
    """Whether a cross-sectional rank exists for a candidate."""

    NOT_COMPUTED = "NOT_COMPUTED"
    COMPUTED = "COMPUTED"


class SectorClusterState(StrEnum):
    """Whether a sector or correlation cluster was resolved for a candidate."""

    UNAVAILABLE = "UNAVAILABLE"
    RESOLVED = "RESOLVED"


class ChallengerVerdict(StrEnum):
    """The one thing a Challenger output may do to a candidate: remove it."""

    NOT_FALSIFIED = "NOT_FALSIFIED"
    FALSIFIED = "FALSIFIED"


class ModuleVerdict(StrEnum):
    """What a strategy module concluded about one security at one instant."""

    TRIGGERED = "TRIGGERED"
    SETUP_NOT_TRIGGERED = "SETUP_NOT_TRIGGERED"
    INELIGIBLE = "INELIGIBLE"
    GAP_CONSTRAINT = "GAP_CONSTRAINT"


class EntryCondition(StrEnum):
    """Closed entry-condition vocabulary. A condition is named, never described in prose."""

    CLOSE_ABOVE_BASE_HIGH_WITH_VOLUME_CONFIRMATION = (
        "CLOSE_ABOVE_BASE_HIGH_WITH_VOLUME_CONFIRMATION"
    )


class InvalidationCondition(StrEnum):
    """Closed invalidation-condition vocabulary."""

    CLOSE_BELOW_BASE_LOW = "CLOSE_BELOW_BASE_LOW"


class StopReferenceKind(StrEnum):
    """What level a technical stop *reference* names. A reference, never an order."""

    BASE_LOW = "BASE_LOW"


class BorrowAvailability(StrEnum):
    """Borrow availability as observed evidence. ``UNKNOWN`` blocks."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class BorrowFeeState(StrEnum):
    """Borrow fee state. ``UNKNOWN`` blocks."""

    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    UNKNOWN = "UNKNOWN"


class SqueezeState(StrEnum):
    """Squeeze and crowding state. ``UNKNOWN`` blocks."""

    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    UNKNOWN = "UNKNOWN"


class ShortSaleRestrictionState(StrEnum):
    """Regulation SHO short-sale restriction state. ``UNKNOWN`` blocks."""

    NOT_IN_EFFECT = "NOT_IN_EFFECT"
    IN_EFFECT = "IN_EFFECT"
    UNKNOWN = "UNKNOWN"


class RecallRiskState(StrEnum):
    """Recall and buy-in risk state. ``UNKNOWN`` blocks."""

    LOW = "LOW"
    ELEVATED = "ELEVATED"
    UNKNOWN = "UNKNOWN"


class FactorFamily(StrEnum):
    """The five factor families of the deterministic factor matrix (section 5.1)."""

    PRICE_MOMENTUM = "PRICE_MOMENTUM"
    EVENT_EARNINGS = "EVENT_EARNINGS"
    PRICE_VOLUME_QUALITY = "PRICE_VOLUME_QUALITY"
    FUNDAMENTAL_QUALITY = "FUNDAMENTAL_QUALITY"
    RISK_CONTEXT = "RISK_CONTEXT"


__all__ = [
    "CANDIDATE_PRODUCING_STAGES",
    "COMPILER_STAGE_ORDER",
    "DETERMINISTIC_REFUSAL_STATES",
    "FORBIDDEN_DECISION_STATE_NAMES",
    "LIVE_ELIGIBLE_STAGES",
    "PAPER_ELIGIBLE_STAGES",
    "AlphaFamily",
    "BorrowAvailability",
    "BorrowFeeState",
    "ChallengerVerdict",
    "CompilerStage",
    "DataDomain",
    "DecisionState",
    "Direction",
    "EarningsCarryPermission",
    "EntryCondition",
    "EventTimestampQuality",
    "EvidenceState",
    "FactorFamily",
    "HealthState",
    "InvalidationCondition",
    "LifecycleStage",
    "MarketPermission",
    "ModuleVerdict",
    "RankState",
    "ReasonCode",
    "RecallRiskState",
    "Requirement",
    "SectorClusterState",
    "ShortSaleRestrictionState",
    "SqueezeState",
    "StopReferenceKind",
    "closed_member",
    "require_decision_state",
]
