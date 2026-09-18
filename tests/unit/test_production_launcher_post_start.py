"""ADR-0045 s.15: bounded read-only re-polling, sanitized poll evidence and the post-start
stop invariant of the launch sequence -- on fakes only.

Motivated by two production launches of 2026-09-18 refused at the fourth ``DescribeTasks``
inside the image-digest wait after placement was verified; both recorded signatures are
reproduced here as fixtures (the historical evidence itself is untouched). Every scenario
proves: one ``RunTask`` and never a second; a verified state only from a valid response;
the ceiling never extended; the stop invariant once the task was accepted; the refusal
preserved beside the stop and the cleanup; and nothing sensitive in any report or document.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_runtime import (
    CANARIES,
    INTERFACE_ID,
    TASK_ARN,
    FakeClientError,
    FakeClock,
    FakeEc2,
    FakeEcs,
    FakeSsm,
    acquisition_input_document,
    compiled_launch,
    encode,
    interface_entry,
    task_entry,
)
from kalpamani.data.contracts.canonical import canonical_bytes
from kalpamani.data.production.sharadar import compute as pc
from kalpamani.data.production.sharadar import launch_records as lr
from kalpamani.data.production.sharadar import launcher as pl
from kalpamani.data.production.sharadar.outcomes import CleanupStage, LaunchOutcome
from kalpamani.data.production.sharadar.parameters import SsmParameterAdapter
from kalpamani.data.production.sharadar.poll_evidence import (
    PollClass,
    PollDiagnostic,
    PollDisposition,
    PollPhase,
    StopOutcome,
    poll_class_of,
)
from kalpamani.data.production.sharadar.vocabulary import IdentityPath, ProductionActor

ACQ: Final = ProductionActor.ACQUISITION
ROOT: Final = Path(__file__).resolve().parents[2]
PRODUCTION: Final = ROOT / "src" / "kalpamani" / "data" / "production" / "sharadar"
ADR: Final = (
    ROOT
    / "docs"
    / "decisions"
    / ("ADR-0045-verification-entries-observation-build-and-launch-tool.md")
)
RUN_ID: Final = "synthetic-production-run-0001"
#: Text a backend exception might carry. It must never reach a report or a document.
LEAK: Final = (
    "connect timeout on endpoint https://ecs.us-east-1.amazonaws.com for "
    f"{TASK_ARN} interface {INTERFACE_ID} account 000000000000 request-id 0123456789ab"
)


class ConnectTimeoutError(Exception):  # mirrors the botocore class name
    """A botocore-shaped transport failure: no ``response``, only a message."""


class ReadTimeoutError(Exception):  # mirrors the botocore class name
    """A botocore-shaped transport failure: no ``response``, only a message."""


class ScriptedEcs(FakeEcs):
    """A ``FakeEcs`` whose ``describe_tasks`` follows a per-call script.

    ``script[i]`` is ``None`` for a normal description, a service error code string for a
    ``FakeClientError`` carrying it, or an exception instance to raise as is.
    """

    def __init__(self, *, run_response: dict[str, Any], descriptions: list[dict[str, Any]]) -> None:
        super().__init__(run_response=run_response, descriptions=list(descriptions))
        self.script: list[str | BaseException | None] = []

    def describe_tasks(self, **kwargs: Any) -> dict[str, Any]:
        if self.script:
            step = self.script.pop(0)
            if step is not None:
                self.calls.append(("describe_tasks", kwargs))
                if isinstance(step, BaseException):
                    raise step
                raise FakeClientError(step)
        return super().describe_tasks(**kwargs)


def _accepted_run_response() -> dict[str, Any]:
    return {
        "tasks": [
            task_entry(
                ACQ,
                status="PROVISIONING",
                attachment_status="PRECREATED",
                interface_id=None,
                subnet_id=None,
            )
        ],
        "failures": [],
    }


#: The description sequence the two 2026-09-18 launches saw before the failed poll: two
#: pre-attachment polls, one ATTACHED poll with the image digest still unresolved (the
#: window before ECS has pulled the image), then the image-wait poll that failed.
def _run14_descriptions() -> list[dict[str, Any]]:
    return [
        task_entry(
            ACQ, status="PENDING", attachment_status="ATTACHING", interface_id=None, subnet_id=None
        ),
        task_entry(
            ACQ, status="PENDING", attachment_status="ATTACHING", interface_id=None, subnet_id=None
        ),
        task_entry(ACQ, status="PENDING", attachment_status="ATTACHED", image_digest=None),
        task_entry(ACQ, status="RUNNING", attachment_status="ATTACHED"),
        task_entry(ACQ, status="STOPPED", attachment_status="ATTACHED", exit_code=0),
    ]


#: The recorded launcher signature of both halted attempts (evidence documents
#: ``…f4fbdf2d`` and ``…4f797fd4``): what the tool observed, with no stop on that path.
RUN14_SIGNATURE: Final = {
    "outcome": LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED,
    "run_task": 1,
    "describe_tasks": 4,
    "describe_network_interfaces": 1,
    "stop_task_before": 0,
    "incident": None,
    "exit_codes": (),
    "task_started": True,
}


class Scenario:
    """One launch over scripted fakes: the run-14 description sequence by default."""

    def __init__(self, descriptions: list[dict[str, Any]] | None = None) -> None:
        self.compiled = compiled_launch(ACQ)
        self.ecs = ScriptedEcs(
            run_response=_accepted_run_response(),
            descriptions=descriptions if descriptions is not None else _run14_descriptions(),
        )
        self.ec2 = FakeEc2(interface=interface_entry(public_ip="203.0.113.10"))
        self.human_ssm = FakeSsm()
        self.launcher_ssm = FakeSsm()
        self.clock = FakeClock()
        self.proofs: list[IdentityPath] = []
        self.authorization = pl.LaunchAuthorization(
            identity=RUN_ID, input_bytes=encode(acquisition_input_document())
        )

    def proof(self, path: IdentityPath) -> str | None:
        self.proofs.append(path)
        return None

    def run(self) -> pl.LaunchReport:
        return pl.launch_authorized_run(
            compiled=self.compiled,
            adapters=pl.LaunchAdapters(
                ecs=pc.EcsTaskAdapter(ecs=self.ecs, compiled=self.compiled),
                ec2=pc.Ec2InterfaceAdapter(ec2=self.ec2),
                human_parameters=SsmParameterAdapter(ssm=self.human_ssm),
                launcher_parameters=SsmParameterAdapter(ssm=self.launcher_ssm),
            ),
            authorization=self.authorization,
            identity_proof=self.proof,
            now=self.clock.now,
            monotonic=self.clock.monotonic,
            sleep=self.clock.sleep,
        )

    def calls(self, operation: str) -> list[dict[str, Any]]:
        return [kwargs for name, kwargs in self.ecs.calls if name == operation]

    def evidence(self, report: pl.LaunchReport) -> dict[str, Any]:
        """The evidence document the launch tool would write for this report."""
        return lr.evidence_document(
            actor=ACQ,
            kind=lr.LaunchKind.PRODUCTION,
            outcome=report.outcome.value,
            counts={
                "run_task": report.counts.run_task,
                "describe_tasks": report.counts.describe_tasks,
                "describe_network_interfaces": report.counts.describe_network_interfaces,
                "stop_task": report.counts.stop_task,
                "parameter_creates": report.counts.parameter_creates,
                "parameter_deletes": report.counts.parameter_deletes,
                "parameter_reads": report.counts.parameter_reads,
                "identity_calls": report.counts.identity_calls,
            },
            incident=None if report.incident is None else report.incident.value,
            cleanup_failures=[f"{f.stage.value}:{f.failure}" for f in report.cleanup_failures],
            task_started=report.task_started,
            exit_codes=list(report.task_exit_codes),
            recorded_at=self.clock.now(),
            diagnostics=[entry.document() for entry in report.diagnostics],
            stop_outcome=report.stop_outcome.value,
        )


def _assert_common_invariants(s: Scenario, report: pl.LaunchReport) -> None:
    """What holds in every scenario after RunTask accepted the task."""
    assert report.counts.run_task == 1 and len(s.calls("run_task")) == 1  # never a second RunTask
    for kwargs in s.calls("describe_tasks"):
        assert kwargs["tasks"] == [TASK_ARN]
    for kwargs in s.calls("stop_task"):
        assert kwargs["task"] == TASK_ARN and kwargs["cluster"] == s.compiled.cluster_arn
    assert report.counts.describe_tasks == len(s.calls("describe_tasks"))
    assert report.counts.stop_task == len(s.calls("stop_task")) <= 1
    text = repr(report) + json.dumps([d.document() for d in report.diagnostics])
    for canary in (*CANARIES, LEAK, "synthetic backend message", "https://"):
        assert canary not in text


class TestBoundedRePolling:
    def test_a_transient_failure_followed_by_a_valid_response_succeeds(self) -> None:
        s = Scenario()
        s.ecs.script = [None, None, None, "ServerException"]  # the 4th poll: the recorded boundary
        report = s.run()
        assert report.outcome is LaunchOutcome.TASK_TERMINAL and report.task_exit_codes == (0,)
        _assert_common_invariants(s, report)
        (entry,) = report.diagnostics
        assert entry.phase is PollPhase.IMAGE and entry.attempt == 4
        assert (
            entry.poll_class is PollClass.TRANSIENT
            and entry.disposition is PollDisposition.RE_POLLED
        )
        assert (
            entry.failure is pc.ComputeFailure.TRANSIENT and entry.service_code == "ServerException"
        )
        assert entry.exception_class == "FakeClientError"
        assert report.stop_outcome is StopOutcome.ALREADY_TERMINAL and report.counts.stop_task == 0
        assert len(s.launcher_ssm.names("put_parameter")) == 1  # the release, after a valid poll

    def test_a_throttled_failure_followed_by_a_valid_response_succeeds(self) -> None:
        s = Scenario()
        s.ecs.script = [None, None, None, "ThrottlingException"]
        report = s.run()
        assert report.outcome is LaunchOutcome.TASK_TERMINAL
        _assert_common_invariants(s, report)
        (entry,) = report.diagnostics
        assert (
            entry.poll_class is PollClass.THROTTLED
            and entry.disposition is PollDisposition.RE_POLLED
        )

    @pytest.mark.parametrize("exception", [ConnectTimeoutError(LEAK), ReadTimeoutError(LEAK)])
    def test_a_transport_failure_followed_by_a_valid_response_succeeds(
        self, exception: BaseException
    ) -> None:
        s = Scenario()
        s.ecs.script = [None, None, None, exception]
        report = s.run()
        assert report.outcome is LaunchOutcome.TASK_TERMINAL
        _assert_common_invariants(s, report)
        (entry,) = report.diagnostics
        assert entry.failure is pc.ComputeFailure.UNKNOWN  # no service answer at all
        assert entry.poll_class is PollClass.TRANSPORT and entry.service_code is None
        assert entry.exception_class == type(exception).__name__
        assert entry.disposition is PollDisposition.RE_POLLED

    def test_an_unknown_failure_is_re_polled_exactly_once(self) -> None:
        s = Scenario()
        s.ecs.script = [None, None, None, RuntimeError(LEAK)]
        report = s.run()
        assert report.outcome is LaunchOutcome.TASK_TERMINAL
        _assert_common_invariants(s, report)
        (entry,) = report.diagnostics
        assert (
            entry.poll_class is PollClass.UNKNOWN and entry.disposition is PollDisposition.RE_POLLED
        )
        # A second unknown failure in the same streak is the bound: refused, no third poll.
        s2 = Scenario()
        s2.ecs.script = [None, None, None, RuntimeError(LEAK), RuntimeError(LEAK)]
        report2 = s2.run()
        assert report2.outcome is LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED
        _assert_common_invariants(s2, report2)
        assert [d.disposition for d in report2.diagnostics] == [
            PollDisposition.RE_POLLED,
            PollDisposition.REFUSED_BOUND,
        ]
        assert report2.counts.describe_tasks == 5
        assert s2.launcher_ssm.names("put_parameter") == []

    def test_repeated_classified_failures_reach_the_bound_and_refuse(self) -> None:
        s = Scenario()
        s.ecs.script = [
            None,
            None,
            None,
            *["ServerException"] * (pl.MAX_CONSECUTIVE_POLL_FAILURES + 1),
        ]
        report = s.run()
        assert report.outcome is LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED
        _assert_common_invariants(s, report)
        dispositions = [d.disposition for d in report.diagnostics]
        assert dispositions == [PollDisposition.RE_POLLED] * pl.MAX_CONSECUTIVE_POLL_FAILURES + [
            PollDisposition.REFUSED_BOUND
        ]
        assert report.counts.describe_tasks == 3 + pl.MAX_CONSECUTIVE_POLL_FAILURES + 1
        assert s.launcher_ssm.names("put_parameter") == []
        # The bound counts consecutive failures: a valid response in between resets it.
        s2 = Scenario(
            [
                task_entry(ACQ, status="PENDING", attachment_status="ATTACHED", image_digest=None),
                task_entry(ACQ, status="PENDING", attachment_status="ATTACHED", image_digest=None),
                task_entry(ACQ, status="RUNNING", attachment_status="ATTACHED"),
                task_entry(ACQ, status="STOPPED", attachment_status="ATTACHED", exit_code=0),
            ]
        )
        s2.ecs.script = [
            None,
            "ServerException",
            "ServerException",
            None,
            "ServerException",
            "ServerException",
            None,
        ]
        report2 = s2.run()
        assert report2.outcome is LaunchOutcome.TASK_TERMINAL and len(report2.diagnostics) == 4

    @pytest.mark.parametrize(
        "code", ["AccessDeniedException", "ClusterNotFoundException", "InvalidParameterException"]
    )
    def test_a_terminal_service_code_is_never_re_polled(self, code: str) -> None:
        s = Scenario()
        s.ecs.script = [None, None, None, code]
        report = s.run()
        assert report.outcome is LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED
        _assert_common_invariants(s, report)
        (entry,) = report.diagnostics
        assert (
            entry.poll_class is PollClass.TERMINAL
            and entry.disposition is PollDisposition.REFUSED_CLASS
        )
        assert entry.service_code == code and report.counts.describe_tasks == 4
        assert (
            s.clock.sleeps.count(pl.PLACEMENT_POLL_INTERVAL_SECONDS) == 3
        )  # no interval after the refusal

    def test_a_malformed_error_code_keeps_the_class_only_and_fails_closed(self) -> None:
        malformed = "Throttling; request id 0123456789ab"  # outside the service-code grammar
        s = Scenario()
        s.ecs.script = [None, None, None, malformed, malformed]
        report = s.run()
        assert report.outcome is LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED
        _assert_common_invariants(s, report)
        assert [d.service_code for d in report.diagnostics] == [None, None]
        assert [d.exception_class for d in report.diagnostics] == ["FakeClientError"] * 2
        assert [d.poll_class for d in report.diagnostics] == [PollClass.UNKNOWN] * 2
        assert malformed not in json.dumps([d.document() for d in report.diagnostics])

    def test_the_ceiling_is_never_extended(self) -> None:
        # The attachment never reports ATTACHED; the poll just inside the ceiling fails.
        pending = task_entry(
            ACQ, status="PENDING", attachment_status="ATTACHING", interface_id=None, subnet_id=None
        )
        s = Scenario([pending] * 60)
        polls_inside = int(pl.PLACEMENT_CEILING_SECONDS / pl.PLACEMENT_POLL_INTERVAL_SECONDS)
        s.ecs.script = [*([None] * polls_inside), "ServerException"]
        report = s.run()
        assert report.outcome is LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED
        _assert_common_invariants(s, report)
        (entry,) = report.diagnostics
        assert entry.disposition is PollDisposition.REFUSED_DEADLINE
        assert s.clock.seconds <= pl.PLACEMENT_CEILING_SECONDS
        assert report.counts.describe_tasks == polls_inside + 1
        # The same rule in the observation loop, against its own ceiling.
        s2 = Scenario(
            [
                task_entry(ACQ, status="RUNNING", attachment_status="ATTACHED"),
            ]
        )
        observe_polls = int(pl.OBSERVE_CEILING_SECONDS / pl.OBSERVE_POLL_INTERVAL_SECONDS)
        # index 0 is the placement poll
        s2.ecs.script = [*([None] * (observe_polls + 1)), "ServerException"]
        report2 = s2.run()
        assert report2.outcome is LaunchOutcome.OBSERVATION_FAILED
        assert report2.diagnostics[-1].disposition is PollDisposition.REFUSED_DEADLINE
        assert report2.diagnostics[-1].phase is PollPhase.OBSERVATION
        assert s2.clock.seconds <= pl.OBSERVE_CEILING_SECONDS + pl.PLACEMENT_POLL_INTERVAL_SECONDS
        assert report2.stop_outcome is StopOutcome.STOPPED

    def test_verification_needs_a_later_valid_response_never_an_exception(self) -> None:
        # Every poll after attachment fails: the image is never verified, no release exists.
        s = Scenario()
        s.ecs.script = [
            None,
            None,
            None,
            "ServerException",
            "ServerException",
            "ServerException",
            "ServerException",
        ]
        report = s.run()
        assert report.outcome is LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED
        assert s.launcher_ssm.names("put_parameter") == [] and report.network_interface_id is None
        assert (
            report.counts.describe_network_interfaces == 1
        )  # placement was checked, once, on a valid poll


class TestThePostStartStopInvariant:
    def test_a_failure_before_task_acceptance_issues_no_stop(self) -> None:
        s = Scenario()
        s.ecs.run_failure = "ServerException"
        report = s.run()
        assert report.outcome is LaunchOutcome.REFUSED_LAUNCH and not report.task_started
        assert s.calls("stop_task") == [] and report.stop_outcome is StopOutcome.NOT_APPLICABLE
        assert report.diagnostics == ()
        assert s.human_ssm.names("delete_parameter") == s.human_ssm.names("put_parameter")

    def test_a_failure_after_acceptance_issues_exactly_one_stop(self) -> None:
        s = Scenario()
        s.ecs.script = [None, None, None, RuntimeError(LEAK), RuntimeError(LEAK)]
        report = s.run()
        assert report.outcome is LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED and report.task_started
        (stop,) = s.calls("stop_task")
        assert stop["reason"] == pl.STOP_REASON_REFUSED and stop["task"] == TASK_ARN
        assert report.stop_outcome is StopOutcome.STOPPED and report.counts.stop_task == 1
        # The release was withheld and the input was cleaned up; the refusal stands.
        assert s.launcher_ssm.names("put_parameter") == []
        assert s.human_ssm.names("delete_parameter") == s.human_ssm.names("put_parameter")
        assert report.cleanup_failures == ()

    def test_an_already_terminal_task_needs_no_stop(self) -> None:
        stopped = task_entry(
            ACQ,
            status="STOPPED",
            attachment_status="PRECREATED",
            interface_id=None,
            subnet_id=None,
            exit_code=1,
        )
        s = Scenario([stopped])
        report = s.run()
        assert report.outcome is LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED
        assert s.calls("stop_task") == [] and report.stop_outcome is StopOutcome.ALREADY_TERMINAL
        # A normal completion is terminal too: no stop, and the outcome is the task's.
        s2 = Scenario()
        report2 = s2.run()
        assert report2.outcome is LaunchOutcome.TASK_TERMINAL
        assert s2.calls("stop_task") == [] and report2.stop_outcome is StopOutcome.ALREADY_TERMINAL

    def test_a_failed_stop_is_recorded_beside_the_preserved_refusal(self) -> None:
        s = Scenario()
        s.ecs.script = [None, None, None, RuntimeError(LEAK), RuntimeError(LEAK)]
        s.ecs.stop_failure = "ServerException"
        report = s.run()
        assert report.outcome is LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED  # never replaced
        assert report.stop_outcome is StopOutcome.STOP_FAILED and report.counts.stop_task == 1
        assert any(
            f.stage is CleanupStage.STOP_TASK and f.failure == "TRANSIENT"
            for f in report.cleanup_failures
        )
        # Parameter cleanup still ran, and its own result is recorded separately.
        assert len(s.human_ssm.names("delete_parameter")) == 1
        evidence = s.evidence(report)
        assert (
            evidence["outcome"] == "REFUSED_PLACEMENT_UNVERIFIED"
            and evidence["stop_outcome"] == "STOP_FAILED"
        )
        assert "STOP_TASK:TRANSIENT" in evidence["cleanup_failures"]

    def test_parameter_cleanup_still_runs_and_no_release_is_written_on_failure(self) -> None:
        # A refusal after the release was written (observation): release removed, task stopped.
        s = Scenario(
            [
                task_entry(ACQ, status="RUNNING", attachment_status="ATTACHED"),
            ]
        )
        s.ecs.script = [
            None,
            "ServerException",
            "ServerException",
            "ServerException",
            "ServerException",
        ]
        report = s.run()
        assert report.outcome is LaunchOutcome.OBSERVATION_FAILED
        assert [d.phase for d in report.diagnostics] == [PollPhase.OBSERVATION] * 4
        assert report.stop_outcome is StopOutcome.STOPPED and report.counts.stop_task == 1
        assert len(s.launcher_ssm.names("delete_parameter")) == 1  # the release, removed
        assert len(s.human_ssm.names("delete_parameter")) == 1  # the input, removed
        # A refusal before the release: none was ever written.
        s2 = Scenario()
        s2.ecs.script = [None, None, None, "AccessDeniedException"]
        report2 = s2.run()
        assert report2.outcome is LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED
        assert (
            s2.launcher_ssm.names("put_parameter") == []
            and s2.launcher_ssm.names("delete_parameter") == []
        )
        assert (
            len(s2.human_ssm.names("delete_parameter")) == 1
            and report2.stop_outcome is StopOutcome.STOPPED
        )

    def test_the_misplaced_and_stale_release_stops_are_the_one_stop(self) -> None:
        s = Scenario()
        s.ec2.interface = interface_entry(public_ip=None)  # PUBLIC_IP_MISMATCH
        report = s.run()
        assert report.outcome is LaunchOutcome.MISPLACED and report.counts.stop_task == 1
        (stop,) = s.calls("stop_task")
        assert (
            stop["reason"] == pl.STOP_REASON_MISPLACED
            and report.stop_outcome is StopOutcome.STOPPED
        )


class TestEvidenceHygiene:
    def test_nothing_sensitive_enters_the_report_or_the_evidence_document(self) -> None:
        s = Scenario()
        s.ecs.script = [
            None,
            None,
            None,
            ConnectTimeoutError(LEAK),
            FakeClientError("ServerException"),
            RuntimeError(LEAK),
            RuntimeError(LEAK),
        ]
        report = s.run()
        assert report.outcome is LaunchOutcome.REFUSED_PLACEMENT_UNVERIFIED
        _assert_common_invariants(s, report)
        evidence = s.evidence(report)
        text = canonical_bytes(evidence).decode("utf-8")
        for canary in (*CANARIES, LEAK, "synthetic backend message", "https://", "request-id"):
            assert canary not in text
        assert evidence["contract_id"] == "kalpamani-launch-evidence/v2"
        # An unknown failure inside a streak of classified ones narrows the bound to one:
        # the streak already used two re-polls, so the unknown failure is the bound.
        assert [d["poll_class"] for d in evidence["diagnostics"]] == [
            "TRANSPORT",
            "TRANSIENT",
            "UNKNOWN",
        ]
        assert [d["disposition"] for d in evidence["diagnostics"]] == [
            "RE_POLLED",
            "RE_POLLED",
            "REFUSED_BOUND",
        ]
        for entry in evidence["diagnostics"]:
            assert set(entry) == lr.EVIDENCE_DIAGNOSTIC_FIELDS
            assert entry["exception_class"] is None or pc.EXCEPTION_CLASS_RE.fullmatch(
                entry["exception_class"]
            )
            assert entry["service_code"] is None or pc.SERVICE_CODE_RE.fullmatch(
                entry["service_code"]
            )
            assert type(entry["elapsed_ms"]) is int and type(entry["attempt"]) is int

    def test_a_compute_error_holds_its_diagnostics_to_their_grammars(self) -> None:
        with pytest.raises(TypeError):
            pc.ComputeError(
                operation=pc.ComputeOperation.DESCRIBE_TASKS,
                failure=pc.ComputeFailure.UNKNOWN,
                exception_class=LEAK,
            )
        with pytest.raises(TypeError):
            pc.ComputeError(
                operation=pc.ComputeOperation.DESCRIBE_TASKS,
                failure=pc.ComputeFailure.UNKNOWN,
                service_code="Throttling; request id 0123456789ab",
            )
        error = pc.ComputeError(
            operation=pc.ComputeOperation.DESCRIBE_TASKS, failure=pc.ComputeFailure.UNKNOWN
        )
        assert error.exception_class is None and error.service_code is None
        assert pc.sanitized_service_code(FakeClientError("Throttling")) == "Throttling"
        assert pc.sanitized_service_code(FakeClientError("bad code!")) is None
        assert pc.sanitized_service_code(RuntimeError(LEAK)) is None
        assert pc.sanitized_exception_class(ConnectTimeoutError(LEAK)) == "ConnectTimeoutError"
        with pytest.raises(TypeError):
            PollDiagnostic(
                phase=PollPhase.IMAGE,
                operation=pc.ComputeOperation.DESCRIBE_TASKS,
                failure=pc.ComputeFailure.UNKNOWN,
                exception_class="ok",
                service_code=None,
                attempt=1,
                elapsed_ms=-1,
                poll_class=PollClass.UNKNOWN,
                disposition=PollDisposition.RE_POLLED,
            )

    def test_the_poll_classification_is_total_over_the_vocabulary(self) -> None:
        for failure in pc.ComputeFailure:
            assert type(poll_class_of(failure, None)) is PollClass
        assert (
            poll_class_of(pc.ComputeFailure.UNKNOWN, "ConnectTimeoutError") is PollClass.TRANSPORT
        )
        assert poll_class_of(pc.ComputeFailure.UNKNOWN, "RuntimeError") is PollClass.UNKNOWN
        assert (
            poll_class_of(pc.ComputeFailure.INVALID_RESPONSE, "ConnectTimeoutError")
            is PollClass.TERMINAL
        )


class TestUnchangedPathsAndTheRecordedSignatures:
    def test_the_successful_path_is_unchanged(self) -> None:
        s = Scenario(
            [
                task_entry(ACQ, status="PENDING", attachment_status="ATTACHED"),
                task_entry(ACQ, status="RUNNING", attachment_status="ATTACHED"),
                task_entry(ACQ, status="STOPPED", attachment_status="ATTACHED", exit_code=0),
            ]
        )
        report = s.run()
        assert report.outcome is LaunchOutcome.TASK_TERMINAL and report.task_exit_codes == (0,)
        assert report.counts.describe_tasks == 3 and report.counts.stop_task == 0
        assert report.counts.parameter_creates == 2 == report.counts.parameter_deletes
        assert report.diagnostics == () and report.stop_outcome is StopOutcome.ALREADY_TERMINAL
        assert s.clock.sleeps == [
            pl.OBSERVE_POLL_INTERVAL_SECONDS
        ]  # attached and pulled at the first poll

    def test_both_recorded_run14_signatures_fail_before_and_pass_after(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The 2026-09-18 boundary: RunTask accepted, ATTACHED at the third poll, placement
        verified (one DNI, no incident), the fourth poll -- the first image-wait poll --
        refused. Before this amendment that was the launch's end; after it the poll is
        repeated and the launch completes. The historical evidence is not touched."""
        # Pass-after: the recorded sequence, then a valid fifth poll.
        for exception in (
            ConnectTimeoutError(LEAK),
            RuntimeError(LEAK),
            FakeClientError("ServerException"),
        ):
            s = Scenario()
            s.ecs.script = [None, None, None, exception]
            report = s.run()
            assert report.outcome is LaunchOutcome.TASK_TERMINAL
            assert report.counts.describe_network_interfaces == 1 and report.incident is None
            assert (
                report.diagnostics[0].attempt == 4
                and report.diagnostics[0].phase is PollPhase.IMAGE
            )
            _assert_common_invariants(s, report)
        # Fail-before: with no re-poll permitted (the pre-amendment rule), the sequence
        # reproduces the recorded launcher signature exactly -- except that the task is
        # now stopped, which is the second half of the correction.
        monkeypatch.setattr(pl, "MAX_CONSECUTIVE_POLL_FAILURES", 0)
        monkeypatch.setattr(pl, "MAX_UNKNOWN_POLL_FAILURES", 0)
        for exception in (ConnectTimeoutError(LEAK), RuntimeError(LEAK)):
            s = Scenario()
            s.ecs.script = [None, None, None, exception]
            report = s.run()
            observed = {
                "outcome": report.outcome,
                "run_task": report.counts.run_task,
                "describe_tasks": report.counts.describe_tasks,
                "describe_network_interfaces": report.counts.describe_network_interfaces,
                "stop_task_before": 0,
                "incident": report.incident,
                "exit_codes": report.task_exit_codes,
                "task_started": report.task_started,
            }
            assert observed == RUN14_SIGNATURE
            assert report.counts.stop_task == 1 and report.stop_outcome is StopOutcome.STOPPED
            assert report.diagnostics[0].disposition is PollDisposition.REFUSED_BOUND


class TestGovernance:
    def test_the_amendment_names_the_contracts_and_the_bounds(self) -> None:
        text = ADR.read_text(encoding="utf-8")
        assert "## 15. Amendment (2026-09-18)" in text
        assert (
            lr.EVIDENCE_CONTRACT_ID == "kalpamani-launch-evidence/v2"
            and lr.EVIDENCE_CONTRACT_ID in text
        )
        assert "kalpamani-launch-evidence/v1" in lr.SUPERSEDED_EVIDENCE_CONTRACT_IDS
        assert f"MAX_CONSECUTIVE_POLL_FAILURES = {pl.MAX_CONSECUTIVE_POLL_FAILURES}" in text
        assert f"MAX_UNKNOWN_POLL_FAILURES = {pl.MAX_UNKNOWN_POLL_FAILURES}" in text
        assert pl.MAX_CONSECUTIVE_POLL_FAILURES == 3 and pl.MAX_UNKNOWN_POLL_FAILURES == 1
        assert "never extended" in text and "no second `RunTask`" in text
        assert "Deployment impact: none" in text
        for member in (*PollPhase, *PollClass, *PollDisposition, *StopOutcome):
            assert member.value in text

    def test_no_task_entry_reaches_the_launcher(self) -> None:
        """The launcher is workstation-only: the image's entry modules never import it."""
        package = "kalpamani.data.production.sharadar"
        seen: set[str] = set()
        frontier = [
            f"{package}.entry",
            f"{package}.acquisition_entry",
            f"{package}.build_entry",
            f"{package}.runner",
        ]
        while frontier:
            module = frontier.pop()
            if module in seen or not module.startswith("kalpamani."):
                continue
            seen.add(module)
            path = ROOT / "src" / Path(*module.split(".")).with_suffix(".py")
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
        assert f"{package}.launcher" not in seen and f"{package}.reachability_hook" not in seen
        # The poll vocabulary is the launcher's: no module of the graph imports it at module
        # level (the launch-records builder admits a document through a function-local import).
        for module in seen:
            path = ROOT / "src" / Path(*module.split(".")).with_suffix(".py")
            if path.exists():
                tree = ast.parse(path.read_text(encoding="utf-8"))
                top = {n.module for n in tree.body if isinstance(n, ast.ImportFrom) and n.module}
                assert f"{package}.poll_evidence" not in top, module

    def test_the_launcher_has_exactly_one_run_task_call_site(self) -> None:
        source = (PRODUCTION / "launcher.py").read_text(encoding="utf-8")
        assert source.count("adapters.ecs.run_task()") == 1
        assert (
            source.count("adapters.ecs.describe_task(task_arn)") == 2
        )  # the re-poll helper and the held loop
        assert "ceiling" in source and "PLACEMENT_CEILING_SECONDS: Final = 120.0" in source
