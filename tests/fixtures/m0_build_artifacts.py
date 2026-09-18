"""Synthetic **build artifacts** for the exploratory adapter. **SYNTHETIC.**

Two sources, both produced by the accepted production code and never by hand:

* :func:`m0_build` -- the M0 synthetic Silver layer (:mod:`fixtures.m0_exploratory`, re-keyed the
  way production keys rows: ``(security_id, ...)``) pushed through the accepted producer --
  ``availability.resolve`` (production P-2), ``universe.build_universe``, ``gold.build_gold``
  (which serializes the Silver artifacts) and ``build_manifest.build_manifest_document`` -- with
  the compiled configuration document beside it. The build input the manifest cites is a
  fixture stand-in exposing the attributes the manifest reads (identity, ledger digest, runs
  with payload digests); the document shape is the accepted function's.
* :func:`scenario_build` -- the existing end-to-end build scenario
  (:mod:`fixtures.production_build`) run through the real task path against a fake store: the
  manifest, artifacts and configuration exactly as the build task publishes them.

No store is read: artifacts are returned as bytes, which is all the adapter accepts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Final

from fixtures import m0_exploratory as fx
from kalpamani.data.contracts.canonical import canonical_bytes
from kalpamani.data.production.sharadar import availability as av
from kalpamani.data.production.sharadar import build_manifest as bm
from kalpamani.data.production.sharadar import gold as gd
from kalpamani.data.production.sharadar import universe as uv
from kalpamani.data.production.sharadar.locator import PayloadDisposition
from kalpamani.data.production.sharadar.pagination import PAGINATION_POLICY_VERSION
from kalpamani.data.production.sharadar.sessions import SessionCalendar
from kalpamani.data.production.sharadar.silver import AcceptedSchemas, SilverDataset, SilverLayer

BUILD_ID: Final = "synthetic-m0-build-0001"
COMMIT: Final = "0" * 40
COMPLETED_AT: Final = datetime(2026, 9, 21, 1, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildArtifacts:
    """What one admitted build hands the adapter, as bytes, plus the objects it came from."""

    manifest: bytes
    artifacts: dict[str, bytes]
    configuration: bytes
    #: The production-keyed Silver layer the artifacts were serialized from (the direct path).
    layer: SilverLayer
    calendar: SessionCalendar
    as_of: datetime
    gold_artifacts: dict[str, bytes]


def _rekey(dataset: SilverDataset, columns: tuple[str, ...]) -> SilverDataset:
    return replace(
        dataset,
        rows=tuple(
            replace(row, row_key=(row.security_id, *[str(row.fields[c]) for c in columns]))
            for row in dataset.rows
        ),
    )


def production_keyed(layer: SilverLayer) -> SilverLayer:
    """The M0 fixture layer as an admitted build would carry it: production row keys
    ``(security_id[, date[, action]])`` and the accepted pagination policy version (the M0
    fixture's own ``"synthetic"`` label is not a value the producer ever writes)."""
    return replace(
        layer,
        tickers=_rekey(layer.tickers, ()),
        stocks=_rekey(layer.stocks, ("date",)),
        actions=_rekey(layer.actions, ("date", "action")),
        pagination=replace(layer.pagination, policy_version=PAGINATION_POLICY_VERSION),
    )


def m0_build(
    cal: SessionCalendar | None = None, *, layer: SilverLayer | None = None
) -> BuildArtifacts:
    """The accepted producer over the (production-keyed) M0 synthetic layer."""
    cal = cal or fx.calendar()
    silver = production_keyed(layer or fx.silver_layer(cal))
    schemas = AcceptedSchemas(
        version="synthetic-schemas-v1",
        digests={
            name: frozenset(silver.by_dataset(name).schema_digests)
            for name in ("tickers", "stocks", "actions")
        },
    )
    evidence = av.AvailabilityEvidence(version="synthetic-evidence-v0")
    resolved = av.resolve(silver, evidence=evidence, calendar=cal)
    sessions = tuple(s.session_date for s in cal.sessions)
    decision = sessions[-2:]
    universe = uv.build_universe(
        resolved, rule=fx.rule(), calendar=cal, sessions=decision, as_of=fx.AS_OF
    )
    gold = gd.build_gold(
        resolved, universe=universe, calendar=cal, as_of=fx.AS_OF, identity_blocking=0
    )
    configuration = bm.BuildConfiguration(
        schemas=schemas,
        calendar=cal,
        evidence=evidence,
        rule=fx.rule(),
        decision_sessions=decision,
        as_of=fx.AS_OF,
        commit=COMMIT,
    )
    published = tuple(
        bm.PublishedArtifact(
            artifact=artifact,
            logical_key=bm.artifact_key(artifact).logical_key,
            disposition=PayloadDisposition.WRITTEN,
        )
        for artifact in (*gold.silver_artifacts, *gold.gold_artifacts)
    )
    # The build input, as the manifest reads it: the fixture rows all carry one provenance run.
    payloads = sorted(
        {
            row.provenance.payload_sha256
            for ds in (silver.tickers, silver.stocks, silver.actions)
            for row in ds.rows
        }
    )
    run_id = silver.stocks.rows[0].provenance.run_id
    inputs: Any = SimpleNamespace(
        build_identity=BUILD_ID,
        ledger_digest="1" * 64,
        runs=(
            SimpleNamespace(
                locator=SimpleNamespace(
                    run_id=run_id,
                    plan_digest="2" * 64,
                    acquisition_mode="BACKFILL",
                    probes_issued=0,
                    provider_calls=len(payloads),
                ),
                pages=[SimpleNamespace(payload_sha256=d, record_sha256="3" * 64) for d in payloads],
            ),
        ),
        object_count=1 + 2 * len(payloads),
        input_bytes=0,
        pages=lambda: iter(inputs.runs[0].pages),
    )
    document = bm.build_manifest_document(
        inputs=inputs,
        silver=silver,
        resolved=resolved,
        universe=universe,
        gold=gold,
        configuration=configuration,
        published=published,
        run_id=bm.derive_run_id(
            inputs=inputs,
            silver=silver,
            resolved=resolved,
            gold=gold,
            configuration=configuration,
        ),
        completed_at=COMPLETED_AT,
    )
    return BuildArtifacts(
        manifest=canonical_bytes(document),
        artifacts={a.name: a.content for a in gold.silver_artifacts},
        configuration=canonical_bytes(configuration.document()),
        layer=silver,
        calendar=cal,
        as_of=fx.AS_OF,
        gold_artifacts={a.name: a.content for a in gold.gold_artifacts},
    )


def scenario_build() -> tuple[bytes, dict[str, bytes], bytes, Any]:
    """The end-to-end build scenario's own published manifest, Silver artifacts and
    configuration -- exactly as the build task writes them to the (fake) store."""
    from fixtures.production_build import BuildScenario, populated_store

    store = populated_store()
    scenario = BuildScenario(store)
    report = scenario.run()
    manifest_keys = store.keys_under("manifests/sharadar/builds/")
    assert len(manifest_keys) == 1, manifest_keys
    manifest = store.objects[manifest_keys[0]]
    document = json.loads(manifest)
    artifacts: dict[str, bytes] = {}
    for output in document["outputs"]:
        if output["artifact"].startswith("silver-"):
            artifacts[output["artifact"]] = store.objects[output["key"].removeprefix("licensed/")]
    return manifest, artifacts, canonical_bytes(scenario.config.document()), report


__all__ = ["BUILD_ID", "COMMIT", "BuildArtifacts", "m0_build", "production_keyed", "scenario_build"]
