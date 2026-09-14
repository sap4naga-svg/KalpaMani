"""The launch tool's durable state on the owner's workstation: reservations, lock, atomic ledger.

**Proposed ADR-0045 §6 — offline, exercised only against a temporary directory.** The
owner ledger is the record of every identity ever consumed; this module is how the tool
makes that record **durable before any external mutation** and **consistent across
concurrent or interrupted attempts**, on the filesystem the owner actually uses (NTFS on
Windows; the same primitives hold on POSIX).

Three primitives, each the narrowest the platform offers:

- **an exclusive reservation** -- ``reservations/<identity>.json`` created with
  ``O_CREAT | O_EXCL``, which the platform makes atomic: two attempts on one identity
  cannot both create it, whatever their timing. The file names the launch specification
  digest the identity was reserved for, and it is **never deleted and never expires**:
  a reservation left by an interrupted attempt is exactly the case it exists for, and
  the only way past it is :func:`recover`, which writes the ledger row and launches
  nothing;
- **an exclusive lock** on the ledger -- ``ledger.lock`` created the same way, held
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
    OwnerLedger,
    parse_owner_ledger,
)
from kalpamani.data.production.sharadar.vocabulary import ProductionActor

RESERVATION_CONTRACT_ID: Final = "kalpamani-launch-reservation/v1"
RESERVATIONS_DIRECTORY: Final = "reservations"
LOCK_NAME: Final = "ledger.lock"
#: How many fresh random names are tried before a record write is refused.
MAX_NAME_ATTEMPTS: Final = 8

_HEX_64: Final = frozenset("0123456789abcdef")
_RESERVATION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "contract_id",
        "identity",
        "actor",
        "kind",
        "specification_digest",
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
    """One consumed identity: which launch specification it was reserved for, and when."""

    identity: str
    actor: ProductionActor
    kind: LaunchKind
    specification_digest: str
    reserved_at: datetime

    def document(self) -> dict[str, Any]:
        """The reservation document."""
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "contract_id": RESERVATION_CONTRACT_ID,
            "identity": self.identity,
            "actor": self.actor.value,
            "kind": self.kind.value,
            "specification_digest": self.specification_digest,
            "reserved_at": self.reserved_at.isoformat(),
        }

    def __repr__(self) -> str:
        """Kind only."""
        return f"Reservation(kind={self.kind.value!r})"


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
    return Reservation(
        identity=identity,
        actor=ProductionActor(actor),
        kind=LaunchKind(kind),
        specification_digest=digest,
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
    """The ledger, the reservations and the records under one records directory."""

    __slots__ = ("_ledger_path", "_records_dir", "_reservations")

    def __init__(self, *, ledger_path: Path, records_dir: Path) -> None:
        """Bind the paths. Nothing is created until an operation needs it."""
        self._ledger_path = ledger_path
        self._records_dir = records_dir
        self._reservations = records_dir / RESERVATIONS_DIRECTORY

    # -- the lock ------------------------------------------------------------------------

    @property
    def lock_path(self) -> Path:
        """Where the exclusive ledger lock lives."""
        return self._ledger_path.with_name(self._ledger_path.name + ".lock")

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
        """Where ``identity``'s reservation lives."""
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
    "LOCK_NAME",
    "MAX_NAME_ATTEMPTS",
    "RESERVATIONS_DIRECTORY",
    "RESERVATION_CONTRACT_ID",
    "LaunchStore",
    "Reservation",
    "StoreDefect",
    "StoreError",
    "parse_reservation",
]
