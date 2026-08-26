"""Immutable, content-addressed Bronze storage.

Bronze holds a payload **byte for byte, exactly as received**, named by the
SHA-256 of its contents, alongside the acquisition metadata that describes how it
arrived. It is append-only. A re-fetch returning different bytes is a *new*
artifact, never a replacement -- which is what makes a vendor backfill visible
instead of silent, and what lets the profile model decide what to do about it.

**The hashing contract, stated once.** The identity of an object is the SHA-256
of the **uncompressed payload bytes**. Gzip is a storage encoding, not part of
identity: the same payload stored compressed and uncompressed is the same
artifact. Compression is therefore performed with a fixed zero ``mtime``, so the
stored file is itself byte-identical across writes and a file-level comparison
cannot mistake a re-run for a change.

**Metadata lives outside the payload.** Provider, dataset, requested range and
retrieval details go in a sidecar. Mixing them into the payload would change the
bytes and therefore the identity, and the identity is supposed to be a property
of what the vendor sent, not of when we asked.

**No network client exists here, and none is authorized in this slice.** This
module receives bytes a caller already holds. It has no HTTP dependency, no
credential handling and no provider knowledge -- which is the reason it can be
written and tested before gate G1 selects a provider at all.

The root path is always an explicit argument. Importing this module creates no
directory and touches no disk.
"""

from __future__ import annotations

import gzip
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.entities import IngestionRun
from kalpamani.data.contracts.errors import BronzeIntegrityError
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
    notes: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class BronzeArtifact:
    """One immutable Bronze object.

    ``was_written`` is ``False`` when the identical payload was already stored.
    Writing the same bytes twice is idempotent, and reporting it as a write would
    make a re-run look like a new acquisition.
    """

    content_sha256: str
    path: Path
    metadata_path: Path
    byte_count: int
    was_written: bool


class BronzeStore:
    """Append-only content-addressed object store rooted at an explicit path."""

    def __init__(self, root: Path) -> None:
        """Bind the store to ``root``. Nothing is created until a write happens."""
        self._root = Path(root)

    @property
    def root(self) -> Path:
        """The root this store writes under."""
        return self._root

    def object_path(self, *, provider: str, dataset: str, ingest_date: date, digest: str) -> Path:
        """Where an object with ``digest`` lives.

        The layout keeps the acquisition date in the path so a directory listing
        is chronologically meaningful, while identity remains the digest alone.
        """
        return (
            self._root
            / "bronze"
            / provider
            / dataset
            / ingest_date.isoformat()
            / f"{digest}.json.gz"
        )

    def write(
        self,
        *,
        payload: bytes,
        retrieval: RetrievalMetadata,
        ingest_date: date,
    ) -> BronzeArtifact:
        """Store ``payload`` immutably, returning its artifact identity.

        Atomic: the bytes are written to a temporary file in the destination
        directory, flushed, ``fsync``-ed and then renamed into place. A partially
        written object is never visible under a real identity.

        Raises:
            BronzeIntegrityError: if an object already exists at this identity
                whose stored bytes differ. Two different payloads cannot share
                one identity, and resolving the collision by overwriting would
                destroy the earlier acquisition.
        """
        digest = sha256_hex(payload)
        destination = self.object_path(
            provider=retrieval.provider,
            dataset=retrieval.dataset,
            ingest_date=ingest_date,
            digest=digest,
        )
        metadata_path = destination.with_suffix("").with_suffix(".meta.json")

        if destination.exists():
            stored = self.read(destination)
            if stored != payload:
                raise BronzeIntegrityError(
                    f"Bronze object {digest} already holds different bytes at {destination}. "
                    "Bronze is content-addressed and append-only: identical identity with "
                    "different content means either a hash collision or a corrupted store, "
                    "and neither is resolved by overwriting."
                )
            return BronzeArtifact(
                content_sha256=digest,
                path=destination,
                metadata_path=metadata_path,
                byte_count=len(payload),
                was_written=False,
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        compressed = gzip.compress(payload, _COMPRESSION_LEVEL, mtime=_DETERMINISTIC_MTIME)
        metadata = _metadata_row(retrieval, digest, len(payload))
        _atomic_write(destination, compressed)
        _atomic_write(metadata_path, canonical_bytes(metadata))

        return BronzeArtifact(
            content_sha256=digest,
            path=destination,
            metadata_path=metadata_path,
            byte_count=len(payload),
            was_written=True,
        )

    def read(self, path: Path) -> bytes:
        """Return the exact uncompressed payload bytes stored at ``path``."""
        return gzip.decompress(path.read_bytes())

    def verify(self, artifact: BronzeArtifact) -> bool:
        """Whether the stored object still hashes to the identity it claims."""
        return sha256_hex(self.read(artifact.path)) == artifact.content_sha256


def _metadata_row(retrieval: RetrievalMetadata, digest: str, byte_count: int) -> dict[str, object]:
    return {
        "content_sha256": digest,
        "byte_count": byte_count,
        "provider": retrieval.provider,
        "dataset": retrieval.dataset,
        "requested_range": retrieval.requested_range,
        "retrieved_at": retrieval.retrieved_at,
        "source_schema_version": retrieval.source_schema_version,
        "notes": retrieval.notes,
    }


def _atomic_write(destination: Path, payload: bytes) -> None:
    """Write ``payload`` to ``destination`` atomically.

    Same directory, so the rename cannot cross a filesystem boundary and degrade
    to a copy. ``os.replace`` is atomic on both POSIX and Windows.
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


def build_ingestion_run(
    *,
    ingestion_run_id: str,
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
    """Build the immutable record of one acquisition.

    ``ingestion_run_id`` is supplied by the caller and expected to be
    deterministic, in the ADR-0004 s.2 spirit: no ``uuid4()``, no timestamps in
    an identity. A derived id means two runs claiming to be the same run can be
    checked against each other rather than merely asserted to match.
    """
    return IngestionRun(
        ingestion_run_id=ingestion_run_id,
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
