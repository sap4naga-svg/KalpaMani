"""What a strategy module hands the compiler, and the protocol it satisfies.

A module answers two questions and no others: *is this security eligible for
this module at this instant*, and *is the entry template triggered now*. It
receives the admitted bars from the reality gate and the strategy's own factor
values; it returns a :class:`ModuleEvaluation` carrying a verdict, the factor
snapshot it computed, reason codes and -- when it triggered -- the entry and
invalidation levels of its thesis.

A module does **not** decide the market permission, the event constraint, the
borrow prerequisite, consolidation, sizing or routing. Those are later stages
of the compiler and later layers of the system. Keeping the module this narrow
is what lets a second module (Pullback, PEAD) reuse the same compiler unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from kalpamani.data.contracts.entities import PriceBarValues
from kalpamani.strategies.brain.factors import FactorValue
from kalpamani.strategies.brain.spec import StrategySpec
from kalpamani.strategies.brain.vocabulary import (
    EntryCondition,
    InvalidationCondition,
    ModuleVerdict,
    ReasonCode,
    StopReferenceKind,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class TemplateTrigger:
    """The levels a triggered template rests on. Levels and references, never orders."""

    entry_condition: EntryCondition
    entry_reference_level: Decimal
    invalidation_condition: InvalidationCondition
    stop_reference_kind: StopReferenceKind
    stop_reference_level: Decimal
    stop_from_first_session: date
    stop_from_last_session: date


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleEvaluation:
    """A module's whole conclusion about one security at one instant."""

    verdict: ModuleVerdict
    factor_snapshot: tuple[FactorValue, ...]
    setup_quality: tuple[FactorValue, ...]
    reason_codes: tuple[ReasonCode, ...]
    trigger: TemplateTrigger | None

    @property
    def triggered(self) -> bool:
        return self.verdict is ModuleVerdict.TRIGGERED


@runtime_checkable
class StrategyModule(Protocol):
    """The interface the compiler drives. One module, one immutable spec."""

    @property
    def spec(self) -> StrategySpec:
        """The versioned, immutable definition this module realises."""
        ...

    def evaluate(
        self,
        bars: tuple[PriceBarValues, ...],
        benchmark: tuple[PriceBarValues, ...],
    ) -> ModuleEvaluation:
        """Evaluate eligibility and the entry template over the admitted bars."""
        ...


__all__ = ["ModuleEvaluation", "StrategyModule", "TemplateTrigger"]
