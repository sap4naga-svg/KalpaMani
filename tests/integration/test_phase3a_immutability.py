"""A frozen dataclass wrapping a caller's dictionary is not frozen.

``frozen=True`` refuses reassignment of the attribute. It says nothing about the
object the attribute points at, and two of the values that decide what a query
returns were exactly that::

    source = {"price_bar": strict}
    approvals = BoundApprovals(by_dataset=source)
    reader = PointInTimeReader(publication, resolution=..., approvals=approvals)

    source["price_bar"] = permissive

Nothing in that sequence touches the frozen object. The reader has already
compared these approvals against the publication's persisted standard and found
them equal; from the next query onward it resolves rows under approvals nobody
agreed to. ``QualityContext.evaluation_cutoffs`` had the same shape: a caller
could move the instant a snapshot was evaluated at *after* the descriptor was
generated and the context hash taken, so the standard a build was judged against
moved while every hash over it went on agreeing with itself.

Both are now copied and proxied at construction. Every test here mutates a source
mapping after the fact and asserts that nothing downstream moved -- and the last
one builds a genuinely different approvals object, so the others are not merely
comparing a value to itself.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.errors import DatasetPublicationError
from kalpamani.data.contracts.resolution import (
    NO_BOUNDS_APPROVED,
    ApprovedBoundPolicy,
    BoundApprovals,
)
from kalpamani.data.contracts.vocabulary import (
    RAW,
    BarResolution,
    InformationSetProfile,
    ProviderBoundDerivation,
    PublicBoundDerivation,
)
from kalpamani.data.pit.accessors import PointInTimeReader, SeriesRequirement
from kalpamani.data.quality.runner import run_quality_plan
from kalpamani.data.storage import LocalTableStore

pytestmark = pytest.mark.integration

PUBLIC = InformationSetProfile.PUBLIC_PIT
SECURITY = phase3a.SEC_CONTINUOUS
FIRST = date(2019, 6, 24)
LAST = date(2019, 6, 28)
SETTLED = phase3a.utc(2019, 7, 1, 12, 0)


def _series(reader: PointInTimeReader) -> Any:
    return reader.get_price_history(
        security_id=SECURITY,
        start=FIRST,
        end=LAST,
        resolution=BarResolution.DAILY,
        adjustment_mode=RAW,
        as_of=SETTLED,
        profile=PUBLIC,
        requirement=SeriesRequirement.REQUIRED,
        revision_view=None,
    )


def _permissive() -> ApprovedBoundPolicy:
    """A genuinely different policy: everything approved rather than the one thing."""
    return ApprovedBoundPolicy(
        public=frozenset(PublicBoundDerivation),
        provider=frozenset(ProviderBoundDerivation),
    )


# ---------------------------------------------------------------------------
# A -- mutating the source mapping afterwards
# ---------------------------------------------------------------------------


def test_mutating_the_source_mapping_does_not_reach_the_approvals() -> None:
    """The dictionary the caller still holds is not the one the object uses."""
    strict = phase3a.approvals().for_dataset("price_bar")
    source = {"price_bar": strict}
    approvals = BoundApprovals(by_dataset=source)
    before_canonical = approvals.canonical()
    before_identity = approvals.identity()

    source["price_bar"] = _permissive()
    source["listing"] = _permissive()
    source.clear()

    assert approvals.canonical() == before_canonical
    assert approvals.identity() == before_identity
    assert approvals.for_dataset("price_bar") == strict, (
        "The policy the object serves is the one it was constructed with."
    )
    assert approvals.for_dataset("price_bar") != _permissive(), (
        "And the replacement written into the source reached nothing."
    )
    assert approvals.for_dataset("listing") is NO_BOUNDS_APPROVED, (
        "A key added to the source afterwards is not a key this object has."
    )


def test_mutating_the_source_cutoffs_does_not_reach_the_context() -> None:
    """The same shape, on the mapping that decides what each snapshot was built from."""
    dataset = phase3a.gold_dataset()
    source = {session: phase3a.session_open(session) for session in phase3a.SNAPSHOT_SESSIONS}
    context = dataclasses.replace(phase3a.quality_context(dataset), evaluation_cutoffs=source)
    before = context.cutoff_rows()
    before_hash = context.context_hash()

    moved = next(iter(source))
    source[moved] = source[moved] + timedelta(days=400)
    source[date(2030, 1, 1)] = phase3a.BUILD_TIME

    assert context.cutoff_rows() == before
    assert context.context_hash() == before_hash


# ---------------------------------------------------------------------------
# B -- mutating through the object
# ---------------------------------------------------------------------------


def test_the_approvals_mapping_cannot_be_written_through() -> None:
    """``approvals.by_dataset[...] = ...`` is the shortest route, and it is closed."""
    approvals = phase3a.approvals()
    assert isinstance(approvals.by_dataset, MappingProxyType)
    with pytest.raises(TypeError):
        approvals.by_dataset["price_bar"] = _permissive()  # type: ignore[index]
    with pytest.raises(TypeError):
        del approvals.by_dataset["price_bar"]  # type: ignore[attr-defined]
    with pytest.raises(dataclasses.FrozenInstanceError):
        approvals.by_dataset = {}  # type: ignore[misc]


def test_the_cutoff_mapping_cannot_be_written_through() -> None:
    """And the nested policies are frozen dataclasses over frozensets, to the leaves."""
    context = phase3a.quality_context(phase3a.gold_dataset())
    assert isinstance(context.evaluation_cutoffs, MappingProxyType)
    with pytest.raises(TypeError):
        context.evaluation_cutoffs[date(2030, 1, 1)] = phase3a.BUILD_TIME  # type: ignore[index]

    policy = phase3a.approvals().for_dataset("price_bar")
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.public = frozenset()  # type: ignore[misc]
    with pytest.raises(AttributeError):
        policy.public.add(PublicBoundDerivation.DATE_PLUS_LAG)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# C -- a reader is stable across a mutation of what built it
# ---------------------------------------------------------------------------


def test_a_readers_answers_do_not_move_when_the_source_mapping_does(
    tmp_path: Path,
) -> None:
    """The case the deep-freeze exists for.

    The reader compared these approvals against the publication's persisted
    standard at construction and found them equal. Every later query has to be
    answered under the approvals that comparison was about.
    """
    source = dict(phase3a.approvals().by_dataset)
    approvals = BoundApprovals(by_dataset=source)
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    reader = PointInTimeReader(publication, resolution=phase3a.resolution(), approvals=approvals)
    identity = reader.approvals_identity

    first = _series(reader)
    source["price_bar"] = _permissive()
    source["market_session"] = _permissive()
    again = _series(reader)

    assert reader.approvals_identity == identity
    assert again.result_bytes == first.result_bytes
    assert again.result_bytes_hash == first.result_bytes_hash
    assert again.query.identity() == first.query.identity()
    assert again.evidence.identity() == first.evidence.identity()
    assert again.evidence.timing_evidence == first.evidence.timing_evidence


def test_a_reader_binds_once_because_the_value_cannot_change(tmp_path: Path) -> None:
    """Why one construction-time comparison is enough, stated as a property.

    ``BoundApprovals`` copies its mapping, proxies it, and holds frozen policies
    over frozensets, so the value compared at construction is the value every
    query uses. Re-deriving that comparison before each accessor call would be a
    check with no reachable failure -- which is how a guard becomes decoration.
    The identity is kept instead, so the fact can be observed.
    """
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    approvals = phase3a.approvals()
    reader = PointInTimeReader(publication, resolution=phase3a.resolution(), approvals=approvals)
    assert reader.approvals_identity == approvals.identity()
    _series(reader)
    reader.get_security_universe(as_of=phase3a.utc(2019, 6, 27, 20, 0), profile=PUBLIC)
    assert reader.approvals_identity == approvals.identity()


# ---------------------------------------------------------------------------
# D -- a quality outcome is stable across a mutation of what built it
# ---------------------------------------------------------------------------


def test_a_quality_outcome_does_not_move_when_its_source_mappings_do() -> None:
    """The descriptor, the context hash, the report hash and the outcome, all fixed.

    A caller who could move a cutoff or an approval after the run could change
    the standard a published dataset records having passed, while every hash over
    that standard went on agreeing with itself.
    """
    dataset = phase3a.gold_dataset()
    cutoffs = {session: phase3a.session_open(session) for session in phase3a.SNAPSHOT_SESSIONS}
    approval_source = dict(phase3a.approvals().by_dataset)
    context = dataclasses.replace(
        phase3a.quality_context(dataset),
        evaluation_cutoffs=cutoffs,
        approvals=BoundApprovals(by_dataset=approval_source),
    )
    outcome = run_quality_plan(context, policy_versions={"lag": phase3a.LAG_POLICY_VERSION})
    descriptor = outcome.report.quality_context
    report_hash = outcome.report.report_hash
    context_hash = context.context_hash()

    cutoffs[next(iter(cutoffs))] += timedelta(days=400)
    cutoffs[date(2030, 1, 1)] = phase3a.BUILD_TIME
    approval_source["price_bar"] = _permissive()
    approval_source.clear()

    assert outcome.report.quality_context == descriptor
    assert outcome.quality_context_hash == descriptor.identity()
    assert outcome.report.quality_context_hash == descriptor.identity()
    assert outcome.report.report_hash == report_hash
    assert context.context_hash() == context_hash, (
        "The context recomputes the same standard after its source mappings moved."
    )

    rerun = run_quality_plan(context, policy_versions={"lag": phase3a.LAG_POLICY_VERSION})
    assert rerun.report.report_hash == report_hash, (
        "And re-running over that context reaches the same report."
    )


# ---------------------------------------------------------------------------
# E -- a genuinely different policy is genuinely different
# ---------------------------------------------------------------------------


def test_a_different_immutable_policy_changes_the_answer_or_is_refused(
    tmp_path: Path,
) -> None:
    """Without this the tests above would pass against a value compared to itself.

    A new ``BoundApprovals`` with a different policy has a different identity, a
    different quality-context hash, and cannot be used to read a publication built
    under the original -- which is what makes the stability above meaningful.
    """
    original = phase3a.approvals()
    different = BoundApprovals(by_dataset={**dict(original.by_dataset), "price_bar": _permissive()})
    assert different.identity() != original.identity()
    assert different.canonical() != original.canonical()

    dataset = phase3a.gold_dataset()
    base = phase3a.quality_context(dataset)
    assert dataclasses.replace(base, approvals=different).context_hash() != base.context_hash(), (
        "A different standard is a different context."
    )

    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    with pytest.raises(DatasetPublicationError, match="approves bound derivations"):
        PointInTimeReader(publication, resolution=phase3a.resolution(), approvals=different)


# ---------------------------------------------------------------------------
# The annotations are coerced, not trusted
# ---------------------------------------------------------------------------


def test_a_mutable_set_supplied_where_a_frozenset_is_declared_is_rebuilt() -> None:
    """``frozenset[...]`` is a type hint, and nothing enforces it at runtime.

    The same defect as a frozen dataclass wrapping a caller's dict, one level
    down: ``ApprovedBoundPolicy(public={x})`` stored the caller's mutable ``set``
    inside a value the rest of the system treats as immutable.
    """
    source = {PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG}
    policy = ApprovedBoundPolicy(public=source)  # type: ignore[arg-type]
    assert type(policy.public) is frozenset

    source.add(PublicBoundDerivation.DATE_PLUS_LAG)
    assert PublicBoundDerivation.DATE_PLUS_LAG not in policy.public, (
        "The set the caller still holds is not the one the policy uses."
    )


def test_a_frozenset_subclass_cannot_split_membership_from_the_record() -> None:
    """Worse than a mutable set: two questions, two different answers.

    ``derivation in policy.public`` is what resolution reads; iterating the same
    field is what :meth:`BoundApprovals.canonical` records. A subclass overriding
    ``__contains__`` makes those disagree, so the bounds a dataset resolves under
    and the bounds the persisted standard names come apart with no hash moving.
    """

    class Liar(frozenset):  # type: ignore[type-arg]
        def __contains__(self, item: object) -> bool:
            return True

    policy = ApprovedBoundPolicy(public=Liar())
    assert type(policy.public) is frozenset
    assert PublicBoundDerivation.DATE_PLUS_LAG not in policy.public
    assert tuple(policy.public) == ()


def test_a_key_with_an_unstable_equality_cannot_reach_the_mapping() -> None:
    """``for_dataset`` must answer the same way twice.

    A ``str`` subclass whose ``__eq__`` alternates answers a lookup differently on
    successive calls while ``canonical()`` goes on reporting one value — so the
    resolution and the recorded standard disagree about which bounds a dataset
    approves, and nothing observable moves.
    """

    class Unstable(str):
        # Deliberately mutable class state: the whole point is a key whose
        # equality answers differently on successive calls.
        _flip: ClassVar[list[bool]] = [False]

        def __eq__(self, other: object) -> bool:
            self._flip[0] = not self._flip[0]
            return self._flip[0] and str(self) == other

        def __hash__(self) -> int:
            return hash(str(self))

    approvals = BoundApprovals(by_dataset={Unstable("price_bar"): _permissive()})
    assert all(type(key) is str for key in approvals.by_dataset)
    assert {approvals.for_dataset("price_bar") == _permissive() for _ in range(8)} == {True}
    assert approvals.canonical()[0][0] == "price_bar"


def test_the_types_the_reader_binds_to_may_not_be_subclassed() -> None:
    """Coercion and accessors are both overridable, so a subclass is a route past both.

    The same shape as the ``VerifiedPublication`` subclass route closed in the
    previous round, on the two values that decide what a query returns.
    ``ProfileResolutionConfig`` matters most: the reader compares it against the
    publication **once** and then re-reads ``resolved_profile`` on every query, so
    an override could answer the agreement check and the queries differently.
    """
    from kalpamani.data.contracts.errors import ProfileResolutionError
    from kalpamani.data.contracts.profiles import ProfileResolutionConfig

    for base in (ApprovedBoundPolicy, BoundApprovals, ProfileResolutionConfig):
        with pytest.raises(ProfileResolutionError, match="may not be subclassed"):
            type("Forged", (base,), {})


def test_a_reader_refuses_a_config_or_approvals_of_the_wrong_type(tmp_path: Path) -> None:
    """Checked at the boundary as well, so relaxing a refusal cannot reopen the door."""
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))
    with pytest.raises(DatasetPublicationError, match="where a BoundApprovals is required"):
        PointInTimeReader(
            publication,
            resolution=phase3a.resolution(),
            approvals=phase3a.resolution(),  # type: ignore[arg-type]
        )
    with pytest.raises(
        DatasetPublicationError, match="where a ProfileResolutionConfig is required"
    ):
        PointInTimeReader(
            publication,
            resolution=phase3a.approvals(),  # type: ignore[arg-type]
            approvals=phase3a.approvals(),
        )


def test_the_registry_identity_covers_what_each_check_does() -> None:
    """Ids and declared findings left the executable half outside the identity.

    ``invoke``, ``applicable`` and ``subjects`` are the parts that decide what is
    actually looked at, so a registry whose implementations all return nothing
    hashed identically to the real one — and the persisted standard's record of
    "which implementations ran" agreed with itself while a different set ran.
    """
    from kalpamani.data.quality.runner import CHECK_REGISTRY, registry_identity

    gutted = {
        ident: dataclasses.replace(implementation, invoke=lambda context: [])
        for ident, implementation in CHECK_REGISTRY.items()
    }
    assert set(gutted) == set(CHECK_REGISTRY), "Same ids, same declared findings."
    assert registry_identity(gutted) != registry_identity(CHECK_REGISTRY)


def test_a_universe_rule_supplied_with_mutable_sets_is_rebuilt() -> None:
    """The rule's parameters are hashed into the persisted standard.

    ``eligible_exchanges: frozenset[...]`` accepts a mutable ``set``, so a caller
    keeping it could widen the eligible venues after the standard recorded them.
    """
    from kalpamani.data.contracts.vocabulary import Exchange
    from kalpamani.data.curate.universe import UniverseDefinition, definition_hash

    base = phase3a.universe_definition()
    venues = {Exchange.NYSE}
    definition = UniverseDefinition(
        version=base.version,
        min_close_price=base.min_close_price,
        min_addv=base.min_addv,
        min_history_sessions=base.min_history_sessions,
        addv_window_sessions=base.addv_window_sessions,
        eligible_exchanges=venues,  # type: ignore[arg-type]
        eligible_security_types=base.eligible_security_types,
    )
    recorded = definition_hash(definition)
    venues.add(Exchange.NASDAQ)

    assert type(definition.eligible_exchanges) is frozenset
    assert definition_hash(definition) == recorded
    assert Exchange.NASDAQ not in definition.eligible_exchanges


def test_a_resolution_config_supplied_with_a_list_is_rebuilt() -> None:
    """It is hashed into the persisted standard and re-read on every query."""
    from kalpamani.data.contracts.profiles import ProfileResolutionConfig

    reference = phase3a.resolution()
    supplied = list(reference.dataset_resolutions)
    config = ProfileResolutionConfig(
        requested_profile=reference.requested_profile,
        resolution_policy_version=reference.resolution_policy_version,
        dataset_resolutions=supplied,  # type: ignore[arg-type]
    )
    canonical = config.canonical_map()
    supplied.clear()

    assert type(config.dataset_resolutions) is tuple
    assert config.canonical_map() == canonical


def test_the_rows_a_derived_artifact_consumed_reach_the_build_identity() -> None:
    """``inputs`` decide availability and eligibility, and nothing hashed them.

    ``decision_available_time`` walks them and
    ``6.6_eligibility_from_inadmissible_data`` examines them, so dropping one
    changed what the checks looked at and what the snapshot was available from
    while the header's identity, the build's and the descriptor's all stayed put.
    """
    dataset = phase3a.gold_dataset()
    before = dataset.build_identity
    session = next(iter(dataset.universe_headers))
    header = dataset.universe_headers[session]
    assert header.inputs, "The header records the rows it consumed."

    thinner = dataclasses.replace(header, inputs=header.inputs[:-1])
    moved = dataclasses.replace(
        dataset, universe_headers={**dict(dataset.universe_headers), session: thinner}
    )
    assert moved.build_identity != before


def test_a_derived_row_with_no_inputs_is_unresolvable_not_a_crash() -> None:
    """Not hypothetical: ``inputs`` are in-memory only, so every decoded header is empty.

    ``max()`` over nothing raises. The reader guarded this and the quality path
    did not, so a decoded header reached the check and came out as a bare
    ``ValueError`` from inside it. Unresolvable is the honest answer.
    """
    from kalpamani.data.contracts.resolution import decision_available_time

    dataset = phase3a.gold_dataset()
    header = dataset.universe_headers[next(iter(dataset.universe_headers))]
    stripped = dataclasses.replace(header, inputs=())
    assert decision_available_time(stripped, dataset.resolved_profile, phase3a.approvals()) is None
    assert (
        decision_available_time(header, dataset.resolved_profile, phase3a.approvals()) is not None
    ), "NEGATIVE CONTROL: the untouched header resolves."
