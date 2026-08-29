"""The dormant Sharadar qualification composition, and offline preflight.

ADR-0014. Until this module, five accepted slices sat beside one another with
nothing joining them: the credential, the transport, the client, the licensed S3
object store and the qualification runtime each existed, each took its
dependencies by injection, and **nothing anywhere constructed the set**. That
absence was the control. It was also a gap in review: the wiring nobody had
written was the wiring nobody had checked.

This module writes it, and stops one step short of using it.

One function, no object
======================

:func:`preflight_qualification_composition` takes every dependency and a plan,
builds the three accepted components as **local variables**, calls
:meth:`~kalpamani.data.ingest.sharadar.runtime.QualificationRuntime.validate`,
and returns a :class:`QualificationPreflight`.

**What that guarantees, stated exactly.** The client, the store and the runtime
are not returned, and are not retained in module state, in an instance, in a
closure or on the result. The **caller keeps ownership of everything it passed
in** -- its credential, transport, S3 client, bucket string, clock and plan are
its own objects, and this function neither takes them over nor makes them go
away. What it does guarantee is that *this function and the object it returns*
hold none of them after a successful return.

This is a statement about what the code retains, not about object lifetimes.
Nothing here claims anything is collected, and on an exception path a traceback
may hold a frame alive for as long as the caller keeps the exception.

**The first revision of this slice got that wrong.** It was a class holding
``_client``, ``_store`` and ``_runtime``, and it claimed that no attribute
exposed the runtime. That was false. ``composition._runtime.execute(plan)``
worked, and its own tests reached those attributes to prove the components had
been built. **A leading underscore is a naming convention, not an execution
barrier**, and a dormancy claim resting on one is not a claim at all.

A function fixes it structurally rather than by policy. There is no ``self`` to
attach a runtime to, no instance for a caller to hold, and no attribute to
reach -- so "no executable component escapes" stops being a rule someone must
remember and becomes a property of the shape.

::

    composition           ONE function, and no stateful object
    exposed operation     offline preflight -- plan validation, and only that
    qualification-run execution surface     NONE
    provider-fetch operation                NONE
    object-publication operation            NONE
    runner                NONE     no CLI, no module entry point, no task
    retained state        NONE     no module global, no closure, no instance
    caller-owned arguments                  the caller's, before and after
    credential retrieval  NONE     no environment read, no file read, no reveal()
    real credential binding: NONE  ·  real bucket binding: NONE
    AWS SDK session or S3-client construction: NONE
    provider requests     ZERO     ·  AWS requests: ZERO

What this is not
================

**It is not authorization to run.** The first authenticated qualification run is
separately gated and remains unauthorized. Nothing outside this module's own
synthetic tests calls this function, and a static guard keeps it that way.

**It selects no provider.** G1 and G2 stay open; naming an implementation target
has never been selection, and joining five slices does not become it.

**Preflight is not a verdict.** It says a plan is internally consistent against
an injected client's own policy -- nothing about the provider, the data, or
whether a run should happen. The status word is ``VALIDATED_OFFLINE`` and
deliberately not "ready", "approved", "proceed" or "qualified": a caller reading
this result must not be able to mistake arithmetic for permission.

Why the credential is a parameter
=================================

:func:`~kalpamani.data.ingest.sharadar.credentials.credential_from_env` exists
and takes an explicit mapping, so a future authorized runner can pass
``os.environ`` at the one place allowed to. **This module is not that place.** It
never calls that function, never touches a process environment, and never calls
:meth:`~kalpamani.data.ingest.sharadar.credentials.SharadarCredential.reveal`.
The credential arrives already built and is handed to a client that lives for the
duration of one call. **It stays the caller's object**; what this module
guarantees is that neither the function nor the result it returns retains it.

Nothing at import time does work, and nothing here opens a socket, reads a file,
parses an argument or names a host, a bucket, an account or an endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from kalpamani.data.contracts.vocabulary import (
    AcquisitionMode,
    InformationSetProfile,
)
from kalpamani.data.ingest.sharadar.client import (
    MAX_ATTEMPTS_CEILING,
    Pacer,
    RetryPolicy,
    SharadarClient,
)
from kalpamani.data.ingest.sharadar.credentials import SharadarCredential
from kalpamani.data.ingest.sharadar.qualification import (
    MAX_REQUESTS,
    MAX_RESPONSE_BYTES,
    MAX_RETRY_BUDGET,
    MAX_RUN_BYTES,
    PERMITTED_PROFILE,
    QUALIFICATION_ACQUISITION_MODE,
    QualificationPlan,
)
from kalpamani.data.ingest.sharadar.redaction import (
    SharadarErrorCode,
    SharadarRequestError,
    SharadarStage,
)
from kalpamani.data.ingest.sharadar.runtime import (
    QualificationClock,
    QualificationRuntime,
)
from kalpamani.data.ingest.sharadar.transport import SharadarTransport
from kalpamani.data.storage.s3 import S3Client, S3ResearchObjectStore


class PreflightStatus(StrEnum):
    """What an offline preflight can conclude. Exactly one member, on purpose.

    A second member would be a *failure* status -- and a failure that can be
    returned is a failure a caller can ignore. Every refusal here raises instead,
    carrying one of the existing closed vocabularies, so the only object this
    module can hand back is one describing a plan that passed.

    The word is chosen to be unusable as permission. ``VALIDATED_OFFLINE`` says
    what happened: a plan was checked, offline, against an injected client's own
    policy. ``READY``, ``PROCEED``, ``APPROVED`` and ``QUALIFIED`` would each be
    read by someone as an answer to a question this module cannot ask.
    """

    VALIDATED_OFFLINE = "VALIDATED_OFFLINE"


def _refuse() -> SharadarRequestError:
    """The one refusal this module raises itself, in the provider's vocabulary.

    ``BUILD``/``REQUEST_MALFORMED`` is what every other constructor in this
    package raises for a dependency it will not accept, and reusing it keeps a
    caller from having to learn a fourth failure type to handle the same
    situation. It carries a stage and a code and nothing else -- no parameter
    name, no value, no repr of the object that was refused.
    """
    return SharadarRequestError(stage=SharadarStage.BUILD, code=SharadarErrorCode.REQUEST_MALFORMED)


def _exact_count(value: object, *, low: int, high: int) -> None:
    """Refuse ``value`` unless it is an exact ``int`` within ``[low, high]``.

    Exact, because ``True`` is an ``int`` in Python and a count of ``True`` is a
    count of one that nobody wrote. Bounded, because a preflight reporting a
    number outside the compiled ceilings would describe a run this system cannot
    perform.
    """
    if type(value) is not int or not low <= value <= high:
        raise _refuse() from None


@dataclass(frozen=True, slots=True, kw_only=True)
class QualificationPreflight:
    """What an offline preflight establishes. Safe to log in full.

    Every field is a closed vocabulary member or a bounded count. **There is no
    credential field, no bucket field, no URL field, no subject field, no payload
    field and no message field**, so none of those has anywhere to be -- and
    :meth:`__post_init__` enforces that at runtime rather than leaving it to
    annotations, which are a static claim.

    **The result must describe a plan that could actually have passed.** An
    earlier revision accepted zero for every count while still reporting
    ``VALIDATED_OFFLINE``, so an independently constructed result could claim
    that a run of no requests, no attempts and no bytes had been validated. No
    plan produces those numbers: a plan has at least one request, a client makes
    at least one attempt, and a ceiling of zero bytes admits no response.

    The bounds are read from the **same compiled constants** the plan and the
    client are held to, so there is no second set of numbers to drift, and the
    two cross-field rules are the ones the runtime itself applies.
    """

    status: PreflightStatus
    request_count: int
    max_attempts: int
    max_response_bytes: int
    max_run_bytes: int
    retry_budget: int
    acquisition_mode: AcquisitionMode
    profile: InformationSetProfile

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing.

        A subclass could add a field, override ``__repr__`` and put a bucket name
        or a credential into a log line through an object that still passes every
        ``isinstance`` check. The result of a safety-critical check is not a base
        class.
        """
        raise TypeError("QualificationPreflight may not be subclassed.")

    def __post_init__(self) -> None:
        """Refuse anything that could not describe a validated plan.

        Raises:
            SharadarRequestError: ``BUILD: REQUEST_MALFORMED``, sanitized and
                raised ``from None``. A bare ``"QUALIFICATION"`` string is refused
                where the member belongs, because two spellings of one value in a
                logged record is how the second one becomes authoritative.
        """
        if type(self.status) is not PreflightStatus:
            raise _refuse() from None
        if type(self.acquisition_mode) is not AcquisitionMode:
            raise _refuse() from None
        if type(self.profile) is not InformationSetProfile:
            raise _refuse() from None
        if self.acquisition_mode is not QUALIFICATION_ACQUISITION_MODE:
            raise _refuse() from None
        if self.profile is not PERMITTED_PROFILE:
            raise _refuse() from None

        _exact_count(self.request_count, low=1, high=MAX_REQUESTS)
        _exact_count(self.max_attempts, low=1, high=MAX_ATTEMPTS_CEILING)
        _exact_count(self.max_response_bytes, low=1, high=MAX_RESPONSE_BYTES)
        _exact_count(self.max_run_bytes, low=1, high=MAX_RUN_BYTES)
        # A retry budget of zero is legitimate -- `max_attempts=1` means no retry
        # is ever taken -- so this floor is 0 where the others are 1.
        _exact_count(self.retry_budget, low=0, high=MAX_RETRY_BUDGET)

        if self.max_response_bytes > self.max_run_bytes:
            # One answer could exhaust the whole run, so the run could never send
            # even its first request within the ceiling it reports.
            raise _refuse() from None
        if self.request_count * (self.max_attempts - 1) > self.retry_budget:
            # The arithmetic `refuse_retry_budget` applies to the plan. A result
            # whose own numbers fail it describes a validation that could not
            # have succeeded.
            raise _refuse() from None


def preflight_qualification_composition(
    *,
    credential: SharadarCredential,
    transport: SharadarTransport,
    pacer: Pacer,
    retry_policy: RetryPolicy,
    timeout_seconds: float,
    s3_client: S3Client,
    licensed_bucket: str,
    clock: QualificationClock,
    plan: QualificationPlan,
) -> QualificationPreflight:
    """Construct the accepted components, validate ``plan`` against them, return facts.

    **Nothing constructed here is handed back or kept.** The client, the store and
    the runtime are local variables: they are not returned, and not retained in
    module state, in an instance, in a closure or on the result. The returned
    :class:`QualificationPreflight` holds counts and closed vocabulary members
    and no dependency at all.

    **The caller keeps what the caller passed in.** Its credential, transport, S3
    client, bucket string, clock and plan remain its own objects; this function
    neither takes them over nor disposes of them. The guarantee is about what
    *this* function and *its* result retain, and it is about retention rather
    than object lifetime -- nothing here claims anything is collected.

    **Offline preflight is the one exposed operation.** It validates; that is
    work, and calling it "no way to run anything" would be false. What does not
    exist is a *qualification-run* execution surface: no provider fetch, no
    object publication, and nothing that returns a component through which one
    could be reached.

    **Every dependency is a required keyword parameter with no default**, so
    nothing here can reach a real service because a caller forgot one.

    Validation is **delegated**, not duplicated: the credential's exactness, the
    transport's callable ``get``, the timeout range, the retry policy's shape,
    the bucket name's grammar, the S3 client's two operations and the clock's one
    method are each already enforced by the constructor that owns them, and each
    refusal is already sanitized. Re-checking them here would create a second,
    drifting copy of every rule.

    ``pacer`` is the exception, and is required and exactly typed here.
    :class:`~kalpamani.data.ingest.sharadar.client.SharadarClient` accepts
    ``None`` and builds its own from :func:`time.monotonic` and
    :func:`time.sleep` -- a sensible default for a client, and the wrong one
    here: a composition that silently acquired an ambient clock would have
    exactly the kind of unexamined dependency this function exists to make
    visible.

    :meth:`~kalpamani.data.ingest.sharadar.runtime.QualificationRuntime.validate`
    is the only thing called on the runtime. It builds the plan's requests,
    checks the retry budget against the *injected client's* attempt policy,
    checks the request count against the plan's ceiling, checks that every
    request derives a distinct acquisition identity, checks both byte ceilings
    against what the client could actually return, and probes the clock. **It
    issues no provider request and no store call**, which is why this function is
    inert even when handed real dependencies.

    Raises:
        SharadarRequestError: ``BUILD: REQUEST_MALFORMED`` for a pacer that is not
            an exact :class:`~kalpamani.data.ingest.sharadar.client.Pacer`, and
            from the client's own constructor for a bad credential, transport,
            timeout or retry policy.
        ObjectStoreBackendError: ``BIND: INVALID_CONFIGURATION`` for a bucket name
            or S3 client the store will not accept. **The refusal never echoes
            the bucket.**
        QualificationRuntimeError: ``DEPENDENCY_MALFORMED`` for a clock that
            cannot answer, a plan that is not an exact
            :class:`~kalpamani.data.ingest.sharadar.qualification.QualificationPlan`,
            or a byte ceiling the client could exceed.
        QualificationPlanError: for any plan defect, including a retry budget the
            client's policy would exceed.
    """
    if type(pacer) is not Pacer:
        raise _refuse() from None

    client = SharadarClient(
        credential=credential,
        transport=transport,
        pacer=pacer,
        retry_policy=retry_policy,
        timeout_seconds=timeout_seconds,
    )
    store = S3ResearchObjectStore(client=s3_client, licensed_bucket=licensed_bucket)
    runtime = QualificationRuntime(client=client, store=store, clock=clock)

    requests = runtime.validate(plan)

    return QualificationPreflight(
        status=PreflightStatus.VALIDATED_OFFLINE,
        request_count=len(requests),
        max_attempts=client.max_attempts,
        # The stricter of the two, written the same way the runtime writes it so
        # the numbers cannot drift apart. `validate()` has already refused a
        # client ceiling above the plan's, so this is the client's -- stated as a
        # minimum anyway, because a bound that depended on a check elsewhere
        # staying exactly as it is would be a bound by coincidence.
        max_response_bytes=min(client.max_response_bytes, plan.limits.max_response_bytes),
        max_run_bytes=plan.limits.max_run_bytes,
        retry_budget=plan.limits.retry_budget,
        acquisition_mode=QUALIFICATION_ACQUISITION_MODE,
        profile=PERMITTED_PROFILE,
    )


__all__ = [
    "PreflightStatus",
    "QualificationPreflight",
    "preflight_qualification_composition",
]
