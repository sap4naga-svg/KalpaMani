"""Canonical serialisation and content hashing.

Pure functions. No I/O, no filesystem, no clock -- so the same value always
produces the same bytes and therefore the same hash, on any machine, in any
process, in any order.

That property is the whole point. Content hashes are identity in this system:
Bronze objects are named by their hash, derived artifacts are keyed by theirs,
dataset versions carry one, and ``run_id`` is derived from a canonical rendering
of a manifest's load-bearing inputs. A serialiser whose output depended on dict
ordering, float formatting or locale would make every one of those identities a
coincidence.

Rules, each of which exists because its absence would silently break identity:

- **Mappings are emitted with sorted keys.** Insertion order is not meaning.
- **Decimals are emitted as their exact string form**, never as floats. A float
  round-trip is how ``0.1`` becomes ``0.1000000000000000055511151231257827``.
- **Instants must be timezone-aware and are emitted in UTC**, to microsecond
  precision, with an explicit ``+00:00`` offset. A naive datetime is refused
  rather than assumed to be UTC.
- **Dates stay dates.** A ``date`` is emitted as ``YYYY-MM-DD`` and is never
  silently promoted to midnight-anything (contract 12.6).
- **Enums are emitted by value**, so a renamed Python member with the same wire
  value does not change an artifact's identity.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Final

#: Prefix distinguishing a hash from an opaque string wherever one is stored.
SHA256_PREFIX: Final = "sha256:"


def canonical_value(value: object) -> Any:
    """Reduce ``value`` to a JSON-safe form with deterministic representation.

    Raises:
        TypeError: if ``value`` is of a type with no canonical form, or is a
            naive datetime. Guessing a timezone is how a full day of look-ahead
            gets introduced (contract 12.7), so it is refused instead.
    """
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, Enum):
        return canonical_value(value.value)
    if isinstance(value, Decimal):
        return f"D:{value}"
    if isinstance(value, datetime):
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise TypeError(
                "Refusing to canonicalise a naive datetime. Every instant in the data "
                "platform is timezone-aware UTC; assuming a zone here would be a silent "
                "look-ahead of up to a full day."
            )
        return "T:" + value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, date):
        # Checked after datetime: datetime is a date subclass, and conflating the
        # two is exactly the promotion the contract forbids.
        return "D8:" + value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(k): canonical_value(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, Sequence):
        return [canonical_value(v) for v in value]
    if isinstance(value, frozenset | set):
        return sorted(canonical_json(v) for v in value)
    if isinstance(value, float):
        raise TypeError(
            "Refusing to canonicalise a float. Prices, ratios and rates use Decimal so "
            "that an artifact hash is a property of the value rather than of the binary "
            "representation that happened to be produced."
        )
    raise TypeError(f"No canonical form for {type(value).__name__}.")


def canonical_json(value: object) -> str:
    """Render ``value`` as canonical JSON text: sorted keys, no incidental whitespace."""
    return json.dumps(
        canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def canonical_bytes(value: object) -> bytes:
    """Render ``value`` as canonical UTF-8 bytes."""
    return canonical_json(value).encode("utf-8")


def sha256_hex(payload: bytes) -> str:
    """SHA-256 of exact bytes, as lowercase hex with no prefix."""
    return hashlib.sha256(payload).hexdigest()


def content_hash(value: object) -> str:
    """Prefixed SHA-256 over the canonical rendering of ``value``."""
    return SHA256_PREFIX + sha256_hex(canonical_bytes(value))


__all__ = [
    "SHA256_PREFIX",
    "canonical_bytes",
    "canonical_json",
    "canonical_value",
    "content_hash",
    "sha256_hex",
]
