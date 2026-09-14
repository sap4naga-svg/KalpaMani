# ADR-0046 — Verification tooling: the production human-binding materializer, the R-3 verification tool, and the verification cell runner

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0046 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **the owner-side tooling that composes the accepted contracts for
readiness steps S5, S7 and S9 — the materializer gate for the two ADR-0036 §2.5 human bindings, the
R-3 tool that executes ADR-0036 §3's procedure and the sanitized record it produces, and the cell
runner that enumerates ADR-0036 §3's cells and derives their state from recorded evidence — together
with the two narrow contracts it adds (the R-3 verification record and the prepared-cells document)
and the one decision it defers (§4), and nothing else**, effective together with the offline code
merged beside it. **Acceptance authorizes no execution** (§6): no R-3 session, no binding
materialization against a real private root, no launch, no run, no probe, no analysis, no Terraform
plan or apply, no IAM change.

**Nothing was run to produce this decision.** No AWS call, no STS call, no S3 operation, no
container image built or pulled, no registry contacted, no credential retrieved, no provider request,
no private input inspected. Every result beside this text is a counting fake's, on synthetic
temporary files. **Mocked results are not AWS verification.**

---

## 1. Context

ADR-0045 (ACCEPTED / IN FORCE on the PR #104 merge, `af20f36acbe8a3006830762fbad5cb01d1e9b38b`)
completed the verification path: the verification entries, the launch tool, its records, the R-2
verdict rule. Readiness §7 and §9.4 then left three code gaps in front of the first runtime evidence:

| Gap | Readiness step | What was missing |
|---|---|---|
| G-4 | S7 | a materializer for the two production human bindings (`kalpamani-production-acquisition-runtime-binding/v1`, `kalpamani-research-build-runtime-binding/v1`); the qualification materializers write different contracts |
| G-5 | S5 | a tool executing R-3's nine counted rows, classifying the access-denied context and running the budgeted failure-path cleanup |
| G-6 | S8, S9 | a runner for the verification cells, composing the launch tool, the reservation store, the receipt validator and the verdict path, with a completion matrix |

Each is owner-side tooling over accepted contracts. None of them needs a new permission, a new
principal, a new task entry or a change to a production processing path.

## 2. Decision

### 2.1 The production human-binding materializer (`scripts/production_human_binding_materialize.py`)

The gate that creates one ADR-0036 §2.5 human binding, on the ADR-0025 materializer's pattern and
refusing by default. **One authorization names one actor**: `--i-am-the-owner-authorizing-acquisition-binding-materialization`
and `--i-am-the-owner-authorizing-research-build-binding-materialization` are mutually exclusive,
there is no `--actor` switch, and the destination is the actor's own fixed variable
(`constants_for(actor).binding_env_var`) — the variable the launch tool reads — so what is written is
what will be loaded. The source is the ADR-0024 environment binding (`KALPAMANI_QUALIFICATION_ENVIRONMENT_BINDING_FILE`),
loaded by the accepted loader against the governed local account; the account and the licensed
bucket are copied, the partition, region, schema, kind, contract and **profile** are the compiled
constants; the document is validated through `parse_production_runtime_binding` **before a byte is
written**, written by the one private-artifact writer (absolute path under the private root,
exclusive create, owner-only descriptor, read-back), re-read through `load_human_runtime_binding`
with the actor's own variable, and removed if it does not reload. Provenance names the reviewed
implementation of the binding contract (the approved head of PR #95 and its tree) and the digest of
the exact environment-binding bytes consumed. **An occupied destination is a refusal.** Every private
path arrives from the environment; every refusal is one closed sentence; no output names an account,
a bucket, a path, a profile or a digest.

**Materializing is not verifying.** The command reaches no AWS service: that the profile it writes
resolves to the actor's permission-set role is established by a later, separately authorized identity
preflight and by the launch tool's own bootstrap (ADR-0036 §2.5, ADR-0045 §6), never here.

### 2.2 The R-3 verification tool (`scripts/production_r3_verification.py`, `r3_verification.py`)

The accepted procedure, transcribed: one identity proof, then **nine expected-path S3 operations**
under `_verification/<stamp>/` with a fixed 64-byte synthetic marker, each held to the class the
accepted table names; on any deviation the path **halts**, the failure-path cleanup runs under its
budget of **ten** operations, and the result is computed after cleanup. The tool's default
invocation prints the matrix and performs nothing; `--check-record` decides whether an existing
record still attests; the authorized branch (`--i-am-the-owner-authorizing-one-r3-verification`)
refuses automation, requires `AWS_PROFILE` pinned to the control profile `kalpamani-foundation` and
the foundation identity gate to pass (one `sts:GetCallerIdentity`, compared with the local account
binding, PASS/FAIL only), loads the environment binding for the bucket and holds its account to the
governed one, digests the tracked declaration (`infra/aws/research-data-plane/storage.tf`), builds one
S3 client (one attempt, finite connect and read timeouts) **only then**, runs the procedure, and writes
the record exclusively under `KALPAMANI_PRODUCTION_R3_RECORD_DIR`. It prints the result and the two
counts, and the record digest **only** when the result is `VERIFIED` (readiness S5a).

**Classification is the evidence.** Every answer is one closed `ObservedClass`: `OK_200`, `OK_204`,
`NOT_FOUND_404`, `NO_SUCH_UPLOAD`, `DENIED_RESOURCE_POLICY` (a `403` carrying the documented *explicit
deny in a resource-based policy* context), `DENIED_IDENTITY_POLICY`, `DENIED_OTHER`,
`NOT_IMPLEMENTED_501`, `AUTHENTICATION_FAILURE`, `NO_SUCH_BUCKET`, `THROTTLED`, `TIMEOUT`,
`NETWORK_FAILURE`, `AMBIGUOUS`, `NOT_EXERCISED`. Only `DENIED_RESOURCE_POLICY` satisfies a negative
row (row 5 also admits the documented `501`); an authentication failure, a missing bucket, a throttle,
a timeout, an identity-based or context-less denial and anything unrecognised fail the row. The
message text, which names the caller ARN, is classified and dropped.

**The record** — `kalpamani-r3-verification-record/v1`: result (`VERIFIED` | `NOT_VERIFIED` |
`NOT_VERIFIED_CLEANUP_UNRESOLVED` | `NOT_EXERCISED`), stamp and prefix, control profile, the nine rows
(operation, key suffix, admitted classes, observed class, matched), the cleanup rows (trigger,
operation, observed, confirmation, resolved), the expected-path and failure-path counts, the residue
keys (synthetic; the stamp is the only value in them), whether the budget was exhausted, and the
instants — and its **binding**: the digest of the environment binding that named the bucket, the
digest of the declared statements, the partition and region. `parse_r3_record` refuses a record whose
result contradicts its rows (`VERIFIED` over a deviating row; resolution claimed over residue; an owed
cleanup absent) and whose rows do not follow the accepted table. `record_attests(record, binding)` is
true only for a `VERIFIED` record whose binding equals the current one: **old evidence attests to
nothing changed** — a changed `storage.tf`, another bucket or another region is a different binding,
and readiness §4.6's re-verification rule is checked, not remembered. The launch-inputs record's
`r3_verification_digest` (readiness S5a) is the digest of this record.

**The cleanup reading, stated.** The accepted failure-path table triggers on rows 2, 4, 5 and 6
returning `200` and on rows 8/9 failing. A path that **halts** before row 8 leaves the positive
control in place; the tool removes it with the same operation and confirmation the row-8/9 trigger
prescribes (`DeleteObject`, `HeadObject → 404`, 1 + 1), and treats an answer that *may* have created
an object (a timeout, a network failure, an ambiguous answer on an object-creating row) as a `200`
for cleanup purposes. A multipart creation that may have succeeded with no `UploadId` cannot be
aborted and is residue. All of it stays inside the ten-operation budget, and a failed row leaves R-3
`NOT_VERIFIED` whatever the cleanup restored.

### 2.3 The verification cell runner (`scripts/production_verification_cells.py`, `verification_cells.py`)

The required cells are enumerated from ADR-0036 §3 and readiness §4.3 as closed definitions — each
naming its actor, entry, what must succeed and what must be refused, its prerequisites, its
authorization and how it is executed:

| Cell | Kind | Execution |
|---|---|---|
| `R3` | control R-3 | the R-3 tool's record, named by the launch inputs and attesting to the current declaration |
| `R1-ACQ-BOOTSTRAP`, `R1-BLD-BOOTSTRAP` | runtime launch | the launch tool: one prepared specification, one `verify-` identity, one authorization naming the digest; `PASSED` only with a `VERIFIED` ledger row of `RECEIPT_VERIFIED` evidence |
| `R2-BLD-ISOLATION` | isolation verdict | the launch tool's `--isolation-verdict` on the build cell's record; `PASSED` only on `VERIFIED`; `INCONCLUSIVE` without qualifying corroboration; `FAILED` on `CONNECTED` |
| `R1-*-NO-RELEASE`, `R1-*-RELEASE-MISMATCH` | negative launch | **BLOCKED** — §4 |
| `R4-ACQUISITION` … `R9-FOUNDATION-TASK` | permission matrix | not orchestrated: owner-run per readiness S8; a cell decided by simulation only is recorded simulated, never verified |

**State is derived, never remembered.** The runner's only durable record is the prepared-cells
document (`kalpamani-verification-cells/v1`, beside the ledger at `<ledger>.cells.json`, written
atomically under the ledger lock): which `verify-` identity and which specification digest each
runtime cell was prepared with — one identity per cell, refused for a second. Every status is
derived from the owner ledger, the reservations beside it, the verdict records in the records
directory, the R-3 record and the launch-inputs record: `UNEXECUTED`, `BLOCKED` (a prerequisite not
`PASSED`, or the cell cannot be executed yet), `PREPARED`, `INTERRUPTED` (reserved, unrecorded —
recover with the launch tool, never relaunch), `LAUNCHED` (a row from the exit code only — a missing
receipt cannot pass), `PASSED`, `REFUSED`, `INCONCLUSIVE`, `FAILED`. The aggregate is `VERIFIED`
only when every required cell is `PASSED`, `FAILED` on any `FAILED`, otherwise `INCOMPLETE`.

**Execution composes the launch tool and adds nothing.** `--prepare-cell` is the launch tool's
offline preparation (specification written, digest printed; no client). `--execute-cell` requires the
flag, the cell exactly `PREPARED`, every prerequisite `PASSED`, and an authorization naming the
prepared digest and identity — then exactly the launch tool's authorized branch, once; a cell that is
`LAUNCHED`, `INTERRUPTED` or consumed is refused, and no authorization is generated or reused.
`--complete-cell` and `--verdict-cell` are the launch tool's `--complete-row` and
`--isolation-verdict` for the cell's record. Bootstrap completion and R-2 isolation are separate
cells; receipt collection stays deferred (ADR-0044 §5) and the owner supplies the receipt lines and
the analysis transcription. **No bypass switch exists** (`--all`, `--retry`, `--force`,
`--skip-prerequisites`, `--bypass`, `--relaunch`, `--auto-authorize` are refused by name), and no
production processing path changed.

## 3. Contracts added

| Contract | Where |
|---|---|
| `kalpamani-r3-verification-record/v1` | `r3_verification.py`: `R3Record`, `parse_r3_record`, `record_attests` |
| `kalpamani-verification-cells/v1` | `verification_cells.py`: `PreparedCell`, `parse_cells_document` |

No accepted contract changed. The production bindings, the launch specification, the reservation, the
launch record, the receipt and the verdict record are read and written exactly as ADR-0045 left them.

## 4. Deferred: the negative R-1 cells

ADR-0036 §3 R-1 requires two negative cells per actor — a verification launch with **no release
written** (`REFUSED_NO_RELEASE` at the ceiling) and one with a release **naming another task**
(`REFUSED_RELEASE_MISMATCH`). The accepted launch tool always writes the release after placement
verification and never writes a mismatched one; producing these cells needs a launcher mode that
deliberately withholds or mis-names the release for one launch. That is a change to `launch_authorized_run`'s
contract and a decision about how such a mode is authorized and distinguished from a defect. **This
ADR does not take it**: the cells are enumerated and stay `BLOCKED` with that reason, the aggregate
cannot be `VERIFIED` until they are decided and executed, and the decision is the owner's, in a later
proposed ADR.

## 5. Amendments stated

None to any accepted document. ADR-0036 §2.5, §2.7, §3 and ADR-0045 §6 are composed, not amended.
G-14 (the bucket-policy transition) stays deferred; the Reachability Analyzer permissions (D-14),
`ecs:DescribeTaskDefinition` (V-16) and the receipt collector's `logs:GetLogEvents` (ADR-0044 §5)
stay recorded and not granted.

## 6. Effectiveness and execution gates

Acceptance of this ADR authorizes **no** R-3 session, **no** materialization against a real private
root, **no** identity preflight, **no** launch, **no** run, **no** probe, **no** analysis, **no**
Terraform plan or apply, **no** image build or publication, **no** IAM or bucket-policy change. Each
tool refuses by default; each authorized branch is opened by its own flag under its own written
authorization; none has run against AWS. **G2 stays OPEN, CONTROL stays DEFERRED, Phase 3 stays NOT
COMPLETE, live trading stays HARD-DISABLED.**
