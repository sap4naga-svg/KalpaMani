"""ADR-0053 §13 (B9): the accepted planner recompiles run 1' and the O-5 program from fixtures.

Every figure here is read from the compiled plans and programs; none is typed in as an
expectation without being derived by the planner itself. Where the derived result differs
from the indicative arithmetic ADR-0053 §13.4 marked CALCULATED, the derived result is
what these tests pin -- and the difference is stated in the test that pins it.
"""

from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise
from typing import Final

import pytest

from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.production.sharadar import plan as pl
from kalpamani.data.production.sharadar import program as pg
from kalpamani.data.production.sharadar.completion import PROBE_POLICY
from kalpamani.data.production.sharadar.inputs import parse_slice

pytestmark = pytest.mark.unit

#: The O-8 window and the replacement first run's own coverage (ADR-0053 §13.4, D-21 §6).
WINDOW_START: Final = date(2024, 6, 3)
WINDOW_END: Final = date(2026, 9, 14)
RUN_1_STOCKS_START: Final = date(2026, 8, 2)
RUN_1_ACTIONS_START: Final = date(2024, 9, 15)
CEILING: Final = 32 * 1024 * 1024


def run_1_slice() -> dict[str, object]:
    return {
        "acquisition_mode": "BACKFILL",
        "datasets": ["actions", "stocks", "tickers"],
        "windows": {
            "actions": f"{RUN_1_ACTIONS_START.isoformat()}/{WINDOW_END.isoformat()}",
            "stocks": f"{RUN_1_STOCKS_START.isoformat()}/{WINDOW_END.isoformat()}",
            "tickers": "SNAPSHOT",
        },
        "request_count": 47,
        "max_response_bytes": CEILING,
    }


def spec(**overrides: object) -> pg.ProgramSpec:
    fields: dict[str, object] = {
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "first_run_stocks_start": RUN_1_STOCKS_START,
        "first_run_actions_start": RUN_1_ACTIONS_START,
        "acquisition_mode": AcquisitionMode.BACKFILL,
    }
    fields.update(overrides)
    return pg.ProgramSpec(**fields)  # type: ignore[arg-type]


class TestReplacementRun1:
    def test_run_1_prime_compiles_to_47_data_coordinates_143_writes_and_94_worst_case_calls(
        self,
    ) -> None:
        plan = pl.compile_plan(
            parse_slice(run_1_slice()), acquisition_mode=AcquisitionMode.BACKFILL
        )
        assert plan.data_coordinates == 47 == plan.request_count
        assert plan.expected_writes == 1 + 3 * 47 + 1 == 143
        assert plan.max_provider_calls == 94 <= pl.MAX_PROVIDER_CALLS_PER_RUN
        by_dataset = {
            dataset: [r for r in plan.requests if r.dataset == dataset]
            for dataset in ("stocks", "tickers", "actions")
        }
        assert len(by_dataset["stocks"]) == 44 and len(by_dataset["tickers"]) == 1
        assert [r.window for r in by_dataset["actions"]] == [
            "2024-09-15/2025-09-15",
            "2025-09-16/2026-09-14",
        ]
        assert all(r.page_offset == 0 for r in plan.requests)
        assert {r.page_limit for r in by_dataset["stocks"]} == {10000}
        assert {r.page_limit for r in by_dataset["tickers"] + by_dataset["actions"]} == {100000}
        assert by_dataset["tickers"][0].predicate == (("table", "stocks"),)
        assert plan.probe_policy == PROBE_POLICY and plan.max_response_bytes == CEILING

    def test_the_plan_digest_is_deterministic_and_moves_with_every_coordinate_and_ceiling(
        self,
    ) -> None:
        base = pl.plan_digest_for(
            parse_slice(run_1_slice()), acquisition_mode=AcquisitionMode.BACKFILL
        )
        assert base == pl.plan_digest_for(
            parse_slice(run_1_slice()), acquisition_mode=AcquisitionMode.BACKFILL
        )
        moved = dict(run_1_slice())
        moved["max_response_bytes"] = CEILING // 2
        assert (
            pl.plan_digest_for(parse_slice(moved), acquisition_mode=AcquisitionMode.BACKFILL)
            != base
        )
        assert (
            pl.plan_digest_for(parse_slice(run_1_slice()), acquisition_mode=AcquisitionMode.UPDATE)
            != base
        )


class TestTheProgram:
    def test_the_derived_o5_program_is_18_runs_855_coordinates_2601_writes(self) -> None:
        """The derived result. ADR-0053 §13.4's indicative 10 / 847 / 2,561 assumed 96 data
        coordinates per run; the accepted per-run ceiling of 96 binds the WORST-CASE provider
        calls (one conditional probe per coordinate), so a run plans at most 48 groups and the
        program is longer. This is the planner's figure, and it supersedes the indicative one."""
        program = pg.compile_program(spec())
        assert program.run_count == 18
        assert program.total_data_coordinates == 855
        assert program.total_expected_writes == 2601
        assert [run.data_coordinates for run in program.runs] == [47, *([48] * 16), 40]
        assert program.max_provider_calls_per_run == 96 == pl.MAX_PROVIDER_CALLS_PER_RUN
        assert program.total_max_provider_calls == 2 * 855
        assert all(run.expected_writes == 2 + 3 * run.data_coordinates for run in program.runs)
        assert program.runs[0].plan.digest == pl.plan_digest_for(
            parse_slice(run_1_slice()), acquisition_mode=AcquisitionMode.BACKFILL
        )
        document = program.document()
        assert document["run_count"] == 18 and document["total_expected_writes"] == 2601
        assert document["contract_id"] == pg.PROGRAM_CONTRACT_ID

    def test_every_run_carries_one_tickers_snapshot_and_stocks_days_partition_the_window(
        self,
    ) -> None:
        program = pg.compile_program(spec())
        days: list[date] = []
        for run in program.runs:
            snapshots = [r for r in run.plan.requests if r.dataset == "tickers"]
            assert len(snapshots) == 1 and snapshots[0].predicate == (("table", "stocks"),)
            for request in run.plan.requests:
                if request.dataset == "stocks":
                    start, end = request.window.split("/")
                    assert start == end
                    days.append(date.fromisoformat(start))
        total = (WINDOW_END - WINDOW_START).days + 1
        assert len(days) == total == len(set(days)) == 834
        assert sorted(days) == [WINDOW_START + timedelta(days=i) for i in range(total)]

    def test_actions_windows_are_contiguous_and_cover_the_window_exactly_once(self) -> None:
        program = pg.compile_program(spec())
        windows = sorted(
            tuple(date.fromisoformat(part) for part in r.window.split("/"))
            for run in program.runs
            for r in run.plan.requests
            if r.dataset == "actions"
        )
        assert windows[0][0] == WINDOW_START and windows[-1][1] == WINDOW_END
        for (_, previous_end), (next_start, _) in pairwise(windows):
            assert next_start == previous_end + timedelta(days=1)
        assert windows == [
            (date(2024, 6, 3), date(2024, 9, 14)),
            (date(2024, 9, 15), date(2025, 9, 15)),
            (date(2025, 9, 16), date(2026, 9, 14)),
        ]
        # The residual window rides on the last run, with the earliest stocks days.
        last = program.runs[-1]
        assert {r.dataset for r in last.plan.requests} == {"actions", "stocks", "tickers"}
        assert last.slice.canonical()["windows"]["stocks"] == "2024-06-03/2024-07-10"

    def test_no_run_plans_a_second_page_and_no_run_exceeds_a_bound(self) -> None:
        program = pg.compile_program(spec())
        for run in program.runs:
            assert all(r.page_offset == 0 for r in run.plan.requests)
            assert run.data_coordinates <= pl.MAX_DATA_COORDINATES_PER_RUN
            assert run.max_provider_calls <= pl.MAX_PROVIDER_CALLS_PER_RUN
            assert run.expected_writes == run.plan.expected_writes
        pg.verify_program(program)

    def test_the_program_digest_is_deterministic_and_the_document_carries_no_secret(self) -> None:
        first, second = pg.compile_program(spec()), pg.compile_program(spec())
        assert first.digest == second.digest
        assert (
            first.digest != pg.compile_program(spec(acquisition_mode=AcquisitionMode.UPDATE)).digest
        )
        rendered = repr(first) + repr(first.runs[0])
        assert first.digest not in rendered

    @pytest.mark.parametrize(
        ("stocks_start", "expected_first"),
        [
            (date(2026, 9, 14), 1 + 1 + 2),  # one session day in run 1'
            (date(2026, 8, 1), 45 + 1 + 2),  # 45 days: exactly 48 coordinates, 96 calls
        ],
        ids=["one-day", "max-fitting"],
    )
    def test_max_bound_and_exact_full_run_variants(
        self, stocks_start: date, expected_first: int
    ) -> None:
        program = pg.compile_program(spec(first_run_stocks_start=stocks_start))
        assert program.runs[0].data_coordinates == expected_first
        assert program.runs[0].max_provider_calls <= 96

    def test_an_over_limit_first_run_is_refused_never_trimmed(self) -> None:
        # 46 stocks days + 1 tickers + 2 actions = 49 coordinates: 98 worst-case calls.
        with pytest.raises(pg.ProgramPlanError):
            pg.compile_program(spec(first_run_stocks_start=date(2026, 7, 31)))

    def test_a_specification_outside_its_window_is_refused(self) -> None:
        with pytest.raises(pg.ProgramPlanError):
            spec(first_run_stocks_start=date(2026, 9, 15))
        with pytest.raises(pg.ProgramPlanError):
            spec(first_run_actions_start=date(2024, 6, 2))
        with pytest.raises(pg.ProgramPlanError):
            spec(acquisition_mode=AcquisitionMode.QUALIFICATION)

    def test_a_forged_program_is_refused_by_verification(self) -> None:
        program = pg.compile_program(spec())
        forged = pg.CompiledProgram(
            contract_id=program.contract_id,
            spec=program.spec,
            runs=program.runs[1:],
            digest=program.digest,
        )
        with pytest.raises(pg.ProgramPlanError):
            pg.verify_program(forged)
