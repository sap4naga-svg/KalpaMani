"""Sharadar-specific private empirical qualification (ADR-0018).

Vendor knowledge is confined to this subpackage, exactly as it is confined to
``data/ingest/sharadar/`` on the acquisition side. Nothing here is imported by a
neutral module, and nothing here imports the acquisition path's publisher.

**This subpackage neither imports nor adapts the public-test-key harness.** That
harness stays untouched and unauthorized to execute; a static test proves the
absence of the import rather than leaving it to review.
"""
