# Runbook — Vendor Data Deletion on Licence Termination

## STATUS: **DESIGN ONLY — NOT EXECUTED, AND NOT EXECUTABLE**

This runbook describes a procedure for a situation that **does not exist**. No provider has been
selected, no subscription has been purchased, no credential has been issued, and no vendor data
has been retrieved. **There is nothing to delete.**

The AWS foundation itself was provisioned on 2026-08-27
([aws-foundation-status.md](../operations/aws-foundation-status.md)), so the buckets this
procedure targets now exist — and are **empty**. That changes the precondition, not the verdict:
an empty licensed bucket is still nothing to delete.

It is written **before** the data exists, on purpose. A deletion obligation with a 30-day clock
that can start without notice is not something to design under time pressure, and a procedure
that has never been read is not a procedure.

> **Nothing in this document authorizes anything.** It does not authorize a purchase, a
> credential, an ingestion, an AWS resource, a `terraform apply`, or its own execution. Gates
> **G1 OPEN · G2 OPEN · G3 CLOSED (Sharadar personal use, ADR-0008) · G4 OPEN · G5 OPEN · G6 OPEN · G7 OPEN**. ADR-0005 **remains PROPOSED**, and live trading remains **HARD-DISABLED**.

**Authority:** [ADR-0007](../decisions/ADR-0007-cloud-first-research-data-plane.md) §3–§4 ·
[ADR-0005](../decisions/ADR-0005-point-in-time-data-architecture.md) §13–§14 ·
[provider-licensing-decision-packet.md](../phase3/provider-licensing-decision-packet.md) §3.C

---

## 1. What obligation this satisfies

The leading provider candidate's §10 requires the subscriber, on expiry or termination, to delete
within **30 days**:

- *"all copies of the Services Data (including downloads, bulk files, caches, and extracts)"*
  (`PSR-SHD-083`);
- *"all data sets that contain, substantially copy, or could reproduce the Services Data or
  Sharadar tables"* (`PSR-SHD-083`);

from **"all computer systems you own or operate"**, with a carve-out permitting retention of
*"research outputs, backtest results, models, summary statistics, trade logs, and similar derived
works that do not contain and cannot reproduce the Services Data"* (`PSR-SHD-084`).

Three properties of that clause shape everything below.

| Property | Consequence for this runbook |
|---|---|
| Termination may be **immediate and without prior notice** (`PSR-SHD-085`) | The clock can start unannounced. The procedure must be runnable on the day it is discovered, not prepared then. |
| The scope is **all systems you own or operate** | AWS **and** the laptop cache **and** any container layer **and** any log that captured a payload. Cloud-first narrows the surface; it does not reduce it to one place. |
| The test is **reconstructability**, not derivedness | You cannot reason your way to "this factor panel is derived enough". [ADR-0007 §3](../decisions/ADR-0007-cloud-first-research-data-plane.md) resolves this in advance by *location*: everything reconstructable already lives in the licensed bucket. |

**The architecture is what makes this procedure short.** Because the two-bucket boundary is
maintained continuously, deletion is *"destroy these prefixes and prove it"* rather than
*"search every artifact ever produced and decide about each one"*. If the boundary was not
maintained, this runbook does not work, and no amount of care on the day recovers that.

---

## 2. Preconditions before this runbook may ever be run

| # | Precondition |
|---|---|
| 1 | The subscription has actually expired or been terminated, evidenced in writing. |
| 2 | The owner has authorized execution. This is a destructive, irreversible operation. |
| 3 | The date the 30-day clock started is recorded. |
| 4 | The licensed/control boundary has been maintained ([§7](#7-pre-flight-verification-that-the-boundary-held)). If it has not, that is established **before** deleting anything, because a misfiled artifact in the control bucket will otherwise survive. |
| 5 | A deletion task or operator path has been **separately authorized and created**, and an identity has been granted `iam:PassRole` for the deletion role. **Neither exists today**, so this runbook is currently unexecutable by construction — see below. |

### Which identity performs which step

**Licensed-S3 destruction and verification — steps 3–9 — run under the dedicated
`licensed_data_deletion` role. The separately authorized operator / orchestration path performs
the surrounding shutdown, credential, compute, container, log, local-copy and receipt steps.**

The split follows directly from the role's scope. `licensed_data_deletion` holds *only*
licensed-bucket S3 inspection and deletion authority, so it is incapable of stopping a schedule,
revoking a provider credential, deleting a container image, touching a log group, clearing a
laptop, or writing a receipt to the control bucket. Those are not oversights in the role — they
are what keeps it narrow, and they mean the role cannot be the whole procedure.

| Steps | Identity | Why |
|---|---|---|
| **1** stop ingestion · **2** revoke and destroy the provider credential | **operator path** | ECS/EventBridge and Secrets Manager / SSM — outside S3 entirely |
| **3** enumerate the licensed surface · **4** abort incomplete multipart uploads · **5** delete Bronze · **6** delete Silver · **7** delete Gold, qualification and reconstructable derivatives · **8** prove the bucket empty including versions and delete markers · **9** inspect versioning, replication and lifecycle state | **`licensed_data_deletion` role** | exactly the authority it holds, and nothing else holds it |
| **10** verify compute retained nothing · **11** inspect/delete contaminated container images, if ever required · **12** inspect/delete contaminated logs, if ever required · **13** clear laptop and local copies · **14** write the deletion receipt to CONTROL · **15** verify permitted retained artifacts | **operator path** | ECS, EBS/EFS, ECR, CloudWatch Logs, local filesystems and the control bucket — none reachable by the deletion role |

The operator path **may invoke the deletion role for steps 3–9** once a future specific workflow
and a scoped `iam:PassRole` authorization exist. Neither exists today.

| | `licensed_data_deletion` |
|---|---|
| **can** | list the licensed bucket and its versions; read its versioning, replication and lifecycle configuration; delete objects, delete object versions, abort and list multipart uploads |
| **cannot** | read licensed object contents (`GetObject`), write anything (`PutObject`), touch the **control** bucket at all, or read any provider secret |

That shape is deliberate. Deletion does not require reading the data, so it does not get to; the
object counts and sizes for the receipt come from listing, not from contents. And because the role
has no access to the control bucket, it cannot destroy the manifests, lineage or deletion receipts
that must survive — **the evidence that a deletion happened is outside the reach of the identity
performing it.** The receipt in step 14 is therefore written by the operator path, never by the
deletion role.

The routine research task role holds **no** `s3:DeleteObject` and appears nowhere in this
procedure. The licensed bucket has no versioning, no replication and no backup, so a delete cannot
be undone; giving standing destructive authority to the role that also runs daily ingestion would
let an ordinary bug in research code destroy unrecoverable history.

> **The deletion role is committed but currently unusable, and that is intentional.** No ECS task
> definition exists, no deletion task or workflow exists, no image exists, and no identity has
> `iam:PassRole` for it — so nothing can launch anything that runs as this role. Creating that
> task and granting a scoped `PassRole` is a **separate authorization that has not been given**.
> The role is defined in advance for the same reason this runbook is written in advance: so the
> destructive path is reviewable before it is ever needed, not improvised inside a 30-day window.

**This procedure is irreversible by design.** The licensed bucket has no versioning, no
replication and no backup precisely so that deletion is complete — which also means there is no
undo. That is the intended trade, and it is why step 2 exists.

---

## 3. Procedure

Every step records evidence. A step that "was done" without evidence did not happen.

### Step 1 — Stop ingestion  *(operator path)*

1. Disable every scheduled or triggered ingestion task.
2. Confirm no ECS task, Batch job or local process is running against the provider.
3. Confirm no queued or retrying job will start one.
4. Record: the disabled schedules, and a listing showing zero running tasks.

*Deleting while a writer is running produces a bucket that is empty and then is not.*

### Step 2 — Revoke and destroy the provider credential  *(operator path)*

1. Revoke or rotate the API key **at the provider** first, so a missed process cannot fetch more.
2. Delete the secret from Secrets Manager / SSM Parameter Store, including any prior versions —
   a secret's version history is a copy of the credential.
3. Confirm no `.env`, shell profile, task definition, CI variable or local file still holds it.
4. Record: revocation confirmation, and the deleted secret ARNs **with the account id redacted**.

*The credential goes before the data, because a live key plus a retrying job re-creates what
step 3 deletes.*

### Step 3 — Enumerate the licensed surface before deleting it  *(`licensed_data_deletion` role)*

1. Identify the licensed-data bucket by name from Terraform outputs or the console.
2. List its prefixes: `bronze/`, `silver/`, `gold/`, `qualification/`, and anything else present —
   **an unexpected prefix is a finding**, and is deleted, not skipped.
3. Record object counts and total bytes per prefix. This is the "before" side of the receipt.

### Step 4 — Abort every incomplete multipart upload  *(`licensed_data_deletion` role)*

Do this **before** the object deletion, not after.

1. `ListMultipartUploads` on the licensed bucket.
2. Abort every upload returned.
3. Re-list and confirm the result is empty.
4. Record both listings.

*Parts of an incomplete multipart upload are stored and billed but do **not** appear in an object
listing. A delete-everything-you-can-list loop reports success and leaves vendor bytes behind.
This is the single most likely way this runbook silently fails.*

### Step 5 — Delete Bronze  *(`licensed_data_deletion` role)*

Delete every object under `bronze/`. Re-list. Confirm zero objects.

### Step 6 — Delete Silver  *(`licensed_data_deletion` role)*

Delete every object under `silver/`. Re-list. Confirm zero objects.

*Silver is a normalization of vendor rows and is squarely inside "substantially copy" — it is not
a derived work under the carve-out (packet §3.C).*

### Step 7 — Delete Gold and every reconstructable derivative  *(`licensed_data_deletion` role)*

Delete every object under `gold/` and `qualification/`, including the adjusted-bar cache
artifacts, historical universe snapshots, factor panels and any provider qualification evidence
embedding vendor rows. Re-list. Confirm zero objects.

*Factor panels are here because [ADR-0007 §3](../decisions/ADR-0007-cloud-first-research-data-plane.md)
defaults ambiguity to LICENSED. If Q4 is ever answered in a way that permits retaining them, that
is a documented decision that changes the classification — never an on-the-day judgement call
made while deleting.*

### Step 8 — Confirm the whole bucket is empty  *(`licensed_data_deletion` role)*

1. List the entire licensed bucket with no prefix filter. Confirm zero objects.
2. `ListMultipartUploads` again. Confirm zero.
3. If versioning was **ever** enabled on this bucket, list **object versions and delete markers**,
   not objects, and delete every version. A bucket with delete markers and no current objects
   lists as empty and still holds the data.
4. Record the final empty listings.

### Step 9 — Verify no replication and no archival copy  *(`licensed_data_deletion` role)*

1. Confirm no replication configuration on the licensed bucket, and no destination bucket exists.
2. Confirm no Glacier or archival lifecycle transition ever moved objects into a restore-required
   class. If one did, those copies are deleted the same way and separately evidenced.
3. Confirm no AWS Backup plan, no snapshot and no cross-account copy references the bucket.
4. Record each confirmation.

*ADR-0007 §4 turns all three off precisely so this step is a confirmation rather than an
investigation.*

### Step 10 — Verify ephemeral compute retained nothing  *(operator path)*

1. Confirm no ECS task is running.
2. Fargate ephemeral storage is destroyed with the task; confirm no task persisted data anywhere
   other than S3 — the licensed prefixes are the only sanctioned destination.
3. Confirm no EBS volume, snapshot or EFS filesystem holds vendor data.
4. Record the confirmations.

### Step 11 — Verify container layers hold no data  *(operator path)*

1. Confirm no ECR image contains licensed data. Per ADR-0007 §7, no image may ever be built with
   data in it; this step verifies the rule held rather than assuming it.
2. If any image does, delete the image **and every tag and digest referencing it** — a layer is
   shared and survives deletion of one tag.
3. Record the image inventory.

### Step 12 — Verify logs contain no data and no key  *(operator path)*

1. Search CloudWatch log groups for vendor payload content, for full provider request URLs, and
   for the API key value.
2. If anything is found, delete the affected log streams — or the log group — and record it as an
   **incident**, because it means the ADR-0007 §8 redaction criteria were not met.
3. Confirm log retention is bounded, so nothing survives beyond its stated period.
4. Record the searches performed and their results.

*Do not paste any found value into the receipt, an issue, a commit message or an AI session. The
finding is that something was present, not what it was.*

### Step 13 — Delete the laptop cache and every local copy  *(operator path)*

**Cloud-first does not exempt the workstation.** §10 reaches every system the owner operates.

1. Delete `.runtime/data/` in every clone on every machine.
2. Delete any temporary export, notebook output, spreadsheet, downloaded file or scratch copy.
3. Confirm nothing vendor-derived is in the working tree — vendor data is never committed
   (ADR-0005 §14), so `git` history should be clean by construction; confirm rather than assume.
4. Record the paths cleared, per machine.

*Repository-owned **synthetic** fixtures under `tests/` are explicitly out of scope. They are
hand-authored and fictitious, contain no vendor data, and must not be deleted.*

### Step 14 — Produce the deletion receipt  *(operator path)*

Write a receipt to the **control** bucket under `receipts/` and, where it contains no vendor
material, retain a copy in the repository as governance evidence. It records:

| Field | Content |
|---|---|
| Termination date, and the date the 30-day clock started | — |
| Authorization | who authorized execution, and when |
| Per-prefix before/after | object counts and bytes, before and after |
| Multipart uploads | aborted count; final empty listing |
| Versioning | whether it was ever enabled; if so, version and delete-marker counts removed |
| Replication / archival / backup | each confirmed absent |
| Compute, container, log | each verification and its result |
| Local machines | each machine, and the paths cleared |
| Retained under the carve-out | what was kept, and why it is non-reconstructable |
| Exceptions | anything not deleted, and the reason |
| Operator and completion date | — |

**The receipt must contain no vendor data, no API key, no AWS account id and no bucket name that
identifies the owner.** A receipt proving deletion is worthless if producing it reintroduces the
thing deleted.

### Step 15 — Confirm what legitimately remains  *(operator path)*

After completion, the **control** bucket still holds, and should still hold:

| Retained | Why it is permitted |
|---|---|
| Run manifests and `run_id` records | identifiers of data, not data |
| Content hashes | a hash cannot reproduce its input |
| Provenance and lineage records | structure, not content |
| Code and config fingerprints | describes the system, not the data |
| Missing-input receipts | evidence data is *absent* |
| Approved non-reconstructable outputs, backtest results, summary statistics | §10 carve-out (`PSR-SHD-084`) |
| Deletion receipts | this runbook's own evidence |

**A rerun from a surviving manifest must now fail loudly, naming the missing input.** That is
ADR-0005 acceptance criterion 14 working correctly, not a regression: durable rerunability
depended on the subscription, and the manifest model was designed to say so out loud rather than
silently produce a different answer.

---

## 4. What this runbook cannot do

Stated plainly, because a procedure that oversells itself is worse than one that does not exist.

- **It cannot prove a negative.** It evidences that the enumerated surfaces were emptied. It
  cannot prove no copy was made somewhere nobody recorded — which is exactly why the
  licensed/control boundary must hold continuously rather than be reconstructed on the day.
- **It cannot undo a leak.** If licensed data ever reached a public repository or an external AI
  provider, deleting the buckets does not retrieve it. INC-0002 is this repository's own evidence
  that a force-push does not delete anything from GitHub.
- **It cannot decide the ambiguous cases.** Whether a dense factor panel is retainable is question
  **Q4** and part of gate **G3**, which is **OPEN**. Until answered, the panel is deleted, because
  defaulting to deletion is the safe direction under an unresolved clause.
- **It has never been executed**, and an unexecuted procedure has unknown defects. The first real
  run should be treated as a rehearsal that also happens to be real, with time budgeted for it.

---

## 5. Rehearsal, before it is ever needed for real

Once AWS resources exist and *before* any licensed data is ingested, this procedure should be
rehearsed end to end against **synthetic** objects: write fixtures into the licensed prefixes,
start and abandon a multipart upload, then run every step and produce a receipt.

> **Precondition status (2026-08-27).** AWS resources now exist — the foundation was provisioned
> ([aws-foundation-status.md](../operations/aws-foundation-status.md)) — and the licensed bucket
> is still empty, so this is the ideal window. **The rehearsal has still NOT been run.**
>
> Provisioning included a five-step synthetic *storage* smoke test (put, get, checksum, delete,
> confirm-absent). That is **not** this rehearsal and must not be recorded as one: it used the
> operator's federated session rather than the deletion role, touched one object rather than the
> licensed prefixes, started no multipart upload, and produced no receipt.
>
> The deletion role was not used because **no current path can run anything as it**: its trust
> policy admits `ecs-tasks.amazonaws.com` only, so no human can directly assume it; no deletion
> task definition exists; no deletion workflow exists; and no authorized principal holds
> `iam:PassRole` for it. A real rehearsal therefore needs the deletion workflow that is **not
> authorized**.

A rehearsal costs cents and finds the steps that do not work. Discovering them inside a 30-day
window that started without notice costs considerably more. **Rehearsal requires the same
authorization as any other AWS activity, and is not authorized here.**

---

## 6. Escalation

If any step cannot be completed within the 30-day window — an inaccessible copy, an unresolvable
log finding, a bucket that will not empty — **stop and escalate to the owner in writing** rather
than reporting completion. Recording a partial deletion honestly is a defensible position.
Reporting a deletion that did not happen is not.

---

## 7. Pre-flight verification that the boundary held

Run before step 5, and ideally on a schedule long before termination is ever contemplated:

1. Sample the **control** bucket for anything that looks like vendor rows: raw payloads,
   normalized tables, dense per-security per-date panels.
2. Any finding is a **boundary violation**. Move it to the licensed bucket, delete it from the
   control bucket, and record it — before the deletion steps run, so that it is deleted with
   everything else rather than surviving in the bucket the procedure deliberately leaves alone.
3. Record the sampling method and the result.

*The control bucket is the one place this procedure does not empty. That is exactly what makes a
misfiled artifact there the most durable possible mistake, and why this check exists.*
