# ADR-0044 — Production delivery contracts and packaging: what an image compiles, what a release attests, what a receipt proves

**Status: PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is
independently reviewed and merged.**

While the pull request introducing this ADR is open, ADR-0044 is proposed and carries no authority.
That is a statement about the present, it will remain true of these days after any later merge, and it
is not to be rewritten as though this decision had authority before it was accepted. On merge, this ADR
becomes **ACCEPTED / IN FORCE** as **the resolution of ADR-0043 §3 and §4 — one coherent delivery
design for the acquisition secret name, the provider origin address set, the build configuration, the
task-side spent identities and the task receipt — together with the narrow amendments to ADR-0036 it
requires and the packaging that implements it offline — and nothing else**, effective together with
the offline contracts merged beside it. **Acceptance authorizes no execution** (§8): no image build,
no publication, no Terraform plan or apply, no launch, no run.

**Nothing was run to produce this decision.** No AWS call, no ECS metadata call, no STS call, no
container image built or pulled, no registry contacted, no credential retrieved, no provider request.
The evidence is the merged runtime composed on synthetic fixtures through the real modules.

---

## 1. Context — five open contracts, and one circularity

ADR-0043 (ACCEPTED / IN FORCE on the PR #100 merge) composed the two task entries and left five
delivery questions as proposals its acceptance did not decide (§3, §4): how the acquisition secret
identifier, the provider origin address set and the build configuration reach the image; how the
task learns which run identities are spent; and how the task's receipt reaches the workstation
ledger. Tracing those against the accepted input, binding, release, bootstrap, task-definition and
receipt contracts exposed a sixth problem that had to be solved first:

**The accepted `CompiledTask` was circular.** ADR-0036 §2.9 had the task's self-check compare the
metadata `ImageID` and `Revision` to values *compiled into the image*. An image cannot contain its
own content digest, and its task-definition revision is registered only after the digest exists. A
placeholder would have satisfied the shape and verified nothing; trusting the metadata as its own
expected value would have verified nothing either. The expected values must come from a source that
exists *after* the image and that the task did not write.

## 2. Decision — the trust chain for expected values

```text
compiled into the image     actor, family, code_commit, configuration_digest    (CompiledTask v2)
                            + ONE closed configuration file at a fixed path      (kalpamani-compiled-configuration/v1)
never in the image          the image digest; the task-definition revision
registered after the image  Terraform: production_image_digests -> a task-definition revision that
                            pins the image BY DIGEST; the generation record: configuration_digest
attested by the launch tool DescribeTasks containers[].imageDigest == the registered digest
                            (a container that has not reported one is waited for, bounded; another
                            digest is MISPLACED / IMAGE_MISMATCH and no release is written)
placement release v2        kalpamani-placement-release/v2 adds image_digest and configuration_digest
                            to the accepted fields; both bound by the task at the barrier:
                            metadata ImageID == release.image_digest      (IMAGE_MISMATCH)
                            compiled configuration_digest == release.configuration_digest
                                                                          (CONFIGURATION_MISMATCH)
                            metadata Family/Revision == release.task_definition_arn (unchanged)
self-check (amended)        family == compiled family; every container reports ONE image; nothing
                            else -- the digest and revision comparisons moved to the barrier
```

**Amendments to accepted text, stated.** ADR-0036 §2.9's self-check clause ("ImageID == compiled
digest, Family/Revision == compiled") and §2.12 step 5 are amended: the image digest and revision are
attested by the launcher and bound at step 6a. ADR-0036's release contract (§2.9) moves to **v2**
with the two digest fields; v1 is retired, and a v1 release is refused (`SCHEMA_VERSION_UNKNOWN`).
`CompiledLaunch` gains the registered `image_digest` and `configuration_digest`; `PlacementIncident`
gains `IMAGE_MISMATCH` and `IMAGE_UNRESOLVED`. ADR-0036's own text is unchanged.

**The compiled configuration file** (`kalpamani-compiled-configuration/v1`) is generated at the image
gate by `scripts/production_compiled_configuration.py` from an owner inputs file outside the
repository, deterministically (canonical bytes; the generation instant is an argument, never the
clock), from a clean checkout whose commit and tree it records. It carries, per entry:

| entry | fields beyond the common ones | not carried |
|---|---|---|
| acquisition | `secret_name` (a Secrets Manager **name**, never an ARN — no account id in the image), `origin_addresses` (IPv4 literals, the Terraform-gate set) | any secret value, any bucket, any account |
| build | `build_configuration` (the accepted `BuildConfiguration.document()`: schemas, calendar, evidence, rule, decision sessions, as-of, commit, tolerances, pinned derivation versions) | — |

The task reads the file at start, refuses `REFUSED_CONFIGURATION` when it is absent, malformed,
oversize, compiled for the other entry, pinned to another derivation version, or carrying any field
outside the closed set; its SHA-256 over the exact bytes is the `configuration_digest`. **Parsing is
total**: a field of the wrong type anywhere — a list where a name is expected, an object where a
digest string is, a float, a session that opens before its own date — a repeated key at any depth,
a lone surrogate or undecodable text is one closed `CompiledConfigurationDefect`, never the
interpreter's or an accepted value contract's own exception. **Rotating an origin address set, a
secret name or a build configuration is an image rebuild, a new registered revision and a Terraform
apply** — the lifecycle consequence of compiling rather than delivering at run time, chosen because
a compiled value is attested by the image digest and can be steered by no parameter, binding or
environment.

**The source identity covers what enters the build.** A recorded commit binds nothing if the bytes
Docker copies come from a working tree: an untracked module, a git-ignored file or a local
modification under `src/` is copied by `docker build .` with no record of it, and
`git status --porcelain --untracked-files=no` cannot see the first two at all. The build context is
therefore **prepared from the exact tree of the recorded commit** by
`scripts/production_build_context.py` — `git archive <commit>` over the closed allowlist of image
source paths (`pyproject.toml`, `src`, the entrypoint script, the Dockerfile, the constraints and
entry files), extracted into a fresh directory outside the checkout — with the compiled
configuration placed beside it at `configuration/compiled-configuration.json` as a **separately
declared, digest-bound input** that is never presented as part of the commit. Five records must
agree before a context exists and before a layer is kept, and a disagreement is refused rather than
relabelled: the `--commit` argument (a full commit id resolving to exactly itself); the generation
record's `code_commit`, `code_tree`, `configuration_digest` and byte count; the compiled file's own
`code_commit`, `code_tree` and `entry`, parsed under the accepted contract; the
`context-manifest.json` the preparer writes (commit, tree, a digest over every source file, the
configuration digest, the build arguments); and, at build time, the required `KALPAMANI_COMMIT` and
`CONFIGURATION_DIGEST` arguments, which the Dockerfile holds equal to the recorded `CODE_COMMIT`, the
copied file's SHA-256 and the target's entry. A configuration generated at an earlier commit is stale
for a later one and is regenerated, never edited. The repository root is not a build context: a
mistaken build from a checkout admits only the source allowlist and fails at the `configuration/`
copy.

## 3. Decision — task-side spent identities travel in the acquisition input

**Selected: acquisition input contract v2** (`kalpamani-production-acquisition-input/v2`, schema 2)
gains one required field, `spent_identities`: `{"spent": [<sorted, distinct run identities>],
"spent_digest": <SHA-256 over the canonical sorted list>}`, at most 128 identities. The acquisition
human actor materializes it from the owner ledger beside the run identity, in the same create-only
`SecureString` write the input already is (ADR-0036 §2.6); the task reads it with the parameter it
already reads. **No fourth parameter, no IAM change, no new operation**: the task bootstrap policy
still names exactly three parameters.

| property | rule |
|---|---|
| freshness | the input's own `issued_at`/`expires_at` (≤ 24 h) |
| integrity | `spent_digest` recomputed and compared; the whole input is bound by digest in the release |
| identity binding | the input's `run_identity` must not appear in its own list (`IDENTITY_SPENT`) |
| size | ≤ 128 identities; the 8 KiB advanced-tier ceiling holds |
| cleanup | the input parameter's existing lifecycle (deleted by the human actor after the run; 24 h expiry) |
| failure | a missing or malformed block is `SPENT_IDENTITIES_MALFORMED` / `SPENT_DIGEST_MISMATCH` → `REFUSED_INPUT`; **never an empty registry** |
| supplementary source | the injected registry (a workstation ledger on the human path) stays optional; on a task none is passed. `UNAVAILABLE` from a supplementary source that *is* configured still refuses |
| durable guard | the payload-independent conditional run reservation (ADR-0038) is unchanged and remains the guard against concurrent reuse |

**Retired:** the `spent_source.py` fourth-parameter document proposed under ADR-0043 §3 is removed;
one implementation remains. **Rejected:** a fourth parameter (widens the task bootstrap policy and
adds a counted read); an S3 read by the acquisition actor (ADR-0019); an always-`UNSPENT` default.

## 4. Decision — the task receipt as bound, machine-readable evidence

The accepted receipt (ADR-0043: allowlisted sentences and integer counts) gains **one last line**,
`receipt: <canonical JSON>` (`kalpamani-task-receipt/v1`):

```text
schema_version, contract_id,
entry, actor           (null exactly for REFUSED_ENTRY: an invalid invocation selected no entry
                        and the receipt invents no actor for it; named for every other outcome),
outcome, exit_code, runner (null before the bootstrap),
counts_observed, counts (null when not observed -- never zeros), cleanup_failures,
code_commit, configuration_digest (null when no configuration was read: REFUSED_ENTRY and
                        REFUSED_CONFIGURATION -- never a placeholder),
binding_digest (null unless the bootstrap released),
receipt_digest (SHA-256 over the rest)
binding_digest = SHA-256 over { task_id, task_definition_arn, image_digest, identity,
                                input_digest, configuration_digest, code_commit }
```

The task discloses **no identifier**: the launch tool holds every value in that set from its own
launch record, recomputes the digest and compares. **This narrowly amends ADR-0036 §2.9's output
rule** ("no key, digest, identifier, subject or vendor row"): the line carries closed tokens, integer
counts, the public code commit and three digests — never a key, identifier, subject or row.

**Every outcome ends in the line, the early refusals included.** The entrypoint's own two refusals —
no closed entry selected (`REFUSED_ENTRY`, exit 2) and no usable compiled configuration
(`REFUSED_CONFIGURATION`, exit 3) — print the allowlisted sentence, the zero counts the process can
prove by construction (no factory, client, socket or working directory existed) and exactly one
closing receipt line, with `entry`/`actor` null for the first, `code_commit`/`configuration_digest`
null for both, `runner` and `binding_digest` null, and no external operation. A `REFUSED_ENTRY`
receipt binds to its launch only through the launch record; the collector never reads an actor out of
it.

The validator (`receipts.py`) refuses: no or duplicate receipt lines; any field outside the closed
set; an exit code that is not the outcome's; a runner verdict that contradicts the outcome; counts
present when unobserved or absent when observed, or data-plane counts on an unreleased bootstrap; a
binding digest present without release or absent with it; a digest mismatch; a receipt from another
entry, configuration, commit, task, image, revision, run or input; an entry or actor on a
`REFUSED_ENTRY` receipt. **Its parsing is total and closed**: a repeated key at any depth
(`DUPLICATE_KEY` — `json.loads` alone keeps the last value, so a contradictory duplicate would
otherwise verify under a matching digest), a lone surrogate or undecodable text (`ENCODING_INVALID`),
malformed or oversize text (`DOCUMENT_MALFORMED`, `TOO_LARGE`), and a value of the wrong type in any
closed field or nested structure — a list where a token is expected, a float, a string count, a
negative count, a malformed cleanup entry — is one closed `ReceiptDefect` (`FIELD_MALFORMED` or the
field's own contradiction member), checked before any set membership, enum conversion or digest
computation, so that no raw `TypeError`, `ValueError` or Unicode error and no input content escapes
the collector boundary.

**Ledger completion** (`ledger_completion`): `COMPLETED` only from a `COMPLETED` receipt with
observed counts; `HALTED`/`REFUSED` from the outcomes that establish them; **no row** for
`UNCLASSIFIED`, `LOCATOR_STATE_UNKNOWN` or `MANIFEST_STATE_UNKNOWN` — the owner reviews those.
Missing evidence and `counts_observed = false` never become measured zeros.

**Collection (proposed, not implemented):** a separately authorized workstation collector reads the
task's log stream (`<prefix>/<container>/<task-id>`) with **`logs:GetLogEvents` (and
`logs:FilterLogEvents`) on the research log group's streams for the actor's launcher permission set**
— an exact IAM delta deferred to the infrastructure cycle — extracts the one receipt line, verifies it
against the launch record and completes the ledger row. Until then the receipt is the boundary.

## 5. Permission and lifecycle consequences

| | |
|---|---|
| IAM / Terraform / network | **no change in this cycle**. Required later: `logs:GetLogEvents`/`FilterLogEvents` for the two launcher sets (§4); `production_image_digests` and task-definition revisions at the image gate (existing declarations) |
| operation accounting | unchanged: the task still reads three parameters; the launcher adds no SSM/S3 call, only further `DescribeTasks` polls while the image digest is unreported (counted) |
| compiled values | rotation = rebuild + register + apply |
| inputs | acquisition input v1 is refused; the human actor's materialization must emit v2 |
| release | v1 is refused; the launch tool emits v2 with both digests |

## 6. Packaging (prepared offline; nothing built)

`docker/production/Dockerfile` (targets `acquire`, `build`; base image pinned by a required
`BASE_IMAGE_DIGEST` build argument; `KALPAMANI_COMMIT` and `CONFIGURATION_DIGEST` required, the first
recorded as `CODE_COMMIT` and both held equal to the copied configuration at build time; one entry
executable per image named as the task definition's `command` token; the compiled configuration copied
from the prepared context's `configuration/` input, never from the checkout; unprivileged user; no
`ENTRYPOINT`), `scripts/production_build_context.py` (the context from the exact tree, §2),
`scripts/production_compiled_configuration.py` (the configuration into the git-ignored
`docker/production/build/<entry>/` staging directory), a root `.dockerignore` that admits only the
source allowlist so a mistaken checkout build still fails, `docker/production/constraints.txt`
pinning the verified SDK set (`boto3==1.43.83`, `botocore==1.43.83` and their resolved dependencies;
hash pinning deferred), and
[docs/operations/production-image-build.md](../operations/production-image-build.md). **No image is
built or published by this repository.**

## 7. Rejected alternatives

- **Deliver the secret name, origin set or build configuration through the runtime binding.** It
  changes the accepted closed field set and re-materialization, and a binding is steerable input,
  not image-attested.
- **Trust the metadata's `ImageID` as its own expected value, or compile a placeholder digest.**
  Neither verifies anything.
- **Let the task read its own digest from the registry.** A network read by the task for a value the
  launcher already observes, and a new permission.
- **Put identifiers in the receipt line.** Contradicts ADR-0036 §2.9 more than necessary; a digest
  binds as strongly.

## 8. Effectiveness and execution gates

- **Effectiveness**: in force only on the independently reviewed merge of the pull request
  introducing it, together with the offline contracts merged beside it.
- **Execution**: acceptance authorizes no image build or publication, no Terraform plan or apply, no
  launch, no run, no AWS, metadata, STS, credential or provider request. The collector's IAM delta
  (§4) is a separate infrastructure cycle. Every ADR-0036 execution gate stays closed.
- **Scope**: nothing here amends ADR-0009, ADR-0019, ADR-0035, ADR-0037, ADR-0038, ADR-0039,
  ADR-0040, ADR-0041 or ADR-0042; the exchange calendar, split-ratio semantics, action-event identity
  and R-3/R-5 stay unresolved.

G2 OPEN; CONTROL DEFERRED; Phase 3 NOT COMPLETE; live trading HARD-DISABLED.
