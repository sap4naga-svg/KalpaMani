"""The production provider adapter: a compiled request, through the accepted transport, once.

**The seam is the accepted client and the accepted transport, and nothing wider.**
A :class:`ProductionRequest` is compiled into the ticker-less request form ADR-0041
proposes (:class:`~kalpamani.data.ingest.sharadar.datasets.CrossSectionRequest`), the
accepted :class:`~kalpamani.data.ingest.sharadar.client.SharadarClient` builds the URL
and runs its one fetch loop over an **injected** transport, and the bytes come back
exactly as received. Every transmitted parameter derives from the compiled request:
the dataset names the path, the window names ``from``/``to``, the page names ``limit``
and ``skip``, the format is the plan's CSV, and the credential is revealed only inside
the accepted URL builder. No other parameter, header, host or destination exists here.

**Unsupported combinations are refused before the transport is invoked.** A window on
the snapshot table, a snapshot on a windowed table, a malformed window, an oversized
page or an unknown dataset is a closed refusal with **zero** transport invocations;
the adapter counts actual transport invocations (``transport_invocations``), and a
local refusal is not one.

**One attempt, no pacing of its own.** The acquisition processor paces every request
on the compiled interval and admits it against the run deadline before this adapter
is called, so the client here is bound to a zero-interval pacer and a one-attempt
retry policy: no hidden retry, no second pacing. The transport's redirect refusal,
timeout, byte ceiling and credential redaction are the accepted transport's and are
not touched.

**Nothing here is a runner.** No credential is retrieved, no transport is
constructed, no entry point exists; the only transport this module has ever been
handed is a scripted fake, and **synthetic transport results are not provider
verification**.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.ingest.sharadar.client import Pacer, RetryPolicy, SharadarClient
from kalpamani.data.ingest.sharadar.credentials import SharadarCredential
from kalpamani.data.ingest.sharadar.datasets import (
    MAX_PAGE_LIMIT,
    WINDOWED_DATASETS,
    CrossSectionRequest,
    DateWindow,
    Page,
    ResponseFormat,
    SharadarDataset,
)
from kalpamani.data.ingest.sharadar.redaction import SharadarRequestError
from kalpamani.data.ingest.sharadar.transport import (
    MAX_TIMEOUT_SECONDS,
    SharadarTransport,
    TransportResponse,
)
from kalpamani.data.production.sharadar.plan import SNAPSHOT_WINDOW, ProductionRequest
from kalpamani.data.qualify.sharadar.plan import TIMEOUT_SECONDS

#: Exactly one attempt per compiled request: the plan's ``provider_max_attempts``.
ONE_ATTEMPT: Final = RetryPolicy(max_attempts=1, backoff_seconds=())

#: The plan's response format. The acquisition record's source-schema version names CSV.
PRODUCTION_FORMAT: Final = ResponseFormat.CSV


class ProviderRefusal(StrEnum):
    """Why a compiled request was refused before any transport invocation. Closed."""

    DATASET_UNSUPPORTED = "DATASET_UNSUPPORTED"
    WINDOW_REQUIRED = "WINDOW_REQUIRED"
    WINDOW_NOT_ALLOWED = "WINDOW_NOT_ALLOWED"
    WINDOW_MALFORMED = "WINDOW_MALFORMED"
    PAGE_MALFORMED = "PAGE_MALFORMED"
    REQUEST_MALFORMED = "REQUEST_MALFORMED"


class ProviderRefusedError(Exception):
    """A closed refusal raised before the transport. Carries a member and nothing else."""

    __slots__ = ("refusal",)

    def __init__(self, refusal: ProviderRefusal) -> None:
        if type(refusal) is not ProviderRefusal:
            raise TypeError("refusal must be an exact ProviderRefusal member")
        self.refusal = refusal
        super().__init__(f"production provider request refused: {refusal.value}")


def _refuse(refusal: ProviderRefusal) -> ProviderRefusedError:
    return ProviderRefusedError(refusal)


def _window(text: str) -> DateWindow:
    try:
        start_text, end_text = text.split("/")
        start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
    except ValueError:
        raise _refuse(ProviderRefusal.WINDOW_MALFORMED) from None
    if start > end or start.isoformat() != start_text or end.isoformat() != end_text:
        raise _refuse(ProviderRefusal.WINDOW_MALFORMED)
    try:
        return DateWindow(start=start, end=end)
    except SharadarRequestError:
        raise _refuse(ProviderRefusal.WINDOW_MALFORMED) from None


def compile_cross_section(request: ProductionRequest) -> CrossSectionRequest:
    """The cross-section request one compiled production request authorizes, or a refusal.

    Deterministic and total over the plan's coordinate grammar: a dataset outside the
    three tables, a window on the snapshot table, ``SNAPSHOT`` on a windowed table, a
    window that is not two ISO dates in order, or a page outside ``1..MAX_PAGE_LIMIT``
    with a non-negative offset is refused. Nothing is transmitted by this function.
    """
    if type(request) is not ProductionRequest:
        raise _refuse(ProviderRefusal.REQUEST_MALFORMED)
    try:
        dataset = SharadarDataset(request.dataset)
    except ValueError:
        raise _refuse(ProviderRefusal.DATASET_UNSUPPORTED) from None
    windowed = dataset in WINDOWED_DATASETS
    if request.window == SNAPSHOT_WINDOW:
        if windowed:
            raise _refuse(ProviderRefusal.WINDOW_REQUIRED)
        window: DateWindow | None = None
    else:
        if not windowed:
            raise _refuse(ProviderRefusal.WINDOW_NOT_ALLOWED)
        window = _window(request.window)
    if (
        type(request.page_limit) is not int
        or not 1 <= request.page_limit <= MAX_PAGE_LIMIT
        or type(request.page_offset) is not int
        or request.page_offset < 0
    ):
        raise _refuse(ProviderRefusal.PAGE_MALFORMED)
    try:
        return CrossSectionRequest(
            dataset=dataset,
            response_format=PRODUCTION_FORMAT,
            page=Page(limit=request.page_limit, skip=request.page_offset),
            window=window,
        )
    except SharadarRequestError:
        raise _refuse(ProviderRefusal.REQUEST_MALFORMED) from None


class _CountingTransport:
    """Count every actual transport invocation, then forward it unchanged."""

    __slots__ = ("_get", "_max_response_bytes", "invocations")

    def __init__(self, transport: SharadarTransport) -> None:
        get = getattr(transport, "get", None)
        if not callable(get):
            raise TypeError("a transport must provide a callable get")
        ceiling = getattr(transport, "max_response_bytes", None)
        if type(ceiling) is not int or ceiling <= 0:
            raise TypeError("a transport must declare a positive max_response_bytes")
        self._get = get
        self._max_response_bytes = ceiling
        self.invocations = 0

    @property
    def max_response_bytes(self) -> int:
        return self._max_response_bytes

    def get(
        self, *, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> TransportResponse:
        self.invocations += 1
        response: TransportResponse = self._get(
            url=url, headers=headers, timeout_seconds=timeout_seconds
        )
        return response


@dataclass(frozen=True, slots=True, kw_only=True)
class _NoSleep:
    """A sleeper the zero-interval pacer never needs. Calling it is a defect."""

    def __call__(self, seconds: float) -> None:
        raise ProviderRefusedError(ProviderRefusal.REQUEST_MALFORMED)


class SharadarProductionProvider:
    """The one :class:`ProductionProvider` implementation that reaches the accepted transport.

    Constructed from an injected transport and the compiled per-request timeout;
    constructs no transport, holds no credential, and paces nothing itself.
    """

    __slots__ = ("_timeout", "_transport")

    def __init__(
        self, *, transport: SharadarTransport, timeout_seconds: float = TIMEOUT_SECONDS
    ) -> None:
        if type(timeout_seconds) is not float or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise TypeError("timeout_seconds must be a positive float within the transport ceiling")
        self._transport = _CountingTransport(transport)
        self._timeout = timeout_seconds

    def __repr__(self) -> str:
        """Invocation count only. **Never a URL, never a credential.**"""
        return f"SharadarProductionProvider(transport_invocations={self.transport_invocations})"

    @property
    def transport_invocations(self) -> int:
        """Actual transport invocations so far. A local refusal is not one."""
        return self._transport.invocations

    def fetch(self, request: ProductionRequest, *, credential: SharadarCredential) -> bytes:
        """The response body for one compiled request, through one transport call.

        Raises:
            ProviderRefusedError: for a request the adapter refuses before the transport.
            SharadarRequestError: the accepted client's sanitized refusal for anything
                the transport or the response did -- never a URL, query or body.
        """
        cross_section = compile_cross_section(request)
        if type(credential) is not SharadarCredential:
            raise _refuse(ProviderRefusal.REQUEST_MALFORMED)
        client = SharadarClient(
            credential=credential,
            transport=self._transport,
            pacer=Pacer(min_interval=0.0, clock=lambda: 0.0, sleeper=_NoSleep()),
            retry_policy=ONE_ATTEMPT,
            timeout_seconds=self._timeout,
        )
        return client.fetch_cross_section(cross_section)


def transport_invocations_of(provider: Any) -> int | None:
    """The provider's actual transport invocation count, if it reports one."""
    count = getattr(provider, "transport_invocations", None)
    return count if type(count) is int else None


__all__ = [
    "ONE_ATTEMPT",
    "PRODUCTION_FORMAT",
    "ProviderRefusal",
    "ProviderRefusedError",
    "SharadarProductionProvider",
    "compile_cross_section",
    "transport_invocations_of",
]
