# Cockpit — traceability matrix and delivery sequencing

**Status: ACCEPTED SPECIFICATION EFFECTIVE ON MERGE OF PR #71, and PROPOSED until that merge —
NOT IMPLEMENTED, NOT AUTHORIZED.**

Every one of the **36 Cockpit V1 product areas** is traced here to its specification section, its
presentation, its read-model owner, its synthetic availability, its real-feed dependency and gate,
its implementation cycle, and its observable acceptance criteria.

**All 36 areas remain in V1 product scope.** **A specified future feed is not an implemented feed**,
and an execution- or control-dependent feature carries an explicit unavailable state until its
dependencies and its authorizations exist.

**Introduced by** [ADR-0027](../decisions/ADR-0027-cockpit-and-feedback-architecture-and-governance.md).

---

## 1. Matrix A — identity, specification, presentation and ownership

| # | Area | Specification | Executive | Operator | Read-model owner and principal input |
|---|---|---|---|---|---|
| 1 | Executive Overview | [spec](cockpit-v1-specification.md) Area 1 | **primary surface** — tiers 1–3 | same data, added detail and drill-down | `ExecutiveOverview` — composite of portfolio, risk, health, data quality, operations, governance |
| 2 | Portfolio Performance | Area 2 | equity, return, drawdown headline | full curves, rolling windows, heatmap, ratios | `PerformanceSeries` / `PerformanceSummary` — recorded valuations and cash flows |
| 3 | Positions & Exposure | Area 3 | exposure summary tile | per-position table, groupings, clusters | `PositionSnapshot` / `ExposureAggregate` — recorded positions and lots |
| 4 | Strategy Performance | Area 4 | per-family headline | per-module, per-version, sliced | `StrategyPerformance` — trade outcomes by module and version |
| 5 | Strategy Health | Area 5 | health state and required action | inputs, transitions, reasons, history | `StrategyHealth` — recorded health transitions |
| 6 | Signal / Candidate Funnel | Area 6 | conversion headline | full funnel, reason distributions, both axes | `CandidateFunnel` — journaled Brain decisions |
| 7 | Candidate Detail | Area 7 | not surfaced | full explainability and lineage | `CandidateDetail` — one journaled `CandidateIntent` |
| 8 | Missed Opportunities | Area 8 | count and top pattern | causes, counterfactuals, windows, assumptions | `MissedOpportunity` — non-entered candidates plus registered windows |
| 9 | Execution Quality | Area 9 | slippage and latency headline | per-order and per-fill mechanics | `ExecutionQuality` — order and fill events |
| 10 | Broker / Reconciliation | Area 10 | reconciliation state tile | full diff, orphans, sessions, incidents | `ReconciliationStatus` — recorded reconciliation results |
| 11 | Market / Regime | Area 11 | regime label and stress | full regime decomposition and history | `MarketRegime` — versioned regime context |
| 12 | Risk Dashboard | Area 12 | open planned risk and breaker state | full constraint set and tiers | `RiskSnapshot` — recorded risk-engine outputs |
| 13 | Short-Side Dashboard | Area 13 | gross short and borrow alerts | borrow, squeeze, SSR, recall, statistics | `ShortSideSnapshot` — borrow and short exposure records |
| 14 | Research / Backtesting | Area 14 | runs-ready count | full registry, manifests, decompositions | `ResearchRun` — immutable research manifests |
| 15 | Champion / Challenger | Area 15 | readiness tile | overlap, divergence, exposure differences | `ChampionChallengerComparison` — paired version results |
| 16 | Feedback Loop | Area 16 | pipeline stage counts | per-stage items, blockages, authorizations | `FeedbackPipeline` — stage records |
| 17 | Research Queue | Area 17 | queued count and top priority | full queue with triggers and evidence | `ResearchQueueItem` — queue records |
| 18 | Hypothesis Registry | Area 18 | not surfaced | registrations, amendments, linked results | `HypothesisRegistration` — immutable preregistrations |
| 19 | Governance Packets | Area 19 | packets awaiting review | full packet and recorded decision | `GovernancePacket` / `DecisionRecord` |
| 20 | Strategy Version Registry | Area 20 | not surfaced | versions, lineage, pinning, rollback | `StrategyVersion` — registry records |
| 21 | AI Contribution Analytics | Area 21 | contribution headline | matched arms, provenance, outages | `AiContribution` — matched-arm results |
| 22 | Data Quality / PIT | Area 22 | freshness and quality tile | coverage, lineage, profiles, incidents | `DataQuality` — recorded quality evidence |
| 23 | System Operations | Area 23 | system health tile | jobs, queues, latency, timeline | `SystemJob` / `SystemIncident` |
| 24 | Project / Qualification Governance | Area 24 | phase and next required event | full gate map, ADR states, blockers | `QualificationStatus` — **tracked repository governance facts** |
| 25 | Environment / Deployment Maturity | Area 25 | maturity summary | per-strategy stage and outstanding gates | `MaturityStatus` — governance records |
| 26 | Audit Trail | Area 26 | not surfaced | immutable event timeline | `AuditEvent` — immutable audit events |
| 27 | Alerts / Exceptions | Area 27 | open alert count | full feed, severity, dedup, resolved | `Alert` — alert records |
| 28 | Executive Attention Required | Area 28 | **first viewport, ranked** | same list with full evidence | `AttentionItem` — composite |
| 29 | Executive / Operator Modes | Area 29 | the mode itself | the mode itself | presentation over all read models |
| 30 | Global Command Palette | Area 30 | available | available | search across read models |
| 31 | Ask KalpaMani | Area 31 | available, cited | available, cited with lineage | bounded typed analytics over authorized read models |
| 32 | Modern Executive UX | Area 32 | the presentation contract | the presentation contract | [`ui-ux-specification.md`](ui-ux-specification.md) |
| 33 | Cockpit Read-Model Architecture | Area 33 | not surfaced | provenance and projection state | [`read-model-contracts.md`](read-model-contracts.md) |
| 34 | Initial V1 Safety Boundary | Area 34 | stated on screen | stated on screen | the boundary itself |
| 35 | Future Human Control Plane | Area 35 | not surfaced | **inert specification only** | none — no handler, **no control route** |
| 36 | Trade History & Trade Detail | Area 36 | recent trades tile | full ledger and complete trade story | `TradeSummary` / `TradeDetail` / `TradeLifecycle` |

---

## 2. Matrix B — availability, gates, cycle and acceptance

**Synthetic availability** is what the area shows over deterministic repository-owned fixtures.
**Real-feed dependency and gate** is what must exist and be authorized before real data appears.

| # | Area | Synthetic availability | Real-feed dependency and gate | Cycle | Observable acceptance criteria |
|---|---|---|---|---|---|
| 1 | Executive Overview | **full** | every contributing subsystem; governance parts already real | **C4** | every tile renders its own availability and as-of; strategy capital and broker equity shown separately, never substituted; five ten-second answers in the first viewport at 1440 × 900 |
| 2 | Portfolio Performance | **full** | portfolio runtime — **NOT IMPLEMENTED** | **C5** | cash flows never appear as profit; a backtest series and a live series never share a line; every ratio shows its denominator or `INSUFFICIENT_OBSERVATIONS` |
| 3 | Positions & Exposure | **full** | portfolio runtime — **NOT IMPLEMENTED** | **C5** | borrow state comes from a record, never from price; groupings are displayed and never computed as a permitted exposure |
| 4 | Strategy Performance | **full** | strategy runtime — **NOT IMPLEMENTED**; **G7 OPEN** | **C5** | Breakout and Pullback keep separate module attribution and share family context; no diversification or alpha claim without evidence; every result attributed to an exact strategy version |
| 5 | Strategy Health | **full** | strategy runtime — **NOT IMPLEMENTED** | **C7** | only the seven ADR-0026 health states render; the view causes no transition; a degradation shows the research queue entry it created |
| 6 | Signal / Candidate Funnel | **full** | Brain runtime — **NOT IMPLEMENTED** | **C6** | the eight Brain states render as a closed set; downstream states render on a **separate** axis; `READY_FOR_RISK_REVIEW` is not presented as a successful end state |
| 7 | Candidate Detail | **full** | Brain runtime — **NOT IMPLEMENTED** | **C6** | no share count, dollar amount, order type or route appears anywhere; the technical stop renders as a reference; AI evidence never explains a restored candidate |
| 8 | Missed Opportunities | **full** | Brain runtime + price history — **NOT IMPLEMENTED**; provider **G1 OPEN** | **C6** | every counterfactual displays its window, assumptions and cost treatment; an incomplete path renders `PARTIAL`; no false-negative rate without a defined population |
| 9 | Execution Quality | **full** | execution runtime — **NOT IMPLEMENTED**; **Paper expansion NOT AUTHORIZED** | **C8** | no broker-native order id is rendered anywhere; slippage names its reference price and side convention |
| 10 | Broker / Reconciliation | **full** | broker session — **NOT IMPLEMENTED / NOT AUTHORIZED** | **C8** | no brokerage credential or session exists in any Cockpit path; broker equity labelled informational; a past reconciliation shows its as-of time |
| 11 | Market / Regime | **full** | regime engine + provider data — **NOT IMPLEMENTED**; **G1, G2 OPEN** | **C5** | the regime is displayed from a versioned context and never recomputed; the view sizes no exposure |
| 12 | Risk Dashboard | **full** | risk engine — **NOT IMPLEMENTED** | **C5** | strictly read-only; governed research values displayed unchanged and labelled as research parameters |
| 13 | Short-Side Dashboard | **full** | borrow data — **NOT IMPLEMENTED**; **G5 OPEN**; short research **NOT AUTHORIZED** | **C5** | borrow availability is never inferred from price; unknown borrow renders as unknown or `BLOCKED_BORROW`, never as available |
| 14 | Research / Backtesting | **full** | research runtime + qualified data — **NOT STARTED**; **G1, G2 OPEN** | **C7** | a run without a named baseline renders incomplete; trial count read from the record; synthetic runs excluded from every real comparison |
| 15 | Champion / Challenger | **full** | research runtime — **NOT IMPLEMENTED** | **C7** | readiness is displayed and never conferred; no promotion path exists from this view |
| 16 | Feedback Loop | **full** | learning engine — **NOT IMPLEMENTED** | **C7** | no stage advances from this screen; each stage shows the authorization it awaits |
| 17 | Research Queue | **full** | learning engine — **NOT IMPLEMENTED** | **C7** | every item shows its trigger, its named baseline and the authorization it is waiting on |
| 18 | Hypothesis Registry | **full** | learning engine — **NOT IMPLEMENTED** | **C7** | a registration is immutable; results render as linked appended records; the amendment chain is visible; failed and abandoned runs count against the budget |
| 19 | Governance Packets | **full** | governance runtime — **NOT IMPLEMENTED** | **C7** | read-only; no approve or reject control exists; a recommendation is labelled as input to a human decision |
| 20 | Strategy Version Registry | **full** | strategy runtime — **NOT IMPLEMENTED** | **C7** | production versions render immutable; open-position pinning is explicit |
| 21 | AI Contribution Analytics | **full** | AI agents — **NOT IMPLEMENTED**; experiment E **not run** | **C7** | matched comparisons with stated uncertainty; no causal alpha claim; small populations render `INSUFFICIENT_OBSERVATIONS` |
| 22 | Data Quality / PIT | **full** | provider data — **NOT IMPLEMENTED**; **G1, G2 OPEN**; **P1–P9 UNEVALUATED** | **C8** | only the three existing profiles render; no default profile is invented; Sharadar price data never renders as `PUBLIC_PIT` |
| 23 | System Operations | **full** | service runtime — **NOT IMPLEMENTED** | **C8** | no start, stop, retry or trigger control exists; last success carries its as-of time |
| 24 | Project / Qualification Governance | **full** | **already real** — tracked repository governance facts | **C4** | public-safe facts only; **P1–P9 render `UNEVALUATED`**; each gate read independently; Run B authorization and its date gate render as two separate facts |
| 25 | Environment / Deployment Maturity | **full** | strategy governance records — **NOT IMPLEMENTED** | **C4** | selecting an environment advances no maturity; the stage-to-lifecycle mapping matches the extension exactly; Shadow shows no order authority |
| 26 | Audit Trail | **full** | platform events — **NOT IMPLEMENTED** | **C8** | the projection is rebuildable and separately identified from source events; no licensed content appears in an audit payload; deletion renders as a tombstone with governance intact |
| 27 | Alerts / Exceptions | **full** | platform alerts — **NOT IMPLEMENTED** | **C8** | one condition produces one alert with an occurrence count; **no external notification integration exists** |
| 28 | Executive Attention Required | **full**, governance items real | contributing subsystems | **C4** | every item shows what happened, why it matters, impact, evidence and a permitted governance action; ranked and deduplicated against alerts |
| 29 | Executive / Operator Modes | **full** | none — presentation | **C3** | both modes read the same read models; switching preserves filters, scoping and drill-down context |
| 30 | Global Command Palette | **full** | entities follow their own areas | **C3** foundation, **C9** full | opens from every route; **no state-changing verb exists**; results respect environment and source scoping |
| 31 | Ask KalpaMani | **demonstration only** | authorized read models — **NOT IMPLEMENTED** | **C9** | no arbitrary SQL or code; no mutation; no broker vocabulary; **no licensed-derived payload leaves for an external model**; abstains when data is missing |
| 32 | Modern Executive UX | **full** | none — presentation | **C3** foundation, **C10** polish | U1–U20 in the UI specification |
| 33 | Cockpit Read-Model Architecture | **contracts only** | none — architecture | **C3** | every response carries the full envelope; an unknown `schema_version` is rejected, not rendered |
| 34 | Initial V1 Safety Boundary | **enforced** | none — boundary | **C3**, held in every cycle | no endpoint, handler or route exists for any forbidden action; asserted by governance tests |
| 35 | Future Human Control Plane | **inert display only** | separate control architecture — **NOT AUTHORIZED** | **C3** inert page, later cycle for design | every control is inert; **no handler and no control API route exists**; a kill-switch representation is labelled as not a kill switch |
| 36 | Trade History & Trade Detail | **full** | portfolio and execution runtimes — **NOT IMPLEMENTED** | **C5** history and basic detail, **C6** full lifecycle | a fill is never counted as a trade; a partial exit reduces rather than closes; a missing event renders as a gap and never as an inference; the four concepts stay on separate screens; **the owner's manual activity is never adopted as platform evidence** |

---

## 3. Delivery sequencing

**Each cycle has its own independent implementation review and merge gate.** A cycle authorizes
nothing beyond itself, and reaching one does not begin the next.

| Cycle | Scope |
|---|---|
| **C1** | **this cycle** — architecture, specifications, contracts, UX and governance. **No implementation** |
| **C2** | **fresh independent review**, corrections, and merge of C1 |
| **C3** | application foundation · design system · Executive and Operator shell · navigation · environment and source badges · command foundation · synthetic contracts |
| **C4** | Executive Overview · Attention Required · Project and Qualification Governance · Environment and Deployment Maturity |
| **C5** | Portfolio Performance · Positions and Exposure · Strategy Performance · Risk · Short-Side · Market and Regime · **Trade History and basic Trade Detail** |
| **C6** | Signal and Candidate Funnel · Candidate Detail and Explainability · Missed Opportunities · **complete synthetic Trade Detail lifecycle and chart drill-down** |
| **C7** | Research and Backtesting · Feedback Loop · Research Queue · Hypothesis Registry · Champion/Challenger · Strategy Health · Governance Packets · Strategy Version Registry · AI Contribution Analytics |
| **C8** | Data Quality and PIT · System Operations · Audit Trail · Alerts and Exceptions · provenance surfaces · **synthetic execution and reconciliation views** |
| **C9** | Ask KalpaMani · advanced read-only search and navigation |
| **C10** | visual polish · accessibility · responsiveness · performance · **synthetic end-to-end and visual regression** |

**No area is dropped because it depends on something later.** Every area appears in a cycle, and an
area whose real feed does not exist is delivered as a labelled synthetic view with its explicit
unavailable states — which is the point of specifying the unavailable-state contract at all.

**Real feeds stay separately gated even where a demonstration view exists.** A screen that renders
`NOT_IMPLEMENTED` correctly is finished work; connecting it to a real producer is a different
authorization, and in most cases a different gate as well.

---

## 4. The September 11 planning target

**A substantial, polished synthetic Cockpit V1 is targeted for 11 September 2026**, ahead of the
2026-09-12 earliest approved Run B target.

**It is a planning target and nothing more.** It is **not** an excuse to skip acceptance criteria,
**not** permission to reduce scope silently, and **not** a claim of real-data readiness. **A
polished synthetic Cockpit is a demonstration over deterministic fixtures**, and on 11 September it
would still be exactly that.

**The two dates are unrelated in authority.** **Passing 2026-09-12 is not execution
authorization** — Run B requires its own fresh prompt and its own written authorization, the
combined assessment requires another, and **the at least eight calendar day Run A to Run B
separation is unchanged**.

---

## 5. Working-mode boundaries for later cycles

| Work | Mode |
|---|---|
| repository documentation, specification and interface work | ordinary authorized working mode |
| private artifacts, AWS, provider, brokerage or infrastructure work | **its own authorization, and an appropriate manual-mode task** |

**A Cockpit implementation cycle is not an authorization to touch a provider, a broker, AWS or a
private artifact**, whatever a screen it is building would eventually display.

---

## 6. Status

```text
Cockpit specification:                   ACCEPTED EFFECTIVE ON MERGE OF PR #71
Cockpit implementation:                  NOT STARTED / NOT AUTHORIZED
areas in V1 scope:                       36
areas traced:                            36
Brain runtime:                           NOT STARTED / NOT AUTHORIZED
backtesting:                             NOT STARTED
Run A retry:                             NOT AUTHORIZED / NOT RUN
Run B:                                   NOT RUN / NOT AUTHORIZED
Run B earliest approved target:          12 SEPTEMBER 2026
Run A to Run B separation:               AT LEAST 8 CALENDAR DAYS
combined assessment:                     NOT RUN / NOT AUTHORIZED
P1-P9:                                   UNEVALUATED
data correctness and quality:            NOT ESTABLISHED
G1 / G2:                                 OPEN / OPEN
provider selected:                       NONE
Phase 3:                                 NOT COMPLETE
CONTROL:                                 DEFERRED
live trading:                            HARD-DISABLED
```

**Every cycle from C3 onward is a separate written authorization.** **Specification,
implementation, research, deployment and execution are five separate gates**, and they are
never collapsed into one.
