"""Error hygiene for the Sharadar boundary: a closed vocabulary, not a redaction pass.

**Why this module exists at all.** The Sharadar API takes its key as a query
parameter (`PSR-SHD-109`). Every request URL this package builds therefore *is* a
credential, in full, in a single string. A log line, a traceback, an exception
message or a repr that carried one would disclose it -- and once a value has been
printed there is no recalling it, which INC-0002 already established the hard way.

**The primary control is construction, not filtering.** A
:class:`SharadarRequestError` is assembled from three closed vocabularies -- a
stage, a code and a dataset label -- so a response body, a URL or a key is not
*redacted* out of the message, it has no parameter to arrive through. A vendor
payload cannot be a :class:`SharadarErrorCode`, and the dataset label is held to a
strict pattern so a CSV body handed in where a name was expected becomes
``<unnamed>`` rather than an error message.

:func:`redact` is the secondary control, applied to anything a caller does hand
in. It exists for defence in depth and for the case this module cannot foresee.
Order matters in :data:`_REDACTIONS`: a whole URL is consumed first, taking its
query string and key with it, then a bare ``api_key=`` assignment, then a bare
query string. Reversing that would leave a scheme-qualified host standing.

**Response bodies never enter an error.** The client does not read a body on a
failing status, and there is no field here to put one in if it did.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

from kalpamani.data.contracts.errors import PointInTimeError


class SharadarStage(StrEnum):
    """Where a failure happened. Part of the error's closed vocabulary."""

    BUILD = "build"
    FETCH = "fetch"
    PUBLISH = "publish"


class SharadarErrorCode(StrEnum):
    """Every failure this boundary can report. A response body is not among them.

    The categories are deliberately coarse. A finer vocabulary would have to be
    derived from something the vendor said, and the only place the vendor says
    anything is the response body -- which is exactly what must not reach a log.
    """

    HTTP_AUTHORIZATION_REFUSED = "HTTP_AUTHORIZATION_REFUSED"
    HTTP_ENDPOINT_NOT_FOUND = "HTTP_ENDPOINT_NOT_FOUND"
    HTTP_RATE_LIMITED = "HTTP_RATE_LIMITED"
    HTTP_CLIENT_ERROR = "HTTP_CLIENT_ERROR"
    HTTP_SERVER_ERROR = "HTTP_SERVER_ERROR"
    HTTP_UNEXPECTED_STATUS = "HTTP_UNEXPECTED_STATUS"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    NETWORK_UNREACHABLE = "NETWORK_UNREACHABLE"
    RESPONSE_READ_FAILED = "RESPONSE_READ_FAILED"
    REQUEST_SCHEME_REFUSED = "REQUEST_SCHEME_REFUSED"
    REQUEST_MALFORMED = "REQUEST_MALFORMED"


#: Conditions a bounded retry may legitimately attempt again.
#:
#: **Authorization refusal is deliberately absent.** A rejected key is rejected on
#: every attempt, so retrying it converts one refused request into several -- which
#: is how an accidental key mix-up becomes a rate-limit incident. A 4xx that is not
#: a rate limit is likewise the caller's defect and will not fix itself.
RETRYABLE_CODES: Final[frozenset[SharadarErrorCode]] = frozenset(
    {
        SharadarErrorCode.HTTP_RATE_LIMITED,
        SharadarErrorCode.HTTP_SERVER_ERROR,
        SharadarErrorCode.NETWORK_TIMEOUT,
        SharadarErrorCode.NETWORK_UNREACHABLE,
        SharadarErrorCode.RESPONSE_READ_FAILED,
    }
)

#: What a dataset label is allowed to look like. A vendor payload does not match
#: it, which is the point: an error is not a channel for content.
_DATASET_LABEL: Final = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

#: Substituted for a label that fails the pattern. Refusing outright inside an
#: exception constructor would replace the original failure with a second one and
#: lose the first.
UNNAMED_DATASET: Final = "<unnamed>"

#: Applied to anything a caller hands in. Order matters -- see the module docstring.
_REDACTIONS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"https?://\S*"), "<url-redacted>"),
    (re.compile(r"api[_-]?key\s*=\s*\S*", re.IGNORECASE), "<key-redacted>"),
    (re.compile(r"\?[^\s]*=\S*"), "?<query-redacted>"),
)


def redact(text: str) -> str:
    """Strip URLs, query strings and anything key-shaped out of ``text``."""
    out = text
    for pattern, replacement in _REDACTIONS:
        out = pattern.sub(replacement, out)
    return out


def safe_dataset_label(label: str | None) -> str | None:
    """A dataset name if it looks like one, ``<unnamed>`` if it does not, else ``None``."""
    if label is None:
        return None
    return label if _DATASET_LABEL.match(label) else UNNAMED_DATASET


def classify_http_status(status: int) -> SharadarErrorCode:
    """A sanitized category for an HTTP status. Never the body, never the URL."""
    if status in (401, 403):
        return SharadarErrorCode.HTTP_AUTHORIZATION_REFUSED
    if status == 404:
        return SharadarErrorCode.HTTP_ENDPOINT_NOT_FOUND
    if status == 429:
        return SharadarErrorCode.HTTP_RATE_LIMITED
    if 400 <= status < 500:
        return SharadarErrorCode.HTTP_CLIENT_ERROR
    if 500 <= status < 600:
        return SharadarErrorCode.HTTP_SERVER_ERROR
    return SharadarErrorCode.HTTP_UNEXPECTED_STATUS


class SharadarRequestError(PointInTimeError):
    """A provider-boundary failure, describable without disclosing anything.

    Every field is drawn from a closed vocabulary or held to a strict pattern, so
    the message is *assembled from an allowlist* rather than filtered afterwards.
    There is no parameter for a URL, a query string, a credential or a response
    body, which is a stronger guarantee than remembering not to pass one.
    """

    __slots__ = ("code", "dataset", "retryable", "stage")

    def __init__(
        self,
        *,
        stage: SharadarStage,
        code: SharadarErrorCode,
        dataset: str | None = None,
    ) -> None:
        """Build the error from a stage, a code and an optional dataset label."""
        self.stage = stage
        self.code = code
        self.dataset = safe_dataset_label(dataset)
        self.retryable = code in RETRYABLE_CODES
        located = f"{stage.value} [{self.dataset}]" if self.dataset else stage.value
        super().__init__(redact(f"sharadar {located}: {code.value}"))


__all__ = [
    "RETRYABLE_CODES",
    "UNNAMED_DATASET",
    "SharadarErrorCode",
    "SharadarRequestError",
    "SharadarStage",
    "classify_http_status",
    "redact",
    "safe_dataset_label",
]
