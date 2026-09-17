"""The owner-side launch tool's records: ledger, slice, launch inputs, authorization, evidence.

**Proposed ADR-0045 — offline, exercised only against fakes.** ADR-0036 §2.6 keeps the owner
ledger on the workstation under the ADR-0023 trust boundary and has the launch tool cut each
task's input from it; §2.12 has the tool compile the launch, launch once, verify placement,
release, observe and clean up. This module is every document that tool reads or writes,
parsed closed, and the rules that make one identity one authorization:

- **the owner ledger** (``kalpamani-owner-ledger/v1``): every identity ever launched, production
  or verification, with its outcome and the evidence that established it. An identity that
  appears in the ledger at all is **consumed**: it may never be launched again for anything.
- **the launch inputs record** (``kalpamani-launch-inputs/v1``): the Terraform outputs and
  image-gate records the tool compiles a launch from -- never typed, always read from a
  record the owner produced from Terraform and the generation records.
- **the authorization record** (``kalpamani-launch-authorization/v1``): the owner's written
  authorization for **one** launch of **one** identity of **one** kind, expiring; a flag on the
  command line is never a substitute for it.
- **the launch evidence** the tool writes beside the ledger: outcome, counts, incident and
  cleanup failures as closed tokens and integers; never an ARN, an identifier or a key.

**Verification identities are their own namespace.** A verification identity carries the
``verify-`` prefix and a production identity may not; a verification task reserves nothing,
so its identity is never spent in the store -- which is exactly why the ledger records it as
consumed: nothing else would stop the same identity from being launched for production later.
Every spent-identity list a production input carries is the ledger's **whole** identity set,
verification rows included.

**A ledger row is completed from a verified receipt or not at all.** The tool records the
exit code it observed through ``DescribeTasks``; the counts reach it only through the task's
receipt line, which -- until the deferred collector exists (ADR-0044 §5) -- the owner reads
from the log stream by hand and hands to the tool for verification against the launch record.
A row whose receipt was never verified is ``EXIT_CODE_ONLY`` evidence and can never enter a
build input.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.production.sharadar.compiled import (
    CompiledConfigurationError,
    parse_compiled_configuration,
)
from kalpamani.data.production.sharadar.compute import (
    CLUSTER_ARN_RE,
    KMS_KEY_ARN_RE,
    PLATFORM_VERSION_RE,
    ROLE_ARN_RE,
    SECURITY_GROUP_ID_RE,
    CompiledLaunch,
)
from kalpamani.data.production.sharadar.documents import (
    decode_document,
    exact_str,
    hex_digest,
    instant,
)
from kalpamani.data.production.sharadar.entry import (
    ENTRY_ACTOR,
    EXIT_STATUS,
    PROBE_ENTRIES,
    PROBE_OUTCOMES,
    VERIFICATION_ENTRIES,
    TaskEntry,
    TaskOutcome,
    entry_family,
)
from kalpamani.data.production.sharadar.inputs import (
    ACQUISITION_INPUT_SCHEMA_VERSION,
    INPUT_SCHEMA_VERSION,
    LEDGER_OUTCOME_COMPLETED,
    LEDGER_OUTCOME_PROBED,
    LEDGER_OUTCOMES,
    MAX_BUILD_RUNS,
    MAX_INPUT_VALIDITY,
    MAX_SPENT_IDENTITIES,
    Slice,
    ledger_digest,
    parse_acquisition_input,
    parse_build_input,
    parse_slice,
    spent_identities_block,
)
from kalpamani.data.production.sharadar.keys import RUN_ID_RE
from kalpamani.data.production.sharadar.metadata_grammar import (
    CODE_COMMIT_RE,
    CONFIGURATION_DIGEST_RE,
    IMAGE_DIGEST_RE,
)
from kalpamani.data.production.sharadar.plan import plan_digest_for
from kalpamani.data.production.sharadar.receipt_collector import (
    CollectorError,
    LogDestination,
    parse_log_destination,
)
from kalpamani.data.production.sharadar.receipts import (
    BOOTSTRAP_REFUSALS,
    LEDGER_OUTCOME_OF,
    PRE_BOOTSTRAP_OUTCOMES,
    ReceiptExpectation,
    VerifiedReceipt,
    ledger_completion,
)
from kalpamani.data.production.sharadar.release import (
    NETWORK_INTERFACE_ID_RE,
    SUBNET_ID_RE,
    TASK_ARN_RE,
    TASK_DEFINITION_ARN_RE,
    ReleaseMode,
)
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for

LEDGER_CONTRACT_ID: Final = "kalpamani-owner-ledger/v1"
LAUNCH_INPUTS_CONTRACT_ID: Final = "kalpamani-launch-inputs/v1"
AUTHORIZATION_CONTRACT_ID: Final = "kalpamani-launch-authorization/v1"
EVIDENCE_CONTRACT_ID: Final = "kalpamani-launch-evidence/v1"
RECORD_SCHEMA_VERSION: Final = 1
#: An owner document is small; a ceiling keeps a mistaken file from being parsed at all.
MAX_RECORD_BYTES: Final = 256 * 1024
#: The reserved prefix of every verification identity. A production identity never has it.
VERIFICATION_IDENTITY_PREFIX: Final = "verify-"
#: A permission-probe launch's identity (ADR-0048): ``probe-<session stamp>``.
PROBE_IDENTITY_PREFIX: Final = "probe-"
#: An authorization is for now: it expires, and a stale one is refused.
MAX_AUTHORIZATION_VALIDITY: Final = timedelta(hours=24)


class LaunchKind(StrEnum):
    """What a launch is for. Closed."""

    PRODUCTION = "production"
    VERIFICATION = "verification"
    PERMISSION_PROBE = "permission-probe"


class LedgerEvidence(StrEnum):
    """How a ledger row's outcome was established. Closed."""

    EXIT_CODE_ONLY = "EXIT_CODE_ONLY"
    RECEIPT_VERIFIED = "RECEIPT_VERIFIED"


class LaunchRecordDefect(StrEnum):
    """Why a record was refused. Closed; carries no value."""

    DOCUMENT_MALFORMED = "DOCUMENT_MALFORMED"
    CONTRACT_UNKNOWN = "CONTRACT_UNKNOWN"
    FIELD_UNKNOWN = "FIELD_UNKNOWN"
    FIELD_MISSING = "FIELD_MISSING"
    FIELD_MALFORMED = "FIELD_MALFORMED"
    IDENTITY_MALFORMED = "IDENTITY_MALFORMED"
    IDENTITY_KIND_MISMATCH = "IDENTITY_KIND_MISMATCH"
    IDENTITY_CONSUMED = "IDENTITY_CONSUMED"
    IDENTITY_DUPLICATE = "IDENTITY_DUPLICATE"
    ROW_NOT_BUILDABLE = "ROW_NOT_BUILDABLE"
    TOO_MANY = "TOO_MANY"
    AUTHORIZATION_MISMATCH = "AUTHORIZATION_MISMATCH"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    ACTOR_MISMATCH = "ACTOR_MISMATCH"
    CONFIGURATION_MISMATCH = "CONFIGURATION_MISMATCH"


class LaunchRecordError(Exception):
    """A refusal built from one closed member and nothing else."""

    __slots__ = ("defect",)

    def __init__(self, defect: LaunchRecordDefect) -> None:
        """Carry the defect."""
        if type(defect) is not LaunchRecordDefect:
            raise TypeError("defect must be an exact LaunchRecordDefect member")
        self.defect = defect
        super().__init__(f"launch record: {defect.value}")


def _refuse(defect: LaunchRecordDefect) -> LaunchRecordError:
    return LaunchRecordError(defect)


def decode_record(raw: object, *, contract_id: str, fields: frozenset[str]) -> dict[str, Any]:
    """One owner record: bounded, strictly decoded, closed shape, the named contract."""
    try:
        document = decode_document(raw, max_bytes=MAX_RECORD_BYTES)
    except Exception:
        raise _refuse(LaunchRecordDefect.DOCUMENT_MALFORMED) from None
    return _closed_record(document, contract_id=contract_id, fields=fields)


def _closed_record(document: object, *, contract_id: str, fields: frozenset[str]) -> dict[str, Any]:
    """An already-decoded object held to a closed shape and the named contract."""
    if type(document) is not dict or not all(type(k) is str for k in document):
        raise _refuse(LaunchRecordDefect.DOCUMENT_MALFORMED)
    names = set(document)
    if names - fields:
        raise _refuse(LaunchRecordDefect.FIELD_UNKNOWN)
    if fields - names:
        raise _refuse(LaunchRecordDefect.FIELD_MISSING)
    if document["schema_version"] != RECORD_SCHEMA_VERSION:
        raise _refuse(LaunchRecordDefect.CONTRACT_UNKNOWN)
    if document["contract_id"] != contract_id:
        raise _refuse(LaunchRecordDefect.CONTRACT_UNKNOWN)
    return document


def _identity(value: object) -> str:
    text = exact_str(value)
    if text is None or not RUN_ID_RE.match(text):
        raise _refuse(LaunchRecordDefect.IDENTITY_MALFORMED)
    return text


def identity_kind(identity: str) -> LaunchKind:
    """The kind an identity's spelling declares: the reserved prefix, or production."""
    if identity.startswith(VERIFICATION_IDENTITY_PREFIX):
        return LaunchKind.VERIFICATION
    if identity.startswith(PROBE_IDENTITY_PREFIX):
        return LaunchKind.PERMISSION_PROBE
    return LaunchKind.PRODUCTION


# ---------------------------------------------------------------------------
# The owner ledger
# ---------------------------------------------------------------------------

_LEDGER_FIELDS: Final[frozenset[str]] = frozenset({"schema_version", "contract_id", "rows"})
_LEDGER_ROW_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "identity",
        "actor",
        "kind",
        "outcome",
        "evidence",
        "launched_at",
        "completed_at",
        "slice",
        "plan_digest",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerLedgerRow:
    """One launched identity. ``slice`` and ``plan_digest`` are ``None`` for a build."""

    identity: str
    actor: ProductionActor
    kind: LaunchKind
    outcome: str
    evidence: LedgerEvidence
    launched_at: datetime
    completed_at: datetime
    slice: Slice | None
    plan_digest: str | None

    @property
    def buildable(self) -> bool:
        """A completed production acquisition whose counts a verified receipt established."""
        return (
            self.kind is LaunchKind.PRODUCTION
            and self.actor is ProductionActor.ACQUISITION
            and self.outcome == LEDGER_OUTCOME_COMPLETED
            and self.evidence is LedgerEvidence.RECEIPT_VERIFIED
            and self.slice is not None
            and self.plan_digest is not None
        )

    def build_input_row(self) -> dict[str, Any]:
        """The accepted build-input ledger row (ADR-0036 §2.6) this row projects to."""
        if not self.buildable:
            raise _refuse(LaunchRecordDefect.ROW_NOT_BUILDABLE)
        assert self.slice is not None and self.plan_digest is not None
        return {
            "run_identity": self.identity,
            "slice": self.slice.canonical(),
            "plan_digest": self.plan_digest,
            "outcome": self.outcome,
            "launched_at": self.launched_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerLedger:
    """Every identity ever launched. Identities are distinct; their kinds match their spelling."""

    rows: tuple[OwnerLedgerRow, ...]

    @property
    def identities(self) -> frozenset[str]:
        """Every consumed identity, production and verification alike."""
        return frozenset(row.identity for row in self.rows)

    def row(self, identity: str) -> OwnerLedgerRow | None:
        """The row for ``identity``, or ``None``."""
        for candidate in self.rows:
            if candidate.identity == identity:
                return candidate
        return None

    def document(self) -> dict[str, Any]:
        """The ledger document, canonical field order."""
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": LEDGER_CONTRACT_ID,
            "rows": [
                {
                    "identity": row.identity,
                    "actor": row.actor.value,
                    "kind": row.kind.value,
                    "outcome": row.outcome,
                    "evidence": row.evidence.value,
                    "launched_at": row.launched_at.isoformat(),
                    "completed_at": row.completed_at.isoformat(),
                    "slice": None if row.slice is None else row.slice.canonical(),
                    "plan_digest": row.plan_digest,
                }
                for row in self.rows
            ],
        }


def _ledger_row(raw: object) -> OwnerLedgerRow:
    if type(raw) is not dict or set(raw) != _LEDGER_ROW_FIELDS:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    identity = _identity(raw["identity"])
    actor_value = exact_str(raw["actor"])
    kind_value = exact_str(raw["kind"])
    outcome = exact_str(raw["outcome"])
    evidence_value = exact_str(raw["evidence"])
    launched_at = instant(raw["launched_at"])
    completed_at = instant(raw["completed_at"])
    if (
        actor_value not in {m.value for m in ProductionActor}
        or kind_value not in {m.value for m in LaunchKind}
        or outcome is None
        or outcome not in LEDGER_OUTCOMES
        or evidence_value not in {m.value for m in LedgerEvidence}
        or launched_at is None
        or completed_at is None
        or completed_at < launched_at
    ):
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    kind = LaunchKind(kind_value)
    if identity_kind(identity) is not kind:
        raise _refuse(LaunchRecordDefect.IDENTITY_KIND_MISMATCH)
    covered: Slice | None = None
    plan_digest: str | None = None
    if raw["slice"] is not None or raw["plan_digest"] is not None:
        # Only an acquisition row covers a slice; a build row carrying one is malformed.
        if ProductionActor(actor_value) is not ProductionActor.ACQUISITION:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
        try:
            covered = parse_slice(raw["slice"])
        except Exception:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED) from None
        plan_digest = hex_digest(raw["plan_digest"])
        if plan_digest is None:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    return OwnerLedgerRow(
        identity=identity,
        actor=ProductionActor(actor_value),
        kind=kind,
        outcome=outcome,
        evidence=LedgerEvidence(evidence_value),
        launched_at=launched_at,
        completed_at=completed_at,
        slice=covered,
        plan_digest=plan_digest,
    )


def parse_owner_ledger(raw: object) -> OwnerLedger:
    """The owner ledger, or refuse. An empty ledger is a valid ledger with no rows."""
    document = decode_record(raw, contract_id=LEDGER_CONTRACT_ID, fields=_LEDGER_FIELDS)
    if type(document["rows"]) is not list:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    rows = tuple(_ledger_row(r) for r in document["rows"])
    if len({row.identity for row in rows}) != len(rows):
        raise _refuse(LaunchRecordDefect.IDENTITY_DUPLICATE)
    return OwnerLedger(rows=rows)


def admit_identity(ledger: OwnerLedger, identity: str, *, kind: LaunchKind) -> str:
    """One identity for one launch of one kind: well-formed, of that kind, never seen."""
    admitted = _identity(identity)
    if identity_kind(admitted) is not kind:
        raise _refuse(LaunchRecordDefect.IDENTITY_KIND_MISMATCH)
    if admitted in ledger.identities:
        raise _refuse(LaunchRecordDefect.IDENTITY_CONSUMED)
    return admitted


# ---------------------------------------------------------------------------
# Input materialization -- the accepted digest functions, nothing restated
# ---------------------------------------------------------------------------


def materialize_acquisition_input(
    ledger: OwnerLedger,
    *,
    identity: str,
    kind: LaunchKind,
    slice_document: object,
    now: datetime,
) -> bytes:
    """The acquisition input v2 bytes for one launch, re-parsed before return.

    The plan digest is computed from the slice with the accepted function; the spent
    block is the ledger's whole identity set (production and verification rows alike),
    so a verification identity can never be reused for production through the
    task-side check either. The admitted input is parsed under the task's own
    contract so the tool cannot write an input the task would refuse.
    """
    admitted = admit_identity(ledger, identity, kind=kind)
    try:
        covered = parse_slice(slice_document)
    except Exception:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED) from None
    spent = sorted(ledger.identities)
    if len(spent) > MAX_SPENT_IDENTITIES:
        raise _refuse(LaunchRecordDefect.TOO_MANY)
    constants = constants_for(ProductionActor.ACQUISITION)
    document = {
        "schema_version": ACQUISITION_INPUT_SCHEMA_VERSION,
        "contract_id": constants.input_contract_id,
        "run_identity": admitted,
        "slice": covered.canonical(),
        "plan_digest": plan_digest_for(
            covered, acquisition_mode=AcquisitionMode(covered.acquisition_mode)
        ),
        "spent_identities": spent_identities_block(spent),
        "issued_at": now.isoformat(),
        "expires_at": (now + MAX_INPUT_VALIDITY).isoformat(),
    }
    parse_acquisition_input(document, now=now)
    return canonical_bytes(document)


def materialize_build_input(
    ledger: OwnerLedger,
    *,
    identity: str,
    kind: LaunchKind,
    run_identities: list[str],
    now: datetime,
) -> bytes:
    """The build input v1 bytes for one launch over completed, receipt-verified rows only.

    A **verification** launch (ADR-0045 s.11) may name no run at all: the verify entry
    terminates at the release barrier and reads nothing, so its input carries an empty
    run set and the ledger digest over ``[]``. A production launch must name at least
    one run, and every run named -- for either kind -- must be a buildable row.
    """
    admitted = admit_identity(ledger, identity, kind=kind)
    if type(run_identities) is not list:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    if not run_identities and kind is not LaunchKind.VERIFICATION:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    if len(run_identities) > MAX_BUILD_RUNS:
        raise _refuse(LaunchRecordDefect.TOO_MANY)
    if len(set(run_identities)) != len(run_identities):
        raise _refuse(LaunchRecordDefect.IDENTITY_DUPLICATE)
    rows: list[dict[str, Any]] = []
    for run_identity in run_identities:
        row = ledger.row(_identity(run_identity))
        if row is None or not row.buildable:
            raise _refuse(LaunchRecordDefect.ROW_NOT_BUILDABLE)
        rows.append(row.build_input_row())
    constants = constants_for(ProductionActor.BUILD)
    document = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "contract_id": constants.input_contract_id,
        "build_identity": admitted,
        "runs": rows,
        "ledger_digest": ledger_digest(rows),
        "issued_at": now.isoformat(),
        "expires_at": (now + MAX_INPUT_VALIDITY).isoformat(),
    }
    parse_build_input(document, now=now, verification_only=kind is LaunchKind.VERIFICATION)
    return canonical_bytes(document)


# ---------------------------------------------------------------------------
# The launch inputs record -> CompiledLaunch
# ---------------------------------------------------------------------------

_LAUNCH_INPUTS_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "cluster_arn",
        "execution_role_arn",
        "binding_key_arn",
        "platform_version",
        "r3_verification_digest",
        "actors",
    }
)
_LAUNCH_ACTOR_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "task_role_arn",
        "subnet_id",
        "security_group_ids",
        "production",
        "verification",
    }
)
_LAUNCH_TARGET_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "task_definition_arn",
        "image_digest",
        "configuration_digest",
        "code_commit",
        "generation_record_digest",
        "task_definition",
    }
)
_TASK_DEFINITION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "family",
        "revision",
        "task_role_arn",
        "execution_role_arn",
        "cpu",
        "memory",
        "network_mode",
        "operating_system_family",
        "cpu_architecture",
        "user",
        "readonly_root_filesystem",
        "work_tmpfs",
        "command",
        "image_digest",
    }
)
#: The fields of the registered task-definition evidence that a verification family
#: must share with its production family (roles, size, network mode, platform, user,
#: read-only root, ``/work`` tmpfs) -- and the ones that differ by design: ``family``,
#: ``revision``, ``command`` and ``image_digest``.
TASK_DEFINITION_SHARED_FIELDS: Final[tuple[str, ...]] = (
    "task_role_arn",
    "execution_role_arn",
    "cpu",
    "memory",
    "network_mode",
    "operating_system_family",
    "cpu_architecture",
    "user",
    "readonly_root_filesystem",
    "work_tmpfs",
)
TASK_DEFINITION_INTENTIONAL_DIFFERENCES: Final[tuple[str, ...]] = (
    "family",
    "revision",
    "command",
    "image_digest",
)
_TASK_USER: Final = "10001:10001"
#: The one optional key of the task-definition evidence (ADR-0049): the registered
#: log destination the receipt collector derives a task's stream from. A registration made
#: before the collector existed stays valid; the collector refuses until one is registered.
_TASK_DEFINITION_OPTIONAL_FIELDS: Final[frozenset[str]] = frozenset({"log_destination"})


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskDefinitionEvidence:
    """The owner's transcription of one registered task-definition revision.

    **Owner-supplied evidence, validated offline.** The launcher permission sets hold
    no ``ecs:DescribeTaskDefinition`` (ADR-0036 §2.9 scopes them to ``RunTask``,
    ``DescribeTasks`` and ``StopTask``), so the tool cannot read a revision back; the
    owner transcribes it from the post-apply verification, and the tool holds every
    field to its grammar and to the compiled launch. **That a transcription is faithful
    is not something this tool can establish.**
    """

    family: str
    revision: int
    task_role_arn: str
    execution_role_arn: str
    cpu: int
    memory: int
    network_mode: str
    operating_system_family: str
    cpu_architecture: str
    user: str
    readonly_root_filesystem: bool
    work_tmpfs: bool
    command: str
    image_digest: str
    #: The registered log destination (ADR-0049): the group and stream prefix the
    #: owner transcribed from the applied revision, and the container name; ``None`` for a
    #: registration made before the collector existed.
    log_destination: LogDestination | None = None

    def document(self) -> dict[str, Any]:
        """The closed block (the optional destination present only when registered)."""
        document = {name: getattr(self, name) for name in sorted(_TASK_DEFINITION_FIELDS)}
        if self.log_destination is not None:
            document["log_destination"] = self.log_destination.document()
        return document

    def __repr__(self) -> str:
        """Family and revision only."""
        return f"TaskDefinitionEvidence(family={self.family!r}, revision={self.revision})"


@dataclass(frozen=True, slots=True, kw_only=True)
class LaunchTarget:
    """One registered revision with the image, configuration and generation records behind it.

    ``generation_record_digest`` is the SHA-256 of the image gate's generation record for
    this target (an owner-held evidence reference: the tool checks its grammar and that
    the authorization names the same one, and cannot establish that the record exists).
    """

    task_definition_arn: str
    image_digest: str
    configuration_digest: str
    code_commit: str
    generation_record_digest: str
    task_definition: TaskDefinitionEvidence

    @property
    def family(self) -> str:
        """The family the revision ARN names."""
        match = TASK_DEFINITION_ARN_RE.fullmatch(self.task_definition_arn)
        assert match is not None
        return match.group(2)

    @property
    def revision(self) -> int:
        """The revision the ARN names."""
        match = TASK_DEFINITION_ARN_RE.fullmatch(self.task_definition_arn)
        assert match is not None
        return int(match.group(3))

    def document(self) -> dict[str, Any]:
        """The closed block."""
        return {
            "task_definition_arn": self.task_definition_arn,
            "image_digest": self.image_digest,
            "configuration_digest": self.configuration_digest,
            "code_commit": self.code_commit,
            "generation_record_digest": self.generation_record_digest,
            "task_definition": self.task_definition.document(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class LaunchInputs:
    """Everything the tool compiles launches from, per actor and kind.

    ``r3_verification_digest`` is the stage-b prerequisite's evidence reference (the
    SHA-256 of the owner's R-3 record, as ``terraform.tfvars`` carries it), or ``None``
    at stage a. It is **applicable to a production launch** -- the assignments the human
    and launcher sets need exist only at stage b -- and not to a verification launch.
    """

    cluster_arn: str
    execution_role_arn: str
    binding_key_arn: str
    platform_version: str
    r3_verification_digest: str | None
    task_role_arns: dict[ProductionActor, str]
    subnet_ids: dict[ProductionActor, str]
    security_group_ids: dict[ProductionActor, tuple[str, ...]]
    targets: dict[tuple[ProductionActor, LaunchKind], LaunchTarget]

    def __repr__(self) -> str:
        """Nothing that is an identifier."""
        return "LaunchInputs()"


def _task_definition(raw: object) -> TaskDefinitionEvidence:
    if (
        type(raw) is not dict
        or not _TASK_DEFINITION_FIELDS <= set(raw)
        or not set(raw) <= _TASK_DEFINITION_FIELDS | _TASK_DEFINITION_OPTIONAL_FIELDS
    ):
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    destination: LogDestination | None = None
    if "log_destination" in raw:
        try:
            destination = parse_log_destination(raw["log_destination"])
        except CollectorError:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED) from None
    family = exact_str(raw["family"])
    revision = raw["revision"]
    task_role = exact_str(raw["task_role_arn"])
    execution_role = exact_str(raw["execution_role_arn"])
    cpu, memory = raw["cpu"], raw["memory"]
    network_mode = exact_str(raw["network_mode"])
    os_family = exact_str(raw["operating_system_family"])
    architecture = exact_str(raw["cpu_architecture"])
    user = exact_str(raw["user"])
    readonly, tmpfs = raw["readonly_root_filesystem"], raw["work_tmpfs"]
    command = exact_str(raw["command"])
    image = exact_str(raw["image_digest"])
    if (
        family is None
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", family)
        or type(revision) is not int
        or revision < 1
        or task_role is None
        or ROLE_ARN_RE.fullmatch(task_role) is None
        or execution_role is None
        or ROLE_ARN_RE.fullmatch(execution_role) is None
        or type(cpu) is not int
        or cpu <= 0
        or type(memory) is not int
        or memory <= 0
        or network_mode != "awsvpc"
        or os_family != "LINUX"
        or architecture != "X86_64"
        or user != _TASK_USER
        or type(readonly) is not bool
        or type(tmpfs) is not bool
        or command is None
        or command not in {member.value for member in TaskEntry}
        or image is None
        or IMAGE_DIGEST_RE.fullmatch(image) is None
    ):
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    return TaskDefinitionEvidence(
        family=family,
        revision=revision,
        task_role_arn=task_role,
        execution_role_arn=execution_role,
        cpu=cpu,
        memory=memory,
        network_mode=network_mode,
        operating_system_family=os_family,
        cpu_architecture=architecture,
        user=user,
        readonly_root_filesystem=readonly,
        work_tmpfs=tmpfs,
        command=command,
        image_digest=image,
        log_destination=destination,
    )


def _target(raw: object) -> LaunchTarget | None:
    if raw is None:
        return None
    if type(raw) is not dict or set(raw) != _LAUNCH_TARGET_FIELDS:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    definition = exact_str(raw["task_definition_arn"])
    image = exact_str(raw["image_digest"])
    configuration = exact_str(raw["configuration_digest"])
    commit = exact_str(raw["code_commit"])
    generation = hex_digest(raw["generation_record_digest"])
    if (
        definition is None
        or TASK_DEFINITION_ARN_RE.fullmatch(definition) is None
        or image is None
        or IMAGE_DIGEST_RE.fullmatch(image) is None
        or configuration is None
        or CONFIGURATION_DIGEST_RE.fullmatch(configuration) is None
        or commit is None
        or CODE_COMMIT_RE.fullmatch(commit) is None
        or generation is None
    ):
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    target = LaunchTarget(
        task_definition_arn=definition,
        image_digest=image,
        configuration_digest=configuration,
        code_commit=commit,
        generation_record_digest=generation,
        task_definition=_task_definition(raw["task_definition"]),
    )
    # The transcribed revision is the registered one: family, revision, image and the
    # command token all agree with the ARN and the target, or the evidence is not this
    # target's.
    evidence = target.task_definition
    if (
        evidence.family != target.family
        or evidence.revision != target.revision
        or evidence.image_digest != target.image_digest
        or evidence.command != target.family
    ):
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    return target


def parse_launch_inputs(raw: object) -> LaunchInputs:
    """The launch inputs record, every identifier held to the compiled-launch grammars."""
    document = decode_record(
        raw, contract_id=LAUNCH_INPUTS_CONTRACT_ID, fields=_LAUNCH_INPUTS_FIELDS
    )
    cluster = exact_str(document["cluster_arn"])
    execution = exact_str(document["execution_role_arn"])
    key = exact_str(document["binding_key_arn"])
    platform = exact_str(document["platform_version"])
    r3 = document["r3_verification_digest"]
    if (
        cluster is None
        or CLUSTER_ARN_RE.fullmatch(cluster) is None
        or execution is None
        or ROLE_ARN_RE.fullmatch(execution) is None
        or key is None
        or KMS_KEY_ARN_RE.fullmatch(key) is None
        or platform is None
        or PLATFORM_VERSION_RE.fullmatch(platform) is None
        or platform == "LATEST"
        or (r3 is not None and hex_digest(r3) is None)
    ):
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    actors = document["actors"]
    if type(actors) is not dict or set(actors) != {m.value for m in ProductionActor}:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    task_roles: dict[ProductionActor, str] = {}
    subnets: dict[ProductionActor, str] = {}
    groups: dict[ProductionActor, tuple[str, ...]] = {}
    targets: dict[tuple[ProductionActor, LaunchKind], LaunchTarget] = {}
    for actor in ProductionActor:
        block = actors[actor.value]
        # ``permission_probe`` (ADR-0048) is the one optional key: a registration
        # made before the probe family existed stays a valid registration without it.
        if type(block) is not dict or set(block) - {"permission_probe"} != _LAUNCH_ACTOR_FIELDS:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
        role = exact_str(block["task_role_arn"])
        subnet = exact_str(block["subnet_id"])
        if (
            role is None
            or ROLE_ARN_RE.fullmatch(role) is None
            or subnet is None
            or SUBNET_ID_RE.fullmatch(subnet) is None
        ):
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
        raw_groups = block["security_group_ids"]
        if type(raw_groups) is not list or not raw_groups:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
        for group in raw_groups:
            if type(group) is not str or SECURITY_GROUP_ID_RE.fullmatch(group) is None:
                raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
        task_roles[actor] = role
        subnets[actor] = subnet
        groups[actor] = tuple(raw_groups)
        for kind, field in (
            (LaunchKind.PRODUCTION, "production"),
            (LaunchKind.VERIFICATION, "verification"),
            (LaunchKind.PERMISSION_PROBE, "permission_probe"),
        ):
            target = _target(block.get(field))
            if target is None:
                continue
            expected = {
                LaunchKind.PRODUCTION: constants_for(actor).task_family,
                LaunchKind.VERIFICATION: constants_for(actor).verification_task_family,
                LaunchKind.PERMISSION_PROBE: constants_for(actor).probe_task_family,
            }[kind]
            if target.family != expected:
                raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
            # The registered roles are this actor's and the shared execution role.
            if (
                target.task_definition.task_role_arn != role
                or target.task_definition.execution_role_arn != execution
            ):
                raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
            targets[(actor, kind)] = target
    return LaunchInputs(
        cluster_arn=cluster,
        execution_role_arn=execution,
        binding_key_arn=key,
        platform_version=platform,
        r3_verification_digest=r3,
        task_role_arns=task_roles,
        subnet_ids=subnets,
        security_group_ids=groups,
        targets=targets,
    )


def compile_launch(
    inputs: LaunchInputs, *, actor: ProductionActor, kind: LaunchKind
) -> tuple[CompiledLaunch, LaunchTarget]:
    """The compiled launch of one actor and kind, or refuse when no target is registered."""
    target = inputs.targets.get((actor, kind))
    if target is None:
        raise _refuse(LaunchRecordDefect.FIELD_MISSING)
    compiled = CompiledLaunch(
        actor=actor,
        cluster_arn=inputs.cluster_arn,
        task_definition_arn=target.task_definition_arn,
        image_digest=target.image_digest,
        configuration_digest=target.configuration_digest,
        task_role_arn=inputs.task_role_arns[actor],
        execution_role_arn=inputs.execution_role_arn,
        subnet_id=inputs.subnet_ids[actor],
        security_group_ids=inputs.security_group_ids[actor],
        assign_public_ip=actor is ProductionActor.ACQUISITION,
        platform_version=inputs.platform_version,
        binding_key_arn=inputs.binding_key_arn,
    )
    if compiled.verification != (kind is LaunchKind.VERIFICATION):
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    if compiled.probe != (kind is LaunchKind.PERMISSION_PROBE):
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    return compiled, target


# ---------------------------------------------------------------------------
# Configuration equivalence -- verification versus production, bound to the registered targets
# ---------------------------------------------------------------------------


class EquivalenceVerdict(StrEnum):
    """Whether a verification image's configuration stands for the production one.

    ``EQUIVALENT`` is a statement about **configuration**: the two registered files
    agree on what a verification task can check. It is never runtime proof -- the
    production image's bytes, its processing path and every field only a production
    entry reads (the secret name, the build configuration) are exercised by nothing but
    a production run.
    """

    EQUIVALENT = "EQUIVALENT"
    UNREADABLE = "UNREADABLE"
    TARGET_MISMATCH = "TARGET_MISMATCH"
    ENTRY_MISMATCH = "ENTRY_MISMATCH"
    CODE_DIFFERS = "CODE_DIFFERS"
    ORIGIN_DIFFERS = "ORIGIN_DIFFERS"
    TASK_DEFINITION_DIFFERS = "TASK_DEFINITION_DIFFERS"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"


def _bound_to_target(raw: bytes, target: LaunchTarget, entry: TaskEntry) -> Any:
    """The parsed configuration, or the verdict that refuses it against its target."""
    try:
        parsed, digest = parse_compiled_configuration(raw)
    except CompiledConfigurationError:
        return EquivalenceVerdict.UNREADABLE
    if parsed.entry is not entry:
        return EquivalenceVerdict.ENTRY_MISMATCH
    if digest != target.configuration_digest or parsed.compiled.code_commit != target.code_commit:
        return EquivalenceVerdict.TARGET_MISMATCH
    if parsed.compiled.family != target.family:
        return EquivalenceVerdict.TARGET_MISMATCH
    return parsed


def configuration_equivalence(
    inputs: LaunchInputs,
    *,
    actor: ProductionActor,
    production: bytes,
    verification: bytes,
    acquisition: bytes | None = None,
) -> EquivalenceVerdict:
    """Compare the registered verification configuration with its production counterpart.

    Every file is first bound to **its own registered target** (digest, commit, entry,
    family): the production file to the actor's production target, the verification
    file to its verification target, and -- for a build pair -- the acquisition file to
    the acquisition production target, because the build verification image carries the
    acquisition origin set and the production build file carries none. Then the two
    registered task-definition revisions are compared field by field: roles, cpu,
    memory, network mode, platform, user, read-only root and the ``/work`` tmpfs must
    agree; family, revision, command and image digest differ by design. Then the
    configurations: the same code commit; the verification origin set equal to the
    acquisition set. **Anything else refuses**; a missing registered target or its
    task-definition evidence is ``EVIDENCE_MISSING``. Nothing here reads a secret name
    or a build configuration into the verdict, and the verdict is never runtime proof.
    """
    production_target = inputs.targets.get((actor, LaunchKind.PRODUCTION))
    verification_target = inputs.targets.get((actor, LaunchKind.VERIFICATION))
    acquisition_target = inputs.targets.get((ProductionActor.ACQUISITION, LaunchKind.PRODUCTION))
    if production_target is None or verification_target is None:
        return EquivalenceVerdict.EVIDENCE_MISSING
    production_entry = (
        TaskEntry.ACQUISITION if actor is ProductionActor.ACQUISITION else TaskEntry.BUILD
    )
    verification_entry = (
        TaskEntry.ACQUISITION_VERIFY
        if actor is ProductionActor.ACQUISITION
        else TaskEntry.BUILD_VERIFY
    )
    prod = _bound_to_target(production, production_target, production_entry)
    if isinstance(prod, EquivalenceVerdict):
        return prod
    verify = _bound_to_target(verification, verification_target, verification_entry)
    if isinstance(verify, EquivalenceVerdict):
        return verify
    if prod.compiled.code_commit != verify.compiled.code_commit:
        return EquivalenceVerdict.CODE_DIFFERS
    # The registered task definitions: shared fields equal, intentional differences only.
    production_evidence = production_target.task_definition
    verification_evidence = verification_target.task_definition
    for name in TASK_DEFINITION_SHARED_FIELDS:
        if getattr(production_evidence, name) != getattr(verification_evidence, name):
            return EquivalenceVerdict.TASK_DEFINITION_DIFFERS
    if (
        verification_evidence.family != constants_for(actor).verification_task_family
        or production_evidence.family != constants_for(actor).task_family
        or verification_evidence.command != verification_entry.value
        or production_evidence.command != production_entry.value
    ):
        return EquivalenceVerdict.TASK_DEFINITION_DIFFERS
    # The origin set the verification image probes or checks is the acquisition's.
    if actor is ProductionActor.ACQUISITION:
        origin = prod.origin_addresses
    else:
        if acquisition is None or acquisition_target is None:
            return EquivalenceVerdict.EVIDENCE_MISSING
        acquired = _bound_to_target(acquisition, acquisition_target, TaskEntry.ACQUISITION)
        if isinstance(acquired, EquivalenceVerdict):
            return acquired
        if acquired.compiled.code_commit != prod.compiled.code_commit:
            return EquivalenceVerdict.CODE_DIFFERS
        origin = acquired.origin_addresses
    if verify.origin_addresses != origin:
        return EquivalenceVerdict.ORIGIN_DIFFERS
    return EquivalenceVerdict.EQUIVALENT


# ---------------------------------------------------------------------------
# The launch specification -- what an authorization binds
# ---------------------------------------------------------------------------

SPECIFICATION_CONTRACT_ID: Final = "kalpamani-launch-specification/v1"


@dataclass(frozen=True, slots=True, kw_only=True)
class LaunchSpecification:
    """The canonical, reviewable statement of one launch: what an authorization binds.

    Built by preparation from the admitted records and rebuilt identically at execution,
    so the authorization's ``specification_digest`` binds exactly what will run:

    - actor, kind, identity and entry;
    - the **workload** -- the acquisition slice and its plan digest, or the selected
      build runs with the ledger evidence each carried (identity, plan digest, outcome,
      evidence, completion instant);
    - the **target** -- revision ARN, image digest, configuration digest, code commit,
      the generation-record reference and the task-definition evidence;
    - the **placement** -- cluster, subnet, security groups, public-IP setting, task and
      execution roles, platform version, binding key;
    - the **gate evidence** -- the R-3 verification digest and whether it applies.

    **Excluded on purpose**: the input's issue and expiry instants and the ledger's
    spent-identity set. The digest is over what is authorized, not over when the input
    was cut; a ledger that grows between preparation and execution changes the spent
    block and nothing the owner authorized, while a change to a selected build run's
    own evidence changes the workload and refuses.
    """

    actor: ProductionActor
    kind: LaunchKind
    identity: str
    entry: TaskEntry
    workload: dict[str, Any]
    target: LaunchTarget
    placement: dict[str, Any]
    gate_evidence: dict[str, Any]
    #: The release behaviour the owner authorizes with this specification; a negative
    #: mode is admissible for a verification launch only (ADR-0047).
    release_mode: ReleaseMode = ReleaseMode.NORMAL

    def __post_init__(self) -> None:
        """A negative release mode names a verification launch and nothing else."""
        if type(self.release_mode) is not ReleaseMode:
            raise TypeError("release_mode must be an exact ReleaseMode")
        if self.release_mode is not ReleaseMode.NORMAL and self.kind is not LaunchKind.VERIFICATION:
            raise ValueError("a negative release mode is a verification launch's alone")

    def document(self) -> dict[str, Any]:
        """The canonical document."""
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": SPECIFICATION_CONTRACT_ID,
            "actor": self.actor.value,
            "kind": self.kind.value,
            "identity": self.identity,
            "entry": self.entry.value,
            "workload": self.workload,
            "target": self.target.document(),
            "placement": dict(self.placement),
            "gate_evidence": dict(self.gate_evidence),
            "release_mode": self.release_mode.value,
        }

    @property
    def digest(self) -> str:
        """The SHA-256 of the canonical document -- the value an authorization names."""
        return sha256_hex(canonical_bytes(self.document()))

    @property
    def compiled(self) -> CompiledLaunch:
        """The compiled launch this specification names: its placement over its target.

        The same object :func:`compile_launch` produced at preparation, rebuilt from the
        specification alone -- which is what lets a later mode (recovery, the verdict)
        take the placement from the reservation's specification rather than from a
        freshly supplied launch-inputs file.
        """
        return CompiledLaunch(
            actor=self.actor,
            cluster_arn=self.placement["cluster_arn"],
            task_definition_arn=self.target.task_definition_arn,
            image_digest=self.target.image_digest,
            configuration_digest=self.target.configuration_digest,
            task_role_arn=self.placement["task_role_arn"],
            execution_role_arn=self.placement["execution_role_arn"],
            subnet_id=self.placement["subnet_id"],
            security_group_ids=tuple(self.placement["security_group_ids"]),
            assign_public_ip=self.placement["assign_public_ip"],
            platform_version=self.placement["platform_version"],
            binding_key_arn=self.placement["binding_key_arn"],
        )

    def __repr__(self) -> str:
        """Actor, kind and entry only."""
        return (
            f"LaunchSpecification(actor={self.actor.value!r}, kind={self.kind.value!r}, "
            f"entry={self.entry.value!r})"
        )


_SPECIFICATION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "actor",
        "kind",
        "identity",
        "entry",
        "workload",
        "target",
        "placement",
        "gate_evidence",
        "release_mode",
    }
)
_PLACEMENT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "cluster_arn",
        "subnet_id",
        "security_group_ids",
        "assign_public_ip",
        "task_role_arn",
        "execution_role_arn",
        "platform_version",
        "binding_key_arn",
    }
)
_GATE_EVIDENCE_FIELDS: Final[frozenset[str]] = frozenset(
    {"r3_verification_digest", "r3_applicable", "generation_record_digest"}
)
_WORKLOAD_RUN_FIELDS: Final[frozenset[str]] = frozenset(
    {"identity", "plan_digest", "outcome", "evidence", "completed_at"}
)
#: A permission-probe launch's workload (ADR-0048): the subcell the probe answers
#: and the workstation chain it was launched for -- the statement, the attempt, the session
#: stamp and its ``startedBy`` tag, the hold, and the digest of the probe input the launcher
#: materializes. Reserved beside the ledger **before** ``RunTask``, so an interrupted probe
#: launch is attributable to its attempt from the reservation alone.
_PROBE_WORKLOAD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "subcell_id",
        "statement_sha256",
        "attempt_sha256",
        "stamp",
        "started_by",
        "hold_seconds",
        "input_digest",
    }
)
_PROBE_STAMP_RE: Final = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{4}")
_PROBE_SUBCELL_RE: Final = re.compile(r"R[4-9]-[A-Z0-9-]{1,60}")
#: The ``startedBy`` tag of a permission session (``permission_cells.started_by_of``).
PROBE_STARTED_BY_PREFIX: Final = "kalpamani-permission-"
#: A held probe's ceiling (``permission_probe.PROBE_HOLD_CEILING_SECONDS``), restated here
#: because this module cannot import the probe contracts (they import the catalogue).
_PROBE_HOLD_CEILING_SECONDS: Final = 600


def _probe_workload(workload: dict[str, Any]) -> dict[str, Any]:
    """A probe workload to its grammar, canonical, or refuse."""
    if set(workload) != _PROBE_WORKLOAD_FIELDS:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    subcell_id = exact_str(workload["subcell_id"])
    stamp = exact_str(workload["stamp"])
    started_by = exact_str(workload["started_by"])
    hold = workload["hold_seconds"]
    digests = {
        name: hex_digest(workload[name])
        for name in ("statement_sha256", "attempt_sha256", "input_digest")
    }
    if (
        subcell_id is None
        or _PROBE_SUBCELL_RE.fullmatch(subcell_id) is None
        or stamp is None
        or _PROBE_STAMP_RE.fullmatch(stamp) is None
        or started_by != PROBE_STARTED_BY_PREFIX + stamp
        or type(hold) is not int
        or hold < 0
        or hold > _PROBE_HOLD_CEILING_SECONDS
        or any(value is None for value in digests.values())
    ):
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    return {
        "subcell_id": subcell_id,
        "statement_sha256": digests["statement_sha256"],
        "attempt_sha256": digests["attempt_sha256"],
        "stamp": stamp,
        "started_by": started_by,
        "hold_seconds": hold,
        "input_digest": digests["input_digest"],
    }


def parse_specification(raw: object) -> LaunchSpecification:
    """A launch specification document, every block to its grammar, or refuse.

    The workload is re-validated the way :func:`build_specification` built it (the slice
    through the accepted parser with its plan digest recomputed; the build runs as closed
    rows), the target through the launch-inputs target parser, the placement by building
    the :class:`CompiledLaunch` it names, and the gate evidence against the kind. A
    document that parses is exactly one :func:`build_specification` could have produced,
    so its digest is the digest an authorization named.
    """
    # Embedded in a reservation the document arrives already decoded (the reservation's
    # own decoding refused duplicate keys); on its own it arrives as bytes.
    document = (
        _closed_record(raw, contract_id=SPECIFICATION_CONTRACT_ID, fields=_SPECIFICATION_FIELDS)
        if type(raw) is dict
        else decode_record(raw, contract_id=SPECIFICATION_CONTRACT_ID, fields=_SPECIFICATION_FIELDS)
    )
    actor_value = exact_str(document["actor"])
    kind_value = exact_str(document["kind"])
    entry_value = exact_str(document["entry"])
    if (
        actor_value not in {m.value for m in ProductionActor}
        or kind_value not in {m.value for m in LaunchKind}
        or entry_value not in {m.value for m in TaskEntry}
    ):
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    actor = ProductionActor(actor_value)
    kind = LaunchKind(kind_value)
    entry = TaskEntry(entry_value)
    if ENTRY_ACTOR[entry] is not actor or (entry in VERIFICATION_ENTRIES) != (
        kind is LaunchKind.VERIFICATION
    ):
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    identity = _identity(document["identity"])
    if identity_kind(identity) is not kind:
        raise _refuse(LaunchRecordDefect.IDENTITY_KIND_MISMATCH)
    mode_value = exact_str(document["release_mode"])
    if mode_value not in {m.value for m in ReleaseMode}:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    release_mode = ReleaseMode(mode_value)
    if release_mode is not ReleaseMode.NORMAL and kind is not LaunchKind.VERIFICATION:
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    target = _target(document["target"])
    if target is None:
        raise _refuse(LaunchRecordDefect.FIELD_MISSING)
    workload = document["workload"]
    if type(workload) is not dict:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    if (entry in PROBE_ENTRIES) != (kind is LaunchKind.PERMISSION_PROBE):
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    if kind is LaunchKind.PERMISSION_PROBE:
        canonical_workload: dict[str, Any] = _probe_workload(workload)
    elif actor is ProductionActor.ACQUISITION:
        if set(workload) != {"slice", "plan_digest"}:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
        try:
            covered = parse_slice(workload["slice"])
            expected = plan_digest_for(
                covered, acquisition_mode=AcquisitionMode(covered.acquisition_mode)
            )
        except Exception:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED) from None
        if workload["plan_digest"] != expected or workload["slice"] != covered.canonical():
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
        canonical_workload = {"slice": covered.canonical(), "plan_digest": expected}
    else:
        runs = workload.get("runs")
        if set(workload) != {"runs"} or type(runs) is not list or not runs:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
        seen: set[str] = set()
        canonical_runs: list[dict[str, Any]] = []
        for run in runs:
            if type(run) is not dict or set(run) != _WORKLOAD_RUN_FIELDS:
                raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
            run_identity = _identity(run["identity"])
            plan = hex_digest(run["plan_digest"])
            outcome = exact_str(run["outcome"])
            evidence = exact_str(run["evidence"])
            completed_at = instant(run["completed_at"])
            if (
                plan is None
                or outcome not in LEDGER_OUTCOMES
                or evidence not in {m.value for m in LedgerEvidence}
                or completed_at is None
            ):
                raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
            if run_identity in seen:
                raise _refuse(LaunchRecordDefect.IDENTITY_DUPLICATE)
            seen.add(run_identity)
            canonical_runs.append(
                {
                    "identity": run_identity,
                    "plan_digest": plan,
                    "outcome": outcome,
                    "evidence": evidence,
                    "completed_at": completed_at.isoformat(),
                }
            )
        canonical_workload = {"runs": canonical_runs}
    placement = document["placement"]
    if type(placement) is not dict or set(placement) != _PLACEMENT_FIELDS:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    groups = placement["security_group_ids"]
    if (
        type(groups) is not list
        or any(type(group) is not str for group in groups)
        or len(set(groups)) != len(groups)
        or any(
            type(placement[key]) is not str
            for key in _PLACEMENT_FIELDS - {"security_group_ids", "assign_public_ip"}
        )
        or type(placement["assign_public_ip"]) is not bool
    ):
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    canonical_placement = {key: placement[key] for key in _PLACEMENT_FIELDS}
    canonical_placement["security_group_ids"] = list(groups)
    gate = document["gate_evidence"]
    if type(gate) is not dict or set(gate) != _GATE_EVIDENCE_FIELDS:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    applicable = kind is LaunchKind.PRODUCTION
    r3 = gate["r3_verification_digest"]
    if (
        gate["r3_applicable"] is not applicable
        or (applicable and hex_digest(r3) is None)
        or (not applicable and r3 is not None)
        or gate["generation_record_digest"] != target.generation_record_digest
    ):
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    specification = LaunchSpecification(
        actor=actor,
        kind=kind,
        identity=identity,
        entry=entry,
        workload=canonical_workload,
        target=target,
        placement=canonical_placement,
        gate_evidence={
            "r3_verification_digest": r3,
            "r3_applicable": applicable,
            "generation_record_digest": target.generation_record_digest,
        },
        release_mode=release_mode,
    )
    try:
        compiled = specification.compiled
    except (TypeError, ValueError):
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED) from None
    if compiled.verification != (kind is LaunchKind.VERIFICATION):
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    if compiled.probe != (kind is LaunchKind.PERMISSION_PROBE):
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    return specification


def build_specification(
    *,
    ledger: OwnerLedger,
    inputs: LaunchInputs,
    actor: ProductionActor,
    kind: LaunchKind,
    identity: str,
    slice_document: object | None,
    run_identities: list[str] | None,
    release_mode: ReleaseMode = ReleaseMode.NORMAL,
) -> LaunchSpecification:
    """The specification of one launch from the admitted records, or refuse.

    The workload is validated the way the input will be: the slice through the accepted
    parser with its plan digest computed by the accepted function; the build runs
    through the same buildable-row rule the input materialization applies. A negative
    ``release_mode`` is admitted for a verification launch only.
    """
    if type(release_mode) is not ReleaseMode:
        raise TypeError("release_mode must be an exact ReleaseMode")
    if release_mode is not ReleaseMode.NORMAL and kind is not LaunchKind.VERIFICATION:
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    if kind is LaunchKind.PERMISSION_PROBE:
        # A probe launch's workload is a permission chain, not a slice or a run set.
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    admitted = admit_identity(ledger, identity, kind=kind)
    compiled, target = compile_launch(inputs, actor=actor, kind=kind)
    if actor is ProductionActor.ACQUISITION:
        if slice_document is None or run_identities is not None:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
        try:
            covered = parse_slice(slice_document)
        except Exception:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED) from None
        entry = (
            TaskEntry.ACQUISITION if kind is LaunchKind.PRODUCTION else TaskEntry.ACQUISITION_VERIFY
        )
        workload: dict[str, Any] = {
            "slice": covered.canonical(),
            "plan_digest": plan_digest_for(
                covered, acquisition_mode=AcquisitionMode(covered.acquisition_mode)
            ),
        }
    else:
        if run_identities is None or slice_document is not None:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
        if type(run_identities) is not list:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
        if not run_identities and kind is not LaunchKind.VERIFICATION:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)  # ADR-0045 s.11
        if len(set(run_identities)) != len(run_identities):
            raise _refuse(LaunchRecordDefect.IDENTITY_DUPLICATE)
        runs: list[dict[str, Any]] = []
        for run_identity in run_identities:
            row = ledger.row(_identity(run_identity))
            if row is None or not row.buildable:
                raise _refuse(LaunchRecordDefect.ROW_NOT_BUILDABLE)
            runs.append(
                {
                    "identity": row.identity,
                    "plan_digest": row.plan_digest,
                    "outcome": row.outcome,
                    "evidence": row.evidence.value,
                    "completed_at": row.completed_at.isoformat(),
                }
            )
        entry = TaskEntry.BUILD if kind is LaunchKind.PRODUCTION else TaskEntry.BUILD_VERIFY
        workload = {"runs": runs}
    placement = {
        "cluster_arn": compiled.cluster_arn,
        "subnet_id": compiled.subnet_id,
        "security_group_ids": list(compiled.security_group_ids),
        "assign_public_ip": compiled.assign_public_ip,
        "task_role_arn": compiled.task_role_arn,
        "execution_role_arn": compiled.execution_role_arn,
        "platform_version": compiled.platform_version,
        "binding_key_arn": compiled.binding_key_arn,
    }
    # The R-3 digest applies to a production launch (stage b); a verification launch
    # at stage a has none to name. Its presence is a reference to owner-held evidence,
    # not proof that the verification occurred.
    applicable = kind is LaunchKind.PRODUCTION
    if applicable and inputs.r3_verification_digest is None:
        raise _refuse(LaunchRecordDefect.FIELD_MISSING)
    gate_evidence = {
        "r3_verification_digest": inputs.r3_verification_digest if applicable else None,
        "r3_applicable": applicable,
        "generation_record_digest": target.generation_record_digest,
    }
    return LaunchSpecification(
        actor=actor,
        kind=kind,
        identity=admitted,
        entry=entry,
        workload=workload,
        target=target,
        placement=placement,
        gate_evidence=gate_evidence,
        release_mode=release_mode,
    )


def probe_specification(
    *,
    ledger: OwnerLedger,
    inputs: LaunchInputs,
    actor: ProductionActor,
    identity: str,
    subcell_id: str,
    statement_sha256: str,
    attempt_sha256: str,
    stamp: str,
    hold_seconds: int,
    input_digest: str,
) -> LaunchSpecification:
    """The specification of one permission-probe launch (ADR-0048), or refuse.

    What the permission tool reserves beside the ledger **before** ``RunTask``: the
    actor's registered probe target and placement, and the workload that attributes the
    launch to its permission chain -- the subcell, the prepared statement, the written
    attempt, the session stamp with its ``startedBy`` tag, the hold and the digest of the
    materialized probe input. A launch record of the probe kind names this
    specification's digest, and binds to the reservation through
    :func:`~kalpamani.data.production.sharadar.launch_store.bind_record` exactly as
    every other launch does; an interrupted launch is attributable -- to its attempt,
    its tag and its cluster -- from the reservation alone.
    """
    admitted = admit_identity(ledger, identity, kind=LaunchKind.PERMISSION_PROBE)
    compiled, target = compile_launch(inputs, actor=actor, kind=LaunchKind.PERMISSION_PROBE)
    workload = _probe_workload(
        {
            "subcell_id": subcell_id,
            "statement_sha256": statement_sha256,
            "attempt_sha256": attempt_sha256,
            "stamp": stamp,
            "started_by": PROBE_STARTED_BY_PREFIX + stamp,
            "hold_seconds": hold_seconds,
            "input_digest": input_digest,
        }
    )
    entry = (
        TaskEntry.ACQUISITION_PROBE
        if actor is ProductionActor.ACQUISITION
        else TaskEntry.BUILD_PROBE
    )
    placement = {
        "cluster_arn": compiled.cluster_arn,
        "subnet_id": compiled.subnet_id,
        "security_group_ids": list(compiled.security_group_ids),
        "assign_public_ip": compiled.assign_public_ip,
        "task_role_arn": compiled.task_role_arn,
        "execution_role_arn": compiled.execution_role_arn,
        "platform_version": compiled.platform_version,
        "binding_key_arn": compiled.binding_key_arn,
    }
    return LaunchSpecification(
        actor=actor,
        kind=LaunchKind.PERMISSION_PROBE,
        identity=admitted,
        entry=entry,
        workload=workload,
        target=target,
        placement=placement,
        gate_evidence={
            "r3_verification_digest": None,
            "r3_applicable": False,
            "generation_record_digest": target.generation_record_digest,
        },
    )


# ---------------------------------------------------------------------------
# The authorization record
# ---------------------------------------------------------------------------

_AUTHORIZATION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "actor",
        "kind",
        "identity",
        "specification_digest",
        "issued_at",
        "expires_at",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class LaunchAuthorizationRecord:
    """The owner's written authorization for exactly one launch of one specification."""

    actor: ProductionActor
    kind: LaunchKind
    identity: str
    specification_digest: str
    issued_at: datetime
    expires_at: datetime

    def valid_at(self, now: datetime) -> bool:
        """Whether the authorization is in force at ``now``."""
        return self.issued_at <= now < self.expires_at


def parse_authorization(
    raw: object,
    *,
    actor: ProductionActor,
    kind: LaunchKind,
    identity: str,
    specification_digest: str,
    now: datetime,
) -> LaunchAuthorizationRecord:
    """The authorization for THIS actor, kind, identity and specification, valid now.

    The specification digest is the one preparation produced from the admitted records
    and execution recomputes; an authorization naming any other refuses
    (``AUTHORIZATION_MISMATCH``) before a client is built.
    """
    document = decode_record(
        raw, contract_id=AUTHORIZATION_CONTRACT_ID, fields=_AUTHORIZATION_FIELDS
    )
    actor_value = exact_str(document["actor"])
    kind_value = exact_str(document["kind"])
    issued_at = instant(document["issued_at"])
    expires_at = instant(document["expires_at"])
    recorded_digest = hex_digest(document["specification_digest"])
    if (
        actor_value not in {m.value for m in ProductionActor}
        or kind_value not in {m.value for m in LaunchKind}
        or issued_at is None
        or expires_at is None
        or recorded_digest is None
    ):
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    recorded_identity = _identity(document["identity"])
    if (
        ProductionActor(actor_value) is not actor
        or LaunchKind(kind_value) is not kind
        or recorded_identity != identity
        or recorded_digest != specification_digest
    ):
        raise _refuse(LaunchRecordDefect.AUTHORIZATION_MISMATCH)
    if expires_at <= issued_at or expires_at - issued_at > MAX_AUTHORIZATION_VALIDITY:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    record = LaunchAuthorizationRecord(
        actor=actor,
        kind=kind,
        identity=recorded_identity,
        specification_digest=recorded_digest,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    if not record.valid_at(now):
        raise _refuse(LaunchRecordDefect.AUTHORIZATION_EXPIRED)
    return record


# ---------------------------------------------------------------------------
# Evidence and the ledger row the tool may write
# ---------------------------------------------------------------------------


def evidence_document(
    *,
    actor: ProductionActor,
    kind: LaunchKind,
    outcome: str,
    counts: dict[str, int],
    incident: str | None,
    cleanup_failures: list[str],
    task_started: bool,
    exit_codes: list[int | None],
    recorded_at: datetime,
) -> dict[str, Any]:
    """The sanitized launch evidence: tokens, counts, exit codes. No ARN, no identifier."""
    if any(type(v) is not int or v < 0 for v in counts.values()):
        raise TypeError("counts must be non-negative integers")
    return {
        "schema_version": RECORD_SCHEMA_VERSION,
        "contract_id": EVIDENCE_CONTRACT_ID,
        "actor": actor.value,
        "kind": kind.value,
        "outcome": outcome,
        "counts": dict(sorted(counts.items())),
        "incident": incident,
        "cleanup_failures": list(cleanup_failures),
        "task_started": task_started,
        "exit_codes": list(exit_codes),
        "recorded_at": recorded_at.isoformat(),
    }


def is_ipv4_set(values: object) -> bool:
    """Whether ``values`` is a non-empty list of IPv4 literals (the origin set's shape)."""
    if type(values) is not list or not values:
        return False
    for value in values:
        if type(value) is not str:
            return False
        try:
            ipaddress.IPv4Address(value)
        except ValueError:
            return False
    return True


# ---------------------------------------------------------------------------
# The launch record, the provisional row, and completion from a verified receipt
# ---------------------------------------------------------------------------

LAUNCH_RECORD_CONTRACT_ID: Final = "kalpamani-launch-record/v1"

_LAUNCH_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "entry",
        "actor",
        "kind",
        "identity",
        "task_arn",
        "task_definition_arn",
        "image_digest",
        "configuration_digest",
        "code_commit",
        "input_digest",
        "slice",
        "plan_digest",
        "launched_at",
        "recorded_at",
        "network_interface_id",
        "subnet_id",
        "security_group_ids",
        "specification_digest",
        "release_mode",
        "observed_exit_code",
    }
)

#: The exit code of every task outcome, inverted: what one observed code means.
_OUTCOME_OF_EXIT: Final[dict[int, TaskOutcome]] = {code: o for o, code in EXIT_STATUS.items()}


@dataclass(frozen=True, slots=True, kw_only=True)
class LaunchRecord:
    """What the tool holds about one launch it made -- **owner-private**, never exported.

    It carries the task ARN and the revision ARN (real account ids once a launch is
    real), which is why it lives beside the ledger under the owner's private root
    and never in evidence. It is exactly what a receipt is verified against
    (:class:`~kalpamani.data.production.sharadar.receipts.ReceiptExpectation`), plus
    the slice and plan digest an acquisition row needs, plus the **binding to the
    launch it belongs to**: the digest of the specification the owner authorized
    (the reservation carries that specification) and the placement the launcher
    verified -- interface, subnet and the security groups the interface carried.

    **The trust boundary is the owner's private root.** These digests bind the
    reservation, the record, the ledger row and the receipt to one launch so that a
    substituted or mislaid artifact is refused; they are not protection against an
    owner who deliberately rewrites every artifact consistently, and nothing here
    claims to be.
    """

    entry: TaskEntry
    kind: LaunchKind
    identity: str
    task_arn: str
    task_definition_arn: str
    image_digest: str
    configuration_digest: str
    code_commit: str
    input_digest: str
    slice: Slice | None
    plan_digest: str | None
    launched_at: datetime
    #: When the tool recorded the launch's terminal (or last observed) state.
    recorded_at: datetime
    #: The placement the launcher verified and the release named; ``None`` when no
    #: release was written. The R-2 verdict binds the analysis source to this interface
    #: and its components to these groups.
    network_interface_id: str | None
    subnet_id: str | None
    security_group_ids: tuple[str, ...] | None
    #: The digest of the specification the authorization named and the reservation holds.
    specification_digest: str
    #: The release behaviour the launcher applied -- the specification's (ADR-0047).
    release_mode: ReleaseMode = ReleaseMode.NORMAL
    #: The exit code the launcher itself observed at the task's terminal state, or ``None``
    #: when it observed no terminal state; the terminal-state confirmation a negative cell
    #: needs beside the receipt (ADR-0047).
    observed_exit_code: int | None = None

    def __post_init__(self) -> None:
        """The verified placement comes whole, and the record is not earlier than the launch."""
        if type(self.release_mode) is not ReleaseMode:
            raise TypeError("release_mode must be an exact ReleaseMode")
        if self.release_mode is not ReleaseMode.NORMAL and self.kind is not LaunchKind.VERIFICATION:
            raise ValueError("a negative release mode is a verification launch's alone")
        if self.observed_exit_code is not None and (
            type(self.observed_exit_code) is not int or not 0 <= self.observed_exit_code <= 255
        ):
            raise ValueError("an observed exit code is an integer 0..255, or None")
        present = {
            self.network_interface_id is None,
            self.subnet_id is None,
            self.security_group_ids is None,
        }
        if len(present) != 1:
            raise ValueError("the verified interface, subnet and groups are recorded together")
        if self.security_group_ids is not None and (
            type(self.security_group_ids) is not tuple
            or not self.security_group_ids
            or len(set(self.security_group_ids)) != len(self.security_group_ids)
        ):
            raise ValueError("the verified security groups are a non-empty tuple")
        if hex_digest(self.specification_digest) is None:
            raise ValueError("the specification digest is a hex SHA-256")
        if self.recorded_at < self.launched_at:
            raise ValueError("a launch is recorded no earlier than it was made")

    @property
    def actor(self) -> ProductionActor:
        """The entry's actor."""
        return ENTRY_ACTOR[self.entry]

    @property
    def task_id(self) -> str:
        """The task id the receipt binds: the last segment of the task ARN."""
        match = TASK_ARN_RE.fullmatch(self.task_arn)
        assert match is not None
        return match.group(3)

    def expectation(self) -> ReceiptExpectation:
        """The receipt expectation this record establishes."""
        return ReceiptExpectation(
            entry=self.entry,
            task_id=self.task_id,
            task_definition_arn=self.task_definition_arn,
            image_digest=self.image_digest,
            configuration_digest=self.configuration_digest,
            code_commit=self.code_commit,
            identity=self.identity,
            input_digest=self.input_digest,
        )

    def document(self) -> dict[str, Any]:
        """The record document."""
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": LAUNCH_RECORD_CONTRACT_ID,
            "entry": self.entry.value,
            "actor": self.actor.value,
            "kind": self.kind.value,
            "identity": self.identity,
            "task_arn": self.task_arn,
            "task_definition_arn": self.task_definition_arn,
            "image_digest": self.image_digest,
            "configuration_digest": self.configuration_digest,
            "code_commit": self.code_commit,
            "input_digest": self.input_digest,
            "slice": None if self.slice is None else self.slice.canonical(),
            "plan_digest": self.plan_digest,
            "launched_at": self.launched_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
            "network_interface_id": self.network_interface_id,
            "subnet_id": self.subnet_id,
            "security_group_ids": (
                None if self.security_group_ids is None else list(self.security_group_ids)
            ),
            "specification_digest": self.specification_digest,
            "release_mode": self.release_mode.value,
            "observed_exit_code": self.observed_exit_code,
        }

    def __repr__(self) -> str:
        """Entry and kind. **Never an ARN, and never an identity.**"""
        return f"LaunchRecord(entry={self.entry.value!r}, kind={self.kind.value!r})"


def parse_launch_record(raw: object) -> LaunchRecord:
    """The launch record, every field to its grammar, entry and kind agreeing."""
    document = decode_record(
        raw, contract_id=LAUNCH_RECORD_CONTRACT_ID, fields=_LAUNCH_RECORD_FIELDS
    )
    entry_value = exact_str(document["entry"])
    kind_value = exact_str(document["kind"])
    if entry_value not in {m.value for m in TaskEntry} or kind_value not in {
        m.value for m in LaunchKind
    }:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    entry = TaskEntry(entry_value)
    kind = LaunchKind(kind_value)
    if (entry in VERIFICATION_ENTRIES) != (kind is LaunchKind.VERIFICATION):
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    if (entry in PROBE_ENTRIES) != (kind is LaunchKind.PERMISSION_PROBE):
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    if document["actor"] != ENTRY_ACTOR[entry].value:
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    identity = _identity(document["identity"])
    if identity_kind(identity) is not kind:
        raise _refuse(LaunchRecordDefect.IDENTITY_KIND_MISMATCH)
    task_arn = exact_str(document["task_arn"])
    launched_at = instant(document["launched_at"])
    recorded_at = instant(document["recorded_at"])
    input_digest_value = hex_digest(document["input_digest"])
    interface = document["network_interface_id"]
    subnet = document["subnet_id"]
    groups = document["security_group_ids"]
    specification_digest = hex_digest(document["specification_digest"])
    definition = exact_str(document["task_definition_arn"])
    image = exact_str(document["image_digest"])
    configuration = exact_str(document["configuration_digest"])
    commit = exact_str(document["code_commit"])
    mode_value = exact_str(document["release_mode"])
    observed = document["observed_exit_code"]
    if (
        mode_value not in {m.value for m in ReleaseMode}
        or (observed is not None and (type(observed) is not int or not 0 <= observed <= 255))
        or task_arn is None
        or TASK_ARN_RE.fullmatch(task_arn) is None
        or launched_at is None
        or recorded_at is None
        or recorded_at < launched_at
        or input_digest_value is None
        or definition is None
        or TASK_DEFINITION_ARN_RE.fullmatch(definition) is None
        or image is None
        or IMAGE_DIGEST_RE.fullmatch(image) is None
        or configuration is None
        or CONFIGURATION_DIGEST_RE.fullmatch(configuration) is None
        or commit is None
        or CODE_COMMIT_RE.fullmatch(commit) is None
        or specification_digest is None
        or len({interface is None, subnet is None, groups is None}) != 1
        or (
            interface is not None
            and (
                type(interface) is not str
                or NETWORK_INTERFACE_ID_RE.fullmatch(interface) is None
                or type(subnet) is not str
                or SUBNET_ID_RE.fullmatch(subnet) is None
                or type(groups) is not list
                or not groups
                or any(
                    type(group) is not str or SECURITY_GROUP_ID_RE.fullmatch(group) is None
                    for group in groups
                )
                or len(set(groups)) != len(groups)
            )
        )
    ):
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    family = TASK_DEFINITION_ARN_RE.fullmatch(definition)
    assert family is not None
    if family.group(2) != entry_family(entry):
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    release_mode = ReleaseMode(mode_value)
    if release_mode is not ReleaseMode.NORMAL and kind is not LaunchKind.VERIFICATION:
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    covered: Slice | None = None
    plan_digest: str | None = None
    # A probe launch (ADR-0048) carries no workload: no slice, no plan digest,
    # whichever actor's probe it is.
    if (
        ENTRY_ACTOR[entry] is ProductionActor.ACQUISITION
        and kind is not LaunchKind.PERMISSION_PROBE
    ):
        try:
            covered = parse_slice(document["slice"])
        except Exception:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED) from None
        plan_digest = hex_digest(document["plan_digest"])
        if plan_digest is None:
            raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    elif document["slice"] is not None or document["plan_digest"] is not None:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    return LaunchRecord(
        entry=entry,
        kind=kind,
        identity=identity,
        task_arn=task_arn,
        task_definition_arn=definition,
        image_digest=image,
        configuration_digest=configuration,
        code_commit=commit,
        input_digest=input_digest_value,
        slice=covered,
        plan_digest=plan_digest,
        launched_at=launched_at,
        recorded_at=recorded_at,
        network_interface_id=interface,
        subnet_id=subnet,
        security_group_ids=None if groups is None else tuple(groups),
        specification_digest=specification_digest,
        release_mode=release_mode,
        observed_exit_code=observed,
    )


def provisional_ledger_outcome(
    *, kind: LaunchKind, task_started: bool, misplaced: bool, exit_codes: tuple[int | None, ...]
) -> str:
    """The ledger outcome one launch establishes from what the tool itself observed.

    **An authorized identity is consumed by its authorization**, whether or not a task
    ran, so every launch attempt writes a row; the row's *disposition* is the most the
    exit code can support:

    - ``MISPLACED`` from the launcher's own incident;
    - ``REFUSED`` when no task started, or when the task's exit code is one of the
      entry's refusals;
    - ``COMPLETED`` only from exit ``0`` on a **production** launch, and ``VERIFIED``
      only from exit ``18`` on a **verification** launch -- each the wrong way round
      is recorded as ``HALTED``, because a verification image that exits ``0`` or a
      production image that exits ``18`` has done something the record cannot name;
    - ``HALTED`` for everything else: a halt, an ambiguous terminal state, no exit
      code observed, or an exit code the table does not know.

    A ``COMPLETED`` row written here carries ``EXIT_CODE_ONLY`` evidence and is **not
    buildable** until :func:`complete_ledger_row` verifies the task's receipt.
    """
    if misplaced:
        return "MISPLACED"
    if not task_started:
        return "REFUSED"
    if len(exit_codes) != 1 or exit_codes[0] is None:
        return "HALTED"
    outcome = _OUTCOME_OF_EXIT.get(exit_codes[0])
    if outcome is None:
        return "HALTED"
    if outcome is TaskOutcome.COMPLETED:
        return LEDGER_OUTCOME_COMPLETED if kind is LaunchKind.PRODUCTION else "HALTED"
    if outcome is TaskOutcome.VERIFIED_BOOTSTRAP:
        return "VERIFIED" if kind is LaunchKind.VERIFICATION else "HALTED"
    if outcome in PROBE_OUTCOMES:
        # A probe exit on a probe launch is PROBED (ADR-0048); on any other
        # kind the image did something the record cannot name.
        return LEDGER_OUTCOME_PROBED if kind is LaunchKind.PERMISSION_PROBE else "HALTED"
    if outcome in BOOTSTRAP_REFUSALS or outcome in PRE_BOOTSTRAP_OUTCOMES:
        return "REFUSED"
    if outcome in LEDGER_OUTCOME_OF:
        # A halt, or an ambiguous terminal state (``None``): never more than HALTED.
        return "HALTED"
    # Every other outcome is one of the processing paths' own refusals -- the same
    # reading the receipt validator gives them.
    return "REFUSED"


def provisional_ledger_row(
    record: LaunchRecord, *, outcome: str, completed_at: datetime
) -> OwnerLedgerRow:
    """The ``EXIT_CODE_ONLY`` row one launch adds to the ledger."""
    if outcome not in LEDGER_OUTCOMES:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    return OwnerLedgerRow(
        identity=record.identity,
        actor=record.actor,
        kind=record.kind,
        outcome=outcome,
        evidence=LedgerEvidence.EXIT_CODE_ONLY,
        launched_at=record.launched_at,
        completed_at=max(completed_at, record.launched_at),
        slice=record.slice,
        plan_digest=record.plan_digest,
    )


def append_row(ledger: OwnerLedger, row: OwnerLedgerRow) -> OwnerLedger:
    """The ledger with ``row`` appended; an identity already present is refused."""
    if row.identity in ledger.identities:
        raise _refuse(LaunchRecordDefect.IDENTITY_CONSUMED)
    return OwnerLedger(rows=(*ledger.rows, row))


def complete_ledger_row(
    ledger: OwnerLedger, *, record: LaunchRecord, receipt: VerifiedReceipt
) -> OwnerLedger:
    """Replace the record's ``EXIT_CODE_ONLY`` row with the receipt's disposition.

    The receipt must already be verified against ``record.expectation()`` -- that is
    what binds it to this launch -- and must establish a disposition
    (:func:`~kalpamani.data.production.sharadar.receipts.ledger_completion`); uncertain
    evidence completes nothing and the row stays provisional. A row already
    ``RECEIPT_VERIFIED`` is never rewritten, and a receipt whose disposition
    contradicts the launch kind (``COMPLETED`` for a verification launch, ``VERIFIED``
    for a production one) is refused.
    """
    existing = ledger.row(record.identity)
    if existing is None or existing.evidence is not LedgerEvidence.EXIT_CODE_ONLY:
        raise _refuse(LaunchRecordDefect.ROW_NOT_BUILDABLE)
    if existing.kind is not record.kind or existing.actor is not record.actor:
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    completion = ledger_completion(receipt)
    if completion is None:
        raise _refuse(LaunchRecordDefect.ROW_NOT_BUILDABLE)
    if (
        completion.outcome == LEDGER_OUTCOME_COMPLETED
    ) and record.kind is not LaunchKind.PRODUCTION:
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    if completion.outcome == "VERIFIED" and record.kind is not LaunchKind.VERIFICATION:
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    if (
        completion.outcome == LEDGER_OUTCOME_PROBED
        and record.kind is not LaunchKind.PERMISSION_PROBE
    ):
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    completed = OwnerLedgerRow(
        identity=existing.identity,
        actor=existing.actor,
        kind=existing.kind,
        outcome=completion.outcome,
        evidence=LedgerEvidence.RECEIPT_VERIFIED,
        launched_at=existing.launched_at,
        completed_at=existing.completed_at,
        slice=existing.slice,
        plan_digest=existing.plan_digest,
    )
    return OwnerLedger(
        rows=tuple(completed if row.identity == existing.identity else row for row in ledger.rows)
    )


__all__ = [
    "AUTHORIZATION_CONTRACT_ID",
    "EVIDENCE_CONTRACT_ID",
    "LAUNCH_INPUTS_CONTRACT_ID",
    "LAUNCH_RECORD_CONTRACT_ID",
    "LEDGER_CONTRACT_ID",
    "MAX_AUTHORIZATION_VALIDITY",
    "MAX_RECORD_BYTES",
    "PROBE_IDENTITY_PREFIX",
    "PROBE_STARTED_BY_PREFIX",
    "RECORD_SCHEMA_VERSION",
    "SPECIFICATION_CONTRACT_ID",
    "TASK_DEFINITION_INTENTIONAL_DIFFERENCES",
    "TASK_DEFINITION_SHARED_FIELDS",
    "VERIFICATION_IDENTITY_PREFIX",
    "EquivalenceVerdict",
    "LaunchAuthorizationRecord",
    "LaunchInputs",
    "LaunchKind",
    "LaunchRecord",
    "LaunchRecordDefect",
    "LaunchRecordError",
    "LaunchSpecification",
    "LaunchTarget",
    "LedgerEvidence",
    "OwnerLedger",
    "OwnerLedgerRow",
    "ReleaseMode",
    "TaskDefinitionEvidence",
    "admit_identity",
    "append_row",
    "build_specification",
    "compile_launch",
    "complete_ledger_row",
    "configuration_equivalence",
    "decode_record",
    "evidence_document",
    "identity_kind",
    "is_ipv4_set",
    "materialize_acquisition_input",
    "materialize_build_input",
    "parse_authorization",
    "parse_launch_inputs",
    "parse_launch_record",
    "parse_owner_ledger",
    "parse_specification",
    "probe_specification",
    "provisional_ledger_outcome",
    "provisional_ledger_row",
]
