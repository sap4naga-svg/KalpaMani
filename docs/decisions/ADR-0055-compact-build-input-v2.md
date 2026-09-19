# ADR-0055 — The compact, digest-bound research-build input (version 2): the 32-run ceiling made reachable inside the unchanged 8 KiB advanced-tier limit

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged at its exact head.**

While the pull request introducing this ADR is open, ADR-0055 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On the exact-head
merge of that pull request this ADR becomes **ACCEPTED / IN FORCE** as **the one contract decision of §2 —
the version-2 build input, its producer-side and consumer-side obligations, the historical disposition of
version 1 — together with the two refusal-boundary corrections of §3 and the amendments of §5, and nothing
else**, effective together with the offline runtime and tooling change merged beside it. **Acceptance
authorizes no deployment and no execution** (§7): no image build, no registry publication, no Terraform,
no registration change, no AWS task, no S3 operation, no production build, no backtest and no trade — each
stays its own written authorization, and §6 states what the next one would have to cover.

**The register rows of this pull request describe the post-merge state.** They say *ACCEPTED / IN FORCE —
PR #138 merged* because that is what an exact-head merge of this pull request makes true, and no later
activation synchronization is owed; if the pull request is not merged at its reviewed head, none of those
rows is true and this document stays proposed.

**Nothing was run against AWS to produce this decision.** No AWS call, no STS call, no S3 operation, no
image built or pulled, no credential retrieved, no provider request. The only real artifacts read were the
owner's private launch store and the nineteen preserved run locators beside it, read-only, on the
workstation, to establish the facts of §1; every other result beside this text is a counting fake's, on
synthetic temporary files. **Mocked results are not AWS verification.**

---

## 1. Context — the first production build could not be prepared

**The S10c preparation stopped at the advanced-tier ceiling.** On 2026-09-19 (UTC) the owner authorized the
offline preparation of the first S10c production build over the eighteen O-5 runs (855 coordinates, 2,601
writes, ledger digest `88dc5795…`). The preparation tool materialized the version-1 build input the accepted
contract required — one whole owner-ledger row per run: identity, slice, plan digest, outcome, launch and
completion instants — and the canonical document came to **8,266 bytes**. The advanced-tier parameter
ceiling ADR-0036 §2.6 fixes is **8,192 bytes**. Seventeen rows fit (7,784 bytes); eighteen did not, and the
accepted ceiling of **32 runs per build** (`MAX_BUILD_RUNS`) was therefore unreachable by the contract that
declared it. The stop is preserved as evidence: the 8,266-byte document
(`build-input-build-20260918T234038Z-6421d019.json`, SHA-256 `7fa1c15e…`) is unchanged, and the in-memory
identity the stopped preparation allocated (`build-20260919T011419Z-b6e5ce65`) was never written, never
consumed and is not reused.

**Two tooling defects were recorded at the same stop.** First, the ceiling was enforced by the launcher's
`LaunchAuthorization` constructor as a raw `ValueError`, which the launch tool did not classify — the
preparation ended in a traceback rather than a closed refusal. Second, nothing enforced the ceiling during
materialization: a document was produced first and refused afterwards, so the byte ceiling was a consequence
a caller discovered rather than a rule the materializer applied. Neither defect wrote anything.

**The owner's decision, verbatim (2026-09-19; owner-input D-23):**

> I select Option A for S10c: replace the redundant build-input row representation with a compact, lossless
> and strictly validated contract that makes the accepted 32-run ceiling genuinely reachable within the
> unchanged 8 KiB advanced-parameter limit. The compact form may remove only values that are
> deterministically derived from the run identity, locator key or validated locator content; it must
> preserve cryptographic binding, fail closed on every mismatch, retain v1 as historical evidence only, and
> weaken no acquisition, build, point-in-time, schema, completion, write-order or audit requirement. I also
> authorize fixing the raw-ValueError refusal boundary and enforcing the byte ceiling during
> materialization. This authorizes repository governance/tooling/runtime changes and an exact-head merge,
> but no image build, registry publication, Terraform, registration change, AWS task, S3 operation,
> production build, backtest or trade.

**Why the row was redundant.** Every value the version-1 row carried beside the run identity is already
inside the run locator the build actor retrieves for that identity — the locator (ADR-0036 §2.4) records the
run's `plan_digest`, its `slice`, its `started_at` and `completed_at`, and the identity itself — and the
locator's key is derived from the identity alone (`bronze/sharadar/_indexes/<run-id>.json`). The accepted
validator recompiles the plan from the locator's own slice and holds its digest to the locator's; it holds
every entry to the compiled request at its ordinal; it requires `COMPLETE` and a known publication state. What
the embedded row added was a **second copy** of those values, compared against the first under ADR-0036 §2.4
clause 1. The copy carried a binding — *this locator is the one the owner admitted* — and that binding is what
the compact form must keep without the copy.

---

## 2. Decision — the version-2 build input

### 2.1 The contract

The research-build input parameter carries **`kalpamani-research-build-input/v2`**, `schema_version = 2`.
The envelope is unchanged in shape — `schema_version`, `contract_id`, `build_identity`, `runs`,
`ledger_digest`, `issued_at`, `expires_at`, no other field — and each row of `runs` is exactly

```text
{"run_identity": <run-id>, "locator_sha256": <64 lowercase hex>}
```

`ledger_digest` is the SHA-256 of the canonical serialization of `runs` **as delivered**, so the whole
program — every identity, every digest, their order — is one binding; a row reordered, altered, added or
removed changes it, and the task refuses `LEDGER_DIGEST_MISMATCH` before any object is read. `runs` is
non-empty for a production build (`NO_RUNS`; a verification-only launch may carry an empty set, ADR-0045
§11), at most `MAX_BUILD_RUNS = 32` (`TOO_MANY_RUNS`), every identity distinct (`IDENTITY_DUPLICATED`) and
in the run-id grammar, every digest distinct (`LOCATOR_DIGEST_DUPLICATED` — one locator binds one run), and a
row with any other field, a missing field, a malformed identity or a malformed digest is `ROW_MALFORMED`.
Validity, expiry and the 24-hour bound are unchanged. **`MAX_BUILD_RUNS` is not reduced; the 8 KiB ceiling is
not raised; no partial or two-part build is introduced.**

### 2.2 Field-by-field mapping, version 1 → version 2

| version-1 row field | version-2 disposition | where the task now takes it from | held by |
|---|---|---|---|
| `run_identity` | **kept** | the row | grammar; distinctness; the locator's declared `run_id` must equal it (`IDENTITY_MISMATCH`) |
| — | **added: `locator_sha256`** | the row | the full SHA-256 of the retrieved locator bytes must equal it, compared in constant time, **before decoding** (`LOCATOR_DIGEST_MISMATCH`) |
| `slice` | **removed** — derived | the validated locator's own `slice` | the accepted validator recompiles the plan from it and holds every entry to the compiled coordinates (ADR-0036 §2.4 clauses 1–3, unchanged) |
| `plan_digest` | **removed** — derived | the validated locator's own `plan_digest` | equals the digest of the plan recompiled from the locator's slice (`PLAN_DIGEST_MISMATCH` / `PLAN_NOT_COMPILABLE`) |
| `outcome` | **removed** — fixed | a locator that validates is a completed run | the locator must be `COMPLETE` with a known publication state (clause 4); `HALTED` has no locator to bind |
| `launched_at` | **removed** — derived | the locator's own `started_at` | instant grammar; `completed_at ≥ started_at` |
| `completed_at` | **removed** — derived | the locator's own `completed_at` | as above |

Nothing else was removed, and nothing was removed that the run identity, the locator key or the validated
locator content does not determine. The ledger-row view every downstream consumer reads (`VerifiedRun.row`)
is rebuilt from those derived values, so the build processing, the Silver/Gold/manifest path, the
availability rules and the write order see the same `LedgerRow` shape they saw before and are unchanged.

### 2.3 The producer's obligation — the owner side binds every locator to its ledger row first

The compact row moves the *owner's* copy of the binding to the owner's side, where the ledger lives. Before a
build input is materialized, the launch tool reads the preserved locator bytes for every named run from
beside the ledger (`<ledger dir>/locators/run-locator-<identity>.json`, exactly as the retrieval procedure
preserved them), and **`bind_run_locators`** holds each to its **true ledger row** through the unchanged
accepted validator — identity, plan recompiled from the row's slice, entries against the compiled plan,
counts, completeness — before recording its SHA-256. A missing locator is `LOCATOR_MISSING`; a locator that
fails the row is `LOCATOR_REFUSED`; two runs whose locators hash alike are `LOCATOR_DIGEST_DUPLICATE`. The
digest the row carries is therefore the digest of a document the owner's tooling has already validated
against the ledger, and the ledger stays where ADR-0035 §3.1 keeps it.

### 2.4 The consumer's obligation — the task trusts nothing it has not hashed

For each row, in order, the build actor derives the locator key from the identity, retrieves the object by
exact name, and — **before any decode** — computes the full SHA-256 of the retrieved bytes and compares it to
the row's digest in constant time. Only a locator whose bytes hash to the row is decoded; its declared `run_id`
must equal the row's identity; the ledger-row view is derived from its own content (§2.2); and the accepted
validator runs unchanged over it. Every mismatch refuses that run and the build publishes nothing
(`LOCATOR_DIGEST_MISMATCH`, `LOCATOR_INVALID`). The exact-read discipline for every payload and record the
locator names — full-object SHA-256 and byte count before parsing — is unchanged.

### 2.5 The byte ceiling is one rule, applied where the bytes are made

`MAX_BUILD_INPUT_DOCUMENT_BYTES = MAX_ADVANCED_PARAMETER_BYTES = 8,192`. The materializer computes the
canonical bytes and applies `check_input_size` **before returning them** — so nothing over the ceiling can
be written to a file, a record or a parameter — and the task applies the same function to the delivered
bytes before parsing (`TOO_LARGE`), as it always did. The launcher's constructor check remains as a third,
now-unreachable guard.

### 2.6 The 32-run proof

With every field at its widest valid width — 64-character run identities (the grammar's ceiling), 64-hex
digests, a 64-character build identity, microsecond-precision instants — a 32-row version-2 document
canonicalizes to **5,717 bytes**, leaving a margin of **2,475 bytes** under 8,192; the eighteen O-5 rows at
their real widths come to well under 1,300 bytes. The proof is a test (`WORST_CASE_32_RUN_BYTES`), not a
sentence: the constant is asserted equal to the measured size and the margin asserted ≥ 512.

### 2.7 Version 1 — historical evidence, never execution

`kalpamani-research-build-input/v1` is retained as a **historical** contract: `parse_historical_build_input_v1`
reads a retained version-1 document under the version-1 rules into a distinct type (`HistoricalBuildInputV1`)
that no execution path accepts — `parse_build_input` refuses a version-1 document (`SCHEMA_VERSION_UNKNOWN`;
relabelled, `CONTRACT_ID_UNKNOWN`; relabelled twice, its rows are `ROW_MALFORMED`), `verify_build_inputs`
refuses the historical type outright, and no task entry and no launch-tool execution path names the
historical reader. The 8,266-byte document of §1 is preserved byte for byte, marked superseded for new
execution, and readable through that reader alone.

---

## 3. The two refusal-boundary corrections

1. **The raw `ValueError` no longer escapes.** A materialized input over the ceiling is a **closed refusal**
   of the launch tool — `refused_input_size`, exit code 20, one allowlisted sentence, no traceback — raised
   from the materializer's `INPUT_TOO_LARGE` before any specification, reservation, ledger row, consumed
   identity, file or client exists; and the constructor boundary is wrapped so that even an oversized value
   reaching it is the same closed refusal.
2. **The ceiling is enforced during materialization** (§2.5), not discovered afterwards.

Neither correction changes what is accepted; both change how a refusal is reported and where it happens.

---

## 4. What is unchanged — stated so it can be checked

The acquisition actor, its input contract (`kalpamani-production-acquisition-input/v2`), its plan, its
processing path, its provider adapter and its write-only publication are untouched; the locator schema and
its four validation clauses are unchanged; the exact-read discipline, the pagination admission, the Silver
revisions, the availability rules, the universe rule, the Gold adjustment and verification, the manifest and
its **last** write, the 3,600 s deadline, the spent-identity guard and the run reservation are unchanged; no
IAM policy, bucket policy, Terraform declaration, task-definition resource, network matrix or registration
schema changes; `MAX_BUILD_RUNS` and `MAX_ADVANCED_PARAMETER_BYTES` are the numbers they were. **The compact
form removes redundancy; it weakens no acquisition, build, point-in-time, schema, completion, write-order or
audit requirement**, and the tests of §8 hold each of those sentences.

---

## 5. Amendments stated

- **ADR-0036 §2.6** — the build input's *content* column and *integrity* column are amended: for each run,
  the row carries the run identity and the SHA-256 of its admitted locator, not the owner's slice-ledger row;
  the contract id is `/v2`. **ADR-0036 §2.4 clause 1** is satisfied differently: identity binding holds the
  locator to the digest the row carries and to the identity that derived its key, and the plan-digest and
  slice equalities are established on the owner side against the true ledger row (§2.3) and on the task side
  by the validator over the locator's own content (§2.4). Recorded as ADR-0036 §7.
- **ADR-0045 §6** — the launch tool's build-side preparation gains one input (the preserved locators beside
  the ledger), one refusal (`refused_input_size`, exit 20) and the pre-write ceiling; **§7** applies as
  written: the build and build-verification actor families change commit, so both are rebuilt and their
  R-1/R-2 cells re-run before a production build revision is launched. Recorded as ADR-0045 §16.
- **ADR-0044** is not amended: the acquisition input v2, the receipt, the release and the packaging are
  untouched.

Every amendment is a dated section appended to the amended document; no accepted text is rewritten.

---

## 6. Deployment consequences — stated, not performed

Every production image carries the one source tree, so the closure is stated on what **executes**: the
version-2 parser is called only under the build actor (the runner's build branch, the build launch records,
the build launch tool), the digest-bound locator read only by the build-side verifier, and the acquisition
entry's admission path names none of the new symbols. The consequences of merging this pull request are
therefore:

| | |
|---|---|
| **images to rebuild** | the **build** and **build-verification** images only, from the merge commit's exact tree; the acquisition and acquisition-verification images stay at their published commit (per-actor commit divergence is the accepted state — the probes are already at a later commit than the acquisitions) |
| **compiled configurations** | two new S1 configurations, and therefore two new configuration digests and one new release commit |
| **task definitions** | two replacements (build, build-verify), each a new revision under the same family |
| **launcher policy** | the build launcher's `RunTask` resource moves to the new revisions (stage-b digest and revision update through the owner's tfvars) |
| **registration** | two blocks re-issued (build, build-verify); the acquisition blocks unchanged |
| **S9 cells** | the current build-family `R-1` and `R-2` cells are expected to derive **HISTORICAL** once the registration moves, exactly as ADR-0045 §7 states — left to the runner to derive, never hand-marked |
| **first build input** | ONE compact version-2 document is materialized offline after the merge over the eighteen O-5 runs, with no identity allocated or consumed, no specification, no client and no AWS call (§7) |

**None of the above is authorized by acceptance.** The next authorization would have to cover, at most:
generating the two S1 configurations, building and publishing the build and build-verification images,
updating the two tfvars digests, producing ONE saved plan, and stopping before apply.

---

## 7. Effectiveness and execution gates

```text
ADR-0055:                                       PROPOSED — NOT IN FORCE while its pull request is open
on the exact-head merge:                        ACCEPTED / IN FORCE — the §2 contract, the §3 corrections,
                                                the §5 amendments, and nothing else
build input contract in force after the merge:  kalpamani-research-build-input/v2 (schema_version 2)
version 1:                                      HISTORICAL — readable as evidence, refused for execution
the 8,266-byte v1 preparation document:         PRESERVED byte for byte, marked superseded for new execution
the stopped preparation's identity:             UNCONSUMED, NOT REUSED
MAX_BUILD_RUNS / advanced-tier ceiling:         32 / 8,192 bytes — UNCHANGED
32-run worst case:                              5,717 bytes, margin 2,475 — held by a test
image build / registry publication:             NOT AUTHORIZED
Terraform / tfvars / registration change:       NOT AUTHORIZED
AWS task / S3 operation / production build:     NOT AUTHORIZED
backtest / trade:                               NOT AUTHORIZED
```

**Acceptance authorizes nothing that runs.** It fixes a contract and corrects two refusal boundaries; the
images that would carry it, the plan that would deploy it and the build that would consume it are three
further gates, each its own written authorization.

---

## 8. How the decision is held

A dedicated test module (`tests/unit/test_adr_0055_build_input_v2.py`) covers: the exact eighteen-row
version-1 shape oversized and refused for execution; the eighteen-row compact document fitting and
round-tripping; the 32-run worst case at 5,717 bytes with its margin, and the materializer refusing a
33-run request; the materializer refusing an oversized document before returning bytes; one ceiling shared
by the materializer and the task; the producer binding every preserved locator to its true row and refusing a
missing, mismatched or shared one; the consumer refusing an altered digest before any content is trusted, a
wrong identity, reordered rows, a duplicate identity, a duplicate digest, a foreign prefix, a differing plan
or slice, an incomplete or unknown-state locator, and an unsupported completion; a valid compact input
reaching build admission unchanged with Silver, Gold and the manifest written in the accepted order; a task
refusing a version-1 input; the launch tool refusing an oversized input as a closed exit-20 refusal with no
traceback, no file, no reservation, no row and no client; the historical reader reachable from no execution
path; and the deployment closure of §6. Mutation controls remove the digest check, the identity check, the
byte ceiling, the duplicate detection, the version-1 execution refusal and the pre-write refusal boundary in
turn, and each removal is caught and reverted before the pull request is opened. One finding of that
exercise is recorded rather than smoothed over: removing the bound-locator read's own `run_id` comparison
alone is an **equivalent mutant**, because the accepted validator's clause 1 makes the same comparison a
step later; the effective identity guard is clause 1, the explicit line is defence in depth, and the control
that counts removes both. A seventh control removes the launch tool's mapping of `INPUT_TOO_LARGE` to the
sized refusal, and is caught.
