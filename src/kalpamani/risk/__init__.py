"""Deterministic risk engine: sizing, stops, gap/event budgets, circuit breakers.

AI never sizes a position or overrides a limit. This package is deterministic.

Bootstrap status: EMPTY BY DESIGN. Only risk PARAMETERS exist, in
kalpamani.common.capital -- not the engine that applies them.
"""
