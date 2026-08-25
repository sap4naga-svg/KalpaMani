"""Arm or disarm the Phase 2 execution gate. Explicit, one-time, human-only.

Normal Phase 2 startup is **read/reconcile only**. This script is the single
deliberate act that opens the order path, and it exists as a separate step so
that arming can never be a side effect of deploying.

Arming requires the operator to type the confirmation phrase exactly. A boolean
flag can be set by a stray environment variable or a copied command line; a
specific phrase cannot be arrived at by accident.

The account is read from the LEAN deployment configuration, never typed by the
operator, so the armed account and the deployed account cannot be two
independent values that disagree.

The arm is written into the **untracked** runtime project config. It is consumed
the moment a trade intent is authorised, and the consumption is recorded durably
-- so a restart finds the arm spent and reconciles instead of re-submitting.

Usage:
    python scripts/phase2_arm.py --status
    python scripts/phase2_arm.py --arm --run 2 --confirm "ARM PHASE2 PAPER BUY 1 SPY"
    python scripts/phase2_arm.py --disarm
    python scripts/phase2_arm.py --clear-halt --run 1 --confirm "CLEAR PHASE2 HALT"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalpamani.broker.account import redact_account_id
from kalpamani.execution.envelope import (
    PHASE2_CONFIRMATION_PHRASE,
    PHASE2_FILL_NOTIONAL_TOLERANCE_USD,
    PHASE2_MAX_REFERENCE_NOTIONAL_USD,
    PHASE2_QUANTITY,
    PHASE2_SYMBOL,
    certification_identity,
    describe_envelope,
)
from kalpamani.execution.halt import (
    HaltClearanceError,
    JsonHaltStore,
    assert_halt_belongs_to,
    assert_halt_clearable,
    halt_state_path,
)
from kalpamani.execution.identity import TradeIdentity  # noqa: F401  (re-exported for tests)
from kalpamani.execution.lifecycle import is_terminal
from kalpamani.execution.session import (
    IB_ACCOUNT_KEY,
    IB_TRADING_MODE_KEY,
    BrokerSessionEvidence,
    SessionVerificationError,
    verify_paper_session,
)
from kalpamani.execution.state_store import JsonTradeStateStore, StateStoreError

#: Parameter that binds the arm to one specific brokerage account. Stored as a
#: fingerprint, never as a raw account id, and REQUIRED for the arm to count.
ACCOUNT_FINGERPRINT_KEY = "phase2_account_fingerprint"

#: Parameter naming the certification RUN this deployment belongs to. Required
#: for an arm, and never defaulted: run 1 failed, and "just use the next number"
#: is exactly the automatic retry Phase 2 must not have.
RUN_NUMBER_KEY = "phase2_run_number"

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = "phase2_order_lifecycle"
RUNTIME_PROJECT = REPO_ROOT / ".runtime" / "lean" / PROJECT_NAME
RUNTIME_CONFIG = RUNTIME_PROJECT / "config.json"
RUNTIME_STORAGE = REPO_ROOT / ".runtime" / "lean" / "storage"
RUNTIME_STATE = RUNTIME_STORAGE / "phase2_trade_state.json"

#: Clearing a durable safety halt is a deliberate human act, so it takes its own
#: phrase. A halt is raised when durable state or broker truth is contradictory;
#: clearing it asserts that a human has reconciled against the broker.
CLEAR_HALT_PHRASE = "CLEAR PHASE2 HALT"
#: The deployment configuration. THE single source of the account identity --
#: the operator never types it, so the arm and the deployment cannot be two
#: independent values that disagree.
LEAN_DEPLOYMENT_CONFIG = REPO_ROOT / ".runtime" / "lean" / "lean.json"

ARM_KEYS = (
    "phase2_test_mode",
    "explicit_execution_arm",
    "phase2_confirmation",
    "phase2_exit_requested",
    ACCOUNT_FINGERPRINT_KEY,
)


def is_git_ignored(path: Path) -> bool:
    result = subprocess.run(  # noqa: S603
        ["git", "check-ignore", "-q", str(path)],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def load_config() -> dict[str, object]:
    if not RUNTIME_CONFIG.is_file():
        return {"algorithm-language": "Python", "parameters": {}}
    return json.loads(RUNTIME_CONFIG.read_text(encoding="utf-8"))


def save_config(config: dict[str, object]) -> None:
    if not is_git_ignored(RUNTIME_CONFIG):
        raise SystemExit(
            f"REFUSING: {RUNTIME_CONFIG} is not git-ignored. The arm must never be committable."
        )
    RUNTIME_PROJECT.mkdir(parents=True, exist_ok=True)
    RUNTIME_CONFIG.write_text(json.dumps(config, indent=4) + "\n", encoding="utf-8")


def selected_run(params: dict[str, object]) -> int | None:
    """The certification run this config selects, or None if unusable.

    Returns None rather than a default. A missing or malformed run selector must
    make the arm INVALID, not silently mean run 1 -- run 1 is a failed
    certification and its identity is evidence, not a fallback.
    """
    raw = str(params.get(RUN_NUMBER_KEY, "") or "").strip()
    if not raw:
        return None
    try:
        run = int(raw)
    except ValueError:
        return None
    return run if run >= 1 else None


def load_trade_record_for_run(run_number: int):
    """The durable record for one certification run, or None. Corrupt state raises."""
    if not RUNTIME_STATE.exists():
        return None
    identity = certification_identity(run_number)
    return JsonTradeStateStore(RUNTIME_STATE).get(identity.trade_intent_id)


def show_status() -> int:
    config = load_config()
    params = dict(config.get("parameters", {}))  # type: ignore[arg-type]
    fingerprint = str(params.get(ACCOUNT_FINGERPRINT_KEY, "") or "")
    run = selected_run(params)
    # An arm without an account binding, or without a usable run selector, is
    # NOT armed. Reporting it as armed would be fail-open, and would contradict
    # what the runbook promises.
    armed = (
        str(params.get("phase2_test_mode", "")).lower() == "true"
        and str(params.get("explicit_execution_arm", "")).lower() == "true"
        and params.get("phase2_confirmation") == PHASE2_CONFIRMATION_PHRASE
        and bool(fingerprint)
        and run is not None
    )
    print("=" * 78)
    print("KalpaMani Phase 2 execution arm")
    print("=" * 78)
    print(f"  runtime config      : {RUNTIME_CONFIG.relative_to(REPO_ROOT)}")
    print(f"  git-ignored         : {'YES' if is_git_ignored(RUNTIME_CONFIG) else 'NO -- ABORT'}")
    print(f"  ARMED               : {'YES' if armed else 'NO (read/reconcile only)'}")
    print(f"  certification run   : {run if run is not None else 'NOT SELECTED -- arm invalid'}")
    print(f"  exit requested      : {params.get('phase2_exit_requested', 'false')}")
    # Presence only. The binding digest is sensitive (see
    # session.account_fingerprint) and is never printed, logged or committed.
    binding = "present" if fingerprint else "ABSENT -- arm cannot be valid"
    print(f"  account binding     : {binding}")
    halt = JsonHaltStore(halt_state_path(RUNTIME_STORAGE)).get()
    print(f"  operational halt    : {halt.describe() if halt else 'none'}")
    print(f"  envelope            : {describe_envelope()}")
    print("=" * 78)
    return 0


def deployment_evidence() -> BrokerSessionEvidence | None:
    """Read the brokerage account from the DEPLOYMENT configuration.

    The operator never supplies this. Deriving it from the same file the engine
    uses is what makes an arm/deployment mismatch structurally impossible.
    """
    if not LEAN_DEPLOYMENT_CONFIG.is_file():
        return None
    raw = json.loads(LEAN_DEPLOYMENT_CONFIG.read_text(encoding="utf-8"))
    account_id = str(raw.get(IB_ACCOUNT_KEY, "") or "")
    if not account_id:
        return None
    return BrokerSessionEvidence(
        account_id=account_id,
        trading_mode=str(raw.get(IB_TRADING_MODE_KEY, "") or ""),
        source=str(LEAN_DEPLOYMENT_CONFIG),
    )


def arm(confirmation: str, run_number: int | None) -> int:
    if run_number is None:
        print("REFUSED: --run is required for --arm.")
        print("  The certification run is a deliberate choice, never a default and never")
        print("  auto-incremented. Run 1 is a FAILED certification whose identity is")
        print("  evidence; a new attempt needs its own run number.")
        print('  Example:  --arm --run 2 --confirm "ARM PHASE2 PAPER BUY 1 SPY"')
        return 1
    if run_number < 1:
        print(f"REFUSED: --run must be a positive integer, got {run_number}.")
        return 1

    if confirmation != PHASE2_CONFIRMATION_PHRASE:
        print("REFUSED: confirmation phrase does not match.")
        print(f'Type exactly:  --confirm "{PHASE2_CONFIRMATION_PHRASE}"')
        return 1

    # Clearing a halt and authorising a run are TWO human acts, in that order.
    # Pre-arming under a halt collapses them: the halt gets cleared later and the
    # next deployment is already armed, which is not the sequence anyone agreed
    # to. Runtime would still refuse to trade -- but the arm should not exist.
    halt = JsonHaltStore(halt_state_path(RUNTIME_STORAGE)).get()
    if halt is not None:
        print(f"REFUSED: a durable operational halt is in force ({halt.describe()}).")
        print(f"  reason: {halt.reason}")
        print("  Resolve it and clear it deliberately FIRST, then authorise a run.")
        print("  Clearing a halt and arming a run are two separate acts, in that order.")
        return 1

    evidence = deployment_evidence()
    if evidence is None:
        print(
            "REFUSED: no brokerage account configured in the deployment "
            f"({LEAN_DEPLOYMENT_CONFIG}). Configure and verify the IBKR PAPER deployment "
            "before arming; the arm derives the account from it and never from you."
        )
        return 1

    try:
        verify_paper_session(evidence)
    except SessionVerificationError as exc:
        print(f"REFUSED: {exc}")
        return 1

    # Every EARLIER run must be terminal before a new one is authorised. An
    # unresolved run may still hold a position or a working order, and arming on
    # top of it is the second entry this whole design exists to prevent.
    try:
        unresolved = [
            r
            for r in (
                JsonTradeStateStore(RUNTIME_STATE).all_records() if RUNTIME_STATE.exists() else []
            )
            if not is_terminal(r.state)
        ]
    except StateStoreError as exc:
        print(f"REFUSED: durable trade state is unreadable: {exc}")
        return 1
    if unresolved:
        print(f"REFUSED: {len(unresolved)} earlier certification run(s) are not terminal.")
        for record in unresolved:
            print(f"  {record.trade_intent_id}: {record.state.value}")
        print("  Resolve them before authorising a new run.")
        return 1

    existing = load_trade_record_for_run(run_number)
    if existing is not None:
        print(
            f"REFUSED: run {run_number} already has a durable record "
            f"(state={existing.state.value}). Each run is armed once; choose a new run number."
        )
        return 1

    account_id = evidence.account_id
    mode = evidence.mode
    fingerprint = evidence.fingerprint

    config = load_config()
    params = dict(config.get("parameters", {}))  # type: ignore[arg-type]
    params.update(
        {
            "phase2_test_mode": "true",
            "explicit_execution_arm": "true",
            "phase2_confirmation": PHASE2_CONFIRMATION_PHRASE,
            "phase2_exit_requested": "false",
            # A fingerprint, not the account id. The runtime requires it and
            # aborts if it is missing or does not match the deployment.
            ACCOUNT_FINGERPRINT_KEY: fingerprint,
            RUN_NUMBER_KEY: str(run_number),
        }
    )
    config["parameters"] = params
    save_config(config)

    print("=" * 78)
    print("PHASE 2 ARMED -- ONE TIME")
    print("=" * 78)
    print(f"  certification run  : {run_number}")
    print(f"  session            : {evidence.describe()}")
    print(f"  account (redacted) : {redact_account_id(account_id)}  mode={mode.value}")
    print(f"  permitted order    : BUY {PHASE2_QUANTITY} {PHASE2_SYMBOL}")
    print(f"  pre-submission cap : USD {PHASE2_MAX_REFERENCE_NOTIONAL_USD} (reference price)")
    print(
        f"  fill tolerance     : USD {PHASE2_FILL_NOTIONAL_TOLERANCE_USD} "
        "(market order: not enforceable)"
    )
    print("  intents / entries  : 1 / 1")
    print()
    print("  The arm is consumed the moment a trade intent is authorised, and the")
    print("  consumption is recorded durably. A restart will NOT re-arm.")
    print("  Disarm with: python scripts/phase2_arm.py --disarm")
    print("=" * 78)
    return 0


def disarm(request_exit: bool = False) -> int:
    config = load_config()
    params = dict(config.get("parameters", {}))  # type: ignore[arg-type]
    for key in ARM_KEYS:
        params.pop(key, None)
    if request_exit:
        params["phase2_exit_requested"] = "true"
        params["phase2_test_mode"] = "true"
    config["parameters"] = params
    save_config(config)
    print("Phase 2 DISARMED." + ("  Exit requested for the next cycle." if request_exit else ""))
    return 0


def clear_halt(confirmation: str, run_number: int | None) -> int:
    """Clear a durable operational halt. Only ever a deliberate human act.

    A safety halt means something contradictory happened: an unprotected
    position, a reconciliation mismatch, an event from the wrong account.
    Clearing it asserts that a human has looked at the broker and resolved it.
    Redeploying does not clear it, and neither does restarting.
    """
    store = JsonHaltStore(halt_state_path(RUNTIME_STORAGE))
    halt = store.get()
    if halt is None:
        print("No durable operational halt is in force. Nothing to clear.")
        return 0

    print("=" * 78)
    print("Durable operational halt in force")
    print("=" * 78)
    print(f"  {halt.describe()}")
    print(f"  reason : {halt.reason}")
    print()

    # The gates run FIRST. The phrase is an assertion of intent, not of fact,
    # and on its own it must never make an unsafe trade resumable.
    # NO fallback to the deployment config. An earlier version read the run from
    # `phase2_run_number` when --run was omitted, which made the selector
    # effectively optional -- and cleared a halt during a smoke test that had
    # passed no run at all. Clearing a halt states which run you mean, out loud,
    # every time.
    if run_number is None:
        print("REFUSED: --run is required to clear a halt.")
        print("  A halt belongs to one certification run. Clearing it without saying which")
        print("  would validate whichever run happened to be selected -- and a resolved")
        print("  run would then authorise clearing a halt protecting a live one.")
        print('  Example:  --clear-halt --run 1 --confirm "CLEAR PHASE2 HALT"')
        return 1

    try:
        evidence = deployment_session_evidence()
        record = load_trade_record_for_run(run_number)
        # The binding comes FIRST: the gates below inspect `record`, so they are
        # only meaningful once we know the halt is this run's halt.
        any_records = bool(
            JsonTradeStateStore(RUNTIME_STATE).all_records() if RUNTIME_STATE.exists() else []
        )
        assert_halt_belongs_to(halt, record, any_records_exist=any_records)
        caveats = assert_halt_clearable(record, evidence)
    except (HaltClearanceError, SessionVerificationError, StateStoreError) as exc:
        print(str(exc))
        print()
        print("The halt is LEFT IN FORCE. Resolve the condition above before retrying.")
        return 1

    print("Pre-clearance checks passed:")
    print(f"  certification run   : {run_number}")
    print(f"  deployment session  : {evidence.describe()}")
    print(f"  trade record        : {record.describe() if record else '(none)'}")
    for caveat in caveats:
        print(f"  NOTE: {caveat}")
    print()

    if confirmation != CLEAR_HALT_PHRASE:
        print(f'REFUSED: clearing a halt requires --confirm "{CLEAR_HALT_PHRASE}" exactly.')
        print("Reconcile the position and the open orders against IBKR by hand FIRST.")
        return 1

    store.clear()
    print("Halt cleared -- the DEPLOYMENT latch only.")
    print("The trade lifecycle is unchanged: a FAILED trade stays FAILED, and the next")
    print("deployment still re-proves the account and reconciles against the broker before")
    print("it does anything at all.")
    return 0


def deployment_session_evidence() -> BrokerSessionEvidence:
    """Session evidence from LEAN's own deployment configuration."""
    raw = json.loads(LEAN_DEPLOYMENT_CONFIG.read_text(encoding="utf-8"))
    account_id = str(raw.get(IB_ACCOUNT_KEY, "") or "")
    if not account_id:
        raise SessionVerificationError(
            f"{IB_ACCOUNT_KEY!r} is absent from the deployment configuration, so a halt "
            "cannot be checked against the account it protects."
        )
    return BrokerSessionEvidence(
        account_id=account_id,
        trading_mode=str(raw.get(IB_TRADING_MODE_KEY, "") or ""),
        source=str(LEAN_DEPLOYMENT_CONFIG),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Arm/disarm the Phase 2 execution gate.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true", help="show the current arm state")
    group.add_argument("--arm", action="store_true", help="arm the one-time execution gate")
    group.add_argument("--disarm", action="store_true", help="clear the arm")
    group.add_argument(
        "--clear-halt",
        action="store_true",
        help="clear a durable operational halt (requires the exact phrase)",
    )
    group.add_argument(
        "--request-exit",
        action="store_true",
        help="clear the arm and request the controlled exit on the next cycle",
    )
    parser.add_argument("--confirm", default="", help="the exact confirmation phrase")
    parser.add_argument(
        "--run",
        type=int,
        default=None,
        help="certification run number (REQUIRED for --arm and --clear-halt)",
    )
    args = parser.parse_args()

    if args.status:
        return show_status()
    if args.clear_halt:
        return clear_halt(args.confirm, args.run)
    if args.disarm:
        return disarm()
    if args.request_exit:
        return disarm(request_exit=True)
    return arm(args.confirm, args.run)


if __name__ == "__main__":
    raise SystemExit(main())
