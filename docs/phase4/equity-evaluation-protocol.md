# Equity evaluation protocol — Breakout Long (and the modules that reuse it)

**Status: PROPOSED / RESEARCH PROTOCOL. No empirical result exists.** This document specifies
*how* the offline equity Brain's first strategy slice would be evaluated once qualified market
data exists. It runs no backtest, claims no alpha, and calibrates no parameter. Every number in
the implemented Breakout Long module is a **proposed research parameter**, not a finding.

**Nothing here is authorized to execute.** Empirical evaluation requires qualified provider data
(**G1/G2 OPEN**, **P1–P9 UNEVALUATED**, **Run B / combined assessment NOT RUN**), and then a
**separate** research authorization per `CLAUDE.md` §8. Passing provider qualification is **not**
blanket research authorization.

---

## 1. Economic hypothesis and horizon

**Hypothesis (to be validated, not assumed):** a liquid U.S. common stock that closes above a
compact consolidation with confirming relative strength and volume continues higher over a
**2–30 trading-day** horizon more often, or by more, than a stated simpler baseline, **after
realistic costs**. The Brain's role ends at a `CandidateIntent`; entry timing, sizing and exit
management belong to later layers (ADR-0026 §16), so this protocol evaluates the **candidate
signal**, paired with a **fixed, pre-declared** exit rule, as a joint object.

**A hypothesis is not a result.** The specification's experiment matrix (spec §23) lists this as
experiment B, and it is unanswered.

## 2. The named baseline comes first

No strategy is evaluated in isolation (spec §22). Breakout Long is compared against a **stated,
simpler alternative** declared before any result is read:

- **Baseline B0 — immediate ranked entry:** buy the same eligible universe ranked by a single
  momentum factor, held for the same horizon with the same exit rule and the same costs. If
  Breakout Long does not beat B0 net of costs, its base/volume/gap machinery has added nothing.
- **Secondary baselines:** buy-and-hold the benchmark; an equal-weight hold of the eligible
  universe. Both include **idle capital** (see §4).

## 3. Point-in-time universe and corporate actions

- **Point-in-time universe membership** as of each decision instant, with **delistings present**
  (survivorship-aware). A security delisted after the decision but active at it is in the universe;
  one delisted before it is not.
- **Corporate actions** (splits, dividends, spinoffs, symbol changes) resolved on the
  point-in-time axis, through the accepted adjustment contract (`AdjustmentMode`, split-only
  forward-base-normalized in this slice). Whether dividend or total-return adjustment is the right
  basis is an **open decision** (see §9).
- **Information profile:** `PROVIDER_REALISTIC_PIT`; `PUBLIC_PIT` is a stricter comparison. Price
  origin stays `PROVIDER_DERIVED` until qualification says otherwise (Q7 `PUBLICLY_UNRESOLVED`).

## 4. Benchmark, portfolio return and idle capital

- **Portfolio-level return**, not average-trade return: capital not deployed earns the declared
  cash rate and is part of the denominator. A strategy that trades rarely is measured on the whole
  book, idle cash included.
- **Benchmark:** a stated broad-market total-return benchmark, plus B0. Report **excess** return
  over each, not gross return alone.
- **Inherited and manual positions** are excluded from the strategy's measured book and accounted
  separately; the strategy is judged on the positions **it** opened.

## 5. Timestamps — signal, availability, earliest execution

Three distinct instants, never collapsed:

- **signal time** — the close of the evaluation session (the decision instant, `as_of`);
- **input-availability time** — when every required input was actually knowable under the resolved
  profile (the reality gate enforces this at decision time);
- **earliest-execution time** — the first session open at which an order could have been placed,
  i.e. **the next session** after the signal. Entry, slippage and fills are modeled from there,
  never from the signal bar's own close.

## 6. Train / validate / final, and overlap

- **Split the history** into an in-sample development window, an out-of-sample validation window,
  and a **locked final** window untouched until the parameters are frozen. The final window is
  read **once**.
- **Walk-forward** across the development/validation boundary; **purge and embargo** around each
  test fold so a 30-day holding period cannot leak across the boundary.
- **Overlapping holding periods** are handled explicitly (many candidates open within one holding
  window): report both per-trade and calendar-time aggregations, and size the multiple-testing
  denominator by the number of **distinct** parameter trials, recorded not remembered (spec §22).

## 7. Costs, fills and capacity

- **Commissions**, a **bid/ask spread** assumption, **slippage** as a function of participation,
  and **fills** modeled at the next-session open (or a stated VWAP window), never at an
  unachievable price.
- **Gap stress:** a breakout that gaps far above the base is entered at the gapped price or skipped
  by the entry-gap rule — never filled at the base high.
- **Capacity:** report the average-dollar-volume distribution of entries and the participation rate
  implied by the strategy capital; a signal that only works below a size the book cannot deploy is
  recorded as capacity-limited.

## 8. Metrics and decomposition

Report, per window and net of costs: **expectancy**, **hit rate**, **average win/loss**,
**maximum drawdown**, **turnover**, **exposure** (gross and net), **capacity**, and the excess over
each baseline. Decompose by **market regime**, **sector**, and **factor** (raw vs relative vs
residual momentum — spec §5.2, experiment A). Report an estimate of the **information-time
limitation** (date-granular provider timing cannot establish an intraday instant).

## 9. Proposed decisions this protocol surfaces (not made here)

Each is a research parameter or contract choice the specification leaves open; **none is an
accepted production rule**, and each would be fixed by a reviewed decision before promotion:

- every Breakout Long threshold: `trend_sessions`, `base_sessions`, `relative_strength_sessions`,
  `volume_baseline_sessions`, `liquidity_sessions`, `high_proximity_sessions`,
  `max_base_compactness`, `min_relative_volume`, `min_relative_strength`, `max_entry_gap`,
  `min_average_dollar_volume`;
- the **production factor formula** behind each §5.1 family (the module computes candidate forms;
  the spec names families, not formulas);
- the **adjustment basis** (split-only vs dividend vs total-return) for a momentum breakout;
- the **benchmark** security and the **cross-sectional rank** requirement (rank needs a
  universe-wide scanner run, out of this slice);
- the **event evidence source** (no accepted earnings/event entity exists — Phase 3B, G4) and the
  **sector classification** source (no sector data in A1);
- the **market-permission mapping** (how a regime maps to permit/defer/deny — spec §18);
- the **exit rule** paired with the entry for evaluation (exit management is a later layer).

## 10. Rejection and promotion criteria (proposed)

- **Reject** if Breakout Long does not beat B0 net of costs on validation, if its edge is confined
  to one regime or a handful of names, if it is capacity-limited below the strategy capital, or if
  the parameter neighbourhood is unstable.
- **Promote** (to the next lifecycle stage, never to trading) only on the locked final window,
  read once, with a governance packet a human reads (spec §10, §12, §25). **No profitable-trade
  count is a proof of edge**, and reaching a lifecycle stage is never automatic (spec §10).

**No result is asserted anywhere in this document, and none exists.**
