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
  recorded skips; no entries in the purge or tail;
* terminal recognition at ``open(t)`` from an admissible ``delisted`` action (§14.2), two
  complete ledgers (optimistic valuation and total loss), every figure on both;
* development and validation each initialized empty under the frozen trial digest (§14.3).

**Configuration provenance is explicit.** :data:`M0_SYNTHETIC_FIXTURE` is an engineering test
input carrying the §14 proposed settings and benchmark A; it is *not* an owner selection.
A run over real data (:attr:`DataKind.REAL`) is refused unless the configuration is
``OWNER_SELECTED`` with every O-1…O-11 choice recorded -- nothing falls back to the fixture.

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
from kalpamani.strategies.breakout.long import BreakoutLong

_ZERO: Final = Decimal(0)
_ONE: Final = Decimal(1)
_CENT: Final = Decimal("0.01")
_BPS: Final = Decimal(10_000)
_PRICE: Final = Decimal("0.0001")
_SESSIONS_PER_YEAR: Final = Decimal(252)

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
    """Why a run did not start. Closed."""

    REFUSED_NOT_ADMITTED = "REFUSED_NOT_ADMITTED"
    REFUSED_UNSELECTED_CONFIGURATION = "REFUSED_UNSELECTED_CONFIGURATION"
    REFUSED_FIXTURE_ON_REAL_DATA = "REFUSED_FIXTURE_ON_REAL_DATA"
    REFUSED_CALENDAR_TOO_SHORT = "REFUSED_CALENDAR_TOO_SHORT"
    REFUSED_CONTENT_DIGEST_MISMATCH = "REFUSED_CONTENT_DIGEST_MISMATCH"


class M0RunError(Exception):
    """One closed refusal."""

    def __init__(self, refusal: RunRefusal) -> None:
        super().__init__(refusal.value)
        self.refusal = refusal


OWNER_DECISIONS: Final = tuple(f"O-{n}" for n in range(1, 12))


@dataclass(frozen=True, slots=True, kw_only=True)
class M0Configuration:
    """Every parameter §11-§14 names, with its provenance. Frozen into the trial digest."""

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
    owner_selections: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.provenance) is not ConfigurationProvenance:
            raise TypeError("provenance must be an exact ConfigurationProvenance")
        if self.provenance is ConfigurationProvenance.OWNER_SELECTED:
            missing = [key for key in OWNER_DECISIONS if not self.owner_selections.get(key)]
            if missing:
                raise M0RunError(RunRefusal.REFUSED_UNSELECTED_CONFIGURATION)
        if self.benchmark_option != "A":
            raise ValueError("only benchmark option A is implemented in this slice")

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
            "owner_selections": dict(sorted(self.owner_selections.items())),
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
# Trades and ledgers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class Trade:
    """One closed (or open-at-end) trade with every figure §12.2 records."""

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
    exit_fill: Decimal | None
    exit_commission: Decimal
    exit_participation_pct: Decimal | None
    held_sessions: int
    realized_pnl: Decimal | None
    r_multiple: Decimal | None
    missing_bar_sessions: int
    bars_after_delisting: int

    def document(self) -> dict[str, Any]:
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
            "exit_fill": None if self.exit_fill is None else str(self.exit_fill),
            "exit_commission": str(self.exit_commission),
            "exit_participation_pct": (
                None if self.exit_participation_pct is None else str(self.exit_participation_pct)
            ),
            "held_sessions": self.held_sessions,
            "realized_pnl": None if self.realized_pnl is None else str(self.realized_pnl),
            "r_multiple": None if self.r_multiple is None else str(self.r_multiple),
            "missing_bar_sessions": self.missing_bar_sessions,
            "bars_after_delisting": self.bars_after_delisting,
        }


@dataclass(slots=True)
class _Position:
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
    held_sessions: int = 1
    last_close: Decimal = _ZERO
    missing_bar_sessions: int = 0
    bars_after_delisting: int = 0
    stop_triggered: bool = False
    time_due: bool = False


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
    """Protocol §8 figures for one window and one ledger, net of costs."""

    window: Window
    trades: int
    winners: int
    losers: int
    expectancy: Decimal | None
    hit_rate: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    net_pnl: Decimal
    max_drawdown: Decimal
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
    benchmark_return_fraction: Decimal

    def document(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in self.__slots__:
            value = getattr(self, name)
            out[name] = (
                value.value
                if isinstance(value, Window)
                else (
                    None if value is None else str(value) if isinstance(value, Decimal) else value
                )
            )
        return out


@dataclass(frozen=True, slots=True, kw_only=True)
class Ledger:
    """One complete ledger under one terminal policy."""

    policy: TerminalPolicy
    label: str
    trades: tuple[Trade, ...]
    skips: tuple[SkipRecord, ...]
    equity: tuple[EquityPoint, ...]
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
            "metrics": [m.document() for m in self.metrics],
            "missing_bar_held_sessions": self.missing_bar_held_sessions,
            "exits_deferred_no_bar": self.exits_deferred_no_bar,
        }


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class Candidate:
    """One signal at ``close(signal_session)``, ranked for execution at the next open."""

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
    executing session. ``None`` when the window is short."""
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


class _Simulation:
    """One ledger's session loop. Deterministic; reads no clock."""

    def __init__(
        self,
        dataset: ExploratoryDataset,
        config: M0Configuration,
        phases: Phases,
        policy: TerminalPolicy,
        source: SignalSource,
        history: int,
    ) -> None:
        self.dataset = dataset
        self.config = config
        self.phases = phases
        self.policy = policy
        self.source = source
        self.history = history
        self.cash = _ZERO
        self.positions: dict[str, _Position] = {}
        self.trades: list[Trade] = []
        self.skips: list[SkipRecord] = []
        self.equity: list[EquityPoint] = []
        self.missing_bar_held = 0
        self.exits_deferred = 0
        self.window_pnl: dict[Window, list[Decimal]] = {}
        self._bar_cache: dict[str, dict[date, PriceBarValues]] = {}
        self._delisted_cache: dict[str, date | None] = {}

    # -- data access: every read is bounded at the instant the rule states --

    def _bars(self, security_id: str) -> dict[date, PriceBarValues]:
        if security_id not in self._bar_cache:
            last = self.dataset.calendar.sessions[-1].session_date
            self._bar_cache[security_id] = {
                bar.session_date: bar for bar in self.dataset.bars_through(security_id, last)
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
        cost_basis = _money(position.entry_fill * position.shares)
        pnl = _money(proceeds - cost_basis - position.entry_commission - commission)
        self.cash = _money(self.cash + proceeds - commission)
        r = (
            None
            if position.planned_risk <= 0
            else (pnl / position.planned_risk).quantize(Decimal("0.0001"))
        )
        self.trades.append(
            Trade(
                security_id=position.security_id,
                window=position.window,
                signal_session=position.signal_session,
                entry_session=position.entry_session,
                shares=position.shares,
                entry_open=position.entry_open,
                entry_fill=position.entry_fill,
                entry_commission=position.entry_commission,
                entry_participation_pct=position.entry_participation_pct.quantize(
                    Decimal("0.0001")
                ),
                entry_capacity_limited=position.entry_capacity_limited,
                stop_level=position.stop_level,
                planned_risk=position.planned_risk,
                exit_session=session,
                exit_reason=reason,
                exit_fill=fill,
                exit_commission=commission,
                exit_participation_pct=None
                if participation is None
                else participation.quantize(Decimal("0.0001")),
                held_sessions=position.held_sessions,
                realized_pnl=pnl,
                r_multiple=r,
                missing_bar_sessions=position.missing_bar_sessions,
                bars_after_delisting=position.bars_after_delisting,
            )
        )
        self.window_pnl.setdefault(position.window, []).append(pnl)
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

    def _entries(self, session: date, signal_session: date, window: Window) -> None:
        candidates = sorted(
            self.source(self.dataset, signal_session, self.history), key=lambda c: c.rank_key
        )
        c = self.config
        for candidate in candidates:
            sid = candidate.security_id
            bar = self._bar(sid, session)
            previous = self._bar(sid, signal_session)
            if bar is None or previous is None:
                self.skips.append(
                    SkipRecord(
                        session=session, security_id=sid, reason=Skip.SKIPPED_NO_EXECUTION_BAR
                    )
                )
                continue
            if sid in self.positions:
                self.skips.append(
                    SkipRecord(session=session, security_id=sid, reason=Skip.SKIPPED_ALREADY_HELD)
                )
                continue
            gap = (bar.open - previous.close) / previous.close
            if gap > c.entry_gap_max:
                self.skips.append(
                    SkipRecord(session=session, security_id=sid, reason=Skip.SKIPPED_ENTRY_GAP)
                )
                continue
            fill_est = bar.open * (
                _ONE + c.half_spread + c.slippage_base_bps / _BPS * c.cost_multiplier
            )
            risk_per_share = fill_est - candidate.stop_level
            if risk_per_share <= 0:
                self.skips.append(
                    SkipRecord(session=session, security_id=sid, reason=Skip.SKIPPED_ZERO_QUANTITY)
                )
                continue
            shares = int(
                min(c.risk_per_trade / risk_per_share, c.position_cap / fill_est).to_integral_value(
                    rounding=ROUND_DOWN
                )
            )
            if shares < 1:
                self.skips.append(
                    SkipRecord(session=session, security_id=sid, reason=Skip.SKIPPED_ZERO_QUANTITY)
                )
                continue
            addv = self._addv_before(sid, session)
            participation = _ZERO if not addv else Decimal(shares) * fill_est / addv * 100
            fill = _price(bar.open * (_ONE + c.half_spread + self._slippage(participation)))
            commission = self._commission(shares)
            planned_risk = _money(Decimal(shares) * (fill - candidate.stop_level))
            notional = _money(Decimal(shares) * fill)
            if planned_risk > c.risk_per_trade:
                self.skips.append(
                    SkipRecord(
                        session=session,
                        security_id=sid,
                        reason=Skip.SKIPPED_RISK_LIMIT_AT_FINAL_FILL,
                    )
                )
                continue
            if notional > c.position_cap:
                self.skips.append(
                    SkipRecord(
                        session=session,
                        security_id=sid,
                        reason=Skip.SKIPPED_POSITION_LIMIT_AT_FINAL_FILL,
                    )
                )
                continue
            if self._open_planned_risk() + planned_risk > c.open_risk_cap:
                self.skips.append(
                    SkipRecord(session=session, security_id=sid, reason=Skip.SKIPPED_RISK_CAPACITY)
                )
                continue
            if self.cash - notional - commission < 0:
                self.skips.append(
                    SkipRecord(session=session, security_id=sid, reason=Skip.SKIPPED_CASH)
                )
                continue
            self.cash = _money(self.cash - notional - commission)
            self.positions[sid] = _Position(
                security_id=sid,
                window=window,
                signal_session=signal_session,
                entry_session=session,
                shares=shares,
                entry_open=bar.open,
                entry_fill=fill,
                entry_commission=commission,
                entry_participation_pct=participation,
                entry_capacity_limited=participation > c.capacity_flag_pct,
                stop_level=candidate.stop_level,
                planned_risk=planned_risk,
                last_close=bar.close,
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
                if self._delisting_recognized_at(position.security_id, session):
                    position.bars_after_delisting += 1
                position.stop_triggered = position.stop_triggered or bar.close < position.stop_level
            if position.entry_session != session:
                position.held_sessions += 1
            if position.held_sessions >= c.time_exit_held_sessions:
                position.time_due = True
            value += _money(position.last_close * position.shares)
        if c.idle_cash_rate_annual > 0:
            self.cash = _money(self.cash * (_ONE + c.idle_cash_rate_annual / _SESSIONS_PER_YEAR))
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

    def _mark_open_at_end(self, window: Window, session: date) -> None:
        for security_id in sorted(self.positions):
            position = self.positions[security_id]
            self.trades.append(
                Trade(
                    security_id=security_id,
                    window=position.window,
                    signal_session=position.signal_session,
                    entry_session=position.entry_session,
                    shares=position.shares,
                    entry_open=position.entry_open,
                    entry_fill=position.entry_fill,
                    entry_commission=position.entry_commission,
                    entry_participation_pct=position.entry_participation_pct.quantize(
                        Decimal("0.0001")
                    ),
                    entry_capacity_limited=position.entry_capacity_limited,
                    stop_level=position.stop_level,
                    planned_risk=position.planned_risk,
                    exit_session=session,
                    exit_reason=ExitReason.OPEN_AT_END,
                    exit_fill=None,
                    exit_commission=_ZERO,
                    exit_participation_pct=None,
                    held_sessions=position.held_sessions,
                    realized_pnl=None,
                    r_multiple=None,
                    missing_bar_sessions=position.missing_bar_sessions,
                    bars_after_delisting=position.bars_after_delisting,
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
                self._exits(session)
                previous = sessions[index[session] - 1] if index[session] > 0 else None
                if previous is not None and p.window_of(previous) in entry_windows:
                    self._entries(session, previous, window)
                self._mark(session, window)
            self._mark_open_at_end(reset, block[-1])

    def metrics(self) -> tuple[WindowMetrics, ...]:
        out: list[WindowMetrics] = []
        bench = {p.session_date: p.level for p in self.dataset.benchmark.points}
        for window, sessions in (
            (Window.DEVELOPMENT, self.phases.development),
            (Window.VALIDATION, self.phases.validation),
        ):
            closed = [t for t in self.trades if t.window is window and t.realized_pnl is not None]
            pnls = [t.realized_pnl for t in closed if t.realized_pnl is not None]
            wins = [x for x in pnls if x > 0]
            losses = [x for x in pnls if x <= 0]
            points = [
                e
                for e in self.equity
                if e.window is window
                or (e.window in (Window.PURGE, Window.TAIL) and self._follows(window, e.session))
            ]
            peak = self.config.capital
            drawdown = _ZERO
            worst_session = _ZERO
            prior = self.config.capital
            exposure: list[Decimal] = []
            for point in points:
                peak = max(peak, point.equity)
                drawdown = max(drawdown, (peak - point.equity) / peak)
                worst_session = min(worst_session, point.equity - prior)
                prior = point.equity
                exposure.append(point.positions_value / point.equity if point.equity > 0 else _ZERO)
            traded = sum(
                (
                    _money(t.entry_fill * t.shares)
                    + (_money(t.exit_fill * t.shares) if t.exit_fill is not None else _ZERO)
                    for t in self.trades
                    if t.window is window
                ),
                _ZERO,
            )
            end_equity = points[-1].equity if points else self.config.capital
            b_start = bench.get(sessions[0])
            b_end = bench.get(sessions[-1])
            out.append(
                WindowMetrics(
                    window=window,
                    trades=len(closed),
                    winners=len(wins),
                    losers=len(losses),
                    expectancy=None if not pnls else _money(sum(pnls, _ZERO) / len(pnls)),
                    hit_rate=None
                    if not pnls
                    else (Decimal(len(wins)) / len(pnls)).quantize(Decimal("0.0001")),
                    average_win=None if not wins else _money(sum(wins, _ZERO) / len(wins)),
                    average_loss=None if not losses else _money(sum(losses, _ZERO) / len(losses)),
                    net_pnl=_money(sum(pnls, _ZERO)),
                    max_drawdown=drawdown.quantize(Decimal("0.0001")),
                    turnover=(traded / self.config.capital).quantize(Decimal("0.0001")),
                    average_exposure=(sum(exposure, _ZERO) / len(exposure)).quantize(
                        Decimal("0.0001")
                    )
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
                    start_equity=self.config.capital,
                    end_equity=end_equity,
                    return_fraction=(
                        (end_equity - self.config.capital) / self.config.capital
                    ).quantize(Decimal("0.0001")),
                    benchmark_return_fraction=(
                        ((b_end / b_start) - _ONE).quantize(Decimal("0.0001"))
                        if b_start and b_end and b_start > 0
                        else _ZERO
                    ),
                )
            )
        return tuple(out)

    def _follows(self, window: Window, session: date) -> bool:
        p = self.phases
        if window is Window.DEVELOPMENT:
            return bool(p.purge) and p.purge[0] <= session <= p.purge[-1]
        return bool(p.tail) and p.tail[0] <= session <= p.tail[-1]

    def ledger(self, label: str) -> Ledger:
        return Ledger(
            policy=self.policy,
            label=label,
            trades=tuple(self.trades),
            skips=tuple(self.skips),
            equity=tuple(self.equity),
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


def trial_digest(
    specification: ResearchSpecification,
    config: M0Configuration,
    dataset: ExploratoryDataset,
    phases: Phases,
) -> str:
    """The frozen parameter identity (§14.3): specification, configuration, calendar, phases,
    benchmark construction -- computed before any development bar is read."""
    document = {
        "specification": specification.document(),
        "configuration": config.document(),
        "calendar_version": dataset.calendar.version,
        "phases": phases.document(),
        "benchmark_version": dataset.benchmark.version,
        "resolution_version": dataset.layer.resolution_version,
    }
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def run_m0(
    *,
    specification: ResearchSpecification,
    inputs: ExploratoryInputSet,
    dataset: ExploratoryDataset,
    config: M0Configuration,
    data_kind: DataKind,
    history_sessions: int = 252,
) -> M0Result:
    """One complete M0 run: admission, freezing, both ledgers, baselines, sensitivities."""
    if admit(specification, inputs) is not AdmissionOutcome.ADMITTED:
        raise M0RunError(RunRefusal.REFUSED_NOT_ADMITTED)
    if (
        data_kind is DataKind.REAL
        and config.provenance is not ConfigurationProvenance.OWNER_SELECTED
    ):
        raise M0RunError(RunRefusal.REFUSED_FIXTURE_ON_REAL_DATA)
    if dataset.content_digest not in {p.content_digest for p in inputs.publications}:
        raise M0RunError(RunRefusal.REFUSED_CONTENT_DIGEST_MISMATCH)
    sessions = tuple(s.session_date for s in dataset.calendar.sessions)
    phases = phases_for(sessions, config)
    frozen = trial_digest(specification, config, dataset, phases)

    def simulate(
        cfg: M0Configuration, policy: TerminalPolicy, source: SignalSource, label: str
    ) -> Ledger:
        simulation = _Simulation(dataset, cfg, phases, policy, source, history_sessions)
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
    equal_weight = {
        window.value: {
            "index_start": str(bench[block[0]].level),
            "index_end": str(bench[block[-1]].level),
            "return_fraction": str(
                ((bench[block[-1]].level / bench[block[0]].level) - _ONE).quantize(
                    Decimal("0.0001")
                )
            ),
            "return_fraction_total_loss": str(
                (
                    (bench[block[-1]].level_total_loss / bench[block[0]].level_total_loss) - _ONE
                ).quantize(Decimal("0.0001"))
            ),
            "costs": "NONE (an index, not a book)",
        }
        for window, block in (
            (Window.DEVELOPMENT, phases.development),
            (Window.VALIDATION, phases.validation),
        )
    }
    return M0Result(
        specification_version=specification.version,
        trial=specification.trial,
        trial_digest=frozen,
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


def _fields(config: M0Configuration) -> dict[str, Any]:
    return {name: getattr(config, name) for name in config.__slots__}


__all__ = [
    "M0_RESEARCH_SPECIFICATION",
    "M0_SYNTHETIC_FIXTURE",
    "OWNER_DECISIONS",
    "Candidate",
    "ConfigurationProvenance",
    "DataKind",
    "EquityPoint",
    "ExitReason",
    "Ledger",
    "M0Configuration",
    "M0Result",
    "M0RunError",
    "Phases",
    "RunRefusal",
    "Skip",
    "SkipRecord",
    "TerminalPolicy",
    "Trade",
    "Window",
    "WindowMetrics",
    "baseline_b0_signals",
    "breakout_long_signals",
    "phases_for",
    "run_m0",
    "trial_digest",
]
