# Production readiness — what remains before the first bounded acquisition and research build

**Status: a preparation record, not an authorization.** Prepared after PR #102 merged, from the
accepted decisions ([ADR-0036](../decisions/ADR-0036-production-data-plane-principals-and-trust-model.md)
through [ADR-0044](../decisions/ADR-0044-production-delivery-contracts-and-packaging.md)), the
tracked code and infrastructure declarations, and public AWS documentation — and from nothing else.
**Nothing was run to produce it**: no AWS, STS, metadata, Secrets Manager or provider call, no
Terraform plan or apply, no image build, pull or publication, no registry login, no task launch, no
private-directory scan, no AWS-configuration, credential, secret or licensed-data read. Every
production value it names as required is **missing** unless the row says otherwise; none is invented,
and the synthetic examples under [`examples/production/`](examples/production/README.md) are shapes,
not values. Reading this authorizes nothing. G2 OPEN; CONTROL DEFERRED; Phase 3 NOT COMPLETE;
live trading HARD-DISABLED.

**This record was merged as PR #103** (merge commit `8464128a9d890a5d43c2a685927742cad8428f8f`,
2026-09-14) and **§9 below records the verification-and-launch cycle its §8 proposed**, carried out
offline in the pull request that adds §9 and **proposed ADR-0045**. Sections 1–8 are kept as the
record of the days before that cycle and are not rewritten; where a §7 gap has moved, §9 says so.
**That pull request, PR #104, has since merged** (2026-09-14T17:28:56Z, merge commit
`af20f36acbe8a3006830762fbad5cb01d1e9b38b`, approved head `2966ed2f24f7841eea264657f75e9c081e35922a`; merge tree identical to
the reviewed head tree), so **ADR-0045 is ACCEPTED / IN FORCE** within its own merge-effectiveness
clause and §9's *proposed* dispositions are decided — as §9 recorded on the days it was written, and
not rewritten. §10 records the tooling cycle that followed (ADR-0046, since accepted on the merge of PR #105 — §10.5); §11 records the coverage cycle that followed it (proposed ADR-0047).

**Baseline.** `main` at `02998fa9bde853d4262269c3b9032bd7fc171461` — the merge of **PR #102**
(merged 2026-09-14T10:25:40Z, ordered parents `98addd070857143b2bd79ef3e2bf6c06539555ba` then
`82d0a3b24e29aa309ad501fd8b7404db1e4c3644`, merge tree `89533df7207f44ee1b5817a0be6d1a73778e53e2`,
identical to the reviewed head's tree). PR #102 merged the locally verified packaging corrections
and the status synchronization for PR #101; its images carry **synthetic** configuration and were
never published, registered or run on AWS. Successful processing inside a container, production
publication and AWS runtime verification remain **unperformed**.

The image procedure itself is [`production-image-build.md`](production-image-build.md); this
document does not restate it. The owner-input checklist is
[`production-owner-inputs.md`](production-owner-inputs.md), and the disposition of the review
findings corrected in this record's second and third revisions is
[`production-readiness-dispositions.md`](production-readiness-dispositions.md). All are indexed from here.

---

## 1. What exists, and what does not

| Exists on `main` (offline, synthetic-only unless stated) | Does not exist |
|---|---|
| the accepted contracts: `CompiledTask` v2, compiled configuration v1, acquisition input v2, build input v1, runtime bindings v1, placement release v2, run locator, receipt line v1 | **any production owner input** (a secret name, an origin address set, a build configuration, a run identity, a ledger) |
| the two task entries and the packaged entrypoint (`scripts/production_task_entrypoint.py`), run only inside local network-disabled containers | **a compiled configuration from production inputs**, a **published image**, a **registry digest**, a **task-definition revision** (`production_stage = "none"`) |
| the generator (`production_compiled_configuration.py`), the tree-exact context preparer (`production_build_context.py`), the Dockerfile, the pinned constraints | **an owner-side launch tool** — `launcher.py` is a library on injected adapters; no script constructs the real ECS, EC2 and SSM clients under the human and launcher profiles, materializes an input, verifies placement, writes a release, observes, or cleans up |
| the launch-sequence library (`launcher.py`, `compute.py`, `parameters.py`, `release.py`), the task bootstrap (`runner.py`) and both processing paths | **an input-materialization tool** — `plan_digest_for`, `spent_identities_block` and `ledger_digest` exist as functions; nothing computes a production input document or writes the create-only parameter |
| the human bootstrap (`runner.human_bootstrap`) and the production binding loader | **a production human-binding materializer** — `scripts/qualification_runtime_binding_materialize.py` writes the qualification binding only; the two ADR-0036 §2.5 human bindings have no writer |
| the receipt validator and `ledger_completion` (`receipts.py`) | **a receipt collector** and its `logs:GetLogEvents`/`FilterLogEvents` IAM delta — **proposed and deferred** (ADR-0044 §4–§5); this document keeps it deferred |
| the offline Terraform declaration (`production_*.tf`, three stage-gated statements in `storage.tf`), validated in an external copy | **an R-3 verification tool** — the nine-row expected path and the failure-path cleanup are a procedure in ADR-0036 §3 with no implementation |
| the qualification package, applied and verified, unchanged | **a verification-only task path** for ADR-0036 R-1/R-2 — see §3 |
| the ADR-0035 offline controls I-1 … I-7 | a **real exchange calendar** (the build consumes a pinned synthetic one), the ADR-0039 vocabulary integration (build-local mirror remains) |

---

## 2. Production input inventory

Every value a production run needs, traced to the contract that consumes it. **Location** is where
the value lives: `Git` (a repository constant), `owner-private` (a git-ignored file or the owner's
records under the ADR-0023 trust boundary), `image` (compiled by the generator), `Terraform` (the
git-ignored `terraform.tfvars` or Terraform state/outputs), `SSM` (a parameter written per run).
**Status** is one of `PRESENT` (in Git, or supplied in evidence), `MISSING` (no value exists or was
supplied) or `AWAITING VERIFICATION` (a value exists and a gate must confirm it). No value was
supplied for this cycle, so every owner value is `MISSING`.

### 2.1 Shared identity and image values

| Input | Purpose · consumer | Authoritative source · owner | Validation · freshness | Location | Status |
|---|---|---|---|---|---|
| `code_commit`, `code_tree` | the tree the image is built from; `CompiledTask.code_commit`, the receipt, the generation record, the context manifest, `BuildConfiguration.commit` | the release commit on `main` chosen by the owner | 40 hex, resolving to exactly itself; a clean checkout; a configuration generated at an earlier commit is stale | Git (the commit) · owner-private (the choice) | MISSING — the release commit is not chosen; `02998fa…` is the current baseline, not a decision |
| `configuration_digest` (per entry) | binds the image's configuration file to the release and the receipt; `CompiledTask`, `CompiledLaunch`, release v2 | the generator's `generation-record.json` | 64 lowercase hex; SHA-256 over the exact file bytes; regenerated on any input or commit change | image · owner-private (record) | MISSING — no production configuration generated |
| `BASE_IMAGE_DIGEST` | the pinned `python:3.11-slim` linux/amd64 image-manifest digest the Dockerfile requires | resolved once by the owner (`docker buildx imagetools inspect`) | `sha256:` + 64 hex; the platform image's digest, never the index's | owner-private (build record) | MISSING for a production build (the local verification pinned one; that record is the owner's) |
| image registry digest (per actor) | `production_image_digests` in Terraform; `CompiledLaunch.image_digest`; release v2 `image_digest`; the launcher's `DescribeTasks` attestation | the registry after `docker push` (`RepoDigests`) | `sha256:` + 64 hex; **never a local image id** | Terraform (tfvars) · owner-private (record) | MISSING — no image published |
| task-definition revision ARN (per actor) | `CompiledLaunch.task_definition_arn`; release v2 `task_definition_arn`; the launcher's exact `RunTask` resource | Terraform state after a stage-a apply | exact family and revision; a new revision on every digest change | Terraform (state/outputs) | MISSING — stage `none` |

### 2.2 Acquisition actor

| Input | Purpose · consumer | Authoritative source · owner | Validation · freshness | Location | Status |
|---|---|---|---|---|---|
| `secret_name` | the one `GetSecretValue` the acquisition task makes (`EntryConfiguration.secret_identifier`) | the owner's Secrets Manager secret holding the **production** Sharadar credential — a different resource from the qualification secret; Terraform creates no secret | a Secrets Manager **name** in the documented grammar, never an ARN, never a value (`FORBIDDEN_INPUT_FIELDS`); must resolve to the same resource `production_acquisition_secret_arn` names | owner-private (inputs file) → image | MISSING |
| `production_acquisition_secret_arn` | the exact ARN the acquisition data-plane policy and the Secrets Manager endpoint policy admit | the same secret | commercial-partition Secrets Manager ARN; required for any stage other than `none` | Terraform (tfvars) | MISSING |
| `origin_addresses` | the compiled IPv4 set the task resolves the pinned provider host against at start (`REFUSED_ORIGIN` outside it) | the provider origin's resolved addresses, materialized by the owner at the Terraform gate | non-empty IPv4 literals; a resolved address outside the compiled set refuses at start (`REFUSED_ORIGIN`), while an address the compiled set admits but `production_provider_origin_cidrs` does not fails at the network layer mid-run — so the two sets are kept equal; **rotation = image rebuild + register + apply** (ADR-0044 §2) — a provider address change invalidates the image | owner-private (inputs file) → image | MISSING |
| `production_provider_origin_cidrs` | the acquisition security group's only non-AWS egress | the same resolved set, as CIDRs | IPv4 CIDRs, never `0.0.0.0/0`; refreshed under the Terraform gate before each authorized run window; an address restriction, not a hostname restriction (ADR-0036 §2.8) | Terraform (tfvars) | MISSING |
| acquisition input v2 — `run_identity` | the single-use run identity; reserved durably first (`_production_claims/runs/<run-id>.json`, ADR-0038); the locator's name | allocated by the owner from the owner ledger | `RUN_ID_RE` (`[A-Za-z0-9][A-Za-z0-9._-]{0,63}`); distinct from every spent identity; one identity = one authorization = one launch | SSM (per run) · owner-private (ledger) | MISSING |
| acquisition input v2 — `slice` | what the run acquires: `acquisition_mode` (`BACKFILL`/`UPDATE`), `datasets`, `windows`, `request_count`, `max_response_bytes` | the owner's ingestion authorization (ADR-0035 §5.2, I-8) | ≤ 96 requests, ≤ 16 MiB per response, compiled deadline 1,800 s; the plan is **recompiled from the slice** by the task, so the slice fully determines the run | SSM (per run) | MISSING — first bounded scope undecided |
| acquisition input v2 — `plan_digest` | must equal the digest of the plan compiled from the slice (`bind_plan`) | computed by `plan_digest_for(slice, mode)` | 64 hex; a supplied number that is not the compiled one refuses the input | SSM (per run) | MISSING (and no tool computes it — §7) |
| acquisition input v2 — `spent_identities` | the task-side spent-identity check (ADR-0044 §3); `{spent, spent_digest}` | the owner ledger's spent identities | sorted, distinct, ≤ 128; `spent_digest` = SHA-256 over the canonical list; the run's own identity must not appear; **a missing block refuses the input — never an empty registry** | SSM (per run) | MISSING (ledger completeness: the ledger is owner-held and has no rows yet) |
| acquisition input v2 — `issued_at`, `expires_at` | freshness | the materialization instant | `expires_at − issued_at ≤ 24 h`; expired refuses | SSM (per run) | MISSING |
| acquisition runtime binding (SSM) | `target_account_id`, `aws_region`, `licensed_bucket_name`, `acquisition_profile`, `provenance` for the task's bootstrap | Terraform materializes it at stage a from `production_target_account_id` (defaults to the qualification target), `aws_region`, the licensed bucket, and `production_binding_provenance` | the same loader as the human file; standard-tier `SecureString` under `kalpamani-task-bindings` | Terraform → SSM | MISSING — stage `none` |
| acquisition human runtime binding (file) | the human principal's bootstrap for input materialization and cleanup (`human_bootstrap`) | ADR-0036 §2.5 third artifact under the ADR-0023 trust boundary, selected by `KALPAMANI_PRODUCTION_ACQUISITION_RUNTIME_BINDING_FILE` | absolute path under the private root, owner-only ACL, closed schema | owner-private | MISSING (and no materializer — §7) |
| `production_binding_provenance` | the provenance block of both task bindings | implementation commit and tree, and the ADR-0024 environment-binding digest | 40/40/64 hex; shape-checked as the loader checks it | Terraform (tfvars) | MISSING |

### 2.3 Research-build actor

| Input | Purpose · consumer | Authoritative source · owner | Validation · freshness | Location | Status |
|---|---|---|---|---|---|
| `build_configuration.accepted_schemas` | the observed CSV header digests Silver admits per dataset (`silver._parse` refuses `SCHEMA_UNSTABLE` for a page whose digest is outside its dataset's set) | the header digests of real deliveries (`schema_digest_of` over the delivered header, in delivered order), observed under the private boundary — **not derivable from public documentation alone** | per-dataset sets of 64-hex digests; an explicitly **empty** set parses and admits nothing; a new provider header is a configuration change and an image rebuild | owner-private → image | MISSING, and **sequenced**: two routes exist (§4.2 item 6) — **Route A** (accepted, evidence-backed, conditional): the private combined qualification report's `observed_schema_digests`, computed by the same parser and digest function over real deliveries of the same three tables, **unattributed to datasets** and observed under the ticker-keyed request form, attributable only by an owner-side digest-equality check against documented headers (complete for `actions` only, PSR-SHD-112); **Route B** (PROPOSED / BLOCKING): an observation build with an empty accepted set whose refusal receipt reports the per-dataset observed digests **as evidence for owner review** — a later configuration names only the digests the owner explicitly accepts, with no automatic promotion. Until one route yields explicitly accepted, attributed digests, no Silver-producing build image can be compiled |
| `build_configuration.calendar` | the trading-session calendar (`session_date`, `open_at`) membership decides against (`decision_time(d) = open(d) − 30 min`) | a **real exchange calendar** with an authoritative source and version | sessions sorted, each opening on its own date; covering every decision session and the history window | owner-private → image | MISSING — only the synthetic pinned calendar exists (`sessions.py`; no tzdata in the operational venv) |
| `build_configuration.evidence` | per-version availability evidence (`DELIVERY_WINDOW` only with explicit per-version evidence; P-2 first-seen bound is the default) | owner-recorded evidence items, or none | closed item shape; an empty item list is a valid configuration under P-2 | owner-private → image | MISSING (may legitimately be empty for the first build) |
| `build_configuration.universe_rule` | `breakout-long-v1` parameters: `decision_margin_seconds`, `history_sessions`, `addv_window_sessions`, `price_floor`, `addv_floor`, `eligible_exchanges`, `common_stock_categories` | ADR-0035 §5.2 I-9 — an owner decision | non-negative integers, decimals, closed lists; `universe_rule_version` must equal the code's | owner-private → image | MISSING — I-9 not supplied |
| `build_configuration.decision_sessions`, `as_of`, `commit` | which sessions the build decides; the as-of instant served rows are re-verified at; the code commit pinned into the manifest | the build authorization; the release commit | sorted distinct dates; an aware instant; 40 hex | owner-private → image | MISSING |
| `build_configuration.jump_ratio`, `reconciliation_tolerance` | quality-plan thresholds | defaults exist in code (`DEFAULT_JUMP_RATIO`, `DEFAULT_RECONCILIATION_TOLERANCE`) | decimals | Git (defaults) · owner-private (override) | PRESENT as defaults; an override is an owner decision |
| pinned derivation versions | `adjustment_policy`, `adjustment_convention`, `adjustment_derivation_version`, `action_selection_version`, `silver_normalization_version`, `source_schema_version` | the code's constants (`SPLIT_ONLY`, `FORWARD_BASE_NORMALIZED`, `sharadar-adjusted-bars-v2`, `sharadar-action-selection-v1`, `sharadar-silver-v2`, `sharadar-csv-production-v1`) | a document pinned to another derivation refuses (`DERIVATION_VERSION_MISMATCH`) | Git | PRESENT |
| build input v1 — `build_identity`, `runs[]`, `ledger_digest`, validity | which completed runs a build reads; each row (`run_identity`, `slice`, `plan_digest`, `outcome`, `launched_at`, `completed_at`) is reconciled against the run locator before any object is read | the owner ledger, completed rows only | ≤ 32 runs; `ledger_digest` = SHA-256 over the canonical rows; every identity distinct; ≤ 24 h | SSM (per build) · owner-private (ledger) | MISSING — no completed run exists to build from |
| build runtime binding (SSM) and human binding (file) | as for acquisition, with `build_profile` | as for acquisition | as for acquisition | Terraform → SSM · owner-private | MISSING |
| split-ratio semantics · action-event identity | the adjustment consumes `SPLIT_ONLY` actions forward-normalized; spinoffs exclude from their ex-date; announcement-based signals and spinoff adjustment stay gated (ADR-0034) | accepted as restrictions; the vendor semantics behind them stay undocumented (ADR-0043 §6, ADR-0044 §8: *unresolved*) | — | Git (the restriction) | AWAITING VERIFICATION — resolvable only from real deliveries and the owner's review; **not** a value to supply |

### 2.4 Terraform gate inputs (git-ignored `terraform.tfvars`)

| Input | Consumer | Validation | Status |
|---|---|---|---|
| `production_stage` | every `production_*` resource's count | `none` / `a` / `b`; `b` refused without the R-3 digest | PRESENT as `none`; moving it is an authorized apply |
| `production_r3_verification_digest` | the stage-b gate | 64 hex — the SHA-256 of the owner's R-3 verification record | MISSING — R-3 not verified |
| `production_target_account_id` (optional) | bindings, parameter ARNs, assignments | 12 digits, in `allowed_account_ids`, **equal** to the provider's account and the qualification target (a blocking precondition) | defaults to the qualification target |
| `production_acquisition_secret_arn`, `production_provider_origin_cidrs`, `production_binding_provenance`, `production_image_digests` | §2.2 / §2.1 | as stated there | MISSING |
| `identity_center_region` | the generated-role ARN path shape in the KMS key policy | an AWS Region name; the instance's Region, not `aws_region` | MISSING |
| `production_apply_principal_arn_pattern` | the key policy's administration statement — the **administrator binding** | an IAM role ARN pattern matching the real apply principal; KMS's lockout safety check refuses a policy excluding the caller | MISSING |
| `production_endpoints_enabled` | the six hourly-billed interface endpoints | a toggle; each flip is an apply under its own spend authorization (§4.21) | PRESENT as `false` |

### 2.5 Launch-tool values (`CompiledLaunch`, per actor)

`cluster_arn`, `task_definition_arn` (exact revision), `image_digest` (registry), `configuration_digest`
(generation record), `task_role_arn`, `execution_role_arn`, `subnet_id` (the first public subnet for
acquisition; the stage-a build subnet for build), `security_group_ids`, `assign_public_ip` (true for
acquisition, false for build — refused otherwise), `platform_version` (pinned; `LATEST` refused; AWS
documents `1.4.0` as the current Linux platform version, and the value is still an owner input),
`binding_key_arn`. **All MISSING**: every one is read from Terraform state or outputs after a stage-a
apply and from the image and generation records, and no tool compiles them today (§7).

### 2.6 Receipt collection and ledger completion

| Input | Purpose | Source | Status |
|---|---|---|---|
| the task's `receipt:` line | the one machine-readable line, bound to the launch record by `binding_digest` over `{task_id, task_definition_arn, image_digest, identity, input_digest, configuration_digest, code_commit}` | the task's stdout → the CloudWatch stream `production-<actor>/<container>/<task-id>` | MISSING — no task has run |
| the launch record | every value in that set, from the tool's own launch | the launch tool (does not exist — §7) | MISSING |
| `logs:GetLogEvents` / `FilterLogEvents` for the two launcher permission sets | reading the stream from the workstation | an IAM delta ADR-0044 §5 **defers** to the infrastructure cycle | DEFERRED — not declared, not proposed for this cycle |
| the ledger row | `COMPLETED` only from a `COMPLETED` receipt with observed counts; `HALTED`/`REFUSED` from their outcomes; **no row** for `UNCLASSIFIED`, `LOCATOR_STATE_UNKNOWN`, `MANIFEST_STATE_UNKNOWN`; missing evidence never becomes zeros | `receipts.ledger_completion` | MISSING — until a collector exists the owner reads the log and completes the row by hand (ADR-0043 §4), and a row completed by hand is recorded as such |

---

## 3. The verification-path question, resolved from code

### 3.1 The finding

**Traced path.** `scripts/production_task_entrypoint.py::main` → `select_entry` →
`_compiled_configuration` → `pre_entry_refusal` (configuration is this entry's; credential
environment is a task's by name; the container URI is the documented shape) → working directory under
`/work` → `run_task_entry` → `run_acquisition_entry` / `run_build_entry` → factories called once
(SSM, STS, S3, Secrets Manager, transport) → `run_production_acquisition` / `run_production_build` →
`run_task_bootstrap` (environment → binding → input → self-check → identity proof → release barrier)
→ **`RELEASED`** → processing.

**The accepted code cannot perform R-1/R-2 and stop.** `run_task_bootstrap` returns `RELEASED` with
zero data-plane operations, but nothing on a composed entry consumes that outcome as a terminal one:

- `entry.BOOTSTRAP_OUTCOME` maps the eight bootstrap *refusals* to task outcomes and states in its
  own comment that "a released bootstrap continues into processing, and the bootstrap-only halt
  never occurs on a composed entry";
- `processing.run_production_acquisition` proceeds from `RELEASED` **directly** to the durable run
  reservation — one conditional `PutObject` to `bronze/_production_claims/runs/<run-id>.json` that
  **permanently spends the run identity** (ADR-0038) — then to `GetSecretValue`, then to the paced
  provider requests and the Bronze writes;
- `build_processing.run_production_build` proceeds from `RELEASED` directly to the locator read and
  the exact reads;
- `runner.run_build_task` is the only surface that halts after `RELEASED`
  (`HALTED_PROCESSING_NOT_IMPLEMENTED`), and ADR-0043 §2 states it "is not the build image's path";
  no entry reaches it;
- `TaskOutcome` has **no** "verification only" member, and ADR-0036 R-1 requires the task to "exit
  with the closed *verification only* code".

**So a matching release written to the production image is not a harmless verification run**: for
the acquisition image it reserves an identity, retrieves the secret and contacts the provider; for
the build image it reads licensed bytes. R-1's positive cell cannot be exercised with the accepted
images, and R-1's negative cells (no release → `REFUSED_NO_RELEASE` at the 300 s ceiling; a
mismatched release → `REFUSED_RELEASE_MISMATCH`) can — but a negative cell alone does not verify
that the positive path reaches the barrier and accepts a release. R-2's provider-origin probe from
the build subnet is likewise "a deliberate probe in the verification image, not in the production
image" (ADR-0036 §3), and no such image or probe exists.

**No runtime switch is added here.** A flag, an environment variable or a task-definition
`command` override that turned processing off would be exactly the override surface ADR-0036 §2.9
and ADR-0043 §5 refuse, and it is not proposed. **The verification command does not exist**, and
this document does not claim otherwise.

### 3.2 The smallest bounded follow-up — PROPOSED, not accepted, not implemented

A contract decision plus code, for the next cycle (§8); nothing here is decided:

1. **One additional closed entry per actor** — a third and fourth `TaskEntry` member
   (`kalpamani-production-acquire-verify`, `kalpamani-research-build-verify`) whose composed path is
   the accepted bootstrap **and nothing after `RELEASED`**, exiting with one new closed
   `TaskOutcome` (`VERIFIED_BOOTSTRAP`, a non-zero exit code so that `0` stays `COMPLETED` alone)
   and the same receipt line. The build verify entry additionally makes the R-2 origin probe, whose
   observed result is evidence and not an isolation verdict (§3.3); the ADR must also define what
   corroboration turns a non-connection into a verified isolation finding.
   Factories for the acquisition verify entry construct **no Secrets Manager client and no
   transport**, so the verification image cannot perform the operations it exists to prove it did not.
2. **Two verification task-definition families** (`…-acquire-verify`, `…-build-verify`) declared at
   stage a beside the production ones, each with its actor's task role, the same network placement
   and the verification image; **each launcher set gains exactly one more `ecs:RunTask` resource**
   (its actor's verification revision) — §4.2 item 4 explains why this is the least-privilege way to
   run R-1/R-2 without rescoping the launcher between images.
3. **An ADR** amending ADR-0043 §2 (two entries → four, the verification entries stated as
   bootstrap-only), ADR-0036 §2.9 (the launcher's `RunTask` resource set) and §3 (R-1/R-2 as
   verification-image cells with the exact expected exit code, the probe's own accounting, and the
   corroboration a non-connection needs before R-2 is anything but INCONCLUSIVE), with
   the static guard A-8 extended to the verify entries and a test that a verify entry's factories have
   no secret and no transport.

The alternative — running R-1/R-2 with the production image and a **deliberately absent release**,
so that only the negative cells are exercised — is recorded as **insufficient** for the positive
cell and is not proposed as a substitute.

### 3.3 Verification-image evidence boundaries

**A verification-image success does not prove production-image execution.** The two tasks share a
code commit and the bootstrap implementation and differ in entry, image, configuration digest and
what follows the barrier. For each property: what a verification task **directly establishes**
(D), what a **configuration-equivalence check** establishes (E — the launch tool compares the two
`CompiledLaunch` records and the two task definitions field by field), and what stays **untested
until the production image is exercised** (U).

| Property | Verification task | Production task | D / E / U |
|---|---|---|---|
| code commit; bootstrap implementation | the same `code_commit` compiled in, the same `run_task_bootstrap`, the same `pre_entry_refusal`, metadata, identity and barrier modules | the same | **D** for the bootstrap code path on this commit; **U** for the entry's own composition (`run_acquisition_entry` / `run_build_entry` are never entered by a verify entry) |
| image digest | the verification image's registry digest, attested by `DescribeTasks` and bound by its release | a different digest | **D** only for the verification image; **U** for the production image — a different image is a different set of bytes, however identical the source |
| configuration digest; entry / family | the verification entry's compiled configuration (same owner inputs, different `entry`, therefore a different digest); family `…-verify` | the production entry's file and family | **E** that the two configurations differ **only** in `entry` (the generator is deterministic: same inputs, same commit, same instant); **U** that the production entry reads and applies its file — only the production task does |
| task role; execution role | the actor's task role and the shared execution role, from the verification task definition | the same two ARNs from the production task definition | **E** (the two task definitions name the same roles; the launcher's `iam:PassRole` allowlist is the same two roles); **D** for the identity proof under that role on the verify task; **U** for the production task's own proof (repeated per launch by design) |
| network placement (subnet, security groups, public IP) | the compiled per-actor placement, verified by the launch tool's `DescribeTasks` / `DescribeNetworkInterfaces` | the same compiled values | **E** (same `CompiledLaunch` placement fields); **D** that the verify task was placed there; **U** that the production task is — verified per launch |
| platform version; `user`; read-only root; `/work` tmpfs | pinned at `RunTask`; the task definition's `user = 10001:10001`, `readonlyRootFilesystem`, tmpfs `/work` | the same declared shape | **E** (the same declaration fields); **D** that `/work` was writable for uid 10001 on the verify task (the working directory step passed, §4.3 S9a); **U** that the production image's process finds the same — the same platform and declaration, a different image |
| binding processing | two `ssm:GetParameter` reads, the same loader, the same actor constants | the same | **D** for the binding parameter's decryptability and shape under the task role; **U** nothing further — the parameter and loader are identical |
| input processing | the real acquisition input v2 / build input v1 admitted (`bind_plan`, spent identities, ledger digest); **no** reservation follows | the same admission, then processing | **D** for admission of that input; **U** for everything the production path does with it |
| release processing | a v2 release bound to the verify task ARN, revision, image digest, configuration digest, identity, input digest | a release bound to the production task's values | **D** that the barrier accepts a matching release and refuses the negative cells; **U** that the production task's barrier does — same code, a different release |
| provider-origin probe (build verify only) | **one** bounded connection attempt (proposed: TCP connect, 443, ≤ 5 s, no request bytes — values the §3.2 ADR decides) to one resolved address of the pinned origin from the build subnet, counted as `probe_attempts = 1` in the receipt; the **observed connection result** is one closed member — `CONNECTED`, `CONNECTION_REFUSED`, `TIMED_OUT`, `UNRESOLVED` — and is recorded as an observation only | no probe; the build image imports no transport (A-8) | **D** the observed result and the count, for that one destination at that one instant, and nothing more. **A timeout or a refusal does not establish that the build subnet's routing or security groups blocked the provider**: a destination failure, a remote rejection, a resolver failure or a transient condition produces the same observation. The **isolation conclusion is a separate finding**: `CONNECTED` **fails** the no-connectivity check for that destination and instant; a non-connection is **INCONCLUSIVE, never VERIFIED**, unless corroborated by evidence that attributes the failure to this account's network controls (the kind the §3.2 ADR must specify — for example a same-instant comparison from a route that is permitted to reach the origin, or a flow-log record of the rejected attempt — each with its own limits: a comparison covers one instant and one address; a log names a rule, not a reason). No corroboration procedure is accepted or authorized here, and no probe permission is broadened. **U** everything about the production build image, which makes no such attempt; the probe is never an assertion about every address or every moment |
| processing capabilities deliberately absent | the acquisition verify entry has no secrets client and no transport; the build verify entry has no S3 client at all; **zero** `GetSecretValue`, provider API requests and data-plane S3 operations by construction, asserted by counting fakes | present | **D** only that the verify image lacks them; **U** every production capability — reservation, credential, provider requests, Bronze writes, locator; locator read, exact reads, Silver, Gold, manifest |

**What "zero" means, precisely.** A verification task makes AWS requests: the metadata read, two or
three `ssm:GetParameter` reads (plus up to 60 barrier polls), one `sts:GetCallerIdentity`, the image
pull and log writes by the agent, and — build verify only — one provider-origin connection attempt.
What is zero is **provider API requests**, **`GetSecretValue`** and **data-plane S3 operations**.
"Zero network attempts" is never claimed.

**The probe's two records are kept apart.** The receipt carries the observed result and the attempt
count; the R-2 cell's isolation verdict (`FAILED` on `CONNECTED`; otherwise `INCONCLUSIVE` until
corroborated, and `VERIFIED` only with the corroboration the §3.2 ADR defines) is recorded by the owner
beside the receipt, never derived from the receipt alone. Reading a timeout as isolation is the error
this separation exists to prevent.

**What a pass authorizes.** Nothing beyond the recorded cell. The production image is exercised for
the first time by the first authorized production run, whose own release, identity proof and receipt
are the evidence for it; every U row above is closed only by that run.

---

## 4. Cloud-verification sequence

### 4.1 Ordering, derived from the accepted decisions and the declared configuration

```text
S0   owner inputs           secret (created outside Terraform), origin address set, release commit,
                            I-8/I-9 decisions, ledger initialized, tfvars values, private bindings
S1   compiled configuration production_compiled_configuration.py per entry (image gate). The build
                            entry's accepted_schemas is Route A digests (attributed) or Route B's
                            explicitly empty set (an OBSERVATION configuration) -- 4.2 item 6
S2   build context + image  production_build_context.py; docker build; step-6 local verification
S3   publish                push to the ONE research repository; record RepoDigests (registry digest)
S4   stage a (Terraform)    plan review; apply: policies, bucket-policy statements, task roles, bootstrap
                            policies, KMS key + alias, binding parameters, network, task definitions
                            (pinned by the S3 digests), the four permission sets + policy references;
                            NO assignments; administrator-binding and shared-route effects (4.4)
S5   R-3                    server-side conditional-write verification by the control principal,
                            nine expected-path operations, failure-path cleanup budget 10;
                            record + digest -> production_r3_verification_digest
S6   stage b (Terraform)    the four account assignments and nothing else. FROM HERE ON EVERY APPLY
                            KEEPS production_stage = "b" AND THE R-3 DIGEST (4.6)
S7   human profiles         materialize the four governed profiles; identity preflights; the two
                            production human bindings under the ADR-0023 trust boundary
S8   R-4 .. R-9             permitted/denied matrix: IAM simulation (L2) then live cells (L3),
                            synthetic objects only, deletion-role cleanup
S9   R-1 / R-2              runtime verification -- BLOCKED on the verification-only path (3.2)
S10a first acquisition      one authorized run -> production Bronze exists
S10b schema digests         Route A: attributed digests already compiled at S1, nothing to do here;
                            Route B: one authorized OBSERVATION build (zero writes) -> per-dataset
                            digests in its refusal receipt AS EVIDENCE -> owner review and explicit
                            acceptance under the applicable gate -> a new build configuration naming
                            only the accepted digests -> S1-S3 for the build image only -> a
                            stage-b-PRESERVING apply (4.6). No digest is promoted automatically
S10c first build            one authorized build -> Silver, Gold, one manifest
```

**What exists before the first acquisition, and what becomes available afterwards.** Before S10a:
both images published and registered (the build image compiled either with Route A digests or as
Route B's observation image); stage b; the four profiles; every human binding; no production Bronze,
no locator, no observed production schema digest, no ledger row. After S10a: production Bronze, one
locator, one completed ledger row — and, under Route B, the possibility of observing the digests
(S10b); only after S10b's observation, the owner's explicit acceptance of the observed digests and a
rebuilt image does a Silver-producing build image exist. Under Route A the digests are
compiled before S10a, and the first build confirms them or refuses `SCHEMA_UNSTABLE` with zero writes.

### 4.2 The dependency cycle, reconciled

The apparent cycle is: R-1/R-2 need a launcher that can run a task → the launcher's `ecs:RunTask`
is scoped to exactly one task-definition revision (`production_policies.tf`) → a revision exists
only at stage a and pins an image digest → an image exists only after S3 → but the launcher is
**assigned** only at stage b, which requires R-3 → and R-3 does not need a task at all.

It resolves as follows, and each arrow is a fact of the declaration or of an accepted decision:

1. **Image before infrastructure.** Stage a *requires* `production_image_digests` for both actors
   (`production_variables.tf`), so S3 precedes S4. A task definition cannot be registered without a
   digest, and a placeholder digest is refused by the variable's grammar only by shape — a
   placeholder that matched the grammar would register a revision naming an image that does not
   exist, and the launcher would then be scoped to it. **Publish first.**
2. **R-3 needs no principal from this design.** It runs under the foundation apply principal
   against stage a's bucket policy, with a fresh positive control; it needs no task, no launcher and
   no assignment. So S5 sits strictly between S4 and S6 and nothing about images or launchers
   blocks it.
3. **Launchers are scoped at stage a and usable only at stage b.** The permission sets and their
   `RunTask` resource exist from S4; a human can assume them only after S6. R-6 (launcher cells)
   therefore follows S6, and R-1/R-2 follow S6 too.
4. **The verification image cannot be a rescoped production launcher.** If R-1/R-2 used a separate
   verification image registered *first* as the family's revision, every later production image
   would be a new revision, and the launcher's single `RunTask` resource would have to be moved by a
   further apply — two applies per verification, and a window in which the launcher can run the
   verification revision but not the production one, or the reverse. **The smallest reconciliation
   is §3's**: separate verification families whose revisions the launcher may also run, so that the
   production revision is registered once, the verification revision beside it, and one stage-a
   apply covers both.
5. **Rotation re-enters the cycle at S1 and never leaves stage b.** A secret rename, an origin address
   change or a build configuration change is a new compiled configuration → a new image → a new
   digest → a new revision → an apply **at the stage already established** (ADR-0044 §2; §4.6). The
   launcher's `RunTask` resource follows the revision automatically because it references the
   Terraform resource, not a literal — only the rotated actor's launcher policy changes.
6. **The first-build cycle is a second cycle, and separate verification families do not touch it.**
   Stage a requires the **build** digest too (item 1) → the build image needs per-dataset accepted
   schema digests baked into its configuration (`compiled.py`, `silver._parse`) → production digests
   are observable only inside the boundary, by the build task, from production Bronze (ADR-0036 §2.3,
   §2.10; the acquisition path parses nothing) → production Bronze needs stage b and an authorized run.
   Two routes, and no third: **Route A** (accepted, evidence-backed, *conditional*) — the private
   combined qualification report records `observed_schema_digests` computed by the very parser and
   `schema_digest_of` Silver imports, over real deliveries of the same three tables; but the set is
   unattributed to datasets, was observed under the ticker-keyed request form, and header identity
   across the two forms is documented (PSR-SHD-110/-112/-113 list columns) and not empirically
   established; attribution is an owner-side offline equality check between `schema_digest_of` over a
   documented header and an observed digest — complete column list in the register for `actions`
   only, and no documented delivered order — so the route is **available in part and unproven**, and a
   digest it cannot attribute is simply not compiled (the build then refuses, zero writes; nothing is
   relaxed). **Route B** (PROPOSED / BLOCKING pending an ADR and its implementation): the first build
   image is an **observation image** — a real compiled configuration whose accepted set is explicitly
   empty (parses; admits nothing) — run once after S10a, reading the locator and exactly what it names,
   refusing `REFUSED_NORMALIZATION` with zero writes, and reporting the **per-dataset observed schema
   digests** in its receipt **as evidence for the owner's review** — never as an accepted set; a later
   configuration names only the digests the owner explicitly accepted under the applicable gate, and
   a second build image is compiled from that (one more image cycle, stage b preserved). No automatic
   promotion exists, and schema validation is unchanged at every step. Affected by Route B: ADR-0044 §4 (the receipt's closed field set), the ADR-0036
   §2.9 output rule as ADR-0044 narrowed it, `silver.normalize` (collect every page's digest before
   refusing), `build_processing`, `receipts.py`; **no new permission and no new S3 operation**. Neither
   route invents a digest, registers a placeholder image, uses a fixture configuration or admits an
   unobserved header. See the disposition record F-1.

### 4.3 The execution matrix

For every step: prerequisites and authorization · actor and minimum permissions · the exact command or
the missing implementation · allowed side effects and limits · positive and negative evidence · halt
conditions, cleanup and residual state. **A step whose command cannot be instantiated names the
missing inputs; nothing below invents an identifier, a budget, a permission or a threshold.**

| # | Step | Prerequisites · authorization | Actor · minimum permissions | Command / implementation | Side effects · limits | Evidence (positive / negative) | Halt · cleanup · residue |
|---|---|---|---|---|---|---|---|
| S0 | Owner inputs | the owner's written authorization for the image gate; the production secret created by the owner outside Terraform (never by this repository) | the owner; Secrets Manager `CreateSecret` under an owner profile is **outside** this design's principals and is not enumerated here | no command in this repository; the checklist in `production-owner-inputs.md` | none | positive: every checklist row has a value held outside the repository; negative: any row still `MISSING` | halt on any missing row; nothing to clean |
| S1 | Compiled configuration | S0; a clean checkout at the release commit; for the build entry, either Route A attributed digests or the Route B observation set (explicitly empty) — never a fixture set | the owner, workstation; no AWS permission | `python scripts/production_compiled_configuration.py --entry <entry> --inputs <owner path> --generated-at <ISO> --output docker/production/build/<entry>` — **needs**: release commit checked out, the owner inputs files | writes the git-ignored staging directory only; no network | positive: `configuration_digest=<64 hex>` printed, `generation-record.json` names the commit and tree; negative: `compiled configuration refused: <reason>` (dirty tree, forbidden field, ARN as secret name, empty or non-IPv4 addresses, build configuration refused) | halt on refusal; residue is the staging directory, deletable |
| S2 | Context, build, local verification | S1; image-gate authorization; `BASE_IMAGE_DIGEST` resolved | the owner, workstation Docker; no AWS permission | `production-image-build.md` steps 3–6 (context preparer, `docker build`, the task-shaped container checks) — **needs**: base digest, build arguments read from `context-manifest.json` | local images only; no push; the local verification's `--network none` shape | positive: the step-6 checks (`exit 4` with no credentials, `exit 2` on an extra argument, `exit 3` on an absent or other-actor configuration, `exit 6` with `/work` unwritable, configuration bytes hash to the digest); negative: any other exit or a traceback | halt on any mismatch; residue: local images and contexts |
| S3 | Publish and record the digest | S2; image-publication authorization | an owner profile with `ecr:GetAuthorizationToken`, `ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`, `ecr:CompleteLayerUpload`, `ecr:PutImage`, `ecr:BatchCheckLayerAvailability` on the one research repository — **the foundation's existing principals grant only pulls**; which profile pushes is an owner decision | `docker login` via `aws ecr get-login-password` (the token is never printed), `docker tag`, `docker push`; then `docker inspect --format '{{index .RepoDigests 0}}'` — **needs**: the repository URI (a Terraform output) | one image manifest and its layers per actor in the research repository; the untagged-image lifecycle rule applies to superseded pushes | positive: a `sha256:` registry digest per actor recorded beside the generation record; negative: a push refused, or a digest that is a local image id | halt on refusal; residue: pushed layers (deletable by the owner; not part of the licensed store) |
| S4 | Stage a — plan review and apply | S3; §4.21 authorization for the apply **and** separately for recurring spend (KMS key; endpoints only if toggled); tfvars complete for stage a | the `kalpamani-foundation` profile (the Terraform-apply principal); the §4.24 identity gate | `scripts/aws_foundation_verify.py` identity gate; `terraform plan -out=<saved plan>` reviewed in full; `terraform apply <saved plan>`; independent post-apply verification — **needs**: every §2.4 value | creates: 8 policies, 2 task roles, KMS key + alias, 2 binding parameters, build subnet + route table, endpoint SGs, S3 gateway endpoint, task SGs, 2 task definitions, 4 permission sets + attachments; changes: the licensed **bucket policy** (three Deny statements) and the **public route table** (S3 gateway association); no assignment | positive: plan shows exactly the stage-a resource set and `0 to destroy`; the account precondition passes; post-apply verification reads each object; negative: the precondition fails, KMS's lockout check refuses the key policy (administrator binding wrong), any destroy | halt before apply on any unexpected plan line; the saved plan is the only thing applied; residue after a failed apply is whatever Terraform recorded — resolved by a further governed apply, never by hand |
| S4a | Administrator-binding verification | S4 | the apply principal | confirm the key policy's `StringLike` administration pattern binds the **real** apply principal ARN (a `kms:DescribeKey` and a read of the policy under the apply profile; PASS/FAIL only, no ARN printed) | read-only | positive: PASS; negative: FAIL — a key nobody administers | halt: the key policy is corrected by a governed apply |
| S4b | Shared-route effect check | S4 | the apply principal | read the public route table: the S3 prefix-list route now targets the gateway endpoint whose policy admits **only** the licensed bucket and the ECR layer bucket — so any task on the public subnets (the qualification tasks, the foundation `<prefix>-task` role) reaches **no other bucket** through that route; the workstation is unaffected | none | positive: the effect is recorded and accepted in writing; negative: an unrecorded change of reach for an existing principal | halt: if the effect is not accepted, stage a is reverted by a governed apply |
| S5 | R-3 | S4; R-3 authorization | the **control principal** — the foundation apply profile, which holds unconditional `s3:PutObject` and the cleanup actions (ADR-0036 §3) | **missing implementation**: no tool executes the nine expected-path rows and the failure-path cleanup with counted operations and classified error contexts; until one exists the rows are owner-run CLI operations, each recorded with its counted result | 1 `GetCallerIdentity`; **9** S3 operations on the expected path under `licensed/_verification/<stamp>/`; **≤ 10** more on the failure path; synthetic 64-byte markers only | positive: rows 1–9 exactly as the table (200 · 403 resource-based · 404 · 403 · 501/403 · 403 · 404 · 204 · 404) → **verified**; negative: any `200` on rows 2/4/5/6, any `403` without the resource-based context, any object found on rows 3/7/9 → **not verified**; a row not executed → **not exercised** | halt on any deviation; cleanup per the failure-path table before recording; unresolved cleanup keeps the gate closed and names the synthetic key; residue: none when verified |
| S5a | R-3 record | S5 | the owner | write the sanitized record (classifications and counts only); `production_r3_verification_digest = SHA-256(record)` into tfvars | none | positive: a 64-hex digest of a record that says *verified*; negative: a digest of a record that says otherwise is **not** supplied | — |
| S6 | Stage b | S5a; assignment authorization | the apply principal | `terraform plan`/`apply` with `production_stage = "b"` — the plan must show **exactly four** `aws_ssoadmin_account_assignment` additions | four assignments; Identity Center creates four generated roles | positive: four assignments, four generated roles verified; negative: anything else in the plan | halt on any other plan line |
| S7 | Profiles and human bindings | S6; profile-materialization authorization | the owner operator (the governed group's one member) | materialize `kalpamani-production-acquisition`, `kalpamani-research-build`, and the two launcher profiles; one identity preflight each (PASS/FAIL); **missing implementation**: a production human-binding materializer for the two ADR-0036 §2.5 files | four profile entries; two private files | positive: four `IDENTITY_PREFLIGHT: PASS`, `human_bootstrap` → `IDENTITY_PROVEN` for each actor and path; negative: any crossover (a profile resolving to another actor's role) | halt on crossover; residue: profile entries and files, owner-held |
| S8 | R-4 … R-9 | S7; per-cell authorization, each counted | each cell's principal; the deletion role for cleanup | L2: `SimulatePrincipalPolicy` per identity-policy cell (no resource policy — unsupported for roles); L3: one real request per cell with synthetic objects — **missing implementation**: no cell runner; owner-run CLI per cell | one operation per cell; synthetic objects under the production prefixes, deleted afterwards under the runbook | positive: every "must succeed" cell succeeds and every "must be refused" cell is refused; negative: any inversion | halt on any inversion; cleanup by the deletion role; a cell decided by simulation only is recorded **simulated**, never verified |
| S9 | R-1 / R-2 | S6, S7; the §3 follow-up merged, built, published and registered; runtime-verification authorization | the actor's launcher set (`RunTask` on the verification revision), the actor's human set (input), the task role | **BLOCKED — no verification-only path exists** (§3); once it does: the launch tool (which also does not exist — §7) launches the verification revision with a real input; positive cell = a matching release; negative cells = no release, a mismatched release, and (build) the origin probe | one task per cell; two parameter reads (binding, input) then ≤ 60 barrier reads of the release; 1 `GetCallerIdentity`; **zero** S3, secret and provider operations by construction | positive: `VERIFIED_BOOTSTRAP` with a receipt whose `binding_digest` matches the launch record; negative: `REFUSED_NO_RELEASE` at the ceiling, `REFUSED_RELEASE_MISMATCH`; the build probe's observed result is recorded as an observation — `CONNECTED` fails R-2 for that destination and instant, a non-connection leaves the isolation verdict **INCONCLUSIVE** until corroborated as the §3.2 ADR specifies (§3.3) | halt on any data-plane count above zero; cleanup: release and input `DeleteParameter`; residue: the run identity used by the verification input is **spent** only if a reservation was written — a verify entry writes none |
| S9a | `/work` mount under uid 10001 | S9 | the same | inside the verification task, the working directory is created under `/work` after the credential-environment check (`REFUSED_DEPENDENCY` if not) | none | positive: the verify entry passes the working-directory step (not `exit 6`); negative: `REFUSED_DEPENDENCY` — Fargate did not give uid 10001 a writable `/work` (§5) | halt: a task-definition change (mount options `uid`/`gid`/`mode`, which the API documents as valid values) is a declaration change under its own apply |
| S10a | First bounded acquisition | S9 verified; ADR-0035 §5.2 I-8…I-12 supplied; one written authorization for one run | acquisition human set (input), acquisition launcher set (launch, release), acquisition task role | the launch tool — **missing implementation** (§7) | 1 run reservation + 3 writes per request + 1 locator (`1 + 3R + 1` conditional `PutObject`, R ≤ 96); 1 `GetSecretValue`; R provider requests, zero retries, 1,800 s deadline; a spent identity | positive: `COMPLETED` receipt with observed counts equal to the plan; negative: any halt outcome — `REFUSED_RESERVATION`, `REFUSED_CREDENTIAL`, `ACQUISITION_HALTED`, `LOCATOR_*` | halt: no retry under the same identity (spent); cleanup: input and release parameters; residue: Bronze objects (deletable only under the runbook) |
| S10b | Schema digests (Route B only) | S10a `COMPLETED`; the Route B ADR accepted and implemented; one written authorization for one observation build | build human set (input), build launcher set, build task role | the launch tool — **missing implementation** (§7) — launches the **observation** build revision with a real build input | 1 locator read + exact reads of the objects it names; **zero writes** (the empty accepted set refuses before any Silver object); 3,600 s deadline | positive: `REFUSED_NORMALIZATION` with a receipt carrying one 64-hex digest set per dataset and zero data-plane writes; negative: `REFUSED_INPUTS` (nothing read past the locator), or any write count above zero (a defect) | halt on any write; cleanup: input and release parameters; residue: none in the store. Then: the reported digests are **evidence for owner review**; the owner explicitly accepts, per dataset, the digests the next configuration may admit, under the applicable gate → generate the build configuration from the accepted set only → S1–S3 for the build image only → a **stage-b-preserving** apply (§4.6). No automatic promotion; validation unchanged |
| S10c | First bounded build | a Silver-producing build image registered at stage b — Route A: compiled before S10a; Route B: after S10b — and one written authorization for one build | build human set, build launcher set, build task role | the launch tool — **missing implementation** | 1 locator read + exact reads of what it names; Silver, Gold and one manifest **last**; 3,600 s deadline | positive: `COMPLETED` with a manifest; negative: `REFUSED_INPUTS`/`REFUSED_NORMALIZATION`/… with zero writes | halt on any refusal; residue: LICENSED Silver/Gold/manifest objects |

### 4.4 Effects the owner accepts in writing before stage a

- **Administrator binding.** The `kalpamani-task-bindings` key policy names the account root under
  a `StringLike` pattern for the apply principal (`production_apply_principal_arn_pattern`); a pattern
  that does not match the real apply role leaves the key with no administrator KMS will accept — KMS's
  lockout safety check refuses such a policy at apply time, which is the documented backstop, and S4a
  is the check that the pattern binds the right principal rather than merely some principal.
- **Shared route.** The S3 gateway endpoint associates with the **existing public route table**. Its
  endpoint policy admits only the licensed bucket and the regional ECR layer bucket, so every task on
  the public subnets — including any future qualification task and anything running as the foundation
  `<prefix>-task` role — loses S3 reach to the CONTROL bucket, the Terraform state bucket and every
  other bucket through that route. The workstation and the deletion runbook (run from the workstation)
  are unaffected. This is a change of reach for existing principals and is recorded here so it is
  accepted, not discovered.
- **The licensed bucket policy** gains three Deny statements scoped to the production prefixes and
  `_verification/`; the qualification prefixes are excluded by enumeration.
- **Recurring spend.** The KMS key (monthly) and, when toggled, six interface endpoints (hourly).

### 4.5 R-5 (build actor) requirements, as they apply

R-5's live cells need objects to read — a Bronze payload, record and locator under the production
prefixes. Before the first acquisition there are none; the exact-read cells are therefore exercised
against **synthetic objects written by the control principal under the same prefixes for that
purpose** and deleted under the runbook afterwards (a repository-owned synthetic payload, never a
vendor row), or they are exercised after S10a against real objects with the same counts. Which of the
two is chosen is an owner decision recorded with the R-5 authorization; the cells and their expected
refusals are unchanged either way.

### 4.6 Preserving stage b — rotation, re-verification, and the applicability of evidence

**The declaration.** The four account assignments exist only while `production_stage == "b"`
(`production_principals.tf`, `count = local.production_count_b`), and `"b"` requires
`production_r3_verification_digest` (`production_variables.tf`). An apply at `"a"` after the assignments
exist plans **four destroys** and removes every generated Identity Center role with them; an apply at
`"none"` plans the destruction of the whole production set.

**The rule, for every apply after S6.** `production_stage = "b"` and the recorded R-3 digest stay in
`terraform.tfvars`; a rotation changes `production_image_digests` (and, for an origin-address change,
`production_provider_origin_cidrs`) and nothing else; the reviewed plan for a rotation shows the new
task-definition revision(s) and the corresponding launcher policy update(s) and **no
`aws_ssoadmin_account_assignment` change**. **Assignment removal is a separate governed decision**,
planned and reviewed as such, and is never an incidental step of an image update. Initial establishment
is `a` → R-3 evidence → `b`, once. **An ordinary image or configuration rotation preserves stage b and
its assignments provided the verified controls it relies on — the bucket policy R-3 verified, the
principal policies the R-4 … R-9 cells exercised — are unchanged by that apply.**

**Evidence must stay applicable, and a digest does not attest to what it did not verify.** The R-3
record describes the licensed bucket policy as deployed at the time, the target it was exercised
against and the conditions of that verification; it applies only while those hold. A prior evidence
digest supplied in `terraform.tfvars` attests to the policy it verified and **not** to a changed one.
Fresh runtime R-3 evidence for a **changed** bucket policy cannot exist before that policy is deployed, so
no instruction here asks for it in that order. **A bucket-policy change therefore requires a separately
reviewed transition procedure**, which must govern the prevention of production use while the policy is
in transition, the deployment of the changed policy, its re-verification (an R-3 of the same shape against
the deployed policy), the cleanup of the verification's synthetic objects and the restoration of
authorized use. **This preparation record neither defines nor authorizes that procedure**, prescribes no
automatic return to stage `a` and no assignment removal as part of it, and does not design the policy
under which other changes of target or verification conditions would be re-assessed; it records only
that applicability is the test and that an inapplicable record is not evidence.

| Change | Renews or invalidates | Basis |
|---|---|---|
| a new image digest (any actor) | a new task-definition revision and that actor's launcher policy; the release binds the new digest and revision per launch; R-3's applicability is unchanged because the bucket policy is untouched | ADR-0044 §2; `production_policies.tf` references the task-definition resource |
| a new compiled configuration (secret name, origin set, build configuration) | the same as above — it is an image rebuild | ADR-0044 §2 |
| a change to the deployed licensed bucket policy (its `storage.tf` statements, or anything else that changes what the policy refuses) | the existing R-3 record **no longer applies** to the changed policy; the change goes through the separately reviewed transition procedure above — prevent production use, deploy, re-verify against the deployed policy, clean up, restore — which this record does not define; the prior digest is not re-supplied as evidence for the changed policy | ADR-0036 §2.7, §3 (R-3 is evidence about the deployed bucket policy) |
| a change to a data-plane, bootstrap or launcher policy | the affected R-4 … R-9 cells' evidence no longer applies to that principal and is re-exercised; the ordering and prevention rules for such a change are part of the same unresolved transition question | ADR-0036 §3 |
| a change of target (bucket, account) or of the conditions a verification was run under | the evidence taken under the earlier target or conditions does not apply; what re-assessment is required is **not designed here** | — |
| a new verification image (proposed, §3.2) | that image's R-1/R-2 evidence is bound to its own digest and revision and is renewed by re-running the cells | §3.3 |
| a new **production** image after a verification pass | **unresolved policy** — no accepted text says whether R-1/R-2 must be repeated for every production revision; recorded as G-12, to be decided in the §3.2 ADR | — |

**Launcher-revision implications.** A rotation of one actor's image updates only that actor's launcher
policy; the other launcher is untouched. Under the proposed §3.2 design each launcher holds two `RunTask`
resources (production and verification revisions), and a rotation of either image leaves the other
resource alone. Terraform's replacement ordering for a task definition whose container definition changed
— a new revision registered and the previous deregistered, with the launcher policy re-pointed in the
same apply — was **not planned or verified here**, and the declaration is unchanged.

---

## 5. Fargate compatibility — documented support versus runtime evidence

Read on 2026-09-14 from the public AWS documentation; no AWS call was made.

| Question | Documented | Requires runtime evidence |
|---|---|---|
| `linuxParameters.tmpfs` on Fargate (the task definitions' `/work` mount) | **Supported for Linux tasks on Fargate** per the AWS announcement of 2026-01-06 ("Amazon ECS now supports tmpfs mounts on AWS Fargate and ECS Managed Instances") and the current `LinuxParameters` API reference, which carries a Fargate exclusion for `devices`, `maxSwap`, `sharedMemorySize` and `swappiness` and **none** for `tmpfs`. **Documentation conflict:** the developer guide's "task definition differences for Fargate" page still states "The `devices`, `sharedMemorySize`, and `tmpfs` parameters are not supported" — a statement the announcement and the API reference postdate. | whether `RegisterTaskDefinition` with `requiresCompatibilities = ["FARGATE"]` accepts the `tmpfs` block (a plan/apply-time fact, S4), and the mount's ownership and mode as seen by uid/gid `10001` under a read-only root (S9a). The declared `mountOptions` are `rw`, `noexec`, `nosuid`; the API documents `uid`, `gid` and `mode` as valid options, so a declaration change is available if the mount is not writable — it is not made here. |
| `readonlyRootFilesystem` | documented for Linux containers (maps to `--read-only`) | none beyond S9a |
| `user = "10001:10001"` | documented (`uid:gid` form) | none |
| `initProcessEnabled` | documented; no Fargate exclusion | none |
| bind mounts (the alternative to `tmpfs`) | documented for Fargate: ephemeral storage ≥ 20 GiB on platform 1.4.0, volume permissions default `0755` owner `root`, customizable through a Dockerfile `VOLUME` directive | not used by the declaration; recorded as the fallback if `tmpfs` registration is refused |
| task metadata endpoint v4, container credential provider | documented on platform 1.4.0 | the shapes the entrypoint validates (`169.254.170.2`, `/v4/<id>`, `/v2/credentials/<id>`) — S9 |
| platform version | `1.4.0` is the documented current Linux platform version; `CompiledLaunch` refuses `LATEST` | the value pinned at launch is an owner input |

---

## 6. Deferred, and kept deferred

- **The receipt collector and its IAM delta** (`logs:GetLogEvents`, `logs:FilterLogEvents` on the
  research log group's streams for the two launcher permission sets): **proposed in ADR-0044 §4–§5,
  not accepted, not declared, not implemented.** This cycle documents nothing further about it and
  does not make it accepted. Until it exists, a ledger row is completed by the owner reading the log
  stream by hand, and **a count that was not read is not zero** — `ledger_completion` returns no row
  without observed counts.
- **CONTROL** stays deferred; manifests stay LICENSED.
- **The ADR-0039 vocabulary integration** stays a build-local mirror.

---

## 7. Unresolved code and contract gaps

> **HISTORICAL — the register as of PR #103.** The verification-and-launch cycle (§9) has since
> implemented G-1, G-2, G-3 and the Route B half of G-7 offline, and proposed decisions for G-12 and
> G-15 in ADR-0045; §9.1 gives every gap's current disposition. Nothing below is rewritten.

| # | Gap | Kind | Blocks |
|---|---|---|---|
| G-1 | **No verification-only task path** (§3): `RELEASED` continues into processing on both composed entries; no `TaskOutcome` for bootstrap-only verification; no R-2 origin probe; ADR-0036 R-1/R-2 as written cannot be run with the accepted images | contract (ADR-0043 §2 entries; ADR-0036 §2.9/§3) + code | S9 |
| G-2 | **No owner-side launch tool**: `launch_authorized_run` has no script that builds the real ECS/EC2/SSM clients under the human and launcher profiles with their before-and-after identity proofs, compiles `CompiledLaunch` from Terraform records, and records the launch record the receipt is bound to | code | S9, S10 |
| G-3 | **No input-materialization tool** for the acquisition input v2 (`plan_digest_for`, `spent_identities_block`) and the build input (`ledger_digest`), nor for the owner ledger the inputs are cut from | code | S9, S10 |
| G-4 | **No production human-binding materializer** for the two ADR-0036 §2.5 private files (the qualification materializer writes a different contract) | code | S7 |
| G-5 | **No R-3 tool** executing the nine counted rows, classifying the access-denied context (resource-based explicit deny vs. other) and running the budgeted failure-path cleanup | code (the procedure is accepted) | S5 |
| G-6 | **No R-4 … R-9 cell runner** (L2 simulation + L3 live cells with counted operations) | code | S8 |
| G-7 | **The first-build cycle** (§4.2 item 6): stage a needs the build digest, the build image needs attributed per-dataset schema digests, production digests are observable only inside the boundary after the first acquisition. Route A (qualification `observed_schema_digests`) is accepted and evidence-backed but unattributed and unproven for the ticker-less form; **Route B (observation build + receipt amendment) is PROPOSED / BLOCKING** — an ADR amending ADR-0044 §4 and the narrowed ADR-0036 §2.9 output rule, plus `silver.normalize`, `build_processing` and `receipts.py` changes; under either route an observed digest is **evidence for owner review** and enters a configuration only by explicit acceptance | contract + code | S1 (build), S10b |
| G-8 | **No real exchange calendar** and no calendar source decision (the venv carries no tzdata; `sessions.py` is synthetic) | owner input + code | S10b |
| G-9 | **Receipt collection**: deferred by decision (§6); the ledger row is hand-completed until then | contract (deferred) | S10 ledger completion |
| G-10 | **Fargate `tmpfs` documentation conflict** (§5) — resolved only by S4's registration and S9a's mount check; a fallback declaration (`uid`/`gid`/`mode` options, or a bind mount) is available and not made | evidence | S4, S9a |
| G-11 | **ECR push permissions**: no principal in the foundation or production design holds image-push actions; which owner profile publishes is undecided | owner decision | S3 |
| G-12 | **Re-verification policy for production revisions**: no accepted text states whether R-1/R-2 must be repeated per new production image; the §3.2 ADR must decide it | contract | every rotation after S9 |
| G-14 | **Bucket-policy transition procedure**: a change to the deployed licensed bucket policy needs a separately reviewed procedure (prevent production use → deploy → re-verify against the deployed policy → clean up → restore) that no accepted text defines; this record neither defines nor authorizes it (§4.6) | contract | any bucket-policy change after S6 |
| G-15 | **R-2 corroboration**: a probe's non-connection is INCONCLUSIVE until corroborated; what corroboration is sufficient, and its limits, are for the §3.2 ADR — none is accepted or authorized here (§3.3) | contract | S9 (build) |
| G-13 | **Route A attribution evidence**: the register documents a complete column list for `actions` only (PSR-SHD-112) and no delivered order for any table; attributing `stocks` and `tickers` needs the vendor pages re-read (public documentation, a later authorized lookup) and still proves nothing about the ticker-less form until the first build | evidence | S1 (build) |

---

## 8. The single next bounded cycle

> **HISTORICAL — the scope as proposed in PR #103.** This cycle has been carried out, offline and
> on fakes only, in the pull request that proposes ADR-0045; §9 records what it delivered, what it
> only proposed, and what it left. The text below is the scope as it was set and is not rewritten.

**Scope: one offline, synthetic-only implementation cycle with one ADR, making the verification
path coherent end to end — G-1, G-2, the Route B receipt amendment (G-7) and the re-verification
policy (G-12) — so that S9 has a task that stops at the barrier, a tool that can launch it, and S10b a
way to observe the schema digests without a placeholder.** Concretely:

1. **an ADR** (proposed; no authority until merged) amending ADR-0043 §2 to four closed entries,
   ADR-0036 §2.9's launcher `RunTask` resource set (one production and one verification revision per
   actor), §3's R-1/R-2 cells with the exact closed exit code, the probe's own accounting
   (`probe_attempts`, the four observed-result members) **and the corroboration rule** that separates an
   observed non-connection from a verified isolation finding (§3.3), ADR-0044 §4's receipt field set
   (`observed_schema_digests` per dataset on build refusals — **evidence for owner review, never an
   accepted set** — and the probe fields on verify receipts) and the narrowed ADR-0036 §2.9 output rule,
   and deciding G-12;
2. `TaskEntry` + `TaskOutcome.VERIFIED_BOOTSTRAP` (non-zero), `run_acquisition_verify_entry` /
   `run_build_verify_entry` composing `run_task_bootstrap` and nothing after `RELEASED`, factories without
   a secrets client, transport or (build) S3 client, the build-side origin probe as one bounded connection
   attempt with a closed outcome, the receipt line extended exactly as the ADR states; the Dockerfile's two
   verify targets and entry executables; the static guard extended;
3. `silver.normalize` collecting every page's observed digest before refusing, `build_processing`
   surfacing the per-dataset set on `REFUSED_NORMALIZATION`, `receipts.py` validating it as **evidence** —
   nothing that writes an observed digest into an accepted set; the observation build needs no other code;
4. `scripts/production_launch.py`: the owner-side launch tool — human bootstrap, input materialization
   from an owner ledger file and a slice document (`plan_digest_for`, `spent_identities_block`,
   `ledger_digest`), `CompiledLaunch` compiled from a Terraform-output record, `launch_authorized_run` on
   real clients under the two profiles with pinned `AWS_PROFILE` and the §4.24 gate, the launch record
   written beside the input, the configuration-equivalence check of §3.3, and the cleanup — refusing by
   default, one explicit flag per authorized run, no output that names an identifier;
5. the Terraform declaration of the two verification families and the launcher resource additions,
   validated in an external copy only, with a mutation test that a rotation plan at stage b touches no
   assignment;
6. tests for each, against fakes; the docs audit and status synchronization.

**Can proceed independently alongside it** (no dependency on the above): G-4 (the production
human-binding materializer), G-5 (the R-3 tool — it needs only the foundation profile and stage a), G-13
(the owner's public-documentation re-read for Route A attribution), the owner's S0 inputs (secret creation
outside the repository, origin address resolution, the release commit choice, I-8/I-9), and G-8's
calendar-source decision. **Not before the cycle above:** any AWS, Terraform, image, registry, launch or
provider operation.

---

## 9. The verification-and-launch cycle — implemented offline, proposed, and what remains

**Status: an offline implementation and a proposed decision, not an authorization and not runtime
evidence.** Everything in this section was produced on synthetic fakes through the real modules,
validated by the repository gates, and — for the Terraform additions — `terraform validate` in a
task-owned external copy only. **Nothing was run against AWS**: no STS, ECS, EC2, SSM, Secrets Manager
or provider call, no image built, pulled or published, no Terraform plan or apply, no launch, no probe,
no Reachability Analyzer analysis. **Mocked results are not AWS verification.** The decision itself is
[ADR-0045](../decisions/ADR-0045-verification-entries-observation-build-and-launch-tool.md) —
**PROPOSED, NOT IN FORCE** while its pull request is open — and every disposition below that says
*proposed* carries no authority until that ADR is independently reviewed and merged. **(Since
satisfied: PR #104 merged 2026-09-14; ADR-0045 ACCEPTED / IN FORCE; §9.2's answers are decided. The
text of §9 stays as written on those days.)**

### 9.1 Implemented offline (code on `main` only after the pull request merges)

| Item | What exists | Held by |
|---|---|---|
| **G-1** — the verification entries | `TaskEntry.ACQUISITION_VERIFY` / `BUILD_VERIFY` (`…-acquire-verify`, `…-build-verify`), composing `run_task_bootstrap` and nothing after `RELEASED`; `TaskOutcome.VERIFIED_BOOTSTRAP`, exit **18**; `VerificationFactories` with no field for a secrets client, transport or S3 client; the compiled-configuration file's verification field set (origin addresses only); `CompiledTask` / `CompiledLaunch` admitting the verification family; the Dockerfile's `acquire-verify` and `build-verify` targets and entry executables; the entrypoint's `_SocketProbe` | `tests/unit/test_production_verification_entry.py` (39), the entry, compiled, receipt, generator, entrypoint and build-context suites |
| **G-1 / G-15** — the build probe and its verdict | `probe.py`: one TCP connect, port 443, 5 s, at most one attempt, to the smallest resolved address **only when every resolved address is inside the compiled set**; closed `ProbeResolution` / `ProbeResult`; `ProbeObservation` invariants; `isolation_verdict` — `FAILED` on `CONNECTED`, `INCONCLUSIVE` otherwise, `VERIFIED` only with a Reachability Analyzer corroboration that matches source and destination, found no path and names a blocking component; the receipt renders the observation and `isolation_verdict=NOT_DECIDED_BY_THE_TASK` | the same suite; `test_adr_0045_governance.py` holds the vocabularies to ADR-0045 |
| **G-7 (Route B)** — the observation build | an explicitly empty `AcceptedSchemas` admits nothing; `silver.normalize` collects every page's `schema_digest_of` before refusing `SCHEMA_UNSTABLE`; `SchemaObservation` (per dataset: sorted distinct digests, pages parsed / total; `complete` only when every page parsed); `BuildReport.schema_observation` only on `REFUSED_NORMALIZATION` with zero writes; receipt v2 (`kalpamani-task-receipt/v2`) carries `schema_observation` and `probe` blocks under closed admission rules; a static test that no production module writes an observation into an accepted set | `tests/unit/test_production_schema_observation.py` (18), through the real build entry over a store the real acquisition path populated |
| **G-2 / G-3** — the owner-side launch tool | `scripts/production_launch.py` + `launch_records.py`: the owner ledger, launch-inputs, authorization, launch-record and evidence contracts parsed closed; acquisition input v2 / build input v1 materialized with `plan_digest_for`, `spent_identities_block` (the ledger's **whole** identity set) and `ledger_digest`, each re-parsed under the task's own contract; `CompiledLaunch` compiled per actor and kind; configuration equivalence (`EQUIVALENT` / `CODE_DIFFERS` / `ORIGIN_DIFFERS` / `ENTRY_MISMATCH` / `UNREADABLE`) and the registered-file check before a verification launch; `human_bootstrap` under the human and launcher profiles, then `launch_authorized_run` on four clients built **only** inside the authorized branch under pinned profiles with one attempt and finite timeouts; a provisional `EXIT_CODE_ONLY` ledger row per launch attempt (an identity is consumed by its authorization, task or no task); `--complete-row` verifying the hand-read receipt line against the launch record; refusal by default, refused spellings, containment under the private root, no identifier in output | `tests/unit/test_production_launch_records.py` (77) and `test_production_launch_script.py` (37), every client a fake |
| **Terraform** | `production_acquire_verify` / `production_build_verify` task definitions (same roles, placement, `user`, read-only root, `/work`), gated on stage `a`/`b` **and** their digest keys (`acquisition_verify`, `build_verify`; any other key refused); each launcher's `RunTask` resource is `concat([production revision], verification revisions)`; three new `terraform test` runs (no verification digest → no family; both → both families, same roles, no assignment; unknown key → refused) | `test_production_infrastructure.py` (63) with mutation controls; in a task-owned external copy under the pinned `hashicorp/aws` 6.62.0: `terraform fmt -check`, `terraform init -backend=false`, `terraform validate` (valid) and `terraform test -test-directory` with the **mock** provider — **14 of 14 runs pass**; no plan, no apply, no backend, no credential, no account (§9.4) |
| Vocabulary | `ActorConstants.verification_task_family`, `ActorConstants.launcher_profile` (`kalpamani-production-acquisition-launcher`, `kalpamani-research-build-launcher`), `is_known_family`; `LEDGER_OUTCOME_VERIFIED` | `test_adr_0045_governance.py` |

### 9.2 Proposed — decided only by ADR-0045's acceptance

| Question | Proposed answer (ADR-0045) |
|---|---|
| four closed entries (amends ADR-0043 §2) | §2 — verification entries terminate at the barrier with `VERIFIED_BOOTSTRAP` (18) |
| the probe's rule and the R-2 verdict (G-15; amends ADR-0036 §3) | §3 — one connect, closed observation; the verdict is the tool's, not the task's; **Reachability Analyzer is the only admitted corroboration**; Flow Logs are not; the analyzer's IAM delta is recorded as an owner input (D-14) and **not granted** |
| Route B as evidence (G-7; amends ADR-0044 §4 and the build's output rule) | §4 — an observed digest is evidence for owner review; promotion is an explicit owner act |
| the verification families and the launcher resource (amends ADR-0036 §2.9) | §5 — one family per actor; exactly one more `RunTask` resource per launcher; no assignment change |
| the launch tool's records and the identity rule (amends ADR-0036 §2.6, §2.12) | §6 — `verify-` reserved; an identity in the ledger is consumed for both kinds; no `RunTask` retry; a row is provisional until receipt-verified |
| re-verification (G-12) | §7 — R-1/R-2 are repeated on a new commit or a new verification image digest; a stage-b production digest rotation needs neither and touches no assignment |

### 9.3 Remaining runtime evidence (unchanged by this cycle)

Every U row of §3.3, every L3 cell of §4.3, S1–S10 in full. The verification entries have never run as
a task; the launch tool has never constructed a real client; the probe adapter has never opened a
socket; the observation build has never read a real locator. The first authorized run of each is the
first evidence of any of them, under its own written authorization.

### 9.4 What could not be completed here, stated

- **The external-copy Terraform validation ran, on the fifth attempt.** Four `terraform init
  -backend=false` attempts earlier in the cycle could not download the pinned `hashicorp/aws` 6.62.0
  provider (connection resets and TLS handshake timeouts against the registry); the fifth succeeded,
  and `terraform validate` (valid) and `terraform test` with the **mock** provider (14 of 14 runs)
  then passed in the task-owned external copy. One assertion the cycle first wrote compared the
  verification and production task definitions' `task_role_arn` — a provider-computed value that is
  **unknown at plan** — and was replaced by plan-evaluable assertions (the closed family names and the
  Fargate shape); the role identity is held by the structural Python guard as the declared expression.
  **A `terraform test` plan against a mock provider is a check of the configuration's own logic, not
  of AWS**: no credential was read, no account was contacted, and no resource exists before or after.
  The repository directory was never initialized. **No plan and no apply were run.**
- **G-4 (the production human-binding materializer)** is not built; the launch tool loads the two
  files through the accepted reader and would refuse without them.
- **G-5, G-6, G-8, G-9, G-10, G-11, G-13** are untouched.

### 9.5 Remaining owner inputs added by this cycle

D-14 (the Reachability Analyzer permission delta and its principal), D-15 (one authorization record
per launch), V-6's two verification digests, V-13's ledger under the private root, V-16's launch-inputs
record, V-17's two launcher profiles, V-18's launch records — all in
[`production-owner-inputs.md`](production-owner-inputs.md).

### 9.6 Deferred, and kept deferred

**G-14** (the bucket-policy transition procedure) is neither defined nor authorized by this cycle, and
nothing in it depends on changing the deployed bucket policy. The receipt collector and its
`logs:GetLogEvents` delta (ADR-0044 §5) stay deferred; the ledger row is completed from a hand-read
line. The R-3 tool, the cell runner and the human-binding materializer stay separate cycles.
**(That separate cycle has since run — §10.)**

### 9.7 The PR #104 correction cycle — four review findings, reproduced and corrected

The independent review of PR #104 returned four findings against §9.1's launch tool and probe. Each
was **reproduced through the real modules on fakes** before any change (the observations are in the
export's `correction-1/before/`), corrected, and re-run (`correction-1/after/`). The dispositions are
recorded in [`production-readiness-dispositions.md`](production-readiness-dispositions.md) §F-4 … §F-7
and in ADR-0045 §10; nothing below weakens a proposed contract, and nothing runs against AWS.

| Finding | Reproduced (observed) | Correction |
|---|---|---|
| **F-4** identity consumption came after external mutation; direct ledger writes; colliding record names | an interruption after `RunTask` left no ledger row and the next attempt launched the same identity (`RunTask` 1 → 2); two launches in one second overwrote one evidence file; `write_bytes` on the ledger | `launch_store.py`: an exclusive `O_CREAT \| O_EXCL` reservation bound to the specification digest, created under the ledger lock **before any bootstrap or client**, never deleted; every ledger write under the lock through an atomic temp-and-`os.replace` that refuses a changed ledger; record names with the instant and eight random hex digits, exclusive, retried never overwritten; `--recover` writes the `HALTED` row for an interrupted identity and launches nothing; every launch refuses while an unreconciled reservation exists; a foreign lock refuses and is never removed. Durability limits (fsync, no directory sync on Windows, `os.replace` share modes) stated in the module |
| **F-5** the authorization bound only actor, kind, identity and validity | a changed slice launched under an unchanged authorization (exit 0) | the launch specification (`kalpamani-launch-specification/v1`): workload (slice + plan digest, or selected runs with their ledger evidence), registered target (revision, image, configuration, commit, generation-record reference, task-definition evidence), placement, gate-evidence references (R-3 digest, applicable to production only); preparation writes it and prints its digest, the authorization names the digest, execution rebuilds and compares before any client, and revalidates freshness before the first mutation; timestamps and the spent set are excluded so ledger growth does not invalidate an authorization while any bound change does; a gate-evidence reference is not proof of approval |
| **F-6** only the verification file was bound to a registered target; no task-definition comparison | an unrelated but valid production file launched a verification (exit 0); the actor block carried no task-definition evidence | every file bound to its own registered target (digest, commit, entry, family) — production, verification, and the acquisition file behind a build pair; owner-transcribed task-definition evidence per target compared field by field (roles, cpu, memory, network mode, platform, `user`, read-only root, `/work` tmpfs must agree; family, revision, command, image differ by design); closed verdicts incl. `TARGET_MISMATCH`, `TASK_DEFINITION_DIFFERS`, `EVIDENCE_MISSING`; `EQUIVALENT` stated as configuration equivalence, never runtime proof; **live read-back needs `ecs:DescribeTaskDefinition`, which the launcher sets do not hold — recorded, not added** |
| **F-7** the verdict accepted supplied match booleans and no analysis identity; the receipt named no destination; the tool never recorded a verdict | `VERIFIED` from two `True` values; the probe block had no destination; `isolation_verdict` absent from the tool | the receipt binds the selected destination under a keyed digest (`destination_binding_digest(input_digest, address, 443)`), recovered by the tool from the compiled set and never inferred from a later resolution; a closed `kalpamani-reachability-evidence/v1` transcription (documented `NetworkInsightsAnalysis` / `NetworkInsightsPath` fields, verified against the public API references); every comparison derived — status, source interface, destination/port/protocol, `startDate` inside the task's window, path found, the admitted explanation codes on their component kinds, placement; closed reasons; `CONNECTED` always fails; `--isolation-verdict` records the verdict beside the launch record; `VERIFIED` unreachable without evidence, and the tool collects none |

| **F-8** the reservation's location depended on `--records-dir` (second cycle) | an interrupted attempt retried with the same ledger, identity and authorization and another records directory launched again (exit 0, `RunTask` 1 → 2); `--recover` from another directory found nothing (exit 3) | reservations and the lock anchored to the ledger's canonical path (`<ledger>.reservations/`, `<ledger>.lock`); the reservation carries the whole specification and recovery's row comes from it; the records directory is an evidence destination only; first-revision reservations under a supplied records directory refuse (`refused_legacy_reservations`) until the owner moves them by hand — the tool reads, moves and deletes none. After: exit 12 before any client from any directory, `RunTask` stays 1; recovery from another directory writes the `HALTED` row; the identity stays consumed everywhere |
| **F-9** the verdict took its security groups from a freshly supplied launch-inputs file (second cycle) | a launch-inputs file listing an extra group turned `COMPONENT_OUTSIDE_PLACEMENT` into `VERIFIED` with the record, receipt and ledger unchanged | the launch record carries the verified security groups and the specification digest; completion and the verdict bind the record to its reservation (same digest, actor, kind, entry, target, acquisition workload, subnet, groups) and to the identity's ledger row; the verdict's placement is the record's, cross-checked against the reservation's specification; a supplied launch-inputs file is verified against the recorded specification and refuses on mismatch. After: exit 3, no verdict written; untampered evidence still verifies; a widened record or reservation, a missing reservation or a missing row each refuses. The trust boundary is the owner's private root, not a stored digest |

**Tests added or rewritten:** `test_production_launch_store.py` (32, incl. eight competing threads
reserving once, reservation location and equivalent ledger spellings, legacy refusal),
`test_production_isolation_verdict.py` (44), `test_production_launch_script.py` (83; reservation,
interruption after reservation and after `RunTask`, evidence and ledger write failures, concurrent
distinct identities, recovery refusal, a different records directory after an interruption, competing
directories, recovery from another directory, legacy reservations, each bound authorization category,
each equivalence substitution, each verdict reason, substituted launch inputs and unbound records),
`test_production_launch_records.py` (specification and its parser, task-definition evidence, bound
equivalence, the launch record's placement and specification digest).

## 10. The verification-tooling cycle — G-4, G-5, G-6 implemented offline; ADR-0046 (accepted on the merge of PR #105, §10.5); ADR-0045 synchronized

**Status: offline owner-side tooling over accepted contracts, proposed in its own pull request; not an
authorization and not runtime evidence.** Baseline `main` at `af20f36acbe8a3006830762fbad5cb01d1e9b38b` (the PR #104 merge). Everything
here was produced on synthetic temporary files through the real modules with counting fakes for every
client. **Nothing was run against AWS**: no STS, S3, ECS, EC2 or SSM call, no image, no Terraform plan
or apply, no launch, no probe, no analysis, no private input read. **Mocked results are not AWS
verification.** The decision is [ADR-0046](../decisions/ADR-0046-verification-tooling-materializer-r3-tool-and-cell-runner.md)
— **PROPOSED, NOT IN FORCE** while its pull request was open (true of those days, and not rewritten);
**ACCEPTED / IN FORCE since PR #105 merged** (§10.5).

### 10.1 Implemented offline

| Gap | Tool | Composes | Held by |
|---|---|---|---|
| **G-4** — the production human-binding materializer (S7) | `scripts/production_human_binding_materialize.py` | the ADR-0024 environment-binding loader against the governed local account; `parse_production_runtime_binding` before a byte is written; the one private-artifact writer (exclusive create, owner-only descriptor, read-back); `load_human_runtime_binding` with the actor's own variable, and removal on a refused reload | `test_production_human_binding_materialize.py` (19): both actors, the other actor's loader refuses the document, a real synthetic private root round trip, occupied destination refused, every refusal writes nothing, the two authorizations distinct and unforgeable, no private value in any output; no SDK import |
| **G-5** — the R-3 tool (S5) | `scripts/production_r3_verification.py` + `r3_verification.py` | the foundation identity gate (`kalpamani-foundation`, PASS/FAIL); the environment binding; the nine accepted rows and the ten-operation failure-path cleanup on an injected client; row 9's `404` the only confirmation of the positive control's absence (row 8's `204` acknowledges the delete); `kalpamani-r3-verification-record/v1` written by the private-artifact writer; `--check-record` for old evidence; the S3 client at `total_max_attempts: 1` | `test_production_r3_verification.py` (97): every response class; the accepted table; a bucket under the policy verifies with nine operations and no residue; each deviation class halts and does not verify; `200`s on rows 2/4/5/6 cleaned and confirmed; row 9 answering `200`, a timeout, an access denial or a network failure after row 8's `204` cleaned up within the budget with the failed row preserved — `NOT_VERIFIED` on a later confirmation, `NOT_VERIFIED_CLEANUP_UNRESOLVED` with residue otherwise, never `VERIFIED`; an abort repeated at most once; unresolved cleanup names residue; the budget never exceeded; a record contradicting its rows refused; old evidence attests to nothing changed; the tool's default performs nothing; every refusal stops before any S3 operation; the SDK named once; the real adapter under invented static credentials with its HTTP session replaced by a counting fake: one transport attempt on `SlowDown`, `500`, timeouts and connection failures, every class in the table, the conditional-copy header present only on the conditional call, no profile-based session |
| **G-6** — the verification cell runner (S9; S8 enumerated) | `scripts/production_verification_cells.py` + `verification_cells.py` | the launch tool (prepare / execute / complete / verdict), its ledger-anchored store, the receipt validator, the verdict path, the R-3 record and the launch inputs; the prepared-cells document (`kalpamani-verification-cells/v1`) beside the ledger under the ledger lock; a matrix **derived** from records, a receipt-verified row passing only through its reservation, its launch record — bound under the launch tool's own shared rule `launch_store.bind_record` (specification, workload, target, verified placement) — and the registration now in force (`HISTORICAL` otherwise, `UNBOUND` when the chain is missing, malformed or substituted, a placement or workload contradiction included); verdict records parsed through the closed `kalpamani-isolation-verdict/v1` contract and resolved deterministically | `test_production_verification_cells.py` (65): the enumeration; R-3 gates every dependant; the R-3 cell passes only with attesting `VERIFIED` evidence the inputs name; runtime states from the ledger and reservations (prepared, interrupted, launched-without-receipt, refused, failed); a bound current chain passes for both actors; a reservation for another specification, a missing reservation or launch record, a substituted record (digest, image, commit, interface) is `UNBOUND`; a record whose only change is its subnet, its security groups, its slice or its plan digest is `UNBOUND` (`PLACEMENT_MISMATCH` / `WORKLOAD_MISMATCH`) with the verdict cell `BLOCKED`, a reordered group set still binds, and the same change through the runner on real files reads `UNBOUND`; `test_production_launch_script.py` holds `bind_record` per class and `--complete-row` refusing a placement-only change; a changed registered image, commit, subnet or platform version is `HISTORICAL` and blocks the verdict cell; the minimal forged verdict shape, ten contradictory or incomplete documents and a corroboration over `CONNECTED` refused; malformed or unreadable verdict evidence reported as `UNBOUND`; `FAILED` dominates in either order; `NO_CORROBORATION` then bound corroboration is `PASSED`, stale or wrong-source evidence alone stays `INCONCLUSIVE`, a modelled path or a differing probe block conflicts to `UNBOUND`; the aggregate `VERIFIED` only when every cell passed; the runner's default constructs nothing; refused flags; prepare records the cell; execute needs the flag, the cell `PREPARED`, every prerequisite `PASSED` and an authorization naming the prepared digest — then the launch tool once, never twice; an interrupted cell reconciled and never relaunched; a held lock refuses; completion then verdict on a verified build launch, wrong-interface and stale transcriptions leaving it `INCONCLUSIVE` and a bound corroboration for the same launch resolving it to `PASSED` with no further `RunTask` and no client constructed; a passed verdict cell not re-evaluated |

### 10.2 Proposed — decided only by ADR-0046's acceptance (since accepted, §10.5)

The three contracts (§3 — the verdict document the launch tool already writes, now read closed), the cleanup and row-9 confirmation readings (§2.2), the matrix, its statuses and its evidence chain (§2.3), and the
deferral of the negative R-1 cells (§4): **no accepted launch mode withholds or mis-names a release**,
so `R1-*-NO-RELEASE` and `R1-*-RELEASE-MISMATCH` stay `BLOCKED`, and the aggregate cannot read
`VERIFIED` until the owner decides that mode in a later ADR. R-4 … R-9 are enumerated with their
must-succeed / must-be-refused text and stay owner-run (S8); a cell decided by simulation only is
recorded simulated, never verified.

### 10.3 ADR-0045 synchronized

PR #104 merged; ADR-0045 carries its post-merge note; the status rows in `CLAUDE.md` / `README.md`,
this record, the dispositions, the owner-input checklist, the image-build procedure and the examples
README say *accepted* where they said *proposed* — with the days it was proposed preserved as written.
Acceptance of ADR-0045 implied no analyzer permission, no runtime verification, no image and no
execution.

### 10.4 What remains — the consolidated owner checklist

[`production-owner-inputs.md`](production-owner-inputs.md) §D separates values the owner must supply,
evidence that can only exist after an earlier runtime step, permissions still needing a decision, and
the code gaps left after this cycle (the withheld-release launch mode for the negative R-1 cells; the
R-4 … R-9 orchestration; the receipt collector; G-14) — as written on that day; §11 and the refreshed
§D record what the coverage cycle closed and what it left.

### 10.5 ADR-0046 accepted

PR #105 merged **2026-09-14T20:37:38Z** (merge commit `5174dcf290b4837d38af8ce4a4b975c6557e482e`, approved head `c4436648d90d39baa3769e990887e6f0f239df40` after two
independently reviewed correction cycles, merge tree identical to the reviewed head tree), so
**ADR-0046 is ACCEPTED / IN FORCE** within its own merge-effectiveness clause — the tooling, its
contracts, the verdict-document contract and the shared reservation-to-record rule its corrections
added, and the §4 deferral. Its post-merge note, the status rows in `CLAUDE.md` / `README.md`, this
record, the dispositions, the owner-input checklist, the tools' docstrings, the SDK guards and the
docs-audit registry say *accepted* where they said *proposed*, with the days it was proposed
preserved as written. **Acceptance authorized no R-3 session, no materialization, no launch, no run,
no probe, no analysis, no Terraform plan or apply and no IAM change.**

## 11. The coverage cycle — negative R-1 launches and the R-4 … R-9 subcells implemented offline; ADR-0047 (accepted on the merge of PR #106)

*ADR-0047 has since been accepted: PR #106 merged 2026-09-15T00:26:19Z (merge commit
`167f1564378cfb96759093b43fbde5443f6c56b6`). The sections below record the cycle and its corrections
as they were written, and §11.2's "decided only by acceptance" is decided; §12 records the mechanisms
cycle that followed.*

**Status: offline code over accepted contracts, proposed in its own pull request; not an
authorization and not runtime evidence.** Baseline `main` at `5174dcf290b4837d38af8ce4a4b975c6557e482e` (the PR #105 merge).
Everything here was produced on synthetic temporary files through the real modules with counting
fakes for every client. **Nothing was run against AWS**: no STS, S3, ECS, EC2, SSM or Secrets Manager
call, no RunTask, no image, no Terraform plan or apply, no launch, no probe, no analysis, no private
input read. **Mocked results are not AWS verification.** The decision is
[ADR-0047](../decisions/ADR-0047-negative-verification-launches-and-permission-subcells.md) —
**PROPOSED, NOT IN FORCE** while its pull request is open.

### 11.1 Implemented offline

| Item | Code | Composes | Held by |
|---|---|---|---|
| **the negative R-1 cells** (S9; ADR-0036 §3 R-1 *must be refused*) | `ReleaseMode` on `launch_records.LaunchSpecification` / `LaunchRecord` (with the launcher's `observed_exit_code`); `launcher.launch_authorized_run(release_mode=)`; `release.mismatched_task_arn`; `launch_store.bind_record` (`MODE_MISMATCH`); `production_launch.py --release-mode`; `verification_cells.NegativeLaunchEvidence` and `_negative_state`; the cell runner's prepare / execute / complete for the negative cells | the accepted launcher, reservation store, receipt validator, shared binding rule and cell runner — one changed step, no retry in any mode | `test_production_runtime_launcher.py` (withheld writes no release and still observes and cleans up; mismatched writes a release the launched task can only refuse and the derived ARN verifies; a negative mode is a verification launch's alone; the ordinary mode unchanged; the observed exit code is the one terminal code or none); `test_production_verification_cells.py` (a bound expected refusal passes each of the four cells; unexpected success, another refusal, a released or operating task, a halt is FAILED; missing, conflicting, malformed, unobserved, cross-mode or unbound evidence is UNBOUND; a changed registration is HISTORICAL; a positive cell prepared under a negative mode does not pass; the contract is closed; end to end through the runner on fakes — prepare, execute under WITHHELD with no release written and one task observed to exit 15, complete with the refused receipt, PASSED, the wrong receipt FAILED, never twice); `test_production_launch_script.py` and `test_production_launch_records.py` (the ordinary paths unchanged) |
| **the R-4 … R-9 subcells** (S8) | `permission_cells.py` (the 98-subcell catalogue traced to ADR-0036 §3, the targets contract, the statement and authorization contracts, the engine, the attempt / record / cleanup contracts joined by identity, the derivation) + `scripts/production_permission_cells.py` (plan / `--check-record` / `--prepare-subcell` / `--execute-subcell --authorization` / `--cleanup`) + `LaunchStore.consume` + the cell runner's permission derivation, subcell lines and `--recover-negative-evidence` | the accepted R-3 classifier and control principal, the human bootstrap and identity gates, the ADR-0037 key builders, the launch store, the launch-inputs registration | `test_production_permission_cells.py` (53): the catalogue (every subcell traced; task roles and the deletion role BLOCKED with their dependency, a human twin never evidence for a task role; the launchers' positives evidenced by R-1 only; prerequisites name creating subcells); targets (synthetic keys exactly in their namespaces; derived revision/family/cluster never the registered ones; the private targets document closed); decisions (twelve classes × two expectations; a delete matches 204 only); the engine (one operation, the created key on success, an inverted write recorded for cleanup, an unexpected launch stopped at once with the stop acknowledged or not, a transport failure undecided, the record contract refusing ten contradictions, cleanup confirmed or residue within the budget); derivation (an inversion never disappears under the same binding, historical under another; undecided; interrupted attempts; unverified identity; prerequisites in order; cleanup required; R-1-evidenced and blocked subcells); the matrix (R-7 and R-9 pass only with every subcell matched under the binding, a stale record HISTORICAL, R-4 blocked however its human subcells read, an inverted subcell fails its cell and the aggregate, R-6 positives follow the R-1 cells); the tool (the plan constructs nothing; refused options; refusals before any client on automation, profile, identity, layer, binding, targets and declarations; the attempt written before the operation; inverted and undecided exits; cleanup under the control principal over every recorded and unanswered key, residue reported, wrong flag or profile refused); the real boto3 adapter at the transport (one attempt per operation, the conditional header, `RunTask` answers carrying the task ARN and failure entries deciding nothing) |

### 11.1a Correction 1 on review (PR #106)

Five source-review findings were reproduced on synthetic inputs against the reviewed head
`c529c3fde9953f49d17085f42b454c29288bb891` and corrected in the same pull request: per-subcell
authorization bound to a prepared statement (principal, operation, exact resolved target, binding,
targets document, bound prerequisite records) and **consumed durably beside the ledger before the
operation** — repeated, interrupted or from another records directory, never executed again, a changed
targets document invalidating it; dependent reads taking the **exact bucket and key** the bound
prerequisite record created, enforced at preparation and execution, the object deferred by the
cleanup until the prepared dependent has run; **possibly committed writes and launches** (timeouts,
network failures, ambiguous statuses) recorded and settled by **attempt identity**, a later result
never answering an earlier attempt, a cleanup recorded before a record never settling it, residue and
the original inconclusive result preserved; ECS accounting — every returned task preserved and
stopped even beside failure entries, termination confirmed only by the cleanup's `DescribeTasks`
(never by a stop acknowledgement), ambiguous launches listed by the request's `startedBy` tag and
never retried, the request carrying the registered placement, the two `ExecuteCommand` subcells
BLOCKED on a running task (56 / 6 / 36); and `--recover-negative-evidence`, the offline recovery of a
negative cell's missing evidence after an interruption between `--complete-row` and the evidence
write, re-verifying the reservation, the launch record and the receipt, repeatable, refusing
contradictions, never relaunching. Validated by the full suite, `ruff`, `mypy` and the docs audit on
the corrected head; before/after results in the evidence export.

### 11.1b Correction 2 on review (PR #106)

Two findings reproduced on synthetic files through the real parsers, runner and cleanup engine
against `984969f342ea8d8f912a2416b7a3e9372858ce12` and corrected: **complete evidence binding** — the
permission binding now covers the owner's targets document; the cell runner holds every result to a
`PermissionContext` built by the permission tool's own constructor (a missing environment binding,
declaration, registration or targets document is no context: `UNBOUND`, never a preserved `PASSED`);
one validator (`bind_result`) binds a result only through its attempt, its statement, its bound
prerequisites, the exact target recomputed now and the consumed authorization
(`kalpamani-permission-consumption/v1`), and admits a cleanup only against that exact attempt and
object or launch — used by execution prerequisites, matrix derivation and cleanup admission alike; the
test that supplied records alone and expected R-7 `PASSED` is replaced by one that builds every chain
through the tool and withholds, substitutes and contradicts each component through the public runner.
**Ambiguous ECS launch settlement** — an empty `ListTasks` no longer settles an ambiguous launch:
discovery is bounded (`RUNNING` and `STOPPED`, three pages each) and explicit, `undiscovered`, `failed`
and `incomplete` are residue, every known task is preserved and described, termination evidence alone
settles, exhaustion is never proof of absence, no `RunTask` is ever sent; the control principal's
`ecs:ListTasks` / `DescribeTasks` / `StopTask` are recorded as deferred, not granted.

### 11.1c Correction 3 on review (PR #106)

Two findings reproduced on synthetic files against `33d7c41c75af242e25a22ae2af8ed633447d27a3` and
corrected: **valid ECS discovery requests** — the adapter's `ListTasks` had combined `startedBy` with
`desiredStatus`, which the documented contract refuses (`startedBy` is the only filter when used);
discovery now lists by `startedBy` alone, cluster, `maxResults` and a returned `nextToken`, for at
most three pages, preserving exact launch attribution, the page bound and the `undiscovered` /
`failed` / `incomplete` residue, adding no filter and no permission, and the request body is asserted
at the real adapter's intercepted transport for every listing (no `RunTask`): a fake `200` alone
validates no request. The stated limitation: a task that stopped before discovery and aged out of the
listing is not discoverable this way, and its launch stays `CLEANUP_UNRESOLVED` (ADR-0047 §3.5, §5).
**Cleanup identity** — a cleanup record whose `identity_verified` is `false` settles nothing: one
admissibility rule (same binding, no earlier than the record, identity verified) is applied by the
matrix derivation, the tool's prerequisite availability and its cleanup suppression alike; the
unverified pass is preserved and reported, and a verified pass settles the same object or launch
again — held for the object and the task case through the public runner beside verified controls.
Validated by the focused regressions, the full suite, `ruff`, `mypy` and the docs audit on the
corrected head; results and limitations in the evidence export.

### 11.2 Proposed — decided only by ADR-0047's acceptance

The release-mode field on the specification and the record (ADR-0045's contracts, narrowly amended —
ADR-0047 §6.1), the negative-evidence and permission contracts (§6.2), the reading of ADR-0036 R-4's
cleanup clause (§6.3), and the two mechanisms named as required and not implemented (§5): a
**task-side permission probe entry** for the 32 task-role subcells, and an **execution path for the
deletion role** for R-8. Until they exist, R-4, R-5 and R-8 read `BLOCKED` with the dependency named,
and the aggregate cannot read `VERIFIED`. Acceptance would grant no permission and authorize no
execution.

*§11.2 is history: ADR-0047's acceptance decided the release-mode field, the contracts and the cleanup
wording; the two mechanisms are delivered (the probe entry, the held task) or designed and not opened
(the deletion path) by ADR-0048, accepted on the merge of PR #107 — §12; the deletion decision is presented as ADR-0049 D-1 (accepted on the merge of PR #108) — §13, and made concrete by ADR-0050 (accepted on the merge of PR #109; D-1 still not taken) — §14.*

### 11.3 What remains — the refreshed owner checklist

[`production-owner-inputs.md`](production-owner-inputs.md) §D now separates the values required before
packaging, the decisions or permissions required before cloud verification, and the evidence
obtainable only after the relevant runtime step.

## 12. The mechanisms cycle — permission-probe tasks and the held ExecuteCommand check implemented offline; ADR-0048 (accepted on the merge of PR #107)

*ADR-0048 is ACCEPTED / IN FORCE: PR #107 merged 2026-09-15T10:22:22Z, merge commit `c0566574c41bc31b7144fafe919078a213982143`, approved head `86fe67b18cb6a213559b418d5312785972b675eb`, base `167f1564378cfb96759093b43fbde5443f6c56b6`, merge tree identical to the reviewed head tree. While the pull request was open it was proposed, which is how §12.1–§12.3 read and is not rewritten. Acceptance authorized no execution and granted no permission; nothing below has run.*

### 12.1 Implemented offline (never run)

- **Permission-probe entries** `kalpamani-production-acquire-probe` / `kalpamani-research-build-probe`
  (`permission_probe_entry.py`): the accepted bootstrap over the **probe input**
  (`kalpamani-permission-probe-input/v1`, `permission_probe.py` — the subcell, the bound statement and
  attempt digests, the stamp, the exact resolved target, a bounded hold), then exactly one catalogued
  operation under the task role through `permission_cells.issue_subcell` over the one service the
  operation names (`permission_client.single_service_client`), or a hold; `PROBE_MATCHED` /
  `PROBE_INVERTED` / `PROBE_UNDECIDED` / `PROBE_HELD` (41–44); the receipt's closed `permission`
  block (`kalpamani-task-receipt/v3`), never a value, key, name or ARN.
- **The workstation tool**: a task-layer subcell is prepared and authorized as before, its authorization
  consumed and its attempt written, then launched through the accepted launch sequence under the
  actor's human and launcher profiles (a probe revision from the registration's optional
  `permission_probe` target, `startedBy` the session's tag, no override), recorded as a launch record
  and an owner-ledger row (`permission-probe`, `PROBED`), and completed only from the hand-read
  receipt (`--complete-subcell --receipt-lines`) verified against that launch record —
  `identity_verified` exactly when the probe's bootstrap released; the probe task is a started task the
  cleanup discovers by the tag and confirms `STOPPED`. Layers `L3_TASK` (32) and `L3_HELD_TASK` (2);
  status `AWAITING_RECEIPT` (cell `INCONCLUSIVE`) between launch and completion.
- **The held `ExecuteCommand` check**: the launcher's one `while_running` check against its own held
  probe task, with the documented request (`interactive: true` — the earlier `interactive=False` was an
  invalid request a fake 200 had accepted); an unexpected session is INVERTED and the task stopped at
  once; the security property (no `enableExecuteCommand`, the launcher's deny) is unchanged.
- **Classification**: `AccessDeniedException` / `UnauthorizedOperation` are denials for every issuing
  service (they had read as `AMBIGUOUS`); every unknown answer still decides nothing.
- **Declarations**: the two probe families and one more exact `ecs:RunTask` resource per launcher,
  gated like the verification families (`acquisition_probe`, `build_probe` digest keys), validated in
  an external copy under the pinned provider (`init`, `validate`, 15 mock-provider runs) — declared,
  not planned, not applied.

### 12.1a Correction cycle 1 (review of the pull request; ADR-0048 §8; the ADR stayed PROPOSED until the merge)

Three defects the review found in 12.1 were reproduced through the real tool, launcher, store and
runner on synthetic files, then corrected:

- **Probe interruption and recovery.** The probe identity is now **reserved beside the ledger before
  `RunTask`** with the whole probe launch specification (target, placement, and a workload naming the
  subcell, statement, attempt, stamp, `startedBy` tag, hold and input digest); the launch record names
  that specification and binds to the reservation. An interruption after `RunTask` and before any
  launch publication leaves the authorization consumed and the started task attributable from the
  reservation alone: the cleanup discovers it on the reservation's cluster by the reservation's tag
  (bounded; an unresolved discovery stays explicit), `--recover-probe-launch` records the ledger row
  offline (from a bound launch record, else `HALTED`), every other probe launch refuses until it does,
  and `RunTask` is never retried. A completion interrupted between its record, its receipt evidence and
  the ledger is **repeatable** with the same receipt (writes exactly what is missing; a whole completion
  changes nothing and says so); nothing is relaunched and no evidence is removed.
- **Complete probe evidence binding.** The one validator now requires of every probe-layer result its
  reservation-attributed launch (exactly one record, bound; workload, actor, identity, entry, hold and
  started task exact), its owner-ledger row (`RECEIPT_VERIFIED`, the receipt's disposition, launched
  when the record says), and its **receipt evidence** (`kalpamani-probe-receipt-evidence/v1`, kept at
  completion and **re-verified on every read** against the launch record's expectation; outcome = the
  observed terminal exit; the permission block = the record's observation for a task subcell; a
  released, held probe for a held subcell). Missing, substituted, conflicting or duplicate evidence
  reads `UNBOUND` (a missing receipt `AWAITING_RECEIPT`), never `PASSED`, and no candidate is ever
  chosen among several — tested through the public runner beside a complete valid control.
- **The held-task precondition.** The launcher admits its one `ExecuteCommand` only on a **fresh
  `RUNNING` description** of exactly the task it started, on the registered revision and image (5 s
  polls, 120 s ceiling, inside the probe's hold), kept as `kalpamani-held-task-evidence/v1`; a task
  stopped first, not running at the ceiling, undescribable or mismatching is **not checked** and the
  record decides nothing (`UNDECIDED`, the evidence naming which). The held subcell completes from the
  probe's own receipt, which must attest a released, held probe. What the precondition proves (the
  probe was available as a target) and what stays an evaluation-order limitation (IAM before
  `enableExecuteCommand`; the managed agent's connection) are stated in ADR-0048 §3.

### 12.2 Designed and not opened — the deletion rehearsal path

ADR-0048 §4 designs a rehearsal family under the deletion role, a rehearsal launcher passing exactly
that role to ECS (no human assumption), the role's two bootstrap parameters, and three R-8 subcells
over the exact synthetic object the bound R-4 human record established, confirmed removed by the
control principal's cleanup. It reverses ADR-0007's verified inert property and is **a governance
decision not taken here**: R-8 stays BLOCKED with that dependency named.

### 12.3 Counts, and what has not moved

98 subcells: 56 `L3_RUNTIME` / 6 `L3_BY_R1` / 32 `L3_TASK` / 2 `L3_HELD_TASK` / 2 `BLOCKED`. Nothing has
been executed; no probe has been launched; no image exists; every owner value stays MISSING; the
receipt collector (ADR-0044 §5) and the G-14 transition stay deferred and were not reopened. One
limitation is stated rather than resolved: whether ECS authorizes the caller before validating a
task's `enableExecuteCommand` state is not established offline — if not, the held check reads
`UNDECIDED`, never a verdict it did not obtain.

## 13. The collection-and-rehearsal cycle — the receipt collector implemented offline; the deletion rehearsal implemented offline and CLOSED; ADR-0049 (accepted on the merge of PR #108)

*Written while PR #108 was open, when ADR-0049 was proposed; that is how the paragraphs below read and they are not rewritten. PR #108 merged 2026-09-15T13:53:41Z (merge commit `82cae1ebfcc99dbbc53f67e534e4d78ffb914d4a`, approved head `9625e241db01b2996fbf9f63814ba3a916a3def7`, merge tree identical to the reviewed head tree), so ADR-0049 is ACCEPTED / IN FORCE; acceptance decided D-1 in neither direction, authorized no execution and granted no permission. §14 records the cycle that followed.*

### 13.1 Implemented offline (never run)

- **The receipt collector** (`receipt_collector.py`, ADR-0049 §2): the stream of one launch
  derived from the bound launch record's task id and the **registered** `log_destination` block of the
  task-definition evidence (one optional block; a registration without it refuses the collection; a
  block for another entry refuses; no caller-supplied stream is ever read); `GetLogEvents` from the head
  with the forward token in 16-page passes — **40 requests, 20,000
  events, 300 s elapsed, each checked before a request is issued; 15 s polls; effective SDK retries
  zero** (one attempt in total, finite timeouts, the workstation client configuration; a request in
  flight is the one limit the collector cannot cut, and the record's `elapsed_ms` says so); **a
  complete scan and only a complete scan establishes one line** (the end token observed, one poll
  interval, a re-read delivering nothing new closes the observation window the record carries), the
  candidate **decoded and verified against the launch record before anything of it is kept**; closed
  outcomes that are never receipt verdicts (`COLLECTED`, `RECEIPT_REJECTED` — closed defect and byte
  count, never the text — `SCAN_INCOMPLETE`, `NO_RECEIPT_WITHIN_BUDGET`, `STREAM_NOT_FOUND_WITHIN_BUDGET`,
  `CONTRADICTORY_RECEIPTS`, `DENIED`, `THROTTLED`, `FAILED`); a closed collection record
  (`kalpamani-receipt-collection/v1`, one parser) keeping the verified receipt line and no other
  event; **one cache-admission rule for both tools** (every record about the launch read, bound to the
  launch record and the destination, contradictions and unverifiable lines refusing whatever the
  filename order, a recorded contradiction never superseded — disposed only by a hand-read completion
  that acknowledges it by digest, recorded beside it, after which only that receipt completes the
  launch — rejected and exhausted attempts never blocking the next read); the line handed to
  **exactly the hand-read completion** — `production_launch.py --complete-row --collect-receipt` and
  `production_permission_cells.py --collect-receipt <subcell>`, each behind
  `--i-am-the-owner-authorizing-receipt-collection` and the actor's launcher identity, refused until
  the launcher observed the terminal state, the logs client built only there. A verified `COLLECTED`
  line is reused (no second read); a completion interrupted after the collection record repairs
  itself; a FAILED or INCONCLUSIVE subcell keeps its reading. **An exhausted or incomplete scan proves
  only that no receipt was established within it; a successful read is not a successful
  verification; delayed delivery is the stated limitation.** The SDK client's serialized `GetLogEvents`
  (`Logs_20140328.GetLogEvents`, `startFromHead`, `nextToken`) and its one-attempt behaviour on a
  throttle, a 5xx and a denial are asserted at an intercepted transport with invented credentials.
  Correction 1 (ADR-0049 §6): the three review findings — an incomplete scan establishing
  uniqueness, unvalidated content persisted before refusal, cached records chosen by filename order
  with no recovery — reproduced on the reviewed head and closed. Correction 2 (ADR-0049 §6.4): a
  recorded contradiction superseded by a later collection or a cache hit — reproduced through both
  public paths and closed (`CONTRADICTION_UNRESOLVED`; explicit acknowledged disposition). Correction
  3 (ADR-0049 §6.5): a disposition naming receipt A not constraining recovery with receipt B —
  reproduced through both public paths at the interruption boundary and closed (`refused_receipt_binding`).
- **The deletion rehearsal path** (`deletion_rehearsal.py`, ADR-0049 §3; ADR-0048 §4's
  design): the target derived from the one bound, MATCHED R-4 human `PutObject` record whose key is the
  synthetic marker's content address and whose object no cleanup has settled — nothing else is ever a
  target; rehearsal statements (`kalpamani-deletion-rehearsal-statement/v1`) binding subcell,
  principal (`DELETION_ROLE`), operation, expectation, exact target, sequence position, stamp and
  binding; the owner's authorization consumed durably (`deletion_rehearsal_authorization`) before any
  operation; the sequence `R8-GET` (a denial passes; a body fails) then `R8-LIST-AND-DELETE` (one list,
  then — only if allowed — one delete of the exact key; 200 then 204 pass **only with** the control
  principal's later verified confirmation of absence; a denial fails; an ambiguous delete is
  `possibly_deleted` and decides nothing; residue is reported); records
  (`kalpamani-deletion-rehearsal-record/v1`) of classes and counts; the reading (`PASSED`, `FAILED`,
  `INCONCLUSIVE`, `CLEANUP_UNRESOLVED`, `RESIDUE`). **CLOSED**: `REHEARSAL_PATH_OPEN` is `False`, the
  catalogue keeps both R-8 subcells BLOCKED with the dependency naming ADR-0049 D-1, the tool refuses
  `--rehearse-deletion` before any path or flag, no family / entry / launcher / parameter / role delta
  is declared, and the engine's only callers are the tests over a fake acting as the deletion role.

### 13.2 Proposed, blocked, and the decisions and permissions the owner holds

| | |
|---|---|
| **proposed** | ADR-0049 (PROPOSED — NOT IN FORCE while its pull request was open; **since ACCEPTED / IN FORCE on the merge of PR #108**): the collector, the optional registered `log_destination` block, the rehearsal's offline implementation, the amendments of its §4 |
| **blocked** | R8-DELETION's two subcells, on **Decision D-1** (ADR-0049 §3.8): open the rehearsal path — the smallest concrete decision, presented with its consequences (ADR-0007's verified inert property reversed by design; one family, one launcher, three parameters, two bootstrap permissions on the deletion role; one synthetic object deleted per authorization) and **taken by nobody here** |
| **owner decisions and values required** | D-1 (above); the registered `log_destination` of every applied revision (`log_group` = `/kalpamani/<name_prefix>/research`, `stream_prefix`, `container` — transcribed from the applied task definition, like the rest of the evidence); every value D.1 already lists (all MISSING) |
| **permissions required, explicitly not granted** | `logs:GetLogEvents` for each launcher permission set on exactly its own families' streams (`…:log-group:/kalpamani/<name_prefix>/research:log-stream:production-<container>/<container>/*`; no `FilterLogEvents`, no `DescribeLogStreams`); on D-1 only: `KalpaManiDeletionRehearse` and the deletion role's `ssm:GetParameter` / `kms:Decrypt` bootstrap delta; unchanged: the control principal's ECS actions, `ecs:DescribeTaskDefinition`, the Reachability Analyzer delta, the probe families' apply |
| **exact next runtime prerequisites** | before any collection: the `logs:GetLogEvents` delta declared, validated externally, applied under its own authorization; the `log_destination` registered; a launch record with an observed terminal exit; one collection authorization per launch. Before any rehearsal: D-1 taken; the rehearsal resources declared and applied; the rehearsal entry built into the image under the image gate; the deletion runtime binding materialized; the R-4 human `PutObject` subcell PASSED under the binding in force; one authorization per R-8 subcell; the control principal's cleanup afterwards |

### 13.3 What has not moved

Counts stay 56 / 6 / 32 / 2 / 2; every executable subcell UNEXECUTED; no receipt collected; no log
read; no rehearsal; no deletion; no image; no plan or apply; every owner value MISSING; the
bucket-policy transition (G-14), the control principal's ECS actions and the stopped-task-visibility
and `ExecuteCommand` evaluation-order limitations unchanged. **G2 OPEN · CONTROL DEFERRED · Phase 3
NOT COMPLETE · live trading HARD-DISABLED.**

## 14. The deletion-rehearsal readiness cycle — D-1 made concrete, the rehearsal integrated offline, the declaration inert; ADR-0050

> **ADR-0050 has since been accepted.** PR #109 merged 2026-09-15T17:36:51Z (merge commit `5f5035fe…`,
> approved head `4ea7e733…` after two review corrections, merge tree identical to the reviewed head
> tree). The section below was written while the pull request was open and says "proposed" of those days,
> which is not rewritten. What acceptance changed is exactly ADR-0050's own clause: the concrete D-1
> statement, the offline integration (with corrections 1 and 2), the inert declaration and the owner
> checklist are **accepted**; **D-1 stays undecided**, the path stays **CLOSED**, `deletion_rehearsal_open`
> stays `false`, both R-8 subcells stay **BLOCKED**, and **no execution or permission followed from the
> merge**.

### 14.1 Decision D-1, made concrete and not taken

ADR-0049 §3.8 presented D-1 in one paragraph; proposed
[ADR-0050](../decisions/ADR-0050-deletion-rehearsal-decision-made-concrete-and-offline-integration.md) §2
states it as the exact consequence of accepting the declaration and the integration below: the
resources and permissions (§2.2), who launches and which role deletes (§2.3 — a human launcher
holding `KalpaManiDeletionRehearse` **passes** the deletion role to ECS; **the deletion role deletes as
the task**; no human ever assumes it), how the target is held to the one synthetic R-4 object (§2.4 —
the statement, the input's recomputed digest, the task's bucket check and the engine's exact operations;
**not IAM**, which cannot name one key for a delete), the exclusion of production and unrelated
resources (§2.5), the operation limits (§2.6), every interruption's recorded outcome with no retry
(§2.7), the control principal's cleanup as the only confirmation (§2.8), the residual risks (§2.9 —
ADR-0007's verified inert property reversed by design; the role's bucket-wide delete authority bounded by
the rehearsal image's code and its pinned digest), what acceptance enables versus what still needs its
own authorization (§2.10), and the decision verbatim for the owner's signature (§2.11). **D-1 is not
taken here or by ADR-0050's acceptance**; the path stays CLOSED and R-8 BLOCKED.

### 14.2 Implemented offline (never run)

- **The rehearsal task** (`deletion_rehearsal_task.py`): the composition the deletion role's task
  definition would run — entry, credential environment, metadata, the rehearsal runtime binding
  (`kalpamani-deletion-runtime-binding/v1`, kind `kalpamani-deletion-rehearsal-runtime`), the launcher's
  input (`kalpamani-deletion-rehearsal-input/v1`, the whole statement, its digest recomputed), the target
  held to the bound bucket, the identity (the deletion role's exact name in the bound account, this task's
  session), the bounded release barrier (5 s / 60 reads / 300 s), then the engine over one client built
  only after the release; one bound receipt line (`kalpamani-deletion-rehearsal-receipt/v1`), exit 50–59
  disjoint from every other table.
- **The launcher and the completion** (`deletion_rehearsal_launch.py`): the launch inputs held to the
  rehearsal family, the deletion role and one account; a `RunTask` with no overrides; the sequence —
  identity, no unsettled reservation beside the ledger, durable consumption, the reservation **anchored
  beside the canonical ledger with the whole compiled specification**, create-only input, one
  never-retried `RunTask`, placement, create-only release, observation, cleanup failures beside the
  outcome, the launch record, the **resolution** anchored beside the reservation with the closed task
  state (correction 1, ADR-0050 §8.1); the record rebuilt only from a verified `REHEARSED` receipt whose
  exit the launcher observed, admitted by **one evidence-binding rule** — consumption, reservation,
  registered specification, launch, retained verified receipt and result for the exact target — that
  prerequisite admission applies too (§8.2).
- **The collector, reused** with an injected verifier; the rehearsal container a known destination.
- **The owner tool's five modes** (`--prepare-rehearsal`, `--rehearse-deletion`,
  `--collect-rehearsal-receipt`, `--complete-rehearsal`, and since correction 1
  `--recover-rehearsal-launch`; `production_deletion_rehearsal_tool.py`), each refused with exit 27
  before any path, flag or client while `REHEARSAL_PATH_OPEN` is `False` — which it is — and exercised
  end to end on fakes with the constant monkeypatched in tests only. An unresolved launch (no
  resolution, `UNKNOWN`, `STARTED_NOT_TERMINAL`) blocks every launch across records directories and
  authorizations until the control principal's verified cleanup settles it under the accepted rule —
  a listing that finds nothing settles nothing; the hand-read completion is held to ADR-0049's
  contradiction and disposition rules (§8.3); every completion retains the verified receipt beside the
  record and is repeatable from that evidence. Correction 2 (§8.4): a `StopTask` acknowledgement on the
  MISPLACED or STALE_RELEASE path settles nothing — the exact task is observed within the one bound, only
  an observed `STOPPED` settles, and `STOP_ACKNOWLEDGED` (task identity kept) blocks every launch until
  the control principal's cleanup describes that task `STOPPED`.
- **The inert declaration** (`production_deletion_rehearsal.tf`, `production_variables.tf`,
  `production_bindings.tf`): every rehearsal resource gated on stage a/b **and** `deletion_rehearsal_open`
  (**false by default**) **and** a `deletion_rehearsal` image digest, the assignment on stage b too;
  the closed default declares nothing and the key policy is exactly the accepted seven statements;
  validated in a task-owned external copy under the pinned provider and the mock (`fmt`, `init
  -backend=false`, `validate`, `terraform test`: 20 runs, five new) and held by a structural test over
  the parsed HCL; `iam.tf` untouched; **no plan, no apply**.

### 14.3 Owner inputs

[`production-owner-checklist.md`](production-owner-checklist.md): one prioritized checklist in four
groups (before local image preparation; before publication or infrastructure change; before verification
launches and collection; before the first production acquisition and build), each item with its purpose,
format, authoritative source, dependencies and whether an accepted value exists — **every private value
MISSING**, none read or invented, values obtainable only after a runtime step marked so.

### 14.4 What has not moved

Counts stay 56 / 6 / 32 / 2 / 2; every executable subcell UNEXECUTED; no rehearsal; no deletion; no
launch; no receipt collected; no log read; no image; no plan or apply; no variable set; no permission
granted; every owner value MISSING; the bucket-policy transition (G-14), the control principal's ECS
actions and the deferred `logs:GetLogEvents` delta for the actor launchers unchanged. **G2 OPEN · CONTROL
DEFERRED · Phase 3 NOT COMPLETE · live trading HARD-DISABLED.**

## 16. The build-verification prerequisite cycle (2026-09-17) — ADR-0045 §11 PROPOSED

`R1-BLD-BOOTSTRAP` could not be prepared: the build input admitted only a `RECEIPT_VERIFIED` `COMPLETED` production
acquisition row, none exists before S10a, and S10a's prerequisite reads "S9 verified" (§4.3). ADR-0045 §11 (proposed)
lets a verification-only build launch carry an empty run set with zero data processing; the production build's
requirement is unchanged and held by regressions. **Deployment impact if accepted:** the build-verify image must be
rebuilt from a release containing the amendment (the `21fa654e` image would refuse the empty input), the
`kalpamani-research-build-verify` task definition replaced (revision 2) with the build launcher policy updated, and the
launch-inputs registration re-issued (earlier permission records HISTORICAL). No other image needs rebuilding. Until
then the build half of S9 stays unpreparable. **Procedure, standing from this date: every S9 cell is prepared and
executed through `scripts/production_verification_cells.py` (`--prepare-cell` / `--execute-cell` / `--complete-cell` /
`--verdict-cell`), never through `production_launch.py` directly** — the cell runner attributes a launch to its cell
only through its own preparation record, and a launch made outside it, however well evidenced, reads `UNEXECUTED`
in the matrix (the 2026-09-17 acquisition bootstrap launch, `verify-acq-20260917T005249Z-76b22185`, is such a
launch: receipt-verified in the ledger, not attributed, preserved as is).

## 17. The pagination-v2 governance cycle (2026-09-18) — ADR-0053 PROPOSED; run 1 historical, not buildable; run 2 superseded; S10c blocked

**What the first production acquisition established.** O-5 run 1 (`run-20260917T221453Z-af316f8b`, 2026-09-17) `COMPLETED`
exit 0 and receipt-verified (96 provider requests, 1 secret retrieval, 290 conditional writes); its locator is admitted by the
accepted validator (65,169 bytes, `24f9c7be…`). Eight of its payload pages were then read under two separately authorized
read-only diagnoses through the accepted exact reader and parser: **every compiled tickers page (4) and actions page (2 + 2)
carried exactly 10,000 rows** — the responses continue beyond the compiled ceilings — and **2,147 byte-identical rows were served
on tickers offsets 20,000 and 30,000** (none duplicated within a page): the vendor's default `lastpricedate.desc` order ties every
active ticker, so offset assembly is neither complete nor deterministic (`PSR-SHD-131`/`133`, now observed). The 44 stocks windows
are complete-shaped. Under ADR-0042 the run-1 input is **not buildable**.

**The owner's decision (recorded verbatim in ADR-0053 §0).** Route R1 + R2: governed single-data-page acquisition with a
completion probe, explicit refusal of multi-page data, raised bounded payload/parser ceilings, full O-5 recompilation and the
whole-run replacement of run 1; run 1 remains historical evidence; run 2 and S10c remain on hold. **ADR-0053 is PROPOSED and
carries no authority while its pull request is open; on merge it is governance and contract only.** It amends ADR-0009, ADR-0041,
ADR-0042, ADR-0035, ADR-0040 and ADR-0043 by dated sections that preserve the accepted text.

**What changes when ADR-0053 is in force, and what it does not.** Each group or window becomes one data request at limit `L`
plus one completion probe at offset `L` with identical immutable parameters; a data-bearing, malformed or unparseable probe fails
the acquisition closed (no `COMPLETE` locator); a full data page with an empty probe is complete; multi-page data is refused on
evidence; the probe is retained and hashed but contributes no rows; schema equality and within-page uniqueness are required; the
acquisition entry parses the probe only (data responses stay opaque). **No numeric `L` and no byte, row or memory ceiling is fixed
by the ADR** — the present 16 MiB response ceiling is visibly insufficient for a single tickers response, and no replacement is
invented; every constant waits on the separately authorized qualification cycle (ADR-0053 §3, owner-input D-19), whose fallback,
if no safe single-page `L` exists, is a deterministic server-side partition — never offset pagination.

**Deployment impact, corrected.** The compiled-configuration digest binds the release commit, tree and `generated_at`, so a new
release moves the configuration digest even with unchanged semantic inputs: expect four rebuilt images (acquisition,
acquisition-verification, build, build-verification), four new release-bound configuration digests, the probe images unchanged
unless code analysis shows otherwise, four replaced task definitions, both launcher policies re-scoped to the new exact revision
ARNs, four registration blocks re-issued (`a0155d0a…` historical for those targets), registration-bound permission evidence
historical, the Terraform add/change/destroy count rederived from the declaration, and the S9/permission cells to repeat rederived
from the binding rules (likely the six R-1 cells and the R-2 corroboration/isolation path; R-3 and probe evidence not assumed
current).

**Dispositions.** Run 1: historical acquisition evidence, not buildable, to be replaced whole (≈ 94 requests: 88 stocks + 2
tickers + 4 actions; write ceiling `1 + 3×94 + 1 = 284` if 94 — final only after qualification and recompilation). Run 2:
specification `899f2e11…` superseded and preserved, identity `run-20260917T232613Z-28726d37` unconsumed, no D-15. Runs 2–19:
on hold pending the recompiled O-5 program. S10c: blocked. G1, G4, G5, PEAD, short-side and M0 readiness: unchanged. **Next
owner decision after the merge: the bounded provider-qualification authorization (D-19).** Estimate at the observed cadence:
≈ 8 bounded cycles to acquisition resumption, ≈ 10 to the first observation build, ≈ +20–25 to the first M0 backtest.
