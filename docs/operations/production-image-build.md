# Production task images — build, digest registration and verification (PROPOSED)

**Status: a procedure for a gate that has not been opened.** No image has been built,
published or run. This document describes what the owner would do at the image gate under
[ADR-0044](../decisions/ADR-0044-production-delivery-contracts-and-packaging.md) once it is
accepted and once the image gate is separately authorized (CLAUDE.md §4.21, §8). Reading it
authorizes nothing; nothing here has been executed.

## What an image is, and what it cannot know

One image per actor, built from `docker/production/Dockerfile` (targets `acquire` and
`build`). An image carries the package source, the entrypoint, the accepted SDK pins
(`docker/production/constraints.txt`), **one** entry executable named as its task definition's
`command` token, and **one** compiled configuration file at
`/etc/kalpamani/compiled-configuration.json`.

An image cannot embed its own content digest, and the task-definition revision that pins that
digest is registered only after the image exists. Neither is therefore compiled in. The
**trust chain** (ADR-0044 §2):

```text
generation record        configuration_digest   = SHA-256 of the compiled configuration file
                         code_commit, code_tree = the commit and tree the file was generated for
build context            source paths extracted from the TREE of that commit (git archive);
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
fresh directory. A checkout is therefore never the build context: an untracked file, a
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
4. **Pin the base image by digest.** Resolve `python:3.11-slim` to a digest once, record it,
   and pass it as `BASE_IMAGE_DIGEST`; the Dockerfile has no default and fails without it.
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

   The repository root is **not** a build context. A mistaken `docker build .` from a checkout
   admits only the source allowlist (`.dockerignore`) and still fails, because no
   `configuration/` input exists there. A target built from the other entry's context fails at
   the Dockerfile's entry check.
6. **Verify before publishing.** Inside the built image (no network): the file at
   `/etc/kalpamani/compiled-configuration.json` hashes to the recorded `configuration_digest`;
   `/opt/kalpamani/CODE_COMMIT` equals the recorded commit; running the entry executable on the
   workstation-shaped environment exits `4` (`REFUSED_CREDENTIAL_ENVIRONMENT`) with zero
   operations and one closing `receipt:` line — `3` (`REFUSED_CONFIGURATION`) is *not*
   expected, because the file is present.
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

## What this document does not authorize

Building, pulling or publishing any image; `terraform plan` or `apply`; a launch; a run; any
AWS, metadata, STS, credential or provider request. The compiled configuration carries no
credential and no account identifier; the owner inputs file stays outside the repository.
