"""The production provider request contract (proposed ADR-0041) and its offline adapter.

Every request here goes through the real ``SharadarProductionProvider`` into the accepted
``SharadarClient`` and a scripted transport that decodes the URL the adapter built. No
socket is opened; **synthetic transport results are not provider or AWS verification**.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

import pytest

from fixtures.production_build import (
    RUN_1,
    RUN_1_AT,
    RUN_2,
    RUN_2_AT,
    SECRET_VALUE,
    ZZAA,
    BuildScenario,
    FakeS3Store,
    acquire,
    responses_for_run,
    slice_for_run,
)
from fixtures.production_provider import CoordinateTransport
from fixtures.sharadar_provider import (
    SYNTHETIC_CREDENTIAL_VALUE,
    actions_request,
    credential,
    stocks_request,
    tickers_request,
)
from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.ingest.sharadar.client import DEFAULT_USER_AGENT
from kalpamani.data.ingest.sharadar.datasets import (
    API_BASE_URL,
    CROSS_SECTION_PARAMETER_ALLOWLIST,
    FORBIDDEN_QUERY_PARAMETERS,
    QUERY_PARAMETER_ALLOWLIST,
    CrossSectionRequest,
    DateWindow,
    Page,
    ResponseFormat,
    SharadarDataset,
    SharadarRequest,
    build_cross_section_query_parameters,
    build_cross_section_url,
    build_query_parameters,
    describe_cross_section_request,
)
from kalpamani.data.ingest.sharadar.redaction import SharadarErrorCode, SharadarRequestError
from kalpamani.data.ingest.sharadar.transport import TransportResponse, TransportUnavailableError
from kalpamani.data.production.sharadar import processing as pp
from kalpamani.data.production.sharadar import provider as pv
from kalpamani.data.production.sharadar.inputs import parse_slice
from kalpamani.data.production.sharadar.plan import ProductionRequest, compile_plan
from kalpamani.data.qualify.sharadar.operations import AcquisitionDeadline

pytestmark = pytest.mark.unit

TICKERS_HEADER_ONLY: Final = b"table,permaticker,ticker\r\n"


def request(
    dataset: str, window: str, offset: int = 0, limit: int = 10000, ordinal: int = 0
) -> ProductionRequest:
    return ProductionRequest(
        ordinal=ordinal, dataset=dataset, window=window, page_offset=offset, page_limit=limit
    )


def provider_over(transport: CoordinateTransport) -> pv.SharadarProductionProvider:
    return pv.SharadarProductionProvider(transport=transport)


def query_of(url: str) -> dict[str, str]:
    return {name: values[0] for name, values in parse_qs(urlsplit(url).query).items()}


# ---------------------------------------------------------------------------
# The request form and its serialization
# ---------------------------------------------------------------------------


class TestCrossSectionForm:
    def test_the_accepted_qualification_form_serializes_unchanged(self) -> None:
        """The qualification path is untouched: same class, same parameters, same order."""
        parameters = build_query_parameters(stocks_request(), credential=credential())
        assert [name for name, _ in parameters] == [
            "api_key",
            "format",
            "ticker",
            "from",
            "to",
            "limit",
            "skip",
        ]
        snapshot = build_query_parameters(tickers_request(), credential=credential())
        assert [name for name, _ in snapshot] == ["api_key", "format", "ticker", "limit", "skip"]
        assert QUERY_PARAMETER_ALLOWLIST == frozenset(
            {"api_key", "format", "ticker", "from", "to", "limit", "skip"}
        )
        assert FORBIDDEN_QUERY_PARAMETERS == frozenset(
            {"years", "fields", "sort", "lastupdated.gte", "lastupdated"}
        )
        with pytest.raises(SharadarRequestError):
            SharadarRequest(
                dataset=SharadarDataset.STOCKS,
                ticker="",
                response_format=ResponseFormat.CSV,
                page=Page(limit=10, skip=0),
                window=DateWindow(start=date(2026, 9, 1), end=date(2026, 9, 1)),
            )
        assert actions_request().ticker

    def test_a_ticker_snapshot_carries_no_ticker_and_no_window(self) -> None:
        cross = pv.compile_cross_section(request("tickers", "SNAPSHOT", 20000))
        parameters = build_cross_section_query_parameters(cross, credential=credential())
        assert parameters == (
            ("api_key", SYNTHETIC_CREDENTIAL_VALUE),
            ("format", "csv"),
            ("limit", "10000"),
            ("skip", "20000"),
        )
        url = build_cross_section_url(cross, credential=credential())
        assert url.startswith(f"{API_BASE_URL}/tickers?")
        assert "ticker=" not in url and "from=" not in url and "to=" not in url
        assert cross.requested_range == "SNAPSHOT"
        assert " ticker " not in describe_cross_section_request(cross)
        assert SYNTHETIC_CREDENTIAL_VALUE not in describe_cross_section_request(cross)

    def test_an_action_window_and_a_stock_session_encode_their_exact_dates(self) -> None:
        window = pv.compile_cross_section(request("actions", "2026-08-01/2026-09-14", 10000))
        assert build_cross_section_query_parameters(window, credential=credential()) == (
            ("api_key", SYNTHETIC_CREDENTIAL_VALUE),
            ("format", "csv"),
            ("from", "2026-08-01"),
            ("to", "2026-09-14"),
            ("limit", "10000"),
            ("skip", "10000"),
        )
        session = pv.compile_cross_section(request("stocks", "2026-09-03/2026-09-03"))
        query = query_of(build_cross_section_url(session, credential=credential()))
        assert query["from"] == query["to"] == "2026-09-03"
        assert query["skip"] == "0" and query["limit"] == "10000" and "ticker" not in query
        assert session.requested_range == "2026-09-03/2026-09-03"

    def test_every_transmitted_name_is_on_the_accepted_allowlist_and_ticker_is_never_sent(
        self,
    ) -> None:
        assert CROSS_SECTION_PARAMETER_ALLOWLIST == QUERY_PARAMETER_ALLOWLIST - {"ticker"}
        for coordinates in (
            ("tickers", "SNAPSHOT"),
            ("stocks", "2026-09-01/2026-09-01"),
            ("actions", "2026-01-01/2026-12-31"),
        ):
            cross = pv.compile_cross_section(request(*coordinates))
            names = {
                name
                for name, _ in build_cross_section_query_parameters(cross, credential=credential())
            }
            assert (
                names <= CROSS_SECTION_PARAMETER_ALLOWLIST
                and not names & FORBIDDEN_QUERY_PARAMETERS
            )
            assert "ticker" not in names

    def test_the_form_itself_refuses_a_window_on_the_snapshot_and_none_on_a_windowed_table(
        self,
    ) -> None:
        with pytest.raises(SharadarRequestError):
            CrossSectionRequest(
                dataset=SharadarDataset.TICKERS,
                response_format=ResponseFormat.CSV,
                page=Page(limit=10, skip=0),
                window=DateWindow(start=date(2026, 9, 1), end=date(2026, 9, 1)),
            )
        with pytest.raises(SharadarRequestError):
            CrossSectionRequest(
                dataset=SharadarDataset.STOCKS,
                response_format=ResponseFormat.CSV,
                page=Page(limit=10, skip=0),
                window=None,
            )
        with pytest.raises(SharadarRequestError):
            build_cross_section_query_parameters(stocks_request(), credential=credential())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Refusals before the transport
# ---------------------------------------------------------------------------


class TestRefusedBeforeTransport:
    @pytest.mark.parametrize(
        ("coordinates", "refusal"),
        [
            (("tickers", "2026-09-01/2026-09-01"), pv.ProviderRefusal.WINDOW_NOT_ALLOWED),
            (("stocks", "SNAPSHOT"), pv.ProviderRefusal.WINDOW_REQUIRED),
            (("actions", "SNAPSHOT"), pv.ProviderRefusal.WINDOW_REQUIRED),
            (("fundamentals", "2026-09-01/2026-09-01"), pv.ProviderRefusal.DATASET_UNSUPPORTED),
            (("stocks", "2026-09-02/2026-09-01"), pv.ProviderRefusal.WINDOW_MALFORMED),
            (("stocks", "2026-9-1/2026-09-01"), pv.ProviderRefusal.WINDOW_MALFORMED),
            (("stocks", "2026-09-01"), pv.ProviderRefusal.WINDOW_MALFORMED),
            (("stocks", "2026-09-01/2026-09-01/2026-09-02"), pv.ProviderRefusal.WINDOW_MALFORMED),
            (("stocks", "20260901/20260901"), pv.ProviderRefusal.WINDOW_MALFORMED),
        ],
    )
    def test_unsupported_combinations_and_malformed_windows_never_reach_the_transport(
        self, coordinates: tuple[str, str], refusal: pv.ProviderRefusal
    ) -> None:
        transport = CoordinateTransport(responses={})
        provider = provider_over(transport)
        with pytest.raises(pv.ProviderRefusedError) as refused:
            provider.fetch(request(*coordinates), credential=credential())
        assert refused.value.refusal is refusal
        assert transport.call_count == 0 and provider.transport_invocations == 0

    @pytest.mark.parametrize(("offset", "limit"), [(0, 0), (0, 10001), (-1, 10000), (0, -5)])
    def test_a_malformed_page_never_reaches_the_transport(self, offset: int, limit: int) -> None:
        transport = CoordinateTransport(responses={})
        provider = provider_over(transport)
        with pytest.raises(pv.ProviderRefusedError) as refused:
            provider.fetch(
                request("stocks", "2026-09-01/2026-09-01", offset, limit), credential=credential()
            )
        assert refused.value.refusal is pv.ProviderRefusal.PAGE_MALFORMED
        assert transport.call_count == 0

    def test_a_non_request_or_non_credential_is_refused_before_the_transport(self) -> None:
        transport = CoordinateTransport(responses={})
        provider = provider_over(transport)
        with pytest.raises(pv.ProviderRefusedError):
            provider.fetch("not-a-request", credential=credential())  # type: ignore[arg-type]
        with pytest.raises(pv.ProviderRefusedError):
            provider.fetch(request("tickers", "SNAPSHOT"), credential="not-a-credential")  # type: ignore[arg-type]
        assert transport.call_count == 0

    def test_the_adapter_refuses_a_transport_without_the_accepted_shape(self) -> None:
        with pytest.raises(TypeError):
            pv.SharadarProductionProvider(transport=object())  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            pv.SharadarProductionProvider(
                transport=CoordinateTransport(responses={}), timeout_seconds=0.0
            )


# ---------------------------------------------------------------------------
# Through the accepted transport seam
# ---------------------------------------------------------------------------


class TestTransportSeam:
    def test_one_fetch_is_one_transport_call_with_the_fixed_headers_and_timeout(self) -> None:
        transport = CoordinateTransport(responses={("tickers", "SNAPSHOT", 0): TICKERS_HEADER_ONLY})
        provider = provider_over(transport)
        body = provider.fetch(request("tickers", "SNAPSHOT"), credential=credential())
        assert body == TICKERS_HEADER_ONLY
        assert transport.call_count == provider.transport_invocations == 1
        assert transport.headers[0]["User-Agent"] == DEFAULT_USER_AGENT
        assert set(transport.headers[0]) == {"User-Agent", "Accept-Encoding"}
        assert transport.timeouts == [30.0]
        assert transport.coordinates == [("tickers", "SNAPSHOT", 0)]
        assert transport.queries[0]["format"] == ["csv"]
        assert transport.queries[0]["api_key"] == [SYNTHETIC_CREDENTIAL_VALUE]

    @pytest.mark.parametrize(
        ("outcome", "code"),
        [
            (
                TransportUnavailableError(SharadarErrorCode.NETWORK_TIMEOUT),
                SharadarErrorCode.NETWORK_TIMEOUT,
            ),
            (
                TransportUnavailableError(SharadarErrorCode.RESPONSE_TOO_LARGE),
                SharadarErrorCode.RESPONSE_TOO_LARGE,
            ),
            (
                TransportUnavailableError(SharadarErrorCode.HTTP_REDIRECT_REFUSED),
                SharadarErrorCode.HTTP_REDIRECT_REFUSED,
            ),
            (TransportResponse(status=429, body=b""), SharadarErrorCode.HTTP_RATE_LIMITED),
            (TransportResponse(status=401, body=b""), SharadarErrorCode.HTTP_AUTHORIZATION_REFUSED),
            (TransportResponse(status=403, body=b""), SharadarErrorCode.HTTP_AUTHORIZATION_REFUSED),
            (TransportResponse(status=500, body=b""), SharadarErrorCode.HTTP_SERVER_ERROR),
            ("not-a-response", SharadarErrorCode.RESPONSE_READ_FAILED),
            (
                RuntimeError("synthetic transport explosion with url=https://leak"),
                SharadarErrorCode.RESPONSE_READ_FAILED,
            ),
        ],
    )
    def test_every_failure_is_one_sanitized_refusal_with_exactly_one_attempt(
        self, outcome: Any, code: SharadarErrorCode
    ) -> None:
        coordinate = ("stocks", "2026-09-03/2026-09-03", 0)
        transport = CoordinateTransport(responses={}, failures={coordinate: outcome})
        provider = provider_over(transport)
        with pytest.raises(SharadarRequestError) as refused:
            provider.fetch(request("stocks", "2026-09-03/2026-09-03"), credential=credential())
        assert refused.value.code is code
        # One attempt: a throttle, a timeout or a server error is not retried here.
        assert transport.call_count == 1 and provider.transport_invocations == 1
        rendered = repr(refused.value) + str(refused.value) + repr(provider)
        assert SYNTHETIC_CREDENTIAL_VALUE not in rendered and "https://" not in rendered

    def test_the_credential_reaches_only_the_url_and_never_a_header_or_a_refusal(self) -> None:
        transport = CoordinateTransport(responses={("tickers", "SNAPSHOT", 0): b"x\r\n"})
        provider = provider_over(transport)
        provider.fetch(request("tickers", "SNAPSHOT"), credential=credential())
        assert SYNTHETIC_CREDENTIAL_VALUE in transport.urls[0]  # the vendor's query-string key
        assert all(SYNTHETIC_CREDENTIAL_VALUE not in v for v in transport.headers[0].values())


# ---------------------------------------------------------------------------
# Through the acquisition processor and the build reader
# ---------------------------------------------------------------------------


def transport_for_run(run: int, **overrides: Any) -> CoordinateTransport:
    return CoordinateTransport(responses=responses_for_run(run), **overrides)


class TestAcquisitionIntegration:
    def test_a_run_through_the_real_adapter_completes_and_counts_transport_calls(self) -> None:
        store = FakeS3Store()
        transport = transport_for_run(1)
        provider = provider_over(transport)
        report = acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT, provider=provider)
        assert report.status is pp.AcquisitionStatus.COMPLETED
        plan = compile_plan(
            parse_slice(slice_for_run(1)), acquisition_mode=AcquisitionMode.BACKFILL
        )
        expected = [(r.dataset, r.window, r.page_offset) for r in plan.requests]
        # The transport saw exactly the compiled coordinates, in plan order, once each.
        assert transport.coordinates == expected
        assert (
            report.counts.provider_requests
            == transport.call_count
            == provider.transport_invocations
            == 16
        )
        assert all(t == 30.0 for t in transport.timeouts)
        assert all("ticker" not in q for q in transport.queries)
        # Pagination: page two of every window is skip=10000, and the terminal page is header-only.
        assert [c for c in transport.coordinates if c[0] == "actions"] == [
            ("actions", "2026-08-01/2026-09-14", 0),
            ("actions", "2026-08-01/2026-09-14", 10000),
        ]
        assert [c[2] for c in transport.coordinates if c[0] == "tickers"] == [
            0,
            10000,
            20000,
            30000,
        ]
        # Every published object is the bytes the transport returned, keyed by request identity.
        document = json.loads(store.objects[f"bronze/sharadar/_indexes/{RUN_1}.json"])
        assert document["completeness"] == "COMPLETE" and len(document["entries"]) == 16
        windows = {
            (e["dataset"], e["request"]["window"], e["request"]["page_offset"])
            for e in document["entries"]
        }
        assert windows == set(expected)
        for entry in document["entries"]:
            key = entry["payload_key"].removeprefix("licensed/")
            coordinate = (
                entry["dataset"],
                entry["request"]["window"],
                entry["request"]["page_offset"],
            )
            assert store.objects[key] == transport.responses[coordinate]

    def test_a_failing_page_halts_the_run_partial_and_is_never_reported_complete(self) -> None:
        store = FakeS3Store()
        failing = ("stocks", "2026-09-02/2026-09-02", 10000)
        transport = transport_for_run(
            1, failures={failing: TransportUnavailableError(SharadarErrorCode.NETWORK_TIMEOUT)}
        )
        provider = provider_over(transport)
        report = acquire(
            store, run_id=RUN_1, run=1, at=RUN_1_AT, provider=provider, expect_completed=False
        )
        assert report.status is pp.AcquisitionStatus.HALTED
        assert report.halt is pp.ProcessingHalt.PROVIDER_FAILURE
        index = transport.coordinates.index(failing)
        assert report.completed_requests == index and transport.call_count == index + 1
        assert report.counts.provider_requests == transport.call_count
        document = json.loads(store.objects[f"bronze/sharadar/_indexes/{RUN_1}.json"])
        assert document["completeness"] == "PARTIAL" and len(document["entries"]) == index
        # A PARTIAL locator refuses the build for that run.
        scenario = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),))
        assert scenario.run().status.value == "REFUSED_INPUTS"

    def test_a_throttled_page_is_not_retried_by_the_adapter_or_the_processor(self) -> None:
        store = FakeS3Store()
        throttled = ("actions", "2026-08-01/2026-09-14", 10000)
        transport = transport_for_run(
            1, failures={throttled: TransportResponse(status=429, body=b"")}
        )
        provider = provider_over(transport)
        report = acquire(
            store, run_id=RUN_1, run=1, at=RUN_1_AT, provider=provider, expect_completed=False
        )
        assert report.status is pp.AcquisitionStatus.HALTED
        assert transport.coordinates.count(throttled) == 1
        assert report.counts.provider_requests == transport.call_count == 2

    def test_a_locally_refused_request_counts_zero_transport_invocations(self) -> None:
        """A provider that refuses before the transport is not a provider request."""
        transport = CoordinateTransport(responses={})
        provider = provider_over(transport)

        counting = pp._CountingProvider(
            provider,
            deadline=AcquisitionDeadline(monotonic=lambda: 0.0, deadline_seconds=1800.0),
        )
        counting._deadline.arm()
        with pytest.raises(pv.ProviderRefusedError):
            counting.fetch(request("stocks", "SNAPSHOT"), credential=credential())
        assert counting.request_count == 0 and transport.call_count == 0
        transport.responses[("tickers", "SNAPSHOT", 0)] = b"x\r\n"
        counting.fetch(request("tickers", "SNAPSHOT"), credential=credential())
        assert counting.request_count == 1 == transport.call_count

    def test_an_oversized_body_halts_by_the_plan_ceiling_after_one_call(self) -> None:
        store = FakeS3Store()
        big = ("tickers", "SNAPSHOT", 0)
        responses = responses_for_run(1)
        responses[big] = b"x" * (4 * 1024 * 1024 + 1)
        transport = CoordinateTransport(responses=responses)
        provider = provider_over(transport)
        report = acquire(
            store, run_id=RUN_1, run=1, at=RUN_1_AT, provider=provider, expect_completed=False
        )
        assert report.status is pp.AcquisitionStatus.HALTED
        assert report.halt is pp.ProcessingHalt.RESPONSE_TOO_LARGE
        assert transport.coordinates.count(big) == 1

    def test_two_runs_through_the_adapter_build_with_windows_and_sessions_distinguished(
        self,
    ) -> None:
        store = FakeS3Store()
        first = provider_over(transport_for_run(1))
        second = provider_over(transport_for_run(2))
        acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT, provider=first)
        acquire(store, run_id=RUN_2, run=2, at=RUN_2_AT, provider=second)
        assert first.transport_invocations == 16 and second.transport_invocations == 32
        scenario = BuildScenario(store)
        report = scenario.run()
        assert report.status.value == "COMPLETED", report.defect
        assert report.objects_read == 2 + 2 * (16 + 32)
        manifest = json.loads(store.objects[store.keys_under("manifests/")[0]])
        digests = {d for run in manifest["build_input"]["runs"] for d in run["payload_digests"]}
        distinct_bytes = set(responses_for_run(1).values()) | set(responses_for_run(2).values())
        assert len(digests) == len(distinct_bytes)
        assert report.publication is not None
        rows = json.loads(
            next(
                a.artifact.content
                for a in report.publication.artifacts
                if a.artifact.name == "gold-adjusted-bars"
            )
        )["rows"]
        assert {r["session_date"] for r in rows if r["security_id"] == ZZAA.security_id} >= {
            "2026-09-01",
            "2026-09-03",
            "2026-09-14",
        }
        assert SECRET_VALUE not in repr(report)
