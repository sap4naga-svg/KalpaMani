# Phase 3 — Point-in-Time Data Foundation — Charter

## STATUS: **PLANNING — IN REVIEW**

**Phase 3 implementation is NOT STARTED and NOT AUTHORIZED.**
**No data provider has been purchased, contracted, trialled or credentialed.**

This document and its siblings under `docs/phase3/` are a plan. Beginning implementation
requires explicit written authorization per [CLAUDE.md](../../CLAUDE.md) §8.

| | |
|---|---|
| authored | 2026-08-26 |
| base commit | `210f768bb8763f78d4a02a70757f26c37457323e` |
| decision record | [ADR-0005](../decisions/ADR-0005-point-in-time-data-architecture.md) — **Proposed** |
| authority | Blueprint V2.1 §18 (Phase 0 data feasibility), §17, §19, §26 |

---

## 1. Why this phase exists

Blueprint V2.1 §18 says it in four words: **"Do not skip."**

> *The hardest data problems are point-in-time analyst revisions and realistic historical
> short borrow conditions — not ordinary OHLCV.*

Everything downstream of Phase 3 — the scanner, the factor composites, every backtest,
every performance claim — is a function of the data underneath it. A look-ahead bug does
not announce itself. It produces a *better* result, which is precisely why it survives
review: nobody investigates a Sharpe ratio that went up.

Phase 2 certified that KalpaMani can put one order at a broker and fail closed when it
cannot prove what it owns. Phase 3 is the analogous claim one layer down: **KalpaMani can
state what it knew, and when it knew it, and fail closed when it cannot.**

## 2. Mission

Establish a trustworthy point-in-time data foundation serving:

- research and factor development
- deterministic scanning
- factor ranking
- backtesting
- forward paper trading
- later live operation

...such that a query for a historical date returns **only what was actually available at
that date**, and any query that cannot honour that guarantee **fails rather than guesses**.

## 3. What Phase 3 must structurally prevent

Each item below is a defect class, not a warning. The plan is judged on whether it makes
these hard to commit, not on whether it advises against them.

| # | Defect | How it enters | Where the plan addresses it |
|---|---|---|---|
| 1 | **look-ahead bias** | any query returning data unavailable at `as_of` | [PIT contract](pit-data-contract.md) §1, mandatory `as_of` |
| 2 | **survivorship bias** | today's universe used to simulate an earlier date | [contract](pit-data-contract.md) §11, `universe_membership` |
| 3 | **revision leakage** | restated financials shown before they were published | explicit revision views, [contract](pit-data-contract.md) §6 |
| 4 | **corporate-action leakage** | split/dividend factors applied before announcement | keyed adjusted artifacts, [contract](pit-data-contract.md) §8 |
| 5 | **stale-universe simulation** | current-membership snapshot reused across history | historical universe reconstruction test |
| 6 | **pre-publication use** | data used before it could have been known | conservative-lag policy, fail-closed |
| 7 | **silent history rewriting** | vendor backfill overwriting an earlier observation | immutable bronze layer, append-only revisions |
| 8 | **information-set confusion** | a backfill treated as though we held it all along | explicit profiles, [contract](pit-data-contract.md) §3 |

**Defect class 8 was added in revision 2**, after review found that the first draft's single
"available time" silently answered three different questions. It is the subtlest of the eight:
nothing about a backfilled row looks wrong, and whether it belongs in a 2015 query depends
entirely on whose information set is being simulated.

## 4. Non-goals — explicitly out of scope for Phase 3

Phase 3 is **data infrastructure, not strategy**. None of the following is implemented,
designed to completion, or authorized here:

> Breakout · Pullback · PEAD strategy logic · short-selling logic · portfolio allocation ·
> the deterministic risk engine · AI Research Agent · AI Challenger Agent · order
> generation · any change to Phase-1 or Phase-2 execution code · live trading

`LIVE_TRADING_HARD_DISABLED` remains `True`. Phase 3 touches no brokerage code, and by
construction cannot: the PIT layer has no `BrokerAdapter` dependency and no order path.

Phase 3 also does not **purchase** anything. Provider selection is proposed, evidenced and
costed here; committing money is a separate, explicitly human decision (§7 below).

## 5. Phase numbering — this repository versus Blueprint §21

This is stated plainly because the two numbering schemes differ, and a reader who assumes
they match will misread both.

| Blueprint §21 roadmap | This repository |
|---|---|
| 0. Data feasibility | — |
| 1. Data + factor foundation | **Phase 3 (this plan)** — the data half |
| 2. Breakout engine | not started |
| 3. Pullback + PEAD | not started |
| 4. Portfolio / risk | not started |
| 5. Broker + automation | **Phases 1–2, complete and certified** |
| 6–9. AI layer, hardening, paper run, micro-live | not started |

**The repository deliberately ran Blueprint roadmap phase 5 first.** Broker connectivity and
the order lifecycle were built and certified before the data foundation existed.

That reordering was sound and should be recorded as such rather than quietly normalised: the
order path is the only part of the system that can lose money by acting, and proving it
*fails closed* — with zero strategy logic capable of driving it — cost nothing and
established the guardrails ([ADR-0003](../decisions/ADR-0003-broker-side-order-controls-are-not-safety-invariants.md),
[ADR-0004](../decisions/ADR-0004-deterministic-order-identity-idempotency-and-execution-lifecycle.md))
before anything could exercise them.

It also leaves a real debt, which this charter names rather than hides: **the system is
order-capable and data-blind.** Blueprint §21 phases 0–1 have not been done. Phase 3 is
that work, arriving out of order. Nothing about the certified execution plumbing depends on
data, so nothing is invalidated — but no claim about *strategy* may be made until the data
underneath it is point-in-time, and none has been.

This is a sequencing observation, not an architectural deviation: Blueprint §21 is a
roadmap with "typical windows", not part of the locked §24 specification. No ADR is
required to have reordered it. One is required to record the resulting data contract, and
that is ADR-0005.

## 6. Structure of the plan

| Document | Answers |
|---|---|
| this charter | why, scope, gates, authorization |
| [pit-data-contract.md](pit-data-contract.md) | what "point-in-time" means here, exactly; the query contract |
| [data-domain-inventory.md](data-domain-inventory.md) | which data domains, which fields, which are blocking |
| [provider-evaluation.md](provider-evaluation.md) | who sells it, what it costs, what is verified |
| [provider-source-register.md](provider-source-register.md) | **the evidence** — every provider claim, with a retrievable source |
| [conceptual-schema.md](conceptual-schema.md) | the data contracts, vendor-neutral |
| [data-quality-plan.md](data-quality-plan.md) | the deterministic checks and their severities |
| [reproducibility-and-provenance.md](reproducibility-and-provenance.md) | the research manifest |
| [implementation-plan.md](implementation-plan.md) | 3A/3B/3C/3D, acceptance criteria, approvals |

## 7. Gates and required human authorizations

Phase 3 is split so that the parts blocked on money or on unavailable data cannot block the
parts that are not.

```
3A  security master · calendars · OHLCV · corporate actions · universe history
        gate: no vendor spend beyond a low-cost individual subscription
3B  filings · fundamentals · earnings timing · analyst estimates and revisions
        gate: PIT ESTIMATES ARE BLOCKING -- see below
3C  borrow availability and fee history · short-data qualification
        gate: SHORT RESEARCH IS FORBIDDEN UNTIL THIS PASSES
3D  LEAN integration · research manifests · data-quality blocking gates
```

Each of these is a separate written authorization. **Revision 2 adds A2 and A4**, after
review found the first draft had no licensing gate and no decision point for the
information-set profile.

| # | Authorization | Required before |
|---|---|---|
| A1 | begin Phase 3A implementation | writing any ingestion code |
| **A2** | **obtain written vendor-licence clarification** ([provider-evaluation.md](provider-evaluation.md) §5) | **any purchase or credential** |
| A3 | subscribe to a paid data plan | any credentialed vendor access |
| **A4** | **select the production information-set profile** ([contract §3](pit-data-contract.md)) | any backtest that informs capital |
| A5 | accept the analyst-estimate gap, or fund an estimates licence | building the earnings/revision composite |
| A6 | fund borrow-history data, **or** formally defer the short family | any short-side research |
| A7 | accept Phase 3 as complete | Phase 4 |

**A2 comes before A3 deliberately.** The low-cost individual licences examined are
personal-use-only and restrict publishing analysis derived from the data. Buying first and
reading the terms afterwards is how a public repository acquires a licence breach it cannot
recall — which is the same mechanism, in a different domain, that left INC-0002 open.

**No credential is requested, entered, stored or logged under this plan.** When A3 is
granted, vendor keys follow the existing rule — environment variables or a secrets manager,
never source, never a committed file, never an AI chat session (CLAUDE.md §4).

## 8. The two findings that shape everything else

Both are argued with evidence in [provider-evaluation.md](provider-evaluation.md) and
classified in [data-domain-inventory.md](data-domain-inventory.md) §12.

**1. Point-in-time analyst revisions are not available at individual cost.** The
earnings/revision composite carries the largest single weight in Blueprint §6 (~35–40%).
The credible sources of historical *revision timing* — I/B/E/S detail history, FactSet
estimates — are institutional, licensed per seat or per firm, and quoted by sales.
Consequence: **the revision sub-factor cannot be built point-in-time at this budget.**
The plan's answer is not to approximate it. It is to build the part of the composite that
*is* point-in-time (as-reported fundamental surprise from filings, and post-filing drift),
mark the revision sub-factor **NOT AVAILABLE**, and forbid any performance claim that
depends on it.

**2. Historical borrow availability and fees are UNRESOLVED — which is not the same as
absent, and revision 1 got this wrong.** It claimed flatly that IBKR does not archive borrow
history, generalising one secondary report about an FTP feed to everything IBKR offers. Review
caught it, and re-verification found the opposite: IBKR documents four historical borrow
surfaces, including **`reqHistoricalData` with `whatToShow=FEE_RATE`** — a historical stock
borrow fee series available through the TWS API this system already connects to.

Its depth is documented nowhere, and that one unknown decides whether the short family is
blocked by data or merely by effort. **Establishing it means calling the broker, which this
plan is not authorized to do.**

Consequence: **the short strategy family still cannot be backtested honestly until the
question is settled** — but the cheapest route to settling it is now an interface we already
have, not a purchase. Phase 3C's first task is that qualification; a free third-party lead is
second; paid sources are last. Short research stays forbidden throughout, rather than
proceeding on assumed borrow.

Blueprint §12 already anticipated this: *"Historical short backtests are discounted unless
borrow cost and availability are modeled conservatively."* Phase 3 makes that a gate
instead of a caution.

## 9. What "done" means

Phase 3 is complete when [implementation-plan.md](implementation-plan.md) acceptance
criteria pass — including the adversarial look-ahead fixtures — and a human accepts it in
writing. Partial completion is reported as partial. Per CLAUDE.md §8, a phase is never
described as complete while any part of it is blocked or skipped.

Phase 3C may be **deferred rather than completed**, provided the deferral is recorded and
the short family stays unauthorized. That is an acceptable outcome. Claiming short support
without it is not.
