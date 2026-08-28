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

**One request is one acquisition.** Each request carries its own derived
:func:`~kalpamani.data.ingest.sharadar.qualification.acquisition_id`, so
byte-identical responses from two datasets, two subjects or two pages are three
different retrievals with three different durable records -- not a collision, and
not a collapse. Payload identity and acquisition identity are different things:
identical bytes deduplicate in the payload namespace, and that says nothing about
whether *this* retrieval was already recorded.

**One publication writes up to three objects, and the result says which.** The
neutral publisher writes a global acquisition claim, then the payload, then the
acquisition record. :class:`RequestOutcome` reports all three dispositions
separately, because "the payload was already there" and "this acquisition was
already recorded" are different facts and a result that conflated them could not
tell a first run from a repeat.

**A failure stops the run and is reported, not raised.** Every object already
published is immutable and already in a licensed bucket; an exception would
discard the record of exactly which ones. So execution returns a
:class:`QualificationRunResult` carrying ``HALTED``, a closed failure code and the
outcomes that did complete. **A partial run is stated as partial** rather than
implied to be transactional -- because it is not, and cannot be: several immutable
objects across several requests have no rollback.

**A publication that raises leaves durable state this module cannot describe.**
The three writes are separate appends. A failure on the second or third may have
committed the first; an ambiguous backend failure may not prove whether *any* of
them committed. :attr:`QualificationRunResult.publication_state_unknown` says so
explicitly, and **no field here claims to know which objects exist** after such a
failure.

**There is no resume.** An earlier revision of this module claimed that re-running
a halted plan resumed it safely through object-store idempotency. That was
false: a real second execution reads a new ``retrieved_at``, so the acquisition
record under an occupied name differs and is **refused** -- correctly, and not as
a resume. Re-running the same execution id after a halt therefore fails closed on
the first already-recorded request. A halted execution must be reviewed, and any
subsequent refetch must use a **new explicit execution id**. Durable cross-process
resume needs a governed checkpoint or attestation, and none exists; it is
deferred, and this module does not pretend otherwise.

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

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Protocol

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
    acquisition_id,
    refuse_retry_budget,
)
from kalpamani.data.ingest.sharadar.redaction import SharadarRequestError
from kalpamani.data.objectstore import ResearchObjectStore

#: What a qualification retrieval records for ``is_backfill``.
#:
#: **Fixed, and not a caller's choice.** An earlier revision took a raw boolean on
#: the plan, which would have let a caller label qualification evidence as a
#: production backfill by passing ``True`` -- turning a metadata field into an
#: authorization claim nobody made.
#:
#: ``False`` is the conservative reading: it is the value that cannot be mistaken
#: for authoritative historical loading. It is **not a perfect fit**, and saying so
#: is the honest position: the neutral contract describes this field as
#: distinguishing "a vendor backfill from an update", and a qualification
#: retrieval of an explicit historical window is neither. See ADR-0012 §4 and the
#: finding recorded there.
QUALIFICATION_IS_BACKFILL: Final = False

#: A content address, as the neutral layer spells one.
_DIGEST: Final = re.compile(r"^[0-9a-f]{64}$")

#: An acquisition identity, as :func:`acquisition_id` derives one and as the
#: neutral identifier grammar admits one.
_ACQUISITION_ID: Final = re.compile(r"^[a-z0-9][a-z0-9._\-]{0,63}$")

#: A subject, held to the same grammar the plan holds one to.
_SUBJECT: Final = re.compile(r"^[A-Z][A-Z0-9.\-]{0,15}$")


class QualificationOutcome(StrEnum):
    """How a whole run ended. Three states, and none of them is ambiguous.

    ``COMPLETED``
        Every planned request was fetched, and every acquisition record exists.
    ``HALTED``
        A terminal failure stopped the run. Whatever had already been published
        stays published -- immutable objects have no rollback -- and the result
        says exactly which acquisitions completed. It does **not** claim to know
        what a failed publication left behind.
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
    RESULT_MALFORMED = "RESULT_MALFORMED"
    UNCLASSIFIED = "UNCLASSIFIED"


class AcquisitionDisposition(StrEnum):
    """What one completed publication actually did to the store.

    Four states, because a publication writes three objects and the interesting
    cases are the mixtures. Reporting only "was the payload written" -- which an
    earlier revision did, and called ``stored_objects`` -- cannot tell a first
    retrieval from a repeat of one whose bytes happened to be present already.

    ``FULLY_NEW``
        Claim, payload and acquisition record all written. A first retrieval of
        these bytes under this identity.
    ``PAYLOAD_REUSED``
        Claim and record written; the payload was already stored. **A new
        acquisition**: identical bytes arrived again under a different request
        identity, and that retrieval is now recorded. Payload reuse is not
        acquisition reuse.
    ``ALREADY_COMPLETE``
        Nothing written. This exact acquisition was already fully recorded, with
        identical metadata.
    ``COMPLETED_PRIOR_PARTIAL``
        Some objects existed and some were written -- the signature of an earlier
        publication that was interrupted between its appends. The record is
        complete now, and the result says it was not complete before.
    """

    FULLY_NEW = "FULLY_NEW"
    PAYLOAD_REUSED = "PAYLOAD_REUSED"
    ALREADY_COMPLETE = "ALREADY_COMPLETE"
    COMPLETED_PRIOR_PARTIAL = "COMPLETED_PRIOR_PARTIAL"


def classify_publication(
    *, claim_written: bool, payload_written: bool, acquisition_written: bool
) -> AcquisitionDisposition:
    """Which :class:`AcquisitionDisposition` three write dispositions describe."""
    if claim_written and payload_written and acquisition_written:
        return AcquisitionDisposition.FULLY_NEW
    if claim_written and acquisition_written and not payload_written:
        return AcquisitionDisposition.PAYLOAD_REUSED
    if not claim_written and not payload_written and not acquisition_written:
        return AcquisitionDisposition.ALREADY_COMPLETE
    return AcquisitionDisposition.COMPLETED_PRIOR_PARTIAL


class QualificationClock(Protocol):
    """The one time source this runtime uses. Injected, never ambient.

    A wall clock read inside the runtime would make two executions of one plan
    produce different acquisition records for the same bytes -- which is exactly
    what makes a second execution a new acquisition rather than a resume.
    """

    def now(self) -> datetime:
        """The instant to record as this retrieval's ``retrieved_at``."""
        ...


class QualificationRuntimeError(PointInTimeError):
    """A dependency or a result was refused. Closed vocabulary only.

    Raised, rather than reported, in the two cases where reporting would be
    worse: **nothing has happened yet** (a malformed dependency, an unusable
    clock), so an exception loses nothing; or **the result itself is malformed**,
    where returning it would hand a caller a record that lies.
    """

    __slots__ = ("failure",)

    def __init__(self, failure: QualificationFailure) -> None:
        """Carry one failure category. Nothing else has a home here."""
        self.failure = closed_member(QualificationFailure, failure) or (
            QualificationFailure.UNCLASSIFIED
        )
        super().__init__(f"sharadar qualification runtime refused: {self.failure.value}")


def _refuse_result() -> QualificationRuntimeError:
    return QualificationRuntimeError(QualificationFailure.RESULT_MALFORMED)


def _member(vocabulary: type[StrEnum], value: object) -> StrEnum | None:
    """``value`` when it is already an **exact member** of ``vocabulary``, else ``None``.

    Stricter than
    :func:`~kalpamani.data.contracts.vocabulary.closed_member`, which normalises a
    bare string into the member it spells. A result is a record of what happened,
    not a parser: accepting ``"COMPLETED"`` where a member belongs would let two
    spellings of one state exist in stored evidence.
    """
    resolved = closed_member(vocabulary, value)
    return resolved if resolved is not None and resolved is value else None


def _exact_count(value: object) -> int:
    """``value`` as an exact non-negative ``int``, or a refusal.

    Exact, because ``True`` is an ``int`` in Python and a count of ``True`` is a
    count of one that nobody wrote.
    """
    if type(value) is not int or value < 0:
        raise _refuse_result() from None
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestOutcome:
    """What one planned request produced. Safe to log in full, and checked.

    Every field is a closed vocabulary member, a grammar-bound identifier, a
    digest, a count or a boolean. **There is no payload field and no error-text
    field**, so a response body and a backend message have nowhere to be -- and
    :meth:`__post_init__` enforces that rather than leaving it to the annotations,
    which are a static claim and not a runtime one.
    """

    dataset: SharadarDataset
    subject: str
    page_skip: int
    page_limit: int
    acquisition_id: str
    content_sha256: str
    byte_count: int
    retrieved_at: datetime
    claim_written: bool
    payload_written: bool
    acquisition_written: bool
    disposition: AcquisitionDisposition
    classification: DataClassification
    profile: InformationSetProfile

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so a reported outcome cannot be restated."""
        raise _refuse_result() from None

    def __post_init__(self) -> None:
        """Hold every field to its own contract. An annotation is not a check."""
        # `is None or is not` rather than a bare `is not`: `closed_member` answers
        # `None` for a value it cannot normalise, which is the *same object* as a
        # `dataset` of `None` -- so the comparison alone silently admits it. An
        # adversarial constructor test found exactly that.
        if _member(SharadarDataset, self.dataset) is None:
            raise _refuse_result() from None
        if type(self.subject) is not str or not _SUBJECT.match(self.subject):
            raise _refuse_result() from None
        _exact_count(self.page_skip)
        if _exact_count(self.page_limit) < 1:
            raise _refuse_result() from None
        if type(self.acquisition_id) is not str or not _ACQUISITION_ID.match(self.acquisition_id):
            raise _refuse_result() from None
        if type(self.content_sha256) is not str or not _DIGEST.match(self.content_sha256):
            raise _refuse_result() from None
        _exact_count(self.byte_count)
        if type(self.retrieved_at) is not datetime or self.retrieved_at.tzinfo is not UTC:
            raise _refuse_result() from None
        for flag in (self.claim_written, self.payload_written, self.acquisition_written):
            if type(flag) is not bool:
                raise _refuse_result() from None
        if _member(AcquisitionDisposition, self.disposition) is None:
            raise _refuse_result() from None
        if self.disposition is not classify_publication(
            claim_written=self.claim_written,
            payload_written=self.payload_written,
            acquisition_written=self.acquisition_written,
        ):
            # A disposition that disagrees with the three flags it summarises is
            # a record that contradicts itself.
            raise _refuse_result() from None
        if self.classification is not DataClassification.LICENSED:
            raise _refuse_result() from None
        if self.profile is not PERMITTED_PROFILE:
            raise _refuse_result() from None


@dataclass(frozen=True, slots=True, kw_only=True)
class QualificationRunResult:
    """The immutable, self-consistent record of one execution.

    ``partial`` and ``publication_state_unknown`` are **stated**, not inferred. A
    caller deriving them from arithmetic would be deriving the two most important
    facts about a failed run from counts that a bug could make agree.

    :meth:`__post_init__` re-derives every count from ``outcomes`` and refuses a
    result whose summary and detail disagree, because a summary nobody checked is
    the part of a report that goes wrong quietly.
    """

    outcome: QualificationOutcome
    failure: QualificationFailure | None
    planned_requests: int
    completed_requests: int
    acquisitions_recorded: int
    payloads_reused: int
    already_complete: int
    total_bytes: int
    outcomes: tuple[RequestOutcome, ...]
    partial: bool
    publication_state_unknown: bool

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing, so a result cannot be restated after the fact."""
        raise _refuse_result() from None

    def __post_init__(self) -> None:
        """Refuse a result that is not internally consistent."""
        if _member(QualificationOutcome, self.outcome) is None:
            raise _refuse_result() from None
        if self.failure is not None and _member(QualificationFailure, self.failure) is None:
            raise _refuse_result() from None
        if type(self.outcomes) is not tuple:
            raise _refuse_result() from None
        for outcome in self.outcomes:
            if type(outcome) is not RequestOutcome:
                raise _refuse_result() from None
        for flag in (self.partial, self.publication_state_unknown):
            if type(flag) is not bool:
                raise _refuse_result() from None
        for count in (
            self.planned_requests,
            self.completed_requests,
            self.acquisitions_recorded,
            self.payloads_reused,
            self.already_complete,
            self.total_bytes,
        ):
            _exact_count(count)

        # -- the summary must be the detail, recomputed ----------------------
        if self.completed_requests != len(self.outcomes):
            raise _refuse_result() from None
        if self.completed_requests > self.planned_requests:
            raise _refuse_result() from None
        if self.total_bytes != sum(outcome.byte_count for outcome in self.outcomes):
            raise _refuse_result() from None
        dispositions = [outcome.disposition for outcome in self.outcomes]
        if self.acquisitions_recorded != sum(
            1 for d in dispositions if d is not AcquisitionDisposition.ALREADY_COMPLETE
        ):
            raise _refuse_result() from None
        if self.payloads_reused != sum(
            1 for d in dispositions if d is AcquisitionDisposition.PAYLOAD_REUSED
        ):
            raise _refuse_result() from None
        if self.already_complete != sum(
            1 for d in dispositions if d is AcquisitionDisposition.ALREADY_COMPLETE
        ):
            raise _refuse_result() from None

        # -- the state invariants --------------------------------------------
        if self.outcome is QualificationOutcome.COMPLETED:
            # COMPLETED means every planned request has a complete acquisition
            # record. It cannot coexist with a failure, a partial flag, an unknown
            # durable state, or a short outcome list.
            if (
                self.failure is not None
                or self.partial
                or self.publication_state_unknown
                or self.completed_requests != self.planned_requests
            ):
                raise _refuse_result() from None
        elif self.outcome is QualificationOutcome.HALTED:
            if self.failure is None or not self.partial:
                raise _refuse_result() from None
        else:  # REFUSED
            if (
                self.failure is not None
                or self.partial
                or self.publication_state_unknown
                or self.outcomes
                or self.completed_requests
                or self.total_bytes
            ):
                raise _refuse_result() from None
        if self.publication_state_unknown and self.outcome is not QualificationOutcome.HALTED:
            raise _refuse_result() from None


class QualificationRuntime:
    """Executes a bounded plan against an already-constructed client and store.

    **Every dependency is a constructor parameter with no default.** A runtime
    that could build its own client is a runtime a forgetful test can point at the
    vendor, and a runtime that could build its own store is one that needs a
    bucket. Neither exists here.
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
        client's* attempt policy, the request count against the plan's ceiling,
        and that every request derives a distinct acquisition identity.

        Raises:
            QualificationPlanError: for any plan defect, including a retry budget
                the client's policy would exceed, and an identity derivation that
                does not separate two requests.
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
        identities = {
            acquisition_id(execution_id=plan.execution_id, request=request) for request in requests
        }
        if len(identities) != len(requests):
            # Unreachable while the plan refuses duplicate subjects and datasets
            # and pages ascend. Checked because the consequence of a collision --
            # two retrievals sharing one durable record -- is exactly the defect
            # this identity model exists to remove.
            raise QualificationPlanError(QualificationDefect.IDENTITY_MALFORMED) from None
        # Probe the clock here, where a fault costs nothing. A clock that cannot
        # answer is a dependency defect exactly like a store that cannot publish,
        # and discovering it after the first fetch would spend a provider request
        # to learn something checkable for free.
        self._retrieved_at()
        return requests

    # -- execution -----------------------------------------------------------

    def execute(self, plan: QualificationPlan) -> QualificationRunResult:
        """Run ``plan`` end to end, stopping at the first terminal failure.

        Requests are issued in the plan's canonical order, each under its own
        derived acquisition identity. Each response is published byte for byte
        through the Bronze bridge under ``LICENSED``; the bytes are never decoded,
        parsed or inspected, so a malformed payload is preserved as evidence
        rather than lost at the boundary.

        The return value is the record of what happened, including a run that
        stopped early. Nothing is rolled back, because immutable objects across
        several requests cannot be -- and when a *publication* fails, this method
        does not claim to know what it left behind: the result carries
        ``publication_state_unknown``.

        **Re-running a halted execution is not a resume.** A second execution
        reads a new instant, so the acquisition record under an already-occupied
        name differs and is refused. Use a new execution id and review what the
        halted one left.

        Raises:
            QualificationPlanError: if the plan is refused. **Nothing is fetched
                and nothing is stored** -- a refusal happens before the first call.
            QualificationRuntimeError: if a dependency is refused, for the same
                reason and with the same guarantee.
        """
        requests = self.validate(plan)

        outcomes: list[RequestOutcome] = []
        total_bytes = 0

        for request in requests:
            try:
                payload = self._client.fetch(request)
            except SharadarRequestError:
                # Already sanitized by construction, and deliberately not chained:
                # its own repr is safe, but a chained traceback would also print
                # every frame between here and the transport.
                return self._halted(
                    QualificationFailure.PROVIDER_REQUEST_FAILED, plan, outcomes, total_bytes
                )
            except Exception:
                # An injected client is code this module did not write. Whatever
                # it raises may carry the URL, and the URL carries the key.
                return self._halted(QualificationFailure.UNCLASSIFIED, plan, outcomes, total_bytes)

            if type(payload) is not bytes:
                # A `bytearray` would let the bytes change after they were hashed;
                # anything else was never a payload.
                return self._halted(
                    QualificationFailure.PAYLOAD_NOT_EXACT_BYTES, plan, outcomes, total_bytes
                )
            if len(payload) > plan.limits.max_response_bytes:
                return self._halted(
                    QualificationFailure.RESPONSE_TOO_LARGE, plan, outcomes, total_bytes
                )
            if total_bytes + len(payload) > plan.limits.max_run_bytes:
                # Checked before publishing, so the ceiling bounds what is stored
                # rather than what was already stored.
                return self._halted(
                    QualificationFailure.RUN_BYTE_CEILING_EXCEEDED, plan, outcomes, total_bytes
                )

            try:
                retrieved_at = self._retrieved_at()
            except QualificationRuntimeError:
                # Deliberately **not** inside the publication handler below. A
                # clock that broke mid-run is a dependency fault, and reporting it
                # as an unclassified storage failure would send a reader to look
                # at the bucket. Nothing was published for this request, so the
                # durable state is not unknown.
                return self._halted(
                    QualificationFailure.DEPENDENCY_MALFORMED, plan, outcomes, total_bytes
                )

            identity = acquisition_id(execution_id=plan.execution_id, request=request)
            try:
                published = publish_sharadar_payload(
                    store=self._store,
                    request=request,
                    payload=payload,
                    retrieved_at=retrieved_at,
                    ingestion_run_id=identity,
                    source_schema_version=plan.source_schema_version,
                    is_backfill=QUALIFICATION_IS_BACKFILL,
                )
            except ObjectAlreadyExistsError:
                # A name is held by different content. Never overwritten: this is
                # a collision, a corruption, or a second execution reusing an
                # execution id -- and none of the three is resolved by replacing
                # evidence. Publication may already have written the claim, so the
                # durable state is unknown.
                return self._halted(
                    QualificationFailure.CONTENT_CONFLICT,
                    plan,
                    outcomes,
                    total_bytes,
                    publication_state_unknown=True,
                )
            except ObjectStoreError:
                return self._halted(
                    QualificationFailure.STORAGE_REFUSED,
                    plan,
                    outcomes,
                    total_bytes,
                    publication_state_unknown=True,
                )
            except Exception:
                return self._halted(
                    QualificationFailure.UNCLASSIFIED,
                    plan,
                    outcomes,
                    total_bytes,
                    publication_state_unknown=True,
                )

            total_bytes += published.byte_count
            outcomes.append(
                RequestOutcome(
                    dataset=request.dataset,
                    subject=request.ticker,
                    page_skip=request.page.skip,
                    page_limit=request.page.limit,
                    acquisition_id=identity,
                    content_sha256=published.content_sha256,
                    byte_count=published.byte_count,
                    retrieved_at=retrieved_at,
                    claim_written=published.claim_written,
                    payload_written=published.payload_written,
                    acquisition_written=published.acquisition_written,
                    disposition=classify_publication(
                        claim_written=published.claim_written,
                        payload_written=published.payload_written,
                        acquisition_written=published.acquisition_written,
                    ),
                    classification=DataClassification.LICENSED,
                    profile=PERMITTED_PROFILE,
                )
            )

        return QualificationRunResult(
            outcome=QualificationOutcome.COMPLETED,
            failure=None,
            planned_requests=len(requests),
            completed_requests=len(outcomes),
            acquisitions_recorded=_recorded(outcomes),
            payloads_reused=_reused(outcomes),
            already_complete=_already(outcomes),
            total_bytes=total_bytes,
            outcomes=tuple(outcomes),
            partial=False,
            publication_state_unknown=False,
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
        *,
        publication_state_unknown: bool = False,
    ) -> QualificationRunResult:
        """The record of a run that stopped early.

        ``partial`` is stated, not derived. ``publication_state_unknown`` is set
        only where a publication was actually attempted and raised -- a fetch
        failure or a ceiling refusal leaves nothing in doubt, and flagging those
        would make the flag mean "something went wrong" instead of "this run
        cannot tell you what is durable".
        """
        listed = list(outcomes)
        return QualificationRunResult(
            outcome=QualificationOutcome.HALTED,
            failure=failure,
            planned_requests=plan.request_count,
            completed_requests=len(listed),
            acquisitions_recorded=_recorded(listed),
            payloads_reused=_reused(listed),
            already_complete=_already(listed),
            total_bytes=total_bytes,
            outcomes=tuple(listed),
            partial=True,
            publication_state_unknown=publication_state_unknown,
        )


def _recorded(outcomes: Sequence[RequestOutcome]) -> int:
    """How many acquisitions this run newly completed."""
    return sum(
        1
        for outcome in outcomes
        if outcome.disposition is not AcquisitionDisposition.ALREADY_COMPLETE
    )


def _reused(outcomes: Sequence[RequestOutcome]) -> int:
    """How many completed acquisitions reused an already-stored payload."""
    return sum(
        1 for outcome in outcomes if outcome.disposition is AcquisitionDisposition.PAYLOAD_REUSED
    )


def _already(outcomes: Sequence[RequestOutcome]) -> int:
    """How many acquisitions were already fully recorded before this run."""
    return sum(
        1 for outcome in outcomes if outcome.disposition is AcquisitionDisposition.ALREADY_COMPLETE
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
        acquisitions_recorded=0,
        payloads_reused=0,
        already_complete=0,
        total_bytes=0,
        outcomes=(),
        partial=False,
        publication_state_unknown=False,
    )


__all__ = [
    "QUALIFICATION_IS_BACKFILL",
    "AcquisitionDisposition",
    "QualificationClock",
    "QualificationFailure",
    "QualificationOutcome",
    "QualificationRunResult",
    "QualificationRuntime",
    "QualificationRuntimeError",
    "RequestOutcome",
    "classify_publication",
    "refused_result",
]
