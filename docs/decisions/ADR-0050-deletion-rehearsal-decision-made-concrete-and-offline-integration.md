# ADR-0050 — The deletion rehearsal decision made concrete, its offline integration, and its inert declaration

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0050 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **the concrete statement of Decision D-1 (§2) — the resources,
permissions, principals, target restriction, limits, interruption handling, cleanup and residual risk
the owner accepts or declines by taking it, presented for the owner's separate acceptance; the offline
integration of the deletion rehearsal path (§3) — the task under the actual deletion role, the launcher,
the completion, the collector's reuse and the owner tool's four modes, exercised only on fakes; the
inert declaration of the rehearsal resources (§4), closed by default; and the owner checklist (§5) —
and nothing else**, effective together with the offline code and the inert declaration merged beside it.
**Acceptance decides D-1 in neither direction**: D-1 is taken only by the owner's own explicit written
acceptance of §2.11, so on this merge the deletion rehearsal path stays **CLOSED** (`REHEARSAL_PATH_OPEN`
is `False`), the two R-8 subcells stay **BLOCKED**, and the declaration stays **inert**
(`deletion_rehearsal_open` is `false`; merging this ADR sets no variable). **Acceptance authorizes no
execution** (§7): no rehearsal, no deletion, no launch, no log read, no image build or publication, no
Terraform plan or apply, no IAM, permission-set, key-policy or bucket-policy change; and **acceptance
grants no permission** — every permission named here is declared behind a variable that is false, and
none is applied.

**Nothing was run to produce this decision.** No AWS call, no STS call, no log read, no S3 operation,
no `RunTask`, no `ExecuteCommand`, no deletion, no container image built or pulled, no registry
contacted, no credential retrieved, no provider request, no private input inspected. Every result beside
this text is a counting fake's on synthetic temporary files, and the Terraform was validated only in a
task-owned external copy under a mock provider. **Mocked results are not AWS verification.**

---

## 1. Context

ADR-0048 §4 designed the deletion role's rehearsal path. ADR-0049 §3 implemented its engine offline
(`deletion_rehearsal.py`: the target derived from the bound R-4 record, the statements, the consumed
authorizations, the `R8-GET` then `R8-LIST-AND-DELETE` sequence, the readings), kept it closed, and
presented Decision D-1 in one paragraph (§3.8): *open the path — set the constant, declare the resources
and the role delta, add the entry to the image, move the two subcells to an executable layer.* ADR-0049
is **ACCEPTED / IN FORCE** on the merge of PR #108 (2026-09-15T13:53:41Z, merge commit
`82cae1ebfcc99dbbc53f67e534e4d78ffb914d4a`); that acceptance decided D-1 in neither direction, and the
owner has asked for the decision to be made concrete before deciding it.

Three things were missing between ADR-0049's engine and a decision the owner could take on evidence:
the **task** that runs the engine under the actual deletion role (the engine's only caller was a test),
the **launcher** that puts it there through the accepted launch mechanisms, and the **declaration** of
what D-1 would apply. This ADR supplies all three offline and inert, and states D-1 as the exact
consequence of accepting them.

**Naming.** `production-owner-inputs.md` §A numbers the *release commit* decision "D-1"; the D-1 of
this ADR is ADR-0049 §3.8's Decision D-1 — the deletion rehearsal decision — and is always cited with
its ADR.

## 2. Decision D-1, made concrete

### 2.1 What accepting D-1 would do, exactly

Accepting D-1 authorizes the owner to, under the runtime authorizations of §2.10 and no earlier:

1. build the rehearsal entry into an image and register its digest under the `deletion_rehearsal` key;
2. set `deletion_rehearsal_open = true` in the git-ignored `terraform.tfvars` and apply the declaration
   of §4 at the stage then in force (stage a declares everything but the assignment; stage b adds it);
3. set `REHEARSAL_PATH_OPEN = True` in `deletion_rehearsal.py` and move `R8-GET` and
   `R8-LIST-AND-DELETE` from `BLOCKED` to an executable layer, in a reviewed pull request of their own;
4. materialize the rehearsal launcher profile `kalpamani-deletion-rehearse` and register the rehearsal
   launch inputs (§2.2);
5. run, per authorization, one rehearsal of one subcell against one synthetic object.

It authorizes nothing else. In particular it does **not** authorize a vendor-termination deletion, a
deletion of any object that is not the statement's target, a change to the deletion role's S3 authority,
or any run outside the R-8 subcells.

### 2.2 Resources and permissions introduced

Every value below is what `infra/aws/research-data-plane/production_deletion_rehearsal.tf` declares
(§4); none exists today.

| Resource | Exact value |
|---|---|
| task definition | family `kalpamani-deletion-rehearsal`; **task role `aws_iam_role.licensed_data_deletion`** — the actual deletion role; execution role `aws_iam_role.task_execution` (the foundation's); one container `deletion-rehearsal`, command `["kalpamani-deletion-rehearsal"]`, image `<research repository>@<production_image_digests["deletion_rehearsal"]>`; the production task shape (1024 / 2048, read-only root, `/work` tmpfs 256 MiB, `10001:10001`); `awslogs` to the research log group under stream prefix `production-deletion-rehearsal` |
| the deletion role's delta | one inline policy `<name_prefix>-deletion-rehearsal-bootstrap`: `ssm:GetParameter` on exactly `/kalpamani/production/deletion/runtime-binding`, `…/input`, `…/release`; `kms:Decrypt` on the task-bindings key with `kms:EncryptionContext:PARAMETER_ARN` = those three and `kms:ViaService` = Parameter Store; explicit denies on every other parameter read and every parameter write or encrypt. **No S3 statement is added, widened or removed** |
| runtime binding parameter | `/kalpamani/production/deletion/runtime-binding`, SecureString under the task-bindings key: `kalpamani-deletion-runtime-binding/v1` — account, region, licensed bucket, **the deletion role's exact name**, the ADR-0023 provenance block |
| launcher permission set | `KalpaManiDeletionRehearse` (25 characters), session `PT1H`, one customer-managed policy `<name_prefix>-deletion-rehearsal-launcher`: `ecs:RunTask` on exactly the rehearsal revision in the one cluster; `iam:PassRole` on exactly the deletion role and the execution role with `iam:PassedToService` = `ecs-tasks.amazonaws.com`, every other role closed by `NotResource`; `ecs:DescribeTasks` / `ecs:StopTask` in the one cluster; `ec2:DescribeNetworkInterfaces`; create-only `ssm:PutParameter` (`ssm:Overwrite` = false) and `ssm:DeleteParameter` on exactly `…/deletion/input` and `…/deletion/release`; `kms:GenerateDataKey` for exactly those two through Parameter Store; `logs:GetLogEvents` on exactly `…:log-stream:production-deletion-rehearsal/deletion-rehearsal/*`; explicit denies on every parameter read and decrypt, every other parameter write, task-definition registration, service creation, `ecs:ExecuteCommand`, **`s3:*`**, `secretsmanager:*` and `sts:AssumeRole` |
| key policy | two statements on the task-bindings key: the deletion role decrypts exactly the three rehearsal parameters; the rehearsal launcher's generated role (`AWSReservedSSO_KalpaManiDeletionRehearse_*`) generates the data keys of exactly the input and the release |
| assignment | `KalpaManiDeletionRehearse` → the governed operator group → the one account — **stage b only**, behind the same R-3 gate as every assignment |
| image | one more `production_image_digests` key, `deletion_rehearsal`; a separate image whose only entry is the rehearsal's |

**Nothing else changes**: no production actor's role, policy, permission set, task definition, network
or parameter; no bucket policy; no `iam.tf` statement; no qualification resource.

### 2.3 Who launches, and which role deletes

- **The launcher** is a human holding `KalpaManiDeletionRehearse` under the one profile
  `kalpamani-deletion-rehearse`; the tool proves its identity by `sts:GetCallerIdentity` (the generated
  role's exact prefix and suffix grammar in the bound account, ADR-0021's rule) **before any other
  client exists**, and the launch sequence proves it again before it consumes anything. The launcher
  **passes** the deletion role to ECS and holds **no S3 action** — it cannot list, read, write or delete
  an object itself.
- **The deletion role deletes.** The rehearsal task's task role is `aws_iam_role.licensed_data_deletion`;
  its credential is the Fargate container provider's, and the task proves it (`assumed-role/<deletion
  role name>/<task id>` in the bound account) before it reads its release. **No human and no control
  principal substitutes**: the engine's client is the task's own, built only after the release, and the
  control principal's only part is the cleanup afterwards.
- **No human may assume the deletion role**, before or after D-1: its trust policy admits ECS tasks only,
  and the launcher's `PassRole` is the one path to it.

### 2.4 How the target is restricted to the one synthetic object

- The **statement** (`kalpamani-deletion-rehearsal-statement/v1`) names the exact bucket and key —
  derived by the engine from exactly one MATCHED R-4 human `PutObject` record under the binding in
  force whose created key is the synthetic marker's content address and whose object no admissible
  cleanup has settled; nothing else is ever a target, and a supplied target does not exist as an input.
- The owner's **authorization** names the statement's digest and is **consumed durably before any
  mutation**; the **launch input** (`kalpamani-deletion-rehearsal-input/v1`) carries the whole statement,
  and the task recomputes its digest and holds the identity to its stamp.
- The **task** refuses a statement whose bucket is not the bound licensed bucket
  (`REFUSED_TARGET`, exit 58) before it proves its identity.
- The **engine** issues, per statement, exactly one `GetObject` of the exact key (`R8-GET`) or one
  `ListObjectsV2` (`MaxKeys=1`) and, only if that was allowed, one `DeleteObject` of the exact key
  (`R8-LIST-AND-DELETE`); no second key, no retry, no listing beyond one key.
- **IAM cannot express "this one key" for a delete** on the deletion role, whose authority is the
  bucket's objects by design (it is the vendor-termination role). The restriction to one object is
  therefore the code's — the task definition runs only the rehearsal entry, the entry runs only the
  engine, the engine issues only the statement's operations — and D-1 accepts that this is where the
  restriction lives (§2.9).

### 2.5 How production and unrelated resources are excluded

- Every rehearsal name is new and disjoint from every production, verification, probe and
  qualification name (family, entry, container, stream prefix, permission set, three parameters, one
  image key).
- The launcher can pass **no role but** the deletion role and the execution role; it holds no
  `ecs:RunTask` on any other revision and no S3, Secrets Manager or `sts:AssumeRole` action.
- The deletion role's S3 authority is **unchanged** (list and delete on the licensed bucket; no read, no
  write, no control bucket, no secret); the rehearsal adds three parameter reads and nothing else.
- The task's input is materialized by the launcher under a create-only parameter, so two launches cannot
  share one input; the release names one task ARN, one revision, one image and one input digest, and
  the task compares all four.
- No production actor, task definition, launcher, binding, key-policy statement (beyond the two gated
  ones), bucket policy or assignment is touched; the tftest run
  `rehearsal_open_at_stage_a_declares_the_task_the_set_and_no_assignment` holds that.

### 2.6 Operation limits

| Where | Bound |
|---|---|
| the launcher, per authorization | one `sts:GetCallerIdentity` before any client and one inside the sequence; one durable consumption; one reservation; **one `RunTask`, never retried**; ≤ 120 `DescribeTasks` reads within 600 s at 5 s polls (placement, then observation to the terminal state); ≤ 1 `DescribeNetworkInterfaces`; ≤ 1 `StopTask`; 2 create-only parameter puts (input, release) and 2 deletes; nothing else |
| the task, per launch | ≤ 2 parameter reads before the barrier; 1 identity call; ≤ 60 release reads within 300 s at 5 s polls; **one S3 client, built only after the release**; then exactly the statement's 1 or 2 operations |
| the collector, per collection | ADR-0049 §2's bounds unchanged: 40 requests, 20,000 events, 300 s, 15 s polls, 16-page passes, SDK retries zero |
| per authorization | one subcell, one synthetic object; the second subcell needs its own statement, its own authorization and the first recorded PASS |

### 2.7 Interruption handling

Every outcome is recorded, none is retried, and nothing is resolved by assumption:

| Interruption | Outcome recorded | The authorization | What follows |
|---|---|---|---|
| launcher identity refused | `REFUSED_IDENTITY` | **not consumed** | nothing written; prepare and authorize again under the right profile |
| authorization already consumed | `REFUSED_CONSUMED` | already spent | nothing written, no client call |
| a stale input parameter exists | `REFUSED_INPUT_EXISTS` | consumed, reserved | nothing launched; the stale parameter is the owner's to remove |
| `RunTask` refused definitively | `LAUNCH_REFUSED` | consumed, reserved | input deleted; no retry |
| `RunTask` answered ambiguously (transient, throttled, unknown, malformed) | `LAUNCH_AMBIGUOUS` | consumed, reserved | input deleted; **never retried**; a task may exist and the cleanup discovers it by the session tag |
| placement mismatch (subnet, groups, public IP, revision, image) | `MISPLACED` | consumed, reserved | task **stopped**, never released; no record |
| a stale release exists | `STALE_RELEASE` | consumed, reserved | task stopped; no record |
| task not observed terminal within the bounds | `OBSERVATION_EXHAUSTED` | consumed | launch record written **without an exit**; **completes nothing** (`LAUNCH_NOT_TERMINAL`) |
| task terminal without an exit code | `LAUNCHED`, exit `null` | consumed | completes nothing |
| a parameter cleanup fails | reported beside the outcome (`cleanup_failures`) | as above | never hidden |
| the task refuses (entry, credential environment, metadata, binding, input, target, identity, release) | a bound receipt with the closed refusal and its exit 51–58 | consumed | `TASK_REFUSED` — the launch completes nothing |
| the receipt contradicts the launch (exit, binding, statement, digest) | `EXIT_CONTRADICTS` / `RECEIPT_REFUSED` / `STATEMENT_CONTRADICTS` | consumed | no record |
| an ambiguous delete | `INCONCLUSIVE`, `possibly_deleted` | consumed | `CLEANUP_UNRESOLVED` until the control's later verified cleanup settles the key; `RESIDUE` if it cannot |
| the collector finds two distinct lines, or a refused line | ADR-0049's `CONTRADICTORY_RECEIPTS` / `RECEIPT_REJECTED` | consumed | as ADR-0049 §2.4 — a hand-read completion with an acknowledged disposition, or another read |

### 2.8 Cleanup

The control principal's existing cleanup pass, **verified and later than the record**, is the only thing
that confirms the object absent: a `204` from the deletion role is an **acknowledgement**, not
confirmation, and reads `CLEANUP_UNRESOLVED` until the cleanup names the prerequisite attempt and the
exact key `confirmed_absent`. **Cleanup by the control principal is never proof that the deletion role
succeeded**: a record whose delete was denied stays `FAILED` however the control cleaned up afterwards,
and a record whose delete answered ambiguously stays `INCONCLUSIVE` even once the control has removed
the object. A started task the launcher lost is discovered by the cleanup through the session tag
`kalpamani-rehearsal-<stamp>`, as for every probe launch.

### 2.9 Residual risk the owner accepts by taking D-1

1. **ADR-0007's verified inert property is reversed by design.** Today no task definition names the
   deletion role and no principal may pass it; after D-1 one task definition does and one launcher may.
   A human still cannot assume the role. The live property is re-verified after the apply as "a
   deletion task definition and a rehearsal launcher exist; no human may assume the role".
2. **The deletion role, once running, could delete any licensed object.** Its S3 authority is the
   bucket's objects; the restriction to one key is the rehearsal image's code (§2.4). The exposure is
   bounded by: the launcher can run only the rehearsal revision (one image, pinned by digest, whose only
   entry is the rehearsal's); the launcher passes no override, so the task command cannot be replaced at
   launch; the task refuses any input whose statement digest does not recompute, whose identity is not
   the stamp's, or whose bucket is not the bound one; the engine issues only the statement's operations.
   **A defect in that code, or a substituted image, is the risk** — and it is the reason the rehearsal
   image is a separate digest key, built from the exact release tree under the image gate, and the
   reason the rehearsal is run against the R-4 synthetic object first.
3. **One more standing capability.** A launcher permission set assigned at stage b is a standing
   authority to start the rehearsal task; it is held by the same governed group as every other launcher
   and bounded by its one-hour session, and its every launch needs a prepared statement, a written
   authorization and a fresh input.
4. **The receipt is on a log stream.** It carries classes, counts, digests and the target's bucket and
   key (a synthetic marker's content address under a production Bronze namespace) — no credential, ARN
   or account — and the launcher reads exactly that container's streams.
5. **Parameter Store and KMS charges** for one more SecureString parameter and two advanced-tier
   per-run parameters; the task-bindings key is already declared at stage a.

### 2.10 What acceptance enables, and what still needs its own authorization

| Enabled by accepting D-1 | Still separately authorized, each in writing |
|---|---|
| the reviewed pull request that sets `REHEARSAL_PATH_OPEN = True` and moves the two subcells to an executable layer | that pull request's merge |
| supplying `deletion_rehearsal_open = true` and the `deletion_rehearsal` digest in `terraform.tfvars` | the image build and registry push of the rehearsal image (the image gate, readiness §S1–S3) |
| registering the rehearsal launch inputs and materializing the launcher profile | the Terraform plan and apply that declares the resources (stage a), and the later apply that adds the assignment (stage b, after R-3) |
| preparing statements and writing authorizations | each `--rehearse-deletion` (one per subcell, per statement), each `--collect-rehearsal-receipt`, the cleanup afterwards |
| — | the R-4 human `PutObject` subcell that creates the target, under its own authorization, first |

### 2.11 The decision presented

> **Decision D-1 (ADR-0049 §3.8; this ADR §2).** I accept that the deletion rehearsal path be opened as
> §2.1–§2.10 state: the resources and permissions of §2.2 declared and, under separate authorizations,
> applied; the rehearsal task running as the actual deletion role, launched by `KalpaManiDeletionRehearse`;
> the target restricted to the one synthetic R-4 object by the statement, the input, the task's bucket
> check and the engine's exact operations, and not by IAM; the limits of §2.6; the interruption and cleanup
> rules of §2.7–§2.8; and the residual risks of §2.9, including the reversal of ADR-0007's inert property.
> I understand that accepting this decision authorizes no run, no image, no plan or apply and no
> assignment by itself, and that each of those needs its own written authorization (§2.10).
>
> Accepted / Declined: ______  Date: ______  By: the owner, in writing, outside this repository.

**This ADR's acceptance does not take D-1**; the owner takes it, or not, and nothing here infers it.
A declined D-1 leaves everything as it is: the path CLOSED, the subcells BLOCKED, the declaration inert,
the R-4…R-9 aggregate unable to read VERIFIED and the deletion runbook unrehearsed.

## 3. Decision — the offline integration

### 3.1 What exists, and what was named and not implemented before

| Component | Before this cycle | Now |
|---|---|---|
| the engine (`deletion_rehearsal.py`) | implemented, ADR-0049 §3 | unchanged; its container name is the collector's constant |
| the task (`deletion_rehearsal_task.py`) | named (§3.1–§3.2), not implemented | implemented: `run_rehearsal_task` |
| the launcher (`deletion_rehearsal_launch.py`) | named (§3.2), not implemented | implemented: `launch_rehearsal`, `complete_rehearsal` |
| the collector over the rehearsal receipt | not implemented | the accepted collector with an injected verifier (`rehearsal_receipt_verifier`) |
| the owner tool (`production_permission_cells.py`) | `--rehearse-deletion` refused | four modes, all refused while closed (`production_deletion_rehearsal_tool.py`) |
| the declaration | named, not declared | declared inert (§4) |

### 3.2 The task under the actual deletion role

`run_rehearsal_task(argv, adapters)` composes, in the accepted bootstrap's order and with every adapter
injected: the entry (exactly `["kalpamani-deletion-rehearsal"]`); the credential environment by variable
name (a workstation variable present, or the container provider absent or malformed, refuses); the
task metadata (one image, its digest, the task's own revision ARN); the **rehearsal runtime binding**
(`kalpamani-deletion-runtime-binding/v1`: the build binding's field set with `deletion_role_name` in
place of a profile, `binding_kind` = `kalpamani-deletion-rehearsal-runtime`, provenance validated by
the accepted ADR-0023 rule); the **input** (`kalpamani-deletion-rehearsal-input/v1`: the identity
`rehearsal-<stamp>`, the whole statement with its digest recomputed and held, the consumed
authorization's digest, ≤ 24 h validity); the target held to the bound bucket; the **identity**
(`sts:GetCallerIdentity`: an assumed-role ARN in the bound account whose role name is exactly the
binding's `deletion_role_name` and whose session is this task's id — a human, the launcher, another
role, another account or an IAM role ARN refuses); the **release** (`kalpamani-deletion-rehearsal-release/v1`,
≤ 10 min: exactly this task ARN, revision, image, identity and input digest, read at 5 s polls within
60 reads and 300 s, `ParameterNotFound` the one tolerated failure); and only then one S3 client and
`rehearse_subcell` with `identity_verified=True`. No later stage runs after a refusal, and no client
exists before the release.

The task emits **one receipt line** on the shared prefix (`kalpamani-deletion-rehearsal-receipt/v1`):
the outcome and its exit status — **50 `REHEARSED`, 51–58 the refusals in order, 59 unclassified**, a
table disjoint from every production, verification and probe table — the **binding digest** over the
task id, revision, image, identity and input digest (present once the input was read), and, exactly
when it rehearsed, the record's block (subcell, statement and authorization digests, target, observed
classes, outcome, `deleted`, `possibly_deleted`, operations, `identity_verified`, stamp) — never the
started and finished instants, never the binding, never a credential, role name or account. The line's
digest covers the body; the collector's verifier and the completion verify every clause in order.

### 3.3 The launcher

`RehearsalLaunchInputs` (`kalpamani-deletion-rehearsal-launch-inputs/v1`) is what the owner registers
once the declaration is applied: cluster, the rehearsal revision (its family held to
`kalpamani-deletion-rehearsal`), the image digest, the execution role, the deletion role (its name held
to `-licensed-data-deletion`), the build subnet, the security groups, the platform version, the binding
key and the log destination (held to the rehearsal container and prefix), every ARN in one account.
`CompiledRehearsalLaunch` is the `RunTask` request: **no `overrides`**, `enableExecuteCommand` false,
no public IP, `startedBy` = `kalpamani-rehearsal-<stamp>`.

`launch_rehearsal` reuses the accepted mechanisms as libraries — the launch store's durable
`consume` and record naming, the compute adapter's task parser and failure classification, the EC2
interface adapter, the SSM parameter adapter — in this order: the launcher's identity → the
authorization consumed (`deletion_rehearsal_authorization`) → the **reservation** beside the ledger
(`kalpamani-deletion-rehearsal-reservation/v1`: identity, subcell, statement, authorization and
compiled-launch digests) → the create-only input → **one `RunTask`** (a definitive refusal is
`LAUNCH_REFUSED`; a transient, throttled, unknown or malformed answer is `LAUNCH_AMBIGUOUS`; neither is
retried) → placement verified from `DescribeTasks` and `DescribeNetworkInterfaces` (subnet, groups, no
public IP, the compiled revision, the compiled image; a mismatch stops the task and never releases it)
→ the create-only release → observation to the terminal state within 120 reads / 600 s → the two
parameters deleted (every failure reported beside the outcome) → the **launch record**
(`kalpamani-deletion-rehearsal-launch-record/v1`: the task, revision, image, input digest, interface,
subnet, groups, the observed exit, the instants, the statement, authorization and specification
digests, the binding).

`complete_rehearsal(launch, receipt_document, statement)` rebuilds the rehearsal record from the
verified receipt and nothing else: the launch must be `LAUNCHED` with an observed exit
(`LAUNCH_NOT_TERMINAL`); the statement's digest must be the launch's (`STATEMENT_CONTRADICTS`); the
receipt must verify against the launch record's expectation (`RECEIPT_REFUSED`); its exit must equal
the exit the launcher observed (`EXIT_CONTRADICTS`); it must be `REHEARSED` (`TASK_REFUSED` — a task
that refused established nothing); its block must carry the statement's own subcell, target and stamp;
and `identity_verified` must be true (`IDENTITY_NOT_VERIFIED`). The record's instants are the launch's,
its binding the launch's; the receipt supplies classes and counts only. **No outcome is derived from a
supplied result or an identity boolean alone**: the result binds the statement, the consumed
authorization, the reservation, the launch record, the verified receipt and — for the deletion — the
control principal's later confirmation.

### 3.4 The collector, reused

`collect_receipt` and `admit_collection_records` take either the task receipt's expectation (the
accepted default) or an injected verifier; the rehearsal supplies `rehearsal_receipt_verifier(expectation)`
over the launch record's expectation, and the rehearsal container is a known destination. The bounds,
the complete-scan rule, the confirmation re-read, the closed outcomes, the collection record and the
one admission rule — contradictions, dispositions, the receipt binding — are ADR-0049's unchanged.

### 3.5 The owner tool's four modes, and the closed gate

`production_permission_cells.py` gains `--prepare-rehearsal <subcell>`, `--rehearse-deletion <subcell>
--rehearsal-inputs <file> --authorization <file> <AUTHORIZATION_FLAG>`, `--collect-rehearsal-receipt
<subcell> --rehearsal-inputs <file> <COLLECT_FLAG>` and `--complete-rehearsal <subcell> --receipt-lines
<file>`; naming any of them, or `--rehearsal-inputs` alone, while `REHEARSAL_PATH_OPEN` is `False`
prints the closed sentence and exits **27** before any path, flag or client is read and before the
rehearsal tool module is imported. The open branch (`production_deletion_rehearsal_tool.py`, exercised
in tests with the constant monkeypatched) reuses the tool's admission, evidence, records directory and
sentences: preparation writes a `rehearsal-statement` record and prints its digest; the launch recomputes
the statement the authorization names against what is admitted now, holds the launch inputs to the bound
account, proves the launcher's identity under `kalpamani-deletion-rehearse` before any client, refuses
while an earlier launch of the subcell is still uncompleted, and prints the outcome (`LAUNCHED` exits 0;
every other sequence outcome exits 31, `rehearsal_not_launched`; identity 4; consumed 16); collection
reuses the one admission rule, reads the stream under the launcher, records the collection and completes;
completion from hand-read lines takes exactly one receipt line; every completion writes the
`rehearsal-record` and prints the reading derived with the control principal's cleanups (PASSED 0,
FAILED 9, INCONCLUSIVE 10, CLEANUP_UNRESOLVED / RESIDUE 12). A malformed rehearsal record refuses every
mode (32).

### 3.6 The holds, and where each is tested

| Hold | Test |
|---|---|
| actual deletion-role execution; no human substitution | `test_production_deletion_rehearsal_path.py::TestRehearsalTask` (identity: the launcher's role, a human, another role, another account refuse) |
| exact target and prerequisite evidence bound to the authorization | the statement carries the R-4 target and its prerequisite digest; the input carries the statement; the task recomputes it (`REFUSED_INPUT` on a tampered key) and holds the bucket (`REFUSED_TARGET`) |
| durable consumption before mutation; no retry after an ambiguous attempt | `TestRehearsalLaunch` (`REFUSED_CONSUMED` with no call; `LAUNCH_AMBIGUOUS` once, the input deleted, the reservation kept) |
| ordered R8 read-refusal then list/delete on the same target | `test_production_deletion_rehearsal_tool.py` (R8-LIST-AND-DELETE preparable only after R8-GET is recorded); the engine's own tests |
| no PASSED from a supplied outcome or identity boolean | `complete_rehearsal` refusals (`TASK_REFUSED`, `IDENTITY_NOT_VERIFIED` under a valid digest); the derivation with `identity_verified` false |
| result binds statement, authorization, attempt, execution evidence, receipt and confirmation | `TestCompletionAndReading` (the launcher's own record refuses the receipt until the input bytes bind; `CLEANUP_UNRESOLVED` until the control's later verified cleanup) |
| deletion acknowledgement ≠ confirmed absence; cleanup by the control is not the role's success | `derive_rehearsal` with a denied delete stays `FAILED` after the control's cleanup; an ambiguous delete stays `INCONCLUSIVE` |
| interrupted or conflicting evidence stays unresolved | `OBSERVATION_EXHAUSTED` and a `null` exit complete nothing; the collector's `RECEIPT_REJECTED` and contradictions refuse |
| public path closed before any client | the closed test with a refusing client factory over all four modes |

## 4. Decision — the inert declaration

`production_deletion_rehearsal.tf` declares the resources of §2.2, each gated on
`local.deletion_rehearsal_count` — `production_stage` a or b **and** `var.deletion_rehearsal_open`
(**false by default**) **and** a `deletion_rehearsal` image digest — and the assignment on that and
stage b. The two key-policy statements in `production_bindings.tf` are dynamic statements on the same
local. Under the committed defaults the configuration declares **nothing** new and the key policy is
exactly the accepted seven statements; `iam.tf` is untouched. Validated in a task-owned external copy
under the pinned provider (`terraform fmt -check`, `init -backend=false`, `validate`, `terraform test`
with the mock provider: 20 runs, five of them new — stage none, the closed default at stage a with the
digest, open without the digest, open at stage none, open at stage a with no assignment, open at stage b
with the one assignment), and held by `test_production_deletion_rehearsal_declaration.py` over the parsed
HCL. **Declaring is not applying**; no plan and no apply were run, and none is authorized.

## 5. Owner inputs

[`production-owner-checklist.md`](../operations/production-owner-checklist.md) is the one prioritized
checklist — before local image preparation, before publication or infrastructure change, before
verification launches and collection, before the first production acquisition and build — each item with
its purpose, format, authoritative source, dependencies and whether an accepted value exists. **Every
private value is MISSING**; none was read or invented; values obtainable only after a runtime step are
marked so. The rehearsal's own items are the D-1 decision (§2.11), the rehearsal image digest, the
`deletion_rehearsal_open` variable, the launch-inputs record, the launcher profile, and one
authorization per subcell.

## 6. Amendments stated

- **ADR-0049 §3.8**: D-1 is made concrete by §2 here; its wording, consequences and the rule that
  acceptance of an ADR never takes it are unchanged.
- **ADR-0049 §3.2 / §3.3**: the resources and the role delta are now declared (inert) exactly as named,
  with two additions the implementation required and the text now states: `logs:GetLogEvents` for the
  rehearsal launcher on exactly the rehearsal container's streams (the collector; ADR-0049 §2.6's rule
  applied to this one launcher), and the launcher's authority to write the **input** parameter as well as
  the release, there being no human deletion profile to write it.
- **ADR-0007**: unchanged today; on D-1's acceptance and apply its verified property reads as §2.9 item 1.
- **ADR-0036 §2.9**: unchanged; the rehearsal launcher is a sixth launcher-shaped set, declared inert.
- No accepted request, key builder, bucket policy, assignment, production actor or deletion S3 authority
  changes; no ADR is superseded.

## 7. Effectiveness and execution gates

Acceptance of this ADR authorizes **no** rehearsal, **no** deletion, **no** launch, **no** log read,
**no** collection, **no** image build or publication, **no** Terraform plan or apply, **no** IAM,
permission-set, key-policy or bucket-policy change, **no** profile materialization, and grants **no**
permission. It does not take D-1. `REHEARSAL_PATH_OPEN` stays `False`, `deletion_rehearsal_open` stays
`false`, the two R-8 subcells stay BLOCKED, every executable subcell stays UNEXECUTED, and every owner
value stays MISSING. **G2 stays OPEN, CONTROL stays DEFERRED, Phase 3 stays NOT COMPLETE, live trading
stays HARD-DISABLED.**
