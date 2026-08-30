"""The dormant Sharadar authenticated acquisition-qualification entry point.

ADR-0017. Six accepted slices built a complete authenticated acquisition stack and
then stopped one statement short of using it: the plan model, the executor, the
licensed store, the Bronze bridge, the composition root and the private-binding
path all existed and were tested, and
:meth:`~kalpamani.data.ingest.sharadar.runtime.QualificationRuntime.execute` had
**no production caller**. This module is that caller, and only that.

**It has never been run.** Implementing an operator surface is not permission to
use it: a real bounded authenticated acquisition qualification is a **separate**
written authorization, and none has been given.

::

    entry points          ONE      scripts/ only; the package re-exports nothing
    default behaviour     REFUSE   no flag, no work -- no lookup, no client, no socket
    authorization         ONE      --i-am-the-operator-authorizing-authenticated-qualification
    what it authorizes    ONE BOUNDED ACQUISITION QUALIFICATION -- never a second
    authorized attempts   ZERO     ·   provider requests: ZERO
    qualification-runtime executions against real services: ZERO
    provider authentication: UNKNOWN   ·   S3 qualification operations: ZERO

What one future run may establish
=================================

**Only** that the governed credential authenticated for the exact bounded request,
that the locked dataset was accessible at that moment, that one response was
returned, and that it was durably acquired under the accepted licensed Bronze
contract.

It establishes **nothing** about: full P1-P9 empirical qualification ·
provider-wide authentication · access to every Sharadar dataset · full-history or
Services Data entitlement · response-schema correctness · data quality ·
point-in-time correctness · history depth · price-feed provenance · Q7, which
stays ``PUBLICLY_UNRESOLVED`` · production-provider selection · G1 or G2 closure ·
ingestion readiness · authorization for another request · current or future
credential or session validity.

The payload is opaque
=====================

Nothing here parses, decodes, samples, counts or inspects the vendor payload, and
no CSV parser is imported or written. The bytes travel from the client to the
Bronze publisher inside the runtime, under ADR-0012's contract. Field names, rows,
ticker correspondence, schema, semantics and data quality belong to a later,
separately governed private empirical slice operating on the retained evidence --
not to a live provider request.

The order is the security property
==================================

::

     1  operator authorization flag
     2  execution context -- refused under pytest, CI or an import-only context
     3  subject and execution-identifier contract admission
     4  governed AWS_PROFILE contract
     5  existing AWS identity gate
     6  existing governed licensed-bucket resolution
     7  fixed secret-identifier source
     8  existing Secrets Manager client and boundary
     9  existing SharadarCredential structural contract
    10  the accepted composition root, extended
    11  one QUALIFICATION acquisition plan
    12  exactly one QualificationRuntime.execute call
    13  a closed, sanitized outcome

No later stage runs after an earlier refusal, because a refusal raises. **The
secret identifier is not resolved before gates 1-5 pass**, so a wrong-account
session never reaches a private identifier and a failed gate never reaches a
credential.

Not the other two scripts
=========================

``sharadar_private_qualification.py`` is the **public-test-token** P1-P9 harness:
a different credential, five tables, payload parsing and a broader persistence
model. ``sharadar_binding_preflight.py`` terminates at offline composition **by
design**. Neither is imported, invoked, repurposed or changed here, and their
executable behaviour is untouched.

Run (by the owner, manually, only under a separate written authorization)::

    .venv\\Scripts\\python.exe scripts\\sharadar_authenticated_qualification.py \\
        --i-am-the-operator-authorizing-authenticated-qualification \\
        --subject AAPL --execution-id <one-execution-identity>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import Any, Final

#: The one flag that turns a refusal into a bounded acquisition qualification.
#:
#: Long, explicit and awkward on purpose. Anything a person might type from habit
#: -- ``--run``, ``--live``, ``--execute``, ``--force`` -- is refused by name
#: below, so a wrong reflex fails loudly instead of doing something.
AUTHORIZATION_FLAG: Final = "--i-am-the-operator-authorizing-authenticated-qualification"

#: The one fixed, non-secret environment-variable *name* the production source
#: reads on the authorized path. The name is not a secret; the value is, and it is
#: never printed, logged, returned or included in a refusal.
#: Ruff flags the *name* on its hardcoded-password heuristic. This is the name of
#: an environment variable, not a value.
SECRET_ID_ENV_VAR: Final = "KALPAMANI_SHARADAR_SECRET_ID"  # noqa: S105

#: The profile and region the governed foundation is pinned to. The same values
#: the binding preflight pins, restated here rather than imported: importing a
#: private helper from another executable script would couple two operator
#: surfaces whose failure modes must stay independent.
EXPECTED_PROFILE: Final = "kalpamani-foundation"
EXPECTED_REGION: Final = "us-east-1"

#: The Terraform output holding the licensed research bucket.
#:
#: Named, so the CONTROL bucket cannot be substituted by editing a variable: the
#: control bucket has a different output key and this module never names it.
LICENSED_BUCKET_OUTPUT: Final = "licensed_bucket_name"

#: The locked plan. ADR-0017 fixed every one of these, and **none is operator
#: selectable**: an operator who could choose the dataset, the page or the window
#: could choose a retrieval nobody reviewed.
LOCKED_DATASET_NAME: Final = "stocks"
PAGE_SKIP: Final = 0
PAGE_LIMIT: Final = 1
PAGE_LIMIT_CEILING: Final = 10
MAX_PAGES: Final = 1
WINDOW_DAYS: Final = 7
TIMEOUT_SECONDS: Final = 30.0

#: Options refused by name, each with the reason.
#:
#: Present as rejected names rather than simply absent: an unrecognised flag is
#: already an ``argparse`` error, but one that says "unrecognized arguments"
#: teaches nothing and someone tries again with a different spelling.
REFUSED_OPTIONS: Final[dict[str, str]] = {
    "--run": "there is no run mode; this command is one bounded acquisition or a refusal",
    "--live": "there is no live mode, and nothing here can construct one",
    "--execute": "the authorization flag is the only way to execute; there is no alias",
    "--force": "nothing here is forceable; a refusal is a refusal",
    "--api-key": "no credential is accepted on the command line, ever",
    "--secret-value": "no credential value is accepted on the command line, ever",
    "--secret-id": (
        "a secret identifier is private; on the command line it enters shell history and "
        "every process listing. It is read from the environment on the authorized path"
    ),
    "--secret-name": "same as --secret-id: a private identifier does not travel in argv",
    "--secret-arn": "same as --secret-id: a private identifier does not travel in argv",
    "--secret": "same as --secret-id: a private identifier does not travel in argv",
    "--arn": "an ARN names an account; it is never supplied and never printed",
    "--profile": "the governed profile is pinned in code and compared, never supplied",
    "--aws-profile": "same as --profile: the pin is not an operator choice",
    "--bucket": "the licensed bucket is resolved from governed state, never supplied",
    "--endpoint": "no endpoint is accepted; the SDK and the transport resolve the governed one",
    "--dataset": "the dataset is locked by ADR-0017; a selector would widen the retrieval",
    "--table": "same as --dataset: the table is locked and is not an operator choice",
    "--window": "the window is a deterministic function of the clock, never supplied",
    "--from": "same as --window: no date bound is accepted",
    "--to": "same as --window: no date bound is accepted",
    "--page": "there is no pagination; one page is the whole authorized retrieval",
    "--page-size": "same as --limit: the page size is locked and is not an operator choice",
    "--limit": "the page limit is locked by ADR-0017 and is not an operator choice",
    "--skip": "the page offset is locked at zero; walking a result set is not authorized",
    "--retry": "there is no retry; one attempt is the whole authorized retrieval",
    "--retries": "same as --retry: a failed request is a completed result, not a first try",
    "--full-history": "full history is not authorized and no code path can request it",
    "--full": "same as --full-history: no bulk retrieval is constructible",
    "--bulk": "no bulk or archive route exists to reach",
    "--archive": "same as --bulk: no archive route exists to reach",
    "--services-data": "Services Data export is not authorized and is not constructible",
    "--ingest": "ingestion is a separate, unauthorized decision",
    "--control": "CONTROL publication is deferred and forbidden; this writes LICENSED only",
    "--token": "no token is accepted, read, stored or bound by this command",
}


class _AcquisitionAuthorization:
    """Proof that the operator flag was parsed. **Exactly one exists.**

    The same shape ADR-0015 arrived at after two corrections, and for the same
    reasons. A ``bool`` would mean any importer could pass ``True``. An object
    carrying a module-private *mint field* would be **copyable**, and
    ``copy.copy`` would manufacture a second bearer of the authority the
    capability exists to prevent.

    There is **no state to copy**: ``__slots__`` is empty, admission is identity
    against the single module-level instance, and every route that would produce a
    second object is closed. An ``object.__new__`` instance can still be built and
    is refused for the reason that matters -- it is not *this* object.

    This is not a claim about hostile runtime introspection: a process that can
    reach this module's private names already holds the singleton.
    """

    __slots__ = ()

    def __new__(cls) -> _AcquisitionAuthorization:
        """Refuse a second construction once the singleton exists."""
        if "_ACQUISITION_AUTHORIZATION" in globals():
            raise TypeError("the acquisition authorization is a singleton")
        return super().__new__(cls)

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass instance is a second bearer."""
        raise TypeError("the acquisition authorization may not be subclassed")

    def __copy__(self) -> _AcquisitionAuthorization:
        """Refuse copying, so no copy operation yields an object at all."""
        raise TypeError("the acquisition authorization may not be copied")

    def __deepcopy__(self, memo: object) -> _AcquisitionAuthorization:
        """Refuse deep copying, for the same reason."""
        raise TypeError("the acquisition authorization may not be copied")

    def __reduce__(self) -> object:
        """Refuse pickling, which is copying with extra steps."""
        raise TypeError("the acquisition authorization may not be pickled")


_ACQUISITION_AUTHORIZATION: Final = _AcquisitionAuthorization()


def _is_authorized(candidate: object) -> bool:
    """Whether ``candidate`` **is** the one authorization this module holds.

    Identity, and nothing else. No type check is needed and none is written: a
    type check plus a copyable field is what admitted a shallow copy in the
    binding preflight's second revision, and adding one back would invite it.
    """
    return candidate is _ACQUISITION_AUTHORIZATION


class AcquisitionOutcome(StrEnum):
    """Every sentence this command may print. A fixed allowlist.

    Each is a fact about what the command did, safe in a public transcript. None
    reports a qualification verdict, provider suitability, entitlement or
    readiness -- those are not facts this command establishes, and a word implying
    one would be read as permission.

    **There is no separate empty-result member, deliberately.** ADR-0017 makes an
    empty provider response a *completed* result: a holiday week, a market closure
    or a delisted subject can legitimately return zero rows, and that is an answer
    rather than a fault. Giving it its own outcome would invite a reader to treat
    it as something to fix, and the one thing it must never become is permission
    to widen the window and ask again.
    """

    REFUSED_NOT_AUTHORIZED = "authenticated qualification refused: not authorized"
    REFUSED_OPTION = "authenticated qualification refused: this option is not accepted"
    REFUSED_EXECUTION_CONTEXT = "authenticated qualification refused: execution context"
    REFUSED_SUBJECT = "authenticated qualification refused: subject or execution identity"
    REFUSED_PROFILE = "authenticated qualification refused: the governed profile did not match"
    REFUSED_IDENTITY = "authenticated qualification refused: the AWS identity gate did not pass"
    REFUSED_LICENSED_BUCKET = "authenticated qualification refused: licensed configuration"
    # The member *name* trips the hardcoded-password heuristic; the value is an
    # allowlisted refusal sentence naming nothing. Suppressed per line, as in the
    # secrets boundary and the binding preflight, not by disabling the rule.
    REFUSED_SECRET_IDENTIFIER = (
        "authenticated qualification refused: no usable secret identifier was resolved"  # noqa: S105
    )
    REFUSED_SECRETS_ACCESS = "authenticated qualification refused: the secrets boundary refused"
    REFUSED_CREDENTIAL = "authenticated qualification refused: the credential contract refused"
    REFUSED_DEPENDENCY = "authenticated qualification refused: a local dependency was unavailable"
    REFUSED_PLAN = "authenticated qualification refused: the bounded plan was refused"
    REFUSED_PROVIDER_REQUEST = "authenticated qualification refused: the provider request failed"
    REFUSED_RESPONSE_SIZE = "authenticated qualification refused: the response exceeded its ceiling"
    REFUSED_PUBLICATION = "authenticated qualification refused: the acquisition was not published"
    REFUSED_UNCLASSIFIED = "authenticated qualification refused: unclassified"
    COMPLETED = "authenticated acquisition qualification completed"


#: The exit status each outcome maps to. **Total, and checked by a test.**
#:
#: Completion is ``0``; every refusal is non-zero. There is no ``.get`` default
#: and no ``else`` branch: an outcome added later by someone who did not run the
#: totality test has no exit code at all, which fails loudly rather than
#: reporting success for something nobody classified.
EXIT_STATUS: Final[dict[AcquisitionOutcome, int]] = {
    AcquisitionOutcome.COMPLETED: 0,
    AcquisitionOutcome.REFUSED_NOT_AUTHORIZED: 1,
    AcquisitionOutcome.REFUSED_OPTION: 2,
    AcquisitionOutcome.REFUSED_EXECUTION_CONTEXT: 3,
    AcquisitionOutcome.REFUSED_SUBJECT: 4,
    AcquisitionOutcome.REFUSED_PROFILE: 5,
    AcquisitionOutcome.REFUSED_IDENTITY: 6,
    AcquisitionOutcome.REFUSED_LICENSED_BUCKET: 7,
    AcquisitionOutcome.REFUSED_SECRET_IDENTIFIER: 8,
    AcquisitionOutcome.REFUSED_SECRETS_ACCESS: 9,
    AcquisitionOutcome.REFUSED_CREDENTIAL: 10,
    AcquisitionOutcome.REFUSED_DEPENDENCY: 11,
    AcquisitionOutcome.REFUSED_PLAN: 12,
    AcquisitionOutcome.REFUSED_PROVIDER_REQUEST: 13,
    AcquisitionOutcome.REFUSED_RESPONSE_SIZE: 14,
    AcquisitionOutcome.REFUSED_PUBLICATION: 15,
    AcquisitionOutcome.REFUSED_UNCLASSIFIED: 16,
}


class AuthenticatedQualificationError(Exception):
    """A refusal carrying exactly one allowlisted :class:`AcquisitionOutcome`.

    Raised ``from None`` everywhere, always. A backend exception quotes a secret
    name, an ARN or a bucket; a plan refusal can quote a subject; a provider error
    can carry a URL that *is* a credential, because the key travels in the query
    string. None of that may reach a traceback a person pastes into a chat.
    """

    def __init__(self, outcome: AcquisitionOutcome) -> None:
        """Bind the outcome. The message is the allowlisted sentence, nothing more."""
        if type(outcome) is not AcquisitionOutcome:  # pragma: no cover - type guard
            raise TypeError("an outcome must be an exact AcquisitionOutcome member")
        super().__init__(outcome.value)
        self.outcome = outcome


#: How a runtime failure maps to a public outcome. **Total, and checked.**
#:
#: No ``.get`` default and no ``else``: a member added to the runtime's vocabulary
#: later maps to nothing here, and the totality test fails rather than a new
#: failure silently becoming a provider-request claim it may not be.
_RUNTIME_FAILURE_OUTCOME: Final[dict[str, AcquisitionOutcome]] = {
    "PROVIDER_REQUEST_FAILED": AcquisitionOutcome.REFUSED_PROVIDER_REQUEST,
    "RESPONSE_TOO_LARGE": AcquisitionOutcome.REFUSED_RESPONSE_SIZE,
    "RUN_BYTE_HEADROOM_EXHAUSTED": AcquisitionOutcome.REFUSED_RESPONSE_SIZE,
    "RUN_BYTE_CEILING_UNSATISFIABLE": AcquisitionOutcome.REFUSED_PLAN,
    "RESPONSE_BYTE_CEILING_UNSATISFIABLE": AcquisitionOutcome.REFUSED_PLAN,
    "PAYLOAD_NOT_EXACT_BYTES": AcquisitionOutcome.REFUSED_PUBLICATION,
    "CONTENT_CONFLICT": AcquisitionOutcome.REFUSED_PUBLICATION,
    "STORAGE_REFUSED": AcquisitionOutcome.REFUSED_PUBLICATION,
    "DEPENDENCY_MALFORMED": AcquisitionOutcome.REFUSED_DEPENDENCY,
    "RESULT_MALFORMED": AcquisitionOutcome.REFUSED_UNCLASSIFIED,
    "UNCLASSIFIED": AcquisitionOutcome.REFUSED_UNCLASSIFIED,
}


def _emit(outcome: AcquisitionOutcome) -> None:
    """Print one allowlisted sentence.

    Takes a vocabulary member, not a string, so there is no parameter through
    which a bucket, a subject, a URL or an exception could arrive.
    """
    print(outcome.value)


def running_under_automation(env: Mapping[str, str], modules: Mapping[str, object]) -> str | None:
    """Why this must not run here, or ``None``.

    A provider request and a durable licensed acquisition are owner actions. Under
    ``pytest`` the tests would perform them; in CI the transcript is a log; on a
    plain import nobody asked for anything at all. Each is refused before the
    profile is even read.

    The check is on the *caller's* mapping arguments rather than on ambient state,
    so the tests can drive every branch without setting a real environment
    variable or importing a real module.
    """
    if "pytest" in modules:
        return "pytest"
    for name in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "BUILD_NUMBER"):
        if env.get(name, "").strip():
            return name
    return None


class SystemClock:
    """The wall clock, in the one place a real run is allowed to read one.

    The runtime takes its instant by injection precisely so it never reads an
    ambient clock; this is the operator boundary handing it one, and the tests
    hand it a fixed clock instead.
    """

    def now(self) -> Any:
        """The current UTC instant."""
        from datetime import UTC, datetime

        return datetime.now(UTC)


def qualification_window(instant: Any) -> Any:
    """The locked seven-calendar-day trailing window, from ``instant``.

    ``end`` is the UTC calendar date **immediately before** ``instant``, and
    ``start`` is six days before that -- seven calendar days inclusive.

    Ending the day before is deliberate: the vendor documents the upper bound as
    defaulting to the prior day (``PSR-SHD-121``), and a window whose last day is
    still in progress makes an empty answer ambiguous between *no session yet* and
    *no data*.

    A pure function of the injected clock, so one execution identity and one
    instant reproduce one window exactly.
    """
    from datetime import UTC, timedelta

    from kalpamani.data.ingest.sharadar.datasets import DateWindow

    end = (instant.astimezone(UTC) - timedelta(days=1)).date()
    return DateWindow(start=end - timedelta(days=WINDOW_DAYS - 1), end=end)


def build_locked_plan(*, subject: str, execution_id: str, instant: Any) -> Any:
    """The one bounded plan ADR-0017 permits. **Every value but two is locked.**

    The subject and the execution identity are the operator's; the dataset, the
    page, the window policy, the page count and the response format are this
    module's, and no argument can change them.

    One dataset plan and one subject over one page is **exactly one request**,
    which is the whole authorized retrieval.

    Raises:
        QualificationPlanError: for a malformed subject, execution identity or
            window. The refusal can quote a subject, so every caller here
            converts it to a closed outcome ``from None``.
    """
    from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
    from kalpamani.data.ingest.sharadar.qualification import (
        DatasetPlan,
        QualificationPlan,
        QualificationSubject,
    )

    return QualificationPlan(
        subjects=(QualificationSubject(subject),),
        datasets=(
            DatasetPlan(
                dataset=SharadarDataset(LOCKED_DATASET_NAME),
                window=qualification_window(instant),
                page_limit=PAGE_LIMIT,
                max_pages=MAX_PAGES,
            ),
        ),
        execution_id=execution_id,
    )


def _classify_result(result: Any) -> AcquisitionOutcome:
    """Map the runtime's own result onto one public outcome.

    ``COMPLETED`` is the only success, and it is a claim about the *acquisition*:
    one request was answered and its evidence was durably published. It says
    nothing about the rows, because nothing here has looked at them -- an empty
    response that published cleanly is a completed acquisition qualification.

    Every other shape is a refusal. A halted run's failure is looked up in a total
    mapping; anything the mapping does not know becomes ``REFUSED_UNCLASSIFIED``
    rather than a positive claim about a boundary that may never have been
    reached.
    """
    outcome = getattr(result, "outcome", None)
    failure = getattr(result, "failure", None)
    name = getattr(outcome, "name", None)

    if name == "COMPLETED":
        return AcquisitionOutcome.COMPLETED
    if name == "REFUSED":
        return AcquisitionOutcome.REFUSED_PLAN
    if name != "HALTED":
        return AcquisitionOutcome.REFUSED_UNCLASSIFIED

    failure_name = getattr(failure, "name", None)
    if type(failure_name) is not str:
        return AcquisitionOutcome.REFUSED_UNCLASSIFIED
    return _RUNTIME_FAILURE_OUTCOME.get(failure_name, AcquisitionOutcome.REFUSED_UNCLASSIFIED)


def run_authenticated_qualification(
    *,
    authorization: object,
    subject: str | None,
    execution_id: str | None,
    env: Mapping[str, str],
    modules: Mapping[str, object],
    profile_of: Callable[[], str],
    identity_gate: Callable[[], str | None],
    resolve_licensed_bucket: Callable[[], str],
    secret_id_source: Callable[[], str],
    secrets_client_factory: Callable[[], Any],
    s3_client_factory: Callable[[], Any],
    transport_factory: Callable[[], Any],
    clock: Any,
) -> AcquisitionOutcome:
    """Bind the private dependencies and perform **one** bounded acquisition.

    Every stage is a parameter, which is what makes this testable without AWS and
    what keeps the ambient environment out of it: nothing here reads
    ``os.environ``, opens a file, constructs a client or resolves a name. The real
    factories are supplied by :func:`main`, and this slice never calls it with
    real ones.

    ``authorization`` is a capability minted by :func:`main` after the exact
    operator flag parses. It is **not** a boolean: a boolean is the one value
    every caller already has.

    ``secret_id_source`` is a zero-argument callable rather than a value, and it
    is invoked **once**, after gates 1-6 have passed. A private identifier must
    not be resolved on a path that is going to refuse.

    The order in the module docstring is enforced here by sequence rather than
    described: a later stage cannot run after an earlier refusal, because a
    refusal raises.

    **Exactly one call to** ``execute_qualification_acquisition`` **is made**, and
    there is no loop, no retry, no fallback and no second request anywhere in this
    function. A provider failure, a publication failure and an empty response are
    each a completed result.

    Raises:
        AuthenticatedQualificationError: one allowlisted
            :class:`AcquisitionOutcome`. The cause is always suppressed.
    """
    # 1. Authorization. A capability this module minted after parsing the flag.
    if not _is_authorized(authorization):
        raise AuthenticatedQualificationError(AcquisitionOutcome.REFUSED_NOT_AUTHORIZED) from None

    # 2. Execution context. Refused before anything is read or resolved.
    if running_under_automation(env, modules) is not None:
        raise AuthenticatedQualificationError(
            AcquisitionOutcome.REFUSED_EXECUTION_CONTEXT
        ) from None

    # 3. The subject and the execution identity, admitted by the plan model's own
    #    grammar -- built here so a malformed one refuses before any AWS contact.
    if type(subject) is not str or type(execution_id) is not str:
        raise AuthenticatedQualificationError(AcquisitionOutcome.REFUSED_SUBJECT) from None
    try:
        plan = build_locked_plan(subject=subject, execution_id=execution_id, instant=clock.now())
    except Exception:
        # The plan refusal can quote a subject, so only the closed outcome survives.
        raise AuthenticatedQualificationError(AcquisitionOutcome.REFUSED_SUBJECT) from None

    # 4. The profile, before any AWS call is attempted at all.
    try:
        profile = profile_of()
    except Exception:
        raise AuthenticatedQualificationError(AcquisitionOutcome.REFUSED_PROFILE) from None
    if profile != EXPECTED_PROFILE:
        raise AuthenticatedQualificationError(AcquisitionOutcome.REFUSED_PROFILE) from None

    # 5. The account identity gate. Its reason string can name an account, so it
    #    is consumed as a pass/fail and never printed.
    try:
        reason = identity_gate()
    except Exception:
        raise AuthenticatedQualificationError(AcquisitionOutcome.REFUSED_IDENTITY) from None
    if reason is not None:
        raise AuthenticatedQualificationError(AcquisitionOutcome.REFUSED_IDENTITY) from None

    # 6. The licensed bucket, from governed state. Never the control one.
    try:
        licensed_bucket = resolve_licensed_bucket()
    except Exception:
        raise AuthenticatedQualificationError(AcquisitionOutcome.REFUSED_LICENSED_BUCKET) from None

    # 7. The secret identifier -- the first stage that touches anything private,
    #    and only now that every gate above has passed.
    try:
        from kalpamani.data.ingest.sharadar.secrets import is_usable_secret_identifier
    except Exception:
        raise AuthenticatedQualificationError(AcquisitionOutcome.REFUSED_DEPENDENCY) from None
    try:
        secret_id = secret_id_source()
    except Exception:
        raise AuthenticatedQualificationError(
            AcquisitionOutcome.REFUSED_SECRET_IDENTIFIER
        ) from None
    if not is_usable_secret_identifier(secret_id):
        raise AuthenticatedQualificationError(
            AcquisitionOutcome.REFUSED_SECRET_IDENTIFIER
        ) from None

    # 8. The Secrets Manager client. A missing SDK is a local dependency failure
    #    and never a credential claim -- the correction ADR-0016 exists for.
    try:
        secrets_client = secrets_client_factory()
    except Exception:
        raise AuthenticatedQualificationError(AcquisitionOutcome.REFUSED_DEPENDENCY) from None

    # 9. The credential, through the existing boundary and contract. One call.
    try:
        from kalpamani.data.ingest.sharadar.secrets import sharadar_credential_from_secret
    except Exception:
        raise AuthenticatedQualificationError(AcquisitionOutcome.REFUSED_DEPENDENCY) from None
    try:
        credential = sharadar_credential_from_secret(client=secrets_client, secret_id=secret_id)
    except Exception:
        raise AuthenticatedQualificationError(AcquisitionOutcome.REFUSED_CREDENTIAL) from None

    # 10. The remaining injected dependencies, then the accepted composition root.
    try:
        from kalpamani.data.ingest.sharadar.client import Pacer, RetryPolicy
        from kalpamani.data.ingest.sharadar.composition import execute_qualification_acquisition

        s3_client = s3_client_factory()
        transport = transport_factory()
    except Exception:
        raise AuthenticatedQualificationError(AcquisitionOutcome.REFUSED_DEPENDENCY) from None

    # 11-12. One plan, one execution. No loop, no retry, no second request.
    try:
        result = execute_qualification_acquisition(
            credential=credential,
            transport=transport,
            pacer=Pacer(),
            retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=()),
            timeout_seconds=TIMEOUT_SECONDS,
            s3_client=s3_client,
            licensed_bucket=licensed_bucket,
            clock=clock,
            plan=plan,
        )
    except Exception:
        # A provider error can carry a URL that *is* a credential, and a store
        # error can quote the bucket. Neither survives into a public outcome.
        raise AuthenticatedQualificationError(AcquisitionOutcome.REFUSED_UNCLASSIFIED) from None

    # 13. One closed outcome, derived from the runtime's own result.
    return _classify_result(result)


def build_parser() -> argparse.ArgumentParser:
    """The executable CLI surface. **Exactly three arguments, and no aliases.**

    Dataset, page, limit, window policy, retry policy, response ceiling, bucket
    destination and acquisition mode are locked in code. An operator who could
    choose them could choose a retrieval nobody reviewed.
    """
    parser = argparse.ArgumentParser(
        prog="sharadar_authenticated_qualification",
        description=(
            "One bounded authenticated Sharadar acquisition qualification. Refused by "
            "default. The dataset, window, page, retry policy and destination are locked."
        ),
    )
    parser.add_argument(
        AUTHORIZATION_FLAG,
        dest="authorization_flag_present",
        action="store_true",
        help="authorize ONE bounded authenticated acquisition qualification, and nothing else",
    )
    parser.add_argument(
        "--subject",
        dest="subject",
        default=None,
        help="the one subject to acquire; validated by the plan model's own grammar",
    )
    parser.add_argument(
        "--execution-id",
        dest="execution_id",
        default=None,
        help="the one execution identity this acquisition is recorded under",
    )
    return parser


def _refused_option(argv: Sequence[str]) -> str | None:
    """The first refused option in ``argv``, or ``None``.

    Matched on the option token, so ``--secret-id=value`` is refused by the same
    entry as ``--secret-id`` and the value is never echoed.
    """
    for token in argv:
        name = token.split("=", 1)[0]
        if name in REFUSED_OPTIONS:
            return name
    return None


def main(argv: list[str] | None = None) -> int:
    """Parse, refuse, or perform one bounded acquisition. Returns a command status.

    ``0`` means the acquisition qualification completed; non-zero means the
    command refused. **Neither is a verdict** about the provider, the data, the
    schema, or whether a further run should happen.

    **The real factories are constructed here and only here**, inside the
    authorized branch. This function has **never been run**: implementing it is
    not authorization to use it, and a bounded authenticated qualification remains
    a separate written authorization that has not been given.
    """
    argv = list(sys.argv[1:] if argv is None else argv)

    refused = _refused_option(argv)
    if refused is not None:
        _emit(AcquisitionOutcome.REFUSED_OPTION)
        print(f"  {refused}: {REFUSED_OPTIONS[refused]}")
        return EXIT_STATUS[AcquisitionOutcome.REFUSED_OPTION]

    parsed = build_parser().parse_args(argv)

    if not parsed.authorization_flag_present:
        # The default path. Nothing above this line looked anything up,
        # constructed anything, or opened anything.
        _emit(AcquisitionOutcome.REFUSED_NOT_AUTHORIZED)
        print(f"  pass {AUTHORIZATION_FLAG} to authorize one bounded acquisition")
        print("  that flag authorizes exactly one acquisition, never a second request")
        return EXIT_STATUS[AcquisitionOutcome.REFUSED_NOT_AUTHORIZED]

    import os

    try:
        outcome = run_authenticated_qualification(
            # Handed over here, and only here: the flag has parsed.
            authorization=_ACQUISITION_AUTHORIZATION,
            subject=parsed.subject,
            execution_id=parsed.execution_id,
            env=os.environ,
            modules=sys.modules,
            profile_of=_ambient_profile,
            identity_gate=_governed_identity_gate,
            resolve_licensed_bucket=_governed_licensed_bucket,
            secret_id_source=_environment_secret_id,
            secrets_client_factory=_secrets_client,
            s3_client_factory=_s3_client,
            transport_factory=_transport,
            clock=SystemClock(),
        )
    except AuthenticatedQualificationError as refusal:
        _emit(refusal.outcome)
        return EXIT_STATUS[refusal.outcome]

    _emit(outcome)
    return EXIT_STATUS[outcome]


def _ambient_profile() -> str:
    """The pinned profile from the process environment. Read, never printed."""
    import os

    return os.environ.get("AWS_PROFILE", "")


def _environment_secret_id() -> str:
    """The secret identifier, from one fixed environment-variable name.

    Called only on the authorized path, after every gate above it has passed. The
    *name* is a constant and is not a secret; the *value* is, and it is never
    printed, logged, returned to a caller or included in a refusal.

    ``os`` is imported inside the body, so an ordinary import of this module --
    and every refusal path above -- performs no environment lookup at all.

    Raises:
        LookupError: if the variable is unset or blank. Converted by the caller
            into the closed ``REFUSED_SECRET_IDENTIFIER`` outcome, which names
            nothing -- and which is not the credential outcome, because at that
            point no client exists and nothing has been invoked.
    """
    import os

    value = os.environ.get(SECRET_ID_ENV_VAR, "")
    if not value.strip():
        raise LookupError("the secret identifier environment variable is unset")
    return value


def _governed_identity_gate() -> str | None:
    """The existing account identity gate. Not a second implementation of one."""
    from aws_foundation_verify import identity_gate  # type: ignore[import-not-found]

    return identity_gate()  # type: ignore[no-any-return]


def _governed_licensed_bucket() -> str:
    """The licensed bucket from governed Terraform state. Never the control one."""
    from aws_foundation_verify import tf_outputs  # type: ignore[import-not-found]

    return str(tf_outputs()[LICENSED_BUCKET_OUTPUT])


def _secrets_client() -> Any:
    """A Secrets Manager client, pinned to the governed region."""
    import boto3

    return boto3.client("secretsmanager", region_name=EXPECTED_REGION)


def _s3_client() -> Any:
    """An S3 client, pinned to the governed region."""
    import boto3

    return boto3.client("s3", region_name=EXPECTED_REGION)


def _transport() -> Any:
    """The origin-pinned provider transport."""
    from kalpamani.data.ingest.sharadar.transport import UrllibTransport

    return UrllibTransport()


#: The public surface, stated so it can be checked rather than inferred.
#:
#: The authorization capability and its class are absent, deliberately: an
#: exported capability is a public constructor by another name.
__all__ = [
    "AUTHORIZATION_FLAG",
    "EXIT_STATUS",
    "REFUSED_OPTIONS",
    "AcquisitionOutcome",
    "AuthenticatedQualificationError",
    "build_locked_plan",
    "build_parser",
    "main",
    "qualification_window",
    "run_authenticated_qualification",
    "running_under_automation",
]


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    sys.exit(main())
