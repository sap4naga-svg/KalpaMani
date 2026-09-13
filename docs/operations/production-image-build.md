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
                         code_commit            = the commit the build context was checked out at
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

## Procedure (owner, workstation; each numbered step is its own authorization where marked)

1. **Check out the exact commit** the image will record; the tree must be clean
   (`git status --porcelain` empty). The generator refuses otherwise.
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
3. **Pin the base image by digest.** Resolve `python:3.11-slim` to a digest once, record it,
   and pass it as `BASE_IMAGE_DIGEST`; the Dockerfile has no default and fails without it.
4. **Build each target** *(image gate authorization)*:

   ```text
   docker build --file docker/production/Dockerfile --target acquire \
       --build-arg BASE_IMAGE_DIGEST=sha256:<base digest> \
       --build-arg KALPAMANI_COMMIT=<commit> --tag kalpamani-acquire:<commit> .
   docker build --file docker/production/Dockerfile --target build ... --tag kalpamani-build:<commit> .
   ```

   The build context is the repository root under the allowlist in `.dockerignore`.
5. **Verify before publishing.** Inside the built image (no network): the file at
   `/etc/kalpamani/compiled-configuration.json` hashes to the recorded `configuration_digest`;
   `/opt/kalpamani/CODE_COMMIT` equals the recorded commit; running the entry executable on the
   workstation-shaped environment exits `3` (`REFUSED_CONFIGURATION` is *not* expected — the file
   is present — `4`, `REFUSED_CREDENTIAL_ENVIRONMENT`, is, with zero operations).
6. **Publish to the one research repository** *(image publication authorization)* and record
   the **registry-reported digest** (`RepoDigests`). This digest, not the local image id, is
   what everything downstream compares.
7. **Register** *(Terraform gate)*: set `production_image_digests = { acquisition = ..., build =
   ... }`, plan, and apply a new task-definition revision per actor. Record the revision ARNs.
8. **Compile the launch tool** (`CompiledLaunch`) with the exact revision ARN, the registry
   digest and the `configuration_digest` from step 2 for each actor; a mismatch between any two
   records is a stop.
9. **Verification, end to end, is a later gate** (ADR-0036 R-1/R-2: a task that reaches the
   barrier and exits with the closed verification code). Nothing in this document is that.

## What this document does not authorize

Building, pulling or publishing any image; `terraform plan` or `apply`; a launch; a run; any
AWS, metadata, STS, credential or provider request. The compiled configuration carries no
credential and no account identifier; the owner inputs file stays outside the repository.
