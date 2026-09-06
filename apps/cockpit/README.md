# KalpaMani Cockpit — C5 portfolio, strategy, exposure and trade views

Portfolio performance, positions and exposure, strategy performance, market and regime, the risk
dashboard, the short side, and trade history with a **basic** trade detail — built on the merged
C3 foundation and C4 screens, under
[ADR-0027](../../docs/decisions/ADR-0027-cockpit-and-feedback-architecture-and-governance.md)
and the corrected contracts of
[ADR-0028](../../docs/decisions/ADR-0028-cockpit-contract-completion-and-boundary-corrections.md)
and
[ADR-0029](../../docs/decisions/ADR-0029-valid-zero-values-and-cache-freshness-deadlines.md).

**This is C5. It is not the Cockpit.** C3 delivered the design system, shell, navigation and
contract layer; C4 added the Executive Overview, the performance overview, Attention Required,
What Changed and two governance screens; C5 adds seven product areas and one deep destination —
still running on a **local fixture adapter**, and still with no production read API, projection
or metric engine behind it.

**Eleven of the thirty-six product areas are implemented.** Areas 1, 24, 25 and 28 from C4, and
areas 2, 3, 4, 11, 12, 13 and 36 from C5 — the C5 row of the traceability matrix. The other
twenty-five remain registered, reachable placeholders, and the C6–C10 sequencing is unchanged.

**Two boundaries inside area 36 are worth naming up front.** The matrix splits it: **C5 owns the
trade history and a BASIC trade detail, and C6 owns the complete lifecycle and the chart
drill-down.** And **Area 5, Strategy Health, is C7's** — this cycle displays a recorded health
state beside each strategy version's results and implements none of the transitions, drift
measures, failure clusters or research-queue behaviour that area is about.

---

## What is real, and what is not

| | |
|---|---|
| **real** | the governance facts on `/governance/qualification`, the readiness figures on the landing page, and the **governed research parameters** on `/risk`. Provenance `REPOSITORY_TRACKED`, transcribed from tracked repository authority, each carrying its exact source path, its source commit and its recorded as-of date |
| **synthetic** | everything in the `demo` scenario. Repository-owned deterministic fixtures, labelled `SYNTHETIC` at page level and at component level. **Not a result, not a measurement, and not evidence of anything** |
| **unavailable** | every operational read model in the default `project` scenario. Portfolio, risk, execution, strategy and signal projections do not exist, so their tiles say so — with the state, its closed reason code and its named dependency. **Nothing is estimated in their place** |

**The tracked facts are a SNAPSHOT.** They were transcribed at the commit recorded in
`src/data/fixtures/tracked-facts.ts` and **they age**. The application performs **no network
read of GitHub, AWS, a provider or a broker**, at runtime or at build time, to refresh them.
A later cycle refreshes them by re-reading the tracked sources under its own authorization.

**No deployment exists and no real-data connection exists.** This runs locally, bound to
loopback, against fixtures.

---

## Requirements

```text
Node            >=22.13.0 <23, or >=24.0.0   (developed on 22.21.0)
npm             >=10.9.0                     (developed on 10.9.4)
package manager npm only, with a committed package-lock.json
```

`jsdom` is pinned to a release whose engine range admits Node 22.21.0, and `@types/node` is
pinned to the 22.x line so the types match the runtime rather than a later Node.

**ESLint is pinned to 9.39.5.** ESLint 10 is not usable here: the `eslint-plugin-react`
bundled by `eslint-config-next@16.3.4` fails to load under it
(`contextOrFilename.getFilename is not a function`). 9.39.5 is the version the version-matched
`create-next-app` generator selects.

**TypeScript is pinned to 5.9.3.** TypeScript 7 is current on npm, and the lint toolchain that
depends on the TypeScript compiler API targets the 5.x line; 5.9.3 is the compatible stable
choice for this stack.

**Recharts is pinned to 3.10.1**, the current stable release, and it is the one dependency C4
adds. `ui-ux-specification.md` §13 assigns "executive and time series — KPI trends, equity and
drawdown curves, ordinary comparisons" to Recharts, so the choice is transcribed rather than
made here. Its published peer range is `react ^16.8 || ^17 || ^18 || ^19` and
`react-dom ^16 || ^17 || ^18 || ^19` against this project's React 19.2.8, and its engine range is
`node >=18` against Node 22.21.0; `npm ls` resolves it with no unmet peer. **No other dependency
was added, upgraded or removed**, and the lockfile is otherwise unchanged.

TradingView Lightweight Charts and Apache ECharts — the other two classes §13 names — are **not**
installed. They belong to price/trade overlays and dense analytics, neither of which C4 renders.

---

## Install, run, test, build

```bash
cd apps/cockpit

npm ci                 # reproducible install from the committed lockfile
npm run dev            # http://127.0.0.1:3000 -- loopback only
npm run lint           # ESLint, including the layering rule
npm run typecheck      # tsc --noEmit, strict
npm test               # Vitest -- contracts, boundaries, rendering, freshness expiry
npm run build          # production build
npm run test:e2e       # Playwright, three viewports (needs: npx playwright install chromium)
npm run verify         # lint + typecheck + test + build
```

`npm run test:e2e` starts its own dev server on port 3100 and writes review screenshots for the
desktop (1440×900), tablet (1024×768) and mobile (390×844) viewports:

```text
screenshots/      the C3 author and reviewer captures, regenerated by the C3 specs
screenshots-c4/   the C4 captures, plus PROVENANCE.txt naming the exact commit they were
                  taken at and whether the working tree was clean
screenshots-c5/   the C5 captures, with their own PROVENANCE.txt
```

All three are git-ignored: they are **review evidence, not a visual-regression baseline**. Visual
regression is specified for a later cycle.

**To review the screens by hand**, `npm run dev` and open:

```text
/?scenario=demo                       the populated Executive Overview -- SYNTHETIC throughout
/?scenario=project                    the honest default: every operational tile is an absence
/?scenario=demo&mode=operator         reason codes, metric ids, freshness inputs, pins
/?scenario=demo&period=ALL            a gapped extent -- the line BREAKS, PARTIAL is stated
/?scenario=demo&changes=no-baseline   a comparison with no baseline -- a state, not a zero
/?scenario=demo&changes=degraded      both endpoints qualified -- reported, not absorbed
/attention?scenario=demo              the ranked list, its filters and its evidence drawers
/governance/qualification             the real tracked governance facts
/governance/maturity                  the stage-to-environment mapping

/portfolio/performance?scenario=demo&gran=MONTHLY   the monthly heat map and the summaries
/portfolio/positions?scenario=demo&dir=SHORT        a filtered table, with its chips
/portfolio/positions?scenario=demo&borrow=BORROW_STATE_UNKNOWN   an unknown borrow
/portfolio/trades?scenario=demo&status=PARTIALLY_EXITED          one trade, reduced not closed
/portfolio/trades/demo-trade-nvl-0002?scenario=demo              a pyramided trade's detail
/portfolio/trades/demo-trade-gen-0002?scenario=demo              CLOSED and PARTIAL together
/strategy/performance?scenario=demo   two versions of one module, kept apart
/risk?scenario=demo                   permitted limits absent, research parameters tracked
/risk/short-side?scenario=demo        a borrow record, and one security with none
/market/regime?scenario=demo          a versioned regime, declared FORWARD_SYSTEM
```

---

## Organization

```text
src/contracts/     the closed vocabularies, the 4.1.1 validity matrix, the freshness
                   deadline arithmetic, the envelope, the admission gate and the C3
                   payload contracts -- transcribed from read-model-contracts.md
src/data/client/   the typed READ-CLIENT BOUNDARY, the query keys and the query hooks.
                   default-client.ts is the ONE composition point that names the adapter
src/data/fixtures/ the deterministic fixture adapter, the ONE synthetic book every C5
                   screen is projected from, and the tracked governance facts
src/components/    ui/ primitives, cockpit/ contract-aware presentation, shell/ the
                   application shell, palette/ the command palette
src/nav/           the typed route registry every navigation surface reads
src/app/           App Router routes
tests/             Vitest
e2e/               Playwright
```

**Presentation never imports fixture data.** Components and pages talk to the read-client
boundary; an ESLint rule and a test both enforce it, and a test asserts that exactly one
module names the fixture adapter.

**The fixture adapter is a local substitute for the future API transport.** It is **not** a
claim that the FastAPI read service, the projections or the metric engine exist. None of them
exists, and none is authorized.

---

## Scenarios and scope

Mode, environment and scenario live in the URL, so a link reproduces the view:

```text
/?mode=executive|operator&env=RESEARCH|PAPER|LIVE&scenario=project|demo
 &period=1M|3M|6M|1Y|ALL&gran=DAILY|WEEKLY|MONTHLY
 &changes=auto|valid|none|no-baseline|degraded
```

Page-local filters live in the same query string, beside the view scope and never instead of it:

```text
/portfolio/positions?q=&dir=&sector=&strategy=&borrow=
/portfolio/trades?q=&status=&dir=&strategy=&outcome=&from=&to=
```

- **mode** — Executive is status, attention and change; Operator adds reason codes, metric
  identities, contract versions, provenance and source links.
- **env** — a **viewing scope** over the runtime `Environment` enum. Selecting Paper or Live
  advances **no maturity and no authority**; a scope change is a different cache key, so one
  environment's values are never flashed under another's badge.

  **Only `RESEARCH` is populated, and the other two are empty on purpose.** Every fact this
  application holds — the repository's own governance record, and the repository-owned
  synthetic fixtures — was produced in the `RESEARCH` runtime environment. There is no Paper
  and no Live cockpit data, so `env=PAPER` and `env=LIVE` return **payloadless**
  `NOT_IMPLEMENTED` responses rather than the same records under a different badge.
  Re-badging them would manufacture evidence of Paper or Live operation from a viewer's
  selection: **`AUTOMATED_PAPER` has never been reached, and live trading is HARD-DISABLED.**

  `maturity_stage` is **absent** on those responses. It is stated "where applicable"
  (`read-model-contracts.md` §3), no strategy version is involved here, and the envelope
  refuses any stage the accepted mapping of `COCKPIT_FEEDBACK_EXTENSION.md` §4.1 does not
  pair with the environment — so `AUTOMATED_PAPER` under `RESEARCH` cannot be published.
- **scenario** — `project` is the honest default; `demo` is the labelled synthetic scenario.
  **Synthetic is provenance, not a runtime environment.**
- **period** — the performance overview's comparison window. A **request parameter**, not a
  presentation preference: it changes the extent the series covers, so it is part of that read
  model's cache key, and one range's points can never be drawn under another range's label.
- **gran** — the granularity a performance series is requested at. Like `period`, it is a
  **request parameter** of one read model: daily, weekly and monthly returns are three different
  chain-linked series over the same window, not one series drawn three ways, so it joins that
  read model's cache key. The monthly heat map reads a **produced** per-period return series
  and derives nothing.
- **page filters** — search, side, sector, strategy, borrow, trade status, outcome and a date
  range. They narrow rows that were already delivered, they are visible as **removable chips**,
  and they survive a mode switch because they live in the URL (U13). **They change no total, no
  population and no permission**: every figure on a page is computed over the whole delivered
  page, and the row count says so.
- **changes** — which of §7's four comparison behaviours the What Changed panel shows. Three of
  them are only reachable when an endpoint is broken, and a reviewer cannot break a fixture from
  the interface — so the variants are selectable, deterministic, and honoured **only inside the
  already-labelled synthetic scenario**. It is a parameter of that read alone.

---

## The contract subset, exactly

**C4 transcribes a SUBSET of `read-model-contracts.md`, and the omissions are stated rather than
implied.** Five read models are implemented — `ExecutiveOverview`, `AttentionItem`,
`WhatChangedEntry`, `QualificationStatus` and `PerformanceSeries`.

### Completed by C4

The C3 foundation named its omissions; the ones C4's surfaces consume are now carried:

| | |
|---|---|
| `ExecutiveOverview.regime_ref` | present, kind `regime_context`, resolving `UNRESOLVABLE_V1` — the producer does not exist, and §4.3 keeps the reference **visible** rather than dropping the join |
| `ExecutiveOverview.last_decision`, `last_scout_run` | present, and both are **absences**. The Brain runtime is not implemented and not authorized, so there has never been a last decision or a last scout run — a plausible date here would be the one figure on the page implying otherwise |
| `ExecutiveOverview.what_changed`, `attention` | present as `RefList`s, and the summary counts come from `total` rather than from `items.length` |
| `RefList.total` | present on every list, as a `CountValue`. A truncated list must state a total **greater** than the items it carries, and a producer that cannot count says so with a state |
| envelope `watermark` | present on every payload-bearing response — "the source position the projection has consumed to". Taken from the **oldest** required input, and refused if it outruns `projected_time` |
| envelope `pins` | present as a full `VersionPins`. Every pin that does not apply **says so** (`NOT_APPLICABLE` with `NOT_DEFINED_FOR_SUBJECT`) rather than being omitted; the two that do apply — the read-model schema and the fixture scenario — are `SafeId`s |
| `PerformanceSeries` | added whole, with the §4.2 `Series`, `SeriesPoint` and `SignedMoney` types and the cash-flow, cost-treatment and drawdown-basis contracts |
| `QualificationStatus` | extended with each run's **date basis** and **minimum separation**, the **blocker chain**, the **next required governance event**, the **implementation phase**, and `snapshot_extracted_on` — kept separate from each fact's own `as_of` |

Two additions were made to the metric dictionary rather than invented at a call site: an
`INSTANT` metric shape, following the precedent `DATE_ONLY` already set — §4.2's `Unit`
vocabulary holds no unit for a point in time, only durations — and the metric keys the new
surfaces render. **An unregistered `metric_id` is still refused at admission.**

### Completed by C5

Nine catalogued read models were added with their per-field contracts, and the §4.4 records were
completed:

| | |
|---|---|
| **the four risk quantities** | `InitialPlannedRisk`, `CurrentOpenPlannedRisk`, `PermittedRisk` and `GapEventRisk` are now defined **in full and in one place**, `src/contracts/risk-records.ts`. C3 carried a two-field subset of two of them; **a second type with the same name is what §4.2 forbids**, so the subset was completed rather than duplicated, and the C4 executive overview was updated to the completed record |
| `PerformanceSummary` | the window, the ratios, the R-multiple distribution, the defined population and the cost treatment — plus per-metric **observation rules** and counted **exclusions**, so a ratio's minimum and its actual sample are displayable rather than implied |
| `PositionSnapshot`, `ExposureAggregate` | per position and per grouping axis, with the four magnitudes checked in **integer hundredths** at the boundary: gross is long plus short, net is their difference carried as a positive magnitude whose direction states the side, and a magnitude is never negative |
| `TradeSummary`, `TradeDetail` | the ledger row and one trade's story, with six cross-field invariants enforced at admission — status against share counts, exit fields against status, realized against a closed portion, unrealized against an open one, R against its initial record, and path-dependent values against completeness |
| `TradeLifecycle` | in the **basic** form C5 owns: the trade-level stages a recorded trade has, ordered by `event_time` with `observed_time` retained, plus an additive `absent_kinds` list naming every event kind this timeline does **not** carry |
| `StrategyPerformance` | keyed by module **and** exact version, with slices, the per-module measures Area 4 names, a recorded health **context**, and a family roll-up carrying **no diversification figure at all** |
| `RiskSnapshot`, `ShortSideSnapshot`, `MarketRegime` | the risk aggregate with its per-trade initial records and its named-but-unapproved thresholds; the borrow records with their own sources; and the versioned regime with its **declared** information-set profile |

Three additions were made to the contract rather than invented at a call site, and each is
labelled where it is defined: an additive `period_return_series` on `PerformanceSeries` — a
**separate `metric_id`**, because a per-period return and a cumulative one are different
quantities and §12.2 forbids sharing an identifier; a `scope` carried beside each permitted-risk
wrapper, so an **absent** limit can still name which limit is missing; and an `EMBEDDED`
resolution for the security and chart references, so a table of reference identifiers is
readable. The metric dictionary gained its C5 rows, each marked either a **§12.3 transcription**
or a **presentation definition proposed by this cycle** under §12.6. **An unregistered
`metric_id` is still refused at admission.**

### Still not carried

| | |
|---|---|
| **read models** | the rest of the catalogue. `CandidateFunnel`, `CandidateDetail`, `MissedOpportunity`, `ExecutionQuality`, `ReconciliationStatus`, `StrategyHealth`, `StrategyVersion`, `ResearchRun`, `DataQuality`, `Alert`, `FeedbackPipeline`, `SearchResultPage` and `AskAnswer` are not implemented, and their screens remain placeholders |
| **the complete `TradeLifecycle`** | order and fill mechanics, protective-order events, reconciliation and corrections. **C6 owns them**, and each is named as an absent event kind rather than left out |
| **finalized attribution** | strategy, factor, regime, execution and cost attribution are all `NOT_IMPLEMENTED` on the trade detail. A provisional zero would be a decomposition nobody computed |
| **rolling series and capacity** | no rolling-window series and no capacity figure is derived. Trailing performance is **five separate reads over five windows**, each with its own population; capacity needs a liquidity and market-impact model over qualified provider data, and **G1 is OPEN** |
| **slippage and execution cost** | unavailable everywhere. It needs a named reference price with its own timestamp per fill, and an execution runtime to record them |
| **cursor pagination** | the page contract carries its size, its total, its truncation flag, its sort key and its tiebreak. It carries **no cursor**: a cursor is meaningful only against a transport that can continue a page, and this local read client returns one page and continues none |
| **`PerformanceSeries` classification** | §4.5 classifies a real one `PRIVATE_OPERATIONAL`, which the `PUBLIC_EDGE` boundary **refuses**. What this application can show is a repository-owned synthetic demonstration, labelled `PUBLIC_SAFE` and `SYNTHETIC` because that is what it is. A real recorded series would be refused here rather than relabelled to fit the host |
| **`source_refs`** | carried, and empty on every response. The fixture adapter references no source fact, and states a total of zero rather than implying one |
| **`QualificationStatus` sources** | still a tracked `{path, commit}` rather than a §4.2 `Ref`: the reference resolves to a file in this public repository, which a `Ref` could not express |

**No claim is made that the catalogue is complete.** The remaining read models, payload fields
and metrics arrive with the cycles that produce them.

---

## Implemented in C5

| Route | Area | State |
|---|---|---|
| `/portfolio/performance` | 2 | **implemented** — equity, return and drawdown at a selectable granularity; realized and unrealized reported separately; the monthly heat map; the window summary with its observation rules and R distribution; trailing-window performance; and the benchmark surface |
| `/portfolio/positions` | 3 | **implemented** — a sortable, filterable TanStack table with a row detail, and seven exposure axes over the same positions |
| `/portfolio/trades` | 36 | **implemented** — the trade ledger, with search, typed filters, a date range and a row detail |
| `/portfolio/trades/[tradeId]` | 36 | **implemented (basic)** — identity, economics, both risk records, recorded reasons, the trade-level timeline, the price marks with their recorded markers, and every stage this cycle does not carry named as a gap |
| `/strategy/performance` | 4 | **implemented** — per module and per **exact version**, with slices, module measures, a recorded health context and the family roll-up |
| `/market/regime` | 11 | **implemented** — the versioned regime, its components, sector standing, long and short context and the recorded stress history |
| `/risk` | 12 | **implemented** — the four risk quantities kept apart, permitted limits reported as unapproved, named thresholds, and the tracked research parameters beside them |
| `/risk/short-side` | 13 | **implemented** — gross short, the borrow records with their sources, the short-specific states and the blocked shorts |

**A basic trade detail is not the full lifecycle**, and this cycle claims neither it nor Area 5.
The complete Candidate → Brain → Risk → Execution → Reconciliation → Attribution workflow is
**C6's**, Strategy Health is **C7's**, and Execution History and the Audit Trail are separate
screens in later cycles. **The four concepts stay apart**: the ledger, one trade's story,
execution mechanics and the audit trail share identifiers and never share a screen.

### The synthetic book

**One deterministic ledger, and every C5 screen is a projection of it.**

```text
8 fictional securities   DEMO.ARB, DEMO.NVL, DEMO.CIR, DEMO.HLX, DEMO.PLM,
                         DEMO.KTN, DEMO.MRD, DEMO.SOL -- across eight sectors
6 exact versions         breakout-long-v3, breakout-long-v2 (superseded),
                         pullback-long-v2, pead-long-v1, pead-short-v1,
                         deterioration-short-v1 -- in three alpha families
200 trades               5 open or partially exited, 195 closed
504 sessions             two years of weekdays on a named market calendar, ending at T-1
1 external cash flow     a deposit inside the three-month window
```

Every value is an **integer number of cents**, and rounding happens once, where a decimal string
is produced. Each trade carries a **daily mark path** with exact endpoints, and MFE, MAE, the
capture ratio and the equity curve are all read from those marks rather than invented separately.
Equity at each session is `strategy capital + realized to date + open unrealized + external
flows`, which is why the curve, the ledger, the positions and the per-version results **cannot
disagree**.

**The cases a reviewer should look for are deliberate, and each occurs exactly once:**

| | |
|---|---|
| a **pyramid add** | `demo-trade-nvl-0002` — two stages, each with its own retained initial-risk record, one row in the ledger |
| a **partial exit** | `demo-trade-cir-0003` — realized on the closed portion, unrealized on the remaining one, and it is not closed |
| a **moved stop** | `demo-trade-arb-0001` — the assessment moved and the entry record did not |
| a **stale assessment** | `demo-trade-plm-0005` — present, marked stale, shown with the instant it was true at |
| an **unknown borrow** | the same short — no borrow record exists, and every figure from it is unavailable |
| a **missing risk record** | `demo-trade-gen-0001` — no R, excluded from the population, and counted |
| an **incomplete price path** | `demo-trade-gen-0002` — `CLOSED` in status and `PARTIAL` in completeness |
| an **exact break-even** | several closed trades realize `0.00` — a measured zero, and `AVAILABLE` |
| a **losing module** | `pead-short-v1` reports a negative expectancy and a profit factor below one |
| a **population below its minimum** | `breakout-long-v2` has too few closed trades for any trade-count ratio |

**Nothing in it is a result.** There is no model, no market and no alpha: a fixed seed walks a
fixed step function between endpoints chosen by hand. Position sizes obey the `CLAUDE.md` §6
research parameters — 0.50% of capital long, 0.25% short, no position near the 8–10% ceiling,
gross short well inside 25% — and **a fixture obeying them is not a claim that anything enforced
them**.

**The owner's real activity is nowhere in it.** No account, no broker record, no provider row, no
private identifier and no real ticker appears anywhere in the book.

---

## Implemented in C4

| Route | Area | State |
|---|---|---|
| `/` | 1 | **implemented** — the Executive Overview: the five ten-second answers, the performance overview, Attention Required and What Changed |
| `/attention` | 28 | **implemented** — the ranked, deduplicated list, with severity and evidence filters and evidence drill-downs |
| `/governance/qualification` | 24 | **implemented** — run authorization and date eligibility as separate facts, gates read independently, P1–P9, the blocker chain and the next required governance event |
| `/governance/maturity` | 25 | **implemented** — the five maturity stages against the unchanged runtime `Environment` enum, with order authority stated for each |
| `/governance/controls` | — | **inert** — a static explanation of a future control plane |
| `/foundation/states` | — | **implemented** — the contract and state reference, a local review surface |
| every other registered route | — | a shared, clearly labelled **not yet implemented** page naming the area, its purpose, its producer or dependency and its intended cycle |

**A placeholder route does not implement its product area**, and C4 makes no claim that it does.
All 36 product areas remain in V1 scope, and the C5–C10 sequencing of the traceability matrix is
unchanged.

**`/portfolio/performance` in particular stays a placeholder.** The executive **performance
overview** on the landing page is three views over one series; it is **not** the portfolio
performance analysis C5 owns — no attribution, no trade population, no expectancy, no cost
decomposition and no summary statistics.

Trade History, Trade Detail, Execution History and the Audit Trail stay reserved as distinct
destinations; C4 implements none of their workflows.

### What C4 added, in one place

| | |
|---|---|
| **the five answers** | each tile is labelled with its **question**, so whether the ten-second test passes is checkable rather than asserted, and each links to the area that owns it |
| **the performance overview** | Recharts; three views (equity, return, drawdown); a period selector carried in the URL; an optional benchmark drawn as **its own line**; a keyboard-reachable table alternative carrying the same points; and gaps rendered as **breaks** rather than drawn through |
| **attention** | one shared ranking pipeline behind both the summary and the page — materiality, then severity, then a stable identifier tie-break — with deduplication by key, and **every withheld row reported** |
| **what changed** | an explicit window, both endpoint as-of times, the environment and provenance of the comparison, and four deterministic behaviours: verified changes, no verified changes, missing baseline, degraded endpoints |
| **governance** | Run B's date and its authorization as two separate facts on a stated calendar basis; the seven gates read independently; P1–P9 unevaluated; the blocker chain; the next required event; and the snapshot's source as-of kept apart from its transcription date |
| **maturity** | the accepted stage-to-environment mapping, read from the same constant the envelope validator enforces |
| **operator detail** | metric identity and unit, reason codes, per-input freshness contracts with their own ages and states, the composite state, coverage, watermark, snapshot version and the full pin set |

---

## What C5 does not contain

Everything in the C4 list below, unchanged, and:

```text
no rolling series          no capacity model         no slippage or execution cost
no cursor pagination       no export                 no OHLC or candle data
no benchmark price         no attribution            no borrow query
no short research          no regime computation     no strategy health transition
```

**Sorting, filtering and grouping are presentation.** They re-order and narrow rows this page was
already served; they issue no request, change no scope, compute no metric and grant no
permission. A truncated page stays truncated and says so, and every figure above a table is
computed over the whole delivered page rather than over the filtered view.

**No headroom is computed anywhere.** Showing a permitted limit is not granting it, and
subtracting a carried figure from a limit would present an amount of capital as available to
deploy. That is a decision, and no interface takes it.

---

## What C4 does not contain

```text
no production read API        no projection runtime      no metric engine
no FastAPI service            no database                no migration
no scheduler                  no container               no deployment
no LLM SDK and no model call  no route handler           no server action
no API route                  no control handler         no mutation of any kind
no provider, broker, AWS, GitHub, LLM or analytics request -- at runtime or at build time
```

**Every future control is inert, and inert means ABSENT.** There is no acknowledge, dismiss,
resolve, snooze, assign or suppress on the attention surface; no run, authorize, approve, start,
execute, promote, advance or retry on either governance surface; no form and no input element on
any of them. None is a disabled button waiting to be enabled — there is no handler and no route
that could carry one. Each would change state in a system this application only reads, and a
control that appeared to work while doing nothing would be worse than its absence.

**Ask KalpaMani is not implemented and is not exposed.** It appears in no route, no navigation
entry and no palette command, so there is no surface that could accept a question. **No model is
called, no model SDK is installed, and no answer is simulated.**

**Nothing here is a trading decision.** No order, size, stop, route, capital change or risk-limit
change is produced, suggested or enabled, and a recommended action is a **permitted governance
action** for a person to take elsewhere.

---

## Governance

**Implemented by this cycle, and pending independent review and merge.** Merging C5 authorizes
no further cycle: **specification, implementation, deployment and execution stay separate
gates**, and C6 is a separate written authorization that has not been given.

```text
C3 application foundation                         MERGED (PR #74)
C4 executive overview and governance              MERGED (PR #75)
C5 portfolio, strategy, exposure and trades       IMPLEMENTED HERE / PENDING REVIEW
trade detail                                      BASIC -- C6 owns the full lifecycle
strategy health                                   RECORDED STATE ONLY -- C7 owns area 5
full Cockpit V1                                   NOT COMPLETE -- 11 of 36 areas implemented
production read API, projections, metric engine   NOT IMPLEMENTED / NOT AUTHORIZED
feedback and self-maturation automation           NOT IMPLEMENTED / NOT AUTHORIZED
Strategy Brain runtime                            NOT IMPLEMENTED / NOT AUTHORIZED
deployment and real-source integration            NOT AUTHORIZED
Run A retry / Run B / combined assessment         NOT AUTHORIZED / NOT RUN
P1-P9                                             UNEVALUATED
data correctness and quality                      NOT ESTABLISHED
G1 / G2                                           OPEN / OPEN
G7 strategy-taxonomy evidence                     OPEN -- no diversification claim is made
provider selected                                 NONE
backtesting                                       NOT STARTED
Phase 3                                           NOT COMPLETE
CONTROL publication                               DEFERRED
live trading                                      HARD-DISABLED
```

### C3 — corrections made under independent review

Four defects were found by independent review of the C3 branch and corrected on it. Each is
locked out by a regression in [`tests/regressions.test.ts`](tests/regressions.test.ts), and
each regression was confirmed to fail when its defect was re-introduced.

| | |
|---|---|
| **`projection_lag` moved when only the evaluation time did** | it reconstructed a source time as `origin − age`, where the age had been measured at *evaluation* time, so the lag became a second copy of `source_age` and grew on every refetch — while the source fact and the build were both unchanged. Each age is now measured from its own pair of instants: `source_age` from the **oldest** required input (§3.1), `projection_lag` from the **newest** (§12.3), `build_age` from `projected_time`. A negative age **beyond the declared clock tolerance** is refused rather than clamped to zero — **as written here that claim was overstated, and C4 corrected what it overstated**; see [C4 — the two foundational corrections](#c4--the-two-foundational-corrections) |
| **freshness admitted contradictory and unreal input** | `composite_state: AVAILABLE` was trusted over a required input that was `STALE`, and a missing source time was reported as an invented `STALE` rather than the `NOT_YET_AVAILABLE` with `SOURCE_TIMESTAMP_MISSING` that §3.1 fixes for it. An instant was validated by **spelling only**, so `2026-02-30` silently rolled over to `2026-03-02` and `2026-13-01` became `NaN` — and `serve_time >= NaN` is false, so that entry could never expire. Instants must now round-trip exactly, and a report that contradicts its own inputs is **refused at the boundary** |
| **metric payloads were not validated to their types** | `MetricValue.value` was `unknown` with only a presence check, so `null`, an object, a boolean, `NaN` and a malformed decimal all reached a formatter on an `AVAILABLE` reading. Each metric is now registered with its unit and value shape, and the formatter never falls back to `String(value)` |
| **a scope selector re-badged existing records** | `scope.environment` was applied to reused fixtures while `maturity_stage` stayed `RESEARCH`, so selecting Live showed the **real tracked governance facts** under a Live badge. Cache keys derived provenance from the **scenario**, labelling tracked facts `SYNTHETIC` in demo and fixtures `REPOSITORY_TRACKED` in project. Provenance now comes from the read model itself, keys carry classification and access scope as §7 requires, and unpopulated environments are explicitly unavailable |

Two smaller corrections followed from them: a run's date gate was carried in `CALENDAR_DAYS`
— a unit of *duration* — for a value that is a calendar date, and money was re-formatted
through `Number()`, round-tripping a decimal string through a binary float at the last step
before display.

### C4 — the two foundational corrections

**Two freshness defects survived that review, and C4 corrected them before adding any
consumer.** Both are locked out by
[`tests/freshness-corrections.test.ts`](tests/freshness-corrections.test.ts), each with a
**negative control**: the pre-correction expression is reimplemented inline and shown to
violate the invariant, and each defect was re-introduced into the source to confirm its
regression fails.

#### A — a negative age could still become a measured zero

The C3 note above claimed plainly that "a negative age is refused rather than clamped to
zero". **The implementation refused only *beyond* the declared two-second clock tolerance**,
and then applied `Math.max(0, Math.floor(exact))` on three paths — the per-input `source_age`,
the composite `source_age`/`projection_lag`/`build_age`, and the tracked-snapshot age in the
adapter. A source dated up to two seconds *after* its own evaluation instant floored to −1 or
−2 and was lifted back to a clean `0` carrying `AVAILABLE` and `NONE`: a fabricated "just now",
with nothing on the screen saying two clocks disagreed.

**The accepted treatment was already written, and is now implemented rather than approximated.**
`read-model-contracts.md` §3.1 states three bands, and one function owns all three:

```text
exact  <  -tolerance   UNKNOWN -- refused; the age is never rendered and never zero
-tol  <=  exact <  0   ZERO, AND FLAGGED -- "a small skew is ordinary and a silent one is not"
exact  >=  0           floor(exact) -- whole seconds, on a NON-NEGATIVE quantity only
```

- **`Math.floor` is applied only to a non-negative quantity**, so it can never deepen a
  negative duration, and **no age clamp remains anywhere**. The one surviving
  `Math.max(0, …)` is `remaining_freshness`, where §3.1.1 puts it: it bounds a spent budget,
  not a measurement.
- **A valid source age of exactly zero stays valid**, measured, `AVAILABLE`/`NONE` and
  unflagged. A measured zero is a result (ADR-0029 §2.1); only a *negative* exact age is
  flagged.
- **The flag is a separate axis**, `FreshnessInput.clock_skew_flagged`. The §4.1.1 matrix
  admits only `NONE` beside `AVAILABLE`, so a skew spelled as a reason code would have to
  either fabricate a failure state or stay silent — and silence is the defect. It renders as
  its own mark on the freshness indicator.
- **Admission checks the number, not only the state.** A producer declaring
  `CLOCK_UNSYNCHRONIZED` while reporting a measured `0` is refused, and so is a reported age
  that disagrees with the input's own instants, a negative `projection_lag` or `build_age`, and
  a composite `source_age` that is not the oldest required input's own age.
- **Fixture construction refuses impossible input** rather than emitting it: a projection dated
  before the newest source it consumed, or an evaluation dated before the build it read.
- **`projection_lag` still uses its own defined source input** (the *newest* required input,
  §12.3) and `source_age` its own (the *oldest*, §3.1). A refetch with fixed source and
  projected instants leaves the lag exactly where it was.

#### B — a composite over mixed required failures was order-dependent

`effectiveComposite` returned the **first** required input in array order that was not
`AVAILABLE`, and admission accepted any composite naming **any** unhealthy input's state.
Reordering the same two required inputs therefore changed the diagnosis on screen with no
change to the facts: a `STALE` mark and a `SOURCE_TIMESTAMP_MISSING` snapshot rendered as
either one, depending on which happened to be listed first.

**No enum ordering was invented, and no "first failure wins" policy was written down.** §3.1
says the composite "takes the **worst** state any required input reached" and fixes only
`AVAILABLE` and `STALE`; it defines no ordering across the other nine states. So:

| | |
|---|---|
| every required input `AVAILABLE` | the composite is `AVAILABLE` |
| **one** distinct failure `(state, reason)` | that failure **is** the worst one, and the composite must be exactly it |
| **several** distinct failures | the contract determines no unique composite, so the report is **refused at admission**, naming every way it failed — and each input keeps its own state and reason for inspection |

The signature is the `(state, reason)` **pair**, not the state alone: `PARTIAL` admits five
reasons, and two `PARTIAL` inputs with different reasons still leave the composite reason
undetermined. Signatures are compared by value and sorted, so **a supported report produces
the same result under every permutation of its inputs**, and optional inputs never set the
composite state nor make a supported report ambiguous. If a mixed report ever reaches the
renderer anyway, it **fails closed** on `ERROR`/`PROJECTION_ERROR` rather than picking one of
its answers.

### C4 — corrections made under independent review

**An independent review of the C4 head reproduced six further defects, and each is corrected
here.** They are locked out by
[`tests/c4-review-corrections.test.tsx`](tests/c4-review-corrections.test.tsx) and
[`e2e/u1-first-viewport.spec.ts`](e2e/u1-first-viewport.spec.ts). **Every one of them was
reproduced against the reviewed implementation before a fix was written**, and each correction
was confirmed by re-introducing its defect into the source and watching the regression fail.

#### A — a degraded endpoint was presented as a valid change

`ui-ux-specification.md` §7 and **U17** require that where either endpoint is
`NOT_YET_AVAILABLE`, `STALE` or `PARTIAL`, the item **reports that state instead of a delta**.
The row drew `before → after` with an arrow, asserted the entry's materiality, and attached
**one** availability badge taken from `entry.after` — so a **stale baseline compared against a
sound comparison endpoint was reported behind the after endpoint's `AVAILABLE`**, which is the
one endpoint that was fine.

- **No arrow, no delta and no asserted materiality** over an unsound comparison. The row
  carries `data-comparison="UNAVAILABLE"` and reads `NOT COMPARABLE` where a materiality badge
  would otherwise be.
- **Each endpoint answers for itself.** `baseline` and `comparison` are separately labelled,
  each with **its own** state badge, **its own** reason and **its own** as-of — so which
  endpoint is degraded is stated rather than inferred.
- **The values are kept as diagnostic detail**, because a stale number is still evidence; it is
  simply never presented as a comparison a reader can trust.
- Baseline-only, comparison-only, both-degraded, absent and sound endpoints are each covered.

#### B — absence was treated as proof of appearance

`read-model-contracts.md` §4.5 states the invariant plainly: **"a change is never synthesised
from the absence of a value"**. A missing `before` was rendered as "no prior value for this
subject — reported as an appearance", which reads *the subject was not there before* out of
*this response carries no prior value for it*. Those are different claims, and only the second
was established. The fixture asserted the stronger one **in a code comment**, where neither the
schema nor the component could check it.

**No population-completeness metadata was invented.** The claim is read from the accepted
envelope field that already states it — `completeness`:

| | |
|---|---|
| `COMPLETE` | the comparison covered the extent it was asked for, so a subject absent from the baseline was **verified absent**, and the appearance is reported as one |
| `PARTIAL` / `UNKNOWN` | the prior population is **not known to be complete**, so a genuinely absent subject cannot be told apart from one the comparison never covered. The row reports `NOT_YET_AVAILABLE` with `EXTENT_PARTIALLY_COVERED` or `EXTENT_NOT_DETERMINABLE` and **states that no change is inferred** |

**A valid numeric zero in an observed prior record stays a delta** (ADR-0029 §2.1), and a prior
producer that was unavailable is still refused at admission rather than rendered as a change.

#### C — an empty list asserted a verified nothing

`payload.entries.length === 0` rendered `EMPTY_VERIFIED` and the sentence *"Both endpoints are
sound and nothing changed between them"* — while the envelope's own `completeness` could be
`PARTIAL`, which the panel then reported separately, further down, in a footer. **A comparison
that did not cover its extent has established nothing about the part it did not cover.**
`EMPTY_VERIFIED` now requires `completeness === "COMPLETE"` **and** an `AVAILABLE` envelope;
anything else renders the coverage state and says the difference in those words.

**Evidence became a drill-down rather than a count.** The row previously showed
`evidence 1 · UNRESOLVABLE_V1` as operator-only text. Every reference is now disclosed in
**both** modes with its kind, its **own** resolution, its classification and a link to the area
that owns it, and `UNRESOLVABLE_V1` is rendered **with** that stated resolution rather than
dropped — it is a resolution to an availability state, not a gap (§4.2). A change carrying **no
reference at all** is not rendered, and the withheld count is stated.

#### D — attention deduplication was order-dependent and could not report a conflict

The pairwise fold compared each arriving record against whichever one it was holding, on
`last_seen`, then the occurrence count where **both** were known, then the identifier. With
three records at one `last_seen` and one unknown count the preference is **not transitive** —
`c` beats `a` on count, `a` beats `b` on identifier, `b` beats `c` on identifier — so the
survivor depended on the order the producer emitted them in. **All three won**, one per input
permutation, which the regression reproduces exactly. It also kept whichever record arrived
**first** when two agreed on identity, time and count but disagreed on content.

Deduplication is now **grouped**, and the group is narrowed only by rules that actually
establish a winner:

```text
1. the newest last_seen supersedes older observations of the same thing
2. a strictly larger occurrence count wins ONLY when every remaining record states one --
   an unknown count is not a larger number and not a smaller one, so it orders nothing
3. records identical after that are the same record, and collapse
```

**What survives step 3 is a genuine conflict, and none is invented.** No JSON ordering, no
arbitrary severity and no fabricated zero count decides it. The group is reported as
**conflicting**, one record is still shown **so the underlying issue does not disappear from
the list**, and the row renders it as an unresolved conflict rather than as the current
version. The counts stay separate and are never conflated: **ranked total**, **withheld
incomplete**, **rows folded** and **conflicting keys** answer four different questions.

#### E — severity was ranked by a bare code string

`severityRank` took `item.severity.code` alone, so `HIGH` in **any** vocabulary took this
vocabulary's rank, its tone and its glyph. A `ReasonCoded` is a code **plus** the vocabulary and
version it belongs to; the ordering is now declared over exactly one `(vocabulary, version)`
pair and everything else is `UNRANKED` — after every ranked severity, and labelled.

#### F — the first-viewport criterion was measured, and did not hold

**U1 and §6 require the five answers *and* Attention Required inside the first viewport at
1440 × 900.** The desktop check measured the bounding box of each **question label** and only
the **top edge** of the first attention item. Measured against the running application, the
first ranked item spanned **y = 818 → 1024**: its impact, its recommended governance action and
its evidence affordance were **124 pixels below the fold**. The criterion was reported as met
and was not met.

- **The layout was corrected, not the assertion.** The executive summary renders a **dense**
  attention row — impact, the recommended action and the evidence affordance share a line, and
  the panel and page reclaim spacing. **All five presented things are still rendered, at the
  same type sizes**; rows are combined and **no content is reduced, truncated or hidden**. The
  dedicated `/attention` page is unchanged.
- **Measured after the correction**, at 1440 × 900: every answer tile ends above the fold, and
  the first ranked item spans **758 → 883** in the populated demonstration. In the default
  project view the attention panel's own availability answer ends at **895**. Nothing is
  scrolled: `window.scrollY` is `0`.
- **The check now measures the whole tile and the whole item**, asserts each of the five
  presented things is visible, **opens the evidence affordance to prove it works**, and checks
  every measured element for vertical clipping of its own box.
- **U1 is stated at one width, so it is registered at one width.** `playwright.config.ts`
  ignores this spec in the tablet and mobile projects rather than skipping it inside them: a
  `test.skip` reported a criterion as skipped at two viewports it was never in scope for. §12
  gives tablet and mobile their own, different requirements, and every other spec still runs at
  all three widths.

### C5 — three defects found by measuring, and corrected

Each was reproduced against the running application before a fix was written. None changes an
accepted contract; each brings the implementation back to one.

| | |
|---|---|
| **the page scrolled sideways while every container looked correct** | a wide table inside an `overflow-x: auto` region still contributed its full width to the document's scroll width, so **U14 failed on `/portfolio/trades` at 1024 × 768 and on two routes at 390 × 844** — and a programmatic horizontal scroll actually moved the page by the overhang. Paint containment on the shared `ScrollRegion` makes the clip authoritative, and it removes the same latent overflow from the merged C4 evidence strip. **The layout was corrected, not the assertion**, and the column priority of the two dense tables was declared and measured rather than guessed |
| **secondary chip text failed the contrast requirement** | reference chips dimmed their resolution and classification with `opacity`, which measured **2.83:1** and **3.80:1** against §11's 4.5:1 body-text requirement, on twenty-six nodes of `/risk` alone. Hierarchy now comes from the design token rather than from fading text out. The heat-map tint was capped for the same reason: at full strength its cells measured **1.9:1**, so the tint is now a secondary cue and the signed number is the primary one |
| **a leading plus was printed on quantities that have no direction** | `+41.85 USD` beside an entry price reads as a gain of 41.85. A unit says a value *could* be directional; the field says whether it *is*. Profit, loss and return carry a sign; a price, a risk amount, a permitted limit, a share count and a concentration are magnitudes, and a negative one still shows its minus |

**One fixture property was corrected for honesty rather than for a test.** The generated entries
originally stopped far enough from the snapshot that the one-month window contained no closed
trade at all, so every ratio in that column read `INSUFFICIENT_OBSERVATIONS` — true, and it read
as a broken column rather than as a rule. Entries now spread closer to the end of the retained
extent, and the short windows demonstrate the rule with a real population behind it.

### Validation

Reproduced on the C4 head, on Node 22.21.0 and npm 10.9.4:

```text
npm ci --no-audit --no-fund     clean install from the committed lockfile
npx eslint .                    clean
npx next build                  succeeds -- 31 static routes, no API route
npx tsc --noEmit                clean (run after a build; route types are generated)
npx vitest run                  148 passed   (C3 baseline was 84)
npx playwright test             172 passed, 2 skipped, across 1440x900, 1024x768 and 390x844
```

Reproduced again on the reviewed and corrected head, on the same toolchain:

```text
npm ci                          clean install from the committed lockfile
npx eslint .                    clean
npx tsc --noEmit                clean
npx vitest run                  173 passed   (C4 author head was 148; C3 baseline was 84)
npx next build                  succeeds -- no API route
npx playwright test             176 passed, 0 skipped, across 1440x900, 1024x768 and 390x844
```

**The two skips are gone because the U1 spec is registered only at the width U1 is stated at**,
not because a skip was suppressed: the tablet and mobile projects no longer register a
desktop-only criterion at all, and their own viewport coverage is unchanged.

The two skipped Playwright cases are the ten-second-test viewport assertion on the tablet and
mobile projects: **U1 is stated at the reference desktop width**, and asserting it at a width the
specification does not state it for would be asserting something else.

The repository's own gates were run on the same head, and on the exact baseline commit before any
edit, so the two are comparable:

```text
pytest -q                       7074 passed        (unchanged from the baseline)
ruff check .                    all checks passed
ruff format --check .           263 files already formatted
mypy                            no issues in 181 source files
scripts/phase3_docs_audit.py    AUDIT PASSED
scripts/test_integrity_audit.py AUDIT PASSED
git diff --check                clean
```

Reproduced again on the C5 head, on the same toolchain:

```text
npm ci                          clean install from the committed lockfile
npx eslint .                    clean
npx tsc --noEmit                clean (run after a build; route types are generated)
npx next build                  succeeds -- 32 routes, one of them dynamic, no API route
npx vitest run                  261 passed   (C4 baseline was 173)
npx playwright test             263 passed, 0 skipped, across 1440x900, 1024x768 and 390x844
```

The repository's own gates were run on the exact baseline commit before any edit, and again on
the C5 head, so the two are comparable:

```text
pytest -q                       7074 passed        (unchanged from the baseline)
ruff check .                    all checks passed
ruff format --check .           263 files already formatted
mypy                            no issues in 181 source files
scripts/phase3_docs_audit.py    AUDIT PASSED
scripts/test_integrity_audit.py AUDIT PASSED
git diff --check                clean
```

**No test was weakened, skipped or suppressed.** Two C4 assertions were **retargeted rather than
relaxed**: the executive exposure figure now asserts the book-derived long exposure, because the
overview reads the same ledger the position table does; and the two trade-table separations are
asserted in the **row detail**, which is present at every viewport, because their columns drop
under the declared column priority on a narrow screen. Both still assert a concrete rendered
fact, and one new case was added for the trade that is `CLOSED` in status and `PARTIAL` in
completeness.

**Local validation is local.** These were run on a workstation, not by a CI service, and no
CI status check exists for this application.

**What was checked by hand, and what was not.** Every C5 screen was inspected at 1440×900,
1024×768 and 390×844 in the executive, operator, project and demo combinations; keyboard
navigation, focus restoration, the row disclosures, the filter chips and both chart table
alternatives were exercised directly; and `@axe-core/playwright` reports **no violation at all**
across the WCAG 2.1 A and AA rule sets on every C5 route, at every viewport, in Operator mode —
a stricter check than the C4 suite's serious-and-critical filter, and it is asserted rather than
sampled.

**An automated pass is not an accessible interface**: no screen-reader pass was performed, so
nothing here claims one, and the price chart's canvas is explicitly **decorative** with a table
alternative carrying the same marks and the same recorded events. **No performance target was
measured** — the specification sets those as targets for a later cycle, and this cycle measures
nothing and claims nothing.

**Browser network traffic was checked and is empty.** Across every C5 route the browser issued
**no request to any origin other than the local dev server**, and the console logged **no error
and no hydration mismatch**.

### Dependencies added by C5

```text
lightweight-charts  5.2.1   Apache-2.0   TradingView Lightweight Charts
fancy-canvas        2.1.0   MIT          its single transitive dependency
```

**One dependency, and the specification names it.** `ui-ux-specification.md` §13 assigns **price
and trade overlays — OHLC and candles, and Trade Detail entry, add, stop and exit markers** to
TradingView Lightweight Charts, and the trade detail is that surface. Compatibility was checked
from the published package metadata: it declares **no peer dependency and no engine constraint**,
ships its own TypeScript types, and carries exactly one transitive dependency. It is imported
**inside one effect in one component** — a static test asserts that no other module names it —
so a server render and the test environment touch no canvas, and the component draws only where
`matchMedia` and `ResizeObserver` exist.

**It draws a mark line, not candles.** Open, high, low and close need a market-data provider,
**no provider is selected and G1 is OPEN**, so the chart carries one recorded mark per session
and says so on screen.

Third-party attribution is in [NOTICE.md](NOTICE.md).
