"""The deletion rehearsal task: the contracts the task reads and emits, and its composition.

The rehearsal runs as an ECS task whose task role **is** the deletion role (ADR-0048 s.4,
ADR-0049 s.3.1): no human and no control principal ever substitutes for it. This module is
the task's side of that path, offline: the three parameters the launcher materializes and
the task reads (the **runtime binding**, the **input**, the **release**), the **receipt** the
task emits as its one machine-readable line, the ordered composition that reads them, proves
the task's own identity, waits for the release and only then issues the subcell's
operations through :func:`deletion_rehearsal.rehearse_subcell` over the task's own S3 client,
and the verifier the launcher's completion and the collector apply to the receipt.

The order is the accepted bootstrap's and it is the security property: entry, credential
environment, task metadata, binding, input, identity, release, then the operations. No
later stage runs after an earlier refusal, so a task that is not the deletion role, or is
not the task the launcher released, never touches the bucket. Every contract is closed and
every refusal is a closed token; no identifier, key, ARN or body is ever rendered.

**The path is CLOSED** (:data:`deletion_rehearsal.REHEARSAL_PATH_OPEN`): no task
definition carries this entry, no image builds it, and the only callers here are tests over
fakes. **Mocked results are not AWS verification.**
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar.bindings import (
    BINDING_SCHEMA_VERSION,
    ParameterReader,
    _validate_provenance,
    decode_parameter_document,
)
from kalpamani.data.production.sharadar.deletion_rehearsal import (
    REHEARSAL_BINDING_CONTRACT_ID,
    REHEARSAL_BINDING_PARAMETER,
    REHEARSAL_ENTRY,
    REHEARSAL_INPUT_PARAMETER,
    REHEARSAL_OPERATION_BUDGET,
    REHEARSAL_RELEASE_PARAMETER,
    REHEARSAL_SEQUENCE,
    REHEARSAL_STATEMENT_CONTRACT_ID,
    RehearsalOutcome,
    RehearsalRecord,
    RehearsalStatement,
    RehearsalTarget,
    rehearse_subcell,
)
from kalpamani.data.production.sharadar.documents import exact_str, hex_digest, instant
from kalpamani.data.production.sharadar.identity import parse_assumed_role_arn
from kalpamani.data.production.sharadar.launch_records import RECORD_SCHEMA_VERSION
from kalpamani.data.production.sharadar.metadata import TaskMetadata
from kalpamani.data.production.sharadar.parameters import ParameterError, ParameterFailure
from kalpamani.data.production.sharadar.permission_cells import (
    PermissionClient,
    _binding_from,
)
from kalpamani.data.production.sharadar.r3_verification import ObservedClass
from kalpamani.data.production.sharadar.receipts import MAX_RECEIPT_BYTES, RECEIPT_LINE_PREFIX
from kalpamani.data.production.sharadar.task_clients import (
    container_credential_source_refusal,
    task_credential_environment_refusal,
)
from kalpamani.data.production.sharadar.vocabulary import EXPECTED_PARTITION, EXPECTED_REGION

# ---------------------------------------------------------------------------
# Contract identities and bounds
# ---------------------------------------------------------------------------

REHEARSAL_INPUT_CONTRACT_ID: Final = "kalpamani-deletion-rehearsal-input/v1"
REHEARSAL_RELEASE_CONTRACT_ID: Final = "kalpamani-deletion-rehearsal-release/v1"
REHEARSAL_RECEIPT_CONTRACT_ID: Final = "kalpamani-deletion-rehearsal-receipt/v1"
REHEARSAL_RECEIPT_SCHEMA_VERSION: Final = 1
MAX_REHEARSAL_PARAMETER_BYTES: Final = 8 * 1024
#: An input is valid for at most one day; a release for ten minutes (the accepted values).
MAX_INPUT_VALIDITY: Final = timedelta(hours=24)
MAX_RELEASE_VALIDITY: Final = timedelta(minutes=10)
#: The release barrier's bounds: the accepted 5 s / 60 reads / 300 s.
RELEASE_POLL_SECONDS: Final = 5.0
MAX_RELEASE_READS: Final = 60
RELEASE_CEILING_SECONDS: Final = 300.0
#: One rehearsal identity per launch: ``rehearsal-<stamp>``.
REHEARSAL_IDENTITY_PREFIX: Final = "rehearsal-"
REHEARSAL_IDENTITY_RE: Final = re.compile(r"rehearsal-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{4}")
_TASK_ARN_RE: Final = re.compile(
    r"arn:aws:ecs:([a-z0-9-]+):([0-9]{12}):task/([A-Za-z0-9_-]+)/([0-9a-f]{32})"
)
_TASK_DEFINITION_ARN_RE: Final = re.compile(
    r"arn:aws:ecs:([a-z0-9-]+):([0-9]{12}):task-definition/([A-Za-z0-9_-]+):([0-9]+)"
)
_IMAGE_DIGEST_RE: Final = re.compile(r"sha256:[0-9a-f]{64}")
_ROLE_NAME_RE: Final = re.compile(r"[A-Za-z0-9+=,.@_-]{1,64}")
_BUCKET_RE: Final = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")


class RehearsalTaskOutcome(StrEnum):
    """What the rehearsal task established, in the order it can refuse. Closed."""

    REHEARSED = "REHEARSED"
    REFUSED_ENTRY = "REFUSED_ENTRY"
    REFUSED_CREDENTIAL_ENVIRONMENT = "REFUSED_CREDENTIAL_ENVIRONMENT"
    REFUSED_METADATA = "REFUSED_METADATA"
    REFUSED_BINDING = "REFUSED_BINDING"
    REFUSED_INPUT = "REFUSED_INPUT"
    REFUSED_IDENTITY = "REFUSED_IDENTITY"
    REFUSED_RELEASE = "REFUSED_RELEASE"
    REFUSED_TARGET = "REFUSED_TARGET"
    UNCLASSIFIED = "UNCLASSIFIED"


#: The task's exit status per outcome: its own closed table, disjoint from the
#: production, verification and probe tables so a launcher can never read one as another.
REHEARSAL_EXIT_STATUS: Final[dict[RehearsalTaskOutcome, int]] = {
    RehearsalTaskOutcome.REHEARSED: 50,
    RehearsalTaskOutcome.REFUSED_ENTRY: 51,
    RehearsalTaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT: 52,
    RehearsalTaskOutcome.REFUSED_METADATA: 53,
    RehearsalTaskOutcome.REFUSED_BINDING: 54,
    RehearsalTaskOutcome.REFUSED_INPUT: 55,
    RehearsalTaskOutcome.REFUSED_IDENTITY: 56,
    RehearsalTaskOutcome.REFUSED_RELEASE: 57,
    RehearsalTaskOutcome.REFUSED_TARGET: 58,
    RehearsalTaskOutcome.UNCLASSIFIED: 59,
}


class RehearsalContractDefect(StrEnum):
    """Why a rehearsal contract document is refused. Closed, value-free."""

    BINDING_MALFORMED = "BINDING_MALFORMED"
    INPUT_MALFORMED = "INPUT_MALFORMED"
    INPUT_EXPIRED = "INPUT_EXPIRED"
    RELEASE_MALFORMED = "RELEASE_MALFORMED"
    RELEASE_MISMATCH = "RELEASE_MISMATCH"
    RELEASE_EXPIRED = "RELEASE_EXPIRED"
    RECEIPT_MALFORMED = "RECEIPT_MALFORMED"
    RECEIPT_DIGEST_MISMATCH = "RECEIPT_DIGEST_MISMATCH"
    RECEIPT_BINDING_MISMATCH = "RECEIPT_BINDING_MISMATCH"
    RECEIPT_STATEMENT_MISMATCH = "RECEIPT_STATEMENT_MISMATCH"
    RECEIPT_OUTCOME_CONTRADICTS = "RECEIPT_OUTCOME_CONTRADICTS"


class RehearsalContractError(ValueError):
    def __init__(self, defect: RehearsalContractDefect) -> None:
        super().__init__(defect.value)
        self.defect = defect


def _refuse(defect: RehearsalContractDefect) -> RehearsalContractError:
    return RehearsalContractError(defect)


# ---------------------------------------------------------------------------
# The runtime binding the deletion role's task reads
# ---------------------------------------------------------------------------

_BINDING_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "binding_kind",
        "contract_id",
        "aws_partition",
        "aws_region",
        "target_account_id",
        "licensed_bucket_name",
        "deletion_role_name",
        "provenance",
    }
)
REHEARSAL_BINDING_KIND: Final = "kalpamani-deletion-rehearsal-runtime"


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalRuntimeBinding:
    """The validated binding: the account the identity gate compares against, the bucket
    the target must live in, and the deletion role's exact name. The provenance block is
    validated and not returned (ADR-0023)."""

    target_account_id: str
    licensed_bucket_name: str
    deletion_role_name: str

    def __repr__(self) -> str:
        return "RehearsalRuntimeBinding(<redacted>)"


def parse_rehearsal_runtime_binding(raw: object) -> RehearsalRuntimeBinding:
    """The deletion rehearsal binding (the build binding's field set with the deletion
    role's name in place of a profile), parsed closed, or refuse."""
    try:
        document = decode_parameter_document(raw, max_bytes=MAX_REHEARSAL_PARAMETER_BYTES)
    except Exception:
        raise _refuse(RehearsalContractDefect.BINDING_MALFORMED) from None
    if type(document) is not dict or set(document) != _BINDING_FIELDS:
        raise _refuse(RehearsalContractDefect.BINDING_MALFORMED)
    if (
        document["schema_version"] != BINDING_SCHEMA_VERSION
        or document["binding_kind"] != REHEARSAL_BINDING_KIND
        or document["contract_id"] != REHEARSAL_BINDING_CONTRACT_ID
        or document["aws_partition"] != EXPECTED_PARTITION
        or document["aws_region"] != EXPECTED_REGION
    ):
        raise _refuse(RehearsalContractDefect.BINDING_MALFORMED)
    account = exact_str(document["target_account_id"])
    bucket = exact_str(document["licensed_bucket_name"])
    role = exact_str(document["deletion_role_name"])
    if (
        account is None
        or not re.fullmatch(r"[0-9]{12}", account)
        or bucket is None
        or _BUCKET_RE.fullmatch(bucket) is None
        or role is None
        or _ROLE_NAME_RE.fullmatch(role) is None
    ):
        raise _refuse(RehearsalContractDefect.BINDING_MALFORMED)
    try:
        _validate_provenance(document["provenance"])
    except Exception:
        raise _refuse(RehearsalContractDefect.BINDING_MALFORMED) from None
    return RehearsalRuntimeBinding(
        target_account_id=account, licensed_bucket_name=bucket, deletion_role_name=role
    )


# ---------------------------------------------------------------------------
# The input the launcher materializes
# ---------------------------------------------------------------------------

_INPUT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "identity",
        "subcell_id",
        "statement",
        "statement_sha256",
        "authorization_sha256",
        "issued_at",
        "expires_at",
    }
)


def rehearsal_identity(stamp: str) -> str:
    """The rehearsal identity of one launch: ``rehearsal-<stamp>``."""
    identity = REHEARSAL_IDENTITY_PREFIX + stamp
    if REHEARSAL_IDENTITY_RE.fullmatch(identity) is None:
        raise ValueError("the stamp does not form a rehearsal identity")
    return identity


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalInput:
    """What the launcher hands the task: the prepared statement (whole, so the task
    recomputes its digest), the authorization it was consumed under, and the identity."""

    identity: str
    statement: RehearsalStatement
    authorization_sha256: str
    issued_at: datetime
    expires_at: datetime

    def __repr__(self) -> str:
        return f"RehearsalInput(subcell={self.statement.subcell_id!r})"

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": REHEARSAL_INPUT_CONTRACT_ID,
            "identity": self.identity,
            "subcell_id": self.statement.subcell_id,
            "statement": self.statement.document(),
            "statement_sha256": self.statement.digest,
            "authorization_sha256": self.authorization_sha256,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    def render(self) -> bytes:
        return canonical_bytes(self.document())


def _statement_from(raw: object) -> RehearsalStatement:
    """A statement document back into a statement; the digest is recomputed by the
    caller and held to the one the input names."""
    if type(raw) is not dict or set(raw) != {
        "schema_version",
        "contract_id",
        "subcell_id",
        "principal",
        "operation",
        "expectation",
        "sequence_position",
        "target",
        "target_sha256",
        "stamp",
        "binding",
    }:
        raise ValueError("statement: closed field set")
    if raw["contract_id"] != REHEARSAL_STATEMENT_CONTRACT_ID:
        raise ValueError("statement: contract")
    subcell_id = exact_str(raw["subcell_id"])
    stamp = exact_str(raw["stamp"])
    target = raw["target"]
    if (
        subcell_id not in REHEARSAL_SEQUENCE
        or stamp is None
        or type(target) is not dict
        or set(target) != {"bucket", "key", "prerequisite_sha256"}
    ):
        raise ValueError("statement: field")
    bucket, key = exact_str(target["bucket"]), exact_str(target["key"])
    prerequisite = hex_digest(target["prerequisite_sha256"])
    if bucket is None or key is None or prerequisite is None:
        raise ValueError("statement: target")
    statement = RehearsalStatement(
        subcell_id=subcell_id,
        target=RehearsalTarget(bucket=bucket, key=key, prerequisite_sha256=prerequisite),
        stamp=stamp,
        binding=_binding_from(raw["binding"]),
    )
    if statement.document() != raw:
        raise ValueError("statement: derived fields")
    return statement


def parse_rehearsal_statement(raw: object) -> RehearsalStatement:
    """A prepared statement record (the owner tool's ``rehearsal-statement``) back into a
    statement, every derived field recomputed and held to the document, or refuse."""
    try:
        document = decode_parameter_document(raw, max_bytes=MAX_REHEARSAL_PARAMETER_BYTES)
        return _statement_from(document)
    except Exception:
        raise _refuse(RehearsalContractDefect.INPUT_MALFORMED) from None


def parse_rehearsal_input(raw: object, *, now: datetime) -> RehearsalInput:
    """The input, parsed closed and valid at ``now``, or refuse.

    The statement's digest is recomputed from the statement document and held to the
    digest the input names; the identity is held to the statement's stamp.
    """
    try:
        document = decode_parameter_document(raw, max_bytes=MAX_REHEARSAL_PARAMETER_BYTES)
    except Exception:
        raise _refuse(RehearsalContractDefect.INPUT_MALFORMED) from None
    if type(document) is not dict or set(document) != _INPUT_FIELDS:
        raise _refuse(RehearsalContractDefect.INPUT_MALFORMED)
    if (
        document["schema_version"] != RECORD_SCHEMA_VERSION
        or document["contract_id"] != REHEARSAL_INPUT_CONTRACT_ID
    ):
        raise _refuse(RehearsalContractDefect.INPUT_MALFORMED)
    identity = exact_str(document["identity"])
    digest = hex_digest(document["statement_sha256"])
    authorization = hex_digest(document["authorization_sha256"])
    issued, expires = instant(document["issued_at"]), instant(document["expires_at"])
    try:
        statement = _statement_from(document["statement"])
    except (ValueError, TypeError, KeyError):
        raise _refuse(RehearsalContractDefect.INPUT_MALFORMED) from None
    if (
        identity is None
        or REHEARSAL_IDENTITY_RE.fullmatch(identity) is None
        or identity != rehearsal_identity(statement.stamp)
        or digest is None
        or digest != statement.digest
        or authorization is None
        or issued is None
        or expires is None
        or exact_str(document["subcell_id"]) != statement.subcell_id
        or not issued < expires
        or expires - issued > MAX_INPUT_VALIDITY
    ):
        raise _refuse(RehearsalContractDefect.INPUT_MALFORMED)
    if not issued <= now < expires:
        raise _refuse(RehearsalContractDefect.INPUT_EXPIRED)
    return RehearsalInput(
        identity=identity,
        statement=statement,
        authorization_sha256=authorization,
        issued_at=issued,
        expires_at=expires,
    )


# ---------------------------------------------------------------------------
# The release the launcher writes after verifying placement
# ---------------------------------------------------------------------------

_RELEASE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "identity",
        "task_arn",
        "task_definition_arn",
        "image_digest",
        "input_digest",
        "issued_at",
        "expires_at",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalRelease:
    """The launcher's release: exactly this task, this revision, this image, this input."""

    identity: str
    task_arn: str
    task_definition_arn: str
    image_digest: str
    input_digest: str
    issued_at: datetime
    expires_at: datetime

    def __repr__(self) -> str:
        return "RehearsalRelease(<redacted>)"

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": REHEARSAL_RELEASE_CONTRACT_ID,
            "identity": self.identity,
            "task_arn": self.task_arn,
            "task_definition_arn": self.task_definition_arn,
            "image_digest": self.image_digest,
            "input_digest": self.input_digest,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    def render(self) -> bytes:
        return canonical_bytes(self.document())


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalExpectation:
    """What the task (or the launcher's completion) already knows and holds a release or
    a receipt to: the task, revision and image, the identity, the input's digest and the
    statement and authorization the input carried. None of it is read from the document
    being verified."""

    task_id: str
    task_definition_arn: str
    image_digest: str
    identity: str
    input_digest: str
    statement_sha256: str
    authorization_sha256: str

    def __repr__(self) -> str:
        return "RehearsalExpectation(<redacted>)"


def parse_rehearsal_release(
    raw: object, *, expectation: RehearsalExpectation, now: datetime
) -> RehearsalRelease:
    """A release for exactly this task, or refuse (malformed, mismatched, expired)."""
    try:
        document = decode_parameter_document(raw, max_bytes=MAX_REHEARSAL_PARAMETER_BYTES)
    except Exception:
        raise _refuse(RehearsalContractDefect.RELEASE_MALFORMED) from None
    if type(document) is not dict or set(document) != _RELEASE_FIELDS:
        raise _refuse(RehearsalContractDefect.RELEASE_MALFORMED)
    if (
        document["schema_version"] != RECORD_SCHEMA_VERSION
        or document["contract_id"] != REHEARSAL_RELEASE_CONTRACT_ID
    ):
        raise _refuse(RehearsalContractDefect.RELEASE_MALFORMED)
    values = {name: exact_str(document[name]) for name in _RELEASE_FIELDS - {"schema_version"}}
    issued, expires = instant(document["issued_at"]), instant(document["expires_at"])
    task_arn = values["task_arn"]
    if (
        any(values[n] is None for n in ("identity", "task_arn", "task_definition_arn"))
        or values["image_digest"] is None
        or hex_digest(values["input_digest"]) is None
        or issued is None
        or expires is None
        or not issued < expires
        or expires - issued > MAX_RELEASE_VALIDITY
        or task_arn is None
        or _TASK_ARN_RE.fullmatch(task_arn) is None
    ):
        raise _refuse(RehearsalContractDefect.RELEASE_MALFORMED)
    task_id = task_arn.rsplit("/", 1)[1]
    if (
        task_id != expectation.task_id
        or values["task_definition_arn"] != expectation.task_definition_arn
        or values["image_digest"] != expectation.image_digest
        or values["identity"] != expectation.identity
        or values["input_digest"] != expectation.input_digest
    ):
        raise _refuse(RehearsalContractDefect.RELEASE_MISMATCH)
    if not issued <= now < expires:
        raise _refuse(RehearsalContractDefect.RELEASE_EXPIRED)
    return RehearsalRelease(
        identity=str(values["identity"]),
        task_arn=task_arn,
        task_definition_arn=str(values["task_definition_arn"]),
        image_digest=str(values["image_digest"]),
        input_digest=str(values["input_digest"]),
        issued_at=issued,
        expires_at=expires,
    )


# ---------------------------------------------------------------------------
# The receipt the task emits
# ---------------------------------------------------------------------------


def rehearsal_binding_digest(expectation: RehearsalExpectation) -> str:
    """The digest that binds a receipt to one launch: task id, revision, image, identity
    and input digest -- the launch record's fields, never the receipt's own claims."""
    return sha256_hex(
        canonical_bytes(
            {
                "task_id": expectation.task_id,
                "task_definition_arn": expectation.task_definition_arn,
                "image_digest": expectation.image_digest,
                "identity": expectation.identity,
                "input_digest": expectation.input_digest,
            }
        )
    )


_RECEIPT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "entry",
        "outcome",
        "exit_code",
        "binding_digest",
        "rehearsal",
        "receipt_digest",
    }
)
_REHEARSAL_BLOCK_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "subcell_id",
        "statement_sha256",
        "authorization_sha256",
        "target",
        "observed",
        "outcome",
        "deleted",
        "possibly_deleted",
        "operations",
        "identity_verified",
        "stamp",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalReceipt:
    """The task's one closed line: the outcome, its exit status, the binding digest and
    -- exactly when it rehearsed -- the record it established (classes and counts)."""

    outcome: RehearsalTaskOutcome
    binding_digest: str | None
    record: RehearsalRecord | None

    def __post_init__(self) -> None:
        if (self.outcome is RehearsalTaskOutcome.REHEARSED) != (self.record is not None):
            raise ValueError("a record is present exactly when the task rehearsed")
        if self.record is not None and self.binding_digest is None:
            raise ValueError("a rehearsed receipt is bound")

    @property
    def exit_code(self) -> int:
        return REHEARSAL_EXIT_STATUS[self.outcome]

    def document(self) -> dict[str, Any]:
        block: dict[str, Any] | None = None
        if self.record is not None:
            full = self.record.document()
            block = {name: full[name] for name in _REHEARSAL_BLOCK_FIELDS}
        document: dict[str, Any] = {
            "schema_version": REHEARSAL_RECEIPT_SCHEMA_VERSION,
            "contract_id": REHEARSAL_RECEIPT_CONTRACT_ID,
            "entry": REHEARSAL_ENTRY,
            "outcome": self.outcome.value,
            "exit_code": self.exit_code,
            "binding_digest": self.binding_digest,
            "rehearsal": block,
        }
        document["receipt_digest"] = sha256_hex(canonical_bytes(document))
        return document

    def line(self) -> str:
        """The one machine-readable line, on the shared receipt prefix."""
        return RECEIPT_LINE_PREFIX + canonical_bytes(self.document()).decode("utf-8")

    def render(self) -> tuple[str, ...]:
        """The allowlisted lines: a sentence and the receipt line."""
        return (f"deletion rehearsal {self.outcome.value}", self.line())

    def __repr__(self) -> str:
        return f"RehearsalReceipt(outcome={self.outcome.value!r})"


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifiedRehearsalReceipt:
    """A receipt verified against the launch: the outcome and, when rehearsed, the block
    from which the launcher's completion rebuilds the record under its own binding."""

    outcome: RehearsalTaskOutcome
    exit_code: int
    block: dict[str, Any] | None

    def __repr__(self) -> str:
        return f"VerifiedRehearsalReceipt(outcome={self.outcome.value!r})"


def verify_rehearsal_receipt(
    document: object, *, expectation: RehearsalExpectation
) -> VerifiedRehearsalReceipt:
    """Every clause in order: shape, digest, exit status, binding, then the block's
    statement and authorization held to the expectation's."""
    if type(document) is not dict or set(document) != _RECEIPT_FIELDS:
        raise _refuse(RehearsalContractDefect.RECEIPT_MALFORMED)
    if (
        document["schema_version"] != REHEARSAL_RECEIPT_SCHEMA_VERSION
        or document["contract_id"] != REHEARSAL_RECEIPT_CONTRACT_ID
        or document["entry"] != REHEARSAL_ENTRY
    ):
        raise _refuse(RehearsalContractDefect.RECEIPT_MALFORMED)
    outcome_text = exact_str(document["outcome"])
    if outcome_text not in {m.value for m in RehearsalTaskOutcome}:
        raise _refuse(RehearsalContractDefect.RECEIPT_MALFORMED)
    outcome = RehearsalTaskOutcome(str(outcome_text))
    body = {name: value for name, value in document.items() if name != "receipt_digest"}
    if (
        hex_digest(document["receipt_digest"]) is None
        or sha256_hex(canonical_bytes(body)) != document["receipt_digest"]
    ):
        raise _refuse(RehearsalContractDefect.RECEIPT_DIGEST_MISMATCH)
    if document["exit_code"] != REHEARSAL_EXIT_STATUS[outcome]:
        raise _refuse(RehearsalContractDefect.RECEIPT_OUTCOME_CONTRADICTS)
    block = document["rehearsal"]
    if (block is not None) != (outcome is RehearsalTaskOutcome.REHEARSED):
        raise _refuse(RehearsalContractDefect.RECEIPT_OUTCOME_CONTRADICTS)
    bound = document["binding_digest"]
    if block is None:
        if bound is not None and bound != rehearsal_binding_digest(expectation):
            raise _refuse(RehearsalContractDefect.RECEIPT_BINDING_MISMATCH)
        return VerifiedRehearsalReceipt(
            outcome=outcome, exit_code=int(document["exit_code"]), block=None
        )
    if bound != rehearsal_binding_digest(expectation):
        raise _refuse(RehearsalContractDefect.RECEIPT_BINDING_MISMATCH)
    if type(block) is not dict or set(block) != _REHEARSAL_BLOCK_FIELDS:
        raise _refuse(RehearsalContractDefect.RECEIPT_MALFORMED)
    observed = block["observed"]
    if (
        exact_str(block["subcell_id"]) not in REHEARSAL_SEQUENCE
        or hex_digest(block["statement_sha256"]) is None
        or hex_digest(block["authorization_sha256"]) is None
        or type(block["target"]) is not dict
        or type(observed) is not list
        or not 1 <= len(observed) <= REHEARSAL_OPERATION_BUDGET
        or any(exact_str(o) not in {m.value for m in ObservedClass} for o in observed)
        or exact_str(block["outcome"]) not in {m.value for m in RehearsalOutcome}
        or type(block["deleted"]) is not bool
        or type(block["possibly_deleted"]) is not bool
        or type(block["identity_verified"]) is not bool
        or block["operations"] != len(observed)
        or exact_str(block["stamp"]) is None
    ):
        raise _refuse(RehearsalContractDefect.RECEIPT_MALFORMED)
    if (
        block["statement_sha256"] != expectation.statement_sha256
        or block["authorization_sha256"] != expectation.authorization_sha256
    ):
        raise _refuse(RehearsalContractDefect.RECEIPT_STATEMENT_MISMATCH)
    return VerifiedRehearsalReceipt(
        outcome=outcome, exit_code=int(document["exit_code"]), block=dict(block)
    )


def rehearsal_receipt_verifier(expectation: RehearsalExpectation) -> Callable[[str], None]:
    """The collector's verifier for a rehearsal launch: decode the line, verify it."""
    from kalpamani.data.production.sharadar.receipts import ReceiptError, decode_receipt_line

    def verify(line: str) -> None:
        document = decode_receipt_line(line)
        try:
            verify_rehearsal_receipt(document, expectation=expectation)
        except RehearsalContractError as error:
            raise ReceiptError(_receipt_defect_for(error)) from None

    return verify


def _receipt_defect_for(error: RehearsalContractError) -> Any:
    from kalpamani.data.production.sharadar.receipts import ReceiptDefect

    mapping = {
        RehearsalContractDefect.RECEIPT_MALFORMED: ReceiptDefect.FIELD_MALFORMED,
        RehearsalContractDefect.RECEIPT_DIGEST_MISMATCH: ReceiptDefect.DIGEST_MISMATCH,
        RehearsalContractDefect.RECEIPT_BINDING_MISMATCH: ReceiptDefect.BINDING_MISMATCH,
        RehearsalContractDefect.RECEIPT_STATEMENT_MISMATCH: ReceiptDefect.BINDING_MISMATCH,
        RehearsalContractDefect.RECEIPT_OUTCOME_CONTRADICTS: (
            ReceiptDefect.EXIT_CODE_CONTRADICTS_OUTCOME
        ),
    }
    return mapping.get(error.defect, ReceiptDefect.FIELD_MALFORMED)


# ---------------------------------------------------------------------------
# The task's composition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalTaskAdapters:
    """Everything the rehearsal task may touch, injected. No transport, no secret.

    ``s3`` builds the one client the operations use -- the task's own credential source
    acting as the deletion role -- and is called at most once, after the release.
    """

    environment_names: Callable[[], Iterable[str]]
    environment: Callable[[str], str | None]
    metadata: Callable[[], TaskMetadata]
    parameters: ParameterReader
    caller_identity: Callable[[], dict[str, str]]
    s3: Callable[[], PermissionClient]
    now: Callable[[], datetime]
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalTaskResult:
    """The receipt and the counts a test holds the task to."""

    receipt: RehearsalReceipt
    parameter_reads: int
    identity_calls: int
    release_reads: int
    s3_clients_built: int

    def __repr__(self) -> str:
        return f"RehearsalTaskResult(outcome={self.receipt.outcome.value!r})"


def _refusal(
    outcome: RehearsalTaskOutcome, *, bound: str | None = None, **counts: int
) -> RehearsalTaskResult:
    return RehearsalTaskResult(
        receipt=RehearsalReceipt(outcome=outcome, binding_digest=bound, record=None),
        parameter_reads=counts.get("parameter_reads", 0),
        identity_calls=counts.get("identity_calls", 0),
        release_reads=counts.get("release_reads", 0),
        s3_clients_built=0,
    )


def run_rehearsal_task(argv: list[str], adapters: RehearsalTaskAdapters) -> RehearsalTaskResult:
    """The rehearsal task, in the accepted bootstrap's order; one closed receipt.

    Entry (exactly one closed token), credential environment (names only), task metadata,
    the binding, the input, the identity (the deletion role's exact name in the bound
    account, this task's session), the release (exactly this task), and only then the
    subcell's operations through :func:`rehearse_subcell` over the task's own client.
    The target must live in the bound bucket. No later stage runs after a refusal.
    """
    if list(argv) != [REHEARSAL_ENTRY]:
        return _refusal(RehearsalTaskOutcome.REFUSED_ENTRY)
    try:
        names = list(adapters.environment_names())
    except Exception:
        return _refusal(RehearsalTaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT)
    if task_credential_environment_refusal(names) is not None:
        return _refusal(RehearsalTaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT)
    if container_credential_source_refusal(adapters.environment) is not None:
        return _refusal(RehearsalTaskOutcome.REFUSED_CREDENTIAL_ENVIRONMENT)
    try:
        metadata = adapters.metadata()
        task_id = metadata.task_id
        task_definition_arn = metadata.task_definition_arn()
    except Exception:
        return _refusal(RehearsalTaskOutcome.REFUSED_METADATA)
    if (
        type(metadata) is not TaskMetadata
        or _TASK_DEFINITION_ARN_RE.fullmatch(task_definition_arn) is None
        or len(metadata.image_ids) != 1
        or _IMAGE_DIGEST_RE.fullmatch(metadata.image_ids[0]) is None
    ):
        return _refusal(RehearsalTaskOutcome.REFUSED_METADATA)
    image_digest = metadata.image_ids[0]
    reads = 0
    try:
        reads += 1
        binding = parse_rehearsal_runtime_binding(
            adapters.parameters.read_parameter(REHEARSAL_BINDING_PARAMETER)
        )
    except Exception:
        return _refusal(RehearsalTaskOutcome.REFUSED_BINDING, parameter_reads=reads)
    try:
        reads += 1
        input_bytes = adapters.parameters.read_parameter(REHEARSAL_INPUT_PARAMETER)
        rehearsal_input = parse_rehearsal_input(input_bytes, now=adapters.now())
    except Exception:
        return _refusal(RehearsalTaskOutcome.REFUSED_INPUT, parameter_reads=reads)
    expectation = RehearsalExpectation(
        task_id=task_id,
        task_definition_arn=task_definition_arn,
        image_digest=image_digest,
        identity=rehearsal_input.identity,
        input_digest=sha256_hex(input_bytes),
        statement_sha256=rehearsal_input.statement.digest,
        authorization_sha256=rehearsal_input.authorization_sha256,
    )
    bound = rehearsal_binding_digest(expectation)
    if rehearsal_input.statement.target.bucket != binding.licensed_bucket_name:
        return _refusal(RehearsalTaskOutcome.REFUSED_TARGET, bound=bound, parameter_reads=reads)
    identity_calls = 1
    try:
        caller = adapters.caller_identity()
        parsed = parse_assumed_role_arn(caller.get("Arn"))
        account_ok = caller.get("Account") == binding.target_account_id
    except Exception:
        return _refusal(
            RehearsalTaskOutcome.REFUSED_IDENTITY,
            bound=bound,
            parameter_reads=reads,
            identity_calls=identity_calls,
        )
    if (
        parsed is None
        or not account_ok
        or parsed.account != binding.target_account_id
        or parsed.role_name != binding.deletion_role_name
        or parsed.session_name != task_id
    ):
        return _refusal(
            RehearsalTaskOutcome.REFUSED_IDENTITY,
            bound=bound,
            parameter_reads=reads,
            identity_calls=identity_calls,
        )
    # The release barrier: exactly this task's release, within the accepted bounds.
    started = adapters.monotonic()
    release_reads = 0
    released = False
    while True:
        elapsed = max(0.0, adapters.monotonic() - started)
        if release_reads >= MAX_RELEASE_READS or elapsed >= RELEASE_CEILING_SECONDS:
            break
        release_reads += 1
        try:
            raw = adapters.parameters.read_parameter(REHEARSAL_RELEASE_PARAMETER)
        except ParameterError as error:
            if error.failure is not ParameterFailure.NOT_FOUND:
                break
            if elapsed + RELEASE_POLL_SECONDS > RELEASE_CEILING_SECONDS:
                break
            adapters.sleep(RELEASE_POLL_SECONDS)
            continue
        except Exception:
            break
        if max(0.0, adapters.monotonic() - started) >= RELEASE_CEILING_SECONDS:
            break
        try:
            parse_rehearsal_release(raw, expectation=expectation, now=adapters.now())
        except RehearsalContractError:
            break
        released = True
        break
    if not released:
        return _refusal(
            RehearsalTaskOutcome.REFUSED_RELEASE,
            bound=bound,
            parameter_reads=reads,
            identity_calls=identity_calls,
            release_reads=release_reads,
        )
    try:
        client = adapters.s3()
    except Exception:
        return _refusal(
            RehearsalTaskOutcome.UNCLASSIFIED,
            bound=bound,
            parameter_reads=reads,
            identity_calls=identity_calls,
            release_reads=release_reads,
        )
    started_at = adapters.now()
    record = rehearse_subcell(
        rehearsal_input.statement,
        authorization_sha256=rehearsal_input.authorization_sha256,
        client=client,
        identity_verified=True,
        now=started_at,
        finished=adapters.now(),
    )
    return RehearsalTaskResult(
        receipt=RehearsalReceipt(
            outcome=RehearsalTaskOutcome.REHEARSED, binding_digest=bound, record=record
        ),
        parameter_reads=reads,
        identity_calls=identity_calls,
        release_reads=release_reads,
        s3_clients_built=1,
    )


def receipt_lines_within(lines: Iterable[str]) -> list[str]:
    """The receipt-shaped lines among ``lines`` (the collector's rule), bounded."""
    return [
        line
        for line in lines
        if type(line) is str
        and line.startswith(RECEIPT_LINE_PREFIX)
        and len(line.encode("utf-8")) <= MAX_RECEIPT_BYTES + len(RECEIPT_LINE_PREFIX)
    ]


__all__ = [
    "MAX_INPUT_VALIDITY",
    "MAX_REHEARSAL_PARAMETER_BYTES",
    "MAX_RELEASE_READS",
    "MAX_RELEASE_VALIDITY",
    "REHEARSAL_BINDING_KIND",
    "REHEARSAL_EXIT_STATUS",
    "REHEARSAL_IDENTITY_PREFIX",
    "REHEARSAL_IDENTITY_RE",
    "REHEARSAL_INPUT_CONTRACT_ID",
    "REHEARSAL_RECEIPT_CONTRACT_ID",
    "REHEARSAL_RECEIPT_SCHEMA_VERSION",
    "REHEARSAL_RELEASE_CONTRACT_ID",
    "RELEASE_CEILING_SECONDS",
    "RELEASE_POLL_SECONDS",
    "RehearsalContractDefect",
    "RehearsalContractError",
    "RehearsalExpectation",
    "RehearsalInput",
    "RehearsalReceipt",
    "RehearsalRelease",
    "RehearsalRuntimeBinding",
    "RehearsalTaskAdapters",
    "RehearsalTaskOutcome",
    "RehearsalTaskResult",
    "VerifiedRehearsalReceipt",
    "parse_rehearsal_input",
    "parse_rehearsal_release",
    "parse_rehearsal_runtime_binding",
    "parse_rehearsal_statement",
    "receipt_lines_within",
    "rehearsal_binding_digest",
    "rehearsal_identity",
    "rehearsal_receipt_verifier",
    "run_rehearsal_task",
    "verify_rehearsal_receipt",
]
