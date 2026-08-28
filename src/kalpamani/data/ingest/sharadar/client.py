"""The Sharadar client: paced, bounded, silent, and byte-faithful.

It does one thing -- turn a :class:`~kalpamani.data.ingest.sharadar.datasets.SharadarRequest`
into the exact bytes the vendor returned -- and it does not parse, interpret,
normalise or store them. That separation is what lets a malformed future payload
still be preserved as Bronze evidence instead of being lost to a parse error at
the boundary.

**Pacing is conservative because no public rate limit exists.** The vendor
publishes no request budget (`PSR-SHD-109`), and *no documented limit is not an
absent limit*. The default is one request per second, and both the clock and the
sleep are injected, so a test proves the pacing without spending the time.

**Retries are bounded, deterministic and narrow.** A fixed backoff schedule with
no jitter -- jitter would need randomness, and a non-reproducible retry sequence is
one more thing a failed run cannot be re-derived from.
:data:`~kalpamani.data.ingest.sharadar.redaction.RETRYABLE_CODES` decides what may
be attempted again, and **an authorization refusal is not in it**: a rejected key
is rejected every time, so retrying turns one refused request into several, which
is how a key mix-up becomes a rate-limit incident.

**Nothing about the request is emitted.** The URL is a local variable, built and
handed to the transport in the same expression. It is never logged, never stored,
never attached to an exception and never returned. The client's ``repr`` names its
configuration and not its credential.

**Nothing injected is trusted at runtime.** The credential must be an exact
:class:`~kalpamani.data.ingest.sharadar.credentials.SharadarCredential`, the
request an exact
:class:`~kalpamani.data.ingest.sharadar.datasets.SharadarRequest`, and whatever
the transport returns an exact
:class:`~kalpamani.data.ingest.sharadar.transport.TransportResponse` -- which in
turn guarantees an exact ``int`` status and exact ``bytes`` body. A ``Protocol``
annotation is a static claim, not a runtime one, and a transport that returned
``None``, a duck-typed object or a ``bytearray`` body would otherwise have handed
that straight back to the caller as a payload.

**It cannot reach a network by itself.** The transport has no default; a client
constructed without one is a ``TypeError``. **No runner exists in this slice, and
none is authorized.**
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from kalpamani.data.ingest.sharadar.credentials import SharadarCredential
from kalpamani.data.ingest.sharadar.datasets import SharadarRequest, build_request_url
from kalpamani.data.ingest.sharadar.redaction import (
    RETRYABLE_CODES,
    SharadarErrorCode,
    SharadarRequestError,
    SharadarStage,
    classify_http_status,
)
from kalpamani.data.ingest.sharadar.transport import (
    MAX_RESPONSE_BYTES_CEILING,
    MAX_TIMEOUT_SECONDS,
    SharadarTransport,
    TransportResponse,
    TransportUnavailableError,
)

#: Identifies this system honestly to the vendor. Deterministic: it names the
#: project and the phase, and carries no host name, user or run identifier.
DEFAULT_USER_AGENT: Final = "KalpaMani-Personal-Research/phase3a-sharadar"

#: Courtesy pacing, not compliance with a stated budget -- there is no stated budget.
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS: Final = 1.0

#: Bounded by construction. A request with no ceiling can hold a run open forever.
DEFAULT_TIMEOUT_SECONDS: Final = 60.0

#: The largest number of attempts any policy may authorise. A bound on the bound.
MAX_ATTEMPTS_CEILING: Final = 5


def _finite(value: object) -> bool:
    """Whether ``value`` is a real, finite number this boundary may act on.

    ``bool`` is excluded even though it is an ``int``: ``True`` seconds is a
    caller mistake, not a one-second interval. NaN and infinity are excluded
    because every ordinary bounds check silently *accepts* NaN -- ``nan < 0``,
    ``nan > 0`` and ``nan <= 0`` are all ``False`` -- so a comparison-based guard
    lets it through and then disables the behaviour it was guarding.
    """
    if type(value) is int:
        return True
    if type(value) is float:
        return math.isfinite(value)
    return False


class Pacer:
    """At most one request per ``min_interval`` seconds, on an injected clock.

    Clock and sleep are parameters so pacing is provable in a test that runs
    instantly. A pacer holding a real ``time.sleep`` would make every retry test a
    multi-second one, and slow tests are the ones that get deleted.
    """

    __slots__ = ("_clock", "_last", "_sleep", "min_interval")

    def __init__(
        self,
        min_interval: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        """Bind the interval and the injected clock and sleep.

        Raises:
            SharadarRequestError: if ``min_interval`` is not a finite,
                non-negative number. NaN is the case worth naming: ``nan < 0`` is
                ``False``, so a bare comparison *accepts* it, and every later
                arithmetic comparison in :meth:`wait` is also ``False`` -- which
                silently disables pacing rather than failing.
        """
        if not _finite(min_interval) or min_interval < 0:
            raise SharadarRequestError(
                stage=SharadarStage.BUILD, code=SharadarErrorCode.REQUEST_MALFORMED
            )
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleeper
        self._last: float | None = None

    def wait(self) -> float:
        """Block until the next request is due. Returns the seconds actually slept."""
        now = self._clock()
        slept = 0.0
        if self._last is not None:
            due = self._last + self.min_interval
            if now < due:
                slept = due - now
                self._sleep(slept)
                now = due
        self._last = now
        return slept

    def pause(self, seconds: float) -> None:
        """Sleep for a retry backoff. **Deliberately does not touch ``_last``.**

        ``_last`` records when the last *request* was made, not when the pacer last
        did something, so the next :meth:`wait` sees that the backoff has already
        run the clock past the interval and does not sleep again. Advancing
        ``_last`` here would push the next request out by ``backoff + interval``
        instead of ``max(backoff, interval)`` -- spending part of the delay twice,
        and doing it invisibly, since both numbers look plausible in a log.
        """
        if seconds > 0:
            self._sleep(seconds)


@dataclass(frozen=True, slots=True, kw_only=True)
class RetryPolicy:
    """A bounded, deterministic retry schedule.

    ``backoff_seconds`` holds exactly one delay per retry, so the total wait a
    policy can impose is a number a reviewer can read off rather than derive. No
    jitter and no multiplier: a run that failed must be describable by the same
    schedule that produced it.
    """

    max_attempts: int
    backoff_seconds: tuple[float, ...]

    def __post_init__(self) -> None:
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= MAX_ATTEMPTS_CEILING:
            raise SharadarRequestError(
                stage=SharadarStage.BUILD, code=SharadarErrorCode.REQUEST_MALFORMED
            )
        if type(self.backoff_seconds) is not tuple:
            raise SharadarRequestError(
                stage=SharadarStage.BUILD, code=SharadarErrorCode.REQUEST_MALFORMED
            )
        if len(self.backoff_seconds) != self.max_attempts - 1:
            raise SharadarRequestError(
                stage=SharadarStage.BUILD, code=SharadarErrorCode.REQUEST_MALFORMED
            )
        # `not (delay > 0)` rather than `delay <= 0`: NaN fails both comparisons,
        # so the negated form is what actually refuses it. An infinite backoff is
        # refused for the plainer reason that it never returns.
        if any(not _finite(delay) or not delay > 0 for delay in self.backoff_seconds):
            raise SharadarRequestError(
                stage=SharadarStage.BUILD, code=SharadarErrorCode.REQUEST_MALFORMED
            )


#: Three attempts, two waits. Small enough that a persistent outage fails quickly.
DEFAULT_RETRY_POLICY: Final = RetryPolicy(max_attempts=3, backoff_seconds=(2.0, 8.0))


class SharadarClient:
    """Fetches exact response bytes for one request. Stores nothing, parses nothing."""

    __slots__ = ("_credential", "_pacer", "_retry_policy", "_timeout", "_transport")

    def __init__(
        self,
        *,
        credential: SharadarCredential,
        transport: SharadarTransport,
        pacer: Pacer | None = None,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Bind the credential, the transport and the pacing and retry policy.

        ``transport`` has **no default**, deliberately: a client that could reach a
        network without one being handed in is a client a forgetful test can point
        at the vendor.

        **There is no ``user_agent`` parameter.** An earlier revision took one and
        put it straight into a request header and into ``repr``. A header value is
        not free text: a caller-supplied ``\\r\\n`` splits the request, a
        key-shaped string turns the User-Agent into a second credential channel,
        and a ``repr`` that echoes it turns any log line into a disclosure. None of
        that buys anything here, because there is exactly one honest thing for this
        client to call itself. Configurability, if it is ever wanted, is a grammar
        and a length ceiling -- and a separate decision.
        """
        if not _finite(timeout_seconds) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise SharadarRequestError(
                stage=SharadarStage.BUILD, code=SharadarErrorCode.REQUEST_MALFORMED
            )
        if type(retry_policy) is not RetryPolicy:
            raise SharadarRequestError(
                stage=SharadarStage.BUILD, code=SharadarErrorCode.REQUEST_MALFORMED
            )
        # An exact credential, not a credential-shaped object. Subclassing is
        # refused at class creation; this is the boundary half of the same rule,
        # so a stand-in cannot override a rendering method or `reveal()` and put a
        # real key into a log line or a request.
        if type(credential) is not SharadarCredential:
            raise SharadarRequestError(
                stage=SharadarStage.BUILD, code=SharadarErrorCode.REQUEST_MALFORMED
            )
        self._credential = credential
        self._transport = transport
        self._pacer = pacer if pacer is not None else Pacer()
        self._retry_policy = retry_policy
        self._timeout = timeout_seconds

    def __repr__(self) -> str:
        """Configuration only, and every value in it is a constant or a number.

        Nothing a caller supplied can appear here, which is what makes the repr
        safe to log without anyone having to think about it.
        """
        return (
            f"SharadarClient(timeout_seconds={self._timeout}, "
            f"max_attempts={self._retry_policy.max_attempts})"
        )

    @property
    def max_attempts(self) -> int:
        """How many attempts this client will make for one request, at most.

        Read-only, and read by the qualification plan so a run's retry budget is a
        bound on what will actually happen rather than a number written down
        beside it. Without it, a budget could only be *declared*: the plan would
        have to trust that whoever built the client respected it, which is exactly
        the kind of bound that is correct in the review and wrong in production.

        The value already appears in :meth:`__repr__`, so this exposes nothing new
        -- it makes an existing, non-sensitive configuration number reachable
        without reading a private attribute.
        """
        return self._retry_policy.max_attempts

    @property
    def max_response_bytes(self) -> int:
        """The largest body one request can return, read from the bound transport.

        **Derived, not duplicated.** The number belongs to the transport, which is
        the thing that actually stops reading; restating it here as a constant
        would create two ceilings that a later edit could move apart.

        Falls back to
        :data:`~kalpamani.data.ingest.sharadar.transport.MAX_RESPONSE_BYTES_CEILING`
        when an injected transport does not declare one, or declares something
        outside the permitted range. That is the **conservative** direction: a
        transport that will not say how much it may return is assumed to be able
        to return the most any transport may, so a caller budgeting against this
        number cannot under-count.
        """
        declared = getattr(self._transport, "max_response_bytes", None)
        if type(declared) is int and 0 < declared <= MAX_RESPONSE_BYTES_CEILING:
            return declared
        return MAX_RESPONSE_BYTES_CEILING

    def headers(self) -> Mapping[str, str]:
        """The fixed request headers. Constant, and carrying no credential.

        Both values are module constants -- **nothing caller-supplied reaches a
        header**, so header injection has no source. The key travels in the query
        string for this vendor (`PSR-SHD-109`), so there is no authorization
        header here, and nothing that varies per run, per host or per machine.
        """
        return {"User-Agent": DEFAULT_USER_AGENT, "Accept-Encoding": "identity"}

    def fetch(self, request: SharadarRequest) -> bytes:
        """Return the vendor's response bytes for ``request``, exactly as received.

        Paced before every attempt, retried only on a retryable condition, and
        bounded by the policy. An empty body is returned as an empty payload
        rather than refused: emptiness is a fact about the range, and Bronze
        preserves what arrived rather than judging it.

        Raises:
            SharadarRequestError: naming the stage, a sanitized code and the
                dataset. Never a URL, never a query string, never a body.
        """
        if type(request) is not SharadarRequest:
            raise SharadarRequestError(
                stage=SharadarStage.FETCH, code=SharadarErrorCode.REQUEST_MALFORMED
            )
        url = build_request_url(request, credential=self._credential)
        code = SharadarErrorCode.REQUEST_MALFORMED
        for attempt in range(self._retry_policy.max_attempts):
            self._pacer.wait()
            try:
                response = self._transport.get(
                    url=url, headers=self.headers(), timeout_seconds=self._timeout
                )
            except TransportUnavailableError as exc:
                code = exc.code
            except Exception:
                # A transport is injected code. It may be a fake, a future
                # implementation, or something that got the Protocol wrong -- and
                # whatever it raises may carry the URL, and therefore the key.
                # A Protocol annotation is not a runtime guarantee.
                code = SharadarErrorCode.RESPONSE_READ_FAILED
            else:
                if type(response) is not TransportResponse:
                    # None, a duck-typed object, or a subclass that skipped the
                    # field validation. `TransportResponse.__post_init__` already
                    # guarantees an exact int status and exact bytes body for a
                    # genuine instance, so this one check covers every malformed
                    # shape without repeating those.
                    code = SharadarErrorCode.RESPONSE_READ_FAILED
                elif response.status == 200:
                    return response.body
                else:
                    code = classify_http_status(response.status)
            if code not in RETRYABLE_CODES:
                break
            if attempt == self._retry_policy.max_attempts - 1:
                break
            self._pacer.pause(self._retry_policy.backoff_seconds[attempt])
        raise SharadarRequestError(
            stage=SharadarStage.FETCH, code=code, dataset=request.dataset.value
        )


__all__ = [
    "DEFAULT_MIN_REQUEST_INTERVAL_SECONDS",
    "DEFAULT_RETRY_POLICY",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_USER_AGENT",
    "MAX_ATTEMPTS_CEILING",
    "Pacer",
    "RetryPolicy",
    "SharadarClient",
]
