"""The research-only vocabulary (proposed ADR-0051 §2).

Closed enumerations, deliberately **separate** from the accepted point-in-time vocabulary in
``kalpamani.data.contracts.vocabulary``. A value here is never a member there: the accepted
``InformationSetProfile`` still has exactly its accepted members, the accepted
``ProviderBoundDerivation`` likewise, and a static test holds both facts. That separation is
the isolation -- an accepted result type cannot carry an exploratory profile because its
validators only admit accepted members, so exploratory evidence cannot be smuggled into the
accepted gate by any wrapper.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from kalpamani.data.contracts.vocabulary import InformationSetProfile, ProviderBoundDerivation


class ExploratoryProfile(StrEnum):
    """The one research-only information-set profile. Not an ``InformationSetProfile``."""

    #: What a hindsight reader of today's vendor snapshot *assumes* was knowable on each
    #: historical session. Research only; confers no point-in-time status on any period.
    EXPLORATORY_HINDSIGHT = "EXPLORATORY_HINDSIGHT"


class ExploratoryDerivation(StrEnum):
    """The one research-only availability derivation. Not a ``ProviderBoundDerivation``."""

    #: A bar is *assumed* available at its own session close, a snapshot attribute at all
    #: times, an action at its date's session open. An assumption, never evidence.
    AS_DATED = "AS_DATED"


class AvailabilityBasis(StrEnum):
    """Why a row is treated as available. Exploratory documents may carry only ``ASSUMED``."""

    #: Availability taken from the row's own date (§2.2): assumed, not observed.
    ASSUMED_HISTORICAL = "ASSUMED_HISTORICAL"
    #: Availability observed or evidenced (production P-2 / P-3). **Never expressible** in an
    #: exploratory document: the member exists so the refusal names what was attempted.
    EVIDENCED = "EVIDENCED"


class QualificationClaim(StrEnum):
    """What an exploratory publication may claim about production qualification: nothing."""

    NONE = "NONE"


class ExploratoryLimitation(StrEnum):
    """The limitations an exploratory publication must declare (§2.3). Closed."""

    #: Today's row version stands in for every historical version; corrections and
    #: re-adjustments are invisible.
    REVISION_LOOKAHEAD = "REVISION_LOOKAHEAD"
    #: Today's exchange, category and listing attributes stand in for every past session.
    CURRENT_ATTRIBUTE_LOOKAHEAD = "CURRENT_ATTRIBUTE_LOOKAHEAD"
    #: No scheduled-event evidence exists; nothing is known about upcoming events.
    EVENT_BLIND = "EVENT_BLIND"
    #: A delisted position is valued at its last available close -- optimistic, not a fill.
    TERMINAL_VALUATION_OPTIMISTIC = "TERMINAL_VALUATION_OPTIMISTIC"
    #: Date-granular data establishes no intraday instant.
    NO_INTRADAY_INSTANT = "NO_INTRADAY_INSTANT"
    #: A benchmark built from the universe itself measures relative strength against
    #: the universe's own average.
    BENCHMARK_SELF_REFERENCE = "BENCHMARK_SELF_REFERENCE"


#: The limitations every exploratory publication must declare whatever else it declares.
#: Event blindness and benchmark self-reference depend on choices still pending (O-2, O-7)
#: and are declared when they apply; the other four follow from ``AS_DATED`` itself.
MANDATORY_LIMITATIONS: Final[frozenset[ExploratoryLimitation]] = frozenset(
    {
        ExploratoryLimitation.REVISION_LOOKAHEAD,
        ExploratoryLimitation.CURRENT_ATTRIBUTE_LOOKAHEAD,
        ExploratoryLimitation.TERMINAL_VALUATION_OPTIMISTIC,
        ExploratoryLimitation.NO_INTRADAY_INSTANT,
    }
)

#: The accepted profile and derivation values, by name. An exploratory document carrying
#: one of these where its own vocabulary belongs is a **substitution** and is refused as
#: such, distinctly from an unknown value.
PRODUCTION_PROFILE_NAMES: Final[frozenset[str]] = frozenset(m.value for m in InformationSetProfile)
PRODUCTION_DERIVATION_NAMES: Final[frozenset[str]] = frozenset(
    m.value for m in ProviderBoundDerivation
)

#: Research-only, by construction: neither enumeration shares a value with its accepted
#: counterpart. Asserted at import so the separation cannot drift silently.
if {m.value for m in ExploratoryProfile} & PRODUCTION_PROFILE_NAMES:
    raise ImportError("the exploratory profile vocabulary must not overlap the accepted one")
if {m.value for m in ExploratoryDerivation} & PRODUCTION_DERIVATION_NAMES:
    raise ImportError("the exploratory derivation vocabulary must not overlap the accepted one")

__all__ = [
    "MANDATORY_LIMITATIONS",
    "PRODUCTION_DERIVATION_NAMES",
    "PRODUCTION_PROFILE_NAMES",
    "AvailabilityBasis",
    "ExploratoryDerivation",
    "ExploratoryLimitation",
    "ExploratoryProfile",
    "QualificationClaim",
]
