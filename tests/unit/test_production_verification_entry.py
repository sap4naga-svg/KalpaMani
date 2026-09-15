"""The verification entries, the probe and the isolation verdict (proposed ADR-0045).

Every case drives the real entry through the public boundary with injected fakes, and
proves through counting what a verification task cannot do: enter production processing,
reserve or spend an identity, retrieve a secret, contact the provider, or perform a
data-plane operation. **Mocked results are not AWS, provider, image or deployment
verification.**
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_build import configuration as build_configuration
from fixtures.production_entry import (
    ACQ,
    BUILD,
    ORIGIN_ADDRESSES,
    AcquisitionHarness,
    FakeProbe,
    VerificationHarness,
    resolve_outside,
)
from fixtures.production_runtime import (
    CONFIGURATION_DIGEST,
    IMAGE_DIGEST,
    TASK_ID,
    compiled_task,
    compiled_verification_task,
    verification_revision_arn,
)
from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar import probe as pp
from kalpamani.data.production.sharadar import receipts as pr
from kalpamani.data.production.sharadar.entry import (
    EXIT_STATUS,
    VERIFICATION_ENTRIES,
    EntryConfiguration,
    TaskEntry,
    TaskOutcome,
    TaskReceipt,
    entry_family,
    run_task_entry,
)
from kalpamani.data.production.sharadar.inputs import input_digest
from kalpamani.data.production.sharadar.outcomes import RunnerOutcome
from kalpamani.data.production.sharadar.vocabulary import constants_for

pytestmark = pytest.mark.unit

PRODUCTION: Final = (
    Path(__file__).resolve().parents[2] / "src" / "kalpamani" / "data" / "production" / "sharadar"
)
VERIFY_ENTRIES: Final = (TaskEntry.ACQUISITION_VERIFY, TaskEntry.BUILD_VERIFY)


def _expectation(harness: VerificationHarness) -> pr.ReceiptExpectation:
    return pr.ReceiptExpectation(
        entry=harness.entry,
        task_id=TASK_ID,
        task_definition_arn=verification_revision_arn(harness.actor),
        image_digest=IMAGE_DIGEST,
        configuration_digest=CONFIGURATION_DIGEST,
        code_commit=compiled_task(harness.actor).code_commit,
        identity=harness.identity,
        input_digest=input_digest(harness.input_bytes),
    )


def _production_configuration(actor: Any) -> EntryConfiguration:
    if actor is ACQ:
        return EntryConfiguration(
            entry=TaskEntry.ACQUISITION,
            compiled=compiled_task(ACQ),
            secret_identifier="synthetic/production/sharadar",  # noqa: S106 - a name
            origin_addresses=ORIGIN_ADDRESSES,
        )
    return EntryConfiguration(
        entry=TaskEntry.BUILD,
        compiled=compiled_task(BUILD),
        build_configuration=build_configuration(),
    )


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------


class TestVocabulary:
    def test_four_entries_two_actors_and_the_verification_families(self) -> None:
        # Six entries since ADR-0048: the two probe entries beside the four.
        assert set(TaskEntry) == {
            TaskEntry.ACQUISITION_PROBE,
            TaskEntry.BUILD_PROBE,
            TaskEntry.ACQUISITION,
            TaskEntry.BUILD,
            TaskEntry.ACQUISITION_VERIFY,
            TaskEntry.BUILD_VERIFY,
        }
        assert VERIFICATION_ENTRIES == frozenset(VERIFY_ENTRIES)
        assert entry_family(TaskEntry.ACQUISITION_VERIFY) == "kalpamani-production-acquire-verify"
        assert entry_family(TaskEntry.BUILD_VERIFY) == "kalpamani-research-build-verify"
        assert entry_family(TaskEntry.ACQUISITION) == constants_for(ACQ).task_family
        for actor in (ACQ, BUILD):
            constants = constants_for(actor)
            assert constants.verification_task_family != constants.task_family

    def test_verified_bootstrap_is_non_zero_and_distinct(self) -> None:
        assert EXIT_STATUS[TaskOutcome.VERIFIED_BOOTSTRAP] == 18
        assert EXIT_STATUS[TaskOutcome.COMPLETED] == 0
        assert len(set(EXIT_STATUS.values())) == len(EXIT_STATUS)

    @pytest.mark.parametrize("entry", VERIFY_ENTRIES)
    def test_a_verification_configuration_holds_no_secret_and_no_build_configuration(
        self, entry: TaskEntry
    ) -> None:
        actor = ACQ if entry is TaskEntry.ACQUISITION_VERIFY else BUILD
        with pytest.raises(ValueError):
            EntryConfiguration(
                entry=entry,
                compiled=compiled_verification_task(actor),
                secret_identifier="x",  # noqa: S106 - an identifier
                origin_addresses=ORIGIN_ADDRESSES,
            )
        with pytest.raises(ValueError):
            EntryConfiguration(
                entry=entry,
                compiled=compiled_verification_task(actor),
                origin_addresses=ORIGIN_ADDRESSES,
                build_configuration=build_configuration(),
            )
        # A production compiled task (the production family) cannot configure a
        # verification entry, and a verification family cannot configure production.
        with pytest.raises(ValueError):
            EntryConfiguration(
                entry=entry, compiled=compiled_task(actor), origin_addresses=ORIGIN_ADDRESSES
            )
        with pytest.raises(ValueError):
            EntryConfiguration(
                entry=TaskEntry.ACQUISITION,
                compiled=compiled_verification_task(ACQ),
                secret_identifier="synthetic/production/sharadar",  # noqa: S106
                origin_addresses=ORIGIN_ADDRESSES,
            )

    def test_the_verification_module_imports_no_secret_transport_s3_or_processing(self) -> None:
        """A-8 applied to the verification image's own module and factories."""
        forbidden = ("secrets", "credentials", "transport", "provider", "processing")
        tree = ast.parse((PRODUCTION / "verification_entry.py").read_text(encoding="utf-8"))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert [m for m in imported if m.rsplit(".", 1)[-1] in forbidden] == []
        assert not any(
            m.endswith((".acquisition_entry", ".build_entry", ".build_processing", ".locator"))
            for m in imported
        )
        factories = VerificationHarness(entry=VERIFY_ENTRIES[0]).factories()
        names = {f.name for f in dataclasses.fields(factories)}
        assert not names & {"s3", "secrets", "transport", "spent_identities"}


# ---------------------------------------------------------------------------
# The verified bootstrap
# ---------------------------------------------------------------------------


class TestVerifiedBootstrap:
    @pytest.mark.parametrize("entry", VERIFY_ENTRIES)
    def test_a_released_bootstrap_stops_with_zero_data_plane_operations(
        self, entry: TaskEntry
    ) -> None:
        harness = VerificationHarness(entry=entry)
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.VERIFIED_BOOTSTRAP and receipt.exit_code == 18
        assert receipt.runner is RunnerOutcome.RELEASED and receipt.evidence is not None
        assert receipt.counts.data_plane_operations == 0
        assert receipt.counts.secret_retrievals == 0 and receipt.counts.provider_requests == 0
        assert receipt.counts.s3_operations == 0
        assert receipt.counts.parameter_reads == 3 and receipt.counts.identity_calls == 1
        assert harness.constructions.built == ["ssm", "sts"]
        assert harness.cleanups == 1
        lines = receipt.render()
        assert lines[0].startswith("verification task stopped at the release barrier")
        assert sum(1 for line in lines if line.startswith("receipt: ")) == 1
        if entry is TaskEntry.BUILD_VERIFY:
            assert "isolation_verdict=NOT_DECIDED_BY_THE_TASK" in lines
        else:
            assert receipt.probe is None

    @pytest.mark.parametrize("entry", VERIFY_ENTRIES)
    def test_the_receipt_verifies_against_the_launch_record_and_completes_no_run(
        self, entry: TaskEntry
    ) -> None:
        harness = VerificationHarness(entry=entry)
        receipt = harness.run()
        verified = pr.collect_and_verify(receipt.render(), expectation=_expectation(harness))
        assert verified.outcome is TaskOutcome.VERIFIED_BOOTSTRAP and verified.released
        completion = pr.ledger_completion(verified)
        assert completion is not None and completion.outcome == "VERIFIED"

    @pytest.mark.parametrize("entry", VERIFY_ENTRIES)
    def test_no_release_refuses_at_the_ceiling_with_a_receipt(self, entry: TaskEntry) -> None:
        harness = VerificationHarness(entry=entry, release=False)
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_NO_RELEASE and receipt.exit_code == 15
        assert receipt.counts.data_plane_operations == 0 and receipt.probe is None
        assert harness.cleanups == 1
        verified = pr.collect_and_verify(receipt.render(), expectation=_expectation(harness))
        assert verified.ledger_outcome == "REFUSED"

    @pytest.mark.parametrize("entry", VERIFY_ENTRIES)
    def test_a_production_configuration_is_refused_before_anything_is_built(
        self, entry: TaskEntry
    ) -> None:
        harness = VerificationHarness(entry=entry)
        receipt = harness.run(configuration=_production_configuration(harness.actor))
        assert receipt.outcome is TaskOutcome.REFUSED_CONFIGURATION and receipt.exit_code == 3
        assert harness.constructions.built == [] and harness.cleanups == 1
        assert receipt.render()[-1].startswith("receipt: ")

    @pytest.mark.parametrize("entry", VERIFY_ENTRIES)
    def test_a_workstation_credential_environment_refuses_with_a_receipt(
        self, entry: TaskEntry
    ) -> None:
        harness = VerificationHarness(entry=entry)
        harness.environment_names = (*harness.environment_names, "AWS_ACCESS_KEY_ID")
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT
        assert receipt.exit_code == 4 and harness.constructions.built == []
        assert sum(1 for line in receipt.render() if line.startswith("receipt: ")) == 1

    def test_the_acquisition_verify_entry_refuses_an_origin_outside_the_compiled_set(
        self,
    ) -> None:
        harness = VerificationHarness(entry=TaskEntry.ACQUISITION_VERIFY)
        harness.resolve = resolve_outside
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_ORIGIN and receipt.exit_code == 5
        assert harness.constructions.built == []

    def test_the_build_verify_entry_needs_a_probe_and_the_acquisition_one_refuses_it(
        self,
    ) -> None:
        build = VerificationHarness(entry=TaskEntry.BUILD_VERIFY)
        assert build.run(probe=None).outcome is TaskOutcome.REFUSED_CONFIGURATION
        acquire = VerificationHarness(entry=TaskEntry.ACQUISITION_VERIFY)
        assert acquire.run(probe=FakeProbe()).outcome is TaskOutcome.REFUSED_CONFIGURATION

    @pytest.mark.parametrize("entry", VERIFY_ENTRIES)
    def test_a_factory_that_raises_is_a_dependency_refusal(self, entry: TaskEntry) -> None:
        harness = VerificationHarness(entry=entry)
        receipt = harness.run(ssm=harness.constructions.factory("ssm", RuntimeError("no client")))
        assert receipt.outcome is TaskOutcome.REFUSED_DEPENDENCY and receipt.exit_code == 6
        assert receipt.counts.parameter_reads == 0

    @pytest.mark.parametrize("entry", VERIFY_ENTRIES)
    def test_the_dispatcher_refuses_production_factories_for_a_verification_entry(
        self, entry: TaskEntry
    ) -> None:
        receipt = run_task_entry(
            entry=entry,
            configuration=VerificationHarness(entry=entry).configuration(),
            factories=AcquisitionHarness().factories(),
        )
        assert receipt.outcome is TaskOutcome.REFUSED_CONFIGURATION

    def test_the_receipt_contract_refuses_a_verified_production_entry(self) -> None:
        receipt = VerificationHarness(entry=TaskEntry.ACQUISITION_VERIFY).run()
        with pytest.raises(ValueError):
            dataclasses.replace(receipt, entry=TaskEntry.ACQUISITION)
        with pytest.raises(ValueError):
            dataclasses.replace(receipt, outcome=TaskOutcome.COMPLETED)


# ---------------------------------------------------------------------------
# The probe: observations, counts, and the verdict it never decides
# ---------------------------------------------------------------------------


BINDING_KEY: Final = "ab" * 32


def _observation(result: pp.ProbeResult) -> pp.ProbeObservation:
    if result is pp.ProbeResult.NOT_ATTEMPTED:
        return pp.ProbeObservation(
            resolution=pp.ProbeResolution.UNRESOLVED, result=result, attempts=0
        )
    return pp.ProbeObservation(
        resolution=pp.ProbeResolution.RESOLVED_IN_SET,
        result=result,
        attempts=1,
        destination_digest=pp.destination_binding_digest(
            BINDING_KEY, min(ORIGIN_ADDRESSES), pp.PROBE_PORT
        ),
    )


class TestProbe:
    @pytest.mark.parametrize(
        "result",
        [pp.ProbeResult.CONNECTED, pp.ProbeResult.CONNECTION_REFUSED, pp.ProbeResult.TIMED_OUT],
    )
    def test_one_attempt_to_the_smallest_in_set_address_with_no_bytes(
        self, result: pp.ProbeResult
    ) -> None:
        probe = FakeProbe(result)
        harness = VerificationHarness(entry=TaskEntry.BUILD_VERIFY, probe=probe)
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.VERIFIED_BOOTSTRAP
        assert receipt.probe is not None
        assert receipt.probe.result is result and receipt.probe.attempts == 1
        assert receipt.probe.resolution is pp.ProbeResolution.RESOLVED_IN_SET
        assert probe.attempts == [(min(ORIGIN_ADDRESSES), pp.PROBE_PORT, pp.PROBE_TIMEOUT_SECONDS)]
        for line in receipt.render():
            assert min(ORIGIN_ADDRESSES) not in line
        verified = pr.collect_and_verify(receipt.render(), expectation=_expectation(harness))
        assert verified.probe == receipt.probe
        # The selected destination is bound under the admitted input's digest: the tool
        # recovers exactly the address the task selected, and nothing else matches.
        assert receipt.evidence is not None
        expected = pp.destination_binding_digest(
            receipt.evidence.input_digest, min(ORIGIN_ADDRESSES), pp.PROBE_PORT
        )
        assert receipt.probe.destination_digest == expected
        assert f"probe_destination={expected}" in receipt.render()
        others = [
            a
            for a in ORIGIN_ADDRESSES
            if pp.destination_binding_digest(receipt.evidence.input_digest, a, pp.PROBE_PORT)
            == expected
        ]
        assert others == [min(ORIGIN_ADDRESSES)]

    def test_a_resolution_failure_makes_no_attempt_and_counts_none(self) -> None:
        probe = FakeProbe(pp.ProbeResult.CONNECTED)
        harness = VerificationHarness(entry=TaskEntry.BUILD_VERIFY, probe=probe)

        def failing(host: str) -> list[str]:
            raise OSError("resolver down")

        harness.resolve = failing
        receipt = harness.run()
        assert receipt.probe is not None
        assert receipt.probe.resolution is pp.ProbeResolution.UNRESOLVED
        assert receipt.probe.result is pp.ProbeResult.NOT_ATTEMPTED
        assert receipt.probe.attempts == 0 and probe.attempts == []

    def test_an_out_of_set_resolution_makes_no_attempt(self) -> None:
        probe = FakeProbe(pp.ProbeResult.CONNECTED)
        harness = VerificationHarness(entry=TaskEntry.BUILD_VERIFY, probe=probe)
        harness.resolve = resolve_outside
        receipt = harness.run()
        assert receipt.probe is not None
        assert receipt.probe.resolution is pp.ProbeResolution.RESOLVED_OUTSIDE_SET
        assert receipt.probe.attempts == 0 and probe.attempts == []

    def test_an_adapter_that_raises_is_a_counted_connection_error(self) -> None:
        harness = VerificationHarness(
            entry=TaskEntry.BUILD_VERIFY, probe=FakeProbe(OSError("boom"))
        )
        receipt = harness.run()
        assert receipt.probe is not None
        assert receipt.probe.result is pp.ProbeResult.CONNECTION_ERROR
        assert receipt.probe.attempts == 1

    def test_the_observation_shape_is_closed(self) -> None:
        with pytest.raises(ValueError):
            pp.ProbeObservation(
                resolution=pp.ProbeResolution.UNRESOLVED,
                result=pp.ProbeResult.TIMED_OUT,
                attempts=1,
            )
        with pytest.raises(ValueError):
            pp.ProbeObservation(
                resolution=pp.ProbeResolution.RESOLVED_IN_SET,
                result=pp.ProbeResult.TIMED_OUT,
                attempts=2,
            )
        with pytest.raises(ValueError):
            pp.parse_probe_observation({"resolution": "RESOLVED_IN_SET", "result": "TIMED_OUT"})
        with pytest.raises(ValueError):
            pp.parse_probe_observation(
                {
                    "resolution": "RESOLVED_IN_SET",
                    "result": "TIMED_OUT",
                    "attempts": "1",
                    "destination_digest": None,
                }
            )
        # An attempt binds exactly one destination digest; no attempt binds none.
        with pytest.raises(ValueError):
            pp.ProbeObservation(
                resolution=pp.ProbeResolution.RESOLVED_IN_SET,
                result=pp.ProbeResult.TIMED_OUT,
                attempts=1,
            )
        with pytest.raises(ValueError):
            pp.ProbeObservation(
                resolution=pp.ProbeResolution.UNRESOLVED,
                result=pp.ProbeResult.NOT_ATTEMPTED,
                attempts=0,
                destination_digest="ab" * 32,
            )
        assert pp.parse_probe_observation(_observation(pp.ProbeResult.TIMED_OUT).document()) == (
            _observation(pp.ProbeResult.TIMED_OUT)
        )

    def test_the_corroboration_kinds_are_the_ones_the_verdict_decides(self) -> None:
        # The verdict itself is held by test_production_isolation_verdict.py.
        assert set(pp.CorroborationKind) == {pp.CorroborationKind.REACHABILITY_ANALYSIS}


# ---------------------------------------------------------------------------
# Receipt v2 evidence blocks
# ---------------------------------------------------------------------------


class TestReceiptEvidence:
    def test_a_probe_block_on_a_production_receipt_is_refused(self) -> None:
        harness = VerificationHarness(entry=TaskEntry.BUILD_VERIFY)
        document = pr.receipt_document(harness.run())
        forged = {name: value for name, value in document.items() if name != "receipt_digest"}
        forged["entry"] = TaskEntry.BUILD.value
        forged["receipt_digest"] = sha256_hex(canonical_bytes(forged))
        with pytest.raises(pr.ReceiptError) as refusal:
            pr.verify_receipt(forged, expectation=_expectation(harness))
        assert refusal.value.defect in (
            pr.ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME,
            pr.ReceiptDefect.ENTRY_MISMATCH,
        )

    def test_a_receipt_line_carries_the_probe_block_and_no_schema_block(self) -> None:
        receipt = VerificationHarness(entry=TaskEntry.BUILD_VERIFY).run()
        document = pr.receipt_document(receipt)
        assert receipt.evidence is not None
        assert document["probe"] == {
            "resolution": "RESOLVED_IN_SET",
            "result": "TIMED_OUT",
            "attempts": 1,
            "destination_digest": pp.destination_binding_digest(
                receipt.evidence.input_digest, min(ORIGIN_ADDRESSES), pp.PROBE_PORT
            ),
        }
        assert document["schema_observation"] is None
        assert document["permission"] is None
        assert document["contract_id"] == "kalpamani-task-receipt/v3"

    def test_a_verification_receipt_with_a_data_plane_count_is_refused(self) -> None:
        receipt = VerificationHarness(entry=TaskEntry.ACQUISITION_VERIFY).run()
        with pytest.raises(ValueError):
            TaskReceipt(
                entry=receipt.entry,
                outcome=receipt.outcome,
                runner=receipt.runner,
                counts=dataclasses.replace(receipt.counts, s3_operations=1),
                counts_observed=True,
                cleanup_failures=(),
                code_commit=receipt.code_commit,
                configuration_digest=receipt.configuration_digest,
                evidence=receipt.evidence,
            )
