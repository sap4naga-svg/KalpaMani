"""The production task entries, driven through the real entry path with synthetic fakes.

Every test here goes through :func:`run_task_entry` -- the selection, the compiled
checks, the credential-environment check, the factories, the accepted bootstrap and the
accepted processing -- and reads counts from the fakes rather than inferring them. **No
socket, no SDK, no real service: a passing test is not AWS or provider verification.**
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_build import (
    ACTIONS_HEADER,
    RUN_1,
    RUN_1_AT,
    RUN_2,
    RUN_2_AT,
    FakeS3Store,
    csv,
    responses_for_run,
)
from fixtures.production_entry import (
    ACQ,
    BUILD,
    METADATA_URI,
    TASK_ENVIRONMENT_NAMES,
    AcquisitionHarness,
    BuildHarness,
    FakeSts,
    resolve_outside,
)
from fixtures.production_runtime import (
    CANARIES,
    OTHER_ACCOUNT,
    OTHER_TASK_ARN,
    FakeClientError,
    build_input_document,
    compiled_task,
    encode,
    human_identity_arn,
    metadata_document,
    task_identity_arn,
)
from kalpamani.data.production.sharadar import acquisition_entry, build_entry, entry
from kalpamani.data.production.sharadar.acquisition_entry import (
    ACQUISITION_OUTCOME,
)
from kalpamani.data.production.sharadar.build_entry import BUILD_OUTCOME, BuildFactories
from kalpamani.data.production.sharadar.build_processing import BuildStatus
from kalpamani.data.production.sharadar.entry import (
    BOOTSTRAP_OUTCOME,
    EXIT_STATUS,
    TASK_SENTENCES,
    EntryConfiguration,
    TaskEntry,
    TaskOutcome,
    TaskReceipt,
    run_task_entry,
    select_entry,
)
from kalpamani.data.production.sharadar.identities import LedgerSpentIdentities
from kalpamani.data.production.sharadar.outcomes import CleanupStage, OperationCounts, RunnerOutcome
from kalpamani.data.production.sharadar.processing import AcquisitionStatus
from kalpamani.data.production.sharadar.task_clients import PutOnlyS3Client
from kalpamani.data.production.sharadar.vocabulary import constants_for

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
PRODUCTION: Final = PROJECT_ROOT / "src" / "kalpamani" / "data" / "production" / "sharadar"

#: Where the fixtures' secret value would show up if anything rendered it.
SECRET_VALUE: Final = "synthetic-fake-not-a-real-sharadar-key-0009"  # noqa: S105

CONFIGURED: Final = LedgerSpentIdentities([])


def rendered(receipt: TaskReceipt) -> str:
    return "\n".join(receipt.render()) + repr(receipt) + repr(receipt.counts)


def assert_sanitized(receipt: TaskReceipt) -> None:
    text = rendered(receipt)
    for canary in CANARIES:
        assert canary not in text
    assert SECRET_VALUE not in text and METADATA_URI not in text


# ---------------------------------------------------------------------------
# Selection, vocabulary, receipts
# ---------------------------------------------------------------------------


class TestSelectionAndVocabulary:
    def test_exactly_one_closed_token_selects_an_entry(self) -> None:
        assert select_entry(["kalpamani-production-acquire"]) is TaskEntry.ACQUISITION
        assert select_entry(["kalpamani-research-build"]) is TaskEntry.BUILD

    @pytest.mark.parametrize(
        "arguments",
        [
            [],
            ["kalpamani-production-acquire", "--now"],
            ["acquire"],
            ["KALPAMANI-PRODUCTION-ACQUIRE"],
            ["kalpamani-production-acquire "],
            [b"kalpamani-research-build"],
            "kalpamani-research-build",
            ["kalpamani-research-build", "kalpamani-production-acquire"],
        ],
    )
    def test_anything_else_selects_nothing(self, arguments: Any) -> None:
        assert select_entry(arguments) is None

    def test_every_outcome_has_one_exit_code_and_one_sentence(self) -> None:
        assert set(EXIT_STATUS) == set(TaskOutcome) and set(TASK_SENTENCES) == set(TaskOutcome)
        assert [o for o, code in EXIT_STATUS.items() if code == 0] == [TaskOutcome.COMPLETED]
        assert len(set(EXIT_STATUS.values())) == len(EXIT_STATUS)
        for outcome, sentence in TASK_SENTENCES.items():
            assert sentence.startswith("production task ")
            if outcome is not TaskOutcome.COMPLETED:
                assert "refused" in sentence or "halted" in sentence or "failed" in sentence

    def test_no_sentence_reads_as_permission_or_a_verdict(self) -> None:
        for sentence in TASK_SENTENCES.values():
            for word in ("READY", "APPROVED", "AUTHORIZED", "PROCEED", "QUALIFIED", "verdict"):
                assert word not in sentence

    def test_the_status_mappings_are_total(self) -> None:
        assert set(ACQUISITION_OUTCOME) | {AcquisitionStatus.REFUSED_BOOTSTRAP} == set(
            AcquisitionStatus
        )
        assert set(BUILD_OUTCOME) | {BuildStatus.REFUSED_BOOTSTRAP} == set(BuildStatus)
        assert set(BOOTSTRAP_OUTCOME) | {
            RunnerOutcome.RELEASED,
            RunnerOutcome.HALTED_PROCESSING_NOT_IMPLEMENTED,
        } == set(RunnerOutcome)

    def test_a_receipt_is_closed_and_consistent(self) -> None:
        with pytest.raises(ValueError):
            TaskReceipt(
                entry=TaskEntry.BUILD,
                outcome=TaskOutcome.COMPLETED,
                runner=RunnerOutcome.REFUSED_INPUT,
                counts=OperationCounts(),
                counts_observed=True,
                cleanup_failures=(),
            )
        with pytest.raises(ValueError):
            TaskReceipt(
                entry=TaskEntry.BUILD,
                outcome=TaskOutcome.UNCLASSIFIED,
                runner=None,
                counts=OperationCounts(),
                counts_observed=True,
                cleanup_failures=(),
            )

    def test_a_configuration_refuses_a_crossed_capability(self) -> None:
        with pytest.raises(ValueError):
            EntryConfiguration(
                entry=TaskEntry.BUILD,
                compiled=compiled_task(BUILD),
                secret_identifier="x",  # noqa: S106 - an identifier, not a secret
            )
        with pytest.raises(ValueError):
            EntryConfiguration(
                entry=TaskEntry.BUILD,
                compiled=compiled_task(BUILD),
                origin_addresses=frozenset({"192.0.2.1"}),
            )
        with pytest.raises(ValueError):
            EntryConfiguration(entry=TaskEntry.ACQUISITION, compiled=compiled_task(BUILD))
        assert "secret" not in repr(AcquisitionHarness().configuration())


# ---------------------------------------------------------------------------
# Refusals before anything is built
# ---------------------------------------------------------------------------


class TestRefusalsBeforeConstruction:
    def test_no_entry_is_a_refusal_with_nothing_built(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)
        receipt = run_task_entry(
            entry=None, configuration=harness.configuration(), factories=harness.factories()
        )
        assert receipt.outcome is TaskOutcome.REFUSED_ENTRY and receipt.exit_code == 2
        assert harness.constructions.built == [] and harness.data_plane_calls() == (0, 0, 0)

    def test_a_missing_configuration_or_factories_refuses(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)
        for configuration, factories in (
            (None, harness.factories()),
            (harness.configuration(), None),
        ):
            receipt = run_task_entry(
                entry=TaskEntry.ACQUISITION, configuration=configuration, factories=factories
            )
            assert receipt.outcome is TaskOutcome.REFUSED_CONFIGURATION
        assert harness.constructions.built == []

    def test_the_other_entrys_configuration_or_factories_refuse(self) -> None:
        acquisition = AcquisitionHarness(spent=CONFIGURED)
        build = BuildHarness(FakeS3Store())
        receipt = run_task_entry(
            entry=TaskEntry.ACQUISITION,
            configuration=build.configuration(),
            factories=acquisition.factories(),
        )
        assert receipt.outcome is TaskOutcome.REFUSED_CONFIGURATION
        receipt = run_task_entry(
            entry=TaskEntry.BUILD,
            configuration=build.configuration(),
            factories=acquisition.factories(),
        )
        assert receipt.outcome is TaskOutcome.REFUSED_CONFIGURATION
        receipt = run_task_entry(
            entry=TaskEntry.ACQUISITION,
            configuration=acquisition.configuration(),
            factories=build.factories(),
        )
        assert receipt.outcome is TaskOutcome.REFUSED_CONFIGURATION
        assert acquisition.constructions.built == [] and build.constructions.built == []

    @pytest.mark.parametrize(
        "configuration_overrides",
        [{"secret_identifier": None}, {"secret_identifier": ""}, {"origin_addresses": frozenset()}],
    )
    def test_an_incomplete_acquisition_configuration_refuses_with_cleanup(
        self, configuration_overrides: dict[str, Any]
    ) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)
        receipt = harness.run(harness.configuration(**configuration_overrides))
        assert receipt.outcome is TaskOutcome.REFUSED_CONFIGURATION and receipt.exit_code == 3
        assert harness.constructions.built == [] and harness.cleanups == 1
        assert receipt.counts == OperationCounts() and receipt.runner is None

    def test_a_build_without_a_build_configuration_refuses(self) -> None:
        harness = BuildHarness(FakeS3Store())
        receipt = harness.run(harness.configuration(build_configuration=None))
        assert receipt.outcome is TaskOutcome.REFUSED_CONFIGURATION
        assert harness.constructions.built == [] and harness.cleanups == 1

    @pytest.mark.parametrize(
        "names",
        [
            ("PATH", "ECS_CONTAINER_METADATA_URI_V4"),  # no container credential provider
            (*TASK_ENVIRONMENT_NAMES, "AWS_PROFILE"),
            (*TASK_ENVIRONMENT_NAMES, "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"),
            (*TASK_ENVIRONMENT_NAMES, "AWS_SHARED_CREDENTIALS_FILE"),
            (*TASK_ENVIRONMENT_NAMES, "AWS_WEB_IDENTITY_TOKEN_FILE"),
        ],
    )
    def test_a_workstation_or_default_chain_environment_refuses_both_entries(
        self, names: tuple[str, ...]
    ) -> None:
        acquisition = AcquisitionHarness(spent=CONFIGURED)
        acquisition.environment_names = names
        receipt = acquisition.run()
        assert receipt.outcome is TaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT
        assert acquisition.constructions.built == [] and acquisition.data_plane_calls() == (0, 0, 0)
        build = BuildHarness(FakeS3Store())
        build.environment_names = names
        receipt = build.run()
        assert receipt.outcome is TaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT
        assert build.constructions.built == [] and build.data_plane_calls() == (0, 0)

    def test_an_environment_that_cannot_be_read_refuses(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)

        def broken() -> list[str]:
            raise RuntimeError("synthetic environment failure")

        receipt = harness.run(environment_names=broken)
        assert receipt.outcome is TaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT
        assert harness.constructions.built == []

    def test_an_origin_outside_the_compiled_set_refuses_before_any_client(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)
        harness.resolve = resolve_outside
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_ORIGIN and receipt.exit_code == 5
        assert harness.constructions.built == [] and harness.data_plane_calls() == (0, 0, 0)

    def test_an_origin_that_does_not_resolve_refuses(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)

        def unresolved(host: str) -> list[str]:
            raise OSError("synthetic resolver failure")

        harness.resolve = unresolved
        assert harness.run().outcome is TaskOutcome.REFUSED_ORIGIN
        assert harness.constructions.built == []

    def test_a_factory_that_raises_is_a_dependency_refusal_with_zero_operations(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)
        receipt = harness.run(
            secrets=harness.constructions.factory("secrets", RuntimeError("synthetic"))
        )
        assert receipt.outcome is TaskOutcome.REFUSED_DEPENDENCY and receipt.exit_code == 6
        assert harness.data_plane_calls() == (0, 0, 0) and harness.cleanups == 1
        build = BuildHarness(FakeS3Store())
        receipt = build.run(s3=build.constructions.factory("s3", object()))
        assert receipt.outcome is TaskOutcome.REFUSED_DEPENDENCY
        assert build.data_plane_calls() == (0, 0)


# ---------------------------------------------------------------------------
# The composed acquisition path
# ---------------------------------------------------------------------------


class TestAcquisitionComposition:
    def test_a_valid_composition_reaches_processing_after_release_and_completes(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.COMPLETED and receipt.exit_code == 0
        assert receipt.runner is RunnerOutcome.RELEASED
        secrets, transport, puts = harness.data_plane_calls()
        assert (secrets, transport, puts) == (1, 16, 50)
        assert receipt.counts.secret_retrievals == secrets
        assert receipt.counts.provider_requests == transport
        assert receipt.counts.s3_operations == puts
        assert receipt.counts.identity_calls == harness.sts.calls == 1
        assert receipt.counts.parameter_reads == 3
        assert harness.constructions.built == ["ssm", "sts", "s3", "secrets", "transport"]
        assert harness.metadata.calls == [(f"{METADATA_URI}/task", 2.0, 64 * 1024)]
        assert harness.cleanups == 1 and receipt.cleanup_failures == ()
        assert harness.store.keys_under(f"bronze/sharadar/_indexes/{RUN_1}.json") != []
        assert_sanitized(receipt)

    def test_the_receipt_renders_the_allowlisted_lines_in_order(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)
        lines = harness.run().render()
        assert lines[0] == "production task completed: every operation confirmed"
        assert lines[1] == "bootstrap: production runner: release verified; processing may begin"
        assert lines[2] == "counts_observed=true"
        assert lines[3:] == tuple(
            f"{name}={value}"
            for name, value in {
                "parameter_reads": 3,
                "parameter_creates": 0,
                "parameter_deletes": 0,
                "run_task": 0,
                "describe_tasks": 0,
                "describe_network_interfaces": 0,
                "stop_task": 0,
                "identity_calls": 1,
                "s3_operations": 50,
                "secret_retrievals": 1,
                "provider_requests": 16,
            }.items()
        )

    def test_a_missing_spent_identity_source_stays_unavailable_and_refuses(self) -> None:
        harness = AcquisitionHarness(spent=None)
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_INPUT and receipt.exit_code == 12
        assert receipt.runner is RunnerOutcome.REFUSED_INPUT
        assert harness.data_plane_calls() == (0, 0, 0) and harness.sts.calls == 0
        assert receipt.counts.data_plane_operations == 0

    def test_a_spent_identity_from_the_configured_source_refuses(self) -> None:
        harness = AcquisitionHarness(spent=LedgerSpentIdentities([RUN_1]))
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_INPUT
        assert harness.data_plane_calls() == (0, 0, 0)

    def test_a_durable_reservation_conflict_prevents_credential_and_provider_activity(
        self,
    ) -> None:
        first = AcquisitionHarness(spent=CONFIGURED)
        assert first.run().outcome is TaskOutcome.COMPLETED
        again = AcquisitionHarness(store=first.store, spent=CONFIGURED)
        receipt = again.run()
        assert receipt.outcome is TaskOutcome.REFUSED_RESERVATION and receipt.exit_code == 20
        assert again.data_plane_calls() == (0, 0, 1)
        assert receipt.counts.secret_retrievals == 0 and receipt.counts.provider_requests == 0
        assert receipt.counts.s3_operations == 1

    def test_the_acquisition_holds_no_read_capability(self) -> None:
        """The client processing sees is put-only, whatever the injected client carries."""
        harness = AcquisitionHarness(spent=CONFIGURED)
        seen: list[Any] = []
        original = PutOnlyS3Client

        class Recording(original):  # type: ignore[misc,valid-type]
            def __init__(self, client: Any) -> None:
                super().__init__(client)
                seen.append(self)

        harness_factories = harness.factories()
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(acquisition_entry, "PutOnlyS3Client", Recording)
            receipt = acquisition_entry.run_acquisition_entry(
                configuration=harness.configuration(), factories=harness_factories
            )
        assert receipt.outcome is TaskOutcome.COMPLETED and len(seen) == 1
        assert not hasattr(seen[0], "get_object") and not hasattr(seen[0], "head_object")
        assert "get_object" not in dir(seen[0]) and "list_objects_v2" not in dir(seen[0])
        assert harness.store.gets == []

    def test_a_credential_failure_after_the_reservation_is_reported_as_such(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)
        harness.secrets.calls = 0
        failing = type(harness.secrets)()

        def get_secret_value(**kwargs: Any) -> dict[str, Any]:
            failing.calls += 1
            raise FakeClientError("AccessDeniedException")

        failing.get_secret_value = get_secret_value  # type: ignore[method-assign]
        receipt = harness.run(secrets=harness.constructions.factory("secrets", failing))
        assert receipt.outcome is TaskOutcome.REFUSED_CREDENTIAL and receipt.exit_code == 21
        assert failing.calls == 1 and harness.transport.call_count == 0
        assert receipt.counts.secret_retrievals == 1 and receipt.counts.provider_requests == 0

    def test_actual_transport_invocations_are_counted_and_local_refusals_are_not(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)
        receipt = harness.run()
        assert receipt.counts.provider_requests == harness.transport.call_count == 16
        # The same adapter, reused across a second harness on a fresh store, keeps
        # counting from its own invocations rather than from the plan.
        second = AcquisitionHarness(run_id=RUN_2, run=2, at=RUN_2_AT, spent=CONFIGURED)
        harness.transport.responses.update(responses_for_run(2))
        receipt = second.run(transport=second.constructions.factory("transport", harness.transport))
        assert receipt.outcome is TaskOutcome.COMPLETED
        # Run 2's plan is larger; the count is this run's own invocations, not the total.
        assert receipt.counts.provider_requests == harness.transport.call_count - 16 == 32

    def test_a_provider_failure_halts_with_observed_counts(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)
        from kalpamani.data.ingest.sharadar.redaction import SharadarErrorCode
        from kalpamani.data.ingest.sharadar.transport import TransportUnavailableError

        coordinate = ("stocks", "2026-09-02/2026-09-02", 0)
        harness.transport.failures[coordinate] = TransportUnavailableError(
            SharadarErrorCode.NETWORK_TIMEOUT
        )
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.ACQUISITION_HALTED and receipt.exit_code == 22
        assert receipt.counts.provider_requests == harness.transport.call_count
        assert receipt.counts.s3_operations == len(harness.store.puts)

    def test_an_unclassified_processing_failure_reports_uncertain_accounting(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)
        with pytest.MonkeyPatch.context() as patch:

            def explode(**kwargs: Any) -> Any:
                raise RuntimeError("synthetic 000000000000 " + SECRET_VALUE)

            patch.setattr(acquisition_entry, "run_production_acquisition", explode)
            receipt = harness.run()
        assert receipt.outcome is TaskOutcome.UNCLASSIFIED and receipt.exit_code == 40
        assert receipt.counts_observed is False and receipt.runner is None
        assert "counts_observed=false" in receipt.render()
        assert harness.cleanups == 1
        assert_sanitized(receipt)

    def test_a_primary_failure_and_a_cleanup_failure_are_both_reported(self) -> None:
        harness = AcquisitionHarness(release=False, spent=CONFIGURED)

        def failing_cleanup() -> None:
            raise OSError("synthetic /private/path 000000000000")

        receipt = harness.run(cleanup=failing_cleanup)
        assert receipt.outcome is TaskOutcome.REFUSED_NO_RELEASE and receipt.exit_code == 15
        assert [f.stage for f in receipt.cleanup_failures] == [CleanupStage.WORKING_DIRECTORY]
        assert receipt.render()[-1] == "cleanup_failure=WORKING_DIRECTORY:CLEANUP_RAISED"
        assert "/private/path" not in rendered(receipt)
        assert harness.data_plane_calls() == (0, 0, 0)


# ---------------------------------------------------------------------------
# Refusals inside the accepted bootstrap, reached through the entry
# ---------------------------------------------------------------------------


class TestBootstrapRefusalsThroughTheEntry:
    def test_identity_mismatch_refuses_with_zero_data_plane_operations(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)
        harness.sts = FakeSts(task_identity_arn(BUILD))
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_IDENTITY and receipt.exit_code == 14
        assert receipt.counts.identity_calls == 1 and harness.data_plane_calls() == (0, 0, 0)
        harness = AcquisitionHarness(spent=CONFIGURED)
        harness.sts = FakeSts(human_identity_arn(ACQ))
        assert harness.run().outcome is TaskOutcome.REFUSED_IDENTITY
        harness = AcquisitionHarness(spent=CONFIGURED)
        harness.sts = FakeSts(task_identity_arn(ACQ), account=OTHER_ACCOUNT)
        assert harness.run().outcome is TaskOutcome.REFUSED_IDENTITY

    def test_identity_unavailable_refuses(self) -> None:
        harness = BuildHarness(FakeS3Store())
        harness.sts = FakeSts(task_identity_arn(BUILD), failure="ExpiredToken")
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_IDENTITY
        assert harness.data_plane_calls() == (0, 0) and harness.sts.calls == 1

    def test_malformed_incomplete_or_contradictory_metadata_refuses(self) -> None:
        for change in (
            {"raw": b"{not json"},
            {"raw": b"\xef\xbb\xbf{}"},
            {"raw": b"{" + b" " * (64 * 1024) + b"}"},
            {"document": {**metadata_document(ACQ), "Containers": []}},
            {"document": {k: v for k, v in metadata_document(ACQ).items() if k != "Revision"}},
            {
                "document": {
                    **metadata_document(ACQ),
                    "Cluster": (
                        "arn:aws:ecs:us-east-1:999999999999:cluster/synthetic-research-cluster"
                    ),
                }
            },
            {"document": {**metadata_document(ACQ), "TaskARN": OTHER_TASK_ARN}},
            {"failure": TimeoutError("synthetic metadata timeout")},
        ):
            harness = AcquisitionHarness(spent=CONFIGURED)
            for name, value in change.items():
                setattr(harness.metadata, name, value)
            receipt = harness.run()
            document = change.get("document")
            other_task = isinstance(document, dict) and document.get("TaskARN") == OTHER_TASK_ARN
            expected = (
                TaskOutcome.REFUSED_IDENTITY if other_task else TaskOutcome.REFUSED_SELF_CHECK
            )
            assert receipt.outcome is expected, change
            assert harness.data_plane_calls() == (0, 0, 0)

    def test_a_metadata_uri_outside_the_link_local_endpoint_refuses(self) -> None:
        for uri in (
            "http://169.254.170.2.attacker.example/v4/abc",
            "https://169.254.170.2/v4/abc",
            "http://user@169.254.170.2/v4/abc",
            "http://169.254.170.2:8080/v4/abc",
            "http://169.254.170.2/v3/abc",
            "",
        ):
            harness = AcquisitionHarness(spent=CONFIGURED)
            harness.environment = {"ECS_CONTAINER_METADATA_URI_V4": uri}
            assert harness.run().outcome is TaskOutcome.REFUSED_SELF_CHECK, uri
            assert harness.metadata.calls == []
        harness = AcquisitionHarness(spent=CONFIGURED)
        harness.environment = {}
        assert harness.run().outcome is TaskOutcome.REFUSED_SELF_CHECK

    def test_a_missing_input_refuses_before_identity(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)
        del harness.ssm.values[constants_for(ACQ).input_parameter]
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_INPUT
        assert harness.sts.calls == 0 and harness.data_plane_calls() == (0, 0, 0)

    def test_no_release_stale_release_and_mismatched_release_refuse(self) -> None:
        harness = AcquisitionHarness(release=False, spent=CONFIGURED)
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_NO_RELEASE
        assert harness.data_plane_calls() == (0, 0, 0) and receipt.counts.parameter_reads == 62
        harness = AcquisitionHarness(spent=CONFIGURED)
        harness.clock.seconds += 15 * 60  # the release is now older than ten minutes
        assert harness.run().outcome is TaskOutcome.REFUSED_RELEASE_MISMATCH
        other = AcquisitionHarness(run_id=RUN_2, run=2, at=RUN_2_AT, spent=CONFIGURED)
        mismatched = AcquisitionHarness(spent=CONFIGURED)
        mismatched.ssm.values[constants_for(ACQ).release_parameter] = other.ssm.values[
            constants_for(ACQ).release_parameter
        ]
        receipt = mismatched.run()
        assert receipt.outcome is TaskOutcome.REFUSED_RELEASE_MISMATCH and receipt.exit_code == 16
        assert mismatched.data_plane_calls() == (0, 0, 0)

    def test_a_release_read_failure_refuses(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)
        harness.ssm.get_failures[constants_for(ACQ).release_parameter] = "AccessDeniedException"
        assert harness.run().outcome is TaskOutcome.REFUSED_RELEASE_READ

    def test_a_private_variable_in_the_task_context_refuses(self) -> None:
        harness = AcquisitionHarness(spent=CONFIGURED)
        harness.environment_names = (*TASK_ENVIRONMENT_NAMES, "KALPAMANI_SHARADAR_SECRET_ID")
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_ENVIRONMENT and receipt.exit_code == 10
        assert receipt.counts == OperationCounts()

    def test_the_release_barrier_cannot_be_bypassed_by_a_processing_status(self) -> None:
        """A refused bootstrap is always mapped from the bootstrap's own outcome."""
        harness = AcquisitionHarness(release=False, spent=CONFIGURED)
        receipt = harness.run()
        assert receipt.runner is RunnerOutcome.REFUSED_NO_RELEASE
        assert receipt.outcome is BOOTSTRAP_OUTCOME[receipt.runner]
        assert receipt.counts.data_plane_operations == 0


# ---------------------------------------------------------------------------
# The composed build path
# ---------------------------------------------------------------------------


class TestBuildComposition:
    def test_a_valid_build_composition_reaches_processing_after_release_and_completes(
        self,
    ) -> None:
        source = AcquisitionHarness(spent=CONFIGURED)
        assert source.run().outcome is TaskOutcome.COMPLETED
        harness = BuildHarness(source.store, runs=((RUN_1, 1, RUN_1_AT),))
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.COMPLETED and receipt.exit_code == 0
        assert receipt.runner is RunnerOutcome.RELEASED
        gets, puts = harness.data_plane_calls()
        assert (gets, puts) == (33, 8) and receipt.counts.s3_operations == gets + puts
        assert receipt.counts.secret_retrievals == 0 and receipt.counts.provider_requests == 0
        assert receipt.counts.identity_calls == harness.sts.calls == 1
        assert harness.constructions.built == ["ssm", "sts", "s3"]
        assert harness.cleanups == 1
        assert harness.store.keys_under("manifests/") != []
        assert_sanitized(receipt)

    def test_the_build_cannot_hold_a_secret_or_a_provider(self) -> None:
        assert {f for f in BuildFactories.__dataclass_fields__} == {
            "environment_names",
            "environment",
            "metadata_fetch",
            "ssm",
            "sts",
            "s3",
            "now",
            "monotonic",
            "sleep",
            "cleanup",
        }
        with pytest.raises(TypeError):
            dataclasses.replace(
                BuildHarness(FakeS3Store()).factories(),
                secrets=object(),  # type: ignore[call-arg]
            )
        harness = BuildHarness(FakeS3Store())
        with pytest.raises(ValueError):
            harness.configuration(secret_identifier="x")  # noqa: S106 - an identifier

    def test_the_build_entry_module_imports_no_credential_secrets_or_provider(self) -> None:
        """ADR-0036 acceptance guard A-8, applied to the build image's import graph."""
        forbidden = ("secrets", "credentials", "transport", "provider", "processing", "client")
        for path in (PRODUCTION / "build_entry.py", PRODUCTION / "build_processing.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = {
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            }
            offenders = [m for m in imported if m.rsplit(".", 1)[-1] in forbidden]
            assert offenders == [], (path.name, offenders)
        acquisition = ast.parse((PRODUCTION / "acquisition_entry.py").read_text(encoding="utf-8"))
        imported = {
            node.module
            for node in ast.walk(acquisition)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not any(
            m.endswith((".locator", ".build_processing", ".build_inputs")) for m in imported
        )

    def test_a_build_refusal_writes_nothing_and_keeps_its_accounting(self) -> None:
        store = FakeS3Store()
        harness = BuildHarness(store, runs=((RUN_1, 1, RUN_1_AT),))
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_INPUTS and receipt.exit_code == 30
        gets, puts = harness.data_plane_calls()
        assert puts == 0 and receipt.counts.s3_operations == gets == 1

    def test_the_full_synthetic_path_keeps_the_pagination_refusal_and_zero_build_writes(
        self,
    ) -> None:
        """Acquisition entry -> COMPLETE locator -> build entry, an unsupported delivery."""
        responses = responses_for_run(1)
        responses[("actions", "2026-08-01/2026-09-14", 10000)] = csv(
            ACTIONS_HEADER,
            [("2026-08-20", "dividend", "ZY00001", "Synthetic", "0.01", "", "")],
        )
        source = AcquisitionHarness(responses=responses, spent=CONFIGURED)
        acquisition = source.run()
        assert acquisition.outcome is TaskOutcome.COMPLETED
        document = json.loads(source.store.objects[f"bronze/sharadar/_indexes/{RUN_1}.json"])
        assert document["completeness"] == "COMPLETE"
        harness = BuildHarness(source.store, runs=((RUN_1, 1, RUN_1_AT),))
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_NORMALIZATION and receipt.exit_code == 31
        gets, puts = harness.data_plane_calls()
        assert puts == 0 and gets == 33 and receipt.counts.s3_operations == 33
        assert source.store.keys_under("silver/") == []
        assert source.store.keys_under("gold/") == []
        assert source.store.keys_under("manifests/") == []
        assert_sanitized(receipt)

    def test_an_unclassified_build_failure_reports_uncertain_accounting(self) -> None:
        harness = BuildHarness(FakeS3Store())
        with pytest.MonkeyPatch.context() as patch:

            def explode(**kwargs: Any) -> Any:
                raise RuntimeError("synthetic")

            patch.setattr(build_entry, "run_production_build", explode)
            receipt = harness.run()
        assert receipt.outcome is TaskOutcome.UNCLASSIFIED and receipt.counts_observed is False
        assert harness.cleanups == 1

    def test_a_build_input_that_does_not_validate_refuses_before_identity(self) -> None:
        harness = BuildHarness(FakeS3Store())
        harness.ssm.values[constants_for(BUILD).input_parameter] = encode(
            build_input_document(schema_version=99)
        )
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.REFUSED_INPUT
        assert harness.sts.calls == 0 and harness.data_plane_calls() == (0, 0)


# ---------------------------------------------------------------------------
# The modules stay dormant on import
# ---------------------------------------------------------------------------


def test_importing_the_entry_modules_constructs_nothing_and_names_no_sdk() -> None:
    for name in ("entry", "acquisition_entry", "build_entry", "task_clients", "task_metadata"):
        tree = ast.parse((PRODUCTION / f"{name}.py").read_text(encoding="utf-8"))
        imported = {
            (node.module if isinstance(node, ast.ImportFrom) else alias.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.Import | ast.ImportFrom)
            for alias in (getattr(node, "names", None) or [None])
        }
        assert not any(
            str(m).split(".")[0] in ("boto3", "botocore", "socket", "urllib3", "requests", "os")
            for m in imported
            if m
        ), (name, imported)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.ClassDef | ast.If | ast.Expr):
                continue
            assert "os.environ" not in ast.unparse(node) and "boto3" not in ast.unparse(node)
    assert entry.run_task_entry is not None
