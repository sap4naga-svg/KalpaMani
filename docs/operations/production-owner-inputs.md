# Production owner inputs — the one checklist

**Every value below is the owner's, lives outside this repository, and is `MISSING` as of this
record.** Nothing here is a template to fill in inside Git: the private values go to the places named
in the *where* column and nowhere else. The synthetic examples under
[`examples/production/`](examples/production/README.md) show each document's **shape**; their values
are the test suite's and are never production inputs. Traceability, validation rules and consumers are
in [`production-readiness.md`](production-readiness.md) §2; this list is the short form.

**Never supplied to this repository, an AI session or a pull request:** a secret value, an API key, an
account id, an ARN, a bucket name, a private path, a run identity, a vendor row.

## A. Decisions (written, one per line, before anything is generated)

| # | Decision | Needed by |
|---|---|---|
| D-1 | the **release commit** on `main` the images are built from (full 40 hex; a clean checkout) | S1 |
| D-2 | the **first bounded acquisition scope** (ADR-0035 §5.2 I-8): `acquisition_mode`, datasets, windows, request count ≤ 96, response ceiling ≤ 16 MiB — one run | S10a |
| D-3 | the **`breakout-long-v1` rule parameters** (ADR-0035 §5.2 I-9): decision margin, `history_sessions`, ADDV window, price floor, ADDV floor, eligible exchanges, common-stock categories | S1 (build) |
| D-4 | the **decision sessions**, **as-of instant**, and any override of `jump_ratio` / `reconciliation_tolerance` for the first build | S1 (build) |
| D-5 | the **exchange-calendar source and version** the build calendar is taken from (no real calendar exists in the repository) | S1 (build) |
| D-6 | **which owner profile pushes images** to the research repository (no declared principal holds push actions) | S3 |
| D-7 | the **platform version** to pin at launch (`LATEST` is refused; AWS documents `1.4.0` as the current Linux platform version) | S9 |
| D-8 | acceptance in writing of the **stage-a side effects**: the shared public-route S3 gateway policy, the licensed bucket-policy statements, the KMS key's monthly charge and the endpoints' hourly charge when toggled | S4 |
| D-9 | for R-5: whether the exact-read cells run against **synthetic objects written for the purpose** or after the first acquisition | S8 |
| D-10 | the resolution of the **verification-only path** (readiness §3.2, §8) — an ADR decision, before R-1/R-2. **Proposed as ADR-0045 in the verification-and-launch pull request** (readiness §9): the decision is yours on its independent review and merge; until then it carries no authority. **Decided: PR #104 merged 2026-09-14, ADR-0045 ACCEPTED / IN FORCE** — the path exists; running it stays separately authorized | S9 |
| D-11 | the **schema-digest route for the first build** (readiness §4.2 item 6): **Route A** — attribute the private combined report's `observed_schema_digests` to datasets by an offline digest-equality check against documented headers (no private payload read; complete documented column list exists for `actions` only), compiling only what is attributed; or **Route B** — an observation build with an explicitly empty accepted set, which needs its ADR accepted and implemented first, and whose reported digests are **evidence for your review**: you accept, per dataset, the digests a later configuration may admit. Never a fixture set, never a guessed digest, never an automatic promotion | S1 (build) |
| D-12 | acceptance that every ordinary rotation after stage b keeps `production_stage = "b"` and the R-3 digest with the verified controls unchanged, and that assignment removal is a separate governed decision (readiness §4.6) | every rotation |
| D-13 | before any change to the deployed licensed bucket policy: a **separately reviewed transition procedure** (prevent production use → deploy → re-verify → clean up → restore); a prior R-3 digest does not attest to a changed policy, and this PR neither defines nor authorizes the procedure (readiness §4.6, G-14) | any bucket-policy change |
| D-14 | whether to **declare the Reachability Analyzer permission delta** (`ec2:CreateNetworkInsightsPath`, `ec2:StartNetworkInsightsAnalysis`, `ec2:DescribeNetworkInsights*`, `ec2:DeleteNetworkInsights*`) for the principal that corroborates R-2, and under which principal — ADR-0045 §3 (accepted) admits that analysis as the only corroboration and **grants nothing**; without it every R-2 non-connection stays `INCONCLUSIVE`; each analysis is charged | S9 (build) |
| D-15 | per launch, the **written authorization record** (`kalpamani-launch-authorization/v1`: actor, kind, identity, **the launch specification's digest**, ≤ 24 h) the launch tool requires beside its flag — one record per launch, never reused; the digest is the one the tool prints when run without its flag, over the specification it writes for your review (workload, registered target, placement, gate-evidence references) (example: `examples/production/launch-authorization.synthetic.json`) | S9, S10 |
| D-16 | per R-2 cell, whether to **transcribe a Reachability Analyzer analysis** (`kalpamani-reachability-evidence/v1`: analysis and path ids, status, `networkPathFound`, `startDate`, the path's source interface, destination IP, port and protocol, and each explanation's code and component) for the launch tool's `--isolation-verdict`; without one the verdict is `INCONCLUSIVE` and is recorded as such | S9 (build) |

## B. Values held outside the repository

| # | Value | Where it goes | Constraint |
|---|---|---|---|
| V-1 | the **production Sharadar secret** — created by the owner in Secrets Manager (this repository creates none); its **name** | the acquisition owner-inputs file (`secret_name`) → image | a name in the documented grammar; never an ARN, never the value; a different resource from the qualification secret |
| V-2 | that secret's **ARN** | `terraform.tfvars` → `production_acquisition_secret_arn` | must be the same resource as V-1 |
| V-3 | the **provider origin's resolved IPv4 addresses** | the acquisition owner-inputs file (`origin_addresses`) **and** `terraform.tfvars` → `production_provider_origin_cidrs` | the two sets kept equal; refreshed before each run window; a change is an image rebuild + register + apply |
| V-4 | the **build configuration** document | the build owner-inputs file (`build_configuration`) → image | the accepted `BuildConfiguration.document()` shape; `accepted_schemas` per D-11 — Route A attributed digests, or Route B's explicitly empty set for the observation image (example: `examples/production/build-inputs.observation.synthetic.json`); a Silver-producing image exists only once attributed digests are compiled |
| V-5 | `BASE_IMAGE_DIGEST` — the linux/amd64 image-manifest digest of `python:3.11-slim` | the build command (`--build-arg`) and the build record | the platform image's digest, never the index's |
| V-6 | the **registry digests** of the published images (`RepoDigests`) — the two production images, and under ADR-0045 (accepted) the two verification images (keys `acquisition_verify`, `build_verify`) | `terraform.tfvars` → `production_image_digests`; the launch-inputs record | never a local image id; a verification key declares that actor's verification family and adds one `RunTask` resource to its launcher |
| V-7 | `production_binding_provenance` (implementation commit, tree, ADR-0024 environment-binding digest) | `terraform.tfvars` | 40 / 40 / 64 hex |
| V-8 | `identity_center_region` | `terraform.tfvars` | the Identity Center instance's Region, not `aws_region` |
| V-9 | `production_apply_principal_arn_pattern` | `terraform.tfvars` | must match the real apply role (the administrator binding; KMS refuses a lockout) |
| V-10 | `production_target_account_id` (optional) | `terraform.tfvars` | leave unset to inherit the qualification target; if set, equal to the provider's account and the qualification target |
| V-11 | the **R-3 verification record** and its SHA-256 | the owner's evidence; `terraform.tfvars` → `production_r3_verification_digest` | supplied only for a record that says *verified*; **kept in `terraform.tfvars` for every later apply** — removing it or moving the stage back to `a` destroys the assignments (readiness §4.6) |
| V-12 | the two **production human runtime bindings** (acquisition, build) | private files under the ADR-0023 root, selected by `KALPAMANI_PRODUCTION_ACQUISITION_RUNTIME_BINDING_FILE` / `KALPAMANI_RESEARCH_BUILD_RUNTIME_BINDING_FILE` | owner-only ACL; **no materializer exists yet** (readiness G-4) — the launch tool loads them through the accepted reader and does not write them |
| V-13 | the **owner ledger** (`kalpamani-owner-ledger/v1`): every identity ever launched, production or verification, with kind, outcome and evidence | owner-private, **under the ADR-0023 private root** (the launch tool refuses a ledger elsewhere) | the source of every input's `run_identity`, `spent_identities` and `runs[]`; under ADR-0045 (accepted) the launch tool cuts both inputs from it, appends a provisional row per launch and completes the row from a verified receipt (example: `examples/production/owner-ledger.synthetic.json`); a `verify-` identity is a verification launch's and never a production one's |
| V-14 | per run: the **acquisition input v2** (identity, slice, plan digest, spent identities, ≤ 24 h validity) | SSM `/kalpamani/production/acquisition/input`, create-only, by the acquisition human set | example: `examples/production/acquisition-input.v2.synthetic.json`; materialized by the launch tool from V-13 and a slice document, and re-parsed under the task's contract before it is written |
| V-15 | per build: the **build input v1** (build identity, ≤ 32 completed ledger rows, ledger digest, ≤ 24 h) | SSM `/kalpamani/production/research-build/input`, create-only, by the build human set | example: `examples/production/build-input.v1.synthetic.json`; only `RECEIPT_VERIFIED` `COMPLETED` production acquisition rows are buildable |
| V-16 | per launch: the **launch-inputs record** (`kalpamani-launch-inputs/v1`: cluster, execution role, binding key, platform version, the R-3 verification digest or null; per actor the task role, subnet, security groups, and the registered production and verification targets — revision ARN, image digest, configuration digest, code commit, the generation record's SHA-256, and the **task-definition evidence** transcribed from the post-apply verification: family, revision, roles, cpu, memory, network mode, platform, `user`, read-only root, `/work` tmpfs, command, image digest) | owner-private, transcribed from Terraform outputs, the generation records and the post-apply verification | the launch tool compiles `CompiledLaunch` from it and from nothing typed, binds every configuration file to its registered target, and compares the two task definitions field by field before a verification launch; **the transcription is yours and is validated offline only** — the launcher permission sets hold no `ecs:DescribeTaskDefinition`, so no read-back exists (recorded dependency, not added); **not exemplified** (it carries ARNs) — its field set is `launch_records.parse_launch_inputs` |
| V-17 | the two **launcher profiles** — `kalpamani-production-acquisition-launcher`, `kalpamani-research-build-launcher` — beside the two human profiles | the owner's AWS configuration (S7) | each resolves to its actor's launcher permission-set role; a profile name is routing input, never proof (ADR-0021) |
| V-18 | per launch: the **launch specification** (`kalpamani-launch-specification/v1`, written by preparation for your review), the **reservation** (`kalpamani-launch-reservation/v1`, written before any client at `<ledger>.reservations/<identity>.json`, carrying the specification, never deleted), the **launch record** (`kalpamani-launch-record/v1`: task ARN, revision, digests, commit, identity, input digest, the acquisition slice, the launch and record instants, the verified interface, subnet and security groups, the specification digest) and the sanitized evidence document | owner-private, under the private root; the reservation and the lock beside the ledger, the specification, records and evidence in the `--records-dir` you name (an evidence destination only — naming another one neither hides pending recovery nor frees an identity); record names carry the instant and eight random hex digits and are never overwritten | the record is what the receipt line is verified against (`--complete-row`) and what the R-2 verdict binds to (`--isolation-verdict`), each after the record is bound to its reservation; an interrupted attempt leaves its reservation and is recorded by `--recover` from any records directory, which launches nothing; a reservation is never removed; a `reservations` directory left under a records directory by the first revision refuses until you move its files beside the ledger by hand (the tool moves nothing); a stale `ledger.json.lock` from a crashed process is yours to inspect and remove after confirming no tool process runs; none of it is exported or enters a pull request |

## C. Evidence the owner records after each gate

| # | Evidence | From |
|---|---|---|
| E-1 | `generation-record.json` per entry (commit, tree, `configuration_digest`, byte count) | S1 |
| E-2 | `context-manifest.json` per entry, and the step-6 local-verification results | S2 |
| E-3 | the registry digests and the push record | S3 |
| E-4 | the reviewed saved plan, the apply output, the independent post-apply verification, S4a/S4b results | S4 |
| E-5 | the R-3 record: nine classified rows, counts, cleanup disposition — never the error message text | S5 |
| E-6 | the four profile preflights and the two human-bootstrap outcomes | S7 |
| E-7 | per cell: simulated / verified / not exercised | S8 |
| E-8 | per task: the launch record, the receipt line, the `binding_digest` comparison, the ledger row — provisional (`EXIT_CODE_ONLY`) from the launch tool, completed (`RECEIPT_VERIFIED`) by `--complete-row` from the receipt line you read from the log stream by hand until a collector exists; a count not read is not zero | S9, S10 |
| E-9 | per rotation: the reviewed plan showing new revision(s) and launcher policy update(s) and **no assignment change**; the unchanged R-3 digest | every rotation |
| E-10 | Route B: the observation build's refusal receipt (per-dataset digests, zero writes) **and your explicit per-dataset acceptance record** — the receipt is evidence, the acceptance is the decision; Route A: the attribution worksheet (documented header → `schema_digest_of` → equality with an observed digest, per dataset) | S10b / S1 |
| E-11 | R-2: the probe's observed result, attempt count and keyed destination digest from the receipt, **and separately** the isolation verdict record the launch tool derives (`--isolation-verdict`: `FAILED` on `CONNECTED`; otherwise `INCONCLUSIVE` with its closed reason, or `VERIFIED` only from a transcribed analysis bound to this task's interface, destination and window with an admitted blocking explanation inside the placement) | S9 (build) |

## D. The consolidated checklist for the next runtime milestone (after the tooling cycle, proposed ADR-0046)

Refreshed with the verification-tooling cycle. Four kinds, kept apart; nothing here is a value to
type into this repository, and none of it was supplied to finish the offline work.

### D.1 Values the owner must supply (still MISSING)

| Value | Where it goes | Consumed by |
|---|---|---|
| the ADR-0024 environment binding (account, licensed bucket) — already capturable by the qualification capture | `KALPAMANI_QUALIFICATION_ENVIRONMENT_BINDING_FILE`, under the private root | the materializer (source), the R-3 tool (bucket, binding digest), the cell runner (R-3 attestation) |
| the two production human-binding destinations | `KALPAMANI_PRODUCTION_ACQUISITION_RUNTIME_BINDING_FILE`, `KALPAMANI_RESEARCH_BUILD_RUNTIME_BINDING_FILE` | the materializer (destination), the launch tool (bootstrap) |
| the R-3 record directory | `KALPAMANI_PRODUCTION_R3_RECORD_DIR`, under the private root | the R-3 tool |
| every S0 value of §A/§B: the secret, the origin address set, the release commit, the tfvars values, the ledger, the launch-inputs record, the slice / run identities, one authorization record per cell naming its specification digest | as §A/§B state | the launch tool through the cell runner |

### D.2 Evidence that can only exist after an earlier runtime step

| Evidence | Exists only after | Then consumed by |
|---|---|---|
| the R-3 record (`kalpamani-r3-verification-record/v1`), result `VERIFIED`, attesting to the current `storage.tf` and binding | S4 (stage a applied) and one authorized R-3 session | S5a (`production_r3_verification_digest`), S6, the cell runner's `R3` cell |
| the four profile preflights and both human bindings | S6 (stage b) and S7 | the launch tool's bootstrap; the cell runner |
| a `VERIFIED` ledger row with `RECEIPT_VERIFIED` evidence per bootstrap cell, its reservation and launch record bound to the prepared specification and to the inputs now registered | one authorized launch per cell, the owner's receipt lines; a later change to the registered target or placement makes the row `HISTORICAL` and requires re-verification (ADR-0045 §7) | `R1-*-BOOTSTRAP` PASSED; the verdict cell |
| the isolation verdict record | the build bootstrap cell PASSED and one transcribed analysis (D-16); an `INCONCLUSIVE` verdict is re-evaluated for the same launch with a later qualifying transcription — no relaunch | `R2-BLD-ISOLATION` |
| Route B observation receipts, the first production Bronze, the first manifest | S10a–S10c | later gates, unchanged |

### D.3 Permissions still requiring a decision (recorded, not granted)

| Permission | For | Recorded in |
|---|---|---|
| `ec2:CreateNetworkInsightsPath`, `ec2:StartNetworkInsightsAnalysis`, `ec2:DescribeNetworkInsights*`, `ec2:DeleteNetworkInsights*` | the principal that corroborates R-2 | D-14; ADR-0045 §3 |
| `ecs:DescribeTaskDefinition` | live read-back of the task-definition evidence (the launcher sets do not hold it; the evidence is the owner's transcription) | V-16; ADR-0045 §6 |
| `logs:GetLogEvents` | the deferred receipt collector | ADR-0044 §5 |
| the G-14 bucket-policy transition procedure | a changed deployed policy | readiness §4.6, §6 — deferred |

### D.4 Code gaps remaining after this cycle

| Gap | What is missing | Decision needed |
|---|---|---|
| the negative R-1 cells (`NO-RELEASE`, `RELEASE-MISMATCH`) | a launch mode that withholds or mis-names the release for one launch; the accepted launch tool has none | ADR-0046 §4 — a later proposed ADR; until then the cells are `BLOCKED` and the matrix aggregate cannot be `VERIFIED` |
| R-4 … R-9 orchestration | an L2 `SimulatePrincipalPolicy` runner and L3 per-cell live requests under each principal with synthetic objects and deletion-role cleanup; the cell runner enumerates these cells and does not execute them | a later cycle; the owner runs them per readiness S8 meanwhile |
| the receipt collector | ADR-0044 §5, deferred; receipts are hand-read | unchanged |
| G-14 | the bucket-policy transition procedure | deferred |
