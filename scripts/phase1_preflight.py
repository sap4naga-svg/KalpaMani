"""Phase 1 pre-launch preflight: sync the LEAN project and prove it is safe to run.

Run this immediately before every `lean live deploy`. It:

1. proves the runtime workspace is git-ignored, so credentials LEAN persists
   there can never be committed;
2. syncs the *tracked* smoke-test source into the *untracked* runtime workspace;
3. statically proves the algorithm contains no order-submission path;
4. prints the launch checklist for human review.

Exits non-zero if any check fails. Nothing here contacts a broker.

Usage:
    python scripts/phase1_preflight.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalpamani.common.capital import DEFAULT_STRATEGY_CAPITAL_USD
from kalpamani.common.phase_guards import scan_tree_for_order_apis

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = "ibkr_connectivity_smoke"

TRACKED_PROJECT = REPO_ROOT / "lean" / "projects" / PROJECT_NAME
RUNTIME_WORKSPACE = REPO_ROOT / ".runtime" / "lean"
RUNTIME_PROJECT = RUNTIME_WORKSPACE / PROJECT_NAME

#: Files copied into the runtime workspace. An allowlist, so nothing unexpected
#: is ever synced.
SYNCED_FILES = ("main.py", "config.json")

EXPECTED_ACCOUNT_MODE = "PAPER"
DATA_PROVIDER = "Interactive Brokers"
DELAYED_DATA_ENABLED = True


def _fail(message: str) -> None:
    print(f"  FAIL: {message}")


def is_git_ignored(path: Path) -> bool:
    """Whether git ignores ``path``. Uses git itself rather than reimplementing it."""
    result = subprocess.run(  # noqa: S603
        ["git", "check-ignore", "-q", str(path)],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def git_sees(path: Path) -> bool:
    """Whether git status reports ``path`` at all (tracked or untracked)."""
    result = subprocess.run(  # noqa: S603
        ["git", "status", "--porcelain", "--untracked-files=all", "--", str(path)],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


def check_runtime_is_untracked() -> bool:
    print("[1/4] Runtime workspace isolation")
    ok = True

    runtime_root = REPO_ROOT / ".runtime"
    if is_git_ignored(runtime_root):
        print(f"  OK  : {runtime_root} is git-ignored")
    else:
        _fail(f"{runtime_root} is NOT git-ignored. Refusing to place credentials there.")
        ok = False

    if git_sees(runtime_root):
        _fail(f"git status can see {runtime_root}. It must be invisible to git.")
        ok = False
    else:
        print("  OK  : git status cannot see .runtime/")

    for probe in ("lean.json", "data/credentials", f"{PROJECT_NAME}/config.json"):
        target = RUNTIME_WORKSPACE / probe
        if is_git_ignored(target):
            print(f"  OK  : {target.relative_to(REPO_ROOT)} would be ignored")
        else:
            _fail(f"{target} would NOT be ignored")
            ok = False
    return ok


def sync_project() -> bool:
    print("[2/4] Sync tracked source -> untracked runtime workspace")
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
        print(f"  OK  : {name} -> {(RUNTIME_PROJECT / name).relative_to(REPO_ROOT)}")

    print("  NOTE: the runtime copy is a build artifact. Edit the tracked source only;")
    print("        LEAN writes generated state (local-id, logs) into the runtime copy.")
    return True


def check_zero_orders() -> bool:
    print("[3/4] Zero-order static safety check")
    findings = scan_tree_for_order_apis(TRACKED_PROJECT)
    if findings:
        for finding in findings:
            _fail(finding.describe())
        return False
    print(f"  OK  : no order-submission API found in {TRACKED_PROJECT.relative_to(REPO_ROOT)}")

    runtime_findings = scan_tree_for_order_apis(RUNTIME_PROJECT)
    if runtime_findings:
        for finding in runtime_findings:
            _fail(finding.describe())
        return False
    print("  OK  : no order-submission API found in the synced runtime copy")
    return True


def print_launch_checklist() -> None:
    print("[4/4] Launch checklist -- review before deploying")
    lean_json = RUNTIME_WORKSPACE / "lean.json"
    rows = [
        ("Project (tracked source)", str(TRACKED_PROJECT.relative_to(REPO_ROOT))),
        ("Project (runtime copy)", str(RUNTIME_PROJECT.relative_to(REPO_ROOT))),
        ("LEAN workspace root", str(RUNTIME_WORKSPACE.relative_to(REPO_ROOT))),
        ("Runtime config path", str(lean_json.relative_to(REPO_ROOT))),
        ("Runtime git-ignored", "YES" if is_git_ignored(lean_json) else "NO -- ABORT"),
        ("Expected account mode", EXPECTED_ACCOUNT_MODE),
        ("Brokerage", "Interactive Brokers (PAPER account only)"),
        ("Live data provider", DATA_PROVIDER),
        ("Delayed streaming data", "ENABLED" if DELAYED_DATA_ENABLED else "disabled"),
        ("Subscribed symbol", "SPY (exactly one)"),
        ("Orders permitted", "NONE -- read-only phase"),
        ("KalpaMani strategy capital", f"USD {DEFAULT_STRATEGY_CAPITAL_USD:,}"),
    ]
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {label.ljust(width)} : {value}")


def main() -> int:
    print("=" * 78)
    print("KalpaMani Phase 1 preflight -- IBKR PAPER connectivity")
    print("=" * 78)

    checks = [check_runtime_is_untracked(), sync_project()]
    checks.append(check_zero_orders())

    print()
    print_launch_checklist()
    print()

    if all(checks):
        print("PREFLIGHT PASSED. Safe to deploy read-only against IBKR PAPER.")
        print("Reminder: enter IBKR credentials only into LEAN's own interactive prompts.")
        return 0
    print("PREFLIGHT FAILED. Do not deploy.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
