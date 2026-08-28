"""Deterministic Sharadar request construction, from public documentation only.

Every path segment and parameter name below is taken from the vendor's own
published query examples (`PSR-SHD-118`), and every behavioural rule from a
recorded public source. Nothing here is guessed, and nothing here has been
exercised against the API: **this slice sends no request.**

**Three datasets, and no more.** ``tickers``, ``stocks`` and ``actions`` are the
security-metadata, daily-price and corporate-action surfaces Stage 3A needs.
``fundamentals`` and ``events`` are Phase-3B domains and are deliberately absent
-- a request builder that could reach them would be authority this slice does not
have, hidden inside a convenience.

**Nothing defaults.** The vendor documents ``from`` as *one year ago* and ``to``
as *the prior day* on every temporal table (`PSR-SHD-121`), so a request that
omits them silently means something narrower than it appears to. A
:class:`SharadarRequest` therefore requires an explicit window on a windowed
dataset -- and **refuses** one on ``tickers``, which the vendor states is a
snapshot with no time axis (`PSR-SHD-119`). Format and pagination are required
for the same reason: the vendor's ``limit`` default of 10000 is a silent
truncation boundary, and a caller who did not state a limit did not decide one.

**A table-wide bulk download is not constructible.** ``years=`` triggers a zip of
every security (`PSR-SHD-119`), which is neither a scoped request nor something a
first integration should be able to emit by accident.
:data:`FORBIDDEN_QUERY_PARAMETERS` names it, :data:`QUERY_PARAMETER_ALLOWLIST`
excludes it, and :func:`build_query_parameters` checks both on every call. A
single ticker is required on every request, so there is no shape here that
enumerates the market.

**One ticker per request, because that is what the documentation evidences.** The
public examples show ``ticker=<one symbol>``; a multi-symbol form is not
documented, and inventing one would put an unverified parameter shape on the wire
the first time a real credential is used. How a full-universe backfill is
actually assembled is a decision for the authorized ingestion slice, on evidence
this slice does not have.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING, Final
from urllib.parse import urlencode

from kalpamani.data.contracts.vocabulary import closed_member
from kalpamani.data.ingest.sharadar.redaction import (
    SharadarErrorCode,
    SharadarRequestError,
    SharadarStage,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance for typing only
    from kalpamani.data.ingest.sharadar.credentials import SharadarCredential

#: The provider name recorded in Bronze metadata. Lowercase, path-safe, stable.
PROVIDER: Final = "sharadar"

#: The documented API root (`PSR-SHD-118`). HTTPS is part of the constant, and
#: :func:`build_request_url` refuses anything that does not start with it.
API_BASE_URL: Final = "https://api.sharadar.com/v1.0/data"

#: Largest page the vendor documents (`PSR-SHD-121`). A request may ask for less;
#: it may not ask for more and quietly receive this.
MAX_PAGE_LIMIT: Final = 10000


class SharadarDataset(StrEnum):
    """The three Stage-3A surfaces. Phase-3B tables are deliberately absent."""

    TICKERS = "tickers"
    STOCKS = "stocks"
    ACTIONS = "actions"


#: Datasets carrying a time axis, which therefore **require** an explicit window.
#: ``tickers`` is absent because the vendor calls it a snapshot (`PSR-SHD-119`),
#: and a date range on a table with no time axis is a parameter that means nothing.
WINDOWED_DATASETS: Final[frozenset[SharadarDataset]] = frozenset(
    {SharadarDataset.STOCKS, SharadarDataset.ACTIONS}
)


class ResponseFormat(StrEnum):
    """The response encoding, always stated explicitly."""

    CSV = "csv"
    JSON = "json"


#: Every query parameter this package will ever send. Checked on every build, so a
#: parameter added later has to pass review rather than merely compile.
QUERY_PARAMETER_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {"api_key", "format", "ticker", "from", "to", "limit", "skip"}
)

#: Documented parameters that are refused outright. ``years`` is a table-wide bulk
#: download; ``lastupdated.gte`` is incremental-sync behaviour, which is production
#: ingestion and not authorized; ``fields`` and ``sort`` would make two requests for
#: the same range return differently-shaped bytes, and Bronze identity is the bytes.
FORBIDDEN_QUERY_PARAMETERS: Final[frozenset[str]] = frozenset(
    {"years", "fields", "sort", "lastupdated.gte", "lastupdated"}
)

#: What a US equity symbol is allowed to look like on the wire.
_TICKER: Final = re.compile(r"^[A-Z][A-Z0-9.\-]{0,15}$")

#: The range recorded when a dataset has no time axis.
SNAPSHOT_RANGE: Final = "SNAPSHOT"


def _refuse(code: SharadarErrorCode, dataset: str | None = None) -> SharadarRequestError:
    return SharadarRequestError(stage=SharadarStage.BUILD, code=code, dataset=dataset)


@dataclass(frozen=True, slots=True, kw_only=True)
class DateWindow:
    """An explicit, inclusive request window. There is no implicit default."""

    start: date
    end: date

    def __post_init__(self) -> None:
        # Exact date, so a datetime does not slip in and render an instant where
        # the vendor documents a YYYY-MM-DD filter.
        if type(self.start) is not date or type(self.end) is not date:
            raise _refuse(SharadarErrorCode.REQUEST_MALFORMED)
        if self.start > self.end:
            raise _refuse(SharadarErrorCode.REQUEST_MALFORMED)

    @property
    def requested_range(self) -> str:
        """The range in the form Bronze metadata records it."""
        return f"{self.start.isoformat()}/{self.end.isoformat()}"


@dataclass(frozen=True, slots=True, kw_only=True)
class Page:
    """Explicit pagination. ``skip`` is the vendor's name for the offset.

    Both are required. A caller who did not state a limit did not choose the
    vendor's 10000-row default, and a truncated page that nobody asked about looks
    exactly like a complete one.
    """

    limit: int
    skip: int

    def __post_init__(self) -> None:
        # Exact int, so True does not silently become a limit of 1.
        if type(self.limit) is not int or not 1 <= self.limit <= MAX_PAGE_LIMIT:
            raise _refuse(SharadarErrorCode.REQUEST_MALFORMED)
        if type(self.skip) is not int or self.skip < 0:
            raise _refuse(SharadarErrorCode.REQUEST_MALFORMED)

    def advanced(self) -> Page:
        """The next page. Deterministic, and the only way to walk a result set."""
        return Page(limit=self.limit, skip=self.skip + self.limit)


@dataclass(frozen=True, slots=True, kw_only=True)
class SharadarRequest:
    """One fully-specified request. Every decision is stated, none is defaulted."""

    dataset: SharadarDataset
    ticker: str
    response_format: ResponseFormat
    page: Page
    window: DateWindow | None

    def __post_init__(self) -> None:
        # Normalised before anything reads `.value`. These are StrEnums, so a bare
        # "stocks" compares equal to the member, satisfies `in WINDOWED_DATASETS`
        # and only differs where the query is built -- which is the one place that
        # matters. An annotation is not a check.
        dataset = closed_member(SharadarDataset, self.dataset)
        if dataset is None:
            raise _refuse(SharadarErrorCode.REQUEST_MALFORMED)
        object.__setattr__(self, "dataset", dataset)
        response_format = closed_member(ResponseFormat, self.response_format)
        if response_format is None:
            raise _refuse(SharadarErrorCode.REQUEST_MALFORMED, dataset.value)
        object.__setattr__(self, "response_format", response_format)

        if type(self.ticker) is not str or not _TICKER.match(self.ticker):
            raise _refuse(SharadarErrorCode.REQUEST_MALFORMED, dataset.value)
        if type(self.page) is not Page:
            raise _refuse(SharadarErrorCode.REQUEST_MALFORMED, dataset.value)
        if self.window is not None and type(self.window) is not DateWindow:
            raise _refuse(SharadarErrorCode.REQUEST_MALFORMED, dataset.value)
        windowed = dataset in WINDOWED_DATASETS
        if windowed and self.window is None:
            raise _refuse(SharadarErrorCode.REQUEST_MALFORMED, dataset.value)
        if not windowed and self.window is not None:
            raise _refuse(SharadarErrorCode.REQUEST_MALFORMED, dataset.value)

    @property
    def requested_range(self) -> str:
        """What Bronze records as this request's range. ``SNAPSHOT`` when untimed."""
        return self.window.requested_range if self.window is not None else SNAPSHOT_RANGE


def build_query_parameters(
    request: SharadarRequest, *, credential: SharadarCredential
) -> tuple[tuple[str, str], ...]:
    """The exact query parameters for ``request``, in a fixed order.

    **The return value carries the credential.** Hand it straight to
    :func:`build_request_url`; do not log it, store it or put it in an exception.

    Raises:
        SharadarRequestError: if the built parameter names are not a subset of
            :data:`QUERY_PARAMETER_ALLOWLIST`, or intersect
            :data:`FORBIDDEN_QUERY_PARAMETERS`. Checked on every call rather than
            trusted from reading this function, because the check is what a future
            edit has to get past.
    """
    parameters: list[tuple[str, str]] = [
        ("api_key", credential.reveal()),
        ("format", request.response_format.value),
        ("ticker", request.ticker),
    ]
    if request.window is not None:
        parameters.append(("from", request.window.start.isoformat()))
        parameters.append(("to", request.window.end.isoformat()))
    parameters.append(("limit", str(request.page.limit)))
    parameters.append(("skip", str(request.page.skip)))

    names = {name for name, _ in parameters}
    if not names <= QUERY_PARAMETER_ALLOWLIST or names & FORBIDDEN_QUERY_PARAMETERS:
        raise _refuse(SharadarErrorCode.REQUEST_MALFORMED, request.dataset.value)
    return tuple(parameters)


def build_request_url(request: SharadarRequest, *, credential: SharadarCredential) -> str:
    """Build one request URL.

    **Never log, print, store or include the return value in an exception.** The
    credential is inside it (`PSR-SHD-109`), which is why the whole of
    :mod:`~kalpamani.data.ingest.sharadar.redaction` exists.

    Raises:
        SharadarRequestError: if the result is not an HTTPS URL under
            :data:`API_BASE_URL`. A constant cannot normally fail this; the check
            is here so that a future edit to the constant fails closed instead of
            sending a credential over an unencrypted or unexpected route.
    """
    parameters = build_query_parameters(request, credential=credential)
    url = f"{API_BASE_URL}/{request.dataset.value}?{urlencode(parameters)}"
    if not url.startswith("https://"):
        raise _refuse(SharadarErrorCode.REQUEST_SCHEME_REFUSED, request.dataset.value)
    return url


def describe_request(request: SharadarRequest) -> str:
    """A disclosure-free description of ``request``, safe to log.

    No scheme, no host, no query string, no credential -- so it survives
    :func:`~kalpamani.data.ingest.sharadar.redaction.redact` unchanged and can be
    recorded in Bronze notes without tripping the disclosure guard.
    """
    return (
        f"{PROVIDER} {request.dataset.value} ticker {request.ticker} "
        f"range {request.requested_range} limit {request.page.limit} skip {request.page.skip}"
    )


__all__ = [
    "API_BASE_URL",
    "FORBIDDEN_QUERY_PARAMETERS",
    "MAX_PAGE_LIMIT",
    "PROVIDER",
    "QUERY_PARAMETER_ALLOWLIST",
    "SNAPSHOT_RANGE",
    "WINDOWED_DATASETS",
    "DateWindow",
    "Page",
    "ResponseFormat",
    "SharadarDataset",
    "SharadarRequest",
    "build_query_parameters",
    "build_request_url",
    "describe_request",
]
