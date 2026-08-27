"""The one place an instant becomes canonical.

Every timezone-aware datetime that enters the data platform passes through
:func:`normalize_instant` before it is stored, compared or hashed. Three rules,
and each exists because its absence corrupts something downstream:

**A naive datetime is refused, never assumed.** Guessing a zone is how a full
day of look-ahead gets introduced -- a 20:00 ET print read as UTC lands on the
next session (contract 12.7). There is no default and no fallback.

**A ``tzinfo`` whose ``utcoffset()`` is ``None`` is refused.** It looks aware and
is not: it cannot answer what instant it denotes, so it cannot be normalised or
ordered.

**An aware non-UTC datetime is converted, not rejected.** ``2026-01-01T12:00:00Z``
and ``2026-01-01T07:00:00-05:00`` are the *same instant*, so they must produce
the same canonical value, the same stored bytes and the same content hash.
Storing the offset the caller happened to hold would make an artifact's identity
depend on which timezone the ingestion process ran in -- and two builds of the
same data would then disagree about being the same build.

**Dates stay dates.** There is deliberately no date-to-instant helper here. A
business date is never silently promoted to midnight-anything (contract 12.6);
where an instant is genuinely needed from a date, the exchange calendar supplies
it.
"""

from __future__ import annotations

from datetime import UTC, datetime


def normalize_instant(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC instant.

    Raises:
        TypeError: if ``value`` is naive, or carries a ``tzinfo`` that cannot
            state its offset. Both are refusals rather than best guesses.
    """
    if value.tzinfo is None:
        raise TypeError(
            "Refusing a naive datetime. Every instant in the data platform is timezone-aware "
            "UTC; assuming a zone here would be a silent look-ahead of up to a full day."
        )
    if value.tzinfo.utcoffset(value) is None:
        raise TypeError(
            "Refusing a datetime whose tzinfo cannot state its UTC offset. It looks aware and "
            "is not: it denotes no particular instant, so it can be neither ordered nor hashed."
        )
    return value.astimezone(UTC)


def normalize_optional_instant(value: datetime | None) -> datetime | None:
    """:func:`normalize_instant`, passing ``None`` through unchanged."""
    return None if value is None else normalize_instant(value)


def is_canonical_instant(value: datetime) -> bool:
    """Whether ``value`` is already an aware instant expressed in UTC."""
    return value.tzinfo is not None and value.utcoffset() == UTC.utcoffset(None)


__all__ = [
    "is_canonical_instant",
    "normalize_instant",
    "normalize_optional_instant",
]
