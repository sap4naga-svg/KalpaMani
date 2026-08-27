"""Query atomicity: a result is whole, or it is a refusal.

Two defects with one shape. A price series checked its completeness against what
the dataset physically held and then filtered for point-in-time availability, so
a bar that existed but was not yet publishable simply left the result. A universe
query picked a session by truncating an instant to a UTC date and then filtered
membership rows one at a time, so a row whose decision landed a moment after its
siblings left the result too.

In both cases the caller received a shorter answer than they asked for, and
nothing in the answer said so. A list of numbers does not carry the fact that
some of it is missing.

Every test here is a case where the previous code returned something.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.entities import Listing, MarketSession, PriceBar
from kalpamani.data.contracts.errors import (
    IncompleteCoverageError,
    MissingHistoricalSnapshotError,
)
from kalpamani.data.contracts.vocabulary import (
    RAW,
    BarResolution,
    Exchange,
    InformationOrigin,
    InformationSetProfile,
    ProviderTimeDerivation,
    PublicTimeDerivation,
)
from kalpamani.data.pit.accessors import PointInTimeReader, SeriesRequirement
from kalpamani.data.storage import LocalTableStore

PUBLIC = InformationSetProfile.PUBLIC_PIT
PROVIDER = InformationSetProfile.PROVIDER_REALISTIC_PIT
FORWARD = InformationSetProfile.FORWARD_SYSTEM

#: The continuously-listed security and the five sessions it trades in June 2019.
SECURITY = phase3a.SEC_CONTINUOUS
FIRST = date(2019, 6, 24)
MIDDLE = date(2019, 6, 26)
LAST = date(2019, 6, 28)
#: Well after every June 2019 bar has published.
SETTLED = phase3a.utc(2019, 7, 1, 12, 0)
#: Far enough in the future that a pushed availability is still ahead of it.
LATE = phase3a.utc(2020, 1, 1, 12, 0)


# ---------------------------------------------------------------------------
# 1 -- a REQUIRED price series is complete after point-in-time filtering
# ---------------------------------------------------------------------------


def _series(
    reader: PointInTimeReader,
    *,
    as_of: datetime = SETTLED,
    start: date = FIRST,
    end: date = LAST,
    requirement: SeriesRequirement = SeriesRequirement.REQUIRED,
    profile: InformationSetProfile = PUBLIC,
) -> Any:
    return reader.get_price_history(
        security_id=SECURITY,
        start=start,
        end=end,
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=as_of,
        profile=profile,
        requirement=requirement,
        revision_view=None,
    )


def _reader_with_late_bar(tmp_path: Path, session_date: date) -> PointInTimeReader:
    """A publication identical to the fixture but for one bar's availability."""
    datasets = phase3a.with_bar_available_at(
        phase3a.source_datasets(),
        security_id=SECURITY,
        session_date=session_date,
        provider_available=phase3a.utc(2025, 1, 1, 12, 0),
    )
    return phase3a.reader_from(LocalTableStore(tmp_path), datasets)


def test_a_fully_available_series_is_served(tmp_path: Path) -> None:
    """NEGATIVE CONTROL. Every expected endpoint survived, so nothing is refused."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    result = _series(reader)
    assert [value.session_date for value in result.bars] == [
        date(2019, 6, 24),
        date(2019, 6, 25),
        date(2019, 6, 26),
        date(2019, 6, 27),
        date(2019, 6, 28),
    ]
    assert result.withheld_endpoints == 0
    assert result.requirement is SeriesRequirement.REQUIRED


@pytest.mark.parametrize(
    ("label", "session_date"),
    [("first", FIRST), ("middle", MIDDLE), ("last", LAST)],
)
def test_one_unavailable_bar_refuses_the_whole_series(
    tmp_path: Path, label: str, session_date: date
) -> None:
    """Wherever the hole is, a five-bar request does not come back four bars long.

    The middle case is the one that mattered most: a hole at either end at least
    changes the range of the result, while a hole in the middle leaves a series
    that looks entirely ordinary.
    """
    reader = _reader_with_late_bar(tmp_path, session_date)
    with pytest.raises(IncompleteCoverageError) as refusal:
        _series(reader)
    message = str(refusal.value)
    assert "not yet available at this as_of" in message
    assert session_date.isoformat() in message
    assert "missing 1 of 5 expected endpoint(s)" in message, label


def test_the_same_series_is_served_short_when_asked_optionally(tmp_path: Path) -> None:
    """The escape hatch is explicit, and the result says it was used."""
    reader = _reader_with_late_bar(tmp_path, MIDDLE)
    result = _series(reader, requirement=SeriesRequirement.OPTIONAL)
    assert [value.session_date for value in result.bars] == [
        date(2019, 6, 24),
        date(2019, 6, 25),
        date(2019, 6, 27),
        date(2019, 6, 28),
    ]
    assert result.withheld_endpoints == 1
    assert result.requirement is SeriesRequirement.OPTIONAL


def test_a_provider_lagged_middle_bar_refuses(tmp_path: Path) -> None:
    """Provider lag is a timing fact, and it makes the series incomplete like any other."""
    datasets = phase3a.with_bar_available_at(
        phase3a.source_datasets(),
        security_id=SECURITY,
        session_date=MIDDLE,
        # One hour after the query's cutoff: ordinary vendor lag, not a defect.
        provider_available=SETTLED + timedelta(hours=1),
    )
    reader = phase3a.reader_from(LocalTableStore(tmp_path), datasets)
    with pytest.raises(IncompleteCoverageError, match="not yet available at this as_of"):
        _series(reader)


def test_an_origin_ineligible_bar_refuses_a_required_series(tmp_path: Path) -> None:
    """A profile that cannot see a bar cannot serve a series that needs it."""
    datasets = dict(phase3a.source_datasets())
    datasets["price_bar"] = tuple(
        dataclasses.replace(
            bar,
            bar_construction=bar.bar_construction,
            envelope=dataclasses.replace(
                bar.envelope,
                information_origin=InformationOrigin.PROVIDER_DERIVED,
                public_available_time=None,
                public_available_upper_bound=None,
                public_time_derivation=PublicTimeDerivation.NOT_APPLICABLE,
                provider_time_derivation=ProviderTimeDerivation.FILE_DROP,
            ),
        )
        if (
            isinstance(bar, PriceBar)
            and bar.security_id == SECURITY
            and bar.session_date == MIDDLE
            and bar.resolution is BarResolution.DAILY
        )
        else bar
        for bar in datasets["price_bar"]
    )
    reader = phase3a.reader_from(LocalTableStore(tmp_path), datasets)
    with pytest.raises(IncompleteCoverageError) as refusal:
        _series(reader)
    assert "origin is not eligible under this profile" in str(refusal.value)


def test_an_as_of_before_the_end_of_the_series_names_the_end_that_would_work(
    tmp_path: Path,
) -> None:
    """The caller shortens ``end`` explicitly rather than being handed a prefix."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    with pytest.raises(IncompleteCoverageError) as refusal:
        _series(reader, as_of=phase3a.utc(2019, 6, 26, 20, 0))
    message = str(refusal.value)
    assert "not yet available at this as_of" in message
    assert "an end of 2019-06-25 would answer" in message


def test_the_named_shorter_end_does_answer(tmp_path: Path) -> None:
    """The hint is worth giving only if following it works."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    result = _series(reader, as_of=phase3a.utc(2019, 6, 26, 20, 0), end=date(2019, 6, 25))
    assert [value.session_date for value in result.bars] == [
        date(2019, 6, 24),
        date(2019, 6, 25),
    ]


def test_a_missing_bar_and_an_unavailable_bar_are_different_refusals(
    tmp_path: Path,
) -> None:
    """A data gap and a timing gap have different fixes, so they read differently."""
    late = _reader_with_late_bar(tmp_path / "late", MIDDLE)
    with pytest.raises(IncompleteCoverageError) as timing:
        _series(late)
    assert "A REQUIRED DAILY series" in str(timing.value)
    assert "not yet available at this as_of" in str(timing.value)

    gapped = phase3a.reader_from(
        LocalTableStore(tmp_path / "gap"),
        phase3a.without_bar(phase3a.source_datasets(), security_id=SECURITY, session_date=MIDDLE),
    )
    with pytest.raises(IncompleteCoverageError) as missing:
        _series(gapped)
    assert "Refused rather than truncated" in str(missing.value)
    assert "has no DAILY bar" in str(missing.value)


def test_a_required_series_with_no_calendar_basis_is_refused(tmp_path: Path) -> None:
    """No listed session means no grid, and no grid means completeness is uncheckable.

    This was a real hole in the first version of the two-phase check: a security
    with no listing rows produced an empty expected grid, so *both* coverage
    checks returned early and a five-session REQUIRED request came back with
    whatever bars happened to be available. The vacuous case is the dangerous one
    precisely because it looks like a pass.
    """
    datasets = phase3a.source_datasets()
    datasets["listing"] = tuple(
        row
        for row in datasets["listing"]
        if isinstance(row, Listing) and row.security_id != SECURITY
    )
    reader = phase3a.reader_from(LocalTableStore(tmp_path), datasets)
    with pytest.raises(IncompleteCoverageError) as refusal:
        _series(reader, as_of=phase3a.utc(2019, 6, 26, 20, 0))
    assert "no listed trading session" in str(refusal.value)


def test_the_same_query_is_served_optionally(tmp_path: Path) -> None:
    """NEGATIVE CONTROL. Best effort remains available, and says what it withheld."""
    datasets = phase3a.source_datasets()
    datasets["listing"] = tuple(
        row
        for row in datasets["listing"]
        if isinstance(row, Listing) and row.security_id != SECURITY
    )
    reader = phase3a.reader_from(LocalTableStore(tmp_path), datasets)
    result = _series(
        reader,
        as_of=phase3a.utc(2019, 6, 26, 20, 0),
        requirement=SeriesRequirement.OPTIONAL,
    )
    assert [value.session_date for value in result.bars] == [
        date(2019, 6, 24),
        date(2019, 6, 25),
    ]


# ---------------------------------------------------------------------------
# 2 -- a universe snapshot is selected and served whole
# ---------------------------------------------------------------------------

#: The fixture's snapshot sessions. The 2019 one opens at 13:30 UTC.
EARLY_SESSION = date(2019, 6, 27)
LATE_SESSION = date(2021, 1, 5)


def test_a_same_day_query_before_the_evaluation_cutoff_does_not_see_the_snapshot(
    tmp_path: Path,
) -> None:
    """The session has not opened in its own venue's terms, so it is not a candidate."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    with pytest.raises(MissingHistoricalSnapshotError, match="evaluation cutoff had passed"):
        reader.get_security_universe(
            as_of=phase3a.session_open(EARLY_SESSION) - timedelta(minutes=1), profile=PUBLIC
        )


def test_a_same_day_query_after_the_evaluation_cutoff_sees_it(tmp_path: Path) -> None:
    """NEGATIVE CONTROL. Once the cutoff has passed the snapshot is the answer."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    result = reader.get_security_universe(
        as_of=phase3a.session_open(EARLY_SESSION) + timedelta(minutes=1), profile=PUBLIC
    )
    assert result.session_date == EARLY_SESSION


def test_a_utc_date_that_runs_ahead_of_the_session_date_is_not_a_candidate(
    tmp_path: Path,
) -> None:
    """02:00 UTC on the 27th is 22:00 on the 26th in New York.

    Selecting by ``session_date <= cutoff.date()`` made the 27th's snapshot a
    candidate at an instant when, in the venue's own terms, the session had not
    begun -- a look-ahead created purely by truncating an instant to a UTC date.
    """
    reader = phase3a.reader(LocalTableStore(tmp_path))
    utc_is_the_27th = phase3a.utc(2019, 6, 27, 2, 0)
    assert utc_is_the_27th.date() == EARLY_SESSION, "The UTC date has already rolled over."
    assert phase3a.session_open(EARLY_SESSION) > utc_is_the_27th, "The session has not opened."

    with pytest.raises(MissingHistoricalSnapshotError, match="evaluation cutoff had passed"):
        reader.get_security_universe(as_of=utc_is_the_27th, profile=PUBLIC)


def test_the_latest_snapshot_is_preferred_when_both_are_available(tmp_path: Path) -> None:
    """NEGATIVE CONTROL. Latest-first is still the rule."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    result = reader.get_security_universe(as_of=phase3a.BUILD_TIME, profile=PUBLIC)
    assert result.session_date == LATE_SESSION


#: Two build instants, modelling an incremental pipeline: the 2019 snapshot has
#: been held since T1, the 2021 one only since T2.
T1 = phase3a.utc(2026, 8, 20, 9, 0)
T2 = phase3a.utc(2026, 8, 25, 9, 0)


def _incremental(tmp_path: Path, **kwargs: Any) -> PointInTimeReader:
    publication = phase3a.incremental_publication(
        LocalTableStore(tmp_path), early_built=T1, late_built=T2, **kwargs
    )
    return PointInTimeReader(
        publication,
        resolution=phase3a.resolution(requested=FORWARD),
        approvals=phase3a.approvals(),
    )


def test_an_unavailable_latest_snapshot_falls_back_to_the_prior_one(
    tmp_path: Path,
) -> None:
    """To the whole earlier snapshot -- not to a subset of the later one.

    Row-by-row filtering produced the subset, and the subset is the thing that
    never existed.
    """
    reader = _incremental(tmp_path)
    between = T2 - timedelta(hours=1)
    result = reader.get_security_universe(as_of=between, profile=FORWARD)
    assert result.session_date == EARLY_SESSION, (
        "The 2021 snapshot's cutoff has long passed, but under FORWARD_SYSTEM it had not been "
        "built yet at this instant, so the query serves the whole snapshot that had."
    )
    stored = reader.publication.dataset.universe[EARLY_SESSION]
    assert len(result.members) + len(result.non_members) == len(stored)


def test_the_later_snapshot_is_served_once_it_has_been_built(tmp_path: Path) -> None:
    """NEGATIVE CONTROL for the fallback."""
    reader = _incremental(tmp_path)
    result = reader.get_security_universe(as_of=T2 + timedelta(hours=1), profile=FORWARD)
    assert result.session_date == LATE_SESSION


def test_no_available_snapshot_at_all_is_a_refusal_naming_each_candidate(
    tmp_path: Path,
) -> None:
    """Refusal, not the emptiest available answer."""
    reader = _incremental(tmp_path)
    with pytest.raises(MissingHistoricalSnapshotError) as refusal:
        reader.get_security_universe(as_of=T1 - timedelta(hours=1), profile=FORWARD)
    message = str(refusal.value)
    assert "was completely available" in message
    assert EARLY_SESSION.isoformat() in message
    assert LATE_SESSION.isoformat() in message


def test_one_membership_decision_arriving_late_withholds_the_whole_snapshot(
    tmp_path: Path,
) -> None:
    """The case that produced a membership set which existed at no instant.

    One decision of the 2019 snapshot was recomputed in the later build, so it
    became available at T2 while its siblings had been available since T1.
    Serving the snapshot between those instants would return every row but that
    one -- silently.
    """
    reader = _incremental(tmp_path, stale_row_security=phase3a.SEC_CONTINUOUS)
    between = T2 - timedelta(hours=1)
    with pytest.raises(MissingHistoricalSnapshotError) as refusal:
        reader.get_security_universe(as_of=between, profile=FORWARD)
    message = str(refusal.value)
    assert "still arriving until" in message
    assert T2.isoformat() in message


def test_the_partly_recomputed_snapshot_is_whole_once_that_decision_lands(
    tmp_path: Path,
) -> None:
    """NEGATIVE CONTROL. Every row, or none."""
    reader = _incremental(tmp_path, stale_row_security=phase3a.SEC_CONTINUOUS)
    result = reader.get_security_universe(as_of=T2 + timedelta(hours=1), profile=FORWARD)
    stored = reader.publication.dataset.universe[result.session_date]
    assert len(result.members) + len(result.non_members) == len(stored)


def test_the_same_snapshot_is_whole_once_its_last_decision_has_landed(
    tmp_path: Path,
) -> None:
    """NEGATIVE CONTROL for the case above."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    result = reader.get_security_universe(as_of=phase3a.utc(2019, 6, 30, 12, 0), profile=PUBLIC)
    assert result.session_date == EARLY_SESSION
    stored = reader.publication.dataset.universe[EARLY_SESSION]
    assert len(result.members) + len(result.non_members) == len(stored), (
        "Every stored row is accounted for. A snapshot is served whole or not at all."
    )


def test_a_universe_result_names_the_snapshot_it_came_from(tmp_path: Path) -> None:
    """A caller citing this result can say exactly which snapshot it was."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    result = reader.get_security_universe(as_of=phase3a.BUILD_TIME, profile=PUBLIC)
    header = reader.publication.dataset.universe_headers[result.session_date]
    assert result.snapshot_content_hash == header.snapshot_content_hash
    assert result.snapshot_artifact_id == header.artifact_id


# ---------------------------------------------------------------------------
# 2b -- a zero-row snapshot is a real answer, under every profile
# ---------------------------------------------------------------------------


def _zero_row_reader(tmp_path: Path, profile: InformationSetProfile) -> PointInTimeReader:
    """A build whose rule genuinely selected nobody on the 2019 session.

    Produced by supplying only the delisted security's listings and evaluating the
    2021 session: the listing rows are admissible evidence by then, so the build
    is computable, and the security had already delisted, so nobody is listed and
    the rule selects nobody.

    That is a real empty selection rather than a published snapshot with its rows
    removed -- and the distinction matters, because telling "nobody qualified"
    apart from "we could not answer" is the whole point of the header.
    """
    datasets = phase3a.forward_datasets() if profile is FORWARD else phase3a.source_datasets()
    datasets["listing"] = tuple(
        row
        for row in datasets["listing"]
        if isinstance(row, Listing) and row.security_id == phase3a.SEC_DELISTED
    )
    return phase3a.reader_from(
        LocalTableStore(tmp_path),
        datasets,
        requested=profile,
        universe_sessions=(LATE_SESSION,),
    )


@pytest.mark.parametrize("profile", [PUBLIC, PROVIDER, FORWARD])
def test_a_zero_row_snapshot_is_served_as_an_answer(
    tmp_path: Path, profile: InformationSetProfile
) -> None:
    """ "Nobody qualified" is an answer, and it is one under every profile.

    A zero-row snapshot is exactly where atomicity has no membership rows to lean
    on. Every constraint on serving it comes from the header alone, which is why
    the header had to become a derived artifact in the first place.
    """
    reader = _zero_row_reader(tmp_path, profile)
    header = reader.publication.dataset.universe_headers[LATE_SESSION]
    assert header.row_count == 0, "Nobody was listed, so the rule selected nobody."
    assert header.is_complete, "And the session was nonetheless built."

    result = reader.get_security_universe(as_of=phase3a.BUILD_TIME, profile=profile)
    assert result.session_date == LATE_SESSION
    assert result.members == ()
    assert result.non_members == ()
    assert result.snapshot_content_hash == header.snapshot_content_hash


def test_a_zero_row_snapshot_is_not_served_before_it_was_built_under_forward_system(
    tmp_path: Path,
) -> None:
    """Before we ran the rule we did not know it selected nobody. We knew nothing."""
    reader = _zero_row_reader(tmp_path, FORWARD)
    with pytest.raises(MissingHistoricalSnapshotError, match="first built at"):
        reader.get_security_universe(
            as_of=phase3a.ARTIFACT_FIRST_BUILT - timedelta(minutes=1), profile=FORWARD
        )


# ---------------------------------------------------------------------------
# 3 -- the inventory distinguishes source from derived
# ---------------------------------------------------------------------------


def test_a_universe_query_records_a_derived_artifact_not_a_source_dataset(
    tmp_path: Path,
) -> None:
    """It reads a stored snapshot. It does not open listing, attribute or bar tables."""
    reader = phase3a.reader(LocalTableStore(tmp_path))
    result = reader.get_security_universe(as_of=phase3a.BUILD_TIME, profile=PUBLIC)
    evidence = reader.execution_evidence()

    assert evidence.direct_source_datasets == ()
    assert result.snapshot_artifact_id in evidence.consumed_artifact_ids
    (artifact,) = evidence.consumed_artifacts
    assert artifact.entity == "universe_snapshot_header"
    assert artifact.artifact_content_hash == result.snapshot_content_hash
    assert artifact.lineage_selectors, "The snapshot's lineage travels with it."


# ---------------------------------------------------------------------------
# the grid and the data are checked against each other
# ---------------------------------------------------------------------------
#
# Found by adversarial review of the two-phase check, not by trusting it. All
# three reach the same defect from different directions: completeness was
# measured against a grid nothing held to the data, so editing the grid made a
# genuine gap stop being one.


def _late_bar_datasets() -> dict[str, Any]:
    return phase3a.with_bar_available_at(
        phase3a.source_datasets(),
        security_id=SECURITY,
        session_date=MIDDLE,
        provider_available=phase3a.utc(2025, 1, 1, 12, 0),
    )


def test_deleting_a_calendar_row_does_not_shrink_the_grid_past_a_gap(
    tmp_path: Path,
) -> None:
    """The completeness check measuring itself against an edited calendar."""
    datasets = _late_bar_datasets()
    datasets["market_session"] = tuple(
        row
        for row in datasets["market_session"]
        if not (
            isinstance(row, MarketSession)
            and row.session_date == MIDDLE
            and row.exchange is Exchange.NYSE
        )
    )
    reader = phase3a.reader_from(LocalTableStore(tmp_path), datasets)
    with pytest.raises(IncompleteCoverageError) as refusal:
        _series(reader)
    assert "its own calendar and listings do not expect" in str(refusal.value)


def test_flagging_a_session_a_holiday_does_not_shrink_the_grid_either(
    tmp_path: Path,
) -> None:
    """Same defect without removing a row at all."""
    datasets = _late_bar_datasets()
    datasets["market_session"] = tuple(
        dataclasses.replace(row, is_holiday=True)
        if (
            isinstance(row, MarketSession)
            and row.session_date == MIDDLE
            and row.exchange is Exchange.NYSE
        )
        else row
        for row in datasets["market_session"]
    )
    reader = phase3a.reader_from(LocalTableStore(tmp_path), datasets)
    with pytest.raises(IncompleteCoverageError, match="do not expect"):
        _series(reader)


def test_a_listing_revision_published_after_as_of_cannot_shrink_the_grid(
    tmp_path: Path,
) -> None:
    """A 2020 delisting decided a 2019 query's expected sessions.

    Listing rows were the one input that never passed point-in-time filtering, so
    a fact the query was not entitled to see removed the very sessions where a
    genuine gap lay -- and the gap stopped being a gap.
    """
    datasets = phase3a.without_bar(
        phase3a.source_datasets(), security_id=SECURITY, session_date=MIDDLE
    )
    original = next(
        row
        for row in datasets["listing"]
        if isinstance(row, Listing) and row.security_id == SECURITY
    )
    published_later = dataclasses.replace(
        original,
        listing_end=date(2019, 6, 25),
        envelope=dataclasses.replace(
            original.envelope,
            revision_sequence=1,
            public_available_time=phase3a.utc(2020, 6, 1, 20, 0),
            provider_available_time=phase3a.utc(2020, 6, 1, 20, 0),
            system_first_seen_time=phase3a.utc(2020, 6, 1, 20, 0),
            source_id=f"{original.envelope.source_id}:r1",
        ),
    )
    datasets["listing"] = (*datasets["listing"], published_later)

    reader = phase3a.reader_from(LocalTableStore(tmp_path), datasets)
    with pytest.raises(IncompleteCoverageError) as refusal:
        _series(reader)
    assert "has no DAILY bar" in str(refusal.value), (
        "The gap is still a gap: the 2020 revision is not admissible at a 2019 as_of, so it "
        "does not decide which sessions this query expects."
    )


def test_a_required_result_never_carries_a_withheld_endpoint(tmp_path: Path) -> None:
    """The field documents an invariant, so the invariant is enforced.

    A bar the grid does not expect used to be withheld silently and reported in
    ``withheld_endpoints`` on a REQUIRED result -- the invariant's own
    counter-example, returned rather than refused.
    """
    reader = phase3a.reader(LocalTableStore(tmp_path))
    result = _series(reader)
    assert result.requirement is SeriesRequirement.REQUIRED
    assert result.withheld_endpoints == 0

    datasets = _late_bar_datasets()
    datasets["market_session"] = tuple(
        row
        for row in datasets["market_session"]
        if not (
            isinstance(row, MarketSession)
            and row.session_date == MIDDLE
            and row.exchange is Exchange.NYSE
        )
    )
    gapped = phase3a.reader_from(LocalTableStore(tmp_path / "gapped"), datasets)
    with pytest.raises(IncompleteCoverageError):
        _series(gapped)
