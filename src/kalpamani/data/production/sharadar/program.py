"""The accepted acquisition-program planner: O-5 recompiled from bounded runs (ADR-0053 §13.4).

**A program is a deterministic sequence of run slices, each compiled by the accepted plan
compiler, that together cover one acquisition window exactly once.** The owner's
decision (ADR-0053 §13.0) requires O-5 and I-8 to be recompiled by this planner rather
than copied from indicative arithmetic; every count a program reports is read from the
compiled plans it contains, never typed.

**The shape of a program.** The replacement first run carries the most recent stocks
sessions (from a stated start date to the window's end), the ``table=stocks`` tickers
snapshot, and the actions year windows of a stated first-run actions coverage. Every
later run walks backwards through the remaining calendar days, carrying one tickers
snapshot (Silver maps every stocks and actions row through the **same run's** snapshot,
so no run may omit it) and as many stocks session dates as the per-run ceiling admits;
the final run also carries the residual actions coverage before the first run's, cut
into canonical year windows by the plan compiler. Each run is held to the accepted
per-run ceiling on **worst-case provider calls** -- one conditional probe per data
coordinate -- so a run plans at most 48 data coordinates, and no run may reach 96
provider calls unless every one of its groups is exactly full.

**What the planner proves, and what it does not.** The stocks session dates of all runs
partition the window with no gap and no overlap; the actions windows of all runs
partition it likewise and are contiguous; every run carries exactly one tickers
snapshot; no run exceeds the coordinate, call or write ceilings; and every plan is the
accepted compiler's, digest and all. It establishes nothing about the vendor -- whether
a session date is a trading day, whether a group will be short or full -- and it
allocates no run: a program is arithmetic, and every run in it is a separate written
authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.production.sharadar.inputs import Slice, parse_slice
from kalpamani.data.production.sharadar.plan import (
    MAX_DATA_COORDINATES_PER_RUN,
    MAX_PROVIDER_CALLS_PER_RUN,
    MAX_RESPONSE_BYTES,
    PRODUCTION_MODES,
    SNAPSHOT_WINDOW,
    CompiledPlan,
    ProductionPlanError,
    canonical_windows,
    compile_plan,
)

#: The one program contract, bound into the program digest.
PROGRAM_CONTRACT_ID: Final = "kalpamani-production-acquisition-program/v1"
#: Every run needs the tickers snapshot, so at most this many stocks sessions fit.
MAX_STOCKS_SESSIONS_PER_RUN: Final = MAX_DATA_COORDINATES_PER_RUN - 1


class ProgramPlanError(ValueError):
    """A program could not be compiled from its specification. **Carries no value.**"""

    __slots__ = ()

    def __init__(self) -> None:
        """Carry the fixed sentence."""
        super().__init__("an acquisition program could not be compiled from this specification")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgramSpec:
    """What one program covers: the whole window, the first run's own coverage, the mode."""

    window_start: date
    window_end: date
    first_run_stocks_start: date
    first_run_actions_start: date
    acquisition_mode: AcquisitionMode
    max_response_bytes: int = MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        for value in (
            self.window_start,
            self.window_end,
            self.first_run_stocks_start,
            self.first_run_actions_start,
        ):
            if type(value) is not date:
                raise ProgramPlanError() from None
        if type(self.acquisition_mode) is not AcquisitionMode:
            raise ProgramPlanError() from None
        if self.acquisition_mode not in PRODUCTION_MODES:
            raise ProgramPlanError() from None
        if not self.window_start <= self.first_run_stocks_start <= self.window_end:
            raise ProgramPlanError() from None
        if not self.window_start <= self.first_run_actions_start <= self.window_end:
            raise ProgramPlanError() from None
        if type(self.max_response_bytes) is not int or not 1 <= self.max_response_bytes <= (
            MAX_RESPONSE_BYTES
        ):
            raise ProgramPlanError() from None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgramRun:
    """One run of a program: its slice, its compiled plan and the counts read from it."""

    ordinal: int
    slice: Slice
    plan: CompiledPlan

    @property
    def data_coordinates(self) -> int:
        """The run's planned data coordinates ``N``."""
        return self.plan.data_coordinates

    @property
    def max_provider_calls(self) -> int:
        """The run's worst-case provider calls ``2N``."""
        return self.plan.max_provider_calls

    @property
    def expected_writes(self) -> int:
        """The run's conditional S3 writes when complete: ``1 + 3N + 1``."""
        return self.plan.expected_writes

    def __repr__(self) -> str:
        """Counts only."""
        return f"ProgramRun(ordinal={self.ordinal}, data_coordinates={self.data_coordinates})"


@dataclass(frozen=True, slots=True, kw_only=True)
class CompiledProgram:
    """A whole program: every run, in launch order, and the totals read from them."""

    contract_id: str
    spec: ProgramSpec
    runs: tuple[ProgramRun, ...]
    digest: str

    def __repr__(self) -> str:
        """Counts only. **Never the digest.**"""
        return (
            f"CompiledProgram(runs={len(self.runs)}, "
            f"data_coordinates={self.total_data_coordinates}, "
            f"expected_writes={self.total_expected_writes})"
        )

    @property
    def run_count(self) -> int:
        """How many runs the program contains."""
        return len(self.runs)

    @property
    def total_data_coordinates(self) -> int:
        """Every run's data coordinates, summed."""
        return sum(run.data_coordinates for run in self.runs)

    @property
    def total_max_provider_calls(self) -> int:
        """Every run's worst-case provider calls, summed."""
        return sum(run.max_provider_calls for run in self.runs)

    @property
    def total_expected_writes(self) -> int:
        """Every run's conditional writes, summed."""
        return sum(run.expected_writes for run in self.runs)

    @property
    def max_provider_calls_per_run(self) -> int:
        """The largest worst-case call count of any run."""
        return max(run.max_provider_calls for run in self.runs)

    def document(self) -> dict[str, Any]:
        """The closed program document: counts and coordinates, never a digest of a run."""
        return {
            "contract_id": self.contract_id,
            "window": f"{self.spec.window_start.isoformat()}/{self.spec.window_end.isoformat()}",
            "acquisition_mode": self.spec.acquisition_mode.value,
            "run_count": self.run_count,
            "total_data_coordinates": self.total_data_coordinates,
            "total_max_provider_calls": self.total_max_provider_calls,
            "total_expected_writes": self.total_expected_writes,
            "max_provider_calls_per_run": self.max_provider_calls_per_run,
            "runs": [
                {
                    "ordinal": run.ordinal,
                    "slice": run.slice.canonical(),
                    "plan_digest": run.plan.digest,
                    "data_coordinates": run.data_coordinates,
                    "max_provider_calls": run.max_provider_calls,
                    "expected_writes": run.expected_writes,
                }
                for run in self.runs
            ],
        }


def _window(start: date, end: date) -> str:
    return f"{start.isoformat()}/{end.isoformat()}"


def _slice(*, mode: AcquisitionMode, windows: dict[str, str], count: int, ceiling: int) -> Slice:
    document = {
        "acquisition_mode": mode.value,
        "datasets": sorted(windows),
        "windows": windows,
        "request_count": count,
        "max_response_bytes": ceiling,
    }
    try:
        return parse_slice(document)
    except Exception:
        raise ProgramPlanError() from None


def _compile(ordinal: int, covered: Slice, mode: AcquisitionMode) -> ProgramRun:
    try:
        plan = compile_plan(covered, acquisition_mode=mode)
    except ProductionPlanError:
        raise ProgramPlanError() from None
    if plan.max_provider_calls > MAX_PROVIDER_CALLS_PER_RUN:
        raise ProgramPlanError() from None
    return ProgramRun(ordinal=ordinal, slice=covered, plan=plan)


def _actions_coordinates(window: str) -> int:
    """How many canonical actions windows one slice window compiles into."""
    try:
        return len(canonical_windows(SharadarDataset.ACTIONS.value, window))
    except ProductionPlanError:
        raise ProgramPlanError() from None


def compile_program(spec: ProgramSpec) -> CompiledProgram:
    """Compile every run of the program ``spec`` describes. **Deterministic; nothing is fetched.**

    Raises:
        ProgramPlanError: for a specification whose runs cannot each be compiled within
            the accepted ceilings, or whose coverage would not partition the window.
    """
    if type(spec) is not ProgramSpec:
        raise ProgramPlanError() from None
    mode, ceiling = spec.acquisition_mode, spec.max_response_bytes
    tickers, stocks, actions = (
        SharadarDataset.TICKERS.value,
        SharadarDataset.STOCKS.value,
        SharadarDataset.ACTIONS.value,
    )
    runs: list[ProgramRun] = []
    # Run 1' (the replacement of historical run 1): its own stocks and actions coverage.
    first_stocks_days = (spec.window_end - spec.first_run_stocks_start).days + 1
    first_actions_window = _window(spec.first_run_actions_start, spec.window_end)
    first_actions = _actions_coordinates(first_actions_window)
    first_count = first_stocks_days + 1 + first_actions
    runs.append(
        _compile(
            0,
            _slice(
                mode=mode,
                windows={
                    actions: first_actions_window,
                    stocks: _window(spec.first_run_stocks_start, spec.window_end),
                    tickers: SNAPSHOT_WINDOW,
                },
                count=first_count,
                ceiling=ceiling,
            ),
            mode,
        )
    )
    # The residual actions coverage, before the first run's, carried by the final run.
    residual_actions: str | None = None
    residual_actions_count = 0
    if spec.first_run_actions_start > spec.window_start:
        residual_actions = _window(
            spec.window_start, spec.first_run_actions_start - timedelta(days=1)
        )
        residual_actions_count = _actions_coordinates(residual_actions)
    # The remaining stocks days, walked backwards from the day before run 1' starts.
    remaining_end = spec.first_run_stocks_start - timedelta(days=1)
    remaining_days = (
        (remaining_end - spec.window_start).days + 1 if remaining_end >= (spec.window_start) else 0
    )
    while remaining_days > 0 or residual_actions is not None:
        capacity = MAX_STOCKS_SESSIONS_PER_RUN
        last = remaining_days <= capacity - residual_actions_count
        take = min(remaining_days, capacity - residual_actions_count if last else capacity)
        windows: dict[str, str] = {tickers: SNAPSHOT_WINDOW}
        count = 1
        if take > 0:
            start = remaining_end - timedelta(days=take - 1)
            windows[stocks] = _window(start, remaining_end)
            count += take
            remaining_end = start - timedelta(days=1)
            remaining_days -= take
        if last and residual_actions is not None:
            windows[actions] = residual_actions
            count += residual_actions_count
            residual_actions = None
        runs.append(
            _compile(
                len(runs), _slice(mode=mode, windows=windows, count=count, ceiling=ceiling), mode
            )
        )
    program = CompiledProgram(
        contract_id=PROGRAM_CONTRACT_ID,
        spec=spec,
        runs=tuple(runs),
        digest=sha256_hex(
            canonical_bytes(
                {
                    "contract_id": PROGRAM_CONTRACT_ID,
                    "window": _window(spec.window_start, spec.window_end),
                    "acquisition_mode": mode.value,
                    "runs": [
                        {"slice": run.slice.canonical(), "plan_digest": run.plan.digest}
                        for run in runs
                    ],
                }
            )
        ),
    )
    verify_program(program)
    return program


def verify_program(program: CompiledProgram) -> None:
    """Every structural invariant of a program, re-derived from its compiled plans.

    Raises:
        ProgramPlanError: on any gap, overlap, missing snapshot, ceiling breach or
            digest disagreement.
    """
    if type(program) is not CompiledProgram or not program.runs:
        raise ProgramPlanError() from None
    spec = program.spec
    stocks_days: list[date] = []
    actions_windows: list[tuple[date, date]] = []
    for expected, run in enumerate(program.runs):
        if run.ordinal != expected:
            raise ProgramPlanError() from None
        if (
            run.plan.digest
            != compile_plan(run.slice, acquisition_mode=spec.acquisition_mode).digest
        ):
            raise ProgramPlanError() from None
        if run.max_provider_calls > MAX_PROVIDER_CALLS_PER_RUN:
            raise ProgramPlanError() from None
        if run.data_coordinates > MAX_DATA_COORDINATES_PER_RUN:
            raise ProgramPlanError() from None
        snapshots = 0
        for request in run.plan.requests:
            if request.page_offset != 0:
                raise ProgramPlanError() from None
            if request.dataset == SharadarDataset.TICKERS.value:
                snapshots += 1
            elif request.dataset == SharadarDataset.STOCKS.value:
                start_text, end_text = request.window.split("/")
                if start_text != end_text:
                    raise ProgramPlanError() from None
                stocks_days.append(date.fromisoformat(start_text))
            else:
                start_text, end_text = request.window.split("/")
                actions_windows.append(
                    (date.fromisoformat(start_text), date.fromisoformat(end_text))
                )
        if snapshots != 1:
            raise ProgramPlanError() from None
    total_days = (spec.window_end - spec.window_start).days + 1
    if len(stocks_days) != total_days or len(set(stocks_days)) != total_days:
        raise ProgramPlanError() from None
    if min(stocks_days) != spec.window_start or max(stocks_days) != spec.window_end:
        raise ProgramPlanError() from None
    ordered = sorted(actions_windows)
    if not ordered or ordered[0][0] != spec.window_start or ordered[-1][1] != spec.window_end:
        raise ProgramPlanError() from None
    for (_, previous_end), (next_start, _) in pairwise(ordered):
        if next_start != previous_end + timedelta(days=1):
            raise ProgramPlanError() from None


__all__ = [
    "MAX_STOCKS_SESSIONS_PER_RUN",
    "PROGRAM_CONTRACT_ID",
    "CompiledProgram",
    "ProgramPlanError",
    "ProgramRun",
    "ProgramSpec",
    "compile_program",
    "verify_program",
]
