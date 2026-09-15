# ADR-0049 — Receipt collection from the launch's own stream, and the deletion rehearsal decision

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0049 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **the bounded receipt collector (§2) — the derivation of a launch's
log stream from the bound launch record and the registered task-definition evidence, the collection's
bounds and outcomes, the collection record, and its integration into the two tools' existing
completion paths — together with the narrow amendments it states (§4) and the offline implementation
of the deletion rehearsal path (§3.1–§3.7) that ADR-0048 §4 designed; and nothing else**, effective
together with the offline code merged beside it. **Acceptance decides §3.8's Decision D-1 in neither
direction**: D-1 is presented here for the owner and is taken only by its own explicit acceptance, so
the deletion rehearsal path stays CLOSED and the two R-8 subcells stay BLOCKED on this merge.
**Acceptance authorizes no execution** (§5): no log read, no collection, no probe launch, no permission
subcell, no rehearsal, no deletion, no cleanup, no run, no image build or publication, no Terraform plan
or apply, no IAM, permission-set or bucket-policy change; and **acceptance grants no permission** — the
`logs:GetLogEvents` the collector needs is recorded in §2.6 as required and not granted, and the
rehearsal's resources in §3.2 are named and not declared.

**Nothing was run to produce this decision.** No AWS call, no STS call, no log read, no S3 operation,
no `RunTask`, no `ExecuteCommand`, no deletion, no container image built or pulled, no registry
contacted, no credential retrieved, no provider request, no private input inspected. Every result beside
this text is a counting fake's or an intercepted transport's, on synthetic temporary files. **Mocked
results are not AWS verification.**

---

## 1. Context

ADR-0044 §4 made the task receipt the delivery boundary and proposed, and deferred, a workstation
**collector** that reads the receipt from the task's log stream; until now the owner hand-reads the
line and hands it to the tools (`--receipt-lines`, `--complete-row`, `--complete-subcell`). ADR-0048 §4
**designed** the deletion role's rehearsal path for the two R-8 subcells ADR-0047 left BLOCKED, and
took no decision to open it. ADR-0048 is ACCEPTED / IN FORCE since PR #107 merged (2026-09-15T10:22:22Z,
merge commit `c0566574c41bc31b7144fafe919078a213982143`); this ADR synchronizes nothing of that itself —
the synchronization travels beside it — and builds on it.

Two things are delivered offline in one cycle because they share one boundary: the collector is the
first tool that reads anything a task produced, and the rehearsal is the first path whose principal is
neither a human nor the control principal. Both are held to the same rules — a derived, never supplied
target; durable consumption before mutation; the existing verifier; classes and counts, never content.

## 2. Decision — the bounded receipt collector

### 2.1 The destination is derived, never supplied

The registered task-definition evidence (ADR-0045 §3, `kalpamani-launch-inputs/v1`) gains **one
optional block**, `log_destination` (`log_group`, `stream_prefix`, `container`): the research log group
(`/kalpamani/<name_prefix>/research`, `logging.tf`) and the stream prefix the owner transcribed from
the applied revision, and the container the entry runs in. The collector derives the stream of one
launch as **`<stream_prefix>/<container>/<task-id>`** from the bound launch record's task id and that
registered block, and holds the block to the declaration's rule for the record's entry (the container
is the entry's short name, the prefix `production-` + container): a registration that names no
destination refuses (`DESTINATION_UNREGISTERED`), one that names another entry's refuses
(`DESTINATION_NOT_THE_ENTRY_S`), and **no caller-supplied stream is accepted as evidence for a launch**.
A registration made before this block existed stays valid; the collector refuses until the owner
registers the destination.

### 2.2 The read: bounds, and what they mean

`GetLogEvents` from the head with the forward token; a page whose token equals the one it was asked
with is the end of the stream as delivered so far (the documented signal), and every further poll
continues from that token. Bounds: at most **16 pages per pass** and **40 requests per collection**,
each page the service's own ceiling (10,000 events or 1 MiB); at most **20,000 events scanned**;
delivery lag polled at **15 s** for at most **300 s** on an injected monotonic clock. **Effective SDK
retries: zero** — the logs client is built with `total_max_attempts = 1` in `standard` mode and finite
socket timeouts, the same configuration as every workstation client; a throttled or failed request is
recorded, never retried inside the SDK, and the collector re-issues nothing within a pass.

Outcomes (`CollectionOutcome`, closed, **never a receipt verdict**): `COLLECTED` (exactly one distinct
receipt line); `NO_RECEIPT_WITHIN_BUDGET` and `STREAM_NOT_FOUND_WITHIN_BUDGET` — **the budget was
exhausted before a line was obtained, which proves nothing about whether one exists**; a later
collection may still find it; `CONTRADICTORY_RECEIPTS` (two distinct receipt lines: refused, never
chosen between; the same line delivered twice is one line); `DENIED`, `THROTTLED`, `FAILED` (one request,
its own class, no retry). A malformed line is *collected* and then refused by the verifier: **a
successful log read is not a successful verification.**

### 2.3 The same verifier, the same completion, no weaker route

The collected line passes through exactly the hand-read path: `collect_and_verify` against the launch
record's expectation (entry, task id, revision, image, identity, input digest, configuration, commit —
the binding digest), the launch record bound to its reservation, the receipt's outcome held to the
observed terminal exit, and then the existing completion — `complete_row` for a production or
verification launch, `complete_subcell` for a probe launch, with the receipt evidence, the ledger row
and (probe) the permission record exactly as ADR-0048 §2.5 states. Wrong task, wrong stream (a stream
is never supplied), wrong registration, wrong configuration and wrong input each refuse where the
hand-read receipt refuses. A FAILED or INCONCLUSIVE subcell keeps its reading: collection completes
evidence and changes no verdict.

### 2.4 Evidence, and what is never kept

One **collection record** (`kalpamani-receipt-collection/v1`) per collection, whatever its outcome:
identity, the launch record's digest, the log group and stream, the outcome, the request, page and
event counts, the count of distinct receipt lines, and — only when `COLLECTED` — the receipt line
itself, which is the closed receipt document (tokens, counts, digests). **No other event is stored**;
every other line is counted and discarded, so no arbitrary log content leaves the stream through the
collector. The record lives under the governed private root beside the launch records.

### 2.5 Repeatable, and where the real client lives

A collection recorded `COLLECTED` for a launch is reused and the stream is not read again; a
completion interrupted after the collection record repairs itself on the next run without a read. The
logs client is built **only inside the collection flag** (`--i-am-the-owner-authorizing-receipt-
collection`, with `--complete-row --collect-receipt` in the launch tool and `--collect-receipt
<subcell>` in the permission tool), after the record, its reservation, the registered destination and
the actor's **launcher identity** (the accepted human bootstrap) are admitted; every test injects a fake
or intercepts the transport.

### 2.6 Permissions required, and not granted

The launcher permission sets (`KalpaManiProductionAcquire` / `KalpaManiResearchBuild` launchers) would
need **`logs:GetLogEvents`** on exactly the research log group's streams of their own families —
resource `arn:aws:logs:<region>:<account>:log-group:/kalpamani/<name_prefix>/research:log-stream:
production-<container>/<container>/*` for each of the actor's containers (production, verify, probe) —
and nothing wider (no `logs:FilterLogEvents`, no `DescribeLogStreams`, no other group). **This ADR
grants nothing**: the delta is the infrastructure cycle's, separately authorized, declared then and
not now. Until it is applied, every collection answers `DENIED` after one request.

## 3. Decision — the deletion rehearsal: implemented offline, closed, with the decision presented

ADR-0048 §4 designed the path; `deletion_rehearsal.py` implements it offline, on fakes, and keeps it
closed: **`REHEARSAL_PATH_OPEN = False`**, the catalogue keeps `R8-GET` and `R8-LIST-AND-DELETE`
BLOCKED with the dependency naming this ADR's D-1, the permission tool refuses `--rehearse-deletion`
before it reads any path or flag, and the engine's only callers are the tests. **Implementation
availability is not authority to execute.**

### 3.1 The execution model

The rehearsal runs **under the actual deletion role**, as a task: a rehearsal family whose task role is
the deletion role, launched by a rehearsal launcher that passes exactly that role and the foundation
execution role to ECS. **No human and no control principal ever substitutes for the deletion role**: the
engine's client is the task's own (in tests, a fake acting as that role), and the control principal's
only part is the cleanup that confirms the object absent afterwards — the deletion role cannot read, so
it confirms nothing itself.

### 3.2 Exact rehearsal resources, and how production resources are excluded

| Resource | Exact value | Existence today |
|---|---|---|
| task family / entry / container | `kalpamani-deletion-rehearsal` / `kalpamani-deletion-rehearsal` / `deletion-rehearsal` | none |
| log stream prefix | `production-deletion-rehearsal` | none |
| launcher permission set | `KalpaManiDeletionRehearse` (`ecs:RunTask` on exactly the rehearsal revision in the one cluster; `iam:PassRole` on exactly the deletion role and the execution role, closed by `NotResource`, `iam:PassedToService` = ECS; `ecs:DescribeTasks` / `StopTask` in the cluster; `ec2:DescribeNetworkInterfaces`; create-only `ssm:PutParameter` and `DeleteParameter` on the three rehearsal parameters; an explicit deny on `ecs:ExecuteCommand`) | none |
| parameters | `/kalpamani/production/deletion/runtime-binding`, `…/input`, `…/release` | none |
| runtime binding contract | `kalpamani-deletion-runtime-binding/v1` (the build binding's field set) | none |
| placement | the build subnet (no internet route), read-only root, `/work` tmpfs, `enableExecuteCommand` false | — |

**Production resources are excluded by construction**: the rehearsal's only target is the one
synthetic object the bound R-4 human `PutObject` record created — the synthetic marker's own content
address under a production Bronze namespace — and the engine refuses any other key (§3.5); the
family, launcher, parameters and stream are all new names disjoint from every production, verification
and probe resource; the launcher can pass no role but the deletion role and the execution role.

### 3.3 Required role and bootstrap changes, and their scope

The deletion role would gain **only** the accepted task bootstrap shape (ADR-0036 §2.5):
`ssm:GetParameter` on exactly its three parameters and `kms:Decrypt` on the binding key. **Its S3
statements do not change** — no widening of what it may list or delete, no read. The rehearsal
launcher is a new permission set assigned to the governed group. ADR-0007's recorded property becomes
"a deletion task definition and a rehearsal launcher exist; no human may assume the role", and the live
inert property is re-verified after the apply. **None of this is declared here**; it is the exact
declaration D-1's acceptance would make.

### 3.4 Authorization binding, and durable consumption before mutation

Each subcell is prepared as a **rehearsal statement** (`kalpamani-deletion-rehearsal-statement/v1`)
binding the subcell, the principal (`DELETION_ROLE`), the operation and expectation, the exact target
(bucket, key, the prerequisite record's digest), its position in the sequence, the session stamp and
the environment/declaration binding; the owner's authorization names the statement's digest
(`kalpamani-permission-authorization/v1`, unchanged) and is **consumed durably beside the ledger**
(`deletion_rehearsal_authorization`) before any operation is issued — one execution per
authorization, whatever follows; a second consumption refuses.

### 3.5 Preconditions and evidence for each subcell

The **target** is derived, never supplied: exactly one MATCHED R-4 human `PutObject` record under the
current binding that binds through the one validator (ADR-0047 §3.4, ADR-0048 §2.5), whose created key
is the synthetic marker's content address, and whose object no admissible cleanup has already
confirmed absent. The **sequence** is fixed: `R8-GET` first, while the object exists; `R8-LIST-AND-
DELETE` second, only after `R8-GET` is recorded PASS under this binding.

| Subcell | Operations | PASS | FAIL | INCONCLUSIVE |
|---|---|---|---|---|
| `R8-GET` | one `GetObject` of the exact key | a denial | a body-returning answer (the role could read) | any other class (timeout, ambiguous) |
| `R8-LIST-AND-DELETE` | one `ListObjectsV2` (`MaxKeys=1`), then — only if allowed — one `DeleteObject` of the exact key | 200 then 204, **and** a later verified control cleanup confirming the exact key absent | a denial on either | an ambiguous delete (`possibly_deleted`, settled only by the control), or an ambiguous list |

Every record (`kalpamani-deletion-rehearsal-record/v1`) carries classes and counts, the target, the
statement and authorization digests, whether the identity was verified, and the two open-object flags;
an unverified identity never reads PASSED.

### 3.6 Interruption, ambiguous responses, cleanup and residue

An authorization consumed before an interruption stays consumed; a delete that answered ambiguously
leaves the object `possibly_deleted`, and the control principal's cleanup — the existing pass, by exact
attempt and key — confirms it absent (`CLEANUP_UNRESOLVED` until then) or reports it as residue
(`RESIDUE`); an unverified cleanup pass settles nothing. No retry, no second key, no relaunch.

### 3.7 What the readings mean

`PASSED` needs a verified identity, the expected class on every operation and, for the deletion, the
control's confirmation; `FAILED` is the observed contradiction; `INCONCLUSIVE` decides nothing and is
never rounded up; `CLEANUP_UNRESOLVED` and `RESIDUE` are exactly what they say. **Two subcells, two
readings; the cell passes only when both pass.**

### 3.8 Decision D-1 — the smallest concrete decision, and its consequences

**D-1: open the deletion rehearsal path** — set `REHEARSAL_PATH_OPEN = True`, declare the resources of
§3.2 and the role delta of §3.3 (Terraform, validated in an external copy, then a separately
authorized plan and apply), add the rehearsal entry to the image and the launcher to the governed
group, and move `R8-GET` and `R8-LIST-AND-DELETE` from BLOCKED to a `L3_REHEARSAL` layer executed by
the engine above.

Consequences the owner accepts by taking it: the verified ADR-0007 property "no execution path exists
for the deletion role" is **reversed** by design (a task definition and a launcher exist; a human still
cannot assume the role); one more family, launcher and three parameters are applied; the deletion role
gains two bootstrap permissions; the rehearsal deletes exactly one synthetic object per authorization.
Consequences of not taking it: R8-DELETION stays BLOCKED, so the R-4…R-9 aggregate cannot read
VERIFIED, and the deletion runbook stays unrehearsed. **This ADR's acceptance does not take D-1**; the
owner takes it, or not, as its own decision, and nothing here infers it.

## 4. Amendments stated

- **ADR-0045 §3, narrowly**: the task-definition evidence admits one optional block, `log_destination`
  (§2.1); the launch-inputs contract identity is unchanged.
- **ADR-0044 §4/§5, narrowly**: the deferred collection is delivered as §2; the `logs:GetLogEvents` delta
  stays the infrastructure cycle's (§2.6), scoped to the launcher sets' own families' streams.
- **ADR-0036 §2.9, narrowly**: the launcher permission sets' documented scope gains the logs read of
  §2.6 **as a requirement**, declared and granted only by the infrastructure cycle.
- **ADR-0048 §4**: unchanged as the design; §3 here implements it offline and presents D-1.
- No accepted request, key builder, bucket policy, assignment, human permission set or deletion
  authority changes; no ADR is superseded.

## 5. Effectiveness and execution gates

Acceptance of this ADR authorizes **no** log read, **no** collection, **no** probe launch, **no**
permission subcell, **no** rehearsal, **no** deletion, **no** cleanup, **no** run, **no** image build or
publication, **no** Terraform plan or apply, **no** IAM, permission-set or bucket-policy change, and
grants **no** permission. Each tool refuses by default; a collection needs its own flag and the launcher
identity; the rehearsal path stays CLOSED and D-1 stays the owner's. **G2 stays OPEN, CONTROL stays
DEFERRED, Phase 3 stays NOT COMPLETE, live trading stays HARD-DISABLED.**
