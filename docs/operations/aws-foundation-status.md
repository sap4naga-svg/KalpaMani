# AWS Research Foundation — Provision Status

**Status: PROVISIONED (2026-08-27).**

The private AWS foundation adopted by
[ADR-0007](../decisions/ADR-0007-cloud-first-research-data-plane.md) has been applied. The
Terraform in [`infra/aws/research-data-plane/`](../../infra/aws/research-data-plane/) is no
longer a description of something that does not exist; it describes something that does.

**This document deliberately contains no identifiers.** No AWS account id, no bucket name, no
ARN, no repository URL, no region-qualified resource name, no email address. Those values exist
only in the git-ignored `terraform.tfvars`, in remote state, and in the account itself. The
verification below reports verdicts; the values behind them are not publishable, which is the
entire reason the two are separated.

---

## What was provisioned

| | |
|---|---|
| AWS account | **EXISTING** — pre-dates this work; **no account was created here** |
| Account configured for the foundation | **2026-08-27** |
| Provision date | **2026-08-27** |
| Region | **us-east-1** |
| Terraform | **v1.16.0** |
| AWS provider | **hashicorp/aws v6.62.0** (from the committed `.terraform.lock.hcl`) |
| Resources created | **36** — `36 added, 0 changed, 0 destroyed` |
| Remote state | **ACTIVE** — private S3 backend, SSE-S3, versioning enabled |
| State locking | **S3 native lockfile** (`use_lockfile`); **no DynamoDB table** |
| Monthly cost budget | **configured** — USD 50 alert threshold, 4 notifications |
| Cost anomaly detection | **configured** — monitor + subscription |

The 36 resources are exactly the reviewed ADR-0007 foundation and nothing else:

```
2 S3 buckets + 12 bucket security/encryption/versioning/lifecycle/policy resources
1 VPC · 1 internet gateway · 2 public subnets · 1 route table · 2 associations
1 security group with ZERO inbound rules · 3 egress rules (HTTPS, DNS udp, DNS tcp)
1 private ECR repository · 1 ECR lifecycle policy
1 ECS cluster · 1 capacity-provider configuration
1 CloudWatch log group
3 IAM roles + 3 role policies (execution · task · licensed-data deletion)
```

The plan contained **no destroy action** and **no resource type outside that list**. In
particular it created no NAT Gateway, no EC2 instance, no RDS instance, no ECS service, no task
definition, no load balancer, no EFS, no AWS Batch, no SageMaker, no Redshift, no Glue, no
Athena, no OpenSearch, no IAM user, no access key and no secret.

### Cost posture

**There is no fixed always-on hourly compute, network or database cost** — no NAT Gateway, no
load balancer, no DynamoDB lock table, no ECS service, no EC2 instance, no RDS instance. Charges
accrue only from *usage*: a Fargate task running, an image stored in ECR, logs ingested, objects
stored in S3.

Idle cost is expected to be **near zero, not literally guaranteed zero**. The Terraform state
bucket holds state and version history, and every plan, apply and lock acquisition issues S3
requests; those are usage-based charges, tiny but real. Calling the foundation cost-free at
rest would be the wrong claim, so this document does not make it.

The USD 50 budget is an **alert threshold, not a spending authorization**. CLAUDE.md §4.21 is
unchanged: cloud spend beyond this idle foundation requires its own written authorization.

---

## Verification

`scripts/aws_foundation_verify.py` asks AWS what is actually deployed rather than reading the
Terraform back. It is read-only — every call is a describe/get/list or an IAM policy
*simulation*, which evaluates a permission without exercising it.

**It fails closed.** An absence is only accepted when AWS returns a *specific, declared* error
code for that call; every other failure — access denied, an expired session, throttling, a
network fault — is a verification FAILURE, never an absence. IAM decisions are read the same
way: `allowed` means allowed, `implicitDeny`/`explicitDeny` mean denied, and anything else,
including a simulation that did not run, fails. A simulation that failed must never be counted
as proof that a permission is denied.

Order is itself a control. The identity gate runs **before** any remote state is read:

```
AWS_PROFILE pinned  ->  sts:GetCallerIdentity vs the local account binding
                    ->  Terraform remote state  ->  foundation verification
```

A stale profile, a missing binding, an expired session or a mismatched account refuses
immediately. **Zero unresolved AWS calls and zero unresolved IAM decisions** were recorded in
the run below.

**Result: PASS — 66 of 66 checks.**

| Group | Result |
|---|---|
| **Identity gate** — profile pinned, STS account matches the local binding | **PASS** |
| **Terraform state backend** — local backend file, region, `encrypt`, `use_lockfile` | **PASS** |
| **State bucket** — exists, BPA all ON, ACLs disabled, AES256, **versioning ENABLED**, not public, no cross-account policy | **PASS** |
| Licensed bucket — exists, private, BPA all ON, ACLs disabled, TLS-only policy, AES256 | **PASS** |
| Control bucket — exists, private, BPA all ON, ACLs disabled, TLS-only policy, AES256 | **PASS** |
| Licensed bucket versioning **disabled**; Object Lock, replication, archival transitions **absent** | **PASS** |
| Licensed bucket aborts incomplete multipart uploads | **PASS** |
| Control bucket versioning **enabled** | **PASS** |
| VPC, expected subnets, **zero inbound** security-group rules, egress present | **PASS** |
| No NAT Gateway, no load balancer | **PASS** |
| ECR private, IMMUTABLE tags, scan-on-push, AES256, no cross-account policy, **empty** | **PASS** |
| ECS cluster ACTIVE; no service, no running/pending task, no task-definition family | **PASS** |
| CloudWatch retention bounded | **PASS** |
| Routine task role **cannot** DeleteObject / DeleteObjectVersion (licensed or control) | **PASS** |
| Deletion role **can** delete licensed; **cannot** Get, **cannot** Put, **cannot** reach control | **PASS** |
| **No `iam:PassRole`** on the deletion role from any role | **PASS** |
| Task role cannot read any secret (`provider_secret_arns` empty) | **PASS** |
| No IAM user, no IAM access key, no root access key, root MFA enabled | **PASS** |

The IAM group is the one worth reading twice. ADR-0007 and `iam.tf` claim a separation — routine
research code holds no destructive authority over a store with no versioning, no replication and
no backup — and the simulation confirms AWS will actually decide it that way, including the
effect of anything attached outside the configuration.

### Synthetic storage smoke test

**Result: PASS.** A hand-authored, fictitious payload of a few bytes — **no vendor data, no
provider contacted** — was uploaded to a test prefix in the licensed bucket, retrieved, verified
by SHA-256 round trip, deleted, and confirmed absent. Both **research-data** buckets — licensed
and control — are empty afterwards.

That scope is deliberate. The separately bootstrapped **Terraform state bucket is not empty and
must not be**: it holds remote state, its version history and lock objects. It is
infrastructure-control data, not research data, and takes the opposite durability posture.

**Which identity deleted, and why it was not the deletion role.** The deletion role is not
"unassumable" — its trust policy deliberately admits `ecs-tasks.amazonaws.com`. The precise
property is narrower: **no human can directly assume it, no deletion task definition exists, no
deletion workflow exists, and no authorized principal holds `iam:PassRole` for it**, so no current
path can launch an ECS task running as it. That is deliberate. Using it here would have
required creating exactly the deletion workflow and `PassRole` grant that are **not authorized**,
so the delete ran as the **operator**: the human's temporary Identity Center session. No IAM
policy was weakened or broadened for the smoke test.

That is an operator-path delete. It is **not** the 15-step vendor-termination deletion rehearsal
in [vendor-data-cloud-deletion.md](../runbooks/vendor-data-cloud-deletion.md), which remains a
**separate future task and has never been run**.

---

## Access and credentials

| | |
|---|---|
| Root MFA | **enabled** |
| Root access keys | **NONE** |
| IAM users | **NONE** |
| IAM access keys | **NONE** |
| Administrative access | **IAM Identity Center**, temporary federated session |
| Local profile | a single named SSO profile; configuration lives outside Git |

No long-lived credential exists anywhere in the account. Every human action runs under a
short-lived Identity Center session, and every workload identity is a role.

The account binding is enforced rather than trusted: `allowed_account_ids` has no default, and the
AWS provider refuses to act if resolved credentials belong to any other account. This matters
concretely on the provisioning workstation, which also holds unrelated AWS profiles for a
different project — the same failure mode CLAUDE.md §3 guards against for GitHub.

---

## What this does NOT change

Provisioning a platform is not permission to use it. **Every one of the following remains exactly
as it was before this work**, and each still requires its own explicit written authorization
under CLAUDE.md §8:

```
provider selected            NONE          -- G1 OPEN
provider account / trial     NONE          -- not authorized
provider credential          NONE          -- G3 OPEN
vendor data retrieved        NONE
SEC / EDGAR ingestion        NONE
research container image     NOT BUILT     -- the ECR repository is empty
ECS / Fargate task run       NONE          -- no task definition exists
ResearchObjectStore          NOT IMPLEMENTED
A2 / A3 - Phase 3B / 3C / 3D NOT STARTED / NOT AUTHORIZED
broker / LEAN activity       NONE
```

| | |
|---|---|
| **G1–G7 decision gates** | **OPEN** — none resolved by this work |
| **ADR-0005** | **PROPOSED** |
| **Phase 3** | **NOT COMPLETE** |
| **Live trading** | **HARD-DISABLED** |

The licensed bucket holds nothing. It is a correctly-configured empty container, and the
deletion-first posture it was built with is what keeps a future vendor obligation satisfiable.

---

## Next authorized task

**Phase 3 — Sharadar free-sample qualification.** That is a separate task with its own
authorization; nothing in this document begins it.
