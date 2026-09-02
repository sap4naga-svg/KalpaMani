# KalpaMani — Private AWS Research Data Plane (Terraform)

## STATUS: **APPLIED — 2026-08-27**

```
AWS account              EXISTING  (pre-dates this work; configured 2026-08-27)
AWS resources created    36        (0 changed, 0 destroyed)
terraform state          REMOTE    private S3 backend, SSE-S3, versioned, S3 native locking
verification             66/66 PASS
licensed bucket          EMPTY
control bucket           EMPTY
ECR repository           EMPTY     no image built or pushed
ECS                      no task definition, nothing running
provider credentials     NONE
vendor data              NONE
further cloud spend      NOT AUTHORIZED
```

This directory was applied on 2026-08-27 under a specific written authorization covering the
foundation and nothing else. The full record, with no identifiers, is
[docs/operations/aws-foundation-status.md](../../../docs/operations/aws-foundation-status.md).

**What exists is an empty, idle platform.** Provisioning it authorized no ingestion, no provider
purchase, no credential and no implementation. Provider access, image builds, task execution and
any further cloud spend each require their own written authorization, separate from and later
than [ADR-0007](../../../docs/decisions/ADR-0007-cloud-first-research-data-plane.md).
**G1 OPEN · G2 OPEN · G3 CLOSED (Sharadar personal use, ADR-0008) · G4 OPEN · G5 OPEN · G6 OPEN · G7 OPEN**. ADR-0005 **remains PROPOSED**.

**Authority:** [ADR-0007](../../../docs/decisions/ADR-0007-cloud-first-research-data-plane.md) ·
[ADR-0005](../../../docs/decisions/ADR-0005-point-in-time-data-architecture.md) ·
[CLAUDE.md](../../../CLAUDE.md)
**Deletion procedure:** [vendor-data-cloud-deletion.md](../../../docs/runbooks/vendor-data-cloud-deletion.md)

### Not everything in this directory has been applied

The `APPLIED` line above describes the 2026-08-27 apply and the 36 resources it created. It is
**not** a statement that every file here has been applied, and two files have not been:

```
qualification_policies.tf     OFFLINE CANDIDATE -- NEVER PLANNED, NEVER APPLIED
qualification_principals.tf   OFFLINE CANDIDATE -- NEVER PLANNED, NEVER APPLIED
```

`qualification_policies.tf` declares the two ADR-0018 §10 qualification permission sets, as
amended by
[ADR-0019](../../../docs/decisions/ADR-0019-write-only-acquisition-collision-policy.md) and
[ADR-0020](../../../docs/decisions/ADR-0020-request-scoped-qualification-payload-identity.md), and
**two `aws_iam_policy` resources are the whole of it** — no role, no trust policy, no attachment,
no bucket and no bucket property. A managed policy attached to no principal grants nothing.

`qualification_principals.tf` names the holder that file deliberately left unnamed, under
[ADR-0021](../../../docs/decisions/ADR-0021-qualification-runtime-principal-and-trust-model.md):
**two IAM Identity Center permission sets, one customer-managed-policy reference each, and two
group-principal account assignments** — and that is the whole of it. There is still **no
`aws_iam_role`, no trust policy, no IAM user, no access key, no instance profile, no service
principal and no `sts:AssumeRole`**: Identity Center creates and owns the runtime role each
assignment produces, and this repository authors no trust boundary of its own. Neither policy's
action or resource matrix is touched. Every environment binding it needs — the Identity Center
instance, the governed operator group and the target account — is an input with **no default**,
and there is no data source of any kind, so nothing here reads the live environment.

**No `terraform plan`, `apply`, `init` or `validate` has been run against either file**, so
`terraform state` still holds the 36 resources the 2026-08-27 apply created. **A declaration is
not a resource**: no permission set, assignment, generated role or policy attachment exists
because these files describe one, whether any such object exists in AWS is **NOT ESTABLISHED**
here, and **no principal has been granted any AWS authority**. Applying either file is a
separate, ungranted authorization — see each file's own header.

---

## What this builds, when it is eventually authorized

```
                     provider API / SEC EDGAR
                              │  outbound HTTPS only
                              ▼
              ┌───────────── PRIVATE AWS ACCOUNT ──────────────┐
              │                                                │
              │   VPC · public subnets · SG with ZERO inbound  │
              │                     │                          │
              │             ECS Fargate one-off task           │
              │             (runs, works, exits)               │
              │                     │                          │
              │        ┌────────────┴────────────┐             │
              │        ▼                         ▼             │
              │  LICENSED BUCKET           CONTROL BUCKET      │
              │   bronze/ silver/           manifests/         │
              │   gold/ qualification/      lineage/           │
              │                             receipts/ outputs/ │
              │   no versioning             versioning on      │
              │   no Object Lock            nothing here is    │
              │   no replication            vendor-terminable  │
              │   no archival lifecycle                        │
              │                                                │
              │   ECR (private, empty) · CloudWatch Logs       │
              └────────────────────────────────────────────────┘
```

| File | Contents |
|---|---|
| `versions.tf` | Terraform and provider constraints; why there is no backend block |
| `providers.tf` | AWS provider; the wrong-account guard |
| `variables.tf` | Inputs. No default carries an identity-bearing value |
| `main.tf` | Locals, AZ lookup, caller identity. No resources |
| `storage.tf` | The two buckets, and why the licensed one has no durability features |
| `iam.tf` | Two separate roles, least privilege, no IAM users, no access keys |
| `network.tf` | VPC, egress-only security group, and the NAT-Gateway argument |
| `ecr.tf` | Private registry, immutable tags, scan on push |
| `ecs.tf` | Cluster only. No task definition, no service |
| `logging.tf` | Bounded retention; the two rules binding on what may be logged |
| `outputs.tf` | Apply-time values. Several embed an account id |
| `terraform.tfvars.example` | Placeholders only. Copy to the git-ignored `terraform.tfvars` |

---

## The three design choices worth reading before changing anything

### 1. The licensed bucket has no versioning, no Object Lock, no replication, no archival lifecycle

**This is deliberate and it is the opposite of conventional cloud practice.**

The candidate provider's licence requires deleting, within 30 days of termination, every copy of
the data from *"all computer systems you own or operate"* — and termination may be immediate and
without notice. A private AWS account is such a system. Versioning leaves noncurrent versions
behind a delete marker; Object Lock makes deletion *impossible until expiry, by design*;
replication creates a copy elsewhere; archival lifecycles make provable deletion slow and
expensive. Each is a durability feature that defeats a contractual obligation.

**No immutability guarantee is lost; recoverability is deliberately traded away to preserve
complete vendor-data deletion capability.** Those are two different properties, and an earlier
revision of this README ran them together by claiming "nothing is lost", which was too broad.

*Immutability and content identity survive intact.* They come from content-addressed object names
and append-only software rules — already implemented in the A1 kernel, where an artifact is named
by the SHA-256 of its contents and a version is never rewritten. Versioning would be a second,
weaker mechanism for a property the first already guarantees.

*Recoverability does not survive, and that is the cost.* With no versioning, no replication and no
backup:

- an accidental or erroneous deletion **destroys the exact historical payload**, and AWS has
  nothing to restore it from;
- **re-fetching from the provider is not restoration.** It returns the vendor's data *as it
  stands today*, which after a correction or backfill is not byte-identical to what was
  originally received. Under the point-in-time contract that returns a **new** artifact with a
  new hash, not the old one — the very mechanism that makes vendor backfills visible instead of
  silent is what makes a re-fetch fail to reconstitute history;
- re-fetching is only possible at all while the subscription is live.

This is accepted deliberately, and [ADR-0007](../../../docs/decisions/ADR-0007-cloud-first-research-data-plane.md)
records it under *Consequences — negative / accepted costs*. The judgement is that a deletion
obligation which cannot be satisfied is a worse failure than a restore that is unavailable, given
that the data is rented rather than owned. Operational care around deletion, not a durability
feature, is what protects the licensed bucket.

### 2. The security group has no inbound rules, and tasks run in public subnets

A NAT Gateway costs roughly **USD 32/month idle** — nearly twice the entire monthly bill of the
NORMAL scenario below — to make an already-unreachable task unaddressable. A public IP makes a
task *addressable*, not *reachable*: reachability needs an inbound rule, there are none,
security groups are stateful so replies to outbound connections return anyway, and nothing is
listening.

**Conditional on there never being a listener.** If any component ever needs to accept a
connection, replace this with private subnets plus a NAT Gateway, or with VPC endpoints.

### 3. Three roles, and only one of them can destroy anything

| Role | Can | Cannot |
|---|---|---|
| **Execution** — the ECS agent, before the container starts | pull the image, open the log stream | see research data |
| **Task** — the research code itself | read/write both buckets, later read one secret | pull images, write CloudWatch directly, **delete anything** |
| **Deletion** — vendor termination and rehearsals only | list and delete licensed objects and versions, abort multipart uploads, read the bucket's versioning/replication/lifecycle state | read object contents, write anything, touch the control bucket, read a secret |

**The task role deliberately holds no `s3:DeleteObject`.** An earlier revision granted it, arguing
that deletion is a licensing requirement — which is true of *KalpaMani as a system* and does not
follow for a role that runs every ingestion job. Because the licensed bucket has no versioning, no
replication and no backup, that grant meant a bug in routine research code could silently destroy
unrecoverable history. Deleting now requires deliberately assuming a different identity.

**The deletion role cannot reach the control bucket**, so the manifests, lineage and deletion
receipts proving a deletion happened lie outside the reach of the identity performing it. It also
cannot read the objects it deletes — deletion does not require reading the data, and receipt
figures come from listing.

**It is unusable as committed, on purpose.** No ECS task definition exists, no deletion task or
workflow exists, no image exists, and nothing is granted `iam:PassRole` for it — so nothing can
launch anything that runs as this role. Creating that task and granting `PassRole` is a separate
authorization that has not been given.

**No IAM user and no long-lived access key is created anywhere.** The only `"*"` resource in the
configuration is on `ecr:GetAuthorizationToken`, which AWS does not permit to be scoped — one
named action, not a wildcard.

**The task role also has no CloudWatch Logs permissions, and they are not missing.** Under the ECS
`awslogs` driver the agent collects stdout/stderr using the *execution* role. Granting them to the
application as well was redundant, and not harmlessly so: it would let application code call
`PutLogEvents` directly, which is exactly the path by which a vendor payload or a query-string API
key reaches a durable, queryable store. Not holding the permission is a structural barrier behind
the redaction rules.

---

## Cost

### Unit prices

Current **public list prices, `us-east-1`**, exclusive of tax and of the AWS Free Tier. These are
illustrative and **must be re-verified against the official AWS pricing pages at the time apply
is authorized** — they change, and the scenarios below inherit any error in them. The Free Tier
would reduce a first year and is deliberately **not** relied on.

| Resource | Price |
|---|---|
| S3 Standard storage | $0.023 / GB-month (first 50 TB) |
| S3 PUT / COPY / POST / LIST | $0.005 / 1,000 requests |
| S3 GET | $0.0004 / 1,000 requests |
| Fargate vCPU | $0.04048 / vCPU-hour |
| Fargate memory | $0.004445 / GB-hour |
| Fargate Spot | roughly 70% below on-demand, and interruptible |
| Public IPv4 address | $0.005 / hour, per address in use |
| ECR storage | $0.10 / GB-month |
| CloudWatch Logs ingestion | $0.50 / GB |
| CloudWatch Logs storage | $0.03 / GB-month |
| Data transfer OUT to internet | first 100 GB/month free, then $0.09 / GB |
| Data transfer IN | free |
| VPC, subnets, route tables, internet gateway, security groups | no charge |
| ECS cluster, ECR repository, IAM roles | no charge |
| *NAT Gateway — avoided by design* | *$0.045/hour ≈ $32.85/month, plus $0.045/GB* |
| *S3 Gateway VPC endpoint — future option* | *no hourly charge* |
| *Interface VPC endpoint — future option* | *$0.01/hour per AZ, plus $0.01/GB* |

### Scenarios

**LOW — the scaffold applied, dormant.** No data ingested, no task ever run. This is what the
account costs for simply existing in the shape described here.

| Line | Amount |
|---|---|
| S3 (empty), ECR (empty), CloudWatch (empty) | $0.00 |
| VPC, subnets, IGW, security group, ECS cluster, IAM | $0.00 |
| **Total** | **≈ $0.00 / month** |

This is the architecture objective: **near-zero cost while idle.** No always-on instance, no NAT
Gateway, no RDS, no managed analytics platform.

**NORMAL — one provider ingested, periodic research.** ~250 GB stored, 40 Fargate task-hours at
2 vCPU / 8 GB, weekly rebuilds.

| Line | Basis | Amount |
|---|---|---|
| S3 storage | 250 GB | $5.75 |
| S3 PUT-class requests | 300,000 | $1.50 |
| S3 GET requests | 10,000,000 | $4.00 |
| Fargate compute | 40 h × (2 vCPU + 8 GB) | $4.66 |
| Public IPv4 | 40 h | $0.20 |
| ECR storage | 5 GB | $0.50 |
| CloudWatch Logs | 2 GB ingested | $1.06 |
| Data transfer out | under the 100 GB free allowance | $0.00 |
| **Total** | | **≈ $18 / month** |

**HEAVY RESEARCH — large backtests, dense factor panels.** ~1.5 TB stored, 600 vCPU-hours,
substantial scanning and some download to the workstation.

| Line | Basis | Amount |
|---|---|---|
| S3 storage | 1,536 GB | $35.33 |
| S3 PUT-class requests | 3,000,000 | $15.00 |
| **S3 GET requests** | **150,000,000** | **$60.00** |
| Compute, on-demand | 600 vCPU-h + 2,400 GB-h | $34.96 |
| *(same compute on Spot)* | *≈ 70% less* | *($10.49)* |
| Public IPv4 | 300 h | $1.50 |
| ECR storage | 20 GB | $2.00 |
| CloudWatch Logs | 10 GB ingested | $5.30 |
| Data transfer out | 300 GB, 100 free | $18.00 |
| **Total, on-demand** | | **≈ $172 / month** |
| **Total, Spot compute** | | **≈ $148 / month** |

### The two costs that surprise people

**Request charges can exceed storage charges.** At heavy scale above, GET requests cost **$60**
against **$35** of storage. Request cost is driven by *object count*, not byte count: a Parquet
dataset written as millions of small files pays per file on every scan. **Coarse partitioning is
a cost control, not only a performance one** — and it is the single most effective knob on this
bill.

**Downloading the data defeats the point.** Transferring 300 GB out costs $18/month while
storing 1.5 TB costs $35/month. Cloud-first works because compute runs *next to* the data;
routinely pulling datasets down to the laptop reintroduces both the cost and the local copy the
deletion runbook then has to reach.

### Cost knobs

| Knob | Effect |
|---|---|
| Objects per dataset (partition width) | dominates request cost at scale |
| Bytes stored, and how long | linear, and the only cost that persists while idle |
| Fargate vCPU-seconds and GB-seconds | billed per second, one-minute minimum — many tiny tasks are inefficient |
| Spot versus on-demand | ~70% on interruptible batch work |
| Data transferred out to the internet | free to 100 GB, then linear |
| CloudWatch ingestion volume and retention | both bounded here; retention cannot be unbounded |
| ECR image size and count | untagged images expire automatically |

### Explicitly avoided

Always-on EC2 · always-on NAT Gateway · RDS for research files · managed analytics platforms
(Athena, Glue, EMR, Redshift, SageMaker) before a measured workload justifies one · Container
Insights · cross-region replication · Glacier lifecycle transitions.

### A budget alarm is mandatory before real ingestion

**No AWS Budget resource is created here.** A budget alarm requires a notification destination —
an email address or SNS topic — which is personal information and is not committed to a public
repository.

**A budget alarm and a cost anomaly alert are mandatory before any real data ingestion**, and are
part of the same authorization that permits `terraform apply`. The steady-state numbers above are
small; the actual financial risk is a runaway loop, a misconfigured retry storm, or a job that
scans the full dataset on every iteration. A monthly bill is not a control — an alarm is.

---

## Validation

```bash
terraform fmt -check -recursive infra/aws/research-data-plane
terraform -chdir=infra/aws/research-data-plane init -backend=false
terraform -chdir=infra/aws/research-data-plane validate
```

`init -backend=false` and `validate` need no AWS credentials and reach no account. They check
syntax, provider schema conformance and internal references — not that the configuration does
what it claims.

**Applied state — these now act on a real account:**

```
terraform plan     # requires credentials; reads the account and remote state
terraform apply    # CREATES RESOURCES AND SPENDS MONEY
terraform destroy  # DESTROYS THE FOUNDATION — never run without written authorization
```

The foundation apply of 2026-08-27 was authorized for that plan alone. A further `apply` that
adds resources, and any `destroy`, each need their own authorization. Read the plan before
applying it: an unexpected recurring-cost resource, or any destroy action, is a stop condition.

Verify the deployed account at any time with the read-only, identifier-free check:

```
AWS_PROFILE=<pinned profile> python scripts/aws_foundation_verify.py
```

### Current validation status: **VALIDATED**

| | |
|---|---|
| Terraform | **v1.16.0**, windows_amd64 |
| Install location | `.runtime/tools/terraform/bin/` — **portable, git-ignored, session-local `PATH` only.** No machine-wide install, no package manager, nothing added to the global `PATH` |
| Archive checksum | SHA-256 matches the published `terraform_1.16.0_SHA256SUMS` |
| Signature | **Good signature** on the checksum file from HashiCorp Security, key `C874 011F 0AB4 0511 0D02 1055 3436 5D94 72D7 468F` |
| `terraform fmt -check -recursive` | **exit 0** — no file required reformatting |
| `terraform init -backend=false` | **success** — `hashicorp/aws v6.62.0`, signed by HashiCorp |
| `terraform validate` | **Success! The configuration is valid.** |
| Lock file | `.terraform.lock.hcl` generated by `init` and **committed** |

That table records the **pre-apply** validation, performed before the KalpaMani foundation was
applied to the account. It is
retained as-is: it is the evidence that the configuration was reviewed and validated *before* it
was ever pointed at a real account. `plan` and `apply` have since been run — see the status
block at the top of this file — and the wrong-account binding is now enforced in practice rather
than only in `terraform console`.

### What validation does and does not establish

`init -backend=false` and `validate` need no AWS credentials and reach no account. They check
syntax, provider schema conformance and internal references against the real AWS provider schema.

**They do not exercise the input-variable rules.** `terraform validate` does not require values
for variables, so a passing validate is *not* evidence that the wrong-account binding is enforced
— that fires at plan/apply time, which is not authorized here. The validation logic was instead
verified directly by evaluating its expressions in `terraform console` in an empty module:

```
empty list                                -> rejected
"REPLACE-WITH-12-DIGIT-AWS-ACCOUNT-ID"    -> rejected   (the placeholder in the .example)
eleven digits                             -> rejected
thirteen digits                           -> rejected
twelve letters                            -> rejected
exactly twelve digits                     -> accepted
one valid entry plus one malformed entry  -> rejected   (a bad entry fails the whole set)
```

*Written out in words rather than as literals on purpose.* A dummy twelve-digit number in a
committed file is indistinguishable at a glance from a real account id, and it is exactly the kind
of thing that gets copied. The audit's account-id scanner refuses any twelve-digit literal under
`infra/` — it caught this block when it was first written with example numbers in it, which is the
guard working rather than a nuisance.

Neither validate nor console establishes that applying this configuration would produce a working
or correct system. That remains unproven and unauthorized.

---

## Rules for anything committed under this directory

Never committed, under any circumstances:

> AWS account ids · access keys · secret access keys · session tokens · ARNs containing a real
> account id · real bucket names · email addresses · SNS topic ARNs · provider API keys ·
> broker identifiers · account-binding digests · vendor data · `terraform.tfstate` ·
> `terraform.tfstate.backup` · `.terraform/` · `*.tfvars` · `*.tfplan` · crash logs

Only `terraform.tfvars.example` is committed, and it contains placeholders alone — the same rule
`.env.example` follows. `.gitignore` enforces this; the exclusion is a safety control, not
housekeeping.

**Credentials never belong in a `.tfvars` file.** Use an AWS profile, SSO/Identity Center, or
environment variables.
