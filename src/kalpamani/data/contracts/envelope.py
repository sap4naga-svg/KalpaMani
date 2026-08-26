"""The two mutually exclusive availability envelopes.

A row carries **one envelope or the other, never both, never neither**
(contract 2.4). This module makes that a property of the type system rather than
a convention a reviewer has to hold in their head:

- :class:`SourceEnvelope` and :class:`DerivedEnvelope` share no availability
  fields at all. They are not a superset and a subset; they are disjoint.
- Because both are keyword-only dataclasses, passing ``system_first_seen_time``
  to a derived artifact -- or ``lineage`` to a source fact -- is a ``TypeError``
  at the call site. An impossible mixed envelope cannot be constructed.
- The only overlap is deliberate: ``ingestion_time``, ``dataset_version``,
  ``quality_status`` and ``provider`` are **physical row properties** -- when
  this row was written, which build it belongs to -- not claims about when
  anyone could have known anything.

**What is enforced at construction, and what is not.** Construction refuses
defects that no legitimate fixture needs to express: a source envelope declaring
``DERIVED_ARTIFACT``, a derived envelope with no lineage at all. Everything else
-- a ``SYSTEM_OBSERVED`` row carrying provider timing, an exact time later than
its own bound, an approximation written into an exact field -- is a **quality
finding**, because the adversarial fixtures in the test suite must be able to
build those rows in order to prove the checks catch them. A check that can never
see the row it exists to reject protects nothing, and a check that over-blocks
gets disabled by whoever is next under deadline pressure.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

from kalpamani.data.contracts.errors import EnvelopeError
from kalpamani.data.contracts.vocabulary import (
    SOURCE_ORIGINS,
    AnnouncementBoundDerivation,
    InformationOrigin,
    OutputValidity,
    ProviderBoundDerivation,
    ProviderTimeDerivation,
    PublicBoundDerivation,
    PublicTimeDerivation,
    QualityStatus,
    TemporalFactClass,
)

# ---------------------------------------------------------------------------
# The source fact anchor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class FactAnchor:
    """A source fact's temporal declaration and the instants that anchor it.

    Every source entity declares exactly one :class:`TemporalFactClass`, and each
    class has exactly one anchor it is checked against. Which field carries that
    anchor is often named for the domain rather than the class -- a bar's
    ``bar_end_time``, a document's ``publication_time`` -- and the mapping is
    part of the contract, not prose to be inferred. See
    :mod:`kalpamani.data.contracts.anchors`.

    ``ANNOUNCED_FORWARD`` gets an upper bound as well as an exact instant,
    because a date-only announcement is common and a nullable anchor with no
    alternative is not an anchor. The bound is usable only if its derivation is
    **approved** for the dataset -- approval is what makes a bound usable, here
    exactly as on the availability axes.

    No validation happens here. A class declared without its anchor is quality
    check 4.0A.11, and the fixture that proves the check works has to be
    constructible.
    """

    temporal_fact_class: TemporalFactClass
    observation_time: datetime | None = None
    announcement_time: datetime | None = None
    announcement_time_upper_bound: datetime | None = None
    announcement_bound_derivation: AnnouncementBoundDerivation = AnnouncementBoundDerivation.NONE
    sample_time: datetime | None = None

    @classmethod
    def retrospective(cls, observation_time: datetime | None) -> FactAnchor:
        """A fact observed at or after it occurred."""
        return cls(
            temporal_fact_class=TemporalFactClass.RETROSPECTIVE,
            observation_time=observation_time,
        )

    @classmethod
    def announced_forward(
        cls,
        *,
        announcement_time: datetime | None = None,
        announcement_time_upper_bound: datetime | None = None,
        announcement_bound_derivation: AnnouncementBoundDerivation = (
            AnnouncementBoundDerivation.NONE
        ),
    ) -> FactAnchor:
        """A fact announced before it takes effect."""
        return cls(
            temporal_fact_class=TemporalFactClass.ANNOUNCED_FORWARD,
            announcement_time=announcement_time,
            announcement_time_upper_bound=announcement_time_upper_bound,
            announcement_bound_derivation=announcement_bound_derivation,
        )

    @classmethod
    def sampled_state(cls, sample_time: datetime | None) -> FactAnchor:
        """A state holding over an interval, observed by sampling."""
        return cls(
            temporal_fact_class=TemporalFactClass.SAMPLED_STATE,
            sample_time=sample_time,
        )


# ---------------------------------------------------------------------------
# The source envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceEnvelope:
    """Availability of a fact that arrived from outside.

    Four different information times, deliberately not collapsed into one
    (contract 2.1). The first draft of the plan had a single
    ``source_available_time`` and silently picked whichever one the ingestion
    code happened to have.

    Exact fields and bound fields are separate and never overwrite one another
    (contract 2.6). ``BOUND`` sets ``provider_available_upper_bound`` from
    ``system_first_seen_time`` and leaves ``provider_available_time`` null, so a
    bounded row is never mistaken for a precisely-stamped one.
    """

    information_origin: InformationOrigin

    public_available_time: datetime | None = None
    public_available_upper_bound: datetime | None = None
    public_time_derivation: PublicTimeDerivation = PublicTimeDerivation.UNKNOWN
    public_bound_derivation: PublicBoundDerivation = PublicBoundDerivation.NONE

    provider_available_time: datetime | None = None
    provider_available_upper_bound: datetime | None = None
    provider_time_derivation: ProviderTimeDerivation = ProviderTimeDerivation.UNKNOWN
    provider_bound_derivation: ProviderBoundDerivation = ProviderBoundDerivation.NONE

    system_first_seen_time: datetime

    anchor: FactAnchor

    revision_sequence: int = 0
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    source_id: str = ""
    vendor_record_id: str | None = None

    # -- physical row properties: the only overlap with the derived envelope --
    ingestion_time: datetime
    dataset_version: str
    quality_status: QualityStatus = QualityStatus.OK
    provider: str | None = None

    def __post_init__(self) -> None:
        if self.information_origin not in SOURCE_ORIGINS:
            raise EnvelopeError(
                f"information_origin={self.information_origin.value} selects the derived "
                "envelope, not the source envelope. A row carries one or the other, never "
                "both. Build a DerivedEnvelope instead."
            )

    @property
    def temporal_fact_class(self) -> TemporalFactClass:
        """The single class this source fact declares."""
        return self.anchor.temporal_fact_class


# ---------------------------------------------------------------------------
# The derived envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class LineageRef:
    """One input a derived artifact consumed.

    Complete enough that a rebuild would read exactly the same rows: the entity,
    the ``dataset_version`` it came from, and either a row selector or an
    upstream ``artifact_id``. A summary is not lineage -- it cannot be replayed,
    and a lineage that cannot be replayed cannot prove an artifact reproduced.
    """

    entity: str
    dataset_version: str
    selector: tuple[tuple[str, str], ...] = ()
    upstream_artifact_id: str | None = None

    @classmethod
    def of(
        cls,
        *,
        entity: str,
        dataset_version: str,
        selector: Mapping[str, str] | None = None,
        upstream_artifact_id: str | None = None,
    ) -> LineageRef:
        """Build a lineage reference, canonically ordering the selector keys."""
        pairs = tuple(sorted((selector or {}).items()))
        return cls(
            entity=entity,
            dataset_version=dataset_version,
            selector=pairs,
            upstream_artifact_id=upstream_artifact_id,
        )

    def is_resolvable(self) -> bool:
        """Whether this reference names something a rebuild could actually read."""
        if not self.entity or not self.dataset_version:
            return False
        return bool(self.selector) or bool(self.upstream_artifact_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class OutputValidityDeclaration:
    """What a derived artifact is *about*, and the field(s) that say so.

    Never part of an availability computation. ``output_validity`` describes the
    period the output describes; availability comes from lineage plus
    ``artifact_first_built_time`` under ``FORWARD_SYSTEM``.

    Permissive at construction on purpose: a ``SESSION_SCOPED`` artifact with no
    ``effective_session`` is quality check 4.0B.5, and the fixture proving that
    check works has to be buildable.
    """

    output_validity: OutputValidity
    effective_session: date | None = None
    valid_time_start: date | None = None
    valid_time_end: date | None = None
    period_end: date | None = None
    observation_reference: tuple[str, ...] = ()

    @classmethod
    def session_scoped(cls, effective_session: date) -> OutputValidityDeclaration:
        """Validity of an artifact describing exactly one session."""
        return cls(
            output_validity=OutputValidity.SESSION_SCOPED,
            effective_session=effective_session,
        )

    @classmethod
    def interval(cls, start: date, end: date) -> OutputValidityDeclaration:
        """Validity of an artifact spanning a range of sessions."""
        return cls(
            output_validity=OutputValidity.INTERVAL,
            valid_time_start=start,
            valid_time_end=end,
        )

    @classmethod
    def period_end_at(cls, period_end: date) -> OutputValidityDeclaration:
        """Validity of an artifact describing a fiscal period."""
        return cls(output_validity=OutputValidity.PERIOD_END, period_end=period_end)

    @classmethod
    def event_referenced(cls, references: tuple[str, ...]) -> OutputValidityDeclaration:
        """Validity of an artifact describing specific source rows."""
        return cls(
            output_validity=OutputValidity.EVENT_REFERENCED,
            observation_reference=references,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DerivedEnvelope:
    """Availability of a value KalpaMani computed from other rows.

    It carries **none** of the source times, and none may be invented for it. Its
    availability is the max over its lineage, plus ``artifact_first_built_time``
    under ``FORWARD_SYSTEM`` only -- that being the one profile that asks what
    *we* held, and we did not hold a computed value before we computed it.

    Its eligibility is the **intersection** of its inputs' eligibility. No amount
    of arithmetic makes a proprietary input public.
    """

    lineage: tuple[LineageRef, ...]
    artifact_first_built_time: datetime
    derivation_spec_version: str
    artifact_content_hash: str
    validity: OutputValidityDeclaration

    # -- physical row properties: the only overlap with the source envelope --
    ingestion_time: datetime
    dataset_version: str
    quality_status: QualityStatus = QualityStatus.OK
    provider: str | None = None

    @property
    def information_origin(self) -> InformationOrigin:
        """Fixed. A derived row cannot claim any other origin, so it is not a field."""
        return InformationOrigin.DERIVED_ARTIFACT

    def __post_init__(self) -> None:
        if not self.lineage:
            raise EnvelopeError(
                "A derived artifact with no lineage is not a derived artifact. Availability "
                "and eligibility are both computed from inputs, so an artifact without them "
                "has neither, and would have to invent an availability it does not have."
            )

    @property
    def output_validity(self) -> OutputValidity:
        """The single validity class this artifact declares."""
        return self.validity.output_validity


#: A record carries one envelope or the other.
Envelope = SourceEnvelope | DerivedEnvelope


def is_derived(envelope: Envelope) -> bool:
    """Whether ``envelope`` is the derived one. The single discriminator."""
    return isinstance(envelope, DerivedEnvelope)


__all__ = [
    "DerivedEnvelope",
    "Envelope",
    "FactAnchor",
    "LineageRef",
    "OutputValidityDeclaration",
    "SourceEnvelope",
    "is_derived",
]
