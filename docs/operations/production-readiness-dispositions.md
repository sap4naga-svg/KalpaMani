# Production readiness — finding dispositions (PR #103 correction cycles, 2026-09-14; PR #104 correction cycle, F-4 … F-7)

**Revision 3** corrects three further findings inside F-1 … F-3 below, each marked *revision 3*: the network probe's
observed result is not an isolation attribution (F-3); a changed bucket policy cannot have fresh R-3 evidence before it
is deployed, and needs a separately reviewed transition procedure this PR neither defines nor authorizes (F-2); Route B's
observed digests are evidence for owner review, never an accepted set (F-1).

A record of how three review findings against [`production-readiness.md`](production-readiness.md)
were resolved, each traced to the source or declaration that decides it. **Nothing was run**: no
Terraform, AWS, provider, image, registry or private-artifact activity; no private artifact was read.
Every design named *proposed* below is **PROPOSED and BLOCKING** — it carries no authority and nothing
may proceed on it until its ADR is accepted and its implementation merged.

## F-1 — the first-build dependency cycle

**The cycle, traced.**

| Link | Where it is decided |
|---|---|
| stage a requires **both** image digests | `infra/aws/research-data-plane/production_variables.tf`, `production_image_digests` validation: stage `a` or `b` requires keys `acquisition` **and** `build`; `production_compute.tf` pins both task definitions from them |
| the build image needs per-dataset accepted schema digests | `compiled.py::parse_build_configuration` → `AcceptedSchemas(digests: dict[dataset, frozenset])`; `silver._parse` refuses `SCHEMA_UNSTABLE` for any page whose header digest is not in its dataset's set; the compiled configuration is baked into the image (ADR-0044 §2) |
| production digests are observable only from production Bronze | the build task is the only reader inside the boundary (ADR-0036 §2.3); the human build principal reads no licensed payload bytes on the workstation (§2.10); the acquisition path parses nothing (ADR-0017 / ADR-0035 §3.1) |
| production Bronze needs stage b and one authorized run | ADR-0036 §2.12 step 0–7; assignments only at stage b (`production_principals.tf`) |

Separate verification families (F-3) do not touch any of these links.

**Accepted, evidence-backed route — Route A, conditional.** The combined qualification assessment
computed a schema digest for every parsed page with `qualify/sharadar/parser.py::schema_digest_of`, and
`silver.py` imports **that same parser and digest** (`from kalpamani.data.qualify.sharadar.parser import
parse_payload`), over the same three tables the production slice names. The private report records them
(`report.py`, `observed_schema_digests`; `assessment.py` line 661 builds the set) and was published once
(CLAUDE.md, *the completed combined assessment*). **Limits, from the same sources:** the report records
**one sorted set across both runs and all three datasets, unattributed to any dataset**, while the
contract needs a per-dataset set; the pages were retrieved under the ticker-keyed request form of the
qualification plan, not the ticker-less form of ADR-0041, and header identity across the two forms is a
documented property of the tables (PSR-SHD-110, -112, -113 list the columns) that is **not empirically
established**; the provider-source register lists the **complete** column set only for `actions`
(PSR-SHD-112, seven columns) and a partial one for `stocks` and `tickers`, and documents no delivered
column **order**. Attribution is therefore an owner-side, offline check — `schema_digest_of` over a
documented header equal to an observed digest proves that digest is that table's — that **may succeed
for `actions`, is unlikely for `tickers` from the register alone, and is closed for any digest with no
equality**. No private artifact was read to establish any of this. Route A is recorded as
*available in part, suitability not established*; it never relaxes validation (an unattributed or
mismatched digest simply refuses the build with zero writes).

**Necessary contract change — Route B, PROPOSED / BLOCKING.** The smallest viable design that
guarantees resolution without a placeholder, a fixture or a relaxation: an **observation build** —
the first build image is compiled from the owner's real build inputs with an **explicitly empty**
accepted set per dataset (`AcceptedSchemas` already admits an empty set and then admits nothing; verified
offline), so the task refuses `REFUSED_NORMALIZATION` with **zero writes** after reading exactly the
locator and the objects it names; and its receipt carries the **per-dataset observed schema digests**
(64-hex digests; no key, row, identifier or subject). **As evidence for the owner's review**: an observed
digest becomes an accepted one only by the owner's explicit acceptance under the applicable gate, written
into a later configuration; nothing promotes a digest automatically and schema validation is never relaxed
(revision 3 makes this explicit wherever Route B is described). Affected: ADR-0044 §4 (the receipt's closed field
set gains `observed_schema_digests` on build refusals; `receipts.py` validator and `ledger_completion`
unchanged in disposition), ADR-0036 §2.9 output rule as already narrowed by ADR-0044 (digests, not "three
digests"), `silver.normalize` (collect every page's digest **before** refusing, instead of `_parse`
refusing on the first), `build_processing` (surface the set), one further build-image cycle (image →
registry digest → task-definition revision → a stage-b-preserving apply, F-2). Permissions: **none new**
— the build task already reads what it needs; the receipt reaches the owner through the existing log
stream, read by hand until the deferred collector exists. Gates: the observation build is a bounded build
run under its own written authorization (reads only, zero writes); its configuration is a **real**
compiled configuration (D-3, D-4, D-5 supplied) whose empty accepted set is an explicit statement, not a
placeholder. Rejected: attributing the report's digests by a human read of a locator or payload (ADR-0036
§2.10); carrying a header digest in the acquisition locator (breaks the acquisition path's
opaque-payload boundary); an always-admitting accepted set (a relaxation).

**Disposition:** cycle **confirmed**; Route A available in part and unproven; Route B proposed and
blocking; the sequence, checklist and gap register updated (`production-readiness.md` §2.3, §4.1, §4.2,
§4.3 S1/S10b, §7 G-7; `production-owner-inputs.md` D-11, V-4; example
`build-inputs.observation.synthetic.json`).

## F-2 — preserving stage b across later updates

**Declaration facts.** `production_principals.tf` declares the four `aws_ssoadmin_account_assignment`
resources with `count = local.production_count_b`; `production_stage = "b"` requires
`production_r3_verification_digest` (`production_variables.tf`). A later apply with
`production_stage = "a"` therefore plans **four destroys** — the assignments — and every generated
Identity Center role with them; an apply at `none` plans the whole production set's destruction.
Image or configuration rotation touches `production_image_digests` only; the task definitions and the
launcher policies (`production_policies.tf`, `ecs:RunTask` resource = the task-definition resource's ARN)
follow the new revision **inside the same stage**.

**Corrections made.** Every rotation instruction now reads: initial establishment `a` → R-3 evidence →
`b`; every later apply keeps `production_stage = "b"` **and** the recorded R-3 digest in `terraform.tfvars`;
a plan for a rotation must show the new task-definition revision(s) and the launcher policy update(s) and
**no assignment change**; assignment removal is a separate governed decision, never an incidental step.

**Evidence that survives, and what renews it (from accepted contracts) — corrected in revision 3.** R-3
is evidence about the licensed bucket policy **as deployed**, against the target and under the conditions
it was exercised with; it applies only while those hold, and an ordinary image rotation — which leaves the
bucket policy untouched — preserves stage b and its assignments. **A changed bucket policy is a different
case**: fresh runtime R-3 evidence for it cannot exist before it is deployed, so the earlier instruction
that required a new R-3 record *before* the apply that introduces the change was impossible and is
withdrawn. A bucket-policy change needs a **separately reviewed transition procedure** — prevention of
production use during the transition, deployment of the changed policy, re-verification against the
deployed policy, cleanup, restoration of authorized use — which this preparation PR **neither defines nor
authorizes**; a prior evidence digest does not attest to a changed policy; no automatic return to stage
`a` and no assignment removal is prescribed. The categorical claim that *only* a `storage.tf` edit could
invalidate R-3 is withdrawn too: evidence must remain applicable to the deployed policy, the target and
the relevant verification conditions, and no comprehensive re-assessment policy is designed here (G-14).
The compiled configuration, image digest and revision are bound per launch by the release (ADR-0044 §2),
so a rotated image is verified per launch, not by prior evidence.
**Unresolved policy (recorded, not decided here):** whether ADR-0036 R-1/R-2 must be **repeated for every
new production revision** — ADR-0036 §3 states the cells once and no accepted text says whether a
verification-image pass carries over an image rebuild; the proposed F-3 design makes a verification
image's evidence bound to its own digest, which argues for repetition per verification-image rebuild and
leaves the production-image question to the ADR. Also unverified here: Terraform's replacement ordering
for a task definition whose container definition changed (a new revision registered and the previous
deregistered, with the launcher policy re-pointed in the same apply) — the declaration is unchanged and
was not planned.

**Launcher-revision implications.** A rotation of one actor's image updates **only that actor's** launcher
policy resource; the other launcher is untouched. The proposed verification families (F-3) add a second
`ecs:RunTask` resource to each launcher; a production rotation leaves the verification resource alone and
a verification-image rotation leaves the production one alone, each a stage-b-preserving apply.

## F-3 — verification-image evidence boundaries

The comparison of a verification task with a production task, property by property, is added as
`production-readiness.md` §3.3, distinguishing what a verification task directly establishes, what a
configuration-equivalence check establishes, and what stays untested until the production image is
exercised. The probe is specified with its own bounded operations and classified evidence, and the
document no longer describes the build task's network posture as "zero network attempts": the accepted
build path makes AWS requests (SSM, STS, S3) and the proposed probe makes exactly one bounded provider-
origin connection attempt; what is zero is **provider API requests** and **data-plane writes**. The
verification-entry design stays proposed; the next-cycle scope (§8) now lists the dependencies that make
it coherent.

**Revision 3 — observation is not attribution.** The probe's **observed connection result** (one of
`CONNECTED`, `CONNECTION_REFUSED`, `TIMED_OUT`, `UNRESOLVED`, with `probe_attempts = 1`) and the **isolation
conclusion** are now two records. A timeout or a refusal alone does not establish that the build subnet's
routing or security groups blocked the provider — a destination failure, a remote rejection, a resolver
failure or a transient condition produces the same observation. `CONNECTED` **fails** the no-connectivity
check for that destination and instant; a non-connection leaves the isolation verdict **INCONCLUSIVE, never
VERIFIED**, until corroborated by evidence that attributes the failure to this account's network controls.
What corroboration is sufficient, and its limits (a same-instant comparison covers one instant and one
address; a flow-log record names a rule, not a reason), is left to the proposed verification ADR; no
procedure is accepted and no probe permission is broadened here (G-15). §3.3, the S9 matrix row and §8 are
corrected accordingly.

## F-4 — durable identity consumption before external mutation (PR #104 review)

**Reproduced** at the reviewed head `73ec563f…`, through `scripts/production_launch.py` on fakes: an
interruption raised at the release's `verified_at` clock read (after `RunTask`, before any record)
left the ledger empty and the records directory absent; the next invocation of the same identity
launched again (`RunTask` count 1 → 2). Two distinct identities recorded in the same second produced
one evidence file. The ledger was written with `Path.write_bytes`.

**Corrected** by `launch_store.py` and the tool's reordering: reservation → bootstrap → clients →
launch → records → ledger, with the reservation exclusive, durable and permanent; the lock and atomic
replacement around every ledger write; exclusive record names; `--recover`; refusal of every launch
while a reservation has no ledger row. The owner-side reservation is distinct from ADR-0038's S3 run
reservation, and a verification task still reserves nothing in the store.

**Limits stated**: durability is the platform's `fsync` and `os.replace`; Windows syncs no directory
entry; a stale lock is the owner's to remove; what a task started before an interruption did is not
known to the tool and is recorded as `HALTED` for owner review.

## F-8 — the reservation's location must not depend on the records directory (PR #104 review, second cycle)

**Reproduced** at `555fdf76…` through the public launch path on fakes: a launch with ledger L and
records directory A, interrupted after `RunTask` and before the ledger row, left its reservation under
`A/reservations`; the same identity retried with ledger L and records directory B found no reservation
and launched again (exit 0, `RunTask` 1 → 2, nineteen clients constructed); `--recover` from another
directory found nothing to recover (exit 3).

**Corrected** by anchoring the reservations directory and the lock to the ledger's canonical path
(`<ledger>.reservations/`, `<ledger>.lock`, via `Path.resolve`), so every mode — preparation,
reservation, execution, completion, recovery, the verdict — resolves one store for one ledger whatever
records directory is named and however the ledger is spelled; by the reservation carrying the whole
authorized specification, so recovery's `HALTED` row takes its slice and plan digest from it and a
launch record the named directory cannot show costs nothing but the launch instant; and by treating
`--records-dir` as an evidence destination only. Exclusive creation, atomic replacement, the lock and
permanent consumption are unchanged. **Legacy state**: a `reservations` directory with any entry
under the supplied records directory refuses (`refused_legacy_reservations`, exit 15) until the owner
has moved its files beside the ledger by hand — the tool reads, moves, migrates and deletes none of
them, looks at no directory it was not handed, and no real reservation exists anywhere because no
launch has ever run; a first-revision document carries no specification and is refused as malformed.
Tested on synthetic directories only; no private production state was scanned or migrated.

## F-9 — the isolation verdict uses the recorded launch placement (PR #104 review, second cycle)

**Reproduced** through the public verdict path on fakes: a valid launch record and verified
build-verification receipt; analysis evidence naming a security group outside the launched placement
gave `INCONCLUSIVE / COMPONENT_OUTSIDE_PLACEMENT`; a substituted, otherwise valid `--launch-inputs`
file whose build groups included that group gave `VERIFIED / CORROBORATED` with the record, receipt and
ledger unchanged — the groups came from the fresh file, unbound to the launch.

**Corrected** by persisting on the launch record the specification digest the authorization named and
the placement the launcher verified (interface, subnet and the security groups
`DescribeNetworkInterfaces` reported on the interface — equal as a set to the compiled groups or the
task was misplaced), carried by `LaunchReport.security_group_ids`; by binding the record to its
reservation before completion or a verdict (same specification digest, actor, kind, entry, registered
target, acquisition workload, subnet and groups) and, for the verdict, to the identity's ledger row;
by deriving the verdict's placement from the record cross-checked against the reservation's
specification; and by verifying a supplied `--launch-inputs` file against the recorded specification
(`compile_launch` must reproduce the specification's compiled launch and target) — a mismatch refuses
and no verdict is written. Destination binding, the analysis checks and `CONNECTED → FAILED` are
unchanged; a missing reservation, row, placement or binding refuses and can never establish
`VERIFIED`. **Trust boundary stated**: the digests make a substituted or mislaid owner artifact a
refusal; they are no protection against an owner who rewrites every owner-controlled artifact
consistently, and none is claimed.

## F-5 — the authorization binds the workload and target (PR #104 review)

**Reproduced**: a slice with a different `actions` window launched under an authorization written for
the original (exit 0); the authorization record carried actor, kind, identity and the two instants.

**Corrected** by the launch specification and its digest in the authorization (ADR-0045 §6): built by
preparation, written for review, rebuilt at execution, compared before any client, freshness
revalidated before the first mutation. Timestamps and the ledger's spent set are outside the digest by
design; every bound category is covered by a test that changes it under an otherwise identical
authorization. Gate-evidence references (the R-3 digest, the generation-record digest) are owner-held
references whose grammar and applicability the tool checks; **that an approval occurred is not
something a digest proves**, and the tool does not claim it.

## F-6 — equivalence binds the actual registered counterparts (PR #104 review)

**Reproduced**: with only the verification target's digest registered, an unrelated but valid
production file (a different origin set) and a matching verification file launched (exit 0); the
launch-inputs actor block carried no task-definition evidence to compare.

**Corrected**: every file is bound to its own registered target (production, verification, and the
acquisition file behind a build pair); the launch-inputs record carries owner-transcribed
task-definition evidence per target, validated to its grammar and to the target (family, revision,
image, command) and compared between the two families with the intentional differences named;
`EQUIVALENT` is configuration equivalence and is stated as never being runtime proof — the production
image's bytes, its processing and the fields only a production entry reads are exercised by a
production run alone. **Dependency recorded, not added**: a live `DescribeTaskDefinition` read-back
needs `ecs:DescribeTaskDefinition`, which the launcher permission sets do not hold; until it is
declared and applied, the evidence is the owner's transcription.

## F-7 — R-2 evidence binding and verdict integration (PR #104 review)

**Reproduced**: `isolation_verdict` returned `VERIFIED` for a corroboration built from two supplied
`True` booleans and no analysis identity, status or time; the probe observation carried resolution,
result and attempts only; `scripts/production_launch.py` contained no verdict path.

**Corrected**: the receipt binds the selected destination under a keyed digest, recovered by the tool
against the compiled set and never inferred; a closed transcription of one Reachability Analyzer
analysis (fields verified against the public `NetworkInsightsAnalysis`, `NetworkInsightsPath` and
`Explanation` references and the published explanation-code list); every comparison derived from the
evidence, the launch record and the compiled placement, with a closed reason per outcome;
`CONNECTED` always fails; configuration-model evidence kept distinct from the packet observation;
`--isolation-verdict` records the verdict beside the launch record. `VERIFIED` is unreachable without
a transcribed analysis, and no analysis is made and no permission granted by this cycle.

## F-10 — the verification tooling (G-4, G-5, G-6), ADR-0046 (accepted on the merge of PR #105)

**Disposition: implemented offline; ADR-0046 ACCEPTED / IN FORCE since PR #105 merged
(2026-09-14T20:37:38Z, merge commit `5174dcf290b4837d38af8ce4a4b975c6557e482e`); proposed while
that pull request was open — true then, and not rewritten.** The human-binding materializer, the R-3 tool and the
cell runner compose accepted contracts and add two closed records — and close a third, the verdict
document the launch tool already writes; none reaches AWS by default and each
authorized branch is opened by its own flag under its own written authorization. **Materializing a
binding is not verifying an identity**; **an R-3 record attests only to the declaration and binding it
names**, its positive control **confirmed absent only by row 9's `404`** and its client held to **one
transport attempt** (`total_max_attempts: 1`); **a cell matrix is derived from the ledger, the
reservations, the launch records and the verdict records, never remembered** — a receipt-verified row
passes only through its bound chain — the launch tool's own reservation-to-record rule, now the shared
`launch_store.bind_record` (specification, workload, target, verified placement) — against the registration now in force (`HISTORICAL` when that
changed, `UNBOUND` when the chain is missing, malformed or substituted), a verdict cell resolves its
records deterministically (`FAILED` never erased; an `INCONCLUSIVE` re-evaluated for the same launch
with no relaunch and no new probe); **the aggregate cannot read VERIFIED while the negative R-1 cells
are undecided** (ADR-0046 §4). The four PR #105 review findings — the SDK retry budget, the unbound
evidence chain, the permanent `INCONCLUSIVE`, the row-9 confirmation — were reproduced against
`cf484410…` before the corrections and are held by the tests named in readiness §10; the second
correction (a placement- or workload-only change to a valid launch record read `PASSED` at
`f949dcb9…`) was reproduced with the real parsers and runner on synthetic files and is held the same way. ADR-0045's acceptance (PR #104 merged 2026-09-14) is synchronized in the same pull
request and implied none of this: no analyzer permission, no runtime verification, no image, no run.

## F-12 — the permission-probe tasks and the held ExecuteCommand check, ADR-0048 (accepted on the merge of PR #107)

**Disposition: implemented offline, accepted (PR #107 merged 2026-09-15T10:22:22Z, merge commit
`c0566574c41bc31b7144fafe919078a213982143`); while the pull request was open it was proposed, which is
how the paragraphs below read and are not rewritten; the deletion rehearsal path designed and not opened —
since implemented offline and CLOSED by ADR-0049, accepted on the merge of PR #108 (F-13); D-1 made concrete by proposed ADR-0050 (F-14).**
The 32 task-role subcells are executed by a **permission-probe task** of the actor's own family: the
workstation prepares and authorizes the subcell exactly as before, consumes the authorization, writes
the attempt, then launches the probe through the accepted launch sequence with the bound statement as
its input; the probe composes the accepted bootstrap, issues **exactly one** catalogued operation under
the task role over the one service it names, and carries the classified answer home in its receipt;
the workstation completes the record only from that receipt, verified against its launch record, with
`identity_verified` exactly when the probe's bootstrap released — **never on an exit code**. The two
`ExecuteCommand` subcells are checked by the launcher against its own **held** probe task, once, with
the documented request; an unexpected session is an inversion and the task is stopped. Every issuing
service's documented denial is classified; every unknown answer decides nothing. The probe task is a
started task the cleanup discovers by the session tag and confirms `STOPPED`. **The deletion role's
rehearsal path is designed (ADR-0048 §4) and not opened**: opening it reverses ADR-0007's verified
inert property, so R-8's two subcells stay BLOCKED with that dependency named. Layers 56 / 6 / 32 / 2
/ 2; nothing executed; **acceptance would authorize no execution and grant no permission**.

**Validation performed for the mechanisms cycle.** The full suite, `ruff check`, `ruff format --check`,
`mypy` and the docs audit on the final head, every one on synthetic temporary files, counting fakes and
an intercepted transport (the serialized `ExecuteCommand` request asserted there); the amended
declarations validated in an external copy under the pinned provider. No image, no Terraform plan or
apply, no AWS call, no private input.

**Correction cycle 1 (review of the pull request; ADR-0048 §8; still PROPOSED).** Three findings,
each reproduced on the reviewed head through the real modules before correction: (1) a probe launch
interrupted after `RunTask` and before its record left the started task unaccounted for, and a
completion interrupted before the ledger was unrepeatable — now the probe identity is reserved beside
the ledger before `RunTask` with its whole specification, the cleanup accounts for the task from the
reservation alone, `--recover-probe-launch` records the row offline, completion is repeatable, and
`RunTask` is never retried; (2) the validator preserved `PASSED` with the launch record removed or
substituted, a duplicate beside it or the ledger row reverted — now the launch, the receipt (kept and
re-verified on every read) and the ledger row are required, exact and never chosen among candidates,
tested through the public runner beside a valid control; (3) the `ExecuteCommand` check was issued
without observing the held task `RUNNING` — now a bounded fresh-description precondition admits the
check, is kept as evidence, and every other outcome decides nothing. Focused regressions and the
required gates on the corrected head are recorded in the export; **synthetic tests do not establish AWS
verification**, nothing has been run against AWS, the deletion path stays BLOCKED, and every deferred
permission is unchanged.

## F-13 — the receipt collector and the deletion rehearsal, ADR-0049 (accepted on the merge of PR #108)

**Disposition: implemented offline, accepted (PR #108 merged 2026-09-15T13:53:41Z, merge commit
`82cae1ebfcc99dbbc53f67e534e4d78ffb914d4a`, approved head `9625e241db01b2996fbf9f63814ba3a916a3def7`); while the pull request was open it was
proposed, which is how the paragraphs below read and are not rewritten; the rehearsal path CLOSED and its
decision presented — decided in neither direction by the merge, and since made concrete by proposed ADR-0050 (F-14).**
The **receipt collector** reads a launch's receipt line from the stream derived from the bound launch
record and the registered `log_destination` block of the task-definition evidence — never from a
caller — under stated bounds (40 requests, 20,000 events, 300 s, each checked before a request; 16-page
passes; 15 s polls; effective SDK retries zero; the in-flight request the one limit it cannot cut),
establishes one line only from a **complete scan** (end token, one poll interval, a re-read delivering
nothing new — the observation window the record carries; delayed delivery the stated limitation),
verifies the candidate against the launch record **before** keeping it (a refused line leaves its closed
defect and byte count, never text), keeps the verified line and no other event in a closed collection
record, admits recorded collections in both tools through one rule (bound to the launch and the
destination; contradictions refuse whatever the filename order; a recorded `CONTRADICTORY_RECEIPTS` is
never superseded by a later collection or a cache hit and is disposed only by a hand-read completion
that acknowledges it by digest, recorded beside it, after which only that receipt completes the launch;
rejected and exhausted attempts never block the next read), and hands the line to exactly the hand-read
completion path (`--complete-row --collect-receipt`, `--collect-receipt
<subcell>`; the receipt verifier, the reservation binding, the observed-exit rule, the receipt evidence
and the ledger row unchanged), behind its own flag and the launcher identity. Pagination, repeated
tokens, delayed delivery, bounded polling, missing / malformed / duplicate / contradictory receipts,
wrong statement, attempt, registration and destination, denial, throttling, timeout, an interrupted
completion after the collection record, and the preservation of an INVERTED reading are each tested
through the real tools, store and runner; the SDK client's serialized request and its one-attempt
behaviour at an intercepted transport. **An exhausted or incomplete scan proves only that no receipt
was established within it, and a successful read is not a successful verification.** Correction 1
(ADR-0049 §6): the review's three findings — an incomplete scan establishing uniqueness, unvalidated
content persisted before refusal, cached records chosen by filename order with no recovery — were
reproduced on the reviewed head through the real collector and both public paths and closed, with
controls beside each regression. Correction 2 (ADR-0049 §6.4): a recorded contradiction silently
superseded by a later single-line collection or by a `COLLECTED` record beside it, in either order —
reproduced through both public paths and closed by the `CONTRADICTION_UNRESOLVED` refusal and the
explicit, evidence-bound disposition, with retry and repeatable-completion controls. Correction 3
(ADR-0049 §6.5): a disposition naming receipt A, interrupted before the completion finished, did not
constrain the retry — receipt B completed by hand and through collection or cache reuse; closed by one
shared status rule that binds the launch to the disposition's receipt before any read or mutation
(`refused_receipt_binding`, `RECEIPT_SUBSTITUTED`, `CONFLICTING_DISPOSITIONS`), with both interruption
boundaries, same-receipt recovery, different-receipt refusal and ordinary-completion controls through
both tools. `logs:GetLogEvents` for the
launcher sets is **recorded and not granted**. The **deletion rehearsal** ADR-0048 §4 designed is
implemented offline over the actual deletion-role execution model — target, statement, consumed
authorization, sequence, engine, record, reading — and **CLOSED**: `REHEARSAL_PATH_OPEN` false, both
R-8 subcells BLOCKED, the tool refusing, no resource declared, existing deletion authority unchanged, no
generic deletion utility. **Decision D-1 (open the path) is presented with its consequences and not
taken.** ADR-0048's accepted state is synchronized in the same change. Nothing has run; acceptance
would authorize no execution and grant no permission.

**Validation performed for the collection-and-rehearsal cycle.** The full suite, `ruff check`,
`ruff format --check`, `mypy` and the docs audit on the final head, every one on synthetic temporary
files, counting fakes and an intercepted transport with invented credentials. No log read, no AWS call,
no image, no Terraform plan or apply, no private input.

## F-11 — the negative R-1 launches and the R-4 … R-9 subcells, ADR-0047 (accepted on the merge of PR #106)

**Disposition: implemented offline, accepted (PR #106 merged 2026-09-15T00:26:19Z, merge commit
`167f1564378cfb96759093b43fbde5443f6c56b6`); while the pull request was open it was proposed, which is
how the paragraph below reads and is not rewritten.** The 36 BLOCKED subcells it names are, since, 34
executable offline by ADR-0048's mechanisms (F-12, accepted on the merge of PR #107) and 2 still BLOCKED on the deletion path. The two negative modes are bound into the
authorized specification (and so into the authorization's digest), applied by the launcher in one
changed step with no retry in any mode, recorded with the launcher's own terminal observation, and
passed by the matrix only on the expected, receipt-verified, bound refusal — **an unexpected success
is FAILED, and a refused verification row is never a successful bootstrap and never buildable**.
ADR-0036 §3's R-4 … R-9 are expanded into 98 traced subcells: 56 executable at runtime under a human
or launcher profile by one tool — one prepared statement binding the exact target, the targets
document and the bound prerequisite records, one owner authorization naming it and consumed durably
beside the ledger before the operation, the attempt recorded before the operation and joined to its
result by identity, every returned task of an unexpected launch stopped at once with termination
confirmed only by the cleanup's `DescribeTasks`, a possibly committed write or launch recorded and
settled by the cleanup and never retried, every record bound to the environment binding, the
production declarations and the registration; 6 evidenced by the R-1 bootstrap launch; **36 BLOCKED
with their exact dependency — the task roles on a task-side permission probe entry that does not
exist, the deletion role on its missing execution path, the two `ExecuteCommand` subcells on a
running task of the actor — and a human role never stands in for a task role**. Cleanup runs under
the control principal by exact identity, defers an object a prepared dependent still needs, and is
confirmed or reported as residue; a negative cell's missing evidence after an interrupted completion
is recovered offline from the re-verified receipt, never relaunched (PR #106 correction 1). A
result binds only through its whole chain — attempt, statement, bound prerequisites, the exact target
recomputed against the context in force (the targets document included), the consumed authorization
— by one validator shared by execution, derivation and cleanup admission, and an ambiguous launch is
settled only by termination evidence after bounded discovery, never by an empty listing (PR #106
correction 2); discovery lists by `startedBy` alone, as the `ListTasks` contract requires, with the
request shape held at the real adapter's intercepted transport, and a cleanup record whose identity is
not verified settles nothing wherever cleanup evidence is consumed (PR #106 correction 3). **Empty,
partial, simulated or blocked
coverage never passes**, and the aggregate stays `INCOMPLETE` while any of it remains. Acceptance
would authorize no execution and grant no permission.

**Validation performed for the coverage cycle.** The full suite, `ruff check`, `ruff format --check`,
`mypy` and the docs audit on the final head, every one on synthetic temporary files and counting fakes;
the results and their limitations are in readiness §11.1 and in the pull request. No image, no
Terraform command, no AWS call, no private input.

## Validation performed for this cycle

Focused only, as the changes are documentation and one synthetic example: the docs audit
(`scripts/phase3_docs_audit.py`), the example-consistency test
(`tests/unit/test_production_readiness_examples.py`, extended for the observation example), the
provider-row guard (`tests/unit/test_sharadar_qualification_boundary.py`), the ADR-0043/0044 governance
tests, `ruff check`, `ruff format --check` and `mypy` on the touched test. The full suite and the images
were **not** rerun: no source under `src/` or `scripts/` changed.

## F-14 — the deletion rehearsal made concrete, integrated offline and declared inert, proposed ADR-0050

**Disposition: implemented offline, proposed; Decision D-1 made concrete and NOT TAKEN; the declaration
inert; the path CLOSED.** Proposed ADR-0050 states D-1 as the exact consequence of what it merges: the
resources and permissions (a rehearsal task definition whose task role is the actual deletion role; the
role's delta of three exact parameter reads and a scoped decrypt with **no S3 change**; a runtime-binding
parameter; the `KalpaManiDeletionRehearse` launcher with one exact `RunTask`, `PassRole` of exactly the
deletion and execution roles, create-only input and release parameters, `GetLogEvents` on exactly the
rehearsal streams and **no S3 action**; two gated key-policy statements; one assignment at stage b), the
principals (a human launcher passes; the deletion role deletes as the task; no human ever assumes it), the
target restriction (the statement, the input's recomputed digest, the task's bucket check, the engine's
exact operations — not IAM), the limits, every interruption's recorded outcome with no retry, the control
principal's cleanup as the only confirmation, the residual risks and the separate runtime authorizations
— verbatim for the owner's signature. The **rehearsal task**, the **launcher and completion**, the
**collector's reuse** and the **owner tool's four modes** exist as offline code exercised only on fakes,
every mode refused with exit 27 while `REHEARSAL_PATH_OPEN` is `False` (it is); the **declaration** is
inert behind `deletion_rehearsal_open` (false by default), stage a/b and an image digest, validated only
in an external copy under the mock provider. The **owner checklist** lists every value, all MISSING.

**Validation performed for the readiness cycle.** The full suite, `ruff check`, `ruff format --check`,
`mypy` and the docs audit on the final head; the new suites through the real parsers, stores, tool and
derivation on synthetic files and injected fakes — valid controls; wrong role, target, prerequisite,
authorization and receipt; interrupted launch, operation, receipt collection and completion; ambiguous
deletion and unsuccessful cleanup; conflicting and replayed evidence; the closed path refusing before any
client; the declaration's defaults preserving the closed state — and Terraform `fmt`, `init
-backend=false`, `validate` and `test` (20 runs) in a task-owned external copy. **Synthetic tests do not
establish AWS verification**; no rehearsal, deletion, launch, log read, image, plan, apply or AWS call
occurred; no permission was granted; D-1 stays the owner's.
