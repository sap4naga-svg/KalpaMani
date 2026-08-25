"""Durable trade state (ADR-0004 §5).

Idempotency that lives only in process memory is erased by exactly the event it
exists to survive. So the record of "we already submitted this" is written to
disk **before** the order leaves the process, and read back on recovery.

Phase 2 uses a local JSON file. It is deliberately minimal and deliberately
behind :class:`TradeStateStore`, so PostgreSQL can replace it without lifecycle
logic changing.

Three rules make this trustworthy:

* Writes are **atomic** (temp file + ``os.replace``). A crash mid-write leaves
  the previous good state, never a half-written one.
* A **schema version** is recorded. An unrecognised version fails closed rather
  than being parsed optimistically.
* Missing, unreadable or corrupt state **fails closed** when a trade is expected.
  It is never read as "no record, therefore nothing happened" -- that inference
  is precisely how a restart becomes a duplicate order.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from kalpamani.common.errors import SafetyViolationError
from kalpamani.execution.identity import OrderRole
from kalpamani.execution.lifecycle import TradeState

#: Bumped when the persisted shape changes. Unknown versions fail closed.
STATE_SCHEMA_VERSION = 1


class StateStoreError(SafetyViolationError):
    """Durable state could not be trusted, so no action may proceed."""


class StateMissingError(StateStoreError):
    """A trade record was expected to exist and does not.

    Treated as a safety violation rather than a normal absence: if the caller
    believed a trade existed, the disagreement must be resolved by a human
    before anything touches the broker.
    """


class StateCorruptError(StateStoreError):
    """Durable state exists but cannot be parsed or is internally inconsistent."""


@dataclass(frozen=True, slots=True)
class SubmittedOrder:
    """A durable record that an order was intended and/or submitted.

    ``submitted`` is written **before** the broker call (write-ahead). A record
    with ``submitted=True`` and no broker acknowledgement is recoverable by
    inspection; the reverse -- a live broker order with no local record -- is not,
    which is why the write happens first.
    """

    client_order_id: str
    role: OrderRole
    symbol: str
    side: str
    quantity: int
    submitted: bool = False
    acknowledged: bool = False
    cancelled: bool = False
    filled_quantity: int = 0
    #: Broker-assigned handle. Recorded for audit; never derived from, never
    #: branched on (ADR-0002 §4).
    broker_order_id: str | None = None
    #: Fill identities already applied, so a repeated fill event is a no-op.
    applied_fill_ids: tuple[str, ...] = ()

    @property
    def is_open(self) -> bool:
        """Whether the broker may still act on this order."""
        return self.submitted and not self.cancelled and self.filled_quantity < self.quantity


@dataclass(frozen=True, slots=True)
class TradeRecord:
    """The complete durable record of one execution attempt."""

    trade_intent_id: str
    execution_id: str
    natural_key: str
    attempt: int
    symbol: str
    state: TradeState
    requested_quantity: int
    filled_quantity: int = 0
    protected_quantity: int = 0
    orders: dict[str, SubmittedOrder] = field(default_factory=dict)
    #: Set once the human execution arm has been consumed. Never reset by a
    #: restart -- that is what stops recovery from re-arming.
    arm_consumed: bool = False
    failure_reason: str | None = None

    def order_for_role(self, role: OrderRole) -> SubmittedOrder | None:
        for order in self.orders.values():
            if order.role is role:
                return order
        return None

    @property
    def entry_count(self) -> int:
        """How many entry orders have been submitted. Must never exceed 1."""
        return sum(1 for o in self.orders.values() if o.role is OrderRole.ENTRY and o.submitted)

    @property
    def open_long_quantity(self) -> int:
        """Long quantity believed held, per local records."""
        entry = self.order_for_role(OrderRole.ENTRY)
        exit_order = self.order_for_role(OrderRole.EXIT)
        held = entry.filled_quantity if entry else 0
        closed = exit_order.filled_quantity if exit_order else 0
        return held - closed

    def describe(self) -> str:
        """Log-safe summary. No account identifier, no secret."""
        return (
            f"intent={self.trade_intent_id} execution={self.execution_id} "
            f"state={self.state.value} symbol={self.symbol} "
            f"requested={self.requested_quantity} filled={self.filled_quantity} "
            f"protected={self.protected_quantity} entries={self.entry_count} "
            f"arm_consumed={self.arm_consumed}"
        )


class TradeStateStore(Protocol):
    """Durable persistence for trade records.

    Kept deliberately narrow so a PostgreSQL implementation is a drop-in.
    """

    def get(self, trade_intent_id: str) -> TradeRecord | None:
        """Return the record, or ``None`` if genuinely absent."""
        ...

    def require(self, trade_intent_id: str) -> TradeRecord:
        """Return the record, or raise :class:`StateMissingError`."""
        ...

    def put(self, record: TradeRecord) -> None:
        """Persist ``record`` atomically."""
        ...

    def all_records(self) -> list[TradeRecord]:
        """Every record currently stored."""
        ...


def _serialise(record: TradeRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["state"] = record.state.value
    payload["orders"] = {
        cid: {
            **asdict(order),
            "role": order.role.value,
            "applied_fill_ids": list(order.applied_fill_ids),
        }
        for cid, order in record.orders.items()
    }
    return payload


def _deserialise(payload: dict[str, Any]) -> TradeRecord:
    try:
        orders = {
            cid: SubmittedOrder(
                client_order_id=raw["client_order_id"],
                role=OrderRole(raw["role"]),
                symbol=raw["symbol"],
                side=raw["side"],
                quantity=int(raw["quantity"]),
                submitted=bool(raw["submitted"]),
                acknowledged=bool(raw["acknowledged"]),
                cancelled=bool(raw["cancelled"]),
                filled_quantity=int(raw["filled_quantity"]),
                broker_order_id=raw.get("broker_order_id"),
                applied_fill_ids=tuple(raw.get("applied_fill_ids", ())),
            )
            for cid, raw in payload["orders"].items()
        }
        return TradeRecord(
            trade_intent_id=payload["trade_intent_id"],
            execution_id=payload["execution_id"],
            natural_key=payload["natural_key"],
            attempt=int(payload["attempt"]),
            symbol=payload["symbol"],
            state=TradeState.parse(payload["state"]),
            requested_quantity=int(payload["requested_quantity"]),
            filled_quantity=int(payload["filled_quantity"]),
            protected_quantity=int(payload["protected_quantity"]),
            orders=orders,
            arm_consumed=bool(payload.get("arm_consumed", False)),
            failure_reason=payload.get("failure_reason"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StateCorruptError(
            f"Durable trade state is malformed and cannot be trusted: {exc}. Refusing to "
            "proceed -- acting on state we cannot parse risks duplicating a live order."
        ) from exc


class JsonTradeStateStore:
    """Atomic, single-file JSON implementation of :class:`TradeStateStore`.

    Adequate for Phase 2 certification and nothing more. The Protocol exists so
    the PostgreSQL replacement is an implementation swap.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, TradeRecord]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateCorruptError(
                f"Durable trade state at {self._path} is unreadable: {exc}. Refusing to "
                "treat unreadable state as 'no trade exists'."
            ) from exc

        version = raw.get("schema_version")
        if version != STATE_SCHEMA_VERSION:
            raise StateCorruptError(
                f"Durable trade state schema version {version!r} is not the expected "
                f"{STATE_SCHEMA_VERSION}. State written by a different version of this "
                "code must be migrated deliberately, not parsed hopefully."
            )
        return {tid: _deserialise(p) for tid, p in raw.get("trades", {}).items()}

    def get(self, trade_intent_id: str) -> TradeRecord | None:
        return self._load().get(trade_intent_id)

    def require(self, trade_intent_id: str) -> TradeRecord:
        record = self.get(trade_intent_id)
        if record is None:
            raise StateMissingError(
                f"No durable record for trade intent {trade_intent_id}, but one was expected. "
                "Refusing to continue: absent state must never be read as 'nothing happened', "
                "because that is how a restart becomes a duplicate order."
            )
        return record

    def put(self, record: TradeRecord) -> None:
        """Persist atomically: write a temp file, then replace.

        A crash part-way through leaves the previous good file untouched.
        """
        trades = self._load()
        trades[record.trade_intent_id] = record
        payload = {
            "schema_version": STATE_SCHEMA_VERSION,
            "trades": {tid: _serialise(r) for tid, r in trades.items()},
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle as tmp:
                json.dump(payload, tmp, indent=2, sort_keys=True)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(handle.name, self._path)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise

    def all_records(self) -> list[TradeRecord]:
        return list(self._load().values())


def record_order_intent(
    record: TradeRecord,
    *,
    client_order_id: str,
    role: OrderRole,
    symbol: str,
    side: str,
    quantity: int,
) -> TradeRecord:
    """Return ``record`` with a write-ahead entry for an order about to be sent.

    Raises:
        StateStoreError: if this ``client_order_id`` is already recorded, or if a
            second ENTRY is attempted. Both mean the caller is about to duplicate
            an order it has already sent.
    """
    if client_order_id in record.orders:
        raise StateStoreError(
            f"Order {client_order_id} is already recorded for execution {record.execution_id}. "
            "Refusing to record it twice -- this is the duplicate-order path."
        )
    if role is OrderRole.ENTRY and record.entry_count >= 1:
        raise StateStoreError(
            f"Execution {record.execution_id} already has {record.entry_count} submitted entry "
            "order(s). A second entry is a duplicate, not an addition."
        )
    orders = dict(record.orders)
    orders[client_order_id] = SubmittedOrder(
        client_order_id=client_order_id,
        role=role,
        symbol=symbol,
        side=side,
        quantity=quantity,
        submitted=True,
    )
    return replace(record, orders=orders)


def apply_fill(
    record: TradeRecord,
    *,
    client_order_id: str,
    fill_id: str,
    fill_quantity: int,
) -> TradeRecord:
    """Apply a fill idempotently, keyed on broker fill identity.

    A repeated event for a fill already applied returns the record unchanged, so
    duplicate delivery cannot inflate filled quantity or trigger a second
    protective order.

    Raises:
        StateStoreError: if the order is unknown, or the fill would exceed the
            order's quantity.
    """
    order = record.orders.get(client_order_id)
    if order is None:
        raise StateStoreError(
            f"Fill for unknown order {client_order_id}. Refusing to invent a record for an "
            "order this process did not submit."
        )
    if fill_id in order.applied_fill_ids:
        return record

    new_filled = order.filled_quantity + fill_quantity
    if new_filled > order.quantity:
        raise StateStoreError(
            f"Fill would take order {client_order_id} to {new_filled} of {order.quantity}. "
            "Over-fill indicates contradictory broker state; failing closed."
        )

    orders = dict(record.orders)
    orders[client_order_id] = replace(
        order,
        filled_quantity=new_filled,
        applied_fill_ids=(*order.applied_fill_ids, fill_id),
        acknowledged=True,
    )
    updated = replace(record, orders=orders)
    entry = updated.order_for_role(OrderRole.ENTRY)
    protective = updated.order_for_role(OrderRole.PROTECTIVE)
    return replace(
        updated,
        filled_quantity=entry.filled_quantity if entry else 0,
        protected_quantity=(protective.quantity if protective and not protective.cancelled else 0),
    )


def usd(amount: Decimal | int | str) -> Decimal:
    """Coerce to Decimal. Money is never a float in this codebase."""
    return Decimal(str(amount))


__all__ = [
    "STATE_SCHEMA_VERSION",
    "JsonTradeStateStore",
    "StateCorruptError",
    "StateMissingError",
    "StateStoreError",
    "SubmittedOrder",
    "TradeRecord",
    "TradeStateStore",
    "apply_fill",
    "record_order_intent",
    "usd",
]
