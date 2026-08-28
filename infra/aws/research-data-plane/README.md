# KalpaMani — Private AWS Research Data Plane (Terraform)

## STATUS: **DESCRIPTION ONLY — NEVER APPLIED**

```
AWS resources created    NONE
AWS spend incurred       NONE
AWS account              NOT CREATED
terraform apply          NOT AUTHORIZED
terraform state          DOES NOT EXIST
provider credentials     NONE
vendor data              NONE
```

This directory contains an **infrastructure description**. It has not been applied, no state
file exists, and no AWS account has been created. Running `terraform apply` requires its own
explicit written authorization, separate from and later than
[ADR-0007](../../../docs/decisions/ADR-0007-cloud-first-research-data-plane.md).

**Authority:** [ADR-0007](../../../docs/decisions/ADR-0007-cloud-first-research-data-plane.md) ·
[ADR-0005](../../../docs/decisions/ADR-0005-point-in-time-data-architecture.md) ·
[CLAUDE.md](../../../CLAUDE.md)
**Deletion procedure:** [vendor-data-cloud-deletion.md](../../../docs/runbooks/vendor-data-cloud-deletion.md)

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

**Nothing is lost.** Bronze immutability comes from content-addressed object names and
append-only software rules — already implemented in the A1 kernel, where an artifact is named by
the SHA-256 of its contents and a version is never rewritten. Versioning would be a second,
weaker mechanism for a property the first already guarantees.

### 2. The security group has no inbound rules, and tasks run in public subnets

A NAT Gateway costs roughly **USD 32/month idle** — nearly twice the entire monthly bill of the
NORMAL scenario below — to make an already-unreachable task unaddressable. A public IP makes a
task *addressable*, not *reachable*: reachability needs an inbound rule, there are none,
security groups are stateful so replies to outbound connections return anyway, and nothing is
listening.

**Conditional on there never being a listener.** If any component ever needs to accept a
connection, replace this with private subnets plus a NAT Gateway, or with VPC endpoints.

### 3. Two roles, no users, no access keys

The execution role pulls the image and opens a log stream; it never sees research data. The task
role reaches the buckets; it cannot pull images. No IAM user and no long-lived access key is
created anywhere. The only `"*"` resource in the configuration is on
`ecr:GetAuthorizationToken`, which AWS does not permit to be scoped — one named action, not a
wildcard.

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

**Never run against a real account:**

```
terraform plan     # requires credentials; reads the account
terraform apply    # CREATES RESOURCES AND SPENDS MONEY — NOT AUTHORIZED
```

**Current validation status: static review only.** Terraform is not installed on the development
workstation, so `fmt`, `init` and `validate` have not been run against this configuration. It has
been reviewed by reading. Installing Terraform and running the three commands above is the first
step of any future authorized work here.

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
