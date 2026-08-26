"""Closed vocabularies for the point-in-time data contract.

Every vocabulary here is **closed**: a value outside it is a defect, not an
extension point. They are the mechanical form of the merged Phase-3 planning
contract (``docs/phase3/pit-data-contract.md``), and the reason they live in one
module is that a vocabulary duplicated in two places is a vocabulary that will
eventually disagree with itself.

Two separations are load-bearing and easy to lose:

**Exact and bound derivations have separate vocabularies.** No member of an exact
enum may name a bound field and no member of a bound enum may name an exact one
(contract 2.6, schema 19 rule 7f). A single enum mixing
``AUTHORITATIVE_TIMESTAMP`` with ``DATE_PLUS_LAG`` is exactly how a lag-derived
approximation ends up in a field documented as exact.

**UNKNOWN and NOT_APPLICABLE are never conflated** (schema 19 rule 7b). UNKNOWN
means a time exists and we failed to establish it; NOT_APPLICABLE means no such
time exists for this origin. One is a gap, the other is a shape.

There is deliberately **no DECLARE member** in :class:`DatasetGapPolicy`. It was
withdrawn by contract revision 3 because it served a row on public timing while
labelling the result provider-realistic, which is the profile mixing the contract
forbids.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

# ---------------------------------------------------------------------------
# Origin, profile and view
# ---------------------------------------------------------------------------


class InformationOrigin(StrEnum):
    """Where a fact came from. Decides which envelope and which profiles apply.

    The first three are **source origins** and select the source envelope. The
    fourth is a discriminator saying *this row is not an external observation, so
    do not look for one*, and selects the derived envelope.
    """

    AUTHORITATIVE_PUBLIC = "AUTHORITATIVE_PUBLIC"
    PROVIDER_DERIVED = "PROVIDER_DERIVED"
    SYSTEM_OBSERVED = "SYSTEM_OBSERVED"
    DERIVED_ARTIFACT = "DERIVED_ARTIFACT"


#: The three origins that carry the source envelope.
SOURCE_ORIGINS: Final[frozenset[InformationOrigin]] = frozenset(
    {
        InformationOrigin.AUTHORITATIVE_PUBLIC,
        InformationOrigin.PROVIDER_DERIVED,
        InformationOrigin.SYSTEM_OBSERVED,
    }
)


class InformationSetProfile(StrEnum):
    """Whose information set a query simulates.

    ``PUBLIC_PIT`` asks what the market could have known; ``PROVIDER_REALISTIC_PIT``
    what a subscriber to the chosen provider could have known; ``FORWARD_SYSTEM``
    what KalpaMani actually held.
    """

    PUBLIC_PIT = "PUBLIC_PIT"
    PROVIDER_REALISTIC_PIT = "PROVIDER_REALISTIC_PIT"
    FORWARD_SYSTEM = "FORWARD_SYSTEM"


class RevisionView(StrEnum):
    """Which revision of a revisable fact a query wants.

    ``AS_KNOWN_AT_AS_OF`` is the **normative** historical view -- which is a
    statement about correctness, not a code default. Every accessor still takes it
    explicitly (contract 6.2).

    ``LATEST_RESTATED`` ignores ``as_of`` entirely and is therefore not
    point-in-time. It is fenced off from research and backtest code.
    """

    AS_KNOWN_AT_AS_OF = "AS_KNOWN_AT_AS_OF"
    ORIGINAL_FILING_ONLY = "ORIGINAL_FILING_ONLY"
    LATEST_RESTATED = "LATEST_RESTATED"


# ---------------------------------------------------------------------------
# Temporal declaration
# ---------------------------------------------------------------------------


class TemporalFactClass(StrEnum):
    """Which timing invariant applies to a **source** fact.

    A blanket "availability must not precede observation" rule is wrong for
    anything announced in advance, which is why ``ANNOUNCED_FORWARD`` exists: an
    exchange holiday calendar published a year ahead is a correct, non-leaking
    fact.
    """

    RETROSPECTIVE = "RETROSPECTIVE"
    ANNOUNCED_FORWARD = "ANNOUNCED_FORWARD"
    SAMPLED_STATE = "SAMPLED_STATE"


class OutputValidity(StrEnum):
    """What a **derived** artifact is *about*.

    It never participates in an availability computation. Availability comes from
    lineage, plus ``artifact_first_built_time`` under ``FORWARD_SYSTEM``. Keeping
    the two apart is the whole reason the derived envelope exists.
    """

    SESSION_SCOPED = "SESSION_SCOPED"
    INTERVAL = "INTERVAL"
    PERIOD_END = "PERIOD_END"
    EVENT_REFERENCED = "EVENT_REFERENCED"


# ---------------------------------------------------------------------------
# Exact derivations -- may only ever name an exact field
# ---------------------------------------------------------------------------


class PublicTimeDerivation(StrEnum):
    """How an **exact** ``public_available_time`` was established."""

    AUTHORITATIVE_TIMESTAMP = "AUTHORITATIVE_TIMESTAMP"
    VENDOR_TZ_TIMESTAMP = "VENDOR_TZ_TIMESTAMP"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ProviderTimeDerivation(StrEnum):
    """How an **exact** ``provider_available_time`` was established."""

    VENDOR_STAMPED = "VENDOR_STAMPED"
    FILE_DROP = "FILE_DROP"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


#: Derivations that legitimately produce an exact public instant.
EXACT_PUBLIC_DERIVATIONS: Final[frozenset[PublicTimeDerivation]] = frozenset(
    {
        PublicTimeDerivation.AUTHORITATIVE_TIMESTAMP,
        PublicTimeDerivation.VENDOR_TZ_TIMESTAMP,
    }
)

#: Derivations that legitimately produce an exact provider instant.
EXACT_PROVIDER_DERIVATIONS: Final[frozenset[ProviderTimeDerivation]] = frozenset(
    {
        ProviderTimeDerivation.VENDOR_STAMPED,
        ProviderTimeDerivation.FILE_DROP,
    }
)


# ---------------------------------------------------------------------------
# Bound derivations -- may only ever name an upper-bound field
# ---------------------------------------------------------------------------


class PublicBoundDerivation(StrEnum):
    """How a conservative ``public_available_upper_bound`` was derived."""

    DATE_PLUS_LAG = "DATE_PLUS_LAG"
    SESSION_CLOSE_PLUS_LAG = "SESSION_CLOSE_PLUS_LAG"
    FIRST_SEEN_UPPER_BOUND = "FIRST_SEEN_UPPER_BOUND"
    NONE = "NONE"


class ProviderBoundDerivation(StrEnum):
    """How a conservative ``provider_available_upper_bound`` was derived."""

    FIRST_SEEN_UPPER_BOUND = "FIRST_SEEN_UPPER_BOUND"
    DELIVERY_WINDOW = "DELIVERY_WINDOW"
    NONE = "NONE"


class AnnouncementBoundDerivation(StrEnum):
    """How a conservative ``announcement_time_upper_bound`` was derived.

    An ``ANNOUNCED_FORWARD`` row needs a usable anchor, not merely a nullable one.
    Where only an announcement *date* is published, the bound is the end of that
    date in the venue timezone plus the declared lag.
    """

    DATE_PLUS_LAG = "DATE_PLUS_LAG"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# Profile resolution
# ---------------------------------------------------------------------------


class DatasetGapPolicy(StrEnum):
    """Per-dataset resolution of unknown provider availability.

    ``DECLARE`` is deliberately absent -- see the module docstring. ``DOWNGRADE``
    is deliberately absent too: it is **global**, not per dataset, and lives in
    :class:`GlobalProfileResolution`.
    """

    NONE = "NONE"
    EXCLUDE = "EXCLUDE"
    BOUND = "BOUND"


class GlobalProfileResolution(StrEnum):
    """Run-level profile resolution. ``DOWNGRADE`` changes the whole run."""

    NONE = "NONE"
    DOWNGRADE = "DOWNGRADE"


# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------


class QualitySeverity(StrEnum):
    """Severity of a deterministic quality finding.

    ``BLOCKING`` means every dependent result is **refused**, not annotated.
    """

    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class QualityStatus(StrEnum):
    """Row-level quality state. ``QUARANTINED`` rows never reach a research query."""

    OK = "OK"
    SUSPECT = "SUSPECT"
    QUARANTINED = "QUARANTINED"


class IssueStatus(StrEnum):
    """Lifecycle of a quality issue.

    Suppression is a named human act: it requires a person and a reason.
    """

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    SUPPRESSED = "SUPPRESSED"


# ---------------------------------------------------------------------------
# Coverage and inputs
# ---------------------------------------------------------------------------


class CoverageScope(StrEnum):
    """The scope at which a required input's coverage contract is evaluated.

    The partition minimum decides, never an aggregate: a ``PER_SECURITY`` input at
    97% overall with securities below threshold has failed, and averaging them
    away is the move the scope exists to prevent.
    """

    WHOLE_DOMAIN = "WHOLE_DOMAIN"
    PER_SESSION = "PER_SESSION"
    PER_SECURITY = "PER_SECURITY"
    PER_SECURITY_SESSION = "PER_SECURITY_SESSION"


class InputRequirement(StrEnum):
    """Whether emptying a domain refuses the run or merely annotates it."""

    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"


class LimitationToken(StrEnum):
    """Mandatory manifest limitations. Every token needs positive evidence.

    Only the tokens the A1 foundation slice can actually evidence are defined.
    Phase-3B and 3C tokens are added when the domains they describe exist; a token
    that nothing can emit is a claim nobody can check.
    """

    PROVIDER_AVAILABILITY_UNKNOWN = "PROVIDER_AVAILABILITY_UNKNOWN"
    PROVIDER_TIME_BOUNDED = "PROVIDER_TIME_BOUNDED"
    PUBLIC_TIME_BOUNDED = "PUBLIC_TIME_BOUNDED"
    PROFILE_DOWNGRADED_TO_PUBLIC = "PROFILE_DOWNGRADED_TO_PUBLIC"
    ORIGIN_INELIGIBLE_ROWS_EXCLUDED = "ORIGIN_INELIGIBLE_ROWS_EXCLUDED"
    CORPORATE_ACTION_ANNOUNCE_APPROXIMATED = "CORPORATE_ACTION_ANNOUNCE_APPROXIMATED"
    SINGLE_SOURCE_UNVERIFIED = "SINGLE_SOURCE_UNVERIFIED"
    NON_PIT_RESTATED_VIEW = "NON_PIT_RESTATED_VIEW"


# ---------------------------------------------------------------------------
# Market-data domain vocabularies
# ---------------------------------------------------------------------------


class BarResolution(StrEnum):
    """Bar resolution. Part of the ``price_bar`` primary key."""

    DAILY = "DAILY"
    MINUTE = "MINUTE"


class BarConstruction(StrEnum):
    """How a **source** bar was constructed.

    ``SYSTEM_AGGREGATED`` is deliberately absent: a bar we resampled is not a
    source fact at all, it is an aggregated-bar artifact.
    """

    OFFICIAL_DISSEMINATED = "OFFICIAL_DISSEMINATED"
    PROVIDER_AGGREGATED = "PROVIDER_AGGREGATED"


#: The origin each bar construction implies. Established by provider
#: qualification (implementation-plan test P9), never assumed -- which is why this
#: is a mapping a caller must apply rather than a silent default.
BAR_CONSTRUCTION_ORIGIN: Final[dict[BarConstruction, InformationOrigin]] = {
    BarConstruction.OFFICIAL_DISSEMINATED: InformationOrigin.AUTHORITATIVE_PUBLIC,
    BarConstruction.PROVIDER_AGGREGATED: InformationOrigin.PROVIDER_DERIVED,
}


class Exchange(StrEnum):
    """Listing venue."""

    NYSE = "NYSE"
    NASDAQ = "NASDAQ"
    NYSE_AMERICAN = "NYSE_AMERICAN"
    OTC = "OTC"


class CorporateActionType(StrEnum):
    """Corporate-action type."""

    SPLIT = "SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    DIVIDEND = "DIVIDEND"
    SPECIAL_DIVIDEND = "SPECIAL_DIVIDEND"
    SPINOFF = "SPINOFF"
    MERGER = "MERGER"
    RIGHTS = "RIGHTS"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"
    DELISTING = "DELISTING"


class AdjustmentPolicy(StrEnum):
    """Which actions an adjusted series accounts for. Part of the artifact key."""

    SPLIT_ONLY = "SPLIT_ONLY"
    SPLIT_AND_DIVIDEND = "SPLIT_AND_DIVIDEND"
    TOTAL_RETURN = "TOTAL_RETURN"


@dataclass(frozen=True, slots=True)
class AdjustmentMode:
    """What a price query asks for. There is no implicit adjustment.

    ``RAW`` returns traded prices. ``adjusted(policy)`` returns a series computed
    from raw bars plus the actions admissible at ``as_of`` under the resolved
    profile -- which is why the policy has to be named: "the adjusted close on a
    date" is not a number, it is a number *per information set*.
    """

    policy: AdjustmentPolicy | None

    @classmethod
    def adjusted(cls, policy: AdjustmentPolicy) -> AdjustmentMode:
        """An explicitly policied adjusted series."""
        return cls(policy=policy)

    @property
    def is_raw(self) -> bool:
        """Whether this mode asks for traded prices."""
        return self.policy is None


#: Traded prices, unadjusted. Named so a caller states it rather than omits it.
RAW: Final[AdjustmentMode] = AdjustmentMode(policy=None)


class ListingFactKind(StrEnum):
    """Which fact a listing row carries. A key part, so the two cannot collapse."""

    STATE = "STATE"
    CHANGE_ANNOUNCEMENT = "CHANGE_ANNOUNCEMENT"


class DelistingReason(StrEnum):
    """Why a listing ended."""

    MERGER = "MERGER"
    ACQUISITION = "ACQUISITION"
    BANKRUPTCY = "BANKRUPTCY"
    DEFICIENCY = "DEFICIENCY"
    VOLUNTARY = "VOLUNTARY"
    UNKNOWN = "UNKNOWN"


class TickerChangeReason(StrEnum):
    """Why a ticker mapping changed."""

    RENAME = "RENAME"
    MERGER = "MERGER"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    EXCHANGE_MOVE = "EXCHANGE_MOVE"


class UniverseExclusionReason(StrEnum):
    """Why a security failed the universe definition on a session."""

    PRICE = "PRICE"
    MARKET_CAP = "MARKET_CAP"
    ADDV = "ADDV"
    HISTORY = "HISTORY"
    EXCHANGE = "EXCHANGE"
    SECURITY_TYPE = "SECURITY_TYPE"


class StorageLayer(StrEnum):
    """Which layer a dataset version belongs to."""

    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class IngestionStatus(StrEnum):
    """Outcome of an ingestion run."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


__all__ = [
    "BAR_CONSTRUCTION_ORIGIN",
    "EXACT_PROVIDER_DERIVATIONS",
    "EXACT_PUBLIC_DERIVATIONS",
    "RAW",
    "SOURCE_ORIGINS",
    "AdjustmentMode",
    "AdjustmentPolicy",
    "AnnouncementBoundDerivation",
    "BarConstruction",
    "BarResolution",
    "CorporateActionType",
    "CoverageScope",
    "DatasetGapPolicy",
    "DelistingReason",
    "Exchange",
    "GlobalProfileResolution",
    "InformationOrigin",
    "InformationSetProfile",
    "IngestionStatus",
    "InputRequirement",
    "IssueStatus",
    "LimitationToken",
    "ListingFactKind",
    "OutputValidity",
    "ProviderBoundDerivation",
    "ProviderTimeDerivation",
    "PublicBoundDerivation",
    "PublicTimeDerivation",
    "QualitySeverity",
    "QualityStatus",
    "RevisionView",
    "StorageLayer",
    "TemporalFactClass",
    "TickerChangeReason",
    "UniverseExclusionReason",
]
