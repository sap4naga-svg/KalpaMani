"""Behavioural tests: the task-side and human-side bootstrap sequences, end to end on fakes.

The success path halts honestly at ``HALTED_PROCESSING_NOT_IMPLEMENTED``; every
refusal stage is reached by name; the binding-before-identity order is proved by
counting; and no data-plane operation exists on any path.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_runtime import (
    BUILD_ID,
    CANARIES,
    INTERFACE_ID,
    NOW,
    OTHER_PLAN_DIGEST,
    OTHER_RUN_ID,
    OTHER_TASK_ARN,
    PLAN_DIGEST,
    RUN_ID,
    SUBNET_ID,
    TASK_ARN,
    FakeClock,
    FakeSsm,
    acquisition_input_document,
    binding_document,
    build_input_document,
    caller_identity,
    compiled_task,
    encode,
    human_identity_arn,
    launcher_identity_arn,
    metadata_document,
    revision_arn,
    task_identity_arn,
)
from kalpamani.data.production.sharadar import outcomes as po
from kalpamani.data.production.sharadar import runner as prun
from kalpamani.data.production.sharadar.barrier import MAX_RELEASE_READS, BarrierOutcome
from kalpamani.data.production.sharadar.inputs import input_digest
from kalpamani.data.production.sharadar.parameters import SsmParameterAdapter
from kalpamani.data.production.sharadar.release import ReleaseDefect, build_release_document
from kalpamani.data.production.sharadar.vocabulary import (
    IdentityPath,
    ProductionActor,
    constants_for,
)
from kalpamani.data.qualify.sharadar import runtime_binding as rb

ACQ: Final = ProductionActor.ACQUISITION
BLD: Final = ProductionActor.BUILD


class _Task:
    """One task-side scenario: a parameter store, metadata, an identity, a clock."""

    def __init__(self, actor: ProductionActor = ACQ, *, release: bool = True) -> None:
        self.actor = actor
        constants = constants_for(actor)
        self.ssm = FakeSsm()
        self.ssm.values[constants.binding_parameter] = encode(binding_document(actor))
        document = acquisition_input_document() if actor is ACQ else build_input_document()
        self.input_bytes = encode(document)
        self.ssm.values[constants.input_parameter] = self.input_bytes
        self.clock = FakeClock()
        self.identity_calls = 0
        self.environment = ["PATH", "ECS_CONTAINER_METADATA_URI_V4"]
        self.metadata: object = metadata_document(actor)
        self.identity_arn = task_identity_arn(actor)
        if release:
            self.write_release()

    def write_release(self, **overrides: Any) -> None:
        fields: dict[str, Any] = {
            "actor": self.actor,
            "task_arn": TASK_ARN,
            "task_definition_arn": revision_arn(self.actor),
            "identity": RUN_ID if self.actor is ACQ else BUILD_ID,
            "input_digest": input_digest(self.input_bytes),
            "network_interface_id": INTERFACE_ID,
            "subnet_id": SUBNET_ID,
            "verified_at": NOW - timedelta(seconds=10),
        }
        fields.update(overrides)
        self.ssm.values[constants_for(self.actor).release_parameter] = build_release_document(
            **fields
        )

    def caller(self) -> dict[str, str]:
        self.identity_calls += 1
        return caller_identity(self.identity_arn)

    def adapters(self) -> prun.RunnerAdapters:
        return prun.RunnerAdapters(
            environment_names=lambda: list(self.environment),
            parameters=SsmParameterAdapter(ssm=self.ssm),
            metadata=lambda: self.metadata,
            caller_identity=self.caller,
            now=self.clock.now,
            monotonic=self.clock.monotonic,
            sleep=self.clock.sleep,
        )

    def run(self, **kwargs: Any) -> prun.RunnerReport:
        defaults: dict[str, Any] = {
            "actor": self.actor,
            "compiled": compiled_task(self.actor),
            "adapters": self.adapters(),
            "expected_plan_digest": PLAN_DIGEST,
            "is_spent": lambda _: False,
        }
        defaults.update(kwargs)
        return prun.run_task_bootstrap(**defaults)


class TestTheTaskSequence:
    @pytest.mark.parametrize("actor", (ACQ, BLD), ids=lambda a: a.value)
    def test_the_success_path_halts_honestly_after_the_barrier(
        self, actor: ProductionActor
    ) -> None:
        task = _Task(actor)
        report = task.run()
        assert report.outcome is po.RunnerOutcome.HALTED_PROCESSING_NOT_IMPLEMENTED
        assert report.stage is prun.RunnerStage.PROCESSING
        assert report.barrier is not None and report.barrier.outcome is BarrierOutcome.RELEASED
        counts = report.counts
        assert counts.parameter_reads == 3 and counts.identity_calls == 1
        assert counts.s3_operations == counts.secret_retrievals == counts.provider_requests == 0
        constants = constants_for(actor)
        assert task.ssm.names("get_parameter") == [
            constants.binding_parameter,
            constants.input_parameter,
            constants.release_parameter,
        ]
        rendered = (
            repr(report) + po.runner_sentence(report.outcome) + " ".join(po.count_lines(counts))
        )
        for canary in CANARIES:
            assert canary not in rendered

    def test_a_private_environment_variable_refuses_before_any_read(self) -> None:
        task = _Task()
        task.environment.append("KALPAMANI_PRODUCTION_ACQUISITION_RUNTIME_BINDING_FILE")
        report = task.run()
        assert report.outcome is po.RunnerOutcome.REFUSED_ENVIRONMENT
        assert task.ssm.calls == [] and task.identity_calls == 0

    def test_a_bad_binding_refuses_before_the_input_and_before_identity(self) -> None:
        task = _Task()
        task.ssm.values[constants_for(ACQ).binding_parameter] = encode(binding_document(BLD))
        report = task.run()
        assert (
            report.outcome is po.RunnerOutcome.REFUSED_BINDING
            and report.stage is prun.RunnerStage.BINDING
        )
        assert task.ssm.names("get_parameter") == [constants_for(ACQ).binding_parameter]
        assert task.identity_calls == 0

    def test_a_missing_binding_parameter_refuses(self) -> None:
        task = _Task()
        del task.ssm.values[constants_for(ACQ).binding_parameter]
        assert task.run().outcome is po.RunnerOutcome.REFUSED_BINDING

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"expected_plan_digest": OTHER_PLAN_DIGEST},
            {"expected_plan_digest": None},
            {"is_spent": lambda _: True},
        ],
        ids=["plan-digest", "no-compiled-plan", "spent"],
    )
    def test_an_input_the_contract_refuses_stops_before_the_self_check(
        self, kwargs: dict[str, Any]
    ) -> None:
        task = _Task()
        report = task.run(**kwargs)
        assert (
            report.outcome is po.RunnerOutcome.REFUSED_INPUT
            and report.stage is prun.RunnerStage.INPUT
        )
        assert task.identity_calls == 0
        assert len(task.ssm.names("get_parameter")) == 2

    def test_an_expired_input_refuses(self) -> None:
        task = _Task()
        task.clock.seconds = 0
        task.ssm.values[constants_for(ACQ).input_parameter] = encode(
            acquisition_input_document(
                issued_at=(NOW - timedelta(hours=3)).isoformat(),
                expires_at=(NOW - timedelta(hours=1)).isoformat(),
            )
        )
        assert task.run().outcome is po.RunnerOutcome.REFUSED_INPUT

    def test_a_partial_bootstrap_failure_on_the_input_read_is_a_refusal(self) -> None:
        task = _Task()
        task.ssm.get_failures[constants_for(ACQ).input_parameter] = "AccessDeniedException"
        report = task.run()
        assert report.outcome is po.RunnerOutcome.REFUSED_INPUT and task.identity_calls == 0

    @pytest.mark.parametrize(
        "metadata",
        [
            None,
            {"TaskARN": TASK_ARN},
            metadata_document(ACQ, Revision="8"),
            metadata_document(ACQ, Family=constants_for(BLD).task_family),
            metadata_document(ACQ, Containers=[{"ImageID": "sha256:" + "00" * 32}]),
        ],
        ids=["absent", "partial", "revision", "family", "image"],
    )
    def test_a_failed_self_check_refuses_before_identity(self, metadata: object) -> None:
        task = _Task()
        task.metadata = metadata
        report = task.run()
        assert report.outcome is po.RunnerOutcome.REFUSED_SELF_CHECK
        assert task.identity_calls == 0

    def test_a_raising_metadata_source_refuses(self) -> None:
        task = _Task()

        def raising() -> object:
            raise RuntimeError("metadata endpoint unreachable")

        adapters = task.adapters()
        adapters = prun.RunnerAdapters(
            environment_names=adapters.environment_names,
            parameters=adapters.parameters,
            metadata=raising,
            caller_identity=adapters.caller_identity,
            now=adapters.now,
            monotonic=adapters.monotonic,
            sleep=adapters.sleep,
        )
        assert task.run(adapters=adapters).outcome is po.RunnerOutcome.REFUSED_SELF_CHECK

    @pytest.mark.parametrize(
        "arn",
        [
            task_identity_arn(BLD),
            human_identity_arn(ACQ),
            launcher_identity_arn(ACQ),
            task_identity_arn(ACQ, task_id="fedcba9876543210fedcba9876543210"),
        ],
        ids=["other-actor", "human", "launcher", "other-task-id"],
    )
    def test_a_wrong_identity_refuses_before_the_barrier(self, arn: str) -> None:
        task = _Task()
        task.identity_arn = arn
        report = task.run()
        assert (
            report.outcome is po.RunnerOutcome.REFUSED_IDENTITY
            and report.stage is prun.RunnerStage.IDENTITY
        )
        assert task.identity_calls == 1
        assert constants_for(ACQ).release_parameter not in task.ssm.names("get_parameter")

    def test_the_binding_precedes_identity_and_identity_precedes_the_barrier(self) -> None:
        task = _Task()
        order: list[str] = []
        original_get = task.ssm.get_parameter

        def recording_get(**kwargs: Any) -> dict[str, Any]:
            order.append(kwargs["Name"].rsplit("/", 1)[1])
            return original_get(**kwargs)

        task.ssm.get_parameter = recording_get  # type: ignore[method-assign]
        original_caller = task.caller

        def recording_caller() -> dict[str, str]:
            order.append("sts")
            return original_caller()

        task.caller = recording_caller  # type: ignore[method-assign]
        task.run()
        assert order == ["runtime-binding", "input", "sts", "release"]

    def test_no_release_refuses_after_the_bounded_wait_with_zero_data_operations(self) -> None:
        task = _Task(release=False)
        report = task.run()
        assert report.outcome is po.RunnerOutcome.REFUSED_NO_RELEASE
        assert report.barrier is not None and report.barrier.reads == MAX_RELEASE_READS
        assert report.counts.parameter_reads == 2 + MAX_RELEASE_READS
        assert report.counts.data_plane_operations == 0

    @pytest.mark.parametrize(
        ("overrides", "defect"),
        [
            ({"task_arn": OTHER_TASK_ARN}, ReleaseDefect.TASK_MISMATCH),
            ({"task_definition_arn": revision_arn(ACQ, 8)}, ReleaseDefect.REVISION_MISMATCH),
            ({"identity": OTHER_RUN_ID}, ReleaseDefect.IDENTITY_MISMATCH),
            ({"input_digest": OTHER_PLAN_DIGEST}, ReleaseDefect.INPUT_DIGEST_MISMATCH),
            ({"verified_at": NOW - timedelta(minutes=30)}, ReleaseDefect.EXPIRED),
        ],
        ids=["task", "revision", "identity", "input-digest", "stale"],
    )
    def test_every_release_mismatch_refuses_the_run(
        self, overrides: dict[str, Any], defect: ReleaseDefect
    ) -> None:
        task = _Task(release=False)
        task.write_release(**overrides)
        report = task.run()
        assert report.outcome is po.RunnerOutcome.REFUSED_RELEASE_MISMATCH
        assert report.barrier is not None and report.barrier.defect is defect
        assert report.counts.data_plane_operations == 0

    def test_the_other_actors_release_is_a_mismatch(self) -> None:
        task = _Task(release=False)
        other = _Task(BLD)
        task.ssm.values[constants_for(ACQ).release_parameter] = other.ssm.values[
            constants_for(BLD).release_parameter
        ]
        report = task.run()
        assert report.outcome is po.RunnerOutcome.REFUSED_RELEASE_MISMATCH

    def test_a_release_read_failure_refuses_at_once(self) -> None:
        task = _Task()
        task.ssm.get_failures[constants_for(ACQ).release_parameter] = "AccessDeniedException"
        report = task.run()
        assert report.outcome is po.RunnerOutcome.REFUSED_RELEASE_READ
        assert report.counts.parameter_reads == 3

    def test_a_digest_over_re_serialized_bytes_does_not_release(self) -> None:
        """The release binds the delivered bytes; equal JSON with other bytes mismatches."""
        task = _Task(release=False)
        import json

        loose = json.dumps(acquisition_input_document(), indent=2).encode("utf-8")
        task.write_release(input_digest=input_digest(loose))
        report = task.run()
        assert report.outcome is po.RunnerOutcome.REFUSED_RELEASE_MISMATCH
        assert (
            report.barrier is not None
            and report.barrier.defect is ReleaseDefect.INPUT_DIGEST_MISMATCH
        )

    def test_a_report_cannot_claim_a_data_plane_operation(self) -> None:
        with pytest.raises(ValueError, match="zero"):
            prun.RunnerReport(
                outcome=po.RunnerOutcome.HALTED_PROCESSING_NOT_IMPLEMENTED,
                stage=prun.RunnerStage.PROCESSING,
                counts=po.OperationCounts(s3_operations=1),
                barrier=None,
            )

    def test_the_compiled_task_must_be_this_actors(self) -> None:
        with pytest.raises(ValueError, match="actor"):
            _Task().run(compiled=compiled_task(BLD))


class TestTheHumanSequence:
    CURRENT: Final = "S-1-5-21-0-0-0-1001"

    def _environment(
        self, tmp_path: Path, actor: ProductionActor, document: dict[str, Any] | None = None
    ) -> tuple[Any, Path]:
        root = tmp_path / "KalpaMani" / "private"
        root.mkdir(parents=True, exist_ok=True)
        target = root / "binding.json"
        target.write_bytes(encode(binding_document(actor) if document is None else document))
        return {constants_for(actor).binding_env_var: str(target)}.get, root

    def _security(self) -> rb.FileSecurity:
        return rb.FileSecurity(
            current_principal=self.CURRENT,
            owner=self.CURRENT,
            inheritance_disabled=True,
            allow_principals=(self.CURRENT,),
            deny_principals=(),
        )

    @pytest.mark.parametrize("actor", (ACQ, BLD), ids=lambda a: a.value)
    @pytest.mark.parametrize(
        "path", (IdentityPath.HUMAN, IdentityPath.LAUNCHER), ids=lambda p: p.value
    )
    def test_a_human_or_launcher_proves_identity_under_its_own_path(
        self, tmp_path: Path, actor: ProductionActor, path: IdentityPath
    ) -> None:
        environment, root = self._environment(tmp_path, actor)
        arn = (
            human_identity_arn(actor)
            if path is IdentityPath.HUMAN
            else launcher_identity_arn(actor)
        )
        report = prun.human_bootstrap(
            actor=actor,
            path=path,
            environment=environment,
            caller_identity=lambda: caller_identity(arn),
            root_source=lambda: root,
            security_of=lambda _p: self._security(),
        )
        assert report.outcome is prun.HumanBootstrapOutcome.IDENTITY_PROVEN
        assert report.binding is not None and report.binding.actor is actor
        for canary in CANARIES:
            assert canary not in repr(report)

    def test_a_refused_binding_makes_no_identity_call(self, tmp_path: Path) -> None:
        environment, root = self._environment(tmp_path, ACQ, binding_document(BLD))
        calls: list[int] = []

        def identity() -> dict[str, str]:
            calls.append(1)
            return caller_identity(human_identity_arn(ACQ))

        report = prun.human_bootstrap(
            actor=ACQ,
            path=IdentityPath.HUMAN,
            environment=environment,
            caller_identity=identity,
            root_source=lambda: root,
            security_of=lambda _p: self._security(),
        )
        assert report.outcome is prun.HumanBootstrapOutcome.REFUSED_BINDING and calls == []

    def test_the_wrong_path_refuses(self, tmp_path: Path) -> None:
        environment, root = self._environment(tmp_path, ACQ)
        report = prun.human_bootstrap(
            actor=ACQ,
            path=IdentityPath.LAUNCHER,
            environment=environment,
            caller_identity=lambda: caller_identity(human_identity_arn(ACQ)),
            root_source=lambda: root,
            security_of=lambda _p: self._security(),
        )
        assert (
            report.outcome is prun.HumanBootstrapOutcome.REFUSED_IDENTITY and report.binding is None
        )

    def test_a_human_never_proves_a_task_identity(self, tmp_path: Path) -> None:
        environment, root = self._environment(tmp_path, ACQ)
        with pytest.raises(ValueError, match="task identity"):
            prun.human_bootstrap(
                actor=ACQ,
                path=IdentityPath.TASK,
                environment=environment,
                caller_identity=lambda: caller_identity(task_identity_arn(ACQ)),
                root_source=lambda: root,
            )


class TestOutcomes:
    def test_every_outcome_has_exactly_one_allowlisted_sentence(self) -> None:
        assert set(po.RUNNER_SENTENCES) == set(po.RunnerOutcome)
        assert set(po.LAUNCH_SENTENCES) == set(po.LaunchOutcome)
        forbidden = {
            "ready",
            "approved",
            "authorized",
            "proceed",
            "qualified",
            "completed",
            "bound",
        }
        for sentence in (*po.RUNNER_SENTENCES.values(), *po.LAUNCH_SENTENCES.values()):
            words = {word.strip(":;,.") for word in sentence.lower().split()}
            assert not words & forbidden, sentence

    def test_counts_are_integers_only(self) -> None:
        with pytest.raises(TypeError):
            po.OperationCounts(run_task=True)
        with pytest.raises(TypeError):
            po.OperationCounts(parameter_reads=-1)
        assert po.count_lines(po.OperationCounts(run_task=1))[3] == "run_task=1"

    def test_sentences_are_looked_up_by_exact_member_only(self) -> None:
        with pytest.raises(TypeError):
            po.runner_sentence("REFUSED_BINDING")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            po.launch_sentence("MISPLACED")  # type: ignore[arg-type]
