"""Exact lineage selectors, and the four ways replay can fail.

Lineage is "the set a rebuild would read". A selector that resolves to anything
other than exactly the rows it names cannot prove an artifact reproduced -- and an
artifact that cannot prove that is a number with a hash attached.
"""

from __future__ import annotations

from datetime import date

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.entities import Listing, PriceBar, SecurityAttribute
from kalpamani.data.contracts.envelope import LineageRef
from kalpamani.data.contracts.errors import ArtifactIntegrityError
from kalpamani.data.contracts.vocabulary import (
    BarResolution,
    InformationSetProfile,
    ListingFactKind,
)
from kalpamani.data.curate.lineage import (
    attribute_selector,
    bar_selector,
    lineage_fingerprint,
    listing_selector,
    resolve_lineage,
)
from kalpamani.data.curate.universe import membership_hash_of

pytestmark = pytest.mark.unit

SESSION = date(2019, 6, 27)


def _dataset_rows() -> tuple[
    tuple[Listing, ...], tuple[SecurityAttribute, ...], tuple[PriceBar, ...]
]:
    return phase3a.listings(), phase3a.attributes(), phase3a.bars()


def _replay(refs: tuple[LineageRef, ...], **overrides: object) -> tuple[object, ...]:
    """Replay against the fixture, under the profile the fixture builds for.

    ``resolved_profile`` and ``approvals`` are required rather than defaulted in
    the module itself: a negative-coverage claim is about the *admissible* set, so
    replaying without them would test a different claim than the one recorded.
    """
    listings, attributes, bars = _dataset_rows()
    kwargs: dict[str, object] = {
        "listings": listings,
        "attributes": attributes,
        "bars": bars,
        "resolved_profile": InformationSetProfile.PUBLIC_PIT,
        "approvals": phase3a.approvals(),
    }
    kwargs.update(overrides)
    return resolve_lineage(refs, **kwargs)  # type: ignore[arg-type]


def test_a_membership_row_replays_to_exactly_what_it_consumed() -> None:
    """NEGATIVE CONTROL. Correct lineage replays, and the hash reproduces."""
    for row in phase3a.universe_snapshots()[SESSION]:
        replayed = _replay(row.envelope.lineage)
        assert list(replayed) == list(row.inputs)
        assert membership_hash_of(row) == row.envelope.artifact_content_hash


def test_lineage_names_only_the_rows_that_decided_this_security() -> None:
    rows = {row.security_id: row for row in phase3a.universe_snapshots()[SESSION]}
    subject = rows[phase3a.SEC_CONTINUOUS]

    consumed_securities = {
        getattr(record, "security_id", phase3a.SEC_CONTINUOUS) for record in subject.inputs
    }
    assert consumed_securities == {phase3a.SEC_CONTINUOUS}
    assert len(subject.envelope.lineage) == 3, (
        "One listing revision, one attribute row, one bar selector -- not the whole build."
    )


def test_a_selector_that_resolves_to_nothing_is_refused() -> None:
    """MISSING lineage."""
    ref = LineageRef.of(
        entity="listing",
        dataset_version=phase3a.LISTING_DATASET_VERSION,
        selector={
            "listing_id": "LST-9999",
            "listing_fact_kind": ListingFactKind.STATE.value,
            "revision_sequence": "0",
        },
    )
    with pytest.raises(ArtifactIntegrityError, match="no listing matches"):
        _replay((ref,))


def test_a_bar_selector_naming_an_absent_endpoint_is_refused() -> None:
    """NARROWER than what the dataset holds: a named bar is simply not there."""
    ref = LineageRef.of(
        entity="price_bar",
        dataset_version=phase3a.BAR_DATASET_VERSION,
        selector={
            "security_id": phase3a.SEC_CONTINUOUS,
            "resolution": BarResolution.DAILY.value,
            "bar_end_times": phase3a.utc(2030, 1, 1, 20, 0).isoformat(),
        },
    )
    with pytest.raises(ArtifactIntegrityError, match="no DAILY bar"):
        _replay((ref,))


def test_a_selector_matching_more_rows_than_it_names_is_refused() -> None:
    """BROADER lineage: a key that is not unique cannot identify what was read."""
    _listings, _attributes, bars = _dataset_rows()
    duplicated = (*bars, bars[0])
    ref = LineageRef.of(
        entity="price_bar",
        dataset_version=phase3a.BAR_DATASET_VERSION,
        selector=bar_selector(bars[0].security_id, bars[0].resolution, (bars[0],)),
    )
    with pytest.raises(ArtifactIntegrityError, match="share the key"):
        _replay((ref,), bars=duplicated)


def test_a_selector_contradicting_its_own_key_is_refused() -> None:
    """CONTRADICTORY lineage: the attribute exists, but not at the named date."""
    attribute = phase3a.attributes()[0]
    selector = attribute_selector(attribute)
    selector["valid_from"] = date(1999, 1, 1).isoformat()
    ref = LineageRef.of(
        entity="security_attribute",
        dataset_version=phase3a.ATTRIBUTE_DATASET_VERSION,
        selector=selector,
    )
    with pytest.raises(ArtifactIntegrityError, match="no security_attribute matches"):
        _replay((ref,))


def test_a_lineage_entity_with_no_resolver_is_refused() -> None:
    ref = LineageRef.of(
        entity="fundamental_fact",
        dataset_version="gold/whatever",
        selector={"metric": "revenue"},
    )
    with pytest.raises(ArtifactIntegrityError, match="no resolver for lineage entity"):
        _replay((ref,))


def test_a_listing_selector_pins_one_revision() -> None:
    """Two revisions of one listing must not both answer to one selector."""
    revisions = [
        listing
        for listing in phase3a.listings()
        if listing.listing_id == "LST-0003" and listing.listing_fact_kind is ListingFactKind.STATE
    ]
    assert len(revisions) == 2
    for revision in revisions:
        resolved = _replay(
            (
                LineageRef.of(
                    entity="listing",
                    dataset_version=phase3a.LISTING_DATASET_VERSION,
                    selector=listing_selector(revision),
                ),
            )
        )
        assert resolved == (revision,)


def test_the_lineage_fingerprint_is_order_stable() -> None:
    """It enters a content hash, so its rendering cannot depend on iteration order."""
    row = phase3a.universe_snapshots()[SESSION][0]
    forward = lineage_fingerprint(row.envelope.lineage)
    backward = lineage_fingerprint(tuple(reversed(row.envelope.lineage)))
    assert forward == backward


def test_a_changed_bar_for_another_security_does_not_change_this_row() -> None:
    """The point of per-security lineage, stated as the property it buys."""
    rows = {row.security_id: row for row in phase3a.universe_snapshots()[SESSION]}
    subject = rows[phase3a.SEC_CONTINUOUS]
    other = rows[phase3a.SEC_RENAMED]

    subject_selectors = lineage_fingerprint(subject.envelope.lineage)
    other_selectors = lineage_fingerprint(other.envelope.lineage)
    assert subject_selectors != other_selectors
    assert not set(subject_selectors) & set(other_selectors)
