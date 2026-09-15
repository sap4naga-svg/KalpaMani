"""The verification cell matrix: the required cells, and each one's state derived from records.

**ADR-0036 §3 (L3 cells R-1 … R-9), ADR-0045 (the verification entries, the R-2 verdict rule,
the launch tool), readiness §4.3 (S5, S8, S9); ADR-0046 (this matrix and its state); proposed
ADR-0047 (the negative cells and the permission subcells).**

Nothing here launches, reserves, reads a receipt or decides a verdict: those are the
accepted launch tool's, the reservation store's, the receipt validator's and the
isolation-verdict path's, and the runner script composes them. This module does two
things only: it **enumerates** the required cells with what each one names -- actor,
target, inputs, prerequisite evidence, authorization, how it is executed -- and it
**derives** each cell's status from recorded state (the owner ledger, the reservations
beside it, the verdict records, the R-3 record and the launch-inputs record), so that
a resumed or interrupted matrix is reconciled from what was durably recorded rather than
remembered.

Every status is closed. A cell whose prerequisite did not pass is ``BLOCKED``; a cell
whose identity is reserved but unrecorded is ``INTERRUPTED`` (recover, never relaunch); a
runtime cell with a row but no receipt-verified evidence is ``LAUNCHED`` and cannot pass;
a build isolation cell without a qualifying corroboration stays ``INCONCLUSIVE``; a cell
the accepted tools cannot execute yet is ``BLOCKED`` with its reason or ``UNEXECUTED`` when
it is simply owner-run. The aggregate is ``VERIFIED`` only when every required cell is
``PASSED``; missing receipts, contradictory evidence and blocked cells cannot produce it.

**A runtime cell passes only through its evidence chain.** The prepared cell names an
identity and a specification digest; the reservation beside the ledger must carry that
identity and that digest; the launch record must name the same digest, identity, actor, kind,
entry and the reservation's registered target; the ledger row must be ``VERIFIED`` with
receipt-verified evidence; and the reservation's target and compiled placement must be the
ones the launch-inputs record registers **now** -- otherwise the success is ``HISTORICAL``
(ADR-0045 §7: a new commit or a new verification image digest needs fresh R-1/R-2
evidence). Anything missing, malformed, conflicting or substituted is ``UNBOUND``, never
``PASSED``. **The trust boundary is the owner's private root**: these bindings refuse a
mislaid or substituted artifact; they are no proof against an owner who rewrites every
artifact consistently, and none is claimed.

**The isolation cell reads every verdict record for its launch.** Each must parse closed
and consistent (:func:`probe.parse_isolation_verdict_document`), name the cell's actor and
kind, and carry the same probe block; then, deterministically: any ``FAILED`` (an observed
connection) is ``FAILED``; differing probe blocks or an ``INCONCLUSIVE`` reason a later
corroboration cannot resolve beside a ``VERIFIED`` is a conflict (``UNBOUND``); a
``VERIFIED`` whose companions are all resolvable insufficiencies is ``PASSED``; otherwise
``INCONCLUSIVE``. A later record resolves an earlier insufficiency for the **same launch**
only; nothing is relaunched, no record is discarded, and no "latest wins" rule exists.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes
from kalpamani.data.production.sharadar.documents import (
    decode_document,
    exact_str,
    hex_digest,
    instant,
)
from kalpamani.data.production.sharadar.entry import EXIT_STATUS, TaskEntry, TaskOutcome
from kalpamani.data.production.sharadar.launch_records import (
    MAX_RECORD_BYTES,
    RECORD_SCHEMA_VERSION,
    VERIFICATION_IDENTITY_PREFIX,
    LaunchInputs,
    LaunchKind,
    LaunchRecord,
    LaunchRecordError,
    LedgerEvidence,
    OwnerLedger,
    compile_launch,
)
from kalpamani.data.production.sharadar.launch_store import RecordBinding, Reservation, bind_record
from kalpamani.data.production.sharadar.permission_cells import (
    PermissionEvidence,
    SubcellState,
    SubcellStatus,
    derive_subcell,
    subcells_of,
)
from kalpamani.data.production.sharadar.probe import (
    RESOLVABLE_INSUFFICIENCIES,
    IsolationVerdict,
    IsolationVerdictDocument,
)
from kalpamani.data.production.sharadar.r3_verification import R3Binding, R3Record, record_attests
from kalpamani.data.production.sharadar.receipts import VerifiedReceipt
from kalpamani.data.production.sharadar.release import ReleaseMode
from kalpamani.data.production.sharadar.vocabulary import ProductionActor

CELLS_CONTRACT_ID: Final = "kalpamani-verification-cells/v1"


class CellKind(StrEnum):
    """How a cell is executed. Closed."""

    CONTROL_R3 = "CONTROL_R3"
    RUNTIME_LAUNCH = "RUNTIME_LAUNCH"
    ISOLATION_VERDICT = "ISOLATION_VERDICT"
    NEGATIVE_LAUNCH = "NEGATIVE_LAUNCH"
    PERMISSION_MATRIX = "PERMISSION_MATRIX"


class CellStatus(StrEnum):
    """The derived state of one cell. Closed."""

    UNEXECUTED = "UNEXECUTED"
    BLOCKED = "BLOCKED"
    PREPARED = "PREPARED"
    INTERRUPTED = "INTERRUPTED"
    LAUNCHED = "LAUNCHED"
    PASSED = "PASSED"
    REFUSED = "REFUSED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"
    #: Recorded evidence that binds to a target or configuration other than the one now
    #: registered: a success that stays historical under ADR-0045 §7's re-verification rule.
    HISTORICAL = "HISTORICAL"
    #: Recorded evidence that does not bind: missing, malformed, conflicting or substituted.
    UNBOUND = "UNBOUND"


class AggregateStatus(StrEnum):
    """The matrix as a whole."""

    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True, slots=True, kw_only=True)
class CellDefinition:
    """One required cell: what it names and how it is executed."""

    cell_id: str
    cell_ref: str
    kind: CellKind
    actor: ProductionActor | None
    entry: TaskEntry | None
    title: str
    must_succeed: str
    must_be_refused: str
    depends_on: tuple[str, ...]
    authorization: str
    execution: str
    #: For a launch cell, the release mode the prepared specification must carry
    #: (ADR-0047); ``None`` for a cell that is not a launch.
    release_mode: ReleaseMode | None = None
    #: For a negative launch cell, the one task outcome that passes it.
    expected_outcome: TaskOutcome | None = None

    def document(self) -> dict[str, Any]:
        """The closed definition block."""
        return {
            "cell_id": self.cell_id,
            "cell_ref": self.cell_ref,
            "kind": self.kind.value,
            "actor": None if self.actor is None else self.actor.value,
            "entry": None if self.entry is None else self.entry.value,
            "title": self.title,
            "must_succeed": self.must_succeed,
            "must_be_refused": self.must_be_refused,
            "release_mode": None if self.release_mode is None else self.release_mode.value,
            "expected_outcome": (
                None if self.expected_outcome is None else self.expected_outcome.value
            ),
            "depends_on": list(self.depends_on),
            "authorization": self.authorization,
            "execution": self.execution,
        }


_LAUNCH_TOOL: Final = (
    "scripts/production_launch.py -- one prepared specification, one identity, one authorization"
)
_NEGATIVE: Final = (
    "scripts/production_verification_cells.py --prepare-cell / --execute-cell / --complete-cell: "
    "the launch tool once under --release-mode withheld|mismatched (ADR-0047); the "
    "expected refusal, and only it, passes -- receipt-verified, bound to its reservation, "
    "record and terminal state, with zero data-plane operations"
)
_OWNER_RUN: Final = (
    "scripts/production_permission_cells.py --execute-subcell <id> per subcell (one operation, "
    "one principal, one attempt; ADR-0047) and --cleanup afterwards; the cell passes "
    "only when every subcell is matched at runtime under the current binding and every "
    "created object is confirmed removed; a blocked subcell (task role, deletion role) blocks "
    "the cell, and simulation never passes one"
)

#: The required cells, enumerated from ADR-0036 §3 and readiness §4.3 (S5, S8, S9).
REQUIRED_CELLS: Final[tuple[CellDefinition, ...]] = (
    CellDefinition(
        cell_id="R3",
        cell_ref="R-3",
        kind=CellKind.CONTROL_R3,
        actor=None,
        entry=None,
        title="server-side conditional-write refusal, control principal",
        must_succeed=(
            "row 1: one conditional PutObject of a synthetic object (fresh positive control)"
        ),
        must_be_refused=(
            "rows 2, 4, 5, 6: unconditional, copy-shaped and multipart creation refused with an "
            "explicit deny in a resource-based policy; rows 3, 7, 9: nothing created"
        ),
        depends_on=(),
        authorization="one written R-3 authorization; the foundation control profile",
        execution=(
            "scripts/production_r3_verification.py; evidence = the sanitized record whose digest "
            "the launch-inputs record names as r3_verification_digest and which attests to the "
            "current declared statements"
        ),
    ),
    CellDefinition(
        cell_id="R1-ACQ-BOOTSTRAP",
        cell_ref="R-1",
        kind=CellKind.RUNTIME_LAUNCH,
        actor=ProductionActor.ACQUISITION,
        entry=TaskEntry.ACQUISITION_VERIFY,
        title="acquisition verification task reaches the barrier and exits VERIFIED_BOOTSTRAP",
        must_succeed=(
            "one launch of the registered acquisition verification revision with a real input; "
            "a matching release; receipt VERIFIED_BOOTSTRAP bound to the launch record; ledger row "
            "VERIFIED with RECEIPT_VERIFIED evidence; zero S3, secret and provider operations"
        ),
        must_be_refused="(negative cells R1-ACQ-NO-RELEASE / R1-ACQ-RELEASE-MISMATCH)",
        depends_on=("R3",),
        authorization="one authorization naming this cell's launch specification digest",
        execution=_LAUNCH_TOOL,
    ),
    CellDefinition(
        cell_id="R1-BLD-BOOTSTRAP",
        cell_ref="R-1",
        kind=CellKind.RUNTIME_LAUNCH,
        actor=ProductionActor.BUILD,
        entry=TaskEntry.BUILD_VERIFY,
        title="build verification task reaches the barrier and exits VERIFIED_BOOTSTRAP",
        must_succeed=(
            "one launch of the registered build verification revision with a real build input; a "
            "matching release; receipt VERIFIED_BOOTSTRAP with its probe block; ledger row "
            "VERIFIED with RECEIPT_VERIFIED evidence; zero S3 operations"
        ),
        must_be_refused="(negative cells R1-BLD-NO-RELEASE / R1-BLD-RELEASE-MISMATCH)",
        depends_on=("R3",),
        authorization="one authorization naming this cell's launch specification digest",
        execution=_LAUNCH_TOOL,
    ),
    CellDefinition(
        cell_id="R2-BLD-ISOLATION",
        cell_ref="R-2",
        kind=CellKind.ISOLATION_VERDICT,
        actor=ProductionActor.BUILD,
        entry=TaskEntry.BUILD_VERIFY,
        title="build subnet reaches no provider origin",
        must_succeed=(
            "the verdict derived from the verified receipt's probe block, the recorded placement "
            "and one transcribed Reachability Analyzer analysis is VERIFIED"
        ),
        must_be_refused=(
            "CONNECTED is FAILED whatever the model says; a non-connection without qualifying "
            "corroboration stays INCONCLUSIVE"
        ),
        depends_on=("R1-BLD-BOOTSTRAP",),
        authorization="none beyond the launch's; the owner supplies the transcription (D-16)",
        execution="scripts/production_launch.py --isolation-verdict on the cell's launch record",
    ),
    *(
        CellDefinition(
            cell_id=f"R1-{short}-NO-RELEASE",
            cell_ref="R-1",
            kind=CellKind.NEGATIVE_LAUNCH,
            actor=actor,
            entry=entry,
            title=f"{actor.value} verification task with no release written",
            must_succeed="",
            must_be_refused=(
                "REFUSED_NO_RELEASE at the barrier ceiling with zero S3, secret and provider "
                "operations"
            ),
            depends_on=(f"R1-{short}-BOOTSTRAP",),
            authorization="one authorization per cell; not reusable",
            execution=_NEGATIVE,
            release_mode=ReleaseMode.WITHHELD,
            expected_outcome=TaskOutcome.REFUSED_NO_RELEASE,
        )
        for short, actor, entry in (
            ("ACQ", ProductionActor.ACQUISITION, TaskEntry.ACQUISITION_VERIFY),
            ("BLD", ProductionActor.BUILD, TaskEntry.BUILD_VERIFY),
        )
    ),
    *(
        CellDefinition(
            cell_id=f"R1-{short}-RELEASE-MISMATCH",
            cell_ref="R-1",
            kind=CellKind.NEGATIVE_LAUNCH,
            actor=actor,
            entry=entry,
            title=f"{actor.value} verification task with a release naming another task",
            must_succeed="",
            must_be_refused="REFUSED_RELEASE_MISMATCH with zero data-plane operations",
            depends_on=(f"R1-{short}-BOOTSTRAP",),
            authorization="one authorization per cell; not reusable",
            execution=_NEGATIVE,
            release_mode=ReleaseMode.MISMATCHED,
            expected_outcome=TaskOutcome.REFUSED_RELEASE_MISMATCH,
        )
        for short, actor, entry in (
            ("ACQ", ProductionActor.ACQUISITION, TaskEntry.ACQUISITION_VERIFY),
            ("BLD", ProductionActor.BUILD, TaskEntry.BUILD_VERIFY),
        )
    ),
    CellDefinition(
        cell_id="R4-ACQUISITION",
        cell_ref="R-4",
        kind=CellKind.PERMISSION_MATRIX,
        actor=ProductionActor.ACQUISITION,
        entry=None,
        title="acquisition principals (human and task): permitted and refused operations",
        must_succeed=(
            "GetSecretValue on the one secret; conditional PutObject to each production Bronze "
            "prefix and to _indexes/ (synthetic object, deleted by the deletion role afterwards)"
        ),
        must_be_refused=(
            "GetObject on its own write; ListBucket; DeleteObject; PutObject to silver/, gold/, "
            "manifests/, any qualification prefix, the CONTROL bucket; GetSecretValue on the "
            "qualification secret; DescribeSecret; ssm:GetParameter on the other actor's "
            "parameters; ssm:PutParameter on any binding parameter"
        ),
        depends_on=("R3",),
        authorization="per-cell authorization, each counted",
        execution=_OWNER_RUN,
    ),
    CellDefinition(
        cell_id="R5-BUILD",
        cell_ref="R-5",
        kind=CellKind.PERMISSION_MATRIX,
        actor=ProductionActor.BUILD,
        entry=None,
        title="build principals (human and task): permitted and refused operations",
        must_succeed=(
            "exact GetObject on a Bronze payload, record and locator; conditional PutObject to "
            "silver/, gold/, manifests/; GetObject on its own output"
        ),
        must_be_refused=(
            "GetSecretValue on any secret; ListBucket; GetObject on a claim; PutObject to "
            "bronze/*; DeleteObject; any qualification prefix; the CONTROL bucket; "
            "ssm:GetParameter on the acquisition parameters"
        ),
        depends_on=("R3",),
        authorization="per-cell authorization, each counted (synthetic objects per readiness 4.5)",
        execution=_OWNER_RUN,
    ),
    CellDefinition(
        cell_id="R6-LAUNCHERS",
        cell_ref="R-6",
        kind=CellKind.PERMISSION_MATRIX,
        actor=None,
        entry=None,
        title="each launcher: its own revision only",
        must_succeed=(
            "RunTask of its own actor's exact revision on the one cluster with count = 1; "
            "DescribeTasks; DescribeNetworkInterfaces on the task's interface"
        ),
        must_be_refused=(
            "RunTask of the other actor's definition; of another revision or family; on another "
            "cluster; with a taskRoleArn override naming the other actor's task role or the "
            "foundation task role (iam:PassRole refused); ExecuteCommand"
        ),
        depends_on=("R3",),
        authorization="per-cell authorization, each counted",
        execution=_OWNER_RUN,
    ),
    CellDefinition(
        cell_id="R7-QUALIFICATION",
        cell_ref="R-7",
        kind=CellKind.PERMISSION_MATRIX,
        actor=None,
        entry=None,
        title="qualification actors unchanged",
        must_succeed="unchanged",
        must_be_refused=(
            "any production prefix (bronze/sharadar/* outside qualification/, _indexes/, silver/, "
            "gold/, manifests/); any production parameter"
        ),
        depends_on=("R3",),
        authorization="per-cell authorization, each counted",
        execution=_OWNER_RUN,
    ),
    CellDefinition(
        cell_id="R8-DELETION",
        cell_ref="R-8",
        kind=CellKind.PERMISSION_MATRIX,
        actor=None,
        entry=None,
        title="deletion role",
        must_succeed=(
            "list and delete under the widened prefixes (rehearsal against synthetic objects only)"
        ),
        must_be_refused="GetObject anywhere",
        depends_on=("R3",),
        authorization="per-cell authorization, each counted",
        execution=_OWNER_RUN,
    ),
    CellDefinition(
        cell_id="R9-FOUNDATION-TASK",
        cell_ref="R-9",
        kind=CellKind.PERMISSION_MATRIX,
        actor=None,
        entry=None,
        title="foundation task role not passable",
        must_succeed="",
        must_be_refused="not passable by either launcher (iam:PassRole refused by NotResource)",
        depends_on=("R3",),
        authorization="per-cell authorization, each counted",
        execution=_OWNER_RUN,
    ),
)

CELL_BY_ID: Final[dict[str, CellDefinition]] = {cell.cell_id: cell for cell in REQUIRED_CELLS}
#: The cells a prepared-cells document may name: those the launch tool executes.
_PREPARABLE_KINDS: Final[frozenset[CellKind]] = frozenset(
    {CellKind.RUNTIME_LAUNCH, CellKind.NEGATIVE_LAUNCH}
)
assert len(CELL_BY_ID) == len(REQUIRED_CELLS)


def definition(cell_id: str) -> CellDefinition:
    """The definition of ``cell_id``, or refuse."""
    try:
        return CELL_BY_ID[cell_id]
    except KeyError:
        raise ValueError("unknown cell") from None


# ---------------------------------------------------------------------------
# The prepared-cell state document
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class PreparedCell:
    """What preparation recorded for one launch cell: its identity and its specification."""

    cell_id: str
    identity: str
    specification_digest: str
    prepared_at: datetime

    def document(self) -> dict[str, Any]:
        """The closed block."""
        return {
            "cell_id": self.cell_id,
            "identity": self.identity,
            "specification_digest": self.specification_digest,
            "prepared_at": self.prepared_at.isoformat(),
        }


class CellsDocumentError(ValueError):
    """A cells document that is not one. Carries no value."""


def cells_document(prepared: Iterable[PreparedCell]) -> dict[str, Any]:
    """The state document: the prepared cells, keyed by cell id."""
    return {
        "schema_version": RECORD_SCHEMA_VERSION,
        "contract_id": CELLS_CONTRACT_ID,
        "cells": {p.cell_id: p.document() for p in prepared},
    }


def parse_cells_document(raw: object) -> dict[str, PreparedCell]:
    """The prepared cells, closed. Each names a launch cell, a verify- identity, a digest."""
    try:
        document = decode_document(raw, max_bytes=MAX_RECORD_BYTES) if type(raw) is bytes else raw
    except Exception:
        raise CellsDocumentError("malformed") from None
    if type(document) is not dict or set(document) != {"schema_version", "contract_id", "cells"}:
        raise CellsDocumentError("malformed")
    if (
        document["schema_version"] != RECORD_SCHEMA_VERSION
        or document["contract_id"] != CELLS_CONTRACT_ID
    ):
        raise CellsDocumentError("malformed")
    cells = document["cells"]
    if type(cells) is not dict:
        raise CellsDocumentError("malformed")
    prepared: dict[str, PreparedCell] = {}
    identities: set[str] = set()
    for cell_id, block in cells.items():
        if (
            type(block) is not dict
            or set(block) != {"cell_id", "identity", "specification_digest", "prepared_at"}
            or block["cell_id"] != cell_id
            or cell_id not in CELL_BY_ID
            or CELL_BY_ID[cell_id].kind not in _PREPARABLE_KINDS
        ):
            raise CellsDocumentError("malformed")
        identity = exact_str(block["identity"])
        digest = hex_digest(block["specification_digest"])
        prepared_at = instant(block["prepared_at"])
        if (
            identity is None
            or not identity.startswith(VERIFICATION_IDENTITY_PREFIX)
            or digest is None
            or prepared_at is None
            or identity in identities
        ):
            raise CellsDocumentError("malformed")
        identities.add(identity)
        prepared[cell_id] = PreparedCell(
            cell_id=cell_id, identity=identity, specification_digest=digest, prepared_at=prepared_at
        )
    return prepared


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


NEGATIVE_EVIDENCE_CONTRACT_ID: Final = "kalpamani-negative-launch-evidence/v1"
MAX_NEGATIVE_EVIDENCE_BYTES: Final = 16 * 1024
_NEGATIVE_EVIDENCE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "cell_id",
        "actor",
        "identity",
        "specification_digest",
        "release_mode",
        "receipt_outcome",
        "counts",
        "released",
        "recorded_at",
    }
)
_NEGATIVE_COUNT_FIELDS: Final[frozenset[str]] = frozenset(
    {"s3_operations", "secret_retrievals", "provider_requests"}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class NegativeLaunchEvidence:
    """What a negative cell's verified receipt established, recorded closed.

    Written by the cell runner's ``--complete-cell`` after the launch tool verified the
    receipt against the launch record (ADR-0047): the cell, the launch it
    belongs to (identity and specification digest), the release mode the specification
    carried, the task's own outcome token, the data-plane counts the task measured
    (``None`` when it measured none -- uncertainty, never zero), and whether the task
    reported itself released. The ledger row records only ``REFUSED``; this record is
    what says *which* refusal, and it passes the cell only when it is the expected one.
    """

    cell_id: str
    actor: ProductionActor
    identity: str
    specification_digest: str
    release_mode: ReleaseMode
    receipt_outcome: TaskOutcome
    counts: dict[str, int] | None
    released: bool
    recorded_at: datetime

    def document(self) -> dict[str, Any]:
        """The closed record."""
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": NEGATIVE_EVIDENCE_CONTRACT_ID,
            "cell_id": self.cell_id,
            "actor": self.actor.value,
            "identity": self.identity,
            "specification_digest": self.specification_digest,
            "release_mode": self.release_mode.value,
            "receipt_outcome": self.receipt_outcome.value,
            "counts": None if self.counts is None else dict(sorted(self.counts.items())),
            "released": self.released,
            "recorded_at": self.recorded_at.isoformat(),
        }

    @property
    def data_plane_operations(self) -> int | None:
        """The task's S3, secret and provider operations together, or ``None`` unmeasured."""
        if self.counts is None:
            return None
        return sum(self.counts.values())


def negative_evidence_document(
    *,
    cell: CellDefinition,
    identity: str,
    specification_digest: str,
    release_mode: ReleaseMode,
    receipt: VerifiedReceipt,
    recorded_at: datetime,
) -> dict[str, Any]:
    """The negative launch evidence record for one verified receipt."""
    if cell.kind is not CellKind.NEGATIVE_LAUNCH or cell.actor is None:
        raise ValueError("negative launch evidence belongs to a negative launch cell")
    if type(receipt) is not VerifiedReceipt:
        raise TypeError("receipt must be a VerifiedReceipt")
    counts = (
        None
        if receipt.counts is None
        else {
            "s3_operations": receipt.counts.s3_operations,
            "secret_retrievals": receipt.counts.secret_retrievals,
            "provider_requests": receipt.counts.provider_requests,
        }
    )
    return NegativeLaunchEvidence(
        cell_id=cell.cell_id,
        actor=cell.actor,
        identity=identity,
        specification_digest=specification_digest,
        release_mode=release_mode,
        receipt_outcome=receipt.outcome,
        counts=counts,
        released=receipt.released,
        recorded_at=recorded_at,
    ).document()


def parse_negative_launch_evidence(raw: object) -> NegativeLaunchEvidence:
    """A negative launch evidence record, parsed closed, or ``ValueError``."""
    document = (
        raw if type(raw) is dict else decode_document(raw, max_bytes=MAX_NEGATIVE_EVIDENCE_BYTES)
    )
    if type(document) is not dict or set(document) != _NEGATIVE_EVIDENCE_FIELDS:
        raise ValueError("negative launch evidence: closed field set")
    if (
        document["schema_version"] != RECORD_SCHEMA_VERSION
        or document["contract_id"] != NEGATIVE_EVIDENCE_CONTRACT_ID
    ):
        raise ValueError("negative launch evidence: contract")
    cell_id = exact_str(document["cell_id"])
    if cell_id is None or cell_id not in CELL_BY_ID:
        raise ValueError("negative launch evidence: cell")
    cell = CELL_BY_ID[cell_id]
    if cell.kind is not CellKind.NEGATIVE_LAUNCH:
        raise ValueError("negative launch evidence: not a negative cell")
    actor = exact_str(document["actor"])
    identity = exact_str(document["identity"])
    digest = hex_digest(document["specification_digest"])
    mode = exact_str(document["release_mode"])
    outcome = exact_str(document["receipt_outcome"])
    recorded_at = instant(document["recorded_at"])
    if (
        actor not in {m.value for m in ProductionActor}
        or ProductionActor(actor) is not cell.actor
        or identity is None
        or not identity.startswith(VERIFICATION_IDENTITY_PREFIX)
        or digest is None
        or mode not in {m.value for m in ReleaseMode}
        or outcome not in {m.value for m in TaskOutcome}
        or type(document["released"]) is not bool
        or recorded_at is None
    ):
        raise ValueError("negative launch evidence: field")
    counts = document["counts"]
    if counts is not None and (
        type(counts) is not dict
        or set(counts) != _NEGATIVE_COUNT_FIELDS
        or any(type(v) is not int or type(v) is bool or v < 0 for v in counts.values())
    ):
        raise ValueError("negative launch evidence: counts")
    return NegativeLaunchEvidence(
        cell_id=cell_id,
        actor=cell.actor,
        identity=identity,
        specification_digest=digest,
        release_mode=ReleaseMode(mode),
        receipt_outcome=TaskOutcome(outcome),
        counts=None if counts is None else dict(counts),
        released=document["released"],
        recorded_at=recorded_at,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordedEvidence:
    """What the runner read: the ledger, the unreconciled identities, the verdicts, R-3."""

    ledger: OwnerLedger
    unreconciled: frozenset[str]
    #: every verdict document that parsed, grouped by the specification digest it names.
    verdicts: dict[str, tuple[IsolationVerdictDocument, ...]]
    #: specification digests named by verdict files that did NOT parse closed.
    malformed_verdicts: frozenset[str]
    #: verdict files that could not be decoded at all (no digest could be read).
    unreadable_verdicts: int
    #: the reservation beside the ledger, per prepared identity (absent when none).
    reservations: dict[str, Reservation]
    #: launch records in the records directory that parsed, per identity.
    launch_records: dict[str, LaunchRecord]
    #: launch record files that did not parse.
    unreadable_launch_records: int
    inputs: LaunchInputs | None
    r3_record: R3Record | None
    r3_binding: R3Binding | None
    #: negative launch evidence records that parsed, per specification digest.
    negative_evidence: dict[str, tuple[NegativeLaunchEvidence, ...]] = field(default_factory=dict)
    #: specification digests named by negative-evidence files that did NOT parse closed.
    malformed_negative_evidence: frozenset[str] = frozenset()
    #: negative-evidence files that could not be decoded at all.
    unreadable_negative_evidence: int = 0
    #: the R-4 .. R-9 permission records, attempts and cleanups, with the current binding.
    permission: PermissionEvidence = field(default_factory=PermissionEvidence)


@dataclass(frozen=True, slots=True, kw_only=True)
class CellState:
    """One cell's derived status and the reason it has it."""

    cell_id: str
    status: CellStatus
    reason: str
    identity: str | None
    specification_digest: str | None
    #: For a permission cell, every subcell's derived state, in catalogue order.
    subcells: tuple[SubcellState, ...] = ()

    def document(self) -> dict[str, Any]:
        """The closed block."""
        return {
            "cell_id": self.cell_id,
            "status": self.status.value,
            "reason": self.reason,
            "identity": self.identity,
            "specification_digest": self.specification_digest,
        }


def _r3_state(evidence: RecordedEvidence) -> CellState:
    record = evidence.r3_record
    if record is None:
        return CellState(
            cell_id="R3",
            status=CellStatus.BLOCKED,
            reason="no R-3 record supplied; R-3 is the gate to every other cell",
            identity=None,
            specification_digest=None,
        )
    if evidence.r3_binding is None or not record_attests(record, binding=evidence.r3_binding):
        if record.result.value == "VERIFIED":
            reason = "the R-3 record does not attest to the current declared statements or binding"
            status = CellStatus.BLOCKED
        elif record.result.value == "NOT_EXERCISED":
            reason, status = "R-3 not exercised", CellStatus.UNEXECUTED
        else:
            reason, status = f"R-3 {record.result.value}", CellStatus.FAILED
        return CellState(
            cell_id="R3", status=status, reason=reason, identity=None, specification_digest=None
        )
    inputs = evidence.inputs
    if inputs is None or inputs.r3_verification_digest != record.digest:
        return CellState(
            cell_id="R3",
            status=CellStatus.BLOCKED,
            reason=(
                "the launch-inputs record does not name this R-3 record's digest "
                "(stage b not attested)"
            ),
            identity=None,
            specification_digest=None,
        )
    return CellState(
        cell_id="R3",
        status=CellStatus.PASSED,
        reason=(
            "R-3 VERIFIED; the record attests to the current declaration and is named by the "
            "launch inputs"
        ),
        identity=None,
        specification_digest=record.digest,
    )


def _launch_state(
    cell: CellDefinition, evidence: RecordedEvidence, prepared: PreparedCell | None
) -> CellState:
    if prepared is None:
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.UNEXECUTED,
            reason="not prepared: no identity and no specification recorded for this cell",
            identity=None,
            specification_digest=None,
        )
    identity, digest = prepared.identity, prepared.specification_digest
    row = evidence.ledger.row(identity)
    if identity in evidence.unreconciled:
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.INTERRUPTED,
            reason="reserved but unrecorded: run production_launch.py --recover; never relaunch",
            identity=identity,
            specification_digest=digest,
        )
    if row is None:
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.PREPARED,
            reason="specification written; awaiting the owner's authorization and one launch",
            identity=identity,
            specification_digest=digest,
        )
    assert cell.actor is not None
    if row.kind is not LaunchKind.VERIFICATION or row.actor is not cell.actor:
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.FAILED,
            reason="the ledger row for this identity is not this cell's actor and kind",
            identity=identity,
            specification_digest=digest,
        )
    if row.outcome == "VERIFIED" and row.evidence is LedgerEvidence.RECEIPT_VERIFIED:
        return _bound_success(cell, evidence, prepared)
    if row.outcome == "VERIFIED":
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.LAUNCHED,
            reason=(
                "ledger row VERIFIED from the exit code only; the receipt has not verified "
                "(--complete-row)"
            ),
            identity=identity,
            specification_digest=digest,
        )
    if row.outcome == "REFUSED":
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.REFUSED,
            reason="the launch was refused; the identity is consumed",
            identity=identity,
            specification_digest=digest,
        )
    return CellState(
        cell_id=cell.cell_id,
        status=CellStatus.FAILED,
        reason=f"ledger outcome {row.outcome}; the identity is consumed",
        identity=identity,
        specification_digest=digest,
    )


def _unbound(cell: CellDefinition, prepared: PreparedCell, reason: str) -> CellState:
    return CellState(
        cell_id=cell.cell_id,
        status=CellStatus.UNBOUND,
        reason=reason,
        identity=prepared.identity,
        specification_digest=prepared.specification_digest,
    )


def _bound_success(
    cell: CellDefinition, evidence: RecordedEvidence, prepared: PreparedCell
) -> CellState:
    """A receipt-verified row passes only when its whole evidence chain binds and applies."""
    assert cell.actor is not None and cell.entry is not None
    identity, digest = prepared.identity, prepared.specification_digest
    reservation = evidence.reservations.get(identity)
    if reservation is None:
        return _unbound(cell, prepared, "no reservation beside the ledger for this identity")
    if (
        reservation.specification_digest != digest
        or reservation.identity != identity
        or reservation.actor is not cell.actor
        or reservation.kind is not LaunchKind.VERIFICATION
        or reservation.specification.entry is not cell.entry
    ):
        return _unbound(cell, prepared, "the reservation is not for the prepared specification")
    record = evidence.launch_records.get(identity)
    if record is None:
        return _unbound(
            cell, prepared, "no launch record for this identity in the records directory"
        )
    # The accepted launch tool's own reservation-to-record rule -- specification,
    # workload, target and verified placement -- and then the runner's stricter need:
    # a receipt-verified launch had a release, so the record carries its placement.
    binding = bind_record(reservation, record)
    if binding is not RecordBinding.BOUND:
        return _unbound(
            cell, prepared, f"the launch record does not bind to the reservation: {binding.value}"
        )
    if record.network_interface_id is None:
        return _unbound(cell, prepared, "the launch record carries no verified placement")
    expected_mode = ReleaseMode.NORMAL if cell.release_mode is None else cell.release_mode
    if reservation.specification.release_mode is not expected_mode:
        return _unbound(
            cell,
            prepared,
            "the reservation's release mode is not this cell's "
            f"({reservation.specification.release_mode.value})",
        )
    historical = _historical(cell, evidence, reservation, prepared)
    if historical is not None:
        return historical
    return CellState(
        cell_id=cell.cell_id,
        status=CellStatus.PASSED,
        reason=(
            "ledger row VERIFIED with receipt-verified evidence, bound to its reservation, "
            "launch record and the registered target"
        ),
        identity=identity,
        specification_digest=digest,
    )


def _historical(
    cell: CellDefinition,
    evidence: RecordedEvidence,
    reservation: Reservation,
    prepared: PreparedCell,
) -> CellState | None:
    """``HISTORICAL`` when the bound chain is not for the registration now in force."""
    assert cell.actor is not None
    target = reservation.specification.target
    if evidence.inputs is None:
        return _unbound(cell, prepared, "no launch-inputs record to apply the evidence against")
    try:
        current_compiled, current_target = compile_launch(
            evidence.inputs, actor=cell.actor, kind=LaunchKind.VERIFICATION
        )
        applicable = (
            current_target == target and current_compiled == reservation.specification.compiled
        )
    except (LaunchRecordError, TypeError, ValueError):
        applicable = False
    if applicable:
        return None
    return CellState(
        cell_id=cell.cell_id,
        status=CellStatus.HISTORICAL,
        reason=(
            "bound evidence for a target or placement other than the one now registered; "
            "re-verification is required (ADR-0045 s.7)"
        ),
        identity=prepared.identity,
        specification_digest=prepared.specification_digest,
    )


def _negative_state(
    cell: CellDefinition, evidence: RecordedEvidence, prepared: PreparedCell | None
) -> CellState:
    """A negative R-1 cell: the expected refusal passes, and nothing else does.

    The ledger row of a refused verification launch reads ``REFUSED`` and no more; the
    cell passes only through the whole chain -- the reservation carrying this cell's
    release mode, the launch record bound to it under the shared rule (mode included)
    with a verified placement and the launcher's own observation of the expected exit
    code, and exactly one negative launch evidence record for the launch naming the
    expected outcome with zero data-plane operations and no release -- and only against
    the registration now in force. A ``VERIFIED`` row is an unexpected success and
    ``FAILED``; another refusal, a halt, an observed data-plane operation or a task that
    reported itself released is ``FAILED``; missing, malformed or conflicting evidence
    is ``UNBOUND``. A refused negative launch is never a successful bootstrap: its row
    stays ``REFUSED`` and its identity is a ``verify-`` identity no build can select.
    """
    assert cell.actor is not None and cell.release_mode is not None
    assert cell.expected_outcome is not None
    if prepared is None:
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.UNEXECUTED,
            reason="not prepared: no identity and no specification recorded for this cell",
            identity=None,
            specification_digest=None,
        )
    identity, digest = prepared.identity, prepared.specification_digest
    row = evidence.ledger.row(identity)
    if identity in evidence.unreconciled:
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.INTERRUPTED,
            reason="reserved but unrecorded: run production_launch.py --recover; never relaunch",
            identity=identity,
            specification_digest=digest,
        )
    if row is None:
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.PREPARED,
            reason="specification written; awaiting the owner's authorization and one launch",
            identity=identity,
            specification_digest=digest,
        )
    if row.kind is not LaunchKind.VERIFICATION or row.actor is not cell.actor:
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.FAILED,
            reason="the ledger row for this identity is not this cell's actor and kind",
            identity=identity,
            specification_digest=digest,
        )
    if row.evidence is LedgerEvidence.EXIT_CODE_ONLY:
        if row.outcome in {"REFUSED", "VERIFIED"}:
            return CellState(
                cell_id=cell.cell_id,
                status=CellStatus.LAUNCHED,
                reason=(
                    f"ledger row {row.outcome} from the exit code only; the receipt has not "
                    "verified (--complete-cell)"
                ),
                identity=identity,
                specification_digest=digest,
            )
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.FAILED,
            reason=f"ledger outcome {row.outcome}; the identity is consumed",
            identity=identity,
            specification_digest=digest,
        )
    if row.outcome == "VERIFIED":
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.FAILED,
            reason=(
                "unexpected success: the task accepted a release it must have refused; "
                "the identity is consumed"
            ),
            identity=identity,
            specification_digest=digest,
        )
    if row.outcome != "REFUSED":
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.FAILED,
            reason=f"ledger outcome {row.outcome}; the identity is consumed",
            identity=identity,
            specification_digest=digest,
        )
    # REFUSED, receipt-verified: bind the chain, then hold it to the expected refusal.
    reservation = evidence.reservations.get(identity)
    if reservation is None:
        return _unbound(cell, prepared, "no reservation beside the ledger for this identity")
    if (
        reservation.specification_digest != digest
        or reservation.identity != identity
        or reservation.actor is not cell.actor
        or reservation.kind is not LaunchKind.VERIFICATION
        or reservation.specification.entry is not cell.entry
    ):
        return _unbound(cell, prepared, "the reservation is not for the prepared specification")
    if reservation.specification.release_mode is not cell.release_mode:
        return _unbound(
            cell,
            prepared,
            "the reservation's release mode is not this cell's "
            f"({reservation.specification.release_mode.value})",
        )
    record = evidence.launch_records.get(identity)
    if record is None:
        return _unbound(
            cell, prepared, "no launch record for this identity in the records directory"
        )
    binding = bind_record(reservation, record)
    if binding is not RecordBinding.BOUND:
        return _unbound(
            cell, prepared, f"the launch record does not bind to the reservation: {binding.value}"
        )
    if record.network_interface_id is None:
        return _unbound(cell, prepared, "the launch record carries no verified placement")
    if digest in evidence.malformed_negative_evidence or evidence.unreadable_negative_evidence:
        return _unbound(
            cell, prepared, "malformed or unreadable negative launch evidence in the records"
        )
    records = evidence.negative_evidence.get(digest, ())
    if not records:
        return _unbound(
            cell, prepared, "no negative launch evidence record for this launch (--complete-cell)"
        )
    distinct = {canonical_bytes(r.document()) for r in records}
    if len(distinct) != 1:
        return _unbound(
            cell, prepared, "conflicting negative launch evidence records for this launch"
        )
    found = records[0]
    if (
        found.cell_id != cell.cell_id
        or found.identity != identity
        or found.actor is not cell.actor
        or found.release_mode is not cell.release_mode
    ):
        return _unbound(cell, prepared, "the negative launch evidence is not this cell's")
    if found.receipt_outcome is not cell.expected_outcome:
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.FAILED,
            reason=(
                f"the task refused with {found.receipt_outcome.value}, not "
                f"{cell.expected_outcome.value}; the identity is consumed"
            ),
            identity=identity,
            specification_digest=digest,
        )
    expected_exit = EXIT_STATUS[cell.expected_outcome]
    if record.observed_exit_code is None:
        return _unbound(cell, prepared, "the launcher observed no terminal state for this launch")
    if record.observed_exit_code != expected_exit:
        return _unbound(
            cell,
            prepared,
            "the terminal exit code the launcher observed contradicts the receipt "
            f"({record.observed_exit_code} is not {expected_exit})",
        )
    if found.released or found.data_plane_operations is None or found.data_plane_operations:
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.FAILED,
            reason=(
                "the refused task reported a release or a data-plane operation, or measured "
                "no counts; the identity is consumed"
            ),
            identity=identity,
            specification_digest=digest,
        )
    historical = _historical(cell, evidence, reservation, prepared)
    if historical is not None:
        return historical
    return CellState(
        cell_id=cell.cell_id,
        status=CellStatus.PASSED,
        reason=(
            f"the task refused with {cell.expected_outcome.value} under a "
            f"{cell.release_mode.value} release, receipt-verified and bound to its "
            "reservation, launch record, terminal state and the registered target"
        ),
        identity=identity,
        specification_digest=digest,
    )


def resolve_verdicts(
    documents: tuple[IsolationVerdictDocument, ...],
) -> tuple[CellStatus, str]:
    """The deterministic status of one launch's verdict records, and why.

    Rules, in order: no document is ``UNEXECUTED``; any ``FAILED`` is ``FAILED``, whatever
    was recorded beside it; differing probe blocks conflict; a ``VERIFIED`` beside an
    ``INCONCLUSIVE`` whose reason a later corroboration cannot resolve conflicts; a
    ``VERIFIED`` otherwise is ``PASSED``; the rest is ``INCONCLUSIVE``. A conflict is
    ``UNBOUND``, never a pass.
    """
    if not documents:
        return CellStatus.UNEXECUTED, "no verdict recorded for this launch (--isolation-verdict)"
    verdicts = [doc.verdict for doc in documents]
    if any(v.verdict is IsolationVerdict.FAILED for v in verdicts):
        return CellStatus.FAILED, "isolation verdict FAILED: an observed connection"
    probes = {doc.probe for doc in documents}
    if len(probes) != 1:
        return CellStatus.UNBOUND, "verdict records for this launch carry different probe blocks"
    corroborated = [v for v in verdicts if v.verdict is IsolationVerdict.VERIFIED]
    inconclusive = [v for v in verdicts if v.verdict is IsolationVerdict.INCONCLUSIVE]
    if corroborated:
        unresolved = [v.reason for v in inconclusive if v.reason not in RESOLVABLE_INSUFFICIENCIES]
        if unresolved:
            return (
                CellStatus.UNBOUND,
                "a corroborated verdict contradicts an unresolvable earlier verdict: "
                + ", ".join(sorted(r.value for r in unresolved)),
            )
        return CellStatus.PASSED, "isolation verdict VERIFIED (corroborated)"
    reasons = sorted({v.reason.value for v in inconclusive})
    return CellStatus.INCONCLUSIVE, "isolation verdict INCONCLUSIVE: " + ", ".join(reasons)


def _verdict_state(
    cell: CellDefinition, evidence: RecordedEvidence, states: dict[str, CellState]
) -> CellState:
    launch = states[cell.depends_on[0]]
    if launch.status is not CellStatus.PASSED:
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.BLOCKED,
            reason=(
                f"{cell.depends_on[0]} is {launch.status.value}; "
                "the verdict needs a verified receipt"
            ),
            identity=launch.identity,
            specification_digest=launch.specification_digest,
        )
    assert launch.specification_digest is not None and cell.actor is not None
    digest = launch.specification_digest
    if evidence.unreadable_verdicts or digest in evidence.malformed_verdicts:
        status, reason = (
            CellStatus.UNBOUND,
            "a verdict record that does not parse is present; nothing is read past it",
        )
    else:
        documents = evidence.verdicts.get(digest, ())
        if any(doc.actor != cell.actor.value or doc.kind != "verification" for doc in documents):
            status, reason = (
                CellStatus.UNBOUND,
                "a verdict record for this launch names another actor or kind",
            )
        else:
            status, reason = resolve_verdicts(documents)
    return CellState(
        cell_id=cell.cell_id,
        status=status,
        reason=reason,
        identity=launch.identity,
        specification_digest=digest,
    )


def derive_states(
    evidence: RecordedEvidence, prepared: dict[str, PreparedCell]
) -> dict[str, CellState]:
    """Every required cell's status, from recorded evidence, in definition order."""
    states: dict[str, CellState] = {}
    for cell in REQUIRED_CELLS:
        blocked = [d for d in cell.depends_on if states[d].status is not CellStatus.PASSED]
        if cell.kind is CellKind.CONTROL_R3:
            states[cell.cell_id] = _r3_state(evidence)
            continue
        if cell.kind is CellKind.RUNTIME_LAUNCH:
            state = _launch_state(cell, evidence, prepared.get(cell.cell_id))
            # A launched or recorded cell keeps its recorded status; an unstarted one is
            # blocked by an unpassed prerequisite.
            if blocked and state.status in {CellStatus.UNEXECUTED, CellStatus.PREPARED}:
                state = CellState(
                    cell_id=cell.cell_id,
                    status=CellStatus.BLOCKED,
                    reason=f"prerequisite {blocked[0]} is {states[blocked[0]].status.value}",
                    identity=state.identity,
                    specification_digest=state.specification_digest,
                )
            states[cell.cell_id] = state
            continue
        if cell.kind is CellKind.ISOLATION_VERDICT:
            states[cell.cell_id] = _verdict_state(cell, evidence, states)
            continue
        if cell.kind is CellKind.NEGATIVE_LAUNCH:
            state = _negative_state(cell, evidence, prepared.get(cell.cell_id))
            if blocked and state.status in {CellStatus.UNEXECUTED, CellStatus.PREPARED}:
                state = CellState(
                    cell_id=cell.cell_id,
                    status=CellStatus.BLOCKED,
                    reason=f"prerequisite {blocked[0]} is {states[blocked[0]].status.value}",
                    identity=state.identity,
                    specification_digest=state.specification_digest,
                )
            states[cell.cell_id] = state
            continue
        assert cell.kind is CellKind.PERMISSION_MATRIX
        if blocked:
            states[cell.cell_id] = CellState(
                cell_id=cell.cell_id,
                status=CellStatus.BLOCKED,
                reason=f"prerequisite {blocked[0]} is {states[blocked[0]].status.value}",
                identity=None,
                specification_digest=None,
            )
            continue
        states[cell.cell_id] = _permission_state(cell, evidence, states)
    return states


#: The cell status each subcell status contributes, in precedence order: the first status
#: any subcell holds decides the cell. A cell is PASSED only when every subcell is.
_SUBCELL_PRECEDENCE: Final[tuple[tuple[SubcellStatus, CellStatus], ...]] = (
    (SubcellStatus.FAILED, CellStatus.FAILED),
    (SubcellStatus.UNBOUND, CellStatus.UNBOUND),
    (SubcellStatus.BLOCKED, CellStatus.BLOCKED),
    (SubcellStatus.INTERRUPTED, CellStatus.INTERRUPTED),
    (SubcellStatus.HISTORICAL, CellStatus.HISTORICAL),
    (SubcellStatus.CLEANUP_UNRESOLVED, CellStatus.INCONCLUSIVE),
    (SubcellStatus.UNDECIDED, CellStatus.INCONCLUSIVE),
    # A launched probe whose receipt is not yet verified (proposed ADR-0048): the cell
    # is INCONCLUSIVE until the record is completed -- never PASSED on an exit code.
    (SubcellStatus.AWAITING_RECEIPT, CellStatus.INCONCLUSIVE),
    (SubcellStatus.AWAITING_R1, CellStatus.UNEXECUTED),
    (SubcellStatus.UNEXECUTED, CellStatus.UNEXECUTED),
)


def _permission_state(
    cell: CellDefinition, evidence: RecordedEvidence, states: dict[str, CellState]
) -> CellState:
    """A permission cell from its subcells: PASSED only when every subcell is.

    Every other status is decided by precedence over the subcells' statuses -- a
    failed subcell fails the cell whatever the others read; a blocked subcell (the
    deletion role with no execution path) blocks it;
    unresolved cleanup or an undecided answer leaves it INCONCLUSIVE. Empty, partial,
    simulated or blocked coverage never passes.
    """
    r1_passed = {
        ProductionActor.ACQUISITION: states["R1-ACQ-BOOTSTRAP"].status is CellStatus.PASSED,
        ProductionActor.BUILD: states["R1-BLD-BOOTSTRAP"].status is CellStatus.PASSED,
    }
    subcells = tuple(
        derive_subcell(s, evidence.permission, r1_passed=r1_passed)
        for s in subcells_of(cell.cell_id)
    )
    counts = {status: sum(1 for s in subcells if s.status is status) for status in SubcellStatus}
    summary = " ".join(f"{s.value.lower()}={n}" for s, n in counts.items() if n)
    if subcells and all(s.status is SubcellStatus.PASSED for s in subcells):
        return CellState(
            cell_id=cell.cell_id,
            status=CellStatus.PASSED,
            reason=f"every subcell matched under the current binding ({summary})",
            identity=None,
            specification_digest=None,
            subcells=subcells,
        )
    for subcell_status, cell_status in _SUBCELL_PRECEDENCE:
        if counts.get(subcell_status):
            first = next(s for s in subcells if s.status is subcell_status)
            return CellState(
                cell_id=cell.cell_id,
                status=cell_status,
                reason=f"{first.subcell_id} {first.status.value}: {first.reason} ({summary})",
                identity=None,
                specification_digest=None,
                subcells=subcells,
            )
    return CellState(
        cell_id=cell.cell_id,
        status=CellStatus.UNEXECUTED,
        reason=cell.execution,
        identity=None,
        specification_digest=None,
        subcells=subcells,
    )


def aggregate(states: dict[str, CellState]) -> AggregateStatus:
    """VERIFIED only when every required cell PASSED; FAILED on any FAILED; else INCOMPLETE."""
    values = [state.status for state in states.values()]
    if any(v is CellStatus.FAILED for v in values):
        return AggregateStatus.FAILED
    if all(v is CellStatus.PASSED for v in values):
        return AggregateStatus.VERIFIED
    return AggregateStatus.INCOMPLETE


def matrix_lines(states: dict[str, CellState]) -> list[str]:
    """The completion matrix, one sanitized line per cell and the aggregate. No identity."""
    lines = []
    for cell in REQUIRED_CELLS:
        state = states[cell.cell_id]
        lines.append(
            f"cell={cell.cell_id} ref={cell.cell_ref} kind={cell.kind.value} "
            f"status={state.status.value}"
        )
        for sub in state.subcells:
            lines.append(f"  subcell={sub.subcell_id} status={sub.status.value}")
    counts = {
        status: sum(1 for s in states.values() if s.status is status) for status in CellStatus
    }
    summary = " ".join(f"{status.value.lower()}={n}" for status, n in counts.items() if n)
    lines.append(f"aggregate={aggregate(states).value} {summary}")
    return lines


__all__ = [
    "CELLS_CONTRACT_ID",
    "CELL_BY_ID",
    "MAX_NEGATIVE_EVIDENCE_BYTES",
    "NEGATIVE_EVIDENCE_CONTRACT_ID",
    "REQUIRED_CELLS",
    "AggregateStatus",
    "CellDefinition",
    "CellKind",
    "CellState",
    "CellStatus",
    "CellsDocumentError",
    "NegativeLaunchEvidence",
    "PreparedCell",
    "RecordedEvidence",
    "aggregate",
    "cells_document",
    "definition",
    "derive_states",
    "matrix_lines",
    "negative_evidence_document",
    "parse_cells_document",
    "parse_negative_launch_evidence",
    "resolve_verdicts",
]
