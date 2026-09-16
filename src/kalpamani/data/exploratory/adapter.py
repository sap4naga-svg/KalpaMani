"""The exploratory adapter: an admitted production build → an ``ExploratoryPublication``.

The M0 runner (:mod:`kalpamani.data.exploratory.m0`) reads a
:class:`~kalpamani.data.production.sharadar.silver.SilverLayer`, a
:class:`~kalpamani.data.production.sharadar.sessions.SessionCalendar` and the accepted
:class:`~kalpamani.data.production.sharadar.universe.UniverseRule`. An admitted production build
publishes exactly the material to rebuild them -- **as bytes** -- and this module turns those
bytes back into the objects, refusing anything it cannot bind:

* the **build manifest** (``kalpamani-production-build-manifest/v1``), parsed totally: a
  closed key set at every level, exact types, duplicate keys refused;
* the three **Silver artifacts** (``silver-tickers``, ``silver-stocks``, ``silver-actions``):
  digest and byte count verified against the manifest's ``outputs`` **before** a byte is parsed,
  every row document closed, every row's provenance bound to a run the manifest names;
* the **compiled build configuration**, whose canonical digest must equal the manifest's
  ``configuration_digest`` -- the calendar the build actually used, not a look-alike;
* the **rule**, which must be the accepted rule with **252 history sessions**.

Two refusals carry the point of the exercise. ``REVISIONS_EXCLUDED_BY_TIME``: the artifacts hold
the latest revision **admissible under production P-2 at the build's** ``as_of``; a manifest whose
``served`` counts say a revision was excluded by time describes rows the research layer would
silently lack, so it is refused rather than read as complete. ``NOT_A_SILVER_ARTIFACT``: Gold is
already adjusted, withholds restricted and spinoff rows and carries no attributes or actions --
offering it as Silver is refused by name; Gold alone is never a sufficient input.

**The calendar's close is an approximation.** ``Session`` carries ``open_at`` only; the
exploratory ``session_close`` is ``open_at + 6h30``
(:data:`~kalpamani.data.exploratory.resolution.REGULAR_SESSION`),
so an early-close day's bar is bounded and its signal placed at the regular close, later than the
exchange's actual early close. That is conservative (nothing is assumed available earlier than it
was) and it is **not** an exact exchange schedule; the assembled dataset records the approximation
in its publication limitations exactly as the fixture path does (``NO_INTRADAY_INSTANT``).

What this module never does: read S3 or any store (it takes bytes), emit an A1
``VerifiedPublication`` (it emits
:class:`~kalpamani.data.exploratory.contracts.ExploratoryPublication` through
:func:`~kalpamani.data.exploratory.dataset.publish`), select an owner decision, or run.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.exploratory.contracts import ExploratoryPublication
from kalpamani.data.exploratory.dataset import ExploratoryDataset, build_benchmark_a, publish
from kalpamani.data.exploratory.resolution import decide_membership_all, resolve_as_dated
from kalpamani.data.exploratory.vocabulary import ExploratoryLimitation
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.production.sharadar.pagination import PaginationSummary
from kalpamani.data.production.sharadar.sessions import Session as CalendarSession
from kalpamani.data.production.sharadar.sessions import SessionCalendar
from kalpamani.data.production.sharadar.silver import (
    Provenance,
    RowVersion,
    SilverDataset,
    SilverLayer,
)
from kalpamani.data.production.sharadar.universe import UniverseRule

#: The manifest contract this adapter reads. A different version is a different document.
MANIFEST_CONTRACT: Final = "kalpamani-production-build-manifest/v1"
#: The history the exploratory path requires: the accepted module's, and no other.
REQUIRED_HISTORY_SESSIONS: Final = 252
#: The Silver artifacts an admitted build publishes, by dataset.
SILVER_ARTIFACTS: Final[dict[str, str]] = {
    SharadarDataset.TICKERS.value: "silver-tickers",
    SharadarDataset.STOCKS.value: "silver-stocks",
    SharadarDataset.ACTIONS.value: "silver-actions",
}
_DATASETS: Final = tuple(SILVER_ARTIFACTS)
#: Byte ceilings: a manifest is small; a Silver artifact of a research window is not.
MAX_MANIFEST_BYTES: Final = 16 * 1024 * 1024
MAX_ARTIFACT_BYTES: Final = 2 * 1024 * 1024 * 1024
MAX_CONFIGURATION_BYTES: Final = 16 * 1024 * 1024
_HEX64: Final = frozenset("0123456789abcdef")


class AdapterDefect(StrEnum):
    """Why the adapter refused. Closed; never a raw exception."""

    MANIFEST_MALFORMED = "MANIFEST_MALFORMED"
    MANIFEST_CONTRACT_MISMATCH = "MANIFEST_CONTRACT_MISMATCH"
    MANIFEST_KEY_UNKNOWN = "MANIFEST_KEY_UNKNOWN"
    MANIFEST_KEY_DUPLICATE = "MANIFEST_KEY_DUPLICATE"
    MANIFEST_FIELD_MALFORMED = "MANIFEST_FIELD_MALFORMED"
    ARTIFACT_NOT_IN_MANIFEST = "ARTIFACT_NOT_IN_MANIFEST"
    ARTIFACT_DIGEST_MISMATCH = "ARTIFACT_DIGEST_MISMATCH"
    ARTIFACT_BYTES_MISMATCH = "ARTIFACT_BYTES_MISMATCH"
    ARTIFACT_MALFORMED = "ARTIFACT_MALFORMED"
    NOT_A_SILVER_ARTIFACT = "NOT_A_SILVER_ARTIFACT"
    DATASET_MISSING = "DATASET_MISSING"
    ROW_MALFORMED = "ROW_MALFORMED"
    ROW_DATASET_MISMATCH = "ROW_DATASET_MISMATCH"
    PROVENANCE_UNBOUND = "PROVENANCE_UNBOUND"
    REVISIONS_EXCLUDED_BY_TIME = "REVISIONS_EXCLUDED_BY_TIME"
    CONFIGURATION_MALFORMED = "CONFIGURATION_MALFORMED"
    CONFIGURATION_UNBOUND = "CONFIGURATION_UNBOUND"
    CALENDAR_VERSION_MISMATCH = "CALENDAR_VERSION_MISMATCH"
    RULE_MALFORMED = "RULE_MALFORMED"
    RULE_HISTORY_NOT_ACCEPTED = "RULE_HISTORY_NOT_ACCEPTED"


class AdapterError(Exception):
    """One closed refusal, raised ``from None``."""

    def __init__(self, defect: AdapterDefect) -> None:
        super().__init__(defect.value)
        self.defect = defect


def _refuse(defect: AdapterDefect) -> AdapterError:
    return AdapterError(defect)


# ---------------------------------------------------------------------------
# Total parsing helpers
# ---------------------------------------------------------------------------


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise _DuplicateKeyError
        out[key] = value
    return out


class _DuplicateKeyError(Exception):
    pass


def _decode(
    payload: bytes, *, ceiling: int, malformed: AdapterDefect, duplicate: AdapterDefect
) -> Any:
    if type(payload) is not bytes or len(payload) > ceiling:
        raise _refuse(malformed)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse(malformed) from None
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates)
    except _DuplicateKeyError:
        raise _refuse(duplicate) from None
    except (ValueError, RecursionError):
        raise _refuse(malformed) from None


def _mapping(value: Any, defect: AdapterDefect) -> dict[str, Any]:
    if type(value) is not dict:
        raise _refuse(defect)
    return value


def _closed(
    value: Any, keys: frozenset[str], *, unknown: AdapterDefect, malformed: AdapterDefect
) -> dict[str, Any]:
    out = _mapping(value, malformed)
    if set(out) != keys:
        raise _refuse(unknown if set(out) - keys else malformed)
    return out


def _text(value: Any, defect: AdapterDefect) -> str:
    if type(value) is not str:
        raise _refuse(defect)
    return value


def _hex64(value: Any, defect: AdapterDefect) -> str:
    text = _text(value, defect)
    if len(text) != 64 or set(text) - _HEX64:
        raise _refuse(defect)
    return text


def _count(value: Any, defect: AdapterDefect) -> int:
    if type(value) is not int or value < 0:
        raise _refuse(defect)
    return value


def _instant(value: Any, defect: AdapterDefect) -> datetime:
    text = _text(value, defect)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise _refuse(defect) from None
    if parsed.tzinfo is None:
        raise _refuse(defect)
    return parsed


def _day(value: Any, defect: AdapterDefect) -> date:
    text = _text(value, defect)
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise _refuse(defect) from None


def _texts(value: Any, defect: AdapterDefect) -> tuple[str, ...]:
    if type(value) is not list:
        raise _refuse(defect)
    return tuple(_text(item, defect) for item in value)


# ---------------------------------------------------------------------------
# The manifest view
# ---------------------------------------------------------------------------

_MANIFEST_KEYS: Final = frozenset(
    {
        "schema_version",
        "build_id",
        "run_id",
        "classification",
        "build_input",
        "source_versions",
        "transformation",
        "resolved_profile",
        "as_of",
        "resolution_map",
        "served",
        "pagination",
        "identity",
        "census",
        "undecidable_sessions",
        "quality",
        "limitations",
        "spinoff_excluded_securities",
        "restrictions",
        "unresolved_contracts",
        "empty_reason",
        "outputs",
        "completed_at",
    }
)
_OUTPUT_KEYS: Final = frozenset({"artifact", "key", "sha256", "bytes", "rows", "disposition"})
_RUN_KEYS: Final = frozenset(
    {"run_id", "plan_digest", "acquisition_mode", "entries", "payload_digests", "record_digests"}
)
_IDENTITY_KEYS: Final = frozenset(
    {"duplicate_rows", "unmapped_symbols", "ambiguous_symbols", "rows_excluded_for_identity"}
)
_SERVED_KEYS: Final = frozenset(
    {"dataset", "revisions_admitted", "revisions_superseded", "revisions_excluded_by_time"}
)
_RESOLUTION_KEYS: Final = frozenset(
    {"dataset", "P-2", "P-3/DELIVERY_WINDOW", "gated_evidence_ignored"}
)
_M: Final = AdapterDefect.MANIFEST_FIELD_MALFORMED


@dataclass(frozen=True, slots=True, kw_only=True)
class OutputRef:
    """One published artifact as the manifest names it."""

    artifact: str
    key: str
    sha256: str
    bytes: int
    rows: int
    disposition: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ServedCounts:
    """The manifest's ``served`` entry for one dataset: which revisions the build served at its
    ``as_of`` under production P-2/P-3, and how many it could not."""

    dataset: str
    revisions_admitted: int
    revisions_superseded: int
    revisions_excluded_by_time: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolutionCounts:
    """The manifest's ``resolution_map`` entry for one dataset: rows bounded by each rule."""

    dataset: str
    p2: int
    p3_delivery_window: int
    gated_evidence_ignored: int


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildManifestView:
    """What the adapter reads from an admitted build's manifest. Closed; bytes-derived."""

    manifest_digest: str
    build_id: str
    run_id: str
    as_of: datetime
    resolved_profile: str
    calendar_version: str
    configuration_digest: str
    commit: str
    accepted_schemas_version: str
    observed_schema_digests: dict[str, tuple[str, ...]]
    identity: dict[str, dict[str, int]]
    pagination: PaginationSummary
    served: dict[str, ServedCounts]
    resolution: dict[str, ResolutionCounts]
    universe_rule: dict[str, Any]
    outputs: dict[str, OutputRef]
    #: run id → the payload digests that run delivered: what every row's provenance must bind to.
    runs: dict[str, frozenset[str]]

    def document(self) -> dict[str, Any]:
        return {
            "manifest_digest": self.manifest_digest,
            "build_id": self.build_id,
            "run_id": self.run_id,
            "as_of": self.as_of.isoformat(),
            "calendar_version": self.calendar_version,
            "configuration_digest": self.configuration_digest,
            "commit": self.commit,
            "outputs": sorted(self.outputs),
            "runs": sorted(self.runs),
        }


def parse_manifest(document: bytes) -> BuildManifestView:
    """Total parsing of the accepted build manifest. Every refusal is an :class:`AdapterDefect`."""
    raw = _decode(
        document,
        ceiling=MAX_MANIFEST_BYTES,
        malformed=AdapterDefect.MANIFEST_MALFORMED,
        duplicate=AdapterDefect.MANIFEST_KEY_DUPLICATE,
    )
    top = _closed(
        raw,
        _MANIFEST_KEYS,
        unknown=AdapterDefect.MANIFEST_KEY_UNKNOWN,
        malformed=AdapterDefect.MANIFEST_MALFORMED,
    )
    if top["schema_version"] != MANIFEST_CONTRACT:
        raise _refuse(AdapterDefect.MANIFEST_CONTRACT_MISMATCH)
    if _text(top["classification"], _M) != "LICENSED":
        raise _refuse(_M)
    source = _mapping(top["source_versions"], _M)
    transformation = _mapping(top["transformation"], _M)
    observed: dict[str, tuple[str, ...]] = {}
    for dataset in _DATASETS:
        digests = _texts(_mapping(source.get("observed_schema_digests"), _M).get(dataset), _M)
        observed[dataset] = tuple(_hex64(d, _M) for d in digests)
    identity: dict[str, dict[str, int]] = {}
    for dataset in _DATASETS:
        block = _closed(
            _mapping(top["identity"], _M).get(dataset), _IDENTITY_KEYS, unknown=_M, malformed=_M
        )
        identity[dataset] = {name: _count(block[name], _M) for name in sorted(_IDENTITY_KEYS)}
    pagination_doc = _mapping(top["pagination"], _M)
    pagination = PaginationSummary(
        policy_version=_text(pagination_doc.get("policy_version"), _M),
        groups_admitted={
            _text(k, _M): _count(v, _M)
            for k, v in _mapping(pagination_doc.get("groups_admitted"), _M).items()
        },
        groups_empty={
            _text(k, _M): _count(v, _M)
            for k, v in _mapping(pagination_doc.get("groups_empty"), _M).items()
        },
    )
    served: dict[str, ServedCounts] = {}
    if type(top["served"]) is not list:
        raise _refuse(_M)
    for entry in top["served"]:
        block = _closed(entry, _SERVED_KEYS, unknown=_M, malformed=_M)
        dataset = _text(block["dataset"], _M)
        if dataset not in SILVER_ARTIFACTS or dataset in served:
            raise _refuse(_M)
        served[dataset] = ServedCounts(
            dataset=dataset,
            revisions_admitted=_count(block["revisions_admitted"], _M),
            revisions_superseded=_count(block["revisions_superseded"], _M),
            revisions_excluded_by_time=_count(block["revisions_excluded_by_time"], _M),
        )
    if set(served) != set(_DATASETS):
        raise _refuse(_M)
    resolution: dict[str, ResolutionCounts] = {}
    if type(top["resolution_map"]) is not list:
        raise _refuse(_M)
    for entry in top["resolution_map"]:
        block = _closed(entry, _RESOLUTION_KEYS, unknown=_M, malformed=_M)
        dataset = _text(block["dataset"], _M)
        if dataset not in SILVER_ARTIFACTS or dataset in resolution:
            raise _refuse(_M)
        resolution[dataset] = ResolutionCounts(
            dataset=dataset,
            p2=_count(block["P-2"], _M),
            p3_delivery_window=_count(block["P-3/DELIVERY_WINDOW"], _M),
            gated_evidence_ignored=_count(block["gated_evidence_ignored"], _M),
        )
    if set(resolution) != set(_DATASETS):
        raise _refuse(_M)
    outputs: dict[str, OutputRef] = {}
    if type(top["outputs"]) is not list:
        raise _refuse(_M)
    for entry in top["outputs"]:
        block = _closed(entry, _OUTPUT_KEYS, unknown=_M, malformed=_M)
        name = _text(block["artifact"], _M)
        if name in outputs:
            raise _refuse(_M)
        outputs[name] = OutputRef(
            artifact=name,
            key=_text(block["key"], _M),
            sha256=_hex64(block["sha256"], _M),
            bytes=_count(block["bytes"], _M),
            rows=_count(block["rows"], _M),
            disposition=_text(block["disposition"], _M),
        )
    runs: dict[str, frozenset[str]] = {}
    build_input = _mapping(top["build_input"], _M)
    if type(build_input.get("runs")) is not list:
        raise _refuse(_M)
    for entry in build_input["runs"]:
        block = _closed(entry, _RUN_KEYS, unknown=_M, malformed=_M)
        run_id = _text(block["run_id"], _M)
        if run_id in runs:
            raise _refuse(_M)
        runs[run_id] = frozenset(_hex64(d, _M) for d in _texts(block["payload_digests"], _M))
    return BuildManifestView(
        manifest_digest=sha256_hex(document),
        build_id=_text(top["build_id"], _M),
        run_id=_text(top["run_id"], _M),
        as_of=_instant(top["as_of"], _M),
        resolved_profile=_text(top["resolved_profile"], _M),
        calendar_version=_text(transformation.get("calendar_version"), _M),
        configuration_digest=_hex64(transformation.get("configuration_digest"), _M),
        commit=_text(transformation.get("commit"), _M),
        accepted_schemas_version=_text(source.get("accepted_schemas_version"), _M),
        observed_schema_digests=observed,
        identity=identity,
        pagination=pagination,
        served=served,
        resolution=resolution,
        universe_rule=_mapping(transformation.get("universe_rule"), _M),
        outputs=outputs,
        runs=runs,
    )


# ---------------------------------------------------------------------------
# Silver artifacts → row versions
# ---------------------------------------------------------------------------

_ROW_KEYS: Final = frozenset(
    {
        "row_key",
        "security_id",
        "revision_sequence",
        "content_sha256",
        "fields",
        "provider_last_updated_date",
        "system_first_seen_time",
        "content_first_seen_time",
        "is_return",
        "observation_count",
        "observed_at",
        "redelivery_gaps",
        "provenance",
        "availability",
    }
)
_PROVENANCE_KEYS: Final = frozenset(
    {
        "acquisition_id",
        "request_ordinal",
        "source_digest",
        "schema_digest",
        "acquisition_mode",
        "retrieved_at",
    }
)
_R: Final = AdapterDefect.ROW_MALFORMED


def _row_version(dataset: str, document: Any) -> tuple[RowVersion, tuple[str, ...]]:
    """One ``_silver_document`` back into a ``RowVersion``, and the gap run ids it named."""
    block = _closed(document, _ROW_KEYS, unknown=_R, malformed=_R)
    fields_raw = _mapping(block["fields"], _R)
    fields: dict[str, str | None] = {}
    for name, value in fields_raw.items():
        if type(name) is not str or (value is not None and type(value) is not str):
            raise _refuse(_R)
        fields[name] = value
    symbol = fields.get("ticker")
    if type(symbol) is not str or not symbol:
        raise _refuse(_R)
    prov = _closed(block["provenance"], _PROVENANCE_KEYS, unknown=_R, malformed=_R)
    observed = block["observed_at"]
    if type(observed) is not list or not observed:
        raise _refuse(_R)
    observed_at = tuple(_instant(item, _R) for item in observed)
    if type(block["is_return"]) is not bool or _count(block["observation_count"], _R) != len(
        observed_at
    ):
        raise _refuse(_R)
    gaps = _texts(block["redelivery_gaps"], _R)
    row = RowVersion(
        dataset=dataset,
        row_key=_texts(block["row_key"], _R),
        security_id=_text(block["security_id"], _R),
        symbol=symbol,
        revision_sequence=_count(block["revision_sequence"], _R),
        content_sha256=_hex64(block["content_sha256"], _R),
        fields=fields,
        provenance=Provenance(
            run_id=_text(prov["acquisition_id"], _R),
            ordinal=_count(prov["request_ordinal"], _R),
            payload_sha256=_hex64(prov["source_digest"], _R),
            schema_digest=_hex64(prov["schema_digest"], _R),
            acquisition_mode=_text(prov["acquisition_mode"], _R),
            retrieved_at=_instant(prov["retrieved_at"], _R),
        ),
        system_first_seen_time=_instant(block["system_first_seen_time"], _R),
        content_first_seen_time=_instant(block["content_first_seen_time"], _R),
        observed_at=observed_at,
        # The artifact names the runs whose covering window did not redeliver the key, but
        # not the instant each was seen; a gap's instant is NOT reconstructible here. The
        # exploratory path consumes no gap; the run ids are returned beside the row so a
        # caller can record that the instants are unknown, never invented.
        redelivery_gaps=(),
    )
    if not row.row_key or row.row_key[0] != row.security_id:
        raise _refuse(_R)
    return row, gaps


def parse_silver_artifact(
    name: str, content: bytes, *, expected_sha256: str, expected_bytes: int
) -> tuple[tuple[RowVersion, ...], int]:
    """The rows of one Silver artifact, after its digest and byte count are verified.

    Returns the rows and the number of redelivery-gap run ids the artifact named (whose
    instants are not reconstructible and are not carried on the rows).
    """
    if type(name) is not str or name not in SILVER_ARTIFACTS.values():
        raise _refuse(AdapterDefect.NOT_A_SILVER_ARTIFACT)
    if type(content) is not bytes or len(content) > MAX_ARTIFACT_BYTES:
        raise _refuse(AdapterDefect.ARTIFACT_MALFORMED)
    if len(content) != expected_bytes:
        raise _refuse(AdapterDefect.ARTIFACT_BYTES_MISMATCH)
    if sha256_hex(content) != expected_sha256:
        raise _refuse(AdapterDefect.ARTIFACT_DIGEST_MISMATCH)
    raw = _decode(
        content,
        ceiling=MAX_ARTIFACT_BYTES,
        malformed=AdapterDefect.ARTIFACT_MALFORMED,
        duplicate=AdapterDefect.ARTIFACT_MALFORMED,
    )
    top = _closed(
        raw,
        frozenset({"artifact", "rows"}),
        unknown=AdapterDefect.ARTIFACT_MALFORMED,
        malformed=AdapterDefect.ARTIFACT_MALFORMED,
    )
    if top["artifact"] != name or type(top["rows"]) is not list:
        raise _refuse(AdapterDefect.ARTIFACT_MALFORMED)
    dataset = next(d for d, artifact in SILVER_ARTIFACTS.items() if artifact == name)
    rows: list[RowVersion] = []
    gap_names = 0
    for document in top["rows"]:
        row, gaps = _row_version(dataset, document)
        rows.append(row)
        gap_names += len(gaps)
    return tuple(rows), gap_names


@dataclass(frozen=True, slots=True, kw_only=True)
class LayerAssembly:
    """The assembled layer and what the assembly could not carry."""

    layer: SilverLayer
    manifest: BuildManifestView
    #: Redelivery-gap run ids named by the artifacts whose instants are unknown (not carried).
    gap_instants_unknown: int


def assemble_layer(manifest: BuildManifestView, artifacts: Mapping[str, bytes]) -> LayerAssembly:
    """The build's Silver layer from its manifest and its three Silver artifacts.

    Every artifact must be one the manifest lists under ``outputs`` with a confirmed
    disposition; its digest and byte count are verified before parsing; every row's provenance
    must name a run and a payload digest the manifest's build input names; a manifest whose
    resolution map excluded any revision by time is refused.
    """
    if type(manifest) is not BuildManifestView:
        raise TypeError("manifest must be a BuildManifestView")
    for counts in manifest.served.values():
        if counts.revisions_excluded_by_time != 0:
            raise _refuse(AdapterDefect.REVISIONS_EXCLUDED_BY_TIME)
    for name in artifacts:
        if name not in SILVER_ARTIFACTS.values():
            raise _refuse(AdapterDefect.NOT_A_SILVER_ARTIFACT)
    datasets: dict[str, SilverDataset] = {}
    gap_instants_unknown = 0
    for dataset, name in SILVER_ARTIFACTS.items():
        content = artifacts.get(name)
        if content is None:
            raise _refuse(AdapterDefect.DATASET_MISSING)
        ref = manifest.outputs.get(name)
        if ref is None or ref.disposition not in ("WRITTEN", "ALREADY_PRESENT"):
            raise _refuse(AdapterDefect.ARTIFACT_NOT_IN_MANIFEST)
        rows, gaps = parse_silver_artifact(
            name, content, expected_sha256=ref.sha256, expected_bytes=ref.bytes
        )
        if len(rows) != ref.rows:
            raise _refuse(AdapterDefect.ARTIFACT_MALFORMED)
        for row in rows:
            if row.dataset != dataset:
                raise _refuse(AdapterDefect.ROW_DATASET_MISMATCH)
            delivered = manifest.runs.get(row.provenance.run_id)
            if delivered is None or row.provenance.payload_sha256 not in delivered:
                raise _refuse(AdapterDefect.PROVENANCE_UNBOUND)
        gap_instants_unknown += gaps
        identity = manifest.identity[dataset]
        datasets[dataset] = SilverDataset(
            dataset=dataset,
            rows=rows,
            schema_digests=manifest.observed_schema_digests[dataset],
            duplicate_rows=identity["duplicate_rows"],
            unmapped_symbols=identity["unmapped_symbols"],
            ambiguous_symbols=identity["ambiguous_symbols"],
            rows_excluded_for_identity=identity["rows_excluded_for_identity"],
        )
    layer = SilverLayer(
        tickers=datasets[SharadarDataset.TICKERS.value],
        stocks=datasets[SharadarDataset.STOCKS.value],
        actions=datasets[SharadarDataset.ACTIONS.value],
        schemas_version=manifest.accepted_schemas_version,
        pagination=manifest.pagination,
    )
    return LayerAssembly(layer=layer, manifest=manifest, gap_instants_unknown=gap_instants_unknown)


# ---------------------------------------------------------------------------
# Calendar and rule, bound to the build
# ---------------------------------------------------------------------------


def calendar_from_configuration(document: bytes, *, manifest: BuildManifestView) -> SessionCalendar:
    """The calendar the build was compiled with, from the compiled build configuration.

    The configuration's canonical digest must equal the manifest's ``configuration_digest``
    and its calendar version the manifest's ``calendar_version``: the sessions returned are
    the ones the build decided under, not a look-alike. The close is **not** in the
    document -- ``Session`` carries ``open_at`` only -- so the exploratory path's regular-close
    approximation applies to every session, early-close days included.
    """
    raw = _decode(
        document,
        ceiling=MAX_CONFIGURATION_BYTES,
        malformed=AdapterDefect.CONFIGURATION_MALFORMED,
        duplicate=AdapterDefect.CONFIGURATION_MALFORMED,
    )
    top = _mapping(raw, AdapterDefect.CONFIGURATION_MALFORMED)
    if sha256_hex(canonical_bytes(top)) != manifest.configuration_digest:
        raise _refuse(AdapterDefect.CONFIGURATION_UNBOUND)
    block = _closed(
        top.get("calendar"),
        frozenset({"version", "sessions"}),
        unknown=AdapterDefect.CONFIGURATION_MALFORMED,
        malformed=AdapterDefect.CONFIGURATION_MALFORMED,
    )
    version = _text(block["version"], AdapterDefect.CONFIGURATION_MALFORMED)
    if version != manifest.calendar_version:
        raise _refuse(AdapterDefect.CALENDAR_VERSION_MISMATCH)
    if type(block["sessions"]) is not list or not block["sessions"]:
        raise _refuse(AdapterDefect.CONFIGURATION_MALFORMED)
    sessions: list[CalendarSession] = []
    for entry in block["sessions"]:
        item = _closed(
            entry,
            frozenset({"session_date", "open_at"}),
            unknown=AdapterDefect.CONFIGURATION_MALFORMED,
            malformed=AdapterDefect.CONFIGURATION_MALFORMED,
        )
        try:
            sessions.append(
                CalendarSession(
                    session_date=_day(item["session_date"], AdapterDefect.CONFIGURATION_MALFORMED),
                    open_at=_instant(item["open_at"], AdapterDefect.CONFIGURATION_MALFORMED),
                )
            )
        except (TypeError, ValueError):
            raise _refuse(AdapterDefect.CONFIGURATION_MALFORMED) from None
    try:
        return SessionCalendar(version=version, sessions=tuple(sessions))
    except (TypeError, ValueError):
        raise _refuse(AdapterDefect.CONFIGURATION_MALFORMED) from None


_RULE_KEYS: Final = frozenset(
    {
        "universe_rule_version",
        "decision_margin_seconds",
        "history_sessions",
        "addv_window_sessions",
        "price_floor",
        "addv_floor",
        "eligible_exchanges",
        "common_stock_categories",
    }
)


def rule_from_manifest(manifest: BuildManifestView) -> UniverseRule:
    """The accepted rule the build decided under. Only 252 history sessions is accepted here."""
    from datetime import timedelta

    block = _closed(
        manifest.universe_rule,
        _RULE_KEYS,
        unknown=AdapterDefect.RULE_MALFORMED,
        malformed=AdapterDefect.RULE_MALFORMED,
    )
    d = AdapterDefect.RULE_MALFORMED
    history = _count(block["history_sessions"], d)
    if history != REQUIRED_HISTORY_SESSIONS:
        raise _refuse(AdapterDefect.RULE_HISTORY_NOT_ACCEPTED)
    try:
        return UniverseRule(
            version=_text(block["universe_rule_version"], d),
            decision_margin=timedelta(seconds=_count(block["decision_margin_seconds"], d)),
            history_sessions=history,
            addv_window_sessions=_count(block["addv_window_sessions"], d),
            price_floor=Decimal(_text(block["price_floor"], d)),
            addv_floor=Decimal(_text(block["addv_floor"], d)),
            eligible_exchanges=frozenset(_texts(block["eligible_exchanges"], d)),
            common_stock_categories=frozenset(_texts(block["common_stock_categories"], d)),
        )
    except (TypeError, ValueError, ArithmeticError):
        raise _refuse(d) from None


# ---------------------------------------------------------------------------
# The dataset and its publication
# ---------------------------------------------------------------------------


def build_dataset(
    assembly: LayerAssembly,
    *,
    calendar: SessionCalendar,
    rule: UniverseRule,
    as_of: datetime | None = None,
) -> ExploratoryDataset:
    """AS_DATED resolution, the accepted membership clauses, benchmark A -- over the
    assembled layer. ``as_of`` defaults to the build's; a later instant is allowed, an
    earlier one is not (the artifacts hold what the build served at its own ``as_of``)."""
    if type(assembly) is not LayerAssembly:
        raise TypeError("assembly must be a LayerAssembly")
    if rule.history_sessions != REQUIRED_HISTORY_SESSIONS:
        raise _refuse(AdapterDefect.RULE_HISTORY_NOT_ACCEPTED)
    if calendar.version != assembly.manifest.calendar_version:
        raise _refuse(AdapterDefect.CALENDAR_VERSION_MISMATCH)
    instant = assembly.manifest.as_of if as_of is None else as_of
    if type(instant) is not datetime or instant.tzinfo is None or instant < assembly.manifest.as_of:
        raise _refuse(AdapterDefect.MANIFEST_FIELD_MALFORMED)
    resolved = resolve_as_dated(assembly.layer, calendar=calendar)
    membership = decide_membership_all(resolved, rule=rule, calendar=calendar, as_of=instant)
    benchmark = build_benchmark_a(resolved, membership, calendar=calendar)
    return ExploratoryDataset(
        layer=resolved,
        membership=membership,
        calendar=calendar,
        benchmark=benchmark,
        as_of=instant,
        source_manifest_digest=assembly.manifest.manifest_digest,
    )


def publish_from_build(
    dataset: ExploratoryDataset,
    *,
    publication_id: str,
    limitations: frozenset[ExploratoryLimitation],
) -> ExploratoryPublication:
    """The exploratory publication of an adapted build -- never an A1 ``VerifiedPublication``."""
    return publish(dataset, publication_id=publication_id, limitations=limitations)


__all__ = [
    "MANIFEST_CONTRACT",
    "MAX_ARTIFACT_BYTES",
    "MAX_CONFIGURATION_BYTES",
    "MAX_MANIFEST_BYTES",
    "REQUIRED_HISTORY_SESSIONS",
    "SILVER_ARTIFACTS",
    "AdapterDefect",
    "AdapterError",
    "BuildManifestView",
    "LayerAssembly",
    "OutputRef",
    "ResolutionCounts",
    "ServedCounts",
    "assemble_layer",
    "build_dataset",
    "calendar_from_configuration",
    "parse_manifest",
    "parse_silver_artifact",
    "publish_from_build",
    "rule_from_manifest",
    "sha256_hex",
]
