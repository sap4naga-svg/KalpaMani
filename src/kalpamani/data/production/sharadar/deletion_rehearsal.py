"""The deletion rehearsal path: implemented offline, closed (ADR-0048 s.4; ADR-0049 s.3;
proposed ADR-0050 makes the decision concrete).

ADR-0048 s.4 designed how the two R-8 subcells the catalogue keeps BLOCKED would be exercised
**under the actual deletion role**: a rehearsal task family whose task role *is* the deletion
role, launched by a rehearsal launcher that passes exactly that role to ECS (no human ever
assumes it), over a rehearsal input that names one exact synthetic object the accepted R-4
human ``PutObject`` subcell established. This module is that path's offline implementation:
the target rule, the statement and its authorization, the durable consumption before any
mutation, the engine that issues the subcells' operations over an injected client acting as
the deletion role, the record, and the reading that turns records and the control principal's
cleanup into a pass, a failure or an inconclusive result.

**Implementation availability is not authority to execute.** :data:`REHEARSAL_PATH_OPEN` is
``False``: opening the path reverses a verified ADR-0007 property (no execution path exists
for the deletion role) and is the governance decision ADR-0049 D-1 presents (made concrete
by proposed ADR-0050) to the owner. While it is ``False`` the catalogue keeps both subcells
BLOCKED, the tools refuse the rehearsal, the rehearsal family, entry, launcher and role delta
are declared only INERT (proposed ADR-0050, behind a variable that is false by default), and
the engine's callers are this repository's tests over fakes and the rehearsal task
composition, itself reachable only from that closed path. **Nothing here broadens the
deletion role's existing authority** (its S3 statements are unchanged by this module), and
nothing here is a general deletion utility: the engine deletes exactly the one key the bound
R-4 record names, under a consumed authorization naming that key, and refuses any other.

**Mocked results are not AWS verification.** Every answer in this repository's tests is a fake's.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar.documents import exact_str, hex_digest, instant
from kalpamani.data.production.sharadar.launch_records import RECORD_SCHEMA_VERSION
from kalpamani.data.production.sharadar.permission_cells import (
    SUBCELL_BY_ID,
    SYNTHETIC_MARKER,
    BoundChain,
    ChainError,
    Layer,
    Operation,
    PermissionBinding,
    PermissionCleanup,
    PermissionClient,
    PermissionEvidence,
    Principal,
    _binding_from,
    bind_result,
    classify,
)
from kalpamani.data.production.sharadar.permission_probe import SubcellOutcome
from kalpamani.data.production.sharadar.r3_verification import Observation, ObservedClass
from kalpamani.data.production.sharadar.receipt_collector import (
    REHEARSAL_CONTAINER as _REHEARSAL_CONTAINER,
)

#: The governance decision that would open the path. ``False`` until that decision is
#: accepted; flipping it is that decision's implementation and nothing else's.
REHEARSAL_PATH_OPEN: Final = False
REHEARSAL_DECISION: Final = "ADR-0049 D-1"
#: The resources the accepted decision would declare (ADR-0048 s.4). Named here so the
#: declaration, when made, is held to these exact values; none exists today.
REHEARSAL_FAMILY: Final = "kalpamani-deletion-rehearsal"
REHEARSAL_ENTRY: Final = "kalpamani-deletion-rehearsal"
REHEARSAL_CONTAINER: Final = _REHEARSAL_CONTAINER
REHEARSAL_STREAM_PREFIX: Final = "production-deletion-rehearsal"
REHEARSAL_LAUNCHER_PERMISSION_SET: Final = "KalpaManiDeletionRehearse"
#: The one named profile the rehearsal launcher is invoked under (routing input, not
#: proof: the identity is proven by ``sts:GetCallerIdentity`` against the binding).
REHEARSAL_LAUNCHER_PROFILE: Final = "kalpamani-deletion-rehearse"
REHEARSAL_PARAMETER_PREFIX: Final = "/kalpamani/production/deletion/"
REHEARSAL_BINDING_PARAMETER: Final = REHEARSAL_PARAMETER_PREFIX + "runtime-binding"
REHEARSAL_INPUT_PARAMETER: Final = REHEARSAL_PARAMETER_PREFIX + "input"
REHEARSAL_RELEASE_PARAMETER: Final = REHEARSAL_PARAMETER_PREFIX + "release"
REHEARSAL_BINDING_CONTRACT_ID: Final = "kalpamani-deletion-runtime-binding/v1"
#: The two subcells, in the only admissible order: the read refusal first, while the object
#: still exists; the list-and-delete second, which removes it.
REHEARSAL_SEQUENCE: Final[tuple[str, ...]] = ("R8-GET", "R8-LIST-AND-DELETE")
#: The one subcell whose bound record establishes the rehearsal's exact target.
REHEARSAL_PREREQUISITE: Final = "R4-PUT-PAYLOAD-HUMAN"
REHEARSAL_CONSUMPTION_KIND: Final = "deletion_rehearsal_authorization"
REHEARSAL_STATEMENT_CONTRACT_ID: Final = "kalpamani-deletion-rehearsal-statement/v1"
REHEARSAL_RECORD_CONTRACT_ID: Final = "kalpamani-deletion-rehearsal-record/v1"
#: Operations per subcell: R8-GET one; R8-LIST-AND-DELETE at most two.
REHEARSAL_OPERATION_BUDGET: Final = 2


class RehearsalDefect(StrEnum):
    """Why a rehearsal cannot be prepared or read. Closed."""

    PATH_CLOSED = "PATH_CLOSED"
    NOT_A_REHEARSAL_SUBCELL = "NOT_A_REHEARSAL_SUBCELL"
    PREREQUISITE_UNBOUND = "PREREQUISITE_UNBOUND"
    PREREQUISITE_NOT_SYNTHETIC = "PREREQUISITE_NOT_SYNTHETIC"
    PREREQUISITE_SETTLED = "PREREQUISITE_SETTLED"
    SEQUENCE_VIOLATED = "SEQUENCE_VIOLATED"
    STATEMENT_MISMATCH = "STATEMENT_MISMATCH"


class RehearsalError(ValueError):
    def __init__(self, defect: RehearsalDefect) -> None:
        super().__init__(defect.value)
        self.defect = defect


class RehearsalOutcome(StrEnum):
    """What one rehearsed subcell established. Closed."""

    PASS = "PASS"  # noqa: S105 - a closed outcome token, not a credential
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class RehearsalStatus(StrEnum):
    """The derived reading of one rehearsal record with the control principal's cleanup."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    CLEANUP_UNRESOLVED = "CLEANUP_UNRESOLVED"
    RESIDUE = "RESIDUE"


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalTarget:
    """The one object a rehearsal may touch: the exact bucket and key the bound
    R-4 human ``PutObject`` record created, and the digest of that record."""

    bucket: str
    key: str
    prerequisite_sha256: str

    def __repr__(self) -> str:
        return "RehearsalTarget(<one synthetic object>)"

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.document()))

    def document(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "key": self.key,
            "prerequisite_sha256": self.prerequisite_sha256,
        }


def _is_synthetic_marker_key(key: str) -> bool:
    """Whether ``key`` is the synthetic marker's own content address under a production
    Bronze namespace -- the only object the R-4 human ``PutObject`` subcell ever creates."""
    return (
        key.startswith("bronze/sharadar/")
        and "/production/objects/sha256/" in key
        and key.endswith("/objects/sha256/" + sha256_hex(SYNTHETIC_MARKER))
    )


def rehearsal_target(evidence: PermissionEvidence) -> RehearsalTarget:
    """The rehearsal's exact target from the evidence, or ``RehearsalError``.

    Exactly one bound (:func:`bind_result`), MATCHED R-4 human ``PutObject`` record under
    the current binding whose created key is the synthetic marker's own content address
    under a production Bronze namespace, not yet confirmed absent by an admissible cleanup.
    A record that does not bind, that created nothing, whose key is not the synthetic one,
    or whose object a cleanup already settled establishes no target: the rehearsal never
    derives a key from anything else.
    """
    binding = evidence.binding
    if binding is None:
        raise RehearsalError(RehearsalDefect.PREREQUISITE_UNBOUND)
    candidates: list[BoundChain] = []
    for record in evidence.records.get(REHEARSAL_PREREQUISITE, ()):
        if record.binding != binding or record.outcome is not SubcellOutcome.MATCHED:
            continue
        if record.created_key is None or record.created_bucket is None:
            continue
        try:
            candidates.append(bind_result(record, evidence))
        except ChainError:
            continue
    if len(candidates) != 1:
        raise RehearsalError(RehearsalDefect.PREREQUISITE_UNBOUND)
    chain = candidates[0]
    record = chain.record
    assert record.created_key is not None and record.created_bucket is not None
    if not _is_synthetic_marker_key(record.created_key):
        raise RehearsalError(RehearsalDefect.PREREQUISITE_NOT_SYNTHETIC)
    if any(
        c.admissible_for(binding, not_before=record.finished_at)
        and c.settles_object(record.attempt_sha256, record.created_bucket, record.created_key)
        for c in evidence.cleanups
    ):
        raise RehearsalError(RehearsalDefect.PREREQUISITE_SETTLED)
    return RehearsalTarget(
        bucket=record.created_bucket, key=record.created_key, prerequisite_sha256=record.digest
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalStatement:
    """What one authorization binds: the subcell, the principal, the operation, the exact
    target, the position in the sequence, the stamp and the binding. Its digest is what the
    owner's authorization names."""

    subcell_id: str
    target: RehearsalTarget
    stamp: str
    binding: PermissionBinding

    def __post_init__(self) -> None:
        if self.subcell_id not in REHEARSAL_SEQUENCE:
            raise RehearsalError(RehearsalDefect.NOT_A_REHEARSAL_SUBCELL)

    @property
    def cell(self) -> Any:
        return SUBCELL_BY_ID[self.subcell_id]

    def document(self) -> dict[str, Any]:
        cell = self.cell
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": REHEARSAL_STATEMENT_CONTRACT_ID,
            "subcell_id": self.subcell_id,
            "principal": Principal.DELETION_ROLE.value,
            "operation": cell.operation.value,
            "expectation": cell.expectation.value,
            "sequence_position": REHEARSAL_SEQUENCE.index(self.subcell_id),
            "target": self.target.document(),
            "target_sha256": self.target.digest,
            "stamp": self.stamp,
            "binding": self.binding.document(),
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.document()))


def prepare_rehearsal(
    subcell_id: str, evidence: PermissionEvidence, *, stamp: str, earlier: Iterable[str] = ()
) -> RehearsalStatement:
    """The statement for one rehearsal subcell, or refuse; the sequence is enforced here.

    ``earlier`` names the rehearsal subcells already recorded PASS under this binding:
    R8-LIST-AND-DELETE is preparable only after R8-GET, because the read refusal must be
    observed while the object still exists.
    """
    if subcell_id not in REHEARSAL_SEQUENCE:
        raise RehearsalError(RehearsalDefect.NOT_A_REHEARSAL_SUBCELL)
    position = REHEARSAL_SEQUENCE.index(subcell_id)
    if any(prior not in set(earlier) for prior in REHEARSAL_SEQUENCE[:position]):
        raise RehearsalError(RehearsalDefect.SEQUENCE_VIOLATED)
    target = rehearsal_target(evidence)
    binding = evidence.binding
    assert binding is not None
    return RehearsalStatement(subcell_id=subcell_id, target=target, stamp=stamp, binding=binding)


@dataclass(frozen=True, slots=True, kw_only=True)
class RehearsalRecord:
    """What one rehearsed subcell established, classes and counts only.

    ``observed`` are the classes of each operation in order (R8-GET: the read; R8-LIST-AND-
    DELETE: the list, then the delete when the list allowed it); ``possibly_deleted`` says
    the delete's answer left the removal open, which only the control principal's later
    cleanup settles; ``deleted`` says the service acknowledged the removal (a 204), which
    is still not confirmation -- the cleanup's ``HeadObject`` is.
    """

    subcell_id: str
    statement_sha256: str
    authorization_sha256: str
    target: RehearsalTarget
    observed: tuple[ObservedClass, ...]
    outcome: RehearsalOutcome
    deleted: bool
    possibly_deleted: bool
    operations: int
    identity_verified: bool
    stamp: str
    started_at: datetime
    finished_at: datetime
    binding: PermissionBinding

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": REHEARSAL_RECORD_CONTRACT_ID,
            "subcell_id": self.subcell_id,
            "statement_sha256": self.statement_sha256,
            "authorization_sha256": self.authorization_sha256,
            "target": self.target.document(),
            "observed": [o.value for o in self.observed],
            "outcome": self.outcome.value,
            "deleted": self.deleted,
            "possibly_deleted": self.possibly_deleted,
            "operations": self.operations,
            "identity_verified": self.identity_verified,
            "stamp": self.stamp,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "binding": self.binding.document(),
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.document()))

    @property
    def object_open(self) -> bool:
        """Whether the target still needs settling: deleted or possibly deleted, the
        control principal confirms; an untouched object stays the prerequisite's."""
        return self.deleted or self.possibly_deleted


_DENIED: Final[frozenset[ObservedClass]] = frozenset(
    {
        ObservedClass.DENIED_RESOURCE_POLICY,
        ObservedClass.DENIED_IDENTITY_POLICY,
        ObservedClass.DENIED_OTHER,
    }
)


def _decide(
    expected: ObservedClass, observed: ObservedClass, *, expect_allow: bool
) -> RehearsalOutcome:
    if observed is expected:
        return RehearsalOutcome.PASS
    if expect_allow:
        return RehearsalOutcome.FAIL if observed in _DENIED else RehearsalOutcome.INCONCLUSIVE
    # A refusal is expected: any success class is a failure; anything else decides nothing.
    if observed in (ObservedClass.OK_200, ObservedClass.OK_204):
        return RehearsalOutcome.FAIL
    return RehearsalOutcome.INCONCLUSIVE


def rehearse_subcell(
    statement: RehearsalStatement,
    *,
    authorization_sha256: str,
    client: PermissionClient,
    identity_verified: bool,
    now: datetime,
    finished: datetime,
) -> RehearsalRecord:
    """Issue one rehearsal subcell's operations over ``client`` -- the deletion role's.

    The authorization must already be consumed durably (the caller's store); nothing here
    consumes or checks it. R8-GET: one ``GetObject`` of the exact key, a denial passes, a
    body-returning answer fails (the role could read), anything else decides nothing.
    R8-LIST-AND-DELETE: one ``ListObjectsV2`` (``MaxKeys=1``) then, only when the list was
    allowed, one ``DeleteObject`` of the exact key: a 200 then a 204 pass pending the
    control principal's confirmation; a denial on either fails; an ambiguous delete leaves
    the removal open (``possibly_deleted``) and decides nothing. No retry, no second key.
    """
    cell = statement.cell
    target = statement.target
    observed: list[ObservedClass] = []
    deleted = possibly = False
    if cell.operation is Operation.S3_GET:
        answer: Observation = client.get_object(target.bucket, target.key)
        observed.append(classify(answer))
        outcome = _decide(ObservedClass.DENIED_OTHER, observed[0], expect_allow=False)
        if observed[0] in _DENIED:
            outcome = RehearsalOutcome.PASS
    else:
        listed = classify(client.list_objects(target.bucket))
        observed.append(listed)
        if listed is not ObservedClass.OK_200:
            outcome = _decide(ObservedClass.OK_200, listed, expect_allow=True)
        else:
            removed = classify(client.delete_object(target.bucket, target.key))
            observed.append(removed)
            outcome = _decide(ObservedClass.OK_204, removed, expect_allow=True)
            deleted = removed is ObservedClass.OK_204
            possibly = outcome is RehearsalOutcome.INCONCLUSIVE
    return RehearsalRecord(
        subcell_id=statement.subcell_id,
        statement_sha256=statement.digest,
        authorization_sha256=authorization_sha256,
        target=target,
        observed=tuple(observed),
        outcome=outcome,
        deleted=deleted,
        possibly_deleted=possibly,
        operations=len(observed),
        identity_verified=identity_verified,
        stamp=statement.stamp,
        started_at=now,
        finished_at=finished,
        binding=statement.binding,
    )


def derive_rehearsal(
    record: RehearsalRecord, cleanups: Iterable[PermissionCleanup], *, prerequisite_attempt: str
) -> tuple[RehearsalStatus, str]:
    """The reading of one rehearsal record with the control principal's cleanup passes.

    A record whose identity was not verified, or whose outcome decided nothing, never
    reads PASSED. A deleted or possibly deleted object must be confirmed absent by an
    admissible later cleanup naming the prerequisite attempt and the exact key
    (``CLEANUP_UNRESOLVED`` until then); an object a cleanup could not settle is RESIDUE.
    """
    if not record.identity_verified:
        return RehearsalStatus.INCONCLUSIVE, "the deletion role's identity was not verified"
    if record.outcome is RehearsalOutcome.FAIL:
        return RehearsalStatus.FAILED, f"observed {[o.value for o in record.observed]}"
    later = [c for c in cleanups if c.admissible_for(record.binding, not_before=record.finished_at)]
    if record.object_open:
        settled = any(
            c.settles_object(prerequisite_attempt, record.target.bucket, record.target.key)
            for c in later
        )
        if not settled:
            residue = any(
                any(
                    k.attempt_sha256 == prerequisite_attempt
                    and k.key == record.target.key
                    and not k.confirmed_absent
                    for k in c.keys
                )
                for c in later
            )
            if residue:
                return (
                    RehearsalStatus.RESIDUE,
                    "the control principal could not confirm the object absent",
                )
            return (
                RehearsalStatus.CLEANUP_UNRESOLVED,
                "the removal is not confirmed by a later verified cleanup naming the exact key",
            )
    if record.outcome is RehearsalOutcome.INCONCLUSIVE:
        return RehearsalStatus.INCONCLUSIVE, f"observed {[o.value for o in record.observed]}"
    return RehearsalStatus.PASSED, f"observed {[o.value for o in record.observed]} as expected"


_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
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
        "started_at",
        "finished_at",
        "binding",
    }
)


def parse_rehearsal_record(raw: object) -> RehearsalRecord:
    """A rehearsal record, parsed closed."""
    from kalpamani.data.production.sharadar.documents import decode_document
    from kalpamani.data.production.sharadar.permission_cells import MAX_PERMISSION_RECORD_BYTES

    document = (
        raw if type(raw) is dict else decode_document(raw, max_bytes=MAX_PERMISSION_RECORD_BYTES)
    )
    if type(document) is not dict or set(document) != _RECORD_FIELDS:
        raise ValueError("rehearsal record: closed field set")
    if (
        document["schema_version"] != RECORD_SCHEMA_VERSION
        or document["contract_id"] != REHEARSAL_RECORD_CONTRACT_ID
    ):
        raise ValueError("rehearsal record: contract")
    subcell_id = exact_str(document["subcell_id"])
    if subcell_id not in REHEARSAL_SEQUENCE:
        raise ValueError("rehearsal record: subcell")
    target = document["target"]
    if type(target) is not dict or set(target) != {"bucket", "key", "prerequisite_sha256"}:
        raise ValueError("rehearsal record: target")
    bucket, key = exact_str(target["bucket"]), exact_str(target["key"])
    prerequisite = hex_digest(target["prerequisite_sha256"])
    statement = hex_digest(document["statement_sha256"])
    authorization = hex_digest(document["authorization_sha256"])
    stamp = exact_str(document["stamp"])
    started, finished = instant(document["started_at"]), instant(document["finished_at"])
    observed_raw = document["observed"]
    if (
        bucket is None
        or key is None
        or prerequisite is None
        or statement is None
        or authorization is None
        or stamp is None
        or started is None
        or finished is None
        or type(observed_raw) is not list
        or not 1 <= len(observed_raw) <= REHEARSAL_OPERATION_BUDGET
        or any(exact_str(o) not in {m.value for m in ObservedClass} for o in observed_raw)
        or exact_str(document["outcome"]) not in {m.value for m in RehearsalOutcome}
        or type(document["deleted"]) is not bool
        or type(document["possibly_deleted"]) is not bool
        or type(document["identity_verified"]) is not bool
        or type(document["operations"]) is not int
        or document["operations"] != len(observed_raw)
    ):
        raise ValueError("rehearsal record: field")
    return RehearsalRecord(
        subcell_id=subcell_id,
        statement_sha256=statement,
        authorization_sha256=authorization,
        target=RehearsalTarget(bucket=bucket, key=key, prerequisite_sha256=prerequisite),
        observed=tuple(ObservedClass(str(o)) for o in observed_raw),
        outcome=RehearsalOutcome(str(document["outcome"])),
        deleted=document["deleted"],
        possibly_deleted=document["possibly_deleted"],
        operations=document["operations"],
        identity_verified=document["identity_verified"],
        stamp=stamp,
        started_at=started,
        finished_at=finished,
        binding=_binding_from(document["binding"]),
    )


def rehearsal_blocked() -> bool:
    """Whether the catalogue keeps the two R-8 subcells BLOCKED: exactly while the path is
    closed. Held by a governance test to the catalogue and to this constant together."""
    blocked = all(SUBCELL_BY_ID[s].layer is Layer.BLOCKED for s in REHEARSAL_SEQUENCE)
    return blocked and not REHEARSAL_PATH_OPEN


__all__ = [
    "REHEARSAL_BINDING_CONTRACT_ID",
    "REHEARSAL_BINDING_PARAMETER",
    "REHEARSAL_CONSUMPTION_KIND",
    "REHEARSAL_CONTAINER",
    "REHEARSAL_DECISION",
    "REHEARSAL_ENTRY",
    "REHEARSAL_FAMILY",
    "REHEARSAL_INPUT_PARAMETER",
    "REHEARSAL_LAUNCHER_PERMISSION_SET",
    "REHEARSAL_LAUNCHER_PROFILE",
    "REHEARSAL_OPERATION_BUDGET",
    "REHEARSAL_PARAMETER_PREFIX",
    "REHEARSAL_PATH_OPEN",
    "REHEARSAL_PREREQUISITE",
    "REHEARSAL_RECORD_CONTRACT_ID",
    "REHEARSAL_RELEASE_PARAMETER",
    "REHEARSAL_SEQUENCE",
    "REHEARSAL_STATEMENT_CONTRACT_ID",
    "REHEARSAL_STREAM_PREFIX",
    "RehearsalDefect",
    "RehearsalError",
    "RehearsalOutcome",
    "RehearsalRecord",
    "RehearsalStatement",
    "RehearsalStatus",
    "RehearsalTarget",
    "derive_rehearsal",
    "parse_rehearsal_record",
    "prepare_rehearsal",
    "rehearsal_blocked",
    "rehearsal_target",
    "rehearse_subcell",
]
