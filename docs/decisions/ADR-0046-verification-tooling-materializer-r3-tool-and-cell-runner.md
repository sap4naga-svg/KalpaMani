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

**The condition above has since been satisfied.** **PR #105 merged** — merged **2026-09-14T20:37:38Z**,
merge commit **`5174dcf290b4837d38af8ce4a4b975c6557e482e`**, ordered parents **`af20f36acbe8a3006830762fbad5cb01d1e9b38b`** then
**`c4436648d90d39baa3769e990887e6f0f239df40`** (the approved head, after two independently reviewed correction cycles
recorded in the pull request), with a **merge tree identical to the reviewed pull-request head tree**
(`4ec26720c7635257a3f938b21750e9b778fc42a9`). ADR-0046 is therefore **ACCEPTED / IN FORCE** exactly as the clause
above states — the owner-side tooling for S5, S7 and S9, the two narrow contracts it adds, the
verdict-document contract and the shared reservation-to-record rule its corrections added (§3), and the
one decision it deferred (§4) — effective together with the offline code merged beside it, and nothing
else. While the pull request was open it was proposed and carried no authority — true then, and not
rewritten. **Acceptance authorized no R-3 session, no materialization, no launch, no run, no probe, no
analysis, no Terraform plan or apply and no IAM change**; every tool still refuses by default and none
has run against AWS. The deferral of §4 is decided by a later, separately proposed ADR-0047 — since
accepted on the merge of PR #106 (2026-09-15).

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
S3 client **only then** — `retries={"total_max_attempts": 1, "mode": "standard"}` with finite connect
and read timeouts, so every operation is **one transport attempt**, a retryable answer (`SlowDown`,
`500`, a timeout) included — runs the procedure, and writes the record exclusively under
`KALPAMANI_PRODUCTION_R3_RECORD_DIR`. The SDK's `max_attempts` counts attempts *after* the first
request, so `max_attempts: 1` had permitted a second; the effective budget is asserted from the
constructed client's own configuration and observed at the transport (a counting fake in place of
the client's HTTP session, under invented static credentials — no profile, no discovery, no socket),
never assumed from the request. It prints the result and the two
counts, and the record digest **only** when the result is `VERIFIED` (readiness S5a).

**Classification is the evidence.** Every answer is one closed `ObservedClass`: `OK_200`, `OK_204`,
`NOT_FOUND_404`, `NO_SUCH_UPLOAD`, `DENIED_RESOURCE_POLICY` (a `403` carrying the documented *explicit
deny in a resource-based policy* context), `DENIED_IDENTITY_POLICY`, `DENIED_OTHER`,
`NOT_IMPLEMENTED_501`, `AUTHENTICATION_FAILURE`, `NO_SUCH_BUCKET`, `THROTTLED`, `TIMEOUT`,
`NETWORK_FAILURE`, `AMBIGUOUS`, `NOT_EXERCISED`, and — added 2026-09-17 for the permission subcells of
ADR-0047, never emitted by the R-3 classifier — `TARGET_NOT_FOUND`. Only `DENIED_RESOURCE_POLICY` satisfies a negative
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

**Row 8 acknowledges; row 9 confirms.** A `204` on row 8 is the service accepting the delete, not the
object's absence: the positive control is **confirmed absent only when row 9 observes `404`**. Any
other row-9 answer — `200` (the object is still there), a timeout, an access denial, a network
failure, an ambiguous answer — leaves the object unconfirmed: row 9 stays a failed row, the tool
performs the bounded cleanup (`DeleteObject`, then `HeadObject` held to `404`) inside the same
ten-operation budget, and the record carries the failed row **and** the cleanup rows. A later
confirmation restores the bucket and nothing else — the result is `NOT_VERIFIED`; an unconfirmed
object after cleanup, a refused cleanup delete or an exhausted budget is residue, and the result is
`NOT_VERIFIED_CLEANUP_UNRESOLVED`. `parse_r3_record` reads confirmation the same way (row 9's
observed class is `NOT_FOUND_404`, never row 8's `204`) and refuses a record that claims removal
from row 8 alone. **No cleanup outcome makes a failed verification `VERIFIED`.**

### 2.3 The verification cell runner (`scripts/production_verification_cells.py`, `verification_cells.py`)

The required cells are enumerated from ADR-0036 §3 and readiness §4.3 as closed definitions — each
naming its actor, entry, what must succeed and what must be refused, its prerequisites, its
authorization and how it is executed:

| Cell | Kind | Execution |
|---|---|---|
| `R3` | control R-3 | the R-3 tool's record, named by the launch inputs and attesting to the current declaration |
| `R1-ACQ-BOOTSTRAP`, `R1-BLD-BOOTSTRAP` | runtime launch | the launch tool: one prepared specification, one `verify-` identity, one authorization naming the digest; `PASSED` only with a `VERIFIED` ledger row of `RECEIPT_VERIFIED` evidence |
| `R2-BLD-CORROBORATION` | runtime launch | *(added by ADR-0052 — §7)* the launch tool, as the bootstrap cells: one fresh `verify-` identity, its own specification over the accepted empty run set, one authorization; the only cell the runner hands the ADR-0045 §12 hook to; requires `R3` and `R1-BLD-BOOTSTRAP` PASSED; `PASSED` is the launch's own success, never the verdict |
| `R2-BLD-ISOLATION` | isolation verdict | the launch tool's `--isolation-verdict` on the build cell's record *(since ADR-0052: the corroboration cell's record)*; `PASSED` only on `VERIFIED`; `INCONCLUSIVE` without qualifying corroboration; `FAILED` on `CONNECTED` |
| `R1-*-NO-RELEASE`, `R1-*-RELEASE-MISMATCH` | negative launch | **BLOCKED** — §4 |
| `R4-ACQUISITION` … `R9-FOUNDATION-TASK` | permission matrix | not orchestrated: owner-run per readiness S8; a cell decided by simulation only is recorded simulated, never verified |

**State is derived, never remembered.** The runner's only durable record is the prepared-cells
document (`kalpamani-verification-cells/v1`, beside the ledger at `<ledger>.cells.json`, written
atomically under the ledger lock): which `verify-` identity and which specification digest each
runtime cell was prepared with — one identity per cell, refused for a second. Every status is
derived from the owner ledger, the reservations beside it, the verdict records in the records
directory, the launch records in the records directory, the R-3 record and the launch-inputs
record: `UNEXECUTED`, `BLOCKED` (a prerequisite not `PASSED`, or the cell cannot be executed yet),
`PREPARED`, `INTERRUPTED` (reserved, unrecorded — recover with the launch tool, never relaunch),
`LAUNCHED` (a row from the exit code only — a missing receipt cannot pass), `PASSED`, `REFUSED`,
`INCONCLUSIVE`, `FAILED`, `HISTORICAL` (bound evidence for a target or placement other than the one
now registered — ADR-0045 §7's re-verification rule, checked rather than remembered), `UNBOUND`
(evidence that is missing, malformed, contradictory or for another specification, identity, actor
or kind — reported, never ignored, never passed). The aggregate is `VERIFIED` only when every
required cell is `PASSED`, `FAILED` on any `FAILED`, otherwise `INCOMPLETE`; `HISTORICAL` and
`UNBOUND` are `INCOMPLETE`, and a cell behind one is `BLOCKED`.

**A receipt-verified row passes only through its whole chain.** A `VERIFIED` / `RECEIPT_VERIFIED`
ledger row is a claim the runner binds before it is a pass: the **reservation** beside the ledger
for the prepared identity must carry the prepared specification digest, this cell's actor, the
verification kind and this cell's entry; the **launch record** in the records directory for that
identity must bind to that reservation under the accepted launch tool's **one shared rule**
(`launch_store.bind_record`, the rule `--complete-row` and `--isolation-verdict` refuse on): the same
digest, identity, actor, kind and entry; the record's slice and plan digest exactly the
specification's workload; the reservation's target (task-definition revision, image digest,
configuration digest, code commit); and the record's verified subnet and security groups (as a set)
the specification's placement — with the runner additionally requiring that a verified placement
is present. A record whose **only** change is its subnet, its security groups, its slice or its
plan digest, under an unchanged digest, reservation, registration and ledger row, is
`PLACEMENT_MISMATCH` or `WORKLOAD_MISMATCH` and the row is `UNBOUND`; two launch records for one
identity bind neither. The bound evidence is then
held **against the launch-inputs record now registered**: the specification compiled from the
current inputs for this actor must equal the reservation's, target and placement alike — otherwise
the row is `HISTORICAL`. A row with no reservation, no launch record, a reservation for another
specification or a substituted record is `UNBOUND`. The runner derives every status from files it
reads and performs no external operation to do so; what it trusts is the owner ledger, the
reservations the launch tool wrote under the ledger lock and the records it wrote, and it trusts
them **only where they agree with each other and with the current registration**.

**Verdict records are parsed closed.** Each `isolation-verdict-*` record is read through the
`kalpamani-isolation-verdict/v1` contract (§3): `schema_version`, `contract_id`, the actor and
kind, the specification digest, the receipt's probe block, the verdict block, whether evidence was
supplied, and the instant — no other field, and no field absent. A document whose blocks disagree
is refused: a `CORROBORATED` verdict over a `CONNECTED` probe, `OBSERVED_CONNECTION` over any other
result, a `NO_ATTEMPT` reason over a probe that attempted, a corroboration or an evidence-dependent
reason with no evidence supplied, `NO_CORROBORATION` beside supplied evidence, a verdict or
`analysis_bound` the reason does not imply. `CONNECTED` is `FAILED` and nothing else. An unreadable
or refused record is counted and reported, and any such record for a prepared launch makes its
verdict cell `UNBOUND`; a document for another actor or kind does not bind. The records for one
launch resolve deterministically: no document is `UNEXECUTED`; **any `FAILED` is `FAILED`** whatever
was recorded beside it; records carrying different probe blocks are not one launch's and conflict;
a `VERIFIED` beside an `INCONCLUSIVE` whose reason a later analysis cannot resolve (`NO_ATTEMPT`,
`DESTINATION_UNBOUND`, `PATH_FOUND_CONTRADICTS_OBSERVATION`) conflicts; a `VERIFIED` otherwise is
`PASSED`; the rest is `INCONCLUSIVE`. A conflict is `UNBOUND`, never a pass.

**An `INCONCLUSIVE` verdict is re-evaluated for the same launch, never relaunched.** `--verdict-cell`
is admitted from `UNEXECUTED` and from `INCONCLUSIVE`; it re-runs the launch tool's `--isolation-verdict`
on the **same** launch record, receipt lines and configuration — no new launch, no new probe — and
appends one more verdict record; every earlier record is preserved. Qualifying, bound corroboration
(the analysis over this launch's interface, its destination and inside its task window, succeeded,
no path found) resolves `NO_CORROBORATION` and the other insufficiencies to `PASSED`; a
wrong-source, wrong-destination, stale or contradictory transcription adds an `INCONCLUSIVE` record
and promotes nothing. A `PASSED` or `FAILED` verdict cell is not re-evaluated.

**Execution composes the launch tool and adds nothing.** `--prepare-cell` is the launch tool's
offline preparation (specification written, digest printed; no client). `--execute-cell` requires the
flag, the cell exactly `PREPARED`, every prerequisite `PASSED`, and an authorization naming the
prepared digest and identity — then exactly the launch tool's authorized branch, once; a cell that is
`LAUNCHED`, `INTERRUPTED` or consumed is refused, and no authorization is generated or reused.
`--complete-cell` and `--verdict-cell` are the launch tool's `--complete-row` and
`--isolation-verdict` for the cell's record (`--verdict-cell` also from `INCONCLUSIVE`, for the
same launch — above). Bootstrap completion and R-2 isolation are separate
cells; receipt collection stays deferred (ADR-0044 §5) and the owner supplies the receipt lines and
the analysis transcription. **No bypass switch exists** (`--all`, `--retry`, `--force`,
`--skip-prerequisites`, `--bypass`, `--relaunch`, `--auto-authorize` are refused by name), and no
production processing path changed.

## 3. Contracts added

| Contract | Where |
|---|---|
| `kalpamani-r3-verification-record/v1` | `r3_verification.py`: `R3Record`, `parse_r3_record`, `record_attests` |
| `kalpamani-verification-cells/v1` | `verification_cells.py`: `PreparedCell`, `parse_cells_document` |
| `kalpamani-isolation-verdict/v1` | `probe.py`: `IsolationVerdictDocument`, `parse_isolation_verdict_document` — the document the ADR-0045 launch tool already writes, now a closed, bounded (64 KiB) contract with the consistency rules of §2.3 |
| reservation-to-record binding | `launch_store.py`: `bind_record`, `RecordBinding` (`BOUND`, `SPECIFICATION_MISMATCH`, `WORKLOAD_MISMATCH`, `TARGET_MISMATCH`, `PLACEMENT_MISMATCH`, `UNCOMPILABLE`) — the launch tool's existing rule moved into one shared validator, used by `--complete-row`, `--isolation-verdict` and the cell runner; no record or reservation field changed |

**One contract change, stated.** The launch tool's verdict record was written under ADR-0045 with
the contract identifier and the nine fields above but was read open — the first cell runner accepted
any object carrying that identifier, a digest and a `verdict.verdict` token. It is now a contract:
what the tool writes is unchanged byte for byte; what a reader accepts is the closed document, and
nothing less. The production bindings, the launch specification, the reservation, the launch record
and the receipt are read and written exactly as ADR-0045 left them; the runner reads the reservation
and launch records it already had access to and adds no field to any of them.

## 4. Deferred: the negative R-1 cells

> **Decided since by ADR-0047** (a later, separate pull request, PR #106, since merged): the two negative modes are
> bound into the authorized specification and the launcher, and R-4 .. R-9 are expanded into
> executable subcells. The text below records the deferral as this ADR made it and is not rewritten.

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

## Vocabulary addition (2026-09-17) — `TARGET_NOT_FOUND`

*[On `main` since PR #118 merged 2026-09-17T00:42:22Z, merge commit `696749f6e8fbc4b6647c76e0d6349650d997dd69`, ordered parents
`a59ad2c4…` then `f6d0efca…`.]*

One member was added to the closed `ObservedClass` this decision fixed, and nothing else here changes. On
2026-09-16 (permission batch 1, run 4, row 34) the acquisition launcher's `RunTask` on a task-definition
revision that does not exist was answered by ECS with `ClientException: TaskDefinition not found.` — a
**target validation failure**: the service reported that the addressed resource does not exist, before any
authorization answer and before any task. It is **neither a permission denial nor a success**, and the R-3
classifier reads it as `AMBIGUOUS` (an answer it does not know), which is correct for R-3 and stays so.

`TARGET_NOT_FOUND` names that answer as its own closed class so that a permission record can carry it
without pretending it decided anything: it is emitted **only** by the ADR-0047 permission-subcell classifier,
for ECS's exact documented message `TaskDefinition not found.` on a `ClientException` (any other
`ClientException` message stays `AMBIGUOUS`) and for `ClusterNotFoundException`; the R-3 classifier of this
decision never produces it, no R-3 row admits it, and no R-3 record is affected. Under ADR-0047 it decides
nothing (`UNDECIDED` for either expectation) and, because such a request created no task, it is "definitely
not committed": no launch is recorded as possibly started and the cleanup has nothing to discover. The
original row-34 record, written before the member existed, is preserved as `AMBIGUOUS` / `UNDECIDED`.

## 7. Amendment (2026-09-17) — the dedicated R-2 corroboration cell, and a launched binding is never rebound

**Status: PROPOSED — NOT IN FORCE while the pull request carrying this section is open.** Proposed by
ADR-0052, and effective with it; nothing else in this decision changes. *[Since accepted: ADR-0052 is ACCEPTED / IN FORCE on the merge of PR #126 — 2026-09-17T18:53:23Z, merge commit
`01f77a10a2341b1d1d99a7fe0024b104563d692c`, ordered parents `d5407d8a…` then `a489f13f…`, merge tree identical to the reviewed head
tree — and this section with it; true when written, not rewritten.]*

§2.3's catalogue gains one runtime-launch cell under R-2, **`R2-BLD-CORROBORATION`** — the build actor,
the `kalpamani-research-build-verify` entry, prerequisites `R3` and `R1-BLD-BOOTSTRAP` PASSED, executed by
the launch tool exactly as the bootstrap cells are (a fresh `verify-` identity, its own prepared
specification over the accepted empty run set with a `NORMAL` release, one authorization naming its
digest, one launch, the receipt) and the only cell the runner hands ADR-0045 §12's hook to. Its `PASSED`
is the launch's own success — the vehicle — and never the isolation verdict. **`R2-BLD-ISOLATION` now
depends on `R2-BLD-CORROBORATION`** rather than on `R1-BLD-BOOTSTRAP`, and is taken on the corroboration
launch's record and receipt; its rule, its `INCONCLUSIVE` / `FAILED` / `UNBOUND` derivation and its
resolvable insufficiencies are unchanged.

One rule joins the runner's: **`--prepare-cell` refuses (`refused_cell_state`) a cell whose bound identity
was launched** — a reservation beside the ledger or a ledger row under that identity — whatever identity is
offered, and an unreadable store is no licence to rebind. The PASSED `R1-BLD-BOOTSTRAP` cell's binding,
reservation, launch record, receipt and row therefore stay byte for byte what they are; the corroboration
is a new binding under a new identity. Why: the S9 build bootstrap ran once and PASSED on its receipt while
the hook's path request was refused at parameter validation (a request-shape defect since corrected, a
workstation-only change); a second analysis attempt must not rebind a PASSED cell's evidence to a second
launch. Held by `test_production_verification_cells.py` (the catalogue, the hook's single cell, the whole
lifecycle on fakes with the rebinding and reuse refusals) and by this document's governance test.



## 8. Amendment (2026-09-18) — `HISTORICAL` from a historical reservation's chain, and the registration-historical rebinding rule (ADR-0054)

**Status: PROPOSED — NOT IN FORCE while the pull request carrying this section is open; it changes no
task image, no compiled configuration, no task definition, no Terraform, no IAM and no registration.**
Proposed by [ADR-0054](ADR-0054-historical-v1-reservations-and-registration-historical-rebinding.md) on 2026-09-18, and effective with it; the text above is preserved as accepted and is not rewritten. *[Since accepted: ADR-0054 is ACCEPTED / IN FORCE on the merge of PR #135 — 2026-09-18T17:35:07Z, merge commit
`8be462b953c33a6953429ee9edc321f843ab6ae1`, ordered parents `a5a6384f…` then `bbaa419d…`, merge tree identical to the reviewed head
tree — and this section with it; true when written, not rewritten.]*

§2's derivation reads reservations through the store's evidence read (ADR-0045 §14): a v1 reservation is
corroborated against its ledger row (actor, kind, canonical slice, plan digest — a disagreement is
`refused_records`), refused `refused_records` if the registration in force still names its target and placement,
and otherwise bound to its launch record under the **same** accepted rule (digest, identity, actor, kind, entry,
workload, target, verified placement, release mode) — then derived `HISTORICAL` with a reason naming the
superseded contract and ADR-0045 §7, never `PASSED`; a chain that does not bind is `UNBOUND`. `--prepare-cell`
gains ADR-0054 §2.2's rule: §7's refusal of a launched binding stands, except for a binding the derivation reads
`HISTORICAL` because the registration moved, proven step by step before any write (launched; reservation and
launch record integrity-valid and bound; derived `HISTORICAL` for that identity and digest; registration
difference re-checked; replacement `verify-` identity fresh in the ledger, reservations, bindings and superseded
links, launch and specification records and consumed markers; the launch tool's admission passed), with the
previous cells document preserved owner-only beside the ledger (`<ledger>.cells.superseded-<sha16>-<stamp>.json`)
and the new binding carrying a closed, digest-bound `supersedes` link. The order is preserve → write the
specification → write the cells document, a failure of the last unlinking the specification, so a refused or
interrupted preparation leaves no stray record. `refused_rebinding` (exit 15) is the one new sentence. The rule is
generic across the runtime-launch catalogue, `R2-BLD-CORROBORATION` included when its prerequisites permit, and
historical evidence never becomes a current `PASSED`.
