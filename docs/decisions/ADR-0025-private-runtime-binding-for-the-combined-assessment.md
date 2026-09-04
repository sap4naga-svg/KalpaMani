# ADR-0025 — The private runtime binding for the combined assessment

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0025 is proposed and carries no
authority. That is a statement about the present, it will remain true of these days after any
later merge, and it is not to be rewritten as though this decision had authority before it was
accepted. On merge, this ADR becomes **ACCEPTED / IN FORCE** as **architecture plus the offline
implementation the same pull request carries**, and nothing else.

**Nothing was run to produce this decision.** No AWS CLI or SDK call, no STS, SSO or Secrets
Manager call, no S3 operation, no Terraform command of any kind — `version` included — no
Terraform state, backend configuration, `.tfvars` or `.terraform/` read, no AWS configuration,
credential or SSO cache read, no provider request, no execution-identifier or assessment-identifier
allocation, no Run A retry, no Run B and no combined assessment. **No real assessment binding was
created, and none exists as a result of this decision.**

**Accepting this ADR authorizes no execution.** It does not authorize materializing a real
assessment binding, an AWS or Terraform command, an infrastructure mutation, a binding preflight,
an execution or assessment identifier, a qualification run, Run B, the combined assessment, CONTROL
publication, ingestion or trading. **Architecture and offline implementation, real
assessment-binding materialization, the binding preflight, Run B and combined-assessment execution
are five separate gates**, and this decision opens only the first.

---

## 1. Context

[ADR-0023](ADR-0023-private-runtime-binding-for-the-licensed-bucket.md) corrected the Run A
acquisition path: it took the licensed bucket out of Terraform remote state and made it arrive as
an ACL-protected private JSON file. **It said, in its own text, that the combined assessment entry
point was deliberately out of scope and that correcting it was a separate authorization.** That was
accurate, and it is the gap this decision closes.

The combined assessment entry point still resolves its licensed bucket from Terraform remote state,
and it still obtains its account binding from the local, git-ignored Terraform variables file:

```text
sharadar_qualification_assessment.main()
    run_qualification_assessment()
        _governed_identity_gate()
            qualification_identity_gate(ASSESSMENT)
                expected_account()
                    terraform.tfvars
        _governed_licensed_bucket()
            tf_outputs()
                Terraform / governed remote state
```

**Two prohibited dependencies, not one.** They are separate defects with separate causes, and a
correction that removed only the first would leave the second in place while looking finished.

| | |
|---|---|
| **the Terraform state read** | `tf_outputs()` starts a Terraform child process, and Terraform inherits the process environment — so the read is attempted under `kalpamani-qualification-assessment`. That actor holds **no grant of any kind on the state bucket**, so the read cannot succeed, and stage 5 refuses before a locator key is derived |
| **the private Terraform input** | `qualification_identity_gate` calls `expected_account()`, which parses `terraform.tfvars`. That is a plain local file read rather than a subprocess, so it *works* — and it makes a governed identity check depend on a Terraform input the assessment actor has no other relationship with, inside a closure that must be able to prove it contains no Terraform |

**Widening the actor is the wrong repair, and is rejected.** Terraform state carries the whole
infrastructure inventory and can hold plaintext-sensitive values. Granting the assessment actor
state access would hand a compromised assessment process reach that
[ADR-0019](ADR-0019-write-only-acquisition-collision-policy.md) and
[ADR-0021](ADR-0021-qualification-runtime-principal-and-trust-model.md) deliberately withheld, and
would void the two-actor compromise argument ADR-0018 §10.3 rests on. **The assessment IAM policy is
untouched by this decision**, and so is every `.tf` declaration, Identity Center resource and AWS
profile.

### 1.1 Why the acquisition artifact is not reused

The obvious shortcut is to let the assessment read the ADR-0023 runtime binding. It is rejected for
reasons that are about the artifact rather than about convenience:

- **It pins the acquisition profile.** `acquisition_profile` is a required field whose value is
  compared against a compiled constant, so the acquisition binding *is* an acquisition-actor
  artifact by construction.
- **An actor field would make a private file choose the principal.** Adding `actor` — or a flag
  selecting one — to a shared real artifact would let one private file decide which principal reads
  licensed bytes. That is a routing decision taken outside the repository, which is exactly what
  ADR-0023 refused when it declined to accept the partition, the region and the profile from the
  file.
- **One artifact means one mistake reaches both actors.** A wrong or stale shared binding would
  misdirect the write-only acquisition run and the read-capable assessment run together.

**The two artifacts share what should be shared and nothing else**: the environment binding they are
derived from, the private-artifact writer that creates them, and the trust boundary both are read
under.

### 1.2 What the assessment actually needs

Only the governed deployment binding, and nothing wider. It needs **no** provider credential, **no**
secret identifier, **no** provider endpoint and **no** transport — the combined assessment is
structurally unable to reach a provider, and this decision does not change that.

```text
the governed account the authenticated identity must be in
the licensed bucket the exact referenced objects are read from
the partition and the region
the governed assessment profile
private provenance, so the artifact names the implementation it was made for
```

---

## 2. Decision

**The combined assessment resolves its licensed bucket and its account binding from one
ACL-protected private JSON file of its own**, selected by absolute path through one fixed
environment variable, and its identity gate is given that account binding rather than looking one
up.

```text
governed infrastructure outputs
        |  capture, under the foundation actor, separately authorized
        v
environment binding        ADR-0024, actor-neutral, unchanged
        |                                     |
        |  acquisition materialization        |  assessment materialization
        v                                     v
runtime binding (ADR-0023)            assessment binding (this decision)
        |                                     |
        v                                     v
Run A stage 6                         combined assessment stage 4
   no Terraform, no Terraform input reachable from either
```

### 2.1 The assessment-binding schema

Schema version 1, with exactly these top-level keys and no others at any level:

```json
{
  "schema_version": 1,
  "binding_kind": "kalpamani-qualification-assessment-runtime",
  "contract_id": "qualification-assessment-runtime-binding/v1",
  "aws_partition": "aws",
  "aws_region": "us-east-1",
  "target_account_id": "<private 12-digit value>",
  "assessment_profile": "kalpamani-qualification-assessment",
  "licensed_bucket_name": "<private value>",
  "provenance": {
    "implementation_commit": "<40 lowercase hex>",
    "implementation_tree": "<40 lowercase hex>",
    "environment_binding_sha256": "<64 lowercase hex>"
  }
}
```

**It differs from the ADR-0023 runtime binding in exactly one field name** — `assessment_profile`
where that one carries `acquisition_profile` — and the kind and the contract id differ too. That is
what makes each document refuse the other's loader on the field-set check, before any value is
examined: **neither artifact validates as the other**, so a swapped path is a refusal rather than a
silent actor substitution.

**The schema, the kind, the contract id, the partition, the region and the profile are compared
against compiled constants and never accepted from the file.** A private input that could select
its own actor, region or partition would be a routing decision taken outside the repository.

### 2.2 The path contract

```text
KALPAMANI_QUALIFICATION_ASSESSMENT_RUNTIME_BINDING_FILE
```

**There is no default path**, no directory scan, no newest-file selection and no fallback: the
variable names the exact file, or nothing is read at all. The production location is beneath
`%LOCALAPPDATA%\KalpaMani\private`, which is a **containment boundary and not a search path** —
nothing enumerates that directory. The variable is deliberately **not** the acquisition binding's,
so no single name routes both actors, and no entry point exposes an option that could supply a path
either way.

### 2.3 The trust boundary

**The assessment binding is trusted exactly as the other two private artifacts are, by the same
code.** Every clause below is performed by the functions ADR-0023 and ADR-0024 already use, so the
boundary is one implementation rather than three that agree today:

```text
the path is absolute
the canonical file path is strictly beneath %LOCALAPPDATA%\KalpaMani\private
the file is a regular file
no symlink, junction or other reparse point appears anywhere in the chain
the owner is the current Windows identity
ACL inheritance is disabled
exactly one effective Allow entry exists, and it names the current user
no Deny entry exists
the size is greater than zero and no more than 16 KiB
the identity, path and security metadata are verified before AND after reading
the content is a UTF-8 JSON object, with no byte-order mark
a duplicate JSON key is refused rather than collapsed
the key set and every type are exact
schema version, binding kind and contract id are exact
partition, region and the assessment profile are exact
the account is exactly twelve digits
the bucket passes the repository's approved S3 bucket-name grammar
every provenance value matches its exact grammar
no private value appears in an error, a log line or any output
```

**Where a platform-specific ACL check cannot be executed, production fails closed**, and any failure
to answer is `SECURITY_UNVERIFIABLE`. **No second ACL parser is written**: the policy function the
loader already exports is the one that answers.

**The document carries no capability.** It holds no secret identifier, credential, token, provider
endpoint, execution identifier, locator, report key or payload, and there is no field in the schema
for one.

### 2.4 The account binding, and why loading is not proof

**`target_account_id` is the private account binding the assessment identity comparison is made
against.** This is the one place the assessment binding differs from the acquisition one in
substance rather than in naming: the acquisition binding drops the account, because the identity
gate one stage earlier read it from `terraform.tfvars`; the assessment path is forbidden to read
that file, so this artifact *is* where the bound account comes from.

**Carrying it is not trusting it, and loading it is not identity proof.** The value fixes only
*which* account the authenticated identity must be in. The proof remains **one
`sts:GetCallerIdentity`**, and the existing pure identity-validation logic is reused rather than
reimplemented: the returned identity must match

```text
the bound account from the assessment binding
the governed assessment permission-set role-name prefix, with a valid generated suffix
the configured assessment profile
```

**A binding naming some other account therefore misdirects nothing**: the operator's session is not
in that account, the gate refuses, and no S3 client is constructed, no locator key is derived and no
licensed byte is read. **A binding is not a credential**, and it grants no access that the
authenticated session does not already hold.

### 2.5 The corrected stage order

```text
 1  require the assessment singleton authorization
 2  refuse under automation, CI, pytest and import-only contexts
 3  pin the governed assessment profile
 4  load and validate the private assessment binding -- LOCALLY, no process, no request
 5  one identity call, against the account THAT binding names
 6  accept the two owner-known execution identities and the assessment identity
 7  construct the S3 client
 8+ the existing locator, pair-validation, payload-read, evaluation and report stages
```

**Stages 4 and 5 changed places**, because the binding now supplies what the gate compares against.
Order remains the security property: a refusal raises, so no later stage runs after an earlier one
refuses.

**The public outcomes are preserved.** An invalid, unsafe, absent or unusable assessment binding is
the closed, value-free `REFUSED_LICENSED_BUCKET`; an identity mismatch is `REFUSED_IDENTITY`. **The
existing outcome vocabulary and exit-code map are unchanged**, and no member is added, removed or
renumbered.

### 2.6 The materialization gate

**One operator-only command creates the assessment binding, and it reaches no AWS service and starts
no process.** It is a **second gate rather than a mode of the first**: a single command with an
actor flag would make one operator mistake enough to hand one actor the other's binding.

It accepts the environment binding **only by its explicit absolute path**, validates it through the
production validator, derives `target_account_id` and `licensed_bucket_name` **only** from that
validated document, pins the assessment profile in code, records the accepted implementation commit
and tree together with the SHA-256 of **the exact environment-binding bytes it consumed**, uses the
shared canonical serialisation, writes atomically through the existing private-artifact writer,
and then **re-reads the artifact through the loader the assessment itself uses** — deleting the
output if it does not verify. **A collision is a refusal**, never a replacement. It prints no private
value, and it is **unreachable from Run A, Run B and the combined assessment**.

**The accepted implementation provenance names the reviewed commit this contract's implementation
arrived in, and that commit's tree** — `f19608a024a33383bb271f0f6df54045fd3b6f2e` and
`5b786da9f95000d355f5f1902d85d06cd1978985`. That is the convention ADR-0024 established for the
acquisition gate, whose pair names the single approved implementation commit of the ADR-0023 pull
request rather than the merge that landed it or the state it was branched from; a normal merge
preserves that commit in `main`, so the pair keeps resolving for as long as the history does. A
later commit on this slice that corrects the provenance record itself does not move the pair,
because it moves no part of the contract.

**The state this slice was branched from would have been the wrong value, not a harmless one.** It
carries no assessment-binding contract at all, so a reviewer resolving it would find a tree in which
`qualification-assessment-runtime-binding/v1` does not exist — which is exactly the identification
this field is for. The loader validates both values for grammar and **never returns, prints or logs
them**, and a governance test holds the gate's constants equal to the values recorded here, so one
provenance is never spelled two ways.

### 2.7 What the assessment still cannot do

**No provider capability is introduced anywhere.** The assessment process retrieves no credential,
constructs no Secrets Manager client, holds no provider transport and makes no provider request —
this decision adds none of those, and removing a Terraform dependency does not add one. A provider
failure still cannot be converted into an assessment result, because the process cannot contact a
provider at all.

---

## 3. Consequences

- **The combined assessment reaches no Terraform.** No `tf_outputs`, no Terraform subprocess, no
  Terraform executable path, no backend or state read, and **no foundation-profile fallback**, are in
  its execution closure.
- **The combined assessment reads no private Terraform input.** `expected_account` and
  `terraform.tfvars` are out of its closure too, which is the half of the defect a bucket-only
  correction would have left behind.
- **Run A and the acquisition binding are unchanged.** The acquisition runtime-binding schema, its
  parser, its environment variable, its materializer, its entry point and its behaviour are all
  untouched, and the acquisition path keeps the identity gate that reads the local Terraform
  variables file.
- **The shared gate keeps one implementation.** The account binding is a parameter of the existing
  pure refusal function, and the new actor-bound gate supplies it rather than looking one up. The
  refusal message it returns became source-neutral, because two callers now obtain that binding from
  two different governed sources.
- **No private value enters Git.** No bucket, account, path, principal, digest or deployment value of
  any real deployment appears in this repository, and every test fixture is invented.
- **The qualification package boundaries are not widened.** The second contract lives in the module
  that already owns the first two, so one trust boundary exists rather than two, and the operator
  tool lives outside the package.
- **Nothing about the assessment's own behaviour changes.** The refusal by default, the separate
  authorization flag, the automation refusal, the two distinct execution identities, the Run A
  before Run B ordering, the eight-calendar-day separation, both locators and the pair validated
  before any payload byte is read, exact-key reads with no listing, checksum and byte-count
  verification before parsing, one owner-only report with no local copy, and the absence of any
  public P1–P9 fact are each unchanged.
- **The arithmetic is unchanged.** A successful future assessment remains 194 object-byte
  `GetObject`, one report `PutObject`, zero or one conditional `HeadObject`, and 195–196 S3
  operations, with **no CONTROL operation**.
- **Materialization is not a run.** Materializing the assessment binding, the binding preflight,
  Run B and the combined assessment are **four separate written authorizations**, and none of them
  is implied by any other or by this decision.

---

## 4. Rejected alternatives

- **Leave the assessment on Terraform because Run A was the urgent case.** Rejected: the state read
  cannot succeed under the assessment actor either, so the combined assessment would refuse at stage
  5 the first time it was authorized — and the private Terraform input would stay inside a closure
  that is supposed to prove it has none.
- **Give the assessment actor Terraform-state access.** Rejected: it hands a compromised assessment
  process the whole infrastructure inventory and voids the two-actor compromise argument. The
  assessment IAM policy is unchanged.
- **Reuse the ADR-0023 acquisition runtime binding.** Rejected: it pins `acquisition_profile` by
  construction, so it is an acquisition-actor artifact, and one artifact means one mistake reaches
  both actors.
- **Add an actor field or an actor flag to a shared real artifact.** Rejected: it would let a private
  file choose which principal reads licensed bytes, which is a routing decision taken outside the
  repository.
- **Keep `expected_account()` and replace only `tf_outputs()`.** Rejected: it removes one prohibited
  dependency and leaves the other, so the identity gate would still read `terraform.tfvars` while the
  correction looked complete.
- **Take the account from the environment binding at run time.** Rejected: the environment binding is
  the capture the materialization consumes, and a run that read it would be reaching for the producer
  rather than the product — the ADR-0024 isolation property, restated for this actor.
- **Accept a raw bucket or account environment variable.** Rejected: no account binding, no
  provenance, no protected envelope, nothing for a later review to inspect, and trivially settable by
  any process that can set an environment.
- **Hardcode the bucket or the account in Git.** Rejected: a private identifier in a public
  repository is a disclosure that deleting the line does not undo.
- **Discover the artifact by listing the private directory, or by taking the newest file.** Rejected:
  it makes a tool enumerate a private directory, and it turns a wrong or absent variable into a
  silent substitution of some other private file.
- **Fall back to the `kalpamani-foundation` profile when the assessment profile cannot resolve.**
  Rejected: a fallback that reaches a wider actor is the wrong-account hazard the pinning exists to
  prevent.
- **Treat a successfully loaded binding as identity proof.** Rejected: a local file says which account
  the operator believes they are in, and `sts:GetCallerIdentity` says which one they are in.
- **Put the assessment contract in a new module.** Rejected: containment, ownership, the ACL, the
  before-and-after verification and the canonical serialisation would then exist in two places, and
  two security models are one more than anybody reviews.
- **Give the acquisition and assessment materializations one command with two modes.** Rejected: one
  operator mistake would then be enough to hand one actor the other's binding, and "this gate cannot
  write the other artifact" would be unprovable.
- **Overwrite an occupied destination.** Rejected: a private artifact another run is bound to is not
  this command's to replace, and a check followed by a write is a race. The create is exclusive and a
  collision is a refusal.

---

## 5. Status of everything else

```text
assessment-binding contract:                  IMPLEMENTED / OFFLINE-VALIDATED
assessment-binding materialization gate:      IMPLEMENTED / OFFLINE-VALIDATED / NEVER RUN
real assessment runtime binding:              NOT MATERIALIZED
real private runtime binding:                 NOT MATERIALIZED
assessment IAM policy:                        UNCHANGED
Terraform-state access for assessment actor:  NONE
Terraform reachable from the assessment:      NO
private Terraform input reachable:            NO
operator tools reachable from the assessment: NO
provider or credential reachable:             NO
AWS activity:                                 NONE
Terraform activity:                           NONE
provider/Sharadar activity:                   NONE
new execution identifiers:                    0
new assessment identifiers:                   0
Run A:                                        COMPLETED ONCE / 2026-09-04
a Run A retry:                                NOT AUTHORIZED / NOT RUN
assessment-binding materialization:           NOT AUTHORIZED / NOT RUN
binding preflight:                            NOT AUTHORIZED / NOT RUN
Run B:                                        NOT AUTHORIZED / NOT RUN
Run B minimum separation:                     AT LEAST 8 CALENDAR DAYS AFTER RUN A
Run B earliest approved target:               12 SEPTEMBER 2026
combined assessment:                          NOT AUTHORIZED / NOT RUN
P1-P9:                                        UNEVALUATED
data correctness and quality:                 NOT ESTABLISHED
production ingestion/backfill/update:         NOT AUTHORIZED / NOT RUN
third ADR-0017 acquisition:                   NOT AUTHORIZED / NOT RUN
sixth private-binding preflight:              NOT AUTHORIZED / NOT RUN
further infrastructure mutation:              NOT AUTHORIZED
G1 / G2:                                      OPEN / OPEN
provider selected:                            NONE
backtesting:                                  NOT STARTED
Phase 3:                                      NOT COMPLETE
CONTROL:                                      DEFERRED
live trading:                                 HARD-DISABLED
```

**This ADR supersedes no earlier decision and amends no earlier ADR document.** It closes a gap
ADR-0023 named and deliberately left open, for the actor ADR-0023 excluded. ADR-0017 isolation,
ADR-0018's evidence inventory and ceilings, ADR-0019's write-only acquisition and fail-closed
collision policy, ADR-0020's request-scoped payload identity and assessment digest verification,
ADR-0021's principal and trust model, ADR-0022's permission-set name, ADR-0023's runtime binding and
ADR-0024's environment binding are each unchanged, and so is the arithmetic:

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
