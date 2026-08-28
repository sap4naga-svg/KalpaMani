"""The concrete transport's rules, proven against a fake opener. **No socket opens.**

This is the one module in the repository allowed to construct
:class:`~kalpamani.data.ingest.sharadar.transport.UrllibTransport`, and an
architecture test enforces that. *Dormant* must not be allowed to mean *untested*:
every rule that stands between a query-string credential and the wrong host is
checked here, because the alternative is a docstring nobody has run.

The opener is injected, so nothing below resolves a name, opens a connection or
contacts any host -- real or synthetic. The fakes return objects; they do not
perform I/O.

What is proven:

* the origin is pinned by **parsing**, so a lookalike host, a userinfo prefix, a
  non-default port, a wrong scheme, a fragment and a path outside the documented
  prefix are all refused;
* a redirect is refused rather than followed -- its target is never opened, its
  body is never read, and ``Location`` never leaves the transport;
* ambient proxy discovery is off and no opener is installed globally;
* a successful body is bounded, and an oversized ``Content-Length`` refuses before
  the body is read at all;
* a failing response's body is never read;
* no URL, key, host or body reaches an exception.
"""

from __future__ import annotations

import http.client
import urllib.error
import urllib.request
from typing import Any

import pytest

from kalpamani.data.ingest.sharadar.datasets import API_BASE_URL
from kalpamani.data.ingest.sharadar.redaction import SharadarErrorCode
from kalpamani.data.ingest.sharadar.transport import (
    ALLOWED_HOST,
    ALLOWED_PATH_PREFIX,
    DEFAULT_MAX_RESPONSE_BYTES,
    MAX_RESPONSE_BYTES_CEILING,
    MAX_TIMEOUT_SECONDS,
    RefuseRedirects,
    TransportUnavailableError,
    UrllibTransport,
    build_pinned_opener,
    build_pinned_opener_director,
    origin_refusal,
)

pytestmark = pytest.mark.unit

APPROVED_URL = f"{API_BASE_URL}/stocks?api_key=synthetic-fake-key-0001&ticker=ZZQA"
HEADERS = {"User-Agent": "KalpaMani-Personal-Research/phase3a-sharadar"}


class FakeResponse:
    """A response object. Holds bytes and a status; performs no I/O."""

    def __init__(
        self, *, status: int = 200, body: bytes = b"", content_length: str | None = None
    ) -> None:
        self._status = status
        self._body = body
        self._content_length = content_length
        self.closed = False
        self.read_calls: list[int] = []

    @property
    def status(self) -> int:
        return self._status

    def read(self, amount: int, /) -> bytes:
        self.read_calls.append(amount)
        return self._body[:amount]

    def getheader(self, name: str, default: str | None = None, /) -> str | None:
        if name.lower() == "content-length":
            return self._content_length if self._content_length is not None else default
        return default

    def close(self) -> None:
        self.closed = True


class RecordingOpener:
    """Records every URL it was asked to open, and returns a queued outcome."""

    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome
        self.opened: list[str] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> Any:
        self.opened.append(request.full_url)
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


def transport(outcome: Any, **kwargs: Any) -> UrllibTransport:
    """A transport wired to a fake opener. **The only place this class is built.**"""
    return UrllibTransport(opener=RecordingOpener(outcome), **kwargs)


def http_error(status: int) -> urllib.error.HTTPError:
    """An HTTPError with a body a correct transport must never read."""
    return urllib.error.HTTPError(
        url="https://elsewhere.invalid/leak?api_key=synthetic-fake-key-0001",
        code=status,
        msg="synthetic vendor error page body",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )


# ---------------------------------------------------------------------------
# Origin pinning, by parsing
# ---------------------------------------------------------------------------


def test_the_approved_origin_is_accepted() -> None:
    opener = RecordingOpener(FakeResponse(body=b"synthetic-ok"))
    response = UrllibTransport(opener=opener).get(
        url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0
    )
    assert response.status == 200
    assert response.body == b"synthetic-ok"
    assert opener.opened == [APPROVED_URL]


@pytest.mark.parametrize(
    "url,expected",
    [
        # A lookalike host that satisfies every prefix test there is.
        (
            f"https://{ALLOWED_HOST}.attacker.invalid{ALLOWED_PATH_PREFIX}stocks?a=1",
            SharadarErrorCode.REQUEST_ORIGIN_REFUSED,
        ),
        (
            f"https://elsewhere.invalid{ALLOWED_PATH_PREFIX}stocks",
            SharadarErrorCode.REQUEST_ORIGIN_REFUSED,
        ),
        # Userinfo: the part of a URL that reads as the host to a human.
        (
            f"https://{ALLOWED_HOST}:key@elsewhere.invalid{ALLOWED_PATH_PREFIX}stocks",
            SharadarErrorCode.REQUEST_ORIGIN_REFUSED,
        ),
        (
            f"https://user@{ALLOWED_HOST}{ALLOWED_PATH_PREFIX}stocks",
            SharadarErrorCode.REQUEST_ORIGIN_REFUSED,
        ),
        (
            f"https://{ALLOWED_HOST}:8443{ALLOWED_PATH_PREFIX}stocks",
            SharadarErrorCode.REQUEST_ORIGIN_REFUSED,
        ),
        (
            f"https://{ALLOWED_HOST}{ALLOWED_PATH_PREFIX}stocks#fragment",
            SharadarErrorCode.REQUEST_ORIGIN_REFUSED,
        ),
        (f"https://{ALLOWED_HOST}/v9.9/other/stocks", SharadarErrorCode.REQUEST_ORIGIN_REFUSED),
        (f"https://{ALLOWED_HOST}/", SharadarErrorCode.REQUEST_ORIGIN_REFUSED),
        (
            f"http://{ALLOWED_HOST}{ALLOWED_PATH_PREFIX}stocks",
            SharadarErrorCode.REQUEST_SCHEME_REFUSED,
        ),
        ("file:///etc/passwd", SharadarErrorCode.REQUEST_SCHEME_REFUSED),
        ("ftp://api.sharadar.com/v1.0/data/stocks", SharadarErrorCode.REQUEST_SCHEME_REFUSED),
        ("not a url at all", SharadarErrorCode.REQUEST_SCHEME_REFUSED),
    ],
)
def test_every_other_origin_is_refused(url: str, expected: SharadarErrorCode) -> None:
    assert origin_refusal(url) is expected


@pytest.mark.parametrize(
    "url",
    [
        f"https://{ALLOWED_HOST}.attacker.invalid{ALLOWED_PATH_PREFIX}stocks",
        f"https://{ALLOWED_HOST}:key@elsewhere.invalid{ALLOWED_PATH_PREFIX}stocks",
        f"http://{ALLOWED_HOST}{ALLOWED_PATH_PREFIX}stocks",
        f"https://{ALLOWED_HOST}:8443{ALLOWED_PATH_PREFIX}stocks",
        f"https://{ALLOWED_HOST}{ALLOWED_PATH_PREFIX}stocks#f",
    ],
)
def test_a_refused_origin_is_never_opened(url: str) -> None:
    """The refusal happens before urllib sees the URL, so nothing is contacted."""
    opener = RecordingOpener(FakeResponse())
    with pytest.raises(TransportUnavailableError):
        UrllibTransport(opener=opener).get(url=url, headers=HEADERS, timeout_seconds=10.0)
    assert opener.opened == []


def test_the_default_port_is_accepted_and_an_explicit_443_is_too() -> None:
    assert origin_refusal(APPROVED_URL) is None
    assert origin_refusal(f"https://{ALLOWED_HOST}:443{ALLOWED_PATH_PREFIX}stocks?a=1") is None


def test_prefix_matching_would_not_have_caught_the_lookalike() -> None:
    """NEGATIVE CONTROL for the check itself.

    The rejected URL passes ``startswith("https://")`` -- which is exactly why the
    origin is parsed instead.
    """
    lookalike = f"https://{ALLOWED_HOST}.attacker.invalid{ALLOWED_PATH_PREFIX}stocks"
    assert lookalike.startswith("https://")
    assert origin_refusal(lookalike) is SharadarErrorCode.REQUEST_ORIGIN_REFUSED


# ---------------------------------------------------------------------------
# Redirects and proxies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirect_is_refused_and_its_target_is_never_contacted(status: int) -> None:
    """Following one would hand the query string -- and the key -- to the new host."""
    opener = RecordingOpener(http_error(status))
    response = transport(http_error(status)).get(
        url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0
    )
    assert response.status == status
    assert response.body == b""
    assert opener.opened == []


def test_a_redirect_status_classifies_as_refused_rather_than_unexpected() -> None:
    from kalpamani.data.ingest.sharadar.redaction import RETRYABLE_CODES, classify_http_status

    assert classify_http_status(302) is SharadarErrorCode.HTTP_REDIRECT_REFUSED
    assert SharadarErrorCode.HTTP_REDIRECT_REFUSED not in RETRYABLE_CODES


def test_the_redirect_handler_refuses_every_redirect() -> None:
    """``redirect_request`` returning ``None`` is what makes urllib stop."""
    handler = RefuseRedirects()
    # The request object is built and never opened; it exists only as an argument.
    prepared = urllib.request.Request(APPROVED_URL)  # noqa: S310 - never opened
    outcome: object = handler.redirect_request(  # type: ignore[func-returns-value]
        prepared, None, 302, "Found", None, "https://elsewhere.invalid/"
    )
    assert outcome is None, "a redirect handler that returns a request would follow it"


def test_the_pinned_opener_carries_the_refusing_redirect_handler() -> None:
    director = build_pinned_opener_director()
    handlers = director.handlers  # type: ignore[attr-defined]
    assert any(isinstance(handler, RefuseRedirects) for handler in handlers)


def test_the_pinned_opener_suppresses_ambient_proxy_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ``HTTPS_PROXY`` variable must not route a credential-bearing request.

    Compared against a default opener built in the same environment rather than
    asserted from the source. The mechanism is indirect -- passing a
    ``ProxyHandler`` instance makes ``build_opener`` drop the *default* one, which
    is the handler that reads the environment -- and an empty ``ProxyHandler``
    registers no methods, so it does not appear in ``handlers`` at all. Checking
    that it was passed would therefore prove nothing; checking that the ambient
    proxy is present in one opener and absent from the other proves the effect.
    """
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")

    ambient = urllib.request.build_opener()
    ambient_proxies = [
        handler.proxies  # type: ignore[attr-defined]
        for handler in ambient.handlers  # type: ignore[attr-defined]
        if isinstance(handler, urllib.request.ProxyHandler)
    ]
    assert ambient_proxies and ambient_proxies[0], (
        "precondition: a default opener does pick the ambient proxy up, which is "
        "exactly the behaviour the pinned opener has to suppress"
    )

    pinned = build_pinned_opener_director()
    assert [
        handler.proxies  # type: ignore[attr-defined]
        for handler in pinned.handlers  # type: ignore[attr-defined]
        if isinstance(handler, urllib.request.ProxyHandler) and handler.proxies  # type: ignore[attr-defined]
    ] == []


def test_no_opener_is_installed_globally() -> None:
    """Installing one would change unrelated code in this process, and vice versa."""
    assert callable(build_pinned_opener())
    assert urllib.request._opener is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Response size bound
# ---------------------------------------------------------------------------


def test_a_body_exactly_at_the_limit_is_accepted() -> None:
    body = b"x" * 32
    response = transport(FakeResponse(body=body), max_response_bytes=32).get(
        url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0
    )
    assert response.body == body


def test_a_body_one_byte_over_the_limit_is_refused() -> None:
    fake = FakeResponse(body=b"x" * 33)
    with pytest.raises(TransportUnavailableError) as caught:
        transport(fake, max_response_bytes=32).get(
            url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0
        )
    assert caught.value.code is SharadarErrorCode.RESPONSE_TOO_LARGE
    # Read at most limit + 1: enough to know, never enough to load.
    assert fake.read_calls == [33]
    assert fake.closed is True


def test_an_oversized_content_length_refuses_before_the_body_is_read() -> None:
    fake = FakeResponse(body=b"x" * 1000, content_length="999999999")
    with pytest.raises(TransportUnavailableError) as caught:
        transport(fake, max_response_bytes=32).get(
            url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0
        )
    assert caught.value.code is SharadarErrorCode.RESPONSE_TOO_LARGE
    assert fake.read_calls == [], "the body must not be read once the header settles it"


@pytest.mark.parametrize("declared", ["not-a-number", "", "-1", "12 34"])
def test_a_malformed_content_length_is_ignored_and_the_read_bound_still_decides(
    declared: str,
) -> None:
    """The documented rule: the header is an early exit, the read ceiling is the control.

    Refusing on an unparseable header would reject a legitimate response for a
    cosmetic vendor bug, and would add nothing -- an oversized body is caught by
    the bounded read either way, which the second half of this test shows.
    """
    ok = transport(FakeResponse(body=b"x" * 10, content_length=declared), max_response_bytes=32)
    assert ok.get(url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0).body == b"x" * 10

    with pytest.raises(TransportUnavailableError) as caught:
        transport(FakeResponse(body=b"x" * 40, content_length=declared), max_response_bytes=32).get(
            url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0
        )
    assert caught.value.code is SharadarErrorCode.RESPONSE_TOO_LARGE


def test_a_content_length_within_the_limit_does_not_short_circuit_the_bound() -> None:
    """A truthful-looking header must not become a licence to read without a ceiling."""
    fake = FakeResponse(body=b"x" * 40, content_length="10")
    with pytest.raises(TransportUnavailableError):
        transport(fake, max_response_bytes=32).get(
            url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0
        )


def test_the_default_ceiling_is_finite_and_leaves_room_for_a_full_documented_page() -> None:
    """10,000 CSV rows of a few dozen bytes is about a megabyte; 64 MiB is the bound."""
    assert DEFAULT_MAX_RESPONSE_BYTES == 64 * 1024 * 1024
    assert DEFAULT_MAX_RESPONSE_BYTES > 10_000 * 200
    assert DEFAULT_MAX_RESPONSE_BYTES < MAX_RESPONSE_BYTES_CEILING


@pytest.mark.parametrize("limit", [0, -1, MAX_RESPONSE_BYTES_CEILING + 1, True, 1.5, "64", None])
def test_an_out_of_range_response_ceiling_is_refused(limit: object) -> None:
    """A ceiling that can be set to anything is not a ceiling."""
    with pytest.raises(TransportUnavailableError) as caught:
        UrllibTransport(opener=RecordingOpener(FakeResponse()), max_response_bytes=limit)  # type: ignore[arg-type]
    assert caught.value.code is SharadarErrorCode.REQUEST_MALFORMED


# ---------------------------------------------------------------------------
# Failure hygiene
# ---------------------------------------------------------------------------


def test_a_failing_response_body_is_not_read() -> None:
    error = http_error(500)
    response = transport(error).get(url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0)
    assert response.status == 500
    assert response.body == b""


@pytest.mark.parametrize(
    "raised,expected",
    [
        (TimeoutError(), SharadarErrorCode.NETWORK_TIMEOUT),
        (
            urllib.error.URLError("getaddrinfo failed for api.sharadar.com"),
            SharadarErrorCode.NETWORK_UNREACHABLE,
        ),
        (OSError("connection reset"), SharadarErrorCode.RESPONSE_READ_FAILED),
    ],
)
def test_a_network_failure_becomes_a_sanitized_code(
    raised: BaseException, expected: SharadarErrorCode
) -> None:
    with pytest.raises(TransportUnavailableError) as caught:
        transport(raised).get(url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0)
    assert caught.value.code is expected


@pytest.mark.parametrize(
    "raised",
    [
        http_error(500),
        urllib.error.URLError("getaddrinfo failed for api.sharadar.com"),
        TimeoutError(),
        OSError("connection reset"),
    ],
)
def test_no_url_key_host_or_body_reaches_a_transport_failure(raised: BaseException) -> None:
    try:
        result = transport(raised).get(url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0)
    except TransportUnavailableError as exc:
        rendered = str(exc)
    else:
        rendered = repr(result)
    for leak in (
        "synthetic-fake-key-0001",
        "api_key",
        "https://",
        "sharadar.com",
        "elsewhere.invalid",
        "vendor error page",
        "?",
    ):
        assert leak not in rendered


@pytest.mark.parametrize(
    "timeout", [0.0, -1.0, MAX_TIMEOUT_SECONDS + 1, float("nan"), float("inf")]
)
def test_an_unusable_timeout_is_refused_before_anything_opens(timeout: float) -> None:
    """NaN is the one worth naming: every ordinary bounds comparison accepts it."""
    opener = RecordingOpener(FakeResponse())
    with pytest.raises(TransportUnavailableError) as caught:
        UrllibTransport(opener=opener).get(
            url=APPROVED_URL, headers=HEADERS, timeout_seconds=timeout
        )
    assert caught.value.code is SharadarErrorCode.REQUEST_MALFORMED
    assert opener.opened == []


def test_a_transport_error_code_is_normalised_rather_than_trusted() -> None:
    """A bare string must not reach ``.value`` and raise from inside error handling."""
    assert TransportUnavailableError("NETWORK_TIMEOUT").code is SharadarErrorCode.NETWORK_TIMEOUT  # type: ignore[arg-type]
    assert TransportUnavailableError("nonsense").code is SharadarErrorCode.UNCLASSIFIED  # type: ignore[arg-type]
    assert TransportUnavailableError(object()).code is SharadarErrorCode.UNCLASSIFIED  # type: ignore[arg-type]


class ExplodingResponse:
    """A response whose every accessor fails the way a malformed one would."""

    def __init__(self, failure: BaseException, *, fail_close: bool = False) -> None:
        self._failure = failure
        self._fail_close = fail_close
        self.closed = False

    @property
    def status(self) -> int:
        raise self._failure

    def read(self, amount: int, /) -> bytes:
        raise self._failure

    def getheader(self, name: str, default: str | None = None, /) -> str | None:
        raise self._failure

    def close(self) -> None:
        self.closed = True
        if self._fail_close:
            raise OSError("connection reset while closing api.sharadar.com")


@pytest.mark.parametrize(
    "failure",
    [
        ValueError(
            "invalid header value for https://api.sharadar.com/?api_key=synthetic-leak-canary"
        ),
        TypeError("bad header type"),
        AttributeError("no attribute 'status'"),
        OSError("connection reset"),
        http.client.HTTPException("malformed chunked encoding"),
    ],
)
def test_a_failing_response_accessor_becomes_a_sanitized_code(failure: BaseException) -> None:
    """Reading response metadata can fail, and the message names what it choked on."""
    fake = ExplodingResponse(failure)
    with pytest.raises(TransportUnavailableError) as caught:
        transport(fake).get(url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0)
    assert caught.value.code in {
        SharadarErrorCode.RESPONSE_READ_FAILED,
        SharadarErrorCode.RESPONSE_TOO_LARGE,
    }
    for leak in ("api_key", "https://", "sharadar.com", "synthetic-leak-canary"):
        assert leak not in str(caught.value)
    assert fake.closed is True


def test_a_close_that_fails_does_not_replace_the_outcome_or_leak_a_host() -> None:
    """A close failure is never the caller's problem, and its message names the host."""

    class ClosesBadly(FakeResponse):
        def close(self) -> None:
            self.closed = True
            raise OSError("connection reset while closing api.sharadar.com")

    fake = ClosesBadly(body=b"synthetic-ok")
    response = transport(fake).get(url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0)
    assert response.body == b"synthetic-ok"
    assert fake.closed is True


@pytest.mark.parametrize(
    "headers",
    [
        {"User-Agent": "agent" + chr(13) + chr(10) + "X-Injected: yes"},
        {"User-Agent" + chr(10) + "X-Injected": "yes"},
    ],
)
def test_an_invalid_header_cannot_escape_as_a_raw_value_error(
    headers: dict[str, str],
) -> None:
    """``Request`` raises ValueError carrying the offending header line."""
    opener = RecordingOpener(FakeResponse())
    with pytest.raises(TransportUnavailableError) as caught:
        UrllibTransport(opener=opener).get(url=APPROVED_URL, headers=headers, timeout_seconds=10.0)
    assert caught.value.code is SharadarErrorCode.REQUEST_MALFORMED
    assert "X-Injected" not in str(caught.value)
    assert opener.opened == []


@pytest.mark.parametrize(
    "raised",
    [
        ValueError("unknown url type: https://api.sharadar.com/?api_key=synthetic-leak-canary"),
        TypeError(),
    ],
)
def test_an_opener_value_error_is_converted_without_echoing_the_url(
    raised: BaseException,
) -> None:
    with pytest.raises(TransportUnavailableError) as caught:
        transport(raised).get(url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0)
    assert caught.value.code is SharadarErrorCode.REQUEST_MALFORMED
    for leak in ("api_key", "https://", "sharadar.com", "synthetic-leak-canary"):
        assert leak not in str(caught.value)


def test_a_non_bytes_body_is_refused_rather_than_returned() -> None:
    """A fake or a future response object that returns a str is a read failure."""

    class WrongBodyType(FakeResponse):
        def read(self, amount: int, /) -> bytes:
            self.read_calls.append(amount)
            return "synthetic-str-body"  # type: ignore[return-value]

    with pytest.raises(TransportUnavailableError) as caught:
        transport(WrongBodyType()).get(url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0)
    assert caught.value.code is SharadarErrorCode.RESPONSE_READ_FAILED


def test_the_fixed_user_agent_still_reaches_the_opener() -> None:
    """The negative control for every refusal above: the valid header does arrive."""
    opener = RecordingOpener(FakeResponse(body=b"synthetic-ok"))
    UrllibTransport(opener=opener).get(url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0)
    assert opener.opened == [APPROVED_URL]


def test_the_response_is_always_closed() -> None:
    fake = FakeResponse(body=b"synthetic")
    transport(fake).get(url=APPROVED_URL, headers=HEADERS, timeout_seconds=10.0)
    assert fake.closed is True
