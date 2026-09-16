"""The M0 report: trades, equity, refusals, both terminal ledgers, determinism evidence.

Every page carries the label the result carries (``SYNTHETIC / EXPLORATORY_HINDSIGHT`` for a
synthetic run) and the specification's differences and limitations verbatim, so nothing in it
can be read as a production figure, a qualification, or a promotion readiness.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from kalpamani.data.exploratory.m0 import M0_RESEARCH_SPECIFICATION, Ledger, M0Result
from kalpamani.data.exploratory.vocabulary import ExploratoryLimitation

_BIAS_STATEMENT = " ".join(
    (
        "This run ASSUMES historical availability (AS_DATED): today's row versions stand in for",
        "every historical version (REVISION_LOOKAHEAD); today's exchange, category and listing",
        "attributes stand in for every past session (CURRENT_ATTRIBUTE_LOOKAHEAD); no",
        "scheduled-event evidence exists (EVENT_BLIND); a delisted position is valued at its last",
        "available close in the optimistic ledger (TERMINAL_VALUATION_OPTIMISTIC); date-granular",
        "data establishes no intraday instant (NO_INTRADAY_INSTANT); the benchmark is built from",
        "the universe itself (BENCHMARK_SELF_REFERENCE). No figure here satisfies P1-P9, any G2",
        "criterion or any promotion criterion; no period is point-in-time qualified; no strategy",
        "profitability is established.",
    )
)

_PERIODS_NOTE = " ".join(
    (
        "Two labelled periods per window. EVALUATION: from the close before the window's first",
        "session to the close of its last session; the strategy return and the benchmark return",
        "cover exactly those instants, on the benchmark series of the ledger's terminal policy.",
        "LIQUIDATION-INCLUSIVE: extended through the following purge or tail, where positions may",
        "only close; its benchmark figure covers the same extended instants. Trade statistics",
        "count the window's trades wherever they closed. A benchmark return is blank where a level",
        "is",
        "missing or zero -- never a zero standing in for it.",
    )
)

_METRIC_COLUMNS = (
    "window",
    "evaluation",
    "trades",
    "winners",
    "losers",
    "expectancy",
    "hit rate",
    "net P&L",
    "max DD (eval)",
    "turnover",
    "avg exposure",
    ">1R losses",
    "worst trade",
    "terminal",
    "open at end",
    "end equity (eval)",
    "return (eval)",
    "benchmark (eval)",
    "liquidation end",
    "end equity (liq)",
    "return (liq)",
    "benchmark (liq)",
    "max DD (liq)",
)
_TRADE_COLUMNS = (
    "security",
    "window",
    "entry",
    "shares",
    "fill",
    "stop",
    "planned risk",
    "exit",
    "reason",
    "exit shares",
    "exit fill",
    "cash in lieu",
    "P&L",
    "unrealized",
    "R",
    "held",
    "missing bars",
    "splits",
)


def _row(cells: tuple[object, ...]) -> str:
    return "| " + " | ".join("" if cell is None else str(cell) for cell in cells) + " |"


def _ledger_section(ledger: Ledger) -> list[str]:
    lines = [f"### Ledger `{ledger.label}`", ""]
    lines.append(_row(_METRIC_COLUMNS))
    lines.append("|" + "---|" * len(_METRIC_COLUMNS))
    for m in ledger.metrics:
        lines.append(
            _row(
                (
                    m.window.value,
                    f"{m.evaluation_start}..{m.evaluation_end}",
                    m.trades,
                    m.winners,
                    m.losers,
                    m.expectancy,
                    m.hit_rate,
                    m.net_pnl,
                    m.max_drawdown,
                    m.turnover,
                    m.average_exposure,
                    m.losses_beyond_one_r,
                    m.worst_trade_pnl,
                    m.terminal_events,
                    m.open_at_end,
                    m.end_equity,
                    m.return_fraction,
                    m.benchmark_return_fraction,
                    m.liquidation_end,
                    m.liquidation_end_equity,
                    m.liquidation_return_fraction,
                    m.liquidation_benchmark_return_fraction,
                    m.max_drawdown_through_liquidation,
                )
            )
        )
    exits = Counter(t.exit_reason.value for t in ledger.trades)
    skips = Counter(s.reason.value for s in ledger.skips)
    journal = Counter(x.kind.value for x in ledger.transactions)
    lines += [
        "",
        f"Exits: {dict(sorted(exits.items()))}. Skips: {dict(sorted(skips.items()))}. "
        f"Sessions held with a missing bar: {ledger.missing_bar_held_sessions}; exits deferred "
        f"for a missing execution bar: {ledger.exits_deferred_no_bar}. "
        f"Journal: {dict(sorted(journal.items()))}.",
        "",
        _row(_TRADE_COLUMNS),
        "|" + "---|" * len(_TRADE_COLUMNS),
    ]
    for t in ledger.trades:
        lines.append(
            _row(
                (
                    t.security_id,
                    t.window.value,
                    t.entry_session,
                    t.shares,
                    t.entry_fill,
                    t.stop_level,
                    t.planned_risk,
                    t.exit_session,
                    t.exit_reason.value,
                    t.exit_shares,
                    t.exit_fill,
                    t.cash_in_lieu,
                    t.realized_pnl,
                    t.unrealized_pnl,
                    t.r_multiple,
                    t.held_sessions,
                    t.missing_bar_sessions,
                    "; ".join(f"{e.ratio}:1 on {e.ex_date}" for e in t.split_events) or "",
                )
            )
        )
    lines.append("")
    return lines


def render_markdown(result: M0Result, *, determinism: tuple[str, str] | None = None) -> str:
    """The report. ``determinism`` is the pair of digests of two independent runs, if taken."""
    label = (
        "SYNTHETIC / EXPLORATORY_HINDSIGHT"
        if result.data_kind.value == "SYNTHETIC"
        else "EXPLORATORY_HINDSIGHT"
    )
    lines = [
        f"# M0 exploratory run — **{label}** — `{result.specification_version}`, "
        f"trial {result.trial}",
        "",
        f"**{label}.** {_BIAS_STATEMENT}",
        "",
        f"- trial digest (frozen before any development bar): `{result.trial_digest}`",
        f"- input set digest: `{result.input_set_digest}` · dataset digest: "
        f"`{result.dataset_digest}` · benchmark digest: `{result.benchmark_digest}`",
        f"- result digest: `{result.digest}`",
    ]
    if determinism is not None:
        first, second = determinism
        lines.append(
            f"- determinism: two independent runs produced `{first[:16]}…` and `{second[:16]}…` — "
            + ("**identical**" if first == second else "**DIFFERENT**")
        )
    lines += ["", "## Differences from the accepted Breakout Long module", ""]
    lines += [f"- {d}" for d in M0_RESEARCH_SPECIFICATION.differences]
    lines += ["", "## Declared limitations", ""]
    lines += [f"- `{item.value}`" for item in ExploratoryLimitation]
    lines += [
        "",
        "## Configuration",
        "",
        "```json",
        json.dumps(result.configuration, indent=1, sort_keys=True),
        "```",
        "",
    ]
    lines += ["## Phases", "", "```json", json.dumps(result.phases, indent=1), "```", ""]
    lines += ["## Periods", "", _PERIODS_NOTE, ""]
    lines += ["## Breakout Long — both terminal ledgers", ""]
    for ledger in result.ledgers:
        lines += _ledger_section(ledger)
    lines += ["## Baseline B0 — both terminal ledgers", ""]
    for ledger in result.baselines:
        lines += _ledger_section(ledger)
    lines += ["## Sensitivities (optimistic ledger)", ""]
    for ledger in result.sensitivities:
        lines += _ledger_section(ledger)
    lines += [
        "## Equal-weight hold (the benchmark index itself; no costs)",
        "",
        "```json",
        json.dumps(result.equal_weight_hold, indent=1),
        "```",
        "",
    ]
    lines += [
        "## Universe census (first and last decided sessions)",
        "",
        "```json",
        json.dumps([result.census[0], result.census[-1]] if result.census else [], indent=1),
        "```",
        "",
    ]
    lines += [f"**{label}.** Software behaviour only. {_BIAS_STATEMENT}", ""]
    return "\n".join(lines)


def write_report(
    result: M0Result, directory: Path, *, determinism: tuple[str, str] | None = None
) -> dict[str, Path]:
    """Write the markdown report and the canonical JSON result. Returns the paths."""
    directory.mkdir(parents=True, exist_ok=True)
    markdown = directory / "M0-REPORT.md"
    document = directory / "M0-RESULT.json"
    markdown.write_text(
        render_markdown(result, determinism=determinism), encoding="utf-8", newline="\n"
    )
    document.write_text(
        json.dumps(result.document(), indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {"markdown": markdown, "json": document}


def summary(result: M0Result) -> dict[str, Any]:
    """A small machine-readable summary for tests and records."""
    return {
        "label": result.document()["label"],
        "trial_digest": result.trial_digest,
        "result_digest": result.digest,
        "ledgers": {
            ledger.label: {
                "trades": len(ledger.trades),
                "exits": dict(sorted(Counter(t.exit_reason.value for t in ledger.trades).items())),
                "skips": dict(sorted(Counter(s.reason.value for s in ledger.skips).items())),
                "missing_bar_held_sessions": ledger.missing_bar_held_sessions,
            }
            for ledger in (*result.ledgers, *result.baselines, *result.sensitivities)
        },
        "windows": {
            f"{ledger.label}/{m.window.value}": {
                "evaluation": [m.evaluation_start.isoformat(), m.evaluation_end.isoformat()],
                "return_fraction": str(m.return_fraction),
                "benchmark_return_fraction": None
                if m.benchmark_return_fraction is None
                else str(m.benchmark_return_fraction),
                "liquidation_end": m.liquidation_end.isoformat(),
                "liquidation_end_equity": str(m.liquidation_end_equity),
                "liquidation_benchmark_return_fraction": None
                if m.liquidation_benchmark_return_fraction is None
                else str(m.liquidation_benchmark_return_fraction),
                "open_at_end": m.open_at_end,
            }
            for ledger in result.ledgers
            for m in ledger.metrics
        },
    }


__all__ = ["render_markdown", "summary", "write_report"]
