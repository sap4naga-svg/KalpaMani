"""Private empirical provider qualification (ADR-0018).

**Separate from :mod:`kalpamani.data.ingest` on purpose, and structurally.** The
acquisition path publishes vendor responses byte for byte and never parses them;
this package parses them. Keeping the parser out of the ingestion package is what
makes the opaque-payload boundary a property of the import graph rather than a
rule somebody has to remember, and a static test refuses any import from
``data/ingest/`` into here.

**Nothing in this package runs by itself.** Importing it constructs no client,
reads no environment variable, opens no socket and resolves no credential. The
two operator entry points that drive it live in ``scripts/`` and refuse by
default; execution against real services is a separate written authorization that
has not been given.
"""
