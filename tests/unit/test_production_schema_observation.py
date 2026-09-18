"""Route B: the observation build (proposed ADR-0045), through the real build entry.

An explicitly empty accepted set admits nothing; the build refuses at normalization with
zero writes; its receipt carries the per-dataset header digests it observed **as evidence**;
nothing promotes an observed digest into an accepted set. The store is populated by the
real acquisition path over synthetic responses. **Mocked results are not AWS verification.**
"""

from __future__ import annotations

import dataclasses
from typing import Any, Final

import pytest

from fixtures.production_build import (
    ACTIONS_HEADER,
    RUN_1,
    RUN_1_AT,
    SCHEMAS,
    STOCKS_HEADER,
    TICKERS_HEADER,
    configuration,
    responses_for_run,
)
from fixtures.production_entry import BUILD, AcquisitionHarness, BuildHarness
from fixtures.production_runtime import (
    BUILD_ID,
    CONFIGURATION_DIGEST,
    IMAGE_DIGEST,
    TASK_ID,
    compiled_task,
    revision_arn,
)
from kalpamani.data.production.sharadar import receipts as pr
from kalpamani.data.production.sharadar import schema_observation as so
from kalpamani.data.production.sharadar.build_manifest import BuildConfiguration
from kalpamani.data.production.sharadar.entry import TaskEntry, TaskOutcome, TaskReceipt
from kalpamani.data.production.sharadar.identities import LedgerSpentIdentities
from kalpamani.data.production.sharadar.inputs import input_digest
from kalpamani.data.production.sharadar.silver import AcceptedSchemas
from kalpamani.data.qualify.sharadar.parser import schema_digest_of

pytestmark = pytest.mark.unit

CONFIGURED: Final = LedgerSpentIdentities([])

EMPTY: Final = AcceptedSchemas(
    version="observation-empty-v1",
    digests={"tickers": frozenset(), "stocks": frozenset(), "actions": frozenset()},
)
EXPECTED_DIGESTS: Final = {
    "actions": (schema_digest_of(ACTIONS_HEADER),),
    "stocks": (schema_digest_of(STOCKS_HEADER),),
    "tickers": (schema_digest_of(TICKERS_HEADER),),
}


def _observation_configuration(**overrides: Any) -> BuildConfiguration:
    return dataclasses.replace(configuration(), schemas=EMPTY, **overrides)


def _expectation(harness: BuildHarness) -> pr.ReceiptExpectation:
    return pr.ReceiptExpectation(
        entry=TaskEntry.BUILD,
        task_id=TASK_ID,
        task_definition_arn=revision_arn(BUILD),
        image_digest=IMAGE_DIGEST,
        configuration_digest=CONFIGURATION_DIGEST,
        code_commit=compiled_task(BUILD).code_commit,
        identity=BUILD_ID,
        input_digest=input_digest(harness.input_bytes),
    )


def _acquired(responses: dict[tuple[str, str, int], bytes] | None = None) -> AcquisitionHarness:
    source = AcquisitionHarness(responses=responses, spent=CONFIGURED)
    assert source.run().outcome is TaskOutcome.COMPLETED
    return source


class TestObservationBuild:
    def test_an_empty_accepted_set_admits_nothing(self) -> None:
        for dataset, digests in EXPECTED_DIGESTS.items():
            assert not EMPTY.admits(dataset, digests[0])
            assert SCHEMAS.admits(dataset, digests[0])

    def test_the_observation_build_refuses_with_zero_writes_and_a_complete_observation(
        self,
    ) -> None:
        source = _acquired()
        harness = BuildHarness(source.store, runs=((RUN_1, 1, RUN_1_AT),))
        receipt = harness.run(
            configuration=harness.configuration(build_configuration=_observation_configuration())
        )
        assert receipt.outcome is TaskOutcome.REFUSED_NORMALIZATION and receipt.exit_code == 31
        gets, puts = harness.data_plane_calls()
        assert puts == 0 and gets == 15 and receipt.counts.s3_operations == 15
        assert source.store.keys_under("silver/") == []
        assert source.store.keys_under("gold/") == []
        assert source.store.keys_under("manifests/") == []
        observation = receipt.schema_observation
        assert observation is not None and observation.complete
        for dataset, digests in EXPECTED_DIGESTS.items():
            block = observation.datasets[dataset]
            assert block.digests == digests
            assert block.pages_parsed == block.pages_total > 0
        # The observed digests are exactly the fixtures' accepted ones -- observed, not
        # admitted: the build still refused, and the receipt says so.
        lines = receipt.render()
        assert "schema_observation=COMPLETE digests=3" in lines
        verified = pr.collect_and_verify(lines, expectation=_expectation(harness))
        assert verified.schema_observation == observation
        assert verified.ledger_outcome == "REFUSED" and pr.ledger_completion(verified) is not None
        assert pr.ledger_completion(verified).outcome != "COMPLETED"  # type: ignore[union-attr]

    def test_an_unparseable_page_halts_the_acquisition_and_reaches_no_observation(self) -> None:
        # Pagination v2 (ADR-0053 §11.2): the acquisition actor parses every data page, so a
        # body the accepted parser refuses halts the run before the group's writes and the
        # PARTIAL locator refuses the build at its inputs -- no observation is reachable
        # through the accepted path, and none is invented.
        responses = responses_for_run(1)
        key = next(k for k in responses if k[0] == "actions")
        responses[key] = b"\x00\xff not a delivery"
        source = AcquisitionHarness(responses=responses, spent=CONFIGURED)
        acquisition = source.run()
        assert acquisition.outcome is TaskOutcome.ACQUISITION_HALTED and acquisition.exit_code == 22
        harness = BuildHarness(source.store, runs=((RUN_1, 1, RUN_1_AT),))
        receipt = harness.run(
            configuration=harness.configuration(build_configuration=_observation_configuration())
        )
        assert receipt.outcome is TaskOutcome.REFUSED_INPUTS and receipt.exit_code == 30
        assert receipt.schema_observation is None
        assert harness.data_plane_calls()[1] == 0

    def test_an_observation_over_a_page_that_does_not_parse_is_partial(self) -> None:
        # The observation contract itself: a page the parser refuses is counted, not parsed.
        from datetime import timedelta

        from fixtures.production_build import AS_OF, ledger_row
        from fixtures.production_runtime import BUCKET, build_input_document
        from kalpamani.data.production.sharadar import build_inputs as bi
        from kalpamani.data.production.sharadar.inputs import ledger_digest, parse_build_input
        from kalpamani.data.production.sharadar.locator import ProductionLocatorReader
        from kalpamani.data.production.sharadar.silver import observe_schemas

        source = _acquired()
        rows = [ledger_row(RUN_1, 1, RUN_1_AT)]
        admitted = parse_build_input(
            build_input_document(
                rows,
                ledger_digest=ledger_digest(rows),
                issued_at=(AS_OF - timedelta(hours=1)).isoformat(),
                expires_at=(AS_OF + timedelta(hours=1)).isoformat(),
            ),
            now=AS_OF,
        )
        inputs = bi.verify_build_inputs(
            admitted, reader=ProductionLocatorReader(client=source.store, licensed_bucket=BUCKET)
        )
        pages = list(inputs.pages())
        broken = dataclasses.replace(pages[0], payload=b"\x00\xff not a delivery")
        observation = observe_schemas([broken, *pages[1:]])
        assert not observation.complete
        block = observation.datasets[pages[0].dataset]
        assert block.pages_parsed < block.pages_total

    def test_a_refusal_before_schema_admission_carries_no_observation(self) -> None:
        # Under pagination v2 an unparseable stocks page halts the acquisition, so the build
        # refuses at its inputs -- before schema admission -- with no observation at all.
        responses = responses_for_run(1)
        key = next(k for k in responses if k[0] == "stocks")
        responses[key] = b"\x00\xff not a delivery"
        source = AcquisitionHarness(responses=responses, spent=CONFIGURED)
        assert source.run().outcome is TaskOutcome.ACQUISITION_HALTED
        harness = BuildHarness(source.store, runs=((RUN_1, 1, RUN_1_AT),))
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_INPUTS
        assert receipt.schema_observation is None
        assert pr.receipt_document(receipt)["schema_observation"] is None

    def test_an_ordinary_build_with_accepted_schemas_is_unchanged(self) -> None:
        source = _acquired()
        harness = BuildHarness(source.store, runs=((RUN_1, 1, RUN_1_AT),))
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.COMPLETED and receipt.schema_observation is None
        assert harness.data_plane_calls() == (15, 8)

    def test_a_header_the_set_does_not_admit_is_observed_with_the_admitted_ones(self) -> None:
        """A real accepted set that misses one dataset's header refuses, and the
        observation names every header -- the admitted ones included -- as evidence."""
        partial = AcceptedSchemas(
            version="partial-v1",
            digests={
                "tickers": SCHEMAS.digests["tickers"],
                "stocks": SCHEMAS.digests["stocks"],
                "actions": frozenset(),
            },
        )
        source = _acquired()
        harness = BuildHarness(source.store, runs=((RUN_1, 1, RUN_1_AT),))
        receipt = harness.run(
            configuration=harness.configuration(
                build_configuration=dataclasses.replace(configuration(), schemas=partial)
            )
        )
        assert receipt.outcome is TaskOutcome.REFUSED_NORMALIZATION
        assert receipt.schema_observation is not None
        assert receipt.schema_observation.datasets["actions"].digests == EXPECTED_DIGESTS["actions"]
        assert harness.data_plane_calls()[1] == 0


class TestObservationContract:
    def _block(self, **overrides: Any) -> dict[str, Any]:
        document: dict[str, Any] = {
            "complete": True,
            "datasets": {
                name: {"digests": list(digests), "pages_parsed": 2, "pages_total": 2}
                for name, digests in EXPECTED_DIGESTS.items()
            },
        }
        document.update(overrides)
        return document

    def test_round_trip(self) -> None:
        observation = so.parse_schema_observation(self._block())
        assert observation.complete and observation.digest_count == 3
        assert so.parse_schema_observation(observation.document()) == observation

    def test_a_completeness_claim_the_counts_contradict_is_refused(self) -> None:
        block = self._block()
        block["datasets"]["stocks"]["pages_parsed"] = 1
        with pytest.raises(ValueError):
            so.parse_schema_observation(block)
        block["complete"] = False
        assert not so.parse_schema_observation(block).complete

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda b: b.pop("complete"),
            lambda b: b["datasets"].pop("actions"),
            lambda b: b["datasets"].__setitem__("events", b["datasets"]["actions"]),
            lambda b: b["datasets"]["actions"].__setitem__("digests", ["not-a-digest"]),
            lambda b: b["datasets"]["actions"].__setitem__("pages_parsed", "2"),
            lambda b: b["datasets"]["actions"].__setitem__("pages_total", 1),
            lambda b: b["datasets"]["actions"].__setitem__("digests", []),
        ],
    )
    def test_malformed_blocks_are_refused(self, mutate: Any) -> None:
        block = self._block()
        mutate(block)
        with pytest.raises((ValueError, TypeError)):
            so.parse_schema_observation(block)

    def test_a_dataset_observation_holds_its_own_invariants(self) -> None:
        with pytest.raises(ValueError):
            so.DatasetObservation(digests=(), pages_parsed=1, pages_total=1)
        with pytest.raises(ValueError):
            so.DatasetObservation(
                digests=EXPECTED_DIGESTS["actions"], pages_parsed=0, pages_total=1
            )
        with pytest.raises(ValueError):
            so.DatasetObservation(
                digests=tuple(sorted(EXPECTED_DIGESTS["actions"] * 2)),
                pages_parsed=1,
                pages_total=1,
            )

    def test_a_schema_block_on_a_non_refusal_receipt_is_refused(self) -> None:
        source = _acquired()
        harness = BuildHarness(source.store, runs=((RUN_1, 1, RUN_1_AT),))
        completed = harness.run()
        assert completed.outcome is TaskOutcome.COMPLETED
        observation = so.parse_schema_observation(self._block())
        with pytest.raises(ValueError):
            TaskReceipt(
                entry=completed.entry,
                outcome=completed.outcome,
                runner=completed.runner,
                counts=completed.counts,
                counts_observed=True,
                cleanup_failures=(),
                code_commit=completed.code_commit,
                configuration_digest=completed.configuration_digest,
                evidence=completed.evidence,
                schema_observation=observation,
            )

    def test_nothing_in_the_package_writes_an_observation_into_an_accepted_set(self) -> None:
        """The static half of 'no automatic promotion': no production module names both."""
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "src" / "kalpamani" / "data" / "production"
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "AcceptedSchemas(" in text and "SchemaObservation" in text:
                # silver.py builds observations and *consumes* accepted sets; it must never
                # construct an accepted set from an observation.
                assert (
                    "AcceptedSchemas("
                    not in text.split("def observe_schemas")[-1].split("def _parse(")[0]
                ), path
