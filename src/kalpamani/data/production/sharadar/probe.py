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
limits, is the proposed ADR's §5 -- nothing here collects it, and no permission is broadened.

**The probe is bounded and value-free.** One destination, chosen deterministically from the
compiled origin address set (the lexicographically smallest resolved address that lies inside
the set); one TCP connection attempt to port 443 with a compiled timeout; **no request bytes**
-- no TLS handshake, no HTTP, no provider API request; a resolution failure makes **no** attempt
and counts none. The observation carries closed tokens and integers only: never an address,
never a host.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol

from kalpamani.data.production.sharadar.task_clients import PROVIDER_ORIGIN_HOST

#: The destination port of the one attempt: the provider's HTTPS origin.
PROBE_PORT: Final = 443
#: The compiled connection timeout, in seconds (proposed ADR-0045 §4).
PROBE_TIMEOUT_SECONDS: Final = 5.0
#: Exactly one attempt per verification task. Never more.
PROBE_MAX_ATTEMPTS: Final = 1


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

    def document(self) -> dict[str, object]:
        """The closed receipt block."""
        return {
            "resolution": self.resolution.value,
            "result": self.result.value,
            "attempts": self.attempts,
        }

    def __repr__(self) -> str:
        """Tokens and the count only."""
        return (
            f"ProbeObservation(resolution={self.resolution.value!r}, "
            f"result={self.result.value!r}, attempts={self.attempts})"
        )


def parse_probe_observation(raw: object) -> ProbeObservation:
    """The closed block back into an observation, or ``ValueError``/``TypeError``."""
    if type(raw) is not dict or set(raw) != {"resolution", "result", "attempts"}:
        raise ValueError("a probe observation carries exactly resolution, result and attempts")
    resolution, result, attempts = raw["resolution"], raw["result"], raw["attempts"]
    if type(resolution) is not str or type(result) is not str or type(attempts) is not int:
        raise ValueError("a probe observation's fields are two tokens and one integer")
    if resolution not in {m.value for m in ProbeResolution}:
        raise ValueError("unknown resolution")
    if result not in {m.value for m in ProbeResult}:
        raise ValueError("unknown result")
    return ProbeObservation(
        resolution=ProbeResolution(resolution), result=ProbeResult(result), attempts=attempts
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
) -> ProbeObservation:
    """Resolve, select, attempt at most once; never raise; never send a byte.

    A resolver that raises is ``UNRESOLVED`` with zero attempts. An adapter that raises
    is ``CONNECTION_ERROR`` -- the attempt was made and is counted.
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
    return ProbeObservation(resolution=resolution, result=result, attempts=PROBE_MAX_ATTEMPTS)


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


@dataclass(frozen=True, slots=True, kw_only=True)
class IsolationCorroboration:
    """Owner-recorded corroboration of one probe, in the shape the proposed ADR states.

    ``network_path_found`` is the analysis's own verdict; ``blocking_components`` the
    documented component types the analysis named; ``source_interface_matches`` and
    ``destination_matches`` are the launch tool's comparisons of the analysis's source
    network interface and destination address against its own launch record and the
    compiled destination selection -- booleans, so no interface id or address is carried.
    """

    kind: CorroborationKind
    network_path_found: bool
    blocking_components: frozenset[BlockingComponent]
    source_interface_matches: bool
    destination_matches: bool

    def __post_init__(self) -> None:
        """Exact members and booleans."""
        if type(self.kind) is not CorroborationKind:
            raise TypeError("kind must be an exact CorroborationKind member")
        if type(self.blocking_components) is not frozenset or any(
            type(c) is not BlockingComponent for c in self.blocking_components
        ):
            raise TypeError("blocking components must be a frozenset of exact members")
        for name in ("network_path_found", "source_interface_matches", "destination_matches"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a bool")


def isolation_verdict(
    observation: ProbeObservation, corroboration: IsolationCorroboration | None
) -> IsolationVerdict:
    """The R-2 conclusion for one probe, under the proposed ADR's rule.

    - ``CONNECTED`` **fails**, whatever the corroboration says: a configuration model
      that predicts a block does not undo an observed connection.
    - a non-connection with no corroboration, an unmatched corroboration, an analysis
      that found a path, or one that names no component inside this VPC's own
      controls, is ``INCONCLUSIVE``;
    - ``VERIFIED`` requires a non-connection **observed on an actual attempt** (an
      unresolved or out-of-set resolution made none, so it corroborates nothing about
      the network) and a matching reachability analysis that found no path and named at
      least one blocking component of this VPC's route table, security group, NACL or
      subnet.
    """
    if type(observation) is not ProbeObservation:
        raise TypeError("observation must be an exact ProbeObservation")
    if observation.result is ProbeResult.CONNECTED:
        return IsolationVerdict.FAILED
    if observation.attempts != PROBE_MAX_ATTEMPTS:
        return IsolationVerdict.INCONCLUSIVE
    if corroboration is None or type(corroboration) is not IsolationCorroboration:
        return IsolationVerdict.INCONCLUSIVE
    # CorroborationKind has one member; a second kind must extend this rule explicitly,
    # and a test holds the vocabulary to the kinds this function decides.
    if not (corroboration.source_interface_matches and corroboration.destination_matches):
        return IsolationVerdict.INCONCLUSIVE
    if corroboration.network_path_found or not corroboration.blocking_components:
        return IsolationVerdict.INCONCLUSIVE
    return IsolationVerdict.VERIFIED


__all__ = [
    "PROBE_MAX_ATTEMPTS",
    "PROBE_PORT",
    "PROBE_TIMEOUT_SECONDS",
    "BlockingComponent",
    "CorroborationKind",
    "IsolationCorroboration",
    "IsolationVerdict",
    "ProbeAdapter",
    "ProbeObservation",
    "ProbeResolution",
    "ProbeResult",
    "isolation_verdict",
    "parse_probe_observation",
    "run_origin_probe",
    "select_destination",
]
