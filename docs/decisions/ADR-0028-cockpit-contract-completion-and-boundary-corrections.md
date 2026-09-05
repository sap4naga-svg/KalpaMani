# ADR-0028 — Cockpit contract completion, and four boundary corrections

**Status: PROPOSED — NOT IN FORCE. No authority until PR #72, the pull request introducing this
ADR, is independently reviewed and merged.**

While PR #72 is open, ADR-0028 is proposed and carries no authority,
and so are the corrections it makes to the Cockpit specifications in the same pull request. That is
a statement about the present, it will remain true of these days after any later merge, and it is
not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **corrected contracts, corrected boundaries and governance** —
and nothing else.

**The acceptance event is exact:** the independent review and merge of **PR #72** into `main`. No merge SHA and no merge timestamp is predicted here; those are repository
state, recorded after the fact if they are recorded at all.

**Date:** 2026-09-05
**Supersedes:** nothing
**Superseded by:** —
**Amends:** the specifications
[ADR-0027](ADR-0027-cockpit-and-feedback-architecture-and-governance.md) adopted, at the exact
clauses listed in §3. **It does not amend, supersede or edit ADR-0027 itself.**
**Relates to:** [ADR-0005](ADR-0005-point-in-time-data-architecture.md),
[ADR-0006](ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md),
[ADR-0007](ADR-0007-cloud-first-research-data-plane.md),
[ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md),
[ADR-0026](ADR-0026-strategy-brain-architecture-and-governance.md),
[ADR-0027](ADR-0027-cockpit-and-feedback-architecture-and-governance.md)

**Nothing was run to produce this decision.** No AWS, STS, SSO, IAM, Secrets Manager or S3 call; no
Terraform command of any kind; no Terraform state, backend configuration, `.tfvars` or `.terraform/`
read; no `.runtime/` inspection; no provider request; no credential access; no Run A retry, Run B or
combined assessment; no P1–P9 execution; no backtest; and no broker, LEAN or IBKR activity. **No
Blueprint PDF was opened or edited.** No dependency was installed, no package manifest was changed,
and no application was scaffolded. This decision is authored from tracked repository authority
alone.

**No alpha is claimed anywhere in this decision.**

---

## 1. Context

**ADR-0027 is ACCEPTED / IN FORCE.** It was accepted by the independent review and merge of
**PR #71** into `main` — merged **2026-09-05T16:02:48Z**, merge commit
**`751bf759fd6516149421a99ebf6c2c997c6c6766`**, final reviewed pull-request head
**`2eecade03c8c74265507bf9c030e7986e5ff3931`**. **Its conditional acceptance event has occurred**,
and the conditional status text ADR-0027 was written with is preserved as the record of the days
before that merge rather than rewritten. **This decision does not revert, reopen or restate
ADR-0027 as proposed.**

**This decision exists because four issues in those accepted specifications were identified and were
not resolved.** They are not editorial. Each one either leaves a contract unbuildable, or lets a
later implementation reach a wrong conclusion while obeying the text.

**Four further defects were found by the independent review of PR #72, and are corrected in the
same pull request.** They are recorded in §2.5 rather than in a separate decision, because they are
defects in *these* corrections rather than in the accepted package: an availability value and a
reason code that were spelled in each other's vocabularies, a required nested record with no way to
be unavailable, a basis-point figure that was never multiplied into basis points, and a freshness
number that measured when a projection was built rather than how old its facts were.

### 1.1 The read-model contracts stopped short of being implementable

[`read-model-contracts.md`](../cockpit/read-model-contracts.md) §4.1 was titled *Selected payload
shapes* and said that **full field-level definitions belong to the implementation cycle**. Two
payloads were sketched and the remaining catalogued read models had none. Fields were typed as
`metric-defined` with no resolvable definition; every `_ref` was named and none stated how it
resolves; endpoints declared neither response type, nor filters, nor sorts, nor page sizes, nor
extent bounds, nor cursor semantics, nor error codes; and four catalogued endpoints —
what-changed, candidates, search and ask — resolved to no read model at all.

**A deferral is not a contract.** ADR-0027 states that its contracts are *implementation-reviewable*
and that a reviewer should be able to tell whether a build matches. **Against a deferral, no
reviewer can**, and the first implementation cycle would have made every one of those decisions
inside a feature pull request — which is the failure ADR-0027 §8 rejects for the technology stack
and accidentally permitted for the contracts.

### 1.2 A new registration made exposed out-of-sample data untouched again

[`feedback-self-maturation-specification.md`](../cockpit/feedback-self-maturation-specification.md)
§2.7 required that out-of-sample data be *consumed once per registration*, and that a second
evaluation against the same locked set *requires a new registration*.

**Re-registration is free.** Under that rule a researcher — or an automated research loop — reaches
a fresh out-of-sample claim over already-exposed data by producing a new hypothesis identity, a new
registration identity or a new Challenger identity. **The trial budget and the multiple-testing
record reset with it.** A multiple-testing control whose denominator a rename resets is not a
control, which is the exact failure §2.7 was written to prevent.

### 1.3 Classification contradicted itself, and a label was doing a gate's job

Three statements in the accepted package could not all hold.

| | |
|---|---|
| the classification vocabulary | admits `LICENSED_DERIVED` as a legitimate class **inside** the approved private deployment boundary |
| `read-model-contracts.md` §10 | listed a *vendor row or reconstructable derivative of one* alongside credentials and infrastructure identifiers as **never** placed in **a read model**, without qualification |
| `PUBLIC_EDGE` | admitted `PUBLIC_SAFE` with **`SYNTHETIC` provenance only** — while `QualificationStatus` is `AVAILABLE`, `PUBLIC_SAFE`, and composed of **real** tracked repository governance facts |

So a qualified, authorized private price projection was simultaneously a legitimate
`LICENSED_DERIVED` read model and a forbidden one; and the one read model whose inputs are real
either could not be displayed on an externally hosted deployment, or had to be relabelled
`SYNTHETIC`, **which would be false**.

Underneath both is one conflation: **classification is a sensitivity label and publication is an
authorization**, and the package used the label to answer both questions. A `PUBLIC_SAFE` marking
was, in effect, a publication permission.

The audit and deletion reconciliation had a smaller version of the same gap: it required that
governance evidence survive deletion, without stating that a deletion or a correction **appends a
linked event** rather than mutating the original — and immutability that permits in-place redaction
is not immutability.

### 1.4 One phrase, "planned risk", was doing four jobs

*Planned risk* appeared as an Executive Overview tile (**open** planned risk), as a per-position
field, as a Risk Dashboard heading (*planned and permitted risk*), and as the R-multiple
denominator (**initial** planned risk). §12 then defined a single `Planned risk` metric as *the
deterministic risk the position was opened with*, which is the **initial** quantity — leaving the
tile labelled *open planned risk* with no definition of its own.

The consequences are concrete: a screen could show a current assessment under a label whose defined
meaning is an entry-time record; a trailing stop could plausibly be read as moving the R
denominator; an aggregate could double-count an add; permitted limits sat beside carried risk with
no policy reference; and §12's `R multiple` row required `NOT_APPLICABLE` when initial planned risk
is unavailable — **reporting that the question does not apply when the truth is that nobody
answered it.**

---

## 2. Decision

**Correct all four, in the specifications ADR-0027 adopted, and record the corrections here.**

### 2.1 Complete the read-model contracts

**Replace the §4.1 deferral with declarative, reviewable contracts.** `read-model-contracts.md` now
carries, for every catalogued read model:

```text
field-level contracts     type, unit, requiredness and absence behaviour for every field
reusable defined types    one definition each, used everywhere, redefined nowhere
per-field availability    a closed FieldReasonCode beside every nullable value
identity and ownership    the identity of the row, and the subsystem that owns it
references                every _ref with its resolution, cardinality and required scope
pins and classification   version pins, classification, provenance and access scope
freshness and coverage    the contract each row is measured against, and its invariants
examples                  two shared templates -- synthetic, and unavailable
```

**Four read models are added** for endpoints that had none — `WhatChangedEntry`, `CandidateSummary`,
`SearchResultPage` and `AskAnswer` — so **every endpoint resolves to a read model and every read
model has a contract.**

**Every endpoint declares its response type, its filters, its sorts, its default and maximum page
size, its extent bound, its cursor and snapshot semantics and its closed error codes.** The page
sizes and extent bounds are **proposed read-resource limits** that bound a read API's work and
response size. **They are not trading risk limits, position limits, capital limits or any other
governed value**, and adopting one here adopts nothing anywhere else. **Where a bound must come from
a separately governed policy, the contract requires that policy's versioned reference and refuses
with `POLICY_REFERENCE_MISSING` when it is absent** rather than serving under an unapproved default.

**The metric dictionary is completed**: each metric carries a formula or an unambiguous rule, its
unit and named denominator, its calendar and timezone basis, its cost treatment, its sign
convention, its sample convention, its minimum-observation rule and its unavailable outcome. The
hard cases are decided — external cash flows and cash-flow-adjusted return and drawdown, benchmark
alignment and price-versus-total return, expectancy, profit factor, win rate and Sharpe, partial
fills, partial exits, adds and pyramids, MFE, MAE and capture ratio in compatible units, slippage
and latency. **`metric-defined` no longer appears anywhere**, and **`return.naive` is not defined
and not offered.**

**Costs already realized in a fill are not subtracted twice.** An actual fill price already
incorporates the spread crossed and the slippage realized; `slippage` measures that fill against a
named reference and is never deducted from the same fill's economics again, and **no modelled spread
or slippage estimate is applied on top of an actual fill.** A hypothetical outcome has no actual
fill, states its modelled assumptions, and **is never placed in a series with realized results.**

**Display sufficiency is not evidence of strategy validity**, and the dictionary says so in its own
words. A metric that satisfies every rule here is a computed number, not a validated edge.

### 2.2 Close cross-registration out-of-sample reuse

**Exposure is recorded against the locked set, not against a registration.** Every locked set has an
identity derived from its manifest, profile, revision view and evaluation boundary, and an
**append-only exposure ledger** attached to it. Every evaluation appends an entry naming the
registration, the Challenger, the research code and configuration identity, the evaluation class,
the instant, the requested extent and its overlap with prior entries.

**A new hypothesis, registration or Challenger identity does not make exposed data untouched.**
Exposure is inherited through the parent registration, the amendment chain, a superseded or
superseding registration, a shared named baseline, a shared queue trigger or failure cluster, and a
shared Challenger derivation. **Trial budgets and multiple-testing records are read across that
lineage, so renaming resets neither.**

**Unknown exposure history cannot support a fresh out-of-sample claim.** An incomplete or
unresolvable ledger is `EXPOSURE_HISTORY_UNKNOWN` and a confirmatory evaluation is refused. **An
absence of recorded exposure is never read as evidence of absent exposure.**

**Three evaluation classes, and only one is confirmation.**

| | |
|---|---|
| `DETERMINISTIC_REPRODUCTION` | re-executing a frozen run at its exact pins and seeds. **No new confirmation of anything**, no trial-budget consumption |
| `EXPLORATORY_REUSE` | any further look at exposed data. **Disclosed, never fresh out-of-sample**, consumes budget, and the disclosure travels into every packet and comparison |
| `CONFIRMATORY` | eligible **only** against an untouched holdout, new forward evidence, or a separately governed methodology that accounts for the reuse |

**Preregistration stays immutable, failed and abandoned trials stay retained and still count**, and
governance-packet evidence and refusal contracts now carry the evaluation class and the exposure
disclosure. **A new identity reusing an exposed holdout is refused with
`OUT_OF_SAMPLE_ALREADY_CONSUMED`**, and that negative control is a required test.

### 2.3 Reconcile licensed-data admission, and separate the label from the gate

**Two lists, governed differently.**

| | |
|---|---|
| **credentials and infrastructure identifiers** | **never** in a read model, URL, cache key, export, log line or chart label — at any classification, in any environment, on any host, under any authorization |
| **classified payload content** | a vendor row and any reconstructable derivative is **classified**, not forbidden. `LICENSED_DERIVED` inside the approved private boundary is **legitimate**; `PUBLIC_SAFE` and `PRIVATE_OPERATIONAL` payloads carry none; outside the boundary, never; **uncertain is treated as licensed and refused rather than downgraded** |

**A qualified, authorized private price projection is licensed-derived and belongs inside the
boundary.** Licensed-derived is not a defect; publishing it is.

**Classification is a sensitivity label; publication is a separate recorded authorization.** A
`PUBLIC_SAFE` label states what the content is. **It does not bypass a required release
authorization**, and a payload with a correct label and no authorization is refused rather than
published.

**One provenance member is added: `REPOSITORY_TRACKED`** — a real fact read from tracked repository
authority. This is an explicit, reviewed extension of a closed vocabulary, taken through an ADR
exactly as `read-model-contracts.md` §2 requires. **It exists so that real governance facts are
never relabelled `SYNTHETIC` to satisfy a hosting rule.**

**`PUBLIC_EDGE` now admits `PUBLIC_SAFE` payloads with `SYNTHETIC` or `REPOSITORY_TRACKED`
provenance only**, and `REPOSITORY_TRACKED` only from the enumerated governance read models —
`QualificationStatus`, and the governance-derived entries of `AttentionItem`, `WhatChangedEntry`,
`SearchResultPage` and `MaturityStatus` — whose facts already resolve to tracked sources published
in this public repository, and only under a recorded release authorization.
**`SYSTEM_RECORDED`, `BACKTEST_SIMULATED` and `BROKER_REPORTED` are never admitted to an externally
hosted deployment.**

**Everything already forbidden stays forbidden.** The Cockpit and its API proxy reach no provider,
no broker and no secret; real feed access remains separately authorized; licensed and reconstructable
content stays inside its approved boundary and enters no public Git, external LLM, third-party
hosting, external cache, telemetry, build artifact or ordinary log; **an SSR, proxy, build or cache
path on an externally hosted deployment cannot bypass the private boundary**; `UNCLASSIFIED` fails
closed; and **CONTROL publication remains DEFERRED and refused at admission.**

**Immutable audit and deletable licensed data are reconciled by appending.** An audit event carries
permitted evidence and classified references, **never a copy of deletable licensed content**. A
correction appends a **new** linked event naming what it supersedes; a deletion appends a **new**
linked tombstone carrying its recorded deletion authority; **the original event is never mutated,
redacted in place or overwritten.** An authorized cached copy carries the same destruction
obligation as its source. **This decision states that obligation, implements no deletion, and grants
no operational authority** — the deletion path and its runbook are unchanged, and **deletion never
depends on a locator, a projection or an audit event to discover licensed objects.**

### 2.4 Separate initial risk from current risk

**Four quantities, kept apart, with a contract each.**

| | |
|---|---|
| `InitialPlannedRisk` | the **immutable** entry-time record, and **the only denominator an R multiple may use** |
| `CurrentOpenPlannedRisk` | the risk engine's assessment of the **remaining** exposure, meaningless without its as-of, carrying its policy and source pins and a `FRESH` / `STALE` / `MISSING` state |
| `PermittedRisk` | a separately governed policy value, carried with its `PolicyRef`, and **`POLICY_REFERENCE_MISSING` rather than a number when the reference is absent** |
| `GapEventRisk` | a separately modelled scenario, never folded into either planned-risk figure |

**A moving stop cannot silently move the R denominator.** A protective-order change, a partial exit
and a size change each move the current quantity and leave the entry record untouched. **Each add
carries its own initial planned risk record and the earlier records are retained unchanged**; the
trade-level R denominator is the sum of the retained per-stage records, and a trade whose stages
carry different risk-policy versions displays every contributing version.

**Partial fills, partial exits, adds, protection changes, closed versus remaining exposure, stale
assessments, missing assessments and aggregation are each decided.** Aggregation sums the current
quantity over open exposure **once per position**, an aggregate with a stale or missing component is
`PARTIAL` with its components named, and **an add is never counted twice.**

**Missing initial planned risk is unavailable, not inapplicable.** `NOT_APPLICABLE` has **exactly
two** routes — `NOT_DEFINED_FOR_SUBJECT`, where the subject has no such property, and
`DENOMINATOR_ZERO`, where the arithmetic is undefined — and **`UPSTREAM_INPUT_MISSING` reaches
neither**. **Everything merely absent is unavailable, with the state and the reason code that say
why.**

**A record that can be unavailable is carried in a wrapper, not declared required and left
unfillable.** Every one of the four quantities is a `RecordValue`, so an absent record is *absent*
rather than a skeleton carrying an invented timestamp, a synthesised policy identifier or a zeroed
amount. §2.5 records that correction.

**The Cockpit displays these facts and invents no trading permission.** Showing a limit is not
granting it, showing headroom is not authorizing its use, and no view computes a permitted exposure.

### 2.5 Four corrections from the independent review of PR #72

**These are defects in the corrections above, found by the review of this pull request and fixed in
it.** They are recorded here so the semantic change is discoverable rather than buried in a diff.

#### 2.5.1 Availability and reason are two axes, and one validity matrix governs both

**They were being spelled in each other's vocabularies.** `UPSTREAM_INPUT_MISSING` — a
`FieldReasonCode` — was written where an `AvailabilityState` belongs, in §4.1's own rule, in the
missing-initial-risk contract and in eight metric rows; and `UNKNOWN`, a `completeness` value, was
written as the `coverage` metric's availability outcome. **A consumer switching on availability
would have found values that are not in the enum.**

**`read-model-contracts.md` §4.1.1 now carries one exhaustive validity matrix** over the
availability state, the permitted reason codes and whether a value is present. `AVAILABLE`,
`STALE`, `PARTIAL` and `EMPTY_VERIFIED` are **value-bearing**; the rest are absences.
`EMPTY_VERIFIED` is named as **the only state in which a zero is a correct answer**.

**A successful value no longer needs a fabricated failure reason.** `reason` is required on every
`MetricValue`, including a good one, and there was no member meaning *nothing is wrong* — so a
producer had to pick a failure. **`NONE` is added, and is the only reason `AVAILABLE` admits.**

**`NOT_APPLICABLE` has two routes and not one.** The package required `NOT_APPLICABLE` with
`DENOMINATOR_ZERO` for `profit_factor` and `capture_ratio` while also stating that
`NOT_DEFINED_FOR_SUBJECT` was the only route — **both could not hold**. Subject inapplicability and
undefined arithmetic are now two named routes, and **nothing else reaches `NOT_APPLICABLE`**.

**`FieldReasonCode` gains six members**, taken through this ADR exactly as a closed vocabulary
requires: `NONE`, `EMPTY_RESULT_VERIFIED`, `EXTENT_PARTIALLY_COVERED`, `EXTENT_NOT_DETERMINABLE`,
`NOT_YET_ASSESSED` and, for §2.5.4, `SOURCE_TIMESTAMP_MISSING` and `CLOCK_UNSYNCHRONIZED`.
**`AvailabilityState` gains nothing**, and no member of either vocabulary is removed or renamed.

#### 2.5.2 A required nested record needs a way to be unavailable

**`InitialPlannedRisk` was declared `required` with every field concrete and required** — money, a
reference price, an invalidation reference, a `recorded_at`, a `PolicyRef` and a source enum — while
the same section said initial risk may be `NOT_YET_AVAILABLE`. **There was no shape for the
unavailable case**, so an implementation would have invented one: a zeroed amount, a synthesised
policy identifier, or the response's own timestamp standing in for a source time that does not
exist.

**`RecordValue` is added to §4.2 and applied to all four risk quantities**, and to every payload
that carries them. The record is present exactly when the state is value-bearing and **`ABSENT`
otherwise — never a skeleton, never a placeholder, never a zeroed record**. `CurrentOpenPlannedRisk`
keeps `staleness` for a **present** assessment and `MISSING` moves to the wrapper, because a missing
assessment has no `as_of` and no `assessment_ref` to report.

**An absent source time is not the response's time.** `as_of_time` and `projected_time` belong to
the response and are always known; a record's own `recorded_at` belongs to the source fact, and when
the fact does not exist neither does its time. **§4.4.1 writes out six payloads** — available
initial risk, not-yet-available during entry filling, missing historical evidence, missing current
assessment, missing policy reference, and a partially available composite — so the shapes are
satisfiable rather than described.

#### 2.5.3 Slippage is basis points, and its sign says which way

**The formula produced a ratio and labelled it `BPS`.** `signed(fill − reference) / reference` is
out by a factor of 10,000, and `signed` was never defined, so the side convention the row referred
to did not exist anywhere.

```text
slippage_bps = side_sign * (fill_price - reference_price) / reference_price * 10,000
side_sign    +1 for every buy (open and cover)   -1 for every sell (close and open)
positive     ADVERSE COST        negative  FAVOURABLE FILL
```

**Positive is adverse cost, for both sides.** A buy at 100.10 against a 100.00 reference and a sell
at 99.90 against the same reference are **each +10 bps**; without `side_sign` a book of equally
adverse buys and sells averages to zero and reports perfect execution. **§12.3.1 works all four
cases through by hand.**

**`Bps` becomes a decimal string with a stated scale, minimum two decimal places**, because
truncating 8.42 to 8 discards four tenths of a basis point on every fill and an aggregate over fifty
thousand fills carries the whole of it. Rounding is **half-even, at the declared scale, on the final
value only**. Aggregation is quantity-weighted with the method named, **fills with no reference are
excluded and counted**, and a zero reference price is `NOT_APPLICABLE` with `DENOMINATOR_ZERO`
rather than a division.

**Nothing is subtracted twice.** §12.4's costs-already-in-the-fill rule is unchanged and governs.

#### 2.5.4 Freshness is the age of the facts, not the age of the build

**`as_of_time − newest contributing projected_time` measures when a machine last ran.** Rebuilding a
projection over week-old source data would have reported it seconds old; a historical `as_of` query
would have produced a **negative** number; and *newest contributing* reports the freshest input
while **concealing an older required one**.

**§3.1 separates six times** — `evaluation_time`, `as_of_time`, `source_effective_time`,
`source_observation_time`, `projected_time` and `source_watermark` — and derives three ages that are
reported separately: **`source_age`** (how old the facts are, and the freshness question),
**`projection_lag`** (how far the build lags its sources) and **`build_age`** (how old the build is,
**and the only one a rebuild resets**).

**Every required input is evaluated against its own contract.** The composite reports the **oldest**
required input by name and takes the **worst** state any required input reached, so **one fresh
input never raises a view carrying a stale one**. Optional inputs are reported and do not set the
composite state.

**Missing and skewed clocks refuse rather than resolve.** An input with no usable source time is
`SOURCE_TIMESTAMP_MISSING` — **its age is unknown, not zero**; a source time later than the
evaluation time beyond tolerance is `CLOCK_UNSYNCHRONIZED`, and **a negative age is never clamped**.
**A cache cannot freeze an `AVAILABLE` state**: a cached response carries the origin's
`evaluation_time` with its report, and an entry lives at most as long as the strictest
`contract_max_age` it carries.

#### 2.5.5 Two smaller corrections, in the same round

**Overlapping data is exposure.** §2.2's ledger was keyed by a locked-set identity derived from
manifest, profile, revision view and boundary — which catches a **repeat** and not a **subset, a
superset, a shifted window or a re-cut**. Evaluating 2015-2019 and then registering 2015-2020 as a
new locked set produced a new identity over four-fifths of the same data. **The lookup is now by
measured overlap**, on the axes a locked set is cut along; **any overlap disqualifies a
`CONFIRMATORY` claim**, there is no threshold below which reuse becomes fresh, and **an unmeasurable
overlap is `EXPOSURE_HISTORY_UNKNOWN`, because incomparable is not disjoint**.

**A flow-free holding period is one valid sub-period.** `return.time_weighted` required **two**
sub-periods, so a perfectly ordinary period containing no external cash flow reported
`INSUFFICIENT_OBSERVATIONS`. The minimum is **one complete sub-period**, each requiring a beginning
and an ending valuation — **the chaining exists to survive cash flows, not to require them**. **No
research restriction is invented to preserve the old number**, and `return.naive` is still not
offered.

---

## 3. Exactly what is amended

**ADR-0027 is not amended, superseded or edited.** Its text, its status line and its historical
record stand. What this decision amends is the **specifications ADR-0027 adopted**, at these clauses
and no others.

| Document | Clauses |
|---|---|
| [`read-model-contracts.md`](../cockpit/read-model-contracts.md) | §2.2 provenance · §2.4 hosting · §3 envelope `freshness`, with new §3.1 · §4 catalog and payload contracts, with new §4.1–§4.6, new §4.1.1 and new §4.4.1 · §5 endpoint contracts, with new §5.1–§5.2 · §7 caching · new §7.1 · §9 partial data · §10 identifiers · §11 audit and deletion · §12 metric dictionary, renumbered to §12.1–§12.6, with new §12.3.1 |
| [`feedback-self-maturation-specification.md`](../cockpit/feedback-self-maturation-specification.md) | §2.5 registration outputs and refusals · §2.7 reuse protections, with new §2.7.1 including the overlap rule of §2.5.5 · §2.9 packet inputs, outputs and refusals |
| [`COCKPIT_FEEDBACK_EXTENSION.md`](../architecture/COCKPIT_FEEDBACK_EXTENSION.md) | §4.3 provenance · §4.5 classification and hosting · new §4.6 · §5 audit and deletion |
| [`cockpit-v1-specification.md`](../cockpit/cockpit-v1-specification.md) | Areas 1, 3, 12, 24, 31 and 36 |
| [`traceability-matrix.md`](../cockpit/traceability-matrix.md) | the acceptance criteria of Areas 1, 3, 12, 15, 18, 24, 31, 33 and 36 |
| [`ui-ux-specification.md`](../cockpit/ui-ux-specification.md) | §5 · new §9.4 |

**No other clause of any of them changes**, and no ADR document is edited by this decision.

---

## 4. What is preserved, unchanged

```text
all 36 product areas stay in V1 scope        the C1-C10 delivery sequence is unchanged
Trade History, Trade Detail, Execution History and Audit Trail stay four separate screens
the Brain ends at CandidateIntent            sizing and execution stay downstream
no sizing or execution field is added to CandidateIntent
the Brain decision vocabulary is consumed unchanged and is not extended
the downstream stage vocabulary stays a separate axis
the runtime Environment enum is unchanged    the ADR-0026 lifecycle is unchanged
the seven strategy health states are unchanged, and so is their recovery authority
V1 stays observational and READ-ONLY is still defined by absence
every future control stays inert, with no executable handler and no control API route
governance screens still originate no authoritative approval record
no risk limit, capital value, leverage setting, sizing rule or stop policy changes
no Blueprint PDF is opened or edited         no source module is created
no dependency is installed                   no application is scaffolded
```

**`CandidateIntent` gains nothing.** The completed contracts join downstream facts by **safe internal
reference**, exactly as ADR-0027 requires, and `CandidateDetail` continues to carry no share count,
dollar amount, position size, order type, route or order identifier.

---

## 5. Alternatives considered

| Alternative | Why it was not chosen |
|---|---|
| **Leave field-level contracts to the implementation cycle** | that is the state being corrected. A contract a reviewer cannot check is not a contract, and the decisions would then be made inside feature pull requests |
| **Keep "a second evaluation requires a new registration"** | a control defeated by a rename. Automated research would reach fresh out-of-sample claims by producing identities |
| **Ban `LICENSED_DERIVED` read models outright** | it would forbid the private projections the private boundary exists to hold, and would make the qualification work unusable by the surface built to observe it |
| **Relabel `QualificationStatus` as `SYNTHETIC` so `PUBLIC_EDGE` admits it** | false. The facts are real and tracked, and a hosting rule is not a reason to misdescribe data |
| **Treat `PUBLIC_SAFE` as sufficient for publication** | it makes a sensitivity label a release authorization, which is how content reaches a public host because someone marked it safe |
| **Redact licensed content out of audit events on deletion** | in-place redaction of an immutable record is not immutability. Appending a tombstone preserves both obligations |
| **Keep one "planned risk" and disambiguate in the UI** | the ambiguity is in the contract, and a label cannot repair a definition. Four facts need four contracts |
| **Recompute initial planned risk from the current stop** | it would make the R denominator drift with a trailing stop, which is the specific error this separation prevents |
| **Report `NOT_APPLICABLE` when initial planned risk is missing** | it asserts that the question does not apply when nobody answered it. Absence is unavailability, with a reason code |
| **Let a successful value carry the least-wrong failure reason** | it is a false report, and it makes every reason code unreadable — a consumer cannot tell a real `UPSTREAM_INPUT_MISSING` from a filler one. `NONE` costs one member |
| **Keep `NOT_DEFINED_FOR_SUBJECT` as the only route and drop the `DENOMINATOR_ZERO` ratio rule** | a zero gross loss is not a subject that lacks the property; the subject has it and the arithmetic is undefined. Merging them would lose the distinction a reader needs |
| **Make the four risk records `optional` instead of wrapping them** | §4.1 already forbids using `optional` to make a missing producer look intentional, and an absent field carries no reason. The wrapper says *why* |
| **Report slippage as a ratio and let the UI multiply** | the unit would live in the presentation layer, two screens would disagree, and the dictionary's own `BPS` declaration would stay wrong |
| **Keep one freshness number and document that it means build age** | the field is read as *how old is this data*. Renaming it would not stop that, and the composite would still conceal a stale required input |
| **Treat overlap below a threshold as fresh out-of-sample** | there is no honest threshold. A partly-exposed holdout is exposed, and a number would become the thing researchers tune against |
| **Require two sub-periods so the chaining is always exercised** | it refuses a valid return to make a formula look used, and inventing a research restriction to preserve an arithmetic convenience is the wrong direction |

---

## 6. Consequences

**Accepted.**

- The contracts become implementable and reviewable: a later cycle builds against field-level
  definitions rather than deciding them, and a reviewer can tell whether a build matches.
- A rename no longer buys fresh out-of-sample evidence, and every reuse travels into the governance
  packet as a disclosure.
- The private-data boundary states one rule for content and one rule for publication, so a
  legitimate private projection is permitted and a public deployment needs an authorization.
- Risk is four facts with four contracts, and no screen can present an assessment under an entry
  record's label.

**Costs, stated rather than absorbed.**

- **The contracts document is now long.** That is the cost of being checkable; the alternative was a
  deferral that hid the length until implementation.
- **The exposure ledger is real work.** Tracking exposure across lineage is more expensive than
  counting per registration, and it is the only version that is a control.
- **Read-resource limits are proposals.** They are reviewable numbers chosen for a read API and
  nothing else, and a later cycle may lower them; raising one is a decision, not a tuning.
- **Closed vocabularies gained members.** `DataProvenance` gained `REPOSITORY_TRACKED`, and
  `FieldReasonCode` gained the seven of §2.5.1 and §2.5.4. Each is one more value every consumer
  must handle, taken deliberately through an ADR rather than assumed by an implementation.
- **A reason is now mandatory on a successful value.** `NONE` is not decoration: it is what stops a
  producer inventing a failure to fill a required field, and every consumer must read it.
- **Freshness is three numbers where it was one.** A view now states the age of its facts, the lag
  of its build and the age of its build separately, and evaluates every required input against its
  own contract. That is more work than one subtraction, and one subtraction was measuring the wrong
  thing.

---

## 7. What acceptance would and would not mean

**On independent review and merge, this ADR accepts corrected contracts, corrected boundaries and
governance — and nothing else.** **Acceptance authorizes no implementation and no execution.**

| | |
|---|---|
| Corrected Cockpit contracts and boundaries | **ACCEPTED EFFECTIVE ON MERGE OF PR #72** |
| Cockpit application implementation | **NOT STARTED / NOT AUTHORIZED** |
| Read-model, projection, metric-engine and API implementation | **NOT STARTED / NOT AUTHORIZED** |
| Feedback and learning-engine implementation | **NOT STARTED / NOT AUTHORIZED** |
| Brain runtime implementation | **NOT STARTED / NOT AUTHORIZED** |
| Portfolio, risk, strategy, factor, scanner and AI-agent implementation | **NOT STARTED / NOT AUTHORIZED** |
| Database, migration, scheduler, container and deployment | **NOT STARTED / NOT AUTHORIZED** |
| Backtesting | **NOT STARTED** |
| Run A retry | **NOT AUTHORIZED / NOT RUN** |
| Run B | **NOT RUN / NOT AUTHORIZED** — earliest approved target 2026-09-12, at least eight calendar days after Run A |
| Combined assessment | **NOT RUN / NOT AUTHORIZED** |
| P1–P9 | **UNEVALUATED** |
| Data correctness and quality | **NOT ESTABLISHED** |
| G1 / G2 | **OPEN / OPEN** |
| Provider selected | **NONE** |
| Phase 3 | **NOT COMPLETE** |
| CONTROL publication | **DEFERRED** |
| `LIVE_TRADING_HARD_DISABLED` | **True** |
| Live trading | **HARD-DISABLED** |

**No ADR is amended or superseded.** ADR-0027 is **ACCEPTED / IN FORCE** through the merge of
PR #71, ADR-0026 is **ACCEPTED / IN FORCE** through the merge of PR #70, and this decision changes
nothing in either document — it corrects the specifications ADR-0027 adopted, at the clauses §3
names. ADR-0005 remains **PROPOSED**. ADR-0006's authority split is applied, not altered.

**Passing the 2026-09-12 date gate is not execution authorization.** Run B still requires its own
fresh prompt and its own written authorization, and so does the combined assessment. **The at least
eight calendar day Run A to Run B separation is unchanged.**

**Specification, implementation, research, deployment and execution are five separate gates**, and
they are never collapsed into one. This decision stays inside the first.

---

## 8. Governance status at the time of this decision

```text
G1 OPEN · G2 OPEN · G3 CLOSED · G4 OPEN · G5 OPEN · G6 OPEN · G7 OPEN
ADR-0005 PROPOSED · ADR-0026 ACCEPTED / IN FORCE · ADR-0027 ACCEPTED / IN FORCE
INC-0002 OPEN
Phase 3 NOT COMPLETE · CONTROL publication DEFERRED · live trading HARD-DISABLED
Run A COMPLETED ONCE, 2026-09-04 · Run A retry NOT AUTHORIZED
Run B NOT RUN / NOT AUTHORIZED · earliest approved target 2026-09-12
combined assessment NOT RUN / NOT AUTHORIZED · P1–P9 UNEVALUATED
provider selected NONE · backtesting NOT STARTED
```

**Each gate is read on its own.** G3 is closed for the Sharadar personal-use licence and nothing
else ([ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md)); the other
six are open for their own reasons. **No blanket statement about all seven is correct.**
