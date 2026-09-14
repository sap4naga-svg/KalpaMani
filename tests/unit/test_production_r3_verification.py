"""R-3 -- the accepted procedure on a counting fake bucket, and the tool over it.

The fake models a bucket whose policy is in force (the accepted expected path) and lets a
test switch any statement off, time out, throttle, refuse authentication or answer
ambiguously; every operation is counted, every key it touched is remembered, and no test
here constructs a client or opens a socket. **Mocked results are not AWS verification.**
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_runtime import CANARIES, FakeClock
from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar import r3_verification as r3
from kalpamani.data.qualify.sharadar import runtime_binding as rb

pytestmark = pytest.mark.unit

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
SCRIPT: Final = REPO_ROOT / "scripts" / "production_r3_verification.py"
NOW: Final = datetime(2026, 9, 14, 18, 0, tzinfo=UTC)
ACCOUNT: Final = "111111111111"
BUCKET: Final = "synthetic-licensed-bucket"
ENVELOPE: Final = "ab" * 32

RESOURCE_DENY: Final = (
    "User: arn:aws:sts::111111111111:assumed-role/synthetic/session is not authorized to "
    "perform: s3:PutObject on resource: ... with an explicit deny in a resource-based policy"
)


def _module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tool = _module("production_r3_verification", SCRIPT)


class FakeBucket:
    """A bucket under the accepted policy, with switches for every deviation."""

    def __init__(self, **switches: Any) -> None:
        self.objects: dict[str, bytes] = {}
        self.uploads: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []
        self.switches = switches

    def _deviation(self, name: str) -> r3.Observation | None:
        value = self.switches.get(name)
        if value is None:
            return None
        if callable(value):
            answer: r3.Observation = value(self)
            return answer
        return value  # type: ignore[no-any-return]

    def put_object(self, key: str, body: bytes, *, if_none_match: bool) -> r3.Observation:
        self.calls.append(("put_object", key))
        switch = self._deviation("put_conditional" if if_none_match else "put_unconditional")
        if switch is not None:
            if switch.status == 200:
                self.objects[key] = body
            return switch
        if if_none_match:
            if key in self.objects:
                return r3.Observation(status=412, code="PreconditionFailed")
            self.objects[key] = body
            return r3.Observation(status=200)
        return r3.Observation(status=403, code="AccessDenied", message=RESOURCE_DENY)

    def head_object(self, key: str) -> r3.Observation:
        self.calls.append(("head_object", key))
        switch = self._deviation("head")
        if switch is not None:
            return switch
        if key in self.objects:
            return r3.Observation(status=200)
        return r3.Observation(status=404, code="404", message="Not Found")

    def copy_object(self, source_key: str, key: str, *, if_none_match: bool) -> r3.Observation:
        self.calls.append(("copy_object", key))
        switch = self._deviation("copy_conditional" if if_none_match else "copy_unconditional")
        if switch is not None:
            if switch.status == 200:
                self.objects[key] = self.objects.get(source_key, b"")
            return switch
        if if_none_match:
            return r3.Observation(status=501, code="NotImplemented")
        return r3.Observation(status=403, code="AccessDenied", message=RESOURCE_DENY)

    def create_multipart_upload(self, key: str) -> r3.Observation:
        self.calls.append(("create_multipart_upload", key))
        switch = self._deviation("multipart")
        if switch is not None:
            if switch.status == 200 and switch.upload_id is not None:
                self.uploads[switch.upload_id] = key
            return switch
        return r3.Observation(status=403, code="AccessDenied", message=RESOURCE_DENY)

    def delete_object(self, key: str) -> r3.Observation:
        self.calls.append(("delete_object", key))
        switch = self._deviation("delete")
        if switch is not None:
            return switch
        self.objects.pop(key, None)
        return r3.Observation(status=204)

    def abort_multipart_upload(self, key: str, upload_id: str) -> r3.Observation:
        self.calls.append(("abort_multipart_upload", key))
        switch = self._deviation("abort")
        if switch is not None:
            return switch
        self.uploads.pop(upload_id, None)
        return r3.Observation(status=204)

    def list_parts(self, key: str, upload_id: str) -> r3.Observation:
        self.calls.append(("list_parts", key))
        if upload_id in self.uploads:
            return r3.Observation(status=200)
        return r3.Observation(status=404, code="NoSuchUpload")


BINDING: Final = r3.R3Binding(
    environment_binding_sha256=ENVELOPE,
    policy_declaration_sha256="cd" * 32,
    partition="aws",
    region="us-east-1",
)


def _run(bucket: FakeBucket, **kw: Any) -> r3.R3Record:
    clock = FakeClock()
    return r3.run_r3(bucket, binding=BINDING, now=clock.now, stamp="20260914T180000Z-abcd", **kw)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("observation", "expected"),
    [
        (r3.Observation(status=200), r3.ObservedClass.OK_200),
        (r3.Observation(status=204), r3.ObservedClass.OK_204),
        (r3.Observation(status=404, code="404"), r3.ObservedClass.NOT_FOUND_404),
        (r3.Observation(status=404, code="NoSuchKey"), r3.ObservedClass.NOT_FOUND_404),
        (
            r3.Observation(status=403, code="AccessDenied", message=RESOURCE_DENY),
            r3.ObservedClass.DENIED_RESOURCE_POLICY,
        ),
        (
            r3.Observation(
                status=403, code="AccessDenied", message="... identity-based policy ..."
            ),
            r3.ObservedClass.DENIED_IDENTITY_POLICY,
        ),
        (r3.Observation(status=403, code="AccessDenied"), r3.ObservedClass.DENIED_OTHER),
        (r3.Observation(status=501, code="NotImplemented"), r3.ObservedClass.NOT_IMPLEMENTED_501),
        (r3.Observation(status=403, code="ExpiredToken"), r3.ObservedClass.AUTHENTICATION_FAILURE),
        (
            r3.Observation(status=None, code="NoCredentialsError"),
            r3.ObservedClass.AUTHENTICATION_FAILURE,
        ),
        (r3.Observation(status=404, code="NoSuchBucket"), r3.ObservedClass.NO_SUCH_BUCKET),
        (r3.Observation(status=503, code="SlowDown"), r3.ObservedClass.THROTTLED),
        (r3.Observation(status=None, transport_failure="timeout"), r3.ObservedClass.TIMEOUT),
        (
            r3.Observation(status=None, transport_failure="network"),
            r3.ObservedClass.NETWORK_FAILURE,
        ),
        (r3.Observation(status=None, code="Exception"), r3.ObservedClass.AMBIGUOUS),
        (r3.Observation(status=412, code="PreconditionFailed"), r3.ObservedClass.AMBIGUOUS),
        (r3.Observation(status=404, code="NoSuchUpload"), r3.ObservedClass.NO_SUCH_UPLOAD),
    ],
)
def test_every_answer_is_classified_and_the_message_is_dropped(
    observation: r3.Observation, expected: r3.ObservedClass
) -> None:
    assert r3.classify(observation) is expected
    assert "assumed-role" not in repr(observation)


# ---------------------------------------------------------------------------
# The expected path
# ---------------------------------------------------------------------------


def test_the_expected_path_is_the_accepted_table() -> None:
    assert [row.number for row in r3.EXPECTED_PATH] == list(range(1, 10))
    assert [row.operation for row in r3.EXPECTED_PATH] == [
        r3.R3Operation.PUT_CONDITIONAL,
        r3.R3Operation.PUT_UNCONDITIONAL,
        r3.R3Operation.HEAD,
        r3.R3Operation.COPY_UNCONDITIONAL,
        r3.R3Operation.COPY_CONDITIONAL,
        r3.R3Operation.CREATE_MULTIPART,
        r3.R3Operation.HEAD,
        r3.R3Operation.DELETE,
        r3.R3Operation.HEAD,
    ]
    assert r3.EXPECTED_PATH[4].expected == (
        r3.ObservedClass.NOT_IMPLEMENTED_501,
        r3.ObservedClass.DENIED_RESOURCE_POLICY,
    )
    assert len(r3.SYNTHETIC_MARKER) == 64
    assert r3.EXPECTED_PATH_OPERATIONS == 9 and r3.FAILURE_PATH_BUDGET == 10
    assert r3.CONTROL_PROFILE == "kalpamani-foundation"


def test_a_bucket_under_the_policy_verifies_with_nine_operations_and_no_residue() -> None:
    bucket = FakeBucket()
    record = _run(bucket)
    assert record.result is r3.R3Result.VERIFIED
    assert record.expected_path_operations == 9 and record.failure_path_operations == 0
    assert len(bucket.calls) == 9 and record.cleanup == () and record.residue == ()
    assert all(row.matched for row in record.rows)
    assert bucket.objects == {} and bucket.uploads == {}
    prefix = "_verification/20260914T180000Z-abcd/"
    assert all(key.startswith(prefix) for _op, key in bucket.calls)
    assert record.document()["verification_prefix"] == prefix
    # The record round-trips, its digest is stable, and it carries no private value.
    parsed = r3.parse_r3_record(canonical_bytes(record.document()))
    assert parsed == record and parsed.digest == record.digest
    text = json.dumps(record.document())
    for canary in (*CANARIES, BUCKET, ACCOUNT, "assumed-role"):
        assert canary not in text


def test_a_copy_refused_with_a_resource_deny_instead_of_501_still_verifies() -> None:
    bucket = FakeBucket(
        copy_conditional=r3.Observation(status=403, code="AccessDenied", message=RESOURCE_DENY)
    )
    assert _run(bucket).result is r3.R3Result.VERIFIED


@pytest.mark.parametrize(
    ("switch", "halted_row", "observed"),
    [
        (
            {"put_unconditional": r3.Observation(status=403, code="AccessDenied")},
            2,
            r3.ObservedClass.DENIED_OTHER,
        ),
        (
            {
                "put_unconditional": r3.Observation(
                    status=403, code="AccessDenied", message="identity-based policy"
                )
            },
            2,
            r3.ObservedClass.DENIED_IDENTITY_POLICY,
        ),
        (
            {"put_conditional": r3.Observation(status=403, code="ExpiredToken")},
            1,
            r3.ObservedClass.AUTHENTICATION_FAILURE,
        ),
        (
            {"put_conditional": r3.Observation(status=404, code="NoSuchBucket")},
            1,
            r3.ObservedClass.NO_SUCH_BUCKET,
        ),
        (
            {"put_unconditional": r3.Observation(status=503, code="SlowDown")},
            2,
            r3.ObservedClass.THROTTLED,
        ),
        (
            {"multipart": r3.Observation(status=403, code="AccessDenied")},
            6,
            r3.ObservedClass.DENIED_OTHER,
        ),
    ],
)
def test_a_denial_without_the_resource_context_or_any_other_class_halts_and_does_not_verify(
    switch: dict[str, Any], halted_row: int, observed: r3.ObservedClass
) -> None:
    bucket = FakeBucket(**switch)
    record = _run(bucket)
    assert record.result is not r3.R3Result.VERIFIED
    assert record.rows[halted_row - 1].observed is observed
    assert not record.rows[halted_row - 1].matched
    assert all(row.observed is r3.ObservedClass.NOT_EXERCISED for row in record.rows[halted_row:])
    assert record.expected_path_operations == halted_row
    assert bucket.objects == {}  # every cleanup resolved: the prefix is empty again
    parsed = r3.parse_r3_record(canonical_bytes(record.document()))
    assert parsed.result is record.result


def test_a_200_on_the_unconditional_put_is_cleaned_up_and_not_verified() -> None:
    bucket = FakeBucket(put_unconditional=r3.Observation(status=200))
    record = _run(bucket)
    assert record.result is r3.R3Result.NOT_VERIFIED
    assert record.rows[1].observed is r3.ObservedClass.OK_200
    # Cleanup: the unconditional object, then the positive control (row 8 never ran).
    assert [c.key_suffix for c in record.cleanup] == ["unconditional", "positive"]
    assert all(c.resolved for c in record.cleanup)
    assert record.failure_path_operations == 4 and record.residue == ()
    assert bucket.objects == {}
    assert len(bucket.calls) == 2 + 4


def test_a_200_on_a_copy_is_cleaned_up_and_not_verified() -> None:
    bucket = FakeBucket(copy_unconditional=r3.Observation(status=200))
    record = _run(bucket)
    assert record.result is r3.R3Result.NOT_VERIFIED
    assert [c.key_suffix for c in record.cleanup] == ["copied", "positive"]
    assert bucket.objects == {} and record.failure_path_operations == 4


def test_a_multipart_creation_that_succeeds_is_aborted_and_confirmed() -> None:
    bucket = FakeBucket(multipart=r3.Observation(status=200, upload_id="synthetic-upload"))
    record = _run(bucket)
    assert record.result is r3.R3Result.NOT_VERIFIED
    assert [c.operation for c in record.cleanup] == [
        r3.R3Operation.ABORT_MULTIPART,
        r3.R3Operation.DELETE,
    ]
    assert record.cleanup[0].confirmation is r3.ObservedClass.NO_SUCH_UPLOAD
    assert bucket.uploads == {} and bucket.objects == {}
    assert record.failure_path_operations == 4


def test_an_abort_that_needs_repeating_is_repeated_at_most_once() -> None:
    attempts = {"n": 0}

    def flaky_abort(bucket: FakeBucket) -> r3.Observation:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return r3.Observation(status=204)  # answered, but the upload is still listed
        bucket.uploads.clear()
        return r3.Observation(status=204)

    bucket = FakeBucket(
        multipart=r3.Observation(status=200, upload_id="synthetic-upload"), abort=flaky_abort
    )
    record = _run(bucket)
    assert record.result is r3.R3Result.NOT_VERIFIED
    aborts = [c for c in record.cleanup if c.operation is r3.R3Operation.ABORT_MULTIPART]
    assert len(aborts) == 2 and not aborts[0].resolved and aborts[1].resolved
    assert record.failure_path_operations == 6


def test_unresolved_cleanup_names_the_residue_and_keeps_the_gate_closed() -> None:
    bucket = FakeBucket(
        put_unconditional=r3.Observation(status=200),
        delete=r3.Observation(status=403, code="AccessDenied"),
    )
    record = _run(bucket)
    assert record.result is r3.R3Result.NOT_VERIFIED_CLEANUP_UNRESOLVED
    assert record.residue == (
        "_verification/20260914T180000Z-abcd/unconditional",
        "_verification/20260914T180000Z-abcd/positive",
    )
    assert not any(c.resolved for c in record.cleanup)
    parsed = r3.parse_r3_record(canonical_bytes(record.document()))
    assert parsed.residue == record.residue


def test_a_multipart_creation_with_no_upload_id_is_unresolvable_residue() -> None:
    bucket = FakeBucket(multipart=r3.Observation(status=None, transport_failure="timeout"))
    record = _run(bucket)
    assert record.result is r3.R3Result.NOT_VERIFIED_CLEANUP_UNRESOLVED
    assert "_verification/20260914T180000Z-abcd/multipart" in record.residue
    assert record.rows[5].observed is r3.ObservedClass.TIMEOUT


def test_the_failure_path_budget_is_never_exceeded() -> None:
    bucket = FakeBucket(
        put_unconditional=r3.Observation(status=200),
        head=r3.Observation(status=200),  # every confirmation finds the object
    )
    record = _run(bucket)
    assert record.result is r3.R3Result.NOT_VERIFIED_CLEANUP_UNRESOLVED
    assert record.failure_path_operations <= r3.FAILURE_PATH_BUDGET
    assert len(bucket.calls) <= 9 + r3.FAILURE_PATH_BUDGET


def test_a_timed_out_row_halts_and_the_positive_control_is_removed() -> None:
    bucket = FakeBucket(copy_unconditional=r3.Observation(status=None, transport_failure="timeout"))
    record = _run(bucket)
    assert record.result is r3.R3Result.NOT_VERIFIED
    assert record.rows[3].observed is r3.ObservedClass.TIMEOUT
    assert [c.key_suffix for c in record.cleanup] == ["copied", "positive"]
    assert bucket.objects == {}


def test_a_failed_cleanup_row_eight_is_retried_once_through_the_failure_path() -> None:
    first = {"seen": False}

    def failing_delete(bucket: FakeBucket) -> r3.Observation:
        if not first["seen"]:
            first["seen"] = True
            return r3.Observation(status=None, transport_failure="timeout")
        bucket.objects.clear()
        return r3.Observation(status=204)

    bucket = FakeBucket(delete=failing_delete)
    record = _run(bucket)
    assert record.result is r3.R3Result.NOT_VERIFIED
    assert record.rows[7].observed is r3.ObservedClass.TIMEOUT
    assert [c.key_suffix for c in record.cleanup] == ["positive"] and record.cleanup[0].resolved


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


def test_a_not_exercised_record_has_no_operations() -> None:
    record = r3.not_exercised_record(binding=BINDING, now=NOW, stamp="20260914T180000Z-0000")
    assert record.result is r3.R3Result.NOT_EXERCISED
    assert record.expected_path_operations == 0
    assert r3.parse_r3_record(canonical_bytes(record.document())) == record
    assert not r3.record_attests(record, binding=BINDING)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.__setitem__("result", "VERIFIED"),  # over a deviating row
        lambda d: d["rows"][1].__setitem__("matched", True),
        lambda d: d["rows"].pop(),
        lambda d: d.__setitem__("cleanup", []),  # NOT_VERIFIED with nothing resolved
        lambda d: d.__setitem__("residue", ["elsewhere/key"]),
        lambda d: d.__setitem__("control_profile", "default"),
        lambda d: d.__setitem__("verification_prefix", "_verification/other/"),
        lambda d: d.__setitem__("expected_path_operations", 12),
        lambda d: d.__setitem__("failure_path_operations", 11),
        lambda d: d["binding"].__setitem__("policy_declaration_sha256", "xyz"),
        lambda d: d.__setitem__("extra", 1),
        lambda d: d.__setitem__("contract_id", "kalpamani-r3-verification-record/v2"),
        lambda d: d["rows"][0].__setitem__("operation", "DeleteObject"),
        lambda d: d.__setitem__("started_at", (NOW + timedelta(days=1)).isoformat()),
    ],
)
def test_a_record_that_contradicts_itself_or_the_table_is_refused(mutate: Any) -> None:
    record = _run(FakeBucket(put_unconditional=r3.Observation(status=200)))
    document = record.document()
    mutate(document)
    with pytest.raises(r3.R3RecordError):
        r3.parse_r3_record(canonical_bytes(document))


def test_a_verified_record_cannot_carry_cleanup_or_residue() -> None:
    document = _run(FakeBucket()).document()
    document["residue"] = ["_verification/20260914T180000Z-abcd/positive"]
    with pytest.raises(r3.R3RecordError):
        r3.parse_r3_record(canonical_bytes(document))


def test_old_evidence_attests_to_nothing_changed() -> None:
    record = _run(FakeBucket())
    assert r3.record_attests(record, binding=BINDING)
    changed_policy = r3.R3Binding(
        environment_binding_sha256=ENVELOPE,
        policy_declaration_sha256="ef" * 32,
        partition="aws",
        region="us-east-1",
    )
    other_bucket = r3.R3Binding(
        environment_binding_sha256="ba" * 32,
        policy_declaration_sha256="cd" * 32,
        partition="aws",
        region="us-east-1",
    )
    assert not r3.record_attests(record, binding=changed_policy)
    assert not r3.record_attests(record, binding=other_bucket)
    assert not r3.record_attests(
        _run(FakeBucket(put_unconditional=r3.Observation(status=200))), binding=BINDING
    )


# ---------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------


def _environment_binding(digest: str = ENVELOPE) -> rb.QualificationEnvironmentBinding:
    return rb.QualificationEnvironmentBinding(
        target_account_id=ACCOUNT,
        licensed_bucket_name=BUCKET,
        partition=rb.EXPECTED_PARTITION,
        region=rb.EXPECTED_REGION,
        digest=digest,
    )


class _Scenario:
    def __init__(self, tmp_path: Path, bucket: FakeBucket | None = None) -> None:
        self.bucket = FakeBucket() if bucket is None else bucket
        self.declaration = tmp_path / "storage.tf"
        self.declaration.write_text("synthetic declared statements\n", encoding="utf-8")
        self.records = tmp_path / "records"
        self.records.mkdir()
        self.constructions: list[tuple[str, str]] = []
        self.gate_calls = 0
        self.written: list[Path] = []
        self.clock = FakeClock()
        self.env = {
            "AWS_PROFILE": "kalpamani-foundation",
            rb.ENVIRONMENT_BINDING_ENV_VAR: str(tmp_path / "environment.json"),
            tool.RECORD_DIR_ENV_VAR: str(self.records),
        }

    def gate(self) -> str | None:
        self.gate_calls += 1
        return None

    def factory(self, bucket: str, region: str) -> Any:
        self.constructions.append((bucket, region))
        return self.bucket

    def write(self, name: str, payload: bytes) -> Path:
        path = self.records / name
        if path.exists():
            raise FileExistsError(name)
        path.write_bytes(payload)
        self.written.append(path)
        return path

    def fields(self, **overrides: Any) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "env": self.env,
            "modules": {},
            "identity_gate": self.gate,
            "expected_account": lambda: ACCOUNT,
            "load_environment_binding": lambda **_kw: _environment_binding(),
            "client_factory": self.factory,
            "write_record": self.write,
            "read_record": lambda path: Path(path).read_bytes(),
            "now": self.clock.now,
            "declaration_path": self.declaration,
        }
        fields.update(overrides)
        return fields

    def main(self, *argv: str, **overrides: Any) -> int:
        code: int = tool.main(list(argv), **self.fields(**overrides))
        return code


def test_the_default_invocation_prints_the_plan_and_performs_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _Scenario(tmp_path)
    assert scenario.main() == tool.EXIT_PLANNED
    out = capsys.readouterr().out
    assert "row=1 PutObject+IfNoneMatch positive expects=OK_200" in out
    assert "failure_path_budget=10" in out and tool.SENTENCES["planned"] in out
    assert scenario.constructions == [] and scenario.gate_calls == 0
    assert scenario.bucket.calls == [] and scenario.written == []


@pytest.mark.parametrize("flag", sorted(tool.REFUSED_OPTIONS))
def test_refused_options_are_refused_before_anything(tmp_path: Path, flag: str) -> None:
    scenario = _Scenario(tmp_path)
    assert scenario.main(flag) == tool.EXIT_REFUSED_ARGUMENTS
    assert scenario.main(tool.AUTHORIZATION_FLAG, "--check-record") == tool.EXIT_REFUSED_ARGUMENTS
    assert scenario.constructions == [] and scenario.gate_calls == 0


def test_an_authorized_session_verifies_and_writes_the_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _Scenario(tmp_path)
    assert scenario.main(tool.AUTHORIZATION_FLAG) == tool.EXIT_VERIFIED
    out = capsys.readouterr().out
    assert "r3_result=VERIFIED expected_path_operations=9 failure_path_operations=0" in out
    assert scenario.gate_calls == 1 and scenario.constructions == [(BUCKET, "us-east-1")]
    (written,) = scenario.written
    record = r3.parse_r3_record(written.read_bytes())
    assert record.result is r3.R3Result.VERIFIED
    assert f"r3_verification_digest={record.digest}" in out
    assert record.binding.policy_declaration_sha256 == sha256_hex(scenario.declaration.read_bytes())
    assert record.binding.environment_binding_sha256 == ENVELOPE
    for canary in (BUCKET, ACCOUNT, *CANARIES):
        assert canary not in out and canary not in written.read_text(encoding="utf-8")


def test_a_deviation_is_recorded_not_verified_and_no_digest_is_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _Scenario(tmp_path, FakeBucket(put_unconditional=r3.Observation(status=200)))
    assert scenario.main(tool.AUTHORIZATION_FLAG) == tool.EXIT_NOT_VERIFIED
    out = capsys.readouterr().out
    assert "r3_result=NOT_VERIFIED" in out and "r3_verification_digest" not in out
    assert len(scenario.written) == 1
    (tmp_path / "b").mkdir()
    scenario = _Scenario(
        tmp_path / "b",
        FakeBucket(
            put_unconditional=r3.Observation(status=200),
            delete=r3.Observation(status=403, code="AccessDenied"),
        ),
    )
    assert scenario.main(tool.AUTHORIZATION_FLAG) == tool.EXIT_CLEANUP_UNRESOLVED
    assert "residue_count=2" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("overrides", "exit_code"),
    [
        ({"modules": {"pytest": object()}}, tool.EXIT_REFUSED_EXECUTION_CONTEXT),
        ({"env": {"AWS_PROFILE": "default"}}, tool.EXIT_REFUSED_IDENTITY),
        (
            {"identity_gate": lambda: "the authenticated account does not match"},
            tool.EXIT_REFUSED_IDENTITY,
        ),
        (
            {"identity_gate": lambda: (_ for _ in ()).throw(RuntimeError("x"))},
            tool.EXIT_REFUSED_IDENTITY,
        ),
        ({"expected_account": lambda: None}, tool.EXIT_REFUSED_BINDING),
        ({"expected_account": lambda: "222222222222"}, tool.EXIT_REFUSED_BINDING),
        (
            {"load_environment_binding": lambda **_kw: (_ for _ in ()).throw(ValueError("x"))},
            tool.EXIT_REFUSED_BINDING,
        ),
        (
            {"declaration_path": Path("C:/synthetic/missing/storage.tf")},
            tool.EXIT_REFUSED_DECLARATION,
        ),
        (
            {"client_factory": lambda b, r: (_ for _ in ()).throw(RuntimeError("no sdk"))},
            tool.EXIT_REFUSED_DEPENDENCY,
        ),
    ],
)
def test_every_refusal_stops_before_any_s3_operation(
    tmp_path: Path, overrides: dict[str, Any], exit_code: int
) -> None:
    scenario = _Scenario(tmp_path)
    if "env" in overrides:
        overrides["env"] = {**scenario.env, **overrides["env"]}
    assert scenario.main(tool.AUTHORIZATION_FLAG, **overrides) == exit_code
    assert scenario.bucket.calls == [] and scenario.written == []


def test_a_record_that_cannot_be_written_is_a_refusal_after_the_session(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)

    def failing(name: str, payload: bytes) -> Path:
        raise OSError("no")

    assert (
        scenario.main(tool.AUTHORIZATION_FLAG, write_record=failing)
        == tool.EXIT_REFUSED_RECORD_WRITE
    )
    assert len(scenario.bucket.calls) == 9  # the session ran; the evidence was not kept


def test_check_record_reports_whether_old_evidence_still_attests(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _Scenario(tmp_path)
    assert scenario.main(tool.AUTHORIZATION_FLAG) == tool.EXIT_VERIFIED
    (written,) = scenario.written
    scenario.env[tool.RECORD_FILE_ENV_VAR] = str(written)
    capsys.readouterr()
    assert scenario.main("--check-record") == tool.EXIT_CHECKED
    out = capsys.readouterr().out
    assert "r3_record_result=VERIFIED attests_current_declaration=True" in out
    # The declaration changed: the record no longer attests.
    scenario.declaration.write_text("changed statements\n", encoding="utf-8")
    assert scenario.main("--check-record") == tool.EXIT_CHECKED
    assert "attests_current_declaration=False" in capsys.readouterr().out
    # Another environment binding: the same.
    scenario.declaration.write_text("synthetic declared statements\n", encoding="utf-8")
    assert (
        scenario.main(
            "--check-record", load_environment_binding=lambda **_kw: _environment_binding("ba" * 32)
        )
        == tool.EXIT_CHECKED
    )
    assert "attests_current_declaration=False" in capsys.readouterr().out
    # A record that does not parse refuses.
    written.write_bytes(b"{}")
    assert scenario.main("--check-record") == tool.EXIT_CHECK_REFUSED
    assert scenario.constructions == [(BUCKET, "us-east-1")]  # only the one session built a client


class TestRowNineConfirmation:
    """PR #105 review finding 4: row 8's 204 acknowledges the delete; row 9 confirms absence."""

    @staticmethod
    def _bucket(
        row_nine: r3.Observation, *, later_head: r3.Observation | None = None
    ) -> FakeBucket:
        """A bucket whose ninth expected-path call answers ``row_nine`` and whose later
        cleanup confirmations answer ``later_head`` (default: the object is gone)."""

        def head(bucket: FakeBucket) -> r3.Observation:
            heads = [c for c in bucket.calls if c[0] == "head_object"]
            if len(heads) == 3 and len(bucket.calls) == 9:
                return row_nine
            if len(bucket.calls) > 9 and later_head is not None:
                return later_head
            return r3.Observation(status=404, code="404")

        return FakeBucket(head=head)

    @pytest.mark.parametrize(
        ("row_nine", "observed"),
        [
            (r3.Observation(status=200), r3.ObservedClass.OK_200),
            (r3.Observation(status=None, transport_failure="timeout"), r3.ObservedClass.TIMEOUT),
            (r3.Observation(status=403, code="AccessDenied"), r3.ObservedClass.DENIED_OTHER),
            (
                r3.Observation(status=None, transport_failure="network"),
                r3.ObservedClass.NETWORK_FAILURE,
            ),
        ],
    )
    def test_an_unconfirmed_absence_is_cleaned_up_and_the_row_stays_failed(
        self, row_nine: r3.Observation, observed: r3.ObservedClass
    ) -> None:
        bucket = self._bucket(row_nine)
        record = _run(bucket)
        assert record.rows[7].observed is r3.ObservedClass.OK_204
        assert record.rows[8].observed is observed and not record.rows[8].matched
        # Cleanup: one more delete and a confirmation, within the budget.
        assert [c.key_suffix for c in record.cleanup] == ["positive"]
        assert record.cleanup[0].resolved and record.failure_path_operations == 2
        assert record.residue == ()
        # The failed row stays failed: cleanup restores the bucket, not the result.
        assert record.result is r3.R3Result.NOT_VERIFIED
        assert r3.parse_r3_record(canonical_bytes(record.document())) == record
        assert len(bucket.calls) == 9 + 2

    def test_an_absence_that_stays_unconfirmed_is_residue(self) -> None:
        bucket = self._bucket(r3.Observation(status=200), later_head=r3.Observation(status=200))
        record = _run(bucket)
        assert record.result is r3.R3Result.NOT_VERIFIED_CLEANUP_UNRESOLVED
        assert record.residue == ("_verification/20260914T180000Z-abcd/positive",)
        assert record.failure_path_operations == 2
        assert r3.parse_r3_record(canonical_bytes(record.document())) == record
        # A refused cleanup delete is unresolved too.
        bucket = FakeBucket()
        state = {"n": 0}

        def head(b: FakeBucket) -> r3.Observation:
            state["n"] += 1
            return (
                r3.Observation(status=200)
                if state["n"] == 3
                else r3.Observation(status=404, code="404")
            )

        bucket.switches["head"] = head
        bucket.switches["delete"] = r3.Observation(status=403, code="AccessDenied")
        record = _run(bucket)
        assert record.rows[7].observed is r3.ObservedClass.DENIED_OTHER
        assert record.result is r3.R3Result.NOT_VERIFIED_CLEANUP_UNRESOLVED
        assert record.residue == ("_verification/20260914T180000Z-abcd/positive",)

    def test_a_confirmed_absence_verifies_and_needs_no_cleanup(self) -> None:
        record = _run(self._bucket(r3.Observation(status=404, code="404")))
        assert record.result is r3.R3Result.VERIFIED
        assert record.cleanup == () and record.failure_path_operations == 0

    def test_a_record_claiming_removal_from_row_eight_alone_is_refused(self) -> None:
        record = _run(self._bucket(r3.Observation(status=200)))
        document = record.document()
        document["cleanup"] = []
        document["result"] = "NOT_VERIFIED"
        with pytest.raises(r3.R3RecordError):
            r3.parse_r3_record(canonical_bytes(document))


class CountingTransport:
    """Replaces the botocore HTTP session: every ``send`` is one transport attempt.

    Answers with a scripted status and body, raises a scripted transport exception, and
    records every request's headers -- so the retry budget, the classification and the
    conditional-header injection are observed at the wire, not at a fake above it.
    """

    def __init__(self) -> None:
        self.sends = 0
        self.requests: list[Any] = []
        self.script: list[Any] = []

    def send(self, request: Any) -> Any:
        import io

        from botocore.awsrequest import AWSResponse  # type: ignore[import-untyped]

        self.sends += 1
        self.requests.append(request)
        answer = self.script.pop(0) if self.script else (200, b"")
        if isinstance(answer, BaseException):
            raise answer
        status, body = answer
        raw = io.BytesIO(body)
        raw.stream = lambda **_kw: iter([body])  # type: ignore[attr-defined]
        return AWSResponse(request.url, status, {"content-type": "application/xml"}, raw)


def _synthetic_session(region: str) -> Any:
    import boto3  # type: ignore[import-untyped]

    return boto3.Session(
        aws_access_key_id="SYNTHETIC00000000000",
        aws_secret_access_key="synthetic-secret-key-never-a-credential",  # noqa: S106
        region_name=region,
    )


def _error(code: str, message: str = "") -> bytes:
    return f"<Error><Code>{code}</Code><Message>{message}</Message></Error>".encode()


class TestBoto3Adapter:
    """PR #105 review finding 1: one total attempt, observed at the transport."""

    def _adapter(self, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, CountingTransport]:
        import boto3

        # No credential discovery: a session built from the workstation's profiles is refused.
        original = boto3.Session

        def refuse_profiles(*args: Any, **kwargs: Any) -> Any:
            if "profile_name" in kwargs:
                raise AssertionError("a test must never build a session from a profile")
            return original(*args, **kwargs)

        monkeypatch.setattr(boto3, "Session", refuse_profiles)
        adapter = tool._Boto3R3Client(BUCKET, "us-east-1", session_factory=_synthetic_session)
        transport = CountingTransport()
        adapter._client._endpoint.http_session = transport
        return adapter, transport

    def test_the_effective_retry_configuration_is_one_total_attempt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter, _transport = self._adapter(monkeypatch)
        retries = adapter._client.meta.config.retries
        assert retries["total_max_attempts"] == 1 and retries["mode"] == "standard"
        assert adapter._client.meta.config.connect_timeout == tool.CONNECT_TIMEOUT_SECONDS
        assert adapter._client.meta.config.read_timeout == tool.READ_TIMEOUT_SECONDS

    @pytest.mark.parametrize(
        ("script", "expected"),
        [
            ([(503, _error("SlowDown", "slow"))], r3.ObservedClass.THROTTLED),
            ([(500, _error("InternalError", "x"))], r3.ObservedClass.AMBIGUOUS),
            ([(403, _error("ExpiredToken", "expired"))], r3.ObservedClass.AUTHENTICATION_FAILURE),
            ([(404, _error("NoSuchBucket", "none"))], r3.ObservedClass.NO_SUCH_BUCKET),
            (
                [
                    (
                        403,
                        _error(
                            "AccessDenied", "... with an explicit deny in a resource-based policy"
                        ),
                    )
                ],
                r3.ObservedClass.DENIED_RESOURCE_POLICY,
            ),
            ([(403, _error("AccessDenied", "denied"))], r3.ObservedClass.DENIED_OTHER),
            ([(200, b"")], r3.ObservedClass.OK_200),
        ],
    )
    def test_every_service_answer_is_one_transport_attempt_and_one_class(
        self, monkeypatch: pytest.MonkeyPatch, script: list[Any], expected: r3.ObservedClass
    ) -> None:
        adapter, transport = self._adapter(monkeypatch)
        transport.script = list(script)
        observation = adapter.put_object("_verification/x/unconditional", b"x", if_none_match=False)
        assert r3.classify(observation) is expected
        assert transport.sends == 1  # a retryable answer is NOT retried
        assert "assumed-role" not in repr(observation)

    def test_transport_failures_are_one_attempt_and_classified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from botocore.exceptions import (  # type: ignore[import-untyped]
            ConnectTimeoutError,
            EndpointConnectionError,
            ReadTimeoutError,
        )

        adapter, transport = self._adapter(monkeypatch)
        for exception, expected in (
            (ReadTimeoutError(endpoint_url="https://synthetic"), r3.ObservedClass.TIMEOUT),
            (ConnectTimeoutError(endpoint_url="https://synthetic"), r3.ObservedClass.TIMEOUT),
            (
                EndpointConnectionError(endpoint_url="https://synthetic"),
                r3.ObservedClass.NETWORK_FAILURE,
            ),
        ):
            transport.sends = 0
            transport.script = [exception]
            observation = adapter.head_object("_verification/x/positive")
            assert r3.classify(observation) is expected
            assert transport.sends == 1

    def test_head_and_delete_answers_classify_as_the_table_expects(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter, transport = self._adapter(monkeypatch)
        transport.script = [(404, b"")]
        assert r3.classify(adapter.head_object("_verification/x/copied")) is (
            r3.ObservedClass.NOT_FOUND_404
        )
        transport.script = [(204, b"")]
        assert r3.classify(adapter.delete_object("_verification/x/positive")) is (
            r3.ObservedClass.OK_204
        )
        transport.script = [(501, _error("NotImplemented", "x"))]
        assert (
            r3.classify(
                adapter.copy_object(
                    "_verification/x/positive", "_verification/x/copied", if_none_match=True
                )
            )
            is r3.ObservedClass.NOT_IMPLEMENTED_501
        )
        transport.script = [
            (
                200,
                b"<InitiateMultipartUploadResult><UploadId>synthetic-upload</UploadId></InitiateMultipartUploadResult>",
            )
        ]
        multipart = adapter.create_multipart_upload("_verification/x/multipart")
        assert r3.classify(multipart) is r3.ObservedClass.OK_200
        assert multipart.upload_id == "synthetic-upload"
        transport.script = [(404, _error("NoSuchUpload", "gone"))]
        assert r3.classify(adapter.list_parts("_verification/x/multipart", "synthetic-upload")) is (
            r3.ObservedClass.NO_SUCH_UPLOAD
        )

    def test_the_conditional_copy_header_is_injected_for_that_call_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter, transport = self._adapter(monkeypatch)
        transport.script = [(403, _error("AccessDenied", "x"))] * 3
        adapter.copy_object(
            "_verification/x/positive", "_verification/x/copied", if_none_match=False
        )
        adapter.copy_object(
            "_verification/x/positive", "_verification/x/copied", if_none_match=True
        )
        adapter.copy_object(
            "_verification/x/positive", "_verification/x/copied", if_none_match=False
        )
        headers = [
            {k.lower(): v for k, v in request.headers.items()} for request in transport.requests
        ]
        assert "if-none-match" not in headers[0]
        assert headers[1]["if-none-match"] in ("*", b"*")
        assert "if-none-match" not in headers[2]
        assert "x-amz-copy-source" in headers[1]
        assert transport.sends == 3
        # The conditional put carries the header through the SDK's own parameter.
        transport.script = [(200, b"")]
        adapter.put_object("_verification/x/positive", b"x", if_none_match=True)
        assert {k.lower(): v for k, v in transport.requests[-1].headers.items()}[
            "if-none-match"
        ] in ("*", b"*")

    def test_the_procedure_over_the_adapter_counts_nine_transport_attempts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter, transport = self._adapter(monkeypatch)
        deny = (403, _error("AccessDenied", "explicit deny in a resource-based policy"))
        transport.script = [
            (200, b""),
            deny,
            (404, b""),
            deny,
            (501, _error("NotImplemented", "x")),
            deny,
            (404, b""),
            (204, b""),
            (404, b""),
        ]
        record = r3.run_r3(adapter, binding=BINDING, now=lambda: NOW, stamp="20260914T180000Z-abcd")
        assert record.result is r3.R3Result.VERIFIED
        assert transport.sends == 9 and record.expected_path_operations == 9
        assert all(
            request.url.startswith("https://")
            and "_verification/20260914T180000Z-abcd/" in request.url
            for request in transport.requests
        )


def test_the_sdk_is_named_only_inside_the_client_class() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.count("import boto3") == 1
    assert "profile_name=r3.CONTROL_PROFILE" in source
    assert '"total_max_attempts": 1' in source and '"max_attempts": 1' not in source
    assert "--skip-cleanup" in tool.REFUSED_OPTIONS and "--retry" in tool.REFUSED_OPTIONS
