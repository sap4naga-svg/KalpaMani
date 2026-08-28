"""The transport boundary: the one place in this package that could open a socket.

**Everything network-capable is behind :class:`SharadarTransport`, and the client
has no default.** A :class:`~kalpamani.data.ingest.sharadar.client.SharadarClient`
cannot be constructed without one being handed in, so a test that forgets to
inject a fake gets a ``TypeError`` rather than a request to a vendor. There is no
code path from ``import`` to a connection.

:class:`UrllibTransport` is the concrete implementation, written from the standard
library so no HTTP dependency enters the project. **Nothing in the repository
constructs it outside its own synthetic unit test** -- no production module, no
script, no runner -- and an architecture test holds that true. Its opener is
injectable, so every rule below is proven against a fake rather than asserted in a
docstring: *dormant* must not be allowed to mean *untested*.

Four rules exist because the credential is in the query string
(`PSR-SHD-109`), which makes a request URL a credential in one string.

**The origin is pinned exactly, by parsing.** ``url.startswith("https://")`` is not
an origin check. A host of the form ``<allowed-host>.attacker.example`` passes it,
and so does a userinfo prefix -- ``<allowed-host>:key@somewhere-else`` -- where the
part that reads as the host to a human is not the host at all. The URL is parsed
and every component is required to match: scheme, host, port, empty userinfo,
empty fragment, and a path under the documented data prefix. Anything else is
refused before ``urlopen`` sees it.

**Redirects are refused, never followed.** A 3xx would hand the query string -- and
therefore the key -- to whatever host the ``Location`` header names, and that
header is attacker-influenced exactly when the response is not the one expected.
The opener's redirect handler returns ``None``, so urllib raises instead of
following; the status becomes ``HTTP_REDIRECT_REFUSED``, the body is not read, the
target is never contacted, and ``Location`` is never surfaced.

**Ambient proxy discovery is off.** The default opener reads ``HTTPS_PROXY`` and,
on Windows, the system proxy settings -- so an environment variable could route a
credential-bearing request through a host nobody chose. This transport builds its
own opener with an empty :class:`~urllib.request.ProxyHandler` and never installs
it globally. A governed proxy configuration would be a separate decision.

**A successful body is bounded.** ``read()`` with no ceiling lets a response size
decided by the other end decide this process's memory. At most
``max_response_bytes + 1`` is read, so an oversized response is detected without
being loaded; a ``Content-Length`` already over the limit refuses before any body
is read at all.

**Headers are validated here, not left to urllib.** ``Request`` stores a header
without checking it, and a ``CR LF`` in a value is only rejected much later, at
send time -- so a split-request attempt would look well formed in between. Names
and values are held to strict ASCII token grammars before an opener sees them.

**A failing response is never read.** ``urlopen`` raises
:class:`~urllib.error.HTTPError` for a 4xx or 5xx, and that exception *is* the
response object -- reading it is one attribute access away. This transport closes
it and returns the status with an empty body instead, so a vendor error page has no
route into a log, an exception or a Bronze object.

**Network failures become codes, not tracebacks.** A URL appears in
:class:`~urllib.error.URLError` chains and in socket-level messages, so every
failure is converted to a :class:`TransportUnavailableError` carrying a
:class:`~kalpamani.data.ingest.sharadar.redaction.SharadarErrorCode` and nothing
else, with the original exception suppressed via ``from None``.
"""

from __future__ import annotations

import http.client
import math
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol
from urllib.parse import urlsplit

from kalpamani.data.ingest.sharadar.datasets import API_BASE_URL
from kalpamani.data.ingest.sharadar.redaction import SharadarErrorCode, safe_code

#: Longest timeout a caller may request. A request with no effective ceiling is a
#: request that can hold a run open indefinitely.
MAX_TIMEOUT_SECONDS: Final = 300.0

#: Default ceiling on a successful response body: 64 MiB.
#:
#: Chosen against the largest page this package can ask for. The documented
#: maximum is 10,000 rows (`PSR-SHD-121`), and a daily-price row is a few dozen
#: bytes of CSV -- so a full page is on the order of one megabyte. 64 MiB leaves
#: roughly two orders of magnitude of headroom for a wider table, a verbose JSON
#: encoding or a future column, while still bounding what one response can cost
#: this process. It is a memory bound, not a data-volume policy.
DEFAULT_MAX_RESPONSE_BYTES: Final = 64 * 1024 * 1024

#: The largest ceiling any caller may configure: 256 MiB. A bound on the bound, so
#: "make the limit bigger" cannot quietly become "make the limit meaningless".
MAX_RESPONSE_BYTES_CEILING: Final = 256 * 1024 * 1024

#: The exact origin this transport will talk to, derived from the documented API
#: root rather than restated -- a second literal is a second thing to drift.
_ALLOWED = urlsplit(API_BASE_URL)
ALLOWED_SCHEME: Final = _ALLOWED.scheme
ALLOWED_HOST: Final = _ALLOWED.hostname or ""
ALLOWED_PORTS: Final[frozenset[int | None]] = frozenset({None, 443})
ALLOWED_PATH_PREFIX: Final = f"{_ALLOWED.path}/"


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

    The code is normalised on the way in, so a bare string or a hostile object
    cannot make a later ``.value`` raise from inside exception handling.
    """

    __slots__ = ("code",)

    def __init__(self, code: SharadarErrorCode) -> None:
        """Carry ``code``. There is no field for a URL, a host or a message."""
        self.code = safe_code(code)
        super().__init__(self.code.value)


class HttpResponseLike(Protocol):
    """What this transport is allowed to touch on a successful response.

    Narrow on purpose. There is no ``headers`` mapping, no ``url``, no ``geturl``
    and no unbounded ``read()`` in the shape -- so a fake in a test and the real
    :class:`http.client.HTTPResponse` are held to the same, deliberately small,
    surface.
    """

    @property
    def status(self) -> int:
        """The HTTP status code."""

    def read(self, amount: int, /) -> bytes:
        """At most ``amount`` bytes of the body."""

    def getheader(self, name: str, default: str | None = None, /) -> str | None:
        """One response header, or ``default``."""

    def close(self) -> None:
        """Release the connection."""


#: How a prepared request is opened. Injectable so the concrete transport's rules
#: can be tested without a socket.
OpenerCall = Callable[[urllib.request.Request, float], HttpResponseLike]


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


class RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect handler that never redirects.

    Returning ``None`` from ``redirect_request`` makes urllib stop and raise
    :class:`~urllib.error.HTTPError` for the 3xx, which is exactly what is wanted:
    the status is observable, the target is never contacted, and ``Location``
    never leaves this object.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        """Refuse every redirect."""
        return None


def build_pinned_opener_director() -> urllib.request.OpenerDirector:
    """An opener that follows no redirect and discovers no proxy.

    **How the proxy suppression actually works**, because it is not obvious from
    reading it. Passing a :class:`~urllib.request.ProxyHandler` *instance* makes
    :func:`~urllib.request.build_opener` drop the default ``ProxyHandler`` class
    from the handlers it would otherwise add -- and the default is the one that
    calls ``getproxies()`` and picks up ``HTTPS_PROXY`` or the Windows system
    settings. The instance passed here holds an empty proxy map, so it registers
    no ``*_open`` method and does no proxying itself. The net effect is an opener
    with no proxy behaviour at all, which is why the test for this compares
    against a default opener built with the same environment rather than merely
    asserting that the handler was passed.

    Built per transport and **never installed globally**: installing it would
    change the behaviour of unrelated code in this process, and inheriting the
    globally installed one would let unrelated code change this.
    """
    return urllib.request.build_opener(RefuseRedirects(), urllib.request.ProxyHandler({}))


def build_pinned_opener() -> OpenerCall:
    """The pinned opener as the call this transport uses."""
    opener = build_pinned_opener_director()

    def call(request: urllib.request.Request, timeout: float) -> HttpResponseLike:
        response: HttpResponseLike = opener.open(request, timeout=timeout)
        return response

    return call


def origin_refusal(url: str) -> SharadarErrorCode | None:
    """The code refusing ``url``, or ``None`` if its origin is exactly the allowed one.

    Parsed, never prefix-matched. A host of the form
    ``<allowed-host>.attacker.example`` and a userinfo prefix of the form
    ``<allowed-host>:key@somewhere-else`` both satisfy a ``startswith`` test, and
    neither is this vendor.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return SharadarErrorCode.REQUEST_ORIGIN_REFUSED
    try:
        port = parts.port
    except ValueError:
        # A malformed port raises rather than returning None.
        return SharadarErrorCode.REQUEST_ORIGIN_REFUSED
    if parts.scheme != ALLOWED_SCHEME:
        return SharadarErrorCode.REQUEST_SCHEME_REFUSED
    if parts.hostname != ALLOWED_HOST:
        return SharadarErrorCode.REQUEST_ORIGIN_REFUSED
    if port not in ALLOWED_PORTS:
        return SharadarErrorCode.REQUEST_ORIGIN_REFUSED
    if parts.username is not None or parts.password is not None:
        return SharadarErrorCode.REQUEST_ORIGIN_REFUSED
    if parts.fragment:
        return SharadarErrorCode.REQUEST_ORIGIN_REFUSED
    if not parts.path.startswith(ALLOWED_PATH_PREFIX):
        return SharadarErrorCode.REQUEST_ORIGIN_REFUSED
    return None


#: An RFC 7230 header field-name token.
_HEADER_NAME: Final = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")

#: A header value: printable US-ASCII only, no leading or trailing space, bounded.
#: CR, LF and NUL are excluded by construction, which is the point.
_HEADER_VALUE: Final = re.compile(r"^[\x21-\x7e]([\x20-\x7e]{0,254}[\x21-\x7e])?$")


def headers_are_safe(headers: Mapping[str, str]) -> bool:
    """Whether every header name and value is an exact, well-formed ASCII token.

    **Checked here rather than left to urllib**, which was the assumption an
    earlier revision made and it was wrong: :class:`urllib.request.Request` stores
    headers without validating them, and a ``\\r\\n`` in a value is only rejected
    much later, at send time, by :mod:`http.client`. Between those two points the
    request looks well formed. Validating at the boundary means a split-request
    attempt never reaches an opener at all.
    """
    for name, value in headers.items():
        if type(name) is not str or type(value) is not str:
            return False
        if not _HEADER_NAME.match(name) or not _HEADER_VALUE.match(value):
            return False
    return True


def _content_length_over(response: HttpResponseLike, limit: int) -> bool:
    """Whether a declared ``Content-Length`` already exceeds ``limit``.

    **A malformed or absent header is ignored, deliberately.** The read ceiling is
    the control; this is an early exit that avoids pulling a body we already know
    is too big. Refusing on an unparseable header would reject a legitimate
    response for a cosmetic vendor bug, and would add nothing, because an
    oversized body is caught by the bounded read either way.
    """
    try:
        declared = response.getheader("Content-Length")
    except Exception:
        return False
    if declared is None:
        return False
    try:
        return int(declared.strip()) > limit
    except (ValueError, TypeError, AttributeError):
        return False


class UrllibTransport:
    """A standard-library HTTPS transport, pinned to one origin.

    Adds no dependency and holds no state between calls beyond its own opener.
    **Nothing in the repository constructs it outside its dedicated synthetic unit
    test**, where the opener is a fake and no socket is opened.
    """

    __slots__ = ("_max_response_bytes", "_opener")

    def __init__(
        self,
        *,
        opener: OpenerCall | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        """Bind the opener and the response ceiling.

        Raises:
            TransportUnavailableError: if ``max_response_bytes`` is not an ``int``
                in ``1..MAX_RESPONSE_BYTES_CEILING``. A ceiling that can be set to
                anything is not a ceiling.
        """
        if type(max_response_bytes) is not int or not (
            0 < max_response_bytes <= MAX_RESPONSE_BYTES_CEILING
        ):
            raise TransportUnavailableError(SharadarErrorCode.REQUEST_MALFORMED)
        self._opener = opener if opener is not None else build_pinned_opener()
        self._max_response_bytes = max_response_bytes

    @property
    def max_response_bytes(self) -> int:
        """The configured ceiling on a successful response body."""
        return self._max_response_bytes

    def get(
        self, *, url: str, headers: Mapping[str, str], timeout_seconds: float
    ) -> TransportResponse:
        """Perform one GET against the pinned origin, disclosing nothing on failure."""
        refusal = origin_refusal(url)
        if refusal is not None:
            raise TransportUnavailableError(refusal)
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise TransportUnavailableError(SharadarErrorCode.REQUEST_MALFORMED)
        if not headers_are_safe(headers):
            raise TransportUnavailableError(SharadarErrorCode.REQUEST_MALFORMED)

        try:
            request = urllib.request.Request(  # noqa: S310 - origin pinned above
                url, headers=dict(headers), method="GET"
            )
        except (ValueError, TypeError, http.client.HTTPException):
            # Header and URL construction raise ValueError carrying the offending
            # value -- a header line, or the URL with the key in it. Converted
            # here rather than allowed to propagate, because the message is the
            # disclosure.
            raise TransportUnavailableError(SharadarErrorCode.REQUEST_MALFORMED) from None

        try:
            response = self._opener(request, float(timeout_seconds))
        except urllib.error.HTTPError as exc:
            # The body of a failing response is NOT read. This exception is the
            # response object, so reading it is one attribute away -- and a vendor
            # error page, or a redirect's Location, is exactly what must never
            # reach a log or a Bronze object. A refused 3xx arrives here too.
            exc.close()
            return TransportResponse(status=int(exc.code), body=b"")
        except TimeoutError:
            raise TransportUnavailableError(SharadarErrorCode.NETWORK_TIMEOUT) from None
        except urllib.error.URLError:
            raise TransportUnavailableError(SharadarErrorCode.NETWORK_UNREACHABLE) from None
        except http.client.HTTPException:
            raise TransportUnavailableError(SharadarErrorCode.RESPONSE_READ_FAILED) from None
        except OSError:
            raise TransportUnavailableError(SharadarErrorCode.RESPONSE_READ_FAILED) from None
        except (ValueError, TypeError):
            # An opener can raise these for a URL or header it dislikes, and the
            # message carries the value it disliked.
            raise TransportUnavailableError(SharadarErrorCode.REQUEST_MALFORMED) from None

        try:
            if _content_length_over(response, self._max_response_bytes):
                raise TransportUnavailableError(SharadarErrorCode.RESPONSE_TOO_LARGE)
            try:
                # One byte past the ceiling: enough to know it was exceeded,
                # never enough to load a body that exceeds it.
                body = response.read(self._max_response_bytes + 1)
                status = int(response.status)
            except TimeoutError:
                raise TransportUnavailableError(SharadarErrorCode.NETWORK_TIMEOUT) from None
            except (OSError, http.client.HTTPException):
                raise TransportUnavailableError(SharadarErrorCode.RESPONSE_READ_FAILED) from None
            except (ValueError, TypeError, AttributeError):
                # Reading response metadata can fail on a malformed response. No
                # value from it reaches the caller.
                raise TransportUnavailableError(SharadarErrorCode.RESPONSE_READ_FAILED) from None
            if type(body) is not bytes or len(body) > self._max_response_bytes:
                raise TransportUnavailableError(
                    SharadarErrorCode.RESPONSE_TOO_LARGE
                    if type(body) is bytes
                    else SharadarErrorCode.RESPONSE_READ_FAILED
                )
            return TransportResponse(status=status, body=body)
        finally:
            # A close() that raises must not replace the outcome, and must not
            # surface a socket message naming the host.
            try:
                response.close()
            except Exception:  # noqa: S110 - a close failure is never the caller's problem
                pass


__all__ = [
    "ALLOWED_HOST",
    "ALLOWED_PATH_PREFIX",
    "ALLOWED_PORTS",
    "ALLOWED_SCHEME",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "MAX_RESPONSE_BYTES_CEILING",
    "MAX_TIMEOUT_SECONDS",
    "HttpResponseLike",
    "OpenerCall",
    "RefuseRedirects",
    "SharadarTransport",
    "TransportResponse",
    "TransportUnavailableError",
    "UrllibTransport",
    "build_pinned_opener",
    "build_pinned_opener_director",
    "headers_are_safe",
    "origin_refusal",
]
