# Options research and future-architecture brief

**Status: PROPOSED / RESEARCH ONLY.** This document researches and designs; it authorizes and
implements nothing. **No options runtime, contract-selection code or options schema exists or is
authorized** (`CLAUDE.md` §4.14), no `CandidateIntent` field is added, no ADR is amended, and
nothing is wired into execution. It relies on **public primary-source documentation only**: no paid
subscription, account connection, API market-data request or historical chain download was made.

**The first equity release does not depend on this document.** Options are prepared here so that a
later, separately authorized decision has a starting point — not made a prerequisite for equities.

**Documented fact vs design recommendation.** Every external claim carries a source URL and an
access date (all accessed **2026-09-10**), and is marked **[fact]** where it restates published
documentation or **[recommendation]** where it is our proposed design. Bounded intentionally: this
answers a first research question and maps prerequisites; it is not a survey.

**Bounding assumption — bounded risk is not proven profit.** That an option's maximum loss is
defined at entry does **not** make a purchased call, put or debit spread profitable or appropriate.
Time decay, the bid/ask spread on every leg, and adverse implied-volatility moves are real costs,
and the brief treats every structure below as a **hypothesis to be tested at comparable risk after
realistic costs**, never as an improvement assumed because loss is capped.

---

## 0. The first research question

> **For the same eligible underlying signal, when do shares, a purchased call/put, or a debit
> vertical spread improve outcomes at comparable risk after realistic costs?**

This is the question a later research phase must answer, and it is **unanswered here**. The honest
shape of the answer, stated as **[recommendation]**:

- **Compare at comparable risk, not comparable notional.** A call controlling 100 shares is not
  comparable to 100 shares; the comparison must equalise dollars-at-risk (premium at risk vs the
  stop-defined risk of the share trade), then compare net outcomes.
- **The candidate levers are entry cost, defined risk, convexity and decay.** Shares have no decay
  and no convexity; a long call/put pays premium (theta, vega exposure) for convexity and a floor;
  a debit spread reduces premium and vega exposure by capping upside. Which wins is **regime-,
  horizon- and cost-dependent**, and must be measured per the methodology in §C.
- **The honest default expectation is "usually shares, sometimes options."** For a 2–30 day
  momentum continuation thesis, the drag of spread + theta on a long option is large relative to the
  expected move; options are most plausibly justified around **defined event risk** or when a
  **hard floor** on a gap-prone name is worth its cost. This is a hypothesis to test, not a finding.

**Initial proposed scope**, and its limits: **purchased calls and puts**, and **debit vertical
spreads as a separate, later capability**. **Explicitly out of scope:** naked/short option selling,
0DTE, any volatility-selling program, and complex or multi-leg expansion beyond a two-leg debit
spread. Bounded-risk-at-entry is the reason these are *considered*, never a claim they work.

---

## A. Architecture — how future options support could fit the accepted design

The accepted three-layer handoff (ADR-0026 §16) is **Brain → portfolio/risk → execution**. Options
map onto it **without moving the boundary**; each allocation below is **[recommendation]** and
labelled PROPOSED where accepted authority is absent.

| Question class | Equity today | Options (PROPOSED) |
|---|---|---|
| **Why does the opportunity exist / why now** (Brain) | the underlying `CandidateIntent` | **unchanged** — the Brain still evaluates the **underlying** and emits a `CandidateIntent`; it does **not** pick an instrument |
| **Which instrument / structure** | n/a (shares implied) | **PROPOSED new layer, between Brain and portfolio/risk**: an *instrument-selection* step that reads the `CandidateIntent` plus options context and proposes shares / call / put / debit spread. It is **deterministic**, and it is **not** the Brain |
| **Can the portfolio own it / how much risk / how many** (portfolio & risk) | deterministic risk engine | **extended, not relocated**: risk must budget delta, gamma, vega, theta and premium-at-risk, and combined equity+options exposure |
| **How to route / protect / reconcile** (execution) | `BrokerAdapter`, ADR-0004 identity | **extended**: multi-leg order construction, per-leg fills, exercise/assignment/expiration handling, and stock positions arising from assignment |

**The locked boundary is preserved.** The Brain's terminal output stays `CandidateIntent`, which
**may never** carry a size, an order, a route or an instrument instruction (ADR-0026 §2.2). Instrument
selection is a **downstream deterministic decision**, exactly as sizing is — so "AI cannot choose to
buy a call" stays true by the same structural argument that keeps "AI cannot size" true.

**Exercise, assignment and expiration** are **execution-and-risk** responsibilities, never the
Brain's — the analogue of the live pre-submit borrow recheck. Assignment produces a **stock
position** [fact: OIC, options-exercise / splits FAQ], which the existing equity position and
reconciliation machinery must then own.

**Equity-only assumptions that could cause future rework** (identified, not fixed — **no change is
made to any of them here**):

- `CandidateIntent`'s trade thesis assumes a **share** invalidation level and a single instrument;
  an options structure has its own P&L geometry. **Do not** add an options field to `CandidateIntent`
  — the instrument-selection layer consumes the underlying intent and produces its **own** typed
  record in a future, separately authorized slice.
- Risk parameters (ADR-0026 §24) are share-denominated (planned risk %, position %). Options need
  premium-at-risk and Greek budgets; these are **new risk contracts**, not edits to the Brain.
- Execution identity (ADR-0004) is per-order; a spread is **multi-leg** with partial-fill and
  leg-risk semantics that the identity and reconciliation model must be extended to cover.

**What this section does not do:** it changes `CandidateIntent`, adds no options field or runtime
class, adds no empty plugin framework, amends no accepted ADR, and wires nothing into execution.
**The smallest future extension** [recommendation]: a **read-only options context record** (§B) and
a **deterministic instrument-selection evaluator** that, given an underlying `CandidateIntent` and
that context, returns `SHARES` or an explicitly-typed option structure proposal — behind its own
ADR, with its own gates, producing no order.

---

## B. Data readiness — what options research and operation require

**None of this data is supplied by the current equity provider, and equity qualification does not
qualify options data.** Sharadar (the equity qualification subject) is **not** claimed to provide any
of the below. Historical options data is a **distinct, specialized dataset** [fact].

**Required vs helpful.** *Required* is what a defensible historical evaluation cannot omit; *helpful*
improves it.

| Field / dataset | Need | Note |
|---|---|---|
| **Timestamped historical option chains with bid/ask quotes** | **required** | consolidated U.S. options quotes originate from **OPRA** [fact: Cboe/OPRA]; realistic fills need the quote, not just a last price |
| **Expired / delisted contracts** | **required** | a survivorship-free history must include contracts that expired; vendors offer this as historical/expired data [fact: Cboe DataShop] |
| **Contract identifiers, multiplier, deliverable, adjustments** | **required** | the deliverable and multiplier **change** on corporate actions (§D); an evaluation keyed to a stale deliverable is wrong |
| **Underlying prices, dividends, corporate actions** | **required** | already in the equity PIT plane; the join must be point-in-time |
| **Quote condition, staleness and liquidity flags** | **required** | wide/locked/crossed quotes and stale NBBO must be detectable, or fills are fiction |
| **Implied volatility / Greeks: source, timestamp, calculation assumptions** | **helpful (required if used)** | if consumed, the **model, inputs (rate, dividend), and snapshot time** must be recorded; vendors ship optional calc/IV/Greeks snapshots (e.g. EOD and 3:45 PM ET) [fact: Cboe DataShop] |
| **Open interest with publication timing** | **helpful** | OI is **not** real-time; it is published on a lag, and no strategy may assume same-day OI [recommendation, consistent with OPRA/exchange practice] |
| **Exercise style, settlement type, trading & expiration calendars** | **required** | equity options are **American-style, physically settled**; most index options are **European, cash-settled** [fact: OIC options-exercise FAQ] |
| **Licensing, coverage and acquisition cost** | **required before purchase** | **not established here**; a separate licensing/qualification decision (the options analogue of G1/G3) is required |

**Data readiness is a gate, not a checkbox.** The options analogue of P1–P9 (chain completeness,
expired-contract coverage, quote-timestamp fidelity, deliverable-adjustment correctness,
IV/Greek provenance) must be **defined and run** on real licensed options data before any options
backtest is believed. **None of it is done.**

---

## C. Research methodology (PROPOSED)

All **[recommendation]**, and all subject to §E gates. Consistent with the equity protocol
(`equity-evaluation-protocol.md`): point-in-time, survivorship-aware, costed, baseline-first.

- **Expiration selection relative to horizon:** for a 2–30 day thesis, test expirations that bracket
  the horizon with a stated buffer beyond it; never hold to an expiration inside the thesis window
  without a rule for it.
- **Strike / delta and liquidity selection:** select by a stated delta band and a **liquidity
  screen** (quoted size, spread width, OI floor); reject illiquid strikes rather than assuming a
  mid fill.
- **Entry / exit and pre-expiration policy:** a fixed rule for closing or rolling before expiration,
  and an explicit policy that **avoids letting a position ride into expiration** unless the design
  intends assignment.
- **Event exposure and volatility scenarios:** test entries around earnings/events separately, and
  stress **implied-volatility changes** (a long option can lose on a correct directional call if IV
  falls). Theoretical pricing (e.g. Black–Scholes) may support **scenario analysis only** — it
  **cannot** establish executable historical returns.
- **Execution assumptions:** model fills against **bid/ask**, per leg, with a participation-based
  slippage; model **incomplete multi-leg fills** (one leg fills, the other does not) as a real
  outcome, not an impossibility.
- **Costs for every leg:** commissions and spread on **each** leg of a spread, plus assignment/
  exercise fees where applicable.
- **Comparison with the underlying at comparable risk:** every option result is reported **beside**
  the share trade on the same signal at equalised dollars-at-risk, net of costs — answering §0.
- **Return accounting:** report **return on premium**, **return on allocated capital**, **drawdown**
  and **economic (delta-equivalent) exposure** as **distinct** numbers; a large return on a small
  premium is not a large return on the book.

**Do not** infer historical option profits from stock bars, and **do not** read a payoff diagram as
a realized return.

---

## D. Risk and operational prerequisites (PROPOSED)

- **Combined exposure:** equity + options must be budgeted **together**; an options overlay is not a
  separate book for risk purposes.
- **Greek sensitivities:** delta, gamma, vega and theta must be measured and limited; premium-at-risk
  and per-underlying exposure caps are required contracts.
- **Assignment and exercise:** equity options are **American-style and physically settled**, so a
  short leg can be **assigned early**, producing a stock position [fact: OIC]. **Automatic exercise
  by exception** at expiration exercises options **$0.01 or more in the money** unless instructed
  otherwise, and this is a procedure between OCC and clearing members — **the broker/customer must
  still communicate exercise instructions** [fact: OIC options-exercise FAQ; OCC]. The system must
  therefore hold explicit expiration instructions, not rely on defaults.
- **Expiration / pin risk:** a price sitting near the strike at expiration makes exercise/assignment
  uncertain; the operational design must handle a position that may or may not be assigned.
- **Contract adjustments:** splits, reverse splits, special distributions, mergers and spinoffs can
  change the **deliverable, multiplier and strike** via an OCC adjustment panel under OCC by-laws;
  ordinary dividends generally do **not** adjust [fact: OIC splits/mergers/spinoffs FAQ; OCC]. The
  data join and risk model must track the **adjusted** deliverable, not the original.
- **Broker liquidation and buying power:** a broker may take **protective action** for projected
  post-settlement margin, including lapsing long in-the-money options and liquidating expiring
  positions, typically **the business day following expiration** (IBKR states liquidations of U.S.
  positions begin ~9:40 AM ET the following business day) [fact: IBKR — see Sources; page not
  fetchable in this session, quoted via the search index]. Settlement is now **T+1** for equities
  [fact: SEC Rule 15c6-1, effective 2024-05-28], which tightens buying-power timing.
- **Multi-leg failures and reconciliation:** a partially filled spread is a real, risk-bearing state
  the reconciliation model must represent.

**"Defined risk" is conditional, not unconditional.** A debit spread's payoff-diagram maximum loss
assumes both legs are filled as intended, held as intended, and **not** disrupted by early
assignment, a contract adjustment, a gap, or a broker liquidation. Presenting the payoff-diagram
maximum as an operational guarantee would be false; the operational maximum loss depends on all of
the above.

---

## E. Future promotion gates (PROPOSED)

Evidence required **before** each step. No step is authorized; **no profitable-trade count is proof
of an edge**, and **equity pilot success does not qualify options**.

1. **Before options implementation:** an accepted options ADR (architecture, the instrument-selection
   layer, the new risk contracts), an **options data-readiness decision** (the §B analogue of
   G1/G3), and a licensing decision. No code before this.
2. **Before empirical evaluation:** licensed, qualified historical options data that passes a defined
   options-quality gate (§B); the §C methodology reviewed; a named baseline (**shares on the same
   signal**) fixed.
3. **Before broker rehearsal:** offline evaluation showing the structure beats shares at comparable
   risk net of costs on a locked out-of-sample window; a modeled exercise/assignment/expiration and
   multi-leg-fill design; combined Greek and premium-at-risk limits defined.
4. **Before a limited live options pilot:** IBKR **paper** rehearsal of the full lifecycle
   (entry → partial fills → adjustment → expiration/assignment → reconciliation); the repository
   **private** again (`CLAUDE.md` §3); a working Gate-2 for live; explicit written human sign-off.
   Live options remain **HARD-DISABLED** until then, exactly as equities.

---

## Conclusion

- **What can be researched now:** public options mechanics, the instrument-selection architecture,
  the data-readiness inventory, and the methodology — **all done here, as design only**.
- **What must wait:** any options code, any options data purchase or request, any backtest, and any
  broker activity — each behind its own gate (§E).
- **The smallest later options slice:** a **read-only options context record** plus a
  **deterministic instrument-selection evaluator** over an existing underlying `CandidateIntent`,
  producing `SHARES` or a typed option-structure proposal and **no order**, behind its own ADR.
- **Explicit dependencies:** an options ADR; an options data-licensing and readiness decision; the
  equity Brain foundation this brief sits beside; and the risk-engine extension for Greeks and
  premium-at-risk.
- **Unresolved questions:** does any option structure beat shares at comparable risk after costs for
  this horizon (§0); which vendor/coverage/cost for options data; the exact instrument-selection
  contract; the Greek and premium-at-risk budgets; and the pin/assignment operational policy.
- **Confirmation:** **the first equity launch does not depend on completing this options work.**

**No alpha is claimed. No options data is qualified. No options runtime is implemented. Options
execution and live trading remain NOT AUTHORIZED, and live trading remains HARD-DISABLED.**

---

## Sources

All accessed **2026-09-10**. **[fact]** = restates the cited documentation; the brief's design
choices are **[recommendation]** in-line above.

- The Options Industry Council (OIC), *Options Exercise* FAQ — American/European style, physical
  settlement of equity options, $0.01 automatic-exercise-by-exception threshold, exercise
  instructions: <https://www.optionseducation.org/referencelibrary/faq/options-exercise>
- OIC, *Options Assignment* FAQ: <https://www.optionseducation.org/referencelibrary/faq/options-assignment>
- OIC, *Splits, Mergers, Spinoffs & Bankruptcies* FAQ — contract adjustments and the adjustment
  panel: <https://www.optionseducation.org/referencelibrary/faq/splits-mergers-spinoffs-bankruptcies>
- OIC, *Understanding Options Greeks* — delta/gamma/theta/vega and implied volatility:
  <https://www.optionseducation.org/advancedconcepts/understanding-options-greeks>
- The Options Clearing Corporation (OCC), *Exercise & Assignment* primer (PDF):
  <https://www.theocc.com/getmedia/eebc0b12-73d0-40f4-a024-020f55cb2d0e/OCC-Primer-Exercise-Assiginment-F.pdf>
- OCC, *By-Laws and Rules* (contract adjustments authority; PDF):
  <https://www.theocc.com/getmedia/9d3854cd-b782-450f-bcf7-33169b0576ce/occ_rules.pdf>
- OCC Information Memo #54262, cash-dividend adjustment policy:
  <https://infomemo.theocc.com/infomemos?number=54262>
- Cboe DataShop — bulk OPRA-reported options trade/quote data, expired contracts, optional IV/Greeks
  calcs (capability description only; coverage/cost **not** verified here):
  <https://datashop.cboe.com/options-data> and <https://datashop.cboe.com/options-price-bulk-data>
- Cboe Options Lite — consolidated U.S. options (OPRA) feed description:
  <https://www.cboe.com/data/market-data-services/cboe-options-lite/>
- Interactive Brokers, *Delivery, Exercise and Corporate Actions* (returned HTTP 403 to automated
  fetch this session; cited via the search index for the liquidation-timing and lapse facts, to be
  re-verified before any options work): <https://www.interactivebrokers.com/en/trading/delivery-exercise-actions.php>
- Interactive Brokers, *Exercise and Assignment* trading lesson (also 403 to automated fetch this
  session): <https://www.interactivebrokers.com/campus/trading-lessons/exercise-and-assignment/>
- Interactive Brokers, *Order Types and Algos*:
  <https://www.interactivebrokers.com/en/trading/ordertypes.php>
- U.S. SEC, *Shortening the Securities Transaction Settlement Cycle* (Rule 15c6-1, T+1 effective
  2024-05-28): <https://www.sec.gov/files/rules/final/2023/34-96930.pdf> and investor bulletin
  <https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins/new-t1-settlement-cycle-what-investors-need-know-investor-bulletin>
- FINRA, *Day Trading* / pattern-day-trader margin, and the new intraday-margin requirements
  (Regulatory Notice 26-10): <https://www.finra.org/investors/investing/investment-products/stocks/day-trading>
  and <https://www.finra.org/rules-guidance/notices/26-10>

**Access limitation recorded.** The two Interactive Brokers pages above returned **HTTP 403** to the
automated fetch used in this session; their facts are quoted from the search index and are marked to
be **re-verified from the live pages before any options implementation**. No other cited source was
inaccessible.
