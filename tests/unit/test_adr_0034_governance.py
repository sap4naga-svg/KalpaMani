"""ADR-0034 governance: a partial G1 decision recorded in decision language, and nothing else.

ADR-0034 records the owner's provider selection for the domains the qualification package
acquired. The one property that matters most is what the document must **never** contain:
the private combined report's contents. Sharadar Terms section 8 (ADR-0008) bars disclosing
conclusions about the data's fitness, and ADR-0018 section 11.3 keeps P1-P9 results out of Git.
So the checks here are mostly absences -- no evaluative status token, no measurement, no
identifier-shaped value, no account, no digest -- plus the presence of the decision itself, its
restrictions, and the gates it leaves open.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from kalpamani.data.contracts import vocabulary

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0034-select-sharadar-for-initial-equity-research-domains.md"
ADR_0035: Final = DECISIONS / "ADR-0035-initial-breakout-long-research-dataset-ingestion-design.md"
README: Final = PROJECT_ROOT / "README.md"
CLAUDE: Final = PROJECT_ROOT / "CLAUDE.md"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""
ADR_FLAT: Final = " ".join(ADR_TEXT.split())

#: Evaluative status tokens that live only in the private report. None may appear in a
#: decision document, in any casing, because the ladder is the finding.
EVALUATIVE_TOKENS: Final = tuple(
    sorted(
        {
            "PARTIALLY_TESTED",
            "INSUFFICIENT_EVIDENCE",
            "DOCUMENTATION_RESOLVED",
            "TESTED",
        }
    )
)
# ``DEFERRED`` is deliberately absent from the list: it is also the CONTROL publication
# status every status block carries, so its presence proves nothing about the report.

#: Shapes that would mean private material leaked into the decision record.
IDENTIFIER_SHAPED: Final = re.compile(r"\b(?:runa|runb|assess)[a-z0-9]*-\d{8}-[a-z0-9]+\b")
TWELVE_DIGITS: Final = re.compile(r"\b\d{12}\b")
HEX_64: Final = re.compile(r"\b[0-9a-f]{64}\b")
ARN: Final = re.compile(r"\barn:aws\b")
S3_URI: Final = re.compile(r"\bs3://")
PRIVATE_FILENAME: Final = re.compile(r"binding-v\d\.json|allocation-\d{8}T\d{6}Z")


# -- the decision exists and claims no authority it has not been given --------


def test_the_adr_exists_at_its_exact_path() -> None:
    assert ADR.is_file()


def test_exactly_one_adr_0034_exists() -> None:
    assert [path.name for path in sorted(DECISIONS.glob("ADR-0034-*.md"))] == [ADR.name]


def test_the_adr_carries_a_conditional_acceptance_status() -> None:
    assert "Status: PROPOSED — NOT IN FORCE" in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "independently reviewed and merged" in ADR_FLAT


def test_the_adr_states_that_nothing_was_run_to_produce_it() -> None:
    assert "Nothing was run to produce this decision" in ADR_FLAT
    for claim in ("no provider request", "no acquisition", "no assessment", "no backtest"):
        assert claim in ADR_FLAT, claim


def test_the_adr_authorizes_no_execution() -> None:
    assert "Accepting this ADR authorizes no execution" in ADR_FLAT
    assert "authorizes no ingestion, backfill or update" in ADR_FLAT
    assert "no credential use" in ADR_FLAT


def test_the_adr_supersedes_and_amends_nothing() -> None:
    assert "This ADR supersedes no earlier decision and amends no earlier ADR document" in ADR_FLAT


@pytest.mark.parametrize("number", [f"{n:04d}" for n in range(1, 34)])
def test_no_earlier_adr_mentions_this_one(number: str) -> None:
    earlier = sorted(DECISIONS.glob(f"ADR-{number}-*.md"))
    assert earlier, number
    for path in earlier:
        assert "ADR-0034" not in path.read_text(encoding="utf-8")


# -- the decision itself ------------------------------------------------------


def test_the_decision_names_the_three_domains_and_their_dispositions() -> None:
    assert "Sharadar is selected as the provider for two domains" in ADR_FLAT
    assert "`tickers`" in ADR_TEXT and "`stocks`" in ADR_TEXT and "`actions`" in ADR_TEXT
    assert "selected, and its use is restricted" in ADR_FLAT
    assert ADR_FLAT.count("**GATED**") >= 2
    assert "announcement-based signal" in ADR_FLAT
    assert "spinoff treatment" in ADR_FLAT


def test_the_decision_keeps_g2_open_with_the_target_profile() -> None:
    assert "G2 stays OPEN" in ADR_FLAT
    assert vocabulary.InformationSetProfile.PROVIDER_REALISTIC_PIT.value in ADR_TEXT
    assert "subject to documented availability rules" in ADR_FLAT.lower() or (
        "documented per-dataset availability rules" in ADR_FLAT
    )


def test_the_decision_leaves_every_other_domain_open() -> None:
    assert "G1 stays **OPEN** for fundamentals" in ADR_FLAT
    assert "G3 stays **CLOSED**" in ADR_FLAT


def test_the_decision_uses_the_permitted_public_facts_only() -> None:
    for citation in ("PSR-SHD-094", "PSR-SHD-112"):
        assert citation in ADR_TEXT, citation
    assert vocabulary.InformationOrigin.PROVIDER_DERIVED.value in ADR_TEXT


def test_the_adr_points_at_the_ingestion_design() -> None:
    assert ADR_0035.name in ADR_TEXT


def test_both_adrs_become_effective_on_one_merge() -> None:
    assert "become effective together on its single independently reviewed merge" in ADR_FLAT
    assert "ADR-0035 depends on this decision" in ADR_FLAT
    assert "separate merge" not in ADR_FLAT.lower()


def test_the_disclosure_history_is_recorded_not_denied() -> None:
    """Repository non-disclosure is asserted; broader non-disclosure is not, because it is false."""
    assert "not recorded in this repository" in ADR_FLAT.lower()
    assert "sharing the assessment output with an external AI service" in ADR_FLAT
    assert "makes no claim either way" in ADR_FLAT
    assert "disclosed nowhere" not in ADR_FLAT.lower()
    assert "not to any ai session" not in ADR_FLAT.lower()
    assert "stays private" not in ADR_FLAT.lower()


# -- what must never be in a decision record ----------------------------------


def test_the_adr_records_no_evaluative_finding() -> None:
    assert "records no evaluative finding" in ADR_FLAT
    for token in EVALUATIVE_TOKENS:
        assert re.search(rf"\b{token}\b", ADR_TEXT) is None, token


def test_the_adr_carries_no_private_value() -> None:
    assert IDENTIFIER_SHAPED.search(ADR_TEXT) is None
    assert TWELVE_DIGITS.search(ADR_TEXT) is None
    assert HEX_64.search(ADR_TEXT) is None
    assert ARN.search(ADR_TEXT) is None
    assert S3_URI.search(ADR_TEXT) is None
    assert PRIVATE_FILENAME.search(ADR_TEXT) is None


def test_the_adr_carries_no_measurement_or_subject() -> None:
    for word in ("row count", "rows delivered", "measurement:", "subject list", "coverage ratio"):
        assert word not in ADR_FLAT.lower(), word


# -- the status documents carry the decision as PROPOSED, not as in force -------


@pytest.mark.parametrize("path", [README, CLAUDE])
def test_status_documents_record_the_adr_as_proposed(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "ADR-0034" in text
    assert re.search(r"ADR-0034[^\n]{0,400}PROPOSED", text) is not None
    assert "partial" in text.lower()


@pytest.mark.parametrize("path", [README, CLAUDE])
def test_status_documents_record_the_disclosure_history_accurately(path: Path) -> None:
    section = (
        path.read_text(encoding="utf-8")
        .split("### The completed Run B acquisition and the completed combined assessment")[1]
        .split("\n### ")[0]
    )
    flat = " ".join(section.split()).lower()
    assert "not recorded in this repository" in flat
    assert "external ai service (chatgpt)" in flat
    assert "not established here" in flat
    assert "disclosed nowhere" not in flat
    assert "not to any ai session" not in flat
    assert "successful-run subtotal" in flat
    assert "excludes the refused assessment invocation" in flat
    assert "before any evidence read" not in flat
