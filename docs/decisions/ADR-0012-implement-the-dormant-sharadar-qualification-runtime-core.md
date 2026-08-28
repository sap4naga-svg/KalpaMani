# ADR-0012 — Implement the Dormant Sharadar Qualification Runtime Core

**Status:** **Accepted — effective on the merge of the pull request that introduces this ADR.**
Until that merge it is proposed and carries no authority.
**Date:** 2026-08-28
**Deciders:** Project owner (human governance)
**Supersedes:** nothing. It supersedes **no gate status**, no part of
[ADR-0005](ADR-0005-point-in-time-data-architecture.md), no part of
[ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md)'s boundary, and no
authorization. It **narrows** one standing description — that no caller of the object store
exists — and states the narrower fact in its place.
**Superseded by:** —
**Relates to:** [ADR-0005](ADR-0005-point-in-time-data-architecture.md) (the point-in-time contract
and the gate model), [ADR-0007](ADR-0007-cloud-first-research-data-plane.md) (the private AWS
location and the deletion-first posture),
[ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md) (why licensed
material may not leave the private boundary),
[ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md) (the client, transport,
redaction and Bronze bridge this composes),
[ADR-0010](ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md)
(Q7, Q8 and the point-in-time consequences this encodes),
[ADR-0011](ADR-0011-implement-the-licensed-s3-research-object-store.md) (the licensed S3 backend a
future composition root would inject)
**Authority:** Blueprint V3.0 §11, §17, §19 · CLAUDE.md §4.21, §4.22, §4.23, §4.24, §8

---

## 1. Context

Five slices now exist and none of them can be run.
[ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md) built a client, a pinned
transport, a redaction vocabulary and a Bronze bridge.
[ADR-0011](ADR-0011-implement-the-licensed-s3-research-object-store.md) built the licensed S3
backend of the neutral object store. Every piece is reviewed, and **nothing joins them together**:
there is no type that says which requests a run consists of, no code that walks them, and no shape
for what a run produced.

That gap is not neutral. When a bounded qualification run is eventually authorized, the work of
deciding *how much a run may ask for* would have to be done under time pressure, beside a live
credential and a running subscription clock — which is exactly the situation in which a page limit
becomes "whatever gets the data" and a subject list becomes "the universe".

So the decision here is the same one ADR-0011 made about the S3 adapter, applied one layer up:
**write the part that decides a run's bounds while nothing can run.**

### What must not be built along with it

A runtime that could construct its own client would need a credential. One that could construct its
own store would need a bucket. Either would be a **composition root**, and a composition root is
the single thing standing between "reviewed code" and "a process that reaches Sharadar and AWS".

That is the line this ADR draws, and it is drawn by absence rather than by policy.

---

## 2. Decision

**Implement a dormant, dependency-injected Sharadar qualification runtime core: a bounded plan
model and an executor that acts only on already-constructed dependencies.**

```
plan model EXISTS   ·   executor EXISTS   ·   dependencies INJECTED
composition root: NONE   ·   credential source: NONE   ·   client construction: NONE
bucket binding: NONE   ·   runner: NONE   ·   __main__ in either module: NONE
constructed outside its own tests: NEVER
Sharadar requests sent: ZERO   ·   AWS requests sent: ZERO
```

Two modules, and no third:

| | |
|---|---|
| `data/ingest/sharadar/qualification.py` | the plan: subjects, dataset plans, compiled ceilings, complete pre-execution validation, deterministic request generation |
| `data/ingest/sharadar/runtime.py` | the executor: validate, fetch through the injected client, publish through the Bronze bridge, return an immutable structured result |

### The plan decides a run's whole cost, before it runs

Nine properties, each with a test behind it:

1. **Three datasets only.** `tickers`, `stocks`, `actions`. `fundamentals`, `daily`, the `SF*`
   tables, events, metrics, holdings and funds are refused **by name** — they are real vendor tables
   owned by a later phase, and a refusal that says *why* is worth more than one that says
   "unknown". Every other name is refused as unknown.
2. **Every request names an explicitly supplied subject.** There is no default ticker and **no real
   symbol is compiled into the module**, which a test asserts.
3. **Explicit windows only.** Required on a windowed dataset, forbidden on the snapshot one. The
   vendor defaults `from` to a year ago and `to` to the prior day (`PSR-SHD-121`), so an omitted
   window silently means something narrower than it looks.
4. **Duplicates and conflicts are refused**, and distinguished: two entries for one dataset with
   the same window is a duplicate; with different windows it is a plan that does not say what range
   it covers.
5. **Unsupported parameters are refused a step early** — `years` (a table-wide bulk download),
   `fields`/`sort`/`columns`/`order` (which make two requests for one range return
   differently-shaped bytes, and Bronze identity *is* the bytes), and `lastupdated` (incremental
   sync, which is production ingestion).
6. **One canonical request order**, by dataset then subject then page offset, independent of input
   order — so two plans holding the same content derive the same acquisition identities and
   reconcile with the same durable evidence.
7. **Seven compiled ceilings, lowerable and never raisable.** A limit above its constant is
   refused rather than clamped: clamping would let a plan claim a budget it does not have and then
   behave differently from what it says.
8. **Validation is complete and happens first.** A partly-wrong plan is refused whole, because
   discovering the eighth request is malformed after seven have been published leaves immutable
   objects in a licensed bucket that nobody decided to create.
9. **Point-in-time consequences are in the type.** `PROVIDER_REALISTIC_PIT` is the only admitted
   profile and `refuse_public_pit` is a function rather than a comment, because a rule that has to
   be remembered is a rule that will be forgotten at the one call site that matters.

### The ceilings, and why each is that number

| Ceiling | Value | Why |
|---|---|---|
| subjects | 8 | Qualification measures whether data behaves as documented; a wide subject list is how that quietly becomes a backfill. Eight covers the shapes that matter — large cap, small cap, delisted, renamed, split, dividend — and keeps a whole run reviewable by reading its result |
| datasets | 3 | There are three Stage-3A tables. Present so the table is complete, and so a fourth appearing in the enum does not silently widen a plan |
| pages per request | 4 | Pagination is how a bounded request becomes unbounded. Four pages is a sample; forty is a download, and a run needing more is asking Q8's empirical question, which is not authorized |
| requests | 96 | The product of the three above, stated as its own constant so the number a reviewer checks is the number the code enforces |
| per-response bytes | inherited from the transport's own default | Tied rather than restated, so the plan cannot authorize a response the transport would refuse and the two cannot drift |
| run bytes | 512 MiB | A per-response ceiling bounds one answer; without this, ninety-six maximum-size answers are still authorized. Enforced as bytes are published, not estimated |
| retry budget | 32 | The vendor publishes no rate limit (`PSR-SHD-109`), and *no documented limit is not an absent limit*. Checked against the **injected client's own attempt policy**, so it bounds what will happen rather than describing an intention |

### One request is one acquisition

The neutral contract defines a retrieval identity as
``(payload digest, ingestion run id)``. An earlier draft of this slice passed one **execution-level**
id to every publication, which made that identity mean something it does not. Three defects followed,
and all three were real:

* byte-identical payloads from **two datasets** collided on the global acquisition claim, so a run
  halted on a conflict that was an artefact of the identity rather than a fact about the data;
* byte-identical payloads from **two subjects** collapsed into one acquisition, so the second
  retrieval left no durable evidence at all;
* byte-identical payloads on **two pages** did the same.

Each request now derives its own identity, ``<execution>.<24 hex>``, where the digest binds the
execution id, the provider, the dataset, the subject, the requested range, the response format and
both page values. Two different requests therefore differ **even when their bytes are identical**,
and the same canonical request under the same execution derives the same identity every time — which
is what lets durable evidence be reconciled with the attempt that produced it.

Disclosure safety is a property of the shape rather than a filter: every component is already
grammar-bound (an enum member, a validated subject, a closed range token, an exact integer), so
there is no field a credential, a URL, a bucket or a response body could arrive in. The derivation
takes no credential at all.

**The execution id has no default.** A reusable one made two attempts share evidence.

### The runtime acts, and reports

**Every dependency is a constructor parameter with no default**: the client, the object store and
the clock. A runtime that could build its own client is one a forgetful test can point at the
vendor.

**Failures stop the run and are reported, not raised.** Objects already published are immutable and
already in a licensed bucket; an exception would discard the record of exactly which ones. So
execution returns a result carrying `HALTED`, one closed failure code, and the outcomes that did
complete — and **states `partial` rather than leaving it to be derived** from arithmetic. Several
immutable objects across several requests have no rollback, and the result says so instead of
implying otherwise.

**Refusals before anything runs still raise**, because nothing has happened yet: a bad plan, a
malformed dependency or an unusable clock stops the caller at the point of the mistake, with zero
provider requests and zero writes.

**One publication writes three objects, and the result says which.** The neutral publisher appends a
global acquisition claim, then the payload, then the acquisition record. All three dispositions are
reported separately, because *the payload was already there* and *this acquisition was already
recorded* are different facts — an earlier draft reported only the payload and called it
`stored_objects`, which could not tell a first retrieval from a repeat of one whose bytes happened to
be present. Four states are distinguished: `FULLY_NEW`, `PAYLOAD_REUSED`, `ALREADY_COMPLETE`, and
`COMPLETED_PRIOR_PARTIAL` — the signature of an earlier publication interrupted between its appends.

**A publication that raises leaves durable state this runtime cannot describe, and it says so.** The
three writes are separate appends: a failure on the second or third may have committed the first,
and an ambiguous backend failure **may not prove whether any of them committed**. The result carries
`publication_state_unknown` and **claims to know nothing more** — in particular, no field here
claims to identify which objects exist after such a failure.

**There is no resume, and an earlier draft of this ADR wrongly said there was.** It claimed that
re-running a halted plan resumed it safely through object-store idempotency. That was only ever
true of a *frozen* clock: a real second execution reads a new ``retrieved_at``, so the acquisition
record under an already-occupied name differs and is **refused** — correctly, and not as a resume.
Re-running the same execution id after a halt therefore fails closed on the first already-recorded
request.

The supported path is stated instead: **a halted execution must be reviewed, and any subsequent
refetch must use a new explicit execution id.** Identical payload bytes may still deduplicate in the
payload namespace, but the later retrieval is a **new acquisition with a new retrieval instant** —
payload reuse is not acquisition reuse. Reusing an execution id with different acquisition metadata
fails closed rather than being described as a resume.

**Durable cross-process resume is deferred** until a separately governed checkpoint or attestation
exists. This slice adds no checkpoint file, no CONTROL record, no mutable ledger, no store listing
and no ungoverned attestation, and would need an ADR of its own to add one.

**Nothing a dependency says reaches a message.** A response body, a URL carrying the key
(`PSR-SHD-109`), a bucket name, a backend error string and an arbitrary exception have no parameter
to enter through: every failure is one member of a closed `StrEnum`, and exceptions are raised
`from None`.

### One addition to an accepted module

`SharadarClient` gains a read-only `max_attempts` property. The value already appears in its
`__repr__`, so nothing new is exposed; it makes an existing non-sensitive configuration number
reachable without reading a private attribute. Without it the retry budget could only be
*declared* — a bound that is correct in review and unenforced in production.

### The backfill flag is fixed, and the fit is imperfect — a finding, not a decision

An earlier draft took a raw ``is_backfill`` boolean on the public plan. A caller could therefore
label qualification evidence as a **production backfill** by passing ``True``, turning a metadata
field into an authorization claim nobody made. The field is removed from the plan, and the bridge
receives the fixed value :data:`~kalpamani.data.ingest.sharadar.runtime.QUALIFICATION_IS_BACKFILL`
(``False``). **This authorizes and implements no production backfill**, and no second acquisition
mode, production mode or backfill route is added.

**The fixed value is not a perfect fit, and pretending otherwise would be the wrong kind of tidy.**
The neutral contract describes ``is_backfill`` as distinguishing "a vendor backfill from an update".
A qualification retrieval is neither: it extends no prior state, so it is not an update; and it is
not an authoritative historical load, so calling it a backfill would overstate what the evidence is.
``False`` is chosen as the value that **cannot be mistaken for authoritative historical loading**,
which is the failure that would matter downstream.

**Owner decision required before this metadata is relied on.** A design that fits exactly — a
per-dataset value, or a third token in the neutral vocabulary — is available and is deliberately
**not** chosen here, because inventing one would be a change to the neutral contract that this
correction was not authorized to make.

### An offline plan-check command

`scripts/sharadar_plan_check.py` validates a plan and prints a fixed-schema summary. **It has no
execution mode, and the absence is structural**: it imports no client, no transport, no store and
no executor, so there is nothing there to point at a vendor even by accident. `--execute`,
`--live`, `--api-key`, `--secret`, `--bucket`, `--aws-profile`, `--endpoint` and `--token` are
refused **by name**, because an unrecognised flag teaches nothing and someone will try a different
spelling. No subject symbol is printed.

It is **not** the private qualification harness. `scripts/sharadar_private_qualification.py` is
untouched, unimported and still unauthorized to execute.

---

## 3. Alternatives considered

**Build the composition root too, and gate it behind a flag.** Rejected, and it is the central
decision. A flag is a thing that can be set — by a script, by an environment variable, by a
well-meaning session reading a runbook. The control that actually holds is that no credential
resolver, no client factory and no bucket binding exists to switch on. Absence is checkable; a flag
is a promise.

**Let the runtime read the plan from a configuration file.** Rejected. It would turn every ceiling
into a value editable without review, which is precisely what compiling them in prevents, and it
would give the module a filesystem read it otherwise does not have.

**Retry inside the runtime.** Rejected. The client already retries on a bounded, deterministic,
jitter-free schedule. A second retry layer would multiply attempts by a factor nobody reads off the
code, and against a vendor with no published rate limit that is how a courteous integration becomes
an incident. A future authorized caller may re-run the whole `put_if_absent`, which is safe only
because every attempt stays conditional.

**Raise on execution failure instead of returning a result.** Rejected. The exception would be
tidier and would discard the one thing a failed run most needs to record: which immutable objects
are now in the bucket.

**Parse the payloads to check them.** Rejected. Bronze exists so a truncated, malformed or
unexpectedly encoded response is preserved as evidence rather than lost to a parse error at the
boundary — and that is the case where evidence matters most. It would also be the first step toward
deriving something from `permaticker`, whose level is publicly unresolved.

**Reuse the private qualification harness as the executor.** Rejected. It is an owner-only tool
under `scripts/`, unauthorized to execute, and built around the vendor's published test token. A
production-shaped runtime must not inherit either property.

---

## 4. Consequences

**Gained.** The bounds of a future qualification run are now decided, written down and tested,
while nothing can run. The five existing slices have a shape that joins them, so the next
authorization is "run this bounded plan" rather than "design and run a plan". A partial run has a
defined, honest reporting shape, which is the thing a first real run is most likely to need.

**Given up.** The claim that nothing in this repository can call the object store. It was accurate
until now and is not any more: the runtime calls it, through the Bronze bridge, with an injected
store. **The narrower and still-true statement is that no composition root exists** — no credential,
no client, no bucket, no runner and no caller outside the runtime's own tests, each verified by a
static test. That correction is made in `CLAUDE.md` and `README.md` in the same change.

**A finding carried forward.** The ``is_backfill`` fit above is imperfect and is recorded rather
than smoothed over. Until it is decided, no consumer should read a qualification acquisition
record's ``is_backfill`` as evidence about the retrieval's nature.

**Not gained — stated exhaustively.** This ADR authorizes **code, tests, documentation and
synthetic validation only.** It does not authorize, and merging it does not enable:

> retrieving, inspecting, creating, configuring or binding a private credential · Secrets Manager
> access or a real secret resolver · constructing a real AWS SDK session or client · resolving or
> binding a real bucket · any AWS read, write, mutation, verification, CLI command or Terraform
> command · any Sharadar API call · published-test-token probing · Services Data access, parsing,
> download or ingestion · bulk downloads · empirical Q8 or `permaticker` qualification · production
> backfill or ingestion · CONTROL publication · provider selection or G1/G2 closure · broker, LEAN,
> Paper expansion or live trading

**The next slice, and what it must bring.** A separately authorized composition root would supply
the real private bindings — a credential source, a constructed client, a bound bucket, a constructed
`S3ResearchObjectStore` — and authorize one bounded run. Each of those is a decision this ADR does
not make.

**Unchanged.** **G1 OPEN · G2 OPEN · G3 CLOSED (Sharadar personal use, ADR-0008) · G4 OPEN ·
G5 OPEN · G6 OPEN · G7 OPEN.** ADR-0005 remains **PROPOSED**. INC-0002 remains **OPEN**. Phase 3
remains **NOT COMPLETE**. CONTROL publication remains **DEFERRED**, and
`LIVE_TRADING_HARD_DISABLED` remains **True**.

**Q7, Q8 and `permaticker` are unchanged and unresolved.** Q7 remains `PUBLICLY_UNRESOLVED`; Q8
remains `PUBLICLY_BOUNDED` with empirical verification not performed; published table depths remain
planning boundaries rather than certified earliest records; `permaticker` remains an opaque
vendor-stable identifier from which neither issuer-level nor security-level semantics may be
inferred. **This runtime resolves none of them, and derives nothing from `permaticker` at all** —
payloads are opaque bytes here and are never parsed.

**No dependency was added.** The project's runtime dependency list is still exactly
`["boto3>=1.36.0,<2.0"]`, and neither new module imports it.

---

## 5. Verification

Enforced by test, not by review:

| Property | How |
|---|---|
| the new modules import no network client and no SDK | AST scan, per module |
| nothing constructs a client, session, credential or S3 store | AST scan for construction sites |
| no ambient environment or filesystem read | docstring-stripped source scan |
| no host, bucket, ARN or account literal | regex over executable code |
| no entry point and no import-time work | AST scan of module bodies |
| no module-level mutable state | AST scan for list/dict/set assignment |
| nothing in the repository constructs the runtime outside its own tests | AST scan over `src/`, `scripts/`, `tests/` |
| publication goes only through the Bronze bridge | scan for `put_if_absent`, `put_object`, `ObjectKey.` in the runtime |
| `RetrievalMetadata.notes` is never used as a channel | scan of both modules |
| every ceiling refuses an increase and permits a decrease | parametrised over each field |
| out-of-phase and unknown datasets refused | parametrised over every named table |
| missing subject, unbounded window, conflicting window refused | dedicated tests |
| deterministic order, independent of input order | two plans built in opposite orders compared |
| a refused plan issues zero provider and zero store calls | recorded call counts on both |
| exact bytes and digests preserved, payload never parsed | a payload that was never valid anything |
| LICENSED only; no CONTROL key | logical-key inspection |
| byte-identical payloads across two datasets complete without conflict | the real in-memory store, not a lenient fake |
| byte-identical payloads for two subjects create two acquisitions | distinct derived identities asserted |
| byte-identical payloads on two pages create two acquisitions | distinct derived identities asserted |
| changing any identity component changes the identity | parametrised over all six components plus the execution |
| no credential or URL can influence or enter an identity | the derivation takes no credential, and the pre-image has no field one could arrive in |
| a replay on a **real** clock is refused, not reported as a resume | a stepping clock, five minutes later |
| a new execution id records a second retrieval, reusing the payload | payload reuse and acquisition recording asserted separately |
| a failure at each of the three publication writes halts and reports unknown state | fault injected at write 1, 2 and 3 |
| an interrupted publication completes on a later run as `COMPLETED_PRIOR_PARTIAL` | staged failure, then a clean run |
| every result field is validated at construction | adversarial constructors: string subclasses, negative counts, malformed digests, wrong profile, wrong classification, list-for-tuple, contradictory states |
| a result summary that disagrees with its outcomes is refused | every derived count re-checked |
| an unknown query parameter is refused | allowlist admission, including `api_key` and an invented future name |
| stop on first failure, partial stated | recorded transport call count and `partial` |
| errors carry no body, URL, key or bucket | leak canaries plus `__cause__ is None` |
| no outcome is `PUBLIC_PIT`; the runtime never names it | outcome inspection and source scan |
| `permaticker` is never named or derived from | docstring-stripped scan of both modules |
| the CLI has no execution mode and refuses live options | in-process runs of each refused option |
| the CLI opens no socket and prints no subject | patched socket module; output inspection |

**Every test is synthetic and offline. No test contacts Sharadar or AWS, and none can: there is
nothing to contact either with.**
