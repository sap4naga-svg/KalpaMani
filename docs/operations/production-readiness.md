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

**Baseline.** `main` at `02998fa9bde853d4262269c3b9032bd7fc171461` — the merge of **PR #102**
(merged 2026-09-14T10:25:40Z, ordered parents `98addd070857143b2bd79ef3e2bf6c06539555ba` then
`82d0a3b24e29aa309ad501fd8b7404db1e4c3644`, merge tree `89533df7207f44ee1b5817a0be6d1a73778e53e2`,
identical to the reviewed head's tree). PR #102 merged the locally verified packaging corrections
and the status synchronization for PR #101; its images carry **synthetic** configuration and were
never published, registered or run on AWS. Successful processing inside a container, production
publication and AWS runtime verification remain **unperformed**.

The image procedure itself is [`production-image-build.md`](production-image-build.md); this
document does not restate it. The owner-input checklist is
[`production-owner-inputs.md`](production-owner-inputs.md). Both are indexed from here.

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
| `build_configuration.accepted_schemas` | the observed CSV header digests Silver admits per dataset (`SCHEMA_UNSTABLE` otherwise) | the header digests of real deliveries, observed under the private boundary — **not derivable from public documentation** | per-dataset sets of 64-hex digests; a new provider header is a configuration change and an image rebuild | owner-private → image | MISSING — and **sequenced after the first acquisition**: the production digests can be observed only from real Bronze, so the first build configuration follows the first completed acquisition |
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

**Traced path.** `scripts/production_task_entrypoint.py::main` → `select_entry` →
`_compiled_configuration` → `pre_entry_refusal` (configuration is this entry's; credential
environment is a task's by name; the container URI is the documented shape) → working directory under
`/work` → `run_task_entry` → `run_acquisition_entry` / `run_build_entry` → factories called once
(SSM, STS, S3, Secrets Manager, transport) → `run_production_acquisition` / `run_production_build` →
`run_task_bootstrap` (environment → binding → input → self-check → identity proof → release barrier)
→ **`RELEASED`** → processing.

**Finding: the accepted code cannot perform R-1/R-2 and stop.** `run_task_bootstrap` returns
`RELEASED` with zero data-plane operations, but nothing on a composed entry consumes that outcome as
a terminal one:

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

**The smallest bounded follow-up (a contract decision plus code, proposed for the next cycle,
not decided here):**

1. **One additional closed entry per actor** — a third and fourth `TaskEntry` member
   (`kalpamani-production-acquire-verify`, `kalpamani-research-build-verify`) whose composed path is
   the accepted bootstrap **and nothing after `RELEASED`**, exiting with one new closed
   `TaskOutcome` (`VERIFIED_BOOTSTRAP`, a non-zero exit code so that `0` stays `COMPLETED` alone)
   and the same receipt line; the build verify entry additionally makes the R-2 origin probe (one
   bounded connection attempt to the pinned provider origin that must time out or be refused at the
   network layer) and reports its result as a closed member. Factories for the acquisition verify
   entry construct **no Secrets Manager client and no transport**, so the verification image cannot
   perform the operations it exists to prove it did not.
2. **Two verification task-definition families** (`…-acquire-verify`, `…-build-verify`) declared at
   stage a beside the production ones, each with its actor's task role, the same network placement
   and the verification image; **each launcher set gains exactly one more `ecs:RunTask` resource**
   (its actor's verification revision) — the dependency reconciliation in §4.2 explains why this
   is the least-privilege way to run R-1/R-2 without rescoping the launcher between images.
3. **An ADR** amending ADR-0043 §2 (two entries → four, with the verification entries stated as
   bootstrap-only), ADR-0036 §2.9 (the launcher's `RunTask` resource set) and §3 (R-1/R-2 as
   verification-image cells with the exact expected exit code), with the static guard A-8 extended
   to the verify entries and a test that a verify entry's factories have no secret and no transport.

The alternative — running R-1/R-2 with the production image and a **deliberately absent release**,
so that only the negative cells are exercised — is recorded as **insufficient** for the positive
cell and is not proposed as a substitute.

---

## 4. Cloud-verification sequence

### 4.1 Ordering, derived from the accepted decisions and the declared configuration

```text
S0  owner inputs           secret (created outside Terraform), origin address set, release commit,
                           I-8/I-9 decisions, ledger initialized, tfvars values, private bindings
S1  compiled configuration production_compiled_configuration.py per entry (image gate)
S2  build context + image  production_build_context.py; docker build; step-6 local verification
S3  publish                push to the ONE research repository; record RepoDigests (registry digest)
S4  stage a (Terraform)    plan review; apply: policies, bucket-policy statements, task roles, bootstrap
                           policies, KMS key + alias, binding parameters, network, task definitions
                           (pinned by the S3 digests), the four permission sets + policy references;
                           NO assignments; administrator-binding and shared-route effects (4.4)
S5  R-3                    server-side conditional-write verification by the control principal,
                           nine expected-path operations, failure-path cleanup budget 10;
                           record + digest -> production_r3_verification_digest
S6  stage b (Terraform)    the four account assignments and nothing else
S7  human profiles         materialize the four governed profiles; identity preflights; the two
                           production human bindings under the ADR-0023 trust boundary
S8  R-4 .. R-9             permitted/denied matrix: IAM simulation (L2) then live cells (L3),
                           synthetic objects only, deletion-role cleanup
S9  R-1 / R-2              runtime verification -- BLOCKED on the verification-only path (3)
S10 first bounded run      acquisition (one authorized run), then the first build configuration
                           (schema digests observed), then one authorized build
```

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
5. **Rotation re-enters the cycle at S1.** A secret rename, an origin address change or a build
   configuration change is a new compiled configuration → a new image → a new digest → a new
   revision → a stage-a apply (ADR-0044 §2). The launcher's `RunTask` resource follows the revision
   automatically because it references the Terraform resource, not a literal.

### 4.3 The execution matrix

For every step: prerequisites and authorization · actor and minimum permissions · the exact command or
the missing implementation · allowed side effects and limits · positive and negative evidence · halt
conditions, cleanup and residual state. **A step whose command cannot be instantiated names the
missing inputs; nothing below invents an identifier, a budget, a permission or a threshold.**

| # | Step | Prerequisites · authorization | Actor · minimum permissions | Command / implementation | Side effects · limits | Evidence (positive / negative) | Halt · cleanup · residue |
|---|---|---|---|---|---|---|---|
| S0 | Owner inputs | the owner's written authorization for the image gate; the production secret created by the owner outside Terraform (never by this repository) | the owner; Secrets Manager `CreateSecret` under an owner profile is **outside** this design's principals and is not enumerated here | no command in this repository; the checklist in `production-owner-inputs.md` | none | positive: every checklist row has a value held outside the repository; negative: any row still `MISSING` | halt on any missing row; nothing to clean |
| S1 | Compiled configuration | S0; a clean checkout at the release commit | the owner, workstation; no AWS permission | `python scripts/production_compiled_configuration.py --entry <entry> --inputs <owner path> --generated-at <ISO> --output docker/production/build/<entry>` — **needs**: release commit checked out, the owner inputs files | writes the git-ignored staging directory only; no network | positive: `configuration_digest=<64 hex>` printed, `generation-record.json` names the commit and tree; negative: `compiled configuration refused: <reason>` (dirty tree, forbidden field, ARN as secret name, empty or non-IPv4 addresses, build configuration refused) | halt on refusal; residue is the staging directory, deletable |
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
| S9 | R-1 / R-2 | S6, S7; the §3 follow-up merged, built, published and registered; runtime-verification authorization | the actor's launcher set (`RunTask` on the verification revision), the actor's human set (input), the task role | **BLOCKED — no verification-only path exists** (§3); once it does: the launch tool (which also does not exist — §7) launches the verification revision with a real input; positive cell = a matching release; negative cells = no release, a mismatched release, and (build) the origin probe | one task per cell; two parameter reads (binding, input) then ≤ 60 barrier reads of the release; 1 `GetCallerIdentity`; **zero** S3, secret and provider operations by construction | positive: `VERIFIED_BOOTSTRAP` with a receipt whose `binding_digest` matches the launch record; negative: `REFUSED_NO_RELEASE` at the ceiling, `REFUSED_RELEASE_MISMATCH`, the build probe timing out or refused | halt on any data-plane count above zero; cleanup: release and input `DeleteParameter`; residue: the run identity used by the verification input is **spent** only if a reservation was written — a verify entry writes none |
| S9a | `/work` mount under uid 10001 | S9 | the same | inside the verification task, the working directory is created under `/work` after the credential-environment check (`REFUSED_DEPENDENCY` if not) | none | positive: the verify entry passes the working-directory step (not `exit 6`); negative: `REFUSED_DEPENDENCY` — Fargate did not give uid 10001 a writable `/work` (§5) | halt: a task-definition change (mount options `uid`/`gid`/`mode`, which the API documents as valid values) is a declaration change under its own apply |
| S10a | First bounded acquisition | S9 verified; ADR-0035 §5.2 I-8…I-12 supplied; one written authorization for one run | acquisition human set (input), acquisition launcher set (launch, release), acquisition task role | the launch tool — **missing implementation** (§7) | 1 run reservation + 3 writes per request + 1 locator (`1 + 3R + 1` conditional `PutObject`, R ≤ 96); 1 `GetSecretValue`; R provider requests, zero retries, 1,800 s deadline; a spent identity | positive: `COMPLETED` receipt with observed counts equal to the plan; negative: any halt outcome — `REFUSED_RESERVATION`, `REFUSED_CREDENTIAL`, `ACQUISITION_HALTED`, `LOCATOR_*` | halt: no retry under the same identity (spent); cleanup: input and release parameters; residue: Bronze objects (deletable only under the runbook) |
| S10b | First build configuration | S10a `COMPLETED` | the owner | observe the accepted schema digests from the first real deliveries under the private boundary; generate the build configuration → S1–S6 again for the build image (a new build image, digest and revision) | a second image cycle | — | — |
| S10c | First bounded build | S10b; one written authorization for one build | build human set, build launcher set, build task role | the launch tool — **missing implementation** | 1 locator read + exact reads of what it names; Silver, Gold and one manifest **last**; 3,600 s deadline | positive: `COMPLETED` with a manifest; negative: `REFUSED_INPUTS`/`REFUSED_NORMALIZATION`/… with zero writes | halt on any refusal; residue: LICENSED Silver/Gold/manifest objects |

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

| # | Gap | Kind | Blocks |
|---|---|---|---|
| G-1 | **No verification-only task path** (§3): `RELEASED` continues into processing on both composed entries; no `TaskOutcome` for bootstrap-only verification; no R-2 origin probe; ADR-0036 R-1/R-2 as written cannot be run with the accepted images | contract (ADR-0043 §2 entries; ADR-0036 §2.9/§3) + code | S9 |
| G-2 | **No owner-side launch tool**: `launch_authorized_run` has no script that builds the real ECS/EC2/SSM clients under the human and launcher profiles with their before-and-after identity proofs, compiles `CompiledLaunch` from Terraform records, and records the launch record the receipt is bound to | code | S9, S10 |
| G-3 | **No input-materialization tool** for the acquisition input v2 (`plan_digest_for`, `spent_identities_block`) and the build input (`ledger_digest`), nor for the owner ledger the inputs are cut from | code | S9, S10 |
| G-4 | **No production human-binding materializer** for the two ADR-0036 §2.5 private files (the qualification materializer writes a different contract) | code | S7 |
| G-5 | **No R-3 tool** executing the nine counted rows, classifying the access-denied context (resource-based explicit deny vs. other) and running the budgeted failure-path cleanup | code (the procedure is accepted) | S5 |
| G-6 | **No R-4 … R-9 cell runner** (L2 simulation + L3 live cells with counted operations) | code | S8 |
| G-7 | **Accepted schema digests are observable only from real deliveries**, so the first build image can be compiled only after the first acquisition completes — a sequencing constraint, not a defect, but one no document stated | sequencing | S10b |
| G-8 | **No real exchange calendar** and no calendar source decision (the venv carries no tzdata; `sessions.py` is synthetic) | owner input + code | S10b |
| G-9 | **Receipt collection**: deferred by decision (§6); the ledger row is hand-completed until then | contract (deferred) | S10 ledger completion |
| G-10 | **Fargate `tmpfs` documentation conflict** (§5) — resolved only by S4's registration and S9a's mount check; a fallback declaration (`uid`/`gid`/`mode` options, or a bind mount) is available and not made | evidence | S4, S9a |
| G-11 | **ECR push permissions**: no principal in the foundation or production design holds image-push actions; which owner profile publishes is undecided | owner decision | S3 |

---

## 8. The single next bounded cycle

**Scope: close G-1 and G-2 together — the verification-only path and the launch tool — as one
offline, synthetic-only implementation cycle with its ADR, so that S9 has both a task that stops at
the barrier and a tool that can launch it.** Concretely:

1. an ADR (proposed, no authority until merged) amending ADR-0043 §2 to four closed entries, ADR-0036
   §2.9's launcher `RunTask` resource set (one production and one verification revision per actor) and
   §3's R-1/R-2 cells with the exact closed exit code;
2. `TaskEntry` + `TaskOutcome.VERIFIED_BOOTSTRAP` (non-zero), `run_acquisition_verify_entry` /
   `run_build_verify_entry` composing `run_task_bootstrap` and nothing after `RELEASED`, factories
   without a secrets client or transport, the build-side origin probe as a closed member, the receipt
   line unchanged in shape; the Dockerfile's two verify targets and entry executables; the static
   guard extended;
3. `scripts/production_launch.py`: the owner-side launch tool — human bootstrap, input materialization
   from an owner ledger file and a slice document (`plan_digest_for`, `spent_identities_block`,
   `ledger_digest`), `CompiledLaunch` compiled from a Terraform-output record, `launch_authorized_run`
   on real clients under the two profiles with pinned `AWS_PROFILE` and the §4.24 gate, the launch
   record written beside the input, and the cleanup — refusing by default, one explicit flag per
   authorized run, no output that names an identifier;
4. the Terraform declaration of the two verification families and the launcher resource additions,
   validated in an external copy only;
5. tests for each, against fakes; the docs audit and status synchronization.

**Can proceed independently alongside it** (no dependency on G-1/G-2): G-4 (the production
human-binding materializer), G-5 (the R-3 tool — it needs only the foundation profile and stage a),
the owner's S0 inputs (secret creation outside the repository, origin address resolution, the release
commit choice, I-8/I-9), and G-8's calendar-source decision. **Not before the cycle above:** any AWS,
Terraform, image, registry, launch or provider operation.
