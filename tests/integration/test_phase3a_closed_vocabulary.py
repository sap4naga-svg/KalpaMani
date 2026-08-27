"""A value that spells a vocabulary member is not that member.

Every closed vocabulary in the point-in-time contract is a ``StrEnum``, and that
makes an untyped value almost invisible::

    envelope.public_bound_derivation = "SESSION_CLOSE_PLUS_LAG"   # a plain str

    derivation == PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG    # True
    derivation in approvals.for_dataset("price_bar").public       # True

It passes equality. It passes membership. It passes the approval test that
decides whether a row's bound may resolve at all. It differs from the member in
exactly one place -- ``.value`` -- which is where storage encodes it and where a
refusal interpolates it. So the untyped value sailed through every gate that was
supposed to judge it and then raised ``AttributeError: 'str' object has no
attribute 'value'`` from inside the receipt, naming neither the row nor the field.

An object of one's own is worse. ``Enum(value)`` is a ``_value2member_map_``
dict lookup, and a dict lookup asks the *supplied* object whether it matches the
stored key. The first test here shows that a class with a colliding ``__hash__``
and a permissive ``__eq__`` is found by that lookup and is accepted into a
frozenset of approved derivations -- so this is not a hypothetical.

The closure is one shared definition, :func:`source_vocabulary_defects`, applied
at every boundary a malformed row can cross:

* the resolution boundary refuses the run, typed, **before** it fingerprints;
* the quality gate reports ``4.0A.0_source_vocabulary_type_mismatch`` BLOCKING
  before it computes any availability or tests any approval;
* serde refuses to encode, rather than raising from mid-write;
* every resolution *function* answers "unresolvable" -- ``False``, ``None``,
  ``frozenset()`` -- instead of resolving on a value it cannot trust.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures import phase3a
from kalpamani.data.contracts.anchors import resolved_fact_anchor
from kalpamani.data.contracts.entities import PriceBar
from kalpamani.data.contracts.envelope import FactAnchor, SourceEnvelope
from kalpamani.data.contracts.errors import EnvelopeError, ProfileResolutionError
from kalpamani.data.contracts.profiles import DatasetGapResolution, ProfileResolutionConfig
from kalpamani.data.contracts.resolution import (
    ApprovedBoundPolicy,
    BoundApprovals,
    decision_available_time,
    governing_timing_bases,
    is_eligible,
    required_timing_bases,
    resolved_public_time,
)
from kalpamani.data.contracts.serde import encode_source_envelope
from kalpamani.data.contracts.vocabulary import (
    RAW,
    AnnouncementBoundDerivation,
    BarResolution,
    DatasetGapPolicy,
    GlobalProfileResolution,
    InformationOrigin,
    InformationSetProfile,
    ProviderBoundDerivation,
    PublicBoundDerivation,
    PublicTimeDerivation,
    QualitySeverity,
)
from kalpamani.data.curate.resolution_run import resolve_run_inputs
from kalpamani.data.pit.accessors import PointInTimeReader, SeriesRequirement
from kalpamani.data.quality.checks import check_envelope
from kalpamani.data.storage import LocalTableStore

pytestmark = pytest.mark.integration

PUBLIC = InformationSetProfile.PUBLIC_PIT
SECURITY = phase3a.SEC_CONTINUOUS
FIRST = date(2019, 6, 24)
LAST = date(2019, 6, 28)
SETTLED = phase3a.utc(2019, 7, 1, 12, 0)

#: The one bound derivation the fixture approves for ``price_bar``. Tests that
#: need a *valid* spelling use this one, so "approved" is never the reason a row
#: is refused -- the type is.
APPROVED = PublicBoundDerivation.SESSION_CLOSE_PLUS_LAG

VOCABULARY_CHECK = "4.0A.0_source_vocabulary_type_mismatch"


class _AnswersForItself:
    """Colliding hash, permissive equality, a ``.value`` of its own, and mutable.

    The mutability is the second half of the problem: even a system that looked
    at ``.value`` once and liked it would be reading a different answer the next
    time. Nothing here is exotic -- it is what any object gets to decide about
    itself in Python.
    """

    def __init__(self, spelling: str = APPROVED.value) -> None:
        self.value = spelling

    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return hash(self.value)


@dataclasses.dataclass(frozen=True)
class _Row:
    """The two attributes a quality check reads off a record."""

    dataset: str
    envelope: SourceEnvelope


def _envelope(**overrides: Any) -> SourceEnvelope:
    """A well-formed AUTHORITATIVE_PUBLIC envelope, with named fields replaced.

    ``SourceEnvelope`` is deliberately permissive at construction -- the quality
    suite has to be able to hold a malformed row -- so this builds the malformed
    cases directly rather than through a back door.
    """
    instant = phase3a.utc(2019, 6, 28, 21, 0)
    base: dict[str, Any] = {
        "information_origin": InformationOrigin.AUTHORITATIVE_PUBLIC,
        "public_available_upper_bound": instant,
        "public_time_derivation": PublicTimeDerivation.UNKNOWN,
        "public_bound_derivation": APPROVED,
        "system_first_seen_time": instant,
        "anchor": FactAnchor.retrospective(observation_time=instant),
        "ingestion_time": instant,
        "dataset_version": phase3a.DATASET_VERSION,
    }
    base.update(overrides)
    return SourceEnvelope(**base)


def _corrupted_datasets(**overrides: Any) -> dict[str, tuple[Any, ...]]:
    """The fixture's source rows with one daily bar's envelope fields replaced."""
    datasets = phase3a.source_datasets()
    bars = list(datasets["price_bar"])
    for index, bar in enumerate(bars):
        if isinstance(bar, PriceBar) and bar.resolution is BarResolution.DAILY:
            bars[index] = dataclasses.replace(
                bar, envelope=dataclasses.replace(bar.envelope, **overrides)
            )
            break
    else:  # pragma: no cover - the fixture has daily bars
        raise AssertionError("the fixture no longer has a daily bar to corrupt")
    datasets["price_bar"] = tuple(bars)
    return datasets


def _findings(envelope: SourceEnvelope, *, approvals: BoundApprovals | None = None) -> Any:
    return check_envelope(
        _Row(dataset="price_bar", envelope=envelope),
        approvals=approvals if approvals is not None else phase3a.approvals(),
    )


def _names(findings: Any) -> set[str]:
    return {finding.check_name for finding in findings}


# ---------------------------------------------------------------------------
# The premise, established rather than assumed
# ---------------------------------------------------------------------------


def test_an_object_that_answers_for_itself_passes_equality_and_membership() -> None:
    """Why refusing non-strings before the enum lookup is the load-bearing part.

    Nothing below is a claim about this codebase. It is what Python does, and it
    is the reason the checks in the rest of this file exist: every gate built out
    of ``==`` or ``in`` is one this object walks through.
    """
    hostile = _AnswersForItself()
    approved = phase3a.approvals().for_dataset("price_bar").public

    assert hostile == APPROVED
    assert hostile in approved, "a frozenset lookup asks the supplied object, and it says yes"
    assert PublicBoundDerivation(hostile) is APPROVED, "so does the enum's own constructor"  # type: ignore[arg-type]
    assert "SESSION_CLOSE_PLUS_LAG" in approved, "and a bare string is equally welcome"


# ---------------------------------------------------------------------------
# Item 1 -- every closed-vocabulary constructor refuses it, on every route
# ---------------------------------------------------------------------------


def test_an_approved_bound_policy_refuses_an_object_that_answers_for_itself() -> None:
    """Route one: the approved-derivation sets, on each of the three axes."""
    for axis in ("public", "provider", "announcement"):
        with pytest.raises(ProfileResolutionError, match="refused before it is asked"):
            ApprovedBoundPolicy(**{axis: frozenset({_AnswersForItself()})})  # type: ignore[arg-type]


def test_a_gap_resolution_refuses_an_object_that_answers_for_itself() -> None:
    """Route two: the per-dataset gap policy, which decides whether rows survive."""
    with pytest.raises(ProfileResolutionError, match="refused before it is asked"):
        DatasetGapResolution(
            dataset="price_bar",
            policy=_AnswersForItself(DatasetGapPolicy.EXCLUDE.value),  # type: ignore[arg-type]
            reason="a policy that decides for itself",
        )


@pytest.mark.parametrize(
    ("field", "spelling"),
    [
        ("requested_profile", InformationSetProfile.PUBLIC_PIT.value),
        ("global_profile_resolution", GlobalProfileResolution.NONE.value),
    ],
)
def test_a_resolution_config_refuses_an_object_that_answers_for_itself(
    field: str, spelling: str
) -> None:
    """Routes three and four: the two scalars that decide what a whole run serves."""
    entries = (
        DatasetGapResolution(dataset=name, policy=DatasetGapPolicy.NONE, reason="none needed")
        for name in phase3a.DIRECTLY_READ_DATASETS
    )
    arguments: dict[str, Any] = {
        "requested_profile": InformationSetProfile.PUBLIC_PIT,
        "global_profile_resolution": GlobalProfileResolution.NONE,
        "dataset_resolutions": tuple(entries),
        "resolution_policy_version": "pit/test.1",
    }
    arguments[field] = _AnswersForItself(spelling)
    with pytest.raises(ProfileResolutionError, match="refused before it is asked"):
        ProfileResolutionConfig(**arguments)


# ---------------------------------------------------------------------------
# A -- a valid spelling of an approved derivation, untyped
# ---------------------------------------------------------------------------


def test_a_plain_string_bound_is_blocking_even_when_that_derivation_is_approved(
    tmp_path: Path,
) -> None:
    """The case that used to pass silently and then crash somewhere else.

    ``SESSION_CLOSE_PLUS_LAG`` is the derivation the fixture approves for
    ``price_bar``, so approval is not what refuses this row. Its type is.
    """
    envelope = _envelope(public_bound_derivation=APPROVED.value)
    findings = _findings(envelope)

    assert VOCABULARY_CHECK in _names(findings)
    assert all(finding.severity is QualitySeverity.BLOCKING for finding in findings)
    assert any("public_bound_derivation" in finding.detail for finding in findings)

    store = LocalTableStore(tmp_path)
    with pytest.raises(EnvelopeError, match="public_bound_derivation"):
        resolve_run_inputs(
            _corrupted_datasets(public_bound_derivation=APPROVED.value),
            config=phase3a.resolution(),
            approvals=phase3a.approvals(),
        )
    assert not list(tmp_path.rglob("*.jsonl")), "and nothing reached storage"
    assert not list(tmp_path.rglob("*manifest*")), "and no version was published"
    assert store.root == tmp_path


# ---------------------------------------------------------------------------
# B -- a spelling no vocabulary has
# ---------------------------------------------------------------------------


def test_a_string_that_names_nothing_is_a_typed_finding_rather_than_an_exception() -> None:
    """The check reports; it does not raise while reporting."""
    findings = _findings(_envelope(provider_bound_derivation="NOT-A-DERIVATION"))

    assert VOCABULARY_CHECK in _names(findings)
    assert any("NOT-A-DERIVATION" in finding.detail for finding in findings)
    assert any("provider_bound_derivation" in finding.detail for finding in findings)


# ---------------------------------------------------------------------------
# C -- an object with a .value of its own
# ---------------------------------------------------------------------------


def test_an_object_that_answers_for_itself_does_not_satisfy_an_approval() -> None:
    """It passes ``in``, so the gate is not allowed to be built out of ``in``."""
    hostile = _AnswersForItself()
    envelope = _envelope(public_bound_derivation=hostile)
    row = _Row(dataset="price_bar", envelope=envelope)
    approvals = phase3a.approvals()

    assert hostile in approvals.for_dataset("price_bar").public, "the danger, restated locally"

    assert VOCABULARY_CHECK in _names(check_envelope(row, approvals=approvals))
    assert resolved_public_time(row, approvals) is None
    assert decision_available_time(row, PUBLIC, approvals) is None
    assert is_eligible(row, PUBLIC) is False
    assert required_timing_bases(row, PUBLIC, approvals) == frozenset()
    assert governing_timing_bases(row, PUBLIC, approvals) == frozenset()

    hostile.value = "SOMETHING-ELSE"
    assert resolved_public_time(row, approvals) is None, "and it stays refused after it changes"


# ---------------------------------------------------------------------------
# D -- a sibling enum whose values overlap
# ---------------------------------------------------------------------------


def test_a_sibling_enums_member_is_refused_in_a_field_it_does_not_belong_to() -> None:
    """``FIRST_SEEN_UPPER_BOUND`` is spelled the same on two axes and is not the same value.

    The approvals normaliser accepts the sibling and stores the field's own
    member, because there the field decides which enum a *name* belongs to. A
    stored envelope is the other way round: the value is already typed, and a
    provider derivation sitting in a public field is a mislabelled row, not a
    name to be resolved.
    """
    sibling = ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND
    assert sibling.value in {item.value for item in PublicBoundDerivation}

    findings = _findings(_envelope(public_bound_derivation=sibling))
    assert VOCABULARY_CHECK in _names(findings)
    assert any("ProviderBoundDerivation" in finding.detail for finding in findings)


# ---------------------------------------------------------------------------
# E -- the fact anchor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "supplied",
    [
        AnnouncementBoundDerivation.DATE_PLUS_LAG.value,
        _AnswersForItself(AnnouncementBoundDerivation.DATE_PLUS_LAG.value),
        ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND,
    ],
    ids=["plain-string", "answers-for-itself", "wrong-enum"],
)
def test_an_untyped_announcement_bound_does_not_satisfy_the_announcement_approval(
    supplied: Any,
) -> None:
    """The anchor is where a forward-dated fact becomes usable, so it gates too."""
    approved = frozenset({AnnouncementBoundDerivation.DATE_PLUS_LAG})
    announced = phase3a.utc(2019, 6, 20, 13, 0)
    anchor = dataclasses.replace(
        FactAnchor.announced_forward(
            announcement_time_upper_bound=announced,
            announcement_bound_derivation=AnnouncementBoundDerivation.DATE_PLUS_LAG,
        ),
        announcement_bound_derivation=supplied,
    )

    assert resolved_fact_anchor(anchor, approved) is None

    findings = _findings(_envelope(anchor=anchor))
    assert VOCABULARY_CHECK in _names(findings)
    assert any("anchor.announcement_bound_derivation" in finding.detail for finding in findings)


# ---------------------------------------------------------------------------
# F -- the negative control
# ---------------------------------------------------------------------------


def test_exact_vocabulary_still_publishes_and_answers_the_same_query(tmp_path: Path) -> None:
    """Without this, every assertion above is satisfied by refusing everything."""
    findings = _findings(_envelope())
    assert VOCABULARY_CHECK not in _names(findings)

    encoded = encode_source_envelope(_envelope())
    assert encoded["public_bound_derivation"] == APPROVED.value

    reader = phase3a.reader(LocalTableStore(tmp_path))
    assert isinstance(reader, PointInTimeReader)
    series = reader.get_price_history(
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
    assert series.result.bars, "the clean path still serves rows"


# ---------------------------------------------------------------------------
# G -- the order: refused before anything encodes it
# ---------------------------------------------------------------------------


def test_a_malformed_row_is_refused_before_anything_reads_its_value() -> None:
    """``.value`` is where the old failure surfaced, so nothing may reach it.

    Both halves matter. The boundary refuses the run before the receipt
    fingerprints anything, and the encoder -- reached by any other route -- names
    the field instead of raising ``AttributeError`` from mid-write.
    """
    malformed = _envelope(public_bound_derivation=APPROVED.value)

    with pytest.raises(EnvelopeError, match="public_bound_derivation"):
        encode_source_envelope(malformed)

    with pytest.raises(EnvelopeError) as refusal:
        resolve_run_inputs(
            _corrupted_datasets(public_bound_derivation=APPROVED.value),
            config=phase3a.resolution(),
            approvals=phase3a.approvals(),
        )
    assert "public_bound_derivation" in str(refusal.value)
    assert not isinstance(refusal.value, AttributeError)
