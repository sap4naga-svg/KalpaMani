"""ADR-0053 §13 (B10): the pagination-v2 regression list, on synthetic inputs only.

Every case names the accepted rule it holds. No provider, AWS or credential is touched:
the acquisition path runs over the fixtures' fakes, the parser over synthetic bytes.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import pytest

from fixtures.production_build import (
    RUN_1,
    RUN_1_AT,
    STOCKS_HEADER,
    BuildScenario,
    FakeS3Store,
    acquire,
    csv,
    responses_for_run,
    stocks_rows,
)
from fixtures.production_runtime import (
    NOW,
    PAYLOADS,
    PLAN_DIGEST,
    RECORDS,
    RUN_ID,
    locator_document,
    locator_entry,
    probed_evidence,
    short_page_evidence,
    slice_document,
)
from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.production.sharadar import build_processing as bp
from kalpamani.data.production.sharadar import plan as pl
from kalpamani.data.production.sharadar import processing as pp
from kalpamani.data.production.sharadar import silver as sv
from kalpamani.data.production.sharadar.actions_identity import (
    ACCEPTED_ACTIONS_SCHEMA_DIGEST,
    ACTIONS_IDENTITY_CONTRACT_ID,
    ACTIONS_IDENTITY_FIELDS,
    ActionsIdentityDefect,
    ActionsIdentityRefusalError,
    EventAdmission,
    admit_events,
    canonical_row,
    event_identity,
    normalize_field,
)
from kalpamani.data.production.sharadar.compiled import (
    build_compiled_configuration,
    parse_compiled_configuration,
)
from kalpamani.data.production.sharadar.completion import (
    CompletionDefect,
    CompletionError,
    CompletionOutcome,
    PaginationEvidence,
    ParserOutcome,
    parse_pagination_evidence,
)
from kalpamani.data.production.sharadar.entry import TaskEntry
from kalpamani.data.production.sharadar.inputs import (
    InputDefect,
    InputError,
    LedgerRow,
    decode_input,
    parse_acquisition_input,
    parse_slice,
)
from kalpamani.data.production.sharadar.locator import (
    RunLocatorDefect,
    RunLocatorError,
    validate_run_locator,
)
from kalpamani.data.qualify.sharadar.parser import (
    MAX_PARSE_BYTES,
    MAX_ROWS_PER_PAGE,
    PARSE_BYTES_CEILING,
    PARSE_ROWS_CEILING,
    ParseDefect,
    ParseError,
    parse_payload,
    schema_digest_of,
)
from kalpamani.data.qualify.sharadar.read import (
    MAX_READ_BYTES,
    MAX_READ_BYTES_CEILING,
    ExactObjectReference,
    LicensedObjectReader,
    LicensedReadError,
    ReadFailure,
)

pytestmark = pytest.mark.unit

WINDOW: Final = "2026-09-01/2026-09-01"
STOCKS_LIMIT: Final = 10_000


def full_stocks_page() -> bytes:
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
        for i in range(STOCKS_LIMIT - len(base))
    ]
    return csv(STOCKS_HEADER, [*base, *filler])


def _row() -> LedgerRow:
    return LedgerRow(
        run_identity=RUN_ID,
        slice=parse_slice(slice_document()),
        plan_digest=PLAN_DIGEST,
        outcome="COMPLETED",
        launched_at=NOW - timedelta(days=2),
        completed_at=NOW - timedelta(days=2, hours=-1),
    )


def _refused(document: dict[str, Any]) -> RunLocatorDefect:
    with pytest.raises(RunLocatorError) as info:
        validate_run_locator(document, run_id=RUN_ID, ledger_row=_row())
    return info.value.defect


# ---------------------------------------------------------------------------
# Ceilings: the whole body before admission, the governed row ceilings
# ---------------------------------------------------------------------------


class TestCeilings:
    def test_the_production_parse_ceilings_and_the_pinned_qualification_defaults(self) -> None:
        assert PARSE_BYTES_CEILING == 32 * 1024 * 1024 and PARSE_ROWS_CEILING == 100_000
        assert MAX_PARSE_BYTES == 4 * 1024 * 1024 and MAX_ROWS_PER_PAGE == 10_000
        assert pl.PAYLOAD_CEILING_BYTES == PARSE_BYTES_CEILING == MAX_READ_BYTES_CEILING
        assert pl.PAGE_LIMITS == {"tickers": 100_000, "actions": 100_000, "stocks": 10_000}
        assert pl.PROCESS_MEMORY_CEILING_BYTES == 1024 * 1024 * 1024
        assert pl.TASK_MEMORY_MIB == 2048 and pl.PROCESS_MEMORY_CEILING_BYTES < 2048 * 1024 * 1024
        # The qualification caller passes no ceiling and keeps its 4 MiB / 10,000 bounds.
        with pytest.raises(ParseError) as refused:
            parse_payload(b"x" * (MAX_PARSE_BYTES + 1), dataset=SharadarDataset.STOCKS)
        assert refused.value.defect is ParseDefect.PAYLOAD_TOO_LARGE
        for bad in ({"max_bytes": PARSE_BYTES_CEILING + 1}, {"max_rows": 0}, {"max_rows": 100_001}):
            with pytest.raises(TypeError):
                parse_payload(b"ticker,date,close\r\n", dataset=SharadarDataset.STOCKS, **bad)

    def test_a_body_exactly_at_the_ceiling_is_admitted_and_one_byte_above_is_refused_whole(
        self,
    ) -> None:
        header = b"ticker,date,close\r\n"
        # Long rows (under the 4,096-character field ceiling) so the body reaches the byte
        # ceiling well inside the 100,000-row ceiling.
        row = b"ZZ,2026-09-01," + b"1" * 4000 + b"\r\n"
        count = (PARSE_BYTES_CEILING - len(header)) // len(row)
        body = header + row * count
        remainder = PARSE_BYTES_CEILING - len(body)
        if remainder:
            body += b"ZZ,2026-09-01," + b"1" * (remainder - len(b"ZZ,2026-09-01,\r\n")) + b"\r\n"
        assert len(body) == PARSE_BYTES_CEILING
        parsed = parse_payload(
            body,
            dataset=SharadarDataset.STOCKS,
            max_bytes=PARSE_BYTES_CEILING,
            max_rows=PARSE_ROWS_CEILING,
        )
        assert parsed.row_count > 0
        with pytest.raises(ParseError) as refused:
            parse_payload(
                body + b"x" * (PARSE_BYTES_CEILING - len(body) + 1),
                dataset=SharadarDataset.STOCKS,
                max_bytes=PARSE_BYTES_CEILING,
                max_rows=PARSE_ROWS_CEILING,
            )
        assert refused.value.defect is ParseDefect.PAYLOAD_TOO_LARGE

    def test_row_counts_at_and_above_the_governed_ceiling(self) -> None:
        at = csv(
            STOCKS_HEADER,
            [(f"Z{i}", "2026-09-01", "1", "1", "1", "1", "1", "1", "1", "d") for i in range(10)],
        )
        assert parse_payload(at, dataset=SharadarDataset.STOCKS, max_rows=10).row_count == 10
        with pytest.raises(ParseError) as refused:
            parse_payload(at, dataset=SharadarDataset.STOCKS, max_rows=9)
        assert refused.value.defect is ParseDefect.ROW_COUNT_EXCEEDED

    def test_the_reader_ceiling_is_bound_per_reader_under_the_hard_cap(self) -> None:
        class Client:
            def get_object(self, **kwargs: Any) -> Any:
                raise AssertionError("never reached")

            def put_object(self, **kwargs: Any) -> Any:
                raise AssertionError("never reached")

            def head_object(self, **kwargs: Any) -> Any:
                raise AssertionError("never reached")

        default = LicensedObjectReader(client=Client(), licensed_bucket="synthetic-bucket")
        wide = LicensedObjectReader(
            client=Client(), licensed_bucket="synthetic-bucket", read_ceiling=MAX_READ_BYTES_CEILING
        )
        big = ExactObjectReference(
            logical_key="licensed/bronze/x",
            expected_sha256="0" * 64,
            expected_bytes=MAX_READ_BYTES + 1,
        )
        with pytest.raises(LicensedReadError) as refused:
            default.read_exact(big)
        assert refused.value.failure is ReadFailure.TOO_LARGE
        with pytest.raises(LicensedReadError) as reached:  # admitted: the client is reached
            wide.read_exact(big)
        assert reached.value.failure is not ReadFailure.TOO_LARGE
        with pytest.raises(LicensedReadError):
            LicensedObjectReader(
                client=Client(),
                licensed_bucket="synthetic-bucket",
                read_ceiling=MAX_READ_BYTES_CEILING + 1,
            )


# ---------------------------------------------------------------------------
# The completion evidence contract and the locator's four probe outcomes
# ---------------------------------------------------------------------------


class TestCompletionEvidence:
    def test_the_state_machine_refuses_every_impossible_value(self) -> None:
        good = short_page_evidence(limit=5, rows=3)
        assert parse_pagination_evidence(good.document(), governed_limit=5) == good
        probed = probed_evidence(dataset="stocks", window=WINDOW, predicate=(), limit=5)
        assert parse_pagination_evidence(probed.document(), governed_limit=5) == probed
        cases: list[tuple[dict[str, Any], CompletionDefect]] = [
            ({"row_count": 6}, CompletionDefect.ROW_COUNT_OVER_LIMIT),
            ({"completion": "PROBE_PASSED"}, CompletionDefect.OUTCOME_INCONSISTENT),
            ({"probe": probed.document()["probe"]}, CompletionDefect.PROBE_UNEXPECTED),
            ({"contract_id": "other"}, CompletionDefect.CONTRACT_UNKNOWN),
            ({"governed_limit": 6}, CompletionDefect.LIMIT_MISMATCH),
        ]
        for override, defect in cases:
            document = dict(good.document(), **override)
            with pytest.raises(CompletionError) as refused:
                parse_pagination_evidence(document, governed_limit=5)
            assert refused.value.defect is defect, override
        full = dict(probed.document(), probe=None)
        with pytest.raises(CompletionError) as refused:
            parse_pagination_evidence(full, governed_limit=5)
        assert refused.value.defect is CompletionDefect.PROBE_EVIDENCE_MISSING
        for override in (
            {"row_count": 1},
            {"schema_digest": "ee" * 32},
            {"outcome": "PROBE_REFUSED"},
        ):
            document = dict(probed.document(), probe=dict(probed.document()["probe"], **override))
            with pytest.raises(CompletionError) as refused:
                parse_pagination_evidence(document, governed_limit=5)
            assert refused.value.defect is CompletionDefect.PROBE_FAILED, override
        with pytest.raises(CompletionError) as refused:
            parse_pagination_evidence({"contract_id": "x"}, governed_limit=5)
        assert refused.value.defect is CompletionDefect.EVIDENCE_MALFORMED
        with pytest.raises(CompletionError):
            PaginationEvidence(
                governed_limit=5,
                row_count=5,
                schema_digest="ab" * 32,
                parser_outcome=ParserOutcome.PARSED,
                completion=CompletionOutcome.PROBE_PASSED,
                probe=None,
            )

    def test_the_locator_distinguishes_not_required_passed_failed_and_missing(self) -> None:
        limit = pl.PAGE_LIMITS["actions"]
        # Not required: a short page (the fixture's default) is admitted.
        document = locator_document()
        validated = validate_run_locator(document, run_id=RUN_ID, ledger_row=_row())
        assert validated.entries[0].pagination.completion is CompletionOutcome.SHORT_PAGE_COMPLETE
        # Required and passed: a full actions page with a passed probe; the counts follow.
        passed = probed_evidence(
            dataset="actions", window="2025-01-01/2025-12-31", predicate=(), limit=limit
        )
        document = locator_document(probes_issued=1, provider_calls=3)
        document["entries"][0] = locator_entry(
            0, "actions", PAYLOADS[0], RECORDS[0], pagination=passed.document()
        )
        validated = validate_run_locator(document, run_id=RUN_ID, ledger_row=_row())
        assert validated.probes_issued == 1 and validated.provider_calls == 3
        assert validated.entries[0].pagination.completion is CompletionOutcome.PROBE_PASSED
        # Required and failed: a data-bearing probe recorded on the entry.
        failed = dict(passed.document())
        failed["probe"] = dict(failed["probe"], row_count=1, outcome="PROBE_DATA_BEARING")
        document = locator_document(probes_issued=1, provider_calls=3)
        document["entries"][0] = locator_entry(
            0, "actions", PAYLOADS[0], RECORDS[0], pagination=failed
        )
        assert _refused(document) is RunLocatorDefect.PROBE_FAILED
        # Required and missing: a full page with no probe evidence.
        missing = dict(passed.document(), probe=None)
        document = locator_document()
        document["entries"][0] = locator_entry(
            0, "actions", PAYLOADS[0], RECORDS[0], pagination=missing
        )
        assert _refused(document) is RunLocatorDefect.PROBE_EVIDENCE_MISSING
        # A probe on a short page, a row count over the limit, and inconsistent accounting.
        unexpected = dict(
            short_page_evidence(limit=limit, rows=3).document(), probe=passed.document()["probe"]
        )
        document = locator_document()
        document["entries"][0] = locator_entry(
            0, "actions", PAYLOADS[0], RECORDS[0], pagination=unexpected
        )
        assert _refused(document) is RunLocatorDefect.PROBE_UNEXPECTED
        over = dict(short_page_evidence(limit=limit, rows=3).document(), row_count=limit + 1)
        document = locator_document()
        document["entries"][0] = locator_entry(
            0, "actions", PAYLOADS[0], RECORDS[0], pagination=over
        )
        assert _refused(document) is RunLocatorDefect.ROW_COUNT_OVER_LIMIT
        assert (
            _refused(locator_document(probes_issued=1)) is RunLocatorDefect.PROBE_COUNT_INCONSISTENT
        )
        assert (
            _refused(locator_document(provider_calls=3))
            is RunLocatorDefect.PROBE_COUNT_INCONSISTENT
        )
        assert (
            _refused(locator_document(provider_calls=5))
            is RunLocatorDefect.PROVIDER_CALLS_OVER_CEILING
        )
        assert _refused(locator_document(max_provider_calls=6)) is RunLocatorDefect.FIELD_MALFORMED
        assert _refused(locator_document(expected_writes=9)) is RunLocatorDefect.FIELD_MALFORMED


# ---------------------------------------------------------------------------
# The actions identity, promoted (B7)
# ---------------------------------------------------------------------------


def action(**overrides: str | None) -> dict[str, str | None]:
    base: dict[str, str | None] = {
        "date": "2025-03-14",
        "action": "dividend",
        "ticker": "XYZ",
        "name": "Example Corp",
        "value": "0.25",
        "contraticker": None,
        "contraname": None,
    }
    base.update(overrides)
    return base


class TestActionsIdentity:
    def test_the_contract_id_the_fields_and_the_digest_are_the_accepted_ones(self) -> None:
        assert ACTIONS_IDENTITY_CONTRACT_ID == "sharadar-actions-event-identity/v1"
        assert ACTIONS_IDENTITY_FIELDS == (
            "date",
            "action",
            "ticker",
            "name",
            "value",
            "contraticker",
            "contraname",
        )
        assert schema_digest_of(ACTIONS_IDENTITY_FIELDS) == ACCEPTED_ACTIONS_SCHEMA_DIGEST
        assert sv.ACTIONS_IDENTITY_VERSION == ACTIONS_IDENTITY_CONTRACT_ID

    def test_canonical_bytes_bind_the_contract_the_schema_and_the_ordered_pairs(self) -> None:
        canonical = canonical_row(action(), schema_digest=ACCEPTED_ACTIONS_SCHEMA_DIGEST)
        assert canonical == (
            b'{"contract":"sharadar-actions-event-identity/v1","fields":[["date","2025-03-14"],'
            b'["action","dividend"],["ticker","XYZ"],["name","Example Corp"],["value","0.25"],'
            b'["contraticker",null],["contraname",null]],"schema":"'
            + ACCEPTED_ACTIONS_SCHEMA_DIGEST.encode()
            + b'"}'
        )
        identity = event_identity(action(), schema_digest=ACCEPTED_ACTIONS_SCHEMA_DIGEST)
        assert len(identity) == 64 and identity == event_identity(
            dict(reversed(list(action().items()))), schema_digest=ACCEPTED_ACTIONS_SCHEMA_DIGEST
        )

    def test_every_field_participates_and_normalization_is_typed(self) -> None:
        base = event_identity(action(), schema_digest=ACCEPTED_ACTIONS_SCHEMA_DIGEST)
        for name in ACTIONS_IDENTITY_FIELDS:
            changed = action(**{name: {"date": "2025-03-15", "value": "0.26"}.get(name, "other")})
            assert event_identity(changed, schema_digest=ACCEPTED_ACTIONS_SCHEMA_DIGEST) != base
        assert normalize_field("date", "2025-03-14") == "2025-03-14"
        assert normalize_field("value", "0.250") == "0.250"  # the exact literal, no rescaling
        assert normalize_field("name", " Example ") == " Example "  # no trimming
        assert normalize_field("contraname", None) is None
        for name, value, defect in (
            ("date", None, ActionsIdentityDefect.ACTIONS_REQUIRED_FIELD_NULL),
            ("date", "14/03/2025", ActionsIdentityDefect.ACTIONS_DATE_MALFORMED),
            ("value", "abc", ActionsIdentityDefect.ACTIONS_VALUE_NOT_DECIMAL),
        ):
            with pytest.raises(ActionsIdentityRefusalError) as refused:
                normalize_field(name, value)
            assert refused.value.defect is defect
        with pytest.raises(ActionsIdentityRefusalError) as refused:
            canonical_row(action(), schema_digest="ab" * 32)
        assert refused.value.defect is ActionsIdentityDefect.ACTIONS_SCHEMA_NOT_GOVERNED

    def test_same_coarse_key_distinct_rows_are_distinct_events_and_exact_duplicates_are_refused(
        self,
    ) -> None:
        admission = EventAdmission()
        first = admission.admit(action(), schema_digest=ACCEPTED_ACTIONS_SCHEMA_DIGEST)
        second = admission.admit(action(value="0.30"), schema_digest=ACCEPTED_ACTIONS_SCHEMA_DIGEST)
        assert first.identity != second.identity and admission.admitted_count == 2
        with pytest.raises(ActionsIdentityRefusalError) as refused:
            admission.admit(action(), schema_digest=ACCEPTED_ACTIONS_SCHEMA_DIGEST)
        assert refused.value.defect is ActionsIdentityDefect.ACTIONS_DUPLICATE_EVENT
        assert "Example" not in repr(first)

    def test_a_digest_collision_is_refused_never_merged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import hashlib

        admission = EventAdmission()
        admission.admit(action(), schema_digest=ACCEPTED_ACTIONS_SCHEMA_DIGEST)
        colliding = action(value="0.30")
        real = hashlib.sha256(
            canonical_row(action(), schema_digest=ACCEPTED_ACTIONS_SCHEMA_DIGEST)
        ).hexdigest()

        class Colliding:
            def __init__(self, data: bytes) -> None:
                self.data = data

            def hexdigest(self) -> str:
                return real

        monkeypatch.setattr(hashlib, "sha256", Colliding)
        with pytest.raises(ActionsIdentityRefusalError) as refused:
            admission.admit(colliding, schema_digest=ACCEPTED_ACTIONS_SCHEMA_DIGEST)
        assert refused.value.defect is ActionsIdentityDefect.ACTIONS_IDENTITY_COLLISION

    def test_admit_events_orders_by_canonical_bytes(self) -> None:
        events = admit_events(
            [action(value="0.30"), action()], schema_digest=ACCEPTED_ACTIONS_SCHEMA_DIGEST
        )
        assert [c for _, c in events] == sorted(c for _, c in events)


# ---------------------------------------------------------------------------
# Backward compatibility (B8): historical run 1 and the superseded run-2 specification
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_a_v1_locator_is_refused_as_superseded_never_reinterpreted(self) -> None:
        # The v1 shape historical run 1 published: two-to-four offset pages, no evidence.
        document = locator_document()
        document["schema_version"] = "kalpamani-production-run-locator/v1"
        for field in (
            "pagination_contract",
            "probe_policy",
            "probes_issued",
            "provider_calls",
            "max_provider_calls",
            "expected_writes",
        ):
            del document[field]
        for entry in document["entries"]:
            del entry["pagination"]
            del entry["request"]["predicate"]
        # The v1 field set is refused before the version is examined -- and the version
        # itself is refused as superseded when the shape happens to be v2's.
        assert _refused(document) is RunLocatorDefect.FIELD_MISSING
        assert (
            _refused(locator_document(schema_version="kalpamani-production-run-locator/v1"))
            is RunLocatorDefect.SCHEMA_VERSION_SUPERSEDED
        )
        assert (
            _refused(locator_document(schema_version="kalpamani-production-run-locator/v3"))
            is RunLocatorDefect.SCHEMA_VERSION_UNKNOWN
        )

    def test_a_v1_specification_is_refused_by_the_v2_planner(self) -> None:
        # A v1 slice asked for compiled pages (2 actions + 4 tickers = 6 requests) under the
        # v1 plan contract; under v2 the same coverage is 2 data coordinates, and a v1 digest
        # can never equal a v2 digest.
        v1_slice = slice_document(request_count=6)
        v1_digest = "21" * 32  # any digest computed under the v1 contract
        document = {
            "schema_version": 2,
            "contract_id": "kalpamani-production-acquisition-input/v2",
            "run_identity": RUN_ID,
            "slice": v1_slice,
            "plan_digest": v1_digest,
            "spent_identities": {"spent": [], "spent_digest": _spent_digest()},
            "issued_at": (NOW - timedelta(hours=1)).isoformat(),
            "expires_at": (NOW + timedelta(hours=23)).isoformat(),
        }
        admitted = parse_acquisition_input(decode_input(_encode(document)), now=NOW, registry=None)
        with pytest.raises(InputError) as refused:
            pl.bind_plan(admitted)
        assert refused.value.defect is InputDefect.PLAN_NOT_COMPILABLE  # 6 is not the v2 count
        v2_count = dict(document, slice=slice_document(request_count=2))
        admitted = parse_acquisition_input(decode_input(_encode(v2_count)), now=NOW, registry=None)
        with pytest.raises(InputError) as refused:
            pl.bind_plan(admitted)
        assert refused.value.defect is InputDefect.PLAN_DIGEST_MISMATCH
        assert pl.SUPERSEDED_PLAN_CONTRACT_IDS == {"kalpamani-production-acquisition-plan/v1"}
        assert pl.PLAN_CONTRACT_ID == "kalpamani-production-acquisition-plan/v2"

    def test_a_v1_record_is_refused_by_the_build_as_unsupported(self) -> None:
        from kalpamani.data.production.sharadar import build_inputs as bi

        v1 = {
            "provider": "sharadar",
            "dataset": "actions",
            "requested_range": "2025-01-01/2025-12-31",
            "retrieved_at": NOW.isoformat(),
            "source_schema_version": "sharadar-csv-production-v1",
            "ingestion_run_id": RUN_ID,
            "content_sha256": "0" * 64,
            "byte_count": 1,
            "acquisition_mode": "BACKFILL",
            "classification": "LICENSED",
        }
        with pytest.raises(bi.BuildInputError) as refused:
            bi._record(json.dumps(v1).encode())
        assert refused.value.defect is bi.BuildInputDefect.RECORD_CONTRACT_UNSUPPORTED
        with pytest.raises(bi.BuildInputError) as refused:
            bi._record(
                json.dumps(
                    {"contract_id": "x", "retrieval": v1, "request": {}, "pagination": {}}
                ).encode()
            )
        assert refused.value.defect is bi.BuildInputDefect.RECORD_CONTRACT_UNSUPPORTED

    def test_contract_versions_moved_explicitly(self) -> None:
        from kalpamani.data.production.sharadar import build_manifest as bm
        from kalpamani.data.production.sharadar import locator as lc
        from kalpamani.data.production.sharadar import pagination as pg

        assert lc.LOCATOR_SCHEMA_VERSION == "kalpamani-production-run-locator/v2"
        assert lc.SUPERSEDED_LOCATOR_SCHEMA_VERSIONS == {"kalpamani-production-run-locator/v1"}
        assert pp.RECORD_CONTRACT_ID == "kalpamani-production-acquisition-record/v2"
        assert pp.SOURCE_SCHEMA_VERSION == "sharadar-csv-production-v1"  # the CSV is unchanged
        assert bm.MANIFEST_SCHEMA_VERSION == "kalpamani-production-build-manifest/v2"
        assert sv.SILVER_NORMALIZATION_VERSION == "sharadar-silver-v3"
        assert pg.PAGINATION_POLICY_VERSION == "sharadar-pagination-admission-v2"
        assert pg.SUPERSEDED_PAGINATION_POLICY_VERSIONS == {"sharadar-pagination-admission-v1"}


def _spent_digest() -> str:
    from kalpamani.data.production.sharadar.inputs import spent_digest

    return spent_digest([])


def _encode(document: dict[str, Any]) -> bytes:
    from kalpamani.data.contracts.canonical import canonical_bytes

    return canonical_bytes(document)


# ---------------------------------------------------------------------------
# Locator last, no write after a failed probe, the compiled bounds, digests
# ---------------------------------------------------------------------------


class TestRunAccounting:
    def test_the_locator_is_the_last_write_and_no_write_follows_a_failed_probe(self) -> None:
        responses = responses_for_run(1)
        responses[("stocks", WINDOW, 0)] = full_stocks_page()
        responses[("stocks", WINDOW, STOCKS_LIMIT)] = csv(
            STOCKS_HEADER, stocks_rows(date(2026, 9, 1), run=1)[:1]
        )
        store = FakeS3Store()
        report = acquire(
            store, run_id=RUN_1, run=1, at=RUN_1_AT, responses=responses, expect_completed=False
        )
        assert report.halt is pp.ProcessingHalt.PROBE_DATA_BEARING
        puts = [key for key in store.puts]
        # reservation, then 3 writes for each of the two completed coordinates, then the locator.
        assert len(puts) == 1 + 3 * 2 + 1 == report.counts.s3_operations
        assert puts[-1] == f"bronze/sharadar/_indexes/{RUN_1}.json"
        assert not any("/objects/sha256/" in key for key in puts[7:])
        # The failed group's data page is nowhere in the store.
        from kalpamani.data.contracts.canonical import sha256_hex

        assert sha256_hex(full_stocks_page()) not in "".join(store.objects)

    def test_the_provider_call_ceiling_and_the_write_ceiling_are_the_plans(self) -> None:
        responses = responses_for_run(1)
        responses[("stocks", WINDOW, 0)] = full_stocks_page()
        responses[("stocks", WINDOW, STOCKS_LIMIT)] = csv(STOCKS_HEADER, [])
        store = FakeS3Store()
        report = acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT, responses=responses)
        assert report.status is pp.AcquisitionStatus.COMPLETED
        plan = pl.compile_plan(
            parse_slice(
                __import__("fixtures.production_build", fromlist=["slice_for_run"]).slice_for_run(1)
            ),
            acquisition_mode=AcquisitionMode.BACKFILL,
        )
        assert report.counts.provider_requests == 8 <= plan.max_provider_calls == 14
        assert report.counts.s3_operations == plan.expected_writes == 23
        assert report.probes_issued == 1 and report.max_provider_calls == 14
        with pytest.raises(ValueError, match="provider requests cannot exceed"):
            pp.AcquisitionReport(
                status=pp.AcquisitionStatus.HALTED,
                bootstrap=report.bootstrap,
                halt=pp.ProcessingHalt.PROVIDER_FAILURE,
                reservation=report.reservation,
                completed_requests=0,
                planned_requests=7,
                probes_issued=0,
                max_provider_calls=14,
                payloads_written=0,
                payloads_already_present=0,
                publication_state_unknown=False,
                locator=None,
                counts=__import__(
                    "kalpamani.data.production.sharadar.outcomes", fromlist=["OperationCounts"]
                ).OperationCounts(provider_requests=15),
            )

    def test_plan_and_manifest_digests_are_deterministic(self) -> None:
        store = FakeS3Store()
        acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT)
        first = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),), build_id="synthetic-b-1").run()
        second = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),), build_id="synthetic-b-2").run()
        assert (
            first.status is bp.BuildStatus.COMPLETED and second.status is bp.BuildStatus.COMPLETED
        )
        manifests = [json.loads(store.objects[key]) for key in store.keys_under("manifests/")]
        assert len(manifests) == 2 and manifests[0]["run_id"] == manifests[1]["run_id"]

    def test_the_configuration_digest_moves_with_commit_tree_and_timestamp(self) -> None:
        from fixtures.production_runtime import COMMIT, TREE

        base = dict(
            entry=TaskEntry.ACQUISITION,
            code_commit=COMMIT,
            code_tree=TREE,
            generated_at=datetime(2026, 9, 20, tzinfo=UTC),
            secret_name="synthetic/production/sharadar",  # noqa: S106 - an identifier, not a secret
            origin_addresses=["192.0.2.10"],
        )
        reference = build_compiled_configuration(**base)  # type: ignore[arg-type]
        configured, digest = parse_compiled_configuration(reference)
        assert configured.compiled.configuration_digest == digest
        document = json.loads(reference)
        assert document["pagination_targets"] == pl.pagination_targets_document()
        for change in (
            {"code_commit": "1" * 40},
            {"code_tree": "2" * 40},
            {"generated_at": datetime(2026, 9, 21, tzinfo=UTC)},
        ):
            moved = build_compiled_configuration(**{**base, **change})  # type: ignore[arg-type]
            assert parse_compiled_configuration(moved)[1] != digest
        # A configuration naming other targets cannot run under this code.
        tampered = dict(document)
        tampered["pagination_targets"] = dict(document["pagination_targets"], task_memory_mib=4096)
        from kalpamani.data.production.sharadar.compiled import (
            CompiledConfigurationDefect,
            CompiledConfigurationError,
        )

        with pytest.raises(CompiledConfigurationError) as refused:
            parse_compiled_configuration(_encode(tampered))
        assert refused.value.defect is CompiledConfigurationDefect.PAGINATION_TARGETS_MISMATCH
