"""Durable trade state and the order dispatch model (ADR-0004 §5).

Idempotency that lives only in process memory is erased by exactly the event it
exists to survive. So the record of "we intend to send this" is written to disk
**before** the order leaves the process, and read back on recovery.

The dispatch model
------------------
"Submitted" is too coarse a word to be safe. A durable record written before a
broker call is *not* evidence that the broker received anything, and treating it
as such lets a crash leave a position that looks protected but is not. So each
order carries an explicit :class:`DispatchState`:

    INTENT_RECORDED  durable write done; the dispatcher has NOT yet committed to
                     contacting the broker. We know the order does not exist.
    SEND_FENCED      the SEND FENCE is durable. From this point on the broker call
                     MAY have happened, and automatic resend is FORBIDDEN.
    ACKNOWLEDGED     the broker confirms the order is working
    FILLED           the broker filled it
    CANCELLED        the broker CONFIRMED a cancellation
    REJECTED         the broker rejected it (LEAN OrderStatus.INVALID)

Why a fence and not "attempted"
-------------------------------
There is no atomic transaction spanning "call the broker" and "write that we
called it". Whichever order those happen in, a crash can fall between them. So
the fence is persisted **before** the call, and its meaning is deliberately
weaker than "we sent it": *a send may have occurred*. That is the honest
statement, and it is the safe one -- inferring "definitely not sent" from a
missing post-call write is what would let recovery issue a second SELL.

A crash after the fence but before the call therefore looks identical to a crash
after the call. Both halt for a human. That conservative ambiguity is the
intended trade: safety over automatic liveness.

The distinction that matters most: ``protected_quantity`` counts a protective
order only once the broker has **acknowledged** it. A fenced-but-unconfirmed
order must never be mistaken for working protection.

Three storage rules
-------------------
* Writes are **atomic** (temp file + fsync + ``os.replace``). A crash mid-write
  leaves the previous good state, never a half-written one.
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
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from kalpamani.common.errors import SafetyViolationError
from kalpamani.execution.identity import OrderRole
from kalpamani.execution.lifecycle import TradeState

#: Bumped when the persisted shape changes. Unknown versions fail closed.
#: v2 introduced the explicit dispatch model in place of a boolean "submitted".
#: v3 replaced DISPATCH_ATTEMPTED with the SEND_FENCED send fence.
#: v4 bound each record to the brokerage account it was armed against.
STATE_SCHEMA_VERSION = 4


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


class StaleWriteError(StateStoreError):
    """An older in-memory record tried to overwrite newer durable state.

    Field-level monotonicity is not enough on its own: writing a whole stale
    record would roll back *every* field, including broker evidence adopted since
    the stale copy was taken. Refusing loudly turns a silent rollback into a
    visible failure.
    """


class DispatchState(StrEnum):
    """How far an order has got toward the broker, stated honestly.

    The gap between the first two values is the whole point. ``INTENT_RECORDED``
    is a positive claim -- the dispatcher has not committed, so the order does
    not exist at the broker. ``SEND_FENCED`` is deliberately weaker: it says only
    that a send *may* have happened, because no transaction spans the broker call
    and the record of it.
    """

    INTENT_RECORDED = "INTENT_RECORDED"
    #: The SEND FENCE. Persisted BEFORE the broker call. From here, automatic
    #: resend is forbidden regardless of what the open-order list shows.
    SEND_FENCED = "SEND_FENCED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


#: Dispatch states from which no further broker action is expected.
TERMINAL_DISPATCH: frozenset[DispatchState] = frozenset(
    {DispatchState.FILLED, DispatchState.CANCELLED, DispatchState.REJECTED}
)

#: Dispatch progress is MONOTONIC. A stale in-memory record must never be able
#: to write an order back to an earlier state -- e.g. an object captured before
#: reconciliation adopted ACKNOWLEDGED must not push it back to SEND_FENCED,
#: which would re-open the "may not have been sent" ambiguity on an order the
#: broker has positively confirmed.
_DISPATCH_RANK: dict[DispatchState, int] = {
    DispatchState.INTENT_RECORDED: 0,
    DispatchState.SEND_FENCED: 1,
    DispatchState.ACKNOWLEDGED: 2,
    DispatchState.FILLED: 3,
    DispatchState.CANCELLED: 3,
    DispatchState.REJECTED: 3,
}


@dataclass(frozen=True, slots=True)
class SubmittedOrder:
    """A durable record of one order and how far it has actually got."""

    client_order_id: str
    role: OrderRole
    symbol: str
    side: str
    quantity: int
    dispatch: DispatchState = DispatchState.INTENT_RECORDED
    #: A cancellation was ASKED FOR. The broker may still be working the order.
    cancel_requested: bool = False
    filled_quantity: int = 0
    #: Broker-assigned handle. Recorded for audit; never derived from, never
    #: branched on (ADR-0002 §4).
    broker_order_id: str | None = None
    #: Fill identities already applied, so a repeated fill event is a no-op.
    applied_fill_ids: tuple[str, ...] = ()
    #: Stop price as a decimal string, for STOP orders only. Durable so that an
    #: undispatched protective intent can be rebuilt exactly on recovery.
    stop_price: str | None = None

    @property
    def send_fenced(self) -> bool:
        """Whether the send fence was acquired.

        Once true, a broker call may have occurred and this order must never be
        automatically resent.
        """
        return self.dispatch is not DispatchState.INTENT_RECORDED

    @property
    def broker_confirmed(self) -> bool:
        """Whether the broker has positively evidenced this order's existence."""
        return self.dispatch in (
            DispatchState.ACKNOWLEDGED,
            DispatchState.FILLED,
            DispatchState.CANCELLED,
        )

    @property
    def dispatch_outcome_unknown(self) -> bool:
        """The fence is held but the broker has confirmed nothing either way.

        The ambiguous case, and it covers both a crash before the broker call and
        a crash after it -- they are indistinguishable from durable state alone.
        Never resend from here: the order may be live.
        """
        return self.dispatch is DispatchState.SEND_FENCED

    @property
    def is_working(self) -> bool:
        """Whether the broker may still act on this order.

        Requires broker acknowledgement. A fenced-but-unconfirmed order is not
        counted as working, because we do not know that it is.
        """
        return self.dispatch is DispatchState.ACKNOWLEDGED and self.filled_quantity < self.quantity

    @property
    def is_open(self) -> bool:
        """Alias kept for reconciliation readability."""
        return self.is_working


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
    #: Fingerprint of the brokerage account this trade was ARMED against.
    #:
    #: The trade is bound to an account, not merely to a mode. Without this, a
    #: restart pointed at a different account could look like a normal recovery:
    #: paper account A holds the position, the process comes back against
    #: account B, and local state -- which knows nothing about B -- would happily
    #: authorise a protective or exit order into the wrong account.
    #:
    #: A pseudonymous account-binding digest, never the raw identifier. The
    #: digest is itself sensitive (see session.account_fingerprint): it lives
    #: only under the git-ignored runtime directory and is never logged or
    #: printed -- describe() reports presence, not the value. Optional only
    #: because dataclass defaults require it; every code path that can reach the
    #: broker treats ``None`` as a fail-closed condition.
    account_fingerprint: str | None = None
    #: Optimistic-concurrency revision. Incremented by every successful write.
    #: A put whose revision is behind the stored one is refused.
    revision: int = 0

    def order_for_role(self, role: OrderRole) -> SubmittedOrder | None:
        for order in self.orders.values():
            if order.role is role:
                return order
        return None

    @property
    def entry_count(self) -> int:
        """How many entry orders exist at all. Must never exceed 1.

        Counts an order from the moment its intent is recorded, not from
        dispatch: a recorded intent already forbids creating another.
        """
        return sum(1 for o in self.orders.values() if o.role is OrderRole.ENTRY)

    @property
    def open_long_quantity(self) -> int:
        """Long quantity believed held, per local records.

        A filled PROTECTIVE stop closes the long just as surely as a deliberate
        exit does. Counting only entry-minus-exit would leave the system
        believing it still held a position the stop had already sold -- and it
        would then try to sell it again, opening a short.
        """
        entry = self.order_for_role(OrderRole.ENTRY)
        held = entry.filled_quantity if entry else 0
        closed = sum(
            order.filled_quantity
            for order in self.orders.values()
            if order.role in (OrderRole.EXIT, OrderRole.PROTECTIVE)
        )
        return held - closed

    @property
    def protective_fill_quantity(self) -> int:
        """Quantity closed by the protective stop firing, if it did."""
        protective = self.order_for_role(OrderRole.PROTECTIVE)
        return protective.filled_quantity if protective else 0

    @property
    def has_working_protection(self) -> bool:
        """Whether protection is broker-confirmed working."""
        protective = self.order_for_role(OrderRole.PROTECTIVE)
        return bool(protective and protective.is_working)

    def unfenced_orders(self) -> list[SubmittedOrder]:
        """Orders recorded but never fenced -- so provably never sent."""
        return [o for o in self.orders.values() if o.dispatch is DispatchState.INTENT_RECORDED]

    def fenced_unconfirmed_orders(self) -> list[SubmittedOrder]:
        """Orders holding the send fence with no broker confirmation either way."""
        return [o for o in self.orders.values() if o.dispatch_outcome_unknown]

    def describe(self) -> str:
        """Log-safe summary. No account identifier, no secret."""
        dispatches = ",".join(f"{o.role.value}:{o.dispatch.value}" for o in self.orders.values())
        return (
            f"intent={self.trade_intent_id} execution={self.execution_id} "
            f"state={self.state.value} symbol={self.symbol} "
            f"requested={self.requested_quantity} filled={self.filled_quantity} "
            f"protected={self.protected_quantity} entries={self.entry_count} "
            f"long={self.open_long_quantity} arm_consumed={self.arm_consumed} "
            f"account_binding={'present' if self.account_fingerprint else 'ABSENT'} "
            f"dispatch=[{dispatches}]"
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

    def put(self, record: TradeRecord) -> TradeRecord:
        """Persist ``record`` atomically and return it with the bumped revision.

        Raises:
            StaleWriteError: if ``record`` is behind the stored revision.
        """
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
            "dispatch": order.dispatch.value,
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
                dispatch=DispatchState(raw["dispatch"]),
                cancel_requested=bool(raw.get("cancel_requested", False)),
                filled_quantity=int(raw["filled_quantity"]),
                broker_order_id=raw.get("broker_order_id"),
                applied_fill_ids=tuple(raw.get("applied_fill_ids", ())),
                stop_price=raw.get("stop_price"),
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
            account_fingerprint=payload.get("account_fingerprint"),
            revision=int(payload.get("revision", 0)),
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

    def put(self, record: TradeRecord) -> TradeRecord:
        """Persist atomically: write a temp file, fsync, then replace.

        A crash part-way through leaves the previous good file untouched.

        Refuses a stale write. If the stored record has advanced past the one
        being written, the caller is holding an out-of-date object and
        persisting it would roll back everything learned since.

        Returns:
            The persisted record, carrying the incremented revision. Callers
            must use this, not the object they passed in.

        Raises:
            StaleWriteError: if ``record`` is behind the stored revision.
        """
        trades = self._load()
        existing = trades.get(record.trade_intent_id)
        if existing is not None and existing.revision > record.revision:
            raise StaleWriteError(
                f"Refusing a stale write for {record.trade_intent_id}: stored revision "
                f"{existing.revision} is newer than the in-memory revision {record.revision}. "
                "Persisting it would discard state adopted since this copy was taken. "
                "Re-read the record and retry."
            )
        record = replace(record, revision=record.revision + 1)
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
        return record

    def all_records(self) -> list[TradeRecord]:
        return list(self._load().values())


def _recompute(record: TradeRecord) -> TradeRecord:
    """Recompute derived totals from the orders that actually exist.

    ``protected_quantity`` counts a protective order only when the broker has
    acknowledged it and it is still working. An intent that was recorded but
    never dispatched, or dispatched with no acknowledgement, is **not** counted
    -- claiming protection we cannot evidence is how an unprotected position
    comes to look healthy.
    """
    entry = record.order_for_role(OrderRole.ENTRY)
    protective = record.order_for_role(OrderRole.PROTECTIVE)
    return replace(
        record,
        filled_quantity=entry.filled_quantity if entry else 0,
        protected_quantity=protective.quantity if protective and protective.is_working else 0,
    )


def record_order_intent(
    record: TradeRecord,
    *,
    client_order_id: str,
    role: OrderRole,
    symbol: str,
    side: str,
    quantity: int,
    stop_price: str | None = None,
) -> TradeRecord:
    """Write-ahead-record an order that is about to be sent.

    The order starts at :attr:`DispatchState.INTENT_RECORDED`: durable, but not
    yet handed to the broker.

    Raises:
        StateStoreError: if this ``client_order_id`` is already recorded, or if a
            second ENTRY is attempted. Both mean the caller is about to duplicate
            an order it has already recorded.
    """
    if client_order_id in record.orders:
        raise StateStoreError(
            f"Order {client_order_id} is already recorded for execution {record.execution_id}. "
            "Refusing to record it twice -- this is the duplicate-order path."
        )
    if role is OrderRole.ENTRY and record.entry_count >= 1:
        raise StateStoreError(
            f"Execution {record.execution_id} already has {record.entry_count} entry "
            "order(s). A second entry is a duplicate, not an addition."
        )
    orders = dict(record.orders)
    orders[client_order_id] = SubmittedOrder(
        client_order_id=client_order_id,
        role=role,
        symbol=symbol,
        side=side,
        quantity=quantity,
        dispatch=DispatchState.INTENT_RECORDED,
        stop_price=stop_price,
    )
    return _recompute(replace(record, orders=orders))


def _advance_dispatch(
    record: TradeRecord,
    client_order_id: str,
    target: DispatchState,
    *,
    broker_order_id: str | None = None,
) -> TradeRecord:
    order = record.orders.get(client_order_id)
    if order is None:
        raise StateStoreError(f"Cannot move unknown order {client_order_id} to {target.value}.")
    if _DISPATCH_RANK[target] <= _DISPATCH_RANK[order.dispatch]:
        # Never regress. A repeat of the same step is a harmless no-op; a step
        # backwards would discard broker evidence we already hold.
        return record
    orders = dict(record.orders)
    orders[client_order_id] = replace(
        order,
        dispatch=target,
        broker_order_id=broker_order_id or order.broker_order_id,
    )
    return _recompute(replace(record, orders=orders))


def fence_dispatch(record: TradeRecord, client_order_id: str) -> TradeRecord:
    """Acquire the durable SEND FENCE. Must be persisted BEFORE the broker call.

    After this returns, the only honest statement about the order is "a send may
    have occurred". That is weaker than "we sent it", and deliberately so: it is
    what makes automatic resend unsafe and therefore forbidden.
    """
    return _advance_dispatch(record, client_order_id, DispatchState.SEND_FENCED)


def mark_acknowledged(
    record: TradeRecord,
    client_order_id: str,
    *,
    broker_order_id: str | None = None,
) -> TradeRecord:
    """Record positive broker evidence that the order is working."""
    return _advance_dispatch(
        record, client_order_id, DispatchState.ACKNOWLEDGED, broker_order_id=broker_order_id
    )


def mark_rejected(record: TradeRecord, client_order_id: str) -> TradeRecord:
    """Record that the broker rejected the order (LEAN ``OrderStatus.INVALID``)."""
    return _advance_dispatch(record, client_order_id, DispatchState.REJECTED)


def request_cancel(record: TradeRecord, client_order_id: str) -> TradeRecord:
    """Record that a cancellation was REQUESTED. The order is still working.

    Deliberately does NOT mark the order cancelled. LEAN reports ``CANCEL_PENDING``
    before ``CANCELED``; treating the request as the outcome would let the exit
    proceed while a live stop could still fire -- the exact path to an accidental
    short.
    """
    order = record.orders.get(client_order_id)
    if order is None:
        raise StateStoreError(f"Cannot request cancellation of unknown order {client_order_id}.")
    orders = dict(record.orders)
    orders[client_order_id] = replace(order, cancel_requested=True)
    return _recompute(replace(record, orders=orders))


def confirm_cancel(record: TradeRecord, client_order_id: str) -> TradeRecord:
    """Record that the broker CONFIRMED a cancellation (``OrderStatus.CANCELED``).

    Only this makes the order inert, drops ``protected_quantity`` to zero, and
    makes the closing order eligible.
    """
    order = record.orders.get(client_order_id)
    if order is None:
        raise StateStoreError(f"Cannot confirm cancellation of unknown order {client_order_id}.")
    orders = dict(record.orders)
    orders[client_order_id] = replace(
        order, dispatch=DispatchState.CANCELLED, cancel_requested=True
    )
    return _recompute(replace(record, orders=orders))


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
        # A fill is itself broker evidence that the order existed and was working.
        dispatch=(
            DispatchState.FILLED if new_filled >= order.quantity else DispatchState.ACKNOWLEDGED
        ),
    )
    return _recompute(replace(record, orders=orders))


def usd(amount: Decimal | int | str) -> Decimal:
    """Coerce to Decimal. Money is never a float in this codebase."""
    return Decimal(str(amount))


__all__ = [
    "STATE_SCHEMA_VERSION",
    "TERMINAL_DISPATCH",
    "DispatchState",
    "JsonTradeStateStore",
    "StaleWriteError",
    "StateCorruptError",
    "StateMissingError",
    "StateStoreError",
    "SubmittedOrder",
    "TradeRecord",
    "TradeStateStore",
    "apply_fill",
    "confirm_cancel",
    "fence_dispatch",
    "mark_acknowledged",
    "mark_rejected",
    "record_order_intent",
    "request_cancel",
    "usd",
]
