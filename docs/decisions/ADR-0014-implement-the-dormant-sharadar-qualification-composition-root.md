# ADR-0014 — Implement the Dormant Sharadar Qualification Composition Root and Offline Preflight

**Status:** **Accepted — effective on the merge of the pull request that introduces this ADR.**
Until that merge it is proposed and carries no authority.
**Date:** 2026-08-29
**Deciders:** Project owner (human governance)
**Supersedes:** the **live "no composition root exists" claim only** — in
[ADR-0011](ADR-0011-implement-the-licensed-s3-research-object-store.md) §"the control is absence",
[ADR-0012](ADR-0012-implement-the-dormant-sharadar-qualification-runtime-core.md), and wherever a
current status document states that nothing constructs the client, the store or the runtime. It
supersedes **no gate status**, no authorization boundary, and no other property of those decisions —
their append-only, integrity, redaction, ceiling and PIT guarantees are untouched. **Accepted ADRs
are not rewritten**: their historical text is the record of what was decided then, and none of it
functions as a current contract where this ADR speaks.
**Superseded by:** —
**Relates to:** [ADR-0005](ADR-0005-point-in-time-data-architecture.md) (the point-in-time contract
and the gate model), [ADR-0007](ADR-0007-cloud-first-research-data-plane.md) (the private research
data plane), [ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md) (the client and
transport this wires), [ADR-0010](ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md)
(Q7 and Q8, unchanged by this),
[ADR-0011](ADR-0011-implement-the-licensed-s3-research-object-store.md) (the store this wires),
[ADR-0012](ADR-0012-implement-the-dormant-sharadar-qualification-runtime-core.md) (the runtime this
wires), [ADR-0013](ADR-0013-introduce-acquisition-mode-and-retire-is-backfill.md) (the acquisition
mode this composition can only ever record)
**Authority:** Blueprint V3.0 §11, §17, §19 · CLAUDE.md §4.21, §4.22, §4.23, §4.24, §7, §8

---

## 1. Context

Five accepted slices sit beside one another, each taking its dependencies by injection: the
credential, the transport, the client (ADR-0009), the licensed S3 object store (ADR-0011) and the
qualification runtime (ADR-0012). **Nothing anywhere constructed the set.**

That absence was the control, and it was stated as one in every status document: *the distance
between this and a live run is exactly one composition root, and none exists.* It was also a gap in
review. The wiring nobody had written was the wiring nobody had checked — and it is the piece where
a credential meets a transport, and a bucket meets a store, which is precisely where a mistake would
matter most. Deferring it did not remove the risk; it moved the risk into the moment when someone
would write it under time pressure, next to an authorization to run.

### The owner's authorization, exactly as given

> The owner authorizes implementation of a dormant Sharadar qualification composition root and
> offline preflight. Scope is limited to: code; tests; documentation; audits; and synthetic/local
> validation. **The first authenticated qualification run remains separately gated.**

Nothing in this ADR reaches beyond those five words: code, tests, documentation, audits, synthetic
validation.

---

## 2. Decision

**Implement one composition, in one module, as one function, with no way to run anything.**

`src/kalpamani/data/ingest/sharadar/composition.py`, and no second module —
`preflight_qualification_composition`, and **no stateful object**.

**Why a function and not a class.** The first revision of this ADR specified a class, and the class
was wrong. It held `_client`, `_store` and `_runtime`, and this ADR claimed no attribute exposed the
runtime. That was false: `composition._runtime.execute(plan)` ran, and the slice's own tests reached
those attributes to prove the components had been built. **A leading underscore is a naming
convention, not an execution barrier**, and a dormancy claim resting on one is not a claim.

A function makes the property structural. There is no `self` to attach a runtime to, no instance for
a caller to hold, and no attribute to reach — so *no executable component escapes* stops being a
rule someone must remember and becomes a fact about the shape. §5.1 records the defect in full.

### What it constructs, and from what

Every dependency is a **required keyword parameter with no default**. There is no ambient discovery
of any kind, and no default that could reach a real service.

| Input | Supplied by the caller |
|---|---|
| `credential` | an already-built exact `SharadarCredential` |
| `transport` | an object satisfying `SharadarTransport` |
| `pacer` | an exact `Pacer`, with its own injected clock and sleeper |
| `retry_policy` | an exact `RetryPolicy` |
| `timeout_seconds` | a bounded float |
| `s3_client` | an object satisfying `S3Client` |
| `licensed_bucket` | a bucket-shaped string, validated by the store that receives it |
| `clock` | an object satisfying `QualificationClock` |

It also takes the `plan` to check, because a function that validated nothing would have no reason
to build anything.

From those it builds `SharadarClient`, `S3ResearchObjectStore` and `QualificationRuntime` as **local
variables**, and returns only the closed result. **It builds nothing else, and it discovers
nothing.** When the call returns, the client, the store, the runtime, the credential, the transport,
the S3 client, the bucket string, the clock and the plan are all unreachable: nothing holds them.

**Precisely what "no construction" does and does not mean here.** A client, a store and a runtime
**are** constructed — from values a caller hands in — and tests construct a synthetic bucket string
and a synthetic store. What does not exist anywhere is an **AWS SDK session or S3-client
construction**, a **real** bucket binding, a **real** credential binding, or any credential source.
The credential is held by the client for the duration of one call and is unreachable after it.

**Validation is delegated, not duplicated.** The credential's exactness, the timeout range, the
retry policy's shape, the bucket's grammar, the S3 client's two operations and the clock's one
method are each already enforced by the constructor that owns them, and each refusal is already
sanitized. Re-checking them here would create a second, drifting copy of every rule.

`pacer` is the one exception, and it is required and exactly typed here. `SharadarClient` accepts
`None` and builds its own from `time.monotonic` and `time.sleep` — the right default for a client,
and the wrong one for a composition root, which would then hold an ambient dependency nobody handed
it.

### The only operation

`preflight(plan)` calls `QualificationRuntime.validate` and nothing else, then returns a small
closed result. `validate` builds the plan's requests, checks the retry budget against the *injected
client's* attempt policy, checks the request count against the plan's ceiling, checks that every
request derives a distinct acquisition identity, checks both byte ceilings against what the client
could actually return, and probes the clock. **It issues no provider request and no store call** —
which is why a composition holding real dependencies is still inert while only this method exists.

### Preflight performs none of these

> a fetch · a publication · a provider call · an AWS call · a credential retrieval · a `reveal()` ·
> an environment lookup · a file read · a socket · a subprocess · an SDK import

Each is checked, most of them by counting calls on a synthetic dependency rather than by asserting
an intention.

### The result

`QualificationPreflight` is frozen, slotted, subclass-refusing, and carries eight fields: a closed
status, five bounded non-negative counts, `AcquisitionMode.QUALIFICATION` and
`InformationSetProfile.PROVIDER_REALISTIC_PIT`.

**There is no credential field, no bucket field, no URL field, no region, profile or account field,
no subject field, no payload field, no backend-message field and no free-text field.** Those have
nowhere to be, and `__post_init__` enforces the shape at runtime rather than leaving it to
annotations, which are a static claim.

**The result must describe a plan that could actually have passed.** The first revision accepted
zero for every count while still reporting `VALIDATED_OFFLINE`, so an independently constructed
result could claim a run of no requests, no attempts and no bytes had been validated. No plan
produces those numbers. Every count is now bounded by the **same compiled constants** the plan and
the client are held to — `MAX_REQUESTS`, `MAX_ATTEMPTS_CEILING`, `MAX_RESPONSE_BYTES`,
`MAX_RUN_BYTES`, `MAX_RETRY_BUDGET` — with no second set of numbers to drift, and the two cross-field
rules the runtime itself applies are re-checked: the response ceiling may not exceed the run ceiling,
and `requests × (attempts − 1)` may not exceed the retry budget. A retry budget of zero stays
legitimate, because `max_attempts=1` takes no retry.

The numbers are **derived, never restated**: the request count from the plan's own generator, the
attempt ceiling from the injected client's retry policy, the response ceiling from the stricter of
the client and the plan. A preflight reporting declared intentions rather than effective bounds
would describe a run other than the one that would happen.

### The transport contract is enforced where it is owned

`SharadarClient.__init__` did not check that the injected transport could perform a request. An
object carrying only a plausible `max_response_bytes` composed and validated cleanly while being
unable to fetch anything — a `Protocol` annotation is a static claim, and nothing checked it.

The client now requires a **callable `get`**, and converts a missing, non-callable or
exception-raising member lookup into its existing sanitized `BUILD: REQUEST_MALFORMED` refusal, from
`None`. The dependency's own exception text never reaches the refusal. This is fixed at the client,
which is the thing that calls `get`, rather than duplicated in the composition.

The declared response ceiling is now **resolved once, during client construction, and stored**. An
earlier revision asked the transport on every access, which made the ceiling a *view of a mutable
dependency*: a plan could be validated against one number and executed against another, because the
object that declared it is free to change its mind in between. **A bound is not a bound if the thing
it bounds can move it.** The conservative fallback is kept — a transport that does not declare a
valid ceiling is assumed able to return the most any transport may, so a caller budgeting against
this number cannot under-count — but a *raising* declaration is not absorbed: an object whose
attribute access raises is not one that declined to answer.

### One acquisition-mode constant, in the module that owns it

The first revision defined `QUALIFICATION_ACQUISITION_MODE` in the composition while the runtime
separately named `AcquisitionMode.QUALIFICATION`, and the composition's comment claimed it read the
runtime's contract. **It did not.** Two independent statements of one fact is a dual-write in every
sense that matters, and the interesting case is the one where they disagree.

The constant is now defined **once**, in `qualification.py`, exported from there, and imported by
the runtime when it records retrieval metadata and by the composition when it reports the mode. A
test asserts exactly one assignment defines it. There is still no plan field, caller parameter,
conditional derivation or override.

### The status word is a control

The single member is **`VALIDATED_OFFLINE`**. Not `READY`, not `PROCEED`, not `APPROVED`, not
`QUALIFIED`, not `AUTHORIZED` — a test refuses each of those spellings anywhere in the module.

The vocabulary has exactly one member, because a *failure* status that can be returned is a failure
a caller can ignore. Every refusal raises, in one of the existing closed vocabularies, so the only
object this module can hand back is one describing a plan that passed.

**Preflight is not a verdict.** It says a plan is internally consistent against an injected client's
own policy. It says nothing about the provider, nothing about the data, and nothing about whether a
run should happen.

### There is no execution surface

No `execute`, `run`, `fetch`, `publish`, `upload` or any private spelling of one; **no object to
hold a runtime and no attribute to reach one through**; no CLI, no module entry point, no console
script, no scheduled task, no ECS task, no Lambda, no Terraform resource, no Docker image. The
module defines exactly one public callable, and its only `return` of a constructed value is the
closed result.

**The module never spells `execute` at all**, which is checked over docstring-stripped code.

### Nothing outside its own tests constructs it

Not a production module, not a script, not another test. The package does not re-export it, so
reaching it requires naming the module — which is a decision rather than an accident. A static guard
over `src/`, `scripts/` and `tests/` holds all of that.

---

## 3. Alternatives considered

**Keep deferring the composition root until the run is authorized.** Rejected. That schedules the
least-reviewed code for the moment of highest pressure, beside the authorization that makes it live.
Writing it while nothing can use it is the only time it can be reviewed calmly.

**Put the wiring in the existing private qualification harness.** Rejected, firmly. That harness is
a standalone owner-run instrument that reads the vendor's *published* test key, and it is
deliberately outside the installed package. Making it the composition root would fuse a manual
instrument with production wiring, and would put a credential-reading module on the path every
future runner takes. It is not modified, imported, executed or repurposed by this slice.

**Give the composition an `execute` method and gate it behind a flag.** Rejected. A boolean, a token
or an "activation" parameter that a caller can set is not a governance control — it is a control
that looks like one, which is worse than none. The gate is the absence of the code.

**Have the composition read the credential from the environment.** Rejected.
`credential_from_env` already exists and takes an explicit mapping precisely so that a future
authorized runner can pass `os.environ` at the one place allowed to. This module is not that place,
never calls that function, and never touches a process environment.

**Report a richer preflight result — the bucket, the subjects, the URL that would be called.**
Rejected. Every one of those is a private identifier or licensed material under CLAUDE.md §3 and
§4.22, and a result object is the thing most likely to be logged.

---

## 4. Consequences

**Gained.** The wiring exists, is reviewed, and is proven inert by counted calls rather than by
assertion. A plan can be checked against the components that would actually run it — the injected
client's own retry policy and byte ceiling, not a number written beside them. And the repository can
now say precisely where composition happens, instead of saying it happens nowhere.

**Given up.** The simplest possible claim. "Nothing constructs any of these" was easy to verify and
is no longer true. What replaces it is narrower and has to be maintained: *exactly one module
constructs them, it has no execution surface, and nothing calls it.* Each clause is a test.

**Not gained — stated exhaustively.** This ADR authorizes **code, tests, documentation, audits and
synthetic/local validation only.** It does not authorize:

> credential retrieval, inspection, creation, setup, storage or real binding · Secrets Manager ·
> AWS session or client construction · bucket discovery or real binding · AWS reads, writes,
> verification or Terraform · any Sharadar API call · published-test-token probing · Services Data
> access, download, publication or ingestion · empirical qualification · bulk download · production
> backfill, update or ingestion · CONTROL publication · provider selection or G1/G2 closure ·
> broker or LEAN activity · Paper expansion · live trading

**The first authenticated qualification run remains separately gated**, and this merge does not
approach it. What would still be needed: an authorization, a credential source, a real credential, a
constructed SDK client, a bound bucket, and code that calls something other than `preflight`. **None
of those exists**, and each is a separate decision.

**Merging this slice selects no provider.** Naming an implementation target has never been
selection, and joining five slices does not become it. **G1 and G2 stay OPEN.**

**`AcquisitionMode.QUALIFICATION` remains fixed by the qualification runtime** (ADR-0013). The
composition has no mode parameter, `preflight` has no mode parameter, and `QualificationPlan` has no
mode field — so there is nothing for a caller to supply or override. The preflight result reports
the mode; it does not choose it. As ADR-0013 records, the mode is declared rather than inferred and
**proves nothing on its own** about PIT admissibility or row chronology.

**CONTROL publication remains DEFERRED and NOT AUTHORIZED.** The store this composition constructs
refuses `CONTROL` at admission, and nothing here changes that.

**The SDK stays unimported.** `boto3>=1.36.0,<2.0` remains the only runtime dependency and no
dependency is added. The S3 client is injected here as it was everywhere else, so **no module under
`src/` imports the SDK** — the composition root included. Importing the data platform still pulls in
no AWS code, opens no socket and performs no ambient credential discovery.

**Unchanged.** **G1 OPEN · G2 OPEN · G3 CLOSED (Sharadar personal use, ADR-0008) · G4 OPEN ·
G5 OPEN · G6 OPEN · G7 OPEN.** ADR-0005 remains **PROPOSED**. INC-0002 remains **OPEN**. Phase 3
remains **NOT COMPLETE**. CONTROL publication remains **DEFERRED**. `LIVE_TRADING_HARD_DISABLED`
remains **True**.

---

## 5. Verification

Enforced by test, not by review:

| Property | How |
|---|---|
| every input is required, keyword-only, and has no default | signature inspection, plus a parametrised omission per input |
| no dependency default can reach a real service | the pacer is required and exactly typed, because the client's own `None` default builds one from `time` |
| the three accepted components are constructed | observed by what only each could have done: the client resolves the transport ceiling, the store refuses a bad bucket, the runtime probes the clock. **Not** by reaching a private attribute — that reach *was* the defect |
| no executable component escapes | everything reachable from the result is walked; no client, store, runtime or credential is in it |
| no component is stored durably | AST: a constructed component may be assigned only to a bare local; no module-level state but `__all__` |
| no component, closure or bound method is returned | AST over every `return` in the module |
| there is no stateful composition object | the module's classes are exactly the status enum and the result |
| preflight calls `validate`, never `execute` | both patched and counted; `execute` raises if reached |
| a bounded plan yields `VALIDATED_OFFLINE` | end to end on synthetic fakes |
| the counts are derived from the plan and the client | a changed retry policy moves the reported ceiling; the response ceiling follows the transport |
| `QUALIFICATION` is fixed and unsupplied | no mode parameter on the composition, on preflight, on the plan or on the limits; a non-qualification mode is refused by the result |
| the profile is exactly `PROVIDER_REALISTIC_PIT` | identity assertion, and `PUBLIC_PIT` is absent from the module |
| the result is closed and immutable | frozen, slotted, subclass-refused |
| the result cannot describe an impossible run | 25 adversarial cases — every prohibited zero, every value above its compiled ceiling, a response ceiling above the run ceiling, retry arithmetic above the budget, booleans, negatives, floats, strings, `None`, and a bare token where a member belongs |
| every legitimate boundary is still accepted | 8 cases including `max_attempts=1` with `retry_budget=0`, equal byte ceilings, and retry arithmetic exactly at the budget |
| the bounds come from the compiled constants | the five constant names appear in the module |
| refusal happens before any activity | a bad bucket, timeout, clock, plan or ceiling, each with transport and S3 call counts asserted at zero |
| provider transport calls | **zero**, counted on a fake that raises if called |
| S3 `put_object` / `head_object` calls | **zero**, counted the same way, through a real `S3ResearchObjectStore` |
| object-store publication | **none**; publication can only reach S3 through the counted client |
| `reveal()` calls | **zero**, measured by patching `SharadarCredential.reveal` |
| clock reads | exactly one, and only because `validate` probes it |
| no leak | a secret-shaped, a bucket-shaped, a backend-message-shaped and a subject-shaped canary, each absent from the result, its fields, both reprs, `str`, every refusal and captured output |
| the transport must be able to perform a request | a missing `get`, a non-callable `get`, a raising lookup and a raising ceiling, each refused and each sanitized |
| the response ceiling is resolved once | the transport counts its own reads: exactly one, and repeated access does not increase it |
| a mutating transport cannot move a validated bound | the declaration is changed after construction; the client and the reported preflight are unmoved |
| one assignment defines the acquisition-mode constant | AST over `src/` |
| no execution-like callable | regex over the module's public and private callables, dunders excluded by shape |
| exactly three methods on the class | AST over the class body |
| the module never names `execute` | docstring-stripped source scan |
| no entry point, CLI, subprocess, file read or `Path` | docstring-stripped source scan |
| no SDK or network-client import | AST import scan on the module, and repository-wide over `src/` |
| no default network opener anywhere under `src/` | AST scan for `UrllibTransport`, `build_opener`, `urlopen` |
| nothing constructs or imports it outside its own tests | AST and text scans over `src/`, `scripts/` and `tests/` |
| the package does not re-export it | `__all__` and attribute assertions |
| the plan carries no credential, bucket, mode or permission field | dataclass field-set assertions |
| import time does nothing | AST over module-level statements |
| the retired `is_backfill` representation is absent | docstring-stripped source scan |

**Every test is synthetic and offline.** The credential is a self-labelled synthetic string, the
bucket is a synthetic name, the transport and S3 client raise if called, and the clock is a fixed
instant. Nothing here contacts a provider, AWS or a network, and no credential, bucket, endpoint or
real-data path becomes constructible.

### 5.1 Four defects this ADR's first revision contained

Recorded because they are the reason several rows above exist, and because a correction that hides
what it corrected teaches a later reader nothing.

**An executable runtime escaped.** The composition was a class holding `_client`, `_store` and
`_runtime`. This ADR claimed no attribute exposed the runtime, that there was no way to run
anything, and that a first authenticated run would need new execution code. All three were false:
`composition._runtime.execute(plan)` ran, using only what the object already handed out. The slice's
own tests reached those attributes with `object.__getattribute__` to prove the components had been
built — **which was the demonstration of the defect, not evidence of safety**. The correction is a
module-level function, so the property is structural rather than a convention.

**The result could describe an impossible run.** `__post_init__` accepted zero for every count while
still reporting `VALIDATED_OFFLINE`. No plan produces zero requests, zero attempts and zero bytes,
so an independently constructed result could claim a validation that could not have happened.

**A malformed transport passed preflight.** `SharadarClient` never checked that the injected
transport could perform a request, so an object carrying only a plausible `max_response_bytes`
composed and validated cleanly. The ceiling was also re-read from the dependency on every access,
which made a validated bound movable after the fact.

**The acquisition mode was stated twice.** The composition defined its own constant while the runtime
named the member directly, and a comment claimed the composition read the runtime's contract. It did
not; they were two independent statements that could drift.

**The shape of all four is the same:** a property asserted in prose and enforced nowhere, or enforced
on one path and assumed on another. Each correction replaces the assertion with something a test can
falsify.
