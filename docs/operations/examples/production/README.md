# Synthetic production input examples — SHAPE ONLY, NEVER PRODUCTION VALUES

Every document in this directory is **synthetic**: each value is the test suite's own fixture
value (`tests/fixtures/production_runtime.py`, `tests/fixtures/production_build.py`,
`tests/fixtures/production_entry.py`), and `tests/unit/test_production_readiness_examples.py`
parses every file through the accepted contract it illustrates on every run, so a file that
drifts from its contract fails the suite. **None of them is a production input, none was
produced from an owner value, and none may be relabelled as one.** The secret name is
`synthetic/production/sharadar`; the addresses are RFC 5737 documentation addresses
(`192.0.2.0/24`); the run and build identities are the fixtures' `synthetic-…` values; the
compiled configurations record the fixtures' synthetic commit and tree. The production values
these stand in for are listed in [`../../production-owner-inputs.md`](../../production-owner-inputs.md).

| File | Contract | Who produces the production document | Consumer |
|---|---|---|---|
| `acquire-inputs.synthetic.json` | the owner inputs file `scripts/production_compiled_configuration.py --entry kalpamani-production-acquire` reads (exactly `secret_name`, `origin_addresses`) | the owner, outside the repository, from the Terraform-gate values | the generator, at the image gate |
| `build-inputs.synthetic.json` | the owner inputs file for `--entry kalpamani-research-build` (exactly `build_configuration`, the accepted `BuildConfiguration.document()` shape) | the owner, outside the repository | the generator, at the image gate |
| `build-inputs.observation.synthetic.json` | the same shape with an **explicitly empty** `accepted_schemas` set per dataset — the **Route B observation image** configuration of the readiness record (§4.2 item 6), which parses, admits no header, and therefore refuses every build with zero writes. **Route B is PROPOSED and BLOCKING**: the receipt amendment it needs does not exist, the digests such a build would report are evidence for the owner's review and never an accepted set, and this file only shows that an empty set is a valid, non-admitting configuration rather than a placeholder | the owner, outside the repository — and only after the Route B ADR is accepted | the generator, at the image gate |
| `compiled-configuration.acquire.synthetic.json` | `kalpamani-compiled-configuration/v1`, acquisition entry — what the generator writes and the image carries at `/etc/kalpamani/compiled-configuration.json` | the generator | the task entrypoint |
| `compiled-configuration.build.synthetic.json` | the same, build entry | the generator | the task entrypoint |
| `acquisition-input.v2.synthetic.json` | `kalpamani-production-acquisition-input/v2` — the SSM `SecureString` the acquisition human actor materializes per run (ADR-0036 §2.6, ADR-0044 §3) | the acquisition human principal, per authorized run (no tool exists yet — see the readiness document) | the acquisition task |
| `build-input.v2.synthetic.json` | `kalpamani-research-build-input/v2` (ADR-0055) — the build human actor's per-build input: per run, the identity and the SHA-256 of its admitted run locator, within the 8 KiB advanced-tier ceiling; the launch tool materializes it from the ledger and the preserved locators | the research-build human principal, per authorized build, through the launch tool | the build task |
| `build-input.v1.synthetic.json` | `kalpamani-research-build-input/v1` — **historical**: the version-1 shape carrying whole ledger rows, which eighteen runs could not fit under 8 KiB (ADR-0055 §1); retained as evidence of that shape, readable only through `parse_historical_build_input_v1`, refused for any launch | — (no new v1 input is ever materialized) | the historical reader only |
| `owner-ledger.synthetic.json` | `kalpamani-owner-ledger/v1` — the owner ledger the launch tool of **ADR-0045** (accepted on the PR #104 merge) cuts every input from and appends every launch to: one buildable row (`RECEIPT_VERIFIED`, `COMPLETED`), one verification row (`verify-` identity, `VERIFIED`), one provisional `COMPLETED` row (`EXIT_CODE_ONLY`, not buildable until its receipt is verified) and one halted build row. Every identity in it is consumed for both kinds | the launch tool, under the owner's private root; never typed | `scripts/production_launch.py` |
| `launch-authorization.synthetic.json` | `kalpamani-launch-authorization/v1` — the owner's written authorization for exactly one launch of one identity of one kind **of one launch specification** (its `specification_digest` is the value `scripts/production_launch.py` prints when run without its flag; the example names the digest the fixtures' synthetic records produce), valid at most 24 h, required beside the tool's flag | the owner, per launch, never reused | `scripts/production_launch.py` |

The runtime-binding parameters (`kalpamani-production-*-runtime-binding/v1`), the placement
release (`kalpamani-placement-release/v2`), the launch-inputs record (`kalpamani-launch-inputs/v1`),
the launch specification (`kalpamani-launch-specification/v1`), the launch record
(`kalpamani-launch-record/v1`, which also names its specification digest and the verified security
groups) and the reservation (`kalpamani-launch-reservation/v1`, which embeds the whole specification)
are deliberately **not** exemplified here: each carries an account-bearing ARN or account id or is
written only by the tool, and the bindings are materialized by Terraform, the release, specification, record and reservation
by the launch tool, the launch-inputs record transcribed from Terraform outputs, never typed by the
owner. The Reachability Analyzer transcription (`kalpamani-reachability-evidence/v1`) is a closed
document with no free-text field to carry a synthetic marker, so it is not exemplified either; its
shape is `probe.parse_reachability_evidence` and the ADR-0045 §3 field list. Their field sets are stated in the readiness document,
and the test suite builds and verifies synthetic instances of both from the fixtures on every run.
