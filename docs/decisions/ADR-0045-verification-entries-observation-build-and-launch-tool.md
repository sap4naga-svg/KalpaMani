# ADR-0045 — Verification entries, the observation build, and the owner-side launch tool

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0045 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **the verification-path completion of ADR-0043 §2 and ADR-0036
§2.9 / §3 — two closed verification entries that stop at the release barrier, the receipt evidence
they and a refused build carry, the isolation rule the build probe is read under, the two verification
task-definition families and the launcher resource each adds, the owner-side launch tool and its
records, and the re-verification policy — together with the narrow amendments to ADR-0036, ADR-0043
and ADR-0044 it states, and nothing else**, effective together with the offline code merged beside
it. **Acceptance authorizes no execution** (§9): no image build, no publication, no Terraform plan or
apply, no launch, no run, no probe.

**Nothing was run to produce this decision.** No AWS call, no STS call, no ECS, EC2 or SSM call, no
container image built, pulled or published, no registry contacted, no credential retrieved, no
provider request, no TCP connection attempted, no Reachability Analyzer analysis started. Every
adapter named here was exercised only against synthetic fakes through the real modules; the Terraform
additions were validated offline in a task-owned external copy, and never planned or applied.
**Mocked results are not AWS verification.**

---

## 1. Context — the verification path had no task, no tool and no rule

`docs/operations/production-readiness.md` (merged as PR #103) established four things from the code
and left each open as a numbered gap:

- **G-1**: a released bootstrap continues directly into processing on both composed entries — there is
  no way to run ADR-0036 §3's R-1 (release barrier) and R-2 (build-subnet isolation) cells with the
  accepted images, because the only task that reaches `RELEASED` then reserves an identity, retrieves
  a credential and calls the provider.
- **G-2 / G-3**: `launch_authorized_run` is a library on injected adapters, and nothing materializes an
  input from the owner ledger, compiles a `CompiledLaunch` from Terraform records, or records the launch
  a receipt must be verified against.
- **G-7 (Route B)**: the first build image cannot be gated on per-dataset schema digests nobody has
  observed for the ticker-less request form; an observation build that admits nothing and reports what
  it saw is the only route that does not invent a value.
- **G-12 / G-15**: no accepted text says whether R-1/R-2 must be repeated per production image, or what
  turns a probe's non-connection into an isolation finding rather than an observation.

This ADR decides each. It **does not** decide G-14 (the bucket-policy transition procedure), which
stays deferred: nothing here depends on changing the deployed bucket policy.

---

## 2. Decision — two verification entries that terminate at the barrier

**ADR-0043 §2's two closed entries become four.** The task definitions' `command` tokens are:

```text
kalpamani-production-acquire         the acquisition actor's production entry   (ADR-0043)
kalpamani-research-build             the build actor's production entry         (ADR-0043)
kalpamani-production-acquire-verify  the acquisition actor's VERIFICATION entry (this ADR)
kalpamani-research-build-verify      the build actor's VERIFICATION entry       (this ADR)
```

A verification entry composes exactly the accepted bootstrap — environment, binding, input,
self-check, identity proof, release barrier (`run_task_bootstrap`) — **and nothing after
`RELEASED`**. On release it returns the closed outcome **`VERIFIED_BOOTSTRAP`**, exit code **18**:
non-zero on purpose, so that exit `0` stays `COMPLETED` alone and a verification run can never be read
as a run. Every bootstrap refusal keeps its accepted outcome and exit code.

**What a verification entry cannot do, by construction.** Its factories (`VerificationFactories`)
have no field for a Secrets Manager client, a provider transport or an S3 client, and `run_task_bootstrap`
is called with no spent-identity registry. So a verification task performs **zero** `GetSecretValue`,
**zero** provider API requests, **zero** data-plane S3 operations and **zero** run reservations —
asserted by counting fakes, and by a static guard that no verification module names those clients.
A verification identity is therefore **never spent in the store**; §6 is why that matters.

**The compiled configuration of a verification entry** carries the origin address set and nothing
else — no secret name, no build configuration (ADR-0044 §2's file, `_VERIFICATION_FIELDS`). The
generator refuses any other field for a verification entry. `CompiledTask` admits either the
production family or the verification family for an actor (`is_known_family`); the entry's own
invariant holds a verification entry to the verification family and a production entry to the
production one, so a verification image can never run under a production family's task definition or
the reverse.

**The build verification entry makes one provider-origin probe** (§3). The acquisition verification
entry makes none: it refuses an unpinned or partly-left origin exactly as the production entry does
(`origin_address_refusal`) and attempts nothing.

**What a verification pass establishes** is exactly the D column of the readiness plan's §3.3 table,
and nothing in its U column: the bootstrap code path on this commit, the verification image's own
digest and configuration, the binding, input and release processing under the actor's task role on
this task, and the absence of the processing capabilities. **It does not establish that the production
image executes**; the first authorized production run is the evidence for that.

---

## 3. Decision — the build probe: closed observations, and a verdict decided outside the task

**The probe is one TCP connect and no bytes.** Port **443**, timeout **5 s**, **at most one attempt**
(`PROBE_PORT`, `PROBE_TIMEOUT_SECONDS`, `PROBE_MAX_ATTEMPTS`), against exactly one destination:
the lexicographically smallest IPv4 literal the pinned origin resolves to — and only when **every**
resolved address lies inside the compiled origin set. A set the origin has partly left is stale, and a
probe against it observes nothing about the current provider; the same rule the accepted entries apply
to the origin. The destination is therefore deterministic from the compiled set and the resolution, so
the launch tool can name it from its own record without the task disclosing an address.

**The observation is closed.** The receipt carries three fields:

```text
probe_resolution   RESOLVED_IN_SET | RESOLVED_OUTSIDE_SET | UNRESOLVED
probe_result       CONNECTED | CONNECTION_REFUSED | TIMED_OUT | CONNECTION_ERROR | NOT_ATTEMPTED
probe_attempts     0 | 1     -- exactly 1 iff RESOLVED_IN_SET; NOT_ATTEMPTED iff 0
```

A resolver that raises is `UNRESOLVED` with no attempt; an adapter that raises is `CONNECTION_ERROR`
with the one attempt it made. **No address, host name, port or timing reaches the receipt.**

**The isolation verdict is not the task's.** The receipt line renders
`isolation_verdict=NOT_DECIDED_BY_THE_TASK`, and the launch tool records the verdict beside the
receipt under this rule (`isolation_verdict`):

- `CONNECTED` **fails** R-2 for that destination and instant, whatever any corroboration says;
- a non-connection is **`INCONCLUSIVE`** — a destination failure, a remote rejection, a resolver failure
  and a transient condition produce the same observation as a network control;
- **`VERIFIED`** requires a non-connection observed on an actual attempt (`probe_attempts = 1`) **and**
  one corroboration of the one kind this ADR admits.

**The admitted corroboration is a VPC Reachability Analyzer analysis** (`CorroborationKind.
REACHABILITY_ANALYSIS`), recorded as four closed facts: `source_interface_matches` (the analysis's
source is the task's network interface, as the release names it), `destination_matches` (its
destination is the probe's IP address and port), `network_path_found` (`false` required), and
`blocking_components` — a non-empty subset of `ROUTE_TABLE`, `SECURITY_GROUP`, `NETWORK_ACL`, `SUBNET`
naming the component of **this VPC's own controls** the analysis attributes the block to. An analysis
that found a path, or names no component, corroborates nothing.

**Why this kind, and its limits, stated.** Reachability Analyzer evaluates the account's **network
configuration** — route tables, security groups, NACLs, endpoints — and reports whether a path exists
and, when none does, which component blocks it; it sends **no packets**, so it establishes what the
configuration permits, not what happened on the wire at the probe's instant. That is the complement
the probe lacks: the probe observed one instant on the wire and cannot attribute it; the analysis
attributes and cannot observe. Neither alone is an isolation finding; the two together, for the same
source interface and destination, are what `VERIFIED` means here. Its costs and prerequisites are
stated rather than absorbed: each analysis is **charged per analysis**; it needs the interface to
exist (so the analysis runs while the verification task is placed, or against the interface the
release names before it is released); and it needs permissions **no declared principal holds** —
`ec2:CreateNetworkInsightsPath`, `ec2:StartNetworkInsightsAnalysis`, `ec2:DescribeNetworkInsights*`
and `ec2:DeleteNetworkInsights*`. **That IAM delta is not granted by this ADR** and is recorded as a
remaining owner input; until it is declared and applied, every R-2 non-connection stays
`INCONCLUSIVE`.

**VPC Flow Logs are not admitted as corroboration**, and the reason is recorded. A `REJECT` record
attributes a drop to "security groups or network ACLs" collectively (the `reject-reason` field is
`-` for those), names no rule, cannot distinguish a security-group drop from a NACL drop, records no
drop for a packet that had **no route** (the case a subnet with no internet route produces), needs
flow logs enabled on the interface or subnet, and is delivered minutes after the fact. It may be kept
as supplementary evidence in the owner's record; it never turns `INCONCLUSIVE` into `VERIFIED`.

---

## 4. Decision — Route B: the observation build, and what its evidence is

**An accepted-schema set may be explicitly empty**, and an empty set admits nothing. A build image
whose configuration carries an empty set for every dataset is the **observation build**: it reads the
run's locators and objects exactly as a production build does, parses every page through the accepted
parser, and — because no header is admitted — refuses at normalization with **`REFUSED_NORMALIZATION`**
(`SCHEMA_UNSTABLE`), **zero Silver, Gold or manifest writes**.

**Its receipt carries what it saw** (ADR-0044 §4's field set, extended by one block):
`schema_observation`, with `complete` and, per dataset, the sorted distinct header digests observed,
the pages parsed and the pages total. `silver.normalize` collects every page's digest **before**
refusing: a page the parser cannot read (`PAYLOAD_UNPARSEABLE`) is counted as unparsed and the
observation is **`PARTIAL`**, so a refusal over a broken delivery is never presented as a complete
survey. The digest is `schema_digest_of` — the same function the qualification parser uses, so an
observed digest and an accepted one are comparable by construction.

**An observed digest is evidence for owner review, never an accepted set.** Nothing in the package
writes an observation into an `AcceptedSchemas`; a static test holds that no production module
constructs an accepted set from an observation, and the receipt validator admits the block **only**
on a build entry's `REFUSED_NORMALIZATION` receipt. Promoting an observed digest into a configuration
is an explicit owner act — a new compiled configuration, a new image digest, a new revision — and this
ADR authorizes none of it.

---

## 5. Decision — two verification families, and exactly one more `RunTask` resource per launcher

**ADR-0036 §2.9 is amended narrowly.** Beside each actor's production task-definition family, a
verification family (`kalpamani-production-acquire-verify`, `kalpamani-research-build-verify`) is
declared with **the same task role, the same execution role, the same network placement, the same
`user`, read-only root filesystem and `/work` tmpfs**, and the verification image pinned by its own
digest. Each family exists only at stage `a` or `b` **and** only when `production_image_digests` names
its key (`acquisition_verify`, `build_verify`); any other key is refused by the variable's validation.

**Each launcher permission set gains exactly one more `ecs:RunTask` resource**: its own actor's
verification revision, as a `concat` of the production revision and the verification family's
revision list — never a wildcard, never a family ARN, never the other actor's, and nothing when no
verification digest is declared. The `iam:PassRole` allowlist is unchanged (the same two roles), and
**no assignment changes**: the mutation test that a stage-b digest rotation touches no assignment
covers the verification families too.

**Why not a rescoped production launcher.** Running R-1/R-2 with the production image and a deliberately
absent release exercises only the negative cells, and moving the launcher's single `RunTask` resource
between images needs two applies per verification with a window in which the launcher can run the
wrong revision. A second family per actor is the least-privilege shape.

---

## 6. Decision — the owner-side launch tool, and one identity for one authorization

`scripts/production_launch.py` and `launch_records.py` implement ADR-0036 §2.12 on the workstation,
composing `human_bootstrap` and `launch_authorized_run` and adding nothing to their contracts.

**Records, each parsed closed.** The **owner ledger** (`kalpamani-owner-ledger/v1`): every identity ever
launched, production or verification, with actor, kind, outcome, `evidence` (`EXIT_CODE_ONLY` |
`RECEIPT_VERIFIED`), the instants and — acquisition rows — the slice and plan digest. The
**launch-inputs record** (`kalpamani-launch-inputs/v1`): cluster, execution role, binding key, platform
version, and per actor the task role, subnet, security groups and the registered production and
verification targets (revision ARN, image digest, configuration digest, code commit) — values the
owner transcribes from Terraform outputs and the generation records, never typed into a command. The
**authorization record** (`kalpamani-launch-authorization/v1`): the owner's written authorization for
one launch of one identity of one kind, valid for at most 24 hours; a flag is never a substitute. The
**launch record** (`kalpamani-launch-record/v1`): what the tool holds about one launch it made — the
task ARN, the revision, the image and configuration digests, the commit, the identity and the input
digest — exactly a `ReceiptExpectation`, owner-private, never exported. The **evidence document**
(`kalpamani-launch-evidence/v1`): outcome, counts, incident, cleanup failures, exit codes — tokens and
integers, no ARN, no identifier.

**Input materialization uses the accepted digest functions and the task's own contract.** Acquisition
input v2: `plan_digest_for` over the slice, `spent_identities_block` over the ledger's **whole**
identity set, re-parsed by `parse_acquisition_input` before it leaves the tool. Build input v1: the
rows of the named run identities, `ledger_digest`, re-parsed by `parse_build_input`. Only a
`RECEIPT_VERIFIED` `COMPLETED` production acquisition row is buildable; an `EXIT_CODE_ONLY` row, a
`VERIFIED` row and a halted row are refused.

**Verification identities are their own namespace.** A verification identity carries the reserved
prefix **`verify-`**; a production identity may not. A verification task reserves nothing (§2), so the
store would never refuse the same identity launched for production later — which is exactly why the
ledger records it as consumed and the next acquisition input's spent block carries it: **an identity in
the ledger is consumed for both kinds, whatever its outcome**, and the tool refuses to launch it again.
An identity is consumed by its **authorization**: a launch attempt that never started a task still
writes a `REFUSED` row.

**Configuration equivalence is checked before a verification launch.** The verification file must
parse, name the production file's code commit, be the production entry's own verification entry, and
carry the acquisition configuration's origin set (the build verification file is compared against the
acquisition file's set, because the production build file has none); and it must be the file the
launch-inputs record registered (its digest and commit). Any other verdict — `CODE_DIFFERS`,
`ORIGIN_DIFFERS`, `ENTRY_MISMATCH`, `UNREADABLE` — refuses the launch.

**The authorized branch.** `human_bootstrap` under the actor's human profile and again under its
launcher profile (`launcher_profile`, a constant this ADR adds to the actor vocabulary — routing
input, never proof), each proving its own identity against the private binding file before any
adapter exists; then the four real clients — built only here, only from `boto3.Session(profile_name=…)`
under the two pinned profiles, with one attempt in total and finite socket timeouts — and
`launch_authorized_run` with its before-and-after proofs. **No `RunTask` is ever retried**: an
ambiguous outcome (`OBSERVATION_TIMEOUT`, `OBSERVATION_FAILED`, an unknown exit code, no exit code) is
recorded as `HALTED` with `EXIT_CODE_ONLY` evidence and the identity stays consumed. A misplaced task is
stopped by the launcher with no release written and recorded as `MISPLACED`.

**A provisional row is what the exit code supports.** `COMPLETED` from exit `0` on a production launch
and `VERIFIED` from exit `18` on a verification launch — each the other way round is `HALTED`, because
an image that did that has done something the record cannot name; `REFUSED` for every entry refusal and
for a task that never started; `HALTED` for a halt or an ambiguous state. **A `COMPLETED` row written
from an exit code is not buildable** until `--complete-row` verifies the task's receipt — the line the
owner reads from the log stream by hand until the deferred collector exists (ADR-0044 §5) — against the
launch record's expectation and replaces the row with the receipt's disposition; a receipt that
establishes none leaves the row provisional, and a row is never completed twice.

**Containment.** The ledger, the launch records and the evidence are written only beneath the private
root (`%LOCALAPPDATA%\KalpaMani\private`, ADR-0023); a path outside it is refused before any record is
read, so an identity, a slice or an ARN can never be written into a tracked tree by this tool.

**Remaining dependency, not built here.** The production human-binding files the tool loads
(ADR-0036 §2.5) have no materializer; the qualification materializer writes a different contract. It
is recorded as G-4, unchanged.

---

## 7. Decision — re-verification (G-12)

**R-1 and R-2 are evidence about one commit and one verification image.** They are repeated when
either changes: a new code commit, or a new verification image digest. A new **production** image
digest alone — the same commit, a regenerated configuration — does not require them, because a
verification task exercises none of the production image's bytes (§2) and its pass never claimed to;
the production run's own release, identity proof and receipt are that image's evidence. **A stage-b
digest rotation therefore requires no re-verification and touches no assignment**; a commit change
requires both families rebuilt and R-1/R-2 re-run before the production revision is launched.

---

## 8. Amendments stated

| Accepted text | Amendment |
|---|---|
| ADR-0043 §2 (two closed entries) | four; the two verification entries bootstrap-only, `VERIFIED_BOOTSTRAP` exit 18 |
| ADR-0036 §2.9 (task definitions; the launcher's `RunTask` resource) | one verification family per actor; the launcher's resource set is `concat([production revision], verification revision list)` |
| ADR-0036 §3 (R-1 / R-2) | run with the verification image; R-1's expected exit is 18; R-2 reads the probe under §3's verdict rule; corroboration is Reachability Analyzer only |
| ADR-0036 §2.6 (the owner ledger) | rows carry `kind` and `evidence`; verification identities are consumed rows; the `verify-` prefix is reserved |
| ADR-0036 §2.12 (the launch tool) | implemented as §6; the ledger row is provisional until receipt-verified |
| ADR-0044 §2 (compiled configuration) | the verification field set (origin addresses only); `is_known_family` |
| ADR-0044 §4 (the receipt) | `kalpamani-task-receipt/v2`: `probe` (build verify, `VERIFIED_BOOTSTRAP` only) and `schema_observation` (build, `REFUSED_NORMALIZATION` only); `VERIFIED` added to the ledger outcomes |
| ADR-0040 / the build's output rule | an explicitly empty accepted set is admitted, refuses at normalization, and writes nothing |

No accepted document is edited; each is amended by this text alone.

---

## 9. Effectiveness and execution gates

Acceptance of this ADR authorizes **no** image build, publication or pull; **no** Terraform plan or
apply; **no** launch of any kind; **no** run; **no** probe; **no** Reachability Analyzer analysis; **no**
IAM change (the analyzer permissions are a recorded delta, not a grant); **no** bucket-policy change
(G-14 stays deferred). The verification entries, the launch tool and the Terraform declaration have
never run against AWS; every result recorded beside them is a synthetic one. **G2 stays OPEN, CONTROL
stays DEFERRED, Phase 3 stays NOT COMPLETE, live trading stays HARD-DISABLED.**
