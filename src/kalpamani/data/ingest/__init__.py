"""Bronze ingestion: immutable, content-addressed raw payload storage.

Two publishers, one set of invariants. :mod:`~kalpamani.data.ingest.bronze`
writes to a local filesystem; :mod:`~kalpamani.data.ingest.publication` writes to
a :class:`~kalpamani.data.objectstore.ResearchObjectStore`. Both store a payload
byte for byte exactly as received, name it by the SHA-256 of its contents, and
never overwrite. Both are **provider-neutral**: they receive bytes a caller
already holds, so neither has an HTTP dependency, a credential or any vendor
knowledge.

:mod:`~kalpamani.data.ingest.sharadar` is the one provider package, authorized by
[ADR-0009](../../../../docs/decisions/ADR-0009-sharadar-provider-realistic-implementation.md).
Vendor knowledge stays inside it, and the neutral layer above never imports it --
which is what keeps "the adapter feeds evidence into the architecture" true rather
than aspirational. **It has never sent a request**; a subscription, a private
credential and production ingestion each remain separately unauthorized.

Research, strategy, risk and portfolio code may not import this package at all.
"""
