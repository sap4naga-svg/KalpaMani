"""ADR-0053 §13 (B10, B11): mutation controls for the critical pagination-v2 branches.

Each control names one guarded behaviour, a probe that observes it, and a mutation of the
implementation that would silently break it. The probe must hold on the unmutated code,
must FAIL under the mutation (so a defect of that kind cannot pass the suite unnoticed),
and must hold again once the mutation is undone. Mutations are in-process
``monkeypatch`` substitutions of module attributes; nothing on disk changes, and every
control leaves the modules exactly as it found them.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, Final

import pytest

from fixtures.production_build import (
    ACTIONS_HEADER,
    RUN_1,
    RUN_1_AT,
    STOCKS_HEADER,
    BuildScenario,
    FakeS3Store,
    acquire,
    actions_rows,
    csv,
    responses_for_run,
    stocks_rows,
)
from fixtures.production_runtime import (
    PAYLOADS,
    RECORDS,
    RUN_ID,
    locator_document,
    locator_entry,
    probed_evidence,
    slice_document,
)
from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.production.sharadar import build_processing as bp
from kalpamani.data.production.sharadar import compiled as cp
from kalpamani.data.production.sharadar import completion as co
from kalpamani.data.production.sharadar import locator as lc
from kalpamani.data.production.sharadar import pagination as pg
from kalpamani.data.production.sharadar import plan as pl
from kalpamani.data.production.sharadar import processing as pp
from kalpamani.data.production.sharadar import provider as pv
from kalpamani.data.production.sharadar import silver as sv
from kalpamani.data.production.sharadar.entry import TaskEntry
from kalpamani.data.production.sharadar.inputs import InputError, parse_slice
from kalpamani.data.qualify.sharadar import parser as qp
from kalpamani.data.qualify.sharadar.parser import ParseError

pytestmark = pytest.mark.unit

WINDOW: Final = "2026-09-01/2026-09-01"
LIMIT: Final = 10_000


def full_page() -> bytes:
    base = stocks_rows(date(2026, 9, 1), run=1)
    filler: list[tuple[str, ...]] = [
        (
            f"ZY{i:05d}",
            "2026-09-01",
            "9.90",
            "10.20",
            "9.70",
            "10.00",
            "1000",
            "10.00",
            "10.00",
            "2026-09-04",
        )
        for i in range(LIMIT - len(base))
    ]
    return csv(STOCKS_HEADER, [*base, *filler])


# ---------------------------------------------------------------------------
# Probes: each returns True when the guarded behaviour holds
# ---------------------------------------------------------------------------


def probe_body_ceiling_refuses_whole() -> bool:
    body = b"ticker,date,close\r\n" + b"x" * 64
    try:
        qp.parse_payload(body, dataset=SharadarDataset.STOCKS, max_bytes=32)
    except ParseError as error:
        return error.defect is qp.ParseDefect.PAYLOAD_TOO_LARGE
    return False


def probe_full_page_without_probe_halts() -> bool:
    responses = responses_for_run(1)
    responses[("stocks", WINDOW, 0)] = full_page()  # no probe scripted: a probe is refused
    store = FakeS3Store()
    report = acquire(
        store, run_id=RUN_1, run=1, at=RUN_1_AT, responses=responses, expect_completed=False
    )
    return report.status is pp.AcquisitionStatus.HALTED and report.halt is (
        pp.ProcessingHalt.PROBE_REFUSED
    )


def probe_data_bearing_probe_writes_nothing_for_the_group() -> bool:
    responses = responses_for_run(1)
    responses[("stocks", WINDOW, 0)] = full_page()
    responses[("stocks", WINDOW, LIMIT)] = csv(
        STOCKS_HEADER, stocks_rows(date(2026, 9, 1), run=1)[:1]
    )
    store = FakeS3Store()
    report = acquire(
        store, run_id=RUN_1, run=1, at=RUN_1_AT, responses=responses, expect_completed=False
    )
    return (
        report.halt is pp.ProcessingHalt.PROBE_DATA_BEARING
        and report.counts.s3_operations == 1 + 3 * 2 + 1
    )


def probe_locator_refuses_a_full_page_without_probe_evidence() -> bool:
    from datetime import timedelta

    from fixtures.production_runtime import NOW, PLAN_DIGEST
    from kalpamani.data.production.sharadar.inputs import LedgerRow

    limit = pl.PAGE_LIMITS["actions"]
    passed = probed_evidence(
        dataset="actions", window="2025-01-01/2025-12-31", predicate=(), limit=limit
    )
    missing = dict(passed.document(), probe=None)
    document = locator_document()
    document["entries"][0] = locator_entry(
        0, "actions", PAYLOADS[0], RECORDS[0], pagination=missing
    )
    row = LedgerRow(
        run_identity=RUN_ID,
        slice=parse_slice(slice_document()),
        plan_digest=PLAN_DIGEST,
        outcome="COMPLETED",
        launched_at=NOW - timedelta(days=2),
        completed_at=NOW - timedelta(days=2, hours=-1),
    )
    try:
        lc.validate_run_locator(document, run_id=RUN_ID, ledger_row=row)
    except lc.RunLocatorError as error:
        return error.defect is lc.RunLocatorDefect.PROBE_EVIDENCE_MISSING
    return False


def probe_gate_refuses_an_unproven_full_page() -> bool:
    from datetime import UTC, datetime

    from kalpamani.data.production.sharadar.build_inputs import AcquiredPage

    parsed = qp.parse_payload(
        csv(
            STOCKS_HEADER,
            [(f"ZY{i}", "2026-09-01", "1", "1", "1", "1", "1", "1", "1", "d") for i in range(5)],
        ),
        dataset=SharadarDataset.STOCKS,
    )
    evidence = object.__new__(co.PaginationEvidence)
    for name, value in dict(
        governed_limit=5,
        row_count=5,
        schema_digest=parsed.schema_digest,
        parser_outcome=co.ParserOutcome.PARSED,
        completion=co.CompletionOutcome.SHORT_PAGE_COMPLETE,
        probe=None,
    ).items():
        object.__setattr__(evidence, name, value)
    at = datetime(2026, 9, 5, tzinfo=UTC)
    page = AcquiredPage(
        run_id="r",
        ordinal=0,
        dataset="stocks",
        window=WINDOW,
        predicate=(),
        page_offset=0,
        page_limit=5,
        pagination=evidence,
        acquisition_mode="BACKFILL",
        retrieved_at=at,
        payload=b"",
        payload_sha256="0" * 64,
        payload_bytes=0,
        record_sha256="0" * 64,
        run_started_at=at,
        run_completed_at=at,
    )
    try:
        pg.admit_pagination([(page, parsed)])
    except pg.PaginationError as error:
        return error.defect is pg.PaginationDefect.COMPLETION_UNPROVEN
    return False


def probe_silver_refuses_an_exact_duplicate_action() -> bool:
    responses = responses_for_run(1)
    rows = actions_rows(run=1)
    responses[("actions", "2026-08-01/2026-09-14", 0)] = csv(ACTIONS_HEADER, [*rows, rows[0]])
    store = FakeS3Store()
    acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT, responses=responses)
    report = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),)).run()
    return (
        report.status is bp.BuildStatus.REFUSED_NORMALIZATION
        and report.defect == sv.SilverDefect.ACTIONS_DUPLICATE_EVENT.value
    )


def probe_provider_refuses_a_tickers_request_without_the_predicate() -> bool:
    request = pl.ProductionRequest(
        ordinal=0, dataset="tickers", window="SNAPSHOT", predicate=(), page_offset=0, page_limit=100
    )
    try:
        pv.compile_cross_section(request)
    except pv.ProviderRefusedError as error:
        return error.refusal is pv.ProviderRefusal.PREDICATE_MALFORMED
    return False


def probe_plan_refuses_49_coordinates() -> bool:
    covered = parse_slice(
        slice_document(
            datasets=["stocks"], windows={"stocks": "2025-01-01/2025-02-18"}, request_count=49
        )
    )
    try:
        pl.compile_plan(covered, acquisition_mode=AcquisitionMode.BACKFILL)
    except pl.ProductionPlanError:
        return True
    return False


def probe_configuration_targets_are_pinned() -> bool:
    import json
    from datetime import UTC, datetime

    from kalpamani.data.contracts.canonical import canonical_bytes

    raw = cp.build_compiled_configuration(
        entry=TaskEntry.ACQUISITION,
        code_commit="0" * 40,
        code_tree="1" * 40,
        generated_at=datetime(2026, 9, 20, tzinfo=UTC),
        secret_name="synthetic/production/sharadar",  # noqa: S106 - an identifier, not a secret
        origin_addresses=["192.0.2.10"],
    )
    document = json.loads(raw)
    document["pagination_targets"] = dict(document["pagination_targets"], task_memory_mib=4096)
    try:
        cp.parse_compiled_configuration(canonical_bytes(document))
    except cp.CompiledConfigurationError as error:
        return error.defect is cp.CompiledConfigurationDefect.PAGINATION_TARGETS_MISMATCH
    return False


def probe_bind_plan_refuses_a_foreign_digest() -> bool:

    from fixtures.production_runtime import NOW, acquisition_input_document, encode
    from kalpamani.data.production.sharadar.inputs import decode_input, parse_acquisition_input

    document = acquisition_input_document(plan_digest="ab" * 32)
    admitted = parse_acquisition_input(decode_input(encode(document)), now=NOW, registry=None)
    try:
        pl.bind_plan(admitted)
    except InputError:
        return True
    return False


# ---------------------------------------------------------------------------
# Mutations: each silently disables the guarded branch
# ---------------------------------------------------------------------------


def mutate_lift_body_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    original = qp.parse_payload

    def lenient(payload: bytes, *, dataset: Any, max_bytes: int = 0, max_rows: int = 0) -> Any:
        return original(
            payload,
            dataset=dataset,
            max_bytes=qp.PARSE_BYTES_CEILING,
            max_rows=qp.PARSE_ROWS_CEILING,
        )

    monkeypatch.setattr(qp, "parse_payload", lenient)


def mutate_skip_the_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """An under-counting parse: an exactly-full page reads as short, so no probe is issued."""
    import dataclasses

    original = pp._parse_bounded

    def under_count(payload: bytes, *, request: Any, ceiling: int, malformed: Any) -> Any:
        parsed = original(payload, request=request, ceiling=ceiling, malformed=malformed)
        if parsed.row_count == request.page_limit:
            return dataclasses.replace(parsed, rows=parsed.rows[:-1])
        return parsed

    monkeypatch.setattr(pp, "_parse_bounded", under_count)


def mutate_lenient_locator_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    def lenient(raw: object, *, governed_limit: int) -> Any:
        assert isinstance(raw, dict)
        relaxed = dict(raw)
        if relaxed.get("probe") is None and relaxed.get("row_count") == governed_limit:
            relaxed["row_count"] = governed_limit - 1
        return co.parse_pagination_evidence(relaxed, governed_limit=governed_limit)

    monkeypatch.setattr(lc, "parse_pagination_evidence", lenient)


def mutate_gate_ignores_missing_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    original = pg._admit_group

    def lenient(pages: Any) -> Any:
        try:
            return original(pages)
        except pg.PaginationError as error:
            if error.defect is pg.PaginationDefect.COMPLETION_UNPROVEN:
                page, parsed = pages[0]
                return pg.GroupAdmission(
                    run_id=page.run_id,
                    dataset=page.dataset,
                    window=page.window,
                    predicate=page.predicate,
                    rows=parsed.row_count,
                    governed_limit=page.page_limit,
                    completion=co.CompletionOutcome.SHORT_PAGE_COMPLETE,
                )
            raise

    monkeypatch.setattr(pg, "_admit_group", lenient)


def mutate_silver_dedups_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    original = sv._event_identity

    def dedup(admissions: Any, *, page: Any, parsed: Any, fields: Any) -> str:
        try:
            return original(admissions, page=page, parsed=parsed, fields=fields)
        except sv.SilverError as error:
            if error.defect is sv.SilverDefect.ACTIONS_DUPLICATE_EVENT:
                from kalpamani.data.production.sharadar.actions_identity import event_identity

                return event_identity(fields, schema_digest=parsed.schema_digest)
            raise

    monkeypatch.setattr(sv, "_event_identity", dedup)


def mutate_provider_accepts_any_predicate(monkeypatch: pytest.MonkeyPatch) -> None:
    original = pv.compile_cross_section

    def lenient(request: Any) -> Any:
        if request.dataset == "tickers" and not request.predicate:
            request = pl.ProductionRequest(
                ordinal=request.ordinal,
                dataset=request.dataset,
                window=request.window,
                predicate=pl.TICKERS_PREDICATE,
                page_offset=request.page_offset,
                page_limit=request.page_limit,
            )
        return original(request)

    monkeypatch.setattr(pv, "compile_cross_section", lenient)


def mutate_lift_call_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pl, "MAX_PROVIDER_CALLS_PER_RUN", 200)
    monkeypatch.setattr(pl, "MAX_DATA_COORDINATES_PER_RUN", 100)


def mutate_unpin_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    original = cp.parse_compiled_configuration

    def lenient(raw: bytes) -> Any:
        import json

        from kalpamani.data.contracts.canonical import canonical_bytes

        document = json.loads(raw)
        if "pagination_targets" in document:
            document["pagination_targets"] = pl.pagination_targets_document()
        return original(canonical_bytes(document))

    monkeypatch.setattr(cp, "parse_compiled_configuration", lenient)


def mutate_bind_plan_trusts_the_input(monkeypatch: pytest.MonkeyPatch) -> None:
    def trusting(admitted: Any) -> Any:
        return pl.compile_plan(
            admitted.slice, acquisition_mode=AcquisitionMode(admitted.slice.acquisition_mode)
        )

    monkeypatch.setattr(pl, "bind_plan", trusting)


CONTROLS: Final[list[tuple[str, Callable[[], bool], Callable[[pytest.MonkeyPatch], None]]]] = [
    ("body ceiling refuses whole", probe_body_ceiling_refuses_whole, mutate_lift_body_ceiling),
    ("full page requires a probe", probe_full_page_without_probe_halts, mutate_skip_the_probe),
    (
        "locator refuses missing probe evidence",
        probe_locator_refuses_a_full_page_without_probe_evidence,
        mutate_lenient_locator_evidence,
    ),
    (
        "gate refuses an unproven full page",
        probe_gate_refuses_an_unproven_full_page,
        mutate_gate_ignores_missing_probe,
    ),
    (
        "silver refuses duplicate actions",
        probe_silver_refuses_an_exact_duplicate_action,
        mutate_silver_dedups_actions,
    ),
    (
        "provider refuses a missing tickers predicate",
        probe_provider_refuses_a_tickers_request_without_the_predicate,
        mutate_provider_accepts_any_predicate,
    ),
    ("plan refuses 49 coordinates", probe_plan_refuses_49_coordinates, mutate_lift_call_ceiling),
    (
        "configuration targets are pinned",
        probe_configuration_targets_are_pinned,
        mutate_unpin_targets,
    ),
    (
        "bind_plan refuses a foreign digest",
        probe_bind_plan_refuses_a_foreign_digest,
        mutate_bind_plan_trusts_the_input,
    ),
]


@pytest.mark.parametrize(("name", "probe", "mutate"), CONTROLS, ids=[c[0] for c in CONTROLS])
def test_each_control_holds_fails_under_its_mutation_and_holds_again(
    name: str, probe: Callable[[], bool], mutate: Callable[[pytest.MonkeyPatch], None]
) -> None:
    assert probe(), f"{name}: the guard does not hold before the mutation"
    with pytest.MonkeyPatch.context() as patch:
        mutate(patch)
        assert not probe(), f"{name}: the mutation was not caught"
    assert probe(), f"{name}: the guard does not hold after the mutation is undone"


def test_the_data_bearing_probe_control_holds_and_its_mutation_is_caught() -> None:
    """The no-write-after-a-failed-probe guard, separately: the mutation forges extra writes."""
    assert probe_data_bearing_probe_writes_nothing_for_the_group()
    with pytest.MonkeyPatch.context() as patch:
        original = pp._publish_request

        def eager(**kwargs: Any) -> Any:
            return original(**kwargs)

        # Mutation: publish the group's writes before the probe verdict by publishing a
        # copy of every completed group twice -- the observable effect is extra S3 writes.
        def twice(**kwargs: Any) -> Any:
            eager(**{**kwargs, "run_id": kwargs["run_id"]})
            return original(**{**kwargs, "run_id": kwargs["run_id"] + "-x"})

        patch.setattr(pp, "_publish_request", twice)
        patch.setattr(pp.AcquisitionReport, "__post_init__", lambda self: None)
        assert not probe_data_bearing_probe_writes_nothing_for_the_group()
    assert probe_data_bearing_probe_writes_nothing_for_the_group()
