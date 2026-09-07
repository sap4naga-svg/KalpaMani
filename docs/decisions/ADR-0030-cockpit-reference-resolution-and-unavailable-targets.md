# ADR-0030 — Cockpit reference resolution, unassigned reference kinds and unavailable targets

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0030 is proposed and carries no authority,
and so are the corrections it makes to the Cockpit specification in the same pull request. That is a
statement about the present, it will remain true of these days after any later merge, and it is not
to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **corrected contracts and governance** — and nothing else.

**The acceptance event is exact:** the independent review and merge of the pull request introducing
this ADR into `main`. No merge SHA and no merge timestamp is predicted here; those are repository
state, recorded after the fact if they are recorded at all.

**Date:** 2026-09-07
**Supersedes:** nothing
**Superseded by:** —
**Amends:** [`docs/cockpit/read-model-contracts.md`](../cockpit/read-model-contracts.md) at §4.1,
§4.2, §4.3 and §5, at the exact clauses listed in §4 below. **It does not amend, supersede or edit
ADR-0027, ADR-0028 or ADR-0029 themselves**, each of which remains **ACCEPTED / IN FORCE**.
**Relates to:** [ADR-0026](ADR-0026-strategy-brain-architecture-and-governance.md),
[ADR-0027](ADR-0027-cockpit-and-feedback-architecture-and-governance.md),
[ADR-0028](ADR-0028-cockpit-contract-completion-and-boundary-corrections.md),
[ADR-0029](ADR-0029-valid-zero-values-and-cache-freshness-deadlines.md)

**Nothing was run to produce this decision.** No AWS, STS, SSO, IAM, Secrets Manager or S3 call; no
Terraform command of any kind; no Terraform state, backend configuration, `.tfvars` or `.terraform/`
read; no `.runtime/` inspection; no provider request; no credential access; no Run A retry, Run B or
combined assessment; no P1–P9 execution; no backtest; and no broker, LEAN or IBKR activity. **No
Blueprint PDF was opened or edited.** No dependency was installed, no package manifest was changed,
and no runtime behaviour was implemented. This decision is authored from tracked repository
authority alone.

**No alpha is claimed anywhere in this decision.**

---

## 1. Context

The C6 cycle implemented the signals and trade-lifecycle read models against
`read-model-contracts.md` §4.2 and §4.3. Its independent review recorded that `ref_kind` is admitted
as an open string, that no reference-kind-to-resolution table is enforced, and that
`TradeDetail.brain_decision_ref` is emitted with an `ENDPOINT` resolution where §4.3 assigns
`brain_decision` an `EMBEDDED` one.

**C7 extends the same reference infrastructure.** Areas 5 and 14–21 introduce read models joined
almost entirely by reference — `strategy_version`, `health_transition`, `research_run`,
`registration`, `queue_item`, `packet` and `decision` are each a §4.3 row that C7 is the first cycle
to exercise. Building those screens on an unenforced reference contract would multiply the defect
rather than contain it, which is why this reconciliation is a prerequisite rather than a cleanup.

**The reviewer's finding is correct, and the reason recorded beside it in the C6 implementation is
not the whole reason.** The C6 note argues that `brain_decision` cannot be `EMBEDDED` from
`TradeDetail` because the journaled decision is not inside that response. That much is true. It does
not follow that a required reference implies an available target, and the investigation behind this
decision established a different and larger conflict underneath it: **the accepted text assigns no
kind at all to eighteen of its own required reference fields**, so the closed vocabulary §4.2 names
cannot be enumerated and the §4.3 table cannot be applied to them.

---

## 2. The defects, reproduced from the accepted text

Each finding below is **parsed out of `read-model-contracts.md` and executed**, not read off by
eye. `tests/unit/test_cockpit_reference_contracts.py` carries the parsers and their self-tests.

### 2.1 D1 — eighteen required reference fields carry no `ref_kind`

§4.2 types `Ref.ref_kind` as a **closed `RefKind`**, and §4.3 opens with *"A `_ref` whose resolution
is not in this table is refused at the boundary."* Both rules are unreachable for a reference whose
kind was never assigned, and the accepted §4.5 catalogue leaves **eighteen** `Ref`-valued fields
without a `kind` declaration:

```text
ExecutiveOverview        last_decision.ref            last_scout_run.ref
TradeLifecycle           events[].correction_of       events[].source_ref
ReconciliationStatus     position_diffs[].security_ref            order_diffs[].local_ref
CandidateDetail          downstream_refs.risk_decision            downstream_refs.trade
RiskSnapshot             initial_planned_risk_open[].trade_ref    decisions[].decision_ref
ShortSideSnapshot        borrow[].security_ref        deterioration[].record_ref
                         blocked_shorts[].candidate_ref
HypothesisRegistration   lineage.parent_registration  lineage.superseded_by
QualificationStatus      three separate source_ref fields
SearchResultPage         results[].ref
```

**Every kind the catalogue does declare explicitly has a §4.3 row.** The gap is not a missing row
for a declared kind; it is that these eighteen fields declare no kind for a row to be found for.

**An implementation must therefore guess, and one guess is already wrong in a way a reader can
see.** `CandidateDetail.downstream_refs.trade` is *the trade this candidate became*. §4.3 has no
`trade` row, so C6 emitted it as kind `source_fact` — the row §4.3 defines as *"the recorded fact a
projection was built from"* — with an `ENDPOINT` resolution that `source_fact`'s own row does not
list. A reader of that payload cannot distinguish the trade a candidate produced from a provenance
record the projection was built out of, and the two are different facts.

### 2.2 D2 — `brain_decision` is assigned `EMBEDDED`, and its only carrier cannot embed it

`brain_decision` is declared **exactly once** in the whole §4.5 catalogue, on
`TradeDetail.brain_decision_ref`. §4.2 defines `EMBEDDED` as *"the referenced payload is already
inside this response"*, and the accepted `TradeDetail.payload` carries **no** brain-decision field.
§4.3's own target column points the reference into `CandidateDetail` — which carries `brain_state`
as a plain `BrainDecisionState` field and **no `brain_decision` reference at all**.

So the one place the kind is used is the one place `EMBEDDED` cannot be stated truthfully, and the
place `EMBEDDED` would be truthful carries no reference to be truthful about. **No implementation
resolves this**: emitting `EMBEDDED` from `TradeDetail` claims a payload the response does not
carry, and emitting anything else contradicts the table.

### 2.3 D3 — the Resolution column is already a set, and `EMBEDDED` is response-relative

Two accepted rows carry **two** resolutions in one cell — `chart_series` and `benchmark_series` are
each *"`AUTHORIZED_READ` — `market:read`; `UNRESOLVABLE_V1`"*. The column is therefore **not** a
single per-kind invariant, and the accepted text never says what a multi-valued cell permits.

Meanwhile `EMBEDDED` is defined relative to *"this response"*. A property of a response cannot be
expressed by one global value for a kind carried by more than one response, and the implementation
demonstrates exactly that: `TradeDetail` emits `EMBEDDED` for `add`, `exit` and `execution_quality`
against a table value of `ENDPOINT`, and for `chart_series` and `benchmark_series` against a cell
that does not list `EMBEDDED` — **truthfully in every case**, because `TradeDetail` really does
carry `execution_quality`, `chart_series` and `benchmark_series` as ADR-0028 additive payloads.

**Enforcing the column as a per-kind invariant would force a producer to lie** — to declare
`ENDPOINT` beside a payload it is carrying — or to drop accepted additive fields.

### 2.4 D4 — the Cardinality column has three possible referents

`Cardinality` appears in §4.2 only as a field of `RefList`, never of `Ref`. Yet §4.3 states a
cardinality for every kind, including kinds carried as a single required `Ref`:

```text
candidate     ZERO_OR_ONE    carried by TradeDetail.candidate_ref, a REQUIRED single Ref
source_fact   ONE_OR_MORE    carried by the envelope's source_refs, legitimately EMPTY today
```

A required field always carries exactly one reference object, so `ZERO_OR_ONE` cannot be counting
reference objects there; and an envelope whose producer references no source fact cannot satisfy
`ONE_OR_MORE` if it is. **The column sometimes describes reference objects and sometimes describes
targets, and the text does not say which.** `RefList.cardinality` is additionally never validated
against `items`, so a list may declare `EXACTLY_ONE` and carry five.

### 2.5 D5 — no code distinguishes an unknown identifier from an unimplemented producer

The closed `FieldReasonCode` vocabulary (§4.1) carries `PRODUCER_NOT_IMPLEMENTED`,
`PRODUCER_NOT_AUTHORIZED` and `CLASSIFICATION_WITHHELD`, and the closed §5 error vocabulary carries
`SCOPE_MISSING`, `SCOPE_INSUFFICIENT` and `CLASSIFICATION_WITHHELD`. **Neither carries a member
meaning "this reference is well-formed and names nothing."**

A reference to a deleted, superseded or simply unknown identifier therefore has nowhere truthful to
land. It collapses into `PRODUCER_NOT_IMPLEMENTED` — which asserts something false about the
producing subsystem — or into a bare 404 a caller has to interpret, which is the outcome
`UNRESOLVABLE_V1` exists to prevent.

### 2.6 What is a plain implementation defect, and is not corrected here

`ref_kind: z.string().min(1)` in `apps/cockpit/src/contracts/values.ts` is an open string where the
contract says closed. **That is a genuine implementation defect and it is correctable** — but only
once D1, D2 and D3 fix *which* members the closed set has and *which* resolutions each admits.
Closing it against today's table would refuse the truthful `EMBEDDED` declarations of D3 and would
freeze the mislabelled `source_fact` of D1. It is assigned to the implementation follow-up in §7.

**One thing the review might have expected to find is not a defect.** Reference navigation already
resolves through a closed allowlist keyed by kind, with no fallback: an unmapped kind produces no
link. No URL is built from `ref_id` or `ref_kind`, and there is no generic resolver, proxy or
external fetcher. R10 records that as a rule rather than leaving it as an accident.

---

## 3. Why faithful implementation cannot resolve this

**D1 and D2 are not correctable under accepted authority**, and the distinction matters because a
specification amendment is the heavier instrument and should not be reached for first.

| | |
|---|---|
| **D1** | assigning a kind to an accepted contract field is a **specification act**, and §2 of `read-model-contracts.md` reserves extension of a closed vocabulary to an ADR: *"a new member is added by an ADR rather than by an implementation."* `downstream_refs.trade` additionally needs a `trade` member that no accepted row supplies |
| **D2** | the two accepted clauses are **jointly unsatisfiable** by any conformant `TradeDetail`. An implementation can obey one or the other and not both, and choosing between two accepted clauses is not an implementation decision |
| **D3** | requires **choosing** whether the Resolution column is an invariant or a permitted set, and whether `EMBEDDED` is response-relative. The accepted text supports the question and answers neither |
| **D4** | requires **choosing** the referent of a column that the accepted text uses in two incompatible ways |
| **D5** | requires **adding members** to two closed vocabularies, which §2 and §5 both reserve to an ADR |

**No conflict is manufactured to avoid an implementation correction.** The correctable part is named
in §2.6, it is real, and it is scheduled — it is simply blocked behind the five decisions above,
because enforcing an under-determined table is what produced the mislabelled reference in the first
place.

---

## 4. Decision

Ten rules. Each is written to be checkable, and §6.3 gives the acceptance examples an implementation
will be reviewed against.

### R1 — `RefKind` is closed and enumerated

The closed `RefKind` vocabulary has **twenty-seven** members: the twenty-six rows of the accepted
§4.3 table, plus **`trade`**, added here because `CandidateDetail.downstream_refs.trade` and
`RiskSnapshot.initial_planned_risk_open[].trade_ref` both require a reference to a trade and no
accepted row supplies one. A value outside the set is **refused at the boundary**, never rendered
and never coerced.

### R2 — every `Ref`-valued field in the catalogue names its kind

The eighteen fields of §2.1 are assigned as follows. Each assignment is the kind the field's own
contract text already describes; none invents a relationship the catalogue does not state.

| Field | Kind |
|---|---|
| `ExecutiveOverview.last_decision.ref` | `decision` |
| `ExecutiveOverview.last_scout_run.ref` | `research_run` |
| `TradeLifecycle.events[].correction_of` | **the kind of the event it corrects** — one of `order`, `fill`, `protection`, `add`, `exit` |
| `TradeLifecycle.events[].source_ref` | `source_fact` |
| `ReconciliationStatus.position_diffs[].security_ref` | `evidence` |
| `ReconciliationStatus.order_diffs[].local_ref` | `order` |
| `CandidateDetail.downstream_refs.risk_decision` | `risk_decision` |
| `CandidateDetail.downstream_refs.trade` | **`trade`** |
| `RiskSnapshot.initial_planned_risk_open[].trade_ref` | **`trade`** |
| `RiskSnapshot.decisions[].decision_ref` | `risk_decision` |
| `ShortSideSnapshot.borrow[].security_ref` | `evidence` |
| `ShortSideSnapshot.deterioration[].record_ref` | `evidence` |
| `ShortSideSnapshot.blocked_shorts[].candidate_ref` | `candidate` |
| `HypothesisRegistration.lineage.parent_registration` | `registration` |
| `HypothesisRegistration.lineage.superseded_by` | `registration` |
| `QualificationStatus` — each of three `source_ref` fields | `source_fact` |
| `SearchResultPage.results[].ref` | **any `RefKind`** — a search result names whatever was found, and its resolution is that kind's |

`security_ref` resolves to `evidence` because the accepted `CandidateDetail.security_ref` already
declares *"required, kind `evidence`"*, and one field name must not mean two kinds.

### R3 — the Resolution column is a permitted SET, and a reference declares one member of it

`Resolution` stays the closed four-member vocabulary. §4.3's column names **which members a
reference of that kind may declare**, and a reference declaring a member outside its kind's set is
refused at the boundary. Two accepted cells already carry two members, and this rule states what
that means rather than changing it.

### R4 — `EMBEDDED` is response-relative, permitted for every kind, and only when true

A response may declare `EMBEDDED` on a reference **exactly when that same response carries the
referenced payload in a named field**. Otherwise `EMBEDDED` is refused.

The rule is **self-verifying**: the check is against the response being validated, not against a
table, so `EMBEDDED` cannot be claimed for a payload that is not there. It makes `TradeDetail`'s
existing `add`, `exit`, `execution_quality`, `chart_series` and `benchmark_series` declarations
correct rather than tolerated, and it keeps a producer from declaring `ENDPOINT` beside a payload it
is carrying. **`EMBEDDED` is therefore in every kind's permitted set, and constrained by truth
rather than by enumeration.**

### R5 — `brain_decision` permits `EMBEDDED`, `ENDPOINT` and `UNRESOLVABLE_V1`

`EMBEDDED` where a response carries the journaled decision status — the case §4.3's target column
describes. **`ENDPOINT`** from `TradeDetail` where a candidate was journaled, resolving by
`GET /api/v1/signals/candidates/{candidate_id}`. **`UNRESOLVABLE_V1`** where no candidate was
journaled and no producer exists.

This **ratifies the C6 implementation's choice** rather than reversing it: the choice was honest and
the table was wrong to forbid it. `TradeDetail` gains **no** brain-decision field — widening it to
force an `EMBEDDED` declaration would put a Brain payload inside a portfolio read model, and §4.3's
*"resolving a reference is an authorized read, not a widening"* forbids exactly that.

### R6 — `UNRESOLVABLE_V1` means the producer does not exist, and an implemented producer is not one

Unchanged from §4.3 and made checkable: `UNRESOLVABLE_V1` is permitted **only** where the producing
subsystem does not exist. **A producer implemented against repository-owned synthetic fixtures
exists**, and a reference into it declares the resolution its kind and response actually support.
Declaring `UNRESOLVABLE_V1` over a producer this application implements is refused.

### R7 — cardinality is a statement about targets; a list additionally constrains its items

The §4.3 Cardinality column describes **the relation** — how many targets a subject may have.

```text
a required Ref field       carries EXACTLY ONE reference OBJECT, always
its cardinality column     says how many TARGETS that one reference may resolve to
                           ZERO_OR_ONE  -- the target may be absent, and the reference stays
                           EXACTLY_ONE  -- a target exists whenever the subject does
a RefList field            carries zero or more reference objects
its cardinality field      RESTATES the relation cardinality from the table, and must be
                           consistent with items and total
```

**A `RefList` whose `items` count cannot satisfy its declared cardinality is refused**, with one
stated exception: a `ONE_OR_MORE` relation may carry an empty list when its `total` is **not** an
`AVAILABLE` zero — the count must carry a state and reason saying why the population could not be
enumerated. An `AVAILABLE` zero against a `ONE_OR_MORE` relation asserts that a relation the
contract says always has members has none, and that is a claim no producer may make silently.

### R8 — a reference resolves to its own target, or to nothing

A resolved target must match the reference's `ref_id` **exactly** and be of the reference's kind.
**A resolver never falls back to a different entity, a nearest match, a default or a first row when
an identifier is unknown**, and the resolved target's environment and provenance must match the
resolving response's envelope. A reference whose identifier names nothing resolves to the
availability state of R9 and never to a substitute.

### R9 — four unavailable outcomes, kept apart

`FieldReasonCode` gains **`REFERENT_NOT_FOUND`**, and the §5 error vocabulary gains
**`REFERENT_NOT_FOUND`**. The four outcomes are then distinct and none is a synonym for another:

| Outcome | Availability | Reason |
|---|---|---|
| the reference is well-formed and names nothing | `NOT_YET_AVAILABLE` | `REFERENT_NOT_FOUND` |
| the producing subsystem does not exist | `NOT_IMPLEMENTED` | `PRODUCER_NOT_IMPLEMENTED` |
| the target exists and this caller may not read it | `NOT_AUTHORIZED` | `CLASSIFICATION_WITHHELD` |
| the reference itself is malformed or its kind is unknown | — | **refused at admission**, never an availability state |

**A malformed reference is a contract violation, not an availability answer**, and the boundary
rejects the response rather than rendering a state for it.

**`REFERENT_NOT_FOUND` carries `NOT_YET_AVAILABLE`, and never `NOT_APPLICABLE`.** An earlier draft
of this decision placed it under `NOT_APPLICABLE`, and the accepted governance suite refused it:
ADR-0028 established that **`NOT_APPLICABLE` has exactly two routes** and that *"inapplicability is a
property of the subject or of the arithmetic, not a synonym for 'we do not have it'"*. A reference
whose identifier names nothing is exactly *we do not have it* — the question still applies, and the
target is absent. **The accepted invariant was right and the draft was wrong**, so this decision
leaves `NOT_APPLICABLE` at its two routes and **weakens no accepted guard to fit its own prose**.

### R10 — no generic resolver, and no constructed URL

A navigation destination for a reference comes from a **closed allowlist keyed by `RefKind`**. An
unknown or unmapped kind yields **no link**. No destination is constructed from `ref_id` or
`ref_kind`, and **no generic external URL fetcher, proxy or unrestricted resolver is introduced**.
`Ref.classification` labels the reference; **it is not access or publication authorization**, and a
reference the caller may not follow stays **visible** under R9 so the reader knows something exists
that they may not see.

---

## 5. Alternatives considered

| Alternative | Why not |
|---|---|
| **Enforce §4.3 exactly as written** | jointly unsatisfiable. D2 makes a conformant `TradeDetail` impossible, and D1 leaves eighteen fields with no row to enforce |
| **Widen `TradeDetail` with a brain-decision payload so `EMBEDDED` becomes true** | puts a Brain payload inside a portfolio read model and contradicts §4.3's *"resolving a reference is an authorized read, not a widening"*. R5 keeps the join a reference |
| **Leave `ref_kind` an open string and document the convention** | §4.2 says closed. An open string is what admitted a trade reference labelled `source_fact` with a resolution its own row does not list |
| **Add a `lifecycle_event` kind for `correction_of`** | a correction corrects an event of a kind the vocabulary already has. A twenty-eighth member would name the same things twice |
| **Treat a multi-valued Resolution cell as an error to be normalised to one value** | two accepted rows carry two members. Normalising would silently drop `UNRESOLVABLE_V1` from the two market-data kinds that most need it |
| **Reuse `UPSTREAM_INPUT_MISSING` for an unknown identifier** | it means an input a producer needed was absent, not that an identifier names nothing. Reusing it would make the two indistinguishable, which is the failure R9 exists to prevent |
| **Bump every `schema_version` to `v2`** | no payload field is removed, renamed or given a new meaning. §5's rule makes that unnecessary, and a global bump would invalidate conformant clients for a narrowing |

---

## 6. Compatibility, versioning and acceptance examples

### 6.1 Compatibility

**No `schema_version` is bumped.** §5's accepted rule is *"a new optional field is additive; a
removal, a rename or a semantic change is a new version."* This decision removes no field, renames
no field and changes no field's meaning. It **narrows the admitted value set** of `ref_kind` and
`resolution`, which is transparent to any producer already conformant with the table, and it
**extends two closed vocabularies by ADR**, which §2 and §5 name as the sanctioned mechanism.

**One emitted value changes, and it was never contractual.**
`CandidateDetail.downstream_refs.trade` moves from kind `source_fact` to kind `trade`. The accepted
contract never authorized `source_fact` there — the kind was unassigned and the implementation
guessed — so this corrects a non-conformant value rather than changing a contract.

**Consumers switching exhaustively on a closed vocabulary gain one member each.**
`REFERENT_NOT_FOUND` is added to `FieldReasonCode` and to the §5 error vocabulary. A consumer with
an exhaustive switch must handle it; the repository's Zod boundary and TypeScript discriminated
unions make that a compile-time obligation rather than a runtime surprise.

### 6.2 Affected C3–C6 surface

| | |
|---|---|
| **`CandidateDetail`** | `downstream_refs.trade` re-labelled `trade`. Visible as a changed reference badge on `/signals/candidates/[candidateId]` |
| **`TradeDetail`** | **no change.** Its `EMBEDDED` declarations for `add`, `exit`, `execution_quality`, `chart_series` and `benchmark_series` become correct under R4, and `brain_decision_ref` stays `ENDPOINT` / `UNRESOLVABLE_V1` under R5 |
| **the envelope's `source_refs`** | declared cardinality reconciled with R7. Its empty list stays legitimate; its `total` must stop asserting an `AVAILABLE` zero against a `ONE_OR_MORE` relation |
| **`ExecutiveOverview`, `RiskSnapshot`, `ShortSideSnapshot`, `ReconciliationStatus`** | kinds assigned by R2 match what the fixtures already emit. No re-labelling |
| **`CandidateIntent` separation** | **unchanged.** No sizing, execution, share count, dollar amount, order type, route or broker identifier is added anywhere by this decision |
| **the ADR-0028 risk, entry, add and fill corrections** | **unchanged.** No risk quantity, R denominator, policy version or stage record is touched |
| **the data-hosting boundary** | **unchanged.** No private locator, broker order id, account id, credential or licensed row becomes expressible through a reference |

### 6.3 Implementation acceptance examples

An implementation of this decision is accepted when each of the following holds. These are the cases
a reviewer should be able to run.

```text
ADMITTED
  ref_kind trade, resolution ENDPOINT, on CandidateDetail.downstream_refs.trade
  ref_kind execution_quality, resolution EMBEDDED, where the response carries execution_quality
  ref_kind brain_decision, resolution ENDPOINT, from TradeDetail where a candidate was journaled
  ref_kind brain_decision, resolution UNRESOLVABLE_V1, where no candidate was journaled
  ref_kind chart_series, resolution EMBEDDED, where the response carries chart_series
  a RefList of kind order declaring ZERO_OR_MORE and carrying zero items

REFUSED
  any ref_kind outside the twenty-seven members
  ref_kind candidate with a resolution outside its permitted set
  resolution EMBEDDED where the response carries no such payload
  resolution UNRESOLVABLE_V1 over a producer this application implements
  a RefList declaring EXACTLY_ONE and carrying two items
  a ONE_OR_MORE RefList carrying zero items and an AVAILABLE total of zero
  a resolved target whose id, kind, environment or provenance differs from the reference
  a malformed reference -- refused at admission, never rendered as an availability state

RENDERED, NOT REFUSED
  a well-formed reference naming nothing        NOT_YET_AVAILABLE + REFERENT_NOT_FOUND
  a reference whose producer does not exist     NOT_IMPLEMENTED   + PRODUCER_NOT_IMPLEMENTED
  a reference this caller may not read          NOT_AUTHORIZED    + CLASSIFICATION_WITHHELD
                                                and the reference stays VISIBLE
  NOT_APPLICABLE keeps its two ADR-0028 routes, and REFERENT_NOT_FOUND is not one of them
```

---

## 7. The bounded implementation follow-up

**This decision implements no runtime behaviour, and none is authorized by it.** The pull request
introducing it changes specification text and governance tests only; no module under `src/`, no
module under `apps/cockpit/src/` and no fixture is changed by it.

On acceptance, **one bounded implementation cycle** would:

```text
close ref_kind to the twenty-seven members, replacing z.string().min(1)
compile the per-kind permitted-resolution sets, and refuse a resolution outside one
enforce EMBEDDED against the response actually being validated
enforce cardinality under R7, including RefList items and total
re-label CandidateDetail.downstream_refs.trade to kind trade
add REFERENT_NOT_FOUND to both closed vocabularies and render its state
assign every catalogue Ref field its R2 kind
```

**It is a separate authorization**, and it is not opened by merging this decision.
**Specification, implementation, research, deployment and execution stay five separate gates.**

---

## 8. What this decision does not do

```text
Brain, scanner, strategy, risk, portfolio and execution engines:  NOT IMPLEMENTED / NOT AUTHORIZED
Cockpit runtime behaviour changed by this decision:               NONE
new src/ or apps/cockpit/src/ modules created:                    NONE
fixtures changed by this decision:                                NONE
production read services, projections, databases, schedulers:     NOT AUTHORIZED
C7 research and feedback interfaces:                              NOT STARTED
C5 completion follow-up:                                          STILL PENDING / NOT AUTHORIZED
dependency or manifest changes:                                   NONE
Blueprint PDF changes:                                            NONE
provider data used:                                               NONE
private artifacts read:                                           NONE
AWS / Terraform operations:                                       NONE
broker, LEAN and IBKR activity:                                   NONE
Run A retry:                                                      NOT AUTHORIZED / NOT RUN
Run B:                                                            NOT AUTHORIZED / NOT RUN
combined assessment:                                              NOT AUTHORIZED / NOT RUN
P1-P9:                                                            UNEVALUATED
G1 / G2:                                                          OPEN / OPEN
provider selected:                                                NONE
backtesting:                                                      NOT STARTED
Phase 3:                                                          NOT COMPLETE
ADR-0005:                                                         PROPOSED
INC-0002:                                                         OPEN
CONTROL:                                                          DEFERRED
live trading:                                                     HARD-DISABLED
```

**ADR-0027, ADR-0028 and ADR-0029 remain ACCEPTED / IN FORCE**, none of their documents is edited by
this decision, and **no gate is closed by it**.
