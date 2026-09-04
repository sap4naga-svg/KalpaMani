# ADR-0024 — The governed qualification environment-binding source

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0024 is proposed and carries no
authority. That is a statement about the present, it will remain true of these days after any
later merge, and it is not to be rewritten as though this decision had authority before it was
accepted. On merge, this ADR becomes **ACCEPTED / IN FORCE** as **architecture plus the offline
implementation the same pull request carries**, and nothing else.

**Nothing was run to produce this decision.** No AWS CLI or SDK call, no Terraform command of any
kind — `version` included — no Terraform state, backend configuration, `.tfvars` or `.terraform/`
read, no AWS configuration, credential or SSO cache read, no Secrets Manager or S3 operation, no
provider request, no execution-identifier allocation, no Run A, no Run B and no assessment.
**No real environment binding and no real runtime binding was created, and neither exists as a
result of this decision.**

**Accepting this ADR authorizes no execution.** It does not authorize capturing a real
environment binding, materializing a real runtime binding, an AWS or Terraform command, an
infrastructure mutation, a binding preflight, an execution identifier, a qualification run,
Run A, Run B, the combined assessment, CONTROL publication, ingestion or trading.
**Implementation, materialization and execution stay three separate gates**, and this decision
opens only the first.

---

## 1. Context

[ADR-0023](ADR-0023-private-runtime-binding-for-the-licensed-bucket.md) took the licensed bucket
out of Terraform remote state and made it arrive as an ACL-protected private JSON file, selected
by absolute path through `KALPAMANI_QUALIFICATION_RUNTIME_BINDING_FILE`. Its schema requires a
provenance block, and inside it:

```json
"environment_binding_sha256": "<64 lowercase hex>"
```

**The loader validates that field's grammar and nothing else.** It checks sixty-four lowercase
hexadecimal characters, and then deliberately discards the value: the acquisition path does not
need it, so it never carries it.

**Nothing in the repository established what those bytes are.** There is no schema for the
artifact they digest, no producer that writes one, no path-discovery mechanism that selects one,
and no code that hands the digest to runtime-binding materialization — because no runtime-binding
materialization exists in tracked code either. ADR-0023 deferred creating the file to "a separate,
foundation-authorized materialization gate" and did not describe the gate.

The consequence is concrete rather than theoretical. An operator asked to perform that gate has
no defined way to obtain `target_account_id` and `licensed_bucket_name`, no defined artifact whose
bytes the digest names, and therefore no way to fill in a required field truthfully. A field that
cannot be filled in truthfully gets filled in anyway.

**One naming collision made the gap easy to miss.** The loader's own
`environment_binding_path()` returns the path of the **runtime** binding — the binding *from the
environment* — while `environment_binding_sha256` names something else entirely. The same phrase
was doing two jobs in one module, and neither of them was the missing one.

### 1.1 Two artifacts that were considered and are not this one

**The applied secret-access receipt is not the environment binding.** It records a secret-access
decision. It carries no licensed bucket, so redesignating it would leave the runtime binding
copying values from an artifact that does not contain them, and would make
`environment_binding_sha256` name bytes that say nothing about the licensed destination the
binding exists to supply.

**The private Terraform input is not the environment binding either.** `terraform.tfvars` is the
local, git-ignored account-binding variables file the identity gate already reads. It carries the
allowed account and no licensed bucket; it is not an ACL-governed artifact beneath the operator's
private root; and it is Terraform's own input rather than a capture of Terraform's output.
Silently redesignating it would change what a governed identity check reads, which is an
architectural change and not a naming convenience.

---

## 2. Decision

**The qualification environment binding is a second private artifact, with its own contract, its
own producer, and its own path.** It carries the authoritative qualification-environment values,
captured from the governed infrastructure outputs by an operator-only command that runs under the
foundation actor. The runtime binding is then derived from it, and
**`provenance.environment_binding_sha256` is the SHA-256 of the exact bytes of the environment
binding that runtime-binding materialization consumed**.

```text
governed infrastructure outputs
        |  capture, under the foundation actor, separately authorized
        v
environment binding        (private, ACL-protected, beneath the private root)
        |  materialization, no AWS and no Terraform, separately authorized
        v
runtime binding            (ADR-0023, unchanged schema)
        |  read
        v
Run A stage 6              (no Terraform, no capture, no materialization reachable)
```

### 2.1 The environment-binding schema

Schema version 1, with exactly these top-level keys and no others at any level:

```json
{
  "schema_version": 1,
  "binding_kind": "kalpamani-qualification-environment",
  "contract_id": "qualification-environment-binding/v1",
  "aws_partition": "aws",
  "aws_region": "us-east-1",
  "target_account_id": "<private 12-digit value>",
  "licensed_bucket_name": "<private value>",
  "provenance": {
    "source_kind": "terraform-output",
    "captured_at_utc": "<RFC3339 UTC, second precision, Z designator>",
    "outputs_digest": "<64 lowercase hex>"
  }
}
```

**It is deliberately actor-neutral.** There is no `acquisition_profile` field: this artifact
describes the deployment, and the actor is added one layer later by the runtime binding. A
captured environment that could select which principal will use it would be a routing decision
taken by a private file.

**The provenance identifies the capture, not the operator.** `source_kind` is a closed vocabulary
of exactly one member, so a document claiming some other origin is refused rather than trusted;
`captured_at_utc` has one exact shape, so two captures are comparable and neither carries a local
timezone; and `outputs_digest` binds the exact governed outputs that were consumed.

### 2.2 The path contract

The environment binding is selected by **an absolute path**, supplied by the operator through one
fixed environment variable:

```text
KALPAMANI_QUALIFICATION_ENVIRONMENT_BINDING_FILE
```

**There is no default path**, no directory scan, no newest-file selection and no fallback. The
production location is beneath `%LOCALAPPDATA%\KalpaMani\private\`, which is a containment
boundary and not a search path: **nothing enumerates that directory**. The filename may carry a
timestamp, and consumers still receive the exact absolute path explicitly — they never discover it
by listing.

**The validator itself reads no environment variable.** It takes the path as a required argument.
That is the isolation property rather than a style choice: a loader that resolved its own path
could be called from anywhere and would find something, and Run A must not be able to read this
artifact at all.

### 2.3 The trust boundary

**The environment binding is trusted exactly as the runtime binding is, by the same code.** Every
clause of the ADR-0023 §2.2 boundary applies, and it applies because one function performs it for
both artifacts rather than because two implementations agree today:

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
partition and region are exact
the account is exactly twelve digits and matches the governed expected account
the bucket passes the repository's approved S3 bucket-name grammar
every provenance value matches its exact grammar
no private value appears in an error, a log line or any output
```

**Where a platform-specific ACL check cannot be executed, production fails closed**, and any
failure to answer is `SECURITY_UNVERIFIABLE`. **The governed expected account is supplied by the
caller** from the same local binding the identity gate reads; **no AWS call is made to obtain it**,
and no Terraform process is started.

### 2.4 The digest, defined

**`environment_binding_sha256` is the SHA-256, in lowercase hexadecimal, of the exact byte
sequence of the environment binding that runtime-binding materialization read.** It is taken from
the bytes on disk, not recomputed from the parsed document: a digest of a re-serialisation would
name a *shape*, two differently formatted files would carry the same value, and a reviewer handed
the digest could not re-derive it from the artifact.

**Byte agreement is fixed by one serialisation.** A private binding document is written as UTF-8
with no byte-order mark, sorted keys, compact separators, no escaped non-ASCII and a trailing
newline, produced by one shared function, so the producer's file and anybody's later digest of it
are computed over the same bytes.

### 2.5 The producer, and what it may not become

**One operator-only capture command reads the governed infrastructure outputs, and it is the only
thing in this repository that may.** It is separate from Run A and from every qualification entry
point, and it is **unreachable from the Run A call graph**.

| | |
|---|---|
| **the actor is pinned explicitly** | `AWS_PROFILE` must already be the governed foundation profile, and the two qualification profile names are refused by name. Terraform inherits the process environment, which is exactly how the ADR-0023 defect arose |
| **identity is proved before anything is read** | the existing governed identity gate must pass first |
| **exactly one output is consumed** | the output map carries a registry URL and role ARNs that each embed an account, and a capture that took the whole map would put them in a file nobody asked for |
| **it fails closed** | on an unpinned or wrong profile, a failing identity gate, a missing or malformed output, a missing account binding, a refused destination, or a document the production validator will not accept |
| **it writes atomically, and a collision is a refusal** | one exclusive create, never a check followed by a write, and never an overwrite |
| **it grants itself nothing** | no IAM or infrastructure mutation, no credential or secret value stored, no standing authorization to run Terraform or AWS again |
| **running it is a separate authorization** | in its own fresh session, under Manual approval |

### 2.6 The materialization gate

**One operator-only command derives the runtime binding, and it reaches no AWS service and starts
no process.** It accepts the environment binding **only by its explicit absolute path**, validates
it through the production validator, copies **only** `target_account_id` and
`licensed_bucket_name`, confirms partition and region consistency, and writes the **unchanged**
ADR-0023 runtime-binding schema. The schema, kind, contract, partition, region and acquisition
profile are the compiled governed constants.

It stores the SHA-256 of the environment binding it consumed in `environment_binding_sha256`,
preserves the accepted implementation provenance of the merged ADR-0023 slice
(`d412d528f02686940cd77edd2101f3fc687cc34e` and `d49d83da4382536a38f4d06a03bf723320b20b44`),
writes atomically and collision-fail-closed under the same owner-only security boundary, and then
**re-reads the artifact through the loader Run A itself uses** and refuses if it does not load. It
prints no private value.

### 2.7 One writer, not two

Both artifacts are created by **one** private-artifact writer, which applies a descriptor and then
asks the loader's own policy function whether the result is admissible. A second tool deciding for
itself what owner-only meant would be a second security model, and two security models are one
more than anybody reviews. **It creates no directory**: the private root is the owner's to
establish, with the descriptor they chose.

---

## 3. Consequences

- **Run A is unchanged.** The acquisition entry point still consumes only the already-materialized
  runtime binding, its stage order, its closed `REFUSED_LICENSED_BUCKET` outcome and its exit code
  `8` are untouched, and **Terraform remains unreachable from it**. Two guards now cover that: the
  existing Terraform call-graph check, and a new one proving the closure reaches neither the
  capture, nor the materialization gate, nor the writer, nor the environment-binding validator.
- **The acquisition IAM policy is unchanged.** It stays write-only with its explicit read denials
  intact. This decision changes no `.tf` declaration, no IAM policy, no Identity Center resource
  and no AWS profile.
- **No private value enters Git.** No bucket, account, path, principal, digest or deployment value
  of any real deployment appears in this repository, and every test fixture is invented.
- **ADR-0023's runtime-binding schema is not changed.** No field is added, removed or renamed; one
  field that was previously undefined now has a defined meaning and a defined producer.
- **The qualification package boundaries are not widened.** Exactly one module there reads an
  environment, exactly the same two read a file, and none of them writes one — the contract for
  the second artifact lives in the module that already owns the first, and both operator tools
  live outside the package.
- **Qualification payloads are unaffected.** ADR-0017 isolation, ADR-0019 write-only acquisition,
  ADR-0020 request-scoped payload identity and assessment digest verification are unchanged.
- **A capture is not a materialization, and a materialization is not a run.** Capturing the
  environment binding, materializing the runtime binding, the binding preflight, allocating an
  execution identifier, Run A, Run B and the combined assessment are **seven separate written
  authorizations**, and none of them is implied by any other or by this decision.

---

## 4. Rejected alternatives

- **Leave `environment_binding_sha256` as a grammar-checked field.** Rejected: a required field
  with no defined artifact behind it is a field an operator fills in from whatever they have, and
  the provenance it appears to record is then unverifiable by anybody.
- **Redesignate the applied secret-access receipt as the environment binding.** Rejected: it does
  not contain the licensed-bucket environment binding, so the runtime binding could not be derived
  from it and the digest would name bytes that say nothing about the licensed destination.
- **Redesignate the private Terraform input as the environment binding.** Rejected: it is
  Terraform's input rather than a capture of its output, it carries no licensed bucket, it is not
  an ACL-governed artifact beneath the private root, and changing what the governed identity check
  reads is an architectural change that would need its own accepted decision.
- **Let Run A capture the values itself when the runtime binding is absent.** Rejected: that is
  the ADR-0023 defect restored under a new name — the acquisition actor cannot read state, and an
  actor that could would hold the reach ADR-0019 removed.
- **Resolve the environment binding from its own environment variable inside the validator.**
  Rejected: a loader that finds its own path is reachable from anywhere, and Run A must not be
  able to read this artifact at all. The path is an argument, so the call graph shows every
  caller.
- **Discover the artifact by listing the private directory, or by taking the newest file.**
  Rejected: it makes a tool enumerate a private directory, and it turns a wrong or absent variable
  into a silent substitution of some other private file.
- **Accept a raw bucket or account environment variable for materialization.** Rejected: no
  account binding, no provenance, no protected envelope, nothing for a later review to inspect,
  and trivially settable by any process that can set an environment.
- **Overwrite an occupied destination.** Rejected: a private artifact another run is bound to is
  not this command's to replace, and a check followed by a write is a race. The create is
  exclusive and a collision is a refusal.
- **Give the capture and the materialization one command with two modes.** Rejected: the capture
  legitimately reads Terraform and the gate legitimately must not, and a single module would make
  "the gate cannot reach Terraform" unprovable.
- **Write the artifact with a second, tool-local notion of owner-only permissions.** Rejected: the
  reader's policy is the only policy, and a writer that agreed with it today would be free to
  disagree with it tomorrow.
- **Take the digest over a re-serialisation of the parsed document.** Rejected: it would name a
  shape rather than bytes, and a reviewer could not re-derive it from the artifact on disk.

---

## 5. Status of everything else

```text
environment-binding contract:                 IMPLEMENTED / OFFLINE-VALIDATED
environment-binding producer:                 IMPLEMENTED / OFFLINE-VALIDATED / NEVER RUN
runtime-binding materialization gate:         IMPLEMENTED / OFFLINE-VALIDATED / NEVER RUN
real environment binding:                     NOT MATERIALIZED
real private runtime binding:                 NOT MATERIALIZED
acquisition IAM policy:                       UNCHANGED / WRITE-ONLY
Terraform-state access for acquisition actor: NONE
Terraform reachable from Run A:               NO
operator tools reachable from Run A:          NO
Run A:                                        BLOCKED PENDING MATERIALIZATION AND REVIEW
AWS activity:                                 NONE
Terraform activity:                           NONE
provider/Sharadar activity:                   NONE
new execution identifiers:                    0
environment-binding capture:                  NOT AUTHORIZED / NOT RUN
runtime-binding materialization:              NOT AUTHORIZED / NOT RUN
binding preflight:                            NOT AUTHORIZED / NOT RUN
execution-identifier allocation:              NOT AUTHORIZED / NOT PERFORMED
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

**This ADR supersedes no earlier decision and amends no earlier ADR document.** It defines an
artifact ADR-0023 required and did not define, and it changes nothing ADR-0023 decided. ADR-0017
isolation, ADR-0018's evidence inventory and ceilings, ADR-0019's write-only acquisition and
fail-closed collision policy, ADR-0020's request-scoped payload identity, ADR-0021's principal and
trust model, ADR-0022's permission-set name and ADR-0023's runtime binding are each unchanged, and
so is the arithmetic:

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
