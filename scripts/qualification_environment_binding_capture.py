"""Capture the governed qualification environment binding (ADR-0024). **Refused by default.**

This is the producer the private runtime binding never had. ADR-0023 made the licensed
bucket arrive as an ACL-protected private file and required
``provenance.environment_binding_sha256`` in it -- but nothing said what those bytes
were, wrote them, or handed a digest to anything. This command writes them: one
owner-only JSON artifact carrying the authoritative qualification-environment values,
captured from the governed infrastructure outputs.

**It is the only place in this repository that may read those outputs for this
purpose, and it is deliberately not on any run path.** The acquisition entry point
consumes the already-materialized runtime binding and nothing else; it cannot reach
this command, this command cannot reach it, and a test follows the call graph to prove
both. Terraform stays exactly where ADR-0023 put it -- outside Run A.

**The actor is the foundation actor, and it is pinned explicitly.** Terraform inherits
the process environment, which is precisely how the original defect arose, so this
command refuses unless ``AWS_PROFILE`` is already the governed foundation profile, and
refuses the two qualification profile names by name. It then passes the existing
governed identity gate before reading anything. A capture performed as the acquisition
actor would fail for the reason ADR-0023 documented; a capture performed as *some*
actor nobody pinned is worse, because it might succeed.

**The operator contract, in full.**

```text
AWS_PROFILE                                        the governed foundation profile
KALPAMANI_QUALIFICATION_ENVIRONMENT_BINDING_FILE   an ABSOLUTE path to the artifact
                                                   to create, beneath the private root
```

Neither is an option, and neither may be: a profile and a private path on a command
line enter shell history and every process listing on the workstation, so each arrives
from the environment and every spelling of a corresponding flag is refused by name.

**Running this requires its own written authorization, in its own fresh session, under
Manual approval.** Implementing an operator surface is not permission to use it. This
command has never been run; it reads governed infrastructure outputs and creates a
private artifact, and each of those is an owner action.

**Output is allowlisted.** A fixed set of sentences through one function that takes a
vocabulary member, not a string -- so no bucket, account, path, digest, profile or
platform message can reach a transcript.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
for _entry in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
    if str(_entry) not in sys.path:  # pragma: no cover - import bootstrap
        sys.path.insert(0, str(_entry))

#: The one fixed, non-secret environment-variable *name* naming the artifact this
#: command creates. Spelled once, in the contract module, so the producer, the
#: materializer and the validator cannot drift apart.
from kalpamani.data.qualify.sharadar.runtime_binding import (  # noqa: E402
    ENVIRONMENT_BINDING_CONTRACT_ID,
    ENVIRONMENT_BINDING_ENV_VAR,
    ENVIRONMENT_BINDING_KIND,
    ENVIRONMENT_BINDING_SCHEMA_VERSION,
    ENVIRONMENT_BINDING_SOURCE_KIND,
    EXPECTED_PARTITION,
    EXPECTED_REGION,
    canonical_binding_bytes,
    parse_environment_binding,
    sha256_hex,
)

#: The one governed Terraform output this command reads. Exactly one: an output map
#: carries an ECR URL and two role ARNs that each embed an account, and a capture that
#: took the whole map would put them in a file for no reason anybody asked for.
LICENSED_BUCKET_OUTPUT: Final = "licensed_bucket_name"

#: The single flag that authorizes one capture, and nothing else. Long and awkward on
#: purpose: nobody types this by reflex.
AUTHORIZATION_FLAG: Final = "--i-am-the-operator-authorizing-environment-binding-capture"

#: Options refused by name, each with the reason. A private path, a licensed
#: destination, an account and a profile on a command line enter shell history and
#: every process listing, and the remainder name operations this command does not have.
REFUSED_OPTIONS: Final[dict[str, str]] = {
    "--bucket": "the licensed bucket is captured from the governed outputs, never supplied",
    "--bucket-name": "same as --bucket: a licensed destination is not an operator choice",
    "--account": "the account comes from the governed local binding, never from argv",
    "--account-id": "same as --account: an account identifier does not travel in argv",
    "--profile": "the actor is the governed foundation profile, pinned in the environment",
    "--aws-profile": "same as --profile: the actor is not an operator choice here",
    "--region": "the region is governed and compiled in, not selected per run",
    "--partition": "the partition is governed and compiled in, not selected per run",
    "--path": "the destination is named by one fixed environment variable",
    "--output": "same as --path: a private location would enter every process listing",
    "--out": "same as --path: a private location would enter every process listing",
    "--binding": "same as --path: the private path is not an operator choice",
    "--force": "an occupied destination is a refusal; there is no overwrite",
    "--overwrite": "same as --force: a private artifact is never replaced in place",
    "--run": "this command creates one artifact; it runs no qualification",
    "--execute": "same as --run: no acquisition, run or assessment is reachable from here",
    "--live": "same as --run: there is no other mode to select",
    "--secret-id": "no secret is read, stored or bound by this command",
    "--token": "no token is accepted, read, stored or bound by this command",
}


class _CaptureAuthorization:
    """Proof that the operator flag was parsed. **Exactly one exists.**

    The shape the other operator surfaces arrived at, for the same reasons. A ``bool``
    would mean any importer could pass ``True``, and an object carrying a
    module-private mint field would be copyable -- ``copy.copy`` would manufacture a
    second bearer of the authority the capability exists to prevent.

    There is **no state to copy**: ``__slots__`` is empty, admission is identity
    against the single module-level instance, and every route that would produce a
    second object is closed.
    """

    __slots__ = ()

    def __new__(cls) -> _CaptureAuthorization:
        """Refuse a second construction once the singleton exists."""
        if "_CAPTURE_AUTHORIZATION" in globals():
            raise TypeError("the environment-binding capture authorization is a singleton")
        return super().__new__(cls)

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass instance is a second bearer."""
        raise TypeError("the environment-binding capture authorization may not be subclassed")

    def __copy__(self) -> _CaptureAuthorization:
        """Refuse copying, so no copy operation yields an object at all."""
        raise TypeError("the environment-binding capture authorization may not be copied")

    def __deepcopy__(self, memo: object) -> _CaptureAuthorization:
        """Refuse deep copying, for the same reason."""
        raise TypeError("the environment-binding capture authorization may not be copied")

    def __reduce__(self) -> object:
        """Refuse pickling, which is copying with extra steps."""
        raise TypeError("the environment-binding capture authorization may not be pickled")


_CAPTURE_AUTHORIZATION: Final = _CaptureAuthorization()


def _is_authorized(candidate: object) -> bool:
    """Whether ``candidate`` **is** the one authorization this module holds."""
    return candidate is _CAPTURE_AUTHORIZATION


class CaptureOutcome(StrEnum):
    """Every sentence this command may print. A fixed allowlist.

    Each is a fact about what the command did. **None reports a bucket, an account, a
    path, a digest, a provider conclusion or a readiness**, and none is permission for
    anything downstream: a captured environment is configuration, not a run.
    """

    REFUSED_NOT_AUTHORIZED = "environment binding capture refused: not authorized"
    REFUSED_OPTION = "environment binding capture refused: this option is not accepted"
    REFUSED_EXECUTION_CONTEXT = "environment binding capture refused: execution context"
    REFUSED_PROFILE = "environment binding capture refused: the governed profile is not pinned"
    REFUSED_IDENTITY = "environment binding capture refused: the AWS identity gate did not pass"
    REFUSED_DESTINATION = "environment binding capture refused: the destination was refused"
    REFUSED_EXPECTED_ACCOUNT = "environment binding capture refused: no governed account binding"
    REFUSED_OUTPUTS = "environment binding capture refused: the governed outputs were refused"
    REFUSED_DOCUMENT = "environment binding capture refused: the captured document was refused"
    REFUSED_WRITE = "environment binding capture refused: the artifact was not created"
    COMPLETED = "environment binding capture completed"


#: The exit status each outcome closes with. Command status only -- never a verdict
#: about the provider, the data or whether anything downstream may proceed.
_EXIT_CODES: Final[dict[CaptureOutcome, int]] = {
    CaptureOutcome.COMPLETED: 0,
    CaptureOutcome.REFUSED_NOT_AUTHORIZED: 1,
    CaptureOutcome.REFUSED_OPTION: 2,
    CaptureOutcome.REFUSED_EXECUTION_CONTEXT: 3,
    CaptureOutcome.REFUSED_PROFILE: 4,
    CaptureOutcome.REFUSED_IDENTITY: 5,
    CaptureOutcome.REFUSED_DESTINATION: 6,
    CaptureOutcome.REFUSED_EXPECTED_ACCOUNT: 7,
    CaptureOutcome.REFUSED_OUTPUTS: 8,
    CaptureOutcome.REFUSED_DOCUMENT: 9,
    CaptureOutcome.REFUSED_WRITE: 10,
}


class CaptureError(Exception):
    """A refusal carrying exactly one :class:`CaptureOutcome` and nothing else."""

    __slots__ = ("outcome",)

    def __init__(self, outcome: CaptureOutcome) -> None:
        """Bind the outcome. The message is the member's sentence, nothing more."""
        if type(outcome) is not CaptureOutcome:  # pragma: no cover - type guard
            raise TypeError("an outcome must be an exact CaptureOutcome member")
        super().__init__(outcome.value)
        self.outcome = outcome


def emit(outcome: CaptureOutcome) -> None:
    """Print one allowlisted sentence.

    Takes a vocabulary member, not a string, so there is no parameter through which a
    bucket, an account, a path, a digest or an exception could arrive.
    """
    print(outcome.value)


def running_under_automation(env: Mapping[str, str], modules: Mapping[str, object]) -> str | None:
    """Why this must not run here, or ``None``.

    Reading governed infrastructure outputs and creating a private artifact are owner
    actions. Under ``pytest`` the tests would perform them; in CI the transcript is a
    log; on a plain import nobody asked for anything at all.
    """
    if "pytest" in modules:
        return "pytest"
    for name in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "BUILD_NUMBER"):
        if env.get(name, "").strip():
            return name
    return None


class SystemClock:
    """The wall clock, in the one place this command is allowed to read one."""

    def captured_at(self) -> str:
        """The current UTC instant, in the one shape the contract admits."""
        from datetime import UTC, datetime

        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def capture_environment_binding(
    *,
    authorization: object,
    env: Mapping[str, str],
    modules: Mapping[str, object],
    governed_profile: str,
    profile_of: Callable[[], str],
    identity_gate: Callable[[], str | None],
    destination_source: Callable[[], str],
    expected_account: Callable[[], str | None],
    governed_outputs: Callable[[], Mapping[str, Any]],
    clock: Any,
    write_artifact: Callable[..., Path],
) -> CaptureOutcome:
    """Capture one governed environment binding, or refuse. Every dependency injected.

    **Order is the security property.** The actor is pinned and proved before any
    output is read; the destination is settled before anything is captured, so a
    wrong or occupied path costs nothing; and the composed document is validated
    through the production validator **before** it is written, so this command cannot
    create an artifact the materializer would refuse.

    Returns:
        :attr:`CaptureOutcome.COMPLETED`. A refusal is raised, not returned.

    Raises:
        CaptureError: one allowlisted :class:`CaptureOutcome`. The cause is always
            suppressed.
    """
    # 1. Authorization. A capability this module minted after parsing the flag.
    if not _is_authorized(authorization):
        raise CaptureError(CaptureOutcome.REFUSED_NOT_AUTHORIZED) from None

    # 2. Execution context. Refused before anything is read or resolved.
    if running_under_automation(env, modules) is not None:
        raise CaptureError(CaptureOutcome.REFUSED_EXECUTION_CONTEXT) from None

    # 3. The actor, before any AWS call is attempted at all. Terraform inherits this
    #    process's environment, so an unpinned profile is the original defect.
    try:
        profile = profile_of()
    except Exception:
        raise CaptureError(CaptureOutcome.REFUSED_PROFILE) from None
    if type(profile) is not str or profile != governed_profile:
        raise CaptureError(CaptureOutcome.REFUSED_PROFILE) from None

    # 4. The account identity gate. Its reason string can name an account, so it is
    #    consumed as a pass/fail and never printed.
    try:
        reason = identity_gate()
    except Exception:
        raise CaptureError(CaptureOutcome.REFUSED_IDENTITY) from None
    if reason is not None:
        raise CaptureError(CaptureOutcome.REFUSED_IDENTITY) from None

    # 5. The destination, settled before anything is captured.
    try:
        destination = destination_source()
    except Exception:
        raise CaptureError(CaptureOutcome.REFUSED_DESTINATION) from None
    if type(destination) is not str or not destination.strip():
        raise CaptureError(CaptureOutcome.REFUSED_DESTINATION) from None

    # 6. The governed account, from the same local binding the identity gate read.
    try:
        account = expected_account()
    except Exception:
        raise CaptureError(CaptureOutcome.REFUSED_EXPECTED_ACCOUNT) from None
    if type(account) is not str:
        raise CaptureError(CaptureOutcome.REFUSED_EXPECTED_ACCOUNT) from None

    # 7. Exactly one governed output. The map carries identifiers this artifact has
    #    no reason to hold, so one key is taken and the rest are never looked at.
    try:
        outputs = governed_outputs()
    except Exception:
        raise CaptureError(CaptureOutcome.REFUSED_OUTPUTS) from None
    if not isinstance(outputs, Mapping):
        raise CaptureError(CaptureOutcome.REFUSED_OUTPUTS) from None
    bucket = outputs.get(LICENSED_BUCKET_OUTPUT)
    if type(bucket) is not str or not bucket:
        raise CaptureError(CaptureOutcome.REFUSED_OUTPUTS) from None

    # 8. The document, and the digest over exactly the outputs that were consumed.
    try:
        captured_at = clock.captured_at()
        outputs_digest = sha256_hex(canonical_binding_bytes({LICENSED_BUCKET_OUTPUT: bucket}))
        document = {
            "schema_version": ENVIRONMENT_BINDING_SCHEMA_VERSION,
            "binding_kind": ENVIRONMENT_BINDING_KIND,
            "contract_id": ENVIRONMENT_BINDING_CONTRACT_ID,
            "aws_partition": EXPECTED_PARTITION,
            "aws_region": EXPECTED_REGION,
            "target_account_id": account,
            "licensed_bucket_name": bucket,
            "provenance": {
                "source_kind": ENVIRONMENT_BINDING_SOURCE_KIND,
                "captured_at_utc": captured_at,
                "outputs_digest": outputs_digest,
            },
        }
        payload = canonical_binding_bytes(document)
        # Validated through the production validator before a byte is written: an
        # artifact this command creates and the materializer then refuses would be a
        # private file the operator has to diagnose from a refusal that names no value.
        parse_environment_binding(document, expected_account=account, digest=sha256_hex(payload))
    except Exception:
        raise CaptureError(CaptureOutcome.REFUSED_DOCUMENT) from None

    # 9. One atomic, collision-fail-closed, owner-only create.
    try:
        write_artifact(destination=destination, payload=payload)
    except Exception:
        raise CaptureError(CaptureOutcome.REFUSED_WRITE) from None

    return CaptureOutcome.COMPLETED


def build_parser() -> argparse.ArgumentParser:
    """The executable CLI surface. **Exactly one argument, and no aliases.**"""
    parser = argparse.ArgumentParser(
        prog="qualification_environment_binding_capture",
        description=(
            "Capture the governed qualification environment binding. Refused by default. "
            "The destination and the actor come from the environment; nothing else is a choice."
        ),
    )
    parser.add_argument(
        AUTHORIZATION_FLAG,
        dest="authorization_flag_present",
        action="store_true",
        help="authorize ONE environment-binding capture, and nothing else",
    )
    return parser


def _refused_option(argv: Sequence[str]) -> str | None:
    """The first refused option in ``argv``, or ``None``.

    Matched on the option token, so ``--bucket=NAME`` is refused by the same entry as
    ``--bucket`` and the value is never echoed.
    """
    for token in argv:
        name = token.split("=", 1)[0]
        if name in REFUSED_OPTIONS:
            return name
    return None


def _governed_profile_name() -> str:
    """The foundation profile this capture must already be running under."""
    from aws_foundation_verify import EXPECTED_PROFILE  # type: ignore[import-not-found]

    return str(EXPECTED_PROFILE)


def _current_profile(env: Mapping[str, str]) -> str:
    """The profile the process is pinned to, as an exact string."""
    return env.get("AWS_PROFILE", "")


def _identity_gate() -> str | None:
    """The existing governed identity gate for the foundation actor."""
    from aws_foundation_verify import identity_gate  # type: ignore[import-not-found]

    return identity_gate()  # type: ignore[no-any-return]


def _expected_account() -> str | None:
    """The governed account, from the local binding. A plain local file read."""
    from aws_foundation_verify import expected_account  # type: ignore[import-not-found]

    return expected_account()  # type: ignore[no-any-return]


def _governed_outputs() -> Mapping[str, Any]:
    """The governed infrastructure outputs, read as the foundation actor."""
    from aws_foundation_verify import tf_outputs  # type: ignore[import-not-found]

    return tf_outputs()  # type: ignore[no-any-return]


def _destination(env: Mapping[str, str]) -> str:
    """The artifact to create, from the one fixed environment-variable name."""
    return env.get(ENVIRONMENT_BINDING_ENV_VAR, "")


def _write_artifact(*, destination: str, payload: bytes) -> Path:
    """The one private-artifact writer. No second security model exists to pick."""
    from qualification_private_artifacts import (  # type: ignore[import-not-found]
        write_private_artifact,
    )

    return write_private_artifact(  # type: ignore[no-any-return]
        destination=destination, payload=payload
    )


def main(argv: list[str] | None = None) -> int:
    """Parse, refuse, or capture one governed environment binding.

    ``0`` means the artifact was created. Non-zero means the command refused.
    **Neither is a verdict** about the provider, the data, or whether Run A, Run B or
    the combined assessment may happen -- each of those is a separate written
    authorization that has not been given.

    **This function has never been run.** Implementing an operator surface was not
    permission to use it, and running it requires its own fresh-session, Manual-mode
    authorization.
    """
    import os

    argv = list(sys.argv[1:] if argv is None else argv)

    refused = _refused_option(argv)
    if refused is not None:
        emit(CaptureOutcome.REFUSED_OPTION)
        return _EXIT_CODES[CaptureOutcome.REFUSED_OPTION]

    parser = build_parser()
    try:
        parsed = parser.parse_args(argv)
    except SystemExit:
        emit(CaptureOutcome.REFUSED_OPTION)
        return _EXIT_CODES[CaptureOutcome.REFUSED_OPTION]

    if not parsed.authorization_flag_present:
        emit(CaptureOutcome.REFUSED_NOT_AUTHORIZED)
        return _EXIT_CODES[CaptureOutcome.REFUSED_NOT_AUTHORIZED]

    env = dict(os.environ)
    try:
        outcome = capture_environment_binding(
            authorization=_CAPTURE_AUTHORIZATION,
            env=env,
            modules=sys.modules,
            governed_profile=_governed_profile_name(),
            profile_of=lambda: _current_profile(env),
            identity_gate=_identity_gate,
            destination_source=lambda: _destination(env),
            expected_account=_expected_account,
            governed_outputs=_governed_outputs,
            clock=SystemClock(),
            write_artifact=_write_artifact,
        )
    except CaptureError as refusal:
        emit(refusal.outcome)
        return _EXIT_CODES[refusal.outcome]

    emit(outcome)
    return _EXIT_CODES[outcome]


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
