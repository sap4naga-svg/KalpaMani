# ADR-0017 — Bounded Authenticated Sharadar Acquisition Qualification

**Status:** **Accepted — effective on the merge of the pull request that introduces this ADR.**
Until that merge it is proposed and carries no authority.
**Date:** 2026-08-30
**Deciders:** Project owner (human governance)
**Supersedes:** nothing. It **narrows no accepted rule, retracts no invariant and edits no prior
ADR.** In particular it leaves intact
[ADR-0012](ADR-0012-implement-the-dormant-sharadar-qualification-runtime-core.md)'s
*one request is one durable acquisition* rule, its byte-for-byte Bronze publication contract and its
opaque-payload boundary; [ADR-0013](ADR-0013-introduce-acquisition-mode-and-retire-is-backfill.md)'s
closed three-member acquisition-mode vocabulary;
[ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md)'s requirement that
private qualification evidence is retained privately;
[ADR-0014](ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md)'s composition
architecture; and
[ADR-0015](ADR-0015-implement-the-dormant-sharadar-private-binding-preflight.md)'s operator-boundary
principles. **Accepted ADRs are not rewritten.**
**Superseded by:** —
**Relates to:** [ADR-0005](ADR-0005-point-in-time-data-architecture.md) (the gate model),
[ADR-0007](ADR-0007-cloud-first-research-data-plane.md) (the governed AWS foundation, its identity
gate and its licensed bucket),
[ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md) (the licence this
credential is used under), [ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md) (the
client, credential and request builder),
[ADR-0011](ADR-0011-implement-the-licensed-s3-research-object-store.md) (the licensed store and its
append-only semantics),
[ADR-0012](ADR-0012-implement-the-dormant-sharadar-qualification-runtime-core.md) (the plan model and
the executor this uses), [ADR-0013](ADR-0013-introduce-acquisition-mode-and-retire-is-backfill.md)
(the acquisition mode this declares),
[ADR-0014](ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md) (the
composition root this extends),
[ADR-0015](ADR-0015-implement-the-dormant-sharadar-private-binding-preflight.md) (the binding path
this reuses), [ADR-0016](ADR-0016-correct-private-binding-preflight-failure-boundaries.md) (the
corrected failure boundaries this inherits)
**Authority:** Blueprint V3.0 §11, §17, §19 · CLAUDE.md §4.4, §4.5, §4.21, §4.22, §4.23, §4.24, §7, §8

---

## 1. Context

Six accepted slices built a complete authenticated Sharadar acquisition stack and then stopped one
statement short of using it. The plan model, the executor, the licensed store, the Bronze bridge, the
composition root and the private-binding path all exist and are tested. The fifth authorized binding
preflight retrieved one credential, constructed one Secrets Manager client, one S3 client and one
provider transport, and validated a plan offline. **It sent no provider request**, because
`preflight_qualification_composition` is the only operation the composition root exposes.

So the repository can prove that a credential is *structurally* acceptable to `SharadarCredential`
and cannot prove that it *authenticates against Sharadar*. Those are different facts, and only a real
request separates them.

### What a static inspection found, and why this ADR exists

A separately authorized session was asked to execute *"exactly one bounded authenticated Sharadar
qualification attempt"* against a tracked private authenticated entry point. It performed the
starting-state verification and the static call-graph inspection, and **stopped before executing
anything**, because no such entry point exists:

| Candidate | What it actually is |
|---|---|
| `scripts/sharadar_private_qualification.py` | the **public-test-token** P1–P9 harness — its credential is the vendor's published test token, it retrieves five tables, parses payloads, stages raw files locally and uploads them |
| `scripts/sharadar_binding_preflight.py` | the **offline** binding/composition preflight — terminates at `preflight_qualification_composition` by design |
| `scripts/sharadar_plan_check.py` | offline plan validation; imports no client, transport, store or executor |

`QualificationRuntime.execute` — the only code that can issue an authenticated provider request
through the governed path — **has no production caller.** Every call site is a unit test.

**No AWS, Secrets Manager, S3, Terraform or provider activity occurred during that inspection**, and
no qualification was attempted. This ADR exists because the missing piece is an *architectural*
decision, not a coding oversight.

### The decision that was declined, and why it needed an ADR

A follow-up authorization proposed implementing a **bounded authenticated probe**: one provider
request, **zero S3 operations**, **zero persistence**, and a structural check of the returned rows.
That implementation was declined at its own governance gate, because three accepted rules say
otherwise and none of them may be narrowed quietly:

1. **ADR-0012 requires publication.** `QualificationRuntime.execute` publishes every response
   byte for byte through the Bronze bridge under `LICENSED`. *One request is one acquisition.* An
   authenticated request that records nothing has no place in the accepted architecture.
2. **ADR-0013 requires a declared acquisition mode.** `RetrievalMetadata.acquisition_mode` and
   `IngestionRun.acquisition_mode` are required with **no default**, over a deliberately closed
   three-member vocabulary. A fetch that publishes nothing constructs neither record, so the request
   would be declared as nothing at all.
3. **ADR-0012 keeps payloads opaque.** *"payloads are opaque bytes here and are never parsed."*
   Structural row validation at the provider boundary contradicts it, and no parser exists under
   `src/` to reuse — the only one in the repository lives inside the public-test-token harness.

**The correct minimum is not a smaller request. It is the same minimum request, published.** A
bounded acquisition is *narrower in scope* than the probe and *stronger in evidence*: it proves the
credential authenticated, and it leaves durable, auditable, licensed evidence that a later private
empirical slice can evaluate without contacting the vendor again.

---

## 2. Decision

**Authorize a later, separately reviewed, code-only implementation slice adding one dormant operator
entry point that performs exactly one bounded authenticated Sharadar acquisition qualification
through the already-accepted stack.**

```
this ADR authorizes        a later CODE-ONLY implementation PR, and nothing else
this ADR executes          nothing
entry point created here   NONE
provider requests          ZERO   ·   AWS requests: ZERO   ·   S3 operations: ZERO
credential retrievals      ZERO   ·   qualification executions: ZERO
authenticated qualification attempts to date: ZERO
provider authentication: UNKNOWN
```

The operation is named a **bounded authenticated acquisition qualification**. It is **not** the
P1–P9 empirical qualification, which remains a separate, unexecuted, public-test-token harness.

### It uses the accepted stack, and adds no parallel one

The future execution must, in this order and with no substitutions:

| | |
|---|---|
| governed profile | the existing `EXPECTED_PROFILE` contract |
| identity | the existing governed AWS identity gate in `scripts/aws_foundation_verify.py` |
| licensed configuration | the existing governed licensed-bucket resolution |
| secret identifier | the existing fixed source, the tracked non-secret variable **name** |
| credential | the existing Secrets Manager boundary, `data/ingest/sharadar/secrets.py` |
| credential contract | the existing `SharadarCredential` |
| client and transport | the existing `SharadarClient` over the existing origin-pinned transport |
| executor | the existing `QualificationRuntime.execute` |
| mode | `AcquisitionMode.QUALIFICATION`, from the existing `QUALIFICATION_ACQUISITION_MODE` |
| publication | the existing licensed Bronze bridge, byte for byte |
| evidence | the existing durable acquisition artifacts, in the licensed private data plane only |

**No CONTROL publication. No Silver or Gold ingestion. No provider selection. No gate closure.**

### The composition root is extended, not duplicated

`src/kalpamani/data/ingest/sharadar/composition.py` is the **one** module under `src/` authorized to
construct the licensed store, the client and the runtime, and a static test enforces that a second
one fails. The future implementation **extends that module** with one additional function that
executes a plan, alongside the existing `preflight_qualification_composition`.

**This is decided, not left open.** A separate root is **rejected**: it would require widening the
single-constructor guard from one module to two, and that guard is the thing standing between this
architecture and an unreviewed construction site. Extending the accepted root keeps the guard exactly
as strict as it is today, and the new function is subject to every rule the existing one is.

---

## 3. What is preserved, explicitly

This ADR is a **use** of the accepted architecture, so each of the following continues to hold
unchanged, and the later implementation must not weaken any of them:

| Preserved | Consequence here |
|---|---|
| **ADR-0012 — one request is one acquisition** | the single request produces exactly one durable acquisition. **Not narrowed**, and not made conditional |
| **ADR-0012 — byte-for-byte Bronze publication** | the response is published as returned, undecoded |
| **ADR-0012 — opaque payloads at the acquisition runtime** | the bytes are not parsed, decoded, sampled or inspected. **No new parser is authorized anywhere in the provider boundary** |
| **ADR-0013 — closed acquisition-mode vocabulary** | `QUALIFICATION`, declared and never inferred. **No fourth mode is introduced** |
| **ADR-0008 — private evidence stays private** | the acquisition lands in the licensed bucket and nowhere else; no result, row or count reaches Git, a pull request, an issue or an AI session |
| **ADR-0014 — composition architecture** | one composition module, extended; dependencies injected; nothing retained |
| **ADR-0015 / ADR-0016 — operator boundary** | refuse by default, ordered gates, no identifier in `argv`, closed outcomes raised `from None`, allowlisted output |
| **Licensed / CONTROL separation** | CONTROL writes stay **ZERO and forbidden** |
| **Vendor payloads stay out of the repository** | no payload, row, digest or byte count is committed |
| **No selection from one result** | one acquisition selects no provider and closes no gate |

**A zero-persistence provider request is not authorized by this ADR, and is rejected by it** (§12).

---

## 4. The locked one-request plan

The later implementation must lock every one of these in code. **None is operator-selectable.**

| | Locked value | Evidence |
|---|---|---|
| Dataset | `SharadarDataset.STOCKS` | the smallest price surface the tracked enum defines; the snapshot table carries no price observation and the corporate-action feed is not a price path |
| Subject | one normalized ticker from `--subject`; the first authorized run pins **AAPL** | `SharadarRequest.ticker` is validated against the tracked ticker grammar |
| Acquisition mode | `AcquisitionMode.QUALIFICATION` | `QUALIFICATION_ACQUISITION_MODE`, defined once in `qualification.py` |
| Page skip | `0` | `Page.skip >= 0` |
| Page limit | the smallest positive limit that satisfies the model, with a **hard maximum of 10** | `Page` admits `1 <= limit <= MAX_PAGE_LIMIT`; the ceiling here is this ADR's, far below the model's |
| Pagination | **forbidden** — `Page.advanced()` is never called | it is the only way to walk a result set |
| Retry | **forbidden** — `RetryPolicy(max_attempts=1, backoff_seconds=())` | `RetryPolicy` requires `len(backoff_seconds) == max_attempts - 1`, so this is the valid zero-retry policy |
| Provider requests | **exactly one** | one dataset plan, one subject, one page |
| Response ceiling | the existing `SharadarClient.max_response_bytes`, resolved once at construction | unchanged from ADR-0009; not restated and not raised |
| Bulk / full history | **forbidden** | `years`, `fields`, `sort`, `columns`, `order` and `lastupdated` are already refused by name a step before the request builder |
| Services Data export | **forbidden** | no such route is constructible |

### The date window, decided

`stocks` is in `WINDOWED_DATASETS`, so `SharadarRequest` **refuses to construct without an explicit
`DateWindow`**. The window is therefore a decision this ADR must make rather than defer.

**Decision: a seven-calendar-day trailing window ending on the UTC date immediately before
invocation**, derived from the injected clock — `DateWindow(start=D-6, end=D)`, where `D` is the UTC
date immediately before the invocation instant.

| Why this one | |
|---|---|
| small | seven calendar days is a sample, not a retrieval |
| normally non-empty | it spans a full week, so it ordinarily contains completed U.S. sessions |
| no new dependency | it needs no exchange calendar, no holiday table and no market-data source |
| deterministic | it is a pure function of the injected clock, so a run is reproducible from its execution id and its instant |
| honest when empty | an empty response is a **valid closed outcome**, not an error and **not permission to retry** |

**Ending the day before, rather than on the invocation date, is deliberate**: the vendor documents
the upper bound as defaulting to the prior day (`PSR-SHD-121`), and a window whose last day is still
in progress would make "empty" ambiguous between *no session yet* and *no data*.

**A holiday week, a market closure or a delisted subject can legitimately return zero rows.** That is
a completed result. **No second request may be made** — not with a wider window, not with a different
subject, not otherwise — under the same authorization.

---

## 5. Durable evidence, and the exact S3 envelope

**Zero S3 operations is not the design.** The whole point of publishing is that the evidence outlives
the run. The counts below were established by static inspection of the accepted code and are stated
exactly, because a ceiling argued from intention is not a ceiling.

### One acquisition creates three durable artifacts

`publish_bronze_payload` claims, publishes and records — in that order, so a contradictory identity is
refused before any bytes land, and a record can never name a payload that does not exist:

| # | Artifact | Written by |
|---|---|---|
| 1 | the **acquisition claim**, under the reserved acquisition-claim prefix | `store.put_if_absent(key=claim_key, payload=claim_bytes)` |
| 2 | the **raw vendor payload**, byte for byte | `store.put_if_absent(key=payload_key, payload=payload)` |
| 3 | the **acquisition record** — immutable metadata carrying the acquisition mode as a plain exact string | `store.put_if_absent(key=acquisition_key, payload=record_bytes)` |

### The S3 operation count, exactly

Each `put_if_absent` issues **exactly one `PutObject`** with `IfNoneMatch="*"` and **no preflight
`HEAD`** — a check-then-write is a race, and the bucket carries no versioning to absorb it. A
`HeadObject` is issued **only after a `412 PreconditionFailed`**, to resolve whether an occupied name
holds identical content. A `409 ConditionalRequestConflict` is `TRANSIENT` and reaches no
`HeadObject`.

```
S3 client constructions                    ONE
PutObject operations                       EXACTLY THREE   -- one publication
HeadObject operations                      ZERO to THREE   -- only on a 412 collision
S3 object-byte reads                       ZERO            -- the store has no read surface
CONTROL bucket operations                  ZERO            -- forbidden, and refused at admission
```

**The `HeadObject` path is surfaced rather than rounded to zero.** It is a *metadata* read that
ADR-0011 already requires for collision resolution; **object bytes are never downloaded**, because
the licensed store exposes only `put_object` and `head_object` and has no read, list, delete, copy or
multipart path. This is an existing accepted contract, not a new authorization, and it is recorded
here so a later ceiling is written against what the code does.

**The future operational ceiling is bound to one normal three-write publication**, plus at most the
three collision `HeadObject` calls that publication can itself issue.

### No additional report is invented

`QualificationRunResult` is an **in-memory frozen dataclass**. It is returned to the caller and
**written nowhere**. The acquisition record is already the durable evidence of the bounded result, so
**no separate qualification report artifact is authorized** — one would duplicate metadata that
already exists and create a second private thing to keep.

### The cleanup contract, precisely

**There is none to state, because there is no staging.** `QualificationRuntime.execute` holds the
response in memory and publishes it; the runtime module performs **no filesystem write of any kind**
— no `open`, no path write, no directory creation, no temporary file. Local staging and post-upload
purging exist only in the public-test-token harness, which this path does not use and does not
import.

```
.runtime/ writes by this path              ZERO
temporary vendor payload files             ZERO
local vendor payload after publication     NONE -- none was ever written
```

---

## 6. Acquisition identity

The future execution must produce, for its single request:

- `AcquisitionMode.QUALIFICATION` — declared, never inferred from dates, counts, payload contents or
  prior coverage;
- **one execution identifier**, supplied by `--execution-id`;
- **one request identity**, derived by `request_identity_preimage` from the execution id, provider,
  dataset, subject, requested range, response format and both page values;
- **one acquisition identity**, via `acquisition_id`;
- the governed provider, dataset, subject, window and page parameters, recorded through the existing
  durable field allowlist;
- immutable acquisition metadata with **no free-text field**;
- the existing content addressing and lineage;
- **no overwrite** — every write is append-only and idempotent for identical content.

It must be distinguishable, from the durable record alone, from **`BACKFILL`**, **`UPDATE`**, the
public-test-token qualification, a binding preflight, a CONTROL publication and production ingestion.

**Re-running is not a resume.** A second execution reads a new instant, so its acquisition record
differs and the store refuses it. A halted run is reviewed and refetched under a **new explicit
execution id**, under a **new authorization**.

---

## 7. The initial slice does not parse the payload

**Decided: the bounded authenticated acquisition qualification does not parse or semantically inspect
the provider payload.** The acquisition runtime continues to treat the response as opaque bytes.

The initial outcome rests on four things only:

1. authenticated request admission;
2. provider transport completion;
3. bounded response-byte admission under the existing client contract;
4. successful durable Bronze publication.

**Required-field checks, subject correspondence, schema conformance, semantic validation and data
quality belong to a later, separately governed private empirical-qualification slice** operating on
the retained private evidence — not on a live provider request. That ordering is the point: the
acquisition captures the evidence once, and every subsequent question is answered from the licensed
store without contacting the vendor again.

**No new CSV parser is authorized in the provider boundary.** The parser in the public-test-token
harness stays where it is; it is **not reused, moved, copied, imported or adapted**.

---

## 8. The future operator surface

A later implementation pull request may add one dormant operator entry point under `scripts/`.
**This ADR does not create it.**

Its CLI must contain **exactly three** arguments:

```
--i-am-the-operator-authorizing-authenticated-qualification
--subject
--execution-id
```

Dataset, page, limit, window policy, retry policy, response ceiling, bucket destination and
acquisition mode are **locked in code and not operator-selectable**.

**Forbidden CLI concepts**, refused by name so a wrong reflex fails loudly rather than silently: any
credential or secret argument, a secret identifier, an ARN, an API key, an endpoint, a dataset or
table selector, a full-history or bulk switch, pagination, a page size, retry, a bucket, the
`--run` / `--live` / `--force` aliases, and any ingestion or publication mode.

### The ordered gates

The path must fail closed in this order, and no later stage may run after an earlier refusal:

```
 1  operator authorization flag
 2  refusal under pytest, CI or import-only context
 3  governed AWS profile contract
 4  existing AWS identity gate
 5  existing licensed-bucket resolution
 6  fixed secret-identifier source
 7  existing Secrets Manager boundary
 8  existing credential structural contract
 9  one provider transport / client construction
10  exactly one authenticated provider request
11  bounded response-byte admission
12  one Bronze acquisition publication
13  sanitized closed outcome
```

**The secret identifier is not read before stages 1 to 4 pass.** Order is the security property: a
wrong-account session never reaches a secret, and a failed gate never reaches a credential.

---

## 9. Closed outcomes

The later implementation must define a closed vocabulary distinguishing at least these, with names
consistent with the repository's existing refusal idiom:

| Semantic outcome | Exit |
|---|---|
| operator authorization refused | non-zero |
| governed profile refused | non-zero |
| AWS identity refused | non-zero |
| licensed-bucket resolution refused | non-zero |
| secret identifier refused | non-zero |
| Secrets Manager access refused | non-zero |
| credential contract refused | non-zero |
| provider authentication / request refused | non-zero |
| response size refused | non-zero |
| Bronze publication refused | non-zero |
| **acquisition qualification completed** | **zero** |

Public output is a fixed, allowlisted set of sentences. **No raw exception, URL, query string,
secret, secret identifier, account identity, ARN, profile value, bucket, provider row, response
header, entitlement detail, payload length or fingerprint may be emitted.** Every refusal is a closed
member raised `from None`.

**A failed request or a failed publication is a completed result, not permission to retry.**

---

## 10. Future operational ceilings

Any later single authorized execution is bound to:

```
process invocations                        ONE
operator admissions                        ONE
governed-profile verifications             ONE
AWS identity gates                         ONE
licensed-bucket resolutions                ONE
secret-identifier resolutions              ONE
Secrets Manager client constructions       ONE
get_secret_value invocations               ONE
credential contract admissions             ONE
S3 client constructions                    ONE
Bronze acquisition publications            EXACTLY ONE
S3 PutObject operations                    EXACTLY THREE -- that publication's
S3 HeadObject operations                   ZERO to THREE -- only on a 412 collision
provider transport constructions           ONE
Sharadar/provider requests                 ONE
qualification-runtime executions           ONE
pagination                                 ZERO
automatic retries                          ZERO
additional subjects                        ZERO
additional datasets                        ZERO
CONTROL operations                         ZERO
Silver/Gold ingestion                      ZERO
production ingestion                       ZERO
broker or trading operations               ZERO
underlying AWS and provider network requests   UNKNOWN
```

**Underlying network-request totals stay UNKNOWN** unless an existing operation counter proves
otherwise. A method invocation is not a proven network request: a client may validate parameters
locally and fail after the method is entered and before anything leaves the machine.

---

## 11. What a success may and may not establish

A completed bounded authenticated acquisition qualification establishes **only**:

- the governed credential **authenticated for that exact request**;
- the locked dataset and endpoint **were accessible at that moment**;
- **one** provider response was returned;
- the raw response was **durably acquired** under the accepted licensed Bronze contract;
- the acquisition runtime **completed its existing publication contract**.

It does **not** establish, and must never be described as establishing:

> full P1–P9 empirical qualification · provider-wide authentication · access to every Sharadar
> dataset · full-history entitlement · Services Data entitlement · response-schema correctness ·
> data quality · point-in-time correctness · history depth · price-feed provenance · **Q7
> resolution** · production-provider selection · **G1 or G2 closure** · ingestion readiness ·
> authorization for another request · current or future credential or session validity

**Q7 remains `PUBLICLY_UNRESOLVED`.** A credential probe cannot resolve feed provenance, and neither
can an acquisition. All Sharadar price data stays `PROVIDER_DERIVED`, usable only under
`PROVIDER_REALISTIC_PIT`, and never represented as `PUBLIC_PIT`.

**The public-test-token P1–P9 harness remains separate and unexecuted**, and this path neither
imports it nor replaces it.

---

## 12. Alternatives considered

| Alternative | Rejected because |
|---|---|
| **Zero-persistence authenticated probe** | it violates ADR-0012's *one request is one acquisition* rule and its publication contract, and ADR-0008's requirement that qualification evidence is retained privately. A provider request leaving no record is unauditable and architecturally exceptional — the one class of request nobody could later review |
| **A fourth acquisition mode for a "probe"** | ADR-0013 already provides `QUALIFICATION` for exactly this: a bounded provider-validation retrieval. A fourth member would re-open a vocabulary closed on purpose, to name something that already has a name |
| **Reusing the public-test-token harness as the authenticated runner** | it authenticates with the vendor's **published test token**, retrieves **five** tables, **parses** payloads, stages raw files locally and uploads on a broader persistence model. Repurposing it would change the executable behaviour of an accepted harness and destroy the evidence value of its separation |
| **Reusing the binding preflight as the runner** | it terminates at offline composition **by design**, and that is the property ADR-0015 was accepted for. Giving it an execution surface would retract an accepted guarantee |
| **Parsing the payload at the provider boundary** | ADR-0012 requires opaque bytes there, and the invariant is independently enforced. Parsing also loses the evidence case that matters most: a truncated or malformed response is preserved as evidence rather than lost at the boundary |
| **Running the full P1–P9 empirical qualification immediately** | far broader than the minimum authenticated gate. It answers questions that cannot be asked until authentication is established, and its results are private conclusions under the licence |
| **A provider request without durable evidence** | it would leave the one thing a later empirical slice needs — the retained raw acquisition — unavailable, forcing a second vendor request to answer questions the first could have captured |
| **A separate composition root for execution** | it would widen the single-constructor guard from one module to two. The accepted root can be extended safely, so it is (§2) |

---

## 13. The authorization sequence

Acceptance of this ADR **skips no step**:

1. **Merge ADR-0017.** It becomes effective on that merge and carries no authority before it.
2. **Separately review and merge a code-only implementation pull request** adding the dormant
   surface.
3. **Verify the dormant surface entirely with fakes and synthetic tests** — no AWS, no network.
4. **Separately authorize exactly one real execution.**
5. **Stop on its first outcome.** A refusal, timeout or unexpected response is a completed
   diagnostic result, not permission to repair and retry.
6. **Synchronize documentation** under its own review.
7. **Separately decide** whether to authorize private empirical P1–P9 qualification using the
   retained acquisition.
8. **Provider selection and gate closure remain later decisions**, taken on their own evidence.

**Merging this ADR authorizes step 2 and nothing beyond it.** It does not authorize execution.

---

## 14. Consequences

**What becomes possible:** a reviewed implementation slice may be proposed. Nothing else changes on
merge — no code is added by this ADR, no entry point exists, and no run is authorized.

**What stays true:** authenticated qualification attempts **ZERO** · provider requests **ZERO** ·
qualification executions **ZERO** · provider authentication **UNKNOWN** · S3 object operations
**ZERO** · credential retrievals **ONE**, the single structurally accepted retrieval from the fifth
binding-preflight attempt · binding-preflight attempts **FIVE** · CONTROL publication **DEFERRED**.

**What is not resolved:** **G1 OPEN · G2 OPEN · G3 CLOSED · G4–G7 OPEN**, ADR-0005 **PROPOSED**,
INC-0002 **OPEN**, Phase 3 **NOT COMPLETE**, live trading **HARD-DISABLED**. **No provider is
selected**, and one acquisition would not select one.

---

## 15. Verification

This ADR is documentation. What it can be checked against is the accepted code it describes, and each
statement below was established by static inspection rather than assumed:

| Claim | How it was established |
|---|---|
| `execute` publishes every response through the Bronze bridge | the runtime's own docstring and body; ADR-0012 §2 |
| one publication writes three artifacts | `publish_bronze_payload` — three `put_if_absent` calls |
| one `put_if_absent` is one `PutObject`, with `HeadObject` only after a 412 | the licensed S3 backend |
| the store has no read surface | it exposes `put_object` and `head_object` only |
| `QualificationRunResult` is not durable | an in-memory frozen dataclass, returned and written nowhere |
| the runtime performs no filesystem write | no file open, path write, directory creation or temporary file in the runtime module |
| `stocks` requires an explicit window | `WINDOWED_DATASETS` and `SharadarRequest.__post_init__` |
| `Page` admits a smallest positive limit and a zero skip | `Page.__post_init__` |
| `RetryPolicy(max_attempts=1, backoff_seconds=())` is valid | `RetryPolicy.__post_init__` |
| `QUALIFICATION` is defined once | `QUALIFICATION_ACQUISITION_MODE` in `qualification.py` |
| exactly one module may construct the licensed store | the static architecture test, and this audit's own check |
| no tracked authenticated entry point exists | every module entry point under `src/` and `scripts/` enumerated; `execute` has no production caller |

The documentation audit independently requires the status documents to keep saying that this surface
does not exist, has not run, and authorizes no execution.
