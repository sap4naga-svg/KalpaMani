"""Build manifests and immutable publication of Silver, Gold and the manifest -- ADR-0035 §3.8.

**The manifest is bound to what was actually consumed and produced.** It names the
delivered build-input bytes (the ledger digest and every payload and record digest the
validated locators named), the exact source versions (the compiled source-schema
version and every observed schema digest), every transformation and configuration
version (Silver normalization, universe rule and its parameters, adjustment policy and
convention, resolution policy, calendar, quality plan, evidence set, the commit and the
configuration digest), the resolved profile and ``as_of``, the per-dataset resolution
and served maps, the census, the quality report, the limitations, and the digest and
disposition of every output. Its derived ``run_id`` covers everything except the build
identity, so **identical inputs under a pinned configuration yield identical Silver and
Gold bytes and an identical ``run_id``**, and a differing rebuild is a defect.

**Publication is conditional, immutable and ordered.** Silver artifacts, then Gold
artifacts, each under a content-addressed name in the accepted licensed namespaces
(``silver/*``, ``gold/*``); a 412 on a content-addressed name is ``ALREADY_PRESENT`` --
a byte-identical rebuild -- and never a conflict. The manifest goes **last**, under the
build identity's name in ``manifests/*``, and **only after every artifact write has a
confirmed disposition**. A 412 on the manifest name is ``MANIFEST_NAME_OCCUPIED``: the
identity is spent and nothing is adopted. A definitive backend refusal halts with the
state known; an ambiguous one halts with ``publication_state_unknown`` and no manifest,
so a partial or uncertain publication is preserved as exactly that and never reported
as success. Nothing is read back, retried, resumed or deleted.

**Manifests stay LICENSED while CONTROL is deferred** (ADR-0036 §2.3): they carry no
vendor row, but the build actor holds no CONTROL grant, and no CONTROL write exists here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.errors import ObjectStoreBackendError
from kalpamani.data.contracts.vocabulary import DataClassification, ObjectStoreFailure
from kalpamani.data.ingest.sharadar.datasets import PROVIDER
from kalpamani.data.objectstore import ObjectKey
from kalpamani.data.production.sharadar.availability import (
    ACTION_SELECTION_VERSION,
    RESOLVED_PROFILE,
    AvailabilityEvidence,
    ResolvedLayer,
)
from kalpamani.data.production.sharadar.build_inputs import VerifiedBuildInputs
from kalpamani.data.production.sharadar.gold import (
    ADJUSTMENT_CONVENTION,
    ADJUSTMENT_DERIVATION_VERSION,
    ADJUSTMENT_POLICY,
    DEFAULT_JUMP_RATIO,
    DEFAULT_RECONCILIATION_TOLERANCE,
    GoldArtifact,
    GoldLayer,
)
from kalpamani.data.production.sharadar.keys import RUN_ID_RE
from kalpamani.data.production.sharadar.locator import PayloadDisposition
from kalpamani.data.production.sharadar.processing import SOURCE_SCHEMA_VERSION
from kalpamani.data.production.sharadar.sessions import SessionCalendar
from kalpamani.data.production.sharadar.silver import (
    SILVER_NORMALIZATION_VERSION,
    AcceptedSchemas,
    SilverLayer,
)
from kalpamani.data.production.sharadar.universe import UniverseRule, UniverseSnapshot
from kalpamani.data.qualify.sharadar.publication import (
    LicensedWriteOnlyPublisher,
    NameOccupiedError,
)

MANIFEST_SCHEMA_VERSION: Final = "kalpamani-production-build-manifest/v1"
MAX_MANIFEST_BYTES: Final = 4 * 1024 * 1024

SILVER_NAMESPACE: Final = "silver"
GOLD_NAMESPACE: Final = "gold"
MANIFESTS_NAMESPACE: Final = "manifests"
BUILDS_SEGMENT: Final = "builds"
OBJECTS_SEGMENT: Final = "objects"
DIGEST_SEGMENT: Final = "sha256"

#: Backend categories under which a conditional write is definitively not done.
_DEFINITIVE_REFUSALS: Final[frozenset[ObjectStoreFailure]] = frozenset(
    {
        ObjectStoreFailure.ACCESS_DENIED,
        ObjectStoreFailure.NOT_FOUND,
        ObjectStoreFailure.INVALID_CONFIGURATION,
    }
)


class BuildConfigurationError(ValueError):
    """A configuration that cannot pin a build."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildConfiguration:
    """Everything a build is pinned to. Digested into the manifest and the ``run_id``."""

    schemas: AcceptedSchemas
    calendar: SessionCalendar
    evidence: AvailabilityEvidence
    rule: UniverseRule
    decision_sessions: tuple[date, ...]
    as_of: datetime
    commit: str
    jump_ratio: Decimal = DEFAULT_JUMP_RATIO
    reconciliation_tolerance: Decimal = DEFAULT_RECONCILIATION_TOLERANCE

    def __post_init__(self) -> None:
        if type(self.as_of) is not datetime or self.as_of.tzinfo is None:
            raise BuildConfigurationError("as_of must be an aware datetime")
        if (
            type(self.commit) is not str
            or len(self.commit) != 40
            or any(c not in "0123456789abcdef" for c in self.commit)
        ):
            raise BuildConfigurationError("commit must be 40 lowercase hex characters")
        if list(self.decision_sessions) != sorted(set(self.decision_sessions)):
            raise BuildConfigurationError("decision sessions are distinct and ascending")

    def document(self) -> dict[str, Any]:
        """The closed configuration document. Everything that pins a build."""
        return {
            "accepted_schemas": {
                "version": self.schemas.version,
                "digests": {
                    dataset: sorted(digests)
                    for dataset, digests in sorted(self.schemas.digests.items())
                },
            },
            "calendar": {
                "version": self.calendar.version,
                "sessions": [
                    {"session_date": s.session_date.isoformat(), "open_at": s.open_at.isoformat()}
                    for s in self.calendar.sessions
                ],
            },
            "evidence": {
                "version": self.evidence.version,
                "items": [
                    {
                        "kind": item.kind.value,
                        "dataset": item.dataset,
                        "row_key": list(item.row_key),
                        "content_sha256": item.content_sha256,
                        "instant": None if item.instant is None else item.instant.isoformat(),
                        "evidence_digest": item.evidence_digest,
                    }
                    for item in self.evidence.items
                ],
            },
            "universe_rule": self.rule.document(),
            "decision_sessions": [d.isoformat() for d in self.decision_sessions],
            "as_of": self.as_of.isoformat(),
            "commit": self.commit,
            "jump_ratio": str(self.jump_ratio),
            "reconciliation_tolerance": str(self.reconciliation_tolerance),
            "adjustment_policy": ADJUSTMENT_POLICY.value,
            "adjustment_convention": ADJUSTMENT_CONVENTION.value,
            "adjustment_derivation_version": ADJUSTMENT_DERIVATION_VERSION,
            "action_selection_version": ACTION_SELECTION_VERSION,
            "silver_normalization_version": SILVER_NORMALIZATION_VERSION,
            "source_schema_version": SOURCE_SCHEMA_VERSION,
        }

    @property
    def digest(self) -> str:
        """SHA-256 over the canonical configuration document."""
        return sha256_hex(canonical_bytes(self.document()))


class ManifestDisposition(StrEnum):
    """What happened to the manifest write. Closed."""

    PUBLISHED = "PUBLISHED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    NAME_OCCUPIED = "NAME_OCCUPIED"
    REFUSED = "REFUSED"
    STATE_UNKNOWN = "STATE_UNKNOWN"


class PublicationHalt(StrEnum):
    """Why artifact publication stopped short. Closed."""

    PUBLICATION_REFUSED = "PUBLICATION_REFUSED"
    PUBLICATION_STATE_UNKNOWN = "PUBLICATION_STATE_UNKNOWN"
    PUBLICATION_CONFLICT = "PUBLICATION_CONFLICT"
    DEADLINE_EXHAUSTED = "DEADLINE_EXHAUSTED"
    MANIFEST_TOO_LARGE = "MANIFEST_TOO_LARGE"


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishedArtifact:
    """One artifact's confirmed disposition under its exact name."""

    artifact: GoldArtifact
    logical_key: str
    disposition: PayloadDisposition

    def document(self) -> dict[str, Any]:
        """The manifest's output entry."""
        return {
            "artifact": self.artifact.name,
            "key": self.logical_key,
            "sha256": self.artifact.sha256,
            "bytes": len(self.artifact.content),
            "rows": self.artifact.row_count,
            "disposition": self.disposition.value,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicationResult:
    """Every confirmed artifact disposition, the halt if any, and the manifest's fate."""

    artifacts: tuple[PublishedArtifact, ...]
    halt: PublicationHalt | None
    publication_state_unknown: bool
    manifest: ManifestDisposition
    manifest_sha256: str | None
    run_id: str | None

    def __post_init__(self) -> None:
        if self.manifest is ManifestDisposition.PUBLISHED and (
            self.halt is not None or self.publication_state_unknown
        ):
            raise ValueError("a manifest is published only after every write is confirmed")
        if (
            self.manifest is ManifestDisposition.STATE_UNKNOWN
            and not self.publication_state_unknown
        ):
            raise ValueError("an uncertain manifest write is uncertain publication state")

    def __repr__(self) -> str:
        """Counts and dispositions only."""
        return (
            f"PublicationResult(artifacts={len(self.artifacts)}, halt={self.halt}, "
            f"manifest={self.manifest.value!r})"
        )


class _HaltError(Exception):
    def __init__(self, halt: PublicationHalt, *, state_unknown: bool = False) -> None:
        super().__init__(halt.value)
        self.halt = halt
        self.state_unknown = state_unknown


def artifact_key(artifact: GoldArtifact) -> ObjectKey:
    """The content-addressed licensed name of one Silver or Gold artifact."""
    namespace = SILVER_NAMESPACE if artifact.name.startswith("silver-") else GOLD_NAMESPACE
    kind = artifact.name.split("-", 1)[1]
    return ObjectKey.licensed(
        namespace,
        PROVIDER,
        kind,
        OBJECTS_SEGMENT,
        DIGEST_SEGMENT,
        artifact.sha256,
        payload=artifact.content,
    )


def manifest_key(*, build_id: str, payload: bytes) -> ObjectKey:
    """The name-addressed licensed manifest key: one per build identity."""
    if type(build_id) is not str or not RUN_ID_RE.match(build_id):
        raise BuildConfigurationError("a build identity names a manifest")
    return ObjectKey.licensed(
        MANIFESTS_NAMESPACE, PROVIDER, BUILDS_SEGMENT, build_id + ".json", payload=payload
    )


def derive_run_id(
    *,
    inputs: VerifiedBuildInputs,
    silver: SilverLayer,
    resolved: ResolvedLayer,
    gold: GoldLayer,
    configuration: BuildConfiguration,
) -> str:
    """The reproducibility identity: everything but the build identity and the instant."""
    document = {
        "bronze_digests": sorted(page.payload_sha256 for page in inputs.pages()),
        "ledger_digest": inputs.ledger_digest,
        "silver_normalization_version": SILVER_NORMALIZATION_VERSION,
        "adjustment_derivation_version": ADJUSTMENT_DERIVATION_VERSION,
        "action_selection_version": ACTION_SELECTION_VERSION,
        "resolution_policy_version": resolved.policy_version,
        "pagination_policy_version": silver.pagination.policy_version,
        "schema_digests": {
            dataset: list(silver.by_dataset(dataset).schema_digests)
            for dataset in ("tickers", "stocks", "actions")
        },
        "resolution_map": [count.document() for count in resolved.counts],
        "served": [count.document() for count in gold.served],
        "resolved_profile": RESOLVED_PROFILE.value,
        "configuration_digest": configuration.digest,
        "outputs": [artifact.sha256 for artifact in (*gold.silver_artifacts, *gold.gold_artifacts)],
    }
    return sha256_hex(canonical_bytes(document))


def build_manifest_document(
    *,
    inputs: VerifiedBuildInputs,
    silver: SilverLayer,
    resolved: ResolvedLayer,
    universe: UniverseSnapshot,
    gold: GoldLayer,
    configuration: BuildConfiguration,
    published: tuple[PublishedArtifact, ...],
    run_id: str,
    completed_at: datetime,
) -> dict[str, Any]:
    """The closed manifest document. No vendor row; every binding explicit."""
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "build_id": inputs.build_identity,
        "run_id": run_id,
        "classification": DataClassification.LICENSED.value,
        "build_input": {
            "ledger_digest": inputs.ledger_digest,
            "runs": [
                {
                    "run_id": run.locator.run_id,
                    "plan_digest": run.locator.plan_digest,
                    "acquisition_mode": run.locator.acquisition_mode,
                    "entries": len(run.pages),
                    "payload_digests": [page.payload_sha256 for page in run.pages],
                    "record_digests": [page.record_sha256 for page in run.pages],
                }
                for run in inputs.runs
            ],
            "objects_read": inputs.object_count,
            "input_bytes": inputs.input_bytes,
        },
        "source_versions": {
            "source_schema_version": SOURCE_SCHEMA_VERSION,
            "accepted_schemas_version": silver.schemas_version,
            "observed_schema_digests": {
                dataset: list(silver.by_dataset(dataset).schema_digests)
                for dataset in ("tickers", "stocks", "actions")
            },
        },
        "transformation": {
            "silver_normalization_version": SILVER_NORMALIZATION_VERSION,
            "universe_rule": configuration.rule.document(),
            "adjustment_policy": ADJUSTMENT_POLICY.value,
            "adjustment_convention": ADJUSTMENT_CONVENTION.value,
            "adjustment_derivation_version": ADJUSTMENT_DERIVATION_VERSION,
            "action_selection_version": ACTION_SELECTION_VERSION,
            "resolution_policy_version": resolved.policy_version,
            "pagination_policy_version": silver.pagination.policy_version,
            "calendar_version": configuration.calendar.version,
            "quality_plan_version": gold.quality.plan_version,
            "evidence_version": resolved.evidence_version,
            "commit": configuration.commit,
            "configuration_digest": configuration.digest,
        },
        "resolved_profile": RESOLVED_PROFILE.value,
        "as_of": configuration.as_of.isoformat(),
        "resolution_map": [count.document() for count in resolved.counts],
        "served": [count.document() for count in gold.served],
        "pagination": silver.pagination.document(),
        "identity": {
            dataset: {
                "duplicate_rows": silver.by_dataset(dataset).duplicate_rows,
                "unmapped_symbols": silver.by_dataset(dataset).unmapped_symbols,
                "ambiguous_symbols": silver.by_dataset(dataset).ambiguous_symbols,
                "rows_excluded_for_identity": silver.by_dataset(dataset).rows_excluded_for_identity,
            }
            for dataset in ("tickers", "stocks", "actions")
        },
        "census": [entry.document() for entry in universe.census],
        "undecidable_sessions": [d.isoformat() for d in universe.undecidable_sessions],
        "quality": gold.quality.document(),
        "limitations": [token.value for token in gold.limitations],
        "spinoff_excluded_securities": list(gold.spinoff_excluded_securities),
        "restrictions": [item.document() for item in gold.restrictions],
        "unresolved_contracts": {
            "action-event-identity": {
                "statement": "the vendor actions table carries no event identity; a key "
                "absent from a later covering delivery is recorded as a redelivery gap, "
                "never read as a deletion or a correction",
                "action_keys_with_redelivery_gaps": sum(
                    1
                    for row in resolved.actions
                    if row.row.gaps_through(configuration.as_of) and row.row.revision_sequence == 0
                ),
                "adjusted_rows_withheld": gold.adjusted_rows_withheld_for_unresolved_actions,
            }
        },
        "empty_reason": gold.empty_reason,
        "outputs": [item.document() for item in published],
        "completed_at": completed_at.isoformat(),
    }


def _conditional_write(
    publisher: LicensedWriteOnlyPublisher,
    *,
    key: ObjectKey,
    payload: bytes,
    content_addressed: bool,
) -> PayloadDisposition:
    try:
        publisher.put_if_absent(key=key, payload=payload)
    except NameOccupiedError:
        if content_addressed:
            return PayloadDisposition.ALREADY_PRESENT
        raise _HaltError(PublicationHalt.PUBLICATION_CONFLICT) from None
    except ObjectStoreBackendError as error:
        if error.failure in _DEFINITIVE_REFUSALS:
            raise _HaltError(PublicationHalt.PUBLICATION_REFUSED) from None
        raise _HaltError(PublicationHalt.PUBLICATION_STATE_UNKNOWN, state_unknown=True) from None
    return PayloadDisposition.WRITTEN


def publish_build(
    *,
    publisher: LicensedWriteOnlyPublisher,
    inputs: VerifiedBuildInputs,
    silver: SilverLayer,
    resolved: ResolvedLayer,
    universe: UniverseSnapshot,
    gold: GoldLayer,
    configuration: BuildConfiguration,
    completed_at: datetime,
    deadline_exhausted: Any,
) -> PublicationResult:
    """Silver, then Gold, then -- only after every disposition is confirmed -- the manifest.

    ``deadline_exhausted`` is a zero-argument callable answering whether the deadline
    refused an admission; the accepted publisher wraps that refusal as an unclassified
    backend failure, and the halt must be the deadline's, with the state known.
    """
    published: list[PublishedArtifact] = []
    halt: PublicationHalt | None = None
    state_unknown = False
    try:
        for artifact in (*gold.silver_artifacts, *gold.gold_artifacts):
            key = artifact_key(artifact)
            disposition = _conditional_write(
                publisher, key=key, payload=artifact.content, content_addressed=True
            )
            published.append(
                PublishedArtifact(
                    artifact=artifact, logical_key=key.logical_key, disposition=disposition
                )
            )
    except _HaltError as stopped:
        halt, state_unknown = stopped.halt, stopped.state_unknown
        if deadline_exhausted():
            halt, state_unknown = PublicationHalt.DEADLINE_EXHAUSTED, False
    run_id = derive_run_id(
        inputs=inputs, silver=silver, resolved=resolved, gold=gold, configuration=configuration
    )
    if halt is not None:
        return PublicationResult(
            artifacts=tuple(published),
            halt=halt,
            publication_state_unknown=state_unknown,
            manifest=ManifestDisposition.NOT_ATTEMPTED,
            manifest_sha256=None,
            run_id=run_id,
        )
    document = build_manifest_document(
        inputs=inputs,
        silver=silver,
        resolved=resolved,
        universe=universe,
        gold=gold,
        configuration=configuration,
        published=tuple(published),
        run_id=run_id,
        completed_at=completed_at,
    )
    payload = canonical_bytes(document)
    if len(payload) > MAX_MANIFEST_BYTES:
        return PublicationResult(
            artifacts=tuple(published),
            halt=PublicationHalt.MANIFEST_TOO_LARGE,
            publication_state_unknown=False,
            manifest=ManifestDisposition.NOT_ATTEMPTED,
            manifest_sha256=None,
            run_id=run_id,
        )
    manifest_sha256 = sha256_hex(payload)
    try:
        _conditional_write(
            publisher,
            key=manifest_key(build_id=inputs.build_identity, payload=payload),
            payload=payload,
            content_addressed=False,
        )
    except _HaltError as stopped:
        if deadline_exhausted():
            # The deadline refused the admission; nothing was sent, the state is known.
            return PublicationResult(
                artifacts=tuple(published),
                halt=PublicationHalt.DEADLINE_EXHAUSTED,
                publication_state_unknown=False,
                manifest=ManifestDisposition.NOT_ATTEMPTED,
                manifest_sha256=None,
                run_id=run_id,
            )
        if stopped.halt is PublicationHalt.PUBLICATION_CONFLICT:
            fate, unknown = ManifestDisposition.NAME_OCCUPIED, False
        elif stopped.state_unknown:
            fate, unknown = ManifestDisposition.STATE_UNKNOWN, True
        else:
            fate, unknown = ManifestDisposition.REFUSED, False
        return PublicationResult(
            artifacts=tuple(published),
            halt=None,
            publication_state_unknown=unknown,
            manifest=fate,
            manifest_sha256=manifest_sha256,
            run_id=run_id,
        )
    return PublicationResult(
        artifacts=tuple(published),
        halt=None,
        publication_state_unknown=False,
        manifest=ManifestDisposition.PUBLISHED,
        manifest_sha256=manifest_sha256,
        run_id=run_id,
    )


__all__ = [
    "BUILDS_SEGMENT",
    "GOLD_NAMESPACE",
    "MANIFESTS_NAMESPACE",
    "MANIFEST_SCHEMA_VERSION",
    "MAX_MANIFEST_BYTES",
    "SILVER_NAMESPACE",
    "BuildConfiguration",
    "BuildConfigurationError",
    "ManifestDisposition",
    "PublicationHalt",
    "PublicationResult",
    "PublishedArtifact",
    "artifact_key",
    "build_manifest_document",
    "derive_run_id",
    "manifest_key",
    "publish_build",
]
