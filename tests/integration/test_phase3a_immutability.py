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
from kalpamani.data.contracts.errors import DatasetPublicationError, ProfileResolutionError
from kalpamani.data.contracts.profiles import DatasetGapResolution, ProfileResolutionConfig
from kalpamani.data.contracts.resolution import (
    NO_BOUNDS_APPROVED,
    ApprovedBoundPolicy,
    BoundApprovals,
)
from kalpamani.data.contracts.vocabulary import (
    RAW,
    BarResolution,
    DatasetGapPolicy,
    GlobalProfileResolution,
    InformationSetProfile,
    ProviderBoundDerivation,
    PublicBoundDerivation,
)
from kalpamani.data.pit.accessors import PointInTimeReader, SeriesRequirement
from kalpamani.data.quality.runner import run_quality_plan
from kalpamani.data.storage import LocalTableStore

pytestmark = pytest.mark.integration

#: The A1 record, checked by one test for the rule it previously stated wrongly.
KERNEL_DOCUMENT = "phase3a-a1-foundation-kernel.md"

PUBLIC = InformationSetProfile.PUBLIC_PIT
PROVIDER = InformationSetProfile.PROVIDER_REALISTIC_PIT
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


class _FakePolicy:
    """Policy-shaped, mutable, and not an ``ApprovedBoundPolicy``."""

    def __init__(self) -> None:
        self.public: set[PublicBoundDerivation] = set()
        self.provider: set[object] = set()
        self.announcement: set[object] = set()


@dataclasses.dataclass(frozen=True)
class _Lookalike:
    """An unrelated dataclass carrying the three governed field names."""

    public: frozenset[PublicBoundDerivation] = frozenset()
    provider: frozenset[object] = frozenset()
    announcement: frozenset[object] = frozenset()


class _FakeResolution:
    """Resolution-shaped and mutable. ``policy`` can change between reads."""

    def __init__(self) -> None:
        self.dataset = "price_bar"
        self.policy = DatasetGapPolicy.BOUND
        self.reason = "a reason nobody normalised"


class _Renamed(str):
    """A ``str`` subclass, so two entries can differ in type and not in name."""


class _NormalisesToOneName:
    """Two distinct keys that both ``str()`` to the same dataset name."""

    def __init__(self, tag: int) -> None:
        self.tag = tag

    def __str__(self) -> str:
        return "price_bar"

    def __lt__(self, other: object) -> bool:
        return self.tag < getattr(other, "tag", 0)


def _permissive() -> ApprovedBoundPolicy:
    """A genuinely different policy: every real derivation, rather than the one.

    NONE is excluded because it is not a derivation -- it is the absence of
    one, and the constructor refuses it for exactly that reason.
    """
    return ApprovedBoundPolicy(
        public=frozenset(item for item in PublicBoundDerivation if item.value != "NONE"),
        provider=frozenset(item for item in ProviderBoundDerivation if item.value != "NONE"),
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


# ---------------------------------------------------------------------------
# The nested types are closed as well as frozen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ({"SESSION_CLOSE_PLUS_LAG"}, PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG),
        (
            frozenset({PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG}),
            PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG,
        ),
    ],
    ids=["a plain valid string", "the member itself"],
)
def test_an_approved_derivation_is_normalised_to_its_exact_enum(
    supplied: object, expected: PublicBoundDerivation
) -> None:
    """Rebuilding the container left the elements as whatever the caller put in.

    The resolution asks ``envelope.public_bound_derivation in policy.public`` --
    a membership test -- and the descriptor records ``item.value``. An object
    answering ``__eq__``, ``__hash__`` and ``.value`` however it liked satisfied
    both, and could answer them inconsistently.
    """
    policy = ApprovedBoundPolicy(public=supplied)  # type: ignore[arg-type]
    (member,) = policy.public
    assert member is expected
    assert type(member) is PublicBoundDerivation


@pytest.mark.parametrize(
    "supplied",
    [{"NOT-A-DERIVATION"}, {DatasetGapPolicy.BOUND}],
    ids=["an unknown string", "a member of the wrong enum"],
)
def test_an_unrecognised_approved_derivation_is_refused_at_construction(
    supplied: object,
) -> None:
    """Where a caller can still act on it, not at the first membership test."""
    with pytest.raises(ProfileResolutionError, match="is not a PublicBoundDerivation"):
        ApprovedBoundPolicy(public=supplied)  # type: ignore[arg-type]


def test_an_object_that_answers_for_itself_never_reaches_the_enum_lookup() -> None:
    """The sharpest case, and the one the constructor alone did **not** close.

    ``Enum(value)`` is a ``_value2member_map_`` dict lookup, and a dict lookup
    compares the *stored* key against the supplied object -- delegating ``__eq__``
    to the thing being validated. An object with a colliding ``__hash__`` and a
    permissive ``__eq__`` is therefore found, and silently becomes a real member.

    ``Shifty`` below is refused today for the right reason: it is not a string, so
    it never reaches the lookup. ``Colliding`` is the version that used to get
    through -- it hashes exactly as the value it impersonates -- and is the reason
    "the constructor is the validator" was not sufficient on its own.
    """

    class Shifty:
        def __init__(self) -> None:
            self.value = "SESSION_CLOSE_PLUS_LAG"

        def __hash__(self) -> int:
            return 0

        def __eq__(self, other: object) -> bool:
            return True

    class Colliding:
        def __hash__(self) -> int:
            return hash("SESSION_CLOSE_PLUS_LAG")

        def __eq__(self, other: object) -> bool:
            return True

    for hostile in (Shifty(), Colliding()):
        with pytest.raises(ProfileResolutionError, match="is named by a string"):
            ApprovedBoundPolicy(public={hostile})  # type: ignore[arg-type]

    # NEGATIVE CONTROL: the two string-shaped spellings still pass.
    expected = frozenset({PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG})
    spelled = ApprovedBoundPolicy(
        public={"SESSION_CLOSE_PLUS_LAG"}  # type: ignore[arg-type]
    )
    assert spelled.public == expected
    assert ApprovedBoundPolicy(public=expected).public == expected


def test_resolution_and_the_record_observe_the_same_exact_members() -> None:
    """The two readers of a policy must be reading one thing.

    ``canonical()`` iterates the field; the resolution tests membership in it.
    Normalised elements make those the same set by construction.
    """
    approvals = BoundApprovals(
        by_dataset={"price_bar": ApprovedBoundPolicy(public={"SESSION_CLOSE_PLUS_LAG"})}  # type: ignore[arg-type]
    )
    policy = approvals.for_dataset("price_bar")
    recorded = {dataset: public for dataset, public, _, _ in approvals.canonical()}["price_bar"]

    assert recorded == ("SESSION_CLOSE_PLUS_LAG",)
    for name in recorded:
        assert PublicBoundDerivation(name) in policy.public, (
            "What the standard records is what a membership test finds."
        )
    assert {member.value for member in policy.public} == set(recorded)


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (lambda: {"price_bar": _FakePolicy()}, "not an exact ApprovedBoundPolicy"),
        (lambda: {"price_bar": _Lookalike()}, "not an exact ApprovedBoundPolicy"),
        (lambda: {"": ApprovedBoundPolicy()}, "empty dataset name"),
    ],
    ids=["a mutable policy-shaped object", "an unrelated dataclass", "an empty key"],
)
def test_bound_approvals_stores_only_exact_policies(build: Any, match: str) -> None:
    """Fail closed rather than duck-type.

    A policy-shaped object supplies its own ``public``/``provider``/
    ``announcement``, so it can answer the resolution's membership test and the
    descriptor's iteration differently -- and it is the value that decides which
    rows resolve at all.
    """
    with pytest.raises(ProfileResolutionError, match=match):
        BoundApprovals(by_dataset=build())


def test_a_refused_fake_policy_cannot_affect_anything_afterwards() -> None:
    """Refusal precedes retention, so mutating the refused object reaches nothing."""
    fake = _FakePolicy()
    with pytest.raises(ProfileResolutionError):
        BoundApprovals(by_dataset={"price_bar": fake})  # type: ignore[dict-item]

    fake.public.add(PublicBoundDerivation.DATE_PLUS_LAG)
    honest = BoundApprovals(by_dataset={"price_bar": ApprovedBoundPolicy()})
    assert honest.for_dataset("price_bar").public == frozenset()
    assert honest.canonical() == (("price_bar", (), (), ()),)


def test_two_keys_that_normalise_to_one_name_are_refused() -> None:
    """Detected **after** normalisation, which is the only place it is visible.

    Normalising inside the sort let the later of two colliding keys win by
    iteration order, so which bounds a dataset approves would have been a
    property of how the caller happened to build their mapping.
    """
    source = {
        _NormalisesToOneName(1): ApprovedBoundPolicy(),
        _NormalisesToOneName(2): ApprovedBoundPolicy(),
    }
    assert len(source) == 2, "Two distinct keys, one normalised name."
    with pytest.raises(ProfileResolutionError, match="normalise to the same dataset name"):
        BoundApprovals(by_dataset=source)  # type: ignore[arg-type]


def test_key_normalisation_is_deterministic_and_precedes_sorting() -> None:
    """Whatever order the caller built the mapping in, the canonical form is one."""
    policies = {
        "ticker_history": ApprovedBoundPolicy(),
        "corporate_action": ApprovedBoundPolicy(public={"DATE_PLUS_LAG"}),  # type: ignore[arg-type]
        "price_bar": ApprovedBoundPolicy(public={"SESSION_CLOSE_PLUS_LAG"}),  # type: ignore[arg-type]
    }
    forward = BoundApprovals(by_dataset=dict(policies))
    backward = BoundApprovals(by_dataset=dict(reversed(list(policies.items()))))

    assert [name for name, *_ in forward.canonical()] == [
        "corporate_action",
        "price_bar",
        "ticker_history",
    ]
    assert forward.canonical() == backward.canonical()
    assert forward.identity() == backward.identity()


# ---------------------------------------------------------------------------
# The gap-resolution entries are closed too
# ---------------------------------------------------------------------------


def _resolution(dataset: str, policy: object, reason: str = "why") -> DatasetGapResolution:
    return DatasetGapResolution(
        dataset=dataset,
        policy=policy,  # type: ignore[arg-type]
        reason=reason,
    )


def test_a_gap_policy_is_normalised_to_its_exact_enum() -> None:
    """A plain valid string is accepted and becomes the member."""
    entry = _resolution("price_bar", "BOUND")
    assert entry.policy is DatasetGapPolicy.BOUND
    assert type(entry.policy) is DatasetGapPolicy
    assert type(entry.dataset) is str


@pytest.mark.parametrize(
    ("dataset", "policy", "reason", "match"),
    [
        ("price_bar", "NOT-A-POLICY", "why", "is not a DatasetGapPolicy"),
        ("", DatasetGapPolicy.NONE, "why", "no dataset name"),
        ("price_bar", DatasetGapPolicy.NONE, "", "states no reason"),
    ],
    ids=["an invalid policy", "an empty dataset", "an empty reason"],
)
def test_an_unusable_gap_resolution_is_refused_at_construction(
    dataset: str, policy: object, reason: str, match: str
) -> None:
    """The policy decides whether a dataset's rows are excluded, bounded or kept."""
    with pytest.raises(ProfileResolutionError, match=match):
        _resolution(dataset, policy, reason)


def test_a_gap_resolution_may_not_be_subclassed() -> None:
    """``policy`` is read by the run and again by the record of what the run did."""
    with pytest.raises(ProfileResolutionError, match="may not be subclassed"):
        type("Forged", (DatasetGapResolution,), {})


def test_a_config_stores_only_exact_gap_resolutions() -> None:
    """The outer sequence was tuple-coerced and its entries trusted whole.

    A resolution-shaped object supplies its own ``policy``, so it can answer
    ``policy_for`` -- which the run consults -- differently from
    ``canonical_map``, which the persisted standard and ``run_id`` record.
    """
    with pytest.raises(ProfileResolutionError, match="not an exact DatasetGapResolution"):
        ProfileResolutionConfig(
            requested_profile=PUBLIC,
            resolution_policy_version="policy/synthetic.1",
            dataset_resolutions=(_FakeResolution(),),  # type: ignore[arg-type]
        )


def test_a_refused_fake_resolution_cannot_affect_anything_afterwards() -> None:
    """And mutating it after the refusal reaches nothing that was retained."""
    fake = _FakeResolution()
    with pytest.raises(ProfileResolutionError):
        ProfileResolutionConfig(
            requested_profile=PUBLIC,
            resolution_policy_version="policy/synthetic.1",
            dataset_resolutions=(fake,),  # type: ignore[arg-type]
        )
    fake.policy = DatasetGapPolicy.EXCLUDE

    honest = ProfileResolutionConfig(
        requested_profile=PUBLIC,
        resolution_policy_version="policy/synthetic.1",
        dataset_resolutions=(_resolution("price_bar", DatasetGapPolicy.NONE),),
    )
    assert honest.policy_for("price_bar") is DatasetGapPolicy.NONE
    assert honest.canonical_map() == (("price_bar", "NONE", "why"),)


def test_mutating_the_source_sequence_does_not_reach_the_config() -> None:
    """A list passed for a ``tuple[...]`` field stays a list unless it is rebuilt."""
    source = [
        _resolution("z_dataset", DatasetGapPolicy.NONE),
        _resolution("a_dataset", DatasetGapPolicy.BOUND),
    ]
    config = ProfileResolutionConfig(
        requested_profile=PUBLIC,
        resolution_policy_version="policy/synthetic.1",
        dataset_resolutions=source,  # type: ignore[arg-type]
    )
    canonical = config.canonical_map()
    source.clear()
    source.append(_resolution("smuggled", DatasetGapPolicy.EXCLUDE))

    assert type(config.dataset_resolutions) is tuple
    assert config.canonical_map() == canonical
    assert config.policy_for("smuggled") is DatasetGapPolicy.NONE


def test_the_config_stores_one_canonical_order() -> None:
    """``policy_for`` and ``canonical_map`` read the same, stably-ordered entries."""
    entries = [
        _resolution("z_dataset", DatasetGapPolicy.NONE),
        _resolution("a_dataset", DatasetGapPolicy.BOUND),
    ]
    forward = ProfileResolutionConfig(
        requested_profile=PUBLIC,
        resolution_policy_version="policy/synthetic.1",
        dataset_resolutions=tuple(entries),
    )
    backward = ProfileResolutionConfig(
        requested_profile=PUBLIC,
        resolution_policy_version="policy/synthetic.1",
        dataset_resolutions=tuple(reversed(entries)),
    )
    assert [entry.dataset for entry in forward.dataset_resolutions] == [
        "a_dataset",
        "z_dataset",
    ]
    assert forward.canonical_map() == backward.canonical_map()
    assert forward.policy_for("a_dataset") is DatasetGapPolicy.BOUND
    assert forward.policy_for("a_dataset") is backward.policy_for("a_dataset")


def test_two_entries_that_normalise_to_one_dataset_refuse() -> None:
    """Collisions are detected after normalisation, where they are visible."""
    with pytest.raises(ProfileResolutionError, match="resolved more than once"):
        ProfileResolutionConfig(
            requested_profile=PUBLIC,
            resolution_policy_version="policy/synthetic.1",
            dataset_resolutions=(
                _resolution(_Renamed("price_bar"), DatasetGapPolicy.NONE),
                _resolution("price_bar", DatasetGapPolicy.BOUND),
            ),
        )


# ---------------------------------------------------------------------------
# The whole path, end to end
# ---------------------------------------------------------------------------


def test_nested_contracts_refuse_before_a_reader_exists_and_hold_after_it_does(
    tmp_path: Path,
) -> None:
    """The danger, reproduced whole.

    Both halves matter. A mutable nested object must be refused *before* a reader
    is built from it -- once a reader exists, its agreement with the publication's
    persisted standard has already been checked, and a later mutation is a change
    nobody recorded. And once properly-typed values are used, mutating every
    source collection they were built from must reach nothing: not the answers,
    not the query identity, not the evidence, not the standard.
    """
    publication = phase3a.build_verified_synthetic_publication(LocalTableStore(tmp_path))

    # 1. The refusals happen at construction, so no reader is ever built.
    with pytest.raises(ProfileResolutionError, match="not an exact ApprovedBoundPolicy"):
        BoundApprovals(by_dataset={"price_bar": _FakePolicy()})  # type: ignore[dict-item]
    with pytest.raises(ProfileResolutionError, match="not an exact DatasetGapResolution"):
        ProfileResolutionConfig(
            requested_profile=PUBLIC,
            resolution_policy_version="policy/synthetic.1",
            dataset_resolutions=(_FakeResolution(),),  # type: ignore[arg-type]
        )

    # 2. Properly-typed values, built from collections the caller keeps.
    approval_source = dict(phase3a.approvals().by_dataset)
    reference = phase3a.resolution()
    entry_source = list(reference.dataset_resolutions)
    approvals = BoundApprovals(by_dataset=approval_source)
    config = ProfileResolutionConfig(
        requested_profile=reference.requested_profile,
        global_profile_resolution=reference.global_profile_resolution,
        resolution_policy_version=reference.resolution_policy_version,
        dataset_resolutions=entry_source,  # type: ignore[arg-type]
    )
    reader = PointInTimeReader(publication, resolution=config, approvals=approvals)

    first = _series(reader)
    universe = reader.get_security_universe(as_of=phase3a.utc(2019, 6, 27, 20, 0), profile=PUBLIC)
    descriptor = publication.quality_report.quality_context
    before = (
        reader.approvals_identity,
        approvals.identity(),
        config.canonical_map(),
        descriptor.identity(),
    )

    # 3. Mutate every source collection the objects were built from.
    approval_source["price_bar"] = _permissive()
    approval_source["market_session"] = _permissive()
    approval_source.clear()
    entry_source.clear()
    entry_source.append(_resolution("smuggled", DatasetGapPolicy.EXCLUDE))

    # 4. Nothing moved.
    again = _series(reader)
    universe_again = reader.get_security_universe(
        as_of=phase3a.utc(2019, 6, 27, 20, 0), profile=PUBLIC
    )
    assert (
        reader.approvals_identity,
        approvals.identity(),
        config.canonical_map(),
        descriptor.identity(),
    ) == before
    assert again.result_bytes == first.result_bytes
    assert again.query.identity() == first.query.identity()
    assert again.evidence.identity() == first.evidence.identity()
    assert again.evidence.timing_evidence == first.evidence.timing_evidence
    assert universe_again.result_bytes == universe.result_bytes
    assert universe_again.evidence.identity() == universe.evidence.identity()
    assert config.policy_for("smuggled") is DatasetGapPolicy.NONE
    assert approvals.for_dataset("price_bar") != _permissive()


def test_a_sibling_enum_member_normalises_by_value_or_is_refused() -> None:
    """Stated because it is surprising, and because it is the specified behaviour.

    The derivation enums are ``StrEnum`` and share some values, so a sibling
    member whose value the field's own enum also has is accepted and stored as
    the field's own member: the field decides which enum a *name* belongs to, the
    stored member is always of that exact type, and membership and the record
    agree -- which is the property that matters.

    A value the field's own enum does not have is refused, so this is
    normalisation rather than a hole. ``NONE`` is not the example used here: it is
    shared by all three enums and refused on every one of them, which the test
    below pins.
    """
    shared = ApprovedBoundPolicy(
        public={ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND}  # type: ignore[arg-type]
    )
    (member,) = shared.public
    assert type(member) is PublicBoundDerivation
    assert member is PublicBoundDerivation.FIRST_SEEN_UPPER_BOUND

    with pytest.raises(ProfileResolutionError, match="is not a PublicBoundDerivation"):
        ApprovedBoundPolicy(public={ProviderBoundDerivation.DELIVERY_WINDOW})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "supplied",
    [
        PublicBoundDerivation.NONE,
        ProviderBoundDerivation.NONE,
        "NONE",
    ],
    ids=["own-enum", "sibling-enum", "plain-string"],
)
def test_none_cannot_be_approved_in_any_spelling(supplied: object) -> None:
    """The one claim this file previously got wrong, pinned so it cannot return.

    An earlier revision documented ``ProviderBoundDerivation.NONE`` in ``public``
    as *accepted*, normalising to ``PublicBoundDerivation.NONE``. It is not, and
    the difference is not cosmetic: ``NONE`` is the value an envelope carries when
    it has **no** bound derivation, so approving it approves every bound whose
    provenance nobody stated -- the most permissive thing the mechanism can
    express, spelled with the token that reads as nothing.
    """
    with pytest.raises(ProfileResolutionError, match="cannot be approved"):
        ApprovedBoundPolicy(public={supplied})  # type: ignore[arg-type]


def test_the_kernel_document_states_the_rule_that_none_is_refused() -> None:
    """A written claim that contradicts the code is how the wrong one survived.

    The prose is what a reviewer reads, and for one revision it said the opposite
    of what the constructor did. This asserts only that the A1 document states the
    rule the tests above prove; it is not a check that the rest of the document is
    accurate.
    """
    document = (
        Path(__file__).resolve().parents[2] / "docs" / "phase3" / KERNEL_DOCUMENT
    ).read_text(encoding="utf-8")
    assert "`NONE` is refused on **every** axis" in document


class _Chameleon(str):
    """``__str__`` returns ``self``, so ``str()`` does not defuse it.

    CPython's ``PyObject_Str`` calls ``tp_str`` and accepts any ``str`` subclass
    back, so this survives ``str(value)`` intact -- and with it the ``__eq__``
    below, which is enough to make a dataset name answer one lookup and record
    another.
    """

    def __str__(self) -> str:
        return self

    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return str.__hash__(self)


@pytest.mark.parametrize(
    "build",
    [
        lambda name: (
            DatasetGapResolution(
                dataset=name,
                policy=DatasetGapPolicy.NONE,
                reason="why",
            ).dataset
        ),
        lambda name: (
            DatasetGapResolution(
                dataset="price_bar",
                policy=DatasetGapPolicy.NONE,
                reason=name,
            ).reason
        ),
        lambda name: next(
            iter(BoundApprovals(by_dataset={name: ApprovedBoundPolicy()}).by_dataset)
        ),
    ],
    ids=["a gap resolution's dataset", "a gap resolution's reason", "an approvals key"],
)
def test_a_string_that_refuses_to_be_stringified_is_reduced_anyway(build: Any) -> None:
    """``str(value)`` is not a normaliser, and every one of these relied on it.

    ``str.__str__`` returns a fresh plain string for a subclass and the object
    itself only when it is already exactly ``str``, so it defuses the override.
    The result is a plain ``str`` carrying no equality of its own -- reduced
    rather than refused, which is the stated contract.
    """
    reduced = build(_Chameleon("price_bar"))
    assert type(reduced) is str
    assert reduced == "price_bar"
    assert not isinstance(reduced, _Chameleon)


def test_a_value_that_cannot_be_reduced_to_a_string_is_refused() -> None:
    """The second branch: a non-string whose ``__str__`` misbehaves."""

    class NotAString:
        def __str__(self) -> str:
            return _Chameleon("price_bar")

    with pytest.raises(ProfileResolutionError, match="does not reduce to a plain string"):
        DatasetGapResolution(
            dataset=NotAString(),  # type: ignore[arg-type]
            policy=DatasetGapPolicy.NONE,
            reason="why",
        )


def test_a_plain_downgrade_string_actually_downgrades_the_run() -> None:
    """``resolved_profile`` decides the whole run with an **identity** test.

    ``GlobalProfileResolution`` is a ``StrEnum``, so the plain string
    ``"DOWNGRADE"`` compares equal to the member and fails ``is`` -- a config that
    every equality-based check reads as downgraded would have executed at the
    requested profile instead, which is the one direction that leaks data.
    """
    config = ProfileResolutionConfig(
        requested_profile=PROVIDER,
        global_profile_resolution="DOWNGRADE",  # type: ignore[arg-type]
        resolution_policy_version="policy/synthetic.1",
    )
    assert config.global_profile_resolution is GlobalProfileResolution.DOWNGRADE
    assert config.resolved_profile is PUBLIC

    with pytest.raises(ProfileResolutionError, match="is not a GlobalProfileResolution"):
        ProfileResolutionConfig(
            requested_profile=PUBLIC,
            global_profile_resolution="SOMETHING-ELSE",  # type: ignore[arg-type]
            resolution_policy_version="policy/synthetic.1",
        )
    with pytest.raises(ProfileResolutionError, match="is not a InformationSetProfile"):
        ProfileResolutionConfig(
            requested_profile="NOT-A-PROFILE",  # type: ignore[arg-type]
            resolution_policy_version="policy/synthetic.1",
        )


def test_an_iterator_of_resolutions_is_refused_rather_than_silently_empty() -> None:
    """An exhausted one materialises to ``()``, which reads as "nothing declared".

    A config that resolved nothing and one that declared nothing produce the same
    tuple, and the manifest's per-dataset evidence would then be *missing* rather
    than wrong -- which is harder to notice.
    """
    spent = iter([_resolution("price_bar", DatasetGapPolicy.BOUND)])
    list(spent)
    with pytest.raises(ProfileResolutionError, match="not a sequence"):
        ProfileResolutionConfig(
            requested_profile=PUBLIC,
            resolution_policy_version="policy/synthetic.1",
            dataset_resolutions=spent,  # type: ignore[arg-type]
        )


def test_the_none_derivation_cannot_be_approved() -> None:
    """It is the value an envelope carries when it has **no** bound derivation.

    Approving it approves any bound whose provenance nobody stated, which is what
    an approval exists to require. Refused for each of the three axes, in the
    member spelling and the string one.
    """
    for field, supplied in (
        ("public", PublicBoundDerivation.NONE),
        ("public", "NONE"),
        ("provider", ProviderBoundDerivation.NONE),
        ("announcement", "NONE"),
    ):
        with pytest.raises(ProfileResolutionError, match="cannot be approved"):
            ApprovedBoundPolicy(**{field: {supplied}})  # type: ignore[arg-type]

    # NEGATIVE CONTROL: a derivation that states a provenance is approvable.
    approved = ApprovedBoundPolicy(public=frozenset({PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG}))
    assert approved.public == frozenset({PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG})


@pytest.mark.parametrize(
    "supplied", [None, object(), 7], ids=["None", "an arbitrary object", "an int"]
)
def test_an_uniterable_approval_collection_is_refused_in_the_governed_way(
    supplied: object,
) -> None:
    """A bare ``TypeError`` from inside a constructor tells a caller nothing.

    Every refusal on this path is a governed one, so the message says which field
    and why rather than leaving the caller to read a traceback.
    """
    with pytest.raises(ProfileResolutionError, match="is not iterable"):
        ApprovedBoundPolicy(public=supplied)  # type: ignore[arg-type]


def test_an_unapproved_bound_produces_a_refusal_rather_than_a_crash() -> None:
    """The check whose job is to refuse must not raise while writing the refusal.

    ``SourceEnvelope`` does not validate ``public_bound_derivation``, and the
    finding's message interpolated ``.value``. So the *unapproved* branch raised a
    bare ``AttributeError`` on a plain string, while a plain string that happened
    to match an approval passed silently -- the check crashed on exactly the input
    it existed to refuse.

    The derivation here is an exact member that is simply not approved, which is
    the case this finding is for. The untyped spelling is refused earlier now, by
    the vocabulary gate -- see ``test_phase3a_closed_vocabulary``.
    """
    from kalpamani.data.contracts.envelope import FactAnchor, SourceEnvelope
    from kalpamani.data.contracts.vocabulary import (
        InformationOrigin,
        PublicTimeDerivation,
    )
    from kalpamani.data.quality.checks import check_envelope

    instant = phase3a.utc(2019, 6, 28, 21, 0)

    @dataclasses.dataclass(frozen=True)
    class Row:
        dataset: str
        envelope: SourceEnvelope

    row = Row(
        dataset="price_bar",
        envelope=SourceEnvelope(
            information_origin=InformationOrigin.AUTHORITATIVE_PUBLIC,
            public_available_upper_bound=instant,
            public_time_derivation=PublicTimeDerivation.UNKNOWN,
            public_bound_derivation=PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG,
            system_first_seen_time=instant,
            anchor=FactAnchor.retrospective(observation_time=instant),
            ingestion_time=instant,
            dataset_version=phase3a.DATASET_VERSION,
        ),
    )
    nothing_approved = BoundApprovals(by_dataset={"price_bar": ApprovedBoundPolicy()})
    findings = check_envelope(row, approvals=nothing_approved)

    assert "4.0A.9_unapproved_public_bound" in {finding.check_name for finding in findings}
    assert any("SESSION_CLOSE_PLUS_LAG" in finding.detail for finding in findings), (
        "And the refusal still names the derivation it refused."
    )
