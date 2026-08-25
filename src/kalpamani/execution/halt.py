"""The operational halt, and which halts survive a restart (ADR-0004 §15).

A halt latch that lives only in memory is cleared by the one event it most needs
to survive. Phase 2 told the operator "normal progression REMAINS halted" and
then, on the next process start, resumed as though nothing had happened.

Why this is not just ``TradeState.FAILED``
------------------------------------------
``FAILED`` is a *lifecycle* verdict and it is terminal. It cannot also serve as
the mutable broker-fact ledger, because broker facts keep arriving after it --
a fill for an order sent before the failure is still true, and still has to be
recorded. So the operational halt is a separate, small piece of state:

    lifecycle  ->  what this trade's progression concluded (terminal)
    ledger     ->  what the broker actually did (always appendable)
    halt       ->  whether this DEPLOYMENT may take new normal action

Unknown failures fail toward safety -- revised 2026-08-25
---------------------------------------------------------
The first version of this policy read "a safety violation is durable, anything
else is transient until proven otherwise". That is **fail-open** the moment the
system is order-capable, and this review cycle produced the counter-example: a
``TypeError`` from .NET's ``System.Decimal`` shadowing Python's, sitting on the
armed path, invisible to a full green test suite. Under the old rule that would
have halted the session and then **cleared itself on restart** -- with an entry
possibly live at the broker.

The rule is now the other way round:

**Once anything is at stake, EVERY halt is durable. An unrecognised failure is
durable whether anything is at stake or not. Only an explicitly enumerated,
known-benign pre-trade condition may be session-scoped.**

"At stake" is :class:`ExecutionRisk`, and it is deliberately broad: an arm
consumed, a trade record existing at all, an order recorded, a send fence held,
a broker acknowledgement, a fill, a position that may exist, a close in
progress, or durable state we could not even read. Any one of those, and the
halt survives the restart.

Making every hiccup a permanent chore is still a real failure mode -- an
operator who clears halts reflexively has stopped reading them -- so
:data:`TRANSIENT_PRE_TRADE_ERRORS` keeps a short, explicit allowlist. It applies
*only* before anything exists to lose, and it lists conditions by type rather
than by exclusion. Nothing joins it by default.

What a halt does NOT stop
-------------------------
Broker facts are still ingested, and a position that fills is still protected
(the guarded risk-reducing exception). A halt stops *new normal decisions*; it
was never meant to stop us knowing what the broker did.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from kalpamani.broker.account import BrokerAccountMode
from kalpamani.common.errors import SafetyViolationError
from kalpamani.execution.identity import OrderRole
from kalpamani.execution.lifecycle import TradeState
from kalpamani.execution.session import BrokerSessionEvidence
from kalpamani.execution.state_store import DispatchState, TradeRecord

#: Bumped when the persisted shape changes. Unknown versions fail closed.
HALT_SCHEMA_VERSION = 1


class HaltStoreError(SafetyViolationError):
    """The durable halt record could not be read or trusted."""


class HaltKind(StrEnum):
    """How long a halt lasts."""

    #: Halts this deployment only. A restart may retry.
    SESSION = "SESSION"
    #: Survives restart. Only an explicit human action clears it.
    MANUAL_CLEARANCE_REQUIRED = "MANUAL_CLEARANCE_REQUIRED"


class HaltClearanceError(SafetyViolationError):
    """A durable halt cannot be cleared: something it protects is still unsafe."""


#: The ONLY failures that may halt session-scoped, and only when nothing is at
#: stake. An allowlist by type, never a catch-all by exclusion: a category joins
#: this tuple because someone established it is benign, not because it failed to
#: match something else.
#:
#: Both are transport conditions raised before any order exists -- the IB data
#: farm not yet available on a cold start, a socket timing out while the gateway
#: authenticates. Neither can leave an order, a fence or a position behind,
#: because on this path none of those exist yet.
TRANSIENT_PRE_TRADE_ERRORS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
)


@dataclass(frozen=True, slots=True)
class ExecutionRisk:
    """Whether anything is at stake, and therefore whether a halt must persist.

    Deliberately broad and deliberately pessimistic. Every field here is a
    condition under which an order may exist, may have existed, or may be about
    to; and any single one of them makes a halt durable regardless of what
    caused it.
    """

    #: Durable state could not be read. We do not know what we are holding.
    state_unreadable: bool = False
    arm_consumed: bool = False
    trade_record_exists: bool = False
    orders_recorded: bool = False
    send_fence_held: bool = False
    broker_acknowledged: bool = False
    fills_applied: bool = False
    position_may_exist: bool = False
    closing_in_progress: bool = False
    #: Broker truth was established this cycle. False means we could not see it.
    broker_state_established: bool = True

    @property
    def any_execution_risk(self) -> bool:
        return (
            self.state_unreadable
            or self.arm_consumed
            or self.trade_record_exists
            or self.orders_recorded
            or self.send_fence_held
            or self.broker_acknowledged
            or self.fills_applied
            or self.position_may_exist
            or self.closing_in_progress
            # NOT `or not broker_state_established`. Failing to read broker
            # truth matters when we hold something -- and a record existing
            # already forces risk on the line above. Before any record exists
            # there is nothing to be confident *about*, and treating a cold-start
            # data-farm blip as durable would make the pre-trade allowlist
            # unreachable in the one case it exists for. Our OWN state being
            # unreadable is different, and is the first condition here.
        )

    def describe(self) -> str:
        """Log-safe. Names the conditions, carries no identifier."""
        active = [
            name
            for name in (
                "state_unreadable",
                "arm_consumed",
                "trade_record_exists",
                "orders_recorded",
                "send_fence_held",
                "broker_acknowledged",
                "fills_applied",
                "position_may_exist",
                "closing_in_progress",
            )
            if getattr(self, name)
        ]
        if not self.broker_state_established:
            active.append("broker_state_unestablished")
        return ",".join(active) or "(nothing at stake)"

    @classmethod
    def nothing_at_stake(cls, *, broker_state_established: bool = True) -> ExecutionRisk:
        """No trade record exists. Only reachable before anything is authorised."""
        return cls(broker_state_established=broker_state_established)

    @classmethod
    def unknown(cls) -> ExecutionRisk:
        """We could not establish our own state. Treated as maximum risk."""
        return cls(state_unreadable=True, broker_state_established=False)

    @classmethod
    def from_record(
        cls, record: TradeRecord, *, broker_state_established: bool = True
    ) -> ExecutionRisk:
        orders = list(record.orders.values())
        return cls(
            arm_consumed=record.arm_consumed,
            trade_record_exists=True,
            orders_recorded=bool(orders),
            send_fence_held=any(o.send_fenced for o in orders),
            broker_acknowledged=any(o.broker_confirmed for o in orders),
            fills_applied=any(o.filled_quantity > 0 for o in orders),
            position_may_exist=record.open_long_quantity != 0
            or any(o.role is OrderRole.ENTRY and o.send_fenced for o in orders),
            closing_in_progress=record.state
            in (TradeState.EXIT_REQUESTED, TradeState.EXIT_SUBMITTED)
            or any(o.role in (OrderRole.PROTECTIVE, OrderRole.EXIT) for o in orders),
            broker_state_established=broker_state_established,
        )


def classify_halt(error: BaseException | None, risk: ExecutionRisk) -> HaltKind:
    """Decide whether a halt must survive a restart. Unknowns fail toward safety.

    Three rules, applied in order:

    1. **Anything at stake -> durable.** Once an arm is consumed, a record
       exists, a fence is held or a position may exist, no failure is small
       enough to forget on restart.
    2. **A safety violation -> durable**, even with nothing at stake. Durable
       state or broker truth being contradictory always needs a human.
    3. **An enumerated benign pre-trade transient -> session.** Everything else,
       including every exception this code has never seen, is **durable**.

    Rule 3 is the reversal. The previous version returned SESSION for anything
    unrecognised, which meant an unknown defect on a broker path cleared itself
    on the next restart.
    """
    if risk.any_execution_risk:
        return HaltKind.MANUAL_CLEARANCE_REQUIRED
    if isinstance(error, SafetyViolationError):
        return HaltKind.MANUAL_CLEARANCE_REQUIRED
    if error is not None and isinstance(error, TRANSIENT_PRE_TRADE_ERRORS):
        return HaltKind.SESSION
    # Unknown, unexpected, or no exception at all: fail toward safety.
    return HaltKind.MANUAL_CLEARANCE_REQUIRED


@dataclass(frozen=True, slots=True)
class OperationalHalt:
    """Why this deployment may not take new normal action."""

    reason: str
    kind: HaltKind

    @property
    def manual_clear_required(self) -> bool:
        return self.kind is HaltKind.MANUAL_CLEARANCE_REQUIRED

    def describe(self) -> str:
        """Log-safe. Carries no account binding and no identifier."""
        return f"kind={self.kind.value} manual_clear_required={self.manual_clear_required}"


class HaltStore(Protocol):
    """Durable persistence for the operational halt."""

    def get(self) -> OperationalHalt | None: ...

    def put(self, halt: OperationalHalt) -> None: ...

    def clear(self) -> None: ...


class JsonHaltStore:
    """Atomic single-file JSON halt store.

    Only :attr:`HaltKind.MANUAL_CLEARANCE_REQUIRED` halts are written. A session
    halt is deliberately *not* persisted -- persisting it would make every
    transient fault a manual chore, which is how operators learn to clear halts
    without reading them.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def get(self) -> OperationalHalt | None:
        if not self._path.exists():
            return None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HaltStoreError(
                f"The durable halt record at {self._path} is unreadable: {exc}. Refusing to "
                "treat an unreadable halt as 'not halted' -- that inference would resume "
                "trading precisely when something is wrong."
            ) from exc
        version = raw.get("schema_version")
        if version != HALT_SCHEMA_VERSION:
            raise HaltStoreError(
                f"Halt record schema version {version!r} is not the expected "
                f"{HALT_SCHEMA_VERSION}. Failing closed rather than parsing hopefully."
            )
        try:
            return OperationalHalt(reason=str(raw["reason"]), kind=HaltKind(raw["kind"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise HaltStoreError(f"The durable halt record is malformed: {exc}.") from exc

    def put(self, halt: OperationalHalt) -> None:
        """Persist a halt that must survive a restart. Session halts are skipped."""
        if not halt.manual_clear_required:
            return
        payload = {
            "schema_version": HALT_SCHEMA_VERSION,
            "reason": halt.reason,
            "kind": halt.kind.value,
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

    def clear(self) -> None:
        """Remove the halt. An explicit human action, never automatic."""
        self._path.unlink(missing_ok=True)


def assert_halt_clearable(
    record: TradeRecord | None,
    evidence: BrokerSessionEvidence,
) -> list[str]:
    """Assert a durable halt may be cleared, and report what could NOT be checked.

    The confirmation phrase is an assertion of intent, not of fact. On its own it
    must never make an unsafe trade resumable, so every invariant that can be
    re-established here is re-established here, from durable state and from the
    deployment configuration.

    What this can prove, and does:

    * the deployment session is PAPER, never LIVE and never unclassifiable;
    * durable state is readable and internally coherent;
    * the trade is bound to *this* deployment account;
    * no send fence is left unresolved;
    * no long is recorded without confirmed protection;
    * no short is recorded at all.

    What it cannot prove, and says so: this runs on the host, with no brokerage
    connection. Local-versus-broker position agreement, unexpected working SPY
    orders and an accidental short at the broker are verifiable only from inside
    a deployment -- and they are, on every cycle, by
    ``Phase2Coordinator.reconcile`` and ``assert_eligible_to_arm``. Clearing the
    halt removes the deployment-level latch and nothing else: the next run still
    re-proves the account, still reconciles, and still halts if anything
    disagrees.

    Clearing also never revives a lifecycle. ``TradeState.FAILED`` is terminal
    and stays terminal; a cleared halt on a FAILED trade buys a read-only
    reconciliation pass, not progression.

    Returns:
        Human-readable caveats the operator must have discharged by hand.

    Raises:
        HaltClearanceError: if any checkable invariant is violated.
    """
    if evidence.mode is not BrokerAccountMode.PAPER:
        raise HaltClearanceError(
            f"REFUSED: the deployment account classifies as {evidence.mode.value!r}. A halt is "
            "never cleared against a session that is not provably PAPER."
        )
    if evidence.effective_trading_mode != "paper":
        raise HaltClearanceError(
            f"REFUSED: the deployment trading mode is {evidence.effective_trading_mode!r}, not "
            "'paper'."
        )

    caveats = [
        "Local position vs BROKER position cannot be checked from the host; the next "
        "deployment reconciles it and will halt again if they disagree.",
        "Unexpected working SPY orders and an accidental short at the broker are visible "
        "only from inside a deployment.",
    ]
    if record is None:
        return caveats

    if not record.account_fingerprint:
        raise HaltClearanceError(
            "REFUSED: the trade record carries no account binding, so it cannot be proven to "
            "belong to this deployment. Failing closed."
        )
    if record.account_fingerprint != evidence.fingerprint:
        raise HaltClearanceError(
            "REFUSED: the trade is bound to a DIFFERENT brokerage account from the one this "
            "deployment is configured for. Clearing a halt across accounts is never correct. "
            "(Neither binding value is printed.)"
        )

    unresolved = [
        o.client_order_id for o in record.orders.values() if o.dispatch is DispatchState.SEND_FENCED
    ]
    if unresolved:
        raise HaltClearanceError(
            f"REFUSED: {len(unresolved)} order(s) hold an unresolved SEND FENCE -- a send may "
            "have occurred and the broker has confirmed nothing either way. Reconcile against "
            "the IBKR order history by hand and resolve the ambiguity FIRST; clearing the halt "
            "would let a deployment act while it still cannot say whether an order is live."
        )

    long_quantity = record.open_long_quantity
    if long_quantity < 0:
        raise HaltClearanceError(
            f"REFUSED: durable state records a SHORT position ({long_quantity} "
            f"{record.symbol}). Phase 2 is long-only; this is the condition the whole design "
            "exists to prevent. Close it by hand and investigate before clearing anything."
        )
    if long_quantity > 0 and record.protected_quantity < long_quantity:
        raise HaltClearanceError(
            f"REFUSED: {long_quantity} {record.symbol} is held with only "
            f"{record.protected_quantity} unit(s) of confirmed protection. An UNPROTECTED "
            "POSITION must be protected or closed at IBKR by hand -- it must not become "
            "autonomous again merely because a halt was cleared."
        )

    if record.state is TradeState.FAILED:
        caveats.append(
            "The trade lifecycle is FAILED and STAYS FAILED. Clearing this halt does not "
            "revive it: the next deployment reads FAILED and halts again. This buys a "
            "read-only reconciliation pass, nothing more."
        )
    return caveats


def halt_state_path(storage_root: Path) -> Path:
    return storage_root / "phase2_operational_halt.json"


__all__ = [
    "HALT_SCHEMA_VERSION",
    "TRANSIENT_PRE_TRADE_ERRORS",
    "ExecutionRisk",
    "HaltClearanceError",
    "HaltKind",
    "HaltStore",
    "HaltStoreError",
    "JsonHaltStore",
    "OperationalHalt",
    "assert_halt_clearable",
    "classify_halt",
    "halt_state_path",
]
