"""The dormant Sharadar qualification composition root, and offline preflight.

ADR-0014. Until this module, five accepted slices sat beside one another with
nothing joining them: the credential, the transport, the client, the licensed S3
object store and the qualification runtime each existed, each took its
dependencies by injection, and **nothing anywhere constructed the set**. That
absence was the control. It was also a gap in review: the wiring nobody had
written was the wiring nobody had checked.

This module writes it, and stops one step short of using it.

What it is
==========

One class, :class:`SharadarQualificationComposition`, that receives every
dependency explicitly and builds the three accepted components from them. It
exposes exactly one operation -- :meth:`SharadarQualificationComposition.preflight`
-- which calls :meth:`~kalpamani.data.ingest.sharadar.runtime.QualificationRuntime.validate`
and returns a small closed result.

::

    composition root    EXISTS   (this module, and nowhere else)
    execution surface   NONE     no execute, run, fetch, publish or upload
    runner              NONE     no CLI, no module entry point, no scheduled task
    credential source   NONE     nothing here reads an environment or a file
    bucket binding      NONE     the bucket is a parameter, bound by a caller
    client construction NONE     the S3 client is a parameter; no SDK is imported
    provider requests   ZERO
    AWS requests        ZERO

What it is not
==============

**It is not authorization to run.** The first authenticated qualification run is
separately gated and remains unauthorized. Nothing outside this module's own
synthetic tests constructs this class, and a static guard keeps it that way.

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
The credential arrives already built, is handed to the client, and is not
retained here.

Nothing at import time does work, and nothing here opens a socket, reads a file,
parses an argument or names a host, a bucket, an account or an endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from kalpamani.data.contracts.vocabulary import (
    AcquisitionMode,
    InformationSetProfile,
)
from kalpamani.data.ingest.sharadar.client import (
    Pacer,
    RetryPolicy,
    SharadarClient,
)
from kalpamani.data.ingest.sharadar.credentials import SharadarCredential
from kalpamani.data.ingest.sharadar.qualification import (
    PERMITTED_PROFILE,
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

#: The acquisition mode this composition can ever record, fixed by the runtime.
#:
#: Restated here only so the preflight result can report it. It is **read from
#: the runtime's contract, not chosen here**: there is no parameter, no plan
#: field and no caller override, because there is exactly one kind of retrieval
#: this composition could perform and it is not a production operation
#: (ADR-0013).
QUALIFICATION_ACQUISITION_MODE: Final = AcquisitionMode.QUALIFICATION


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


@dataclass(frozen=True, slots=True, kw_only=True)
class QualificationPreflight:
    """What an offline preflight establishes. Safe to log in full.

    Every field is a closed vocabulary member or a bounded non-negative count.
    **There is no credential field, no bucket field, no URL field, no subject
    field, no payload field and no message field**, so none of those has anywhere
    to be -- and :meth:`__post_init__` enforces that at runtime rather than
    leaving it to annotations, which are a static claim.

    The numbers are *derived*, never restated: the request count comes from the
    plan's own generator, the attempt ceiling from the injected client's retry
    policy, and the byte ceilings from the stricter of the client and the plan.
    A preflight that reported declared intentions instead of effective bounds
    would describe a run other than the one that would happen.
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
        """Refuse anything that is not an exact member or an exact count.

        Raises:
            SharadarRequestError: ``BUILD: REQUEST_MALFORMED``. ``True`` is an
                ``int`` in Python, so an exact type check is what keeps a boolean
                out of a count; and a bare ``"QUALIFICATION"`` string is refused
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
        for count in (
            self.request_count,
            self.max_attempts,
            self.max_response_bytes,
            self.max_run_bytes,
            self.retry_budget,
        ):
            if type(count) is not int or count < 0:
                raise _refuse() from None


class SharadarQualificationComposition:
    """The wiring, and only the wiring.

    Receives every dependency explicitly -- there is **no default on any
    parameter**, so nothing here can reach a real transport, a real bucket or a
    real clock because a caller forgot one. Builds the three accepted components
    and keeps them private.

    **There is no execution method.** No ``execute``, ``run``, ``fetch``,
    ``publish``, ``upload`` or any private spelling of one, and no attribute
    exposing the runtime for a caller to call ``execute`` on. There is also no
    module-executable entry point: the guard that keeps one out of this package
    scans raw source, so this module does not spell the dunder even in prose. The distance
    between this and a live run is a separately gated authorization plus the code
    that would use it, and neither exists.
    """

    __slots__ = ("_client", "_runtime", "_store")

    def __init__(
        self,
        *,
        credential: SharadarCredential,
        transport: SharadarTransport,
        pacer: Pacer,
        retry_policy: RetryPolicy,
        timeout_seconds: float,
        s3_client: S3Client,
        licensed_bucket: str,
        clock: QualificationClock,
    ) -> None:
        """Construct the client, the licensed store and the runtime from injections.

        Validation is **delegated**, not duplicated: the credential's exactness,
        the timeout range, the retry policy's shape, the bucket name's grammar,
        the S3 client's two operations and the clock's one method are each already
        enforced by the constructor that owns them, and each refusal is already
        sanitized. Re-checking them here would create a second, drifting copy of
        every rule.

        ``pacer`` is the exception, and is required and exactly typed here.
        :class:`~kalpamani.data.ingest.sharadar.client.SharadarClient` accepts
        ``None`` and builds its own from :func:`time.monotonic` and
        :func:`time.sleep` -- a sensible default for a client, and the wrong one
        here: a composition root that silently acquired an ambient clock would
        have exactly the kind of unexamined dependency this module exists to make
        visible.

        Raises:
            SharadarRequestError: ``BUILD: REQUEST_MALFORMED`` for a pacer that is
                not an exact :class:`~kalpamani.data.ingest.sharadar.client.Pacer`,
                and from the client's own constructor for a bad credential,
                timeout or retry policy.
            ObjectStoreBackendError: ``BIND: INVALID_CONFIGURATION`` for a bucket
                name or S3 client the store will not accept. **The refusal never
                echoes the bucket.**
            QualificationRuntimeError: ``DEPENDENCY_MALFORMED`` for a clock that
                cannot answer.
        """
        if type(pacer) is not Pacer:
            raise _refuse() from None
        self._client = SharadarClient(
            credential=credential,
            transport=transport,
            pacer=pacer,
            retry_policy=retry_policy,
            timeout_seconds=timeout_seconds,
        )
        self._store = S3ResearchObjectStore(client=s3_client, licensed_bucket=licensed_bucket)
        self._runtime = QualificationRuntime(client=self._client, store=self._store, clock=clock)

    def __repr__(self) -> str:
        """A constant. Nothing caller-supplied can appear here.

        The three components it holds each have a constant or numeric ``repr`` of
        their own, but composing them would still be a decision about what is safe
        to print. A fixed string needs no such decision.
        """
        return "SharadarQualificationComposition(provider=sharadar, surface=preflight)"

    def preflight(self, plan: QualificationPlan) -> QualificationPreflight:
        """Validate ``plan`` against the constructed components. **Fetches nothing.**

        Calls :meth:`~kalpamani.data.ingest.sharadar.runtime.QualificationRuntime.validate`
        and nothing else. That method builds the plan's requests, checks the retry
        budget against the *injected client's* attempt policy, checks the request
        count against the plan's ceiling, checks that every request derives a
        distinct acquisition identity, checks both byte ceilings against what the
        client could actually return, and probes the clock. **It issues no
        provider request and no store call**, which is why a composition holding
        real dependencies is still inert while only this method exists.

        The returned counts are read back from the plan and the client rather than
        from the caller, so a preflight cannot report a bound the run would not
        honour.

        Raises:
            QualificationPlanError: for any plan defect, including a retry budget
                the client's policy would exceed.
            QualificationRuntimeError: for a malformed plan object, an unusable
                clock, or a byte ceiling the client could exceed.
        """
        requests = self._runtime.validate(plan)
        return QualificationPreflight(
            status=PreflightStatus.VALIDATED_OFFLINE,
            request_count=len(requests),
            max_attempts=self._client.max_attempts,
            # The stricter of the two, written the same way the runtime writes it
            # so the numbers cannot drift apart. `validate()` has already refused
            # a client ceiling above the plan's, so this is the client's -- stated
            # as a minimum anyway, because a preflight that depended on a check
            # elsewhere staying exactly as it is would be a bound by coincidence.
            max_response_bytes=min(self._client.max_response_bytes, plan.limits.max_response_bytes),
            max_run_bytes=plan.limits.max_run_bytes,
            retry_budget=plan.limits.retry_budget,
            acquisition_mode=QUALIFICATION_ACQUISITION_MODE,
            profile=PERMITTED_PROFILE,
        )


__all__ = [
    "QUALIFICATION_ACQUISITION_MODE",
    "PreflightStatus",
    "QualificationPreflight",
    "SharadarQualificationComposition",
]
