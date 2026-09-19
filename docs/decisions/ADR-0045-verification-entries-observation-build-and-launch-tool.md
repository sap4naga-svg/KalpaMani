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

**The condition above has since been satisfied.** **PR #104 merged** — merged **2026-09-14T17:28:56Z**,
merge commit **`af20f36acbe8a3006830762fbad5cb01d1e9b38b`**, ordered parents **`8464128a9d890a5d43c2a685927742cad8428f8f`** then
**`2966ed2f24f7841eea264657f75e9c081e35922a`** (the approved head, after two independently reviewed correction cycles
recorded in §10), with a **merge tree identical to the reviewed pull-request head tree**
(`f43beef329511e53a79777e1301ee9901d9945e3`). ADR-0045 is therefore **ACCEPTED / IN FORCE** exactly as the clause
above states — the verification-path completion of ADR-0043 §2 and ADR-0036 §2.9 / §3, the receipt
evidence, the isolation rule, the verification families and the launcher resource, the launch tool
and its records, the re-verification policy, the narrow amendments to ADR-0036, ADR-0043 and ADR-0044
it states, and its §10 corrections — effective together with the offline code merged beside it, and
nothing else. While the pull request was open it was proposed and carried no authority — true then,
and not rewritten. **Acceptance authorized no image build, no publication, no Terraform plan or
apply, no launch, no run, no probe, no Reachability Analyzer analysis and no IAM change**: the
analyzer permissions (D-14) stay a recorded delta, `ecs:DescribeTaskDefinition` (V-16) stays a
recorded dependency, G-14 stays deferred, and every owner input stays MISSING. The owner-side tooling
that composes these contracts — the human-binding materializer, the R-3 tool and the cell runner —
was proposed separately as ADR-0046 (since accepted on the merge of PR #105).

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
to the origin. The destination is deterministic from the compiled set and the task's own
resolution; the task records it under a keyed digest (below), and the launch tool recovers it from
that record — never from a resolution of its own.

**The observation is closed, and it binds the destination the task actually selected.** The
receipt carries four fields:

```text
probe_resolution    RESOLVED_IN_SET | RESOLVED_OUTSIDE_SET | UNRESOLVED
probe_result        CONNECTED | CONNECTION_REFUSED | TIMED_OUT | CONNECTION_ERROR | NOT_ATTEMPTED
probe_attempts      0 | 1     -- exactly 1 iff RESOLVED_IN_SET; NOT_ATTEMPTED iff 0
probe_destination   the keyed digest of the selected destination, or none -- present iff attempted
```

A resolver that raises is `UNRESOLVED` with no attempt; an adapter that raises is `CONNECTION_ERROR`
with the one attempt it made. **No address, host name, port or timing reaches the receipt.** The
destination is named by `destination_binding_digest(input_digest, address, 443)` — a SHA-256 keyed
by the admitted input's digest, which the launch tool holds in its own record and a log reader does
not (an unkeyed digest of an IPv4 address would name it to anyone). The tool recovers *which*
compiled address the task selected by recomputing the digest for every address of the compiled set;
**it never infers the task's DNS result from a later resolution or from the set alone**, and an
observation whose digest recovers no compiled address is unbound (`DESTINATION_UNBOUND`).

**The isolation verdict is not the task's.** The receipt line renders
`isolation_verdict=NOT_DECIDED_BY_THE_TASK`, and the launch tool records the verdict beside the
receipt under this rule (`isolation_verdict`):

- `CONNECTED` **fails** R-2 for that destination and instant, whatever any corroboration says;
- a non-connection is **`INCONCLUSIVE`** — a destination failure, a remote rejection, a resolver failure
  and a transient condition produce the same observation as a network control;
- **`VERIFIED`** requires a non-connection observed on an actual attempt (`probe_attempts = 1`) whose
  destination digest recovers a compiled address, **and** one corroboration of the one kind this ADR
  admits, **bound by derivation** to that task, that destination and that instant.

**The admitted corroboration is a VPC Reachability Analyzer analysis** (`CorroborationKind.
REACHABILITY_ANALYSIS`), transcribed by the owner into a closed document
(`kalpamani-reachability-evidence/v1`) whose fields are the documented `NetworkInsightsAnalysis`
and `NetworkInsightsPath` attributes: `analysis_id`, `path_id`, `status` (`running | succeeded |
failed`), `network_path_found`, `start_date`, the path's `source_interface_id`, `destination_ip`,
`destination_port`, `protocol` (`tcp | udp`), and the `explanations` — each an `explanation_code`
with the component object it names (`component_kind` ∈ `SECURITY_GROUP | NETWORK_ACL | ROUTE_TABLE |
SUBNET`, `component_id`, and the `subnet_id` named beside it). **No match is supplied**: the verdict
derives every comparison itself, in this order, and the first that fails names the reason —

```text
OBSERVED_CONNECTION                 CONNECTED -> FAILED, whatever the evidence
NO_ATTEMPT · DESTINATION_UNBOUND    no attempt, or a digest that recovers no compiled address
NO_CORROBORATION                    no evidence supplied
ANALYSIS_NOT_SUCCEEDED              status != succeeded
SOURCE_MISMATCH                     the path's source is not the interface the release named
DESTINATION_MISMATCH                the path's destination is not the recovered address, TCP, 443
ANALYSIS_OUTSIDE_TASK_WINDOW        start_date outside [launched_at, recorded_at] -- a later analysis
                                    models a configuration the task never had
PATH_FOUND_CONTRADICTS_OBSERVATION  the model found a path while the wire did not: contradictory
UNSUPPORTED_EXPLANATION             no explanation carries an admitted code on the component kind it
                                    attributes to (ENI_SG_RULES_MISMATCH, SG_HAS_NO_RULES -> security
                                    group; SUBNET_ACL_RESTRICTION -> network ACL; NO_ROUTE_TO_DESTINATION
                                    -> route table; every other documented code -- NO_PATH,
                                    NO_POSSIBLE_DESTINATION, UNKNOWN_*, VPC_BLOCK_PUBLIC_ACCESS_ENABLED,
                                    the load-balancer, gateway, peering and transit codes -- attributes
                                    nothing to the four admitted components)
COMPONENT_OUTSIDE_PLACEMENT         the admitted explanations name a security group that is not one
                                    of the task's compiled groups, or a route table / NACL / subnet
                                    not placed by the task's subnet
CORROBORATED                        -> VERIFIED, with the components the evidence named
```

Every case but the last is `INCONCLUSIVE`. **Configuration-model evidence stays distinct from the
packet observation**: the receipt block is what the wire returned once; the evidence document is what
the model predicts; the verdict record carries both, and `analysis_bound` says whether the analysis
was ever tied to this task at all.

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
`INCONCLUSIVE`. The launch tool's `--isolation-verdict` mode derives and records the verdict from the
verified receipt, the launch record (which carries the interface and subnet the release named and
the instants the launch was made and recorded) and the owner's transcription; it collects no
analysis, and **`VERIFIED` is unreachable without one**.

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
version, the R-3 verification digest (or none at stage a), and per actor the task role, subnet,
security groups and the registered production and verification targets — revision ARN, image digest,
configuration digest, code commit, the generation-record digest, and the **task-definition evidence**
(family, revision, roles, cpu, memory, network mode, platform, `user`, read-only root, `/work` tmpfs,
command, image digest) the owner transcribes from the post-apply verification — values transcribed
from Terraform outputs and the generation records, never typed into a command. **The task-definition
evidence is owner-supplied and validated offline**: the launcher permission sets hold no
`ecs:DescribeTaskDefinition`, so the tool cannot read a revision back; that a transcription is
faithful is not something the tool establishes, and the permission is recorded as a dependency, not
added. The **launch specification** (`kalpamani-launch-specification/v1`): the canonical, reviewable
statement of one launch that preparation writes and an authorization binds (below). The
**authorization record** (`kalpamani-launch-authorization/v1`): the owner's written authorization for
one launch of one identity of one kind **of one specification digest**, valid for at most 24 hours;
a flag is never a substitute. The **reservation** (`kalpamani-launch-reservation/v1`): the durable
consumption of one identity for one specification, created before any external mutation and never
deleted — it **carries the whole authorized specification** and its digest, so the placement and
workload that were authorized are read back from the durable artifact and never from a later file.
The **launch record** (`kalpamani-launch-record/v1`): what the tool holds about one launch it
made — the task ARN, the revision, the image and configuration digests, the commit, the identity, the
input digest, the instants the launch was made and recorded, the network interface, subnet and
**security groups the launcher verified** (the groups `DescribeNetworkInterfaces` reported on the
task's interface, equal as a set to the compiled groups or the task was misplaced), and the
**specification digest** the authorization named — exactly a `ReceiptExpectation` plus the R-2
binding and the binding to its reservation, owner-private, never exported. The **evidence document**
(`kalpamani-launch-evidence/v1`): outcome, counts, incident, cleanup failures, exit codes — tokens
and integers, no ARN, no identifier. The **isolation verdict** (`kalpamani-isolation-verdict/v1`): the
probe block, the derived verdict, its reason and components, and the specification digest.

**The authorization binds the whole launch, through the specification.** Preparation (no flag)
builds the specification from the admitted records — actor, kind, identity, entry; the workload
(the acquisition slice and its `plan_digest_for`, or the selected build runs with the ledger evidence
each carried); the registered target (revision, image, configuration, commit, generation-record
reference, task-definition evidence); the placement (cluster, subnet, security groups, public-IP
setting, roles, platform version, binding key); and the gate evidence (the R-3 digest, applicable to
a production launch and not to a verification launch, and the generation-record reference) — writes
it beside the ledger for review, and prints its SHA-256. The owner's authorization names that digest.
Execution rebuilds the specification from the same records and refuses any authorization naming
another digest (`AUTHORIZATION_MISMATCH`) **before any client exists**, and revalidates the
authorization's validity window **immediately before the first external mutation**. **The digest is
neither circular nor unstable**: it is over what is authorized and excludes the input's issue and
expiry instants and the ledger's spent-identity set, so a ledger that grows between preparation and
execution changes the spent block and nothing the owner authorized, while a changed slice, a changed
run selection or a changed run's own ledger evidence, a changed registered target or a changed
placement changes the workload and refuses. A gate-evidence digest in the specification is a
**reference to owner-held evidence**, never proof that the approval it refers to occurred.

**The identity is consumed durably before any external mutation.** Under an exclusive ledger lock,
the ledger is re-read, the identity re-checked against it and against the ledger's reservations,
and a reservation carrying the specification and naming its digest is created with
`O_CREAT | O_EXCL` — before the bootstrap, before any client. A reservation that already exists
refuses; one that cannot be persisted refuses; **a reservation is never deleted and never expires**,
through cleanup, failures, ambiguous outcomes and interruptions. Every ledger write — the
provisional row, its completion, recovery — happens under the same lock and replaces the ledger
atomically (a fresh temporary file, synced, `os.replace`d) after re-checking that the ledger's bytes
are the ones read, so a read-modify-write cannot lose an update; a lock another process left is
refused and never removed by the tool. Evidence and launch records are created under exclusive names
carrying the instant and eight random hex digits, so two records in one second cannot collide or
overwrite. **An interrupted attempt** — a crash after the reservation, after `RunTask`, or a failed
record or ledger write — leaves the reservation with no ledger row; every later launch of any
identity refuses (`refused_recovery_pending`) until the owner runs `--recover`, which writes a
`HALTED`, `EXIT_CODE_ONLY` row for the reserved identity — its slice and plan digest from the
reservation's own specification, its launch instant from the launch record when one is visible and
names the same specification, otherwise the reservation's — launches nothing, and keeps the
reservation. What a task that started before the interruption did, the tool does not know and does
not guess; the owner reviews ECS by hand. **This owner-side reservation is distinct from the
acquisition task's accepted S3 run reservation** (ADR-0038): the store's reservation guards the
identity against the provider; the workstation's guards it against the owner's own tool. A
verification task still reserves nothing in the store. Durability is the platform's: NTFS honours
exclusive creation and atomic replacement on one volume; a power loss before `fsync` returns can lose
a write, and Windows syncs no directory entry separately — stated as limits, not designed away.

**The reservation's location depends on the ledger and on nothing else.** Reservations live at
`<ledger>.reservations/<identity>.json` and the lock at `<ledger>.lock`, both beside the ledger's
**canonical** path (`Path.resolve`: absolute, symlinks followed, the platform's own spelling), so a
relative spelling, a `..` segment, another case on a case-insensitive volume or a symlink names the
same reservations and the same lock. `--records-dir` is an **evidence destination and nothing more**:
naming a different one — or the same one spelled differently — changes where evidence and launch
records are written and nothing about which identities are consumed or await recovery; recovery finds
the reservation from any records directory, and a launch record it cannot see there yields an honest
`HALTED` row from the reservation alone, never a released identity. **Legacy state:** the first
revision kept reservations under `<records-dir>/reservations`. No launch has ever run against AWS, so
no real reservation exists there; still, such a directory with any entry under the supplied records
directory refuses (`refused_legacy_reservations`) until the owner has moved its files beside the
ledger by hand and unchanged — the tool reads, moves, migrates and deletes none of them, and scans no
directory it was not handed. A first-revision reservation document carries no specification and is
refused as malformed rather than read.

**The verdict binds to the recorded placement, and every artifact of one launch binds to the
others.** The launch record names the specification digest the authorization named and carries the
placement the launcher verified — interface, subnet and the security groups the interface carried.
Completion and the verdict both require the record's reservation beside the ledger, with the same
specification digest, the same actor, kind and entry, the same registered target (revision, image,
configuration, commit), the same acquisition workload, and a verified placement the specification
named (its subnet; its security groups as a set); the verdict further requires the identity's ledger
row and a build-verification receipt that verified against the record. **The verdict's security
groups are the record's**, cross-checked against the reservation's specification — never a freshly
supplied launch-inputs file's. That argument is retained for the invocation's shape and is **verified
against the recorded specification**: a file compiling to another placement or another target refuses
(observed before the correction: a launch-inputs file listing an extra group turned
`COMPONENT_OUTSIDE_PLACEMENT` into `VERIFIED`; after it, exit 3 and no verdict written). A missing
reservation, a missing row, a record without a verified placement or a record naming another
specification refuses; nothing missing can establish `VERIFIED`. **The trust boundary is the
owner's private root.** These digests make a substituted or mislaid owner artifact a refusal — a
different records directory, a different launch-inputs file, a rewritten record; they are not
protection against an owner who deliberately rewrites every owner-controlled artifact consistently,
and this proposal does not claim that a stored digest protects against its own author.

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

**Configuration equivalence binds every file to its registered counterpart.** Before a verification
launch, the production file is bound to the actor's registered **production** target (digest, commit,
entry, family), the verification file to its registered **verification** target, and — for a build
pair — the acquisition file to the registered acquisition production target, because the build
verification image carries the acquisition origin set and the production build file carries none.
Then the two registered task-definition revisions are compared field by field: task and execution
roles, cpu, memory, network mode, platform, `user`, read-only root and the `/work` tmpfs **must
agree**; family, revision, command and image digest **differ by design**; anything else refuses. Then
the configurations: the same code commit, the verification origin set equal to the acquisition set.
The verdicts are closed — `EQUIVALENT`, `UNREADABLE`, `TARGET_MISMATCH`, `ENTRY_MISMATCH`,
`CODE_DIFFERS`, `ORIGIN_DIFFERS`, `TASK_DEFINITION_DIFFERS`, `EVIDENCE_MISSING` — and every one but
the first refuses the launch. **`EQUIVALENT` is a statement about configuration, never runtime
proof**: a verification task exercises none of the production image's bytes, none of its processing
path, and none of the fields only a production entry reads (the secret name, the build
configuration); those are exercised by nothing but a production run.

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
establishes none leaves the row provisional, and a row is never completed twice. Completion runs under
the ledger lock and through the same atomic replacement as every other ledger write.

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
| ADR-0036 §2.12 (the launch tool) | implemented as §6; the authorization binds a launch specification; the identity is reserved durably before any external mutation, beside the ledger and carrying the specification; ledger writes are locked and atomic; the ledger row is provisional until receipt-verified; interrupted work is recovered from any records directory, never relaunched; the launch record names the specification digest and the verified placement (interface, subnet, groups), and the R-2 verdict binds to that recorded placement |
| ADR-0044 §2 (compiled configuration) | the verification field set (origin addresses only); `is_known_family` |
| ADR-0044 §4 (the receipt) | `kalpamani-task-receipt/v2`: `probe` (build verify, `VERIFIED_BOOTSTRAP` only; resolution, result, attempts and the keyed `destination_digest`) and `schema_observation` (build, `REFUSED_NORMALIZATION` only); `VERIFIED` added to the ledger outcomes |
| ADR-0036 §3 (R-2 evidence) | the corroboration is one transcribed Reachability Analyzer analysis, bound by derivation; the launch tool records the verdict; task-definition read-back (`ecs:DescribeTaskDefinition`) is a recorded dependency of the launcher sets, not granted |
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

---

## 10. Corrections after the independent review of PR #104

Four findings against the first revision of this proposal were each reproduced through the real
modules on fakes before they were corrected, and the corrections are recorded here rather than
written as though the first revision had said them.

1. **Durable identity consumption came after external mutation.** The tool launched, then wrote the
   ledger with a direct write; an interruption after `RunTask` left the identity unrecorded and a
   second attempt launched it again (observed: `RunTask` count 1 → 2); two launches in one second
   overwrote one evidence file. Corrected by §6's reservation, lock, atomic replacement, exclusive
   record names and recovery.
2. **The authorization bound only actor, kind, identity and validity.** A changed slice launched under
   an unchanged authorization (observed: exit 0 with a different window). Corrected by the launch
   specification and its digest in the authorization, checked before any client and revalidated for
   freshness before mutation.
3. **Only the verification file was bound to a registered target.** An unrelated but valid production
   file, with a matching verification file, launched (observed: exit 0 with a production file whose
   digest was not the registered one); no task-definition evidence was compared. Corrected by binding
   every file to its own registered target and comparing the transcribed task-definition evidence
   field by field, with the intentional differences named.
4. **The verdict accepted supplied match booleans and no analysis identity.** `VERIFIED` was reachable
   from two `True` values (observed), the receipt did not identify the selected destination, and the
   tool never invoked the verdict. Corrected by the keyed destination digest in the receipt, the closed
   evidence document, the derived comparisons and reasons, the launch record's interface, subnet and
   instants, and the `--isolation-verdict` mode.

Each correction narrows a proposed contract; none weakens one. The receipt's probe block, the
authorization record and the launch record changed shape as stated in §8; the examples, parsers and
guards changed with them.

Two further findings against the corrected revision (`555fdf76…`) were reproduced the same way and
corrected in a second cycle:

5. **The reservation's location depended on the records directory.** Reservations lived under
   `<records-dir>/reservations`, so an interrupted attempt retried with the same ledger, identity and
   authorization and a different `--records-dir` found no reservation and launched again (observed:
   exit 0, `RunTask` 1 → 2, nineteen clients constructed), and `--recover` from another directory
   found nothing to recover (observed: exit 3). Corrected by anchoring reservations and the lock to
   the ledger's canonical path, by the reservation carrying the specification (so recovery's row
   comes from it), by treating the records directory as an evidence destination only, and by
   refusing first-revision reservations under a supplied records directory until the owner moves
   them (observed after: exit 12 before any client from any directory, `RunTask` stays 1; recovery
   from another directory writes the `HALTED` row; the identity stays consumed everywhere).
6. **The verdict took its security groups from a freshly supplied launch-inputs file.** The record
   carried the interface and subnet, but the groups came from `--launch-inputs`, unbound to the
   launch; a file listing an extra group turned an outside-placement explanation into `VERIFIED`
   (observed: `COMPONENT_OUTSIDE_PLACEMENT` → `CORROBORATED`). Corrected by recording the verified
   groups and the specification digest on the launch record, binding the record to its reservation
   and ledger row before completion or a verdict, deriving the verdict's placement from the record
   cross-checked against the reservation's specification, and verifying a supplied launch-inputs
   file against the recorded specification (observed after: exit 3, no verdict written; the
   untampered evidence still verifies; a widened record, a widened reservation, a missing
   reservation or a missing row each refuses). The trust boundary is stated as the owner's private
   root, not as a stored digest.

The reservation and launch-record contracts changed shape in this cycle as §6 states; the parsers,
the store, the launcher's report and the guards changed with them, and the examples are unchanged
(neither document is exemplified).

## 11. Amendment (2026-09-17) — a verification-only build launch may carry an empty run set

**Status: PROPOSED — NOT IN FORCE while the pull request carrying this section is open; nothing here is
deployed.** *[Since accepted: PR #120 merged 2026-09-17T02:07:08Z, merge commit `d5349d9516643af4dedddc7ada6af2c06fcb71d8`, ordered parents
`696749f6…` then `da6742c7…`; effective on that merge — true when written, not rewritten.]* It amends §6's build-input rule in one respect and leaves the production build's requirement
exactly as it was.

**The cycle it removes.** §6 admits only a `RECEIPT_VERIFIED` `COMPLETED` production acquisition row as a build
run identity, and the build input contract refused an empty run set (`NO_RUNS`) for every launch. The build
verification entry (`kalpamani-research-build-verify`, §2) terminates at the release barrier and reads no run
— yet its input could not be materialized before an acquisition had completed and been receipt-verified.
Readiness §4.3 makes "S9 verified" a prerequisite of S10a, so the build half of S9 depended on S10a's evidence
while S10a depended on S9: a cycle the readiness document did not spell out, established on 2026-09-17 when the
launch tool's prepare mode refused `R1-BLD-BOOTSTRAP` with `ROW_NOT_BUILDABLE` against a ledger holding only the
completed acquisition-verification row.

**The amendment.** A build **verification** launch may carry an **empty** run set: the launch tool materializes
the build input v1 with `runs = []` and the ledger digest over `[]` (for the verification kind only; a production
launch must still name at least one run), the build verification entry admits it on a `verification_only` path
of the build input parser that the production entries never take, and the task terminates at the barrier with
**zero data processing** — the verify entry has no processing path to enter. Every run that **is** named, for
either kind, must still be a buildable row. The production build (`run_production_build`, the
`kalpamani-research-build` entry) is unchanged: an empty run set is refused at its input stage (`NO_RUNS`),
before any release read, locator read or write, and an `EXIT_CODE_ONLY`, `VERIFIED` or halted row is refused
(`ROW_NOT_BUILDABLE`) as before. **Verification input cannot become a build, and verification cannot enter the
production processing path.**

**Held by regressions:** a build verification input is materialized from a ledger with no acquisition at all
and parses only on the verification-only path (`test_production_launch_records`); the production kind over the
same ledger refuses empty and unverified inputs alike, and a verification launch that names a run still needs a
buildable one (same); the build verify entry with an empty run set reaches the barrier and terminates
`VERIFIED_BOOTSTRAP` with zero data-plane, secret and provider operations
(`test_production_verification_entry`); the production build with the same empty input refuses at the input
stage with zero data-plane operations (`test_production_build_processing`).

**What it changes in the deployed system, stated.** The task-side parser lives in the image: the build-verify
image published at release `21fa654e` embeds the pre-amendment parser and would refuse an empty run set
(`REFUSED_INPUT`, exit 12). So the amendment has **no runtime effect until a build-verify image is built from a
release that contains it** — S1 (its compiled verification configuration is unchanged: origin addresses only),
S2, S3, a stage-b-preserving apply that **replaces** the `kalpamani-research-build-verify` task definition (revision
2) and updates the build launcher's `RunTask` resource, and a launch-inputs registration re-issue, after which
every earlier permission record reads HISTORICAL under the new registration digest. The acquisition images, the
production build image and the probe images need no rebuild for this amendment (their parsers are stricter, not
wrong). None of that is authorized by this amendment.

## 12. Amendment (2026-09-17) — the launcher's held-task hook is the R-2 corroboration attachment point

**Status: PROPOSED — NOT IN FORCE while the pull request carrying this section is open; nothing here is
deployed, and it changes no task image and no compiled configuration.** *[Since accepted: PR #121 merged 2026-09-17T12:43:29Z, merge commit `1c707d30bc53d585445822e315a2bfe83a4b7ccc`, ordered parents
`d5349d95…` then `07af84bb…`; the attachment point named here has since moved to the dedicated cell by §13 / ADR-0052, accepted on the
merge of PR #126 — true when written, not rewritten.]*

**Why.** §3 admits one Reachability Analyzer analysis as R-2's corroboration, bound by the verdict to the
launched task's own interface (`SOURCE_MISMATCH` otherwise) and to `[launched_at, recorded_at]`
(`ANALYSIS_OUTSIDE_TASK_WINDOW` otherwise). Selecting that interface from a family listing (`ListTasks`) is
weaker than necessary: the launch tool already holds the exact task it started, and ADR-0048 §3 already
gives the launcher a `while_running` hook that fires **after the release is written and before observation
begins**, only once a fresh `DescribeTasks` reports the started task `RUNNING` on the registered revision
with the registered image — the one moment a corroborating analysis should be started. That hook was
admitted for a released permission-probe launch alone.

**The amendment.** The hook is admitted for a released (`NORMAL`) **build verification** launch as well —
a compiled build verification target with a `verify-` identity — and for nothing else: never a production
launch, never an acquisition verification (its task holds the provider credential path and asks no
reachability question), never a negative release mode. The launch tool hands an injected hook through
unchanged and refuses an inadmissible one (`refused_arguments`) before its first bootstrap; the cell runner
passes a hook to exactly one cell, `R1-BLD-BOOTSTRAP`. The hook receives the exact started task's
description (`HeldTask`, the ARN held and never rendered) and its own failure never escapes; the sequence —
proofs, placement, release, observation, cleanup — is unchanged. **What the hook does under R-2** (create
the path from that task's interface to the compiled destination, start the analysis, log privately) is the
owner's separately authorized watcher, not part of this amendment; the verdict's binding checks are
unchanged and remain the proof.

**Held by regressions:** the hook rides a build verification launch and sees the started task after the
release and before observation (`test_production_runtime_launcher`); it is refused before anything is done
for an acquisition verification, a production launch of either actor and every negative release mode (same);
the tool refuses it with `refused_arguments` and constructs no client (`test_production_launch_script`); the
runner hands it to `R1-BLD-BOOTSTRAP` alone (`test_production_verification_cells`).

**Deployment impact: none.** The launcher runs on the workstation only; no task entry imports it; the
compiled configuration carries no field the hook reads. The build-verify image built from release
`d5349d95` (configuration `da807859…`) stays the image this hook will corroborate.


## 13. Amendment (2026-09-17) — the hook's attachment point is the dedicated `R2-BLD-CORROBORATION` cell

**Status: PROPOSED — NOT IN FORCE while the pull request carrying this section is open; it changes no
task image and no compiled configuration.** Proposed by ADR-0052, and effective with it. *[Since accepted: ADR-0052 is ACCEPTED / IN FORCE on the merge of PR #126 — 2026-09-17T18:53:23Z, merge commit
`01f77a10a2341b1d1d99a7fe0024b104563d692c`, ordered parents `d5407d8a…` then `a489f13f…`, merge tree identical to the reviewed head
tree — and this section with it; true when written, not rewritten.]*

§12 had the cell runner hand the `while_running` hook to `R1-BLD-BOOTSTRAP`. That cell has since run once
and PASSED on its receipt, while the hook's path request was refused by the service at parameter
validation (`Client.MissingParameter` — the deprecated `DestinationIp` form; corrected to
`FilterAtSource.DestinationAddress`, a workstation-only change). Attempting the analysis again under §12 as
written would mean re-preparing and relaunching a PASSED cell, rebinding its evidence. ADR-0052 instead
adds a dedicated R-2 runtime-launch cell, `R2-BLD-CORROBORATION`, under its own fresh identity and
specification, and **the runner hands the hook to that cell alone** — never again to `R1-BLD-BOOTSTRAP`,
never to the acquisition bootstrap, never to a negative. The launch tool's admission rule (a released build
verification launch with a `verify-` identity), the launcher's sequence, the `HeldTask` the hook receives
and the verdict's binding checks are unchanged; `R2-BLD-ISOLATION` is taken on the corroboration launch's
record. Nothing in §12 other than the named cell is amended.

---

## 14. Amendment (2026-09-18) — the store reads supported v1 reservations as evidence, never as authority (ADR-0054)

**Status: PROPOSED — NOT IN FORCE while the pull request carrying this section is open; it changes no
task image, no compiled configuration, no task definition, no Terraform, no IAM and no registration.**
Proposed by [ADR-0054](ADR-0054-historical-v1-reservations-and-registration-historical-rebinding.md) on 2026-09-18, and effective with it; the text above is preserved as accepted and is not rewritten. *[Since accepted: ADR-0054 is ACCEPTED / IN FORCE on the merge of PR #135 — 2026-09-18T17:35:07Z, merge commit
`8be462b953c33a6953429ee9edc321f843ab6ae1`, ordered parents `a5a6384f…` then `bbaa419d…`, merge tree identical to the reviewed head
tree — and this section with it; true when written, not rewritten.]*

§6's store gains one evidence-only read beside its strict one. `parse_reservation`, `LaunchStore.reservation` and
`reservations()` admit exactly what they admitted before; every execution path of the launch tool — recover,
isolation verdict, execute, complete-row and `prepare_launch`'s unreconciled check — still reads reservations only
through the strict `reservation()`, held by a source-inspection test. `parse_reservation_for_evidence` /
`evidence_reservation(s)` admit, in addition, a reservation whose acquisition workload was compiled under the
superseded `kalpamani-production-acquisition-plan/v1` contract (ADR-0053): strict parse first; on `FIELD_MALFORMED`
only, the closed envelope and the one superseded workload rule — the slice under the accepted slice parser, a plan
digest that is a digest and is **never recompiled**, actor acquisition — with the envelope's identity, actor, kind
and digest required to agree with the specification's. The result is a distinct `HistoricalReservation` carrying
the stored file's SHA-256; a document the strict parser admits is refused `WORKLOAD_CURRENT`; unknown schemas,
corrupted bytes, digest mismatches, build workloads and every other v1 shape stay `RESERVATION_MALFORMED`; a
historical reservation without a ledger row is `RESERVATION_ORPHANED`. No identity or filename is special-cased,
original bytes are never rewritten, and a historical reservation is never reservable, executable, recoverable,
collectable or admissible — §7's rule reads it `HISTORICAL`, checked rather than remembered.

---

## 15. Amendment (2026-09-18) — bounded read-only re-polling, sanitized poll evidence, and the post-start stop invariant

**Status: PROPOSED — NOT IN FORCE while the pull request carrying this section is open; it changes no
task image, no compiled configuration, no task definition, no Terraform, no IAM and no registration.**
It amends §6's launch tool in three respects and leaves launch identity, image verification, placement
verification, the release barrier, the operation-count bounds, identity consumption, reservation semantics,
the parameter lifecycle, the receipt contracts, every deadline ceiling and the fail-closed rule exactly as
they were. The text above is preserved as accepted and is not rewritten.

**What it corrects.** On 2026-09-18 two independent production launches of one logical O-5 run (two fresh
identities, one unchanged plan) were refused `REFUSED_PLACEMENT_UNVERIFIED` with the same signature: `RunTask`
accepted, the attachment reached `ATTACHED`, placement verified through one `DescribeNetworkInterfaces` with no
incident, and then the **fourth `DescribeTasks` — the first poll of the image-digest wait — raised a
`ComputeError`**, 21.6–21.7 s after acceptance, well inside the 120 s placement ceiling; the same path had
completed 13 of 13 times under identical configuration. The retained evidence (`kalpamani-launch-evidence/v1`:
outcome, counts, incident, cleanup failures, exit codes) **does not establish the exception class or service
code** of either failure, and this record does not infer one. On that path the launcher issued no `StopTask`, and
the task — already accepted by ECS — started against an input the launcher had deleted and failed closed at its
own input stage (`REFUSED_INPUT`, exit 12). Both attempts stay halted pre-release launches with zero provider,
secret, S3, reservation and locator activity; neither is reinterpreted by this amendment.

**A. Sanitized poll evidence.** A `ComputeError` raised from a backend exception now carries two bounded,
sanitized diagnostics beside its closed operation and category: the exception's **class name**
(`EXCEPTION_CLASS_RE`, `[A-Za-z_][A-Za-z0-9_]{0,63}`) and the **validated service error code**
(`SERVICE_CODE_RE`, `[A-Za-z][A-Za-z0-9.]{0,63}`); a value outside its grammar is dropped, never truncated or
repaired, and nothing is invented. Every failed read-only poll of a launch is retained in the evidence document as a
`PollDiagnostic` — phase (`PLACEMENT`, `IMAGE`, `OBSERVATION`), operation, category, the two diagnostics, the
attempt number inside the phase, the elapsed milliseconds since the phase began, the retry classification and the
disposition — and nothing else: **no exception message, request parameter, task ARN, interface, account, endpoint,
credential, raw response or free text has a field to arrive through**, and the document builder refuses an entry
outside the closed field set before the document exists. The evidence document is
`kalpamani-launch-evidence/v2` (`diagnostics`, `stop_outcome` added; every v1 field unchanged); v1 documents
written before this amendment are preserved as written and are never re-read by the tool
(`SUPERSEDED_EVIDENCE_CONTRACT_IDS`). The isolation verdict, the launch record, the receipt and the ledger are
unchanged.

**B. Bounded read-only re-polling.** A `DescribeTasks` that fails inside the placement, image-digest or
observation loop is classified from its closed category and sanitized class — `THROTTLED`, `TRANSIENT`,
`TRANSPORT` (a connection the SDK could not open, keep or read within its accepted timeouts), `UNKNOWN`, or
`TERMINAL` (denied, not found, invalid request, invalid response, invalid configuration) — and:

- a throttled, transient or transport failure is repeated after the phase's accepted interval at most
  `MAX_CONSECUTIVE_POLL_FAILURES = 3` times in a row; an unknown failure at most `MAX_UNKNOWN_POLL_FAILURES = 1`,
  recorded as `UNKNOWN`; a valid response resets the streak;
- every repeat (`RE_POLLED`) is the **read-only poll alone**, only while another interval still fits inside the phase's
  **unchanged** ceiling measured from the phase's own start (placement and image 120 s, observation 3,600 s):
  the ceiling is never extended and no second `RunTask` exists on any path;
- placement and image verification succeed **only on a later valid `DescribeTasks` response**; an exception is
  never read as a state; a terminal class (`REFUSED_CLASS`), the bound (`REFUSED_BOUND`) and the ceiling
  (`REFUSED_DEADLINE`) refuse exactly as before — `REFUSED_PLACEMENT_UNVERIFIED` or `OBSERVATION_FAILED`;
- the SDK client configuration (one attempt in total, finite timeouts), the provider and task-side retry rules
  and every other operation's policy are unchanged; the held-task readiness loop (§12) is unchanged.

**C. The post-start stop invariant.** Once `RunTask` has accepted a task, every terminal refusal before the task's
own terminal state — and an exception nothing classified — (1) writes no release, or leaves the written release to
the prescribed cleanup, (2) issues **one** bounded, best-effort `StopTask` on **this task only**, unless the last
valid description already reported it terminal, (3) records `stop_outcome` (`STOPPED`, `STOP_FAILED`,
`ALREADY_TERMINAL`; `NOT_APPLICABLE` exactly when no task was accepted), (4) runs the prescribed parameter cleanup,
(5) preserves the primary refusal separately from the stop and the cleanup, (6) never reports success because a
stop or a cleanup succeeded, and (7) never hides a failed stop, which is a `STOP_TASK` cleanup failure beside the
refusal. The placement-mismatch and stale-release stops are unchanged and count as that one stop. One observable
consequence is stated rather than left implicit: `OBSERVATION_TIMEOUT` — the launcher's 3,600 s observation
ceiling — now stops the task instead of leaving it running under a release the cleanup then deletes; the
acquisition task's own 1,800 s deadline sits inside that ceiling, while a build that legitimately needs the whole
of its own 3,600 s deadline after its barrier could be stopped by it — the ceilings are unchanged here (lowerable,
never raisable) and that consequence is recorded for the owner.

**Deployment impact: none.** The launcher module is imported by the owner-side launch tool, the permission-cell
tool and the reachability hook, and by no task entry; no compiled configuration or image contract binds its
behaviour; `kalpamani-launch-evidence/v2` is a workstation record. No image is rebuilt or published, no task
definition, Terraform, IAM or registration changes, and the registered images, configurations and revisions are
exactly as deployed. Held by focused regression tests over the launcher's fakes — the two recorded 2026-09-18
signatures reproduced as fail-before / pass-after fixtures without altering the historical evidence — and by
mutation controls that remove the bound, extend the deadline, suppress the stop, retry `RunTask`, read an
exception as state, store the message or mask a cleanup failure, each caught.

---

## 16. Amendment (2026-09-19) — the build launch binds the preserved locators; a sized, closed refusal (ADR-0055)

**PROPOSED — NOT IN FORCE while the pull request carrying this section is open; in force on the exact-head
merge of that pull request, together with ADR-0055.** The accepted text above is not rewritten.

**§6, the build-side preparation.** For a production build the launch tool now reads the owner's preserved
run locators from beside the ledger (`<ledger dir>/locators/run-locator-<identity>.json`, one per named run,
each at most the locator ceiling), holds each to its ledger row through the unchanged accepted validator
(`bind_run_locators`: `LOCATOR_MISSING`, `LOCATOR_REFUSED`, `LOCATOR_DIGEST_DUPLICATE`), and materializes the
**version-2** build input over the identities and the locator digests. A verification-only build launch
names no run and reads no locator (§11 unchanged). The materializer applies the advanced-tier ceiling to the
canonical bytes **before returning them** (`INPUT_TOO_LARGE`), and the launch tool reports that as one closed
refusal — `refused_input_size`, exit code **20**, one allowlisted sentence, no traceback — before any
specification, reservation, ledger row, consumed identity, file or client exists; the launcher's constructor
boundary is wrapped so that even an oversized value reaching it is the same closed refusal, never a raw
`ValueError`. The two defects the S10c preparation stop recorded on 2026-09-19 are those two, and they are
what this section corrects.

**§7 applies as written.** The build and build-verification actor families change commit under ADR-0055;
both are rebuilt from the merge commit's exact tree and their R-1/R-2 cells re-run before a production build
revision is launched; the acquisition families are unchanged and their images stay at their published commit.
The runner derives what that makes of the current build-family cells — nothing here hand-marks a cell.

**Unchanged:** the specification's workload (the ledger rows a build names; the locator binding lives in the
input, never in the workload), the reservation, the one-identity-per-authorization rule, the release, the
receipt, the ledger-row completion and every other exit code and sentence.

