"""R-3 -- server-side conditional-write verification, executed on an injected client.

**ADR-0036 §2.7 / §3 (the R-3 procedure), ADR-0046 (the record).** The
procedure is transcribed from the accepted text and nothing is added to it: one
identity proof first (the tool's, not this module's), then **nine expected-path S3
operations** under ``_verification/<stamp>/`` with a fixed 64-byte synthetic marker, each
counted and each held to the class of response the accepted table names; on any
deviation the expected path **halts**, the failure-path cleanup of the accepted table
runs under a budget of **at most ten** further operations, and the result is computed
**after** cleanup. Every row is recorded by the **classification** of what S3 answered --
never the message text, which names the caller ARN.

Rows are verified by *class*, and the classes are what distinguishes an expected denial
from everything that is not one: a ``403`` carrying the documented *explicit deny in a
resource-based policy* context is the expected refusal; a ``403`` with an identity-based
context, a ``403`` with no context, an authentication failure, a missing bucket, a
throttle, a timeout or anything unrecognised is a different class and fails the row. **A
row that does not match halts the path; a row not reached is NOT_EXERCISED; nothing
here can pass with an incomplete or contradictory observation.**

**Old evidence attests to nothing newer.** The record binds the digest of the declared
bucket-policy statements (the tracked ``storage.tf`` bytes the tool ran beside), the
digest of the environment binding that named the bucket, the partition and region, and
the stamp; a later declaration change, or another bucket, produces a record whose
bindings differ, and readiness §4.6's rule that a changed policy needs fresh evidence is
checked against these fields rather than remembered.

**Nothing here constructs a client, mutates a policy, moves a stage or changes an
assignment.** The client is injected; the tool builds a real one only inside its
authorized branch, and every test uses a counting fake.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Protocol

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar.documents import decode_document, exact_str, instant

R3_RECORD_CONTRACT_ID: Final = "kalpamani-r3-verification-record/v1"
R3_RECORD_SCHEMA_VERSION: Final = 1
MAX_R3_RECORD_BYTES: Final = 64 * 1024

#: The verification prefix ADR-0036 §3 dedicates to R-3 -- the physical key prefix in
#: the licensed bucket, inside the bucket-policy scope and the deletion runbook's list.
VERIFICATION_PREFIX: Final = "_verification"
#: The fixed synthetic marker every R-3 object carries. Never a vendor row.
SYNTHETIC_MARKER: Final = b"kalpamani-r3-synthetic-marker-" + b"0" * 34
assert len(SYNTHETIC_MARKER) == 64
#: The accepted operation ceilings.
EXPECTED_PATH_OPERATIONS: Final = 9
FAILURE_PATH_BUDGET: Final = 10
#: The control principal's profile: the foundation's Terraform-apply profile.
CONTROL_PROFILE: Final = "kalpamani-foundation"

#: The documented enhanced access-denied context fragments (S3 access-denied
#: troubleshooting). Only their presence is classified; the message is never kept.
_RESOURCE_POLICY_CONTEXT: Final = "explicit deny in a resource-based policy"
_IDENTITY_POLICY_CONTEXT: Final = "identity-based policy"

_AUTHENTICATION_CODES: Final[frozenset[str]] = frozenset(
    {
        "InvalidAccessKeyId",
        "ExpiredToken",
        "ExpiredTokenException",
        "TokenRefreshRequired",
        "SignatureDoesNotMatch",
        "InvalidToken",
        "AuthorizationHeaderMalformed",
        "CredentialsNotFound",
        "NoCredentialsError",
    }
)
_THROTTLE_CODES: Final[frozenset[str]] = frozenset(
    {"SlowDown", "Throttling", "ThrottlingException", "RequestLimitExceeded", "503"}
)


class R3Operation(StrEnum):
    """The S3 operations R-3 issues. Closed; nothing else is reachable."""

    PUT_CONDITIONAL = "PutObject+IfNoneMatch"
    PUT_UNCONDITIONAL = "PutObject"
    HEAD = "HeadObject"
    COPY_UNCONDITIONAL = "CopyObject"
    COPY_CONDITIONAL = "CopyObject+IfNoneMatch"
    CREATE_MULTIPART = "CreateMultipartUpload"
    DELETE = "DeleteObject"
    ABORT_MULTIPART = "AbortMultipartUpload"
    LIST_PARTS = "ListParts"


class ObservedClass(StrEnum):
    """What S3 answered, classified. **The only thing a record carries about a response.**"""

    OK_200 = "OK_200"
    OK_204 = "OK_204"
    NOT_FOUND_404 = "NOT_FOUND_404"
    NO_SUCH_UPLOAD = "NO_SUCH_UPLOAD"
    DENIED_RESOURCE_POLICY = "DENIED_RESOURCE_POLICY"
    DENIED_IDENTITY_POLICY = "DENIED_IDENTITY_POLICY"
    DENIED_OTHER = "DENIED_OTHER"
    NOT_IMPLEMENTED_501 = "NOT_IMPLEMENTED_501"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    NO_SUCH_BUCKET = "NO_SUCH_BUCKET"
    THROTTLED = "THROTTLED"
    TIMEOUT = "TIMEOUT"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_EXERCISED = "NOT_EXERCISED"


class R3Result(StrEnum):
    """The closed verdict of one R-3 session. Computed after cleanup, never before."""

    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    NOT_VERIFIED_CLEANUP_UNRESOLVED = "NOT_VERIFIED_CLEANUP_UNRESOLVED"
    NOT_EXERCISED = "NOT_EXERCISED"


@dataclass(frozen=True, slots=True, kw_only=True)
class Observation:
    """One S3 answer as the adapter reports it. ``message`` is classified and dropped."""

    status: int | None
    code: str | None = None
    message: str | None = None
    upload_id: str | None = None
    #: ``"timeout"`` / ``"network"`` when the request never produced a response.
    transport_failure: str | None = None
    #: Every task ARN a ``RunTask`` or ``ListTasks`` answered with (the permission cells'
    #: unexpected-success reaction stops each; the cleanup settles each). Never rendered.
    task_arns: tuple[str, ...] = ()
    #: ``(task ARN, lastStatus)`` pairs a ``DescribeTasks`` answered with. Never rendered.
    task_statuses: tuple[tuple[str, str], ...] = ()
    #: The count of ``failures`` entries a ``RunTask`` answer carried beside its tasks.
    failures: int = 0

    @property
    def task_arn(self) -> str | None:
        """The first returned task ARN, when one was returned."""
        return self.task_arns[0] if self.task_arns else None

    def __repr__(self) -> str:
        """Status and code only -- never the message."""
        return f"Observation(status={self.status!r}, code={self.code!r})"


class R3Client(Protocol):
    """The nine operations, each answering with an :class:`Observation`. **Never raises.**"""

    def put_object(self, key: str, body: bytes, *, if_none_match: bool) -> Observation: ...
    def head_object(self, key: str) -> Observation: ...
    def copy_object(self, source_key: str, key: str, *, if_none_match: bool) -> Observation: ...
    def create_multipart_upload(self, key: str) -> Observation: ...
    def delete_object(self, key: str) -> Observation: ...
    def abort_multipart_upload(self, key: str, upload_id: str) -> Observation: ...
    def list_parts(self, key: str, upload_id: str) -> Observation: ...


def classify(observation: Observation) -> ObservedClass:
    """The class of one answer. The message is read for the documented context only."""
    if observation.transport_failure == "timeout":
        return ObservedClass.TIMEOUT
    if observation.transport_failure is not None:
        return ObservedClass.NETWORK_FAILURE
    code = observation.code or ""
    message = observation.message or ""
    status = observation.status
    if code in _AUTHENTICATION_CODES or status == 401:
        return ObservedClass.AUTHENTICATION_FAILURE
    if code == "NoSuchBucket":
        return ObservedClass.NO_SUCH_BUCKET
    if code == "NoSuchUpload":
        return ObservedClass.NO_SUCH_UPLOAD
    if code in _THROTTLE_CODES or status == 503:
        return ObservedClass.THROTTLED
    if status == 200:
        return ObservedClass.OK_200
    if status == 204:
        return ObservedClass.OK_204
    if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
        return ObservedClass.NOT_FOUND_404
    if status == 501 or code == "NotImplemented":
        return ObservedClass.NOT_IMPLEMENTED_501
    if status == 403 or code == "AccessDenied":
        if _RESOURCE_POLICY_CONTEXT in message:
            return ObservedClass.DENIED_RESOURCE_POLICY
        if _IDENTITY_POLICY_CONTEXT in message:
            return ObservedClass.DENIED_IDENTITY_POLICY
        return ObservedClass.DENIED_OTHER
    return ObservedClass.AMBIGUOUS


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpectedRow:
    """One accepted expected-path row: its operation, its key suffix, its admitted classes."""

    number: int
    operation: R3Operation
    key_suffix: str
    source_suffix: str | None
    expected: tuple[ObservedClass, ...]
    establishes: str


#: The accepted table, transcribed. Row 5 admits the documented ``501`` or a
#: resource-based ``403``; every other row admits exactly one class.
EXPECTED_PATH: Final[tuple[ExpectedRow, ...]] = (
    ExpectedRow(
        number=1,
        operation=R3Operation.PUT_CONDITIONAL,
        key_suffix="positive",
        source_suffix=None,
        expected=(ObservedClass.OK_200,),
        establishes="the principal is authorized and the path works (fresh positive control)",
    ),
    ExpectedRow(
        number=2,
        operation=R3Operation.PUT_UNCONDITIONAL,
        key_suffix="unconditional",
        source_suffix=None,
        expected=(ObservedClass.DENIED_RESOURCE_POLICY,),
        establishes="the bucket policy refuses object creation without If-None-Match",
    ),
    ExpectedRow(
        number=3,
        operation=R3Operation.HEAD,
        key_suffix="unconditional",
        source_suffix=None,
        expected=(ObservedClass.NOT_FOUND_404,),
        establishes="the refused put created nothing",
    ),
    ExpectedRow(
        number=4,
        operation=R3Operation.COPY_UNCONDITIONAL,
        key_suffix="copied",
        source_suffix="positive",
        expected=(ObservedClass.DENIED_RESOURCE_POLICY,),
        establishes="copy-shaped writes refused",
    ),
    ExpectedRow(
        number=5,
        operation=R3Operation.COPY_CONDITIONAL,
        key_suffix="copied",
        source_suffix="positive",
        expected=(ObservedClass.NOT_IMPLEMENTED_501, ObservedClass.DENIED_RESOURCE_POLICY),
        establishes="copy-shaped writes refused even when conditional",
    ),
    ExpectedRow(
        number=6,
        operation=R3Operation.CREATE_MULTIPART,
        key_suffix="multipart",
        source_suffix=None,
        expected=(ObservedClass.DENIED_RESOURCE_POLICY,),
        establishes="multipart creation refused (ObjectCreationOperation = false branch)",
    ),
    ExpectedRow(
        number=7,
        operation=R3Operation.HEAD,
        key_suffix="copied",
        source_suffix=None,
        expected=(ObservedClass.NOT_FOUND_404,),
        establishes="nothing was created by rows 4-5",
    ),
    ExpectedRow(
        number=8,
        operation=R3Operation.DELETE,
        key_suffix="positive",
        source_suffix=None,
        expected=(ObservedClass.OK_204,),
        establishes="synthetic-object cleanup by the control principal",
    ),
    ExpectedRow(
        number=9,
        operation=R3Operation.HEAD,
        key_suffix="positive",
        source_suffix=None,
        expected=(ObservedClass.NOT_FOUND_404,),
        establishes="cleanup confirmed; the verification prefix is empty again",
    ),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RowOutcome:
    """One expected-path row as observed."""

    number: int
    operation: R3Operation
    key_suffix: str
    expected: tuple[ObservedClass, ...]
    observed: ObservedClass
    matched: bool

    def document(self) -> dict[str, Any]:
        """The closed row block."""
        return {
            "row": self.number,
            "operation": self.operation.value,
            "key_suffix": self.key_suffix,
            "expected": [c.value for c in self.expected],
            "observed": self.observed.value,
            "matched": self.matched,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class CleanupOutcome:
    """One failure-path cleanup operation and its confirmation."""

    trigger: str
    operation: R3Operation
    key_suffix: str
    observed: ObservedClass
    confirmation: ObservedClass | None
    resolved: bool

    def document(self) -> dict[str, Any]:
        """The closed cleanup block."""
        return {
            "trigger": self.trigger,
            "operation": self.operation.value,
            "key_suffix": self.key_suffix,
            "observed": self.observed.value,
            "confirmation": None if self.confirmation is None else self.confirmation.value,
            "resolved": self.resolved,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class R3Binding:
    """What the record binds its evidence to. No bucket name, no account -- digests only."""

    environment_binding_sha256: str
    policy_declaration_sha256: str
    partition: str
    region: str


@dataclass(slots=True, kw_only=True)
class R3Session:
    """The counted state of one R-3 session as it runs."""

    stamp: str
    rows: list[RowOutcome] = field(default_factory=list)
    cleanup: list[CleanupOutcome] = field(default_factory=list)
    expected_path_operations: int = 0
    failure_path_operations: int = 0
    residue: list[str] = field(default_factory=list)
    budget_exhausted: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class R3Record:
    """The sanitized record: classifications and counts only. Its digest is the S5a value."""

    result: R3Result
    stamp: str
    control_profile: str
    binding: R3Binding
    rows: tuple[RowOutcome, ...]
    cleanup: tuple[CleanupOutcome, ...]
    expected_path_operations: int
    failure_path_operations: int
    residue: tuple[str, ...]
    budget_exhausted: bool
    started_at: datetime
    finished_at: datetime

    def document(self) -> dict[str, Any]:
        """The closed record document."""
        return {
            "schema_version": R3_RECORD_SCHEMA_VERSION,
            "contract_id": R3_RECORD_CONTRACT_ID,
            "result": self.result.value,
            "stamp": self.stamp,
            "verification_prefix": f"{VERIFICATION_PREFIX}/{self.stamp}/",
            "control_profile": self.control_profile,
            "binding": {
                "environment_binding_sha256": self.binding.environment_binding_sha256,
                "policy_declaration_sha256": self.binding.policy_declaration_sha256,
                "partition": self.binding.partition,
                "region": self.binding.region,
            },
            "rows": [row.document() for row in self.rows],
            "cleanup": [item.document() for item in self.cleanup],
            "expected_path_operations": self.expected_path_operations,
            "failure_path_operations": self.failure_path_operations,
            "residue": list(self.residue),
            "budget_exhausted": self.budget_exhausted,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
        }

    @property
    def digest(self) -> str:
        """SHA-256 of the canonical record: ``production_r3_verification_digest`` when VERIFIED."""
        return sha256_hex(canonical_bytes(self.document()))

    def __repr__(self) -> str:
        """Result only."""
        return f"R3Record(result={self.result.value!r})"


def new_stamp(now: datetime) -> str:
    """The session stamp: the instant plus four random hex digits. Carries no private value."""
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(2)}"


def verification_key(stamp: str, suffix: str) -> str:
    """The physical key of one R-3 object."""
    return f"{VERIFICATION_PREFIX}/{stamp}/{suffix}"


def _issue(client: R3Client, row: ExpectedRow, stamp: str) -> Observation:
    key = verification_key(stamp, row.key_suffix)
    if row.operation is R3Operation.PUT_CONDITIONAL:
        return client.put_object(key, SYNTHETIC_MARKER, if_none_match=True)
    if row.operation is R3Operation.PUT_UNCONDITIONAL:
        return client.put_object(key, SYNTHETIC_MARKER, if_none_match=False)
    if row.operation is R3Operation.HEAD:
        return client.head_object(key)
    if row.operation is R3Operation.COPY_UNCONDITIONAL:
        assert row.source_suffix is not None
        return client.copy_object(
            verification_key(stamp, row.source_suffix), key, if_none_match=False
        )
    if row.operation is R3Operation.COPY_CONDITIONAL:
        assert row.source_suffix is not None
        return client.copy_object(
            verification_key(stamp, row.source_suffix), key, if_none_match=True
        )
    if row.operation is R3Operation.CREATE_MULTIPART:
        return client.create_multipart_upload(key)
    if row.operation is R3Operation.DELETE:
        return client.delete_object(key)
    raise AssertionError("unreachable expected-path operation")  # pragma: no cover


#: Classes after which an object-creating request may have created something.
_MAY_HAVE_CREATED: Final[frozenset[ObservedClass]] = frozenset(
    {
        ObservedClass.OK_200,
        ObservedClass.TIMEOUT,
        ObservedClass.NETWORK_FAILURE,
        ObservedClass.AMBIGUOUS,
    }
)


def _cleanup_object(client: R3Client, session: R3Session, *, trigger: str, suffix: str) -> None:
    """DeleteObject then HeadObject → 404, within the budget; residue on any other answer."""
    key = verification_key(session.stamp, suffix)
    if session.failure_path_operations + 2 > FAILURE_PATH_BUDGET:
        session.budget_exhausted = True
        session.residue.append(key)
        return
    deleted = classify(client.delete_object(key))
    session.failure_path_operations += 1
    confirmed = classify(client.head_object(key))
    session.failure_path_operations += 1
    resolved = deleted in {ObservedClass.OK_204, ObservedClass.NOT_FOUND_404} and (
        confirmed is ObservedClass.NOT_FOUND_404
    )
    session.cleanup.append(
        CleanupOutcome(
            trigger=trigger,
            operation=R3Operation.DELETE,
            key_suffix=suffix,
            observed=deleted,
            confirmation=confirmed,
            resolved=resolved,
        )
    )
    if not resolved:
        session.residue.append(key)


def _cleanup_multipart(client: R3Client, session: R3Session, *, upload_id: str | None) -> None:
    """AbortMultipartUpload then ListParts → NoSuchUpload; at most one repeat."""
    key = verification_key(session.stamp, "multipart")
    if upload_id is None:
        # A creation that may have succeeded with no UploadId to abort: unresolvable here.
        session.residue.append(key)
        return
    for attempt in range(2):
        if session.failure_path_operations + 2 > FAILURE_PATH_BUDGET:
            session.budget_exhausted = True
            session.residue.append(key)
            return
        aborted = classify(client.abort_multipart_upload(key, upload_id))
        session.failure_path_operations += 1
        listed = classify(client.list_parts(key, upload_id))
        session.failure_path_operations += 1
        resolved = aborted in {ObservedClass.OK_204, ObservedClass.OK_200} and (
            listed is ObservedClass.NO_SUCH_UPLOAD
        )
        session.cleanup.append(
            CleanupOutcome(
                trigger="row 6 returned 200 with UploadId"
                if attempt == 0
                else "abort repeated once",
                operation=R3Operation.ABORT_MULTIPART,
                key_suffix="multipart",
                observed=aborted,
                confirmation=listed,
                resolved=resolved,
            )
        )
        if resolved:
            return
    session.residue.append(key)


def run_r3(
    client: R3Client,
    *,
    binding: R3Binding,
    now: Callable[[], datetime],
    stamp: str | None = None,
) -> R3Record:
    """Execute the accepted R-3 procedure on ``client`` and compute the record.

    The expected path runs in order and **halts at the first row that does not match**;
    rows not reached are ``NOT_EXERCISED``. After a halt, the failure-path cleanup of the
    accepted table runs for everything the halted path may have created -- an object
    from a ``200`` (or an answer that may have been a ``200``: a timeout, a network
    failure, an ambiguous answer) on rows 2, 4 or 5, an upload from row 6, and the
    positive control whenever row 9 did not confirm its absence (row 8's ``204``
    acknowledges the delete and establishes nothing about the object; a row 9 that finds
    it, times out, is refused or fails cannot confirm it) -- within the ten-operation
    budget. The result is ``VERIFIED`` only when all nine rows matched; ``NOT_VERIFIED``
    when a row deviated and every cleanup resolved; ``NOT_VERIFIED_CLEANUP_UNRESOLVED``
    when any cleanup did not resolve, was refused, could not be issued or exhausted the
    budget, with the residue named by its synthetic key.
    """
    started = now()
    session = R3Session(stamp=new_stamp(started) if stamp is None else stamp)
    halted_at: int | None = None
    positive_written = False
    # Row 8's 204 acknowledges the delete; only row 9's 404 confirms the absence. Cleanup
    # of the positive control is owed until the absence is confirmed.
    positive_confirmed_absent = False
    created: list[str] = []
    multipart_upload: str | None = None
    multipart_created = False
    for row in EXPECTED_PATH:
        observation = _issue(client, row, session.stamp)
        session.expected_path_operations += 1
        observed = classify(observation)
        matched = observed in row.expected
        session.rows.append(
            RowOutcome(
                number=row.number,
                operation=row.operation,
                key_suffix=row.key_suffix,
                expected=row.expected,
                observed=observed,
                matched=matched,
            )
        )
        if row.number == 1 and observed in _MAY_HAVE_CREATED:
            positive_written = True
        if row.number in {2, 4, 5} and observed in _MAY_HAVE_CREATED:
            created.append(row.key_suffix)
        if row.number == 6 and observed in _MAY_HAVE_CREATED:
            multipart_created = True
            multipart_upload = observation.upload_id
        if row.number == 9 and observed is ObservedClass.NOT_FOUND_404:
            positive_confirmed_absent = True
        if not matched:
            halted_at = row.number
            break
    for row in EXPECTED_PATH:
        if row.number > len(session.rows):
            session.rows.append(
                RowOutcome(
                    number=row.number,
                    operation=row.operation,
                    key_suffix=row.key_suffix,
                    expected=row.expected,
                    observed=ObservedClass.NOT_EXERCISED,
                    matched=False,
                )
            )
    if halted_at is not None:
        for suffix in dict.fromkeys(created):
            _cleanup_object(
                client,
                session,
                trigger=f"row {halted_at} halted; {suffix} may exist",
                suffix=suffix,
            )
        if multipart_created:
            _cleanup_multipart(client, session, upload_id=multipart_upload)
        if positive_written and not positive_confirmed_absent:
            _cleanup_object(
                client, session, trigger="positive control not confirmed absent", suffix="positive"
            )
    finished = now()
    if halted_at is None:
        result = R3Result.VERIFIED
    elif session.residue or session.budget_exhausted:
        # Every cleanup that did not resolve named its key as residue (a repeated abort
        # that resolved on its second attempt named none).
        result = R3Result.NOT_VERIFIED_CLEANUP_UNRESOLVED
    else:
        result = R3Result.NOT_VERIFIED
    return R3Record(
        result=result,
        stamp=session.stamp,
        control_profile=CONTROL_PROFILE,
        binding=binding,
        rows=tuple(session.rows),
        cleanup=tuple(session.cleanup),
        expected_path_operations=session.expected_path_operations,
        failure_path_operations=session.failure_path_operations,
        residue=tuple(dict.fromkeys(session.residue)),
        budget_exhausted=session.budget_exhausted,
        started_at=started,
        finished_at=finished,
    )


def not_exercised_record(*, binding: R3Binding, now: datetime, stamp: str) -> R3Record:
    """The record of a session that never reached S3 (an identity gate that did not pass)."""
    return R3Record(
        result=R3Result.NOT_EXERCISED,
        stamp=stamp,
        control_profile=CONTROL_PROFILE,
        binding=binding,
        rows=tuple(
            RowOutcome(
                number=row.number,
                operation=row.operation,
                key_suffix=row.key_suffix,
                expected=row.expected,
                observed=ObservedClass.NOT_EXERCISED,
                matched=False,
            )
            for row in EXPECTED_PATH
        ),
        cleanup=(),
        expected_path_operations=0,
        failure_path_operations=0,
        residue=(),
        budget_exhausted=False,
        started_at=now,
        finished_at=now,
    )


_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "result",
        "stamp",
        "verification_prefix",
        "control_profile",
        "binding",
        "rows",
        "cleanup",
        "expected_path_operations",
        "failure_path_operations",
        "residue",
        "budget_exhausted",
        "started_at",
        "finished_at",
    }
)
_ROW_FIELDS: Final[frozenset[str]] = frozenset(
    {"row", "operation", "key_suffix", "expected", "observed", "matched"}
)
_CLEANUP_FIELDS: Final[frozenset[str]] = frozenset(
    {"trigger", "operation", "key_suffix", "observed", "confirmation", "resolved"}
)
_HEX_64: Final = frozenset("0123456789abcdef")


class R3RecordError(ValueError):
    """A record that is not one. Carries no value."""


def _hex64(value: object) -> str:
    text = exact_str(value)
    if text is None or len(text) != 64 or set(text) - _HEX_64:
        raise R3RecordError("malformed")
    return text


def parse_r3_record(raw: object) -> R3Record:
    """A record document, every field to its grammar and every row to the accepted table."""
    try:
        document = (
            decode_document(raw, max_bytes=MAX_R3_RECORD_BYTES) if type(raw) is bytes else raw
        )
    except Exception:
        raise R3RecordError("malformed") from None
    if type(document) is not dict or set(document) != _RECORD_FIELDS:
        raise R3RecordError("malformed")
    if (
        document["schema_version"] != R3_RECORD_SCHEMA_VERSION
        or document["contract_id"] != R3_RECORD_CONTRACT_ID
    ):
        raise R3RecordError("malformed")
    result = exact_str(document["result"])
    stamp = exact_str(document["stamp"])
    profile = exact_str(document["control_profile"])
    started = instant(document["started_at"])
    finished = instant(document["finished_at"])
    if (
        result not in {m.value for m in R3Result}
        or stamp is None
        or not stamp
        or "/" in stamp
        or document["verification_prefix"] != f"{VERIFICATION_PREFIX}/{stamp}/"
        or profile != CONTROL_PROFILE
        or started is None
        or finished is None
        or finished < started
        or type(document["expected_path_operations"]) is not int
        or type(document["failure_path_operations"]) is not int
        or not 0 <= document["expected_path_operations"] <= EXPECTED_PATH_OPERATIONS
        or not 0 <= document["failure_path_operations"] <= FAILURE_PATH_BUDGET
        or type(document["budget_exhausted"]) is not bool
        or type(document["residue"]) is not list
        or any(
            type(k) is not str or not k.startswith(f"{VERIFICATION_PREFIX}/{stamp}/")
            for k in document["residue"]
        )
    ):
        raise R3RecordError("malformed")
    binding_raw = document["binding"]
    if type(binding_raw) is not dict or set(binding_raw) != {
        "environment_binding_sha256",
        "policy_declaration_sha256",
        "partition",
        "region",
    }:
        raise R3RecordError("malformed")
    partition = exact_str(binding_raw["partition"])
    region = exact_str(binding_raw["region"])
    if not partition or not region:
        raise R3RecordError("malformed")
    binding = R3Binding(
        environment_binding_sha256=_hex64(binding_raw["environment_binding_sha256"]),
        policy_declaration_sha256=_hex64(binding_raw["policy_declaration_sha256"]),
        partition=partition,
        region=region,
    )
    rows_raw = document["rows"]
    if type(rows_raw) is not list or len(rows_raw) != EXPECTED_PATH_OPERATIONS:
        raise R3RecordError("malformed")
    rows: list[RowOutcome] = []
    for expected, raw_row in zip(EXPECTED_PATH, rows_raw, strict=True):
        if type(raw_row) is not dict or set(raw_row) != _ROW_FIELDS:
            raise R3RecordError("malformed")
        observed = exact_str(raw_row["observed"])
        if (
            raw_row["row"] != expected.number
            or raw_row["operation"] != expected.operation.value
            or raw_row["key_suffix"] != expected.key_suffix
            or raw_row["expected"] != [c.value for c in expected.expected]
            or observed not in {m.value for m in ObservedClass}
            or type(raw_row["matched"]) is not bool
            or raw_row["matched"] != (ObservedClass(observed) in expected.expected)
        ):
            raise R3RecordError("malformed")
        rows.append(
            RowOutcome(
                number=expected.number,
                operation=expected.operation,
                key_suffix=expected.key_suffix,
                expected=expected.expected,
                observed=ObservedClass(observed),
                matched=raw_row["matched"],
            )
        )
    cleanup_raw = document["cleanup"]
    if type(cleanup_raw) is not list:
        raise R3RecordError("malformed")
    cleanup: list[CleanupOutcome] = []
    for raw_item in cleanup_raw:
        if type(raw_item) is not dict or set(raw_item) != _CLEANUP_FIELDS:
            raise R3RecordError("malformed")
        operation = exact_str(raw_item["operation"])
        observed = exact_str(raw_item["observed"])
        confirmation = raw_item["confirmation"]
        trigger = exact_str(raw_item["trigger"])
        suffix = exact_str(raw_item["key_suffix"])
        if (
            operation not in {R3Operation.DELETE.value, R3Operation.ABORT_MULTIPART.value}
            or observed not in {m.value for m in ObservedClass}
            or (confirmation is not None and confirmation not in {m.value for m in ObservedClass})
            or type(raw_item["resolved"]) is not bool
            or not trigger
            or not suffix
        ):
            raise R3RecordError("malformed")
        cleanup.append(
            CleanupOutcome(
                trigger=trigger,
                operation=R3Operation(operation),
                key_suffix=suffix,
                observed=ObservedClass(observed),
                confirmation=None if confirmation is None else ObservedClass(confirmation),
                resolved=raw_item["resolved"],
            )
        )
    # The result must be the one the rows and cleanup imply; a record cannot say VERIFIED
    # over a deviating row, nor claim resolution over residue.
    all_matched = all(row.matched for row in rows)
    unresolved = bool(document["residue"]) or document["budget_exhausted"]
    residue = set(document["residue"])
    # Every cleanup a halted path owed is present or its key is residue: an object a
    # row may have created (rows 2, 4, 5), an upload from row 6, the positive control
    # when row 8 did not remove it; and a cleanup that stayed unresolved named residue.
    by_key: dict[str, bool] = {}
    for item in cleanup:
        by_key[item.key_suffix] = item.resolved
    for suffix, resolved in by_key.items():
        if not resolved and verification_key(stamp, suffix) not in residue:
            raise R3RecordError("malformed")
    if not all_matched:
        owed: set[str] = set()
        for row in rows:
            if row.number in {2, 4, 5} and row.observed in _MAY_HAVE_CREATED:
                owed.add(row.key_suffix)
            if row.number == 6 and row.observed in _MAY_HAVE_CREATED:
                owed.add("multipart")
        positive_written = rows[0].observed in _MAY_HAVE_CREATED
        positive_confirmed = rows[8].observed is ObservedClass.NOT_FOUND_404
        if positive_written and not positive_confirmed:
            owed.add("positive")
        for suffix in owed:
            if suffix not in by_key and verification_key(stamp, suffix) not in residue:
                raise R3RecordError("malformed")
    implied = (
        R3Result.VERIFIED
        if all_matched
        else (R3Result.NOT_VERIFIED_CLEANUP_UNRESOLVED if unresolved else R3Result.NOT_VERIFIED)
    )
    if result == R3Result.NOT_EXERCISED.value:
        if document["expected_path_operations"] != 0 or any(
            row.observed is not ObservedClass.NOT_EXERCISED for row in rows
        ):
            raise R3RecordError("malformed")
    elif R3Result(result) is not implied:
        raise R3RecordError("malformed")
    if all_matched and (cleanup or document["residue"] or document["budget_exhausted"]):
        raise R3RecordError("malformed")
    return R3Record(
        result=R3Result(result),
        stamp=stamp,
        control_profile=CONTROL_PROFILE,
        binding=binding,
        rows=tuple(rows),
        cleanup=tuple(cleanup),
        expected_path_operations=document["expected_path_operations"],
        failure_path_operations=document["failure_path_operations"],
        residue=tuple(document["residue"]),
        budget_exhausted=document["budget_exhausted"],
        started_at=started,
        finished_at=finished,
    )


def record_attests(record: R3Record, *, binding: R3Binding) -> bool:
    """Whether ``record`` is VERIFIED evidence for exactly ``binding`` (policy, target, region)."""
    return record.result is R3Result.VERIFIED and record.binding == binding


__all__ = [
    "CONTROL_PROFILE",
    "EXPECTED_PATH",
    "EXPECTED_PATH_OPERATIONS",
    "FAILURE_PATH_BUDGET",
    "MAX_R3_RECORD_BYTES",
    "R3_RECORD_CONTRACT_ID",
    "R3_RECORD_SCHEMA_VERSION",
    "SYNTHETIC_MARKER",
    "VERIFICATION_PREFIX",
    "CleanupOutcome",
    "ExpectedRow",
    "Observation",
    "ObservedClass",
    "R3Binding",
    "R3Client",
    "R3Operation",
    "R3Record",
    "R3RecordError",
    "R3Result",
    "RowOutcome",
    "classify",
    "new_stamp",
    "not_exercised_record",
    "parse_r3_record",
    "record_attests",
    "run_r3",
    "verification_key",
]
