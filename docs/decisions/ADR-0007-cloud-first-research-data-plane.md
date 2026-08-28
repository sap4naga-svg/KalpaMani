# ADR-0007 — Private AWS Cloud-First Research Data Plane

**Status:** **Accepted — effective on the merge of the pull request that introduces this ADR.**
Until that merge it is proposed and carries no authority.
**Date:** 2026-08-27
**Deciders:** Project owner (human governance)
**Supersedes:** the *deployment location* of the Phase-3 research store proposed in
[ADR-0005](ADR-0005-point-in-time-data-architecture.md) §11 and
[implementation-plan.md](../phase3/implementation-plan.md) §1.3 — and nothing else in either.
**Superseded by:** —
**Relates to:** [ADR-0001](ADR-0001-system-foundation.md) (PostgreSQL as the operational
database), [ADR-0002](ADR-0002-broker-adapter-and-brokerage-boundary.md) §13 (market-data code
stays separate from brokerage execution),
[ADR-0003](ADR-0003-broker-side-order-controls-are-not-safety-invariants.md) (no safety claim may
rest on a control the deployment path can silently reset),
[ADR-0005](ADR-0005-point-in-time-data-architecture.md),
[ADR-0006](ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md)
**Authority:** Blueprint V3.0 §17, §19, §26

---

## Context

The Phase-3 planning package placed the point-in-time research store on the development
laptop: Parquet and a DuckDB catalog under the git-ignored `.runtime/data/` tree
([implementation-plan.md](../phase3/implementation-plan.md) §1.3, ADR-0005 §11). That was the
right recommendation for the slice that has actually been built. The A1 foundation kernel holds
a few dozen fictitious rows, adds no runtime dependency, and needed to prove *determinism and
content-addressed identity*, not analytical throughput.

It is the wrong shape for the layer that will hold real vendor history, for three reasons that
only appear once the data is real:

1. **Ingestion becomes a background obligation.** Daily and backfill ingestion against a
   provider must not require a particular laptop to be powered on, awake, connected and not
   mid-update. A store whose availability is a person's laptop lid is not a store.
2. **Research compute outgrows the workstation before the data does.** A full-universe,
   multi-year, profile-keyed factor rebuild is a batch job. Running it on the machine also used
   to edit code and drive IB Gateway couples two things that should not be coupled.
3. **Durability.** `.runtime/` is git-ignored precisely because it must never be committed,
   which also means it is the one part of this system with no version-controlled copy. A disk
   failure loses every ingested artifact and every manifest that names one.

None of that is controversial. What follows is, and it is the actual subject of this ADR.

### Moving rented data into a cloud account makes deletion *harder*, not easier

The provider licensing packet's §3.C finding is the constraint that governs this design. Under
the leading candidate's §10, on termination the subscriber must delete, within 30 days,
*"all copies of the Services Data (including downloads, bulk files, caches, and extracts)"* and
*"all data sets that contain, substantially copy, or could reproduce the Services Data"* — from
*"all computer systems you own or operate"* — and termination may be immediate and without prior
notice ([provider-licensing-decision-packet.md](../phase3/provider-licensing-decision-packet.md)
§3.C, `PSR-SHD-083`, `PSR-SHD-085`).

**A private AWS account is a computer system the owner operates.** Every default that
conventional cloud architecture treats as obviously correct is, against that clause, a liability:

| Conventional cloud default | What it does to a §10 deletion obligation |
|---|---|
| S3 **versioning** on | A delete writes a delete marker. The bytes remain as noncurrent versions. The bucket *looks* empty and is not. |
| **Object Lock** / compliance mode | Makes deletion **impossible until expiry, by design — including for the account root**. Directly incompatible with a 30-day deletion obligation. |
| Cross-region **replication** | Creates a second copy, in a second bucket and possibly a second region, that the deletion procedure must know about to reach. |
| **Glacier / archival lifecycle** | Moves copies into a class with retrieval latency and minimum-duration billing, making *delete and prove it* slower and more expensive. |
| Automated **backup** of the data bucket | Creates copies in a service whose whole purpose is surviving deletion. |

This is the mirror image of the mistake ADR-0003 records. There, a broker-side control was
assumed to be a safety invariant and the deployment path silently reset it. Here, a cloud
durability feature would be enabled because it is *generally* good practice, and would silently
defeat a contractual obligation the architecture is supposed to satisfy. **Generic best practice
is not a substitute for reading what this particular system is required to be able to do.**

So the licensed-data store is deliberately built *against* the conventional durability posture,
and the reason is written down here so that a future reviewer who notices versioning is off does
not helpfully switch it on.

### The one thing that must not be lost by turning durability features off

Bronze immutability is a **Phase-3 contract requirement** (ADR-0005 §10: *"immutable,
content-addressed vendor payloads, append-only"*). It would be a mistake to satisfy that with S3
versioning and then discover the two requirements are in direct conflict.

They are not in conflict, because **versioning was never the mechanism**. The A1 kernel already
implements Bronze and Gold immutability in software: artifacts are named by the SHA-256 of their
contents, `LocalTableStore.commit_version` refuses to publish over an existing version
(*"versions are superseded, never rewritten"*), and a re-fetch returning different bytes is a
*new* artifact rather than a replacement — which is exactly what makes a vendor backfill visible
instead of silent. Content addressing gives immutability *and* tamper evidence: a modified object
no longer hashes to its own name.

**Object versioning would be a second, weaker mechanism for a property the first already
guarantees, bought at the price of the deletion obligation.** It is therefore off.

**Stated precisely, because the two properties are easy to run together: no immutability or
content-identity guarantee is lost. Recoverability is deliberately traded away.** Turning these
features off does cost something real, and *Consequences* below records it — an erroneous
deletion destroys the exact historical payload with nothing to restore from, and re-fetching
from the provider is not restoration: it returns the vendor's data as it stands today, which
after a correction or backfill is a **new artifact with a new hash** rather than the original.
The mechanism that makes a vendor backfill visible instead of silent is precisely what stops a
re-fetch from reconstituting history. That trade is accepted on the judgement that an
unsatisfiable deletion obligation is a worse failure than an unavailable restore, for data that
is rented rather than owned.

---

## Decision

### 1. The Phase-3 research data plane is private-AWS cloud-first

The intended authoritative location for licensed research data and heavy deterministic research
compute is a **private AWS account**.

| Role | Holder |
|---|---|
| Authoritative licensed-data store | **Private AWS S3** — licensed-data bucket |
| Authoritative control/provenance store | **Private AWS S3** — control bucket |
| Heavy deterministic research and ingestion compute | **Ephemeral AWS compute** — ECS Fargate tasks; Batch/EC2 Spot as a documented later path |
| Development and control workstation | **The laptop** |
| Optional temporary cache, staging, synthetic fixtures, local testing | **The laptop**, under `.runtime/data/` |

The laptop is explicitly **not**: the authoritative long-term licensed-data store; a machine that
must remain powered on for ingestion to proceed; or a machine required for heavy backtests.

**No AWS resource exists.** This ADR selects an intended target platform and commits an
infrastructure description. It provisions nothing — see §12.

### 2. The quantitative stack does not change

Parquet, DuckDB and Python remain the research stack, exactly as ADR-0005 §11 proposes. What
changes is **where the Parquet lives**: private object storage rather than a local disk, with
DuckDB reading Parquet from S3. The A1 kernel's newline-delimited canonical JSON remains correct
for the synthetic slice it serves; adopting Parquet remains a writer change, and is still gated
on G1 selecting a provider and therefore a data volume.

**PostgreSQL's role is unchanged and is not affected by this ADR.** ADR-0001 selects PostgreSQL
for operational, transactional, concurrently-written state — features, signals, trades, audit
state. That remains true, remains unimplemented, and is a different job from analytical queries
over immutable research files. Nothing here substitutes object storage for it.

### 3. Two buckets, and the licence's own test decides which one an artifact goes in

Two separate private buckets, with a strict promotion boundary between them.

```
LICENSED-DATA BUCKET                    CONTROL / PERMITTED-OUTPUT BUCKET

  bronze/        raw vendor payloads      manifests/  run manifests, run_id records
  silver/        normalized vendor rows   lineage/    lineage refs, code/config
  gold/          PIT research artifacts               fingerprints
  qualification/ provider test evidence   receipts/   missing-input receipts,
                                                      deletion receipts
                                          outputs/    approved non-reconstructable
                                                      outputs

  deletion-friendly by construction       versioning permitted
  no versioning · no Object Lock          nothing here is subject to a vendor
  no replication · no archival lifecycle  deletion obligation
```

The boundary is **not** "raw versus derived", and not "how derived a thing feels". The licence
does not draw that taxonomy. It asks **one binary question**, in both its redistribution clause
and its retention clause (packet §3.D):

> **Can the vendor's rows be recovered from this artifact?**

If yes — or if the answer is uncertain — the artifact is **LICENSED**. Only artifacts for which
the answer is a confident *no* may be promoted to CONTROL.

| Artifact | Bucket | Why |
|---|---|---|
| Bronze vendor payloads | LICENSED | is the Services Data |
| Silver normalized rows | LICENSED | *"substantially copy"* by construction |
| Gold PIT artifacts, adjusted-bar cache, historical universes | LICENSED | reconstructable from, and reconstructing, vendor rows |
| Per-security per-date factor panels | **LICENSED** | the hardest case under *"could reproduce"*; packet §3.D marks it **AMBIGUOUS**, and ambiguous resolves to LICENSED |
| Provider qualification evidence (P1–P9) where it embeds vendor rows | LICENSED | sampled rows are extracts |
| Run manifests, `run_id`, content hashes, code/config fingerprints | CONTROL | identifiers *of* data, not data |
| Lineage and provenance records | CONTROL | structure, not content |
| Missing-input receipts, deletion receipts | CONTROL | evidence that data is *absent* |
| Scalar performance summaries, backtest **results** | CONTROL | named in the §10 carve-out |

**The default is LICENSED.** A new artifact type nobody has classified is LICENSED until someone
classifies it, because the failure directions are not symmetric: an over-classified artifact costs
a deletion that was not required, and an under-classified one is a copy that survives a deletion
obligation in a bucket the runbook never visits.

The control bucket must never silently receive raw vendor rows, normalized vendor tables, or
reconstructable factor panels. Promotion is a deliberate, reviewed act, not a default.

> **This ADR does not resolve the underlying ambiguity — it contains it.** Whether a dense factor
> panel is retainable after termination is question **Q4** of the licensing clarification draft,
> and part of gate **G3**, which is **OPEN**. Defaulting to LICENSED is how the architecture stays
> correct under either eventual answer.

### 4. The licensed bucket is deletion-first

Enforced in the infrastructure description, not merely documented:

| Control | Setting | Reason |
|---|---|---|
| Block Public Access | **all four controls ON** | non-negotiable, both buckets |
| Object ownership | **bucket-owner-enforced**, ACLs disabled | removes ACL-based access as a surface entirely |
| Encryption at rest | **on** | baseline |
| TLS | **required by bucket policy** — deny when `aws:SecureTransport` is false | encryption in transit enforced, not assumed |
| Public bucket policy | **none** | — |
| Cross-account principals | **none** | — |
| Anonymous access | **none** | — |
| **Versioning** | **OFF** | immutability comes from content addressing; versions are copies a deletion must reach |
| **Object Lock** | **OFF** | would make the 30-day obligation unsatisfiable |
| **Replication** | **OFF** | a second copy the runbook would have to know about |
| **Glacier / archival transitions** | **OFF initially** | slows and complicates provable deletion |
| **Backups of the licensed bucket** | **none** | a backup is a copy that outlives deletion |
| Abort incomplete multipart uploads | **lifecycle rule ON** | see below |

**The multipart-upload rule is a deletion aid, not an archival lifecycle, and the distinction
matters.** Parts of an incomplete multipart upload are stored and billed but do **not** appear in
an object listing. A deletion procedure that enumerates objects and deletes them will therefore
leave vendor bytes behind while reporting success. Aborting incomplete uploads automatically, and
explicitly listing and aborting them during the runbook, closes a gap a list-and-delete loop
cannot see by construction.

If versioning is ever enabled on the licensed bucket, **every version must be purgeable and the
deletion procedure must enumerate versions and delete markers**, not objects. The preference is
simply not to enable it.

The control bucket carries the same public-access, ownership, encryption and TLS posture.
Versioning **may** be enabled there, because nothing in it is subject to a vendor deletion
obligation — which is precisely what promotion into it asserts.

### 5. Storage persists; compute is ephemeral

**No always-on research server.** An idle EC2 instance or a permanently running container is
rejected: it bills continuously, holds state that should live in S3, and becomes a machine
somebody has to maintain.

| Workload | Vehicle |
|---|---|
| Ingestion, normalization, moderate curation | **ECS Fargate one-off tasks** — run, work, exit |
| Heavy research and backtests | **AWS Batch / EC2 on-demand or Spot** — a documented future scaling path, **not provisioned here** |

The initial scaffold creates an **ECS cluster** — a logical grouping that costs nothing while no
task runs — suitable for future one-off research and ingestion tasks. **No task is run, and no
image exists to run.**

### 6. No inbound network exposure, and no idle network cost

Research compute needs **outbound** HTTPS: a provider API, SEC EDGAR, and controlled package and
image retrieval. It needs **no inbound** anything — there is no service, no listener, no port, no
load balancer, and nothing that answers.

```
dedicated VPC
  public subnets, used only by ephemeral outbound-capable tasks
  security group with ZERO inbound rules
  egress: HTTPS only
  a task receives a temporary public IP only while it runs, and only when it needs egress
```

**Why not private subnets behind a NAT Gateway, which is the textbook answer.** A NAT Gateway
bills hourly whether or not anything uses it — on the order of USD 30–35/month at current public
pricing, before data-processing charges — for an account that is idle almost all of the time.
That is real recurring money spent to make an *already unreachable* task unaddressable. It
contradicts the near-zero-idle-cost objective for no security gain the security group does not
already provide.

**Why a public IP is acceptable here, stated precisely.** A public IP makes a task *addressable*,
not *reachable*. Reachability requires a security-group rule permitting inbound traffic, and there
are none; security groups deny inbound by default and are **stateful**, so replies to the task's
own outbound connections return without any inbound rule existing. There is also nothing
listening to reach. The exposure is an address that drops every unsolicited packet.

This argument is explicitly **conditional on there never being a listener.** The moment any
component needs to accept a connection, this design is wrong and must be replaced by private
subnets with a NAT Gateway or — better for an S3-dominated workload — **VPC endpoints**: a Gateway
endpoint for S3, which carries no hourly charge, plus Interface endpoints for ECR and CloudWatch
Logs, which do. That upgrade path is recorded here so that taking it is a decision rather than a
discovery.

S3 Block Public Access is independent of all of this and is mandatory regardless.

### 7. A private container registry, and nothing sensitive in the image

A private **ECR** repository for future KalpaMani research images: image scanning on push,
immutable tags so a tag cannot be re-pointed under a running deployment, and a lifecycle rule
bounding untagged-image accumulation.

**Nothing sensitive is ever baked into an image**: no credentials, no provider API keys, no
licensed data, no `.env`. An image layer is a durable, distributable copy — a key in a layer is a
key that survives every rotation, and vendor rows in a layer are a copy the deletion runbook must
reach. Both are prevented by never putting them there.

**No image is built or pushed by this ADR.**

### 8. Secrets: the contract only

Future provider credentials live in **AWS Secrets Manager** or **SSM Parameter Store
SecureString**, injected into a task at runtime through the task role. They must never appear in
Terraform variables or committed `.tfvars`; Terraform state; environment files in Git; container
images; CloudWatch Logs; or shell scripts.

**No secret is created, populated or referenced by value in this change.** Terraform declares no
secret resource carrying a value. Only the interface is recorded.

#### The query-string problem, and why it becomes an acceptance criterion

The leading provider candidate accepts its API key **as a URL query parameter**. That single fact
defeats the usual mental model of secret hygiene, because the secret stops being a header that
tooling knows to redact and becomes part of a string that everything logs by default:

| Path | What lands where |
|---|---|
| An unhandled exception | the full request URL, including the key, inside the traceback |
| HTTP-library debug logging | the full URL, once per request |
| Retry / backoff logging | the full URL, once per attempt |
| A non-200 response log line | the full URL, plus response body |
| Any of the above under ECS | **CloudWatch Logs — a durable, queryable, long-lived store** |

A key logged to CloudWatch is not a transient mistake; it is a credential written to a database.
Therefore, as a **mandatory acceptance criterion for any future provider client** — binding when
that client is written, and *not* an authorization to write it:

1. Query strings are **redacted at the logging boundary**, not at each call site.
2. API keys are redacted wherever they may appear, by parameter name **and** by value match.
3. Full request URLs never reach logs; only scheme, host and path do.
4. Exceptions are **sanitized before propagation** — a raised exception carrying a URL is the most
   likely leak path precisely because nobody writes it deliberately.
5. Retry and backoff logging is sanitized under the same rule.
6. HTTP debug/trace logging is **off in every deployed configuration**, and its accidental
   enablement must not leak a key.
7. Log retention is bounded, and no vendor payload is ever logged.

This is recorded now so it is a requirement *before* the client exists, rather than a finding
after it does.

### 9. The AI boundary is unchanged, and cloud-first does not widen it

Cloud-first changes where deterministic code runs. It changes nothing about what AI may see.

**Permitted:** deterministic KalpaMani code processing provider raw and provider-derived data
**inside the private AWS account**. That is the entire point of the quantitative engine, and
nothing here restricts it.

**Not permitted:** vendor raw or provider-derived rows automatically leaving that boundary into an
external LLM API (Anthropic, OpenAI or any other), a public GitHub repository, or a third-party
shared SaaS.

The AI layer may receive: public qualitative sources; SEC material subject to applicable use-time
rights; approved `CandidateIntent` fields (Blueprint V3.0 §8 — never shares, dollar size, order
type, route or any order ID); and approved **non-reconstructable** derived quantitative summaries.

> **The most likely violation in this repository is not a strategy calling an LLM API.** It is an
> interactive assistant session — one exactly like the sessions that build this system — reading a
> bronze or silver file into its context to debug something. That is an upload of vendor rows to
> an external model provider; it is indistinguishable from any other file read at the moment it
> happens; and no amount of runtime code prevents it. It is prevented by the rule that licensed
> data lives in the private account and not in the working tree, and by naming the failure mode
> here so that it is recognisable when it is about to happen.

**No raw vendor row may enter an external AI prompt.** This restriction does not prevent vendor
data from powering the quantitative engine, which is deterministic and runs in the private
account.

### 10. Identity is a hash; `s3://` is a location

Moving storage must not move identity. The point-in-time contract's reproducibility model rests on
content hashes, `run_id` values and manifests (ADR-0005 §18), none of which mention a filesystem.

**A manifest names hashes. It does not name buckets.** An `s3://` URI is a resolvable *location*
for an artifact, never the artifact's *identity*. The consequences are deliberate:

- The same artifact has the same identity in the laptop cache, in the licensed bucket, and in a
  future different bucket or region.
- Changing bucket names or regions cannot invalidate a manifest.
- The A1 kernel's identity, hashing, manifest, profile, provenance and evidence semantics are
  **unchanged by this ADR**. Nothing about point-in-time correctness moved.
- A deletion under §10 removes the *bytes*; the manifest naming them survives in the control
  bucket, and a rerun then fails loudly naming the missing input — which is acceptance criterion
  14 behaving exactly as specified (packet §3.C).

### 11. Research code does not import an AWS SDK

`s3://` paths must not be hard-coded through research logic, and research and data-contract code
must not import `boto3`. AWS belongs behind an infrastructure/storage boundary.

The contract, recorded for a later authorized slice to implement:

```python
class ResearchObjectStore(Protocol):
    def put_content_addressed(self, payload: bytes, *, prefix: str) -> str: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def list_prefix(self, prefix: str) -> Sequence[str]: ...
    def delete(self, key: str) -> None: ...
    def checksum(self, key: str) -> str: ...
```

with two later implementations — `S3ResearchObjectStore` and `LocalResearchObjectStore` — and
`delete` present on the interface *because deletion is a licensing requirement*, not merely a
convenience.

**No code is added by this ADR, deliberately.** A new module under `src/kalpamani/data/` would
fail `test_the_data_package_holds_only_the_authorized_a1_surface`, which asserts that package
holds exactly the authorized A1 surface. Widening it is an A2 decision, and A2 is not authorized.
The boundary this section exists to protect is meanwhile **already enforced by tests**: `boto3`
and `botocore` are in `FORBIDDEN_DISTRIBUTIONS`, so neither may be declared as a dependency nor
imported by any `kalpamani` module. Weakening an existing guard in order to scaffold an interface
for unauthorized work would be the wrong trade.

### 12. What is committed is a description, not infrastructure

`infra/aws/research-data-plane/` contains Terraform describing the above. It has been formatted,
initialized offline and validated against the real AWS provider schema (`hashicorp/aws` v6, pinned
by a committed `.terraform.lock.hcl`). **It has not been applied, no state exists, no AWS account
has been created, no credentials were used, and no resource has been provisioned.**

**Validating is not planning.** `terraform validate` checks syntax, provider schema conformance
and internal references without contacting AWS — and it does not evaluate input-variable rules, so
a passing validate is not evidence that the wrong-account binding works. `terraform plan`,
`apply`, `refresh` and `import` each require their own explicit written authorization, separate
from and later than this ADR.

**The AWS account binding fails closed.** `allowed_account_ids` has no default and must be a
non-empty list of twelve-digit ids, so an omitted binding is a hard error before any provider call
rather than a silently disabled check. This is the same rule CLAUDE.md §3 applies to GitHub
accounts and ADR-0003 applies to broker-side controls: **a control that is off unless someone
remembers to switch it on is not a control.**

---

## Consequences

**Positive**

- Ingestion and heavy research stop depending on one laptop being awake.
- The deletion obligation becomes an architectural property enforced by configuration, rather than
  an intention discovered to be unimplementable on the day it is invoked.
- The licensed/control split makes "what must be destroyed" a *location*, so the runbook is a
  procedure over prefixes instead of a search.
- Idle cost is near zero: object storage, and nothing else.
- Point-in-time semantics, hashes, manifests, profiles and evidence contracts are untouched.

**Negative / accepted costs**

- **Reduced durability on the licensed bucket, on purpose.** No versioning, no replication and no
  backup means an erroneous delete or overwrite is not recoverable from AWS. Content addressing
  makes an overwrite-in-place fail rather than corrupt silently, so the exposure is deletion
  rather than corruption — but **a re-fetch is not a restore**. It returns the vendor's data as it
  stands today; after a correction or backfill that is a new artifact with a new hash, and the
  original payload is simply gone. It is also possible only while the subscription is live. The
  practical protection is operational care around deletion, not a durability feature. A real
  trade, accepted deliberately rather than overlooked.
- **A public-subnet egress design that is correct only while nothing listens.** It is cheap and
  safe under a zero-inbound security group, and it becomes wrong the moment that premise changes.
- **A second deletion surface remains.** Cloud-first does not remove the laptop from *"all
  computer systems you own or operate"*. Any local cache under `.runtime/data/` is in scope, and
  the deletion runbook must cover it. Cloud-first narrows the problem; it does not eliminate it.
- **Operational surface grows.** An AWS account is a thing to secure, budget and monitor. A budget
  alarm becomes mandatory before any real ingestion.
- **Cost becomes usage-dependent rather than zero.** S3 storage and Fargate seconds are small but
  not free, and a runaway job is a way to spend money that a laptop is not.

**Neutral**

- ADR-0001's PostgreSQL selection is untouched. ADR-0005 §11's Parquet/DuckDB recommendation is
  untouched. Only the location changes.

---

## What this decision does NOT do

This ADR selects AWS as the **intended** research deployment platform and commits an
infrastructure *description*. Explicitly, it does **not**:

- select a production data provider, and does not select Sharadar — **G1 remains OPEN**;
- resolve the production information-set profile — **G2 remains OPEN**;
- resolve vendor licensing, answer Q1–Q6, or authorize contacting a vendor — **G3 remains OPEN**;
- resolve the analyst-estimate gap — **G4 remains OPEN**;
- qualify borrow history or authorize short research — **G5 remains OPEN**;
- resolve the options overlay or the strategy-taxonomy question — **G6 and G7 remain OPEN**;
- accept ADR-0005, which **remains PROPOSED**;
- authorize **any** AWS spending;
- authorize `terraform apply`, AWS resource creation, or creating an AWS account;
- authorize changing billing, or entering AWS credentials into Git or any repository file;
- authorize provider purchase, trial, account creation, credentials, sample or data retrieval;
- authorize SEC ingestion, or any real provider data acquisition;
- authorize Phase 3A A2 or A3, or Phase 3B, 3C or 3D;
- authorize any broker or LEAN activity;
- change strategy capital, risk parameters or leverage;
- alter the AI/deterministic boundary;
- authorize live trading, which remains **HARD-DISABLED**.

**Gates G1–G7 are all OPEN.** Nothing has been purchased, trialled or credentialed. No vendor data
has been retrieved. No AWS resource has been created and no AWS spend has been incurred. Phase 3
remains **NOT COMPLETE**.

---

## Follow-ups

Listed by topic. Numbers are taken when an ADR is written, from the next unused number in
`docs/decisions/`.

- **AWS account creation, budget alarm and `terraform apply` authorization** — required before any
  resource exists. The budget alarm needs a notification destination, which is personal
  information and is therefore not committed here.
- **Remote Terraform state backend** — an encrypted, versioned state bucket with locking, decided
  when apply is authorized. State may reference bucket and account identifiers, and is never
  committed.
- **Provider client redaction implementation** — the §8 acceptance criteria, when a client is
  authorized.
- **`ResearchObjectStore` implementation** — an A2 decision.
- **Private-subnet / VPC-endpoint network revision** — if any listener is ever required, or if S3
  data-transfer volume justifies a Gateway endpoint.
- **Parquet writer and DuckDB catalog over S3** — after G1 fixes the data volume.
