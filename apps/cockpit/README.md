# KalpaMani Cockpit — C3 application foundation

The first runnable Cockpit application, built under
[ADR-0027](../../docs/decisions/ADR-0027-cockpit-and-feedback-architecture-and-governance.md)
and the corrected contracts of
[ADR-0028](../../docs/decisions/ADR-0028-cockpit-contract-completion-and-boundary-corrections.md)
and
[ADR-0029](../../docs/decisions/ADR-0029-valid-zero-values-and-cache-freshness-deadlines.md).

**This is the C3 foundation. It is not the Cockpit.** It is design system, shell, navigation,
contract layer and two substantive screens, running on a local fixture adapter.

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

`npm run test:e2e` starts its own dev server on port 3100 and writes review screenshots to
`screenshots/` for the desktop (1440×900), tablet (1024×768) and mobile (390×844) viewports.
Both directories are git-ignored.

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

---

## The contract subset, exactly

**C3 transcribes a SUBSET of `read-model-contracts.md`, and the omissions are stated rather
than implied.** Four read models are implemented — `ExecutiveOverview`, `AttentionItem`,
`WhatChangedEntry` and `QualificationStatus` — and within them:

| | |
|---|---|
| **payload fields not carried** | `ExecutiveOverview.regime_ref`, `last_decision`, `last_scout_run` and the `what_changed` and `attention` `RefList`s. Each needs a producing subsystem that does not exist, and none is rendered anywhere |
| **`RefList.total` is not carried** | the §4.2 shape states a `total: CountValue`; C3 carries `items`, `cardinality` and `truncated`. No C3 list is truncated, and `truncated: false` is asserted on every one |
| **`source_ref` is a tracked source** | `QualificationStatus` facts carry the exact tracked `path` and 40-character `commit` they were read at, rather than a §4.2 `Ref`. The reference resolves to a file in this public repository, which a `Ref` could not express |
| **envelope fields not carried** | `watermark` and `pins`. Neither has a producer, and no view reads either |
| **metrics** | the closed `C3_METRIC_DICTIONARY` in `src/contracts/values.ts`. Every metric this application renders is registered there with its unit and its value shape, and **an unregistered `metric_id` is refused at admission** |

**No claim is made that the catalogue is complete.** The full catalogue is larger, and the
remaining read models, payload fields and metrics arrive with the cycles that produce them.

---

## Implemented in C3

| Route | State |
|---|---|
| `/` | **implemented** — the composed Executive and Operator foundation landing page |
| `/governance/qualification` | **implemented** — the source-linked readiness summary |
| `/governance/controls` | **inert** — a static explanation of a future control plane |
| `/foundation/states` | **implemented** — the contract and state reference, a local review surface |
| every other registered route | a shared, clearly labelled **not yet implemented** page naming the area, its purpose, its producer or dependency and its intended cycle |

**A placeholder route does not implement its product area**, and this foundation makes no
claim that it does. All 36 product areas remain in V1 scope, and the C4–C10 sequencing of the
traceability matrix is unchanged.

Trade History, Trade Detail, Execution History and the Audit Trail stay reserved as distinct
destinations; C3 implements none of their workflows.

---

## What this foundation does not contain

```text
no production read API        no projection runtime      no metric engine
no FastAPI service            no database                no migration
no scheduler                  no container               no deployment
no chart library              no LLM SDK and no model call
no route handler              no server action           no API route
no control handler            no mutation of any kind
no provider, broker, AWS, GitHub, LLM or analytics request -- at runtime or at build time
```

**Ask KalpaMani is not implemented and is not exposed.** It appears in no route, no
navigation entry and no palette command, so there is no surface that could accept a
question. **No model is called, no model SDK is installed, and no answer is simulated.**

---

## Governance

**Implemented by this cycle, and pending independent review and merge.** Merging this
foundation authorizes no further cycle.

```text
Cockpit frontend foundation      IMPLEMENTED HERE / PENDING REVIEW
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

### Corrections made under independent review

Four defects were found by independent review of this branch and corrected on it. Each is
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

Reproduced on the corrected head, on Node 22.21.0 and npm 10.9.4:

```text
npm ci --no-audit --no-fund     clean install from the committed lockfile
npx eslint .                    clean
npx next build                  succeeds -- 31 static routes, no API route
npx tsc --noEmit                clean (run after a build; route types are generated)
npx vitest run                  84 passed
npx playwright test             87 passed across 1440x900, 1024x768 and 390x844
```

**Local validation is local.** These were run on a workstation, not by a CI service, and no
CI status check exists for this application.

Third-party attribution is in [NOTICE.md](NOTICE.md).
