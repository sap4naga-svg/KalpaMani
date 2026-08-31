"""The dormant composition, and the offline preflight that is its only surface.

ADR-0014 authorized wiring five accepted slices together and stopping one step
short of using them. Two kinds of check live here:

**Behavioural.** A composition is preflighted from synthetic fakes. The fakes
count every call they could receive, so "no provider request, no S3 write, no
credential reveal" is a number this file reads rather than a claim it repeats.

**Structural.** AST scans proving the module holds no state, returns no
executable component, has no entry point, reads no environment or file, imports
no SDK, and has no caller anywhere outside this file.

Correction round 1 changed the shape these tests are written against. The first
revision was a class holding ``_client``, ``_store`` and ``_runtime``, and
several tests here reached those attributes to prove the components had been
built -- which was also the proof that ``composition._runtime.execute(plan)``
worked. **Reaching a private attribute is not evidence of safety; it is the
demonstration of the defect.** Those tests are gone, replaced by ones proving no
executable component escapes at all.

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
    MAX_ATTEMPTS_CEILING,
    Pacer,
    RetryPolicy,
    SharadarClient,
)
from kalpamani.data.ingest.sharadar.composition import (
    PreflightStatus,
    QualificationPreflight,
    preflight_qualification_composition,
)
from kalpamani.data.ingest.sharadar.credentials import SharadarCredential
from kalpamani.data.ingest.sharadar.datasets import DateWindow, SharadarDataset
from kalpamani.data.ingest.sharadar.qualification import (
    MAX_REQUESTS,
    MAX_RESPONSE_BYTES,
    MAX_RETRY_BUDGET,
    MAX_RUN_BYTES,
    PERMITTED_PROFILE,
    QUALIFICATION_ACQUISITION_MODE,
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
from kalpamani.data.ingest.sharadar.transport import (
    MAX_RESPONSE_BYTES_CEILING,
    TransportResponse,
)
from kalpamani.data.storage.s3 import S3ResearchObjectStore

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
SCRIPTS = PROJECT_ROOT / "scripts"
TESTS = PROJECT_ROOT / "tests"
COMPOSITION = SRC / "kalpamani" / "data" / "ingest" / "sharadar" / "composition.py"
CLIENT = SRC / "kalpamani" / "data" / "ingest" / "sharadar" / "client.py"

#: The one operator entry point ADR-0015 authorized to call this composition.
#:
#: Named individually, so a second caller has to pass review rather than merely
#: be in ``scripts/``. It refuses by default and has no qualification-run
#: execution surface; what it may do is bind the private dependencies and call
#: the offline preflight below.
BINDING_PREFLIGHT = SCRIPTS / "sharadar_binding_preflight.py"
BINDING_PREFLIGHT_TEST = TESTS / "unit" / "test_sharadar_binding_preflight.py"

#: Values that must never surface. Distinctive enough that a substring search is
#: meaningful, and shaped like the things that would actually hurt.
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
    """A transport that refuses to transport, and says how often it was asked.

    ``max_response_bytes`` is a property that counts its own reads, because the
    client must resolve it **once** at construction rather than consult a mutable
    dependency on every access.
    """

    def __init__(self, max_response_bytes: int = 1 << 20) -> None:
        self.declared = max_response_bytes
        self.calls = 0
        self.ceiling_reads = 0

    @property
    def max_response_bytes(self) -> int:
        self.ceiling_reads += 1
        return self.declared

    def get(self, **_: Any) -> TransportResponse:
        self.calls += 1
        raise AssertionError("preflight must not reach a transport")


class TransportWithoutGet:
    """Declares a plausible ceiling and cannot perform a request.

    The shape the first revision accepted: a `Protocol` annotation is a static
    claim, and nothing checked it, so this composed and validated cleanly while
    being unable to fetch anything.
    """

    max_response_bytes = 1 << 20


class TransportWithNonCallableGet:
    max_response_bytes = 1 << 20
    get = "not callable"


class TransportWithHostileLookup:
    """Raises from inside attribute access, carrying its own text."""

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(CANARY_BACKEND_MESSAGE)


class TransportWithHostileCeiling:
    """Answers ``get`` and raises only when asked how much it may return."""

    def get(self, **_: Any) -> TransportResponse:  # pragma: no cover - never called
        raise AssertionError("preflight must not reach a transport")

    @property
    def max_response_bytes(self) -> int:
        raise RuntimeError(CANARY_BACKEND_MESSAGE)


class TransportWithNoCeiling:
    """A legitimate stand-in that simply does not narrow the ceiling."""

    def get(self, **_: Any) -> TransportResponse:  # pragma: no cover - never called
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


#: Distinct from ``None``, which is a value these helpers must be able to pass
#: through: ``SharadarClient`` accepts ``None`` and builds its own pacer, and the
#: composition's refusal of that is exactly what one test checks.
_KEEP: Final = object()


def preflight(
    *,
    transport: Any = _KEEP,
    s3_client: Any = _KEEP,
    clock: Any = _KEEP,
    licensed_bucket: str = CANARY_BUCKET,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    timeout_seconds: float = 30.0,
    pacer: Any = _KEEP,
    subject_plan: Any = _KEEP,
) -> QualificationPreflight:
    return preflight_qualification_composition(
        credential=credential(),
        transport=CountingTransport() if transport is _KEEP else transport,
        pacer=silent_pacer() if pacer is _KEEP else pacer,
        retry_policy=retry_policy,
        timeout_seconds=timeout_seconds,
        s3_client=CountingS3Client() if s3_client is _KEEP else s3_client,
        licensed_bucket=licensed_bucket,
        clock=CountingClock() if clock is _KEEP else clock,
        plan=plan() if subject_plan is _KEEP else subject_plan,
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
    "plan",
)


def test_every_composition_input_is_required_and_keyword_only() -> None:
    """No default means no dependency this function could supply itself."""
    named = dict(inspect.signature(preflight_qualification_composition).parameters)
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
        "plan": plan(),
    }
    del supplied[omitted]
    with pytest.raises(TypeError):
        preflight_qualification_composition(**supplied)


def test_the_pacer_must_be_supplied_exactly() -> None:
    """``SharadarClient`` accepts ``None`` and builds one from :mod:`time`.

    That is the right default for a client and the wrong one here: a composition
    root that silently acquired an ambient clock would have exactly the
    unexamined dependency this module exists to make visible.
    """
    for rejected in (None, object(), 0.0):
        with pytest.raises(SharadarRequestError):
            preflight(pacer=rejected)


# ---------------------------------------------------------------------------
# It genuinely constructs the accepted components
# ---------------------------------------------------------------------------


def test_the_three_accepted_components_are_constructed() -> None:
    """Constructed, and proven so without reaching for a private attribute.

    Each component is observed by something only *it* could have done: the client
    resolves the transport's ceiling at construction, the store validates the
    bucket name, and the runtime probes the clock during ``validate``. An earlier
    revision asserted this with ``object.__getattribute__``, which proved the
    components existed *and* that a caller could reach them -- the defect, not
    the property.
    """
    transport = CountingTransport()
    clock = CountingClock()
    preflight(transport=transport, clock=clock)

    assert transport.ceiling_reads == 1, "no SharadarClient resolved the transport ceiling"
    assert clock.calls == 1, "no QualificationRuntime probed the clock"
    with pytest.raises(ObjectStoreBackendError):
        # Only S3ResearchObjectStore refuses a bucket name, and it does so at
        # construction -- so a refusal here is the store having been built.
        preflight(licensed_bucket="A_BAD_BUCKET")


#: Types that must never come back from the composition, directly or nested.
EXECUTABLE_TYPES = (SharadarClient, S3ResearchObjectStore, QualificationRuntime)


def test_no_executable_component_escapes_the_preflight() -> None:
    """The correction round 1 exists for.

    The first revision returned a *stateful object* holding ``_client``,
    ``_store`` and ``_runtime``, so ``composition._runtime.execute(plan)`` ran.
    A function has no ``self`` to attach them to: they are locals, and they are
    neither returned nor stored on the result.

    **What this asserts is retention, not lifetime.** It walks everything
    reachable *from the returned result* and asserts none of the three
    components -- and no credential -- is in it. It says nothing about whether
    those objects still exist: the caller's transport, S3 client, clock and
    credential are the caller's, before and after.
    """
    result = preflight()
    assert type(result) is QualificationPreflight

    reachable: list[object] = [result]
    seen: set[int] = set()
    while reachable:
        obj = reachable.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        assert not isinstance(obj, EXECUTABLE_TYPES), f"{type(obj).__name__} escaped"
        assert not isinstance(obj, SharadarCredential), "the credential escaped"
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            reachable.extend(getattr(obj, f.name) for f in dataclasses.fields(obj))
        for attribute in getattr(type(obj), "__slots__", ()):
            reachable.append(getattr(obj, attribute, None))
        reachable.extend(vars(obj).values() if hasattr(obj, "__dict__") else ())


def test_the_result_holds_no_dependency_shaped_attribute() -> None:
    """Not by name, and not by type. ``__slots__`` is the whole storage."""
    result = preflight()
    assert not hasattr(result, "__dict__")
    assert set(QualificationPreflight.__slots__) == {
        field.name for field in dataclasses.fields(QualificationPreflight)
    }
    for forbidden in ("_client", "_store", "_runtime", "client", "store", "runtime"):
        assert not hasattr(result, forbidden)


def test_the_module_holds_no_stateful_composition_object() -> None:
    """No class to instantiate, so no instance for a caller to hold."""
    import kalpamani.data.ingest.sharadar.composition as module

    assert not hasattr(module, "SharadarQualificationComposition")
    classes = [node.name for node in _tree(COMPOSITION).body if isinstance(node, ast.ClassDef)]
    assert classes == ["PreflightStatus", "QualificationPreflight"]


def test_no_assignment_stores_a_constructed_component_anywhere_durable() -> None:
    """A local is fine. ``self.x``, a class attribute and a module global are not.

    **Two steps count as one.** A first draft of this test looked only at the
    assignment whose *value* was the construction, so ``runtime = Runtime(...)``
    followed by ``SomeClass.escaped = runtime`` slipped through -- the escape the
    whole round exists to prevent, reachable in two lines. A negative control
    found it. The names bound to constructions are tracked, and any later
    non-local assignment *of one of those names* is an offender too.
    """
    built = {"SharadarClient", "S3ResearchObjectStore", "QualificationRuntime"}
    tree = _tree(COMPOSITION)
    module_level = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert not module_level - {"__all__"}, f"module-level state: {module_level}"

    component_locals: set[str] = set()
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        constructed = (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in built
        )
        carries_component = isinstance(value, ast.Name) and value.id in component_locals
        for target in node.targets:
            if isinstance(target, ast.Name):
                if constructed:
                    component_locals.add(target.id)
                elif carries_component:
                    # An alias for a component is still a component.
                    component_locals.add(target.id)
                continue
            if constructed or carries_component:
                offenders.append(f"line {node.lineno}: {ast.unparse(target)}")
    assert offenders == [], f"a constructed component is stored durably at: {offenders}"
    assert component_locals == {"client", "store", "runtime"}, (
        f"unexpected component bindings: {component_locals}"
    )


def test_the_module_returns_no_component_closure_or_bound_method() -> None:
    """Every ``return`` yields a closed result, a refusal, or the runtime's own
    result object -- never a component, a closure or a bound method.

    ADR-0017 added ``runtime.execute(plan)`` as a returned call. It is admitted
    by name rather than by loosening the rule: an arbitrary call would let a
    future edit return the runtime itself, which is the escape this guards.
    """
    permitted = {"QualificationPreflight", "SharadarRequestError"}
    permitted_methods = {"execute"}
    offenders: list[str] = []
    for node in ast.walk(_tree(COMPOSITION)):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            if value.func.id not in permitted:
                offenders.append(f"line {node.lineno}: {value.func.id}")
        elif isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
            if value.func.attr not in permitted_methods:
                offenders.append(f"line {node.lineno}: {value.func.attr}")
        elif not isinstance(value, ast.Name | ast.Constant | ast.Attribute):
            offenders.append(f"line {node.lineno}: {ast.unparse(value)}")
        if isinstance(value, ast.Lambda):
            offenders.append(f"line {node.lineno}: a closure")
    assert offenders == [], f"a non-result value is returned at: {offenders}"


# ---------------------------------------------------------------------------
# Preflight validates, and does nothing else
# ---------------------------------------------------------------------------


def test_a_bounded_plan_validates_offline() -> None:
    result = preflight()
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

    preflight()
    assert seen == {"validate": 1, "execute": 0}


def test_the_reported_numbers_are_derived_from_the_plan_and_the_client() -> None:
    """A preflight that restated declared intentions would describe a different
    run from the one that would happen."""
    transport = CountingTransport(max_response_bytes=4096)
    limits = QualificationLimits(max_response_bytes=8192, max_run_bytes=1 << 20, retry_budget=16)
    subject_plan = plan(limits=limits)
    result = preflight(transport=transport, subject_plan=subject_plan)

    assert result.request_count == len(subject_plan.requests()) == subject_plan.request_count
    assert result.request_count == 3  # one tickers page + two stocks pages
    assert result.max_attempts == DEFAULT_RETRY_POLICY.max_attempts
    # The stricter of the client's ceiling and the plan's, which is the client's.
    assert result.max_response_bytes == 4096
    assert result.max_run_bytes == limits.max_run_bytes
    assert result.retry_budget == limits.retry_budget


def test_a_different_retry_policy_changes_the_reported_attempt_ceiling() -> None:
    policy = RetryPolicy(max_attempts=2, backoff_seconds=(1.0,))
    result = preflight(retry_policy=policy)
    assert result.max_attempts == 2


def test_the_acquisition_mode_is_fixed_at_qualification() -> None:
    assert QUALIFICATION_ACQUISITION_MODE is AcquisitionMode.QUALIFICATION
    assert preflight().acquisition_mode is AcquisitionMode.QUALIFICATION


def test_no_caller_can_supply_or_override_the_acquisition_mode() -> None:
    """Not through the composition, not through preflight, not through the plan."""
    parameters = set(inspect.signature(preflight_qualification_composition).parameters)
    assert "acquisition_mode" not in parameters
    assert "mode" not in parameters
    assert "acquisition_mode" not in {f.name for f in dataclasses.fields(QualificationPlan)}
    assert "acquisition_mode" not in {f.name for f in dataclasses.fields(QualificationLimits)}


def test_the_profile_is_exactly_provider_realistic_pit() -> None:
    result = preflight()
    assert result.profile is PERMITTED_PROFILE
    assert result.profile is InformationSetProfile.PROVIDER_REALISTIC_PIT
    assert "PUBLIC_PIT" not in _executable(COMPOSITION)


# ---------------------------------------------------------------------------
# The result is closed, immutable and safe
# ---------------------------------------------------------------------------


def test_the_result_is_frozen_slotted_and_refuses_subclassing() -> None:
    result = preflight()
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


#: A result that describes a plan which could actually have passed.
VALID_RESULT: Final[dict[str, Any]] = {
    "status": PreflightStatus.VALIDATED_OFFLINE,
    "request_count": 1,
    "max_attempts": 3,
    "max_response_bytes": 1024,
    "max_run_bytes": 4096,
    "retry_budget": 8,
    "acquisition_mode": AcquisitionMode.QUALIFICATION,
    "profile": PERMITTED_PROFILE,
}


def result_with(**overrides: Any) -> QualificationPreflight:
    return QualificationPreflight(**{**VALID_RESULT, **overrides})


def test_the_valid_result_is_accepted() -> None:
    """The baseline every adversarial case below is one change away from.

    Without this, a refusal test proves nothing: every case would fail whether or
    not the invariant under test is the reason.
    """
    assert result_with().status is PreflightStatus.VALIDATED_OFFLINE


#: Every way a result can fail to describe a validated plan.
#:
#: The zeros are the defect correction round 1 found: an earlier revision
#: accepted zero for every count while still reporting VALIDATED_OFFLINE, so an
#: independently constructed result could claim a run of no requests, no attempts
#: and no bytes had been validated. No plan produces those numbers.
INVALID_RESULTS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("zero-requests", {"request_count": 0}),
    ("zero-attempts", {"max_attempts": 0}),
    ("zero-response-bytes", {"max_response_bytes": 0}),
    ("zero-run-bytes", {"max_run_bytes": 0}),
    ("negative-requests", {"request_count": -1}),
    ("negative-retry-budget", {"retry_budget": -1}),
    ("requests-above-ceiling", {"request_count": MAX_REQUESTS + 1}),
    ("attempts-above-ceiling", {"max_attempts": MAX_ATTEMPTS_CEILING + 1}),
    ("response-above-ceiling", {"max_response_bytes": MAX_RESPONSE_BYTES + 1}),
    ("run-above-ceiling", {"max_run_bytes": MAX_RUN_BYTES + 1}),
    ("retry-budget-above-ceiling", {"retry_budget": MAX_RETRY_BUDGET + 1}),
    (
        "response-ceiling-above-run-ceiling",
        {"max_response_bytes": 8192, "max_run_bytes": 4096},
    ),
    (
        "retry-arithmetic-exceeds-budget",
        {"request_count": 10, "max_attempts": 5, "retry_budget": 8},
    ),
    ("boolean-request-count", {"request_count": True}),
    ("boolean-retry-budget", {"retry_budget": False}),
    ("float-run-bytes", {"max_run_bytes": 4096.0}),
    ("float-request-count", {"request_count": 1.0}),
    ("string-request-count", {"request_count": "1"}),
    ("none-attempts", {"max_attempts": None}),
    ("status-token-not-member", {"status": "VALIDATED_OFFLINE"}),
    ("mode-token-not-member", {"acquisition_mode": "QUALIFICATION"}),
    ("profile-token-not-member", {"profile": "PROVIDER_REALISTIC_PIT"}),
    ("backfill-mode", {"acquisition_mode": AcquisitionMode.BACKFILL}),
    ("update-mode", {"acquisition_mode": AcquisitionMode.UPDATE}),
    ("public-pit-profile", {"profile": InformationSetProfile.PUBLIC_PIT}),
)


@pytest.mark.parametrize(
    ("label", "overrides"), INVALID_RESULTS, ids=[case[0] for case in INVALID_RESULTS]
)
def test_the_result_refuses_a_value_no_validated_plan_could_produce(
    label: str, overrides: dict[str, Any]
) -> None:
    with pytest.raises(SharadarRequestError):
        result_with(**overrides)


#: Legitimate boundaries, which a stricter-than-intended check would reject.
VALID_BOUNDARIES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("one-attempt-zero-budget", {"max_attempts": 1, "retry_budget": 0}),
    ("one-request", {"request_count": 1}),
    ("requests-at-ceiling", {"request_count": MAX_REQUESTS, "max_attempts": 1, "retry_budget": 0}),
    (
        "attempts-at-ceiling",
        {"request_count": 1, "max_attempts": MAX_ATTEMPTS_CEILING, "retry_budget": 4},
    ),
    (
        "byte-ceilings-at-maximum",
        {"max_response_bytes": MAX_RESPONSE_BYTES, "max_run_bytes": MAX_RUN_BYTES},
    ),
    ("equal-byte-ceilings", {"max_response_bytes": 4096, "max_run_bytes": 4096}),
    ("retry-budget-at-ceiling", {"retry_budget": MAX_RETRY_BUDGET}),
    (
        "retry-arithmetic-exactly-at-budget",
        {"request_count": 4, "max_attempts": 3, "retry_budget": 8},
    ),
)


@pytest.mark.parametrize(
    ("label", "overrides"), VALID_BOUNDARIES, ids=[case[0] for case in VALID_BOUNDARIES]
)
def test_the_result_accepts_every_legitimate_boundary(
    label: str, overrides: dict[str, Any]
) -> None:
    """A check tightened past the contract would reject a real preflight."""
    assert result_with(**overrides).status is PreflightStatus.VALIDATED_OFFLINE


def test_the_result_bounds_come_from_the_compiled_constants() -> None:
    """Not a second set of numbers written beside the first."""
    source = _executable(COMPOSITION)
    for constant in (
        "MAX_REQUESTS",
        "MAX_ATTEMPTS_CEILING",
        "MAX_RESPONSE_BYTES",
        "MAX_RUN_BYTES",
        "MAX_RETRY_BUDGET",
    ):
        assert constant in source, f"{constant} is not the source of its own bound"


# ---------------------------------------------------------------------------
# Failure is closed, and happens before anything could have been touched
# ---------------------------------------------------------------------------


def test_a_bad_bucket_is_refused_without_echoing_it() -> None:
    with pytest.raises(ObjectStoreBackendError) as raised:
        preflight(licensed_bucket=CANARY_BUCKET + "/../escape")
    assert CANARY_BUCKET not in str(raised.value)


def test_a_bad_timeout_is_refused() -> None:
    for rejected in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(SharadarRequestError):
            preflight(timeout_seconds=rejected)


def test_a_clock_that_cannot_answer_is_refused_at_construction() -> None:
    with pytest.raises(QualificationRuntimeError):
        preflight(clock=object())


def test_a_plan_the_client_could_overshoot_is_refused_before_any_call() -> None:
    """A per-response ceiling has to bind before the response exists."""
    transport = CountingTransport(max_response_bytes=1 << 24)
    s3 = CountingS3Client()
    limits = QualificationLimits(max_response_bytes=32)
    with pytest.raises(QualificationRuntimeError):
        preflight(transport=transport, s3_client=s3, subject_plan=plan(limits=limits))
    assert (transport.calls, s3.put_calls, s3.head_calls) == (0, 0, 0)


def test_a_retry_budget_the_client_would_exceed_is_refused() -> None:
    transport = CountingTransport()
    s3 = CountingS3Client()
    with pytest.raises(QualificationPlanError):
        preflight(
            transport=transport,
            s3_client=s3,
            subject_plan=plan(limits=QualificationLimits(retry_budget=1)),
        )
    assert (transport.calls, s3.put_calls, s3.head_calls) == (0, 0, 0)


def test_a_plan_that_is_not_a_plan_is_refused() -> None:
    with pytest.raises(QualificationRuntimeError):
        preflight(subject_plan=object())


# ---------------------------------------------------------------------------
# The transport contract, enforced where the client owns it
# ---------------------------------------------------------------------------
#
# `SharadarClient` accepted any object as a transport. An object carrying only a
# plausible `max_response_bytes` composed and validated cleanly while being
# unable to perform a single request -- a `Protocol` annotation is a static
# claim, and nothing checked it. Enforced at the client, not duplicated here:
# the client is the thing that calls `get`.


def test_a_transport_without_get_is_refused() -> None:
    with pytest.raises(SharadarRequestError):
        preflight(transport=TransportWithoutGet())


def test_a_transport_whose_get_is_not_callable_is_refused() -> None:
    with pytest.raises(SharadarRequestError):
        preflight(transport=TransportWithNonCallableGet())


def test_a_transport_whose_lookup_raises_is_sanitized() -> None:
    """A hostile ``__getattr__`` raises carrying its own text, which must not
    escape as the refusal."""
    with pytest.raises(SharadarRequestError) as raised:
        preflight(transport=TransportWithHostileLookup())
    assert CANARY_BACKEND_MESSAGE not in f"{raised.value!r} {raised.value!s}"


def test_a_transport_whose_ceiling_lookup_raises_is_sanitized() -> None:
    """Answering ``get`` and refusing to say how much it may return is a
    dependency that cannot be reasoned about, not one that declined to answer."""
    with pytest.raises(SharadarRequestError) as raised:
        preflight(transport=TransportWithHostileCeiling())
    assert CANARY_BACKEND_MESSAGE not in f"{raised.value!r} {raised.value!s}"


def test_a_transport_that_declares_no_ceiling_falls_back_conservatively() -> None:
    """The existing conservative direction is kept: a transport that will not
    narrow the ceiling is assumed able to return the most any transport may."""
    client = SharadarClient(
        credential=credential(),
        # Deliberately narrower than the protocol: the point is a stand-in that
        # does not declare a ceiling, which is what the fallback exists for.
        transport=TransportWithNoCeiling(),  # type: ignore[arg-type]
        pacer=silent_pacer(),
        retry_policy=DEFAULT_RETRY_POLICY,
        timeout_seconds=30.0,
    )
    assert client.max_response_bytes == MAX_RESPONSE_BYTES_CEILING


def test_the_transport_ceiling_is_read_exactly_once() -> None:
    """Resolved at construction, then stored."""
    transport = CountingTransport(max_response_bytes=4096)
    client = SharadarClient(
        credential=credential(),
        transport=transport,
        pacer=silent_pacer(),
        retry_policy=DEFAULT_RETRY_POLICY,
        timeout_seconds=30.0,
    )
    assert transport.ceiling_reads == 1
    for _ in range(5):
        assert client.max_response_bytes == 4096
    assert transport.ceiling_reads == 1, "the client re-consulted a mutable dependency"


def test_changing_the_transport_after_construction_cannot_move_the_ceiling() -> None:
    """A bound is not a bound if the thing it bounds can move it.

    Before this, a plan could be validated against one ceiling and executed
    against another, because the object that declared it is free to change its
    mind between the two.
    """
    transport = CountingTransport(max_response_bytes=4096)
    client = SharadarClient(
        credential=credential(),
        transport=transport,
        pacer=silent_pacer(),
        retry_policy=DEFAULT_RETRY_POLICY,
        timeout_seconds=30.0,
    )
    transport.declared = MAX_RESPONSE_BYTES_CEILING
    assert client.max_response_bytes == 4096


def test_a_mutating_transport_cannot_change_a_reported_preflight_ceiling() -> None:
    transport = CountingTransport(max_response_bytes=4096)
    result = preflight(transport=transport)
    assert result.max_response_bytes == 4096
    transport.declared = 1
    assert result.max_response_bytes == 4096


def test_no_transport_call_occurs_while_the_contract_is_checked() -> None:
    """Every refusal above happens at construction, before any request."""
    for bad in (
        TransportWithoutGet(),
        TransportWithNonCallableGet(),
        TransportWithHostileLookup(),
        TransportWithHostileCeiling(),
    ):
        s3 = CountingS3Client()
        with pytest.raises(SharadarRequestError):
            preflight(transport=bad, s3_client=s3)
        assert (s3.put_calls, s3.head_calls) == (0, 0)


# ---------------------------------------------------------------------------
# Zero activity, counted
# ---------------------------------------------------------------------------


def test_a_successful_preflight_touches_no_transport_and_no_s3() -> None:
    transport = CountingTransport()
    s3 = CountingS3Client()
    clock = CountingClock()
    preflight(transport=transport, s3_client=s3, clock=clock)

    assert transport.calls == 0, "a provider request was made"
    assert s3.put_calls == 0, "put_object was called"
    assert s3.head_calls == 0, "head_object was called"
    # One clock read, and only because `validate()` probes it: a clock that
    # cannot answer is a dependency defect, and discovering it after the first
    # fetch would spend a provider request to learn something checkable for free.
    assert clock.calls == 1


def test_no_object_store_publication_occurs() -> None:
    """The store is real; only its injected client is a fake, so a publication
    would have to go through ``put_object`` -- which is counted here.

    An earlier revision reached ``object.__getattribute__(composition, "_store")``
    to assert the store was real. That reach *was* the defect; the store's
    realness is established by its bucket-name refusal instead.
    """
    s3 = CountingS3Client()
    preflight(s3_client=s3)
    assert (s3.put_calls, s3.head_calls) == (0, 0)
    with pytest.raises(ObjectStoreBackendError):
        preflight(s3_client=s3, licensed_bucket="A_BAD_BUCKET")
    assert (s3.put_calls, s3.head_calls) == (0, 0)


def test_the_credential_is_never_revealed(monkeypatch: pytest.MonkeyPatch) -> None:
    reveals = {"count": 0}
    real = SharadarCredential.reveal

    def spy(self: SharadarCredential) -> str:
        reveals["count"] += 1
        return real(self)

    monkeypatch.setattr(SharadarCredential, "reveal", spy)
    preflight()
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
    result = preflight(subject_plan=plan(subject=CANARY_SUBJECT))
    rendered = f"{result!r} {result!s} "
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
        preflight(licensed_bucket=CANARY_BUCKET + "!!")
    failures.append(f"{bucket_refusal.value!r} {bucket_refusal.value!s}")

    with pytest.raises(SharadarRequestError) as timeout_refusal:
        preflight(timeout_seconds=-1.0)
    failures.append(f"{timeout_refusal.value!r} {timeout_refusal.value!s}")

    with pytest.raises(QualificationRuntimeError) as clock_refusal:
        preflight(clock=object())
    failures.append(f"{clock_refusal.value!r} {clock_refusal.value!s}")

    with pytest.raises(SharadarRequestError) as transport_refusal:
        preflight(transport=TransportWithHostileLookup())
    failures.append(f"{transport_refusal.value!r} {transport_refusal.value!s}")

    joined = " ".join(failures)
    for canary in CANARIES:
        assert canary not in joined


def test_the_result_repr_carries_only_counts_and_members() -> None:
    """There is no composition object to have a repr any more, and the result's
    default one is safe because every field is a count or a closed member."""
    rendered = repr(preflight(licensed_bucket="a-second-synthetic-bucket"))
    assert "a-second-synthetic-bucket" not in rendered
    assert "VALIDATED_OFFLINE" in rendered


# ---------------------------------------------------------------------------
# Structural: no qualification-run execution surface, no runner, no caller
# ---------------------------------------------------------------------------

EXECUTION_LIKE = re.compile(
    r"^_*(execute|run|fetch|publish|upload|send|post|put|get|start|invoke|main|ingest|acquire)"
)


#: Dunders are the object protocol, not a surface a caller reaches for to make
#: something happen. Excluded by shape rather than by name, so a future dunder
#: does not have to be added to a list.
def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def test_the_module_has_exactly_one_execution_like_callable() -> None:
    """ADR-0017 authorized **one**, and named it. Everything else is still
    refused, private spellings included: a leading underscore hides a function
    from a reviewer skimming, not from a caller who knows the name.

    Inverted rather than deleted. The earlier rule was 'none exists', which was
    correct while offline preflight was the only operation; deleting it would
    have left a second, unreviewed execution surface unguarded.
    """
    import kalpamani.data.ingest.sharadar.composition as module

    found = [
        name
        for name, member in inspect.getmembers(module)
        if callable(member) and not _is_dunder(name) and EXECUTION_LIKE.match(name)
    ]
    assert found == ["execute_qualification_acquisition"], (
        f"exactly one authorized execution surface may exist. Found: {found}"
    )


def test_the_module_defines_exactly_two_public_operations() -> None:
    """Offline preflight, and the ADR-0017 bounded acquisition. A third would
    be a new surface nobody reviewed."""
    functions = [
        node.name
        for node in _tree(COMPOSITION).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    assert functions == [
        "_refuse",
        "_exact_count",
        "preflight_qualification_composition",
        "execute_qualification_acquisition",
    ]
    assert [name for name in functions if not name.startswith("_")] == [
        "preflight_qualification_composition",
        "execute_qualification_acquisition",
    ]


def test_the_module_names_execute_exactly_where_adr_0017_authorized_it() -> None:
    """Once as the authorized function name, once as the single call it makes.

    A count rather than a prohibition: the earlier rule was that the word did
    not appear at all, and dropping it entirely would have let a second call
    site -- a retry, a fallback, a loop body -- arrive unnoticed."""
    source = _executable(COMPOSITION)
    # Twice: the definition, and the `__all__` entry that exports it.
    assert source.count("execute_qualification_acquisition") == 2
    assert source.count(".execute(") == 1


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


def test_nothing_calls_the_composition_outside_this_file() -> None:
    """One authorized caller, and no other.

    ADR-0014's version of this said *nobody* calls it, which was true while no
    caller was authorized. ADR-0015 authorized exactly one -- the operator binding
    preflight, which refuses by default -- and the empirical acquisition
    composition adds a second, as the offline plan preflight it runs before its
    first request. The rule is narrowed again rather than dropped: a **third**
    caller, a script, a task or an ad-hoc invocation still fails here.
    """
    allowed = {
        Path(__file__).resolve(),
        BINDING_PREFLIGHT,
        BINDING_PREFLIGHT_TEST,
        SRC / "kalpamani" / "data" / "qualify" / "sharadar" / "acquisition.py",
    }
    offenders: list[str] = []
    for root in (SRC, SCRIPTS, TESTS):
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


def test_no_module_imports_the_composition_outside_this_file() -> None:
    """The composition has a small, named set of importers, and no others.

    ADR-0017 added the authenticated entry point and its tests; the empirical
    qualification package adds its acquisition composition and the boundary test
    that asserts what that composition may not import. Listed by name rather than
    by relaxing the scan, so a tenth importer still fails here.
    """
    allowed = {
        Path(__file__).resolve(),
        COMPOSITION,
        BINDING_PREFLIGHT,
        BINDING_PREFLIGHT_TEST,
        SCRIPTS / "sharadar_authenticated_qualification.py",
        TESTS / "unit" / "test_sharadar_authenticated_qualification.py",
        TESTS / "unit" / "test_sharadar_acquisition_composition.py",
        SRC / "kalpamani" / "data" / "qualify" / "sharadar" / "acquisition.py",
        TESTS / "unit" / "test_sharadar_qualification_package_boundaries.py",
    }
    offenders: list[str] = []
    for root in (SRC, SCRIPTS, TESTS):
        for path in _python_files(root):
            if path in allowed:
                continue
            if "sharadar.composition" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == [], f"the composition is imported at: {offenders}"


def test_the_package_does_not_re_export_the_composition() -> None:
    """Not exported, so ``from ...sharadar import preflight_qualification_composition``
    does not work. Reaching it takes naming the module, which is a decision."""
    import kalpamani.data.ingest.sharadar as provider

    assert "preflight_qualification_composition" not in getattr(provider, "__all__", ())
    assert not hasattr(provider, "preflight_qualification_composition")
    assert not hasattr(provider, "QualificationPreflight")


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
