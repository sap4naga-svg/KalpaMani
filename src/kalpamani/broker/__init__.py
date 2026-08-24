"""Broker adapters. All broker-specific logic lives behind a BrokerAdapter.

Phase 1 status: READ-ONLY BOUNDARY ONLY (ADR-0002). `account` exposes an
immutable account snapshot and a paper-account guard. There is deliberately
no order-submission surface anywhere in this package, and adding one is an
ADR-level change rather than an ordinary code change.

IBKR connectivity itself is reached through QuantConnect LEAN's officially
supported Interactive Brokers integration, not a hand-rolled client.
"""
