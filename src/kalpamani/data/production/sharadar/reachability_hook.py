"""The R-2 reachability watcher: the ``while_running`` hook for ONE build verification launch.

Option A of the R-2 corroboration choice (ADR-0045 s.12; the hook interface PR #121 merged):
while the released build verification task is RUNNING, one VPC Reachability Analyzer
analysis is started from the task's own network interface to the probe destination --
the lexicographically smallest address of the accepted compiled origin set, TCP/443 --
so that its ``startDate`` lies inside the window in which that interface existed. The
hook holds the exact task ARN the launcher handed it and nothing looser: no family
listing, no other task, no guessed interface.

What it does, in order, and what it refuses:

1. **Attribution.** ``HeldTask`` must name the registered task definition and image the
   watcher was constructed for; one ``DescribeTasks`` on exactly that ARN must report the
   task ``RUNNING`` with one attached network interface. Anything else records
   ``ATTRIBUTION_REFUSED`` and touches nothing.
2. **Path and analysis.** One ``CreateNetworkInsightsPath`` (source = that interface,
   destination = the compiled address, tcp/443) and one ``StartNetworkInsightsAnalysis``.
   The analysis ``startDate`` is what the API returned, never the clock here.
3. **Bounded wait.** ``DescribeNetworkInsightsAnalyses`` on that analysis at
   ``POLL_INTERVAL_SECONDS`` for at most ``MAX_POLLS`` polls / ``POLL_CEILING_SECONDS``
   on the injected monotonic clock; ``running`` past the ceiling is
   ``ANALYSIS_TIMEOUT`` (the analysis is still deleted).
4. **Evidence.** The documented fields are transcribed verbatim into a proposed
   ``kalpamani-reachability-evidence/v1`` document beside the raw responses. **The owner
   attests the D-16 transcription**; the watcher proposes it and the verdict tool parses
   it closed. A proposed document that fails the accepted parser is recorded as
   ``EVIDENCE_UNPARSEABLE`` and still written raw.
5. **Cleanup.** ``DeleteNetworkInsightsAnalysis`` then ``DeleteNetworkInsightsPath`` --
   only the ids this invocation created, each once; a failure is recorded beside the
   outcome, never hidden, and never retried.

Every step is journaled to one owner-only private log **before** the next operation, so
an interruption leaves the ids on disk for the bounded ``cleanup_from_log`` and never a
silent residue. The hook's outcome is its own record: the launcher swallows exceptions
(``launch_authorized_run``), the bootstrap cell reads its verdict from the receipt, and
the R-2 cell reads ``INCONCLUSIVE`` unless the verdict tool binds a ``succeeded`` analysis
to this task's interface, destination and window -- a completed bootstrap never masks a
missing, failed, mismatched or out-of-window analysis, and never masks a cleanup
failure, because neither reaches the R-2 verdict and both are printed by the driver.

The watcher sends no packets and proves no isolation: a ``succeeded`` analysis is a
configuration-model result the verdict tool binds; anything short of it is INCONCLUSIVE
there, never PASS here.
"""

from __future__ import annotations

import ipaddress
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol

from kalpamani.data.contracts.canonical import canonical_bytes
from kalpamani.data.production.sharadar.compute import TaskDescription
from kalpamani.data.production.sharadar.launcher import HeldTask
from kalpamani.data.production.sharadar.probe import (
    PROBE_PORT,
    PROBE_PROTOCOL,
    REACHABILITY_EVIDENCE_CONTRACT_ID,
    REACHABILITY_EVIDENCE_SCHEMA_VERSION,
    parse_reachability_evidence,
)

#: Poll ``DescribeNetworkInsightsAnalyses`` every 5 s, at most 60 times (<= 300 s).
POLL_INTERVAL_SECONDS: Final = 5.0
MAX_POLLS: Final = 60
POLL_CEILING_SECONDS: Final = 300.0
#: One of each; the hook never retries an operation.
MAX_DESCRIBE_TASK: Final = 1
MAX_CREATE_PATH: Final = 1
MAX_START_ANALYSIS: Final = 1
MAX_DELETE_ANALYSIS: Final = 1
MAX_DELETE_PATH: Final = 1
LOG_CONTRACT_ID: Final = "kalpamani-reachability-hook-log/v1"
#: The documented explanation component objects and the component kind each names
#: (https://docs.aws.amazon.com/vpc/latest/reachability/explanation-codes.html).
_COMPONENT_OBJECTS: Final[tuple[tuple[str, str], ...]] = (
    ("SecurityGroup", "SECURITY_GROUP"),
    ("Acl", "NETWORK_ACL"),
    ("RouteTable", "ROUTE_TABLE"),
    ("SubnetRouteTable", "ROUTE_TABLE"),
    ("Subnet", "SUBNET"),
)


class HookOutcome(StrEnum):
    """The watcher's own closed outcome. None of them is an isolation verdict."""

    COMPLETED = "COMPLETED"
    ATTRIBUTION_REFUSED = "ATTRIBUTION_REFUSED"
    PATH_NOT_CREATED = "PATH_NOT_CREATED"
    ANALYSIS_NOT_STARTED = "ANALYSIS_NOT_STARTED"
    ANALYSIS_TIMEOUT = "ANALYSIS_TIMEOUT"
    OBSERVATION_FAILED = "OBSERVATION_FAILED"
    EVIDENCE_UNPARSEABLE = "EVIDENCE_UNPARSEABLE"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReachabilityTarget:
    """What the watcher was constructed for: the registered build verification target
    and the accepted compiled origin set. The destination is derived, never supplied."""

    task_definition_arn: str
    image_digest: str
    compiled_origin_addresses: frozenset[str]

    @property
    def destination_ip(self) -> str:
        """The lexicographically smallest compiled IPv4 literal -- the probe's own rule."""
        addresses = sorted(self.compiled_origin_addresses)
        if not addresses:
            raise ValueError("the compiled origin set is empty")
        for address in addresses:
            ipaddress.IPv4Address(address)
        return addresses[0]


class NetworkInsightsClient(Protocol):
    """The five EC2 operations the watcher uses, client-shaped (``boto3`` ``ec2``)."""

    def create_network_insights_path(self, **kwargs: Any) -> Any: ...
    def start_network_insights_analysis(self, **kwargs: Any) -> Any: ...
    def describe_network_insights_analyses(self, **kwargs: Any) -> Any: ...
    def delete_network_insights_analysis(self, **kwargs: Any) -> Any: ...
    def delete_network_insights_path(self, **kwargs: Any) -> Any: ...


@dataclass(slots=True, kw_only=True)
class HookCounts:
    """What the watcher asked of its clients."""

    describe_task: int = 0
    create_path: int = 0
    start_analysis: int = 0
    describe_analysis: int = 0
    delete_analysis: int = 0
    delete_path: int = 0

    def document(self) -> dict[str, int]:
        """A plain mapping."""
        return {
            "describe_task": self.describe_task,
            "create_path": self.create_path,
            "start_analysis": self.start_analysis,
            "describe_analysis": self.describe_analysis,
            "delete_analysis": self.delete_analysis,
            "delete_path": self.delete_path,
        }


@dataclass(slots=True, kw_only=True)
class HookState:
    """Everything the watcher established, journaled as it goes."""

    outcome: HookOutcome | None = None
    reason: str | None = None
    task_arn: str | None = None
    network_interface_id: str | None = None
    path_id: str | None = None
    analysis_id: str | None = None
    start_date: str | None = None
    status: str | None = None
    network_path_found: bool | None = None
    raw_analysis: dict[str, Any] | None = None
    proposed_evidence: dict[str, Any] | None = None
    evidence_parses: bool | None = None
    cleanup_failures: list[str] = field(default_factory=list)
    counts: HookCounts = field(default_factory=HookCounts)
    events: list[dict[str, str]] = field(default_factory=list)

    def document(self) -> dict[str, Any]:
        """The private log document (owner-only; never printed)."""
        return {
            "contract_id": LOG_CONTRACT_ID,
            "schema_version": 1,
            "outcome": None if self.outcome is None else self.outcome.value,
            "reason": self.reason,
            "task_arn": self.task_arn,
            "network_interface_id": self.network_interface_id,
            "path_id": self.path_id,
            "analysis_id": self.analysis_id,
            "start_date": self.start_date,
            "status": self.status,
            "network_path_found": self.network_path_found,
            "raw_analysis": self.raw_analysis,
            "proposed_evidence": self.proposed_evidence,
            "evidence_parses": self.evidence_parses,
            "cleanup_failures": list(self.cleanup_failures),
            "counts": self.counts.document(),
            "events": list(self.events),
        }


def _sanitize(value: Any) -> Any:
    """JSON-serializable copy of an API response (datetimes to ISO instants)."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Mapping):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_sanitize(v) for v in value]
    return value


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return value if isinstance(value, str) else None


def propose_evidence(
    *, analysis: Mapping[str, Any], path_id: str, source_interface_id: str, destination_ip: str
) -> dict[str, Any]:
    """The ``kalpamani-reachability-evidence/v1`` document proposed from one
    ``NetworkInsightsAnalysis`` response, field by field from the documented attributes.
    The owner's attestation is a separate act; the accepted parser decides admission."""
    explanations: list[dict[str, Any]] = []
    for entry in analysis.get("Explanations") or []:
        if not isinstance(entry, Mapping):
            continue
        kind: str | None = None
        component_id: str | None = None
        for attribute, component_kind in _COMPONENT_OBJECTS:
            component = entry.get(attribute)
            if isinstance(component, Mapping) and isinstance(component.get("Id"), str):
                kind, component_id = component_kind, component["Id"]
                break
        subnet = entry.get("Subnet")
        subnet_id = subnet.get("Id") if isinstance(subnet, Mapping) else None
        explanations.append(
            {
                "explanation_code": entry.get("ExplanationCode"),
                "component_kind": kind,
                "component_id": component_id,
                "subnet_id": subnet_id if isinstance(subnet_id, str) else None,
            }
        )
    return {
        "schema_version": REACHABILITY_EVIDENCE_SCHEMA_VERSION,
        "contract_id": REACHABILITY_EVIDENCE_CONTRACT_ID,
        "analysis_id": analysis.get("NetworkInsightsAnalysisId"),
        "path_id": path_id,
        "status": analysis.get("Status"),
        "network_path_found": analysis.get("NetworkPathFound"),
        "start_date": _iso(analysis.get("StartDate")),
        "source_interface_id": source_interface_id,
        "destination_ip": destination_ip,
        "destination_port": PROBE_PORT,
        "protocol": PROBE_PROTOCOL,
        "explanations": explanations,
    }


class ReachabilityWatcher:
    """The ``while_running`` hook. Construct once per launch; call at most once."""

    __slots__ = (
        "_describe_task",
        "_ec2",
        "_log_path",
        "_monotonic",
        "_now",
        "_sleep",
        "_target",
        "state",
    )

    def __init__(
        self,
        *,
        target: ReachabilityTarget,
        describe_task: Callable[[str], TaskDescription],
        ec2: NetworkInsightsClient,
        log_path: Path,
        now: Callable[[], datetime],
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        """Bind the target, the two client seams, the private log and the clocks."""
        _ = target.destination_ip  # refuse an empty or non-IPv4 set at construction
        self._target = target
        self._describe_task = describe_task
        self._ec2 = ec2
        self._log_path = log_path
        self._now = now
        self._monotonic = monotonic
        self._sleep = sleep
        self.state = HookState()
        if log_path.exists():
            raise FileExistsError("the private hook log must not exist yet")
        self._journal("constructed")

    # -- journaling ---------------------------------------------------------------

    def _journal(self, event: str) -> None:
        self.state.events.append({"at": self._now().astimezone(UTC).isoformat(), "event": event})
        payload = canonical_bytes(self.state.document())
        tmp = self._log_path.with_name(self._log_path.name + ".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp, self._log_path)

    def _finish(self, outcome: HookOutcome, reason: str | None = None) -> None:
        self.state.outcome = outcome
        self.state.reason = reason
        self._journal(f"finished:{outcome.value}")

    # -- the hook -----------------------------------------------------------------

    def __call__(self, held: HeldTask) -> None:
        """Attribute, create, start, wait, transcribe, clean up -- each once."""
        if self.state.outcome is not None or self.state.counts.describe_task:
            raise RuntimeError("the watcher was already invoked")
        try:
            self._run(held)
        finally:
            if self.state.outcome is None:
                self._finish(HookOutcome.OBSERVATION_FAILED, "an unclassified failure")

    def _run(self, held: HeldTask) -> None:
        state, counts, target = self.state, self.state.counts, self._target
        if type(held) is not HeldTask:  # a duck-typed object is not the launcher's
            self._finish(HookOutcome.ATTRIBUTION_REFUSED, "the launcher handed no HeldTask")
            return
        state.task_arn = held.task_arn
        self._journal("held_task_received")
        if (
            held.task_definition_arn != target.task_definition_arn
            or held.image_digest != target.image_digest
            or held.last_status != "RUNNING"
        ):
            self._finish(
                HookOutcome.ATTRIBUTION_REFUSED, "the held task is not the registered target"
            )
            return
        counts.describe_task += 1
        try:
            described = self._describe_task(held.task_arn)
        except Exception:
            self._finish(HookOutcome.ATTRIBUTION_REFUSED, "DescribeTasks failed")
            return
        attachment = described.attachment
        if (
            described.task_arn != held.task_arn
            or described.task_definition_arn != target.task_definition_arn
            or described.last_status != "RUNNING"
            or attachment is None
            or attachment.network_interface_id is None
        ):
            self._finish(
                HookOutcome.ATTRIBUTION_REFUSED,
                "the task did not report RUNNING with one interface",
            )
            return
        state.network_interface_id = attachment.network_interface_id
        self._journal("interface_attributed")
        destination = target.destination_ip
        counts.create_path += 1
        try:
            created = self._ec2.create_network_insights_path(
                Source=state.network_interface_id,
                DestinationIp=destination,
                DestinationPort=PROBE_PORT,
                Protocol=PROBE_PROTOCOL,
            )
            path_id = created["NetworkInsightsPath"]["NetworkInsightsPathId"]
        except Exception:
            self._finish(HookOutcome.PATH_NOT_CREATED, "CreateNetworkInsightsPath failed")
            return
        state.path_id = path_id
        self._journal("path_created")
        try:
            counts.start_analysis += 1
            try:
                started = self._ec2.start_network_insights_analysis(NetworkInsightsPathId=path_id)
                analysis = started["NetworkInsightsAnalysis"]
                state.analysis_id = analysis["NetworkInsightsAnalysisId"]
                state.start_date = _iso(analysis.get("StartDate"))
                state.status = analysis.get("Status")
            except Exception:
                self._finish(
                    HookOutcome.ANALYSIS_NOT_STARTED, "StartNetworkInsightsAnalysis failed"
                )
                return
            self._journal("analysis_started")
            final = self._wait(state.analysis_id)
            if final is None:
                return
            state.raw_analysis = _sanitize(final)
            state.status = final.get("Status")
            state.network_path_found = final.get("NetworkPathFound")
            state.start_date = _iso(final.get("StartDate")) or state.start_date
            proposed = propose_evidence(
                analysis=final,
                path_id=path_id,
                source_interface_id=state.network_interface_id,
                destination_ip=destination,
            )
            state.proposed_evidence = proposed
            try:
                parse_reachability_evidence(json.dumps(proposed).encode("utf-8"))
                state.evidence_parses = True
            except Exception:
                state.evidence_parses = False
            self._journal("evidence_proposed")
            if not state.evidence_parses:
                self._finish(
                    HookOutcome.EVIDENCE_UNPARSEABLE,
                    "the proposed evidence fails the accepted parser",
                )
            else:
                self._finish(HookOutcome.COMPLETED)
        finally:
            self._cleanup()

    def _wait(self, analysis_id: str) -> dict[str, Any] | None:
        state, counts = self.state, self.state.counts
        started = self._monotonic()
        polls = 0
        while True:
            if (
                polls >= MAX_POLLS
                or self._monotonic() - started + POLL_INTERVAL_SECONDS > POLL_CEILING_SECONDS
            ):
                self._finish(
                    HookOutcome.ANALYSIS_TIMEOUT, "the analysis did not finish inside the ceiling"
                )
                return None
            self._sleep(POLL_INTERVAL_SECONDS)
            polls += 1
            counts.describe_analysis += 1
            try:
                response = self._ec2.describe_network_insights_analyses(
                    NetworkInsightsAnalysisIds=[analysis_id]
                )
                analyses = response["NetworkInsightsAnalyses"]
                if (
                    len(analyses) != 1
                    or analyses[0].get("NetworkInsightsAnalysisId") != analysis_id
                ):
                    raise ValueError("not exactly this analysis")
                analysis = analyses[0]
            except Exception:
                self._finish(
                    HookOutcome.OBSERVATION_FAILED, "DescribeNetworkInsightsAnalyses failed"
                )
                return None
            state.status = analysis.get("Status")
            if state.status in ("succeeded", "failed"):
                self._journal(f"analysis_terminal:{state.status}")
                return dict(analysis)
            if state.status != "running":
                self._finish(HookOutcome.OBSERVATION_FAILED, "an undocumented analysis status")
                return None

    def _cleanup(self) -> None:
        state, counts = self.state, self.state.counts
        if state.analysis_id is not None and counts.delete_analysis < MAX_DELETE_ANALYSIS:
            counts.delete_analysis += 1
            try:
                self._ec2.delete_network_insights_analysis(
                    NetworkInsightsAnalysisId=state.analysis_id
                )
            except Exception:
                state.cleanup_failures.append("delete_analysis")
        if state.path_id is not None and counts.delete_path < MAX_DELETE_PATH:
            counts.delete_path += 1
            try:
                self._ec2.delete_network_insights_path(NetworkInsightsPathId=state.path_id)
            except Exception:
                state.cleanup_failures.append("delete_path")
        self._journal("cleanup_attempted")


def cleanup_from_log(log_path: Path, ec2: NetworkInsightsClient) -> dict[str, Any]:
    """Bounded recovery after an interruption: delete exactly the ids the log names, once
    each, and record the result in the log. Never creates, never re-analyses."""
    document = json.loads(log_path.read_bytes())
    if document.get("contract_id") != LOG_CONTRACT_ID:
        raise ValueError("not a reachability hook log")
    counts = document.setdefault("counts", {})
    failures = document.setdefault("cleanup_failures", [])
    result: dict[str, Any] = {"deleted_analysis": False, "deleted_path": False}
    if document.get("analysis_id") and counts.get("delete_analysis", 0) < MAX_DELETE_ANALYSIS:
        counts["delete_analysis"] = counts.get("delete_analysis", 0) + 1
        try:
            ec2.delete_network_insights_analysis(NetworkInsightsAnalysisId=document["analysis_id"])
            result["deleted_analysis"] = True
        except Exception:
            failures.append("delete_analysis:recovery")
    if document.get("path_id") and counts.get("delete_path", 0) < MAX_DELETE_PATH:
        counts["delete_path"] = counts.get("delete_path", 0) + 1
        try:
            ec2.delete_network_insights_path(NetworkInsightsPathId=document["path_id"])
            result["deleted_path"] = True
        except Exception:
            failures.append("delete_path:recovery")
    document.setdefault("events", []).append(
        {"at": datetime.now(UTC).isoformat(), "event": "cleanup_from_log"}
    )
    log_path.write_bytes(canonical_bytes(document))
    return result


__all__ = [
    "LOG_CONTRACT_ID",
    "MAX_CREATE_PATH",
    "MAX_DELETE_ANALYSIS",
    "MAX_DELETE_PATH",
    "MAX_DESCRIBE_TASK",
    "MAX_POLLS",
    "MAX_START_ANALYSIS",
    "POLL_CEILING_SECONDS",
    "POLL_INTERVAL_SECONDS",
    "HookCounts",
    "HookOutcome",
    "HookState",
    "NetworkInsightsClient",
    "ReachabilityTarget",
    "ReachabilityWatcher",
    "cleanup_from_log",
    "propose_evidence",
]
