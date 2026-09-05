# Phase 4 — Strategy Brain specification

**Status: ACCEPTED SPECIFICATION EFFECTIVE ON MERGE OF PR #70, and PROPOSED until that merge —
NOT IMPLEMENTED, NOT AUTHORIZED.**

This document specifies the future KalpaMani Strategy Brain: its contracts, its boundaries, its
lifecycle, its deterministic decision semantics, its strategy taxonomy, its research and promotion
rules, its health states, its AI boundaries and its handoff to portfolio and risk.

**It specifies. It does not implement, and it authorizes nothing.** No Brain runtime module, no
strategy module, no factor calculation, no scanner, no AI agent, no portfolio sizing, no order
routing and no broker action exists or is authorized because this document describes one.
**A described architecture is not permission to build it** — the rule
[ADR-0006](../decisions/ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md) §H already
holds this repository to, and this document inherits it rather than restating a weaker version.

**Nothing here rests on provider data.** Provider qualification has not completed: **P1–P9 are
UNEVALUATED**, **data correctness and quality are NOT ESTABLISHED**, **G1 and G2 are OPEN**, **no
provider is selected**, **Run B has not run and is not authorized**, and **the combined assessment
has not run and is not authorized**. Every strategy statement below is a **hypothesis to be
validated**, never a finding.

**No alpha is claimed anywhere in this document.**

---

## 1. Authority and scope

| | |
|---|---|
| **Governed by** | Blueprint V3.0, then approved ADRs, then `CLAUDE.md`, then the approved task specification |
| **Introduced by** | [ADR-0026](../decisions/ADR-0026-strategy-brain-architecture-and-governance.md) — **ACCEPTED EFFECTIVE ON MERGE OF PR #70**, and **PROPOSED — NOT IN FORCE** until that merge |
| **Builds on** | [ADR-0006](../decisions/ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md) §C self-maturation, §D taxonomy, §E the `CandidateIntent` boundary |
| **Depends on** | [ADR-0005](../decisions/ADR-0005-point-in-time-data-architecture.md) point-in-time architecture — **still PROPOSED**; the Phase-3 point-in-time contract; the A1 foundation kernel |
| **Does not amend** | any accepted ADR. It **refines ADR-0006 §D and §E into checkable contracts** and supersedes nothing |
| **Does not resolve** | G1, G2, G4, G5, G6 or G7. **All six stay OPEN**, and this document closes none of them |

**What this document is not.** It is not a strategy, not a backtest, not an evaluation, not a
provider selection, not a capital decision and not a readiness statement. It is the contract set a
later, separately authorized implementation must satisfy.

---

## 2. The locked principle, expressed as a boundary

> **AI may improve information processing, research, hypothesis generation and challenge analysis.**
>
> **Deterministic software controls money, risk, trade eligibility, sizing, execution approval,
> broker actions, stops, pyramiding, reconciliation, circuit breakers and the kill switch.**

The Brain sits entirely on the information side of that line.

```text
                      THE BRAIN                     |        NOT THE BRAIN
                                                    |
  why does an opportunity exist                     |  can the portfolio own it
  why enter now                                     |  how much risk
  what evidence supports it                         |  how many shares
  what evidence rejects it                          |  which order type
  what deterministic status it has                  |  which route
  what risk context downstream logic must know      |  how to protect a fill
                                                    |  how to reconcile broker state
```

**The Brain produces no broker order and no position size.** Its terminal output is a deterministic
typed `CandidateIntent` handed to later portfolio and risk logic, and nothing else.

### 2.1 Required Brain properties

The Brain must be:

| | |
|---|---|
| **point-in-time** | every input is resolved as of an explicit decision instant, never "latest" |
| **deterministic at the decision boundary** | the same immutable inputs produce the same `CandidateIntent` |
| **versioned** | strategy, factor-definition, policy, model and prompt versions are pinned, never floating |
| **reproducible** | a decision replays from its recorded inputs without contacting a network |
| **explainable** | every status carries closed reason codes, not prose |
| **auditable** | every decision is journaled with complete lineage |
| **fail-closed** | missing, malformed, stale or unrecognised input blocks; it never defaults |
| **strategy-aware** | family, module and template are first-class, not tags |
| **portfolio-unaware for sizing** | it never computes size, and it is exposure-**aware** only where exposure context is explicitly supplied to it |
| **incapable of silently changing its own production rules** | no online self-modification, ever |

---

## 3. Strategy taxonomy

Six concepts, non-interchangeable. This refines
[ADR-0006](../decisions/ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md) §D and does
not alter it.

| Concept | Question it answers | What it is not |
|---|---|---|
| **Alpha family** | why does a return exist economically? | not an implementation; carries the family risk budget and factor accounting |
| **Strategy module** | which separately versioned, separately researched process pursues it? | not a family; two modules in one family are one exposure with two names |
| **Trade template** | why enter *now*? | not alpha; a construction of entry, invalidation and exit |
| **Feature** | what measured input informs ranking or evidence? | **not a strategy** |
| **Filter** | what makes a candidate ineligible? | **not a strategy** |
| **Risk overlay** | what context or permission constrains the candidate? | **not alpha** |

**Different labels do not constitute diversification.** Two modules loading on the same factors are
budgeted as one exposure.

### 3.1 The initial families and modules

```text
FAMILY A — MOMENTUM CONTINUATION            one family risk cap, one factor budget
    module  Breakout Long
    module  Pullback Long

FAMILY B — EVENT / INFORMATION DRIFT
    module  PEAD Long
    module  PEAD Short

FAMILY C — FUNDAMENTAL DETERIORATION
    module  Deterioration Short
```

**Breakout Long and Pullback Long are separate modules that share a family exposure cap**, and each
keeps **separate module attribution** so their economics can be measured apart. Whether they are
economically distinct enough to justify separate module budgets inside the family is **open gate
G7**, and this document does not decide it.

**No generic "Breakdown Short" is authorized.** A short module may not be produced by inverting a
long breakout. **Short alpha is asymmetric** — borrow, fees, recall, squeeze dynamics, SSR, gap
asymmetry and an unbounded loss profile have no long-side mirror — so it requires its own economic
evidence, its own research and its own gates.

---

## 4. The point-in-time reality gate

**Stage one of the Brain, before any strategy logic runs.** It establishes that the world was
knowable as of the candidate cutoff, and refuses otherwise.

It must establish, as of the decision instant:

```text
security identity resolved                 historical universe membership valid
sessions and calendars resolved            required bars admissible
corporate actions admissible               required events and filings admissible
revisions taken through the explicitly     dataset and profile versions resolved
    allowed view                           required quality evidence valid
lineage complete
```

### 4.1 The refusal rules

| | |
|---|---|
| **no default information profile** | the profile is declared by the strategy version, never inferred |
| **no default as-of** | the decision instant is supplied, never taken from the clock at read time |
| **no "latest" shortcut** | a current value is not a point-in-time value, whatever it is named |
| **missing required evidence** | **BLOCK / REFUSE** — never `zero`, `neutral`, `false`, `empty`, "most recent" or "current value" |
| **optional evidence** | may be absent **only** where the strategy version explicitly declares it optional |

**Substituting a value for missing evidence is the defect this gate exists to prevent.** A zero
that stands in for an unknown reads downstream as a measurement, and every later check treats it as
one.

---

## 5. The deterministic factor matrix

A shared substrate consumed by every module. **This document specifies factor *families* and their
contracts; it specifies no formula and implements nothing.**

### 5.1 Families

**Price / relative / residual momentum**

> 20 / 60 / 126-day returns or the currently governed equivalents · benchmark-relative momentum ·
> sector-relative momentum · market and sector residual momentum · trend persistence ·
> 52-week-high proximity

**Event / earnings**

> standardized earnings surprise or the governed equivalent · revenue surprise · guidance direction ·
> abnormal return and cumulative abnormal return · abnormal volume · margin acceleration · genuine
> point-in-time revisions **only if and when they are qualified** (gate G4)

**Price / volume quality**

> base compactness · volatility contraction · pullback quality · relative volume · trend stability ·
> liquidity · gap behaviour

**Fundamental quality / deterioration**

> sales direction · margin direction · cash-flow direction · accruals · leverage and distress ·
> share-count and dilution · profitability trend

**Risk / context**

> market regime · sector and correlation · event risk · gap risk · borrow and squeeze context ·
> optional future options context (gate G6)

### 5.2 Residualization is a hypothesis, not doctrine

**Raw, relative and residual momentum must be compared empirically.** Residualizing against market
and sector is a research hypothesis with a real cost — it discards exposure that may itself be
compensated, and it introduces an estimation window whose choice is a free parameter. The
specification therefore requires the comparison and **forbids assuming the answer**.

### 5.3 Factor contracts

Every factor definition must carry: an identity; a version; its required data domains; its required
information profile; its lookback and estimation windows; its handling of missing inputs; its
admissibility rules; and its point-in-time semantics. **A factor whose definition version is not
pinned may not inform a candidate.**

---

## 6. The `CandidateIntent` contract

An **immutable** typed record. The terminal output of the Brain, and the whole of it.

### 6.1 Required content

**Identity**

> `candidate_id` · `security_id` · `as_of_time` · `direction` · `environment`

**Strategy**

> `alpha_family` · `strategy_module` · `trade_template` · `strategy_version` ·
> `factor_definition_version`

**Evidence**

> `factor_vector` or a stable reference to it · cross-sectional rank and rank metadata ·
> setup-quality evidence · data-coverage evidence · lineage and source references ·
> deterministic reason codes

**AI**

> research-agent output reference · challenger output reference · source publish times ·
> model version · prompt version · confidence and provenance metadata

**Trade thesis**

> entry condition · invalidation condition · technical stop **reference** · expected holding period

**Risk context**

> upcoming event flags · gap-risk estimate · earnings-carry permission · liquidity ·
> family and factor exposures · sector and correlation cluster

**Short context** — required when `direction` is SHORT

> borrow required · borrow evidence reference and state · fee state · squeeze state · SSR state ·
> recall and buy-in risk · event constraints

**Decision**

> typed status · deterministic reason codes

### 6.2 Forbidden content

`CandidateIntent` **may never** carry:

```text
shares                      dollar amount               final position size
final broker order type     broker route                client order ID
broker order ID             credential                  account number
arbitrary free-form execution instruction
```

**The contract must make it structurally impossible for Brain output to be treated as a broker
ticket.** The absence is a property of the type, not a convention a later author could relax:
there must be no field of any of those meanings, no free-text field an instruction could arrive
through, and no extension point that admits one.

**The technical stop is a reference, not an order.** It names the invalidation level the thesis
rests on. Turning it into a protective order — its type, its route, its size, its identity — is
execution's work, under the deterministic order-identity rules already accepted in
[ADR-0004](../decisions/ADR-0004-deterministic-order-identity-idempotency-and-execution-lifecycle.md).

---

## 7. The Brain decision states

A **closed** typed vocabulary. A status outside it is refused.

| State | Meaning |
|---|---|
| `READY_FOR_RISK_REVIEW` | every deterministic requirement is satisfied; the candidate is handed to portfolio and risk, which decide independently |
| `WATCHLIST` | the thesis stands but the entry condition is not met now |
| `REJECTED` | a deterministic strategy or eligibility rule refused it |
| `BLOCKED_DATA` | the point-in-time reality gate or a coverage requirement refused |
| `BLOCKED_EVENT` | an event or gap constraint refused |
| `BLOCKED_AI` | required AI evidence is missing, malformed, stale or unschematized |
| `BLOCKED_CONTRADICTION` | an unresolved contradiction between evidence sources |
| `BLOCKED_BORROW` | short borrow prerequisites are unsatisfied or unknown |

**`READY_FOR_RISK_REVIEW` is not an approval to trade.** It is the Brain saying it has no
deterministic objection; portfolio and risk may still refuse, and frequently will.

**Forbidden states**, because each invites a reader to act on it:

```text
MAYBE          BUY          SELL          EXECUTE          APPROVED_ORDER
```

A state is added only where tracked architecture clearly requires it, through an ADR.

---

## 8. Candidate consolidation

**The Brain consolidates duplicate economic opportunities before portfolio risk is considered.**

A security that qualifies through residual momentum, industry strength, 52-week-high proximity and
a breakout template is **one economic opportunity with four pieces of evidence** — not four trades.
Presenting it as four is how a single exposure acquires four risk budgets.

### 8.1 Consolidation keys

Two candidates are the same economic opportunity when they share:

```text
the same security               the same direction
an overlapping alpha family     the same underlying catalyst or setup
the same as-of decision window
```

### 8.2 What consolidation preserves

**Module attribution survives consolidation.** The consolidated candidate records **every**
contributing module, template and evidence path, so attribution, health monitoring and research can
still measure each module separately — while downstream capital sees **one** opportunity.

**Competing modules on one security are represented as one candidate with ranked contributing
module attributions**, never as parallel independent candidates. Where two modules disagree on
direction for one security in one decision window, the candidate carries the contradiction and the
compiler returns `BLOCKED_CONTRADICTION`; it does not silently prefer one.

**Consolidation is not netting and not sizing.** It removes double-counting of an opportunity; how
much capital the opportunity receives remains a later, deterministic portfolio decision.

---

## 9. The `StrategySpec` contract

A **versioned, immutable** record. A module's whole definition.

**Identity and status**

> `strategy_id` · `alpha_family` · `version` · lifecycle status · authorized environments

**Direction and horizon**

> LONG / SHORT / BOTH as appropriate · expected holding horizon

**Data**

> required domains · optional domains · information profile · revision view · coverage contracts

**Logic**

> factor dependencies · trade templates · setup eligibility · entry policies · invalidation
> policies · exit-policy references

**Permissions**

> market prerequisite · event prerequisite · gap prerequisite · borrow prerequisite

**Risk tags**

> family exposure · factor exposure · sector exposure · capacity characteristics · risk-policy
> compatibility

**Reproducibility**

> strategy version · factor-definition version · manifest version · code commit · configuration
> identity · model version · prompt version

**Research governance**

> hypothesis identity · baseline · trial budget · success criteria · failure criteria · promotion
> history · rollback history

**A `StrategySpec` with an unpinned version, an unpinned factor-definition version or an
unauthorized environment may not produce a candidate.**

---

## 10. Strategy lifecycle

```text
IDEA
  ->  REGISTERED_HYPOTHESIS
  ->  TAXONOMY_OVERLAP_REVIEW
  ->  DATA_FEASIBILITY
  ->  BASELINE_RESEARCH
  ->  LOCKED_OUT_OF_SAMPLE_VALIDATION
  ->  SHADOW
  ->  AUTOMATED_PAPER
  ->  MICRO_LIVE_CANARY
  ->  SCALED  |  WATCH  |  SUSPENDED  |  RETIRED
```

**What does not advance a lifecycle stage:**

| | |
|---|---|
| **a code module** | existing is not evidence |
| **a backtest** | a result is not a promotion, however good |
| **an AI recommendation** | it is input to a human decision, never the decision |

**Every transition requires immutable evidence and the correct authority.** The evidence is
recorded before the transition, not reconstructed after it, and the authority is the one §25 names
for that specific transition.

**`AUTOMATED_PAPER` is the first order-producing stage**, and reaching it requires human approval —
see §25.

---

## 11. Immutable versioning and open-position pinning

```text
production strategy versions are IMMUTABLE
a modification creates a NEW CHALLENGER VERSION -- never an edit in place
```

**An open position stays governed by the exact versions that opened it.** While a trade is open,
none of these may mutate under it:

> strategy version · factor-definition version · risk-policy version · entry-policy version ·
> exit-policy version

**AI model and prompt versions are recorded wherever AI influenced the candidate**, and so is the
code commit and release identity.

**No uncontrolled online self-modification exists anywhere in the design.** A system that could
rewrite the rule that opened a position could not explain, reproduce or audit why the position
exists.

---

## 12. Champion / Challenger

A **Challenger** is a candidate replacement running beside the production **Champion**.

**A Challenger:**

> observes the same point-in-time opportunity set as the Champion wherever comparison is intended ·
> runs under an immutable version · records overlap and divergence · records factor-exposure
> differences · records trade-population differences · records hypothetical economics · records
> slippage and capacity assumptions · records regime performance · may progress automatically
> **only** through preapproved research and shadow stages

**A Challenger may not:**

> produce order-generating Paper or live actions without approval · silently replace the Champion ·
> increase capital

**Promotion requires a governance packet** — the evidence, the comparison, the exposure analysis,
the assumptions and the failure criteria, assembled for a human to read and decide on. **Automation
may prepare and evidence a promotion; it may not take one.**

---

## 13. Strategy health state machine

```text
HEALTHY  ->  WATCH  ->  DEGRADED  ->  NEW_ENTRIES_REDUCED  ->  NEW_ENTRIES_DISABLED
                                                           ->  SUSPENDED
                                                           ->  RETIRED
```

**Permitted transitions, conceptually.** Degradation may advance one step at a time or jump
directly to `NEW_ENTRIES_DISABLED` or `SUSPENDED` under a preapproved safety rule. **Recovery
toward `HEALTHY` is never automatic past a governed suspension**: leaving `SUSPENDED` requires
human authority, and `RETIRED` is terminal for that version. Reducing or disabling **new entries**
is automatic and always permitted; **restoring** them is not.

**Health inputs**

> expectancy · drawdown · tail losses · opportunity count · turnover · slippage · modeled versus
> realized execution · capacity · factor exposure · cross-strategy correlation · regime behaviour ·
> borrow failures · data-quality incidents · AI contribution · reconciliation incidents

**A degradation creates a research queue entry. It does not automatically mutate strategy
parameters.** Automatic reparameterization in response to recent losses is curve-fitting performed
by a machine at production speed, and it is forbidden.

---

## 14. The AI Research and Challenger contract

Two bounded roles. Both produce **evidence**; neither produces a decision.

### 14.1 Research Agent

**Allowed**

> consume **only already shortlisted** candidates · extract structured facts from approved source
> documents · classify catalysts · assess demand, margins, guidance and competitive position ·
> identify risks · attach source IDs and publication times · output bounded structured evidence

**Forbidden**

> full-universe scanning · selecting arbitrary securities · choosing dollar size · overriding
> deterministic eligibility · overriding risk · sending orders · selecting a broker action

**The shortlist restriction is a boundary, not an optimization.** An AI that may choose which
securities to look at is a scanner, and the scanner is deterministic by design.

### 14.2 Challenger Agent

**Allowed**

> attempt to falsify the thesis · identify contradictions · identify crowding · identify valuation
> risk · identify event risk · identify dilution · identify alternative explanations · score
> evidence quality

**Forbidden**

> approving a trade · weakening deterministic rules · increasing confidence by unsupported
> intuition · sending an order

### 14.3 The AI influence rule

**A deterministic failure cannot be rescued by AI.** No quantity of AI evidence converts a
`BLOCKED_DATA`, `BLOCKED_EVENT`, `BLOCKED_BORROW`, `BLOCKED_CONTRADICTION` or `REJECTED` into
`READY_FOR_RISK_REVIEW`. AI may **remove** a candidate; it may never **restore** one.

**Every AI output must carry**

> source provenance · source publish time · model version · prompt version · structured schema
> version · confidence · evidence quality

**AI outage behaviour**

| | |
|---|---|
| existing deterministic position management | may continue later, under its own authorization |
| AI-dependent **new entries** | **fail closed** |

---

## 15. The deterministic decision compiler

The Brain's final stage. It validates, in this order, and stops at the first refusal:

```text
 1  point-in-time reality gate
 2  authorized strategy version
 3  factor-definition version
 4  required data coverage
 5  strategy and module eligibility
 6  trade-template match
 7  duplicate-economic-exposure consolidation
 8  AI schema and provenance, where required
 9  unresolved contradictions
10  market permission context
11  event and gap context
12  short borrow prerequisite, if applicable
13  immutable reason-code construction
```

**Order is the property.** A later stage never runs after an earlier refusal, so an unresolved
point-in-time gate never reaches a borrow check and an unauthorized strategy version never reaches
AI evidence.

**Its output is a `CandidateIntent` status, and nothing else.** It must not output:

```text
share count      dollars       final risk amount     leverage
order type       broker route  stop order            take-profit order
client order ID
```

Those belong to the later portfolio, risk and execution layers.

---

## 16. The Brain to portfolio/risk to execution handoff

```text
BRAIN                     |  PORTFOLIO / RISK                |  EXECUTION
                          |                                  |
why does the opportunity  |  can the portfolio own it        |  how to route
    exist                 |  how much risk                   |  which order type
why enter now             |  how many shares                 |  how to protect fills
what evidence supports    |  family/sector/correlation       |  how to reconcile
    or rejects it         |      constraints                 |      broker state
what deterministic status |  event and gap budget            |
what risk context         |  borrow constraint               |
                          |  is final trade risk permitted   |
```

**No single module may answer all three classes of question.** That separation is what makes "AI
cannot size or route" checkable rather than aspirational, and it is the typed expression of the
locked principle in §2.

---

## 17. The initial research modules

**Documented as research modules with stated premises. No module is claimed to work, and none is
implemented or authorized.**

### 17.1 Breakout Long

**Economic premise (hypothesis):** momentum continuation.

**Entry-template concepts:** strong trend · compact base or resistance · relative or residual
strength · price confirmation · volume confirmation · acceptable event and gap context.

**Research focus:** false breakouts · gap risk · slippage · factor crowding · regime dependency.

### 17.2 Pullback Long

**Economic premise (hypothesis):** continuation after a controlled retracement.

**Concepts:** established trend · controlled retracement · contracting pullback volume ·
structural support · renewed demand confirmation.

**Research focus:** stop efficiency · regime sensitivity · reversal quality · **distinction from
the breakout population** — which is gate G7's question.

### 17.3 PEAD Long

**Economic premise (hypothesis):** post-event information diffusion.

**Concepts:** positive earnings, revenue or guidance evidence · abnormal return and volume ·
post-gap stabilization or continuation.

**No pre-earnings prediction.** The module trades **after** the information event.

### 17.4 PEAD Short

**Concepts:** negative surprise or guidance · negative abnormal return · failed stabilization ·
**borrow and squeeze qualification**.

### 17.5 Deterioration Short

**Requires all four:** negative fundamental or event evidence · negative relative or residual
momentum · an execution trigger · a qualified borrow and squeeze state.

**Possible evidence:** weak revenue · margin deterioration · cash-flow deterioration · high
accruals · dilution · negative guidance · weak sector context.

**Bottom-decile momentum alone is not short authorization.** Weak price action is *timing*
information; it is not an economic reason a short return exists.

---

## 18. Market regime and permission context

A **versioned** `MarketRegime` / `MarketPermission` context consumed by the Brain, the compiler and
later by the risk engine.

**It may include:** broad trend · breadth · realized volatility · momentum-crash state · factor
reversal state · sector regime · event stress.

**The Brain may use regime context to** rank · block · downgrade · defer · tag.

**The Brain does not size gross exposure.** Exposure scaling stays in the later deterministic
portfolio and risk logic, on a versioned regime input the Brain merely records.

---

## 19. The event and gap contract

**Recorded by the Brain:** upcoming earnings or event flag · event timestamp quality · overnight
gap-risk estimate or reference · correlated event cluster · earnings-carry permission.

**Default architectural principles:**

| | |
|---|---|
| **Breakout and Pullback do not carry through earnings** | unless a separately researched and separately authorized rule permits it |
| **PEAD trades after the information event** | never before it |

**The Brain records the context; the later risk logic enforces the sizing and the budget.** An
event flag on a candidate is information, not an allocation decision.

---

## 20. The short-side contract

**SHORT is a separate evidence path, not a stricter long path.**

**Required short context**

> borrow availability state · borrow fee state · shortable quantity state or reference · fee
> deterioration · squeeze and crowding state · SSR state · recall and buy-in state · corporate
> action context · binary-event context

**The Brain may return `BLOCKED_BORROW`.**

**The Brain may not infer borrow from price behaviour.** Hard-to-borrow conditions and price action
correlate; correlation is not a borrow record, and a candidate whose borrow state is unknown is
blocked rather than assumed.

**The live pre-submit borrow recheck belongs to execution and risk, not to the Brain.** Borrow is
a perishable fact: a state observed at decision time is evidence, and the state at submission time
is the one that governs.

**Gate G5 — historical borrow qualification — is OPEN**, and no short module may be researched to
promotion without it.

---

## 21. The optional options-overlay boundary

**Options information stays out of the initial core dependency**, and is specified only as a future
optional research and risk context.

**Potential future states:** `NORMAL` · `ELEVATED_EVENT_RISK` · `EXTREME_TAIL_PRICING` ·
`SQUEEZE_RISK` · `OPTIONS_DATA_UNRELIABLE`.

**Potential future research features:** ATM IV · implied move · IV change and percentile · skew ·
term structure · options liquidity.

**No options trading is authorized** (`CLAUDE.md` §4.14). **Options data is not required for the V1
Brain**, and gate **G6** governs any production influence from it.

---

## 22. Research methodology contract

Standards every future Brain research task must satisfy.

```text
point-in-time data only            survivorship-aware universe
revision-aware evidence            immutable research manifests
a NAMED BASELINE FIRST             locked out-of-sample
walk-forward                       purging where overlapping horizons require it
parameter-neighborhood stability   recorded trial count
multiple-testing controls          commissions
spread                             slippage
realistic fills                    liquidity
borrow cost                        gap stress
regime decomposition               sector decomposition
factor decomposition               capacity analysis
```

**A named baseline comes first.** A strategy that is not compared against a stated, simpler
alternative has not been shown to add anything.

**The trial count is recorded, not remembered.** Multiple-testing control is meaningless if the
denominator is whatever the researcher recalls.

**No strategy currently passes any of these tests, because none has been run.**

---

## 23. The initial experiment matrix

The first research questions, **specified and not run**.

| | Question |
|---|---|
| **A** | raw momentum vs relative momentum vs market/sector residual momentum |
| **B** | Breakout Long vs Pullback Long vs an immediate ranked-entry baseline |
| **C** | PEAD SUE-only baseline vs SUE + CAR + volume + guidance |
| **D** | the short engine with vs without borrow and squeeze filters |
| **E** | deterministic-only vs structured evidence vs structured evidence + LLM interpretation |
| **F** | the core strategies vs an optional future options overlay |

**No result is asserted by this document, and none exists.** Experiment B is the evidence gate
**G7** requires; experiment F is bounded by **G6**; experiment C's revision-enhanced variants are
bounded by **G4**; experiment D is bounded by **G5**.

---

## 24. Portfolio and risk parameters — reference only

Reproduced so the interfaces are unambiguous. **Risk authority is not relocated into the Brain by
reproducing them.**

| Control | Current governed research value |
|---|---|
| Strategy capital | **USD 80,000** |
| Broker equity | **informational for reconciliation only — never sizing authority** |
| Long planned risk / trade | 0.50% |
| Short planned risk / trade | 0.25% |
| Maximum open planned risk | approximately 5% |
| Maximum individual position | approximately 8–10% |
| Initial gross short | at most 25% |
| Volatility target | approximately 10–12% annualized |
| Leverage | **NONE initially** |
| Averaging down | **DISABLED** |
| Pyramiding | confirmed winners only |

**The Brain must not calculate a final position size from these values.** It may carry the context
tags the later risk engine needs. These are **research parameters, not performance expectations**.

---

## 25. Human and automatic authority matrix

**Automatic, within approved bounds**

> normal candidate generation · deterministic eligibility · Research Agent · Challenger Agent ·
> health monitoring · research hypothesis generation · approved-scope research · shadow challenger
> operation · fail-closed blocking · preapproved risk reduction and disabling of new entries

**Human approval required**

> strategy promotion to order-producing Paper · Paper to micro-live · micro-live to scaled live ·
> production model replacement · production parameter release · capital increase · risk increase ·
> leverage · short-exposure increase · provider or licence purchase · new production data
> dependency · resume from a governed suspension · any change to kill-switch behaviour

**Self-maturing is not self-governing.** The system may prepare, evidence and recommend every item
in the second list. It may take none of them.

**Emergency reduction is automatic; emergency flattening is not the Brain's.** The kill switch
remains independent of the AI, and the human retains direct control of it.

---

## 26. Security and failure invariants

```text
no credential in CandidateIntent            no private account ID in Brain output
no broker credential                        no order ID
no direct network requirement for the deterministic compiler
deterministic replay from immutable inputs
```

**Every one of these blocks:**

| Condition | |
|---|---|
| missing required source | `BLOCKED_DATA` |
| malformed AI output | `BLOCKED_AI` |
| stale AI evidence | `BLOCKED_AI` |
| stale market or context data | `BLOCKED_DATA` |
| unauthorized strategy version | `REJECTED` |
| unrecognized version | `REJECTED` |
| unknown decision state | refused at construction |
| schema mismatch | refused at construction |

**No implicit fallback to a latest strategy, model or prompt exists.** An unpinned version is a
refusal, never a resolution.

**Every failure preserves auditable reason codes.** A refusal whose reason is not recorded is
indistinguishable from a crash.

---

## 27. Audit and journal specification

Journaled per candidate:

```text
candidate ID                       as-of
strategy / module / template       strategy version
factor-definition version          profile / dataset manifest
source lineage IDs                 deterministic factor snapshot or reference
AI source IDs and publish times    model / prompt versions
Research output reference          Challenger output reference
contradictions                     reason codes
final Brain status                 risk-context tags
code commit / release identity
```

**Provider payload bytes are never written to the operational journal.** Licensed vendor rows stay
inside the private deployment boundary (`CLAUDE.md` §4.22); the journal carries **references and
lineage identifiers**, and a reference is not a row.

---

## 28. What this specification does not do

```text
implements NOTHING                        authorizes NOTHING
selects no provider                       closes no gate
claims no alpha                           establishes no expected return
runs no backtest                          reads no provider data
reads no private artifact                 touches no AWS or Terraform
contacts no broker                        produces no order
```

| | |
|---|---|
| Brain specification | **ACCEPTED EFFECTIVE ON MERGE OF PR #70** |
| Brain runtime implementation | **NOT STARTED / NOT AUTHORIZED** |
| Core strategy implementation | **NOT STARTED / NOT AUTHORIZED** |
| Backtesting | **NOT STARTED** |
| Run B | **NOT RUN / NOT AUTHORIZED** — earliest approved target 2026-09-12 |
| Combined assessment | **NOT RUN / NOT AUTHORIZED** |
| P1-P9 | **UNEVALUATED** |
| Data correctness and quality | **NOT ESTABLISHED** |
| G1 / G2 | **OPEN / OPEN** |
| Provider selected | **NONE** |
| Phase 3 | **NOT COMPLETE** |
| CONTROL publication | **DEFERRED** |
| Live trading | **HARD-DISABLED** |

**Specification, implementation, research, deployment and execution are five separate gates**, and
they are never collapsed into one. This document opens only the first, and only on independent
review and merge.

**"Brain started" does not mean runtime coding started.** This document exists; the Brain does not.
