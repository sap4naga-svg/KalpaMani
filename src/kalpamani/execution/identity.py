"""Deterministic order identity (ADR-0004).

Identity is **derived, never generated**. There is no ``uuid4()`` here, no
timestamp, and no in-memory counter. Every identifier is a pure function of
durable inputs, which is what lets a restarted process recompute byte-identical
identifiers and recognise its own prior orders at the broker instead of issuing
new ones.

    trade_intent_id  -- one decision to establish one position
    execution_id     -- one attempt to realise that intent through a broker
    client_order_id  -- one order sent to the broker

The broker's own order id is deliberately absent: per ADR-0002 §4 it is recorded
for reconciliation and audit, never derived from and never branched on.

The ``attempt`` component of an execution id increments **only** on an explicit
new human authorization. A restart, reconnect, crash or redeploy must never
increment it -- that single rule is what makes *restart != replay intent* true.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum

from kalpamani.common.errors import KalpaManiError

#: Bumped only if an id derivation rule changes. Mixed into every hash so that a
#: rule change produces visibly different ids rather than silent collisions with
#: ids minted under the old rule.
ID_SCHEME_VERSION = "v1"

_INTENT_PREFIX = "ti"
_EXECUTION_PREFIX = "ex"
_ORDER_PREFIX = "km"

_INTENT_DIGEST_LEN = 16
_EXECUTION_DIGEST_LEN = 16
_ORDER_DIGEST_LEN = 8

#: Client order ids travel to the broker as the LEAN order tag. Keep them short,
#: greppable and free of characters a broker might mangle.
CLIENT_ORDER_ID_PATTERN = re.compile(r"^km-[0-9a-f]{8}-(ENTRY|PROTECTIVE|EXIT)-\d+$")


class OrderIdentityError(KalpaManiError):
    """An identifier was requested with inputs that cannot produce a valid id."""


class OrderRole(StrEnum):
    """The closed set of roles an order may play in a trade lifecycle.

    There is deliberately no "adjust", "scale" or "average" role. Pyramiding and
    averaging down are out of scope for V1 (Blueprint V2.1 §10), and a role that
    does not exist cannot be requested by mistake.
    """

    #: Establishes the position. At most ONE per execution.
    ENTRY = "ENTRY"
    #: Protects filled quantity. Sized from actual fills only, never requested size.
    PROTECTIVE = "PROTECTIVE"
    #: Closes remaining quantity.
    EXIT = "EXIT"


def _digest(*parts: str, length: int) -> str:
    payload = "|".join((ID_SCHEME_VERSION, *parts))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def trade_intent_id(natural_key: str) -> str:
    """Derive the permanent identity of one decision to establish one position.

    Args:
        natural_key: A stable, human-meaningful description of the intent, e.g.
            ``"phase2-certification/SPY/long/1"``. The same key must always mean
            the same intent -- that is the whole basis of idempotency.

    Raises:
        OrderIdentityError: if the key is empty or whitespace-only. An intent
            with no identity would be indistinguishable from every other, which
            would defeat duplicate detection entirely.
    """
    key = natural_key.strip()
    if not key:
        raise OrderIdentityError(
            "trade_intent_id requires a non-empty natural key. An intent without a stable "
            "key cannot be recognised after a restart, which is exactly when it matters."
        )
    return f"{_INTENT_PREFIX}-{_digest('intent', key, length=_INTENT_DIGEST_LEN)}"


def execution_id(intent_id: str, attempt: int) -> str:
    """Derive the identity of one attempt to realise ``intent_id`` at a broker.

    Args:
        intent_id: A ``trade_intent_id``.
        attempt: 1-based attempt number. Incremented **only** by an explicit new
            human authorization -- never by a restart, reconnect or crash.

    Raises:
        OrderIdentityError: if the attempt is below 1.
    """
    if attempt < 1:
        raise OrderIdentityError(f"attempt must be >= 1, got {attempt}.")
    digest = _digest("exec", intent_id, str(attempt), length=_EXECUTION_DIGEST_LEN)
    return f"{_EXECUTION_PREFIX}-{digest}"


def client_order_id(exec_id: str, role: OrderRole, ordinal: int = 0) -> str:
    """Derive the identity of one order, carried to the broker as the order tag.

    Args:
        exec_id: An ``execution_id``.
        role: Which role the order plays.
        ordinal: Distinguishes multiple orders in the same role. ``ENTRY`` admits
            only ordinal 0 -- see below.

    Raises:
        OrderIdentityError: if ``ordinal`` is negative, or if a second ``ENTRY``
            is requested. One execution establishes one position; a second entry
            is not a larger position, it is a duplicate. Refusing it here means
            the caller cannot even name the order it would need to send.
    """
    if ordinal < 0:
        raise OrderIdentityError(f"ordinal must be >= 0, got {ordinal}.")
    if role is OrderRole.ENTRY and ordinal != 0:
        raise OrderIdentityError(
            f"Refusing to derive a second ENTRY order id (ordinal={ordinal}) for execution "
            f"{exec_id}. One execution establishes one position. A second entry is a "
            "duplicate, not an addition."
        )
    digest = _digest("order", exec_id, role.value, str(ordinal), length=_ORDER_DIGEST_LEN)
    return f"{_ORDER_PREFIX}-{digest}-{role.value}-{ordinal}"


def is_valid_client_order_id(candidate: str) -> bool:
    """Whether ``candidate`` has the shape this module produces.

    Used when adopting orders discovered at the broker: an order whose tag does
    not match was not created by KalpaMani, and must never be treated as ours.
    """
    return bool(CLIENT_ORDER_ID_PATTERN.fullmatch(candidate))


def role_of_client_order_id(candidate: str) -> OrderRole:
    """Extract the role encoded in a client order id.

    Raises:
        OrderIdentityError: if ``candidate`` is not a KalpaMani client order id.
    """
    match = CLIENT_ORDER_ID_PATTERN.fullmatch(candidate)
    if match is None:
        raise OrderIdentityError(
            f"{candidate!r} is not a KalpaMani client order id. Orders that do not match "
            "the KalpaMani id scheme belong to someone else and must not be adopted."
        )
    return OrderRole(match.group(1))


@dataclass(frozen=True, slots=True)
class TradeIdentity:
    """The full derived identity set for one execution attempt.

    Immutable and fully reconstructible from ``(natural_key, attempt)``, which is
    the property recovery depends on.
    """

    natural_key: str
    attempt: int
    trade_intent_id: str
    execution_id: str

    @classmethod
    def derive(cls, natural_key: str, attempt: int = 1) -> TradeIdentity:
        """Derive a complete identity set from its two durable inputs."""
        intent = trade_intent_id(natural_key)
        return cls(
            natural_key=natural_key.strip(),
            attempt=attempt,
            trade_intent_id=intent,
            execution_id=execution_id(intent, attempt),
        )

    @property
    def entry_order_id(self) -> str:
        """The one and only entry order id for this execution."""
        return client_order_id(self.execution_id, OrderRole.ENTRY)

    @property
    def protective_order_id(self) -> str:
        return client_order_id(self.execution_id, OrderRole.PROTECTIVE)

    @property
    def exit_order_id(self) -> str:
        return client_order_id(self.execution_id, OrderRole.EXIT)

    def order_id_for(self, role: OrderRole, ordinal: int = 0) -> str:
        return client_order_id(self.execution_id, role, ordinal)

    def owns(self, candidate_client_order_id: str) -> bool:
        """Whether an order id observed at the broker belongs to this execution."""
        return candidate_client_order_id in {
            self.entry_order_id,
            self.protective_order_id,
            self.exit_order_id,
        }

    def describe(self) -> str:
        """Log-safe summary. Contains no account identifier and no secret."""
        return (
            f"intent={self.trade_intent_id} execution={self.execution_id} "
            f"attempt={self.attempt} entry={self.entry_order_id}"
        )


__all__ = [
    "CLIENT_ORDER_ID_PATTERN",
    "ID_SCHEME_VERSION",
    "OrderIdentityError",
    "OrderRole",
    "TradeIdentity",
    "client_order_id",
    "execution_id",
    "is_valid_client_order_id",
    "role_of_client_order_id",
    "trade_intent_id",
]
