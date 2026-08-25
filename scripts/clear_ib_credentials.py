"""Clear cached Interactive Brokers settings from the LEAN runtime config.

WHY THIS EXISTS
---------------
`lean live deploy` caches brokerage-specific settings in the workspace
`lean.json` and silently reuses them on the next run. It re-prompts for the
brokerage and data-feed *selection*, but NOT for the IB username, account id or
password. So a deployment that failed on bad credentials will fail again,
identically, no matter how many times it is re-run -- the wizard never asks
again.

Run this to force the wizard to prompt for IB credentials on the next deploy.

SAFETY
------
- Refuses to touch a file that git does not ignore.
- Reports removed settings BY NAME ONLY. Values are never read, printed or
  logged.
- Only `ib-*` keys are removed; the rest of the LEAN config is left alone.

Usage:
    python scripts/clear_ib_credentials.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEAN_CONFIG = REPO_ROOT / ".runtime" / "lean" / "lean.json"

#: Every IB setting LEAN caches. Cleared together so a retry starts clean --
#: a stale account id paired with a fresh password is its own kind of confusing.
IB_KEYS = (
    "ib-user-name",
    "ib-account",
    "ib-password",
    "ib-trading-mode",
    "ib-agent-description",
    "ib-enable-delayed-streaming-data",
    "ib-weekly-restart-utc-time",
    "ib-financial-advisors-group-filter",
)


def is_git_ignored(path: Path) -> bool:
    result = subprocess.run(  # noqa: S603
        ["git", "check-ignore", "-q", str(path)],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def main() -> int:
    print("=" * 78)
    print("Clear cached IBKR settings from the LEAN runtime config")
    print("=" * 78)

    if not LEAN_CONFIG.is_file():
        print(f"Nothing to do: {LEAN_CONFIG} does not exist.")
        return 0

    if not is_git_ignored(LEAN_CONFIG):
        print(f"REFUSING: {LEAN_CONFIG} is not git-ignored.")
        print("A credential file that git can see is a bug. Fix .gitignore first.")
        return 1
    print(f"OK  : {LEAN_CONFIG.relative_to(REPO_ROOT)} is git-ignored")

    raw = LEAN_CONFIG.read_text(encoding="utf-8")
    # LEAN ships lean.json with // comments, which json.loads rejects.
    config = json.loads(re.sub(r"^\s*//.*$", "", raw, flags=re.M))

    removed = [key for key in IB_KEYS if key in config]
    for key in removed:
        del config[key]

    if not removed:
        print("OK  : no cached IB settings found; the wizard will prompt already.")
        return 0

    LEAN_CONFIG.write_text(json.dumps(config, indent=4) + "\n", encoding="utf-8")

    print(f"OK  : removed {len(removed)} cached IB settings (names only):")
    for key in removed:
        print(f"        - {key}")
    print()
    print("Values were never read or printed.")
    print("The next `lean live deploy` will prompt for IB credentials again.")
    print()
    print("NOTE: this rewrites lean.json without LEAN's inline comments. The")
    print("      settings are unchanged; only formatting and the IB keys differ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
