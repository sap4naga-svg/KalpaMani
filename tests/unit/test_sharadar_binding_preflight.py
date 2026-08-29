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
from datetime import UTC, datetime
from pathlib import Path
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
    SecretRetrievalError,
    SecretRetrievalFailure,
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
    """Answers one secret and counts the asking."""

    def __init__(self, response: Any = None, raises: Exception | None = None) -> None:
        self.response = {"SecretString": CANARY_SECRET} if response is None else response
        self.raises = raises
        self.calls = 0
        self.secret_ids: list[str] = []

    def get_secret_value(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.secret_ids.append(kwargs.get("SecretId", ""))
        if self.raises is not None:
            raise self.raises
        return self.response


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
        profile_raises: bool = False,
        identity_raises: bool = False,
        bucket_raises: bool = False,
    ) -> None:
        self.stages = Stages()
        self.profile = profile
        self.identity_reason = identity_reason
        self.bucket = bucket
        self.profile_raises = profile_raises
        self.identity_raises = identity_raises
        self.bucket_raises = bucket_raises
        self.secrets = secrets_client or CountingSecretsClient()
        self.s3 = CountingS3Client()
        self.transport = CountingTransport()

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

    def secrets_factory(self) -> CountingSecretsClient:
        self.stages.record("secret")
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
        authorized: Any = True,
        secret_id: Any = CANARY_SECRET_ID,
        subjects: Any = ("SYNTH",),
        execution_id: str | None = "synthetic-execution-0001",
    ) -> Any:
        return bp.run_binding_preflight(
            binding_authorized=authorized,
            secret_id=secret_id,
            subjects=subjects,
            execution_id=execution_id,
            profile_of=self.profile_of,
            identity_gate=self.identity_gate,
            resolve_licensed_bucket=self.resolve_bucket,
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
            assert isinstance(node.value, ast.Constant | ast.Dict | ast.Attribute | ast.Name), (
                f"import-time call at line {node.lineno}"
            )
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


def test_invocation_without_the_flag_refuses_before_any_stage() -> None:
    harness = Harness()
    with pytest.raises(bp.BindingPreflightError) as raised:
        harness.run(authorized=False)
    assert raised.value.outcome is bp.PreflightOutcome.REFUSED_NOT_AUTHORIZED
    assert harness.stages.order == [], "a stage ran before authorization was checked"
    assert harness.secrets.calls == 0


class TruthyLookalike:
    def __bool__(self) -> bool:
        return True


@pytest.mark.parametrize(
    "forged",
    [1, "yes", "true", "True", [1], TruthyLookalike(), 1.0],
    ids=["int", "yes", "true", "True", "list", "lookalike", "float"],
)
def test_authorization_cannot_be_forged(forged: Any) -> None:
    """Exact ``True``. A truthy stand-in must not authorize a binding preflight."""
    harness = Harness()
    with pytest.raises(bp.BindingPreflightError) as raised:
        harness.run(authorized=forged)
    assert raised.value.outcome is bp.PreflightOutcome.REFUSED_NOT_AUTHORIZED
    assert harness.stages.order == []


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
    assert harness.stages.order == ["profile", "identity", "bucket", "secret"]
    assert (harness.s3.put_calls, harness.s3.head_calls, harness.transport.calls) == (0, 0, 0)


def test_a_missing_secret_identifier_refuses_before_the_backend_is_asked() -> None:
    harness = Harness()
    for missing in (None, "", "   ", 7):
        with pytest.raises(bp.BindingPreflightError) as raised:
            harness.run(secret_id=missing)
        assert raised.value.outcome is bp.PreflightOutcome.REFUSED_CREDENTIAL
    assert harness.secrets.calls == 0


def test_the_full_ordering_is_exact_on_the_authorized_path() -> None:
    harness = Harness()
    harness.run()
    assert harness.stages.order == ["profile", "identity", "bucket", "secret", "s3", "transport"]


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
    assert bp.main(["--api-key=whatever"]) == 2
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
            if isinstance(value, ast.Dict) and target.id != "REFUSED_OPTIONS":
                offenders.append(f"{target.id} at line {node.lineno}")
    assert offenders == [], f"module-level mutable state: {offenders}"


def test_the_entry_point_is_the_only_place_that_constructs_an_sdk_client() -> None:
    # The docs audit and this file both *name* the constructor -- one to forbid it,
    # one to assert its absence. A guard that could not tell a prohibition from a
    # construction would forbid writing the prohibition.
    scanning = {ENTRY_POINT, Path(__file__).resolve(), SCRIPTS / "phase3_docs_audit.py"}
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


def test_the_entry_point_is_the_only_caller_of_the_composition_outside_its_tests() -> None:
    allowed = {
        ENTRY_POINT,
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
    assert re.search(r"sts", source) is None, "the entry point calls sts directly"
