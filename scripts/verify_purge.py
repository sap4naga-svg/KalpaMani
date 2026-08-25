"""Verify that orphaned pre-sanitization objects are gone from GitHub.

A feature branch once carried a sensitive pseudonymous identifier. The branch was
rewritten to remove it, but a force-push does not delete anything: the
pre-rewrite commits and blobs stay retrievable by SHA until GitHub purges them.
Until they are gone the repository stays **PRIVATE** (CLAUDE.md §3).

This is the gate on that. It reports a verdict and nothing else:

* it reads the object list from the untracked operational file under `.runtime/`,
  so no SHA and no path is baked into tracked source;
* it prints **counts and HTTP statuses**, never object contents;
* it exits non-zero while any object is still retrievable.

`404` for every object is the only result that permits proposing a visibility
change -- and even then, the change is a separate authorised decision.

Usage:
    python scripts/verify_purge.py
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO = "sap4naga-svg/KalpaMani"

#: Untracked. Written when the support request was prepared.
AFFECTED = REPO_ROOT / ".runtime" / "support" / "_affected.json"


def status_of(endpoint: str) -> int:
    """HTTP status for one API endpoint. Contents are never read."""
    result = subprocess.run(  # noqa: S603
        ["gh", "api", "-i", "--silent", endpoint],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    for line in (result.stdout or result.stderr).splitlines():
        if line.upper().startswith("HTTP/"):
            parts = line.split()
            if len(parts) > 1 and parts[1].isdigit():
                return int(parts[1])
    return 0 if result.returncode == 0 else 404


def main() -> int:
    print("=" * 78)
    print("KalpaMani -- orphaned object purge verification")
    print("=" * 78)

    if not AFFECTED.is_file():
        print(f"  FAIL: {AFFECTED.relative_to(REPO_ROOT)} not found.")
        print("        Prepare the support request first; this reads its object list.")
        return 1

    data = json.loads(AFFECTED.read_text(encoding="utf-8"))
    commits: list[str] = data.get("commits", [])
    blobs: list[str] = data.get("blobs", [])
    print(f"  checking {len(commits)} commit(s) and {len(blobs)} blob(s)")

    remaining = 0
    for sha in commits:
        if status_of(f"repos/{REPO}/commits/{sha}") != 404:
            remaining += 1
    for sha in blobs:
        if status_of(f"repos/{REPO}/git/blobs/{sha}") != 404:
            remaining += 1

    print()
    if remaining:
        print(f"  NOT PURGED: {remaining} object(s) are still retrievable by SHA.")
        print("  The repository MUST stay private. Do not propose a visibility change.")
        return 1

    print("  PURGED: every listed object returns 404.")
    print()
    print("  This clears the blocker; it is NOT authorisation to go public.")
    print("  Ask for that separately, and if approved change visibility and")
    print("  CLAUDE.md section 3 in the same controlled change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
