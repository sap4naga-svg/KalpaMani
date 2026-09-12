"""ADR-0039 governance: a proposed, narrow amendment adding two universe exclusion reasons.

These checks hold the document to its own claims -- proposed and not in force, exactly two
members, the effectiveness and execution gates stated -- and hold the offline build to the
shape the document describes: a build-local mirror, the accepted vocabulary untouched, and
every membership row naming which vocabulary its reason belongs to.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from kalpamani.data.contracts import vocabulary
from kalpamani.data.contracts.vocabulary import UniverseExclusionReason
from kalpamani.data.production.sharadar import universe

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
ADR: Final = (
    DECISIONS
    / "ADR-0039-universe-exclusion-reasons-for-indeterminate-attributes-and-unresolved-actions.md"
)
README: Final = PROJECT_ROOT / "README.md"
CLAUDE: Final = PROJECT_ROOT / "CLAUDE.md"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""
ADR_FLAT: Final = " ".join(ADR_TEXT.split())

HEX_64: Final = re.compile(r"\b[0-9a-f]{64}\b")
TWELVE_DIGITS: Final = re.compile(r"\b\d{12}\b")
REAL_ARN: Final = re.compile(r"\barn:aws\b")
PROPOSED: Final = "PROPOSED " + chr(0x2014) + " NOT IN FORCE"


def test_the_adr_exists_and_is_the_only_0039() -> None:
    assert ADR.is_file()
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0039-*.md"))] == [ADR.name]


def test_the_adr_keeps_its_conditional_status_and_records_the_merge() -> None:
    """The pre-merge condition is preserved as written; the note beside it records the event."""
    assert "Status: " + PROPOSED in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "two additional members of `UniverseExclusionReason`" in ADR_FLAT
    assert "Nothing was run to produce this decision" in ADR_FLAT
    assert "The condition above has since been satisfied." in ADR_FLAT
    assert "PR #97 merged" in ADR_FLAT and "2026-09-12T16:56:34Z" in ADR_FLAT
    assert "2be8d2ee7946de457e8071160f89836746713168" in ADR_TEXT
    assert "6ddfa3601a8b14d4e0768ddd823f2c5a34927bdd" in ADR_TEXT
    assert "310df423f2a2b26109e23bb5a4b1be8edc787f65" in ADR_TEXT
    assert "ADR-0039 is therefore ACCEPTED / IN FORCE" in ADR_FLAT.replace("**", "")
    assert "did not add the members to `kalpamani.data.contracts.vocabulary`" in ADR_FLAT
    assert "Acceptance authorizes no build, no ingestion and no run" in ADR_FLAT
    assert "## 3. Effectiveness and execution gates" in ADR_TEXT
    assert "acceptance authorizes no build, no ingestion and no run" in ADR_FLAT
    assert "G2 stays OPEN" in ADR_FLAT
    assert (
        "`VENDOR_DATE_UPPER_BOUND` and `VERSION_EVIDENCE_UPPER_BOUND` stay proposed and gated"
        in ADR_FLAT
    )


def test_the_adr_names_exactly_the_two_members_and_their_semantics() -> None:
    assert "ATTRIBUTE_UNAVAILABLE" in ADR_TEXT and "UNRESOLVED_CORPORATE_ACTION" in ADR_TEXT
    assert "The build-local mirror retires on effectiveness" in ADR_FLAT
    assert "`exclusion_vocabulary` field reads `accepted`" in ADR_FLAT


def test_the_accepted_vocabulary_is_untouched_and_the_mirror_matches_it() -> None:
    """Implementing the members belongs to the effectiveness gate, not to this proposal."""
    assert not hasattr(vocabulary.UniverseExclusionReason, "ATTRIBUTE_UNAVAILABLE")
    assert not hasattr(vocabulary.UniverseExclusionReason, "UNRESOLVED_CORPORATE_ACTION")
    accepted = {member.value for member in UniverseExclusionReason}
    mirror = {member.value for member in universe.BuildExclusionReason}
    assert accepted < mirror
    assert mirror - accepted == {"ATTRIBUTE_UNAVAILABLE", "UNRESOLVED_CORPORATE_ACTION"}
    assert {m.value for m in universe.PROPOSED_EXCLUSIONS} == mirror - accepted
    assert {m.value for m in universe.ACCEPTED_EXCLUSIONS} == accepted
    for member in universe.BuildExclusionReason:
        expected = "accepted" if member.value in accepted else "proposed-adr-0039"
        assert universe.exclusion_vocabulary(member) == expected


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
        and "ADR-0039](" in line
        and "two universe exclusion reasons" in line.split("|")[1]
    ]
    assert len(rows) == 1
    flat = " ".join(rows[0].replace("**", "").split())
    assert "ACCEPTED / IN FORCE" in flat and "PR #97 merged 2026-09-12T16:56:34Z" in flat
    assert "2be8d2ee7946de457e8071160f89836746713168" in flat
    assert "while PR #97 was open it was proposed and carried no authority" in flat
    assert "Vocabulary integration has not occurred" in flat
    assert "ADR-0039 (two universe exclusion reasons):        ACCEPTED / IN FORCE" in text
    assert "vocabulary integration NOT PERFORMED" in text
    assert re.search(r"ADR-0039[^\n]{0,200}" + re.escape(PROPOSED), text) is None
