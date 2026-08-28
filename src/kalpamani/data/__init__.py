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
    bronze writers, and the one provider package. Vendor knowledge lives inside
    ``ingest.sharadar`` and nowhere else; the neutral writers never import it.
``objectstore``
    the provider-neutral logical object contract Bronze publishes through.
    Classification is part of an object's identity, and LICENSED is what you get
    by writing the ordinary thing.
``storage``
    the backends behind that contract. ``storage.local`` is the Silver/Gold
    analytical store; ``storage.s3`` is the licensed cloud object store
    (ADR-0011) -- **code only, and it has never run against AWS.** ``s3`` is
    deliberately *not* re-exported from the package, so importing the data
    platform pulls in no AWS SDK, opens no socket and discovers no credential.
    It is also the only module in the repository permitted to name that SDK.
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

**Status: Phase 3A A1 foundation kernel, ACCEPTED**, plus two separately
authorized code-only slices on top of it -- the Sharadar provider adapter
(ADR-0009) and the licensed S3 object store (ADR-0011). Everything here is proven
against repository-owned synthetic fixtures only. **No provider is connected, no
request has ever been sent to a vendor, no object has ever been written to AWS**,
no external data has been acquired, and no result produced here is evidence about
any real security.
"""
