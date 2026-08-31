# ADR-0018 — Bounded private empirical Sharadar qualification

**Status: Accepted — effective only upon merge of the pull request introducing this ADR.**

**Before that merge this ADR is PROPOSED and carries no authority.** It is a document in an
open pull request. Nothing in it permits an implementation, an infrastructure change, a
provider request, an S3 operation, a credential retrieval or an execution, and nothing in it
becomes permission by being read.

**Date:** 2026-08-30
**Supersedes:** nothing.
**Amends:** [`docs/runbooks/vendor-data-cloud-deletion.md`](../runbooks/vendor-data-cloud-deletion.md),
clarification only, no behavioural change.

---

## 1. What merging this does, and what it does not

Merging this ADR approves **an architecture**. It approves no code, no role, no bucket policy,
no run and no verdict.

| | |
|---|---|
| **Approved on merge** | the design in §4–§12: the evidence inventory, the P1–P9 ceilings, the two-process split, the deterministic private locator, the operation arithmetic, the two least-privilege roles, the parser/evaluator/report boundaries, and the runbook clarification |
| **NOT approved on merge** | implementation under `src/`, a new entry point, an IAM role, a Terraform plan or apply, a binding preflight, Run A, Run B, an assessment run, a provider request, an S3 operation, a credential retrieval, a private report, a P1–P9 execution, a provider selection, a G1 or G2 decision |

**Implementation, infrastructure mutation and execution are three separate gates and are never
collapsed into one.** That rule is not new here; it is the rule five binding-preflight attempts
and two authenticated qualification attempts have each been held to, and this ADR inherits it
rather than restating a weaker version of it.

**This ADR supersedes nothing, and it rewrites no history.**
[ADR-0011](ADR-0011-implement-the-licensed-s3-research-object-store.md) and
[ADR-0017](ADR-0017-bounded-authenticated-sharadar-acquisition-qualification.md) stay exactly as
written. In particular:

- ADR-0011's statement that the licensed store has **no read surface** was true of the store it
  authorized and stays true of it. §7 below adds a **separate, narrowly scoped** read component
  for a different actor; it does not widen `ResearchObjectStore`, and it does not widen the
  writer-side `S3Client` protocol.
- ADR-0017's accounting — **exactly three `PutObject`**, **zero to three conditional
  `HeadObject`**, **zero object-byte reads** — is a fact about *its* surface and *its* two
  attempts. It is untouched. The surface designed here is a **different** surface with its own
  accounting (§9), and it may never be reached through the ADR-0017 entry point.

---

## 2. Context

Two authenticated qualification attempts have occurred under ADR-0017. The first refused at the
AWS identity gate. The second **completed**, made **one** provider request, and published a
single seven-day, single-subject, single-dataset acquisition.

That is bounded-plumbing evidence, and it is accepted as such. It is not empirical provider
qualification: **no P1–P9 minimum is met by one row of one dataset for one subject.** The
retained response also has no digest-free locator, and because the licensed store has no listing
surface — deliberately, since a producer that could list the store could enumerate what a vendor
sent — those three objects cannot be addressed after the fact without a listing nobody will
authorize.

So the question this ADR answers is not *how do we read attempt two*. It is *what would a
package look like that actually produces useful P1–P9 evidence*, and *what has to be true of it
so that the addressability failure cannot recur*.

---

## 3. Owner decisions recorded

| # | Decision |
|---|---|
| 1 | Attempt two remains **successful bounded-plumbing evidence** |
| 2 | Its retained one-row response **will not be located or assessed** |
| 3 | **No S3 listing** is authorized to recover attempt two |
| 4 | Attempt two's three licensed objects **remain covered by prefix-based deletion** |
| 5 | A **third execution of the ADR-0017 entry point remains unauthorized** |
| 6 | The public-test-key harness stays **untouched, unimported and unauthorized to execute** |
| 7 | Create a **new, separately governed** private empirical-qualification architecture |
| 8 | Use the **full eight-subject inventory, by subject class** |
| 9 | **Concrete subject names stay private** — never in Git, documentation, command arguments, public output or this ADR |
| 10 | The owner supplies subject names later through a **git-ignored, owner-only private input** |
| 11 | **Three Phase-3A datasets only:** `tickers`, `stocks`, `actions` |
| 12 | **Two empirical observation runs, at least eight calendar days apart** |
| 13 | Each run needs **its own future authorization and a distinct execution identity** |
| 14 | Run A and Run B are **never one standing authorization** |
| 15 | Approve a **new, narrowly scoped licensed object-byte read surface** |
| 16 | Do **not** widen `ResearchObjectStore` or the writer-side `S3Client` |
| 17 | **No S3 listing** anywhere in the new architecture |
| 18 | **One deterministic private locator per execution** |
| 19 | **Two separate least-privilege roles and separate sessions** — acquisition, assessment |
| 20 | The **acquisition role cannot read retained object bytes** |
| 21 | The **assessment role cannot retrieve the credential or contact the provider** |
| 22 | The **deletion role stays separate and cannot read** |
| 23 | The canonical private report lives **only** in the licensed `qualification/` prefix |
| 24 | **No routine local report copy** |
| 25 | The **deletion-runbook clarification** is part of this slice |
| 26 | ADR-0018 authorizes **architecture only** |
| 27 | **G1 and G2 remain OPEN** |
| 28 | **No provider is selected** |
| 29 | **Phase 3 remains incomplete** |
| 30 | **CONTROL remains deferred; live trading remains hard-disabled** |

**Decision 9 is a licensing control, not a style preference.** Which securities the owner chose
to evaluate is *evaluation information*, and the Sharadar Personal Use License bars disclosing
fitness conclusions ([ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md)).
A subject list in a tracked module, a commit message or a command line would put that in Git
history and in every process listing on the workstation. It therefore arrives through an
owner-only, git-ignored input, is validated against the existing plan grammar, and is never
printed. The plan's **inventory digest** binds it, so a report can prove *which* inventory was
used without disclosing it.

---

## 4. The evidence inventory

**Derived from the P1–P9 requirements, not inherited from the existing harness.** That harness's
request inventory names five tables including `fundamentals` and `events`, two of which the
Stage-3A dataset vocabulary refuses by name. Reusing it because it exists would have imported a
Phase-3B surface into a Stage-3A package.

### 4.1 Eight private subject classes

Recorded as classes. No concrete name appears here or anywhere tracked.

| # | Subject class | Requirements served |
|---|---|---|
| 1 | Active long-history large-cap dividend payer with an in-window split | P1 change detection · P5 split and dividend limbs · P3 delivered header · P4 control |
| 2 | Active spinoff **parent** | P5 spinoff limb |
| 3 | Active spinoff **child** | P5 spinoff limb — the other side of the published ratio |
| 4 | Security delisted approximately **five** years ago | P2 cohort A |
| 5 | Security delisted approximately **ten** years ago | P2 cohort B |
| 6 | Security delisted approximately **fifteen** years ago | P2 cohort C |
| 7 | Ticker-change or numeric-suffix reassignment case | P2 identifier transition · P4 support |
| 8 | Active small-cap control with no corporate action in the window | P5 no-action control · P1 unchanged-row control |

Eight is the compiled subject ceiling. Classes 2 and 3 exist together because the published
spinoff ratio needs the spun-off entity's own opening price: a single-subject sample can never
reach that limb. **One name per delisting cohort is exactly why P2 ceilings at existence rather
than population**, and that limit is stated rather than discovered later.

### 4.2 Datasets, windows and pagination

| Dataset | Window | `page_limit` | `max_pages` |
|---|---|---|---|
| `tickers` | **none — snapshot semantics**, a window is refused | 100 | 2 |
| `stocks` | **1998-01-01 → `T−1`** | 10,000 | 2 |
| `actions` | **1998-01-01 → `T−1`** | 10,000 | 2 |

A window is **required** on a windowed dataset and **forbidden** on the snapshot one, which is
the existing request builder's rule. `T−1` is the UTC day before invocation, derived from the
injected clock and never operator-supplied. The two start dates are the vendor's own documented
depths for those tables, and they are **planning boundaries, not certified earliest records** —
the ADR-0010 disposition of Q8 is unchanged by this ADR.

**Page two is a completeness probe, and it is not an invitation to paginate.** With sorting a
forbidden request parameter and the row limit documented to default to a silent 10,000-row
truncation boundary, an empty second page is the only available proof that the first page was
complete. A **non-empty** second page means truncation, and every row-count-dependent conclusion
for that (subject, dataset) pair is then refused rather than reported. Three pages are not
authorized.

### 4.3 Ceilings

| Ceiling | Value | Basis |
|---|---|---|
| Requests per run | **48** = 8 subjects × 3 datasets × 2 pages | plan arithmetic, at or below every compiled bound |
| Max pages per subject/dataset | **2** | at or below the compiled ceiling of 4 |
| Provider retry policy | **`max_attempts = 1` — zero provider retries** | **arithmetically forced.** The compiled retry budget is 32, and the plan model refuses unless `requests × (attempts − 1) ≤ budget`. At 48 requests, any retry at all needs `48 ≤ 32`, which is false |
| Max response bytes per request | **4 MiB** | roughly five times the largest realistic response; at or below the compiled 64 MiB. **The transport must be constructed with the same value**, because the transport is what stops reading |
| Max total run bytes | **64 MiB** | roughly nine times the expected total; at or below the compiled 512 MiB |
| Per-request timeout | **30 seconds** | |
| Inter-request pacing | **at least 1 second** | the vendor publishes no rate limit, and *no documented limit is not an absent limit* |
| Execution | **sequential only** | concurrency multiplies rate-limit exposure, breaks the canonical request ordering acquisition identity depends on, and makes the run-byte headroom check meaningless |
| Wall-clock ceiling | **1,800 seconds** | worst case 48 × 30 s = 1,440 s, plus pacing |
| Runs | **two, at least eight calendar days apart** | P1 needs two observations of the same rows separated by real calendar time |
| **Max total provider requests across both runs** | **96** | |

### 4.4 Three scales, kept apart

| | Subjects | Span | Requests | Order of magnitude |
|---|---|---|---|---|
| **Minimum qualification** | 4 | 1998 → `T−1` | 24 | 10¹ |
| **This empirical package** | 8, twice | 1998 → `T−1` | 96 total | 10² |
| **Production backfill** | the traded universe | full history | far larger | 10⁵ or more |

Backfill is also a **different acquisition mode**. `BACKFILL` and `UPDATE` exist and neither is
authorized. Nothing in this package can reach either: the mode is fixed at
`AcquisitionMode.QUALIFICATION`, declared and never inferred, with **no fourth mode introduced**.

---

## 5. Honest P1–P9 ceilings

These are ceilings, not expectations. A run may fall short of one; **no run may exceed one.**

| | Ceiling and why |
|---|---|
| **P1** — availability semantics and origin | `PARTIALLY_TESTED` after Run A; **at most `TESTED` after Run B**. The information-time resolution **remains bounded regardless of outcome**, because the vendor's update column is **date-granular** and a date cannot supply an instant. A favourable empirical result does not upgrade it |
| **P2** — delisted coverage | **at most `PARTIALLY_TESTED`.** Sampled delisted-history existence **is not proof of the provider's population-wide survivorship claim** — one name per cohort establishes that history exists for those names and bounds nothing about the population |
| **P3** — corporate-action announcement timing | the **schema question can reach `TESTED`**, because a delivered header decides it. Announcement timing **remains approximated** where the required field is absent, whatever the header says |
| **P4** — classification history | `DOCUMENTATION_RESOLVED`. Classification history **cannot become empirically historized from a snapshot table**: there is no time axis to sample, so no quantity of rows can lift this |
| **P5** — adjusted/raw reconciliation | **realistically at most `PARTIALLY_TESTED`.** The split and dividend limbs may be tested; the **spinoff interpretation remains inconclusive if the provider's semantics remain undocumented** |
| **P6** — known-restatement qualification | **`DEFERRED` to Phase 3B** — it needs a dataset this package refuses by name |
| **P7** — filing linkage | **`DEFERRED` to Phase 3B and EDGAR** |
| **P8** — earnings-timing fidelity | **`DEFERRED` to Phase 3B and EDGAR**. The schema half is already answered adversely by documentation: the events surface is date-only with no time component |
| **P9** — bar construction and origin | `DOCUMENTATION_RESOLVED`. Price **information origin remains `PROVIDER_DERIVED`**, and **`PUBLIC_PIT` is not reachable from this evidence**. P9 asks a question about the vendor's production process rather than about its data, so **no sample of rows can answer it** |

**No aggregate verdict exists anywhere in this design.** There is no aggregate pass, no
qualified, no approved, no proceed, no ready and no provider-selection value — not in the
evaluator, not in the private report and not in the public result. Provider selection is G1, and
G1 is the owner's decision, taken by a person reading evidence and not returned by a program.

---

## 6. Two separate future processes

One package, two processes, two authorizations, two roles, two sessions.

**Why not a single acquire-retain-assess process.** A parser inside the acquisition process puts
a parser on the path that must stay opaque-byte — the invariant ADR-0012, ADR-0014 and ADR-0017
each enforce with a test. It also makes *the provider failed* and *the assessment failed* share
one exit path, which is the conversion this design must prevent. And it makes every parser fix
or evaluator refinement cost **another 48 provider requests** against a bounded subscription, to
re-answer a question the retained bytes already answer.

### 6.1 Acquisition process

A new future entry point, **distinct from every existing entry point** — not the ADR-0017
authenticated entry point, not the binding preflight, not the plan check, not the public-test-key
harness. It will eventually, in this order:

```text
 1  require an explicit ONE-RUN authorization
 2  refuse under automation, CI, pytest and import-only contexts
 3  read the private subject inventory from an owner-only, git-ignored input
 4  pin the governed AWS profile
 5  pass the governed identity gate
 6  resolve only the LICENSED bucket -- never CONTROL
 7  resolve the fixed secret identifier
 8  retrieve one credential
 9  construct injected dependencies
10  run an offline plan preflight
11  execute the 48 requests SEQUENTIALLY
12  publish three Bronze objects per completed request
13  publish ONE private locator, LAST
14  return only closed, non-sensitive counts and statuses
```

**Order is the security property.** A refusal raises, so no later stage runs after an earlier
one refuses: a wrong-account session never reaches a secret, and a failed gate never reaches a
credential. A refusal at stages 1–10 issues **zero** provider requests and **zero** writes.

### 6.2 Assessment process

A separate future entry point under a **separate authorization**. It will eventually:

```text
 1  require a DIFFERENT singleton authorization
 2  refuse under automation, CI, pytest and import-only contexts
 3  pin the governed AWS profile
 4  pass the governed identity gate
 5  resolve only the LICENSED bucket
 6  accept the owner-known execution identity privately
 7  derive the exact locator key -- WITHOUT LISTING
 8  retrieve and validate the locator
 9  retrieve the exact referenced objects
10  verify full-object checksum and byte count BEFORE parsing
11  parse in a new package the ingestion path cannot import
12  evaluate P1-P9 under compiled ceilings
13  publish ONE owner-only private report
14  emit only a closed public result
```

**The assessment process performs zero provider-credential retrievals and zero provider
requests.** That is enforced twice: it has no credential source in its code, and its role
(§10) can reach neither the secret nor the provider. A provider failure therefore cannot become
an assessment result, because the assessment process cannot contact a provider at all.

---

## 7. The deterministic private locator

```text
licensed/qualification/sharadar/locators/<execution-id>.json
```

**The physical path is private and never appears in public runtime output.**

**One locator per execution, not per request.** Per-request locators would need an index of their
own, which is recursion; and they would multiply writes by the request count. One per execution
adds **one write per run**.

### 7.1 The asymmetry that makes it work

An object key in this system binds a **name and a content address together**, and the content
address is derived from the payload — so a key is not constructible without the bytes. That is
exactly the property that made attempt two unaddressable.

The locator resolves it by being **the one object addressed by name**:

- the **locator** is retrieved by a key derived from the execution identity alone, then validated
  against its closed schema and size ceiling **after** retrieval;
- **every object it references** is retrieved by **name and expected digest**, and the
  full-object checksum and byte count are verified **before any parsing**.

So the owner needs to know one thing they already know — the execution identity they chose —
and nothing about payload bytes.

### 7.2 Required properties

| | |
|---|---|
| Classification | **LICENSED**. It carries subject symbols, which are evaluation information |
| Addressability | owner-addressable from a private execution identity; **requires no S3 listing** |
| Append-only | conditional publication; **never overwritten** |
| Ordering | **published last**, after every acquisition write. A locator written first would reference objects that do not exist |
| Schema | **closed**, with **no free-text field**. Not a filtered one — an absent one |
| Size | **at most 256 KiB**, refused above |
| Binding | binds the **plan** and the **private inventory** through digests |
| Per-object binding | binds every **claim**, **payload** and **acquisition record** to an exact private key, its **expected full-object digest**, its **byte count** and its **disposition** |
| Counts | records **planned** and **completed** request counts |
| Completeness | records **`COMPLETE`** or **`PARTIAL`** |
| Ambiguity | records **`publication_state_unknown`** |
| Scope | **never a cross-execution index.** No enumeration, no cross-references, and deliberately **no index of locators** |
| Disclosure | **never** a bucket, account, credential, provider URL or vendor row |
| Deletion | covered by deletion of the licensed `qualification/` prefix |
| Public output | **never appears** |
| Git / AI | **never committed, never handed to an AI session** |

### 7.3 Schema

```text
schema_version   classification   provider   execution_id
acquisition_mode   profile
plan_digest   inventory_digest   source_schema_version
run_started_at   run_completed_at
completeness{COMPLETE|PARTIAL}   publication_state_unknown{bool}
planned_request_count   completed_request_count
entries[]:
    acquisition_id   dataset   subject   requested_range   page_limit   page_skip
    claim_key     claim_sha256     claim_bytes     claim_disposition
    payload_key   payload_sha256   payload_bytes   payload_disposition
    record_key    record_sha256    record_bytes    record_disposition
```

Every field is grammar-bound; there is no field a URL, bucket, account, credential or vendor row
could arrive through. At 48 requests the document is on the order of 32 KiB, well inside the cap.

The locator's own key segment is validated by the existing path-segment grammar, which refuses a
leading underscore, a reserved prefix, a trailing dot and a Windows device name at any extension.
An execution identity whose first dot-separated part collides with a device name therefore
refuses at key construction rather than producing a file that reads differently on another
platform.

### 7.4 Failure classification

| Condition | Classification | Consequence |
|---|---|---|
| Run completed, locator published | `COMPLETE` | assessable |
| Run halted, locator published | **`PARTIAL`** | **accounting is preserved, and the assessor REFUSES to evaluate it** |
| Publication may have partly committed | `publication_state_unknown = true` | assessor refuses |
| Locator write refused | `LOCATOR_NOT_PUBLISHED` | evidence exists and is unaddressable; a **new execution identity** is required |
| Locator write ambiguous | `LOCATOR_STATE_UNKNOWN` | same |
| Locator name occupied by different content | `LOCATOR_COLLISION` | refusal; a new execution identity is required |
| Locator malformed, oversize or digest-unverifiable | refusal | **no payload is read** |

**A missing, collided, ambiguous or unverified locator fails closed.** There is no fallback path
that reconstructs evidence by listing, probing or guessing, because adding one would reintroduce
exactly the capability this architecture removes.

**There is no replay.** A genuine re-run reads a new retrieval instant, so it cannot produce
byte-identical locator content, and the append-only store refuses it. That is the same
no-resume rule the qualification runtime already has, and it is deliberate: a halted execution is
reviewed, and any refetch happens under a **new explicit execution identity**.

---

## 8. Assessment reads exactly what it needs

**Acquisition claims are validated structurally from the locator and are NOT retrieved.**

The claim is a write-time global-uniqueness reservation. Its content carries no evidence about
the provider's data, and the **acquisition record — written last — is what marks an acquisition
complete**. Retrieving 48 claim objects would re-derive a fact the record already carries, at the
cost of 48 additional reads of licensed material. Minimising licensed byte reads is a control,
not an optimisation.

**Acquisition records ARE retrieved.** The record is content-addressed and its digest is bound by
the locator, whereas the locator itself is addressed by name. Reading each record and
cross-checking it against its locator entry is therefore the integrity control that detects a
locator describing a different run.

**The private report key carries a separate assessment identity:**

```text
licensed/qualification/sharadar/reports/<execution-id>/<assessment-id>.json
```

Without this, a report write that failed ambiguously would leave the name occupied by unknown
content and block re-assessment of that execution permanently — while re-assessment is precisely
the cheap operation this architecture exists to make possible. The assessment identity is
owner-supplied, single-use, on the same grammar as the execution identity, and never printed.

---

## 9. Operation-count arithmetic

**Nominal and maximum are different numbers, and this ADR states both.** Reporting a maximum as
though it were exact is how an accounting stops being an accounting.

### 9.1 Acquisition — nominal (48 requests, all complete, locator published first attempt)

| Operation | Count |
|---|---|
| Provider requests | **exactly 48** |
| Provider retries | **zero** |
| Bronze `PutObject` | **exactly 144** — three per completed request |
| Locator `PutObject` | **exactly 1** |
| **Total `PutObject`** | **exactly 145** |
| Conditional `HeadObject` | **zero to 145** — only after a `412`, at most one per `PutObject` invocation |
| Object-byte `GetObject` | **zero** |
| S3 listing | **zero** |
| CONTROL operations | **zero** |
| **Total S3 operations** | **145 to 290** |

### 9.2 Locator retry — the exact closed conditions

A locator publication may be retried **at most twice**, and **only** when the conditional
`PutObject` itself refused with one of these two closed backend classifications — that is, **only
while the condition remains unresolved**:

| Permitted | Why it is safe |
|---|---|
| `THROTTLED` | rate-limited; the write did not take effect for a reason that may not recur |
| `TRANSIENT` | a backend-side failure that may not recur, **including a conditional-write conflict**, where the condition was never resolved |

**Every retry remains conditional** — the same conditional write, with **byte-identical
content**, because the locator payload is built once and held in memory rather than re-derived
from a clock. Conditional publication is idempotent for identical content: if an earlier attempt
did commit, a later one is answered `412`, resolves the occupancy by metadata, finds the digest
matches, and reports *already present*. A retry can therefore resolve an unresolved condition and
can never overwrite, duplicate or corrupt.

**Retry is forbidden after any other outcome**, without exception:

```text
ACCESS_DENIED            a permission failure does not fix itself
NOT_FOUND                the backend answered definitively
INVALID_RESPONSE         the store could not verify what happened -- AMBIGUOUS
INVALID_CONFIGURATION    nothing was sent, and nothing will be
UNKNOWN                  unclassified -- AMBIGUOUS
already-occupied-by-different-content   a genuine collision; retrying repeats it
```

**No retry may follow an ambiguous or unclassified result.** `INVALID_RESPONSE` and `UNKNOWN` are
excluded for exactly that reason.

**A retry-triggering attempt sends no `HeadObject`, so retries do not multiply the metadata
resolution.** `THROTTLED` and `TRANSIENT` are refusals of the conditional `PutObject` itself:
they leave before the occupancy resolution and issue **no** `HeadObject`. The only attempt that
reaches that resolution is one answered `412` — and a `412` **resolves** the condition, which is
the property the retry permission requires to be *absent*. Nothing reached after a `412`
therefore permits another attempt: identical content is a published outcome, different content
is a genuine collision, and a `THROTTLED`, `TRANSIENT` or unverifiable refusal *of the metadata
resolution itself* arrives with the condition already resolved. **At most one locator attempt
can ever reach the `412` metadata-resolution path**, so locator `HeadObject` is **at most one**,
however many `PutObject` invocations the locator made.

### 9.3 Acquisition — maximum (locator retried twice)

| Operation | Count |
|---|---|
| Bronze `PutObject` | **exactly 144** — Bronze writes are never retried |
| Locator `PutObject` | **at most 3** |
| **Maximum total `PutObject`** | **147** |
| Conditional `HeadObject` | **zero to 145** — 144 Bronze, plus **at most one** locator |
| **Maximum total S3 operations** | **147 to 292** |

**A complete run's `PutObject` count is therefore `144 <= n <= 147`, and it is not "exactly 145"
whenever a retry occurred.** The public counters report the **real invocation count**, observed
rather than assumed, and the consistency rules require:

```text
put_object_count == 3 * completed_requests + locator_put_attempts
locator_put_attempts in {0, 1, 2, 3}
head_object_count  <= 3 * completed_requests + 1
get_object_count   == 0        (acquisition)
list_operations    == 0
control_operations == 0
```

**For a complete 48-request run that bound is `head_object_count <= 145`**, and it does **not**
rise with `locator_put_attempts`. Bounding it by the `PutObject` invocation count instead would
admit 147, which no run can reach: the extra invocations a retry buys are exactly the ones that
sent no `HeadObject`. The maximum per-run total is therefore
`147 + 145 = 292` operations, and across the package's two acquisition runs `2 × 292 = 584`.

### 9.4 Assessment — exact formulas

For a `COMPLETE` locator over **R** planned requests, with R = 48:

| Operation | Formula | R = 48 |
|---|---|---|
| Provider requests | `0` | **0** |
| Credential retrievals | `0` | **0** |
| Locator `GetObject` | `1` | **1** |
| Acquisition-record `GetObject` | `R` | **48** |
| Payload `GetObject` | `R` | **48** |
| Acquisition-claim `GetObject` | `0` | **0** |
| **Total `GetObject`** | `2R + 1` | **97** |
| Report `PutObject` | `1` | **1** |
| Conditional `HeadObject` | `0` or `1` | **0 to 1** |
| S3 listing | `0` | **0** |
| CONTROL operations | `0` | **0** |
| **Total S3 operations** | `2R + 2` to `2R + 3` | **98 to 99** |

**The report write is not retried.** Unlike the locator, a failed report costs only a re-run of
the assessment process, which makes **zero** provider requests — so the cheap remedy is a new
assessment identity, not a retry.

For a **refused** locator — `PARTIAL`, missing, collided, malformed, oversize or
digest-unverifiable:

| Operation | Count |
|---|---|
| Locator `GetObject` | **0 or 1** |
| Every other S3 operation | **zero** |
| **Total S3 operations** | **0 to 1** |

**No payload is read on a refusal**, which is what makes the locator validation a gate rather
than a formality.

### 9.5 Whole-package bound

| | Nominal | Maximum |
|---|---|---|
| Provider requests, both runs | 96 | 96 |
| Acquisition S3 operations, both runs | 290 to 580 | 294 to 584 |
| Assessment S3 operations, both runs | 196 to 198 | 196 to 198 |

**Underlying AWS network requests remain UNKNOWN** in every row above. A cloud SDK call can
resolve locally and fail before anything leaves the machine, so a method invocation is not a
proven network request. These are invocation counts, and they are labelled as such.

---

## 10. Two least-privilege roles

Two roles, and **separate sessions** — the assessment process must never inherit a session that
held the acquisition role.

### 10.1 Qualification-acquisition role

**May eventually receive only:**

- one governed secret retrieval;
- conditional `PutObject` to licensed `bronze/*`;
- conditional `PutObject` to the locator prefix;
- the **metadata-only** collision resolution the append-only writer requires.

**Must not receive:** object-byte `GetObject` · S3 listing · delete · copy · CONTROL access ·
bucket administration · assessment-report publication.

### 10.2 Qualification-assessment role

**May eventually receive only:**

- exact `GetObject` on the locator prefix;
- exact referenced-object reads under licensed Bronze;
- conditional publication under `qualification/sharadar/reports/*`.

**Must not receive:** provider-credential or secret access · provider network access · S3 listing
· delete · copy · Bronze publication · CONTROL access · bucket administration.

### 10.3 Why two, and not one

This is a control, not tidiness. The acquisition role is the only principal that can reach the
provider credential — **and it has no object-byte read**, so a compromised acquisition path
cannot exfiltrate the licensed store. The assessment role can read licensed bytes — **and it can
reach neither the secret nor the provider**, so it cannot make a provider request at all. *A
provider failure cannot be converted into an assessment result* then holds as a property of the
identity system, not only of the code.

### 10.4 Unchanged

**The deletion role is unchanged.** It can list and delete for deletion governance, and it
**cannot read object bytes**. Deletion authority stays separated from both new roles, and neither
new role gains any part of it.

**No IAM or Terraform change is authorized by this ADR.** Designing a role is not creating one,
and creating one is a separately authorized infrastructure mutation under the cloud-spend rule.

---

## 11. Parser, evaluator and private report

### 11.1 A new package the ingestion path cannot import

`data/qualify/sharadar/` — new, and deliberately **not** under `data/ingest/`, so the acquisition
path stays parser-free.

- **`data/ingest/` cannot import it.** A static guard, so the separation is structural rather
  than remembered.
- **It cannot import or adapt the public-test-key harness.** Not by import, not by copy, not by
  moving a function. That harness stays untouched and unauthorized to execute.

### 11.2 Parser contract

| | |
|---|---|
| Encoding | **strict UTF-8**; refuse on error. **No replacement decoding** — a replacement character is silent corruption of evidence |
| CSV | RFC4180 handling; ragged rows refused rather than padded |
| Schemas | **dataset-specific contracts**, exact where the vendor documents the header exhaustively and required-subset where it does not, with observed extras recorded rather than refused |
| Numerics | **`Decimal`, never binary floating point** — a float tolerance makes a reconciliation check meaningless |
| Dates | **real calendar-date parsing**; **no coercion of date-only values into instants** |
| Duplicates | detected and reported, never silently de-duplicated |
| Order | **delivered order is observed and recorded, never silently reordered** — sorting is a forbidden request parameter, so the order is the vendor's and it is evidence |
| Missing values | **distinct from zero**, always |
| Empty responses | **header-only responses are valid** where appropriate — a delisted name outside its listing life legitimately returns no rows |
| Pagination | **page-two completeness validation**; a non-empty second page is truncation |
| Schema drift | an **observed schema digest** is recorded, so a later run detects a silent change |
| Profile | **`PROVIDER_REALISTIC_PIT` only**; **`PUBLIC_PIT` is not expressible** in the package |
| Failures | **closed, sanitized**, raised without private causes |
| Ceilings | **per-test compiled ceilings** (§5), enforced rather than documented |
| Verdict | **none** — no aggregate recommendation, no provider selection, no readiness value |

Insufficient evidence — a truncated page, a digest mismatch, a missing limb — yields an explicit
insufficiency, **never a weaker pass**.

### 11.3 The canonical private report

| | |
|---|---|
| Location | **only** `licensed/qualification/sharadar/reports/` |
| Readership | **owner-readable** |
| Contents | classification, evidence identity, creation time, retention basis, deletion obligation, observed schema digests, per-test statuses and limbs, and the measurements the owner needs for a later G1/G2 decision |
| Excluded | **no provider-selection recommendation**, and nothing that reads as one |
| Never enters | **Git · CI · logs · chat · an AI session · CONTROL** |
| Local copies | **none created routinely** — the process writes no local file and offers no output-path option, so an uncontrolled local copy is structurally impossible rather than discouraged |
| Deletion | **inside the existing deletion surface** |

If temporary local material ever became necessary — it is not, at this size — the rule is a
single deterministic path, deleted unconditionally afterwards, **existence re-verified after
deletion**, and a **fail-closed refusal if cleanup cannot be verified**.

---

## 12. Deletion and licensing

### 12.1 The runbook clarification

The runbook's expected licensed prefixes gain:

```text
qualification/sharadar/locators/
qualification/sharadar/reports/
```

**Deletion behaviour does not change.** The runbook already deletes everything under
`qualification/` wholesale, and both new prefixes sit inside it. The clarification exists because
the runbook records that *an unexpected prefix is a finding*, and these two would otherwise be
recorded as findings on their first appearance.

**Preserved unchanged:** no versioning · no Object Lock · no replication · no archival lifecycle
· no backup · prefix-wide deletion · separated deletion authority · the deletion role cannot
read object bytes.

**A locator may be absent, and the deletion procedure must never depend on one to discover
licensed objects.** Deletion is prefix-wide and stays prefix-wide. A locator is a convenience for
the owner's own assessment, never an inventory the deletion path trusts — an object with no
locator is still deleted, which is exactly why attempt two's three unaddressable objects remain
covered.

### 12.2 Licensing

All parsing happens inside the private boundary or in the owner's own process memory. **No vendor
row reaches Git, a chat, an AI session, CI or an external model API.** Fitness conclusions live
only in the licensed prefix, and the public vocabulary carries no finding, no value and no
recommendation. **The subject list is itself evaluation information** and is handled accordingly
(§3, decision 9). Every new artifact is LICENSED and lives inside the 30-day deletion surface.

---

## 13. What this ADR does not change

`AcquisitionMode.QUALIFICATION` with no fourth mode · `PROVIDER_REALISTIC_PIT` as the only
permitted profile · the Q7 and Q8 dispositions · `permaticker` · append-only S3 semantics ·
acquisition identity · the response and run ceilings · no-resume semantics · the opaque-payload
boundary on the acquisition path · CONTROL deferral · provider-neutral contracts · every
production-ingestion boundary · the ADR-0017 surface and its accounting · the public-test-key
harness.

**G1 OPEN · G2 OPEN · G3 CLOSED · G4–G7 OPEN**, ADR-0005 **PROPOSED**, INC-0002 **OPEN**, Phase 3
**NOT COMPLETE**, CONTROL publication **DEFERRED**, live trading **HARD-DISABLED**. A **third**
execution of the ADR-0017 entry point remains **NOT AUTHORIZED**.

---

## 14. Consequences

### 14.1 The gated delivery sequence

Each is a separate written authorization. **Gates 3, 6 and 8 may never be collapsed.**

```text
 1  ADR creation                            this document
 2  ADR review and merge                    architecture approved; nothing else
 3  Offline implementation                  synthetic licensed fixtures only
 4  Implementation review and merge
 5  IAM / Terraform DESIGN and review       a document; no plan, no apply
 6  IAM / Terraform APPLICATION             separately authorized cloud mutation
 7  Owner-only binding preflight            offline composition validation
 8  ONE owner-only Run A
 9  ONE owner-only Run B                    its own authorization, its own identity
10  ONE owner-only assessment run           its own authorization
11  Public status synchronization
12  Private owner review
13  G1 decision                             owner only
14  G2 decision                             owner only
15  Production ingestion / backfill design  a further, separate gate
```

### 14.2 The state this ADR leaves behind

```text
empirical-package executions                 ZERO
provider requests by this package            ZERO
S3 operations by this package                ZERO
P1-P9 executions by this package             ZERO
locators created by this package             ZERO
private reports created by this package      ZERO
new IAM roles created                        ZERO -- none exists
licensed object-byte read surface            DOES NOT EXIST -- until separately
                                             authorized implementation is merged
G1                                           OPEN
G2                                           OPEN
provider selected                            NONE
Phase 3                                      NOT COMPLETE
CONTROL publication                          DEFERRED
live trading                                 HARD-DISABLED
ADR-0017 third attempt                       NOT AUTHORIZED
```

---

## 15. Alternatives considered

| Alternative | Advances P1–P9 | Adds provider requests | Requires S3 listing | Rejected because |
|---|---|---|---|---|
| Assess attempt two's one-row acquisition | **No** — no P-test minimum is met | 0 | **Yes** | it cannot be addressed without a listing nobody will authorize, and one row of one dataset for one subject answers nothing |
| Run the public-test-key harness | Marginally | Yes, on a published test key | No | a subscribed owner evaluating on the vendor's published test key is the wrong credential for private evaluation, and its ceilings are already known |
| Repeat the ADR-0017 one-row entry point | **No** | +1 | Yes | a third identical sample answers nothing the second did not, and a completed run is not permission to run again |
| **Build this package** | **Yes** — the only option meeting the P2 and P5 minimums | 96, bounded | **No** | **chosen** |
| Begin production backfill before qualification | Inverts the order the plan blocks on | Very many | Yes | it would build on unqualified data and is separately prohibited |

---

## 16. Decision

**Adopt the architecture in §4–§12**, effective **only upon merge** of the pull request
introducing this ADR.

**Merging approves architecture. It authorizes no implementation, no infrastructure mutation and
no execution.** Both future runs, the assessment run, the infrastructure and the implementation
each remain separately gated, and **no live request of any kind is authorized by this document.**
