"""What the Brain evaluates: point-in-time kernel results plus explicit context.

The price and universe evidence are the kernel's own result types --
:class:`~kalpamani.data.pit.accessors.BarSeriesResult` and
:class:`~kalpamani.data.pit.accessors.UniverseSnapshotResult` -- taken exactly
as a :class:`~kalpamani.data.pit.accessors.PointInTimeReader` returns them,
with their :class:`~kalpamani.data.pit.accessors.ResultProvenance` attached.
The Brain defines no parallel bar schema: a second schema is a second place for
a look-ahead to hide.

The context records below are the Brain's own, because no accepted kernel
entity exists yet for events, market permission, AI output or borrow (filings,
earnings and borrow are Phase 3B/3C). Each is a **contract for evidence a
module may declare it requires**, and each carries an explicit
:class:`~kalpamani.strategies.brain.vocabulary.EvidenceState` where the
question may be unanswerable -- ``UNAVAILABLE`` is a value the gate blocks on,
never a default it fills in. Where the evidence would come from in production
is a later decision this slice does not make.

One record deliberately validates nothing at construction.
:class:`AiEvidenceRecord` is the raw shape an AI output arrives in; the
compiler classifies a malformed or stale one as ``BLOCKED_AI`` (specification
section 26) so that the refusal is journaled with a reason rather than raised
as a crash.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TypeVar

from kalpamani.common.environment import Environment
from kalpamani.data.pit.accessors import BarSeriesResult, UniverseSnapshotResult
from kalpamani.strategies.brain.errors import BrainContractError
from kalpamani.strategies.brain.identity import require_identifier, require_instant
from kalpamani.strategies.brain.vocabulary import (
    BorrowAvailability,
    BorrowFeeState,
    ChallengerVerdict,
    EventTimestampQuality,
    EvidenceState,
    MarketPermission,
    RecallRiskState,
    ShortSaleRestrictionState,
    SqueezeState,
    closed_member,
)

Member = TypeVar("Member", bound=StrEnum)


def _member(vocabulary: type[Member], value: object, *, field: str) -> Member:
    member = closed_member(vocabulary, value)
    if member is None:
        raise BrainContractError(f"Field {field!r} must be a {vocabulary.__name__} member.")
    return member


def _date(value: object, *, field: str) -> date:
    # ``datetime`` is a ``date`` subclass, and conflating the two is the promotion
    # the kernel forbids: a business date is never silently an instant.
    if type(value) is not date:
        raise BrainContractError(f"Field {field!r} must be a calendar date, not an instant.")
    return value


def _optional_date(value: object, *, field: str) -> date | None:
    return None if value is None else _date(value, field=field)


@dataclass(frozen=True, slots=True, kw_only=True)
class EventContext:
    """The scheduled-event evidence a module may require (section 19).

    ``coverage_through_session`` states how far ahead the source could see: an
    absence of a known event is only evidence up to that session. A record
    whose coverage does not reach the strategy's holding horizon does not say
    "no event"; it says "unknown", and the gate blocks on it.
    """

    state: EvidenceState
    as_of: datetime
    source_reference: str
    coverage_through_session: date | None
    next_event_session: date | None
    timestamp_quality: EventTimestampQuality

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "state", _member(EvidenceState, self.state, field="state"))
        set_(self, "as_of", require_instant(self.as_of, field="as_of"))
        require_identifier(self.source_reference, field="source_reference")
        set_(
            self,
            "coverage_through_session",
            _optional_date(self.coverage_through_session, field="coverage_through_session"),
        )
        set_(
            self,
            "next_event_session",
            _optional_date(self.next_event_session, field="next_event_session"),
        )
        set_(
            self,
            "timestamp_quality",
            _member(EventTimestampQuality, self.timestamp_quality, field="timestamp_quality"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketPermissionContext:
    """A versioned ``MarketRegime`` / ``MarketPermission`` context (section 18).

    The Brain records it, may block, defer or tag on it, and never scales
    exposure from it. ``version`` is a pin: an unversioned context cannot be
    replayed, and the gate refuses one.
    """

    version: str
    as_of: datetime
    regime_reference: str
    permission_long: MarketPermission
    permission_short: MarketPermission

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        require_identifier(self.version, field="version")
        set_(self, "as_of", require_instant(self.as_of, field="as_of"))
        require_identifier(self.regime_reference, field="regime_reference")
        set_(
            self,
            "permission_long",
            _member(MarketPermission, self.permission_long, field="permission_long"),
        )
        set_(
            self,
            "permission_short",
            _member(MarketPermission, self.permission_short, field="permission_short"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AiEvidenceRecord:
    """An AI output as it arrives, before the compiler has judged its schema.

    **Nothing is validated here on purpose.** Every field is optional so a
    malformed output can be handed to the compiler and refused there as
    ``BLOCKED_AI`` with a reason code, which is what section 26 requires. A
    record that raised at construction would leave no journal entry.
    """

    research_output_reference: str | None = None
    challenger_output_reference: str | None = None
    source_publish_time: datetime | None = None
    produced_at: datetime | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    schema_version: str | None = None
    confidence: Decimal | None = None
    evidence_quality: Decimal | None = None
    challenger_verdict: ChallengerVerdict | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ShortContext:
    """The required short context (section 20). Every ``UNKNOWN`` blocks.

    Borrow is never inferred from price behaviour: this record is observed
    evidence with a reference, and a candidate whose borrow state is unknown is
    blocked rather than assumed. The live pre-submit borrow recheck belongs to
    execution and risk, not here.
    """

    as_of: datetime
    evidence_reference: str
    borrow_availability: BorrowAvailability
    borrow_fee: BorrowFeeState
    squeeze: SqueezeState
    short_sale_restriction: ShortSaleRestrictionState
    recall_risk: RecallRiskState

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "as_of", require_instant(self.as_of, field="as_of"))
        require_identifier(self.evidence_reference, field="evidence_reference")
        set_(
            self,
            "borrow_availability",
            _member(BorrowAvailability, self.borrow_availability, field="borrow_availability"),
        )
        set_(self, "borrow_fee", _member(BorrowFeeState, self.borrow_fee, field="borrow_fee"))
        set_(self, "squeeze", _member(SqueezeState, self.squeeze, field="squeeze"))
        set_(
            self,
            "short_sale_restriction",
            _member(
                ShortSaleRestrictionState,
                self.short_sale_restriction,
                field="short_sale_restriction",
            ),
        )
        set_(self, "recall_risk", _member(RecallRiskState, self.recall_risk, field="recall_risk"))

    @property
    def is_fully_qualified(self) -> bool:
        """Whether every state is affirmatively known and permits a short."""
        return (
            self.borrow_availability is BorrowAvailability.AVAILABLE
            and self.borrow_fee is not BorrowFeeState.UNKNOWN
            and self.squeeze is not SqueezeState.UNKNOWN
            and self.short_sale_restriction is ShortSaleRestrictionState.NOT_IN_EFFECT
            and self.recall_risk is not RecallRiskState.UNKNOWN
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationInputs:
    """Everything one Brain evaluation reads, resolved as of one decision instant.

    ``as_of_time`` is injected, never taken from a clock. ``evaluation_session``
    is the exchange session whose close the decision rests on; the gate requires
    the price history to end on exactly that session, so a series that stops
    earlier is stale rather than "the most recent available".
    """

    as_of_time: datetime
    environment: Environment
    security_id: str
    evaluation_session: date
    price_history: BarSeriesResult
    benchmark_history: BarSeriesResult | None = None
    universe: UniverseSnapshotResult | None = None
    event_context: EventContext | None = None
    market_context: MarketPermissionContext | None = None
    ai_evidence: AiEvidenceRecord | None = None
    short_context: ShortContext | None = None

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "as_of_time", require_instant(self.as_of_time, field="as_of_time"))
        set_(self, "environment", _member(Environment, self.environment, field="environment"))
        require_identifier(self.security_id, field="security_id")
        set_(
            self,
            "evaluation_session",
            _date(self.evaluation_session, field="evaluation_session"),
        )
        _require_type(self.price_history, BarSeriesResult, field="price_history")
        _require_optional_type(self.benchmark_history, BarSeriesResult, field="benchmark_history")
        _require_optional_type(self.universe, UniverseSnapshotResult, field="universe")
        _require_optional_type(self.event_context, EventContext, field="event_context")
        _require_optional_type(self.market_context, MarketPermissionContext, field="market_context")
        _require_optional_type(self.ai_evidence, AiEvidenceRecord, field="ai_evidence")
        _require_optional_type(self.short_context, ShortContext, field="short_context")


def _require_type(value: object, expected: type[object], *, field: str) -> None:
    if type(value) is not expected:
        raise BrainContractError(
            f"Field {field!r} must be a {expected.__name__}; a look-alike is a schema mismatch."
        )


def _require_optional_type(value: object, expected: type[object], *, field: str) -> None:
    if value is not None:
        _require_type(value, expected, field=field)


__all__ = [
    "AiEvidenceRecord",
    "EvaluationInputs",
    "EventContext",
    "MarketPermissionContext",
    "ShortContext",
]
