"""What a run actually read, recorded while it read it, sealed to what it produced.

The research manifest used to take its input inventory as arguments:
``directly_read_datasets=[]``, ``unapproved_bounds_relied_upon=()``,
``hash_mismatches=()``. Every evidence rule downstream was then enforced against
whatever the caller chose to admit, which is not a rule -- a caller obtained a
valid manifest by passing empty lists, and the manifest would say, truthfully,
that nothing it had been told about was wrong.

Closing that took three passes, and each pass revealed the next.

**First: record what was read.** The verified query path writes into an
accumulator it owns and hands out an immutable :class:`ExecutionEvidence`.

**Then: seal it to the result.** An inventory built from evidence and one written
by hand were the same type, so a shortened one was accepted on sight.
:class:`ExecutedResult` binds them together.

**Then: stop the seal being a formality.** ``PointInTimeReader.seal(result,
result_bytes)`` took *any* object and *any* bytes and stamped them with whatever
evidence the reader had accumulated -- across every earlier query. Three separate
failures in one method: the result need not be one the reader produced, the bytes
need not encode it, and the evidence need not be about it.

So no such method exists. Each accessor runs against a **fresh recorder**, encodes
its own result canonically, records the
:class:`~kalpamani.data.pit.query.QuerySpec` it served, and returns the sealed
value itself. A later query inherits nothing from an earlier one, because it does
not share the recorder that would have carried it.

**The seal is structural, not a flag.** :class:`ExecutedResult` is deliberately
*not* a dataclass: ``dataclasses.replace`` copies a token field straight through,
so a token stored in a readable field is no boundary at all. ``replace`` cannot
touch a non-dataclass, and the consuming operation re-derives every identity it
depends on rather than trusting what it is handed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final, Generic, TypeVar

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.errors import ExecutionSealError
from kalpamani.data.contracts.resolution import TimingBasisUsed
from kalpamani.data.pit.query import QuerySpec

ResultT = TypeVar("ResultT")


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
class RowTimingEvidence:
    """How one dataset's **served** rows were actually admitted.

    Per query and per row, not per dataset and per build. A dataset containing
    bounded rows and a result that leant on one are different claims, and
    reporting the first as the second put a ``PROVIDER_TIME_BOUNDED`` limitation
    on results computed entirely from exact times.
    """

    dataset: str
    bases: frozenset[TimingBasisUsed]
    rows: int

    @property
    def used_a_bound(self) -> bool:
        """Whether a row this result actually served was admitted on a bound."""
        return bool(self.bases & {TimingBasisUsed.PUBLIC_BOUNDED, TimingBasisUsed.PROVIDER_BOUNDED})


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionEvidence:
    """An immutable account of **one query's** reads, produced by the query path.

    Every field answers a question the manifest would otherwise have to ask the
    caller: which datasets were touched, which publication each came from, what
    quality evidence gated it, how the rows it served were admitted, and whether
    any of that was unapproved or failed to verify.
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
    #: How the rows this query served were admitted, per dataset.
    timing_evidence: tuple[RowTimingEvidence, ...]
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

    def bases_for(self, dataset: str) -> frozenset[TimingBasisUsed]:
        """How ``dataset``'s served rows were admitted, or nothing if it was not read."""
        for entry in self.timing_evidence:
            if entry.dataset == dataset:
                return entry.bases
        return frozenset()

    def identity(self) -> dict[str, object]:
        """The canonical form the run's identity hashes."""
        return {
            "direct_source_datasets": list(self.direct_source_datasets),
            "dataset_manifest_hashes": dict(self.dataset_manifest_hashes),
            "consumed_artifact_ids": list(self.consumed_artifact_ids),
            "revisable_datasets_consumed": list(self.revisable_datasets_consumed),
            "timing_evidence": [
                [entry.dataset, sorted(basis.value for basis in entry.bases), entry.rows]
                for entry in self.timing_evidence
            ],
            "bounds_relied_upon": list(self.bounds_relied_upon),
            "unapproved_bounds_relied_upon": list(self.unapproved_bounds_relied_upon),
            "hash_mismatches": list(self.hash_mismatches),
            "origin_exclusion_rows": self.origin_exclusion_rows,
            "quality_report_hash": self.quality_report_hash,
        }


class ExecutionRecorder:
    """The accumulator **one accessor call** writes into while it answers.

    Created per query, never per reader. A reader-lifetime recorder meant the
    second query's inventory named the first query's datasets, so a manifest for a
    universe query truthfully claimed to have read price bars -- and every
    downstream evidence rule was then enforced against a set of reads that was not
    this result's.

    Mutable by necessity -- a query learns what it read by reading -- and it hands
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
        self._bases: dict[str, set[TimingBasisUsed]] = {}
        self._served: dict[str, int] = {}
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

    def record_served_row(
        self, dataset: str, bases: frozenset[TimingBasisUsed], *, approved: bool
    ) -> None:
        """Record how one row this result actually served was admitted.

        Per row, because the alternative -- reading the dataset's build-time
        evidence -- reports a query as having leant on a bound when every row it
        served carried an exact time.
        """
        self._bases.setdefault(dataset, set()).update(bases)
        self._served[dataset] = self._served.get(dataset, 0) + 1
        if not approved and (
            bases & {TimingBasisUsed.PUBLIC_BOUNDED, TimingBasisUsed.PROVIDER_BOUNDED}
        ):
            self._unapproved_bounds.add(dataset)

    def record_artifact(self, artifact: ConsumedArtifactRecord) -> None:
        """Record a derived artifact a query consumed, with its full identity.

        Raises:
            ExecutionSealError: if a different artifact is already recorded under
                this id. Replacing it silently would let whichever description
                arrived last decide what the run claims to have read.
        """
        existing = self._artifacts.get(artifact.artifact_id)
        if existing is not None and existing != artifact:
            raise ExecutionSealError(
                f"Two different artifacts are recorded under {artifact.artifact_id!r}. "
                "Keeping the later one would let the order a query happened to read them in "
                "decide what the run claims it consumed."
            )
        self._artifacts[artifact.artifact_id] = artifact

    def record_hash_mismatch(self, detail: str) -> None:
        """Record a content hash that failed to verify during execution."""
        self._hash_mismatches.add(detail)

    def origin_exclusions(self) -> tuple[tuple[str, str, int], ...]:
        """Rows dropped for origin ineligibility, itemised and ordered."""
        return tuple(
            (dataset, origin, rows) for (dataset, origin), rows in sorted(self._exclusions.items())
        )

    def evidence(self) -> ExecutionEvidence:
        """An immutable snapshot of everything recorded so far."""
        timing = tuple(
            RowTimingEvidence(
                dataset=dataset,
                bases=frozenset(bases),
                rows=self._served.get(dataset, 0),
            )
            for dataset, bases in sorted(self._bases.items())
        )
        return ExecutionEvidence(
            dataset_version=self._dataset_version,
            publication_manifest_hash=self._manifest_hash,
            quality_report_hash=self._quality_hash,
            direct_source_datasets=tuple(sorted(self._datasets)),
            dataset_manifest_hashes={self._dataset_version: self._manifest_hash},
            revisable_datasets_consumed=tuple(sorted(self._revisable)),
            consumed_artifact_ids=tuple(sorted(self._artifacts)),
            consumed_artifacts=tuple(self._artifacts[key] for key in sorted(self._artifacts)),
            timing_evidence=timing,
            bounds_relied_upon=tuple(
                sorted(entry.dataset for entry in timing if entry.used_a_bound)
            ),
            unapproved_bounds_relied_upon=tuple(sorted(self._unapproved_bounds)),
            hash_mismatches=tuple(sorted(self._hash_mismatches)),
            origin_exclusion_rows=self._excluded_rows,
        )


#: Held by the accessors alone. Not sufficient on its own -- see the class below.
_EXECUTION_TOKEN: Final = object()


class ExecutedResult(Generic[ResultT]):
    """One query's answer, sealed to the question and the evidence that produced it.

    Deliberately **not a dataclass**. A frozen dataclass carrying a token in a
    readable field looks sealed and is not: ``dataclasses.replace`` copies the
    token straight through onto different contents, and every check the token
    guards then passes. ``replace`` cannot operate on a non-dataclass at all, so
    the boundary is structural rather than a flag anyone can carry across.

    The result, its canonical bytes, the question and the evidence travel as one
    value because separating them is what let them disagree. A caller holding a
    result and an inventory could substitute either; a caller holding this can
    substitute neither, and
    :func:`~kalpamani.data.contracts.manifest.emit_manifest` re-derives the
    identities it depends on rather than trusting them.
    """

    __slots__ = (
        "_bounds_relied_upon",
        "_canonical_bytes",
        "_dataset_version",
        "_evidence",
        "_origin_exclusions",
        "_publication_manifest_hash",
        "_quality_report_hash",
        "_query",
        "_result",
        "_result_bytes_hash",
    )

    def __init__(
        self,
        *,
        result: ResultT,
        result_bytes: bytes,
        query: QuerySpec,
        evidence: ExecutionEvidence,
        dataset_version: str,
        publication_manifest_hash: str,
        quality_report_hash: str,
        origin_exclusions: Sequence[tuple[str, str, int]],
        token: object,
    ) -> None:
        """Seal a result. ``token`` is the accessors', and nothing else has it."""
        if token is not _EXECUTION_TOKEN:
            raise ExecutionSealError(
                "An ExecutedResult may only be produced by a PointInTimeReader accessor. A "
                "result and an inventory assembled at a call site can each be substituted for "
                "something else, which is the whole reason they travel as one sealed value."
            )
        if not quality_report_hash:
            raise ExecutionSealError(
                "An ExecutedResult carries no quality-report identity. Absence of evidence and "
                "absence of a finding are different claims."
            )
        self._result = result
        self._canonical_bytes = result_bytes
        self._result_bytes_hash = sha256_hex(result_bytes)
        self._query = query
        self._evidence = evidence
        self._dataset_version = dataset_version
        self._publication_manifest_hash = publication_manifest_hash
        self._quality_report_hash = quality_report_hash
        self._origin_exclusions = tuple(sorted(origin_exclusions))
        self._bounds_relied_upon = evidence.bounds_relied_upon

    @property
    def result(self) -> ResultT:
        """The typed query result, exactly as the accessor returned it."""
        return self._result

    @property
    def result_bytes(self) -> bytes:
        """The canonical bytes this result encodes to.

        Handed out rather than taken in. A caller emitting the result writes
        *these*, so the hash the manifest checks and the bytes on disk cannot
        describe different things -- which is exactly what accepting bytes from a
        caller allowed.
        """
        return self._canonical_bytes

    @property
    def result_bytes_hash(self) -> str:
        """SHA-256 of the canonical bytes this result encodes to."""
        return self._result_bytes_hash

    @property
    def query(self) -> QuerySpec:
        """What was asked, recorded by the accessor that answered it."""
        return self._query

    @property
    def evidence(self) -> ExecutionEvidence:
        """What this one query read."""
        return self._evidence

    @property
    def dataset_version(self) -> str:
        """The publication this query was served from."""
        return self._dataset_version

    @property
    def publication_manifest_hash(self) -> str:
        """The identity of that publication."""
        return self._publication_manifest_hash

    @property
    def quality_report_hash(self) -> str:
        """The quality evidence that publication was gated on."""
        return self._quality_report_hash

    @property
    def origin_exclusions(self) -> tuple[tuple[str, str, int], ...]:
        """Rows dropped for origin ineligibility, itemised as the manifest records them."""
        return self._origin_exclusions

    @property
    def bounds_relied_upon(self) -> tuple[str, ...]:
        """Datasets whose **served rows** were admitted on a bound."""
        return self._bounds_relied_upon

    @property
    def exclusion_rows(self) -> int:
        """Total rows dropped for origin ineligibility across this result."""
        return sum(rows for _, _, rows in self._origin_exclusions)

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return (
            f"ExecutedResult(query={self._query.kind!r}, dataset_version={self._dataset_version!r})"
        )


def seal_executed_result(
    *,
    result: ResultT,
    result_payload: Mapping[str, Any],
    query: QuerySpec,
    recorder: ExecutionRecorder,
    dataset_version: str,
    publication_manifest_hash: str,
    quality_report_hash: str,
    token: object,
) -> ExecutedResult[ResultT]:
    """Encode a result canonically and seal it to the query that produced it.

    The bytes are derived **here**, from the result's own canonical payload,
    rather than accepted from a caller. Accepting them meant the hash the manifest
    checks and the numbers the caller emits could describe different things.
    """
    return ExecutedResult(
        result=result,
        result_bytes=canonical_bytes(result_payload),
        query=query,
        evidence=recorder.evidence(),
        dataset_version=dataset_version,
        publication_manifest_hash=publication_manifest_hash,
        quality_report_hash=quality_report_hash,
        origin_exclusions=recorder.origin_exclusions(),
        token=token,
    )


__all__ = [
    "ConsumedArtifactRecord",
    "ExecutedResult",
    "ExecutionEvidence",
    "ExecutionRecorder",
    "RowTimingEvidence",
    "seal_executed_result",
]
