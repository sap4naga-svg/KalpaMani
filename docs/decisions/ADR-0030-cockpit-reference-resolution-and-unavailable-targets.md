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
kind at all to twenty-five of its own reference-valued fields**, so the closed vocabulary §4.2 names
cannot be enumerated and the §4.3 table cannot be applied to them.

---

## 2. The defects, reproduced from the accepted text

Each finding below is **parsed out of `read-model-contracts.md` and executed**, not read off by
eye. `tests/unit/test_adr_0030_governance.py` carries the parsers and their self-tests.

### 2.1 D1 — twenty-five reference fields carry no `ref_kind`

§4.2 types `Ref.ref_kind` as a **closed `RefKind`**, and §4.3 opens with *"A `_ref` whose resolution
is not in this table is refused at the boundary."* Both rules are unreachable for a reference whose
kind was never assigned, and the accepted §4.5 catalogue leaves **twenty-five** reference-valued
fields without a `kind` declaration — **nineteen** scalar `Ref` fields and **six** `RefList` fields:

```text
scalar Ref, nineteen
  ExecutiveOverview        last_decision.ref            last_scout_run.ref
  TradeLifecycle           events[].correction_of       events[].source_ref
  ReconciliationStatus     position_diffs[].security_ref            order_diffs[].local_ref
  CandidateDetail          downstream_refs.risk_decision            downstream_refs.trade
  RiskSnapshot             initial_planned_risk_open[].trade_ref    decisions[].decision_ref
  ShortSideSnapshot        borrow[].security_ref        borrow[].record_ref
                           blocked_shorts[].candidate_ref
  HypothesisRegistration   lineage.parent_registration  lineage.superseded_by
  QualificationStatus      three separate source_ref fields
  SearchResultPage         results[].ref

RefList, six
  StrategyHealth           transitions[].input_refs     failure_clusters[].evidence_refs
  HypothesisRegistration   lineage.related_registrations            lineage.amendment_chain
  AiContribution           ai_provenance.source_refs
  FeedbackPipeline         stages[].item_refs
```

**The count is of FIELDS, and it is neither of occurrences nor of leaf names.** `source_ref` is one
leaf name and four distinct fields — one on `TradeLifecycle.events[]` and three on
`QualificationStatus` — and each names its own kind. A count of leaf names is **thirteen**, and a
count that reaches only scalar `Ref` fields is **nineteen**; neither is the population the closed
vocabulary has to cover.

**The six `RefList` fields matter most, and an earlier draft of this decision missed all six.** They
sit in `StrategyHealth`, `HypothesisRegistration`, `AiContribution` and `FeedbackPipeline` — which
is precisely the research-and-feedback surface C7 consumes, and precisely the reason this
reconciliation is a C7 prerequisite. A reconciliation that assigned only the scalar fields would
have left the C7 area exactly as unenforceable as it found it. **A regex of the form `:\s*Ref`
never matches `RefList`**, which is how the omission survived; the parser in
`tests/unit/test_adr_0030_governance.py` now matches both and is asserted against the full count.

**Every kind the catalogue does declare explicitly has a §4.3 row.** The gap is not a missing row
for a declared kind; it is that these twenty-five fields declare no kind for a row to be found for.

**An implementation must therefore guess, and two guesses are already wrong in a way a reader can
see.** `CandidateDetail.downstream_refs.trade` is *the trade this candidate became*, and
`RiskSnapshot.initial_planned_risk_open[].trade_ref` is *the trade a planned-risk row belongs to*.
§4.3 has no `trade` row, so C6 emitted **both** as kind `source_fact` — the row §4.3 defines as
*"the recorded fact a projection was built from"* — each with an `ENDPOINT` resolution that
`source_fact`'s own row does not list. A reader of those payloads cannot distinguish the trade a
candidate produced from a provenance record the projection was built out of, and the two are
different facts.

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

**The strongest form of the defect is that one kind is carried by BOTH shapes.** `source_fact` is
`ONE_OR_MORE` in the table and is also carried by four **required scalar `Ref`** fields —
`PositionSnapshot.trade_ref`, `TradeSummary.detail_ref`, `ResearchQueueItem.trigger_ref` and
`GovernancePacket.comparison_ref` — each resolving to at most one target. **No single per-kind value
can describe both shapes**, so the column cannot be the validation input for either. The envelope's
`source_refs` is not even a `RefList`: §3 types it `[ { ref_id, ref_kind, classification } ]`, with
no `cardinality`, no `total` and no `resolution` to reconcile.

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

Eleven rules — R1 to R10, with R4.1 separating the co-location question R4 would otherwise be read
as answering. Each is written to be checkable, and §6.3 gives the acceptance examples an
implementation will be reviewed against.

### R1 — `RefKind` is closed and enumerated

The closed `RefKind` vocabulary has **twenty-seven** members: the twenty-six rows of the accepted
§4.3 table, plus **`trade`**, added here because `CandidateDetail.downstream_refs.trade` and
`RiskSnapshot.initial_planned_risk_open[].trade_ref` both require a reference to a trade and no
accepted row supplies one. A value outside the set is **refused at the boundary**, never rendered
and never coerced.

### R2 — every reference-valued field in the catalogue names its kind

The twenty-five fields of §2.1 are assigned as follows. Each assignment is the kind the field's own
contract text already describes; none invents a relationship the catalogue does not state.

**A kind is a property of the FIELD, not of the field NAME.** The accepted catalogue already gives
one name two kinds — `evidence_refs` is declared `source_fact` on three models, `evidence` on
another, and *"evidence or source_fact"* on a fifth — so a field may declare a kind or a stated
**set** of kinds, and the field's own declaration governs. The `security_ref` reading below is a
statement about those particular fields and about the catalogue's own precedent, and it is not a
global uniqueness rule over names.

| Field | Kind |
|---|---|
| `ExecutiveOverview.last_decision.ref` | `decision` |
| `ExecutiveOverview.last_scout_run.ref` | `research_run` |
| `TradeLifecycle.events[].correction_of` | **the `RefKind` corresponding to the corrected event's `event_kind`**, restricted to the lifecycle-event kinds §4.3 resolves into `TradeLifecycle` — `order`, `fill`, `protection`, `add`, `exit` |
| `TradeLifecycle.events[].source_ref` | `source_fact` |
| `ReconciliationStatus.position_diffs[].security_ref` | `evidence` |
| `ReconciliationStatus.order_diffs[].local_ref` | `order` |
| `CandidateDetail.downstream_refs.risk_decision` | `risk_decision` |
| `CandidateDetail.downstream_refs.trade` | **`trade`** |
| `RiskSnapshot.initial_planned_risk_open[].trade_ref` | **`trade`** |
| `RiskSnapshot.decisions[].decision_ref` | `risk_decision` |
| `ShortSideSnapshot.borrow[].security_ref` | `evidence` |
| `ShortSideSnapshot.borrow[].record_ref` | `evidence` |
| `ShortSideSnapshot.blocked_shorts[].candidate_ref` | `candidate` |
| `HypothesisRegistration.lineage.parent_registration` | `registration` |
| `HypothesisRegistration.lineage.superseded_by` | `registration` |
| `HypothesisRegistration.lineage.related_registrations` | `registration` |
| `HypothesisRegistration.lineage.amendment_chain` | `registration` |
| `StrategyHealth.transitions[].input_refs` | `source_fact` |
| `StrategyHealth.failure_clusters[].evidence_refs` | `evidence` |
| `AiContribution.ai_provenance.source_refs` | `source_fact` |
| `FeedbackPipeline.stages[].item_refs` | `queue_item` |
| `QualificationStatus` — each of three `source_ref` fields | `source_fact` |
| `SearchResultPage.results[].ref` | **any `RefKind`** — a search result names whatever was found, and its resolution is that kind's |

`security_ref` resolves to `evidence` on both fields above because the accepted
`CandidateDetail.security_ref` and `ShortSideSnapshot.borrow[].security_ref` sit beside an already
declared *"required, kind `evidence`"*, and reading one of them differently would put two kinds
behind one contract line.

**`record_ref` is a field of `borrow[]`.** An earlier draft of this decision addressed it as
`ShortSideSnapshot.deterioration[].record_ref`. There is no `deterioration[]` array:
`deterioration` is a `MetricValue` **inside** each `borrow[]` entry, and `record_ref` is a sibling
field of that same entry. The path is corrected rather than the assignment.

### R3 — the Resolution column is a permitted SET, and a reference declares one member of it

`Resolution` stays the closed four-member vocabulary. §4.3's column names **which members a
reference of that kind may declare**, and a reference declaring a member outside its kind's set is
refused at the boundary. Two accepted cells already carry two members, and this rule states what
that means rather than changing it.

### R4 — `EMBEDDED` requires contractual PERMISSION and validated TRUTH, and presence alone authorizes nothing

A response may declare `EMBEDDED` on a reference **only when both** of the following hold. Either one
alone is insufficient, and an earlier draft of this decision required only the second.

```text
PERMISSION   the catalogue authorizes THIS host field to embed THIS target kind, and NAMES
             the carrier field that holds it, and states whether that carrier holds the
             COMPLETE target or a DECLARED PROJECTION of it
TRUTH        the response actually carries that named field, its content validates against
             the declared schema, its identity corresponds to the reference's ref_id under
             R8, and its classification, access scope, environment and provenance are ones
             this response is already authorized to carry
```

**Payload presence alone must never establish authorization.** A rule that reads *"`EMBEDDED` is
true whenever the payload is there"* is satisfied by **putting the payload there**, so it authorizes
any widening a producer chooses to perform and then ratifies it. That is the loophole R5 has to close
by hand for `brain_decision`, and closing it once in R4 is what makes R5 an instance of a rule rather
than an exception to one. **A carrier field the catalogue does not authorize is a widening, and it is
refused whether or not the payload is present.**

**An absent target is never represented by a fabricated embedded payload.** Where a permitted embed
has no target, the reference declares another resolution its kind permits, or the carrying
value-bearing field states the availability of R9. A placeholder, an empty object or a zero-valued
stand-in in a named carrier field is a wrong answer wearing a correct one's shape.

**A declared projection is not the complete target, and the catalogue says which it is.**
`TradeDetail.security_ref` is `EMBEDDED` beside a `security` carrier holding
`{ symbol, display_name }` — a projection, not a complete evidence artefact, and one that carries
no identifier of its own today. Naming the carrier, its shape and its identity correspondence is
assigned to the implementation follow-up in §7, and until a carrier is named that way its embed is
not authorized.

### R4.1 — co-location does not compel `EMBEDDED`, and does not forbid `ENDPOINT`

**A response that carries a payload MAY declare `EMBEDDED`, and MAY instead declare any other
resolution its kind's set permits.** Carrying the payload is not, by itself, a reason to refuse
`ENDPOINT`.

An earlier draft held that the rule *"keeps a producer from declaring `ENDPOINT` beside a payload it
is carrying"*. **That is chosen against, and the reason is that the two statements are not
competing.** `EMBEDDED` tells a reader *you already have this*; `ENDPOINT` tells a reader *the
authoritative record lives here, and here is the catalogued route to it*. Both are true of a response
that carries a projection of a target that is also independently addressable, and the application
already relies on it: `CandidateDetail.downstream_refs.trade` is followed to
`/portfolio/trades/{ref_id}` while the candidate page renders what it holds. **Forbidding
`ENDPOINT` on co-location would destroy the route information, and would force churn on every
reference each time an ADR-0028 additive payload is added beside it.**

`EMBEDDED` is therefore **refused only** when it is not permitted by the catalogue or not true of the
response — never merely because some other resolution was also available.

### R5 — `brain_decision` permits `EMBEDDED`, `ENDPOINT` and `UNRESOLVABLE_V1`

**`EMBEDDED`** only where the catalogue authorizes that host field to carry the journaled decision
status and the response carries it — the case §4.3's target column describes, and which
`CandidateDetail` is the contract for. **`ENDPOINT`** from `TradeDetail` where a candidate was
journaled, resolving by `GET /api/v1/signals/candidates/{candidate_id}`. **`UNRESOLVABLE_V1`** only
where no producer exists for the requested scope, under R6.

This **ratifies the C6 implementation's choice** rather than reversing it: the choice was honest and
the table was wrong to forbid it. `TradeDetail` gains **no** brain-decision field — widening it to
force an `EMBEDDED` declaration would put a Brain payload inside a portfolio read model, and §4.3's
*"resolving a reference is an authorized read, not a widening"* forbids exactly that. Under R4 that
prohibition is now structural rather than a special case: `TradeDetail` is not an authorized carrier
for a `brain_decision`, so adding the payload would not make `EMBEDDED` admissible there.

### R6 — producer existence is SCOPED, and a missing record is not a missing producer

`UNRESOLVABLE_V1` is permitted **only** where no producing subsystem exists **for the requested
environment, provenance and read-model scope**. Three separate things are kept apart:

```text
the producer does not exist for this scope        UNRESOLVABLE_V1 / PRODUCER_NOT_IMPLEMENTED
the producer exists and holds no such record      REFERENT_NOT_FOUND            (R9)
the producer exists and this caller may not read  a scope or classification outcome (R9)
```

**A producer implemented against repository-owned synthetic fixtures exists for `SYNTHETIC`
provenance, and for nothing else.** It establishes **no** `SYSTEM_RECORDED`, `BROKER_REPORTED` or
`BACKTEST_SIMULATED` producer, and it never establishes that the real subsystem exists. **A synthetic
candidate producer is not the Brain**, which stays **NOT IMPLEMENTED / NOT AUTHORIZED**, and a
reference resolving inside the demonstration must not be readable as evidence that a scanner,
strategy, portfolio, risk or execution runtime has been built.

**An implemented producer that lacks one requested record is not producer nonexistence.** A trade
with no journaled candidate is a `REFERENT_NOT_FOUND` against an implemented candidate producer, and
declaring `UNRESOLVABLE_V1` there asserts something false about the subsystem. Declaring
`UNRESOLVABLE_V1` over a producer this application implements **for the requested scope** is refused.

### R7 — six quantities, kept apart, and the HOST FIELD's declaration governs

The single word *cardinality* was doing at least three jobs. Six quantities are separated, and each
rule below names which one it constrains.

```text
1 relation cardinality      how many TARGETS a subject may have in this relation
2 reference-object count    how many Ref objects the field carries
3 resolvable targets        how many of those references resolve for this caller
4 total population          how many targets exist -- a CountValue, with its own state
5 truncation                whether `items` is a page of the population
6 unknown vs verified empty an unenumerable population is NOT an empty one
```

**The host field's own declaration is authoritative for validation**, and the §4.3 Cardinality column
states the kind's **generic** relation rather than the value a validator checks. That is not an
invention: the accepted catalogue already declares cardinality at the field —
`AskAnswer.citations` reads *"required, kind `source_fact` — ONE_OR_MORE, or the answer is not
returned"*.

**A per-kind cardinality cannot be the validation input, because one kind is carried by both shapes.**
`source_fact` is `ONE_OR_MORE` in the table and is carried by four **required scalar `Ref`** fields
— `PositionSnapshot.trade_ref`, `TradeSummary.detail_ref`, `ResearchQueueItem.trigger_ref` and
`GovernancePacket.comparison_ref` — each of which carries exactly one reference resolving to at most
one target. `evidence` is `ZERO_OR_MORE` and is carried by required scalar `security_ref` fields.
Neither field can satisfy a list cardinality, and neither is defective.

```text
a scalar Ref field      carries EXACTLY ONE reference OBJECT, always (quantity 2)
                        and resolves to AT MOST ONE target (quantity 1)
                        required    -> the target exists whenever the subject does
                        conditional -> the target may be absent, and the reference STAYS
a RefList field         carries zero or more reference objects, and its OWN `cardinality`
                        governs; `items`, `total` and `truncated` are checked against it
```

**`source_fact`'s relation cardinality is amended to `ZERO_OR_MORE`.** An envelope whose producer
references no source fact — which every `NOT_IMPLEMENTED` producer in this application legitimately
is — has zero, and that is a true and complete answer. `AskAnswer.citations` keeps its **field-level
`ONE_OR_MORE`**, which is the one place the stronger relation is actually meant, and it keeps its
accepted consequence: without a citation the answer is not returned.

**A verified-empty population is never relabelled unknown.** An earlier draft permitted an empty
`ONE_OR_MORE` list only where `total` was **not** an `AVAILABLE` zero, which requires a producer that
counted its population and found none to stop saying so. **That is refused**: it manufactures unknown
data to satisfy an inherited declaration, and it contradicts ADR-0029's accepted `EMPTY_VERIFIED`
semantics and its legitimate `AVAILABLE` zero. The exception is **deleted**, and the relation is
amended instead — which is the honest instrument.

**What a `RefList` must satisfy.**

```text
truncated = false, total AVAILABLE   items.length == total, and total satisfies the relation
truncated = true,  total AVAILABLE   items.length <= total, and total satisfies the relation
total NOT value-bearing              the relation is NOT asserted satisfied; the count's state
                                     and reason are the whole answer, and no bound is inferred
                                     from items.length, which is a page fact
EXACTLY_ONE, complete, two items     REFUSED
EXACTLY_ONE, complete, zero items    REFUSED
ZERO_OR_MORE, complete, zero items   ADMITTED, and reported EMPTY_VERIFIED / AVAILABLE zero
```

**`items.length` never bounds the relation while `truncated` is true**, because a page is not a
population. This is the same rule ADR-0028 already applies to `total`, applied to cardinality.

**The envelope's `source_refs` is not a `RefList` and nothing about it changes.** §3 types it
`[ { ref_id, ref_kind, classification } ]` — a plain list with **no `cardinality`, no `total`, no
`truncated` and no `resolution`**. An earlier draft instructed producers that its *"`total` must stop
asserting an `AVAILABLE` zero"*; there is no `total` on it to change, and the instruction was not
implementable. With `source_fact` amended to `ZERO_OR_MORE`, an empty `source_refs` is simply
conformant.

### R8 — a reference resolves to its OWN target, and identity is compared like with like

A resolved target must be **of the reference's kind** and must match the reference's `ref_id`
**exactly**, where *the target* means **the target entity**, not the container it was retrieved
through.

**A container identifier is not a target identifier.** `brain_decision` resolves to *"the journaled
decision status inside `CandidateDetail`"* and is retrieved by
`GET /api/v1/signals/candidates/{candidate_id}`. Comparing the reference's `ref_id` against the
**candidate's** id compares a decision to the record that carries it, and would refuse every correct
resolution. **Where a target is nested, the catalogue names the container route AND the in-container
selector**, the comparand is the nested entity's own identifier, and the container's id is not the
comparand. Where the catalogue names no selector, the reference is not resolvable by identity and
must not be declared as though it were.

**No resolver ever substitutes.** No nearest match, no default, no first row, no fallback of any kind
when an identifier is unknown. An unknown identifier resolves to the availability of R9 and never to
a different entity.

**Environment must match. Provenance must match unless the catalogue authorizes otherwise and the
reference says so.** A blanket *"provenance must match the resolving envelope"* is unimplementable
against the accepted catalogue and would refuse two contracts that are working as designed:

```text
QualificationStatus   its three source_ref fields point at TRACKED REPOSITORY AUTHORITY --
                      "each fact read INDEPENDENTLY from tracked repository authority" --
                      which is the whole purpose of the view. Copying the resolving
                      envelope's provenance onto that target would misdescribe it
SearchResultPage      results[] already carry their OWN environment, provenance and
                      classification per row, and `scoping` is "present on every result and
                      never widened server-side". The per-row label IS the contract
```

So: **environment must match the resolving envelope**, always. **Provenance must match, except where
the catalogue explicitly authorizes a cross-provenance reference AND the reference or its result row
carries the target's own provenance label** — in which case the label governs and is displayed.
**Silent provenance mixing stays prohibited**, and an authorized cross-provenance link is never
implicit: an unlabelled target of differing provenance is refused.

### R9 — five unavailable outcomes, kept apart, and each stated WHERE it lands

`FieldReasonCode` gains **`REFERENT_NOT_FOUND`**, and the §5 error vocabulary gains
**`REFERENT_NOT_FOUND`**. The outcomes are then distinct and none is a synonym for another:

| Outcome | Where it lands | Value |
|---|---|---|
| the reference is well formed and names nothing | the resolution attempt, or the value-bearing field the target would fill | §5 error `REFERENT_NOT_FOUND`; or `NOT_YET_AVAILABLE` + `REFERENT_NOT_FOUND` |
| the producing subsystem does not exist for this scope | as above | `NOT_IMPLEMENTED` + `PRODUCER_NOT_IMPLEMENTED`, and the reference may declare `UNRESOLVABLE_V1` |
| the caller lacks the scope the read requires | the resolution attempt | §5 error `SCOPE_MISSING` or `SCOPE_INSUFFICIENT` |
| the caller has the scope and classification withholds the target | the value-bearing field | `NOT_AUTHORIZED` + `CLASSIFICATION_WITHHELD`, and the reference stays **VISIBLE** |
| the reference is malformed, or its kind or resolution is outside its closed set | admission | **refused at admission**, never an availability state |

**A `Ref` carries no availability, and R9 does not pretend it does.** §4.2 types `Ref` as
`{ ref_id, ref_kind, resolution, classification }` — there is **no `availability` field and no
`reason` field on it**. An earlier draft's table implied a bare reference could carry
`NOT_YET_AVAILABLE`, which is not expressible. `REFERENT_NOT_FOUND` therefore appears in exactly two
places: as a **§5 error** returned by an attempt to follow the reference, and as a
**`FieldReasonCode`** on a value-bearing wrapper — a `RecordValue`, `MetricValue` or `CountValue` —
whose value would have been obtained by resolving it. **The reference object itself stays present and
visible**, and is never replaced by a state.

**Scope denial is not classification withholding.** The accepted §5 vocabulary already separates
`SCOPE_MISSING` and `SCOPE_INSUFFICIENT` from `CLASSIFICATION_WITHHELD`, and collapsing a denied read
into the classification code would report a policy decision as a data-sensitivity one. A caller
lacking `risk:read` receives a scope error; a caller holding it whose classification bars the target
receives `CLASSIFICATION_WITHHELD`.

**A known deleted or superseded target is not an unknown one, where the catalogue supports the
distinction.** `AuditEvent.tombstone_of` and `AuditEvent.supersedes` exist precisely so a withdrawn
record stays addressable. Where a tombstone is recorded the reference resolves to it; only where
nothing is recorded is the outcome `REFERENT_NOT_FOUND`.

**`REFERENT_NOT_FOUND` carries `NOT_YET_AVAILABLE`, and never `NOT_APPLICABLE`.** An earlier draft of
this decision placed it under `NOT_APPLICABLE`, and the accepted governance suite refused it:
ADR-0028 established that **`NOT_APPLICABLE` has exactly two routes** and that *"inapplicability is a
property of the subject or of the arithmetic, not a synonym for 'we do not have it'"*. A reference
whose identifier names nothing is exactly *we do not have it* — the question still applies, and the
target is absent. **The accepted invariant was right and the draft was wrong**, so this decision
leaves `NOT_APPLICABLE` at its two routes and **weakens no accepted guard to fit its own prose**.

### R10 — an allowlisted internal ROUTE TEMPLATE, and never a free-form URL

A navigation destination for a reference comes from a **closed allowlist keyed by `RefKind`**. An
unknown or unmapped kind yields **no link**.

**A safe allowlisted route template is not a constructed URL, and the distinction is the whole rule.**
An earlier draft read *"no destination is built from `ref_id` or `ref_kind`"*, which prohibits the
application's existing and correct navigation: the allowlist **is** keyed by `ref_kind`, and the
candidate view links a trade by interpolating `ref_id` into `/portfolio/trades/{ref_id}`. Ordinary
dynamic internal navigation is not the hazard.

```text
PERMITTED   an allowlisted INTERNAL route TEMPLATE selected by RefKind, into which a ref_id
            already validated as SafeId is interpolated as a single ENCODED path segment,
            and nothing else is interpolated
REFUSED     a free-form or absolute URL, any external origin, any destination derived from
            free text, a title, a label or any other untrusted content
REFUSED     a generic resolver, a proxy, an unrestricted fetcher, or any destination for a
            kind the allowlist does not map -- which yields NO LINK, never a guess
```

`Ref.classification` labels the reference; **it is not access or publication authorization**, and a
reference the caller may not follow stays **visible** under R9 so the reader knows something exists
that they may not see.


---

## 5. Alternatives considered

| Alternative | Why not |
|---|---|
| **Enforce §4.3 exactly as written** | jointly unsatisfiable. D2 makes a conformant `TradeDetail` impossible, and D1 leaves twenty-five fields with no row to enforce |
| **Widen `TradeDetail` with a brain-decision payload so `EMBEDDED` becomes true** | puts a Brain payload inside a portfolio read model and contradicts §4.3's *"resolving a reference is an authorized read, not a widening"*. R5 keeps the join a reference |
| **Leave `ref_kind` an open string and document the convention** | §4.2 says closed. An open string is what admitted a trade reference labelled `source_fact` with a resolution its own row does not list |
| **Add a `lifecycle_event` kind for `correction_of`** | a correction corrects an event of a kind the vocabulary already has. A twenty-eighth member would name the same things twice |
| **Treat a multi-valued Resolution cell as an error to be normalised to one value** | two accepted rows carry two members. Normalising would silently drop `UNRESOLVABLE_V1` from the two market-data kinds that most need it |
| **Reuse `UPSTREAM_INPUT_MISSING` for an unknown identifier** | it means an input a producer needed was absent, not that an identifier names nothing. Reusing it would make the two indistinguishable, which is the failure R9 exists to prevent |
| **Bump every `schema_version` to `v2`** | no payload field is removed, renamed or given a new meaning, and §6.1's four deployment constraints hold today. A global bump would invalidate conformant clients for a narrowing. **The reasoning is topological and expires** if any constraint stops holding |
| **Permit `EMBEDDED` wherever the payload is present** | payload presence is something a producer CONTROLS, so the rule would authorize any widening and then ratify it. R4 requires catalogue permission as well as truth |
| **Forbid `ENDPOINT` on a response that carries the payload** | the two statements do not compete: `EMBEDDED` says *you already have it*, `ENDPOINT` says *the authoritative record lives here*. Forbidding it destroys route information and churns every reference an ADR-0028 additive payload lands beside (R4.1) |
| **Keep `source_fact` at `ONE_OR_MORE` and let an empty list declare an unknown total** | it requires a producer that counted its population and found none to stop saying so. That manufactures unknown data and contradicts ADR-0029's `EMPTY_VERIFIED`. R7 amends the relation instead |
| **Require a resolved target's provenance to equal the resolving envelope's** | refuses `QualificationStatus`, whose whole purpose is referencing tracked repository authority, and `SearchResultPage`, whose rows already carry their own provenance. R8 authorizes labelled, catalogue-permitted cross-provenance links only |

---

## 6. Compatibility, versioning and acceptance examples

### 6.1 Compatibility

**No `schema_version` is bumped, and the reason is the deployment topology rather than the shape of
the change.**

**Two arguments are explicitly NOT relied on.** *"No field is removed or renamed"* is insufficient:
this decision **narrows** two admitted value sets, and a narrowing rejects payloads a prior validator
accepted. *"TypeScript makes it a compile-time obligation"* is insufficient too: a compiler checks
only code recompiled from this tree, and it says nothing about a validator, a stored example or a
cached response produced earlier.

**What the change actually does to a consumer.**

| Change | Direction | Effect on an older consumer |
|---|---|---|
| `RefKind` closed to twenty-seven members | **narrowing** of what a producer may emit | none, once producers conform; a producer emitting anything else is refused |
| per-kind permitted resolution sets enforced | **narrowing** | none, once producers conform |
| `REFERENT_NOT_FOUND` added to `FieldReasonCode` | **widening** of what a producer may emit | **an older validator compiled against the previous closed set REJECTS it** |
| `REFERENT_NOT_FOUND` added to the §5 error vocabulary | **widening** | as above |
| `source_fact` relation amended to `ZERO_OR_MORE` | **widening** of the relation | none; it admits what the envelope already emits |
| `downstream_refs.trade` and `initial_planned_risk_open[].trade_ref` re-labelled `trade` | **correction of non-conformant output** | a consumer switching on `source_fact` for those fields stops matching |

**A closed-vocabulary addition is a breaking change for an unrecompiled validator, and that is stated
rather than argued away.** It is safe here **only** because of four constraints that hold today:

```text
1  ONE local application. Producer (fixtures), contracts and consumers live in this tree
   and are replaced ATOMICALLY in one commit
2  NO independently deployed or third-party consumer exists, and no schema artifact is
   published, exported or vendored anywhere outside this repository
3  NO persisted response cache, stored wire example, recorded fixture snapshot or golden
   payload survives the change -- every payload is constructed at run time from fixtures
4  NO real producer exists. Provenance is SYNTHETIC throughout, so there is no recorded
   history of emitted payloads to stay compatible with
```

**This reasoning expires, and it says so.** The moment any one of those four stops holding -- a real
producer, a second deployable, a published schema, or a stored payload -- **a coordinated replacement
is no longer available and the change requires a `schema_version` bump**. The implementation
follow-up in §7 is required to re-check all four before it lands, and to bump rather than proceed if
any has changed.

**Stale readers, caches and examples.** Because constraint 3 holds, there is nothing to invalidate:
no response is persisted between runs, and the build output is regenerated from the same tree. The
implementation follow-up must nonetheless land contract, fixture and consumer changes in a **single**
commit, so no intermediate state exists in which a narrowed validator meets an un-relabelled fixture.

**Two emitted values change, and neither was ever contractual.**
`CandidateDetail.downstream_refs.trade` and `RiskSnapshot.initial_planned_risk_open[].trade_ref` both
move from kind `source_fact` to kind `trade`. The accepted contract never authorized `source_fact` on
either -- the kind was unassigned and the implementation guessed the same way twice -- so this
corrects non-conformant values rather than changing a contract. An earlier draft of this decision
recorded only the first of the two.

### 6.2 Affected C3-C6 surface

| | |
|---|---|
| **`CandidateDetail`** | `downstream_refs.trade` re-labelled `trade`, and its `ENDPOINT` becomes conformant because the `trade` row lists it. Visible as a changed reference badge on `/signals/candidates/[candidateId]` |
| **`RiskSnapshot`** | `initial_planned_risk_open[].trade_ref` re-labelled `trade`. **This is a second re-labelling**, and an earlier draft asserted `RiskSnapshot` needed none |
| **`TradeDetail`** | `brain_decision_ref` stays `ENDPOINT` / `UNRESOLVABLE_V1` under R5. Its `add`, `exit`, `execution_quality`, `chart_series` and `benchmark_series` declarations become correct **once the catalogue names each carrier field** under R4; until then they are permitted output the follow-up must authorize explicitly rather than tolerate |
| **every `EMBEDDED` `security_ref`** | in `TradeDetail`, `PositionSnapshot`, `RiskSnapshot` and `CandidateDetail` the `security` carrier is a `symbol` plus `display_name` **projection with no identifier**. R4 requires the catalogue to name the carrier, declare it a projection, and state identity correspondence. **Assigned to the follow-up**, and it is a real item rather than a formality |
| **every default-resolution `demoRef`** | `demoRef` defaults `resolution` to `UNRESOLVABLE_V1`. Under R6 that is refused wherever the producer **is** implemented for `SYNTHETIC` provenance and only the record is absent, which is `REFERENT_NOT_FOUND` instead. The follow-up must audit each default call site rather than assume the default is right |
| **the envelope's `source_refs`** | **unchanged.** It is a plain list with no `cardinality` and no `total`; with `source_fact` amended to `ZERO_OR_MORE` its empty list is simply conformant |
| **`ExecutiveOverview`, `ShortSideSnapshot`** | kinds assigned by R2 match what the fixtures already emit -- `decision`, `research_run`, `evidence`, `candidate`. No re-labelling |
| **`ReconciliationStatus`** | `position_diffs[]` and `order_diffs[]` are **not implemented** as models or fixtures, so nothing is re-labelled. That is absence, not conformance |
| **`StrategyHealth`, `HypothesisRegistration`, `AiContribution`, `FeedbackPipeline`** | the six `RefList` assignments are **specification-only** today; none of these payloads is implemented, and C7 is the cycle that would first emit them |
| **`CandidateIntent` separation** | **unchanged.** No sizing, execution, share count, dollar amount, order type, route or broker identifier is added anywhere by this decision |
| **the ADR-0028 risk, entry, add and fill corrections** | **unchanged.** No risk quantity, R denominator, policy version or stage record is touched |
| **the data-hosting boundary** | **unchanged.** No private locator, broker order id, account id, credential or licensed row becomes expressible through a reference |

### 6.3 Implementation acceptance examples

An implementation of this decision is accepted when each of the following holds. These are the cases
a reviewer should be able to run.

```text
ADMITTED
  ref_kind trade, resolution ENDPOINT, on CandidateDetail.downstream_refs.trade
  ref_kind trade, resolution ENDPOINT, on RiskSnapshot.initial_planned_risk_open[].trade_ref
  ref_kind execution_quality, resolution EMBEDDED, where the catalogue names TradeDetail an
      authorized carrier AND the response carries that named field
  ref_kind trade, resolution ENDPOINT, on a response that ALSO carries a trade projection --
      co-location neither compels EMBEDDED nor forbids ENDPOINT (R4.1)
  ref_kind brain_decision, resolution ENDPOINT, from TradeDetail where a candidate was journaled
  a RefList of kind order declaring ZERO_OR_MORE, complete, carrying zero items, reporting
      EMPTY_VERIFIED with an AVAILABLE total of zero
  a RefList declaring ZERO_OR_MORE with truncated true, items.length 20 and an AVAILABLE
      total of 137
  a QualificationStatus source_ref whose target is tracked repository authority of a
      DIFFERENT provenance, explicitly labelled and catalogue-authorized (R8)

REFUSED
  any ref_kind outside the twenty-seven members
  ref_kind candidate with a resolution outside its permitted set
  resolution EMBEDDED where the response carries no such payload
  resolution EMBEDDED where the response DOES carry the payload but the catalogue does not
      authorize that host field to embed that kind -- presence is not permission (R4)
  a brain-decision payload added to TradeDetail in order to make EMBEDDED true (R4, R5)
  resolution UNRESOLVABLE_V1 over a producer implemented for the requested scope where only
      the record is absent -- that is REFERENT_NOT_FOUND (R6)
  a synthetic producer's existence offered as evidence that the real subsystem exists (R6)
  a RefList declaring EXACTLY_ONE and carrying two items when complete
  a ONE_OR_MORE RefList relabelling a VERIFIED-EMPTY population as unknown in order to
      satisfy its declaration (R7)
  a relation asserted satisfied from items.length while truncated is true (R7)
  a resolved target whose id or kind differs from the reference
  a resolved target compared against its CONTAINER's id rather than its own (R8)
  a cross-provenance target that is neither catalogue-authorized nor explicitly labelled (R8)
  a navigation destination that is a free-form or external URL, or derived from free text (R10)
  a malformed reference -- refused at admission, never rendered as an availability state

RENDERED, NOT REFUSED
  a well-formed reference naming nothing        NOT_YET_AVAILABLE + REFERENT_NOT_FOUND on the
                                                value-bearing field, or the section 5 error on
                                                the resolution attempt -- never on the bare Ref,
                                                which carries no availability (R9)
  a reference whose producer does not exist     NOT_IMPLEMENTED   + PRODUCER_NOT_IMPLEMENTED
  a read the caller lacks the scope for         SCOPE_MISSING or SCOPE_INSUFFICIENT, and
                                                NEVER CLASSIFICATION_WITHHELD (R9)
  a target withheld by classification           NOT_AUTHORIZED    + CLASSIFICATION_WITHHELD
                                                and the reference stays VISIBLE
  a recorded tombstone                          resolves to the tombstone, not REFERENT_NOT_FOUND
  NOT_APPLICABLE keeps its two ADR-0028 routes, and REFERENT_NOT_FOUND is not one of them
```

## 7. The bounded implementation follow-up

**This decision implements no runtime behaviour, and none is authorized by it.** The pull request
introducing it changes specification text and governance tests only; no module under `src/`, no
module under `apps/cockpit/src/` and no fixture is changed by it.

On acceptance, **one bounded implementation cycle** would:

```text
re-check the four §6.1 deployment constraints, and BUMP rather than proceed if any changed
close ref_kind to the twenty-seven members, replacing z.string().min(1)
compile the per-kind permitted-resolution sets, and refuse a resolution outside one
name, per host field, which target kinds it may EMBED and which carrier field holds them,
    and whether each carrier is the complete target or a declared projection (R4)
state identity correspondence for every projection carrier, including the identifier-less
    `security` projection every EMBEDDED security_ref currently sits beside
enforce EMBEDDED against BOTH catalogue permission and the response being validated
enforce cardinality under R7 from the HOST FIELD's declaration, with items, total and
    truncated kept apart, and never inferring a relation from a page
amend the source_fact relation to ZERO_OR_MORE, keeping AskAnswer.citations at ONE_OR_MORE
re-label CandidateDetail.downstream_refs.trade AND
    RiskSnapshot.initial_planned_risk_open[].trade_ref to kind trade
audit every demoRef call site that takes the UNRESOLVABLE_V1 default, and replace each one
    that names an implemented synthetic producer with a REFERENT_NOT_FOUND outcome (R6)
add REFERENT_NOT_FOUND to both closed vocabularies, and render it on the value-bearing
    field or as a §5 error -- never on the bare Ref, which carries no availability (R9)
keep scope denial (SCOPE_MISSING / SCOPE_INSUFFICIENT) distinct from CLASSIFICATION_WITHHELD
assign every catalogue reference field its R2 kind, RefList fields included
land contract, fixture and consumer changes in a SINGLE commit (§6.1)
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
