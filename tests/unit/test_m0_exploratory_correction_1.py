"""PR #112 review correction 1 -- targeted regressions, written before the correction.

Each test names the finding it reproduces. Synthetic fixtures only; every assertion is about
software behaviour, never a strategy result. The findings came from source review; these are
the executed reproductions, run first against the reviewed head ``ce1f793b`` to establish
which fail there (recorded in the ADR-0051 §10 table), then against the correction.
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Final

import pytest

from fixtures import m0_exploratory as fx
from kalpamani.data.exploratory import m0
from kalpamani.data.exploratory.contracts import ExploratoryInputSet
from kalpamani.data.exploratory.dataset import (
    BenchmarkPoint,
    BenchmarkSeries,
    ExploratoryDataset,
    publish,
)
from kalpamani.data.exploratory.m0 import (
    M0_RESEARCH_SPECIFICATION,
    M0_SYNTHETIC_FIXTURE,
    ConfigurationProvenance,
    DataKind,
    ExitReason,
    M0Configuration,
    M0Result,
    M0RunError,
    RunRefusal,
    Skip,
    TerminalPolicy,
    Window,
    run_m0,
)
from kalpamani.data.exploratory.vocabulary import ExploratoryLimitation
from kalpamani.strategies.breakout import long as breakout_long

LIMITATIONS: Final = frozenset(ExploratoryLimitation)
CENT: Final = Decimal("0.01")


def run(dataset: ExploratoryDataset, tag: str, config: M0Configuration | None = None) -> M0Result:
    inputs = ExploratoryInputSet(
        publications=(
            publish(dataset, publication_id=f"synthetic-c1-{tag}", limitations=LIMITATIONS),
        )
    )
    return run_m0(
        specification=M0_RESEARCH_SPECIFICATION,
        inputs=inputs,
        dataset=dataset,
        config=config or M0_SYNTHETIC_FIXTURE,
        data_kind=DataKind.SYNTHETIC,
    )


def ledger(result: M0Result, policy: TerminalPolicy = TerminalPolicy.OPTIMISTIC) -> m0.Ledger:
    return next(item for item in result.ledgers if item.policy is policy)


def trades_of(
    result: M0Result, symbol: str, policy: TerminalPolicy = TerminalPolicy.OPTIMISTIC
) -> list[m0.Trade]:
    sid = fx.security_id(symbol)
    return [t for t in ledger(result, policy).trades if t.security_id == sid]


def raw_close(dataset: ExploratoryDataset, symbol: str, session: date) -> Decimal:
    """The unadjusted close straight from the Silver rows -- independent of the reader."""
    sid = fx.security_id(symbol)
    for item in dataset.layer.stocks:
        if item.row.security_id == sid and item.row.fields.get("date") == session.isoformat():
            return Decimal(str(item.row.fields["closeunadj"]))
    raise KeyError((symbol, session))


@pytest.fixture(scope="module")
def calendar() -> Any:
    return fx.calendar()


@pytest.fixture(scope="module")
def phases(calendar: Any) -> dict[str, tuple[date, ...]]:
    return fx.phases_of(calendar)


@pytest.fixture(scope="module")
def base(calendar: Any) -> ExploratoryDataset:
    return fx.dataset(calendar)


@pytest.fixture(scope="module")
def base_result(base: ExploratoryDataset) -> M0Result:
    return run(base, "base")


# --- finding 1: consistent split handling ----------------------------------------------------


def test_f1_a_split_after_a_completed_trade_cannot_change_that_trade(
    calendar: Any,
    phases: dict[str, tuple[date, ...]],
    base: ExploratoryDataset,
    base_result: M0Result,
) -> None:
    before = trades_of(base_result, "ZZAA")
    assert len(before) == 1 and before[0].exit_reason is ExitReason.TIME
    ex = phases["development"][70]  # well after the time exit at development[26]
    assert before[0].exit_session is not None and ex > before[0].exit_session
    variant = fx.dataset_from(
        fx.with_split(fx.silver_layer(calendar), "ZZAA", ex, Decimal(2)), calendar
    )
    after = trades_of(run(variant, "split-after"), "ZZAA")
    assert after == before  # every recorded figure, fills and participation included
    assert not [
        s
        for s in ledger(run(variant, "split-after-2")).skips
        if s.security_id == fx.security_id("ZZAA")
    ]


def test_f1_a_split_between_signal_and_execution_creates_no_gap_and_a_compatible_stop(
    calendar: Any, base_result: M0Result
) -> None:
    before = trades_of(base_result, "ZZAA")[0]
    ex = before.entry_session  # the split is effective at the executing open
    variant = fx.dataset_from(
        fx.with_split(fx.silver_layer(calendar), "ZZAA", ex, Decimal(2)), calendar
    )
    result = run(variant, "split-at-entry")
    skips = [s for s in ledger(result).skips if s.security_id == fx.security_id("ZZAA")]
    assert not skips, skips
    after = trades_of(result, "ZZAA")
    assert len(after) == 1
    t = after[0]
    assert t.entry_session == before.entry_session and t.exit_session == before.exit_session
    assert t.stop_level == (before.stop_level / 2).quantize(Decimal("0.000001"))
    assert t.entry_open == (before.entry_open / 2).quantize(Decimal("0.0001"))
    assert abs(t.shares - before.shares * 2) <= 1
    # Whole-share rounding at half the price may add or drop one share: within one share's
    # risk and one share's price, the sizing is the same economic position.
    assert abs(t.planned_risk - before.planned_risk) <= (t.entry_fill - t.stop_level) + Decimal(
        "0.10"
    )
    assert abs(
        t.entry_fill * t.shares - before.entry_fill * before.shares
    ) <= t.entry_fill + Decimal("0.10")
    # One whole share of rounding at half the price moves participation by a hair.
    assert abs(t.entry_participation_pct - before.entry_participation_pct) <= Decimal("0.001")


@pytest.mark.parametrize("ratio", [Decimal(2), Decimal("1.5")])
def test_f1_a_split_during_a_holding_preserves_value_and_records_the_fractional_policy(
    calendar: Any,
    phases: dict[str, tuple[date, ...]],
    base: ExploratoryDataset,
    base_result: M0Result,
    ratio: Decimal,
) -> None:
    before = trades_of(base_result, "ZZAA")[0]
    sessions = [s.session_date for s in calendar.sessions]
    ex = sessions[sessions.index(before.entry_session) + 6]
    variant = fx.dataset_from(fx.with_split(fx.silver_layer(calendar), "ZZAA", ex, ratio), calendar)
    result = run(variant, f"split-mid-{ratio}")
    t = trades_of(result, "ZZAA")[0]
    assert t.entry_session == before.entry_session and t.exit_session == before.exit_session
    assert t.exit_reason is ExitReason.TIME and t.shares == before.shares  # entry facts unchanged
    events = t.split_events
    assert len(events) == 1 and events[0].ex_date == ex and events[0].ratio == ratio
    whole = int((Decimal(before.shares) * ratio).to_integral_value(rounding="ROUND_DOWN"))
    assert events[0].shares_before == before.shares and events[0].shares_after == whole
    fraction = Decimal(before.shares) * ratio - whole
    close_ex = raw_close(variant, "ZZAA", ex)
    assert events[0].cash_in_lieu == (fraction * close_ex).quantize(CENT)
    assert t.exit_shares == whole and t.cash_in_lieu == events[0].cash_in_lieu
    # Economic value on the ex-session: the position plus any cash in lieu equals what the
    # unsplit position was worth at the same session (the split moved no market).
    opt_base = ledger(base_result)
    opt = ledger(result)
    point_base = next(e for e in opt_base.equity if e.session == ex)
    point = next(e for e in opt.equity if e.session == ex)
    assert abs(
        (point.positions_value + point.cash) - (point_base.positions_value + point_base.cash)
    ) <= Decimal("0.10")
    # Marks while held equal the unsplit run's, except that the fractional share settled in
    # cash on the ex-session no longer moves with the market afterwards.
    assert before.exit_session is not None
    for session in sessions[sessions.index(ex) : sessions.index(before.exit_session)]:
        a = next(e for e in opt_base.equity if e.session == session)
        b = next(e for e in opt.equity if e.session == session)
        forgone = fraction * (raw_close(variant, "ZZAA", session) - close_ex)
        assert abs((a.equity - b.equity) - forgone) <= Decimal("0.10"), session
    # The realized result differs only by the exit commission on the changed share count, the
    # fractional share's forgone move, and the cents of quantization -- never by the split.
    assert (
        before.realized_pnl is not None and t.realized_pnl is not None and t.exit_fill is not None
    )
    forgone_at_exit = fraction * (t.exit_fill - close_ex)
    before_exit_commission = before.realized_pnl + before.exit_commission
    split_before_exit_commission = t.realized_pnl + t.exit_commission
    assert abs(before_exit_commission - split_before_exit_commission - forgone_at_exit) <= Decimal(
        "0.10"
    )
    assert t.stop_level == (before.stop_level / ratio).quantize(Decimal("0.000001"))


def test_f1_split_adjusted_volume_preserves_addv(base: ExploratoryDataset) -> None:
    sid = fx.security_id("ZZCC")
    sessions = [s.session_date for s in base.calendar.sessions]
    i = sessions.index(fx.SPLIT_EX)
    window_end = sessions[i - 1]
    as_of_before = base.bars_through(sid, window_end, count=20)
    as_of_after = base.bars_through(sid, sessions[i + 25])
    same_window = tuple(
        b for b in as_of_after if as_of_before[0].session_date <= b.session_date <= window_end
    )
    assert len(same_window) == 20
    assert m0._addv(as_of_before, 20) == m0._addv(same_window, 20)
    raw = (
        sum(
            (raw_close(base, "ZZCC", b.session_date) * Decimal(50_000) for b in as_of_before),
            Decimal(0),
        )
        / 20
    )
    assert m0._addv(as_of_before, 20) == raw


# --- finding 2: no entries during purge or tail ----------------------------------------------


def test_f2_signals_on_the_last_evaluation_sessions_open_no_position(
    phases: dict[str, tuple[date, ...]], base_result: M0Result
) -> None:
    purge_and_tail = set(phases["purge"]) | set(phases["tail"])
    for policy in TerminalPolicy:
        item = ledger(base_result, policy)
        assert trades_of(base_result, "ZZPP", policy) == []
        assert not [t for t in item.trades if t.entry_session in purge_and_tail]
        assert not [s for s in item.skips if s.session in purge_and_tail]
    for item in (*base_result.baselines, *base_result.sensitivities):
        assert not [t for t in item.trades if t.entry_session in purge_and_tail], item.label


def test_f2_positions_exit_in_purge_or_tail_attributed_to_the_originating_window(
    phases: dict[str, tuple[date, ...]], base_result: M0Result
) -> None:
    qq = trades_of(base_result, "ZZQQ")
    assert [t.window for t in qq] == [Window.DEVELOPMENT, Window.VALIDATION]
    assert qq[0].exit_session in phases["purge"] and qq[1].exit_session in phases["tail"]
    assert all(t.exit_reason is ExitReason.TIME for t in qq)
    dev, val = ledger(base_result).metrics
    assert dev.window is Window.DEVELOPMENT and val.window is Window.VALIDATION
    assert qq[0].realized_pnl is not None and qq[1].realized_pnl is not None
    # Their P&L is counted in the originating window's realized figures.
    dev_pnl = sum(
        (
            t.realized_pnl
            for t in ledger(base_result).trades
            if t.window is Window.DEVELOPMENT and t.realized_pnl is not None
        ),
        Decimal(0),
    )
    assert dev.net_pnl == dev_pnl.quantize(CENT)


# --- finding 3: no same-session re-entry -------------------------------------------------------


def test_f3_no_same_session_re_entry_after_any_exit(base_result: M0Result) -> None:
    for item in (*base_result.ledgers, *base_result.baselines, *base_result.sensitivities):
        exits: dict[str, set[date]] = {}
        for t in item.trades:
            if t.exit_session is not None and t.exit_reason is not ExitReason.OPEN_AT_END:
                exits.setdefault(t.security_id, set()).add(t.exit_session)
        for t in item.trades:
            assert t.entry_session not in exits.get(t.security_id, set()), (
                item.label,
                t.security_id,
                t.entry_session,
            )


def test_f3_the_collision_is_recorded_and_ordinary_re_entry_remains_possible(
    phases: dict[str, tuple[date, ...]], base_result: M0Result
) -> None:
    rr = trades_of(base_result, "ZZRR")
    assert len(rr) == 2
    first, second = rr
    assert first.exit_reason is ExitReason.TIME and first.exit_session is not None
    collision = [
        s
        for s in ledger(base_result).skips
        if s.security_id == fx.security_id("ZZRR") and s.session == first.exit_session
    ]
    assert [s.reason for s in collision] == [Skip.SKIPPED_EXITED_THIS_SESSION]
    assert second.entry_session > first.exit_session
    sessions = list(phases["development"])
    assert second.entry_session == sessions[5 + 1 + 81]  # the later breakout's next open


# --- finding 4: validated configuration and complete trial binding ---------------------------


@pytest.mark.parametrize(
    "field, value",
    [
        ("capital", 80000.0),
        ("capital", 80000),
        ("capital", "80000"),
        ("capital", Decimal("NaN")),
        ("capital", Decimal("Infinity")),
        ("capital", Decimal(0)),
        ("risk_per_trade", Decimal("-1")),
        ("time_exit_held_sessions", True),
        ("time_exit_held_sessions", 0),
        ("time_exit_held_sessions", 20.0),
        ("warm_up_sessions", 100),
        ("development_sessions", 0),
        ("addv_sessions", 0),
        ("entry_gap_max", Decimal("-0.1")),
        ("cost_multiplier", Decimal("-1")),
        ("spread_bps_round_trip", Decimal("NaN")),
        ("benchmark_option", "B"),
    ],
)
def test_f4_malformed_or_out_of_range_settings_are_refused(field: str, value: object) -> None:
    with pytest.raises(M0RunError) as caught:
        M0Configuration(provenance=ConfigurationProvenance.SYNTHETIC_FIXTURE, **{field: value})  # type: ignore[arg-type]
    assert caught.value.refusal is RunRefusal.REFUSED_INVALID_CONFIGURATION


@pytest.mark.parametrize(
    "overrides",
    [
        {"position_cap": Decimal("100000.00")},  # a position larger than the capital
        {"open_risk_cap": Decimal("300.00")},  # less than one trade's risk
        {"participation_free_pct": Decimal("6"), "capacity_flag_pct": Decimal("5")},
    ],
)
def test_f4_contradictory_settings_are_refused(overrides: dict[str, Any]) -> None:
    with pytest.raises(M0RunError) as caught:
        M0Configuration(provenance=ConfigurationProvenance.SYNTHETIC_FIXTURE, **overrides)
    assert caught.value.refusal is RunRefusal.REFUSED_INVALID_CONFIGURATION


def _selections(**overrides: Any) -> Any:
    from kalpamani.data.exploratory.m0 import (
        Acknowledgment,
        AcquisitionRouteChoice,
        BenchmarkChoice,
        ComputeLocationChoice,
        CostModelChoice,
        EventHandlingChoice,
        ExitRuleChoice,
        ExploratoryModeChoice,
        OwnerSelections,
        SizingSequencingChoice,
        TerminalAccountingChoice,
    )

    values: dict[str, Any] = {
        "o1_exploratory_mode": ExploratoryModeChoice.ENABLED,
        "o2_benchmark": BenchmarkChoice.A_EW_UNIVERSE,
        "o3_exit_rule": ExitRuleChoice.CLOSE_BELOW_BASE_LOW_NEXT_OPEN,
        "o4_cost_model": CostModelChoice.M0_SECTION_14,
        "o5_acquisition_route": AcquisitionRouteChoice.BOUNDED_RUNS,
        "o6_compute_location": ComputeLocationChoice.PRIVATE_AWS,
        "o7_event_handling": EventHandlingChoice.EVENT_BLIND,
        "o8_data_window_start": date(2024, 6, 3),
        "o8_data_window_end": date(2026, 9, 14),
        "o9_terminal_accounting": TerminalAccountingChoice.TWO_LEDGERS,
        "o10_sizing_and_sequencing": SizingSequencingChoice.CLAUDE_S6_FINAL_FILL_REJECTION,
        "o11_no_untouched_window": Acknowledgment.ACKNOWLEDGED,
    }
    values.update(overrides)
    return OwnerSelections(**values)


def test_f4_owner_selections_are_typed_complete_and_immutable() -> None:
    from kalpamani.data.exploratory.m0 import ExploratoryModeChoice

    selections = _selections()
    config = M0Configuration(
        provenance=ConfigurationProvenance.OWNER_SELECTED, owner_selections=selections
    )
    assert config.owner_selections is not None and config.owner_selections is selections
    with pytest.raises(dataclasses.FrozenInstanceError):
        selections.o1_exploratory_mode = ExploratoryModeChoice.DECLINED  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.owner_selections = None  # type: ignore[misc]
    document = config.document()["owner_selections"]
    assert set(document) == {f"O-{n}" for n in range(1, 12)}
    # Free text, a mapping and a lookalike are not selections.
    for bad in ({k: "recorded" for k in m0.OWNER_DECISIONS}, "all selected", object()):
        with pytest.raises(M0RunError) as caught:
            M0Configuration(provenance=ConfigurationProvenance.OWNER_SELECTED, owner_selections=bad)  # type: ignore[arg-type]
        assert caught.value.refusal is RunRefusal.REFUSED_INVALID_CONFIGURATION
    with pytest.raises(M0RunError) as caught:
        M0Configuration(provenance=ConfigurationProvenance.OWNER_SELECTED, owner_selections=None)
    assert caught.value.refusal is RunRefusal.REFUSED_UNSELECTED_CONFIGURATION
    # The synthetic fixture never carries owner selections: engineering inputs are not decisions.
    with pytest.raises(M0RunError) as caught:
        M0Configuration(
            provenance=ConfigurationProvenance.SYNTHETIC_FIXTURE, owner_selections=selections
        )
    assert caught.value.refusal is RunRefusal.REFUSED_INVALID_CONFIGURATION
    assert M0_SYNTHETIC_FIXTURE.owner_selections is None


def test_f4_unsupported_and_contradictory_selections_are_refused() -> None:
    from kalpamani.data.exploratory.m0 import (
        Acknowledgment,
        BenchmarkChoice,
        ExploratoryModeChoice,
        SizingSequencingChoice,
    )

    with pytest.raises(M0RunError) as caught:
        _selections(o1_exploratory_mode=ExploratoryModeChoice.DECLINED)
    assert caught.value.refusal is RunRefusal.REFUSED_CONTRADICTORY_SELECTION
    with pytest.raises(M0RunError) as caught:
        _selections(o2_benchmark=BenchmarkChoice.B_FUND_SERIES)
    assert caught.value.refusal is RunRefusal.REFUSED_UNSUPPORTED_SELECTION
    with pytest.raises(M0RunError) as caught:
        _selections(
            o10_sizing_and_sequencing=SizingSequencingChoice.CLAUDE_S6_ONE_RESIZING_ITERATION
        )
    assert caught.value.refusal is RunRefusal.REFUSED_UNSUPPORTED_SELECTION
    with pytest.raises(M0RunError) as caught:
        _selections(o11_no_untouched_window=Acknowledgment.NOT_ACKNOWLEDGED)
    assert caught.value.refusal is RunRefusal.REFUSED_CONTRADICTORY_SELECTION
    with pytest.raises(M0RunError) as caught:
        _selections(o8_data_window_start=date(2026, 9, 15))  # after the end
    assert caught.value.refusal is RunRefusal.REFUSED_CONTRADICTORY_SELECTION
    with pytest.raises(M0RunError) as caught:
        _selections(o1_exploratory_mode="ENABLED")  # by name is not a choice
    assert caught.value.refusal is RunRefusal.REFUSED_INVALID_CONFIGURATION


def test_f4_a_selected_window_must_cover_the_calendar_and_real_data_stays_unexecuted(
    base: ExploratoryDataset,
) -> None:
    """The run-time consistency check between selections and the dataset, exercised on the
    refusal path only: no real-data invocation is authorized, and none is made here."""
    narrow = M0Configuration(
        provenance=ConfigurationProvenance.OWNER_SELECTED,
        owner_selections=_selections(o8_data_window_start=date(2025, 1, 1)),
    )
    inputs = ExploratoryInputSet(
        publications=(publish(base, publication_id="synthetic-c1-window", limitations=LIMITATIONS),)
    )
    with pytest.raises(M0RunError) as caught:
        run_m0(
            specification=M0_RESEARCH_SPECIFICATION,
            inputs=inputs,
            dataset=base,
            config=narrow,
            data_kind=DataKind.REAL,
        )
    assert caught.value.refusal is RunRefusal.REFUSED_SELECTION_INCONSISTENT


def test_f4_a_malformed_data_kind_cannot_bypass_the_real_data_check(
    base: ExploratoryDataset,
) -> None:
    inputs = ExploratoryInputSet(
        publications=(publish(base, publication_id="synthetic-c1-kind", limitations=LIMITATIONS),)
    )
    for bad in ("REAL", "SYNTHETIC", None, 1):
        with pytest.raises(M0RunError) as caught:
            run_m0(
                specification=M0_RESEARCH_SPECIFICATION,
                inputs=inputs,
                dataset=base,
                config=M0_SYNTHETIC_FIXTURE,
                data_kind=bad,  # type: ignore[arg-type]
            )
        assert caught.value.refusal is RunRefusal.REFUSED_MALFORMED_DATA_KIND, bad


def test_f4_the_history_requirement_is_the_accepted_modules_and_not_an_override(
    base: ExploratoryDataset,
) -> None:
    assert m0.HISTORY_SESSIONS == 252
    assert m0.HISTORY_SESSIONS == breakout_long.build_spec().data.required_history_sessions
    inputs = ExploratoryInputSet(
        publications=(
            publish(base, publication_id="synthetic-c1-history", limitations=LIMITATIONS),
        )
    )
    with pytest.raises(TypeError):
        run_m0(
            specification=M0_RESEARCH_SPECIFICATION,
            inputs=inputs,
            dataset=base,
            config=M0_SYNTHETIC_FIXTURE,
            data_kind=DataKind.SYNTHETIC,
            history_sessions=10,  # type: ignore[call-arg]
        )


def test_f4_the_trial_digest_binds_strategy_identity_calendar_content_and_every_setting(
    base: ExploratoryDataset, base_result: M0Result
) -> None:
    sessions = tuple(s.session_date for s in base.calendar.sessions)
    phases = m0.phases_for(sessions, M0_SYNTHETIC_FIXTURE)
    document = m0.trial_document(M0_RESEARCH_SPECIFICATION, M0_SYNTHETIC_FIXTURE, base, phases)
    spec = breakout_long.build_spec()
    assert document["strategy"] == {
        "strategy_id": spec.strategy_id,
        "version": spec.version,
        "parameters_hash": spec.parameters_hash,
        "required_history_sessions": 252,
    }
    assert document["history_sessions"] == 252
    assert "calendar_digest" in document and document["calendar_version"] == base.calendar.version
    assert base_result.trial_digest == m0.trial_digest(
        M0_RESEARCH_SPECIFICATION, M0_SYNTHETIC_FIXTURE, base, phases
    )
    # The same calendar version with different content is a different trial.
    last = base.calendar.sessions[-1]
    moved = replace(
        base.calendar,
        sessions=(
            *base.calendar.sessions[:-1],
            replace(
                last,
                session_date=last.session_date + timedelta(days=1),
                open_at=last.open_at + timedelta(days=1),
            ),
        ),
    )
    other = replace(base, calendar=moved, cache={})
    assert (
        m0.trial_digest(M0_RESEARCH_SPECIFICATION, M0_SYNTHETIC_FIXTURE, other, phases)
        != base_result.trial_digest
    )
    # Every execution-affecting setting moves the digest.
    for field, value in (
        ("time_exit_held_sessions", 19),
        ("entry_gap_max", Decimal("0.09")),
        ("purge_sessions", 31),
        ("baseline_stop_sessions", 21),
        ("slippage_base_bps", Decimal(11)),
    ):
        overrides: dict[str, Any] = {field: value}
        cfg = M0Configuration(provenance=ConfigurationProvenance.SYNTHETIC_FIXTURE, **overrides)
        assert (
            m0.trial_digest(M0_RESEARCH_SPECIFICATION, cfg, base, m0.phases_for(sessions, cfg))
            != base_result.trial_digest
        ), field


# --- finding 5: comparable benchmark periods and terminal policies ---------------------------


def _level(dataset: ExploratoryDataset, session: date, *, total_loss: bool = False) -> Decimal:
    point = next(p for p in dataset.benchmark.points if p.session_date == session)
    return point.level_total_loss if total_loss else point.level


def test_f5_evaluation_period_comparisons_share_identical_instants(
    base: ExploratoryDataset, phases: dict[str, tuple[date, ...]], base_result: M0Result
) -> None:
    sessions = [s.session_date for s in base.calendar.sessions]
    for policy in TerminalPolicy:
        item = ledger(base_result, policy)
        for metrics, name in zip(item.metrics, ("development", "validation"), strict=True):
            block = phases[name]
            assert metrics.evaluation_start == block[0] and metrics.evaluation_end == block[-1]
            start_close = sessions[
                sessions.index(block[0]) - 1
            ]  # the first session's return counts
            expected = (
                _level(base, block[-1], total_loss=policy is TerminalPolicy.TOTAL_LOSS)
                / _level(base, start_close, total_loss=policy is TerminalPolicy.TOTAL_LOSS)
                - 1
            ).quantize(Decimal("0.0001"))
            assert metrics.benchmark_return_fraction == expected
            end_point = next(e for e in item.equity if e.session == block[-1])
            assert metrics.end_equity == end_point.equity
            assert metrics.return_fraction == (
                (end_point.equity - M0_SYNTHETIC_FIXTURE.capital) / M0_SYNTHETIC_FIXTURE.capital
            ).quantize(Decimal("0.0001"))


def test_f5_liquidation_tail_outcomes_are_labelled_with_equal_benchmark_coverage(
    base: ExploratoryDataset, phases: dict[str, tuple[date, ...]], base_result: M0Result
) -> None:
    sessions = [s.session_date for s in base.calendar.sessions]
    item = ledger(base_result)
    for metrics, name, after in zip(
        item.metrics, ("development", "validation"), ("purge", "tail"), strict=True
    ):
        block = phases[name]
        assert metrics.liquidation_end == phases[after][-1]
        start_close = sessions[sessions.index(block[0]) - 1]
        expected = (_level(base, phases[after][-1]) / _level(base, start_close) - 1).quantize(
            Decimal("0.0001")
        )
        assert metrics.liquidation_benchmark_return_fraction == expected
        end_point = next(e for e in item.equity if e.session == phases[after][-1])
        assert metrics.liquidation_end_equity == end_point.equity
        assert metrics.max_drawdown <= metrics.max_drawdown_through_liquidation


def test_f5_each_terminal_policy_uses_its_own_benchmark_series(base_result: M0Result) -> None:
    opt = ledger(base_result, TerminalPolicy.OPTIMISTIC).metrics[0]
    loss = ledger(base_result, TerminalPolicy.TOTAL_LOSS).metrics[0]
    assert opt.benchmark_return_fraction is not None and loss.benchmark_return_fraction is not None
    # ZZCC's missing bars fall in development: the total-loss series is strictly lower.
    assert loss.benchmark_return_fraction < opt.benchmark_return_fraction
    assert (
        base_result.equal_weight_hold["DEVELOPMENT"]["return_fraction_total_loss"]
        != base_result.equal_weight_hold["DEVELOPMENT"]["return_fraction"]
    )


def test_f5_a_zero_benchmark_level_yields_no_return_and_no_division_error(
    base: ExploratoryDataset, phases: dict[str, tuple[date, ...]]
) -> None:
    # The total-loss series is what a total-loss ledger compares against, and it is not read
    # by any signal -- so zeroing it exercises the division guard without touching signals.
    sessions = [s.session_date for s in base.calendar.sessions]
    zeroed = {sessions[sessions.index(phases["development"][0]) - 1], phases["development"][0]}
    points = tuple(
        BenchmarkPoint(
            session_date=p.session_date,
            level=p.level,
            level_total_loss=Decimal(0) if p.session_date in zeroed else p.level_total_loss,
            members=p.members,
            missing_bars=p.missing_bars,
        )
        for p in base.benchmark.points
    )
    variant = replace(
        base,
        benchmark=BenchmarkSeries(
            benchmark_id=base.benchmark.benchmark_id, version=base.benchmark.version, points=points
        ),
        cache={},
    )
    result = run(variant, "zero-benchmark")
    loss_dev, loss_val = ledger(result, TerminalPolicy.TOTAL_LOSS).metrics
    assert loss_dev.benchmark_return_fraction is None
    assert loss_dev.liquidation_benchmark_return_fraction is None
    assert loss_val.benchmark_return_fraction is not None
    opt_dev = ledger(result, TerminalPolicy.OPTIMISTIC).metrics[0]
    assert opt_dev.benchmark_return_fraction is not None
    assert result.equal_weight_hold["DEVELOPMENT"]["return_fraction_total_loss"] is None
    assert result.equal_weight_hold["DEVELOPMENT"]["return_fraction"] is not None
    assert m0.ratio_return(Decimal(0), Decimal(5)) is None
    assert m0.ratio_return(None, Decimal(5)) is None
    assert m0.ratio_return(Decimal(100), Decimal(0)) == Decimal("-1.0000")


# --- finding 6: independent reconciliation with residual positions ---------------------------


def _reconcile(
    dataset: ExploratoryDataset,
    item: m0.Ledger,
    phases: dict[str, tuple[date, ...]],
    capital: Decimal,
) -> None:
    """Rebuild every figure from the journal and the raw bars; nothing is read from metrics
    until the end, when the two reconstructions must agree with them."""
    kinds = m0.TransactionKind
    for window, name, after in (
        (Window.DEVELOPMENT, "development", "purge"),
        (Window.VALIDATION, "validation", "tail"),
    ):
        block = (*phases[name], *phases[after])
        journal = [x for x in item.transactions if x.session in block]
        cash = capital + sum((x.cash_delta for x in journal), Decimal(0))
        trades = [t for t in item.trades if t.window is window]
        entries = [x for x in journal if x.kind is kinds.ENTRY]
        assert sorted((x.security_id, x.session) for x in entries) == sorted(
            (t.security_id, t.entry_session) for t in trades
        )
        closed = [t for t in trades if t.exit_reason is not ExitReason.OPEN_AT_END]
        open_at_end = [t for t in trades if t.exit_reason is ExitReason.OPEN_AT_END]
        realized = Decimal(0)
        for t in closed:
            assert t.realized_pnl is not None
            proceeds = (
                Decimal(0) if t.exit_fill is None else (t.exit_fill * t.exit_shares).quantize(CENT)
            )
            basis = (t.entry_fill * t.shares).quantize(CENT)
            assert t.realized_pnl == (
                proceeds + t.cash_in_lieu - basis - t.entry_commission - t.exit_commission
            ).quantize(CENT)
            realized += t.realized_pnl
        marked = Decimal(0)
        unrealized = Decimal(0)
        open_entry_commission = Decimal(0)
        for t in open_at_end:
            assert t.exit_fill is None and t.exit_commission == 0 and t.realized_pnl is None
            last = max(b.session_date for b in dataset.bars_through(t.security_id, block[-1]))
            mark = raw_close(
                dataset, next(s for s in fx.SYMBOLS if fx.security_id(s) == t.security_id), last
            )
            assert t.mark_price == mark and t.mark_session == last
            value = (mark * t.exit_shares).quantize(CENT)
            marked += value
            remaining_basis = (t.entry_fill * t.shares).quantize(CENT) - t.cash_in_lieu
            assert t.unrealized_pnl == (value - remaining_basis).quantize(CENT)
            unrealized += t.unrealized_pnl
            open_entry_commission += t.entry_commission
        interest = sum((x.cash_delta for x in journal if x.kind is kinds.INTEREST), Decimal(0))
        commissions = sum((t.entry_commission + t.exit_commission for t in trades), Decimal(0))
        assert commissions == sum((x.commission for x in journal), Decimal(0))
        equity = (cash + marked).quantize(CENT)
        assert equity == (
            capital + realized + unrealized - open_entry_commission + interest
        ).quantize(CENT)
        metrics = next(m for m in item.metrics if m.window is window)
        assert metrics.liquidation_end_equity == equity
        assert next(e for e in item.equity if e.session == block[-1]).equity == equity


def test_f6_every_ledger_reconciles_from_recorded_transactions_with_residual_positions(
    base: ExploratoryDataset, phases: dict[str, tuple[date, ...]], base_result: M0Result
) -> None:
    opt = ledger(base_result)
    open_at_end = [t for t in opt.trades if t.exit_reason is ExitReason.OPEN_AT_END]
    assert sorted(t.security_id for t in open_at_end) == sorted(
        fx.security_id(s) for s in ("ZZMM", "ZZNN")
    )
    assert all(t.missing_bar_sessions > 0 for t in open_at_end)
    assert opt.metrics[0].open_at_end == 1 and opt.metrics[1].open_at_end == 1
    for item in (*base_result.ledgers, *base_result.baselines, *base_result.sensitivities):
        _reconcile(base, item, phases, M0_SYNTHETIC_FIXTURE.capital)
    idle = next(item for item in base_result.sensitivities if "idle" in item.label)
    assert any(x.kind is m0.TransactionKind.INTEREST for x in idle.transactions)
    assert not any(x.kind is m0.TransactionKind.INTEREST for x in opt.transactions)


def test_f6_a_split_during_a_holding_reconciles_with_cash_in_lieu(
    calendar: Any, phases: dict[str, tuple[date, ...]], base_result: M0Result
) -> None:
    before = trades_of(base_result, "ZZAA")[0]
    sessions = [s.session_date for s in calendar.sessions]
    ex = sessions[sessions.index(before.entry_session) + 6]
    variant = fx.dataset_from(
        fx.with_split(fx.silver_layer(calendar), "ZZAA", ex, Decimal("1.5")), calendar
    )
    result = run(variant, "split-reconcile")
    item = ledger(result)
    cil = [x for x in item.transactions if x.kind is m0.TransactionKind.CASH_IN_LIEU]
    assert (
        len(cil) == 1
        and cil[0].session == ex
        and cil[0].cash_delta == trades_of(result, "ZZAA")[0].cash_in_lieu > 0
    )
    _reconcile(variant, item, phases, M0_SYNTHETIC_FIXTURE.capital)
