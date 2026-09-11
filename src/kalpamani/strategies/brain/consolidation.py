"""Candidate consolidation (specification section 8).

One economic opportunity may qualify through several modules; presenting it as
several candidates is how a single exposure acquires several risk budgets. The
Brain consolidates before portfolio risk is considered, and preserves the
attribution of every contributing module so each can still be measured apart.

This slice ships one module, so the ordinary case is a single attribution. The
machinery is here in full anyway, because the rule it enforces -- a direction
contradiction between two modules on one security **blocks**, it never silently
prefers one -- is architecture, not an optimisation, and it is exercised with
synthetic peer attributions in the tests.

A peer is a *record of another module's conclusion*, not a second evaluation
run here: consolidation combines conclusions, it does not re-decide them.

**Attribution order is canonical, not caller order.** The primary module is
always rank 1; peers follow in ``(strategy_id, strategy_version)`` order, so two
calls that supply the same peers in a different sequence produce the same
attribution. A module attributed twice is refused, because one module counted
twice is the double-counting consolidation exists to remove.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

from kalpamani.strategies.brain.errors import BrainContractError
from kalpamani.strategies.brain.identity import require_identifier
from kalpamani.strategies.brain.intent import ModuleAttribution, StrategyAttribution
from kalpamani.strategies.brain.spec import StrategySpec
from kalpamani.strategies.brain.vocabulary import (
    AlphaFamily,
    Direction,
    ModuleVerdict,
    closed_member,
)

Member = TypeVar("Member", bound=StrEnum)


def _member(vocabulary: type[Member], value: object, *, field: str) -> Member:
    member = closed_member(vocabulary, value)
    if member is None:
        raise BrainContractError(f"Field {field!r} must be a {vocabulary.__name__} member.")
    return member


@dataclass(frozen=True, slots=True, kw_only=True)
class PeerConclusion:
    """Another module's conclusion about the same security in the same decision window.

    Carries only what consolidation needs: the module's identity, its family and
    direction, and the verdict it reached. It never carries a size or an order.
    """

    strategy_id: str
    strategy_version: str
    strategy_module: str
    trade_template: str
    alpha_family: AlphaFamily
    direction: Direction
    verdict: ModuleVerdict

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        require_identifier(self.strategy_id, field="strategy_id")
        require_identifier(self.strategy_version, field="strategy_version")
        require_identifier(self.strategy_module, field="strategy_module")
        require_identifier(self.trade_template, field="trade_template")
        # Closed members, normalised at construction: a bare string that happened
        # to spell a direction compared unequal by identity below and was read as
        # a contradiction, or not, by accident rather than by rule.
        set_(self, "alpha_family", _member(AlphaFamily, self.alpha_family, field="alpha_family"))
        set_(self, "direction", _member(Direction, self.direction, field="direction"))
        set_(self, "verdict", _member(ModuleVerdict, self.verdict, field="verdict"))


def require_peers(peers: object, *, primary_strategy_id: str) -> tuple[PeerConclusion, ...]:
    """``peers`` as a canonically ordered tuple of distinct :class:`PeerConclusion`.

    Raises:
        BrainContractError: if ``peers`` is not a tuple of exact ``PeerConclusion``
            records, if a strategy id appears twice, or if a peer carries the
            primary module's own id -- each is one module counted twice.
    """
    if not isinstance(peers, tuple) or any(type(peer) is not PeerConclusion for peer in peers):
        raise BrainContractError("peers must be a tuple of PeerConclusion records.")
    ids = [peer.strategy_id for peer in peers]
    if len(set(ids)) != len(ids) or primary_strategy_id in ids:
        raise BrainContractError(
            "Each module contributes at most one conclusion to a consolidation; a module "
            "attributed twice is the double-counting consolidation exists to remove."
        )
    return tuple(sorted(peers, key=lambda peer: (peer.strategy_id, peer.strategy_version)))


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsolidationResult:
    """What consolidation concluded: the attribution, and whether directions conflict."""

    attribution: StrategyAttribution
    has_direction_contradiction: bool
    contradicting_module_ids: tuple[str, ...]


def consolidate(
    *,
    spec: StrategySpec,
    primary_direction: Direction,
    primary_verdict: ModuleVerdict,
    peers: tuple[PeerConclusion, ...] = (),
) -> ConsolidationResult:
    """Consolidate the primary module with any peers on the same security.

    The primary module is always attribution rank 1. Peers that reached an
    active conclusion (triggered, or an eligible setup) and take the **opposite**
    direction raise a direction contradiction; the result records them and the
    compiler returns ``BLOCKED_CONTRADICTION``. Peers that agree in direction are
    kept as further ranked attributions so their contribution stays measurable.

    Peers are validated and canonically ordered here as well as at the compiler's
    entry, so a direct caller gets the same refusals and the same ranks.
    """
    peers = require_peers(peers, primary_strategy_id=spec.strategy_id)
    contradictions: list[str] = []
    contributing = [
        ModuleAttribution(
            strategy_id=spec.strategy_id,
            strategy_version=spec.version,
            trade_template=spec.trade_template,
            verdict=primary_verdict,
            rank=1,
        )
    ]
    next_rank = 2
    for peer in peers:
        active = peer.verdict in (ModuleVerdict.TRIGGERED, ModuleVerdict.SETUP_NOT_TRIGGERED)
        if active and peer.direction is not primary_direction:
            contradictions.append(peer.strategy_id)
        contributing.append(
            ModuleAttribution(
                strategy_id=peer.strategy_id,
                strategy_version=peer.strategy_version,
                trade_template=peer.trade_template,
                verdict=peer.verdict,
                rank=next_rank,
            )
        )
        next_rank += 1
    attribution = StrategyAttribution(
        alpha_family=spec.alpha_family,
        strategy_id=spec.strategy_id,
        strategy_module=spec.strategy_module,
        trade_template=spec.trade_template,
        strategy_version=spec.version,
        factor_definition_version=spec.factor_definition_version,
        contributing=tuple(contributing),
    )
    return ConsolidationResult(
        attribution=attribution,
        has_direction_contradiction=bool(contradictions),
        contradicting_module_ids=tuple(contradictions),
    )


__all__ = ["ConsolidationResult", "PeerConclusion", "consolidate", "require_peers"]
