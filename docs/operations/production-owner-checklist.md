# Production owner checklist — one prioritized list, from the contracts

*Prepared in the deletion-rehearsal readiness cycle (ADR-0050, accepted on the merge of PR #109; D-1 not taken); a companion to
[`production-owner-inputs.md`](production-owner-inputs.md) (§A–§D, which stays the full register) and
[`production-readiness.md`](production-readiness.md) (the sequence S0–S10); the per-item source, validation and
private-placement detail is in [`production-owner-input-worksheet.md`](production-owner-input-worksheet.md).
Every item below is derived
from a tracked contract or declaration; none was read from a private input, and no value is invented.
**Every private value is MISSING.** "Now" means the owner can supply it before any runtime step; "after
S-n" means it exists only once that step has run, and cannot be supplied earlier.*

## How to read a row

| Column | Meaning |
|---|---|
| **Purpose** | what refuses without it |
| **Format** | the grammar the consuming parser enforces (the authoritative source's) |
| **Source** | the tracked contract, declaration or document that defines it |
| **Depends on** | what must exist first |
| **Accepted value?** | `MISSING` (no value exists in this repository), `DECIDED` (a written decision exists), or `after S-n` (obtainable only after that runtime step) |

## 1. Before local image preparation (S0–S2)

| # | Item | Purpose | Format | Source | Depends on | Accepted value? |
|---|---|---|---|---|---|---|
| 1.1 | the **release commit** on `main` (owner-inputs decision "D-1 release commit") | every image is built from the exact Git tree of one commit | 40 lowercase hex | `scripts/production_build_context.py`; ADR-0044 §3 | a reviewed commit on `main` (ADR-0050's merge `5f5035fe…`, or a later one) | MISSING — **now** |
| 1.2 | the **production Sharadar secret's name** | the compiled acquisition configuration (`secret_identifier`) | a Secrets Manager name in the documented grammar; never an ARN, never the value | `compiled.py`; ADR-0044 §2 | the owner creates the secret (this repository creates none) | MISSING — **now** |
| 1.3 | the **provider origin address set** | the compiled acquisition configuration (`origin_addresses`) and the security-group allowlist; kept equal | IPv4 literals in the compiled configuration (`compiled_origin_addresses`); the equal set as IPv4 CIDR blocks in `terraform.tfvars`; never `0.0.0.0/0` | `task_clients.compiled_origin_addresses`; `production_variables.tf` `production_provider_origin_cidrs` | resolved by the owner before each run window | MISSING — **now** (refreshed per window) |
| 1.4 | the **build configuration** document (`accepted_schemas` per Route A or B) | the compiled build configuration | `BuildConfiguration.document()`; example `docs/operations/examples/production/build-inputs*.synthetic.json` | ADR-0040 / ADR-0042; owner-inputs D-3, D-4, D-5, D-11 | the rule parameters, sessions, calendar source and the schema-digest route decided in writing | MISSING — decisions **now**; Route A digests only from the private report (owner-held) |
| 1.5 | `BASE_IMAGE_DIGEST` — the linux/amd64 manifest digest of `python:3.11-slim` | the Dockerfile's required build argument | `sha256:<64 hex>` of the platform image, never the index | ADR-0044 §6; the build record | — | MISSING — **now** |
| 1.6 | the **rehearsal image** decision (ADR-0050 §2.1 item 1) | whether a `deletion_rehearsal` image is prepared beside the actor images | a written yes/no; the image's only entry is `kalpamani-deletion-rehearsal` | ADR-0050 §2; `production_deletion_rehearsal.tf` | **Decision D-1 (ADR-0049 §3.8 / ADR-0050 §2.11) accepted in writing** | MISSING — D-1 **not taken** |

## 2. Before publication or infrastructure change (S3–S6)

| # | Item | Purpose | Format | Source | Depends on | Accepted value? |
|---|---|---|---|---|---|---|
| 2.1 | **which owner profile pushes images** (owner-inputs D-6) | no declared principal holds push actions | a profile name; a written decision | ADR-0044 §6; readiness §3 | 1.1–1.5 | MISSING — **now** |
| 2.2 | the **registry digests** of every pushed image (`RepoDigests`) | `production_image_digests` and the launch-inputs record | `sha256:<64 hex>` per key: `acquisition`, `build`, optional `acquisition_verify`, `build_verify`, `acquisition_probe`, `build_probe`, `deletion_rehearsal` | `production_variables.tf`; ADR-0045/0048/0050 | the push (S3) | **after S3** |
| 2.3 | `terraform.tfvars`: `production_acquisition_secret_arn`, `production_binding_provenance` (commit / tree / ADR-0024 digest), `identity_center_region`, `production_apply_principal_arn_pattern`, `production_target_account_id` (optional), `production_endpoints_enabled` | stage a refuses without them | as each variable's validation states (ARN grammar; 40/40/64 hex; a Region name; an IAM role ARN pattern) | `production_variables.tf` | 1.2 (the same secret resource); the ADR-0024 environment binding captured | MISSING — **now** |
| 2.4 | `terraform.tfvars`: `production_stage = "a"` | the first apply | `none` → `a`; a separately authorized apply | `production_variables.tf`; readiness §4 | 2.2, 2.3; the written acceptance of the stage-a side effects (owner-inputs D-8) | MISSING — a decision **now**, an apply **later** |
| 2.5 | the **R-3 verification record** and its SHA-256 (`production_r3_verification_digest`) | stage b (the four assignments) is refused without it | `kalpamani-r3-verification-record/v1`, result `VERIFIED`; 64 hex | the R-3 tool (ADR-0046); `production_variables.tf` | stage a applied; one authorized R-3 session | **after S5** |
| 2.6 | the **launch-inputs record** (`kalpamani-launch-inputs/v1`): cluster, execution role, binding key, platform version, per actor the task role, subnet, groups and every registered target's revision ARN, digests, commit and task-definition evidence including the optional **`log_destination`** block | every launch and every collection | the contract's grammar; `log_destination` = `{log_group, stream_prefix, container}` transcribed from the applied task definition | `launch_records.parse_launch_inputs`; ADR-0045 §3; ADR-0049 §2.1 | stage a applied and read back (S4b) | **after S4** |
| 2.7 | the two **production human runtime bindings** and the four **profiles** (human and launcher per actor) | the launch tool's and the permission tool's bootstrap | ADR-0023 private files, owner-only ACL; profile names as the vocabulary fixes them | the materializer (ADR-0046); ADR-0021/0036 | stage b (assignments) | **after S6** |
| 2.8 | the **permission targets** document (`kalpamani-permission-targets/v1`: foundation task role ARN, qualification secret ARN, CONTROL bucket name) | R-4's refused secret, R-4/R-5's refused bucket, R-9 | three values under the private root, `KALPAMANI_PRODUCTION_PERMISSION_TARGETS_FILE` | `permission_cells.parse_permission_targets` | the applied foundation (exists) | MISSING — **now** |
| 2.9 | **Decision D-1** in writing (ADR-0050 §2.11), then `deletion_rehearsal_open = true` and the `deletion_rehearsal` digest in `terraform.tfvars` | the rehearsal resources are declared only under all three gates; the assignment only at stage b | a signed acceptance outside the repository; `true`; `sha256:<64 hex>` | ADR-0050 §2, §4; `production_deletion_rehearsal.tf` | 2.2 (the rehearsal image), 2.4, and for the assignment 2.5 | MISSING — **D-1 not taken**; the variable stays `false` |
| 2.10 | the **rehearsal launch inputs** (`kalpamani-deletion-rehearsal-launch-inputs/v1`: cluster, the rehearsal revision, image digest, execution role, the deletion role, the build subnet, groups, platform version, binding key, the rehearsal `log_destination`) and the **launcher profile** `kalpamani-deletion-rehearse` | `--rehearse-deletion` and `--collect-rehearsal-receipt` | the contract's grammar (family held to `kalpamani-deletion-rehearsal`; role held to `-licensed-data-deletion`; one account) | `deletion_rehearsal_launch.parse_rehearsal_launch_inputs`; ADR-0050 §3.3 | 2.9 applied (stage a for the revision; stage b for the profile to resolve) | **after the rehearsal apply** |
| 2.11 | the **G-14 transition procedure** before any change to the deployed licensed bucket policy | a changed policy is never covered by a prior R-3 digest | a separately reviewed procedure | readiness §4.6, §6 | — | MISSING — deferred; not needed for stage a |
| 2.12 | the **Reachability Analyzer delta** decision and principal (owner-inputs D-14) | R-2 corroboration; without it every non-connection is `INCONCLUSIVE` | a written decision; the four `ec2:*NetworkInsights*` actions declared and applied, or not | ADR-0045 §3 | — | MISSING — **now** (a decision), not required to proceed |

## 3. Before verification launches and collection (S7–S9; the permission subcells; the rehearsal)

| # | Item | Purpose | Format | Source | Depends on | Accepted value? |
|---|---|---|---|---|---|---|
| 3.1 | the **owner ledger** (`kalpamani-owner-ledger/v1`) under the private root | every identity, input and completion | the contract; example `docs/operations/examples/production/owner-ledger.synthetic.json` | `launch_records`; ADR-0045 §7 | — | MISSING — **now** (empty at first) |
| 3.2 | per launch: the **written launch authorization** (`kalpamani-launch-authorization/v1`) naming the printed specification digest (owner-inputs D-15) | the launch tool refuses without it; one per launch, never reused | actor, kind, identity, digest, ≤ 24 h | the launch tool (ADR-0045) | the specification prepared and reviewed | **after each preparation** |
| 3.3 | per verification or negative launch: the **receipt lines** read from the log stream, or a **collection** | `--complete-row` / `--complete-row --collect-receipt` | the receipt line on the shared prefix; or `COLLECT_FLAG` + the launcher profile | ADR-0044 §4; ADR-0049 §2 | a launch record with an observed terminal exit; for a collection the `logs:GetLogEvents` delta applied (**recorded, not granted**) and 2.6's `log_destination` | **after each launch** |
| 3.4 | per permission subcell: one **prepared statement** (its printed digest) and one **authorization** (`kalpamani-permission-authorization/v1`) | `--execute-subcell`; consumed by its one execution | subcell, statement digest, ≤ the stated validity | the permission tool (ADR-0047) | 2.7, 2.8; the R-3 cell; for R-4/R-5 reads the R-4 objects | **after each preparation** |
| 3.5 | the **control principal's cleanup** authorization after each session (`CLEANUP_FLAG`) | settles every created or possibly created object and every started task; confirms absence | one flag per cleanup, under `r3.CONTROL_PROFILE` | the permission tool | the session's records | **after each session** |
| 3.6 | the control principal's `ecs:ListTasks` / `DescribeTasks` / `StopTask` on the cluster (whether its policy already holds them is **not established here**) | discovery and settlement of an unexpected launch; otherwise residue | an IAM check, then a declared delta if absent | ADR-0047 §3.5, §5 — recorded, not granted | — | MISSING — a check **now** |
| 3.7 | the **R-4 human `PutObject` subcell** PASSED under the binding in force | the one rehearsal target (the synthetic marker's content address) | its permission record MATCHED, bound, unsettled | `deletion_rehearsal.rehearsal_target`; ADR-0049 §3.5 | 3.4 | **after that subcell** |
| 3.8 | per R-8 subcell: one **rehearsal statement** (`--prepare-rehearsal`, its printed digest) and one **authorization** naming it; `R8-GET` first, `R8-LIST-AND-DELETE` only after `R8-GET` is recorded PASS | `--rehearse-deletion`; consumed durably before any mutation | `kalpamani-deletion-rehearsal-statement/v1`; the same authorization contract | ADR-0050 §3.5; `production_deletion_rehearsal_tool.py` | **D-1 accepted (2.9) and `REHEARSAL_PATH_OPEN` set in a merged pull request**; 2.10; 3.7 | **after 2.9 and 3.7** |
| 3.9 | per rehearsal launch: the **receipt line** (hand-read from `production-deletion-rehearsal/deletion-rehearsal/<task id>`, or collected under the rehearsal launcher) | `--complete-rehearsal --receipt-lines` / `--collect-rehearsal-receipt` | `kalpamani-deletion-rehearsal-receipt/v1` on the shared prefix | ADR-0050 §3.2; the collector | a rehearsal launch record with an observed exit | **after each rehearsal launch** |
| 3.10 | per interrupted rehearsal launch (a reservation beside the ledger with no resolution): the **offline recovery** (`--recover-rehearsal-launch <subcell>`), then the control principal's verified cleanup that settles it | every launch is refused (exit 21) while a reservation is unsettled, whatever the records directory or authorization | no input — the reservation retains the specification and attribution | ADR-0050 §8.1 | the interrupted launch | **only after an interruption** |
| 3.11 | the **R-2 reachability evidence** (`kalpamani-reachability-evidence/v1`, owner-inputs D-16), if a verdict other than `INCONCLUSIVE` is wanted | `--isolation-verdict` | the contract's fields, transcribed from one analysis | ADR-0045 §3 | 2.12; the build bootstrap cell PASSED | **after S9 (build)**, optional |

## 4. Before the first production acquisition and build (S10)

| # | Item | Purpose | Format | Source | Depends on | Accepted value? |
|---|---|---|---|---|---|---|
| 4.1 | the **first bounded acquisition scope** (owner-inputs D-2): `acquisition_mode`, datasets, windows, ≤ 96 requests, response ceiling | the acquisition slice → the plan digest | the slice document; ADR-0035 §5.2 I-8 | `plan.py`; `inputs.py` | — | MISSING — **now** (a decision) |
| 4.2 | per run: the **acquisition input v2** (identity, slice, plan digest, spent identities from the ledger, ≤ 24 h) | `/kalpamani/production/acquisition/input`, create-only, by the acquisition human set | example `acquisition-input.v2.synthetic.json` | ADR-0044 §2; `inputs.py` | 3.1, 4.1, every earlier cell VERIFIED as readiness §3 requires | **after the verification cells** |
| 4.3 | per build: the **build input v2** (ADR-0055 — build identity, ≤ 32 completed `RECEIPT_VERIFIED` production runs each bound by the SHA-256 of its admitted locator, ledger digest, ≤ 24 h, ≤ 8 KiB enforced at materialization) | `/kalpamani/production/research-build/input` | example `build-input.v2.synthetic.json` (v1 retained as historical evidence only) | ADR-0040, ADR-0055; `inputs.py` | 4.2 completed and its row `RECEIPT_VERIFIED` | **after the first acquisition** |
| 4.4 | Route B: the observation build's refusal receipt **and** the per-dataset acceptance record; Route A: the attribution worksheet | the Silver-producing image's `accepted_schemas` | owner-inputs E-10 | ADR-0042; readiness §4.2 item 6 | 1.4's route | **after S10b** (Route B) / owner-held (Route A) |
| 4.5 | the **written run authorization** per acquisition and per build (readiness §3) | each is its own gate | one record per run, never reused | ADR-0045 §7 | everything above | **after each preparation** |
| 4.6 | **the bounded provider-qualification cycle for the pagination-v2 limit `L` and the payload/parser/memory ceilings** (ADR-0053 §3, §8; accepted on the merge of PR #129, 2026-09-18) — before the constants code cycle, the O-5 recompilation and the whole-run replacement of acquisition run 1 (historical, not buildable: every tickers/actions page full at 10,000 rows; 2,147 rows re-served across two tickers offsets); run 2's specification superseded and preserved; S10c blocked | the qualified limit `L` and the byte/row/memory ceilings → the constants code cycle → every recompiled plan digest | one qualification record per candidate (row counts, sizes, digests, parser time, peak memory, task resources, licence, safety margin) | owner-inputs D-18 / D-19 / D-20 / D-21; ADR-0053 §11–§13 | 4.1, 4.5 | **D-19 `PROVIDER_REFUSED`; D-20 `DUPLICATE_PRIMARY_KEY`; D-21 `QUALIFIED_AT_L_100000` — the envelope accepted as implementation targets (ADR-0053 §13); NOT deployed** |

## What is decided, and what is not

- **Decided in writing and in force**: D-10 (ADR-0045), the reading of R-4's cleanup clause (ADR-0047 §6.3),
  the collector (ADR-0049), the permission-probe mechanisms (ADR-0048).
- **Presented and not taken**: **Decision D-1** (ADR-0049 §3.8, made concrete by ADR-0050 §2 — accepted on the merge of PR #109, which took the decision no more than its text does).
- **MISSING, suppliable now**: 1.1, 1.2, 1.3, 1.5, 2.1, 2.3, 2.8, 3.1 and the decisions of 1.4, 2.4, 2.12,
  3.6, 4.1.
- **Obtainable only after a runtime step**: 2.2 (S3), 2.5 (S5), 2.6 (S4), 2.7 (S6), 2.10 (the rehearsal
  apply), 3.2–3.5, 3.7–3.11, 4.2–4.5 — each after the step its row names.
- **Recorded and not granted**: `logs:GetLogEvents` for the actor launcher sets (ADR-0049 §2.6), the
  control principal's ECS actions (ADR-0047 §5), the Reachability Analyzer delta (ADR-0045 §3), and —
  declared inert behind D-1 — every rehearsal permission (ADR-0050 §2.2).

**G2 OPEN · CONTROL DEFERRED · Phase 3 NOT COMPLETE · live trading HARD-DISABLED.**
