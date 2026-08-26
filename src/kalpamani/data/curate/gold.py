"""Writing and reading a curated Gold dataset version.

The step that makes a backtest's inputs a **materialised, versioned, checksummed
artifact** rather than the live result of a query that might behave differently
tomorrow -- the difference between a reproducible result and a result that
happened to reproduce.

**Reading back re-resolves lineage rather than storing resolved inputs.** A
derived artifact's ``inputs`` are the records it consumed; its ``lineage`` is the
replayable description of them. Persisting the resolved records would duplicate
every input row inside every artifact that read it, and invite the two copies to
disagree. So the reader replays the lineage instead, re-applying the *same*
deterministic admissibility filter the build applied. That is precisely the
property lineage is supposed to have -- "the set a rebuild would read" -- and
exercising it on every read means a lineage that stopped being replayable is
found immediately rather than the first time someone tries to reproduce a result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime

from kalpamani.data.contracts.canonical import content_hash
from kalpamani.data.contracts.dataset import GoldDataset
from kalpamani.data.contracts.entities import DatasetVersion, UniverseMembership
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
    InformationSetProfile,
    StorageLayer,
)
from kalpamani.data.curate.universe import admissible_inputs
from kalpamani.data.storage import LocalTableStore, TableArtifact

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


def write_gold_dataset(
    store: LocalTableStore,
    dataset: GoldDataset,
    *,
    code_commit_sha: str,
    lag_policy_version: str,
    resolved_profile: InformationSetProfile,
    universe_definition_version: str,
) -> tuple[DatasetVersion, tuple[TableArtifact, ...]]:
    """Persist every table of ``dataset`` and return its immutable version record.

    Deterministic: two builds from the same inputs produce byte-identical tables
    and therefore an identical ``content_hash``.
    """
    universe_rows: list[UniverseMembership] = []
    for rows in dataset.universe.values():
        universe_rows.extend(rows)

    tables: dict[str, list[Mapping[str, object]]] = {
        "market_session": [encode_market_session(s) for s in dataset.sessions],
        "listing": [encode_listing(item) for item in dataset.listings],
        "security_attribute": [encode_security_attribute(a) for a in dataset.attributes],
        "ticker_history": [encode_ticker_history(t) for t in dataset.tickers],
        "price_bar": [encode_price_bar(b) for b in dataset.bars],
        "corporate_action": [encode_corporate_action(a) for a in dataset.actions],
        "universe_membership": [encode_universe_membership(u) for u in universe_rows],
    }

    artifacts = tuple(
        store.write_table(
            layer=StorageLayer.GOLD,
            dataset_version=dataset.dataset_version,
            entity=entity,
            rows=tables[entity],
        )
        for entity in GOLD_ENTITIES
    )

    version = DatasetVersion(
        dataset_version=dataset.dataset_version,
        layer=StorageLayer.GOLD,
        built_at=dataset.build_time,
        built_from_run_ids=(),
        code_commit_sha=code_commit_sha,
        content_hash=content_hash(
            [[artifact.entity, artifact.content_hash] for artifact in artifacts]
        ),
        lag_policy_version=lag_policy_version,
        resolved_profile=resolved_profile,
        universe_definition_version=universe_definition_version,
    )
    return version, artifacts


def read_gold_dataset(
    store: LocalTableStore,
    *,
    dataset_version: str,
    build_time: datetime,
    coverage_start: date,
    coverage_end: date,
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
    evaluation_cutoffs: Mapping[date, datetime],
) -> GoldDataset:
    """Load a published Gold dataset version back from storage.

    ``evaluation_cutoffs`` supplies each session's own cutoff so universe lineage
    can be replayed under the same admissibility rule the build used. Passing them
    in rather than deriving them keeps the cutoff a stated policy instead of an
    assumption made twice, in two places, that might diverge.
    """

    def rows(entity: str) -> Sequence[Mapping[str, object]]:
        return store.read_table(
            layer=StorageLayer.GOLD,
            dataset_version=dataset_version,
            entity=entity,
        )

    sessions = tuple(decode_market_session(r) for r in rows("market_session"))
    listings = tuple(decode_listing(r) for r in rows("listing"))
    attributes = tuple(decode_security_attribute(r) for r in rows("security_attribute"))
    tickers = tuple(decode_ticker_history(r) for r in rows("ticker_history"))
    bars = tuple(decode_price_bar(r) for r in rows("price_bar"))
    actions = tuple(decode_corporate_action(r) for r in rows("corporate_action"))

    universe: dict[date, list[UniverseMembership]] = {}
    for row in rows("universe_membership"):
        session_raw = row["session_date"]
        assert isinstance(session_raw, str)
        session = date.fromisoformat(session_raw)
        cutoff = evaluation_cutoffs[session]
        replayed: tuple[PitRecord, ...] = admissible_inputs(
            listings=listings,
            attributes=attributes,
            bars=bars,
            resolved_profile=resolved_profile,
            approvals=approvals,
            evaluation_cutoff=cutoff,
        )
        universe.setdefault(session, []).append(decode_universe_membership(row, replayed))

    return GoldDataset(
        dataset_version=dataset_version,
        build_time=build_time,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
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


__all__ = [
    "GOLD_ENTITIES",
    "read_gold_dataset",
    "write_gold_dataset",
]
