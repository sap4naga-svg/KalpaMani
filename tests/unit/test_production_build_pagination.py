"""Build-side pagination admission, v2: one proven-complete data page per group, every refusal.

The direct cases drive the gate over hand-built pages; the end-to-end cases run the real
acquisition path into a fake store and the real build over it, and the adapter cases run the
merged production provider adapter over a URL-decoding scripted transport. No provider or
AWS call; synthetic results are not provider or AWS verification.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any, Final

import pytest

from fixtures.production_build import (
    RUN_1,
    RUN_1_AT,
    RUN_2,
    RUN_2_AT,
    STOCKS_HEADER,
    BuildScenario,
    FakeS3Store,
    acquire,
    csv,
    responses_for_run,
    slice_with_stocks_window,
    stocks_rows,
)
from fixtures.production_provider import CoordinateTransport
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.production.sharadar import build_processing as bp
from kalpamani.data.production.sharadar import pagination as pg
from kalpamani.data.production.sharadar import processing as pp
from kalpamani.data.production.sharadar import silver as sv
from kalpamani.data.production.sharadar.build_inputs import AcquiredPage
from kalpamani.data.production.sharadar.completion import (
    CompletionOutcome,
    PaginationEvidence,
    ParserOutcome,
    ProbeEvidence,
    ProbeOutcome,
    request_shape_digest,
)
from kalpamani.data.production.sharadar.provider import SharadarProductionProvider
from kalpamani.data.qualify.sharadar.parser import ParsedPage, parse_payload

pytestmark = pytest.mark.unit

STOCKS_LIMIT: Final = 10000
WINDOW: Final = "2026-09-01/2026-09-01"
Coordinate = tuple[str, str, int]


def rows_for(n: int, start: int = 0) -> list[tuple[str, ...]]:
    """``n`` distinct synthetic stocks rows."""
    return [
        (
            f"ZY{start + i:05d}",
            "2026-09-01",
            "1",
            "2",
            "0.5",
            "1.5",
            "10",
            "1.5",
            "1.5",
            "2026-09-04",
        )
        for i in range(n)
    ]


def parsed(rows: list[tuple[str, ...]]) -> ParsedPage:
    return parse_payload(csv(STOCKS_HEADER, rows), dataset=SharadarDataset.STOCKS)


def evidence(
    *,
    limit: int,
    rows: int,
    schema: str,
    probe_rows: int | None = None,
    probe_schema: str | None = None,
) -> PaginationEvidence:
    """Short-page evidence, or full-page evidence with a passed probe when ``probe_rows`` is 0."""
    if probe_rows is None:
        return PaginationEvidence(
            governed_limit=limit,
            row_count=rows,
            schema_digest=schema,
            parser_outcome=ParserOutcome.PARSED,
            completion=CompletionOutcome.SHORT_PAGE_COMPLETE,
            probe=None,
        )
    return PaginationEvidence(
        governed_limit=limit,
        row_count=rows,
        schema_digest=schema,
        parser_outcome=ParserOutcome.PARSED,
        completion=CompletionOutcome.PROBE_PASSED,
        probe=ProbeEvidence(
            request_shape_sha256=request_shape_digest(
                dataset="stocks", window=WINDOW, predicate=(), page_offset=limit, page_limit=limit
            ),
            page_offset=limit,
            page_limit=limit,
            response_sha256="cd" * 32,
            byte_count=32,
            row_count=probe_rows,
            schema_digest=schema if probe_schema is None else probe_schema,
            parser_outcome=ParserOutcome.PARSED,
            outcome=ProbeOutcome.PROBE_PASSED,
        ),
    )


def unchecked(**fields: Any) -> PaginationEvidence:
    """An evidence value built past the state machine, so the gate's own branch is exercised."""
    value = object.__new__(PaginationEvidence)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def acquired(
    *,
    evidence_value: PaginationEvidence,
    offset: int = 0,
    limit: int = 5,
    run_id: str = "r",
    window: str = WINDOW,
    predicate: tuple[tuple[str, str], ...] = (),
    ordinal: int = 0,
) -> AcquiredPage:
    at = datetime(2026, 9, 5, tzinfo=UTC)
    return AcquiredPage(
        run_id=run_id,
        ordinal=ordinal,
        dataset="stocks",
        window=window,
        predicate=predicate,
        page_offset=offset,
        page_limit=limit,
        pagination=evidence_value,
        acquisition_mode="BACKFILL",
        retrieved_at=at,
        payload=b"",
        payload_sha256="0" * 64,
        payload_bytes=0,
        record_sha256="0" * 64,
        run_started_at=at,
        run_completed_at=at,
    )


def build_over(
    responses: dict[Coordinate, bytes],
) -> tuple[bp.BuildReport, BuildScenario, FakeS3Store]:
    store = FakeS3Store()
    acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT, responses=responses)
    scenario = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),))
    return scenario.run(), scenario, store


def assert_refused(
    report: bp.BuildReport, scenario: BuildScenario, store: FakeS3Store, defect: sv.SilverDefect
) -> None:
    assert report.status is bp.BuildStatus.REFUSED_NORMALIZATION
    assert report.defect == defect.value
    gets, puts = scenario.data_plane_calls()
    assert puts == 0 and report.counts.s3_operations == gets and report.objects_read == gets
    assert store.keys_under("silver/") == [] and store.keys_under("gold/") == []
    assert store.keys_under("manifests/") == []
    assert report.manifest.value == "NOT_ATTEMPTED" and report.publication is None


# ---------------------------------------------------------------------------
# The gate, directly: the v2 state machine over one group
# ---------------------------------------------------------------------------


class TestTheGate:
    def test_a_short_page_without_a_probe_is_admitted(self) -> None:
        page = parsed(rows_for(3))
        summary = pg.admit_pagination(
            [(acquired(evidence_value=evidence(limit=5, rows=3, schema=page.schema_digest)), page)]
        )
        assert summary.policy_version == "sharadar-pagination-admission-v2"
        assert summary.groups_admitted == {"stocks": 1}
        assert summary.groups_empty == {"stocks": 0} and summary.groups_probed == {"stocks": 0}
        document = summary.document()
        assert "groups_probed" in document and document["establishes"]
        assert "vendor completeness of the window" in document["does_not_establish"]

    def test_an_empty_page_is_consistent_and_claims_nothing(self) -> None:
        page = parsed([])
        summary = pg.admit_pagination(
            [(acquired(evidence_value=evidence(limit=5, rows=0, schema=page.schema_digest)), page)]
        )
        assert summary.groups_empty == {"stocks": 1}

    def test_a_full_page_with_a_passed_probe_is_admitted_and_counted_as_probed(self) -> None:
        page = parsed(rows_for(5))
        summary = pg.admit_pagination(
            [
                (
                    acquired(
                        evidence_value=evidence(
                            limit=5, rows=5, schema=page.schema_digest, probe_rows=0
                        )
                    ),
                    page,
                )
            ]
        )
        assert summary.groups_admitted == {"stocks": 1} and summary.groups_probed == {"stocks": 1}

    def test_a_full_page_without_probe_evidence_is_unproven(self) -> None:
        page = parsed(rows_for(5))
        value = unchecked(
            governed_limit=5,
            row_count=5,
            schema_digest=page.schema_digest,
            parser_outcome=ParserOutcome.PARSED,
            completion=CompletionOutcome.SHORT_PAGE_COMPLETE,
            probe=None,
        )
        with pytest.raises(pg.PaginationError) as refused:
            pg.admit_pagination([(acquired(evidence_value=value), page)])
        assert refused.value.defect is pg.PaginationDefect.COMPLETION_UNPROVEN

    @pytest.mark.parametrize(
        ("probe_rows", "probe_schema", "outcome"),
        [
            (1, None, ProbeOutcome.PROBE_PASSED),
            (0, "ab" * 32, ProbeOutcome.PROBE_PASSED),
            (0, None, ProbeOutcome.PROBE_DATA_BEARING),
            (0, None, ProbeOutcome.PROBE_REFUSED),
        ],
        ids=["data-bearing", "schema-mismatch", "outcome-data-bearing", "outcome-refused"],
    )
    def test_a_full_page_whose_probe_failed_is_truncated(
        self, probe_rows: int, probe_schema: str | None, outcome: ProbeOutcome
    ) -> None:
        page = parsed(rows_for(5))
        good = evidence(limit=5, rows=5, schema=page.schema_digest, probe_rows=0)
        assert good.probe is not None
        probe = ProbeEvidence(
            request_shape_sha256=good.probe.request_shape_sha256,
            page_offset=5,
            page_limit=5,
            response_sha256="cd" * 32,
            byte_count=32,
            row_count=probe_rows,
            schema_digest=page.schema_digest if probe_schema is None else probe_schema,
            parser_outcome=ParserOutcome.PARSED,
            outcome=outcome,
        )
        value = unchecked(
            governed_limit=5,
            row_count=5,
            schema_digest=page.schema_digest,
            parser_outcome=ParserOutcome.PARSED,
            completion=CompletionOutcome.PROBE_PASSED,
            probe=probe,
        )
        with pytest.raises(pg.PaginationError) as refused:
            pg.admit_pagination([(acquired(evidence_value=value), page)])
        assert refused.value.defect is pg.PaginationDefect.DELIVERY_TRUNCATED

    def test_more_rows_than_the_governed_limit_is_over_limit(self) -> None:
        page = parsed(rows_for(6))
        value = unchecked(
            governed_limit=5,
            row_count=6,
            schema_digest=page.schema_digest,
            parser_outcome=ParserOutcome.PARSED,
            completion=CompletionOutcome.SHORT_PAGE_COMPLETE,
            probe=None,
        )
        with pytest.raises(pg.PaginationError) as refused:
            pg.admit_pagination([(acquired(evidence_value=value), page)])
        assert refused.value.defect is pg.PaginationDefect.PAGE_OVER_LIMIT

    def test_evidence_that_disagrees_with_the_parsed_page_is_inconsistent(self) -> None:
        page = parsed(rows_for(3))
        schema = page.schema_digest
        for value in (
            evidence(limit=5, rows=2, schema=schema),  # recorded rows are not the page's
            evidence(limit=5, rows=3, schema="ab" * 32),  # recorded schema is not the page's
            evidence(limit=6, rows=3, schema=schema),  # recorded limit is not the coordinate's
            evidence(limit=5, rows=5, schema=schema, probe_rows=0),  # a probe on a short page
        ):
            with pytest.raises(pg.PaginationError) as refused:
                pg.admit_pagination([(acquired(evidence_value=value), page)])
            assert refused.value.defect is pg.PaginationDefect.PAGINATION_INCONSISTENT

    def test_a_second_page_or_a_positive_offset_is_unsupported(self) -> None:
        page = parsed(rows_for(3))
        value = evidence(limit=5, rows=3, schema=page.schema_digest)
        with pytest.raises(pg.PaginationError) as refused:
            pg.admit_pagination(
                [
                    (acquired(evidence_value=value), page),
                    (acquired(evidence_value=value, offset=5, ordinal=1), parsed([])),
                ]
            )
        assert refused.value.defect is pg.PaginationDefect.PAGINATION_UNSUPPORTED
        with pytest.raises(pg.PaginationError) as refused:
            pg.admit_pagination([(acquired(evidence_value=value, offset=5), page)])
        assert refused.value.defect is pg.PaginationDefect.PAGINATION_UNSUPPORTED

    def test_groups_are_keyed_by_run_window_and_predicate(self) -> None:
        page = parsed(rows_for(3))
        value = evidence(limit=5, rows=3, schema=page.schema_digest)
        summary = pg.admit_pagination(
            [
                (acquired(evidence_value=value), page),
                (acquired(evidence_value=value, run_id="s"), page),
                (acquired(evidence_value=value, window="2026-09-02/2026-09-02", ordinal=1), page),
                (acquired(evidence_value=value, predicate=(("table", "x"),), ordinal=2), page),
            ]
        )
        assert summary.groups_admitted == {"stocks": 4}

    def test_the_gate_vocabulary_maps_totally_onto_silver(self) -> None:
        assert set(sv._PAGINATION_DEFECTS) == set(pg.PaginationDefect)
        assert len({member.value for member in sv._PAGINATION_DEFECTS.values()}) == len(
            pg.PaginationDefect
        )
        assert pg.SUPERSEDED_PAGINATION_POLICY_VERSIONS == {"sharadar-pagination-admission-v1"}

    def test_a_non_pair_is_a_caller_defect(self) -> None:
        with pytest.raises(TypeError):
            pg.admit_pagination([("page", "parsed")])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# End to end: the real acquisition, the real build
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_short_pages_publish_and_the_manifest_records_no_probe(self) -> None:
        report, _, store = build_over(responses_for_run(1))
        assert report.status is bp.BuildStatus.COMPLETED, report.defect
        manifest = json.loads(store.objects[store.keys_under("manifests/")[0]])
        assert manifest["pagination"]["groups_probed"] == {"actions": 0, "stocks": 0, "tickers": 0}
        assert manifest["pagination"]["groups_admitted"] == {
            "actions": 1,
            "stocks": 5,
            "tickers": 1,
        }

    def test_a_short_page_below_the_limit_by_one_row_is_admitted(self) -> None:
        responses = responses_for_run(1)
        base = stocks_rows(date(2026, 9, 1), run=1)
        responses[("stocks", WINDOW, 0)] = csv(
            STOCKS_HEADER, [*base, *rows_for(STOCKS_LIMIT - 1 - len(base))]
        )
        report, _, _ = build_over(responses)
        assert report.status is bp.BuildStatus.COMPLETED, report.defect

    def test_a_full_page_issues_one_probe_through_the_adapter_and_the_build_admits_it(
        self,
    ) -> None:
        responses = responses_for_run(1)
        base = stocks_rows(date(2026, 9, 1), run=1)
        responses[("stocks", WINDOW, 0)] = csv(
            STOCKS_HEADER, [*base, *rows_for(STOCKS_LIMIT - len(base))]
        )
        responses[("stocks", WINDOW, STOCKS_LIMIT)] = csv(STOCKS_HEADER, [])
        store = FakeS3Store()
        transport = CoordinateTransport(responses=responses)
        provider = SharadarProductionProvider(transport=transport)
        acquisition = acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT, provider=provider)
        assert acquisition.status is pp.AcquisitionStatus.COMPLETED
        assert acquisition.probes_issued == 1
        assert provider.transport_invocations == transport.call_count == 8
        assert transport.coordinates.count(("stocks", WINDOW, STOCKS_LIMIT)) == 1
        # The probe writes nothing: 1 + 3 x 7 + 1.
        assert acquisition.counts.s3_operations == 23
        scenario = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),))
        report = scenario.run()
        assert report.status is bp.BuildStatus.COMPLETED, report.defect
        manifest = json.loads(store.objects[store.keys_under("manifests/")[0]])
        assert manifest["pagination"]["groups_probed"]["stocks"] == 1
        assert manifest["build_input"]["runs"][0]["probes_issued"] == 1
        assert manifest["build_input"]["runs"][0]["provider_calls"] == 8

    def test_a_data_bearing_probe_halts_the_acquisition_with_no_write_for_the_group(
        self,
    ) -> None:
        responses = responses_for_run(1)
        base = stocks_rows(date(2026, 9, 1), run=1)
        responses[("stocks", WINDOW, 0)] = csv(
            STOCKS_HEADER, [*base, *rows_for(STOCKS_LIMIT - len(base))]
        )
        responses[("stocks", WINDOW, STOCKS_LIMIT)] = csv(STOCKS_HEADER, rows_for(1, 90000))
        store = FakeS3Store()
        acquisition = acquire(
            store, run_id=RUN_1, run=1, at=RUN_1_AT, responses=responses, expect_completed=False
        )
        assert acquisition.status is pp.AcquisitionStatus.HALTED
        assert acquisition.halt is pp.ProcessingHalt.PROBE_DATA_BEARING
        # The actions coordinate and the 08-31 session (ordinals 0 and 1) completed; the
        # full 09-01 page (ordinal 2) wrote nothing: reservation + 2 x 3 + the PARTIAL locator.
        assert acquisition.completed_requests == 2 and acquisition.counts.s3_operations == 8
        assert acquisition.counts.provider_requests == 4  # two data requests, the data
        # request of the full page, and its probe
        document = json.loads(store.objects[f"bronze/sharadar/_indexes/{RUN_1}.json"])
        assert document["completeness"] == "PARTIAL" and document["probes_issued"] == 0
        assert document["provider_calls"] == 4
        report = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),)).run()
        assert report.status is bp.BuildStatus.REFUSED_INPUTS

    def test_an_unscripted_probe_is_a_refused_probe_and_halts(self) -> None:
        responses = responses_for_run(1)
        base = stocks_rows(date(2026, 9, 1), run=1)
        responses[("stocks", WINDOW, 0)] = csv(
            STOCKS_HEADER, [*base, *rows_for(STOCKS_LIMIT - len(base))]
        )
        store = FakeS3Store()
        acquisition = acquire(
            store, run_id=RUN_1, run=1, at=RUN_1_AT, responses=responses, expect_completed=False
        )
        assert acquisition.halt is pp.ProcessingHalt.PROBE_REFUSED

    def test_wide_windows_keep_their_own_groups(self) -> None:
        wide = slice_with_stocks_window(2, "2026-09-01/2026-09-14")
        store = FakeS3Store()
        acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT)
        acquire(
            store,
            run_id=RUN_2,
            run=2,
            at=RUN_2_AT,
            responses=responses_for_run(2, wide),
            slice_doc=wide,
        )
        scenario = BuildScenario(store, slices={RUN_2: wide})
        report = scenario.run()
        assert report.status is bp.BuildStatus.COMPLETED, report.defect
        manifest = json.loads(store.objects[store.keys_under("manifests/")[0]])
        # 5 stocks groups from run 1 and 14 from run 2: never merged into one.
        assert manifest["pagination"]["groups_admitted"]["stocks"] == 19
