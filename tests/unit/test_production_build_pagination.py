"""Build-side pagination admission: the one supported page shape, every refusal, per group.

Every case runs the real acquisition path into a fake store and the real build over it; the
integration cases run the merged production provider adapter over a URL-decoding scripted
transport. No provider or AWS call; synthetic results are not provider or AWS verification.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any, Final

import pytest

from fixtures.production_build import (
    ACTIONS_HEADER,
    RUN_1,
    RUN_1_AT,
    RUN_2,
    RUN_2_AT,
    STOCKS_HEADER,
    TICKERS_HEADER,
    BuildScenario,
    FakeS3Store,
    acquire,
    actions_rows,
    configuration,
    csv,
    responses_for_run,
    slice_with_stocks_window,
    stocks_rows,
    tickers_rows,
)
from fixtures.production_provider import CoordinateTransport
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.production.sharadar import build_processing as bp
from kalpamani.data.production.sharadar import pagination as pg
from kalpamani.data.production.sharadar import silver as sv
from kalpamani.data.production.sharadar.build_inputs import AcquiredPage
from kalpamani.data.production.sharadar.provider import SharadarProductionProvider
from kalpamani.data.qualify.sharadar.parser import parse_payload

pytestmark = pytest.mark.unit

LIMIT: Final = 10000
Coordinate = tuple[str, str, int]

#: One data-bearing coordinate per dataset, with its header, a row factory and the offsets
#: the compiled plan asks for beyond the first page.
DATASETS: Final[dict[str, tuple[Coordinate, tuple[str, ...], tuple[int, ...]]]] = {
    "tickers": (("tickers", "SNAPSHOT", 0), TICKERS_HEADER, (10000, 20000, 30000)),
    "stocks": (("stocks", "2026-09-02/2026-09-02", 0), STOCKS_HEADER, (10000,)),
    "actions": (("actions", "2026-08-01/2026-09-14", 0), ACTIONS_HEADER, (10000,)),
}


def rows_for(dataset: str, n: int, start: int = 0) -> list[tuple[str, ...]]:
    """``n`` distinct synthetic rows of one dataset."""
    if dataset == "tickers":
        return [
            (
                "SEP",
                str(300000 + start + i),
                f"ZY{start + i:05d}",
                "Synthetic",
                "NYSE",
                "N",
                "Domestic Common Stock",
                "",
                "",
                "2026-09-04",
                "2010-01-04",
                "2026-09-14",
            )
            for i in range(n)
        ]
    if dataset == "stocks":
        return [
            (
                f"ZY{start + i:05d}",
                "2026-09-02",
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
    return [
        ("2026-08-20", "dividend", f"ZY{start + i:05d}", "Synthetic", "0.01", "", "")
        for i in range(n)
    ]


def base_rows(dataset: str) -> list[tuple[str, ...]]:
    if dataset == "tickers":
        return tickers_rows(lastupdated="2026-09-04")
    if dataset == "stocks":
        return stocks_rows(date(2026, 9, 2), run=1)
    return actions_rows(run=1)


def page(dataset: str, offset: int) -> Coordinate:
    first, _, _ = DATASETS[dataset]
    return (first[0], first[1], offset)


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
# The supported shape
# ---------------------------------------------------------------------------


class TestSupportedShape:
    def test_a_short_first_page_and_header_only_later_pages_publish(self) -> None:
        report, _, store = build_over(responses_for_run(1))
        assert report.status is bp.BuildStatus.COMPLETED, report.defect
        manifest = json.loads(store.objects[store.keys_under("manifests/")[0]])
        pagination = manifest["pagination"]
        assert pagination["policy_version"] == pg.PAGINATION_POLICY_VERSION
        # Run 1: one tickers group, one actions group, five stocks groups (two of them
        # non-sessions and therefore entirely header-only).
        assert pagination["groups_admitted"] == {"actions": 1, "stocks": 5, "tickers": 1}
        assert pagination["groups_empty"] == {"actions": 0, "stocks": 0, "tickers": 0}
        assert pagination["establishes"] == []
        assert "vendor completeness of the window" in pagination["does_not_establish"]
        assert (
            manifest["transformation"]["pagination_policy_version"] == pg.PAGINATION_POLICY_VERSION
        )

    @pytest.mark.parametrize("dataset", ["tickers", "stocks", "actions"])
    def test_an_entirely_empty_group_is_consistent_and_claims_nothing(self, dataset: str) -> None:
        responses = responses_for_run(1)
        first, header, _ = DATASETS[dataset]
        responses[first] = csv(header, [])
        report, _, store = build_over(responses)
        assert report.status is bp.BuildStatus.COMPLETED, report.defect
        manifest = json.loads(store.objects[store.keys_under("manifests/")[0]])
        assert manifest["pagination"]["groups_empty"][dataset] >= 1
        if dataset == "tickers":
            # An empty snapshot is pagination-consistent and nothing more: every stocks
            # and actions symbol is then unmapped under the existing identity rule, and
            # the build publishes an empty result that says so rather than a universe.
            assert manifest["identity"]["stocks"]["unmapped_symbols"] > 0
            assert manifest["empty_reason"] is not None
        if dataset == "stocks":
            # The empty session is a calendar gap downstream, not a proof of emptiness.
            findings = {(f["check"], f["scope"]) for f in manifest["quality"]["findings"]}
            assert any(check == "MARKET_MISSING_SESSIONS" for check, _ in findings)

    def test_a_short_first_page_below_the_limit_by_one_row_is_admitted(self) -> None:
        responses = responses_for_run(1)
        responses[page("tickers", 0)] = csv(
            TICKERS_HEADER,
            base_rows("tickers") + rows_for("tickers", LIMIT - 1 - len(base_rows("tickers"))),
        )
        report, _, _ = build_over(responses)
        assert report.status is bp.BuildStatus.COMPLETED, report.defect


# ---------------------------------------------------------------------------
# Refusals, per dataset
# ---------------------------------------------------------------------------


class TestRefusals:
    @pytest.mark.parametrize("dataset", ["tickers", "stocks", "actions"])
    def test_a_full_first_page_followed_by_empty_pages_is_truncation(self, dataset: str) -> None:
        responses = responses_for_run(1)
        first, header, _ = DATASETS[dataset]
        responses[first] = csv(
            header, base_rows(dataset) + rows_for(dataset, LIMIT - len(base_rows(dataset)))
        )
        assert_refused(*build_over(responses), sv.SilverDefect.DELIVERY_TRUNCATED)

    @pytest.mark.parametrize("dataset", ["tickers", "stocks", "actions"])
    def test_a_non_empty_later_page_is_unsupported_even_when_every_row_is_unique(
        self, dataset: str
    ) -> None:
        responses = responses_for_run(1)
        first, header, later = DATASETS[dataset]
        responses[first] = csv(
            header, base_rows(dataset) + rows_for(dataset, LIMIT - len(base_rows(dataset)))
        )
        responses[page(dataset, later[0])] = csv(header, rows_for(dataset, 5, start=LIMIT))
        assert_refused(*build_over(responses), sv.SilverDefect.PAGINATION_UNSUPPORTED)
        # And with a short first page: still unsupported -- rows beyond the first page
        # cannot be shown to be the rows the first page did not return.
        responses = responses_for_run(1)
        responses[page(dataset, later[-1])] = csv(header, rows_for(dataset, 3, start=LIMIT))
        assert_refused(*build_over(responses), sv.SilverDefect.PAGINATION_UNSUPPORTED)

    @pytest.mark.parametrize("dataset", ["tickers", "stocks", "actions"])
    def test_duplicated_and_overlapping_rows_across_pages_are_unsupported(
        self, dataset: str
    ) -> None:
        responses = responses_for_run(1)
        first, header, later = DATASETS[dataset]
        rows = base_rows(dataset)
        responses[first] = csv(header, rows)
        responses[page(dataset, later[0])] = csv(header, rows[:2])  # overlap with page one
        assert_refused(*build_over(responses), sv.SilverDefect.PAGINATION_UNSUPPORTED)

    @pytest.mark.parametrize("dataset", ["tickers", "stocks", "actions"])
    def test_a_full_first_page_of_repeated_rows_is_refused_before_deduplication(
        self, dataset: str
    ) -> None:
        responses = responses_for_run(1)
        first, header, _ = DATASETS[dataset]
        rows = base_rows(dataset)
        responses[first] = csv(header, (rows * (LIMIT // len(rows) + 1))[:LIMIT])
        report, scenario, store = build_over(responses)
        assert_refused(report, scenario, store, sv.SilverDefect.DELIVERY_TRUNCATED)
        # The parser retains every raw row, so the gate saw a full page.
        parsed = parse_payload(responses[first], dataset=SharadarDataset(dataset))
        assert parsed.row_count == LIMIT and parsed.duplicate_row_count > 0

    @pytest.mark.parametrize("dataset", ["tickers", "stocks", "actions"])
    def test_an_empty_first_page_followed_by_data_is_inconsistent(self, dataset: str) -> None:
        responses = responses_for_run(1)
        first, header, later = DATASETS[dataset]
        responses[first] = csv(header, [])
        responses[page(dataset, later[0])] = csv(header, base_rows(dataset))
        assert_refused(*build_over(responses), sv.SilverDefect.PAGINATION_INCONSISTENT)

    def test_an_empty_terminal_page_after_inconsistent_earlier_pages_does_not_rescue(self) -> None:
        responses = responses_for_run(1)
        responses[page("tickers", 0)] = csv(TICKERS_HEADER, [])
        responses[page("tickers", 10000)] = csv(TICKERS_HEADER, base_rows("tickers"))
        responses[page("tickers", 20000)] = csv(TICKERS_HEADER, [])
        responses[page("tickers", 30000)] = csv(TICKERS_HEADER, [])
        assert_refused(*build_over(responses), sv.SilverDefect.PAGINATION_INCONSISTENT)
        responses = responses_for_run(1)
        responses[page("tickers", 0)] = csv(TICKERS_HEADER, base_rows("tickers"))
        responses[page("tickers", 10000)] = csv(TICKERS_HEADER, rows_for("tickers", 2))
        responses[page("tickers", 20000)] = csv(TICKERS_HEADER, [])
        responses[page("tickers", 30000)] = csv(TICKERS_HEADER, [])
        assert_refused(*build_over(responses), sv.SilverDefect.PAGINATION_UNSUPPORTED)

    @pytest.mark.parametrize("dataset", ["tickers", "stocks", "actions"])
    def test_more_than_limit_rows_on_a_page_is_refused(self, dataset: str) -> None:
        responses = responses_for_run(1)
        first, header, _ = DATASETS[dataset]
        responses[first] = csv(header, rows_for(dataset, LIMIT + 1))
        # The accepted parser refuses a page over the vendor maximum before the gate sees it.
        report, scenario, store = build_over(responses)
        assert_refused(report, scenario, store, sv.SilverDefect.PAYLOAD_UNPARSEABLE)

    def test_a_page_over_its_own_requested_limit_is_refused_by_the_gate(self) -> None:
        """Below the parser ceiling but above the compiled limit: the gate's own rule."""
        first = AcquiredPage(
            run_id="r",
            ordinal=0,
            dataset="stocks",
            window="2026-09-02/2026-09-02",
            page_offset=0,
            page_limit=5,
            acquisition_mode="BACKFILL",
            retrieved_at=datetime(2026, 9, 5, tzinfo=UTC),
            payload=b"",
            payload_sha256="0" * 64,
            payload_bytes=0,
            record_sha256="0" * 64,
            run_started_at=datetime(2026, 9, 5, tzinfo=UTC),
            run_completed_at=datetime(2026, 9, 5, tzinfo=UTC),
        )
        parsed = parse_payload(
            csv(STOCKS_HEADER, rows_for("stocks", 6)), dataset=SharadarDataset.STOCKS
        )
        with pytest.raises(pg.PaginationError) as refused:
            pg.admit_pagination([(first, parsed)])
        assert refused.value.defect is pg.PaginationDefect.PAGE_OVER_LIMIT

    def test_offsets_outside_the_compiled_sequence_are_inconsistent(self) -> None:
        def acquired(offset: int, limit: int = 5) -> AcquiredPage:
            return AcquiredPage(
                run_id="r",
                ordinal=0,
                dataset="stocks",
                window="2026-09-02/2026-09-02",
                page_offset=offset,
                page_limit=limit,
                acquisition_mode="BACKFILL",
                retrieved_at=datetime(2026, 9, 5, tzinfo=UTC),
                payload=b"",
                payload_sha256="0" * 64,
                payload_bytes=0,
                record_sha256="0" * 64,
                run_started_at=datetime(2026, 9, 5, tzinfo=UTC),
                run_completed_at=datetime(2026, 9, 5, tzinfo=UTC),
            )

        empty = parse_payload(csv(STOCKS_HEADER, []), dataset=SharadarDataset.STOCKS)
        short = parse_payload(
            csv(STOCKS_HEADER, rows_for("stocks", 2)), dataset=SharadarDataset.STOCKS
        )
        for pages in (
            [(acquired(5), short)],  # no offset-zero page
            [(acquired(0), short), (acquired(7), empty)],  # gap
            [(acquired(0), short), (acquired(5, limit=6), empty)],  # limit changes
        ):
            with pytest.raises(pg.PaginationError) as refused:
                pg.admit_pagination(pages)
            assert refused.value.defect is pg.PaginationDefect.PAGINATION_INCONSISTENT
        summary = pg.admit_pagination([(acquired(0), short), (acquired(5), empty)])
        assert summary.groups_admitted == {"stocks": 1} and summary.groups_empty == {"stocks": 0}

    def test_the_gate_vocabulary_maps_totally_onto_silver(self) -> None:
        assert set(sv._PAGINATION_DEFECTS) == set(pg.PaginationDefect)
        assert len({member.value for member in sv._PAGINATION_DEFECTS.values()}) == len(
            pg.PaginationDefect
        )


# ---------------------------------------------------------------------------
# Coordinates and groups
# ---------------------------------------------------------------------------


class TestCoordinatesAndGroups:
    @pytest.mark.parametrize(
        "mutate",
        [
            lambda entries: entries.pop(3),  # missing ordinal
            lambda entries: entries.append(dict(entries[2])),  # duplicated coordinates
            lambda entries: entries[2]["request"].__setitem__(
                "page_offset", 5000
            ),  # altered offset
            lambda entries: entries[2]["request"].__setitem__("page_limit", 5000),  # altered limit
        ],
    )
    def test_missing_duplicate_or_altered_coordinates_refuse_at_the_locator(
        self, mutate: Any
    ) -> None:
        store = FakeS3Store()
        acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT)
        key = f"bronze/sharadar/_indexes/{RUN_1}.json"
        document = json.loads(store.objects[key])
        mutate(document["entries"])
        store.objects[key] = json.dumps(document).encode()
        scenario = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),))
        report = scenario.run()
        assert report.status is bp.BuildStatus.REFUSED_INPUTS
        assert report.defect == "LOCATOR_INVALID"
        assert scenario.data_plane_calls() == (1, 0)

    def test_groups_never_borrow_empty_pages_or_counts_across_runs_or_windows(self) -> None:
        """Run 2 covers 09-02..09-14; a data-bearing later page in run 2's 09-03 window is
        refused although run 1's 09-03 window and every other window are clean."""
        store = FakeS3Store()
        acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT)
        r2 = responses_for_run(2)
        r2[("stocks", "2026-09-03/2026-09-03", 10000)] = csv(
            STOCKS_HEADER, rows_for("stocks", 1, start=LIMIT)
        )
        acquire(store, run_id=RUN_2, run=2, at=RUN_2_AT, responses=r2)
        scenario = BuildScenario(store)
        report = scenario.run()
        assert_refused(report, scenario, store, sv.SilverDefect.PAGINATION_UNSUPPORTED)
        # The same store with run 2's clean delivery builds; the reads are all of both runs.
        clean = FakeS3Store()
        acquire(clean, run_id=RUN_1, run=1, at=RUN_1_AT)
        acquire(clean, run_id=RUN_2, run=2, at=RUN_2_AT)
        ok = BuildScenario(clean)
        assert ok.run().status is bp.BuildStatus.COMPLETED
        assert ok.data_plane_calls() == (98, 8)

    def test_one_invalid_group_among_valid_groups_refuses_the_whole_build_with_zero_writes(
        self,
    ) -> None:
        responses = responses_for_run(1)
        responses[page("stocks", 10000)] = csv(STOCKS_HEADER, rows_for("stocks", 1, start=LIMIT))
        report, scenario, store = build_over(responses)
        assert_refused(report, scenario, store, sv.SilverDefect.PAGINATION_UNSUPPORTED)
        # Every object was read (the refusal comes after integrity and parsing), nothing written.
        assert scenario.data_plane_calls() == (1 + 2 * 16, 0)
        assert report.counts.s3_operations == 33

    def test_the_gate_runs_after_parsing_and_before_consolidation(self) -> None:
        """A run that would refuse on same-run conflict and on pagination refuses on
        pagination first: the gate sits before revision consolidation."""
        responses = responses_for_run(1)
        rows = stocks_rows(date(2026, 9, 1), run=1)
        conflicting = (*rows[0][:5], "99.99", *rows[0][6:])
        responses[("stocks", "2026-09-01/2026-09-01", 0)] = csv(STOCKS_HEADER, [*rows, conflicting])
        responses[page("stocks", 10000)] = csv(STOCKS_HEADER, rows_for("stocks", 1, start=LIMIT))
        report, scenario, store = build_over(responses)
        assert_refused(report, scenario, store, sv.SilverDefect.PAGINATION_UNSUPPORTED)


# ---------------------------------------------------------------------------
# Through the merged provider adapter
# ---------------------------------------------------------------------------


class TestThroughTheProviderAdapter:
    def test_a_supported_delivery_through_the_adapter_publishes(self) -> None:
        store = FakeS3Store()
        transport = CoordinateTransport(responses=responses_for_run(1))
        provider = SharadarProductionProvider(transport=transport)
        acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT, provider=provider)
        assert provider.transport_invocations == transport.call_count == 16
        scenario = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),))
        report = scenario.run()
        assert report.status is bp.BuildStatus.COMPLETED, report.defect
        assert scenario.data_plane_calls() == (33, 8)

    @pytest.mark.parametrize("dataset", ["tickers", "stocks", "actions"])
    def test_a_data_bearing_later_page_through_the_adapter_is_refused_at_the_build(
        self, dataset: str
    ) -> None:
        responses = responses_for_run(1)
        _, header, later = DATASETS[dataset]
        responses[page(dataset, later[0])] = csv(header, rows_for(dataset, 4, start=LIMIT))
        store = FakeS3Store()
        transport = CoordinateTransport(responses=responses)
        provider = SharadarProductionProvider(transport=transport)
        acquisition = acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT, provider=provider)
        # The acquisition is COMPLETE -- every page was delivered and written -- and that is
        # exactly what does not establish the delivery's semantic completeness.
        assert acquisition.status.value == "COMPLETED" and transport.call_count == 16
        document = json.loads(store.objects[f"bronze/sharadar/_indexes/{RUN_1}.json"])
        assert document["completeness"] == "COMPLETE"
        scenario = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),))
        report = scenario.run()
        assert_refused(report, scenario, store, sv.SilverDefect.PAGINATION_UNSUPPORTED)
        assert scenario.data_plane_calls() == (33, 0)

    def test_an_as_of_before_the_run_still_refuses_an_unsupported_delivery(self) -> None:
        """Pagination is admitted before any availability or as_of filtering."""
        responses = responses_for_run(1)
        responses[page("actions", 10000)] = csv(ACTIONS_HEADER, rows_for("actions", 1, start=LIMIT))
        store = FakeS3Store()
        acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT, responses=responses)
        scenario = BuildScenario(
            store,
            runs=((RUN_1, 1, RUN_1_AT),),
            config=configuration(as_of=datetime(2026, 9, 1, tzinfo=UTC)),
        )
        report = scenario.run()
        assert_refused(report, scenario, store, sv.SilverDefect.PAGINATION_UNSUPPORTED)

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
