"""ADR-0051 says what the exploratory contracts do, and they say the same.

The research-only vocabulary; assumed versus evidenced availability; the declared limitations;
non-satisfaction of qualification, G2 and promotion; acceptance apart from execution; the
pending decisions; and the status rows that keep the ADR proposed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from kalpamani.data.exploratory import admission, contracts, vocabulary

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = REPO_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0051-exploratory-hindsight-research-profile-and-isolation.md"
ADR_TEXT: Final = ADR.read_text(encoding="utf-8")
ADR_PLAIN: Final = " ".join(ADR_TEXT.split()).replace("**", "").replace("`", "")
PROPOSED: Final = (
    "PROPOSED — NOT IN FORCE. No authority until the pull request introducing this ADR is"
)


def test_the_adr_exists_is_proposed_and_keeps_acceptance_apart_from_execution() -> None:
    assert [p.name for p in sorted(DECISIONS.glob("ADR-0051-*.md"))] == [ADR.name]
    assert "Status: " + PROPOSED in ADR_TEXT
    assert "not to be rewritten as though this decision had authority" in ADR_PLAIN
    assert "Acceptance authorizes no execution and grants no permission" in ADR_PLAIN
    assert "## 5. Acceptance and execution authority are separate" in ADR_TEXT
    assert "Nothing was run to produce this decision" in ADR_PLAIN
    assert "The condition above has since been satisfied" not in ADR_PLAIN


def test_the_adr_defines_the_vocabulary_as_research_only_and_the_code_agrees() -> None:
    assert "ExploratoryProfile.EXPLORATORY_HINDSIGHT" in ADR_PLAIN
    assert "ExploratoryDerivation.AS_DATED" in ADR_PLAIN
    assert (
        "not members of the accepted InformationSetProfile or ProviderBoundDerivation" in ADR_PLAIN
    )
    assert [m.value for m in vocabulary.ExploratoryProfile] == ["EXPLORATORY_HINDSIGHT"]
    assert [m.value for m in vocabulary.ExploratoryDerivation] == ["AS_DATED"]
    assert (
        not {m.value for m in vocabulary.ExploratoryProfile} & vocabulary.PRODUCTION_PROFILE_NAMES
    )
    assert (
        not {m.value for m in vocabulary.ExploratoryDerivation}
        & vocabulary.PRODUCTION_DERIVATION_NAMES
    )


def test_the_adr_separates_assumed_from_evidenced_availability() -> None:
    assert "### 2.2 Assumed availability is not evidenced availability" in ADR_TEXT
    assert "availability_basis = ASSUMED_HISTORICAL" in ADR_PLAIN
    assert "Nothing in this ADR changes, relaxes or reinterprets P-2 or P-3" in ADR_PLAIN
    assert vocabulary.AvailabilityBasis.EVIDENCED.value == "EVIDENCED"
    assert contracts.ExploratoryDefect.EVIDENCED_BASIS_CLAIMED.value == "EVIDENCED_BASIS_CLAIMED"


def test_the_adr_names_the_limitations_the_code_requires() -> None:
    for member in vocabulary.ExploratoryLimitation:
        assert member.value in ADR_TEXT
    assert vocabulary.MANDATORY_LIMITATIONS == frozenset(
        {
            vocabulary.ExploratoryLimitation.REVISION_LOOKAHEAD,
            vocabulary.ExploratoryLimitation.CURRENT_ATTRIBUTE_LOOKAHEAD,
            vocabulary.ExploratoryLimitation.TERMINAL_VALUATION_OPTIMISTIC,
            vocabulary.ExploratoryLimitation.NO_INTRADAY_INSTANT,
        }
    )
    assert "are mandatory" in ADR_PLAIN
    assert "EVENT_BLIND" in ADR_PLAIN and "BENCHMARK_SELF_REFERENCE" in ADR_PLAIN


def test_the_adr_denies_qualification_g2_and_promotion() -> None:
    assert "### 2.4 What an exploratory result never satisfies" in ADR_TEXT
    assert "production_qualification = NONE" in ADR_PLAIN
    assert (
        "No exploratory result satisfies P1" in ADR_PLAIN
        and "any G2 criterion (ADR-0035 G2-A" in ADR_PLAIN
        and "any provider qualification, or any promotion criterion" in ADR_PLAIN
    )
    assert list(vocabulary.QualificationClaim) == [vocabulary.QualificationClaim.NONE]
    assert (
        "never a production rule, a Cockpit AVAILABLE figure or a point-in-time claim" in ADR_PLAIN
    )


def test_the_adr_names_the_four_contracts_the_code_defines() -> None:
    assert contracts.PROVENANCE_CONTRACT_ID in ADR_TEXT
    assert contracts.PUBLICATION_CONTRACT_ID in ADR_TEXT
    assert contracts.INPUT_SET_CONTRACT_ID in ADR_TEXT
    assert admission.RESEARCH_SPECIFICATION_CONTRACT_ID in ADR_TEXT
    assert "REFUSED_PRODUCTION_CONSUMER" in ADR_TEXT
    assert admission.AdmissionOutcome.REFUSED_PRODUCTION_CONSUMER.value in ADR_TEXT
    assert "There is no duck-typed opt-in" in ADR_PLAIN
    assert "not cryptographic ones" in ADR_PLAIN


def test_the_adr_keeps_the_decisions_pending_and_the_scope_bounded() -> None:
    assert "## 6. Decisions explicitly pending" in ADR_TEXT
    for item in ("O-1", "O-2", "O-5", "O-6", "D-1"):
        assert item in ADR_TEXT
    assert "the rehearsal path stays CLOSED" in ADR_PLAIN
    assert "## 4. What this ADR does not decide or implement" in ADR_TEXT
    for absent in (
        "bridge from production Gold",
        "benchmark",
        "backtest runner",
        "portfolio ledger",
    ):
        assert absent in ADR_PLAIN
    assert "backtesting stays NOT STARTED" in ADR_PLAIN


def test_the_status_documents_carry_one_proposed_row_each_and_agree() -> None:
    rows = {}
    for name in ("CLAUDE.md", "README.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        matching = [line for line in text.splitlines() if "[ADR-0051](docs/decisions/" in line]
        assert len(matching) == 1, name
        assert "PROPOSED — NOT IN FORCE" in matching[0], name
        assert "ACCEPTED / IN FORCE" not in matching[0], name
        rows[name] = matching[0]
    assert rows["CLAUDE.md"] == rows["README.md"]


def test_the_adr_records_review_correction_1_and_the_regressions_exist() -> None:
    assert "## 8. Review correction 1" in ADR_TEXT
    assert "56556d9e3d823323c8124913d0754b9d0b0af7d3" in ADR_TEXT
    assert "reproduced on that head by a regression before it was corrected" in ADR_PLAIN
    assert "admit never raises" in ADR_PLAIN
    assert "No refusal code was added or removed" in ADR_PLAIN
    assert (REPO_ROOT / "tests" / "unit" / "test_exploratory_isolation_correction_1.py").is_file()
    assert "at least the four mandatory limitations" in ADR_PLAIN
