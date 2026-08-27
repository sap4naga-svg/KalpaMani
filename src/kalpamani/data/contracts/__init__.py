"""Vendor-neutral point-in-time data contracts.

The schemas and the rules that govern them, with **no vendor knowledge** and no
I/O. Importing this package creates no directory, opens no file and reads no
clock.

This is the one package research, strategy, risk and portfolio code may import
alongside :mod:`kalpamani.data.pit`. Everything else under
:mod:`kalpamani.data` -- ingestion, normalisation, curation, live access -- is
off-limits to them, enforced by static test rather than by convention.

Read the modules in this order:

``vocabulary``
    the closed enums. Nothing outside them is representable.
``envelope``
    the two mutually exclusive availability envelopes.
``anchors``
    resolved fact-time anchors and the contract's domain-alias table.
``resolution``
    resolved availability times, origin eligibility, the governing decision time.
``profiles``
    per-dataset gap resolution and the global downgrade.
``entities``
    the Phase-3A entity subset.
``canonical``
    deterministic serialisation and content hashing, on which every identity in
    the system rests.
"""

from __future__ import annotations

__all__: list[str] = []
