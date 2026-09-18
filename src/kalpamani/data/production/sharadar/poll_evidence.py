"""Bounded, sanitized evidence of the launch sequence's read-only polling, and the
post-start stop outcome (ADR-0045 s.15). Launcher-side vocabulary; no task entry imports it.

Every field of a :class:`PollDiagnostic` is a closed member, a bounded string held to
its grammar, or an integer: an exception message, a request parameter, an identifier,
an endpoint or a raw response has no field to arrive through.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from kalpamani.data.production.sharadar.compute import (
    EXCEPTION_CLASS_RE,
    SERVICE_CODE_RE,
    ComputeFailure,
    ComputeOperation,
)


class PollPhase(StrEnum):
    """Which read-only ``DescribeTasks`` loop of the launch sequence a poll belongs to. Closed."""

    PLACEMENT = "PLACEMENT"
    IMAGE = "IMAGE"
    OBSERVATION = "OBSERVATION"


class PollClass(StrEnum):
    """The retry classification of one failed read-only poll. Closed.

    ``THROTTLED`` and ``TRANSIENT`` are the service's own answers; ``TRANSPORT`` is a
    connection the SDK could not open, keep or read within its timeouts (no service
    answer at all); ``UNKNOWN`` is an unclassified compute failure, re-polled at most
    once; ``TERMINAL`` is a definitive refusal -- denied, not found, invalid request or
    response, invalid configuration -- and is never re-polled.
    """

    THROTTLED = "THROTTLED"
    TRANSIENT = "TRANSIENT"
    TRANSPORT = "TRANSPORT"
    UNKNOWN = "UNKNOWN"
    TERMINAL = "TERMINAL"


class PollDisposition(StrEnum):
    """What the sequence did after one failed read-only poll. Closed."""

    #: The poll was repeated after the accepted interval, inside the phase's ceiling.
    RE_POLLED = "RE_POLLED"
    #: The failure class is terminal: refused at once.
    REFUSED_CLASS = "REFUSED_CLASS"
    #: The consecutive-failure bound for the class was reached: refused.
    REFUSED_BOUND = "REFUSED_BOUND"
    #: The phase's ceiling leaves no room for another interval: refused.
    REFUSED_DEADLINE = "REFUSED_DEADLINE"


class StopOutcome(StrEnum):
    """What the post-start stop invariant established. Closed.

    Recorded beside -- never in place of -- the launch outcome: a ``StopTask`` that
    failed is a cleanup failure for the ``STOP_TASK`` stage as well, and a stop that
    succeeded never turns a refusal into a success.
    """

    #: No task was accepted by ``RunTask``: nothing to stop.
    NOT_APPLICABLE = "NOT_APPLICABLE"
    #: One ``StopTask`` on this task was issued and accepted.
    STOPPED = "STOPPED"
    #: One ``StopTask`` on this task was issued and refused; recorded as a cleanup failure.
    STOP_FAILED = "STOP_FAILED"
    #: The last valid description reported the task terminal: no stop was needed.
    ALREADY_TERMINAL = "ALREADY_TERMINAL"


#: The botocore exception class names that mean *no service answer*: the connection
#: could not be opened, kept or read within the accepted timeouts.
TRANSPORT_EXCEPTION_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "ConnectTimeoutError",
        "ReadTimeoutError",
        "EndpointConnectionError",
        "ConnectionClosedError",
        "ProxyConnectionError",
        "SSLError",
        "ConnectionError",
        "HTTPClientError",
    }
)


def poll_class_of(failure: ComputeFailure, exception_class: str | None) -> PollClass:
    """Reduce a compute refusal to its retry classification. Total over the vocabulary."""
    if failure is ComputeFailure.THROTTLED:
        return PollClass.THROTTLED
    if failure is ComputeFailure.TRANSIENT:
        return PollClass.TRANSIENT
    if failure is ComputeFailure.UNKNOWN:
        if exception_class in TRANSPORT_EXCEPTION_CLASSES:
            return PollClass.TRANSPORT
        return PollClass.UNKNOWN
    return PollClass.TERMINAL


@dataclass(frozen=True, slots=True, kw_only=True)
class PollDiagnostic:
    """One failed read-only poll: phase, operation, category, the two sanitized
    diagnostics, the attempt number inside the phase, the elapsed milliseconds since the
    phase began, the classification and the disposition."""

    phase: PollPhase
    operation: ComputeOperation
    failure: ComputeFailure
    exception_class: str | None
    service_code: str | None
    attempt: int
    elapsed_ms: int
    poll_class: PollClass
    disposition: PollDisposition

    def __post_init__(self) -> None:
        """Every field closed or held to its grammar; nothing free-text."""
        if type(self.phase) is not PollPhase or type(self.operation) is not ComputeOperation:
            raise TypeError("phase and operation must be exact members")
        if type(self.failure) is not ComputeFailure:
            raise TypeError("failure must be an exact ComputeFailure member")
        if type(self.poll_class) is not PollClass or type(self.disposition) is not PollDisposition:
            raise TypeError("poll_class and disposition must be exact members")
        if self.exception_class is not None and (
            type(self.exception_class) is not str
            or not EXCEPTION_CLASS_RE.fullmatch(self.exception_class)
        ):
            raise TypeError("exception_class must match its grammar or be None")
        if self.service_code is not None and (
            type(self.service_code) is not str or not SERVICE_CODE_RE.fullmatch(self.service_code)
        ):
            raise TypeError("service_code must match its grammar or be None")
        if type(self.attempt) is not int or self.attempt < 1:
            raise TypeError("attempt must be a positive int")
        if type(self.elapsed_ms) is not int or self.elapsed_ms < 0:
            raise TypeError("elapsed_ms must be a non-negative int")

    def document(self) -> dict[str, str | int | None]:
        """The evidence entry: closed tokens, the two bounded strings, two integers."""
        return {
            "phase": self.phase.value,
            "operation": self.operation.value,
            "failure": self.failure.value,
            "exception_class": self.exception_class,
            "service_code": self.service_code,
            "attempt": self.attempt,
            "elapsed_ms": self.elapsed_ms,
            "poll_class": self.poll_class.value,
            "disposition": self.disposition.value,
        }


__all__ = [
    "TRANSPORT_EXCEPTION_CLASSES",
    "PollClass",
    "PollDiagnostic",
    "PollDisposition",
    "PollPhase",
    "StopOutcome",
    "poll_class_of",
]
