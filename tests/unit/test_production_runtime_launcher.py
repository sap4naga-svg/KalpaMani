"""Behavioural tests: the launch sequence through injected adapters, on fakes only.

Success path, placement failure of every kind, the two create-only conflicts,
partial identity failures, cleanup failures preserved beside the primary
outcome, the own-task stop restriction, and the override restrictions on the
one ``RunTask`` request.
"""

from __future__ import annotations

from typing import Any, Final

import pytest

from fixtures.production_runtime import (
    BUILD_ID,
    CANARIES,
    INTERFACE_ID,
    KEY_ARN,
    OTHER_SECURITY_GROUP,
    OTHER_SUBNET_ID,
    OTHER_TASK_ARN,
    RUN_ID,
    SECURITY_GROUPS,
    SUBNET_ID,
    TASK_ARN,
    FakeClock,
    FakeEc2,
    FakeEcs,
    FakeSsm,
    acquisition_input_document,
    build_input_document,
    compiled_launch,
    encode,
    interface_entry,
    revision_arn,
    task_entry,
)
from kalpamani.data.production.sharadar import compute as pc
from kalpamani.data.production.sharadar import launcher as pl
from kalpamani.data.production.sharadar.inputs import input_digest
from kalpamani.data.production.sharadar.outcomes import (
    CleanupFailure,
    CleanupStage,
    LaunchOutcome,
    PlacementIncident,
    launch_sentence,
)
from kalpamani.data.production.sharadar.parameters import ParameterFailure, SsmParameterAdapter
from kalpamani.data.production.sharadar.release import (
    ReleaseExpectation,
    decode_release,
    verify_release,
)
from kalpamani.data.production.sharadar.vocabulary import (
    IdentityPath,
    ProductionActor,
    constants_for,
)

ACQ: Final = ProductionActor.ACQUISITION
BLD: Final = ProductionActor.BUILD


class _Scenario:
    """One launch scenario: fakes, adapters, an authorization, and a run."""

    def __init__(
        self, actor: ProductionActor = ACQ, *, public_ip: str | None = "203.0.113.10"
    ) -> None:
        self.actor = actor
        self.compiled = compiled_launch(actor)
        self.ecs = FakeEcs(
            run_response={
                "tasks": [
                    task_entry(
                        actor,
                        status="PROVISIONING",
                        attachment_status="PRECREATED",
                        interface_id=None,
                        subnet_id=None,
                    )
                ],
                "failures": [],
            },
            descriptions=[
                task_entry(actor, status="PENDING", attachment_status="ATTACHED"),
                task_entry(actor, status="RUNNING", attachment_status="ATTACHED"),
                task_entry(actor, status="STOPPED", attachment_status="ATTACHED", exit_code=0),
            ],
        )
        self.ec2 = FakeEc2(interface=interface_entry(public_ip=public_ip if actor is ACQ else None))
        self.human_ssm = FakeSsm()
        self.launcher_ssm = FakeSsm()
        self.clock = FakeClock()
        self.proofs: list[IdentityPath] = []
        self.refuse: set[IdentityPath] = set()
        self.refuse_after: int | None = None
        document = acquisition_input_document() if actor is ACQ else build_input_document()
        self.authorization = pl.LaunchAuthorization(
            identity=RUN_ID if actor is ACQ else BUILD_ID, input_bytes=encode(document)
        )

    def adapters(self) -> pl.LaunchAdapters:
        return pl.LaunchAdapters(
            ecs=pc.EcsTaskAdapter(ecs=self.ecs, compiled=self.compiled),
            ec2=pc.Ec2InterfaceAdapter(ec2=self.ec2),
            human_parameters=SsmParameterAdapter(ssm=self.human_ssm),
            launcher_parameters=SsmParameterAdapter(ssm=self.launcher_ssm),
        )

    def proof(self, path: IdentityPath) -> str | None:
        self.proofs.append(path)
        if self.refuse_after is not None and len(self.proofs) > self.refuse_after:
            return "refused"
        return "refused" if path in self.refuse else None

    def run(self) -> pl.LaunchReport:
        return pl.launch_authorized_run(
            compiled=self.compiled,
            adapters=self.adapters(),
            authorization=self.authorization,
            identity_proof=self.proof,
            now=self.clock.now,
            monotonic=self.clock.monotonic,
            sleep=self.clock.sleep,
        )

    @property
    def constants(self) -> Any:
        return constants_for(self.actor)


class TestTheSuccessPath:
    @pytest.mark.parametrize("actor", (ACQ, BLD), ids=lambda a: a.value)
    def test_one_launch_verified_released_observed_and_cleaned_up(
        self, actor: ProductionActor
    ) -> None:
        scenario = _Scenario(actor)
        report = scenario.run()
        assert report.outcome is LaunchOutcome.TASK_TERMINAL
        assert report.task_started and report.task_exit_codes == (0,)
        assert report.cleanup_failures == () and report.incident is None
        counts = report.counts
        assert counts.run_task == 1
        # One describe for placement (ATTACHED at once), then RUNNING, then STOPPED.
        assert counts.describe_tasks == 3
        assert scenario.clock.sleeps == [pl.OBSERVE_POLL_INTERVAL_SECONDS]
        assert counts.describe_network_interfaces == 1
        assert counts.stop_task == 0
        assert counts.parameter_creates == 2 and counts.parameter_deletes == 2
        assert counts.identity_calls == 4
        assert counts.data_plane_operations == 0
        # The human profile touched only the input; the launcher only the release.
        assert scenario.human_ssm.names("put_parameter") == [scenario.constants.input_parameter]
        assert scenario.human_ssm.names("delete_parameter") == [scenario.constants.input_parameter]
        assert scenario.launcher_ssm.names("put_parameter") == [
            scenario.constants.release_parameter
        ]
        assert scenario.launcher_ssm.names("delete_parameter") == [
            scenario.constants.release_parameter
        ]
        assert scenario.human_ssm.values == {} and scenario.launcher_ssm.values == {}
        # Identity was proven before each profile's work, and before each cleanup.
        assert scenario.proofs == [
            IdentityPath.HUMAN,
            IdentityPath.LAUNCHER,
            IdentityPath.LAUNCHER,
            IdentityPath.HUMAN,
        ]

    def test_the_release_written_is_the_one_the_task_would_verify(self) -> None:
        scenario = _Scenario()
        written: dict[str, bytes] = {}
        original_put = scenario.launcher_ssm.put_parameter

        def capture(**kwargs: Any) -> dict[str, Any]:
            written[kwargs["Name"]] = kwargs["Value"].encode("utf-8")
            return original_put(**kwargs)

        scenario.launcher_ssm.put_parameter = capture  # type: ignore[method-assign]
        scenario.run()
        release = verify_release(
            decode_release(written[scenario.constants.release_parameter]),
            expectation=ReleaseExpectation(
                actor=ACQ,
                task_arn=TASK_ARN,
                task_definition_arn=revision_arn(ACQ),
                identity=RUN_ID,
                input_digest=input_digest(scenario.authorization.input_bytes),
            ),
            now=scenario.clock.now(),
        )
        assert release.network_interface_id == INTERFACE_ID and release.subnet_id == SUBNET_ID

    def test_the_run_task_request_carries_no_override_and_count_one(self) -> None:
        scenario = _Scenario()
        scenario.run()
        (kwargs,) = scenario.ecs.names("run_task")
        assert set(kwargs) == {
            "cluster",
            "taskDefinition",
            "count",
            "launchType",
            "platformVersion",
            "networkConfiguration",
            "enableExecuteCommand",
        }
        assert "overrides" not in kwargs and kwargs["count"] == 1
        assert kwargs["taskDefinition"] == revision_arn(ACQ) and kwargs["launchType"] == "FARGATE"
        assert kwargs["enableExecuteCommand"] is False
        vpc = kwargs["networkConfiguration"]["awsvpcConfiguration"]
        assert vpc == {
            "subnets": [SUBNET_ID],
            "securityGroups": list(SECURITY_GROUPS),
            "assignPublicIp": "ENABLED",
        }

    def test_the_build_launch_disables_the_public_ip(self) -> None:
        scenario = _Scenario(BLD)
        scenario.run()
        (kwargs,) = scenario.ecs.names("run_task")
        assert kwargs["networkConfiguration"]["awsvpcConfiguration"]["assignPublicIp"] == "DISABLED"

    def test_a_late_attachment_is_polled_at_the_compiled_interval(self) -> None:
        scenario = _Scenario()
        scenario.ecs.descriptions = [
            task_entry(
                ACQ,
                status="PROVISIONING",
                attachment_status="PRECREATED",
                interface_id=None,
                subnet_id=None,
            ),
            task_entry(
                ACQ,
                status="PENDING",
                attachment_status="ATTACHING",
                interface_id=None,
                subnet_id=None,
            ),
            task_entry(ACQ, status="PENDING", attachment_status="ATTACHED"),
            task_entry(ACQ, status="STOPPED", attachment_status="ATTACHED", exit_code=0),
        ]
        report = scenario.run()
        assert report.outcome is LaunchOutcome.TASK_TERMINAL
        assert scenario.clock.sleeps[:2] == [pl.PLACEMENT_POLL_INTERVAL_SECONDS] * 2

    def test_the_report_and_its_parts_render_no_identifier(self) -> None:
        report = _Scenario().run()
        rendered = (
            repr(report)
            + repr(report.handle)
            + repr(report.counts)
            + launch_sentence(report.outcome)
        )
        for canary in CANARIES:
            assert canary not in rendered
        assert report.handle is not None and report.handle.task_arn == TASK_ARN


class TestPlacementFailure:
    @pytest.mark.parametrize(
        ("mutate", "incident"),
        [
            (
                lambda s: s.ecs.descriptions.__setitem__(
                    0, task_entry(ACQ, status="PENDING", revision=8)
                ),
                PlacementIncident.REVISION_MISMATCH,
            ),
            (
                lambda s: s.ecs.descriptions.__setitem__(
                    0, task_entry(ACQ, status="PENDING", subnet_id=OTHER_SUBNET_ID)
                ),
                PlacementIncident.SUBNET_MISMATCH,
            ),
            (
                lambda s: setattr(
                    s.ec2,
                    "interface",
                    interface_entry(subnet_id=OTHER_SUBNET_ID, public_ip="203.0.113.10"),
                ),
                PlacementIncident.SUBNET_MISMATCH,
            ),
            (
                lambda s: setattr(
                    s.ec2,
                    "interface",
                    interface_entry(
                        groups=(*SECURITY_GROUPS, OTHER_SECURITY_GROUP), public_ip="203.0.113.10"
                    ),
                ),
                PlacementIncident.SECURITY_GROUP_MISMATCH,
            ),
            (
                lambda s: setattr(
                    s.ec2,
                    "interface",
                    interface_entry(groups=SECURITY_GROUPS[:1], public_ip="203.0.113.10"),
                ),
                PlacementIncident.SECURITY_GROUP_MISMATCH,
            ),
            (
                lambda s: setattr(s.ec2, "interface", interface_entry(public_ip=None)),
                PlacementIncident.PUBLIC_IP_MISMATCH,
            ),
            (
                lambda s: setattr(s.ec2, "failure", "InvalidNetworkInterfaceID.NotFound"),
                PlacementIncident.INTERFACE_UNRESOLVED,
            ),
            (
                lambda s: s.ecs.descriptions.__setitem__(
                    0, task_entry(ACQ, status="PENDING", interface_id=None)
                ),
                PlacementIncident.INTERFACE_UNRESOLVED,
            ),
        ],
        ids=[
            "revision",
            "attachment-subnet",
            "interface-subnet",
            "extra-group",
            "missing-group",
            "public-ip",
            "eni-lookup",
            "eni-missing",
        ],
    )
    def test_each_mismatch_stops_this_task_and_writes_no_release(
        self, mutate: Any, incident: PlacementIncident
    ) -> None:
        scenario = _Scenario()
        mutate(scenario)
        report = scenario.run()
        assert report.outcome is LaunchOutcome.MISPLACED and report.incident is incident
        assert report.counts.stop_task == 1
        (stop,) = scenario.ecs.names("stop_task")
        assert stop["task"] == TASK_ARN and stop["cluster"] == scenario.compiled.cluster_arn
        assert stop["reason"] == pl.STOP_REASON_MISPLACED
        assert scenario.launcher_ssm.names("put_parameter") == []
        # The input is still cleaned up; there is no release to delete.
        assert scenario.human_ssm.names("delete_parameter") == [scenario.constants.input_parameter]
        assert scenario.launcher_ssm.names("delete_parameter") == []
        assert report.cleanup_failures == ()

    def test_a_build_task_with_a_public_ip_is_misplaced(self) -> None:
        scenario = _Scenario(BLD)
        scenario.ec2.interface = interface_entry(public_ip="203.0.113.10")
        report = scenario.run()
        assert (
            report.outcome is LaunchOutcome.MISPLACED
            and report.incident is PlacementIncident.PUBLIC_IP_MISMATCH
        )

    def test_a_task_that_never_attaches_is_stopped_at_the_placement_ceiling(self) -> None:
        scenario = _Scenario()
        scenario.ecs.descriptions = [
            task_entry(
                ACQ,
                status="PENDING",
                attachment_status="ATTACHING",
                interface_id=None,
                subnet_id=None,
            )
        ]
        report = scenario.run()
        assert report.outcome is LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED
        assert report.counts.stop_task == 1 and scenario.launcher_ssm.names("put_parameter") == []
        assert scenario.clock.seconds <= pl.PLACEMENT_CEILING_SECONDS

    def test_a_task_stopped_before_attaching_is_reported_unverified(self) -> None:
        scenario = _Scenario()
        scenario.ecs.descriptions = [
            task_entry(
                ACQ,
                status="STOPPED",
                attachment_status="PRECREATED",
                interface_id=None,
                subnet_id=None,
                exit_code=1,
            )
        ]
        report = scenario.run()
        assert report.outcome is LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED
        assert report.counts.stop_task == 0 and report.task_exit_codes == (1,)

    def test_a_task_already_terminal_after_verification_gets_no_release(self) -> None:
        scenario = _Scenario()
        scenario.ecs.descriptions = [
            task_entry(ACQ, status="STOPPED", attachment_status="ATTACHED", exit_code=3)
        ]
        report = scenario.run()
        assert report.outcome is LaunchOutcome.TASK_TERMINAL and report.task_exit_codes == (3,)
        assert scenario.launcher_ssm.names("put_parameter") == []


class TestCreateOnlyConflicts:
    def test_an_existing_input_refuses_before_any_launch(self) -> None:
        scenario = _Scenario()
        scenario.human_ssm.values[scenario.constants.input_parameter] = b"leftover"
        report = scenario.run()
        assert report.outcome is LaunchOutcome.REFUSED_INPUT_EXISTS
        assert not report.task_started and scenario.ecs.calls == []
        # The leftover is not ours to delete: no cleanup on a parameter this run did not create.
        assert scenario.human_ssm.names("delete_parameter") == []
        assert scenario.human_ssm.values[scenario.constants.input_parameter] == b"leftover"

    def test_an_existing_release_stops_this_task_and_cleans_up_the_input(self) -> None:
        scenario = _Scenario()
        scenario.launcher_ssm.values[scenario.constants.release_parameter] = b"leftover"
        report = scenario.run()
        assert report.outcome is LaunchOutcome.REFUSED_RELEASE_EXISTS
        assert report.counts.stop_task == 1
        (stop,) = scenario.ecs.names("stop_task")
        assert stop["reason"] == pl.STOP_REASON_RELEASE_EXISTS
        assert scenario.launcher_ssm.names("delete_parameter") == []
        assert scenario.human_ssm.names("delete_parameter") == [scenario.constants.input_parameter]

    def test_the_channels_never_overwrite(self) -> None:
        scenario = _Scenario()
        scenario.run()
        for ssm in (scenario.human_ssm, scenario.launcher_ssm):
            for name, kwargs in ssm.calls:
                if name == "put_parameter":
                    assert kwargs["Overwrite"] is False


class TestPartialFailures:
    def test_a_refused_human_identity_stops_before_the_input(self) -> None:
        scenario = _Scenario()
        scenario.refuse = {IdentityPath.HUMAN}
        report = scenario.run()
        assert report.outcome is LaunchOutcome.REFUSED_IDENTITY
        assert scenario.human_ssm.calls == [] and scenario.ecs.calls == []

    def test_a_refused_launcher_identity_stops_before_the_launch_and_cleans_up_the_input(
        self,
    ) -> None:
        scenario = _Scenario()
        scenario.refuse = {IdentityPath.LAUNCHER}
        report = scenario.run()
        assert report.outcome is LaunchOutcome.REFUSED_IDENTITY
        assert scenario.ecs.calls == []
        assert scenario.human_ssm.names("delete_parameter") == [scenario.constants.input_parameter]
        assert report.cleanup_failures == ()

    def test_a_launch_refusal_cleans_up_the_input(self) -> None:
        scenario = _Scenario()
        scenario.ecs.run_failure = "AccessDeniedException"
        report = scenario.run()
        assert report.outcome is LaunchOutcome.REFUSED_LAUNCH and not report.task_started
        assert scenario.human_ssm.names("delete_parameter") == [scenario.constants.input_parameter]

    def test_a_run_task_response_with_a_failure_entry_is_a_refusal(self) -> None:
        scenario = _Scenario()
        scenario.ecs.run_response = {
            "tasks": [],
            "failures": [{"arn": "x", "reason": "RESOURCE:MEMORY"}],
        }
        assert scenario.run().outcome is LaunchOutcome.REFUSED_LAUNCH

    def test_a_run_task_response_naming_another_cluster_is_a_refusal(self) -> None:
        scenario = _Scenario()
        scenario.ecs.run_response = {
            "tasks": [
                task_entry(
                    ACQ,
                    status="PROVISIONING",
                    task_arn=TASK_ARN.replace("synthetic-research-cluster", "other-cluster"),
                )
            ],
            "failures": [],
        }
        assert scenario.run().outcome is LaunchOutcome.REFUSED_LAUNCH

    def test_an_observation_failure_still_cleans_up_both_parameters(self) -> None:
        scenario = _Scenario()
        scenario.ecs.descriptions = [
            task_entry(ACQ, status="PENDING", attachment_status="ATTACHED")
        ]
        calls = {"n": 0}
        original = scenario.ecs.describe_tasks

        def flaky(**kwargs: Any) -> dict[str, Any]:
            calls["n"] += 1
            if calls["n"] >= 2:
                scenario.ecs.describe_failure = "ServerException"
            return original(**kwargs)

        scenario.ecs.describe_tasks = flaky  # type: ignore[method-assign]
        report = scenario.run()
        assert report.outcome is LaunchOutcome.OBSERVATION_FAILED
        assert scenario.launcher_ssm.names("delete_parameter") == [
            scenario.constants.release_parameter
        ]
        assert scenario.human_ssm.names("delete_parameter") == [scenario.constants.input_parameter]

    def test_an_observation_timeout_is_reported_and_cleaned_up(self) -> None:
        scenario = _Scenario()
        scenario.ecs.descriptions = [
            task_entry(ACQ, status="RUNNING", attachment_status="ATTACHED")
        ]
        report = scenario.run()
        assert report.outcome is LaunchOutcome.OBSERVATION_TIMEOUT
        assert report.counts.stop_task == 0  # a slow task is not a misplaced task
        assert (
            scenario.clock.seconds <= pl.OBSERVE_CEILING_SECONDS + pl.OBSERVE_POLL_INTERVAL_SECONDS
        )
        assert scenario.launcher_ssm.names("delete_parameter") == [
            scenario.constants.release_parameter
        ]


class TestCleanupFailures:
    def test_a_failed_release_delete_is_reported_beside_the_primary_outcome(self) -> None:
        scenario = _Scenario()
        scenario.launcher_ssm.delete_failures[scenario.constants.release_parameter] = (
            "AccessDeniedException"
        )
        report = scenario.run()
        assert report.outcome is LaunchOutcome.TASK_TERMINAL
        assert report.cleanup_failures == (
            CleanupFailure(
                stage=CleanupStage.DELETE_RELEASE, failure=ParameterFailure.ACCESS_DENIED
            ),
        )
        # The input delete still ran.
        assert scenario.human_ssm.names("delete_parameter") == [scenario.constants.input_parameter]

    def test_a_failed_input_delete_after_a_misplacement_preserves_the_incident(self) -> None:
        scenario = _Scenario()
        scenario.ec2.interface = interface_entry(public_ip=None)
        scenario.human_ssm.delete_failures[scenario.constants.input_parameter] = (
            "ThrottlingException"
        )
        report = scenario.run()
        assert report.outcome is LaunchOutcome.MISPLACED
        assert report.incident is PlacementIncident.PUBLIC_IP_MISMATCH
        assert report.cleanup_failures == (
            CleanupFailure(stage=CleanupStage.DELETE_INPUT, failure=ParameterFailure.THROTTLED),
        )

    def test_a_failed_stop_is_reported_and_the_run_is_still_misplaced(self) -> None:
        scenario = _Scenario()
        scenario.ec2.interface = interface_entry(public_ip=None)
        scenario.ecs.stop_failure = "ServerException"
        report = scenario.run()
        assert report.outcome is LaunchOutcome.MISPLACED
        assert report.cleanup_failures == (
            CleanupFailure(stage=CleanupStage.STOP_TASK, failure="TRANSIENT"),
        )

    def test_a_refused_identity_at_cleanup_is_a_cleanup_failure_not_a_new_outcome(self) -> None:
        scenario = _Scenario()
        scenario.refuse_after = 2  # the two proofs before work pass; the two before cleanup refuse
        report = scenario.run()
        assert report.outcome is LaunchOutcome.TASK_TERMINAL
        assert [failure.stage for failure in report.cleanup_failures] == [
            CleanupStage.DELETE_RELEASE,
            CleanupStage.DELETE_INPUT,
        ]
        assert all(failure.failure == "IDENTITY_REFUSED" for failure in report.cleanup_failures)
        assert (
            scenario.launcher_ssm.names("delete_parameter") == []
            and scenario.human_ssm.names("delete_parameter") == []
        )


class TestOwnTaskOnly:
    def test_the_sequence_stops_only_the_task_it_started(self) -> None:
        scenario = _Scenario()
        scenario.ecs.run_response = {
            "tasks": [
                task_entry(
                    ACQ, status="PROVISIONING", task_arn=OTHER_TASK_ARN, attachment_status=None
                )
            ],
            "failures": [],
        }
        scenario.ecs.descriptions = [
            task_entry(ACQ, status="PENDING", task_arn=OTHER_TASK_ARN, subnet_id=OTHER_SUBNET_ID)
        ]
        report = scenario.run()
        assert report.outcome is LaunchOutcome.MISPLACED
        (stop,) = scenario.ecs.names("stop_task")
        assert (
            stop["task"] == OTHER_TASK_ARN
            and report.handle is not None
            and report.handle.task_arn == OTHER_TASK_ARN
        )
        for kwargs in scenario.ecs.names("describe_tasks"):
            assert kwargs["tasks"] == [OTHER_TASK_ARN]

    def test_a_description_naming_a_different_task_is_refused(self) -> None:
        scenario = _Scenario()
        scenario.ecs.descriptions = [task_entry(ACQ, status="PENDING", task_arn=OTHER_TASK_ARN)]
        report = scenario.run()
        assert report.outcome is LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED


class TestCompiledLaunch:
    def test_a_compiled_launch_refuses_to_contradict_its_actor(self) -> None:
        with pytest.raises(ValueError, match="public-IP"):
            compiled_launch(BLD, assign_public_ip=True)
        with pytest.raises(ValueError, match="family"):
            compiled_launch(ACQ, task_definition_arn=revision_arn(BLD))
        with pytest.raises(ValueError, match="task role"):
            compiled_launch(
                ACQ,
                task_role_arn=f"arn:aws:iam::000000000000:role/{constants_for(BLD).task_role_name}",
            )
        with pytest.raises(ValueError, match="pinned"):
            compiled_launch(ACQ, platform_version="LATEST")
        with pytest.raises(ValueError, match="account"):
            compiled_launch(ACQ, execution_role_arn="arn:aws:iam::999999999999:role/exec")
        with pytest.raises(ValueError, match="binding key"):
            compiled_launch(ACQ, binding_key_arn="not-a-key")

    def test_a_compiled_launch_renders_no_identifier(self) -> None:
        rendered = repr(compiled_launch(ACQ))
        for canary in CANARIES:
            assert canary not in rendered
        assert KEY_ARN not in rendered

    def test_the_adapters_classify_structurally_and_carry_no_message(self) -> None:
        ecs = FakeEcs(run_failure="ClusterNotFoundException")
        adapter = pc.EcsTaskAdapter(ecs=ecs, compiled=compiled_launch(ACQ))
        with pytest.raises(pc.ComputeError) as info:
            adapter.run_task()
        assert info.value.failure is pc.ComputeFailure.NOT_FOUND and info.value.__cause__ is None
        assert "synthetic backend message" not in str(info.value)
        assert pc.classify_compute_failure(RuntimeError()) is pc.ComputeFailure.UNKNOWN
