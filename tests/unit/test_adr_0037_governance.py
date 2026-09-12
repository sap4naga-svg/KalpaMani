"""ADR-0037 governance: a narrow, proposed amendment of ADR-0036's production prefixes.

The amendment moves production Bronze under namespaces no earlier package writes. These
checks hold the document to its own claims -- proposed and not in force, a narrow amendment
that rewrites nothing, the traced layouts named, the disjoint prefixes stated -- and hold the
offline declaration to the amended prefixes. The proof that the prefixes are disjoint from
the merged key builders' output lives in ``test_production_infrastructure.py``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0037-disjoint-production-bronze-namespaces.md"
ADR_0036: Final = DECISIONS / "ADR-0036-production-data-plane-principals-and-trust-model.md"
POLICIES_TF: Final = (
    PROJECT_ROOT / "infra" / "aws" / "research-data-plane" / "production_policies.tf"
)
README: Final = PROJECT_ROOT / "README.md"
CLAUDE: Final = PROJECT_ROOT / "CLAUDE.md"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""
ADR_FLAT: Final = " ".join(ADR_TEXT.split())

HEX_64: Final = re.compile(r"\b[0-9a-f]{64}\b")
TWELVE_DIGITS: Final = re.compile(r"\b\d{12}\b")
REAL_ARN: Final = re.compile(r"\barn:aws\b")


def test_the_adr_exists_and_is_the_only_0037() -> None:
    assert ADR.is_file()
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0037-*.md"))] == [ADR.name]


def test_the_adr_carries_a_conditional_acceptance_status() -> None:
    assert "Status: PROPOSED — NOT IN FORCE" in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert (
        "a narrow amendment of ADR-0036's production Bronze prefixes and nothing else" in ADR_FLAT
    )
    assert "Nothing was run to produce this decision" in ADR_FLAT


def test_the_amendment_names_the_traced_layouts_and_the_disjoint_prefixes() -> None:
    for builder in (
        "`bronze_payload_key`",
        "`bronze_acquisition_key`",
        "`acquisition_claim_key`",
        "`qualification_payload_key`",
        "`locator_key_segments`",
        "`report_key_segments`",
    ):
        assert builder in ADR_TEXT, builder
    for prefix in (
        "licensed/bronze/sharadar/<dataset>/production/objects/sha256/<digest>",
        "licensed/bronze/sharadar/<dataset>/production/acquisitions/<...>",
        "licensed/bronze/_production_claims/<...>",
    ):
        assert prefix in ADR_TEXT, prefix
    assert "**No existing object moves.**" in ADR_FLAT
    assert "It does not rewrite ADR-0036's accepted text" in ADR_FLAT


def test_adr_0036_accepted_text_is_not_rewritten() -> None:
    """The accepted prefixes stay in ADR-0036; the amendment lives beside it."""
    text = ADR_0036.read_text(encoding="utf-8")
    assert "licensed/bronze/sharadar/<dataset>/objects/sha256/*" in text
    assert "ADR-0037" not in text.split("The condition above has since been satisfied", 1)[0]


def test_the_declaration_uses_the_amended_prefixes_only() -> None:
    hcl = "\n".join(
        line
        for line in POLICIES_TF.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    for prefix in (
        "/bronze/sharadar/tickers/production/objects/sha256/*",
        "/bronze/sharadar/tickers/production/acquisitions/*",
        "/bronze/_production_claims/*",
    ):
        assert prefix in hcl, prefix
    # the earlier claim namespace appears exactly once outside comments: in the foreign deny list
    foreign = hcl.split("production_foreign_bronze_objects = [", 1)[1].split("]", 1)[0]
    assert foreign.count("/bronze/_acquisition_claims/*") == 1
    assert hcl.count("/bronze/_acquisition_claims/*") == 1


def test_the_adr_carries_no_private_value() -> None:
    assert HEX_64.search(ADR_TEXT) is None
    assert TWELVE_DIGITS.search(ADR_TEXT) is None
    assert REAL_ARN.search(ADR_TEXT) is None


@pytest.mark.parametrize("path", [README, CLAUDE])
def test_status_documents_record_the_adr_as_proposed(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert re.search(r"ADR-0037[^\n]{0,200}PROPOSED — NOT IN FORCE", text) is not None
