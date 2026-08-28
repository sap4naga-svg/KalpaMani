"""The dormant qualification runtime: a bounded plan, executed against injected parts.

**Dormant. This has never been run against Sharadar or AWS, and cannot reach
either by itself.** It constructs no client, no transport, no credential, no
session and no bucket; it reads no environment variable and no file. Everything it
touches is handed to it. A future, separately authorized composition root would
build a real
:class:`~kalpamani.data.ingest.sharadar.client.SharadarClient` and a real
:class:`~kalpamani.data.storage.s3.S3ResearchObjectStore` and pass them in --
**and that composition root does not exist** (ADR-0012).

**Nothing here is a second storage layer.** Publication goes through
:func:`~kalpamani.data.ingest.sharadar.bronze.publish_sharadar_payload`, which
goes through the vendor-neutral publisher, which owns content addressing,
append-only identity, the LICENSED classification and the disclosure guard. There
is no S3 call in this module and no route around the bridge.

**A failure stops the run and is reported, not raised.** Every object already
published is immutable and already in a licensed bucket; an exception would
discard the record of exactly which ones. So execution returns a
:class:`QualificationRunResult` carrying ``HALTED``, a closed failure code and the
outcomes that did complete. **A partial run is stated as partial** rather than
implied to be transactional -- because it is not, and cannot be: several immutable
objects across several requests have no rollback.

**Resume is safe because the store refuses to lie.** Re-running the same plan with
the same run id republishes identical bytes, which the object store reports as an
idempotent no-op; bytes that changed are refused as a collision rather than
overwritten. That is the whole resume story, and it is the existing content
identity doing the work rather than a bookkeeping file this module would have to
keep honest.

**Nothing that arrives from a dependency reaches a message.** A response body, a
URL carrying the key (`PSR-SHD-109`), a bucket name, a backend error string and an
arbitrary exception have no parameter to enter through: every failure is one
member of :class:`QualificationFailure`, and exceptions are raised ``from None``.

**Point-in-time consequences are enforced, not documented.** The plan's profile is
already held to ``PROVIDER_REALISTIC_PIT``; this module records the same on every
outcome and never emits ``PUBLIC_PIT``. It resolves neither Q7, nor Q8, nor the
``permaticker`` conflict, and it derives nothing from ``permaticker`` at all --
payloads are opaque bytes here and are never parsed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from kalpamani.data.contracts.errors import (
    ObjectAlreadyExistsError,
    ObjectStoreError,
    PointInTimeError,
)
from kalpamani.data.contracts.vocabulary import (
    DataClassification,
    InformationSetProfile,
    closed_member,
)
from kalpamani.data.ingest.sharadar.bronze import publish_sharadar_payload
from kalpamani.data.ingest.sharadar.client import SharadarClient
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset, SharadarRequest
from kalpamani.data.ingest.sharadar.qualification import (
    PERMITTED_PROFILE,
    QualificationDefect,
    QualificationPlan,
    QualificationPlanError,
    refuse_retry_budget,
)
from kalpamani.data.ingest.sharadar.redaction import SharadarRequestError
from kalpamani.data.objectstore import ResearchObjectStore


class QualificationOutcome(StrEnum):
    """How a whole run ended. Three states, and none of them is ambiguous.

    ``COMPLETED``
        Every planned request was fetched and published.
    ``HALTED``
        A terminal failure stopped the run. Whatever had already been published
        stays published -- immutable objects have no rollback -- and the result
        says exactly which ones.
    ``REFUSED``
        Nothing ran. The plan or the injected dependencies were rejected before
        the first fetch, so no request was sent and no object was written.
    """

    COMPLETED = "COMPLETED"
    HALTED = "HALTED"
    REFUSED = "REFUSED"


class QualificationFailure(StrEnum):
    """Why a run halted, in categories a caller can act on.

    Deliberately coarse, for the reason the whole redaction module exists: a finer
    vocabulary would have to be derived from what the vendor or the backend
    *said*, and what they say is exactly what must not reach a log.
    """

    PROVIDER_REQUEST_FAILED = "PROVIDER_REQUEST_FAILED"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    RUN_BYTE_CEILING_EXCEEDED = "RUN_BYTE_CEILING_EXCEEDED"
    PAYLOAD_NOT_EXACT_BYTES = "PAYLOAD_NOT_EXACT_BYTES"
    CONTENT_CONFLICT = "CONTENT_CONFLICT"
    STORAGE_REFUSED = "STORAGE_REFUSED"
    DEPENDENCY_MALFORMED = "DEPENDENCY_MALFORMED"
    UNCLASSIFIED = "UNCLASSIFIED"


class PublicationDisposition(StrEnum):
    """What one publication actually did to the store.

    ``STORED`` and ``ALREADY_PRESENT`` are reported separately because they are
    the difference between a first run and a resumed one, and a run that reported
    them the same way could not tell progress from repetition.
    """

    STORED = "STORED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


class QualificationClock(Protocol):
    """The one time source this runtime uses. Injected, never ambient.

    A wall clock read inside the runtime would make two runs of the same plan
    produce different acquisition records, and therefore different content
    addresses, for the same bytes.
    """

    def now(self) -> datetime:
        """The instant to record as this retrieval's ``retrieved_at``."""
        ...


class QualificationRuntimeError(PointInTimeError):
    """A dependency was refused before anything ran. Closed vocabulary only.

    Raised, rather than reported, precisely because **nothing has happened yet**:
    there is no partial state for a caller to learn about, so an exception loses
    nothing and stops the caller at the point of the mistake.
    """

    __slots__ = ("failure",)

    def __init__(self, failure: QualificationFailure) -> None:
        """Carry one failure category. Nothing else has a home here."""
        self.failure = closed_member(QualificationFailure, failure) or (
            QualificationFailure.UNCLASSIFIED
        )
        super().__init__(f"sharadar qualification runtime refused: {self.failure.value}")


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestOutcome:
    """What one planned request produced. Safe to log in full.

    Every field is either a closed vocabulary member, a validated identifier, a
    digest or a count. **There is no payload field and no error-text field**, so a
    response body and a backend message have nowhere to be.
    """

    dataset: SharadarDataset
    subject: str
    page_skip: int
    content_sha256: str
    byte_count: int
    disposition: PublicationDisposition
    classification: DataClassification
    profile: InformationSetProfile

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so a reported outcome cannot be restated."""
        raise QualificationRuntimeError(QualificationFailure.DEPENDENCY_MALFORMED) from None


@dataclass(frozen=True, slots=True, kw_only=True)
class QualificationRunResult:
    """The immutable record of one run. Counts, identities and dispositions only.

    ``partial`` is stated rather than inferred. A caller that had to derive it
    from ``len(outcomes) != planned_requests`` would be deriving the most
    important fact about a failed run from arithmetic.
    """

    outcome: QualificationOutcome
    failure: QualificationFailure | None
    planned_requests: int
    completed_requests: int
    stored_objects: int
    already_present_objects: int
    total_bytes: int
    outcomes: tuple[RequestOutcome, ...]
    partial: bool

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so a result cannot be restated after the fact."""
        raise QualificationRuntimeError(QualificationFailure.DEPENDENCY_MALFORMED) from None


class QualificationRuntime:
    """Executes a bounded plan against an already-constructed client and store.

    **Every dependency is a constructor parameter with no default.** A runtime
    that could build its own client is a runtime a forgetful test can point at the
    vendor, and a runtime that could build its own store is one that needs a
    bucket name. Neither exists here.
    """

    __slots__ = ("_client", "_clock", "_store")

    def __init__(
        self,
        *,
        client: SharadarClient,
        store: ResearchObjectStore,
        clock: QualificationClock,
    ) -> None:
        """Bind an already-constructed client, object store and clock.

        Raises:
            QualificationRuntimeError: ``DEPENDENCY_MALFORMED`` if the client is
                not an exact :class:`SharadarClient`, or if the store or clock
                cannot serve the one method this runtime calls on each. A
                ``Protocol`` annotation is a static claim; this is the runtime
                half of it.
        """
        if type(client) is not SharadarClient:
            raise QualificationRuntimeError(QualificationFailure.DEPENDENCY_MALFORMED) from None
        if not callable(getattr(store, "put_if_absent", None)):
            raise QualificationRuntimeError(QualificationFailure.DEPENDENCY_MALFORMED) from None
        if not callable(getattr(clock, "now", None)):
            raise QualificationRuntimeError(QualificationFailure.DEPENDENCY_MALFORMED) from None
        self._client = client
        self._store = store
        self._clock = clock

    def __repr__(self) -> str:
        """A constant. Nothing caller-supplied, so it is safe to log unthinkingly."""
        return "QualificationRuntime(provider=sharadar, mode=injected)"

    # -- validation, all of it, before anything is fetched -------------------

    def validate(self, plan: QualificationPlan) -> tuple[SharadarRequest, ...]:
        """The requests ``plan`` will issue, or a refusal. **Fetches nothing.**

        Called by :meth:`execute` first, and callable on its own so a plan can be
        checked without a run. Everything checkable is checked here: the plan's
        own rules at construction, the retry budget against the *injected
        client's* attempt policy, and the request count against the plan's
        ceiling.

        Raises:
            QualificationPlanError: for any plan defect, including a retry budget
                the client's policy would exceed.
            QualificationRuntimeError: ``DEPENDENCY_MALFORMED`` if ``plan`` is not
                an exact :class:`QualificationPlan`, or if the injected clock
                cannot answer with an aware ``datetime``.
        """
        if type(plan) is not QualificationPlan:
            raise QualificationRuntimeError(QualificationFailure.DEPENDENCY_MALFORMED) from None
        requests = plan.requests()
        if len(requests) != plan.request_count:
            # The plan's arithmetic and its generator disagreeing would mean the
            # ceiling checked at construction bounded a different number from the
            # one about to be issued.
            raise QualificationPlanError(QualificationDefect.PLAN_MALFORMED) from None
        if len(requests) > plan.limits.max_requests:
            raise QualificationPlanError(QualificationDefect.LIMIT_EXCEEDS_CEILING) from None
        refuse_retry_budget(
            request_count=len(requests),
            max_attempts=self._client.max_attempts,
            budget=plan.limits.retry_budget,
        )
        # Probe the clock here, where a fault costs nothing. A clock that cannot
        # answer is a dependency defect exactly like a store that cannot publish,
        # and discovering it after the first fetch would spend a provider request
        # to learn something checkable for free.
        self._retrieved_at()
        return requests

    # -- execution -----------------------------------------------------------

    def execute(self, plan: QualificationPlan) -> QualificationRunResult:
        """Run ``plan`` end to end, stopping at the first terminal failure.

        Requests are issued in the plan's canonical order. Each response is
        published byte for byte through the Bronze bridge under ``LICENSED``; the
        bytes are never decoded, parsed or inspected, so a malformed payload is
        preserved as evidence rather than lost at the boundary.

        The return value is the record of what happened, including a run that
        stopped early. Nothing is rolled back, because immutable objects across
        several requests cannot be.

        Raises:
            QualificationPlanError: if the plan is refused. **Nothing is fetched
                and nothing is stored** -- a refusal happens before the first call.
            QualificationRuntimeError: if a dependency is refused, for the same
                reason and with the same guarantee.
        """
        requests = self.validate(plan)

        outcomes: list[RequestOutcome] = []
        total_bytes = 0
        stored = 0
        already = 0

        for request in requests:
            try:
                payload = self._client.fetch(request)
            except SharadarRequestError:
                # Already sanitized by construction, and deliberately not chained:
                # its own repr is safe, but a chained traceback would also print
                # every frame between here and the transport.
                return self._halted(
                    QualificationFailure.PROVIDER_REQUEST_FAILED,
                    plan,
                    outcomes,
                    total_bytes,
                    stored,
                    already,
                )
            except Exception:
                # An injected client is code this module did not write. Whatever
                # it raises may carry the URL, and the URL carries the key.
                return self._halted(
                    QualificationFailure.UNCLASSIFIED,
                    plan,
                    outcomes,
                    total_bytes,
                    stored,
                    already,
                )

            if type(payload) is not bytes:
                # A `bytearray` would let the bytes change after they were hashed;
                # anything else was never a payload.
                return self._halted(
                    QualificationFailure.PAYLOAD_NOT_EXACT_BYTES,
                    plan,
                    outcomes,
                    total_bytes,
                    stored,
                    already,
                )
            if len(payload) > plan.limits.max_response_bytes:
                return self._halted(
                    QualificationFailure.RESPONSE_TOO_LARGE,
                    plan,
                    outcomes,
                    total_bytes,
                    stored,
                    already,
                )
            if total_bytes + len(payload) > plan.limits.max_run_bytes:
                # Checked before publishing, so the ceiling bounds what is stored
                # rather than what was already stored.
                return self._halted(
                    QualificationFailure.RUN_BYTE_CEILING_EXCEEDED,
                    plan,
                    outcomes,
                    total_bytes,
                    stored,
                    already,
                )

            try:
                retrieved_at = self._retrieved_at()
            except QualificationRuntimeError:
                # Deliberately **not** inside the publication handler below. A
                # clock that broke mid-run is a dependency fault, and reporting it
                # as an unclassified storage failure would send a reader to look
                # at the bucket. Halting rather than raising keeps the record of
                # what was already published, which is the whole reason execution
                # reports instead of raising.
                return self._halted(
                    QualificationFailure.DEPENDENCY_MALFORMED,
                    plan,
                    outcomes,
                    total_bytes,
                    stored,
                    already,
                )

            try:
                published = publish_sharadar_payload(
                    store=self._store,
                    request=request,
                    payload=payload,
                    retrieved_at=retrieved_at,
                    ingestion_run_id=plan.ingestion_run_id,
                    source_schema_version=plan.source_schema_version,
                    is_backfill=plan.is_backfill,
                )
            except ObjectAlreadyExistsError:
                # The name is held by different content. Never overwritten: this
                # is either a collision or a corruption, and neither is resolved
                # by replacing evidence.
                return self._halted(
                    QualificationFailure.CONTENT_CONFLICT,
                    plan,
                    outcomes,
                    total_bytes,
                    stored,
                    already,
                )
            except ObjectStoreError:
                return self._halted(
                    QualificationFailure.STORAGE_REFUSED,
                    plan,
                    outcomes,
                    total_bytes,
                    stored,
                    already,
                )
            except Exception:
                return self._halted(
                    QualificationFailure.UNCLASSIFIED,
                    plan,
                    outcomes,
                    total_bytes,
                    stored,
                    already,
                )

            disposition = (
                PublicationDisposition.STORED
                if published.payload_written
                else PublicationDisposition.ALREADY_PRESENT
            )
            if published.payload_written:
                stored += 1
            else:
                already += 1
            total_bytes += published.byte_count
            outcomes.append(
                RequestOutcome(
                    dataset=request.dataset,
                    subject=request.ticker,
                    page_skip=request.page.skip,
                    content_sha256=published.content_sha256,
                    byte_count=published.byte_count,
                    disposition=disposition,
                    classification=DataClassification.LICENSED,
                    profile=PERMITTED_PROFILE,
                )
            )

        return QualificationRunResult(
            outcome=QualificationOutcome.COMPLETED,
            failure=None,
            planned_requests=len(requests),
            completed_requests=len(outcomes),
            stored_objects=stored,
            already_present_objects=already,
            total_bytes=total_bytes,
            outcomes=tuple(outcomes),
            partial=False,
        )

    # -- helpers -------------------------------------------------------------

    def _retrieved_at(self) -> datetime:
        """The injected clock's instant, as an aware UTC ``datetime``.

        A naive instant would be recorded as though its offset were known, and a
        non-UTC one would make two runs of the same plan on two machines produce
        different records for the same bytes.

        Raises:
            QualificationRuntimeError: ``DEPENDENCY_MALFORMED`` if the clock
                returns anything other than an aware ``datetime``.
        """
        try:
            instant = self._clock.now()
        except Exception:
            raise QualificationRuntimeError(QualificationFailure.DEPENDENCY_MALFORMED) from None
        if type(instant) is not datetime or instant.tzinfo is None:
            raise QualificationRuntimeError(QualificationFailure.DEPENDENCY_MALFORMED) from None
        return instant.astimezone(UTC)

    def _halted(
        self,
        failure: QualificationFailure,
        plan: QualificationPlan,
        outcomes: Sequence[RequestOutcome],
        total_bytes: int,
        stored: int,
        already: int,
    ) -> QualificationRunResult:
        """The record of a run that stopped early. ``partial`` is stated, not derived."""
        return QualificationRunResult(
            outcome=QualificationOutcome.HALTED,
            failure=failure,
            planned_requests=plan.request_count,
            completed_requests=len(outcomes),
            stored_objects=stored,
            already_present_objects=already,
            total_bytes=total_bytes,
            outcomes=tuple(outcomes),
            partial=True,
        )


def refused_result(plan_requests: int) -> QualificationRunResult:
    """The result shape a caller may record when a plan was refused before running.

    Offered so a caller reporting a refusal does not have to invent a result with
    counts that might not be zero. Nothing was fetched and nothing was stored, and
    every count says so.
    """
    return QualificationRunResult(
        outcome=QualificationOutcome.REFUSED,
        failure=None,
        planned_requests=plan_requests if type(plan_requests) is int and plan_requests >= 0 else 0,
        completed_requests=0,
        stored_objects=0,
        already_present_objects=0,
        total_bytes=0,
        outcomes=(),
        partial=False,
    )


__all__ = [
    "PublicationDisposition",
    "QualificationClock",
    "QualificationFailure",
    "QualificationOutcome",
    "QualificationRunResult",
    "QualificationRuntime",
    "QualificationRuntimeError",
    "RequestOutcome",
    "refused_result",
]
