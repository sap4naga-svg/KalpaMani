"""The Phase 2 regular-hours entry window (ADR-0004 §11).

Phase 2 submits a MARKET order. A market order asks the book for whatever price
it has, so the certification is only meaningful -- and only safe -- in a liquid
regular session. Outside it, quoted spreads on SPY widen, extended-hours fills
are routed differently, and a "1 share of SPY" reference guard stops being a
realistic bound on what actually fills.

The runbook said "market hours only" for exactly this reason. A runbook line is
an instruction to a human; this module makes it a condition the code enforces.

Two independent gates, both required
------------------------------------
1. **The exchange says the regular session is open.** Supplied by the caller
   from LEAN (``QCAlgorithm.is_market_open``), which excludes extended hours and
   knows the real calendar -- holidays, half days, early closes. We do not
   re-implement that.
2. **The clock is inside the certification window.** The opening and closing
   auctions are the least representative minutes of the day, so the window
   deliberately starts after the open and ends before the close.

Both must hold. Gate 1 without gate 2 would permit the auction; gate 2 without
gate 1 would permit a holiday.

TEST PARAMETER -- NOT PRODUCTION STRATEGY LOGIC. The window is a certification
constraint chosen for liquidity, and encodes no view on when it is a good idea
to trade.
"""

from __future__ import annotations

from datetime import time

from kalpamani.common.errors import SafetyViolationError

#: The algorithm time zone Phase 2 pins, so ``time`` values are unambiguous.
PHASE2_TIME_ZONE = "America/New_York"

#: Certification window, in :data:`PHASE2_TIME_ZONE`. Starts 15 minutes after the
#: 09:30 open and ends 30 minutes before the 16:00 close, avoiding both auctions.
PHASE2_WINDOW_OPEN = time(9, 45)
PHASE2_WINDOW_CLOSE = time(15, 30)


class TradingWindowError(SafetyViolationError):
    """The entry was attempted outside the Phase 2 certification window."""


def within_certification_window(now: time) -> bool:
    """Whether an exchange-local time falls inside the window (inclusive)."""
    return PHASE2_WINDOW_OPEN <= now <= PHASE2_WINDOW_CLOSE


def assert_within_certification_window(now: time, *, regular_session_open: bool) -> None:
    """Assert both gates hold before the entry may be authorised.

    Args:
        now: exchange-local time, in :data:`PHASE2_TIME_ZONE`.
        regular_session_open: the exchange's own answer, excluding extended
            hours. Never inferred from the clock -- only the calendar knows about
            holidays and early closes.

    Raises:
        TradingWindowError: if the regular session is closed, or the time falls
            outside the window.
    """
    if not regular_session_open:
        raise TradingWindowError(
            f"The {PHASE2_TIME_ZONE} regular session is not open (exchange calendar says "
            f"closed at {now.isoformat(timespec='minutes')}). Phase 2 submits a MARKET order "
            "and will not do so outside regular hours. Staying read-only."
        )
    if not within_certification_window(now):
        raise TradingWindowError(
            f"{now.isoformat(timespec='minutes')} is outside the Phase 2 certification window "
            f"{describe_window()}. The opening and closing auctions are the least "
            "representative minutes of the session, so the window excludes them. "
            "Staying read-only."
        )


def describe_window() -> str:
    """Log-safe summary for the preflight banner and the arm log."""
    return (
        f"{PHASE2_WINDOW_OPEN.isoformat(timespec='minutes')}-"
        f"{PHASE2_WINDOW_CLOSE.isoformat(timespec='minutes')} {PHASE2_TIME_ZONE} "
        "(regular session only; TEST window)"
    )


__all__ = [
    "PHASE2_TIME_ZONE",
    "PHASE2_WINDOW_CLOSE",
    "PHASE2_WINDOW_OPEN",
    "TradingWindowError",
    "assert_within_certification_window",
    "describe_window",
    "within_certification_window",
]
