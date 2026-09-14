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
| `build-inputs.observation.synthetic.json` | the same shape with an **explicitly empty** `accepted_schemas` set per dataset — the **Route B observation image** configuration of the readiness record (§4.2 item 6), which parses, admits no header, and therefore refuses every build with zero writes. **Route B is PROPOSED and BLOCKING**: the receipt amendment it needs does not exist, and this file only shows that an empty set is a valid, non-admitting configuration rather than a placeholder | the owner, outside the repository — and only after the Route B ADR is accepted | the generator, at the image gate |
| `compiled-configuration.acquire.synthetic.json` | `kalpamani-compiled-configuration/v1`, acquisition entry — what the generator writes and the image carries at `/etc/kalpamani/compiled-configuration.json` | the generator | the task entrypoint |
| `compiled-configuration.build.synthetic.json` | the same, build entry | the generator | the task entrypoint |
| `acquisition-input.v2.synthetic.json` | `kalpamani-production-acquisition-input/v2` — the SSM `SecureString` the acquisition human actor materializes per run (ADR-0036 §2.6, ADR-0044 §3) | the acquisition human principal, per authorized run (no tool exists yet — see the readiness document) | the acquisition task |
| `build-input.v1.synthetic.json` | `kalpamani-research-build-input/v1` — the build human actor's per-build input carrying the owner ledger rows | the research-build human principal, per authorized build (no tool exists yet) | the build task |

The runtime-binding parameters (`kalpamani-production-*-runtime-binding/v1`) and the placement
release (`kalpamani-placement-release/v2`) are deliberately **not** exemplified here: both carry an
account-bearing ARN or account id, and the bindings are materialized by Terraform, the release by
the launch tool, never typed by the owner. Their field sets are stated in the readiness document,
and the test suite builds and verifies synthetic instances of both from the fixtures on every run.
