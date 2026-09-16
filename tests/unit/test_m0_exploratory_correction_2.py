"""PR #112 review correction 2 -- targeted regressions, written before the correction.

Two findings from source inspection of ``95be27e6``: (1) the split-effective open read that
session's close to settle the fractional entitlement and credited the cash before the day's
exits and entries; (2) ``OwnerSelections`` put a sizing choice at O-7, which the owner decision
form defines as the event-handling choice (O-10 is sizing and sequencing). Synthetic fixtures
only; software behaviour only.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any, Final

import pytest

from fixtures import m0_exploratory as fx
from kalpamani.data.exploratory import m0
from kalpamani.data.exploratory.contracts import ExploratoryInputSet
from kalpamani.data.exploratory.dataset import ExploratoryDataset, publish
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
from kalpamani.data.production.sharadar.silver import SilverLayer

LIMITATIONS: Final = frozenset(ExploratoryLimitation)
CENT: Final = Decimal("0.01")
THREE_FOR_TWO: Final = Decimal("1.5")
#: A ratio no whole-share position in the fixture multiplies to a whole number: a fraction is due.
ODD_RATIO: Final = Decimal("1.003")


def run(dataset: ExploratoryDataset, tag: str, config: M0Configuration | None = None) -> M0Result:
    inputs = ExploratoryInputSet(
        publications=(
            publish(dataset, publication_id=f"synthetic-c2-{tag}", limitations=LIMITATIONS),
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
    sid = fx.security_id(symbol)
    for item in dataset.layer.stocks:
        if item.row.security_id == sid and item.row.fields.get("date") == session.isoformat():
            return Decimal(str(item.row.fields["closeunadj"]))
    raise KeyError((symbol, session))


def with_close_changed(
    layer: SilverLayer, symbol: str, session: date, factor: Decimal
) -> SilverLayer:
    """The same layer with one security's close on one session multiplied (high kept above)."""
    sid = fx.security_id(symbol)
    rows = []
    for row in layer.stocks.rows:
        if row.security_id == sid and row.fields.get("date") == session.isoformat():
            fields = dict(row.fields)
            close = (Decimal(str(fields["close"])) * factor).quantize(Decimal("0.0001"))
            for name in ("close", "closeadj", "closeunadj"):
                fields[name] = str(close)
            fields["high"] = str(max(Decimal(str(fields["high"])), close))
            rows.append(replace(row, fields=fields))
        else:
            rows.append(row)
    return replace(layer, stocks=replace(layer.stocks, rows=tuple(rows)))


@pytest.fixture(scope="module")
def calendar() -> Any:
    return fx.calendar()


@pytest.fixture(scope="module")
def sessions(calendar: Any) -> list[date]:
    return [s.session_date for s in calendar.sessions]


@pytest.fixture(scope="module")
def phases(calendar: Any) -> dict[str, tuple[date, ...]]:
    return fx.phases_of(calendar)


@pytest.fixture(scope="module")
def base(calendar: Any) -> ExploratoryDataset:
    return fx.dataset(calendar)


@pytest.fixture(scope="module")
def base_result(base: ExploratoryDataset) -> M0Result:
    return run(base, "base")


def _ex_mid_hold(base_result: M0Result, sessions: list[date]) -> date:
    # ZZBB's stop executes at this open (three sessions after the common entry), so the
    # session has opening transactions to compare while ZZAA is still held.
    entry = trades_of(base_result, "ZZAA")[0].entry_session
    return sessions[sessions.index(entry) + 3]


# --- finding 1: the fractional entitlement is settled at the close, never read at the open ---


def test_c2_the_split_session_close_cannot_change_that_sessions_opening_decisions(
    calendar: Any, sessions: list[date], base_result: M0Result
) -> None:
    ex = _ex_mid_hold(base_result, sessions)
    split = fx.with_split(fx.silver_layer(calendar), "ZZAA", ex, ODD_RATIO)
    a = run(fx.dataset_from(split, calendar), "a")
    b = run(fx.dataset_from(with_close_changed(split, "ZZAA", ex, Decimal("1.03")), calendar), "b")
    opening = m0.TransactionKind.ENTRY, m0.TransactionKind.EXIT
    day_a = [x for x in ledger(a).transactions if x.session == ex and x.kind in opening]
    day_b = [x for x in ledger(b).transactions if x.session == ex and x.kind in opening]
    assert day_a and day_a == day_b  # fills, shares, commissions and cash movements at the open
    assert [s for s in ledger(a).skips if s.session == ex] == [
        s for s in ledger(b).skips if s.session == ex
    ]
    ta, tb = trades_of(a, "ZZAA")[0], trades_of(b, "ZZAA")[0]
    assert (
        ta.exit_shares == tb.exit_shares
        and ta.split_events[0].shares_after == tb.split_events[0].shares_after
    )
    assert ta.cash_in_lieu != tb.cash_in_lieu  # the close prices the entitlement, at the close
    cil_a = [x for x in ledger(a).transactions if x.kind is m0.TransactionKind.CASH_IN_LIEU]
    assert len(cil_a) == 1 and cil_a[0].session == ex and cil_a[0].timing is m0.Timing.CLOSE
    # Every opening transaction of the session precedes the settlement in the journal.
    journal = ledger(a).transactions
    assert max(journal.index(x) for x in day_a) < journal.index(cil_a[0])


def test_c2_a_cash_constrained_candidate_cannot_use_unsettled_fractional_proceeds(
    calendar: Any, sessions: list[date], phases: dict[str, tuple[date, ...]]
) -> None:
    """With the time exit lengthened so ZZAA is still held on the tight-group session, a 3:2
    split of ZZAA on that session yields a fractional entitlement worth more than the cash
    shortfall of the last tight candidate. The candidate is still SKIPPED_CASH at the open,
    and the entitlement lands in cash only at the close."""
    ex = phases["development"][61]
    layer = fx.with_split(fx.silver_layer(calendar), "ZZAA", ex, ODD_RATIO)
    dataset = fx.dataset_from(layer, calendar)
    long_hold = M0Configuration(
        provenance=ConfigurationProvenance.SYNTHETIC_FIXTURE, time_exit_held_sessions=60
    )
    probe = run(dataset, "probe", long_hold)
    opt = ledger(probe)
    assert any(
        t.security_id == fx.security_id("ZZAA") and t.entry_session < ex < (t.exit_session or ex)
        for t in opt.trades
    )
    entered = [
        x for x in opt.transactions if x.kind is m0.TransactionKind.ENTRY and x.session == ex
    ]
    assert entered, "no tight-group entry on the split session"
    cash_before_open = next(
        e for e in opt.equity if e.session == sessions[sessions.index(ex) - 1]
    ).cash
    exits_open = sum(
        (
            x.cash_delta
            for x in opt.transactions
            if x.kind is m0.TransactionKind.EXIT and x.session == ex
        ),
        Decimal(0),
    )
    per_entry = -entered[0].cash_delta  # notional plus commission, identical across the group
    fraction_value = trades_of(probe, "ZZAA")[0].cash_in_lieu
    assert fraction_value > Decimal("3.00")
    # Capital such that, at the open, cash covers exactly one entry fewer than the candidates
    # and the shortfall is smaller than the entitlement settled at the close.
    shortfall = Decimal("3.00")
    admitted = len(entered)
    capital = (
        long_hold.capital - cash_before_open - exits_open + per_entry * (admitted + 1) - shortfall
    ).quantize(CENT)
    tuned = M0Configuration(
        provenance=ConfigurationProvenance.SYNTHETIC_FIXTURE,
        time_exit_held_sessions=60,
        capital=capital,
    )
    result = run(dataset, "tuned", tuned)
    item = ledger(result)
    day_entries = [
        x for x in item.transactions if x.kind is m0.TransactionKind.ENTRY and x.session == ex
    ]
    cash_skips = [s for s in item.skips if s.session == ex and s.reason is Skip.SKIPPED_CASH]
    assert len(day_entries) == admitted and len(cash_skips) >= 1
    settled = [
        x
        for x in item.transactions
        if x.kind is m0.TransactionKind.CASH_IN_LIEU and x.session == ex
    ]
    assert len(settled) == 1 and settled[0].timing is m0.Timing.CLOSE
    assert settled[0].cash_delta > shortfall  # the proceeds would have covered it -- at the close
    cash_at_open = (
        next(e for e in item.equity if e.session == sessions[sessions.index(ex) - 1]).cash
        + sum(
            (
                x.cash_delta
                for x in item.transactions
                if x.kind is m0.TransactionKind.EXIT and x.session == ex
            ),
            Decimal(0),
        )
        + sum((x.cash_delta for x in day_entries), Decimal(0))
    )
    assert Decimal(0) <= cash_at_open < per_entry  # short of one more entry by design
    assert (
        cash_at_open + settled[0].cash_delta >= per_entry
    )  # ...which the entitlement would have covered


def test_c2_a_position_exiting_at_the_split_open_still_receives_its_entitlement_at_the_close(
    calendar: Any, sessions: list[date], base_result: M0Result
) -> None:
    before = trades_of(base_result, "ZZAA")[0]
    ex = before.exit_session
    assert ex is not None and before.exit_reason is ExitReason.TIME
    variant = fx.dataset_from(
        fx.with_split(fx.silver_layer(calendar), "ZZAA", ex, THREE_FOR_TWO), calendar
    )
    result = run(variant, "exit-day")
    t = trades_of(result, "ZZAA")[0]
    assert t.exit_session == ex and t.exit_reason is ExitReason.TIME
    whole = int((Decimal(before.shares) * THREE_FOR_TWO).to_integral_value(rounding="ROUND_DOWN"))
    assert t.exit_shares == whole and t.shares == before.shares
    fraction = Decimal(before.shares) * THREE_FOR_TWO - whole
    close = raw_close(variant, "ZZAA", ex)
    assert t.cash_in_lieu == (fraction * close).quantize(CENT) > 0
    event = t.split_events[0]
    assert (
        event.settlement_session == ex
        and event.settlement_policy is m0.SettlementPolicy.EX_SESSION_CLOSE
    )
    assert event.cash_in_lieu == t.cash_in_lieu
    # Realized P&L and R include the settlement; the exit itself was decided at the open.
    assert t.exit_fill is not None and t.realized_pnl is not None and t.r_multiple is not None
    proceeds = (t.exit_fill * t.exit_shares).quantize(CENT)
    basis = (t.entry_fill * t.shares).quantize(CENT)
    assert t.realized_pnl == (
        proceeds + t.cash_in_lieu - basis - t.entry_commission - t.exit_commission
    ).quantize(CENT)
    assert t.r_multiple == (t.realized_pnl / t.planned_risk).quantize(Decimal("0.0001"))
    journal = ledger(result).transactions
    exit_tx = next(
        x
        for x in journal
        if x.kind is m0.TransactionKind.EXIT and x.session == ex and x.security_id == t.security_id
    )
    cil_tx = [x for x in journal if x.kind is m0.TransactionKind.CASH_IN_LIEU]
    assert (
        len(cil_tx) == 1
        and cil_tx[0].session == ex
        and journal.index(exit_tx) < journal.index(cil_tx[0])
    )
    assert exit_tx.timing is m0.Timing.OPEN and cil_tx[0].timing is m0.Timing.CLOSE
    # Counted once, attributed to the originating trade and its window.
    assert sum((x.cash_in_lieu for x in ledger(result).trades), Decimal(0)) == t.cash_in_lieu
    assert t.window is Window.DEVELOPMENT


def test_c2_a_missing_close_on_the_split_session_is_handled_explicitly(
    calendar: Any, sessions: list[date], base_result: M0Result
) -> None:
    """ZZDD has no bar on one held session. A 3:2 split effective there settles at the next
    observed close, recorded as such -- the prior close is never read as if it were current."""
    dd = trades_of(base_result, "ZZDD")[0]
    ex = sessions[sessions.index(dd.entry_session) + 6]  # the missing session (after[6])
    variant = fx.dataset_from(
        fx.with_split(fx.silver_layer(calendar), "ZZDD", ex, ODD_RATIO), calendar
    )
    assert not any(b.session_date == ex for b in variant.raw_bars(fx.security_id("ZZDD")))
    result = run(variant, "missing-close")
    t = trades_of(result, "ZZDD")[0]
    event = t.split_events[0]
    following = sessions[sessions.index(ex) + 1]
    assert event.ex_date == ex and event.settlement_session == following
    assert event.settlement_policy is m0.SettlementPolicy.NEXT_OBSERVED_CLOSE
    assert event.price == raw_close(variant, "ZZDD", following)
    cil = [x for x in ledger(result).transactions if x.kind is m0.TransactionKind.CASH_IN_LIEU]
    assert len(cil) == 1 and cil[0].session == following
    # And an entitlement that never meets an observed close stays unresolved, at zero, recorded.
    mm = trades_of(base_result, "ZZMM")[0]
    assert mm.exit_reason is ExitReason.OPEN_AT_END
    silent = sessions[sessions.index(mm.entry_session) + 7]
    variant2 = fx.dataset_from(
        fx.with_split(fx.silver_layer(calendar), "ZZMM", silent, ODD_RATIO), calendar
    )
    result2 = run(variant2, "unresolved")
    t2 = trades_of(result2, "ZZMM")[0]
    event2 = t2.split_events[0]
    assert (
        event2.settlement_session is None
        and event2.settlement_policy is m0.SettlementPolicy.UNRESOLVED
    )
    assert event2.cash_in_lieu == 0 and t2.cash_in_lieu == 0
    assert t2.unresolved_entitlement_shares == Decimal(mm.shares) * ODD_RATIO - int(
        (Decimal(mm.shares) * ODD_RATIO).to_integral_value(rounding="ROUND_DOWN")
    )
    assert t2.unresolved_entitlement_shares > 0
    unresolved = ledger(result2).unresolved_entitlements
    assert len(unresolved) == 1 and unresolved[0].security_id == t2.security_id
    assert (
        unresolved[0].shares == t2.unresolved_entitlement_shares
        and unresolved[0].window is Window.DEVELOPMENT
    )
    assert not [
        x for x in ledger(result2).transactions if x.kind is m0.TransactionKind.CASH_IN_LIEU
    ]


def _reconcile(
    dataset: ExploratoryDataset,
    item: m0.Ledger,
    phases: dict[str, tuple[date, ...]],
    capital: Decimal,
) -> None:
    kinds = m0.TransactionKind
    for window, name, after in (
        (Window.DEVELOPMENT, "development", "purge"),
        (Window.VALIDATION, "validation", "tail"),
    ):
        block = (*phases[name], *phases[after])
        journal = [x for x in item.transactions if x.session in block]
        cash = capital + sum((x.cash_delta for x in journal), Decimal(0))
        trades = [t for t in item.trades if t.window is window]
        # Settlements: once each, and exactly what the trades carry.
        settlements = [x for x in journal if x.kind is kinds.CASH_IN_LIEU]
        assert sum((x.cash_delta for x in settlements), Decimal(0)) == sum(
            (t.cash_in_lieu for t in trades), Decimal(0)
        )
        assert all(x.timing is m0.Timing.CLOSE for x in settlements)
        for t in trades:
            assert (
                len([e for e in t.split_events if e.cash_in_lieu != 0])
                == len(
                    [
                        x
                        for x in settlements
                        if x.security_id == t.security_id and x.session >= t.entry_session
                    ]
                )
                or t.split_events == ()
            )
        realized = Decimal(0)
        for t in trades:
            if t.exit_reason is ExitReason.OPEN_AT_END:
                continue
            assert t.realized_pnl is not None
            proceeds = (
                Decimal(0) if t.exit_fill is None else (t.exit_fill * t.exit_shares).quantize(CENT)
            )
            basis = (t.entry_fill * t.shares).quantize(CENT)
            assert t.realized_pnl == (
                proceeds + t.cash_in_lieu - basis - t.entry_commission - t.exit_commission
            ).quantize(CENT)
            realized += t.realized_pnl
        marked = unrealized = open_entry_commission = Decimal(0)
        fractional_assets = Decimal(0)
        for t in trades:
            if t.exit_reason is not ExitReason.OPEN_AT_END:
                continue
            assert t.mark_price is not None and t.unrealized_pnl is not None
            value = (t.mark_price * t.exit_shares).quantize(CENT)
            marked += value
            remaining_basis = (t.entry_fill * t.shares).quantize(CENT) - t.cash_in_lieu
            assert t.unrealized_pnl == (value - remaining_basis).quantize(CENT)
            unrealized += t.unrealized_pnl
            open_entry_commission += t.entry_commission
            fractional_assets += t.unresolved_entitlement_shares
        interest = sum((x.cash_delta for x in journal if x.kind is kinds.INTEREST), Decimal(0))
        equity = (cash + marked).quantize(CENT)
        assert equity == (
            capital + realized + unrealized - open_entry_commission + interest
        ).quantize(CENT)
        assert fractional_assets == sum(
            (u.shares for u in item.unresolved_entitlements if u.window is window), Decimal(0)
        )  # carried at zero, listed, never priced from a stale close
        metrics = next(m for m in item.metrics if m.window is window)
        assert metrics.liquidation_end_equity == equity


def test_c2_everything_reconciles_with_settled_and_unresolved_entitlements(
    calendar: Any, sessions: list[date], phases: dict[str, tuple[date, ...]], base_result: M0Result
) -> None:
    ex = _ex_mid_hold(base_result, sessions)
    layer = fx.with_split(fx.silver_layer(calendar), "ZZAA", ex, ODD_RATIO)
    mm = trades_of(base_result, "ZZMM")[0]
    layer = fx.with_split(layer, "ZZMM", sessions[sessions.index(mm.entry_session) + 7], ODD_RATIO)
    dataset = fx.dataset_from(layer, calendar)
    result = run(dataset, "reconcile")
    for item in (*result.ledgers, *result.baselines, *result.sensitivities):
        _reconcile(dataset, item, phases, M0_SYNTHETIC_FIXTURE.capital)
    item = ledger(result)
    assert any(t.cash_in_lieu > 0 for t in item.trades) and item.unresolved_entitlements


# --- finding 2: O-7 is the event-handling choice; O-10 is sizing and sequencing ---------------


def _selections(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "o1_exploratory_mode": m0.ExploratoryModeChoice.ENABLED,
        "o2_benchmark": m0.BenchmarkChoice.A_EW_UNIVERSE,
        "o3_exit_rule": m0.ExitRuleChoice.CLOSE_BELOW_BASE_LOW_NEXT_OPEN,
        "o4_cost_model": m0.CostModelChoice.M0_SECTION_14,
        "o5_acquisition_route": m0.AcquisitionRouteChoice.BOUNDED_RUNS,
        "o6_compute_location": m0.ComputeLocationChoice.PRIVATE_AWS,
        "o7_event_handling": m0.EventHandlingChoice.EVENT_BLIND,
        "o8_data_window_start": date(2024, 6, 3),
        "o8_data_window_end": date(2026, 9, 14),
        "o9_terminal_accounting": m0.TerminalAccountingChoice.TWO_LEDGERS,
        "o10_sizing_and_sequencing": m0.SizingSequencingChoice.CLAUDE_S6_FINAL_FILL_REJECTION,
        "o11_no_untouched_window": m0.Acknowledgment.ACKNOWLEDGED,
    }
    values.update(overrides)
    return m0.OwnerSelections(**values)


def test_c2_o7_is_the_event_handling_choice_and_o10_is_sizing_and_sequencing() -> None:
    selections = _selections()
    document = selections.document()
    assert document["O-7"] == "EVENT_BLIND"
    assert document["O-10"] == "CLAUDE_S6_FINAL_FILL_REJECTION"
    assert [m.value for m in m0.EventHandlingChoice] == ["EVENT_BLIND", "WAIT_FOR_EVENT_ENTITY"]
    assert [m.value for m in m0.SizingSequencingChoice] == [
        "CLAUDE_S6_FINAL_FILL_REJECTION",
        "CLAUDE_S6_ONE_RESIZING_ITERATION",
    ]
    # Event-blind is the only executable choice; waiting needs an event entity that does not exist.
    with pytest.raises(M0RunError) as caught:
        _selections(o7_event_handling=m0.EventHandlingChoice.WAIT_FOR_EVENT_ENTITY)
    assert caught.value.refusal is RunRefusal.REFUSED_UNSUPPORTED_SELECTION
    with pytest.raises(M0RunError) as caught:
        _selections(
            o10_sizing_and_sequencing=m0.SizingSequencingChoice.CLAUDE_S6_ONE_RESIZING_ITERATION
        )
    assert caught.value.refusal is RunRefusal.REFUSED_UNSUPPORTED_SELECTION
    with pytest.raises(M0RunError) as caught:
        _selections(o7_event_handling="EVENT_BLIND")
    assert caught.value.refusal is RunRefusal.REFUSED_INVALID_CONFIGURATION


def test_c2_the_former_o7_sizing_substitution_is_rejected_not_reinterpreted() -> None:
    assert not hasattr(m0, "SizingPolicyChoice")
    assert not hasattr(m0, "FinalFillPolicyChoice")
    base = _selections()
    kwargs = {name: getattr(base, name) for name in base.__slots__}
    kwargs.pop("o7_event_handling")
    kwargs["o7_sizing_policy"] = "CLAUDE_S6_RESEARCH_PARAMETERS"
    with pytest.raises(TypeError):
        m0.OwnerSelections(**kwargs)
    kwargs = {name: getattr(base, name) for name in base.__slots__}
    kwargs.pop("o10_sizing_and_sequencing")
    kwargs["o10_final_fill_policy"] = "REJECTION"
    with pytest.raises(TypeError):
        m0.OwnerSelections(**kwargs)


def test_c2_corrected_choices_are_bound_into_the_trial_record(base: ExploratoryDataset) -> None:
    config = M0Configuration(
        provenance=ConfigurationProvenance.OWNER_SELECTED, owner_selections=_selections()
    )
    sessions = tuple(s.session_date for s in base.calendar.sessions)
    phases = m0.phases_for(sessions, config)
    record = m0.trial_document(M0_RESEARCH_SPECIFICATION, config, base, phases)
    selected = record["configuration"]["owner_selections"]
    assert selected["O-7"] == "EVENT_BLIND" and selected["O-10"] == "CLAUDE_S6_FINAL_FILL_REJECTION"
    assert "D2 EVENT_CALENDAR not required: event-blind" in record["specification"]["differences"]
    # The synthetic fixture carries no selections at all: the record says so.
    fixture_record = m0.trial_document(
        M0_RESEARCH_SPECIFICATION,
        M0_SYNTHETIC_FIXTURE,
        base,
        m0.phases_for(sessions, M0_SYNTHETIC_FIXTURE),
    )
    assert fixture_record["configuration"]["owner_selections"] is None
    assert fixture_record["configuration"]["provenance"] == "SYNTHETIC_FIXTURE"
    assert record["configuration"]["provenance"] == "OWNER_SELECTED"
    assert m0.trial_digest(M0_RESEARCH_SPECIFICATION, config, base, phases) != m0.trial_digest(
        M0_RESEARCH_SPECIFICATION, M0_SYNTHETIC_FIXTURE, base, phases
    )
