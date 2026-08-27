"""Immutable, content-addressed Bronze storage.

Bronze holds a payload **byte for byte, exactly as received**, named by the
SHA-256 of its contents, alongside the acquisition records describing how it
arrived. It is append-only. A re-fetch returning different bytes is a *new*
artifact, never a replacement -- which is what makes a vendor backfill visible
instead of silent, and what lets the profile model decide what to do about it.

**Two separate immutable things, deliberately.**

*The content object* is keyed by payload digest alone. Identical bytes fetched
ten times are one object, written once. Its identity is a property of what the
vendor sent, not of when we asked.

*An acquisition record* is written per retrieval, keyed by ``(digest,
ingestion_run_id)``. Fetching the same bytes again records a second acquisition
without duplicating or rewriting the content object -- which is the honest
account: we did fetch it twice, and there is still only one payload.

**Crash safety.** The two are written in a fixed order -- content first,
acquisition second -- and each atomically. That order makes the only reachable
inconsistency a payload with a missing acquisition record, which is *repairable*:
a retry completes it. The reverse order would leave an acquisition record naming
a payload that does not exist, which is not repairable from anything on disk.

A retry that finds a payload present and its acquisition record absent
**repairs** the record and says so. It never returns success while the metadata
remains missing: a payload nothing can explain is worse than no payload, because
it looks like evidence.

**The hashing contract, stated once.** The identity of an object is the SHA-256
of the **uncompressed payload bytes**. Gzip is a storage encoding, not part of
identity. Compression uses a fixed zero ``mtime`` and level, so the stored file is
itself byte-identical across writes and a file comparison cannot mistake a re-run
for a change.

**No network client exists here, and none is authorized in this slice.** This
module receives bytes a caller already holds. It has no HTTP dependency, no
credential handling and no provider knowledge -- which is the reason it can be
written and tested before gate G1 selects a provider at all.

The root path is always an explicit argument. Importing this module creates no
directory and touches no disk.
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


@dataclass(frozen=True, slots=True, kw_only=True)
class BronzeArtifact:
    """One immutable Bronze object and the acquisition that produced this call.

    ``content_written`` is ``False`` when the identical payload was already
    stored: writing the same bytes twice is idempotent, and reporting it as a
    write would make a re-run look like a new acquisition.

    ``acquisition_written`` is ``True`` whenever this retrieval's record was
    created -- including when it repaired an earlier interrupted write.
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

    def object_path(self, *, provider: str, dataset: str, ingest_date: date, digest: str) -> Path:
        """Where the content object with ``digest`` lives.

        The layout keeps the acquisition date in the path so a directory listing
        is chronologically meaningful, while identity remains the digest alone.
        """
        return self._partition(provider, dataset, ingest_date) / f"{digest}.json.gz"

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
        partition = self._partition(provider, dataset, ingest_date)
        return partition / f"{digest}.{ingestion_run_id}.acquisition.json"

    def _partition(self, provider: str, dataset: str, ingest_date: date) -> Path:
        return self._root / "bronze" / provider / dataset / ingest_date.isoformat()

    def write(
        self,
        *,
        payload: bytes,
        retrieval: RetrievalMetadata,
        ingest_date: date,
    ) -> BronzeArtifact:
        """Store ``payload`` immutably and record this acquisition.

        Content first, acquisition second, each atomic. A crash between them
        leaves a repairable state; the reverse order would not.

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
        acquisition = self.acquisition_path(
            provider=retrieval.provider,
            dataset=retrieval.dataset,
            ingest_date=ingest_date,
            digest=digest,
            ingestion_run_id=retrieval.ingestion_run_id,
        )

        content_written = False
        repaired = False
        if destination.exists():
            stored = self.read(destination)
            if stored != payload:
                raise BronzeIntegrityError(
                    f"Bronze object {digest} already holds different bytes at {destination}. "
                    "Bronze is content-addressed and append-only: identical identity with "
                    "different content means either a hash collision or a corrupted store, "
                    "and neither is resolved by overwriting."
                )
            # A payload present with no acquisition record is the one reachable
            # inconsistency, and this call repairs it rather than reporting success.
            repaired = not acquisition.exists()
        else:
            _atomic_write(
                destination,
                gzip.compress(payload, _COMPRESSION_LEVEL, mtime=_DETERMINISTIC_MTIME),
            )
            content_written = True

        acquisition_written = False
        if not acquisition.exists():
            _atomic_write(
                acquisition,
                canonical_bytes(_acquisition_body(retrieval, digest, len(payload))),
            )
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
        partition = self._partition(provider, dataset, ingest_date)
        if not partition.is_dir():
            return ()
        records: list[Mapping[str, Any]] = []
        for path in sorted(partition.glob(f"{digest}.*.acquisition.json")):
            decoded: Any = json.loads(path.read_text(encoding="utf-8"))
            records.append(decoded)
        return tuple(records)

    def audit_partition(self, *, provider: str, dataset: str, ingest_date: date) -> tuple[str, ...]:
        """Content digests present with no acquisition record at all.

        The recovery entry point: a caller repairs each by re-running its write,
        or refuses explicitly. Never by ignoring it.
        """
        partition = self._partition(provider, dataset, ingest_date)
        if not partition.is_dir():
            return ()
        orphaned: list[str] = []
        for path in sorted(partition.glob("*.json.gz")):
            digest = path.name.removesuffix(".json.gz")
            if not any(partition.glob(f"{digest}.*.acquisition.json")):
                orphaned.append(digest)
        return tuple(orphaned)

    def require_complete(self, *, provider: str, dataset: str, ingest_date: date) -> None:
        """Refuse a partition holding a payload nothing can explain.

        Raises:
            AcquisitionIncompleteError: naming every orphaned digest.
        """
        orphaned = self.audit_partition(provider=provider, dataset=dataset, ingest_date=ingest_date)
        if orphaned:
            raise AcquisitionIncompleteError(
                f"{len(orphaned)} Bronze payload(s) in {provider}/{dataset}/"
                f"{ingest_date.isoformat()} have no acquisition record: {list(orphaned)}. "
                "Repair by re-running the acquisition, or refuse the partition. A payload "
                "nothing can explain is worse than no payload, because it looks like evidence."
            )


def _acquisition_body(
    retrieval: RetrievalMetadata, digest: str, byte_count: int
) -> dict[str, object]:
    return {
        "content_sha256": digest,
        "byte_count": byte_count,
        "provider": retrieval.provider,
        "dataset": retrieval.dataset,
        "requested_range": retrieval.requested_range,
        "retrieved_at": retrieval.retrieved_at.isoformat(),
        "source_schema_version": retrieval.source_schema_version,
        "ingestion_run_id": retrieval.ingestion_run_id,
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
