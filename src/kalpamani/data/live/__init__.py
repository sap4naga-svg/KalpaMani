"""Current-state accessors for live scanning. ``as_of`` is forbidden here.

**Unimplemented in this slice, and deliberately so.** Nothing in Phase 3A needs
current data: A1 builds the historical foundation, and live scanning belongs to a
phase that has not been authorized.

The package exists now for one reason. ``data.pit`` and ``data.live`` are two
packages rather than one package with a flag, because a flag is a thing that can
be set wrongly and a missing import is a thing that fails in CI. Research and
backtest code importing this package is a static-test failure -- the same shape
as ADR-0004 s.10's rule that strategy modules cannot import execution. Creating
the boundary before there is anything behind it means the boundary is inherited
by whatever arrives, rather than retrofitted around it under time pressure.

There is no accessor here, and adding one is a phase decision, not an
implementation detail.
"""

from __future__ import annotations

__all__: list[str] = []
