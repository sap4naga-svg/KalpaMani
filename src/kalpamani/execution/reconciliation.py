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

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from kalpamani.common.errors import SafetyViolationError
from kalpamani.execution.identity import OrderRole, TradeIdentity, is_valid_client_order_id
from kalpamani.execution.state_store import SubmittedOrder, TradeRecord


class ReconciliationError(SafetyViolationError):
    """Internal state and broker state disagree; no action may proceed."""


class UnprotectedPositionError(SafetyViolationError):
    """A filled position exists without confirmed protection.

    The highest-severity Phase 2 condition. It never triggers another entry --
    the response is to surface it and stop normal progression.
    """


class OwnershipBasis(StrEnum):
    """How an open order was identified as ours -- or not."""

    #: The LEAN tag carried our client order id. Only possible in the process
    #: that submitted the order.
    TAG = "TAG"
    #: The broker-native id matched a durable record. Survives a restart.
    BROKER_ID = "BROKER_ID"
    #: Not ours, or not provably ours. Never adopted, never modified.
    NONE = "NONE"


class OwnershipError(SafetyViolationError):
    """An open order cannot be attributed safely: ambiguous or contradictory."""


def normalise_order_type(raw: str) -> str:
    """Fold ``StopMarket`` / ``STOP_MARKET`` / ``stop_market`` to one token."""
    return "".join(ch for ch in raw.upper() if ch.isalnum())


#: The order type each role must have, normalised.
EXPECTED_ORDER_TYPE: dict[OrderRole, str] = {
    OrderRole.ENTRY: "MARKET",
    OrderRole.PROTECTIVE: "STOPMARKET",
    OrderRole.EXIT: "MARKET",
}


@dataclass(frozen=True, slots=True)
class BrokerOrderView:
    """One open order as the broker reports it, plus how we identified it."""

    #: Resolved KalpaMani identity, or a redacted ``<foreign-N>`` placeholder.
    #: Set by :func:`resolve_broker_view`, not by the adapter.
    client_order_id: str
    symbol: str
    side: str
    quantity: int
    is_open: bool
    #: Raw LEAN tag. BLANK on an order LEAN re-hydrated after a restart: the tag
    #: is never sent to IBKR, so it cannot come back.
    tag: str = ""
    #: Broker-native ids (``Order.BrokerId``). The only identity proven to
    #: survive a restart. Never printed in normal logs.
    broker_order_ids: tuple[str, ...] = ()
    #: LEAN's process-local order id. Used ONLY to address a cancellation within
    #: the current process, and never as durable identity -- it is reassigned on
    #: restart, which was observed directly.
    lean_order_id: str = ""
    order_type: str = ""
    stop_price: str | None = None
    ownership: OwnershipBasis = OwnershipBasis.NONE


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

        Reads the resolution :func:`resolve_broker_view` already performed. An
        order that could not be attributed carries a ``<foreign-N>`` placeholder
        and is excluded: never adopted, never modified (ADR-0002 -- we do not
        touch what we do not own).
        """
        return tuple(
            o
            for o in self.open_orders
            if o.ownership is not OwnershipBasis.NONE
            and is_valid_client_order_id(o.client_order_id)
            and identity.owns(o.client_order_id)
        )

    def owned_order(self, client_order_id: str) -> BrokerOrderView | None:
        """The single resolved view for one of our orders, or None.

        Raises:
            OwnershipError: if more than one open order resolved to the same
                client order id. Two live orders claiming one identity is not a
                state to cancel or close from.
        """
        matches = [
            o
            for o in self.open_orders
            if o.ownership is not OwnershipBasis.NONE and o.client_order_id == client_order_id
        ]
        if len(matches) > 1:
            raise OwnershipError(
                f"{len(matches)} open orders resolve to {client_order_id}. Ambiguous ownership; "
                "refusing to act on either."
            )
        return matches[0] if matches else None

    def open_protective_quantity(self, identity: TradeIdentity) -> int:
        return sum(
            o.quantity
            for o in self.orders_owned_by(identity)
            if o.client_order_id == identity.protective_order_id and o.is_open
        )

    def open_order_count_for_symbol(self, symbol: str) -> int:
        """Count EVERY working order on this symbol, whoever created it.

        Deliberately not filtered to KalpaMani orders. A foreign working order on
        the same symbol makes position ownership ambiguous, and ambiguity is what
        the pre-arm gate exists to refuse.
        """
        return sum(1 for o in self.open_orders if o.symbol == symbol and o.is_open)

    def foreign_open_order_count_for_symbol(self, symbol: str, identity: TradeIdentity) -> int:
        """Working orders on this symbol that KalpaMani did not create."""
        owned = {o.client_order_id for o in self.orders_owned_by(identity)}
        return sum(
            1
            for o in self.open_orders
            if o.symbol == symbol and o.is_open and o.client_order_id not in owned
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


def _assert_attributes_agree(view: BrokerOrderView, durable: SubmittedOrder) -> None:
    """Attributes VALIDATE an identity; they never create one.

    Reached only after a tag or a broker id has already established which order
    this is. A disagreement here means the identity we established and the order
    the broker is describing are not the same thing, which is a contradiction
    rather than a near-miss.

    Raises:
        OwnershipError: on any disagreement.
    """
    problems: list[str] = []
    if view.symbol != durable.symbol:
        problems.append(f"symbol {view.symbol} != {durable.symbol}")
    if view.side.strip().upper() != durable.side.strip().upper():
        problems.append(f"side {view.side} != {durable.side}")
    if view.quantity != durable.quantity:
        problems.append(f"quantity {view.quantity} != {durable.quantity}")
    if view.order_type:
        expected = EXPECTED_ORDER_TYPE.get(durable.role, "")
        if expected and normalise_order_type(view.order_type) != expected:
            problems.append(
                f"order type {view.order_type} is not {expected} for {durable.role.value}"
            )
    if durable.role is OrderRole.PROTECTIVE and view.stop_price and durable.stop_price:
        if Decimal(view.stop_price) != Decimal(durable.stop_price):
            problems.append(f"stop price {view.stop_price} != {durable.stop_price}")
    if problems:
        raise OwnershipError(
            f"An open order was identified as {durable.client_order_id} "
            f"({durable.role.value}) but its attributes contradict that record: "
            + "; ".join(problems)
            + ". Refusing to adopt it."
        )


def resolve_ownership(
    view: BrokerOrderView,
    record: TradeRecord | None,
    identity: TradeIdentity,
) -> tuple[str | None, OwnershipBasis]:
    """Attribute one open order, by evidence and never by resemblance.

    The hierarchy, strongest first:

    1. **TAG.** The LEAN tag carries our client order id. Only available in the
       process that submitted the order -- the tag is not sent to IBKR.
    2. **BROKER ID.** The broker-native id matches exactly one durable order.
       This is what survives a restart, proven on a real IBKR Paper reconnect.
    3. **Attributes** then VALIDATE whichever identity was established. They are
       never allowed to establish one: a manual SELL stop for 1 SPY at the same
       price is indistinguishable by shape, and adopting it would let KalpaMani
       cancel a stranger's order or believe a stranger's order protects it.
    4. Otherwise the order is FOREIGN. Never adopted, never cancelled, never
       answered with a compensating order.

    Raises:
        OwnershipError: if a broker id matches more than one durable order, or
            if attributes contradict the established identity.
    """
    if record is None:
        return None, OwnershipBasis.NONE

    tag = view.tag.strip()
    if is_valid_client_order_id(tag) and identity.owns(tag) and tag in record.orders:
        _assert_attributes_agree(view, record.orders[tag])
        return tag, OwnershipBasis.TAG

    if view.broker_order_ids:
        incoming = set(view.broker_order_ids)
        matches = [
            durable
            for durable in record.orders.values()
            if durable.broker_order_ids and incoming & set(durable.broker_order_ids)
        ]
        if len(matches) > 1:
            raise OwnershipError(
                f"A broker order id matches {len(matches)} durable KalpaMani orders "
                f"({', '.join(sorted(m.client_order_id for m in matches))}). Ambiguous "
                "identity; refusing to attribute it to any of them."
            )
        if matches:
            durable = matches[0]
            if is_valid_client_order_id(tag) and tag != durable.client_order_id:
                raise OwnershipError(
                    f"An open order carries the tag {tag} but its broker id belongs to "
                    f"{durable.client_order_id}. The two identities contradict each other; "
                    "refusing to adopt it."
                )
            _assert_attributes_agree(view, durable)
            return durable.client_order_id, OwnershipBasis.BROKER_ID

    return None, OwnershipBasis.NONE


def resolve_broker_view(
    view: BrokerView,
    record: TradeRecord | None,
    identity: TradeIdentity,
) -> BrokerView:
    """Attribute every open order in a raw broker view.

    Unattributed orders keep a redacted ``<foreign-N>`` placeholder: they stay
    VISIBLE, because any working order on our symbol must block a new entry,
    while staying excluded from anything that touches an order.
    """
    resolved: list[BrokerOrderView] = []
    for index, raw in enumerate(view.open_orders):
        client_order_id, basis = resolve_ownership(raw, record, identity)
        resolved.append(
            replace(
                raw,
                client_order_id=client_order_id or f"<foreign-{index}>",
                ownership=basis,
            )
        )
    return replace(view, open_orders=tuple(resolved))


def assert_symbol_has_no_open_orders(
    broker: BrokerView,
    symbol: str,
    identity: TradeIdentity,
) -> None:
    """Refuse to arm while ANY order is working on the symbol, from any source.

    A manual SELL working on SPY is invisible to KalpaMani-owned filters, but it
    is not invisible to the account: we could buy 1, the manual order could fill,
    and ownership of the resulting position becomes ambiguous -- at which point
    our protective stop can sell something we no longer hold and open a short.

    Foreign orders are never cancelled or modified. We simply decline to trade
    alongside them. Counts only are reported: unrelated order details are not
    ours to log.

    Raises:
        ReconciliationError: if any order is working on ``symbol``.
    """
    total = broker.open_order_count_for_symbol(symbol)
    if total == 0:
        return
    foreign = broker.foreign_open_order_count_for_symbol(symbol, identity)
    owned = total - foreign
    raise ReconciliationError(
        f"Existing open {symbol} order(s) detected: {total} working "
        f"({foreign} non-KalpaMani, {owned} KalpaMani). Refusing to arm -- position "
        "ownership would be ambiguous, and a protective stop could then sell a position "
        "KalpaMani does not hold. Foreign orders are left untouched; resolve manually."
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
    "EXPECTED_ORDER_TYPE",
    "BrokerOrderView",
    "BrokerPositionView",
    "BrokerView",
    "ExitPlan",
    "OwnershipBasis",
    "OwnershipError",
    "ReconciliationError",
    "ReconciliationResult",
    "UnprotectedPositionError",
    "assert_flat",
    "assert_protected",
    "assert_safe_to_close",
    "assert_symbol_has_no_open_orders",
    "normalise_order_type",
    "plan_exit",
    "reconcile",
    "required_protection_quantity",
    "resolve_broker_view",
    "resolve_ownership",
]
