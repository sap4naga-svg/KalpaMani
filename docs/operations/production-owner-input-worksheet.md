# Production owner-input worksheet — what to supply, from where, when, and how it is checked

*Prepared in the ADR-0050 accepted-state synchronization cycle; a companion to
[`production-owner-checklist.md`](production-owner-checklist.md) (the prioritized list, whose item
numbers this worksheet keeps), [`production-owner-inputs.md`](production-owner-inputs.md) (§A–§D, the full
register) and [`production-readiness.md`](production-readiness.md) (the sequence S0–S10). Every row is
derived from a tracked loader, contract, declaration or document; none was read from a private input, and
no value is invented. **Every private value is MISSING.** Preparing this worksheet completes none of them.*

## How to read a row

| Column | Meaning |
|---|---|
| **Supply** | what the owner must produce, in one phrase |
| **From** | where the value comes from — a decision, an owner-held system, or a runtime step's output |
| **When** | **now** (before any runtime step), or **after S-n** (exists only once that step has run) |
| **Consumed by** | the step, tool mode or declaration that refuses without it |
| **Validated by** | the loader, parser, variable validation or gate that checks it, and what it checks |
| **Private?** | whether the value may enter a tracked file (`tracked`) or must stay outside the repository (`PRIVATE`), and where the owner places it |

Private placement follows the accepted ADR-0023 convention: a file under the owner's private root
`%LOCALAPPDATA%\KalpaMani\private` (a containment boundary — never searched, never listed), named to the
tool by exactly the environment variable or the `--path` argument the row states, owner-only ACL. The
git-ignored `terraform.tfvars` holds the Terraform values. Nothing private is ever typed into `argv`,
a tracked example, a commit message or a pull request.

## 1. Before local image preparation (S0–S2)

| # | Supply | From | When | Consumed by | Validated by | Private? |
|---|---|---|---|---|---|---|
| 1.1 | the **release commit** on `main` (owner-inputs "D-1 release commit" — not ADR-0049/0050's D-1) | the owner's written decision; `main` now carries ADR-0050 (`5f5035fe…`) and the commit may be it or a later reviewed one | **now** | S1 (the compiled configuration names it), S2 (`scripts/production_build_context.py --commit`; the Dockerfile's `KALPAMANI_COMMIT` argument) | `production_build_context.py`: 40 lowercase hex, an existing commit, the context prepared from that exact Git tree and never from a working tree; ADR-0044 §3 | tracked (a commit SHA is public) — record it in the build record |
| 1.2 | the **production Sharadar secret's name** | the owner creates the secret in Secrets Manager (this repository creates none) | **now** | S1 (`compiled-configuration.acquire`, field `secret_name`); the acquisition task's one `GetSecretValue` | `compiled.secret_name_refusal`: a name of the documented length and character grammar, **never an ARN**; the task's runtime reads the value, never the tool | **PRIVATE** — the name goes only into the compiled-configuration input file the owner keeps outside the repository; the value never leaves Secrets Manager |
| 1.3 | the **provider origin address set** | the owner resolves the provider origin before each run window | **now**, refreshed per window | S1 (`origin_addresses` of the acquire and verify configurations); S4/S6 (`production_provider_origin_cidrs`) | `task_clients.compiled_origin_addresses`: distinct **IPv4 literals** in canonical form (the compiled file); `production_variables.tf`: **IPv4 CIDR blocks**, never `0.0.0.0/0`, non-empty at stage a/b (the allowlist); the two kept equal by the owner (each literal as its `/32`, or the vendor's published blocks resolved to literals) | **PRIVATE** by convention (an operational address set) — the compiled input file and `terraform.tfvars` |
| 1.4 | the **build configuration** (`accepted_schemas` per Route A or B; rule parameters; sessions; calendar source) | the owner's written decisions D-3, D-4, D-5, D-11; Route A digests only from the private report | decisions **now**; Route A digests owner-held; Route B digests after S10b | S1 (`compiled-configuration.build`) | `compiled.parse_compiled_configuration`: the closed field set, `BuildConfiguration.document()` grammar (ADR-0040 / ADR-0042); an example is `docs/operations/examples/production/build-inputs*.synthetic.json` | tracked decisions; **PRIVATE** digests (they derive from licensed observations) |
| 1.5 | `BASE_IMAGE_DIGEST` — the linux/amd64 **manifest** digest of `python:3.11-slim` | the registry, resolved by the owner | **now** | S2 (the Dockerfile's required build argument) | the Dockerfile refuses a build without it; ADR-0044 §6 requires the platform manifest, never the index; recorded in the build record | tracked (a public image digest) |
| 1.6 | the **rehearsal image** decision | **Decision D-1** (ADR-0049 §3.8 / ADR-0050 §2.11), the owner's written acceptance outside the repository | **now** — a decision; **NOT TAKEN** | whether a `deletion_rehearsal` image is prepared at S2 beside the actor images | the image's only entry is `kalpamani-deletion-rehearsal`; the digest key is admitted by `production_variables.tf` only with `deletion_rehearsal_open = true` | tracked decision (a signed acceptance outside the repository) |

## 2. Before publication or infrastructure change (S3–S6)

| # | Supply | From | When | Consumed by | Validated by | Private? |
|---|---|---|---|---|---|---|
| 2.1 | **which owner profile pushes images** (owner-inputs D-6) | the owner's written decision | **now** | S3 | no declared principal holds push actions; the profile must hold the `ecr:*` actions readiness S3 lists | tracked decision; the profile name is operational, kept outside the repository |
| 2.2 | the **registry digests** of every pushed image (`RepoDigests`) | S3's push output | **after S3** | S4 (`production_image_digests`), 2.6 and 2.10 (the launch-inputs records) | `production_variables.tf`: `sha256:<64 hex>` per key (`acquisition`, `build`; optional `acquisition_verify`, `build_verify`, `acquisition_probe`, `build_probe`, `deletion_rehearsal`); the launch records hold a registered target's digest to the applied revision | **PRIVATE** — `terraform.tfvars` and the launch-inputs file |
| 2.3 | `terraform.tfvars`: `production_acquisition_secret_arn`, `production_binding_provenance` (commit / tree / ADR-0024 digest), `identity_center_region`, `production_apply_principal_arn_pattern`, `production_target_account_id` (optional), `production_endpoints_enabled` | the owner's account, the secret of 1.2, the captured ADR-0024 environment binding | **now** | S4 (stage a refuses without them) | each variable's `validation` block in `production_variables.tf` (ARN grammar; 40 / 40 / 64 hex; a Region name; an IAM role ARN pattern; a twelve-digit account when supplied); the blocking account-consistency precondition | **PRIVATE** — `terraform.tfvars` only (git-ignored); never a tracked example |
| 2.4 | `production_stage = "a"` | the owner's written acceptance of the stage-a side effects (owner-inputs D-8) and a separately authorized apply | a decision **now**; the apply **later** | S4 | `production_variables.tf` (`none` → `a`); the plan review readiness §4 prescribes | **PRIVATE** — `terraform.tfvars` |
| 2.5 | the **R-3 verification record** and its SHA-256 (`production_r3_verification_digest`) | S5's one authorized R-3 session (`scripts/production_r3_verification.py`) | **after S5** | S6 (stage b refuses without it) | `kalpamani-r3-verification-record/v1`, result `VERIFIED`; the variable requires 64 hex; the tool's `--check-record` re-verifies the record the environment names (`KALPAMANI_PRODUCTION_R3_RECORD_FILE` / `KALPAMANI_PRODUCTION_R3_RECORD_DIR`) | **PRIVATE** — the record under the private root; the digest in `terraform.tfvars` |
| 2.6 | the **launch-inputs record** (`kalpamani-launch-inputs/v1`) | transcribed from the applied stage-a resources (S4b read-back) | **after S4** | every `production_launch.py --launch-inputs` and `production_permission_cells.py --launch-inputs` mode; every collection (`log_destination`) | `launch_records.parse_launch_inputs`: the closed field set, one account, per-actor task role, subnet, groups, every registered target's revision ARN / digests / commit / task-definition evidence, optional `log_destination = {log_group, stream_prefix, container}` | **PRIVATE** — a file under the private root, passed by `--launch-inputs` |
| 2.7 | the two **production human runtime bindings** and the four **profiles** (human and launcher per actor) | S7: `scripts/production_human_binding_materialize.py` under its per-actor authorization flag; the profiles materialized by the owner operator | **after S6** | every launch tool and permission tool bootstrap | `bindings.load_human_runtime_binding`: containment beneath the private root, regular file, no link, owner-only ACL, size ceiling, strict decoding, the per-actor field set; profile names fixed by the vocabulary | **PRIVATE** — files under the private root named by `KALPAMANI_PRODUCTION_ACQUISITION_RUNTIME_BINDING_FILE` and `KALPAMANI_RESEARCH_BUILD_RUNTIME_BINDING_FILE`; profiles in the owner's AWS configuration |
| 2.8 | the **permission targets** document (`kalpamani-permission-targets/v1`: foundation task role ARN, qualification secret ARN, CONTROL bucket name) | the applied foundation (exists today) | **now** | R-4's refused secret, R-4/R-5's refused bucket, R-9 (`production_permission_cells.py`) | `permission_cells.parse_permission_targets`: the three values, each in its grammar; the tool reads the file `KALPAMANI_PRODUCTION_PERMISSION_TARGETS_FILE` names through the private reader (containment beneath the private root, size ceiling) | **PRIVATE** — a file under the private root |
| 2.9 | **Decision D-1** in writing (ADR-0050 §2.11), then `deletion_rehearsal_open = true` and the `deletion_rehearsal` digest | the owner's signed acceptance outside the repository; 2.2 for the digest | **NOT TAKEN**; the variable stays `false` | the rehearsal resources declare only under stage a/b **and** the variable **and** the digest; the assignment only at stage b | `production_variables.tf` (`deletion_rehearsal_open` boolean, `false` by default; the digest key); the tftest runs of ADR-0050 §4 | **PRIVATE** — `terraform.tfvars`; the decision itself is the owner's document |
| 2.10 | the **rehearsal launch inputs** (`kalpamani-deletion-rehearsal-launch-inputs/v1`) and the **launcher profile** `kalpamani-deletion-rehearse` | transcribed from the applied rehearsal resources; the profile materialized at stage b | **after the rehearsal apply** (which needs 2.9) | `--rehearse-deletion`, `--collect-rehearsal-receipt` | `deletion_rehearsal_launch.parse_rehearsal_launch_inputs`: family held to `kalpamani-deletion-rehearsal`, the deletion role's name held to `-licensed-data-deletion`, one account, the rehearsal `log_destination` | **PRIVATE** — a file under the private root, passed by `--rehearsal-inputs` |
| 2.11 | the **G-14 transition procedure** before any change to the deployed licensed bucket policy | a separately reviewed procedure | deferred; not needed for stage a | any later bucket-policy change | readiness §4.6, §6 | tracked (a procedure) |
| 2.12 | the **Reachability Analyzer delta** decision and principal (owner-inputs D-14) | the owner's written decision | **now** (a decision), not required to proceed | R-2 corroboration (`--isolation-verdict`) | ADR-0045 §3: the four `ec2:*NetworkInsights*` actions declared and applied, or every non-connection reads `INCONCLUSIVE` | tracked decision |

## 3. Before verification launches and collection (S7–S9; the permission subcells; the rehearsal)

| # | Supply | From | When | Consumed by | Validated by | Private? |
|---|---|---|---|---|---|---|
| 3.1 | the **owner ledger** (`kalpamani-owner-ledger/v1`) | created empty by the owner; appended only by the tools | **now** (empty at first) | every identity, input, reservation and completion (`--ledger`) | `launch_records` (the contract; the example `owner-ledger.synthetic.json`); consumptions, reservations and resolutions anchored beside it (`<ledger>.consumed/`, `.rehearsal_reservations/`, `.rehearsal_resolutions/`) | **PRIVATE** — under the private root, passed by `--ledger`; never typed |
| 3.2 | per launch: the **written launch authorization** (`kalpamani-launch-authorization/v1`) naming the printed specification digest (owner-inputs D-15) | the owner, after reviewing the prepared specification | **after each preparation** | `production_launch.py --authorization` | `launch_records.parse_authorization`: actor, kind, identity, the exact specification digest, validity ≤ 24 h (`MAX_AUTHORIZATION_VALIDITY`); the identity is consumed by its authorization through the ledger row and may never be launched again | **PRIVATE** — a file under the private root |
| 3.3 | per verification or negative launch: the **receipt lines** read from the log stream, or a **collection** | the launch's own log stream (hand-read), or the collector under the launcher profile | **after each launch** | `--complete-row` / `--complete-row --collect-receipt` | the receipt verified against the launch record before any record is written; a collection needs the `logs:GetLogEvents` delta applied (**recorded, not granted**) and 2.6's `log_destination` | **PRIVATE** — a lines file under the private root (`--receipt-lines`) |
| 3.4 | per permission subcell: one **prepared statement** (its printed digest) and one **authorization** (`kalpamani-permission-authorization/v1`) | `--prepare-subcell`, then the owner's written authorization | **after each preparation** | `--execute-subcell` (consumed by its one execution) | `permission_cells.parse_permission_authorization`: subcell, the exact statement digest, the stated validity; the statement recomputed against what is admitted now | **PRIVATE** — files under the private root |
| 3.5 | the **control principal's cleanup** authorization after each session | the owner, per session | **after each session** | `--cleanup` under the control profile (`kalpamani-foundation`) | the cleanup settles every created or possibly created object and every started task; a listing that finds nothing settles nothing | a flag; nothing private beyond the records |
| 3.6 | the control principal's `ecs:ListTasks` / `DescribeTasks` / `StopTask` on the cluster | an IAM check by the owner (whether the policy already holds them is **not established here**) | a check **now** | discovery and settlement of an unexpected launch | ADR-0047 §3.5, §5 — recorded, not granted; a declared delta if absent | tracked (a finding); no value |
| 3.7 | the **R-4 human `PutObject` subcell** PASSED under the binding in force | S8 | **after that subcell** | the one rehearsal target (`deletion_rehearsal.rehearsal_target`) | exactly one bound MATCHED R-4 record whose created key is the synthetic marker's content address and whose object no admissible cleanup has settled | the record under the records directory (private) |
| 3.8 | per R-8 subcell: one **rehearsal statement** (`--prepare-rehearsal`, its printed digest) and one **authorization** naming it; `R8-GET` first, `R8-LIST-AND-DELETE` only after `R8-GET` is recorded PASS | the owner, after D-1 and the merged pull request that sets `REHEARSAL_PATH_OPEN` | **after 2.9 and 3.7** — today refused with exit 27 | `--rehearse-deletion` | `kalpamani-deletion-rehearsal-statement/v1` recomputed at launch; the same authorization contract; consumed durably before any mutation; refused while any reservation beside the ledger is unsettled | **PRIVATE** — files under the private root |
| 3.9 | per rehearsal launch: the **receipt line** (hand-read from `production-deletion-rehearsal/deletion-rehearsal/<task id>`, or collected under the rehearsal launcher) | the rehearsal task's log stream | **after each rehearsal launch** | `--complete-rehearsal --receipt-lines` / `--collect-rehearsal-receipt` | `kalpamani-deletion-rehearsal-receipt/v1` verified against the launch record; the one evidence-binding rule (ADR-0050 §8.2); the contradiction / disposition rules on the hand path (§8.3) | **PRIVATE** — a lines file under the private root |
| 3.10 | per interrupted rehearsal launch: the **offline recovery** (`--recover-rehearsal-launch <subcell>`), then the control principal's verified cleanup | the reservation beside the ledger (nothing to supply) | **only after an interruption** | every launch is refused (exit 21) while a reservation is unsettled | ADR-0050 §8.1 / §8.4: settled only by a cleanup that discovered and described the task `STOPPED` | nothing to supply |
| 3.11 | the **R-2 reachability evidence** (`kalpamani-reachability-evidence/v1`, owner-inputs D-16) | one Reachability Analyzer analysis, transcribed | **after S9 (build)**, optional | `--isolation-verdict --reachability-evidence` | the contract's fields (ADR-0045 §3) | **PRIVATE** — a file under the private root |

## 4. Before the first production acquisition and build (S10)

| # | Supply | From | When | Consumed by | Validated by | Private? |
|---|---|---|---|---|---|---|
| 4.1 | the **first bounded acquisition scope** (owner-inputs D-2): `acquisition_mode`, datasets, windows, ≤ 96 requests, response ceiling | the owner's written decision (ADR-0035 §5.2 I-8) | **now** (a decision) | the acquisition slice → the plan digest | `plan.py` compiles the plan from the slice and refuses a digest that is not the compiled one; `inputs.py` | tracked decision; the slice document under the private root when it carries operational values |
| 4.2 | per run: the **acquisition input v2** (identity, slice, plan digest, spent identities from the ledger, ≤ 24 h) | the launch tool cuts it from the ledger (`--slice`, `--run-identity`) | **after the verification cells** | `/kalpamani/production/acquisition/input` (create-only, written by the acquisition human set) | `inputs.py`: ≤ 8 KiB, 24 h validity, ≤ 32 identities, the ledger digest over the delivered rows, the plan digest against the compiled plan; example `acquisition-input.v2.synthetic.json` | **PRIVATE** — Parameter Store only; never a file the owner edits |
| 4.3 | per build: the **build input v1** (build identity, ≤ 32 completed `RECEIPT_VERIFIED` production rows, ledger digest, ≤ 24 h) | the launch tool cuts it from the ledger | **after the first acquisition** | `/kalpamani/production/research-build/input` | `inputs.py`; example `build-input.v1.synthetic.json` | **PRIVATE** — Parameter Store only |
| 4.4 | Route B: the observation build's refusal receipt **and** the per-dataset acceptance record; Route A: the attribution worksheet | S10b (Route B) / owner-held (Route A) | **after S10b** / owner-held | the Silver-producing image's `accepted_schemas` (owner-inputs E-10) | ADR-0042; readiness §4.2 item 6 | **PRIVATE** (derived from licensed observations) |
| 4.5 | the **written run authorization** per acquisition and per build (readiness §3) | the owner, per run | **after each preparation** | each run is its own gate | ADR-0045 §7: one record per run, never reused | **PRIVATE** — a file under the private root |

## What the owner can supply now, in dependency order

Supplying these completes nothing by itself and authorizes no runtime step; each later step keeps its own
written authorization. Ordered so that each item needs only the ones above it:

1. **1.1** the release commit (a decision; `main` at `5f5035fe…` or a later reviewed commit).
2. **1.5** `BASE_IMAGE_DIGEST` (resolve the platform manifest digest).
3. **1.2** the production secret's **name** (create the secret first; supply the name, never the value).
4. **1.3** the provider origin address set (IPv4 literals for the compiled file; the equal CIDR blocks for
   `terraform.tfvars`).
5. **1.4** the build-configuration decisions (D-3, D-4, D-5, D-11; the Route A/B choice — Route A digests
   stay owner-held).
6. **2.1** which owner profile pushes images (D-6).
7. **2.3** the `terraform.tfvars` values (secret ARN, binding provenance, Region, apply-principal pattern,
   optional target account, endpoints toggle) — into the git-ignored file only.
8. **2.4** the stage-a decision (D-8) — the apply itself stays separately authorized.
9. **2.8** the permission-targets document (from the applied foundation, which exists).
10. **3.1** an empty owner ledger under the private root.
11. **2.12**, **3.6**, **4.1** the remaining written decisions (Reachability Analyzer delta; the control
    principal's ECS-action check; the first bounded acquisition scope).
12. **Decision D-1** (1.6 / 2.9) — the owner's separate written acceptance or decline of ADR-0050 §2.11,
    outside the repository. **Not taken**; nothing above depends on it, and everything rehearsal-related
    (2.9's variable and digest, 2.10, 3.8–3.10) waits on it.

Everything else (2.2, 2.5, 2.6, 2.7, 2.10, 3.2–3.5, 3.7–3.11, 4.2–4.5) exists only after the runtime step
its row names and cannot be supplied earlier.

**G2 OPEN · CONTROL DEFERRED · Phase 3 NOT COMPLETE · live trading HARD-DISABLED.**
