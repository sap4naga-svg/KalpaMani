"""Production acquisition processing: after the barrier, one bounded run, one locator last.

**Everything before the first data-plane operation is the accepted bootstrap.**
:func:`run_production_acquisition` calls
:func:`~kalpamani.data.production.sharadar.runner.run_task_bootstrap` and proceeds
only on ``RELEASED``: binding, input, self-check, identity proof and the placement
release barrier have all passed, and zero S3, secret and provider operations have
occurred. Only then is the one credential retrieved, and only then is a provider
asked anything.

**Every dependency is injected; the executor composes and decides nothing.**
The secret comes through the accepted secrets boundary from an injected client;
provider requests go through an injected :class:`ProductionProvider`; every
durable object is written through the accepted write-only publisher over an
injected ``put_object``-only client, wrapped in the accepted deadline-admitting,
counting wrappers. No adapter here has ever been given a real client: the numbers
this module reports are what synthetic fakes were asked, and **mocked results are
not AWS verification**.

**The run identity is reserved durably before anything else is spent.** The first
conditional write of a run is a **payload-independent run reservation** at
``bronze/_production_claims/runs/<run-id>.json`` (proposed ADR-0038), issued after
the release barrier and **before** the credential is retrieved or a provider is
asked. A 412 there is a *reservation conflict*: the identity is spent, whatever
bytes a re-run would produce, and the run stops with zero provider requests and
no locator of its own. An ambiguous result stops with the uncertainty preserved.
The reservation is never deleted -- the actor cannot -- so a reserved identity
stays spent when later processing fails. This is the durable guard the
preliminary spent-identity check is not.

**Write-only, conditional, exactly accounted** (ADR-0019, ADR-0036 §2.2, ADR-0037).
Per completed request: one conditional ``PutObject`` for the claim, one for the
payload, one for the acquisition record -- claim first, so a reused identity meets
an occupied name before any bytes land; record last, so a record can never name a
payload that does not exist. Nothing is read, listed, deleted or copied; nothing is
retried; a run is never resumed.

**Dispositions are explicit, and only one kind of 412 is success.** The payload
namespace is content-addressed, so two requests returning identical bytes hit one
name: ADR-0035 §3.1 makes that an idempotent no-op on the payload, recorded as
``ALREADY_PRESENT`` in the locator for the build actor to verify by digest. The
claim and record names carry the request ordinal, so they are this request's alone
and a 412 on either is a **conflict** that halts the run -- distinct request
provenance never collapses into one object, and a reused identity never proceeds.
A definitive backend refusal halts; an ambiguous one (a 409, an unverifiable
response, an unknown code) halts **and** marks ``publication_state_unknown``.

**A COMPLETE locator is published only when every required operation has a
confirmed successful disposition and the document passes the accepted validator**
against this run's own identity, plan and slice. A halted run publishes a
``PARTIAL`` locator while the reserve allows one -- it preserves accounting and
grants no build -- and a locator that could not be published, or whose state is
unknown, or whose name was occupied, is reported as exactly that and never as
success.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Protocol

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.errors import ObjectStoreBackendError
from kalpamani.data.contracts.vocabulary import AcquisitionMode, ObjectStoreFailure
from kalpamani.data.ingest.bronze import RetrievalMetadata
from kalpamani.data.ingest.publication import (
    ACQUISITION_RECORD_FIELDS,
    CLAIM_FIELDS,
    acquisition_claim,
    acquisition_record,
    require_recordable,
)
from kalpamani.data.ingest.sharadar.client import Pacer
from kalpamani.data.ingest.sharadar.credentials import SharadarCredential
from kalpamani.data.ingest.sharadar.datasets import PROVIDER
from kalpamani.data.ingest.sharadar.secrets import SecretsClient, sharadar_credential_from_secret
from kalpamani.data.production.sharadar.identities import SpentIdentityRegistry
from kalpamani.data.production.sharadar.inputs import AcquisitionInput, LedgerRow
from kalpamani.data.production.sharadar.keys import (
    production_acquisition_key,
    production_claim_key,
    production_payload_key,
    run_locator_key,
    run_reservation_key,
)
from kalpamani.data.production.sharadar.locator import (
    LOCATOR_SCHEMA_VERSION,
    MAX_LOCATOR_BYTES,
    Completeness,
    PayloadDisposition,
    RunLocatorError,
    validate_run_locator,
)
from kalpamani.data.production.sharadar.metadata import CompiledTask
from kalpamani.data.production.sharadar.outcomes import OperationCounts, RunnerOutcome
from kalpamani.data.production.sharadar.plan import CompiledPlan, ProductionRequest
from kalpamani.data.production.sharadar.provider import transport_invocations_of
from kalpamani.data.production.sharadar.runner import (
    RunnerAdapters,
    RunnerReport,
    run_task_bootstrap,
)
from kalpamani.data.production.sharadar.vocabulary import ProductionActor
from kalpamani.data.qualify.sharadar.acquisition import DeadlinePacedSleeper
from kalpamani.data.qualify.sharadar.operations import (
    AcquisitionDeadline,
    CountingS3Client,
    DeadlineExhaustedError,
    LocatorPublication,
    LocatorPublicationStatus,
    publish_locator,
)
from kalpamani.data.qualify.sharadar.publication import (
    LicensedWriteOnlyPublisher,
    NameOccupiedError,
)

#: The schema version every production acquisition record carries. A constant of
#: the plan, not of a payload: the acquisition path parses nothing.
SOURCE_SCHEMA_VERSION: Final = "sharadar-csv-production-v1"

#: The run reservation contract. Closed fields; no free text.
RESERVATION_CONTRACT_ID: Final = "kalpamani-production-run-reservation/v1"
RESERVATION_SCHEMA_VERSION: Final = 1

#: The backend categories under which a conditional write's outcome is
#: **definitively not done**. Everything else the backend can answer leaves the
#: durable state unknown (a 409 never resolved the condition; an unverifiable
#: response proved nothing; an unknown code says nothing).
_DEFINITIVE_REFUSALS: Final[frozenset[ObjectStoreFailure]] = frozenset(
    {
        ObjectStoreFailure.ACCESS_DENIED,
        ObjectStoreFailure.NOT_FOUND,
        ObjectStoreFailure.INVALID_CONFIGURATION,
    }
)


class ProductionProvider(Protocol):
    """One provider operation: the bytes one request coordinate returns.

    Injected. The accepted transport cannot serve this shape today (see
    :mod:`~kalpamani.data.production.sharadar.plan`), so the only implementations
    that exist are synthetic. The credential is handed in and revealed **only**
    inside the adapter; nothing here reads it.
    """

    def fetch(self, request: ProductionRequest, *, credential: SharadarCredential) -> bytes:
        """The response body, or raise."""
        ...


class ProcessingHalt(StrEnum):
    """Why an acquisition run stopped before every request completed. Closed."""

    RESERVATION_CONFLICT = "RESERVATION_CONFLICT"
    RESERVATION_REFUSED = "RESERVATION_REFUSED"
    RESERVATION_STATE_UNKNOWN = "RESERVATION_STATE_UNKNOWN"
    CREDENTIAL_REFUSED = "CREDENTIAL_REFUSED"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    RUN_BYTES_EXCEEDED = "RUN_BYTES_EXCEEDED"
    DEADLINE_EXHAUSTED = "DEADLINE_EXHAUSTED"
    PUBLICATION_CONFLICT = "PUBLICATION_CONFLICT"
    PUBLICATION_REFUSED = "PUBLICATION_REFUSED"
    PUBLICATION_STATE_UNKNOWN = "PUBLICATION_STATE_UNKNOWN"


class AcquisitionStatus(StrEnum):
    """The one verdict of a production acquisition run. Closed, never a data verdict.

    ``COMPLETED`` requires **all** of: every planned request completed with
    confirmed dispositions, no unknown publication state, a COMPLETE locator that
    passed the accepted validator, and that locator ``PUBLISHED``. Everything else
    names what stopped short.
    """

    COMPLETED = "COMPLETED"
    REFUSED_BOOTSTRAP = "REFUSED_BOOTSTRAP"
    REFUSED_RESERVATION = "REFUSED_RESERVATION"
    REFUSED_CREDENTIAL = "REFUSED_CREDENTIAL"
    HALTED = "HALTED"
    LOCATOR_NOT_PUBLISHED = "LOCATOR_NOT_PUBLISHED"
    LOCATOR_STATE_UNKNOWN = "LOCATOR_STATE_UNKNOWN"
    LOCATOR_NAME_OCCUPIED = "LOCATOR_NAME_OCCUPIED"


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessingAdapters:
    """Everything processing touches after the barrier, injected. Nothing is built here."""

    secrets: SecretsClient
    secret_id: str
    provider: ProductionProvider
    s3: Any
    monotonic: Callable[[], float]
    sleeper: Callable[[float], None]
    clock: Callable[[], datetime]


class _CountingProvider:
    """Admit against the deadline, count the request, forward it. Nothing else."""

    __slots__ = ("_deadline", "_provider", "request_count")

    def __init__(self, provider: ProductionProvider, *, deadline: AcquisitionDeadline) -> None:
        if not callable(getattr(provider, "fetch", None)):
            raise TypeError("a provider must provide a callable fetch")
        self._provider = provider
        self._deadline = deadline
        self.request_count = 0

    def fetch(self, request: ProductionRequest, *, credential: SharadarCredential) -> bytes:
        self._deadline.admit_provider_request()
        reported = transport_invocations_of(self._provider)
        if reported is None:
            # A provider that does not report its transport invocations is counted
            # by the call, as the synthetic fakes always were.
            self.request_count += 1
            return self._provider.fetch(request, credential=credential)
        # A provider that reports actual transport invocations is counted by them:
        # a request it refuses before the transport is not a provider request.
        try:
            return self._provider.fetch(request, credential=credential)
        finally:
            after = transport_invocations_of(self._provider)
            self.request_count += (after if after is not None else reported) - reported


@dataclass(frozen=True, slots=True, kw_only=True)
class CompletedRequest:
    """One request whose three writes each have a confirmed disposition."""

    request: ProductionRequest
    payload_sha256: str
    payload_bytes: int
    payload_disposition: PayloadDisposition
    payload_key: str
    record_sha256: str
    record_bytes: int
    record_key: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionReport:
    """The sanitized result of one production acquisition run.

    Counts are observed from the wrappers and the bootstrap, never planned. No
    identity, key, digest, bucket, credential or vendor row is carried by any
    field a report renders.
    """

    status: AcquisitionStatus
    bootstrap: RunnerReport
    halt: ProcessingHalt | None
    reservation: PayloadDisposition | None
    completed_requests: int
    planned_requests: int
    payloads_written: int
    payloads_already_present: int
    publication_state_unknown: bool
    locator: LocatorPublication | None
    counts: OperationCounts

    def __post_init__(self) -> None:
        """A report must describe one possible run."""
        if type(self.status) is not AcquisitionStatus:
            raise TypeError("status must be an exact AcquisitionStatus member")
        if self.halt is not None and type(self.halt) is not ProcessingHalt:
            raise TypeError("halt must be an exact ProcessingHalt member or None")
        if self.completed_requests > self.planned_requests:
            raise ValueError("completed requests cannot exceed planned requests")
        if self.reservation is not None and self.reservation is not PayloadDisposition.WRITTEN:
            raise ValueError("a reservation is either written by this run or absent")
        if self.reservation is None and (self.completed_requests or self.locator is not None):
            raise ValueError("nothing is acquired or published without a reservation")
        if self.locator is not None and (
            self.locator.status is LocatorPublicationStatus.STATE_UNKNOWN
            and not self.publication_state_unknown
        ):
            raise ValueError("an uncertain locator publication is uncertain publication state")
        if self.payloads_written + self.payloads_already_present != self.completed_requests:
            raise ValueError("every completed request has exactly one payload disposition")
        completed = self.status is AcquisitionStatus.COMPLETED
        if completed and (
            self.halt is not None
            or self.completed_requests != self.planned_requests
            or self.publication_state_unknown
            or self.locator is None
            or self.locator.status is not LocatorPublicationStatus.PUBLISHED
        ):
            raise ValueError(
                "COMPLETED requires every request, a known state and a published locator"
            )

    def __repr__(self) -> str:
        """Status and counts only."""
        return (
            f"AcquisitionReport(status={self.status.value!r}, "
            f"completed={self.completed_requests}/{self.planned_requests})"
        )


class _HaltError(Exception):
    """Internal: the run stops here with this halt. Never escapes the module."""

    def __init__(self, halt: ProcessingHalt, *, state_unknown: bool = False) -> None:
        super().__init__(halt.value)
        self.halt = halt
        self.state_unknown = state_unknown


def _retrieval(
    request: ProductionRequest, *, run_id: str, mode: AcquisitionMode, retrieved_at: datetime
) -> RetrievalMetadata:
    return RetrievalMetadata(
        provider=PROVIDER,
        dataset=request.dataset,
        requested_range=request.window,
        retrieved_at=retrieved_at,
        source_schema_version=SOURCE_SCHEMA_VERSION,
        ingestion_run_id=run_id,
        acquisition_mode=mode,
    )


def _conditional_write(
    publisher: LicensedWriteOnlyPublisher, *, key: Any, payload: bytes, content_addressed: bool
) -> PayloadDisposition:
    """One conditional write, reduced to a disposition or a halt.

    A 412 on a content-addressed name is ``ALREADY_PRESENT``; on any other name it
    is a conflict. A definitive backend refusal halts with the state known; an
    ambiguous one halts with the state unknown. **No retry, no read, no adoption.**
    """
    try:
        publisher.put_if_absent(key=key, payload=payload)
    except NameOccupiedError:
        if content_addressed:
            return PayloadDisposition.ALREADY_PRESENT
        raise _HaltError(ProcessingHalt.PUBLICATION_CONFLICT) from None
    except ObjectStoreBackendError as error:
        if error.failure in _DEFINITIVE_REFUSALS:
            raise _HaltError(ProcessingHalt.PUBLICATION_REFUSED) from None
        raise _HaltError(ProcessingHalt.PUBLICATION_STATE_UNKNOWN, state_unknown=True) from None
    except DeadlineExhaustedError:
        raise _HaltError(ProcessingHalt.DEADLINE_EXHAUSTED) from None
    return PayloadDisposition.WRITTEN


def _publish_request(
    *,
    publisher: LicensedWriteOnlyPublisher,
    request: ProductionRequest,
    payload: bytes,
    run_id: str,
    mode: AcquisitionMode,
    retrieved_at: datetime,
) -> CompletedRequest:
    """Claim, payload, record -- three conditional writes, in that order."""
    digest = sha256_hex(payload)
    retrieval = _retrieval(request, run_id=run_id, mode=mode, retrieved_at=retrieved_at)
    claim = acquisition_claim(retrieval=retrieval, content_sha256=digest)
    require_recordable(claim, allowed=CLAIM_FIELDS)
    claim_bytes = canonical_bytes(claim)
    record = acquisition_record(retrieval=retrieval, content_sha256=digest, byte_count=len(payload))
    require_recordable(record, allowed=ACQUISITION_RECORD_FIELDS)
    record_bytes = canonical_bytes(record)

    claim_key = production_claim_key(
        payload_digest=digest, run_id=run_id, ordinal=request.ordinal, claim=claim_bytes
    )
    payload_key = production_payload_key(dataset=request.dataset, payload=payload)
    record_key = production_acquisition_key(
        dataset=request.dataset,
        payload_digest=digest,
        run_id=run_id,
        ordinal=request.ordinal,
        record=record_bytes,
    )
    _conditional_write(publisher, key=claim_key, payload=claim_bytes, content_addressed=False)
    disposition = _conditional_write(
        publisher, key=payload_key, payload=payload, content_addressed=True
    )
    _conditional_write(publisher, key=record_key, payload=record_bytes, content_addressed=False)
    return CompletedRequest(
        request=request,
        payload_sha256=digest,
        payload_bytes=len(payload),
        payload_disposition=disposition,
        payload_key=payload_key.logical_key,
        record_sha256=record_key.content_sha256,
        record_bytes=len(record_bytes),
        record_key=record_key.logical_key,
    )


def build_run_locator_document(
    *,
    plan: CompiledPlan,
    admitted: AcquisitionInput,
    completed: tuple[CompletedRequest, ...],
    started_at: datetime,
    completed_at: datetime,
    publication_state_unknown: bool,
) -> dict[str, Any]:
    """The closed run-locator document for this run, COMPLETE or PARTIAL as the facts are."""
    complete = len(completed) == plan.request_count and not publication_state_unknown
    return {
        "schema_version": LOCATOR_SCHEMA_VERSION,
        "run_id": admitted.run_identity,
        "plan_digest": plan.digest,
        "slice": admitted.slice.canonical(),
        "acquisition_mode": plan.acquisition_mode.value,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "completeness": (Completeness.COMPLETE if complete else Completeness.PARTIAL).value,
        "publication_state_unknown": publication_state_unknown,
        "planned_requests": plan.request_count,
        "completed_requests": len(completed),
        "entries": [
            {
                "ordinal": item.request.ordinal,
                "dataset": item.request.dataset,
                "payload_key": item.payload_key,
                "payload_sha256": item.payload_sha256,
                "payload_bytes": item.payload_bytes,
                "payload_disposition": item.payload_disposition.value,
                "record_key": item.record_key,
                "record_sha256": item.record_sha256,
                "record_bytes": item.record_bytes,
                "request": {
                    "window": item.request.window,
                    "page_offset": item.request.page_offset,
                    "page_limit": item.request.page_limit,
                },
            }
            for item in completed
        ],
    }


def _self_validate_complete(
    document: dict[str, Any],
    *,
    admitted: AcquisitionInput,
    plan: CompiledPlan,
    started_at: datetime,
    completed_at: datetime,
) -> None:
    """A COMPLETE locator must pass the accepted validator before it is published."""
    row = LedgerRow(
        run_identity=admitted.run_identity,
        slice=admitted.slice,
        plan_digest=plan.digest,
        outcome="COMPLETED",
        launched_at=started_at,
        completed_at=completed_at,
    )
    validate_run_locator(document, run_id=admitted.run_identity, ledger_row=row)


def run_production_acquisition(
    *,
    compiled: CompiledTask,
    bootstrap: RunnerAdapters,
    registry: SpentIdentityRegistry,
    processing: ProcessingAdapters,
) -> AcquisitionReport:
    """Bootstrap, barrier, then one bounded acquisition and one locator last.

    Returns a report on every path; nothing is raised out of here once the
    bootstrap has passed, because a halted run's accounting is the point.
    """
    if type(processing) is not ProcessingAdapters:
        raise TypeError("processing must be an exact ProcessingAdapters")
    report = run_task_bootstrap(
        actor=ProductionActor.ACQUISITION, compiled=compiled, adapters=bootstrap, registry=registry
    )
    zero = OperationCounts()
    if report.outcome is not RunnerOutcome.RELEASED:
        return AcquisitionReport(
            status=AcquisitionStatus.REFUSED_BOOTSTRAP,
            bootstrap=report,
            halt=None,
            reservation=None,
            completed_requests=0,
            planned_requests=0,
            payloads_written=0,
            payloads_already_present=0,
            publication_state_unknown=False,
            locator=None,
            counts=report.counts,
        )
    assert report.binding is not None and report.plan is not None
    assert type(report.admitted_input) is AcquisitionInput
    binding, admitted, plan = report.binding, report.admitted_input, report.plan

    def counts(
        *, secrets: int, provider: int, s3: int, extra: OperationCounts = zero
    ) -> OperationCounts:
        base = report.counts
        return OperationCounts(
            parameter_reads=base.parameter_reads,
            parameter_creates=base.parameter_creates,
            parameter_deletes=base.parameter_deletes,
            run_task=base.run_task,
            describe_tasks=base.describe_tasks,
            describe_network_interfaces=base.describe_network_interfaces,
            stop_task=base.stop_task,
            identity_calls=base.identity_calls,
            s3_operations=s3,
            secret_retrievals=secrets,
            provider_requests=provider,
        )

    # The deadline, the counting wrappers and the write-only publisher.
    deadline = AcquisitionDeadline(
        monotonic=processing.monotonic, deadline_seconds=plan.deadline_seconds
    )
    counting_s3 = CountingS3Client(processing.s3, deadline=deadline)
    provider = _CountingProvider(processing.provider, deadline=deadline)
    publisher = LicensedWriteOnlyPublisher(
        client=counting_s3, licensed_bucket=binding.licensed_bucket_name
    )
    pacer = Pacer(
        min_interval=plan.min_request_interval_seconds,
        clock=processing.monotonic,
        sleeper=DeadlinePacedSleeper(deadline=deadline, sleeper=processing.sleeper),
    )
    started_at = processing.clock()
    # Armed here rather than immediately before the first provider request: the
    # reservation is an S3 operation of this run and is admitted and counted like
    # every other. Arming earlier is conservative -- it can only halt sooner.
    deadline.arm()

    # Step 7a: the durable run reservation -- the first write, before the credential.
    reservation_document = {
        "schema_version": RESERVATION_SCHEMA_VERSION,
        "contract_id": RESERVATION_CONTRACT_ID,
        "run_id": admitted.run_identity,
        "plan_digest": plan.digest,
        "acquisition_mode": plan.acquisition_mode.value,
        "reserved_at": started_at.isoformat(),
    }
    reservation_bytes = canonical_bytes(reservation_document)
    try:
        _conditional_write(
            publisher,
            key=run_reservation_key(run_id=admitted.run_identity, payload=reservation_bytes),
            payload=reservation_bytes,
            content_addressed=False,
        )
    except _HaltError as stopped:
        halt_by_kind = {
            ProcessingHalt.PUBLICATION_CONFLICT: ProcessingHalt.RESERVATION_CONFLICT,
            ProcessingHalt.PUBLICATION_REFUSED: ProcessingHalt.RESERVATION_REFUSED,
            ProcessingHalt.PUBLICATION_STATE_UNKNOWN: ProcessingHalt.RESERVATION_STATE_UNKNOWN,
            ProcessingHalt.DEADLINE_EXHAUSTED: ProcessingHalt.DEADLINE_EXHAUSTED,
        }
        # A losing or uncertain reservation acquires nothing and publishes nothing
        # -- no locator under an identity that may be another run's.
        return AcquisitionReport(
            status=AcquisitionStatus.REFUSED_RESERVATION,
            bootstrap=report,
            halt=halt_by_kind[stopped.halt],
            reservation=None,
            completed_requests=0,
            planned_requests=plan.request_count,
            payloads_written=0,
            payloads_already_present=0,
            publication_state_unknown=stopped.state_unknown,
            locator=None,
            counts=counts(secrets=0, provider=0, s3=counting_s3.put_object_count),
        )

    # Step 7b: the one credential, through the accepted secrets boundary.
    try:
        credential = sharadar_credential_from_secret(
            client=processing.secrets, secret_id=processing.secret_id
        )
    except Exception:
        return AcquisitionReport(
            status=AcquisitionStatus.REFUSED_CREDENTIAL,
            bootstrap=report,
            halt=ProcessingHalt.CREDENTIAL_REFUSED,
            reservation=PayloadDisposition.WRITTEN,
            completed_requests=0,
            planned_requests=plan.request_count,
            payloads_written=0,
            payloads_already_present=0,
            publication_state_unknown=False,
            locator=None,
            counts=counts(secrets=1, provider=0, s3=counting_s3.put_object_count),
        )

    completed: list[CompletedRequest] = []
    halt: ProcessingHalt | None = None
    state_unknown = False
    run_bytes = 0
    try:
        for request in plan.requests:
            try:
                pacer.wait()
                payload = provider.fetch(request, credential=credential)
            except DeadlineExhaustedError:
                raise _HaltError(ProcessingHalt.DEADLINE_EXHAUSTED) from None
            except Exception:
                raise _HaltError(ProcessingHalt.PROVIDER_FAILURE) from None
            if type(payload) is not bytes:
                raise _HaltError(ProcessingHalt.PROVIDER_FAILURE)
            if len(payload) > plan.max_response_bytes:
                raise _HaltError(ProcessingHalt.RESPONSE_TOO_LARGE)
            run_bytes += len(payload)
            if run_bytes > plan.max_run_bytes:
                raise _HaltError(ProcessingHalt.RUN_BYTES_EXCEEDED)
            completed.append(
                _publish_request(
                    publisher=publisher,
                    request=request,
                    payload=payload,
                    run_id=admitted.run_identity,
                    mode=plan.acquisition_mode,
                    retrieved_at=processing.clock(),
                )
            )
    except _HaltError as stopped:
        halt = stopped.halt
        state_unknown = stopped.state_unknown
        if deadline.exhausted:
            # The deadline refused an admission. The accepted publisher wraps the
            # refusal as an unclassified backend failure, but nothing was sent: the
            # halt is the deadline's, and the durable state is known.
            halt = ProcessingHalt.DEADLINE_EXHAUSTED
            state_unknown = False
    completed_at = processing.clock()
    entries = tuple(completed)

    # The locator, last. COMPLETE only when everything confirmed and the accepted
    # validator admits the document; PARTIAL otherwise; never rebuilt per attempt.
    deadline.begin_locator_phase()
    document = build_run_locator_document(
        plan=plan,
        admitted=admitted,
        completed=entries,
        started_at=started_at,
        completed_at=completed_at,
        publication_state_unknown=state_unknown,
    )
    if document["completeness"] == Completeness.COMPLETE.value:
        try:
            _self_validate_complete(
                document,
                admitted=admitted,
                plan=plan,
                started_at=started_at,
                completed_at=completed_at,
            )
        except RunLocatorError:
            # The document this run would publish as COMPLETE fails the validator the
            # build actor will apply. It is published as PARTIAL instead, so the
            # accounting survives and no build proceeds on it.
            document["completeness"] = Completeness.PARTIAL.value
    payload_bytes = canonical_bytes(document)
    if len(payload_bytes) > MAX_LOCATOR_BYTES or not deadline.permits_locator_construction():
        publication = LocatorPublication(status=LocatorPublicationStatus.NOT_PUBLISHED, attempts=0)
    else:
        publication = publish_locator(
            store=publisher,
            key=run_locator_key(run_id=admitted.run_identity, payload=payload_bytes),
            payload=payload_bytes,
            deadline=deadline,
        )

    if halt is not None:
        status = AcquisitionStatus.HALTED
    elif document["completeness"] != Completeness.COMPLETE.value:
        status = AcquisitionStatus.HALTED
        halt = ProcessingHalt.PUBLICATION_STATE_UNKNOWN
    elif publication.status is LocatorPublicationStatus.PUBLISHED:
        status = AcquisitionStatus.COMPLETED
    elif publication.status is LocatorPublicationStatus.NAME_OCCUPIED:
        status = AcquisitionStatus.LOCATOR_NAME_OCCUPIED
    elif publication.status is LocatorPublicationStatus.STATE_UNKNOWN:
        status = AcquisitionStatus.LOCATOR_STATE_UNKNOWN
    else:
        status = AcquisitionStatus.LOCATOR_NOT_PUBLISHED

    # Uncertainty is never cleared by a later success and never hidden behind an
    # earlier halt: an ambiguous locator publication is uncertain publication state
    # in the final report whatever determined the overall status.
    locator_uncertain = publication.status is LocatorPublicationStatus.STATE_UNKNOWN
    return AcquisitionReport(
        status=status,
        bootstrap=report,
        halt=halt,
        reservation=PayloadDisposition.WRITTEN,
        completed_requests=len(entries),
        planned_requests=plan.request_count,
        payloads_written=sum(
            1 for item in entries if item.payload_disposition is PayloadDisposition.WRITTEN
        ),
        payloads_already_present=sum(
            1 for item in entries if item.payload_disposition is PayloadDisposition.ALREADY_PRESENT
        ),
        publication_state_unknown=(
            state_unknown or document["publication_state_unknown"] or locator_uncertain
        ),
        locator=publication,
        counts=counts(secrets=1, provider=provider.request_count, s3=counting_s3.put_object_count),
    )


__all__ = [
    "RESERVATION_CONTRACT_ID",
    "RESERVATION_SCHEMA_VERSION",
    "SOURCE_SCHEMA_VERSION",
    "AcquisitionReport",
    "AcquisitionStatus",
    "CompletedRequest",
    "ProcessingAdapters",
    "ProcessingHalt",
    "ProductionProvider",
    "build_run_locator_document",
    "run_production_acquisition",
]
