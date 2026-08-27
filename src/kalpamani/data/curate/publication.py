"""Atomic dataset publication, and reads that verify before they decode.

A dataset version is **published or it does not exist**. There is no partially
published build, because a half-written build is not a smaller build: reading one
produces a result nobody can reproduce, from inputs nobody can name.

Publication sequence, and why each step is where it is:

1. the **resolution receipt** is verified against the rows about to be written --
   a build whose rows the resolution never saw is refused before anything lands;
2. the **quality report** is required and must carry no open BLOCKING finding;
3. every table is written into a **staging** directory, each fsync-ed as it lands;
4. the **dataset manifest** -- coverage, resolved profile, the complete resolution
   map and evidence, the quality-report identity, every table's path, row count
   and content hash, source ingestion runs, and a hash over all of it -- is
   written and fsync-ed into staging;
5. staging is **atomically renamed** into its final location.

The rename is the commit. Before it, nothing is visible under the published name;
after it, everything is.

**Readers do not take the caller's word for anything.** Build time, coverage,
resolved profile, resolution evidence and quality evidence all come from the
persisted manifest. Every table hash is verified **before** its rows are decoded,
the decoded row count is checked against the declared one, and the manifest body
is checked against its own hash. Two manifests that differ in profile, coverage
or policy evidence cannot share a dataset identity, because all of it is inside
that hash.

**The receipt is recomputed, not reconstructed.** An earlier read path rebuilt
the receipt with empty evidence and row fingerprints, which made the hash it
carried unfalsifiable -- the reconstruction could never disagree with anything,
so nothing was being checked. The read now rebuilds the **complete** receipt from
the manifest, the persisted evidence and the rows it actually decoded, and
compares its hash to ``manifest.resolution_receipt_hash``. A row substituted
between publication and read fails there, including one that kept its identifier
and changed only a price or an availability time.

**The verified read path is the only way to obtain a queryable publication.**
:func:`read_published_dataset` returns a :class:`VerifiedPublication`, which
cannot be constructed anywhere else, and the point-in-time reader accepts nothing
else. A hand-assembled dataset/manifest/report triplet is not a smaller amount of
evidence -- its hashes agree with each other, which is not the same as agreeing
with what was published.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, content_hash, sha256_hex
from kalpamani.data.contracts.dataset import GoldDataset, UniverseSnapshotHeader
from kalpamani.data.contracts.entities import (
    DatasetVersion,
    Listing,
    PriceBar,
    SecurityAttribute,
    UniverseMembership,
)
from kalpamani.data.contracts.errors import (
    BuildBoundaryError,
    DatasetPublicationError,
    QualityGateError,
)
from kalpamani.data.contracts.instants import is_canonical_instant, normalize_instant
from kalpamani.data.contracts.paths import safe_component, safe_relative_path
from kalpamani.data.contracts.profiles import (
    DatasetResolutionEvidence,
    ProfileResolutionConfig,
    ResolutionReceipt,
    TimingBasis,
    evidence_fingerprint,
)
from kalpamani.data.contracts.resolution import BoundApprovals, SourceRecord
from kalpamani.data.contracts.row_identity import row_fingerprint
from kalpamani.data.contracts.serde import (
    decode_corporate_action,
    decode_derived_envelope,
    decode_listing,
    decode_market_session,
    decode_price_bar,
    decode_security_attribute,
    decode_ticker_history,
    decode_universe_membership,
    encode_corporate_action,
    encode_derived_envelope,
    encode_listing,
    encode_market_session,
    encode_price_bar,
    encode_security_attribute,
    encode_ticker_history,
    encode_universe_membership,
)
from kalpamani.data.contracts.vocabulary import (
    DatasetGapPolicy,
    GlobalProfileResolution,
    InformationSetProfile,
    StorageLayer,
)
from kalpamani.data.curate.build import dataset_row_fingerprint
from kalpamani.data.curate.lineage import resolve_lineage
from kalpamani.data.curate.universe import membership_hash_of
from kalpamani.data.quality.plan import QualityPlan, plan_for
from kalpamani.data.quality.report import (
    QualityReport,
    decode_quality_report,
    encode_quality_report,
    report_file_hash,
)
from kalpamani.data.quality.runner import require_runner_produced
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
    "universe_snapshot_header",
)

#: Source datasets whose resolution evidence a publication must carry.
REQUIRED_EVIDENCE_DATASETS = (
    "corporate_action",
    "listing",
    "market_session",
    "price_bar",
    "security_attribute",
    "ticker_history",
)

#: Filename of the manifest whose arrival commits a version.
MANIFEST_NAME = "_dataset_manifest.json"

#: Filename of the quality report gating the version.
QUALITY_REPORT_NAME = "_quality_report.json"

#: Version of the publication format itself.
PUBLICATION_FORMAT_VERSION = 3


@dataclass(frozen=True, slots=True, kw_only=True)
class TableRecord:
    """One table inside a published version."""

    entity: str
    relative_path: str
    row_count: int
    content_hash: str


@dataclass(frozen=True, slots=True, kw_only=True)
class DatasetManifest:
    """What a published version claims about itself. Verified on every read.

    ``manifest_hash`` covers **everything below it** -- the format version, the
    identity, the coverage, both profiles, the global resolution, the complete
    resolution map and evidence, the receipt and quality-report identities, every
    table record, the ingestion runs, the commit and the policy versions. Only
    the hash field itself is excluded. Two manifests differing in any of that
    cannot share a dataset identity.
    """

    publication_format_version: int
    dataset_version: str
    layer: StorageLayer
    build_time: datetime
    coverage_start: date
    coverage_end: date
    resolved_profile: InformationSetProfile
    requested_profile: InformationSetProfile
    global_profile_resolution: GlobalProfileResolution
    resolution_policy_version: str
    resolution_map: tuple[tuple[str, str, str], ...]
    resolution_evidence: tuple[DatasetResolutionEvidence, ...]
    resolution_receipt_hash: str
    quality_report_hash: str
    #: Hash of the exact persisted quality-report bytes. ``quality_report_hash``
    #: omits ``produced_at`` by design, so on its own it leaves those bytes
    #: unbound; this covers the file itself.
    quality_report_file_hash: str
    #: The versioned plan the report is evidence against. A publication naming a
    #: plan this code does not have refuses on read.
    quality_plan_version: str
    tables: tuple[TableRecord, ...]
    source_ingestion_run_ids: tuple[str, ...]
    code_commit_sha: str
    lag_policy_version: str
    universe_definition_version: str | None
    manifest_hash: str

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


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def _evidence_row(entry: DatasetResolutionEvidence) -> dict[str, object]:
    return {
        "dataset": entry.dataset,
        "policy": entry.policy.value,
        "rows_considered": entry.rows_considered,
        "public_rows_applicable": entry.public_rows_applicable,
        "public_basis": entry.public_basis.value,
        "public_exact_rows": entry.public_exact_rows,
        "public_bounded_rows": entry.public_bounded_rows,
        "public_excluded_rows": entry.public_excluded_rows,
        "public_unresolved_rows": entry.public_unresolved_rows,
        "provider_rows_applicable": entry.provider_rows_applicable,
        "provider_basis": entry.provider_basis.value,
        "provider_exact_rows": entry.provider_exact_rows,
        "provider_bounded_rows": entry.provider_bounded_rows,
        "provider_excluded_rows": entry.provider_excluded_rows,
        "provider_unresolved_rows": entry.provider_unresolved_rows,
        "excluded_rows": entry.excluded_rows,
        "reason": entry.reason,
    }


def _decode_evidence(row: Mapping[str, Any]) -> DatasetResolutionEvidence:
    return DatasetResolutionEvidence(
        dataset=str(row["dataset"]),
        policy=DatasetGapPolicy(str(row["policy"])),
        rows_considered=int(row["rows_considered"]),
        public_rows_applicable=int(row["public_rows_applicable"]),
        public_basis=TimingBasis(str(row["public_basis"])),
        public_exact_rows=int(row["public_exact_rows"]),
        public_bounded_rows=int(row["public_bounded_rows"]),
        public_excluded_rows=int(row["public_excluded_rows"]),
        public_unresolved_rows=int(row["public_unresolved_rows"]),
        provider_rows_applicable=int(row["provider_rows_applicable"]),
        provider_basis=TimingBasis(str(row["provider_basis"])),
        provider_exact_rows=int(row["provider_exact_rows"]),
        provider_bounded_rows=int(row["provider_bounded_rows"]),
        provider_excluded_rows=int(row["provider_excluded_rows"]),
        provider_unresolved_rows=int(row["provider_unresolved_rows"]),
        excluded_rows=int(row["excluded_rows"]),
        reason=str(row["reason"]),
    )


def _manifest_body(manifest: DatasetManifest, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "publication_format_version": manifest.publication_format_version,
        "dataset_version": manifest.dataset_version,
        "layer": manifest.layer.value,
        "build_time": manifest.build_time.isoformat(),
        "coverage_start": manifest.coverage_start.isoformat(),
        "coverage_end": manifest.coverage_end.isoformat(),
        "resolved_profile": manifest.resolved_profile.value,
        "requested_profile": manifest.requested_profile.value,
        "global_profile_resolution": manifest.global_profile_resolution.value,
        "resolution_policy_version": manifest.resolution_policy_version,
        "resolution_map": [list(entry) for entry in manifest.resolution_map],
        "resolution_evidence": [_evidence_row(e) for e in manifest.resolution_evidence],
        "resolution_receipt_hash": manifest.resolution_receipt_hash,
        "quality_report_hash": manifest.quality_report_hash,
        "quality_report_file_hash": manifest.quality_report_file_hash,
        "quality_plan_version": manifest.quality_plan_version,
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
    }
    if include_hash:
        body["manifest_hash"] = manifest.manifest_hash
    return body


def compute_manifest_hash(manifest: DatasetManifest) -> str:
    """Hash the whole manifest body, excluding only its own hash field."""
    return content_hash(_manifest_body(manifest, include_hash=False))


def _encode_header(header: UniverseSnapshotHeader) -> dict[str, object]:
    return {
        "session_date": header.session_date.isoformat(),
        "universe_definition_version": header.universe_definition_version,
        "resolved_profile": header.resolved_profile.value,
        "evaluation_cutoff": header.evaluation_cutoff.isoformat(),
        "row_count": header.row_count,
        "snapshot_content_hash": header.snapshot_content_hash,
        "derivation_spec_version": header.derivation_spec_version,
        "status": header.status,
        "required_domain_coverage": [
            list(entry) for entry in sorted(header.required_domain_coverage)
        ],
        "envelope": encode_derived_envelope(header.envelope),
        "header_identity_hash": header.header_identity_hash,
    }


def _decode_header(row: Mapping[str, Any]) -> UniverseSnapshotHeader:
    """Decode a snapshot header, refusing one that does not reproduce its identity.

    The identity covers the session, definition, profile, cutoff, status, row
    count, membership hashes and lineage. Recomputing it here is what stops a
    fabricated header from asserting that a session was built.
    """
    header = UniverseSnapshotHeader(
        session_date=date.fromisoformat(str(row["session_date"])),
        universe_definition_version=str(row["universe_definition_version"]),
        resolved_profile=InformationSetProfile(str(row["resolved_profile"])),
        evaluation_cutoff=datetime.fromisoformat(str(row["evaluation_cutoff"])),
        row_count=int(row["row_count"]),
        snapshot_content_hash=str(row["snapshot_content_hash"]),
        derivation_spec_version=str(row["derivation_spec_version"]),
        envelope=decode_derived_envelope(row["envelope"]),
        required_domain_coverage=tuple(
            (str(entry[0]), int(entry[1]), int(entry[2]))
            for entry in row.get("required_domain_coverage", [])
        ),
        status=str(row["status"]),
    )
    recorded = str(row["header_identity_hash"])
    if header.header_identity_hash != recorded:
        raise DatasetPublicationError(
            f"The snapshot header for {header.session_date.isoformat()} does not reproduce its "
            f"identity (recorded {recorded}, recomputed {header.header_identity_hash}). A "
            "header is the only evidence that a session was built at all, so one that can be "
            "edited afterwards is evidence of nothing."
        )
    return header


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
        "universe_snapshot_header": [
            _encode_header(header) for header in dataset.universe_headers.values()
        ],
    }


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------


def publish_gold_dataset(
    store: LocalTableStore,
    dataset: GoldDataset,
    *,
    quality_report: QualityReport,
    quality_plan: QualityPlan,
    code_commit_sha: str,
    lag_policy_version: str,
    universe_definition_version: str | None,
    source_ingestion_run_ids: Sequence[str] = (),
) -> tuple[DatasetVersion, DatasetManifest]:
    """Verify, stage, then commit a version with one atomic rename.

    Raises:
        BuildBoundaryError: if the dataset's receipt does not account for its
            rows, its evidence, its policy map or its policy version.
        QualityGateError: if a BLOCKING finding stands against the build, the
            report does not close against ``quality_plan``, or the report was not
            produced by the quality runner. A checks_run list a caller wrote is a
            claim about work rather than a product of it.
        DatasetPublicationError: if the version is already published, or a
            required source dataset has no resolution evidence.
    """
    safe_relative_path(dataset.dataset_version, kind="dataset_version")
    for run_id in source_ingestion_run_ids:
        safe_component(run_id, kind="ingestion_run_id")

    _verify_receipt_covers_rows(dataset)
    _verify_evidence_complete(dataset)
    # Plan first, provenance second. A report that fails the plan should fail
    # for the reason it is wrong, not for where it came from.
    quality_plan.validate(quality_report, published_tables=GOLD_ENTITIES)
    require_runner_produced(quality_report, dataset_version=dataset.dataset_version)
    quality_report.require_publishable(dataset_version=dataset.dataset_version)

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
        artifact = store.write_staged_table(
            layer=StorageLayer.GOLD,
            dataset_version=dataset.dataset_version,
            entity=entity,
            rows=encoded[entity],
        )
        tables.append(
            TableRecord(
                entity=entity,
                relative_path=artifact.path.name,
                row_count=artifact.row_count,
                content_hash=artifact.content_hash,
            )
        )

    manifest = _with_hash(
        DatasetManifest(
            publication_format_version=PUBLICATION_FORMAT_VERSION,
            dataset_version=dataset.dataset_version,
            layer=StorageLayer.GOLD,
            build_time=normalize_instant(dataset.build_time),
            coverage_start=dataset.coverage_start,
            coverage_end=dataset.coverage_end,
            resolved_profile=dataset.resolved_profile,
            requested_profile=dataset.resolution_receipt.requested_profile,
            global_profile_resolution=dataset.resolution_receipt.global_profile_resolution,
            resolution_policy_version=dataset.resolution_policy_version,
            resolution_map=dataset.resolution_receipt.canonical_map,
            resolution_evidence=dataset.resolution_evidence,
            resolution_receipt_hash=dataset.resolution_receipt.receipt_hash,
            quality_report_hash=quality_report.report_hash,
            quality_report_file_hash=report_file_hash(quality_report),
            quality_plan_version=quality_plan.plan_version,
            tables=tuple(tables),
            source_ingestion_run_ids=tuple(sorted(source_ingestion_run_ids)),
            code_commit_sha=code_commit_sha,
            lag_policy_version=lag_policy_version,
            universe_definition_version=universe_definition_version,
            manifest_hash="",
        )
    )

    store.write_staged_bytes(
        layer=StorageLayer.GOLD,
        dataset_version=dataset.dataset_version,
        name=QUALITY_REPORT_NAME,
        payload=canonical_bytes(encode_quality_report(quality_report)),
    )
    store.write_staged_bytes(
        layer=StorageLayer.GOLD,
        dataset_version=dataset.dataset_version,
        name=MANIFEST_NAME,
        payload=canonical_bytes(_manifest_body(manifest, include_hash=True)),
    )
    store.commit_version(layer=StorageLayer.GOLD, dataset_version=dataset.dataset_version)

    version = DatasetVersion(
        dataset_version=dataset.dataset_version,
        layer=StorageLayer.GOLD,
        built_at=dataset.build_time,
        built_from_run_ids=manifest.source_ingestion_run_ids,
        code_commit_sha=code_commit_sha,
        content_hash=manifest.manifest_hash,
        lag_policy_version=lag_policy_version,
        resolved_profile=dataset.resolved_profile,
        resolution_policy_version=dataset.resolution_policy_version,
        universe_definition_version=universe_definition_version,
    )
    return version, manifest


def _with_hash(draft: DatasetManifest) -> DatasetManifest:
    digest = compute_manifest_hash(draft)
    return DatasetManifest(
        publication_format_version=draft.publication_format_version,
        dataset_version=draft.dataset_version,
        layer=draft.layer,
        build_time=draft.build_time,
        coverage_start=draft.coverage_start,
        coverage_end=draft.coverage_end,
        resolved_profile=draft.resolved_profile,
        requested_profile=draft.requested_profile,
        global_profile_resolution=draft.global_profile_resolution,
        resolution_policy_version=draft.resolution_policy_version,
        resolution_map=draft.resolution_map,
        resolution_evidence=draft.resolution_evidence,
        resolution_receipt_hash=draft.resolution_receipt_hash,
        quality_report_hash=draft.quality_report_hash,
        quality_report_file_hash=draft.quality_report_file_hash,
        quality_plan_version=draft.quality_plan_version,
        tables=draft.tables,
        source_ingestion_run_ids=draft.source_ingestion_run_ids,
        code_commit_sha=draft.code_commit_sha,
        lag_policy_version=draft.lag_policy_version,
        universe_definition_version=draft.universe_definition_version,
        manifest_hash=digest,
    )


def _verify_receipt_covers_rows(dataset: GoldDataset) -> None:
    """The receipt must be about *these* rows, not about a policy in the abstract.

    Four things are compared, not one: the content-bound row fingerprint, the
    evidence fingerprint, the policy version, and the evidence's agreement with
    the canonical map it was produced under -- dataset by dataset, policy and
    stated reason alike. A build that satisfies three of the four has one
    statement in it that is false, and nothing downstream could say which.
    """
    problems = dataset.resolution_receipt.disagreements_with(
        evidence=dataset.resolution_evidence,
        row_fingerprint=dataset_row_fingerprint(dataset),
        resolution_policy_version=dataset.resolution_policy_version,
    )
    if dataset.resolution_receipt.resolved_profile is not dataset.resolved_profile:
        problems.append(
            f"the build claims {dataset.resolved_profile.value} while its receipt records "
            f"{dataset.resolution_receipt.resolved_profile.value}"
        )
    if problems:
        raise BuildBoundaryError(
            f"The resolution receipt for {dataset.dataset_version} does not describe this "
            "build:\n  - "
            + "\n  - ".join(problems)
            + "\nA row substituted after resolution was never resolved, and publishing "
            "it would record a policy that never saw it."
        )


def _verify_evidence_complete(dataset: GoldDataset) -> None:
    evidenced = {entry.dataset for entry in dataset.resolution_evidence}
    missing = sorted(set(REQUIRED_EVIDENCE_DATASETS) - evidenced)
    if missing:
        raise DatasetPublicationError(
            f"{dataset.dataset_version} has no resolution evidence for {missing}. The evidence "
            "is a complete inventory of direct source reads, not a list of the problematic "
            "ones."
        )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


#: Held by the verified read path alone. ``VerifiedPublication`` refuses to be
#: constructed without it, so the class cannot be instantiated from a triplet
#: assembled at a call site -- which is exactly what the reader used to accept.
_VERIFIED_READ_TOKEN: Final = object()


def verification_seal(
    manifest: DatasetManifest,
    report: QualityReport,
    receipt: ResolutionReceipt,
) -> str:
    """The seal a verified read stamps onto a publication.

    Binds the three identities that were checked -- the manifest, the quality
    evidence and the recomputed receipt -- so that a publication carrying a seal
    names precisely which artifacts the verification passed over.
    """
    return content_hash(
        {
            "publication_format_version": manifest.publication_format_version,
            "dataset_version": manifest.dataset_version,
            "manifest_hash": manifest.manifest_hash,
            "quality_report_hash": report.report_hash,
            "quality_report_file_hash": manifest.quality_report_file_hash,
            "resolution_receipt_hash": receipt.receipt_hash,
        }
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifiedPublication:
    """A published dataset that **this process** verified, with its evidence.

    The three artifacts used to travel as a tuple, which meant the point-in-time
    reader could not tell a verified read from three objects assembled at a call
    site. It checked what it could -- that the manifest named the dataset, that
    the report hash matched -- and those checks pass for a hand-built triplet,
    because they compare the pieces to each other rather than to storage.

    This type carries the fact of verification itself. Only
    :func:`read_published_dataset` holds the token that constructs it, and the
    seal records which manifest, report and receipt the verification covered.
    """

    dataset: GoldDataset
    manifest: DatasetManifest
    quality_report: QualityReport
    verification_seal: str
    verified_by: object

    def __post_init__(self) -> None:
        if self.verified_by is not _VERIFIED_READ_TOKEN:
            raise DatasetPublicationError(
                "A VerifiedPublication may only be produced by read_published_dataset. A "
                "dataset, a manifest and a report assembled at a call site have not been "
                "checked against storage -- their hashes agree with each other, which is not "
                "the same as agreeing with what was published."
            )
        expected = verification_seal(
            self.manifest, self.quality_report, self.dataset.resolution_receipt
        )
        if self.verification_seal != expected:
            raise DatasetPublicationError(
                f"The verification seal on {self.manifest.dataset_version} does not describe "
                "the artifacts it is attached to. A seal that names other artifacts is not "
                "evidence about these."
            )

    @property
    def dataset_version(self) -> str:
        """The version this publication serves."""
        return self.manifest.dataset_version


def load_dataset_manifest(store: LocalTableStore, *, dataset_version: str) -> DatasetManifest:
    """Load a published version's manifest, refusing anything unpublished.

    Raises:
        DatasetPublicationError: if the version is absent, the manifest is
            missing, or the manifest body does not reconcile with its own hash.
    """
    safe_relative_path(dataset_version, kind="dataset_version")
    root = store.version_root(layer=StorageLayer.GOLD, dataset_version=dataset_version)
    path = root / MANIFEST_NAME
    if not path.exists():
        raise DatasetPublicationError(
            f"Gold version {dataset_version} has no published manifest at {path}. Publication "
            "is committed by an atomic rename, so an absent manifest means the version was "
            "never committed -- not that it is incomplete."
        )
    body = store.read_json(path)
    manifest = DatasetManifest(
        publication_format_version=int(body["publication_format_version"]),
        dataset_version=str(body["dataset_version"]),
        layer=StorageLayer(str(body["layer"])),
        build_time=datetime.fromisoformat(str(body["build_time"])),
        coverage_start=date.fromisoformat(str(body["coverage_start"])),
        coverage_end=date.fromisoformat(str(body["coverage_end"])),
        resolved_profile=InformationSetProfile(str(body["resolved_profile"])),
        requested_profile=InformationSetProfile(str(body["requested_profile"])),
        global_profile_resolution=GlobalProfileResolution(str(body["global_profile_resolution"])),
        resolution_policy_version=str(body["resolution_policy_version"]),
        resolution_map=tuple(
            (str(entry[0]), str(entry[1]), str(entry[2])) for entry in body["resolution_map"]
        ),
        resolution_evidence=tuple(
            _decode_evidence(row) for row in list(body["resolution_evidence"])
        ),
        resolution_receipt_hash=str(body["resolution_receipt_hash"]),
        quality_report_hash=str(body["quality_report_hash"]),
        quality_report_file_hash=str(body["quality_report_file_hash"]),
        quality_plan_version=str(body["quality_plan_version"]),
        tables=tuple(
            TableRecord(
                entity=str(row["entity"]),
                relative_path=str(row["relative_path"]),
                row_count=int(row["row_count"]),
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
        manifest_hash=str(body["manifest_hash"]),
    )
    recomputed = compute_manifest_hash(manifest)
    if recomputed != manifest.manifest_hash:
        raise DatasetPublicationError(
            f"Gold version {dataset_version} has a manifest that does not reconcile with its "
            f"own hash (recorded {manifest.manifest_hash}, recomputed {recomputed}). A "
            "manifest that can be edited after publication is not evidence of anything."
        )
    return manifest


def load_quality_report(store: LocalTableStore, manifest: DatasetManifest) -> QualityReport:
    """Load and verify the quality evidence a published version was gated on.

    Both hashes are checked. ``report_hash`` proves the findings did not change;
    it deliberately omits ``produced_at``, so on its own it leaves those bytes
    editable. ``quality_report_file_hash`` covers the file exactly as written.

    Raises:
        QualityGateError: if the report is absent, does not reconcile with its
            own hash, is not the report the manifest names, or is not the file
            the manifest names. A missing report is not a clean one.
    """
    root = store.version_root(layer=StorageLayer.GOLD, dataset_version=manifest.dataset_version)
    path = root / QUALITY_REPORT_NAME
    if not path.exists():
        raise QualityGateError(
            f"Gold version {manifest.dataset_version} has no persisted quality report at "
            f"{path}. A publication with no quality evidence cannot be read: absence of a "
            "finding and absence of a check are different claims."
        )
    stored_bytes = path.read_bytes()
    file_digest = sha256_hex(stored_bytes)
    if file_digest != manifest.quality_report_file_hash:
        raise QualityGateError(
            f"The quality report file stored with {manifest.dataset_version} hashes to "
            f"{file_digest}, not the {manifest.quality_report_file_hash} its manifest records. "
            "The logical report hash omits produced_at by design, so only this covers the "
            "bytes -- and a file that can be edited after the gate is not a gate."
        )
    report = decode_quality_report(store.read_json(path))
    if report.report_hash != manifest.quality_report_hash:
        raise QualityGateError(
            f"The quality report stored with {manifest.dataset_version} is not the one its "
            f"manifest names (manifest {manifest.quality_report_hash}, stored "
            f"{report.report_hash}). Swapping the evidence after the gate is the failure the "
            "binding exists to prevent."
        )
    return report


def read_published_dataset(
    store: LocalTableStore,
    *,
    dataset_version: str,
    config: ProfileResolutionConfig,
    approvals: BoundApprovals,
) -> VerifiedPublication:
    """Load a published version, verifying everything before decoding anything.

    This is the **only** route to a :class:`VerifiedPublication`, and therefore
    the only route to a point-in-time reader. A caller that has the data has the
    evidence, cannot obtain one without the other, and cannot assemble the pair
    at a call site.

    Raises:
        DatasetPublicationError: on a missing or partial publication, a table
            whose bytes or row count disagree with the manifest, an incoherent
            manifest, a resolution that disagrees with ``config``, a snapshot
            header that does not reproduce its identity, or a receipt that does
            not recompute from the rows that were stored.
        QualityGateError: if the quality evidence is missing, mismatched, does
            not close against the plan the manifest names, or carries an open
            BLOCKING finding.
        ArtifactIntegrityError: if a stored membership row's lineage does not
            replay to exactly the rows it names.
    """
    manifest = load_dataset_manifest(store, dataset_version=dataset_version)
    _verify_manifest_coherence(manifest)
    _verify_resolution_agrees(manifest, config)
    report = load_quality_report(store, manifest)
    plan_for(manifest.quality_plan_version).validate(report, published_tables=GOLD_ENTITIES)
    _verify_quality_gate(manifest, report)
    _verify_tables(store, manifest)

    def rows(entity: str) -> Sequence[Mapping[str, Any]]:
        return store.read_table(
            layer=StorageLayer.GOLD, dataset_version=dataset_version, entity=entity
        )

    sessions = tuple(decode_market_session(r) for r in rows("market_session"))
    listings = tuple(decode_listing(r) for r in rows("listing"))
    attributes = tuple(decode_security_attribute(r) for r in rows("security_attribute"))
    tickers = tuple(decode_ticker_history(r) for r in rows("ticker_history"))
    bars = tuple(decode_price_bar(r) for r in rows("price_bar"))
    actions = tuple(decode_corporate_action(r) for r in rows("corporate_action"))
    headers = {
        header.session_date: header
        for header in (_decode_header(r) for r in rows("universe_snapshot_header"))
    }

    universe: dict[date, list[UniverseMembership]] = {session: [] for session in headers}
    for row in rows("universe_membership"):
        stored = decode_universe_membership(row, ())
        replayed = resolve_lineage(
            stored.envelope.lineage,
            listings=listings,
            attributes=attributes,
            bars=bars,
            resolved_profile=manifest.resolved_profile,
            approvals=approvals,
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

    stored_universe = {
        session: tuple(sorted(members, key=lambda m: m.security_id))
        for session, members in sorted(universe.items())
    }
    _verify_snapshot_headers(
        headers,
        stored_universe,
        manifest,
        listings=listings,
        attributes=attributes,
        bars=bars,
        approvals=approvals,
    )

    source_rows: list[SourceRecord] = [
        *sessions,
        *listings,
        *attributes,
        *tickers,
        *bars,
        *actions,
    ]
    receipt = _recompute_receipt(manifest, source_rows)

    built = GoldDataset(
        dataset_version=manifest.dataset_version,
        build_time=manifest.build_time,
        coverage_start=manifest.coverage_start,
        coverage_end=manifest.coverage_end,
        resolved_profile=manifest.resolved_profile,
        resolution_policy_version=manifest.resolution_policy_version,
        resolution_receipt=receipt,
        resolution_evidence=manifest.resolution_evidence,
        sessions=sessions,
        listings=listings,
        attributes=attributes,
        tickers=tickers,
        bars=bars,
        actions=actions,
        universe=stored_universe,
        universe_headers=headers,
    )
    return VerifiedPublication(
        dataset=built,
        manifest=manifest,
        quality_report=report,
        verification_seal=verification_seal(manifest, report, receipt),
        verified_by=_VERIFIED_READ_TOKEN,
    )


def _recompute_receipt(
    manifest: DatasetManifest,
    source_rows: Sequence[SourceRecord],
) -> ResolutionReceipt:
    """Rebuild the **complete** receipt from what was persisted, and check its hash.

    Every part comes from evidence that survived the round trip: both profiles,
    the global resolution and the canonical map from the manifest; the evidence
    fingerprint from the persisted evidence; the row fingerprint from the rows
    just decoded, contents included.

    The earlier version filled the fingerprints with empty tuples, which meant
    the reconstruction agreed with the recorded hash only when the recorded hash
    had also been taken over empty tuples -- a check that could not fail. This
    one fails on a substituted row, a substituted evidence entry and a
    substituted map alike.

    Raises:
        DatasetPublicationError: if the recomputed receipt hash is not the one
            the manifest records.
    """
    receipt = ResolutionReceipt(
        requested_profile=manifest.requested_profile,
        resolved_profile=manifest.resolved_profile,
        global_profile_resolution=manifest.global_profile_resolution,
        resolution_policy_version=manifest.resolution_policy_version,
        canonical_map=manifest.resolution_map,
        evidence_fingerprint=evidence_fingerprint(manifest.resolution_evidence),
        row_fingerprint=row_fingerprint(source_rows),
    )
    if receipt.receipt_hash != manifest.resolution_receipt_hash:
        raise DatasetPublicationError(
            f"Gold version {manifest.dataset_version} does not recompute its resolution "
            f"receipt (manifest {manifest.resolution_receipt_hash}, recomputed "
            f"{receipt.receipt_hash}). The receipt is recomputed from the rows that were "
            "actually stored, so a row substituted after publication -- including one that "
            "kept its identifier and changed only a price or an availability time -- fails "
            "here rather than being served."
        )
    return receipt


def _verify_manifest_coherence(manifest: DatasetManifest) -> None:
    problems: list[str] = []
    if manifest.publication_format_version != PUBLICATION_FORMAT_VERSION:
        problems.append(
            f"publication format {manifest.publication_format_version} is not the "
            f"{PUBLICATION_FORMAT_VERSION} this reader understands"
        )
    if manifest.coverage_start > manifest.coverage_end:
        problems.append(
            f"coverage {manifest.coverage_start.isoformat()}.."
            f"{manifest.coverage_end.isoformat()} is inverted"
        )
    if not is_canonical_instant(manifest.build_time):
        problems.append("build_time is not a canonical UTC instant")

    entities = [table.entity for table in manifest.tables]
    if len(set(entities)) != len(entities):
        problems.append("two table records name the same entity")
    if set(entities) != set(GOLD_ENTITIES):
        problems.append(
            f"declares tables {sorted(set(entities))}; a complete publication declares "
            f"{sorted(GOLD_ENTITIES)}"
        )
    for table in manifest.tables:
        safe_component(table.relative_path, kind="table relative_path")
        if table.relative_path != f"{table.entity}.jsonl":
            problems.append(
                f"table {table.entity!r} declares path {table.relative_path!r}, not the "
                "committed path its entity implies"
            )
        if table.row_count < 0:
            problems.append(f"table {table.entity!r} declares a negative row count")

    datasets = [entry.dataset for entry in manifest.resolution_evidence]
    if len(set(datasets)) != len(datasets):
        problems.append("two resolution-evidence entries name the same dataset")
    missing_evidence = sorted(set(REQUIRED_EVIDENCE_DATASETS) - set(datasets))
    if missing_evidence:
        problems.append(f"required source datasets {missing_evidence} have no resolution evidence")
    for entry in manifest.resolution_evidence:
        counts = (
            entry.rows_considered,
            entry.public_rows_applicable,
            entry.public_exact_rows,
            entry.public_bounded_rows,
            entry.public_excluded_rows,
            entry.public_unresolved_rows,
            entry.provider_rows_applicable,
            entry.provider_exact_rows,
            entry.provider_bounded_rows,
            entry.provider_excluded_rows,
            entry.provider_unresolved_rows,
            entry.excluded_rows,
        )
        if any(count < 0 for count in counts):
            problems.append(f"dataset {entry.dataset!r} declares a negative count")
        if not entry.public_axis_reconciles():
            problems.append(f"dataset {entry.dataset!r} public-axis counts do not reconcile")
        if not entry.provider_axis_reconciles():
            problems.append(f"dataset {entry.dataset!r} provider-axis counts do not reconcile")
        if entry.public_basis is TimingBasis.EXACT and entry.public_bounded_rows:
            problems.append(
                f"dataset {entry.dataset!r} claims EXACT public basis with bounded rows"
            )
        if entry.provider_basis is TimingBasis.EXACT and entry.provider_bounded_rows:
            problems.append(
                f"dataset {entry.dataset!r} claims EXACT provider basis with bounded rows"
            )
        if entry.public_basis is TimingBasis.EXACT and not entry.public_exact_rows:
            problems.append(
                f"dataset {entry.dataset!r} claims EXACT public basis with no exact rows; a "
                "basis derived from nothing describes nothing"
            )
        if entry.provider_basis is TimingBasis.EXACT and not entry.provider_exact_rows:
            problems.append(
                f"dataset {entry.dataset!r} claims EXACT provider basis with no exact rows; a "
                "basis derived from nothing describes nothing"
            )

    map_datasets = [entry[0] for entry in manifest.resolution_map]
    if len(set(map_datasets)) != len(map_datasets):
        problems.append("two resolution-map entries name the same dataset")

    if problems:
        raise DatasetPublicationError(
            f"Gold version {manifest.dataset_version} is incoherent:\n  - "
            + "\n  - ".join(problems)
        )


def _verify_resolution_agrees(manifest: DatasetManifest, config: ProfileResolutionConfig) -> None:
    """The persisted map must match the run's, entry for entry, reason included."""
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
            f"{config.resolution_policy_version!r}."
        )
    if manifest.resolution_map != config.canonical_map():
        published = {entry[0]: entry for entry in manifest.resolution_map}
        declared = {entry[0]: entry for entry in config.canonical_map()}
        extra = sorted(set(published) - set(declared))
        absent = sorted(set(declared) - set(published))
        differing = sorted(
            name for name in set(published) & set(declared) if published[name] != declared[name]
        )
        raise DatasetPublicationError(
            f"Gold version {manifest.dataset_version} was built under a different resolution "
            f"map than this run declares. Only in the publication: {extra}. Only in the run: "
            f"{absent}. Differing in policy or reason: {differing}. The whole map is compared, "
            "reasons included: two runs that bounded the same dataset for different stated "
            "reasons resolved it differently."
        )


def _verify_quality_gate(manifest: DatasetManifest, report: QualityReport) -> None:
    blocking = report.blocking
    if blocking:
        names = sorted({finding.check_name for finding in blocking})
        raise QualityGateError(
            f"Gold version {manifest.dataset_version} carries {len(blocking)} open BLOCKING "
            f"quality finding(s) ({names}). Every dependent result is refused, not annotated, "
            "and the evidence travels with the dataset so a reader cannot obtain a clean "
            "result by omitting it."
        )


def _verify_tables(store: LocalTableStore, manifest: DatasetManifest) -> None:
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
        payload = path.read_bytes()
        actual = sha256_hex(payload)
        if actual != table.content_hash:
            raise DatasetPublicationError(
                f"Table {table.entity!r} in {manifest.dataset_version} hashes to {actual}, "
                f"not the {table.content_hash} its manifest records. Verification happens "
                "before decoding, so corruption is caught as corruption."
            )
        observed = sum(1 for line in payload.decode("utf-8").splitlines() if line)
        if observed != table.row_count:
            raise DatasetPublicationError(
                f"Table {table.entity!r} in {manifest.dataset_version} holds {observed} rows "
                f"but declares {table.row_count}. A count that does not match what is there "
                "makes every completeness claim built on it unfalsifiable."
            )


def _verify_snapshot_headers(
    headers: Mapping[date, UniverseSnapshotHeader],
    universe: Mapping[date, Sequence[UniverseMembership]],
    manifest: DatasetManifest,
    *,
    listings: Sequence[Listing],
    attributes: Sequence[SecurityAttribute],
    bars: Sequence[PriceBar],
    approvals: BoundApprovals,
) -> None:
    """The snapshot is verified as one artifact, header and rows together.

    The header is the only thing asserting that a session was built, so it is held
    to the same standard as the rows it heads: its lineage must **replay**, its
    identity and content hash must recompute, its status must be COMPLETE, and
    every row under it must agree with it on the session, the definition version
    and the resolved profile.

    Rows are not filtered here, and that is deliberate. A snapshot is served whole
    or refused, so a row that disagrees with its header is a corrupt snapshot
    rather than a row to leave out.
    """
    orphaned = sorted(session for session in universe if session not in headers)
    if orphaned:
        raise DatasetPublicationError(
            f"Gold version {manifest.dataset_version} holds membership rows for sessions with "
            f"no snapshot header: {orphaned}. A header is what says the session was built, and "
            "rows without one cannot be distinguished from rows left behind by another build."
        )
    for session, header in sorted(headers.items()):
        rows = tuple(universe.get(session, ()))
        _verify_one_header(
            session,
            header,
            rows,
            manifest,
            listings=listings,
            attributes=attributes,
            bars=bars,
            approvals=approvals,
        )


def _verify_one_header(
    session: date,
    header: UniverseSnapshotHeader,
    rows: Sequence[UniverseMembership],
    manifest: DatasetManifest,
    *,
    listings: Sequence[Listing],
    attributes: Sequence[SecurityAttribute],
    bars: Sequence[PriceBar],
    approvals: BoundApprovals,
) -> None:
    if not header.is_complete:
        raise DatasetPublicationError(
            f"The snapshot header for {session.isoformat()} declares status "
            f"{header.status!r}. Only a COMPLETE snapshot is served: a partial one answers "
            "the universe question with a subset and nothing in the answer says so."
        )
    if header.row_count != len(rows):
        raise DatasetPublicationError(
            f"The snapshot header for {session.isoformat()} declares {header.row_count} "
            f"rows and {len(rows)} were stored. A zero-row snapshot is legitimate; a "
            "header that miscounts is not."
        )
    recomputed = content_hash(sorted(membership_hash_of(row) for row in rows))
    if recomputed != header.snapshot_content_hash:
        raise DatasetPublicationError(
            f"The snapshot header for {session.isoformat()} records content hash "
            f"{header.snapshot_content_hash} and its stored rows hash to {recomputed}. "
            "The membership changed after the header was written, or the header describes "
            "a different snapshot."
        )
    if header.envelope.dataset_version != manifest.dataset_version:
        raise DatasetPublicationError(
            f"The snapshot header for {session.isoformat()} is stamped with dataset "
            f"version {header.envelope.dataset_version!r} inside publication "
            f"{manifest.dataset_version!r}. A header copied from another build describes "
            "that build."
        )
    if header.envelope.artifact_first_built_time > manifest.build_time:
        raise DatasetPublicationError(
            f"The snapshot header for {session.isoformat()} claims it was first built at "
            f"{header.envelope.artifact_first_built_time.isoformat()}, after the build "
            f"itself at {manifest.build_time.isoformat()}."
        )
    if header.resolved_profile is not manifest.resolved_profile:
        raise DatasetPublicationError(
            f"The snapshot header for {session.isoformat()} is keyed to "
            f"{header.resolved_profile.value} while the build resolved to "
            f"{manifest.resolved_profile.value}."
        )

    # The header's own lineage replays, under the profile the build resolved to.
    # Without this the considered-listing evidence would be a list nobody checked.
    resolve_lineage(
        header.envelope.lineage,
        listings=listings,
        attributes=attributes,
        bars=bars,
        resolved_profile=manifest.resolved_profile,
        approvals=approvals,
    )

    for row in rows:
        if row.session_date != header.session_date:
            raise DatasetPublicationError(
                f"A membership row for {row.security_id} is dated "
                f"{row.session_date.isoformat()} under the header for {session.isoformat()}. "
                "A snapshot is one session's decisions."
            )
        if row.universe_definition_version != header.universe_definition_version:
            raise DatasetPublicationError(
                f"The membership row for {row.security_id} on {session.isoformat()} is keyed "
                f"to universe definition {row.universe_definition_version!r} and its header "
                f"declares {header.universe_definition_version!r}. Changing the rule creates "
                "a new version; it does not retroactively change history."
            )
        if row.resolved_profile is not header.resolved_profile:
            raise DatasetPublicationError(
                f"The membership row for {row.security_id} on {session.isoformat()} is keyed "
                f"to {row.resolved_profile.value} and its header to "
                f"{header.resolved_profile.value}. Eligibility is evaluated on admissible "
                "data, so membership is profile-specific."
            )


__all__ = [
    "GOLD_ENTITIES",
    "MANIFEST_NAME",
    "PUBLICATION_FORMAT_VERSION",
    "QUALITY_REPORT_NAME",
    "REQUIRED_EVIDENCE_DATASETS",
    "DatasetManifest",
    "TableRecord",
    "VerifiedPublication",
    "compute_manifest_hash",
    "load_dataset_manifest",
    "load_quality_report",
    "publish_gold_dataset",
    "read_published_dataset",
    "verification_seal",
]
