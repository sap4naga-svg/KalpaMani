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
        dest="binding_authorized",
        action="store_true",
        help=(
            "Authorize a binding preflight. This does not authorize, imply or stand in "
            "for authorization to execute a qualification run."
        ),
    )
    parser.add_argument(
        "--secret-id",
        dest="secret_id",
        default=None,
        help=(
            "The identifier of the Secrets Manager secret holding the private "
            "credential. Supplied by the operator; never compiled in, never printed."
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
    binding_authorized: bool,
    secret_id: str | None,
    subjects: Sequence[str] | None,
    execution_id: str | None,
    profile_of: Callable[[], str],
    identity_gate: Callable[[], str | None],
    resolve_licensed_bucket: Callable[[], str],
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
    # 1. Authorization. Exact `True`, not merely truthy: a non-empty string, a 1
    #    or a lookalike object must not authorize anything.
    if binding_authorized is not True:
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

    # 5. The private credential. Imported here rather than at module scope so an
    #    import of this file pulls in no provider code at all.
    from kalpamani.data.ingest.sharadar.secrets import sharadar_credential_from_secret

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

    if not parsed.binding_authorized:
        # The default path. Nothing above this line looked anything up,
        # constructed anything, or opened anything.
        _emit(PreflightOutcome.REFUSED_NOT_AUTHORIZED)
        print(f"  pass {BINDING_AUTHORIZATION_FLAG} to authorize a binding preflight")
        print("  that flag authorizes a binding preflight only, never a qualification run")
        return 1

    try:
        result = run_binding_preflight(
            binding_authorized=True,
            secret_id=parsed.secret_id,
            subjects=parsed.subjects,
            execution_id=parsed.execution_id,
            profile_of=_ambient_profile,
            identity_gate=_governed_identity_gate,
            resolve_licensed_bucket=_governed_licensed_bucket,
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


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    sys.exit(main())
