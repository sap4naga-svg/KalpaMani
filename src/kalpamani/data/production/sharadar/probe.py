"""The build verification task's provider-origin probe, and the verdict it does NOT decide.

**Proposed ADR-0045 — not accepted, not in force.** ADR-0036 R-2 asks that "any provider-origin
connection attempt from the build subnet times out or is refused at the network layer", exercised by
"a deliberate probe in the verification image, not in the production image". This module is that
probe's contract and its evidence rule, exercised only against fakes.

**Two records, kept apart.** The probe produces an **observation** -- what one bounded connection
attempt to one destination at one instant returned -- and the observation is *never* an isolation
verdict. A timeout or a refusal is exactly what a destination failure, a remote rejection, a
resolver failure or a transient condition also produce, so a non-connection alone is
``INCONCLUSIVE``. ``CONNECTED`` **fails** the no-connectivity check for that destination and
instant. ``VERIFIED`` requires corroboration that attributes the non-connection to this account's
network controls, in the form :func:`isolation_verdict` states; what that corroboration is, and its
limits, is the proposed ADR's §3 -- nothing here collects it, and no permission is broadened.
The corroboration the ADR admits is one VPC Reachability Analyzer analysis, transcribed by the
owner into a closed document and **bound by derivation**: the verdict compares the analysis's own
source, destination, status, start time and explanations against the launch record and the
task's own destination binding, and never accepts a supplied match.

**The probe is bounded and value-free.** One destination, chosen deterministically from the
compiled origin address set (the lexicographically smallest resolved address that lies inside
the set); one TCP connection attempt to port 443 with a compiled timeout; **no request bytes**
-- no TLS handshake, no HTTP, no provider API request; a resolution failure makes **no** attempt
and counts none. The observation carries closed tokens and integers only -- never an address,
never a host -- plus, when an attempt was made, a **salted digest of the selected destination**
(``destination_binding_digest``: SHA-256 over the admitted input's digest, the address and the
port), so the launch tool can recover *which* compiled address the task actually selected from
its own record without the receipt disclosing it, and without inferring the task's DNS result
from a later resolution.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar.documents import (
    decode_document,
    exact_str,
    hex_digest,
    instant,
)
from kalpamani.data.production.sharadar.task_clients import PROVIDER_ORIGIN_HOST

#: The destination port of the one attempt: the provider's HTTPS origin.
PROBE_PORT: Final = 443
#: The compiled connection timeout, in seconds (proposed ADR-0045 §4).
PROBE_TIMEOUT_SECONDS: Final = 5.0
#: Exactly one attempt per verification task. Never more.
PROBE_MAX_ATTEMPTS: Final = 1

_HEX_64: Final = re.compile(r"[0-9a-f]{64}")


def destination_binding_digest(binding_key: str, address: str, port: int) -> str:
    """The privacy-preserving name of one selected destination: a keyed SHA-256.

    ``binding_key`` is the admitted input's digest -- a value the launch tool holds in its
    own record and a log reader does not -- so the digest identifies the address to the
    tool and to nobody else; the address space is small enough that an unkeyed digest
    would name it to anyone.
    """
    if type(binding_key) is not str or _HEX_64.fullmatch(binding_key) is None:
        raise ValueError("the binding key is the input digest: 64 lowercase hex")
    if type(address) is not str or type(port) is not int:
        raise TypeError("address must be a string and port an integer")
    return sha256_hex(
        canonical_bytes({"binding_key": binding_key, "address": address, "port": port})
    )


class ProbeResolution(StrEnum):
    """What resolving the pinned origin host produced, before any attempt."""

    RESOLVED_IN_SET = "RESOLVED_IN_SET"
    RESOLVED_OUTSIDE_SET = "RESOLVED_OUTSIDE_SET"
    UNRESOLVED = "UNRESOLVED"


class ProbeResult(StrEnum):
    """The observed result of the one connection attempt. Closed; an observation only."""

    CONNECTED = "CONNECTED"
    CONNECTION_REFUSED = "CONNECTION_REFUSED"
    TIMED_OUT = "TIMED_OUT"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


class IsolationVerdict(StrEnum):
    """The R-2 conclusion, decided by :func:`isolation_verdict` and never by the probe alone."""

    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    VERIFIED = "VERIFIED"


class ProbeAdapter(Protocol):
    """The one operation the probe may perform: a bounded TCP connect, no bytes sent."""

    def connect(self, address: str, port: int, timeout_seconds: float) -> ProbeResult:
        """Attempt one TCP connection; return a closed result; send nothing."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ProbeObservation:
    """What the verification task observed. Closed tokens and counts; no address, no host."""

    resolution: ProbeResolution
    result: ProbeResult
    attempts: int
    #: The keyed digest of the selected destination; present exactly when an attempt was made.
    destination_digest: str | None = None

    def __post_init__(self) -> None:
        """A resolution that made no attempt has no attempt; an attempt has exactly one."""
        if type(self.resolution) is not ProbeResolution or type(self.result) is not ProbeResult:
            raise TypeError("resolution and result must be exact members")
        if type(self.attempts) is not int or self.attempts < 0:
            raise TypeError("attempts must be a non-negative integer")
        attempted = self.resolution is ProbeResolution.RESOLVED_IN_SET
        if attempted != (self.attempts == PROBE_MAX_ATTEMPTS):
            raise ValueError("exactly one attempt follows an in-set resolution, and none otherwise")
        if attempted == (self.result is ProbeResult.NOT_ATTEMPTED):
            raise ValueError("NOT_ATTEMPTED is the result exactly when no attempt was made")
        if self.destination_digest is not None and (
            type(self.destination_digest) is not str
            or _HEX_64.fullmatch(self.destination_digest) is None
        ):
            raise ValueError("a destination digest is 64 lowercase hex")
        if attempted != (self.destination_digest is not None):
            raise ValueError("an attempt binds exactly one destination digest, and none otherwise")

    def document(self) -> dict[str, object]:
        """The closed receipt block."""
        return {
            "resolution": self.resolution.value,
            "result": self.result.value,
            "attempts": self.attempts,
            "destination_digest": self.destination_digest,
        }

    def __repr__(self) -> str:
        """Tokens and the count only."""
        return (
            f"ProbeObservation(resolution={self.resolution.value!r}, "
            f"result={self.result.value!r}, attempts={self.attempts})"
        )


def parse_probe_observation(raw: object) -> ProbeObservation:
    """The closed block back into an observation, or ``ValueError``/``TypeError``."""
    fields = {"resolution", "result", "attempts", "destination_digest"}
    if type(raw) is not dict or set(raw) != fields:
        raise ValueError("a probe observation carries exactly its four closed fields")
    resolution, result, attempts = raw["resolution"], raw["result"], raw["attempts"]
    digest = raw["destination_digest"]
    if type(resolution) is not str or type(result) is not str or type(attempts) is not int:
        raise ValueError("a probe observation's fields are two tokens and one integer")
    if digest is not None and type(digest) is not str:
        raise ValueError("a destination digest is a string or null")
    if resolution not in {m.value for m in ProbeResolution}:
        raise ValueError("unknown resolution")
    if result not in {m.value for m in ProbeResult}:
        raise ValueError("unknown result")
    return ProbeObservation(
        resolution=ProbeResolution(resolution),
        result=ProbeResult(result),
        attempts=attempts,
        destination_digest=digest,
    )


def select_destination(
    compiled: frozenset[str], resolved: Iterable[object]
) -> tuple[ProbeResolution, str | None]:
    """The one destination the probe may attempt, or why none is attempted.

    ``resolved`` is what the injected resolver returned for the pinned origin host. The
    destination is the lexicographically smallest resolved IPv4 literal, and it is
    attempted only when **every** resolved address lies inside the compiled set -- the
    accepted origin rule (``origin_address_refusal``), applied to the probe: a set the
    origin has partly left is stale, and a probe against it observes nothing about the
    current provider. Deterministic, so the launch tool can name the destination from
    its own record without the task disclosing it.
    """
    if type(compiled) is not frozenset:
        raise TypeError("compiled must be a frozenset")
    addresses: list[str] = []
    for candidate in resolved:
        if type(candidate) is not str:
            return ProbeResolution.UNRESOLVED, None
        try:
            ipaddress.IPv4Address(candidate)
        except ValueError:
            return ProbeResolution.UNRESOLVED, None
        addresses.append(candidate)
    if not addresses:
        return ProbeResolution.UNRESOLVED, None
    if any(address not in compiled for address in addresses):
        return ProbeResolution.RESOLVED_OUTSIDE_SET, None
    return ProbeResolution.RESOLVED_IN_SET, sorted(addresses)[0]


def run_origin_probe(
    *,
    compiled: frozenset[str],
    resolve: Callable[[str], Iterable[object]],
    adapter: ProbeAdapter,
    binding_key: str,
) -> ProbeObservation:
    """Resolve, select, attempt at most once; never raise; never send a byte.

    A resolver that raises is ``UNRESOLVED`` with zero attempts. An adapter that raises
    is ``CONNECTION_ERROR`` -- the attempt was made and is counted. ``binding_key`` is
    the admitted input's digest, under which the selected destination is bound.
    """
    try:
        resolved = list(resolve(PROVIDER_ORIGIN_HOST))
    except Exception:
        return ProbeObservation(
            resolution=ProbeResolution.UNRESOLVED, result=ProbeResult.NOT_ATTEMPTED, attempts=0
        )
    resolution, destination = select_destination(compiled, resolved)
    if destination is None:
        return ProbeObservation(resolution=resolution, result=ProbeResult.NOT_ATTEMPTED, attempts=0)
    try:
        result = adapter.connect(destination, PROBE_PORT, PROBE_TIMEOUT_SECONDS)
    except Exception:
        result = ProbeResult.CONNECTION_ERROR
    if type(result) is not ProbeResult or result is ProbeResult.NOT_ATTEMPTED:
        result = ProbeResult.CONNECTION_ERROR
    return ProbeObservation(
        resolution=resolution,
        result=result,
        attempts=PROBE_MAX_ATTEMPTS,
        destination_digest=destination_binding_digest(binding_key, destination, PROBE_PORT),
    )


# ---------------------------------------------------------------------------
# The isolation verdict -- corroboration is the proposed ADR's, and is recorded by the owner
# ---------------------------------------------------------------------------


class CorroborationKind(StrEnum):
    """The corroboration sources the proposed ADR names. Closed."""

    #: A VPC Reachability Analyzer analysis from the verification task's network
    #: interface to the probe destination, TCP/443, returning *not reachable* with at
    #: least one blocking component inside the compiled build placement.
    REACHABILITY_ANALYSIS = "REACHABILITY_ANALYSIS"


class BlockingComponent(StrEnum):
    """Path components that attribute a block to this VPC's own controls (documented set)."""

    ROUTE_TABLE = "ROUTE_TABLE"
    SECURITY_GROUP = "SECURITY_GROUP"
    NETWORK_ACL = "NETWORK_ACL"
    SUBNET = "SUBNET"


#: The explanation codes the documented Reachability Analyzer vocabulary attributes to a
#: control of the analysed VPC, and the component kind each attributes it to
#: (https://docs.aws.amazon.com/vpc/latest/reachability/explanation-codes.html). A code
#: outside this table -- ``NO_PATH``, ``NO_POSSIBLE_DESTINATION``, ``UNKNOWN_*``,
#: ``VPC_BLOCK_PUBLIC_ACCESS_ENABLED`` and every load-balancer, gateway, peering and
#: transit code -- attributes nothing to the four components the ADR admits and leaves
#: the verdict INCONCLUSIVE; extending the table is an ADR amendment, not an edit.
ADMITTED_EXPLANATIONS: Final[dict[str, BlockingComponent]] = {
    "ENI_SG_RULES_MISMATCH": BlockingComponent.SECURITY_GROUP,
    "SG_HAS_NO_RULES": BlockingComponent.SECURITY_GROUP,
    "SUBNET_ACL_RESTRICTION": BlockingComponent.NETWORK_ACL,
    "NO_ROUTE_TO_DESTINATION": BlockingComponent.ROUTE_TABLE,
}

#: The analysis status that carries a result (documented: ``running | succeeded | failed``).
ANALYSIS_SUCCEEDED: Final = "succeeded"
ANALYSIS_STATUSES: Final[frozenset[str]] = frozenset({"running", "succeeded", "failed"})
#: The path protocol the probe uses (documented values ``tcp | udp``).
PROBE_PROTOCOL: Final = "tcp"

REACHABILITY_EVIDENCE_CONTRACT_ID: Final = "kalpamani-reachability-evidence/v1"
REACHABILITY_EVIDENCE_SCHEMA_VERSION: Final = 1
#: An evidence document is one analysis; a ceiling keeps a mistaken file out.
MAX_REACHABILITY_EVIDENCE_BYTES: Final = 64 * 1024
#: The most explanations one evidence document may carry.
MAX_EXPLANATIONS: Final = 32

_ANALYSIS_ID_RE: Final = re.compile(r"nia-[0-9a-f]{8,32}")
_PATH_ID_RE: Final = re.compile(r"nip-[0-9a-f]{8,32}")
_INTERFACE_ID_RE: Final = re.compile(r"eni-[0-9a-f]{8,17}")
_COMPONENT_ID_RE: Final = re.compile(r"[a-z]{2,8}-[0-9a-f]{8,17}")
_EVIDENCE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "analysis_id",
        "path_id",
        "status",
        "network_path_found",
        "start_date",
        "source_interface_id",
        "destination_ip",
        "destination_port",
        "protocol",
        "explanations",
    }
)
_EXPLANATION_FIELDS: Final[frozenset[str]] = frozenset(
    {"explanation_code", "component_kind", "component_id", "subnet_id"}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReachabilityExplanation:
    """One explanation the analysis returned, reduced to what attribution needs.

    ``component_kind`` is the documented component object the explanation names
    (``securityGroup``, ``acl``, ``routeTable``/``subnetRouteTable``, ``subnet``), as the
    owner transcribed it; ``component_id`` that component's id; ``subnet_id`` the
    explanation's ``subnet`` component when one is named beside the component.
    """

    explanation_code: str
    component_kind: BlockingComponent | None
    component_id: str | None
    subnet_id: str | None

    def __repr__(self) -> str:
        """The code and the kind; never an identifier."""
        kind = None if self.component_kind is None else self.component_kind.value
        return f"ReachabilityExplanation(code={self.explanation_code!r}, kind={kind!r})"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReachabilityEvidence:
    """One Reachability Analyzer analysis, transcribed by the owner and parsed closed.

    The fields are the documented ``NetworkInsightsAnalysis`` and ``NetworkInsightsPath``
    attributes the verdict binds to -- analysis and path identity, status, the
    ``networkPathFound`` result, ``startDate``, the path's source (a network interface
    id), destination IP, port and protocol -- and the explanations. **This is
    configuration-model evidence**: the analyzer evaluates the account's network
    configuration and sends no packets; it is never a packet observation and is never
    read as one.
    """

    kind: CorroborationKind
    analysis_id: str
    path_id: str
    status: str
    network_path_found: bool
    start_date: datetime
    source_interface_id: str
    destination_ip: str
    destination_port: int
    protocol: str
    explanations: tuple[ReachabilityExplanation, ...]

    def __repr__(self) -> str:
        """Status and result only; never an id, an address or an interface."""
        return (
            f"ReachabilityEvidence(status={self.status!r}, "
            f"network_path_found={self.network_path_found})"
        )


def _evidence_error(message: str) -> ValueError:
    return ValueError(message)


def parse_reachability_evidence(raw: object) -> ReachabilityEvidence:
    """The evidence document, every field to its documented grammar, or ``ValueError``."""
    try:
        document = decode_document(raw, max_bytes=MAX_REACHABILITY_EVIDENCE_BYTES)
    except Exception:
        raise _evidence_error("the reachability evidence is not a readable document") from None
    if type(document) is not dict or set(document) != _EVIDENCE_FIELDS:
        raise _evidence_error("the reachability evidence carries exactly the closed fields")
    if document["schema_version"] != REACHABILITY_EVIDENCE_SCHEMA_VERSION:
        raise _evidence_error("unknown reachability evidence schema version")
    if document["contract_id"] != REACHABILITY_EVIDENCE_CONTRACT_ID:
        raise _evidence_error("unknown reachability evidence contract")
    analysis_id = exact_str(document["analysis_id"])
    path_id = exact_str(document["path_id"])
    status = exact_str(document["status"])
    start_date = instant(document["start_date"])
    source = exact_str(document["source_interface_id"])
    destination_ip = exact_str(document["destination_ip"])
    port = document["destination_port"]
    protocol = exact_str(document["protocol"])
    found = document["network_path_found"]
    if (
        analysis_id is None
        or _ANALYSIS_ID_RE.fullmatch(analysis_id) is None
        or path_id is None
        or _PATH_ID_RE.fullmatch(path_id) is None
        or status not in ANALYSIS_STATUSES
        or start_date is None
        or source is None
        or _INTERFACE_ID_RE.fullmatch(source) is None
        or destination_ip is None
        or type(port) is not int
        or not 0 <= port <= 65535
        or protocol not in ("tcp", "udp")
        or type(found) is not bool
    ):
        raise _evidence_error("a reachability evidence field is outside its documented grammar")
    try:
        ipaddress.IPv4Address(destination_ip)
    except ValueError:
        raise _evidence_error("the destination is not an IPv4 literal") from None
    raw_explanations = document["explanations"]
    if type(raw_explanations) is not list or len(raw_explanations) > MAX_EXPLANATIONS:
        raise _evidence_error("explanations must be a bounded list")
    explanations: list[ReachabilityExplanation] = []
    for entry in raw_explanations:
        if type(entry) is not dict or set(entry) != _EXPLANATION_FIELDS:
            raise _evidence_error("an explanation carries exactly the closed fields")
        code = exact_str(entry["explanation_code"])
        kind_value = entry["component_kind"]
        component_id = entry["component_id"]
        subnet_id = entry["subnet_id"]
        if code is None or not re.fullmatch(r"[A-Z0-9_]{1,64}", code):
            raise _evidence_error("an explanation code is an upper-case documented token")
        kind: BlockingComponent | None = None
        if kind_value is not None:
            if type(kind_value) is not str or kind_value not in {
                m.value for m in BlockingComponent
            }:
                raise _evidence_error("component_kind must be a documented component or null")
            kind = BlockingComponent(kind_value)
        for value in (component_id, subnet_id):
            if value is not None and (
                type(value) is not str or _COMPONENT_ID_RE.fullmatch(value) is None
            ):
                raise _evidence_error("a component id must be a resource id or null")
        if (kind is None) != (component_id is None):
            raise _evidence_error("a component kind and its id come together")
        explanations.append(
            ReachabilityExplanation(
                explanation_code=code,
                component_kind=kind,
                component_id=component_id,
                subnet_id=subnet_id,
            )
        )
    return ReachabilityEvidence(
        kind=CorroborationKind.REACHABILITY_ANALYSIS,
        analysis_id=analysis_id,
        path_id=path_id,
        status=status,
        network_path_found=found,
        start_date=start_date,
        source_interface_id=source,
        destination_ip=destination_ip,
        destination_port=port,
        protocol=protocol,
        explanations=tuple(explanations),
    )


class VerdictReason(StrEnum):
    """Why the verdict is what it is. Closed; one per verdict; never a value."""

    OBSERVED_CONNECTION = "OBSERVED_CONNECTION"
    NO_ATTEMPT = "NO_ATTEMPT"
    DESTINATION_UNBOUND = "DESTINATION_UNBOUND"
    NO_CORROBORATION = "NO_CORROBORATION"
    ANALYSIS_NOT_SUCCEEDED = "ANALYSIS_NOT_SUCCEEDED"
    SOURCE_MISMATCH = "SOURCE_MISMATCH"
    DESTINATION_MISMATCH = "DESTINATION_MISMATCH"
    ANALYSIS_OUTSIDE_TASK_WINDOW = "ANALYSIS_OUTSIDE_TASK_WINDOW"
    PATH_FOUND_CONTRADICTS_OBSERVATION = "PATH_FOUND_CONTRADICTS_OBSERVATION"
    UNSUPPORTED_EXPLANATION = "UNSUPPORTED_EXPLANATION"
    COMPONENT_OUTSIDE_PLACEMENT = "COMPONENT_OUTSIDE_PLACEMENT"
    CORROBORATED = "CORROBORATED"


@dataclass(frozen=True, slots=True, kw_only=True)
class VerdictBinding:
    """What the launch tool knows about the task the observation came from.

    ``network_interface_id`` and ``subnet_id`` are the placement the launcher verified
    and the release named; ``security_group_ids`` the compiled groups; ``launched_at``
    and ``recorded_at`` bound the window in which the task's interface existed; and
    ``binding_key`` is the admitted input's digest, the salt the task bound its selected
    destination with; ``origin_addresses`` the compiled origin set the task selected from.
    """

    network_interface_id: str
    subnet_id: str
    security_group_ids: frozenset[str]
    launched_at: datetime
    recorded_at: datetime
    binding_key: str
    origin_addresses: frozenset[str]

    def __repr__(self) -> str:
        """A fixed token."""
        return "VerdictBinding(<private>)"


@dataclass(frozen=True, slots=True, kw_only=True)
class IsolationVerdictRecord:
    """The verdict, its one closed reason, and the components the evidence named."""

    verdict: IsolationVerdict
    reason: VerdictReason
    blocking_components: frozenset[BlockingComponent]
    analysis_bound: bool

    def document(self) -> dict[str, object]:
        """The sanitized evidence block: tokens only."""
        return {
            "verdict": self.verdict.value,
            "reason": self.reason.value,
            "blocking_components": sorted(c.value for c in self.blocking_components),
            "analysis_bound": self.analysis_bound,
        }


#: The verdict each reason implies, and whether the analysis was bound when it was given.
#: Transcribed from :func:`isolation_verdict`: a record whose fields disagree with this table
#: was not derived by it.
REASON_VERDICT: Final[dict[VerdictReason, tuple[IsolationVerdict, bool]]] = {
    VerdictReason.OBSERVED_CONNECTION: (IsolationVerdict.FAILED, False),
    VerdictReason.NO_ATTEMPT: (IsolationVerdict.INCONCLUSIVE, False),
    VerdictReason.DESTINATION_UNBOUND: (IsolationVerdict.INCONCLUSIVE, False),
    VerdictReason.NO_CORROBORATION: (IsolationVerdict.INCONCLUSIVE, False),
    VerdictReason.ANALYSIS_NOT_SUCCEEDED: (IsolationVerdict.INCONCLUSIVE, False),
    VerdictReason.SOURCE_MISMATCH: (IsolationVerdict.INCONCLUSIVE, False),
    VerdictReason.DESTINATION_MISMATCH: (IsolationVerdict.INCONCLUSIVE, False),
    VerdictReason.ANALYSIS_OUTSIDE_TASK_WINDOW: (IsolationVerdict.INCONCLUSIVE, False),
    VerdictReason.PATH_FOUND_CONTRADICTS_OBSERVATION: (IsolationVerdict.INCONCLUSIVE, True),
    VerdictReason.UNSUPPORTED_EXPLANATION: (IsolationVerdict.INCONCLUSIVE, True),
    VerdictReason.COMPONENT_OUTSIDE_PLACEMENT: (IsolationVerdict.INCONCLUSIVE, True),
    VerdictReason.CORROBORATED: (IsolationVerdict.VERIFIED, True),
}

#: Reasons a later corroboration for the SAME launch can resolve: each says the evidence
#: supplied was insufficient or unbound, not that the observation itself contradicts a
#: block. ``NO_ATTEMPT`` and ``DESTINATION_UNBOUND`` are about the probe and cannot be
#: resolved by evidence; ``PATH_FOUND_CONTRADICTS_OBSERVATION`` is a modelled path against
#: a non-connection and is a contradiction a later analysis does not erase.
RESOLVABLE_INSUFFICIENCIES: Final[frozenset[VerdictReason]] = frozenset(
    {
        VerdictReason.NO_CORROBORATION,
        VerdictReason.ANALYSIS_NOT_SUCCEEDED,
        VerdictReason.SOURCE_MISMATCH,
        VerdictReason.DESTINATION_MISMATCH,
        VerdictReason.ANALYSIS_OUTSIDE_TASK_WINDOW,
        VerdictReason.UNSUPPORTED_EXPLANATION,
        VerdictReason.COMPONENT_OUTSIDE_PLACEMENT,
    }
)


def parse_isolation_verdict_record(raw: object) -> IsolationVerdictRecord:
    """The closed verdict block back into a record, held to the derivation's own table.

    Raises ``ValueError`` for any shape, token or combination :func:`isolation_verdict`
    could not have produced: a verdict that is not its reason's, an analysis marked bound
    where the reason says it was not, components on any reason but ``CORROBORATED``, or
    ``CORROBORATED`` with none.
    """
    fields = {"verdict", "reason", "blocking_components", "analysis_bound"}
    if type(raw) is not dict or set(raw) != fields:
        raise ValueError("a verdict record carries exactly its four closed fields")
    verdict, reason = raw["verdict"], raw["reason"]
    components, bound = raw["blocking_components"], raw["analysis_bound"]
    if (
        type(verdict) is not str
        or verdict not in {m.value for m in IsolationVerdict}
        or type(reason) is not str
        or reason not in {m.value for m in VerdictReason}
        or type(bound) is not bool
        or type(components) is not list
        or any(
            type(c) is not str or c not in {m.value for m in BlockingComponent} for c in components
        )
        or len(set(components)) != len(components)
        or components != sorted(components)
    ):
        raise ValueError("a verdict record's fields are closed tokens and one boolean")
    expected_verdict, expected_bound = REASON_VERDICT[VerdictReason(reason)]
    if IsolationVerdict(verdict) is not expected_verdict or bound is not expected_bound:
        raise ValueError("the verdict and binding are not the reason's")
    if (VerdictReason(reason) is VerdictReason.CORROBORATED) != bool(components):
        raise ValueError("components are named exactly by a corroborated verdict")
    return IsolationVerdictRecord(
        verdict=IsolationVerdict(verdict),
        reason=VerdictReason(reason),
        blocking_components=frozenset(BlockingComponent(c) for c in components),
        analysis_bound=bound,
    )


ISOLATION_VERDICT_CONTRACT_ID: Final = "kalpamani-isolation-verdict/v1"
MAX_ISOLATION_VERDICT_BYTES: Final = 64 * 1024
_VERDICT_DOCUMENT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "actor",
        "kind",
        "specification_digest",
        "probe",
        "verdict",
        "evidence_supplied",
        "recorded_at",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class IsolationVerdictDocument:
    """The launch tool's verdict document, parsed closed and held consistent.

    ``specification_digest`` names the launch (the specification the authorization
    named and the reservation carries); ``probe`` is the receipt's observation; the
    verdict block is the derivation's; ``evidence_supplied`` says whether a transcription
    was handed in. A document whose blocks disagree -- a corroborated verdict over a
    ``CONNECTED`` probe, a corroboration with no evidence supplied, a
    ``NO_CORROBORATION`` reason beside supplied evidence, an attempt-dependent reason over
    a probe that made none -- was not written by the tool and is refused.
    """

    actor: str
    kind: str
    specification_digest: str
    probe: ProbeObservation
    verdict: IsolationVerdictRecord
    evidence_supplied: bool
    recorded_at: datetime

    def __repr__(self) -> str:
        """Verdict and reason only."""
        return (
            f"IsolationVerdictDocument(verdict={self.verdict.verdict.value!r}, "
            f"reason={self.verdict.reason.value!r})"
        )


def parse_isolation_verdict_document(raw: object) -> IsolationVerdictDocument:
    """One verdict document (bytes or an already-decoded object), or ``ValueError``."""
    try:
        document = (
            decode_document(raw, max_bytes=MAX_ISOLATION_VERDICT_BYTES)
            if type(raw) is bytes
            else raw
        )
    except Exception:
        raise ValueError("a verdict document decodes closed") from None
    if type(document) is not dict or set(document) != _VERDICT_DOCUMENT_FIELDS:
        raise ValueError("a verdict document carries exactly its closed fields")
    if document["schema_version"] != 1 or document["contract_id"] != ISOLATION_VERDICT_CONTRACT_ID:
        raise ValueError("a verdict document names its contract")
    actor = exact_str(document["actor"])
    kind = exact_str(document["kind"])
    digest = hex_digest(document["specification_digest"])
    supplied = document["evidence_supplied"]
    recorded_at = instant(document["recorded_at"])
    if (
        actor not in {"acquisition", "build"}
        or kind not in {"production", "verification"}
        or digest is None
        or type(supplied) is not bool
        or recorded_at is None
    ):
        raise ValueError("a verdict document's fields are closed tokens, a digest and an instant")
    probe = parse_probe_observation(document["probe"])
    verdict = parse_isolation_verdict_record(document["verdict"])
    reason = verdict.reason
    attempted = probe.attempts == PROBE_MAX_ATTEMPTS
    if (reason is VerdictReason.OBSERVED_CONNECTION) != (probe.result is ProbeResult.CONNECTED):
        raise ValueError("an observed connection is FAILED, and FAILED is an observed connection")
    if (reason is VerdictReason.NO_ATTEMPT) != (
        not attempted and probe.result is not ProbeResult.CONNECTED
    ):
        raise ValueError("NO_ATTEMPT is the reason exactly when the probe made no attempt")
    if reason is VerdictReason.NO_CORROBORATION and supplied:
        raise ValueError("NO_CORROBORATION contradicts supplied evidence")
    if (
        reason
        not in {
            VerdictReason.OBSERVED_CONNECTION,
            VerdictReason.NO_ATTEMPT,
            VerdictReason.DESTINATION_UNBOUND,
            VerdictReason.NO_CORROBORATION,
        }
        and not supplied
    ):
        raise ValueError("a reason about the evidence needs supplied evidence")
    return IsolationVerdictDocument(
        actor=actor,
        kind=kind,
        specification_digest=digest,
        probe=probe,
        verdict=verdict,
        evidence_supplied=supplied,
        recorded_at=recorded_at,
    )


def _record(
    verdict: IsolationVerdict,
    reason: VerdictReason,
    components: frozenset[BlockingComponent] = frozenset(),
    *,
    bound: bool = False,
) -> IsolationVerdictRecord:
    return IsolationVerdictRecord(
        verdict=verdict, reason=reason, blocking_components=components, analysis_bound=bound
    )


def bound_destination(binding: VerdictBinding, observation: ProbeObservation) -> str | None:
    """The address the task selected, recovered from its salted digest -- or ``None``.

    The task selected one address from the compiled set and recorded
    ``destination_binding_digest(binding_key, address, PROBE_PORT)``; the tool recomputes
    that digest for every compiled address and takes the one that matches. The DNS
    result is read from the task's own record, never from a later resolution and never
    assumed from the set.
    """
    if observation.destination_digest is None:
        return None
    for address in binding.origin_addresses:
        if destination_binding_digest(binding.binding_key, address, PROBE_PORT) == (
            observation.destination_digest
        ):
            return address
    return None


def isolation_verdict(
    observation: ProbeObservation,
    evidence: ReachabilityEvidence | None,
    *,
    binding: VerdictBinding,
) -> IsolationVerdictRecord:
    """The R-2 conclusion for one probe under the proposed ADR's rule, with its reason.

    - ``CONNECTED`` **fails**, whatever the evidence says: a configuration model that
      predicts a block does not undo an observed connection.
    - every other case is ``INCONCLUSIVE`` unless **all** of the following hold, each
      derived from the evidence and the binding and never supplied as a boolean: the
      probe made its one attempt and its recorded destination digest recovers an
      address of the compiled set; the analysis ``succeeded``; its path source is the
      task's network interface; its destination is that address, TCP, the probe port;
      its ``startDate`` lies inside the window in which the task's interface existed
      (a later analysis models a configuration the task never had); it found no path;
      and at least one explanation carries an admitted code whose component is inside
      the task's placement -- a compiled security group, or the task's subnet for a
      route-table or network-ACL code.
    """
    if type(observation) is not ProbeObservation or type(binding) is not VerdictBinding:
        raise TypeError("observation and binding must be exact values")
    if observation.result is ProbeResult.CONNECTED:
        return _record(IsolationVerdict.FAILED, VerdictReason.OBSERVED_CONNECTION)
    if observation.attempts != PROBE_MAX_ATTEMPTS:
        return _record(IsolationVerdict.INCONCLUSIVE, VerdictReason.NO_ATTEMPT)
    address = bound_destination(binding, observation)
    if address is None:
        return _record(IsolationVerdict.INCONCLUSIVE, VerdictReason.DESTINATION_UNBOUND)
    if evidence is None or type(evidence) is not ReachabilityEvidence:
        return _record(IsolationVerdict.INCONCLUSIVE, VerdictReason.NO_CORROBORATION)
    if evidence.status != ANALYSIS_SUCCEEDED:
        return _record(IsolationVerdict.INCONCLUSIVE, VerdictReason.ANALYSIS_NOT_SUCCEEDED)
    if evidence.source_interface_id != binding.network_interface_id:
        return _record(IsolationVerdict.INCONCLUSIVE, VerdictReason.SOURCE_MISMATCH)
    if (
        evidence.destination_ip != address
        or evidence.destination_port != PROBE_PORT
        or evidence.protocol != PROBE_PROTOCOL
    ):
        return _record(IsolationVerdict.INCONCLUSIVE, VerdictReason.DESTINATION_MISMATCH)
    if not binding.launched_at <= evidence.start_date <= binding.recorded_at:
        return _record(IsolationVerdict.INCONCLUSIVE, VerdictReason.ANALYSIS_OUTSIDE_TASK_WINDOW)
    # From here the analysis is bound to this task, this destination and this window.
    if evidence.network_path_found:
        return _record(
            IsolationVerdict.INCONCLUSIVE,
            VerdictReason.PATH_FOUND_CONTRADICTS_OBSERVATION,
            bound=True,
        )
    attributed: set[BlockingComponent] = set()
    outside = False
    for explanation in evidence.explanations:
        kind = ADMITTED_EXPLANATIONS.get(explanation.explanation_code)
        if kind is None or explanation.component_kind is not kind:
            continue
        if kind is BlockingComponent.SECURITY_GROUP:
            inside = explanation.component_id in binding.security_group_ids
        elif kind is BlockingComponent.SUBNET:
            inside = explanation.component_id == binding.subnet_id
        else:
            # A route table or network ACL is placed by the subnet it serves.
            inside = explanation.subnet_id == binding.subnet_id
        if inside:
            attributed.add(kind)
        else:
            outside = True
    if attributed:
        return _record(
            IsolationVerdict.VERIFIED, VerdictReason.CORROBORATED, frozenset(attributed), bound=True
        )
    if outside:
        return _record(
            IsolationVerdict.INCONCLUSIVE, VerdictReason.COMPONENT_OUTSIDE_PLACEMENT, bound=True
        )
    return _record(IsolationVerdict.INCONCLUSIVE, VerdictReason.UNSUPPORTED_EXPLANATION, bound=True)


__all__ = [
    "ADMITTED_EXPLANATIONS",
    "ANALYSIS_STATUSES",
    "ANALYSIS_SUCCEEDED",
    "ISOLATION_VERDICT_CONTRACT_ID",
    "MAX_EXPLANATIONS",
    "MAX_REACHABILITY_EVIDENCE_BYTES",
    "PROBE_MAX_ATTEMPTS",
    "PROBE_PORT",
    "PROBE_PROTOCOL",
    "PROBE_TIMEOUT_SECONDS",
    "REACHABILITY_EVIDENCE_CONTRACT_ID",
    "REACHABILITY_EVIDENCE_SCHEMA_VERSION",
    "REASON_VERDICT",
    "RESOLVABLE_INSUFFICIENCIES",
    "BlockingComponent",
    "CorroborationKind",
    "IsolationVerdict",
    "IsolationVerdictDocument",
    "IsolationVerdictRecord",
    "ProbeAdapter",
    "ProbeObservation",
    "ProbeResolution",
    "ProbeResult",
    "ReachabilityEvidence",
    "ReachabilityExplanation",
    "VerdictBinding",
    "VerdictReason",
    "bound_destination",
    "destination_binding_digest",
    "isolation_verdict",
    "parse_isolation_verdict_document",
    "parse_isolation_verdict_record",
    "parse_probe_observation",
    "parse_reachability_evidence",
    "run_origin_probe",
    "select_destination",
]
