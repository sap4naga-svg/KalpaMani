"""The dormant runtime, exercised end to end against synthetic parts. **No socket opens.**

The client is the shipped one — its pacing, retries, exact-type checks and
redaction are all real. Only the transport is synthetic, and it holds no host,
resolves no name and opens no socket. The object store is the shipped in-memory
backend, so admission, content addressing, idempotency and collision refusal are
the real rules rather than a fixture's guess at them.

What that buys: a test here cannot pass because a fake was lenient. It passes
because the runtime handed real components the right things and read their answers
correctly.

Every payload is invented and opaque. No vendor row, worked example or sampled
response appears here or is reachable from here.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import Any

import pytest

from fixtures.sharadar_provider import ok
from fixtures.sharadar_runtime import (
    LEAK_CANARIES,
    OTHER_RUN_ID,
    PAYLOAD_A,
    PAYLOAD_B,
    PAYLOAD_C,
    RUN_INSTANT,
    SUBJECT_A,
    SUBJECT_B,
    BadClock,
    FixedClock,
    LeakyClient,
    RaisingClock,
    RecordingStore,
    RefusingStore,
    client,
    snapshot_plan,
    three_dataset_plan,
)
from kalpamani.data.contracts.canonical import sha256_hex
from kalpamani.data.contracts.errors import (
    ObjectAlreadyExistsError,
    ObjectStoreBackendError,
)
from kalpamani.data.contracts.vocabulary import (
    DataClassification,
    InformationSetProfile,
    ObjectStoreFailure,
    ObjectStoreOperation,
)
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.ingest.sharadar.qualification import (
    PERMITTED_PROFILE,
    QualificationDefect,
    QualificationLimits,
    QualificationPlanError,
)
from kalpamani.data.ingest.sharadar.runtime import (
    PublicationDisposition,
    QualificationFailure,
    QualificationOutcome,
    QualificationRunResult,
    QualificationRuntime,
    QualificationRuntimeError,
    RequestOutcome,
    refused_result,
)

pytestmark = pytest.mark.unit


def runtime(
    payloads: list[bytes], *, store: Any = None, clock: Any = None, max_attempts: int = 1
) -> tuple[QualificationRuntime, Any, Any]:
    """A runtime wired to a scripted transport and a recording store."""
    built, transport = client([ok(payload) for payload in payloads], max_attempts=max_attempts)
    backing = store if store is not None else RecordingStore()
    return (
        QualificationRuntime(
            client=built, store=backing, clock=clock if clock is not None else FixedClock()
        ),
        backing,
        transport,
    )


# ---------------------------------------------------------------------------
# Dependency boundaries
# ---------------------------------------------------------------------------


def test_the_runtime_accepts_only_an_exact_client() -> None:
    """A duck-typed client could hold a credential this runtime never validated."""
    with pytest.raises(QualificationRuntimeError) as caught:
        QualificationRuntime(client=LeakyClient(), store=RecordingStore(), clock=FixedClock())  # type: ignore[arg-type]
    assert caught.value.failure is QualificationFailure.DEPENDENCY_MALFORMED


@pytest.mark.parametrize("store", [None, object(), "store", 7])
def test_a_store_that_cannot_publish_is_refused(store: Any) -> None:
    built, _ = client([])
    with pytest.raises(QualificationRuntimeError):
        QualificationRuntime(client=built, store=store, clock=FixedClock())


@pytest.mark.parametrize("clock", [None, object(), 7])
def test_a_clock_without_now_is_refused(clock: Any) -> None:
    built, _ = client([])
    with pytest.raises(QualificationRuntimeError):
        QualificationRuntime(client=built, store=RecordingStore(), clock=clock)


def test_the_repr_is_a_constant() -> None:
    engine, _, _ = runtime([])
    assert repr(engine) == "QualificationRuntime(provider=sharadar, mode=injected)"


def test_the_runtime_has_no_public_surface_beyond_validate_and_execute() -> None:
    """A wider surface is a wider thing to authorize later."""
    surface = {name for name in vars(QualificationRuntime) if not name.startswith("_")}
    assert surface == {"validate", "execute"}


# ---------------------------------------------------------------------------
# Validation happens first, and completely
# ---------------------------------------------------------------------------


def test_a_refused_plan_causes_zero_provider_and_zero_store_calls() -> None:
    """The whole point of validating first: a bad plan costs nothing."""
    engine, store, transport = runtime([PAYLOAD_A])
    plan = snapshot_plan(SUBJECT_A, limits=QualificationLimits(retry_budget=0))
    engine_with_retries, store_b, transport_b = runtime([PAYLOAD_A], max_attempts=3)

    with pytest.raises(QualificationPlanError) as caught:
        engine_with_retries.execute(plan)
    assert caught.value.defect is QualificationDefect.RETRY_BUDGET_EXCEEDED
    assert transport_b.call_count == 0
    assert store_b.call_count == 0
    # The first pair is untouched, which is the control.
    assert transport.call_count == 0 and store.call_count == 0
    assert engine is not engine_with_retries


def test_the_retry_budget_is_checked_against_the_injected_clients_policy() -> None:
    """A budget that only described intent would be correct in review and wrong in
    production. This one reads the client."""
    engine, _, _ = runtime([PAYLOAD_A], max_attempts=3)
    with pytest.raises(QualificationPlanError):
        engine.validate(snapshot_plan(SUBJECT_A, limits=QualificationLimits(retry_budget=1)))
    engine.validate(snapshot_plan(SUBJECT_A, limits=QualificationLimits(retry_budget=2)))


def test_validate_fetches_nothing() -> None:
    engine, store, transport = runtime([PAYLOAD_A])
    requests = engine.validate(snapshot_plan(SUBJECT_A))
    assert len(requests) == 1
    assert transport.call_count == 0 and store.call_count == 0


@pytest.mark.parametrize("plan", [None, object(), "plan", 7])
def test_a_non_exact_plan_is_refused(plan: Any) -> None:
    engine, _, transport = runtime([])
    with pytest.raises(QualificationRuntimeError):
        engine.execute(plan)
    assert transport.call_count == 0


# ---------------------------------------------------------------------------
# The synthetic fetch -> Bronze -> object store flow
# ---------------------------------------------------------------------------


def test_a_complete_run_publishes_every_planned_request() -> None:
    engine, store, transport = runtime([PAYLOAD_A, PAYLOAD_B, PAYLOAD_C])
    result = engine.execute(three_dataset_plan(SUBJECT_A))

    assert result.outcome is QualificationOutcome.COMPLETED
    assert result.failure is None
    assert result.partial is False
    assert result.planned_requests == result.completed_requests == 3
    assert result.stored_objects == 3
    assert result.already_present_objects == 0
    assert transport.call_count == 3
    # Three publications, each writing a claim, a payload and a record.
    assert store.call_count == 9


def test_requests_are_issued_in_the_plans_canonical_order() -> None:
    engine, _, _ = runtime([PAYLOAD_A, PAYLOAD_B, PAYLOAD_C])
    result = engine.execute(three_dataset_plan(SUBJECT_A))
    assert [outcome.dataset for outcome in result.outcomes] == [
        SharadarDataset.TICKERS,
        SharadarDataset.STOCKS,
        SharadarDataset.ACTIONS,
    ]


def test_exact_bytes_and_digests_are_preserved() -> None:
    """The payload is opaque: never decoded, parsed or validated."""
    malformed = b"\x00\xff not valid utf-8 \xfe truncated,"
    engine, _, _ = runtime([malformed])
    result = engine.execute(snapshot_plan(SUBJECT_A))
    outcome = result.outcomes[0]
    assert outcome.content_sha256 == sha256_hex(malformed)
    assert outcome.byte_count == len(malformed)
    assert result.total_bytes == len(malformed)


def test_every_outcome_is_licensed_and_provider_realistic() -> None:
    engine, _, _ = runtime([PAYLOAD_A, PAYLOAD_B, PAYLOAD_C])
    result = engine.execute(three_dataset_plan(SUBJECT_A))
    for outcome in result.outcomes:
        assert outcome.classification is DataClassification.LICENSED
        assert outcome.profile is PERMITTED_PROFILE


def test_nothing_is_published_under_control() -> None:
    """CONTROL publication is deferred; the only constructor is LICENSED-only."""
    engine, store, _ = runtime([PAYLOAD_A])
    engine.execute(snapshot_plan(SUBJECT_A))
    for logical in store.put_keys:
        assert logical.startswith("licensed/")
        assert "control" not in logical.split("/")


def test_the_run_uses_the_injected_clock_and_never_a_wall_clock() -> None:
    """Four reads for three requests: one probe during validation, then one per
    retrieval. The probe is what makes a broken clock cost nothing."""
    clock = FixedClock()
    engine, _, _ = runtime([PAYLOAD_A, PAYLOAD_B, PAYLOAD_C], clock=clock)
    engine.execute(three_dataset_plan(SUBJECT_A))
    assert clock.calls == 4
    assert clock.instant == RUN_INSTANT


def test_a_naive_or_malformed_clock_reading_is_refused() -> None:
    """A naive instant would be recorded as though its offset were known.

    Refused during validation, so a broken clock costs **zero** provider
    requests -- the same argument as validating the plan before fetching.
    """
    for answer in (None, "2026-08-28", datetime(2026, 8, 28, 15, 30, 0), 7):
        engine, store, transport = runtime([PAYLOAD_A], clock=BadClock(answer))
        with pytest.raises(QualificationRuntimeError) as caught:
            engine.execute(snapshot_plan(SUBJECT_A))
        assert caught.value.failure is QualificationFailure.DEPENDENCY_MALFORMED
        assert transport.call_count == 0 and store.call_count == 0


def test_a_non_utc_clock_reading_is_normalised_rather_than_refused() -> None:
    """An aware instant in another offset is unambiguous; it is converted, so two
    machines record the same instant for the same bytes."""
    from datetime import timedelta, timezone

    elsewhere = RUN_INSTANT.astimezone(timezone(timedelta(hours=-5)))
    engine, _, _ = runtime([PAYLOAD_A], clock=BadClock(elsewhere))
    result = engine.execute(snapshot_plan(SUBJECT_A))
    assert result.outcome is QualificationOutcome.COMPLETED
    baseline, _, _ = runtime([PAYLOAD_A], clock=FixedClock())
    assert baseline.execute(snapshot_plan(SUBJECT_A)).outcomes[0].content_sha256 == (
        result.outcomes[0].content_sha256
    )


# ---------------------------------------------------------------------------
# Idempotency, conflict and resume
# ---------------------------------------------------------------------------


def test_an_identical_replay_is_idempotent() -> None:
    """A resumed run republishes identical bytes and stores nothing new."""
    store = RecordingStore()
    first, _, _ = runtime([PAYLOAD_A], store=store)
    assert first.execute(snapshot_plan(SUBJECT_A)).stored_objects == 1

    second, _, _ = runtime([PAYLOAD_A], store=store)
    result = second.execute(snapshot_plan(SUBJECT_A))
    assert result.outcome is QualificationOutcome.COMPLETED
    assert result.stored_objects == 0
    assert result.already_present_objects == 1
    assert result.outcomes[0].disposition is PublicationDisposition.ALREADY_PRESENT


def test_a_clock_that_breaks_mid_run_halts_and_keeps_the_partial_record() -> None:
    """Different from a clock that was broken at the start, deliberately.

    Nothing had happened then, so raising lost nothing. Here objects are already
    published and immutable, so the run halts and the result says which ones --
    and it is reported as a dependency fault, not as a storage failure, so a
    reader is not sent to look at the bucket.
    """

    class FailsAfter:
        def __init__(self, good: int) -> None:
            self.remaining = good

        def now(self) -> Any:
            if self.remaining <= 0:
                return None
            self.remaining -= 1
            return RUN_INSTANT

    # One probe during validation, then one good read, then a fault.
    engine, _store, _ = runtime([PAYLOAD_A, PAYLOAD_B, PAYLOAD_C], clock=FailsAfter(2))
    result = engine.execute(three_dataset_plan(SUBJECT_A))
    assert result.outcome is QualificationOutcome.HALTED
    assert result.failure is QualificationFailure.DEPENDENCY_MALFORMED
    assert result.partial is True
    assert result.completed_requests == 1


def test_resume_after_a_partial_run_completes_the_remainder() -> None:
    """The store's content identity does the work; no bookkeeping file is kept."""
    store = RecordingStore()
    from fixtures.sharadar_provider import failing

    built, _ = client([ok(PAYLOAD_A), failing(500)])
    partial = QualificationRuntime(client=built, store=store, clock=FixedClock())
    first = partial.execute(three_dataset_plan(SUBJECT_A))
    assert first.outcome is QualificationOutcome.HALTED
    assert first.partial is True
    assert first.completed_requests == 1

    resumed, _, _ = runtime([PAYLOAD_A, PAYLOAD_B, PAYLOAD_C], store=store)
    second = resumed.execute(three_dataset_plan(SUBJECT_A))
    assert second.outcome is QualificationOutcome.COMPLETED
    assert second.completed_requests == 3
    # The first object was already there; the other two are new.
    assert second.already_present_objects == 1
    assert second.stored_objects == 2


def test_different_bytes_are_a_different_object_not_a_collision() -> None:
    """A name here **is** a content address, so changed bytes get a new name.

    Worth stating explicitly, because "a changed payload is refused" is the
    intuition an append-only store invites and it is not what happens: the second
    payload is a second object, and the first is still there, unmodified. The
    refusal case is the acquisition *identity* below, not the bytes.
    """
    store = RecordingStore()
    first, _, _ = runtime([PAYLOAD_A], store=store)
    first.execute(snapshot_plan(SUBJECT_A))

    second, _, _ = runtime([PAYLOAD_B], store=store)
    result = second.execute(snapshot_plan(SUBJECT_A, ingestion_run_id=OTHER_RUN_ID))
    assert result.outcome is QualificationOutcome.COMPLETED
    assert result.outcomes[0].content_sha256 == sha256_hex(PAYLOAD_B)


def test_one_run_id_cannot_claim_one_digest_for_two_datasets() -> None:
    """The real collision, and the runtime meets it in an ordinary run.

    ``(digest, run id)`` is a **global** acquisition identity that binds the
    provider and the dataset. If two datasets in one run return byte-identical
    payloads, the second claim contradicts the first and is refused -- which is
    exactly the guarantee that stops two providers claiming one retrieval.

    Reported as ``CONTENT_CONFLICT`` and never overwritten.
    """
    engine, _store, _ = runtime([PAYLOAD_A, PAYLOAD_A, PAYLOAD_A])
    result = engine.execute(three_dataset_plan(SUBJECT_A))

    assert result.outcome is QualificationOutcome.HALTED
    assert result.failure is QualificationFailure.CONTENT_CONFLICT
    assert result.partial is True
    assert result.completed_requests == 1, "the first dataset published, the second was refused"


def test_a_second_run_id_records_a_second_acquisition_of_the_same_bytes() -> None:
    store = RecordingStore()
    first, _, _ = runtime([PAYLOAD_A], store=store)
    first.execute(snapshot_plan(SUBJECT_A))

    second, _, _ = runtime([PAYLOAD_A], store=store)
    result = second.execute(snapshot_plan(SUBJECT_A, ingestion_run_id=OTHER_RUN_ID))
    assert result.outcome is QualificationOutcome.COMPLETED
    assert result.outcomes[0].disposition is PublicationDisposition.ALREADY_PRESENT


# ---------------------------------------------------------------------------
# Stop on first failure, and say that the run was partial
# ---------------------------------------------------------------------------


def test_a_provider_failure_stops_the_run_at_that_request() -> None:
    from fixtures.sharadar_provider import failing

    built, transport = client([ok(PAYLOAD_A), failing(404)])
    engine = QualificationRuntime(client=built, store=RecordingStore(), clock=FixedClock())
    result = engine.execute(three_dataset_plan(SUBJECT_A))

    assert result.outcome is QualificationOutcome.HALTED
    assert result.failure is QualificationFailure.PROVIDER_REQUEST_FAILED
    assert result.partial is True
    assert result.planned_requests == 3
    assert result.completed_requests == 1
    assert transport.call_count == 2, "the third request must never be attempted"


def test_a_partial_run_states_that_it_is_partial_rather_than_implying_a_rollback() -> None:
    """Immutable objects across several requests have no rollback, so the result
    reports what stayed rather than pretending nothing did."""
    from fixtures.sharadar_provider import failing

    built, _ = client([ok(PAYLOAD_A), failing(500)])
    engine = QualificationRuntime(client=built, store=RecordingStore(), clock=FixedClock())
    result = engine.execute(three_dataset_plan(SUBJECT_A))
    assert result.partial is True
    assert result.stored_objects == 1
    assert len(result.outcomes) == 1
    assert result.total_bytes == len(PAYLOAD_A)


def test_a_storage_refusal_halts_the_run() -> None:
    store = RefusingStore(
        ObjectStoreBackendError(
            operation=ObjectStoreOperation.PUT, failure=ObjectStoreFailure.ACCESS_DENIED
        )
    )
    engine, _, _ = runtime([PAYLOAD_A], store=store)
    result = engine.execute(snapshot_plan(SUBJECT_A))
    assert result.outcome is QualificationOutcome.HALTED
    assert result.failure is QualificationFailure.STORAGE_REFUSED


def test_a_collision_from_the_store_is_reported_as_a_content_conflict() -> None:
    store = RefusingStore(ObjectAlreadyExistsError("synthetic"))
    engine, _, _ = runtime([PAYLOAD_A], store=store)
    result = engine.execute(snapshot_plan(SUBJECT_A))
    assert result.failure is QualificationFailure.CONTENT_CONFLICT


def test_an_unexpected_store_exception_is_classified_not_propagated() -> None:
    store = RefusingStore(RuntimeError("api_key=leak https://api.sharadar.com"))
    engine, _, _ = runtime([PAYLOAD_A], store=store)
    result = engine.execute(snapshot_plan(SUBJECT_A))
    assert result.failure is QualificationFailure.UNCLASSIFIED


def test_a_raising_clock_is_refused_without_disclosing_its_message() -> None:
    engine, _, _ = runtime([PAYLOAD_A], clock=RaisingClock())
    with pytest.raises(QualificationRuntimeError) as caught:
        engine.execute(snapshot_plan(SUBJECT_A))
    rendered = f"{caught.value!r} {caught.value!s}"
    for canary in LEAK_CANARIES:
        assert canary not in rendered
    assert caught.value.__cause__ is None


# ---------------------------------------------------------------------------
# Ceilings enforced at run time
# ---------------------------------------------------------------------------


def test_a_response_over_the_plans_ceiling_halts_before_publication() -> None:
    engine, store, _ = runtime([b"x" * 64])
    result = engine.execute(
        snapshot_plan(SUBJECT_A, limits=QualificationLimits(max_response_bytes=32))
    )
    assert result.failure is QualificationFailure.RESPONSE_TOO_LARGE
    assert store.call_count == 0, "nothing may be stored once the ceiling is exceeded"


def test_the_run_byte_ceiling_is_checked_before_publishing_not_after() -> None:
    """The ceiling bounds what is stored, not what was already stored."""
    engine, store, _ = runtime([PAYLOAD_A, PAYLOAD_B, PAYLOAD_C])
    result = engine.execute(
        three_dataset_plan(SUBJECT_A, limits=QualificationLimits(max_run_bytes=len(PAYLOAD_A) + 1))
    )
    assert result.failure is QualificationFailure.RUN_BYTE_CEILING_EXCEEDED
    assert result.completed_requests == 1
    assert result.total_bytes == len(PAYLOAD_A)
    assert store.call_count == 3, "only the first publication's three writes"


def test_a_payload_that_is_not_exact_bytes_halts_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``bytearray`` would let the bytes change after they were hashed.

    The shipped client cannot return one -- ``TransportResponse`` already pins an
    exact ``bytes`` body -- so this branch guards a *future* client rather than the
    present one. Patched at the class, because the client uses ``__slots__`` and
    has no instance dictionary to shadow.
    """
    from kalpamani.data.ingest.sharadar.client import SharadarClient

    monkeypatch.setattr(
        SharadarClient, "fetch", lambda self, request: bytearray(PAYLOAD_A), raising=True
    )
    engine, store, _ = runtime([PAYLOAD_A])
    result = engine.execute(snapshot_plan(SUBJECT_A))
    assert result.failure is QualificationFailure.PAYLOAD_NOT_EXACT_BYTES
    assert store.call_count == 0


# ---------------------------------------------------------------------------
# Result and outcome hygiene
# ---------------------------------------------------------------------------


def test_a_run_result_carries_no_payload_and_no_error_text() -> None:
    """Counts, identities and dispositions. Nothing a dependency said."""
    from dataclasses import fields

    outcome_fields = {field.name for field in fields(RequestOutcome)}
    assert "payload" not in outcome_fields and "body" not in outcome_fields
    result_fields = {field.name for field in fields(QualificationRunResult)}
    assert not result_fields & {"payload", "body", "message", "error", "url", "bucket"}


def test_a_run_result_discloses_nothing_when_rendered() -> None:
    from fixtures.sharadar_provider import failing

    built, _ = client([failing(403)])
    engine = QualificationRuntime(client=built, store=RecordingStore(), clock=FixedClock())
    rendered = repr(engine.execute(snapshot_plan(SUBJECT_A)))
    for canary in LEAK_CANARIES:
        assert canary not in rendered


@pytest.mark.parametrize("cls", [RequestOutcome, QualificationRunResult])
def test_result_types_refuse_subclassing(cls: type) -> None:
    with pytest.raises(QualificationRuntimeError):
        type("Sneaky", (cls,), {})


def test_a_refused_result_reports_zero_of_everything() -> None:
    result = refused_result(4)
    assert result.outcome is QualificationOutcome.REFUSED
    assert (result.completed_requests, result.stored_objects, result.total_bytes) == (0, 0, 0)
    assert result.outcomes == ()
    assert result.partial is False
    assert result.planned_requests == 4


@pytest.mark.parametrize("value", [-1, None, "4"])
def test_a_refused_result_refuses_a_malformed_count(value: Any) -> None:
    assert refused_result(value).planned_requests == 0


def test_a_runtime_error_carries_only_a_closed_failure() -> None:
    error = QualificationRuntimeError(QualificationFailure.DEPENDENCY_MALFORMED)
    assert str(error) == "sharadar qualification runtime refused: DEPENDENCY_MALFORMED"
    assert set(QualificationRuntimeError.__slots__) == {"failure"}
    assert QualificationRuntimeError("nonsense").failure is QualificationFailure.UNCLASSIFIED  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Point-in-time and permaticker
# ---------------------------------------------------------------------------


def test_no_outcome_is_ever_public_pit() -> None:
    engine, _, _ = runtime([PAYLOAD_A, PAYLOAD_B, PAYLOAD_C])
    result = engine.execute(three_dataset_plan(SUBJECT_A))
    for outcome in result.outcomes:
        assert outcome.profile is not InformationSetProfile.PUBLIC_PIT


def test_the_runtime_never_names_public_pit_at_all() -> None:
    """A profile that cannot be written cannot be written by accident."""
    import inspect

    from kalpamani.data.ingest.sharadar import runtime as module

    source = inspect.getsource(module)
    assert "PUBLIC_PIT" not in source.replace("``PUBLIC_PIT``", "")


def test_the_runtime_never_mentions_or_derives_permaticker() -> None:
    """`permaticker` is an opaque vendor-stable identifier whose level is publicly
    unresolved; the runtime treats payloads as bytes and parses none of them."""
    import ast
    import inspect

    from kalpamani.data.ingest.sharadar import qualification
    from kalpamani.data.ingest.sharadar import runtime as module

    def executable(source: str) -> str:
        """The module's code with every docstring removed.

        Scanning raw source would fire on the prose that states the rule, which
        would either weaken the guard or forbid explaining why it exists.
        """
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            ):
                continue
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
        return ast.unparse(tree)

    for source in (inspect.getsource(module), inspect.getsource(qualification)):
        lowered = executable(source).lower()
        assert "permaticker" not in lowered
        for verb in ("groupby", "group_by", "merge(", "json.loads", "decode("):
            assert verb not in lowered


def test_the_runtime_parses_no_payload() -> None:
    """A payload that was never valid anything still publishes."""
    engine, _, _ = runtime([b"\x00\x01\x02 not a csv \xff"])
    result = engine.execute(snapshot_plan(SUBJECT_A))
    assert result.outcome is QualificationOutcome.COMPLETED


# ---------------------------------------------------------------------------
# Dormancy
# ---------------------------------------------------------------------------


def test_importing_the_runtime_opens_no_socket_and_reads_no_environment() -> None:
    import subprocess
    import sys
    from pathlib import Path

    probe = (
        "import os, sys;"
        "seen=[];"
        "real=os.environ.get;"
        "os.environ.get=lambda *a, **k: seen.append(a[:1]) or real(*a, **k);"
        "import kalpamani.data.ingest.sharadar.runtime as m;"
        "import kalpamani.data.ingest.sharadar.qualification as q;"
        "print(len(seen),"
        " any(name.split('.')[0] in ('boto3','botocore','requests','httpx') "
        "for name in sys.modules))"
    )
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert completed.stdout.split() == ["0", "False"], completed.stdout


def test_a_full_run_opens_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the qualification runtime must not open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    engine, _, _ = runtime([PAYLOAD_A, PAYLOAD_B, PAYLOAD_C])
    assert engine.execute(three_dataset_plan(SUBJECT_A)).outcome is QualificationOutcome.COMPLETED


def test_two_subjects_across_three_datasets_stay_within_the_ceiling() -> None:
    """Six distinct payloads, because six identical ones would collide on the
    global acquisition claim -- which is a different property, tested above."""
    distinct = [b"synthetic-opaque-qualification-payload-%02d" % index for index in range(6)]
    engine, _, transport = runtime(distinct)
    result = engine.execute(three_dataset_plan(SUBJECT_A, SUBJECT_B))
    assert result.planned_requests == 6
    assert transport.call_count == 6
    assert result.stored_objects == 6
    assert result.outcome is QualificationOutcome.COMPLETED


def test_a_run_result_is_immutable() -> None:
    engine, _, _ = runtime([PAYLOAD_A])
    result = engine.execute(snapshot_plan(SUBJECT_A))
    with pytest.raises(FrozenInstanceError):
        result.partial = True  # type: ignore[misc]
    assert result.partial is False
    assert type(result.outcomes) is tuple


def test_the_utc_normalisation_uses_an_aware_instant() -> None:
    assert RUN_INSTANT.tzinfo is UTC
