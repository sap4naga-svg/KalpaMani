"""Proof that the connected brokerage session is PAPER, plus arm durability.

**Configuration alone is not evidence.** An operator-typed account id that merely
*looks* like a paper id proves nothing about the session LEAN actually opened.
This module ties the arm to the brokerage configuration the deployment really
uses, so the two cannot be independent values that disagree.

Where the evidence comes from
-----------------------------
LEAN mounts its merged runtime configuration inside the container at
``/Lean/Launcher/bin/Debug/config.json`` (``LEAN_ROOT_PATH/config.json``). That
file carries the brokerage settings the engine is actually running with:

* ``ib-account``       -- the account the IBKR brokerage connects to
* ``ib-trading-mode``  -- ``paper`` or ``live``, which **LEAN derives itself**
  from the account id by regex (``^df|^du|^di`` -> paper, ``^f|^i|^u`` -> live)

Two independent signals, both from the deployment rather than from us.

Known limitation (documented rather than papered over)
------------------------------------------------------
``QCAlgorithm`` exposes **no** brokerage account identifier. Verified against the
installed QuantConnect stubs: the account id lives on ``LiveNodePacket``
(``brokerage_data``), which the algorithm cannot reach. So the strongest
in-algorithm evidence available is the deployment configuration above, and the
pre-launch preflight independently verifies the same source before deployment.

Account identifiers are treated as sensitive. Only a **fingerprint** is stored or
compared; the raw id is never persisted or logged.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from kalpamani.broker.account import BrokerAccountMode, redact_account_id
from kalpamani.common.errors import SafetyViolationError

#: Where LEAN mounts the merged runtime configuration inside the container.
LEAN_CONTAINER_CONFIG_PATH = Path("/Lean/Launcher/bin/Debug/config.json")

#: Deployment config keys that carry brokerage session truth.
IB_ACCOUNT_KEY = "ib-account"
IB_TRADING_MODE_KEY = "ib-trading-mode"

#: The only trading mode Phase 2 may run against.
REQUIRED_TRADING_MODE = "paper"

_FINGERPRINT_LEN = 16


class SessionVerificationError(SafetyViolationError):
    """The connected brokerage session could not be proven to be PAPER."""


class ArmReceiptError(SafetyViolationError):
    """The one-time arm receipt is missing, contradictory, or already consumed."""


def account_fingerprint(account_id: str) -> str:
    """Stable, non-reversible fingerprint of an account id.

    Comparisons and durable records use this, never the raw identifier, so an
    account id is not spread across state files and logs.
    """
    normalised = account_id.strip().upper()
    if not normalised:
        raise SessionVerificationError(
            "Cannot fingerprint an empty account id. An absent account id is not evidence "
            "of anything, least of all that the session is paper."
        )
    return hashlib.sha256(f"v1|account|{normalised}".encode()).hexdigest()[:_FINGERPRINT_LEN]


@dataclass(frozen=True, slots=True)
class BrokerSessionEvidence:
    """What the deployment itself says about the brokerage session."""

    account_id: str
    trading_mode: str
    source: str

    @property
    def fingerprint(self) -> str:
        return account_fingerprint(self.account_id)

    @property
    def mode(self) -> BrokerAccountMode:
        return BrokerAccountMode.classify(self.account_id)

    @property
    def trading_mode_is_explicit(self) -> bool:
        """Whether the deployment stated the trading mode outright.

        ``ib-trading-mode`` is an *internal-input* in the LEAN CLI: it is derived
        at deploy time from the account id and injected into the container
        config, so it is present inside the container but legitimately absent
        from the host-side ``lean.json``.
        """
        return bool(self.trading_mode.strip())

    @property
    def effective_trading_mode(self) -> str:
        """The stated trading mode, or the one derived from the account id.

        Derivation uses the same rule LEAN uses (``^df|^du|^di`` -> paper), so a
        derived value agrees with what the engine will conclude. An account that
        classifies as UNKNOWN derives to ``"unknown"`` and therefore fails.
        """
        if self.trading_mode_is_explicit:
            return self.trading_mode.strip().lower()
        return self.mode.value

    def describe(self) -> str:
        """Log-safe. Redacted id, never the full identifier."""
        origin = "stated" if self.trading_mode_is_explicit else "derived-from-account-id"
        return (
            f"account={redact_account_id(self.account_id)} "
            f"fingerprint={self.fingerprint} "
            f"classified={self.mode.value} "
            f"trading_mode={self.effective_trading_mode!r} ({origin}) "
            f"source={self.source}"
        )


def load_session_evidence(config_path: Path = LEAN_CONTAINER_CONFIG_PATH) -> BrokerSessionEvidence:
    """Read brokerage session evidence from LEAN's own deployment configuration.

    Raises:
        SessionVerificationError: if the config is missing, unreadable, or lacks
            the brokerage keys. Absence is a failure, not a default.
    """
    if not config_path.is_file():
        raise SessionVerificationError(
            f"LEAN deployment configuration not found at {config_path}. Without it the "
            "brokerage session cannot be verified, so no order path may open."
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SessionVerificationError(
            f"LEAN deployment configuration at {config_path} is unreadable: {exc}."
        ) from exc

    account_id = str(raw.get(IB_ACCOUNT_KEY, "") or "")
    trading_mode = str(raw.get(IB_TRADING_MODE_KEY, "") or "")
    if not account_id:
        raise SessionVerificationError(
            f"{IB_ACCOUNT_KEY!r} is absent from the deployment configuration. The session "
            "cannot be tied to a known account, so Phase 2 must abort."
        )
    # `ib-trading-mode` may be absent: the LEAN CLI derives it at deploy time and
    # injects it into the container config. When absent we derive it ourselves
    # using LEAN's own rule, and say so in the evidence.
    return BrokerSessionEvidence(
        account_id=account_id, trading_mode=trading_mode, source=str(config_path)
    )


def verify_paper_session(
    evidence: BrokerSessionEvidence,
    *,
    expected_fingerprint: str | None = None,
) -> None:
    """Prove the session is paper and, if armed, that it is the armed account.

    Both signals must agree:

    1. LEAN's own ``ib-trading-mode`` must be ``paper``.
    2. The account id must classify as PAPER (never LIVE, never UNKNOWN).

    And when an arm exists, the account must be the *same* account the arm was
    issued against -- otherwise the arm and the deployment are two independent
    values that could disagree, which is precisely what this prevents.

    Raises:
        SessionVerificationError: on any disagreement.
    """
    if evidence.effective_trading_mode != REQUIRED_TRADING_MODE:
        origin = "stated" if evidence.trading_mode_is_explicit else "derived from the account id"
        raise SessionVerificationError(
            f"Deployment trading mode is {evidence.effective_trading_mode!r} ({origin}), but "
            f"Phase 2 requires {REQUIRED_TRADING_MODE!r}. Aborting before any order path opens."
        )
    if evidence.mode is not BrokerAccountMode.PAPER:
        raise SessionVerificationError(
            f"Deployment account classifies as {evidence.mode.value!r} "
            f"({redact_account_id(evidence.account_id)}). Phase 2 is PAPER only, and an "
            "unclassifiable account is an abort condition, not an assumption of safety."
        )
    if expected_fingerprint is not None and evidence.fingerprint != expected_fingerprint:
        raise SessionVerificationError(
            "Armed account does not match the deployed brokerage account "
            f"(armed={expected_fingerprint}, deployed={evidence.fingerprint}). The arm was "
            "issued against a different session; refusing to trade it."
        )


@dataclass(frozen=True, slots=True)
class ArmReceipt:
    """Durable evidence that a one-time arm was issued and/or consumed.

    Written to **two independent locations on different container mounts** so
    that losing one -- a mis-mounted object store, a wiped runtime directory --
    cannot silently look like a first run.
    """

    trade_intent_id: str
    account_fingerprint: str
    consumed: bool

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema": 1,
                "trade_intent_id": self.trade_intent_id,
                "account_fingerprint": self.account_fingerprint,
                "consumed": self.consumed,
            },
            indent=2,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, text: str) -> ArmReceipt:
        try:
            raw = json.loads(text)
            return cls(
                trade_intent_id=str(raw["trade_intent_id"]),
                account_fingerprint=str(raw["account_fingerprint"]),
                consumed=bool(raw["consumed"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ArmReceiptError(f"Arm receipt is malformed: {exc}.") from exc


def write_arm_receipt(receipt: ArmReceipt, paths: tuple[Path, ...]) -> None:
    """Persist the receipt to EVERY location, fsync it, and read all of them back.

    Redundancy that tolerates a partial write is not redundancy. So all
    configured locations must be written, flushed to disk, and read back
    identical before the arm counts as consumed. If any one of them fails, the
    arm is refused -- an arm whose consumption cannot be proven everywhere could
    be replayed after a restart.

    Raises:
        ArmReceiptError: if any location cannot be written, or if any readback
            disagrees with what was written.
    """
    if not paths:
        raise ArmReceiptError("No arm receipt locations configured; refusing to arm.")

    payload = receipt.to_json()
    for path in paths:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise ArmReceiptError(
                f"Could not write the arm receipt to {path}: {exc}. Refusing to arm: the "
                "two-location receipt is only redundant if BOTH locations are written."
            ) from exc

    # Read every location back and require exact agreement.
    for path in paths:
        try:
            readback = ArmReceipt.from_json(path.read_text(encoding="utf-8"))
        except (OSError, ArmReceiptError) as exc:
            raise ArmReceiptError(
                f"Arm receipt at {path} could not be read back after writing: {exc}. "
                "Refusing to arm."
            ) from exc
        if readback != receipt:
            raise ArmReceiptError(
                f"Arm receipt at {path} does not match what was written. Refusing to arm on "
                "receipts that disagree with themselves."
            )


def read_arm_receipts(paths: tuple[Path, ...]) -> list[ArmReceipt]:
    """Read every receipt that exists. Malformed receipts raise."""
    receipts: list[ArmReceipt] = []
    for path in paths:
        if path.is_file():
            receipts.append(ArmReceipt.from_json(path.read_text(encoding="utf-8")))
    return receipts


def assert_arm_available(
    paths: tuple[Path, ...],
    *,
    trade_state_present: bool,
) -> None:
    """Fail closed when a consumed arm exists but the trade record does not.

    This closes the failure mode where the arm parameters are still set, the
    trade-state file is lost (wrong mount, wiped directory), and the run would
    otherwise look like a virgin first run with a usable arm.

    Raises:
        ArmReceiptError: if a consumed receipt exists without a trade record, or
            if receipts disagree with one another.
    """
    receipts = read_arm_receipts(paths)
    if not receipts:
        return

    fingerprints = {r.account_fingerprint for r in receipts}
    intents = {r.trade_intent_id for r in receipts}
    consumed_flags = {r.consumed for r in receipts}
    if len(fingerprints) > 1 or len(intents) > 1 or len(consumed_flags) > 1:
        raise ArmReceiptError(
            "Arm receipts disagree with each other (fingerprint, intent or consumed flag). "
            "Contradictory arm evidence; failing closed rather than choosing one. In "
            "particular, one receipt saying the arm was consumed and another saying it was "
            "not is exactly the ambiguity that could permit a replay."
        )

    if any(r.consumed for r in receipts) and not trade_state_present:
        raise ArmReceiptError(
            "An arm receipt records that the Phase 2 arm was already CONSUMED, but no "
            "durable trade record was found. Refusing to treat this as a first run: the "
            "trade state is missing, not absent. Investigate the object-store mount and "
            "reconcile against the broker by hand before doing anything else."
        )


def arm_receipt_paths(storage_root: Path, project_root: Path) -> tuple[Path, ...]:
    """The two independent receipt locations, on different container mounts."""
    return (
        storage_root / "phase2_arm_receipt.json",
        project_root / ".phase2_arm_receipt.json",
    )


__all__ = [
    "IB_ACCOUNT_KEY",
    "IB_TRADING_MODE_KEY",
    "LEAN_CONTAINER_CONFIG_PATH",
    "REQUIRED_TRADING_MODE",
    "ArmReceipt",
    "ArmReceiptError",
    "BrokerSessionEvidence",
    "SessionVerificationError",
    "account_fingerprint",
    "arm_receipt_paths",
    "assert_arm_available",
    "load_session_evidence",
    "read_arm_receipts",
    "verify_paper_session",
    "write_arm_receipt",
]
