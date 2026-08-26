"""Resolved availability times, origin eligibility and the governing decision time.

Pure, deterministic functions over a record and an approved-bound policy. No
clock, no filesystem, no configuration read from the environment: the same record
under the same policy always resolves to the same instant.

Three ideas do the work.

**Resolved times.** ``resolved_public_time`` and ``resolved_provider_time`` return
the exact field, else an **approved** upper bound, else ``None``. "Approved" is
doing real work: a bound satisfies a profile requirement only when its derivation
appears in the dataset's configured approved list, which stops an arbitrary
approximation from silently qualifying a record and keeps the choice governed
rather than a property of whichever ingestion path happened to run. The helper
returns a *value*; the exact and bound fields stay exactly where they were, so
exact-versus-bound provenance survives every downstream use.

**Eligibility is separate from availability.** A record can be ineligible under a
profile (its origin describes an information set the profile cannot simulate) or
eligible-but-unresolvable (the profile's required time is missing). Both make
``decision_available_time`` return ``None``, and they call for opposite
responses: ineligible rows are **excluded and counted**; unresolvable rows are a
**refusal**. :func:`is_eligible` is what tells them apart, and callers are
expected to ask.

**Everything reads ``resolved_profile``, never ``requested_profile``.** A
``DOWNGRADE`` changes the whole run before any filtering, anchoring or artifact
construction happens; the requested profile survives only as audit evidence of
what was asked for.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Protocol, Self, runtime_checkable

from kalpamani.data.contracts.envelope import DerivedEnvelope, Envelope, SourceEnvelope
from kalpamani.data.contracts.vocabulary import (
    AnnouncementBoundDerivation,
    InformationOrigin,
    InformationSetProfile,
    ProviderBoundDerivation,
    PublicBoundDerivation,
)

# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@runtime_checkable
class PitRecord(Protocol):
    """Anything the resolution functions can reason about.

    Deliberately minimal: a dataset name (which selects the approved-bound
    policy) and one envelope (which selects everything else).
    """

    @property
    def dataset(self) -> str: ...

    @property
    def envelope(self) -> Envelope: ...


@runtime_checkable
class SourceRecord(PitRecord, Protocol):
    """A record carrying the source envelope, which profile resolution can rewrite.

    ``with_envelope`` returns a **copy**. Rows are never mutated in place, which
    is what makes silent history rewriting structurally impossible rather than
    merely discouraged.
    """

    @property
    def envelope(self) -> SourceEnvelope: ...

    def with_envelope(self, envelope: SourceEnvelope) -> Self: ...


@runtime_checkable
class DerivedArtifactRecord(PitRecord, Protocol):
    """A derived artifact, together with the records it actually consumed.

    ``envelope.lineage`` says what a rebuild would read; ``inputs`` are the
    resolved records themselves, which is what an availability computation needs.
    Keeping both is not duplication: lineage must survive serialisation and be
    replayable from storage, and inputs exist only in memory during a build.
    """

    @property
    def inputs(self) -> tuple[PitRecord, ...]: ...


# ---------------------------------------------------------------------------
# Approved bounds
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovedBoundPolicy:
    """Which bound derivations are approved for one dataset.

    Empty by default, and that default is a refusal rather than a permission:
    nothing is approved until someone approves it.
    """

    public: frozenset[PublicBoundDerivation] = frozenset()
    provider: frozenset[ProviderBoundDerivation] = frozenset()
    announcement: frozenset[AnnouncementBoundDerivation] = frozenset()


#: Nothing approved. The fail-closed default for an unconfigured dataset.
NO_BOUNDS_APPROVED: Final = ApprovedBoundPolicy()


@dataclass(frozen=True, slots=True, kw_only=True)
class BoundApprovals:
    """Per-dataset approved-bound configuration for a run.

    A dataset absent from the mapping has **nothing** approved. Silently
    approving an unconfigured dataset would make the approval mechanism
    decorative.
    """

    by_dataset: Mapping[str, ApprovedBoundPolicy] = field(default_factory=dict)

    def for_dataset(self, dataset: str) -> ApprovedBoundPolicy:
        """The approved bounds for ``dataset``, defaulting to none approved."""
        return self.by_dataset.get(dataset, NO_BOUNDS_APPROVED)


# ---------------------------------------------------------------------------
# Origin eligibility
# ---------------------------------------------------------------------------

#: Contract 3.1 as data: which source origins each profile can serve.
_ELIGIBLE_SOURCE_ORIGINS: Final[dict[InformationSetProfile, frozenset[InformationOrigin]]] = {
    InformationSetProfile.PUBLIC_PIT: frozenset({InformationOrigin.AUTHORITATIVE_PUBLIC}),
    InformationSetProfile.PROVIDER_REALISTIC_PIT: frozenset(
        {InformationOrigin.AUTHORITATIVE_PUBLIC, InformationOrigin.PROVIDER_DERIVED}
    ),
    InformationSetProfile.FORWARD_SYSTEM: frozenset(
        {
            InformationOrigin.AUTHORITATIVE_PUBLIC,
            InformationOrigin.PROVIDER_DERIVED,
            InformationOrigin.SYSTEM_OBSERVED,
        }
    ),
}


def origin_eligible(origin: InformationOrigin, profile: InformationSetProfile) -> bool:
    """Whether a **source** origin can be served under ``profile``.

    ``PUBLIC_PIT`` asks what the market could have known, so a proprietary
    consensus has no answer under it -- excluding it is correct, not a limitation
    to declare. ``DERIVED_ARTIFACT`` is not a source origin and always returns
    ``False`` here; use :func:`is_eligible`, which computes the intersection over
    a derived artifact's inputs.
    """
    return origin in _ELIGIBLE_SOURCE_ORIGINS[profile]


def is_eligible(record: PitRecord, resolved_profile: InformationSetProfile) -> bool:
    """Whether ``record`` may be served under ``resolved_profile`` at all.

    For a source fact this is origin eligibility. For a derived artifact it is the
    **intersection** of its inputs' eligibility: no amount of arithmetic makes a
    proprietary input public. Under ``FORWARD_SYSTEM`` every source origin is
    eligible, so the intersection is satisfied there by construction.
    """
    envelope = record.envelope
    if isinstance(envelope, SourceEnvelope):
        return origin_eligible(envelope.information_origin, resolved_profile)
    inputs = _derived_inputs(record)
    return all(is_eligible(item, resolved_profile) for item in inputs)


# ---------------------------------------------------------------------------
# Resolved times
# ---------------------------------------------------------------------------


def resolved_public_time(record: PitRecord, approvals: BoundApprovals) -> datetime | None:
    """Exact public time, else an approved public upper bound, else ``None``.

    A derived artifact has no public axis at all and resolves to ``None``; it
    never invents one (contract 2.5).
    """
    envelope = record.envelope
    if not isinstance(envelope, SourceEnvelope):
        return None
    if envelope.public_available_time is not None:
        return envelope.public_available_time
    approved = approvals.for_dataset(record.dataset).public
    if (
        envelope.public_available_upper_bound is not None
        and envelope.public_bound_derivation in approved
    ):
        return envelope.public_available_upper_bound
    return None


def resolved_provider_time(record: PitRecord, approvals: BoundApprovals) -> datetime | None:
    """Exact provider time, else an approved provider upper bound, else ``None``."""
    envelope = record.envelope
    if not isinstance(envelope, SourceEnvelope):
        return None
    if envelope.provider_available_time is not None:
        return envelope.provider_available_time
    approved = approvals.for_dataset(record.dataset).provider
    bound = envelope.provider_available_upper_bound
    if bound is not None and envelope.provider_bound_derivation in approved:
        return bound
    return None


# ---------------------------------------------------------------------------
# The governing decision time
# ---------------------------------------------------------------------------


def decision_available_time(
    record: PitRecord,
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
) -> datetime | None:
    """The instant from which ``record`` may participate in a query under ``resolved_profile``.

    Never stored on a fact row: a record has no single availability time, it has
    several, and which one governs is a property of the question being asked.

    Returns ``None`` for two different situations, and callers must distinguish
    them with :func:`is_eligible`:

    - **ineligible by origin** -- the profile cannot describe this kind of fact.
      Exclude the row and count it.
    - **eligible but unresolvable** -- the profile's required time is missing and
      no approved bound stands in. Refuse.
    """
    envelope = record.envelope
    if isinstance(envelope, DerivedEnvelope):
        return _derived_decision_time(record, envelope, resolved_profile, approvals)
    return _source_decision_time(record, envelope, resolved_profile, approvals)


def _source_decision_time(
    record: PitRecord,
    envelope: SourceEnvelope,
    profile: InformationSetProfile,
    approvals: BoundApprovals,
) -> datetime | None:
    origin = envelope.information_origin
    if not origin_eligible(origin, profile):
        return None

    public = resolved_public_time(record, approvals)
    provider = resolved_provider_time(record, approvals)
    seen = envelope.system_first_seen_time

    match profile:
        case InformationSetProfile.PUBLIC_PIT:
            # Only AUTHORITATIVE_PUBLIC reaches here, and it is governed by the
            # resolved public time -- exact or approved bound, never a substitute.
            return public

        case InformationSetProfile.PROVIDER_REALISTIC_PIT:
            if origin is InformationOrigin.PROVIDER_DERIVED:
                return provider
            # AUTHORITATIVE_PUBLIC: simulating a subscriber means knowing when the
            # SUBSCRIBER got the row, so both axes are required. Serving on public
            # timing alone is the withdrawn DECLARE behaviour.
            if public is None or provider is None:
                return None
            return max(public, provider)

        case InformationSetProfile.FORWARD_SYSTEM:
            # What did we hold? system_first_seen_time answers it for every origin.
            # Public and provider times remain provenance and quality inputs, and
            # participate only where the record actually has them.
            candidates = [t for t in (public, provider, seen) if t is not None]
            return max(candidates)


def _derived_decision_time(
    record: PitRecord,
    envelope: DerivedEnvelope,
    profile: InformationSetProfile,
    approvals: BoundApprovals,
) -> datetime | None:
    inputs = _derived_inputs(record)
    resolved: list[datetime] = []
    for item in inputs:
        if not is_eligible(item, profile):
            return None
        available = decision_available_time(item, profile, approvals)
        if available is None:
            return None
        resolved.append(available)

    lineage_max = max(resolved)
    if profile is InformationSetProfile.FORWARD_SYSTEM:
        # We did not hold a computed value before we computed it.
        return max(lineage_max, envelope.artifact_first_built_time)
    # Under the other two the artifact is exactly as available as its slowest
    # input, which is the honest answer to "when could this have been calculated?".
    return lineage_max


def _derived_inputs(record: PitRecord) -> tuple[PitRecord, ...]:
    if isinstance(record, DerivedArtifactRecord):
        return record.inputs
    raise TypeError(
        f"{type(record).__name__} carries a derived envelope but exposes no resolved inputs. "
        "A derived artifact's availability and eligibility are computed from its inputs; "
        "without them it would have to invent an availability it does not have."
    )


# ---------------------------------------------------------------------------
# The availability anchor
# ---------------------------------------------------------------------------


def source_anchor(
    record: PitRecord,
    resolved_profile: InformationSetProfile,
    approvals: BoundApprovals,
) -> datetime | None:
    """The one origin-aware availability anchor every temporal rule reads.

    Anchoring every class to the public time -- as an earlier revision of the plan
    did -- silently disabled all three class invariants for ``PROVIDER_DERIVED``
    and ``SYSTEM_OBSERVED`` rows, where the public time is legitimately null. A
    consensus snapshot stamped *before* the moment it was sampled would have
    passed every check.
    """
    envelope = record.envelope
    if isinstance(envelope, DerivedEnvelope):
        return decision_available_time(record, resolved_profile, approvals)

    match envelope.information_origin:
        case InformationOrigin.AUTHORITATIVE_PUBLIC:
            return resolved_public_time(record, approvals)
        case InformationOrigin.PROVIDER_DERIVED:
            return resolved_provider_time(record, approvals)
        case InformationOrigin.SYSTEM_OBSERVED:
            return envelope.system_first_seen_time
        case InformationOrigin.DERIVED_ARTIFACT:  # pragma: no cover - refused at construction
            return None


__all__ = [
    "NO_BOUNDS_APPROVED",
    "ApprovedBoundPolicy",
    "BoundApprovals",
    "DerivedArtifactRecord",
    "PitRecord",
    "SourceRecord",
    "decision_available_time",
    "is_eligible",
    "origin_eligible",
    "resolved_provider_time",
    "resolved_public_time",
    "source_anchor",
]
