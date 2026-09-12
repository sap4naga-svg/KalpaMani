"""The task self-check over task metadata v4 (ADR-0036 §2.9, §2.12 step 5).

The runner checks **documented fields only**: ``TaskARN``, ``Family`` and
``Revision`` from the task document, and each container's ``ImageID``. The
earlier claim that the endpoint exposes a subnet CIDR or a public IP is withdrawn
by ADR-0036; placement is the launcher's check, not the task's, and nothing here
pretends otherwise.

The metadata source is injected -- a zero-argument callable returning the decoded
task document -- so this module opens no socket and reads no environment
variable. The production caller reads ``ECS_CONTAINER_METADATA_URI_V4`` and
fetches ``<uri>/task``; that caller is the image's entrypoint, which does not
exist in this repository.

**The environment guard is part of the self-check.** A task context in which any
``KALPAMANI_*`` variable is present refuses: a private value must never arrive
through a task-definition environment entry or a launch override, and the
cheapest way to hold that line is to refuse the whole run when one appears.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

from kalpamani.data.production.sharadar.documents import exact_int, exact_str
from kalpamani.data.production.sharadar.release import TASK_ARN_RE, TASK_DEFINITION_ARN_RE
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for

#: The one environment variable a task runner may read, and the prefix it must
#: refuse to find.
METADATA_URI_ENV_VAR: Final = "ECS_CONTAINER_METADATA_URI_V4"
PRIVATE_ENV_PREFIX: Final = "KALPAMANI_"

#: An image digest as the metadata reports it: ``sha256:`` and 64 lowercase hex.
IMAGE_DIGEST_RE: Final = re.compile(r"sha256:[0-9a-f]{64}")

#: A task-definition family and a registered revision.
FAMILY_RE: Final = re.compile(r"[A-Za-z0-9_-]{1,255}")


@dataclass(frozen=True, slots=True, kw_only=True)
class CompiledTask:
    """What the image compiles about itself: family, exact revision, own digest."""

    actor: ProductionActor
    family: str
    revision: int
    image_digest: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("CompiledTask may not be subclassed")

    def __post_init__(self) -> None:
        """Hold the constants to their grammars, and the family to the actor's."""
        if type(self.actor) is not ProductionActor:
            raise ValueError("actor must be an exact ProductionActor member")
        if self.family != constants_for(self.actor).task_family:
            raise ValueError("the compiled family is not this actor's family")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("the compiled revision must be a positive integer")
        if type(self.image_digest) is not str or not IMAGE_DIGEST_RE.fullmatch(self.image_digest):
            raise ValueError("the compiled image digest must be sha256:<64 hex>")


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskMetadata:
    """The documented fields of one task metadata v4 document, and nothing else."""

    task_arn: str
    family: str
    revision: int
    image_ids: tuple[str, ...]

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("TaskMetadata may not be subclassed")

    def __repr__(self) -> str:
        """Counts only. **Never the ARN.**"""
        return f"TaskMetadata(containers={len(self.image_ids)})"

    @property
    def task_id(self) -> str:
        """The task id, the last segment of the task ARN."""
        return self.task_arn.rsplit("/", 1)[1]

    def task_definition_arn(self) -> str:
        """The exact task-definition ARN this task runs, rebuilt from documented fields.

        The task ARN carries the partition, region and account; the family and the
        revision are the task document's own. The result is what a release must
        name.
        """
        match = TASK_ARN_RE.fullmatch(self.task_arn)
        if match is None:  # pragma: no cover - parse_task_metadata guarantees the grammar
            raise ValueError("task ARN grammar")
        prefix = self.task_arn[: self.task_arn.index(":task/")]
        arn = f"{prefix}:task-definition/{self.family}:{self.revision}"
        if TASK_DEFINITION_ARN_RE.fullmatch(arn) is None:  # pragma: no cover - grammar-bounded
            raise ValueError("task definition ARN grammar")
        return arn


def parse_task_metadata(document: object) -> TaskMetadata | None:
    """The documented fields of a task metadata v4 document, or ``None``.

    ``None`` for anything that is not an object carrying a well-formed ``TaskARN``,
    a ``Family``, a positive integer ``Revision`` (the endpoint reports it as a
    string, which is admitted; an integer is admitted too) and a non-empty
    ``Containers`` list in which every entry carries a well-formed ``ImageID``.
    """
    if not isinstance(document, dict):
        return None
    payload: dict[str, Any] = document
    task_arn = exact_str(payload.get("TaskARN"))
    if task_arn is None or not TASK_ARN_RE.fullmatch(task_arn):
        return None
    family = exact_str(payload.get("Family"))
    if family is None or not FAMILY_RE.fullmatch(family):
        return None
    raw_revision = payload.get("Revision")
    revision: int | None
    if type(raw_revision) is str and raw_revision.isdigit() and not raw_revision.startswith("0"):
        revision = int(raw_revision)
    else:
        revision = exact_int(raw_revision)
    if revision is None or revision < 1:
        return None
    containers = payload.get("Containers")
    if not isinstance(containers, list) or not containers:
        return None
    image_ids: list[str] = []
    for container in containers:
        if not isinstance(container, dict):
            return None
        image_id = exact_str(container.get("ImageID"))
        if image_id is None or not IMAGE_DIGEST_RE.fullmatch(image_id):
            return None
        image_ids.append(image_id)
    return TaskMetadata(
        task_arn=task_arn, family=family, revision=revision, image_ids=tuple(image_ids)
    )


def self_check_refusal(metadata: TaskMetadata, compiled: CompiledTask) -> str | None:
    """Why the task is not the one its image was compiled for, or ``None``.

    Family and revision must equal the compiled ones; every container's image must
    be the compiled digest (a sidecar with another image would be a container this
    image did not compile). Value-free reasons only.
    """
    if type(metadata) is not TaskMetadata or type(compiled) is not CompiledTask:
        return "the self-check received no usable metadata"
    if metadata.family != compiled.family:
        return "the task family is not the compiled family"
    if metadata.revision != compiled.revision:
        return "the task-definition revision is not the compiled revision"
    if any(image_id != compiled.image_digest for image_id in metadata.image_ids):
        return "a container image is not the compiled image digest"
    return None


def task_environment_refusal(variable_names: Iterable[str]) -> str | None:
    """Why a task context is refused for its environment, or ``None``.

    ``variable_names`` are the *names* present -- values are never read. Any name
    beginning with ``KALPAMANI_`` refuses, so a private path, identifier or value
    cannot have been injected by an override or a task-definition entry.
    """
    for name in variable_names:
        if type(name) is str and name.startswith(PRIVATE_ENV_PREFIX):
            return "a private KalpaMani environment variable is present in the task context"
    return None


__all__ = [
    "FAMILY_RE",
    "IMAGE_DIGEST_RE",
    "METADATA_URI_ENV_VAR",
    "PRIVATE_ENV_PREFIX",
    "CompiledTask",
    "TaskMetadata",
    "parse_task_metadata",
    "self_check_refusal",
    "task_environment_refusal",
]
