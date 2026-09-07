# KalpaMani Cockpit — C6 signals, explainability and the complete trade lifecycle

The signal and candidate funnel, candidate explainability, missed opportunities, and the complete
synthetic trade lifecycle with its chart drill-down — built on the merged C3 foundation and the
C4 and C5 screens, under
[ADR-0027](../../docs/decisions/ADR-0027-cockpit-and-feedback-architecture-and-governance.md)
and the corrected contracts of
[ADR-0028](../../docs/decisions/ADR-0028-cockpit-contract-completion-and-boundary-corrections.md)
and
[ADR-0029](../../docs/decisions/ADR-0029-valid-zero-values-and-cache-freshness-deadlines.md).

**This is C6. It is not the Cockpit.** C3 delivered the design system, shell, navigation and
contract layer; C4 added the Executive Overview, the performance overview, Attention Required,
What Changed and two governance screens; C5 added seven product areas and a **basic** trade
detail; C6 adds three product areas and completes a fourth — still running on a **local fixture
adapter**, and still with no production read API, projection or metric engine behind it.

**Fourteen of the thirty-six product areas are addressed, and all fourteen are finished within
their documented accepted scope.** *Finished* here means every requirement the accepted
specification states for that area is either demonstrated or reported as an honest absence with its
named dependency — it does not mean the area has a production producer behind it, and the count of
areas is not itself evidence of completion. The named limitations are in *What C6 does not contain*
and in the **C5 completion follow-up** below, and they are part of this claim rather than
exceptions to it.
Areas 1, 24, 25 and 28 from C4; areas 2, 3, 4, 11, 12, 13 and 36 from C5; and areas **6** (Signal
and Candidate Funnel), **7** (Candidate Detail and Explainability) and **8** (Missed
Opportunities) from C6 — the C6 row of the traceability matrix. **Area 36 was deliberately split
across two cycles and is now complete**: C5 delivered its ledger and a basic detail, and C6
delivers the Candidate → Brain → Risk → Order → Fill → Protection → Add → Exit → Reconciliation →
Attribution reconstruction and the chart drill-down. The other twenty-two remain registered,
reachable placeholders, and the C7-C10 sequencing is unchanged.

**Two boundaries are worth naming up front.** **The Brain runtime does not exist**: no candidate
here was produced by a scanner, a factor matrix, a decision compiler or a model, and nothing on
these screens is a decision anything made. And **Area 5, Strategy Health, is C7's** — the strategy
screens still display a recorded health state and implement none of the transitions, drift
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

**Recharts is pinned to 3.10.1**, the current stable release, and it was the one dependency C4
added. `ui-ux-specification.md` §13 assigns "executive and time series — KPI trends, equity and
drawdown curves, ordinary comparisons" to Recharts, so the choice is transcribed rather than
made here. Its published peer range is `react ^16.8 || ^17 || ^18 || ^19` and
`react-dom ^16 || ^17 || ^18 || ^19` against this project's React 19.2.8, and its engine range is
`node >=18` against Node 22.21.0; `npm ls` resolves it with no unmet peer.

**TradingView Lightweight Charts 5.2.1 is installed, and C5 added it.** §13 assigns
price and trade overlays to it, and the trade detail is that surface — the full entry is under
*Dependencies added by C5* below. An earlier revision of this file said it was **not** installed,
which was true of C4 and stopped being true when C5 added it; the statement is corrected here
rather than left to contradict the lockfile.

**Apache ECharts — the third class §13 names — is still not installed.** It belongs to dense
analytics, which no cycle so far renders.

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
src/data/fixtures/ the deterministic fixture adapter, the ONE synthetic book every C5 and
                   C6 screen is projected from -- its trades, its declared execution
                   evidence and its journaled candidate decisions -- and the tracked
                   governance facts
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
| `ExecutiveOverview.regime_ref` | present, kind `regime_context`, resolving `ENDPOINT` — its row lists no other member. **It resolved `UNRESOLVABLE_V1` until ADR-0030 was implemented**, which said the PRODUCER does not exist; whether a producer exists is now a separate axis carried by the value-bearing field beside the reference, and §4.3 keeps the reference **visible** either way |
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

### Completed by C5, and superseded in part by C6

The four rows below record what C5 declared as **not carried** and what C6 has since done with
each. **Two of them are now carried, two remain outstanding, and one is outstanding in a narrower
form than C5 stated it** — see *The C5 coverage questions, answered* below for the full
disposition.

### Completed by C6

Four catalogued read models were added with their per-field contracts, and one was completed:

| | |
|---|---|
| `CandidateFunnel` | the four stages, the eight Brain states as a **closed set**, the nine downstream stages on a **separate axis with its own counts, its own counting basis and its own stated population**, the conversions with **both** of their counts and **both** of their subjects, and a per-module view. §4.5 makes the downstream `count` a required field, so a recorded count is admissible and the V1 `NOT_IMPLEMENTED` invariant governs **real** data — exactly as Area 6's own *V1 availability* reads "`SYNTHETIC` demonstration; real candidates `NOT_IMPLEMENTED`" while the Brain axis beside it is demonstrated the same way. Its refinement refuses a **mixed counting basis**, a count with **no population to divide by**, a stage exceeding that population, an `overlapping` flag contradicting its basis, an availability disagreeing with its own count, and approvals plus declines together exceeding the one population they partition — and still refuses a Brain axis that does not partition the consolidated stage and a rate between two stages counting different subjects |
| `CandidateSummary`, `CandidateDetail` | the candidate ledger and one decision's whole explanation: thesis, entry condition, ranking context, deterministic factor evidence, AI research and challenger evidence with per-reference provenance, contradictions, evidence gaps, the invalidation **reference**, the risk context and the downstream references. **The refinement refuses a `USD` or `SHARES` quantity anywhere in either payload**, refuses a blocked candidate with no reason, and refuses AI evidence recorded as having cleared a block |
| `MissedOpportunity` | the recorded cause, the **registered** measurement window, detection and decision instants with the delay between them, both excursions, the counterfactual and its assumptions, the follow-up path, the recurring causes, the taken-versus-missed comparisons and the rates. **The refinement refuses a money counterfactual, refuses an `AVAILABLE` path-dependent value over an incomplete path, refuses a rate with no population and refuses a difference between two arms it has declared incomparable** |
| `ExecutionQuality` | for **one trade**, embedded on its detail — not the Area 9 aggregate surface, which is a later cycle. Each fill against its named reference price, with the four order sides and the `side_sign` that makes an adverse buy and an adverse sell both read positive |
| `TradeDetail`, `TradeLifecycle` | completed. Orders, fills, protective-order placement, amendment, correction and cancellation, reconciliation, a declared attribution and a benchmark aligned to exactly the trade's holding period — **for the six trades whose execution evidence a fixture actually records** |

Six additions were made to the contract rather than invented at a call site, and each is labelled
where it is defined: a `subject` on every funnel stage, because two stages counting different
subjects must never subtract; `numerator`, `denominator`, both subjects and a `comparable` flag on
every conversion, so a rate is checkable rather than asserted; an `overlapping` flag on every
reason count, because one candidate may carry several blocking reasons; per-reference AI
provenance beside `ai_evidence_refs`, because a `Ref` carries no model, prompt or publish time;
`price` on the reference-price record, because slippage is not checkable without the third number;
and `execution_quality`, `fill_quality`, `benchmark_series`, `benchmark_window` and
`benchmark_label` on `TradeDetail`, each present exactly when its reference states it is embedded.
The metric dictionary gained its C6 rows, each marked either a **§12.3 transcription** —
`slippage`, `latency.signal_to_order`, `latency.order_to_fill` — or a **presentation definition
proposed by this cycle** under §12.6. **An unregistered `metric_id` is still refused at
admission.**

**One resolution was chosen deliberately and is recorded here.** §4.3 assigns `brain_decision` an
`EMBEDDED` resolution, because the journaled decision status lives **inside** `CandidateDetail`.
From `TradeDetail` it is not inside that response, so calling it `EMBEDDED` would claim a payload
this response does not carry. Where a candidate was journaled, it is one authorized read away and
is carried as `ENDPOINT`; where none was, it resolves to an availability state like every other
absent producer. `ENDPOINT` is an accepted member of the closed `Resolution` vocabulary, and no
producing contract was widened.

**That reconciliation has since been accepted, and the reference contract is now ENFORCED.**
[ADR-0030](../../docs/decisions/ADR-0030-cockpit-reference-resolution-and-unavailable-targets.md)
recorded five findings the accepted text could not be enforced through — twenty-five
reference-valued fields carried no kind at all, nineteen scalar `Ref` and six `RefList`;
`brain_decision`'s only carrier could not embed it; the Resolution column was already a set rather
than an invariant; the Cardinality column had three possible referents; and no reason code
distinguished an unknown identifier from an unimplemented producer. The bounded implementation
follow-up its §7 assigns is what this section now describes. **The C6 choice recorded above is
RATIFIED by R5 rather than reversed.**

### The reference boundary

**Where it is enforced.** `contracts/references.ts` carries the closed `RefKind`, the per-kind
permitted resolution sets and the host-field catalogue; every reference-valued field in every
payload is declared through `refOf` or `refListFieldOf`, so the rules run inside the same
`schema.safeParse` that `admit` already called. **A helper tested in isolation but bypassed by the
client is not enforcement**, so the checks sit on the path the fixture adapter actually takes.

| | |
|---|---|
| **`RefKind`** | closed at the **twenty-seven** rows of §4.3, replacing `z.string().min(1)`. `trade` is the member ADR-0030 R1 added |
| **resolutions** | each kind's row is a **permitted set**, and a reference declares one member of it. A kind whose row lists no `UNRESOLVABLE_V1` cannot declare one |
| **`EMBEDDED`** | needs catalogue **permission** *and* **truth**. §4.3.2 names seven authorized carriers, says whether each holds the complete target or a **declared projection**, and states its identity correspondence. **Presence is not permission** |
| **identity** | compared against the **target entity**, never the container. The identifier-less `security` projection is compared on its canonicalized `symbol` and **never on the display name** |
| **cardinality** | the host field's own declaration governs; `items`, `total` and `truncated` are kept apart, and no relation is asserted from a page or from a total nobody took |
| **absence** | `REFERENT_NOT_FOUND` was added to both closed vocabularies. An implemented producer missing one record says so; only a producer that does not exist for the scope is `PRODUCER_NOT_IMPLEMENTED` |
| **navigation** | one closed allowlist keyed by `RefKind`, in `lib/reference-navigation.ts`. Two duplicated destination maps in the components are gone; an unmapped kind yields **no link**, and a `ref_id` that is not a `SafeId` yields none either |

**Four `EMBEDDED` declarations were withdrawn, and one of them was untrue rather than merely
unpermitted.** `add_refs` and `exit_ref` resolve to lifecycle **events** this response does not
carry; `ShortSideSnapshot.borrow[].security_ref` sat beside a display string with no identifier to
compare; and `RiskDecision.initial_risk_ref` claimed an embed of a record `RiskDecision` carries
nowhere at all.

**Both mislabelled trade references are corrected.** `CandidateDetail.downstream_refs.trade` and
`RiskSnapshot.initial_planned_risk_open[].trade_ref` are kind `trade` resolving by `ENDPOINT` —
the value C6 had to guess twice, because §4.3 supplied no `trade` row until R1 added one.

**Thirteen `schema_version`s moved to `v2`, and six did not.** ADR-0030 §6.1 permits a coordinated
replacement without a bump only while four deployment constraints hold, and **the fourth does
not**: `QualificationStatus` carries `REPOSITORY_TRACKED` provenance over real tracked governance
facts, so "provenance is `SYNTHETIC` throughout" is false of this boundary. The follow-up is
required to bump rather than proceed, and it did. Which read models moved was established by
**diffing every emitted payload against the same payload built from the pre-change tree** rather
than by judgement: the thirteen whose bytes changed are `v2`, and `CandidateFunnel`,
`MarketRegime`, `MissedOpportunity`, `PerformanceSeries`, `PerformanceSummary` and
`QualificationStatus` are byte-identical and stay `v1`.

### Still not carried

| | |
|---|---|
| **read models** | the rest of the catalogue. `ReconciliationStatus`, `StrategyHealth`, `StrategyVersion`, `ResearchRun`, `DataQuality`, `Alert`, `FeedbackPipeline`, `SearchResultPage` and `AskAnswer` are not implemented, and their screens remain placeholders |
| **the aggregate `ExecutionQuality` surface** | Area 9 aggregates every fill in a window across every trade. C6 carries **one trade's** record, embedded on its detail; the `/execution/quality` screen remains a placeholder |
| **a risk ENGINE** | **still does not exist, and none is authorized.** What C6 carries is the *record* — an immutable repository-owned `RiskDecision` for each candidate the book declares one for, joined onto the trade under §4.3's `AUTHORIZED_READ`. It says what size was assigned, against which reference and invalidation prices, under which policy version, and reconciles to the cent with the retained entry-stage record; a **declined** decision assigns nothing and names why. Nothing here computes a size, applies a policy, permits an exposure or authorizes an order, and a trade whose sizing nobody recorded still reports `RISK_ENGINE_DECISION` as a gap |
| **immutable audit events** | the Audit Trail is a separate screen and a separate read model, and neither exists. `audit_refs` is carried, empty, and states a total of zero |
| **rolling series and capacity** | no rolling-window series and no capacity figure is derived. Trailing performance is **five separate reads over five windows**, each with its own population. **The two halves are blocked differently and are recorded separately**: a rolling-window series over the synthetic book needs no provider and is outstanding **implementation**; a **capacity** figure needs a liquidity and market-impact model over qualified provider data, and **G1 is OPEN**. Both are assigned to the **C5 completion follow-up** below, which is not authorized to run |
| **real benchmark price history** | the holding-period benchmark C6 added is an obviously synthetic index this repository owns. **Real** SPY, QQQ and IWM price history resolves to nothing, because **no provider has been selected and G1 is OPEN**. That blocks the *real* series and **not** the comparison itself: a portfolio-level comparison against a repository-owned synthetic index is buildable today on exactly the terms Trade Detail already demonstrates, and it is outstanding **implementation** assigned to the **C5 completion follow-up** rather than blocked on qualification |
| **cursor pagination** | the page contract carries its size, its total, its truncation flag, its sort key and its tiebreak. It carries **no cursor**: a cursor is meaningful only against a transport that can continue a page, and this local read client returns one page and continues none |
| **`PerformanceSeries` classification** | §4.5 classifies a real one `PRIVATE_OPERATIONAL`, which the `PUBLIC_EDGE` boundary **refuses**. What this application can show is a repository-owned synthetic demonstration, labelled `PUBLIC_SAFE` and `SYNTHETIC` because that is what it is. A real recorded series would be refused here rather than relabelled to fit the host |
| **`source_refs`** | carried, and empty on every response. The fixture adapter references no source fact, and states a total of zero rather than implying one |
| **`QualificationStatus` sources** | still a tracked `{path, commit}` rather than a §4.2 `Ref`: the reference resolves to a file in this public repository, which a `Ref` could not express |

**No claim is made that the catalogue is complete.** The remaining read models, payload fields
and metrics arrive with the cycles that produce them.

---

## Implemented in C6

| Route | Area | State |
|---|---|---|
| `/signals/funnel` | 6 | **implemented** — the four stages with the subject each counts, the eight Brain states as a closed set with their reason distributions, the downstream axis beside them carrying no count, the conversions with both counts and both subjects, a per-module funnel, and the candidate ledger with search and a state filter |
| `/signals/candidates/[candidateId]` | 7 | **implemented** — the decision and its thesis, deterministic factor evidence, the ranking context, the risk, event, liquidity and short context, AI research and challenger evidence with per-reference provenance, contradictions, the evidence the decision did not have, and the lineage |
| `/signals/missed` | 8 | **implemented** — recurring causes, taken-versus-missed comparisons including one that is **refused**, the two rates, and one row per recorded miss with a keyboard-reachable detail carrying the registered window, the counterfactual, its assumptions and the observed follow-up path |
| `/portfolio/trades/[tradeId]` | 36 | **completed** — C5's identity, economics, risk records and price marks, plus the orders, fills, protective-order events, corrections, reconciliation, per-fill execution quality, attribution and holding-period benchmark C6 adds |

### The C5 coverage questions, answered

C5 recorded four omissions. **Each is dispositioned here rather than quietly carried forward**,
and two of them remain open.

| C5 omission | C6 disposition |
|---|---|
| **the complete `TradeLifecycle`** — order and fill mechanics, protective-order events, reconciliation and corrections | **implemented and demonstrated.** All four are carried, for the six trades whose execution evidence a fixture records. The other one hundred and ninety-four name each kind as absent, because a ledger row does not say how many fills it took |
| **finalized attribution** | **implemented and demonstrated.** A declared decomposition whose five components sum to the trade's outcome exactly, labelled `PROVISIONAL` or `FINAL`. One trade in the book carries **no** attribution at all, and says so |
| **slippage and execution cost** | **implemented and demonstrated, for one trade at a time.** Each fill against a named reference price with its own timestamp and side convention. The **aggregate** figure reports `INSUFFICIENT_OBSERVATIONS` against its declared twenty-fill minimum, which is the §12.3 rule working rather than a gap |
| **rolling series and capacity** | **required and still outstanding.** Area 2 names rolling returns and Area 4 names rolling expectancy, drawdown and tail losses; neither is derived. **C6 did not attempt it**: it is a portfolio and strategy-performance concern rather than a signals or trade-lifecycle one, and widening this cycle into a portfolio-dashboard rebuild is exactly what its scope excludes. **It remains an open C5-assigned requirement**, and no cycle currently owns it |

**The benchmark question is split, and only half of it was C6's.** A **holding-period benchmark on
Trade Detail** is Area 36.2's own requirement and is **implemented and demonstrated**: one
synthetic index, sliced to exactly the trade's entry and last session, stating `PRICE_RETURN`
because the index and the demonstration securities both pay no dividend. The **portfolio-level
comparison** in Area 2 is a different requirement and was not C6's, so it remains outstanding.

**What blocks it is narrower than an earlier revision of this file claimed.** That revision said the
portfolio comparison "needs a qualified market-data provider", which is true of **real SPY, QQQ and
IWM price history** and is not true of the comparison. A **synthetic** portfolio-level benchmark
demonstration needs no provider at all — Trade Detail already builds one over a repository-owned
index — so the requirement is **outstanding implementation**, not work gated on G1. The two are now
recorded apart: the synthetic demonstration is assigned to the **C5 completion follow-up**, and only
the real vendor series waits on provider selection.

### The C5 completion follow-up — named, owned and not authorized

**An earlier revision recorded rolling series and capacity as outstanding with "no cycle currently
owns it".** An unowned requirement is one nobody is accountable for, so the residue is given a name
here: the **C5 completion follow-up**, a bounded later cycle carrying exactly the C5-assigned
requirements C6 did not close.

| Carried by the C5 completion follow-up | Why it is outstanding |
|---|---|
| rolling-window return, expectancy, drawdown and tail-loss series | **implementation.** Derivable over the synthetic book with no provider |
| portfolio-level benchmark comparison, synthetic index | **implementation.** Not blocked on G1 — the mechanism exists on Trade Detail |
| capacity, liquidity and market-impact | **blocked.** Needs qualified provider data, and **G1 is OPEN** |
| real SPY, QQQ and IWM price history | **blocked.** Needs a selected provider, and **none is selected** |

**Naming a follow-up is not completing it, and not authorization to start it.** No part of the
table above is implemented, none of it is authorized, and this review implemented none of it: a
portfolio-dashboard rebuild is explicitly outside C6's scope. It is recorded so the requirement has
an owner rather than disappearing between two cycles.

### The synthetic book, extended

The C5 book is unchanged in shape and gained exactly what C6 needed to demonstrate its cases.

| | |
|---|---|
| **one more featured trade** | a CLOSED long reduced twice and then closed by its remaining balance — the case Area 36.4 is most explicit about, and the one no C5 row could show. `GENERATED_TRADES` dropped by one in exchange, so the ledger population is unchanged at exactly its declared page size and the generated ordinals below it are untouched |
| **declared execution evidence for six trades** | orders, fills, protective-order events, reconciliation, corrections and attribution, **written down rather than derived**. A multi-fill order's quantity-weighted price must equal the price the ledger recorded, and the builder **refuses** a declaration where it does not |
| **sixteen journaled candidate decisions** | every one of the eight Brain states is populated, so the funnel renders a closed set rather than the interesting half of one. Six became the six trades with execution evidence; ten record a cause for not being entered |
| **one benchmark index** | a single series over the whole retained extent that every trade's window is a **slice** of — not a path generated per trade, which would measure two trades in the same month against two different markets |

**The cases the fixture exists to demonstrate**, each on a named row:

```text
every Brain state                     sixteen candidates across all eight
ready, then declined downstream       demo-candidate-0006, cause DOWNSTREAM_RISK_DECISION_DECLINED
watchlist expiry                      demo-candidate-0007
decision delay                        demo-candidate-0016, 9,180 seconds
data / event / borrow / contradiction demo-candidate-0009 / -0010 / -0011 / -0012
AI evidence unavailable               demo-candidate-0013
AI evidence that removed a candidate  demo-candidate-0012
AI evidence past its contract         demo-candidate-0015, STALE
incomplete follow-up path             demo-candidate-0009, PARTIAL
long completed lifecycle              demo-trade-sol-0006
short completed lifecycle             the first closed short in the deterministic book
pyramid with retained per-stage risk  demo-trade-nvl-0002
fully filled order, partial exit      demo-trade-cir-0003
partially filled order                demo-trade-arb-0001, two fills
several partial exits, then close     demo-trade-sol-0006, three exits
an appended correction                demo-trade-sol-0006, a protective level restated
a late observation                    demo-trade-arb-0001, a fill observed three hours late
a missing stage                       demo-trade-nvl-0002, never reconciled and never attributed
no execution evidence at all          every other trade in the book
```

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

### Corrected in independent review

Six defects were found by reading the fixture against `read-model-contracts.md` §4.5, §12.4
and `cockpit-v1-specification.md` §5, reproduced on the reviewed head, and corrected here. The
three below are the trade-semantics ones; three more follow the table. Each has a regression that
fails for the intended reason. **Two carry an in-test negative control** asserting that the
retired rule gives a **different** answer, so the assertion distinguishes the two rules rather
than passing under both; a third was verified by temporarily reintroducing the defect, observing
the regression fail for its intended reason, and restoring the tree — that check was run, and it
is not committed.

| | |
|---|---|
| **a later add restated the original entry** | `shares_at_entry` summed every stage and `entry_price` reported the blended basis, so the pyramid's ledger row read **100 shares at 63.88** for an entry of **60 at 62.40** — a size and a price the trade never entered at. §4.5 calls this field "filled at entry" and calls `PositionSnapshot.entry_price` a "position-weighted basis" in the same document, so they are two questions. The entry facts are now the entry stage's, what the trade went on to hold is carried by the additive `shares_acquired` and `current_basis`, and **the admission rule that forced the conflation was corrected rather than the fact**: the status rules bound the open quantity by what the trade FILLED, so a pyramid holding more than it entered with is admitted, and a trade holding more than it ever filled is still refused |
| **one blended record stood in for every stage's** | the single retained `InitialPlannedRisk` carried the **summed** risk of both stages against the **combined** basis, while dating itself at the entry and pointing at the entry's invalidation level — a record describing no stage that ever existed, and the number the trade detail printed under "Recorded at entry". §12.4 requires each add to keep "its own record, at its own reference price and its own as-of" with "the trade's original record retained unchanged", and makes the **sum** the trade-level R denominator, which is a third thing. All three are now separate: the original record, each add's own, and `r_denominator` — **served rather than derived**, because a screen computing it would be a screen computing a metric. Every contributing policy version is printed with its own record, and the book's add now names a later one so that case is visible rather than theoretical. **The R denominator itself is unchanged** — it was already the sum, and §12.4 says it must be |
| **a historical valuation used a future add** | MFE and MAE were measured across the **whole** path at the final quantity and the final basis, so the thirty sessions during which the pyramid held 60 shares at 62.40 were valued as 100 at 63.88. On this trade that reported **29.00 / −342.00** where the position could only have reached **106.20 / −314.00**, and `capture_ratio` divided by the wrong MFE. Every session is now valued with the quantity and basis it actually carried, exits included |

A fourth was an internal contradiction inside the book itself: `stop_outcome` returned
**`STOP_TRAILED_THEN_TRIGGERED` for every non-losing outcome**, so a trade whose recorded
`exit_reason` was **`PLANNED_TARGET_REACHED`** also claimed its trailed stop had triggered, and so
did the exact break-even, whose reason is `TIME_STOP_REACHED`. Two fields describing one event
disagreed on roughly a fifth of the closed ledger. They now share the thresholds of the reason
that produces them, and a regression walks every closed trade asserting that a reason which says
the stop did not fire is never paired with an outcome that says it did — checking first that both
contradicting cases actually occur in the book, so the assertion is exercised rather than vacuous.

Correcting the second one exposed a **sixth**, in the surface that matters most. The risk
dashboard lists the retained entry-time records of open exposure, and it listed **one per trade**
— which, once each record described its own stage truthfully, reported the pyramid's planned risk
as **186.00** where its retained records total **398.00**. Understating planned risk on a risk
dashboard is the wrong direction to be wrong in, so it now lists **one entry per retained stage
record**, stage-labelled so two records sharing a trade reference stay apart, with a regression
asserting the listed records total the trade's own retained sum.

A fifth was corrected in the lifecycle: an exit reported **`ORDER_PARTIALLY_FILLED`** whenever
its quantity was smaller than the trade's, inferring an **order's** fulfilment from a **position**
comparison — while `absent_kinds` declared `INDIVIDUAL_FILL` as `PRODUCER_NOT_IMPLEMENTED` in the
same payload. A partial exit is routinely executed by an order that filled completely. This book
records completed stage and exit fills and nothing else, so every event reports the fill state it
actually has and per-order evidence stays explicitly unavailable. The same comparison also decided
**partial versus final**, which is a question about what is **left**: an exit closing the remainder
after earlier partial exits is smaller than the entry and is still the final one. That defect was
**latent** — no shipped row exercises it, because every generated trade exits in one go — so its
regression is a constructed trade, and the report says so rather than claiming a visible fix.

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
| a **pyramid add** | `demo-trade-nvl-0002` — entered 60 at 62.40, added 40 at 66.10, and **the entry facts are not restated**: the ledger row reports 60 at entry, 100 acquired, 100 open, and a current basis of 63.88 that is shown as a basis and never as an entry price. One row in the ledger |
| **two contributing risk-policy versions** | the same pyramid — each stage keeps its own retained record at its own reference price and as-of, they name **different** policy versions, and §12.4's R denominator is the **sum** of the two, carried explicitly rather than derived on the screen |
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

## What C6 does not contain

Everything in the C5 and C4 lists below, unchanged, and:

```text
no Brain runtime           no scanner or factor matrix   no decision compiler
no AI agent or model call  no risk engine                no order router
no aggregate execution     no audit trail                no rolling series
no capacity model          no real benchmark price       no provider data
no sizing computation      no policy application         no exposure permission
```

**No model is called from anywhere in this application.** The AI evidence records carry model,
prompt and schema versions because §14.3 requires them **on evidence**; the versions are fictional
strings identifying nothing, and no SDK, endpoint or key exists in the tree.

**AI may remove a candidate and may never restore one**, and the contract refuses a payload
claiming otherwise rather than leaving it to a screen. **No counterfactual becomes an amount of
money**, because that needs a sizing basis somebody approved and none exists. **No false-negative
rate is reported**, because a ledger of detected candidates contains no undetected one.

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

**Implemented by this cycle, and pending independent review and merge.** Merging C6 authorizes
no further cycle: **specification, implementation, deployment and execution stay separate
gates**, and C7 is a separate written authorization that has not been given.

```text
C3 application foundation                         MERGED (PR #74)
C4 executive overview and governance              MERGED (PR #75)
C5 portfolio, strategy, exposure and trades       MERGED (PR #76)
C6 signals, explainability, trade lifecycle       IMPLEMENTED HERE / PENDING REVIEW
trade detail                                      COMPLETE LIFECYCLE
strategy health                                   RECORDED STATE ONLY -- C7 owns area 5
aggregate execution quality (area 9)              NOT IMPLEMENTED -- later cycle
audit trail (area 26)                             NOT IMPLEMENTED -- later cycle
rolling series and capacity                       OUTSTANDING -- owned by the C5 completion
                                                  follow-up; the series is implementation,
                                                  capacity is blocked on G1
portfolio benchmark, synthetic index               OUTSTANDING IMPLEMENTATION -- owned by the
                                                  C5 completion follow-up, NOT blocked on G1
real SPY / QQQ / IWM price history                 BLOCKED -- needs a selected provider
C5 completion follow-up                            NAMED / NOT AUTHORIZED / NOT STARTED
full Cockpit V1                                   NOT COMPLETE -- 14 of 36 addressed and
                                                  finished; area 36 is now complete
Strategy Brain runtime                            NOT IMPLEMENTED / NOT AUTHORIZED
scanner, factor matrix, decision compiler         NOT IMPLEMENTED / NOT AUTHORIZED
AI research and challenger agents                 NOT IMPLEMENTED / NOT AUTHORIZED
model, SDK or endpoint calls of any kind          NONE
risk engine and order router                      NOT IMPLEMENTED / NOT AUTHORIZED
production read API, projections, metric engine   NOT IMPLEMENTED / NOT AUTHORIZED
feedback and self-maturation automation           NOT IMPLEMENTED / NOT AUTHORIZED
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

**A synthetic evidence record is fixture data, and never evidence that a system ran.** The
candidate decisions, orders, fills, protective-order events, reconciliations and attributions this
cycle renders were typed into a repository-owned fixture. **No Brain has ever decided anything, no
order has ever been sent, no fill has ever occurred, no model has ever been called and no
benchmark price has ever been requested.**

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

### C6 — three defects found by independent review, and corrected

Each was reproduced on the author's head before it was corrected, and each correction carries a
**negative control**: the retired rule was temporarily reintroduced and the new regression was
confirmed to fail on it, so the tests distinguish the two rules rather than agreeing with whatever
the fixture produces.

| | |
|---|---|
| **a trade reference was read as order evidence** | `downstreamStageOf` returned `ORDER_FILLED` for any candidate carrying a `tradeId`. **A trade link says a position was opened; it says nothing about whether any order was submitted, acknowledged, partially filled or filled.** The stage is now read from the candidate's declared risk decision and from the execution record's own fills, and a new candidate makes the gap visible: it was approved, a position was opened, **nobody recorded an order**, and its stage stops at `RISK_APPROVED`. Under the retired rule that same candidate reported a fill this book does not contain |
| **the funnel refused every downstream count** | the refinement rejected any value-bearing downstream availability, so a recorded count was **unexpressible** — a fixture's emptiness had become a permanent property of the contract. §4.5 makes the downstream `count` a **required** field, and Area 6's own *V1 availability* reads "`SYNTHETIC` demonstration; real candidates `NOT_IMPLEMENTED`" — the same terms the Brain axis beside it was already demonstrated on. The axis now carries counts on a **stated basis** (`EVER_REACHED`) over a **stated population**, and the refinement refuses the things that make a count uncheckable instead. The stated rationale for the old rule — that a count "would be the first step of merging" the axes — does not follow: the two remain separate arrays over separate closed vocabularies, and neither acquires the other's members |
| **two screens contradicted each other about the risk decision** | `/risk` listed three decisions with an outcome of `RISK_APPROVED_AT_RECORDED_SIZE`, while Trade Detail declared `RISK_ENGINE_DECISION` **`NOT_IMPLEMENTED` — "the producing subsystem does not exist"** — for those same trades. Both statements cannot hold over one fixture. The book now declares a `RiskDecision` per candidate that has one, `/risk` indexes those records rather than synthesising three from the first open trades, and the gap is reported **only** where no decision was recorded |

**The risk decision is a record, not an engine.** Nothing added here computes a size, applies a
policy, permits an exposure or authorizes an order. The records are immutable repository-owned
declarations, and the builder **refuses** a declaration whose arithmetic does not reconcile with the
retained entry-stage record — `shares × |reference − invalidation|`, which §4.4 defines the retained
record by. A declared number nobody checks is how a fixture starts teaching a reader something
untrue.

**The boundary held.** The sizing lives on the **trade**, joined by reference under §4.3's
`AUTHORIZED_READ`. `CandidateIntent` acquired no field of it, `CandidateDetail` carries the
reference alone, and a test asserts that no `SHARES` or `USD` quantity appears anywhere in a
candidate payload. A **declined** decision assigns nothing — no shares, no risk, no retained record
to point at — and names why.

**What this correction does not unlock.** The money counterfactual on Missed Opportunities stays
refused. A dollar counterfactual needs a permitted sizing basis, and a missed candidate was never
sized: the one decision that touches a miss **declined** it, and a decline assigns no size. The
field remains structurally present and never served.

### C6 — the baseline timeout, investigated

The C6 author reported an isolated baseline run of **265 passed with one navigation timeout**,
against a historical baseline of **266 passed**. The review re-ran the **whole baseline suite on
`main` alone**, in its own clean worktree, with no concurrent mutation and no competing heavyweight
test run:

```text
baseline tree                   main @ 4bdc0da54ad14126891870e41ee69ab8726c96a3
npm run test:e2e                266 passed (7.8m), exit 0
```

**The first observed result of that run is the one recorded**, and it did not reproduce the
timeout. **A successful rerun does not retroactively make the author's original run a pass** — that
run timed out, and it is recorded as having timed out.

**No product defect was identified, and none was corrected.** Two of the three known runs of this
same baseline tree passed in full, which is what a load- or timing-sensitive failure looks like and
is not what a product defect looks like. The suite runs a **Next.js dev server**, which compiles
routes on first request, so a first navigation under load is the plausible pressure point — that is
a hypothesis about the environment and **not** an established cause, and nothing here claims one.

**No timeout was increased and no retry was added** to obtain a green run. The Playwright
configuration is unchanged: one worker, a 60-second test timeout, and no retries.

### C6 — validation on the reviewed and corrected head

Run on Node 22.21.0 and npm 10.9.4, from the committed lockfile, in a clean isolated worktree:

```text
npm ci                          clean install from the committed lockfile
npx eslint .                    clean
npx next build                  succeeds -- no API route
npx tsc --noEmit                clean, strict (run after a build; route types are generated)
npx vitest run                  372 passed   (C6 author head was 363; C5 baseline was 261)
npx playwright test             398 passed, 0 skipped, across 1440x900, 1024x768 and 390x844
```

And the repository-wide gates, from the same tree:

```text
pytest -q                       7074 passed          (unchanged from the baseline)
ruff check .                    all checks passed
ruff format --check .           263 files already formatted
mypy                            no issues in 181 source files
scripts/phase3_docs_audit.py    4575 checks, AUDIT PASSED
scripts/test_integrity_audit.py 85 modules, AUDIT PASSED
git diff --check                clean
```

**Nine browser failures were found and fixed during the review, and they were the review's own.**
The `RiskDecisionRecord` panel was first written with `<dl>` children that were neither `<dt>` nor
`<dd>`, which `axe-core` correctly reported as `definition-list` on every viewport; and a C5
negative control asserted `Risk engine decision` as a gap on a trade that now has a recorded
decision. **The accessibility defect was corrected in the markup, not waived**, and the C5
assertion was repointed rather than deleted — it now requires the gap on a trade with **no**
decision and requires its **absence** on a trade with one, so the pair distinguishes the two cases
instead of accepting either.

**An automated `axe-core` pass is not an accessibility audit**, and none was performed: no screen
reader was run, and no performance target was measured. Browser traffic was checked and reaches
**no origin other than the local dev server**, with **no console error and no hydration mismatch**.

**Local validation is local.** These were run on a workstation. **No CI service ran them**, and no
CI status check exists for this application.

### C6 — the browser evidence, and what it does not claim

The C6 review captures live in **`apps/cockpit/screenshots-c6/`**, at all three registered
viewports, stamped with the exact commit and working-tree state they were taken at. They are
**review evidence, not a visual-regression baseline**, and the C3, C4 and C5 captures are
untouched.

**No screen-reader claim and no performance claim is made.** The accessibility evidence is an
automated `axe-core` scan at WCAG 2.1 A and AA over every C6 route in Operator mode, plus a
keyboard test that opens a missed-opportunity detail with the keyboard and asserts that focus
returns to the control that opened it. **An automated scan is not an audit**, and no screen reader
was run.

### Dependencies added by C6

**None.** C6 adds no runtime dependency, no development dependency and no lockfile change. The
price view is the same TradingView Lightweight Charts surface C5 introduced, still imported inside
one effect in one component.

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
