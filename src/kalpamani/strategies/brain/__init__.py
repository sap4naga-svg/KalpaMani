"""The Strategy Brain kernel — the offline, deterministic foundation of ADR-0026.

The Brain sits entirely on the information side of the locked principle: it says
**why** an opportunity exists, **why now**, what evidence supports or rejects it
and what deterministic status it has. Its terminal output is a typed
:class:`~kalpamani.strategies.brain.intent.CandidateIntent`, and nothing else --
no share count, no dollar amount, no order type, no route, no order identity.
Those are the later portfolio, risk and execution layers' questions, and no
module in this package can answer them because no field exists to carry the
answer.

What this package implements, against the accepted specification
(``docs/phase4/strategy-brain-specification.md``):

``vocabulary``
    the closed decision states, reason codes, lifecycle and health stages and
    the thirteen compiler stages. Instruction-shaped states are refused by name.
``evidence``
    the input contracts the Brain evaluates: kernel point-in-time results plus
    the small context records (event, market permission, AI, short) a module may
    declare it requires.
``gate``
    the point-in-time reality gate -- stage one, before any strategy logic.
``factors``
    deterministic ``Decimal`` factor computations for the price and volume
    families. Computations, not production factor selections.
``spec``
    the versioned, immutable ``StrategySpec``.
``module``
    what a strategy module hands the compiler, and nothing more.
``consolidation``
    one economic opportunity, many evidence paths, attribution preserved.
``compiler``
    the thirteen ordered validations, stopping at the first refusal.
``intent``
    the ``CandidateIntent`` record and its structural exclusions.
``journal``
    the per-candidate audit record, carrying references and never payload bytes.
``health``
    the seven-state strategy health machine and its one asymmetry.

What it does not do. It reads no network, provider, broker, model, database or
clock; every instant is injected. It computes no size and constructs no order.
It selects no provider, qualifies no data and closes no gate. Every threshold a
strategy module carries is a **proposed research parameter** recorded in a
research-stage ``StrategySpec`` that authorizes the ``RESEARCH`` environment and
no other. **No alpha is claimed by anything here.**
"""

from __future__ import annotations

__all__: list[str] = []
