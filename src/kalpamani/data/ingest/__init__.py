"""Bronze ingestion: immutable, content-addressed raw payload storage.

**No network client exists here, and none is authorized in this slice.** The
Bronze writer receives bytes a caller already holds, so it has no HTTP
dependency, no credential handling and no provider knowledge -- which is exactly
why it can be built and tested before gate G1 selects a provider.

Research, strategy, risk and portfolio code may not import this package.
"""
