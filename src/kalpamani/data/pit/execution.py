"""What a run actually read, recorded while it read it.

The research manifest used to take its input inventory as arguments:
``directly_read_datasets=[]``, ``unapproved_bounds_relied_upon=()``,
``hash_mismatches=()``. Every evidence rule downstream was then enforced against
whatever the caller chose to admit, which is not a rule -- a caller obtained a
valid manifest by passing empty lists, and the manifest would say, truthfully,
that nothing it had been told about was wrong.

Two of those arguments were worse than merely weak. ``unapproved_bounds_relied_upon``
and ``hash_mismatches`` were *side channels*: the only way a manifest could learn
that a bound was unapproved or a hash failed was for the caller to volunteer it,
so the one party with a reason to stay quiet was the one being asked.

This module closes both. The verified query path records what it reads as it
reads it, into an accumulator it owns, and hands out an immutable
:class:`ExecutionEvidence` snapshot. :class:`~kalpamani.data.contracts.manifest.InputInventory`
is built **from** that snapshot. If the query path did not record a dataset, that
is a bug here -- not a caller's prerogative.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionEvidence:
    """An immutable account of one run's reads, produced by the query path.

    Every field answers a question the manifest would otherwise have to ask the
    caller: which datasets were touched, which publication each came from, what
    quality evidence gated it, which bounds the answers leant on, and whether any
    of them were unapproved or failed to verify.
    """

    dataset_version: str
    publication_manifest_hash: str
    quality_report_hash: str
    direct_source_datasets: tuple[str, ...]
    dataset_manifest_hashes: Mapping[str, str]
    revisable_datasets_consumed: tuple[str, ...]
    consumed_artifact_ids: tuple[str, ...]
    bounds_relied_upon: tuple[str, ...]
    #: Bounds relied upon whose derivation was not approved for their dataset.
    #: Recorded by the run rather than declared by the caller.
    unapproved_bounds_relied_upon: tuple[str, ...]
    #: Content hashes that failed to verify during execution. Same reason.
    hash_mismatches: tuple[str, ...]
    origin_exclusion_rows: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dataset_manifest_hashes",
            MappingProxyType(dict(sorted(self.dataset_manifest_hashes.items()))),
        )


class ExecutionRecorder:
    """The accumulator a reader writes into while serving queries.

    Mutable by necessity -- a run learns what it read by reading -- and it hands
    out only frozen snapshots, so nothing downstream holds a reference that can
    change after a manifest hashes it.
    """

    def __init__(self, *, dataset_version: str, manifest_hash: str, quality_hash: str) -> None:
        """Bind the recorder to the publication whose reads it will describe."""
        self._dataset_version = dataset_version
        self._manifest_hash = manifest_hash
        self._quality_hash = quality_hash
        self._datasets: set[str] = set()
        self._revisable: set[str] = set()
        self._artifacts: set[str] = set()
        self._bounds: set[str] = set()
        self._unapproved_bounds: set[str] = set()
        self._hash_mismatches: set[str] = set()
        self._excluded_rows = 0

    def record_read(
        self,
        datasets: Iterable[str],
        *,
        revisable: Iterable[str] = (),
        excluded_rows: int = 0,
    ) -> None:
        """Record one query's direct source reads."""
        self._datasets.update(datasets)
        self._revisable.update(revisable)
        self._excluded_rows += excluded_rows

    def record_artifact(self, artifact_id: str) -> None:
        """Record a derived artifact a query consumed."""
        self._artifacts.add(artifact_id)

    def record_bound(self, dataset: str, *, approved: bool) -> None:
        """Record that an answer leant on a bounded availability time."""
        self._bounds.add(dataset)
        if not approved:
            self._unapproved_bounds.add(dataset)

    def record_hash_mismatch(self, detail: str) -> None:
        """Record a content hash that failed to verify during execution."""
        self._hash_mismatches.add(detail)

    def evidence(self) -> ExecutionEvidence:
        """An immutable snapshot of everything recorded so far."""
        datasets = tuple(sorted(self._datasets))
        return ExecutionEvidence(
            dataset_version=self._dataset_version,
            publication_manifest_hash=self._manifest_hash,
            quality_report_hash=self._quality_hash,
            direct_source_datasets=datasets,
            dataset_manifest_hashes={self._dataset_version: self._manifest_hash},
            revisable_datasets_consumed=tuple(sorted(self._revisable)),
            consumed_artifact_ids=tuple(sorted(self._artifacts)),
            bounds_relied_upon=tuple(sorted(self._bounds)),
            unapproved_bounds_relied_upon=tuple(sorted(self._unapproved_bounds)),
            hash_mismatches=tuple(sorted(self._hash_mismatches)),
            origin_exclusion_rows=self._excluded_rows,
        )


__all__ = ["ExecutionEvidence", "ExecutionRecorder"]
