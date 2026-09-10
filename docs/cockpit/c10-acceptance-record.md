# Cockpit V1 — C10 acceptance record

**Status: PROPOSED — carried by an open pull request, and carrying no authority until that pull
request is merged.** Nothing here accepts a cycle, closes a gate, selects a provider or authorizes
an operation. It began as an **author's requirement-by-requirement assessment**, written so an
independent reviewer could check each row rather than take a summary on trust.

**It has since been independently reviewed, and the review corrected it.** Rows the review changed
say so in place, and §11 records what the review ran, what it found and what it could not assess.
**A reviewed record is still not an acceptance decision**: acceptance is a human act, and this
document is an input to one.

**It records what was found, not what was hoped for.** Where a requirement is unmet, partial,
blocked or unassessed, it says so in those words and names what it waits on.

---

## 1. What this record is, and what it is not

| | |
|---|---|
| **it is** | one row per accepted requirement, with the clause it comes from, where it is implemented, what data stands behind it, the evidence that it holds, and its disposition |
| **it is** | an **observational** assessment. Every disposition below is about a screen over deterministic repository-owned fixtures and tracked repository facts |
| **it is not** | an acceptance decision. Acceptance is a human act on an independently reviewed pull request, and this document is an input to one |
| **it is not** | a claim that any producing subsystem exists. **No Brain, strategy, portfolio, risk, execution, broker, research, learning, governance, alert or audit runtime exists, and none is authorized** |
| **it is not** | a performance or accessibility conformance claim. §7 states exactly what was measured, under what conditions, and what was not assessed at all |
| **it is not** | evidence about any strategy, provider, broker or market. **No provider is selected, P1–P9 are UNEVALUATED, and data correctness is NOT ESTABLISHED** |

---

## 2. The disposition vocabulary

**Five dispositions, and they are not interchangeable.** These are **documentation dispositions**:
they classify rows in this record. **They are not a runtime vocabulary**, they appear in no payload,
and nothing renders them.

| Disposition | Means |
|---|---|
| **`IMPLEMENTED`** | implemented and evidenced within the accepted observational scope — the criterion holds, and a named test or a named capture shows it holding |
| **`ACCEPTED_UNAVAILABLE`** | the accepted behaviour **is** an explicit unavailable state, because the producing subsystem does not exist, and the screen renders that state correctly with its named dependency. **Finished work under the accepted scope** — the traceability matrix says so in as many words: *"A screen that renders `NOT_IMPLEMENTED` correctly is finished work; connecting it to a real producer is a different authorization"* |
| **`PARTIAL`** | some of the requirement holds and some does not, or a presented fact the specification names is not carried at all. **Never rounded up** |
| **`BLOCKED_CONTRACT`** | an accepted contract decision does not answer the question the requirement asks, so no implementation can be correct until a decision is taken |
| **`NOT_ASSESSED`** | this cycle did not assess it, and does not claim it. **Never reported as a pass** |

**`ACCEPTED_UNAVAILABLE` and `PARTIAL` are the pair this record exists to keep apart.** A screen that
correctly reports a missing producer has met its criterion; a screen that cannot produce a value the
specification asks it to *present* has not. Collapsing the two in either direction is the failure
mode: calling every unavailable state a defect would condemn the whole Cockpit, and calling every
absent value an accepted absence would report the two outstanding C5 requirements as delivered.

---

## 3. Method

**Each row was checked against the accepted clause, not against a previous report's summary.** The
clauses come from
[`traceability-matrix.md`](traceability-matrix.md) Matrix B — *observable acceptance criteria*, which
is the acceptance instrument — with the functional description in
[`cockpit-v1-specification.md`](cockpit-v1-specification.md) and the presentation contract in
[`ui-ux-specification.md`](ui-ux-specification.md) read beside it.

**Implementation was traced past route existence.** For each area the record follows the route to the
component, the component to the read model it consumes, and the read model to the fixture or tracked
fact behind it. A route that renders is not evidence that a page uses its intended read-model
boundary, that a detail link identifies the intended subject, that a filter operates over its declared
population, or that a chart and its table agree — each of those is a separate check, and the tests
named in the evidence column are the ones that make it.

**A placeholder is not an implementation, and a canned response is not a feature.** Where a value
could not be produced, the row says which stage refused and what it waits on.

**The accepted specifications are read, and they are not edited.** Their own status blocks still read
*"Cockpit implementation: NOT STARTED / NOT AUTHORIZED"* and *"accessibility conformance: NOT
MEASURED / NOT CLAIMED"*, because those sentences are what the specification cycle wrote about the
days it was written and an accepted document is not rewritten by a later slice. **The current status
lives in `README.md` and `CLAUDE.md`**, which is where every cycle since C3 has recorded it.

---

## 4. The thirty-six product areas

**Data scope** is what actually stands behind the screen today: `SYNTHETIC` for repository-owned
deterministic fixtures, `REPOSITORY_TRACKED` for real tracked governance facts, `UNAVAILABLE` where
no value exists and the state is rendered instead.

| # | Area | Cycle | Route | Read model | Data scope | Evidence | Disposition | Remaining dependency |
|---|---|---|---|---|---|---|---|---|
| 1 | Executive Overview | C4 | `/` | `ExecutiveOverview` | SYNTHETIC + REPOSITORY_TRACKED | `e2e/c4-executive.spec.ts`, `e2e/u1-first-viewport.spec.ts`, `screenshots-c10/*-overview-*` | `IMPLEMENTED` | every operational producer, for real inputs |
| 2 | Portfolio Performance | C5 + follow-up | `/portfolio/performance` | `PerformanceSeries`, `PerformanceSummary` | SYNTHETIC | `e2e/c5-portfolio.spec.ts`, `e2e/c5-followup.spec.ts`, `tests/c5-followup-rendering.test.tsx` | `PARTIAL` | **named benchmarks SPY, QQQ and IWM are UNAVAILABLE** — no provider is selected, **G1 OPEN**. Every other Area 2 criterion holds |
| 3 | Positions & Exposure | C5 | `/portfolio/positions` | `PositionSnapshot`, `ExposureAggregate` | SYNTHETIC | `e2e/c5-portfolio.spec.ts`, `tests/c5-rendering.test.tsx` | `PARTIAL` | the matrix criteria hold; **three facts the Area 3 narrative names — earnings proximity, liquidity and capacity — are carried by no field of `PositionSnapshot`**. Each needs provider data (**G1 OPEN**) or the capacity model. See §6.3 |
| 4 | Strategy Performance | C5 + ADR-0032 | `/strategy/performance` | `StrategyPerformance` | SYNTHETIC, capacity UNAVAILABLE | `e2e/adr-0032-measurements.spec.ts`, `tests/adr-0032-measurements.test.ts` | `PARTIAL` | **`strategy.capacity` is NOT OBTAINABLE.** The §12.3.3 admission gate is enforced on the read path and refuses at its required-input stage; **nine required inputs do not exist**, **G1 and G5 OPEN** |
| 5 | Strategy Health | C7 + ADR-0032 | `/strategy/health` | `StrategyHealth` | SYNTHETIC, several inputs UNAVAILABLE | `e2e/c7-research.spec.ts`, `e2e/adr-0032-measurements.spec.ts` | `PARTIAL` | the seven states, the transitions, the queue entry and the rolling tail loss all hold; **the capacity health input is NOT OBTAINABLE through the same gate**. Turnover, slippage, modelled-versus-realized execution and regime behaviour are `ACCEPTED_UNAVAILABLE` with named producers |
| 6 | Signal / Candidate Funnel | C6 | `/signals/funnel` | `CandidateFunnel` | SYNTHETIC | `e2e/c6-signals.spec.ts`, `tests/c6-read-models.test.ts` | `IMPLEMENTED` | the Brain runtime, for real decisions |
| 7 | Candidate Detail | C6 | `/signals/candidates/[candidateId]` | `CandidateDetail` | SYNTHETIC | `e2e/c6-signals.spec.ts`, `tests/c6-rendering.test.tsx` | `IMPLEMENTED` | the Brain runtime |
| 8 | Missed Opportunities | C6 | `/signals/missed` | `MissedOpportunity` | SYNTHETIC | `e2e/c6-signals.spec.ts` | `IMPLEMENTED` | the Brain runtime and a qualified price history, **G1 OPEN** |
| 9 | Execution Quality | C8 | `/execution/quality` | `ExecutionQuality` | SYNTHETIC | `e2e/c8-operations.spec.ts`, `tests/c8-read-models.test.ts` | `IMPLEMENTED` | the execution runtime; **Paper expansion NOT AUTHORIZED** |
| 10 | Broker / Reconciliation | C8 | `/execution/reconciliation` | `ReconciliationStatus` | SYNTHETIC | `e2e/c8-operations.spec.ts` | `IMPLEMENTED` | a broker session — **none exists in any Cockpit path, and none is authorized** |
| 11 | Market / Regime | C5 | `/market/regime` | `MarketRegime` | SYNTHETIC | `e2e/c5-portfolio.spec.ts` | `IMPLEMENTED` | a regime engine and qualified provider data, **G1 and G2 OPEN** |
| 12 | Risk Dashboard | C5 | `/risk` | `RiskSnapshot` | SYNTHETIC | `e2e/c5-portfolio.spec.ts`, `tests/c5-rendering.test.tsx` | `IMPLEMENTED` | the risk engine |
| 13 | Short-Side Dashboard | C5 | `/risk/short-side` | `ShortSideSnapshot` | SYNTHETIC | `e2e/c5-portfolio.spec.ts` | `IMPLEMENTED` | borrow data, **G5 OPEN**; short research **NOT AUTHORIZED** |
| 14 | Research / Backtesting | C7 + ADR-0032 | `/research/runs` | `ResearchRun` | SYNTHETIC, capacity UNAVAILABLE | `e2e/c7-research.spec.ts` | `PARTIAL` | the run registry holds; **each run's capacity declaration is NOT OBTAINABLE** through the §12.3.3 gate |
| 15 | Champion / Challenger | C7 | `/strategy/champion-challenger` | `ChampionChallengerComparison` | SYNTHETIC | `e2e/c7-research.spec.ts` | `IMPLEMENTED` | the research runtime and the shadow runner |
| 16 | Feedback Loop | C7 | `/research/feedback` | `FeedbackPipeline` | SYNTHETIC | `e2e/c7-research.spec.ts` | `IMPLEMENTED` | the learning engine |
| 17 | Research Queue | C7 | `/research/queue` | `ResearchQueueItem` | SYNTHETIC | `e2e/c7-research.spec.ts` | `IMPLEMENTED` | the learning engine |
| 18 | Hypothesis Registry | C7 | `/research/hypotheses` | `HypothesisRegistration` | SYNTHETIC | `e2e/c7-research.spec.ts`, `tests/c7-read-models.test.ts` | `IMPLEMENTED` | the learning engine |
| 19 | Governance Packets | C7 | `/governance/packets` | `GovernancePacket`, `DecisionRecord` | SYNTHETIC | `e2e/c7-research.spec.ts` | `IMPLEMENTED` | the governance runtime |
| 20 | Strategy Version Registry | C7 | `/strategy/versions` | `StrategyVersion` | SYNTHETIC | `e2e/c7-research.spec.ts` | `IMPLEMENTED` | the strategy runtime |
| 21 | AI Contribution Analytics | C7 | `/research/ai-contribution` | `AiContribution` | SYNTHETIC | `e2e/c7-research.spec.ts` | `IMPLEMENTED` | the AI agents; **experiment E NOT RUN** |
| 22 | Data Quality / PIT | C8 | `/system/data-quality` | `DataQuality` | SYNTHETIC | `e2e/c8-operations.spec.ts` | `IMPLEMENTED` | provider data, **G1 and G2 OPEN**, **P1–P9 UNEVALUATED** |
| 23 | System Operations | C8 | `/system/operations` | `SystemJob`, `SystemIncident` | SYNTHETIC | `e2e/c8-operations.spec.ts` | `IMPLEMENTED` | a scheduler and service runtime |
| 24 | Project / Qualification Governance | C4 | `/governance/qualification` | `QualificationStatus` | **REPOSITORY_TRACKED** | `e2e/c4-executive.spec.ts`, `screenshots-c10/*-qualification.png` | `IMPLEMENTED` | none — the facts are already real |
| 25 | Environment / Deployment Maturity | C4 | `/governance/maturity` | `MaturityStatus` | SYNTHETIC + REPOSITORY_TRACKED | `e2e/c4-executive.spec.ts` | `IMPLEMENTED` | strategy governance records |
| 26 | Audit Trail | C8 | `/governance/audit` | `AuditEvent` | SYNTHETIC | `e2e/c8-operations.spec.ts` | `IMPLEMENTED` | platform events; **no authoritative audit store exists** |
| 27 | Alerts / Exceptions | C8 | `/system/alerts` | `Alert` | SYNTHETIC | `e2e/c8-operations.spec.ts` | `IMPLEMENTED` | platform alerts; **no notification integration exists or is authorized** |
| 28 | Executive Attention Required | C4 + ADR-0031 | `/attention`, `/` | `AttentionItem` | SYNTHETIC + REPOSITORY_TRACKED | `e2e/adr-0031-owning-area.spec.ts`, `tests/adr-0031-owning-area.test.ts` | `IMPLEMENTED` | contributing subsystems. **General evidence retrieval stays OPEN by ADR-0031 A5** and is stated on screen |
| 29 | Executive / Operator Modes | C3 | shell | presentation over all read models | n/a | `e2e/cockpit.spec.ts`, `e2e/c10-acceptance.spec.ts` | `IMPLEMENTED` | none |
| 30 | Global Command Palette | C3 + C9 | global | `SearchResultPage` | SYNTHETIC | `e2e/c9-ask.spec.ts`, `e2e/cockpit.spec.ts` | `IMPLEMENTED` | entities follow their own areas |
| 31 | Ask KalpaMani | C9 | global | `AskAnswer` | SYNTHETIC | `e2e/c9-ask.spec.ts`, `tests/c9-read-models.test.ts` | `IMPLEMENTED` | authorized read models. **Governance questions are referred by name, not answered — a §7.1 contract consequence, stated on screen** |
| 32 | Modern Executive UX | C3 + **C10** | presentation | — | n/a | §5 of this record, row by row | `PARTIAL` | **U10 and U12 hold; the manual screen-reader pass is `NOT_ASSESSED` and the committed visual baseline is not created.** See §5 and §7 |
| 33 | Cockpit Read-Model Architecture | C3 | contracts | every catalogued model | n/a | `tests/contracts.test.ts`, `tests/adr-0030-references.test.ts` | `IMPLEMENTED` | none |
| 34 | Initial V1 Safety Boundary | C3, held every cycle | absence | — | n/a | `tests/boundaries.test.ts`, `e2e/cockpit.spec.ts`, `e2e/c10-acceptance.spec.ts` | `IMPLEMENTED` | none |
| 35 | Future Human Control Plane | C3 | `/governance/controls` | — | n/a | `e2e/cockpit.spec.ts`, `e2e/c10-acceptance.spec.ts` | `IMPLEMENTED` | a separate control architecture — **NOT AUTHORIZED** |
| 36 | Trade History & Trade Detail | C5 + C6 | `/portfolio/trades`, `/portfolio/trades/[tradeId]` | `TradeSummary`, `TradeDetail`, `TradeLifecycle` | SYNTHETIC | `e2e/c5-portfolio.spec.ts`, `e2e/c6-signals.spec.ts` | `IMPLEMENTED` | the portfolio and execution runtimes |

**Counts, with their denominator and counting rule stated.** The denominator is the **36 areas the
matrix traces**, and the rule is **one row per area**. Of those 36: **30 `IMPLEMENTED`**, **6
`PARTIAL`** — areas **2, 3, 4, 5, 14** and **32** — **0 `BLOCKED_CONTRACT`** and **0
`NOT_ASSESSED`**. **Every one of the 36 was assessed.**

**Five of the six partial rows are product areas; the sixth, area 32, is the cross-cutting
presentation row**, and it is partial for the two §15 criteria §7 records as unmet rather than for
anything a screen fails to render.

**A count of areas is not a measure of project completion.** Thirty implemented areas are
thirty screens over fixtures. **Phase 3 is NOT COMPLETE, no provider is selected, backtesting has
NOT STARTED and live trading is HARD-DISABLED**; none of that is affected by anything in this table.

---

## 5. The cross-cutting presentation criteria — U1 to U20

**These are area 32's acceptance criteria**, and area 32 is the row the traceability matrix assigns to
**C3 foundation, C10 polish**. Each row names the evidence that establishes it.

| # | Criterion | Evidence | Disposition |
|---|---|---|---|
| **U1** | five ten-second answers in the first viewport at 1440 × 900, without scrolling | `e2e/u1-first-viewport.spec.ts` — the WHOLE tile is measured, the first ranked attention item is measured whole, the scroll offset is asserted zero | `IMPLEMENTED` |
| **U2** | environment, source and freshness visible on every route, at all times | `e2e/c10-acceptance.spec.ts` and `e2e/cockpit.spec.ts` each assert the context bar on **every registered route at all three viewports** | `IMPLEMENTED` |
| **U3** | `SYNTHETIC` labelled at page level **and** component level | `e2e/c10-acceptance.spec.ts` asserts the page-level label on **every route at all three viewports**; `e2e/cockpit.spec.ts` counts the component-level badges; `screenshots-c10/*-overview-demo-*.png` show both together | `IMPLEMENTED` |
| **U4** | all eleven availability states render distinctly, none as zero or as healthy | `tests/rendering.test.tsx`, `e2e/c10-acceptance.spec.ts`, `screenshots-c10/*-availability-states.png` | `IMPLEMENTED` |
| **U5** | `EMPTY_VERIFIED`, `NOT_YET_AVAILABLE`, `NOT_IMPLEMENTED`, `NOT_AUTHORIZED` and `STALE` visually distinguishable | `tests/rendering.test.tsx` compares the five rendered texts as a set | `IMPLEMENTED` |
| **U6** | a failing widget leaves the page usable and the page reports `PARTIAL` | `e2e/c4-executive.spec.ts` asserts the page-level `PARTIAL` badge beside a degraded widget; `e2e/c10-acceptance.spec.ts` shows the ERROR state rendering while the `h1` and context bar survive it, with no console error | `IMPLEMENTED` |
| **U7** | a loading skeleton carries no digits and no plausible placeholder | `tests/rendering.test.tsx`; `Skeleton` and every panel fallback are shape-only | `IMPLEMENTED` |
| **U8** | `Cmd/Ctrl+K` opens the palette from every route; `Escape` closes one layer and restores focus | `e2e/cockpit.spec.ts`, `e2e/c9-ask.spec.ts`, `e2e/c10-acceptance.spec.ts` (from a deep route) | `IMPLEMENTED` |
| **U9** | the palette exposes **no** state-changing verb | `e2e/cockpit.spec.ts` drives execution words through the matcher and asserts every result's kind is a registered destination or a local view filter | `IMPLEMENTED` |
| **U10** | every chart has a keyboard-reachable, screen-reader-readable alternative with the same information | `e2e/c4-executive.spec.ts`, `e2e/c5-followup.spec.ts`, `e2e/c7-research.spec.ts`, `tests/c5-followup-rendering.test.tsx` — the table alternative is compared by VALUE against the plotted points | `IMPLEMENTED` |
| **U11** | no status conveyed by colour alone | `tests/rendering.test.tsx`; every availability state carries a glyph and a label, and every signed metric carries its sign | `IMPLEMENTED` |
| **U12** | `prefers-reduced-motion` removes every non-essential transition | `e2e/responsive.spec.ts`, `e2e/c10-acceptance.spec.ts` — forty interactive elements are sampled and each transition duration is under a millisecond | `IMPLEMENTED` |
| **U13** | filters, date range, mode and scoping survive a mode switch and are reproducible from the URL | `e2e/cockpit.spec.ts`, `e2e/c8-operations.spec.ts` | `IMPLEMENTED` |
| **U14** | no page scrolls horizontally at any reference viewport; wide content scrolls in its own container | `e2e/c10-acceptance.spec.ts` and `e2e/c10-reference-viewports.spec.ts` check **every registered route at all six reference viewports**, and again at 200% zoom on three routes. **Two independent checks, because the first one alone could not fail**: the document-overflow measurement, and `clippedBeyondViewport`, which reports any element extending past the viewport without a scroll container to extend into | `IMPLEMENTED` — **and only after a correction**. The document-overflow measurement is clamped by the `overflow-x: hidden` this application sets on `html` and `body`, so it read zero even with 2400-pixel content injected. The real check it was replaced with found **eleven routes clipping a badge's sentence at 390 × 844** and the landing page clipping an attention timestamp; **both are fixed in this cycle**, and the gate that found them fails when either fix is reverted. See §7.2 and §11 |
| **U15** | mode switching preserves drill-down context and does not reset the view | `e2e/cockpit.spec.ts`, `e2e/c8-operations.spec.ts` | `IMPLEMENTED` |
| **U16** | every future control on `/governance/controls` is inert, and **no control API route exists** | `e2e/cockpit.spec.ts` (no button, input or form in `main`), `tests/boundaries.test.ts` (no route handler or server action anywhere) | `IMPLEMENTED` |
| **U17** | a What Changed item with an unavailable endpoint reports that state instead of a delta | `e2e/cockpit.spec.ts`, `tests/c4-review-corrections.test.tsx` | `IMPLEMENTED` |
| **U18** | an "all environments" search groups by environment and presents no combined result | `e2e/c9-ask.spec.ts` | `IMPLEMENTED` |
| **U19** | every displayed metric shows its unit, and every ratio its denominator or its `NOT_APPLICABLE` state | `tests/rendering.test.tsx`, `tests/c5-rendering.test.tsx`; `MetricTile` and `MetricText` render the unit from the closed `Unit` vocabulary | `IMPLEMENTED` |
| **U20** | no owner private identifier, vendor row, account, bucket, locator or broker-native order id appears anywhere | `e2e/cockpit.spec.ts`, `e2e/c8-operations.spec.ts`, `e2e/c9-ask.spec.ts` | `IMPLEMENTED` |

**Twenty of twenty assessed; twenty satisfied.** The denominator is the twenty criteria the UI
specification numbers, and the counting rule is one row per criterion.

**That is not the whole of area 32.** §11 of the UI specification states accessibility targets beyond
U1–U20, §12 states responsive requirements at six reference viewports, and §15 states what a later
cycle owes. Those are assessed in §7. **Of §15's four criteria, one is satisfied and three are
not**; §11's manual screen-reader pass is **unassessed**; and §12 is now swept at **all six**
reference viewports with **one narrative requirement still unmet**. **Corrected in independent
review** — this paragraph read *"two of them are not satisfied"*, which agreed with neither §7.4's
table nor §10's own count.

**U14's evidence was rebuilt by the review rather than taken on its wording**, and the rebuilt
check found real defects. See §7.2 and §11.

---

## 6. The independent audit of C5 and C7

**Both were audited against their requirements rather than against their previous reports.** Both
remain **NOT COMPLETE**, and the reasons below are requirement-level.

### 6.1 C5 — NOT COMPLETE, for two requirements

| Requirement | Accepted clause | What is true today |
|---|---|---|
| **named benchmarks SPY, QQQ and IWM** | Area 2 — *"benchmark comparison against SPY, QQQ and IWM"* | **UNAVAILABLE.** The three references are carried so the join is specified, and each resolves to nothing. The screen states the requirement is **not** satisfied by the synthetic comparison. **No provider is selected; G1 is OPEN** |
| **strategy capacity** | Area 4 — *"…turnover, **capacity**, MFE, MAE and capture ratio"*, as amended by ADR-0032 | **NOT OBTAINABLE.** The §12.3.3 admission gate is enforced by the actual producer, evaluates today's facts, and refuses at its **required-input** stage. **Nine required inputs do not exist**; **G1 and G5 are OPEN**; no capacity model, calibration, qualification or search executor exists |

**Everything else C5 owns is implemented and evidenced** — the rolling return, rolling drawdown and
rolling expectancy, the portfolio benchmark comparison against the repository-owned curve, positions
and exposure, strategy performance, market and regime, risk, the short side, and the trade ledger with
its detail.

**One further gap is recorded here for the first time**, and it belongs to C5 rather than to C10: see
§6.3.

### 6.2 C7 — NOT COMPLETE, for one requirement

| Requirement | Accepted clause | What is true today |
|---|---|---|
| **the capacity health input** | Area 5 — *"With rolling expectancy, drawdown and tail losses · opportunity count · turnover · execution quality · **capacity** · factor drift …"* | **NOT OBTAINABLE.** Area 5 reads capacity through the **same** §12.3.3 gate Area 4 reads, deliberately, so the two screens cannot disagree about one `metric_id`. The gate refuses at its required-input stage, and the health screen renders `NOT_YET_AVAILABLE` with `UPSTREAM_INPUT_MISSING` |

**Area 14's per-run capacity declaration is the same dependency**, reached through the same gate.

**Everything else C7 owns is implemented and evidenced** — the seven health states and their
transitions, the research queue entry a degradation created, the run registry with its named
baselines and evaluation classes, the immutable preregistrations and their lineage-wide trial budget
and exposure ledger, the Champion/Challenger comparisons, the feedback pipeline, the governance
packets and recorded decisions, the version registry, the matched-arm AI comparisons, and the rolling
tail loss with its window, population, tail fraction, R basis and observation counts.

**Four of Area 5's other health inputs are `ACCEPTED_UNAVAILABLE` rather than outstanding** — turnover,
slippage, modelled-versus-realized execution and regime behaviour each name a producer that does not
exist, and each renders the correct state with its dependency. That is the accepted contract, not a
shortfall.

### 6.3 A newly recorded Area 3 gap, and it is not C10's

**`PositionSnapshot` carries no earnings-proximity, liquidity or capacity field.** Area 3's presented
facts include *"Concentration, gap exposure, event exposure, earnings proximity, borrow state,
liquidity and capacity"*; concentration, gap and event exposure, and borrow state are all carried, and
the other three are not carried at all.

**The matrix's observable acceptance criteria for Area 3 are met** — borrow comes from a record and
never from price, groupings are displayed and never computed as a permitted exposure, and initial and
current open planned risk are separate columns a moving stop moves only one of. So the row is
`PARTIAL` on the narrative rather than failing on the criteria, and it is recorded rather than
smoothed over.

**Each of the three depends on something this cycle may not obtain**: earnings proximity and liquidity
need provider data (**G1 OPEN**), and capacity needs the model that does not exist. **The row belongs
to C5's remaining dependency, and correcting it is not C10 work** — acquiring provider data, adding a
capacity model and inventing a liquidity measure are each explicitly outside this cycle.

---

## 7. Accessibility, responsiveness, performance, and the two criteria that are not met

### 7.1 Accessibility

| | |
|---|---|
| **automated, every route, every reference viewport** | `e2e/c10-acceptance.spec.ts` runs axe-core over **all 30 registered sidebar routes at 1440 × 900, 1024 × 768 and 390 × 844** with the `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa` and `wcag22aa` tags, and asserts **no serious or critical violation** |
| **the structural rules the tags do not carry** | the same spec runs `heading-order`, `empty-heading`, `landmark-one-main`, `page-has-heading-one` and `landmark-unique` **by name**, because axe tags `heading-order` as best-practice and every tagged run this repository had therefore never checked it |
| **keyboard** | skip links to main content **and** to the primary table, palette open and close from a deep route with focus restored, the drawer's focus trap and release, and the sortable-header and disclosure controls exercised by the per-cycle specs |
| **manual screen-reader pass** | **`NOT_ASSESSED`.** No screen reader was run by the author, and **none was available to the independent review either** — this environment has no assistive technology a reviewer could drive, and neither session heard a single announcement. §15 asks for a manual pass, an automated pass is not one, and the honest disposition is unassessed rather than covered by the axe result |
| **zoom** | usable at 200% — asserted by halving the CSS viewport on three routes and re-checking horizontal overflow, the context bar and the `h1` |

**An automated pass is not an accessibility conformance claim, and none is made.** What is claimed is
exactly what was run.

### 7.2 Responsiveness

**All six reference viewports are registered and swept.** `e2e/c10-acceptance.spec.ts` sweeps every
registered route at **1440 × 900, 1024 × 768 and 390 × 844**, and
`e2e/c10-reference-viewports.spec.ts` sweeps every registered route at **1920 × 1080, 1280 × 800 and
768 × 1024**. Each route is checked at each width for page overflow, **content clipped outside a
scroll container**, a single `h1`, a `main` landmark, heading order, the U2 context bar, the U3
page-level `SYNTHETIC` label, console errors and off-origin requests.

**Corrected in independent review.** This section previously read *"three of the specification's six
reference viewports are not registered … `NOT_ASSESSED` at those three widths"*, and gave as the
reason that *"adding viewports to the suite would change every existing spec's run count"*. The three
missing widths are now registered in **their own three projects, running one focused responsive
spec**, so **no existing spec's run count moves** and the coverage the specification asks for exists.
Each width additionally gets the requirement stated on **its own row** in §12: the first-viewport rule
at 1920 × 1080, full persistent navigation at 1280 × 800, and a ledger scrolling inside its own
container at 768 × 1024.

**The sweep found real defects at 390 × 844, and they are fixed.** §12 forbids a clipped control and
a truncated value at every reference viewport, and the check that was supposed to catch that could
not: `globals.css` sets `overflow-x: hidden` on `html` and `body`, so
`documentElement.scrollWidth − clientWidth` is clamped and reads zero however wide the content is.
Injecting a 2400-pixel element left every U14 assertion in this repository green. The replacement
check found **a badge carrying a sentence overflowing the viewport on eleven routes** — *"The
evidence rests on one confirmatory evaluation"* reached x = 608 in a 390-pixel viewport, clipped and
unreachable — and **the attention item's metadata pair overflowing on the landing page**. Both are
corrected: `badgeVariants` no longer forces `whitespace-nowrap`, and the attention metadata pairs
wrap. **Reverting either fix fails the gate**, which is how it is known to be a gate.

**One narrative requirement remains unmet, and the accepted text does not settle it.** §12's mobile
row reads *"executive summary only — tier 1, Attention Required and search"*; the mobile Executive
Overview renders the full executive page stacked, including What Changed, the performance overview
and tier 2. **That much is confirmed.** What the accepted text does **not** settle is what becomes of
the rest at that width: whether *"only"* requires those sections to be **omitted** at 390 × 844, or
merely that they are **not part of the summary** and may follow it or sit behind a disclosure. The
distinction is material because **no route owns What Changed or the tier-2 supporting-context
tiles** — omitting them at mobile would remove specified executive information with no navigation to
it, which §12's own tail (*"Operator tables are reachable"*) shows the section does not intend, while
leaving them where they are does not deliver *"executive summary only"*.

**The bounded decision needed is exactly that**: omit or defer, and if omit, which route surfaces
What Changed and the tier-2 facts at 390 × 844. **It is recorded rather than invented here**, and the
requirement stays **unmet** until it is taken. Nothing at that viewport is clipped or overflowing any
more, and the page is not a scaled-down operator console — operator tables stay on their own routes.

### 7.3 Performance

**Measured, with its conditions, and against no budget.** `e2e/c10-performance.spec.ts` records first
answer, first contentful paint, DOM-content-loaded, load and transferred bytes for five routes, plus
two interaction latencies, at each viewport, into
`screenshots-c10/performance-<project>-<server>.json`.

**No numeric performance budget exists anywhere in tracked authority**, so none is asserted. The
assertions are that each measurement was obtained and is a real, finite, positive duration, and that
each timed interaction completed.

**The conditions are part of the measurement, and they are recorded rather than reasoned from.** The
suite drives `next dev` by default — a development server, compiled on demand and unminified — on one
worker, on one machine, over the local fixture adapter. **Corrected in independent review**: this
section previously read *"these figures are an upper bound on a production build's"*, which **these
measurements do not establish**. A development and a production server differ in compilation,
bundling, caching and rendering, in more than one direction, and nothing measured here orders them.
The claim is withdrawn from this record, from the spec's own commentary and from the evidence file's
`conditions` block.

**A production build was measured instead of reasoned about.** The independent review ran
`next build`, started `next start` on the suite's port and re-ran the measurement with
`KM_COCKPIT_SERVER` naming that server, so the evidence file records the server it describes:

```text
server              next start - a production build, minified and precompiled
project             desktop-1440 (1440 x 900), one worker, local loopback, local fixtures
first answer        /  618 ms   ·  /portfolio/trades  462 ms  ·  /portfolio/performance  384 ms
                    /governance/qualification  269 ms  ·  /system/alerts  311 ms
DOMContentLoaded    32-166 ms       load event  137-329 ms
transferred         399-537 KB per route
interactions        command palette  51 ms   ·   Executive to Operator  211 ms
first contentful paint   NOT OBTAINED - the paint entry was absent on every route in this run,
                    and no figure is invented for it
```

**The development server was measured on the same machine, in the same run, and both sets are
retained.** At 1440 x 900 its first-answer figures were 779 to 2164 ms against the production
build's 269 to 618 ms, and it recorded a first contentful paint of 184 to 656 ms where the
production run recorded none at all.

**That is one paired sample, and it establishes no general ordering.** It is reported because
withholding it would be the same withholding the retracted claim was: on this machine, in this run,
the production build answered sooner on every measured route. **One paired run is not a rule about
development and production servers**, and this record asserts none.

**These figures describe those servers on that machine and nothing else.** No budget is asserted,
and **a measurement is not a performance claim about a deployed Cockpit — none is deployed**.

### 7.4 The §15 criteria, and the three that are not met

| §15 item | Disposition |
|---|---|
| **synthetic end-to-end** | `IMPLEMENTED` — navigation across every route, every availability state rendered, drill-down paths traversed, mode switching with context preserved, palette open and close, and the failure states exercised deliberately |
| **accessibility checks in the pipeline** | `PARTIAL` — the automated half is implemented and runs on every route at every registered viewport; **the manual keyboard pass is partly automated and the manual screen-reader pass is `NOT_ASSESSED`**, by the author and by the independent review alike |
| **performance targets** | `PARTIAL` — measured on both a development server and a production build, each recorded with the conditions it was taken under; **no target exists anywhere in tracked authority to measure against**, and neither this cycle nor its review invents one |
| **screenshot and visual regression** | `PARTIAL` — **and materially closer than it was.** A **committed baseline now exists**: nine tracked images under `e2e/visual-baseline/`, three route-and-state captures at each of the three registered viewports, compared on every run by `e2e/c10-visual-regression.spec.ts`. **Corrected in independent review** — the earlier claim that *"this repository keeps screenshots outside the tracked tree, so a baseline could not be committed"* described a practice for review captures, not a rule: nothing in this repository's instructions prohibits a tracked test asset, and `.gitattributes` has declared `*.png binary` since long before this cycle. **It is still `PARTIAL`, and for a real reason**: §15 asks for a stable baseline **per route and per state**, and this one covers a **representative subset** — the Executive Overview populated, the same route with its producers absent, and the eleven availability states — not all thirty routes in every state |

---

## 8. What C10 changed, and what it deliberately did not

### 8.1 Corrected

| | |
|---|---|
| **panel titles were not headings** | `ReadModelPanel`, `PerformanceOverview`, the rolling-series panel, the attention panel and the What Changed panel rendered their titles as `<span>`, so most screens offered a screen reader exactly one heading — the `h1` — and `PanelSection`'s `h3` then **skipped a level from it**. Section 11 asks for "landmarks, one `h1` per page, ordered headings", and both halves failed. The titles are headings now, the visual treatment is byte-identical, and `heading-order` is checked on every route at every viewport |
| **twenty-two page-level card titles** | the same correction where a page's own sections are plain cards — governance, maturity, qualification, attention, risk, positions and the two executive tier-two cards |
| **repeated landmarks shared one name** | `/strategy/performance` rendered one *"Minimum observation rules"* region per strategy version and per family, so a landmark list offered several identical destinations. Each now names its subject |
| **a drill-down screen had no place in the sidebar** | `aria-current` was decided by `pathname === href`, so **nothing** was current on `/portfolio/trades/<id>` or `/signals/candidates/<id>`. A deep destination now resolves to the sidebar entry that owns it — marked `aria-current="true"` as the owning **section**, never `"page"`, because the reader is not on the ledger |
| **no skip link reached a table** | section 10 asks for skip links to "the main content **and** the primary table"; only the first existed, so reaching a ledger by keyboard meant tabbing past the header and thirty sidebar links. The second link appears only once a table exists to point at |
| **six identical link names** | the executive answers all read *"Open the area that owns this"*, so a screen-reader link list offered six indistinguishable entries. The visible text is unchanged and each accessible name now carries its subject |
| **two stale comments** | both described six of seven owning-area routes as placeholders; C8 built the last of them. The code was already registry-derived; the comments were not |

### 8.2 Deliberately not done

| | |
|---|---|
| **per-route document titles** | every route shares one `<title>`, and **no accepted requirement asks for a per-route one** — not U1–U20, not §11's enumerated accessibility targets, and not any area's criteria in the traceability matrix, none of which mentions the document title at all. It is therefore an **unrequired improvement, not an unmet criterion**, and it is **not blocked**: a per-route segment layout is ordinary framework-supported work that a later cycle can add. **Corrected in independent review** — the earlier wording here described the fix as structurally unavailable, which overstated the obstacle |
| **narrowing the mobile Executive Overview** | §7.2 — **still not done**, and the precise unresolved choice is named there rather than decided |
| **the three unregistered reference viewports** | **done in independent review** — all six are registered and swept. §7.2 |
| **anything requiring a producer** | no capacity model, no search executor, no acquired data, no invented capacity estimate, no synthetic stand-in for a named benchmark |
| **any change to economics** | **no book, trade population, entry or add fact, risk denominator, strategy version or accepted measurement formula was changed**, and **no fixture was edited to make a chart more interesting** |
| **any new dependency** | none was added |

### 8.3 The negative controls

**Every correction was reintroduced and the test that guards it was watched fail.** A regression that
cannot fail is not a regression, and each of these was run against a deliberately mutated tree and
then restored.

| Correction reintroduced | What failed |
|---|---|
| `ReadModelPanel`'s title back to a `<span>` | `tests/c10-polish.test.tsx` — **3 of 8** tests, and `e2e/c10-acceptance.spec.ts` reported `/risk: heading-order` |
| `resolveRoute` reduced to an exact-path match | `tests/c10-polish.test.tsx` — the deep-destination test, and **2 of 3** drill-down browser tests, each receiving `null` |
| the table region's `data-table-region` marker removed | the primary-table skip link never appears, so `skip-to-table` is not found |
| the family rollup's landmark subject removed | `e2e/c10-acceptance.spec.ts` reported `/strategy/performance: landmark-unique` |
| the executive links' `aria-label` removed | the six link names collapse to **one** distinct name where six are required |

**One control was informative rather than confirming, and it is recorded as such.** Removing the
**per-version** landmark subject alone did **not** reproduce the violation: only one module card
expands at a time in the current fixture set, so the collision the automated check caught came from
the **family rollups**, which render together. **The per-version subject is therefore defensive
rather than load-bearing today**, and saying so is more useful than presenting it as a fix that was
proved necessary.

---

## 9. Carried-forward limitations, unchanged

**None of these is resolved by this cycle, and each is stated so it is not read as closed.**

```text
real capacity inputs, model, calibration and qualification    ABSENT
named SPY / QQQ / IWM comparisons                             UNAVAILABLE - G1 OPEN
some capacity declaration failures refuse with an empty
    missing-input list; the declaration-to-input mapping
    stays UNRESOLVED                                          CARRIED FORWARD
the synthetic book's valued tails are flat at -1.00 R         CARRIED FORWARD
governance entity search and reference limitations, where
    accepted contracts provide no destination                 CARRIED FORWARD
the C8 fill-scoped count under an order-labelled code         OPEN, UNCHANGED
the C8 contract comment that overstates its body              OPEN, UNCHANGED
SearchResultPage's unexercised governance-provenance
    permission                                                OPEN, UNCHANGED
the ADR-0031 A5 general evidence-retrieval limitation         OPEN, UNCHANGED
original Linux PR #84 review evidence                         UNAVAILABLE - the Windows
                                                              evidence is a separate set
```

---

## 10. Status

```text
C10 polish and acceptance cycle:                  IMPLEMENTED IN AN OPEN PULL REQUEST
independent review of the C10 implementation:     PERFORMED
areas in V1 scope:                                36
areas assessed by the acceptance record:          36 OF 36
areas IMPLEMENTED within accepted scope:          30
areas PARTIAL:                                    6
areas BLOCKED by a contract decision:             0
areas NOT ASSESSED:                               0
U1-U20 assessed:                                  20
U1-U20 satisfied:                                 20
section 15 criteria assessed:                     4 OF 4
section 15 criteria satisfied:                    1 OF 4
manual screen-reader pass:                        NOT ASSESSED
mobile executive summary - section 12:            NOT SATISFIED - AMBIGUITY RECORDED
responsive defects found and fixed by review:     2 - BADGE CLIPPING, ATTENTION METADATA
committed visual-regression baseline:             CREATED - 9 IMAGES, REPRESENTATIVE SUBSET
accepted numeric performance budget:              NONE EXISTS - NONE INVENTED
reference viewports registered and swept:         6 OF 6
read models changed by this cycle:                NONE
schema versions changed by this cycle:            NONE
fixtures changed by this cycle:                   NONE
C5:                                               NOT COMPLETE
C7:                                               NOT COMPLETE
full Cockpit V1:                                  INCOMPLETE
new API routes, handlers or server actions:       NONE
new runtime dependencies:                         NONE
ledger economics, entry facts or risk records:    UNCHANGED
provider data used:                               NONE
private artifacts read:                           NONE
AWS / Terraform operations:                       NONE
broker activity:                                  NONE
Brain runtime:                                    NOT IMPLEMENTED / NOT AUTHORIZED
backtesting:                                      NOT STARTED
Run A retry:                                      NOT AUTHORIZED / NOT RUN
Run B:                                            NOT RUN / NOT AUTHORIZED
Run B earliest approved target:                   12 SEPTEMBER 2026
combined assessment:                              NOT RUN / NOT AUTHORIZED
P1-P9:                                            UNEVALUATED
data correctness and quality:                     NOT ESTABLISHED
G1 / G2:                                          OPEN / OPEN
provider selected:                                NONE
Phase 3:                                          NOT COMPLETE
CONTROL:                                          DEFERRED
live trading:                                     HARD-DISABLED
```

**Twenty satisfied UI criteria are twenty satisfied UI criteria.** They are not a measure of how much
of this project is built, and they are not a step toward live trading. **Specification,
implementation, research, deployment and execution stay five separate gates.**

---

## 11. The independent review

**The review read the accepted clauses and re-derived each disposition, rather than checking the rows
against each other.** It ran the full gate set on a clean worktree at `main` before touching
anything, reproduced the corrections it could, and rebuilt one check that could not fail.

### 11.1 What it confirmed

| | |
|---|---|
| **the baseline** | pytest **7351**, Vitest **829**, Playwright **890**, docs audit **4599 checks**, ruff, ruff format, mypy, the test-integrity audit and `git diff --check` — every one clean at `main`, on a worktree never edited |
| **the author's own baseline failure did not recur** | the author recorded one browser failure at `c8-operations.spec.ts:428`, mobile-390, `net::ERR_NO_BUFFER_SPACE`. **That observation is preserved as a fact about their run.** This review's baseline passed 890 of 890; **no cause is assigned to theirs**, and "did not recur" is not a claim that it did not happen |
| **the six corrections** | each was traced to its consumers rather than to its own test. The heading control was reproduced exactly — reverting `ReadModelPanel`'s title to a `<span>` fails **3 of 8** tests in `tests/c10-polish.test.tsx`, as recorded |
| **the counting rule** | 36 rows, 30 `IMPLEMENTED`, 6 `PARTIAL` — areas 2, 3, 4, 5, 14 and 32 — re-derived from the table itself |
| **the Area 3 gap** | `PositionSnapshot` carries no earnings-proximity, liquidity or capacity field. **Confirmed against the contract**, and confirmed as **C5's dependency rather than C10 work** |
| **the capacity dependency** | `read-model-contracts.md` §12.3 names **all nine required inputs** and states `NOT_YET_AVAILABLE` with `UPSTREAM_INPUT_MISSING` is **"the state today"**. Areas 4, 5 and 14 are held `PARTIAL` rather than `ACCEPTED_UNAVAILABLE`, which is the **conservative** reading of the record's own vocabulary; the review leaves it conservative and does not round it up |

### 11.2 What it corrected

| | |
|---|---|
| **an arithmetic residue** | *"Thirty-one implemented areas"* survived the commit that corrected 31 to 30 |
| **a §15 miscount** | *"two of them are not satisfied"* and the §7.4 heading disagreed with §7.4's own table and with §10 |
| **an overstated obstacle** | per-route document titles were recorded as structurally blocked. **They are not required by any accepted clause at all** — not U1–U20, not §11's enumerated targets, not any area's criteria — and they are **not blocked** either |
| **an unsupported claim** | *"an upper bound on a production build's"*, withdrawn, and a production build measured instead |
| **an unsupported justification** | *"a baseline could not be committed"*, replaced by a committed baseline |
| **an unassessed half of §12** | three reference viewports, now registered and swept |
| **a check that could not fail** | U14's document-overflow measurement, replaced by one that does |

### 11.3 What it found

**Two real responsive defects, at a reference viewport, that no existing test could see.**

```text
badges carrying a sentence            11 routes, clipped past 390 x 844, unreachable
attention metadata pairs              the landing page, clipped past 390 x 844
cause                                 whitespace-nowrap on the badge primitive, and a
                                      non-wrapping dt/dd group
why nothing caught it                 html and body set overflow-x: hidden, so the root
                                      scroll-width measurement is clamped and reads zero
                                      however wide the content is -- proven by injecting a
                                      2400-pixel element and watching every U14 assertion
                                      in this repository stay green
fixed                                 yes, in this cycle, in two lines
gate                                  clippedBeyondViewport, on every route at all six
                                      reference viewports; reverting either fix fails it
```

**Neither defect was introduced by this pull request** — both predate it, and the `overflow-x: hidden`
that hid them is older than C10.

### 11.4 What it could not assess

| | |
|---|---|
| **the manual screen-reader pass** | **`NOT_ASSESSED`.** No assistive technology was available to this review, and none was driven. Nothing here is a screen-reader result |
| **§12's mobile executive summary** | **unmet, and not decided.** §7.2 names the exact unresolved choice; inventing a mobile product design was outside what the accepted text supports |
| **every route and every state, visually** | the committed baseline is a **representative subset**, and §15 asks for more |
| **anything requiring a producer** | unchanged. No capacity model, no named benchmark, no acquired data |

### 11.5 The review's own negative controls

**A control that cannot fail is not a control, and one of these did not fail the first time it was
run — which is recorded rather than quietly re-run.**

| Control | Outcome |
|---|---|
| `ReadModelPanel`'s title back to a `<span>` | **3 of 8** `tests/c10-polish.test.tsx` tests failed, reproducing the author's result |
| the badge fix reverted | `/governance/packets` failed at mobile-390, naming five clipped sentences up to x = 608 |
| a design token shifted, against the **default** screenshot tolerance | **PASSED — the control was INERT.** Playwright's default per-pixel threshold of 0.2 absorbed a visible colour change, so the baseline was tightened to **zero tolerance** before it was trusted |
| the same token shifted, against the **tightened** baseline | failed, with **13 489 to 17 472** differing pixels |
| the baseline re-run twice on an unchanged tree | **byte-identical both times**, before and after the tightening |
| the baseline inside a full six-project run | **ONE FLAKE, and it is recorded rather than re-run away.** The availability-state screen's *precondition* wait — the 5-second default, waiting for the page to render at all — expired before any screenshot was taken, in a 33-minute run. The same test passed **four of four** in isolation and at **every other viewport in the same run**. **Corrected in the browser-gate diagnosis (§11.6)**: this row previously attributed the wait to *"the heaviest page a development server compiles on demand"*, which the run's own log contradicts — the same server had loaded that route 55 tests earlier. The precondition waits are now explicit at 30 seconds; **the comparison itself is untouched and still fails on one differing pixel** |
| a 2400-pixel element injected, against the **document-overflow** measurement | **PASSED — inert**, which is the finding in §11.3 |
| a 2400-pixel element injected, against `clippedBeyondViewport` | failed, as designed |
| one grep-scoped control | **matched no test and proved nothing.** Re-run with a correct pattern rather than counted |

### 11.6 The full browser suite — the two failures, and what their cause is not

**The browser gate did not pass literally on this branch's first two full runs at its final content,
and the record keeps every run rather than the best one.** The suite has **1238 tests across six
projects**, on one worker, against a `next dev` server. Four full six-project runs have been made on
trees whose application and end-to-end content is identical apart from the visual spec's precondition
wait and this record; each is listed with its result, and none is omitted.

| Run | Tree | Result | The one failure |
|---|---|---|---|
| review run 1 | `4199de7` — inferred from the review worktree's reflog and the log's timing; the log itself records no commit | **1238 passed**, exit 0, 38.4 min | none |
| review run 2 | `c19b0ab` — inferred the same way, and consistent with the failure: it ran the 5-second precondition that `e385b41` later replaced | 1237 passed, **1 failed**, exit 1, 33.3 min | `c10-visual-regression.spec.ts:116`, desktop-1440, the **5-second default precondition** — the freshness indicator had not appeared; no screenshot was taken |
| review run 3 | `e385b41` — the review's recorded final head, and the run its ledger reports | 1237 passed, **1 failed**, exit 1, 33.4 min | `c7-research.spec.ts:342`, desktop-1440, its own **20-second precondition** — one skeleton stayed on `/research/hypotheses` for the whole wait |
| diagnosis run, instrumented | `e385b41`, task-owned server with its log retained, `--trace retain-on-failure`, a socket sampler every 5 s, nothing else running | **1238 passed**, exit 0, 37.9 min | none — **the failure did not reproduce** |

**The review's earlier text tabulated two of its three six-project runs.** The passing first run was
real, is retained, and is listed above; omitting it understated the evidence rather than overstating it,
and a ledger that lists only the failures is as incomplete as one that lists only the passes.

**What the two failures establish, read from the retained logs rather than from a theory.** In each,
`page.goto` had returned — the document was served and the server-rendered context bar was visible —
and the client-rendered content had not appeared within the wait. In run 3 the very next test loaded
its page in 1.3 seconds against the same server, and `/research/hypotheses` carries exactly one read
panel, so *one skeleton for 20 seconds* is *nothing client-rendered for 20 seconds*, not one slow read
among several. The failing operation is therefore **after the document response and before the first
client render** — a chunk request issued during hydration, hydration itself, or the read that follows
it. Tracing was off in both runs, so which of the three it was **was not recorded**, and the review's
later isolated probes overwrote the only artifact the failures left.

**Three causes that were offered are unsupported or contradicted, and are withdrawn from this
record and from the spec's commentary.**

| Offered cause | Standing |
|---|---|
| *"compiled on demand by the development server"* | **contradicted** — run 2's own log shows `/foundation/states` loaded at 1.1 s, 55 tests earlier, on the same server |
| *"the machine intermittently stalls a `next dev` page load"* | **not supported as stated** — in both failures the page load completed; what did not complete came after it. The diagnosis run's server log shows all 2,292 document requests answered, the slowest in 1.8 s, with one compile and no error — though the development server does not log chunk requests, so a stalled chunk is not excluded by it |
| the author's `net::ERR_NO_BUFFER_SPACE` observation generalized to socket pressure | **unsupported by measurement** — the socket sampler peaked at 620 `TIME_WAIT` connections against a 16 384-port dynamic range |
| a fixture-backed read rejecting, which `ReadModelPanel` would show as a skeleton | **unsupported** — 86 400 reads over 7 200 distinct session instants, the two reads that route issues, zero rejections |

**The cause is NOT ESTABLISHED.** *Environmental* and *unrelated to this branch* are hypotheses here,
not findings: the added coverage raises the number of page loads from 890 to 1238, and a per-load
failure whose mechanism is unknown cannot be declared independent of the workload that exposed it.

**One bounded correction, and why it is the right one.** The runner recorded `trace: "off"`, so a
failing test left only an ARIA snapshot. It now retains the trace of a **failing** test only —
network, console and DOM timeline — and discards a passing test's, so no tracked artifact is produced
and no assertion, timeout, project, tolerance or coverage changes. The control: a deliberately failing
test under the old setting left **zero** trace archives; the same test under the new setting left
**one**, holding a network log; a passing test under the new setting left **none**. A recurrence will
carry its own evidence. No pre-existing timeout was inflated, no retry was added, nothing was skipped,
and no isolated pass is substituted for the full suite. **A `ReadModelPanel` cannot distinguish a
rejected read from a pending one** — both render the skeleton — which is recorded as an observability
limitation of the application and was not changed in this cycle, because no rejection was found.

**The definitive run for the merge decision is recorded in the pull request**, at the exact final
commit, with every gate's raw exit code. **A passing browser suite is a passing gate, not a diagnosis,
and not an acceptance**: C10 stays at one of four §15 criteria, and full Cockpit V1 stays INCOMPLETE.
