"""The pinned exchange-session calendar a build consumes. Configuration, versioned.

**Every session carries its own open instant, as an aware UTC datetime.** No timezone
database is consulted: the calendar is a compiled artifact with a version that the
manifest records, so two builds on the same calendar version compute the same
``decision_time(d)`` and a differing calendar is a differing configuration rather than
a silent drift. A real exchange calendar is a later, separately reviewed artifact; the
one exercised in this repository is synthetic.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final

#: The operational margin before the session open at which membership is decided
#: (ADR-0035 §3.4, initial value). A rule parameter carried in the manifest.
DEFAULT_DECISION_MARGIN: Final = timedelta(minutes=30)


@dataclass(frozen=True, slots=True, kw_only=True)
class Session:
    """One exchange session and the instant it opens."""

    session_date: date
    open_at: datetime

    def __post_init__(self) -> None:
        if type(self.session_date) is not date:
            raise TypeError("session_date must be an exact date")
        if type(self.open_at) is not datetime or self.open_at.tzinfo is None:
            raise TypeError("open_at must be an aware datetime")
        if self.open_at.date() < self.session_date:
            raise ValueError("a session opens on or after its own date")


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionCalendar:
    """An ordered, gap-free-by-declaration list of sessions under one version."""

    version: str
    sessions: tuple[Session, ...]

    def __post_init__(self) -> None:
        if type(self.version) is not str or not self.version:
            raise ValueError("a calendar carries a version")
        dates = [session.session_date for session in self.sessions]
        if dates != sorted(set(dates)):
            raise ValueError("sessions must be strictly increasing and distinct")
        opens = [session.open_at for session in self.sessions]
        if opens != sorted(opens):
            raise ValueError("session opens must be increasing")

    def __repr__(self) -> str:
        """Version and count only."""
        return f"SessionCalendar(version={self.version!r}, sessions={len(self.sessions)})"

    def _index(self, session_date: date) -> int | None:
        dates = [session.session_date for session in self.sessions]
        index = bisect_left(dates, session_date)
        if index < len(dates) and dates[index] == session_date:
            return index
        return None

    def is_session(self, session_date: date) -> bool:
        """Whether ``session_date`` is a session of this calendar."""
        return self._index(session_date) is not None

    def open_at(self, session_date: date) -> datetime | None:
        """The open instant of a session, or ``None`` for a date that is not one."""
        index = self._index(session_date)
        return None if index is None else self.sessions[index].open_at

    def decision_time(self, session_date: date, *, margin: timedelta) -> datetime | None:
        """``open(d) - margin``: the one instant membership for ``d`` is fixed at."""
        opened = self.open_at(session_date)
        return None if opened is None else opened - margin

    def previous(self, session_date: date) -> date | None:
        """The session immediately before ``session_date`` (``d-1``), or ``None``."""
        index = self._index(session_date)
        if index is None or index == 0:
            return None
        return self.sessions[index - 1].session_date

    def next_session(self, session_date: date) -> date | None:
        """The session immediately after ``session_date``, or ``None``."""
        index = self._index(session_date)
        if index is None or index + 1 >= len(self.sessions):
            return None
        return self.sessions[index + 1].session_date

    def trailing(self, session_date: date, *, count: int) -> tuple[date, ...]:
        """The ``count`` sessions ending at ``session_date`` inclusive, oldest first.

        Fewer than ``count`` when the calendar does not reach back that far -- which
        a history clause must treat as history it cannot see, not as history present.
        """
        index = self._index(session_date)
        if index is None or count <= 0:
            return ()
        start = max(0, index + 1 - count)
        return tuple(session.session_date for session in self.sessions[start : index + 1])


__all__ = ["DEFAULT_DECISION_MARGIN", "Session", "SessionCalendar"]
