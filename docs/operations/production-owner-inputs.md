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
| D-10 | the resolution of the **verification-only path** (readiness §3.2, §8) — an ADR decision, before R-1/R-2 | S9 |
| D-11 | the **schema-digest route for the first build** (readiness §4.2 item 6): **Route A** — attribute the private combined report's `observed_schema_digests` to datasets by an offline digest-equality check against documented headers (no private payload read; complete documented column list exists for `actions` only), compiling only what is attributed; or **Route B** — an observation build with an explicitly empty accepted set, which needs its ADR accepted and implemented first. Never a fixture set, never a guessed digest | S1 (build) |
| D-12 | acceptance that every apply after stage b keeps `production_stage = "b"` and the R-3 digest, and that assignment removal is a separate governed decision (readiness §4.6) | every rotation |

## B. Values held outside the repository

| # | Value | Where it goes | Constraint |
|---|---|---|---|
| V-1 | the **production Sharadar secret** — created by the owner in Secrets Manager (this repository creates none); its **name** | the acquisition owner-inputs file (`secret_name`) → image | a name in the documented grammar; never an ARN, never the value; a different resource from the qualification secret |
| V-2 | that secret's **ARN** | `terraform.tfvars` → `production_acquisition_secret_arn` | must be the same resource as V-1 |
| V-3 | the **provider origin's resolved IPv4 addresses** | the acquisition owner-inputs file (`origin_addresses`) **and** `terraform.tfvars` → `production_provider_origin_cidrs` | the two sets kept equal; refreshed before each run window; a change is an image rebuild + register + apply |
| V-4 | the **build configuration** document | the build owner-inputs file (`build_configuration`) → image | the accepted `BuildConfiguration.document()` shape; `accepted_schemas` per D-11 — Route A attributed digests, or Route B's explicitly empty set for the observation image (example: `examples/production/build-inputs.observation.synthetic.json`); a Silver-producing image exists only once attributed digests are compiled |
| V-5 | `BASE_IMAGE_DIGEST` — the linux/amd64 image-manifest digest of `python:3.11-slim` | the build command (`--build-arg`) and the build record | the platform image's digest, never the index's |
| V-6 | the **registry digests** of both published images (`RepoDigests`) | `terraform.tfvars` → `production_image_digests`; the launch record | never a local image id |
| V-7 | `production_binding_provenance` (implementation commit, tree, ADR-0024 environment-binding digest) | `terraform.tfvars` | 40 / 40 / 64 hex |
| V-8 | `identity_center_region` | `terraform.tfvars` | the Identity Center instance's Region, not `aws_region` |
| V-9 | `production_apply_principal_arn_pattern` | `terraform.tfvars` | must match the real apply role (the administrator binding; KMS refuses a lockout) |
| V-10 | `production_target_account_id` (optional) | `terraform.tfvars` | leave unset to inherit the qualification target; if set, equal to the provider's account and the qualification target |
| V-11 | the **R-3 verification record** and its SHA-256 | the owner's evidence; `terraform.tfvars` → `production_r3_verification_digest` | supplied only for a record that says *verified*; **kept in `terraform.tfvars` for every later apply** — removing it or moving the stage back to `a` destroys the assignments (readiness §4.6) |
| V-12 | the two **production human runtime bindings** (acquisition, build) | private files under the ADR-0023 root, selected by `KALPAMANI_PRODUCTION_ACQUISITION_RUNTIME_BINDING_FILE` / `KALPAMANI_RESEARCH_BUILD_RUNTIME_BINDING_FILE` | owner-only ACL; **no materializer exists yet** (readiness G-4) |
| V-13 | the **owner ledger**: allocated run and build identities, spent identities, completed rows | owner-private | the source of every input's `run_identity`, `spent_identities` and `runs[]`; **no tool cuts an input from it yet** (readiness G-3) |
| V-14 | per run: the **acquisition input v2** (identity, slice, plan digest, spent identities, ≤ 24 h validity) | SSM `/kalpamani/production/acquisition/input`, create-only, by the acquisition human set | example: `examples/production/acquisition-input.v2.synthetic.json` |
| V-15 | per build: the **build input v1** (build identity, ≤ 32 completed ledger rows, ledger digest, ≤ 24 h) | SSM `/kalpamani/production/research-build/input`, create-only, by the build human set | example: `examples/production/build-input.v1.synthetic.json` |
| V-16 | per launch: the **`CompiledLaunch` values** (cluster, revision ARN, registry digest, configuration digest, task and execution role ARNs, subnet, security groups, public-IP setting, platform version, key ARN) | the launch tool's record, from Terraform state/outputs | **no launch tool exists yet** (readiness G-2) |

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
| E-8 | per task: the launch record, the receipt line, the `binding_digest` comparison, the ledger row (hand-completed until a collector exists — a count not read is not zero) | S9, S10 |
| E-9 | per rotation: the reviewed plan showing new revision(s) and launcher policy update(s) and **no assignment change**; the unchanged R-3 digest | every rotation |
| E-10 | Route B: the observation build's refusal receipt (per-dataset digests, zero writes); Route A: the attribution worksheet (documented header → `schema_digest_of` → equality with an observed digest, per dataset) | S10b / S1 |
