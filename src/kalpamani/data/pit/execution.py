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

**And the inventory is not substitutable.** An ``InputInventory`` built from
evidence and one written out by hand are the same type, so the manifest could not
tell them apart: a caller who shortened the dataset list, dropped a consumed
artifact or restated the exclusion count produced an object the manifest accepted
on sight. :class:`ExecutedResult` closes that. It binds the result bytes, the
evidence, the verified publication's identity and the quality evidence into one
sealed value that only the reader can produce, and manifest construction takes
*it* rather than a freely constructed inventory.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Final

from kalpamani.data.contracts.canonical import sha256_hex
from kalpamani.data.contracts.errors import ExecutionSealError


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsumedArtifactRecord:
    """A derived artifact a query actually read, pinned well enough to reproduce.

    Mirrors :class:`~kalpamani.data.contracts.manifest.ConsumedArtifact` field for
    field, so the manifest is built from what the run recorded rather than from a
    parallel description of it. Two descriptions of one artifact would eventually
    disagree, and the disagreement would be invisible.
    """

    artifact_id: str
    entity: str
    output_validity: str
    derivation_spec_version: str
    artifact_content_hash: str
    artifact_first_built_time: datetime
    lineage_selectors: tuple[tuple[str, str, str], ...]


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
    #: The full identity of each of those artifacts, in the same order.
    consumed_artifacts: tuple[ConsumedArtifactRecord, ...]
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
        self._artifacts: dict[str, ConsumedArtifactRecord] = {}
        self._bounds: set[str] = set()
        self._unapproved_bounds: set[str] = set()
        self._hash_mismatches: set[str] = set()
        self._excluded_rows = 0
        self._exclusions: dict[tuple[str, str], int] = {}

    def record_read(
        self,
        datasets: Iterable[str],
        *,
        revisable: Iterable[str] = (),
        excluded_rows: int = 0,
        exclusions: Mapping[tuple[str, str], int] | None = None,
    ) -> None:
        """Record one query's direct source reads.

        ``exclusions`` are itemised by (dataset, origin) as well as counted, so
        the manifest's origin-exclusion block and the run's own count come from
        one place and cannot disagree.
        """
        self._datasets.update(datasets)
        self._revisable.update(revisable)
        self._excluded_rows += excluded_rows
        for key, rows in (exclusions or {}).items():
            self._exclusions[key] = self._exclusions.get(key, 0) + rows

    def origin_exclusions(self) -> tuple[tuple[str, str, int], ...]:
        """Rows dropped for origin ineligibility, itemised and ordered."""
        return tuple(
            (dataset, origin, rows) for (dataset, origin), rows in sorted(self._exclusions.items())
        )

    def record_artifact(self, artifact: ConsumedArtifactRecord) -> None:
        """Record a derived artifact a query consumed, with its full identity.

        An id alone is not enough for the manifest, which has to pin the content
        hash, the spec version, the lineage and -- under ``FORWARD_SYSTEM`` -- when
        the artifact was first built. Recording the id and describing the rest
        elsewhere would let the two drift.
        """
        self._artifacts[artifact.artifact_id] = artifact

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
            consumed_artifacts=tuple(self._artifacts[key] for key in sorted(self._artifacts)),
            bounds_relied_upon=tuple(sorted(self._bounds)),
            unapproved_bounds_relied_upon=tuple(sorted(self._unapproved_bounds)),
            hash_mismatches=tuple(sorted(self._hash_mismatches)),
            origin_exclusion_rows=self._excluded_rows,
        )


#: Held by the point-in-time reader alone. An ``ExecutedResult`` carrying it came
#: out of an actual query.
_EXECUTION_TOKEN: Final = object()


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutedResult:
    """One query's answer, sealed to the evidence that produced it.

    The result and its provenance travel as one value because separating them is
    what let them disagree. A caller holding a result and an inventory could
    substitute either; a caller holding this can substitute neither, because only
    :class:`~kalpamani.data.pit.accessors.PointInTimeReader` can make one.

    ``result_bytes_hash`` is over the **exact bytes** the caller will emit, so the
    manifest's claim about what was produced is checked against the thing
    produced rather than against a description of it.
    """

    #: The typed query result, whatever the accessor returned.
    result: object
    #: SHA-256 of the exact canonical bytes this result is emitted as.
    result_bytes_hash: str
    evidence: ExecutionEvidence
    dataset_version: str
    publication_manifest_hash: str
    quality_report_hash: str
    #: Rows dropped for origin ineligibility, itemised as the manifest records them.
    origin_exclusions: tuple[tuple[str, str, int], ...]
    #: Datasets whose answers leant on a bounded availability.
    bounds_relied_upon: tuple[str, ...]
    produced_by: object

    def __post_init__(self) -> None:
        if self.produced_by is not _EXECUTION_TOKEN:
            raise ExecutionSealError(
                "An ExecutedResult may only be produced by PointInTimeReader. A result and an "
                "inventory assembled at a call site can each be substituted for something "
                "else, which is the whole reason they now travel as one sealed value."
            )
        if not self.result_bytes_hash:
            raise ExecutionSealError(
                "An ExecutedResult carries no result hash. A result nothing identifies cannot "
                "be checked against the manifest that claims to describe it."
            )
        if not self.quality_report_hash:
            raise ExecutionSealError(
                "An ExecutedResult carries no quality-report identity. Absence of evidence and "
                "absence of a finding are different claims."
            )

    @property
    def exclusion_rows(self) -> int:
        """Total rows dropped for origin ineligibility across this result."""
        return sum(rows for _, _, rows in self.origin_exclusions)


def seal_executed_result(
    *,
    result: object,
    result_bytes: bytes,
    evidence: ExecutionEvidence,
    dataset_version: str,
    publication_manifest_hash: str,
    quality_report_hash: str,
    origin_exclusions: Sequence[tuple[str, str, int]],
    bounds_relied_upon: Sequence[str],
    token: object,
) -> ExecutedResult:
    """Seal a result. ``token`` is the reader's, and nothing else has it."""
    return ExecutedResult(
        result=result,
        result_bytes_hash=sha256_hex(result_bytes),
        evidence=evidence,
        dataset_version=dataset_version,
        publication_manifest_hash=publication_manifest_hash,
        quality_report_hash=quality_report_hash,
        origin_exclusions=tuple(sorted(origin_exclusions)),
        bounds_relied_upon=tuple(sorted(set(bounds_relied_upon))),
        produced_by=token,
    )


__all__ = [
    "ConsumedArtifactRecord",
    "ExecutedResult",
    "ExecutionEvidence",
    "ExecutionRecorder",
    "seal_executed_result",
]
