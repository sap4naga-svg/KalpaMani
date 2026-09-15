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

## D. The consolidated checklist for the next runtime milestone (after the coverage cycle, proposed ADR-0047)

Refreshed with the coverage cycle (ADR-0046 accepted on the merge of PR #105; ADR-0047 proposed).
Three kinds, kept apart; nothing here is a value to type into this repository, and none of it was
supplied to finish the offline work. **Every value stays MISSING; no permission is granted; no
deferred owner decision is resolved by assumption.**

### D.1 Values required before packaging

| Value | Where it goes | Consumed by |
|---|---|---|
| every S0 value of §A/§B: the production secret's **name** (in the compiled acquisition configuration), the origin address set, the release commit, the `tfvars` values, the ledger, the launch-inputs record, the slice / run identities | as §A/§B state | the compiled-configuration generator, the image build, the launch tool |
| the ADR-0024 environment binding (account, licensed bucket) — already capturable by the qualification capture | `KALPAMANI_QUALIFICATION_ENVIRONMENT_BINDING_FILE`, under the private root | the materializer (source), the R-3 tool, the permission tool, the cell runner |
| the two production human-binding destinations | `KALPAMANI_PRODUCTION_ACQUISITION_RUNTIME_BINDING_FILE`, `KALPAMANI_RESEARCH_BUILD_RUNTIME_BINDING_FILE` | the materializer (destination), the launch tool and the permission tool (bootstrap) |
| the R-3 record directory | `KALPAMANI_PRODUCTION_R3_RECORD_DIR`, under the private root | the R-3 tool |
| the **permission targets** document (`kalpamani-permission-targets/v1`: the foundation task role ARN, the qualification secret ARN, the CONTROL bucket name — three values no accepted binding carries) | `KALPAMANI_PRODUCTION_PERMISSION_TARGETS_FILE`, under the private root | the permission tool (R-4's refused secret, R-4/R-5's refused bucket, R-9) |
| one authorization record per cell naming its prepared specification digest — the negative cells' digests cover their release mode | `--authorization` per execution | the cell runner, the launch tool |
| one authorization per permission subcell (`kalpamani-permission-authorization/v1`) naming the prepared statement's digest — consumed by its one execution | `--authorization` per `--execute-subcell` | the permission tool |

### D.2 Decisions or permissions required before cloud verification (recorded, not granted, not resolved)

| Decision or permission | For | Recorded in |
|---|---|---|
| the **permission-probe families and launcher resources** proposed by ADR-0048 (two families under the actors' task roles, one more exact `ecs:RunTask` resource per launcher, two image digests) — a Terraform apply, separately authorized after ADR-0048's acceptance | the 32 task-role subcells of R-4 and R-5 and the 2 R-6 `ExecuteCommand` subcells — executable offline since ADR-0048, `UNEXECUTED` until a probe is launched; a human role is never a substitute | ADR-0048 §2, §3, §5 |
| the **deletion rehearsal path** (a rehearsal family under the deletion role, a rehearsal launcher passing exactly that role to ECS, the role's two bootstrap parameters) — reverses ADR-0007's verified inert property | the 2 R-8 subcells — until that decision `BLOCKED` | ADR-0048 §4 — designed, not opened |
| `ecs:ListTasks`, `ecs:DescribeTasks`, `ecs:StopTask` on the governed cluster for the **control principal** (whether its identity policy already holds them is not established here) | the cleanup's discovery and settlement of an unexpected or ambiguous launch — until then a `failed` discovery is residue | ADR-0047 §3.5, §5 — recorded, not granted |
| an **owner attestation** for an ambiguous launch whose task is never discovered | the subcell stays `CLEANUP_UNRESOLVED` (discovery exhaustion is never proof of absence) | ADR-0047 §3.5, §5 — not implemented, not decided |
| **discovery of a task that stopped early and aged out of the `startedBy` listing** (a `ListTasks` by `startedBy` admits no status filter; a documented request under another filter, or an attestation, would be a later decision) | such a launch stays `CLEANUP_UNRESOLVED` | ADR-0047 §3.5, §5 — limitation recorded, not implemented, not decided |
| an **execution path for the deletion role** (a deletion task definition, or a runbook step under a separately authorized principal) | the 2 R-8 subcells — until then `BLOCKED` | ADR-0047 §5; ADR-0007 |
| the reading of ADR-0036 R-4's *"deleted by the deletion role afterwards"* as cleanup by the control principal | the R-4 / R-5 synthetic objects | ADR-0047 §6.3 — decided by its acceptance |
| `ec2:CreateNetworkInsightsPath`, `ec2:StartNetworkInsightsAnalysis`, `ec2:DescribeNetworkInsights*`, `ec2:DeleteNetworkInsights*` | the principal that corroborates R-2 | D-14; ADR-0045 §3 |
| `ecs:DescribeTaskDefinition` | live read-back of the task-definition evidence | V-16; ADR-0045 §6 |
| `logs:GetLogEvents` for each **launcher permission set** on exactly its own families' streams (`…:log-group:/kalpamani/<name_prefix>/research:log-stream:production-<container>/<container>/*`; no `FilterLogEvents`, no `DescribeLogStreams`) — the receipt collector is implemented offline; until the delta is applied every collection answers `DENIED` after one request and receipts stay hand-read | `--complete-row --collect-receipt`, `--collect-receipt <subcell>` | proposed ADR-0049 §2.6 — recorded, not granted |
| the registered **`log_destination`** of every applied revision (`log_group`, `stream_prefix`, `container`, transcribed from the applied task definition into the launch-inputs task-definition evidence) — without it the collector refuses | every collection | proposed ADR-0049 §2.1 — a value, MISSING |
| **Decision D-1 — open the deletion rehearsal path** (the family, launcher and three parameters of ADR-0049 §3.2; the deletion role's `ssm:GetParameter` / `kms:Decrypt` bootstrap delta of §3.3; `REHEARSAL_PATH_OPEN` flipped; R-8 to an executable layer) — reverses ADR-0007's verified inert property | the 2 R-8 subcells — until then `BLOCKED`; the path is implemented offline and CLOSED | proposed ADR-0049 §3.8 — presented, not taken |
| the G-14 bucket-policy transition procedure | a changed deployed policy | readiness §4.6, §6 — deferred |
| stage a and stage b applies, the R-3 session, each launch, each permission subcell and the cleanup | every runtime step | each its own written authorization (readiness §3) |

### D.3 Evidence obtainable only after the relevant runtime step

| Evidence | Exists only after | Then consumed by |
|---|---|---|
| the R-3 record (`kalpamani-r3-verification-record/v1`), result `VERIFIED`, attesting to the current `storage.tf` and binding | S4 (stage a applied) and one authorized R-3 session | S5a (`r3_verification_digest`), S6, the cell runner's `R3` cell |
| the four profile preflights and both human bindings | S6 (stage b) and S7 | the launch tool's bootstrap; the cell runner; the permission tool |
| a `VERIFIED` ledger row with `RECEIPT_VERIFIED` evidence per bootstrap cell, its reservation and launch record bound to the prepared specification and to the inputs now registered | one authorized launch per cell, the owner's receipt lines; a later change to the registered target or placement makes the row `HISTORICAL` (ADR-0045 §7) | `R1-*-BOOTSTRAP` PASSED; the verdict cell; R-6's evidenced positives |
| a `REFUSED` ledger row with `RECEIPT_VERIFIED` evidence per negative cell, its launch record carrying the mode and the observed exit code, and its negative-evidence record | one authorized negative launch per cell (four in all), the owner's receipt lines | `R1-*-NO-RELEASE`, `R1-*-RELEASE-MISMATCH` PASSED |
| the isolation verdict record | the build bootstrap cell PASSED and one transcribed analysis (D-16); an `INCONCLUSIVE` verdict is re-evaluated for the same launch — no relaunch | `R2-BLD-ISOLATION` |
| one prepared statement, one consumed authorization (its consumption record beside the ledger), one attempt and one permission record per executable subcell (56), each under its principal and bound as one chain to the context in force (environment binding, declarations, registration, **targets document**), and one cleanup record settling every created or possibly created object and every started or possibly started task by attempt identity — a launch only by termination evidence | one authorized invocation per subcell and one authorized cleanup, after the R-3 cell and (for R-4/R-5 reads) the creating subcells | `R6-LAUNCHERS`, `R7-QUALIFICATION`, `R9-FOUNDATION-TASK` PASSED; R-4 and R-5's human subcells (the cells stay `BLOCKED` on D.2) |
| Route B observation receipts, the first production Bronze, the first manifest | S10a–S10c | later gates, unchanged |

**What the coverage cycle closed, and what it left.** The withheld-release launch mode and the negative
R-1 cells, and the R-4 … R-9 orchestration, are no longer code gaps: both are implemented offline and
proposed by ADR-0047 and accepted on the merge of PR #106. Since the mechanisms cycle (ADR-0048,
accepted on the merge of PR #107) the task-side permission probe entry and the held `ExecuteCommand`
check exist as offline code (34 subcells executable, none executed). Since the collection-and-rehearsal
cycle (proposed ADR-0049) the receipt collector exists as offline code behind its own flag and the
un-granted `logs:GetLogEvents` delta, and the deletion role's execution path exists as offline code
**CLOSED** behind Decision D-1 (D.2, blocking 2 subcells). Still absent: the G-14 transition procedure
(deferred).
