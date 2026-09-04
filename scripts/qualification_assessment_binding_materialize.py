"""Materialize the private ASSESSMENT runtime binding from the environment binding.

**Refused by default.**

ADR-0025 took the licensed bucket and the account binding out of Terraform for the
combined assessment actor, exactly as ADR-0023 did for acquisition, and made both
arrive in one ACL-protected private JSON file. This command is the gate that creates
that file. It reads the environment binding a capture produced, copies the two values
the assessment contract needs, and writes the ADR-0025 document with the digest of
**the exact bytes it consumed** in ``provenance.environment_binding_sha256``.

**It is a second gate rather than a mode of the first.** The acquisition gate writes an
artifact naming the acquisition profile, and this one writes an artifact naming the
assessment profile; a single command with an actor flag would make one operator mistake
enough to hand one actor the other's binding. The two tools share the environment
binding they read, the writer they write through and the trust boundary both are held
to -- and share no output.

**This command reaches no AWS service and starts no process.** The governed account it
validates the source against is the local account binding, which is a plain file read,
and the licensed bucket arrives from the environment binding rather than from
infrastructure. Terraform is not reachable from here, and neither is the capture that
does read it.

**The operator contract, in full.**

```text
KALPAMANI_QUALIFICATION_ENVIRONMENT_BINDING_FILE         an ABSOLUTE path to the
                                                         existing environment binding
KALPAMANI_QUALIFICATION_ASSESSMENT_RUNTIME_BINDING_FILE  an ABSOLUTE path to the
                                                         assessment binding to create
```

Both are absolute paths beneath the operator's private root, and neither is an option:
a private path on a command line enters shell history and every process listing, so each
arrives from the environment and every spelling of a path flag is refused by name. **An
occupied destination is a refusal**, never a replacement.

**Running this requires its own written authorization, in its own fresh session.**
Implementing a materialization gate is not performing one, and performing one is not
authorization for a binding preflight, Run B or the combined assessment -- each of those
remains a separate written authorization that has not been given.
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

from kalpamani.data.qualify.sharadar.runtime_binding import (  # noqa: E402
    ASSESSMENT_RUNTIME_BINDING_CONTRACT_ID,
    ASSESSMENT_RUNTIME_BINDING_ENV_VAR,
    ASSESSMENT_RUNTIME_BINDING_KIND,
    ASSESSMENT_RUNTIME_BINDING_SCHEMA_VERSION,
    ENVIRONMENT_BINDING_ENV_VAR,
    EXPECTED_ASSESSMENT_PROFILE,
    EXPECTED_PARTITION,
    EXPECTED_REGION,
    QualificationEnvironmentBinding,
    canonical_binding_bytes,
    parse_assessment_runtime_binding,
)

#: The reviewed repository state this gate's contract was written against, named by
#: the Git objects that carry it. Not a secret -- a Git object name is public -- and
#: not decoration: it records *which* reviewed state an operator's private file was
#: made for, so a binding written against one contract is identifiable after the
#: contract has moved on.
#:
#: **These name the baseline this slice was built on, not this slice's own merge**,
#: which cannot exist while the slice is being written. The acquisition gate's pair
#: names an already-merged slice because that slice had merged before its gate was
#: added. If a reviewer would rather this named this correction's own accepted
#: objects, that is a one-line follow-up after merge; it changes no behaviour, because
#: the field is validated for grammar and never interpreted.
IMPLEMENTATION_COMMIT: Final = "3bab8d362f292fed9aea243b4135467d609c61a9"
IMPLEMENTATION_TREE: Final = "23436ebd420a2bc09a3142cc161706a7dab3d89e"

#: The single flag that authorizes one materialization, and nothing else. Distinct from
#: the acquisition gate's, so neither authorization can be pasted into the other.
AUTHORIZATION_FLAG: Final = "--i-am-the-operator-authorizing-assessment-binding-materialization"

#: Options refused by name, each with the reason.
REFUSED_OPTIONS: Final[dict[str, str]] = {
    "--bucket": "the licensed bucket comes from the environment binding, never from argv",
    "--bucket-name": "same as --bucket: a licensed destination is not an operator choice",
    "--account": "the account comes from the environment binding and the governed local one",
    "--account-id": "same as --account: an account identifier does not travel in argv",
    "--binding": "the private paths are named by two fixed environment variables",
    "--binding-file": "same as --binding: a private path is not an operator choice",
    "--environment-binding": "same as --binding: a private path would enter every listing",
    "--assessment-binding": "same as --binding: a private path would enter every listing",
    "--runtime-binding": "same as --binding: a private path would enter every listing",
    "--path": "same as --binding: a private path would enter every process listing",
    "--actor": "there is no actor switch; this gate writes the assessment binding only",
    "--acquisition": "the acquisition binding has its own gate, and this is not it",
    "--profile": "no AWS profile is read, pinned or used by this command",
    "--aws-profile": "same as --profile: this command reaches no AWS service",
    "--region": "the region is governed and compiled in, not selected per run",
    "--partition": "the partition is governed and compiled in, not selected per run",
    "--force": "an occupied destination is a refusal; there is no overwrite",
    "--overwrite": "same as --force: a private artifact is never replaced in place",
    "--run": "this command creates one artifact; it runs no assessment",
    "--execute": "same as --run: no acquisition, run or assessment is reachable from here",
    "--live": "same as --run: there is no other mode to select",
    "--secret-id": "no secret is read, stored or bound by this command",
    "--token": "no token is accepted, read, stored or bound by this command",
}


class _AssessmentMaterializationAuthorization:
    """Proof that the operator flag was parsed. **Exactly one exists.**

    The shape every operator surface here arrived at: no state to copy, admission by
    identity against one module-level object, and every route to a second one closed.
    """

    __slots__ = ()

    def __new__(cls) -> _AssessmentMaterializationAuthorization:
        """Refuse a second construction once the singleton exists."""
        if "_MATERIALIZATION_AUTHORIZATION" in globals():
            raise TypeError("the materialization authorization is a singleton")
        return super().__new__(cls)

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass instance is a second bearer."""
        raise TypeError("the materialization authorization may not be subclassed")

    def __copy__(self) -> _AssessmentMaterializationAuthorization:
        """Refuse copying, so no copy operation yields an object at all."""
        raise TypeError("the materialization authorization may not be copied")

    def __deepcopy__(self, memo: object) -> _AssessmentMaterializationAuthorization:
        """Refuse deep copying, for the same reason."""
        raise TypeError("the materialization authorization may not be copied")

    def __reduce__(self) -> object:
        """Refuse pickling, which is copying with extra steps."""
        raise TypeError("the materialization authorization may not be pickled")


_MATERIALIZATION_AUTHORIZATION: Final = _AssessmentMaterializationAuthorization()


def _is_authorized(candidate: object) -> bool:
    """Whether ``candidate`` **is** the one authorization this module holds."""
    return candidate is _MATERIALIZATION_AUTHORIZATION


class MaterializationOutcome(StrEnum):
    """Every sentence this command may print. A fixed allowlist.

    **None reports a bucket, an account, a path or a digest**, and none is permission
    for anything downstream: a materialized binding is configuration a later,
    separately authorized run may read.
    """

    REFUSED_NOT_AUTHORIZED = "assessment binding materialization refused: not authorized"
    REFUSED_OPTION = "assessment binding materialization refused: this option is not accepted"
    REFUSED_EXECUTION_CONTEXT = "assessment binding materialization refused: execution context"
    REFUSED_SOURCE_PATH = "assessment binding materialization refused: no environment binding path"
    REFUSED_EXPECTED_ACCOUNT = "assessment binding materialization refused: no governed account"
    REFUSED_ENVIRONMENT_BINDING = (
        "assessment binding materialization refused: the environment binding was refused"
    )
    REFUSED_DESTINATION = "assessment binding materialization refused: the destination was refused"
    REFUSED_DOCUMENT = (
        "assessment binding materialization refused: the composed document was refused"
    )
    REFUSED_WRITE = "assessment binding materialization refused: the artifact was not created"
    REFUSED_VERIFICATION = "assessment binding materialization refused: the artifact did not verify"
    COMPLETED = "assessment binding materialization completed"


#: The exit status each outcome closes with. Command status only.
_EXIT_CODES: Final[dict[MaterializationOutcome, int]] = {
    MaterializationOutcome.COMPLETED: 0,
    MaterializationOutcome.REFUSED_NOT_AUTHORIZED: 1,
    MaterializationOutcome.REFUSED_OPTION: 2,
    MaterializationOutcome.REFUSED_EXECUTION_CONTEXT: 3,
    MaterializationOutcome.REFUSED_SOURCE_PATH: 4,
    MaterializationOutcome.REFUSED_EXPECTED_ACCOUNT: 5,
    MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING: 6,
    MaterializationOutcome.REFUSED_DESTINATION: 7,
    MaterializationOutcome.REFUSED_DOCUMENT: 8,
    MaterializationOutcome.REFUSED_WRITE: 9,
    MaterializationOutcome.REFUSED_VERIFICATION: 10,
}


class MaterializationError(Exception):
    """A refusal carrying exactly one :class:`MaterializationOutcome` and nothing else."""

    __slots__ = ("outcome",)

    def __init__(self, outcome: MaterializationOutcome) -> None:
        """Bind the outcome. The message is the member's sentence, nothing more."""
        if type(outcome) is not MaterializationOutcome:  # pragma: no cover - type guard
            raise TypeError("an outcome must be an exact MaterializationOutcome member")
        super().__init__(outcome.value)
        self.outcome = outcome


def emit(outcome: MaterializationOutcome) -> None:
    """Print one allowlisted sentence. Takes a vocabulary member, not a string."""
    print(outcome.value)


def running_under_automation(env: Mapping[str, str], modules: Mapping[str, object]) -> str | None:
    """Why this must not run here, or ``None``.

    Creating the private artifact the combined assessment is bound to is an owner
    action. Under ``pytest`` the tests would perform it; in CI the transcript is a log;
    on a plain import nobody asked for anything at all.
    """
    if "pytest" in modules:
        return "pytest"
    for name in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "BUILD_NUMBER"):
        if env.get(name, "").strip():
            return name
    return None


def materialize_assessment_binding(
    *,
    authorization: object,
    env: Mapping[str, str],
    modules: Mapping[str, object],
    source_path: Callable[[], str],
    destination_source: Callable[[], str],
    expected_account: Callable[[], str | None],
    load_environment_binding: Callable[..., QualificationEnvironmentBinding],
    write_artifact: Callable[..., Path],
    verify_assessment_binding: Callable[..., Any],
    discard_artifact: Callable[[Path], None],
) -> MaterializationOutcome:
    """Materialize one assessment binding from one environment binding. All injected.

    **The digest is taken from the artifact that was actually read**, not recomputed
    from a re-serialisation of it: the loader returns the SHA-256 of the exact bytes it
    consumed, and that value goes into ``provenance.environment_binding_sha256``
    unchanged, so the field names bytes a reviewer can re-read and re-digest.

    Only the account and the licensed bucket are copied. The partition, the region, the
    schema, the kind, the contract and **the assessment profile** are the compiled
    governed constants, because a private input that could select any of them -- the
    actor above all -- would be a routing decision taken outside the repository.

    **A written artifact that does not reload is removed before the refusal is raised.**
    The shared writer already rolls back its own failures; this rolls back the one it
    cannot see -- a file that satisfied the composer and the descriptor but that the
    production loader will not accept. Leaving it behind would put an unusable private
    artifact where a later run reads one, and the operator would discover it at stage 4
    of a run they had to authorize separately.

    Returns:
        :attr:`MaterializationOutcome.COMPLETED`. A refusal is raised, not returned.

    Raises:
        MaterializationError: one allowlisted :class:`MaterializationOutcome`. The cause
            is always suppressed.
    """
    if not _is_authorized(authorization):
        raise MaterializationError(MaterializationOutcome.REFUSED_NOT_AUTHORIZED) from None

    if running_under_automation(env, modules) is not None:
        raise MaterializationError(MaterializationOutcome.REFUSED_EXECUTION_CONTEXT) from None

    try:
        source = source_path()
    except Exception:
        raise MaterializationError(MaterializationOutcome.REFUSED_SOURCE_PATH) from None
    if type(source) is not str or not source.strip():
        raise MaterializationError(MaterializationOutcome.REFUSED_SOURCE_PATH) from None

    try:
        account = expected_account()
    except Exception:
        raise MaterializationError(MaterializationOutcome.REFUSED_EXPECTED_ACCOUNT) from None
    if type(account) is not str:
        raise MaterializationError(MaterializationOutcome.REFUSED_EXPECTED_ACCOUNT) from None

    try:
        environment = load_environment_binding(path=source, expected_account=account)
    except Exception:
        # The loader's refusals are closed and value-free, and this converts them
        # anyway: only the allowlisted outcome may reach a transcript.
        raise MaterializationError(MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING) from None
    if type(environment) is not QualificationEnvironmentBinding:
        raise MaterializationError(MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING) from None
    if environment.partition != EXPECTED_PARTITION or environment.region != EXPECTED_REGION:
        raise MaterializationError(MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING) from None
    if environment.target_account_id != account:
        raise MaterializationError(MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING) from None

    try:
        destination = destination_source()
    except Exception:
        raise MaterializationError(MaterializationOutcome.REFUSED_DESTINATION) from None
    if type(destination) is not str or not destination.strip():
        raise MaterializationError(MaterializationOutcome.REFUSED_DESTINATION) from None

    try:
        document = {
            "schema_version": ASSESSMENT_RUNTIME_BINDING_SCHEMA_VERSION,
            "binding_kind": ASSESSMENT_RUNTIME_BINDING_KIND,
            "contract_id": ASSESSMENT_RUNTIME_BINDING_CONTRACT_ID,
            "aws_partition": EXPECTED_PARTITION,
            "aws_region": EXPECTED_REGION,
            "target_account_id": environment.target_account_id,
            "assessment_profile": EXPECTED_ASSESSMENT_PROFILE,
            "licensed_bucket_name": environment.licensed_bucket_name,
            "provenance": {
                "implementation_commit": IMPLEMENTATION_COMMIT,
                "implementation_tree": IMPLEMENTATION_TREE,
                "environment_binding_sha256": environment.digest,
            },
        }
        # Validated through the production loader's own parser before a byte is
        # written: a file this creates and the assessment then refuses would be a
        # private artifact the operator has to diagnose from a refusal naming no value.
        parse_assessment_runtime_binding(document)
        payload = canonical_binding_bytes(document)
    except Exception:
        raise MaterializationError(MaterializationOutcome.REFUSED_DOCUMENT) from None

    try:
        written = write_artifact(destination=destination, payload=payload)
    except Exception:
        # The writer removes its own partial output, so nothing is left to roll back.
        raise MaterializationError(MaterializationOutcome.REFUSED_WRITE) from None

    def _refuse_verification() -> MaterializationError:
        # A failure to remove must not mask the refusal, and must not change it.
        try:
            discard_artifact(written)
        except Exception:  # noqa: S110 - the refusal is the report, not this
            pass
        return MaterializationError(MaterializationOutcome.REFUSED_VERIFICATION)

    # ``isinstance`` rather than an exact type check, unlike the ``str`` guards above:
    # ``Path`` is a factory that answers with ``WindowsPath`` or ``PosixPath``, so an
    # exact check would refuse every genuine path a writer returns.
    if not isinstance(written, Path):
        raise _refuse_verification() from None
    try:
        verified = verify_assessment_binding(destination=destination)
    except Exception:
        raise _refuse_verification() from None
    if getattr(verified, "licensed_bucket_name", None) != environment.licensed_bucket_name:
        raise _refuse_verification() from None
    if getattr(verified, "target_account_id", None) != environment.target_account_id:
        raise _refuse_verification() from None

    return MaterializationOutcome.COMPLETED


def build_parser() -> argparse.ArgumentParser:
    """The executable CLI surface. **Exactly one argument, and no aliases.**"""
    parser = argparse.ArgumentParser(
        prog="qualification_assessment_binding_materialize",
        description=(
            "Materialize the private assessment runtime binding from the environment "
            "binding. Refused by default. Both private paths come from the environment."
        ),
    )
    parser.add_argument(
        AUTHORIZATION_FLAG,
        dest="authorization_flag_present",
        action="store_true",
        help="authorize ONE assessment-binding materialization, and nothing else",
    )
    return parser


def _refused_option(argv: Sequence[str]) -> str | None:
    """The first refused option in ``argv``, or ``None``."""
    for token in argv:
        name = token.split("=", 1)[0]
        if name in REFUSED_OPTIONS:
            return name
    return None


def _expected_account() -> str | None:
    """The governed account, from the local binding. A plain local file read.

    Reachable from **this operator tool** and from no qualification run: the assessment
    run takes its account binding from the artifact this command writes, which is the
    whole point of ADR-0025, and a call-graph guard proves the run cannot reach here.
    """
    from aws_foundation_verify import expected_account  # type: ignore[import-not-found]

    return expected_account()  # type: ignore[no-any-return]


def _load_environment_binding(*, path: str, expected_account: str | None) -> Any:
    """The production environment-binding loader, on an explicitly given path."""
    from kalpamani.data.qualify.sharadar.runtime_binding import load_environment_binding

    return load_environment_binding(path=path, expected_account=expected_account)


def _write_artifact(*, destination: str, payload: bytes) -> Path:
    """The one private-artifact writer. No second security model exists to pick."""
    from qualification_private_artifacts import (  # type: ignore[import-not-found]
        write_private_artifact,
    )

    return write_private_artifact(  # type: ignore[no-any-return]
        destination=destination, payload=payload
    )


def _discard_artifact(path: Path) -> None:
    """Remove an artifact the production loader refused. **Nothing else is touched.**

    Reached only after this command created that exact file itself, on the one path
    where it has been proved unusable. It takes the normalised path the writer
    returned rather than the operator's string, so a destination that was refused,
    rewritten or never created has nothing here to act on.
    """
    import os

    try:
        os.unlink(path)
    except OSError:
        # A failure to remove must not mask the refusal that caused it.
        pass


def _verify_assessment_binding(*, destination: str) -> Any:
    """Re-read the artifact through the loader the assessment uses, and validate it.

    A file that satisfies the composer but not the loader is a file the operator
    discovers is unusable at stage 4 of a run they had to authorize separately. This
    asks the real question now, against the real bytes on disk.
    """
    from kalpamani.data.qualify.sharadar.runtime_binding import load_assessment_runtime_binding

    return load_assessment_runtime_binding(path_source=lambda: destination)


def main(argv: list[str] | None = None) -> int:
    """Parse, refuse, or materialize one assessment binding.

    ``0`` means the artifact was created and verified. Non-zero means the command
    refused. **Neither is a verdict**, and neither authorizes a binding preflight,
    Run B or the combined assessment.

    **This function has never been run.** Implementing a materialization gate was not
    permission to perform one, and performing one requires its own fresh-session
    written authorization.
    """
    import os

    argv = list(sys.argv[1:] if argv is None else argv)

    refused = _refused_option(argv)
    if refused is not None:
        emit(MaterializationOutcome.REFUSED_OPTION)
        return _EXIT_CODES[MaterializationOutcome.REFUSED_OPTION]

    parser = build_parser()
    try:
        parsed = parser.parse_args(argv)
    except SystemExit:
        emit(MaterializationOutcome.REFUSED_OPTION)
        return _EXIT_CODES[MaterializationOutcome.REFUSED_OPTION]

    if not parsed.authorization_flag_present:
        emit(MaterializationOutcome.REFUSED_NOT_AUTHORIZED)
        return _EXIT_CODES[MaterializationOutcome.REFUSED_NOT_AUTHORIZED]

    env = dict(os.environ)
    try:
        outcome = materialize_assessment_binding(
            authorization=_MATERIALIZATION_AUTHORIZATION,
            env=env,
            modules=sys.modules,
            source_path=lambda: env.get(ENVIRONMENT_BINDING_ENV_VAR, ""),
            destination_source=lambda: env.get(ASSESSMENT_RUNTIME_BINDING_ENV_VAR, ""),
            expected_account=_expected_account,
            load_environment_binding=_load_environment_binding,
            write_artifact=_write_artifact,
            verify_assessment_binding=_verify_assessment_binding,
            discard_artifact=_discard_artifact,
        )
    except MaterializationError as refusal:
        emit(refusal.outcome)
        return _EXIT_CODES[refusal.outcome]

    emit(outcome)
    return _EXIT_CODES[outcome]


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
