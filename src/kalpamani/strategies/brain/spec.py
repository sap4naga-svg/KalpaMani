"""The ``StrategySpec`` contract: a module's whole definition, versioned and immutable.

Specification section 9, as a type. A spec with an unpinned version, an
unpinned factor-definition version or an unauthorized environment may not
produce a candidate -- and here the first two cannot be *constructed*, while
the third is what the compiler's second stage refuses.

Two consistency rules are encoded rather than documented, because each is a
place where a research parameter could quietly become a production one:

**Environment follows lifecycle.** A version may authorize ``PAPER`` only from
``AUTOMATED_PAPER`` onward -- the first order-producing stage, which a human
promotes it to (sections 10 and 25) -- and ``LIVE`` only from
``MICRO_LIVE_CANARY`` onward. A research-stage version therefore authorizes
``RESEARCH`` and nothing else, and no edit to a threshold can change that
without also changing the stage, which is a human decision.

**Short requires borrow.** A ``SHORT`` version must declare the borrow domain
and the borrow prerequisite; a ``LONG`` one must declare neither applicable.
The asymmetry of section 20 is a constructor rule, not a reminder.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

from kalpamani.common.environment import Environment
from kalpamani.data.contracts.vocabulary import (
    AdjustmentMode,
    BarResolution,
    InformationSetProfile,
    RevisionView,
    closed_member,
)
from kalpamani.strategies.brain.errors import BrainContractError
from kalpamani.strategies.brain.factors import FactorDefinition
from kalpamani.strategies.brain.identity import (
    require_identifier,
    require_optional_identifier,
    require_positive_int,
)
from kalpamani.strategies.brain.vocabulary import (
    CANDIDATE_PRODUCING_STAGES,
    LIVE_ELIGIBLE_STAGES,
    PAPER_ELIGIBLE_STAGES,
    AlphaFamily,
    DataDomain,
    Direction,
    FactorFamily,
    LifecycleStage,
    ReasonCode,
    Requirement,
)

Member = TypeVar("Member", bound=StrEnum)

#: The revision views a strategy version may declare. Named by their admissible members
#: rather than by the one they exclude, so this both refuses any non-point-in-time view
#: and never names the restated route the consumer-boundary guard forbids.
_POINT_IN_TIME_REVISION_VIEWS = frozenset(
    {RevisionView.AS_KNOWN_AT_AS_OF, RevisionView.ORIGINAL_FILING_ONLY}
)


def _member(vocabulary: type[Member], value: object, *, field: str) -> Member:
    member = closed_member(vocabulary, value)
    if member is None:
        raise BrainContractError(f"Field {field!r} must be a {vocabulary.__name__} member.")
    return member


def _members(vocabulary: type[Member], values: object, *, field: str) -> frozenset[Member]:
    if not isinstance(values, frozenset | set | tuple | list):
        raise BrainContractError(f"Field {field!r} must be a collection of members.")
    return frozenset(_member(vocabulary, value, field=field) for value in values)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchGovernance:
    """Section 9, *research governance*: the hypothesis, its baseline and its budget.

    ``baseline_id`` names the simpler alternative the module must beat (section
    22: a named baseline comes first). ``trial_budget`` is the recorded trial
    count the multiple-testing control divides by -- recorded, not remembered.
    """

    hypothesis_id: str
    baseline_id: str
    trial_budget: int
    success_criteria_reference: str
    failure_criteria_reference: str

    def __post_init__(self) -> None:
        require_identifier(self.hypothesis_id, field="hypothesis_id")
        require_identifier(self.baseline_id, field="baseline_id")
        require_positive_int(self.trial_budget, field="trial_budget")
        require_identifier(self.success_criteria_reference, field="success_criteria_reference")
        require_identifier(self.failure_criteria_reference, field="failure_criteria_reference")


@dataclass(frozen=True, slots=True, kw_only=True)
class DataRequirements:
    """Section 9, *data*: domains, profile, revision view, coverage.

    ``required_history_sessions`` counts bars including the evaluation bar, and
    must cover every factor the version depends on; the constructor checks it
    against the factor definitions rather than trusting the number.
    """

    required_profile: InformationSetProfile
    revision_view: RevisionView | None
    adjustment_mode: AdjustmentMode
    resolution: BarResolution
    required_domains: frozenset[DataDomain]
    optional_domains: frozenset[DataDomain]
    required_history_sessions: int

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(
            self,
            "required_profile",
            _member(InformationSetProfile, self.required_profile, field="required_profile"),
        )
        if self.revision_view is not None:
            view = _member(RevisionView, self.revision_view, field="revision_view")
            if view not in _POINT_IN_TIME_REVISION_VIEWS:
                raise BrainContractError(
                    "A strategy version must declare a point-in-time revision view. The restated "
                    "view ignores as_of and is not point-in-time; the kernel refuses it at "
                    "runtime, and a version may not declare it."
                )
            set_(self, "revision_view", view)
        if type(self.adjustment_mode) is not AdjustmentMode:
            raise BrainContractError("Field 'adjustment_mode' must be an AdjustmentMode.")
        set_(self, "resolution", _member(BarResolution, self.resolution, field="resolution"))
        required = _members(DataDomain, self.required_domains, field="required_domains")
        optional = _members(DataDomain, self.optional_domains, field="optional_domains")
        if DataDomain.PRICE_BARS not in required:
            raise BrainContractError("Every strategy version requires the PRICE_BARS domain.")
        if required & optional:
            raise BrainContractError("A domain is required or optional, never both.")
        set_(self, "required_domains", required)
        set_(self, "optional_domains", optional)
        require_positive_int(self.required_history_sessions, field="required_history_sessions")


@dataclass(frozen=True, slots=True, kw_only=True)
class Permissions:
    """Section 9, *permissions*, plus the AI and rank requirements of section 6."""

    market_prerequisite: Requirement
    event_prerequisite: Requirement
    gap_prerequisite: Requirement
    borrow_prerequisite: Requirement
    ai_requirement: Requirement
    rank_requirement: Requirement

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        for field in (
            "market_prerequisite",
            "event_prerequisite",
            "gap_prerequisite",
            "borrow_prerequisite",
            "ai_requirement",
            "rank_requirement",
        ):
            set_(self, field, _member(Requirement, getattr(self, field), field=field))


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskTags:
    """Section 9, *risk tags*: what the later risk engine needs to know, as tags.

    Tags, not numbers: the Brain carries the family and factor exposures a
    candidate loads on so the risk engine can budget them. It never computes
    the budget.
    """

    family_exposure: AlphaFamily
    factor_exposures: tuple[FactorFamily, ...]
    capacity_reference: str
    risk_policy_compatibility: str

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(
            self,
            "family_exposure",
            _member(AlphaFamily, self.family_exposure, field="family_exposure"),
        )
        exposures = tuple(
            _member(FactorFamily, value, field="factor_exposures")
            for value in self.factor_exposures
        )
        if not exposures or len(set(exposures)) != len(exposures):
            raise BrainContractError("factor_exposures must be a non-empty tuple without repeats.")
        set_(self, "factor_exposures", exposures)
        require_identifier(self.capacity_reference, field="capacity_reference")
        require_identifier(self.risk_policy_compatibility, field="risk_policy_compatibility")


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategySpec:
    """A versioned, immutable module definition (section 9).

    ``parameters_hash`` binds the version to the exact parameter values the
    module was constructed with; a module whose parameters hash differently
    from its spec is refused at module construction. ``factor_definition_version``
    pins the factor **set**; each member definition carries its own version.
    """

    strategy_id: str
    alpha_family: AlphaFamily
    strategy_module: str
    trade_template: str
    version: str
    lifecycle_stage: LifecycleStage
    authorized_environments: frozenset[Environment]
    direction: Direction
    expected_holding_sessions: int
    minimum_holding_sessions: int
    maximum_holding_sessions: int
    data: DataRequirements
    permissions: Permissions
    factor_definitions: tuple[FactorDefinition, ...]
    factor_definition_version: str
    parameters_hash: str
    manifest_version: str
    configuration_identity: str
    model_version: str | None
    prompt_version: str | None
    risk_tags: RiskTags
    research: ResearchGovernance

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing. A subclass could relax a constructor rule."""
        raise TypeError("StrategySpec may not be subclassed.")

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        require_identifier(self.strategy_id, field="strategy_id")
        set_(self, "alpha_family", _member(AlphaFamily, self.alpha_family, field="alpha_family"))
        require_identifier(self.strategy_module, field="strategy_module")
        require_identifier(self.trade_template, field="trade_template")
        require_identifier(self.version, field="version")
        stage = _member(LifecycleStage, self.lifecycle_stage, field="lifecycle_stage")
        set_(self, "lifecycle_stage", stage)
        environments = _members(
            Environment, self.authorized_environments, field="authorized_environments"
        )
        if not environments:
            raise BrainContractError("A strategy version must authorize at least one environment.")
        if Environment.PAPER in environments and stage not in PAPER_ELIGIBLE_STAGES:
            raise BrainContractError(
                "PAPER may be authorized only from AUTOMATED_PAPER onward: it is the first "
                "order-producing stage, and reaching it is a human promotion, not a spec edit."
            )
        if Environment.LIVE in environments and stage not in LIVE_ELIGIBLE_STAGES:
            raise BrainContractError(
                "LIVE may be authorized only from MICRO_LIVE_CANARY onward. Live trading is "
                "hard-disabled system-wide regardless of this declaration."
            )
        set_(self, "authorized_environments", environments)
        set_(self, "direction", _member(Direction, self.direction, field="direction"))
        require_positive_int(self.minimum_holding_sessions, field="minimum_holding_sessions")
        require_positive_int(self.maximum_holding_sessions, field="maximum_holding_sessions")
        require_positive_int(self.expected_holding_sessions, field="expected_holding_sessions")
        if not (
            self.minimum_holding_sessions
            <= self.expected_holding_sessions
            <= self.maximum_holding_sessions
        ):
            raise BrainContractError(
                "expected_holding_sessions must lie within the declared holding horizon."
            )
        if type(self.data) is not DataRequirements:
            raise BrainContractError("Field 'data' must be a DataRequirements.")
        if type(self.permissions) is not Permissions:
            raise BrainContractError("Field 'permissions' must be a Permissions.")
        definitions = tuple(self.factor_definitions)
        if not definitions or any(type(d) is not FactorDefinition for d in definitions):
            raise BrainContractError("factor_definitions must be a non-empty tuple of definitions.")
        if len({d.factor_id for d in definitions}) != len(definitions):
            raise BrainContractError("factor_definitions must not repeat a factor id.")
        set_(self, "factor_definitions", definitions)
        deepest = max(d.lookback_sessions for d in definitions)
        if self.data.required_history_sessions < deepest:
            raise BrainContractError(
                "required_history_sessions must cover the deepest factor lookback; a version "
                "that declares less history than its factors need would compute over nothing."
            )
        require_identifier(self.factor_definition_version, field="factor_definition_version")
        require_identifier(self.parameters_hash, field="parameters_hash")
        require_identifier(self.manifest_version, field="manifest_version")
        require_identifier(self.configuration_identity, field="configuration_identity")
        require_optional_identifier(self.model_version, field="model_version")
        require_optional_identifier(self.prompt_version, field="prompt_version")
        self._require_consistent_declarations()
        if type(self.risk_tags) is not RiskTags:
            raise BrainContractError("Field 'risk_tags' must be a RiskTags.")
        if self.risk_tags.family_exposure is not self.alpha_family:
            raise BrainContractError("risk_tags.family_exposure must equal alpha_family.")
        if type(self.research) is not ResearchGovernance:
            raise BrainContractError("Field 'research' must be a ResearchGovernance.")

    def _require_consistent_declarations(self) -> None:
        """Each permission and domain must agree with the others and with the direction."""
        permissions = self.permissions
        required = self.data.required_domains
        pairs = (
            (permissions.market_prerequisite, DataDomain.MARKET_PERMISSION, "market"),
            (permissions.event_prerequisite, DataDomain.EVENT_CALENDAR, "event"),
            (permissions.ai_requirement, DataDomain.AI_RESEARCH, "AI"),
            (permissions.borrow_prerequisite, DataDomain.BORROW, "borrow"),
        )
        for requirement, domain, label in pairs:
            if (requirement is Requirement.REQUIRED) != (domain in required):
                raise BrainContractError(
                    f"The {label} prerequisite and the {domain.value} domain must agree: a "
                    "required prerequisite needs its evidence declared required, and vice versa."
                )
        if self.direction is Direction.SHORT:
            if permissions.borrow_prerequisite is not Requirement.REQUIRED:
                raise BrainContractError(
                    "A SHORT version must require the borrow prerequisite. Short is a separate "
                    "evidence path, not a stricter long path."
                )
        elif permissions.borrow_prerequisite is not Requirement.NOT_APPLICABLE:
            raise BrainContractError(
                "A LONG version declares the borrow prerequisite NOT_APPLICABLE."
            )
        if permissions.ai_requirement is Requirement.REQUIRED:
            if self.model_version is None or self.prompt_version is None:
                raise BrainContractError(
                    "A version that requires AI evidence must pin a model version and a prompt "
                    "version. An unpinned version is a refusal, never a resolution."
                )
        elif self.model_version is not None or self.prompt_version is not None:
            raise BrainContractError(
                "A version that does not require AI evidence pins no model or prompt version."
            )
        if permissions.gap_prerequisite is Requirement.NOT_APPLICABLE:
            raise BrainContractError("The gap prerequisite is REQUIRED or OPTIONAL, never N/A.")

    def refusal_for(self, environment: Environment) -> ReasonCode | None:
        """Why this version may not produce a candidate in ``environment``, or ``None``.

        The two runtime refusals of section 9. Version pins are constructor
        rules and cannot be violated by a constructed spec.
        """
        if self.lifecycle_stage not in CANDIDATE_PRODUCING_STAGES:
            return ReasonCode.LIFECYCLE_STAGE_NOT_CANDIDATE_PRODUCING
        if environment not in self.authorized_environments:
            return ReasonCode.ENVIRONMENT_NOT_AUTHORIZED
        return None

    @property
    def reference(self) -> str:
        """``strategy_id@version`` -- how the version is cited in a record."""
        return f"{self.strategy_id}@{self.version}"


__all__ = [
    "DataRequirements",
    "Permissions",
    "ResearchGovernance",
    "RiskTags",
    "StrategySpec",
]
