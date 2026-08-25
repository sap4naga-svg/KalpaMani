"""Broker-vs-internal reconciliation and safe exit planning (ADR-0004 §8, §9).

LEAN events do not establish broker truth; explicit reconciliation does. This
module compares what KalpaMani believes against what the broker reports, and
fails closed whenever they disagree.

It also owns the exit ordering rule, which exists to prevent a specific and
nasty outcome: if a protective SELL stop is still working after the long is
closed, it can fill on its own and open an **unintended short position**. So
protection is cancelled and confirmed cancelled *before* the closing order is
sent -- ordering, not tidiness.
"""

from __future__ import annotations

from dataclasses import dataclass

from kalpamani.common.errors import SafetyViolationError
from kalpamani.execution.identity import OrderRole, TradeIdentity, is_valid_client_order_id
from kalpamani.execution.state_store import TradeRecord


class ReconciliationError(SafetyViolationError):
    """Internal state and broker state disagree; no action may proceed."""


class UnprotectedPositionError(SafetyViolationError):
    """A filled position exists without confirmed protection.

    The highest-severity Phase 2 condition. It never triggers another entry --
    the response is to surface it and stop normal progression.
    """


@dataclass(frozen=True, slots=True)
class BrokerOrderView:
    """One open order as the broker reports it."""

    client_order_id: str
    symbol: str
    side: str
    quantity: int
    is_open: bool


@dataclass(frozen=True, slots=True)
class BrokerPositionView:
    """One position as the broker reports it."""

    symbol: str
    quantity: int


@dataclass(frozen=True, slots=True)
class BrokerView:
    """A snapshot of broker truth relevant to one trade intent."""

    positions: tuple[BrokerPositionView, ...] = ()
    open_orders: tuple[BrokerOrderView, ...] = ()

    def position_quantity(self, symbol: str) -> int:
        return sum(p.quantity for p in self.positions if p.symbol == symbol)

    def orders_owned_by(self, identity: TradeIdentity) -> tuple[BrokerOrderView, ...]:
        """Open orders attributable to this execution.

        Orders whose tag is not a KalpaMani client order id, or belongs to a
        different execution, are somebody else's. They are never adopted and
        never modified (ADR-0002: we do not touch what we do not own).
        """
        return tuple(
            o
            for o in self.open_orders
            if is_valid_client_order_id(o.client_order_id) and identity.owns(o.client_order_id)
        )

    def open_protective_quantity(self, identity: TradeIdentity) -> int:
        return sum(
            o.quantity
            for o in self.orders_owned_by(identity)
            if o.client_order_id == identity.protective_order_id and o.is_open
        )

    def open_entry_count(self, identity: TradeIdentity) -> int:
        return sum(
            1
            for o in self.orders_owned_by(identity)
            if o.client_order_id == identity.entry_order_id and o.is_open
        )


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Outcome of comparing internal state against broker truth."""

    internal_filled_quantity: int
    broker_position_quantity: int
    internal_protected_quantity: int
    broker_protective_quantity: int
    matches: bool

    def describe(self) -> str:
        return (
            f"internal_filled={self.internal_filled_quantity} "
            f"broker_position={self.broker_position_quantity} "
            f"internal_protected={self.internal_protected_quantity} "
            f"broker_protective={self.broker_protective_quantity} "
            f"matches={self.matches}"
        )


def reconcile(
    record: TradeRecord,
    identity: TradeIdentity,
    broker: BrokerView,
) -> ReconciliationResult:
    """Compare internal state to broker truth, failing closed on disagreement.

    Raises:
        ReconciliationError: if filled quantity or protective quantity disagree.
            We do not reconcile optimistically toward either side -- a mismatch
            means this process does not understand the position, and acting on a
            position you do not understand is how duplicates and naked exposure
            happen.
    """
    broker_position = broker.position_quantity(record.symbol)
    broker_protective = broker.open_protective_quantity(identity)

    result = ReconciliationResult(
        internal_filled_quantity=record.open_long_quantity,
        broker_position_quantity=broker_position,
        internal_protected_quantity=record.protected_quantity,
        broker_protective_quantity=broker_protective,
        matches=(
            record.open_long_quantity == broker_position
            and record.protected_quantity == broker_protective
        ),
    )
    if not result.matches:
        raise ReconciliationError(
            "Internal state and broker state disagree: " + result.describe() + ". Failing "
            "closed. A human must resolve the discrepancy before any further order activity."
        )
    return result


def assert_protected(
    record: TradeRecord,
    identity: TradeIdentity,
    broker: BrokerView,
) -> None:
    """Assert the filled long quantity is fully protected at the broker.

    A position counts as protected only when the broker confirms a working SELL
    order of the right quantity, attributable to this execution.

    Raises:
        UnprotectedPositionError: if a filled position lacks matching protection.
    """
    long_quantity = record.open_long_quantity
    if long_quantity <= 0:
        return

    owned = [
        o
        for o in broker.orders_owned_by(identity)
        if o.client_order_id == identity.protective_order_id and o.is_open
    ]
    protective_quantity = sum(o.quantity for o in owned)
    wrong_side = [o for o in owned if o.side.upper() != "SELL"]
    wrong_symbol = [o for o in owned if o.symbol != record.symbol]

    if not owned or protective_quantity != long_quantity or wrong_side or wrong_symbol:
        raise UnprotectedPositionError(
            f"UNPROTECTED POSITION: {record.symbol} long {long_quantity} with protective "
            f"quantity {protective_quantity} "
            f"(orders={len(owned)}, wrong_side={len(wrong_side)}, "
            f"wrong_symbol={len(wrong_symbol)}). "
            "Highest-severity Phase 2 failure. Do NOT submit another entry; surface this "
            "and stop normal progression."
        )


def required_protection_quantity(record: TradeRecord) -> int:
    """How much protection the ACTUAL fills require -- never requested quantity.

    Zero filled means zero protection. Fabricating a stop for a position that
    does not exist would itself be capable of opening a short.
    """
    entry = record.order_for_role(OrderRole.ENTRY)
    return entry.filled_quantity if entry else 0


@dataclass(frozen=True, slots=True)
class ExitPlan:
    """A validated, ordered exit sequence."""

    cancel_client_order_id: str | None
    exit_client_order_id: str
    exit_quantity: int
    symbol: str

    def describe(self) -> str:
        cancel = self.cancel_client_order_id or "(none)"
        return (
            f"cancel_first={cancel} then_sell={self.exit_quantity} {self.symbol} "
            f"as={self.exit_client_order_id}"
        )


def plan_exit(
    record: TradeRecord,
    identity: TradeIdentity,
    broker: BrokerView,
) -> ExitPlan:
    """Build a safe exit plan for the Phase 2 position.

    Raises:
        ReconciliationError: if there is nothing to close, or if broker and
            internal views of the position disagree.
    """
    broker_position = broker.position_quantity(record.symbol)
    internal_long = record.open_long_quantity

    if internal_long != broker_position:
        raise ReconciliationError(
            f"Cannot plan an exit while internal long ({internal_long}) and broker position "
            f"({broker_position}) disagree for {record.symbol}."
        )
    if internal_long <= 0:
        raise ReconciliationError(
            f"No long position to close for {record.symbol} (internal={internal_long}). "
            "Refusing to send a SELL that would open a short."
        )

    protective_open = broker.open_protective_quantity(identity) > 0
    return ExitPlan(
        cancel_client_order_id=identity.protective_order_id if protective_open else None,
        exit_client_order_id=identity.exit_order_id,
        exit_quantity=internal_long,
        symbol=record.symbol,
    )


def assert_safe_to_close(
    plan: ExitPlan,
    identity: TradeIdentity,
    broker_after_cancel: BrokerView,
) -> None:
    """Assert protection is genuinely gone before the closing SELL is sent.

    Raises:
        ReconciliationError: if a protective order is still working. Sending the
            close now could leave the stop live; once the long is flat that stop
            can fill and open an unintended short.
    """
    remaining = broker_after_cancel.open_protective_quantity(identity)
    if remaining > 0:
        raise ReconciliationError(
            f"Protective order still working ({remaining} units) after cancellation was "
            "requested. Refusing to submit the closing SELL: a stop left live after the long "
            "is closed can fill and open an unintended SHORT position."
        )
    if plan.exit_quantity > broker_after_cancel.position_quantity(plan.symbol):
        raise ReconciliationError(
            f"Exit quantity {plan.exit_quantity} exceeds the broker position "
            f"{broker_after_cancel.position_quantity(plan.symbol)} for {plan.symbol}. "
            "Selling more than is held would open a short."
        )


def assert_flat(
    record: TradeRecord,
    identity: TradeIdentity,
    broker: BrokerView,
) -> None:
    """Assert the final Phase 2 acceptance state: nothing left anywhere.

    Raises:
        ReconciliationError: if any position or working order remains, including
            an accidental short.
    """
    position = broker.position_quantity(record.symbol)
    owned_open = [o for o in broker.orders_owned_by(identity) if o.is_open]

    problems: list[str] = []
    if position > 0:
        problems.append(f"residual long position {position}")
    if position < 0:
        problems.append(f"ACCIDENTAL SHORT position {position}")
    if owned_open:
        ids = ", ".join(o.client_order_id for o in owned_open)
        problems.append(f"open KalpaMani orders: {ids}")

    if problems:
        raise ReconciliationError(
            f"Phase 2 is not flat for {record.symbol}: " + "; ".join(problems) + "."
        )


__all__ = [
    "BrokerOrderView",
    "BrokerPositionView",
    "BrokerView",
    "ExitPlan",
    "ReconciliationError",
    "ReconciliationResult",
    "UnprotectedPositionError",
    "assert_flat",
    "assert_protected",
    "assert_safe_to_close",
    "plan_exit",
    "reconcile",
    "required_protection_quantity",
]
