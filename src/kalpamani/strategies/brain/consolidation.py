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
"""

from __future__ import annotations

from dataclasses import dataclass

from kalpamani.strategies.brain.identity import require_identifier
from kalpamani.strategies.brain.intent import ModuleAttribution, StrategyAttribution
from kalpamani.strategies.brain.spec import StrategySpec
from kalpamani.strategies.brain.vocabulary import AlphaFamily, Direction, ModuleVerdict


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
        require_identifier(self.strategy_id, field="strategy_id")
        require_identifier(self.strategy_version, field="strategy_version")
        require_identifier(self.strategy_module, field="strategy_module")
        require_identifier(self.trade_template, field="trade_template")


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
    """
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


__all__ = ["ConsolidationResult", "PeerConclusion", "consolidate"]
