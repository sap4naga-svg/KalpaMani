"""The acquisition deadline, observed operation counting, and the locator retry matrix.

**The deadline is a stopwatch, not arithmetic.** :class:`AcquisitionDeadline` holds
one real elapsed-time budget on an **injected monotonic clock**, armed at the
stage-11 boundary and running until the terminal locator result. Every provider
request, every pacing delay and every S3 invocation is admitted against it before it
starts, and an operation that does not fit is **refused rather than truncated**. The
constants it is made of live in :mod:`kalpamani.data.qualify.sharadar.plan`, where
they are checked against one another at import.

**Refusing before starting is the whole design.** A budget consulted afterwards
reports an overrun; a budget consulted first prevents one. So a provider request is
admitted only when the remaining budget covers its complete downstream obligation --
its own ceiling, the three Bronze writes and up to three conditional resolutions it
creates, and the locator reserve -- which is what keeps the locator reachable at the
end of a run that used every second it had.


**The counters count invocations, and they are labelled as invocations.** A cloud
SDK call can resolve locally and fail before anything leaves the machine, so a
method invocation is not a proven network request and nothing here claims one. What
these count is exactly what a counter can see: how many times the injected client's
methods were called. That is the number the accepted arithmetic is stated in, and
it is observed rather than assumed -- a run that retried its locator reports the
retry, and never "exactly 145".

**The retry permission is narrow, and its narrowness is the safety argument.** A
locator publication may be retried at most twice, and only when the conditional
``PutObject`` **itself** refused with ``THROTTLED`` or ``TRANSIENT`` -- that is,
only while the publication condition remains unresolved. Every attempt sends
byte-identical content, so if an earlier attempt did commit, a later one is
answered ``412``, resolves the occupancy by metadata, finds the digest matches and
reports *already present*. A retry can therefore resolve an unresolved condition
and can never overwrite, duplicate or corrupt.

**No retry may follow an ambiguous or unclassified result.** ``INVALID_RESPONSE``
and ``UNKNOWN`` are excluded for exactly that reason, and so are ``ACCESS_DENIED``,
``NOT_FOUND``, ``INVALID_CONFIGURATION`` and a genuine different-content collision.

**A retry-triggering attempt sends no ``HeadObject``.** ``THROTTLED`` and
``TRANSIENT`` are refusals of the conditional ``PutObject`` itself: they leave
before the occupancy resolution. The only attempt that reaches that resolution is
one answered ``412`` -- and a ``412`` *resolves* the condition, which is the
property the retry permission requires to be absent. So at most one locator attempt
can ever reach the metadata-resolution path, and locator ``HeadObject`` is at most
one however many ``PutObject`` invocations the locator made.

**Bronze writes are never retried here.** They are the runtime's, under its own
accepted contract, and this module neither wraps nor repeats them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol

from kalpamani.data.contracts.errors import ObjectAlreadyExistsError, ObjectStoreBackendError
from kalpamani.data.contracts.vocabulary import ObjectStoreFailure, ObjectStoreOperation
from kalpamani.data.objectstore import ObjectKey, PutOutcome, ResearchObjectStore
from kalpamani.data.qualify.sharadar.plan import (
    ACQUISITION_DEADLINE_SECONDS,
    BRONZE_OPERATION_ADMISSION_SECONDS,
    LOCATOR_ATTEMPT_ADMISSION_SECONDS,
    LOCATOR_OPERATION_ADMISSION_SECONDS,
    PROVIDER_REQUEST_ADMISSION_SECONDS,
    validate_deadline_constants,
)

#: The two failures that leave the publication condition unresolved, and are
#: therefore the only two a retry may follow. An allowlist: a failure category
#: added to the vocabulary later is not retryable until somebody adds it here
#: deliberately, which is the direction that fails closed.
RETRYABLE_LOCATOR_FAILURES: Final[frozenset[ObjectStoreFailure]] = frozenset(
    {ObjectStoreFailure.THROTTLED, ObjectStoreFailure.TRANSIENT}
)

#: At most two retries after the first attempt, so at most three attempts.
MAX_LOCATOR_ATTEMPTS: Final = 3

#: Three durable objects per completed acquisition: claim, payload, record.
OBJECTS_PER_ACQUISITION: Final = 3


class DeadlineStage(StrEnum):
    """What was being admitted when the acquisition deadline refused it.

    Closed, and carrying **no time value, no identifier and no measurement** -- a
    stage token says which admission failed and nothing about how long anything
    took, because a duration in a public refusal is a side channel about a private
    run.
    """

    PROVIDER_REQUEST = "PROVIDER_REQUEST"
    PACING = "PACING"
    BRONZE_OPERATION = "BRONZE_OPERATION"
    LOCATOR_OPERATION = "LOCATOR_OPERATION"


class DeadlineExhaustedError(Exception):
    """The acquisition deadline refused one operation. Raised ``from None``.

    It carries exactly one :class:`DeadlineStage`. There is no parameter for a
    remaining budget, an elapsed time, a key, a subject or a bucket, so none of them
    can arrive -- and the accepted runtime, which catches whatever an injected
    dependency raises, therefore has nothing private to leak into its own halt.
    """

    __slots__ = ("stage",)

    def __init__(self, stage: DeadlineStage) -> None:
        """Bind the stage. The message is the member's token, nothing more."""
        if type(stage) is not DeadlineStage:  # pragma: no cover - type guard
            raise TypeError("a stage must be an exact DeadlineStage member")
        super().__init__(stage.value)
        self.stage = stage


class DeadlinePhase(StrEnum):
    """Where in the acquisition execution phase the deadline currently is.

    The phase decides how much an S3 operation must leave behind: during
    ``ACQUIRING`` a Bronze write must not spend the locator's reserve, and during
    ``LOCATOR`` the reserve is exactly what is being spent.
    """

    UNARMED = "UNARMED"
    ACQUIRING = "ACQUIRING"
    LOCATOR = "LOCATOR"


class AcquisitionDeadline:
    """One real elapsed-time deadline over the acquisition execution phase.

    **Monotonic, and never calendar.** The clock is injected and is required to be a
    monotonic source: a calendar clock can be stepped backwards by an NTP
    correction or a daylight-saving change, and a licensed acquisition whose
    deadline can be lengthened or shortened by a clock adjustment has no deadline.
    Nothing in this class reads ``datetime``, ``time.time`` or a timezone, and a
    test asserts that moving calendar time changes no answer here.

    **It is armed at the stage-11 boundary and not before.** Stages 1-10 --
    authorization, the private input, identity, binding, the credential, dependency
    construction and the offline preflight -- are gates that happen before the
    acquisition execution phase begins, and they consume none of this budget. The
    arm point is immediately before the call that performs the first provider
    request, and the deadline ends only at the terminal locator result.

    **Nothing is truncated to fit.** Every admission is a refusal or a pass. A
    pacing delay that does not fit is refused and the run halts; it is never
    shortened, because a shortened pacing delay is a rate limit this package
    promised the vendor and then did not keep.

    **No operation may start on the hope that it finishes in time.** A provider
    request is admitted only when the remaining budget covers its whole downstream
    obligation -- its own ceiling, the three Bronze writes and up to three
    conditional resolutions it creates, and the locator reserve. That is what makes
    the locator reachable at the end of a run that ran right up to the edge.
    """

    __slots__ = ("_deadline", "_monotonic", "_phase", "_started", "exhausted")

    def __init__(
        self,
        *,
        monotonic: Callable[[], float],
        deadline_seconds: float = ACQUISITION_DEADLINE_SECONDS,
    ) -> None:
        """Bind the monotonic source and the deadline. **Does not start it.**

        Raises:
            TypeError: if ``monotonic`` is not callable.
            EmpiricalPlanError: ``DEADLINE_UNSATISFIABLE`` if the compiled budget
                arithmetic does not hold for ``deadline_seconds``.
        """
        if not callable(monotonic):
            raise TypeError("a deadline needs a callable monotonic source")
        validate_deadline_constants(deadline_seconds=deadline_seconds)
        self._monotonic = monotonic
        self._deadline = float(deadline_seconds)
        self._started: float | None = None
        self._phase = DeadlinePhase.UNARMED
        self.exhausted = False

    def __repr__(self) -> str:
        """The phase and whether it was exhausted. **Never a time value.**"""
        return f"AcquisitionDeadline(phase={self._phase.value}, exhausted={self.exhausted})"

    @property
    def armed(self) -> bool:
        """Whether the elapsed-time budget has started running."""
        return self._started is not None

    @property
    def phase(self) -> DeadlinePhase:
        """Where in the acquisition execution phase this deadline is."""
        return self._phase

    def arm(self) -> None:
        """Start the budget, at the stage-11 boundary. **Once, and only once.**

        Raises:
            RuntimeError: on a second arm. Re-arming would restart a deadline
                mid-run, which is a way of never reaching one.
        """
        if self._started is not None:
            raise RuntimeError("an acquisition deadline may be armed only once")
        self._started = self._monotonic()
        self._phase = DeadlinePhase.ACQUIRING

    def begin_locator_phase(self) -> None:
        """Enter the terminal locator phase, at the stage-13 boundary.

        Raises:
            RuntimeError: if the deadline was never armed.
        """
        if self._started is None:
            raise RuntimeError("the locator phase follows an armed acquisition phase")
        self._phase = DeadlinePhase.LOCATOR

    @property
    def elapsed(self) -> float:
        """Seconds of monotonic time since arming. Zero while unarmed."""
        if self._started is None:
            return 0.0
        return self._monotonic() - self._started

    @property
    def remaining(self) -> float:
        """Seconds of budget left. The whole deadline while unarmed.

        Read fresh from the monotonic source on every access, deliberately: a
        cached remaining budget is a budget that stops noticing time passing, and
        pacing must be visible to the admission check that follows it.
        """
        if self._started is None:
            return self._deadline
        return self._deadline - (self._monotonic() - self._started)

    def _require(self, needed: float, stage: DeadlineStage) -> None:
        if self.remaining < needed:
            self.exhausted = True
            raise DeadlineExhaustedError(stage) from None

    def admit_provider_request(self) -> None:
        """Admit one provider request, or refuse the run.

        Requires ``T_req + 6 * T_s3 + L``. **Pacing is not in that sum**: pacing for
        this request was checked and consumed before admission is asked, so counting
        it again here would spend one interval twice and halt runs that could have
        finished.

        Raises:
            DeadlineExhaustedError: ``PROVIDER_REQUEST``. Nothing is sent, and the
                request is not counted.
        """
        self._require(PROVIDER_REQUEST_ADMISSION_SECONDS, DeadlineStage.PROVIDER_REQUEST)

    def admit_pacing(self, seconds: float) -> None:
        """Admit one pacing delay of exactly ``seconds``, or refuse the run.

        The delay is **never truncated**. A pacer that shortened its interval to fit
        a deadline would silently break the request spacing this package commits to,
        and would do it precisely on the runs already under pressure.

        Raises:
            DeadlineExhaustedError: ``PACING``.
        """
        if type(seconds) not in (int, float) or seconds != seconds:
            raise DeadlineExhaustedError(DeadlineStage.PACING) from None
        if seconds <= 0:
            return
        self._require(float(seconds), DeadlineStage.PACING)

    def admit_s3_operation(self) -> None:
        """Admit one qualification S3 invocation, or refuse the run.

        During ``ACQUIRING`` a Bronze operation must leave the locator reserve
        intact, so it requires ``T_s3 + L``. During ``LOCATOR`` the reserve is what
        is being spent, so it requires ``T_s3``. An unarmed deadline admits nothing:
        no S3 operation belongs to the acquisition phase before it starts.

        Raises:
            DeadlineExhaustedError: ``BRONZE_OPERATION`` or ``LOCATOR_OPERATION``.
        """
        if self._phase is DeadlinePhase.LOCATOR:
            self._require(LOCATOR_OPERATION_ADMISSION_SECONDS, DeadlineStage.LOCATOR_OPERATION)
            return
        if self._started is None:
            self.exhausted = True
            raise DeadlineExhaustedError(DeadlineStage.BRONZE_OPERATION) from None
        self._require(BRONZE_OPERATION_ADMISSION_SECONDS, DeadlineStage.BRONZE_OPERATION)

    def permits_locator_construction(self) -> bool:
        """Whether the locator may be built and one write attempted at all.

        Answered rather than raised: below this threshold the run has an accepted
        closed result -- ``LOCATOR_NOT_PUBLISHED`` -- and it **must not claim a
        locator exists**. An exception here would discard the accounting that result
        is for.
        """
        return self.remaining >= LOCATOR_ATTEMPT_ADMISSION_SECONDS

    def permits_locator_write(self) -> bool:
        """Whether one further locator ``PutObject`` attempt may be started."""
        return self.remaining >= LOCATOR_OPERATION_ADMISSION_SECONDS


class LocatorPublicationStatus(StrEnum):
    """How the one locator publication ended. Closed, and never a verdict.

    ``PUBLISHED``
        The locator was written by this execution.
    ``ALREADY_PRESENT``
        Byte-identical content was already stored under the name. An ordinary
        idempotent outcome of a retry whose earlier attempt did commit.
    ``NOT_PUBLISHED``
        The write was refused definitively. **The evidence exists and is
        unaddressable**, and a new execution identity is required.
    ``STATE_UNKNOWN``
        The write could not be verified either way. Same consequence.
    ``COLLISION``
        The name is held by different content. A genuine collision; retrying
        repeats it, so nothing does.
    """

    PUBLISHED = "PUBLISHED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    NOT_PUBLISHED = "NOT_PUBLISHED"
    STATE_UNKNOWN = "STATE_UNKNOWN"
    COLLISION = "COLLISION"


#: The statuses under which a locator is addressable afterwards.
ADDRESSABLE_STATUSES: Final[frozenset[LocatorPublicationStatus]] = frozenset(
    {LocatorPublicationStatus.PUBLISHED, LocatorPublicationStatus.ALREADY_PRESENT}
)


class CountingS3Client:
    """An S3 client that counts what it was asked for, and does nothing else.

    Wraps an injected client and forwards every call unchanged. It adds no
    behaviour, no retry, no caching and no rewriting -- it is a counter, and a
    counter that changed what happened would be measuring itself.

    **It exposes only ``put_object`` and ``head_object``**, which is the whole of
    the writer-side protocol. There is no ``get_object`` here: the acquisition path
    has no object-byte read, and a wrapper that offered one would be a read surface
    growing quietly inside a counter.
    """

    __slots__ = ("_client", "_deadline", "head_object_count", "put_object_count")

    def __init__(self, client: Any, *, deadline: AcquisitionDeadline) -> None:
        """Bind the injected client and the deadline, and start both counters at zero.

        The deadline is **required**, not optional. An optional one would make the
        unguarded call the default, and the guard would then be present only where
        somebody remembered it -- which is exactly the shape of the defect this
        correction exists to remove.
        """
        if not callable(getattr(client, "put_object", None)) or not callable(
            getattr(client, "head_object", None)
        ):
            raise ObjectStoreBackendError(
                operation=ObjectStoreOperation.BIND,
                failure=ObjectStoreFailure.INVALID_CONFIGURATION,
            )
        if type(deadline) is not AcquisitionDeadline:
            raise ObjectStoreBackendError(
                operation=ObjectStoreOperation.BIND,
                failure=ObjectStoreFailure.INVALID_CONFIGURATION,
            )
        self._client = client
        self._deadline = deadline
        self.put_object_count = 0
        self.head_object_count = 0

    def __repr__(self) -> str:
        """Counts only. **Never the wrapped client, a bucket or a key.**"""
        return (
            f"CountingS3Client(put_object={self.put_object_count}, "
            f"head_object={self.head_object_count})"
        )

    def put_object(self, **kwargs: Any) -> Any:
        """Admit against the deadline, count the invocation, then forward it.

        The order is the control. **Admission first**, so an operation refused by
        the deadline never starts and is never counted -- it did not happen, and a
        counter that recorded it would report work nobody did. **Counting second**,
        so an invocation that raises *is* counted: it happened, and a counter that
        only recorded successes would understate exactly the runs whose accounting
        matters most.

        Raises:
            DeadlineExhaustedError: if the remaining budget does not cover this
                operation and whatever the current phase requires it to leave
                behind.
        """
        self._deadline.admit_s3_operation()
        self.put_object_count += 1
        return self._client.put_object(**kwargs)

    def head_object(self, **kwargs: Any) -> Any:
        """Admit against the deadline, count the invocation, then forward it."""
        self._deadline.admit_s3_operation()
        self.head_object_count += 1
        return self._client.head_object(**kwargs)


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionOperationCounts:
    """The observed operation accounting of one acquisition execution.

    Every field is a real invocation count read off a counter, and
    :meth:`__post_init__` refuses a set of counts that no run could have produced.
    A summary nobody checked is the part of a report that goes wrong quietly.
    """

    completed_requests: int
    put_object_count: int
    head_object_count: int
    get_object_count: int
    list_operation_count: int
    control_operation_count: int
    locator_put_attempts: int
    provider_request_count: int

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so an accounting cannot be restated after the fact."""
        raise TypeError("AcquisitionOperationCounts may not be subclassed")

    def __post_init__(self) -> None:
        """Refuse counts that contradict the accepted arithmetic."""
        for value in (
            self.completed_requests,
            self.put_object_count,
            self.head_object_count,
            self.get_object_count,
            self.list_operation_count,
            self.control_operation_count,
            self.locator_put_attempts,
            self.provider_request_count,
        ):
            if type(value) is not int or value < 0:
                raise ValueError("every operation count must be an exact non-negative int")

        if not 0 <= self.locator_put_attempts <= MAX_LOCATOR_ATTEMPTS:
            raise ValueError("locator_put_attempts must be in 0..3")

        bronze_puts = self.put_object_count - self.locator_put_attempts
        completed_puts = OBJECTS_PER_ACQUISITION * self.completed_requests
        if bronze_puts < completed_puts:
            raise ValueError("each completed acquisition writes three Bronze objects")
        if bronze_puts > completed_puts + OBJECTS_PER_ACQUISITION - 1:
            # **A bound, not an equality, and the difference is a halted run.** A
            # publication writes its claim, payload and record in three separate
            # conditional invocations with no short-circuit, so a run that halted
            # part-way through one of them -- a storage refusal, or the deadline
            # refusing the next write -- has one *incomplete* publication whose one
            # or two writes really happened and are really counted, while its
            # request never became a completed acquisition. An equality here would
            # refuse to describe the halted run at all, which is the run whose
            # accounting matters most. At most one publication can be incomplete,
            # because the runtime stops at the first terminal failure.
            raise ValueError("at most one incomplete publication may exceed the per-request writes")
        if self.head_object_count > bronze_puts + 1:
            # Bounded by the *PutObject* count of the Bronze writes plus at most
            # one locator resolution -- and deliberately not by the total PutObject
            # count, which a retry raises. The extra invocations a retry buys are
            # exactly the ones that sent no HeadObject.
            raise ValueError("head_object_count exceeds one metadata resolution per write")
        if self.get_object_count:
            raise ValueError("the acquisition path performs no object-byte read")
        if self.list_operation_count:
            raise ValueError("no listing exists anywhere in this architecture")
        if self.control_operation_count:
            raise ValueError("CONTROL publication is deferred and forbidden")

    @property
    def total_s3_operations(self) -> int:
        """Every S3 invocation this execution made."""
        return self.put_object_count + self.head_object_count + self.get_object_count


@dataclass(frozen=True, slots=True, kw_only=True)
class LocatorPublication:
    """What the one locator publication did, and how many attempts it took."""

    status: LocatorPublicationStatus
    attempts: int

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so a publication result cannot be restated."""
        raise TypeError("LocatorPublication may not be subclassed")

    @property
    def addressable(self) -> bool:
        """Whether the locator can be retrieved afterwards by name."""
        return self.status in ADDRESSABLE_STATUSES


class _LocatorStore(Protocol):
    """The one store method locator publication uses."""

    def put_if_absent(self, *, key: ObjectKey, payload: bytes) -> PutOutcome:
        """Publish one object unless the name is already occupied."""
        ...


def publish_locator(
    *,
    store: ResearchObjectStore | _LocatorStore,
    key: ObjectKey,
    payload: bytes,
    deadline: AcquisitionDeadline,
) -> LocatorPublication:
    """Publish the locator conditionally, retrying only while unresolved.

    ``payload`` is built once by the caller and passed in unchanged, so every
    attempt writes byte-identical content. This function never rebuilds it, never
    reads a clock and never derives anything of its own -- which is what makes the
    retry idempotent rather than merely repeated.

    **The loop cannot exceed three attempts**, and it exits on anything that is not
    an unresolved-condition refusal of the ``PutObject`` itself:

    - a store refusal whose operation is ``HEAD`` is post-``412`` metadata
      resolution, so the condition is already resolved and no retry follows;
    - ``ACCESS_DENIED``, ``NOT_FOUND`` and ``INVALID_CONFIGURATION`` are
      definitive;
    - ``INVALID_RESPONSE`` and ``UNKNOWN`` are ambiguous, and no retry may follow
      an ambiguous result;
    - a different-content collision is genuine, and retrying repeats it.

    **The deadline is checked before every attempt**, including before a retry, and
    the locator's own S3 invocations are admitted again inside the counting client.
    An attempt that cannot fit is not started: below the threshold with nothing
    written the result is ``NOT_PUBLISHED``, and below it after an unresolved
    attempt the result is ``STATE_UNKNOWN``. Neither is a claim that a locator
    exists.

    Returns:
        The status and the **real attempt count**. Nothing raises out of here: a
        caller needs the accounting of a failed publication, and an exception would
        discard it.
    """
    if type(deadline) is not AcquisitionDeadline:  # pragma: no cover - type guard
        raise TypeError("locator publication requires the acquisition deadline")
    attempts = 0
    while attempts < MAX_LOCATOR_ATTEMPTS:
        if not deadline.permits_locator_write():
            # **The budget is checked before the attempt, including before a
            # retry.** With nothing attempted yet the locator was never written and
            # the run says so exactly: ``NOT_PUBLISHED``, and it must not claim a
            # locator exists. After an attempt that left the condition unresolved,
            # what is durable is genuinely unknown, and stopping here does not make
            # it known.
            if attempts == 0:
                return LocatorPublication(status=LocatorPublicationStatus.NOT_PUBLISHED, attempts=0)
            return LocatorPublication(
                status=LocatorPublicationStatus.STATE_UNKNOWN, attempts=attempts
            )
        attempts += 1
        try:
            outcome = store.put_if_absent(key=key, payload=payload)
        except ObjectAlreadyExistsError:
            return LocatorPublication(status=LocatorPublicationStatus.COLLISION, attempts=attempts)
        except ObjectStoreBackendError as refusal:
            if (
                refusal.operation is ObjectStoreOperation.PUT
                and refusal.failure in RETRYABLE_LOCATOR_FAILURES
                and attempts < MAX_LOCATOR_ATTEMPTS
            ):
                continue
            if refusal.failure in (
                ObjectStoreFailure.INVALID_RESPONSE,
                ObjectStoreFailure.UNKNOWN,
            ):
                return LocatorPublication(
                    status=LocatorPublicationStatus.STATE_UNKNOWN, attempts=attempts
                )
            return LocatorPublication(
                status=LocatorPublicationStatus.NOT_PUBLISHED, attempts=attempts
            )
        except Exception:
            # A store this module did not write raised something it does not
            # classify. That is unresolved and unclassified, which is the exact
            # definition of a state nobody may retry or claim.
            return LocatorPublication(
                status=LocatorPublicationStatus.STATE_UNKNOWN, attempts=attempts
            )
        status = (
            LocatorPublicationStatus.PUBLISHED
            if outcome.stored
            else LocatorPublicationStatus.ALREADY_PRESENT
        )
        return LocatorPublication(status=status, attempts=attempts)

    # The loop exhausted its permitted attempts without resolving the condition.
    return LocatorPublication(
        status=LocatorPublicationStatus.STATE_UNKNOWN, attempts=MAX_LOCATOR_ATTEMPTS
    )


__all__ = [
    "ADDRESSABLE_STATUSES",
    "MAX_LOCATOR_ATTEMPTS",
    "OBJECTS_PER_ACQUISITION",
    "RETRYABLE_LOCATOR_FAILURES",
    "AcquisitionDeadline",
    "AcquisitionOperationCounts",
    "CountingS3Client",
    "DeadlineExhaustedError",
    "DeadlinePhase",
    "DeadlineStage",
    "LocatorPublication",
    "LocatorPublicationStatus",
    "publish_locator",
]
