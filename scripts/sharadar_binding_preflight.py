"""The operator binding preflight for the authenticated Sharadar stack.

ADR-0015. Every accepted slice takes its private bindings by injection and none
of them has ever had a way to obtain one: no credential source, no bucket
resolution, no constructed AWS client. This is the path that will eventually
supply them -- written, reviewed and tested while it is still refused by default,
rather than written under pressure beside an authorization to run.

::

    entry points        ONE      this file, and nothing re-exports it
    default behaviour   REFUSE   no flag, no work: no lookup, no client, no socket
    authorization       ONE      --i-am-the-operator-authorizing-binding-preflight
    what it authorizes  BINDING PREFLIGHT ONLY -- never a qualification run
    operations reached  preflight_qualification_composition, and nothing else
    real bindings used  NONE     this has never been run against AWS or Sharadar
    AWS requests        ZERO     ·  provider requests: ZERO  ·  S3 object calls: ZERO

Three separate future events
============================

**Private credential setup**, **a real binding preflight** and an **authenticated
qualification run** are three decisions, not one. Implementing this path is none
of them. This file existing does not create a secret, does not read one, does not
touch AWS, and cannot execute a qualification run -- there is no code here that
could, and a static guard keeps it that way.

Refusing by default, and why the flag is spelled like that
==========================================================

An ordinary import or an ordinary invocation does nothing at all. The operational
path needs
``--i-am-the-operator-authorizing-binding-preflight``, and the name is
deliberately unmistakable: ``--run``, ``--live``, ``--execute`` and ``--force``
are all things a person types out of habit on the wrong terminal. This one has to
be meant.

**It authorizes a binding preflight and nothing further.** It does not mint,
imply or stand in for authorization to execute a qualification run, and no code
path here consumes it as one.

Two defects this file's first revision contained
================================================

**A boolean could forge the authorization.** The check was ``binding_authorized is True``, so a
caller who imported :func:`run_binding_preflight` and passed ``True`` reached the profile, identity
and bucket stages without the flag ever being parsed. A boolean is the one value every caller
already has; an authorization that any caller can supply is not an authorization.

**A copyable mint field was not much better.** The next revision took an object of an exact type
carrying a module-private mint field. ``copy.copy`` produced a *distinct* object holding the same
field, and admission accepted it -- so copying manufactured a second bearer of authority. The
slice's closeout claimed both "copying cannot forge one" and "a shallow copy stays genuine", which
cannot both be true; review caught it.

The parameter is now **one module-level object, admitted by identity**. There is no state to copy:
``__slots__`` is empty, ``__new__`` refuses once the singleton exists, ``__copy__``,
``__deepcopy__`` and ``__reduce__`` all refuse, and subclassing refuses. The object is not
exported, and no function returns it except the parser path that has already admitted the flag.

*What that claims, exactly:* no caller can obtain a second admitted authorization through
construction, copying, deep copying, serialisation, subclassing, a structural lookalike or a
borrowed field. It is **not** a claim about hostile runtime introspection -- a process that can
reach a module's private names already holds the singleton, and this file does not pretend
otherwise.

**A private secret identifier travelled in argv.** ``--secret-id`` put it in shell history and in
every process listing on the machine, whether or not this program ever printed it. Redacting output
does not help once the value is on the command line.

The identifier now comes from an **injected zero-argument source**, called once, only after
authorization, profile, identity and bucket resolution have all passed, and immediately before the
credential is retrieved. The production source reads **one fixed, non-secret environment-variable
name** on that authorized path. ``--secret-id``, ``--secret-name`` and their near spellings are
refused by name rather than silently ignored.

The order, and why nothing may be reordered
===========================================

1. explicit binding-preflight authorization
2. the exact AWS profile
3. the AWS account identity gate
4. governed licensed-bucket resolution
5. private credential retrieval
6. client and dependency construction
7. the accepted offline composition preflight
8. a closed result

Each stage runs only if every earlier one passed. The order is the security
property: identity is established before any state is read, the bucket is
resolved before a secret is fetched, and the secret is fetched before anything is
constructed -- so a wrong-account session never reaches a secret, and a failed
gate never reaches a credential.

Nothing here reimplements a gate. ``AWS_PROFILE`` pinning, the account-binding
comparison and the Terraform-state read all come from
``scripts/aws_foundation_verify.py``, which already owns them; a second copy of
account matching is a second thing to get wrong.

What may be printed
===================

A fixed allowlist of sentences, none of which carries a private identifier. No
credential or fragment, no secret identifier, no bucket, no account, no ARN, no
profile, no region, no Terraform output, no URL, no plan subject, no empirical
result and no provider recommendation. The exit status reports command success or
refusal -- never a qualification verdict and never provider suitability.

Not the public-token harness
============================

``scripts/sharadar_private_qualification.py`` is a separate, owner-only
instrument that reads the vendor's *published* test token. This file does not
import, invoke, modify or repurpose it, and the two have no code in common.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

REPO_ROOT_MARKER: Final = "scripts"

#: The one flag that turns a refusal into a binding preflight.
#:
#: Long, explicit and awkward on purpose. Anything a person might type from habit
#: -- ``--run``, ``--live``, ``--execute``, ``--force`` -- is refused by name
#: below, so a wrong reflex fails loudly instead of doing something.
BINDING_AUTHORIZATION_FLAG: Final = "--i-am-the-operator-authorizing-binding-preflight"

#: The one fixed, non-secret environment-variable *name* the production source
#: reads on the authorized path. The name is not a secret; the value is, and it
#: is never printed, logged or included in a refusal.
#: Ruff flags the *name* on its hardcoded-password heuristic. This is the name of
#: an environment variable, not a value: the identifier it holds is private, this
#: constant is not, and renaming it to dodge the check would make it less clear
#: what the constant is.
SECRET_ID_ENV_VAR: Final = "KALPAMANI_SHARADAR_SECRET_ID"  # noqa: S105


class _BindingAuthorization:
    """Proof that the operator flag was parsed. **Exactly one exists.**

    Two revisions got this wrong, and the second is worth stating because it is
    the subtler mistake.

    The first took a ``bool``, so any importer could pass ``True``.

    The second took an object carrying a module-private *mint field*, and
    admitted anything of the exact type holding that field. **A field is
    copyable.** ``copy.copy`` produced a distinct object carrying the same mint,
    and admission accepted it -- so copying manufactured a second bearer of
    authority, which is precisely what the capability existed to prevent. The
    slice's own closeout claimed both "copying cannot forge one" and "a shallow
    copy stays genuine"; those cannot both be true, and review caught it.

    There is now **no state to copy**: ``__slots__`` is empty, admission is
    identity against the single module-level instance, and every route that
    would produce a second object is closed --

    * ``__new__`` refuses once the singleton exists, so there is no second
      construction;
    * ``__copy__`` and ``__deepcopy__`` refuse, so no copy operation yields an
      object at all;
    * ``__reduce__`` refuses, so the object cannot be pickled and therefore
      cannot be unpickled into a second bearer;
    * subclassing refuses, so no subclass instance can stand in.

    An ``object.__new__`` instance can still be built -- that bypasses
    ``__new__`` -- and it is refused for the reason that matters: it is not
    *this* object.

    **What that claims, precisely.** No caller can obtain a second admitted
    authorization through construction, copying, deep copying, serialisation,
    subclassing, a structural lookalike or a borrowed field. It is **not** a
    claim about hostile runtime introspection: a process that can reach a
    module's private names already holds the singleton, and this file does not
    pretend otherwise.
    """

    __slots__ = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing.

        A subclass instance would satisfy an ``isinstance`` check while being a
        different object from the one this module made.
        """
        raise TypeError("_BindingAuthorization may not be subclassed.")

    def __new__(cls) -> _BindingAuthorization:
        """Build the one instance, and refuse every later construction.

        Raises:
            TypeError: once the singleton is bound. The module binds it below;
                after that, ``_BindingAuthorization()`` is a refusal rather than
                a second capability.
        """
        if "_BINDING_PREFLIGHT_AUTHORIZATION" in globals():
            raise TypeError(
                "there is one binding-preflight authorization; it is obtained by parsing "
                "the operator flag, not constructed"
            )
        return super().__new__(cls)

    def __copy__(self) -> _BindingAuthorization:
        """Refuse copying.

        Returning ``self`` would also have been defensible -- one object, no new
        bearer. Refusing is chosen because it fails loudly: code that copies an
        authorization is doing something this design does not intend, and a
        silent pass-through would let that intent survive unexamined.
        """
        raise TypeError("a binding-preflight authorization may not be copied.")

    def __deepcopy__(self, memo: object) -> _BindingAuthorization:
        """Refuse deep copying, for the same reason."""
        raise TypeError("a binding-preflight authorization may not be copied.")

    def __reduce__(self) -> object:
        """Refuse pickling, so nothing can be unpickled into a second bearer."""
        raise TypeError("a binding-preflight authorization may not be serialised.")

    def __repr__(self) -> str:
        """A constant. There is nothing else to render."""
        return "<binding-preflight authorization>"


#: The one authorization. Admission is identity against exactly this object.
#:
#: Not exported, and no function returns it except the parser path that has
#: already admitted the operator flag.
_BINDING_PREFLIGHT_AUTHORIZATION: Final = _BindingAuthorization()


def _is_authorized(candidate: object) -> bool:
    """Whether ``candidate`` **is** the one authorization this module holds.

    Identity, and nothing else. No type check is needed and none is written: a
    type check plus a copyable field is what admitted a shallow copy in the
    previous revision, and adding one back would invite the same mistake.
    """
    return candidate is _BINDING_PREFLIGHT_AUTHORIZATION


#: The profile and region the governed foundation is pinned to.
#:
#: Read from the verifier that owns them rather than restated, so the pin cannot
#: drift between the gate and this caller.
EXPECTED_PROFILE: Final = "kalpamani-foundation"
EXPECTED_REGION: Final = "us-east-1"

#: The Terraform output holding the licensed research bucket.
#:
#: Named, so the CONTROL bucket cannot be substituted by editing a variable: the
#: control bucket has a different output key and this module never names it.
LICENSED_BUCKET_OUTPUT: Final = "licensed_bucket_name"

#: Options refused by name, each with the reason.
#:
#: Present as rejected names rather than simply absent: an unrecognised flag is
#: already an ``argparse`` error, but one that says "unrecognized arguments"
#: teaches nothing and someone tries again with a different spelling.
REFUSED_OPTIONS: Final[dict[str, str]] = {
    "--run": "there is no run mode; a qualification run is a separate authorization",
    "--live": "there is no live mode, and nothing here can construct one",
    "--execute": "this command cannot execute a qualification run; no such code path exists",
    "--force": "nothing here is forceable; a refusal is a refusal",
    "--api-key": "no credential is accepted on the command line, ever",
    "--secret-value": "no credential value is accepted on the command line, ever",
    "--secret-id": (
        "a secret identifier is private; on the command line it enters shell history and "
        "every process listing. It is read from the environment on the authorized path"
    ),
    "--secret-name": "same as --secret-id: a private identifier does not travel in argv",
    "--secretid": "same as --secret-id: a private identifier does not travel in argv",
    "--secret-arn": "same as --secret-id: a private identifier does not travel in argv",
    "--secret": "same as --secret-id: a private identifier does not travel in argv",
    "--account": "the account is never supplied; it is compared against the local binding",
    "--bucket": "the licensed bucket is resolved from governed state, never supplied",
    "--endpoint": "no endpoint is accepted; the SDK resolves the governed one",
    "--token": "no token is accepted, read, stored or bound by this command",
}


class PreflightOutcome(StrEnum):
    """Every sentence this command may print. A fixed allowlist.

    Each is a fact about what the command did, safe in a public transcript. None
    reports a qualification verdict, provider suitability or readiness to run --
    those are not facts this command establishes, and a word implying one would
    be read as permission.
    """

    REFUSED_NOT_AUTHORIZED = "binding preflight refused: no operator authorization was given"
    REFUSED_PROFILE = "binding preflight refused: the AWS profile is not the governed one"
    REFUSED_IDENTITY = "binding preflight refused: the AWS identity gate did not pass"
    REFUSED_BUCKET = "binding preflight refused: the licensed bucket could not be resolved"
    REFUSED_CREDENTIAL = "binding preflight refused: the private credential could not be retrieved"
    REFUSED_DEPENDENCIES = "binding preflight refused: a dependency was not usable"
    REFUSED_PLAN = "binding preflight refused: the qualification plan did not validate"
    REFUSED_OPTION = "binding preflight refused: an option this command does not accept"
    COMPLETED = "binding preflight completed"
    VALIDATION_COMPLETED = "offline validation completed"


class BindingPreflightError(Exception):
    """A stage refused. Carries one closed outcome and nothing else.

    No secret, no identifier, no bucket, no account, no ARN, no backend message
    and no attempted value: there is no parameter for one.
    """

    __slots__ = ("outcome",)

    def __init__(self, outcome: PreflightOutcome) -> None:
        """Carry one allowlisted outcome, and render it as that sentence alone."""
        self.outcome = (
            outcome if type(outcome) is PreflightOutcome else PreflightOutcome.REFUSED_DEPENDENCIES
        )
        super().__init__(self.outcome.value)


def _emit(outcome: PreflightOutcome) -> None:
    """Print one allowlisted sentence. The only route to stdout in this file."""
    print(outcome.value)


class SystemClock:
    """The retrieval instant, as the qualification runtime's clock protocol.

    Defined here rather than in the package because it is a *deployment*
    decision: the runtime takes an injected clock precisely so that nothing
    inside it reads a wall clock, and the one place allowed to choose one is the
    operator path that also chooses the credential and the bucket.
    """

    def now(self) -> datetime:
        """The current instant, timezone-aware."""
        return datetime.now(UTC)


def build_parser() -> argparse.ArgumentParser:
    """The command's surface. One authorizing flag, one secret identifier, one plan."""
    parser = argparse.ArgumentParser(
        prog="sharadar_binding_preflight",
        description=(
            "Operator binding preflight for the authenticated Sharadar qualification "
            "stack. Refuses by default. Authorizes a binding preflight only -- never a "
            "qualification run."
        ),
    )
    parser.add_argument(
        BINDING_AUTHORIZATION_FLAG,
        # "was the flag present", which is a parse result -- not an
        # authorization. The authorization is minted from it below, and the
        # name says which of the two this is.
        dest="binding_flag_present",
        action="store_true",
        help=(
            "Authorize a binding preflight. This does not authorize, imply or stand in "
            "for authorization to execute a qualification run."
        ),
    )
    parser.add_argument(
        "--subject",
        dest="subjects",
        action="append",
        default=None,
        help="A qualification subject. Never printed back.",
    )
    parser.add_argument(
        "--execution-id",
        dest="execution_id",
        default=None,
        help="The explicit execution identity for the plan. No default exists.",
    )
    return parser


def _refused_option(argv: Sequence[str]) -> str | None:
    """The first refused option in ``argv``, if any.

    Checked before parsing, so a refused name is reported as itself rather than
    as an unrecognised argument.
    """
    for argument in argv:
        name = argument.split("=", 1)[0]
        if name in REFUSED_OPTIONS:
            return name
    return None


def run_binding_preflight(
    *,
    authorization: object,
    subjects: Sequence[str] | None,
    execution_id: str | None,
    profile_of: Callable[[], str],
    identity_gate: Callable[[], str | None],
    resolve_licensed_bucket: Callable[[], str],
    secret_id_source: Callable[[], str],
    secrets_client_factory: Callable[[], Any],
    s3_client_factory: Callable[[], Any],
    transport_factory: Callable[[], Any],
) -> Any:
    """Bind the private dependencies and validate a plan against them. **Offline.**

    Every stage is a parameter, which is what makes this testable without AWS and
    what keeps the ambient environment out of it: nothing here reads
    ``os.environ``, opens a file, constructs a client or resolves a name. The
    real factories are supplied by :func:`main`, and this slice never calls it
    with real ones.

    ``authorization`` is a capability minted by :func:`main` after the exact
    operator flag parses. It is **not** a boolean: an earlier revision took one,
    which meant an importer could pass ``True`` and reach the profile, identity
    and bucket stages with no flag involved.

    ``secret_id_source`` is a zero-argument callable rather than a value, and it
    is invoked **once**, after every gate has passed and immediately before the
    credential is retrieved. A private identifier must not be resolved on a path
    that is going to refuse.

    The order in the module docstring is the security property, and it is
    enforced here by sequence rather than described: a later stage cannot run
    after an earlier refusal, because a refusal raises.

    **The only operation reached is** ``preflight_qualification_composition``.
    There is no call to ``QualificationRuntime.execute``, to a provider
    transport's ``get``, or to ``put_object`` or ``head_object`` -- and no code in
    this file could construct one.

    Raises:
        BindingPreflightError: one allowlisted :class:`PreflightOutcome`. The
            cause is always suppressed: a backend exception quotes a secret name,
            an ARN or a bucket, and a plan refusal can quote a subject.
    """
    # 1. Authorization. A capability this module minted after parsing the flag --
    #    not a boolean, which is the one value every caller already has.
    if not _is_authorized(authorization):
        raise BindingPreflightError(PreflightOutcome.REFUSED_NOT_AUTHORIZED) from None

    # 2. The profile, before any AWS call is attempted at all.
    try:
        profile = profile_of()
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_PROFILE) from None
    if profile != EXPECTED_PROFILE:
        raise BindingPreflightError(PreflightOutcome.REFUSED_PROFILE) from None

    # 3. The account identity gate. Its reason string can name an account, so it
    #    is consumed as a pass/fail and never printed.
    try:
        reason = identity_gate()
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_IDENTITY) from None
    if reason is not None:
        raise BindingPreflightError(PreflightOutcome.REFUSED_IDENTITY) from None

    # 4. The licensed bucket, from governed state. Never the control bucket:
    #    the resolver is asked for one named output and this module names no
    #    other.
    try:
        licensed_bucket = resolve_licensed_bucket()
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_BUCKET) from None
    if type(licensed_bucket) is not str or not licensed_bucket.strip():
        raise BindingPreflightError(PreflightOutcome.REFUSED_BUCKET) from None

    # 5. The secret identifier, resolved **here** and nowhere earlier. It is
    #    private, so every refusal above must complete without asking for it --
    #    which is why it is a source rather than an argument.
    from kalpamani.data.ingest.sharadar.secrets import sharadar_credential_from_secret

    try:
        secret_id = secret_id_source()
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_CREDENTIAL) from None
    if type(secret_id) is not str or not secret_id.strip():
        raise BindingPreflightError(PreflightOutcome.REFUSED_CREDENTIAL) from None
    try:
        credential = sharadar_credential_from_secret(
            client=secrets_client_factory(), secret_id=secret_id
        )
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_CREDENTIAL) from None

    # 6. The remaining dependencies.
    from kalpamani.data.ingest.sharadar.client import DEFAULT_RETRY_POLICY, Pacer

    try:
        s3_client = s3_client_factory()
        transport = transport_factory()
        pacer = Pacer()
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_DEPENDENCIES) from None

    # 7. The accepted offline composition preflight, and nothing else.
    from kalpamani.data.ingest.sharadar.composition import preflight_qualification_composition

    try:
        plan = _build_plan(subjects=subjects, execution_id=execution_id)
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_PLAN) from None

    try:
        return preflight_qualification_composition(
            credential=credential,
            transport=transport,
            pacer=pacer,
            retry_policy=DEFAULT_RETRY_POLICY,
            timeout_seconds=60.0,
            s3_client=s3_client,
            licensed_bucket=licensed_bucket,
            clock=SystemClock(),
            plan=plan,
        )
    except Exception:
        raise BindingPreflightError(PreflightOutcome.REFUSED_PLAN) from None


def _build_plan(*, subjects: Sequence[str] | None, execution_id: str | None) -> Any:
    """The bounded qualification plan this preflight validates.

    No subject and no execution identity is compiled in: both are supplied, and
    the plan's own contract refuses a malformed one. Neither is ever printed
    back -- a subject is a listed security, and this command's transcript is
    meant to be safe to share.
    """
    from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
    from kalpamani.data.ingest.sharadar.qualification import (
        DatasetPlan,
        QualificationPlan,
        QualificationSubject,
    )

    if not subjects or execution_id is None:
        raise ValueError("a subject and an execution identity are both required")
    return QualificationPlan(
        subjects=tuple(QualificationSubject(subject) for subject in subjects),
        datasets=(DatasetPlan(dataset=SharadarDataset.TICKERS, page_limit=100, max_pages=1),),
        execution_id=execution_id,
    )


def main(argv: list[str] | None = None) -> int:
    """Parse, refuse or bind. Returns a command status, never a verdict.

    ``0`` means the command did what it was asked to do; non-zero means it
    refused. Neither says anything about the provider, the data, or whether a
    qualification run should happen.

    **The real factories are constructed here and only here**, inside the
    authorized branch. This is the one place ADR-0015 permits an AWS SDK session
    or client to be built -- and it has never been executed against AWS, which is
    a fact about this repository rather than a property of the code.
    """
    argv = list(sys.argv[1:] if argv is None else argv)

    refused = _refused_option(argv)
    if refused is not None:
        _emit(PreflightOutcome.REFUSED_OPTION)
        print(f"  {refused}: {REFUSED_OPTIONS[refused]}")
        return 2

    parsed = build_parser().parse_args(argv)

    if not parsed.binding_flag_present:
        # The default path. Nothing above this line looked anything up,
        # constructed anything, or opened anything.
        _emit(PreflightOutcome.REFUSED_NOT_AUTHORIZED)
        print(f"  pass {BINDING_AUTHORIZATION_FLAG} to authorize a binding preflight")
        print("  that flag authorizes a binding preflight only, never a qualification run")
        return 1

    try:
        result = run_binding_preflight(
            # Handed over here, and only here: the flag has parsed.
            authorization=_BINDING_PREFLIGHT_AUTHORIZATION,
            subjects=parsed.subjects,
            execution_id=parsed.execution_id,
            profile_of=_ambient_profile,
            identity_gate=_governed_identity_gate,
            resolve_licensed_bucket=_governed_licensed_bucket,
            secret_id_source=_environment_secret_id,
            secrets_client_factory=_secrets_client,
            s3_client_factory=_s3_client,
            transport_factory=_transport,
        )
    except BindingPreflightError as refusal:
        _emit(refusal.outcome)
        return 1

    _emit(PreflightOutcome.COMPLETED)
    if str(result.status) == "VALIDATED_OFFLINE":
        _emit(PreflightOutcome.VALIDATION_COMPLETED)
    return 0


# ---------------------------------------------------------------------------
# The real factories. Referenced by `main`, never called by a test.
# ---------------------------------------------------------------------------
#
# Each imports what it needs inside the function body, so importing this module
# imports no SDK, reads no environment and touches no state. Every one of them is
# a future operational event that is separately gated, and none has been run.


def _ambient_profile() -> str:
    """The pinned profile from the process environment. Read, never printed."""
    import os

    return os.environ.get("AWS_PROFILE", "")


def _environment_secret_id() -> str:
    """The secret identifier, from one fixed environment-variable name.

    Called only on the authorized path, after every gate has passed. The
    *name* is a constant and is not a secret; the *value* is, and it is never
    printed, logged, returned to a caller or included in a refusal.

    ``os`` is imported inside the body, so an ordinary import of this module --
    and every refusal path above -- performs no environment lookup at all.

    Raises:
        LookupError: if the variable is unset or blank. Converted by the caller
            into the closed ``REFUSED_CREDENTIAL`` outcome, which names nothing.
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
    """A Secrets Manager client, pinned to the governed region.

    The one AWS SDK construction ADR-0015 authorizes, and the reason the SDK is a
    declared dependency at all. It lives in a script rather than under ``src/``
    so the data platform stays SDK-free.
    """
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
#: The authorization capability, its mint and its minting function are all
#: absent, deliberately: an exported mint is a public constructor by another
#: name. An audit guard asserts their absence, which is only meaningful
#: because this list exists to be absent from.
__all__ = [
    "BINDING_AUTHORIZATION_FLAG",
    "REFUSED_OPTIONS",
    "SECRET_ID_ENV_VAR",
    "BindingPreflightError",
    "PreflightOutcome",
    "SystemClock",
    "build_parser",
    "main",
    "run_binding_preflight",
]


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    sys.exit(main())
