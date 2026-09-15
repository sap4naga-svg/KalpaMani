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

`GetLogEvents` from the head with the forward token, in passes of at most **16 pages**; a page whose
token equals the one it was asked with is the end of the stream as delivered so far (the documented
signal). Bounds: **40 requests per collection**, each page the service's own ceiling (10,000 events or
1 MiB); **20,000 events scanned**; **300 s elapsed** on an injected monotonic clock, delivery lag
polled at **15 s**. **Every bound is checked before a request is issued** — the request count, the
event count and the elapsed time each refuse the next request when reached, and a page whose events
would cross the event ceiling is scanned only up to it (§6, correction 1). **The one limit the
collector cannot enforce is a request already in flight**: an issued request completes, or fails,
within the client's own connect and read timeouts (the workstation client configuration — finite,
one attempt in total), so a collection's elapsed time may exceed the ceiling by at most one request's
in-flight time, and the record's `elapsed_ms` says by how much. **Effective SDK retries: zero** — the
logs client is built with `total_max_attempts = 1` in `standard` mode; a throttled or failed request
is recorded, never retried inside the SDK, and the collector re-issues nothing.

**A complete scan, and only a complete scan, establishes one line.** The stream is read to its end
(the repeated token) and, after one poll interval, re-read from that token; a re-read that delivers
nothing new closes the **observation window**, which every record carries (`started_at`,
`finished_at`, `scan_complete`). Exactly one distinct receipt-shaped line in a complete scan is the
candidate; a receipt-shaped line seen in a scan the budget cut short is `SCAN_INCOMPLETE` — nothing is
established, and the line is not kept; two distinct receipt-shaped lines are `CONTRADICTORY_RECEIPTS`
at once, whether or not the scan completed. **Delayed delivery is the stated limitation**: the
`awslogs` driver delivers with lag, and the window closes on the stream *as delivered* by
`finished_at` — an event delivered after that was not observed. That is why a collection is refused
until the launcher observed the task's terminal state (a stopped task writes nothing more), and why
`COLLECTED` means *unique within the observed window*, not unique on the stream for all time.

**The candidate is verified before anything of it is kept.** It must decode as the closed receipt
document and verify against the launch record's expectation (the binding digest over task id,
revision, image, identity and input digest; the configuration digest; the commit) inside the
collector; a line that does not is `RECEIPT_REJECTED`, and its record carries the closed
`ReceiptDefect` and the line's byte count — **never the text**. A closed receipt document that verifies
but contradicts the launch in what only the completion can see (the observed terminal exit; for a
probe, the permission block's attempt, statement and stamp) is `COLLECTED` — it is closed evidence
of that contradiction and holds no arbitrary text — and the completion refuses it exactly as a
hand-read one, repeatably.

Outcomes (`CollectionOutcome`, closed, **never a receipt verdict**): `COLLECTED`; `RECEIPT_REJECTED`;
`SCAN_INCOMPLETE`; `NO_RECEIPT_WITHIN_BUDGET` and `STREAM_NOT_FOUND_WITHIN_BUDGET` — **the budget was
exhausted before a line was obtained, which proves nothing about whether one exists**; a later
collection may still find it; `CONTRADICTORY_RECEIPTS` (refused, never chosen between; the same line
delivered twice is one line); `DENIED`, `THROTTLED`, `FAILED` (one request, its own class, no retry).
**A successful log read is not a successful verification**: the completion re-verifies the kept line
as a hand-read one.

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

One **collection record** (`kalpamani-receipt-collection/v1`, closed: `parse_collection_record`
admits exactly its fields) per collection, whatever its outcome: identity, the launch record's
digest, the log group and stream, the outcome, the request, page and event counts, the count of
distinct receipt-shaped lines, `scan_complete`, the observation window (`started_at`, `finished_at`,
`elapsed_ms`), and — only when `COLLECTED` — the verified receipt line itself, which is the closed
receipt document (tokens, counts, digests); only when `RECEIPT_REJECTED`, the closed defect and the
byte count. **No other event and no rejected text is stored**; every other line is counted and
discarded, so no arbitrary log content leaves the stream through the collector. The record lives
under the governed private root beside the launch records, and nothing is ever removed from there.

### 2.5 Repeatable, and where the real client lives

Both tools admit the recorded collections of a launch through **one rule**
(`admit_collection_records`): every `receipt-collection` record about the identity is read, each is
held to the launch record's digest and to the derived group and stream, a kept line is re-verified
against the expectation, and two different kept lines are a contradiction — `RECORD_MALFORMED`,
`LAUNCH_MISMATCH`, `DESTINATION_MISMATCH`, `RECEIPT_UNVERIFIABLE`, `CONTRADICTORY_RECORDS` each refuse
the completion (`refused_collection_records`), **and nothing is chosen by filename order or by any
other order**. A verified `COLLECTED` record is reused and the stream is not read again; a completion
interrupted after the collection record repairs itself on the next run without a read. **Recovery
from a rejected attempt is explicit and automatic**: a `RECEIPT_REJECTED`, `SCAN_INCOMPLETE`,
exhausted, denied, throttled or failed record never blocks — the next collection reads the stream
again and its record is written beside the earlier ones. **A recorded `CONTRADICTORY_RECEIPTS` is
never superseded** (§6, correction 2): while it stands, the admission rule refuses
(`CONTRADICTION_UNRESOLVED`) — no later collection is made, no `COLLECTED` record recorded before or
after it is reused, and no ordering changes that. The one route past it is **explicit and
evidence-bound**: the owner reads the stream, completes from a hand-read receipt
(`--complete-row --receipt-lines` / `--complete-subcell --receipt-lines`) and acknowledges the
contradiction record by its digest (`--acknowledge-collection-contradiction <sha256>`, repeatable;
refused beside a collection, refused for a digest that names no recorded contradiction, and every
unresolved contradiction must be acknowledged); the tool then writes one **disposition** record
(`kalpamani-collection-disposition/v1`: identity, launch record digest, the contradiction record's
digest, the digest of the receipt line completed from, `HAND_READ_COMPLETION`, the instant) beside
the untouched contradiction record, and only a disposed contradiction admits the launch again. No
rule chooses between two lines, no collection resolves a contradiction, and a disposition naming no
recorded contradiction refuses (`DISPOSITION_UNBOUND`). **The disposition's `receipt_line_sha256`
constrains recovery** (§6, correction 3): once a disposition names receipt A, the launch is bound to A
in one shared status rule (`contradiction_status`, applied by the admission rule and by both hand-read
completions before any log read or completion mutation) — a hand-read completion offering another
line, even one decoding to the same document, is refused (`refused_receipt_binding`, exit 19 / 30); a
kept `COLLECTED` line other than A is `RECEIPT_SUBSTITUTED`; two dispositions naming different
receipts are `CONFLICTING_DISPOSITIONS` (a record refusal); and a collection reads nothing while a
disposition binds a launch whose completion is not whole. An **interrupted resolution** (the
disposition written, the completion not whole) is therefore repeatable only with A — with or without
the acknowledgement, writing no second disposition — and a **completed resolution** is whole; the two
are told apart by the completion's own evidence (the permission record, the receipt evidence, the
ledger row), never by the disposition alone. Unverifiable or mutually contradictory `COLLECTED`
records likewise name a conflict no tool picks between. The
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

## 6. Corrections after review (correction 1; the ADR stays PROPOSED)

The independent review of the pull request reproduced three findings through the real collector and
both public completion paths, on synthetic files and fakes; each is corrected in the same pull
request, and this section records what changed against the text above.

1. **An incomplete scan established uniqueness.** A pass that ended on the 16-page bound, the
   request budget or the event ceiling with one receipt-shaped line seen was `COLLECTED` — a valid
   line on page 1 and a contradictory line on page 17 completed a row and a subcell; a page crossing
   the event ceiling was scanned whole; the elapsed ceiling was checked only between passes, so slow
   requests ran a pass far past it. Now: `COLLECTED` and `RECEIPT_REJECTED` require a **complete scan**
   (end token observed, one poll interval, a re-read delivering nothing new); a line seen in a cut
   scan is `SCAN_INCOMPLETE` and is not kept; a second distinct line refuses at once; every bound is
   checked **before** each request and a page is scanned only up to the event ceiling; the in-flight
   request is documented as the one limit the collector cannot cut, and `elapsed_ms` records it.
2. **Unvalidated content was persisted before the completion refused it.** Receipt-prefixed
   malformed text, and a closed document with one unexpected field, were written into a `COLLECTED`
   record and refused only afterwards. Now the candidate is decoded and verified against the launch
   record's expectation **inside the collector**, before any record is written; a refused line leaves
   `RECEIPT_REJECTED` with the closed defect and a byte count only.
3. **Cached records were chosen by filename order, and a cached rejection had no recovery.** The
   first `COLLECTED` record in sorted order was reused; two contradicting records completed or
   refused depending on their names; a `COLLECTED` record carrying a malformed line was reused
   forever and the stream never read again. Now one closed parser and one admission rule (§2.5)
   serve both tools: every record about the launch is read and bound to the launch record and the
   destination, contradictions and unverifiable lines refuse whatever the order, and rejected or
   exhausted attempts never block a new collection.

Also corrected with them: a collection is refused until the launcher observed the task's terminal
state (§2.2); the tools print one closed summary line (outcome, counts, `scan_complete`); the two R-8
subcells stay BLOCKED, the rehearsal path stays CLOSED, and no permission or runtime authorization
moves.

4. **Correction 2 — a recorded contradiction was silently superseded.** After correction 1 a
   `CONTRADICTORY_RECEIPTS` record was history that never blocked: a later collection returning one
   valid line completed the row and the subcell, and a `COLLECTED` record placed beside the
   contradiction was reused in either filename order. Now the admission rule refuses while any
   contradiction record of the launch has no disposition (`CONTRADICTION_UNRESOLVED`); the only
   route past it is the explicit, evidence-bound disposition of §2.5 — a hand-read completion that
   acknowledges the record by digest, recorded as `kalpamani-collection-disposition/v1` beside the
   untouched contradiction record — and no automatic rule resolves anything. Exhausted and rejected
   attempts stay retryable as designed; the launch tool also refuses a collection for a row that is
   no longer provisional before any read.
5. **Correction 3 — the disposition did not constrain recovery.** A hand-read completion with
   receipt A and the acknowledgement, interrupted right after the disposition was written, could be
   retried with a different otherwise-valid receipt B — through hand completion and through a
   collection or cache reuse of B — the disposition naming A ignored. Now `contradiction_status`
   carries the one receipt every disposition of the launch bound it to, and one shared rule refuses
   before any read or mutation: another offered line (`refused_receipt_binding`), another kept line
   (`RECEIPT_SUBSTITUTED`), dispositions naming different receipts (`CONFLICTING_DISPOSITIONS`), and
   any collection while the bound completion is not whole. Recovery with A is repeatable at either
   interruption boundary (inside the disposition write: nothing persisted, the acknowledged completion
   runs again; after it: A finishes the completion, with or without the acknowledgement, writing no
   second disposition); the original contradiction record stays byte-identical; no write was moved and
   no new interruption window introduced.
