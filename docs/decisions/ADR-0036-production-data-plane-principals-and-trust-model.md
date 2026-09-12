# ADR-0036 — Production data-plane principals: the acquisition actor, the research-build actor, and how ephemeral compute assumes them

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0036 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **architecture and acceptance tests only**.

**Nothing was run to produce this design.** No AWS CLI or SDK call, no STS, SSO, IAM, Identity Center,
Secrets Manager or S3 operation, no Terraform command of any kind, no policy simulation, no provider
request, no private-data read, no ingestion, no backtest and no broker activity. Every AWS behaviour
cited below is public AWS documentation; every repository fact is the tracked tree at the merge of PR #92.

**Accepting this ADR authorizes no implementation and no execution.** It authorizes no Terraform
declaration, plan or apply, no IAM or Identity Center mutation, no ECS resource, no profile
materialization, no binding materialization, no ingestion, no build, no read of the licensed store and no
CONTROL publication. **Architecture acceptance, offline Terraform declaration, application, profile and
binding materialization, and the first bounded ingestion are five separate gates**, and this decision
opens only the first — exactly as [ADR-0021](ADR-0021-qualification-runtime-principal-and-trust-model.md)
did for the qualification actors.

---

## 1. Context

[ADR-0035](ADR-0035-initial-breakout-long-research-dataset-ingestion-design.md) §3.10 named the two
principals the production data plane needs and deliberately left them undesigned:

| Principal | May | May not |
|---|---|---|
| **production acquisition actor** | one governed secret retrieval; conditional `PutObject` under the production Bronze prefixes and the claim namespace | any `GetObject`, `HeadObject`, listing, delete, copy, CONTROL, qualification prefixes |
| **research-build actor** | exact `GetObject` on production Bronze; `PutObject` of Silver and Gold under licensed prefixes; read of its own Silver/Gold; publication of manifests to CONTROL **only once CONTROL is undeferred** | any provider or credential access; delete; listing beyond its own build outputs; the qualification prefixes |

What exists and is reused: the foundation account and licensed bucket
([ADR-0007](ADR-0007-cloud-first-research-data-plane.md); deletion-first, no versioning, SSE-S3, zero
inbound rules, outbound HTTPS only, ephemeral task model); the Identity Center human-authentication root,
one-hour permission-set sessions and the account-plus-role-prefix identity gate
([ADR-0021](ADR-0021-qualification-runtime-principal-and-trust-model.md),
[ADR-0022](ADR-0022-qualification-permission-set-name-limit.md)); the write-only publication surface and
fail-closed collision policy ([ADR-0019](ADR-0019-write-only-acquisition-collision-policy.md)); the
private runtime and environment bindings and their trust boundary
([ADR-0023](ADR-0023-private-runtime-binding-for-the-licensed-bucket.md),
[ADR-0024](ADR-0024-governed-qualification-environment-binding-source.md),
[ADR-0025](ADR-0025-private-runtime-binding-for-the-combined-assessment.md)); the assessment-only exact
read surface (ADR-0018 §10.2, `qualify/sharadar/read.py`); and the deletion role that can list and delete
licensed objects but never read them.

What is deliberately **not** reused: the two qualification permission sets, their policies, their
profiles, their bindings, their prefixes and their accounting. Qualification is a closed, audited package;
production gets its own principals and its own accounting, and neither may reach the other's objects.

---

## 2. Decision

### 2.1 Two actors, four principals

**Each actor has a human principal and a compute principal, and they carry the same customer-managed
policy.** The human principal is an Identity Center permission set assigned to the governed operator group,
for bootstrap and for bounded owner-run operations; the compute principal is an ECS task role that only an
ECS task in this account can assume. No IAM user, no access key, no cross-account principal, no
`sts:AssumeRole` from application code.

| Actor | Customer-managed policy | Identity Center permission set (≤ 32 chars) | Governed profile | ECS task role |
|---|---|---|---|---|
| **production acquisition** | `kalpamani-production-acquisition` | `KalpaManiProductionAcquire` (26) | `kalpamani-production-acquisition` | `kalpamani-production-acquire-task` |
| **research build** | `kalpamani-research-build` | `KalpaManiResearchBuild` (22) | `kalpamani-research-build` | `kalpamani-research-build-task` |

**Session requirements.** Permission-set sessions are bounded to **one hour** (`PT1H`), as for the
qualification actors; a run that cannot finish inside the session it began in is refused at its next
identity-bearing step, never extended. Task-role credentials are issued by the ECS agent for the life of
one task and are bounded by the task's own compiled deadline; a task that outlives its deadline is stopped
by the runner, not renewed.

### 2.2 The acquisition actor — bounded secret access, write-only Bronze

```text
ALLOW  secretsmanager:GetSecretValue      on exactly ONE secret ARN: the production Sharadar credential
                                          (its own secret; the qualification secret is a different resource)
ALLOW  s3:PutObject                       licensed/bronze/sharadar/<dataset>/objects/sha256/*
                                          licensed/bronze/sharadar/<dataset>/acquisitions/*
                                          licensed/bronze/sharadar/_indexes/*          (the run locator, 2.4)
                                          licensed/bronze/_acquisition_claims/*
       with conditions                    s3:x-amz-server-side-encryption = AES256
                                          s3:if-none-match = *   (conditional-write enforcement, see 2.6)
DENY   s3:GetObject, s3:GetObjectVersion, s3:GetObjectAttributes, s3:GetObjectVersionAttributes,
       s3:ListBucket, s3:ListBucketVersions, s3:DeleteObject*, s3:PutObjectAcl, s3:CopyObject-shaped puts
       (s3:PutObject with x-amz-copy-source), s3:RestoreObject, s3:PutObjectRetention, s3:PutObjectLegalHold
       on the licensed bucket and every object in it
DENY   every s3 action on the CONTROL bucket and on the Terraform state bucket
DENY   s3:*  on licensed/qualification/* and licensed/bronze/sharadar/*/qualification/*
DENY   secretsmanager:* except the one GetSecretValue above; no ListSecrets, DescribeSecret, PutSecretValue
DENY   iam:*, sts:AssumeRole, ec2:*, ecs:RunTask, ssm:* except the one binding parameter read of 2.5
```

The actor is **write-only** exactly as ADR-0019 requires: it cannot read what it wrote, cannot list, cannot
delete, cannot copy. Its one capability beyond writing is one secret; it has no other.

**Network.** The acquisition task runs in a private subnet whose egress allows HTTPS to the provider's
pinned origin and to the S3 gateway endpoint, and nothing else; no inbound rule exists.

### 2.3 The research-build actor — exact reads, licensed Silver/Gold writes, no secret

```text
ALLOW  s3:GetObject                       licensed/bronze/sharadar/<dataset>/objects/sha256/*
                                          licensed/bronze/sharadar/<dataset>/acquisitions/*
                                          licensed/bronze/sharadar/_indexes/*
                                          licensed/silver/*, licensed/gold/*, licensed/manifests/*   (its own outputs)
ALLOW  s3:PutObject                       licensed/silver/*, licensed/gold/*, licensed/manifests/*
       with conditions                    s3:x-amz-server-side-encryption = AES256
                                          s3:if-none-match = *
DENY   s3:ListBucket, s3:ListBucketVersions, s3:DeleteObject*, s3:PutObjectAcl, copy-shaped puts,
       s3:RestoreObject, s3:PutObjectRetention, s3:PutObjectLegalHold   on the licensed bucket
DENY   s3:GetObject on licensed/bronze/_acquisition_claims/*   (claims are validated from the locator, never read)
DENY   every s3 action on the CONTROL bucket and on the Terraform state bucket
DENY   s3:*  on licensed/qualification/* and licensed/bronze/sharadar/*/qualification/*
DENY   secretsmanager:*  (no secret of any kind), iam:*, sts:AssumeRole, ec2:*, ecs:RunTask
```

**Structural provider isolation.** The build task runs in a private subnet with **no NAT and no internet
egress** — only the S3 gateway endpoint (and the SSM/KMS interface endpoints of 2.5). It therefore cannot
reach the provider even if code tried to, which is the same property ADR-0018 §10.3 gave the assessment
actor, now held by the network as well as by IAM. **Manifests stay LICENSED while CONTROL is deferred**:
they carry no vendor row, but the CONTROL bucket is not written by anyone until CONTROL is undeferred by
its own decision, and the build actor holds no CONTROL grant.

### 2.4 Exact object references without listing — the production run locator

The build actor may not list. It learns exactly which objects to read the way the assessment learns it
(ADR-0018 §7): from **one object addressed by name**.

- Every acquisition run publishes, **last** and conditionally, a **run locator** at
  `licensed/bronze/sharadar/_indexes/<run-id>.json` (≤ 256 KiB, closed schema, no free text): for every
  completed request, the exact payload key, payload digest and byte count, the acquisition-record key,
  digest and byte count, the request coordinates, the acquisition mode, and the run's start and completion
  instants; plus the plan digest and the slice it covered.
- The build actor derives the locator key from a **run identity the owner supplies** through its private
  binding input (2.5), retrieves it by exact name, validates its closed schema, and then reads **only the
  objects it names**, verifying each object's full-object SHA-256 and byte count before parsing — the
  assessment's exact-read discipline (`read_exact`) applied to production.
- A missing, malformed, oversize or `PARTIAL` locator refuses the build for that run; there is no fallback
  that reconstructs by listing, probing or guessing.
- The owner-only slice ledger of ADR-0035 §3.1 is reconciled against the locators the build actor reads;
  a disagreement is a BLOCKING finding.

The locator prefix is inside `bronze/`, so prefix-based deletion already covers it, and it is written by
the acquisition actor's existing write-only grant.

### 2.5 Bindings — validated the same way, delivered two ways

**Humans.** Each actor has its own private runtime binding under the ADR-0023 trust boundary — a third
and fourth artifact, never the qualification ones:

```text
contract_id   kalpamani-production-acquisition-runtime-binding/v1
              kalpamani-research-build-runtime-binding/v1
fields        schema_version · binding_kind · contract_id · aws_partition · aws_region ·
              target_account_id · <actor>_profile · licensed_bucket_name · provenance{...}
variable      KALPAMANI_PRODUCTION_ACQUISITION_RUNTIME_BINDING_FILE
              KALPAMANI_RESEARCH_BUILD_RUNTIME_BINDING_FILE
```

The field sets differ by exactly the profile field name, so neither loads as the other, and neither loads
as a qualification binding. Same absolute-path-only selection, same containment beneath the private root,
same owner-only ACL, same before-and-after identity check, same closed schema, same "loading is not
identity proof". The research-build binding additionally names, in a separate owner-only **build input**
document, the run identities to build from — private evaluation information that never enters argv.

**Compute.** A container has no private root and no Windows ACL, so a task receives its binding from a
**per-actor SSM `SecureString` parameter**, readable by exactly that task role (an exact-ARN
`ssm:GetParameter` grant plus a parameter policy naming that role) and encrypted with the account's KMS
key. The **same loader** validates the document — schema, kind, contract, partition, region, profile,
account grammar, bucket grammar, provenance — with the filesystem clauses replaced by two that the platform
supplies: the parameter's ARN is compiled into the task definition, and the decrypting role is the task's
own. No environment variable carries a bucket or an account, and no task definition embeds one.

**Identity proof is unchanged in kind and extended in shape.** Every run performs one
`sts:GetCallerIdentity` and compares the exact bound account and the actor's role name against a closed
grammar: for a human, `AWSReservedSSO_<permission-set>_<suffix>`; for a task,
`arn:<partition>:sts::<account>:assumed-role/<task-role-name>/<task-id>` with the exact task-role name.
A credential resolving to the other actor, to a qualification actor, to the foundation profile or to any
default chain refuses before any S3 or secret operation.

### 2.6 Prefix isolation and immutable-write controls

| Control | Mechanism | Layer |
|---|---|---|
| production never touches qualification | explicit `Deny` on `licensed/qualification/*` and `licensed/bronze/sharadar/*/qualification/*` in both production policies; the qualification policies gain nothing | IAM |
| acquisition cannot reach Silver/Gold | no `PutObject` grant outside Bronze prefixes; explicit `Deny` on reads everywhere | IAM |
| build cannot write Bronze or claims | no `PutObject` grant on `bronze/*`; explicit `Deny` on claim reads | IAM |
| no overwrite | every `PutObject` is conditional (`IfNoneMatch="*"`), fail-closed on 412 (ADR-0019); **enforced in policy** by requiring the `s3:if-none-match` condition key on every production `PutObject` grant — an unconditional put is denied before the bucket sees it. *The condition key is to be verified against the pinned provider and API version at the Terraform gate; if it is unavailable, the invariant remains an application invariant with a static test, and this ADR says so rather than claiming enforcement it cannot prove.* | IAM + application |
| no delete, no copy, no ACL, no retention change | explicit `Deny` for both actors; deletion stays with the separately roled deletion path | IAM |
| no CONTROL | explicit `Deny` on the CONTROL bucket for both actors while CONTROL is deferred | IAM |
| no versioning to absorb a mistake | the bucket stays deletion-first (ADR-0007); an overwrite would be destructive, which is why the conditional write and the policy condition both exist | bucket |
| output redaction | both runners print allowlisted sentences and integer counts only; CloudWatch log groups carry the same output and nothing else, with a compiled retention; no vendor row, key, digest, subject or identifier reaches a log | application |

### 2.7 How ephemeral compute assumes each role

```text
launch     owner-run  ecs:RunTask  under a separately gated launcher permission set (KalpaManiTaskLauncher)
           holding iam:PassRole for exactly the two task roles and nothing else; one task per run;
           no service, no schedule, no scaling group -- a task that is not launched does not exist
task       ECS Fargate; task definition per actor pinned to an ECR image digest; task role = the actor's
           role; execution role = image pull + log write only; deadline = the runner's compiled deadline
trust      each task role trusts ecs-tasks.amazonaws.com only, with aws:SourceAccount = the governed
           account and aws:SourceArn scoped to this account's ECS -- no human and no other service can
           assume it, and no authorized principal but the launcher holds iam:PassRole for it
identity   the runner's first act is the identity gate of 2.5 against the task-role grammar
network    acquisition subnet: provider origin + S3 endpoint egress; build subnet: S3 endpoint only
end        the task exits with the runner's closed exit code; nothing persists on the task's filesystem
```

The pattern is the one ADR-0007's deletion role already uses in reverse: a role that only a task can
assume is inert until a task exists, and a task cannot exist until a separately authorized principal
passes the role. **Launcher permission set, task definitions, images and subnets are each infrastructure
gates**, not consequences of accepting this ADR.

### 2.8 Deletion responsibilities

Unchanged in principle, widened in scope. The deletion role can list and delete under `bronze/`,
`silver/`, `gold/`, `manifests/` and `qualification/`, and cannot read any of them. The cloud-deletion
runbook gains `bronze/sharadar/_indexes/`, `silver/`, `gold/` and `manifests/` as expected prefixes so
their first appearance is not a finding. Neither production actor can delete anything. **The 30-day
obligation covers every object both actors write**, and a run locator may be absent — the runbook never
depends on one to discover licensed objects.

---

## 3. Acceptance tests

Two layers, and the layer is stated on every test.

**Offline, before any apply (implementable at the Terraform gate):**

| # | Test |
|---|---|
| A-1 | the two policy documents, parsed as JSON: acquisition grants no `s3:Get*`, no `s3:List*`, no `s3:Delete*`; build grants no `secretsmanager:*`; both carry explicit `Deny` on qualification prefixes, the CONTROL bucket and the state bucket |
| A-2 | every `s3:PutObject` `Allow` in both policies carries the SSE and `s3:if-none-match` conditions |
| A-3 | permission-set names are ≤ 32 characters under the pinned provider's validator (ADR-0022's guard, reused) |
| A-4 | task-role trust policies name only `ecs-tasks.amazonaws.com` with source-account and source-ARN conditions; no `AWS` principal |
| A-5 | the identity gate accepts exactly the two human role-prefix shapes and the two task-role names, per actor, and refuses the other actor's, the qualification actors', the foundation profile's and a default-chain identity (synthetic fixtures) |
| A-6 | the two binding contracts refuse each other and refuse every qualification binding on the field set; the SSM-delivered document passes the same parser |
| A-7 | `terraform validate` in an isolated external copy under the pinned provider; no repository directory initialized |
| A-8 | static guards: the acquisition runner imports no read surface; the build runner imports no credential, secrets boundary or transport |

**Live, only under the application gate and its own authorization (permitted / denied matrix, one
`SimulatePrincipalPolicy` or one real operation per cell, each counted):**

| Actor | Permitted — must succeed | Denied — must be refused |
|---|---|---|
| acquisition (human and task) | `GetSecretValue` on the one secret; conditional `PutObject` to each production Bronze prefix and to `_indexes/` | `GetObject` on its own Bronze write; `ListBucket`; `DeleteObject`; `PutObject` to `silver/`, `gold/`, `manifests/`, any qualification prefix, the CONTROL bucket; unconditional `PutObject`; `GetSecretValue` on the qualification secret; `DescribeSecret` |
| build (human and task) | exact `GetObject` on a Bronze payload, record and locator; conditional `PutObject` to `silver/`, `gold/`, `manifests/`; `GetObject` on its own output | `GetSecretValue` on any secret; `ListBucket`; `GetObject` on a claim; `PutObject` to `bronze/*`; `DeleteObject`; any qualification prefix; the CONTROL bucket; unconditional `PutObject`; any provider-origin network call from the build subnet (must time out or be refused at the network layer) |
| qualification actors | unchanged | any production prefix (`bronze/sharadar/*` outside `qualification/`, `_indexes/`, `silver/`, `gold/`, `manifests/`) |
| deletion role | list and delete under the widened prefixes | `GetObject` anywhere |

A cell that cannot be exercised is recorded as not exercised, never as passed.

---

## 4. Consequences

- The ingestion design of ADR-0035 gains the principals it named, in a form the accepted trust model
  already knows how to build and verify; nothing about ADR-0035's data design changes.
- **Four new gates follow**: offline Terraform declaration (policies, permission sets, task roles, SSM
  parameters, subnets, launcher set); application with independent post-apply verification; profile and
  binding materialization for the two human principals; and the first bounded ingestion under ADR-0035
  §5. The live acceptance matrix belongs to the application gate.
- The qualification package is untouched: no policy, permission set, profile, binding, prefix or test of it
  changes, and both production policies deny its prefixes explicitly.
- CONTROL stays deferred; manifests are LICENSED until a separate decision undefers it.
- The immutable-write claim is stated at two strengths on purpose — application invariant now,
  policy-enforced if the condition key verifies at the Terraform gate — so the acceptance test A-2 either
  proves the stronger claim or the documents fall back to the weaker one explicitly.

---

## 5. Rejected alternatives

- **One production actor for acquisition and build.** Rejected: a principal holding both the provider
  secret and object-read authority could exfiltrate the licensed store — the compromise argument of
  ADR-0018 §10.3, restated for production.
- **Reuse the qualification permission sets with wider grants.** Rejected: the qualification accounting is
  closed and audited; widening it would rewrite what those principals were verified to be.
- **Let the build actor list the Bronze prefix.** Rejected: listing is enumeration of what a vendor sent;
  a locator addressed by name gives exact references without it.
- **Deliver task bindings through task-definition environment variables.** Rejected: a bucket and an
  account in a task definition are a private value in an infrastructure document; a KMS-encrypted parameter
  with an exact-role read is the compute analogue of the ACL-protected file.
- **Give the launcher permission set `iam:PassRole` on `*`.** Rejected: it would let any task run as any
  role; two exact ARNs and nothing else.
- **Long-lived compute (a service or scheduled task).** Rejected by ADR-0007: ephemeral one-off tasks, no
  always-on server; a run that nobody launched must not happen.
- **Claim policy-enforced immutability without verifying the condition key.** Rejected: an enforcement
  claim the pinned provider cannot express would be documentation drift from the first apply.

---

## 6. Status of everything else

```text
this ADR:                                     PROPOSED / NO AUTHORITY WHILE ITS PR IS OPEN
ADR-0034 (partial G1):                        ACCEPTED / IN FORCE -- PR #92 merged
ADR-0035 (ingestion design):                  ACCEPTED / IN FORCE -- PR #92 merged, dependent on ADR-0034
G1 — tickers, stocks; actions restricted:     DECIDED / IN FORCE (ADR-0034); OPEN for every other domain
G2:                                           OPEN -- criteria ADR-0035 G2-A ... G2-H
production policies / permission sets /
  task roles / SSM parameters / launcher:      DESIGNED HERE -- NOT DECLARED, NOT APPLIED, NOT AUTHORIZED
governed production profiles and bindings:    NOT MATERIALIZED / NOT AUTHORIZED
production run locator:                       DESIGNED -- NOT IMPLEMENTED
first bounded ingestion:                      NOT AUTHORIZED / NOT RUN
qualification principals and artifacts:       UNCHANGED / ISOLATED
CONTROL:                                      DEFERRED
Phase 3:                                      NOT COMPLETE
live trading:                                 HARD-DISABLED
```

**This ADR supersedes no earlier decision and amends no earlier ADR document.** It designs, under the
accepted trust model, the two principals ADR-0035 §3.10 named and left to a later gate, and it names the
gates that follow it.
