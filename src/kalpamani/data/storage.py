"""Local analytical storage for the Silver and Gold layers.

The smallest storage proof that can carry the point-in-time contract end to end:
Bronze bytes to normalised source facts to derived Gold artifacts to a
point-in-time query, with a verifiable content hash at every step.

**Why not Parquet and DuckDB yet.** The merged plan recommends them, and that
recommendation stands for the layer that will hold real vendor history. This
slice holds a few dozen fictitious rows, and what it must actually prove is
*determinism* and *content-addressed identity* -- not analytical throughput.
Newline-delimited canonical JSON gives both with no runtime dependency at all,
which keeps ``dependencies = []`` intact and keeps the A1 kernel installable and
testable with nothing but the standard library. Choosing a data engine before
gate G1 selects a provider would also fix the engine ahead of the decision that
determines the data volume it has to serve. The layout below is the one the plan
specifies, so adopting Parquet later is a writer change rather than a rewrite.

**Publication is atomic.** A version is built in a staging directory and committed
by a single directory rename. Before the rename nothing is visible under the
published name; after it, everything is. There is no window in which a reader can
see a manifest describing tables that have not landed, or tables no manifest
describes. Versions are superseded, never mutated.

**Determinism is enforced.** Rows are written in canonical order with canonical
scalar rendering, so two builds from the same inputs produce byte-identical files
and therefore identical hashes. A store whose bytes depended on iteration order
would make every "reproduces bit-identically" claim in this system a coincidence.

The root path is always explicit. Importing this module creates no directory and
touches no disk.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_json, sha256_hex
from kalpamani.data.contracts.errors import ArtifactIntegrityError, DatasetPublicationError
from kalpamani.data.contracts.paths import (
    internal_filename,
    safe_component,
    safe_relative_path,
)
from kalpamani.data.contracts.vocabulary import StorageLayer

#: Where a deployment's data lives by default. A path value, not a directory:
#: nothing here creates it, and importing this module performs no I/O.
DEFAULT_DATA_ROOT: Final = Path(".runtime") / "data"

#: Prefix marking a version directory that has not been committed. A reader never
#: looks inside one, so an abandoned build is invisible rather than partial.
STAGING_PREFIX: Final = "_staging-"

Row = Mapping[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class TableArtifact:
    """One written table, and the hash that identifies its contents."""

    layer: StorageLayer
    dataset_version: str
    entity: str
    path: Path
    row_count: int
    content_hash: str


class LocalTableStore:
    """Append-only, content-hashed local table storage rooted at an explicit path."""

    def __init__(self, root: Path) -> None:
        """Bind the store to ``root``. Nothing is created until a write happens."""
        self._root = Path(root)

    @property
    def root(self) -> Path:
        """The root this store writes under."""
        return self._root

    # -- locations ---------------------------------------------------------

    def version_root(self, *, layer: StorageLayer, dataset_version: str) -> Path:
        """The committed location of one dataset version.

        A dataset version is conventionally a path-like name (``gold/2026.08.26.1``),
        so it becomes nested directories and the leaf is the version itself.
        """
        safe_relative_path(dataset_version, kind="dataset_version")
        return self._root / layer.value.lower() / Path(dataset_version)

    def staging_root(self, *, layer: StorageLayer, dataset_version: str) -> Path:
        """The uncommitted location a version is assembled in.

        Deliberately a sibling of the **leaf**, not of the first path component.
        Prefixing an intermediate directory would rename a whole family of
        versions into place at once, and the commit is supposed to publish exactly
        one.
        """
        final = self.version_root(layer=layer, dataset_version=dataset_version)
        return final.parent / f"{STAGING_PREFIX}{final.name}"

    def table_path(self, *, layer: StorageLayer, dataset_version: str, entity: str) -> Path:
        """Where one entity's table lives inside a committed version."""
        safe_component(entity, kind="entity")
        return self.version_root(layer=layer, dataset_version=dataset_version) / f"{entity}.jsonl"

    def is_published(
        self, *, layer: StorageLayer, dataset_version: str, manifest_name: str
    ) -> bool:
        """Whether a committed version with a manifest exists."""
        root = self.version_root(layer=layer, dataset_version=dataset_version)
        return (root / manifest_name).exists()

    # -- staged writes -----------------------------------------------------

    def write_staged_table(
        self,
        *,
        layer: StorageLayer,
        dataset_version: str,
        entity: str,
        rows: Sequence[Row],
    ) -> TableArtifact:
        """Write one table into this version's staging directory."""
        payload = _render(rows)
        safe_component(entity, kind="entity")
        staging = self.staging_root(layer=layer, dataset_version=dataset_version)
        destination = staging / f"{entity}.jsonl"
        _atomic_write(destination, payload)
        return TableArtifact(
            layer=layer,
            dataset_version=dataset_version,
            entity=entity,
            path=destination,
            row_count=len(rows),
            content_hash=sha256_hex(payload),
        )

    def write_staged_bytes(
        self,
        *,
        layer: StorageLayer,
        dataset_version: str,
        name: str,
        payload: bytes,
    ) -> Path:
        """Write one of this package's own internal files into staging.

        ``name`` is checked against an exact allowlist rather than a prefix rule.
        An earlier version waved anything beginning with ``_`` straight through
        on the grounds that publication names its own files -- but
        ``_dataset_manifest.json/../../escape`` also begins with an underscore,
        and a rule with that hole in it is not a rule. There is no caller that
        needs to stage a file this package did not name.
        """
        internal_filename(name, kind="staged file")
        destination = self.staging_root(layer=layer, dataset_version=dataset_version) / name
        _atomic_write(destination, payload)
        return destination

    def commit_version(self, *, layer: StorageLayer, dataset_version: str) -> Path:
        """Promote a staged version with one atomic rename. **This is the commit.**

        Raises:
            DatasetPublicationError: if nothing was staged, or a committed version
                already exists under this name.
        """
        staging = self.staging_root(layer=layer, dataset_version=dataset_version)
        final = self.version_root(layer=layer, dataset_version=dataset_version)
        if not staging.exists():
            raise DatasetPublicationError(
                f"Nothing is staged for {layer.value} version {dataset_version}; there is "
                "nothing to commit."
            )
        if final.exists():
            raise DatasetPublicationError(
                f"{layer.value} version {dataset_version} already exists at {final}. Versions "
                "are superseded, never rewritten."
            )
        final.parent.mkdir(parents=True, exist_ok=True)
        _fsync_directory(staging)
        os.replace(staging, final)
        _fsync_directory(final.parent)
        return final

    def discard_staged_version(self, *, layer: StorageLayer, dataset_version: str) -> None:
        """Remove an uncommitted version. Nothing observed it, so nothing is lost."""
        staging = self.staging_root(layer=layer, dataset_version=dataset_version)
        if staging.exists():
            shutil.rmtree(staging)

    # -- reads -------------------------------------------------------------

    def read_table(
        self,
        *,
        layer: StorageLayer,
        dataset_version: str,
        entity: str,
    ) -> tuple[Row, ...]:
        """Read one entity's table back from a committed version.

        Raises:
            ArtifactIntegrityError: if the table does not exist. A missing table
                is a refusal, not an empty result -- returning nothing here is how
                a backtest ends up looking merely unprofitable rather than broken.
        """
        path = self.table_path(layer=layer, dataset_version=dataset_version, entity=entity)
        if not path.exists():
            raise ArtifactIntegrityError(
                f"{layer.value} table {dataset_version}/{entity} does not exist at {path}. "
                "An absent table is a refusal, not an empty result."
            )
        rows: list[Row] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line:
                decoded: Any = json.loads(line)
                rows.append(decoded)
        return tuple(rows)

    def read_json(self, path: Path) -> Mapping[str, Any]:
        """Read one JSON document, refusing anything that is not an object."""
        decoded: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(decoded, Mapping):
            raise DatasetPublicationError(f"{path} does not contain a JSON object.")
        return decoded

    def verify_table(self, artifact: TableArtifact) -> bool:
        """Whether the stored table still hashes to the identity it claims."""
        path = self.table_path(
            layer=artifact.layer,
            dataset_version=artifact.dataset_version,
            entity=artifact.entity,
        )
        candidate = path if path.exists() else artifact.path
        if not candidate.exists():
            return False
        return sha256_hex(candidate.read_bytes()) == artifact.content_hash


def _render(rows: Sequence[Row]) -> bytes:
    """Render rows to canonical newline-delimited JSON, in canonical order.

    Sorting on the canonical rendering rather than on a declared key means the
    order is a property of the content alone -- no entity has to nominate a sort
    key, and no entity can nominate one that fails to be total.
    """
    lines = sorted(canonical_json(row) for row in rows)
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def _atomic_write(destination: Path, payload: bytes) -> None:
    """Write ``payload`` to ``destination`` atomically, via the same directory."""
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


def _fsync_directory(path: Path) -> None:
    """Flush a directory entry, so a rename survives a crash.

    Not every platform supports opening a directory; where it does not, the
    rename is still atomic and the flush is simply unavailable. Refusing to run
    on such a platform would buy nothing.
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


__all__ = [
    "DEFAULT_DATA_ROOT",
    "STAGING_PREFIX",
    "LocalTableStore",
    "Row",
    "TableArtifact",
]
