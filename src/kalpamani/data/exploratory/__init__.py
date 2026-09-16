"""Exploratory research isolation (proposed ADR-0051): research-only vocabulary and contracts.

Everything in this package describes evidence whose historical availability is **assumed**,
not evidenced: an exploratory publication is derived from production Gold under the
``AS_DATED`` assumption that a bar was knowable at its own session close, an attribute at all
times and an action at its date. That assumption is what makes a historical simulation
possible, and it is exactly what production P-2/P-3 refuse to assume. The two worlds are kept
apart by construction:

* the exploratory profile and derivation live in **this** vocabulary, never in the accepted
  ``InformationSetProfile`` / ``ProviderBoundDerivation`` (which stay closed and unchanged);
* an exploratory publication can be consumed only through an explicit
  :class:`~kalpamani.data.exploratory.specification.ResearchSpecification` that names the
  profile; every other consumer -- the accepted ``StrategySpec`` of Breakout Long included --
  is refused at admission;
* no module under ``kalpamani.data.production``, ``kalpamani.data.pit``,
  ``kalpamani.data.curate``, ``kalpamani.data.contracts`` or ``kalpamani.strategies`` imports
  this package (a static test holds it), so nothing production-side can consume or emit it;
* every document is parsed totally and closed: a missing, unknown, production-valued, mixed or
  contradictory profile or provenance refuses.

Nothing here qualifies any period as point-in-time, satisfies G2 or any promotion criterion,
or authorizes an acquisition, a build, a run or any spend. The bridge from production Gold,
the benchmark, the backtest runner and the portfolio ledger are **not** in this package.
"""
