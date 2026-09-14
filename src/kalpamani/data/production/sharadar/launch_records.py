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
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes
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
    VERIFICATION_ENTRIES,
    TaskEntry,
    TaskOutcome,
    entry_family,
)
from kalpamani.data.production.sharadar.inputs import (
    ACQUISITION_INPUT_SCHEMA_VERSION,
    INPUT_SCHEMA_VERSION,
    LEDGER_OUTCOME_COMPLETED,
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
from kalpamani.data.production.sharadar.receipts import (
    BOOTSTRAP_REFUSALS,
    LEDGER_OUTCOME_OF,
    PRE_BOOTSTRAP_OUTCOMES,
    ReceiptExpectation,
    VerifiedReceipt,
    ledger_completion,
)
from kalpamani.data.production.sharadar.release import (
    SUBNET_ID_RE,
    TASK_ARN_RE,
    TASK_DEFINITION_ARN_RE,
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
#: An authorization is for now: it expires, and a stale one is refused.
MAX_AUTHORIZATION_VALIDITY: Final = timedelta(hours=24)


class LaunchKind(StrEnum):
    """What a launch is for. Closed."""

    PRODUCTION = "production"
    VERIFICATION = "verification"


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
    """The build input v1 bytes for one launch over completed, receipt-verified rows only."""
    admitted = admit_identity(ledger, identity, kind=kind)
    if type(run_identities) is not list or not run_identities:
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
    parse_build_input(document, now=now)
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
    {"task_definition_arn", "image_digest", "configuration_digest", "code_commit"}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class LaunchTarget:
    """One registered revision with the image and configuration records behind it."""

    task_definition_arn: str
    image_digest: str
    configuration_digest: str
    code_commit: str


@dataclass(frozen=True, slots=True, kw_only=True)
class LaunchInputs:
    """Everything the tool compiles launches from, per actor and kind."""

    cluster_arn: str
    execution_role_arn: str
    binding_key_arn: str
    platform_version: str
    task_role_arns: dict[ProductionActor, str]
    subnet_ids: dict[ProductionActor, str]
    security_group_ids: dict[ProductionActor, tuple[str, ...]]
    targets: dict[tuple[ProductionActor, LaunchKind], LaunchTarget]

    def __repr__(self) -> str:
        """Nothing that is an identifier."""
        return "LaunchInputs()"


def _target(raw: object) -> LaunchTarget | None:
    if raw is None:
        return None
    if type(raw) is not dict or set(raw) != _LAUNCH_TARGET_FIELDS:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    definition = exact_str(raw["task_definition_arn"])
    image = exact_str(raw["image_digest"])
    configuration = exact_str(raw["configuration_digest"])
    commit = exact_str(raw["code_commit"])
    if (
        definition is None
        or TASK_DEFINITION_ARN_RE.fullmatch(definition) is None
        or image is None
        or IMAGE_DIGEST_RE.fullmatch(image) is None
        or configuration is None
        or CONFIGURATION_DIGEST_RE.fullmatch(configuration) is None
        or commit is None
        or CODE_COMMIT_RE.fullmatch(commit) is None
    ):
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    return LaunchTarget(
        task_definition_arn=definition,
        image_digest=image,
        configuration_digest=configuration,
        code_commit=commit,
    )


def parse_launch_inputs(raw: object) -> LaunchInputs:
    """The launch inputs record, every identifier held to the compiled-launch grammars."""
    document = decode_record(
        raw, contract_id=LAUNCH_INPUTS_CONTRACT_ID, fields=_LAUNCH_INPUTS_FIELDS
    )
    cluster = exact_str(document["cluster_arn"])
    execution = exact_str(document["execution_role_arn"])
    key = exact_str(document["binding_key_arn"])
    platform = exact_str(document["platform_version"])
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
        if type(block) is not dict or set(block) != _LAUNCH_ACTOR_FIELDS:
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
        ):
            target = _target(block[field])
            if target is None:
                continue
            family = TASK_DEFINITION_ARN_RE.fullmatch(target.task_definition_arn)
            assert family is not None
            expected = (
                constants_for(actor).task_family
                if kind is LaunchKind.PRODUCTION
                else constants_for(actor).verification_task_family
            )
            if family.group(2) != expected:
                raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
            targets[(actor, kind)] = target
    return LaunchInputs(
        cluster_arn=cluster,
        execution_role_arn=execution,
        binding_key_arn=key,
        platform_version=platform,
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
    return compiled, target


# ---------------------------------------------------------------------------
# Configuration equivalence -- verification versus production
# ---------------------------------------------------------------------------


class EquivalenceVerdict(StrEnum):
    """Whether a verification image's configuration stands for the production one."""

    EQUIVALENT = "EQUIVALENT"
    CODE_DIFFERS = "CODE_DIFFERS"
    ORIGIN_DIFFERS = "ORIGIN_DIFFERS"
    ENTRY_MISMATCH = "ENTRY_MISMATCH"
    UNREADABLE = "UNREADABLE"


def configuration_equivalence(
    *, production: bytes, verification: bytes, acquisition: bytes | None = None
) -> EquivalenceVerdict:
    """Compare a verification configuration file with its production counterpart.

    Equivalent when both parse, both name the same code commit and tree, the verification
    entry is the production entry's own, and the origin set matches: the acquisition
    verify file must carry the acquisition file's origin set; the build verify file --
    whose production counterpart carries no origin -- must carry the **acquisition**
    configuration's set, which is why ``acquisition`` is supplied for a build pair.
    Nothing here reads a secret name into the verdict.
    """
    try:
        prod, _ = parse_compiled_configuration(production)
        verify, _ = parse_compiled_configuration(verification)
    except CompiledConfigurationError:
        return EquivalenceVerdict.UNREADABLE
    if (
        verify.entry not in VERIFICATION_ENTRIES
        or ENTRY_ACTOR[verify.entry] is not ENTRY_ACTOR[prod.entry]
    ):
        return EquivalenceVerdict.ENTRY_MISMATCH
    if prod.entry in VERIFICATION_ENTRIES:
        return EquivalenceVerdict.ENTRY_MISMATCH
    if prod.compiled.code_commit != verify.compiled.code_commit:
        return EquivalenceVerdict.CODE_DIFFERS
    if prod.entry is TaskEntry.ACQUISITION:
        origin = prod.origin_addresses
    else:
        if acquisition is None:
            return EquivalenceVerdict.ORIGIN_DIFFERS
        try:
            acquired, _ = parse_compiled_configuration(acquisition)
        except CompiledConfigurationError:
            return EquivalenceVerdict.UNREADABLE
        if acquired.entry is not TaskEntry.ACQUISITION:
            return EquivalenceVerdict.ENTRY_MISMATCH
        origin = acquired.origin_addresses
    if verify.origin_addresses != origin:
        return EquivalenceVerdict.ORIGIN_DIFFERS
    return EquivalenceVerdict.EQUIVALENT


# ---------------------------------------------------------------------------
# The authorization record
# ---------------------------------------------------------------------------

_AUTHORIZATION_FIELDS: Final[frozenset[str]] = frozenset(
    {"schema_version", "contract_id", "actor", "kind", "identity", "issued_at", "expires_at"}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class LaunchAuthorizationRecord:
    """The owner's written authorization for exactly one launch."""

    actor: ProductionActor
    kind: LaunchKind
    identity: str
    issued_at: datetime
    expires_at: datetime


def parse_authorization(
    raw: object, *, actor: ProductionActor, kind: LaunchKind, identity: str, now: datetime
) -> LaunchAuthorizationRecord:
    """The authorization for THIS actor, kind and identity, valid now -- or refuse."""
    document = decode_record(
        raw, contract_id=AUTHORIZATION_CONTRACT_ID, fields=_AUTHORIZATION_FIELDS
    )
    actor_value = exact_str(document["actor"])
    kind_value = exact_str(document["kind"])
    issued_at = instant(document["issued_at"])
    expires_at = instant(document["expires_at"])
    if (
        actor_value not in {m.value for m in ProductionActor}
        or kind_value not in {m.value for m in LaunchKind}
        or issued_at is None
        or expires_at is None
    ):
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    recorded_identity = _identity(document["identity"])
    if (
        ProductionActor(actor_value) is not actor
        or LaunchKind(kind_value) is not kind
        or recorded_identity != identity
    ):
        raise _refuse(LaunchRecordDefect.AUTHORIZATION_MISMATCH)
    if expires_at <= issued_at or expires_at - issued_at > MAX_AUTHORIZATION_VALIDITY:
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    if not issued_at <= now < expires_at:
        raise _refuse(LaunchRecordDefect.AUTHORIZATION_EXPIRED)
    return LaunchAuthorizationRecord(
        actor=actor,
        kind=kind,
        identity=recorded_identity,
        issued_at=issued_at,
        expires_at=expires_at,
    )


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
    the slice and plan digest an acquisition row needs.
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
    if document["actor"] != ENTRY_ACTOR[entry].value:
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    identity = _identity(document["identity"])
    if identity_kind(identity) is not kind:
        raise _refuse(LaunchRecordDefect.IDENTITY_KIND_MISMATCH)
    task_arn = exact_str(document["task_arn"])
    launched_at = instant(document["launched_at"])
    input_digest_value = hex_digest(document["input_digest"])
    if (
        task_arn is None
        or TASK_ARN_RE.fullmatch(task_arn) is None
        or launched_at is None
        or input_digest_value is None
    ):
        raise _refuse(LaunchRecordDefect.FIELD_MALFORMED)
    target = _target(
        {
            "task_definition_arn": document["task_definition_arn"],
            "image_digest": document["image_digest"],
            "configuration_digest": document["configuration_digest"],
            "code_commit": document["code_commit"],
        }
    )
    assert target is not None
    family = TASK_DEFINITION_ARN_RE.fullmatch(target.task_definition_arn)
    assert family is not None
    if family.group(2) != entry_family(entry):
        raise _refuse(LaunchRecordDefect.ACTOR_MISMATCH)
    covered: Slice | None = None
    plan_digest: str | None = None
    if ENTRY_ACTOR[entry] is ProductionActor.ACQUISITION:
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
        task_definition_arn=target.task_definition_arn,
        image_digest=target.image_digest,
        configuration_digest=target.configuration_digest,
        code_commit=target.code_commit,
        input_digest=input_digest_value,
        slice=covered,
        plan_digest=plan_digest,
        launched_at=launched_at,
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
    "RECORD_SCHEMA_VERSION",
    "VERIFICATION_IDENTITY_PREFIX",
    "EquivalenceVerdict",
    "LaunchAuthorizationRecord",
    "LaunchInputs",
    "LaunchKind",
    "LaunchRecord",
    "LaunchRecordDefect",
    "LaunchRecordError",
    "LaunchTarget",
    "LedgerEvidence",
    "OwnerLedger",
    "OwnerLedgerRow",
    "admit_identity",
    "append_row",
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
    "provisional_ledger_outcome",
    "provisional_ledger_row",
]
