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
its own ceiling, the three Bronze writes it creates, and the locator reserve --
which is what keeps the locator reachable at the end of a run that used every second
it had. **There is no conditional resolution in that obligation any more**: ADR-0019
removed the acquisition role's object-read authority, so ``3 * T_s3`` is the whole
per-request S3 cost.

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
byte-identical content, so a retry can never overwrite, duplicate or corrupt.

**And a retry answered ``412`` now fails closed.** Under ADR-0018 as accepted, an
earlier attempt that did in fact commit was recognised on the retry by a metadata
read and reported *already present*. ADR-0019 removed that read, so the same case
now ends in ``NAME_OCCUPIED``: the run reports that the name was occupied even
though a correct, byte-identical locator exists. **That is a false negative in the
safe direction** -- the run never claims a locator exists when it does not, nothing
is overwritten, and the orphaned object stays inside the licensed qualification
prefix that prefix-based deletion already covers. It is recorded rather than
absorbed, and it must never be reinterpreted as success.

**No retry may follow an ambiguous or unclassified result.** ``INVALID_RESPONSE``
and ``UNKNOWN`` are excluded for exactly that reason, and so are ``ACCESS_DENIED``,
``NOT_FOUND``, ``INVALID_CONFIGURATION`` and an occupied name.

**No locator attempt sends a ``HeadObject``, and neither does any Bronze write.**
``THROTTLED`` and ``TRANSIENT`` are refusals of the conditional ``PutObject``
itself, and a ``412`` is now terminal rather than the start of a resolution. So
acquisition ``HeadObject`` is **exactly zero** however many ``PutObject``
invocations the locator made, and acquisition ``GetObject`` is exactly zero too.

**Bronze writes are never retried here.** They are the runtime's, under its own
accepted contract, and this module neither wraps nor repeats them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol

from kalpamani.data.contracts.errors import ObjectStoreBackendError
from kalpamani.data.contracts.vocabulary import ObjectStoreFailure, ObjectStoreOperation
from kalpamani.data.objectstore import ObjectKey, PutOutcome
from kalpamani.data.qualify.sharadar.plan import (
    ACQUISITION_DEADLINE_SECONDS,
    BRONZE_OPERATION_ADMISSION_SECONDS,
    LOCATOR_ATTEMPT_ADMISSION_SECONDS,
    LOCATOR_OPERATION_ADMISSION_SECONDS,
    PROVIDER_REQUEST_ADMISSION_SECONDS,
    validate_deadline_constants,
)
from kalpamani.data.qualify.sharadar.publication import NameOccupiedError

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
    obligation -- its own ceiling, the three Bronze writes it creates, and the
    locator reserve. That is what makes the locator reachable at the end of a run
    that ran right up to the edge.
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

        Requires ``T_req + 3 * T_s3 + L`` (ADR-0019 §7). **Pacing is not in that
        sum**: pacing for
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

        **Every admitted operation is a ``PutObject``.** The acquisition path issues
        no ``HeadObject`` and no ``GetObject``, so there is no other kind of S3
        invocation for this method to admit.

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
        The locator was written by this execution. **The only addressable outcome.**
    ``NOT_PUBLISHED``
        The write was refused definitively. **The evidence exists and is
        unaddressable**, and a new execution identity is required.
    ``STATE_UNKNOWN``
        The write could not be verified either way. Same consequence.
    ``NAME_OCCUPIED``
        The conditional write found the name occupied, and **what occupies it was
        not determined**. ADR-0019 removed the metadata read that would have said
        whether the stored bytes were identical, so this member replaces both of the
        two ADR-0018 outcomes that depended on it: there is no ``ALREADY_PRESENT``
        and no ``COLLISION`` here any more. It is never addressable, never counted as
        retained evidence, and never reinterpreted as success -- including in the one
        case where a byte-identical locator really does exist, which is a false
        negative in the safe direction.
    """

    PUBLISHED = "PUBLISHED"
    NOT_PUBLISHED = "NOT_PUBLISHED"
    STATE_UNKNOWN = "STATE_UNKNOWN"
    NAME_OCCUPIED = "NAME_OCCUPIED"


#: The statuses under which a locator is addressable afterwards. **Exactly one**:
#: an occupied name is not an addressable locator, because nothing established what
#: the name holds.
ADDRESSABLE_STATUSES: Final[frozenset[LocatorPublicationStatus]] = frozenset(
    {LocatorPublicationStatus.PUBLISHED}
)


class CountingS3Client:
    """An S3 client that counts what it was asked for, and does nothing else.

    Wraps an injected client and forwards every call unchanged. It adds no
    behaviour, no retry, no caching and no rewriting -- it is a counter, and a
    counter that changed what happened would be measuring itself.

    **It exposes only ``put_object``**, which is now the whole of the acquisition
    writer-side protocol. There is no ``head_object`` and no ``get_object`` here:
    ADR-0019 removed the acquisition role's object-read authority, and a wrapper that
    offered either would be a read surface growing quietly inside a counter. A client
    that happens to *carry* those methods is never called through them, because there
    is no call site that could.
    """

    __slots__ = ("_client", "_deadline", "put_object_count")

    def __init__(self, client: Any, *, deadline: AcquisitionDeadline) -> None:
        """Bind the injected client and the deadline, and start the counter at zero.

        **Only ``put_object`` is required**, and that is the correction: requiring
        ``head_object`` would have refused exactly the write-only client this path is
        supposed to be given.

        The deadline is **required**, not optional. An optional one would make the
        unguarded call the default, and the guard would then be present only where
        somebody remembered it -- which is exactly the shape of the defect an earlier
        correction exists to remove.
        """
        if not callable(getattr(client, "put_object", None)):
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

    def __repr__(self) -> str:
        """One count. **Never the wrapped client, a bucket or a key.**"""
        return f"CountingS3Client(put_object={self.put_object_count})"

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
        if bronze_puts > completed_puts + OBJECTS_PER_ACQUISITION:
            # **A bound, not an equality, and the difference is a halted run.** A
            # publication writes its claim, payload and record in three separate
            # conditional invocations with no short-circuit, so a run that halted
            # part-way through one of them -- a storage refusal, or the deadline
            # refusing the next write -- has one *incomplete* publication whose
            # writes really happened and are really counted, while its request never
            # became a completed acquisition. An equality here would refuse to
            # describe the halted run at all, which is the run whose accounting
            # matters most. At most one publication can be incomplete, because the
            # runtime stops at the first terminal failure.
            #
            # **All three of that publication's writes may be counted**, not two.
            # ADR-0019 §6.5 is explicit that a collided ``PutObject`` *is* an
            # invocation and *is* counted, so a third write answered ``412`` leaves
            # three counted Bronze writes against a request that never completed --
            # a real, reachable run that the earlier ``- 1`` refused to describe.
            raise ValueError("at most one incomplete publication may exceed the per-request writes")
        if self.head_object_count:
            # **Equality with zero, not a bound derived from the write count.**
            # ADR-0019 replaced the accepted ``<= 3 * completed + 1`` ceiling with
            # this, which is stricter and needs no derivation: the acquisition role
            # holds no object-read authority and the publication surface has no
            # ``head_object``, so any non-zero count means something published
            # through a path this architecture does not have.
            raise ValueError("the acquisition path performs no metadata read")
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
    """The one store method locator publication uses.

    **Deliberately narrower than the neutral store protocol**, and deliberately not a
    union with it: the shared
    :class:`~kalpamani.data.storage.s3.S3ResearchObjectStore` resolves a ``412`` with
    a ``HeadObject``, and accepting it here would be a route back to the metadata read
    ADR-0019 removed. What this path is given is the ADR-0018 write-only publisher.
    """

    def put_if_absent(self, *, key: ObjectKey, payload: bytes) -> PutOutcome:
        """Publish one object unless the name is already occupied."""
        ...


def publish_locator(
    *,
    store: _LocatorStore,
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

    - an occupied name resolves the condition -- the write did not happen -- so it
      is terminal and no retry follows;
    - ``ACCESS_DENIED``, ``NOT_FOUND`` and ``INVALID_CONFIGURATION`` are
      definitive;
    - ``INVALID_RESPONSE`` and ``UNKNOWN`` are ambiguous, and no retry may follow
      an ambiguous result.

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
        except NameOccupiedError:
            # **Terminal, and it claims only that the name was occupied.** No
            # ``HeadObject``, no comparison, no adoption: what holds the name is
            # undetermined and stays undetermined. When this arrives on a *retry*
            # whose earlier attempt may in fact have committed a byte-identical
            # locator, the run still fails closed -- the safe-direction false
            # negative ADR-0019 §4.3 records, and never a success.
            return LocatorPublication(
                status=LocatorPublicationStatus.NAME_OCCUPIED, attempts=attempts
            )
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
        # **One success, and it is a write.** The write-only publisher reaches no
        # other: ``stored`` is ``True`` on every outcome it returns, so there is no
        # branch here that could report an occupied name as an idempotent
        # re-publication.
        status = (
            LocatorPublicationStatus.PUBLISHED
            if outcome.stored
            else LocatorPublicationStatus.STATE_UNKNOWN
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
