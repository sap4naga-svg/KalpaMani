"""The exploratory adapter (ADR-0051 §12): an admitted production build's manifest and Silver
artifacts, as bytes, into an ``ExploratoryPublication`` and through the M0 runner.

The ten acceptance cases of the readiness packet (`m0-readiness-2026-09-16/READINESS-PACKET.md`
§4), on synthetic artifacts produced by the **accepted** producer. Nothing here reads a store,
touches licensed data, or selects an owner decision.
"""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures import m0_build_artifacts as ba
from fixtures import m0_exploratory as fx
from kalpamani.data.contracts.canonical import canonical_bytes
from kalpamani.data.curate import publication as a1
from kalpamani.data.exploratory import adapter, m0
from kalpamani.data.exploratory.adapter import (
    AdapterDefect,
    AdapterError,
    assemble_layer,
    bind_configuration,
    build_dataset,
    calendar_from_configuration,
    parse_manifest,
    parse_silver_artifact,
    publish_from_build,
    rule_from_manifest,
)
from kalpamani.data.exploratory.admission import AdmissionOutcome, admit
from kalpamani.data.exploratory.contracts import ExploratoryInputSet, ExploratoryPublication
from kalpamani.data.exploratory.dataset import publish
from kalpamani.data.exploratory.m0 import (
    M0_RESEARCH_SPECIFICATION,
    M0_SYNTHETIC_FIXTURE,
    DataKind,
    run_m0,
)
from kalpamani.data.exploratory.vocabulary import ExploratoryLimitation
from kalpamani.strategies.breakout import long as breakout_long

pytestmark = pytest.mark.unit

LIMITATIONS: Final = frozenset(ExploratoryLimitation)
REPO_ROOT: Final = Path(__file__).resolve().parents[2]
SRC: Final = REPO_ROOT / "src" / "kalpamani"


@pytest.fixture(scope="module")
def build() -> ba.BuildArtifacts:
    return ba.m0_build()


@pytest.fixture(scope="module")
def scenario() -> tuple[bytes, dict[str, bytes], bytes, Any]:
    return ba.scenario_build()


def mutate_manifest(manifest: bytes, edit: Any) -> bytes:
    document = json.loads(manifest)
    edit(document)
    return canonical_bytes(document)


def keyed(layer: Any) -> Any:
    """The same layer with every dataset's rows in row-key order (the artifact order)."""
    from kalpamani.data.production.sharadar.silver import SilverDataset

    def sort(ds: SilverDataset) -> SilverDataset:
        return replace(ds, rows=tuple(sorted(ds.rows, key=lambda r: r.row_key)))

    return replace(
        layer, tickers=sort(layer.tickers), stocks=sort(layer.stocks), actions=sort(layer.actions)
    )


def refusal(callable_: Any, *args: Any, **kwargs: Any) -> AdapterDefect:
    with pytest.raises(AdapterError) as caught:
        callable_(*args, **kwargs)
    return caught.value.defect


# --- 1. round trip: the adapted build equals the direct path -------------------------------------


def test_case_1_the_adapted_build_runs_m0_identically_to_the_direct_path(
    build: ba.BuildArtifacts,
) -> None:
    manifest = parse_manifest(build.manifest)
    assembly = assemble_layer(manifest, build.artifacts)
    bound = bind_configuration(build.configuration, manifest=manifest)
    rule = bound.rule
    assert bound.calendar == build.calendar
    assert rule == rule_from_manifest(manifest)
    assert rule.history_sessions == 252 == m0.HISTORY_SESSIONS
    adapted = build_dataset(assembly, configuration=bound)
    # The artifacts hold every served revision in key order; the direct path over the same
    # rows in the same order is the reference (the exploratory layer digest is order-sensitive).
    direct = fx.dataset_from(keyed(build.layer), build.calendar)
    # The layers agree row for row (the artifacts hold every served revision).
    for name in ("tickers", "stocks", "actions"):
        left = assembly.layer.by_dataset(name).rows
        right = build.layer.by_dataset(name).rows
        assert len(left) == len(right)
        assert sorted((r.row_key, r.revision_sequence, r.content_sha256) for r in left) == sorted(
            (r.row_key, r.revision_sequence, r.content_sha256) for r in right
        )
        for r in left:
            assert r.provenance.run_id in manifest.runs
    # The resolution, membership and benchmark agree exactly.
    assert adapted.layer.digest == direct.layer.digest
    assert adapted.membership.rows == direct.membership.rows
    assert adapted.benchmark.digest == direct.benchmark.digest
    # The dataset digests differ only through the source manifest digest, which the adapter
    # binds to the real manifest and the direct fixture to its own identity.
    assert (
        adapted.source_manifest_digest == manifest.manifest_digest != direct.source_manifest_digest
    )
    assert (
        replace(
            adapted, source_manifest_digest=direct.source_manifest_digest, cache={}
        ).content_digest
        == direct.content_digest
    )
    publication = publish_from_build(
        adapted, publication_id="synthetic-adapter-pub-01", limitations=LIMITATIONS
    )
    inputs = ExploratoryInputSet(publications=(publication,))
    result = run_m0(
        specification=M0_RESEARCH_SPECIFICATION,
        inputs=inputs,
        dataset=adapted,
        config=M0_SYNTHETIC_FIXTURE,
        data_kind=DataKind.SYNTHETIC,
    )
    direct_result = run_m0(
        specification=M0_RESEARCH_SPECIFICATION,
        inputs=ExploratoryInputSet(
            publications=(
                publish(direct, publication_id="synthetic-adapter-pub-01", limitations=LIMITATIONS),
            )
        ),
        dataset=direct,
        config=M0_SYNTHETIC_FIXTURE,
        data_kind=DataKind.SYNTHETIC,
    )
    assert result.trial_digest == direct_result.trial_digest
    assert [ledger.document()["trades"] for ledger in result.ledgers] == [
        ledger.document()["trades"] for ledger in direct_result.ledgers
    ]
    assert result.document()["label"] == "SYNTHETIC / EXPLORATORY_HINDSIGHT"
    assert assembly.gap_instants_unknown == 0
    # And the engine itself does not care about row order: the fixture's scripted order yields
    # the same trades (its layer digest differs only by ordering).
    unsorted = fx.dataset_from(build.layer, build.calendar)
    unsorted_result = run_m0(
        specification=M0_RESEARCH_SPECIFICATION,
        inputs=ExploratoryInputSet(
            publications=(
                publish(
                    unsorted, publication_id="synthetic-adapter-pub-01", limitations=LIMITATIONS
                ),
            )
        ),
        dataset=unsorted,
        config=M0_SYNTHETIC_FIXTURE,
        data_kind=DataKind.SYNTHETIC,
    )
    assert [ledger.document()["trades"] for ledger in unsorted_result.ledgers] == [
        ledger.document()["trades"] for ledger in result.ledgers
    ]


# --- 2. digest discipline ----------------------------------------------------------------------


def test_case_2_a_flipped_byte_or_a_wrong_byte_count_is_refused_before_parsing(
    build: ba.BuildArtifacts,
) -> None:
    manifest = parse_manifest(build.manifest)
    ref = manifest.outputs["silver-actions"]
    content = build.artifacts["silver-actions"]
    flipped = bytearray(content)
    flipped[len(flipped) // 2] ^= 0x01
    assert (
        refusal(
            parse_silver_artifact,
            "silver-actions",
            bytes(flipped),
            expected_sha256=ref.sha256,
            expected_bytes=ref.bytes,
        )
        is AdapterDefect.ARTIFACT_DIGEST_MISMATCH
    )
    assert (
        refusal(
            parse_silver_artifact,
            "silver-actions",
            content + b" ",
            expected_sha256=ref.sha256,
            expected_bytes=ref.bytes,
        )
        is AdapterDefect.ARTIFACT_BYTES_MISMATCH
    )
    swapped = dict(build.artifacts)
    swapped["silver-actions"] = bytes(flipped)
    assert refusal(assemble_layer, manifest, swapped) is AdapterDefect.ARTIFACT_DIGEST_MISMATCH


# --- 3. manifest closedness --------------------------------------------------------------------


def test_case_3_the_manifest_is_parsed_totally(build: ba.BuildArtifacts) -> None:
    def add_key(d: dict[str, Any]) -> None:
        d["extra"] = 1

    def wrong_as_of(d: dict[str, Any]) -> None:
        d["as_of"] = 20260921

    def naive_as_of(d: dict[str, Any]) -> None:
        d["as_of"] = "2026-09-21T00:00:00"

    def other_version(d: dict[str, Any]) -> None:
        d["schema_version"] = "kalpamani-production-build-manifest/v3"

    def drop_key(d: dict[str, Any]) -> None:
        del d["served"]

    assert (
        refusal(parse_manifest, mutate_manifest(build.manifest, add_key))
        is AdapterDefect.MANIFEST_KEY_UNKNOWN
    )
    assert (
        refusal(parse_manifest, mutate_manifest(build.manifest, wrong_as_of))
        is AdapterDefect.MANIFEST_FIELD_MALFORMED
    )
    assert (
        refusal(parse_manifest, mutate_manifest(build.manifest, naive_as_of))
        is AdapterDefect.MANIFEST_FIELD_MALFORMED
    )
    assert (
        refusal(parse_manifest, mutate_manifest(build.manifest, other_version))
        is AdapterDefect.MANIFEST_CONTRACT_MISMATCH
    )
    assert (
        refusal(parse_manifest, mutate_manifest(build.manifest, drop_key))
        is AdapterDefect.MANIFEST_MALFORMED
    )
    duplicate = build.manifest[:-1] + b',"build_id":"twice"}'
    assert refusal(parse_manifest, duplicate) is AdapterDefect.MANIFEST_KEY_DUPLICATE
    assert refusal(parse_manifest, b"\xff\xfe") is AdapterDefect.MANIFEST_MALFORMED
    assert refusal(parse_manifest, b"[]") is AdapterDefect.MANIFEST_MALFORMED
    assert refusal(parse_manifest, "text") is AdapterDefect.MANIFEST_MALFORMED


# --- 4. missing / unlisted artifacts, excluded revisions ---------------------------------------


def test_case_4_missing_unlisted_artifacts_and_excluded_revisions_are_refused(
    build: ba.BuildArtifacts,
) -> None:
    manifest = parse_manifest(build.manifest)
    without = {k: v for k, v in build.artifacts.items() if k != "silver-stocks"}
    assert refusal(assemble_layer, manifest, without) is AdapterDefect.DATASET_MISSING

    def unlist(d: dict[str, Any]) -> None:
        d["outputs"] = [o for o in d["outputs"] if o["artifact"] != "silver-tickers"]

    assert (
        refusal(
            assemble_layer, parse_manifest(mutate_manifest(build.manifest, unlist)), build.artifacts
        )
        is AdapterDefect.ARTIFACT_NOT_IN_MANIFEST
    )

    def not_confirmed(d: dict[str, Any]) -> None:
        for o in d["outputs"]:
            if o["artifact"] == "silver-tickers":
                o["disposition"] = "NAME_OCCUPIED"

    # An unconfirmed disposition is not a value the producer writes into a published manifest
    # (ADR-0040: WRITTEN or ALREADY_PRESENT), so it is refused at parse, before assembly.
    assert (
        refusal(parse_manifest, mutate_manifest(build.manifest, not_confirmed))
        is AdapterDefect.MANIFEST_VALUE_UNSUPPORTED
    )
    # And a view forged with such a disposition is still refused at assembly.
    forged = replace(
        manifest,
        outputs={
            **manifest.outputs,
            "silver-tickers": replace(manifest.outputs["silver-tickers"], disposition="PENDING"),
        },
    )
    assert (
        refusal(assemble_layer, forged, build.artifacts) is AdapterDefect.ARTIFACT_NOT_IN_MANIFEST
    )

    def excluded(d: dict[str, Any]) -> None:
        d["served"][1]["revisions_excluded_by_time"] = 1

    assert (
        refusal(
            assemble_layer,
            parse_manifest(mutate_manifest(build.manifest, excluded)),
            build.artifacts,
        )
        is AdapterDefect.REVISIONS_EXCLUDED_BY_TIME
    )

    def unbound_run(d: dict[str, Any]) -> None:
        # A well-formed run that delivered one payload fewer: the manifest stays internally
        # consistent (entries == both digest lists) and one row's provenance no longer binds.
        run = d["build_input"]["runs"][0]
        run["payload_digests"] = run["payload_digests"][:-1]
        run["record_digests"] = run["record_digests"][:-1]
        run["entries"] -= 1
        run["provider_calls"] -= 1  # v2 accounting stays consistent: one call per entry

    assert (
        refusal(
            assemble_layer,
            parse_manifest(mutate_manifest(build.manifest, unbound_run)),
            build.artifacts,
        )
        is AdapterDefect.PROVENANCE_UNBOUND
    )


# --- 5. calendar binding -----------------------------------------------------------------------


def test_case_5_the_calendar_is_the_builds_own_and_its_close_is_an_approximation(
    build: ba.BuildArtifacts,
) -> None:
    manifest = parse_manifest(build.manifest)
    calendar = calendar_from_configuration(build.configuration, manifest=manifest)
    assert calendar == build.calendar
    # A different configuration -- even one whose calendar version matches -- is not the build's.
    other = json.loads(build.configuration)
    other["decision_sessions"] = other["decision_sessions"][:1]
    assert (
        refusal(calendar_from_configuration, canonical_bytes(other), manifest=manifest)
        is AdapterDefect.CONFIGURATION_UNBOUND
    )

    def rename(d: dict[str, Any]) -> None:
        d["transformation"]["calendar_version"] = "some-other-calendar"

    assert (
        refusal(
            calendar_from_configuration,
            build.configuration,
            manifest=parse_manifest(mutate_manifest(build.manifest, rename)),
        )
        is AdapterDefect.CALENDAR_VERSION_MISMATCH
    )
    assembly = assemble_layer(manifest, build.artifacts)
    bound = bind_configuration(build.configuration, manifest=manifest)
    # Dataset construction takes the bound configuration only; a carried calendar that differs
    # from the one its own bytes derive -- renamed or re-sessioned -- is inconsistent, not read.
    assert (
        refusal(
            build_dataset,
            assembly,
            configuration=replace(bound, calendar=replace(calendar, version="renamed")),
        )
        is AdapterDefect.CONFIGURATION_INCONSISTENT
    )
    # The close is not in the document: every session's close is open_at + 6h30 by construction,
    # stated as an approximation and never as the exchange's schedule.
    from kalpamani.data.exploratory.resolution import REGULAR_SESSION, session_close

    for session in calendar.sessions[:3]:
        assert session_close(calendar, session.session_date) == session.open_at + REGULAR_SESSION
    assert "approximation" in (adapter.__doc__ or "")
    assert REGULAR_SESSION == timedelta(hours=6, minutes=30)


# --- 6. the 252-session requirement ------------------------------------------------------------


def test_case_6_a_rule_without_252_history_sessions_is_refused(build: ba.BuildArtifacts) -> None:
    def shorter(d: dict[str, Any]) -> None:
        d["transformation"]["universe_rule"]["history_sessions"] = 20

    manifest = parse_manifest(mutate_manifest(build.manifest, shorter))
    assert refusal(rule_from_manifest, manifest) is AdapterDefect.RULE_HISTORY_NOT_ACCEPTED
    good = rule_from_manifest(parse_manifest(build.manifest))
    assert good == fx.rule()
    assert good.history_sessions == 252 == breakout_long.build_spec().data.required_history_sessions
    full = parse_manifest(build.manifest)
    assembly = assemble_layer(full, build.artifacts)
    bound = bind_configuration(build.configuration, manifest=full)
    # A carried rule that is not the one the bound bytes derive is inconsistent -- whatever its
    # history count says -- and never reaches the membership clauses.
    assert (
        refusal(
            build_dataset,
            assembly,
            configuration=replace(bound, rule=replace(good, history_sessions=251)),
        )
        is AdapterDefect.CONFIGURATION_INCONSISTENT
    )
    # A build genuinely compiled with another history is bound faithfully and refused at
    # construction with the 252 requirement's own defect (the real scenario in case 10 does this).
    assert bound.rule.history_sessions == 252

    def malformed(d: dict[str, Any]) -> None:
        d["transformation"]["universe_rule"]["price_floor"] = 5

    # The manifest's own copy of the rule is validated at parse ...
    assert (
        refusal(parse_manifest, mutate_manifest(build.manifest, malformed))
        is AdapterDefect.MANIFEST_FIELD_MALFORMED
    )
    # ... and a forged view is still a closed refusal at the rule.
    assert (
        refusal(
            rule_from_manifest,
            replace(full, universe_rule={**full.universe_rule, "price_floor": "not-a-number"}),
        )
        is AdapterDefect.RULE_MALFORMED
    )


# --- 7. provenance round trip -------------------------------------------------------------------


def test_case_7_provenance_round_trips_and_gap_instants_are_never_invented(
    build: ba.BuildArtifacts,
) -> None:
    manifest = parse_manifest(build.manifest)
    assembly = assemble_layer(manifest, build.artifacts)
    originals = {
        (r.dataset, r.row_key): r
        for ds in (build.layer.tickers, build.layer.stocks, build.layer.actions)
        for r in ds.rows
    }
    for ds in (assembly.layer.tickers, assembly.layer.stocks, assembly.layer.actions):
        for row in ds.rows:
            original = originals[(row.dataset, row.row_key)]
            assert row.provenance == original.provenance
            assert row.system_first_seen_time == original.system_first_seen_time
            assert row.content_first_seen_time == original.content_first_seen_time
            assert row.observed_at == original.observed_at
            assert row.fields == original.fields and row.symbol == original.symbol
            assert row.redelivery_gaps == ()  # the instant is not in the artifact; never invented
    # A row that names a gap is counted, and the count is reported beside the layer.
    rows = json.loads(build.artifacts["silver-actions"])
    rows["rows"][0]["redelivery_gaps"] = ["some-later-run"]
    content = canonical_bytes(rows)
    edited = dict(build.artifacts)
    edited["silver-actions"] = content

    def rebind(d: dict[str, Any]) -> None:
        for o in d["outputs"]:
            if o["artifact"] == "silver-actions":
                o["sha256"] = adapter.sha256_hex(content)
                o["bytes"] = len(content)

    assembly2 = assemble_layer(parse_manifest(mutate_manifest(build.manifest, rebind)), edited)
    assert assembly2.gap_instants_unknown == 1


# --- 8. isolation --------------------------------------------------------------------------------


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_case_8_the_adapter_imports_only_accepted_contracts_and_its_output_is_exploratory(
    build: ba.BuildArtifacts,
) -> None:
    names = _imports_of(SRC / "data" / "exploratory" / "adapter.py")
    forbidden = (
        "boto3",
        "botocore",
        "socket",
        "urllib",
        "http",
        "subprocess",
        "kalpamani.data.storage",
        "kalpamani.data.production.sharadar.task_clients",
        "kalpamani.data.production.sharadar.build_inputs",
        "kalpamani.data.production.sharadar.bindings",
        "kalpamani.data.production.sharadar.locator",
        "kalpamani.data.production.sharadar.processing",
        "kalpamani.data.production.sharadar.build_processing",
    )
    for name in names:
        assert not any(name == bad or name.startswith(bad + ".") for bad in forbidden), name
        if name.startswith("kalpamani.data.ingest"):
            # the dataset vocabulary only -- never the client, transport or any other module
            assert name == "kalpamani.data.ingest.sharadar.datasets", name
    manifest = parse_manifest(build.manifest)
    dataset = build_dataset(
        assemble_layer(manifest, build.artifacts),
        configuration=bind_configuration(build.configuration, manifest=manifest),
    )
    publication = publish_from_build(
        dataset, publication_id="synthetic-adapter-pub-08", limitations=LIMITATIONS
    )
    assert type(publication) is ExploratoryPublication
    assert a1.VerifiedPublication not in type(publication).__mro__
    assert a1.VerifiedPublication not in type(dataset).__mro__
    inputs = ExploratoryInputSet(publications=(publication,))
    assert admit(M0_RESEARCH_SPECIFICATION, inputs) is AdmissionOutcome.ADMITTED
    assert admit(breakout_long.build_spec(), inputs) is AdmissionOutcome.REFUSED_PRODUCTION_CONSUMER
    assert publication.provenance.source_manifest_digest == manifest.manifest_digest


# --- 9. Gold is not an input ---------------------------------------------------------------------


def test_case_9_gold_is_not_consumed_and_is_refused_by_name(build: ba.BuildArtifacts) -> None:
    manifest = parse_manifest(build.manifest)
    gold_ref = manifest.outputs["gold-adjusted-bars"]
    content = build.gold_artifacts["gold-adjusted-bars"]
    assert (
        refusal(
            parse_silver_artifact,
            "gold-adjusted-bars",
            content,
            expected_sha256=gold_ref.sha256,
            expected_bytes=gold_ref.bytes,
        )
        is AdapterDefect.NOT_A_SILVER_ARTIFACT
    )
    with_gold = dict(build.artifacts)
    with_gold["gold-adjusted-bars"] = content
    assert refusal(assemble_layer, manifest, with_gold) is AdapterDefect.NOT_A_SILVER_ARTIFACT
    # Gold offered under a Silver name fails its digest, never its parse.
    ref = manifest.outputs["silver-stocks"]
    assert refusal(
        parse_silver_artifact,
        "silver-stocks",
        content,
        expected_sha256=ref.sha256,
        expected_bytes=ref.bytes,
    ) in (AdapterDefect.ARTIFACT_BYTES_MISMATCH, AdapterDefect.ARTIFACT_DIGEST_MISMATCH)
    assert not any("gold" in name.lower() for name in adapter.__all__ if name != "SILVER_ARTIFACTS")
    assert "parse_gold" not in dir(adapter)


# --- 10. no store, no read ------------------------------------------------------------------------


def test_case_10_the_adapter_takes_bytes_only_and_the_scenario_build_round_trips(
    scenario: tuple[bytes, dict[str, bytes], bytes, Any],
) -> None:
    # Structural: no call that could reach a store or a file -- checked on the AST, not on prose.
    tree = ast.parse((SRC / "data" / "exploratory" / "adapter.py").read_text(encoding="utf-8"))
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert not calls & {
        "get_object",
        "head_object",
        "put_object",
        "open",
        "urlopen",
        "read_bytes",
        "read_text",
    }
    names = _imports_of(SRC / "data" / "exploratory" / "adapter.py")
    assert not any(
        n in ("pathlib", "io", "os", "boto3", "botocore") or n.startswith("os.") for n in names
    )
    manifest_bytes, artifacts, configuration, report = scenario
    manifest = parse_manifest(manifest_bytes)
    assembly = assemble_layer(manifest, artifacts)
    for name in ("tickers", "stocks", "actions"):
        assert len(assembly.layer.by_dataset(name).rows) == manifest.outputs[f"silver-{name}"].rows
        for row in assembly.layer.by_dataset(name).rows:
            assert row.provenance.run_id in manifest.runs
    calendar = calendar_from_configuration(configuration, manifest=manifest)
    assert calendar.version == manifest.calendar_version
    bound = bind_configuration(configuration, manifest=manifest)
    assert bound.calendar == calendar
    # The scenario's rule has three history sessions: it binds faithfully (it is what the build
    # decided under), and the research path refuses it at the manifest and at construction, as
    # the 252-session requirement demands -- the layer assembled all the same.
    assert bound.rule.history_sessions == 3
    assert refusal(rule_from_manifest, manifest) is AdapterDefect.RULE_HISTORY_NOT_ACCEPTED
    assert (
        refusal(build_dataset, assembly, configuration=bound)
        is AdapterDefect.RULE_HISTORY_NOT_ACCEPTED
    )
    assert report.status.value == "COMPLETED"


def test_a_malformed_row_is_a_closed_defect_never_a_raw_exception(build: ba.BuildArtifacts) -> None:
    manifest = parse_manifest(build.manifest)
    rows = json.loads(build.artifacts["silver-actions"])
    edits: tuple[Any, ...] = (
        lambda r: r.__setitem__("fields", "not a mapping"),
        lambda r: r.__setitem__("revision_sequence", "1"),
        lambda r: r.__setitem__("observed_at", []),
        lambda r: r.__setitem__("row_key", ["other", r["row_key"][1], r["row_key"][2]]),
        lambda r: r.__setitem__("provenance", {}),
        lambda r: r.__setitem__("extra", 1),
        lambda r: r["fields"].__setitem__("ticker", None),
    )
    for edit in edits:
        edited = json.loads(json.dumps(rows))
        edit(edited["rows"][0])
        content = canonical_bytes(edited)
        assert (
            refusal(
                parse_silver_artifact,
                "silver-actions",
                content,
                expected_sha256=adapter.sha256_hex(content),
                expected_bytes=len(content),
            )
            is AdapterDefect.ROW_MALFORMED
        )
    assert manifest.served["stocks"].revisions_excluded_by_time == 0
    assert manifest.resolution["stocks"].p2 == manifest.served["stocks"].revisions_admitted
    assert Decimal(manifest.universe_rule["price_floor"]) == Decimal("5")
    assert manifest.as_of == datetime(2026, 9, 21, 0, 0, tzinfo=UTC)
