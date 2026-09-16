"""The M0 exploratory research path: signals, execution, ledgers, baselines, metrics (M0 §11-§14).

Everything here runs under an admitted :class:`ExploratoryInputSet` for the research
specification ``breakout-long-m0-exploratory-v1`` and never touches the accepted Brain gate:
the accepted :class:`~kalpamani.strategies.breakout.long.BreakoutLong` module is called
**unchanged, with its default parameters**, on bars the research reader serves. The
specification's differences from the accepted module (D1-D11) are enumerated on the
:data:`M0_RESEARCH_SPECIFICATION` object, and every execution rule is the one §11-§14 states:

* three instants per session -- membership at ``open(d) - margin`` from data through ``d-1``,
  the signal at ``close(d)`` with the evaluation bar, execution at ``open(d+1)``;
* participation and slippage from ``ADDV20`` ending the session **before** the executing
  open; the executing session's volume is never read;
* one-pass sizing with **final-fill rejection** of both limits (§14.1);
* exits before entries; ranking relative strength → ADDV20 → security id; constraints as
  recorded skips; **no entry executes in the purge or the tail**, and **no security re-enters
  at the open it exited** (stop, time or terminal);
* terminal recognition at ``open(t)`` from an admissible ``delisted`` action (§14.2), two
  complete ledgers (optimistic valuation and total loss), every figure on both;
* development and validation each initialized empty under the frozen trial digest (§14.3).

**Price bases are consistent.** A signal is evaluated on the split-only series *as of the
signal session*; execution reads every bar on that bar's **own** session's basis (the raw
delivered price); a level stated on the signal session's basis is carried to the executing
session by the split ratios between them; a split effective while a position is held rescales
the held shares and the stop at that open, settles any fractional share in cash at that
session's close (``SplitEvent.cash_in_lieu``, no commission), and leaves the entry facts and
the planned risk as they were. No split effective after a session can reach back into it.

**Configuration provenance is explicit and validated.** :data:`M0_SYNTHETIC_FIXTURE` is an
engineering test input carrying the §14 proposed settings and benchmark A; it is *not* an
owner selection and may carry none. A run over real data (:attr:`DataKind.REAL`) is refused
unless the configuration is ``OWNER_SELECTED`` with a typed, complete, supported and
non-contradictory :class:`OwnerSelections` -- nothing falls back to the fixture, and a
malformed data kind is refused rather than read as synthetic.

Synthetic success establishes software behaviour only: no strategy profitability, no
promotion readiness, no qualification of any period.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.entities import PriceBarValues
from kalpamani.data.exploratory.admission import AdmissionOutcome, ResearchSpecification, admit
from kalpamani.data.exploratory.contracts import ExploratoryInputSet
from kalpamani.data.exploratory.dataset import ExploratoryDataset
from kalpamani.data.exploratory.vocabulary import (
    ExploratoryDerivation,
    ExploratoryLimitation,
    ExploratoryProfile,
)
from kalpamani.data.production.sharadar.universe import ACTION_DELISTED
from kalpamani.strategies.brain import factors
from kalpamani.strategies.brain.vocabulary import ModuleVerdict
from kalpamani.strategies.breakout.long import BreakoutLong, build_spec

_ZERO: Final = Decimal(0)
_ONE: Final = Decimal(1)
_CENT: Final = Decimal("0.01")
_BPS: Final = Decimal(10_000)
_PRICE: Final = Decimal("0.0001")
_LEVEL: Final = Decimal("0.000001")
_FRACTION: Final = Decimal("0.0001")
_SESSIONS_PER_YEAR: Final = Decimal(252)

#: The accepted module's own identity: its research version, the hash of the exact parameter
#: values it evaluates with, and the history it requires. Bound into every trial digest.
_ACCEPTED_SPEC: Final = build_spec()
STRATEGY_IDENTITY: Final[dict[str, Any]] = {
    "strategy_id": _ACCEPTED_SPEC.strategy_id,
    "version": _ACCEPTED_SPEC.version,
    "parameters_hash": _ACCEPTED_SPEC.parameters_hash,
    "required_history_sessions": _ACCEPTED_SPEC.data.required_history_sessions,
}
#: The history every signal reads: the accepted module's requirement (252), never an override.
HISTORY_SESSIONS: Final[int] = _ACCEPTED_SPEC.data.required_history_sessions

#: The research specification (M0 §1-§2): derived from the accepted module, every difference named.
M0_RESEARCH_SPECIFICATION: Final = ResearchSpecification(
    name="breakout-long-m0-exploratory",
    version="breakout-long-m0-exploratory-v1",
    admits_profile=ExploratoryProfile.EXPLORATORY_HINDSIGHT,
    admits_derivation=ExploratoryDerivation.AS_DATED,
    declared_limitations=frozenset(ExploratoryLimitation),
    base_strategy_version="breakout-long/r1-research",
    differences=(
        "D1 profile EXPLORATORY_HINDSIGHT instead of PROVIDER_REALISTIC_PIT",
        "D2 EVENT_CALENDAR not required: event-blind",
        "D3 MARKET_PERMISSION a constant context: long PERMITTED, short DENIED",
        "D4 benchmark M0-EW-UNIVERSE (option A) instead of a broad-market benchmark",
        "D5 membership clauses unchanged, under AS_DATED bounds",
        "D6 an execution layer: entry next open, gap skip, close-below-base-low stop next open, "
        "time exit",
        "D7 a portfolio ledger with the CLAUDE.md s.6 research parameters and a capacity ranking",
        "D8 the eleven thresholds unchanged (one trial)",
        "D9 adjustment SPLIT_ONLY / FORWARD_BASE_NORMALIZED unchanged",
        "D10 holding horizon unchanged; time exit at 20 held sessions",
        "D11 invalidation CLOSE_BELOW_BASE_LOW executed at the next open",
    ),
    trial=1,
)


class ConfigurationProvenance(StrEnum):
    """Where a configuration's values come from. Closed."""

    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    OWNER_SELECTED = "OWNER_SELECTED"


class DataKind(StrEnum):
    """What the inputs are. Declared by the caller; real data needs owner selections."""

    SYNTHETIC = "SYNTHETIC"
    REAL = "REAL"


class TerminalPolicy(StrEnum):
    """The two complete ledgers (§12.3, §14.2)."""

    OPTIMISTIC = "OPTIMISTIC"
    TOTAL_LOSS = "TOTAL_LOSS"


class Window(StrEnum):
    """The phases of §11.1."""

    WARM_UP = "WARM_UP"
    DEVELOPMENT = "DEVELOPMENT"
    PURGE = "PURGE"
    VALIDATION = "VALIDATION"
    TAIL = "TAIL"


class Skip(StrEnum):
    """Every recorded reason a candidate did not become a trade. Closed."""

    SKIPPED_ENTRY_GAP = "SKIPPED_ENTRY_GAP"
    SKIPPED_ZERO_QUANTITY = "SKIPPED_ZERO_QUANTITY"
    SKIPPED_RISK_LIMIT_AT_FINAL_FILL = "SKIPPED_RISK_LIMIT_AT_FINAL_FILL"
    SKIPPED_POSITION_LIMIT_AT_FINAL_FILL = "SKIPPED_POSITION_LIMIT_AT_FINAL_FILL"
    SKIPPED_RISK_CAPACITY = "SKIPPED_RISK_CAPACITY"
    SKIPPED_CASH = "SKIPPED_CASH"
    SKIPPED_ALREADY_HELD = "SKIPPED_ALREADY_HELD"
    SKIPPED_EXITED_THIS_SESSION = "SKIPPED_EXITED_THIS_SESSION"
    SKIPPED_NO_EXECUTION_BAR = "SKIPPED_NO_EXECUTION_BAR"
    SKIPPED_INSUFFICIENT_HISTORY = "SKIPPED_INSUFFICIENT_HISTORY"


class ExitReason(StrEnum):
    """Why a position closed. Closed."""

    STOP = "STOP"
    TIME = "TIME"
    TERMINAL_VALUATION_OPTIMISTIC = "TERMINAL_VALUATION_OPTIMISTIC"
    TERMINAL_TOTAL_LOSS = "TERMINAL_TOTAL_LOSS"
    OPEN_AT_END = "OPEN_AT_END"


class RunRefusal(StrEnum):
    """Why a run did not start, or a configuration was not admitted. Closed."""

    REFUSED_NOT_ADMITTED = "REFUSED_NOT_ADMITTED"
    REFUSED_UNSELECTED_CONFIGURATION = "REFUSED_UNSELECTED_CONFIGURATION"
    REFUSED_INVALID_CONFIGURATION = "REFUSED_INVALID_CONFIGURATION"
    REFUSED_UNSUPPORTED_SELECTION = "REFUSED_UNSUPPORTED_SELECTION"
    REFUSED_CONTRADICTORY_SELECTION = "REFUSED_CONTRADICTORY_SELECTION"
    REFUSED_SELECTION_INCONSISTENT = "REFUSED_SELECTION_INCONSISTENT"
    REFUSED_FIXTURE_ON_REAL_DATA = "REFUSED_FIXTURE_ON_REAL_DATA"
    REFUSED_MALFORMED_DATA_KIND = "REFUSED_MALFORMED_DATA_KIND"
    REFUSED_CALENDAR_TOO_SHORT = "REFUSED_CALENDAR_TOO_SHORT"
    REFUSED_CONTENT_DIGEST_MISMATCH = "REFUSED_CONTENT_DIGEST_MISMATCH"


class M0RunError(Exception):
    """One closed refusal."""

    def __init__(self, refusal: RunRefusal) -> None:
        super().__init__(refusal.value)
        self.refusal = refusal


# ---------------------------------------------------------------------------
# Owner selections: typed, supported, non-contradictory, immutable
# ---------------------------------------------------------------------------


class ExploratoryModeChoice(StrEnum):
    """O-1: whether an exploratory mode is wanted at all."""

    ENABLED = "ENABLED"
    DECLINED = "DECLINED"


class BenchmarkChoice(StrEnum):
    """O-2: the benchmark. Only option A is executable in this slice."""

    A_EW_UNIVERSE = "A_EW_UNIVERSE"
    B_FUND_SERIES = "B_FUND_SERIES"


class ExitRuleChoice(StrEnum):
    """O-3: the exit rule."""

    CLOSE_BELOW_BASE_LOW_NEXT_OPEN = "CLOSE_BELOW_BASE_LOW_NEXT_OPEN"


class CostModelChoice(StrEnum):
    """O-4: the cost model."""

    M0_SECTION_14 = "M0_SECTION_14"


class AcquisitionRouteChoice(StrEnum):
    """O-5: the acquisition route. Recorded; nothing here acquires."""

    BOUNDED_RUNS = "BOUNDED_RUNS"
    BULK_ACQUISITION_ADR = "BULK_ACQUISITION_ADR"


class ComputeLocationChoice(StrEnum):
    """O-6: the research compute location. Recorded; nothing here computes elsewhere."""

    PRIVATE_AWS = "PRIVATE_AWS"
    WORKSTATION = "WORKSTATION"


class SizingPolicyChoice(StrEnum):
    """O-7: the sizing policy."""

    CLAUDE_S6_RESEARCH_PARAMETERS = "CLAUDE_S6_RESEARCH_PARAMETERS"


class TerminalAccountingChoice(StrEnum):
    """O-9: the terminal-event accounting."""

    TWO_LEDGERS = "TWO_LEDGERS"


class FinalFillPolicyChoice(StrEnum):
    """O-10: what happens when the final fill breaches a sizing limit."""

    REJECTION = "REJECTION"
    RESIZE = "RESIZE"


class Acknowledgment(StrEnum):
    """O-11: the acknowledgment that M0 has no untouched test window."""

    ACKNOWLEDGED = "ACKNOWLEDGED"
    NOT_ACKNOWLEDGED = "NOT_ACKNOWLEDGED"


#: What this slice can execute. A selection outside this set is refused as unsupported.
_SUPPORTED: Final[dict[str, frozenset[Any]]] = {
    "o2_benchmark": frozenset({BenchmarkChoice.A_EW_UNIVERSE}),
    "o10_final_fill_policy": frozenset({FinalFillPolicyChoice.REJECTION}),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerSelections:
    """The owner's O-1…O-11 decisions as typed choices. Frozen; validated at construction.

    Every field is an exact member of its closed vocabulary (a name, a string or a lookalike
    is not a choice), every choice must be one this slice can execute, and the set must not
    contradict running at all. Synthetic fixture values are never selections.
    """

    o1_exploratory_mode: ExploratoryModeChoice
    o2_benchmark: BenchmarkChoice
    o3_exit_rule: ExitRuleChoice
    o4_cost_model: CostModelChoice
    o5_acquisition_route: AcquisitionRouteChoice
    o6_compute_location: ComputeLocationChoice
    o7_sizing_policy: SizingPolicyChoice
    o8_data_window_start: date
    o8_data_window_end: date
    o9_terminal_accounting: TerminalAccountingChoice
    o10_final_fill_policy: FinalFillPolicyChoice
    o11_no_untouched_window: Acknowledgment

    def __post_init__(self) -> None:
        for name, kind in (
            ("o1_exploratory_mode", ExploratoryModeChoice),
            ("o2_benchmark", BenchmarkChoice),
            ("o3_exit_rule", ExitRuleChoice),
            ("o4_cost_model", CostModelChoice),
            ("o5_acquisition_route", AcquisitionRouteChoice),
            ("o6_compute_location", ComputeLocationChoice),
            ("o7_sizing_policy", SizingPolicyChoice),
            ("o8_data_window_start", date),
            ("o8_data_window_end", date),
            ("o9_terminal_accounting", TerminalAccountingChoice),
            ("o10_final_fill_policy", FinalFillPolicyChoice),
            ("o11_no_untouched_window", Acknowledgment),
        ):
            if type(getattr(self, name)) is not kind:
                raise M0RunError(RunRefusal.REFUSED_INVALID_CONFIGURATION)
        for name, supported in _SUPPORTED.items():
            if getattr(self, name) not in supported:
                raise M0RunError(RunRefusal.REFUSED_UNSUPPORTED_SELECTION)
        if (
            self.o1_exploratory_mode is ExploratoryModeChoice.DECLINED
            or self.o11_no_untouched_window is Acknowledgment.NOT_ACKNOWLEDGED
            or self.o8_data_window_start > self.o8_data_window_end
        ):
            raise M0RunError(RunRefusal.REFUSED_CONTRADICTORY_SELECTION)

    @property
    def benchmark_option(self) -> str:
        return "A" if self.o2_benchmark is BenchmarkChoice.A_EW_UNIVERSE else "B"

    def document(self) -> dict[str, Any]:
        return {
            "O-1": self.o1_exploratory_mode.value,
            "O-2": self.o2_benchmark.value,
            "O-3": self.o3_exit_rule.value,
            "O-4": self.o4_cost_model.value,
            "O-5": self.o5_acquisition_route.value,
            "O-6": self.o6_compute_location.value,
            "O-7": self.o7_sizing_policy.value,
            "O-8": {
                "start": self.o8_data_window_start.isoformat(),
                "end": self.o8_data_window_end.isoformat(),
            },
            "O-9": self.o9_terminal_accounting.value,
            "O-10": self.o10_final_fill_policy.value,
            "O-11": self.o11_no_untouched_window.value,
        }


OWNER_DECISIONS: Final = tuple(f"O-{n}" for n in range(1, 12))


# ---------------------------------------------------------------------------
# Configuration: every value typed, finite, in range and cross-checked
# ---------------------------------------------------------------------------

_DECIMAL_FIELDS: Final[tuple[tuple[str, bool], ...]] = (
    # (name, strictly positive)
    ("commission_per_share", False),
    ("commission_minimum", False),
    ("spread_bps_round_trip", False),
    ("slippage_base_bps", False),
    ("slippage_bps_per_participation_pct", False),
    ("participation_free_pct", False),
    ("capacity_flag_pct", False),
    ("capital", True),
    ("risk_per_trade", True),
    ("position_cap", True),
    ("open_risk_cap", True),
    ("entry_gap_max", False),
    ("idle_cash_rate_annual", False),
    ("cost_multiplier", False),
)
_INT_FIELDS: Final[tuple[tuple[str, int], ...]] = (
    # (name, minimum)
    ("time_exit_held_sessions", 1),
    ("warm_up_sessions", HISTORY_SESSIONS + 1),
    ("development_sessions", 1),
    ("purge_sessions", 1),
    ("validation_sessions", 1),
    ("tail_sessions", 1),
    ("addv_sessions", 1),
    ("baseline_stop_sessions", 1),
    ("baseline_momentum_sessions", 1),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class M0Configuration:
    """Every parameter §11-§14 names, with its provenance. Frozen into the trial digest.

    Validation is total: a wrong type (a float, an int for a Decimal, a bool for an int, a
    string), a non-finite Decimal, an out-of-range value or a contradictory pair is
    ``REFUSED_INVALID_CONFIGURATION``. ``OWNER_SELECTED`` requires an :class:`OwnerSelections`;
    ``SYNTHETIC_FIXTURE`` may carry none.
    """

    provenance: ConfigurationProvenance
    benchmark_option: str = "A"
    commission_per_share: Decimal = Decimal("0.005")
    commission_minimum: Decimal = Decimal("1.00")
    spread_bps_round_trip: Decimal = Decimal(10)
    slippage_base_bps: Decimal = Decimal(10)
    slippage_bps_per_participation_pct: Decimal = Decimal(10)
    participation_free_pct: Decimal = Decimal(1)
    capacity_flag_pct: Decimal = Decimal(5)
    capital: Decimal = Decimal("80000.00")
    risk_per_trade: Decimal = Decimal("400.00")
    position_cap: Decimal = Decimal("6400.00")
    open_risk_cap: Decimal = Decimal("4000.00")
    time_exit_held_sessions: int = 20
    entry_gap_max: Decimal = Decimal("0.10")
    idle_cash_rate_annual: Decimal = Decimal(0)
    cost_multiplier: Decimal = Decimal(1)
    warm_up_sessions: int = 253
    development_sessions: int = 126
    purge_sessions: int = 30
    validation_sessions: int = 126
    tail_sessions: int = 30
    addv_sessions: int = 20
    #: The stop level B0 uses: the low of the prior ``base_sessions`` bars (the same
    #: base_range helper the module uses) -- an M0 assumption, not an accepted rule.
    baseline_stop_sessions: int = 20
    baseline_momentum_sessions: int = 60
    owner_selections: OwnerSelections | None = None

    def __post_init__(self) -> None:
        invalid = M0RunError(RunRefusal.REFUSED_INVALID_CONFIGURATION)
        if type(self.provenance) is not ConfigurationProvenance:
            raise invalid
        if self.provenance is ConfigurationProvenance.OWNER_SELECTED:
            if self.owner_selections is None:
                raise M0RunError(RunRefusal.REFUSED_UNSELECTED_CONFIGURATION)
            if type(self.owner_selections) is not OwnerSelections:
                raise invalid
        elif self.owner_selections is not None:
            raise invalid  # engineering inputs are never owner decisions
        if type(self.benchmark_option) is not str or self.benchmark_option != "A":
            raise invalid  # only benchmark option A is implemented in this slice
        if (
            self.owner_selections is not None
            and self.owner_selections.benchmark_option != self.benchmark_option
        ):
            raise invalid
        for name, strictly_positive in _DECIMAL_FIELDS:
            value = getattr(self, name)
            if type(value) is not Decimal or not value.is_finite():
                raise invalid
            if value < 0 or (strictly_positive and value == 0):
                raise invalid
        for name, minimum in _INT_FIELDS:
            value = getattr(self, name)
            if type(value) is not int or value < minimum:
                raise invalid
        if (
            self.position_cap > self.capital
            or self.open_risk_cap > self.capital
            or self.risk_per_trade > self.open_risk_cap
            or self.participation_free_pct > self.capacity_flag_pct
        ):
            raise invalid

    @property
    def half_spread(self) -> Decimal:
        return self.spread_bps_round_trip / 2 / _BPS * self.cost_multiplier

    def document(self) -> dict[str, Any]:
        """The closed configuration document the trial digest binds."""
        return {
            "provenance": self.provenance.value,
            "benchmark_option": self.benchmark_option,
            "commission_per_share": str(self.commission_per_share),
            "commission_minimum": str(self.commission_minimum),
            "spread_bps_round_trip": str(self.spread_bps_round_trip),
            "slippage_base_bps": str(self.slippage_base_bps),
            "slippage_bps_per_participation_pct": str(self.slippage_bps_per_participation_pct),
            "participation_free_pct": str(self.participation_free_pct),
            "capacity_flag_pct": str(self.capacity_flag_pct),
            "capital": str(self.capital),
            "risk_per_trade": str(self.risk_per_trade),
            "position_cap": str(self.position_cap),
            "open_risk_cap": str(self.open_risk_cap),
            "time_exit_held_sessions": self.time_exit_held_sessions,
            "entry_gap_max": str(self.entry_gap_max),
            "idle_cash_rate_annual": str(self.idle_cash_rate_annual),
            "cost_multiplier": str(self.cost_multiplier),
            "phases": [
                self.warm_up_sessions,
                self.development_sessions,
                self.purge_sessions,
                self.validation_sessions,
                self.tail_sessions,
            ],
            "addv_sessions": self.addv_sessions,
            "baseline_stop_sessions": self.baseline_stop_sessions,
            "baseline_momentum_sessions": self.baseline_momentum_sessions,
            "owner_selections": (
                None if self.owner_selections is None else self.owner_selections.document()
            ),
        }


#: Engineering test input: the §14 proposed settings and benchmark A. NOT an owner selection.
M0_SYNTHETIC_FIXTURE: Final = M0Configuration(provenance=ConfigurationProvenance.SYNTHETIC_FIXTURE)


@dataclass(frozen=True, slots=True, kw_only=True)
class Phases:
    """The exact session boundaries, anchored at the data end (§11.1)."""

    warm_up: tuple[date, ...]
    development: tuple[date, ...]
    purge: tuple[date, ...]
    validation: tuple[date, ...]
    tail: tuple[date, ...]

    def window_of(self, session: date) -> Window | None:
        for name, sessions in (
            (Window.WARM_UP, self.warm_up),
            (Window.DEVELOPMENT, self.development),
            (Window.PURGE, self.purge),
            (Window.VALIDATION, self.validation),
            (Window.TAIL, self.tail),
        ):
            if sessions and sessions[0] <= session <= sessions[-1]:
                return name
        return None

    def document(self) -> dict[str, Any]:
        return {
            name: [s[0].isoformat(), s[-1].isoformat(), len(s)] if s else []
            for name, s in (
                ("warm_up", self.warm_up),
                ("development", self.development),
                ("purge", self.purge),
                ("validation", self.validation),
                ("tail", self.tail),
            )
        }


def phases_for(sessions: tuple[date, ...], config: M0Configuration) -> Phases:
    total = (
        config.warm_up_sessions
        + config.development_sessions
        + config.purge_sessions
        + config.validation_sessions
        + config.tail_sessions
    )
    if len(sessions) < total:
        raise M0RunError(RunRefusal.REFUSED_CALENDAR_TOO_SHORT)
    end = len(sessions)

    def take(count: int) -> tuple[date, ...]:
        nonlocal end
        block = sessions[end - count : end]
        end -= count
        return block

    tail = take(config.tail_sessions)
    validation = take(config.validation_sessions)
    purge = take(config.purge_sessions)
    development = take(config.development_sessions)
    warm_up = take(config.warm_up_sessions)
    return Phases(
        warm_up=warm_up, development=development, purge=purge, validation=validation, tail=tail
    )


# ---------------------------------------------------------------------------
# Trades, transactions and ledgers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class SplitEvent:
    """A split effective while the position was held, and how it was applied."""

    ex_date: date
    ratio: Decimal
    shares_before: int
    shares_after: int
    #: The fractional share settled in cash at ``price`` (the ex-session close), no commission.
    cash_in_lieu: Decimal
    price: Decimal

    def document(self) -> dict[str, Any]:
        return {
            "ex_date": self.ex_date.isoformat(),
            "ratio": str(self.ratio),
            "shares_before": self.shares_before,
            "shares_after": self.shares_after,
            "cash_in_lieu": str(self.cash_in_lieu),
            "price": str(self.price),
        }


class TransactionKind(StrEnum):
    """Every cash movement the ledger records. Closed."""

    ENTRY = "ENTRY"
    EXIT = "EXIT"
    CASH_IN_LIEU = "CASH_IN_LIEU"
    INTEREST = "INTEREST"


@dataclass(frozen=True, slots=True, kw_only=True)
class Transaction:
    """One recorded cash movement: what the reconciliation is rebuilt from."""

    kind: TransactionKind
    session: date
    security_id: str | None
    shares: int
    price: Decimal | None
    commission: Decimal
    cash_delta: Decimal
    reason: str | None

    def document(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "session": self.session.isoformat(),
            "security_id": self.security_id,
            "shares": self.shares,
            "price": None if self.price is None else str(self.price),
            "commission": str(self.commission),
            "cash_delta": str(self.cash_delta),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class Trade:
    """One closed (or open-at-end) trade with every figure §12.2 records.

    ``shares``, ``entry_fill`` and ``entry_open`` are the entry facts on the entry session's
    basis and never change; ``exit_shares`` is the quantity held at the exit (after any
    split); ``cash_in_lieu`` is what the fractional-share policy settled in cash; an
    open-at-end trade carries its mark and unrealized P&L instead of a realized one.
    """

    security_id: str
    window: Window
    signal_session: date
    entry_session: date
    shares: int
    entry_open: Decimal
    entry_fill: Decimal
    entry_commission: Decimal
    entry_participation_pct: Decimal
    entry_capacity_limited: bool
    stop_level: Decimal
    planned_risk: Decimal
    exit_session: date | None
    exit_reason: ExitReason
    exit_shares: int
    exit_fill: Decimal | None
    exit_commission: Decimal
    exit_participation_pct: Decimal | None
    held_sessions: int
    realized_pnl: Decimal | None
    r_multiple: Decimal | None
    missing_bar_sessions: int
    bars_after_delisting: int
    split_events: tuple[SplitEvent, ...]
    cash_in_lieu: Decimal
    mark_session: date | None
    mark_price: Decimal | None
    unrealized_pnl: Decimal | None

    def document(self) -> dict[str, Any]:
        def money(value: Decimal | None) -> str | None:
            return None if value is None else str(value)

        return {
            "security_id": self.security_id,
            "window": self.window.value,
            "signal_session": self.signal_session.isoformat(),
            "entry_session": self.entry_session.isoformat(),
            "shares": self.shares,
            "entry_open": str(self.entry_open),
            "entry_fill": str(self.entry_fill),
            "entry_commission": str(self.entry_commission),
            "entry_participation_pct": str(self.entry_participation_pct),
            "entry_capacity_limited": self.entry_capacity_limited,
            "stop_level": str(self.stop_level),
            "planned_risk": str(self.planned_risk),
            "exit_session": None if self.exit_session is None else self.exit_session.isoformat(),
            "exit_reason": self.exit_reason.value,
            "exit_shares": self.exit_shares,
            "exit_fill": money(self.exit_fill),
            "exit_commission": str(self.exit_commission),
            "exit_participation_pct": money(self.exit_participation_pct),
            "held_sessions": self.held_sessions,
            "realized_pnl": money(self.realized_pnl),
            "r_multiple": money(self.r_multiple),
            "missing_bar_sessions": self.missing_bar_sessions,
            "bars_after_delisting": self.bars_after_delisting,
            "split_events": [e.document() for e in self.split_events],
            "cash_in_lieu": str(self.cash_in_lieu),
            "mark_session": None if self.mark_session is None else self.mark_session.isoformat(),
            "mark_price": money(self.mark_price),
            "unrealized_pnl": money(self.unrealized_pnl),
        }


@dataclass(slots=True)
class _Position:
    security_id: str
    window: Window
    signal_session: date
    entry_session: date
    entry_shares: int
    shares: int
    entry_open: Decimal
    entry_fill: Decimal
    entry_commission: Decimal
    entry_participation_pct: Decimal
    entry_capacity_limited: bool
    stop_level: Decimal
    planned_risk: Decimal
    last_close: Decimal
    last_close_session: date
    held_sessions: int = 1
    missing_bar_sessions: int = 0
    bars_after_delisting: int = 0
    stop_triggered: bool = False
    time_due: bool = False
    cash_in_lieu: Decimal = _ZERO
    split_events: list[SplitEvent] = field(default_factory=list)

    @property
    def cost_basis(self) -> Decimal:
        return _money(self.entry_fill * self.entry_shares)


@dataclass(frozen=True, slots=True, kw_only=True)
class SkipRecord:
    session: date
    security_id: str
    reason: Skip

    def document(self) -> dict[str, Any]:
        return {
            "session": self.session.isoformat(),
            "security_id": self.security_id,
            "reason": self.reason.value,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class EquityPoint:
    session: date
    window: Window
    cash: Decimal
    positions_value: Decimal
    equity: Decimal
    open_planned_risk: Decimal

    def document(self) -> dict[str, Any]:
        return {
            "session": self.session.isoformat(),
            "window": self.window.value,
            "cash": str(self.cash),
            "positions_value": str(self.positions_value),
            "equity": str(self.equity),
            "open_planned_risk": str(self.open_planned_risk),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class WindowMetrics:
    """Protocol §8 figures for one window and one ledger, net of costs.

    Two labelled periods. The **evaluation period** runs from the close before
    ``evaluation_start`` to the close of ``evaluation_end`` (the window itself); its
    strategy return and its benchmark return cover exactly those instants, so the first
    session's return counts on both sides. The **liquidation-inclusive period** extends to
    ``liquidation_end`` (the following purge or tail), where positions may only close; its
    benchmark figure covers the same extended instants. Trade statistics count the window's
    trades wherever they closed, which is how a trade is attributed.
    """

    window: Window
    evaluation_start: date
    evaluation_end: date
    liquidation_end: date
    trades: int
    winners: int
    losers: int
    expectancy: Decimal | None
    hit_rate: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    net_pnl: Decimal
    max_drawdown: Decimal
    max_drawdown_through_liquidation: Decimal
    turnover: Decimal
    average_exposure: Decimal
    capacity_limited_entries: int
    max_participation_pct: Decimal
    losses_beyond_one_r: int
    worst_trade_pnl: Decimal | None
    worst_session_pnl: Decimal
    terminal_events: int
    open_at_end: int
    start_equity: Decimal
    end_equity: Decimal
    return_fraction: Decimal
    benchmark_return_fraction: Decimal | None
    liquidation_end_equity: Decimal
    liquidation_return_fraction: Decimal
    liquidation_benchmark_return_fraction: Decimal | None

    def document(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in self.__slots__:
            value = getattr(self, name)
            if isinstance(value, Window):
                out[name] = value.value
            elif isinstance(value, date):
                out[name] = value.isoformat()
            elif isinstance(value, Decimal):
                out[name] = str(value)
            else:
                out[name] = value
        return out


@dataclass(frozen=True, slots=True, kw_only=True)
class Ledger:
    """One complete ledger under one terminal policy, with its transaction journal."""

    policy: TerminalPolicy
    label: str
    trades: tuple[Trade, ...]
    skips: tuple[SkipRecord, ...]
    equity: tuple[EquityPoint, ...]
    transactions: tuple[Transaction, ...]
    metrics: tuple[WindowMetrics, ...]
    missing_bar_held_sessions: int
    exits_deferred_no_bar: int

    def document(self) -> dict[str, Any]:
        return {
            "policy": self.policy.value,
            "label": self.label,
            "trades": [t.document() for t in self.trades],
            "skips": [s.document() for s in self.skips],
            "equity": [e.document() for e in self.equity],
            "transactions": [x.document() for x in self.transactions],
            "metrics": [m.document() for m in self.metrics],
            "missing_bar_held_sessions": self.missing_bar_held_sessions,
            "exits_deferred_no_bar": self.exits_deferred_no_bar,
        }


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class Candidate:
    """One signal at ``close(signal_session)``, ranked for execution at the next open. Its
    ``stop_level`` is stated on the signal session's price basis."""

    security_id: str
    signal_session: date
    rank_primary: Decimal
    addv: Decimal
    stop_level: Decimal

    @property
    def rank_key(self) -> tuple[Decimal, Decimal, str]:
        return (-self.rank_primary, -self.addv, self.security_id)


SignalSource = Callable[[ExploratoryDataset, date, int], list[Candidate]]


def _addv(bars: tuple[PriceBarValues, ...], sessions: int) -> Decimal | None:
    """Mean ``close x volume`` over the last ``sessions`` bars of a series ending before the
    executing session. ``None`` when the window is short. Basis-invariant: a split divides
    the close and multiplies the volume."""
    if len(bars) < sessions:
        return None
    window = bars[-sessions:]
    return sum((bar.close * Decimal(bar.volume) for bar in window), _ZERO) / Decimal(sessions)


def breakout_long_signals(
    dataset: ExploratoryDataset, signal_session: date, history: int
) -> list[Candidate]:
    """Breakout Long, unchanged, over every member of ``signal_session`` with enough bars."""
    cache = dataset.cache.setdefault("breakout_long_signals", {})
    key = (signal_session, history)
    if key in cache:
        return list(cache[key])
    module = BreakoutLong()
    benchmark = tuple(bar for bar in dataset.benchmark_bars() if bar.session_date <= signal_session)
    out: list[Candidate] = []
    for security_id in dataset.members_at(signal_session):
        bars = dataset.bars_through(security_id, signal_session, count=history + 1)
        if len(bars) < history + 1 or bars[-1].session_date != signal_session:
            continue
        grid = benchmark[-len(bars) :]
        if len(grid) != len(bars) or grid[0].session_date != bars[0].session_date:
            continue
        evaluation = module.evaluate(bars, grid)
        if evaluation.verdict is not ModuleVerdict.TRIGGERED or evaluation.trigger is None:
            continue
        relative_strength = next(
            v.value
            for v in evaluation.factor_snapshot
            if v.definition.factor_id == "relative-strength"
        )
        addv = _addv(bars, 20) or _ZERO
        out.append(
            Candidate(
                security_id=security_id,
                signal_session=signal_session,
                rank_primary=relative_strength,
                addv=addv,
                stop_level=evaluation.trigger.stop_reference_level,
            )
        )
    cache[key] = tuple(out)
    return out


def baseline_b0_signals(momentum_sessions: int, stop_sessions: int) -> SignalSource:
    """B0: every member with enough bars, ranked by the single momentum factor; the stop
    level is the low of the prior ``stop_sessions`` bars (an M0 assumption)."""

    def source(dataset: ExploratoryDataset, signal_session: date, history: int) -> list[Candidate]:
        out: list[Candidate] = []
        for security_id in dataset.members_at(signal_session):
            bars = dataset.bars_through(security_id, signal_session, count=history + 1)
            if len(bars) < history + 1 or bars[-1].session_date != signal_session:
                continue
            momentum = factors.simple_return(bars, momentum_sessions)
            stop = factors.base_range(bars, stop_sessions).low
            out.append(
                Candidate(
                    security_id=security_id,
                    signal_session=signal_session,
                    rank_primary=momentum,
                    addv=_addv(bars, 20) or _ZERO,
                    stop_level=stop,
                )
            )
        return out

    return source


# ---------------------------------------------------------------------------
# The simulation
# ---------------------------------------------------------------------------


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT)


def _price(value: Decimal) -> Decimal:
    return value.quantize(_PRICE)


def _level(value: Decimal) -> Decimal:
    return value.quantize(_LEVEL)


def ratio_return(start: Decimal | None, end: Decimal | None) -> Decimal | None:
    """``end / start - 1`` where both levels exist and ``start`` is positive; otherwise
    ``None`` -- never a zero standing in for an undefined return."""
    if start is None or end is None or start <= 0:
        return None
    return ((end / start) - _ONE).quantize(_FRACTION)


class _Simulation:
    """One ledger's session loop. Deterministic; reads no clock."""

    def __init__(
        self,
        dataset: ExploratoryDataset,
        config: M0Configuration,
        phases: Phases,
        policy: TerminalPolicy,
        source: SignalSource,
    ) -> None:
        self.dataset = dataset
        self.config = config
        self.phases = phases
        self.policy = policy
        self.source = source
        self.cash = _ZERO
        self.positions: dict[str, _Position] = {}
        self.trades: list[Trade] = []
        self.skips: list[SkipRecord] = []
        self.equity: list[EquityPoint] = []
        self.transactions: list[Transaction] = []
        self.missing_bar_held = 0
        self.exits_deferred = 0
        self.exited_this_session: set[str] = set()
        self._bar_cache: dict[str, dict[date, PriceBarValues]] = {}

    # -- data access: every read is bounded at the instant the rule states, on its own basis --

    def _bars(self, security_id: str) -> dict[date, PriceBarValues]:
        """Raw bars by session: each on its own session's basis. Nothing later reaches in."""
        if security_id not in self._bar_cache:
            self._bar_cache[security_id] = {
                bar.session_date: bar for bar in self.dataset.raw_bars(security_id)
            }
        return self._bar_cache[security_id]

    def _bar(self, security_id: str, session: date) -> PriceBarValues | None:
        return self._bars(security_id).get(session)

    def _addv_before(self, security_id: str, session: date) -> Decimal | None:
        """``ADDV20`` ending the session before ``session``; the session's own bar unread."""
        held = self._bars(security_id)
        sessions = self._sorted_sessions(security_id)
        lo, hi = 0, len(sessions)
        while lo < hi:
            mid = (lo + hi) // 2
            if sessions[mid] < session:
                lo = mid + 1
            else:
                hi = mid
        window = tuple(held[s] for s in sessions[max(0, lo - self.config.addv_sessions) : lo])
        return _addv(window, self.config.addv_sessions)

    def _sorted_sessions(self, security_id: str) -> list[date]:
        key = f"sessions:{security_id}"
        cached: list[date] | None = self.dataset.cache.get(key)
        if cached is None:
            cached = sorted(self._bars(security_id))
            self.dataset.cache[key] = cached
        return cached

    def _delisting_recognized_at(self, security_id: str, session: date) -> bool:
        """A ``delisted`` action admissible at ``open(session)`` (its bound <= that open)."""
        opened = self.dataset.calendar.open_at(session)
        if opened is None:
            return False
        if "delisted_bounds" not in self.dataset.cache:
            bounds: dict[str, Any] = {}
            for item in self.dataset.layer.actions:
                if item.row.fields.get("action") != ACTION_DELISTED:
                    continue
                current = bounds.get(item.row.security_id)
                bound = item.availability.governing_time
                if current is None or bound < current:
                    bounds[item.row.security_id] = bound
            self.dataset.cache["delisted_bounds"] = bounds
        bound = self.dataset.cache["delisted_bounds"].get(security_id)
        return bool(bound is not None and bound <= opened)

    # -- costs --

    def _slippage(self, participation_pct: Decimal) -> Decimal:
        c = self.config
        excess = max(_ZERO, participation_pct - c.participation_free_pct)
        return (
            (c.slippage_base_bps + c.slippage_bps_per_participation_pct * excess)
            / _BPS
            * c.cost_multiplier
        )

    def _commission(self, shares: int) -> Decimal:
        c = self.config
        return _money(
            max(c.commission_minimum, c.commission_per_share * shares) * c.cost_multiplier
        )

    def _sell_fill(
        self, price: Decimal, shares: int, addv: Decimal | None
    ) -> tuple[Decimal, Decimal]:
        participation = _ZERO if not addv else (Decimal(shares) * price / addv * 100)
        fill = _price(price * (_ONE - self.config.half_spread - self._slippage(participation)))
        return fill, participation

    def _record(
        self,
        kind: TransactionKind,
        session: date,
        security_id: str | None,
        shares: int,
        price: Decimal | None,
        commission: Decimal,
        cash_delta: Decimal,
        reason: str | None = None,
    ) -> None:
        self.transactions.append(
            Transaction(
                kind=kind,
                session=session,
                security_id=security_id,
                shares=shares,
                price=price,
                commission=commission,
                cash_delta=_money(cash_delta),
                reason=reason,
            )
        )

    # -- splits effective while held --

    def _apply_splits(self, session: date, previous: date | None) -> None:
        """A split with ex-date in ``(previous, session]`` rescales every held position at
        this open: shares x ratio (whole shares kept), the stop and the last close divided,
        the fractional share settled in cash at this session's close, no commission. The
        entry facts and the planned risk are unchanged."""
        for security_id in sorted(self.positions):
            position = self.positions[security_id]
            for ex_date, ratio in self.dataset.splits_between(security_id, previous, session):
                scaled = Decimal(position.shares) * ratio
                whole = int(scaled.to_integral_value(rounding=ROUND_DOWN))
                bar = self._bar(security_id, session)
                price = _level(bar.close if bar is not None else position.last_close / ratio)
                cash_in_lieu = _money((scaled - whole) * price)
                position.split_events.append(
                    SplitEvent(
                        ex_date=ex_date,
                        ratio=ratio,
                        shares_before=position.shares,
                        shares_after=whole,
                        cash_in_lieu=cash_in_lieu,
                        price=price,
                    )
                )
                position.shares = whole
                position.stop_level = _level(position.stop_level / ratio)
                position.last_close = _level(position.last_close / ratio)
                position.cash_in_lieu = _money(position.cash_in_lieu + cash_in_lieu)
                if cash_in_lieu != 0:
                    self.cash = _money(self.cash + cash_in_lieu)
                    self._record(
                        TransactionKind.CASH_IN_LIEU,
                        session,
                        security_id,
                        0,
                        price,
                        _ZERO,
                        cash_in_lieu,
                        f"split {ratio}:1",
                    )

    # -- exits --

    def _close_position(
        self,
        position: _Position,
        session: date,
        reason: ExitReason,
        fill: Decimal | None,
        commission: Decimal,
        participation: Decimal | None,
    ) -> None:
        proceeds = _ZERO if fill is None else _money(fill * position.shares)
        pnl = _money(
            proceeds
            + position.cash_in_lieu
            - position.cost_basis
            - position.entry_commission
            - commission
        )
        self.cash = _money(self.cash + proceeds - commission)
        self._record(
            TransactionKind.EXIT,
            session,
            position.security_id,
            position.shares,
            fill,
            commission,
            proceeds - commission,
            reason.value,
        )
        r = (
            None
            if position.planned_risk <= 0
            else (pnl / position.planned_risk).quantize(_FRACTION)
        )
        self.trades.append(
            Trade(
                security_id=position.security_id,
                window=position.window,
                signal_session=position.signal_session,
                entry_session=position.entry_session,
                shares=position.entry_shares,
                entry_open=position.entry_open,
                entry_fill=position.entry_fill,
                entry_commission=position.entry_commission,
                entry_participation_pct=position.entry_participation_pct.quantize(_FRACTION),
                entry_capacity_limited=position.entry_capacity_limited,
                stop_level=position.stop_level,
                planned_risk=position.planned_risk,
                exit_session=session,
                exit_reason=reason,
                exit_shares=position.shares,
                exit_fill=fill,
                exit_commission=commission,
                exit_participation_pct=None
                if participation is None
                else participation.quantize(_FRACTION),
                held_sessions=position.held_sessions,
                realized_pnl=pnl,
                r_multiple=r,
                missing_bar_sessions=position.missing_bar_sessions,
                bars_after_delisting=position.bars_after_delisting,
                split_events=tuple(position.split_events),
                cash_in_lieu=position.cash_in_lieu,
                mark_session=None,
                mark_price=None,
                unrealized_pnl=None,
            )
        )
        self.exited_this_session.add(position.security_id)
        del self.positions[position.security_id]

    def _exits(self, session: date) -> None:
        """Terminal valuations, then stops, then time exits -- at ``open(session)``."""
        for security_id in sorted(self.positions):
            position = self.positions[security_id]
            if self._delisting_recognized_at(security_id, session):
                if self.policy is TerminalPolicy.OPTIMISTIC:
                    price = position.last_close
                    fill, participation = self._sell_fill(
                        price, position.shares, self._addv_before(security_id, session)
                    )
                    self._close_position(
                        position,
                        session,
                        ExitReason.TERMINAL_VALUATION_OPTIMISTIC,
                        fill,
                        self._commission(position.shares),
                        participation,
                    )
                else:
                    self._close_position(
                        position, session, ExitReason.TERMINAL_TOTAL_LOSS, None, _ZERO, None
                    )
        for security_id in sorted(self.positions):
            position = self.positions[security_id]
            if not (position.stop_triggered or position.time_due):
                continue
            bar = self._bar(security_id, session)
            if bar is None:
                self.exits_deferred += 1
                continue
            reason = ExitReason.STOP if position.stop_triggered else ExitReason.TIME
            fill, participation = self._sell_fill(
                bar.open, position.shares, self._addv_before(security_id, session)
            )
            self._close_position(
                position, session, reason, fill, self._commission(position.shares), participation
            )

    # -- entries --

    def _open_planned_risk(self) -> Decimal:
        return sum((p.planned_risk for p in self.positions.values()), _ZERO)

    def _skip(self, session: date, security_id: str, reason: Skip) -> None:
        self.skips.append(SkipRecord(session=session, security_id=security_id, reason=reason))

    def _entries(self, session: date, signal_session: date, window: Window) -> None:
        candidates = sorted(
            self.source(self.dataset, signal_session, HISTORY_SESSIONS), key=lambda c: c.rank_key
        )
        c = self.config
        for candidate in candidates:
            sid = candidate.security_id
            bar = self._bar(sid, session)
            previous = self._bar(sid, signal_session)
            if bar is None or previous is None:
                self._skip(session, sid, Skip.SKIPPED_NO_EXECUTION_BAR)
                continue
            if sid in self.positions:
                self._skip(session, sid, Skip.SKIPPED_ALREADY_HELD)
                continue
            if sid in self.exited_this_session:
                self._skip(session, sid, Skip.SKIPPED_EXITED_THIS_SESSION)
                continue
            # Carry the signal session's levels onto the executing session's basis.
            factor = self.dataset.split_factor_between(sid, signal_session, session)
            previous_close = previous.close / factor
            stop_level = _level(candidate.stop_level / factor)
            gap = (bar.open - previous_close) / previous_close
            if gap > c.entry_gap_max:
                self._skip(session, sid, Skip.SKIPPED_ENTRY_GAP)
                continue
            fill_est = bar.open * (
                _ONE + c.half_spread + c.slippage_base_bps / _BPS * c.cost_multiplier
            )
            risk_per_share = fill_est - stop_level
            if risk_per_share <= 0:
                self._skip(session, sid, Skip.SKIPPED_ZERO_QUANTITY)
                continue
            shares = int(
                min(c.risk_per_trade / risk_per_share, c.position_cap / fill_est).to_integral_value(
                    rounding=ROUND_DOWN
                )
            )
            if shares < 1:
                self._skip(session, sid, Skip.SKIPPED_ZERO_QUANTITY)
                continue
            addv = self._addv_before(sid, session)
            participation = _ZERO if not addv else Decimal(shares) * fill_est / addv * 100
            fill = _price(bar.open * (_ONE + c.half_spread + self._slippage(participation)))
            commission = self._commission(shares)
            planned_risk = _money(Decimal(shares) * (fill - stop_level))
            notional = _money(Decimal(shares) * fill)
            if planned_risk > c.risk_per_trade:
                self._skip(session, sid, Skip.SKIPPED_RISK_LIMIT_AT_FINAL_FILL)
                continue
            if notional > c.position_cap:
                self._skip(session, sid, Skip.SKIPPED_POSITION_LIMIT_AT_FINAL_FILL)
                continue
            if self._open_planned_risk() + planned_risk > c.open_risk_cap:
                self._skip(session, sid, Skip.SKIPPED_RISK_CAPACITY)
                continue
            if self.cash - notional - commission < 0:
                self._skip(session, sid, Skip.SKIPPED_CASH)
                continue
            self.cash = _money(self.cash - notional - commission)
            self._record(
                TransactionKind.ENTRY,
                session,
                sid,
                shares,
                fill,
                commission,
                -notional - commission,
            )
            self.positions[sid] = _Position(
                security_id=sid,
                window=window,
                signal_session=signal_session,
                entry_session=session,
                entry_shares=shares,
                shares=shares,
                entry_open=bar.open,
                entry_fill=fill,
                entry_commission=commission,
                entry_participation_pct=participation,
                entry_capacity_limited=participation > c.capacity_flag_pct,
                stop_level=stop_level,
                planned_risk=planned_risk,
                last_close=bar.close,
                last_close_session=session,
            )

    # -- the close --

    def _mark(self, session: date, window: Window) -> None:
        c = self.config
        value = _ZERO
        for position in self.positions.values():
            bar = self._bar(position.security_id, session)
            if bar is None:
                position.missing_bar_sessions += 1
                self.missing_bar_held += 1
            else:
                position.last_close = bar.close
                position.last_close_session = session
                if self._delisting_recognized_at(position.security_id, session):
                    position.bars_after_delisting += 1
                position.stop_triggered = position.stop_triggered or bar.close < position.stop_level
            if position.entry_session != session:
                position.held_sessions += 1
            if position.held_sessions >= c.time_exit_held_sessions:
                position.time_due = True
            value += _money(position.last_close * position.shares)
        if c.idle_cash_rate_annual > 0:
            accrued = _money(self.cash * (_ONE + c.idle_cash_rate_annual / _SESSIONS_PER_YEAR))
            interest = _money(accrued - self.cash)
            self.cash = accrued
            if interest != 0:
                self._record(TransactionKind.INTEREST, session, None, 0, None, _ZERO, interest)
        self.equity.append(
            EquityPoint(
                session=session,
                window=window,
                cash=self.cash,
                positions_value=_money(value),
                equity=_money(self.cash + value),
                open_planned_risk=self._open_planned_risk(),
            )
        )

    def _mark_open_at_end(self, session: date) -> None:
        """Positions still open at the end of the block: marked at their last close, never
        charged an exit, their unrealized result recorded beside the realized ones."""
        for security_id in sorted(self.positions):
            position = self.positions[security_id]
            marked = _money(position.last_close * position.shares)
            remaining_basis = _money(position.cost_basis - position.cash_in_lieu)
            self.trades.append(
                Trade(
                    security_id=security_id,
                    window=position.window,
                    signal_session=position.signal_session,
                    entry_session=position.entry_session,
                    shares=position.entry_shares,
                    entry_open=position.entry_open,
                    entry_fill=position.entry_fill,
                    entry_commission=position.entry_commission,
                    entry_participation_pct=position.entry_participation_pct.quantize(_FRACTION),
                    entry_capacity_limited=position.entry_capacity_limited,
                    stop_level=position.stop_level,
                    planned_risk=position.planned_risk,
                    exit_session=session,
                    exit_reason=ExitReason.OPEN_AT_END,
                    exit_shares=position.shares,
                    exit_fill=None,
                    exit_commission=_ZERO,
                    exit_participation_pct=None,
                    held_sessions=position.held_sessions,
                    realized_pnl=None,
                    r_multiple=None,
                    missing_bar_sessions=position.missing_bar_sessions,
                    bars_after_delisting=position.bars_after_delisting,
                    split_events=tuple(position.split_events),
                    cash_in_lieu=position.cash_in_lieu,
                    mark_session=position.last_close_session,
                    mark_price=position.last_close,
                    unrealized_pnl=_money(marked - remaining_basis),
                )
            )
            del self.positions[security_id]

    def run(self) -> None:
        p = self.phases
        sessions = [s.session_date for s in self.dataset.calendar.sessions]
        index = {s: i for i, s in enumerate(sessions)}
        for block, entry_windows, reset in (
            ((*p.development, *p.purge), {Window.DEVELOPMENT}, Window.DEVELOPMENT),
            ((*p.validation, *p.tail), {Window.VALIDATION}, Window.VALIDATION),
        ):
            # §14.3: each evaluation window initializes independently.
            self.cash = self.config.capital
            self.positions = {}
            for session in block:
                window = p.window_of(session) or reset
                previous = sessions[index[session] - 1] if index[session] > 0 else None
                self.exited_this_session = set()
                self._apply_splits(session, previous)
                self._exits(session)
                # An entry executes only when the signal session AND the executing session
                # both lie in the evaluation window: nothing opens in the purge or the tail.
                if (
                    previous is not None
                    and p.window_of(previous) in entry_windows
                    and window in entry_windows
                ):
                    self._entries(session, previous, window)
                self._mark(session, window)
            self._mark_open_at_end(block[-1])

    def metrics(self) -> tuple[WindowMetrics, ...]:
        out: list[WindowMetrics] = []
        total_loss = self.policy is TerminalPolicy.TOTAL_LOSS
        bench = {
            p.session_date: (p.level_total_loss if total_loss else p.level)
            for p in self.dataset.benchmark.points
        }
        calendar = [s.session_date for s in self.dataset.calendar.sessions]
        capital = self.config.capital
        for window, sessions, after in (
            (Window.DEVELOPMENT, self.phases.development, self.phases.purge),
            (Window.VALIDATION, self.phases.validation, self.phases.tail),
        ):
            closed = [t for t in self.trades if t.window is window and t.realized_pnl is not None]
            pnls = [t.realized_pnl for t in closed if t.realized_pnl is not None]
            wins = [x for x in pnls if x > 0]
            losses = [x for x in pnls if x <= 0]
            evaluation = [e for e in self.equity if sessions[0] <= e.session <= sessions[-1]]
            liquidation = [e for e in self.equity if sessions[0] <= e.session <= after[-1]]
            drawdown_evaluation = self._drawdown(evaluation)
            drawdown_liquidation = self._drawdown(liquidation)
            worst_session = _ZERO
            prior = capital
            exposure: list[Decimal] = []
            for point in evaluation:
                worst_session = min(worst_session, point.equity - prior)
                prior = point.equity
                exposure.append(point.positions_value / point.equity if point.equity > 0 else _ZERO)
            traded = sum(
                (
                    _money(t.entry_fill * t.shares)
                    + (_money(t.exit_fill * t.exit_shares) if t.exit_fill is not None else _ZERO)
                    for t in self.trades
                    if t.window is window
                ),
                _ZERO,
            )
            end_equity = evaluation[-1].equity if evaluation else capital
            liquidation_end_equity = liquidation[-1].equity if liquidation else capital
            # Both comparisons start at the close BEFORE the first evaluation session, so the
            # first session's return counts for the strategy and the benchmark alike.
            start_index = calendar.index(sessions[0])
            b_start = bench.get(calendar[start_index - 1]) if start_index > 0 else None
            out.append(
                WindowMetrics(
                    window=window,
                    evaluation_start=sessions[0],
                    evaluation_end=sessions[-1],
                    liquidation_end=after[-1],
                    trades=len(closed),
                    winners=len(wins),
                    losers=len(losses),
                    expectancy=None if not pnls else _money(sum(pnls, _ZERO) / len(pnls)),
                    hit_rate=None
                    if not pnls
                    else (Decimal(len(wins)) / len(pnls)).quantize(_FRACTION),
                    average_win=None if not wins else _money(sum(wins, _ZERO) / len(wins)),
                    average_loss=None if not losses else _money(sum(losses, _ZERO) / len(losses)),
                    net_pnl=_money(sum(pnls, _ZERO)),
                    max_drawdown=drawdown_evaluation,
                    max_drawdown_through_liquidation=drawdown_liquidation,
                    turnover=(traded / capital).quantize(_FRACTION),
                    average_exposure=(sum(exposure, _ZERO) / len(exposure)).quantize(_FRACTION)
                    if exposure
                    else _ZERO,
                    capacity_limited_entries=sum(
                        1 for t in self.trades if t.window is window and t.entry_capacity_limited
                    ),
                    max_participation_pct=max(
                        (t.entry_participation_pct for t in self.trades if t.window is window),
                        default=_ZERO,
                    ),
                    losses_beyond_one_r=sum(
                        1 for t in closed if t.r_multiple is not None and t.r_multiple < -1
                    ),
                    worst_trade_pnl=min(pnls) if pnls else None,
                    worst_session_pnl=_money(worst_session),
                    terminal_events=sum(
                        1
                        for t in self.trades
                        if t.window is window
                        and t.exit_reason
                        in (
                            ExitReason.TERMINAL_VALUATION_OPTIMISTIC,
                            ExitReason.TERMINAL_TOTAL_LOSS,
                        )
                    ),
                    open_at_end=sum(
                        1
                        for t in self.trades
                        if t.window is window and t.exit_reason is ExitReason.OPEN_AT_END
                    ),
                    start_equity=capital,
                    end_equity=end_equity,
                    return_fraction=((end_equity - capital) / capital).quantize(_FRACTION),
                    benchmark_return_fraction=ratio_return(b_start, bench.get(sessions[-1])),
                    liquidation_end_equity=liquidation_end_equity,
                    liquidation_return_fraction=(
                        (liquidation_end_equity - capital) / capital
                    ).quantize(_FRACTION),
                    liquidation_benchmark_return_fraction=ratio_return(
                        b_start, bench.get(after[-1])
                    ),
                )
            )
        return tuple(out)

    def _drawdown(self, points: list[EquityPoint]) -> Decimal:
        peak = self.config.capital
        drawdown = _ZERO
        for point in points:
            peak = max(peak, point.equity)
            drawdown = max(drawdown, (peak - point.equity) / peak)
        return drawdown.quantize(_FRACTION)

    def ledger(self, label: str) -> Ledger:
        return Ledger(
            policy=self.policy,
            label=label,
            trades=tuple(self.trades),
            skips=tuple(self.skips),
            equity=tuple(self.equity),
            transactions=tuple(self.transactions),
            metrics=self.metrics(),
            missing_bar_held_sessions=self.missing_bar_held,
            exits_deferred_no_bar=self.exits_deferred,
        )


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class M0Result:
    """One M0 run: the trial identity, every ledger, the baselines and the determinism digest."""

    specification_version: str
    trial: int
    trial_digest: str
    trial_record: dict[str, Any]
    configuration: dict[str, Any]
    data_kind: DataKind
    phases: dict[str, Any]
    input_set_digest: str
    dataset_digest: str
    benchmark_digest: str
    ledgers: tuple[Ledger, ...]
    baselines: tuple[Ledger, ...]
    sensitivities: tuple[Ledger, ...]
    equal_weight_hold: dict[str, Any]
    census: tuple[dict[str, Any], ...]

    def document(self) -> dict[str, Any]:
        return {
            "label": "SYNTHETIC / EXPLORATORY_HINDSIGHT"
            if self.data_kind is DataKind.SYNTHETIC
            else "EXPLORATORY_HINDSIGHT",
            "profile": ExploratoryProfile.EXPLORATORY_HINDSIGHT.value,
            "derivation": ExploratoryDerivation.AS_DATED.value,
            "specification_version": self.specification_version,
            "trial": self.trial,
            "trial_digest": self.trial_digest,
            "trial_record": self.trial_record,
            "configuration": self.configuration,
            "data_kind": self.data_kind.value,
            "phases": self.phases,
            "input_set_digest": self.input_set_digest,
            "dataset_digest": self.dataset_digest,
            "benchmark_digest": self.benchmark_digest,
            "ledgers": [ledger.document() for ledger in self.ledgers],
            "baselines": [ledger.document() for ledger in self.baselines],
            "sensitivities": [ledger.document() for ledger in self.sensitivities],
            "equal_weight_hold": self.equal_weight_hold,
            "census": list(self.census),
        }

    @property
    def digest(self) -> str:
        """SHA-256 over the canonical result: the determinism evidence."""
        return hashlib.sha256(
            json.dumps(self.document(), sort_keys=True, separators=(",", ":")).encode("ascii")
        ).hexdigest()


def _calendar_digest(dataset: ExploratoryDataset) -> str:
    """The calendar's content -- every session date and opening instant -- not only its name."""
    document = [
        [s.session_date.isoformat(), s.open_at.isoformat()] for s in dataset.calendar.sessions
    ]
    return hashlib.sha256(json.dumps(document, separators=(",", ":")).encode("ascii")).hexdigest()


def trial_document(
    specification: ResearchSpecification,
    config: M0Configuration,
    dataset: ExploratoryDataset,
    phases: Phases,
) -> dict[str, Any]:
    """The frozen parameter identity (§14.3), as a document: the research specification, the
    accepted module's identity and history requirement, every configuration setting, the
    calendar by content, the phase boundaries, and the benchmark and resolution rule versions
    -- everything that decides execution, computed before any development bar is read."""
    return {
        "specification": specification.document(),
        "strategy": dict(STRATEGY_IDENTITY),
        "history_sessions": HISTORY_SESSIONS,
        "configuration": config.document(),
        "calendar_version": dataset.calendar.version,
        "calendar_digest": _calendar_digest(dataset),
        "phases": phases.document(),
        "benchmark_id": dataset.benchmark.benchmark_id,
        "benchmark_version": dataset.benchmark.version,
        "resolution_version": dataset.layer.resolution_version,
        "membership_rule": dataset.membership.rule.document(),
    }


def trial_digest(
    specification: ResearchSpecification,
    config: M0Configuration,
    dataset: ExploratoryDataset,
    phases: Phases,
) -> str:
    """SHA-256 over :func:`trial_document`."""
    return hashlib.sha256(
        json.dumps(
            trial_document(specification, config, dataset, phases),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()


def run_m0(
    *,
    specification: ResearchSpecification,
    inputs: ExploratoryInputSet,
    dataset: ExploratoryDataset,
    config: M0Configuration,
    data_kind: DataKind,
) -> M0Result:
    """One complete M0 run: admission, validation, freezing, both ledgers, baselines,
    sensitivities. Every refusal is closed and happens before any bar is read."""
    if type(data_kind) is not DataKind:
        raise M0RunError(RunRefusal.REFUSED_MALFORMED_DATA_KIND)
    if type(config) is not M0Configuration:
        raise M0RunError(RunRefusal.REFUSED_INVALID_CONFIGURATION)
    if admit(specification, inputs) is not AdmissionOutcome.ADMITTED:
        raise M0RunError(RunRefusal.REFUSED_NOT_ADMITTED)
    if (
        data_kind is DataKind.REAL
        and config.provenance is not ConfigurationProvenance.OWNER_SELECTED
    ):
        raise M0RunError(RunRefusal.REFUSED_FIXTURE_ON_REAL_DATA)
    sessions = tuple(s.session_date for s in dataset.calendar.sessions)
    if config.owner_selections is not None and (
        not sessions
        or sessions[0] < config.owner_selections.o8_data_window_start
        or sessions[-1] > config.owner_selections.o8_data_window_end
    ):
        raise M0RunError(RunRefusal.REFUSED_SELECTION_INCONSISTENT)
    if dataset.content_digest not in {p.content_digest for p in inputs.publications}:
        raise M0RunError(RunRefusal.REFUSED_CONTENT_DIGEST_MISMATCH)
    phases = phases_for(sessions, config)
    record = trial_document(specification, config, dataset, phases)
    frozen = trial_digest(specification, config, dataset, phases)

    def simulate(
        cfg: M0Configuration, policy: TerminalPolicy, source: SignalSource, label: str
    ) -> Ledger:
        simulation = _Simulation(dataset, cfg, phases, policy, source)
        simulation.run()
        return simulation.ledger(label)

    b0 = baseline_b0_signals(config.baseline_momentum_sessions, config.baseline_stop_sessions)
    ledgers = tuple(
        simulate(config, policy, breakout_long_signals, f"breakout-long/{policy.value}")
        for policy in TerminalPolicy
    )
    baselines = tuple(
        simulate(config, policy, b0, f"B0/{policy.value}") for policy in TerminalPolicy
    )
    sensitivities: list[Ledger] = []
    for multiplier in (Decimal(0), Decimal(2)):
        cfg = M0Configuration(**{**_fields(config), "cost_multiplier": multiplier})
        sensitivities.append(
            simulate(
                cfg,
                TerminalPolicy.OPTIMISTIC,
                breakout_long_signals,
                f"breakout-long/OPTIMISTIC/costs-x{multiplier}",
            )
        )
    idle = M0Configuration(**{**_fields(config), "idle_cash_rate_annual": Decimal("0.04")})
    sensitivities.append(
        simulate(
            idle,
            TerminalPolicy.OPTIMISTIC,
            breakout_long_signals,
            "breakout-long/OPTIMISTIC/idle-4pct",
        )
    )
    bench = {p.session_date: p for p in dataset.benchmark.points}
    equal_weight: dict[str, Any] = {}
    for window, block in (
        (Window.DEVELOPMENT, phases.development),
        (Window.VALIDATION, phases.validation),
    ):
        start_index = sessions.index(block[0])
        before = bench.get(sessions[start_index - 1]) if start_index > 0 else None
        end = bench[block[-1]]
        equal_weight[window.value] = {
            "start_session_close": None if before is None else before.session_date.isoformat(),
            "end_session": block[-1].isoformat(),
            "index_start": None if before is None else str(before.level),
            "index_end": str(end.level),
            "return_fraction": _fraction(
                ratio_return(None if before is None else before.level, end.level)
            ),
            "return_fraction_total_loss": _fraction(
                ratio_return(
                    None if before is None else before.level_total_loss, end.level_total_loss
                )
            ),
            "costs": "NONE (an index, not a book)",
        }
    return M0Result(
        specification_version=specification.version,
        trial=specification.trial,
        trial_digest=frozen,
        trial_record=record,
        configuration=config.document(),
        data_kind=data_kind,
        phases=phases.document(),
        input_set_digest=inputs.digest,
        dataset_digest=dataset.content_digest,
        benchmark_digest=dataset.benchmark.digest,
        ledgers=ledgers,
        baselines=baselines,
        sensitivities=tuple(sensitivities),
        equal_weight_hold=equal_weight,
        census=tuple(c.document() for c in dataset.membership.census),
    )


def _fraction(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _fields(config: M0Configuration) -> dict[str, Any]:
    return {name: getattr(config, name) for name in config.__slots__}


__all__ = [
    "HISTORY_SESSIONS",
    "M0_RESEARCH_SPECIFICATION",
    "M0_SYNTHETIC_FIXTURE",
    "OWNER_DECISIONS",
    "STRATEGY_IDENTITY",
    "Acknowledgment",
    "AcquisitionRouteChoice",
    "BenchmarkChoice",
    "Candidate",
    "ComputeLocationChoice",
    "ConfigurationProvenance",
    "CostModelChoice",
    "DataKind",
    "EquityPoint",
    "ExitReason",
    "ExitRuleChoice",
    "ExploratoryModeChoice",
    "FinalFillPolicyChoice",
    "Ledger",
    "M0Configuration",
    "M0Result",
    "M0RunError",
    "OwnerSelections",
    "Phases",
    "RunRefusal",
    "SizingPolicyChoice",
    "Skip",
    "SkipRecord",
    "SplitEvent",
    "TerminalAccountingChoice",
    "TerminalPolicy",
    "Trade",
    "Transaction",
    "TransactionKind",
    "Window",
    "WindowMetrics",
    "baseline_b0_signals",
    "breakout_long_signals",
    "phases_for",
    "ratio_return",
    "run_m0",
    "trial_digest",
    "trial_document",
]
