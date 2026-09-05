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
  advances **no maturity and no authority**; unpopulated scopes show explicit unavailable
  states, and a scope change is a different cache key, so one environment's values are never
  flashed under another's badge.
- **scenario** — `project` is the honest default; `demo` is the labelled synthetic scenario.
  **Synthetic is provenance, not a runtime environment.**

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

**Ask KalpaMani is exposed as an unavailable future capability.** No model is called and no
answer is simulated.

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

Third-party attribution is in [NOTICE.md](NOTICE.md).
