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

Not every halt deserves to be permanent
---------------------------------------
Making every transient warning permanently unrecoverable is its own failure
mode: an operator who has to clear a halt after each hiccup stops reading them.
So halts are classified, and the rule is about *what the halt implies*:

**A safety violation means durable state or broker truth is contradictory, and a
human has to look. Anything else is transient until proven otherwise.**

:class:`~kalpamani.common.errors.SafetyViolationError` is exactly that category
-- unprotected positions, reconciliation mismatches, account-binding failures,
contradictory arm evidence, illegal lifecycle transitions. Those persist and
require explicit human clearance. A transport blip or an unexpected runtime
error halts the session, and a restart may retry it.

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

from kalpamani.common.errors import SafetyViolationError

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


def classify_halt(error: BaseException | None) -> HaltKind:
    """Decide whether a halt must survive a restart.

    A :class:`SafetyViolationError` means durable state or broker truth is
    contradictory: an unprotected position, a reconciliation mismatch, a session
    that is not the armed account, arm evidence that disagrees with itself. None
    of those get better by restarting, and all of them need a human. Everything
    else -- a transport error, an unexpected runtime fault -- halts the session
    and may be retried.
    """
    if isinstance(error, SafetyViolationError):
        return HaltKind.MANUAL_CLEARANCE_REQUIRED
    return HaltKind.SESSION


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


def halt_state_path(storage_root: Path) -> Path:
    return storage_root / "phase2_operational_halt.json"


__all__ = [
    "HALT_SCHEMA_VERSION",
    "HaltKind",
    "HaltStore",
    "HaltStoreError",
    "JsonHaltStore",
    "OperationalHalt",
    "classify_halt",
    "halt_state_path",
]
