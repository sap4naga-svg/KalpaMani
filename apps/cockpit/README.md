# KalpaMani Cockpit — C4 Executive Overview and governance

The Executive Overview, Attention Required, project and qualification governance, and
environment and deployment maturity — built on the merged C3 application foundation, under
[ADR-0027](../../docs/decisions/ADR-0027-cockpit-and-feedback-architecture-and-governance.md)
and the corrected contracts of
[ADR-0028](../../docs/decisions/ADR-0028-cockpit-contract-completion-and-boundary-corrections.md)
and
[ADR-0029](../../docs/decisions/ADR-0029-valid-zero-values-and-cache-freshness-deadlines.md).

**This is C4. It is not the Cockpit.** C3 delivered the design system, shell, navigation and
contract layer with two substantive screens; C4 adds the Executive Overview, a performance
overview, the ranked Attention Required list, What Changed, and two governance screens — still
running on a **local fixture adapter**, and still with no production read API, projection or
metric engine behind it.

**Four of the thirty-six product areas are implemented.** Areas 1, 24, 25 and 28 — the C4 row of
the traceability matrix. The other thirty-two remain registered, reachable placeholders, and the
C5–C10 sequencing is unchanged.

---

## What is real, and what is not

| | |
|---|---|
| **real** | the governance facts on `/governance/qualification`, and the readiness figures on the landing page. Provenance `REPOSITORY_TRACKED`, transcribed from tracked repository authority, each carrying its exact source path, its source commit and its recorded as-of date |
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
```

Both are git-ignored: they are **review evidence, not a visual-regression baseline**. Visual
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
```

---

## Organization

```text
src/contracts/     the closed vocabularies, the 4.1.1 validity matrix, the freshness
                   deadline arithmetic, the envelope, the admission gate and the C3
                   payload contracts -- transcribed from read-model-contracts.md
src/data/client/   the typed READ-CLIENT BOUNDARY, the query keys and the query hooks.
                   default-client.ts is the ONE composition point that names the adapter
src/data/fixtures/ the deterministic fixture adapter, the synthetic scenario and the
                   tracked governance facts
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
 &period=1M|3M|6M|1Y|ALL&changes=auto|valid|none|no-baseline|degraded
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

### Still not carried

| | |
|---|---|
| **read models** | the rest of the catalogue. `PerformanceSummary`, `TradeDetail`, `ExecutionQuality`, `StrategyHealth`, `SignalFunnel`, `DataQuality`, `Alert`, `FeedbackPipeline`, `SearchResultPage` and `AskAnswer` are not implemented, and their screens remain placeholders |
| **`PerformanceSeries` classification** | §4.5 classifies a real one `PRIVATE_OPERATIONAL`, which the `PUBLIC_EDGE` boundary **refuses**. What this application can show is a repository-owned synthetic demonstration, labelled `PUBLIC_SAFE` and `SYNTHETIC` because that is what it is. A real recorded series would be refused here rather than relabelled to fit the host |
| **`source_refs`** | carried, and empty on every response. The fixture adapter references no source fact, and states a total of zero rather than implying one |
| **`QualificationStatus` sources** | still a tracked `{path, commit}` rather than a §4.2 `Ref`: the reference resolves to a file in this public repository, which a `Ref` could not express |

**No claim is made that the catalogue is complete.** The remaining read models, payload fields
and metrics arrive with the cycles that produce them.

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

**Implemented by this cycle, and pending independent review and merge.** Merging C4 authorizes
no further cycle: **specification, implementation, deployment and execution stay separate
gates**, and C5 is a separate written authorization that has not been given.

```text
C3 application foundation                         MERGED (PR #74)
C4 executive overview and governance              IMPLEMENTED HERE / PENDING REVIEW
full Cockpit V1                                   NOT COMPLETE -- 4 of 36 areas implemented
production read API, projections, metric engine   NOT IMPLEMENTED / NOT AUTHORIZED
feedback and self-maturation automation           NOT IMPLEMENTED / NOT AUTHORIZED
Strategy Brain runtime                            NOT IMPLEMENTED / NOT AUTHORIZED
deployment and real-source integration            NOT AUTHORIZED
Run A retry / Run B / combined assessment         NOT AUTHORIZED / NOT RUN
P1-P9                                             UNEVALUATED
data correctness and quality                      NOT ESTABLISHED
G1 / G2                                           OPEN / OPEN
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

**Local validation is local.** These were run on a workstation, not by a CI service, and no
CI status check exists for this application.

**What was checked by hand, and what was not.** Every screen was inspected at 1440×900,
1024×768 and 390×844 in the executive, operator, project and demo combinations; keyboard
navigation, focus restoration and the chart's table alternative were exercised directly; and
`@axe-core/playwright` reports no serious or critical violation on the substantive routes.
**An automated pass is not an accessible interface**: no screen-reader pass was performed, so
nothing here claims one. **No performance target was measured** — the specification sets those
as targets for a later cycle, and this cycle measures nothing and claims nothing.

Third-party attribution is in [NOTICE.md](NOTICE.md).
