"""The dormant composition root, and the offline preflight that is its only surface.

ADR-0014 authorized wiring five accepted slices together and stopping one step
short of using them. Two kinds of check live here:

**Behavioural.** A composition is built from synthetic fakes and preflighted. The
fakes count every call they could receive, so "no provider request, no S3 write,
no credential reveal" is a number this file reads rather than a claim it repeats.

**Structural.** AST scans proving the module has no execution method, no entry
point, no environment or file read, no SDK import, and no caller anywhere outside
this file.

Nothing here contacts Sharadar, AWS or any network. The credential is a
self-labelled synthetic string, the bucket is a synthetic name, and neither is
ever revealed, printed or sent.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from kalpamani.data.contracts.errors import ObjectStoreBackendError
from kalpamani.data.contracts.vocabulary import AcquisitionMode, InformationSetProfile
from kalpamani.data.ingest.sharadar.client import (
    DEFAULT_RETRY_POLICY,
    Pacer,
    RetryPolicy,
    SharadarClient,
)
from kalpamani.data.ingest.sharadar.composition import (
    QUALIFICATION_ACQUISITION_MODE,
    PreflightStatus,
    QualificationPreflight,
    SharadarQualificationComposition,
)
from kalpamani.data.ingest.sharadar.credentials import SharadarCredential
from kalpamani.data.ingest.sharadar.datasets import DateWindow, SharadarDataset
from kalpamani.data.ingest.sharadar.qualification import (
    PERMITTED_PROFILE,
    DatasetPlan,
    QualificationLimits,
    QualificationPlan,
    QualificationPlanError,
    QualificationSubject,
)
from kalpamani.data.ingest.sharadar.redaction import SharadarRequestError
from kalpamani.data.ingest.sharadar.runtime import (
    QualificationRuntime,
    QualificationRuntimeError,
)
from kalpamani.data.ingest.sharadar.transport import TransportResponse
from kalpamani.data.storage.s3 import S3ResearchObjectStore

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
SCRIPTS = PROJECT_ROOT / "scripts"
TESTS = PROJECT_ROOT / "tests"
COMPOSITION = SRC / "kalpamani" / "data" / "ingest" / "sharadar" / "composition.py"

#: Values that must never surface. Distinctive enough that a substring search is
#: meaningful, and shaped like the four things that would actually hurt.
CANARY_SECRET = "synthetic-canary-secret-a1b2c3d4e5f6"  # noqa: S105 -- a synthetic
#: canary, deliberately secret-shaped so a leak test has something real to find.
CANARY_BUCKET = "synthetic-canary-bucket-a1b2c3"
CANARY_BACKEND_MESSAGE = "synthetic-canary-backend-message-a1b2c3"
CANARY_SUBJECT = "ZZZZCANARY"

INSTANT = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Synthetic dependencies. Every one counts what was asked of it.
# ---------------------------------------------------------------------------


class CountingTransport:
    """A transport that refuses to transport, and says how often it was asked."""

    def __init__(self, max_response_bytes: int = 1 << 20) -> None:
        self._max = max_response_bytes
        self.calls = 0

    @property
    def max_response_bytes(self) -> int:
        return self._max

    def get(self, **_: Any) -> TransportResponse:
        self.calls += 1
        raise AssertionError("preflight must not reach a transport")


class CountingS3Client:
    """Satisfies :class:`~kalpamani.data.storage.s3.S3Client` and does nothing."""

    def __init__(self) -> None:
        self.put_calls = 0
        self.head_calls = 0

    def put_object(self, **_: Any) -> dict[str, Any]:
        self.put_calls += 1
        raise AssertionError(CANARY_BACKEND_MESSAGE)

    def head_object(self, **_: Any) -> dict[str, Any]:
        self.head_calls += 1
        raise AssertionError(CANARY_BACKEND_MESSAGE)


class CountingClock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return INSTANT


# There is no `CountingCredential` wrapper: `SharadarCredential` refuses
# subclassing at class creation, which is the guarantee it exists to make. The
# reveal count is therefore measured by patching the class itself, in
# `test_the_credential_is_never_revealed` below.


def credential() -> SharadarCredential:
    """A self-labelled synthetic credential. Never revealed, never sent."""
    return SharadarCredential(CANARY_SECRET)


def silent_pacer() -> Pacer:
    """Zero interval, injected clock and sleeper. Runs instantly, sleeps never."""
    return Pacer(min_interval=0.0, clock=lambda: 0.0, sleeper=lambda _: None)


def plan(
    *,
    subject: str = "SYNTH",
    execution_id: str = "synthetic-execution-0001",
    limits: QualificationLimits | None = None,
) -> QualificationPlan:
    return QualificationPlan(
        subjects=(QualificationSubject(subject),),
        datasets=(
            DatasetPlan(
                dataset=SharadarDataset.TICKERS,
                page_limit=100,
                max_pages=1,
            ),
            DatasetPlan(
                dataset=SharadarDataset.STOCKS,
                window=DateWindow(start=date(2024, 1, 2), end=date(2024, 3, 28)),
                page_limit=100,
                max_pages=2,
            ),
        ),
        execution_id=execution_id,
        limits=limits if limits is not None else QualificationLimits(),
    )


#: Distinct from ``None``, which is a value this helper must be able to pass
#: through: ``SharadarClient`` accepts ``None`` and builds its own pacer, and the
#: composition's refusal of that is exactly what one test checks.
_KEEP: Final = object()


def compose(
    *,
    transport: CountingTransport | None = None,
    s3_client: CountingS3Client | None = None,
    clock: CountingClock | None = None,
    licensed_bucket: str = CANARY_BUCKET,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    timeout_seconds: float = 30.0,
    pacer: Any = _KEEP,
) -> SharadarQualificationComposition:
    return SharadarQualificationComposition(
        credential=credential(),
        transport=transport if transport is not None else CountingTransport(),
        pacer=silent_pacer() if pacer is _KEEP else pacer,
        retry_policy=retry_policy,
        timeout_seconds=timeout_seconds,
        s3_client=s3_client if s3_client is not None else CountingS3Client(),
        licensed_bucket=licensed_bucket,
        clock=clock if clock is not None else CountingClock(),
    )


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _executable(path: Path) -> str:
    """The module's code with every docstring removed.

    A raw-source scan would fire on the prose explaining what the module refuses
    to do, which would either weaken the guard or forbid saying why it exists.
    """
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
# Every dependency is required, and none defaults to anything real
# ---------------------------------------------------------------------------

COMPOSITION_INPUTS = (
    "credential",
    "transport",
    "pacer",
    "retry_policy",
    "timeout_seconds",
    "s3_client",
    "licensed_bucket",
    "clock",
)


def test_every_composition_input_is_required_and_keyword_only() -> None:
    """No default means no dependency this module could supply itself."""
    parameters = inspect.signature(SharadarQualificationComposition.__init__).parameters
    named = {name: p for name, p in parameters.items() if name != "self"}
    assert tuple(named) == COMPOSITION_INPUTS
    for name, parameter in named.items():
        assert parameter.default is inspect.Parameter.empty, f"{name} has a default"
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, f"{name} is positional"


@pytest.mark.parametrize("omitted", COMPOSITION_INPUTS)
def test_omitting_any_input_is_a_type_error(omitted: str) -> None:
    supplied: dict[str, Any] = {
        "credential": credential(),
        "transport": CountingTransport(),
        "pacer": silent_pacer(),
        "retry_policy": DEFAULT_RETRY_POLICY,
        "timeout_seconds": 30.0,
        "s3_client": CountingS3Client(),
        "licensed_bucket": CANARY_BUCKET,
        "clock": CountingClock(),
    }
    del supplied[omitted]
    with pytest.raises(TypeError):
        SharadarQualificationComposition(**supplied)


def test_the_pacer_must_be_supplied_exactly() -> None:
    """``SharadarClient`` accepts ``None`` and builds one from :mod:`time`.

    That is the right default for a client and the wrong one here: a composition
    root that silently acquired an ambient clock would have exactly the
    unexamined dependency this module exists to make visible.
    """
    for rejected in (None, object(), 0.0):
        with pytest.raises(SharadarRequestError):
            compose(pacer=rejected)


# ---------------------------------------------------------------------------
# It genuinely constructs the accepted components
# ---------------------------------------------------------------------------


def test_the_three_accepted_components_are_constructed() -> None:
    composition = compose()
    assert type(object.__getattribute__(composition, "_client")) is SharadarClient
    assert type(object.__getattribute__(composition, "_store")) is S3ResearchObjectStore
    assert type(object.__getattribute__(composition, "_runtime")) is QualificationRuntime


def test_the_components_are_private_and_not_exposed_as_attributes() -> None:
    """Private in the sense that matters: ``__slots__`` names them with a leading
    underscore and no property, method or export hands one out."""
    assert SharadarQualificationComposition.__slots__ == ("_client", "_runtime", "_store")
    public = {name for name in dir(SharadarQualificationComposition) if not name.startswith("_")}
    assert public == {"preflight"}


# ---------------------------------------------------------------------------
# Preflight validates, and does nothing else
# ---------------------------------------------------------------------------


def test_a_bounded_plan_validates_offline() -> None:
    result = compose().preflight(plan())
    assert type(result) is QualificationPreflight
    assert result.status is PreflightStatus.VALIDATED_OFFLINE


def test_preflight_calls_validate_and_never_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    """The distinction the whole slice rests on, measured rather than asserted."""
    seen = {"validate": 0, "execute": 0}
    real_validate = QualificationRuntime.validate

    def spy_validate(self: QualificationRuntime, p: QualificationPlan) -> Any:
        seen["validate"] += 1
        return real_validate(self, p)

    def forbidden(*_: Any, **__: Any) -> Any:
        seen["execute"] += 1
        raise AssertionError("preflight reached execute")

    monkeypatch.setattr(QualificationRuntime, "validate", spy_validate)
    monkeypatch.setattr(QualificationRuntime, "execute", forbidden)

    compose().preflight(plan())
    assert seen == {"validate": 1, "execute": 0}


def test_the_reported_numbers_are_derived_from_the_plan_and_the_client() -> None:
    """A preflight that restated declared intentions would describe a different
    run from the one that would happen."""
    transport = CountingTransport(max_response_bytes=4096)
    limits = QualificationLimits(max_response_bytes=8192, max_run_bytes=1 << 20, retry_budget=16)
    subject_plan = plan(limits=limits)
    result = compose(transport=transport).preflight(subject_plan)

    assert result.request_count == len(subject_plan.requests()) == subject_plan.request_count
    assert result.request_count == 3  # one tickers page + two stocks pages
    assert result.max_attempts == DEFAULT_RETRY_POLICY.max_attempts
    # The stricter of the client's ceiling and the plan's, which is the client's.
    assert result.max_response_bytes == 4096
    assert result.max_run_bytes == limits.max_run_bytes
    assert result.retry_budget == limits.retry_budget


def test_a_different_retry_policy_changes_the_reported_attempt_ceiling() -> None:
    policy = RetryPolicy(max_attempts=2, backoff_seconds=(1.0,))
    result = compose(retry_policy=policy).preflight(plan())
    assert result.max_attempts == 2


def test_the_acquisition_mode_is_fixed_at_qualification() -> None:
    assert QUALIFICATION_ACQUISITION_MODE is AcquisitionMode.QUALIFICATION
    assert compose().preflight(plan()).acquisition_mode is AcquisitionMode.QUALIFICATION


def test_no_caller_can_supply_or_override_the_acquisition_mode() -> None:
    """Not through the composition, not through preflight, not through the plan."""
    for callable_ in (
        SharadarQualificationComposition.__init__,
        SharadarQualificationComposition.preflight,
    ):
        parameters = set(inspect.signature(callable_).parameters)
        assert "acquisition_mode" not in parameters
        assert "mode" not in parameters
    assert "acquisition_mode" not in {f.name for f in dataclasses.fields(QualificationPlan)}
    assert "acquisition_mode" not in {f.name for f in dataclasses.fields(QualificationLimits)}


def test_the_profile_is_exactly_provider_realistic_pit() -> None:
    result = compose().preflight(plan())
    assert result.profile is PERMITTED_PROFILE
    assert result.profile is InformationSetProfile.PROVIDER_REALISTIC_PIT
    assert "PUBLIC_PIT" not in _executable(COMPOSITION)


# ---------------------------------------------------------------------------
# The result is closed, immutable and safe
# ---------------------------------------------------------------------------


def test_the_result_is_frozen_slotted_and_refuses_subclassing() -> None:
    result = compose().preflight(plan())
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.request_count = 99  # type: ignore[misc]
    # `slots=True`, so there is no instance `__dict__` for a new attribute to
    # land in. The frozen `__setattr__` raises first, and which exception type it
    # chooses is an implementation detail of the dataclass machinery -- the
    # property being checked is that the assignment cannot succeed.
    assert not hasattr(result, "__dict__")
    with pytest.raises((AttributeError, TypeError)):
        result.extra = "x"  # type: ignore[attr-defined]
    with pytest.raises(TypeError):

        class Widened(QualificationPreflight):
            pass


def test_the_result_carries_only_safe_fields() -> None:
    names = {field.name for field in dataclasses.fields(QualificationPreflight)}
    assert names == {
        "status",
        "request_count",
        "max_attempts",
        "max_response_bytes",
        "max_run_bytes",
        "retry_budget",
        "acquisition_mode",
        "profile",
    }
    for forbidden in (
        "credential",
        "secret",
        "key",
        "bucket",
        "url",
        "endpoint",
        "region",
        "profile_name",
        "account",
        "subject",
        "ticker",
        "payload",
        "message",
        "error",
        "notes",
    ):
        assert forbidden not in names


def test_the_status_vocabulary_implies_no_permission() -> None:
    """Wording is a control here. A caller must not be able to read arithmetic as
    an answer to a question this module cannot ask."""
    assert [member.value for member in PreflightStatus] == ["VALIDATED_OFFLINE"]
    source = _executable(COMPOSITION)
    for implying in ("PROCEED", "APPROVED", "QUALIFIED", "AUTHORIZED", "READY"):
        assert implying not in source, f"the module spells {implying}"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "VALIDATED_OFFLINE"),
        ("acquisition_mode", "QUALIFICATION"),
        ("profile", "PROVIDER_REALISTIC_PIT"),
        ("request_count", True),
        ("max_attempts", -1),
        ("max_run_bytes", 1.0),
    ],
)
def test_the_result_refuses_a_near_miss(field: str, value: Any) -> None:
    """``True`` is an ``int``, and a bare token is not the member it spells."""
    fields: dict[str, Any] = {
        "status": PreflightStatus.VALIDATED_OFFLINE,
        "request_count": 1,
        "max_attempts": 3,
        "max_response_bytes": 1024,
        "max_run_bytes": 4096,
        "retry_budget": 8,
        "acquisition_mode": AcquisitionMode.QUALIFICATION,
        "profile": PERMITTED_PROFILE,
    }
    fields[field] = value
    with pytest.raises(SharadarRequestError):
        QualificationPreflight(**fields)


def test_a_non_qualification_mode_cannot_be_recorded() -> None:
    for mode in (AcquisitionMode.BACKFILL, AcquisitionMode.UPDATE):
        with pytest.raises(SharadarRequestError):
            QualificationPreflight(
                status=PreflightStatus.VALIDATED_OFFLINE,
                request_count=1,
                max_attempts=3,
                max_response_bytes=1024,
                max_run_bytes=4096,
                retry_budget=8,
                acquisition_mode=mode,
                profile=PERMITTED_PROFILE,
            )


# ---------------------------------------------------------------------------
# Failure is closed, and happens before anything could have been touched
# ---------------------------------------------------------------------------


def test_a_bad_bucket_is_refused_without_echoing_it() -> None:
    with pytest.raises(ObjectStoreBackendError) as raised:
        compose(licensed_bucket=CANARY_BUCKET + "/../escape")
    assert CANARY_BUCKET not in str(raised.value)


def test_a_bad_timeout_is_refused() -> None:
    for rejected in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(SharadarRequestError):
            compose(timeout_seconds=rejected)


def test_a_clock_that_cannot_answer_is_refused_at_construction() -> None:
    with pytest.raises(QualificationRuntimeError):
        compose(clock=object())  # type: ignore[arg-type]


def test_a_plan_the_client_could_overshoot_is_refused_before_any_call() -> None:
    """A per-response ceiling has to bind before the response exists."""
    transport = CountingTransport(max_response_bytes=1 << 24)
    s3 = CountingS3Client()
    limits = QualificationLimits(max_response_bytes=32)
    with pytest.raises(QualificationRuntimeError):
        compose(transport=transport, s3_client=s3).preflight(plan(limits=limits))
    assert (transport.calls, s3.put_calls, s3.head_calls) == (0, 0, 0)


def test_a_retry_budget_the_client_would_exceed_is_refused() -> None:
    transport = CountingTransport()
    s3 = CountingS3Client()
    with pytest.raises(QualificationPlanError):
        compose(transport=transport, s3_client=s3).preflight(
            plan(limits=QualificationLimits(retry_budget=1))
        )
    assert (transport.calls, s3.put_calls, s3.head_calls) == (0, 0, 0)


def test_a_plan_that_is_not_a_plan_is_refused() -> None:
    with pytest.raises(QualificationRuntimeError):
        compose().preflight(object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Zero activity, counted
# ---------------------------------------------------------------------------


def test_a_successful_preflight_touches_no_transport_and_no_s3() -> None:
    transport = CountingTransport()
    s3 = CountingS3Client()
    clock = CountingClock()
    compose(transport=transport, s3_client=s3, clock=clock).preflight(plan())

    assert transport.calls == 0, "a provider request was made"
    assert s3.put_calls == 0, "put_object was called"
    assert s3.head_calls == 0, "head_object was called"
    # One clock read, and only because `validate()` probes it: a clock that
    # cannot answer is a dependency defect, and discovering it after the first
    # fetch would spend a provider request to learn something checkable for free.
    assert clock.calls == 1


def test_no_object_store_publication_occurs() -> None:
    """The store is real; only its injected client is a fake, so a publication
    would have to go through ``put_object`` -- which is counted above and here."""
    s3 = CountingS3Client()
    composition = compose(s3_client=s3)
    store = object.__getattribute__(composition, "_store")
    assert type(store) is S3ResearchObjectStore
    composition.preflight(plan())
    assert (s3.put_calls, s3.head_calls) == (0, 0)


def test_the_credential_is_never_revealed(monkeypatch: pytest.MonkeyPatch) -> None:
    reveals = {"count": 0}
    real = SharadarCredential.reveal

    def spy(self: SharadarCredential) -> str:
        reveals["count"] += 1
        return real(self)

    monkeypatch.setattr(SharadarCredential, "reveal", spy)
    compose().preflight(plan())
    assert reveals["count"] == 0


def test_the_module_never_calls_reveal_or_reads_a_credential_source() -> None:
    source = _executable(COMPOSITION)
    for forbidden in ("reveal(", "credential_from_env", "os.environ", "getenv", "environ"):
        assert forbidden not in source, f"the composition names {forbidden!r}"


# ---------------------------------------------------------------------------
# Nothing leaks
# ---------------------------------------------------------------------------

CANARIES = (CANARY_SECRET, CANARY_BUCKET, CANARY_BACKEND_MESSAGE, CANARY_SUBJECT)


def test_no_canary_reaches_the_result_its_repr_or_captured_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    composition = compose()
    result = composition.preflight(plan(subject=CANARY_SUBJECT))
    rendered = f"{result!r} {result!s} {composition!r} {composition!s}"
    rendered += " ".join(str(getattr(result, f.name)) for f in dataclasses.fields(result))
    captured = capsys.readouterr()
    for canary in CANARIES:
        assert canary not in rendered, f"{canary} surfaced"
        assert canary not in captured.out and canary not in captured.err


def test_no_canary_reaches_a_failure() -> None:
    """Each of the three constructors refuses without echoing what it refused.

    Each refusal is caught as its own closed type. A single broad
    ``pytest.raises(Exception)`` would record any failure as the expected one --
    a mistyped helper included -- and then assert a canary is absent from a
    message the test never meant to produce.
    """
    failures: list[str] = []

    with pytest.raises(ObjectStoreBackendError) as bucket_refusal:
        compose(licensed_bucket=CANARY_BUCKET + "!!")
    failures.append(f"{bucket_refusal.value!r} {bucket_refusal.value!s}")

    with pytest.raises(SharadarRequestError) as timeout_refusal:
        compose(timeout_seconds=-1.0)
    failures.append(f"{timeout_refusal.value!r} {timeout_refusal.value!s}")

    with pytest.raises(QualificationRuntimeError) as clock_refusal:
        compose(clock=object())  # type: ignore[arg-type]
    failures.append(f"{clock_refusal.value!r} {clock_refusal.value!s}")

    joined = " ".join(failures)
    for canary in CANARIES:
        assert canary not in joined


def test_the_composition_repr_is_a_constant() -> None:
    assert repr(compose()) == repr(
        compose(licensed_bucket="a-second-synthetic-bucket", timeout_seconds=11.0)
    )


# ---------------------------------------------------------------------------
# Structural: no execution surface, no runner, no caller
# ---------------------------------------------------------------------------

EXECUTION_LIKE = re.compile(
    r"^_*(execute|run|fetch|publish|upload|send|post|put|get|start|invoke|main|ingest|acquire)"
)


#: Dunders are the object protocol, not a surface a caller reaches for to make
#: something happen. Excluded by shape rather than by name, so a future dunder
#: does not have to be added to a list.
def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def test_the_composition_has_no_execution_like_method() -> None:
    """Private spellings included: a leading underscore hides a method from a
    reviewer skimming, not from a caller who knows the name."""
    offenders = [
        name
        for name, member in inspect.getmembers(SharadarQualificationComposition)
        if callable(member) and not _is_dunder(name) and EXECUTION_LIKE.match(name)
    ]
    assert offenders == [], f"an execution-like method exists: {offenders}"


def test_the_module_defines_exactly_one_public_operation() -> None:
    tree = _tree(COMPOSITION)
    composition_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SharadarQualificationComposition"
    )
    methods = [
        node.name
        for node in composition_class.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    assert methods == ["__init__", "__repr__", "preflight"]


def test_the_module_never_names_execute() -> None:
    assert "execute" not in _executable(COMPOSITION)


def test_the_module_has_no_entry_point_cli_or_subprocess() -> None:
    source = _executable(COMPOSITION)
    for forbidden in (
        '__name__ == "__main__"',
        "argparse",
        "sys.argv",
        "subprocess",
        "Popen",
        "open(",
        "read_text",
        "read_bytes",
        "Path(",
    ):
        assert forbidden not in source, f"the composition names {forbidden!r}"


def test_the_module_imports_no_sdk_or_network_client() -> None:
    imported: set[str] = set()
    for node in ast.walk(_tree(COMPOSITION)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module)
    roots = {name.split(".")[0] for name in imported}
    assert not roots & {
        "boto3",
        "botocore",
        "urllib",
        "urllib3",
        "requests",
        "httpx",
        "socket",
        "ssl",
        "http",
        "os",
        "sys",
        "subprocess",
        "argparse",
        "pathlib",
    }


def test_no_source_module_imports_the_aws_sdk() -> None:
    """Repository-wide, and unchanged by this slice: the SDK is a declared
    dependency because a *future* authorized runner must construct a signed
    client. No module under ``src/`` imports it, this one included."""
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


def test_no_default_network_opener_is_constructed_anywhere_under_src() -> None:
    """``UrllibTransport()`` with no injected opener is the one construction that
    would turn an injected transport into a real one."""
    offenders: list[str] = []
    for path in _python_files(SRC):
        for node in ast.walk(_tree(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"UrllibTransport", "build_opener", "urlopen"}
            ):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
    assert offenders == [], f"a real opener is constructed at: {offenders}"


def test_nothing_constructs_the_composition_outside_this_file() -> None:
    """The whole slice in one assertion: the wiring exists and nobody uses it."""
    offenders: list[str] = []
    for root in (SRC, SCRIPTS, TESTS):
        for path in _python_files(root):
            if path == Path(__file__).resolve():
                continue
            for node in ast.walk(_tree(path)):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "SharadarQualificationComposition"
                ):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
    assert offenders == [], f"the composition is constructed at: {offenders}"


def test_no_module_imports_the_composition_outside_this_file() -> None:
    offenders: list[str] = []
    for root in (SRC, SCRIPTS, TESTS):
        for path in _python_files(root):
            if path in {Path(__file__).resolve(), COMPOSITION}:
                continue
            if "sharadar.composition" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == [], f"the composition is imported at: {offenders}"


def test_the_package_does_not_re_export_the_composition() -> None:
    """Not exported, so ``from ...sharadar import SharadarQualificationComposition``
    does not work. Reaching it takes naming the module, which is a decision."""
    import kalpamani.data.ingest.sharadar as provider

    assert "SharadarQualificationComposition" not in getattr(provider, "__all__", ())
    assert not hasattr(provider, "SharadarQualificationComposition")


def test_the_composition_does_not_touch_the_private_harness() -> None:
    assert "sharadar_private_qualification" not in COMPOSITION.read_text(encoding="utf-8")


def test_the_published_test_token_is_absent() -> None:
    assert "test-api-key" not in COMPOSITION.read_text(encoding="utf-8")


def test_importing_the_module_runs_nothing() -> None:
    """Import time must contain no statement that does work."""
    allowed = (
        ast.Import,
        ast.ImportFrom,
        ast.ClassDef,
        ast.FunctionDef,
        ast.Assign,
        ast.AnnAssign,
        ast.Expr,
    )
    for node in _tree(COMPOSITION).body:
        assert isinstance(node, allowed), f"import-time statement: {type(node).__name__}"
        if isinstance(node, ast.Expr):
            assert isinstance(node.value, ast.Constant), "import-time expression"
        if isinstance(node, ast.Assign | ast.AnnAssign):
            value = node.value
            assert value is None or isinstance(value, ast.Constant | ast.Attribute | ast.List), (
                f"import-time call at line {node.lineno}"
            )


# ---------------------------------------------------------------------------
# The bounds this slice must not have moved
# ---------------------------------------------------------------------------


def test_the_plan_carries_no_credential_bucket_or_permission_field() -> None:
    names = {f.name for f in dataclasses.fields(QualificationPlan)}
    names |= {f.name for f in dataclasses.fields(QualificationLimits)}
    for forbidden in (
        "credential",
        "secret",
        "api_key",
        "token",
        "bucket",
        "licensed_bucket",
        "endpoint",
        "region",
        "acquisition_mode",
        "authorized",
        "execute",
        "live",
    ):
        assert forbidden not in names


def test_the_retired_representation_is_absent_from_the_composition() -> None:
    source = _executable(COMPOSITION)
    for retired in ("is_backfill", "QUALIFICATION_IS_BACKFILL"):
        assert retired not in source
