"""ADR-0041 governance: a proposed, narrow amendment adding the ticker-less request form.

These checks hold the document to its own claims -- proposed and not in force, one request
form beside the unchanged accepted one, documented versus assumed provider semantics, the
effectiveness and execution gates -- and hold the offline adapter and the register rows to
the shape the document describes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from kalpamani.data.ingest.sharadar import datasets
from kalpamani.data.production.sharadar import provider

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0041-production-provider-request-form.md"
REGISTER: Final = PROJECT_ROOT / "docs" / "phase3" / "provider-source-register.md"
README: Final = PROJECT_ROOT / "README.md"
CLAUDE: Final = PROJECT_ROOT / "CLAUDE.md"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""
ADR_FLAT: Final = " ".join(ADR_TEXT.split())

HEX_64: Final = re.compile(r"\b[0-9a-f]{64}\b")
TWELVE_DIGITS: Final = re.compile(r"\b\d{12}\b")
REAL_ARN: Final = re.compile(r"\barn:aws\b")
PROPOSED: Final = "PROPOSED " + chr(0x2014) + " NOT IN FORCE"


def test_the_adr_exists_and_is_the_only_0041() -> None:
    assert ADR.is_file()
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0041-*.md"))] == [ADR.name]


def test_the_adr_carries_a_conditional_acceptance_status_and_the_gates() -> None:
    assert "Status: " + PROPOSED in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "a narrow amendment of ADR-0009's request model" in ADR_FLAT
    assert "Nothing was run to produce this decision" in ADR_FLAT
    assert 'not a "test" request, not the published test key' in ADR_FLAT
    assert "## 5. Effectiveness and execution gates" in ADR_TEXT
    assert "acceptance authorizes no execution" in ADR_FLAT
    assert "inclusivity is an assumption" in ADR_FLAT
    assert "Multi-page one-session cross-sections are unsupported" in ADR_FLAT
    assert "NOT AUTHORIZED / NOT RUN" in ADR_FLAT


def test_the_adr_separates_documented_from_assumed_and_cites_the_register() -> None:
    for claim in ("PSR-SHD-129", "PSR-SHD-130", "PSR-SHD-131", "PSR-SHD-132", "PSR-SHD-133"):
        assert claim in ADR_TEXT, claim
    assert "`ticker` defaults to `all`" in ADR_FLAT
    assert "inclusivity of `from`/`to` is not stated" in ADR_FLAT
    assert "no terminal-page signal and no documented stable order across offsets" in ADR_FLAT
    assert "`sort` stays **forbidden**" in ADR_FLAT
    register = REGISTER.read_text(encoding="utf-8")
    for claim, url in (
        ("PSR-SHD-129", "https://sharadar.com/docs/stocks"),
        ("PSR-SHD-130", "https://sharadar.com/docs/actions"),
        ("PSR-SHD-131", "https://sharadar.com/docs/tickers"),
        ("PSR-SHD-132", "https://sharadar.com/docs/auth"),
        ("PSR-SHD-133", "https://sharadar.com/docs/stocks"),
    ):
        row = next((line for line in register.splitlines() if line.startswith(f"| `{claim}`")), "")
        assert row and url in row, claim
    assert "api.sharadar.com` was not called" in register


def test_the_implementation_matches_the_document() -> None:
    assert datasets.CROSS_SECTION_PARAMETER_ALLOWLIST == datasets.QUERY_PARAMETER_ALLOWLIST - {
        "ticker"
    }
    assert datasets.QUERY_PARAMETER_ALLOWLIST == frozenset(
        {"api_key", "format", "ticker", "from", "to", "limit", "skip"}
    )
    assert "sort" in datasets.FORBIDDEN_QUERY_PARAMETERS
    assert provider.ONE_ATTEMPT.max_attempts == 1
    assert provider.PRODUCTION_FORMAT is datasets.ResponseFormat.CSV
    for token in (
        "DATASET_UNSUPPORTED",
        "WINDOW_REQUIRED",
        "WINDOW_NOT_ALLOWED",
        "WINDOW_MALFORMED",
        "PAGE_MALFORMED",
    ):
        assert token in {member.value for member in provider.ProviderRefusal}
    # The accepted form still names a ticker on every request.
    assert "ticker" in datasets.SharadarRequest.__dataclass_fields__
    assert "ticker" not in datasets.CrossSectionRequest.__dataclass_fields__


def test_the_adr_carries_no_private_value() -> None:
    assert HEX_64.search(ADR_TEXT) is None
    assert TWELVE_DIGITS.search(ADR_TEXT) is None
    assert REAL_ARN.search(ADR_TEXT) is None
    assert "test-api-key" not in ADR_TEXT


@pytest.mark.parametrize("path", [README, CLAUDE])
def test_status_documents_record_the_adr_as_proposed(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert re.search(r"ADR-0041[^\n]{0,200}" + re.escape(PROPOSED), text) is not None
    assert "ADR-0041 (production provider request form):     " + PROPOSED in text
    assert "SCRIPTED-TRANSPORT-ONLY" in text
