"""The placement release barrier: bounded waiting, then exactly one verdict.

After the identity proof (ADR-0036 §2.12 step 6) the task polls its release
parameter at a compiled interval (**5 s**) up to a compiled ceiling (**300 s, at
most 60 reads, each counted**). ``NOT_FOUND`` means *not yet released* and is the
only tolerated failure; any other read failure refuses at once. A release that
arrives is verified against the expectation the task already holds, and a
mismatched, malformed or stale one refuses at once too.

**No data-plane operation is reachable from here.** The barrier takes a
parameter reader, a clock and a sleep; it takes no S3 client, no secret source
and no provider transport, so a caller that has not yet passed it cannot have
performed any of the operations it guards -- a test counts them at zero across
every refusal path.

The clock is a monotonic seconds source and the sleep is a callable, both
injected, so the ceiling is measured rather than computed and a test drives the
whole 300 seconds in no time at all.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from kalpamani.data.production.sharadar.bindings import ParameterReader
from kalpamani.data.production.sharadar.parameters import ParameterError, ParameterFailure
from kalpamani.data.production.sharadar.release import (
    PlacementRelease,
    ReleaseDefect,
    ReleaseError,
    ReleaseExpectation,
    decode_release,
    verify_release,
)
from kalpamani.data.production.sharadar.vocabulary import constants_for

#: The compiled polling constants of ADR-0036 §2.9. Lowerable, never raisable.
POLL_INTERVAL_SECONDS: Final = 5.0
MAX_RELEASE_READS: Final = 60
RELEASE_CEILING_SECONDS: Final = 300.0


class BarrierOutcome(StrEnum):
    """Exactly one verdict per barrier pass. Closed."""

    RELEASED = "RELEASED"
    REFUSED_NO_RELEASE = "REFUSED_NO_RELEASE"
    REFUSED_RELEASE_MISMATCH = "REFUSED_RELEASE_MISMATCH"
    REFUSED_RELEASE_READ = "REFUSED_RELEASE_READ"


@dataclass(frozen=True, slots=True, kw_only=True)
class BarrierResult:
    """What the barrier did: the verdict, the reads it counted, the time it took."""

    outcome: BarrierOutcome
    reads: int
    elapsed_seconds: float
    release: PlacementRelease | None
    defect: ReleaseDefect | None
    read_failure: ParameterFailure | None

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing."""
        raise TypeError("BarrierResult may not be subclassed")

    def __post_init__(self) -> None:
        """A result must be internally consistent, or it is not a result."""
        if type(self.outcome) is not BarrierOutcome:
            raise TypeError("outcome must be an exact BarrierOutcome member")
        if type(self.reads) is not int or not 0 <= self.reads <= MAX_RELEASE_READS:
            raise ValueError("reads must lie within the compiled ceiling")
        released = self.outcome is BarrierOutcome.RELEASED
        if released != (self.release is not None):
            raise ValueError("a release is present exactly when the outcome is RELEASED")
        if (self.outcome is BarrierOutcome.REFUSED_RELEASE_MISMATCH) != (self.defect is not None):
            raise ValueError("a defect is present exactly when the outcome is a mismatch")
        if (self.outcome is BarrierOutcome.REFUSED_RELEASE_READ) != (self.read_failure is not None):
            raise ValueError("a read failure is present exactly when the outcome is a read refusal")


def await_placement_release(
    *,
    reader: ParameterReader,
    expectation: ReleaseExpectation,
    now: Callable[[], datetime],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
) -> BarrierResult:
    """Poll for this task's release within the compiled bounds; one closed verdict.

    Each read is counted before it is attempted, so the count reported is the
    count of reads issued, and never fewer. The ceiling is checked before every
    read, **again after every read and before any release is accepted**, and
    before every sleep -- so no read starts after 300 s, a response that arrives at
    or beyond 300 s is refused however valid it is, and no sleep is started that
    would end past the ceiling.
    """
    if type(expectation) is not ReleaseExpectation:
        raise TypeError("expectation must be an exact ReleaseExpectation")
    name = constants_for(expectation.actor).release_parameter
    started = monotonic()
    reads = 0

    def elapsed() -> float:
        return max(0.0, monotonic() - started)

    while True:
        if reads >= MAX_RELEASE_READS or elapsed() >= RELEASE_CEILING_SECONDS:
            return BarrierResult(
                outcome=BarrierOutcome.REFUSED_NO_RELEASE,
                reads=reads,
                elapsed_seconds=elapsed(),
                release=None,
                defect=None,
                read_failure=None,
            )
        reads += 1
        try:
            raw = reader.read_parameter(name)
        except ParameterError as error:
            if error.failure is ParameterFailure.NOT_FOUND:
                if elapsed() + POLL_INTERVAL_SECONDS > RELEASE_CEILING_SECONDS:
                    return BarrierResult(
                        outcome=BarrierOutcome.REFUSED_NO_RELEASE,
                        reads=reads,
                        elapsed_seconds=elapsed(),
                        release=None,
                        defect=None,
                        read_failure=None,
                    )
                sleep(POLL_INTERVAL_SECONDS)
                continue
            return BarrierResult(
                outcome=BarrierOutcome.REFUSED_RELEASE_READ,
                reads=reads,
                elapsed_seconds=elapsed(),
                release=None,
                defect=None,
                read_failure=error.failure,
            )
        except Exception:
            return BarrierResult(
                outcome=BarrierOutcome.REFUSED_RELEASE_READ,
                reads=reads,
                elapsed_seconds=elapsed(),
                release=None,
                defect=None,
                read_failure=ParameterFailure.UNKNOWN,
            )

        # The read itself took time. A response that arrives at or beyond the
        # ceiling is refused before it is looked at: the deadline bounds when the
        # task may *proceed*, not merely when it may ask.
        if elapsed() >= RELEASE_CEILING_SECONDS:
            return BarrierResult(
                outcome=BarrierOutcome.REFUSED_NO_RELEASE,
                reads=reads,
                elapsed_seconds=elapsed(),
                release=None,
                defect=None,
                read_failure=None,
            )

        try:
            release = verify_release(decode_release(raw), expectation=expectation, now=now())
        except ReleaseError as error:
            return BarrierResult(
                outcome=BarrierOutcome.REFUSED_RELEASE_MISMATCH,
                reads=reads,
                elapsed_seconds=elapsed(),
                release=None,
                defect=error.defect,
                read_failure=None,
            )
        return BarrierResult(
            outcome=BarrierOutcome.RELEASED,
            reads=reads,
            elapsed_seconds=elapsed(),
            release=release,
            defect=None,
            read_failure=None,
        )


__all__ = [
    "MAX_RELEASE_READS",
    "POLL_INTERVAL_SECONDS",
    "RELEASE_CEILING_SECONDS",
    "BarrierOutcome",
    "BarrierResult",
    "await_placement_release",
]
