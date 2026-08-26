"""The point-in-time data platform.

Deliberately separate from brokerage execution: broker market data must never be
the sole source for universe ranking or backtests (Blueprint V2.1 s.26), and no
broker-native identifier appears anywhere in this package (ADR-0002 s.13,
conceptual-schema s.19 rules 9 and 10). ``kalpamani.data`` may not import
``kalpamani.broker`` or ``kalpamani.execution``, and a static test enforces it.

Layout, and who may import what:

``contracts``
    the schemas and the rules over them. No vendor knowledge, no I/O.
``pit``
    historical accessors. ``as_of`` and ``profile`` mandatory, no defaults.
``live``
    current accessors, ``as_of`` forbidden. **Unimplemented in this slice.**
``ingest``
    bronze writers. No network client exists yet.
``normalize``
    silver transforms: bronze bytes to normalised source facts.
``curate``
    gold builders -- adjustment, historical universe, the curated store.
``quality``
    deterministic checks returning typed findings.

Research, strategy, risk and portfolio code may import ``contracts`` and ``pit``
and **nothing else** here. Two packages rather than one package with a flag,
because a flag is a thing that can be set wrongly and a missing import is a thing
that fails in CI.

**Status: Phase 3A A1 foundation kernel, IN REVIEW.** Vendor-neutral and proven
against repository-owned synthetic fixtures only. No provider is connected, no
external data has been acquired, and no result produced here is evidence about
any real security.
"""
