"""Observed operation counting, and the locator publication retry matrix.

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

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol

from kalpamani.data.contracts.errors import ObjectAlreadyExistsError, ObjectStoreBackendError
from kalpamani.data.contracts.vocabulary import ObjectStoreFailure, ObjectStoreOperation
from kalpamani.data.objectstore import ObjectKey, PutOutcome, ResearchObjectStore

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

    __slots__ = ("_client", "head_object_count", "put_object_count")

    def __init__(self, client: Any) -> None:
        """Bind the injected client and start both counters at zero."""
        if not callable(getattr(client, "put_object", None)) or not callable(
            getattr(client, "head_object", None)
        ):
            raise ObjectStoreBackendError(
                operation=ObjectStoreOperation.BIND,
                failure=ObjectStoreFailure.INVALID_CONFIGURATION,
            )
        self._client = client
        self.put_object_count = 0
        self.head_object_count = 0

    def __repr__(self) -> str:
        """Counts only. **Never the wrapped client, a bucket or a key.**"""
        return (
            f"CountingS3Client(put_object={self.put_object_count}, "
            f"head_object={self.head_object_count})"
        )

    def put_object(self, **kwargs: Any) -> Any:
        """Count the invocation, then forward it unchanged.

        Counted **before** the call, so an invocation that raises is still counted.
        A counter that only recorded successes would understate exactly the runs
        whose accounting matters most.
        """
        self.put_object_count += 1
        return self._client.put_object(**kwargs)

    def head_object(self, **kwargs: Any) -> Any:
        """Count the invocation, then forward it unchanged."""
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

        bronze_puts = OBJECTS_PER_ACQUISITION * self.completed_requests
        if self.put_object_count != bronze_puts + self.locator_put_attempts:
            raise ValueError("put_object_count must be three per acquisition plus locator attempts")
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

    Returns:
        The status and the **real attempt count**. Nothing raises out of here: a
        caller needs the accounting of a failed publication, and an exception would
        discard it.
    """
    attempts = 0
    while attempts < MAX_LOCATOR_ATTEMPTS:
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
    "AcquisitionOperationCounts",
    "CountingS3Client",
    "LocatorPublication",
    "LocatorPublicationStatus",
    "publish_locator",
]
