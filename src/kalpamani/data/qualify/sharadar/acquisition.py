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

**One real elapsed-time deadline governs the acquisition execution phase.** It is
armed here, at the stage-11 boundary -- after the offline preflight has returned and
immediately before the call that performs the first provider request -- and it ends
at the terminal locator result. Nothing in stages 1 to 10 consumes it.

The deadline reaches the accepted runtime the only way an accepted contract may be
reached: **by injection**. The transport wrapper admits each provider request, the
pacer is built with a sleeper that admits each pacing delay, and the counting S3
client admits each Bronze and locator invocation. The runtime is not modified,
because it does not need to be -- it already halts cleanly and returns its
accounting whenever an injected dependency refuses, which is exactly what the
deadline makes one do.

**Forty-eight requests are a maximum, not a promise.** The deadline is a safety
bound on elapsed time. A slow provider means the run halts short, keeps every
completed request, publishes a ``PARTIAL`` locator while the reserve still allows
one, and reports ``RUN_DEADLINE_EXHAUSTED``. A deadline is not a rollback.
"""

from __future__ import annotations

from collections.abc import Callable
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
    AcquisitionDeadline,
    AcquisitionOperationCounts,
    CountingS3Client,
    LocatorPublication,
    LocatorPublicationStatus,
    publish_locator,
)
from kalpamani.data.qualify.sharadar.plan import (
    ACQUISITION_DEADLINE_SECONDS,
    EMPIRICAL_REQUEST_COUNT,
    MAX_RESPONSE_BYTES,
    MIN_REQUEST_INTERVAL_SECONDS,
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
    ``RUN_DEADLINE_EXHAUSTED``
        The run halted because the acquisition elapsed-time deadline was reached.
        A ``PARTIAL`` with its cause named: **completed requests remain completed**,
        because a deadline is not a rollback, and the locator was still published.
        **It authorizes nothing** -- not a retry, not a resume, not a new execution
        identity. Re-running is a separate authorization, and there is no resume.
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
    RUN_DEADLINE_EXHAUSTED = "RUN_DEADLINE_EXHAUSTED"
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

    __slots__ = ("_deadline", "_transport", "request_count")

    def __init__(self, transport: Any, *, deadline: AcquisitionDeadline) -> None:
        """Bind the injected transport and the deadline, counter at zero."""
        if not callable(getattr(transport, "get", None)):
            raise TypeError("a transport must provide a callable get")
        if type(deadline) is not AcquisitionDeadline:
            raise TypeError("a counting transport requires the acquisition deadline")
        self._transport = transport
        self._deadline = deadline
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
        """Admit against the deadline, count the request, then forward it unchanged.

        **Admission first**, so a request the deadline refuses is never sent and
        never counted: nothing left the machine, and a counter claiming otherwise
        would misreport what the vendor was asked for. **Counting second**, so a
        request that raised is still counted -- it was sent.

        The pacing delay for this request has already been checked and has already
        elapsed by the time this runs, because the accepted client paces before it
        calls a transport. Admission therefore requires the request ceiling, the
        Bronze obligation and the locator reserve, and **not** the pacing interval
        again.

        Raises:
            DeadlineExhaustedError: which the accepted client converts into a sanitized
                request failure and the accepted runtime converts into a clean halt.
        """
        self._deadline.admit_provider_request()
        self.request_count += 1
        return self._transport.get(**kwargs)


class DeadlinePacedSleeper:
    """The sleep the accepted pacer performs, admitted against the deadline first.

    The accepted :class:`~kalpamani.data.ingest.sharadar.client.Pacer` computes the
    exact delay it owes and hands it to an injected sleeper, which is the one place
    the delay is known as a number before it is spent. So the budget check lives
    here: **before the sleep begins, on the real interval, and never truncating it**.

    Refusing rather than shortening is the point. A pacer that trimmed its interval
    to fit a deadline would break the request spacing this package commits to, and
    would do it on exactly the runs already under pressure -- silently, because both
    a full and a trimmed delay look like a delay.
    """

    __slots__ = ("_deadline", "_sleeper", "admitted_count", "slept_seconds")

    def __init__(self, *, deadline: AcquisitionDeadline, sleeper: Callable[[float], None]) -> None:
        """Bind the deadline and the real sleep."""
        if type(deadline) is not AcquisitionDeadline:
            raise TypeError("a paced sleeper requires the acquisition deadline")
        if not callable(sleeper):
            raise TypeError("a paced sleeper requires a callable sleep")
        self._deadline = deadline
        self._sleeper = sleeper
        self.admitted_count = 0
        self.slept_seconds = 0.0

    def __repr__(self) -> str:
        """A count. **Never the wrapped sleep and never the deadline's numbers.**"""
        return f"DeadlinePacedSleeper(admitted={self.admitted_count})"

    def __call__(self, seconds: float) -> None:
        """Admit ``seconds`` against the deadline, then sleep exactly that long.

        Raises:
            DeadlineExhaustedError: ``PACING``. The pacer calls this from outside the
                accepted client's own try block, so the refusal reaches the accepted
                runtime, which halts and returns its accounting.
        """
        self._deadline.admit_pacing(seconds)
        self.admitted_count += 1
        self.slept_seconds += float(seconds)
        self._sleeper(seconds)


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
    #: Whether an admission against the acquisition deadline refused something.
    #: Recorded as a fact about the run, and **never as a permission**: it does not
    #: authorize a retry, a resume or a new execution identity.
    deadline_exhausted: bool = False

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so a result cannot be restated after the fact."""
        raise TypeError("EmpiricalAcquisitionResult may not be subclassed")

    @property
    def addressable(self) -> bool:
        """Whether an assessment could later retrieve this execution's locator."""
        return self.status in (
            AcquisitionStatus.COMPLETED,
            AcquisitionStatus.PARTIAL,
            AcquisitionStatus.RUN_DEADLINE_EXHAUSTED,
        )


def _status_for(
    result: QualificationRunResult,
    publication: LocatorPublication,
    *,
    deadline_exhausted: bool,
) -> AcquisitionStatus:
    """One closed status from the run result, the locator publication and the deadline.

    The precedence, and why it is this way round:

    **A locator problem outranks everything.** An unaddressable execution cannot be
    assessed at all, so reporting a halt reason for it would overstate what the
    owner can do next -- the next step is a new execution identity either way.

    **Deadline exhaustion outranks a plain partial**, because it names the cause. A
    run that stopped at 1,800 seconds and a run that stopped because the provider
    refused are both partial, and telling them apart is the difference between
    reviewing a timing budget and reviewing a vendor.
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
    if complete:
        return AcquisitionStatus.COMPLETED
    if deadline_exhausted:
        return AcquisitionStatus.RUN_DEADLINE_EXHAUSTED
    return AcquisitionStatus.PARTIAL


def run_empirical_acquisition(
    *,
    credential: SharadarCredential,
    transport: Any,
    monotonic: Callable[[], float],
    sleeper: Callable[[float], None],
    s3_client: Any,
    licensed_bucket: str,
    clock: QualificationClock,
    inventory: PrivateInventory,
    execution_id: str,
) -> EmpiricalAcquisitionResult:
    """Build the plan, execute it under one deadline, and publish one locator last.

    The retry policy, the timeout, the deadline and every ceiling are constants and
    are **not parameters**: an operator who could supply them could supply a
    retrieval nobody reviewed.

    ``monotonic`` and ``sleeper`` replace the caller-supplied pacer of an earlier
    revision, and the replacement is the correction. A pacer built outside this
    function is a pacer whose sleep is not admitted against the deadline, and one
    unadmitted sleep is enough to run past 1,800 seconds. The pacer is therefore
    built **here**, from the same monotonic source the deadline uses, so pacing and
    the budget cannot read two different clocks.

    ``clock`` remains the calendar clock, and it is used **only** for the retrieval
    instants and the locator's run timestamps. **No deadline arithmetic touches
    it** -- a calendar step must not be able to lengthen or shorten a licensed
    acquisition.

    Returns:
        The closed record of what happened. A halted run, an exhausted deadline and
        a failed locator are **returned, not raised**: published objects are
        immutable and have no rollback, so a caller needs the accounting rather than
        an exception that discards it.

    Raises:
        EmpiricalPlanError: for a plan defect. **Nothing is fetched and nothing is
            stored** -- the refusal happens before the deadline is even armed.
    """
    plan: EmpiricalPlan = build_empirical_plan(
        inventory=inventory, execution_id=execution_id, instant=clock.now()
    )

    deadline = AcquisitionDeadline(monotonic=monotonic, deadline_seconds=plan.deadline_seconds)
    counting_client = CountingS3Client(s3_client, deadline=deadline)
    counting_transport = CountingTransport(transport, deadline=deadline)
    pacer = Pacer(
        min_interval=MIN_REQUEST_INTERVAL_SECONDS,
        clock=monotonic,
        sleeper=DeadlinePacedSleeper(deadline=deadline, sleeper=sleeper),
    )

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

    # **Stage 11 begins here.** Everything above -- authorization, the inventory,
    # identity, binding, the credential, dependency construction and the offline
    # preflight -- is a gate, and consumes none of this budget. Arming immediately
    # before the call that performs the first provider request is the earliest
    # point at which no provider or S3 operation can already have happened, and the
    # only work between the arm and that request is the runtime's own offline
    # `validate()`, which sends nothing. Including it is conservative: it can make
    # a run halt marginally earlier, never later.
    run_started_at = clock.now()
    deadline.arm()
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

    # **Stage 13 begins here.** From this point the reserve held back all run is
    # what is being spent, so an S3 operation no longer has to leave it behind.
    deadline.begin_locator_phase()

    if not deadline.permits_locator_construction():
        # **No safe attempt remains, so none is started.** The accepted closed
        # result for this is ``LOCATOR_NOT_PUBLISHED``, and it says exactly what
        # happened: the evidence exists and is unaddressable. It must not claim a
        # locator exists, and it authorizes no retry -- a new execution identity is
        # the only way forward, and that is a separate authorization.
        publication = LocatorPublication(status=LocatorPublicationStatus.NOT_PUBLISHED, attempts=0)
    else:
        # Built once, held, and written byte-identically on every attempt.
        # Rebuilding it per attempt would read a new clock and produce a different
        # document, which is how a conditional retry stops being idempotent.
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
            deadline=deadline,
        )

    return EmpiricalAcquisitionResult(
        status=_status_for(result, publication, deadline_exhausted=deadline.exhausted),
        locator_attempts=publication.attempts,
        deadline_exhausted=deadline.exhausted,
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
    "ACQUISITION_DEADLINE_SECONDS",
    "EMPIRICAL_REQUEST_COUNT",
    "NO_RETRY_POLICY",
    "AcquisitionStatus",
    "CountingTransport",
    "DeadlinePacedSleeper",
    "EmpiricalAcquisitionResult",
    "run_empirical_acquisition",
]
