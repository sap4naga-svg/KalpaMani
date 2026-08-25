"""Build a sanitized, untracked bundle for independent review of PR #3.

The repository is private (CLAUDE.md §3), so an external reviewer cannot read it
on GitHub — and it must not be made public again to enable one. This produces a
local ZIP the owner can hand to a reviewer instead.

Two rules make it safe:

1. **Only tracked files go in.** Everything is read from `git show HEAD:<path>`,
   never from the working tree. That structurally excludes `.runtime/` — LEAN
   configuration, IBKR gateway logs, credentials, cached brokerage settings —
   because none of it is tracked. A stray untracked file cannot be swept up.
2. **The staged bytes are scanned before the ZIP is written**, and generation
   ABORTS on any hit. The scan runs over generated text too (the patch, the
   validation report), because those are the parts nobody reviewed by hand.

The bundle is written under `.runtime/`, which is git-ignored, so it cannot be
committed by accident.

Usage:
    python scripts/phase2_review_bundle.py
"""

from __future__ import annotations

import itertools
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalpamani.execution.session import IB_ACCOUNT_KEY, account_fingerprint

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_BRANCH = "main"
OUTPUT_DIR = REPO_ROOT / ".runtime" / "review"
OUTPUT_ZIP = OUTPUT_DIR / "phase2-round10-review.zip"

#: The deployment configuration. Read ONLY to learn what must never appear in
#: the bundle. Its contents never enter the bundle.
LEAN_DEPLOYMENT_CONFIG = REPO_ROOT / ".runtime" / "lean" / "lean.json"

#: EXCLUDED from the bundle. Everything else that is tracked goes in, so the
#: full test suite runs from an extraction -- an earlier bundle hand-picked
#: files, and a reviewer could only run the Phase-2 subset from it.
#:
#: The Blueprint PDF is the proprietary architecture document: 300+ KB of binary
#: a reviewer of this PR does not need, and which no text scan can meaningfully
#: inspect. Its governing content is quoted in CLAUDE.md and the ADRs, which ARE
#: included.
EXCLUDE_SUFFIXES = (".pdf",)

#: Brokerage account shape, including the letter some IBKR ids carry in third
#: position -- an earlier version of this pattern missed exactly those.
_ACCOUNT_SHAPE = re.compile(r"\b(?:DU|DF|DI|U|F|I)[A-Z]?\d{6,9}\b")


def looks_synthetic(account_id: str) -> bool:
    """Whether an account-shaped token is obviously a placeholder.

    Judging the VALUE beats keeping an allowlist, which drifts the moment a test
    invents another fake id and quietly turns the scan off for it. Real IBKR
    account numbers are not ``0000000``, and they do not count up from one.
    """
    digits = "".join(c for c in account_id if c.isdigit())
    if len(set(digits)) <= 2:
        return True
    steps = {ord(b) - ord(a) for a, b in itertools.pairwise(digits)}
    return steps in ({1}, {-1})


_CREDENTIAL_SHAPE = re.compile(
    r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|bearer)\b\s*[:=]\s*[\"']?[^\s\"',}]{6,}"
)


def run(*args: str) -> str:
    result = subprocess.run(  # noqa: S603
        args, cwd=REPO_ROOT, capture_output=True, text=True, errors="replace", check=False
    )
    return result.stdout


def tracked_files() -> list[str]:
    return [line for line in run("git", "ls-files").splitlines() if line.strip()]


def selected_files() -> list[str]:
    """Every tracked file, minus explicit exclusions.

    Tracked-by-default is the safe direction here: `.runtime/` is untracked, so
    credentials, LEAN configuration and IBKR logs cannot be reached at all, while
    a reviewer gets a tree complete enough to run `pytest` against.
    """
    return sorted(f for f in tracked_files() if not f.lower().endswith(EXCLUDE_SUFFIXES))


def tracked_content(path: str) -> bytes | None:
    """Read from the COMMIT, not the working tree. Untracked bytes cannot leak.

    Returns ``None`` only when git could not produce the object. An EMPTY result
    with a clean exit is a legitimately empty tracked file -- the repository has
    eleven `.gitkeep` placeholders -- and must not be mistaken for a failure.
    """
    result = subprocess.run(  # noqa: S603
        ["git", "show", f"HEAD:{path}"],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def forbidden_needles() -> list[tuple[str, str]]:
    """Exact values that must never appear. Never printed, only matched."""
    needles: list[tuple[str, str]] = []
    if LEAN_DEPLOYMENT_CONFIG.is_file():
        raw = json.loads(LEAN_DEPLOYMENT_CONFIG.read_text(encoding="utf-8"))
        account_id = str(raw.get(IB_ACCOUNT_KEY, "") or "")
        if account_id:
            needles.append(("deployment account id", account_id))
            needles.append(("deployment account binding digest", account_fingerprint(account_id)))
    return needles


def scan(staged: dict[str, bytes]) -> list[str]:
    """Return every reason the bundle must not be written."""
    problems: list[str] = []
    needles = forbidden_needles()

    for arcname, blob in staged.items():
        text = blob.decode("utf-8", errors="replace")

        for label, needle in needles:
            if needle in text:
                problems.append(f"{arcname}: contains the {label}")

        for match in _ACCOUNT_SHAPE.findall(text):
            if not looks_synthetic(match):
                problems.append(
                    f"{arcname}: contains a brokerage-account-shaped value that does not look "
                    "like a placeholder"
                )
                break

        if _CREDENTIAL_SHAPE.search(text):
            problems.append(f"{arcname}: contains something shaped like a credential assignment")

    # NOTE: deliberately no check for `.runtime/` path STRINGS. Only tracked
    # content is staged, so a path named in a comment carries nothing -- and
    # flagging it would train whoever runs this to skim past the output.
    return problems


def validation_report() -> str:
    """Plain-text validation, captured from the real commands."""
    lines = [
        "KalpaMani Phase 2 -- validation report",
        "=" * 60,
        "",
        f"HEAD           : {run('git', 'rev-parse', 'HEAD').strip()}",
        f"branch         : {run('git', 'rev-parse', '--abbrev-ref', 'HEAD').strip()}",
        f"commits ahead : {run('git', 'rev-list', '--count', f'{BASE_BRANCH}..HEAD').strip()}",
        "",
    ]
    python = str(REPO_ROOT / ".venv" / "Scripts" / "python.exe")
    for label, command in (
        ("pytest", [python, "-m", "pytest", "-q", "--no-header"]),
        ("ruff check", [python, "-m", "ruff", "check"]),
        ("ruff format --check", [python, "-m", "ruff", "format", "--check"]),
        ("mypy --strict", [python, "-m", "mypy"]),
    ):
        result = subprocess.run(  # noqa: S603
            command, cwd=REPO_ROOT, capture_output=True, text=True, errors="replace", check=False
        )
        tail = [ln for ln in result.stdout.strip().splitlines() if ln.strip()][-3:]
        lines.append(f"$ {label}  -> exit {result.returncode}")
        lines.extend(f"    {ln}" for ln in tail)
        lines.append("")

    lines += [
        "Preflight scripts are NOT run here: their output names the deployment account",
        "(redacted) and local runtime paths, neither of which belongs in a review bundle.",
        "Run them locally; both exit 0.",
        "",
        "SYSTEM STATE: DISARMED. No order has ever been submitted.",
    ]
    return "\n".join(lines)


def readme(files: list[str]) -> str:
    return f"""KalpaMani Phase 2 -- independent review bundle
=============================================

Phase 2 is an execution-plumbing certification, not a strategy: a single
BUY 1 SPY on IBKR PAPER, protected, reconciled, restarted, exited, flat.

NOTHING HAS BEEN SUBMITTED. The system is DISARMED and PR #3 is unmerged.

Contents
--------
  README.txt            this file
  VALIDATION.txt        pytest / ruff / mypy results
  PATCH.diff            git diff {BASE_BRANCH}...HEAD
  CHANGED_FILES.txt     files the branch touches
  source/               {len(files)} tracked files, read from the commit

Reproducing the validation
--------------------------
  cd source && python -m pip install -r /dev/null 2>/dev/null; python -m pytest -q

`pyproject.toml` sets `pythonpath = ["src"]`, so the suite runs from `source/`
with no install step. Requires pytest; ruff and mypy are optional.

The tree is COMPLETE apart from `docs/architecture/*.pdf` (the proprietary
Blueprint, excluded deliberately). Every test in the repository is present and
should pass.

Where to start
--------------
  source/docs/decisions/ADR-0004-*.md        the design and every amendment
  source/src/kalpamani/execution/cycle.py    every decision Phase 2 makes
  source/src/kalpamani/execution/coordinator.py  all lifecycle writes
  source/src/kalpamani/execution/halt.py     halt policy and clearance gates
  source/lean/projects/.../main.py           the LEAN adapter (decides nothing)

What is deliberately absent
---------------------------
Brokerage credentials, account identifiers, account-binding digests, LEAN
deployment configuration and IBKR gateway logs. None of it is tracked, and this
bundle is built only from tracked content, then scanned before it is written.
"""


def main() -> int:
    print("=" * 78)
    print("KalpaMani Phase 2 -- sanitized review bundle")
    print("=" * 78)

    files = selected_files()
    if not files:
        print("  FAIL: no tracked files matched the include list")
        return 1

    read = {path: tracked_content(path) for path in files}
    unreadable = [path for path, blob in read.items() if blob is None]
    if unreadable:
        print(f"  FAIL: {len(unreadable)} selected file(s) could not be read from HEAD")
        return 1
    staged: dict[str, bytes] = {
        f"source/{path}": blob for path, blob in read.items() if blob is not None
    }

    patch = run("git", "diff", f"{BASE_BRANCH}...HEAD")
    changed = run("git", "diff", "--stat", f"{BASE_BRANCH}...HEAD")
    staged["PATCH.diff"] = patch.encode("utf-8")
    staged["CHANGED_FILES.txt"] = changed.encode("utf-8")
    staged["VALIDATION.txt"] = validation_report().encode("utf-8")
    staged["README.txt"] = readme(files).encode("utf-8")

    print(f"  INFO: staged {len(files)} tracked files + 4 generated documents")
    print(f"  INFO: patch is {len(patch.splitlines())} lines")

    problems = scan(staged)
    if problems:
        print()
        print("  ABORTED -- sensitive data detected in the staged contents:")
        for problem in sorted(set(problems)):
            print(f"    - {problem}")
        print()
        print("  No archive was written. The offending values are NOT printed.")
        return 1
    print("  OK  : sensitive-data scan clean (account ids, binding digests,")
    print("        credential shapes, runtime LEAN paths)")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as archive:
        for arcname in sorted(staged):
            archive.writestr(arcname, staged[arcname])

    ignored = subprocess.run(  # noqa: S603
        ["git", "check-ignore", "-q", str(OUTPUT_ZIP)],  # noqa: S607 cwd=REPO_ROOT, check=False
    )
    if ignored.returncode != 0:
        OUTPUT_ZIP.unlink(missing_ok=True)
        print("  FAIL: the output path is NOT git-ignored; refusing to leave an archive there")
        return 1

    size_kb = OUTPUT_ZIP.stat().st_size / 1024
    print("  OK  : git-ignored output path (cannot be committed)")
    print()
    print(f"BUNDLE WRITTEN: {OUTPUT_ZIP}")
    print(f"  {len(staged)} entries, {size_kb:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
