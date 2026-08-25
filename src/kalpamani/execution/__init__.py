"""Order construction, submission, fill protection and reconciliation.

Phase 2 status: MINIMUM ORDER-CAPABLE BOUNDARY (ADR-0004). Contains
deterministic order identity, validated lifecycle states, a durable trade state
store, the Phase 2 safety envelope with its one-time execution arm, and
broker-vs-internal reconciliation.

Strategy modules must NOT import this package. Order capability is reached only
through the execution boundary, never from strategy logic (ADR-0002 s.3,
ADR-0004 s.10), and a test enforces that.

Phase 2 is execution plumbing certification: SPY only, long only, exactly one
share, IBKR Paper only, one intent, one entry.
"""
