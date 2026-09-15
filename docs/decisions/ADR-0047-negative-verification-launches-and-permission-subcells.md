# ADR-0047 — Negative R-1 verification launches and the R-4 .. R-9 permission subcells

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0047 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **the completion of the verification cell matrix's executable
coverage — the two negative R-1 modes of a verification launch bound into the authorized
specification, the launcher, the launch record and the cell matrix; the expansion of ADR-0036 §3's R-4
.. R-9 rows into executable subcells with one operation, one principal, one target and one
expectation each, their evidence, budgets, interruption and cleanup rules and the tool that executes
them; the narrow amendments to ADR-0045's contracts and to ADR-0036 §3's cleanup wording it states
(§6); and the two mechanisms it names as required and not implemented (§5) — and nothing else**,
effective together with the offline code merged beside it. **Acceptance authorizes no execution**
(§7): no launch, no run, no probe, no permission subcell, no cleanup, no Terraform plan or apply, no
IAM change, no image; and **acceptance grants no permission** — every subcell exercises a permission
the accepted declarations already state, and the two mechanisms §5 names stay unimplemented until
their own decisions.

**The condition above has since been satisfied.** **PR #106 merged** — merged **2026-09-15T00:26:19Z**,
merge commit **`167f1564378cfb96759093b43fbde5443f6c56b6`**, ordered parents
**`5174dcf290b4837d38af8ce4a4b975c6557e482e`** then **`7eecbb61747f8516dafd0cd44261b816fe5312bd`** (the
approved head, after three independently reviewed correction cycles recorded in §8–§10), with a
**merge tree identical to the reviewed pull-request head tree** (`5fcccc891aa52b0004b35656c25a9df3e76cc850`).
ADR-0047 is therefore **ACCEPTED / IN FORCE** exactly as the clause above states — the completion of
the verification cell matrix's executable coverage, the narrow amendments of §6, and the two mechanisms
§5 named as required and not implemented — effective together with the offline code merged beside it,
and nothing else. While the pull request was open it was proposed and carried no authority — true then,
and not rewritten. **Acceptance authorized no launch, no negative launch, no permission subcell, no
cleanup, no run, no probe, no Terraform plan or apply and no IAM change**; every tool still refuses by
default and none has run against AWS. The mechanisms §5 names as required are decided by a later,
separately by ADR-0048 (accepted on the merge of PR #107): the task-side probe entry and the `ExecuteCommand` mechanism are
delivered there (with one further subcell status, `AWAITING_RECEIPT`, for a launched probe whose
receipt is not yet verified), and the deletion role's execution path is designed there and not opened.

**One sentence of §3.4 is corrected after acceptance, and the correction is recorded here rather than
by rewriting the sentence.** §3.4 says an unverified cleanup record "never makes a prerequisite object
available for a dependent subcell". The implementation and its tests hold the opposite direction: an
unverified cleanup **establishes no removal**, so the prerequisite object **stays available** — a
dependent subcell can still be prepared against it, and the next verified pass settles the object
again. The accurate sentence is "never makes a prerequisite object *unavailable*"; the original wording
below is kept as the record of what was reviewed and merged.

**Nothing was run to produce this decision.** No AWS call, no STS call, no S3 operation, no RunTask,
no container image built or pulled, no registry contacted, no credential retrieved, no provider
request, no private input inspected. Every result beside this text is a counting fake's, on synthetic
temporary files. **Mocked results are not AWS verification.**

---

## 1. Context

ADR-0046 (accepted on the merge of PR #105) enumerated ADR-0036 §3's cells and derived the matrix
from recorded evidence, and it deferred two things (its §4 and readiness §10.2): the negative R-1
cells — a verification launch with **no release written** and one with a release **naming another
task** — because the accepted launch tool always wrote the release after placement verification and
had no mode that withholds or mis-names it; and R-4 .. R-9, enumerated as owner-run rows with no
executable form. Readiness S8 and S9, and ADR-0036 §3's *"a cell that cannot be exercised is recorded
as not exercised, never as passed"*, leave the aggregate `INCOMPLETE` until both are decided and
executed. This ADR decides both, offline, and states exactly what remains blocked.

## 2. Decision — the negative R-1 launches

The four negative cells are `R1-ACQ-NO-RELEASE`, `R1-BLD-NO-RELEASE`, `R1-ACQ-RELEASE-MISMATCH`
and `R1-BLD-RELEASE-MISMATCH` — ADR-0036 §3 R-1's two *must be refused* clauses, per actor.

### 2.1 The release mode is part of the authorized specification

`ReleaseMode` (`NORMAL` | `WITHHELD` | `MISMATCHED`) is a field of the launch specification
(`kalpamani-launch-specification/v1`, §6.1) and therefore of the digest the owner's authorization
names: **the negative behaviour is authorized by the same act that authorizes the launch, and no
command-line argument can change it afterwards** — the launch tool applies the mode the reserved
specification carries, never one it was told. A negative mode is admissible only for
`kind = verification` (the specification's parser, the record's parser and the launcher each refuse
it otherwise); the production kind is always `NORMAL`, so ordinary production launches are
unchanged.

### 2.2 The launcher's one changed step

`launch_authorized_run(..., release_mode=)` runs the accepted sequence unchanged — the two identity
proofs, the create-only input, one `RunTask`, placement and image verification, the bounded
observation, the prescribed cleanup — and changes exactly step 1a: under `WITHHELD` no release is
written and the launcher proceeds to observe the task, which exits `REFUSED_NO_RELEASE` at its
barrier ceiling; under `MISMATCHED` the release written names `mismatched_task_arn(task)` — the
launched task's cluster and a task id derived from its own by SHA-256, asserted unequal — so the task
exits `REFUSED_RELEASE_MISMATCH`. **A mismatched release cannot accidentally be valid for the
launched task**: the release contract binds the exact task ARN, the derived id is never the real one,
and every other field is the launch's own so no other task can accept it either. The verified
placement is recorded in every mode; there is no retry, no relaunch and no second `RunTask` in any
mode; an interruption after the launch leaves the reservation and is recovered, never relaunched
(ADR-0045's rule, unchanged).

### 2.3 What passes a negative cell, and what never does

The launch record gains the mode the launcher applied and the exit code it **itself observed** at
the task's terminal state (§6.1). The cell runner's `--complete-cell` on a negative cell runs the
launch tool's `--complete-row` (the receipt verified against the launch record) and then writes one
`kalpamani-negative-launch-evidence/v1` record naming the verified receipt's outcome token, its
data-plane counts and whether the task reported itself released — the ledger row itself records
only `REFUSED`, and this record is what says *which* refusal.

A negative cell is `PASSED` only when **all** of the following hold: the ledger row is
`REFUSED` with `RECEIPT_VERIFIED` evidence; the reservation for the prepared identity carries the
prepared digest, this cell's actor, entry and **release mode**; the launch record binds to the
reservation under the shared rule (`bind_record`, mode included) and carries a verified placement;
the receipt's outcome is exactly the cell's expected refusal; the launcher's observed exit code is
that refusal's; the receipt measured its counts and every data-plane count is zero and it reported
no release; exactly one evidence record exists for the launch; and the bound evidence still applies
to the registration now in force (ADR-0045 §7 — otherwise `HISTORICAL`).

**Admissible evidence, stated for what it is.** A refused bootstrap receipt carries no bootstrap
evidence block (ADR-0044 §4), so its binding to the launch is the entry, the configuration digest
and the code commit it carries, the row completion the launch tool performed for this record, and the
launcher's own observation of the terminal exit code — two independent sources agreeing on the same
refusal. No stronger claim is made.

`VERIFIED` on a negative cell — the task accepted a release it must have refused — is `FAILED`
(an unexpected success); another refusal, a halt, a misplacement, a released task or an observed
data-plane operation is `FAILED`; missing, malformed, conflicting or substituted evidence, an
unobserved terminal state or a contradicting exit code is `UNBOUND`; a timeout leaves the row
provisional. **A refused negative launch is never a successful bootstrap, never successful
processing and never a buildable acquisition**: its row is `REFUSED`, its identity is a `verify-`
identity no build workload can select, and the positive bootstrap cell is `UNBOUND` if its prepared
specification carries a negative mode.

### 2.4 Recovering the evidence of a completed row

The row's completion (`--complete-row`, a ledger write) and the evidence write are two durable
writes; an interruption between them leaves the row `REFUSED` / `RECEIPT_VERIFIED` and the cell
`UNBOUND` with no evidence record, and completion cannot be repeated on a completed row. The cell
runner's `--recover-negative-evidence <cell> --launch-record --receipt-lines` records the missing
evidence **offline**: the reservation, the launch record and the receipt are re-verified through the
launch tool's own reader (the shared reservation-to-record rule and the receipt-to-record rule,
unchanged), the row must already be complete for the prepared identity, the record must be this
cell's prepared launch under its release mode, and the receipt's outcome must be the terminal state
the launcher itself observed — two pieces of evidence for one launch that disagree are a
contradiction and refuse. The evidence document is recomputed from the verified receipt; an existing
record equal to it (`recorded_at` aside) means nothing is written and the mode succeeds again; one
that differs refuses (`EXIT_REFUSED_EVIDENCE_CONFLICT`) and is never overwritten, reconciled away or
superseded. **No launch, no new identity, no ledger change, no binding check weakened.**

## 3. Decision — the R-4 .. R-9 permission subcells

### 3.1 Expansion, traced

Each ADR-0036 §3 row of R-4 .. R-9 is expanded into subcells (`permission_cells.SUBCELLS`, 98 in
all), each carrying the exact phrase of the row it comes from, and each stating: the **principal**
(one of ten, each reached through exactly one workstation profile or through none), the
**operation** (one of thirteen closed operations), the **target class** (one of twenty-four, resolved
at execution from the environment binding, the launch-inputs registration and a private targets
document), the **expectation** (`ALLOWED` or `DENIED`), the **layer** that can decide it, the
subcells whose created object it needs, whether it may create an object, and — when blocked — its
exact dependency.

| Cell | Subcells | Executable now (L3, human principal) | Evidenced by R-1 | Blocked |
|---|---|---|---|---|
| R-4 acquisition (`R4-ACQUISITION`) | 34 | 17 (the acquisition human profile) | — | 17 (the acquisition task role) |
| R-5 build (`R5-BUILD`) | 30 | 15 (the build human profile) | — | 15 (the build task role) |
| R-6 launchers (`R6-LAUNCHERS`) | 18 | 10 (the two launcher profiles: five refusals each) | 6 (own revision, `DescribeTasks`, `DescribeNetworkInterfaces` — the R-1 bootstrap launch performs and records exactly these) | 2 (`ExecuteCommand`: no running task of the actor to execute into) |
| R-7 qualification (`R7-QUALIFICATION`) | 12 | 12 (the two qualification profiles) | — | — |
| R-8 deletion (`R8-DELETION`) | 2 | — | — | 2 (no execution path) |
| R-9 foundation task role (`R9-FOUNDATION-TASK`) | 2 | 2 (the two launcher profiles) | — | — |

**Identity-policy simulation is not runtime behaviour.** L2 (`SimulatePrincipalPolicy`) is not
executed by this tooling and could never pass a subcell; a subcell is decided at L3 by one real
request or not at all. **A human role never stands in for a task role**: the task-role subcells
exist as their own subcells, under their own principal, and are blocked (§5) — the human twin of the
same operation is evidence for the human role alone. **A request against a target that does not exist
is not a permission test**: R-6's `ExecuteCommand` subcells are blocked (§5) because no task of ours
runs outside an authorized R-1 launch, and a refusal against a task ARN that names nothing would
prove nothing about the policy. Every launching request carries the registered placement of its
actor (FARGATE, the subnet, the security groups, the public-IP setting, the pinned platform version —
the same request shape the accepted launcher sends), because a request that fails on its parameters
before any policy is evaluated is not a permission test either.

### 3.2 One operation, one decision, one bounded reaction

**Preparation states what will be executed.** `--prepare-subcell <id>` admits the bindings, the
registration and the private targets document, resolves the subcell's exact target for one session
stamp, binds every prerequisite object the operation reads to the exact record that created it, and
writes a **statement** (`kalpamani-permission-statement/v1`: the subcell, the principal, the
operation, the target class, the SHA-256 of the resolved target — bucket and key, name or ARN,
cluster, definition, override role and placement — the stamp, the binding, the SHA-256 of the
targets document, and the bound prerequisite records by digest). Its digest is what the owner's
**authorization** names (`kalpamani-permission-authorization/v1`: one subcell, one statement digest,
issued and expiring within 24 hours). No identity proof and no client: preparation performs
nothing.

The tool (`scripts/production_permission_cells.py`) executes **one subcell per authorized
invocation**, in this order: automation refused; the flag; the subcell exists and is an L3 subcell;
`AWS_PROFILE` pinned to the principal's own profile; the principal's identity proven (a production
human or launcher through the accepted human bootstrap against its private binding — the launch
tool's own proof; a qualification actor through the accepted ADR-0021 gate; the control principal
through the foundation gate); the environment binding, the launch-inputs registration, the private
targets document and, for the production secret, the acquisition configuration admitted; the binding
digests computed; the authorization admitted for this subcell and valid now; the statement it names
found under the current binding and **recomputed** from its own stamp against what is admitted now —
a changed target, targets document, declaration, registration or prerequisite is not what the owner
authorized and refuses; **the authorization consumed durably** (one exclusive file beside the
canonical ledger, named by the authorization's digest and carrying the consumption record —
`kalpamani-permission-consumption/v1`: the subcell, the statement digest, the authorization digest,
the instant — never under the records directory, never removed) **before anything is attempted**; the **attempt record written before the operation**,
naming the authorization, the statement and the exact bucket and key it may create; the client built
**only now** (one transport attempt, finite timeouts); the operation; the record, naming the attempt
it answers. A second execution under the same authorization — repeated, after an interruption at any
later point, from another records directory — finds the consumption and refuses; recovery of an
interrupted attempt is the cleanup's, never a re-execution, and preserves the consumption. One
execution needs one new preparation and one new authorization.

The answer is classified through the accepted R-3 classifier and decided: `ALLOWED` matches only
the operation's success class (`200`, or `204` for a delete); `DENIED` matches an access denial
whichever policy refused (which policy refused is R-3's question, not these cells'); a timeout, a
network failure, an authentication failure, a missing bucket, a throttle or an ambiguous answer
decides nothing — the record reads `UNDECIDED`, the subcell stays unexercised, and **nothing is
retried**.

**Unexpected success is a resource, not only an inversion.** A `DENIED` launch whose answer
returned tasks is stopped **at once** by the same principal — one `StopTask` per returned task, every
returned task accounted for up to a bound of four, whatever failure entries came beside them — and
the record carries every task id and which stops were acknowledged; **an acknowledged stop is not a
termination**, which only a later `DescribeTasks` in the cleanup confirms. A `DENIED` write that
succeeded is recorded with the exact bucket and key it created, for the cleanup.

**An open answer is a possibly committed write or launch.** A timeout, a network failure, a throttle
or an ambiguous status after a creating write leaves the object *possibly created*, and after a
launch leaves a task *possibly started*; both are recorded as such (the result stays `UNDECIDED`,
never repeated) and the cleanup settles them — the object by the key the attempt named, the launch
by listing the cluster for the `startedBy` tag every launching request of the session carries
(`kalpamani-permission-<stamp>`). **No `RunTask` is ever retried.** Budget: **one operation plus one
`StopTask` per returned task** per subcell, **two per object** and **one `ListTasks` plus one
`DescribeTasks` and at most one `StopTask` per task** per launching attempt in the cleanup.

### 3.3 Targets

Every synthetic S3 key is a real key shape of its namespace, built by the accepted key builders,
carrying the session stamp in its run identity (`verification-<stamp>`) and the digest of a fixed
64-byte synthetic marker as its content address — so it lies exactly where the policy statement under
test applies (`bronze/sharadar/<dataset>/production/`, `bronze/_production_claims/`,
`bronze/sharadar/_indexes/`, `silver/`, `gold/`, `manifests/`, `qualification/`, and the CONTROL
bucket) and nowhere a production object could be. **A subcell that reads or deletes an object a
prerequisite subcell created takes the exact bucket and key that prerequisite's bound `MATCHED`
record established** — never a key derived from its own stamp — and is prepared and executed only
while that record exists under the current binding and no later cleanup has confirmed its object
removed; the statement and the record both name the prerequisite record by digest, and the matrix
holds the dependent to exactly that record. Launch targets are the registered
verification revision (own) or deterministic derivations of it (the next revision number, a
`-verification-other` family, a `-verification-other` cluster) that the exact-resource policies cannot
name; the other actor's task role and the foundation task role are the two override targets. Three
values no accepted binding carries — the foundation task role ARN, the qualification secret ARN and
the CONTROL bucket name — come from a private `kalpamani-permission-targets/v1` document under the
owner's root, named by `KALPAMANI_PRODUCTION_PERMISSION_TARGETS_FILE`, never from the command line and
never rendered.

### 3.4 Records, binding and derivation

Six closed contracts (§6.2). Every record, attempt, statement and cleanup binds to the environment
binding's digest, the digest over the tracked production declarations (`production_*.tf` and
`storage.tf`, each by name and bytes), the digest of the launch-inputs record the targets were
resolved from, **the digest of the owner's private targets document**, the partition and the region
— one `PermissionBinding`, computed only when every one of those inputs is present now, so a missing
input holds every recorded result `UNBOUND` and a changed one makes it `HISTORICAL`; nothing
preserves a `PASSED` silently. **Attempts, records and cleanup entries are joined by identity, never
by their order in time**: a record names the digest of the attempt it answers, a cleanup entry names
the attempt whose exact object (bucket and key) or launch (`startedBy` tag and tasks) it settled, and
a later result never answers an earlier attempt.

**One validator binds a result, and it is the same everywhere** (`permission_cells.bind_result`,
used by the tool's prerequisite admission, by the matrix derivation and by the cleanup's
already-settled rule): a result binds only through its whole chain — the current context (the
binding and the inputs a target is resolved from: the environment binding, the registration, the
targets document and, when named, the acquisition configuration); the record under the current
binding; the attempt the record names by digest, for the same subcell, principal, stamp, start,
authorization and binding; the statement the attempt names by digest, for the same subcell,
principal, operation, target class, stamp, binding, targets document and prerequisites; every
prerequisite the statement names as the exact bound record it was prepared against, itself bound
through its own chain, established before this one, its object created; the exact target
**recomputed now** from the context and equal to the statement's digest, with the attempt's and the
record's object the target's; and the durable consumption of the authorization, naming this subcell
and statement, consumed no later than the attempt started. **A digest-shaped field alone binds
nothing**: a record whose attempt, statement or consumption is missing, substituted or contradicting
is `UNBOUND` with the defect named, and a cleanup settles a bound result only by naming its attempt
and its exact object or launch **and only when it is admissible** — the one rule every consumer of
cleanup evidence applies (`PermissionCleanup.admissible_for`, used by the matrix derivation, by the
tool's prerequisite availability and by its cleanup suppression alike): the same binding, recorded
no earlier than the record, **and the control principal's identity verified**. **A cleanup record
whose identity is not verified settles nothing**: it is preserved and reported (the reason names it),
but it never confirms an object removed or a launch terminated, never makes a prerequisite object
available for a dependent subcell [*corrected after acceptance: an unverified cleanup establishes no
removal, so the prerequisite object stays available — it never makes it* unavailable; *see the note
under the status*], and never suppresses the next cleanup pass — a verified pass
settles the same object or launch again. The cell
runner derives each subcell from the records: a bound `MATCHED` result under the current binding whose
identity was verified and whose every open object or launch is settled is `PASSED`; **an inversion under the current
binding never disappears** when a later matched record arrives (a corrected declaration changes the
binding, and then the old records are `HISTORICAL`); an attempt no record names is `INTERRUPTED` —
never re-executed automatically, its object settled by the cleanup and its authorization still
consumed; an undecided answer is `UNDECIDED` and stays so after its possibly committed write is
settled — **the original inconclusive result is preserved, and the cleanup changes no result**; a
record for another binding is `HISTORICAL`; malformed or unreadable evidence, an unverified identity
or a prerequisite that is not the exact bound record is `UNBOUND`; an object created or possibly
created, or a task started or possibly started, not yet settled by a later cleanup naming the attempt
is `CLEANUP_UNRESOLVED` — a `FAILED` launch reports whether its tasks' termination was confirmed; a
blocked subcell is `BLOCKED` with its dependency; a launcher positive is `AWAITING_R1` until its
bootstrap cell passes; a subcell with no attempt and no record is `UNEXECUTED`. A cell is `PASSED` only when **every** subcell is; otherwise the first status by
precedence (`FAILED`, `UNBOUND`, `BLOCKED`, `INTERRUPTED`, `HISTORICAL`, `CLEANUP_UNRESOLVED`,
`UNDECIDED`, `AWAITING_R1`, `UNEXECUTED`) decides, and the matrix prints every subcell beneath its
cell. **Empty, partial, simulated or blocked coverage never passes**, and the
aggregate stays `INCOMPLETE` while R-4, R-5 and R-8 are blocked.

### 3.5 Cleanup

`--cleanup` runs under the control principal (`kalpamani-foundation`, the R-3 control principal,
whose identity policy already grants `s3:DeleteObject`) and settles, by exact identity, every object
a record created or possibly created and every object an unanswered attempt named — confirming each
absent with one `HeadObject` held to `404` — and every launch a record started or possibly started:
**bounded discovery** by the attempt's `startedBy` tag — `ListTasks` with `startedBy` as **the only
filter** (the documented `ListTasks` contract: when `startedBy` is used it is the sole filter, so no
`desiredStatus`, `family`, `serviceName`, `launchType` or `containerInstance` accompanies it), the
cluster, `maxResults` and, when a page returned one, `nextToken`, following the token for at most
three pages — then per known or discovered task one `DescribeTasks` held to `STOPPED` and, otherwise,
one `StopTask` with the task recorded as residue. The request shape is held at the real adapter's
intercepted transport, not by a fake's answer: **a fake HTTP 200 alone does not validate request
compatibility.** **A launch is settled only by termination evidence for every task it is known to
have started; discovery settles nothing by itself.** A discovery that found nothing (delayed
visibility looks exactly like absence), a discovery that did not answer (`failed`) and a discovery
that reached its page bound with a token remaining (`incomplete`) each leave the launch unresolved
residue, named by its tag and the reason; every task known before the discovery is preserved and
described; a task found on a later pass is settled then. **Discovery exhaustion is never proof of
absence, and no `RunTask` is ever sent by the cleanup.** **Stopped-task visibility is a stated
limitation**: without a second filter the listing returns what ECS currently returns for the tag —
running tasks and recently stopped ones — so a task that stopped before discovery and has aged out
of the listing is not discoverable by this mechanism; such a launch stays unresolved, and the
mechanism that would settle it (a status-filtered listing under a different, documented request, or
an owner attestation) is outside this decision (§5). An ambiguous launch whose task is never
discovered stays `CLEANUP_UNRESOLVED`; an owner mechanism to attest such a launch settled is not
implemented and not decided here (§5). **A cleanup pass settles nothing unless its record attests
the control principal's verified identity** (§3.4): an `identity_verified=false` pass is reported
and settles no object and no launch. **An object the R-4 or
R-5 positive writes left for a prepared, not yet recorded dependent subcell is deferred, not removed**
— kept until that dependent check has run, then settled by the next pass. A key not confirmed absent,
a task not confirmed stopped, an undiscovered, failed or incomplete discovery, a refused delete or an
exhausted budget (64 objects, 8 launches) is residue, recorded by its synthetic key, task id or tag,
and every subcell that created or started it stays `CLEANUP_UNRESOLVED`. **Cleanup restores the
buckets and the cluster; it never changes what a subcell established, and it never launches.**

## 4. Traceability

Every subcell's `trace` is the ADR-0036 §3 phrase it implements, and the governance test holds every
"must succeed" and "must be refused" clause of R-4 .. R-9 to at least one subcell. R-1's two negative
clauses are the two negative cells per actor; R-6's three positive operations are evidenced by the
R-1 bootstrap launch, which performs and records exactly them, rather than by a second task started to
prove them.

## 5. Required and not implemented

| Mechanism | Needed for | What it would be | Status |
|---|---|---|---|
| a **task-side permission probe entry** | the 32 task-role subcells of R-4 and R-5 | one closed verification entry in the image (a third verification entry beside ADR-0045's two) that selects exactly one catalogued subcell from its compiled configuration, issues that one operation under the task role after the release barrier, and prints a receipt naming the subcell, the observed class and the outcome — the receipt then completes the subcell the way a refused receipt completes a negative cell | **not implemented; not authorized by this ADR** — a task-definition family, a compiled-configuration field and a launcher resource, each a later decision |
| a **running task of the actor** | the 2 R-6 `ExecuteCommand` subcells | a task of ours runs only during an authorized R-1 launch; executing into it during that launch (and recording the refusal) is a later decision of the verification entries | **not implemented; not authorized by this ADR** |
| the **control principal's task discovery and stop** (`ecs:ListTasks`, `ecs:DescribeTasks`, `ecs:StopTask` on the governed cluster) | the cleanup's settlement of launches (§3.5) | the R-3 control principal's identity policy grants the S3 operations the cleanup uses; whether it holds these ECS actions is not established here and is not granted by this ADR — until it does, the cleanup records a `failed` discovery as residue | **recorded as deferred (owner inputs D.2); not granted** |
| an **owner attestation for an undiscovered ambiguous launch** | an ambiguous launch whose task is never discovered (§3.5) | a mechanism that would let the owner record, on evidence outside the cleanup, that no task ran — none is designed; the subcell stays `CLEANUP_UNRESOLVED` | **not implemented; not decided here** |
| **discovery of a task that stopped before discovery and aged out of the `startedBy` listing** | a launch whose task stopped early (§3.5) | `ListTasks` by `startedBy` returns what ECS currently lists for the tag, and a status filter cannot accompany it; a documented request that lists stopped tasks by another filter, or an attestation, would be a later decision — until then the launch stays `CLEANUP_UNRESOLVED` | **limitation recorded; not implemented; not decided here** |
| an **execution path for the deletion role** | the 2 R-8 subcells | a deletion task definition, or a runbook step under a separately authorized principal (ADR-0007 holds that no human may assume the role and no deletion task definition exists) | **not implemented; the runbook step stays separately authorized** |
| the **owner-held targets** | R-4's refused secret, R-4/R-5's refused bucket, R-9 | the private targets document (§3.3) | a value the owner supplies before cloud verification (owner inputs D.1) |

No permission is granted by this ADR: D-14 (analyzer), V-16 (`ecs:DescribeTaskDefinition`),
`logs:GetLogEvents` (the receipt collector) and G-14 stay recorded and not granted.

*Since acceptance (ADR-0048, accepted on the merge of PR #107 — not this ADR's decision): the task-side permission probe entry
and the running task the `ExecuteCommand` subcells needed are delivered as the permission-probe entry
and the held probe task; the deletion role's execution path is designed as a rehearsal path and stays a
separate decision; the control principal's ECS actions, the owner attestation and the stopped-task
listing stay recorded as above. The table is history and is not rewritten.*

## 6. Amendments stated

### 6.1 ADR-0045's contracts, narrowly

- `kalpamani-launch-specification/v1` gains `release_mode` (`NORMAL` | `WITHHELD` | `MISMATCHED`;
  `NORMAL` for every production launch). The digest covers it. No reservation had been written before
  this change; the identifier is unchanged.
- `kalpamani-launch-record/v1` gains `release_mode` and `observed_exit_code` (the launcher's own
  terminal observation, `None` when it observed none). No record had been written before this change.
- `bind_record` (ADR-0046's shared rule) gains `MODE_MISMATCH`: a record whose mode is not the
  specification's does not bind.
- The launch tool (`scripts/production_launch.py`) gains `--release-mode withheld|mismatched`,
  admitted for a verification launch's preparation or execution only; the mode applied at execution is the reserved specification's.

### 6.2 Contracts added

| Contract | Where |
|---|---|
| `kalpamani-negative-launch-evidence/v1` | `verification_cells.py`: `NegativeLaunchEvidence`, `parse_negative_launch_evidence` |
| `kalpamani-permission-targets/v1` | `permission_cells.py`: `PermissionTargets`, `parse_permission_targets` (private, never rendered) |
| `kalpamani-permission-statement/v1`, `kalpamani-permission-authorization/v1`, `kalpamani-permission-consumption/v1` | `permission_cells.py`: `PermissionStatement`, `PermissionAuthorization`, `PermissionConsumption` and their parsers; the consumption beside the ledger is `LaunchStore.consume`, read back by `LaunchStore.consumptions`; the one validator is `bind_result` over a `PermissionContext` |
| `kalpamani-permission-attempt/v1`, `kalpamani-permission-record/v1`, `kalpamani-permission-cleanup/v1` | `permission_cells.py`: `PermissionAttempt` (the authorization, the statement, the exact bucket and key), `PermissionRecord` (the attempt it answers, the bound prerequisites, the created bucket and key, `possibly_created`, every started task, the acknowledged stops, the `startedBy` tag, `possibly_started`), `PermissionCleanup` (objects and launches by attempt — each launch with its listings, `discovery_failed`, `discovery_incomplete`, the tasks known, stopped and left — `deferred`, residue) and their parsers |

### 6.3 ADR-0036 §3, one wording

ADR-0036 R-4 says the synthetic object is *"deleted by the deletion role afterwards under its own
runbook step"*. The deletion role has no execution path (§5), so the synthetic objects the R-4 and R-5
positive subcells create are removed by the **control principal** under the cleanup mode of §3.5, the
same principal and the same confirmation R-3's cleanup uses; the R-8 rehearsal against synthetic
objects stays the deletion role's own, blocked. ADR-0036's text is not rewritten; this ADR states the
reading.

## 7. Effectiveness and execution gates

Acceptance of this ADR authorizes **no** launch, **no** negative launch, **no** permission subcell,
**no** cleanup, **no** run, **no** probe, **no** analysis, **no** Terraform plan or apply, **no** image
build or publication, **no** IAM or bucket-policy change, and grants **no** permission. Each tool
refuses by default; each authorized branch is opened by its own flag under its own written
authorization — a permission subcell by an authorization naming its prepared statement, consumed by
its one execution; none has run against AWS. **G2 stays OPEN, CONTROL stays DEFERRED, Phase 3 stays NOT
COMPLETE, live trading stays HARD-DISABLED.**

## 8. Corrections on review (PR #106, correction 1)

Five source-review findings were reproduced on synthetic inputs against the reviewed head and
corrected in the same pull request; the text above states the corrected design. (1) Authorization:
no per-subcell authorization existed and nothing was consumed, so one flag executed repeatedly and a
changed targets document changed nothing — now a prepared statement, an authorization naming it,
recomputation at execution and durable consumption beside the ledger (§3.2). (2) Prerequisite
identity: a dependent read resolved a key from its own stamp, prerequisites were checked only at
derivation, and the cleanup removed objects a prepared dependent still needed — now the exact bound
record's bucket and key, enforced at preparation and execution, deferred by the cleanup (§3.3, §3.5).
(3) Ambiguous writes: a timed-out write recorded no key and was never cleaned, and attempts were
joined to results by order — now possibly committed writes and launches are recorded and settled by
attempt identity, a cleanup recorded before a record cannot settle it, residue and the original
result are preserved (§3.2, §3.4). (4) ECS accounting: the adapter dropped task ARNs when failure
entries came beside them, stopped only the first task, claimed *stopped* from an acknowledgement,
sent no placement and no tag, and `ExecuteCommand` addressed a task that does not exist — now every
returned task is accounted for and stopped, termination is confirmed only by `DescribeTasks` in the
cleanup, ambiguous launches are listed by tag and never retried, the request carries the registered
placement and the tag, and the two `ExecuteCommand` subcells are blocked (§3.1, §3.2, §5).
(5) Negative-evidence recovery: an interruption between `--complete-row` and the evidence write left
the cell `UNBOUND` with no path back — now `--recover-negative-evidence` (§2.4). The counts of §3.1
moved from 58 / 6 / 34 to **56 / 6 / 36**; the task-role and deletion-role cases are retained as
blocked.

## 9. Corrections on review (PR #106, correction 2)

Two further findings were reproduced on synthetic files through the real parsers, the real runner
and the real cleanup engine against the corrected head of correction 1, and corrected. (1) A result
passed when no unmatched attempt existed: twelve records alone, with digest-shaped attempt and
authorization fields naming nothing, passed R-7 through the public runner, and the binding carried no
targets digest, so a changed or missing targets document preserved `PASSED`. Now the binding covers
the targets document, the runner holds every result to a context built the tool's own way (a missing
input is no context, `UNBOUND`), and one validator binds a result only through its attempt,
statement, exact target, bound prerequisites and consumed authorization (§3.4) — the test that
supplied only records and expected R-7 `PASSED` is replaced by one that builds every chain through
the tool and then withholds, substitutes and contradicts each component through the public runner.
(2) An ambiguous launch with no known task was settled by one `ListTasks` answering `200` with an
empty list. Now discovery is bounded and explicit (two desired statuses, three pages each, residue for
`undiscovered`, `failed` and `incomplete`), every known task is preserved and described, a launch is
settled only by termination evidence, exhaustion is never proof of absence, and no `RunTask` is ever
sent (§3.5); the control principal's ECS actions are recorded as deferred, not granted (§5). Counts
unchanged at **56 / 6 / 36**; the task-role, deletion-role and `ExecuteCommand` cases stay blocked.

## 10. Corrections on review (PR #106, correction 3)

Two further findings were reproduced on synthetic files against the corrected head of correction 2
and corrected. (1) **Invalid ECS discovery requests**: the adapter's `ListTasks` combined
`startedBy` with `desiredStatus`, and the documented contract makes `startedBy` the only filter when
it is used — a request the fake accepted with `200` and the service would refuse. Now discovery
lists by `startedBy` alone (cluster, `startedBy`, `maxResults`, `nextToken` when following a token),
for at most three pages; the same attribution, the same page bound and the same residue
(`undiscovered`, `failed`, `incomplete`); no filter, status or permission added; and the request
shape is asserted at the real adapter's intercepted transport for every listing sent, with no
`RunTask` — **a fake HTTP 200 alone does not validate request compatibility** (§3.5). The
consequence is stated rather than worked around: a task that stopped before discovery and aged out
of the listing is not discoverable by this mechanism, the launch stays unresolved, and the mechanism
that would settle it is recorded in §5 as a limitation, not implemented and not decided. (2)
**Cleanup identity**: a complete, valid chain whose cleanup differed only by `identity_verified =
false` settled its object and its launch, in the matrix, in the tool's prerequisite availability and
in its cleanup suppression. Now one admissibility rule (`PermissionCleanup.admissible_for`: same
binding, no earlier than the record, identity verified) is applied wherever cleanup evidence is
consumed; an unverified pass is preserved for reporting and settles nothing, the reason names it, and
a verified pass settles the same object or launch again (§3.4, §3.5) — held by object and task cases
through the public runner beside their verified controls. Counts unchanged at **56 / 6 / 36**; the
task-role, deletion-role and `ExecuteCommand` cases stay blocked; ADR-0047 stays PROPOSED.
