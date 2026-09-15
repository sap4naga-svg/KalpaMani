"""The launch tool's durable state on the owner's workstation: reservations, lock, atomic ledger.

**Proposed ADR-0045 §6 — offline, exercised only against a temporary directory.** The
owner ledger is the record of every identity ever consumed; this module is how the tool
makes that record **durable before any external mutation** and **consistent across
concurrent or interrupted attempts**, on the filesystem the owner actually uses (NTFS on
Windows; the same primitives hold on POSIX).

Three primitives, each the narrowest the platform offers, **every one of them anchored
to the ledger and to nothing else**:

- **an exclusive reservation** -- ``<ledger>.reservations/<identity>.json`` beside the
  ledger, created with ``O_CREAT | O_EXCL``, which the platform makes atomic: two
  attempts on one identity cannot both create it, whatever their timing. The file
  carries the **launch specification** the identity was reserved for (and its digest,
  the value the authorization named), so that recovery and the isolation verdict read
  the placement and workload that were authorized rather than a freshly supplied
  file. It is **never deleted and never expires**: a reservation left by an interrupted
  attempt is exactly the case it exists for, and the only way past it is
  :func:`recover`, which writes the ledger row and launches nothing;
- **an exclusive lock** on the ledger -- ``<ledger>.lock`` created the same way, held
  across every read-modify-write and released in a ``finally``; a lock that already
  exists refuses (``LEDGER_LOCKED``). **The tool never removes another process's lock**:
  a stale one (a crash while holding it) is the owner's to inspect and remove, after
  confirming no tool process runs -- stated as a limit, not automated away;
- **an atomic ledger replacement** -- the new ledger is written to a fresh temporary
  file beside the old one, flushed and synced, then ``os.replace``d over it, so a reader
  sees the old bytes or the new bytes and never a partial write. Under the lock the
  read-modify-write cannot lose an update; belt and braces, the replacement also refuses
  when the ledger's bytes changed since they were read (``LEDGER_CHANGED``).

**Durability guarantees and their limits, stated.** A reservation or a ledger
replacement is durable once ``fsync`` returns; a power loss before that can lose it, and
a lost reservation with no ledger row means an identity the next attempt cannot see --
which is why the reservation is written **before** any bootstrap or client, so an
interruption after it always leaves it behind. Directory entries are not separately
synced on Windows (``os.fsync`` takes no directory handle there). ``os.replace`` needs
both paths on one volume and can fail while another process holds the destination open
with a conflicting share mode; either failure refuses the write and leaves the old
ledger intact and the reservation in place. None of this is a claim about ECS: a task
that started before an interruption ran to whatever end it reached, and recovery records
that the tool does not know which.

**Record filenames cannot collide.** Evidence and launch records are created with
``O_EXCL`` under a name carrying the instant, the identity kind and eight random hex
digits, and a name that already exists is retried with fresh random digits -- never
overwritten.

**The records directory is an evidence destination and nothing more.** The ledger's
identity is its resolved path (``Path.resolve``: absolute, symlinks followed, the
platform's own spelling of an existing path), and the reservations and the lock hang off
that path. A different ``--records-dir`` -- another folder, a relative spelling, another
case on a case-insensitive volume -- names a different place to put evidence and the
same ledger, the same reservations and the same lock; it cannot hide pending recovery
and cannot let an identity be consumed twice. **Legacy state:** the first revision kept
reservations under ``<records-dir>/reservations``. No launch has ever run against AWS,
so no real reservation exists there; still, a ``reservations`` directory with any entry
under the supplied records directory refuses (``LEGACY_RESERVATIONS_PRESENT``) until
the owner has moved its files, by hand and unchanged, beside the ledger -- the tool
neither reads, moves, migrates nor deletes them, and it scans no directory it was not
handed. A reservation written under the first revision's schema is refused as
malformed rather than read: it carried no specification.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.production.sharadar.documents import decode_document, exact_str, instant
from kalpamani.data.production.sharadar.keys import RUN_ID_RE
from kalpamani.data.production.sharadar.launch_records import (
    MAX_RECORD_BYTES,
    RECORD_SCHEMA_VERSION,
    LaunchKind,
    LaunchRecord,
    LaunchRecordError,
    LaunchSpecification,
    OwnerLedger,
    parse_owner_ledger,
    parse_specification,
)
from kalpamani.data.production.sharadar.vocabulary import ProductionActor

RESERVATION_CONTRACT_ID: Final = "kalpamani-launch-reservation/v1"
#: The suffix appended to the ledger's file name for its reservations directory.
RESERVATIONS_SUFFIX: Final = ".reservations"
#: The suffix appended to the ledger's file name for its exclusive lock.
LOCK_SUFFIX: Final = ".lock"
#: Where the first revision kept reservations, relative to the records directory. Refused.
LEGACY_RESERVATIONS_DIRECTORY: Final = "reservations"
#: How many fresh random names are tried before a record write is refused.
MAX_NAME_ATTEMPTS: Final = 8
#: Beside the ledger, the consumed authorizations (ADR-0047): one exclusive file
#: per authorization digest, created before the operation it authorizes.
CONSUMED_SUFFIX: Final = ".consumed"

_HEX_64: Final = frozenset("0123456789abcdef")
_RESERVATION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "identity",
        "actor",
        "kind",
        "specification_digest",
        "specification",
        "reserved_at",
    }
)


class StoreDefect(StrEnum):
    """Why a store operation refused. Closed; carries no path."""

    LEDGER_LOCKED = "LEDGER_LOCKED"
    LEDGER_CHANGED = "LEDGER_CHANGED"
    LEDGER_UNREADABLE = "LEDGER_UNREADABLE"
    RESERVATION_EXISTS = "RESERVATION_EXISTS"
    RESERVATION_MALFORMED = "RESERVATION_MALFORMED"
    RESERVATION_MISSING = "RESERVATION_MISSING"
    WRITE_FAILED = "WRITE_FAILED"
    NAME_EXHAUSTED = "NAME_EXHAUSTED"
    LEGACY_RESERVATIONS_PRESENT = "LEGACY_RESERVATIONS_PRESENT"
    AUTHORIZATION_CONSUMED = "AUTHORIZATION_CONSUMED"


class StoreError(Exception):
    """A refusal built from one closed member and nothing else."""

    __slots__ = ("defect",)

    def __init__(self, defect: StoreDefect) -> None:
        """Carry the defect."""
        self.defect = defect
        super().__init__(f"launch store: {defect.value}")


def _refuse(defect: StoreDefect) -> StoreError:
    return StoreError(defect)


@dataclass(frozen=True, slots=True, kw_only=True)
class Reservation:
    """One consumed identity: the launch specification it was reserved for, and when.

    The specification is the whole authorized document, so its placement and workload
    are read back from here -- the durable, exclusive artifact -- by recovery and by the
    isolation verdict; ``specification_digest`` is its digest, the value the
    authorization named.
    """

    identity: str
    actor: ProductionActor
    kind: LaunchKind
    specification: LaunchSpecification
    reserved_at: datetime

    def __post_init__(self) -> None:
        """The reservation names the specification's own identity, actor and kind."""
        if (
            self.specification.identity != self.identity
            or self.specification.actor is not self.actor
            or self.specification.kind is not self.kind
        ):
            raise ValueError("a reservation names its specification's identity, actor and kind")

    @property
    def specification_digest(self) -> str:
        """The digest the authorization named."""
        return self.specification.digest

    def document(self) -> dict[str, Any]:
        """The reservation document."""
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": RESERVATION_CONTRACT_ID,
            "identity": self.identity,
            "actor": self.actor.value,
            "kind": self.kind.value,
            "specification_digest": self.specification_digest,
            "specification": self.specification.document(),
            "reserved_at": self.reserved_at.isoformat(),
        }

    def __repr__(self) -> str:
        """Kind only."""
        return f"Reservation(kind={self.kind.value!r})"


class RecordBinding(StrEnum):
    """How a launch record relates to the reservation of its identity. Closed."""

    #: The record is this reservation's launch: specification, workload, target and
    #: any verified placement all agree.
    BOUND = "BOUND"
    #: Another specification: digest, actor, kind or entry differ.
    SPECIFICATION_MISMATCH = "SPECIFICATION_MISMATCH"
    #: The acquisition slice or plan digest is not the specification's workload.
    WORKLOAD_MISMATCH = "WORKLOAD_MISMATCH"
    #: The revision, image, configuration or commit is not the specification's target.
    TARGET_MISMATCH = "TARGET_MISMATCH"
    #: The verified subnet or security groups are not the specification's placement.
    PLACEMENT_MISMATCH = "PLACEMENT_MISMATCH"
    #: The specification cannot be compiled, so nothing can be held to it.
    UNCOMPILABLE = "UNCOMPILABLE"
    #: The record's release mode is not the one the specification authorized.
    MODE_MISMATCH = "MODE_MISMATCH"


def bind_record(reservation: Reservation, record: LaunchRecord) -> RecordBinding:
    """The one binding rule between a reservation and a launch record.

    The record names the specification digest the authorization named; the reservation
    beside the ledger carries that specification. They bind when the digests, actor,
    kind and entry agree; when the record's slice and plan digest are exactly the
    specification's workload (``None`` for a build, whose workload names runs); when the
    record's target is the specification's own -- revision, image, configuration and
    commit; when any verified placement the record carries is the specification's
    subnet and its security groups as a set; and when the record's release mode is the
    one the specification authorized. A record with no verified placement (no
    release was written) is not held to a placement here; a caller that needs one checks
    for it. The launch tool refuses on anything but ``BOUND`` before completing a row or
    deciding a verdict, and the cell runner reads anything else as unbound evidence.
    """
    specification = reservation.specification
    if (
        reservation.specification_digest != record.specification_digest
        or reservation.identity != record.identity
        or reservation.actor is not record.actor
        or reservation.kind is not record.kind
        or specification.entry is not record.entry
    ):
        return RecordBinding.SPECIFICATION_MISMATCH
    try:
        compiled = specification.compiled
    except (KeyError, TypeError, ValueError):
        return RecordBinding.UNCOMPILABLE
    workload = specification.workload
    recorded_slice = None if record.slice is None else record.slice.canonical()
    if recorded_slice != workload.get("slice") or record.plan_digest != workload.get("plan_digest"):
        return RecordBinding.WORKLOAD_MISMATCH
    target = specification.target
    if (
        target.task_definition_arn != record.task_definition_arn
        or target.image_digest != record.image_digest
        or target.configuration_digest != record.configuration_digest
        or target.code_commit != record.code_commit
    ):
        return RecordBinding.TARGET_MISMATCH
    if record.subnet_id is not None and (
        compiled.subnet_id != record.subnet_id
        or frozenset(compiled.security_group_ids) != frozenset(record.security_group_ids or ())
    ):
        return RecordBinding.PLACEMENT_MISMATCH
    if record.release_mode is not specification.release_mode:
        return RecordBinding.MODE_MISMATCH
    return RecordBinding.BOUND


def parse_reservation(raw: object) -> Reservation:
    """A reservation document, or refuse."""
    try:
        document = decode_document(raw, max_bytes=MAX_RECORD_BYTES)
    except Exception:
        raise _refuse(StoreDefect.RESERVATION_MALFORMED) from None
    if type(document) is not dict or set(document) != _RESERVATION_FIELDS:
        raise _refuse(StoreDefect.RESERVATION_MALFORMED)
    if (
        document["schema_version"] != RECORD_SCHEMA_VERSION
        or document["contract_id"] != RESERVATION_CONTRACT_ID
    ):
        raise _refuse(StoreDefect.RESERVATION_MALFORMED)
    identity = exact_str(document["identity"])
    actor = exact_str(document["actor"])
    kind = exact_str(document["kind"])
    digest = exact_str(document["specification_digest"])
    reserved_at = instant(document["reserved_at"])
    if (
        identity is None
        or not RUN_ID_RE.match(identity)
        or actor not in {m.value for m in ProductionActor}
        or kind not in {m.value for m in LaunchKind}
        or digest is None
        or len(digest) != 64
        or set(digest) - _HEX_64
        or reserved_at is None
    ):
        raise _refuse(StoreDefect.RESERVATION_MALFORMED)
    try:
        specification = parse_specification(document["specification"])
    except LaunchRecordError:
        raise _refuse(StoreDefect.RESERVATION_MALFORMED) from None
    if (
        specification.digest != digest
        or specification.identity != identity
        or specification.actor.value != actor
        or specification.kind.value != kind
    ):
        raise _refuse(StoreDefect.RESERVATION_MALFORMED)
    return Reservation(
        identity=identity,
        actor=ProductionActor(actor),
        kind=LaunchKind(kind),
        specification=specification,
        reserved_at=reserved_at,
    )


def _create_exclusive(path: Path, payload: bytes) -> None:
    """Create ``path`` with its whole payload, or fail without touching an existing file."""
    descriptor = os.open(
        str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class LaunchStore:
    """One ledger with its reservations and lock beside it, and a records directory for evidence.

    ``ledger_path`` is canonicalized once (:meth:`Path.resolve`), so two spellings of one
    ledger -- relative and absolute, with or without ``..`` segments, in either case on a
    case-insensitive volume, through a symlink -- bind one reservations directory and one
    lock. ``records_dir`` only says where evidence and launch records are written.
    """

    __slots__ = ("_ledger_path", "_records_dir", "_reservations")

    def __init__(self, *, ledger_path: Path, records_dir: Path) -> None:
        """Bind the paths. Nothing is created until an operation needs it."""
        self._ledger_path = ledger_path.resolve(strict=False)
        self._records_dir = records_dir
        self._reservations = self._ledger_path.with_name(
            self._ledger_path.name + RESERVATIONS_SUFFIX
        )

    @property
    def ledger_path(self) -> Path:
        """The canonical ledger path every reservation and lock is anchored to."""
        return self._ledger_path

    @property
    def reservations_path(self) -> Path:
        """Where this ledger's reservations live, whatever records directory was named."""
        return self._reservations

    def refuse_legacy_state(self) -> None:
        """Refuse while the supplied records directory holds first-revision reservations.

        Nothing is read, moved or deleted: the owner relocates the files beside the
        ledger by hand, and the tool refuses until the legacy directory is empty or
        gone. Only the directory the owner named is looked at.
        """
        legacy = self._records_dir / LEGACY_RESERVATIONS_DIRECTORY
        try:
            if legacy.is_dir() and any(legacy.iterdir()):
                raise _refuse(StoreDefect.LEGACY_RESERVATIONS_PRESENT)
        except OSError:
            raise _refuse(StoreDefect.LEGACY_RESERVATIONS_PRESENT) from None

    # -- the lock ------------------------------------------------------------------------

    @property
    def lock_path(self) -> Path:
        """Where the exclusive ledger lock lives: beside the canonical ledger."""
        return self._ledger_path.with_name(self._ledger_path.name + LOCK_SUFFIX)

    @contextmanager
    def locked(self, *, now: Callable[[], datetime]) -> Iterator[None]:
        """Hold the ledger lock for one read-modify-write; refuse if another holds it."""
        marker = canonical_bytes({"pid": os.getpid(), "acquired_at": now().isoformat()})
        try:
            _create_exclusive(self.lock_path, marker)
        except FileExistsError:
            raise _refuse(StoreDefect.LEDGER_LOCKED) from None
        except OSError:
            raise _refuse(StoreDefect.WRITE_FAILED) from None
        try:
            yield
        finally:
            # Released even when the body raised; the reservation, not the lock, is the
            # durable guard. A lock that outlives its process is one the process never
            # reached this line for.
            try:
                os.unlink(self.lock_path)
            except OSError:
                pass

    # -- the ledger ------------------------------------------------------------------------

    def read_ledger(self) -> tuple[OwnerLedger, str]:
        """The ledger and the digest of the exact bytes it was read from."""
        try:
            raw = self._ledger_path.read_bytes()
        except OSError:
            raise _refuse(StoreDefect.LEDGER_UNREADABLE) from None
        try:
            ledger = parse_owner_ledger(raw)
        except Exception:
            raise _refuse(StoreDefect.LEDGER_UNREADABLE) from None
        return ledger, sha256_hex(raw)

    def replace_ledger(self, ledger: OwnerLedger, *, expected_digest: str) -> None:
        """Atomically replace the ledger, only if its bytes are still the ones read.

        Written to a fresh temporary file beside the ledger, flushed and synced, then
        renamed over it in one ``os.replace``; the old ledger survives every failure.
        """
        try:
            current = sha256_hex(self._ledger_path.read_bytes())
        except OSError:
            raise _refuse(StoreDefect.LEDGER_UNREADABLE) from None
        if current != expected_digest:
            raise _refuse(StoreDefect.LEDGER_CHANGED)
        payload = canonical_bytes(ledger.document())
        temporary = self._ledger_path.with_name(
            f".{self._ledger_path.name}.{secrets.token_hex(4)}.tmp"
        )
        try:
            _create_exclusive(temporary, payload)
            os.replace(temporary, self._ledger_path)
        except OSError:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise _refuse(StoreDefect.WRITE_FAILED) from None

    # -- reservations ----------------------------------------------------------------------

    def reservation_path(self, identity: str) -> Path:
        """Where ``identity``'s reservation lives: beside the ledger, never under the records."""
        return self._reservations / f"{identity}.json"

    def reserve(self, reservation: Reservation) -> None:
        """Consume the identity durably, or refuse if it is already reserved.

        Exclusive creation: a second attempt on the same identity -- concurrent, later,
        after an interruption, after an ambiguous outcome -- finds the file and refuses.
        """
        try:
            self._reservations.mkdir(parents=True, exist_ok=True)
            _create_exclusive(
                self.reservation_path(reservation.identity),
                canonical_bytes(reservation.document()),
            )
        except FileExistsError:
            raise _refuse(StoreDefect.RESERVATION_EXISTS) from None
        except OSError:
            raise _refuse(StoreDefect.WRITE_FAILED) from None

    def reservation(self, identity: str) -> Reservation | None:
        """The reservation for ``identity``, ``None`` if there is none; malformed refuses."""
        path = self.reservation_path(identity)
        if not path.exists():
            return None
        try:
            raw = path.read_bytes()
        except OSError:
            raise _refuse(StoreDefect.RESERVATION_MALFORMED) from None
        return parse_reservation(raw)

    # -- consumed authorizations -----------------------------------------------------------

    def consumed_path(self, kind: str, digest: str) -> Path:
        """Where the consumption of ``digest`` lives: beside the ledger, never under the records."""
        if not (len(digest) == 64 and set(digest) <= _HEX_64) or not kind.isidentifier():
            raise _refuse(StoreDefect.WRITE_FAILED)
        return self._ledger_path.with_name(self._ledger_path.name + CONSUMED_SUFFIX) / (
            f"{kind}-{digest}.json"
        )

    def consume(self, kind: str, digest: str, document: dict[str, Any]) -> None:
        """Consume one authorization durably, or refuse if it was consumed before.

        Exclusive creation beside the canonical ledger: a second execution under the same
        authorization -- repeated, after an interruption, after an ambiguous outcome, from
        another records directory -- finds the file and refuses. Nothing here ever
        removes a consumption.
        """
        path = self.consumed_path(kind, digest)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _create_exclusive(path, canonical_bytes(document))
        except FileExistsError:
            raise _refuse(StoreDefect.AUTHORIZATION_CONSUMED) from None
        except OSError:
            raise _refuse(StoreDefect.WRITE_FAILED) from None

    def is_consumed(self, kind: str, digest: str) -> bool:
        """Whether ``digest`` was consumed before."""
        return self.consumed_path(kind, digest).exists()

    def consumptions(self, kind: str) -> dict[str, bytes]:
        """Every consumption of ``kind`` beside the ledger: the digest and the bytes.

        Read only; a file whose name is not a digest of this kind is ignored, a file that
        cannot be read is reported by its digest with empty bytes (malformed, never
        silently absent).
        """
        directory = self._ledger_path.with_name(self._ledger_path.name + CONSUMED_SUFFIX)
        if not directory.is_dir() or not kind.isidentifier():
            return {}
        found: dict[str, bytes] = {}
        for path in sorted(directory.glob(f"{kind}-*.json")):
            digest = path.name[len(kind) + 1 : -len(".json")]
            if len(digest) != 64 or not set(digest) <= _HEX_64:
                continue
            try:
                found[digest] = path.read_bytes()
            except OSError:
                found[digest] = b""
        return found

    def unreconciled(self, ledger: OwnerLedger) -> list[str]:
        """Identities reserved but absent from the ledger: interrupted work, sorted."""
        if not self._reservations.is_dir():
            return []
        found: list[str] = []
        for path in sorted(self._reservations.glob("*.json")):
            reservation = parse_reservation(path.read_bytes())
            if reservation.identity != path.stem:
                raise _refuse(StoreDefect.RESERVATION_MALFORMED)
            if ledger.row(reservation.identity) is None:
                found.append(reservation.identity)
        return found

    # -- records -----------------------------------------------------------------------------

    def write_record(self, prefix: str, document: dict[str, Any], *, at: datetime) -> Path:
        """Create one record under a name that cannot collide; never overwrite."""
        self._records_dir.mkdir(parents=True, exist_ok=True)
        stamp = at.strftime("%Y%m%dT%H%M%SZ")
        payload = canonical_bytes(document)
        for _ in range(MAX_NAME_ATTEMPTS):
            path = self._records_dir / f"{prefix}-{stamp}-{secrets.token_hex(4)}.json"
            try:
                _create_exclusive(path, payload)
            except FileExistsError:
                continue
            except OSError:
                raise _refuse(StoreDefect.WRITE_FAILED) from None
            return path
        raise _refuse(StoreDefect.NAME_EXHAUSTED)

    def launch_records(self) -> list[Path]:
        """Every launch record in the directory, oldest name first."""
        if not self._records_dir.is_dir():
            return []
        return sorted(self._records_dir.glob("launch-record-*.json"))


__all__ = [
    "CONSUMED_SUFFIX",
    "LEGACY_RESERVATIONS_DIRECTORY",
    "LOCK_SUFFIX",
    "MAX_NAME_ATTEMPTS",
    "RESERVATIONS_SUFFIX",
    "RESERVATION_CONTRACT_ID",
    "LaunchStore",
    "RecordBinding",
    "Reservation",
    "StoreDefect",
    "StoreError",
    "bind_record",
    "parse_reservation",
]
