"""One bounded private empirical Sharadar acquisition (ADR-0018). **Refused by default.**

**This command has never been run, and running it is a separate written
authorization that has not been given.** Implementing an operator surface is not
permission to use it. Implementation, infrastructure mutation and execution are
three distinct gates, and they are never collapsed into one.

**An ordinary import does nothing observable.** No environment lookup, no client
construction, no socket, no file read, no credential and no state read. Every
``kalpamani`` import sits inside a function body, so a machine with a broken
environment gets a clean refusal rather than a traceback -- which is the class of
machine these defects are found on.

**The enforced order is the security property, and it is sequence rather than
prose.** A refusal raises, so no later stage runs after an earlier one refuses: a
wrong-account session never reaches a secret, and a failed gate never reaches a
credential. A refusal at stages 1-10 issues **zero** provider requests and **zero**
writes.

```text
 1  require an explicit ONE-RUN authorization
 2  refuse under automation, CI, pytest and import-only contexts
 3  load and validate the owner-only eight-subject inventory
 4  pin the governed AWS profile
 5  pass the governed identity gate
 6  resolve only the LICENSED bucket -- never CONTROL
 7  resolve the fixed secret identifier
 8  retrieve one governed credential
 9  construct the injected dependencies
10  run the offline plan preflight
11  execute the 48 requests SEQUENTIALLY
12  publish three Bronze objects per completed request
13  publish ONE private locator, LAST
14  emit only closed, non-sensitive counts and statuses
```

**The inventory is loaded at stage 3, before any AWS or provider dependency can be
reached.** A private input that is missing or malformed costs nothing to discover,
and discovering it after the identity gate would mean an AWS round trip spent
learning something checkable for free.

**No subject reaches the command line, and no option could carry one.** The CLI is
exactly two arguments. The subjects come from an owner-only, git-ignored file whose
path the application fixes; a ``--subject`` flag would put a private evaluation
decision into shell history and into every process listing on the workstation.

**Output is allowlisted.** A fixed set of sentences through one function that takes a
vocabulary member, not a string -- so no bucket, key, digest, subject, account, URL,
row or finding has a parameter to arrive through. The exit status is a command
status and never a qualification verdict.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import Any, Final

#: The one flag that turns a refusal into one bounded empirical acquisition.
#:
#: Long, explicit and awkward on purpose, and **distinct from every other operator
#: flag in this repository**: an authorization that could be pasted from another
#: command is an authorization that can be given by accident.
AUTHORIZATION_FLAG: Final = "--i-am-the-operator-authorizing-empirical-acquisition"

#: The one fixed, non-secret environment-variable *name* the production source reads
#: on the authorized path. The name is not a secret; the value is, and it is never
#: printed, logged, returned or included in a refusal.
#: Ruff flags the *name* on its hardcoded-password heuristic. This is the name of an
#: environment variable, not a value.
SECRET_ID_ENV_VAR: Final = "KALPAMANI_SHARADAR_SECRET_ID"  # noqa: S105

#: The profile and region the governed foundation is pinned to. Restated rather than
#: imported from another executable script: coupling two operator surfaces would make
#: their failure modes depend on each other.
EXPECTED_PROFILE: Final = "kalpamani-foundation"
EXPECTED_REGION: Final = "us-east-1"

#: The Terraform output holding the licensed research bucket. Named, so the CONTROL
#: bucket cannot be substituted by editing a variable: it has a different output key
#: and this module never names it.
LICENSED_BUCKET_OUTPUT: Final = "licensed_bucket_name"

#: Options refused by name, each with the reason. Present as rejected names rather
#: than merely absent: an unrecognised flag is already an ``argparse`` error, but one
#: that says "unrecognized arguments" teaches nothing and someone tries again with a
#: different spelling.
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
    "--subject": (
        "a subject is private evaluation information; it would enter shell history and "
        "every process listing. Subjects come from the owner-only inventory file"
    ),
    "--subjects": "same as --subject: no security name is accepted on the command line",
    "--ticker": "same as --subject: no security name is accepted on the command line",
    "--tickers": "same as --subject: no security name is accepted on the command line",
    "--inventory": (
        "the private inventory path is fixed by the application; a path option would "
        "put a private location into shell history and every process listing"
    ),
    "--inventory-path": "same as --inventory: the private path is not an operator choice",
    "--show-inventory": "the inventory is never printed, previewed, enumerated or summarised",
    "--print-inventory": "same as --show-inventory: there is no disclosure option",
    "--dataset": "the three datasets are locked; a selector would widen the retrieval",
    "--table": "same as --dataset: the tables are locked and are not an operator choice",
    "--window": "the window is a deterministic function of the clock, never supplied",
    "--from": "same as --window: no date bound is accepted",
    "--to": "same as --window: no date bound is accepted",
    "--page": "pagination is locked at two pages, the second a completeness probe",
    "--pages": "same as --page: the page count is locked and is not an operator choice",
    "--page-size": "same as --limit: the page size is locked per dataset",
    "--limit": "the page limits are locked per dataset and are not an operator choice",
    "--skip": "page offsets are generated from the locked page limits, never supplied",
    "--retry": "there is no provider retry; the request budget arithmetically forbids one",
    "--retries": "same as --retry: a failed request is a completed result, not a first try",
    "--full-history": "full history is not authorized and no code path can request it",
    "--full": "same as --full-history: no bulk retrieval is constructible",
    "--bulk": "no bulk or archive route exists to reach",
    "--archive": "same as --bulk: no archive route exists to reach",
    "--services-data": "Services Data export is not authorized and is not constructible",
    "--ingest": "ingestion is a separate, unauthorized decision",
    "--backfill": "backfill is a different acquisition mode and is not authorized",
    "--control": "CONTROL publication is deferred and forbidden; this writes LICENSED only",
    "--token": "no token is accepted, read, stored or bound by this command",
    "--output": "no local output file is written, and no path option exists",
    "--report": "this command publishes no report; assessment is a separate process",
}


class _AcquisitionAuthorization:
    """Proof that the operator flag was parsed. **Exactly one exists.**

    The shape the binding preflight arrived at after two corrections, for the same
    reasons. A ``bool`` would mean any importer could pass ``True``. An object
    carrying a module-private *mint field* would be **copyable**, and ``copy.copy``
    would manufacture a second bearer of the authority the capability exists to
    prevent.

    There is **no state to copy**: ``__slots__`` is empty, admission is identity
    against the single module-level instance, and every route that would produce a
    second object is closed. An ``object.__new__`` instance can still be built and is
    refused for the reason that matters -- it is not *this* object.

    This is not a claim about hostile runtime introspection: a process that can reach
    this module's private names already holds the singleton.
    """

    __slots__ = ()

    def __new__(cls) -> _AcquisitionAuthorization:
        """Refuse a second construction once the singleton exists."""
        if "_EMPIRICAL_AUTHORIZATION" in globals():
            raise TypeError("the empirical acquisition authorization is a singleton")
        return super().__new__(cls)

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass instance is a second bearer."""
        raise TypeError("the empirical acquisition authorization may not be subclassed")

    def __copy__(self) -> _AcquisitionAuthorization:
        """Refuse copying, so no copy operation yields an object at all."""
        raise TypeError("the empirical acquisition authorization may not be copied")

    def __deepcopy__(self, memo: object) -> _AcquisitionAuthorization:
        """Refuse deep copying, for the same reason."""
        raise TypeError("the empirical acquisition authorization may not be copied")

    def __reduce__(self) -> object:
        """Refuse pickling, which is copying with extra steps."""
        raise TypeError("the empirical acquisition authorization may not be pickled")


_EMPIRICAL_AUTHORIZATION: Final = _AcquisitionAuthorization()


def _is_authorized(candidate: object) -> bool:
    """Whether ``candidate`` **is** the one authorization this module holds.

    Identity, and nothing else. A type check plus a copyable field is what admitted a
    shallow copy in an earlier operator surface, and adding one back would invite it.
    """
    return candidate is _EMPIRICAL_AUTHORIZATION


class EmpiricalOutcome(StrEnum):
    """Every sentence this command may print. A fixed allowlist.

    Each is a fact about what the command did, safe in a public transcript. **None
    reports a qualification verdict, provider suitability, entitlement, a finding, a
    measurement or readiness** -- those are not facts this command establishes, and a
    word implying one would be read as permission.
    """

    REFUSED_NOT_AUTHORIZED = "empirical acquisition refused: not authorized"
    REFUSED_OPTION = "empirical acquisition refused: this option is not accepted"
    REFUSED_EXECUTION_CONTEXT = "empirical acquisition refused: execution context"
    REFUSED_INVENTORY = "empirical acquisition refused: the private inventory was refused"
    REFUSED_EXECUTION_IDENTITY = "empirical acquisition refused: execution identity"
    REFUSED_PROFILE = "empirical acquisition refused: the governed profile did not match"
    REFUSED_IDENTITY = "empirical acquisition refused: the AWS identity gate did not pass"
    REFUSED_LICENSED_BUCKET = "empirical acquisition refused: licensed configuration"
    # The member *name* trips the hardcoded-password heuristic; the value is an
    # allowlisted refusal sentence naming nothing.
    REFUSED_SECRET_IDENTIFIER = (
        "empirical acquisition refused: no usable secret identifier was resolved"  # noqa: S105
    )
    REFUSED_CREDENTIAL = "empirical acquisition refused: the credential contract refused"
    REFUSED_DEPENDENCY = "empirical acquisition refused: a local dependency was unavailable"
    REFUSED_PLAN = "empirical acquisition refused: the bounded plan was refused"
    REFUSED_UNCLASSIFIED = "empirical acquisition refused: unclassified"
    COMPLETED = "empirical acquisition completed"
    COMPLETED_PARTIAL = "empirical acquisition halted: the locator records a partial run"
    RUN_DEADLINE_EXHAUSTED = "empirical acquisition halted: the acquisition deadline was reached"
    # **The two occupied-name sentences say only that a name was occupied.** This
    # path performs no object read, so what holds the name is undetermined -- and a
    # sentence claiming the content was identical, different, adopted or resumable
    # would be a claim nothing established.
    BRONZE_NAME_OCCUPIED = "empirical acquisition halted: a publication name was occupied"
    LOCATOR_NOT_PUBLISHED = "empirical acquisition: the locator was not published"
    LOCATOR_STATE_UNKNOWN = "empirical acquisition: the locator publication was not verified"
    LOCATOR_NAME_OCCUPIED = "empirical acquisition: the locator name was occupied"


#: The exit status each outcome maps to. **Total, and checked by a test.**
#:
#: Only an addressable, complete acquisition is ``0``. A partial run and every
#: locator problem are non-zero, because none of them leaves the owner with evidence
#: an assessment could evaluate. There is no ``.get`` default and no ``else``: an
#: outcome added later by someone who did not run the totality test has no exit code
#: at all, which fails loudly rather than reporting success for something nobody
#: classified.
EXIT_STATUS: Final[dict[EmpiricalOutcome, int]] = {
    EmpiricalOutcome.COMPLETED: 0,
    EmpiricalOutcome.REFUSED_NOT_AUTHORIZED: 1,
    EmpiricalOutcome.REFUSED_OPTION: 2,
    EmpiricalOutcome.REFUSED_EXECUTION_CONTEXT: 3,
    EmpiricalOutcome.REFUSED_INVENTORY: 4,
    EmpiricalOutcome.REFUSED_EXECUTION_IDENTITY: 5,
    EmpiricalOutcome.REFUSED_PROFILE: 6,
    EmpiricalOutcome.REFUSED_IDENTITY: 7,
    EmpiricalOutcome.REFUSED_LICENSED_BUCKET: 8,
    EmpiricalOutcome.REFUSED_SECRET_IDENTIFIER: 9,
    EmpiricalOutcome.REFUSED_CREDENTIAL: 10,
    EmpiricalOutcome.REFUSED_DEPENDENCY: 11,
    EmpiricalOutcome.REFUSED_PLAN: 12,
    EmpiricalOutcome.REFUSED_UNCLASSIFIED: 13,
    EmpiricalOutcome.COMPLETED_PARTIAL: 14,
    EmpiricalOutcome.LOCATOR_NOT_PUBLISHED: 15,
    EmpiricalOutcome.LOCATOR_STATE_UNKNOWN: 16,
    EmpiricalOutcome.LOCATOR_NAME_OCCUPIED: 17,
    EmpiricalOutcome.RUN_DEADLINE_EXHAUSTED: 18,
    EmpiricalOutcome.BRONZE_NAME_OCCUPIED: 19,
}

#: How an acquisition status becomes a public outcome. **Total, and checked.**
_STATUS_OUTCOME: Final[dict[str, EmpiricalOutcome]] = {
    "COMPLETED": EmpiricalOutcome.COMPLETED,
    "PARTIAL": EmpiricalOutcome.COMPLETED_PARTIAL,
    "RUN_DEADLINE_EXHAUSTED": EmpiricalOutcome.RUN_DEADLINE_EXHAUSTED,
    "BRONZE_NAME_OCCUPIED": EmpiricalOutcome.BRONZE_NAME_OCCUPIED,
    "LOCATOR_NOT_PUBLISHED": EmpiricalOutcome.LOCATOR_NOT_PUBLISHED,
    "LOCATOR_STATE_UNKNOWN": EmpiricalOutcome.LOCATOR_STATE_UNKNOWN,
    "LOCATOR_NAME_OCCUPIED": EmpiricalOutcome.LOCATOR_NAME_OCCUPIED,
}


class EmpiricalQualificationError(Exception):
    """A refusal carrying exactly one allowlisted :class:`EmpiricalOutcome`.

    Raised ``from None`` everywhere, always. A backend exception quotes a secret name,
    an ARN or a bucket; a plan refusal can quote a subject; a provider error can carry
    a URL that *is* a credential, because the key travels in the query string. None of
    that may reach a traceback a person pastes into a chat.
    """

    def __init__(self, outcome: EmpiricalOutcome) -> None:
        """Bind the outcome. The message is the allowlisted sentence, nothing more."""
        if type(outcome) is not EmpiricalOutcome:  # pragma: no cover - type guard
            raise TypeError("an outcome must be an exact EmpiricalOutcome member")
        super().__init__(outcome.value)
        self.outcome = outcome


def _emit(outcome: EmpiricalOutcome) -> None:
    """Print one allowlisted sentence.

    Takes a vocabulary member, not a string, so there is no parameter through which a
    bucket, a subject, a URL, a digest or an exception could arrive.
    """
    print(outcome.value)


def _emit_counts(counts: Any) -> None:
    """Print the operation accounting. **Numbers only, and no identifier.**

    Every value is an integer this run observed. There is no key, digest, subject,
    bucket, account or finding in the output, and no branch that could add one.
    """
    print(f"  provider requests: {counts.provider_request_count}")
    print(f"  put_object: {counts.put_object_count}")
    print(f"  conditional head_object: {counts.head_object_count}")
    print(f"  object-byte get_object: {counts.get_object_count}")
    print(f"  listing operations: {counts.list_operation_count}")
    print(f"  CONTROL operations: {counts.control_operation_count}")
    print(f"  total S3 operations: {counts.total_s3_operations}")


def running_under_automation(env: Mapping[str, str], modules: Mapping[str, object]) -> str | None:
    """Why this must not run here, or ``None``.

    Provider requests and durable licensed acquisitions are owner actions. Under
    ``pytest`` the tests would perform them; in CI the transcript is a log; on a plain
    import nobody asked for anything at all. Each is refused before the inventory is
    even read.

    The check is on the *caller's* mapping arguments rather than on ambient state, so
    the tests can drive every branch without setting a real environment variable or
    importing a real module.
    """
    if "pytest" in modules:
        return "pytest"
    for name in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "BUILD_NUMBER"):
        if env.get(name, "").strip():
            return name
    return None


class SystemClock:
    """The wall clock, in the one place a real run is allowed to read one.

    The runtime takes its instant by injection precisely so it never reads an ambient
    clock; this is the operator boundary handing it one, and the tests hand it a fixed
    clock instead.
    """

    def now(self) -> Any:
        """The current UTC instant."""
        from datetime import UTC, datetime

        return datetime.now(UTC)


def run_empirical_qualification(
    *,
    authorization: object,
    execution_id: str | None,
    env: Mapping[str, str],
    modules: Mapping[str, object],
    load_inventory: Callable[[], Any],
    profile_of: Callable[[], str],
    identity_gate: Callable[[], str | None],
    resolve_licensed_bucket: Callable[[], str],
    secret_id_source: Callable[[], str],
    secrets_client_factory: Callable[[], Any],
    s3_client_factory: Callable[[], Any],
    transport_factory: Callable[[], Any],
    clock: Any,
    monotonic: Callable[[], float],
    sleeper: Callable[[float], None],
) -> tuple[EmpiricalOutcome, Any]:
    """Bind the private dependencies and perform **one** bounded acquisition.

    Every stage is a parameter, which is what makes this testable without AWS and what
    keeps the ambient environment out of it: nothing here reads ``os.environ``, opens
    a file, constructs a client or resolves a name. The real factories are supplied by
    :func:`main`.

    ``authorization`` is a capability minted by :func:`main` after the exact operator
    flag parses. It is **not** a boolean: a boolean is the one value every caller
    already has.

    ``secret_id_source`` is a zero-argument callable rather than a value, and it is
    invoked **once**, after every gate above it has passed. A private identifier must
    not be resolved on a path that is going to refuse.

    ``monotonic`` and ``sleeper`` are the acquisition deadline's clock and the
    pacer's sleep. They are injected as a pair and from one source, so a test drives
    the whole 1,800-second budget without waiting for any of it. ``monotonic`` must
    be a **monotonic** source: ``clock`` above is the calendar, it supplies the
    retrieval instants and the locator's run timestamps, and **no deadline
    arithmetic reads it**.

    Returns:
        One allowlisted outcome and the observed operation accounting. A halted run
        and a failed locator are **returned, not raised**, because a caller needs the
        accounting rather than an exception that discards it.

    Raises:
        EmpiricalQualificationError: one allowlisted :class:`EmpiricalOutcome`. The
            cause is always suppressed.
    """
    # 1. Authorization. A capability this module minted after parsing the flag.
    if not _is_authorized(authorization):
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_NOT_AUTHORIZED) from None

    # 2. Execution context. Refused before anything is read or resolved.
    if running_under_automation(env, modules) is not None:
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_EXECUTION_CONTEXT) from None

    # 3. The owner-only inventory, before any AWS or provider dependency. A private
    #    input that is missing or malformed costs nothing to discover here.
    try:
        inventory = load_inventory()
    except Exception:
        # The loader's refusals are already closed and value-free, and this converts
        # them anyway: only the allowlisted outcome may reach a transcript.
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_INVENTORY) from None

    if type(execution_id) is not str:
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_EXECUTION_IDENTITY) from None

    # 4. The profile, before any AWS call is attempted at all.
    try:
        profile = profile_of()
    except Exception:
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_PROFILE) from None
    if profile != EXPECTED_PROFILE:
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_PROFILE) from None

    # 5. The account identity gate. Its reason string can name an account, so it is
    #    consumed as a pass/fail and never printed.
    try:
        reason = identity_gate()
    except Exception:
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_IDENTITY) from None
    if reason is not None:
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_IDENTITY) from None

    # 6. The licensed bucket, from governed state. Never the control one.
    try:
        licensed_bucket = resolve_licensed_bucket()
    except Exception:
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_LICENSED_BUCKET) from None

    # 7. The secret identifier -- the first stage that touches anything private, and
    #    only now that every gate above has passed.
    try:
        from kalpamani.data.ingest.sharadar.secrets import is_usable_secret_identifier
    except Exception:
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_DEPENDENCY) from None
    try:
        secret_id = secret_id_source()
    except Exception:
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_SECRET_IDENTIFIER) from None
    if not is_usable_secret_identifier(secret_id):
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_SECRET_IDENTIFIER) from None

    # 8. The credential. A missing SDK is a local dependency failure and never a
    #    credential claim -- the correction the failure-boundary ADR exists for.
    try:
        secrets_client = secrets_client_factory()
    except Exception:
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_DEPENDENCY) from None
    try:
        from kalpamani.data.ingest.sharadar.secrets import sharadar_credential_from_secret
    except Exception:
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_DEPENDENCY) from None
    try:
        credential = sharadar_credential_from_secret(client=secrets_client, secret_id=secret_id)
    except Exception:
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_CREDENTIAL) from None

    # 9. The remaining injected dependencies.
    if not callable(monotonic) or not callable(sleeper):
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_DEPENDENCY) from None
    try:
        from kalpamani.data.qualify.sharadar.acquisition import run_empirical_acquisition

        s3_client = s3_client_factory()
        transport = transport_factory()
    except Exception:
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_DEPENDENCY) from None

    # 10-13. The offline preflight, then the armed acquisition phase: the sequential
    #        requests, the Bronze writes and the one locator, all inside the
    #        composition that enforces their order and holds them to one deadline.
    #        The pacer is built in there, from ``monotonic``, so its sleep is
    #        admitted against the same budget.
    try:
        result = run_empirical_acquisition(
            credential=credential,
            transport=transport,
            monotonic=monotonic,
            sleeper=sleeper,
            s3_client=s3_client,
            licensed_bucket=licensed_bucket,
            clock=clock,
            inventory=inventory,
            execution_id=execution_id,
        )
    except Exception as failure:
        # A plan refusal can quote a subject, a provider error can carry a URL that is
        # a credential, and a store error can quote the bucket. None survives.
        if type(failure).__name__ == "EmpiricalPlanError":
            raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_PLAN) from None
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_UNCLASSIFIED) from None

    # 14. One closed outcome, derived from the composition's own status.
    name = getattr(result.status, "name", None)
    if type(name) is not str or name not in _STATUS_OUTCOME:
        raise EmpiricalQualificationError(EmpiricalOutcome.REFUSED_UNCLASSIFIED) from None
    return _STATUS_OUTCOME[name], result.counts


def build_parser() -> argparse.ArgumentParser:
    """The executable CLI surface. **Exactly two arguments, and no aliases.**

    Subjects, datasets, windows, pages, limits, retry policy, response ceilings,
    destination and acquisition mode are locked in code. An operator who could choose
    them could choose a retrieval nobody reviewed.
    """
    parser = argparse.ArgumentParser(
        prog="sharadar_empirical_qualification",
        description=(
            "One bounded private empirical Sharadar acquisition. Refused by default. "
            "Subjects come from the owner-only inventory; every other value is locked."
        ),
    )
    parser.add_argument(
        AUTHORIZATION_FLAG,
        dest="authorization_flag_present",
        action="store_true",
        help="authorize ONE bounded empirical acquisition, and nothing else",
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

    Matched on the option token, so ``--subject=NAME`` is refused by the same entry as
    ``--subject`` and the value is never echoed.
    """
    for token in argv:
        name = token.split("=", 1)[0]
        if name in REFUSED_OPTIONS:
            return name
    return None


def main(argv: list[str] | None = None) -> int:
    """Parse, refuse, or perform one bounded acquisition. Returns a command status.

    ``0`` means the acquisition completed and its locator is addressable; non-zero
    means the command refused or the evidence is not addressable. **Neither is a
    verdict** about the provider, the data, the schema, P1-P9, or whether a further
    run should happen.

    **The real factories are constructed here and only here**, inside the authorized
    branch. **This function has never been run**: implementing it was not authorization
    to use it, and each of Run A, Run B and the assessment run remains a separate
    written authorization that has not been given.
    """
    argv = list(sys.argv[1:] if argv is None else argv)

    refused = _refused_option(argv)
    if refused is not None:
        _emit(EmpiricalOutcome.REFUSED_OPTION)
        print(f"  {refused}: {REFUSED_OPTIONS[refused]}")
        return EXIT_STATUS[EmpiricalOutcome.REFUSED_OPTION]

    parsed = build_parser().parse_args(argv)

    if not parsed.authorization_flag_present:
        # The default path. Nothing above this line looked anything up, constructed
        # anything, or opened anything.
        _emit(EmpiricalOutcome.REFUSED_NOT_AUTHORIZED)
        print(f"  pass {AUTHORIZATION_FLAG} to authorize one bounded acquisition")
        print("  that flag authorizes exactly one run, never a second")
        return EXIT_STATUS[EmpiricalOutcome.REFUSED_NOT_AUTHORIZED]

    # Imported inside the authorized branch, like every other real dependency, so
    # the default refusal path still touches nothing. ``time.monotonic`` is the
    # deadline's clock and ``time.sleep`` is the pacer's: neither is a calendar
    # source, and the deadline must never be able to move because a calendar did.
    import os
    import time

    try:
        outcome, counts = run_empirical_qualification(
            # Handed over here, and only here: the flag has parsed.
            authorization=_EMPIRICAL_AUTHORIZATION,
            execution_id=parsed.execution_id,
            env=os.environ,
            modules=sys.modules,
            load_inventory=_private_inventory,
            profile_of=_ambient_profile,
            identity_gate=_governed_identity_gate,
            resolve_licensed_bucket=_governed_licensed_bucket,
            secret_id_source=_environment_secret_id,
            secrets_client_factory=_secrets_client,
            s3_client_factory=_s3_client,
            transport_factory=_transport,
            clock=SystemClock(),
            monotonic=time.monotonic,
            sleeper=time.sleep,
        )
    except EmpiricalQualificationError as refusal:
        _emit(refusal.outcome)
        return EXIT_STATUS[refusal.outcome]

    _emit(outcome)
    _emit_counts(counts)
    return EXIT_STATUS[outcome]


def _private_inventory() -> Any:
    """The owner-only inventory, from the application-fixed private path.

    No path is accepted, printed or logged, and the loaded inventory is never
    rendered: it goes straight into the plan builder as typed subjects.
    """
    from kalpamani.data.qualify.sharadar.inventory import load_private_inventory

    return load_private_inventory()


def _ambient_profile() -> str:
    """The pinned profile from the process environment. Read, never printed."""
    import os

    return os.environ.get("AWS_PROFILE", "")


def _environment_secret_id() -> str:
    """The secret identifier, from one fixed environment-variable name.

    Called only on the authorized path, after every gate above it has passed. The
    *name* is a constant and is not a secret; the *value* is, and it is never printed,
    logged, returned to a caller or included in a refusal.

    ``os`` is imported inside the body, so an ordinary import of this module -- and
    every refusal path above -- performs no environment lookup at all.

    Raises:
        LookupError: if the variable is unset or blank. Converted by the caller into
            the closed ``REFUSED_SECRET_IDENTIFIER`` outcome, which names nothing.
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
    """An S3 client, pinned to the governed region, with **retries disabled**.

    The deadline's per-operation ceiling assumes one invocation is one attempt. The
    SDK's default retry mode does not: it would turn one ``PutObject`` into several
    attempts, each with its own connect and read timeouts, and the ceiling would then
    bound a fraction of what the operation could actually take. So the configuration
    is explicit and finite -- ``total_max_attempts`` of one in ``standard`` mode, an
    explicit connect timeout and an explicit read timeout -- and it comes from
    :func:`~kalpamani.data.qualify.sharadar.plan.s3_client_config_kwargs`, the same
    module the ceiling is derived in, so the two cannot drift apart.

    **``total_max_attempts``, not ``max_attempts``.** Botocore's ``max_attempts``
    counts the retries that follow the first request, so one there would permit a
    second attempt; ``total_max_attempts`` counts every attempt, so one there is one
    request. Only the second spelling makes the ceiling above true.

    Adaptive and legacy retry modes are not reachable from here: the mode is a
    compiled constant and there is no parameter to change it.
    """
    import boto3
    from botocore.config import Config

    from kalpamani.data.qualify.sharadar.plan import s3_client_config_kwargs

    return boto3.client(
        "s3",
        region_name=EXPECTED_REGION,
        config=Config(**s3_client_config_kwargs()),  # type: ignore[arg-type]
    )


def _transport() -> Any:
    """The origin-pinned provider transport, at this package's response ceiling.

    The ceiling is passed explicitly because **the transport is what stops reading**:
    a plan may declare a smaller limit, but only the transport can enforce one.
    """
    from kalpamani.data.ingest.sharadar.transport import UrllibTransport
    from kalpamani.data.qualify.sharadar.plan import MAX_RESPONSE_BYTES

    return UrllibTransport(max_response_bytes=MAX_RESPONSE_BYTES)


#: The public surface, stated so it can be checked rather than inferred.
#:
#: The authorization capability and its class are absent, deliberately: an exported
#: capability is a public constructor by another name.
__all__ = [
    "AUTHORIZATION_FLAG",
    "EXIT_STATUS",
    "REFUSED_OPTIONS",
    "EmpiricalOutcome",
    "EmpiricalQualificationError",
    "build_parser",
    "main",
    "run_empirical_qualification",
    "running_under_automation",
]


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    sys.exit(main())
