# Production readiness — finding dispositions (PR #103 correction cycle, 2026-09-14)

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
(64-hex digests; no key, row, identifier or subject). Affected: ADR-0044 §4 (the receipt's closed field
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

**Evidence that survives, and what renews it (from accepted contracts).** R-3 is evidence about the
licensed bucket policy and is invalidated only by a change to the `storage.tf` statements it verified;
image rotation does not touch it. The compiled configuration, image digest and revision are bound per
launch by the release (ADR-0044 §2), so a rotated image is verified per launch, not by prior evidence.
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

## Validation performed for this cycle

Focused only, as the changes are documentation and one synthetic example: the docs audit
(`scripts/phase3_docs_audit.py`), the example-consistency test
(`tests/unit/test_production_readiness_examples.py`, extended for the observation example), the
provider-row guard (`tests/unit/test_sharadar_qualification_boundary.py`), the ADR-0043/0044 governance
tests, `ruff check`, `ruff format --check` and `mypy` on the touched test. The full suite and the images
were **not** rerun: no source under `src/` or `scripts/` changed.
