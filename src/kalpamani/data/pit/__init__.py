"""Historical point-in-time accessors.

``as_of``, ``profile`` and -- over revisable facts -- ``revision_view`` are
mandatory and have **no defaults**. A default here is a decision made silently by
whoever wrote the accessor rather than by whoever asked the question.

There is no ``latest``, ``current``, ``most_recent`` or ``today`` route, and a
static test asserts that no such identifier exists anywhere in this package.

This package and :mod:`kalpamani.data.contracts` are the only parts of the data
platform research, strategy, risk and portfolio code may import.
"""

from __future__ import annotations

__all__: list[str] = []
