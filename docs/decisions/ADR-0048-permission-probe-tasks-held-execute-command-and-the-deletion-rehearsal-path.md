# ADR-0048 — Permission-probe tasks, the held ExecuteCommand check, and the deletion rehearsal path

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0048 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **the two mechanisms that execute the task-role and `ExecuteCommand`
permission subcells ADR-0047 left blocked — the permission-probe entry and its families, the probe
input and observation contracts, the receipt's permission block, the launch records' probe kind and
the workstation tool's probe launch and receipt completion (§2); the launcher's `ExecuteCommand`
refusal against its own held probe task (§3) — together with the classification of every issuing
service's documented denial (§2.6), the narrow amendments it states (§6), and the one design it
proposes and does not open: the deletion role's rehearsal path (§4), which stays BLOCKED until a
separate decision takes it — and nothing else**, effective together with the offline code merged beside
it. **Acceptance authorizes no execution** (§7): no probe launch, no permission subcell, no cleanup, no
run, no image, no Terraform plan or apply, no IAM change; and **acceptance grants no permission** —
every probe exercises a permission the accepted declarations already state, and the deletion role's
path is not opened by accepting this text.

**Nothing was run to produce this decision.** No AWS call, no STS call, no S3 operation, no `RunTask`,
no `ExecuteCommand`, no container image built or pulled, no registry contacted, no credential
retrieved, no provider request, no private input inspected. Every result beside this text is a counting
fake's or an intercepted transport's, on synthetic temporary files. **Mocked results are not AWS
verification.**

---

## 1. Context

ADR-0047 (accepted on the merge of PR #106, `167f1564…`, 2026-09-15) expanded ADR-0036 §3's R-4 … R-9
rows into 98 subcells and named 36 of them BLOCKED: **32 task-role subcells** of R-4 and R-5 on "a
task-side permission probe entry" (ADR-0047 §5), **2 `ExecuteCommand` subcells** of R-6 on "a running
task of this actor to execute into", and **2 deletion-role subcells** of R-8 on the deletion role's
missing execution path (ADR-0007). A blocked subcell blocks its cell, so R-4, R-5, R-6 and R-8 could
not read `PASSED`, and the aggregate stayed `INCOMPLETE` whatever the human principals established. A
human role never stands in for a task role (ADR-0047 §3.1).

Three further facts shaped the design and are recorded rather than smoothed over:

- **The workstation's `ExecuteCommand` request was invalid.** The accepted adapter sent
  `interactive=False`; the documented API states that ECS "only supports initiating interactive
  sessions, so you must specify `true`" and lists `command` and `interactive` as required. A fake
  HTTP 200 had accepted the request; the service would have refused it on its parameters before any
  policy was evaluated — not a permission test.
- **Non-S3 denials were not classified as denials.** The R-3 classifier reads S3's `AccessDenied`
  (403). Secrets Manager, SSM and ECS refuse with `AccessDeniedException` (HTTP 400) and EC2 with
  `UnauthorizedOperation`; a permission subcell issuing those services would have read a real
  refusal as `AMBIGUOUS` — `UNDECIDED`, never `MATCHED`.
- **ADR-0007's inert property is verified, not merely declared.** "No deletion task definition exists,
  no deletion workflow exists, and no authorized principal holds `iam:PassRole` for the deletion
  role" is checked against the live account. Any execution path for the deletion role reverses it.

## 2. Decision — the permission-probe entry (the 32 task-role subcells)

### 2.1 Two entries, two families, two more `RunTask` resources

ADR-0043's two production entries and ADR-0045's two verification entries become **six**:

```text
kalpamani-production-acquire-probe   the acquisition actor's PERMISSION-PROBE entry
kalpamani-research-build-probe       the build actor's PERMISSION-PROBE entry
```

Each is the `command` token of a **permission-probe task-definition family** of the same name,
declared beside the actor's production and verification families with **the same task role, the same
execution role, the same network placement, the same `user`, read-only root filesystem and `/work`
tmpfs**, and the verification image pinned by its own digest (`production_image_digests` keys
`acquisition_probe`, `build_probe`). A probe family exists only at stage `a` or `b` **and** only when
its digest is supplied; any other key is refused by the variable's validation. **Each launcher
permission set gains exactly one more `ecs:RunTask` resource**: its own actor's probe revision, as a
`concat` beside the production and verification revisions — three exact ARNs at most, never a
wildcard, never a family ARN, never the other actor's. The `iam:PassRole` allowlist is unchanged
(the same two roles), the launcher still **denies `ecs:ExecuteCommand`**, and no assignment changes.

The compiled configuration of a probe entry carries the common fields and nothing else
(`_PROBE_FIELDS`): no secret name, no origin address set, no build configuration. The subcell a probe
issues comes from its input, never from the image, so one image serves every task-role subcell.

### 2.2 The probe input: what the workstation bound, for the task to act on

`kalpamani-permission-probe-input/v1` (`permission_probe.py`) replaces the actor's production input
for a probe launch — the same parameter, the same digest over the bytes, a different closed document:
the actor, the identity (`probe-<session stamp>`), the subcell, the **statement and attempt digests**
the workstation already bound, the stamp, the **exact resolved target document** (the statement's
`target_sha256` is the digest of this document) and `hold_seconds`, valid for at most 24 hours.
Parsing holds the subcell to the catalogue: it must be a task-issued subcell of the input's actor
with `hold_seconds = 0`, or that actor's held `ExecuteCommand` subcell with a positive hold, and the
target kind must be the subcell's. The accepted bootstrap admits it through `run_task_bootstrap(…,
probe=True)` and changes nothing else — environment, binding, self-check, identity proof and release
barrier are the same functions, in the same order.

### 2.3 The entry: the accepted bootstrap, then exactly one operation

`permission_probe_entry.run_permission_probe_entry` composes the accepted pre-entry checks and
`run_task_bootstrap`, then — only after `RELEASED` — builds **the one client its subcell's operation
names** (`permission_client.single_service_client`: a Secrets Manager client for a `GetSecretValue`
subcell and nothing else; an S3 client for an S3 subcell and nothing else; any other service refused
before an SDK client exists) from the task's isolated, container-credentialed session, and issues
**exactly one operation** through `permission_cells.issue_subcell` — the same engine the workstation
uses for a human principal. Its factories hold no provider transport, no spent-identity source and no
build configuration; it never writes the run reservation, never retries, never issues a second
operation. The closed outcomes are `PROBE_MATCHED` (41), `PROBE_INVERTED` (42), `PROBE_UNDECIDED`
(43) and `PROBE_HELD` (44): non-zero on purpose, so exit `0` stays `COMPLETED` alone and a probe can
never be read as a run. A held probe (§3) issues nothing.

### 2.4 The receipt's permission block, and what it never carries

The task receipt moves to **`kalpamani-task-receipt/v3`** by adding one closed, nullable block,
`permission` — the `PermissionProbeObservation`: the subcell, the statement and attempt digests, the
stamp, the observed class, the outcome, whether the object was created or possibly created, the
operation count and the seconds held. It is present exactly on a probe entry's `PROBE_*` receipt; a v2
validator refuses the field. **The receipt never carries the value a `GetSecretValue` or `GetObject`
returned, a key, a name or an ARN** — the observation is classes and counts, and the response body is
never read into it. The accepted validator binds the receipt to the launch record through the same
binding digest (task id, revision, image, identity, input digest, configuration, commit) and
additionally refuses a block that contradicts its outcome (a held block on a non-held outcome, an
outcome the block does not state) and a probe outcome on any but a probe entry.

### 2.5 The workstation: launch, then complete from the verified receipt

`scripts/production_permission_cells.py` executes a task-layer subcell in the order ADR-0047 fixed —
the flag, the subcell, the bindings, the prepared statement recomputed, the authorization admitted and
**consumed durably beside the ledger**, the attempt written naming the exact object it may create —
and then, instead of a client, **the accepted launch sequence** (`launch_authorized_run`) under the
actor's human and launcher profiles, both identities proven through the accepted human bootstrap as
the launch tool proves them: the probe input materialized create-only, one `RunTask` of the
registered probe revision **tagged with the session's `startedBy`** (the one field added to the
accepted request; `overrides` stays absent, `enableExecuteCommand` stays `false`), placement verified,
the release written, the task observed to its terminal state, the prescribed cleanup, and a **launch
record plus an owner-ledger row** (`kind = permission-probe`, outcome `PROBED` from a probe exit,
`REFUSED` or `HALTED` otherwise) written under the ledger lock — every launched identity is in the
ledger, probe or not.

**The launch is attributed before it is made** (correction 1, §8.1). Between the attempt and the first
client, under the ledger lock, the tool **reserves the probe identity beside the ledger** exactly as the
launch tool reserves every identity (ADR-0045): an exclusive `kalpamani-launch-reservation/v1` carrying
the whole **probe launch specification** — the registered probe target and placement, and a workload
naming the subcell, the prepared statement, the written attempt, the session stamp and its `startedBy`
tag, the hold and the digest of the materialized probe input. The launch record then names **that
specification's digest** and binds to the reservation through the one record-to-reservation rule; an
interrupted launch — after `RunTask`, before any launch publication — is attributable to its attempt,
its tag and its cluster **from the reservation alone**. The consumed authorization stays consumed; a
reserved identity that never reached the ledger refuses every further probe launch until
`--recover-probe-launch <id>` records its row offline (from the launch record when one exists and
binds, `HALTED` from the reservation otherwise; a record naming another specification refuses) —
nothing is relaunched, nothing is removed, the attempt stays `INTERRUPTED`, and the cleanup discovers
any started task on the reservation's cluster by the reservation's tag, bounded, with the launch
record's task, when one was written, confirmed by exact identity. No post-launch record is needed to
account for a started probe.

The subcell is then **`AWAITING_RECEIPT`** (the cell `INCONCLUSIVE`, never `PASSED` on an exit code):
`--complete-subcell <id> --receipt-lines <file>` verifies the hand-read receipt against that launch
record through the accepted validator, holds its outcome to the **exit code the launcher observed at
the terminal state**, holds its permission block to this attempt, statement, subcell and stamp, writes
the permission record — `identity_verified` exactly when the probe's bootstrap released, which is the
task's own identity proof; the created object is the attempt's exact key; the probe task itself is a
started task of the record, discovered by the session's tag and confirmed `STOPPED` by the cleanup
like every launched task — **keeps the receipt as evidence** (`kalpamani-probe-receipt-evidence/v1`:
the receipt document as collected, bound to the launch record by that record's digest) and completes
the owner-ledger row from it. A receipt of a probe that refused before its operation completes the
record as `UNDECIDED` (`NOT_EXERCISED`, zero operations), never re-executed automatically. A launch
that started no task consumes the authorization and leaves the attempt `INTERRUPTED`. **Completion is
repeatable** (correction 1, §8.1): an interruption between the record, the receipt evidence and the
ledger leaves a partial completion, and the same completion run again with the same receipt writes
exactly what is missing — the receipt must then re-establish what the existing record recorded — while
a completion already whole changes nothing and says so; no evidence is ever removed. The receipt
collector of ADR-0044 §5 stays deferred: receipts are hand-read.

**A probe-layer result binds through its whole evidence** (correction 1, §8.2). The one validator
(ADR-0047 §3.4) requires of a task-layer or held-task record, beyond the permission chain: exactly one
probe launch attributed to the attempt by its reservation, with exactly one launch record that binds to
that reservation (specification, workload, target, placement) and whose workload names this subcell,
statement, attempt, stamp and tag, the actor's probe entry and identity, the hold of the layer, and
the task the record started; exactly one owner-ledger row for that identity, of the probe kind and
actor, launched when the record says and completed `RECEIPT_VERIFIED` with the receipt's disposition;
exactly one receipt evidence, **re-verified on every read** against that launch record's expectation,
naming the record by digest, whose outcome is the observed terminal exit and whose permission block
equals the record's observation (a task subcell) or which attests a released, held probe (a held
subcell, §3). A missing receipt reads `AWAITING_RECEIPT`; a missing, substituted, duplicated or
contradicting launch, reservation, ledger or receipt reads `UNBOUND` and never `PASSED`; a duplicate is
a defect, never a choice among candidates; a probe launch record no reservation attributes makes every
probe subcell `UNBOUND`. The task-issued operation (the receipt's block) and the launcher's
`ExecuteCommand` observation (the record written at launch) stay two different facts with their own
evidence.

### 2.6 Classification: every issuing service's documented denial

`permission_cells.classify` is the accepted S3 classifier plus one rule: `AccessDeniedException` and
`UnauthorizedOperation` are denials (`DENIED_OTHER`; which policy refused is not what a subcell
decides). `InvalidParameterException`, `TargetNotConnectedException` and every answer the classifier
does not know stay `AMBIGUOUS` — `UNDECIDED`. The R-3 classifier is unchanged.

## 3. Decision — the launcher's `ExecuteCommand` refusal against its own held probe (2 subcells)

The two `R6-*-EXECUTE-COMMAND` subcells move to layer **`L3_HELD_TASK`**. Their target is the actor's
own **held probe task**: the tool launches the probe family with `hold_seconds = 180` (bounded by the
probe's ceiling of 600 s and the launcher's observation ceiling), and `launch_authorized_run` invokes
its one **`while_running`** hook at most once — after the release is written and before observation
begins — and only once the **held-task precondition** holds (correction 1, §8.3): the launcher
describes the task it started afresh, at 5 s intervals for at most 120 s (inside the probe's own hold),
until `DescribeTasks` reports it **`RUNNING`** on the registered revision with the registered image;
that fresh description (`HeldTask`: task, revision, image, `lastStatus`, when observed, how many
descriptions) is what the check receives and what is kept as evidence
(`kalpamani-held-task-evidence/v1`). The hook then issues **one `ExecuteCommand`** under the launcher's
profile with the documented request (`cluster`, `task`, `command`, `interactive: true`) and records
the answer at once: a denial `MATCHED`; **an unexpected session (a 200) is an inversion and a
capability to close** — the task is stopped immediately, the stop acknowledged in the record; an
`InvalidParameterException`, a `TargetNotConnectedException` or a task that already exited decides
nothing (`UNDECIDED`). A task that stops before it is observed running, that has not reached `RUNNING`
at the ceiling, that cannot be described, or that reports another revision or image is **not
checked**: the launch reports which (`TASK_STOPPED`, `READINESS_TIMEOUT`, `OBSERVATION_FAILED`,
`TASK_MISMATCH`), the record says nothing was issued (`UNDECIDED`, `NOT_EXERCISED`) and the held-task
evidence says why — one attempt, explicit accounting, no retry. The hook is admitted for a released
permission-probe launch only, its own failure never changes the sequence, and a held launch that never
reached its release (a misplacement, a refused release) writes no record: the attempt stays
`INTERRUPTED` and the cleanup discovers the task by the reservation's tag. The security property under
test is preserved: `enableExecuteCommand` stays `false` on every task definition, the launcher keeps
its explicit deny, and nothing here enables the capability to make the test runnable.

**What the precondition proves, and what it does not.** The fresh `RUNNING` description proves that,
at the moment the check was admitted, the exact task this sequence started and released was running on
the registered revision and image — the probe was *available* as a target. The probe's own receipt
(`PROBE_HELD` from a released bootstrap, kept as evidence at completion, §2.5) proves the task then held
as designed; a receipt that says its bootstrap refused, or that it did not hold, reads the check as
`UNDECIDED` — the launcher's denial against a task whose availability was not established decides
nothing, and never `PASSED`. **What remains an evaluation-order limitation**: whether ECS evaluates the
caller's IAM authorization before it validates the task's `enableExecuteCommand` state, and whether the
task's managed agent was connected, are not established offline and are not observable without the
capability the test refuses to enable. If the service refuses on the parameter or the connection
first, the recorded answer is `UNDECIDED`, and the subcell stays undecided rather than reading as a
permission verdict it did not obtain.

## 4. Proposed and not opened — the deletion role's rehearsal path (2 subcells stay BLOCKED)

The R-8 subcells stay **BLOCKED**, and their dependency names why: the deletion role's execution path
reverses a verified ADR-0007 property, which is a governance decision this ADR designs and does not
take. The concrete design, so that decision can be taken on a stated shape:

| Element | Design |
|---|---|
| **rehearsal family** | `kalpamani-deletion-rehearsal`: the verification image, `task_role_arn` = the deletion role, the foundation execution role, the build subnet (no internet route), read-only root, `/work` tmpfs, declared only with its own image digest key and at stage `a` or `b`; `enableExecuteCommand` false |
| **rehearsal entry** | `kalpamani-deletion-rehearsal`: the accepted bootstrap over a **deletion runtime binding** (the build binding's field set under `kalpamani-deletion-runtime-binding/v1`, a third parameter under `/kalpamani/production/deletion/…`) and the probe input contract of §2.2 (the catalogue's R-8 subcells under `DELETION_ROLE`), the identity gate holding the exact account and the deletion role's name, the release barrier; then exactly one operation through `issue_subcell` |
| **the subcells** | `R8-LIST` (`ListObjectsV2` with `Prefix` = the widened production prefix, `MaxKeys=1`, expected `200`), `R8-DELETE` (`DeleteObject` of the exact synthetic object the bound `R4-PUT-PAYLOAD-HUMAN` record established, expected `204`) and `R8-GET` (`GetObject` of that same object, expected denied); one probe launch per subcell |
| **the synthetic objects** | established only by the accepted R-4 human `PutObject` subcells (the marker payload under the production Bronze namespaces, ADR-0047 §3.3), attributed by the bound prerequisite record, and confirmed removed by the control principal's cleanup pass (`HeadObject` held to `404`) — the deletion role cannot read, so it confirms nothing itself. No production deletion scope is widened: the rehearsal deletes exactly one key the bound record names |
| **rehearsal launcher** | one permission set, `KalpaManiDeletionRehearse`, assigned to the governed group: `ecs:RunTask` on exactly the rehearsal revision in the one cluster, `iam:PassRole` on exactly the deletion role and the execution role (closed by `NotResource`, `iam:PassedToService` = ECS), `ecs:DescribeTasks` / `StopTask` in the cluster, `ec2:DescribeNetworkInterfaces`, create-only `ssm:PutParameter` and `DeleteParameter` on the two fixed rehearsal parameter names, an explicit deny on `ecs:ExecuteCommand`; **no human assumes the deletion role** — the role is passed to ECS, and its trust policy already admits `ecs-tasks.amazonaws.com` |
| **the deletion role's delta** | `ssm:GetParameter` on exactly its binding, input and release parameters and `kms:Decrypt` on the binding key — the accepted task bootstrap shape (ADR-0036 §2.5) — and nothing else; its S3 statements are unchanged |
| **what acceptance would change** | ADR-0007's recorded property becomes "a deletion task definition and a rehearsal launcher exist; no human may assume the role"; CLAUDE.md §*Research data plane* and the deletion runbook state the new path; the live inert property is re-verified after the apply |

**Not implemented here**: no `ProductionActor` for the deletion role, no rehearsal family, no launcher
permission set, no binding contract, no IAM change. The probe input contract, the receipt block and
the tool's completion path are principal-agnostic and would serve the rehearsal unchanged.

## 5. Traceability, and the resulting counts

Every subcell keeps its ADR-0036 §3 trace (ADR-0047 §4); no clause moves. The layers now read:

| Layer | Subcells | Decided by |
|---|---|---|
| `L3_RUNTIME` | 56 | one request under the principal's own profile (ADR-0047) |
| `L3_BY_R1` | 6 | the actor's passed R-1 bootstrap launch (ADR-0047) |
| `L3_TASK` | 32 | one probe launch and its verified receipt (§2) |
| `L3_HELD_TASK` | 2 | one `ExecuteCommand` against the actor's held probe task (§3) |
| `BLOCKED` | 2 | the deletion role's execution path — a governance decision (§4) |

**98 subcells; 56 / 6 / 32 / 2 / 2.** Nothing has been executed: every task-layer and held-task
subcell reads `UNEXECUTED`, and R-8 reads `BLOCKED` with its dependency. The cell runner reads a
launched, uncompleted probe as `AWAITING_RECEIPT` (`INCONCLUSIVE`), a reserved, unrecorded probe
launch as `INTERRUPTED` awaiting recovery, a check whose held-task precondition did not hold as
`UNDECIDED`, and a result whose launch, reservation, ledger or receipt evidence is missing,
substituted, duplicated or contradicting as `UNBOUND`; **empty, partial, simulated or blocked coverage
never passes**.

## 6. Amendments stated

- **ADR-0045 §2, narrowly**: the four entries become six; `CompiledTask` admits the probe family for an
  actor (`is_known_family`); the receipt contract moves from v2 to v3 by one nullable block.
- **ADR-0045 §5, narrowly**: each launcher's `ecs:RunTask` resource list gains the probe revision.
- **ADR-0036 §2.6, narrowly**: the actor's input parameter carries the probe input contract for a probe
  launch; the launch-inputs record (`kalpamani-launch-inputs/v1`) admits one optional per-actor key,
  `permission_probe`, so a registration made before the probe family existed stays valid.
- **ADR-0036 §2.12 / ADR-0045 §6, narrowly**: `RunTask` carries `startedBy` for a probe launch, and the
  sequence has one hook, admitted for a released probe launch only; `LaunchKind` gains
  `permission-probe`, the owner ledger's outcome vocabulary gains `PROBED`.
- **ADR-0047 §3.4, one sentence**: an unverified cleanup "never makes a prerequisite object
  *unavailable*" — it establishes no removal, so the prerequisite stays available; ADR-0047's text
  carries the correction beside its original wording.
- **ADR-0047 §5**: the task-side probe entry and the `ExecuteCommand` mechanism are delivered here; the
  deletion path is designed (§4) and not opened. ADR-0047's own §5 table is history and is not
  rewritten.
- **ADR-0045 §3 / ADR-0047 §3.4, narrowly** (correction 1): the launch specification admits a
  permission-probe workload, and a probe launch is reserved beside the ledger before `RunTask`
  exactly as every other launch; the one validator requires of a probe-layer result its
  reservation-attributed launch, its re-verified receipt (`kalpamani-probe-receipt-evidence/v1`),
  its ledger row and, held, its precondition evidence (`kalpamani-held-task-evidence/v1`).
- No accepted request, key builder, bucket policy, assignment or human permission set changes; no
  ADR is superseded.

## 7. Effectiveness and execution gates

Acceptance of this ADR authorizes **no** probe launch, **no** permission subcell, **no** held task,
**no** cleanup, **no** run, **no** image build or publication, **no** Terraform plan or apply, **no**
IAM, permission-set or bucket-policy change, and grants **no** permission. Each tool refuses by default;
a probe subcell is executed only by an authorization naming its prepared statement, consumed by its
one launch; the receipt is hand-read; none has run against AWS. The deletion rehearsal path stays a
separate decision. **G2 stays OPEN, CONTROL stays DEFERRED, Phase 3 stays NOT COMPLETE, live trading
stays HARD-DISABLED.**

## 8. Corrections after review (correction 1; the ADR stays PROPOSED)

An independent review of the pull request introducing this ADR found three defects in the offline
implementation beside it. Each was reproduced through the real tool, launcher, store and runner on
synthetic files before it was corrected; each correction is stated above where it belongs and recorded
here as a correction rather than rewritten as though the design had always said so.

### 8.1 Probe interruption and recovery

As reviewed, a probe launch interrupted after `RunTask` and before its launch record left the started
task unaccounted for: the cleanup discovered probe tasks only from a launch record, so no record meant
no discovery, while the authorization stayed consumed; and a completion interrupted between its
permission record and the ledger replacement could not be repeated, leaving the row provisional for
good. Now the probe identity is **reserved beside the ledger before `RunTask`** with the whole
specification (§2.5), the cleanup accounts for the started probe from the reservation alone,
`--recover-probe-launch` records the row offline without relaunching, and completion is repeatable
without relaunching, removing evidence or leaving a partial completion unrepairable. `RunTask` is never
retried; discovery stays bounded; an unresolved discovery stays explicit.

### 8.2 Complete probe evidence binding

As reviewed, the one validator bound a probe-layer result through its permission chain only: with the
launch record removed, its verified placement substituted, a second launch record beside it, or the
ledger row reverted to exit-code-only, the matrix preserved `PASSED`; the receipt was not kept at all.
Now the validator requires the launch, receipt and ledger evidence stated in §2.5, refuses missing,
substituted, conflicting and duplicate launch evidence without selecting among candidates, and holds
the receipt outcome to the observed terminal exit and the permission observation to the attempt and
statement; a task-issued operation and the launcher's `ExecuteCommand` observation each need their own
evidence.

### 8.3 The held-task precondition

As reviewed, the launcher issued its `ExecuteCommand` immediately after the release, on the placement
description alone, without observing the task `RUNNING`: a task still `PENDING`, or stopped after the
release, was checked as if available, and a denial against it read `PASSED`. Now the bounded
precondition of §3 admits the check only on a fresh `RUNNING` description of exactly the launched task,
keeps that description as evidence, records every other outcome as no check made, and the completion
of the held subcell from the probe's own receipt holds the probe to having held; the evaluation-order
limitation is restated exactly. One `ExecuteCommand` attempt, explicit accounting, the
unexpected-success cleanup and the refusal to enable the capability are unchanged.

None of this opens the deletion rehearsal path (§4), grants a deferred permission, or changes the
gates of §7.
