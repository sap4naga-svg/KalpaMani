"""The empirical acquisition composition: plan, execute, publish the locator last.

**It composes; it decides nothing.** Every dependency is a required keyword
parameter with no default, the components are locals built from them, and every
number the run is held to is a constant in
:mod:`kalpamani.data.qualify.sharadar.plan`. A composition that chose its own
dataset, window or retry policy could choose differently.

**The payload is never parsed here, and no parser is reachable from this module.**
The bytes go from the client to the publisher inside the accepted qualification
runtime; this module does not decode, sample, count or inspect them. A static test
proves this module imports neither the parser nor the evaluator, which is what keeps
the acquisition path's opaque-payload boundary structural rather than remembered.

**The locator is published last, after every acquisition write.** A locator written
first would reference objects that do not exist. It is published even when the run
halted -- a ``PARTIAL`` locator preserves the accounting, and the assessor refuses to
evaluate it, which are two different things and both are wanted.

**Counts are observed, not assumed.** The injected S3 client and the injected
transport are each wrapped in a counter that forwards every call unchanged, so the
reported invocation counts are what the dependencies were actually asked for. A run
that retried its locator reports the retry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.ingest.sharadar.client import Pacer, RetryPolicy
from kalpamani.data.ingest.sharadar.composition import (
    execute_qualification_acquisition,
    preflight_qualification_composition,
)
from kalpamani.data.ingest.sharadar.credentials import SharadarCredential
from kalpamani.data.ingest.sharadar.runtime import (
    QualificationClock,
    QualificationOutcome,
    QualificationRunResult,
)
from kalpamani.data.qualify.sharadar.inventory import PrivateInventory
from kalpamani.data.qualify.sharadar.locator import (
    build_locator_document,
    locator_object_key,
    serialize_locator,
)
from kalpamani.data.qualify.sharadar.operations import (
    AcquisitionOperationCounts,
    CountingS3Client,
    LocatorPublication,
    LocatorPublicationStatus,
    publish_locator,
)
from kalpamani.data.qualify.sharadar.plan import (
    EMPIRICAL_REQUEST_COUNT,
    MAX_RESPONSE_BYTES,
    PROVIDER_MAX_ATTEMPTS,
    TIMEOUT_SECONDS,
    EmpiricalPlan,
    build_empirical_plan,
)
from kalpamani.data.storage.s3 import S3ResearchObjectStore

#: The one retry policy this package permits: one attempt, no backoff. A second
#: attempt is refused by the accepted plan model's retry-budget arithmetic before
#: this constant is even consulted, which is the stronger of the two guarantees.
NO_RETRY_POLICY: Final = RetryPolicy(max_attempts=PROVIDER_MAX_ATTEMPTS, backoff_seconds=())


class AcquisitionStatus(StrEnum):
    """How one empirical acquisition execution ended. Closed, and never a verdict.

    ``COMPLETED``
        Every planned request completed and the locator is addressable.
    ``PARTIAL``
        The run halted. Whatever was published stays published, the locator records
        the accounting, and **the assessor will refuse to evaluate it**.
    ``LOCATOR_NOT_PUBLISHED``
        The evidence exists and is **unaddressable**. A new execution identity is
        required; there is no listing that could recover it, and none will be added.
    ``LOCATOR_STATE_UNKNOWN``
        The locator write could not be verified either way. Same consequence.
    ``LOCATOR_COLLISION``
        The locator name is held by different content. A new execution identity is
        required; retrying repeats the collision.
    """

    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    LOCATOR_NOT_PUBLISHED = "LOCATOR_NOT_PUBLISHED"
    LOCATOR_STATE_UNKNOWN = "LOCATOR_STATE_UNKNOWN"
    LOCATOR_COLLISION = "LOCATOR_COLLISION"


#: How a locator publication status becomes an acquisition status when the run
#: itself completed. **Total, and checked by a test**: no ``.get`` default and no
#: ``else``, so a status added later has no mapping and fails loudly rather than
#: silently becoming a completion.
_LOCATOR_STATUS: Final[dict[LocatorPublicationStatus, AcquisitionStatus]] = {
    LocatorPublicationStatus.PUBLISHED: AcquisitionStatus.COMPLETED,
    LocatorPublicationStatus.ALREADY_PRESENT: AcquisitionStatus.COMPLETED,
    LocatorPublicationStatus.NOT_PUBLISHED: AcquisitionStatus.LOCATOR_NOT_PUBLISHED,
    LocatorPublicationStatus.STATE_UNKNOWN: AcquisitionStatus.LOCATOR_STATE_UNKNOWN,
    LocatorPublicationStatus.COLLISION: AcquisitionStatus.LOCATOR_COLLISION,
}


class CountingTransport:
    """A provider transport that counts requests and does nothing else.

    Wraps an injected transport and forwards ``get`` unchanged. Counting here rather
    than inferring from the run result is what makes the provider-request figure an
    **observed** count: a request that failed was still a request, and a number
    derived from completed acquisitions would silently omit it.
    """

    __slots__ = ("_transport", "request_count")

    def __init__(self, transport: Any) -> None:
        """Bind the injected transport and start the counter at zero."""
        if not callable(getattr(transport, "get", None)):
            raise TypeError("a transport must provide a callable get")
        self._transport = transport
        self.request_count = 0

    def __repr__(self) -> str:
        """A count. **Never the wrapped transport, a URL or a credential.**"""
        return f"CountingTransport(requests={self.request_count})"

    @property
    def max_response_bytes(self) -> int:
        """The wrapped transport's declared ceiling, unchanged."""
        declared = self._transport.max_response_bytes
        return declared if type(declared) is int else MAX_RESPONSE_BYTES

    def get(self, **kwargs: Any) -> Any:
        """Count the request, then forward it unchanged.

        Counted **before** the call, so a request that raised is still counted. A
        counter that recorded only successes would understate exactly the runs whose
        accounting matters most.
        """
        self.request_count += 1
        return self._transport.get(**kwargs)


@dataclass(frozen=True, slots=True, kw_only=True)
class EmpiricalAcquisitionResult:
    """The closed record of one empirical acquisition execution.

    **No field carries a subject, a key, a digest, a bucket or a payload.** What a
    caller gets is a status, an attempt count and an operation accounting -- which is
    everything a public transcript may hold, and nothing more. The evidence itself
    lives in the licensed store, addressed by the locator.
    """

    status: AcquisitionStatus
    locator_attempts: int
    counts: AcquisitionOperationCounts

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so a result cannot be restated after the fact."""
        raise TypeError("EmpiricalAcquisitionResult may not be subclassed")

    @property
    def addressable(self) -> bool:
        """Whether an assessment could later retrieve this execution's locator."""
        return self.status in (AcquisitionStatus.COMPLETED, AcquisitionStatus.PARTIAL)


def _status_for(
    result: QualificationRunResult, publication: LocatorPublication
) -> AcquisitionStatus:
    """One closed status from the run result and the locator publication.

    A locator problem outranks a partial run: an unaddressable execution cannot be
    assessed at all, so reporting ``PARTIAL`` for it would overstate what the owner
    can do next.
    """
    mapped = _LOCATOR_STATUS[publication.status]
    if mapped is not AcquisitionStatus.COMPLETED:
        return mapped
    complete = (
        result.outcome is QualificationOutcome.COMPLETED
        and result.completed_requests == result.planned_requests
        and not result.partial
        and not result.publication_state_unknown
    )
    return AcquisitionStatus.COMPLETED if complete else AcquisitionStatus.PARTIAL


def run_empirical_acquisition(
    *,
    credential: SharadarCredential,
    transport: Any,
    pacer: Pacer,
    s3_client: Any,
    licensed_bucket: str,
    clock: QualificationClock,
    inventory: PrivateInventory,
    execution_id: str,
) -> EmpiricalAcquisitionResult:
    """Build the plan, execute it, and publish exactly one locator last.

    The retry policy, the timeout and every ceiling are this module's constants and
    are **not parameters**: an operator who could supply them could supply a
    retrieval nobody reviewed. The pacer is injected because its clock and sleep must
    be injectable for tests, and its interval is checked here rather than trusted.

    Returns:
        The closed record of what happened. A halted run and a failed locator are
        **returned, not raised**: published objects are immutable and have no
        rollback, so a caller needs the accounting rather than an exception that
        discards it.

    Raises:
        EmpiricalPlanError: for a plan defect. **Nothing is fetched and nothing is
            stored** -- the refusal happens before the first request.
    """
    plan: EmpiricalPlan = build_empirical_plan(
        inventory=inventory, execution_id=execution_id, instant=clock.now()
    )

    counting_client = CountingS3Client(s3_client)
    counting_transport = CountingTransport(transport)

    # **Offline plan preflight, before the first request.** It validates the plan
    # against the injected client's own attempt policy and byte ceiling, so a
    # configuration that could not have completed is refused while it is still free.
    # It issues no provider request and no store call, and it is the accepted
    # composition root's own check rather than a second opinion.
    preflight_qualification_composition(
        credential=credential,
        transport=counting_transport,
        pacer=pacer,
        retry_policy=NO_RETRY_POLICY,
        timeout_seconds=TIMEOUT_SECONDS,
        s3_client=counting_client,
        licensed_bucket=licensed_bucket,
        clock=clock,
        plan=plan.plan,
    )

    run_started_at = clock.now()
    result = execute_qualification_acquisition(
        credential=credential,
        transport=counting_transport,
        pacer=pacer,
        retry_policy=NO_RETRY_POLICY,
        timeout_seconds=TIMEOUT_SECONDS,
        s3_client=counting_client,
        licensed_bucket=licensed_bucket,
        clock=clock,
        plan=plan.plan,
    )
    run_completed_at = clock.now()

    # Built once, held, and written byte-identically on every attempt. Rebuilding it
    # per attempt would read a new clock and produce a different document, which is
    # how a conditional retry stops being idempotent.
    payload = serialize_locator(
        build_locator_document(
            plan=plan,
            result=result,
            run_started_at=run_started_at,
            run_completed_at=run_completed_at,
        )
    )
    store = S3ResearchObjectStore(client=counting_client, licensed_bucket=licensed_bucket)
    publication = publish_locator(
        store=store,
        key=locator_object_key(execution_id=plan.plan.execution_id, payload=payload),
        payload=payload,
    )

    return EmpiricalAcquisitionResult(
        status=_status_for(result, publication),
        locator_attempts=publication.attempts,
        counts=AcquisitionOperationCounts(
            completed_requests=result.completed_requests,
            put_object_count=counting_client.put_object_count,
            head_object_count=counting_client.head_object_count,
            # Structural, not measured: the writer-side client this path uses has no
            # ``get_object`` in its shape at all, and no listing or CONTROL surface
            # exists anywhere in this architecture to have counted.
            get_object_count=0,
            list_operation_count=0,
            control_operation_count=0,
            locator_put_attempts=publication.attempts,
            provider_request_count=counting_transport.request_count,
        ),
    )


__all__ = [
    "EMPIRICAL_REQUEST_COUNT",
    "NO_RETRY_POLICY",
    "AcquisitionStatus",
    "CountingTransport",
    "EmpiricalAcquisitionResult",
    "run_empirical_acquisition",
]
