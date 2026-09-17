"""The R-2 reachability watcher (the ``while_running`` hook), offline on fakes.

Attribution, failure and cleanup paths; the operation, poll and elapsed-time limits; the
proposed evidence against the accepted parser; the private log after every step; the
bounded recovery from a log. Nothing here reaches AWS: every client is a fake that
counts what it was asked and returns documented shapes.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from kalpamani.data.production.sharadar import reachability_hook as rh
from kalpamani.data.production.sharadar.compute import TaskAttachment, TaskDescription
from kalpamani.data.production.sharadar.launcher import HeldTask
from kalpamani.data.production.sharadar.probe import (
    VerdictBinding,
    isolation_verdict,
    parse_reachability_evidence,
)

TASK_ARN = "arn:aws:ecs:us-east-1:111111111111:task/kalpamani/0123456789abcdef0123456789abcdef"
TD_ARN = "arn:aws:ecs:us-east-1:111111111111:task-definition/kalpamani-research-build-verify:2"
IMAGE = "sha256:" + "ab" * 32
ENI = "eni-0123456789abcdef0"
ORIGIN = frozenset({"203.0.113.9", "203.0.113.4", "198.51.100.7"})
T0 = datetime(2026, 9, 17, 15, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.wall = T0
        self.mono = 1000.0
        self.slept: list[float] = []

    def now(self) -> datetime:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.mono += seconds
        self.wall += timedelta(seconds=seconds)


def held(**overrides: Any) -> HeldTask:
    values: dict[str, Any] = {
        "task_arn": TASK_ARN,
        "task_definition_arn": TD_ARN,
        "image_digest": IMAGE,
        "last_status": "RUNNING",
        "observed_at": T0,
        "describe_calls": 1,
    }
    values.update(overrides)
    return HeldTask(**values)


def described(**overrides: Any) -> TaskDescription:
    values: dict[str, Any] = {
        "task_arn": TASK_ARN,
        "task_definition_arn": TD_ARN,
        "last_status": "RUNNING",
        "attachment": TaskAttachment(
            status="ATTACHED", network_interface_id=ENI, subnet_id="subnet-0123456789abcdef0"
        ),
        "exit_codes": (None,),
        "image_digests": (IMAGE,),
    }
    values.update(overrides)
    return TaskDescription(**values)


class FakeEc2:
    """Documented response shapes; scripted statuses; counts every call."""

    def __init__(
        self,
        statuses: list[str] | None = None,
        *,
        explanations: list[dict[str, Any]] | None = None,
        fail: Iterable[str] = (),
        path_found: bool = False,
    ) -> None:
        self.statuses = list(statuses if statuses is not None else ["running", "succeeded"])
        self.explanations = (
            explanations
            if explanations is not None
            else [
                {
                    "ExplanationCode": "NO_ROUTE_TO_DESTINATION",
                    "RouteTable": {"Id": "rtb-0123456789abcdef0"},
                    "Subnet": {"Id": "subnet-0123456789abcdef0"},
                }
            ]
        )
        self.fail = set(fail)
        self.path_found = path_found
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.start_date = T0 + timedelta(seconds=3)

    def _call(self, name: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((name, kwargs))
        if name in self.fail:
            raise RuntimeError(name)

    def create_network_insights_path(self, **kwargs: Any) -> Any:
        self._call("create_path", kwargs)
        self.path_tags = kwargs.get("TagSpecifications", [{}])[0].get("Tags", [])
        return {
            "NetworkInsightsPath": {
                "NetworkInsightsPathId": "nip-0123456789abcdef0",
                "Tags": list(self.path_tags),
            }
        }

    def start_network_insights_analysis(self, **kwargs: Any) -> Any:
        self._call("start_analysis", kwargs)
        self.analysis_tags = kwargs.get("TagSpecifications", [{}])[0].get("Tags", [])
        return {
            "NetworkInsightsAnalysis": {
                "NetworkInsightsAnalysisId": "nia-0123456789abcdef0",
                "Status": "running",
                "StartDate": self.start_date,
            }
        }

    def describe_network_insights_paths(self, **kwargs: Any) -> Any:
        self._call("describe_paths", kwargs)
        # a tag-filtered listing: the fake applies the filter exactly as the API would
        wanted = kwargs["Filters"][0]["Values"][0]
        paths = [
            {
                "NetworkInsightsPathId": "nip-0123456789abcdef0",
                "Tags": list(getattr(self, "path_tags", [])),
            },
            {
                "NetworkInsightsPathId": "nip-0fedcba9876543210",
                "Tags": [{"Key": rh.INVOCATION_TAG_KEY, "Value": "another-invocation"}],
            },
        ]
        return {
            "NetworkInsightsPaths": [
                p for p in paths if any(t.get("Value") == wanted for t in p["Tags"])
            ]
        }

    def describe_network_insights_analyses(self, **kwargs: Any) -> Any:
        self._call("describe_analysis", kwargs)
        if "NetworkInsightsPathId" in kwargs:
            # the by-path listing used only by cleanup / recovery: one tagged analysis of
            # ours and one foreign analysis on the same path, which must never be deleted
            return {
                "NetworkInsightsAnalyses": [
                    {
                        "NetworkInsightsAnalysisId": "nia-0123456789abcdef0",
                        "NetworkInsightsPathId": kwargs["NetworkInsightsPathId"],
                        "Status": "running",
                        "Tags": list(getattr(self, "analysis_tags", [])),
                    },
                    {
                        "NetworkInsightsAnalysisId": "nia-0fedcba9876543210",
                        "NetworkInsightsPathId": kwargs["NetworkInsightsPathId"],
                        "Status": "running",
                        "Tags": [{"Key": rh.INVOCATION_TAG_KEY, "Value": "another-invocation"}],
                    },
                ]
            }
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        entry: dict[str, Any] = {
            "NetworkInsightsAnalysisId": "nia-0123456789abcdef0",
            "NetworkInsightsPathId": "nip-0123456789abcdef0",
            "Status": status,
            "StartDate": self.start_date,
        }
        if status == "succeeded":
            entry["NetworkPathFound"] = self.path_found
            entry["Explanations"] = self.explanations
        return {"NetworkInsightsAnalyses": [entry]}

    def delete_network_insights_analysis(self, **kwargs: Any) -> Any:
        self._call("delete_analysis", kwargs)
        return {"NetworkInsightsAnalysisId": kwargs["NetworkInsightsAnalysisId"]}

    def delete_network_insights_path(self, **kwargs: Any) -> Any:
        self._call("delete_path", kwargs)
        return {"NetworkInsightsPathId": kwargs["NetworkInsightsPathId"]}

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]


def watcher(
    tmp_path: Path,
    ec2: FakeEc2,
    *,
    describe: Callable[[str], TaskDescription] | None = None,
    clock: Clock | None = None,
) -> tuple[rh.ReachabilityWatcher, Clock]:
    clock = clock or Clock()
    describes: list[str] = []

    def describe_task(arn: str) -> TaskDescription:
        describes.append(arn)
        if describe is not None:
            return describe(arn)
        return described()

    w = rh.ReachabilityWatcher(
        target=rh.ReachabilityTarget(
            task_definition_arn=TD_ARN, image_digest=IMAGE, compiled_origin_addresses=ORIGIN
        ),
        describe_task=describe_task,
        ec2=ec2,
        log_path=tmp_path / "hook-log.json",
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    return w, clock


def log(tmp_path: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((tmp_path / "hook-log.json").read_bytes())
    return document


def test_destination_is_the_smallest_compiled_address() -> None:
    target = rh.ReachabilityTarget(
        task_definition_arn=TD_ARN, image_digest=IMAGE, compiled_origin_addresses=ORIGIN
    )
    assert target.destination_ip == "198.51.100.7"
    empty = rh.ReachabilityTarget(
        task_definition_arn=TD_ARN, image_digest=IMAGE, compiled_origin_addresses=frozenset()
    )
    with pytest.raises(ValueError):
        _ = empty.destination_ip


def test_completed_path_proposes_evidence_the_accepted_parser_admits_and_cleans_up(
    tmp_path: Path,
) -> None:
    ec2 = FakeEc2(["running", "running", "succeeded"])
    w, clock = watcher(tmp_path, ec2)
    w(held())
    s = w.state
    assert s.outcome is rh.HookOutcome.COMPLETED and s.reason is None
    assert ec2.names() == [
        "create_path",
        "start_analysis",
        "describe_analysis",
        "describe_analysis",
        "describe_analysis",
        "delete_analysis",
        "delete_path",
    ]
    create = ec2.calls[0][1]
    token = s.invocation_token
    assert create == {
        "Source": ENI,
        "DestinationIp": "198.51.100.7",
        "DestinationPort": 443,
        "Protocol": "tcp",
        "ClientToken": f"{token}-path",
        "TagSpecifications": [
            {
                "ResourceType": "network-insights-path",
                "Tags": [{"Key": rh.INVOCATION_TAG_KEY, "Value": token}],
            }
        ],
    }
    start = ec2.calls[1][1]
    assert start["ClientToken"] == f"{token}-analysis"
    assert start["TagSpecifications"][0]["ResourceType"] == "network-insights-analysis"
    assert start["TagSpecifications"][0]["Tags"] == [{"Key": rh.INVOCATION_TAG_KEY, "Value": token}]
    assert s.counts.document() == {
        "describe_task": 1,
        "create_path": 1,
        "start_analysis": 1,
        "describe_analysis": 3,
        "describe_paths": 0,
        "delete_analysis": 1,
        "delete_path": 1,
    }
    assert s.cleanup_failures == [] and s.evidence_parses is True
    evidence = parse_reachability_evidence(json.dumps(s.proposed_evidence).encode())
    assert evidence.source_interface_id == ENI and evidence.destination_ip == "198.51.100.7"
    assert evidence.start_date == ec2.start_date and evidence.network_path_found is False
    assert evidence.explanations[0].explanation_code == "NO_ROUTE_TO_DESTINATION"
    assert evidence.explanations[0].component_id == "rtb-0123456789abcdef0"
    # the log holds everything, ending on cleanup, and is byte-canonical
    doc = log(tmp_path)
    assert doc["outcome"] == "COMPLETED" and doc["events"][-1]["event"] == "cleanup_attempted"
    assert (
        doc["path_id"] == "nip-0123456789abcdef0" and doc["analysis_id"] == "nia-0123456789abcdef0"
    )
    assert clock.slept == [5.0, 5.0, 5.0]


def test_the_verdict_tool_binds_the_proposed_evidence_to_the_launch(tmp_path: Path) -> None:
    """A succeeded, in-window, correctly-sourced analysis is what the verdict needs; the
    same evidence out of window or off-interface is INCONCLUSIVE there."""
    from kalpamani.data.production.sharadar.probe import (
        ProbeObservation,
        ProbeResolution,
        ProbeResult,
        destination_binding_digest,
    )

    ec2 = FakeEc2()
    w, _ = watcher(tmp_path, ec2)
    w(held())
    evidence = parse_reachability_evidence(json.dumps(w.state.proposed_evidence).encode())
    key = "0" * 64
    observation = ProbeObservation(
        resolution=ProbeResolution.RESOLVED_IN_SET,
        result=ProbeResult.TIMED_OUT,
        attempts=1,
        destination_digest=destination_binding_digest(key, "198.51.100.7", 443),
    )

    def binding(**overrides: Any) -> VerdictBinding:
        values: dict[str, Any] = {
            "binding_key": key,
            "origin_addresses": ORIGIN,
            "network_interface_id": ENI,
            "subnet_id": "subnet-0123456789abcdef0",
            "security_group_ids": frozenset({"sg-0123456789abcdef0"}),
            "launched_at": T0,
            "recorded_at": T0 + timedelta(seconds=60),
        }
        values.update(overrides)
        return VerdictBinding(**values)

    assert isolation_verdict(observation, evidence, binding=binding()).verdict.value == "VERIFIED"
    assert (
        isolation_verdict(
            observation, evidence, binding=binding(network_interface_id="eni-0fedcba9876543210")
        ).reason.value
        == "SOURCE_MISMATCH"
    )
    assert (
        isolation_verdict(
            observation, evidence, binding=binding(launched_at=T0 + timedelta(seconds=10))
        ).reason.value
        == "ANALYSIS_OUTSIDE_TASK_WINDOW"
    )
    assert (
        isolation_verdict(observation, None, binding=binding()).reason.value == "NO_CORROBORATION"
    )


@pytest.mark.parametrize(
    "task",
    [
        held(task_definition_arn=TD_ARN.replace(":2", ":1")),
        held(image_digest="sha256:" + "cd" * 32),
        held(last_status="PENDING"),
    ],
)
def test_a_held_task_that_is_not_the_registered_target_touches_nothing(
    tmp_path: Path, task: HeldTask
) -> None:
    ec2 = FakeEc2()
    w, _ = watcher(tmp_path, ec2)
    w(task)
    assert w.state.outcome is rh.HookOutcome.ATTRIBUTION_REFUSED
    assert ec2.calls == [] and w.state.counts.describe_task == 0
    assert log(tmp_path)["outcome"] == "ATTRIBUTION_REFUSED"


@pytest.mark.parametrize(
    "description",
    [
        described(last_status="STOPPED"),
        described(attachment=None),
        described(
            attachment=TaskAttachment(status="ATTACHING", network_interface_id=None, subnet_id=None)
        ),
        described(task_arn=TASK_ARN[:-1] + "e"),
        described(task_definition_arn=TD_ARN.replace(":2", ":3")),
    ],
)
def test_describe_tasks_that_does_not_attribute_one_running_interface_refuses(
    tmp_path: Path, description: TaskDescription
) -> None:
    ec2 = FakeEc2()
    w, _ = watcher(tmp_path, ec2, describe=lambda _arn: description)
    w(held())
    assert w.state.outcome is rh.HookOutcome.ATTRIBUTION_REFUSED
    assert ec2.calls == [] and w.state.counts.describe_task == 1


def test_describe_tasks_failure_refuses_before_any_ec2_operation(tmp_path: Path) -> None:
    def boom(_arn: str) -> TaskDescription:
        raise RuntimeError("compute")

    ec2 = FakeEc2()
    w, _ = watcher(tmp_path, ec2, describe=boom)
    w(held())
    assert w.state.outcome is rh.HookOutcome.ATTRIBUTION_REFUSED and ec2.calls == []


def test_describe_tasks_is_on_exactly_the_held_arn(tmp_path: Path) -> None:
    seen: list[str] = []

    def describe(arn: str) -> TaskDescription:
        seen.append(arn)
        return described()

    w, _ = watcher(tmp_path, FakeEc2(), describe=describe)
    w(held())
    assert seen == [TASK_ARN]


def test_path_creation_failure_records_and_deletes_nothing(tmp_path: Path) -> None:
    ec2 = FakeEc2(fail={"create_path"})
    w, _ = watcher(tmp_path, ec2)
    w(held())
    assert w.state.outcome is rh.HookOutcome.PATH_NOT_CREATED
    assert ec2.names() == ["create_path"] and w.state.path_id is None


def test_analysis_start_failure_deletes_the_path_only(tmp_path: Path) -> None:
    ec2 = FakeEc2(fail={"start_analysis"})
    w, _ = watcher(tmp_path, ec2)
    w(held())
    assert w.state.outcome is rh.HookOutcome.ANALYSIS_NOT_STARTED
    # a start that raised may still have committed server-side: the path's analyses are
    # listed once and only a tagged one would be deleted (none here), then the path is
    assert ec2.names() == ["create_path", "start_analysis", "describe_analysis", "delete_path"]
    assert ec2.calls[2][1] == {"NetworkInsightsPathId": "nip-0123456789abcdef0"}
    assert w.state.analysis_id is None and w.state.cleanup_failures == []
    assert w.state.counts.delete_analysis == 0


def test_analysis_that_never_finishes_times_out_at_the_poll_ceiling_and_is_deleted(
    tmp_path: Path,
) -> None:
    ec2 = FakeEc2(["running"])
    w, clock = watcher(tmp_path, ec2)
    w(held())
    assert w.state.outcome is rh.HookOutcome.ANALYSIS_TIMEOUT
    assert (
        w.state.counts.describe_analysis == rh.MAX_POLLS
    )  # 60 polls at 5 s == the 300 s ceiling, never a 61st
    assert sum(clock.slept) <= rh.POLL_CEILING_SECONDS
    assert ec2.names()[-2:] == ["delete_analysis", "delete_path"]
    assert w.state.proposed_evidence is None


def test_a_failed_analysis_is_transcribed_as_failed_never_upgraded(tmp_path: Path) -> None:
    class FailedWithResult(FakeEc2):
        def describe_network_insights_analyses(self, **kwargs: Any) -> Any:
            self._call("describe_analysis", kwargs)
            return {
                "NetworkInsightsAnalyses": [
                    {
                        "NetworkInsightsAnalysisId": "nia-0123456789abcdef0",
                        "Status": "failed",
                        "NetworkPathFound": False,
                        "StartDate": self.start_date,
                        "Explanations": [],
                    }
                ]
            }

    ec2 = FailedWithResult()
    w, _ = watcher(tmp_path, ec2)
    w(held())
    assert w.state.outcome is rh.HookOutcome.COMPLETED
    assert w.state.proposed_evidence is not None
    assert w.state.proposed_evidence["status"] == "failed"
    evidence = parse_reachability_evidence(json.dumps(w.state.proposed_evidence).encode())
    assert (
        evidence.status == "failed"
    )  # the verdict tool reads ANALYSIS_NOT_SUCCEEDED -> INCONCLUSIVE


def test_a_failed_analysis_without_a_result_field_is_never_completed_by_invention(
    tmp_path: Path,
) -> None:
    ec2 = FakeEc2(["failed"])  # the fake omits NetworkPathFound on failure, as an API may
    w, _ = watcher(tmp_path, ec2)
    w(held())
    assert w.state.outcome is rh.HookOutcome.EVIDENCE_UNPARSEABLE
    assert w.state.proposed_evidence is not None and w.state.raw_analysis is not None
    # transcribed absent, not as False
    assert w.state.proposed_evidence["network_path_found"] is None
    assert w.state.raw_analysis["Status"] == "failed"
    assert ec2.names()[-2:] == ["delete_analysis", "delete_path"]


def test_describe_failure_mid_wait_records_observation_failed_and_cleans_up(tmp_path: Path) -> None:
    class Flaky(FakeEc2):
        def describe_network_insights_analyses(self, **kwargs: Any) -> Any:
            self._call("describe_analysis", kwargs)
            raise RuntimeError("throttled")

    ec2 = Flaky()
    w, _ = watcher(tmp_path, ec2)
    w(held())
    assert w.state.outcome is rh.HookOutcome.OBSERVATION_FAILED
    assert ec2.names() == [
        "create_path",
        "start_analysis",
        "describe_analysis",
        "delete_analysis",
        "delete_path",
    ]


def test_cleanup_failures_are_recorded_beside_a_completed_outcome_never_retried(
    tmp_path: Path,
) -> None:
    ec2 = FakeEc2(fail={"delete_analysis", "delete_path"})
    w, _ = watcher(tmp_path, ec2)
    w(held())
    assert w.state.outcome is rh.HookOutcome.COMPLETED
    assert w.state.cleanup_failures == ["delete_analysis:RuntimeError", "delete_path:RuntimeError"]
    assert ec2.names().count("delete_analysis") == 1 and ec2.names().count("delete_path") == 1
    assert log(tmp_path)["cleanup_failures"] == [
        "delete_analysis:RuntimeError",
        "delete_path:RuntimeError",
    ]


def test_unparseable_evidence_is_recorded_raw_and_still_cleaned_up(tmp_path: Path) -> None:
    ec2 = FakeEc2(
        explanations=[
            {
                "ExplanationCode": "lower-case-not-a-token",
                "Subnet": {"Id": "subnet-0123456789abcdef0"},
            }
        ]
    )
    w, _ = watcher(tmp_path, ec2)
    w(held())
    assert w.state.outcome is rh.HookOutcome.EVIDENCE_UNPARSEABLE
    assert w.state.raw_analysis is not None and w.state.evidence_parses is False
    assert ec2.names()[-2:] == ["delete_analysis", "delete_path"]


def test_the_watcher_is_single_use_and_a_second_call_touches_nothing(tmp_path: Path) -> None:
    ec2 = FakeEc2()
    w, _ = watcher(tmp_path, ec2)
    w(held())
    before = list(ec2.calls)
    with pytest.raises(RuntimeError):
        w(held())
    assert ec2.calls == before


def test_the_log_is_journaled_before_each_operation(tmp_path: Path) -> None:
    class Interrupting(FakeEc2):
        def start_network_insights_analysis(self, **kwargs: Any) -> Any:
            # the log must already name the path before the analysis is started
            assert log(tmp_path)["path_id"] == "nip-0123456789abcdef0"
            self._call("start_analysis", kwargs)
            raise KeyboardInterrupt

    ec2 = Interrupting()
    w, _ = watcher(tmp_path, ec2)
    with pytest.raises(KeyboardInterrupt):
        w(held())
    doc = log(tmp_path)
    # the finally-cleanup ran for the path, and the outcome was closed rather than left open
    assert doc["counts"]["delete_path"] == 1 and doc["outcome"] == "OBSERVATION_FAILED"


def test_an_existing_log_refuses_construction(tmp_path: Path) -> None:
    (tmp_path / "hook-log.json").write_bytes(b"{}")
    with pytest.raises(FileExistsError):
        watcher(tmp_path, FakeEc2())


def _journal_after(tmp_path: Path, **fields: Any) -> str:
    """A log as a hard kill would leave it: the state at some journaled step."""
    state = rh.HookState()
    document = state.document()
    document.update(fields)
    (tmp_path / "hook-log.json").write_bytes(json.dumps(document).encode())
    return state.invocation_token


def test_cleanup_from_log_deletes_exactly_the_named_ids_once(tmp_path: Path) -> None:
    """A hard kill between the analysis start and the invocation's own cleanup leaves the
    ids in the log with no delete attempted; the recovery deletes each once and no more."""
    _journal_after(
        tmp_path,
        path_id="nip-0123456789abcdef0",
        analysis_id="nia-0123456789abcdef0",
        counts={**rh.HookCounts().document(), "create_path": 1, "start_analysis": 1},
    )
    recovery = FakeEc2()
    result = rh.cleanup_from_log(tmp_path / "hook-log.json", recovery)
    assert result == {
        "deleted_analyses": ["nia-0123456789abcdef0"],
        "deleted_paths": ["nip-0123456789abcdef0"],
        "recovered_path_ids": [],
    }
    assert recovery.calls == [
        ("delete_analysis", {"NetworkInsightsAnalysisId": "nia-0123456789abcdef0"}),
        ("delete_path", {"NetworkInsightsPathId": "nip-0123456789abcdef0"}),
    ]
    again = FakeEc2()
    assert rh.cleanup_from_log(tmp_path / "hook-log.json", again) == {
        "deleted_analyses": [],
        "deleted_paths": [],
        "recovered_path_ids": [],
    }
    assert again.calls == []
    assert log(tmp_path)["counts"]["delete_analysis"] == 1
    assert log(tmp_path)["counts"]["delete_path"] == 1


def test_cleanup_from_log_finds_a_path_created_but_never_acknowledged_by_its_tag_only(
    tmp_path: Path,
) -> None:
    """The kill lands after CreateNetworkInsightsPath succeeded and before its id reached
    the journal: the journal shows the request and the token; recovery lists by that tag,
    deletes that path (and only that path), and never repeats the listing."""
    token = _journal_after(tmp_path, counts={**rh.HookCounts().document(), "create_path": 1})
    recovery = FakeEc2()
    recovery.path_tags = [{"Key": rh.INVOCATION_TAG_KEY, "Value": token}]
    result = rh.cleanup_from_log(tmp_path / "hook-log.json", recovery)
    assert result == {
        "deleted_analyses": [],
        "deleted_paths": ["nip-0123456789abcdef0"],
        "recovered_path_ids": ["nip-0123456789abcdef0"],
    }
    assert recovery.calls[0] == (
        "describe_paths",
        {"Filters": [{"Name": f"tag:{rh.INVOCATION_TAG_KEY}", "Values": [token]}]},
    )
    assert [n for n, _ in recovery.calls] == ["describe_paths", "delete_path"]
    assert "nip-0fedcba9876543210" not in json.dumps(recovery.calls)
    # the listing is made once; a second recovery does not list or delete again
    again = FakeEc2()
    again.path_tags = recovery.path_tags
    assert rh.cleanup_from_log(tmp_path / "hook-log.json", again)["deleted_paths"] == []
    assert again.calls == []


def test_cleanup_from_log_with_no_request_journaled_lists_nothing(tmp_path: Path) -> None:
    _journal_after(tmp_path)  # constructed, then killed before any request
    recovery = FakeEc2()
    assert rh.cleanup_from_log(tmp_path / "hook-log.json", recovery) == {
        "deleted_analyses": [],
        "deleted_paths": [],
        "recovered_path_ids": [],
    }
    assert recovery.calls == []


def test_cleanup_from_log_finds_an_analysis_started_but_never_acknowledged_through_our_path(
    tmp_path: Path,
) -> None:
    """The kill lands after StartNetworkInsightsAnalysis succeeded and before its id reached
    the journal: recovery lists the analyses of this invocation's path, deletes the one
    carrying the token, leaves the foreign one, then deletes the path."""
    token = _journal_after(
        tmp_path,
        path_id="nip-0123456789abcdef0",
        counts={**rh.HookCounts().document(), "create_path": 1, "start_analysis": 1},
    )
    recovery = FakeEc2()
    recovery.analysis_tags = [{"Key": rh.INVOCATION_TAG_KEY, "Value": token}]
    result = rh.cleanup_from_log(tmp_path / "hook-log.json", recovery)
    assert result["deleted_analyses"] == ["nia-0123456789abcdef0"]
    assert result["deleted_paths"] == ["nip-0123456789abcdef0"]
    assert [n for n, _ in recovery.calls] == [
        "describe_analysis",
        "delete_analysis",
        "delete_path",
    ]
    assert recovery.calls[0][1] == {"NetworkInsightsPathId": "nip-0123456789abcdef0"}
    assert "nia-0fedcba9876543210" not in json.dumps(recovery.calls)


def test_a_start_that_succeeded_without_a_parseable_id_is_cleaned_up_through_the_path(
    tmp_path: Path,
) -> None:
    class Unacknowledged(FakeEc2):
        def start_network_insights_analysis(self, **kwargs: Any) -> Any:
            self._call("start_analysis", kwargs)
            self.analysis_tags = kwargs["TagSpecifications"][0]["Tags"]
            return {"NetworkInsightsAnalysis": {"Status": "running"}}  # no id in the response

    ec2 = Unacknowledged()
    w, _ = watcher(tmp_path, ec2)
    w(held())
    assert w.state.outcome is rh.HookOutcome.ANALYSIS_NOT_STARTED
    assert [n for n, _ in ec2.calls] == [
        "create_path",
        "start_analysis",
        "describe_analysis",
        "delete_analysis",
        "delete_path",
    ]
    assert ec2.calls[3][1] == {"NetworkInsightsAnalysisId": "nia-0123456789abcdef0"}
    assert w.state.cleanup_failures == [] and w.state.counts.delete_analysis == 1


def test_the_request_is_journaled_before_the_create_and_start_calls(tmp_path: Path) -> None:
    class Killing(FakeEc2):
        def create_network_insights_path(self, **kwargs: Any) -> Any:
            doc = log(tmp_path)
            assert doc["counts"]["create_path"] == 1 and doc["path_id"] is None
            assert doc["invocation_token"] == kwargs["TagSpecifications"][0]["Tags"][0]["Value"]
            assert doc["events"][-1]["event"] == "create_path_requested"
            raise KeyboardInterrupt  # the process dies with the request in flight

    ec2 = Killing()
    w, _ = watcher(tmp_path, ec2)
    with pytest.raises(KeyboardInterrupt):
        w(held())
    assert log(tmp_path)["outcome"] == "OBSERVATION_FAILED"


def test_cleanup_from_log_never_retries_a_delete_the_invocation_already_attempted(
    tmp_path: Path,
) -> None:
    ec2 = FakeEc2(fail={"delete_analysis", "delete_path"})
    w, _ = watcher(tmp_path, ec2)
    w(held())
    recovery = FakeEc2()
    assert rh.cleanup_from_log(tmp_path / "hook-log.json", recovery) == {
        "deleted_analyses": [],
        "deleted_paths": [],
        "recovered_path_ids": [],
    }
    assert recovery.calls == []
    assert log(tmp_path)["cleanup_failures"] == [
        "delete_analysis:RuntimeError",
        "delete_path:RuntimeError",
    ]


def test_cleanup_from_log_refuses_a_log_without_a_token(tmp_path: Path) -> None:
    (tmp_path / "log.json").write_bytes(
        json.dumps({"contract_id": rh.LOG_CONTRACT_ID, "invocation_token": ""}).encode()
    )
    with pytest.raises(ValueError):
        rh.cleanup_from_log(tmp_path / "log.json", FakeEc2())


def test_the_state_repr_carries_no_identifier(tmp_path: Path) -> None:
    w, _ = watcher(tmp_path, FakeEc2())
    w(held())
    text = repr(w.state)
    assert text == "HookState(outcome='COMPLETED')"
    for secret in (TASK_ARN, ENI, "nip-", "nia-", w.state.invocation_token):
        assert secret not in text


def test_the_proposed_evidence_is_marked_unattested(tmp_path: Path) -> None:
    w, _ = watcher(tmp_path, FakeEc2())
    w(held())
    doc = log(tmp_path)
    assert doc["evidence_is_owner_attested"] is False
    assert doc["proposed_evidence"]["contract_id"] == "kalpamani-reachability-evidence/v1"


def test_cleanup_from_log_refuses_a_foreign_document(tmp_path: Path) -> None:
    (tmp_path / "other.json").write_bytes(b'{"contract_id": "something-else"}')
    with pytest.raises(ValueError):
        rh.cleanup_from_log(tmp_path / "other.json", FakeEc2())


def test_the_log_never_carries_more_than_the_closed_fields(tmp_path: Path) -> None:
    w, _ = watcher(tmp_path, FakeEc2())
    w(held())
    assert set(log(tmp_path)) == {
        "contract_id",
        "schema_version",
        "invocation_token",
        "outcome",
        "reason",
        "task_arn",
        "held_observed_at",
        "network_interface_id",
        "path_id",
        "analysis_id",
        "start_date",
        "status",
        "network_path_found",
        "raw_analysis",
        "proposed_evidence",
        "evidence_parses",
        "evidence_is_owner_attested",
        "cleanup_failures",
        "counts",
        "events",
    }


class _ClientError(Exception):
    """An SDK client-error-shaped exception: a ``response`` with ``Error.Code`` and a
    message that carries what must never reach the journal."""

    def __init__(self, code: str) -> None:
        super().__init__(f"An error occurred ({code}) on {TASK_ARN} / {ENI}")
        self.response = {"Error": {"Code": code, "Message": f"about {ENI}"}}


def test_a_failed_operation_journals_its_sanitized_failure_code_never_the_message(
    tmp_path: Path,
) -> None:
    """The readiness S9 build-bootstrap finding: a create that failed left only
    "CreateNetworkInsightsPath failed" in the journal, so its cause could not be told
    apart. The class name and the service's error code are journaled; the message --
    which quotes ARNs and interface ids -- never is."""

    class Refusing(FakeEc2):
        def create_network_insights_path(self, **kwargs: Any) -> Any:
            self._call("create_path", kwargs)
            raise _ClientError("UnauthorizedOperation")

    w, _ = watcher(tmp_path, Refusing())
    w(held())
    assert w.state.outcome is rh.HookOutcome.PATH_NOT_CREATED
    assert w.state.reason == "CreateNetworkInsightsPath failed: _ClientError:UnauthorizedOperation"
    doc = log(tmp_path)
    assert ENI not in doc["reason"] and "An error occurred" not in json.dumps(doc)
    assert doc["events"][-1]["event"] == "finished:PATH_NOT_CREATED"
    assert rh.failure_code(RuntimeError("x")) == "RuntimeError"
    assert rh.failure_code(_ClientError("bad code with spaces")) == "_ClientError"


def test_cleanup_failures_carry_the_sanitized_code(tmp_path: Path) -> None:
    class Failing(FakeEc2):
        def delete_network_insights_path(self, **kwargs: Any) -> Any:
            self._call("delete_path", kwargs)
            raise _ClientError("DependencyViolation")

    w, _ = watcher(tmp_path, Failing())
    w(held())
    assert w.state.cleanup_failures == ["delete_path:_ClientError:DependencyViolation"]
