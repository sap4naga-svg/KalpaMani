"""Order construction, submission, fill protection and reconciliation.

Requires deterministic client/order IDs for idempotency and duplicate-order
prevention before any automated order testing (Blueprint V2.1, s.16).

Bootstrap status: EMPTY BY DESIGN. No order can be submitted.
"""
