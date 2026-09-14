"""Proposed ADR-0046 says what the tooling does, and the code says the same.

The document is PROPOSED and says so; it names the three tools, the two contracts, the
control profile, the budgets, the deferred negative cells; the status register carries it;
and nothing in it is a real value.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from kalpamani.data.production.sharadar import r3_verification as r3
from kalpamani.data.production.sharadar import verification_cells as vc

pytestmark = pytest.mark.unit

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = REPO_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0046-verification-tooling-materializer-r3-tool-and-cell-runner.md"
ADR_TEXT: Final = ADR.read_text(encoding="utf-8")
ADR_PLAIN: Final = " ".join(ADR_TEXT.split()).replace("**", "").replace("`", "")
PROPOSED: Final = "PROPOSED " + chr(0x2014) + " NOT IN FORCE"
HEX_64: Final = re.compile(r"\b[0-9a-f]{64}\b")
TWELVE_DIGITS: Final = re.compile(r"\b\d{12}\b")


def test_the_adr_exists_is_proposed_and_names_its_gates() -> None:
    # The conditional status line is kept as the record of the days before the merge; the
    # post-merge note beside it records that the condition has been satisfied.
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0046-*.md"))] == [ADR.name]
    assert "Status: " + PROPOSED in ADR_TEXT
    assert "The condition above has since been satisfied" in ADR_PLAIN
    assert "PR #105 merged" in ADR_PLAIN and "5174dcf290b4837d38af8ce4a4b975c6557e482e" in ADR_TEXT
    assert (
        "c4436648d90d39baa3769e990887e6f0f239df40" in ADR_TEXT
        and "af20f36acbe8a3006830762fbad5cb01d1e9b38b" in ADR_TEXT
    )
    assert "ACCEPTED / IN FORCE" in ADR_PLAIN
    assert "Acceptance authorized no R-3 session" in ADR_PLAIN
    assert "Acceptance authorizes no execution" in ADR_PLAIN
    assert "## 6. Effectiveness and execution gates" in ADR_TEXT
    assert "Nothing was run to produce this decision" in ADR_PLAIN
    assert "Mocked results are not AWS verification" in ADR_PLAIN
    assert "G2 stays OPEN, CONTROL stays DEFERRED, Phase 3 stays NOT COMPLETE" in ADR_PLAIN


def test_the_adr_names_the_tools_and_the_contracts_the_code_defines() -> None:
    for name in (
        "scripts/production_human_binding_materialize.py",
        "scripts/production_r3_verification.py",
        "scripts/production_verification_cells.py",
    ):
        assert name in ADR_TEXT and (REPO_ROOT / name).is_file()
    assert r3.R3_RECORD_CONTRACT_ID in ADR_TEXT and vc.CELLS_CONTRACT_ID in ADR_TEXT
    assert r3.CONTROL_PROFILE in ADR_TEXT
    assert r3.FAILURE_PATH_BUDGET == 10 and "budget of ten operations" in ADR_PLAIN
    assert "nine expected-path S3 operations" in ADR_PLAIN
    names = [m.value for m in r3.ObservedClass] + [m.value for m in r3.R3Result]
    names += [m.value for m in vc.CellStatus]
    for name in names:
        assert name in ADR_TEXT, name
    for cell in vc.REQUIRED_CELLS:
        if cell.kind in {
            vc.CellKind.CONTROL_R3,
            vc.CellKind.RUNTIME_LAUNCH,
            vc.CellKind.ISOLATION_VERDICT,
        }:
            assert cell.cell_id in ADR_TEXT, cell.cell_id
    assert "## 4. Deferred: the negative R-1 cells" in ADR_TEXT
    assert "withholds or mis-names the release" in ADR_PLAIN
    assert "record_attests" in ADR_TEXT and "old evidence attests to nothing changed" in ADR_PLAIN
    assert "Materializing is not verifying" in ADR_PLAIN


def test_the_status_register_carries_the_proposal() -> None:
    for name in ("CLAUDE.md", "README.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert "ADR-0046-verification-tooling-materializer-r3-tool-and-cell-runner.md" in text
        assert "ADR-0046 verification tooling (code):" in text
        assert "PR #104 merged 2026-09-14T17:28:56Z" in text


def test_the_adr_names_no_real_value() -> None:
    assert not HEX_64.search(ADR_TEXT)
    assert not TWELVE_DIGITS.search(ADR_TEXT)
    assert "arn:aws" not in ADR_TEXT
