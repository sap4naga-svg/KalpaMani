"""The end-to-end synthetic M0 path (ADR-0051 s.9-s.10; M0 specification s.11-s.14).

Synthetic fixtures only. Every assertion is about software behaviour: the three instants,
prior-session ADDV, final-fill rejection, exit precedence and sequencing, causal terminal
recognition, the two reconciled ledgers, independent window initialization under the frozen
trial digest, benchmark membership, production refusal, determinism. Nothing here is a
strategy result.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures import m0_exploratory as fx
from kalpamani.data.contracts.vocabulary import InformationSetProfile, PublicBoundDerivation
from kalpamani.data.exploratory import m0
from kalpamani.data.exploratory.admission import AdmissionOutcome, admit
from kalpamani.data.exploratory.contracts import (
    ExploratoryInputSet,
    ExploratoryPublication,
    parse_publication,
)
from kalpamani.data.exploratory.dataset import (
    BENCHMARK_A_ID,
    ExploratoryDataset,
    build_benchmark_a,
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
    phases_for,
    run_m0,
)
from kalpamani.data.exploratory.report import render_markdown, summary, write_report
from kalpamani.data.exploratory.resolution import (
    REGULAR_SESSION,
    ExploratoryResolvedLayer,
    decide_membership,
    resolve_as_dated,
)
from kalpamani.data.exploratory.vocabulary import (
    AvailabilityBasis,
    ExploratoryDerivation,
    ExploratoryLimitation,
    ExploratoryProfile,
)
from kalpamani.data.production.sharadar import availability, universe
from kalpamani.data.production.sharadar.silver import RowVersion
from kalpamani.strategies.breakout import long as breakout_long

LIMITATIONS: Final = frozenset(ExploratoryLimitation)


@pytest.fixture(scope="module")
def dataset() -> ExploratoryDataset:
    return fx.dataset()


@pytest.fixture(scope="module")
def inputs(dataset: ExploratoryDataset) -> ExploratoryInputSet:
    return ExploratoryInputSet(
        publications=(
            publish(dataset, publication_id="synthetic-m0-pub-01", limitations=LIMITATIONS),
        )
    )


@pytest.fixture(scope="module")
def result(dataset: ExploratoryDataset, inputs: ExploratoryInputSet) -> M0Result:
    return run_m0(
        specification=M0_RESEARCH_SPECIFICATION,
        inputs=inputs,
        dataset=dataset,
        config=M0_SYNTHETIC_FIXTURE,
        data_kind=DataKind.SYNTHETIC,
    )


def ledger(result: M0Result, policy: TerminalPolicy) -> m0.Ledger:
    return next(item for item in result.ledgers if item.policy is policy)


def trades_of(
    result: M0Result, symbol: str, policy: TerminalPolicy = TerminalPolicy.OPTIMISTIC
) -> list[m0.Trade]:
    sid = fx.security_id(symbol)
    return [t for t in ledger(result, policy).trades if t.security_id == sid]


# --- AS_DATED resolution and membership -----------------------------------------------------


def test_as_dated_bounds_are_the_rows_own_dates_and_never_the_retrieval_instant(
    dataset: ExploratoryDataset,
) -> None:
    layer = dataset.layer
    calendar = dataset.calendar
    for item in layer.stocks[:50]:
        session = datetime.fromisoformat(str(item.row.fields["date"])).date()
        opened = calendar.open_at(session)
        assert opened is not None
        assert item.availability.governing_time == opened + REGULAR_SESSION
        assert item.availability.derivation is ExploratoryDerivation.AS_DATED
        assert item.availability.basis is AvailabilityBasis.ASSUMED_HISTORICAL
        assert item.availability.profile is ExploratoryProfile.EXPLORATORY_HINDSIGHT
        assert item.availability.governing_time < item.availability.system_first_seen_time
    for item in layer.tickers:
        assert item.availability.governing_time < calendar.sessions[0].open_at
    delisted = [a for a in layer.actions if a.row.fields.get("action") == "delisted"]
    assert len(delisted) == 1
    when = datetime.fromisoformat(str(delisted[0].row.fields["date"])).date()
    assert delisted[0].availability.governing_time == calendar.open_at(when)


def test_membership_reuses_the_accepted_clauses_and_the_252_session_history(
    dataset: ExploratoryDataset,
) -> None:
    phases = fx.phases_of(dataset.calendar)
    first_dev = phases["development"][0]
    rows = {r.security_id: r for r in dataset.membership.rows if r.session_date == first_dev}
    assert len(rows) == len(fx.SYMBOLS)
    assert all(r.is_member for r in rows.values())
    assert all(r.history_sessions_at_eval == 253 for r in rows.values())
    # Before enough history exists, the accepted HISTORY exclusion applies -- the 252 rule holds.
    early = dataset.calendar.sessions[100].session_date
    early_rows = [r for r in dataset.membership.rows if r.session_date == early]
    assert early_rows and all(
        r.exclusion_reason is universe.BuildExclusionReason.HISTORY for r in early_rows
    )
    assert dataset.membership.rule.history_sessions == 252
    assert dataset.membership.rule.version == universe.UNIVERSE_RULE_VERSION


def test_the_exploratory_clauses_equal_the_accepted_path_under_equal_bounds(
    dataset: ExploratoryDataset,
) -> None:
    """Conformance: with the accepted P-2 bounds made equal to the AS_DATED bounds, the accepted
    ``build_universe`` and the exploratory ``decide_membership`` decide identically."""
    calendar = dataset.calendar
    sessions = tuple(s.session_date for s in calendar.sessions)[300:340]
    layer = dataset.layer
    silver = fx.silver_layer(calendar)

    def rebound(rows: tuple[RowVersion, ...]) -> tuple[RowVersion, ...]:
        by_key = {(r.dataset, r.row_key, r.security_id): r for r in rows}
        out = []
        for item in layer.by_dataset(rows[0].dataset) if rows else ():
            row = by_key[(item.row.dataset, item.row.row_key, item.row.security_id)]
            bound = item.availability.governing_time
            out.append(
                RowVersion(
                    dataset=row.dataset,
                    row_key=row.row_key,
                    security_id=row.security_id,
                    symbol=row.symbol,
                    revision_sequence=row.revision_sequence,
                    content_sha256=row.content_sha256,
                    fields=row.fields,
                    provenance=row.provenance,
                    system_first_seen_time=bound,
                    content_first_seen_time=bound,
                    observed_at=(bound,),
                    redelivery_gaps=row.redelivery_gaps,
                )
            )
        return tuple(out)

    from dataclasses import replace

    equal = replace(
        silver,
        tickers=replace(silver.tickers, rows=rebound(silver.tickers.rows)),
        stocks=replace(silver.stocks, rows=rebound(silver.stocks.rows)),
        actions=replace(silver.actions, rows=rebound(silver.actions.rows)),
    )
    accepted = universe.build_universe(
        availability.resolve(
            equal, calendar=calendar, evidence=availability.AvailabilityEvidence(version="none")
        ),
        rule=fx.rule(),
        calendar=calendar,
        sessions=sessions,
        as_of=fx.AS_OF,
    )
    exploratory = decide_membership(
        layer, rule=fx.rule(), calendar=calendar, sessions=sessions, as_of=fx.AS_OF
    )

    def key(r: universe.MembershipRow) -> tuple[object, ...]:
        return (
            r.session_date,
            r.security_id,
            r.is_member,
            r.exclusion_reason,
            r.history_sessions_at_eval,
        )

    assert [key(r) for r in accepted.rows] == [key(r) for r in exploratory.rows]
    assert [c.document() for c in accepted.census] == [c.document() for c in exploratory.census]


def test_the_accepted_build_refuses_an_exploratory_layer_by_type(
    dataset: ExploratoryDataset,
) -> None:
    with pytest.raises(TypeError):
        universe.build_universe(
            dataset.layer,  # type: ignore[arg-type]
            rule=fx.rule(),
            calendar=dataset.calendar,
            sessions=(dataset.calendar.sessions[300].session_date,),
            as_of=fx.AS_OF,
        )
    assert type(dataset.layer) is ExploratoryResolvedLayer
    with pytest.raises(ValueError):
        availability.Availability(
            rule=availability.AvailabilityRule.P2_FIRST_SEEN,
            provider_bound_derivation="AS_DATED",  # type: ignore[arg-type]
            provider_available_upper_bound=fx.AS_OF,
            public_bound_derivation=next(iter(PublicBoundDerivation)),
            public_available_upper_bound=None,
            governing_time=fx.AS_OF,
            evidence_digest=None,
            limitations=(),
        )


# --- publication and reader ---------------------------------------------------------------------


def test_the_publication_is_exploratory_and_never_an_a1_publication(
    dataset: ExploratoryDataset, inputs: ExploratoryInputSet
) -> None:
    publication = inputs.publications[0]
    assert publication.content_digest == dataset.content_digest
    assert publication.provenance.profile is ExploratoryProfile.EXPLORATORY_HINDSIGHT
    assert publication.provenance.source_manifest_digest == fx.source_digest()
    assert parse_publication(publication.document()) == publication
    from kalpamani.data.curate import publication as a1

    # Disjoint types by construction: neither the publication nor the dataset descends from
    # the A1 VerifiedPublication, and the name never enters their documents.
    assert a1.VerifiedPublication not in type(publication).__mro__
    assert a1.VerifiedPublication not in type(dataset).__mro__
    assert "VerifiedPublication" not in json.dumps(publication.document())


def test_production_consumers_refuse_the_exploratory_input_set(inputs: ExploratoryInputSet) -> None:
    assert admit(breakout_long.build_spec(), inputs) is AdmissionOutcome.REFUSED_PRODUCTION_CONSUMER
    assert admit(M0_RESEARCH_SPECIFICATION, inputs) is AdmissionOutcome.ADMITTED
    assert (
        breakout_long.build_spec().data.required_profile
        is InformationSetProfile.PROVIDER_REALISTIC_PIT
    )
    assert breakout_long.BreakoutLongParameters().high_proximity_sessions == 252


def test_split_only_forward_base_adjustment_is_applied_through_the_reader(
    dataset: ExploratoryDataset,
) -> None:
    sid = fx.security_id("ZZCC")
    before = dataset.bars_through(sid, fx.SPLIT_EX - timedelta(days=1))
    after = dataset.bars_through(sid, fx.SPLIT_EX)
    assert before[-1].close == Decimal("40.000000")  # served before the split: unadjusted
    assert (
        after[-2].close == Decimal("20.000000") and after[-2].volume == 100000
    )  # divided by 2 once the split is known
    assert after[-1].close == Decimal("20.000000")


# --- the three instants -------------------------------------------------------------------------


def test_membership_signal_and_execution_are_three_distinct_instants(
    dataset: ExploratoryDataset, result: M0Result
) -> None:
    calendar = dataset.calendar
    phases = fx.phases_of(calendar)
    d = phases["development"][5]
    trade = trades_of(result, "ZZAA")[0]
    assert trade.signal_session == d
    assert (
        trade.entry_session
        == calendar.sessions[[s.session_date for s in calendar.sessions].index(d) + 1].session_date
    )
    decision = calendar.decision_time(d, margin=timedelta(seconds=1800))
    opened = calendar.open_at(d)
    assert decision is not None and opened is not None
    assert decision == opened - timedelta(seconds=1800)
    # Membership for d consumed bars through d-1 only: the last bar consumed predates d.
    row = next(
        r
        for r in dataset.membership.rows
        if r.session_date == d and r.security_id == trade.security_id
    )
    assert row.decision_time == decision
    assert all(bar_id.split(":")[0] < d.isoformat() for bar_id in row.bars_consumed)
    # The signal consumed the evaluation bar of d (its close), bounded at close(d) > decision time.
    evaluation_bar = dataset.bars_through(trade.security_id, d)[-1]
    assert (
        evaluation_bar.session_date == d and evaluation_bar.bar_end_time == opened + REGULAR_SESSION
    )
    assert evaluation_bar.bar_end_time > decision
    # Execution at the next open: the fill sits above that open by the costs, never at the
    # signal close.
    entry_bar = dataset.bars_through(trade.security_id, trade.entry_session)[-1]
    assert trade.entry_open == entry_bar.open
    assert trade.entry_fill > trade.entry_open
    assert trade.entry_fill != evaluation_bar.close


def test_execution_uses_only_prior_session_addv(
    dataset: ExploratoryDataset, inputs: ExploratoryInputSet
) -> None:
    """Changing the executing session's volume changes no fill and no participation."""
    baseline = run_m0(
        specification=M0_RESEARCH_SPECIFICATION,
        inputs=inputs,
        dataset=dataset,
        config=M0_SYNTHETIC_FIXTURE,
        data_kind=DataKind.SYNTHETIC,
    )
    trade = trades_of(baseline, "ZZAA")[0]
    calendar = dataset.calendar
    silver = fx.silver_layer(calendar)
    from dataclasses import replace

    changed_rows = []
    for row in silver.stocks.rows:
        if (
            row.security_id == trade.security_id
            and row.fields["date"] == trade.entry_session.isoformat()
        ):
            fields = dict(row.fields)
            fields["volume"] = "5000"  # a hundredfold lower volume ON the executing session
            changed_rows.append(replace(row, fields=fields))
        else:
            changed_rows.append(row)
    layer = resolve_as_dated(
        replace(silver, stocks=replace(silver.stocks, rows=tuple(changed_rows))), calendar=calendar
    )
    from kalpamani.data.exploratory.resolution import decide_membership_all

    membership = decide_membership_all(layer, rule=fx.rule(), calendar=calendar, as_of=fx.AS_OF)
    altered = ExploratoryDataset(
        layer=layer,
        membership=membership,
        calendar=calendar,
        benchmark=build_benchmark_a(layer, membership, calendar=calendar),
        as_of=fx.AS_OF,
        source_manifest_digest=fx.source_digest(),
    )
    altered_inputs = ExploratoryInputSet(
        publications=(
            publish(altered, publication_id="synthetic-m0-pub-02", limitations=LIMITATIONS),
        )
    )
    changed = run_m0(
        specification=M0_RESEARCH_SPECIFICATION,
        inputs=altered_inputs,
        dataset=altered,
        config=M0_SYNTHETIC_FIXTURE,
        data_kind=DataKind.SYNTHETIC,
    )
    other = trades_of(changed, "ZZAA")[0]
    assert (
        other.entry_fill,
        other.shares,
        other.entry_participation_pct,
        other.entry_commission,
        other.planned_risk,
    ) == (
        trade.entry_fill,
        trade.shares,
        trade.entry_participation_pct,
        trade.entry_commission,
        trade.planned_risk,
    )


# --- sizing, limits, sequencing -----------------------------------------------------------------


def test_final_fill_rejection_preserves_both_limits_without_resizing(
    dataset: ExploratoryDataset, inputs: ExploratoryInputSet
) -> None:
    """A participation term large enough to lift the final fill above the estimate rejects the
    candidate under the position limit; a tiny stop distance rejects under the risk limit."""
    steep = M0Configuration(
        provenance=ConfigurationProvenance.SYNTHETIC_FIXTURE,
        participation_free_pct=Decimal(0),
        slippage_bps_per_participation_pct=Decimal(400),
    )
    result = run_m0(
        specification=M0_RESEARCH_SPECIFICATION,
        inputs=inputs,
        dataset=dataset,
        config=steep,
        data_kind=DataKind.SYNTHETIC,
    )
    skips = [s for s in ledger(result, TerminalPolicy.OPTIMISTIC).skips]
    reasons = {s.reason for s in skips}
    assert (
        Skip.SKIPPED_POSITION_LIMIT_AT_FINAL_FILL in reasons
        or Skip.SKIPPED_RISK_LIMIT_AT_FINAL_FILL in reasons
    )
    # No trade in any ledger breaches either limit, and none was resized to fit.
    for item in (*result.ledgers, *result.baselines):
        for t in item.trades:
            assert t.planned_risk <= steep.risk_per_trade
            assert t.entry_fill * t.shares <= steep.position_cap
    for item in (*result.ledgers,):
        for t in item.trades:
            # The limits were applied on the final fill: recomputing from the fill reproduces
            # the record.
            assert t.planned_risk == (Decimal(t.shares) * (t.entry_fill - t.stop_level)).quantize(
                Decimal("0.01")
            )


def test_exits_precede_entries_ranking_cash_and_open_risk_are_deterministic(
    dataset: ExploratoryDataset, result: M0Result
) -> None:
    opt = ledger(result, TerminalPolicy.OPTIMISTIC)
    phases = fx.phases_of(dataset.calendar)
    tight_entry = phases["development"][61]
    tight = sorted(
        (t for t in opt.trades if t.entry_session == tight_entry), key=lambda t: t.security_id
    )
    assert len(tight) == 12
    cash_skips = [
        s for s in opt.skips if s.reason is Skip.SKIPPED_CASH and s.session == tight_entry
    ]
    assert len(cash_skips) == 1 and cash_skips[0].security_id == fx.security_id(
        "ZZTM"
    )  # the last by id
    # Ranking: equal relative strength and ADDV, so the security id decides; the thirteenth
    # is skipped.
    wide_entry = phases["validation"][41]
    wide = [t for t in opt.trades if t.entry_session == wide_entry]
    assert len(wide) == 10
    risk_skips = [
        s for s in opt.skips if s.reason is Skip.SKIPPED_RISK_CAPACITY and s.session == wide_entry
    ]
    assert len(risk_skips) == 3
    assert sum(t.planned_risk for t in wide) <= M0_SYNTHETIC_FIXTURE.open_risk_cap
    # Commission floor and per-share rate.
    assert all(
        t.entry_commission
        == max(Decimal("1.00"), Decimal("0.005") * t.shares).quantize(Decimal("0.01"))
        for t in opt.trades
    )


def test_stop_and_time_exit_precedence_and_re_entry_timing(
    dataset: ExploratoryDataset, result: M0Result
) -> None:
    calendar = [s.session_date for s in dataset.calendar.sessions]
    stop = trades_of(result, "ZZBB")[0]
    assert stop.exit_reason is ExitReason.STOP
    assert stop.exit_session is not None
    # The close below the base low is at after[2]; the exit executes at the NEXT open, after[3].
    assert calendar.index(stop.exit_session) == calendar.index(stop.entry_session) + 3
    assert stop.exit_fill is not None and stop.r_multiple is not None
    assert stop.r_multiple < Decimal(-1)  # more than 1R lost through the gap
    time_exit = trades_of(result, "ZZAA")[0]
    assert time_exit.exit_reason is ExitReason.TIME and time_exit.held_sessions == 20
    assert time_exit.exit_session is not None
    assert calendar.index(time_exit.exit_session) == calendar.index(time_exit.entry_session) + 20
    # Re-entry: a security is never held twice at once and any re-entry is after its exit.
    for item in result.ledgers:
        by_security: dict[str, list[m0.Trade]] = {}
        for t in item.trades:
            by_security.setdefault(t.security_id, []).append(t)
        for trades in by_security.values():
            trades.sort(key=lambda t: t.entry_session)
            for earlier, later in pairwise(trades):
                assert (
                    earlier.exit_session is not None and later.entry_session > earlier.exit_session
                )


def test_missing_bar_without_an_action_is_held_and_counted(result: M0Result) -> None:
    trade = trades_of(result, "ZZDD")[0]
    assert trade.missing_bar_sessions == 1
    assert trade.exit_reason is ExitReason.TIME and trade.held_sessions == 20
    # ZZDD's one, plus every session ZZMM and ZZNN were held through silence to the end.
    opt = ledger(result, TerminalPolicy.OPTIMISTIC)
    open_at_end = [t for t in opt.trades if t.exit_reason is ExitReason.OPEN_AT_END]
    assert opt.missing_bar_held_sessions == 1 + sum(t.missing_bar_sessions for t in open_at_end)
    assert opt.missing_bar_held_sessions > 1


def test_entry_gap_skip_is_recorded_and_no_trade_opens(result: M0Result) -> None:
    assert trades_of(result, "ZZEE") == []
    skips = [
        s
        for s in ledger(result, TerminalPolicy.OPTIMISTIC).skips
        if s.security_id == fx.security_id("ZZEE")
    ]
    assert skips and skips[0].reason is Skip.SKIPPED_ENTRY_GAP


# --- terminal events ----------------------------------------------------------------------------


def test_terminal_recognition_is_causal_from_the_dated_action(
    dataset: ExploratoryDataset, result: M0Result
) -> None:
    calendar = [s.session_date for s in dataset.calendar.sessions]
    opt = trades_of(result, "ZZCC")[0]
    delisted = next(a for a in dataset.layer.actions if a.row.fields.get("action") == "delisted")
    when = datetime.fromisoformat(str(delisted.row.fields["date"])).date()
    assert opt.exit_reason is ExitReason.TERMINAL_VALUATION_OPTIMISTIC
    assert opt.exit_session == when  # recognized at that session's open from the action's bound
    assert delisted.availability.governing_time == dataset.calendar.open_at(when)
    # The last close through the session before recognition values the position; no bar
    # on `when` exists.
    last = dataset.bars_through(opt.security_id, when)
    assert last[-1].session_date == calendar[calendar.index(when) - 1]
    assert opt.exit_fill is not None and opt.exit_fill < last[-1].close
    # A security with a missing bar and NO action (ZZDD) is not terminal.
    assert trades_of(result, "ZZDD")[0].exit_reason is ExitReason.TIME


def test_a_delisting_dated_before_bars_stop_is_still_recognized_from_the_action(
    dataset: ExploratoryDataset, inputs: ExploratoryInputSet
) -> None:
    """Recognition reads the admissible action, not the missing bar: move the action one
    session earlier (bars still delivered that day) and the terminal event moves with it."""
    from dataclasses import replace

    from kalpamani.data.exploratory.resolution import decide_membership_all

    calendar = dataset.calendar
    silver = fx.silver_layer(calendar)
    sessions = [s.session_date for s in calendar.sessions]
    rows = []
    for row in silver.actions.rows:
        if row.fields.get("action") == "delisted":
            when = datetime.fromisoformat(str(row.fields["date"])).date()
            earlier = sessions[sessions.index(when) - 1]
            fields = dict(row.fields)
            fields["date"] = earlier.isoformat()
            rows.append(replace(row, fields=fields, row_key=(earlier.isoformat(), "delisted")))
        else:
            rows.append(row)
    layer = resolve_as_dated(
        replace(silver, actions=replace(silver.actions, rows=tuple(rows))), calendar=calendar
    )
    membership = decide_membership_all(layer, rule=fx.rule(), calendar=calendar, as_of=fx.AS_OF)
    altered = ExploratoryDataset(
        layer=layer,
        membership=membership,
        calendar=calendar,
        benchmark=build_benchmark_a(layer, membership, calendar=calendar),
        as_of=fx.AS_OF,
        source_manifest_digest=fx.source_digest(),
    )
    altered_inputs = ExploratoryInputSet(
        publications=(
            publish(altered, publication_id="synthetic-m0-pub-03", limitations=LIMITATIONS),
        )
    )
    changed = run_m0(
        specification=M0_RESEARCH_SPECIFICATION,
        inputs=altered_inputs,
        dataset=altered,
        config=M0_SYNTHETIC_FIXTURE,
        data_kind=DataKind.SYNTHETIC,
    )
    moved = trades_of(changed, "ZZCC")[0]
    original = trades_of(
        run_m0(
            specification=M0_RESEARCH_SPECIFICATION,
            inputs=inputs,
            dataset=dataset,
            config=M0_SYNTHETIC_FIXTURE,
            data_kind=DataKind.SYNTHETIC,
        ),
        "ZZCC",
    )[0]
    assert moved.exit_session is not None and original.exit_session is not None
    assert sessions.index(moved.exit_session) == sessions.index(original.exit_session) - 1
    assert (
        moved.bars_after_delisting == 0
    )  # the position closed at that open; the same-day bar is unread


def test_the_two_terminal_ledgers_are_separate_and_reconcile(result: M0Result) -> None:
    opt = ledger(result, TerminalPolicy.OPTIMISTIC)
    loss = ledger(result, TerminalPolicy.TOTAL_LOSS)
    o = trades_of(result, "ZZCC", TerminalPolicy.OPTIMISTIC)[0]
    z = trades_of(result, "ZZCC", TerminalPolicy.TOTAL_LOSS)[0]
    assert (
        o.exit_reason is ExitReason.TERMINAL_VALUATION_OPTIMISTIC
        and z.exit_reason is ExitReason.TERMINAL_TOTAL_LOSS
    )
    assert z.exit_fill is None and z.exit_commission == 0
    assert z.realized_pnl == -(o.entry_fill * o.shares + o.entry_commission).quantize(
        Decimal("0.01")
    )
    assert (
        o.realized_pnl is not None
        and z.realized_pnl is not None
        and o.realized_pnl > z.realized_pnl
    )
    # Every ledger reconciles at the end of its block: liquidation-end equity = capital + the
    # realized P&L of the window's trades + the unrealized P&L of the positions still open,
    # less those positions' entry commissions (already paid, not yet in any P&L).
    for item in (opt, loss):
        for metrics in item.metrics:
            window_trades = [t for t in item.trades if t.window is metrics.window]
            realized = sum(
                (t.realized_pnl for t in window_trades if t.realized_pnl is not None), Decimal(0)
            )
            unrealized = sum(
                (t.unrealized_pnl for t in window_trades if t.unrealized_pnl is not None),
                Decimal(0),
            )
            open_entry_commission = sum(
                (
                    t.entry_commission
                    for t in window_trades
                    if t.exit_reason is ExitReason.OPEN_AT_END
                ),
                Decimal(0),
            )
            assert metrics.liquidation_end_equity == (
                M0_SYNTHETIC_FIXTURE.capital + realized + unrealized - open_entry_commission
            ).quantize(Decimal("0.01"))
    # The same figures are never mixed: the loss ledger's development P&L is lower by the
    # terminal difference.
    assert loss.metrics[0].net_pnl < opt.metrics[0].net_pnl


# --- windows, freezing, benchmark ---------------------------------------------------------------


def test_development_and_validation_initialize_independently_under_the_frozen_digest(
    dataset: ExploratoryDataset, result: M0Result
) -> None:
    opt = ledger(result, TerminalPolicy.OPTIMISTIC)
    phases = fx.phases_of(dataset.calendar)
    first_validation = next(e for e in opt.equity if e.session == phases["validation"][0])
    assert (
        first_validation.cash == M0_SYNTHETIC_FIXTURE.capital
        and first_validation.positions_value == 0
    )
    dev_metrics, val_metrics = opt.metrics
    assert dev_metrics.start_equity == val_metrics.start_equity == M0_SYNTHETIC_FIXTURE.capital
    assert dev_metrics.trades == 19 and val_metrics.trades == 11
    assert dev_metrics.open_at_end == 1 and val_metrics.open_at_end == 1
    assert not any(
        t.window is Window.DEVELOPMENT
        and t.exit_session is not None
        and t.exit_session >= phases["validation"][0]
        for t in opt.trades
    )
    # The trial digest binds specification + configuration + calendar + phases + benchmark,
    # before any bar.
    assert result.trial_digest == m0.trial_digest(
        M0_RESEARCH_SPECIFICATION,
        M0_SYNTHETIC_FIXTURE,
        dataset,
        phases_for(tuple(s.session_date for s in dataset.calendar.sessions), M0_SYNTHETIC_FIXTURE),
    )
    other = M0Configuration(
        provenance=ConfigurationProvenance.SYNTHETIC_FIXTURE, time_exit_held_sessions=19
    )
    assert (
        m0.trial_digest(
            M0_RESEARCH_SPECIFICATION,
            other,
            dataset,
            phases_for(tuple(s.session_date for s in dataset.calendar.sessions), other),
        )
        != result.trial_digest
    )
    assert result.phases["warm_up"][2] == 253 and result.phases["development"][2] == 126
    assert (
        result.phases["purge"][2] == 30
        and result.phases["validation"][2] == 126
        and result.phases["tail"][2] == 30
    )


def test_benchmark_membership_cannot_depend_on_same_session_returns(
    dataset: ExploratoryDataset,
) -> None:
    """Change a member's bar ON session t: its own return moves the index, but the member set
    for t -- fixed at decision_time(t) from data through t-1 -- does not."""
    calendar = dataset.calendar
    sessions = [s.session_date for s in calendar.sessions]
    t = sessions[320]
    point = next(p for p in dataset.benchmark.points if p.session_date == t)
    assert point.members == len(dataset.members_at(t))
    from dataclasses import replace

    silver = fx.silver_layer(calendar)
    rows = []
    for row in silver.stocks.rows:
        if row.symbol == "ZZAA" and row.fields["date"] == t.isoformat():
            fields = dict(row.fields)
            fields.update(close="1.00", closeunadj="1.00", open="1.00", high="1.00", low="0.50")
            rows.append(replace(row, fields=fields))
        else:
            rows.append(row)
    from kalpamani.data.exploratory.resolution import decide_membership_all

    layer = resolve_as_dated(
        replace(silver, stocks=replace(silver.stocks, rows=tuple(rows))), calendar=calendar
    )
    membership = decide_membership_all(layer, rule=fx.rule(), calendar=calendar, as_of=fx.AS_OF)
    changed = build_benchmark_a(layer, membership, calendar=calendar)
    changed_point = next(p for p in changed.points if p.session_date == t)
    members_t = {r.security_id for r in membership.rows if r.session_date == t and r.is_member}
    assert members_t == set(dataset.members_at(t))  # inclusion unchanged by the same-session bar
    assert changed_point.members == point.members
    assert changed_point.level < point.level  # the return itself entered the index
    # The following session's membership may change (price floor), which is the
    # point-in-time result.
    assert dataset.benchmark.benchmark_id == BENCHMARK_A_ID


def test_benchmark_missing_bars_count_zero_in_the_optimistic_series_and_minus_one_in_total_loss(
    dataset: ExploratoryDataset,
) -> None:
    delisted = next(a for a in dataset.layer.actions if a.row.fields.get("action") == "delisted")
    when = datetime.fromisoformat(str(delisted.row.fields["date"])).date()
    point = next(p for p in dataset.benchmark.points if p.session_date == when)
    assert point.missing_bars >= 1
    assert point.level_total_loss < point.level


# --- configuration provenance, refusals, determinism, report -------------------------------------


def test_real_data_refuses_the_synthetic_fixture_and_unselected_owner_choices(
    dataset: ExploratoryDataset, inputs: ExploratoryInputSet
) -> None:
    with pytest.raises(M0RunError) as caught:
        run_m0(
            specification=M0_RESEARCH_SPECIFICATION,
            inputs=inputs,
            dataset=dataset,
            config=M0_SYNTHETIC_FIXTURE,
            data_kind=DataKind.REAL,
        )
    assert caught.value.refusal is RunRefusal.REFUSED_FIXTURE_ON_REAL_DATA
    with pytest.raises(M0RunError) as caught:
        M0Configuration(provenance=ConfigurationProvenance.OWNER_SELECTED)
    assert caught.value.refusal is RunRefusal.REFUSED_UNSELECTED_CONFIGURATION
    with pytest.raises(M0RunError) as caught:
        M0Configuration(
            provenance=ConfigurationProvenance.OWNER_SELECTED,
            owner_selections={"O-1": "yes"},  # type: ignore[arg-type]
        )
    assert caught.value.refusal is RunRefusal.REFUSED_INVALID_CONFIGURATION
    assert M0_SYNTHETIC_FIXTURE.provenance is ConfigurationProvenance.SYNTHETIC_FIXTURE
    assert M0_SYNTHETIC_FIXTURE.owner_selections is None


def test_a_non_admitted_specification_or_a_foreign_dataset_is_refused(
    dataset: ExploratoryDataset, inputs: ExploratoryInputSet
) -> None:
    production: Any = breakout_long.build_spec()
    with pytest.raises(M0RunError) as caught:
        run_m0(
            specification=production,
            inputs=inputs,
            dataset=dataset,
            config=M0_SYNTHETIC_FIXTURE,
            data_kind=DataKind.SYNTHETIC,
        )
    assert caught.value.refusal is RunRefusal.REFUSED_NOT_ADMITTED
    foreign = ExploratoryPublication(
        publication_id="synthetic-m0-pub-09",
        content_digest="0" * 64,
        provenance=inputs.publications[0].provenance,
    )
    other = ExploratoryInputSet(publications=(foreign,))
    with pytest.raises(M0RunError) as caught:
        run_m0(
            specification=M0_RESEARCH_SPECIFICATION,
            inputs=other,
            dataset=dataset,
            config=M0_SYNTHETIC_FIXTURE,
            data_kind=DataKind.SYNTHETIC,
        )
    assert caught.value.refusal is RunRefusal.REFUSED_CONTENT_DIGEST_MISMATCH
    short = M0Configuration(
        provenance=ConfigurationProvenance.SYNTHETIC_FIXTURE, warm_up_sessions=600
    )
    with pytest.raises(M0RunError) as caught:
        run_m0(
            specification=M0_RESEARCH_SPECIFICATION,
            inputs=inputs,
            dataset=dataset,
            config=short,
            data_kind=DataKind.SYNTHETIC,
        )
    assert caught.value.refusal is RunRefusal.REFUSED_CALENDAR_TOO_SHORT


def test_repeated_identical_runs_produce_identical_canonical_results(
    inputs: ExploratoryInputSet, result: M0Result
) -> None:
    again = run_m0(
        specification=M0_RESEARCH_SPECIFICATION,
        inputs=inputs,
        dataset=fx.dataset(),
        config=M0_SYNTHETIC_FIXTURE,
        data_kind=DataKind.SYNTHETIC,
    )
    assert again.digest == result.digest
    assert json.dumps(again.document(), sort_keys=True) == json.dumps(
        result.document(), sort_keys=True
    )


def test_the_report_is_labelled_and_carries_every_ledger(result: M0Result, tmp_path: Path) -> None:
    text = render_markdown(result, determinism=(result.digest, result.digest))
    assert text.startswith("# M0 exploratory run — **SYNTHETIC / EXPLORATORY_HINDSIGHT**")
    for needle in (
        "TERMINAL_VALUATION_OPTIMISTIC",
        "TERMINAL_TOTAL_LOSS",
        "SKIPPED_CASH",
        "SKIPPED_RISK_CAPACITY",
        "SKIPPED_ENTRY_GAP",
        "identical",
        "No figure here satisfies P1-P9",
    ):
        assert needle in text
    for d in M0_RESEARCH_SPECIFICATION.differences:
        assert d in text
    paths = write_report(result, tmp_path)
    assert paths["markdown"].is_file() and paths["json"].is_file()
    loaded: dict[str, Any] = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert (
        loaded["label"] == "SYNTHETIC / EXPLORATORY_HINDSIGHT"
        and loaded["profile"] == "EXPLORATORY_HINDSIGHT"
    )
    assert (
        summary(result)["ledgers"]["breakout-long/OPTIMISTIC"]["exits"][
            "TERMINAL_VALUATION_OPTIMISTIC"
        ]
        == 1
    )
    assert (
        summary(result)["ledgers"]["breakout-long/TOTAL_LOSS"]["exits"]["TERMINAL_TOTAL_LOSS"] == 1
    )


def test_sensitivities_vary_only_what_they_declare(result: M0Result) -> None:
    labels = [s.label for s in result.sensitivities]
    assert labels == [
        "breakout-long/OPTIMISTIC/costs-x0",
        "breakout-long/OPTIMISTIC/costs-x2",
        "breakout-long/OPTIMISTIC/idle-4pct",
    ]
    zero, double, idle = result.sensitivities
    base = ledger(result, TerminalPolicy.OPTIMISTIC)
    assert zero.metrics[0].net_pnl > base.metrics[0].net_pnl > double.metrics[0].net_pnl
    assert all(t.entry_commission == 0 for t in zero.trades)
    assert (
        idle.metrics[0].end_equity > base.metrics[0].end_equity
        and idle.metrics[0].net_pnl == base.metrics[0].net_pnl
    )
    assert [t.security_id for t in idle.trades] == [t.security_id for t in base.trades]
