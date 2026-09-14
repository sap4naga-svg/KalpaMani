"""Materialize one production HUMAN runtime binding (ADR-0036 §2.5; proposed ADR-0046).

**Refused by default.**

ADR-0036 §2.5 gives each production actor its own private runtime binding under the
ADR-0023 trust boundary -- ``kalpamani-production-acquisition-runtime-binding/v1`` and
``kalpamani-research-build-runtime-binding/v1`` -- read by the accepted loader
(:func:`kalpamani.data.production.sharadar.bindings.load_human_runtime_binding`) before
any client the launch tool builds. This command is the gate that creates one of them
(readiness step S7; gap G-4). It reads the environment binding a capture produced
(ADR-0024), copies the two values the production contract needs -- the account and the
licensed bucket -- and writes the actor's document with the compiled profile constant and
the digest of **the exact bytes it consumed** in ``provenance.environment_binding_sha256``.

**One authorization names one actor.** There is no ``--actor`` switch: the acquisition
binding is authorized by one flag and the research-build binding by another, each spelling
its actor, so a single operator mistake cannot hand one actor the other's binding. The
destination is the actor's own fixed environment variable
(``KALPAMANI_PRODUCTION_ACQUISITION_RUNTIME_BINDING_FILE`` /
``KALPAMANI_RESEARCH_BUILD_RUNTIME_BINDING_FILE``), the same variable the launch tool
reads, so what is written is what will be loaded. Both private paths are absolute paths
beneath the owner's private root, arrive from the environment and never from argv, and
**an occupied destination is a refusal**, never a replacement.

**This command materializes an owner declaration; it verifies no AWS identity.** It
reaches no AWS service and starts no process: the governed account it validates the
source against is the local account binding (a plain file read), and the licensed bucket
arrives from the environment binding. That the profile named in the document resolves to
the actor's permission-set role is established only by a later, separately authorized
identity preflight and by the launch tool's own bootstrap, never here. The document is
validated through the production loader's parser before a byte is written, written by the
one private-artifact writer (exclusive create, owner-only descriptor, read-back), then
re-read through the accepted human loader -- a file the loader would refuse is removed
before the refusal is raised.

**Running this requires its own written authorization, in its own fresh session.**
Implementing the gate is not performing it, and performing it authorizes no identity
preflight, no launch and no run.
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

from kalpamani.data.production.sharadar.bindings import (  # noqa: E402
    BINDING_SCHEMA_VERSION,
    parse_production_runtime_binding,
)
from kalpamani.data.production.sharadar.vocabulary import (  # noqa: E402
    EXPECTED_PARTITION,
    EXPECTED_REGION,
    ProductionActor,
    constants_for,
)
from kalpamani.data.qualify.sharadar.runtime_binding import (  # noqa: E402
    ENVIRONMENT_BINDING_ENV_VAR,
    QualificationEnvironmentBinding,
    canonical_binding_bytes,
)

#: The reviewed implementation of the production binding contract, named by the Git
#: objects that carry it: the approved head of the pull request that introduced
#: ``bindings.py`` (PR #95, ADR-0036 runtime foundations) and that commit's tree. Public
#: Git object names, not secrets; they record which reviewed contract a private file was
#: made for. A governance test holds the pair to the record in the repository status.
IMPLEMENTATION_COMMIT: Final = "1adccd278ae5e0473ca5dbb46825aaa0ff20b94f"
IMPLEMENTATION_TREE: Final = "a5adfd06e56a66af6be253aab0e5cc4fb2b08889"

#: One flag per actor. Each authorizes exactly one materialization of exactly one
#: binding; neither can be pasted into the other's gate.
AUTHORIZATION_FLAGS: Final[dict[str, ProductionActor]] = {
    "--i-am-the-owner-authorizing-acquisition-binding-materialization": (
        ProductionActor.ACQUISITION
    ),
    "--i-am-the-owner-authorizing-research-build-binding-materialization": ProductionActor.BUILD,
}

#: Options refused by name, each with the reason.
REFUSED_OPTIONS: Final[dict[str, str]] = {
    "--actor": "there is no actor switch; each actor has its own authorization flag",
    "--bucket": "the licensed bucket comes from the environment binding, never from argv",
    "--bucket-name": "same as --bucket: a licensed destination is not an operator choice",
    "--account": "the account comes from the environment binding and the governed local one",
    "--account-id": "same as --account: an account identifier does not travel in argv",
    "--binding": "the private paths are named by fixed environment variables",
    "--binding-file": "same as --binding: a private path is not an operator choice",
    "--environment-binding": "same as --binding: a private path would enter every listing",
    "--runtime-binding": "same as --binding: a private path would enter every listing",
    "--destination": "same as --binding: a private path would enter every listing",
    "--output": "same as --binding: a private path would enter every listing",
    "--path": "same as --binding: a private path would enter every process listing",
    "--profile": "the profile is the actor's compiled constant, never an argument",
    "--aws-profile": "same as --profile: this command reaches no AWS service",
    "--region": "the region is governed and compiled in, not selected per run",
    "--partition": "the partition is governed and compiled in, not selected per run",
    "--force": "an occupied destination is a refusal; there is no overwrite",
    "--overwrite": "same as --force: a private artifact is never replaced in place",
    "--run": "this command creates one artifact; it launches nothing",
    "--execute": "same as --run: no launch or run is reachable from here",
    "--live": "same as --run: there is no other mode to select",
    "--verify-identity": "identity is proved by a later, separately authorized preflight",
    "--secret-id": "no secret is read, stored or bound by this command",
    "--token": "no token is accepted, read, stored or bound by this command",
}


class _BindingMaterializationAuthorization:
    """Proof that one actor's flag was parsed. **Exactly one exists per actor.**

    No state to copy, admission by identity against one module-level object per actor,
    and every route to a second one closed.
    """

    __slots__ = ("actor",)

    def __new__(cls, actor: ProductionActor) -> _BindingMaterializationAuthorization:
        """Refuse a second construction for an actor once its singleton exists."""
        existing = globals().get("_MATERIALIZATION_AUTHORIZATIONS")
        if existing is not None and actor in existing:
            raise TypeError("the materialization authorization is a singleton per actor")
        instance = super().__new__(cls)
        object.__setattr__(instance, "actor", actor)
        return instance

    def __init__(self, actor: ProductionActor) -> None:
        """The actor is bound in ``__new__``; nothing else to initialize."""

    def __setattr__(self, name: str, value: object) -> None:
        """Immutable."""
        raise TypeError("the materialization authorization is immutable")

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass instance is a second bearer."""
        raise TypeError("the materialization authorization may not be subclassed")

    def __copy__(self) -> _BindingMaterializationAuthorization:
        """Refuse copying, so no copy operation yields an object at all."""
        raise TypeError("the materialization authorization may not be copied")

    def __deepcopy__(self, memo: object) -> _BindingMaterializationAuthorization:
        """Refuse deep copying, for the same reason."""
        raise TypeError("the materialization authorization may not be copied")

    def __reduce__(self) -> str | tuple[Any, ...]:
        """Refuse pickling, which is copying with extra steps."""
        raise TypeError("the materialization authorization may not be pickled")


_MATERIALIZATION_AUTHORIZATIONS: Final[
    dict[ProductionActor, _BindingMaterializationAuthorization]
] = {actor: _BindingMaterializationAuthorization(actor) for actor in ProductionActor}


def _authorized_actor(candidate: object) -> ProductionActor | None:
    """The actor whose one authorization ``candidate`` **is**, or ``None``."""
    for actor, authorization in _MATERIALIZATION_AUTHORIZATIONS.items():
        if candidate is authorization:
            return actor
    return None


class MaterializationOutcome(StrEnum):
    """Every sentence this command may print. A fixed allowlist.

    **None reports a bucket, an account, a path, a profile or a digest**, and none is
    permission for anything downstream: a materialized binding is configuration a later,
    separately authorized preflight or launch may read.
    """

    REFUSED_NOT_AUTHORIZED = "production binding materialization refused: not authorized"
    REFUSED_OPTION = "production binding materialization refused: this option is not accepted"
    REFUSED_EXECUTION_CONTEXT = "production binding materialization refused: execution context"
    REFUSED_SOURCE_PATH = "production binding materialization refused: no environment binding path"
    REFUSED_EXPECTED_ACCOUNT = "production binding materialization refused: no governed account"
    REFUSED_ENVIRONMENT_BINDING = (
        "production binding materialization refused: the environment binding was refused"
    )
    REFUSED_DESTINATION = "production binding materialization refused: the destination was refused"
    REFUSED_DOCUMENT = (
        "production binding materialization refused: the composed document was refused"
    )
    REFUSED_WRITE = "production binding materialization refused: the artifact was not created"
    REFUSED_VERIFICATION = "production binding materialization refused: the artifact did not verify"
    COMPLETED = "production binding materialization completed"


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

    Creating a private artifact the launch tool is bound to is an owner action. Under
    ``pytest`` the tests would perform it; in CI the transcript is a log.
    """
    if "pytest" in modules:
        return "pytest"
    for name in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "BUILD_NUMBER"):
        if env.get(name, "").strip():
            return name
    return None


def compose_binding_document(
    actor: ProductionActor, environment: QualificationEnvironmentBinding
) -> dict[str, Any]:
    """The actor's binding document from the environment binding. **Reads nothing.**

    Only the account and the licensed bucket are copied. The partition, the region, the
    schema, the kind, the contract and **the actor's profile** are the compiled governed
    constants, because a private input that could select any of them -- the actor above
    all -- would be a routing decision taken outside the repository.
    """
    constants = constants_for(actor)
    return {
        "schema_version": BINDING_SCHEMA_VERSION,
        "binding_kind": constants.binding_kind,
        "contract_id": constants.binding_contract_id,
        "aws_partition": EXPECTED_PARTITION,
        "aws_region": EXPECTED_REGION,
        "target_account_id": environment.target_account_id,
        constants.profile_field: constants.profile,
        "licensed_bucket_name": environment.licensed_bucket_name,
        "provenance": {
            "implementation_commit": IMPLEMENTATION_COMMIT,
            "implementation_tree": IMPLEMENTATION_TREE,
            "environment_binding_sha256": environment.digest,
        },
    }


def materialize_production_binding(
    *,
    authorization: object,
    env: Mapping[str, str],
    modules: Mapping[str, object],
    source_path: Callable[[], str],
    destination_source: Callable[[ProductionActor], str],
    expected_account: Callable[[], str | None],
    load_environment_binding: Callable[..., QualificationEnvironmentBinding],
    write_artifact: Callable[..., Path],
    verify_binding: Callable[..., Any],
    discard_artifact: Callable[[Path], None],
) -> tuple[ProductionActor, MaterializationOutcome]:
    """Materialize one actor's binding from one environment binding. All injected.

    The actor is the one the authorization object **is** for; nothing else selects it.
    The destination comes from ``destination_source(actor)`` -- the production caller
    reads the actor's own fixed environment variable. **A written artifact that does not
    reload through the accepted human loader is removed before the refusal is raised.**

    Returns:
        the actor and :attr:`MaterializationOutcome.COMPLETED`. A refusal is raised.

    Raises:
        MaterializationError: one allowlisted :class:`MaterializationOutcome`. The cause
            is always suppressed.
    """
    admitted = _authorized_actor(authorization)
    if admitted is None:
        raise MaterializationError(MaterializationOutcome.REFUSED_NOT_AUTHORIZED) from None
    actor: ProductionActor = admitted

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
        raise MaterializationError(MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING) from None
    if type(environment) is not QualificationEnvironmentBinding:
        raise MaterializationError(MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING) from None
    if environment.partition != EXPECTED_PARTITION or environment.region != EXPECTED_REGION:
        raise MaterializationError(MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING) from None
    if environment.target_account_id != account:
        raise MaterializationError(MaterializationOutcome.REFUSED_ENVIRONMENT_BINDING) from None

    try:
        destination = destination_source(actor)
    except Exception:
        raise MaterializationError(MaterializationOutcome.REFUSED_DESTINATION) from None
    if type(destination) is not str or not destination.strip():
        raise MaterializationError(MaterializationOutcome.REFUSED_DESTINATION) from None

    try:
        document = compose_binding_document(actor, environment)
        # Validated through the production loader's own parser before a byte is written.
        parsed = parse_production_runtime_binding(document, actor=actor)
        if parsed.actor is not actor:
            raise ValueError("the composed document is not this actor's")
        payload = canonical_binding_bytes(document)
    except Exception:
        raise MaterializationError(MaterializationOutcome.REFUSED_DOCUMENT) from None

    try:
        written = write_artifact(destination=destination, payload=payload)
    except Exception:
        # The writer removes its own partial output, so nothing is left to roll back.
        raise MaterializationError(MaterializationOutcome.REFUSED_WRITE) from None

    def _refuse_verification() -> MaterializationError:
        try:
            discard_artifact(written)
        except Exception:  # noqa: S110 - the refusal is the report, not this
            pass
        return MaterializationError(MaterializationOutcome.REFUSED_VERIFICATION)

    if not isinstance(written, Path):
        raise _refuse_verification() from None
    try:
        verified = verify_binding(actor=actor, destination=destination)
    except Exception:
        raise _refuse_verification() from None
    if getattr(verified, "actor", None) is not actor:
        raise _refuse_verification() from None
    if getattr(verified, "licensed_bucket_name", None) != environment.licensed_bucket_name:
        raise _refuse_verification() from None
    if getattr(verified, "target_account_id", None) != environment.target_account_id:
        raise _refuse_verification() from None
    if getattr(verified, "profile", None) != constants_for(actor).profile:
        raise _refuse_verification() from None

    return actor, MaterializationOutcome.COMPLETED


def build_parser() -> argparse.ArgumentParser:
    """The executable CLI surface. **Two mutually exclusive flags, and no aliases.**"""
    parser = argparse.ArgumentParser(
        prog="production_human_binding_materialize",
        description=(
            "Materialize one production human runtime binding from the environment binding. "
            "Refused by default. One flag per actor; both private paths come from the environment."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    for flag, actor in AUTHORIZATION_FLAGS.items():
        group.add_argument(
            flag,
            dest=f"authorize_{actor.value}",
            action="store_true",
            help=f"authorize ONE {actor.value} binding materialization, and nothing else",
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
    """The governed account, from the local binding. A plain local file read."""
    from aws_foundation_verify import expected_account

    return expected_account()


def _load_environment_binding(*, path: str, expected_account: str | None) -> Any:
    """The production environment-binding loader, on an explicitly given path."""
    from kalpamani.data.qualify.sharadar.runtime_binding import load_environment_binding

    return load_environment_binding(path=path, expected_account=expected_account)


def _write_artifact(*, destination: str, payload: bytes) -> Path:
    """The one private-artifact writer. No second security model exists to pick."""
    from qualification_private_artifacts import write_private_artifact

    return write_private_artifact(destination=destination, payload=payload)


def _discard_artifact(path: Path) -> None:
    """Remove an artifact the accepted loader refused. **Nothing else is touched.**"""
    import os

    try:
        os.unlink(path)
    except OSError:
        pass


def _verify_binding(*, actor: ProductionActor, destination: str) -> Any:
    """Re-read the artifact through the loader the launch tool uses, and validate it."""
    from kalpamani.data.production.sharadar.bindings import load_human_runtime_binding

    variable = constants_for(actor).binding_env_var
    return load_human_runtime_binding(
        actor, environment=lambda name: destination if name == variable else None
    )


def main(argv: list[str] | None = None) -> int:
    """Parse, refuse, or materialize one production binding.

    ``0`` means the artifact was created and verified. Non-zero means the command
    refused. **Neither is a verdict on identity**, and neither authorizes a preflight, a
    launch or a run.

    **This function has never been run against a real private root.** Implementing a
    materialization gate was not permission to perform one.
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

    selected = [
        actor for actor in ProductionActor if getattr(parsed, f"authorize_{actor.value}", False)
    ]
    if len(selected) != 1:
        emit(MaterializationOutcome.REFUSED_NOT_AUTHORIZED)
        return _EXIT_CODES[MaterializationOutcome.REFUSED_NOT_AUTHORIZED]

    env = dict(os.environ)
    try:
        _actor, outcome = materialize_production_binding(
            authorization=_MATERIALIZATION_AUTHORIZATIONS[selected[0]],
            env=env,
            modules=sys.modules,
            source_path=lambda: env.get(ENVIRONMENT_BINDING_ENV_VAR, ""),
            destination_source=lambda actor: env.get(constants_for(actor).binding_env_var, ""),
            expected_account=_expected_account,
            load_environment_binding=_load_environment_binding,
            write_artifact=_write_artifact,
            verify_binding=_verify_binding,
            discard_artifact=_discard_artifact,
        )
    except MaterializationError as refusal:
        emit(refusal.outcome)
        return _EXIT_CODES[refusal.outcome]

    emit(outcome)
    return _EXIT_CODES[outcome]


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
