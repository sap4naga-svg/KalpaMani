"""Immutable, content-addressed Bronze storage.

Bronze holds a payload **byte for byte, exactly as received**, named by the
SHA-256 of its contents, alongside the acquisition records describing how it
arrived. It is append-only. A re-fetch returning different bytes is a *new*
artifact, never a replacement -- which is what makes a vendor backfill visible
instead of silent, and what lets the profile model decide what to do about it.

**Two physical namespaces, deliberately.**

```
bronze/objects/sha256/<digest>.json.gz
bronze/acquisitions/<provider>/<dataset>/<date>/<digest>.<run-id>.json
```

The content object is keyed by **digest alone**, globally. The same bytes fetched
on two different dates, or under two different runs, are one object -- because
identity is a property of what the vendor sent, not of when we asked or how often.
Filing content under the acquisition date would store the same payload twice and
make a re-fetch look like new data.

An acquisition record is written per retrieval. Fetching the same bytes again
records a second acquisition without touching the content object, which is the
honest account: we did fetch it twice, and there is still only one payload. A
second legitimate acquisition is **not** a repair.

**Crash safety, and what "repaired" is allowed to mean.** An acquisition has a
durable state. A ``PENDING`` record is written first, then the content object,
then the record is replaced with ``COMPLETE``. Every step is atomic and fsyncs
its containing directory.

That order makes an interrupted acquisition *visible* rather than merely
inferable. A crash leaves a ``PENDING`` record on disk, which the audit reports
and :meth:`BronzeStore.require_complete` refuses; re-running **that same
acquisition identity** finishes it and reports ``repaired=True``.

The earlier version inferred repair from circumstance -- payload present,
acquisition record absent -- and that inference was wrong in the ordinary case:
a *new* ingestion run fetching bytes the store already held matched it exactly,
so every second acquisition of unchanged data was logged as a recovery event.
Repair now requires a pending record to complete, which is a fact rather than a
guess.

**An acquisition identity is globally unique.** ``(digest, ingestion_run_id)``
names one retrieval, not one retrieval per partition. Recording the same identity
under a second provider, dataset or date is refused: a run fetched a payload
once, and two partitions claiming it would each be evidence for a different
story.

**An acquisition identity means one thing.** Re-writing the same
``(digest, ingestion_run_id)`` with identical metadata is idempotent. Re-writing
it with *different* metadata is refused: one retrieval happened once, and letting
a later call restate it would make the record describe an event that did not
occur.

**External identifiers are never unchecked path components.** Provider, dataset
and run id all pass through :func:`safe_component` first. A vendor name does not
get to choose where we write.

**No network client exists here, and none is authorized in this slice.** This
module receives bytes a caller already holds -- which is the reason it can be
written and tested before gate G1 selects a provider at all.
"""

from __future__ import annotations

import gzip
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.entities import IngestionRun
from kalpamani.data.contracts.errors import AcquisitionIncompleteError, BronzeIntegrityError
from kalpamani.data.contracts.instants import normalize_instant
from kalpamani.data.contracts.paths import safe_component
from kalpamani.data.contracts.vocabulary import AcquisitionMode, IngestionStatus

#: Fixed gzip modification time. Without it the compressed bytes embed a clock,
#: and two identical payloads produce two different files.
_DETERMINISTIC_MTIME = 0

#: Fixed compression level, so the stored bytes do not depend on a zlib default.
_COMPRESSION_LEVEL = 9

#: An acquisition record was written but its content object had not landed yet.
#: Durable, so an interrupted acquisition is a state on disk rather than an
#: inference from what happens to be missing.
ACQUISITION_PENDING = "PENDING"

#: The content object landed and this retrieval is fully recorded.
ACQUISITION_COMPLETE = "COMPLETE"


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalMetadata:
    """How a payload was acquired. Recorded beside the payload, never inside it.

    **The single source of the acquisition mode.** Every durable record and every
    run record reads ``acquisition_mode`` from here rather than taking its own
    copy, so there is no second field for a caller to set differently and no
    reconciliation to get wrong. ADR-0013 removed the second copies that existed
    when the field was a boolean.

    ``acquisition_mode`` has **no default**. A retrieval whose intent nobody
    stated is a retrieval nobody governed, and defaulting it would let the most
    consequential field on the record be filled in by omission.
    """

    provider: str
    dataset: str
    requested_range: str
    retrieved_at: datetime
    source_schema_version: str
    ingestion_run_id: str
    acquisition_mode: AcquisitionMode
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "retrieved_at", normalize_instant(self.retrieved_at))
        # An exact member, not a value that normalises to one. A bare
        # ``"BACKFILL"`` reaching a durable record would be a second spelling of
        # one mode, and ``closed_member`` would happily produce it.
        if type(self.acquisition_mode) is not AcquisitionMode:
            raise AcquisitionIncompleteError(
                "acquisition_mode must be an exact AcquisitionMode member. It states the "
                "governed intent of the retrieval, and a value that merely compares equal "
                "to one is not a statement anybody made."
            )
        if not self.ingestion_run_id:
            raise AcquisitionIncompleteError(
                "An acquisition needs an ingestion_run_id. It is the identity of the act that "
                "fetched the bytes, and without it a second retrieval of the same payload "
                "cannot be distinguished from the first."
            )
        safe_component(self.provider, kind="provider")
        safe_component(self.dataset, kind="dataset")
        safe_component(self.ingestion_run_id, kind="ingestion_run_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class BronzeArtifact:
    """One immutable Bronze object and the acquisition that produced this call.

    ``content_written`` is ``False`` when the identical payload was already
    stored. ``acquisition_written`` is ``True`` when this retrieval's record was
    created or completed by this call. ``repaired`` is ``True`` only when this
    call **completed a PENDING record left by an interrupted run of this same
    acquisition identity**.

    A new ingestion run fetching bytes the store already holds is
    ``content_written=False, acquisition_written=True, repaired=False``. It is an
    ordinary second acquisition -- we did fetch it twice, and there is still only
    one payload -- and logging it as a recovery event would put a crash in the
    audit trail that never happened.
    """

    content_sha256: str
    path: Path
    acquisition_path: Path
    byte_count: int
    content_written: bool
    acquisition_written: bool
    repaired: bool = False


class BronzeStore:
    """Append-only content-addressed object store rooted at an explicit path."""

    def __init__(self, root: Path) -> None:
        """Bind the store to ``root``. Nothing is created until a write happens."""
        self._root = Path(root)

    @property
    def root(self) -> Path:
        """The root this store writes under."""
        return self._root

    def object_path(self, digest: str) -> Path:
        """Where the content object with ``digest`` lives. Global, by digest alone."""
        safe_component(digest, kind="content digest")
        return self._root / "bronze" / "objects" / "sha256" / f"{digest}.json.gz"

    def acquisition_path(
        self,
        *,
        provider: str,
        dataset: str,
        ingest_date: date,
        digest: str,
        ingestion_run_id: str,
    ) -> Path:
        """Where one retrieval's acquisition record lives."""
        return self._acquisition_partition(provider, dataset, ingest_date) / (
            f"{safe_component(digest, kind='content digest')}."
            f"{safe_component(ingestion_run_id, kind='ingestion_run_id')}.json"
        )

    def _acquisition_partition(self, provider: str, dataset: str, ingest_date: date) -> Path:
        return (
            self._root
            / "bronze"
            / "acquisitions"
            / safe_component(provider, kind="provider")
            / safe_component(dataset, kind="dataset")
            / ingest_date.isoformat()
        )

    def write(
        self,
        *,
        payload: bytes,
        retrieval: RetrievalMetadata,
        ingest_date: date,
    ) -> BronzeArtifact:
        """Store ``payload`` immutably and record this acquisition.

        PENDING record, then content, then COMPLETE record. Each write is atomic
        and fsyncs its directory, so an interrupted run leaves a pending record
        that names exactly what to finish.

        Raises:
            BronzeIntegrityError: if an object already exists at this identity
                whose stored bytes differ -- two different payloads cannot share
                one identity, and overwriting would destroy the earlier
                acquisition.
            AcquisitionIncompleteError: if this acquisition identity already
                exists with contradictory metadata, or exists in another
                partition. One retrieval happened once, in one place.
        """
        digest = sha256_hex(payload)
        destination = self.object_path(digest)
        acquisition = self.acquisition_path(
            provider=retrieval.provider,
            dataset=retrieval.dataset,
            ingest_date=ingest_date,
            digest=digest,
            ingestion_run_id=retrieval.ingestion_run_id,
        )
        self._require_identity_unclaimed(acquisition, digest, retrieval.ingestion_run_id)

        pending = _acquisition_body(
            retrieval, digest, len(payload), ingest_date, status=ACQUISITION_PENDING
        )
        complete = _acquisition_body(
            retrieval, digest, len(payload), ingest_date, status=ACQUISITION_COMPLETE
        )

        existing = _read_record(acquisition)
        was_pending = existing is not None and existing.get("status") == ACQUISITION_PENDING
        if existing is None:
            _atomic_write(acquisition, canonical_bytes(pending))
        else:
            _require_same_retrieval(existing, complete, retrieval, digest)

        # The content object is checked on every call, including the idempotent
        # one. Returning early on a COMPLETE record would let a corrupted or
        # replaced payload pass unexamined for the rest of the store's life.
        content_written = False
        if destination.exists():
            stored = self.read(destination)
            if stored != payload:
                raise BronzeIntegrityError(
                    f"Bronze object {digest} already holds different bytes at {destination}. "
                    "Bronze is content-addressed and append-only: identical identity with "
                    "different content means either a hash collision or a corrupted store, "
                    "and neither is resolved by overwriting."
                )
            if sha256_hex(stored) != digest:  # pragma: no cover - defence in depth
                raise BronzeIntegrityError(
                    f"Bronze object at {destination} does not hash to the {digest} its name claims."
                )
        else:
            _atomic_write(
                destination,
                gzip.compress(payload, _COMPRESSION_LEVEL, mtime=_DETERMINISTIC_MTIME),
            )
            content_written = True

        if existing is not None and existing.get("status") == ACQUISITION_COMPLETE:
            # This exact retrieval is already fully recorded. Idempotent.
            return BronzeArtifact(
                content_sha256=digest,
                path=destination,
                acquisition_path=acquisition,
                byte_count=len(payload),
                content_written=content_written,
                acquisition_written=False,
                repaired=False,
            )

        _atomic_write(acquisition, canonical_bytes(complete))

        return BronzeArtifact(
            content_sha256=digest,
            path=destination,
            acquisition_path=acquisition,
            byte_count=len(payload),
            content_written=content_written,
            acquisition_written=True,
            repaired=was_pending,
        )

    def _require_identity_unclaimed(
        self, acquisition: Path, digest: str, ingestion_run_id: str
    ) -> None:
        """Refuse an acquisition identity already filed somewhere else.

        Raises:
            AcquisitionIncompleteError: if ``(digest, ingestion_run_id)`` exists
                under a different partition.
        """
        root = self._root / "bronze" / "acquisitions"
        if not root.is_dir():
            return
        name = f"{digest}.{ingestion_run_id}.json"
        elsewhere = sorted(
            path for path in root.rglob(name) if path.resolve() != acquisition.resolve()
        )
        if elsewhere:
            raise AcquisitionIncompleteError(
                f"Acquisition {ingestion_run_id!r} of {digest} is already recorded at "
                f"{[str(path) for path in elsewhere]}. An acquisition identity names one "
                "retrieval globally, not one per partition: two partitions claiming it would "
                "each be evidence for a different story about when the bytes arrived."
            )

    def read(self, path: Path) -> bytes:
        """Return the exact uncompressed payload bytes stored at ``path``."""
        return gzip.decompress(path.read_bytes())

    def verify(self, artifact: BronzeArtifact) -> bool:
        """Whether the stored object still hashes to the identity it claims."""
        if not artifact.path.exists():
            return False
        return sha256_hex(self.read(artifact.path)) == artifact.content_sha256

    def acquisitions_for(
        self,
        *,
        provider: str,
        dataset: str,
        ingest_date: date,
        digest: str,
    ) -> tuple[Mapping[str, Any], ...]:
        """Every recorded acquisition of one content object, in canonical order."""
        partition = self._acquisition_partition(provider, dataset, ingest_date)
        if not partition.is_dir():
            return ()
        records: list[Mapping[str, Any]] = []
        for path in sorted(partition.glob(f"{digest}.*.json")):
            decoded: Any = json.loads(path.read_text(encoding="utf-8"))
            records.append(decoded)
        return tuple(records)

    def audit_acquisitions(
        self, *, provider: str, dataset: str, ingest_date: date
    ) -> tuple[str, ...]:
        """Acquisition records that do not check out, as human-readable reasons.

        Verifies JSON validity, acquisition status, digest linkage, byte count,
        the provider, dataset, date and run identity the record claims, and that
        the content object it names exists and hashes correctly. A record nothing
        can corroborate is not provenance, and a record still PENDING is a
        retrieval that never finished.
        """
        partition = self._acquisition_partition(provider, dataset, ingest_date)
        if not partition.is_dir():
            return ()
        problems: list[str] = []
        for path in sorted(partition.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                problems.append(f"{path.name}: not valid JSON ({exc.msg})")
                continue
            if not isinstance(record, Mapping):
                problems.append(f"{path.name}: not a JSON object")
                continue
            digest = str(record.get("content_sha256", ""))
            expected_name = f"{digest}.{record.get('ingestion_run_id', '')}.json"
            if path.name != expected_name:
                problems.append(f"{path.name}: filename disagrees with its own identity")
            for field_name, expected in (
                ("provider", provider),
                ("dataset", dataset),
                ("ingest_date", ingest_date.isoformat()),
            ):
                if str(record.get(field_name, "")) != expected:
                    problems.append(
                        f"{path.name}: {field_name} is {record.get(field_name)!r}, not "
                        f"{expected!r} -- the record is filed under a partition it does not "
                        "claim"
                    )
            status = str(record.get("status", ""))
            if status not in (ACQUISITION_PENDING, ACQUISITION_COMPLETE):
                problems.append(
                    f"{path.name}: declares status {status!r}, which is neither "
                    f"{ACQUISITION_PENDING} nor {ACQUISITION_COMPLETE}"
                )
            elif status == ACQUISITION_PENDING:
                problems.append(
                    f"{path.name}: is still {ACQUISITION_PENDING}. An interrupted acquisition "
                    "is finished by re-running that same identity, not by ignoring it."
                )
            content = self.object_path(digest) if digest else None
            if content is None or not content.exists():
                problems.append(f"{path.name}: names content {digest!r}, which does not exist")
                continue
            payload = self.read(content)
            if sha256_hex(payload) != digest:
                problems.append(f"{path.name}: content does not hash to {digest!r}")
            if int(record.get("byte_count", -1)) != len(payload):
                problems.append(
                    f"{path.name}: declares {record.get('byte_count')} bytes, content holds "
                    f"{len(payload)}"
                )
        return tuple(problems)

    def orphaned_content(self) -> tuple[str, ...]:
        """Content digests with no acquisition record anywhere.

        The recovery entry point: a caller repairs each by re-running its
        acquisition, or refuses explicitly. Never by ignoring it.
        """
        objects = self._root / "bronze" / "objects" / "sha256"
        acquisitions = self._root / "bronze" / "acquisitions"
        if not objects.is_dir():
            return ()
        claimed: set[str] = set()
        if acquisitions.is_dir():
            for path in acquisitions.rglob("*.json"):
                claimed.add(path.name.split(".", 1)[0])
        return tuple(
            sorted(
                path.name.removesuffix(".json.gz")
                for path in objects.glob("*.json.gz")
                if path.name.removesuffix(".json.gz") not in claimed
            )
        )

    def require_complete(self, *, provider: str, dataset: str, ingest_date: date) -> None:
        """Refuse a store holding a payload nothing can explain, or a bad record.

        Raises:
            AcquisitionIncompleteError: naming every orphaned digest and every
                acquisition record that fails verification.
        """
        orphaned = self.orphaned_content()
        problems = self.audit_acquisitions(
            provider=provider, dataset=dataset, ingest_date=ingest_date
        )
        if not orphaned and not problems:
            return
        detail: list[str] = []
        if orphaned:
            detail.append(
                f"{len(orphaned)} payload(s) with no acquisition record: {list(orphaned)}"
            )
        detail.extend(problems)
        raise AcquisitionIncompleteError(
            "Bronze is not complete:\n  - "
            + "\n  - ".join(detail)
            + "\nRepair by re-running the acquisition, or refuse the partition. A payload "
            "nothing can explain is worse than no payload, because it looks like evidence."
        )


def _read_record(path: Path) -> dict[str, Any] | None:
    """The acquisition record at ``path``, or ``None`` if there is none.

    Raises:
        AcquisitionIncompleteError: if the file exists but is not a JSON object.
            A record nothing can parse is not evidence of a retrieval.
    """
    if not path.exists():
        return None
    try:
        decoded: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AcquisitionIncompleteError(
            f"The acquisition record at {path} is not valid JSON ({exc.msg}). A record nothing "
            "can read cannot be completed or contradicted, so it is repaired by hand or the "
            "partition is refused."
        ) from exc
    if not isinstance(decoded, dict):
        raise AcquisitionIncompleteError(f"The acquisition record at {path} is not a JSON object.")
    return decoded


def _require_same_retrieval(
    existing: Mapping[str, Any],
    complete: Mapping[str, object],
    retrieval: RetrievalMetadata,
    digest: str,
) -> None:
    """Refuse a second call that restates an acquisition differently.

    Status is excluded from the comparison, because advancing PENDING to COMPLETE
    is exactly what a repair does. Everything else about the retrieval must be
    identical.

    Raises:
        AcquisitionIncompleteError: naming the fields that disagree.
    """
    differing = sorted(
        key for key in complete if key != "status" and existing.get(key) != complete[key]
    )
    if differing:
        raise AcquisitionIncompleteError(
            f"Acquisition {retrieval.ingestion_run_id!r} of {digest} already exists with "
            f"different metadata ({differing}). One retrieval happened once; restating it "
            "later would make the record describe an event that did not occur. Use a new "
            "ingestion_run_id for a new retrieval."
        )


def _acquisition_body(
    retrieval: RetrievalMetadata,
    digest: str,
    byte_count: int,
    ingest_date: date,
    *,
    status: str,
) -> dict[str, object]:
    """The durable body of one filesystem acquisition record.

    ``acquisition_mode`` is written on **both** the PENDING and the COMPLETE
    body, from ``retrieval`` and nowhere else. The first revision of ADR-0013
    updated the object-store record and left this one behind, so the local store
    recorded no mode at all -- and, because :func:`_require_same_retrieval`
    compares every field except ``status``, a second call under the same identity
    with a *different* mode was accepted rather than refused.

    The value is the member's plain ``str`` token, never the ``StrEnum`` member: a
    record is bytes on a disk, and a ``StrEnum`` is a ``str`` *subclass* whose
    identity is not what a later reader gets back.
    """
    return {
        "status": status,
        "content_sha256": digest,
        "byte_count": byte_count,
        "provider": retrieval.provider,
        "dataset": retrieval.dataset,
        "ingest_date": ingest_date.isoformat(),
        "requested_range": retrieval.requested_range,
        "retrieved_at": retrieval.retrieved_at.isoformat(),
        "source_schema_version": retrieval.source_schema_version,
        "ingestion_run_id": retrieval.ingestion_run_id,
        "acquisition_mode": str(retrieval.acquisition_mode.value),
        "notes": retrieval.notes,
    }


def _atomic_write(destination: Path, payload: bytes) -> None:
    """Write ``payload`` atomically, then flush the directory entry.

    Same directory, so the rename cannot cross a filesystem boundary and degrade
    to a copy. ``os.replace`` is atomic on both POSIX and Windows, and the
    directory fsync is what makes the rename itself survive a crash.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = NamedTemporaryFile(
        dir=destination.parent,
        prefix=".tmp-",
        suffix=".part",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    _fsync_directory(destination.parent)


def _fsync_directory(path: Path) -> None:
    """Flush a directory entry so a rename survives a crash.

    Not every platform permits opening a directory; where it does not, the rename
    is still atomic and the flush is simply unavailable. Refusing to run there
    would buy nothing.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def build_ingestion_run(
    *,
    retrieval: RetrievalMetadata,
    started_at: datetime,
    completed_at: datetime,
    artifacts: tuple[BronzeArtifact, ...],
    record_count: int,
    new_record_count: int,
    code_commit_sha: str,
    config_version: str,
    status: IngestionStatus = IngestionStatus.SUCCESS,
) -> IngestionRun:
    """Build the immutable record of one acquisition run.

    The run id comes from ``retrieval``, and is expected to be deterministic in
    the ADR-0004 s.2 spirit: no ``uuid4()``, no timestamps in an identity. A
    derived id means two runs claiming to be the same run can be checked against
    each other rather than merely asserted to match.

    **The acquisition mode comes from ``retrieval`` too, and there is no
    parameter for it.** Accepting a second mode here would create two places to
    state one fact, and the interesting case is the one where they disagree --
    which no validation can resolve, because neither copy is more authoritative
    than the other.
    """
    return IngestionRun(
        ingestion_run_id=retrieval.ingestion_run_id,
        provider=retrieval.provider,
        dataset=retrieval.dataset,
        started_at=started_at,
        completed_at=completed_at,
        status=status,
        requested_range=retrieval.requested_range,
        record_count=record_count,
        new_record_count=new_record_count,
        acquisition_mode=retrieval.acquisition_mode,
        bronze_artifact_hashes=tuple(sorted(a.content_sha256 for a in artifacts)),
        code_commit_sha=code_commit_sha,
        config_version=config_version,
    )


__all__ = [
    "ACQUISITION_COMPLETE",
    "ACQUISITION_PENDING",
    "BronzeArtifact",
    "BronzeStore",
    "RetrievalMetadata",
    "build_ingestion_run",
]
