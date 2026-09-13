"""Task receipts, ledger completion and the compiled configuration (ADR-0044), offline.

Synthetic evidence through the real modules: receipts emitted by the real entries,
verified against launch-record expectations; compiled configuration files generated and
parsed through the real functions; both entries driven from compiled files. **Not AWS,
provider or image-runtime verification.**
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from fixtures.production_build import RUN_1, RUN_1_AT, FakeS3Store, configuration
from fixtures.production_entry import ORIGIN_ADDRESSES, AcquisitionHarness, BuildHarness
from fixtures.production_runtime import (
    BUILD_ID,
    COMMIT,
    CONFIGURATION_DIGEST,
    IMAGE_DIGEST,
    NOW,
    OTHER_IMAGE_DIGEST,
    TASK_ID,
    TREE,
    compiled_task,
    revision_arn,
)
from kalpamani.data.production.sharadar import compiled as pc
from kalpamani.data.production.sharadar import receipts as pr
from kalpamani.data.production.sharadar.entry import (
    EntryConfiguration,
    TaskEntry,
    TaskOutcome,
    TaskReceipt,
)
from kalpamani.data.production.sharadar.inputs import input_digest
from kalpamani.data.production.sharadar.outcomes import (
    CleanupFailure,
    CleanupStage,
    OperationCounts,
    RunnerOutcome,
)
from kalpamani.data.production.sharadar.runner import BootstrapEvidence
from kalpamani.data.production.sharadar.vocabulary import ProductionActor

pytestmark = pytest.mark.unit

ACQ: Final = ProductionActor.ACQUISITION
BUILD: Final = ProductionActor.BUILD


def _expectation(entry: TaskEntry, **overrides: Any) -> pr.ReceiptExpectation:
    actor = ACQ if entry is TaskEntry.ACQUISITION else BUILD
    fields: dict[str, Any] = {
        "entry": entry,
        "task_id": TASK_ID,
        "task_definition_arn": revision_arn(actor),
        "image_digest": IMAGE_DIGEST,
        "configuration_digest": CONFIGURATION_DIGEST,
        "code_commit": COMMIT,
        "identity": RUN_1 if entry is TaskEntry.ACQUISITION else BUILD_ID,
        "input_digest": "ab" * 32,
    }
    fields.update(overrides)
    return pr.ReceiptExpectation(**fields)


# ---------------------------------------------------------------------------
# Receipts emitted by the real entries
# ---------------------------------------------------------------------------


class TestReceiptsFromTheEntries:
    def test_a_completed_acquisition_receipt_binds_to_its_launch_record(self) -> None:
        harness = AcquisitionHarness(spent=None)
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.COMPLETED and receipt.evidence is not None
        lines = receipt.render()
        expectation = _expectation(
            TaskEntry.ACQUISITION, input_digest=input_digest(harness.input_bytes)
        )
        verified = pr.collect_and_verify(lines, expectation=expectation)
        assert verified.outcome is TaskOutcome.COMPLETED and verified.released
        assert verified.counts is not None and verified.counts.provider_requests == 16
        completion = pr.ledger_completion(verified)
        assert completion is not None and completion.outcome == "COMPLETED"
        assert completion.counts == receipt.counts
        # The line discloses no identifier: the binding is a digest.
        document = pr.decode_receipt_line(lines[-1])
        assert set(document) == pr._FIELDS
        assert TASK_ID not in lines[-1].replace(COMMIT, "") and RUN_1 not in lines[-1]
        assert document["binding_digest"] == expectation.binding_digest

    @pytest.mark.parametrize(
        "overrides",
        [
            {"task_id": "f" * 32},
            {"image_digest": OTHER_IMAGE_DIGEST},
            {"identity": "synthetic-production-run-0009"},
            {"input_digest": "cd" * 32},
            {"task_definition_arn": revision_arn(ACQ, 9)},
            {"code_commit": "1" * 40},
        ],
        ids=["task", "image", "identity", "input", "revision", "commit"],
    )
    def test_a_receipt_from_another_run_image_or_build_does_not_bind(
        self, overrides: dict[str, Any]
    ) -> None:
        harness = AcquisitionHarness(spent=None)
        lines = harness.run().render()
        fields = {"input_digest": input_digest(harness.input_bytes), **overrides}
        expectation = _expectation(TaskEntry.ACQUISITION, **fields)
        with pytest.raises(pr.ReceiptError) as refusal:
            pr.collect_and_verify(lines, expectation=expectation)
        assert refusal.value.defect in (
            pr.ReceiptDefect.BINDING_MISMATCH,
            pr.ReceiptDefect.CONFIGURATION_MISMATCH,
        )

    def test_a_refused_bootstrap_receipt_carries_no_binding_and_yields_a_refused_row(self) -> None:
        harness = AcquisitionHarness(release=False, spent=None)
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_NO_RELEASE and receipt.evidence is None
        verified = pr.collect_and_verify(
            receipt.render(), expectation=_expectation(TaskEntry.ACQUISITION)
        )
        assert not verified.released and verified.runner is RunnerOutcome.REFUSED_NO_RELEASE
        completion = pr.ledger_completion(verified)
        assert completion is not None and completion.outcome == "REFUSED"
        assert completion.counts is not None and completion.counts.data_plane_operations == 0

    def test_a_build_receipt_binds_and_completes(self) -> None:
        source = AcquisitionHarness(spent=None)
        assert source.run().outcome is TaskOutcome.COMPLETED
        harness = BuildHarness(source.store, runs=((RUN_1, 1, RUN_1_AT),))
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.COMPLETED
        verified = pr.collect_and_verify(
            receipt.render(),
            expectation=_expectation(
                TaskEntry.BUILD, input_digest=input_digest(harness.input_bytes)
            ),
        )
        assert verified.entry is TaskEntry.BUILD and pr.ledger_completion(verified) is not None
        with pytest.raises(pr.ReceiptError) as refusal:
            pr.collect_and_verify(
                receipt.render(),
                expectation=_expectation(
                    TaskEntry.ACQUISITION, input_digest=input_digest(harness.input_bytes)
                ),
            )
        assert refusal.value.defect is pr.ReceiptDefect.ENTRY_MISMATCH

    def test_unknown_accounting_never_becomes_a_ledger_row(self) -> None:
        receipt = TaskReceipt(
            entry=TaskEntry.ACQUISITION,
            outcome=TaskOutcome.UNCLASSIFIED,
            runner=None,
            counts=OperationCounts(),
            counts_observed=False,
            cleanup_failures=(),
            code_commit=COMMIT,
            configuration_digest=CONFIGURATION_DIGEST,
        )
        document = pr.receipt_document(receipt)
        assert document["counts"] is None and document["counts_observed"] is False
        verified = pr.verify_receipt(document, expectation=_expectation(TaskEntry.ACQUISITION))
        assert verified.counts is None and not verified.counts_observed
        assert pr.ledger_completion(verified) is None
        # A LOCATOR_STATE_UNKNOWN outcome is likewise owner review, not a row.
        uncertain = pr.VerifiedReceipt(
            entry=TaskEntry.ACQUISITION,
            outcome=TaskOutcome.LOCATOR_STATE_UNKNOWN,
            runner=RunnerOutcome.RELEASED,
            counts=OperationCounts(s3_operations=3),
            cleanup_failures=(),
            released=True,
        )
        assert pr.ledger_completion(uncertain) is None
        with pytest.raises(ValueError):
            pr.LedgerCompletion(outcome="COMPLETED", counts=None)


# ---------------------------------------------------------------------------
# The validator refuses incomplete, contradictory and duplicate evidence
# ---------------------------------------------------------------------------


def _document(**overrides: Any) -> dict[str, Any]:
    harness = AcquisitionHarness(spent=None)
    receipt = harness.run()
    document = pr.receipt_document(receipt)
    document.update(overrides)
    if "receipt_digest" not in overrides:
        unsigned = {k: v for k, v in document.items() if k != "receipt_digest"}
        from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex

        document["receipt_digest"] = sha256_hex(canonical_bytes(unsigned))
    return document


class TestValidator:
    def test_no_receipt_and_duplicate_receipts_refuse(self) -> None:
        with pytest.raises(pr.ReceiptError) as refusal:
            pr.collect_receipt_line(["production task refused: x", "counts_observed=true"])
        assert refusal.value.defect is pr.ReceiptDefect.NO_RECEIPT
        line = AcquisitionHarness(spent=None).run().render()[-1]
        with pytest.raises(pr.ReceiptError) as refusal:
            pr.collect_receipt_line([line, "x", line])
        assert refusal.value.defect is pr.ReceiptDefect.DUPLICATE_RECEIPT

    @pytest.mark.parametrize(
        ("overrides", "defect"),
        [
            ({"extra": 1}, pr.ReceiptDefect.FIELD_UNKNOWN),
            ({"schema_version": 2}, pr.ReceiptDefect.SCHEMA_VERSION_UNKNOWN),
            ({"contract_id": "other"}, pr.ReceiptDefect.CONTRACT_ID_UNKNOWN),
            ({"outcome": "SUCCESS"}, pr.ReceiptDefect.OUTCOME_UNKNOWN),
            ({"exit_code": 1}, pr.ReceiptDefect.EXIT_CODE_CONTRADICTS_OUTCOME),
            ({"runner": "REFUSED_INPUT"}, pr.ReceiptDefect.RUNNER_CONTRADICTS_OUTCOME),
            ({"runner": None}, pr.ReceiptDefect.RUNNER_CONTRADICTS_OUTCOME),
            ({"counts_observed": False}, pr.ReceiptDefect.COUNTS_CONTRADICT_OBSERVATION),
            ({"counts": None}, pr.ReceiptDefect.COUNTS_CONTRADICT_OBSERVATION),
            ({"binding_digest": None}, pr.ReceiptDefect.EVIDENCE_CONTRADICTS_OUTCOME),
            ({"binding_digest": "ab" * 32}, pr.ReceiptDefect.BINDING_MISMATCH),
            ({"configuration_digest": "ab" * 32}, pr.ReceiptDefect.CONFIGURATION_MISMATCH),
            ({"code_commit": None}, pr.ReceiptDefect.FIELD_MISSING),
            ({"receipt_digest": "0" * 64}, pr.ReceiptDefect.DIGEST_MISMATCH),
        ],
    )
    def test_each_contradiction_refuses(
        self, overrides: dict[str, Any], defect: pr.ReceiptDefect
    ) -> None:
        harness = AcquisitionHarness(spent=None)
        expectation = _expectation(
            TaskEntry.ACQUISITION, input_digest=input_digest(harness.input_bytes)
        )
        document = _document(**overrides)
        with pytest.raises(pr.ReceiptError) as refusal:
            pr.verify_receipt(document, expectation=expectation)
        assert refusal.value.defect is defect, overrides

    def test_a_missing_field_refuses(self) -> None:
        document = _document()
        del document["counts"]
        with pytest.raises(pr.ReceiptError) as refusal:
            pr.verify_receipt(document, expectation=_expectation(TaskEntry.ACQUISITION))
        assert refusal.value.defect is pr.ReceiptDefect.FIELD_MISSING

    def test_a_bootstrap_refusal_with_data_plane_counts_is_contradictory(self) -> None:
        receipt = TaskReceipt(
            entry=TaskEntry.BUILD,
            outcome=TaskOutcome.REFUSED_IDENTITY,
            runner=RunnerOutcome.REFUSED_IDENTITY,
            counts=OperationCounts(identity_calls=1, s3_operations=2),
            counts_observed=True,
            cleanup_failures=(CleanupFailure(stage=CleanupStage.WORKING_DIRECTORY, failure="X"),),
            code_commit=COMMIT,
            configuration_digest=CONFIGURATION_DIGEST,
        )
        with pytest.raises(pr.ReceiptError) as refusal:
            pr.verify_receipt(
                pr.receipt_document(receipt), expectation=_expectation(TaskEntry.BUILD)
            )
        assert refusal.value.defect is pr.ReceiptDefect.COUNTS_CONTRADICT_OBSERVATION

    def test_a_pre_bootstrap_refusal_verifies_and_keeps_its_cleanup_failure(self) -> None:
        receipt = TaskReceipt(
            entry=TaskEntry.BUILD,
            outcome=TaskOutcome.REFUSED_DEPENDENCY,
            runner=None,
            counts=OperationCounts(),
            counts_observed=True,
            cleanup_failures=(
                CleanupFailure(stage=CleanupStage.WORKING_DIRECTORY, failure="CLEANUP_RAISED"),
            ),
            code_commit=COMMIT,
            configuration_digest=CONFIGURATION_DIGEST,
        )
        verified = pr.verify_receipt(
            pr.receipt_document(receipt), expectation=_expectation(TaskEntry.BUILD)
        )
        assert verified.cleanup_failures[0].stage is CleanupStage.WORKING_DIRECTORY
        assert verified.ledger_outcome == "REFUSED"

    def test_an_unconfigured_refusal_carries_no_configuration_and_still_verifies(self) -> None:
        receipt = TaskReceipt(
            entry=TaskEntry.BUILD,
            outcome=TaskOutcome.REFUSED_CONFIGURATION,
            runner=None,
            counts=OperationCounts(),
            counts_observed=True,
            cleanup_failures=(),
        )
        document = pr.receipt_document(receipt)
        assert document["code_commit"] is None and document["configuration_digest"] is None
        assert pr.verify_receipt(document, expectation=_expectation(TaskEntry.BUILD)).outcome is (
            TaskOutcome.REFUSED_CONFIGURATION
        )
        with pytest.raises(ValueError):
            TaskReceipt(
                entry=TaskEntry.BUILD,
                outcome=TaskOutcome.REFUSED_INPUT,
                runner=RunnerOutcome.REFUSED_INPUT,
                counts=OperationCounts(),
                counts_observed=True,
                cleanup_failures=(),
            )

    def test_evidence_and_receipt_shapes_are_closed(self) -> None:
        with pytest.raises(ValueError):
            TaskReceipt(
                entry=TaskEntry.BUILD,
                outcome=TaskOutcome.COMPLETED,
                runner=RunnerOutcome.RELEASED,
                counts=OperationCounts(),
                counts_observed=True,
                cleanup_failures=(),
                code_commit=COMMIT,
                configuration_digest=CONFIGURATION_DIGEST,
            )  # released without evidence
        evidence = BootstrapEvidence(
            task_id=TASK_ID,
            task_definition_arn=revision_arn(BUILD),
            image_digest=IMAGE_DIGEST,
            identity=BUILD_ID,
            input_digest="ab" * 32,
        )
        assert TASK_ID not in repr(evidence)
        with pytest.raises(pr.ReceiptError):
            pr.ReceiptExpectation(
                entry=TaskEntry.BUILD,
                task_id="short",
                task_definition_arn=revision_arn(BUILD),
                image_digest=IMAGE_DIGEST,
                configuration_digest=CONFIGURATION_DIGEST,
                code_commit=COMMIT,
                identity=BUILD_ID,
                input_digest="ab" * 32,
            )


# ---------------------------------------------------------------------------
# The compiled configuration
# ---------------------------------------------------------------------------


def _acquisition_bytes(**overrides: Any) -> bytes:
    fields: dict[str, Any] = {
        "entry": TaskEntry.ACQUISITION,
        "code_commit": COMMIT,
        "code_tree": TREE,
        "generated_at": NOW,
        "secret_name": "synthetic/production/sharadar",
        "origin_addresses": sorted(ORIGIN_ADDRESSES),
    }
    fields.update(overrides)
    return pc.build_compiled_configuration(**fields)


class TestCompiledConfiguration:
    def test_generation_is_deterministic_and_round_trips(self) -> None:
        raw = _acquisition_bytes()
        assert raw == _acquisition_bytes()
        entry, digest = pc.parse_compiled_configuration(raw)
        assert entry.entry is TaskEntry.ACQUISITION and digest == pc.configuration_digest_of(raw)
        assert entry.compiled.configuration_digest == digest
        assert entry.compiled.code_commit == COMMIT
        assert entry.origin_addresses == ORIGIN_ADDRESSES
        build = pc.build_compiled_configuration(
            entry=TaskEntry.BUILD,
            code_commit=COMMIT,
            code_tree=TREE,
            generated_at=NOW,
            build_configuration=configuration(),
        )
        configured, _ = pc.parse_compiled_configuration(build)
        assert configured.build_configuration is not None
        assert configured.build_configuration.digest == configuration().digest
        assert configured.build_configuration.document() == configuration().document()

    def test_the_file_never_carries_its_own_image_digest_or_revision(self) -> None:
        document = json.loads(_acquisition_bytes())
        assert "image_digest" not in document and "revision" not in document
        assert "configuration_digest" not in document
        assert not any("sha256:" in str(v) for v in document.values())

    @pytest.mark.parametrize(
        ("mutate", "defect"),
        [
            (
                lambda d: d.__setitem__("schema_version", 2),
                pc.CompiledConfigurationDefect.SCHEMA_VERSION_UNKNOWN,
            ),
            (
                lambda d: d.__setitem__("contract_id", "x"),
                pc.CompiledConfigurationDefect.CONTRACT_ID_UNKNOWN,
            ),
            (
                lambda d: d.__setitem__("entry", "other"),
                pc.CompiledConfigurationDefect.ENTRY_UNKNOWN,
            ),
            (
                lambda d: d.__setitem__("actor", "build"),
                pc.CompiledConfigurationDefect.ACTOR_MISMATCH,
            ),
            (
                lambda d: d.__setitem__("family", "kalpamani-research-build"),
                pc.CompiledConfigurationDefect.ACTOR_MISMATCH,
            ),
            (
                lambda d: d.__setitem__("code_commit", "short"),
                pc.CompiledConfigurationDefect.FIELD_MALFORMED,
            ),
            (
                lambda d: d.__setitem__("generated_at", "yesterday"),
                pc.CompiledConfigurationDefect.FIELD_MALFORMED,
            ),
            (lambda d: d.__setitem__("extra", 1), pc.CompiledConfigurationDefect.FIELD_UNKNOWN),
            (lambda d: d.pop("secret_name"), pc.CompiledConfigurationDefect.FIELD_MISSING),
            (
                lambda d: d.__setitem__(
                    "secret_name", "arn:aws:secretsmanager:us-east-1:000000000000:secret:x"
                ),
                pc.CompiledConfigurationDefect.SECRET_NAME_MALFORMED,
            ),
            (
                lambda d: d.__setitem__("secret_name", "bad name"),
                pc.CompiledConfigurationDefect.SECRET_NAME_MALFORMED,
            ),
            (
                lambda d: d.__setitem__("origin_addresses", []),
                pc.CompiledConfigurationDefect.ORIGIN_ADDRESSES_MALFORMED,
            ),
            (
                lambda d: d.__setitem__("origin_addresses", ["::1"]),
                pc.CompiledConfigurationDefect.ORIGIN_ADDRESSES_MALFORMED,
            ),
            (
                lambda d: d.__setitem__("build_configuration", {}),
                pc.CompiledConfigurationDefect.FIELD_UNKNOWN,
            ),
        ],
    )
    def test_each_defect_refuses(self, mutate: Any, defect: pc.CompiledConfigurationDefect) -> None:
        from kalpamani.data.contracts.canonical import canonical_bytes

        document = json.loads(_acquisition_bytes())
        mutate(document)
        with pytest.raises(pc.CompiledConfigurationError) as refusal:
            pc.parse_compiled_configuration(canonical_bytes(document))
        assert refusal.value.defect is defect

    def test_a_build_configuration_pinned_to_another_derivation_refuses(self) -> None:
        from kalpamani.data.contracts.canonical import canonical_bytes

        document = json.loads(
            pc.build_compiled_configuration(
                entry=TaskEntry.BUILD,
                code_commit=COMMIT,
                code_tree=TREE,
                generated_at=NOW,
                build_configuration=configuration(),
            )
        )
        document["build_configuration"]["adjustment_derivation_version"] = "other-v9"
        with pytest.raises(pc.CompiledConfigurationError) as refusal:
            pc.parse_compiled_configuration(canonical_bytes(document))
        assert refusal.value.defect is pc.CompiledConfigurationDefect.DERIVATION_VERSION_MISMATCH
        document = json.loads(
            pc.build_compiled_configuration(
                entry=TaskEntry.BUILD,
                code_commit=COMMIT,
                code_tree=TREE,
                generated_at=NOW,
                build_configuration=configuration(),
            )
        )
        document["build_configuration"]["calendar"]["sessions"] = "none"
        with pytest.raises(pc.CompiledConfigurationError) as refusal:
            pc.parse_compiled_configuration(canonical_bytes(document))
        assert refusal.value.defect is pc.CompiledConfigurationDefect.BUILD_CONFIGURATION_MALFORMED

    @pytest.mark.parametrize(
        ("raw", "defect"),
        [
            (b"", pc.CompiledConfigurationDefect.EMPTY),
            (b"\xef\xbb\xbf{}", pc.CompiledConfigurationDefect.ENCODING_INVALID),
            (b"{", pc.CompiledConfigurationDefect.DOCUMENT_MALFORMED),
            (b'{"a": 1, "a": 2}', pc.CompiledConfigurationDefect.DUPLICATE_KEY),
            (b"[]", pc.CompiledConfigurationDefect.DOCUMENT_MALFORMED),
            (
                b"{" + b" " * pc.MAX_COMPILED_CONFIGURATION_BYTES + b"}",
                pc.CompiledConfigurationDefect.TOO_LARGE,
            ),
        ],
        ids=["empty", "bom", "truncated", "duplicate", "not-object", "oversize"],
    )
    def test_malformed_bytes_refuse(
        self, raw: bytes, defect: pc.CompiledConfigurationDefect
    ) -> None:
        with pytest.raises(pc.CompiledConfigurationError) as refusal:
            pc.parse_compiled_configuration(raw)
        assert refusal.value.defect is defect

    def test_the_compiled_digest_is_what_the_release_must_carry(self) -> None:
        """The trust chain: file digest -> CompiledTask -> ReleaseExpectation, no self-reference."""
        raw = _acquisition_bytes()
        entry, digest = pc.parse_compiled_configuration(raw)
        harness = AcquisitionHarness(spent=None)
        # A release carrying the registered digest of *this* file admits; another refuses.
        from datetime import timedelta

        from fixtures.production_runtime import INTERFACE_ID, SUBNET_ID, TASK_ARN
        from kalpamani.data.production.sharadar.release import build_release_document
        from kalpamani.data.production.sharadar.vocabulary import constants_for

        for registered, expected in (
            (digest, TaskOutcome.COMPLETED),
            ("d" * 64, TaskOutcome.REFUSED_RELEASE_MISMATCH),
        ):
            harness = AcquisitionHarness(spent=None)
            harness.ssm.values[constants_for(ACQ).release_parameter] = build_release_document(
                actor=ACQ,
                task_arn=TASK_ARN,
                task_definition_arn=revision_arn(ACQ),
                image_digest=IMAGE_DIGEST,
                configuration_digest=registered,
                identity=RUN_1,
                input_digest=input_digest(harness.input_bytes),
                network_interface_id=INTERFACE_ID,
                subnet_id=SUBNET_ID,
                verified_at=RUN_1_AT - timedelta(seconds=10),
            )
            receipt = harness.run(harness.configuration(compiled=entry.compiled))
            assert receipt.outcome is expected, registered
            assert receipt.configuration_digest == digest

    def test_a_cross_actor_compiled_configuration_cannot_run_the_other_entry(self) -> None:
        raw = _acquisition_bytes()
        entry, _ = pc.parse_compiled_configuration(raw)
        harness = BuildHarness(FakeS3Store())
        receipt = harness.run(entry)  # an acquisition configuration handed to the build entry
        assert receipt.outcome is TaskOutcome.REFUSED_CONFIGURATION
        assert harness.constructions.built == []
        with pytest.raises(ValueError):
            EntryConfiguration(entry=TaskEntry.BUILD, compiled=compiled_task(ACQ))

    def test_secret_names_are_names_not_arns(self) -> None:
        assert pc.secret_name_refusal("kalpamani/production/sharadar") is None
        assert pc.secret_name_refusal("arn:aws:secretsmanager:us-east-1:000000000000:secret:x")
        assert (
            pc.secret_name_refusal("")
            and pc.secret_name_refusal(7)
            and pc.secret_name_refusal("a b")
        )

    def test_generated_at_is_carried_and_now_is_aware(self) -> None:
        with pytest.raises(pc.CompiledConfigurationError):
            _acquisition_bytes(generated_at=datetime(2026, 9, 13))  # naive
        assert json.loads(_acquisition_bytes(generated_at=datetime(2026, 9, 13, tzinfo=UTC)))[
            "generated_at"
        ].endswith("+00:00")
