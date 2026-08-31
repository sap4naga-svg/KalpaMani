"""The dormant private-binding preflight, and the secrets boundary beneath it.

ADR-0015 authorized the path that will eventually supply the private bindings
every accepted slice takes by injection. Two kinds of check live here:

**Behavioural.** The preflight is driven with synthetic factories that count what
they were asked for, so "refused before the secret" and "zero provider calls" are
numbers this file reads rather than claims it repeats. Stage ordering is proven
by counting which stages ran, not by inspecting the source.

**Structural.** AST and text scans proving the entry point has no execution path,
no module-level state, and no route to a provider fetch or an object publication.

**Nothing here touches AWS, Secrets Manager or Sharadar.** Every client is a
local class, every secret value is a self-labelled synthetic string, and the real
factories in the entry point are never called -- a test that called one would
construct an SDK client, which is the thing this slice is not authorized to do.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

import pytest

from kalpamani.data.contracts.vocabulary import AcquisitionMode, InformationSetProfile
from kalpamani.data.ingest.sharadar.composition import (
    PreflightStatus,
    QualificationPreflight,
    preflight_qualification_composition,
)
from kalpamani.data.ingest.sharadar.credentials import CREDENTIAL_PLACEHOLDER, SharadarCredential
from kalpamani.data.ingest.sharadar.secrets import (
    ARN_SUFFIX_LENGTH,
    MAX_SECRET_ID_LENGTH,
    MAX_SECRET_NAME_LENGTH,
    SecretRetrievalError,
    SecretRetrievalFailure,
    is_usable_secret_identifier,
    sharadar_credential_from_secret,
)

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
SCRIPTS = PROJECT_ROOT / "scripts"
ENTRY_POINT = SCRIPTS / "sharadar_binding_preflight.py"
SECRETS_MODULE = SRC / "kalpamani" / "data" / "ingest" / "sharadar" / "secrets.py"
PRIVATE_HARNESS = SCRIPTS / "sharadar_private_qualification.py"

#: Values that must never surface. Each is shaped like the thing that would hurt.
CANARY_SECRET = "synthetic-canary-key-a1b2c3d4e5f6"  # noqa: S105 -- a synthetic canary,
#: deliberately key-shaped so a leak test has something real to find.
CANARY_SECRET_ID = "synthetic/canary/secret-identifier-a1b2c3"  # noqa: S105 -- synthetic
CANARY_BUCKET = "synthetic-canary-bucket-a1b2c3"
CANARY_ACCOUNT = "synthetic-canary-account-a1b2c3"
CANARY_BACKEND = "synthetic-canary-backend-message-a1b2c3"
CANARY_SUBJECT = "ZZZZCANARY"

CANARIES: Final = (
    CANARY_SECRET,
    CANARY_SECRET_ID,
    CANARY_BUCKET,
    CANARY_ACCOUNT,
    CANARY_BACKEND,
)

INSTANT = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)

#: "hand me the genuine authorization" -- distinct from every value a test might
#: pass as a forgery, including ``None``.
_MINT: Final = object()

#: "no override was given" -- distinct from ``None``, which is itself a client a
#: test may want to inject to prove the dependency stage refuses it.
_UNSET: Final = object()


def _load_entry_point() -> Any:
    """Import the entry point by path, without installing it or adding it to a package.

    It lives in ``scripts/`` deliberately: nothing re-exports it, and importing
    the installed package cannot reach it. Loading it by path here keeps that
    true while still letting the tests drive it.
    """
    spec = importlib.util.spec_from_file_location("_binding_preflight_under_test", ENTRY_POINT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bp = _load_entry_point()


# ---------------------------------------------------------------------------
# Synthetic dependencies. Every one counts what was asked of it.
# ---------------------------------------------------------------------------


class Stages:
    """Which stages ran, in order. The ordering proof is this list."""

    def __init__(self) -> None:
        self.order: list[str] = []

    def record(self, stage: str) -> None:
        self.order.append(stage)


class CountingSecretsClient:
    """Answers one secret and counts the asking.

    ``calls`` is the witnessed ``get_secret_value`` **invocation** count. Every
    count claim in this file reads it rather than inferring "it must have been
    invoked" from which stage raised -- the inference ADR-0016 records as having
    been wrong in production. It witnesses a method call and nothing about the
    network: a real client can reject parameters locally after the method is
    entered.
    """

    def __init__(
        self,
        response: Any = None,
        raises: Exception | None = None,
        stages: Stages | None = None,
    ) -> None:
        self.response = {"SecretString": CANARY_SECRET} if response is None else response
        self.raises = raises
        self.stages = stages
        self.calls = 0
        self.secret_ids: list[str] = []

    def get_secret_value(self, **kwargs: Any) -> Any:
        if self.stages is not None:
            self.stages.record("credential")
        self.calls += 1
        self.secret_ids.append(kwargs.get("SecretId", ""))
        if self.raises is not None:
            raise self.raises
        return self.response


class UnusableSecretsClient:
    """A constructed client that cannot serve the one operation.

    A dependency fact, not a credential one: the object exists, so construction
    succeeded, but nothing here can invoke the one operation through it.
    """

    # Ruff's hardcoded-password heuristic fires on the attribute *name*. This is
    # a deliberately non-callable stand-in for the one operation, and renaming it
    # would stop it standing in for anything.
    get_secret_value = "not callable"  # noqa: S105


class CountingS3Client:
    """Satisfies the object-store protocol and refuses to do anything."""

    def __init__(self) -> None:
        self.put_calls = 0
        self.head_calls = 0

    def put_object(self, **_: Any) -> dict[str, Any]:
        self.put_calls += 1
        raise AssertionError(CANARY_BACKEND)

    def head_object(self, **_: Any) -> dict[str, Any]:
        self.head_calls += 1
        raise AssertionError(CANARY_BACKEND)


class CountingTransport:
    """A transport that refuses to transport."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def max_response_bytes(self) -> int:
        return 1 << 20

    def get(self, **_: Any) -> Any:
        self.calls += 1
        raise AssertionError("binding preflight must not reach a transport")


class Harness:
    """One synthetic binding-preflight environment, with every stage counted."""

    def __init__(
        self,
        *,
        profile: str = "kalpamani-foundation",
        identity_reason: str | None = None,
        bucket: str = CANARY_BUCKET,
        secrets_client: CountingSecretsClient | None = None,
        secrets_client_override: Any = _UNSET,
        secrets_factory_raises: Exception | None = None,
        profile_raises: bool = False,
        identity_raises: bool = False,
        bucket_raises: bool = False,
        secret_id_raises: Exception | None = None,
        secret_id_value: Any = CANARY_SECRET_ID,
    ) -> None:
        self.stages = Stages()
        self.profile = profile
        self.identity_reason = identity_reason
        self.bucket = bucket
        self.profile_raises = profile_raises
        self.identity_raises = identity_raises
        self.bucket_raises = bucket_raises
        self.secrets = secrets_client or CountingSecretsClient()
        self.secrets.stages = self.stages
        self.secrets_client_override: Any = secrets_client_override
        self.secrets_factory_raises = secrets_factory_raises
        self.secrets_factory_calls = 0
        self.s3 = CountingS3Client()
        self.transport = CountingTransport()
        self.secret_id_calls = 0
        self.secret_id_raises = secret_id_raises
        self.secret_id_value: Any = secret_id_value

    def profile_of(self) -> str:
        self.stages.record("profile")
        if self.profile_raises:
            raise RuntimeError(CANARY_ACCOUNT)
        return self.profile

    def identity_gate(self) -> str | None:
        self.stages.record("identity")
        if self.identity_raises:
            raise RuntimeError(CANARY_ACCOUNT)
        return self.identity_reason

    def resolve_bucket(self) -> str:
        self.stages.record("bucket")
        if self.bucket_raises:
            raise RuntimeError(CANARY_BUCKET)
        return self.bucket

    def secret_id_source(self) -> Any:
        """The private identifier, resolved only on the authorized path.

        Counted, because *when* it is asked for is the property: a private
        identifier must not be resolved on a path that is going to refuse.
        """
        self.stages.record("secret-id")
        self.secret_id_calls += 1
        if self.secret_id_raises is not None:
            raise self.secret_id_raises
        return self.secret_id_value

    def secrets_factory(self) -> Any:
        """Construct the Secrets Manager client. **Local work only.**

        Counted separately from the identifier that precedes it and the
        invocation that follows it, because the whole of ADR-0016 is that those
        three were one number and an operator could not tell which had failed.
        An absent SDK raises here; no client exists when it does, so there is
        neither an invocation nor a network request to attribute.
        """
        self.stages.record("secrets-client")
        self.secrets_factory_calls += 1
        if self.secrets_factory_raises is not None:
            raise self.secrets_factory_raises
        if self.secrets_client_override is not _UNSET:
            return self.secrets_client_override
        return self.secrets

    def s3_factory(self) -> CountingS3Client:
        self.stages.record("s3")
        return self.s3

    def transport_factory(self) -> CountingTransport:
        self.stages.record("transport")
        return self.transport

    def run(
        self,
        *,
        authorization: Any = _MINT,
        subjects: Any = ("SYNTH",),
        execution_id: str | None = "synthetic-execution-0001",
    ) -> Any:
        """Drive the preflight. ``authorization`` defaults to a genuine capability."""
        return bp.run_binding_preflight(
            authorization=(
                bp._BINDING_PREFLIGHT_AUTHORIZATION if authorization is _MINT else authorization
            ),
            subjects=subjects,
            execution_id=execution_id,
            profile_of=self.profile_of,
            identity_gate=self.identity_gate,
            resolve_licensed_bucket=self.resolve_bucket,
            secret_id_source=self.secret_id_source,
            secrets_client_factory=self.secrets_factory,
            s3_client_factory=self.s3_factory,
            transport_factory=self.transport_factory,
        )


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _executable(path: Path) -> str:
    """The module's code with docstrings removed."""
    tree = _tree(path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _python_files(root: Path) -> list[Path]:
    return [p for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts]


# ---------------------------------------------------------------------------
# 1 -- import does nothing
# ---------------------------------------------------------------------------


def test_importing_the_entry_point_runs_nothing() -> None:
    """Import time must contain no statement that does work."""
    allowed = (
        ast.Import,
        ast.ImportFrom,
        ast.ClassDef,
        ast.FunctionDef,
        ast.Assign,
        ast.AnnAssign,
        ast.Expr,
        ast.If,
    )
    for node in _tree(ENTRY_POINT).body:
        assert isinstance(node, allowed), f"import-time statement: {type(node).__name__}"
        if isinstance(node, ast.Expr):
            assert isinstance(node.value, ast.Constant), "import-time expression"
        if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            value = node.value
            # The only permitted import-time calls are argument-free
            # constructions of a sentinel type defined in this module -- today,
            # `_BindingAuthorization()`. They do no work: no lookup, no client,
            # no socket, and nothing that could reach a service. Anything with
            # arguments, or naming a type from elsewhere, is refused.
            local_classes = {
                statement.name
                for statement in _tree(ENTRY_POINT).body
                if isinstance(statement, ast.ClassDef)
            }
            bare_sentinel = (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in local_classes | {"object"}
                and not value.args
                and not value.keywords
            )
            # `__all__` is a language convention rather than state: nothing
            # reads it at run time, and mutating it changes an export list, not
            # a run.
            exports = any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            )
            assert (
                bare_sentinel
                or exports
                or isinstance(value, ast.Constant | ast.Dict | ast.Attribute | ast.Name)
            ), f"import-time call at line {node.lineno}"
        if isinstance(node, ast.If):
            # Only the `__main__` guard, which pytest never takes.
            assert "__main__" in ast.unparse(node.test)


def test_importing_the_entry_point_reads_no_environment_or_state() -> None:
    """The real factories import what they need *inside* their bodies, so the
    module itself pulls in no SDK, no environment and no verifier."""
    module_level = ast.unparse(
        ast.Module(
            body=[n for n in _tree(ENTRY_POINT).body if isinstance(n, ast.Import | ast.ImportFrom)],
            type_ignores=[],
        )
    )
    for forbidden in ("boto3", "botocore", "aws_foundation_verify", "import os", "urllib"):
        assert forbidden not in module_level, f"module-level import of {forbidden!r}"


# ---------------------------------------------------------------------------
# 2-3 -- default refusal, and authorization that cannot be forged
# ---------------------------------------------------------------------------


def test_invocation_without_an_authorization_refuses_before_any_stage() -> None:
    harness = Harness()
    with pytest.raises(bp.BindingPreflightError) as raised:
        harness.run(authorization=None)
    assert raised.value.outcome is bp.PreflightOutcome.REFUSED_NOT_AUTHORIZED
    assert harness.stages.order == [], "a stage ran before authorization was checked"
    assert harness.secrets.calls == 0
    assert harness.secret_id_calls == 0


class TruthyLookalike:
    def __bool__(self) -> bool:
        return True


class StructuralLookalike:
    """Everything the capability presents, except being the object itself.

    Empty slots and the same ``repr``, so nothing observable distinguishes it
    from the singleton except identity -- which is the whole check.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "<binding-preflight authorization>"


class BorrowedFieldLookalike:
    """Carries a ``_mint`` field, which the previous revision admitted on.

    Kept as a standing witness that field-based admission is gone: there is no
    ``_mint`` on the real capability any more, and nothing looks for one.
    """

    __slots__ = ("_mint",)

    def __init__(self) -> None:
        self._mint = object()


class ForgedEnum(StrEnum):
    AUTHORIZED = "AUTHORIZED"


#: Everything that must not authorize a binding preflight.
#:
#: The first revision took a ``bool``, so ``True`` alone would have admitted --
#: which is why it leads this list rather than sitting among the near-misses.
FORGERIES: tuple[tuple[str, Any], ...] = (
    ("True", True),
    ("False", False),
    ("one", 1),
    ("zero", 0),
    ("string", "yes"),
    ("flag-spelled string", "--i-am-the-operator-authorizing-binding-preflight"),
    ("enum member", ForgedEnum.AUTHORIZED),
    ("float", 1.0),
    ("list", [1]),
    ("mapping", {"authorized": True}),
    ("bare object", object()),
    ("truthy lookalike", TruthyLookalike()),
    ("structural lookalike", StructuralLookalike()),
    ("borrowed-field lookalike", BorrowedFieldLookalike()),
    ("the class itself", bp._BindingAuthorization),
)


@pytest.mark.parametrize(("label", "forged"), FORGERIES, ids=[case[0] for case in FORGERIES])
def test_authorization_cannot_be_forged(label: str, forged: Any) -> None:
    """A capability minted by this module, or nothing at all.

    ``True`` is the case this round exists for: the first revision checked
    ``binding_authorized is True``, so any importer could authorize a binding
    preflight without the operator flag ever being parsed.
    """
    harness = Harness()
    with pytest.raises(bp.BindingPreflightError) as raised:
        harness.run(authorization=forged)
    assert raised.value.outcome is bp.PreflightOutcome.REFUSED_NOT_AUTHORIZED
    assert harness.stages.order == [], f"{label} reached a stage"
    assert harness.secret_id_calls == 0, f"{label} reached the secret identifier"


def test_the_capability_cannot_be_constructed_a_second_time() -> None:
    """The singleton exists, so every later construction is a refusal.

    Stronger than "no public constructor with the right argument": there is no
    argument at all, and calling the class raises.
    """
    for _ in range(3):
        with pytest.raises(TypeError):
            bp._BindingAuthorization()


def test_the_capability_refuses_subclassing() -> None:
    with pytest.raises(TypeError):

        class Widened(bp._BindingAuthorization):  # type: ignore[misc, name-defined]
            pass


def test_an_uninitialised_instance_is_not_an_authorization() -> None:
    """``object.__new__`` skips ``__init__``, so the instance carries no mint."""
    hollow = object.__new__(bp._BindingAuthorization)
    assert not bp._is_authorized(hollow)
    harness = Harness()
    with pytest.raises(bp.BindingPreflightError):
        harness.run(authorization=hollow)
    assert harness.stages.order == []


def test_copying_produces_no_object_at_all() -> None:
    """The defect this round exists for.

    The previous revision admitted anything of the exact type carrying a
    module-private ``_mint`` field. **A field is copyable**: ``copy.copy``
    returned a *distinct* object holding the same field, and admission accepted
    it -- so copying manufactured a second bearer of authority. Confirmed before
    fixing, and the slice's own closeout had claimed both "copying cannot forge
    one" and "a shallow copy stays genuine", which cannot both be true.

    Copying now yields **no object**: it raises. That is the stricter of the two
    permitted designs -- returning the singleton would also have been sound, but
    refusing fails loudly, and code that copies an authorization is doing
    something this design does not intend.
    """
    import copy

    genuine = bp._BINDING_PREFLIGHT_AUTHORIZATION
    operations: tuple[tuple[str, Callable[[], Any]], ...] = (
        ("shallow copy", lambda: copy.copy(genuine)),
        ("deep copy", lambda: copy.deepcopy(genuine)),
    )
    for label, operation in operations:
        with pytest.raises(TypeError, match="may not be copied"):
            operation()
        assert bp._is_authorized(genuine), f"the {label} attempt disturbed the singleton"


def test_no_distinct_object_is_ever_admitted() -> None:
    """The property underneath the copy refusal, stated directly.

    Every object that is not *this* object is refused, whatever it carries and
    however it was made -- so a copy operation that somehow produced one would be
    refused too.
    """
    genuine = bp._BINDING_PREFLIGHT_AUTHORIZATION
    for candidate in (
        object.__new__(bp._BindingAuthorization),
        StructuralLookalike(),
        BorrowedFieldLookalike(),
    ):
        assert candidate is not genuine
        assert not bp._is_authorized(candidate)
        harness = Harness()
        with pytest.raises(bp.BindingPreflightError):
            harness.run(authorization=candidate)
        assert harness.stages.order == []


def test_serialisation_produces_no_object_either() -> None:
    """Pickling refuses, so nothing can be unpickled into a second bearer."""
    import pickle

    with pytest.raises(TypeError, match="may not be serialised"):
        pickle.dumps(bp._BINDING_PREFLIGHT_AUTHORIZATION)


def test_admission_is_identity_and_reads_no_field() -> None:
    """Isolating: the check must be identity, not exact-type-plus-field.

    The capability carries no ``_mint`` at all now, so a field-based check could
    not even be written against the real object -- and this asserts the absence
    rather than trusting it.
    """
    genuine = bp._BINDING_PREFLIGHT_AUTHORIZATION
    assert not hasattr(genuine, "_mint")
    assert bp._BindingAuthorization.__slots__ == ()
    assert not hasattr(bp, "_AUTHORIZATION_MINT")
    assert not hasattr(bp, "_mint_binding_authorization")

    source = _executable(ENTRY_POINT)
    assert "candidate is _BINDING_PREFLIGHT_AUTHORIZATION" in source
    assert "_mint" not in source, "admission still reads a copyable field"


def test_only_the_singleton_is_admitted() -> None:
    genuine = bp._BINDING_PREFLIGHT_AUTHORIZATION
    assert bp._is_authorized(genuine)
    harness = Harness()
    harness.run(authorization=genuine)
    assert harness.stages.order[0] == "profile"


def test_the_parser_path_hands_over_exactly_that_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What ``main`` passes, after the flag parses, **is** the singleton.

    Behavioural rather than structural: the preflight is replaced by a spy that
    records the object it was given, so this checks what the flag actually
    produces rather than what the source appears to say.
    """
    handed: list[Any] = []

    def spy(**kwargs: Any) -> Any:
        handed.append(kwargs["authorization"])
        raise bp.BindingPreflightError(bp.PreflightOutcome.REFUSED_PROFILE)

    monkeypatch.setattr(bp, "run_binding_preflight", spy)
    assert bp.main([bp.BINDING_AUTHORIZATION_FLAG]) == 1
    assert handed == [bp._BINDING_PREFLIGHT_AUTHORIZATION]
    assert handed[0] is bp._BINDING_PREFLIGHT_AUTHORIZATION


def test_the_capability_and_its_mint_are_not_exported() -> None:
    """Not in ``__all__``, and every name is private by convention as well."""
    exported = getattr(bp, "__all__", ())
    for name in ("_BindingAuthorization", "_BINDING_PREFLIGHT_AUTHORIZATION"):
        assert name not in exported
        assert name.startswith("_"), f"{name} is not a private name"


def test_only_main_hands_over_the_authorization() -> None:
    """One place reads the singleton to pass it on, and it is inside ``main``.

    ``_is_authorized`` also names it, to compare against -- that is the check,
    not a hand-over, so the function that *passes* it is the one asserted here.
    """
    tree = _tree(ENTRY_POINT)
    handing_over = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name != "_is_authorized"
        and any(
            isinstance(inner, ast.Name) and inner.id == "_BINDING_PREFLIGHT_AUTHORIZATION"
            for inner in ast.walk(node)
        )
    ]
    assert handing_over == ["main"]


def test_the_capability_repr_carries_nothing() -> None:
    assert repr(bp._BINDING_PREFLIGHT_AUTHORIZATION) == "<binding-preflight authorization>"


def test_the_authorization_flag_is_unmistakable_and_the_habitual_ones_are_refused() -> None:
    assert bp.BINDING_AUTHORIZATION_FLAG == "--i-am-the-operator-authorizing-binding-preflight"
    for habitual in ("--run", "--live", "--execute", "--force"):
        assert habitual in bp.REFUSED_OPTIONS


# ---------------------------------------------------------------------------
# 4-7 -- ordering, and fail-closed at every stage
# ---------------------------------------------------------------------------


def test_a_profile_mismatch_refuses_before_the_identity_call() -> None:
    harness = Harness(profile="default")
    with pytest.raises(bp.BindingPreflightError) as raised:
        harness.run()
    assert raised.value.outcome is bp.PreflightOutcome.REFUSED_PROFILE
    assert harness.stages.order == ["profile"]
    assert harness.secrets.calls == 0


def test_an_identity_failure_refuses_before_state_secret_or_composition() -> None:
    harness = Harness(identity_reason="the authenticated account does not match")
    with pytest.raises(bp.BindingPreflightError) as raised:
        harness.run()
    assert raised.value.outcome is bp.PreflightOutcome.REFUSED_IDENTITY
    assert harness.stages.order == ["profile", "identity"]
    assert harness.secrets.calls == 0


def test_a_bucket_failure_refuses_before_secret_retrieval() -> None:
    harness = Harness(bucket_raises=True)
    with pytest.raises(bp.BindingPreflightError) as raised:
        harness.run()
    assert raised.value.outcome is bp.PreflightOutcome.REFUSED_BUCKET
    assert harness.stages.order == ["profile", "identity", "bucket"]
    assert harness.secrets.calls == 0


def test_a_blank_bucket_is_refused() -> None:
    harness = Harness(bucket="   ")
    with pytest.raises(bp.BindingPreflightError) as raised:
        harness.run()
    assert raised.value.outcome is bp.PreflightOutcome.REFUSED_BUCKET
    assert harness.secrets.calls == 0


def test_a_secret_failure_refuses_before_composition() -> None:
    harness = Harness(secrets_client=CountingSecretsClient(raises=RuntimeError(CANARY_BACKEND)))
    with pytest.raises(bp.BindingPreflightError) as raised:
        harness.run()
    assert raised.value.outcome is bp.PreflightOutcome.REFUSED_CREDENTIAL
    assert harness.stages.order == [
        "profile",
        "identity",
        "bucket",
        "secret-id",
        "secrets-client",
        "credential",
    ]
    assert harness.secrets.calls == 1, "the credential outcome must follow a witnessed invocation"
    assert (harness.s3.put_calls, harness.s3.head_calls, harness.transport.calls) == (0, 0, 0)


def test_a_missing_secret_identifier_refuses_before_the_backend_is_asked() -> None:
    for missing in (None, "", "   ", 7):
        harness = Harness(secret_id_value=missing)
        with pytest.raises(bp.BindingPreflightError) as raised:
            harness.run()
        assert raised.value.outcome is bp.PreflightOutcome.REFUSED_SECRET_IDENTIFIER
        assert harness.secrets_factory_calls == 0, "a bad identifier built a client"
        assert harness.secrets.calls == 0, "a bad identifier reached the backend"


def test_the_full_ordering_is_exact_on_the_authorized_path() -> None:
    harness = Harness()
    harness.run()
    assert harness.stages.order == [
        "profile",
        "identity",
        "bucket",
        "secret-id",
        "secrets-client",
        "credential",
        "s3",
        "transport",
    ]
    assert harness.secret_id_calls == 1, "the identifier was resolved more than once"
    assert harness.secrets_factory_calls == 1, "the client was constructed more than once"
    assert harness.secrets.calls == 1, "more than one invocation was made"


# ---------------------------------------------------------------------------
# The secret identifier: out of argv, and resolved late
# ---------------------------------------------------------------------------
#
# The first revision took `--secret-id`. A private identifier on the command line
# enters shell history and every process listing on the machine, whether or not
# the program prints it -- so redacting output does not help. It now comes from an
# injected zero-argument source, called once, after every gate has passed.


@pytest.mark.parametrize(
    "option",
    ["--secret-id", "--secret-name", "--secretid", "--secret-arn", "--secret", "--secret-value"],
)
def test_a_command_line_secret_identifier_is_refused_by_name(
    option: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Refused, not silently ignored -- an unrecognised-argument error teaches
    nothing and invites a second spelling."""
    assert bp.main([option, "x"]) == 2
    captured = capsys.readouterr()
    assert bp.PreflightOutcome.REFUSED_OPTION.value in captured.out
    assert option in captured.out
    assert "x" not in captured.out.replace(option, ""), "the attempted value was echoed"


def test_the_equals_form_of_a_secret_option_is_refused_too(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert bp.main([f"--secret-id={CANARY_SECRET_ID}"]) == 2
    captured = capsys.readouterr()
    assert bp.PreflightOutcome.REFUSED_OPTION.value in captured.out
    assert CANARY_SECRET_ID not in captured.out, "the attempted identifier was echoed"


def test_the_parser_exposes_no_secret_option_at_all() -> None:
    destinations = {action.dest for action in bp.build_parser()._actions if action.option_strings}
    for forbidden in ("secret_id", "secret_name", "secret", "api_key", "token"):
        assert forbidden not in destinations


@pytest.mark.parametrize(
    ("label", "harness"),
    [
        ("authorization", Harness()),
        ("profile", Harness(profile="default")),
        ("identity", Harness(identity_reason="mismatch")),
        ("bucket", Harness(bucket_raises=True)),
    ],
)
def test_the_identifier_source_is_untouched_by_every_earlier_refusal(
    label: str, harness: Harness
) -> None:
    """A private identifier must not be resolved on a path that is going to
    refuse, so the source is asked only after every gate has passed."""
    with pytest.raises(bp.BindingPreflightError):
        harness.run(authorization=None if label == "authorization" else _MINT)
    assert harness.secret_id_calls == 0, f"the identifier was resolved after a {label} refusal"


def test_the_identifier_source_is_called_exactly_once_in_order() -> None:
    harness = Harness()
    harness.run()
    assert harness.secret_id_calls == 1
    order = harness.stages.order
    assert (
        order.index("bucket")
        < order.index("secret-id")
        < order.index("secrets-client")
        < order.index("credential")
    )


def test_a_raising_identifier_source_is_a_sanitized_refusal() -> None:
    harness = Harness(secret_id_raises=RuntimeError(CANARY_SECRET_ID))
    with pytest.raises(bp.BindingPreflightError) as raised:
        harness.run()
    assert raised.value.outcome is bp.PreflightOutcome.REFUSED_SECRET_IDENTIFIER
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    rendered = f"{raised.value!r} {raised.value!s}"
    assert CANARY_SECRET_ID not in rendered
    assert harness.secrets_factory_calls == 0
    assert harness.secrets.calls == 0


class HostileString(str):
    """A ``str`` subclass. Exact-type checks must refuse it."""


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("None", None),
        ("empty", ""),
        ("blank", "   "),
        ("integer", 7),
        ("bytes", b"abc"),
        ("list", ["x"]),
        ("str subclass", HostileString("synthetic-subclassed-identifier")),
    ],
)
def test_an_unusable_identifier_is_refused_before_the_backend(label: str, value: Any) -> None:
    harness = Harness(secret_id_value=value)
    with pytest.raises(bp.BindingPreflightError) as raised:
        harness.run()
    assert raised.value.outcome is bp.PreflightOutcome.REFUSED_SECRET_IDENTIFIER
    assert harness.secrets_factory_calls == 0, f"a {label} identifier built a client"
    assert harness.secrets.calls == 0, f"a {label} identifier reached the backend"


def test_the_identifier_never_appears_in_any_observable_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = Harness()
    result = harness.run()
    captured = capsys.readouterr()
    rendered = f"{result!r} {result!s} {captured.out} {captured.err}"
    assert CANARY_SECRET_ID not in rendered
    assert bp.SECRET_ID_ENV_VAR not in rendered, "even the variable name is not printed"


#: Variables the standard library reads while formatting a message, whatever the
#: program does. `argparse` consults these for locale and terminal width, and
#: none is a credential lookup.
STDLIB_FORMATTING_VARIABLES = frozenset(
    {"LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG", "COLUMNS", "LINES", "TERM"}
)


def test_the_default_path_reads_no_credential_bearing_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No flag, no credential lookup -- stated as what actually holds.

    A literal "zero environment lookups" would be false and this test says so:
    ``argparse`` reads ``LANGUAGE``, ``LC_ALL``, ``LC_MESSAGES``, ``LANG``,
    ``COLUMNS`` and ``LINES`` while formatting its own output, whatever the
    program does. Those are locale and terminal width, not secrets, and the only
    way to have none of them would be to not use ``argparse``.

    What is checked is the property that matters and is true: **the secret
    identifier's variable is never read on the default path**, and neither is any
    variable outside that stdlib formatting set.
    """
    import os

    observed: list[str] = []
    real = os.environ

    class RecordingEnviron(dict[str, str]):
        def get(self, key: Any = None, default: Any = None) -> Any:
            observed.append(str(key))
            return real.get(str(key), default)

        def __getitem__(self, key: str) -> str:
            observed.append(key)
            return real[key]

        def __contains__(self, key: object) -> bool:
            observed.append(str(key))
            return key in real

    monkeypatch.setattr(os, "environ", RecordingEnviron())
    assert bp.main([]) == 1

    assert bp.SECRET_ID_ENV_VAR not in observed, "the default path read the secret identifier"
    assert "AWS_PROFILE" not in observed, "the default path read the AWS profile"
    unexpected = sorted(set(observed) - STDLIB_FORMATTING_VARIABLES)
    assert unexpected == [], f"the default path read {unexpected}"


def test_no_earlier_refusal_path_reads_the_secret_identifier_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same property one layer in: a refusal at any gate resolves nothing."""
    import os

    observed: list[str] = []
    real = os.environ

    class RecordingEnviron(dict[str, str]):
        def get(self, key: Any = None, default: Any = None) -> Any:
            observed.append(str(key))
            return real.get(str(key), default)

        def __getitem__(self, key: str) -> str:
            observed.append(key)
            return real[key]

    monkeypatch.setattr(os, "environ", RecordingEnviron())
    for harness in (
        Harness(profile="default"),
        Harness(identity_reason="mismatch"),
        Harness(bucket_raises=True),
    ):
        with pytest.raises(bp.BindingPreflightError):
            harness.run()
    assert bp.SECRET_ID_ENV_VAR not in observed


def test_the_production_identifier_source_reads_one_fixed_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The name is a constant and is not a secret; the value is, and it is
    returned to the caller rather than printed."""
    import os

    monkeypatch.setitem(os.environ, bp.SECRET_ID_ENV_VAR, CANARY_SECRET_ID)
    assert bp._environment_secret_id() == CANARY_SECRET_ID

    monkeypatch.delitem(os.environ, bp.SECRET_ID_ENV_VAR, raising=False)
    with pytest.raises(LookupError):
        bp._environment_secret_id()


def test_the_environment_variable_name_holds_no_identifier() -> None:
    """A *name*, committed; the value it holds is private and is not."""
    assert bp.SECRET_ID_ENV_VAR == "KALPAMANI_SHARADAR_SECRET_ID"  # noqa: S105 -- a name
    assert "arn:aws:" not in bp.SECRET_ID_ENV_VAR
    source = ENTRY_POINT.read_text(encoding="utf-8")
    assert "secretsmanager:" not in source


def test_the_entry_point_reads_the_environment_only_inside_a_factory() -> None:
    """``os`` is imported inside function bodies, so an import and every refusal
    path perform no environment lookup at all."""
    tree = _tree(ENTRY_POINT)
    module_level = {
        alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names
    }
    assert "os" not in module_level
    importers = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(inner, ast.Import) and any(a.name == "os" for a in inner.names)
            for inner in ast.walk(node)
        )
    ]
    assert sorted(importers) == ["_ambient_profile", "_environment_secret_id"]


# ---------------------------------------------------------------------------
# ADR-0016 -- three boundaries where there was one
# ---------------------------------------------------------------------------
#
# Two authorized operator attempts were made against the real foundation. The
# first refused at the identity gate. The second passed identity and bucket
# resolution and reported REFUSED_CREDENTIAL -- and the operational virtual
# environment held no `boto3`, so the constructor had raised ModuleNotFoundError
# and *no client existed, so nothing was invoked*. The command reported a
# private-credential failure for a missing local package.
#
# What follows fixes the counts to behaviour. Every assertion about "it was
# invoked" reads `harness.secrets.calls`, which the synthetic client increments
# when it is actually called -- never inferred from which line raised.


class SyntheticBackendError(Exception):
    """Shaped like a backend error: a message naming things that must not travel."""


#: A synthetic account component, built at runtime from a repeated digit so that
#: **no twelve-digit literal is committed anywhere in this repository**. It is
#: not an account, it never was one, and it exists only to give the ARN grammar
#: a well-shaped field to accept.
SYNTHETIC_ACCOUNT: Final = "9" * 12

#: A synthetic secret name and a synthetic **complete** ARN. Assembled here
#: rather than written out, for the same reason.
VALID_NAME_IDENTIFIER: Final = "synthetic/kalpamani/sharadar-canary"
VALID_ARN_IDENTIFIER: Final = (
    f"arn:aws:secretsmanager:us-east-1:{SYNTHETIC_ACCOUNT}:secret:synthetic/canary-AbCd12"
)

#: The ARN this file used before ADR-0016's first correction round. Its account
#: field was the word ``synthetic-account``, and the old "printable, unspaced"
#: rule admitted it -- so a shape no Secrets Manager client would accept reached
#: the client and was rejected locally *after* the method had been entered.
#: Refused now, and kept as a case rather than deleted.
RETIRED_ARN_IDENTIFIER: Final = (
    "arn:aws:secretsmanager:us-east-1:synthetic-account:secret:synthetic-canary"
)


class BoolLike(int):
    """``True`` is an ``int``; an exact-type check must still refuse it."""


#: Every way the identifier source can fail to produce a usable identifier.
#:
#: The ``raises`` cases model a source that is unavailable -- the production one
#: raises ``LookupError`` when its one fixed variable is unset -- and the value
#: cases model one that returns something unusable.
BAD_IDENTIFIERS: tuple[tuple[str, Any, Any], ...] = (
    ("unavailable source", None, LookupError(CANARY_SECRET_ID)),
    ("raising source", None, SyntheticBackendError(CANARY_SECRET_ID)),
    ("None", None, None),
    ("boolean", True, None),
    ("boolean subclass", BoolLike(1), None),
    ("integer", 7, None),
    ("bytes", b"synthetic", None),
    ("list", ["synthetic"], None),
    ("str subclass", HostileString("synthetic-subclassed-identifier"), None),
    ("empty string", "", None),
    ("whitespace only", "   ", None),
    ("malformed name", "synthetic name with spaces", None),
    ("embedded newline", "synthetic\nsecond-parameter", None),
    ("malformed ARN shape", "arn:aws:secretsmanager:us-east-1: :secret:synthetic", None),
    ("the retired synthetic-account ARN", RETIRED_ARN_IDENTIFIER, None),
)


@pytest.mark.parametrize(
    ("label", "value", "raises"), BAD_IDENTIFIERS, ids=[case[0] for case in BAD_IDENTIFIERS]
)
def test_an_identifier_failure_is_its_own_outcome_and_sends_nothing(
    label: str, value: Any, raises: Any
) -> None:
    """The identifier stage owns its refusal, and nothing downstream has run.

    Before ADR-0016 every one of these was ``REFUSED_CREDENTIAL`` -- an operator
    told the private credential could not be retrieved when no client existed
    and no client existed to invoke.
    """
    harness = Harness(secret_id_value=value, secret_id_raises=raises)
    with pytest.raises(bp.BindingPreflightError) as refusal:
        harness.run()
    assert refusal.value.outcome is bp.PreflightOutcome.REFUSED_SECRET_IDENTIFIER, label
    assert harness.secret_id_calls == 1
    assert harness.secrets_factory_calls == 0, "a client was constructed for a bad identifier"
    assert harness.secrets.calls == 0, "a bad identifier reached an invocation"
    assert harness.stages.order == ["profile", "identity", "bucket", "secret-id"]


@pytest.mark.parametrize(
    ("label", "value", "raises"), BAD_IDENTIFIERS, ids=[case[0] for case in BAD_IDENTIFIERS]
)
def test_an_identifier_failure_discloses_neither_value_nor_cause(
    label: str, value: Any, raises: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = Harness(secret_id_value=value, secret_id_raises=raises)
    with pytest.raises(bp.BindingPreflightError) as refusal:
        harness.run()
    captured = capsys.readouterr()
    rendered = f"{refusal.value!r} {refusal.value!s} {captured.out} {captured.err}"
    assert refusal.value.__cause__ is None, label
    assert refusal.value.__suppress_context__ is True
    for canary in CANARIES:
        assert canary not in rendered, f"{label} disclosed {canary}"
    for shape in (VALID_NAME_IDENTIFIER, VALID_ARN_IDENTIFIER, "synthetic"):
        assert shape not in rendered, f"{label} echoed the identifier it was given"


@pytest.mark.parametrize("identifier", [VALID_NAME_IDENTIFIER, VALID_ARN_IDENTIFIER])
def test_a_usable_identifier_shape_reaches_the_backend_exactly_once(identifier: str) -> None:
    """A name and an ARN are both accepted, and each yields one invocation.

    The complement of the refusals above: a guard that refused everything would
    also satisfy them.
    """
    harness = Harness(secret_id_value=identifier)
    harness.run()
    assert harness.secret_id_calls == 1
    assert harness.secrets_factory_calls == 1
    assert harness.secrets.calls == 1
    assert harness.secrets.secret_ids == [identifier]


# -- the dependency boundary -------------------------------------------------
#
# The operational finding, reproduced synthetically. None of these installs,
# imports or requires the real SDK: an absent `boto3` is a `ModuleNotFoundError`
# raised by a factory, which is exactly what the real factory does on a machine
# without it.

#: Every way a local dependency can fail while the client is being constructed.
DEPENDENCY_FAILURES: tuple[tuple[str, Exception], ...] = (
    ("absent boto3", ModuleNotFoundError(f"No module named 'boto3' {CANARY_BACKEND}")),
    ("absent botocore", ModuleNotFoundError(f"No module named 'botocore' {CANARY_BACKEND}")),
    ("raising SDK import", ImportError(CANARY_BACKEND)),
    ("factory not callable", TypeError(f"'NoneType' object is not callable {CANARY_BACKEND}")),
    ("client construction failure", SyntheticBackendError(CANARY_BACKEND)),
    ("unexpected dependency error", RuntimeError(CANARY_BACKEND)),
)


@pytest.mark.parametrize(
    ("label", "failure"), DEPENDENCY_FAILURES, ids=[case[0] for case in DEPENDENCY_FAILURES]
)
def test_a_client_construction_failure_is_a_dependency_refusal(
    label: str, failure: Exception
) -> None:
    """**The defect ADR-0016 corrects, stated as a count.**

    An absent SDK produces ``REFUSED_DEPENDENCY`` and *zero* ``get_secret_value``
    invocations. The identifier was resolved -- that stage passed -- and nothing
    beyond the constructor ran, so no client exists to invoke or to reach AWS
    with.
    """
    harness = Harness(secrets_factory_raises=failure)
    with pytest.raises(bp.BindingPreflightError) as refusal:
        harness.run()
    assert refusal.value.outcome is bp.PreflightOutcome.REFUSED_DEPENDENCY, label
    assert harness.secret_id_calls == 1
    assert harness.secrets_factory_calls == 1
    assert harness.secrets.calls == 0, f"{label} reached an invocation"
    assert harness.stages.order == ["profile", "identity", "bucket", "secret-id", "secrets-client"]
    assert (harness.s3.put_calls, harness.s3.head_calls, harness.transport.calls) == (0, 0, 0)


@pytest.mark.parametrize(
    ("label", "failure"), DEPENDENCY_FAILURES, ids=[case[0] for case in DEPENDENCY_FAILURES]
)
def test_a_dependency_failure_discloses_no_underlying_text(
    label: str, failure: Exception, capsys: pytest.CaptureFixture[str]
) -> None:
    """An import error names a path; a client constructor names a profile or a region."""
    harness = Harness(secrets_factory_raises=failure)
    with pytest.raises(bp.BindingPreflightError) as refusal:
        harness.run()
    captured = capsys.readouterr()
    rendered = f"{refusal.value!r} {refusal.value!s} {captured.out} {captured.err}"
    assert refusal.value.__cause__ is None, label
    assert refusal.value.__suppress_context__ is True
    assert CANARY_BACKEND not in rendered, f"{label} echoed the dependency exception"
    for forbidden in ("boto3", "botocore", "No module named", "not callable"):
        assert forbidden not in rendered, f"{label} named the dependency"


@pytest.mark.parametrize(
    ("label", "client"),
    [
        ("no such attribute", object()),
        ("attribute is not callable", UnusableSecretsClient()),
        ("client is None", None),
    ],
)
def test_a_constructed_client_that_cannot_serve_the_operation_is_a_dependency_refusal(
    label: str, client: Any
) -> None:
    """Construction succeeded and the object still cannot serve an invocation.

    The secrets boundary calls this ``CLIENT_UNUSABLE``, and that is a fact
    about a dependency. Routing it to the credential would claim a retrieval no
    object here could have performed.
    """
    harness = Harness(secrets_client_override=client)
    with pytest.raises(bp.BindingPreflightError) as refusal:
        harness.run()
    assert refusal.value.outcome is bp.PreflightOutcome.REFUSED_DEPENDENCY, label
    assert harness.secrets_factory_calls == 1
    assert harness.secrets.calls == 0


def test_an_unimportable_secrets_boundary_is_a_dependency_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The boundary module is itself a local dependency.

    Replacing it with an object that does not carry the names the entry point
    imports makes ``from ... import ...`` raise, without touching the real
    module: ``monkeypatch`` restores ``sys.modules`` afterwards.
    """
    monkeypatch.setitem(sys.modules, "kalpamani.data.ingest.sharadar.secrets", object())
    harness = Harness()
    with pytest.raises(bp.BindingPreflightError) as refusal:
        harness.run()
    assert refusal.value.outcome is bp.PreflightOutcome.REFUSED_DEPENDENCY
    assert harness.secret_id_calls == 0, "an identifier was resolved for an unusable dependency"
    assert harness.secrets_factory_calls == 0
    assert harness.secrets.calls == 0


def test_a_late_dependency_failure_is_still_a_dependency_refusal() -> None:
    """Stage 8 runs *after* a successful retrieval and is still not a credential fact.

    The count is the point: one invocation genuinely happened here, and the
    outcome still says what actually failed.
    """

    def failing_transport() -> Any:
        raise SyntheticBackendError(CANARY_BACKEND)

    harness = Harness()
    with pytest.raises(bp.BindingPreflightError) as refusal:
        bp.run_binding_preflight(
            authorization=bp._BINDING_PREFLIGHT_AUTHORIZATION,
            subjects=("SYNTH",),
            execution_id="synthetic-execution-0001",
            profile_of=harness.profile_of,
            identity_gate=harness.identity_gate,
            resolve_licensed_bucket=harness.resolve_bucket,
            secret_id_source=harness.secret_id_source,
            secrets_client_factory=harness.secrets_factory,
            s3_client_factory=harness.s3_factory,
            transport_factory=failing_transport,
        )
    assert refusal.value.outcome is bp.PreflightOutcome.REFUSED_DEPENDENCY
    assert harness.secrets.calls == 1
    assert CANARY_BACKEND not in f"{refusal.value!r} {refusal.value!s}"


# -- the credential boundary -------------------------------------------------
#
# Reserved for a genuine retrieval: the one invocation raised, or what came back
# was not a credential. Every case here witnesses exactly one attempt.

#: Every way a secret response can be unusable, and the closed member each yields.
BAD_RESPONSES: tuple[tuple[str, Any, SecretRetrievalFailure], ...] = (
    ("empty mapping", {}, SecretRetrievalFailure.RESPONSE_MALFORMED),
    ("binary only", {"SecretBinary": b"\x00\x01"}, SecretRetrievalFailure.SECRET_BINARY_REFUSED),
    ("blank string", {"SecretString": "   "}, SecretRetrievalFailure.SECRET_VALUE_UNUSABLE),
    ("empty string", {"SecretString": ""}, SecretRetrievalFailure.SECRET_VALUE_UNUSABLE),
    ("null value", {"SecretString": None}, SecretRetrievalFailure.RESPONSE_MALFORMED),
    ("integer value", {"SecretString": 7}, SecretRetrievalFailure.RESPONSE_MALFORMED),
    ("bytes value", {"SecretString": b"abc"}, SecretRetrievalFailure.RESPONSE_MALFORMED),
    (
        "whitespace-bearing value",
        {"SecretString": "a b"},
        SecretRetrievalFailure.SECRET_VALUE_UNUSABLE,
    ),
    (
        "control character",
        {"SecretString": "abc\ndef"},
        SecretRetrievalFailure.SECRET_VALUE_UNUSABLE,
    ),
    ("not a mapping", 7, SecretRetrievalFailure.RESPONSE_MALFORMED),
)

#: Backend refusals, named the way an operator would see them.
BACKEND_REFUSALS: tuple[tuple[str, Exception], ...] = (
    ("access denied", SyntheticBackendError(f"AccessDeniedException {CANARY_BACKEND}")),
    ("resource not found", SyntheticBackendError(f"ResourceNotFoundException {CANARY_BACKEND}")),
    ("expired session", SyntheticBackendError(f"ExpiredTokenException {CANARY_BACKEND}")),
    ("throttled", SyntheticBackendError(f"ThrottlingException {CANARY_BACKEND}")),
    ("transient SDK error", SyntheticBackendError(f"EndpointConnectionError {CANARY_BACKEND}")),
)


@pytest.mark.parametrize(
    ("label", "failure"), BACKEND_REFUSALS, ids=[case[0] for case in BACKEND_REFUSALS]
)
def test_a_backend_refusal_is_a_credential_refusal_after_exactly_one_attempt(
    label: str, failure: Exception, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = Harness(secrets_client=CountingSecretsClient(raises=failure))
    with pytest.raises(bp.BindingPreflightError) as refusal:
        harness.run()
    captured = capsys.readouterr()
    assert refusal.value.outcome is bp.PreflightOutcome.REFUSED_CREDENTIAL, label
    assert harness.secrets.calls == 1, f"{label} did not witness exactly one attempt"
    rendered = f"{refusal.value!r} {refusal.value!s} {captured.out} {captured.err}"
    assert CANARY_BACKEND not in rendered
    assert refusal.value.__cause__ is None


@pytest.mark.parametrize(
    ("label", "response", "failure"), BAD_RESPONSES, ids=[case[0] for case in BAD_RESPONSES]
)
def test_an_unusable_response_is_a_credential_refusal_after_exactly_one_attempt(
    label: str, response: Any, failure: Any
) -> None:
    """A malformed response, an absent ``SecretString``, binary, or a value the
    credential contract refuses -- all reached by asking, all credential facts."""
    harness = Harness(secrets_client=CountingSecretsClient(response=response))
    with pytest.raises(bp.BindingPreflightError) as refusal:
        harness.run()
    assert refusal.value.outcome is bp.PreflightOutcome.REFUSED_CREDENTIAL, label
    assert harness.secrets.calls == 1, f"{label} did not witness exactly one attempt"
    assert (harness.s3.put_calls, harness.s3.head_calls, harness.transport.calls) == (0, 0, 0)


def test_a_valid_synthetic_secret_completes_with_one_attempt() -> None:
    client = CountingSecretsClient(response={"SecretString": CANARY_SECRET})
    harness = Harness(secrets_client=client)
    result = harness.run()
    assert str(result.status) == "VALIDATED_OFFLINE"
    assert harness.secrets.calls == 1


# -- the closed mapping ------------------------------------------------------


def test_every_secrets_boundary_failure_is_classified() -> None:
    """Total over the boundary's vocabulary, with no default doing the work.

    A member with no entry would fall to the classifier's structural default and
    be reported as a credential failure -- which is the defect, not a way to
    express it. Adding one to ``SecretRetrievalFailure`` fails here first.
    """
    assert {member.value for member in SecretRetrievalFailure} == set(bp.SECRET_FAILURE_OUTCOME)


def test_the_pre_invocation_failures_are_never_credential_failures() -> None:
    """The two the boundary raises *before* it invokes the client."""
    assert bp.SECRET_FAILURE_OUTCOME["CLIENT_UNUSABLE"] is bp.PreflightOutcome.REFUSED_DEPENDENCY
    assert (
        bp.SECRET_FAILURE_OUTCOME["SECRET_IDENTIFIER_MALFORMED"]
        is bp.PreflightOutcome.REFUSED_SECRET_IDENTIFIER
    )


def test_the_post_invocation_failures_are_credential_failures() -> None:
    for token in (
        "BACKEND_REFUSED",
        "RESPONSE_MALFORMED",
        "SECRET_BINARY_REFUSED",
        "SECRET_VALUE_UNUSABLE",
    ):
        assert bp.SECRET_FAILURE_OUTCOME[token] is bp.PreflightOutcome.REFUSED_CREDENTIAL


def test_the_outcome_vocabulary_is_exactly_these_members() -> None:
    """Closed, and closed against an alias too.

    A second spelling of an existing outcome would let one stage's refusal be
    reported under another stage's name, which is what ADR-0016 corrects.
    """
    assert {member.name for member in bp.PreflightOutcome} == {
        "REFUSED_NOT_AUTHORIZED",
        "REFUSED_PROFILE",
        "REFUSED_IDENTITY",
        "REFUSED_BUCKET",
        "REFUSED_SECRET_IDENTIFIER",
        "REFUSED_DEPENDENCY",
        "REFUSED_UNCLASSIFIED",
        "REFUSED_CREDENTIAL",
        "REFUSED_PLAN",
        "REFUSED_OPTION",
        "COMPLETED",
        "VALIDATION_COMPLETED",
    }
    assert len({member.value for member in bp.PreflightOutcome}) == len(bp.PreflightOutcome)


def test_the_superseded_plural_member_is_gone() -> None:
    """``REFUSED_DEPENDENCIES`` is renamed, not aliased. No synonym survives."""
    assert not hasattr(bp.PreflightOutcome, "REFUSED_DEPENDENCIES")
    assert "REFUSED_DEPENDENCIES" not in ENTRY_POINT.read_text(encoding="utf-8")


def test_no_refusal_before_the_invocation_is_worded_as_a_credential_failure() -> None:
    """The sentences an operator reads must not point at the wrong system."""
    for member in (
        bp.PreflightOutcome.REFUSED_SECRET_IDENTIFIER,
        bp.PreflightOutcome.REFUSED_DEPENDENCY,
        bp.PreflightOutcome.REFUSED_UNCLASSIFIED,
    ):
        assert "credential" not in member.value
    assert "credential" in bp.PreflightOutcome.REFUSED_CREDENTIAL.value


# -- the invocation-count table -------------------------------------------------


def _counts(harness: Harness) -> tuple[int, int, int]:
    """Identifier resolutions, client constructions, ``get_secret_value`` invocations."""
    return (harness.secret_id_calls, harness.secrets_factory_calls, harness.secrets.calls)


def test_every_outcome_has_its_witnessed_call_counts() -> None:
    """The table in the entry point's docstring, asserted rather than described.

    Each row is produced by driving the preflight, not by reading the source: a
    count claimed from which stage raised is the inference that produced a false
    report in production.
    """
    unauthorized = Harness()
    with pytest.raises(bp.BindingPreflightError):
        unauthorized.run(authorization=None)
    assert _counts(unauthorized) == (0, 0, 0)

    for label, harness in (
        ("profile", Harness(profile="default")),
        ("identity", Harness(identity_reason="mismatch")),
        ("bucket", Harness(bucket_raises=True)),
    ):
        with pytest.raises(bp.BindingPreflightError):
            harness.run()
        assert _counts(harness) == (0, 0, 0), label

    boundary = Harness()
    with pytest.raises(bp.BindingPreflightError) as refused_import:
        with pytest.MonkeyPatch.context() as patch:
            patch.setitem(sys.modules, "kalpamani.data.ingest.sharadar.secrets", object())
            boundary.run()
    assert refused_import.value.outcome is bp.PreflightOutcome.REFUSED_DEPENDENCY
    assert _counts(boundary) == (0, 0, 0), "the boundary import refuses before the identifier"

    identifier = Harness(secret_id_value=None)
    with pytest.raises(bp.BindingPreflightError) as refused_identifier:
        identifier.run()
    assert refused_identifier.value.outcome is bp.PreflightOutcome.REFUSED_SECRET_IDENTIFIER
    assert _counts(identifier) == (1, 0, 0)

    dependency = Harness(secrets_factory_raises=ModuleNotFoundError("No module named 'boto3'"))
    with pytest.raises(bp.BindingPreflightError) as refused_dependency:
        dependency.run()
    assert refused_dependency.value.outcome is bp.PreflightOutcome.REFUSED_DEPENDENCY
    assert _counts(dependency) == (1, 1, 0)

    credential = Harness(secrets_client=CountingSecretsClient(response={}))
    with pytest.raises(bp.BindingPreflightError) as refused_credential:
        credential.run()
    assert refused_credential.value.outcome is bp.PreflightOutcome.REFUSED_CREDENTIAL
    assert _counts(credential) == (1, 1, 1)

    def failing_transport() -> Any:
        raise SyntheticBackendError(CANARY_BACKEND)

    late = Harness()
    with pytest.raises(bp.BindingPreflightError) as refused_late:
        bp.run_binding_preflight(
            authorization=bp._BINDING_PREFLIGHT_AUTHORIZATION,
            subjects=("SYNTH",),
            execution_id="synthetic-execution-0001",
            profile_of=late.profile_of,
            identity_gate=late.identity_gate,
            resolve_licensed_bucket=late.resolve_bucket,
            secret_id_source=late.secret_id_source,
            secrets_client_factory=late.secrets_factory,
            s3_client_factory=late.s3_factory,
            transport_factory=failing_transport,
        )
    assert refused_late.value.outcome is bp.PreflightOutcome.REFUSED_DEPENDENCY
    assert _counts(late) == (1, 1, 1), "a dependency refusal after a real invocation"

    completed = Harness()
    completed.run()
    assert _counts(completed) == (1, 1, 1)


def test_the_refusing_default_path_needs_neither_the_sdk_nor_the_package() -> None:
    """The path an operator hits with no flag must not depend on what is installed.

    Every ``kalpamani`` import in the entry point sits inside a function body, so
    a refusal on a machine with a broken environment is still a clean refusal
    rather than a traceback. The defect was found on exactly such a machine.
    """
    module_level = ast.unparse(
        ast.Module(
            body=[n for n in _tree(ENTRY_POINT).body if isinstance(n, ast.Import | ast.ImportFrom)],
            type_ignores=[],
        )
    )
    assert "kalpamani" not in module_level
    assert "boto3" not in module_level


# -- the identifier grammar --------------------------------------------------
#
# The first correction round's rule was "an exact printable str with no
# whitespace", and it said so: "nothing about vendor or AWS naming is inferred".
# That is too broad for a Secrets Manager `SecretId`. It let malformed
# identifiers through to the client, which rejects them locally -- after
# `get_secret_value` has been entered, which is then one invocation, which then
# looks like a credential boundary failure. The grammar is the fix.


def _arn(
    *,
    partition: str = "aws",
    service: str = "secretsmanager",
    region: str = "us-east-1",
    account: str = SYNTHETIC_ACCOUNT,
    resource_type: str = "secret",
    name: str = "synthetic/canary-AbCd12",
) -> str:
    """A synthetic ARN with one field replaced. Never a real one."""
    return f"arn:{partition}:{service}:{region}:{account}:{resource_type}:{name}"


#: Every identifier shape the grammar must admit.
USABLE_IDENTIFIERS: tuple[tuple[str, str], ...] = (
    ("plain name", "synthetic-canary"),
    ("path-shaped name", VALID_NAME_IDENTIFIER),
    ("every permitted punctuation", "synthetic/_+=.@-canary"),
    ("single character", "s"),
    ("maximum-length name", "s" * MAX_SECRET_NAME_LENGTH),
    ("complete ARN", VALID_ARN_IDENTIFIER),
    ("complete ARN, china partition", _arn(partition="aws-cn", region="cn-north-1")),
    ("complete ARN, govcloud partition", _arn(partition="aws-us-gov", region="us-gov-west-1")),
    ("complete ARN, multi-part region", _arn(region="ap-southeast-2")),
)


@pytest.mark.parametrize(
    ("label", "identifier"), USABLE_IDENTIFIERS, ids=[c[0] for c in USABLE_IDENTIFIERS]
)
def test_the_grammar_admits_every_well_formed_identifier(label: str, identifier: str) -> None:
    """The complement of the refusals below: a validator that refused
    everything would satisfy them and be useless."""
    assert is_usable_secret_identifier(identifier), label


#: Every identifier shape the grammar must refuse, and why.
UNUSABLE_IDENTIFIERS: tuple[tuple[str, Any], ...] = (
    ("the retired synthetic-account ARN", RETIRED_ARN_IDENTIFIER),
    ("wrong service", _arn(service="ssm")),
    ("wrong resource type", _arn(resource_type="parameter")),
    ("unknown partition", _arn(partition="aws-not-a-partition")),
    ("missing region", _arn(region="")),
    ("malformed region", _arn(region="useast1")),
    ("region with digits in the wrong place", _arn(region="us-east-")),
    ("missing account", _arn(account="")),
    ("nondigit account", _arn(account="9" * 11 + "a")),
    ("too-short account", _arn(account="9" * 11)),
    ("too-long account", _arn(account="9" * 13)),
    ("partial ARN, no generated suffix", _arn(name="synthetic")),
    ("partial ARN, short suffix", _arn(name="synthetic-AbCd1")),
    ("partial ARN, non-alphanumeric suffix", _arn(name="synthetic-AbCd_1")),
    ("missing secret resource", f"arn:aws:secretsmanager:us-east-1:{SYNTHETIC_ACCOUNT}:secret"),
    ("extra ARN field", _arn() + ":extra"),
    ("invalid resource characters", _arn(name="synthetic canary-AbCd12")),
    ("invalid name punctuation", "synthetic!canary"),
    ("name with a comma", "synthetic,canary"),
    ("name with a colon", "synthetic:canary"),
    ("name with whitespace", "synthetic canary"),
    ("name with a newline", "synthetic\ncanary"),
    ("name with a control character", "synthetic\x00canary"),
    ("name with a non-ASCII letter", "synthetic-canaré"),
    ("empty", ""),
    ("blank", "   "),
    ("oversized name", "s" * (MAX_SECRET_NAME_LENGTH + 1)),
    ("oversized ARN", _arn(name="s" * MAX_SECRET_ID_LENGTH + "-AbCd12")),
    ("str subclass", HostileString("synthetic-canary")),
    ("None", None),
    ("integer", 7),
    ("bytes", b"synthetic-canary"),
)


@pytest.mark.parametrize(
    ("label", "identifier"), UNUSABLE_IDENTIFIERS, ids=[c[0] for c in UNUSABLE_IDENTIFIERS]
)
def test_the_grammar_refuses_every_malformed_identifier(label: str, identifier: Any) -> None:
    assert not is_usable_secret_identifier(identifier), label


@pytest.mark.parametrize(
    ("label", "identifier"), UNUSABLE_IDENTIFIERS, ids=[c[0] for c in UNUSABLE_IDENTIFIERS]
)
def test_a_malformed_identifier_never_reaches_a_client(label: str, identifier: Any) -> None:
    """Refused at stage 6, so the client stage never runs and nothing is invoked."""
    harness = Harness(secret_id_value=identifier)
    with pytest.raises(bp.BindingPreflightError) as refusal:
        harness.run()
    assert refusal.value.outcome is bp.PreflightOutcome.REFUSED_SECRET_IDENTIFIER, label
    assert harness.secrets_factory_calls == 0
    assert harness.secrets.calls == 0


def test_the_grammar_transforms_nothing() -> None:
    """It answers a question about the identifier and returns nothing else.

    A validator that trimmed, normalised or rebuilt would be a validator whose
    verdict was about a different string from the one that gets used.
    """
    source = inspect.getsource(is_usable_secret_identifier)
    for transform in (".strip()", ".lower()", ".upper()", ".replace(", "return candidate"):
        assert transform not in source, f"the validator {transform}"
    assert is_usable_secret_identifier(VALID_NAME_IDENTIFIER) is True
    assert is_usable_secret_identifier(f" {VALID_NAME_IDENTIFIER} ") is False


# -- the classifier, adversarially -------------------------------------------
#
# `REFUSED_CREDENTIAL` must be reachable only through an explicit mapping entry
# naming a member known to follow an admitted invocation. The first revision had
# two defaults that produced it for an unreadable token and an unmapped one --
# neither of which establishes that anything was invoked.


class BrokenFailure:
    """A ``failure`` object with no ``value``."""


class HostileFailureError(SecretRetrievalError):
    """A boundary refusal whose own attribute access raises.

    The parent assigns ``failure`` in ``__init__``; this deliberately does not
    call it, so the property below is what a reader gets.
    """

    def __init__(self) -> None:
        Exception.__init__(self, "synthetic hostile refusal")

    @property
    def failure(self) -> Any:  # type: ignore[override]
        raise SyntheticBackendError(CANARY_BACKEND)


def _refusal_with(failure: Any) -> SecretRetrievalError:
    """A boundary refusal carrying ``failure``, whatever that is.

    The class normalises a non-member at construction, so the slot is set
    afterwards -- which is the point: this models a *future* boundary raising
    something this program has never seen.
    """
    refusal = SecretRetrievalError(SecretRetrievalFailure.BACKEND_REFUSED)
    refusal.failure = failure
    return refusal


def _absent_failure() -> SecretRetrievalError:
    refusal = SecretRetrievalError(SecretRetrievalFailure.BACKEND_REFUSED)
    del refusal.failure
    return refusal


#: Every refusal this program cannot classify.
UNCLASSIFIABLE_REFUSALS: tuple[tuple[str, Any], ...] = (
    ("no failure attribute", _absent_failure),
    ("failure without a value", lambda: _refusal_with(BrokenFailure())),
    ("non-string token", lambda: _refusal_with(SimpleNamespace(value=7))),
    ("token is a str subclass", lambda: _refusal_with(SimpleNamespace(value=HostileString("X")))),
    ("unknown string token", lambda: _refusal_with(SimpleNamespace(value="SECRET_SOMETHING_NEW"))),
    ("hostile attribute access", HostileFailureError),
)


@pytest.mark.parametrize(
    ("label", "build"), UNCLASSIFIABLE_REFUSALS, ids=[c[0] for c in UNCLASSIFIABLE_REFUSALS]
)
def test_an_unclassifiable_refusal_never_claims_a_credential(label: str, build: Any) -> None:
    """Not knowing has its own word, and it is not the credential's."""
    assert bp._secret_failure_outcome(build()) is bp.PreflightOutcome.REFUSED_UNCLASSIFIED, label


@pytest.mark.parametrize(
    ("label", "build"), UNCLASSIFIABLE_REFUSALS, ids=[c[0] for c in UNCLASSIFIABLE_REFUSALS]
)
def test_an_unclassifiable_refusal_surfaces_without_disclosure(
    label: str, build: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end, through the preflight, with nothing controlled disclosed.

    The boundary is replaced so the refusal arrives from where a real one would.
    Its invocation count is reported as what it is -- zero, because the
    replacement never touches the client -- and never inferred to be one.
    """
    harness = Harness()

    def refuse(**_: Any) -> Any:
        raise build()

    monkeypatch.setattr(
        "kalpamani.data.ingest.sharadar.secrets.sharadar_credential_from_secret", refuse
    )
    with pytest.raises(bp.BindingPreflightError) as refusal:
        harness.run()
    captured = capsys.readouterr()
    assert refusal.value.outcome is bp.PreflightOutcome.REFUSED_UNCLASSIFIED, label
    assert refusal.value.__cause__ is None
    assert refusal.value.__suppress_context__ is True
    assert harness.secrets.calls == 0, "the witnessed count is zero and is reported as zero"
    rendered = f"{refusal.value!r} {refusal.value!s} {captured.out} {captured.err}"
    for canary in CANARIES:
        assert canary not in rendered, f"{label} disclosed {canary}"


def test_an_unexpected_exception_from_the_boundary_is_a_dependency_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An exception of an unknown type does not establish that anything was invoked.

    The boundary raises only closed members, so an escape means something local
    is broken. It used to answer ``REFUSED_CREDENTIAL``, which asserted an
    invocation the exception says nothing about.
    """
    harness = Harness()

    def explode(**_: Any) -> Any:
        raise SyntheticBackendError(CANARY_BACKEND)

    monkeypatch.setattr(
        "kalpamani.data.ingest.sharadar.secrets.sharadar_credential_from_secret", explode
    )
    with pytest.raises(bp.BindingPreflightError) as refusal:
        harness.run()
    captured = capsys.readouterr()
    assert refusal.value.outcome is bp.PreflightOutcome.REFUSED_DEPENDENCY
    assert harness.secrets.calls == 0
    rendered = f"{refusal.value!r} {refusal.value!s} {captured.out} {captured.err}"
    assert CANARY_BACKEND not in rendered


def test_the_classifier_has_no_credential_default() -> None:
    """Structural, not behavioural: the two defaults must not come back.

    ``.get(token, REFUSED_CREDENTIAL)`` and a bare non-string branch returning
    the credential outcome are both invisible to a totality test -- they only
    fire on inputs a totality test proves cannot exist *today*.
    """
    source = inspect.getsource(bp._secret_failure_outcome)
    body = source.split('"""')[-1]
    assert "REFUSED_CREDENTIAL" not in body, "the classifier body names the credential outcome"
    assert body.count("REFUSED_UNCLASSIFIED") == 3
    assert ".get(token)" in body, "an explicit None check, not a default"


def test_credential_is_reachable_only_from_the_four_mapped_members() -> None:
    """Every token that yields ``REFUSED_CREDENTIAL``, enumerated exhaustively."""
    yielding = {
        token
        for token, outcome in bp.SECRET_FAILURE_OUTCOME.items()
        if outcome is bp.PreflightOutcome.REFUSED_CREDENTIAL
    }
    assert yielding == {
        "BACKEND_REFUSED",
        "RESPONSE_MALFORMED",
        "SECRET_BINARY_REFUSED",
        "SECRET_VALUE_UNUSABLE",
    }
    for token in yielding:
        assert bp._secret_failure_outcome(_refusal_with(SimpleNamespace(value=token))) is (
            bp.PreflightOutcome.REFUSED_CREDENTIAL
        )


def test_a_non_member_outcome_is_unclassified_rather_than_a_dependency_claim() -> None:
    """``BindingPreflightError``'s own fallback, which used to assert a dependency."""
    assert (
        bp.BindingPreflightError("not-a-member").outcome is bp.PreflightOutcome.REFUSED_UNCLASSIFIED
    )


# ---------------------------------------------------------------------------
# 8, 10 -- the secrets boundary
# ---------------------------------------------------------------------------


def test_a_secret_string_becomes_a_credential_and_nothing_else() -> None:
    client = CountingSecretsClient()
    credential = sharadar_credential_from_secret(client=client, secret_id=CANARY_SECRET_ID)
    assert type(credential) is SharadarCredential
    assert repr(credential) == CREDENTIAL_PLACEHOLDER
    assert client.calls == 1
    assert client.secret_ids == [CANARY_SECRET_ID]


@pytest.mark.parametrize(
    ("label", "response", "failure"), BAD_RESPONSES, ids=[c[0] for c in BAD_RESPONSES]
)
def test_every_unusable_secret_response_is_refused(
    label: str, response: Any, failure: SecretRetrievalFailure
) -> None:
    client = CountingSecretsClient(response=response)
    with pytest.raises(SecretRetrievalError) as raised:
        sharadar_credential_from_secret(client=client, secret_id=CANARY_SECRET_ID)
    assert raised.value.failure is failure


def test_a_client_that_cannot_serve_the_operation_is_refused() -> None:
    with pytest.raises(SecretRetrievalError) as raised:
        sharadar_credential_from_secret(client=object(), secret_id=CANARY_SECRET_ID)  # type: ignore[arg-type]
    assert raised.value.failure is SecretRetrievalFailure.CLIENT_UNUSABLE


@pytest.mark.parametrize("identifier", [None, "", "   ", 7, "has space", "has\nnewline"])
def test_a_malformed_secret_identifier_is_refused_before_the_backend(identifier: Any) -> None:
    client = CountingSecretsClient()
    with pytest.raises(SecretRetrievalError) as raised:
        sharadar_credential_from_secret(client=client, secret_id=identifier)
    assert raised.value.failure is SecretRetrievalFailure.SECRET_IDENTIFIER_MALFORMED
    assert client.calls == 0


def test_every_secret_refusal_is_raised_from_none() -> None:
    """A suppressed cause is what keeps the backend's own message -- which quotes
    the secret name and often the ARN -- out of the traceback."""
    client = CountingSecretsClient(raises=RuntimeError(CANARY_BACKEND))
    with pytest.raises(SecretRetrievalError) as raised:
        sharadar_credential_from_secret(client=client, secret_id=CANARY_SECRET_ID)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_the_secrets_module_imports_no_sdk_and_constructs_no_client() -> None:
    source = _executable(SECRETS_MODULE)
    for forbidden in ("boto3", "botocore", "import os", "open(", "environ"):
        assert forbidden not in source
    assert "get_secret_value" in source
    for never_called in ("list_secrets", "describe_secret", "put_secret_value", "delete_secret"):
        assert never_called not in source


# -- the construction contract, adversarially --------------------------------
#
# ADR-0016 round 2. `SecretRetrievalError.__init__` normalised any non-member to
# `RESPONSE_MALFORMED`, and `RESPONSE_MALFORMED` maps to `REFUSED_CREDENTIAL`
# because that member is only reachable *after* an admitted invocation. So a
# bare string, a `str` subclass, `None`, an integer or any other object handed to
# the constructor silently acquired a member asserting an invocation nobody
# witnessed -- the last credential-default path, sitting behind the round-1
# invariant that said there were none.


class HostileFailureValue:
    """An object whose every attribute access raises.

    Handed to the constructor, it must be normalised by an exact-type check that
    never touches it -- not by anything that reads `.value` or `.name`.
    """

    def __getattr__(self, name: str) -> Any:
        raise SyntheticBackendError(CANARY_BACKEND)


#: Every non-member a caller could hand the boundary's error type.
NON_MEMBER_FAILURES: tuple[tuple[str, Any], ...] = (
    ("credential-mapped token as a bare string", "RESPONSE_MALFORMED"),
    ("another credential-mapped token", "BACKEND_REFUSED"),
    ("a token nobody has defined", "SECRET_SOMETHING_NEW"),
    ("str subclass of a credential token", HostileString("RESPONSE_MALFORMED")),
    ("None", None),
    ("integer", 7),
    ("bytes", b"RESPONSE_MALFORMED"),
    ("hostile object", HostileFailureValue()),
    ("a namespace that looks like a member", SimpleNamespace(value="RESPONSE_MALFORMED")),
)


@pytest.mark.parametrize(
    ("label", "failure"), NON_MEMBER_FAILURES, ids=[c[0] for c in NON_MEMBER_FAILURES]
)
def test_a_non_member_failure_normalises_to_unclassified(label: str, failure: Any) -> None:
    """Never to a member that would then be read as a credential claim."""
    error = SecretRetrievalError(failure)
    assert error.failure is SecretRetrievalFailure.UNCLASSIFIED, label
    assert type(error.failure) is SecretRetrievalFailure


@pytest.mark.parametrize(
    ("label", "failure"), NON_MEMBER_FAILURES, ids=[c[0] for c in NON_MEMBER_FAILURES]
)
def test_a_non_member_failure_can_never_become_a_credential_refusal(
    label: str, failure: Any
) -> None:
    """The round-1 invariant, checked through the constructor this time."""
    outcome = bp._secret_failure_outcome(SecretRetrievalError(failure))
    assert outcome is bp.PreflightOutcome.REFUSED_UNCLASSIFIED, label
    assert outcome is not bp.PreflightOutcome.REFUSED_CREDENTIAL


@pytest.mark.parametrize(
    ("label", "failure"), NON_MEMBER_FAILURES, ids=[c[0] for c in NON_MEMBER_FAILURES]
)
def test_a_non_member_failure_discloses_nothing(label: str, failure: Any) -> None:
    """The rendering is the member token, and the member is `UNCLASSIFIED`."""
    error = SecretRetrievalError(failure)
    rendered = f"{error!r} {error!s}"
    assert "UNCLASSIFIED" in rendered
    for canary in CANARIES:
        assert canary not in rendered, f"{label} disclosed {canary}"
    assert "RESPONSE_MALFORMED" not in rendered, f"{label} acquired a credential-mapped member"


def test_a_non_member_construction_surfaces_as_unclassified_with_no_invented_count(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end: the exact case that used to fabricate a credential claim.

    The boundary is replaced with one that raises a refusal built from a bare
    string. Before round 2 the constructor turned that into
    ``RESPONSE_MALFORMED``, which the entry point maps to
    ``REFUSED_CREDENTIAL`` -- so an operator was told the credential boundary
    had refused, while the witnessed invocation count was zero.
    """
    harness = Harness()

    def refuse(**_: Any) -> Any:
        raise SecretRetrievalError("RESPONSE_MALFORMED")  # type: ignore[arg-type]

    monkeypatch.setattr(
        "kalpamani.data.ingest.sharadar.secrets.sharadar_credential_from_secret", refuse
    )
    with pytest.raises(bp.BindingPreflightError) as refusal:
        harness.run()
    captured = capsys.readouterr()
    assert refusal.value.outcome is bp.PreflightOutcome.REFUSED_UNCLASSIFIED
    assert refusal.value.__cause__ is None
    assert refusal.value.__suppress_context__ is True
    assert harness.secrets.calls == 0, "the witnessed count is zero and stays zero"
    rendered = f"{refusal.value!r} {refusal.value!s} {captured.out} {captured.err}"
    for canary in CANARIES:
        assert canary not in rendered
    assert "RESPONSE_MALFORMED" not in rendered


def test_the_constructor_never_names_a_credential_mapped_member() -> None:
    """Structural, because the behavioural cases only prove today's inputs.

    The normalisation target is read out of the constructor's own body: any
    member the entry point maps to ``REFUSED_CREDENTIAL`` appearing there is the
    defect, whatever the current tests happen to exercise.
    """
    source = inspect.getsource(SecretRetrievalError.__init__)
    body = source.split('"""')[-1]
    credential_mapped = {
        token
        for token, outcome in bp.SECRET_FAILURE_OUTCOME.items()
        if outcome is bp.PreflightOutcome.REFUSED_CREDENTIAL
    }
    for token in credential_mapped:
        assert token not in body, f"the constructor can normalise to {token}"
    assert "SecretRetrievalFailure.UNCLASSIFIED" in body


def test_the_unclassified_member_is_never_raised_by_the_boundary_itself() -> None:
    """It exists for the constructor, not as a cause the boundary can diagnose."""
    source = _executable(SECRETS_MODULE)
    assert source.count("SecretRetrievalFailure.UNCLASSIFIED") == 1, (
        "UNCLASSIFIED is the constructor's normalisation target and nothing else"
    )
    assert "_refuse(SecretRetrievalFailure.UNCLASSIFIED)" not in source


# -- the ARN resource length boundary ----------------------------------------
#
# ADR-0016 round 2. The whole resource component -- secret name *plus* the
# generated `-XXXXXX` -- was measured against the 512-character *name* ceiling.
# AWS permits a 512-character name and then appends seven characters of its own,
# so a legitimate ARN for a maximum-length secret has a 519-character resource
# and was refused.

#: A generated-suffix-shaped tail. Synthetic: six ASCII alphanumerics.
SYNTHETIC_SUFFIX: Final = "AbCd12"


def _arn_with_resource(resource: str) -> str:
    """A synthetic ARN carrying an exact resource component."""
    return f"arn:aws:secretsmanager:us-east-1:{SYNTHETIC_ACCOUNT}:secret:{resource}"


#: The name-length boundary, on both sides, with the suffix attached.
ARN_LENGTH_CASES: tuple[tuple[str, str, bool], ...] = (
    ("one-character name plus suffix", f"s-{SYNTHETIC_SUFFIX}", True),
    (
        "maximum-length name plus suffix",
        f"{'s' * MAX_SECRET_NAME_LENGTH}-{SYNTHETIC_SUFFIX}",
        True,
    ),
    (
        "one over the name ceiling plus suffix",
        f"{'s' * (MAX_SECRET_NAME_LENGTH + 1)}-{SYNTHETIC_SUFFIX}",
        False,
    ),
    ("empty name before the suffix", f"-{SYNTHETIC_SUFFIX}", False),
    ("suffix alone", SYNTHETIC_SUFFIX, False),
    ("five-character suffix", "synthetic-AbCd1", False),
    ("seven-character suffix", "synthetic-AbCd123", False),
    ("non-alphanumeric suffix", "synthetic-AbCd_1", False),
    ("no suffix separator", f"synthetic{SYNTHETIC_SUFFIX}", False),
    ("underscore separator", f"synthetic_{SYNTHETIC_SUFFIX}", False),
)


@pytest.mark.parametrize(
    ("label", "resource", "usable"), ARN_LENGTH_CASES, ids=[c[0] for c in ARN_LENGTH_CASES]
)
def test_the_arn_resource_length_boundary(label: str, resource: str, usable: bool) -> None:
    """The 512 ceiling is the name's. The suffix is seven characters on top."""
    assert is_usable_secret_identifier(_arn_with_resource(resource)) is usable, label


def test_the_maximum_length_arn_is_admitted_and_the_name_ceiling_still_binds() -> None:
    """The regression, stated as the pair that used to be indistinguishable.

    Both resources are longer than 512 characters. One is a legitimate ARN for a
    maximum-length secret; the other names a secret one character too long.
    Measuring the suffixed resource against the name ceiling refused both.
    """
    at_ceiling = _arn_with_resource(f"{'s' * MAX_SECRET_NAME_LENGTH}-{SYNTHETIC_SUFFIX}")
    over_ceiling = _arn_with_resource(f"{'s' * (MAX_SECRET_NAME_LENGTH + 1)}-{SYNTHETIC_SUFFIX}")
    assert len(at_ceiling.split(":")[-1]) == MAX_SECRET_NAME_LENGTH + ARN_SUFFIX_LENGTH
    assert is_usable_secret_identifier(at_ceiling) is True
    assert is_usable_secret_identifier(over_ceiling) is False


def test_a_maximum_length_arn_reaches_the_backend_exactly_once() -> None:
    """Through the preflight, not just the predicate."""
    identifier = _arn_with_resource(f"{'s' * MAX_SECRET_NAME_LENGTH}-{SYNTHETIC_SUFFIX}")
    harness = Harness(secret_id_value=identifier)
    harness.run()
    assert harness.secrets.calls == 1
    assert harness.secrets.secret_ids == [identifier]


def test_the_secret_id_ceiling_still_binds_above_the_name_ceiling() -> None:
    """Splitting the resource did not remove the outer bound."""
    oversized = _arn_with_resource(f"{'s' * MAX_SECRET_ID_LENGTH}-{SYNTHETIC_SUFFIX}")
    assert len(oversized) > MAX_SECRET_ID_LENGTH
    assert is_usable_secret_identifier(oversized) is False


def test_the_suffix_check_claims_structure_and_not_provenance() -> None:
    """A name ending in a hyphen and six alphanumerics is lexically a suffix.

    Nothing can tell the two apart, and the module says so rather than implying
    a check it does not perform.
    """
    assert is_usable_secret_identifier(_arn_with_resource("my-secret")) is True
    source = SECRETS_MODULE.read_text(encoding="utf-8")
    assert "Syntax is not provenance" in source


# ---------------------------------------------------------------------------
# 9 -- nothing leaks
# ---------------------------------------------------------------------------


def test_no_canary_reaches_a_refusal_at_any_stage(capsys: pytest.CaptureFixture[str]) -> None:
    """Every stage's refusal, rendered every way, against every canary."""
    rendered: list[str] = []
    for harness in (
        Harness(profile="default"),
        Harness(profile_raises=True),
        Harness(identity_reason=f"account {CANARY_ACCOUNT} does not match"),
        Harness(identity_raises=True),
        Harness(bucket_raises=True),
        Harness(secrets_client=CountingSecretsClient(raises=RuntimeError(CANARY_BACKEND))),
        Harness(secrets_client=CountingSecretsClient(response={"SecretString": "a b"})),
    ):
        with pytest.raises(bp.BindingPreflightError) as raised:
            harness.run()
        rendered.append(f"{raised.value!r} {raised.value!s} {raised.value.outcome.value}")

    captured = capsys.readouterr()
    joined = " ".join(rendered)
    for canary in CANARIES:
        assert canary not in joined, f"{canary} surfaced in a refusal"
        assert canary not in captured.out and canary not in captured.err


def test_no_canary_reaches_the_successful_result_or_its_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = Harness()
    result = harness.run(subjects=(CANARY_SUBJECT,))
    rendered = f"{result!r} {result!s}"
    captured = capsys.readouterr()
    for canary in (*CANARIES, CANARY_SUBJECT):
        assert canary not in rendered
        assert canary not in captured.out and canary not in captured.err


def test_no_canary_or_credential_appears_in_tracked_files() -> None:
    """The entry point and the secrets module carry no private literal."""
    for path in (ENTRY_POINT, SECRETS_MODULE):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("test-api-key", "arn:aws:", "amazonaws.com", "s3://"):
            assert forbidden not in text, f"{path.name} names {forbidden!r}"
        assert re.search(r"\b\d{12}\b", text) is None, f"{path.name} carries a 12-digit number"


# ---------------------------------------------------------------------------
# 11 -- the licensed bucket, never CONTROL
# ---------------------------------------------------------------------------


def test_the_entry_point_names_the_licensed_bucket_output_and_no_control_one() -> None:
    source = _executable(ENTRY_POINT)
    assert bp.LICENSED_BUCKET_OUTPUT == "licensed_bucket_name"
    assert "licensed_bucket_name" in source
    for control in ("control_bucket_name", "control_bucket", "CONTROL"):
        assert control not in source, f"the entry point names {control!r}"


def test_the_resolved_bucket_is_what_the_store_is_bound_to() -> None:
    """A bucket the store refuses proves the store received *this* value."""
    from kalpamani.data.contracts.errors import ObjectStoreBackendError

    harness = Harness(bucket="A_BAD_BUCKET")
    with pytest.raises(bp.BindingPreflightError) as raised:
        harness.run()
    # The composition's store refuses the name; the entry point converts it.
    assert raised.value.outcome is bp.PreflightOutcome.REFUSED_PLAN
    assert ObjectStoreBackendError is not None


# ---------------------------------------------------------------------------
# 12-17 -- the authorized path does exactly one thing
# ---------------------------------------------------------------------------


def test_the_authorized_path_invokes_the_composition_preflight_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    real = preflight_qualification_composition

    def spy(**kwargs: Any) -> Any:
        calls["count"] += 1
        return real(**kwargs)

    import kalpamani.data.ingest.sharadar.composition as composition_module

    monkeypatch.setattr(composition_module, "preflight_qualification_composition", spy)
    Harness().run()
    assert calls["count"] == 1


def test_no_qualification_runtime_execution_occurs(monkeypatch: pytest.MonkeyPatch) -> None:
    from kalpamani.data.ingest.sharadar.runtime import QualificationRuntime

    def forbidden(*_: Any, **__: Any) -> Any:
        raise AssertionError("the binding preflight reached execute")

    monkeypatch.setattr(QualificationRuntime, "execute", forbidden)
    result = Harness().run()
    assert result.status is PreflightStatus.VALIDATED_OFFLINE


def test_provider_and_object_store_call_counts_remain_zero() -> None:
    harness = Harness()
    harness.run()
    assert harness.transport.calls == 0
    assert (harness.s3.put_calls, harness.s3.head_calls) == (0, 0)
    assert harness.secrets.calls == 1, "the secret is read exactly once"


def test_the_credential_is_never_revealed_during_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reveals = {"count": 0}
    real = SharadarCredential.reveal

    def spy(self: SharadarCredential) -> str:
        reveals["count"] += 1
        return real(self)

    monkeypatch.setattr(SharadarCredential, "reveal", spy)
    Harness().run()
    assert reveals["count"] == 0


def test_the_status_is_exactly_validated_offline() -> None:
    result = Harness().run()
    assert type(result) is QualificationPreflight
    assert result.status is PreflightStatus.VALIDATED_OFFLINE
    assert str(result.status) == "VALIDATED_OFFLINE"
    assert result.acquisition_mode is AcquisitionMode.QUALIFICATION
    assert result.profile is InformationSetProfile.PROVIDER_REALISTIC_PIT


def test_nothing_escapes_in_the_result() -> None:
    """No credential, client, bucket, runtime or closure comes back."""
    import dataclasses

    from kalpamani.data.ingest.sharadar.client import SharadarClient
    from kalpamani.data.ingest.sharadar.runtime import QualificationRuntime
    from kalpamani.data.storage.s3 import S3ResearchObjectStore

    result = Harness().run()
    forbidden_types = (
        SharadarClient,
        S3ResearchObjectStore,
        QualificationRuntime,
        SharadarCredential,
        CountingSecretsClient,
        CountingS3Client,
        CountingTransport,
    )
    reachable: list[Any] = [result]
    seen: set[int] = set()
    while reachable:
        obj = reachable.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        assert not isinstance(obj, forbidden_types), f"{type(obj).__name__} escaped"
        assert not callable(obj) or isinstance(obj, type), "a callable escaped"
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            reachable.extend(getattr(obj, f.name) for f in dataclasses.fields(obj))
    # `profile` is deliberately absent from this list: the result carries the
    # *information-set* profile, which is a PIT contract value and not an AWS
    # one. Naming it here would have been a guard against the wrong thing.
    for forbidden in ("bucket", "credential", "secret", "account", "arn", "region", "endpoint"):
        assert not hasattr(result, forbidden)


# ---------------------------------------------------------------------------
# 20 -- output vocabulary
# ---------------------------------------------------------------------------


def test_the_output_vocabulary_admits_no_permission_bearing_word() -> None:
    for member in bp.PreflightOutcome:
        upper = member.value.upper()
        for implying in ("READY", "APPROVED", "AUTHORIZED", "PROCEED", "QUALIFIED", "BOUND"):
            assert implying not in upper, f"{member.name} says {implying}"


def test_every_emitted_sentence_comes_from_the_allowlist() -> None:
    """`_emit` is the one route to stdout, and it takes a member, not a string."""
    signature = inspect.signature(bp._emit)
    assert list(signature.parameters) == ["outcome"]
    source = _executable(ENTRY_POINT)
    assert source.count("def _emit") == 1


def test_the_default_invocation_prints_only_allowlisted_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = bp.main([])
    captured = capsys.readouterr()
    assert status == 1
    assert bp.PreflightOutcome.REFUSED_NOT_AUTHORIZED.value in captured.out
    assert captured.err == ""
    for canary in CANARIES:
        assert canary not in captured.out


@pytest.mark.parametrize("option", sorted(("--run", "--live", "--execute", "--force", "--api-key")))
def test_a_refused_option_is_reported_by_name(
    option: str, capsys: pytest.CaptureFixture[str]
) -> None:
    status = bp.main([option])
    captured = capsys.readouterr()
    assert status == 2
    assert bp.PreflightOutcome.REFUSED_OPTION.value in captured.out
    assert option in captured.out


def test_an_equals_form_of_a_refused_option_is_refused_too(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert bp.main(["--api-key=synthetic-refused-value"]) == 2
    assert bp.PreflightOutcome.REFUSED_OPTION.value in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Structural: one entry point, no execution surface, no state
# ---------------------------------------------------------------------------


def test_the_entry_point_has_no_execution_or_publication_operation() -> None:
    source = _executable(ENTRY_POINT)
    for forbidden in (
        ".execute(",
        "put_object",
        "head_object",
        "put_if_absent",
        "publish_bronze_payload",
        "publish_sharadar_payload",
        "acquisition_record",
        ".fetch(",
    ):
        assert forbidden not in source, f"the entry point names {forbidden!r}"


#: Module-level dictionaries that are constants by convention rather than by
#: type. Named rather than counted, so a third one has to be argued for.
FROZEN_BY_CONVENTION: Final = frozenset({"REFUSED_OPTIONS", "SECRET_FAILURE_OUTCOME"})


def test_the_entry_point_holds_no_module_level_mutable_state() -> None:
    offenders: list[str] = []
    for node in _tree(ENTRY_POINT).body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        value = node.value
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not isinstance(target, ast.Name) or target.id == "__all__":
                continue
            if isinstance(value, ast.List | ast.Set):
                offenders.append(f"{target.id} at line {node.lineno}")
            if isinstance(value, ast.Dict) and target.id not in FROZEN_BY_CONVENTION:
                offenders.append(f"{target.id} at line {node.lineno}")
    assert offenders == [], f"module-level mutable state: {offenders}"


def test_only_the_authorized_entry_points_construct_an_sdk_client() -> None:
    """Four authorized construction sites, each named, and nothing else.

    Narrowed rather than relaxed, three times now. The earliest rule was 'this
    entry point and nowhere else', correct while it was the only operator surface;
    then two; and the empirical qualification package adds its two operator entry
    points. Every one is named here, so a **fifth** arriving anywhere under
    ``src/``, ``scripts/`` or ``tests/`` still fails.

    **All four are in ``scripts/``, and that is the property that matters.** No
    module under ``src/`` constructs a client, which is checked separately and is
    what keeps the data platform free of ambient credential discovery.
    """
    # The docs audit and this file both *name* the constructor -- one to forbid it,
    # one to assert its absence. A guard that could not tell a prohibition from a
    # construction would forbid writing the prohibition.
    scanning = {
        ENTRY_POINT,
        SCRIPTS / "sharadar_authenticated_qualification.py",
        SCRIPTS / "sharadar_empirical_qualification.py",
        SCRIPTS / "sharadar_qualification_assessment.py",
        Path(__file__).resolve(),
        SCRIPTS / "phase3_docs_audit.py",
        # Asserts the absence of a client in those entry points, so it necessarily
        # names the constructor it is asserting the absence of.
        PROJECT_ROOT / "tests" / "unit" / "test_sharadar_empirical_entry_points.py",
    }
    offenders: list[str] = []
    for root in (SRC, SCRIPTS, PROJECT_ROOT / "tests"):
        for path in _python_files(root):
            if path in scanning:
                continue
            source = path.read_text(encoding="utf-8")
            if "boto3.client(" in source or "boto3.Session(" in source:
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == [], f"an SDK client is constructed at: {offenders}"


def test_no_module_under_src_imports_the_sdk() -> None:
    offenders: list[str] = []
    for path in _python_files(SRC):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Import | ast.ImportFrom):
                continue
            names = (
                {alias.name for alias in node.names}
                if isinstance(node, ast.Import)
                else ({node.module} if node.module else set())
            )
            if {name.split(".")[0] for name in names} & {"boto3", "botocore"}:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
    assert offenders == [], f"the SDK is imported at: {offenders}"


def test_the_composition_has_only_its_named_callers_outside_the_tests() -> None:
    """Two authorized callers of the offline preflight, and no others.

    Narrowed rather than relaxed. This entry point was the only caller while it
    was the only authorized surface; the empirical acquisition composition calls
    it too, as the offline plan preflight that runs before its first request. A
    **third** caller, a script, a task or an ad-hoc invocation still fails here.
    """
    allowed = {
        ENTRY_POINT,
        SRC / "kalpamani" / "data" / "qualify" / "sharadar" / "acquisition.py",
        PROJECT_ROOT / "tests" / "unit" / "test_sharadar_composition_preflight.py",
        Path(__file__).resolve(),
    }
    offenders: list[str] = []
    for root in (SRC, SCRIPTS, PROJECT_ROOT / "tests"):
        for path in _python_files(root):
            if path in allowed:
                continue
            for node in ast.walk(_tree(path)):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "preflight_qualification_composition"
                ):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
    assert offenders == [], f"the composition is called at: {offenders}"


def test_the_entry_point_is_not_re_exported_by_the_installed_package() -> None:
    import kalpamani.data.ingest.sharadar as provider

    for name in ("run_binding_preflight", "sharadar_binding_preflight", "PreflightOutcome"):
        assert not hasattr(provider, name)
        assert name not in getattr(provider, "__all__", ())


def test_the_entry_point_creates_no_task_image_or_scheduler() -> None:
    source = ENTRY_POINT.read_text(encoding="utf-8")
    for forbidden in ("ecs", "lambda_client", "register_task_definition", "Dockerfile", "cron"):
        assert forbidden.lower() not in source.lower(), f"the entry point names {forbidden!r}"


def test_the_entry_point_does_not_touch_the_private_harness() -> None:
    source = ENTRY_POINT.read_text(encoding="utf-8")
    assert "import sharadar_private_qualification" not in source
    assert "from sharadar_private_qualification" not in source
    assert PRIVATE_HARNESS.is_file(), "the harness still exists, untouched"


def test_the_published_test_token_stays_in_its_approved_harness() -> None:
    # The docs audit names the token in order to *forbid* it everywhere else. A
    # guard that could not tell a prohibition from a use would forbid writing the
    # prohibition, which is the wrong trade.
    allowed = {PRIVATE_HARNESS, SCRIPTS / "phase3_docs_audit.py"}
    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for root in (SRC, SCRIPTS)
        for path in _python_files(root)
        if path not in allowed and "test-api-key" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"the published token appears at: {offenders}"


def test_the_pinned_profile_and_region_match_the_governed_verifier() -> None:
    """Read from the verifier that owns them, not restated independently."""
    verifier = (SCRIPTS / "aws_foundation_verify.py").read_text(encoding="utf-8")
    assert f'EXPECTED_PROFILE = "{bp.EXPECTED_PROFILE}"' in verifier
    assert f'EXPECTED_REGION = "{bp.EXPECTED_REGION}"' in verifier
    assert bp.EXPECTED_PROFILE == "kalpamani-foundation"
    assert bp.EXPECTED_REGION == "us-east-1"


def test_the_entry_point_reuses_the_governed_gate_rather_than_reimplementing_it() -> None:
    source = _executable(ENTRY_POINT)
    assert "identity_gate" in source
    assert "tf_outputs" in source
    # No second implementation of account matching or state parsing. Matched on
    # word boundaries: a bare "sts" substring also occurs inside "exists".
    for reimplementation in (
        "get-caller-identity",
        "allowed_account_ids",
        "terraform",
        "get_caller_identity",
    ):
        assert reimplementation not in source, f"the entry point reimplements {reimplementation!r}"
    assert re.search(r"\bsts\b", source) is None, "the entry point calls sts directly"
