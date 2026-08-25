"""Arm or disarm the Phase 2 execution gate. Explicit, one-time, human-only.

Normal Phase 2 startup is **read/reconcile only**. This script is the single
deliberate act that opens the order path, and it exists as a separate step so
that arming can never be a side effect of deploying.

Arming requires the operator to type the confirmation phrase exactly. A boolean
flag can be set by a stray environment variable or a copied command line; a
specific phrase cannot be arrived at by accident.

The arm is written into the **untracked** runtime project config. It is consumed
the moment a trade intent is authorised, and the consumption is recorded durably
-- so a restart finds the arm spent and reconciles instead of re-submitting.

Usage:
    python scripts/phase2_arm.py --status
    python scripts/phase2_arm.py --arm --account-id DU1234567
    python scripts/phase2_arm.py --disarm
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalpamani.broker.account import BrokerAccountMode, redact_account_id
from kalpamani.execution.envelope import (
    PHASE2_CONFIRMATION_PHRASE,
    PHASE2_MAX_NOTIONAL_USD,
    PHASE2_QUANTITY,
    PHASE2_SYMBOL,
    describe_envelope,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = "phase2_order_lifecycle"
RUNTIME_PROJECT = REPO_ROOT / ".runtime" / "lean" / PROJECT_NAME
RUNTIME_CONFIG = RUNTIME_PROJECT / "config.json"

ARM_KEYS = (
    "phase2_test_mode",
    "explicit_execution_arm",
    "phase2_confirmation",
    "phase2_exit_requested",
    "ibkr_account_id",
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


def show_status() -> int:
    config = load_config()
    params = dict(config.get("parameters", {}))  # type: ignore[arg-type]
    armed = (
        str(params.get("phase2_test_mode", "")).lower() == "true"
        and str(params.get("explicit_execution_arm", "")).lower() == "true"
        and params.get("phase2_confirmation") == PHASE2_CONFIRMATION_PHRASE
    )
    account_id = str(params.get("ibkr_account_id", ""))
    print("=" * 78)
    print("KalpaMani Phase 2 execution arm")
    print("=" * 78)
    print(f"  runtime config      : {RUNTIME_CONFIG.relative_to(REPO_ROOT)}")
    print(f"  git-ignored         : {'YES' if is_git_ignored(RUNTIME_CONFIG) else 'NO -- ABORT'}")
    print(f"  ARMED               : {'YES' if armed else 'NO (read/reconcile only)'}")
    print(f"  exit requested      : {params.get('phase2_exit_requested', 'false')}")
    if account_id:
        mode = BrokerAccountMode.classify(account_id)
        print(f"  account (redacted)  : {redact_account_id(account_id)}")
        print(f"  account mode        : {mode.value}{'' if mode.is_paper else '  <-- NOT PAPER'}")
    print(f"  envelope            : {describe_envelope()}")
    print("=" * 78)
    return 0


def arm(account_id: str, confirmation: str) -> int:
    if confirmation != PHASE2_CONFIRMATION_PHRASE:
        print("REFUSED: confirmation phrase does not match.")
        print(f'Type exactly:  --confirm "{PHASE2_CONFIRMATION_PHRASE}"')
        return 1

    mode = BrokerAccountMode.classify(account_id)
    if not mode.is_paper:
        print(
            f"REFUSED: account {redact_account_id(account_id)} classifies as {mode.value}. "
            "Phase 2 is PAPER only, and an ambiguous account is an abort condition."
        )
        return 1

    config = load_config()
    params = dict(config.get("parameters", {}))  # type: ignore[arg-type]
    params.update(
        {
            "phase2_test_mode": "true",
            "explicit_execution_arm": "true",
            "phase2_confirmation": PHASE2_CONFIRMATION_PHRASE,
            "phase2_exit_requested": "false",
            "ibkr_account_id": account_id,
        }
    )
    config["parameters"] = params
    save_config(config)

    print("=" * 78)
    print("PHASE 2 ARMED -- ONE TIME")
    print("=" * 78)
    print(f"  account (redacted) : {redact_account_id(account_id)}  mode={mode.value}")
    print(f"  permitted order    : BUY {PHASE2_QUANTITY} {PHASE2_SYMBOL}")
    print(f"  notional ceiling   : USD {PHASE2_MAX_NOTIONAL_USD}")
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
        if key != "ibkr_account_id":
            params.pop(key, None)
    if request_exit:
        params["phase2_exit_requested"] = "true"
        params["phase2_test_mode"] = "true"
    config["parameters"] = params
    save_config(config)
    print("Phase 2 DISARMED." + ("  Exit requested for the next cycle." if request_exit else ""))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Arm/disarm the Phase 2 execution gate.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true", help="show the current arm state")
    group.add_argument("--arm", action="store_true", help="arm the one-time execution gate")
    group.add_argument("--disarm", action="store_true", help="clear the arm")
    group.add_argument(
        "--request-exit",
        action="store_true",
        help="clear the arm and request the controlled exit on the next cycle",
    )
    parser.add_argument("--account-id", default="", help="IBKR PAPER account id (DU/DF/DI...)")
    parser.add_argument("--confirm", default="", help="the exact confirmation phrase")
    args = parser.parse_args()

    if args.status:
        return show_status()
    if args.disarm:
        return disarm()
    if args.request_exit:
        return disarm(request_exit=True)
    if not args.account_id:
        print("REFUSED: --account-id is required to arm, so paper mode can be proven.")
        return 1
    return arm(args.account_id, args.confirm)


if __name__ == "__main__":
    raise SystemExit(main())
