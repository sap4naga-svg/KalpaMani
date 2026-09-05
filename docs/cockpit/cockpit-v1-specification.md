# Cockpit V1 — functional specification

**Status: ACCEPTED SPECIFICATION EFFECTIVE ON MERGE OF PR #NNN, and PROPOSED until that merge —
NOT IMPLEMENTED, NOT AUTHORIZED.**

This document specifies the 36 product areas of Cockpit V1: what each one is for, what it presents,
who owns the facts behind it, what it may never do, and what it shows when the data does not exist.

**It specifies. It does not implement, and it authorizes nothing.** No Cockpit application, read
API, projection, database, scheduler or feedback automation exists or is authorized because this
document describes one. **A described screen is not permission to build it.**

**Nothing here rests on provider data.** **P1–P9 are UNEVALUATED**, **data correctness and quality
are NOT ESTABLISHED**, **G1 and G2 are OPEN**, **no provider is selected**, **Run B has not run and
is not authorized**, and **the combined assessment has not run and is not authorized**. Every
figure, chart and statistic described below is a **shape a screen would take**, never a result.

**No alpha is claimed anywhere in this document.**

---

## 1. Authority and scope

| | |
|---|---|
| **Governed by** | Blueprint V3.0, then approved ADRs, then `CLAUDE.md`, then the approved task specification |
| **Introduced by** | [ADR-0027](../decisions/ADR-0027-cockpit-and-feedback-architecture-and-governance.md) |
| **Architecture** | [`COCKPIT_FEEDBACK_EXTENSION.md`](../architecture/COCKPIT_FEEDBACK_EXTENSION.md) |
| **Contracts** | [`read-model-contracts.md`](read-model-contracts.md) |
| **Feedback** | [`feedback-self-maturation-specification.md`](feedback-self-maturation-specification.md) |
| **Presentation** | [`ui-ux-specification.md`](ui-ux-specification.md) |
| **Traceability** | [`traceability-matrix.md`](traceability-matrix.md) |
| **Consumes** | [ADR-0026](../decisions/ADR-0026-strategy-brain-architecture-and-governance.md) and [`strategy-brain-specification.md`](../phase4/strategy-brain-specification.md) — unchanged |

---

## 2. The V1 safety boundary

**Cockpit V1 is observational.** It displays, explains, compares, diagnoses, surfaces alerts,
navigates, and presents evidence and decisions.

**READ-ONLY is defined by what is absent, not by what is discouraged.** No Cockpit endpoint,
command, assistant tool, hidden handler, background job or scheduled action may:

```text
place or cancel an order          change a stop
change risk or capital            activate or promote a strategy
enable leverage                   change the provider
execute Run B or an assessment    publish CONTROL
alter production strategy state   approve or reject a governance release
```

**Governance screens display recorded decisions and packets. They do not originate authoritative
approval records in V1.**

**Every future control is inert.** Area 35 specifies a future human control plane so its
authentication, authorization, audit, idempotency and safety architecture can be designed
deliberately. In V1 each control is **explicitly unavailable**, with **no executable handler and no
control API route**. A disabled button that would work if enabled is not inert; **the handler and
the route must not exist**.

---

## 3. Shared vocabularies

The maturity, provenance, availability and classification vocabularies are defined once, in
[`COCKPIT_FEEDBACK_EXTENSION.md`](../architecture/COCKPIT_FEEDBACK_EXTENSION.md) §4, and are used
unchanged throughout this document. The field-level shapes are in
[`read-model-contracts.md`](read-model-contracts.md).

**Every area below states its V1 availability using that vocabulary.** An area whose producing
subsystem does not exist reports `NOT_IMPLEMENTED`; an area whose producing operation exists but is
not authorized reports `NOT_AUTHORIZED`; and a synthetic demonstration of either is labelled
`SYNTHETIC` and is not evidence of anything.

---

## 4. Information architecture

**Thirty-six areas are not thirty-six equal sidebar links.** Navigation is grouped, and the
grouping is part of the specification because a flat list of 36 destinations is an unusable
interface.

```text
OVERVIEW        Executive Overview · Attention Required · What Changed
PORTFOLIO       Performance · Positions & Exposure · Trade History · Trade Detail
STRATEGY        Strategy Performance · Strategy Health · Champion/Challenger
                    · Strategy Version Registry
SIGNALS         Signal & Candidate Funnel · Candidate Detail · Missed Opportunities
RISK            Risk Dashboard · Short-Side Dashboard · Market & Regime
EXECUTION       Execution Quality · Broker & Reconciliation
RESEARCH        Research & Backtesting · Research Queue · Hypothesis Registry
                    · Feedback Loop · AI Contribution Analytics
GOVERNANCE      Governance Packets · Project & Qualification Governance
                    · Environment & Deployment Maturity · Audit Trail
SYSTEM          Data Quality & PIT · System Operations · Alerts & Exceptions
GLOBAL          Command Palette · Ask KalpaMani · Executive/Operator mode
                    · Future Control Plane (inert)
```

The route map, navigation behaviour and mode semantics are specified in
[`ui-ux-specification.md`](ui-ux-specification.md).

---

# The 36 product areas

Each area states its **purpose**, what it **presents**, its **read-model owner**, its **V1
availability**, and its **boundaries**. Column-wise traceability — presentation density, synthetic
availability, real-feed gate, implementation cycle and observable acceptance criteria — is in
[`traceability-matrix.md`](traceability-matrix.md).

---

## Area 1 — Executive Overview

**Purpose.** Answer, in roughly ten seconds: how are we doing, is anything wrong, what changed,
where is risk, and what requires attention.

**Presents.** Strategy capital, equity and cash · daily, weekly, monthly and cumulative profit and
loss · return · long, short, gross and net exposure · open planned risk · drawdown · market regime ·
system health · data freshness · active strategies · open incidents · last decision and last scout
run · **What Changed** · a ranked **Attention Required** list.

**Read-model owner.** A snapshot-consistent `ExecutiveOverview` projection assembled from the
portfolio, risk, strategy-health, data-quality, operations and governance read models.

**Boundaries.** **Strategy capital is USD 80,000 and is authoritative; broker-reported equity is
observed for reconciliation and never participates in sizing** (`CLAUDE.md` §6). The overview shows
both and never substitutes one for the other. Every tile carries its own availability and as-of
time; **a tile whose input is missing shows its availability state, never a zero**.

**V1 availability.** `SYNTHETIC` demonstration. Real inputs are `NOT_IMPLEMENTED` for strategy,
candidate, execution and broker facts, and `AVAILABLE` only for governance facts that already exist
in tracked repository authority.

---

## Area 2 — Portfolio Performance

**Purpose.** Show what the portfolio actually did, over time, with the assumptions visible.

**Presents.** Equity, return and drawdown curves · realized and unrealized profit and loss · daily,
weekly, monthly and rolling returns · a monthly return heatmap · maximum drawdown · risk-adjusted
measures · expectancy · profit factor · win rate · average winner and loser · R multiples ·
benchmark comparison against SPY, QQQ and IWM · later, Backtest, Paper and Live comparisons **with
explicit comparability limits**.

**Read-model owner.** `PerformanceSeries` and `PerformanceSummary` projections over recorded
portfolio facts.

**Boundaries.** **Deposits and withdrawals are not trading profit.** External cash flows are handled
by the stated return method and are never allowed to appear as performance. **A backtest series and
a live series never share a line**; a comparison shows separately labelled series with their
comparability limits stated on the chart, not in a footnote nobody reads. Every ratio states its
denominator and its minimum-observation rule, and reports `INSUFFICIENT_OBSERVATIONS` rather than a
meaningless number.

**V1 availability.** `SYNTHETIC` demonstration; real portfolio facts `NOT_IMPLEMENTED`.

---

## Area 3 — Positions & Exposure

**Purpose.** Show what is owned, why, and what it is exposed to.

**Presents.** Per position — entry and current price, unrealized result, planned risk, invalidation
level, ownership, holding duration. Grouped by long and short, sector and industry, strategy,
alpha family, factor and correlation cluster. Concentration, gap exposure, event exposure, earnings
proximity, borrow state, liquidity and capacity.

**Read-model owner.** `PositionSnapshot` and `ExposureAggregate` projections.

**Boundaries.** **Exposure grouping is not a risk decision.** The dashboard shows the groupings the
risk engine uses; it does not compute a permitted exposure and does not imply one. **Borrow state is
displayed from a borrow record, never inferred from price behaviour** (ADR-0026 §20).

**V1 availability.** `SYNTHETIC` demonstration; real positions `NOT_IMPLEMENTED`.

---

## Area 4 — Strategy Performance

**Purpose.** Measure each strategy module separately, and its family jointly.

**Presents.** For Breakout Long, Pullback Long, PEAD Long, PEAD Short and Deterioration Short —
profit and loss, expectancy, win rate, profit factor, drawdown, hold time, opportunity count,
turnover, slippage, capacity, MFE, MAE and capture ratio. Sliced by sector, regime, volatility,
trade template and factor. Aggregated to alpha family.

**Read-model owner.** `StrategyPerformance` projection, keyed by strategy module **and** strategy
version.

**Boundaries.** **Breakout Long and Pullback Long keep separate module attribution and share a
family risk context**, exactly as ADR-0026 §3.1 specifies; whether they are economically distinct is
**open gate G7**, and this document does not decide it. **No diversification or alpha claim is made
without evidence** — two modules in one family are one exposure with two names until measured
otherwise. Results are always attributed to the exact strategy version that produced them.

**V1 availability.** `SYNTHETIC` demonstration; real strategy results `NOT_IMPLEMENTED` — no
strategy module exists.

---

## Area 5 — Strategy Health

**Purpose.** Show whether a strategy is behaving as researched, and what the system did about it.

**Presents.** The health state, from the vocabulary ADR-0026 §13 fixes and this document does not
extend:

```text
HEALTHY   WATCH   DEGRADED   NEW_ENTRIES_REDUCED   NEW_ENTRIES_DISABLED
SUSPENDED   RETIRED
```

With rolling expectancy, drawdown and tail losses · opportunity count · turnover · execution
quality · capacity · factor drift · cross-strategy correlation · regime behaviour · borrow and
data-quality incidents · AI contribution · modeled versus realized execution · transition history
with reasons · the safety action taken · **the human action required**.

**Read-model owner.** `StrategyHealth` projection over recorded health-state transitions.

**Boundaries.** **Reducing or disabling new entries is automatic; restoring them is not**, and
**recovery past a governed suspension is never automatic** (ADR-0026 §13). The Cockpit **displays**
a transition; it never causes one. **A degradation creates a research queue entry and does not
mutate a parameter.**

**V1 availability.** `SYNTHETIC` demonstration; real health facts `NOT_IMPLEMENTED`.

---

## Area 6 — Signal / Candidate Funnel

**Purpose.** Show where opportunities are lost, at every stage, with reasons.

**Presents.** Universe → eligible → generated → consolidated, then the Brain's closed decision
states:

```text
WATCHLIST   READY_FOR_RISK_REVIEW   REJECTED   BLOCKED_DATA   BLOCKED_EVENT
BLOCKED_AI  BLOCKED_CONTRADICTION   BLOCKED_BORROW
```

Counts, conversion rates, reason-code distributions, and a per-strategy funnel.

**Read-model owner.** `CandidateFunnel` projection over journaled Brain decisions.

**Boundaries.** **The Brain status vocabulary is closed and is not extended here.** Downstream risk
approval, order and fill states are a **separate typed axis** owned by the portfolio, risk and
execution layers, presented alongside rather than appended to the Brain states —
[`read-model-contracts.md`](read-model-contracts.md) defines both vocabularies separately.
**`READY_FOR_RISK_REVIEW` is not an approval to trade**, and the funnel must not present it as the
end of a successful path.

**V1 availability.** `SYNTHETIC` demonstration; real candidates `NOT_IMPLEMENTED` — the Brain
runtime does not exist.

---

## Area 7 — Candidate Detail / Explainability

**Purpose.** Explain one candidate completely enough to disagree with it.

**Presents.** Security, direction, alpha family, strategy module, trade template, status,
cross-sectional ranks and setup quality · thesis, entry condition, invalidation condition and
expected horizon · event, gap, liquidity and short context · AI Research evidence · Challenger
evidence and objections · contradictions · deterministic reason codes · lineage · strategy, factor,
model and prompt versions · and the explanation of acceptance or rejection.

**Read-model owner.** `CandidateDetail` projection over the journaled `CandidateIntent` and its
evidence references.

**Boundaries.** **The technical stop is a reference to an invalidation level, not an order.** The
view displays no share count, no dollar amount, no order type and no route, because
`CandidateIntent` carries none — **the exclusion is structural, not a presentation choice**. AI
evidence is always shown with its source publish time, model version and prompt version, and **AI
evidence never appears as the reason a blocked candidate became eligible**.

**V1 availability.** `SYNTHETIC` demonstration; real candidate detail `NOT_IMPLEMENTED`.

---

## Area 8 — Missed Opportunities

**Purpose.** Learn from what the system saw and did not take.

**Presents.** Candidates detected but not entered, with the cause — expiry, delay, data, borrow,
risk, regime, event or execution. Subsequent price path, favourable movement, counterfactual
opportunity cost, recurring patterns, false-positive and false-negative analysis, and a taken versus
missed comparison.

**Read-model owner.** `MissedOpportunity` projection.

**Boundaries.** This is the area most able to mislead, so its limits are contractual rather than
advisory.

| | |
|---|---|
| **hindsight is not achievable profit** | favourable movement after a decision is **not** profit that was available. Sizing, costs, borrow, slippage and the stop that would have been in place all intervene |
| **the measurement window is registered** | every counterfactual states its window, its assumptions and its cost treatment, and two counterfactuals with different windows are never compared |
| **missing bars are missing** | an incomplete follow-up path yields `PARTIAL`, never an optimistic completion |
| **no false-negative rate without a population** | a rate requires a defined evaluable population; where none is defined, the view reports the count and refuses the rate |

**V1 availability.** `SYNTHETIC` demonstration; real missed opportunities `NOT_IMPLEMENTED`.

---

## Area 9 — Execution Quality

**Purpose.** Show what the order machinery did, and what it cost.

**Presents.** The future order lifecycle — submitted, acknowledged, filled, partially filled ·
reference versus actual price · spread and slippage · signal-to-order and order-to-fill latency ·
rejects, cancels and missed fills · duplicate-order protection · protective-order status ·
pyramids · exit quality · modeled versus realized cost.

**Read-model owner.** `ExecutionQuality` projection over recorded order and fill events.

**Boundaries.** **Displaying an order lifecycle is not participating in one.** Order identity and
idempotency remain governed by
[ADR-0004](../decisions/ADR-0004-deterministic-order-identity-idempotency-and-execution-lifecycle.md),
and broker-native identifiers are **never** rendered — they are among the values `CLAUDE.md` §3
forbids in this repository, and a read model that surfaced one would put it on a screen and in a
cache. The view uses safe internal references.

**V1 availability.** `NOT_IMPLEMENTED` — no automated execution exists beyond the certified Phase 2
scope, which is plumbing evidence and not a strategy. `SYNTHETIC` demonstration only.

---

## Area 10 — Broker / Reconciliation

**Purpose.** Show whether the system's view of the world matches the broker's.

**Presents.** Future broker and session health · last reconciliation time and outcome · internal
versus broker positions, cash, orders, fills and ownership · orphan detection · restart and
reconnect events · authentication state · incidents.

**Read-model owner.** `ReconciliationStatus` projection over recorded reconciliation results.

**Boundaries.** **Observed through authorized projections only.** The Cockpit holds no brokerage
credential and opens no brokerage session; a reconciliation screen that queried IBKR to "refresh"
would be an execution-path integration. **Broker equity is informational for reconciliation and
never sizing authority.** **A past successful reconciliation carries its as-of time** and is not
presented as current health.

**V1 availability.** `NOT_IMPLEMENTED`; broker is **flat** and no automated session exists.
`SYNTHETIC` demonstration only.

---

## Area 11 — Market / Regime

**Purpose.** Show the conditions strategies are operating in.

**Presents.** Trend · breadth · volatility · momentum-crash and reversal state · sector leadership
and weakness · factor regime · event stress · long and short context · regime history · strategy
results decomposed by regime.

**Read-model owner.** `MarketRegime` projection over a versioned regime context.

**Boundaries.** **The regime context is versioned and is an input, not a conclusion.** The Cockpit
shows the regime the system recorded; it computes no new regime and it does not size exposure — that
stays in the deterministic portfolio and risk logic (ADR-0026 §18).

**V1 availability.** `NOT_IMPLEMENTED` — no regime engine exists and no provider is selected.
`SYNTHETIC` demonstration only.

---

## Area 12 — Risk Dashboard

**Purpose.** Show the risk the portfolio is carrying and the constraints that bound it.

**Presents.** Planned and permitted risk · concentration · sector, family, factor and correlation
exposure · portfolio volatility · gap, event, earnings, short and borrow risk · loss and drawdown
thresholds · risk tier · circuit-breaker state · new-entry state.

**Read-model owner.** `RiskSnapshot` projection over recorded risk-engine outputs.

**Boundaries.** **Read-only, without exception.** The dashboard changes no threshold, trips no
breaker and reduces no exposure. The governed research values it displays — 0.50% long planned risk
per trade, 0.25% short, approximately 5% maximum open planned risk, approximately 8–10% maximum
individual position, at most 25% initial gross short, no leverage — are **reproduced for context and
are research parameters, not performance expectations**. **This specification changes none of them.**

**V1 availability.** `NOT_IMPLEMENTED` — no risk engine exists. `SYNTHETIC` demonstration only.

---

## Area 13 — Short-Side Dashboard

**Purpose.** Make short-specific risk visible, because it has no long-side mirror.

**Presents.** Short positions · borrow availability, fee, quantity and deterioration · crowding and
utilization · squeeze state · SSR state · recall and buy-in risk · corporate actions · binary
events · short strategy statistics · blocked shorts and borrow-related misses.

**Read-model owner.** `ShortSideSnapshot` projection.

**Boundaries.** **Borrow availability is never inferred from price data.** Hard-to-borrow conditions
and price action correlate; a correlation is not a borrow record, and a candidate whose borrow state
is unknown is displayed as `BLOCKED_BORROW` or unknown rather than assumed available (ADR-0026 §20).
**Gate G5 — historical borrow qualification — is OPEN**, and every borrow statistic in this area
inherits that.

**V1 availability.** `NOT_IMPLEMENTED`; **short research is NOT AUTHORIZED**. `SYNTHETIC`
demonstration only.

---

## Area 14 — Research / Backtesting

**Purpose.** Make research runs findable, comparable and reproducible.

**Presents.** An experiment and run registry · strategy version · manifest, point-in-time profile
and date range · in-sample and out-of-sample split · walk-forward · stress · parameter stability ·
trial count · multiple-testing controls · transaction, slippage and borrow costs · capacity ·
regime, sector and factor decomposition · curves and distributions · baseline comparisons.

**Read-model owner.** `ResearchRun` projection over immutable research manifests.

**Boundaries.** **A named baseline comes first** (ADR-0026 §22); a run without one is displayed as
incomplete rather than as a result. **The trial count is read from the record, never remembered.**
**Synthetic studies are demonstrations, not qualification evidence**, and a synthetic run is
labelled `SYNTHETIC` + `BACKTEST_SIMULATED` and is excluded from every real comparison.

**V1 availability.** `NOT_IMPLEMENTED` — **backtesting is NOT STARTED** and no provider is selected.
`SYNTHETIC` demonstration only.

---

## Area 15 — Champion / Challenger

**Purpose.** Compare a production strategy version against its candidate replacement.

**Presents.** Versions and lineage · population overlap · candidate and profit-and-loss divergence ·
factor-exposure differences · drawdown, regime, execution and capacity differences · out-of-sample
and shadow evidence · governance readiness.

**Read-model owner.** `ChampionChallengerComparison` projection.

**Boundaries.** **No self-promotion.** A Challenger may progress automatically only through
preapproved research and shadow stages; **promotion requires a governance packet and a human
decision** (ADR-0026 §12). The comparison view **shows readiness and never confers it**, and the
word "ready" on this screen means *the evidence required by the packet is present*, never *approved*.

**V1 availability.** `NOT_IMPLEMENTED`. `SYNTHETIC` demonstration only.

---

## Area 16 — Feedback / Self-Maturation Loop

**Purpose.** Make the learning loop visible as a pipeline with states, owners and blockages.

**Presents.**

```text
Journal -> Attribution -> Health / Drift -> Research Queue -> Registered Hypothesis
    -> Immutable Challenger -> Backtest / OOS / Stress -> Shadow
        -> Governance Packet -> Human-Approved Release
```

Each stage with its inputs, outputs, owner, version pins, current items, refusal reasons and the
authorization each transition requires.

**Read-model owner.** `FeedbackPipeline` projection; contracts in
[`feedback-self-maturation-specification.md`](feedback-self-maturation-specification.md).

**Boundaries.** **The Cockpit reads this loop and does not drive it.** No stage advances from this
screen. **The final transition is human-authorized and is recorded elsewhere.**

**V1 availability.** `NOT_IMPLEMENTED` — no learning engine exists. `SYNTHETIC` demonstration only.

---

## Area 17 — Research Queue

**Purpose.** Show what the system thinks should be investigated, and why.

**Presents.** Hypotheses awaiting work, with trigger, strategy, issue, proposed experiment,
baseline, associated Challenger, priority, supporting evidence, state, the authorizations required
before it can proceed, and its result and history.

**Read-model owner.** `ResearchQueueItem` projection.

**Boundaries.** **A queue entry is not an authorization.** Generating and prioritizing research is
inside the automation's approved bounds; running it against real data is not, and every item
displays the authorization it is waiting on.

**V1 availability.** `NOT_IMPLEMENTED`. `SYNTHETIC` demonstration only.

---

## Area 18 — Hypothesis Registry

**Purpose.** Hold preregistrations immutably, so results cannot be reinterpreted after the fact.

**Presents.** Registration identity and time · trigger · strategy · thesis · baseline · variation ·
trial budget · success criteria · failure criteria · data requirements · research version · and
**linked** results and governance decisions.

**Read-model owner.** `HypothesisRegistration` projection.

**Boundaries.** **A preregistration is immutable.** Later results are **appended as linked records,
never edits to the preregistration**. A change of design creates an **amendment or a new
registration before further research**, and the registry displays the chain rather than the latest
version alone. **Every trial counts against the budget, including failed and abandoned runs.**

**V1 availability.** `NOT_IMPLEMENTED`. `SYNTHETIC` demonstration only.

---

## Area 19 — Governance Packets

**Purpose.** Present the evidence a human needs in order to decide.

**Presents.** The proposal and its cause · out-of-sample and stress evidence · shadow evidence ·
risk, factor and operational impact · failure modes · Champion comparison · the recommendation ·
**the recorded human decision** · audit history.

**Read-model owner.** `GovernancePacket` and `DecisionRecord` projections.

**Boundaries.** **Read-only presentation in V1.** The Cockpit **displays** a packet and a recorded
decision; it does not **originate** an approval or a rejection. A recommendation prepared by
automation is input to a human decision and is labelled as such — **never as the decision**.

**V1 availability.** `NOT_IMPLEMENTED`. `SYNTHETIC` demonstration only.

---

## Area 20 — Strategy Version Registry

**Purpose.** Make every production and candidate version findable with its complete lineage.

**Presents.** Version and status · Champion or Challenger role · factor, risk, entry and exit
policies · AI model and prompt versions · code and configuration identity · activation, retirement,
promotion and rollback history · **open-position pinning**.

**Read-model owner.** `StrategyVersion` projection.

**Boundaries.** **Production strategy versions are immutable, and a modification creates a new
Challenger version rather than an edit in place.** **An open position stays governed by the exact
versions that opened it**, and the registry displays that pinning explicitly so a reader can see
which live positions a retirement does and does not affect.

**V1 availability.** `NOT_IMPLEMENTED`. `SYNTHETIC` demonstration only.

---

## Area 21 — AI Contribution Analytics

**Purpose.** Measure what AI actually contributed, without inventing a causal claim.

**Presents.** Deterministic-only versus structured-evidence versus structured-evidence-plus-LLM
arms · Research Agent and Challenger Agent contributions · blocks and contradictions raised ·
eventual incremental economics · model, prompt and source provenance · AI outage periods and their
effect.

**Read-model owner.** `AiContribution` projection.

**Boundaries.** **Matched comparisons and stated uncertainty, and no unsupported causal alpha
claim.** The comparison is experiment E in ADR-0026 §23 and **has not been run**. **AI never
receives money or order authority**, and this view is measurement rather than justification. Where
the matched population is too small, the view reports `INSUFFICIENT_OBSERVATIONS` instead of a
difference.

**V1 availability.** `NOT_IMPLEMENTED` — no AI agent exists. `SYNTHETIC` demonstration only.

---

## Area 22 — Data Quality / Point-in-Time

**Purpose.** Show whether the data underneath every other screen can be trusted.

**Presents.** Coverage · freshness · history depth · information-set profile · dataset version ·
revision view · missingness · lineage · corporate actions · event timing · borrow-data quality ·
incidents · stale data · strategies blocked by a data condition.

**Read-model owner.** `DataQuality` projection over recorded quality evidence.

**Boundaries.** **The profile vocabulary is the existing one and is not extended:** `PUBLIC_PIT`,
`PROVIDER_REALISTIC_PIT` and `FORWARD_SYSTEM`, used exactly as
[ADR-0005](../decisions/ADR-0005-point-in-time-data-architecture.md) and the point-in-time contract
define them. **No default profile is invented**; a profile is declared, never inferred. **All
Sharadar price data stays `PROVIDER_DERIVED` and is never represented as `PUBLIC_PIT`** — Q7 is
`PUBLICLY_UNRESOLVED` (ADR-0010).

**V1 availability.** `NOT_IMPLEMENTED` for a real feed — **no provider is selected, P1–P9 are
UNEVALUATED and data correctness and quality are NOT ESTABLISHED**. `SYNTHETIC` demonstration only.

---

## Area 23 — System Operations

**Purpose.** Show whether the machinery is running.

**Presents.** Service, scheduler, scout, future Brain, data, broker-sync and research-job health ·
failures · latency · queue depth · last success · restarts · incidents · errors · availability · an
operations timeline.

**Read-model owner.** `SystemJob` and `SystemIncident` projections.

**Boundaries.** **Displaying jobs does not run them.** There is no start, stop, retry or trigger
control in V1, and none of those endpoints exists. A job's last successful run carries its as-of
time and is never displayed as current health.

**V1 availability.** `NOT_IMPLEMENTED` — no scheduler or service runtime exists. `SYNTHETIC`
demonstration only.

---

## Area 24 — Project / Qualification Governance

**Purpose.** Show where the project actually is, in public-safe terms.

**Presents.** Run A · Run B · the date gate · the combined assessment · P1–P9 · G1–G7 · provider
status · profile · licensing · borrow · options · ADR states · phase · readiness · blockers · the
next required event.

**Read-model owner.** `QualificationStatus` projection over **tracked repository governance facts**.

**Boundaries.** **Public-safe governance facts only.** This view uses the same statements the
tracked repository already makes; it **never** presents private qualification evidence, a locator, a
private report, an execution identifier, a bucket, an account, a subject or a vendor row. **Terms §8
of the Sharadar personal-use licence bars disclosing fitness conclusions**, and a dashboard is a
disclosure surface. **P1–P9 render as `UNEVALUATED`**, not as pending, not as zero, and not as
blank.

**Each gate is read independently.** G3 is closed for the Sharadar personal-use licence and nothing
else; G1, G2, G4, G5, G6 and G7 are open for their own reasons. **The view never renders a blanket
statement about all seven.**

**V1 availability.** `AVAILABLE` from tracked repository authority — the one area whose real inputs
exist today. Where a governance fact is private, the view reports the public-safe status and nothing
more.

---

## Area 25 — Environment / Deployment Maturity

**Purpose.** Show how far each strategy has actually been governed.

**Presents.** The five stages — Research, Shadow, Automated Paper, Micro-Live, Scaled Live — with
per-strategy authorizations, promotion requirements and outstanding gates.

**Read-model owner.** `MaturityStatus` projection.

**Boundaries.** **No maturity advancement from selecting an environment in the interface.** A stage
is a property of a governance record. The mapping to ADR-0026 lifecycle values and to the runtime
`Environment` enum is the one fixed in
[`COCKPIT_FEEDBACK_EXTENSION.md`](../architecture/COCKPIT_FEEDBACK_EXTENSION.md) §4.1; **Shadow has
no order authority**, and **Automated Paper is the first order-producing stage and requires human
approval**.

**V1 availability.** `NOT_IMPLEMENTED` for strategy records — no strategy exists at any stage.
`SYNTHETIC` demonstration only.

---

## Area 26 — Audit Trail

**Purpose.** Reconstruct what happened, forensically, including things that were not trades.

**Presents.** An immutable timeline of candidate, decision, reason, version, health, hypothesis,
promotion, approval, safety-action, execution and incident events.

**Read-model owner.** An `AuditEvent` projection.

**Boundaries.** **The projection is rebuildable; the authoritative audit events are not the
projection.** Rebuilding a read model must never mutate a source event, and the two are separately
identified so a projection defect cannot be mistaken for missing history. **Licensed content is
never copied into an immutable audit payload**; events carry classified references, and deletion is
expressed through authorized tombstone semantics that preserve the governance record without
retaining vendor data.

**V1 availability.** `NOT_IMPLEMENTED` for platform events. `SYNTHETIC` demonstration only.

---

## Area 27 — Alerts / Exceptions

**Purpose.** Surface conditions that need a human eye, without becoming noise.

**Presents.** Strategy, risk, drawdown, stale-data, provider, broker, reconciliation, borrow,
slippage and AI-outage alerts · research or Challenger ready · governance attention. With severity,
deduplication, freshness, linked evidence and resolved history.

**Read-model owner.** `Alert` projection.

**Boundaries.** **No external notification integration in this cycle** — no email, SMS, push, chat
webhook or paging integration is specified, built or authorized. An alert is a record the interface
displays. **Deduplication is a contract, not a nicety**: one condition produces one alert with an
occurrence count, because a hundred copies of a true alert is an outage of the alerting system.

**V1 availability.** `NOT_IMPLEMENTED` for platform alerts. `SYNTHETIC` demonstration only.

---

## Area 28 — Executive Attention Required

**Purpose.** Turn alerts into a short ranked list a person can act on.

**Presents.** For every item — **what happened**, **why it matters**, **impact**, **evidence**, the
**recommended permitted governance action**, and a **drill-down**.

**Read-model owner.** `AttentionItem` projection, derived from alerts, health, risk, data quality and
governance.

**Boundaries.** **Ranked by materiality and severity, and deduplicated against the alert feed** — an
attention list that repeats every alert is a second alert list. **A recommended action is always a
permitted governance action**, never an execution instruction, and the Cockpit performs none of
them.

**V1 availability.** `SYNTHETIC` demonstration, with the governance-derived items `AVAILABLE` from
tracked authority.

---

## Area 29 — Executive / Operator Modes

**Purpose.** One data system, two presentation densities.

**Presents.** Executive — the ten-second answer, with restraint. Operator — evidence, technical
detail, reason codes, versions and lineage, through drill-down.

**Boundaries.** **Both modes read the same read models.** A mode is a presentation density, not a
different dataset and not a different permission. **Switching modes preserves filters, environment,
source and drill-down context**, because a mode switch that resets context makes the other mode
unusable for the question in hand.

**V1 availability.** `AVAILABLE` as a presentation capability over whatever the underlying areas
provide.

---

## Area 30 — Global Command Palette

**Purpose.** Reach anything in the Cockpit in one keystroke.

**Presents.** `Cmd/Ctrl+K` search and navigation across strategies, securities, trades, candidates,
hypotheses, incidents and research results, plus read-only analytical shortcuts.

**Boundaries.** **No execution commands, ever.** The palette navigates and filters. It has no verb
that changes state, and the command vocabulary is closed so a later author cannot add one casually.
Palette results respect environment and source scoping — a result found under one environment does
not silently open under another.

**V1 availability.** `AVAILABLE` as a navigation capability; the entities it searches follow their
own areas' availability.

---

## Area 31 — Ask KalpaMani

**Purpose.** Natural-language analytics over authorized Cockpit read models.

**Presents.** Answers with evidence links, as-of times, source and environment labels, bounded query
scope, stated uncertainty, and **abstention when the data is missing**.

**Boundaries.** The strictest in the Cockpit, and every clause is load-bearing:

| | |
|---|---|
| **no arbitrary SQL or code execution** | queries are bounded and typed against the read-model catalog |
| **no unrestricted data access** | it reads exactly the read models the asking session is authorized for |
| **no state mutation** | it answers; it changes nothing |
| **no broker action** | it has no execution vocabulary at all |
| **no external LLM transmission of licensed data** | `CLAUDE.md` §4.22 governs this surface exactly as it governs an AI assistant session. **A read model derived from licensed rows may not be sent to an external model**, and an unknown classification fails closed |
| **abstention over invention** | where availability is `NOT_YET_AVAILABLE`, `UNEVALUATED`, `PARTIAL` or `INSUFFICIENT_OBSERVATIONS`, it says so and does not estimate |

**V1 availability.** `NOT_IMPLEMENTED`. Specified now so its boundary is designed rather than
retrofitted.

---

## Area 32 — Modern Executive UX

**Purpose.** Make the Cockpit worth looking at, and legible under pressure.

**Presents.** A premium, calm, dark institutional presentation · excellent typography · numeric
hierarchy · restrained accent use · generous whitespace · responsive layout · polished loading,
empty and error states · explicit provenance and availability everywhere.

**Boundaries.** Detailed tokens, states, accessibility and acceptance criteria are in
[`ui-ux-specification.md`](ui-ux-specification.md). **A loading skeleton never resembles a real
value**, and **an empty state and an unavailable state are visually distinct**.

**V1 availability.** `AVAILABLE` as a presentation contract.

---

## Area 33 — Cockpit Read-Model Architecture

**Purpose.** Make the boundary structural.

**Presents.** Facts, events and versioned results → projections → versioned API → interface. With
dedicated contracts per view, explicit ownership, and **no provider or broker shortcut anywhere**.

**Boundaries.** Specified in full in [`read-model-contracts.md`](read-model-contracts.md). **The
boundary applies to the backend as well as the browser**, and **an API proxy must not become a
disguised provider or broker integration**.

**V1 availability.** `AVAILABLE` as a specification; **the implementation is NOT AUTHORIZED**.

---

## Area 34 — Initial V1 Safety Boundary

**Purpose.** State, once and unambiguously, what V1 may not do.

**Presents.** The read-only boundary as a first-class, testable property rather than an assumption.

**Boundaries.** **Observational only.** No money, risk, strategy, provider, Run B, CONTROL or
authoritative governance mutation. The forbidden list in §2 above is the complete statement, and the
governance tests assert each clause by name.

**V1 availability.** `AVAILABLE` as a specification and as a guard.

---

## Area 35 — Future Human Control Plane

**Purpose.** Specify the controls a governed human will eventually need, so they are designed rather
than improvised.

**Specified, and inert.**

```text
global trading ON / OFF        disable new entries
long-only                      short-disable
strategy disable               risk reduction
cancel unfilled orders         emergency flatten
independent kill switch
```

**Boundaries.** **Every one of these is inert in V1**: explicitly unavailable, **with no executable
handler and no control API route**. Before any of them may exist, a separate architecture is
required for **authentication, authorization, audit, idempotency and safety** — a control that is
merely a button is a control whose failure modes nobody designed.

**The kill switch remains independent of the AI**, and the human retains direct control of it
(`CLAUDE.md` §7). **A Cockpit representation of a kill switch is not a kill switch**, and V1 must
not create the impression that it is.

**V1 availability.** `NOT_IMPLEMENTED` / `NOT_AUTHORIZED`, displayed as such.

---

## Area 36 — Trade History and Trade Detail

**Purpose.** Give a human the trade ledger, and the complete story of any single trade.

**Navigation.** Portfolio → Trade History → a trade → Trade Detail.

### 36.1 Trade History

**Presents.** Open and closed, long and short · strategy, family and symbol · entry and exit
timestamps and prices · shares and initial position value · realized profit and loss · unrealized
profit and loss for open trades · return percentage · R multiple · holding period · MFE · MAE ·
capture ratio · entry and exit reasons · stop and invalidation outcome · strategy, factor and
risk-policy versions · environment and trade status · search, sort, filters and date ranges ·
winners and losers and strategy filters · **safe classified exports where appropriate**.

**An export carries its classification.** A `LICENSED_DERIVED` or `PRIVATE_OPERATIONAL` export
cannot leave the private boundary, and an export of unknown classification is refused.

### 36.2 Trade Detail

**Reconstructs the whole trade:**

```text
Candidate -> Brain Decision -> Risk Decision -> Order -> Fill(s) -> Protection
    -> Pyramid / Adds -> Exit -> Reconciliation -> Attribution
```

**Presents.** The original thesis and why entry occurred · candidate, deterministic, factor and
regime evidence · AI Research evidence and Challenger objections where applicable · entry,
invalidation and technical-stop references · the downstream risk and sizing decisions · the order
and fill timeline with partial fills and slippage · protective orders, adds and pyramids and stop
changes · the exit decision and reason and the final realized economics · MFE, MAE and capture
ratio · benchmark movement during the holding period · strategy, factor and regime attribution ·
strategy, model, prompt, code and version lineage · safe links to immutable audit events · a
**TradingView Lightweight Charts** price view with entry, add, stop and exit markers.

**The join is a read-model concern.** Trade Detail **joins separately owned downstream facts** —
owned by the Brain, by portfolio and risk, and by execution and reconciliation — **through safe
internal references**. **No sizing or execution
field is added to `CandidateIntent`** to make this view simpler.

### 36.3 The four concepts, kept apart

| | |
|---|---|
| **Trade History** | the human-friendly trade ledger and its results |
| **Trade Detail** | the complete story of one trade |
| **Execution History** | order, fill and reconciliation mechanics |
| **Audit Trail** | immutable forensic events, including non-trade activity |

**They share identifiers and never share a screen.**

### 36.4 Trade identity and lifecycle

| | |
|---|---|
| **stable trade identity** | a trade has one durable internal identifier for its whole life, independent of how many orders, fills or adds it involves |
| **trade to position and lot** | the relationship is explicit — a trade maps to a position and to its lots, and the mapping is recorded rather than derived at read time |
| **partial exits** | reduce a trade; they do not close it and do not create a second trade |
| **multiple fills** | are fills. **A fill is never counted as a separate trade** |
| **adds and pyramids** | extend an existing trade under the pyramiding rules, and are attributed to it |
| **corrections** | are appended as corrections with their own time and reason; a corrected value shows that it was corrected |
| **lifecycle gaps** | are shown as gaps. **A missing event is never inferred**, and a trade with an incomplete lifecycle reports `PARTIAL` |

**Existing manual activity is not silently adopted as platform evidence.** Trades the owner placed
by hand are not KalpaMani trades, and the ledger does not absorb them into strategy statistics.

**V1 availability.** `NOT_IMPLEMENTED` for real trades — the platform has produced none beyond the
certified Phase 2 lifecycle, which is plumbing evidence and not a strategy. `SYNTHETIC`
demonstration only.

---

## 5. Synthetic and demonstration contract

**Every synthetic surface obeys the same rules**, because a demonstration that can be mistaken for
real data is worse than no demonstration.

| | |
|---|---|
| **deterministic** | the same fixture set produces the same screen, every time |
| **reproducible** | generated from a versioned, repository-owned fixture definition |
| **internally consistent** | the trades, positions, candidates and metrics agree with each other; a demonstration whose numbers contradict each other teaches the wrong thing |
| **visibly labelled** | `SYNTHETIC` provenance is displayed persistently, not in a tooltip |
| **free of private identifiers** | no account, no execution identifier, no bucket, no locator, no secret identifier, no vendor row |
| **not the owner's real activity** | **the owner's real manual trades and holdings are never used as demonstration inputs** |

**SYNTHETIC/DEMO is provenance, not a live trading environment**, and a `RESEARCH` environment does
not imply synthetic data.

**A synthetic result is not evidence.** No synthetic figure closes a gate, qualifies a provider,
validates a strategy or establishes a threshold. **No numerical value appearing in a synthetic
example becomes a production rule.**

---

## 6. Unavailable-state contract

**Every area renders every availability state**, and the states are visually distinct:

```text
AVAILABLE   NOT_YET_AVAILABLE   NOT_IMPLEMENTED   NOT_AUTHORIZED   UNEVALUATED
STALE       PARTIAL             ERROR             NOT_APPLICABLE
EMPTY_VERIFIED                  INSUFFICIENT_OBSERVATIONS
```

Worked examples, exactly as they must render:

| Subject | State |
|---|---|
| PEAD Short backtest | **NOT YET AVAILABLE** |
| P1–P9 | **UNEVALUATED** |
| Provider | **NONE SELECTED** |
| Brain candidate stream | **RUNTIME NOT IMPLEMENTED** |
| Run B | **NOT AUTHORIZED**, with its date-gate status shown as a **separate** fact |

**Run B's two facts are separate and stay separate.** The earliest approved target is 2026-09-12 and
the authorization state is `NOT_AUTHORIZED`; **passing the date does not change the authorization**,
and a screen that merges them would show an authorization arriving on a calendar.

**A missing value is never rendered as zero, healthy, passed or no incidents**, and **a numeric null
is never used to carry an availability meaning**.

---

## 7. What this specification does not do

```text
implements NOTHING                        authorizes NOTHING
builds no application                     installs no dependency
creates no database                       provisions no infrastructure
selects no provider                       closes no gate
claims no alpha                           establishes no expected return
runs no backtest                          reads no provider data
reads no private artifact                 touches no AWS or Terraform
contacts no broker                        produces no order
changes no runtime enum                   changes no risk or capital value
```

| | |
|---|---|
| Cockpit specification | **ACCEPTED EFFECTIVE ON MERGE OF PR #NNN** |
| Cockpit implementation | **NOT STARTED / NOT AUTHORIZED** |
| Brain runtime | **NOT STARTED / NOT AUTHORIZED** |
| Backtesting | **NOT STARTED** |
| Run A retry | **NOT AUTHORIZED / NOT RUN** |
| Run B | **NOT RUN / NOT AUTHORIZED** — earliest approved target 2026-09-12 |
| Combined assessment | **NOT RUN / NOT AUTHORIZED** |
| P1–P9 | **UNEVALUATED** |
| Data correctness and quality | **NOT ESTABLISHED** |
| G1 / G2 | **OPEN / OPEN** |
| Provider selected | **NONE** |
| Phase 3 | **NOT COMPLETE** |
| CONTROL publication | **DEFERRED** |
| Live trading | **HARD-DISABLED** |

**Specification, implementation, research, deployment and execution are five separate gates**, and
they are never collapsed into one.
