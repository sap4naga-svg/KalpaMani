"""Required and governing timing bases are two questions, not one.

``governing_timing_bases`` returned the union of every axis a profile consulted
and called it "the exact governing basis". Under ``PROVIDER_REALISTIC_PIT`` an
authoritative-public row needs **both** a public and a provider time, and its
availability is the later of the two: both are required, one governs. The union
therefore claimed that an exact provider time had determined a cutoff a bounded
public time actually set -- and, on the other side, that a bounded public time had
governed one an exact provider time set.

The distinction is load-bearing because the limitation tokens rest on it. A
bound-required token says the profile could not have admitted the row without a
bounded axis. A governing bound says the bound decided when the row became
usable. A result can incur either without the other.

Every case below is one the union answered wrongly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from kalpamani.data.contracts.envelope import (
    DerivedEnvelope,
    FactAnchor,
    LineageRef,
    OutputValidityDeclaration,
    SourceEnvelope,
)
from kalpamani.data.contracts.resolution import (
    BOUNDED_BASES,
    ApprovedBoundPolicy,
    BoundApprovals,
    PitRecord,
    TimingBasisUsed,
    decision_available_time,
    governing_timing_bases,
    required_timing_bases,
)
from kalpamani.data.contracts.vocabulary import (
    InformationOrigin,
    InformationSetProfile,
    ProviderBoundDerivation,
    ProviderTimeDerivation,
    PublicBoundDerivation,
    PublicTimeDerivation,
)

pytestmark = pytest.mark.unit

PUBLIC = InformationSetProfile.PUBLIC_PIT
PROVIDER = InformationSetProfile.PROVIDER_REALISTIC_PIT
FORWARD = InformationSetProfile.FORWARD_SYSTEM

EARLY = datetime(2019, 1, 1, tzinfo=UTC)
MIDDLE = datetime(2019, 6, 1, tzinfo=UTC)
LATE = datetime(2019, 12, 1, tzinfo=UTC)
LATEST = datetime(2020, 6, 1, tzinfo=UTC)


def _approvals() -> BoundApprovals:
    """Both bound derivations approved, so an unapproved bound never confounds a case."""
    return BoundApprovals(
        by_dataset={
            "price_bar": ApprovedBoundPolicy(
                public=frozenset({PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG}),
                provider=frozenset({ProviderBoundDerivation.DELIVERY_WINDOW}),
            )
        }
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class _Row:
    """A minimal source row. Only its envelope matters to these functions."""

    envelope: SourceEnvelope
    dataset: str = "price_bar"


@dataclass(frozen=True, slots=True, kw_only=True)
class _Derived:
    """A minimal derived artifact, carrying resolved inputs like a real one."""

    envelope: DerivedEnvelope
    inputs: tuple[PitRecord, ...]
    dataset: str = "adjusted_bar_artifact"


def _row(
    *,
    origin: InformationOrigin = InformationOrigin.AUTHORITATIVE_PUBLIC,
    public_exact: datetime | None = None,
    public_bound: datetime | None = None,
    provider_exact: datetime | None = None,
    provider_bound: datetime | None = None,
    first_seen: datetime = EARLY,
) -> _Row:
    return _Row(
        envelope=SourceEnvelope(
            information_origin=origin,
            public_available_time=public_exact,
            public_available_upper_bound=public_bound,
            public_time_derivation=(
                PublicTimeDerivation.AUTHORITATIVE_TIMESTAMP
                if public_exact
                else PublicTimeDerivation.UNKNOWN
            ),
            public_bound_derivation=(
                PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG
                if public_bound
                else PublicBoundDerivation.NONE
            ),
            provider_available_time=provider_exact,
            provider_available_upper_bound=provider_bound,
            provider_time_derivation=(
                ProviderTimeDerivation.VENDOR_STAMPED
                if provider_exact
                else ProviderTimeDerivation.UNKNOWN
            ),
            provider_bound_derivation=(
                ProviderBoundDerivation.DELIVERY_WINDOW
                if provider_bound
                else ProviderBoundDerivation.NONE
            ),
            system_first_seen_time=first_seen,
            anchor=FactAnchor.retrospective(observation_time=EARLY),
            revision_sequence=0,
            source_id="synthetic:1",
            ingestion_time=EARLY,
            dataset_version="gold/synthetic.a1.1",
            provider="synthetic",
        )
    )


def _required(record: PitRecord, profile: InformationSetProfile) -> set[str]:
    return {basis.value for basis in required_timing_bases(record, profile, _approvals())}


def _governing(record: PitRecord, profile: InformationSetProfile) -> set[str]:
    return {basis.value for basis in governing_timing_bases(record, profile, _approvals())}


# ---------------------------------------------------------------------------
# The two questions come apart
# ---------------------------------------------------------------------------


def test_an_earlier_public_bound_is_required_and_does_not_govern() -> None:
    """The bound was needed to admit the row and decided nothing about when.

    Reporting it as governing put a ``PUBLIC_TIME_BOUNDED`` limitation on a cutoff
    an exact provider timestamp had set.
    """
    row = _row(public_bound=EARLY, provider_exact=LATE)
    assert decision_available_time(row, PROVIDER, _approvals()) == LATE
    assert _required(row, PROVIDER) == {"PUBLIC_BOUNDED", "PROVIDER_EXACT"}
    assert _governing(row, PROVIDER) == {"PROVIDER_EXACT"}


def test_a_later_provider_bound_both_is_required_and_governs() -> None:
    """The other direction: the bound is the thing that set the cutoff."""
    row = _row(public_exact=EARLY, provider_bound=LATE)
    assert decision_available_time(row, PROVIDER, _approvals()) == LATE
    assert _required(row, PROVIDER) == {"PUBLIC_EXACT", "PROVIDER_BOUNDED"}
    assert _governing(row, PROVIDER) == {"PROVIDER_BOUNDED"}


def test_two_axes_landing_together_both_govern() -> None:
    """A tie is not a tiebreak. Either axis alone would have set the same instant."""
    row = _row(public_exact=MIDDLE, provider_exact=MIDDLE)
    assert _governing(row, PROVIDER) == {"PUBLIC_EXACT", "PROVIDER_EXACT"}
    assert _required(row, PROVIDER) == {"PUBLIC_EXACT", "PROVIDER_EXACT"}


def test_first_seen_later_than_both_axes_governs_alone_under_forward_system() -> None:
    """We did not hold the row before we first saw it, whatever its other times say."""
    row = _row(public_exact=EARLY, provider_exact=MIDDLE, first_seen=LATE)
    assert decision_available_time(row, FORWARD, _approvals()) == LATE
    assert _governing(row, FORWARD) == {"SYSTEM_FIRST_SEEN"}


def test_forward_system_requires_no_single_axis_when_it_has_several() -> None:
    """Removing one of three leaves two, and the maximum is still computable.

    Deliberately narrow. ``FORWARD_SYSTEM`` takes the max over whichever axes a row
    happens to have, so "required" means something different there -- and reporting
    every present axis as required would put a bound-required limitation on a
    result the bound could not have blocked.
    """
    row = _row(public_bound=EARLY, provider_exact=MIDDLE, first_seen=LATE)
    assert _required(row, FORWARD) == set()
    assert _governing(row, FORWARD) == {"SYSTEM_FIRST_SEEN"}


def test_forward_system_requires_the_only_axis_a_row_has() -> None:
    """NEGATIVE CONTROL. With one axis, that axis is load-bearing."""
    row = _row(first_seen=LATE)
    assert _required(row, FORWARD) == {"SYSTEM_FIRST_SEEN"}
    assert _governing(row, FORWARD) == {"SYSTEM_FIRST_SEEN"}


def test_public_pit_consults_one_axis_so_it_both_requires_and_governs() -> None:
    """NEGATIVE CONTROL for the split: where there is one axis the two agree."""
    row = _row(public_bound=MIDDLE, provider_exact=EARLY)
    assert _required(row, PUBLIC) == {"PUBLIC_BOUNDED"}
    assert _governing(row, PUBLIC) == {"PUBLIC_BOUNDED"}


def test_a_provider_derived_row_is_governed_by_its_provider_axis_alone() -> None:
    """There is no public axis to require: the fact is the vendor's construction."""
    row = _row(
        origin=InformationOrigin.PROVIDER_DERIVED,
        public_exact=LATEST,
        provider_bound=MIDDLE,
    )
    assert _required(row, PROVIDER) == {"PROVIDER_BOUNDED"}
    assert _governing(row, PROVIDER) == {"PROVIDER_BOUNDED"}


def test_a_row_the_profile_cannot_resolve_has_no_basis_at_all() -> None:
    """Neither required nor governing. A basis for an inadmissible row is a fiction."""
    row = _row(public_exact=EARLY)  # No provider axis at all.
    assert decision_available_time(row, PROVIDER, _approvals()) is None
    assert _required(row, PROVIDER) == set()
    assert _governing(row, PROVIDER) == set()


# ---------------------------------------------------------------------------
# Derived artifacts govern through their slowest input
# ---------------------------------------------------------------------------


def _derived(*inputs: PitRecord, built: datetime = EARLY) -> _Derived:
    return _Derived(
        envelope=DerivedEnvelope(
            derivation_spec_version="spec/1",
            artifact_content_hash="sha256:x",
            artifact_first_built_time=built,
            ingestion_time=EARLY,
            dataset_version="gold/synthetic.a1.1",
            lineage=tuple(
                LineageRef.of(
                    entity="price_bar",
                    dataset_version="gold/synthetic.a1.1",
                    selector={"n": str(index)},
                )
                for index, _ in enumerate(inputs)
            ),
            validity=OutputValidityDeclaration.interval(EARLY.date(), LATE.date()),
        ),
        inputs=tuple(inputs),
    )


def test_a_derived_artifact_governs_through_its_slowest_input_only() -> None:
    """A union over every input reported a fast exact one as having governed.

    One input is exact and slow; the other is bounded and fast. The artifact is as
    available as the slow one, so the fast bound decided nothing -- and reporting
    ``PROVIDER_BOUNDED`` as governing said a bound had set a cutoff an exact
    timestamp set.
    """
    fast_bounded = _row(public_exact=EARLY, provider_bound=EARLY)
    slow_exact = _row(public_exact=EARLY, provider_exact=LATE)
    artifact = _derived(fast_bounded, slow_exact)

    assert decision_available_time(artifact, PROVIDER, _approvals()) == LATE
    assert _governing(artifact, PROVIDER) == {"DERIVED_FROM_INPUTS", "PROVIDER_EXACT"}
    assert "PROVIDER_BOUNDED" in _required(artifact, PROVIDER), (
        "The bound was still needed to admit the fast input, which is a real limitation."
    )


def test_a_derived_artifacts_required_evidence_follows_every_input() -> None:
    """An artifact whose input cannot resolve cannot resolve either."""
    bounded = _row(public_bound=EARLY, provider_exact=EARLY)
    exact = _row(public_exact=MIDDLE, provider_exact=MIDDLE)
    artifact = _derived(bounded, exact)
    assert _required(artifact, PROVIDER) >= {
        "DERIVED_FROM_INPUTS",
        "PUBLIC_BOUNDED",
        "PUBLIC_EXACT",
        "PROVIDER_EXACT",
    }


def test_first_built_governs_a_derived_artifact_when_it_is_the_maximum() -> None:
    """Under FORWARD_SYSTEM we did not hold a computed value before computing it."""
    inputs = _row(public_exact=EARLY, provider_exact=EARLY, first_seen=EARLY)
    artifact = _derived(inputs, built=LATE)
    assert decision_available_time(artifact, FORWARD, _approvals()) == LATE
    assert _governing(artifact, FORWARD) == {"ARTIFACT_FIRST_BUILT"}
    assert "ARTIFACT_FIRST_BUILT" in _required(artifact, FORWARD)


def test_first_built_and_the_lineage_can_govern_together() -> None:
    """A tie at the top is two governing axes, not a coin toss."""
    inputs = _row(public_exact=EARLY, provider_exact=EARLY, first_seen=MIDDLE)
    artifact = _derived(inputs, built=MIDDLE)
    assert _governing(artifact, FORWARD) == {
        "ARTIFACT_FIRST_BUILT",
        "DERIVED_FROM_INPUTS",
        "SYSTEM_FIRST_SEEN",
    }


def test_first_built_does_not_govern_when_an_input_is_slower() -> None:
    """NEGATIVE CONTROL. Building early does not make a late input early."""
    inputs = _row(public_exact=EARLY, provider_exact=EARLY, first_seen=LATE)
    artifact = _derived(inputs, built=EARLY)
    assert _governing(artifact, FORWARD) == {"DERIVED_FROM_INPUTS", "SYSTEM_FIRST_SEEN"}


def test_the_bounded_axes_are_named_in_one_place() -> None:
    """Both the evidence and the tokens ask "was a bound involved", so they share it."""
    assert BOUNDED_BASES == frozenset(
        {TimingBasisUsed.PUBLIC_BOUNDED, TimingBasisUsed.PROVIDER_BOUNDED}
    )
