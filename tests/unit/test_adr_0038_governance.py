"""ADR-0038 governance: the accepted, narrow amendment adding the production run reservation.

These checks hold the document to its own claims -- the conditional status preserved as
written beside the note recording the PR #96 merge, one object class under the accepted
claim namespace, the effectiveness and execution gates stated -- and hold the offline
implementation and the status documents to the shape the document describes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0038-production-run-reservation.md"
README: Final = PROJECT_ROOT / "README.md"
CLAUDE: Final = PROJECT_ROOT / "CLAUDE.md"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""
ADR_FLAT: Final = " ".join(ADR_TEXT.split())

HEX_64: Final = re.compile(r"\b[0-9a-f]{64}\b")
TWELVE_DIGITS: Final = re.compile(r"\b\d{12}\b")
REAL_ARN: Final = re.compile(r"\barn:aws\b")


def test_the_adr_exists_and_is_the_only_0038() -> None:
    assert ADR.is_file()
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0038-*.md"))] == [ADR.name]


def test_the_adr_keeps_its_conditional_status_and_records_the_merge() -> None:
    """The pre-merge condition is preserved as written; the note beside it records the event."""
    assert "Status: PROPOSED — NOT IN FORCE" in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "a narrow amendment of ADR-0037 §2's claim namespace" in ADR_FLAT
    assert "Nothing was run to produce this decision" in ADR_FLAT
    assert "The condition above has since been satisfied." in ADR_FLAT
    assert "PR #96 merged" in ADR_FLAT and "2026-09-12T15:10:12Z" in ADR_FLAT
    assert "6ddfa3601a8b14d4e0768ddd823f2c5a34927bdd" in ADR_TEXT
    assert "7c83da07308eca69b9484c09edd1769ca4055abe" in ADR_TEXT
    assert "61b501cfbb8b1105e11363e41b2767de5cc2aa0a" in ADR_TEXT
    assert "ADR-0038 is therefore ACCEPTED / IN FORCE" in ADR_FLAT.replace("**", "")
    assert "Acceptance authorizes no run" in ADR_FLAT
    assert "## 3. Effectiveness and execution gates" in ADR_TEXT
    assert "acceptance authorizes no run" in ADR_FLAT
    assert "No IAM statement, bucket-policy statement, Terraform declaration" in ADR_FLAT
    assert "or deployed resource changes" in ADR_FLAT


def test_the_adr_states_the_reservation_shape_and_its_consequences() -> None:
    assert "licensed/bronze/_production_claims/runs/<run-id>.json" in ADR_TEXT
    assert "kalpamani-production-run-reservation/v1" in ADR_TEXT
    for token in ("RESERVATION_CONFLICT", "RESERVATION_STATE_UNKNOWN", "RESERVATION_REFUSED"):
        assert token in ADR_TEXT, token
    assert "before any credential is retrieved and before any provider request" in ADR_FLAT
    assert "No locator is published" in ADR_FLAT
    assert "A reserved identity stays spent when later processing fails" in ADR_FLAT
    assert "`1 + 3R + 1`" in ADR_TEXT


def test_the_implementation_matches_the_document() -> None:
    from kalpamani.data.production.sharadar import processing
    from kalpamani.data.production.sharadar.keys import run_reservation_key_segments

    assert processing.RESERVATION_CONTRACT_ID == "kalpamani-production-run-reservation/v1"
    assert run_reservation_key_segments("r-1") == (
        "bronze",
        "_production_claims",
        "runs",
        "r-1.json",
    )
    for token in ("RESERVATION_CONFLICT", "RESERVATION_STATE_UNKNOWN", "RESERVATION_REFUSED"):
        assert token in {member.value for member in processing.ProcessingHalt}


def test_the_adr_carries_no_private_value() -> None:
    assert HEX_64.search(ADR_TEXT) is None
    assert TWELVE_DIGITS.search(ADR_TEXT) is None
    assert REAL_ARN.search(ADR_TEXT) is None


@pytest.mark.parametrize("path", [README, CLAUDE])
def test_status_documents_record_the_adr_as_accepted_on_the_merge(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    rows = [
        line
        for line in text.splitlines()
        if line.startswith("| ")
        and "ADR-0038](" in line
        and "production run reservation" in line.split("|")[1]
    ]
    assert len(rows) == 1
    flat = " ".join(rows[0].replace("**", "").split())
    assert "ACCEPTED / IN FORCE" in flat and "PR #96 merged 2026-09-12T15:10:12Z" in flat
    assert "6ddfa3601a8b14d4e0768ddd823f2c5a34927bdd" in flat
    assert "while PR #96 was open it was proposed and carried no authority" in flat
    assert "acceptance authorized no run" in flat
    assert "ADR-0038 (production run reservation):            ACCEPTED / IN FORCE" in text
    proposed = "PROPOSED " + chr(0x2014) + " NOT IN FORCE"
    assert re.search("ADR-0038[^\n]{0,200}" + re.escape(proposed), text) is None
