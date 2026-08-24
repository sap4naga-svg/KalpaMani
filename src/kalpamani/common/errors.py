"""KalpaMani exception hierarchy.

Safety-relevant failures raise subclasses of :class:`SafetyViolationError` so
that callers can never confuse a safety refusal with an ordinary error.
"""

from __future__ import annotations


class KalpaManiError(Exception):
    """Base class for all KalpaMani errors."""


class ConfigurationError(KalpaManiError):
    """Configuration is missing, malformed or internally inconsistent."""


class SafetyViolationError(KalpaManiError):
    """An operation was refused because it would breach a system safety rule.

    These are never recoverable by retrying. They indicate that code attempted
    something the governance model forbids.
    """


class LiveTradingDisabledError(SafetyViolationError):
    """Live brokerage execution was requested while it is hard-disabled.

    Live trading requires BOTH an explicitly approved deployment phase AND a
    second independent authorization gate that is deliberately not implemented
    during bootstrap. Selecting ``Environment.LIVE`` alone is never sufficient.
    """


class CapitalIntegrityError(SafetyViolationError):
    """An operation would have corrupted the allocated strategy capital.

    Most importantly: broker-reported account equity (for example a simulated
    IBKR paper balance of USD 1,000,000) must never become KalpaMani strategy
    capital.
    """


__all__ = [
    "CapitalIntegrityError",
    "ConfigurationError",
    "KalpaManiError",
    "LiveTradingDisabledError",
    "SafetyViolationError",
]
