"""The Phase 2 regular-hours entry window (ADR-0004 §14).

Phase 2 submits a MARKET order. A market order asks the book for whatever price
it has, so the certification is only meaningful -- and only safe -- in a liquid
regular session. Outside it, quoted spreads on SPY widen, extended-hours fills
are routed differently, and a "1 share of SPY" reference guard stops being a
realistic bound on what actually fills.

The runbook said "market hours only" for exactly this reason. A runbook line is
an instruction to a human; this module makes it a condition the code enforces.

Three gates, all required
-------------------------
1. **The exchange says the regular session is open.** Supplied by the caller
   from LEAN, which excludes extended hours and knows the real calendar --
   holidays, half days, early closes. We do not re-implement that.
2. **The clock is past the open buffer.** The opening auction is the least
   representative part of the day.
3. **The day's ACTUAL close is still at least half an hour away.**

Gate 3 is derived, not assumed, and that is the point. An earlier version
hardcoded a 15:30 upper bound, which is correct only on a normal 16:00 close. On
a 13:00 early close -- the sessions before Thanksgiving, Christmas Eve, Independence
Day -- 12:59 satisfied both "the session is open" and "before 15:30", so the entry
could have fired **one minute before the close**, with no time to observe the
protective stop, let alone exit. The close now comes from the exchange calendar
via ``QCAlgorithm``, so a half day narrows the window by itself.

On a normal 16:00 close this yields 09:45-15:30, which is what the runbook has
always documented. The difference is that 15:30 is now a consequence rather than
an assumption.

The window gates the ENTRY only. Protective and exit actions are never gated on
it: refusing to protect or close a position because of the clock would turn a
liquidity precaution into a risk.

TEST PARAMETER -- NOT PRODUCTION STRATEGY LOGIC. The window is a certification
constraint chosen for liquidity, and encodes no view on when it is a good idea
to trade.
"""

from __future__ import annotations

from datetime import time

from kalpamani.common.errors import SafetyViolationError

#: The algorithm time zone Phase 2 pins, so ``time`` values are unambiguous.
PHASE2_TIME_ZONE = "America/New_York"

#: No entry before this, in :data:`PHASE2_TIME_ZONE`. 15 minutes after the 09:30
#: open, so the opening auction is excluded.
PHASE2_WINDOW_OPEN = time(9, 45)

#: No entry within this many minutes of the day's ACTUAL regular close, whatever
#: the calendar says that is. 30 minutes before a normal 16:00 close is 15:30;
#: before a 13:00 early close it is 12:30.
PHASE2_MIN_MINUTES_TO_CLOSE = 30.0


class TradingWindowError(SafetyViolationError):
    """The entry was attempted outside the Phase 2 certification window."""


def within_certification_window(now: time, minutes_to_close: float | None) -> bool:
    """Whether both clock gates hold. ``None`` minutes_to_close is never inside."""
    if minutes_to_close is None:
        return False
    return now >= PHASE2_WINDOW_OPEN and minutes_to_close >= PHASE2_MIN_MINUTES_TO_CLOSE


def assert_within_certification_window(
    now: time,
    *,
    regular_session_open: bool,
    minutes_to_close: float | None,
) -> None:
    """Assert all three gates hold before the entry may be authorised.

    Args:
        now: exchange-local time, in :data:`PHASE2_TIME_ZONE`.
        regular_session_open: the exchange's own answer, excluding extended
            hours. Never inferred from the clock -- only the calendar knows about
            holidays and early closes.
        minutes_to_close: minutes until the day's ACTUAL regular close, from the
            exchange calendar. ``None`` means the calendar could not answer, which
            fails closed: an unknown close is not a distant one.

    Raises:
        TradingWindowError: if any gate fails.
    """
    if not regular_session_open:
        raise TradingWindowError(
            f"The {PHASE2_TIME_ZONE} regular session is not open (exchange calendar says "
            f"closed at {now.isoformat(timespec='minutes')}). Phase 2 submits a MARKET order "
            "and will not do so outside regular hours. Staying read-only."
        )
    if now < PHASE2_WINDOW_OPEN:
        raise TradingWindowError(
            f"{now.isoformat(timespec='minutes')} is before the Phase 2 window opens at "
            f"{PHASE2_WINDOW_OPEN.isoformat(timespec='minutes')} {PHASE2_TIME_ZONE}. The "
            "opening auction is the least representative part of the session. Staying "
            "read-only."
        )
    if minutes_to_close is None:
        raise TradingWindowError(
            "The exchange calendar did not report today's regular close, so the distance to "
            "it is unknown. An unknown close is not a distant one; failing closed and "
            "staying read-only."
        )
    if minutes_to_close < PHASE2_MIN_MINUTES_TO_CLOSE:
        raise TradingWindowError(
            f"Only {minutes_to_close:.0f} minute(s) remain until today's ACTUAL regular close "
            f"at {now.isoformat(timespec='minutes')} {PHASE2_TIME_ZONE}; Phase 2 requires at "
            f"least {PHASE2_MIN_MINUTES_TO_CLOSE:.0f}. This is what an early close looks "
            "like -- there would be no time to observe the protective stop, let alone exit. "
            "Staying read-only."
        )


def describe_window() -> str:
    """Log-safe summary for the preflight banner and the arm log."""
    return (
        f"from {PHASE2_WINDOW_OPEN.isoformat(timespec='minutes')} {PHASE2_TIME_ZONE} until "
        f"{PHASE2_MIN_MINUTES_TO_CLOSE:.0f} minutes before the day's ACTUAL regular close "
        "(15:30 on a normal day, 12:30 on a 13:00 half day); regular session only; TEST window"
    )


__all__ = [
    "PHASE2_MIN_MINUTES_TO_CLOSE",
    "PHASE2_TIME_ZONE",
    "PHASE2_WINDOW_OPEN",
    "TradingWindowError",
    "assert_within_certification_window",
    "describe_window",
    "within_certification_window",
]
