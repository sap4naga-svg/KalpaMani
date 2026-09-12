"""Provider-availability bounds for every Silver row version -- ADR-0035 §3.3, as accepted.

**Every rule yields a bound; no rule writes an exact provider instant.** The routes the
accepted contract can express are exactly two members of
:class:`~kalpamani.data.contracts.vocabulary.ProviderBoundDerivation`:

- **P-2, ``FIRST_SEEN_UPPER_BOUND``** -- the default and the fall-back: the bound is the
  retrieval instant of the earliest acquisition that delivered *these bytes*, and the
  row carries ``PROVIDER_AVAILABILITY_UNKNOWN`` and ``PROVIDER_TIME_BOUNDED``.
- **P-3, ``DELIVERY_WINDOW``** -- only for a row version with **explicit per-version
  delivery evidence**: a record stating that this content, by digest, was included in a
  specific delivery. The bound is that delivery's instant, taken from the evidence.
  A delivery *schedule* alone establishes that some version was delivered on a date,
  never that the version retrieved today is that version (T-2); it is ignored.

**Two routes are gated, and gated means refused here.** The vendor-date route (P-1,
``VENDOR_DATE_UPPER_BOUND``) and the capture-derived route (``VERSION_EVIDENCE_UPPER_BOUND``)
need vocabulary members the accepted contract does not have. Evidence of those kinds
may be supplied, and is counted as **ignored**; the row falls to P-2 and no bound is
ever derived from a ``lastupdated`` stamp or an archival capture (D-3, T-3 to T-5
without the extension). Nothing here names either member as a derivation.

**A revision never inherits an earlier version's bound.** Bounds are computed per row
version from that version's own first-seen instant and that version's own evidence, so
``v2`` arriving after ``v1`` with no evidence is P-2 at ``v2``'s own first-seen instant
whatever ``v1`` carried (T-1, V-1).

**Public time** applies to ``actions`` only: an ex-date fact is public by its ex-date
session open (``DATE_PLUS_LAG``, lag zero). The governing time under
``PROVIDER_REALISTIC_PIT`` is ``max(public, provider)`` for actions and the provider
bound otherwise; a public bound the calendar cannot place leaves the provider bound
governing, which can only be later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.vocabulary import (
    InformationOrigin,
    InformationSetProfile,
    LimitationToken,
    ProviderBoundDerivation,
    PublicBoundDerivation,
)
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.production.sharadar.sessions import SessionCalendar
from kalpamani.data.production.sharadar.silver import RowVersion, SilverLayer

#: The resolution policy version. Part of every manifest and of the build ``run_id``.
RESOLUTION_POLICY_VERSION: Final = "sharadar-availability-v1"

#: The one profile this build resolves under. ``PUBLIC_PIT`` is ineligible for
#: ``stocks`` (ADR-0010) and is not expressible here.
RESOLVED_PROFILE: Final = InformationSetProfile.PROVIDER_REALISTIC_PIT

#: The derivations this build may emit. **Exactly these two**, by the accepted contract.
EXPRESSIBLE_DERIVATIONS: Final[frozenset[ProviderBoundDerivation]] = frozenset(
    {ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND, ProviderBoundDerivation.DELIVERY_WINDOW}
)

#: The information origin per dataset (ADR-0035 §3.3).
INFORMATION_ORIGIN: Final[dict[str, InformationOrigin]] = {
    SharadarDataset.STOCKS.value: InformationOrigin.PROVIDER_DERIVED,
    SharadarDataset.TICKERS.value: InformationOrigin.PROVIDER_DERIVED,
    SharadarDataset.ACTIONS.value: InformationOrigin.AUTHORITATIVE_PUBLIC,
}


class AvailabilityRule(StrEnum):
    """Which accepted rule admitted a row version. Closed."""

    P2_FIRST_SEEN = "P-2"
    P3_DELIVERY_WINDOW = "P-3/DELIVERY_WINDOW"


class GatedRoute(StrEnum):
    """Routes the accepted contract cannot express. **Named only to be refused.**

    Neither value is a :class:`ProviderBoundDerivation` member, and no row is ever
    labelled with one; a proposed contract amendment would add the members and a
    later, separately authorized build would implement the routes.
    """

    VENDOR_DATE_UPPER_BOUND = "VENDOR_DATE_UPPER_BOUND"
    VERSION_EVIDENCE_UPPER_BOUND = "VERSION_EVIDENCE_UPPER_BOUND"


class EvidenceKind(StrEnum):
    """What a supplied piece of availability evidence claims to be."""

    PER_VERSION_DELIVERY = "PER_VERSION_DELIVERY"
    DELIVERY_SCHEDULE = "DELIVERY_SCHEDULE"
    ARCHIVAL_CAPTURE = "ARCHIVAL_CAPTURE"
    VENDOR_DATE = "VENDOR_DATE"


@dataclass(frozen=True, slots=True, kw_only=True)
class VersionEvidence:
    """One piece of evidence about when a row version was available.

    ``content_sha256`` binds it to one version; a schedule carries none, which is
    exactly why a schedule can never admit a version.
    """

    kind: EvidenceKind
    dataset: str
    row_key: tuple[str, ...]
    content_sha256: str | None
    instant: datetime | None
    evidence_digest: str

    def __post_init__(self) -> None:
        if type(self.kind) is not EvidenceKind:
            raise TypeError("kind must be an exact EvidenceKind member")
        if self.instant is not None and self.instant.tzinfo is None:
            raise ValueError("an evidence instant is aware or absent")
        if type(self.evidence_digest) is not str or len(self.evidence_digest) != 64:
            raise ValueError("evidence carries a 64-hex digest")


@dataclass(frozen=True, slots=True, kw_only=True)
class AvailabilityEvidence:
    """The versioned set of evidence supplied to one build. Configuration."""

    version: str
    items: tuple[VersionEvidence, ...] = ()

    def per_version_delivery(self, row: RowVersion) -> VersionEvidence | None:
        """The one per-version delivery record for this exact content, if any."""
        matches = [
            item
            for item in self.items
            if item.kind is EvidenceKind.PER_VERSION_DELIVERY
            and item.dataset == row.dataset
            and item.row_key == row.row_key
            and item.content_sha256 == row.content_sha256
            and item.instant is not None
        ]
        if not matches:
            return None
        # Deterministic: the earliest evidenced delivery, then the digest.
        return min(matches, key=lambda item: (item.instant, item.evidence_digest))

    def gated_for(self, row: RowVersion) -> int:
        """How many gated-route items name this version or its key. Counted, never used."""
        return sum(
            1
            for item in self.items
            if item.kind in {EvidenceKind.ARCHIVAL_CAPTURE, EvidenceKind.VENDOR_DATE}
            and item.dataset == row.dataset
            and item.row_key == row.row_key
            and (item.content_sha256 is None or item.content_sha256 == row.content_sha256)
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Availability:
    """The bound one row version is served under. Every field a bound, never an instant."""

    rule: AvailabilityRule
    provider_bound_derivation: ProviderBoundDerivation
    provider_available_upper_bound: datetime
    public_bound_derivation: PublicBoundDerivation
    public_available_upper_bound: datetime | None
    governing_time: datetime
    evidence_digest: str | None
    limitations: tuple[LimitationToken, ...]

    def __post_init__(self) -> None:
        if self.provider_bound_derivation not in EXPRESSIBLE_DERIVATIONS:
            raise ValueError("a build emits only derivations the accepted contract expresses")

    def document(self) -> dict[str, Any]:
        """The closed availability document carried by every Silver row."""
        return {
            "resolved_profile": RESOLVED_PROFILE.value,
            "rule": self.rule.value,
            "provider_available_time": None,
            "provider_available_upper_bound": self.provider_available_upper_bound.isoformat(),
            "provider_bound_derivation": self.provider_bound_derivation.value,
            "public_available_upper_bound": (
                None
                if self.public_available_upper_bound is None
                else self.public_available_upper_bound.isoformat()
            ),
            "public_bound_derivation": self.public_bound_derivation.value,
            "governing_time": self.governing_time.isoformat(),
            "evidence_digest": self.evidence_digest,
            "limitations": [token.value for token in self.limitations],
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedRow:
    """One Silver row version and the availability it is served under."""

    row: RowVersion
    availability: Availability

    def __repr__(self) -> str:
        """Rule only."""
        return f"ResolvedRow(rule={self.availability.rule.value!r})"


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolutionCounts:
    """How many row versions each rule admitted, per dataset, and what was ignored."""

    dataset: str
    p2_first_seen: int
    p3_delivery_window: int
    gated_evidence_ignored: int

    def document(self) -> dict[str, Any]:
        """The per-dataset resolution map entry the manifest records."""
        return {
            "dataset": self.dataset,
            AvailabilityRule.P2_FIRST_SEEN.value: self.p2_first_seen,
            AvailabilityRule.P3_DELIVERY_WINDOW.value: self.p3_delivery_window,
            "gated_evidence_ignored": self.gated_evidence_ignored,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedLayer:
    """Every Silver row version with its bound, per dataset, in Silver order."""

    tickers: tuple[ResolvedRow, ...]
    stocks: tuple[ResolvedRow, ...]
    actions: tuple[ResolvedRow, ...]
    counts: tuple[ResolutionCounts, ...]
    policy_version: str
    evidence_version: str

    def by_dataset(self, dataset: str) -> tuple[ResolvedRow, ...]:
        """The rows of one dataset."""
        return {
            SharadarDataset.TICKERS.value: self.tickers,
            SharadarDataset.STOCKS.value: self.stocks,
            SharadarDataset.ACTIONS.value: self.actions,
        }[dataset]


def _public_bound(row: RowVersion, calendar: SessionCalendar) -> datetime | None:
    """The ex-date session open for an action, or ``None`` when the calendar cannot place it."""
    if row.dataset != SharadarDataset.ACTIONS.value:
        return None
    text = row.fields.get("date")
    if text is None:
        return None
    try:
        session_date = date.fromisoformat(text)
    except ValueError:
        return None
    return calendar.open_at(session_date)


def resolve_row(
    row: RowVersion, *, evidence: AvailabilityEvidence, calendar: SessionCalendar
) -> tuple[ResolvedRow, bool]:
    """The bound of one row version, and whether gated evidence was ignored for it."""
    ignored = evidence.gated_for(row) > 0
    delivery = evidence.per_version_delivery(row)
    if delivery is not None and delivery.instant is not None:
        rule = AvailabilityRule.P3_DELIVERY_WINDOW
        derivation = ProviderBoundDerivation.DELIVERY_WINDOW
        provider_bound = delivery.instant
        evidence_digest: str | None = delivery.evidence_digest
        limitations: tuple[LimitationToken, ...] = (LimitationToken.PROVIDER_TIME_BOUNDED,)
    else:
        rule = AvailabilityRule.P2_FIRST_SEEN
        derivation = ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND
        provider_bound = row.system_first_seen_time
        evidence_digest = None
        limitations = (
            LimitationToken.PROVIDER_AVAILABILITY_UNKNOWN,
            LimitationToken.PROVIDER_TIME_BOUNDED,
        )
    public_bound = _public_bound(row, calendar)
    governing = provider_bound if public_bound is None else max(public_bound, provider_bound)
    availability = Availability(
        rule=rule,
        provider_bound_derivation=derivation,
        provider_available_upper_bound=provider_bound,
        public_bound_derivation=(
            PublicBoundDerivation.NONE
            if public_bound is None
            else PublicBoundDerivation.DATE_PLUS_LAG
        ),
        public_available_upper_bound=public_bound,
        governing_time=governing,
        evidence_digest=evidence_digest,
        limitations=limitations,
    )
    return ResolvedRow(row=row, availability=availability), ignored


def resolve(
    layer: SilverLayer, *, evidence: AvailabilityEvidence, calendar: SessionCalendar
) -> ResolvedLayer:
    """Resolve every Silver row version under the accepted rules. Deterministic."""
    if type(layer) is not SilverLayer:
        raise TypeError("layer must be an exact SilverLayer")
    if type(evidence) is not AvailabilityEvidence or type(calendar) is not SessionCalendar:
        raise TypeError("evidence and calendar must be exact")
    resolved: dict[str, tuple[ResolvedRow, ...]] = {}
    counts: list[ResolutionCounts] = []
    for dataset in (
        SharadarDataset.TICKERS.value,
        SharadarDataset.STOCKS.value,
        SharadarDataset.ACTIONS.value,
    ):
        rows: list[ResolvedRow] = []
        p2 = p3 = ignored_count = 0
        for row in layer.by_dataset(dataset).rows:
            item, ignored = resolve_row(row, evidence=evidence, calendar=calendar)
            rows.append(item)
            if item.availability.rule is AvailabilityRule.P2_FIRST_SEEN:
                p2 += 1
            else:
                p3 += 1
            ignored_count += int(ignored)
        resolved[dataset] = tuple(rows)
        counts.append(
            ResolutionCounts(
                dataset=dataset,
                p2_first_seen=p2,
                p3_delivery_window=p3,
                gated_evidence_ignored=ignored_count,
            )
        )
    return ResolvedLayer(
        tickers=resolved[SharadarDataset.TICKERS.value],
        stocks=resolved[SharadarDataset.STOCKS.value],
        actions=resolved[SharadarDataset.ACTIONS.value],
        counts=tuple(counts),
        policy_version=RESOLUTION_POLICY_VERSION,
        evidence_version=evidence.version,
    )


__all__ = [
    "EXPRESSIBLE_DERIVATIONS",
    "INFORMATION_ORIGIN",
    "RESOLUTION_POLICY_VERSION",
    "RESOLVED_PROFILE",
    "Availability",
    "AvailabilityEvidence",
    "AvailabilityRule",
    "EvidenceKind",
    "GatedRoute",
    "ResolutionCounts",
    "ResolvedLayer",
    "ResolvedRow",
    "VersionEvidence",
    "resolve",
    "resolve_row",
]
