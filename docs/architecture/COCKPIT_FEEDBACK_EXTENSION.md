# Cockpit and Feedback — Blueprint V3.0 architecture extension

**Status: PROPOSED — NOT IN FORCE, and ACCEPTED EFFECTIVE ON MERGE OF PR #71.** While the pull
request introducing this extension is open it carries no authority. That is a statement about these
days; it stays true of them after any later merge, and it is not rewritten as though the extension
had authority before it was accepted.

**Introduced by** [ADR-0027](../decisions/ADR-0027-cockpit-and-feedback-architecture-and-governance.md).

---

## What this document is, and what it is not

**The adopted Blueprint V3.0 PDF does not describe the Cockpit.** It was issued and adopted before
this subsystem was specified, and **it is not edited** — the rule this repository already applies to
both Blueprint PDFs ([BLUEPRINT_ERRATA.md](BLUEPRINT_ERRATA.md),
[BLUEPRINT_V3_ADOPTION.md](BLUEPRINT_V3_ADOPTION.md)). **No claim is made anywhere that the adopted
PDF already contains this material.**

This file is the **architecture extension**, recorded in tracked text and indexed beside the
immutable adopted document, exactly as the Document Control override is. It states **fundamental
subsystem architecture** — position, data flow, boundaries, vocabularies and authority.

**It deliberately holds no page-level criteria.** Screen contents, field lists, metric definitions
and acceptance thresholds live in the Cockpit specifications, and a Blueprint-level document that
carried them would have to change every time a chart did.

| Layer | Document |
|---|---|
| **Architecture extension** | this file — subsystem position, data flow, boundaries, vocabularies |
| **Decision** | [ADR-0027](../decisions/ADR-0027-cockpit-and-feedback-architecture-and-governance.md) — rationale, alternatives, consequences, authority |
| **Functional specification** | [`cockpit-v1-specification.md`](../cockpit/cockpit-v1-specification.md) — the 36 areas and their contracts |
| **Contracts** | [`read-model-contracts.md`](../cockpit/read-model-contracts.md) — envelopes, read models, endpoints, metrics |
| **Feedback** | [`feedback-self-maturation-specification.md`](../cockpit/feedback-self-maturation-specification.md) |
| **Presentation** | [`ui-ux-specification.md`](../cockpit/ui-ux-specification.md) |
| **Traceability** | [`traceability-matrix.md`](../cockpit/traceability-matrix.md) |
| **Implementation** | future code, outside this cycle and separately authorized |

---

## 1. The subsystem, and where it sits

**The Cockpit is the primary human observability and governance surface for the eventual autonomous
platform.** It is not a report, not an admin panel and not a control system.

**Initial V1 is observational.** It displays, explains, compares, diagnoses, surfaces alerts,
navigates, and presents evidence and decisions. It changes nothing.

```text
  DETERMINISTIC CORE                     |  OBSERVABILITY
                                         |
  scanner and factor pipeline            |  the Cockpit reads projections of what
  the Strategy Brain                     |      these subsystems recorded
  portfolio and risk                     |
  execution and reconciliation           |  it holds no credential, opens no
  data platform and qualification        |      provider session, and reaches no broker
  the research and feedback engine       |
```

---

## 2. The data flow, and the boundary it creates

```text
KalpaMani subsystems
    -> immutable facts, events and versioned results
        -> dedicated projections and read models
            -> versioned read API
                -> Cockpit UI
```

**Each arrow is a boundary, not a pipe.** A projection is built from recorded facts and never by
asking a live source; the read API serves projections and never proxies a source; the interface
consumes the read API and never anything else.

### 2.1 What the Cockpit has no access to

```text
the Sharadar or any other provider API        provider credentials or AWS secrets
IBKR trading APIs or brokerage credentials    mutable Brain internals
private qualification artifacts through a convenient dashboard proxy
```

**The boundary applies to the backend as well as the browser.** The failure this prevents is not a
browser reaching a broker — no one would write that. It is a read endpoint that "just fetches the
current position from IBKR because the projection is stale", which is an execution-path integration
with a dashboard's name on it. **An API proxy must not become a disguised provider or broker
integration.**

### 2.2 Read-only, defined by absence

No Cockpit endpoint, command, assistant tool, hidden handler, background job or scheduled action may
place or cancel an order, change a stop, change risk or capital, activate or promote a strategy,
enable leverage, change the provider, execute Run B or an assessment, publish CONTROL, alter
production strategy state, or approve or reject a governance release.

**Governance screens display recorded decisions and packets; they do not originate authoritative
approval records in V1.**

**The Cockpit inherits no authority from what it observes.** A separately governed deterministic
system may eventually reduce risk automatically under preapproved rules. That is that system's
authority, and it grants the Cockpit none.

---

## 3. Ownership, preserved exactly

| Layer | Owns | Never owns |
|---|---|---|
| **Brain** | `CandidateIntent` — why an opportunity exists, why now, what evidence, what deterministic status, what risk context | shares, dollars, position size, order type, route, client order ID, broker order ID |
| **Portfolio / risk** | ownership permission, sizing, shares, risk constraints | why the opportunity exists; how an order is routed |
| **Execution** | order type, route, fills, protection, reconciliation | whether the portfolio should own the position |

**No sizing or execution field is added to `CandidateIntent` to simplify a screen.** A Trade Detail
view reconstructs a whole trade by **joining separately owned downstream facts through safe internal
references**. The join is a read-model concern; the contracts stay where they are.

**Downstream states are a separate vocabulary.** ADR-0026's Brain decision states are closed, and
risk-approval, order and fill states belong to their own layers with their own vocabularies. **The
Brain status enum is never extended with downstream states.**

---

## 4. Vocabularies, and how they map to what already exists

### 4.1 Product maturity stages

Five presentation-level stages. **They are a view over existing values; they replace none of them.**

| Stage | Label | ADR-0026 lifecycle stages it presents | Runtime `Environment` | Order authority |
|---|---|---|---|---|
| `RESEARCH` | Research | `IDEA`, `REGISTERED_HYPOTHESIS`, `TAXONOMY_OVERLAP_REVIEW`, `DATA_FEASIBILITY`, `BASELINE_RESEARCH`, `LOCKED_OUT_OF_SAMPLE_VALIDATION` | `RESEARCH` | none |
| `SHADOW` | Shadow | `SHADOW` | `RESEARCH` | **none — Shadow produces no order** |
| `AUTOMATED_PAPER` | Automated Paper | `AUTOMATED_PAPER` | `PAPER` | first order-producing stage; **human approval required** |
| `MICRO_LIVE` | Micro-Live | `MICRO_LIVE_CANARY` | `LIVE` | **HARD-DISABLED** |
| `SCALED_LIVE` | Scaled Live | `SCALED` | `LIVE` | **HARD-DISABLED** |

**`WATCH`, `SUSPENDED` and `RETIRED` are not maturity stages.** They are lifecycle statuses a
version holds *within* whatever stage it last reached, and they are displayed as status rather than
as position on the maturity ladder.

**The runtime `Environment` enum is unchanged** — `RESEARCH`, `PAPER`, `LIVE`, exactly as
`src/kalpamani/common/environment.py` defines it. **No runtime enum is changed, added to or renamed
by this extension**, and no competing lifecycle vocabulary is created.

**Selecting a stage in the interface advances nothing.** A maturity stage is a property of a
strategy version's governance record; a filter is a filter.

### 4.2 The five things kept separate

Collapsing any two of these produces a false statement on a screen.

| Concept | Question it answers | Example |
|---|---|---|
| **deployment identity** | which Cockpit deployment am I looking at? | local · private boundary · externally hosted demonstration |
| **trading and runtime environment** | which runtime `Environment` produced this? | `RESEARCH` · `PAPER` · `LIVE` |
| **strategy maturity** | how far has this strategy version been governed? | the five stages above |
| **source provenance** | where did these numbers come from? | the vocabulary in §4.3 |
| **data availability** | can this number be shown at all? | the vocabulary in §4.4 |

**SYNTHETIC/DEMO is provenance, not an environment.** A `RESEARCH` environment does not imply
synthetic data, and a synthetic figure is not a research result.

### 4.3 Source provenance

A closed vocabulary. Every read model carries one value.

| Value | Meaning |
|---|---|
| `SYNTHETIC` | a repository-owned deterministic fixture. No vendor row, no broker record, no owner private data |
| `SYSTEM_RECORDED` | produced by KalpaMani's own deterministic runtime from authorized inputs |
| `BACKTEST_SIMULATED` | produced by an authorized research run. **Hypothetical, never realized** |
| `BROKER_REPORTED` | observed from a brokerage under an authorized session |

**A hypothetical result and a realized result never share a series.** An explicit comparison keeps
them separately labelled.

### 4.4 Data availability

A closed vocabulary, and **never an overloaded number**.

| Value | Meaning |
|---|---|
| `AVAILABLE` | a real value, with its as-of time |
| `NOT_YET_AVAILABLE` | the feed is specified and the dependency has not been satisfied |
| `NOT_IMPLEMENTED` | the producing subsystem does not exist |
| `NOT_AUTHORIZED` | the producing operation exists and is not authorized to run |
| `UNEVALUATED` | the question has not been assessed |
| `STALE` | a value exists and is older than its freshness contract |
| `PARTIAL` | some of the requested extent is present and some is not |
| `ERROR` | production failed, and the failure is reported rather than hidden |
| `NOT_APPLICABLE` | the question does not apply to this subject |
| `EMPTY_VERIFIED` | the producer ran, and the correct answer is genuinely nothing |
| `INSUFFICIENT_OBSERVATIONS` | a value could be computed and would not be meaningful |

**A missing value is never converted to zero, healthy, passed or no incidents.** `EMPTY_VERIFIED`
and `NOT_YET_AVAILABLE` look identical on a naive screen and mean opposite things.

**A historical success carries its as-of time.** A past identity preflight is not proof of current
authentication health, and a screen that shows one without the other is asserting something nobody
checked.

### 4.5 Classification and hosting

| Classification | May live in |
|---|---|
| `PUBLIC_SAFE` | the public repository, a public demonstration, an externally hosted deployment |
| `PRIVATE_OPERATIONAL` | the approved private deployment boundary only |
| `LICENSED_DERIVED` | the approved private deployment boundary only |
| `UNCLASSIFIED` | **nowhere — it fails closed** |
| `CONTROL` | **refused at admission**; CONTROL publication remains **DEFERRED** |

**"Read model" and "derived" do not mean safe to publish.** The classification question is the one
[ADR-0007](../decisions/ADR-0007-cloud-first-research-data-plane.md) already asks: *can vendor rows
be recovered from this artifact?* Yes **or uncertain** means licensed.

```text
PUBLIC_EDGE         externally hosted; admits PUBLIC_SAFE with SYNTHETIC provenance only
PRIVATE_BOUNDARY    inside the approved private deployment boundary
```

**A server-side render, an API proxy, an edge cache and a build-time fetch are each a copy.** An externally
hosted deployment must not silently receive a licensed payload through any of them.

---

## 5. Immutable audit and deletable licensed data

Two obligations that look opposed and are not:

| | |
|---|---|
| **governance** | the audit trail is immutable, so a decision can be reconstructed years later |
| **licensing** | licensed vendor data must be destroyable on short notice (`CLAUDE.md` §4.23) |

**They are reconciled by never putting one inside the other.** An immutable audit event carries
**classified references and lineage identifiers**, not vendor rows — the rule ADR-0026 §27 already
applies to the Brain journal, extended here to every Cockpit-visible audit surface. Deletion is
expressed as **authorized tombstone semantics**: the governance evidence survives, the referenced
licensed content does not, and the record says which.

**A reference is not a row**, and an audit payload that quotes vendor data is a copy the deletion
runbook cannot reach.

---

## 6. The feedback and self-maturation architecture

```text
Signal / Trade / Decision Journal
    -> Outcome and Attribution
        -> Strategy Health / Drift / Failure Clusters
            -> Research Queue
                -> Preregistered Hypothesis
                    -> Immutable Challenger
                        -> Authorized Backtest / Locked OOS / Stress
                            -> Shadow
                                -> Governance Packet
                                    -> Human-Authorized Release
```

**Self-maturing is not self-governing**, exactly as
[ADR-0006](../decisions/ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md) §C holds.
Automation may run the loop up to the packet; **a human takes the release**.

**The learning engine writes; the Cockpit reads.** They are different systems with different
authority, and neither exists yet.

**Preregistration is immutable, and results append.** No production parameter is mutated
automatically, no threshold is optimized against recent trades, and the Champion is unchanged until
an authorized promotion.

---

## 7. Four separate concepts, kept apart by design

A recurring failure in trading dashboards is one "history" screen that is asked to be four things
and is a poor version of each.

| Concept | Question it answers | Who it is for |
|---|---|---|
| **Trade History** | what did we trade, and how did it turn out? | a human-friendly trade ledger and results |
| **Trade Detail** | what is the complete story of *this* trade? | candidate through attribution, one trade end to end |
| **Execution History** | what did the order machinery actually do? | order, fill and reconciliation mechanics |
| **Audit Trail** | what happened, immutably, including things that were not trades? | forensic reconstruction |

**They share identifiers and do not share screens.** A trade is not its fills; an audit event is not
a trade; and a reconciliation record is neither.

---

## 8. What this extension does not do

```text
edits no Blueprint PDF                     changes no runtime enum
amends no ADR                              creates no source module
implements nothing                         authorizes nothing
selects no provider                        closes no gate
grants the Cockpit no control authority    claims no alpha
```

**Specification, implementation, research, deployment and execution are five separate gates.** This
extension is part of the first, and only on independent review and merge.

```text
G1 OPEN · G2 OPEN · G3 CLOSED · G4 OPEN · G5 OPEN · G6 OPEN · G7 OPEN
Phase 3 NOT COMPLETE · CONTROL DEFERRED · live trading HARD-DISABLED
Run B NOT RUN / NOT AUTHORIZED · earliest approved target 2026-09-12
combined assessment NOT RUN / NOT AUTHORIZED · P1–P9 UNEVALUATED
provider selected NONE · backtesting NOT STARTED
```
