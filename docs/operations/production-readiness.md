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
not rewritten. §10 records the tooling cycle that followed (proposed ADR-0046).

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

## 10. The verification-tooling cycle — G-4, G-5, G-6 implemented offline; proposed ADR-0046; ADR-0045 synchronized

**Status: offline owner-side tooling over accepted contracts, proposed in its own pull request; not an
authorization and not runtime evidence.** Baseline `main` at `af20f36acbe8a3006830762fbad5cb01d1e9b38b` (the PR #104 merge). Everything
here was produced on synthetic temporary files through the real modules with counting fakes for every
client. **Nothing was run against AWS**: no STS, S3, ECS, EC2 or SSM call, no image, no Terraform plan
or apply, no launch, no probe, no analysis, no private input read. **Mocked results are not AWS
verification.** The decision is [ADR-0046](../decisions/ADR-0046-verification-tooling-materializer-r3-tool-and-cell-runner.md)
— **PROPOSED, NOT IN FORCE** while its pull request is open.

### 10.1 Implemented offline

| Gap | Tool | Composes | Held by |
|---|---|---|---|
| **G-4** — the production human-binding materializer (S7) | `scripts/production_human_binding_materialize.py` | the ADR-0024 environment-binding loader against the governed local account; `parse_production_runtime_binding` before a byte is written; the one private-artifact writer (exclusive create, owner-only descriptor, read-back); `load_human_runtime_binding` with the actor's own variable, and removal on a refused reload | `test_production_human_binding_materialize.py` (19): both actors, the other actor's loader refuses the document, a real synthetic private root round trip, occupied destination refused, every refusal writes nothing, the two authorizations distinct and unforgeable, no private value in any output; no SDK import |
| **G-5** — the R-3 tool (S5) | `scripts/production_r3_verification.py` + `r3_verification.py` | the foundation identity gate (`kalpamani-foundation`, PASS/FAIL); the environment binding; the nine accepted rows and the ten-operation failure-path cleanup on an injected client; row 9's `404` the only confirmation of the positive control's absence (row 8's `204` acknowledges the delete); `kalpamani-r3-verification-record/v1` written by the private-artifact writer; `--check-record` for old evidence; the S3 client at `total_max_attempts: 1` | `test_production_r3_verification.py` (97): every response class; the accepted table; a bucket under the policy verifies with nine operations and no residue; each deviation class halts and does not verify; `200`s on rows 2/4/5/6 cleaned and confirmed; row 9 answering `200`, a timeout, an access denial or a network failure after row 8's `204` cleaned up within the budget with the failed row preserved — `NOT_VERIFIED` on a later confirmation, `NOT_VERIFIED_CLEANUP_UNRESOLVED` with residue otherwise, never `VERIFIED`; an abort repeated at most once; unresolved cleanup names residue; the budget never exceeded; a record contradicting its rows refused; old evidence attests to nothing changed; the tool's default performs nothing; every refusal stops before any S3 operation; the SDK named once; the real adapter under invented static credentials with its HTTP session replaced by a counting fake: one transport attempt on `SlowDown`, `500`, timeouts and connection failures, every class in the table, the conditional-copy header present only on the conditional call, no profile-based session |
| **G-6** — the verification cell runner (S9; S8 enumerated) | `scripts/production_verification_cells.py` + `verification_cells.py` | the launch tool (prepare / execute / complete / verdict), its ledger-anchored store, the receipt validator, the verdict path, the R-3 record and the launch inputs; the prepared-cells document (`kalpamani-verification-cells/v1`) beside the ledger under the ledger lock; a matrix **derived** from records, a receipt-verified row passing only through its reservation, its launch record and the registration now in force (`HISTORICAL` otherwise, `UNBOUND` when the chain is missing, malformed or substituted); verdict records parsed through the closed `kalpamani-isolation-verdict/v1` contract and resolved deterministically | `test_production_verification_cells.py` (63): the enumeration; R-3 gates every dependant; the R-3 cell passes only with attesting `VERIFIED` evidence the inputs name; runtime states from the ledger and reservations (prepared, interrupted, launched-without-receipt, refused, failed); a bound current chain passes for both actors; a reservation for another specification, a missing reservation or launch record, a substituted record (digest, image, commit, interface) is `UNBOUND`; a changed registered image, commit, subnet or platform version is `HISTORICAL` and blocks the verdict cell; the minimal forged verdict shape, ten contradictory or incomplete documents and a corroboration over `CONNECTED` refused; malformed or unreadable verdict evidence reported as `UNBOUND`; `FAILED` dominates in either order; `NO_CORROBORATION` then bound corroboration is `PASSED`, stale or wrong-source evidence alone stays `INCONCLUSIVE`, a modelled path or a differing probe block conflicts to `UNBOUND`; the aggregate `VERIFIED` only when every cell passed; the runner's default constructs nothing; refused flags; prepare records the cell; execute needs the flag, the cell `PREPARED`, every prerequisite `PASSED` and an authorization naming the prepared digest — then the launch tool once, never twice; an interrupted cell reconciled and never relaunched; a held lock refuses; completion then verdict on a verified build launch, wrong-interface and stale transcriptions leaving it `INCONCLUSIVE` and a bound corroboration for the same launch resolving it to `PASSED` with no further `RunTask` and no client constructed; a passed verdict cell not re-evaluated |

### 10.2 Proposed — decided only by ADR-0046's acceptance

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
R-4 … R-9 orchestration; the receipt collector; G-14).
