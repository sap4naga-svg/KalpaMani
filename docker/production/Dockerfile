# syntax=docker/dockerfile:1.7
#
# KalpaMani production task images (ADR-0036 s.2.9, ADR-0043, ADR-0044 s.2/s.6).
#
# One Dockerfile, two build targets -- `acquire` and `build` -- each producing ONE
# actor's image. An image carries the code, the accepted SDK pins, ONE entry executable
# named exactly as the task definition's `command` token, and ONE compiled configuration
# file generated at the image gate (docs/operations/production-image-build.md).
#
# THE BUILD CONTEXT IS A PREPARED DIRECTORY, NOT A CHECKOUT. The source paths below are
# extracted from the exact tree of the recorded commit by
# scripts/production_build_context.py (`git archive <commit>` over a closed allowlist,
# every extracted file held equal to the tree's blob), and the compiled configuration is
# placed beside them at `configuration/` as a separately declared, digest-bound input. A
# working tree is never the context: an untracked, ignored or modified file under `src/`
# would otherwise be copied with no record of it. Building from the repository root
# fails at the `configuration/` COPY.
#
# Nothing here is built or published by the repository: the image gate is a separately
# authorized owner action. Every input that the repository cannot know is a REQUIRED
# build argument with no default, so an unconfigured build fails rather than producing
# an image that would "work" with a placeholder:
#
#   BASE_IMAGE_DIGEST      sha256:<64 hex> of the python:3.11-slim base the owner pinned --
#                          the linux/amd64 IMAGE manifest digest (the task definitions run
#                          X86_64), not the multi-platform index digest
#   KALPAMANI_COMMIT       the 40-hex commit the context was prepared from; recorded as
#                          /opt/kalpamani/CODE_COMMIT and held equal to the commit the
#                          compiled configuration carries
#   CONFIGURATION_DIGEST   the 64-hex SHA-256 the generation record and the context
#                          manifest name; the copied file must hash to exactly it
#
# The image's own digest and its task-definition revision are never written into the
# image (ADR-0044 s.2): the launch tool attests both in the release.

ARG BASE_IMAGE_DIGEST
FROM python:3.11-slim@${BASE_IMAGE_DIGEST} AS base

ARG KALPAMANI_COMMIT
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# A dedicated, unprivileged runtime user at EXACTLY the numeric identity the task
# definitions declare (`user = "10001:10001"`, infra/aws/research-data-plane/
# production_compute.tf): a container runs as that number whatever the image says, so
# the image says the same number and the number has a passwd entry. The task holds no
# shell session (ecs:ExecuteCommand is denied) and the root filesystem is read-only under
# the task definition; the only writable space is the task definition's tmpfs at /work,
# which the entrypoint uses as its working root. The mount point is created here with
# /tmp's mode (1777, sticky): a container runtime that mounts the tmpfs over an existing
# directory may copy the directory's MODE onto the tmpfs while leaving it root-owned
# (Docker does; a 0700 mount point made the tmpfs unwritable by uid 10001 in the local
# verification), and a runtime that does not copy it defaults to 1777 -- so the runtime
# user can create its working directory under either behaviour, and a local container
# that carries no tmpfs still has the path. The configuration directory is created here
# with mode 0555 -- see the target stages.
RUN groupadd --system --gid 10001 kalpamani \
    && useradd --system --uid 10001 --gid 10001 --no-create-home \
        --shell /usr/sbin/nologin kalpamani \
    && mkdir --mode=1777 /work \
    && mkdir --mode=0555 /etc/kalpamani

WORKDIR /opt/kalpamani
COPY pyproject.toml ./
COPY docker/production/constraints.txt ./docker/production/constraints.txt
COPY src ./src
COPY scripts/production_task_entrypoint.py ./scripts/production_task_entrypoint.py

# The SDK pins are the ones the repository's verified environment carries; the package
# itself is installed without dependency resolution so nothing beyond the constraints
# file can arrive. No dev, test or cloud CLI tooling exists in the image.
#
# `--no-deps` does NOT disable pip's build isolation: without `--no-build-isolation`, pip
# builds the wheel in a throwaway environment and fetches the build backend
# (`setuptools>=68`, `wheel`) from PyPI at whatever version resolves that day -- an
# unpinned input the first local build demonstrated. The pinned base image already
# carries a `setuptools` and a `wheel` satisfying pyproject.toml's
# `build-system.requires`, so the backend comes from the base digest and nothing is
# fetched to build; the check below holds that true and records the versions used at
# /opt/kalpamani/BUILD_BACKEND beside the code commit.
RUN python -m pip install --no-deps --constraint docker/production/constraints.txt \
        --requirement docker/production/constraints.txt \
    && python - <<'CHECK'
import importlib.metadata as metadata, pathlib, sys, tomllib
requires = tomllib.load(open("pyproject.toml", "rb"))["build-system"]["requires"]
installed = {name: metadata.version(name) for name in ("setuptools", "wheel")}
for requirement in requires:
    name, _, floor = requirement.partition(">=")
    if name not in installed:
        sys.exit(1)
    if floor and tuple(int(p) for p in installed[name].split(".")[:2]) < tuple(
        int(p) for p in floor.split(".")[:2]
    ):
        sys.exit(1)
pathlib.Path("/opt/kalpamani/BUILD_BACKEND").write_text(
    "".join(f"{name}=={version}\n" for name, version in sorted(installed.items()))
)
CHECK
RUN python -m pip install --no-deps --no-build-isolation . \
    && test -n "${KALPAMANI_COMMIT}" \
    && printf '%s\n' "${KALPAMANI_COMMIT}" > /opt/kalpamani/CODE_COMMIT \
    && python - <<'CHECK'
import re, pathlib, sys
commit = pathlib.Path("/opt/kalpamani/CODE_COMMIT").read_text().strip()
sys.exit(0 if re.fullmatch(r"[0-9a-f]{40}", commit) else 1)
CHECK

# Neither target carries a shell entrypoint: the task definition's `command` token is the
# executable, and the executable is the actor's entry and nothing else.
#
# Each target copies the ONE compiled configuration from the context's declared input
# path and then holds these things equal before the layer is kept: the file's SHA-256
# and CONFIGURATION_DIGEST; the file's `entry` and this target's entry; the file's
# `code_commit` and the recorded CODE_COMMIT; and the modes the runtime user needs --
# a `COPY --chmod=0444` that has to CREATE its parent directory gives the directory 0444
# too, and a directory without the execute bit cannot be entered by the unprivileged
# user (the accepted image refused REFUSED_CONFIGURATION with the file present), so the
# base stage creates the directory with 0555 and the check holds it traversable, the
# file readable, the entry executable, and the entry's shebang free of a carriage return.
# A disagreement fails the build.
FROM base AS acquire
ARG CONFIGURATION_DIGEST
COPY --chmod=0555 docker/production/entry/kalpamani-production-acquire /usr/local/bin/kalpamani-production-acquire
COPY --chmod=0444 configuration/compiled-configuration.json /etc/kalpamani/compiled-configuration.json
RUN test -n "${CONFIGURATION_DIGEST}" && EXPECTED_ENTRY=kalpamani-production-acquire python - <<'CHECK'
import hashlib, json, os, pathlib, stat, sys
def refuse(reason):  # a closed, value-free reason; never a digest, a commit or a field
    print("image check refused: " + reason)
    sys.exit(1)
raw = pathlib.Path("/etc/kalpamani/compiled-configuration.json").read_bytes()
if hashlib.sha256(raw).hexdigest() != os.environ["CONFIGURATION_DIGEST"]:
    refuse("the compiled configuration does not hash to CONFIGURATION_DIGEST")
document = json.loads(raw)
if document.get("entry") != os.environ["EXPECTED_ENTRY"]:
    refuse("the compiled configuration was compiled for another entry")
commit = pathlib.Path("/opt/kalpamani/CODE_COMMIT").read_text().strip()
if document.get("code_commit") != commit:
    refuse("the compiled configuration names another code commit than KALPAMANI_COMMIT")
mode = lambda path: stat.S_IMODE(os.stat(path).st_mode)
if mode("/etc/kalpamani") & 0o055 != 0o055:
    refuse("the configuration directory is not traversable by the runtime user")
if mode("/etc/kalpamani/compiled-configuration.json") & 0o044 != 0o044:
    refuse("the compiled configuration is not readable by the runtime user")
entry = pathlib.Path("/usr/local/bin/" + os.environ["EXPECTED_ENTRY"])
if mode(entry) & 0o055 != 0o055:
    refuse("the entry executable is not executable by the runtime user")
if not entry.read_bytes().startswith(b"#!/bin/sh\n"):
    refuse("the entry executable's shebang is not a POSIX one")
CHECK
USER 10001:10001
CMD ["kalpamani-production-acquire"]

FROM base AS build
ARG CONFIGURATION_DIGEST
COPY --chmod=0555 docker/production/entry/kalpamani-research-build /usr/local/bin/kalpamani-research-build
COPY --chmod=0444 configuration/compiled-configuration.json /etc/kalpamani/compiled-configuration.json
RUN test -n "${CONFIGURATION_DIGEST}" && EXPECTED_ENTRY=kalpamani-research-build python - <<'CHECK'
import hashlib, json, os, pathlib, stat, sys
def refuse(reason):  # a closed, value-free reason; never a digest, a commit or a field
    print("image check refused: " + reason)
    sys.exit(1)
raw = pathlib.Path("/etc/kalpamani/compiled-configuration.json").read_bytes()
if hashlib.sha256(raw).hexdigest() != os.environ["CONFIGURATION_DIGEST"]:
    refuse("the compiled configuration does not hash to CONFIGURATION_DIGEST")
document = json.loads(raw)
if document.get("entry") != os.environ["EXPECTED_ENTRY"]:
    refuse("the compiled configuration was compiled for another entry")
commit = pathlib.Path("/opt/kalpamani/CODE_COMMIT").read_text().strip()
if document.get("code_commit") != commit:
    refuse("the compiled configuration names another code commit than KALPAMANI_COMMIT")
mode = lambda path: stat.S_IMODE(os.stat(path).st_mode)
if mode("/etc/kalpamani") & 0o055 != 0o055:
    refuse("the configuration directory is not traversable by the runtime user")
if mode("/etc/kalpamani/compiled-configuration.json") & 0o044 != 0o044:
    refuse("the compiled configuration is not readable by the runtime user")
entry = pathlib.Path("/usr/local/bin/" + os.environ["EXPECTED_ENTRY"])
if mode(entry) & 0o055 != 0o055:
    refuse("the entry executable is not executable by the runtime user")
if not entry.read_bytes().startswith(b"#!/bin/sh\n"):
    refuse("the entry executable's shebang is not a POSIX one")
CHECK
USER 10001:10001
CMD ["kalpamani-research-build"]
