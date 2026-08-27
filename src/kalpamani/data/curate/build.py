"""The one sanctioned way to construct a Gold dataset.

``GoldDataset`` is a plain container, and a container will hold whatever it is
given. This module is the boundary that decides what it may be given: a build
starts from :class:`ResolvedRunInputs`, which carry the receipt saying which
policy admitted the rows, and the dataset it produces carries that receipt
forward. Publication verifies it against the rows it is about to write.

**Why a receipt rather than a convention.** "Correct rows, unknown provenance" is
the shape that passes review and cannot be reproduced afterwards. A dataset
assembled by hand looks exactly like one that went through resolution -- same
types, same values, same tests passing -- right up to the moment someone asks
which policy admitted a particular row and nothing can answer. The receipt makes
that question answerable, and makes a dataset that cannot answer it unpublishable.

The universe is built here rather than by the caller for the same reason: a
snapshot handed in from outside could have been evaluated against inputs the
resolution never saw.

**Lineage names the version a row actually came from.** An earlier draft passed
the final Gold version as every source lineage version, which is wrong in a way
that only shows up later: a Gold build stores a *copy* of a row, and the copy
does not become the source. Replaying such lineage would look for the row in the
Gold version and find it, proving nothing about which source build it was read
from. Selectors now carry ``row.envelope.dataset_version``, and a history
spanning two immutable source versions produces two references rather than one
that quietly averages them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime

from kalpamani.data.contracts.dataset import GoldDataset, UniverseSnapshotHeader
from kalpamani.data.contracts.entities import (
    CorporateAction,
    Listing,
    MarketSession,
    PriceBar,
    SecurityAttribute,
    TickerHistory,
    UniverseMembership,
)
from kalpamani.data.contracts.errors import BuildBoundaryError
from kalpamani.data.contracts.resolution import BoundApprovals, SourceRecord
from kalpamani.data.contracts.row_identity import row_fingerprint
from kalpamani.data.contracts.vocabulary import InformationSetProfile
from kalpamani.data.curate.resolution_run import ResolvedRunInputs
from kalpamani.data.curate.universe import (
    UniverseBuildInputs,
    UniverseDefinition,
    build_snapshot_header,
    build_universe_snapshot,
)

#: The source datasets a Gold build consumes. Each must have been resolved.
GOLD_SOURCE_DATASETS = (
    "corporate_action",
    "listing",
    "market_session",
    "price_bar",
    "security_attribute",
    "ticker_history",
)


def _typed(rows: Sequence[object], expected: type, dataset: str) -> tuple[object, ...]:
    """Confirm resolved rows are the entity their dataset name claims."""
    wrong = [row for row in rows if not isinstance(row, expected)]
    if wrong:
        raise BuildBoundaryError(
            f"dataset {dataset!r} resolved {len(wrong)} row(s) that are not "
            f"{expected.__name__}. A dataset name that does not match its rows would resolve "
            "and evidence the wrong things while every count still reconciled."
        )
    return tuple(rows)


def build_gold_dataset(
    resolved: ResolvedRunInputs,
    *,
    dataset_version: str,
    build_time: datetime,
    coverage_start: date,
    coverage_end: date,
    universe_definition: UniverseDefinition,
    universe_sessions: Sequence[date],
    evaluation_cutoffs: Mapping[date, datetime],
    approvals: BoundApprovals,
    artifact_first_built_time: datetime,
    ingestion_time: datetime,
) -> GoldDataset:
    """Build a Gold dataset from resolved inputs, and only from resolved inputs.

    Raises:
        BuildBoundaryError: if a required source dataset did not go through
            resolution, if a dataset's rows are not the entity it names, or if a
            universe session has no declared evaluation cutoff. Each would
            produce a dataset whose receipt describes something other than its
            contents.
        RequiredInputUnavailableError: propagated from the universe build when a
            required domain has no admissible rows for a session.
    """
    missing = [name for name in GOLD_SOURCE_DATASETS if name not in resolved.by_dataset]
    if missing:
        raise BuildBoundaryError(
            f"Gold requires resolved rows for {missing}, which did not go through "
            "resolve_run_inputs. Gold is built from resolved inputs; assembling it from raw "
            "rows would leave nothing able to say which policy admitted them."
        )

    sessions = _typed(resolved.rows("market_session"), MarketSession, "market_session")
    listings = _typed(resolved.rows("listing"), Listing, "listing")
    attributes = _typed(
        resolved.rows("security_attribute"), SecurityAttribute, "security_attribute"
    )
    tickers = _typed(resolved.rows("ticker_history"), TickerHistory, "ticker_history")
    bars = _typed(resolved.rows("price_bar"), PriceBar, "price_bar")
    actions = _typed(resolved.rows("corporate_action"), CorporateAction, "corporate_action")

    undeclared = sorted(set(universe_sessions) - set(evaluation_cutoffs))
    if undeclared:
        raise BuildBoundaryError(
            f"universe sessions {undeclared} have no declared evaluation cutoff. The cutoff is "
            "a stated policy -- a universe has to be known before the session it governs "
            "begins -- and deriving one here would make it an assumption made twice."
        )

    build_inputs = UniverseBuildInputs(
        listings=listings,  # type: ignore[arg-type]
        attributes=attributes,  # type: ignore[arg-type]
        bars=bars,  # type: ignore[arg-type]
    )

    universe: dict[date, tuple[UniverseMembership, ...]] = {}
    headers: dict[date, UniverseSnapshotHeader] = {}
    for session in sorted(universe_sessions):
        cutoff = evaluation_cutoffs[session]
        snapshot = build_universe_snapshot(
            build_inputs,
            session_date=session,
            evaluation_cutoff=cutoff,
            definition=universe_definition,
            resolved_profile=resolved.resolved_profile,
            approvals=approvals,
            artifact_first_built_time=artifact_first_built_time,
            ingestion_time=ingestion_time,
            dataset_version=dataset_version,
        )
        universe[session] = snapshot.rows
        headers[session] = build_snapshot_header(
            snapshot.rows,
            session_date=session,
            definition=universe_definition,
            resolved_profile=resolved.resolved_profile,
            evaluation_cutoff=cutoff,
            considered_listings=snapshot.considered_listings,
            required_domain_coverage=snapshot.required_domain_coverage,
            artifact_first_built_time=artifact_first_built_time,
            ingestion_time=ingestion_time,
            dataset_version=dataset_version,
        )

    return GoldDataset(
        dataset_version=dataset_version,
        build_time=build_time,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        resolved_profile=resolved.resolved_profile,
        resolution_policy_version=resolved.resolution_policy_version,
        resolution_receipt=resolved.receipt,
        resolution_evidence=resolved.evidence,
        sessions=sessions,  # type: ignore[arg-type]
        listings=listings,  # type: ignore[arg-type]
        attributes=attributes,  # type: ignore[arg-type]
        tickers=tickers,  # type: ignore[arg-type]
        bars=bars,  # type: ignore[arg-type]
        actions=actions,  # type: ignore[arg-type]
        universe=universe,
        universe_headers=headers,
    )


def dataset_row_fingerprint(dataset: GoldDataset) -> tuple[tuple[str, ...], ...]:
    """A content-bound fingerprint over every source row a build holds.

    Publication compares this against the receipt's own. A row substituted after
    resolution changes it -- including a substitution that keeps the identifier
    and changes only a price or an availability time, which a name-only
    fingerprint could not see.
    """
    records: list[SourceRecord] = []
    for rows in (
        dataset.sessions,
        dataset.listings,
        dataset.attributes,
        dataset.tickers,
        dataset.bars,
        dataset.actions,
    ):
        records.extend(rows)
    return row_fingerprint(records)


def dataset_profile(dataset: GoldDataset) -> InformationSetProfile:
    """The profile a build resolved to. Named for readability at call sites."""
    return dataset.resolved_profile


__all__ = [
    "GOLD_SOURCE_DATASETS",
    "build_gold_dataset",
    "dataset_profile",
    "dataset_row_fingerprint",
]
