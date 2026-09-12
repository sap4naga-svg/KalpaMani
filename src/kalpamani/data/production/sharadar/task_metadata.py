"""The task metadata v4 source: one bounded read of ``<uri>/task`` (ADR-0036 §2.9, §2.12 step 5).

The accepted self-check (:mod:`metadata`) takes the decoded task document through an
injected callable and reads documented fields only. This module supplies that callable's
*production shape* without performing the read itself: the HTTP fetch is injected, so the
module opens no socket and names no SDK, and everything around the fetch -- where it may
go, how long it may wait, how much it may read, what it accepts back -- is decided here
and tested here.

**Destination.** The only source is the ECS task metadata endpoint v4, reached at the URI
the agent places in ``ECS_CONTAINER_METADATA_URI_V4`` with ``/task`` appended (the
documented task-level path). The URI is parsed, never prefix-matched: scheme ``http``,
host exactly the link-local metadata address, no userinfo, no port other than 80, a
``/v4/`` path and nothing after it. Anything else is refused before the fetch, so a
variable pointing anywhere else costs nothing and reaches nothing.

**Bounds.** One read, a compiled timeout, a compiled byte ceiling checked on what came
back, strict UTF-8, no byte-order mark, no duplicate keys. The document is then handed
to the accepted parser, which admits only documented fields.

**Contradiction.** The documented ``Cluster`` field carries either the cluster's ARN or
its short name (both are documented v4 representations). A short name must equal the
cluster component of ``TaskARN`` exactly; an ARN must name the same partition, region
and account as ``TaskARN`` and that same cluster. Anything else is a document that
disagrees with itself, refused rather than half-trusted.

**What is not here, on purpose.** No subnet or public-IP self-check: ADR-0036 withdrew
the claim that the endpoint documents either, and placement stays the launcher's check.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from enum import StrEnum
from typing import Any, Final
from urllib.parse import urlsplit

from kalpamani.data.production.sharadar.metadata import (
    METADATA_URI_ENV_VAR,
    TaskMetadata,
    parse_task_metadata,
)
from kalpamani.data.production.sharadar.release import TASK_ARN_RE

#: The link-local address the ECS agent serves task metadata from. Documented, fixed,
#: and the only host a metadata read may reach.
METADATA_HOST: Final = "169.254.170.2"
METADATA_SCHEME: Final = "http"
METADATA_PATH_PREFIX: Final = "/v4/"
TASK_PATH_SUFFIX: Final = "/task"

#: One read, bounded twice: seconds waited and bytes accepted.
METADATA_TIMEOUT_SECONDS: Final = 2.0
MAX_METADATA_BYTES: Final = 64 * 1024

#: A cluster ARN as ECS reports it in the task document, and the short name it may
#: report instead (the same grammar a cluster name satisfies in a task ARN).
CLUSTER_ARN_RE: Final = re.compile(
    r"arn:(?P<partition>aws):ecs:(?P<region>[a-z0-9-]+):(?P<account>[0-9]{12}):cluster/"
    r"(?P<name>[A-Za-z0-9_-]{1,255})"
)
CLUSTER_NAME_RE: Final = re.compile(r"[A-Za-z0-9_-]{1,255}")


class TaskMetadataDefect(StrEnum):
    """Why no task metadata was obtained. Closed; carries no value."""

    URI_MISSING = "URI_MISSING"
    URI_REFUSED = "URI_REFUSED"
    FETCH_FAILED = "FETCH_FAILED"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    RESPONSE_MALFORMED = "RESPONSE_MALFORMED"
    FIELDS_INCOMPLETE = "FIELDS_INCOMPLETE"
    FIELDS_CONTRADICTORY = "FIELDS_CONTRADICTORY"


class TaskMetadataError(Exception):
    """A refusal built from one closed member and nothing else."""

    __slots__ = ("defect",)

    def __init__(self, defect: TaskMetadataDefect) -> None:
        """Carry the defect. There is no field for a URI, a body or a message."""
        if type(defect) is not TaskMetadataDefect:
            raise TypeError("defect must be an exact TaskMetadataDefect member")
        self.defect = defect
        super().__init__(f"task metadata: {defect.value}")


def _refuse(defect: TaskMetadataDefect) -> TaskMetadataError:
    return TaskMetadataError(defect)


#: The one fetch shape: a URL, a timeout, a byte ceiling; the body, or raise. The
#: production implementation lives in the image entrypoint, not under ``src/``.
MetadataFetch = Callable[[str, float, int], bytes]


def task_metadata_url(base_uri: object) -> str:
    """``<base_uri>/task`` if ``base_uri`` is exactly a v4 metadata URI, else refuse.

    Raises:
        TaskMetadataError: ``URI_MISSING`` for a non-string or empty value,
            ``URI_REFUSED`` for any component outside the documented shape.
    """
    if type(base_uri) is not str or not base_uri:
        raise _refuse(TaskMetadataDefect.URI_MISSING)
    try:
        parts = urlsplit(base_uri)
    except ValueError:
        raise _refuse(TaskMetadataDefect.URI_REFUSED) from None
    if parts.scheme != METADATA_SCHEME or parts.hostname != METADATA_HOST:
        raise _refuse(TaskMetadataDefect.URI_REFUSED)
    if parts.username is not None or parts.password is not None:
        raise _refuse(TaskMetadataDefect.URI_REFUSED)
    try:
        port = parts.port
    except ValueError:
        raise _refuse(TaskMetadataDefect.URI_REFUSED) from None
    if port not in (None, 80) or parts.query or parts.fragment:
        raise _refuse(TaskMetadataDefect.URI_REFUSED)
    path = parts.path
    if not path.startswith(METADATA_PATH_PREFIX) or path.endswith("/"):
        raise _refuse(TaskMetadataDefect.URI_REFUSED)
    container = path[len(METADATA_PATH_PREFIX) :]
    if not container or not re.fullmatch(r"[A-Za-z0-9._-]{1,255}", container):
        raise _refuse(TaskMetadataDefect.URI_REFUSED)
    return f"{METADATA_SCHEME}://{METADATA_HOST}{path}{TASK_PATH_SUFFIX}"


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _refuse(TaskMetadataDefect.RESPONSE_MALFORMED)
        seen[key] = value
    return seen


def decode_task_document(raw: object) -> dict[str, Any]:
    """The task document as a closed object: bounded, strict UTF-8, no duplicate key."""
    if type(raw) is not bytes or not raw:
        raise _refuse(TaskMetadataDefect.RESPONSE_MALFORMED)
    if len(raw) > MAX_METADATA_BYTES:
        raise _refuse(TaskMetadataDefect.RESPONSE_TOO_LARGE)
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _refuse(TaskMetadataDefect.RESPONSE_MALFORMED)
    try:
        text = raw.decode("utf-8")
        document = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except TaskMetadataError:
        raise
    except Exception:
        raise _refuse(TaskMetadataDefect.RESPONSE_MALFORMED) from None
    if type(document) is not dict:
        raise _refuse(TaskMetadataDefect.RESPONSE_MALFORMED)
    return document


def contradiction_refusal(document: dict[str, Any], metadata: TaskMetadata) -> str | None:
    """Why the documented fields disagree with one another, or ``None``.

    ``Cluster`` is optional in the shape this module admits. When present it is either
    the cluster's short name, which must equal the task ARN's cluster component, or a
    cluster ARN in the task ARN's partition, region and account naming that same
    cluster. Value-free reasons only.
    """
    task = TASK_ARN_RE.fullmatch(metadata.task_arn)
    if task is None:
        return "the task ARN did not parse"
    cluster = document.get("Cluster")
    if cluster is None:
        return None
    if type(cluster) is not str:
        return "the cluster field is not a string"
    task_cluster = metadata.task_arn[metadata.task_arn.index(":task/") + 6 :].split("/", 1)[0]
    if CLUSTER_NAME_RE.fullmatch(cluster):
        return None if cluster == task_cluster else "the cluster name is not the task's cluster"
    match = CLUSTER_ARN_RE.fullmatch(cluster)
    if match is None:
        return "the cluster field is neither a cluster name nor a cluster ARN"
    task_prefix = metadata.task_arn[: metadata.task_arn.index(":task/")]
    cluster_prefix = cluster[: cluster.index(":cluster/")]
    if task_prefix != cluster_prefix:
        return "the cluster ARN names another partition, region or account"
    if task_cluster != match.group("name"):
        return "the cluster ARN names another cluster"
    return None


def fetch_task_metadata(
    *, environment: Callable[[str], str | None], fetch: MetadataFetch
) -> dict[str, Any]:
    """One bounded read of the task document, validated, as the self-check's input.

    ``environment`` reads exactly one variable name; ``fetch`` performs the one read.
    The returned document is the decoded object the accepted
    :func:`~kalpamani.data.production.sharadar.metadata.parse_task_metadata` admits,
    already checked here for completeness and self-consistency, so a caller that
    parses it again gets the same answer.

    Raises:
        TaskMetadataError: one closed defect; the fetch's own exception, body and
            URL are never carried.
    """
    url = task_metadata_url(environment(METADATA_URI_ENV_VAR))
    try:
        raw = fetch(url, METADATA_TIMEOUT_SECONDS, MAX_METADATA_BYTES)
    except Exception:
        raise _refuse(TaskMetadataDefect.FETCH_FAILED) from None
    document = decode_task_document(raw)
    metadata = parse_task_metadata(document)
    if metadata is None:
        raise _refuse(TaskMetadataDefect.FIELDS_INCOMPLETE)
    if contradiction_refusal(document, metadata) is not None:
        raise _refuse(TaskMetadataDefect.FIELDS_CONTRADICTORY)
    return document


__all__ = [
    "CLUSTER_ARN_RE",
    "CLUSTER_NAME_RE",
    "MAX_METADATA_BYTES",
    "METADATA_HOST",
    "METADATA_PATH_PREFIX",
    "METADATA_SCHEME",
    "METADATA_TIMEOUT_SECONDS",
    "TASK_PATH_SUFFIX",
    "MetadataFetch",
    "TaskMetadataDefect",
    "TaskMetadataError",
    "contradiction_refusal",
    "decode_task_document",
    "fetch_task_metadata",
    "task_metadata_url",
]
