"""Order-capable brokerage boundary (ADR-0004).

Phase 1 exposed a read-only Protocol that was literally incapable of expressing
an order. Phase 2 widens that boundary by the minimum required for
certification: submit, cancel, and observe.

The widening is deliberate and ADR-gated. Everything here stays broker-agnostic:
IBKR-specific behaviour lives behind the adapter, and strategy code never
reaches this module (ADR-0002 s.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from kalpamani.common.errors import SafetyViolationError
from kalpamani.execution.identity import OrderRole, is_valid_client_order_id


class OrderRequestError(SafetyViolationError):
    """A proposed order is malformed and must never reach a broker."""


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    #: Simple immediate execution, suitable for liquid-hours certification.
    MARKET = "MARKET"
    #: Protective stop. Phase 2 uses this for the SELL stop only.
    STOP_MARKET = "STOP_MARKET"


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """An immutable, validated instruction to place one order.

    Carries its deterministic ``client_order_id``, which travels to the broker as
    the order tag so the order remains attributable across restarts.
    """

    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType
    role: OrderRole
    stop_price: Decimal | None = None

    def __post_init__(self) -> None:
        if not is_valid_client_order_id(self.client_order_id):
            raise OrderRequestError(
                f"{self.client_order_id!r} is not a deterministic KalpaMani client order id. "
                "Untagged orders cannot be recognised after a restart, which is exactly when "
                "duplicate prevention matters."
            )
        if self.quantity <= 0:
            raise OrderRequestError(
                f"Order quantity must be positive, got {self.quantity}. Side is expressed by "
                "OrderSide, never by a negative quantity."
            )
        if self.order_type is OrderType.STOP_MARKET and self.stop_price is None:
            raise OrderRequestError("A STOP_MARKET order requires a stop price.")
        if self.order_type is OrderType.MARKET and self.stop_price is not None:
            raise OrderRequestError("A MARKET order must not carry a stop price.")
        if self.stop_price is not None and self.stop_price <= 0:
            raise OrderRequestError(f"Stop price must be positive, got {self.stop_price}.")

    @property
    def signed_quantity(self) -> int:
        """Quantity signed for engines that express side by sign."""
        return self.quantity if self.side is OrderSide.BUY else -self.quantity

    def describe(self) -> str:
        """Log-safe summary. No account identifier, no secret."""
        stop = f" stop={self.stop_price}" if self.stop_price is not None else ""
        return (
            f"{self.side.value} {self.quantity} {self.symbol} "
            f"type={self.order_type.value} role={self.role.value} "
            f"id={self.client_order_id}{stop}"
        )


@dataclass(frozen=True, slots=True)
class OrderAcknowledgement:
    """The broker's acknowledgement that it accepted an order."""

    client_order_id: str
    broker_order_id: str
    accepted: bool
    message: str = ""


@dataclass(frozen=True, slots=True)
class FillEvent:
    """One fill, identified so repeated delivery is a no-op.

    ``fill_id`` is the broker's identity for this fill. It is what makes fill
    handling idempotent: the same fill applied twice changes nothing.
    """

    fill_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    price: Decimal

    def describe(self) -> str:
        return (
            f"fill={self.fill_id} order={self.client_order_id} "
            f"{self.side.value} {self.quantity} {self.symbol} @ {self.price}"
        )


@runtime_checkable
class OrderCapableBroker(Protocol):
    """The minimum order capability Phase 2 requires.

    Deliberately small. There is no `liquidate`, no `close_all`, and no
    `modify_order`: broad account-wide actions are forbidden by ADR-0004 s.9
    because they act on positions KalpaMani does not own.
    """

    def submit_order(self, request: OrderRequest) -> OrderAcknowledgement:
        """Submit one order. Must be safe to call only once per client_order_id."""
        ...

    def cancel_order(self, client_order_id: str) -> bool:
        """Request cancellation. Returns whether the broker accepted the request."""
        ...


__all__ = [
    "FillEvent",
    "OrderAcknowledgement",
    "OrderCapableBroker",
    "OrderRequest",
    "OrderRequestError",
    "OrderSide",
    "OrderType",
]
