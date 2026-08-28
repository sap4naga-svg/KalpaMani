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

The decision this ADR records is **when** to write that code: **before** a credential exists,
**before** a bucket is bound, and **before** a bill is running — so the parts that are easy to get
subtly wrong are reviewed calmly rather than under the pressure of a half-finished ingestion.

### The specific things that are easy to get wrong

| | |
|---|---|
| **Check-then-write** | A `HEAD`, then a `PUT`, is a time-of-check/time-of-use race. Between the two, another writer can land an object, and the `PUT` then destroys evidence that verified a moment earlier |
| **ETag as identity** | An ETag is a multipart-dependent opaque token, **not** a content hash. Treating it as one makes every identity claim in the system conditional on how an object happened to be uploaded |
| **Ambiguity read as success** | An occupied name whose contents cannot be *proven* identical is not "probably fine". A permission failure is not absence |
| **Backend errors as messages** | A raw `ClientError` string carries the bucket, the key, an endpoint host, a request id and sometimes credential-shaped text. Logged or raised verbatim, it publishes exactly what CLAUDE.md §3 forbids committing |
| **Overwrite protection that is not there** | The licensed bucket carries **no versioning** by design. S3 cannot protect an overwrite for us here |

---

## 2. Decision

**Implement `S3ResearchObjectStore`, the LICENSED-only S3 backend of the neutral
`ResearchObjectStore` protocol, as reviewed code that has never been run against AWS.**

Seven properties, each enforced by a test rather than by intention:

1. **Append-only is one conditional request.** Publication is a single `PutObject` carrying
   `IfNoneMatch="*"`. There is **no preflight `HEAD`**. Because the licensed bucket has no
   versioning (ADR-0007, CLAUDE.md §4.23), *conditional publication in software is the immutability
   boundary* — there is no second line behind it.
2. **Integrity is full-object SHA-256, never ETag.** Every write sends
   `ChecksumAlgorithm="SHA256"` and the expected `ChecksumSHA256`. Every read-back requires one and
   verifies it.
3. **A collision is resolved by metadata, never by downloading.** When the conditional write
   reports the name occupied, `HeadObject` supplies the stored checksum and length. Identical
   digest **and** length → the publication is a no-op and reports `stored=False`. Anything else →
   `ObjectAlreadyExistsError`. The bytes are never retrieved: this store has no read surface, and
   downloading vendor payloads to compare them would put licensed rows into a process with no
   business holding them.
4. **Unverifiable is a refusal.** A `HeadObject` response that is not a mapping, or whose
   `ChecksumSHA256` is absent, non-canonical base64 or not 32 bytes, or whose `ContentLength` is
   absent, non-integer or negative, produces `INVALID_RESPONSE` — never a guess in either
   direction.
5. **Backend errors are sanitized into a closed vocabulary.** Every failure becomes an
   `ObjectStoreBackendError` carrying one `ObjectStoreOperation` and one `ObjectStoreFailure`, both
   `StrEnum` members. The original exception is suppressed with `from None`, so no bucket, key,
   endpoint, request id, host id or credential-shaped text can reach a traceback, a log or a
   message. The store's `__repr__` is the constant `S3ResearchObjectStore(classification=LICENSED)`.
6. **The write surface is the whole surface.** The injected client protocol declares `put_object`
   and `head_object` and nothing else — no `get_object`, `delete_object`, `list_objects_v2` or
   `copy_object`. Deletion belongs to the separately roled path under ADR-0007, and a routine
   research writer must never receive it.
7. **CONTROL is not publishable.** `DataClassification.CONTROL` is refused at admission, in this
   slice, on the same footing as in the in-memory backend. CONTROL publication remains deferred.

### The SDK is a dependency, and is imported by nothing

`boto3>=1.36.0,<2.0` becomes the project's **first and only** runtime dependency. It is declared
because a real deployment must *construct* a signed client, and request signing, credential
resolution and retry behaviour must be the official SDK's rather than anything written here — a
hand-rolled signer would be a security-critical component with no review surface and no upstream
fixes.

**No module under `src/` imports it.** The client is injected, so importing the data platform pulls
in no AWS code, opens no socket and performs no ambient credential discovery. Backend exceptions are
classified **structurally**, by the shape a `ClientError` actually has, so a stub, a real error and
a subclass are all handled without an SDK type. A static test permits only
`src/kalpamani/data/storage/s3.py` to name the SDK at all, and a second test asserts that even that
module imports none of it today.

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

**Wait until a credential exists and write it during ingestion.** Rejected — the reason this ADR
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

**The separation that makes this safe is not that the code is careful.** It is that the code has no
credential, no bucket, no client, no runner and no caller — each verified by a static test, not
asserted here.

| Exists in this repository | Does not exist |
|---|---|
| the adapter | any construction of it |
| the injected client protocol | any client |
| a synthetic in-process client | a bucket name, an ARN, an account id, an endpoint |
| tests that never open a socket | a credential, a profile, a runner, a `__main__` |

---

## 5. Verification

Enforced by test, not by review:

| Property | How |
|---|---|
| no preflight `HEAD` before a first publication | recorded call log on the synthetic client |
| exactly one conditional `PutObject` per object | `IfNoneMatch="*"` asserted on every call |
| SSE-S3 requested explicitly, never inherited | `ServerSideEncryption="AES256"` on every call |
| SHA-256 sent and verified; ETag never consulted | checksum encoding tests; `ETag` absent from the adapter's executable code |
| identical replay is a no-op reporting `stored=False` | idempotency and concurrency tests |
| a differing object at an occupied name is refused | collision tests |
| an unverifiable `HeadObject` response fails closed | nine parametrised malformed responses |
| two concurrent writers of different bytes → one object, one refusal | threaded concurrency test |
| no bucket, key, endpoint, request id, host id or credential text escapes | leak canaries planted in the synthetic error, plus `__cause__ is None` |
| only `data/storage/s3.py` may name the AWS SDK | AST scan over `src/` |
| nothing constructs a client or a store | AST scan for construction sites |
| no read, list, delete, copy or multipart surface | AST scan of docstring-stripped code |
| importing `kalpamani.data.storage` pulls in no S3 module and no SDK | fresh-interpreter subprocess probe |
| runtime dependencies are exactly `["boto3>=1.36.0,<2.0"]` | four independent guards |

**Every test is synthetic and offline. No test in this repository contacts AWS, and none can:
there is nothing to contact it with.**
