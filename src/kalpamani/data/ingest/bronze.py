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

**Crash safety.** Content is written first, acquisition second, each atomically,
and both fsync their containing directory. That order makes the only reachable
inconsistency a payload with a missing acquisition record, which is *repairable*:
a retry of that same acquisition identity completes it and reports
``repaired=True``. The reverse order would leave an acquisition naming a payload
that does not exist, which nothing on disk could repair.

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
from kalpamani.data.contracts.vocabulary import IngestionStatus

#: Fixed gzip modification time. Without it the compressed bytes embed a clock,
#: and two identical payloads produce two different files.
_DETERMINISTIC_MTIME = 0

#: Fixed compression level, so the stored bytes do not depend on a zlib default.
_COMPRESSION_LEVEL = 9


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalMetadata:
    """How a payload was acquired. Recorded beside the payload, never inside it."""

    provider: str
    dataset: str
    requested_range: str
    retrieved_at: datetime
    source_schema_version: str
    ingestion_run_id: str
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "retrieved_at", normalize_instant(self.retrieved_at))
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
    created. ``repaired`` is ``True`` only when this call **completed an
    interrupted acquisition** -- the payload was present and this same acquisition
    identity had no record. A second, legitimately different acquisition of the
    same bytes is not a repair, and reporting it as one would turn an ordinary
    re-fetch into a recovery event in the audit trail.
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

        Content first, acquisition second, each atomic and each fsync-ed. A crash
        between them leaves a repairable state; the reverse order would not.

        Raises:
            BronzeIntegrityError: if an object already exists at this identity
                whose stored bytes differ -- two different payloads cannot share
                one identity, and overwriting would destroy the earlier
                acquisition.
            AcquisitionIncompleteError: if this acquisition identity already
                exists with contradictory metadata. One retrieval happened once.
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
        body = _acquisition_body(retrieval, digest, len(payload), ingest_date)

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

        # A repair completes THIS acquisition identity after its payload landed.
        # A different run id fetching the same bytes is an ordinary second
        # acquisition, and calling that a repair would turn a re-fetch into a
        # recovery event in the audit trail.
        repaired = not content_written and not acquisition.exists() and destination.exists()

        acquisition_written = False
        if acquisition.exists():
            existing = json.loads(acquisition.read_text(encoding="utf-8"))
            if existing != json.loads(canonical_bytes(body).decode("utf-8")):
                raise AcquisitionIncompleteError(
                    f"Acquisition {retrieval.ingestion_run_id!r} of {digest} already exists "
                    "with different metadata. One retrieval happened once; restating it "
                    "later would make the record describe an event that did not occur. Use a "
                    "new ingestion_run_id for a new retrieval."
                )
        else:
            _atomic_write(acquisition, canonical_bytes(body))
            acquisition_written = True

        return BronzeArtifact(
            content_sha256=digest,
            path=destination,
            acquisition_path=acquisition,
            byte_count=len(payload),
            content_written=content_written,
            acquisition_written=acquisition_written,
            repaired=repaired,
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

        Verifies JSON validity, digest linkage, byte count, the provider, dataset,
        date and run identity the record claims, and that the content object it
        names exists and hashes correctly. A record nothing can corroborate is not
        provenance.
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


def _acquisition_body(
    retrieval: RetrievalMetadata, digest: str, byte_count: int, ingest_date: date
) -> dict[str, object]:
    return {
        "content_sha256": digest,
        "byte_count": byte_count,
        "provider": retrieval.provider,
        "dataset": retrieval.dataset,
        "ingest_date": ingest_date.isoformat(),
        "requested_range": retrieval.requested_range,
        "retrieved_at": retrieval.retrieved_at.isoformat(),
        "source_schema_version": retrieval.source_schema_version,
        "ingestion_run_id": retrieval.ingestion_run_id,
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
    is_backfill: bool,
    code_commit_sha: str,
    config_version: str,
    status: IngestionStatus = IngestionStatus.SUCCESS,
) -> IngestionRun:
    """Build the immutable record of one acquisition run.

    The run id comes from ``retrieval``, and is expected to be deterministic in
    the ADR-0004 s.2 spirit: no ``uuid4()``, no timestamps in an identity. A
    derived id means two runs claiming to be the same run can be checked against
    each other rather than merely asserted to match.
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
        is_backfill=is_backfill,
        bronze_artifact_hashes=tuple(sorted(a.content_sha256 for a in artifacts)),
        code_commit_sha=code_commit_sha,
        config_version=config_version,
    )


__all__ = [
    "BronzeArtifact",
    "BronzeStore",
    "RetrievalMetadata",
    "build_ingestion_run",
]
