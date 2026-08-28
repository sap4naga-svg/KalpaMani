"""The Sharadar client boundary: what it builds, what it retries, what it discloses.

Four properties, each of which fails silently if nobody checks it:

**Request construction is deterministic and explicit.** HTTPS, a stated format, a
stated page, a stated window on a windowed dataset and none on the snapshot, and
no constructible table-wide bulk download. The vendor's one-year default
(`PSR-SHD-121`) is the concrete hazard: a request that omits its window still
succeeds and means something narrower than the code around it claims.

**Nothing about the request escapes.** The key travels in the query string for
this vendor (`PSR-SHD-109`), so a URL *is* a credential. No error message, no
repr and no rendering of a credential may carry one.

**Pacing is real and testable.** An injected clock proves the interval without
spending it.

**Retries are bounded and narrow.** A retryable condition is attempted again a
fixed number of times; an authorization refusal is not retried at all, because a
rejected key is rejected every time and retrying turns one refused request into
several.

Every transport here is synthetic. **No test opens a socket or names a host.**
"""

from __future__ import annotations

import inspect
import re
from datetime import date

import pytest

from fixtures import sharadar_provider as syn
from kalpamani.data.ingest.sharadar.client import (
    DEFAULT_RETRY_POLICY,
    DEFAULT_USER_AGENT,
    MAX_ATTEMPTS_CEILING,
    Pacer,
    RetryPolicy,
    SharadarClient,
)
from kalpamani.data.ingest.sharadar.credentials import (
    CREDENTIAL_PLACEHOLDER,
    SharadarCredential,
    credential_from_env,
)
from kalpamani.data.ingest.sharadar.datasets import (
    API_BASE_URL,
    FORBIDDEN_QUERY_PARAMETERS,
    QUERY_PARAMETER_ALLOWLIST,
    DateWindow,
    Page,
    ResponseFormat,
    SharadarDataset,
    SharadarRequest,
    build_query_parameters,
    build_request_url,
    describe_request,
)
from kalpamani.data.ingest.sharadar.redaction import (
    RETRYABLE_CODES,
    SharadarErrorCode,
    SharadarRequestError,
    SharadarStage,
    classify_http_status,
    redact,
)
from kalpamani.data.ingest.sharadar.transport import (
    MAX_TIMEOUT_SECONDS,
    TransportUnavailableError,
)

pytestmark = pytest.mark.unit


def client(
    transport: syn.ScriptedTransport,
    clock: syn.ManualClock,
    *,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
) -> SharadarClient:
    """A client wired to a synthetic transport and a clock that never really sleeps."""
    return SharadarClient(
        credential=syn.credential(),
        transport=transport,
        pacer=Pacer(min_interval=1.0, clock=clock.time, sleeper=clock.sleep),
        retry_policy=retry_policy,
    )


# ---------------------------------------------------------------------------
# A -- request construction
# ---------------------------------------------------------------------------


def test_a_request_url_is_https_and_names_the_expected_dataset() -> None:
    url = build_request_url(syn.stocks_request(), credential=syn.credential())
    assert url.startswith("https://")
    assert url.startswith(f"{API_BASE_URL}/stocks?")


def test_every_parameter_name_is_on_the_allowlist_and_none_is_forbidden() -> None:
    built = build_query_parameters(syn.stocks_request(), credential=syn.credential())
    names = {name for name, _ in built}
    assert names <= QUERY_PARAMETER_ALLOWLIST
    assert not names & FORBIDDEN_QUERY_PARAMETERS


def test_a_windowed_request_carries_the_explicit_date_range() -> None:
    """The vendor defaults an omitted window to one year (`PSR-SHD-121`)."""
    parameters = dict(build_query_parameters(syn.stocks_request(), credential=syn.credential()))
    assert parameters["from"] == "2021-08-28"
    assert parameters["to"] == "2026-08-27"


def test_a_windowed_dataset_without_a_window_is_refused() -> None:
    with pytest.raises(SharadarRequestError) as caught:
        SharadarRequest(
            dataset=SharadarDataset.STOCKS,
            ticker=syn.SYNTHETIC_TICKER,
            response_format=ResponseFormat.CSV,
            page=syn.page(),
            window=None,
        )
    assert caught.value.code is SharadarErrorCode.REQUEST_MALFORMED
    assert caught.value.stage is SharadarStage.BUILD


def test_the_snapshot_dataset_refuses_a_window() -> None:
    """The vendor states the tickers table is a snapshot (`PSR-SHD-119`)."""
    with pytest.raises(SharadarRequestError):
        SharadarRequest(
            dataset=SharadarDataset.TICKERS,
            ticker=syn.SYNTHETIC_TICKER,
            response_format=ResponseFormat.CSV,
            page=syn.page(),
            window=syn.window(),
        )
    snapshot = build_query_parameters(syn.tickers_request(), credential=syn.credential())
    assert {name for name, _ in snapshot} == {"api_key", "format", "ticker", "limit", "skip"}


def test_pagination_is_explicit_and_walks_deterministically() -> None:
    first = syn.page(limit=500, skip=0)
    assert first.advanced() == Page(limit=500, skip=500)
    assert first.advanced().advanced() == Page(limit=500, skip=1000)


def test_the_format_is_stated_rather_than_assumed() -> None:
    as_json = syn.stocks_request(response_format=ResponseFormat.JSON)
    parameters = dict(build_query_parameters(as_json, credential=syn.credential()))
    assert parameters["format"] == "json"


def test_no_bulk_download_parameter_is_constructible() -> None:
    """``years=`` fetches every security (`PSR-SHD-119`); it must have no route here."""
    assert "years" in FORBIDDEN_QUERY_PARAMETERS
    for request in (syn.stocks_request(), syn.actions_request(), syn.tickers_request()):
        url = build_request_url(request, credential=syn.credential())
        assert "years=" not in url
        assert "lastupdated" not in url


def test_a_request_always_names_exactly_one_security() -> None:
    """No shape here enumerates the market."""
    for request in (syn.stocks_request(), syn.actions_request(), syn.tickers_request()):
        parameters = dict(build_query_parameters(request, credential=syn.credential()))
        assert parameters["ticker"] == syn.SYNTHETIC_TICKER


@pytest.mark.parametrize("ticker", ["", "lower", "TOO-LONG-A-SYMBOL-INDEED", "A B", "1ABC"])
def test_a_malformed_symbol_is_refused(ticker: str) -> None:
    with pytest.raises(SharadarRequestError):
        syn.stocks_request(ticker=ticker)


def test_an_inverted_window_is_refused() -> None:
    with pytest.raises(SharadarRequestError):
        DateWindow(start=date(2026, 1, 2), end=date(2026, 1, 1))


@pytest.mark.parametrize("limit,skip", [(0, 0), (10001, 0), (500, -1)])
def test_an_out_of_range_page_is_refused(limit: int, skip: int) -> None:
    with pytest.raises(SharadarRequestError):
        Page(limit=limit, skip=skip)


def test_request_construction_is_byte_identical_across_calls() -> None:
    """Two builds of one request must not differ, or nothing downstream is reproducible."""
    first = build_request_url(syn.stocks_request(), credential=syn.credential())
    second = build_request_url(syn.stocks_request(), credential=syn.credential())
    assert first == second


def test_the_timeout_is_bounded_and_sent_on_every_call() -> None:
    transport = syn.ScriptedTransport([syn.ok()])
    clock = syn.ManualClock()
    fetcher = SharadarClient(
        credential=syn.credential(),
        transport=transport,
        pacer=Pacer(min_interval=0.0, clock=clock.time, sleeper=clock.sleep),
        timeout_seconds=12.5,
    )
    fetcher.fetch(syn.stocks_request())
    assert transport.timeouts == [12.5]
    with pytest.raises(SharadarRequestError):
        SharadarClient(
            credential=syn.credential(),
            transport=transport,
            timeout_seconds=MAX_TIMEOUT_SECONDS + 1,
        )


def test_the_user_agent_is_deterministic_and_carries_no_machine_detail() -> None:
    transport = syn.ScriptedTransport([syn.ok()])
    clock = syn.ManualClock()
    client(transport, clock).fetch(syn.stocks_request())
    assert transport.headers[0]["User-Agent"] == DEFAULT_USER_AGENT
    assert "KalpaMani" in DEFAULT_USER_AGENT
    assert "Authorization" not in transport.headers[0]


# ---------------------------------------------------------------------------
# B -- redaction and credential hygiene
# ---------------------------------------------------------------------------


def test_a_credential_renders_as_a_placeholder_through_every_route() -> None:
    secret = syn.credential()
    assert repr(secret) == CREDENTIAL_PLACEHOLDER
    assert str(secret) == CREDENTIAL_PLACEHOLDER
    assert f"{secret}" == CREDENTIAL_PLACEHOLDER
    assert f"{secret!r}" == CREDENTIAL_PLACEHOLDER
    assert format(secret, ">40") == CREDENTIAL_PLACEHOLDER
    # Percent-formatting deliberately, and left as percent-formatting: it is the
    # route `logging` takes when a credential is passed as a lazy log argument,
    # which is the most likely way one would ever be rendered by accident.
    assert "%s" % (secret,) == CREDENTIAL_PLACEHOLDER  # noqa: UP031
    assert syn.SYNTHETIC_CREDENTIAL_VALUE not in repr(secret)
    assert secret.reveal() == syn.SYNTHETIC_CREDENTIAL_VALUE


def test_a_credential_is_not_a_dataclass_with_a_generated_repr() -> None:
    """A generated ``__repr__`` would print the field, and nobody would notice."""
    assert not hasattr(SharadarCredential, "__dataclass_fields__")
    assert SharadarCredential.__slots__ == ("_secret",)


@pytest.mark.parametrize("value", ["", "   ", "has space"])
def test_an_unusable_credential_is_refused_at_construction(value: str) -> None:
    with pytest.raises(SharadarRequestError):
        SharadarCredential(value)


def test_a_credential_is_read_from_an_explicitly_supplied_mapping_only() -> None:
    """The mapping is a parameter, so this module has no route to the real environment."""
    built = credential_from_env({"KALPAMANI_SHARADAR_API_KEY": syn.SYNTHETIC_CREDENTIAL_VALUE})
    assert built.reveal() == syn.SYNTHETIC_CREDENTIAL_VALUE
    with pytest.raises(SharadarRequestError):
        credential_from_env({})


@pytest.mark.parametrize(
    "secret", [syn.SYNTHETIC_CREDENTIAL_VALUE, syn.OTHER_SYNTHETIC_CREDENTIAL_VALUE]
)
def test_redaction_removes_any_key_not_merely_one_known_literal(secret: str) -> None:
    url = build_request_url(syn.stocks_request(), credential=SharadarCredential(secret))
    cleaned = redact(url)
    assert secret not in cleaned
    assert "api_key" not in cleaned
    assert "https://" not in cleaned


def test_redaction_strips_a_bare_query_string_and_a_bare_key_assignment() -> None:
    assert "?" in redact("path?ticker=ZZQA&limit=1")
    assert "ZZQA" not in redact("path?ticker=ZZQA&limit=1")
    assert redact("api_key=synthetic-fake-value-0003") == "<key-redacted>"
    assert redact("API-Key = synthetic-fake-value-0003") == "<key-redacted>"


def test_an_error_carries_no_url_no_query_and_no_credential() -> None:
    transport = syn.ScriptedTransport([syn.failing(401)])
    clock = syn.ManualClock()
    with pytest.raises(SharadarRequestError) as caught:
        client(transport, clock).fetch(syn.stocks_request())
    message = str(caught.value)
    assert syn.SYNTHETIC_CREDENTIAL_VALUE not in message
    assert "api_key" not in message
    assert "https://" not in message
    assert "?" not in message
    assert message == "sharadar fetch [stocks]: HTTP_AUTHORIZATION_REFUSED"


def test_a_response_body_has_no_parameter_to_reach_an_error_through() -> None:
    """The primary control is construction: there is no field for a body."""
    error = SharadarRequestError(
        stage=SharadarStage.FETCH, code=SharadarErrorCode.HTTP_SERVER_ERROR, dataset="stocks"
    )
    assert set(SharadarRequestError.__slots__) == {"code", "dataset", "retryable", "stage"}
    assert str(error) == "sharadar fetch [stocks]: HTTP_SERVER_ERROR"


def test_a_body_handed_in_where_a_dataset_name_belongs_becomes_unnamed() -> None:
    error = SharadarRequestError(
        stage=SharadarStage.FETCH,
        code=SharadarErrorCode.HTTP_CLIENT_ERROR,
        dataset="ticker,date,close\nZZQA,2026-01-02,10.5",
    )
    assert error.dataset == "<unnamed>"
    assert "ZZQA" not in str(error)


def test_the_client_repr_names_configuration_and_not_the_credential() -> None:
    transport = syn.ScriptedTransport([])
    rendered = repr(client(transport, syn.ManualClock()))
    assert syn.SYNTHETIC_CREDENTIAL_VALUE not in rendered
    assert "credential" not in rendered
    assert "max_attempts=3" in rendered


def test_the_client_takes_no_user_agent_and_can_carry_no_caller_text() -> None:
    """A header value is not free text.

    An earlier revision accepted a ``user_agent`` and put it straight into a
    request header and into ``repr``. A caller-supplied CR/LF splits the request,
    a key-shaped string turns the User-Agent into a second credential channel, and
    a repr that echoes it turns a log line into a disclosure. There is exactly one
    honest thing for this client to call itself, so there is no parameter.
    """
    parameters = set(inspect.signature(SharadarClient.__init__).parameters)
    assert "user_agent" not in parameters

    transport = syn.ScriptedTransport([syn.ok()])
    fetcher = client(transport, syn.ManualClock())
    fetcher.fetch(syn.stocks_request())
    assert transport.headers[0] == {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept-Encoding": "identity",
    }
    # Every value in the repr is a constant or a number, so nothing a caller
    # supplied can reach it.
    assert set(re.findall(r"[A-Za-z_]+=", repr(fetcher))) == {
        "timeout_seconds=",
        "max_attempts=",
    }


#: Header values a caller must never be able to supply. The first two carry real
#: CR/LF, built with ``chr`` so the hazard is visible in the source rather than
#: hidden inside an escape sequence.
HOSTILE_USER_AGENTS = (
    "agent" + chr(13) + chr(10) + "X-Injected: yes",
    "agent" + chr(10) + "X-Injected: yes",
    "api_key=synthetic-fake-secret",
    "https://elsewhere.invalid/?api_key=synthetic-fake-secret",
)


@pytest.mark.parametrize("hostile", HOSTILE_USER_AGENTS)
def test_no_caller_supplied_user_agent_can_reach_a_header(hostile: str) -> None:
    """The refusal is structural: the constructor has nowhere to put one."""
    with pytest.raises(TypeError):
        SharadarClient(
            credential=syn.credential(),
            transport=syn.ScriptedTransport([]),
            user_agent=hostile,  # type: ignore[call-arg]
        )


def test_the_credential_bearing_helpers_are_not_on_the_package_surface() -> None:
    """Only the client needs to build a URL that contains the key."""
    import kalpamani.data.ingest.sharadar as package

    assert "build_request_url" not in package.__all__
    assert "build_query_parameters" not in package.__all__


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, SharadarErrorCode.HTTP_AUTHORIZATION_REFUSED),
        (403, SharadarErrorCode.HTTP_AUTHORIZATION_REFUSED),
        (404, SharadarErrorCode.HTTP_ENDPOINT_NOT_FOUND),
        (429, SharadarErrorCode.HTTP_RATE_LIMITED),
        (400, SharadarErrorCode.HTTP_CLIENT_ERROR),
        (500, SharadarErrorCode.HTTP_SERVER_ERROR),
        (503, SharadarErrorCode.HTTP_SERVER_ERROR),
        (301, SharadarErrorCode.HTTP_REDIRECT_REFUSED),
        (302, SharadarErrorCode.HTTP_REDIRECT_REFUSED),
        (307, SharadarErrorCode.HTTP_REDIRECT_REFUSED),
        (200, SharadarErrorCode.HTTP_UNEXPECTED_STATUS),
        (600, SharadarErrorCode.HTTP_UNEXPECTED_STATUS),
    ],
)
def test_a_status_becomes_a_category_never_a_body(status: int, expected: SharadarErrorCode) -> None:
    assert classify_http_status(status) is expected


def test_a_disclosure_free_request_description_survives_redaction_unchanged() -> None:
    description = describe_request(syn.stocks_request())
    assert redact(description) == description
    assert "api_key" not in description
    assert "://" not in description
    assert "?" not in description


# ---------------------------------------------------------------------------
# D -- pacing
# ---------------------------------------------------------------------------


def test_the_first_request_is_immediate_and_the_next_one_waits() -> None:
    clock = syn.ManualClock()
    pacer = Pacer(min_interval=1.0, clock=clock.time, sleeper=clock.sleep)
    assert pacer.wait() == 0.0
    assert pacer.wait() == 1.0
    assert clock.sleeps == [1.0]


def test_pacing_does_not_sleep_when_enough_time_has_already_passed() -> None:
    clock = syn.ManualClock()
    pacer = Pacer(min_interval=1.0, clock=clock.time, sleeper=clock.sleep)
    pacer.wait()
    clock.now = 5.0
    assert pacer.wait() == 0.0
    assert clock.sleeps == []


def test_the_client_paces_every_attempt() -> None:
    transport = syn.ScriptedTransport([syn.ok(), syn.ok()])
    clock = syn.ManualClock()
    fetcher = client(transport, clock)
    fetcher.fetch(syn.stocks_request())
    fetcher.fetch(syn.actions_request())
    assert clock.sleeps == [1.0]
    assert transport.call_count == 2


def test_a_backoff_subsumes_the_pacing_interval_rather_than_adding_to_it() -> None:
    """Otherwise part of the delay is spent twice, and both numbers look plausible."""
    clock = syn.ManualClock()
    pacer = Pacer(min_interval=1.0, clock=clock.time, sleeper=clock.sleep)
    pacer.wait()
    pacer.pause(4.0)
    assert pacer.wait() == 0.0
    assert clock.sleeps == [4.0]


def test_a_backoff_shorter_than_the_interval_still_leaves_the_pacing_to_run() -> None:
    """The negative control: the pacer is `max(backoff, interval)`, not `max(backoff, 0)`."""
    clock = syn.ManualClock()
    pacer = Pacer(min_interval=5.0, clock=clock.time, sleeper=clock.sleep)
    pacer.wait()
    pacer.pause(1.0)
    assert pacer.wait() == 4.0
    assert clock.sleeps == [1.0, 4.0]


# ---------------------------------------------------------------------------
# E -- retries
# ---------------------------------------------------------------------------


def test_a_retryable_status_is_attempted_again_up_to_the_bound() -> None:
    transport = syn.ScriptedTransport([syn.failing(500), syn.failing(500), syn.ok()])
    clock = syn.ManualClock()
    payload = client(transport, clock).fetch(syn.stocks_request())
    assert payload == syn.SYNTHETIC_PAYLOAD
    assert transport.call_count == 3
    # Only the two backoffs. Each already exceeds the one-second pacing interval,
    # so the paced wait before the next attempt has nothing left to sleep -- the
    # delay is `max(backoff, interval)` rather than the sum of the two.
    assert clock.sleeps == [2.0, 8.0]


def test_a_network_failure_is_retried_and_then_reported_sanitized() -> None:
    outcomes = [
        TransportUnavailableError(SharadarErrorCode.NETWORK_TIMEOUT),
        TransportUnavailableError(SharadarErrorCode.NETWORK_TIMEOUT),
        TransportUnavailableError(SharadarErrorCode.NETWORK_TIMEOUT),
    ]
    transport = syn.ScriptedTransport(outcomes)
    with pytest.raises(SharadarRequestError) as caught:
        client(transport, syn.ManualClock()).fetch(syn.stocks_request())
    assert transport.call_count == 3
    assert caught.value.code is SharadarErrorCode.NETWORK_TIMEOUT
    assert caught.value.retryable is True


def test_an_authorization_refusal_is_not_retried() -> None:
    """A rejected key is rejected every time; retrying makes one refusal into several."""
    transport = syn.ScriptedTransport([syn.failing(403), syn.ok()])
    clock = syn.ManualClock()
    with pytest.raises(SharadarRequestError) as caught:
        client(transport, clock).fetch(syn.stocks_request())
    assert transport.call_count == 1
    assert clock.sleeps == []
    assert caught.value.retryable is False
    assert SharadarErrorCode.HTTP_AUTHORIZATION_REFUSED not in RETRYABLE_CODES


def test_a_non_rate_limit_client_error_is_not_retried() -> None:
    transport = syn.ScriptedTransport([syn.failing(400), syn.ok()])
    with pytest.raises(SharadarRequestError):
        client(transport, syn.ManualClock()).fetch(syn.stocks_request())
    assert transport.call_count == 1


def test_a_rate_limit_is_retried_because_it_can_clear() -> None:
    transport = syn.ScriptedTransport([syn.failing(429), syn.ok()])
    payload = client(transport, syn.ManualClock()).fetch(syn.stocks_request())
    assert payload == syn.SYNTHETIC_PAYLOAD
    assert transport.call_count == 2


def test_a_retry_schedule_is_bounded_and_stated_rather_than_derived() -> None:
    assert DEFAULT_RETRY_POLICY.max_attempts == 3
    assert len(DEFAULT_RETRY_POLICY.backoff_seconds) == DEFAULT_RETRY_POLICY.max_attempts - 1
    for bad in (
        {"max_attempts": 0, "backoff_seconds": ()},
        {
            "max_attempts": MAX_ATTEMPTS_CEILING + 1,
            "backoff_seconds": (1.0,) * MAX_ATTEMPTS_CEILING,
        },
        {"max_attempts": 3, "backoff_seconds": (1.0,)},
        {"max_attempts": 2, "backoff_seconds": (0.0,)},
    ):
        with pytest.raises(SharadarRequestError):
            RetryPolicy(**bad)  # type: ignore[arg-type]


def test_a_single_attempt_policy_never_sleeps_between_attempts() -> None:
    transport = syn.ScriptedTransport([syn.failing(500)])
    clock = syn.ManualClock()
    once = RetryPolicy(max_attempts=1, backoff_seconds=())
    with pytest.raises(SharadarRequestError):
        client(transport, clock, retry_policy=once).fetch(syn.stocks_request())
    assert transport.call_count == 1
    assert clock.sleeps == []


def test_an_empty_body_is_preserved_rather_than_refused() -> None:
    """Emptiness is a fact about the range. Bronze preserves what arrived."""
    transport = syn.ScriptedTransport([syn.ok(b"")])
    assert client(transport, syn.ManualClock()).fetch(syn.stocks_request()) == b""


def test_the_bytes_returned_are_the_bytes_received() -> None:
    payload = bytes(range(256))
    transport = syn.ScriptedTransport([syn.ok(payload)])
    assert client(transport, syn.ManualClock()).fetch(syn.stocks_request()) == payload
