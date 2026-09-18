"""PR #113 review correction 1 -- targeted regressions, written before the correction.

Two findings from source inspection of ``9fb52b5e``: (1) ``build_dataset`` accepted an independently
supplied calendar and rule, checked only by version and by ``history_sessions == 252``, so the
configuration binding ``calendar_from_configuration`` verified did not survive to dataset
construction; (2) ``parse_manifest`` closed only the top level -- nested blocks, ``completed_at``,
``build_input.runs[*].entries`` and the fixed contract values went unvalidated. Synthetic artifacts
from the accepted producer only.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any, Final

import pytest

from fixtures import m0_build_artifacts as ba
from fixtures import m0_exploratory as fx
from kalpamani.data.contracts.canonical import canonical_bytes
from kalpamani.data.exploratory import adapter
from kalpamani.data.exploratory.adapter import (
    AdapterDefect,
    AdapterError,
    assemble_layer,
    build_dataset,
    parse_manifest,
)

pytestmark = pytest.mark.unit

# Defect names, resolved at assertion time so the module collects (and fails test by test) on the
# reviewed head, where two of these members do not exist yet.
FIELD: Final = "MANIFEST_FIELD_MALFORMED"
UNKNOWN: Final = "MANIFEST_KEY_UNKNOWN"
MALFORMED: Final = "MANIFEST_MALFORMED"
UNSUPPORTED: Final = "MANIFEST_VALUE_UNSUPPORTED"


@pytest.fixture(scope="module")
def build() -> ba.BuildArtifacts:
    return ba.m0_build()


@pytest.fixture(scope="module")
def bound(build: ba.BuildArtifacts) -> Any:
    manifest = parse_manifest(build.manifest)
    return adapter.bind_configuration(build.configuration, manifest=manifest)


def mutate(manifest: bytes, edit: Any) -> bytes:
    document = json.loads(manifest)
    edit(document)
    return canonical_bytes(document)


def refusal(callable_: Any, *args: Any, **kwargs: Any) -> AdapterDefect:
    with pytest.raises(AdapterError) as caught:
        callable_(*args, **kwargs)
    return caught.value.defect


def _set(path: tuple[Any, ...], value: Any) -> Any:
    def edit(d: dict[str, Any]) -> None:
        target: Any = d
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = value

    return edit


def _drop(path: tuple[Any, ...]) -> Any:
    def edit(d: dict[str, Any]) -> None:
        target: Any = d
        for step in path[:-1]:
            target = target[step]
        del target[path[-1]]

    return edit


# --- finding 1: configuration binding through dataset construction ---------------------------


def test_r1_dataset_construction_takes_only_the_bound_configuration() -> None:
    """No parallel path: the dataset is built from the digest-bound configuration, never from a
    calendar or a rule a caller supplies on its own."""
    parameters = set(inspect.signature(build_dataset).parameters)
    assert parameters == {"assembly", "configuration", "as_of"}
    assert "calendar" not in parameters and "rule" not in parameters
    assert callable(adapter.bind_configuration)


def test_r1_the_valid_producer_round_trip_is_retained(build: ba.BuildArtifacts, bound: Any) -> None:
    manifest = parse_manifest(build.manifest)
    assembly = assemble_layer(manifest, build.artifacts)
    dataset = build_dataset(assembly, configuration=bound)
    assert dataset.calendar == build.calendar
    assert bound.rule == fx.rule() and bound.rule.history_sessions == 252
    assert dataset.as_of == manifest.as_of == bound.as_of
    assert bound.configuration_digest == manifest.configuration_digest
    # The read-only calendar view is the bound calendar, not a parallel construction.
    assert (
        adapter.calendar_from_configuration(build.configuration, manifest=manifest)
        == bound.calendar
    )


def test_r1_a_calendar_with_the_same_version_but_different_content_is_refused(
    build: ba.BuildArtifacts, bound: Any
) -> None:
    manifest = parse_manifest(build.manifest)
    assembly = assemble_layer(manifest, build.artifacts)
    calendar = bound.calendar
    fewer = replace(calendar, sessions=calendar.sessions[:-1])
    assert (
        refusal(build_dataset, assembly, configuration=replace(bound, calendar=fewer))
        is AdapterDefect.CONFIGURATION_INCONSISTENT
    )
    last = calendar.sessions[-1]
    shifted = replace(
        calendar,
        sessions=(
            *calendar.sessions[:-1],
            replace(last, open_at=last.open_at + timedelta(hours=1)),
        ),
    )
    assert shifted.version == calendar.version
    assert (
        refusal(build_dataset, assembly, configuration=replace(bound, calendar=shifted))
        is AdapterDefect.CONFIGURATION_INCONSISTENT
    )


@pytest.mark.parametrize(
    "field, value",
    [
        ("price_floor", Decimal("6")),
        ("addv_floor", Decimal("2000000")),
        ("addv_window_sessions", 21),
        ("decision_margin", timedelta(minutes=31)),
    ],
)
def test_r1_a_rule_keeping_252_sessions_but_changing_another_parameter_is_refused(
    build: ba.BuildArtifacts, bound: Any, field: str, value: Any
) -> None:
    manifest = parse_manifest(build.manifest)
    assembly = assemble_layer(manifest, build.artifacts)
    changed = replace(bound.rule, **{field: value})
    assert changed.history_sessions == 252
    assert (
        refusal(build_dataset, assembly, configuration=replace(bound, rule=changed))
        is AdapterDefect.CONFIGURATION_INCONSISTENT
    )


INCONSISTENT: Final = "CONFIGURATION_INCONSISTENT"


def _rule_field(name: str, value: Any) -> Any:
    return lambda d: d["transformation"]["universe_rule"].__setitem__(name, value)


@pytest.mark.parametrize(
    "edit, expected",
    [
        (_rule_field("price_floor", "6"), INCONSISTENT),
        (_rule_field("decision_margin_seconds", 1801), INCONSISTENT),
        (
            _set(("transformation", "calendar_version"), "another-calendar-v1"),
            "CALENDAR_VERSION_MISMATCH",
        ),
        (_set(("transformation", "commit"), "1" * 40), INCONSISTENT),
        (_set(("as_of",), "2026-09-22T00:00:00+00:00"), INCONSISTENT),
        (_set(("source_versions", "accepted_schemas_version"), "other-schemas-v9"), INCONSISTENT),
        (
            lambda d: d["source_versions"]["observed_schema_digests"]["actions"].append("a" * 64),
            INCONSISTENT,
        ),
    ],
    ids=[
        "rule price_floor",
        "rule decision_margin",
        "calendar_version",
        "commit",
        "as_of",
        "accepted_schemas_version",
        "observed digest not accepted",
    ],
)
def test_r1_a_manifest_field_that_disagrees_with_the_bound_configuration_is_refused(
    build: ba.BuildArtifacts, edit: Any, expected: str
) -> None:
    """The producer writes the same facts twice -- once in the manifest, once in the compiled
    configuration it digests. The digest-bound configuration is the authority; a manifest that
    repeats a fact differently is inconsistent, whatever its digest field says. (A repeated field
    the contract fixes outright -- a policy or a version string -- is refused earlier, at parse,
    as MANIFEST_VALUE_UNSUPPORTED; see the parse cases.)"""
    manifest = parse_manifest(mutate(build.manifest, edit))
    assert (
        refusal(adapter.bind_configuration, build.configuration, manifest=manifest)
        is AdapterDefect[expected]
    )


def test_r1_the_research_as_of_override_is_distinct_from_inconsistent_metadata(
    build: ba.BuildArtifacts, bound: Any
) -> None:
    manifest = parse_manifest(build.manifest)
    assembly = assemble_layer(manifest, build.artifacts)
    later = bound.as_of + timedelta(days=3)
    dataset = build_dataset(assembly, configuration=bound, as_of=later)
    assert dataset.as_of == later  # the supported research override: a later instant
    assert (
        refusal(
            build_dataset, assembly, configuration=bound, as_of=bound.as_of - timedelta(seconds=1)
        )
        is AdapterDefect.AS_OF_BEFORE_BUILD
    )
    assert (
        refusal(build_dataset, assembly, configuration=bound, as_of=later.replace(tzinfo=None))
        is AdapterDefect.AS_OF_BEFORE_BUILD
    )
    # A configuration bound to a different build is not this build's.
    other = replace(bound, configuration_digest="f" * 64)
    assert (
        refusal(build_dataset, assembly, configuration=other)
        is AdapterDefect.CONFIGURATION_INCONSISTENT
    )


def test_r1_a_configuration_document_that_is_not_the_producers_shape_is_refused(
    build: ba.BuildArtifacts,
) -> None:
    manifest = parse_manifest(build.manifest)
    document = json.loads(build.configuration)
    document["extra"] = 1
    assert (
        refusal(adapter.bind_configuration, canonical_bytes(document), manifest=manifest)
        is AdapterDefect.CONFIGURATION_UNBOUND
    )  # the digest no longer matches: refused before any field is read


# --- finding 2: complete manifest validation ----------------------------------------------------


MANIFEST_CASES: Final[list[tuple[str, Any, str]]] = [
    ("build_input extra key", _set(("build_input", "extra"), 1), UNKNOWN),
    ("build_input missing objects_read", _drop(("build_input", "objects_read")), MALFORMED),
    ("build_input.input_bytes str", _set(("build_input", "input_bytes"), "0"), FIELD),
    ("ledger_digest not hex64", _set(("build_input", "ledger_digest"), "abc"), FIELD),
    ("runs[0] extra key", _set(("build_input", "runs", 0, "extra"), 1), UNKNOWN),
    ("runs[0].entries mismatch", _set(("build_input", "runs", 0, "entries"), 1), FIELD),
    ("runs[0].entries negative", _set(("build_input", "runs", 0, "entries"), -1), FIELD),
    ("runs[0].entries str", _set(("build_input", "runs", 0, "entries"), "12669"), FIELD),
    (
        "runs[0].acquisition_mode unsupported",
        _set(("build_input", "runs", 0, "acquisition_mode"), "BULK"),
        UNSUPPORTED,
    ),
    (
        "runs[0].record_digests bad",
        _set(("build_input", "runs", 0, "record_digests"), ["zz"]),
        FIELD,
    ),
    ("completed_at naive", _set(("completed_at",), "2026-09-21T01:00:00"), FIELD),
    ("completed_at int", _set(("completed_at",), 1), FIELD),
    ("completed_at garbage", _set(("completed_at",), "yesterday"), FIELD),
    ("source_versions extra key", _set(("source_versions", "extra"), 1), UNKNOWN),
    (
        "source_schema_version unsupported",
        _set(("source_versions", "source_schema_version"), "sharadar-csv-production-v9"),
        UNSUPPORTED,
    ),
    (
        "observed digests fourth dataset",
        _set(("source_versions", "observed_schema_digests", "funds"), []),
        UNKNOWN,
    ),
    ("transformation extra key", _set(("transformation", "extra"), 1), UNKNOWN),
    ("transformation missing key", _drop(("transformation", "quality_plan_version")), MALFORMED),
    (
        "adjustment_policy unsupported",
        _set(("transformation", "adjustment_policy"), "TOTAL_RETURN"),
        UNSUPPORTED,
    ),
    (
        "adjustment_convention unsupported",
        _set(("transformation", "adjustment_convention"), "BACKWARD"),
        UNSUPPORTED,
    ),
    (
        "adjustment_derivation_version unsupported",
        _set(("transformation", "adjustment_derivation_version"), "sharadar-adjusted-bars-v9"),
        UNSUPPORTED,
    ),
    (
        "silver_normalization_version unsupported",
        _set(("transformation", "silver_normalization_version"), "sharadar-silver-v9"),
        UNSUPPORTED,
    ),
    (
        "pagination policy_version unsupported",
        _set(("pagination", "policy_version"), "synthetic"),
        UNSUPPORTED,
    ),
    (
        "pagination fixed statement altered",
        _set(("pagination", "establishes"), ["vendor completeness"]),
        FIELD,
    ),
    (
        "quality plan_version unsupported",
        _set(("quality", "plan_version"), "other-plan-v1"),
        UNSUPPORTED,
    ),
    (
        "restriction scope unsupported",
        lambda d: d["restrictions"].append(
            {
                "security_id": "x",
                "scope": "build",
                "check": "c",
                "severity": "BLOCKING",
                "count": 1,
                "restricted_from": "2026-01-01T00:00:00+00:00",
                "sessions_affected": [],
                "withheld": "w",
            }
        ),
        UNSUPPORTED,
    ),
    ("census duplicate session", lambda d: d["census"].append(dict(d["census"][0])), FIELD),
    (
        "quality checks overlap",
        lambda d: d["quality"].__setitem__("checks_not_run", d["quality"]["checks_run"][:1]),
        FIELD,
    ),
    (
        "outputs duplicated key",
        lambda d: d["outputs"].append({**d["outputs"][1], "artifact": "silver-other"}),
        FIELD,
    ),
    ("commit short", _set(("transformation", "commit"), "abc"), FIELD),
    ("universe_rule extra key", _set(("transformation", "universe_rule", "extra"), 1), UNKNOWN),
    (
        "universe_rule history str",
        _set(("transformation", "universe_rule", "history_sessions"), "252"),
        FIELD,
    ),
    ("resolved_profile unsupported", _set(("resolved_profile",), "PUBLIC_PIT"), UNSUPPORTED),
    ("classification unsupported", _set(("classification",), "CONTROL"), UNSUPPORTED),
    ("build_id malformed", _set(("build_id",), "has space"), FIELD),
    ("run_id not hex64", _set(("run_id",), "synthetic-run"), FIELD),
    ("resolution_map entry extra key", _set(("resolution_map", 0, "extra"), 1), UNKNOWN),
    ("served entry missing key", _drop(("served", 0, "revisions_superseded")), MALFORMED),
    ("served count negative", _set(("served", 0, "revisions_admitted"), -1), FIELD),
    ("pagination extra key", _set(("pagination", "extra"), 1), UNKNOWN),
    ("pagination groups value str", _set(("pagination", "groups_admitted", "stocks"), "3"), FIELD),
    ("identity fourth dataset", _set(("identity", "funds"), {}), UNKNOWN),
    ("identity.tickers extra key", _set(("identity", "tickers", "extra"), 1), UNKNOWN),
    ("census entry missing members", _drop(("census", 0, "members")), MALFORMED),
    ("census entry bad date", _set(("census", 0, "session_date"), "not-a-date"), FIELD),
    ("undecidable_sessions bad date", _set(("undecidable_sessions",), ["not-a-date"]), FIELD),
    ("quality extra key", _set(("quality", "extra"), 1), UNKNOWN),
    ("quality.build_blocking str", _set(("quality", "build_blocking"), "no"), FIELD),
    ("quality.checks_run not list", _set(("quality", "checks_run"), "all"), FIELD),
    ("limitations unsupported token", _set(("limitations",), ["BOGUS"]), UNSUPPORTED),
    ("limitations not list", _set(("limitations",), "SINGLE_SOURCE_UNVERIFIED"), FIELD),
    ("spinoff_excluded_securities ints", _set(("spinoff_excluded_securities",), [1]), FIELD),
    ("restrictions entry malformed", _set(("restrictions",), [{"security_id": "x"}]), MALFORMED),
    ("identity_contracts extra key", _set(("identity_contracts", "extra"), {}), UNKNOWN),
    (
        "identity_contracts count str",
        _set(("identity_contracts", "action-event-identity", "adjusted_rows_withheld"), "0"),
        FIELD,
    ),
    ("empty_reason int", _set(("empty_reason",), 5), FIELD),
    (
        "outputs entry disposition unsupported",
        _set(("outputs", 0, "disposition"), "NAME_OCCUPIED"),
        UNSUPPORTED,
    ),
    ("outputs entry key empty", _set(("outputs", 0, "key"), ""), FIELD),
    ("outputs entry rows str", _set(("outputs", 0, "rows"), "23"), FIELD),
    ("outputs duplicated artifact", lambda d: d["outputs"].append(dict(d["outputs"][0])), FIELD),
]


@pytest.mark.parametrize(
    "label, edit, expected", MANIFEST_CASES, ids=[c[0] for c in MANIFEST_CASES]
)
def test_r2_every_nested_manifest_defect_is_a_closed_refusal(
    build: ba.BuildArtifacts, label: str, edit: Any, expected: str
) -> None:
    assert refusal(parse_manifest, mutate(build.manifest, edit)) is AdapterDefect[expected], label


def test_r2_valid_producer_manifests_remain_accepted(build: ba.BuildArtifacts) -> None:
    manifest = parse_manifest(build.manifest)
    assert manifest.completed_at == ba.COMPLETED_AT
    assert manifest.runs and all(
        run.entries == len(run.payload_digests) for run in manifest.runs.values()
    )
    scenario_manifest, artifacts, configuration, report = ba.scenario_build()
    view = parse_manifest(scenario_manifest)
    assert view.resolved_profile == "PROVIDER_REALISTIC_PIT" and view.classification == "LICENSED"
    assert set(view.identity) == {"tickers", "stocks", "actions"}
    # The scenario's configuration binds to its manifest exactly as the producer wrote both.
    scenario_bound = adapter.bind_configuration(configuration, manifest=view)
    assert scenario_bound.calendar.version == view.calendar_version
    assert scenario_bound.rule.history_sessions == 3  # bound, and refused for research below
    assembly = assemble_layer(view, artifacts)
    assert (
        refusal(build_dataset, assembly, configuration=scenario_bound)
        is AdapterDefect.RULE_HISTORY_NOT_ACCEPTED
    )
    assert report.status.value == "COMPLETED"


def test_the_pinned_fixed_values_are_the_producers() -> None:
    """The adapter may not import the producer's runtime modules, so it pins the fixed contract
    values it cannot reach; this test holds every pin to the module that owns the value."""
    from kalpamani.data.production.sharadar import build_manifest, gold, locator, processing

    assert adapter.MANIFEST_CONTRACT == build_manifest.MANIFEST_SCHEMA_VERSION
    assert adapter.SOURCE_SCHEMA_VERSION == processing.SOURCE_SCHEMA_VERSION
    assert adapter.QUALITY_PLAN_VERSION == gold.QUALITY_PLAN_VERSION
    assert adapter.ADJUSTMENT_POLICY is gold.ADJUSTMENT_POLICY
    assert adapter.ADJUSTMENT_CONVENTION is gold.ADJUSTMENT_CONVENTION
    assert adapter.ADJUSTMENT_DERIVATION_VERSION == gold.ADJUSTMENT_DERIVATION_VERSION
    assert adapter.CONFIRMED_DISPOSITIONS == frozenset(m.value for m in locator.PayloadDisposition)
    assert {"WRITTEN", "ALREADY_PRESENT"} == adapter.CONFIRMED_DISPOSITIONS
