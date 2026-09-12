"""Strict decoding and field grammars shared by the production contracts.

Every production document -- input, release, locator -- is a closed JSON object
delivered as bytes with a size ceiling. The rules below are the ones the accepted
private-binding loader applies, spelled once: the ceiling is checked **before**
decoding, a byte-order mark is refused, UTF-8 is strict, a duplicate key is refused
rather than resolved, and only an object is admitted. Field grammars follow the
same pattern as the qualification locator: an exact ``str``, an exact ``int``, a
64-hex digest, an aware ISO-8601 instant.

Each contract module maps :class:`DocumentDefect` onto its own closed vocabulary
explicitly and totally, so a decoding defect surfaces in the vocabulary a caller
already handles rather than as a second exception type.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Final


class DocumentDefect(StrEnum):
    """Why bytes were not a usable closed document. Structural; carries no value."""

    EMPTY = "EMPTY"
    TOO_LARGE = "TOO_LARGE"
    ENCODING_INVALID = "ENCODING_INVALID"
    DOCUMENT_MALFORMED = "DOCUMENT_MALFORMED"
    DUPLICATE_KEY = "DUPLICATE_KEY"


class DocumentError(Exception):
    """A refusal carrying exactly one :class:`DocumentDefect`, raised ``from None``."""

    __slots__ = ("defect",)

    def __init__(self, defect: DocumentDefect) -> None:
        """Bind the defect. The message is the member's token, nothing more."""
        if type(defect) is not DocumentDefect:  # pragma: no cover - type guard
            raise TypeError("a defect must be an exact DocumentDefect member")
        super().__init__(defect.value)
        self.defect = defect


def _refuse(defect: DocumentDefect) -> DocumentError:
    return DocumentError(defect)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _refuse(DocumentDefect.DUPLICATE_KEY) from None
        seen[key] = value
    return seen


def decode_document(raw: object, *, max_bytes: int) -> dict[str, Any]:
    """One closed JSON object from delivered bytes, or a refusal. **Reads nothing.**

    Raises:
        DocumentError: ``EMPTY``, ``TOO_LARGE`` (checked before decoding),
            ``ENCODING_INVALID``, ``DUPLICATE_KEY`` or ``DOCUMENT_MALFORMED`` --
            the last also for a non-``bytes`` value and for a JSON value that is
            not an object.
    """
    if type(raw) is not bytes:
        raise _refuse(DocumentDefect.DOCUMENT_MALFORMED) from None
    if not raw:
        raise _refuse(DocumentDefect.EMPTY) from None
    if len(raw) > max_bytes:
        raise _refuse(DocumentDefect.TOO_LARGE) from None
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _refuse(DocumentDefect.ENCODING_INVALID) from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse(DocumentDefect.ENCODING_INVALID) from None
    try:
        document = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except DocumentError:
        raise
    except Exception:
        raise _refuse(DocumentDefect.DOCUMENT_MALFORMED) from None
    if type(document) is not dict:
        raise _refuse(DocumentDefect.DOCUMENT_MALFORMED) from None
    return document


#: Grammars shared by the contracts. Each returns the value or ``None``; the
#: caller raises its own vocabulary member, so no grammar names a defect.
_HEX64: Final = re.compile(r"[0-9a-f]{64}")


def exact_str(value: object) -> str | None:
    """``value`` if it is a non-empty exact ``str``, else ``None``."""
    return value if type(value) is str and value else None


def exact_int(value: object) -> int | None:
    """``value`` if it is a non-negative exact ``int`` (``bool`` refused), else ``None``."""
    return value if type(value) is int and value >= 0 else None


def hex_digest(value: object) -> str | None:
    """``value`` if it is a 64-character lowercase hex digest, else ``None``."""
    return value if type(value) is str and _HEX64.fullmatch(value) else None


def instant(value: object) -> datetime | None:
    """``value`` parsed as an aware ISO-8601 instant, else ``None``."""
    if type(value) is not str or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


__all__ = [
    "DocumentDefect",
    "DocumentError",
    "decode_document",
    "exact_int",
    "exact_str",
    "hex_digest",
    "instant",
]
