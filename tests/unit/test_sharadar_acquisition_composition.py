"""The ADR-0017 acquisition path on the extended composition root.

ADR-0014 authorized one composition module and exactly one exposed operation:
offline preflight. ADR-0017 added a second operation to **that same module** --
``execute_qualification_acquisition`` -- because a second composition module would
have meant widening the single-constructor guard from one file to two.

Two kinds of check live here:

**Behavioural.** A composition is executed from synthetic fakes that count every
call they could receive, so "one provider request, three PutObject calls, no
object-byte read" is a number this file reads rather than a claim it repeats.

**Structural.** AST scans proving the new function composes rather than decides:
no parser, no second store, no retry, no loop, no report path, no CONTROL name.

Nothing here contacts Sharadar, AWS or any network. The credential is a
self-labelled synthetic string, the bucket is a synthetic name, and the payload is
synthetic bytes that no assertion ever decodes.
"""

from __future__ import annotations

import ast
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.ingest.sharadar.client import Pacer, RetryPolicy
from kalpamani.data.ingest.sharadar.composition import execute_qualification_acquisition
from kalpamani.data.ingest.sharadar.credentials import SharadarCredential
from kalpamani.data.ingest.sharadar.datasets import DateWindow, SharadarDataset
from kalpamani.data.ingest.sharadar.qualification import (
    DatasetPlan,
    QualificationPlan,
    QualificationSubject,
)
from kalpamani.data.ingest.sharadar.redaction import (
    SharadarErrorCode,
    SharadarRequestError,
)
from kalpamani.data.ingest.sharadar.runtime import QualificationRuntimeError
from kalpamani.data.ingest.sharadar.transport import (
    TransportResponse,
    TransportUnavailableError,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSITION = PROJECT_ROOT / "src" / "kalpamani" / "data" / "ingest" / "sharadar" / "composition.py"

#: A synthetic subject. Not a listed security: a real ticker compiled into a test
#: is a real ticker committed to a public repository for no reason.
SUBJECT = "SYNTHETICA"

#: A self-labelled synthetic credential. It is never revealed, printed or sent.
SYNTHETIC_KEY = "synthetic-not-a-real-key"

#: A syntactically valid bucket name that is deliberately not the governed one.
SYNTHETIC_BUCKET = "synthetic-licensed-bucket-for-tests"

#: Synthetic provider bytes. **No assertion in this file decodes them** -- that is
#: the opaque-payload contract, and a test that parsed them would be asserting the
#: opposite of what ADR-0012 requires.
PAYLOAD = b"synthetic-opaque-provider-bytes-not-csv"


class FixedClock:
    """A clock that answers one instant, so a window is reproducible."""

    def __init__(self, instant: datetime) -> None:
        self.instant = instant
        self.reads = 0

    def now(self) -> datetime:
        self.reads += 1
        return self.instant


class CountingTransport:
    """A provider transport that counts requests and returns synthetic bytes.

    It records the URLs it is handed so a disclosure canary can prove the key --
    which travels in the query string -- never reaches an assertion message.
    """

    max_response_bytes = 64 * 1024 * 1024

    def __init__(self, payload: bytes = PAYLOAD, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.requests = 0
        self.urls: list[str] = []

    def get(self, *, url: str, headers: object, timeout_seconds: float) -> TransportResponse:
        del headers, timeout_seconds
        self.requests += 1
        self.urls.append(url)
        return TransportResponse(status=self.status, body=self.payload)


class RaisingTransport:
    """A transport that refuses. Used to prove no retry follows a failure."""

    max_response_bytes = 64 * 1024 * 1024

    def __init__(self) -> None:
        self.requests = 0

    def get(self, *, url: str, headers: object, timeout_seconds: float) -> TransportResponse:
        del url, headers, timeout_seconds
        self.requests += 1
        raise TransportUnavailableError(SharadarErrorCode.NETWORK_UNREACHABLE)


class CountingS3Client:
    """An S3 client counting every operation the store may perform.

    ``occupied`` names keys whose first ``put_object`` answers ``412``, which is
    the only path on which the store issues a ``head_object`` at all.
    """

    def __init__(self, occupied: frozenset[str] = frozenset()) -> None:
        self.put_calls: list[str] = []
        self.head_calls: list[str] = []
        self.byte_reads = 0
        self.occupied = occupied

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        key = str(kwargs["Key"])
        self.put_calls.append(key)
        if key in self.occupied:
            raise _precondition_failed()
        return {"ChecksumSHA256": kwargs.get("ChecksumSHA256"), "ChecksumType": "FULL_OBJECT"}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        key = str(kwargs["Key"])
        self.head_calls.append(key)
        return {"Metadata": {}, "ChecksumSHA256": "", "ChecksumType": "FULL_OBJECT"}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        """Present and raising. The store has no read surface, so this must never
        be reached -- an absent method would prove only that the fake lacks one."""
        del kwargs
        self.byte_reads += 1
        raise AssertionError("the licensed store must never download object bytes")

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        """Deletion lives with a separately roled path, never with this store."""
        del kwargs
        raise AssertionError("the licensed store must never delete an object")


class _PreconditionFailedError(Exception):
    """A synthetic ``412``, shaped the way the store's classifier reads one."""

    def __init__(self) -> None:
        super().__init__("synthetic precondition failure")
        self.response = {
            "Error": {"Code": "PreconditionFailed"},
            "ResponseMetadata": {"HTTPStatusCode": 412},
        }


def _precondition_failed() -> Exception:
    return _PreconditionFailedError()


def _credential() -> SharadarCredential:
    return SharadarCredential(SYNTHETIC_KEY)


def _plan(*, execution_id: str = "synthetic-execution-01") -> QualificationPlan:
    """The ADR-0017 shape: one subject, one dataset, one page, one request."""
    return QualificationPlan(
        subjects=(QualificationSubject(SUBJECT),),
        datasets=(
            DatasetPlan(
                dataset=SharadarDataset.STOCKS,
                window=DateWindow(start=date(2026, 8, 23), end=date(2026, 8, 29)),
                page_limit=1,
                max_pages=1,
            ),
        ),
        execution_id=execution_id,
    )


def _execute(
    *,
    transport: Any,
    s3_client: CountingS3Client,
    clock: FixedClock | None = None,
    plan: QualificationPlan | None = None,
) -> Any:
    return execute_qualification_acquisition(
        credential=_credential(),
        transport=transport,
        pacer=Pacer(),
        retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=()),
        timeout_seconds=30.0,
        s3_client=s3_client,
        licensed_bucket=SYNTHETIC_BUCKET,
        clock=clock or FixedClock(datetime(2026, 8, 30, 12, 0, tzinfo=UTC)),
        plan=plan or _plan(),
    )


# ---------------------------------------------------------------------------
# Behavioural: exact operation counts
# ---------------------------------------------------------------------------


def test_one_provider_request_is_issued() -> None:
    transport = CountingTransport()
    _execute(transport=transport, s3_client=CountingS3Client())
    assert transport.requests == 1


def test_one_ordinary_success_issues_exactly_three_put_object_calls() -> None:
    """The claim, the payload and the acquisition record. Three, and no fourth."""
    s3 = CountingS3Client()
    _execute(transport=CountingTransport(), s3_client=s3)
    assert len(s3.put_calls) == 3


def test_three_put_calls_are_three_distinct_keys() -> None:
    s3 = CountingS3Client()
    _execute(transport=CountingTransport(), s3_client=s3)
    assert len(set(s3.put_calls)) == 3


def test_an_ordinary_success_issues_no_preflight_head_object() -> None:
    """A check-then-write is a race, and the bucket carries no versioning."""
    s3 = CountingS3Client()
    _execute(transport=CountingTransport(), s3_client=s3)
    assert s3.head_calls == []


def test_a_conditional_head_object_follows_a_412_and_only_a_412() -> None:
    s3 = CountingS3Client()
    _execute(transport=CountingTransport(), s3_client=s3)
    occupied = frozenset(s3.put_calls[:1])

    collided = CountingS3Client(occupied=occupied)
    _execute(transport=CountingTransport(), s3_client=collided)
    assert len(collided.head_calls) == 1


def test_conditional_head_object_calls_never_exceed_three() -> None:
    s3 = CountingS3Client()
    _execute(transport=CountingTransport(), s3_client=s3)

    collided = CountingS3Client(occupied=frozenset(s3.put_calls))
    _execute(transport=CountingTransport(), s3_client=collided)
    assert len(collided.head_calls) <= 3


def test_no_object_byte_read_occurs() -> None:
    """The fake *offers* ``get_object`` and it raises, so zero is a witnessed count
    rather than a fake that happens to lack the method."""
    s3 = CountingS3Client()
    _execute(transport=CountingTransport(), s3_client=s3)
    assert s3.byte_reads == 0


def test_no_control_classified_object_is_written() -> None:
    s3 = CountingS3Client()
    _execute(transport=CountingTransport(), s3_client=s3)
    assert [key for key in s3.put_calls if "control" in key.lower()] == []


def test_every_written_key_is_bronze() -> None:
    s3 = CountingS3Client()
    _execute(transport=CountingTransport(), s3_client=s3)
    assert all(key.startswith("bronze/") for key in s3.put_calls)


def test_a_transport_failure_produces_no_second_request() -> None:
    transport = RaisingTransport()
    _execute(transport=transport, s3_client=CountingS3Client())
    assert transport.requests == 1


def test_a_transport_failure_writes_nothing() -> None:
    s3 = CountingS3Client()
    _execute(transport=RaisingTransport(), s3_client=s3)
    assert s3.put_calls == []


def test_the_clock_is_read_by_the_runtime_not_by_the_composition() -> None:
    """One read per request, for the retrieval instant. No ambient clock exists."""
    clock = FixedClock(datetime(2026, 8, 30, 12, 0, tzinfo=UTC))
    _execute(transport=CountingTransport(), s3_client=CountingS3Client(), clock=clock)
    assert clock.reads >= 1


def test_the_payload_is_published_byte_for_byte() -> None:
    """Identity of the bytes, asserted without decoding them."""
    marker = b"\x00\x01synthetic-opaque-bytes\xff"
    s3 = CountingS3Client()
    stored: list[bytes] = []
    original = s3.put_object

    def capture(**kwargs: Any) -> dict[str, Any]:
        stored.append(bytes(kwargs["Body"]))
        return original(**kwargs)

    s3.put_object = capture  # type: ignore[method-assign]
    _execute(transport=CountingTransport(marker), s3_client=s3)
    assert marker in stored


def test_the_result_records_the_qualification_acquisition_mode() -> None:
    result = _execute(transport=CountingTransport(), s3_client=CountingS3Client())
    assert result.outcome.name == "COMPLETED"
    assert result.planned_requests == 1


def test_the_acquisition_mode_recorded_is_qualification() -> None:
    s3 = CountingS3Client()
    bodies: list[bytes] = []
    original = s3.put_object

    def capture(**kwargs: Any) -> dict[str, Any]:
        bodies.append(bytes(kwargs["Body"]))
        return original(**kwargs)

    s3.put_object = capture  # type: ignore[method-assign]
    _execute(transport=CountingTransport(), s3_client=s3)
    recorded = b"".join(bodies)
    assert AcquisitionMode.QUALIFICATION.value.encode() in recorded
    assert AcquisitionMode.BACKFILL.value.encode() not in recorded


def test_an_empty_provider_response_completes_and_asks_nothing_further() -> None:
    """Zero rows is an answer. It must not become a second request."""
    transport = CountingTransport(b"")
    result = _execute(transport=transport, s3_client=CountingS3Client())
    assert transport.requests == 1
    assert result.outcome.name == "COMPLETED"


def test_a_refused_plan_reaches_neither_provider_nor_store() -> None:
    transport = CountingTransport()
    s3 = CountingS3Client()
    with pytest.raises(QualificationRuntimeError):
        _execute(transport=transport, s3_client=s3, plan=object())  # type: ignore[arg-type]
    assert (transport.requests, s3.put_calls) == (0, [])


def test_a_non_pacer_is_refused_before_anything_is_constructed() -> None:
    transport = CountingTransport()
    with pytest.raises(SharadarRequestError):
        execute_qualification_acquisition(
            credential=_credential(),
            transport=transport,
            pacer=object(),  # type: ignore[arg-type]
            retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=()),
            timeout_seconds=30.0,
            s3_client=CountingS3Client(),
            licensed_bucket=SYNTHETIC_BUCKET,
            clock=FixedClock(datetime(2026, 8, 30, tzinfo=UTC)),
            plan=_plan(),
        )
    assert transport.requests == 0


def test_no_credential_or_bucket_appears_in_a_refusal() -> None:
    try:
        execute_qualification_acquisition(
            credential=_credential(),
            transport=CountingTransport(),
            pacer=object(),  # type: ignore[arg-type]
            retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=()),
            timeout_seconds=30.0,
            s3_client=CountingS3Client(),
            licensed_bucket=SYNTHETIC_BUCKET,
            clock=FixedClock(datetime(2026, 8, 30, tzinfo=UTC)),
            plan=_plan(),
        )
    except SharadarRequestError as refusal:
        text = f"{refusal!r} {refusal}"
        assert SYNTHETIC_KEY not in text
        assert SYNTHETIC_BUCKET not in text
    else:  # pragma: no cover - the call above always refuses
        pytest.fail("a non-Pacer must be refused")


# ---------------------------------------------------------------------------
# Structural: the root composes, and decides nothing
# ---------------------------------------------------------------------------


def _source() -> str:
    return COMPOSITION.read_text(encoding="utf-8")


def _tree() -> ast.Module:
    return ast.parse(_source())


def _executable_source() -> str:
    """The module's source with every docstring removed.

    A docstring may legitimately discuss ``CONTROL``, a parser or a retry while
    explaining why none exists. Scanning raw text would report the explanation as
    the defect, which trains the next person to delete the explanation.
    """
    tree = _tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_the_module_defines_exactly_two_public_operations() -> None:
    functions = [
        node.name
        for node in _tree().body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    assert [name for name in functions if not name.startswith("_")] == [
        "preflight_qualification_composition",
        "execute_qualification_acquisition",
    ]


def test_the_acquisition_function_calls_execute_exactly_once() -> None:
    tree = _tree()
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "execute_qualification_acquisition"
    )
    calls = [
        node.func.attr
        for node in ast.walk(target)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert calls.count("execute") == 1


def test_the_acquisition_function_contains_no_loop_and_no_retry() -> None:
    tree = _tree()
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "execute_qualification_acquisition"
    )
    loops = [node for node in ast.walk(target) if isinstance(node, ast.For | ast.While)]
    assert loops == []


def test_the_module_introduces_no_parser() -> None:
    source = _executable_source()
    for forbidden in ("csv", "DictReader", "decode(", "json.loads", "splitlines"):
        assert forbidden not in source


def test_the_module_names_no_control_classification() -> None:
    assert "CONTROL" not in _executable_source()


def test_the_module_constructs_exactly_one_store_per_operation() -> None:
    source = _executable_source()
    assert source.count("S3ResearchObjectStore(") == 2


def test_the_module_still_constructs_no_sdk_client() -> None:
    source = _executable_source()
    for forbidden in ("boto3", "botocore", "Session(", "client("):
        assert forbidden not in source


def test_the_module_has_no_entry_point_cli_or_environment_read() -> None:
    source = _executable_source()
    for forbidden in ('__name__ == "__main__"', "argparse", "sys.argv", "os.environ", "open("):
        assert forbidden not in source


def test_the_module_writes_no_file_and_names_no_runtime_directory() -> None:
    source = _executable_source()
    for forbidden in (".runtime/", "write_text", "write_bytes", "mkdir", "tempfile"):
        assert forbidden not in source


def test_the_acquisition_function_takes_every_dependency_by_injection() -> None:
    tree = _tree()
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "execute_qualification_acquisition"
    )
    assert target.args.args == []
    assert [arg.arg for arg in target.args.kwonlyargs] == [
        "credential",
        "transport",
        "pacer",
        "retry_policy",
        "timeout_seconds",
        "s3_client",
        "licensed_bucket",
        "clock",
        "plan",
    ]
    assert all(default is None for default in target.args.kw_defaults)


def test_the_module_exports_both_operations_and_no_capability() -> None:
    import kalpamani.data.ingest.sharadar.composition as module

    assert "execute_qualification_acquisition" in module.__all__
    assert "preflight_qualification_composition" in module.__all__


def test_no_second_composition_module_exists() -> None:
    package = COMPOSITION.parent
    constructors = [
        path.name
        for path in sorted(package.glob("*.py"))
        if "S3ResearchObjectStore(" in path.read_text(encoding="utf-8")
    ]
    assert constructors == ["composition.py"]


def test_the_module_docstring_no_longer_claims_no_execution_surface() -> None:
    """The dormancy claim ADR-0017 made false is corrected, not left standing."""
    doc = ast.get_docstring(_tree()) or ""
    assert "qualification-run execution surface     NONE" not in doc
    assert re.search(r"execution surface\s+ONE", doc) is not None
