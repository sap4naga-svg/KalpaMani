# ADR-0027 — Cockpit and Feedback architecture and governance

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0027 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and
it is not to be rewritten as though this decision had authority before it was accepted. On merge,
this ADR becomes **ACCEPTED / IN FORCE** as **architecture, contracts, governance and future
implementation boundaries** — and nothing else.

**The acceptance event is exact:** the independent review and merge of **PR #71** into `main`. No
merge SHA and no merge timestamp is predicted here; those are repository state, recorded after the
fact if they are recorded at all.

**Date:** 2026-09-05
**Supersedes:** nothing
**Superseded by:** —
**Relates to:** [ADR-0001](ADR-0001-system-foundation.md),
[ADR-0002](ADR-0002-broker-adapter-and-brokerage-boundary.md),
[ADR-0003](ADR-0003-broker-side-order-controls-are-not-safety-invariants.md),
[ADR-0004](ADR-0004-deterministic-order-identity-idempotency-and-execution-lifecycle.md),
[ADR-0005](ADR-0005-point-in-time-data-architecture.md),
[ADR-0006](ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md),
[ADR-0007](ADR-0007-cloud-first-research-data-plane.md),
[ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md),
[ADR-0026](ADR-0026-strategy-brain-architecture-and-governance.md)

**Nothing was run to produce this decision.** No AWS, STS, SSO, IAM, Secrets Manager or S3 call; no
Terraform command of any kind; no Terraform state, backend configuration, `.tfvars` or `.terraform/`
read; no `.runtime/` inspection; no provider request; no credential access; no Run A retry, Run B or
combined assessment; no P1–P9 execution; no backtest; and no broker, LEAN or IBKR activity. **No
Blueprint PDF was opened.** No dependency was installed, no package manifest was changed, and no
application was scaffolded. This decision is authored from tracked repository authority alone.

**No alpha is claimed anywhere in this decision.**

---

## 1. Context

KalpaMani has an architecture, a governed data plane, a specified Brain and a long record of
separately gated decisions. What it has never had is **a way for a human to see the system**.

Every fact this repository holds today reaches its owner through one of three surfaces: a merged
Markdown status document, a pull-request body, or a terminal transcript. That is adequate for a
repository under construction and inadequate for an autonomous trading platform. When a strategy
degrades, when a data feed goes stale, when a candidate is blocked, when a fill slips, when a
Challenger becomes ready — the person who governs the system has to be able to see it, in context,
without reading source code and without running anything.

**The Cockpit is that surface.** This decision establishes it as a first-class subsystem with its
own architecture, its own contracts and its own safety boundary, rather than as a reporting layer
someone bolts onto a finished platform.

**Why now, during provider qualification.** The dependency is stated rather than assumed: **P1–P9
UNEVALUATED**, **data correctness and quality NOT ESTABLISHED**, **G1 and G2 OPEN**, **no provider
selected**, **Run B NOT RUN / NOT AUTHORIZED** with an earliest approved target of 2026-09-12, and
the **combined assessment NOT RUN / NOT AUTHORIZED**. Specifying an observability surface requires
no provider data and creates no dependency on any. Building one against synthetic contracts requires
none either. **Feeding it real data does**, and that is why every real feed in this specification
stays behind the gate that owns it.

There is a second reason, and it is the one that matters more. **A system that cannot be observed
cannot be governed, and a system that learns without being observed cannot be governed at all.**
[ADR-0006](ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md) §C committed this project
to *self-maturing, not self-governing*, and
[ADR-0026](ADR-0026-strategy-brain-architecture-and-governance.md) turned that into contracts for
the Brain. Neither said how a human would *hold* that authority in practice — what they would read,
what evidence they would be shown, and what the machine would have prepared for them. This decision
specifies that loop, and it specifies it before any part of it can be built.

**Specification is its own gate, and it comes before implementation.** That is the discipline
ADR-0026 applied one step earlier, and this decision inherits it rather than restating a weaker
version.

---

## 2. Decision

**Adopt the Cockpit as a first-class KalpaMani subsystem, and adopt the following documents as its
authoritative repository specification.**

| Document | What it governs |
|---|---|
| [`docs/architecture/COCKPIT_FEEDBACK_EXTENSION.md`](../architecture/COCKPIT_FEEDBACK_EXTENSION.md) | the Blueprint V3.0 architecture extension — subsystem position, data flow, boundaries |
| [`docs/cockpit/cockpit-v1-specification.md`](../cockpit/cockpit-v1-specification.md) | the 36 Cockpit V1 product areas and their functional contracts |
| [`docs/cockpit/read-model-contracts.md`](../cockpit/read-model-contracts.md) | envelopes, read-model contracts, the endpoint catalog and the metric dictionary |
| [`docs/cockpit/feedback-self-maturation-specification.md`](../cockpit/feedback-self-maturation-specification.md) | the feedback loop, its stage contracts and its authority matrix |
| [`docs/cockpit/ui-ux-specification.md`](../cockpit/ui-ux-specification.md) | presentation, interaction and observable UI acceptance |
| [`docs/cockpit/traceability-matrix.md`](../cockpit/traceability-matrix.md) | all 36 areas traced to specification, presentation, owner, availability, gate, cycle and acceptance |

**These documents specify. They do not implement, and they authorize nothing.** No Cockpit
application, no Next.js project, no FastAPI service, no projection runtime, no metric engine, no
feedback automation, no database, no migration and no scheduler exists or is authorized because this
decision describes one. **A described architecture is not permission to build it** — the rule
[ADR-0006](ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md) §H already holds this
repository to.

**Acceptance authorizes no implementation and no execution.** Merging this decision opens the
specification gate and no other.

---

## 3. The Cockpit is observational in V1

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
approval records in V1.** A human approval recorded by clicking a button in a dashboard is an
approval whose authenticity rests on that dashboard's session handling; the authoritative approval
record stays with the separately governed decision path that already owns it.

**The Cockpit does not inherit authority from the systems it observes.** Deterministic risk logic
may eventually reduce exposure automatically under preapproved rules; that is a property of the risk
engine's own governance, and it grants the Cockpit nothing. **Do not grant the Cockpit
safety-reduction authority merely because a separately governed deterministic system may eventually
have it.**

**Future controls may be specified visually and remain inert.** The future human control plane is
specified so that its authentication, authorization, audit, idempotency and safety architecture can
be designed deliberately rather than improvised later. Every V1 representation of it is **inert**:
explicitly unavailable, with no executable handler and no control API route.

---

## 4. The read-model boundary

```text
KalpaMani subsystems
    -> immutable facts, events and versioned results
        -> dedicated projections and read models
            -> versioned read API
                -> Cockpit UI
```

**The Cockpit has no direct access to** the Sharadar or any other provider API · provider
credentials or AWS secrets · IBKR trading APIs or brokerage credentials · mutable Brain internals ·
private qualification artifacts.

**The boundary applies to the backend as well as the browser.** A read API that opens a provider
session or a broker connection on the interface's behalf is a provider or broker integration wearing
a dashboard's name. **An API proxy must not become a disguised provider or broker integration.**

**The existing ownership split is preserved exactly.**

| | |
|---|---|
| **Brain** | `CandidateIntent` only |
| **Portfolio / risk** | ownership permission, sizing, shares, risk constraints |
| **Execution** | order type, route, fills, protection, reconciliation |

**No sizing or execution field is added to `CandidateIntent` to simplify a screen.** Trade Detail
reconstructs a whole trade by joining separately owned downstream facts through **safe internal
references**, and the Brain contract is untouched by it. **The Brain never chooses final shares,
dollars, position size, broker order type, route, client order ID or broker order ID** — this
decision restates [ADR-0026](ADR-0026-strategy-brain-architecture-and-governance.md) §6 rather than
amending it.

**Downstream states are separately typed.** ADR-0026's Brain decision vocabulary is closed at
`READY_FOR_RISK_REVIEW`, `WATCHLIST`, `REJECTED`, `BLOCKED_DATA`, `BLOCKED_EVENT`, `BLOCKED_AI`,
`BLOCKED_CONTRADICTION` and `BLOCKED_BORROW`. **Risk approval, order and fill states are a separate
vocabulary owned by a separate layer**, and the funnel presents them as a separate axis. **The Brain
status enum is not extended with downstream states**, because one vocabulary spanning two authority
domains makes it impossible to tell from a status alone which layer produced it.

---

## 5. Environments, provenance and availability

**Five product maturity stages, and they are presentation.**

```text
RESEARCH   SHADOW   AUTOMATED_PAPER   MICRO_LIVE   SCALED_LIVE
Research / Shadow / Automated Paper / Micro-Live / Scaled Live
```

**They map onto existing vocabularies; they do not compete with them.** The runtime `Environment`
enum (`RESEARCH` / `PAPER` / `LIVE`) is unchanged, ADR-0026's strategy lifecycle values are
unchanged, and the mapping is explicit in
[`COCKPIT_FEEDBACK_EXTENSION.md`](../architecture/COCKPIT_FEEDBACK_EXTENSION.md). **`SHADOW` has no
order authority**, and **`AUTOMATED_PAPER` remains the first order-producing stage**, reachable only
by human approval.

**Five things are kept separate**, because collapsing any two of them produces a false statement on
a screen: deployment identity · trading and runtime environment · strategy maturity and
authorization · source provenance · data availability.

**SYNTHETIC/DEMO is provenance, not a live trading environment.** `RESEARCH` alone does not mean
data is synthetic, and a synthetic example is not a research result.

**Availability is a typed vocabulary, never an overloaded number.**

```text
AVAILABLE    NOT_YET_AVAILABLE    NOT_IMPLEMENTED    NOT_AUTHORIZED    UNEVALUATED
STALE        PARTIAL              ERROR             NOT_APPLICABLE
EMPTY_VERIFIED                    INSUFFICIENT_OBSERVATIONS
```

**A missing value is never converted to zero, healthy, passed or no incidents.** A zero that stands
in for an unknown reads downstream as a measurement, and every later check treats it as one — the
same defect ADR-0026 §4 blocks at the point-in-time gate.

**A historical success carries its as-of time.** A past identity preflight is not proof of current
authentication health.

**No silent cross-environment aggregation exists.** An explicit comparison keeps separately labelled
series and separately labelled results, and an all-environments search never implies a meaningful
combined result across backtest, shadow, paper and live copies of one trade.

---

## 6. The private-data and hosting boundary

**"Read model" and "derived" do not mean "safe to publish".** Existing restrictions on licensed
vendor data and reconstructable derivatives continue to govern read models, charts, exports, caches,
logs and Ask KalpaMani, exactly as `CLAUDE.md` §4.22 and
[ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md) already require.

| Classification | Where it may live |
|---|---|
| `PUBLIC_SAFE` | the public repository, a public demo, an externally hosted deployment |
| `PRIVATE_OPERATIONAL` | the approved private deployment boundary only |
| `LICENSED_DERIVED` | the approved private deployment boundary only |
| `UNCLASSIFIED` | nowhere — **it fails closed** |
| `CONTROL` | **refused at admission**; CONTROL publication remains **DEFERRED** |

**Public repository and demo assets are synthetic only.** Real private and licensed projections stay
inside their approved private boundary. **Any externally hosted output requires its applicable
classification and its own authorization**, and **a Vercel SSR, proxy or cache path must not silently
receive a licensed payload**.

**Immutable audit history and deletable licensed data are reconciled rather than traded off.** A
vendor licence may require destroying every copy on short notice (`CLAUDE.md` §4.23), and an
immutable audit record that embedded vendor rows would make that impossible. **Licensed content is
never copied into a permanent immutable audit payload**; audit events carry classified references,
and deletion is expressed through authorized tombstone semantics that preserve governance evidence
without retaining forbidden vendor data.

---

## 7. The feedback and self-maturation loop

```text
Journal -> Attribution -> Health / Drift -> Research Queue -> Registered Hypothesis
    -> Immutable Challenger -> Backtest / Locked OOS / Stress -> Shadow
        -> Governance Packet -> Human-Authorized Release
```

**Self-maturing is not self-governing.** Within separately approved bounds, future automation may
monitor and diagnose, detect drift, overlap, failure clusters and missed-opportunity patterns,
generate research ideas and preregister experiments, run authorized-scope research, operate
authorized shadow Challengers, prepare governance packets, invoke only preapproved deterministic
safety logic, and fail closed.

**Human approval remains required for** promotion into order-producing Paper · Paper to Micro-Live ·
Micro-Live to scaled operation · production model or parameter replacement · capital, risk, leverage
or short-exposure increases · a provider purchase, licence or new production dependency · resumption
after a governed suspension · any change to kill-switch behaviour.

**No automatic production parameter mutation exists anywhere in the design.** There is **no
last-ten-trades threshold optimization in place**; the Champion is unchanged until an authorized
promotion; and **open positions stay pinned to the versions that opened them**.

**Preregistration is immutable.** A change creates a linked amendment or a new registration before
further research; results and decisions **append** as linked records and never edit the
preregistration. **All trials are tracked against the budget, including failed and abandoned runs**,
because a multiple-testing control whose denominator is whatever the researcher recalls is not a
control.

**No numerical research or safety threshold becomes a production rule merely because it appears in a
synthetic example.**

**The Cockpit reads this loop; it does not drive it.** The future learning engine's writes and the
Cockpit's read-only presentation are different systems with different authority, and **this cycle
implements neither**.

---

## 8. The technology decision

**One stack is specified, with its rationale and its boundaries.** Specifying it here means a later
implementation cycle inherits a reviewed choice instead of making an architectural decision inside a
feature pull request.

| Layer | Choice |
|---|---|
| **Frontend** | Next.js App Router · TypeScript · Tailwind CSS · shadcn/ui on Radix primitives · TanStack Query for server state · TanStack Table for analytical tables · Zod for runtime contract validation · Zustand only for genuine local UI state where justified |
| **Charts** | **Recharts** for executive KPIs, trends and ordinary time series and comparisons · **TradingView Lightweight Charts** for OHLC, candles and trade overlays · **Apache ECharts** selectively for correlation matrices, return heatmaps, factor and regime matrices and dense research analytics |
| **Backend** | Python **FastAPI** · **Pydantic** · explicit versioned API contracts |
| **Storage** | **PostgreSQL** for operational projections · **DuckDB + Parquet** for qualified heavy research and history, later |
| **Transport** | ordinary query and cache transport by default; **SSE or WebSocket only where streaming materially benefits the state being shown** |
| **Web deployment** | **Vercel** is acceptable and preferred for an eligible Next.js deployment; Python services stay separately containerized; environment separation is explicit |

**Why these, briefly.** Next.js App Router and TypeScript give server-rendered analytical pages with
a typed contract boundary; Tailwind with shadcn/ui on Radix gives an accessible primitive layer
without adopting a design system whose visual identity would fight the executive brief; TanStack
Query and Table are the two pieces of genuinely hard state and table work worth not writing;
**Zod is load-bearing rather than decorative** — it validates the read-model envelope at the
boundary, so an unknown schema version is rejected instead of rendered. FastAPI and Pydantic match
the deterministic Python core the platform already is, and let the read API reuse its typed
contracts rather than re-describing them. PostgreSQL holds operational projections because they are
small, relational and frequently joined; DuckDB and Parquet hold heavy research history because it
is columnar, immutable and large, and that split already exists in
[ADR-0007](ADR-0007-cloud-first-research-data-plane.md).

**Three chart libraries is a deliberate cost.** One library would be simpler and would do at least
one of the three jobs badly: executive KPI trends, real OHLC with trade overlays, and dense
analytical matrices have genuinely different requirements. The boundary between them is specified so
the choice is not made per-screen by whoever is building it.

**No version is pinned here.** A documentation cycle that pins package versions pins them to the day
it was written; the implementation cycle selects and locks compatible versions, and that lock is
reviewable evidence rather than a guess.

**LEAN is unchanged.** It remains the research and execution engine
([ADR-0001](ADR-0001-system-foundation.md),
[ADR-0002](ADR-0002-broker-adapter-and-brokerage-boundary.md)), and **the Cockpit stack does not
replace it**. A charting library is not an execution engine.

**Nothing is deployed by choosing a stack.** No deployment, account setup, container launch,
database creation, infrastructure change, dependency installation or spending occurs in this cycle —
cloud spending remains separately authorized under `CLAUDE.md` §4.21.

**No claim is made about any third party's internal technology.** The visual direction referenced by
the UI specification is owner-supplied direction and nothing more; **this decision claims no
knowledge of the Atlas or SIRE internal technology stack**, and none was inspected.

---

## 9. Alternatives considered

| Alternative | Why it was not chosen |
|---|---|
| **No Cockpit; keep governing from Markdown and transcripts** | adequate for a repository, not for an autonomous platform. A degrading strategy, a stale feed and a blocked candidate are all invisible in a status document written last week |
| **Build the Cockpit after the platform is finished** | the observability surface would then be designed around whatever the platform happened to emit, and the read-model boundary would be retrofitted onto systems that had already grown convenient shortcuts to provider and broker data |
| **Let the Cockpit query providers and the broker directly** | it is faster to build and it destroys the boundary. A dashboard holding provider credentials is a provider integration; a dashboard holding broker credentials is an execution path |
| **Ship a read/write Cockpit with a small number of "safe" controls** | there is no small safe control on a trading system. A control plane needs its own authentication, authorization, audit, idempotency and safety architecture, and inventing that inside a UI cycle is how it gets invented badly |
| **Let the Cockpit record governance approvals** | the authenticity of an approval would then rest on a dashboard session. Governance screens display recorded decisions; the authoritative record stays where its own governance already puts it |
| **Extend `CandidateIntent` with sizing and execution fields so Trade Detail is a single read** | an interface convenience that relocates risk authority into the Brain. Trade Detail joins separately owned facts by reference instead |
| **Extend the Brain status vocabulary with downstream order states** | one vocabulary spanning two authority domains makes it impossible to tell, from a status alone, whether the Brain or the execution layer produced it |
| **Specify only the screens and decide the stack during implementation** | the stack is an architectural decision with licensing, hosting and boundary consequences. Deciding it inside a feature pull request is deciding it by whoever is typing |
| **Pin exact package versions now** | a documentation cycle cannot validate a lockfile it never installs. Pinning here produces versions nobody resolved |
| **One chart library everywhere** | simpler, and wrong for at least one of the three chart classes. The split is specified rather than left to per-screen improvisation |

---

## 10. Consequences

**Accepted.**

- The Cockpit becomes a named subsystem with an architecture extension indexed beside the adopted
  Blueprint, rather than an undocumented reporting layer.
- Every future Cockpit implementation cycle inherits reviewed contracts, a reviewed stack and a
  reviewed safety boundary, and a deviation from any of them is visible as a deviation.
- The 36 product areas are traceable: each has a specification section, a presentation, a read-model
  owner, a synthetic availability, a real-feed gate, an implementation cycle and observable
  acceptance criteria.
- The feedback loop has stage contracts and an authority matrix, so *what the machine may do on its
  own* is checkable rather than aspirational.

**Costs, stated rather than absorbed.**

- **Specification ages.** Six documents describing a system that does not exist will drift from the
  system that eventually does. The mitigation is the documentation audit and the governance tests,
  not diligence.
- **The read-model boundary costs work.** Every screen that would be trivial against a live provider
  or broker connection instead needs a projection, a contract and a version. That cost is the
  boundary, and paying it is the point.
- **Synthetic-first delivery can flatter.** A polished demonstration over deterministic fixtures can
  be mistaken for a working platform. Every synthetic surface is labelled, and no synthetic result
  is evidence of anything.
- **Thirty-six areas is a large V1 scope.** The sequencing in the traceability matrix is how it is
  managed; the risk that later cycles are cut short is real and is named here rather than discovered
  later.

**Rejected consequences — things this decision does not do.**

```text
implements NOTHING                        authorizes NOTHING
builds no application                     installs no dependency
creates no database                       provisions no infrastructure
selects no provider                       closes no gate
claims no alpha                           establishes no expected return
runs no backtest                          reads no provider data
reads no private artifact                 touches no AWS or Terraform
contacts no broker                        produces no order
advances no qualification gate            changes no risk or capital value
```

---

## 11. What acceptance would and would not mean

**On independent review and merge, this ADR accepts architecture, contracts, governance and future
implementation boundaries — and nothing else.**

| | |
|---|---|
| Cockpit specification | **ACCEPTED EFFECTIVE ON MERGE OF PR #71** |
| Cockpit application implementation | **NOT STARTED / NOT AUTHORIZED** |
| Read-model, projection and API implementation | **NOT STARTED / NOT AUTHORIZED** |
| Feedback and learning-engine implementation | **NOT STARTED / NOT AUTHORIZED** |
| Brain runtime implementation | **NOT STARTED / NOT AUTHORIZED** |
| Strategy, factor, scanner and AI-agent implementation | **NOT STARTED / NOT AUTHORIZED** |
| Portfolio and risk engine implementation | **NOT STARTED / NOT AUTHORIZED** |
| Database, migration, scheduler and deployment | **NOT STARTED / NOT AUTHORIZED** |
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
| `LIVE_TRADING_HARD_DISABLED` | **True** |
| Live trading | **HARD-DISABLED** |

**No ADR is amended or superseded.** ADR-0026 is **ACCEPTED / IN FORCE** through the merge of
PR #70, and this decision **changes nothing in it** — it consumes its contracts. ADR-0005 remains
**PROPOSED**. ADR-0006's authority split is applied, not altered. **No source module is created by
this decision**, and **no placeholder application package is created** — an empty package is an
invitation for a later session to fill it without an authorization.

**Passing the 2026-09-12 date gate is not execution authorization.** Run B still requires its own
fresh prompt and its own written authorization, and so does the combined assessment. **The at least
eight calendar day Run A to Run B separation is unchanged.**

**Specification, implementation, research, deployment and execution are five separate gates**, and
they are never collapsed into one. This decision opens only the first, and only on independent
review and merge.

**"Cockpit specified" does not mean Cockpit implementation started.** These documents exist; the
Cockpit does not.

---

## 12. Governance status at the time of this decision

```text
G1 OPEN · G2 OPEN · G3 CLOSED · G4 OPEN · G5 OPEN · G6 OPEN · G7 OPEN
ADR-0005 PROPOSED · ADR-0026 ACCEPTED / IN FORCE · INC-0002 OPEN
Phase 3 NOT COMPLETE · CONTROL publication DEFERRED · live trading HARD-DISABLED
Run A COMPLETED ONCE, 2026-09-04 · Run A retry NOT AUTHORIZED
Run B NOT RUN / NOT AUTHORIZED · earliest approved target 2026-09-12
combined assessment NOT RUN / NOT AUTHORIZED · P1–P9 UNEVALUATED
provider selected NONE · backtesting NOT STARTED
```

**Each gate is read on its own.** G3 is closed for the Sharadar personal-use licence and nothing
else ([ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md)); the other
six are open for their own reasons. **No blanket statement about all seven is correct.**
