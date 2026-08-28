# ADR-0011 — Implement the Licensed S3 Research Object Store

**Status:** **Accepted — effective on the merge of the pull request that introduces this ADR.**
Until that merge it is proposed and carries no authority.
**Date:** 2026-08-28
**Deciders:** Project owner (human governance)
**Supersedes:** the standing description of the object store as **in-memory only** in
[ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md) §7, and the repository's
**zero-runtime-dependency** posture. Nothing else. It supersedes **no gate status**, no part of
[ADR-0005](ADR-0005-point-in-time-data-architecture.md), no part of
[ADR-0007](ADR-0007-cloud-first-research-data-plane.md), and no authorization boundary.
**Superseded by:** —
**Relates to:** [ADR-0005](ADR-0005-point-in-time-data-architecture.md) (the point-in-time
contract and the gate model), [ADR-0007](ADR-0007-cloud-first-research-data-plane.md) (the private
AWS location, the deletion-first posture, and the separated deletion role),
[ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md) (why licensed
material may not leave the private boundary),
[ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md) (the neutral object contract
this implements a backend for),
[ADR-0010](ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md)
(the qualification subscription this store would eventually serve)
**Authority:** Blueprint V3.0 §11, §17, §19 · CLAUDE.md §4.21, §4.22, §4.23, §4.24, §8

---

## 1. Context

[ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md) defined a provider-neutral
`ResearchObjectStore` — a logical, immutable, append-only contract for licensed research objects —
and shipped exactly one backend for it: an in-memory dictionary. That was the honest scope at the
time. It also left an obvious gap: **the contract had never been implemented against a store that
can actually race, deny, throttle or answer ambiguously.**

The AWS research foundation has been provisioned since 2026-08-27 (36 resources, verified 66/66),
and both research-data buckets are empty. A qualification subscription is now active
([ADR-0010](ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md)).
The next thing that will be asked of this repository is to put bytes somewhere durable.

The decision this ADR records is **when** to write that code: **while the store still has nothing
bound to it** — no bucket identifier, no credential, no client — so the parts that are easy to get
subtly wrong are reviewed calmly rather than under the pressure of a half-finished ingestion.

That is a statement about this repository, not about the world. The AWS foundation and its buckets
were provisioned in August 2026 and exist now; a Sharadar qualification subscription is purchased
and its clock is running (ADR-0010). What this slice establishes is narrower and checkable: **it
retrieved, inspected, created, configured and bound no credential; it binds no bucket identifier to
the adapter and records none here; and the adapter has sent zero AWS requests and incurred no
adapter-attributable request or object-storage activity.**

### The specific things that are easy to get wrong

| | |
|---|---|
| **Check-then-write** | A `HEAD`, then a `PUT`, is a time-of-check/time-of-use race. Between the two, another writer can land an object, and the `PUT` then destroys evidence that verified a moment earlier |
| **ETag as identity** | An ETag is a multipart-dependent opaque token, **not** a content hash. Treating it as one makes every identity claim in the system conditional on how an object happened to be uploaded |
| **Ambiguity read as success** | An occupied name whose contents cannot be *proven* identical is not "probably fine". A permission failure is not absence |
| **A conflict read as occupancy** | S3 answers `412 PreconditionFailed` when the conditional write found the key present, and `409 ConditionalRequestConflict` when a concurrent operation was in flight and the upload is *retryable*. Only the 412 resolved the condition. Treating a 409 as occupancy invents a verdict from an answer that carried none |
| **A composite checksum read as a content address** | S3 reports SHA-256 in two kinds. `FULL_OBJECT` is the digest of the bytes; `COMPOSITE` is a digest of a multipart upload's *part digests*, so it varies with the part size. The algorithm being SHA-256 is not enough — the **type** has to be proven, and an unstated type proves nothing |
| **Backend errors as messages** | A raw `ClientError` string carries the bucket, the key, an endpoint host, a request id and sometimes credential-shaped text. Logged or raised verbatim, it publishes exactly what CLAUDE.md §3 forbids committing |
| **Overwrite protection that is not there** | The licensed bucket carries **no versioning** by design. S3 cannot protect an overwrite for us here |

---

## 2. Decision

**Implement `S3ResearchObjectStore`, the LICENSED-only S3 backend of the neutral
`ResearchObjectStore` protocol, as reviewed code that has never been run against AWS.**

**Status wording is merge-stable by construction.** The slice is recorded as *IMPLEMENTED —
ACCEPTED EFFECTIVE ON MERGE OF PR #16 — CODE ONLY, NEVER RUN AGAINST AWS*. Before that merge the
condition is unsatisfied and this ADR carries no authority; after it, the same sentence is still
true. A *pending* status would have to be edited the moment it stopped being pending, which is the
documentation defect PR #13 already demonstrated.

Eight properties, each enforced by a test rather than by intention:

1. **Append-only is one conditional request.** Publication is a single `PutObject` carrying
   `IfNoneMatch="*"`. There is **no preflight `HEAD`**. Because the licensed bucket has no
   versioning (ADR-0007, CLAUDE.md §4.23), *conditional publication in software is the immutability
   boundary* — there is no second line behind it.
2. **Only a `412` means occupied.** `412 PreconditionFailed` is the answer in which the condition
   was evaluated and failed because an object is there; it, and only it, reaches the occupancy
   resolution. `409 ConditionalRequestConflict` means a conflicting operation was in flight and the
   upload is retryable — the condition was never resolved. A 409 is classified `TRANSIENT`, sends
   **no `HeadObject`**, returns no outcome, and makes no idempotency or collision determination.
   This slice adds **no retry loop**; a future authorized caller may retry the whole
   `put_if_absent`, and that is safe only because every attempt stays conditional.
3. **Integrity is a full-object SHA-256, never an ETag, and never a composite.** Every write sends
   `ChecksumAlgorithm="SHA256"` and the expected `ChecksumSHA256`. Every read-back requires a
   checksum **and** requires S3 to state `ChecksumType="FULL_OBJECT"`. A `COMPOSITE` SHA-256 is a
   digest of part digests: it depends on the upload's part size as well as the object's bytes, so it
   has the ETag's defect wearing the right algorithm's name. An absent, non-string, composite or
   unrecognised type is refused — an allowlist of one, matched exactly, because a denylist would
   admit every checksum type AWS has not invented yet.
4. **A collision is resolved by metadata, never by downloading.** When the conditional write
   reports the name occupied, `HeadObject` supplies the stored checksum and length. Identical
   digest **and** length → the publication is a no-op and reports `stored=False`. Anything else →
   `ObjectAlreadyExistsError`. The bytes are never retrieved: this store has no read surface, and
   downloading vendor payloads to compare them would put licensed rows into a process with no
   business holding them.
5. **Unverifiable is a refusal.** A `HeadObject` response is accepted only when all five hold: it
   is a mapping; `ChecksumType` is exactly `FULL_OBJECT`; `ChecksumSHA256` is canonical base64; it
   decodes to exactly 32 bytes; and `ContentLength` is an exact non-negative integer. Anything else
   produces `INVALID_RESPONSE` — never a guess in either direction.
6. **Backend errors are sanitized into a closed vocabulary.** Every failure becomes an
   `ObjectStoreBackendError` carrying one `ObjectStoreOperation` and one `ObjectStoreFailure`, both
   `StrEnum` members. The original exception is suppressed with `from None`, so no bucket, key,
   endpoint, request id, host id or credential-shaped text can reach a traceback, a log or a
   message. The store's `__repr__` is the constant `S3ResearchObjectStore(classification=LICENSED)`.
7. **The write surface is the whole surface.** The injected client protocol declares `put_object`
   and `head_object` and nothing else — no `get_object`, `delete_object`, `list_objects_v2` or
   `copy_object`. Deletion belongs to the separately roled path under ADR-0007, and a routine
   research writer must never receive it.
8. **CONTROL is not publishable.** `DataClassification.CONTROL` is refused at admission, in this
   slice, on the same footing as in the in-memory backend. CONTROL publication remains deferred.

### The SDK is a dependency, and is imported by nothing

`boto3>=1.36.0,<2.0` becomes the project's **first and only** runtime dependency. It is declared
because a real deployment must *construct* a signed client, and request signing, credential
resolution and retry behaviour must be the official SDK's rather than anything written here — a
hand-rolled signer would be a security-critical component with no review surface and no upstream
fixes.

**The floor is substantiated, not guessed.** It was checked by reading the S3 service model bundled
with `boto3==1.36.0` and `botocore==1.36.0` — the lowest `botocore` that release permits — in a
throwaway environment, offline with respect to AWS. Every member this store depends on is present
at that floor: `PutObject` accepts `Bucket`, `Key`, `Body`, `ContentLength`, `ContentType`,
`ChecksumAlgorithm`, `ChecksumSHA256`, `ServerSideEncryption` and `IfNoneMatch`; `HeadObject`
accepts `ChecksumMode` and returns `ChecksumSHA256`, `ChecksumType` and `ContentLength`; and the
model's `ChecksumType` shape is exactly the enum `["COMPOSITE", "FULL_OBJECT"]`, which is where the
two spellings in this document come from. The ceiling keeps a major-version change a reviewed
decision.

**No module under `src/` imports it.** The client is injected, so importing the data platform pulls
in no AWS code, opens no socket and performs no ambient credential discovery. Backend exceptions are
classified **structurally**, by the shape a `ClientError` actually has, so a stub, a real error and
a subclass are all handled without an SDK type. A static test permits only
`src/kalpamani/data/storage/s3.py` — the sole application module under `src/` permitted to do so —
to name the SDK at all, and a second test asserts that even that module imports none of it today.
The scan covers `src/`; the tests and this ADR necessarily name the SDK, and are not application
code.

### Storage becomes a package

`src/kalpamani/data/storage.py` moves to `src/kalpamani/data/storage/local.py` (via `git mv`,
history preserved, content unchanged), and `storage/__init__.py` re-exports the local table store so
every existing import means exactly what it always did. **`s3` is deliberately not re-exported**: a
convenience re-export would make every importer of the local table store transitively depend on the
AWS boundary. Reaching the S3 store is an explicit `from kalpamani.data.storage.s3 import ...`, and
it should read like a decision.

### Admission rules are shared, not duplicated

Three helpers — `require_exact_key`, `require_publishable`, `physical_key` — move into the neutral
`objectstore` module and are used by **both** backends. Two implementations of "what may be
published" would eventually disagree, and the disagreement would be discovered as a divergence
between what a test proved and what a bucket holds.

`physical_key` is where the classification prefix is consumed: the logical key keeps `licensed/...`,
and the physical key does not repeat it, because the bucket **is** the classification.

---

## 3. Alternatives considered

**Emulate S3 with `moto` or LocalStack.** Rejected. An emulator is a second implementation of S3's
semantics to be wrong about, and a large dependency to carry for it. A synthetic in-process client
proves what the adapter *sends* — the conditional header, the checksum, the encryption — and what it
refuses to guess at, which is the part that has to be right. Where an emulator would help most
(conditional-write atomicity) the synthetic client is explicitly built to help: its conditional put
holds a lock across the occupancy check and the store, so a check-then-write adapter would **fail**
the concurrency tests rather than pass them by luck.

**Wait until a credential is bound and write it during ingestion.** Rejected — the reason this ADR
exists. Race conditions, checksum semantics and error sanitisation are exactly the work that goes
badly when it is in the way of something else.

**Enable bucket versioning so overwrites are recoverable.** Rejected, and not a close call. It is
forbidden by CLAUDE.md §4.23 and ADR-0007: a vendor termination arriving without notice must be
honourable inside 30 days, and versioning leaves copies behind. Durability is bought in software
instead.

**Let the store construct its own client from the environment.** Rejected. Ambient credential
discovery at import time is how a test run, a linter or an editor plug-in ends up holding
credentials it was never given. Injection keeps every construction site visible, and there is no
authorized construction site yet.

**Trust the ETag when a checksum is unavailable.** Rejected. See §1.

---

## 4. Consequences

**Gained.** The neutral contract now has a second, genuinely different backend, which is the only
way to know the protocol was a seam rather than a shape that fitted one implementation — the
existing provider-neutral Bronze publisher runs unchanged through it in test. Append-only,
integrity, sanitisation and the absence of a delete path are now properties with tests attached
rather than intentions. All of it is reviewable before the first byte and the first dollar.

**Given up.** The zero-runtime-dependency posture, deliberately and once, for the AWS SDK alone.
Every other SDK, data engine, database driver, brokerage client and emulator remains refused by
name, and the guard that used to say "none" now says "exactly one, and only one module may name it".

**Not gained — stated exhaustively.** This ADR authorizes **code, tests, documentation and
synthetic validation only.** It does not authorize, and merging it does not enable:

> any AWS mutation or read · running `aws_foundation_verify.py` · Terraform plan, apply or destroy ·
> retrieving Terraform outputs · retrieving, disclosing or binding a bucket name · creating,
> retrieving or configuring a credential · constructing a client · any Sharadar API call · use of
> the published test token · Services Data access or ingestion · bulk download · empirical
> qualification · production backfill · Silver or Gold real-data work · an ingestion runner · an ECS
> task definition or image · CONTROL publication · any broker, LEAN, strategy or risk change · live
> trading

**Unchanged.** **G1 OPEN · G2 OPEN · G3 CLOSED (Sharadar personal use, ADR-0008) · G4 OPEN ·
G5 OPEN · G6 OPEN · G7 OPEN.** ADR-0005 remains **PROPOSED**. Phase 3 remains **NOT COMPLETE**.
No provider is selected. `LIVE_TRADING_HARD_DISABLED` remains **True**.

**The separation that makes this safe is not that the code is careful.** It is that nothing in this
repository binds a credential or a bucket identifier to the store, constructs a client, or calls it
— each verified by a static test, not asserted here.

| Exists in this repository | Absent from this repository |
|---|---|
| the adapter | any construction of it |
| the injected client protocol | any client |
| a synthetic in-process client | any bucket name, ARN, account id or endpoint |
| tests that never open a socket | any credential, profile, runner or `__main__` |

The right-hand column is scoped to this repository and this slice. It says nothing about what
exists in the owner's AWS account or vendor account, which this slice did not examine and must not
infer.

---

## 5. Verification

Enforced by test, not by review:

| Property | How |
|---|---|
| no preflight `HEAD` before a first publication | recorded call log on the synthetic client |
| exactly one conditional `PutObject` per object | `IfNoneMatch="*"` asserted on every call |
| a `412` performs exactly one metadata-only occupancy resolution | recorded `HeadObject` call log |
| a `409` (both spellings) is `PUT: TRANSIENT` | parametrised classification and end-to-end tests |
| a `409` sends no `HeadObject`, yields no outcome and no collision | recorded call log; exception-type assertion |
| a retry after a `409` is still conditional | both recorded `PutObject` calls carry `IfNoneMatch="*"` |
| SSE-S3 requested explicitly, never inherited | `ServerSideEncryption="AES256"` on every call |
| SHA-256 sent and verified; ETag never consulted | checksum encoding tests; `ETag` absent from the adapter's executable code |
| identical replay is a no-op reporting `stored=False` | idempotency and concurrency tests |
| a differing object at an occupied name is refused | collision tests |
| an unverifiable `HeadObject` response fails closed | nine parametrised malformed responses |
| an absent, `COMPOSITE`, misspelled, unknown or non-string `ChecksumType` is refused | nine parametrised types, on both `exists` and the occupancy path |
| a matching ETag does not rescue an unproven checksum type | dedicated test |
| the declared SDK floor exposes every member used | local inspection of the model bundled with `boto3==1.36.0` / `botocore==1.36.0` |
| two concurrent writers of different bytes → one object, one refusal | threaded concurrency test |
| no bucket, key, endpoint, request id, host id or credential text escapes | leak canaries planted in the synthetic error, plus `__cause__ is None` |
| only `data/storage/s3.py` may name the AWS SDK | AST scan over `src/` |
| nothing constructs a client or a store | AST scan for construction sites |
| no read, list, delete, copy or multipart surface | AST scan of docstring-stripped code |
| importing `kalpamani.data.storage` pulls in no S3 module and no SDK | fresh-interpreter subprocess probe |
| runtime dependencies are exactly `["boto3>=1.36.0,<2.0"]` | four independent guards |

**Every test is synthetic and offline. No test in this repository contacts AWS, and none can:
there is nothing to contact it with.**

