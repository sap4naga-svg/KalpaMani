"""Atomic dataset publication, and reads that verify before they decode.

A dataset version is **published or it does not exist**. There is no partially
published build, because a half-written build is not a smaller build: reading one
produces a result nobody can reproduce, from inputs nobody can name.

Publication sequence, and why each step is where it is:

1. every table is written into a **staging** directory for this version, each
   fsync-ed as it lands;
2. the **dataset manifest** -- coverage, resolved profile, resolution policy,
   every table path, row count and content hash, source ingestion runs, and a
   dataset-level hash over all of them -- is written and fsync-ed **into the
   staging directory**;
3. the staging directory is **atomically renamed** into its final location.

The rename is the commit. Before it, nothing is visible under the published name;
after it, everything is. A reader therefore never observes a manifest that
describes tables that are not there yet, nor tables no manifest describes.

**Readers do not take the caller's word for anything.** Build time, coverage and
resolved profile come from the persisted manifest, never from arguments -- an ad
hoc coverage window supplied at read time would let a caller widen a dataset's
claims without touching the dataset. Every table hash is verified **before** its
rows are decoded, so corruption is caught as corruption rather than surfacing as
a strange value three layers up.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from kalpamani.data.contracts.canonical import canonical_bytes, content_hash, sha256_hex
from kalpamani.data.contracts.dataset import GoldDataset
from kalpamani.data.contracts.entities import DatasetVersion, UniverseMembership
from kalpamani.data.contracts.errors import DatasetPublicationError
from kalpamani.data.contracts.instants import normalize_instant
from kalpamani.data.contracts.profiles import (
    DatasetResolutionEvidence,
    ProfileResolutionConfig,
    TimingBasis,
)
from kalpamani.data.contracts.resolution import BoundApprovals, PitRecord
from kalpamani.data.contracts.serde import (
    decode_corporate_action,
    decode_listing,
    decode_market_session,
    decode_price_bar,
    decode_security_attribute,
    decode_ticker_history,
    decode_universe_membership,
    encode_corporate_action,
    encode_listing,
    encode_market_session,
    encode_price_bar,
    encode_security_attribute,
    encode_ticker_history,
    encode_universe_membership,
)
from kalpamani.data.contracts.vocabulary import (
    DatasetGapPolicy,
    InformationSetProfile,
    StorageLayer,
)
from kalpamani.data.curate.lineage import resolve_lineage
from kalpamani.data.curate.universe import membership_hash_of
from kalpamani.data.storage import LocalTableStore

#: Entity tables a Gold dataset version holds, in canonical order.
GOLD_ENTITIES = (
    "market_session",
    "listing",
    "security_attribute",
    "ticker_history",
    "price_bar",
    "corporate_action",
    "universe_membership",
)

#: Filename of the manifest whose arrival commits a version.
MANIFEST_NAME = "_dataset_manifest.json"

#: Version of the publication format itself.
PUBLICATION_FORMAT_VERSION = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class TableRecord:
    """One table inside a published version."""

    entity: str
    relative_path: str
    row_count: int
    content_hash: str


@dataclass(frozen=True, slots=True, kw_only=True)
class DatasetManifest:
    """What a published version claims about itself. Verified on every read."""

    publication_format_version: int
    dataset_version: str
    layer: StorageLayer
    build_time: datetime
    coverage_start: date
    coverage_end: date
    resolved_profile: InformationSetProfile
    resolution_policy_version: str
    resolution_evidence: tuple[DatasetResolutionEvidence, ...]
    tables: tuple[TableRecord, ...]
    source_ingestion_run_ids: tuple[str, ...]
    code_commit_sha: str
    lag_policy_version: str
    universe_definition_version: str | None
    dataset_content_hash: str
    is_published: bool

    def table(self, entity: str) -> TableRecord:
        """The record for one entity's table."""
        for record in self.tables:
            if record.entity == entity:
                return record
        raise DatasetPublicationError(
            f"Published version {self.dataset_version} declares no table for {entity!r}. A "
            "manifest that does not describe every table it published is a partial "
            "publication."
        )


def _evidence_row(entry: DatasetResolutionEvidence) -> dict[str, object]:
    return {
        "dataset": entry.dataset,
        "policy": entry.policy.value,
        "rows_considered": entry.rows_considered,
        "public_basis": entry.public_basis.value,
        "public_exact_rows": entry.public_exact_rows,
        "public_bounded_rows": entry.public_bounded_rows,
        "provider_basis": entry.provider_basis.value,
        "provider_exact_rows": entry.provider_exact_rows,
        "provider_bounded_rows": entry.provider_bounded_rows,
        "excluded_rows": entry.excluded_rows,
        "reason": entry.reason,
    }


def _decode_evidence(row: Mapping[str, object]) -> DatasetResolutionEvidence:
    return DatasetResolutionEvidence(
        dataset=str(row["dataset"]),
        policy=DatasetGapPolicy(str(row["policy"])),
        rows_considered=int(str(row["rows_considered"])),
        public_basis=TimingBasis(str(row["public_basis"])),
        public_exact_rows=int(str(row["public_exact_rows"])),
        public_bounded_rows=int(str(row["public_bounded_rows"])),
        provider_basis=TimingBasis(str(row["provider_basis"])),
        provider_exact_rows=int(str(row["provider_exact_rows"])),
        provider_bounded_rows=int(str(row["provider_bounded_rows"])),
        excluded_rows=int(str(row["excluded_rows"])),
        reason=str(row["reason"]),
    )


def _manifest_body(manifest: DatasetManifest) -> dict[str, object]:
    return {
        "publication_format_version": manifest.publication_format_version,
        "dataset_version": manifest.dataset_version,
        "layer": manifest.layer.value,
        "build_time": manifest.build_time.isoformat(),
        "coverage_start": manifest.coverage_start.isoformat(),
        "coverage_end": manifest.coverage_end.isoformat(),
        "resolved_profile": manifest.resolved_profile.value,
        "resolution_policy_version": manifest.resolution_policy_version,
        "resolution_evidence": [_evidence_row(e) for e in manifest.resolution_evidence],
        "tables": [
            {
                "entity": table.entity,
                "relative_path": table.relative_path,
                "row_count": table.row_count,
                "content_hash": table.content_hash,
            }
            for table in manifest.tables
        ],
        "source_ingestion_run_ids": list(manifest.source_ingestion_run_ids),
        "code_commit_sha": manifest.code_commit_sha,
        "lag_policy_version": manifest.lag_policy_version,
        "universe_definition_version": manifest.universe_definition_version,
        "dataset_content_hash": manifest.dataset_content_hash,
        "is_published": manifest.is_published,
    }


def _dataset_hash(tables: Sequence[TableRecord]) -> str:
    return content_hash(
        sorted([table.entity, table.content_hash, str(table.row_count)] for table in tables)
    )


def _encode_tables(dataset: GoldDataset) -> dict[str, list[Mapping[str, object]]]:
    universe_rows: list[UniverseMembership] = []
    for rows in dataset.universe.values():
        universe_rows.extend(rows)
    return {
        "market_session": [encode_market_session(s) for s in dataset.sessions],
        "listing": [encode_listing(item) for item in dataset.listings],
        "security_attribute": [encode_security_attribute(a) for a in dataset.attributes],
        "ticker_history": [encode_ticker_history(t) for t in dataset.tickers],
        "price_bar": [encode_price_bar(b) for b in dataset.bars],
        "corporate_action": [encode_corporate_action(a) for a in dataset.actions],
        "universe_membership": [encode_universe_membership(u) for u in universe_rows],
    }


def publish_gold_dataset(
    store: LocalTableStore,
    dataset: GoldDataset,
    *,
    code_commit_sha: str,
    lag_policy_version: str,
    universe_definition_version: str | None,
    source_ingestion_run_ids: Sequence[str] = (),
) -> tuple[DatasetVersion, DatasetManifest]:
    """Build a version in staging, then commit it with one atomic rename.

    Raises:
        DatasetPublicationError: if the version is already published. A published
            version is superseded, never rewritten.
    """
    final = store.version_root(layer=StorageLayer.GOLD, dataset_version=dataset.dataset_version)
    if (final / MANIFEST_NAME).exists():
        raise DatasetPublicationError(
            f"Gold version {dataset.dataset_version} is already published. Versions are "
            "superseded, never rewritten -- every manifest that named this one would "
            "otherwise start describing different data."
        )

    staging = store.staging_root(layer=StorageLayer.GOLD, dataset_version=dataset.dataset_version)
    if staging.exists():
        # A previous attempt died before committing. Nothing observed it, because
        # the commit is the rename, so discarding it loses nothing.
        shutil.rmtree(staging)

    encoded = _encode_tables(dataset)
    tables: list[TableRecord] = []
    for entity in GOLD_ENTITIES:
        rows = encoded[entity]
        artifact = store.write_staged_table(
            layer=StorageLayer.GOLD,
            dataset_version=dataset.dataset_version,
            entity=entity,
            rows=rows,
        )
        tables.append(
            TableRecord(
                entity=entity,
                relative_path=artifact.path.name,
                row_count=artifact.row_count,
                content_hash=artifact.content_hash,
            )
        )

    manifest = DatasetManifest(
        publication_format_version=PUBLICATION_FORMAT_VERSION,
        dataset_version=dataset.dataset_version,
        layer=StorageLayer.GOLD,
        build_time=normalize_instant(dataset.build_time),
        coverage_start=dataset.coverage_start,
        coverage_end=dataset.coverage_end,
        resolved_profile=dataset.resolved_profile,
        resolution_policy_version=dataset.resolution_policy_version,
        resolution_evidence=dataset.resolution_evidence,
        tables=tuple(tables),
        source_ingestion_run_ids=tuple(sorted(source_ingestion_run_ids)),
        code_commit_sha=code_commit_sha,
        lag_policy_version=lag_policy_version,
        universe_definition_version=universe_definition_version,
        dataset_content_hash=_dataset_hash(tables),
        is_published=True,
    )
    store.write_staged_bytes(
        layer=StorageLayer.GOLD,
        dataset_version=dataset.dataset_version,
        name=MANIFEST_NAME,
        payload=canonical_bytes(_manifest_body(manifest)),
    )
    store.commit_version(layer=StorageLayer.GOLD, dataset_version=dataset.dataset_version)

    version = DatasetVersion(
        dataset_version=dataset.dataset_version,
        layer=StorageLayer.GOLD,
        built_at=dataset.build_time,
        built_from_run_ids=manifest.source_ingestion_run_ids,
        code_commit_sha=code_commit_sha,
        content_hash=manifest.dataset_content_hash,
        lag_policy_version=lag_policy_version,
        resolved_profile=dataset.resolved_profile,
        resolution_policy_version=dataset.resolution_policy_version,
        universe_definition_version=universe_definition_version,
    )
    return version, manifest


def load_dataset_manifest(store: LocalTableStore, *, dataset_version: str) -> DatasetManifest:
    """Load a published version's manifest, refusing anything unpublished.

    Raises:
        DatasetPublicationError: if the version is absent or the manifest is
            missing. Both mean the same thing: this version was never committed.
    """
    root = store.version_root(layer=StorageLayer.GOLD, dataset_version=dataset_version)
    path = root / MANIFEST_NAME
    if not path.exists():
        raise DatasetPublicationError(
            f"Gold version {dataset_version} has no published manifest at {path}. Publication "
            "is committed by an atomic rename, so an absent manifest means the version was "
            "never committed -- not that it is incomplete."
        )
    body = store.read_json(path)
    return DatasetManifest(
        publication_format_version=int(str(body["publication_format_version"])),
        dataset_version=str(body["dataset_version"]),
        layer=StorageLayer(str(body["layer"])),
        build_time=normalize_instant(datetime.fromisoformat(str(body["build_time"]))),
        coverage_start=date.fromisoformat(str(body["coverage_start"])),
        coverage_end=date.fromisoformat(str(body["coverage_end"])),
        resolved_profile=InformationSetProfile(str(body["resolved_profile"])),
        resolution_policy_version=str(body["resolution_policy_version"]),
        resolution_evidence=tuple(
            _decode_evidence(row) for row in list(body["resolution_evidence"])
        ),
        tables=tuple(
            TableRecord(
                entity=str(row["entity"]),
                relative_path=str(row["relative_path"]),
                row_count=int(str(row["row_count"])),
                content_hash=str(row["content_hash"]),
            )
            for row in list(body["tables"])
        ),
        source_ingestion_run_ids=tuple(
            str(item) for item in list(body["source_ingestion_run_ids"])
        ),
        code_commit_sha=str(body["code_commit_sha"]),
        lag_policy_version=str(body["lag_policy_version"]),
        universe_definition_version=(
            None
            if body["universe_definition_version"] is None
            else str(body["universe_definition_version"])
        ),
        dataset_content_hash=str(body["dataset_content_hash"]),
        is_published=bool(body["is_published"]),
    )


def read_published_dataset(
    store: LocalTableStore,
    *,
    dataset_version: str,
    config: ProfileResolutionConfig,
    approvals: BoundApprovals,
) -> GoldDataset:
    """Load a published version, verifying every table before decoding it.

    Build time, coverage and resolved profile come from the **manifest**. They are
    not parameters, because authoritative build metadata supplied at read time
    would let a caller restate what a dataset covers without touching the dataset.

    Raises:
        DatasetPublicationError: on a missing or partial publication, a table
            whose bytes do not match the hash the manifest records, a
            dataset-level hash that does not reconcile, or a resolution that
            disagrees with ``config``.
        ArtifactIntegrityError: if a stored membership row's lineage does not
            replay to exactly the rows it names, or its content hash does not
            reproduce.
    """
    manifest = load_dataset_manifest(store, dataset_version=dataset_version)
    _verify_publication(store, manifest)
    _verify_resolution_agrees(manifest, config)

    def rows(entity: str) -> Sequence[Mapping[str, object]]:
        return store.read_table(
            layer=StorageLayer.GOLD, dataset_version=dataset_version, entity=entity
        )

    sessions = tuple(decode_market_session(r) for r in rows("market_session"))
    listings = tuple(decode_listing(r) for r in rows("listing"))
    attributes = tuple(decode_security_attribute(r) for r in rows("security_attribute"))
    tickers = tuple(decode_ticker_history(r) for r in rows("ticker_history"))
    bars = tuple(decode_price_bar(r) for r in rows("price_bar"))
    actions = tuple(decode_corporate_action(r) for r in rows("corporate_action"))

    universe: dict[date, list[UniverseMembership]] = {}
    for row in rows("universe_membership"):
        stored = decode_universe_membership(row, ())
        replayed = resolve_lineage(
            stored.envelope.lineage,
            listings=listings,
            attributes=attributes,
            bars=bars,
        )
        member = decode_universe_membership(row, replayed)
        recomputed = membership_hash_of(member)
        if recomputed != member.envelope.artifact_content_hash:
            raise DatasetPublicationError(
                f"Stored membership for {member.security_id} on "
                f"{member.session_date.isoformat()} does not reproduce its content hash "
                f"(stored {member.envelope.artifact_content_hash}, recomputed {recomputed}). "
                "The decision or its lineage changed after the hash was taken."
            )
        universe.setdefault(member.session_date, []).append(member)

    return GoldDataset(
        dataset_version=manifest.dataset_version,
        build_time=manifest.build_time,
        coverage_start=manifest.coverage_start,
        coverage_end=manifest.coverage_end,
        resolved_profile=manifest.resolved_profile,
        resolution_policy_version=manifest.resolution_policy_version,
        resolution_evidence=manifest.resolution_evidence,
        sessions=sessions,
        listings=listings,
        attributes=attributes,
        tickers=tickers,
        bars=bars,
        actions=actions,
        universe={
            session: tuple(sorted(members, key=lambda m: m.security_id))
            for session, members in sorted(universe.items())
        },
    )


def _verify_publication(store: LocalTableStore, manifest: DatasetManifest) -> None:
    if not manifest.is_published:
        raise DatasetPublicationError(
            f"Gold version {manifest.dataset_version} is marked unpublished."
        )
    if manifest.publication_format_version != PUBLICATION_FORMAT_VERSION:
        raise DatasetPublicationError(
            f"Gold version {manifest.dataset_version} uses publication format "
            f"{manifest.publication_format_version}; this reader understands "
            f"{PUBLICATION_FORMAT_VERSION}. An unrecognised format is refused rather than "
            "read optimistically."
        )
    declared = {table.entity for table in manifest.tables}
    if declared != set(GOLD_ENTITIES):
        raise DatasetPublicationError(
            f"Gold version {manifest.dataset_version} declares tables {sorted(declared)}; a "
            f"complete publication declares {sorted(GOLD_ENTITIES)}."
        )
    for table in manifest.tables:
        path = store.table_path(
            layer=StorageLayer.GOLD,
            dataset_version=manifest.dataset_version,
            entity=table.entity,
        )
        if not path.exists():
            raise DatasetPublicationError(
                f"Gold version {manifest.dataset_version} declares table {table.entity!r} at "
                f"{path}, which does not exist. This is a partial publication."
            )
        actual = sha256_hex(path.read_bytes())
        if actual != table.content_hash:
            raise DatasetPublicationError(
                f"Table {table.entity!r} in {manifest.dataset_version} hashes to {actual}, "
                f"not the {table.content_hash} its manifest records. Verification happens "
                "before decoding, so corruption is caught as corruption."
            )
    recomputed = _dataset_hash(manifest.tables)
    if recomputed != manifest.dataset_content_hash:
        raise DatasetPublicationError(
            f"Gold version {manifest.dataset_version} has a dataset content hash that does "
            f"not reconcile with its tables (recorded {manifest.dataset_content_hash}, "
            f"recomputed {recomputed})."
        )


def _verify_resolution_agrees(manifest: DatasetManifest, config: ProfileResolutionConfig) -> None:
    if manifest.resolved_profile is not config.resolved_profile:
        raise DatasetPublicationError(
            f"Gold version {manifest.dataset_version} was curated under "
            f"{manifest.resolved_profile.value}; this run resolved to "
            f"{config.resolved_profile.value}. A dataset cannot answer a question it was not "
            "built for, and relabelling it would be exactly the profile substitution the "
            "contract forbids."
        )
    if manifest.resolution_policy_version != config.resolution_policy_version:
        raise DatasetPublicationError(
            f"Gold version {manifest.dataset_version} was resolved under policy "
            f"{manifest.resolution_policy_version!r}; this run declares "
            f"{config.resolution_policy_version!r}. Two runs that resolved the same gaps "
            "differently admit different rows."
        )
    published = {entry.dataset: entry.policy for entry in manifest.resolution_evidence}
    declared = {entry.dataset: entry.policy for entry in config.dataset_resolutions}
    disagreements = sorted(
        name for name, policy in published.items() if declared.get(name) is not policy
    )
    if disagreements:
        raise DatasetPublicationError(
            f"Gold version {manifest.dataset_version} was built with different per-dataset "
            f"policies than this run declares, for {disagreements}. The evidence has to "
            "describe the rows that are actually there."
        )


def resolved_universe_inputs(dataset: GoldDataset, session: date) -> tuple[PitRecord, ...]:
    """Every input the stored snapshot for ``session`` consumed, deduplicated.

    Useful for auditing a whole snapshot at once. Individual rows keep their own
    exact lineage; this is a union over them, not a substitute for it.
    """
    seen: list[PitRecord] = []
    for row in dataset.universe.get(session, ()):
        for record in row.inputs:
            if record not in seen:
                seen.append(record)
    return tuple(seen)


__all__ = [
    "GOLD_ENTITIES",
    "MANIFEST_NAME",
    "PUBLICATION_FORMAT_VERSION",
    "DatasetManifest",
    "TableRecord",
    "load_dataset_manifest",
    "publish_gold_dataset",
    "read_published_dataset",
    "resolved_universe_inputs",
]
