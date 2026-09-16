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
    # The acceptance event is recorded under the clause, on the ADR-0050 convention: the
    # original status line stays, and the paragraph after it names the merge.
    assert "The condition above has since been satisfied" in ADR_PLAIN
    assert "bc16801efbfd9d8c5a9b947f888da64d7dadf72a" in ADR_TEXT
    assert (
        "ADR-0051 is therefore ACCEPTED / IN FORCE exactly as the clause above states" in ADR_PLAIN
    )
    assert "Acceptance selected none of O-1" in ADR_PLAIN
    assert "acceptance of this ADR is not acceptance of that pull request" in ADR_PLAIN


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
        assert "ACCEPTED / IN FORCE" in matching[0], name
        assert "PR #111 merged" in matching[0], name
        assert "PROPOSED — NOT IN FORCE" not in matching[0], name
        assert "PR #112 OPEN / unmerged" in matching[0], name
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


def test_the_adr_records_slice_2_as_an_implementation_event_and_not_an_acceptance() -> None:
    assert "## 9. Slice 2" in ADR_TEXT
    assert "records no acceptance event and takes no decision" in ADR_PLAIN
    assert "The status line of this ADR is unchanged by it" in ADR_PLAIN
    assert "as a synthetic fixture, not as owner selections" in ADR_PLAIN
    assert "establishes software behaviour only" in ADR_PLAIN
    assert "no bridge reads production Gold objects" in ADR_PLAIN
    assert "superseded in part by" in ADR_PLAIN
    assert "fourth" in ADR_PLAIN and "vendor-scoped package" in ADR_PLAIN
    assert "Status: " + PROPOSED in ADR_TEXT
    for module in ("resolution", "dataset", "m0", "report"):
        assert f"kalpamani.data.exploratory.{module}" in ADR_TEXT
        assert (REPO_ROOT / "src/kalpamani/data/exploratory" / f"{module}.py").is_file()
    assert (REPO_ROOT / "tests/unit/test_m0_exploratory_path.py").is_file()
    assert (REPO_ROOT / "tests/fixtures/m0_exploratory.py").is_file()


def test_the_adr_records_correction_1_of_the_m0_path_and_the_governance_correction() -> None:
    assert "## 10. Review correction 1 of the synthetic M0 path" in ADR_TEXT
    assert "ce1f793b9ca4205c56a1ff04026d38cee14c7f2c" in ADR_TEXT
    assert "40 failed there and 1 passed" in ADR_PLAIN
    for phrase in (
        "SKIPPED_EXITED_THIS_SESSION",
        "cash_in_lieu",
        "REFUSED_INVALID_CONFIGURATION",
        "REFUSED_MALFORMED_DATA_KIND",
        "liquidation-inclusive",
        "transaction journal",
        "accepts the vocabulary and isolation decision only",
        "does not imply acceptance",
    ):
        assert phrase in ADR_PLAIN, phrase
    assert (REPO_ROOT / "tests/unit/test_m0_exploratory_correction_1.py").is_file()
    from kalpamani.data.exploratory import m0

    assert m0.HISTORY_SESSIONS == 252
    assert m0.Skip.SKIPPED_EXITED_THIS_SESSION.value == "SKIPPED_EXITED_THIS_SESSION"
    assert m0.RunRefusal.REFUSED_MALFORMED_DATA_KIND.value == "REFUSED_MALFORMED_DATA_KIND"


def test_the_adr_records_correction_2_and_the_code_carries_the_corrected_o7_o10_mapping() -> None:
    assert "## 11. Review correction 2 of the synthetic M0 path" in ADR_TEXT
    assert "95be27e6b3b0947294bee95d532b4f3b4f5d592a" in ADR_TEXT
    for phrase in (
        "recorded, not priced",
        "NEXT_OBSERVED_CLOSE",
        "UNRESOLVED",
        "engineering assumption pending an owner selection",
        "O-7 = events",
        "O-10 = sizing and sequencing",
        "No owner decision is selected by this correction",
    ):
        assert phrase in ADR_PLAIN, phrase
    from kalpamani.data.exploratory import m0

    assert [c.value for c in m0.EventHandlingChoice] == ["EVENT_BLIND", "WAIT_FOR_EVENT_ENTITY"]
    assert not hasattr(m0, "SizingPolicyChoice") and not hasattr(m0, "FinalFillPolicyChoice")
    assert {"o7_event_handling", "o10_sizing_and_sequencing"} <= set(m0.OwnerSelections.__slots__)
    assert [p.value for p in m0.SettlementPolicy] == [
        "PENDING",
        "NONE_DUE",
        "EX_SESSION_CLOSE",
        "NEXT_OBSERVED_CLOSE",
        "UNRESOLVED",
    ]


def test_the_adr_records_the_adapter_slice_and_the_module_exists() -> None:
    assert "## 12. Slice 3" in ADR_TEXT
    for phrase in (
        "never an A1 VerifiedPublication",
        "REVISIONS_EXCLUDED_BY_TIME",
        "CONFIGURATION_UNBOUND",
        "history_sessions must be 252",
        "Gold is refused by name",
        "an approximation stated in the module",
        "reads no licensed object",
    ):
        assert phrase in ADR_PLAIN, phrase
    assert (REPO_ROOT / "src/kalpamani/data/exploratory/adapter.py").is_file()
    assert (REPO_ROOT / "tests/unit/test_exploratory_adapter.py").is_file()
    assert (REPO_ROOT / "tests/fixtures/m0_build_artifacts.py").is_file()
    from kalpamani.data.exploratory import adapter

    assert adapter.REQUIRED_HISTORY_SESSIONS == 252
    assert adapter.MANIFEST_CONTRACT == "kalpamani-production-build-manifest/v1"
    assert "NOT_A_SILVER_ARTIFACT" in [d.value for d in adapter.AdapterDefect]
