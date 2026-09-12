"""Production data-plane runtime foundations (ADR-0036, as amended by ADR-0037).

**Separate from :mod:`kalpamani.data.ingest` and from :mod:`kalpamani.data.qualify`
on purpose.** The ingestion package publishes vendor responses byte for byte and
never parses them; the qualification package parses them for a private assessment;
this package holds the *runtime contracts* the two production actors of ADR-0036 --
the acquisition task and the research-build task -- and their launch tool are held
to before any data operation: bindings, inputs, the placement release, the identity
shape, the disjoint production key layout of ADR-0037 and the run locator.

**Nothing in this package runs by itself.** Importing it constructs no client, reads
no environment variable, opens no socket and resolves no credential. Every external
service is an injected adapter, and the concrete adapters here have only ever been
exercised against synthetic fakes. No production image, no entry point and no
acquisition or build *processing* exists: the runner stops at a closed
``HALTED_PROCESSING_NOT_IMPLEMENTED`` after the release barrier, having performed
zero S3, secret and provider operations.
"""
