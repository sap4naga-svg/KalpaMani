"""Market data and fundamentals ingestion.

Deliberately separate from brokerage execution: broker market data must never
be the sole source for universe ranking or backtests (Blueprint V2.1, s.26).

Bootstrap status: EMPTY BY DESIGN.
"""
