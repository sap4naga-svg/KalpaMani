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


def test_the_adr_carries_a_conditional_acceptance_status_and_the_gates() -> None:
    assert "Status: " + PROPOSED in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "two additional members of `UniverseExclusionReason`" in ADR_FLAT
    assert "Nothing was run to produce this decision" in ADR_FLAT
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
def test_status_documents_record_the_adr_as_proposed(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert re.search(r"ADR-0039[^\n]{0,200}" + re.escape(PROPOSED), text) is not None
    assert "ADR-0039 (two universe exclusion reasons):        " + PROPOSED in text
