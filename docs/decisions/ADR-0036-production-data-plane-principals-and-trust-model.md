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
cited below is public AWS documentation (listed in §6); every repository fact is the tracked tree at the merge of
PR #92, including the foundation's own network, execution-role and task-role declarations under
`infra/aws/research-data-plane/`.

**Accepting this ADR authorizes no implementation and no execution.** It authorizes no Terraform
declaration, plan or apply, no IAM or Identity Center mutation, no bucket-policy change, no ECS, VPC-endpoint,
KMS or SSM resource, no profile materialization, no binding or input materialization, no ingestion, no build,
no read of the licensed store and no CONTROL publication. **Architecture acceptance, offline Terraform declaration, application, profile and
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
data-plane policy.** The human principal is an Identity Center permission set assigned to the governed operator
group, for bootstrap, input materialization, verification and bounded owner-run operations; the compute
principal is an ECS task role that only an ECS task in this account can assume. No IAM user, no access key,
no cross-account principal, no `sts:AssumeRole` from application code.

| Actor | Customer-managed data-plane policy | Identity Center permission set (≤ 32 chars) | Governed profile | ECS task role |
|---|---|---|---|---|
| **production acquisition** | `kalpamani-production-acquisition` | `KalpaManiProductionAcquire` (26) | `kalpamani-production-acquisition` | `kalpamani-production-acquire-task` |
| **research build** | `kalpamani-research-build` | `KalpaManiResearchBuild` (22) | `kalpamani-research-build` | `kalpamani-research-build-task` |

**Two policy layers per principal, kept apart on purpose.** The *data-plane policy* (2.2, 2.3) is attached to
both the permission set and the task role of its actor and governs S3 and the secret. A *bootstrap policy*
(2.5) is attached **only** to the principal that needs it: the task role gets the task-only binding-read
statements; the permission set gets the human-only input-materialization statements. Neither bootstrap policy
is attached to the other kind of principal, so a task can never materialize an input and a human profile
never reads a task binding.

**The foundation's own task role is not one of these principals.** The research data plane already declares
a role (`<prefix>-task`, ADR-0007) that can list and read both buckets, write both, and — when a secret ARN is
supplied — read a provider secret. That is exactly the combination this decision refuses to give any one
principal. **Neither production actor uses it, no launcher may pass it, and its narrowing or retirement is
a separate decision under ADR-0007** — this ADR neither widens nor edits it.

**Session requirements.** Permission-set sessions are bounded to **one hour** (`PT1H`), as for the
qualification actors; a run that cannot finish inside the session it began in is refused at its next
identity-bearing step, never extended. Task-role credentials are issued by the ECS agent for the life of one
task and are bounded by the task's own compiled deadline; a task that outlives its deadline is stopped by the
runner's own exit, never renewed.

### 2.2 The acquisition actor — bounded secret access, write-only Bronze

```text
ALLOW  secretsmanager:GetSecretValue      on exactly ONE secret ARN: the production Sharadar credential
                                          (its own secret; the qualification secret is a different resource)
ALLOW  s3:PutObject                       licensed/bronze/sharadar/<dataset>/objects/sha256/*
                                          licensed/bronze/sharadar/<dataset>/acquisitions/*
                                          licensed/bronze/sharadar/_indexes/*          (the run locator, 2.4)
                                          licensed/bronze/_acquisition_claims/*
       with conditions                    StringEquals s3:x-amz-server-side-encryption = AES256
                                          Null         s3:if-none-match = false          (2.7)
                                          Bool         s3:ObjectCreationOperation = true (2.7: no multipart)
                                          Null         s3:x-amz-copy-source = true       (2.7: no copy-shaped put)
DENY   s3:GetObject, s3:GetObjectVersion, s3:GetObjectAttributes, s3:GetObjectVersionAttributes,
       s3:ListBucket, s3:ListBucketVersions, s3:ListBucketMultipartUploads, s3:ListMultipartUploadParts,
       s3:DeleteObject*, s3:PutObjectAcl, s3:RestoreObject, s3:PutObjectRetention, s3:PutObjectLegalHold,
       s3:AbortMultipartUpload            on the licensed bucket and every object in it
DENY   s3:PutObject                       when Null s3:x-amz-copy-source = false          (copy-shaped put)
DENY   every s3 action                    on the CONTROL bucket and on the Terraform state bucket
DENY   s3:*                               on licensed/qualification/* and licensed/bronze/sharadar/*/qualification/*
DENY   secretsmanager:*                   except the one GetSecretValue above; no ListSecrets, DescribeSecret,
                                          PutSecretValue, and not the qualification secret
DENY   iam:*, sts:AssumeRole, ec2:*, ecs:*, ssm:PutParameter, ssm:DeleteParameter, kms:Encrypt, kms:GenerateDataKey
```

The actor is **write-only** exactly as ADR-0019 requires: it cannot read what it wrote, cannot list, cannot
delete, cannot copy. Its one capability beyond writing is one secret; it has no other.

### 2.3 The research-build actor — exact reads, licensed Silver/Gold writes, no secret

```text
ALLOW  s3:GetObject                       licensed/bronze/sharadar/<dataset>/objects/sha256/*
                                          licensed/bronze/sharadar/<dataset>/acquisitions/*
                                          licensed/bronze/sharadar/_indexes/*
                                          licensed/silver/*, licensed/gold/*, licensed/manifests/*   (its own outputs)
ALLOW  s3:PutObject                       licensed/silver/*, licensed/gold/*, licensed/manifests/*
       with conditions                    the same four conditions as 2.2
DENY   s3:ListBucket, s3:ListBucketVersions, s3:ListBucketMultipartUploads, s3:ListMultipartUploadParts,
       s3:DeleteObject*, s3:PutObjectAcl, s3:RestoreObject, s3:PutObjectRetention, s3:PutObjectLegalHold,
       s3:AbortMultipartUpload            on the licensed bucket
DENY   s3:PutObject                       when Null s3:x-amz-copy-source = false
DENY   s3:GetObject                       on licensed/bronze/_acquisition_claims/*   (claims are validated from the locator, never read)
DENY   every s3 action                    on the CONTROL bucket and on the Terraform state bucket
DENY   s3:*                               on licensed/qualification/* and licensed/bronze/sharadar/*/qualification/*
DENY   secretsmanager:*  (no secret of any kind), iam:*, sts:AssumeRole, ec2:*, ecs:*,
       ssm:PutParameter, ssm:DeleteParameter, kms:Encrypt, kms:GenerateDataKey
```

**Manifests stay LICENSED while CONTROL is deferred**: they carry no vendor row, but the CONTROL bucket is not
written by anyone until CONTROL is undeferred by its own decision, and the build actor holds no CONTROL grant.

### 2.4 Exact object references without listing — the run locator, and where each boundary is enforced

**The exact-read boundary is two boundaries, and they are stated separately.**

| Boundary | Enforced by | What it proves |
|---|---|---|
| the build actor can read **only** objects under the production Bronze prefixes and its own output prefixes | **IAM** — the wildcard `s3:GetObject` grants of 2.3, plus explicit denies on claims, qualification, CONTROL and state | a compromised build process cannot read outside those prefixes, and cannot list anywhere |
| the build actor reads **only the objects a validated run locator names** | **application** — the runner's read surface takes keys from the locator and from nowhere else; no key is constructed from a guess, a pattern or a listing | a correct build touches exactly the locator's objects; **IAM does not prove this**, because within the granted prefixes IAM cannot distinguish a locator-named key from any other |

So "locator-only reads" is an application invariant with a static guard (A-8) and an operation count
(every run reports its `GetObject` count, which must equal the locator's object count plus the locator
itself), **not** an IAM property. The IAM property is prefix confinement, and it is the one the live
permitted/denied matrix exercises.

**The run locator.** Every acquisition run publishes, **last** and conditionally, a run locator at
`licensed/bronze/sharadar/_indexes/<run-id>.json` (≤ 256 KiB, closed schema, no free text): for every
completed request, the exact payload key, payload digest and byte count, the acquisition-record key, digest and
byte count, the request coordinates, the acquisition mode, the run's start and completion instants, the plan
digest and the slice it covered. The build actor derives the locator key from a run identity in its build input
(2.6), retrieves it by exact name, validates it, and reads only what it names — the assessment's exact-read
discipline (`read_exact`) applied to production, with full-object SHA-256 and byte count verified before any
parse. The build actor may not list.

**Locator validation, before any object it names is read** — every clause is a refusal, and a refused locator
reads nothing further:

1. **Identity binding.** The locator's `run_id` equals the run identity that derived its key; its `plan_digest`
   equals the plan digest recorded in the build input's ledger row for that run; its `slice` equals that row's
   slice.
2. **Prefix allowlist.** Every key it names lies under `licensed/bronze/sharadar/<dataset>/objects/sha256/` or
   `licensed/bronze/sharadar/<dataset>/acquisitions/<run-id>/`, where `<dataset>` is one of the datasets the
   slice declares and `<run-id>` is the locator's own; **no key under `_acquisition_claims/`, `_indexes/`,
   `qualification/`, another run's acquisitions, another provider, `silver/`, `gold/`, `manifests/` or outside
   the licensed bucket is admissible**, whatever IAM would permit.
3. **Request scope.** The number of completed requests equals the slice's request count; each request ordinal
   appears exactly once; every payload key embeds a 64-hex digest equal to the recorded digest; byte counts
   are within the plan's response ceiling.
4. **Completeness.** `COMPLETE`, `publication_state_unknown = false`, schema version known, size ≤ 256 KiB.

A missing, malformed, oversize, `PARTIAL` or mismatched locator refuses the build for that run; there is no
fallback that reconstructs by listing, probing or guessing. The locator prefix is inside `bronze/`, so
prefix-based deletion already covers it, and it is written by the acquisition actor's existing write-only grant.

### 2.5 Bindings — one loader, two deliveries, and the bootstrap permissions that carry them

**Humans.** Each actor has its own private runtime binding under the ADR-0023 trust boundary — a third and
fourth artifact, never the qualification ones:

```text
contract_id   kalpamani-production-acquisition-runtime-binding/v1
              kalpamani-research-build-runtime-binding/v1
fields        schema_version · binding_kind · contract_id · aws_partition · aws_region ·
              target_account_id · <actor>_profile · licensed_bucket_name · provenance{...}
variable      KALPAMANI_PRODUCTION_ACQUISITION_RUNTIME_BINDING_FILE
              KALPAMANI_RESEARCH_BUILD_RUNTIME_BINDING_FILE
```

The field sets differ by exactly the profile field name, so neither loads as the other, and neither loads as a
qualification binding. Same absolute-path-only selection, same containment beneath the private root, same
owner-only ACL, same before-and-after identity check, same closed schema, same "loading is not identity proof".

**Compute.** A container has no private root and no Windows ACL, so a task receives its binding from a
**per-actor SSM `SecureString` parameter**, standard tier (≤ 4,096 bytes; a binding is a few hundred), encrypted
under a **customer-managed KMS key declared for this purpose** (`kalpamani-task-bindings`; the foundation has
no KMS key today, and the AWS-managed `aws/ssm` key cannot carry a key policy). The **same loader** validates
the document — schema, kind, contract, partition, region, profile field, account grammar, bucket grammar,
provenance — with the filesystem clauses replaced by two that the platform supplies: the parameter's ARN is
compiled into the task definition, and the decrypting role is the task's own.

**Parameter ownership and materialization.** The two binding parameters are **declared and materialized by
the Terraform gate** (their content is the account, region, bucket and profile values the configuration already
holds as inputs), under the application authorization, and are the only writers of them: no human principal
and no task role holds `ssm:PutParameter` or `ssm:DeleteParameter` on a binding parameter. The parameter names
are fixed and compiled: `/kalpamani/production/acquisition/runtime-binding` and
`/kalpamani/production/research-build/runtime-binding`. No parameter policy is involved — Parameter Store's
parameter policies are lifecycle instruments (expiration and change notifications, advanced tier only) and
**grant no access**; access is IAM plus the key policy, and nothing else.

**The task-only bootstrap policy**, attached to each task role and to nothing else:

```text
ALLOW  ssm:GetParameter                   on exactly ONE parameter ARN: this actor's runtime-binding parameter
ALLOW  kms:Decrypt                        on exactly ONE key ARN: kalpamani-task-bindings
       with conditions                    StringEquals kms:EncryptionContext:PARAMETER_ARN = <that parameter's ARN>
                                          StringEquals kms:ViaService = ssm.<region>.amazonaws.com
ALLOW  ssm:GetParameter                   on exactly ONE parameter ARN: this actor's input parameter (2.6)
ALLOW  kms:Decrypt                        the same key, EncryptionContext:PARAMETER_ARN = <the input parameter's ARN>
DENY   ssm:GetParameters, ssm:GetParametersByPath, ssm:DescribeParameters, ssm:GetParameterHistory
```

**Why `kms:Decrypt` is a permission and not a network dependency.** With `WithDecryption`, Parameter Store
sends the `Decrypt` request to KMS itself, with the parameter's ARN as encryption context, and returns the
plaintext to the caller. The task therefore needs the *permission* — evaluated against the caller's identity
by KMS — but opens **no connection to KMS**; its only network dependency for bootstrap is the SSM endpoint
(2.8). The `kms:ViaService` condition makes the grant usable **only** through Parameter Store, so a task that
somehow obtained the ciphertext could not decrypt it directly.

**The key policy** of `kalpamani-task-bindings` names: the account's Terraform-apply principal for
administration and `kms:Encrypt` (materialization); the two task roles for `kms:Decrypt` under the two
encryption-context conditions above; and no other principal. The key has rotation enabled and no grants.

**Ordering, without a circular dependency.** A task's first act after credentials arrive from the ECS agent is
the parameter read (bootstrap permission, exact ARN). The binding is then **input** to the identity gate, not
proof: the runner calls `sts:GetCallerIdentity` (regional endpoint, 2.8) and compares the returned account to
`target_account_id` from the binding and the returned role name to the **compiled** expected task-role name
for this runner — a constant in the image, not a field of the binding. A forged or wrong binding therefore
fails the comparison rather than steering it, and no S3 or secret operation is reachable before the comparison
passes. The human path has the same shape with the file in place of the parameter.

**Identity proof is unchanged in kind and extended in shape.** For a human,
`AWSReservedSSO_<permission-set>_<suffix>`; for a task,
`arn:<partition>:sts::<account>:assumed-role/<task-role-name>/<task-id>` with the exact task-role name. A
credential resolving to the other actor, to a qualification actor, to the foundation profile or role, or to any
default chain refuses before any S3 or secret operation.

### 2.6 Compute-input delivery — how a task learns what to do without reading an owner-local file

A task can reach no file on the owner's workstation, and no private value may enter argv or a task-definition
environment variable. Each actor therefore has **one fixed-name input parameter**, delivered the same way as
its binding and validated by a closed schema of its own:

```text
/kalpamani/production/acquisition/input        kalpamani-production-acquisition-input/v1
/kalpamani/production/research-build/input     kalpamani-research-build-input/v1
tier      advanced (≤ 8 KiB)   ·   type SecureString under kalpamani-task-bindings
```

| | acquisition input | build input |
|---|---|---|
| **content** | one single-use run identity; the slice (datasets, windows, request count); the plan digest; `issued_at`; `expires_at` | one build identity; the ordered list of run identities to build from; **for each, the owner's slice-ledger row** (run identity, slice, plan digest, ledger outcome, launch and completion instants); the ledger digest; `issued_at`; `expires_at` |
| **authorized writer** | the **human acquisition permission set only** — a human-only bootstrap statement: `ssm:PutParameter` on exactly this parameter ARN, `kms:Encrypt` on the key with this parameter's encryption context | the **human research-build permission set only**, the same shape on its own parameter |
| **reader** | the acquisition task role only (task-only bootstrap policy) | the build task role only |
| **authorization** | one owner-authorized run = one materialization = one launch; the materialization is the owner's written authorization made concrete | likewise, one build |
| **integrity and version** | schema version and contract id checked by the same loader family; `expires_at - issued_at <= 24 h`; a task refuses an expired input, an input whose run identity is already spent, and an input whose plan digest is not the compiled plan's | schema and contract; expiry; the ledger digest must equal the SHA-256 of the canonical serialization of the embedded rows; every run identity must be distinct and match the run-id grammar |
| **size** | ≤ 8 KiB by tier; a task refuses anything larger before parsing | ≤ 8 KiB; at most 32 run identities per build (the compiled ceiling), so a larger backfill is several builds |
| **reconciliation** | the task's public counts (integers only) are matched by the owner's launch tool against the input it wrote, and the ledger row is written **on the owner workstation by the launch tool**, never by the task | the task reconciles each locator against its embedded ledger row (2.4 clause 1); a disagreement is BLOCKING and the build publishes nothing; the build manifest records the build-input digest so the owner can reconcile after the fact |
| **retention** | an `Expiration` parameter policy (lifecycle, not access) deletes the parameter 24 h after materialization | the same |
| **cleanup** | the owner's launch tool overwrites the parameter with an empty-schema tombstone and then deletes it after the task reaches a terminal state; parameter history is deleted with the parameter | the same |

The build input is the compute analogue of ADR-0035 §3.1's owner-only ledger: the ledger itself stays on the
workstation under the ADR-0023 trust boundary; what travels is the rows a build needs, bounded and expiring.
**The acquisition task never writes the ledger** — ADR-0035 §3.1's "written by the runner at run end" is
satisfied by the launch tool on the workstation, which holds the input it materialized and observes the task's
terminal state and integer counts; that is a refinement of where the writing happens, not of what is written.

### 2.7 Server-side immutable writes — a prerequisite for application, not an invariant with a fallback

**The requirement.** No production principal may perform an unconditional, copy-shaped or multipart write to
the licensed bucket, and that must be **refused by S3 itself** — not only declined by the application's
conditional-put surface. AWS documents the mechanism: the condition keys `s3:if-none-match` and `s3:if-match`
in bucket policies, with `s3:ObjectCreationOperation` distinguishing object-creating requests from multipart
parts, and the documented consequence that under such a policy `CopyObject` requests without a conditional
header fail with `403` and with one fail with `501 Not Implemented`
(<https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes-enforce.html>, read 2026-09-12).

**Two layers, both required.**

1. **Bucket policy on the licensed bucket**, scoped to the production prefixes
   (`licensed/bronze/sharadar/*`, `licensed/bronze/_acquisition_claims/*`, `licensed/silver/*`,
   `licensed/gold/*`, `licensed/manifests/*`) and to every principal:
   - `Deny s3:PutObject` where `Null s3:if-none-match = true` **and** `Bool s3:ObjectCreationOperation = true`
     — an object-creating request without `If-None-Match` is refused;
   - `Deny s3:PutObject` where `Bool s3:ObjectCreationOperation = false` — multipart parts are refused
     outright, so no multipart upload can exist under these prefixes (every production object is one
     `PutObject` of at most the plan's response ceiling);
   - `Deny s3:PutObject` where `Null s3:x-amz-copy-source = false` — a copy-shaped put is refused explicitly,
     in addition to the documented behaviour above.
   The qualification prefixes are **not** in scope of these statements; the qualification package's accounting
   and policies are unchanged, and the qualification policies gain nothing.
2. **Identity policies** (2.2, 2.3) grant `s3:PutObject` only with the same conditions, so the grant and the
   bucket policy agree and an identity-policy edit cannot silently widen a write.

**Application is blocked until the server-side refusal is verified.** The application gate for this design is
one governed sequence — saved plan, apply, independent post-apply verification — and it is **not complete** until
the verification proves, with a single refused request, that an object-creating `PutObject` **without**
`If-None-Match` to a production prefix is rejected by S3 (`403`), and that a copy-shaped put is rejected. A
refused request creates nothing; the accepting side of the mechanism is already established on this bucket by
Run A and Run B, whose 290 conditional `PutObject` requests all carried `If-None-Match: *`. **If the refusal
cannot be demonstrated** — because a condition key is not honoured, the pinned provider will not express the
statement, or the verification cannot be run — **the production principals are not established**: no
account assignment is created, no launcher permission set is assigned, no profile or binding is materialized,
and the gate closes pending a **revised design**. There is no fallback to application-only enforcement, and
this ADR makes no weaker claim.

**What the application still does.** Every production `PutObject` carries `If-None-Match: *` and fails closed
on `412` (ADR-0019); the write surface has no copy, no multipart and no unconditional path (static guard). That
is defence in depth behind the server-side refusal, not a substitute for it.

### 2.8 Network dependencies — a per-actor matrix, and the mechanism behind each restriction

The foundation VPC has public subnets routed through an internet gateway, a task security group with no
inbound rule and `0.0.0.0/0:443` egress, and **no VPC endpoints** (ADR-0007 §6 named endpoints as the design
to move to once isolation is needed). This design adds what the two actors need and nothing more.

**Interface and gateway endpoints (Terraform gate):** `com.amazonaws.<region>.s3` (gateway; exists only if the
foundation already has one, else added), `ecr.api`, `ecr.dkr`, `logs`, `ssm`, `sts`, and — for acquisition
only — `secretsmanager`. Each interface endpoint has private DNS enabled and a security group admitting `443`
from the two task subnets only. **Interface endpoints bill hourly** (about USD 7.30 per endpoint per AZ per
month at current public pricing; six in one AZ ≈ USD 44 per month) — recurring cloud spend under CLAUDE.md
§4.21 that needs its own written authorization; the declarations carry a toggle so the endpoints can exist only
during authorized run windows, each toggle being an apply under its own authorization.

| Dependency | Phase | Acquisition task | Build task | Path | Why |
|---|---|---|---|---|---|
| ECR API + registry (`ecr.api`, `ecr.dkr`) | startup (execution role) | yes | yes | interface endpoints | image manifest and layer auth |
| S3 — ECR layer bucket `prod-<region>-starport-layer-bucket` | startup | yes | yes | S3 gateway endpoint | image layers |
| CloudWatch Logs (`logs`) | startup + run | yes | yes | interface endpoint | allowlisted output only |
| SSM Parameter Store (`ssm`) | bootstrap (task role) | yes | yes | interface endpoint | binding and input parameters |
| KMS | bootstrap | **no network path** | **no network path** | — | `kms:Decrypt` is exercised by Parameter Store on the task's behalf (2.5); the task holds the permission and opens no KMS connection |
| STS regional (`sts.<region>`) | identity gate | yes | yes | interface endpoint | one `GetCallerIdentity`; the runner pins the **regional** endpoint, because the global `sts.amazonaws.com` is not reached through the endpoint |
| Secrets Manager (`secretsmanager`) | run | yes | **denied and unreachable** | interface endpoint (acquisition subnet only) | one `GetSecretValue` |
| S3 — licensed bucket | run | write only | read + write | S3 gateway endpoint | data plane |
| provider origin (HTTPS) | run | yes | **no** | internet gateway from the acquisition subnet | 48 sequential requests |
| anything else | — | no | no | — | no route, no rule |

**The build subnet** is a new private subnet with **no route to the internet gateway and no NAT**; its route
table carries the S3 gateway prefix list and local traffic only, and its security group's egress admits `443`
to the S3 managed prefix list and to the interface-endpoint security group, plus DNS to the VPC resolver.
Provider unreachability is therefore a property of routing and rules, not of application restraint, and it
holds even if the build image contained a transport (which the static guard A-8 forbids anyway).

**The acquisition subnet** is a public subnet (a public IP is what makes the provider reachable without a NAT
gateway, ADR-0007 §6). **The mechanism enforcing its provider-origin restriction is the security group**: its
egress rules admit `443` to (a) the S3 managed prefix list, (b) the interface-endpoint security group, and
(c) **the provider origin's resolved IPv4 addresses, materialized at the Terraform gate as an explicit CIDR set
and refreshed under the same gate before each authorized run window** — and **no `0.0.0.0/0` rule**. The
runner additionally resolves the pinned origin at start and refuses the run if any resolved address is
outside the compiled set, so a stale set fails closed instead of failing mid-run. This is an **address**
restriction, not a **hostname** restriction: a security group cannot see TLS SNI, and an address shared by a
CDN tenant would pass it. The hostname-level control is the transport's origin pin (ADR-0009: parsed origin,
redirects refused), which is application enforcement and is recorded as such. AWS Network Firewall's
domain-list filtering would make the hostname restriction a network property; it is a stateful firewall
endpoint billed hourly and is **not adopted here** — it is the named upgrade path if the provider's address set
proves unstable, under its own spend authorization.

**Endpoint policies** on the S3 gateway endpoint admit only the licensed bucket and the ECR layer bucket; on
the Secrets Manager endpoint, only `GetSecretValue` on the one production secret ARN. These narrow which
resources are reachable through the path and do not replace identity policies.

### 2.9 Launch — the launcher, the execution role, task definitions, and what an override can and cannot do

**Task execution role.** The foundation's `<prefix>-task-execution` role is reused **unchanged**, and its exact
permission set is the whole of what it may hold:

```text
ALLOW  ecr:BatchCheckLayerAvailability, ecr:GetDownloadUrlForLayer, ecr:BatchGetImage   on the one research repository
ALLOW  ecr:GetAuthorizationToken                                                      on * (account-level action)
ALLOW  logs:CreateLogStream, logs:PutLogEvents                                        on the research log group's streams
       (optionally conditioned on aws:SourceVpce = the ecr endpoints)
NO     ssm:*, secretsmanager:*, kms:*, s3:* on the data buckets
```

It holds no SSM, Secrets Manager or KMS permission **because the task definitions do not use the container
`secrets` field** — bindings and inputs are read by the task role inside the container (2.5), never injected
as environment variables by the agent. The execution role is the same for both actors; it has no data access.

**Task definitions.** One family per actor (`kalpamani-production-acquire`, `kalpamani-research-build`), Fargate,
platform version pinned, image pinned **by digest** (`repository@sha256:…`, never a tag), the actor's task role,
the shared execution role, `awslogs` to the research log group with a per-actor stream prefix, no `secrets`,
no `environment` entries carrying a private value, no volumes, no EFS, no port mappings, `command` fixed to the
runner's entrypoint and `essential = true`. **A registered revision is immutable**; a change is a new revision
registered at the Terraform gate, and the launcher is scoped to the exact revision Terraform recorded.

**The launcher permission set** (`KalpaManiTaskLauncher`, 21 characters, Identity Center, assigned to the
governed operator group, `PT1H`):

```text
ALLOW  ecs:RunTask        on exactly two resources: arn:...:task-definition/kalpamani-production-acquire:<rev>
                                                    arn:...:task-definition/kalpamani-research-build:<rev>
       with condition     ArnEquals ecs:cluster = the one research cluster
ALLOW  iam:PassRole       on exactly three roles: the two task roles and the execution role
       with condition     StringEquals iam:PassedToService = ecs-tasks.amazonaws.com
ALLOW  ecs:DescribeTasks, ecs:StopTask   on tasks in that cluster (ecs:cluster condition)
ALLOW  ssm:PutParameter, ssm:DeleteParameter, kms:Encrypt   NONE here -- input materialization is the actor
                                                            permission set's, not the launcher's (2.6)
DENY   ecs:RegisterTaskDefinition, ecs:DeregisterTaskDefinition, ecs:CreateService, ecs:UpdateService,
       ecs:CreateCluster, ecs:PutClusterCapacityProviders, iam:*, ec2:*, ecs:ExecuteCommand
```

**What IAM enforces at `RunTask`, and what it cannot.** `RunTask` is resource-scoped to the task-definition
ARN and conditioned on the cluster, so **the family, the exact revision and the cluster are IAM-enforced**; a
`taskRoleArn` or `executionRoleArn` override is IAM-enforced through `iam:PassRole`, which the launcher holds
for exactly the three roles the definitions already name, so an override can only restate them. **IAM has no
condition key for container overrides (`command`, `environment`) or for `networkConfiguration`**; those are
controlled by two other layers, each named for what it is:

| Override | Control | Layer |
|---|---|---|
| `command` | the launch tool never sends `overrides.containerOverrides`; the image's entrypoint is the runner and the runner ignores argv; a task launched with a command override runs the same entrypoint or exits non-zero | launcher validation + image |
| `environment` | never sent; the runner reads no environment variable except `ECS_CONTAINER_METADATA_URI_V4` and refuses if any `KALPAMANI_*` variable is present in a task context | launcher validation + runner |
| `taskRoleArn`, `executionRoleArn` | `iam:PassRole` on exactly three roles | **IAM** |
| `networkConfiguration` (subnets, security groups, public IP) | the launch tool sends the compiled per-actor subnet and security-group identifiers and refuses any other; the runner then reads task metadata v4 and refuses if the reported subnet CIDR is not the bound actor subnet's, and the build runner refuses if a public IP is present | launcher validation + runner self-check |
| `count` | the launch tool sends `count = 1`; the launcher permission set cannot prevent `count > 1` by IAM | launcher validation |
| `enableExecuteCommand` | `ecs:ExecuteCommand` denied, so an interactive session cannot be opened even if requested | **IAM** |

**One task per authorized run.** A run is authorized in writing, its input is materialized once (2.6), the
launch tool starts exactly one task, records the task ARN and terminal state beside the input it wrote, and
refuses a second launch while an input with the same identity exists or a task for it is not terminal. The
task's own single-use run identity makes a duplicate launch harmless at the store (the second task refuses on
an occupied name, ADR-0019) — but the rule is one launch, enforced by the tool, and a second launch is an
incident, not a retry.

### 2.10 The human operating environment — stated for what it is

**ECS network isolation does not extend to a human profile on a laptop, and this ADR does not claim that it
does.** A governed profile on the owner's workstation reaches the internet the way the workstation does. What
holds a human principal to the same boundary as its task is therefore **IAM and the application**, and the
permitted operating environment is stated so that no stronger property is implied:

| | |
|---|---|
| **where** | the owner's workstation, the governed AWS profile, the ADR-0023 private root and its owner-only ACL, the repository's entry points and nothing else — no cloud shell, no shared machine, no CI |
| **what a human acquisition principal may do** | materialize an acquisition input (2.6); exercise its live acceptance cells (3); run an owner-authorized bounded acquisition from the workstation exactly as the qualification runs were run — with the transport's origin pin, `If-None-Match` on every write, the identity gate and allowlisted output as the controls, and the workstation's network **not** restricted by this design |
| **what a human research-build principal may do** | materialize a build input; exercise its live acceptance cells; **read no licensed payload bytes on the workstation** — an owner-run build is not a permitted human operation under this ADR, because ADR-0007 keeps licensed processing inside the private account and ADR-0035 §3.10 admits no laptop copy of Silver or Gold; the human build principal's `GetObject` grant exists for the exact-read verification cells and for reading its own manifests |
| **what neither may do** | hold a long-lived credential; run from a CI system; operate without the before-and-after identity check; keep licensed bytes on local disk after an operation |

**The compensating control for the missing isolation is the absence of capability**: the human build principal
holds no secret and no provider transport is importable in the build runner (A-8), so a build-role session on
an unrestricted network still cannot reach the provider *as this system*; and the human acquisition principal
cannot read, so an acquisition session on an unrestricted network still cannot exfiltrate the store. That is
an IAM property and it is stated as one.

### 2.11 Deletion responsibilities

Unchanged in principle, widened in scope. The deletion role can list and delete under `bronze/`, `silver/`,
`gold/`, `manifests/` and `qualification/`, and cannot read any of them. The cloud-deletion runbook gains
`bronze/sharadar/_indexes/`, `silver/`, `gold/` and `manifests/` as expected prefixes so their first appearance
is not a finding. Neither production actor can delete anything. **The 30-day obligation covers every object
both actors write**, and a run locator may be absent — the runbook never depends on one to discover licensed
objects. The binding and input parameters carry no vendor data; their deletion is the Terraform gate's
(bindings) and the launch tool's (inputs, 2.6).

### 2.12 One run, end to end

```text
 0  authorization      owner's written authorization for ONE run; the actor's human principal materializes
                       the input parameter (2.6): run identity (or build identity + ledger rows), expiry
 1  launch             owner, under KalpaManiTaskLauncher: RunTask, exact family:revision, the one cluster,
                       count 1, compiled subnet + security group, no overrides (2.9); task ARN recorded
 2  image + log        ECS agent, execution role: ECR auth + pull by digest over the ecr endpoints and the
    bootstrap          S3 gateway; log stream created over the logs endpoint (2.8, 2.9)
 3  credentials        task-role credentials from the ECS agent; no STS call by the task to obtain them
 4  binding + input    task role, bootstrap policy: two ssm:GetParameter (WithDecryption) over the ssm
                       endpoint; KMS decrypts on the task's behalf; same loader validates both (2.5, 2.6);
                       expiry, size, schema, identity grammar checked; refusal = exit, nothing else touched
 5  self-check         task metadata v4: image digest == compiled digest, family/revision == compiled,
                       subnet CIDR == bound actor subnet, no public IP for build (2.9)
 6  identity proof     one sts:GetCallerIdentity over the regional sts endpoint; account == binding,
                       role name == compiled task-role name; refusal = exit (2.5)
 7  data operations    acquisition: one GetSecretValue; 48 provider requests over the SG-allowlisted origin;
                       conditional PutObject per artifact; locator last (2.2, 2.4, 2.7)
                       build: locator by exact name, validated (2.4); exact reads with digest + byte count
                       verification; conditional PutObject of Silver/Gold/manifests; manifest records the
                       build-input digest (2.3, 2.6)
 8  output             allowlisted sentences + integer counts to stdout -> CloudWatch; no key, digest,
                       identifier, subject or vendor row (2.9)
 9  termination        runner exits with its closed code; ephemeral storage does not outlive the task and
                       the runner deletes its working directory before exit regardless; no volume exists
10  cleanup            launch tool: records terminal state + counts beside the input; writes the ledger row
                       (acquisition) on the workstation; tombstones and deletes the input parameter; a
                       lifecycle Expiration policy deletes it anyway at 24 h (2.6)
```

Every refusal between steps 4 and 6 happens before any S3, secret or provider operation; every count in step 7
is reported as observed, never as planned.

---

## 3. Acceptance tests — by layer, and what each layer can and cannot prove

Four layers. **A case is assigned to the weakest layer that can actually decide it, and no layer's pass is
reported as a stronger layer's.** Wording tests in this repository prove what a document says, not what AWS
does; policy simulation proves how IAM would evaluate a request, not that a task starts, an endpoint answers,
a parameter decrypts or a subnet is isolated; only runtime verification proves those, and every runtime check
is separately authorized and counted.

| Layer | What it is | Can prove | Cannot prove |
|---|---|---|---|
| **L0 — static (repository tests)** | JSON and text assertions over policy documents, names, trust policies, task definitions and runner imports | shape: which actions, resources, conditions and principals a declaration carries | that AWS honours any of it |
| **L1 — offline Terraform** | `terraform validate` in an isolated external copy under the pinned provider | the configuration is well-formed for the provider | that a condition key is honoured; that a plan applies; anything live |
| **L2 — IAM simulation** | `SimulatePrincipalPolicy` per cell, with the bucket policy supplied as the resource policy | IAM's decision for a request context | task startup, image pull, endpoint reachability, KMS decryption, network isolation, S3's own conditional behaviour |
| **L3 — runtime verification** | one real request or one real task per cell, each counted, each under the application gate's authorization | the thing itself | nothing beyond the cell exercised |

**L0 — static, implementable now or at the Terraform gate:**

| # | Test |
|---|---|
| A-1 | the two data-plane policy documents, parsed as JSON: acquisition grants no `s3:Get*`, no `s3:List*`, no `s3:Delete*`; build grants no `secretsmanager:*`; both carry explicit `Deny` on qualification prefixes, claims (build), the CONTROL bucket and the state bucket |
| A-2 | every `s3:PutObject` `Allow` in both policies carries the SSE, `Null s3:if-none-match=false`, `Bool s3:ObjectCreationOperation=true` and `Null s3:x-amz-copy-source=true` conditions; the licensed-bucket policy carries the three `Deny` statements of 2.7 scoped to the production prefixes and not to `qualification/` |
| A-3 | permission-set names (`KalpaManiProductionAcquire`, `KalpaManiResearchBuild`, `KalpaManiTaskLauncher`) are 1–32 characters under the pinned provider's validator (ADR-0022's guard, reused) |
| A-4 | task-role trust policies name only `ecs-tasks.amazonaws.com` with `aws:SourceAccount` and `aws:SourceArn` conditions; no `AWS` principal; the execution role's policy holds exactly the actions of 2.9 and no `ssm`, `secretsmanager` or `kms` action |
| A-5 | the identity gate accepts exactly the two human role-prefix shapes and the two task-role names, per actor, and refuses the other actor's, the qualification actors', the foundation profile's and role's, and a default-chain identity (synthetic fixtures) |
| A-6 | the four binding/input contracts refuse each other and every qualification binding on the field set; the SSM-delivered document passes the same parser; an expired, oversize, or spent-identity input is refused (synthetic) |
| A-7 | the bootstrap policies: each task role's `ssm:GetParameter` and `kms:Decrypt` name exactly its two parameter ARNs and the one key with `kms:EncryptionContext:PARAMETER_ARN` and `kms:ViaService` conditions; no human permission set carries a binding-parameter read; each human permission set's `ssm:PutParameter` names exactly its input parameter; no principal holds `ssm:PutParameter` on a binding parameter; the key policy names only the apply principal and the two task roles |
| A-8 | static import guards: the acquisition runner imports no read surface; the build runner imports no credential, secrets boundary or provider transport; neither reads an environment variable other than the metadata URI |
| A-9 | task definitions: image reference is a digest, `secrets` absent, no `environment` entry, no volumes, no port mappings, `command` equals the runner entrypoint; the launcher policy's `ecs:RunTask` resources are exactly the two `family:revision` ARNs Terraform records, `iam:PassRole` exactly three roles with `iam:PassedToService`, `ecs:ExecuteCommand` denied |
| A-10 | network declarations: the build subnet's route table has no `0.0.0.0/0` route; the build security group's egress names only the S3 prefix list, the endpoint security group and VPC-resolver DNS; the acquisition security group's egress names those plus the provider CIDR set and no `0.0.0.0/0`; the S3 endpoint policy names only the two buckets |

**L1 — offline Terraform:** A-11 — `terraform validate` in an isolated external copy under the pinned provider,
no repository directory initialized; this proves syntax and provider schema and **does not** prove that
`s3:if-none-match`, `s3:ObjectCreationOperation` or `s3:x-amz-copy-source` are honoured — condition keys are
opaque strings to the provider.

**L2 — IAM simulation (application gate, separately authorized, each call counted):** the permitted/denied
matrix below, one `SimulatePrincipalPolicy` per cell with the bucket policy as resource policy. A simulated
`explicitDeny` or `allowed` is recorded as the simulation's decision, **not** as proof that S3 refused or
accepted a request.

**L3 — runtime verification (application gate, separately authorized, each request or task counted):**

| Cell | Actor | Must succeed | Must be refused |
|---|---|---|---|
| R-1 | acquisition (task) | task reaches step 6 of 2.12 and exits with the closed "verification only" code: image pulled by digest over the endpoints, log stream written, both parameters decrypted, metadata self-check passed, `GetCallerIdentity` over the regional endpoint | — |
| R-2 | build (task) | the same for the build task | any provider-origin connection attempt from the build subnet **times out or is refused at the network layer** (a deliberate probe in the verification image, not in the production image) |
| R-3 | any principal | — | object-creating `PutObject` **without** `If-None-Match` to a production prefix → `403` from S3 (2.7, **the application-gate prerequisite**); copy-shaped put → refused; multipart `CreateMultipartUpload` under a production prefix → refused |
| R-4 | acquisition (human and task) | `GetSecretValue` on the one secret; conditional `PutObject` to each production Bronze prefix and to `_indexes/` (synthetic object, deleted by the deletion role afterwards under its own runbook step) | `GetObject` on its own write; `ListBucket`; `DeleteObject`; `PutObject` to `silver/`, `gold/`, `manifests/`, any qualification prefix, the CONTROL bucket; `GetSecretValue` on the qualification secret; `DescribeSecret`; `ssm:GetParameter` on the other actor's parameters; `ssm:PutParameter` on any binding parameter |
| R-5 | build (human and task) | exact `GetObject` on a Bronze payload, record and locator; conditional `PutObject` to `silver/`, `gold/`, `manifests/`; `GetObject` on its own output | `GetSecretValue` on any secret; `ListBucket`; `GetObject` on a claim; `PutObject` to `bronze/*`; `DeleteObject`; any qualification prefix; the CONTROL bucket; `ssm:GetParameter` on the acquisition parameters |
| R-6 | launcher | `RunTask` of the exact revision on the one cluster with `count = 1` | `RunTask` of another revision or family; on another cluster; with a `taskRoleArn` override naming any other role; `ExecuteCommand` |
| R-7 | qualification actors | unchanged | any production prefix (`bronze/sharadar/*` outside `qualification/`, `_indexes/`, `silver/`, `gold/`, `manifests/`); any production parameter |
| R-8 | deletion role | list and delete under the widened prefixes (rehearsal against synthetic objects only) | `GetObject` anywhere |
| R-9 | foundation `<prefix>-task` role | — | not passable by the launcher (`iam:PassRole` refused) |

A cell that cannot be exercised is recorded as **not exercised**, never as passed; a cell decided by
simulation only is recorded as **simulated**, never as verified. **R-3 is the gate**: until it is verified,
nothing in R-4 to R-9 is reached, because no production assignment exists.

---

## 4. Consequences

- The ingestion design of ADR-0035 gains the principals it named, in a form the accepted trust model already
  knows how to build and verify; nothing about ADR-0035's data design changes. Its §3.1 ledger is written on
  the workstation by the launch tool rather than by the runner when the runner is a task (2.6).
- **Four new gates follow**: offline Terraform declaration (policies, bucket-policy statements, permission
  sets, task roles, bootstrap policies, KMS key, SSM parameters, endpoints, subnets, security groups, task
  definitions, launcher set); application with independent post-apply verification, **incomplete until R-3 is
  verified**; profile, binding and input materialization; and the first bounded ingestion under ADR-0035 §5.
- **Recurring spend is introduced by isolation**: six interface endpoints (≈ USD 44 per month in one AZ at
  current public pricing) and a customer-managed KMS key (USD 1 per month). Each is cloud spend under CLAUDE.md
  §4.21 and is separately authorized; the endpoint toggle exists so the charge can be confined to run windows.
- **The bucket policy is a change to the licensed bucket** — a policy, not versioning, Object Lock, replication,
  lifecycle or backup, so ADR-0007's deletion-first properties are untouched; it is still declared, reviewed
  and verified at the Terraform gate like any other change to that bucket.
- The qualification package is untouched: no policy, permission set, profile, binding, prefix or test of it
  changes; both production policies deny its prefixes explicitly; the bucket-policy statements exclude them.
- CONTROL stays deferred; manifests are LICENSED until a separate decision undefers it.
- The immutable-write property is claimed at **one** strength: server-side, verified before any production
  principal is established. If it cannot be verified, the design is revised, not weakened.
- Human principals are held to the boundary by IAM and application controls, not by network isolation, and the
  documents say so.

---

## 5. Rejected alternatives

- **One production actor for acquisition and build.** Rejected: a principal holding both the provider secret and
  object-read authority could exfiltrate the licensed store — the compromise argument of ADR-0018 §10.3,
  restated for production. The foundation's existing `<prefix>-task` role is that principal, which is why
  neither actor uses it.
- **Reuse the qualification permission sets with wider grants.** Rejected: the qualification accounting is
  closed and audited; widening it would rewrite what those principals were verified to be.
- **Let the build actor list the Bronze prefix.** Rejected: listing is enumeration of what a vendor sent; a
  locator addressed by name gives exact references without it.
- **Deliver task bindings or inputs through task-definition environment variables or the container `secrets`
  field.** Rejected: a bucket, an account or a run identity in a task definition is a private value in an
  infrastructure document, and the `secrets` field would move the parameter read and the KMS permission onto
  the execution role, which must stay data-blind.
- **Deliver the build input as an S3 object.** Rejected: the task would need a key it cannot be told without an
  override or a listing; a fixed-name parameter needs neither.
- **Control access to a parameter with a parameter policy.** Rejected as a category error: parameter policies
  are lifecycle instruments; access is IAM plus the key policy.
- **Give the launcher permission set `iam:PassRole` on `*`, or `ecs:RunTask` on `family:*`.** Rejected: any
  task as any role, or any revision; three exact roles and two exact revisions.
- **Claim application-level conditional writes as the immutability control, with policy enforcement as an
  optional upgrade.** Rejected: an invariant a compromised process can drop is not a control; server-side
  refusal is the prerequisite and there is no fallback.
- **AWS Network Firewall for the acquisition subnet now.** Not adopted: hostname-level egress filtering is the
  stronger control, but it is an hourly-billed firewall endpoint for an account that acquires rarely; the
  address allowlist plus the transport's origin pin is adopted, and the firewall is the named upgrade path.
- **A NAT gateway for the build subnet.** Rejected: it would give the build task internet egress, which is the
  property being removed; endpoints give it AWS and nothing else.
- **Claim that the human principals are network-isolated.** Rejected: a laptop profile is not a subnet; the
  documents state the IAM-and-application boundary and no more.
- **Long-lived compute (a service or scheduled task).** Rejected by ADR-0007: ephemeral one-off tasks, no
  always-on server; a run that nobody launched must not happen.

---

## 6. Status of everything else

```text
this ADR:                                     PROPOSED / NO AUTHORITY WHILE ITS PR IS OPEN
ADR-0034 (partial G1):                        ACCEPTED / IN FORCE -- PR #92 merged
ADR-0035 (ingestion design):                  ACCEPTED / IN FORCE -- PR #92 merged, dependent on ADR-0034
G1 — tickers, stocks; actions restricted:     DECIDED / IN FORCE (ADR-0034); OPEN for every other domain
G2:                                           OPEN -- criteria ADR-0035 G2-A ... G2-H
production policies / bucket-policy statements /
  permission sets / task roles / bootstrap policies /
  KMS key / SSM parameters / endpoints / subnets /
  task definitions / launcher:                DESIGNED HERE -- NOT DECLARED, NOT APPLIED, NOT AUTHORIZED
server-side conditional-write refusal (R-3):  NOT VERIFIED -- the application-gate prerequisite
governed production profiles and bindings:    NOT MATERIALIZED / NOT AUTHORIZED
production run locator:                       DESIGNED -- NOT IMPLEMENTED
first bounded ingestion:                      NOT AUTHORIZED / NOT RUN
qualification principals and artifacts:       UNCHANGED / ISOLATED
foundation <prefix>-task role:                UNCHANGED / NOT USED BY EITHER ACTOR / NOT PASSABLE
CONTROL:                                      DEFERRED
Phase 3:                                      NOT COMPLETE
live trading:                                 HARD-DISABLED
```

**This ADR supersedes no earlier decision and amends no earlier ADR document.** It designs, under the
accepted trust model, the two principals ADR-0035 §3.10 named and left to a later gate, and it names the
gates that follow it.

**Sources consulted (public AWS documentation, read 2026-09-12; no AWS call was made):** conditional writes
and their enforcement in bucket policies; the ECS task execution role and its Secrets Manager / Parameter Store
permissions; KMS encryption for Parameter Store `SecureString` parameters and the `PARAMETER_ARN` encryption
context; Parameter Store parameter policies; ECS identity-based policy examples (`RunTask` resources and
`ecs:cluster`); ECR interface VPC endpoints and the Fargate endpoint requirements; STS interface VPC endpoints
and the regional-endpoint requirement; Fargate task ephemeral storage; the Fargate task metadata endpoint v4.
