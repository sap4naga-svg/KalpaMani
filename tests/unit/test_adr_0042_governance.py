"""ADR-0042 governance: a proposed, narrow amendment fixing build-side pagination admission.

These checks hold the document to its own claims -- proposed and not in force, one supported
shape for every dataset, the closed refusal vocabulary, the stated limits, the gates -- and
hold the offline gate to the shape the document describes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from kalpamani.data.production.sharadar import pagination, silver

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0042-build-side-pagination-admission.md"
README: Final = PROJECT_ROOT / "README.md"
CLAUDE: Final = PROJECT_ROOT / "CLAUDE.md"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""
ADR_FLAT: Final = " ".join(ADR_TEXT.split())

HEX_64: Final = re.compile(r"\b[0-9a-f]{64}\b")
TWELVE_DIGITS: Final = re.compile(r"\b\d{12}\b")
REAL_ARN: Final = re.compile(r"\barn:aws\b")
PROPOSED: Final = "PROPOSED " + chr(0x2014) + " NOT IN FORCE"


def test_the_adr_exists_and_is_the_only_0042() -> None:
    assert ADR.is_file()
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0042-*.md"))] == [ADR.name]


def test_the_adr_carries_a_conditional_acceptance_status_and_the_gates() -> None:
    assert "Status: " + PROPOSED in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "a narrow amendment of ADR-0041 §3's pagination clause" in ADR_FLAT
    assert "Nothing was run to produce this decision" in ADR_FLAT
    assert "## 5. Effectiveness and execution gates" in ADR_TEXT
    assert "acceptance authorizes no build and no run" in ADR_FLAT
    assert "no live request may be made to explore it" in ADR_FLAT


def test_the_adr_states_the_shape_its_limits_and_what_a_locator_proves() -> None:
    assert "fewer RAW data rows than its requested limit" in ADR_FLAT
    assert "every later compiled page: present, validly parsed, header-only" in ADR_FLAT
    assert "before deduplication, revision consolidation, symbol mapping or filtering" in ADR_FLAT
    assert (
        "an empty terminal page does not establish stable ordering or snapshot consistency"
        in ADR_FLAT
    )
    assert "It does not establish the semantic completeness" in ADR_FLAT
    assert "Unique rows across pages do not establish that no rows were omitted" in ADR_FLAT
    assert "does **not** establish vendor completeness of the window" in ADR_FLAT
    assert "Nothing about requests changes" in ADR_FLAT
    assert "`tickers`, `actions` and `stocks` alike" in ADR_FLAT
    for token in (
        "PAGE_OVER_LIMIT",
        "DELIVERY_TRUNCATED",
        "PAGINATION_UNSUPPORTED",
        "PAGINATION_INCONSISTENT",
    ):
        assert token in ADR_TEXT, token


def test_the_implementation_matches_the_document() -> None:
    assert {m.value for m in pagination.PaginationDefect} == {
        "PAGE_OVER_LIMIT",
        "DELIVERY_TRUNCATED",
        "PAGINATION_UNSUPPORTED",
        "PAGINATION_INCONSISTENT",
    }
    assert set(silver._PAGINATION_DEFECTS) == set(pagination.PaginationDefect)
    assert pagination.PAGINATION_POLICY_VERSION in ADR_TEXT or "pagination" in ADR_FLAT
    summary = pagination.PaginationSummary(
        policy_version=pagination.PAGINATION_POLICY_VERSION, groups_admitted={}, groups_empty={}
    ).document()
    assert summary["establishes"] == []
    assert "stable ordering across offsets" in summary["does_not_establish"]


def test_the_adr_carries_no_private_value() -> None:
    assert HEX_64.search(ADR_TEXT) is None
    assert TWELVE_DIGITS.search(ADR_TEXT) is None
    assert REAL_ARN.search(ADR_TEXT) is None


@pytest.mark.parametrize("path", [README, CLAUDE])
def test_status_documents_record_the_adr_as_proposed(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert re.search("ADR-0042[^\\n]{0,200}" + re.escape(PROPOSED), text) is not None
    assert "ADR-0042 (build-side pagination admission):      " + PROPOSED in text
    assert "ADR-0042 build pagination admission (code):       OFFLINE / SYNTHETIC-ONLY" in text
