"""ADR-0055: the compact build input (version 2) across its producer/consumer closure.

The eighteen-run version-1 document is oversized and refused for execution; the compact
form fits, round-trips and reaches the accepted 32-run ceiling with margin; every binding
version 1 carried beside the identity is re-derived from the digest-bound locator and
refused on every mismatch; the launch tool refuses an oversized input as a closed refusal
before any write or client; the historical v1 reader reads evidence and nothing else; the
build's Silver, Gold and manifest behaviour is unchanged; and the deployment impact is
the build entries' alone.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

import production_launch as launch
import pytest
from test_production_launch_script import _Scenario

from fixtures.production_build import (
    AS_OF,
    RUN_1,
    RUN_1_AT,
    RUN_2,
    RUN_2_AT,
    BuildScenario,
    FakeS3Store,
    compact_rows,
    locator_sha256_of,
    populated_store,
)
from fixtures.production_launch import launch_inputs_document, ledger_document, ledger_row
from fixtures.production_runtime import (
    BUCKET,
    BUILD_ID,
    NOW,
    OTHER_RUN_ID,
    RUN_ID,
    build_input_document,
    compact_row_document,
    encode,
    historical_build_input_v1_document,
    ledger_row_document,
    locator_document,
    slice_document,
    synthetic_locator_sha256,
)
from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar import build_inputs as bi
from kalpamani.data.production.sharadar import build_processing as bp
from kalpamani.data.production.sharadar import inputs as pin
from kalpamani.data.production.sharadar import launch_records as lr
from kalpamani.data.production.sharadar import locator as loc
from kalpamani.data.production.sharadar.keys import run_locator_key_segments
from kalpamani.data.production.sharadar.locator import ProductionLocatorReader
from kalpamani.data.production.sharadar.vocabulary import (
    MAX_ADVANCED_PARAMETER_BYTES,
    ProductionActor,
    constants_for,
)

pytestmark = pytest.mark.unit

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
BLD: Final = ProductionActor.BUILD
ADR: Final = REPO_ROOT / "docs" / "decisions" / "ADR-0055-compact-build-input-v2.md"
#: The size a 32-run version-2 document reaches with every field at its widest valid width
#: (64-character identities, 64-hex digests, microsecond instants); stated in the ADR.
WORST_CASE_32_RUN_BYTES: Final = 5_717
WORST_CASE_MARGIN: Final = MAX_ADVANCED_PARAMETER_BYTES - WORST_CASE_32_RUN_BYTES


def _identity(index: int, width: int = 29) -> str:
    return f"run-20260918T19435{index % 10}Z-{index:08x}"[:width].ljust(width, "0")


def _v1_row(index: int) -> dict[str, Any]:
    """A version-1 row shaped like the real O-5 rows: full slice, microsecond instants."""
    at = datetime.fromisoformat("2026-09-18T19:35:46.777574+00:00") + timedelta(minutes=index)
    return ledger_row_document(
        _identity(index),
        slice={
            "acquisition_mode": "BACKFILL",
            "datasets": ["actions", "stocks", "tickers"],
            "max_response_bytes": 33554432,
            "request_count": 48,
            "windows": {
                "actions": "2024-09-15/2026-09-14",
                "stocks": "2026-08-02/2026-09-14",
                "tickers": "SNAPSHOT",
            },
        },
        plan_digest=sha256_hex(f"plan-{index}".encode()),
        launched_at=at.isoformat(),
        completed_at=(at + timedelta(minutes=1, microseconds=944596)).isoformat(),
    )


def _envelope_v1(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return historical_build_input_v1_document(
        rows,
        build_identity="build-20260918T234038Z-6421d019",
        ledger_digest=pin.ledger_digest(rows),
        issued_at="2026-09-18T23:40:38+00:00",
        expires_at="2026-09-19T23:40:38+00:00",
    )


def _tampered_store(mutate: Any) -> tuple[FakeS3Store, dict[str, Any]]:
    """A populated store whose RUN_1 locator is rewritten by ``mutate`` (digest re-bound)."""
    store = populated_store(runs=(1,))
    key = "/".join(run_locator_key_segments(RUN_1))
    document = json.loads(store.objects[key])
    mutate(document)
    store.objects[key] = canonical_bytes(document)
    return store, document


def _verify(store: FakeS3Store, rows: list[dict[str, Any]], *, now: datetime = AS_OF) -> Any:
    admitted = pin.parse_build_input(
        build_input_document(
            rows,
            ledger_digest=pin.ledger_digest(rows),
            issued_at=(now - timedelta(hours=1)).isoformat(),
            expires_at=(now + timedelta(hours=1)).isoformat(),
        ),
        now=now,
    )
    reader = ProductionLocatorReader(client=store, licensed_bucket=BUCKET)
    return bi.verify_build_inputs(admitted, reader=reader)


def _refusal(store: FakeS3Store, rows: list[dict[str, Any]]) -> bi.BuildInputDefect:
    with pytest.raises(bi.BuildInputError) as info:
        _verify(store, rows)
    return info.value.defect


# ---------------------------------------------------------------------------
# Sizes: the failed v1 shape, the compact v2 shape, the ceiling
# ---------------------------------------------------------------------------


class TestSizes:
    def test_the_eighteen_run_version_one_document_is_oversized_and_refused(self) -> None:
        """The shape that stopped S10c: eighteen whole ledger rows do not fit the 8 KiB tier."""
        rows = [_v1_row(index) for index in range(18)]
        raw = canonical_bytes(_envelope_v1(rows))
        assert len(raw) > MAX_ADVANCED_PARAMETER_BYTES
        with pytest.raises(pin.InputError) as info:
            pin.check_input_size(raw)
        assert info.value.defect is pin.InputDefect.TOO_LARGE
        with pytest.raises(pin.InputError) as info:
            pin.decode_input(raw)
        assert info.value.defect is pin.InputDefect.TOO_LARGE
        # And even a v1 document that fits is refused for execution, by version and contract.
        with pytest.raises(pin.InputError) as info:
            pin.parse_build_input(_envelope_v1(rows[:1]), now=NOW)
        assert info.value.defect is pin.InputDefect.SCHEMA_VERSION_UNKNOWN

    def test_the_eighteen_run_compact_document_fits_and_round_trips(self) -> None:
        rows = [
            compact_row_document(
                _identity(index), locator_sha256=sha256_hex(f"loc-{index}".encode())
            )
            for index in range(18)
        ]
        document = build_input_document(rows, ledger_digest=pin.ledger_digest(rows))
        raw = canonical_bytes(document)
        assert len(raw) < MAX_ADVANCED_PARAMETER_BYTES - 512
        admitted = pin.parse_build_input(pin.decode_input(pin.check_input_size(raw)), now=NOW)
        assert [row.run_identity for row in admitted.runs] == [_identity(i) for i in range(18)]
        assert [row.locator_sha256 for row in admitted.runs] == [r["locator_sha256"] for r in rows]
        assert canonical_bytes(json.loads(raw)) == raw

    def test_the_worst_case_thirty_two_run_document_fits_with_the_stated_margin(self) -> None:
        widest = 64
        rows = [
            compact_row_document(
                ("r" * (widest - 8)) + f"{index:08x}", locator_sha256=("f" * 56) + f"{index:08x}"
            )
            for index in range(pin.MAX_BUILD_RUNS)
        ]
        document = build_input_document(
            rows,
            build_identity="b" * widest,
            ledger_digest=pin.ledger_digest(rows),
            issued_at="2026-09-18T23:59:59.999999+00:00",
            expires_at="2026-09-19T23:59:59.999999+00:00",
        )
        raw = canonical_bytes(document)
        assert len(raw) == WORST_CASE_32_RUN_BYTES
        assert (
            WORST_CASE_MARGIN >= 512
            and len(raw) + WORST_CASE_MARGIN == MAX_ADVANCED_PARAMETER_BYTES
        )
        assert pin.check_input_size(raw) is raw
        admitted = pin.parse_build_input(
            pin.decode_input(raw), now=datetime.fromisoformat("2026-09-19T00:00:00+00:00")
        )
        assert len(admitted.runs) == pin.MAX_BUILD_RUNS
        assert f"{WORST_CASE_32_RUN_BYTES:,}" in ADR.read_text(encoding="utf-8")

    def test_thirty_three_runs_are_refused_by_the_count_ceiling(self) -> None:
        rows = [compact_row_document(_identity(index)) for index in range(pin.MAX_BUILD_RUNS + 1)]
        with pytest.raises(pin.InputError) as info:
            pin.parse_build_input(
                build_input_document(rows, ledger_digest=pin.ledger_digest(rows)), now=NOW
            )
        assert info.value.defect is pin.InputDefect.TOO_MANY_RUNS
        ledger = lr.parse_owner_ledger(
            encode(ledger_document([ledger_row(_identity(i)) for i in range(33)]))
        )
        with pytest.raises(lr.LaunchRecordError) as refused:
            lr.materialize_build_input(
                ledger,
                identity=BUILD_ID,
                kind=lr.LaunchKind.PRODUCTION,
                run_identities=[_identity(i) for i in range(33)],
                now=NOW,
                locator_digests={
                    _identity(i): synthetic_locator_sha256(_identity(i)) for i in range(33)
                },
            )
        assert refused.value.defect is lr.LaunchRecordDefect.TOO_MANY
        assert pin.MAX_BUILD_RUNS == 32

    def test_the_materializer_refuses_an_oversized_document_before_returning_bytes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ceiling is applied to the canonical bytes inside the materializer, so no caller
        can write what the task would refuse; the boundary is exercised by lowering the
        ceiling below one row -- the only way to cross it with valid identities."""
        ledger = lr.parse_owner_ledger(encode(ledger_document([ledger_row(RUN_ID)])))

        def materialize() -> bytes:
            return lr.materialize_build_input(
                ledger,
                identity=BUILD_ID,
                kind=lr.LaunchKind.PRODUCTION,
                run_identities=[RUN_ID],
                now=NOW,
                locator_digests={RUN_ID: synthetic_locator_sha256()},
            )

        raw = materialize()
        assert pin.check_input_size(raw) is raw
        monkeypatch.setattr(pin, "MAX_BUILD_INPUT_DOCUMENT_BYTES", len(raw) - 1)
        with pytest.raises(lr.LaunchRecordError) as refused:
            materialize()
        assert refused.value.defect is lr.LaunchRecordDefect.INPUT_TOO_LARGE

    def test_the_materializer_and_the_task_apply_one_ceiling(self) -> None:
        assert pin.MAX_BUILD_INPUT_DOCUMENT_BYTES == MAX_ADVANCED_PARAMETER_BYTES
        boundary = b"{" + b" " * (MAX_ADVANCED_PARAMETER_BYTES - 2) + b"}"
        assert pin.check_input_size(boundary) is boundary
        assert pin.decode_input(boundary) == {}
        for oversized in (boundary + b" ",):
            with pytest.raises(pin.InputError) as materializer:
                pin.check_input_size(oversized)
            with pytest.raises(pin.InputError) as task:
                pin.decode_input(oversized)
            assert materializer.value.defect is task.value.defect is pin.InputDefect.TOO_LARGE


# ---------------------------------------------------------------------------
# The producer: bind_run_locators holds every preserved locator to its ledger row
# ---------------------------------------------------------------------------


class TestBinding:
    def test_a_preserved_locator_that_validates_against_its_row_contributes_its_digest(
        self,
    ) -> None:
        ledger = lr.parse_owner_ledger(
            encode(ledger_document([ledger_row(RUN_ID), ledger_row(OTHER_RUN_ID)]))
        )
        locators = {
            RUN_ID: encode(locator_document(RUN_ID)),
            OTHER_RUN_ID: encode(locator_document(OTHER_RUN_ID)),
        }
        digests = lr.bind_run_locators(
            ledger, run_identities=[RUN_ID, OTHER_RUN_ID], locators=locators
        )
        assert digests == {identity: sha256_hex(raw) for identity, raw in locators.items()}
        raw = lr.materialize_build_input(
            ledger,
            identity=BUILD_ID,
            kind=lr.LaunchKind.PRODUCTION,
            run_identities=[RUN_ID, OTHER_RUN_ID],
            now=NOW,
            locator_digests=digests,
        )
        admitted = pin.parse_build_input(pin.decode_input(raw), now=NOW)
        assert [(r.run_identity, r.locator_sha256) for r in admitted.runs] == list(digests.items())

    def test_a_missing_locator_is_refused(self) -> None:
        ledger = lr.parse_owner_ledger(encode(ledger_document([ledger_row(RUN_ID)])))
        with pytest.raises(lr.LaunchRecordError) as refused:
            lr.bind_run_locators(ledger, run_identities=[RUN_ID], locators={})
        assert refused.value.defect is lr.LaunchRecordDefect.LOCATOR_MISSING

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d.update(run_id=OTHER_RUN_ID),
            lambda d: d.update(plan_digest="0" * 64),
            lambda d: d.update(completeness="PARTIAL"),
            lambda d: d.update(publication_state_unknown=True),
            lambda d: d["entries"].pop(),
            lambda d: d["slice"].update(request_count=3),
        ],
    )
    def test_a_locator_that_does_not_validate_against_its_row_is_refused(self, mutate: Any) -> None:
        ledger = lr.parse_owner_ledger(encode(ledger_document([ledger_row(RUN_ID)])))
        document = locator_document(RUN_ID)
        mutate(document)
        with pytest.raises(lr.LaunchRecordError) as refused:
            lr.bind_run_locators(
                ledger, run_identities=[RUN_ID], locators={RUN_ID: encode(document)}
            )
        assert refused.value.defect is lr.LaunchRecordDefect.LOCATOR_REFUSED

    def test_two_runs_whose_locators_hash_alike_are_refused(self) -> None:
        """A digest that binds two runs binds neither: the row's binding must be unique."""
        ledger = lr.parse_owner_ledger(
            encode(ledger_document([ledger_row(RUN_ID), ledger_row(OTHER_RUN_ID)]))
        )
        shared = synthetic_locator_sha256()
        with pytest.raises(lr.LaunchRecordError) as refused:
            lr.materialize_build_input(
                ledger,
                identity=BUILD_ID,
                kind=lr.LaunchKind.PRODUCTION,
                run_identities=[RUN_ID, OTHER_RUN_ID],
                now=NOW,
                locator_digests={RUN_ID: shared, OTHER_RUN_ID: shared},
            )
        assert refused.value.defect is lr.LaunchRecordDefect.LOCATOR_DIGEST_DUPLICATE

    def test_the_bound_specification_workload_is_unchanged(self) -> None:
        """The launch specification's build workload names the ledger rows as before; the
        locator binding lives in the input the launch materializes, never in the workload."""
        ledger = lr.parse_owner_ledger(encode(ledger_document([ledger_row(RUN_ID)])))
        inputs = lr.parse_launch_inputs(encode(launch_inputs_document()))
        specification = lr.build_specification(
            ledger=ledger,
            inputs=inputs,
            actor=BLD,
            kind=lr.LaunchKind.PRODUCTION,
            identity=BUILD_ID,
            slice_document=None,
            run_identities=[RUN_ID],
            release_mode=lr.ReleaseMode.NORMAL,
        )
        assert set(specification.workload) == {"runs"}
        assert set(specification.workload["runs"][0]) == {
            "identity",
            "plan_digest",
            "outcome",
            "evidence",
            "completed_at",
        }


# ---------------------------------------------------------------------------
# The consumer: the task re-derives and checks every omitted binding
# ---------------------------------------------------------------------------


class TestConsumer:
    def test_a_valid_compact_input_reaches_the_build_admission_boundary_unchanged(self) -> None:
        store = populated_store(runs=(1, 2))
        inputs = _verify(store, compact_rows(store, ((RUN_1, 1, RUN_1_AT), (RUN_2, 2, RUN_2_AT))))
        assert [run.locator.run_id for run in inputs.runs] == [RUN_1, RUN_2]
        assert [run.locator_sha256 for run in inputs.runs] == [
            locator_sha256_of(store, RUN_1),
            locator_sha256_of(store, RUN_2),
        ]
        # The ledger-row view the build carries forward is the locator's own.
        for run in inputs.runs:
            assert run.row.plan_digest == run.locator.plan_digest
            assert run.row.slice.canonical() == run.locator.slice.canonical()
            assert (run.row.launched_at, run.row.completed_at) == (
                run.locator.started_at,
                run.locator.completed_at,
            )
        assert inputs.ledger_digest == pin.ledger_digest(
            compact_rows(store, ((RUN_1, 1, RUN_1_AT), (RUN_2, 2, RUN_2_AT)))
        )

    def test_an_altered_locator_digest_refuses_before_the_content_is_trusted(self) -> None:
        store = populated_store(runs=(1,))
        rows = [compact_row_document(RUN_1, locator_sha256=synthetic_locator_sha256(RUN_1))]
        assert _refusal(store, rows) is bi.BuildInputDefect.LOCATOR_DIGEST_MISMATCH
        assert store.gets == [
            "/".join(run_locator_key_segments(RUN_1))
        ]  # one read, nothing after it

    def test_a_missing_locator_digest_is_a_malformed_row(self) -> None:
        with pytest.raises(pin.InputError) as info:
            pin.parse_build_input(build_input_document([{"run_identity": RUN_1}]), now=NOW)
        assert info.value.defect is pin.InputDefect.ROW_MALFORMED

    def test_a_wrong_run_identity_for_a_digest_refuses(self) -> None:
        """RUN_2's digest under RUN_1's identity: the key names RUN_1's locator, whose bytes
        do not hash to RUN_2's digest -- refused at the digest, before any content is read."""
        store = populated_store(runs=(1, 2))
        rows = [compact_row_document(RUN_1, locator_sha256=locator_sha256_of(store, RUN_2))]
        assert _refusal(store, rows) is bi.BuildInputDefect.LOCATOR_DIGEST_MISMATCH

    def test_a_locator_whose_declared_identity_differs_refuses_after_the_digest(self) -> None:
        store, document = _tampered_store(lambda d: d.update(run_id=RUN_2))
        rows = [compact_row_document(RUN_1, locator_sha256=locator_sha256_of(store, RUN_1))]
        assert _refusal(store, rows) is bi.BuildInputDefect.LOCATOR_INVALID
        with pytest.raises(loc.RunLocatorError) as info:
            loc.validate_bound_run_locator(
                canonical_bytes(document),
                run_id=RUN_1,
                expected_sha256=locator_sha256_of(store, RUN_1),
            )
        assert info.value.defect is loc.RunLocatorDefect.IDENTITY_MISMATCH

    def test_reordered_rows_refuse_at_the_ledger_digest(self) -> None:
        store = populated_store(runs=(1, 2))
        rows = compact_rows(store, ((RUN_1, 1, RUN_1_AT), (RUN_2, 2, RUN_2_AT)))
        document = build_input_document(rows, ledger_digest=pin.ledger_digest(rows))
        document["runs"].reverse()
        with pytest.raises(pin.InputError) as info:
            pin.parse_build_input(document, now=NOW)
        assert info.value.defect is pin.InputDefect.LEDGER_DIGEST_MISMATCH

    def test_duplicate_identities_and_duplicate_digests_refuse_before_any_read(self) -> None:
        store = populated_store(runs=(1, 2))
        row = compact_rows(store, ((RUN_1, 1, RUN_1_AT),))[0]
        with pytest.raises(pin.InputError) as info:
            pin.parse_build_input(
                build_input_document(
                    [row, dict(row)], ledger_digest=pin.ledger_digest([row, dict(row)])
                ),
                now=NOW,
            )
        assert info.value.defect is pin.InputDefect.IDENTITY_DUPLICATED
        twin = compact_row_document(RUN_2, locator_sha256=row["locator_sha256"])
        with pytest.raises(pin.InputError) as info:
            pin.parse_build_input(
                build_input_document([row, twin], ledger_digest=pin.ledger_digest([row, twin])),
                now=NOW,
            )
        assert info.value.defect is pin.InputDefect.LOCATOR_DIGEST_DUPLICATED
        assert store.gets == []

    @pytest.mark.parametrize(
        ("mutate", "defect"),
        [
            (
                lambda d: d["entries"][0].update(
                    payload_key=d["entries"][0]["payload_key"].replace(
                        "bronze/sharadar/", "bronze/sharadar/qualification/", 1
                    )
                ),
                loc.RunLocatorDefect.PREFIX_NOT_ALLOWED,
            ),
            (
                lambda d: d["entries"][0].update(
                    payload_key="licensed/bronze/other/"
                    + d["entries"][0]["payload_key"].split("/", 3)[3]
                ),
                loc.RunLocatorDefect.PREFIX_NOT_ALLOWED,
            ),
            (lambda d: d.update(plan_digest="0" * 64), loc.RunLocatorDefect.PLAN_DIGEST_MISMATCH),
            (
                lambda d: d["slice"].update(request_count=d["slice"]["request_count"] + 1),
                loc.RunLocatorDefect.PLAN_NOT_COMPILABLE,
            ),
            (lambda d: d.update(completeness="PARTIAL"), loc.RunLocatorDefect.INCOMPLETE),
            (
                lambda d: d.update(publication_state_unknown=True),
                loc.RunLocatorDefect.PUBLICATION_STATE_UNKNOWN,
            ),
            (
                lambda d: d["entries"][0]["pagination"].update(completion="PROBE_PASSED"),
                loc.RunLocatorDefect.PAGINATION_MALFORMED,
            ),
        ],
    )
    def test_internal_bindings_are_re_validated_from_the_digest_bound_locator(
        self, mutate: Any, defect: loc.RunLocatorDefect
    ) -> None:
        """A locator whose bytes hash to the row but whose own plan, prefix, completion or
        completeness clauses fail is refused by the accepted validator, never trusted."""
        store, document = _tampered_store(mutate)
        rows = [compact_row_document(RUN_1, locator_sha256=locator_sha256_of(store, RUN_1))]
        assert _refusal(store, rows) is bi.BuildInputDefect.LOCATOR_INVALID
        with pytest.raises(loc.RunLocatorError) as info:
            loc.validate_bound_run_locator(
                canonical_bytes(document),
                run_id=RUN_1,
                expected_sha256=locator_sha256_of(store, RUN_1),
            )
        assert info.value.defect is defect

    def test_the_bound_validation_refuses_a_malformed_digest_and_an_empty_body(self) -> None:
        raw = encode(locator_document())
        for expected in ("", "x" * 64, sha256_hex(raw).upper()):
            with pytest.raises(loc.RunLocatorError) as info:
                loc.validate_bound_run_locator(raw, run_id=RUN_ID, expected_sha256=expected)
            assert info.value.defect is loc.RunLocatorDefect.LOCATOR_DIGEST_MISMATCH
        with pytest.raises(loc.RunLocatorError) as info:
            loc.validate_bound_run_locator(b"", run_id=RUN_ID, expected_sha256=sha256_hex(b""))
        assert info.value.defect is loc.RunLocatorDefect.LOCATOR_DIGEST_MISMATCH
        validated = loc.validate_bound_run_locator(
            raw, run_id=RUN_ID, expected_sha256=sha256_hex(raw)
        )
        assert (
            validated.run_id == RUN_ID
            and validated.plan_digest == locator_document()["plan_digest"]
        )

    def test_the_build_over_a_compact_input_publishes_silver_gold_and_the_manifest_last(
        self,
    ) -> None:
        store = populated_store()
        scenario = BuildScenario(store)
        report = scenario.run()
        assert report.status is bp.BuildStatus.COMPLETED, (report.status, report.defect)
        assert report.publication is not None
        assert report.artifacts_written == 7 and report.artifacts_already_present == 0
        puts = store.puts[-8:]
        assert [key.split("/")[0] for key in puts] == ["silver"] * 3 + ["gold"] * 4 + ["manifests"]
        manifest_key = store.keys_under("manifests/sharadar/builds/")
        assert len(manifest_key) == 1 and store.puts[-1] == manifest_key[0]
        manifest = json.loads(store.objects[manifest_key[0]])
        rows = compact_rows(store, ((RUN_1, 1, RUN_1_AT), (RUN_2, 2, RUN_2_AT)))
        assert manifest["build_input"]["ledger_digest"] == pin.ledger_digest(rows)
        assert [run["run_id"] for run in manifest["build_input"]["runs"]] == [RUN_1, RUN_2]

    def test_a_task_receiving_a_version_one_input_refuses_at_the_input_stage(self) -> None:
        from fixtures.production_entry import BuildHarness
        from kalpamani.data.production.sharadar.entry import TaskOutcome

        store = populated_store(runs=(1,))
        harness = BuildHarness(store, runs=((RUN_1, 1, RUN_1_AT),))
        rows = [ledger_row_document(RUN_1, slice=slice_document())]
        before = (len(store.gets), len(store.puts))
        harness.ssm.values[constants_for(BLD).input_parameter] = encode(
            historical_build_input_v1_document(
                rows,
                build_identity=BUILD_ID,
                ledger_digest=pin.ledger_digest(rows),
                issued_at=(harness.clock.now() - timedelta(hours=1)).isoformat(),
                expires_at=(harness.clock.now() + timedelta(hours=23)).isoformat(),
            )
        )
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_INPUT
        assert (len(store.gets), len(store.puts)) == before


# ---------------------------------------------------------------------------
# The launch tool: the refusal boundary
# ---------------------------------------------------------------------------


class TestLaunchTool:
    def test_a_production_build_prepares_from_the_preserved_locators(self, tmp_path: Path) -> None:
        scenario = _Scenario(tmp_path, actor=BLD)
        assert scenario.run(authorized=False) == launch.EXIT_PREPARED
        assert len(scenario.files("launch-specification")) == 1

    def test_a_missing_preserved_locator_is_a_record_refusal_before_any_client(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        scenario = _Scenario(tmp_path, actor=BLD)
        (scenario.locators / launch.LOCATOR_FILE_TEMPLATE.format(identity=RUN_ID)).unlink()
        assert scenario.run(authorized=False) == launch.EXIT_REFUSED_RECORDS
        assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_records"]
        assert not scenario.files("launch-specification")

    def test_an_oversized_input_is_a_closed_refusal_with_no_traceback_write_or_client(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 1 of the S10c stop: the raw ValueError no longer escapes. The boundary is
        crossed by lowering the ceiling, the one way to cross it with valid identities."""
        scenario = _Scenario(tmp_path, actor=BLD)
        monkeypatch.setattr(pin, "MAX_BUILD_INPUT_DOCUMENT_BYTES", 64)
        assert scenario.run(authorized=False) == launch.EXIT_REFUSED_INPUT_SIZE
        out = capsys.readouterr().out.strip()
        assert out == launch.SENTENCES["refused_input_size"] and "Traceback" not in out
        assert not scenario.files("launch-specification")
        reservations = scenario.ledger.with_name("ledger.json.reservations")
        assert not reservations.exists() or not list(reservations.glob("*.json"))
        assert scenario.ledger_rows() == [ledger_row(RUN_ID)]
        # the authorized path is refused at the same boundary, before any reservation or client
        assert scenario.run(authorized=True) == launch.EXIT_REFUSED_INPUT_SIZE
        assert not reservations.exists() or not list(reservations.glob("*.json"))
        assert scenario.ledger_rows() == [ledger_row(RUN_ID)]
        assert scenario.ecs.calls == []

    def test_the_authorization_boundary_maps_a_raw_value_error_to_the_same_refusal(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The second boundary: even a materializer that returned oversized bytes reaches
        the authorization as a closed refusal, never as a raw ValueError."""
        scenario = _Scenario(tmp_path, actor=BLD)
        monkeypatch.setattr(
            lr, "materialize_build_input", lambda *a, **k: b"x" * (MAX_ADVANCED_PARAMETER_BYTES + 1)
        )
        assert scenario.run(authorized=False) == launch.EXIT_REFUSED_INPUT_SIZE
        assert capsys.readouterr().out.strip() == launch.SENTENCES["refused_input_size"]
        assert not scenario.files("launch-specification")

    def test_the_exit_code_and_sentence_are_registered(self) -> None:
        assert launch.EXIT_REFUSED_INPUT_SIZE == 20
        assert "refused_input_size" in launch.SENTENCES
        assert not any(
            token in launch.SENTENCES["refused_input_size"] for token in ("Traceback", "ValueError")
        )


# ---------------------------------------------------------------------------
# Governance: the ADR, the registers, the deployment closure
# ---------------------------------------------------------------------------


OWNER_DECISION: Final = (
    "I select Option A for S10c: replace the redundant build-input row representation with a "
    "compact, lossless and strictly validated contract that makes the accepted 32-run ceiling "
    "genuinely reachable within the unchanged 8 KiB advanced-parameter limit. The compact form may "
    "remove only values that are deterministically derived from the run identity, locator key or "
    "validated locator content; it must preserve cryptographic binding, fail closed on every "
    "mismatch, retain v1 as historical evidence only, and weaken no acquisition, build, "
    "point-in-time, schema, completion, write-order or audit requirement. I also authorize fixing "
    "the raw-ValueError refusal boundary and enforcing the byte ceiling during materialization. "
    "This authorizes repository governance/tooling/runtime changes and an exact-head merge, but no "
    "image build, registry publication, Terraform, registration change, AWS task, S3 operation, "
    "production build, backtest or trade."
)


def _plain(text: str) -> str:
    # Blockquote markers are layout, not text: the owner's decision is quoted verbatim.
    lines = (line[2:] if line.startswith("> ") else line for line in text.splitlines())
    return " ".join(" ".join(lines).split()).replace("**", "").replace("`", "")


def _closure(*roots: str) -> set[str]:
    package = "kalpamani.data.production.sharadar"
    seen: set[str] = set()
    frontier = [f"{package}.{root}" for root in roots]
    while frontier:
        module = frontier.pop()
        if module in seen or not module.startswith("kalpamani."):
            continue
        seen.add(module)
        path = REPO_ROOT / "src" / Path(*module.split(".")).with_suffix(".py")
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("kalpamani.")
            ):
                frontier.append(node.module)
                frontier.extend(f"{node.module}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Import):
                frontier.extend(
                    alias.name for alias in node.names if alias.name.startswith("kalpamani.")
                )
    return seen


class TestGovernance:
    def test_the_adr_records_the_owner_decision_and_the_proofs(self) -> None:
        text = ADR.read_text(encoding="utf-8")
        assert OWNER_DECISION in _plain(text)
        assert f"{WORST_CASE_32_RUN_BYTES:,}" in text and f"{WORST_CASE_MARGIN:,}" in text
        assert "8,266" in text and "8,192" in text
        assert (
            "kalpamani-research-build-input/v2" in text
            and "kalpamani-research-build-input/v1" in text
        )
        assert "ACCEPTED / IN FORCE" in text and "exact-head merge" in text
        assert "authorizes no" in text

    def test_the_contract_ids_and_versions_are_the_adrs(self) -> None:
        assert constants_for(BLD).input_contract_id == "kalpamani-research-build-input/v2"
        assert (
            pin.BUILD_INPUT_SCHEMA_VERSION == 2 and pin.HISTORICAL_BUILD_INPUT_SCHEMA_VERSION == 1
        )
        assert pin.HISTORICAL_BUILD_INPUT_CONTRACT_ID == "kalpamani-research-build-input/v1"
        assert (
            constants_for(ProductionActor.ACQUISITION).input_contract_id
            == "kalpamani-production-acquisition-input/v2"
        )

    def test_the_historical_reader_is_reachable_from_no_task_or_launch_execution_path(self) -> None:
        """v1 is evidence: no task entry and no launch-tool execution path names the reader."""
        package = "kalpamani.data.production.sharadar"
        for module in _closure("entry", "acquisition_entry", "build_entry", "runner"):
            path = REPO_ROOT / "src" / Path(*module.split(".")).with_suffix(".py")
            if path.exists() and module != f"{package}.inputs":
                assert "parse_historical_build_input_v1" not in path.read_text(encoding="utf-8"), (
                    module
                )
        for script in (
            "production_launch.py",
            "production_verification_cells.py",
            "production_permission_cells.py",
        ):
            assert "parse_historical_build_input_v1" not in (
                REPO_ROOT / "scripts" / script
            ).read_text(encoding="utf-8")

    def test_the_deployment_impact_is_the_build_entries_alone(self) -> None:
        """Every image carries the one source tree, so the closure is stated on what
        EXECUTES: the version-2 parser is called only under the build actor (the
        runner's build branch, the build launch records, the build launch tool), the
        bound-locator read only from the build-side verifier, and the acquisition
        entry's own admission path names none of the new symbols. That is why the
        rebuild scope is the build and build-verification images (ADR-0055 §6)."""
        package = REPO_ROOT / "src/kalpamani/data/production/sharadar"
        runner = (package / "runner.py").read_text(encoding="utf-8")
        assert runner.count("parse_build_input(") == 1
        dispatch = runner[runner.index("if actor is ProductionActor.ACQUISITION:") :]
        acquisition_branch = dispatch[: dispatch.index("parse_build_input(")]
        assert "parse_acquisition_input(" in acquisition_branch
        assert (
            "return acquisition.run_identity" in acquisition_branch
        )  # the build parser is after it
        callers = {
            path.name
            for path in [*package.glob("*.py"), *(REPO_ROOT / "scripts").glob("*.py")]
            if "read_bound_run_locator(" in path.read_text(encoding="utf-8")
            and "def read_bound_run_locator" not in path.read_text(encoding="utf-8")
        }
        assert callers == {"build_inputs.py"}
        producers = {
            path.name
            for path in [*package.glob("*.py"), *(REPO_ROOT / "scripts").glob("*.py")]
            if "bind_run_locators(" in path.read_text(encoding="utf-8")
            and "def bind_run_locators" not in path.read_text(encoding="utf-8")
        }
        assert producers == {"production_launch.py"}
        for name in ("acquisition_entry.py", "processing.py", "plan.py", "provider.py"):
            text = (package / name).read_text(encoding="utf-8")
            for symbol in (
                "parse_build_input",
                "BuildInputRow",
                "read_bound_run_locator",
                "validate_bound_run_locator",
                "bind_run_locators",
                "check_input_size",
                "parse_historical_build_input_v1",
            ):
                assert symbol not in text, (name, symbol)
        for name in (
            "verification_entry.py",
            "permission_probe_entry.py",
            "deletion_rehearsal_task.py",
        ):
            text = (package / name).read_text(encoding="utf-8")
            assert "parse_build_input" not in text and "read_bound_run_locator" not in text, name

    def test_the_readiness_registers_name_version_two(self) -> None:
        for name in (
            "production-owner-inputs.md",
            "production-owner-checklist.md",
            "production-owner-input-worksheet.md",
        ):
            text = (REPO_ROOT / "docs" / "operations" / name).read_text(encoding="utf-8")
            assert "build-input.v2.synthetic.json" in text and "ADR-0055" in text
        readme = (
            REPO_ROOT / "docs" / "operations" / "examples" / "production" / "README.md"
        ).read_text(encoding="utf-8")
        assert "build-input.v2.synthetic.json" in readme and "historical" in readme
        assert (
            REPO_ROOT / "docs/operations/examples/production/build-input.v1.synthetic.json"
        ).exists()


def test_the_locator_digest_is_a_full_sha256_of_the_preserved_bytes() -> None:
    raw = encode(locator_document())
    assert hashlib.sha256(raw).hexdigest() == sha256_hex(raw)
    assert dataclasses.is_dataclass(pin.BuildInputRow)
