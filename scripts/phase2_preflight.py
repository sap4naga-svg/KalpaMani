"""Phase 2 pre-launch preflight. Run immediately before every deployment.

Phase 2 can place a real order, so this checks more than Phase 1's did:

1. the runtime workspace is git-ignored, so credentials and durable trade state
   can never be committed;
2. the tracked algorithm **and the `kalpamani` package** are synced into the
   runtime workspace -- the package ships so the container runs the same safety
   code the tests cover, instead of a hand-copied duplicate that can drift;
3. the algorithm contains only the order APIs Phase 2 permits, and none of the
   forbidden ones;
4. durable trade state is reported, so an unresolved prior run is visible before
   anything is armed;
5. the arm state is reported explicitly.

Exits non-zero if any check fails. Contacts no broker and places no order.

Usage:
    python scripts/phase2_preflight.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalpamani.broker.account import BrokerAccountMode, redact_account_id
from kalpamani.common.capital import DEFAULT_STRATEGY_CAPITAL_USD
from kalpamani.common.settings import LIVE_TRADING_HARD_DISABLED
from kalpamani.execution.envelope import (
    PHASE2_CONFIRMATION_PHRASE,
    PHASE2_MAX_NOTIONAL_USD,
    PHASE2_QUANTITY,
    PHASE2_SYMBOL,
)
from kalpamani.execution.lifecycle import is_terminal
from kalpamani.execution.state_store import JsonTradeStateStore, StateStoreError

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = "phase2_order_lifecycle"

TRACKED_PROJECT = REPO_ROOT / "lean" / "projects" / PROJECT_NAME
PACKAGE_SOURCE = REPO_ROOT / "src" / "kalpamani"
RUNTIME_WORKSPACE = REPO_ROOT / ".runtime" / "lean"
RUNTIME_PROJECT = RUNTIME_WORKSPACE / PROJECT_NAME
RUNTIME_PACKAGE = RUNTIME_PROJECT / "kalpamani"
RUNTIME_STATE = RUNTIME_WORKSPACE / "storage" / PROJECT_NAME / "phase2_trade_state.json"

SYNCED_FILES = ("main.py",)

#: Order APIs Phase 2 is allowed to call, and nothing else.
PERMITTED_ORDER_APIS = ("market_order(", "stop_market_order(")

#: Order APIs that must never appear: account-wide actions, strategy sizing, or
#: anything that could establish a position other than the single entry.
FORBIDDEN_ORDER_APIS = (
    "liquidate(",
    "set_holdings(",
    "limit_order(",
    "market_on_open_order(",
    "market_on_close_order(",
    "limit_if_touched_order(",
    "trailing_stop_order(",
    "combo_market_order(",
    "exercise_option(",
    "calculate_order_quantity(",
    "add_option(",
    "add_future(",
    "add_forex(",
    "add_crypto(",
    "add_universe(",
)


def _fail(message: str) -> None:
    print(f"  FAIL: {message}")


def is_git_ignored(path: Path) -> bool:
    result = subprocess.run(  # noqa: S603
        ["git", "check-ignore", "-q", str(path)],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def git_sees(path: Path) -> bool:
    result = subprocess.run(  # noqa: S603
        ["git", "status", "--porcelain", "--untracked-files=all", "--", str(path)],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


def check_runtime_isolation() -> bool:
    print("[1/5] Runtime workspace isolation")
    ok = True
    runtime_root = REPO_ROOT / ".runtime"
    if is_git_ignored(runtime_root):
        print(f"  OK  : {runtime_root.relative_to(REPO_ROOT)} is git-ignored")
    else:
        _fail(f"{runtime_root} is NOT git-ignored")
        ok = False
    if git_sees(runtime_root):
        _fail("git status can see .runtime/")
        ok = False
    else:
        print("  OK  : git status cannot see .runtime/")
    for probe in (RUNTIME_STATE, RUNTIME_PROJECT / "config.json"):
        if is_git_ignored(probe):
            print(f"  OK  : {probe.relative_to(REPO_ROOT)} would be ignored")
        else:
            _fail(f"{probe} would NOT be ignored")
            ok = False
    return ok


def sync_project() -> bool:
    print("[2/5] Sync tracked source -> untracked runtime workspace")
    if not TRACKED_PROJECT.is_dir():
        _fail(f"tracked project missing: {TRACKED_PROJECT}")
        return False

    RUNTIME_PROJECT.mkdir(parents=True, exist_ok=True)
    for name in SYNCED_FILES:
        source = TRACKED_PROJECT / name
        if not source.is_file():
            _fail(f"expected tracked file missing: {source}")
            return False
        shutil.copy2(source, RUNTIME_PROJECT / name)
        print(f"  OK  : {name}")

    # Ship the real package so the container runs the same safety code the unit
    # tests cover. Phase 1 duplicated a single constant and needed a drift test;
    # Phase 2's logic is far too important to copy by hand.
    if RUNTIME_PACKAGE.exists():
        shutil.rmtree(RUNTIME_PACKAGE)
    shutil.copytree(
        PACKAGE_SOURCE, RUNTIME_PACKAGE, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    module_count = len(list(RUNTIME_PACKAGE.rglob("*.py")))
    print(f"  OK  : kalpamani package ({module_count} modules) shipped into the project")
    print("  NOTE: the runtime copy is a build artifact. Edit tracked source only.")
    return True


def check_order_surface() -> bool:
    print("[3/5] Order-surface static check")
    source = (TRACKED_PROJECT / "main.py").read_text(encoding="utf-8")
    code_lines = [ln for ln in source.splitlines() if not ln.lstrip().startswith("#")]
    body = "\n".join(code_lines)

    ok = True
    for forbidden in FORBIDDEN_ORDER_APIS:
        if forbidden in body:
            _fail(f"forbidden order API present: {forbidden}")
            ok = False
    if ok:
        print(f"  OK  : none of {len(FORBIDDEN_ORDER_APIS)} forbidden order APIs present")

    found = [api for api in PERMITTED_ORDER_APIS if api in body]
    print(f"  OK  : permitted order APIs in use: {', '.join(found) or '(none)'}")

    entry_calls = body.count("self.market_order(")
    print(f"  INFO: self.market_order( call sites: {entry_calls} (entry + exit)")
    if entry_calls > 2:
        _fail(f"{entry_calls} market_order call sites; Phase 2 allows at most 2 (entry, exit)")
        ok = False
    return ok


def check_durable_state() -> bool:
    print("[4/5] Durable trade state")
    if not RUNTIME_STATE.exists():
        print(f"  OK  : no prior trade state at {RUNTIME_STATE.relative_to(REPO_ROOT)}")
        print("        (a first armed run will create it)")
        return True
    try:
        records = JsonTradeStateStore(RUNTIME_STATE).all_records()
    except StateStoreError as exc:
        _fail(f"trade state is unreadable: {exc}")
        return False

    if not records:
        print("  OK  : trade state present but empty")
        return True

    ok = True
    for record in records:
        status = "TERMINAL" if is_terminal(record.state) else "UNRESOLVED"
        print(f"  INFO: {status}: {record.describe()}")
        if not is_terminal(record.state):
            _fail(
                f"unresolved prior trade in state {record.state.value}. Resolve it before "
                "arming: it may still hold a position or a working order."
            )
            ok = False
    return ok


def print_checklist() -> None:
    print("[5/5] Launch checklist -- review before deploying")
    config = RUNTIME_PROJECT / "config.json"
    armed = "NO (read/reconcile only)"
    account_line = "(not set)"
    if config.is_file():
        import json

        params = json.loads(config.read_text(encoding="utf-8")).get("parameters", {})
        if (
            str(params.get("phase2_test_mode", "")).lower() == "true"
            and str(params.get("explicit_execution_arm", "")).lower() == "true"
            and params.get("phase2_confirmation") == PHASE2_CONFIRMATION_PHRASE
        ):
            armed = "YES -- an entry order may be placed"
        account_id = str(params.get("ibkr_account_id", ""))
        if account_id:
            mode = BrokerAccountMode.classify(account_id)
            account_line = f"{redact_account_id(account_id)}  mode={mode.value}"

    rows = [
        ("Project (tracked source)", str(TRACKED_PROJECT.relative_to(REPO_ROOT))),
        ("Project (runtime copy)", str(RUNTIME_PROJECT.relative_to(REPO_ROOT))),
        ("Durable state path", str(RUNTIME_STATE.relative_to(REPO_ROOT))),
        ("Runtime git-ignored", "YES" if is_git_ignored(RUNTIME_PROJECT) else "NO -- ABORT"),
        ("Brokerage", "Interactive Brokers (PAPER only)"),
        ("Account (redacted)", account_line),
        ("Permitted symbol", PHASE2_SYMBOL),
        ("Permitted side", "BUY (long only)"),
        ("Permitted quantity", f"{PHASE2_QUANTITY} (exact, not a ceiling)"),
        ("Notional ceiling", f"USD {PHASE2_MAX_NOTIONAL_USD}"),
        ("Max intents / entries", "1 / 1"),
        ("EXECUTION ARM", armed),
        ("Strategy capital", f"USD {DEFAULT_STRATEGY_CAPITAL_USD:,}"),
        ("Live trading hard-disabled", str(LIVE_TRADING_HARD_DISABLED)),
    ]
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {label.ljust(width)} : {value}")


def main() -> int:
    print("=" * 78)
    print("KalpaMani Phase 2 preflight -- CONTROLLED IBKR PAPER ORDER LIFECYCLE")
    print("=" * 78)

    checks = [check_runtime_isolation(), sync_project()]
    checks.append(check_order_surface())
    checks.append(check_durable_state())
    print()
    print_checklist()
    print()

    if all(checks):
        print("PREFLIGHT PASSED.")
        print("If the arm shows NO, deployment is read/reconcile only and cannot order.")
        print("Reminder: enter IBKR credentials only into LEAN's own interactive prompts.")
        return 0
    print("PREFLIGHT FAILED. Do not deploy.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
