"""Research specifications and the admission rule (ADR-0051 §3).

An exploratory input set reaches a consumer only through :func:`admit`, and :func:`admit`
admits exactly one kind of consumer: a :class:`ResearchSpecification` that names the set's
profile and derivation. **Every other consumer is refused** -- an accepted ``StrategySpec``
(Breakout Long's requires ``PROVIDER_REALISTIC_PIT``), any object carrying an accepted
``required_profile``, a research specification naming a different profile, ``None``, a
string, anything. The rule is exact-type and fail-closed; there is no duck-typed opt-in.

A research specification is an explicit, versioned opt-in. It names the accepted strategy
specification it derives from and enumerates every difference from it, so a run under it
can never be mistaken for a run of the accepted module.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.vocabulary import InformationSetProfile
from kalpamani.data.exploratory.contracts import (
    SCHEMA_VERSION,
    ExploratoryDefect,
    ExploratoryInputSet,
    _canonical,
    _closed_fields,
    _contract,
    _exact_str,
    _refuse,
)
from kalpamani.data.exploratory.vocabulary import (
    ExploratoryDerivation,
    ExploratoryLimitation,
    ExploratoryProfile,
)

RESEARCH_SPECIFICATION_CONTRACT_ID: Final = "kalpamani-research-specification/v1"

#: A research specification's version string: the accepted identifier grammar, bounded.
_VERSION_MAX: Final = 128
_MAX_DIFFERENCES: Final = 64

_SPECIFICATION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "contract_id",
        "schema_version",
        "name",
        "version",
        "admits_profile",
        "admits_derivation",
        "declared_limitations",
        "base_strategy_version",
        "differences",
        "trial",
    }
)


class AdmissionOutcome(StrEnum):
    """Closed admission outcomes. Exactly one is an admission."""

    ADMITTED = "ADMITTED"
    REFUSED_NOT_A_RESEARCH_SPECIFICATION = "REFUSED_NOT_A_RESEARCH_SPECIFICATION"
    REFUSED_PRODUCTION_CONSUMER = "REFUSED_PRODUCTION_CONSUMER"
    REFUSED_NOT_AN_INPUT_SET = "REFUSED_NOT_AN_INPUT_SET"
    REFUSED_PROFILE_MISMATCH = "REFUSED_PROFILE_MISMATCH"
    REFUSED_DERIVATION_MISMATCH = "REFUSED_DERIVATION_MISMATCH"
    REFUSED_LIMITATIONS_UNDECLARED = "REFUSED_LIMITATIONS_UNDECLARED"


def _text(value: object, *, limit: int) -> str:
    text = _exact_str(value)
    if not text or len(text) > limit or text != text.strip():
        raise _refuse(ExploratoryDefect.FIELD_MALFORMED)
    return text


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchSpecification:
    """An explicit, versioned opt-in to one exploratory profile and derivation."""

    name: str
    version: str
    admits_profile: ExploratoryProfile
    admits_derivation: ExploratoryDerivation
    #: The limitations this specification acknowledges. An input set declaring a limitation
    #: the specification does not acknowledge is refused: the consumer must know what it
    #: is consuming.
    declared_limitations: frozenset[ExploratoryLimitation]
    #: The accepted strategy specification this research specification derives from.
    base_strategy_version: str
    #: Every difference from the base, enumerated. Non-empty: a research specification
    #: identical to its base would be the base.
    differences: tuple[str, ...]
    #: The trial number in the multiple-testing ledger; 1 is the first.
    trial: int

    def __post_init__(self) -> None:
        _text(self.name, limit=_VERSION_MAX)
        _text(self.version, limit=_VERSION_MAX)
        if type(self.admits_profile) is not ExploratoryProfile:
            raise _refuse(ExploratoryDefect.PROFILE_UNKNOWN)
        if type(self.admits_derivation) is not ExploratoryDerivation:
            raise _refuse(ExploratoryDefect.DERIVATION_UNKNOWN)
        if type(self.declared_limitations) is not frozenset or any(
            type(item) is not ExploratoryLimitation for item in self.declared_limitations
        ):
            raise _refuse(ExploratoryDefect.LIMITATION_UNKNOWN)
        _text(self.base_strategy_version, limit=_VERSION_MAX)
        if (
            type(self.differences) is not tuple
            or not self.differences
            or len(self.differences) > _MAX_DIFFERENCES
            or any(type(item) is not str or not item.strip() for item in self.differences)
        ):
            raise _refuse(ExploratoryDefect.FIELD_MALFORMED)
        if type(self.trial) is not int or self.trial < 1:
            raise _refuse(ExploratoryDefect.FIELD_MALFORMED)

    def document(self) -> dict[str, Any]:
        """The closed document. Round-trips through :func:`parse_research_specification`."""
        return {
            "contract_id": RESEARCH_SPECIFICATION_CONTRACT_ID,
            "schema_version": SCHEMA_VERSION,
            "name": self.name,
            "version": self.version,
            "admits_profile": self.admits_profile.value,
            "admits_derivation": self.admits_derivation.value,
            "declared_limitations": sorted(item.value for item in self.declared_limitations),
            "base_strategy_version": self.base_strategy_version,
            "differences": list(self.differences),
            "trial": self.trial,
        }

    @property
    def digest(self) -> str:
        """SHA-256 over the canonical document -- the trial ledger's parameter identity."""
        return hashlib.sha256(_canonical(self.document())).hexdigest()


def parse_research_specification(document: object) -> ResearchSpecification:
    """The specification a document describes, or one closed refusal."""
    fields = _closed_fields(document, _SPECIFICATION_FIELDS)
    _contract(fields, RESEARCH_SPECIFICATION_CONTRACT_ID)
    try:
        profile = ExploratoryProfile(_exact_str(fields["admits_profile"]))
    except ValueError:
        raise _refuse(ExploratoryDefect.PROFILE_UNKNOWN) from None
    try:
        derivation = ExploratoryDerivation(_exact_str(fields["admits_derivation"]))
    except ValueError:
        raise _refuse(ExploratoryDefect.DERIVATION_UNKNOWN) from None
    raw_limitations = fields["declared_limitations"]
    if type(raw_limitations) is not list or len(set(raw_limitations)) != len(raw_limitations):
        raise _refuse(ExploratoryDefect.FIELD_MALFORMED)
    limitations: set[ExploratoryLimitation] = set()
    for item in raw_limitations:
        try:
            limitations.add(ExploratoryLimitation(_exact_str(item)))
        except ValueError:
            raise _refuse(ExploratoryDefect.LIMITATION_UNKNOWN) from None
    raw_differences = fields["differences"]
    if type(raw_differences) is not list:
        raise _refuse(ExploratoryDefect.FIELD_MALFORMED)
    if type(fields["trial"]) is not int:
        raise _refuse(ExploratoryDefect.FIELD_MALFORMED)
    return ResearchSpecification(
        name=_exact_str(fields["name"]),
        version=_exact_str(fields["version"]),
        admits_profile=profile,
        admits_derivation=derivation,
        declared_limitations=frozenset(limitations),
        base_strategy_version=_exact_str(fields["base_strategy_version"]),
        differences=tuple(_exact_str(item) for item in raw_differences),
        trial=fields["trial"],
    )


def _is_production_consumer(consumer: object) -> bool:
    """Whether ``consumer`` declares an accepted point-in-time profile anywhere it could.

    An accepted ``StrategySpec`` carries ``data.required_profile``; any object carrying an
    accepted ``InformationSetProfile`` under either spelling is a production consumer and is
    named as such in the refusal. Attribute access is guarded: an object that raises on
    inspection is simply not a research specification.
    """
    for holder in (consumer, getattr(consumer, "data", None)):
        try:
            profile = getattr(holder, "required_profile", None)
        except Exception:  # inspection must never raise past the rule
            return False
        if type(profile) is InformationSetProfile:
            return True
    return False


def admit(consumer: object, inputs: object) -> AdmissionOutcome:
    """Whether ``consumer`` may consume ``inputs``. Exact types; fail closed; never raises."""
    if type(inputs) is not ExploratoryInputSet:
        return AdmissionOutcome.REFUSED_NOT_AN_INPUT_SET
    if type(consumer) is not ResearchSpecification:
        if _is_production_consumer(consumer):
            return AdmissionOutcome.REFUSED_PRODUCTION_CONSUMER
        return AdmissionOutcome.REFUSED_NOT_A_RESEARCH_SPECIFICATION
    # Compared by value: each vocabulary has one member today, and the rule must stay a
    # comparison rather than a tautology when a later ADR adds another.
    if inputs.profile.value != consumer.admits_profile.value:
        return AdmissionOutcome.REFUSED_PROFILE_MISMATCH
    if inputs.derivation.value != consumer.admits_derivation.value:
        return AdmissionOutcome.REFUSED_DERIVATION_MISMATCH
    if not inputs.limitations <= consumer.declared_limitations:
        return AdmissionOutcome.REFUSED_LIMITATIONS_UNDECLARED
    return AdmissionOutcome.ADMITTED


__all__ = [
    "RESEARCH_SPECIFICATION_CONTRACT_ID",
    "AdmissionOutcome",
    "ResearchSpecification",
    "admit",
    "parse_research_specification",
]
