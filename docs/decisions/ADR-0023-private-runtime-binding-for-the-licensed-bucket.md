# ADR-0023 — Private runtime binding for the licensed bucket

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0023 is proposed and carries no
authority. That is a statement about the present, it will remain true of these days after any
later merge, and it is not to be rewritten as though this decision had authority before it was
accepted. On merge, this ADR becomes **ACCEPTED / IN FORCE** as **architecture plus the offline
implementation the same pull request carries**, and nothing else.

**Nothing was run to produce this decision.** No AWS CLI or SDK call, no Terraform command of any
kind — `version` included — no Terraform state, backend configuration, `.tfvars` or `.terraform/`
read, no AWS configuration, credential or SSO cache read, no Secrets Manager or S3 operation, no
provider request, no Run A, no Run B and no assessment. **No real private runtime binding was
created, and none exists as a result of this decision.**

**Accepting this ADR authorizes no execution.** It does not authorize creating the real binding
file, an AWS or Terraform command, an infrastructure mutation, a binding preflight, a
qualification run, Run A, Run B, the combined assessment, CONTROL publication, ingestion or
trading. **Implementation, materialization and execution stay three separate gates**, and this
decision opens only the first.

---

## 1. Context

The ADR-0018 Run A acquisition entry point runs under the ADR-0021/ADR-0022 acquisition actor,
reached through the governed profile `kalpamani-qualification-acquisition`. Its stage 6 resolved
the licensed bucket like this:

```text
scripts/sharadar_empirical_qualification.py
    _governed_licensed_bucket()
        aws_foundation_verify.tf_outputs()
            subprocess.run([terraform, -chdir=<infra>, output, -json])
```

`tf_outputs` spawns Terraform with no `env=` argument, so the child inherits the process
environment — including the `AWS_PROFILE` that stage 4 has just pinned to the acquisition actor.
Terraform then reads remote state from the state bucket **as the acquisition actor**.

**That actor cannot read it, by design.** ADR-0019 §4.1 gives the acquisition role `s3:PutObject`
on its own publication prefixes and an explicit `Deny` on `s3:GetObject`,
`s3:GetObjectVersion`, `s3:GetObjectAttributes` and every listing action; it holds no grant of any
kind on the Terraform state bucket. The read cannot succeed, so **Run A refused at stage 6 with
`REFUSED_LICENSED_BUCKET` before reaching a credential, a provider request or a write**.

An independent review of a licensed-configuration diagnostic classified the root cause as
`RUNTIME_ACQUISITION_PROFILE_CANNOT_READ_GOVERNED_REMOTE_STATE`, with defect class
**runtime architecture / private binding defect**, and approved a correction boundary of: no
acquisition-role state access; no private identifiers in Git; fail-closed validation; and no
Terraform subprocess reachable from the acquisition path.

Four further facts shape the decision:

- **Terraform state is broader than the bucket name.** It carries the whole infrastructure
  inventory and can hold plaintext-sensitive values. Granting the acquisition actor access would
  hand a compromised acquisition process exactly the reach ADR-0019 removed, and the two-actor
  compromise argument in ADR-0018 §10.3 rests on that reach not existing.
- **The bucket name is a private identifier.** It may not be hardcoded in Git (CLAUDE.md §3), so
  the value has to arrive from outside the repository.
- **A bare environment variable is not enough.** `KALPAMANI_LICENSED_BUCKET=<name>` carries no
  account binding, no provenance, no protection against another process setting it, and nothing a
  later review could inspect. A licensed destination chosen by an unreviewable variable is a
  licensed destination nobody approved.
- **The existing guard could not have caught this.** The entry-point test asserted
  `"terraform" not in source.lower()` over the entry point's own text. The entry point never
  spelled the word — it said `from aws_foundation_verify import tf_outputs` — so the assertion was
  green throughout, and no test followed the call graph to the subprocess.

---

## 2. Decision

**The licensed bucket arrives as configuration, in an external, ACL-protected private JSON file,
selected by absolute path through one fixed environment variable.**

```text
KALPAMANI_QUALIFICATION_RUNTIME_BINDING_FILE
```

The variable holds an **absolute path to the exact binding file**. **There is no default path**,
no directory scan, no newest-file selection and no fallback: the variable names the file, or
nothing is read at all.

The production binding lives canonically beneath:

```text
%LOCALAPPDATA%\KalpaMani\private\
```

**The entry point and the loader never enumerate that directory.** It is a containment boundary,
not a search path.

**The committed code defines the contract and contains no live binding and no identifier.** No
bucket name, account number, path or digest of any real deployment appears in this repository.

### 2.1 The runtime-binding schema

Schema version 1, with exactly these top-level keys and no others at any level:

```json
{
  "schema_version": 1,
  "binding_kind": "kalpamani-qualification-runtime",
  "contract_id": "qualification-runtime-binding/v1",
  "aws_partition": "aws",
  "aws_region": "us-east-1",
  "target_account_id": "<private 12-digit value>",
  "acquisition_profile": "kalpamani-qualification-acquisition",
  "licensed_bucket_name": "<private value>",
  "provenance": {
    "implementation_commit": "<40 lowercase hex>",
    "implementation_tree": "<40 lowercase hex>",
    "environment_binding_sha256": "<64 lowercase hex>"
  }
}
```

**The provenance fields are populated and independently verified at the later materialization
gate.** They are **not secrets**, and they remain **private operational metadata**: the loader
validates their shape and never returns, prints or logs them.

### 2.2 The runtime trust boundary

The runtime accepts a binding only when **every one** of these passes. Any failure is a refusal,
and a refusal is a closed vocabulary member naming a rule.

```text
the environment variable exists and is non-empty
the path is absolute
the canonical file path is strictly beneath %LOCALAPPDATA%\KalpaMani\private
the file is a regular file
no symlink, junction or other reparse point appears anywhere in the chain
the owner is the current Windows identity
ACL inheritance is disabled
exactly one effective Allow entry exists
that entry names the current user
no Deny entry exists
the size is greater than zero and no more than 16 KiB
the identity, path and security metadata are verified before AND after reading
the content is a UTF-8 JSON object, with no byte-order mark
a duplicate JSON key is refused rather than collapsed
the key set and every type are exact
schema version, binding kind and contract id are exact
partition, region and acquisition profile are exact
the account is exactly twelve digits
the account matches the governed expected account
the bucket passes the repository's approved S3 bucket-name grammar
every provenance value matches its exact lowercase-hex grammar
no private value appears in an error, a log line or any output
```

**Where a platform-specific ACL check cannot be executed, production fails closed.** The
production inspector is the real one and any failure to answer is `SECURITY_UNVERIFIABLE`; a test
may inject a synthetic inspector, and **production cannot silently skip the check**.

**The governed expected account is supplied by the caller**, from the same local binding the
stage-5 identity gate already reads. **No AWS call is made to obtain it**, and no Terraform
process is started: the comparison is between two values the workstation already holds. An
expected account that cannot be established is `EXPECTED_ACCOUNT_UNAVAILABLE` and admits nothing.

### 2.3 The entry-point change

Stage 6 becomes:

```text
scripts/sharadar_empirical_qualification.py
    _governed_licensed_bucket()
        kalpamani.data.qualify.sharadar.runtime_binding.load_runtime_binding()
```

`tf_outputs` is removed from the acquisition path. **`tf_outputs` itself is unchanged**, because
the foundation verifier legitimately uses it under its own separate profile. The stage order, the
closed public result `REFUSED_LICENSED_BUCKET` and its exit code `8` are preserved; no
lower-level validation detail reaches stdout or stderr; no AWS call and no Terraform call is
added; and the acquisition profile, region, secret binding, provider plan, 48-request envelope,
pagination, deadline, retry policy, write-only S3 behaviour and assessment separation are each
unchanged. **The acquisition entry point remains unable to use `kalpamani-foundation` as a
fallback.**

### 2.4 Enforcement

The replaced source-string guard is kept as a necessary-but-not-sufficient check, and two
independent semantic defenses are added:

1. **A name-level call graph** over repository-owned modules, seeded from every top-level
   definition of the acquisition entry point and followed **per name** rather than per module —
   because reaching `aws_foundation_verify` is legitimate and reaching `tf_outputs` is not. It
   asserts `tf_outputs`, the pinned Terraform executable, the backend configuration, the
   state-bucket read and the shared foundation profile are all outside the closure, that no
   reachable string literal names Terraform for any reason other than the local `terraform.tfvars`
   the identity gate already reads, and — as positive controls — that the walk really does reach
   into the verifier and into the new loader.
2. **A runtime sentinel**: the real verifier is loaded, `tf_outputs` and its `subprocess` are
   replaced with traps, and stage 6 then runs for real against a synthetic private binding. The
   trap is separately proven to fire when it is called.

Both defenses are driven from the entry point's **source**, so mutation tests reintroduce the
defect in memory — directly, behind an alias, through the foundation profile, and through a raw
bucket environment variable — and prove each guard fails. No production file is rewritten by any
of it.

---

## 3. Consequences

- **Run A no longer needs Terraform, or state-bucket access, at any point.**
- **The acquisition IAM policy is unchanged.** It stays write-only, with its explicit read denials
  intact. This decision changes no `.tf` declaration, no IAM policy, no Identity Center resource
  and no AWS profile.
- **A separate, foundation-authorized materialization gate must create the real file**, with the
  ACL the trust boundary requires, and **a separate independent review must approve it**.
- **A missing, unsafe or invalid binding continues to refuse Run A**, with the same public outcome
  and the same exit code as before.
- **The binding file is configuration, not a credential.** It carries no secret, no key and no
  token; the provider credential still comes from Secrets Manager at stage 8, unchanged.
- **Run A, Run B, the combined assessment and production ingestion remain separately gated.**
- **Two existing package boundaries are narrowed rather than relaxed.** One module in the
  qualification package now reads the environment, and two now read a file; the tests that used to
  assert "none" and "only the inventory" now name **which** module, and pin the **exact**
  environment-variable names it may read. A second reader, or a third variable, fails.
- **One token-scan exemption is added, with a stricter compensating check.** The broker-identifier
  scan over `src/kalpamani/data/` forbids the substring `account_id`; the schema field
  `target_account_id` is an **AWS** account field, not a brokerage one, and its name is fixed by
  this contract. The exemption is by exact file and exact token, and the exempted module is
  separately asserted to contain no other forbidden token, no `account_id` spelling other than the
  schema field, and **no twelve-digit account value at all** — which the token scan never checked
  anywhere.
- **The assessment entry point is deliberately out of scope.** It resolves its bucket the same
  way, under the assessment actor, and correcting it is a separate authorization. This decision
  neither changes it nor claims it is unaffected.

---

## 4. Rejected alternatives

- **Give the acquisition actor Terraform-state access.** Rejected: it hands a compromised
  acquisition process the whole infrastructure inventory, including any plaintext-sensitive value
  in state, and voids the ADR-0018 §10.3 compromise argument that the two-actor split rests on.
- **Switch to `kalpamani-foundation` inside Run A.** Rejected: the acquisition actor's identity is
  the thing stage 5 proves, and a run that silently changed profile to read one value would be
  running as a principal nobody authorized for acquisition.
- **Hardcode the bucket in Git.** Rejected: a licensed destination is a private identifier, and
  CLAUDE.md §3 forbids committing one — irreversibly so while the repository is public.
- **Read Terraform state with the AWS CLI instead of the Terraform binary.** Rejected: it is the
  same read, by the same actor, against the same bucket, with the same missing permission — and it
  would add a state parser to the acquisition path as well.
- **Accept a raw bucket-name environment variable.** Rejected: no account binding, no provenance,
  no protected envelope, nothing for a later review to inspect, and trivially settable by any
  process that can set an environment.
- **Default to the first (or newest) file found in the private directory.** Rejected: it makes the
  loader enumerate a private directory and turns a wrong or absent variable into a silent
  substitution of some other private file.
- **Keep the real binding inside the repository working tree.** Rejected: a private identifier one
  `git add` away from being published is a private identifier that will eventually be published.
- **Weaken or delete the acquisition actor's explicit S3 read denials.** Rejected: they are the
  half of the boundary the application cannot enforce, and ADR-0019 accepted them precisely so a
  compromised credential holder still cannot read a licensed object.

---

## 5. Status of everything else

```text
licensed-configuration root cause:            INDEPENDENTLY APPROVED
private runtime-binding contract:             IMPLEMENTED / OFFLINE-VALIDATED
real private runtime binding:                 NOT MATERIALIZED
acquisition IAM policy:                       UNCHANGED / WRITE-ONLY
Terraform-state access for acquisition actor: NONE
Terraform reachable from Run A:               NO
Run A:                                        BLOCKED PENDING MATERIALIZATION AND REVIEW
AWS activity:                                 NONE
Terraform activity:                           NONE
provider/Sharadar activity:                   NONE
Run B / combined assessment:                  NOT AUTHORIZED / NOT RUN
production ingestion/backfill/update:         NOT AUTHORIZED / NOT RUN
third ADR-0017 acquisition:                   NOT AUTHORIZED / NOT RUN
sixth binding preflight:                      NOT AUTHORIZED / NOT RUN
G1 / G2:                                      OPEN / OPEN
provider selected:                            NONE
backtesting:                                  NOT STARTED
Phase 3:                                      NOT COMPLETE
CONTROL:                                      DEFERRED
live trading:                                 HARD-DISABLED
```

**This ADR supersedes no earlier decision and amends no earlier ADR document.** ADR-0017
isolation, ADR-0018's evidence inventory and ceilings, ADR-0019's write-only acquisition and
fail-closed collision policy, ADR-0020's request-scoped payload identity, ADR-0021's principal
and trust model and ADR-0022's permission-set name are each unchanged, and so is the arithmetic:

```text
acquisition PutObject: 145 to 147
acquisition HeadObject: 0
acquisition GetObject: 0
two successful runs: 290 to 294
assessment: 195 to 196
whole successful package: 485 to 490
L >= 3 * T_s3 + C
remaining >= T_req + 3 * T_s3 + L
```
