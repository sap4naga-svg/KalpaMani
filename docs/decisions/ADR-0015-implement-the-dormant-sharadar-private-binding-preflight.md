# ADR-0015 — Implement the Dormant Sharadar Private-Binding Preflight

**Status:** **Accepted — effective on the merge of the pull request that introduces this ADR.**
Until that merge it is proposed and carries no authority.
**Date:** 2026-08-29
**Deciders:** Project owner (human governance)
**Supersedes:** three live claims and nothing else — *"nothing constructs an AWS SDK client"*, *"no
credential source exists"*, and *"nothing calls the composition preflight"*. Each was true while no
binding path was authorized. It supersedes **no gate status**, no authorization boundary, and no
other property of [ADR-0011](ADR-0011-implement-the-licensed-s3-research-object-store.md),
[ADR-0012](ADR-0012-implement-the-dormant-sharadar-qualification-runtime-core.md) or
[ADR-0014](ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md) — their
append-only, integrity, redaction, ceiling, PIT and non-escape guarantees are untouched. **Accepted
ADRs are not rewritten.**
**Superseded by:** —
**Relates to:** [ADR-0005](ADR-0005-point-in-time-data-architecture.md) (the gate model),
[ADR-0007](ADR-0007-cloud-first-research-data-plane.md) (the governed AWS foundation, its identity
gate and its licensed bucket), [ADR-0008](ADR-0008-sharadar-personal-use-license-and-private-qualification.md)
(the licence this credential is used under),
[ADR-0009](ADR-0009-sharadar-provider-realistic-implementation.md) (the client and credential this
binds), [ADR-0011](ADR-0011-implement-the-licensed-s3-research-object-store.md) (the store this
binds), [ADR-0014](ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md) (the
composition this calls)
**Authority:** Blueprint V3.0 §11, §17, §19 · CLAUDE.md §4.4, §4.5, §4.21, §4.22, §4.23, §4.24, §7, §8

---

## 1. Context

Every accepted slice takes its private bindings by injection, and **none of them has ever had a way
to obtain one.** The credential is a parameter with no source. The bucket is a string with no
resolver. The S3 client is injected and nothing constructs one. That was the control, and it was
stated as one in every status document.

It was also the last piece nobody had written — and it is the piece where a real credential meets a
real transport and a real bucket meets a real store. Deferring it until the run was authorized would
have scheduled the least-reviewed code for the moment of highest pressure, next to the authorization
that makes it live. ADR-0014 made exactly this argument about the composition root; this is the same
argument one layer out.

### The owner's authorization, and its exact boundary

> I authorize the next KalpaMani implementation slice: a dormant, default-refusing operator binding
> preflight for the authenticated Sharadar qualification stack. This authorization covers **code,
> tests, documentation, audits, and synthetic/local validation only.**

### Three separate future events

**Private credential setup**, **a real binding preflight** and an **authenticated Sharadar
qualification run** are three decisions, not one, and **implementing this path is none of them.**

| | |
|---|---|
| **1. Private credential setup** | opening the vendor's API-key page, retrieving a key, creating or updating a Secrets Manager secret. **NOT AUTHORIZED**, and nothing here does it |
| **2. A real binding preflight** | running this entry point with real bindings: an SSO session, an STS call, a state read, a secret read. **NOT AUTHORIZED**, and it has never been run |
| **3. An authenticated qualification run** | fetching from the provider and publishing to the licensed bucket. **NOT AUTHORIZED**, and no code path here could reach it |

---

## 2. Decision

**Implement one operator entry point that is refused by default and structurally unable to execute a
qualification run.**

`scripts/sharadar_binding_preflight.py`, plus one boundary module,
`src/kalpamani/data/ingest/sharadar/secrets.py`, and no third.

### Refusing by default

An ordinary import or an ordinary invocation performs **no environment lookup, no credential lookup,
no SDK construction, no state read, no bucket resolution, no socket, no provider call, no object-store
call and emits no private identifier.** The real factories import what they need *inside their own
bodies*, so importing the module pulls in no SDK, no verifier and no `os`.

The operational path requires one flag:

```
--i-am-the-operator-authorizing-binding-preflight
```

Deliberately unmistakable. `--run`, `--live`, `--execute` and `--force` are the things a person types
from habit on the wrong terminal; each is **refused by name**, with its reason, so a wrong reflex
fails loudly rather than doing something.

**It authorizes a binding preflight and nothing further.** It does not mint, imply or stand in for
authorization to execute a qualification run, and no code path consumes it as one.

### The authorization is a minted capability, not a boolean

This ADR's first revision specified `binding_authorized: bool`, checked as `is True`. **That was not
an authorization.** A caller who imported `run_binding_preflight` and passed `True` reached the
profile, identity and bucket stages with the flag never parsed — and a boolean is the one value every
caller already has.

`run_binding_preflight` now takes a **capability this module mints, only after the exact flag
parses**:

| | |
|---|---|
| **No public constructor** | `__init__` refuses any mint but a module-private sentinel |
| **No subclassing** | a subclass instance would satisfy `isinstance` while never having been minted |
| **Exact type *and* mint identity** | so a structural lookalike, a lookalike carrying a *borrowed* mint, an uninitialised `object.__new__` instance, a deep copy and a pickle round-trip are all refused |
| **Not exported** | neither the class, the sentinel, nor the minting function |
| **One mint call site** | inside `main`, in the branch the flag has already been checked in |

A **shallow copy** stays authorized, and that is correct rather than a hole: it holds the same
sentinel this module made, and copying an authorization manufactures no authority.

**What that claims, precisely.** No caller can construct or forge one through ordinary construction,
subclassing, copying, deserialisation or a structural lookalike. It is **not** a claim about hostile
runtime introspection: a process that can reach a module's private names can build one, as it can in
any Python program, and this ADR does not pretend otherwise.

### The order, which is the security property

1. explicit binding-preflight authorization
2. the exact AWS profile
3. the AWS account identity gate
4. governed licensed-bucket resolution
5. private credential retrieval
6. client and dependency construction
7. the accepted offline composition preflight
8. a closed result

No later stage runs after an earlier refusal, because a refusal raises. **A wrong-account session
never reaches a secret, and a failed gate never reaches a credential.** The ordering is proven by
counting which stages ran, not by reading the source.

**Nothing here reimplements a gate.** `AWS_PROFILE` pinning, the account-binding comparison and the
Terraform-state read all come from `scripts/aws_foundation_verify.py`, which already owns them under
ADR-0007. A second copy of account matching is a second thing to get wrong, and a test asserts this
module contains no `sts` call, no `get-caller-identity`, no `allowed_account_ids` parse and no
`terraform` invocation of its own.

**The licensed bucket, never CONTROL.** One named Terraform output, `licensed_bucket_name`. The
control bucket has a different key and this module never names it — checked, along with the word
`CONTROL` itself.

### The secrets boundary

`SecretsClient` is a one-method protocol: `get_secret_value`, and nothing else. No `list_secrets`, no
`describe_secret`, no `put_secret_value`, no `update_secret`, no `delete_secret` — so this boundary
could not enumerate, create, rotate or destroy a secret even if a later edit tried to. Reading one
value is the least authority that does the job.

| | |
|---|---|
| **Injected, like everything else** | a `boto3` client satisfies it structurally; **no module under `src/` imports the SDK**, so importing the data platform still opens no socket and performs no ambient credential discovery |
| **Nothing is compiled in** | no secret name, ARN, account, bucket, region or endpoint |
| **`SecretString` only** | `SecretBinary` is **refused, not decoded**. An API key is printable text; guessing at an encoding is how a wrong value reaches a request |
| **No fallback of any kind** | no JSON parsing, no key guessing, no alias, no default, no conversion. The secret's value *is* the credential; a secret holding something else is a configuration error to fix at the source |
| **Straight into the credential** | the value is handed immediately to `SharadarCredential` and is never bound to a surviving local, logged, returned or included in a refusal |
| **Fail closed** | missing, blank, binary, non-string, malformed and unusable responses each map to a closed `SecretRetrievalFailure` member |
| **`from None`, always** | a backend exception quotes the secret name, usually the ARN and often the account. Suppressing the cause keeps it out of the traceback too |

`SharadarCredential` is unchanged, and no second credential representation is introduced.

### The secret identifier never travels in argv

This ADR's first revision specified `--secret-id`. **A private identifier on the command line enters
shell history and every process listing on the machine**, whether or not the program prints it —
redacting output does not help once the value is in `argv`.

The identifier now comes from an **injected zero-argument source**, invoked **once**, only after
authorization, profile, identity and bucket resolution have all passed, and immediately before the
credential is retrieved. A private identifier must not be resolved on a path that is going to refuse.

The production source reads **one fixed, non-secret environment-variable name**,
`KALPAMANI_SHARADAR_SECRET_ID`. The *name* is a constant and is committed; the *value* is private and
is never printed, logged, returned or included in a refusal. `os` is imported inside the factory
body, so an ordinary import and every refusal path perform no environment lookup of it at all.

`--secret-id`, `--secret-name`, `--secretid`, `--secret-arn` and `--secret` are **refused by name**
with their reason, rather than silently ignored — an unrecognised-argument error teaches nothing and
invites a second spelling. A missing, blank, non-string, `str`-subclassed or raising source becomes
the closed `REFUSED_CREDENTIAL` outcome, raised `from None`, naming nothing.

**One honest limit.** "Zero environment lookups on the default path" would be false, and this ADR
does not claim it: `argparse` reads `LANGUAGE`, `LC_ALL`, `LC_MESSAGES`, `LANG`, `COLUMNS` and
`LINES` while formatting its own output, whatever the program does. Those are locale and terminal
width, not secrets. What is claimed and tested is the property that matters — **the default path and
every earlier refusal read no credential-bearing variable at all**, and specifically never
`KALPAMANI_SHARADAR_SECRET_ID` or `AWS_PROFILE`.

### Offline composition only

The entry point calls `preflight_qualification_composition` and **nothing else**. There is no call to
`QualificationRuntime.execute`, to a transport's `get`, to `put_object`, to `head_object`, to a
publication helper or to an ingestion function — and no code here could construct one. The result is
the existing closed `QualificationPreflight` with status `VALIDATED_OFFLINE`.

**No permission-bearing vocabulary is added.** `READY`, `APPROVED`, `AUTHORIZED`, `PROCEED`,
`QUALIFIED` and `BOUND` are each refused anywhere in the output vocabulary, by test.

### What may be printed

A fixed allowlist of sentences, reachable through one function that takes a vocabulary member rather
than a string. No credential or fragment, no secret identifier, no bucket, no account, no ARN, no
profile, no region, no Terraform output, no URL, no plan subject, no empirical result and no provider
recommendation.

**The exit status reports command success or refusal only** — never a qualification verdict and never
provider suitability.

### Not the public-token harness

`scripts/sharadar_private_qualification.py` is a separate, owner-only instrument that reads the
vendor's *published* test token. This slice does not import, invoke, modify or repurpose it, the two
share no code, and the published token remains confined to that harness and to the audit that forbids
it elsewhere.

---

## 3. Alternatives considered

**Keep deferring until the run is authorized.** Rejected, for the reason ADR-0014 gave one layer in:
that schedules the least-reviewed code for the moment of highest pressure.

**Put the credential source in `src/`.** Rejected. A module under `src/` that resolved a credential
would make the data platform capable of ambient discovery on import, which is exactly the property
ADR-0011 and ADR-0014 preserved by injection. The boundary lives under `src/` because it is a
contract; the *construction* lives in a script because it is a deployment decision.

**Reuse the private qualification harness as the operator path.** Rejected, firmly. That harness is a
manual instrument reading a *published* token; fusing it with production wiring would put a
credential-reading module on the path every future runner takes.

**A shorter flag, or a config file.** Rejected. The flag is a governance control, and a control that
is convenient to type is one that gets typed by accident.

**Parse the secret as JSON and pick a key.** Rejected. Multi-key guessing means the wrong value can
be selected silently; a secret whose value is not the credential is a setup error, and the repair
belongs at the source.

---

## 4. Consequences

**Gained.** The last unwritten piece is written, reviewed and proven inert by counted calls. The
ordering that keeps a wrong account away from a secret is enforced by sequence and checked by
counting. And the repository can now say precisely where a credential could come from, instead of
saying it could not come from anywhere.

**Given up.** Three simple absence claims. *"Nothing constructs an SDK client"*, *"no credential
source exists"* and *"nothing calls the composition preflight"* were easy to verify and are no longer
true as stated. What replaces them is narrower and has to be maintained: **exactly one module may
construct an SDK client, exactly one may call the composition, the credential source refuses by
default, and none of it has ever been run.** Each clause is a test.

**Not gained — stated exhaustively.** This ADR authorizes **code, tests, documentation, audits and
synthetic/local validation only.** It does not authorize:

> opening the vendor's API-key page · retrieving, revealing, copying, rotating or storing a real API
> key · creating or updating a Secrets Manager secret · reading Secrets Manager · AWS SSO login, STS
> calls, remote-state reads, bucket resolution or any AWS request · Terraform init, plan, apply,
> output or verification · constructing a real service-bound AWS session or client during validation
> · Sharadar API calls or published-test-token probing · Services Data access, download, publication
> or ingestion · S3 `PutObject`, `HeadObject`, `GetObject`, listing or any other object call ·
> empirical qualification · bulk download · production backfill, update or ingestion · CONTROL
> publication · provider selection or G1/G2 closure · broker, LEAN, Paper expansion or live trading

**The first real credential setup, the first real binding preflight, and the first authenticated
qualification run each remain separately gated**, and this merge approaches none of them.

**Merging this slice selects no provider.** **G1 and G2 stay OPEN.**

**Unchanged.** `AcquisitionMode.QUALIFICATION` · `PROVIDER_REALISTIC_PIT` · the Q7 and Q8
dispositions · the `permaticker` treatment · append-only S3 semantics · acquisition identity · the
response and run ceilings · no-resume semantics · three-write reporting · CONTROL deferral ·
provider-neutral contracts · every production-ingestion boundary. **G1 OPEN · G2 OPEN · G3 CLOSED ·
G4 OPEN · G5 OPEN · G6 OPEN · G7 OPEN.** ADR-0005 remains **PROPOSED**. INC-0002 remains **OPEN**.
Phase 3 remains **NOT COMPLETE**. `LIVE_TRADING_HARD_DISABLED` remains **True**.

---

## 5. Verification

Enforced by test, not by review:

| Property | How |
|---|---|
| import does nothing | AST over module-level statements; no SDK, verifier, `os` or `urllib` import at module scope |
| invocation without the flag refuses before any stage | the stage recorder is empty, and the secrets client was never asked |
| authorization cannot be forged | sixteen cases: `True`, `False`, `1`, `0`, a string, the flag spelled as a string, an enum member, a float, a list, a mapping, a bare object, a truthy lookalike, a structural lookalike, a lookalike carrying a *borrowed* mint, the class itself, and the minting function |
| the capability has no public constructor | direct construction with any other mint raises |
| the capability refuses subclassing | class creation raises |
| an uninitialised instance is refused | `object.__new__` skips `__init__`, so no mint is carried |
| a copy is genuine, a deep copy and a pickle round-trip are not | all three exercised end to end |
| the mint has exactly one call site | AST over the module |
| the capability, mint and minting function are unexported | `__all__` and private-name assertions |
| a profile mismatch refuses before the identity call | stages recorded: `["profile"]` |
| an identity failure refuses before state, secret or composition | stages recorded: `["profile", "identity"]` |
| a bucket failure refuses before secret retrieval | stages recorded: `["profile", "identity", "bucket"]`; secret calls `0` |
| a secret failure refuses before composition | S3 and transport call counts `0` |
| the authorized ordering is exact | the full recorded sequence is asserted, not sampled |
| every backend exception is sanitized and raised `from None` | `__cause__ is None` and `__suppress_context__ is True` |
| every unusable secret response is refused | ten cases: empty, binary-only, blank, empty string, null, integer, bytes, whitespace-bearing, control character, not a mapping |
| a malformed secret identifier is refused before the backend | `None`, empty, blank, non-`str`, a space, a newline — with the backend call count at `0` |
| no secret option exists on the command line | six spellings refused by name, the equals form included, and the parser exposes no such destination |
| the identifier is untouched by every earlier refusal | authorization, profile, identity and bucket refusals each leave the source call count at `0` |
| the identifier is resolved once, in order | after the bucket and before the backend, counted |
| a raising or unusable source is a sanitized refusal | seven cases, including a `str` subclass |
| the default path reads no credential-bearing variable | the environment is replaced by a recorder; only stdlib formatting variables appear |
| the licensed bucket is used and CONTROL is structurally refused | the output key is named; `control_bucket_name`, `control_bucket` and `CONTROL` are absent from the module |
| the composition preflight is invoked exactly once | spied and counted |
| provider transport calls | **zero** |
| S3 `put_object` / `head_object` calls | **zero** |
| `reveal()` calls during preflight | **zero**, measured by patching the credential class |
| no qualification runtime execution | `execute` replaced with a raising stub for the duration |
| nothing escapes in the result | everything reachable is walked; no client, store, runtime, credential or callable is in it |
| the status is exactly `VALIDATED_OFFLINE` | identity assertion, plus the fixed mode and profile |
| no permission-bearing output vocabulary | every member checked against six forbidden words |
| no private identifier or credential literal in tracked files | the entry point and the boundary scanned for a token, an ARN, an endpoint, an `s3://` and any twelve-digit number |
| five leak canaries never surface | a key, a secret identifier, a bucket, an account and a backend message, against every stage's refusal, the successful result, `repr`, `str`, stdout and stderr |
| one entry point, and no re-export | the installed package exposes none of its names |
| only that entry point constructs an SDK client | AST and text scan over `src/`, `scripts/` and `tests/` |
| no module under `src/` imports the SDK | AST import scan |
| only that entry point calls the composition | AST scan, with its own tests excepted |
| no execution or publication operation in the entry point | source scan for `execute`, `put_object`, `head_object`, `put_if_absent`, the publication helpers and `fetch` |
| no task, image, scheduler or service | source scan |
| no module-level mutable state | AST over module-level assignments |
| the private harness is untouched | no import of it, and the file still exists |
| the published token stays in its harness | scan over `src/` and `scripts/`, excepting the harness and the audit that forbids it |
| the pinned profile and region match the governed verifier | read from `aws_foundation_verify.py`, not restated |
| no gate is reimplemented | `identity_gate` and `tf_outputs` are used; `sts`, `get-caller-identity`, `allowed_account_ids` and `terraform` are absent |

**Every test is synthetic and offline.** Every client is a local class, every secret value is a
self-labelled synthetic string, and **the real factories are never called** — a test that called one
would construct an SDK client, which is the thing this slice is not authorized to do.
