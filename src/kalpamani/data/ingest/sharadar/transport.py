"""The transport boundary: the one place in this package that could open a socket.

**Everything network-capable is behind :class:`SharadarTransport`, and the client
has no default.** A :class:`~kalpamani.data.ingest.sharadar.client.SharadarClient`
cannot be constructed without one being handed in, so a test that forgets to
inject a fake gets a ``TypeError`` rather than a request to a vendor. Tests use a
synthetic transport and never reach a network; there is no code path from
``import`` to a connection.

:class:`UrllibTransport` is the concrete implementation, written from the standard
library so no HTTP dependency enters the project. **It is dormant in this slice.**
Nothing in the repository constructs it -- not the package, not a script, not a
test -- and a boundary test holds that true. It exists so that the authorized
runner slice has a reviewed transport to inject rather than one written in a hurry
next to a real credential.

**A failing response is never read.** ``urlopen`` raises :class:`~urllib.error.HTTPError`
for a 4xx or 5xx, and that exception *is* the response object -- reading it is one
attribute access away. This transport closes it and returns the status with an
empty body instead, so a vendor error page has no route into a log, an exception
or a Bronze object. The status alone is what the client's closed error vocabulary
needs.

**Network failures become codes, not tracebacks.** A URL passed to ``urlopen``
appears in :class:`~urllib.error.URLError` chains and in socket-level messages, so
every failure is converted to a :class:`TransportUnavailableError` carrying a
:class:`~kalpamani.data.ingest.sharadar.redaction.SharadarErrorCode` and nothing
else, with the original exception suppressed via ``from None``.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Protocol

from kalpamani.data.ingest.sharadar.redaction import SharadarErrorCode

#: Longest timeout a caller may request. A request with no effective ceiling is a
#: request that can hold a run open indefinitely.
MAX_TIMEOUT_SECONDS: Final = 300.0


@dataclass(frozen=True, slots=True, kw_only=True)
class TransportResponse:
    """One HTTP response, reduced to the two things the client may look at.

    ``body`` is empty for any failing status: the transport does not read a
    vendor error page, so there is nothing to carry.
    """

    status: int
    body: bytes


class TransportUnavailableError(Exception):
    """A network-level failure, carrying a closed code and nothing else.

    Deliberately not a :class:`~kalpamani.common.errors.KalpaManiError`: it is an
    internal signal between the transport and the client, which converts it into
    the boundary's own :class:`~kalpamani.data.ingest.sharadar.redaction.SharadarRequestError`.
    """

    __slots__ = ("code",)

    def __init__(self, code: SharadarErrorCode) -> None:
        """Carry ``code``. There is no field for a URL, a host or a message."""
        self.code = code
        super().__init__(code.value)


class SharadarTransport(Protocol):
    """Everything the client needs from a network, and nothing more.

    One method, ``GET`` only. No session, no cookie jar, no redirect policy, no
    connection pool: each of those is state that outlives a request, and state
    that outlives a request is where a credential ends up being cached.
    """

    def get(
        self, *, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> TransportResponse:
        """Perform one GET.

        Raises:
            TransportUnavailableError: on any network-level failure. The
                implementation must not let a URL, a host or a socket message
                escape in the exception.
        """
        ...


class UrllibTransport:
    """A standard-library HTTPS transport. **Dormant: nothing constructs it here.**

    Adds no dependency, holds no state between calls, and refuses any URL that is
    not HTTPS before ``urlopen`` sees it -- which is what keeps ``file://`` and
    other schemes out of a function that would happily open them.
    """

    def get(
        self, *, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> TransportResponse:
        """Perform one GET, disclosing nothing on failure."""
        if not url.startswith("https://"):
            raise TransportUnavailableError(SharadarErrorCode.REQUEST_SCHEME_REFUSED)
        if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise TransportUnavailableError(SharadarErrorCode.REQUEST_MALFORMED)
        request = urllib.request.Request(  # noqa: S310 - scheme is checked immediately above
            url, headers=dict(headers), method="GET"
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - scheme is checked immediately above
                request, timeout=timeout_seconds
            ) as response:
                return TransportResponse(status=int(response.status), body=response.read())
        except urllib.error.HTTPError as exc:
            # The body of a failing response is NOT read. This exception is the
            # response object, so reading it is one attribute away -- and a vendor
            # error page is exactly what must never reach a log or a Bronze object.
            exc.close()
            return TransportResponse(status=int(exc.code), body=b"")
        except TimeoutError:
            raise TransportUnavailableError(SharadarErrorCode.NETWORK_TIMEOUT) from None
        except urllib.error.URLError:
            raise TransportUnavailableError(SharadarErrorCode.NETWORK_UNREACHABLE) from None
        except OSError:
            raise TransportUnavailableError(SharadarErrorCode.RESPONSE_READ_FAILED) from None


__all__ = [
    "MAX_TIMEOUT_SECONDS",
    "SharadarTransport",
    "TransportResponse",
    "TransportUnavailableError",
    "UrllibTransport",
]
