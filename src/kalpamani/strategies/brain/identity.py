"""Identifiers, instants and numbers as the Brain admits them.

Every string a Brain record carries is an **identifier**: a version, a
reference, a hash, a security id. None is prose. The grammar below admits no
whitespace, so a sentence -- and therefore an instruction -- has no field to
arrive through. That is how "no free-text field an instruction could arrive
through" (specification section 6.2) becomes a property of the type.

Candidate identity follows ADR-0004's rule for order identity: **derived,
never generated**. There is no ``uuid4()``, no clock and no counter. A
candidate id is a pure function of the durable inputs that define the
decision, so a replay from the same recorded inputs produces the same id.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from decimal import Decimal
from typing import Final

from kalpamani.data.contracts.instants import normalize_instant
from kalpamani.strategies.brain.errors import BrainContractError

#: One identifier grammar for every string field. No whitespace, no quotes, no
#: control characters; a bounded length so a field cannot become a document.
IDENTIFIER_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,199}$")

#: Bumped only if the derivation rule changes, so a rule change produces visibly
#: different ids rather than silent collisions with ids minted under the old one.
CANDIDATE_ID_SCHEME_VERSION: Final = "v1"
_CANDIDATE_PREFIX: Final = "ci"
_CANDIDATE_DIGEST_LEN: Final = 16

CANDIDATE_ID_PATTERN: Final = re.compile(r"^ci-[0-9a-f]{16}$")


def require_identifier(value: object, *, field: str) -> str:
    """``value`` if it is an identifier under the grammar; a refusal otherwise.

    Raises:
        BrainContractError: if ``value`` is not a ``str`` or does not match
            :data:`IDENTIFIER_PATTERN`. The offending value is **not** quoted in
            the message: a value refused for being free text is exactly the
            value that must not be copied into an error.
    """
    if type(value) is not str or IDENTIFIER_PATTERN.match(value) is None:
        raise BrainContractError(
            f"Field {field!r} must be an identifier: non-empty, no whitespace, at most 200 "
            "characters from [A-Za-z0-9._:/+-]. Prose has no field to arrive through."
        )
    return value


def require_optional_identifier(value: object, *, field: str) -> str | None:
    """:func:`require_identifier`, passing ``None`` through unchanged."""
    return None if value is None else require_identifier(value, field=field)


def require_instant(value: object, *, field: str) -> datetime:
    """``value`` as a canonical UTC instant, or a refusal.

    Raises:
        BrainContractError: if ``value`` is not an aware datetime. The kernel's
            rule is inherited rather than restated: a naive instant is a
            look-ahead of up to a day, and there is no default zone.
    """
    if not isinstance(value, datetime):
        raise BrainContractError(f"Field {field!r} must be a timezone-aware datetime.")
    try:
        return normalize_instant(value)
    except TypeError as refusal:
        raise BrainContractError(f"Field {field!r}: {refusal}") from None


def require_finite_decimal(value: object, *, field: str) -> Decimal:
    """``value`` if it is a finite :class:`Decimal`, or a refusal.

    A ``float`` is refused as well as ``NaN`` and the infinities: a float in a
    hashed record makes identity a property of a binary representation, and
    the kernel's canonical serialiser refuses it for the same reason.
    """
    if type(value) is not Decimal or not value.is_finite():
        raise BrainContractError(f"Field {field!r} must be a finite Decimal.")
    return value


def require_unit_interval(value: object, *, field: str) -> Decimal:
    """A finite Decimal in ``[0, 1]``."""
    decimal = require_finite_decimal(value, field=field)
    if decimal < 0 or decimal > 1:
        raise BrainContractError(f"Field {field!r} must lie in [0, 1].")
    return decimal


def require_non_negative_int(value: object, *, field: str) -> int:
    """A non-negative ``int`` that is not a ``bool``."""
    if type(value) is not int or value < 0:
        raise BrainContractError(f"Field {field!r} must be a non-negative integer.")
    return value


def require_positive_int(value: object, *, field: str) -> int:
    """A strictly positive ``int`` that is not a ``bool``."""
    if type(value) is not int or value < 1:
        raise BrainContractError(f"Field {field!r} must be a positive integer.")
    return value


def candidate_id(
    *,
    security_id: str,
    direction: str,
    strategy_id: str,
    strategy_version: str,
    as_of_time: datetime,
    environment: str,
    evidence_reference: str,
) -> str:
    """Derive the identity of one Brain decision.

    The natural key is the security, the direction, the strategy version, the
    decision instant, the environment and a reference to the exact evidence
    lineage the decision read. Two evaluations of the same security at the same
    instant under the same version over the same evidence are the same decision
    and get the same id; change any of those and the id changes.
    """
    parts = (
        CANDIDATE_ID_SCHEME_VERSION,
        require_identifier(security_id, field="security_id"),
        require_identifier(direction, field="direction"),
        require_identifier(strategy_id, field="strategy_id"),
        require_identifier(strategy_version, field="strategy_version"),
        require_instant(as_of_time, field="as_of_time").isoformat(timespec="microseconds"),
        require_identifier(environment, field="environment"),
        require_identifier(evidence_reference, field="evidence_reference"),
    )
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"{_CANDIDATE_PREFIX}-{digest[:_CANDIDATE_DIGEST_LEN]}"


__all__ = [
    "CANDIDATE_ID_PATTERN",
    "CANDIDATE_ID_SCHEME_VERSION",
    "IDENTIFIER_PATTERN",
    "candidate_id",
    "require_finite_decimal",
    "require_identifier",
    "require_instant",
    "require_non_negative_int",
    "require_optional_identifier",
    "require_positive_int",
    "require_unit_interval",
]
