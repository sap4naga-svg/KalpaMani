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
   destination = the compiled address, tcp/443) and one ``StartNetworkInsightsAnalysis``,
   each carrying the invocation's own token as a client token **and as a tag**, journaled
   before the call -- so a resource whose creation succeeded but whose identifier never
   reached the journal is still attributable to this invocation and to nothing else
   (:func:`cleanup_from_log`). The analysis ``startDate`` is what the API returned, never
   the clock here.
3. **Bounded wait.** ``DescribeNetworkInsightsAnalyses`` on that analysis at
   ``POLL_INTERVAL_SECONDS`` for at most ``MAX_POLLS`` polls / ``POLL_CEILING_SECONDS``
   on the injected monotonic clock; ``running`` past the ceiling is
   ``ANALYSIS_TIMEOUT`` (the analysis is still deleted). The wait sits between the
   launcher's release and its terminal observation, whose own ceiling starts afterwards
   and is not extended by it.
4. **Evidence.** The documented fields are transcribed verbatim into a **proposed**
   ``kalpamani-reachability-evidence/v1`` document beside the raw response. It is a
   proposal, never an attestation: ``evidence_is_owner_attested`` is always ``false`` in
   the log, the owner attests D-16 separately, and the verdict tool parses the attested
   document closed. A proposal the accepted parser refuses is ``EVIDENCE_UNPARSEABLE``
   and still written raw; nothing is invented to make it parse.
5. **Cleanup.** The analysis, then the path -- only what this invocation created, each
   once. An analysis whose start succeeded but whose id was not parsed is found through
   the path this invocation created and deleted (bounded); a failure is recorded beside
   the outcome, never hidden, never retried.

Every step is journaled to one owner-only private log **before** the next operation, so
an interruption leaves the ids -- or, before an id existed, the token that names the
resource -- on disk for the bounded :func:`cleanup_from_log`, and never a silent residue.

The hook's outcome is its own record: the launcher swallows exceptions
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
import re
import secrets
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
#: Attribution lookups during cleanup or recovery: one listing each, and at most this
#: many resources found under this invocation's token or path are deleted.
MAX_ATTRIBUTION_LOOKUPS: Final = 1
MAX_ATTRIBUTED_DELETES: Final = 5
LOG_CONTRACT_ID: Final = "kalpamani-reachability-hook-log/v1"
#: The tag that names the invocation on every resource it creates.
INVOCATION_TAG_KEY: Final = "kalpamani:r2-invocation"
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
    """The six EC2 operations the watcher and its recovery use (``boto3`` ``ec2``-shaped)."""

    def create_network_insights_path(self, **kwargs: Any) -> Any: ...
    def start_network_insights_analysis(self, **kwargs: Any) -> Any: ...
    def describe_network_insights_analyses(self, **kwargs: Any) -> Any: ...
    def describe_network_insights_paths(self, **kwargs: Any) -> Any: ...
    def delete_network_insights_analysis(self, **kwargs: Any) -> Any: ...
    def delete_network_insights_path(self, **kwargs: Any) -> Any: ...


@dataclass(slots=True, kw_only=True)
class HookCounts:
    """What the watcher asked of its clients."""

    describe_task: int = 0
    create_path: int = 0
    start_analysis: int = 0
    describe_analysis: int = 0
    describe_paths: int = 0
    delete_analysis: int = 0
    delete_path: int = 0

    def document(self) -> dict[str, int]:
        """A plain mapping."""
        return {
            "describe_task": self.describe_task,
            "create_path": self.create_path,
            "start_analysis": self.start_analysis,
            "describe_analysis": self.describe_analysis,
            "describe_paths": self.describe_paths,
            "delete_analysis": self.delete_analysis,
            "delete_path": self.delete_path,
        }


@dataclass(slots=True, kw_only=True)
class HookState:
    """Everything the watcher established, journaled as it goes."""

    #: The token that names this invocation on every resource it creates (tag + client
    #: token); minted at construction and journaled before any operation.
    invocation_token: str = field(default_factory=lambda: secrets.token_hex(16))
    outcome: HookOutcome | None = None
    reason: str | None = None
    task_arn: str | None = None
    held_observed_at: str | None = None
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

    def __repr__(self) -> str:
        """Outcome only. **Never an ARN, an interface or a resource id.**"""
        outcome = None if self.outcome is None else self.outcome.value
        return f"HookState(outcome={outcome!r})"

    def document(self) -> dict[str, Any]:
        """The private log document (owner-only; never printed)."""
        return {
            "contract_id": LOG_CONTRACT_ID,
            "schema_version": 1,
            "invocation_token": self.invocation_token,
            "outcome": None if self.outcome is None else self.outcome.value,
            "reason": self.reason,
            "task_arn": self.task_arn,
            "held_observed_at": self.held_observed_at,
            "network_interface_id": self.network_interface_id,
            "path_id": self.path_id,
            "analysis_id": self.analysis_id,
            "start_date": self.start_date,
            "status": self.status,
            "network_path_found": self.network_path_found,
            "raw_analysis": self.raw_analysis,
            "proposed_evidence": self.proposed_evidence,
            "evidence_parses": self.evidence_parses,
            "evidence_is_owner_attested": False,
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


def failure_code(error: BaseException) -> str:
    """The closed, sanitized name of a failure for the journal: the exception class and,
    for an SDK client error, the service's error code -- never the message, which can
    carry an ARN, an interface id or an account."""
    name = type(error).__name__
    response = getattr(error, "response", None)
    code = None
    if isinstance(response, Mapping):
        inner = response.get("Error")
        if isinstance(inner, Mapping) and isinstance(inner.get("Code"), str):
            code = inner["Code"]
    if code is None or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", code):
        return name
    return f"{name}:{code}"


def _tag_specification(resource_type: str, token: str) -> list[dict[str, Any]]:
    return [{"ResourceType": resource_type, "Tags": [{"Key": INVOCATION_TAG_KEY, "Value": token}]}]


def _tagged_with(entry: Mapping[str, Any], token: str) -> bool:
    tags = entry.get("Tags")
    if not isinstance(tags, list):
        return False
    return any(
        isinstance(tag, Mapping)
        and tag.get("Key") == INVOCATION_TAG_KEY
        and tag.get("Value") == token
        for tag in tags
    )


def propose_evidence(
    *, analysis: Mapping[str, Any], path_id: str, source_interface_id: str, destination_ip: str
) -> dict[str, Any]:
    """The ``kalpamani-reachability-evidence/v1`` document proposed from one
    ``NetworkInsightsAnalysis`` response, field by field from the documented attributes.
    A proposal: the owner's attestation is a separate act, and the accepted parser decides
    admission of the attested document."""
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


def _delete_attributed_analyses(
    ec2: NetworkInsightsClient, *, path_id: str, token: str, counts: dict[str, int]
) -> tuple[list[str], list[str]]:
    """Delete every analysis of ``path_id`` carrying this invocation's tag (one listing,
    bounded deletes). The path is this invocation's, so its analyses are too; the tag is
    checked on each entry regardless. Returns (deleted ids, failures)."""
    deleted: list[str] = []
    failures: list[str] = []
    if counts.get("describe_analysis_by_path", 0) >= MAX_ATTRIBUTION_LOOKUPS:
        return deleted, failures
    counts["describe_analysis_by_path"] = counts.get("describe_analysis_by_path", 0) + 1
    try:
        response = ec2.describe_network_insights_analyses(NetworkInsightsPathId=path_id)
        entries = response.get("NetworkInsightsAnalyses") or []
    except Exception:
        failures.append("describe_analyses_by_path")
        return deleted, failures
    for entry in entries[:MAX_ATTRIBUTED_DELETES]:
        if not isinstance(entry, Mapping) or not _tagged_with(entry, token):
            continue
        analysis_id = entry.get("NetworkInsightsAnalysisId")
        if not isinstance(analysis_id, str):
            continue
        counts["delete_analysis"] = counts.get("delete_analysis", 0) + 1
        try:
            ec2.delete_network_insights_analysis(NetworkInsightsAnalysisId=analysis_id)
            deleted.append(analysis_id)
        except Exception:
            failures.append("delete_analysis:attributed")
    return deleted, failures


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
        state.held_observed_at = _iso(held.observed_at)
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
        except Exception as error:
            self._finish(
                HookOutcome.ATTRIBUTION_REFUSED, f"DescribeTasks failed: {failure_code(error)}"
            )
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
        token = state.invocation_token
        # The request is journaled (with the token that will tag the resource) BEFORE the
        # call: a path created but never acknowledged is still ours to find and delete.
        counts.create_path += 1
        self._journal("create_path_requested")
        try:
            created = self._ec2.create_network_insights_path(
                Source=state.network_interface_id,
                DestinationIp=destination,
                DestinationPort=PROBE_PORT,
                Protocol=PROBE_PROTOCOL,
                ClientToken=f"{token}-path",
                TagSpecifications=_tag_specification("network-insights-path", token),
            )
            path_id = created["NetworkInsightsPath"]["NetworkInsightsPathId"]
            if type(path_id) is not str:
                raise TypeError("path id")
        except Exception as error:
            self._finish(
                HookOutcome.PATH_NOT_CREATED,
                f"CreateNetworkInsightsPath failed: {failure_code(error)}",
            )
            return
        state.path_id = path_id
        self._journal("path_created")
        try:
            counts.start_analysis += 1
            self._journal("start_analysis_requested")
            try:
                started = self._ec2.start_network_insights_analysis(
                    NetworkInsightsPathId=path_id,
                    ClientToken=f"{token}-analysis",
                    TagSpecifications=_tag_specification("network-insights-analysis", token),
                )
                analysis = started["NetworkInsightsAnalysis"]
                analysis_id = analysis["NetworkInsightsAnalysisId"]
                if type(analysis_id) is not str:
                    raise TypeError("analysis id")
                state.analysis_id = analysis_id
                state.start_date = _iso(analysis.get("StartDate"))
                state.status = analysis.get("Status")
            except Exception as error:
                self._finish(
                    HookOutcome.ANALYSIS_NOT_STARTED,
                    f"StartNetworkInsightsAnalysis failed: {failure_code(error)}",
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
            except Exception as error:
                self._finish(
                    HookOutcome.OBSERVATION_FAILED,
                    f"DescribeNetworkInsightsAnalyses failed: {failure_code(error)}",
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
        """The analysis, then the path -- only this invocation's, each once.

        A start whose call may have succeeded without an id (``analysis_id`` unknown while
        ``start_analysis`` was requested) is resolved through the path this invocation
        created: its analyses carrying the invocation tag are deleted, bounded, before the
        path is. Failures are recorded and never retried.
        """
        state, counts = self.state, self.state.counts
        if state.path_id is not None and state.analysis_id is None and counts.start_analysis:
            scratch = {"delete_analysis": counts.delete_analysis}
            _deleted, failures = _delete_attributed_analyses(
                self._ec2, path_id=state.path_id, token=state.invocation_token, counts=scratch
            )
            counts.delete_analysis = scratch["delete_analysis"]
            counts.describe_analysis += scratch.get("describe_analysis_by_path", 0)
            state.cleanup_failures.extend(failures)
        if state.analysis_id is not None and counts.delete_analysis < MAX_DELETE_ANALYSIS:
            counts.delete_analysis += 1
            try:
                self._ec2.delete_network_insights_analysis(
                    NetworkInsightsAnalysisId=state.analysis_id
                )
            except Exception as error:
                state.cleanup_failures.append(f"delete_analysis:{failure_code(error)}")
        if state.path_id is not None and counts.delete_path < MAX_DELETE_PATH:
            counts.delete_path += 1
            try:
                self._ec2.delete_network_insights_path(NetworkInsightsPathId=state.path_id)
            except Exception as error:
                state.cleanup_failures.append(f"delete_path:{failure_code(error)}")
        self._journal("cleanup_attempted")


def cleanup_from_log(log_path: Path, ec2: NetworkInsightsClient) -> dict[str, Any]:
    """Bounded recovery after an interruption, from the journal alone.

    Attribution is by what the journal proves this invocation asked for: a path id, an
    analysis id, or -- when a create or start was requested but no id was journaled --
    the invocation token that tagged the resource. One tag-filtered
    ``DescribeNetworkInsightsPaths`` finds a path created but unacknowledged; one
    ``DescribeNetworkInsightsAnalyses`` on this invocation's path finds an analysis started
    but unacknowledged; only entries carrying the token are deleted, at most
    ``MAX_ATTRIBUTED_DELETES``. A delete the invocation already attempted is never retried;
    a recovery already made is not repeated. Never creates, never re-analyses, never
    touches a resource the journal cannot attribute to this invocation. The result is
    written back into the log.
    """
    document = json.loads(log_path.read_bytes())
    if document.get("contract_id") != LOG_CONTRACT_ID:
        raise ValueError("not a reachability hook log")
    token = document.get("invocation_token")
    if type(token) is not str or not token:
        raise ValueError("the log names no invocation token")
    counts = document.setdefault("counts", {})
    failures = document.setdefault("cleanup_failures", [])
    result: dict[str, Any] = {
        "deleted_analyses": [],
        "deleted_paths": [],
        "recovered_path_ids": [],
    }
    path_ids: list[str] = []
    if isinstance(document.get("path_id"), str):
        path_ids.append(document["path_id"])
    elif counts.get("create_path", 0) and counts.get("describe_paths", 0) < MAX_ATTRIBUTION_LOOKUPS:
        # Created, perhaps, but never acknowledged: find it by this invocation's tag only.
        counts["describe_paths"] = counts.get("describe_paths", 0) + 1
        try:
            response = ec2.describe_network_insights_paths(
                Filters=[{"Name": f"tag:{INVOCATION_TAG_KEY}", "Values": [token]}]
            )
            for entry in (response.get("NetworkInsightsPaths") or [])[:MAX_ATTRIBUTED_DELETES]:
                if isinstance(entry, Mapping) and _tagged_with(entry, token):
                    path_id = entry.get("NetworkInsightsPathId")
                    if isinstance(path_id, str):
                        path_ids.append(path_id)
                        result["recovered_path_ids"].append(path_id)
        except Exception:
            failures.append("describe_paths:recovery")
    for path_id in path_ids:
        if isinstance(document.get("analysis_id"), str):
            if counts.get("delete_analysis", 0) < MAX_DELETE_ANALYSIS:
                counts["delete_analysis"] = counts.get("delete_analysis", 0) + 1
                try:
                    ec2.delete_network_insights_analysis(
                        NetworkInsightsAnalysisId=document["analysis_id"]
                    )
                    result["deleted_analyses"].append(document["analysis_id"])
                except Exception:
                    failures.append("delete_analysis:recovery")
        elif counts.get("start_analysis", 0):
            deleted, found_failures = _delete_attributed_analyses(
                ec2, path_id=path_id, token=token, counts=counts
            )
            result["deleted_analyses"].extend(deleted)
            failures.extend(f"{f}:recovery" for f in found_failures)
        if counts.get("delete_path", 0) < MAX_DELETE_PATH:
            counts["delete_path"] = counts.get("delete_path", 0) + 1
            try:
                ec2.delete_network_insights_path(NetworkInsightsPathId=path_id)
                result["deleted_paths"].append(path_id)
            except Exception:
                failures.append("delete_path:recovery")
    document.setdefault("events", []).append(
        {"at": datetime.now(UTC).isoformat(), "event": "cleanup_from_log"}
    )
    log_path.write_bytes(canonical_bytes(document))
    return result


__all__ = [
    "INVOCATION_TAG_KEY",
    "LOG_CONTRACT_ID",
    "MAX_ATTRIBUTED_DELETES",
    "MAX_ATTRIBUTION_LOOKUPS",
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
    "failure_code",
    "propose_evidence",
]
