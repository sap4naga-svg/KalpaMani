# Production task images — build, digest registration and verification

**Status: an accepted procedure for a gate that has not been opened.** Its design is accepted
under [ADR-0044](../decisions/ADR-0044-production-delivery-contracts-and-packaging.md) (PR #101,
merged 2026-09-14). **No image has been published, registered or run on AWS.** Steps 1–6 have been
exercised once, locally, under a separate written authorization for *local image verification*
— on one workstation, with **synthetic** configurations, in **network-disabled** containers — and
what that established and did not is recorded in *Local verification* below; the packaging
corrections it produced merged as **PR #102** (2026-09-14T10:25:40Z, merge commit
`02998fa9bde853d4262269c3b9032bd7fc171461`). What remains before a production image can exist, and
the cloud-verification sequence after it, is recorded in
[`production-readiness.md`](production-readiness.md). Steps 7–10 remain
separately authorized owner actions (CLAUDE.md §4.21, §8). Reading this authorizes nothing.

## What an image is, and what it cannot know

One image per actor, built from `docker/production/Dockerfile` (targets `acquire` and
`build`), and — under **proposed ADR-0045**, no authority while its pull request is open — one
**verification** image per actor (targets `acquire-verify` and `build-verify`, entry tokens
`kalpamani-production-acquire-verify` / `kalpamani-research-build-verify`), built from the same
Dockerfile by the same procedure from a context prepared for its own entry. A verification image
carries a compiled configuration of the verification field set (the origin address set and nothing
else: no secret name, no build configuration), and its entry stops at the release barrier with exit
18. An image carries the package source, the entrypoint, the accepted SDK pins
(`docker/production/constraints.txt`), **one** entry executable named as its task definition's
`command` token, and **one** compiled configuration file at
`/etc/kalpamani/compiled-configuration.json`.

An image cannot embed its own content digest, and the task-definition revision that pins that
digest is registered only after the image exists. Neither is therefore compiled in. The
**trust chain** (ADR-0044 §2):

```text
generation record        configuration_digest   = SHA-256 of the compiled configuration file
                         code_commit, code_tree = the commit and tree the file was generated for
build context            source paths extracted from the TREE of that commit (git archive, with
                         end-of-line conversion disabled, every file held to its blob id);
                         the configuration beside them as a declared, digest-bound input;
                         context-manifest.json naming commit, tree, source digest and
                         configuration digest
image build              KALPAMANI_COMMIT and CONFIGURATION_DIGEST are required arguments;
                         the Dockerfile holds the copied file's SHA-256 equal to the
                         argument, its `entry` equal to the target, and its `code_commit`
                         equal to the recorded /opt/kalpamani/CODE_COMMIT -- or fails
image                    contains code + file; its DIGEST is produced by the registry push
Terraform                production_image_digests[actor] = that digest;  a new task-definition
                         revision pins the image BY DIGEST
launch tool (CompiledLaunch)   image_digest and configuration_digest from those records
DescribeTasks            containers[].imageDigest observed; must equal the registered digest,
                         else MISPLACED / IMAGE_MISMATCH and no release
placement release (v2)   binds task ARN, revision, image_digest, configuration_digest,
                         identity, input digest
task metadata v4         ImageID and Family/Revision observed by the task
release barrier          ImageID == release.image_digest; compiled configuration_digest ==
                         release.configuration_digest; revision == release.task_definition_arn
```

No placeholder digest exists anywhere in the chain, and no value is compared to itself.

## What the source identity covers, exactly

**The image's source bytes are the tree of the recorded commit, never the working tree.**
`scripts/production_build_context.py` runs `git archive <commit>` over the closed allowlist of
image source paths (`IMAGE_SOURCE_PATHS`: `pyproject.toml`, `src`,
`scripts/production_task_entrypoint.py`, `docker/production/Dockerfile`,
`docker/production/constraints.txt`, `docker/production/entry`) and extracts the result into a
fresh directory — **with end-of-line conversion disabled, and every extracted file then hashed as a
Git blob and held equal to the object id the tree lists for that path**. `git archive` honours a
checkout's `core.autocrlf` and `text=auto` attribute, so on a Windows workstation it would
otherwise write CRLF into the POSIX entry executables (a `#!/bin/sh\r` shebang does not exec) and
the source digest would depend on the workstation; the first local build demonstrated exactly that.
A symbolic link, a submodule, an `export-subst` rewrite or any byte disagreement refuses the
context. The manifest also names the sources the tree marks executable. A checkout is therefore never the build context: an untracked file, a
git-ignored file or a local modification under `src/` — each of which `docker build .` would
copy with no record of it, because Docker honours `.dockerignore` and nothing else — cannot
reach the build, and the tests inspect the prepared directory's contents to show it
(`tests/unit/test_production_build_context_script.py`). The Dockerfile itself is archived from
the same tree, so a build uses the commit's own.

**The compiled configuration is a separate, declared input.** It is generated into the
git-ignored `docker/production/build/<entry>/` staging directory and placed in the context at
`configuration/compiled-configuration.json`. It is **not** part of the commit and is never
presented as though it were: the manifest records it under its own digest beside the source
digest, and the Dockerfile copies it from `configuration/` alone.

**Five records must agree, and a disagreement is refused rather than relabelled:**

| record | what it names | held equal by |
|---|---|---|
| the `--commit` argument | the exact 40-hex commit to build | `git rev-parse --verify <commit>^{commit}` must return itself (no abbreviation, branch or tag) |
| `generation-record.json` | `code_commit`, `code_tree`, `configuration_digest`, `configuration_bytes`, `entry` | the context preparer, against the resolved commit, its tree and the file's bytes |
| `compiled-configuration.json` | its own `code_commit`, `code_tree`, `entry` | the context preparer, by parsing the file under the accepted contract |
| `context-manifest.json` | commit, tree, source digest, configuration digest, the build arguments | written only after every check above passed |
| `KALPAMANI_COMMIT` / `CONFIGURATION_DIGEST` | the build arguments; `/opt/kalpamani/CODE_COMMIT` in the image | the Dockerfile's build-time check in each target |

A configuration generated at an earlier commit is **stale** for a later one: the preparer
refuses it, and the owner regenerates rather than editing a record. The generator's own
clean-tree rule (`git status --porcelain --untracked-files=no` empty) remains, but it is a
convenience for the person reading the checkout, not the source-identity control — the
context preparer is.

## Procedure (owner, workstation; each numbered step is its own authorization where marked)

1. **Check out the exact commit** the image will record; the tree must be clean
   (`git status --porcelain` empty). Note the full commit id.
2. **Generate the compiled configuration** for each entry from an owner inputs file kept
   outside the repository (never committed; carries the secret **name**, not a value):

   ```text
   python scripts/production_compiled_configuration.py --entry kalpamani-production-acquire \
       --inputs <owner path>/acquire-inputs.json --generated-at <ISO instant> \
       --output docker/production/build/acquire
   python scripts/production_compiled_configuration.py --entry kalpamani-research-build \
       --inputs <owner path>/build-inputs.json --generated-at <ISO instant> \
       --output docker/production/build/build
   ```

   Record `generation-record.json` (commit, tree, `configuration_digest`) beside the run's
   evidence. `docker/production/build/` is git-ignored.
3. **Prepare the build context** for each entry, from the exact tree, into a directory
   **outside the repository** (the preparer refuses an existing directory and one inside the
   checkout):

   ```text
   python scripts/production_build_context.py --entry kalpamani-production-acquire \
       --commit <commit> --configuration docker/production/build/acquire \
       --output <outside>/kalpamani-context-acquire
   python scripts/production_build_context.py --entry kalpamani-research-build \
       --commit <commit> --configuration docker/production/build/build \
       --output <outside>/kalpamani-context-build
   ```

   It prints the entry, the commit, the configuration digest and the source file count, and
   writes `context-manifest.json`. Its `build_arguments` are the values step 5 passes; **read
   them from the manifest, never retype them**.
4. **Pin the base image by digest.** Resolve `python:3.11-slim` once and record **the linux/amd64
   image manifest digest** — the task definitions run `X86_64` — as `BASE_IMAGE_DIGEST`; the
   Dockerfile has no default and fails without it. A tag resolves to a **multi-platform index**
   whose digest differs from every platform image's; `docker buildx imagetools inspect
   python:3.11-slim` lists both, and the recorded value must be the platform image's, so that the
   same bytes are built wherever the build runs. The base carries the build backend the wheel
   build needs (`setuptools`, `wheel`; pyproject.toml's `build-system.requires`), which the
   Dockerfile checks and records at `/opt/kalpamani/BUILD_BACKEND` — pip's `--no-deps` does not
   disable build isolation, so the install runs `--no-build-isolation` and fetches nothing to build.
5. **Build each target** *(image gate authorization)* **from the prepared context**, using the
   Dockerfile the context carries:

   ```text
   docker build --file <outside>/kalpamani-context-acquire/docker/production/Dockerfile \
       --target acquire \
       --build-arg BASE_IMAGE_DIGEST=sha256:<base digest> \
       --build-arg KALPAMANI_COMMIT=<commit> \
       --build-arg CONFIGURATION_DIGEST=<configuration_digest from the manifest> \
       --tag kalpamani-acquire:<commit> <outside>/kalpamani-context-acquire
   docker build --file <outside>/kalpamani-context-build/docker/production/Dockerfile \
       --target build ... --tag kalpamani-build:<commit> <outside>/kalpamani-context-build
   ```

   The two verification targets (proposed ADR-0045) are built the same way from their own
   contexts — `--target acquire-verify` from a context generated with
   `--entry kalpamani-production-acquire-verify`, `--target build-verify` from one generated with
   `--entry kalpamani-research-build-verify`; each is registered under its verification
   task-definition family (`production_image_digests` keys `acquisition_verify`, `build_verify`).
   **No verification image has been built**; the local verification below covers the two
   production targets only.

   The repository root is **not** a build context. A mistaken `docker build .` from a checkout
   admits only the source allowlist (`.dockerignore`) and still fails, because no
   `configuration/` input exists there. A target built from the other entry's context fails at
   the Dockerfile's entry check.
6. **Verify before publishing.** Inside the built image, in a container shaped like the task
   definition — `--network none`, `--read-only`, `--tmpfs /work:rw,noexec,nosuid`, the image's own
   user (`10001:10001`), no host mounts, no credentials — the file at
   `/etc/kalpamani/compiled-configuration.json` hashes to the recorded `configuration_digest`;
   `/opt/kalpamani/CODE_COMMIT` equals the recorded commit; `/etc/kalpamani` is mode `0555` and
   the file `0444`; the package imports from `site-packages`; and running the entry executable with
   no ECS credential variables exits `4` (`REFUSED_CREDENTIAL_ENVIRONMENT`) with zero operations,
   nothing created under `/work`, and exactly one closing `receipt:` line carrying the commit and
   the configuration digest. `3` (`REFUSED_CONFIGURATION`) is *not* expected, because the file is
   present — the accepted image produced it anyway, because `COPY --chmod=0444` had created its
   parent directory `0444`. With the container credential variable present and no `/work`
   writable, `6` (`REFUSED_DEPENDENCY`) is expected before any client exists. The controlled
   negative builds in *Local verification* are the checks' own negative controls.
7. **Publish to the one research repository** *(image publication authorization)* and record
   the **registry-reported digest** (`RepoDigests`). This digest, not the local image id, is
   what everything downstream compares.
8. **Register** *(Terraform gate)*: set `production_image_digests = { acquisition = ..., build =
   ... }`, plan, and apply a new task-definition revision per actor. Record the revision ARNs.
9. **Compile the launch tool** (`CompiledLaunch`) with the exact revision ARN, the registry
   digest and the `configuration_digest` from step 2 for each actor; a mismatch between any two
   records is a stop.
10. **Verification, end to end, is a later gate** (ADR-0036 R-1/R-2: a task that reaches the
    barrier and exits with the closed verification code). Nothing in this document is that.

## Local verification — performed once, after PR #101; packaging evidence only

Under a separate written authorization, both targets were built once on one workstation
(Docker Desktop 4.48 / engine 28.5.1, `linux/amd64`, BuildKit) from contexts prepared with
`scripts/production_build_context.py` from the exact tree of a committed head, with compiled
configurations generated from **synthetic inputs** (a synthetic secret *name*, the reserved
documentation addresses `192.0.2.10`/`192.0.2.11`, and the test fixtures' synthetic calendar and
evidence), the base pinned by its linux/amd64 image manifest digest. **Nothing was published,
registered, launched or run on AWS; the images carry synthetic configuration and are not
production-ready; the local image ids are not registry digests.**

The accepted packaging (the PR #101 head) built, and its image then demonstrated four defects in
task-shaped containers — each reproduced before it was corrected, and each now held by a test:

| defect the accepted image showed | correction |
|---|---|
| `git archive` on the Windows checkout emitted CRLF; `exec /usr/local/bin/kalpamani-production-acquire: no such file or directory` | the preparer archives with conversion disabled and holds every file to the tree's blob |
| `/etc/kalpamani` was created `0444` by `COPY --chmod=0444`; every non-root user got `REFUSED_CONFIGURATION` (3) with the file present | the base stage creates the directory `0555`; the build-time check holds the modes |
| the image user was uid 999 (`useradd --system`) while the task definitions run `10001:10001`, which had no passwd entry | `groupadd`/`useradd` at `10001`, `USER 10001:10001` |
| `tempfile.mkdtemp()` used `/tmp`, absent under the read-only root: a traceback, exit 1, no receipt | the working directory is created under `/work` after the credential-environment check; an unusable root is `REFUSED_DEPENDENCY` (6) with a receipt |

Two further facts came out of the same runs. pip's `--no-deps` leaves **build isolation** on, so the
accepted Dockerfile fetched `setuptools`/`wheel` from PyPI unpinned to build the wheel; the install
now runs `--no-build-isolation` against the pinned base's backend and records the versions used.
And Docker mounts a tmpfs over an existing mount point with **the directory's mode copied but root
ownership**, so a `0700` `/work` in the image made the tmpfs unwritable by uid 10001; the mount
point is created `1777`, which works under both behaviours.

What the network-disabled containers established, for both images (`--read-only`,
`--tmpfs /work:rw,noexec,nosuid,size=64m`, `--cap-drop ALL`, `no-new-privileges`, memory, CPU and
pid limits, a wall-clock timeout, no Docker socket, no credentials, no private file, no host
directory; single synthetic files bind-mounted read-only only for the negative controls):

```text
image user 10001:10001 (kalpamani); /etc/kalpamani 0555; configuration 0444; entry 0555, LF shebang
configuration bytes hash to the manifest's digest; CODE_COMMIT == the recorded commit ==
    the configuration's code_commit; BUILD_BACKEND recorded; package imports from site-packages
default CMD, no ECS credentials            exit 4  REFUSED_CREDENTIAL_ENVIRONMENT, zero counts, one receipt
entry explicitly / ambient AWS_PROFILE     exit 4  the same
the task definition's user given explicitly exit 4  the same
command override appending an argument     exit 2  REFUSED_ENTRY, entry and actor null
configuration absent / truncated / other actor's   exit 3  REFUSED_CONFIGURATION, no commit or digest claimed
container credential variable, no network  acquire exit 5 REFUSED_ORIGIN (the origin cannot resolve);
                                           build exit 6 REFUSED_DEPENDENCY (the container provider,
                                           the session's only one, cannot reach 169.254.170.2);
                                           /work empty after exit, no cleanup failure reported
container credential variable, /work read-only     exit 6  REFUSED_DEPENDENCY before any client
negative builds: a wrong CONFIGURATION_DIGEST, the other target on this context, a KALPAMANI_COMMIT
    that is not the configuration's, a swapped digest record, no BASE_IMAGE_DIGEST, the repository
    root as context -- each fails at its intended check, and the check names its closed reason
```

**What a local container is not.** It is not Fargate: no task metadata endpoint, no container
credential agent, no awsvpc network, no task role, no SSM parameter, no release, no placement
verification and no CloudWatch stream existed, so every path past the credential-environment check
refused at its first dependency and **no bootstrap, identity proof, release barrier, reservation,
provider request or S3 operation was exercised**. Docker Desktop's engine and Fargate's runtime
differ in what they do with a tmpfs mount point's mode and ownership, in the metadata and
credential endpoints they provide, and in how a read-only root is enforced. ADR-0036 R-1/R-2 (a
task that reaches the barrier and exits with the closed verification code) remain a later gate.

**Remaining prerequisites before an image can be used**, each a separate authorization: production
owner inputs and a compiled configuration from them (never the synthetic ones); a build from a
context prepared at the exact release commit; publication to the one research repository and the
registry-reported digest; `production_image_digests` and a task-definition revision (Terraform
plan/apply); the receipt collector and its `logs:GetLogEvents` delta (ADR-0044 §5, deferred); the
R-3 server-side conditional-write verification; the ADR-0036 R-1/R-2 runtime verification. The
task definition's tmpfs carries no `uid`/`gid`/`mode` mount option; whether Fargate copies the
mount point's mode as Docker does is **not established here** and is a check for the runtime gate.

## What this document does not authorize

Building, pulling or publishing any image beyond the one local verification recorded above —
the two verification targets included, which have never been built;
`terraform plan` or `apply`; a launch; a run; any AWS, metadata, STS, credential or provider
request. The compiled configuration carries no credential and no account identifier; the owner
inputs file stays outside the repository.
