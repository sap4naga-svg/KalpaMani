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

**Immutability is enforced, not documented.** A dataset version is written once.
Rewriting a table with different content is refused; rewriting it with identical
content is idempotent. Versions are superseded, never mutated -- which is what
makes silent history rewriting structurally impossible.

**Determinism is enforced too.** Rows are written in canonical order with
canonical scalar rendering, so two builds from the same inputs produce
byte-identical files and therefore identical hashes. A store whose bytes depended
on iteration order would make every "reproduces bit-identically" claim in this
system a coincidence.

The root path is always explicit. Importing this module creates no directory and
touches no disk.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_json, sha256_hex
from kalpamani.data.contracts.errors import ArtifactIntegrityError
from kalpamani.data.contracts.vocabulary import StorageLayer

#: Where a deployment's data lives by default. A path value, not a directory:
#: nothing here creates it, and importing this module performs no I/O.
DEFAULT_DATA_ROOT: Final = Path(".runtime") / "data"

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

    def table_path(self, *, layer: StorageLayer, dataset_version: str, entity: str) -> Path:
        """Where one entity's table lives inside one dataset version."""
        return self._root / layer.value.lower() / dataset_version / f"{entity}.jsonl"

    def write_table(
        self,
        *,
        layer: StorageLayer,
        dataset_version: str,
        entity: str,
        rows: Sequence[Row],
    ) -> TableArtifact:
        """Write ``rows`` as one immutable table.

        Raises:
            ArtifactIntegrityError: if the table already exists with different
                content. A dataset version is a promise about what it contains,
                and quietly rewriting one breaks every manifest that named it.
        """
        payload = _render(rows)
        destination = self.table_path(layer=layer, dataset_version=dataset_version, entity=entity)
        digest = sha256_hex(payload)

        if destination.exists():
            existing = destination.read_bytes()
            if existing != payload:
                raise ArtifactIntegrityError(
                    f"{layer.value} table {dataset_version}/{entity} already exists with "
                    f"different content (stored {sha256_hex(existing)}, would write {digest}). "
                    "Dataset versions are superseded, never mutated: publish a new version "
                    "instead."
                )
        else:
            _atomic_write(destination, payload)

        return TableArtifact(
            layer=layer,
            dataset_version=dataset_version,
            entity=entity,
            path=destination,
            row_count=len(rows),
            content_hash=digest,
        )

    def read_table(
        self,
        *,
        layer: StorageLayer,
        dataset_version: str,
        entity: str,
    ) -> tuple[Row, ...]:
        """Read one entity's table back.

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

    def verify_table(self, artifact: TableArtifact) -> bool:
        """Whether the stored table still hashes to the identity it claims."""
        if not artifact.path.exists():
            return False
        return sha256_hex(artifact.path.read_bytes()) == artifact.content_hash


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


__all__ = [
    "DEFAULT_DATA_ROOT",
    "LocalTableStore",
    "Row",
    "TableArtifact",
]
