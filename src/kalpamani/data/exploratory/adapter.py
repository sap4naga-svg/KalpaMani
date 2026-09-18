"""The exploratory adapter: an admitted production build → an ``ExploratoryPublication``.

The M0 runner (:mod:`kalpamani.data.exploratory.m0`) reads a
:class:`~kalpamani.data.production.sharadar.silver.SilverLayer`, a
:class:`~kalpamani.data.production.sharadar.sessions.SessionCalendar` and the accepted
:class:`~kalpamani.data.production.sharadar.universe.UniverseRule`. An admitted production build
publishes exactly the material to rebuild them -- **as bytes** -- and this module turns those
bytes back into the objects, refusing anything it cannot bind:

* the **build manifest** (``kalpamani-production-build-manifest/v2``), parsed totally: a
  closed key set at every level, exact types, duplicate keys refused, every fixed contract value
  (profile, classification, policies, versions, modes, tokens, dispositions) held to the accepted
  vocabulary, and every field validated whether or not the research path reads it;
* the three **Silver artifacts** (``silver-tickers``, ``silver-stocks``, ``silver-actions``):
  digest and byte count verified against the manifest's ``outputs`` **before** a byte is parsed,
  every row document closed, every row's provenance bound to a run the manifest names;
* the **compiled build configuration**, whose canonical digest must equal the manifest's
  ``configuration_digest`` -- the calendar the build actually used, not a look-alike -- and whose
  every repeated fact (the rule, the calendar version, ``as_of``, the commit, the schema and
  transformation versions, the evidence version, the observed schema digests) must agree with
  what the manifest says;
* the **rule**, which must be the accepted rule with **252 history sessions**.

**The binding survives to dataset construction.** :func:`bind_configuration` is the one place a
calendar or a rule enters this module, and it returns a :class:`BoundConfiguration` that carries
the verified bytes beside the objects derived from them. :func:`build_dataset` takes only that --
never a caller-supplied calendar or rule -- re-verifies the digest against the assembly's manifest
and re-derives the calendar and rule from the bytes, so a substituted calendar with the right
version but other sessions, or a rule with 252 sessions but another floor, is
``CONFIGURATION_INCONSISTENT`` rather than read. The research ``as_of`` override (a later instant,
never an earlier one -- ``AS_OF_BEFORE_BUILD``) is a parameter of the research, not a build fact,
and is kept distinct from inconsistent build metadata.

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
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.vocabulary import (
    AcquisitionMode,
    AdjustmentConvention,
    AdjustmentPolicy,
    DataClassification,
    LimitationToken,
)
from kalpamani.data.exploratory.contracts import ExploratoryPublication
from kalpamani.data.exploratory.dataset import ExploratoryDataset, build_benchmark_a, publish
from kalpamani.data.exploratory.resolution import decide_membership_all, resolve_as_dated
from kalpamani.data.exploratory.vocabulary import ExploratoryLimitation
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.production.sharadar.availability import (
    ACTION_SELECTION_VERSION,
    RESOLUTION_POLICY_VERSION,
    RESOLVED_PROFILE,
)
from kalpamani.data.production.sharadar.pagination import (
    PAGINATION_POLICY_VERSION,
    PaginationSummary,
)
from kalpamani.data.production.sharadar.sessions import Session as CalendarSession
from kalpamani.data.production.sharadar.sessions import SessionCalendar
from kalpamani.data.production.sharadar.silver import (
    ACTIONS_IDENTITY_VERSION,
    SILVER_NORMALIZATION_VERSION,
    Provenance,
    RowVersion,
    SilverDataset,
    SilverLayer,
)
from kalpamani.data.production.sharadar.universe import UniverseRule

#: The manifest contract this adapter reads. A different version is a different document.
MANIFEST_CONTRACT: Final = "kalpamani-production-build-manifest/v2"
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
_BUILD_ID_CHARS: Final = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)
_COMMIT_LENGTH: Final = 40

#: Fixed contract values the accepted producer writes and this adapter cannot import without
#: reaching a runtime module: pinned here, and held equal to the producer's by a unit test.
#: A producer that changes one of them has changed the contract; the adapter then refuses
#: (``MANIFEST_VALUE_UNSUPPORTED``) until it is reviewed against the new value.
SOURCE_SCHEMA_VERSION: Final = "sharadar-csv-production-v1"
ADJUSTMENT_DERIVATION_VERSION: Final = "sharadar-adjusted-bars-v2"
QUALITY_PLAN_VERSION: Final = "breakout-long-ingest-v1"
ADJUSTMENT_POLICY: Final = AdjustmentPolicy.SPLIT_ONLY
ADJUSTMENT_CONVENTION: Final = AdjustmentConvention.FORWARD_BASE_NORMALIZED
#: The two dispositions a confirmed content-addressed write can carry (ADR-0040).
CONFIRMED_DISPOSITIONS: Final = frozenset({"WRITTEN", "ALREADY_PRESENT"})
_FIXED_TRANSFORMATION_VERSIONS: Final[dict[str, str]] = {
    "silver_normalization_version": SILVER_NORMALIZATION_VERSION,
    "adjustment_policy": ADJUSTMENT_POLICY.value,
    "adjustment_convention": ADJUSTMENT_CONVENTION.value,
    "adjustment_derivation_version": ADJUSTMENT_DERIVATION_VERSION,
    "action_selection_version": ACTION_SELECTION_VERSION,
    "resolution_policy_version": RESOLUTION_POLICY_VERSION,
    "pagination_policy_version": PAGINATION_POLICY_VERSION,
    "actions_identity_version": ACTIONS_IDENTITY_VERSION,
    "quality_plan_version": QUALITY_PLAN_VERSION,
}


class AdapterDefect(StrEnum):
    """Why the adapter refused. Closed; never a raw exception."""

    MANIFEST_MALFORMED = "MANIFEST_MALFORMED"
    MANIFEST_CONTRACT_MISMATCH = "MANIFEST_CONTRACT_MISMATCH"
    MANIFEST_KEY_UNKNOWN = "MANIFEST_KEY_UNKNOWN"
    MANIFEST_KEY_DUPLICATE = "MANIFEST_KEY_DUPLICATE"
    MANIFEST_FIELD_MALFORMED = "MANIFEST_FIELD_MALFORMED"
    MANIFEST_VALUE_UNSUPPORTED = "MANIFEST_VALUE_UNSUPPORTED"
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
    CONFIGURATION_INCONSISTENT = "CONFIGURATION_INCONSISTENT"
    AS_OF_BEFORE_BUILD = "AS_OF_BEFORE_BUILD"
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


def _hex64s(value: Any, defect: AdapterDefect) -> tuple[str, ...]:
    return tuple(_hex64(item, defect) for item in _texts(value, defect))


def _days(value: Any, defect: AdapterDefect) -> tuple[date, ...]:
    if type(value) is not list:
        raise _refuse(defect)
    return tuple(_day(item, defect) for item in value)


def _boolean(value: Any, defect: AdapterDefect) -> bool:
    if type(value) is not bool:
        raise _refuse(defect)
    return value


def _nonempty(value: Any, defect: AdapterDefect) -> str:
    text = _text(value, defect)
    if not text:
        raise _refuse(defect)
    return text


def _commit(value: Any, defect: AdapterDefect) -> str:
    text = _text(value, defect)
    if len(text) != _COMMIT_LENGTH or set(text) - _HEX64:
        raise _refuse(defect)
    return text


def _build_id(value: Any, defect: AdapterDefect) -> str:
    text = _text(value, defect)
    if not 1 <= len(text) <= 64 or set(text) - _BUILD_ID_CHARS or text[0] in "._-":
        raise _refuse(defect)
    return text


def _sequence(value: Any, defect: AdapterDefect) -> list[Any]:
    if type(value) is not list:
        raise _refuse(defect)
    return value


def _fixed(
    value: Any, expected: str, *, malformed: AdapterDefect, unsupported: AdapterDefect
) -> str:
    text = _text(value, malformed)
    if text != expected:
        raise _refuse(unsupported)
    return text


def _member(
    value: Any, members: frozenset[str], *, malformed: AdapterDefect, unsupported: AdapterDefect
) -> str:
    text = _text(value, malformed)
    if text not in members:
        raise _refuse(unsupported)
    return text


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
        "identity_contracts",
        "empty_reason",
        "outputs",
        "completed_at",
    }
)
_BUILD_INPUT_KEYS: Final = frozenset({"ledger_digest", "runs", "objects_read", "input_bytes"})
_RUN_KEYS: Final = frozenset(
    {
        "run_id",
        "plan_digest",
        "acquisition_mode",
        "entries",
        "probes_issued",
        "provider_calls",
        "payload_digests",
        "record_digests",
    }
)
_SOURCE_KEYS: Final = frozenset(
    {"source_schema_version", "accepted_schemas_version", "observed_schema_digests"}
)
_TRANSFORMATION_KEYS: Final = frozenset(
    {
        "silver_normalization_version",
        "universe_rule",
        "adjustment_policy",
        "adjustment_convention",
        "adjustment_derivation_version",
        "action_selection_version",
        "resolution_policy_version",
        "pagination_policy_version",
        "actions_identity_version",
        "calendar_version",
        "quality_plan_version",
        "evidence_version",
        "commit",
        "configuration_digest",
    }
)
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
_RESOLUTION_KEYS: Final = frozenset(
    {"dataset", "P-2", "P-3/DELIVERY_WINDOW", "gated_evidence_ignored"}
)
_SERVED_KEYS: Final = frozenset(
    {"dataset", "revisions_admitted", "revisions_superseded", "revisions_excluded_by_time"}
)
#: The pagination record as the accepted contract writes it: the two dynamic maps plus the fixed
#: statements of what the admission does and does not establish, taken from the contract itself.
_PAGINATION_FIXED: Final[dict[str, Any]] = {
    key: value
    for key, value in PaginationSummary(
        policy_version=PAGINATION_POLICY_VERSION,
        groups_admitted={},
        groups_empty={},
        groups_probed={},
    )
    .document()
    .items()
    if key not in ("groups_admitted", "groups_empty", "groups_probed")
}
_PAGINATION_KEYS: Final = frozenset(
    {*_PAGINATION_FIXED, "groups_admitted", "groups_empty", "groups_probed"}
)
_IDENTITY_KEYS: Final = frozenset(
    {"duplicate_rows", "unmapped_symbols", "ambiguous_symbols", "rows_excluded_for_identity"}
)
_CENSUS_KEYS: Final = frozenset(
    {"session_date", "securities", "attribute_determinable", "attribute_unavailable", "members"}
)
_QUALITY_KEYS: Final = frozenset(
    {
        "plan_version",
        "checks_run",
        "checks_not_run",
        "findings",
        "restricted_securities",
        "build_blocking",
    }
)
_FINDING_KEYS: Final = frozenset({"check", "severity", "scope", "count", "effective_from"})
_RESTRICTION_KEYS: Final = frozenset(
    {
        "security_id",
        "scope",
        "check",
        "severity",
        "count",
        "restricted_from",
        "sessions_affected",
        "withheld",
    }
)
_IDENTITY_CONTRACT_KEYS: Final = frozenset({"action-event-identity"})
_ACTION_EVENT_KEYS: Final = frozenset(
    {"contract_id", "statement", "action_keys_with_redelivery_gaps", "adjusted_rows_withheld"}
)
_OUTPUT_KEYS: Final = frozenset({"artifact", "key", "sha256", "bytes", "rows", "disposition"})
_ACQUISITION_MODES: Final = frozenset(mode.value for mode in AcquisitionMode)
_LIMITATION_TOKENS: Final = frozenset(token.value for token in LimitationToken)
_M: Final = AdapterDefect.MANIFEST_FIELD_MALFORMED
_U: Final = AdapterDefect.MANIFEST_VALUE_UNSUPPORTED


def _block(value: Any, keys: frozenset[str]) -> dict[str, Any]:
    """A closed manifest block at any depth: an unknown key is ``MANIFEST_KEY_UNKNOWN``, a missing
    key or a non-object is ``MANIFEST_MALFORMED`` -- the same vocabulary the top level uses."""
    return _closed(
        value,
        keys,
        unknown=AdapterDefect.MANIFEST_KEY_UNKNOWN,
        malformed=AdapterDefect.MANIFEST_MALFORMED,
    )


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
class RunRef:
    """One acquisition run the build read: its identity, plan, mode and the digests of every
    payload and record it delivered. ``entries`` is the page count and equals both lengths."""

    run_id: str
    plan_digest: str
    acquisition_mode: str
    entries: int
    payload_digests: tuple[str, ...]
    record_digests: tuple[str, ...]


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
    """What the adapter reads from an admitted build's manifest. Closed; bytes-derived.

    Every field of the manifest was validated to produce this view, including the ones the
    research path never reads (census, quality, restrictions, ``completed_at``): a manifest that
    fails anywhere is not an admitted build's.
    """

    manifest_digest: str
    build_id: str
    run_id: str
    classification: str
    as_of: datetime
    completed_at: datetime
    resolved_profile: str
    calendar_version: str
    configuration_digest: str
    commit: str
    source_schema_version: str
    accepted_schemas_version: str
    observed_schema_digests: dict[str, tuple[str, ...]]
    #: The transformation versions the manifest repeats from the compiled configuration.
    transformation_versions: dict[str, str]
    identity: dict[str, dict[str, int]]
    pagination: PaginationSummary
    served: dict[str, ServedCounts]
    resolution: dict[str, ResolutionCounts]
    universe_rule: dict[str, Any]
    outputs: dict[str, OutputRef]
    #: run id → the run: what every row's provenance must bind to.
    runs: dict[str, RunRef]

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


def _parse_build_input(value: Any) -> tuple[dict[str, RunRef], str]:
    block = _block(value, _BUILD_INPUT_KEYS)
    ledger_digest = _hex64(block["ledger_digest"], _M)
    _count(block["objects_read"], _M)
    _count(block["input_bytes"], _M)
    runs: dict[str, RunRef] = {}
    for entry in _sequence(block["runs"], _M):
        run = _block(entry, _RUN_KEYS)
        run_id = _build_id(run["run_id"], _M)
        if run_id in runs:
            raise _refuse(_M)
        payloads = _hex64s(run["payload_digests"], _M)
        records = _hex64s(run["record_digests"], _M)
        entries = _count(run["entries"], _M)
        if entries != len(payloads) or entries != len(records):
            raise _refuse(_M)
        # Pagination v2 accounting: at most one probe per entry, and every provider call
        # is a data request or an issued probe.
        probes = _count(run["probes_issued"], _M)
        calls = _count(run["provider_calls"], _M)
        if probes > entries or calls != entries + probes:
            raise _refuse(_M)
        runs[run_id] = RunRef(
            run_id=run_id,
            plan_digest=_hex64(run["plan_digest"], _M),
            acquisition_mode=_member(
                run["acquisition_mode"], _ACQUISITION_MODES, malformed=_M, unsupported=_U
            ),
            entries=entries,
            payload_digests=payloads,
            record_digests=records,
        )
    return runs, ledger_digest


def _parse_source_versions(value: Any) -> tuple[str, str, dict[str, tuple[str, ...]]]:
    block = _block(value, _SOURCE_KEYS)
    source_schema = _fixed(
        block["source_schema_version"], SOURCE_SCHEMA_VERSION, malformed=_M, unsupported=_U
    )
    accepted = _nonempty(block["accepted_schemas_version"], _M)
    digests = _block(block["observed_schema_digests"], frozenset(_DATASETS))
    observed = {dataset: _hex64s(digests[dataset], _M) for dataset in _DATASETS}
    return source_schema, accepted, observed


def _parse_rule_document(value: Any) -> dict[str, Any]:
    """The rule as the manifest repeats it -- validated in shape here; bound in
    :func:`bind_configuration`, where the digest-bound copy is the authority."""
    block = _block(value, _RULE_KEYS)
    _nonempty(block["universe_rule_version"], _M)
    for name in ("decision_margin_seconds", "history_sessions", "addv_window_sessions"):
        _count(block[name], _M)
    for name in ("price_floor", "addv_floor"):
        try:
            Decimal(_text(block[name], _M))
        except ArithmeticError:
            raise _refuse(_M) from None
    for name in ("eligible_exchanges", "common_stock_categories"):
        _texts(block[name], _M)
    return block


def _parse_transformation(value: Any) -> tuple[dict[str, str], str, str, str, dict[str, Any]]:
    block = _block(value, _TRANSFORMATION_KEYS)
    versions = {
        name: _fixed(block[name], expected, malformed=_M, unsupported=_U)
        for name, expected in _FIXED_TRANSFORMATION_VERSIONS.items()
    }
    versions["evidence_version"] = _nonempty(block["evidence_version"], _M)
    calendar_version = _nonempty(block["calendar_version"], _M)
    commit = _commit(block["commit"], _M)
    configuration_digest = _hex64(block["configuration_digest"], _M)
    rule = _parse_rule_document(block["universe_rule"])
    return versions, calendar_version, commit, configuration_digest, rule


def _parse_per_dataset(value: Any, keys: frozenset[str], build: Any) -> dict[str, Any]:
    """A list with exactly one entry per Silver dataset, in any order."""
    out: dict[str, Any] = {}
    for entry in _sequence(value, _M):
        block = _block(entry, keys)
        dataset = _text(block["dataset"], _M)
        if dataset not in SILVER_ARTIFACTS or dataset in out:
            raise _refuse(_M)
        out[dataset] = build(dataset, block)
    if set(out) != set(_DATASETS):
        raise _refuse(_M)
    return out


def _parse_pagination(value: Any) -> PaginationSummary:
    block = _block(value, _PAGINATION_KEYS)
    for key, expected in _PAGINATION_FIXED.items():
        if block[key] != expected:
            raise _refuse(_U if key == "policy_version" else _M)
    groups = {}
    for name in ("groups_admitted", "groups_empty", "groups_probed"):
        # Genuinely dynamic: one count per (run, dataset, window) group label the build saw.
        groups[name] = {
            _nonempty(k, _M): _count(v, _M) for k, v in _mapping(block[name], _M).items()
        }
    try:
        return PaginationSummary(
            policy_version=PAGINATION_POLICY_VERSION,
            groups_admitted=groups["groups_admitted"],
            groups_empty=groups["groups_empty"],
            groups_probed=groups["groups_probed"],
        )
    except (TypeError, ValueError):
        raise _refuse(_M) from None


def _parse_identity(value: Any) -> dict[str, dict[str, int]]:
    blocks = _block(value, frozenset(_DATASETS))
    identity: dict[str, dict[str, int]] = {}
    for dataset in _DATASETS:
        block = _block(blocks[dataset], _IDENTITY_KEYS)
        identity[dataset] = {name: _count(block[name], _M) for name in sorted(_IDENTITY_KEYS)}
    return identity


def _validate_census(value: Any) -> None:
    seen: set[date] = set()
    for entry in _sequence(value, _M):
        block = _block(entry, _CENSUS_KEYS)
        day = _day(block["session_date"], _M)
        if day in seen:
            raise _refuse(_M)
        seen.add(day)
        for name in ("securities", "attribute_determinable", "attribute_unavailable", "members"):
            _count(block[name], _M)


def _validate_quality(value: Any) -> None:
    block = _block(value, _QUALITY_KEYS)
    _fixed(block["plan_version"], QUALITY_PLAN_VERSION, malformed=_M, unsupported=_U)
    # The check and severity names are the producer's closed vocabularies; the adapter holds them
    # to non-empty text and to the plan's arithmetic (run + not run, no overlap) rather than pin
    # a runtime module's members.
    run = _texts(block["checks_run"], _M)
    not_run = _texts(block["checks_not_run"], _M)
    if any(not name for name in (*run, *not_run)) or set(run) & set(not_run):
        raise _refuse(_M)
    if len(set(run)) != len(run) or len(set(not_run)) != len(not_run):
        raise _refuse(_M)
    for entry in _sequence(block["findings"], _M):
        finding = _block(entry, _FINDING_KEYS)
        _nonempty(finding["check"], _M)
        _nonempty(finding["severity"], _M)
        _nonempty(finding["scope"], _M)
        _count(finding["count"], _M)
        if finding["effective_from"] is not None:
            _instant(finding["effective_from"], _M)
    for security in _texts(block["restricted_securities"], _M):
        if not security:
            raise _refuse(_M)
    _boolean(block["build_blocking"], _M)


def _validate_restrictions(value: Any) -> None:
    for entry in _sequence(value, _M):
        block = _block(entry, _RESTRICTION_KEYS)
        _nonempty(block["security_id"], _M)
        _fixed(block["scope"], "security", malformed=_M, unsupported=_U)
        _nonempty(block["check"], _M)
        _nonempty(block["severity"], _M)
        _count(block["count"], _M)
        _instant(block["restricted_from"], _M)
        _days(block["sessions_affected"], _M)
        _nonempty(block["withheld"], _M)


def _validate_identity_contracts(value: Any) -> None:
    block = _block(value, _IDENTITY_CONTRACT_KEYS)
    contract = _block(block["action-event-identity"], _ACTION_EVENT_KEYS)
    if contract["contract_id"] != ACTIONS_IDENTITY_VERSION:
        raise _refuse(_U)
    _nonempty(contract["statement"], _M)
    _count(contract["action_keys_with_redelivery_gaps"], _M)
    _count(contract["adjusted_rows_withheld"], _M)


def _parse_outputs(value: Any) -> dict[str, OutputRef]:
    outputs: dict[str, OutputRef] = {}
    keys: set[str] = set()
    for entry in _sequence(value, _M):
        block = _block(entry, _OUTPUT_KEYS)
        name = _nonempty(block["artifact"], _M)
        key = _nonempty(block["key"], _M)
        if name in outputs or key in keys:
            raise _refuse(_M)
        keys.add(key)
        outputs[name] = OutputRef(
            artifact=name,
            key=key,
            sha256=_hex64(block["sha256"], _M),
            bytes=_count(block["bytes"], _M),
            rows=_count(block["rows"], _M),
            disposition=_member(
                block["disposition"], CONFIRMED_DISPOSITIONS, malformed=_M, unsupported=_U
            ),
        )
    return outputs


def parse_manifest(document: bytes) -> BuildManifestView:
    """Total parsing of the accepted build manifest. Every refusal is an :class:`AdapterDefect`.

    The schema is the one the accepted producer's ``build_manifest_document`` writes: closed keys
    at every depth; exact types; the fixed contract values (schema version, ``LICENSED``,
    ``PROVIDER_REALISTIC_PIT``, the source and transformation versions, the acquisition modes, the
    limitation tokens, the confirmed dispositions) held to the accepted vocabulary as
    ``MANIFEST_VALUE_UNSUPPORTED``; and every field validated whether or not the research path
    reads it. Genuinely dynamic maps -- the pagination group labels, the quality
    check names, the finding scopes -- are validated in type and shape, not in membership.
    """
    raw = _decode(
        document,
        ceiling=MAX_MANIFEST_BYTES,
        malformed=AdapterDefect.MANIFEST_MALFORMED,
        duplicate=AdapterDefect.MANIFEST_KEY_DUPLICATE,
    )
    top = _block(raw, _MANIFEST_KEYS)
    if top["schema_version"] != MANIFEST_CONTRACT:
        raise _refuse(AdapterDefect.MANIFEST_CONTRACT_MISMATCH)
    classification = _fixed(
        top["classification"], DataClassification.LICENSED.value, malformed=_M, unsupported=_U
    )
    resolved_profile = _fixed(
        top["resolved_profile"], RESOLVED_PROFILE.value, malformed=_M, unsupported=_U
    )
    build_id = _build_id(top["build_id"], _M)
    run_id = _hex64(top["run_id"], _M)
    as_of = _instant(top["as_of"], _M)
    completed_at = _instant(top["completed_at"], _M)
    runs, _ledger_digest = _parse_build_input(top["build_input"])
    source_schema, accepted_schemas, observed = _parse_source_versions(top["source_versions"])
    versions, calendar_version, commit, configuration_digest, rule = _parse_transformation(
        top["transformation"]
    )
    resolution = _parse_per_dataset(
        top["resolution_map"],
        _RESOLUTION_KEYS,
        lambda dataset, block: ResolutionCounts(
            dataset=dataset,
            p2=_count(block["P-2"], _M),
            p3_delivery_window=_count(block["P-3/DELIVERY_WINDOW"], _M),
            gated_evidence_ignored=_count(block["gated_evidence_ignored"], _M),
        ),
    )
    served = _parse_per_dataset(
        top["served"],
        _SERVED_KEYS,
        lambda dataset, block: ServedCounts(
            dataset=dataset,
            revisions_admitted=_count(block["revisions_admitted"], _M),
            revisions_superseded=_count(block["revisions_superseded"], _M),
            revisions_excluded_by_time=_count(block["revisions_excluded_by_time"], _M),
        ),
    )
    pagination = _parse_pagination(top["pagination"])
    identity = _parse_identity(top["identity"])
    _validate_census(top["census"])
    _days(top["undecidable_sessions"], _M)
    _validate_quality(top["quality"])
    for token in _texts(top["limitations"], _M):
        _member(token, _LIMITATION_TOKENS, malformed=_M, unsupported=_U)
    for security in _texts(top["spinoff_excluded_securities"], _M):
        if not security:
            raise _refuse(_M)
    _validate_restrictions(top["restrictions"])
    _validate_identity_contracts(top["identity_contracts"])
    if top["empty_reason"] is not None:
        _nonempty(top["empty_reason"], _M)
    outputs = _parse_outputs(top["outputs"])
    return BuildManifestView(
        manifest_digest=sha256_hex(document),
        build_id=build_id,
        run_id=run_id,
        classification=classification,
        as_of=as_of,
        completed_at=completed_at,
        resolved_profile=resolved_profile,
        calendar_version=calendar_version,
        configuration_digest=configuration_digest,
        commit=commit,
        source_schema_version=source_schema,
        accepted_schemas_version=accepted_schemas,
        observed_schema_digests=observed,
        transformation_versions=versions,
        identity=identity,
        pagination=pagination,
        served=served,
        resolution=resolution,
        universe_rule=rule,
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
        if ref is None or ref.disposition not in CONFIRMED_DISPOSITIONS:
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
            if delivered is None or row.provenance.payload_sha256 not in delivered.payload_digests:
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
# The configuration, bound to the build -- and carried through to the dataset
# ---------------------------------------------------------------------------

_CONFIGURATION_KEYS: Final = frozenset(
    {
        "accepted_schemas",
        "calendar",
        "evidence",
        "universe_rule",
        "decision_sessions",
        "as_of",
        "commit",
        "jump_ratio",
        "reconciliation_tolerance",
        "adjustment_policy",
        "adjustment_convention",
        "adjustment_derivation_version",
        "action_selection_version",
        "silver_normalization_version",
        "source_schema_version",
        "pagination_policy_version",
        "actions_identity_version",
    }
)
_SCHEMAS_KEYS: Final = frozenset({"version", "digests"})
_CALENDAR_KEYS: Final = frozenset({"version", "sessions"})
_SESSION_KEYS: Final = frozenset({"session_date", "open_at"})
_EVIDENCE_KEYS: Final = frozenset({"version", "items"})
_EVIDENCE_ITEM_KEYS: Final = frozenset(
    {"kind", "dataset", "row_key", "content_sha256", "instant", "evidence_digest"}
)
#: Configuration fields the manifest repeats under ``transformation``, by their name there.
_REPEATED_VERSIONS: Final = (
    "adjustment_policy",
    "adjustment_convention",
    "adjustment_derivation_version",
    "action_selection_version",
    "silver_normalization_version",
    "pagination_policy_version",
    "actions_identity_version",
)
_C: Final = AdapterDefect.CONFIGURATION_MALFORMED
_I: Final = AdapterDefect.CONFIGURATION_INCONSISTENT


def _configuration_block(value: Any, keys: frozenset[str]) -> dict[str, Any]:
    return _closed(value, keys, unknown=_C, malformed=_C)


@dataclass(frozen=True, slots=True, kw_only=True)
class BoundConfiguration:
    """The compiled build configuration, verified against one manifest, with the calendar and
    rule derived from it.

    ``document`` is the exact bytes whose canonical digest equals ``configuration_digest``; the
    calendar and rule were derived from those bytes and from nothing else -- the rule **as the
    build decided under it**, whatever its history; the 252-session requirement is applied where
    the research path consumes it, in :func:`build_dataset`. The object is the
    **only** way a calendar or a rule reaches :func:`build_dataset`, which re-derives both from
    ``document`` and refuses if the carried objects differ -- so a ``replace()`` with a look-alike
    calendar or an edited rule is refused, not read.
    """

    document: bytes
    configuration_digest: str
    calendar: SessionCalendar
    rule: UniverseRule
    as_of: datetime
    commit: str
    decision_sessions: tuple[date, ...]
    accepted_schemas_version: str
    accepted_schema_digests: dict[str, frozenset[str]]
    #: ``evidence.version`` -- the fact the manifest repeats as ``transformation.evidence_version``.
    evidence_version: str


def _parse_calendar(value: Any) -> SessionCalendar:
    block = _configuration_block(value, _CALENDAR_KEYS)
    version = _nonempty(block["version"], _C)
    entries = _sequence(block["sessions"], _C)
    if not entries:
        raise _refuse(_C)
    sessions: list[CalendarSession] = []
    for entry in entries:
        item = _configuration_block(entry, _SESSION_KEYS)
        try:
            sessions.append(
                CalendarSession(
                    session_date=_day(item["session_date"], _C),
                    open_at=_instant(item["open_at"], _C),
                )
            )
        except (TypeError, ValueError):
            raise _refuse(_C) from None
    try:
        return SessionCalendar(version=version, sessions=tuple(sessions))
    except (TypeError, ValueError):
        raise _refuse(_C) from None


def _rule_from_document(
    value: Any, *, malformed: AdapterDefect, require_history: bool
) -> UniverseRule:
    block = _closed(value, _RULE_KEYS, unknown=malformed, malformed=malformed)
    d = malformed
    history = _count(block["history_sessions"], d)
    if require_history and history != REQUIRED_HISTORY_SESSIONS:
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


def _validate_evidence(value: Any) -> str:
    block = _configuration_block(value, _EVIDENCE_KEYS)
    version = _nonempty(block["version"], _C)
    for entry in _sequence(block["items"], _C):
        item = _configuration_block(entry, _EVIDENCE_ITEM_KEYS)
        _nonempty(item["kind"], _C)
        _nonempty(item["dataset"], _C)
        _texts(item["row_key"], _C)
        _hex64(item["content_sha256"], _C)
        if item["instant"] is not None:
            _instant(item["instant"], _C)
        _hex64(item["evidence_digest"], _C)
    return version


def _parse_configuration(document: bytes) -> tuple[str, dict[str, Any]]:
    """Decode the compiled configuration and take its canonical digest over the object as
    delivered. Nothing is read from it and nothing is bound yet; the closed parse follows the
    digest check, so an unbound document is refused before a field of it is interpreted."""
    raw = _decode(document, ceiling=MAX_CONFIGURATION_BYTES, malformed=_C, duplicate=_C)
    top = _mapping(raw, _C)
    return sha256_hex(canonical_bytes(top)), top


def bind_configuration(document: bytes, *, manifest: BuildManifestView) -> BoundConfiguration:
    """The compiled build configuration, bound to ``manifest``.

    Order: the digest first -- a document whose canonical digest is not the manifest's
    ``configuration_digest`` is ``CONFIGURATION_UNBOUND`` before any field is read; then total
    parsing; then reconciliation of every fact the producer writes twice. **The digest-bound
    configuration is the authority**: a manifest that repeats the rule, the calendar version,
    ``as_of``, the commit, the accepted-schemas version, a transformation version or the
    evidence version differently, or that observed a schema digest the accepted set does not
    contain, is ``CONFIGURATION_INCONSISTENT`` -- whatever its own digest field says.
    """
    if type(manifest) is not BuildManifestView:
        raise TypeError("manifest must be a BuildManifestView")
    digest, raw = _parse_configuration(document)
    if digest != manifest.configuration_digest:
        raise _refuse(AdapterDefect.CONFIGURATION_UNBOUND)
    top = _configuration_block(raw, _CONFIGURATION_KEYS)
    schemas = _configuration_block(top["accepted_schemas"], _SCHEMAS_KEYS)
    schemas_version = _nonempty(schemas["version"], _C)
    accepted_digests = {
        _nonempty(dataset, _C): frozenset(_hex64s(digests, _C))
        for dataset, digests in _mapping(schemas["digests"], _C).items()
    }
    calendar = _parse_calendar(top["calendar"])
    evidence_version = _validate_evidence(top["evidence"])
    rule = _rule_from_document(
        top["universe_rule"], malformed=AdapterDefect.RULE_MALFORMED, require_history=False
    )
    decision_sessions = _days(top["decision_sessions"], _C)
    as_of = _instant(top["as_of"], _C)
    commit = _commit(top["commit"], _C)
    for name in ("jump_ratio", "reconciliation_tolerance"):
        try:
            Decimal(_text(top[name], _C))
        except ArithmeticError:
            raise _refuse(_C) from None
    versions = {name: _nonempty(top[name], _C) for name in _REPEATED_VERSIONS}
    source_schema = _nonempty(top["source_schema_version"], _C)
    # Reconciliation: the manifest's repeated fields against the digest-bound configuration.
    if calendar.version != manifest.calendar_version:
        raise _refuse(AdapterDefect.CALENDAR_VERSION_MISMATCH)
    if top["universe_rule"] != manifest.universe_rule:
        raise _refuse(_I)
    if as_of != manifest.as_of or commit != manifest.commit:
        raise _refuse(_I)
    if schemas_version != manifest.accepted_schemas_version:
        raise _refuse(_I)
    if source_schema != manifest.source_schema_version:
        raise _refuse(_I)
    if any(versions[name] != manifest.transformation_versions[name] for name in _REPEATED_VERSIONS):
        raise _refuse(_I)
    if evidence_version != manifest.transformation_versions["evidence_version"]:
        raise _refuse(_I)
    for dataset in _DATASETS:
        observed = set(manifest.observed_schema_digests[dataset])
        if not observed <= accepted_digests.get(dataset, frozenset()):
            raise _refuse(_I)
    return BoundConfiguration(
        document=bytes(document),
        configuration_digest=digest,
        calendar=calendar,
        rule=rule,
        as_of=as_of,
        commit=commit,
        decision_sessions=decision_sessions,
        accepted_schemas_version=schemas_version,
        accepted_schema_digests=accepted_digests,
        evidence_version=evidence_version,
    )


def calendar_from_configuration(document: bytes, *, manifest: BuildManifestView) -> SessionCalendar:
    """The calendar the build was compiled with -- :func:`bind_configuration`'s, for inspection.

    The close is **not** in the document -- ``Session`` carries ``open_at`` only -- so the
    exploratory path's regular-close approximation applies to every session, early-close days
    included. Dataset construction does not take this object; it takes the
    :class:`BoundConfiguration` it came from.
    """
    return bind_configuration(document, manifest=manifest).calendar


def rule_from_manifest(manifest: BuildManifestView) -> UniverseRule:
    """The rule as the manifest repeats it, for inspection only. Only 252 history sessions is
    accepted here. Dataset construction takes the digest-bound rule, never this one."""
    if type(manifest) is not BuildManifestView:
        raise TypeError("manifest must be a BuildManifestView")
    return _rule_from_document(
        manifest.universe_rule, malformed=AdapterDefect.RULE_MALFORMED, require_history=True
    )


# ---------------------------------------------------------------------------
# The dataset and its publication
# ---------------------------------------------------------------------------


def _verify_bound(configuration: BoundConfiguration, *, manifest: BuildManifestView) -> None:
    """The carried objects are the ones the bytes derive -- re-derived here, not trusted."""
    if configuration.configuration_digest != manifest.configuration_digest:
        raise _refuse(_I)
    rebound = bind_configuration(configuration.document, manifest=manifest)
    if (
        rebound.configuration_digest != configuration.configuration_digest
        or rebound.calendar != configuration.calendar
        or rebound.rule != configuration.rule
        or rebound.as_of != configuration.as_of
        or rebound.commit != configuration.commit
        or rebound.decision_sessions != configuration.decision_sessions
        or rebound.accepted_schemas_version != configuration.accepted_schemas_version
        or rebound.accepted_schema_digests != configuration.accepted_schema_digests
        or rebound.evidence_version != configuration.evidence_version
    ):
        raise _refuse(_I)


def build_dataset(
    assembly: LayerAssembly,
    *,
    configuration: BoundConfiguration,
    as_of: datetime | None = None,
) -> ExploratoryDataset:
    """AS_DATED resolution, the accepted membership clauses, benchmark A -- over the assembled
    layer, under the **bound** configuration and nothing else.

    ``configuration`` must be bound to this assembly's manifest (same ``configuration_digest``),
    and its calendar and rule are re-derived from its bytes before use: a carried calendar with
    the same version but other sessions or opens, or a carried rule with 252 sessions but another
    parameter, is ``CONFIGURATION_INCONSISTENT``; a faithfully bound rule without 252 history
    sessions is ``RULE_HISTORY_NOT_ACCEPTED`` -- the research path's requirement, applied to the
    build's own rule. ``as_of`` is the research override: it defaults
    to the build's, a later instant is allowed, an earlier or naive one is ``AS_OF_BEFORE_BUILD``
    -- a research parameter, kept distinct from inconsistent build metadata.
    """
    if type(assembly) is not LayerAssembly:
        raise TypeError("assembly must be a LayerAssembly")
    if type(configuration) is not BoundConfiguration:
        raise TypeError("configuration must be a BoundConfiguration")
    manifest = assembly.manifest
    _verify_bound(configuration, manifest=manifest)
    calendar, rule = configuration.calendar, configuration.rule
    if rule.history_sessions != REQUIRED_HISTORY_SESSIONS:
        raise _refuse(AdapterDefect.RULE_HISTORY_NOT_ACCEPTED)
    instant = manifest.as_of if as_of is None else as_of
    if type(instant) is not datetime or instant.tzinfo is None or instant < manifest.as_of:
        raise _refuse(AdapterDefect.AS_OF_BEFORE_BUILD)
    resolved = resolve_as_dated(assembly.layer, calendar=calendar)
    membership = decide_membership_all(resolved, rule=rule, calendar=calendar, as_of=instant)
    benchmark = build_benchmark_a(resolved, membership, calendar=calendar)
    return ExploratoryDataset(
        layer=resolved,
        membership=membership,
        calendar=calendar,
        benchmark=benchmark,
        as_of=instant,
        source_manifest_digest=manifest.manifest_digest,
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
    "ADJUSTMENT_CONVENTION",
    "ADJUSTMENT_DERIVATION_VERSION",
    "ADJUSTMENT_POLICY",
    "CONFIRMED_DISPOSITIONS",
    "MANIFEST_CONTRACT",
    "MAX_ARTIFACT_BYTES",
    "MAX_CONFIGURATION_BYTES",
    "MAX_MANIFEST_BYTES",
    "QUALITY_PLAN_VERSION",
    "REQUIRED_HISTORY_SESSIONS",
    "SILVER_ARTIFACTS",
    "SOURCE_SCHEMA_VERSION",
    "AdapterDefect",
    "AdapterError",
    "BoundConfiguration",
    "BuildManifestView",
    "LayerAssembly",
    "OutputRef",
    "ResolutionCounts",
    "RunRef",
    "ServedCounts",
    "assemble_layer",
    "bind_configuration",
    "build_dataset",
    "calendar_from_configuration",
    "parse_manifest",
    "parse_silver_artifact",
    "publish_from_build",
    "rule_from_manifest",
    "sha256_hex",
]
