"""ADR-0037 governance: a narrow amendment of ADR-0036's production prefixes, accepted on PR #94.

The amendment moves production Bronze under namespaces no earlier package writes. These
checks hold the document to its own claims -- the preserved conditional status beside the
post-merge note, a narrow amendment that rewrites nothing, the traced layouts named, the
disjoint prefixes stated -- and hold the offline declaration to the amended prefixes. The
proof that the prefixes are disjoint from the merged key builders' output lives in
``test_production_infrastructure.py`` and ``test_production_runtime_locator.py``.
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


def test_the_adr_keeps_its_conditional_status_and_records_the_merge() -> None:
    """The pre-merge condition is preserved as written; the note beside it records the event."""
    assert "Status: PROPOSED — NOT IN FORCE" in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert (
        "a narrow amendment of ADR-0036's production Bronze prefixes and nothing else" in ADR_FLAT
    )
    assert "Nothing was run to produce this decision" in ADR_FLAT
    assert "The condition above has since been satisfied." in ADR_FLAT
    assert "PR #94 merged" in ADR_FLAT and "2026-09-12T12:16:47Z" in ADR_FLAT
    assert "7d7cad34454a670c701e615bb7d26a70533118ee" in ADR_TEXT
    assert "066a93d8780aa6fc06354ed096fa69c34496b10d" in ADR_TEXT
    assert "70e365554fa8ad3b8aa5a4b37bbf56ad2b61bc4c" in ADR_TEXT
    assert "ADR-0037 is therefore ACCEPTED / IN FORCE" in ADR_FLAT.replace("**", "")
    assert "Acceptance applied nothing and materialized nothing" in ADR_FLAT


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
def test_status_documents_record_the_adr_as_accepted_on_pr_94(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert (
        re.search(r"ADR-0037[^\n]{0,200}ACCEPTED / IN FORCE[^\n]{0,80}PR #94 merged", text)
        is not None
    )
    assert re.search(r"ADR-0037[^\n]{0,200}PROPOSED — NOT IN FORCE", text) is None
    assert "NOT PLANNED / NOT APPLIED" in text
    assert "HALTED_PROCESSING_NOT_IMPLEMENTED" in text


def test_the_production_key_builders_spell_the_amended_namespaces() -> None:
    from kalpamani.data.production.sharadar import keys

    digest = "ab" * 32
    assert keys.production_payload_key_for_digest(
        dataset="tickers", content_sha256=digest
    ).logical_key == (f"licensed/bronze/sharadar/tickers/production/objects/sha256/{digest}")
    assert keys.production_claim_key(
        payload_digest=digest, run_id="r-1", claim=b"{}"
    ).logical_key == (f"licensed/bronze/_production_claims/{digest}/r-1.json")
    assert keys.run_locator_logical_key("r-1") == "licensed/bronze/sharadar/_indexes/r-1.json"
