# syntax=docker/dockerfile:1.7
#
# KalpaMani production task images (ADR-0036 s.2.9, ADR-0043, ADR-0044 s.2/s.6).
#
# One Dockerfile, two build targets -- `acquire` and `build` -- each producing ONE
# actor's image. An image carries the code, the accepted SDK pins, ONE entry executable
# named exactly as the task definition's `command` token, and ONE compiled configuration
# file generated at the image gate (docs/operations/production-image-build.md).
#
# Nothing here is built or published by the repository: the image gate is a separately
# authorized owner action. Every input that the repository cannot know is a REQUIRED
# build argument with no default, so an unconfigured build fails rather than producing
# an image that would "work" with a placeholder:
#
#   BASE_IMAGE_DIGEST   sha256:<64 hex> of the python:3.11-slim base the owner pinned
#   KALPAMANI_COMMIT    the 40-hex commit the build context was checked out at; the
#                       image records it and refuses to build from a dirty tree elsewhere
#
# The compiled configuration is COPIED from a git-ignored staging path in the build
# context (docker/production/build/<entry>/compiled-configuration.json); an absent file
# fails the build. The image's own digest and its task-definition revision are never
# written into the image (ADR-0044 s.2): the launch tool attests both in the release.

ARG BASE_IMAGE_DIGEST
FROM python:3.11-slim@${BASE_IMAGE_DIGEST} AS base

ARG KALPAMANI_COMMIT
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# A dedicated, unprivileged runtime user. The task holds no shell session (ecs:ExecuteCommand
# is denied) and the root filesystem is read-only under the task definition.
RUN groupadd --system kalpamani && useradd --system --gid kalpamani --no-create-home \
    --shell /usr/sbin/nologin kalpamani

WORKDIR /opt/kalpamani
COPY pyproject.toml ./
COPY docker/production/constraints.txt ./docker/production/constraints.txt
COPY src ./src
COPY scripts/production_task_entrypoint.py ./scripts/production_task_entrypoint.py

# The SDK pins are the ones the repository's verified environment carries; the package
# itself is installed without dependency resolution so nothing beyond the constraints
# file can arrive. No dev, test or cloud CLI tooling exists in the image.
RUN python -m pip install --no-deps --constraint docker/production/constraints.txt \
        --requirement docker/production/constraints.txt \
    && python -m pip install --no-deps . \
    && test -n "${KALPAMANI_COMMIT}" \
    && printf '%s\n' "${KALPAMANI_COMMIT}" > /opt/kalpamani/CODE_COMMIT \
    && python - <<'CHECK'
import re, pathlib, sys
commit = pathlib.Path("/opt/kalpamani/CODE_COMMIT").read_text().strip()
sys.exit(0 if re.fullmatch(r"[0-9a-f]{40}", commit) else 1)
CHECK

# Neither target carries a shell entrypoint: the task definition's `command` token is the
# executable, and the executable is the actor's entry and nothing else.
FROM base AS acquire
COPY --chmod=0555 docker/production/entry/kalpamani-production-acquire /usr/local/bin/kalpamani-production-acquire
COPY --chmod=0444 docker/production/build/acquire/compiled-configuration.json /etc/kalpamani/compiled-configuration.json
USER kalpamani
CMD ["kalpamani-production-acquire"]

FROM base AS build
COPY --chmod=0555 docker/production/entry/kalpamani-research-build /usr/local/bin/kalpamani-research-build
COPY --chmod=0444 docker/production/build/build/compiled-configuration.json /etc/kalpamani/compiled-configuration.json
USER kalpamani
CMD ["kalpamani-research-build"]
