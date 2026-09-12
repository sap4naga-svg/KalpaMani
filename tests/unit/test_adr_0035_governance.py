"""ADR-0035 governance: an ingestion design that reuses accepted contracts and implements nothing.

The design names vocabulary members, contract rules and modules that already exist; a design
that cited a member the vocabulary does not have would be describing a system other than this
one. So the checks here resolve every cited vocabulary token against the real enums, hold the
one proposed addition to be *absent* (it is proposed, not implemented), and hold the document to
the same privacy boundary as ADR-0034: no evaluative finding from the private report, no private
value. The acceptance criteria are checked for presence, not for satisfaction -- none is
satisfied by the merge of this ADR.
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
ADR: Final = DECISIONS / "ADR-0035-initial-breakout-long-research-dataset-ingestion-design.md"
ADR_0034: Final = DECISIONS / "ADR-0034-select-sharadar-for-initial-equity-research-domains.md"
README: Final = PROJECT_ROOT / "README.md"
CLAUDE: Final = PROJECT_ROOT / "CLAUDE.md"
SRC_DATA: Final = PROJECT_ROOT / "src" / "kalpamani" / "data"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""
ADR_FLAT: Final = " ".join(ADR_TEXT.split())

#: ``Enum.Member`` references the design makes. Each must resolve against the real vocabulary.
CITED_MEMBERS: Final = tuple(sorted(set(re.findall(r"\b([A-Z][A-Za-z]+)\.([A-Z_]+)\b", ADR_TEXT))))

#: The members the design proposes and must NOT yet have implemented.
PROPOSED_MEMBERS: Final = (
    ("UniverseExclusionReason", "UNRESOLVED_CORPORATE_ACTION"),
    ("UniverseExclusionReason", "ATTRIBUTE_UNAVAILABLE"),
    ("ProviderBoundDerivation", "VENDOR_DATE_UPPER_BOUND"),
    ("ProviderBoundDerivation", "VERSION_EVIDENCE_UPPER_BOUND"),
)

EVALUATIVE_TOKENS: Final = (
    "PARTIALLY_TESTED",
    "INSUFFICIENT_EVIDENCE",
    "DOCUMENTATION_RESOLVED",
    "TESTED",
)
IDENTIFIER_SHAPED: Final = re.compile(r"\b(?:runa|runb|assess)[a-z0-9]*-\d{8}-[a-z0-9]+\b")
TWELVE_DIGITS: Final = re.compile(r"\b\d{12}\b")
HEX_64: Final = re.compile(r"\b[0-9a-f]{64}\b")
ARN: Final = re.compile(r"\barn:aws\b")


# -- existence and authority --------------------------------------------------


def test_the_adr_exists_at_its_exact_path() -> None:
    assert ADR.is_file()


def test_exactly_one_adr_0035_exists() -> None:
    assert [path.name for path in sorted(DECISIONS.glob("ADR-0035-*.md"))] == [ADR.name]


def test_the_adr_carries_a_conditional_acceptance_status() -> None:
    assert "Status: PROPOSED — NOT IN FORCE" in ADR_TEXT
    assert "No authority until the pull request introducing this ADR is" in ADR_FLAT
    assert "architecture, contracts and acceptance criteria only" in ADR_FLAT


def test_the_adr_states_that_nothing_was_run_and_authorizes_no_execution() -> None:
    assert "Nothing was run to produce this design" in ADR_FLAT
    assert "Accepting this ADR authorizes no execution" in ADR_FLAT
    assert "no read of the licensed store" in ADR_FLAT


def test_the_adr_supersedes_and_amends_nothing() -> None:
    assert "This ADR supersedes no earlier decision and amends no earlier ADR document" in ADR_FLAT


@pytest.mark.parametrize("number", [f"{n:04d}" for n in range(1, 34)])
def test_no_earlier_adr_mentions_this_one(number: str) -> None:
    earlier = sorted(DECISIONS.glob(f"ADR-{number}-*.md"))
    assert earlier, number
    for path in earlier:
        assert "ADR-0035" not in path.read_text(encoding="utf-8")


def test_the_adr_is_built_on_adr_0034() -> None:
    assert ADR_0034.name in ADR_TEXT


# -- it describes this system, not another one --------------------------------


def test_every_cited_vocabulary_member_resolves() -> None:
    assert CITED_MEMBERS, "the design cites no vocabulary members"
    for enum_name, member in CITED_MEMBERS:
        if (enum_name, member) in PROPOSED_MEMBERS:
            continue
        enum = getattr(vocabulary, enum_name, None)
        if enum is None:
            # Not every ``Word.WORD`` is a vocabulary reference (e.g. a module path);
            # only real enums are checked.
            continue
        assert hasattr(enum, member), f"{enum_name}.{member} is cited but does not exist"


@pytest.mark.parametrize("proposed", PROPOSED_MEMBERS, ids=lambda pair: pair[1])
def test_each_proposed_member_is_cited_and_not_yet_implemented(proposed: tuple[str, str]) -> None:
    enum_name, member = proposed
    assert f"{enum_name}.{member}" in ADR_TEXT or f"`{member}`" in ADR_TEXT
    assert not hasattr(getattr(vocabulary, enum_name), member), (
        "the design proposes this member; implementing it is a later gate's work"
    )


@pytest.mark.parametrize(
    "module",
    [
        "ingest/bronze.py",
        "ingest/publication.py",
        "normalize/silver.py",
        "curate/universe.py",
        "curate/adjustment.py",
        "curate/lineage.py",
        "curate/build.py",
        "quality/plan.py",
        "contracts/manifest.py",
    ],
)
def test_every_reused_module_exists(module: str) -> None:
    assert (SRC_DATA / module).is_file(), module
    assert module.split("/")[-1] in ADR_TEXT, module


def test_the_design_covers_every_required_topic() -> None:
    for heading in (
        "Immutable source snapshots",
        "Versioning",
        "Availability timestamps",
        "Historical-universe construction",
        "Identifier changes",
        "Corporate-action handling",
        "Quality checks",
        "Reproducibility",
    ):
        assert heading in ADR_TEXT, heading


def test_the_availability_rules_are_ordered_and_gated() -> None:
    for rule in ("rule P-1", "rule P-2", "rule P-3"):
        assert rule in ADR_TEXT, rule
    assert vocabulary.ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND.value in ADR_TEXT
    assert vocabulary.ProviderBoundDerivation.DELIVERY_WINDOW.value in ADR_TEXT
    assert "admits **nothing** under P-2" in ADR_FLAT
    # P-1 is a bound, never an exact instant, and acceptance is not evidence.
    assert "a **bound, never an exact instant**" in ADR_FLAT
    assert "no rule in this design writes an exact `provider_available_time`" in ADR_FLAT
    assert "none of which owner acceptance can supply" in ADR_FLAT
    assert "Three separate prerequisites" in ADR_FLAT
    # P-3 needs version-specific evidence; a schedule alone never dates a retrieved version.
    assert "version-specific evidence" in ADR_FLAT
    assert "do not establish that the version retrieved today is that version" in ADR_FLAT
    # P-3: the bound comes from the evidence, never from a schedule; gated on expressibility.
    assert "The bound is taken from the evidence itself, never from a schedule" in ADR_FLAT
    assert (
        "only when the evidence explicitly establishes that the matching version was available"
        in ADR_FLAT
    )
    assert "conservative end of that date interval" in ADR_FLAT
    assert "until then the row falls to P-2" in ADR_FLAT
    # Revisions never inherit availability.
    assert "A revision never inherits an earlier version's availability" in ADR_FLAT


def test_the_decision_cutoff_separates_eligibility_from_completeness() -> None:
    assert "`decision_time(d)`" in ADR_TEXT
    assert "no clause may depend on session `d`'s completed bar" in ADR_FLAT
    assert "Decision-time eligibility and later completeness are separate questions" in ADR_FLAT
    assert "Trades during session `d` may occur only in securities that are members" in ADR_FLAT


def test_historical_attributes_are_not_inherited_from_a_current_snapshot() -> None:
    assert "A current snapshot never silently becomes historical truth" in ADR_FLAT
    for attribute in ("exchange", "security type", "listing bounds", "sector", "industry"):
        assert attribute in ADR_FLAT, attribute
    assert "`ATTRIBUTE_UNAVAILABLE`" in ADR_TEXT
    assert "**G2-H**" in ADR_TEXT


def test_the_adversarial_acceptance_examples_exist_and_are_not_claimed_as_runtime_proof() -> None:
    assert "### 3.9 Adversarial acceptance examples" in ADR_TEXT
    for fixture in (
        "T-1",
        "T-2",
        "T-3",
        "T-4",
        "T-5",
        "T-6",
        "D-1",
        "D-2",
        "D-3",
        "C-1",
        "C-2",
        "C-3",
        "A-1",
        "A-2",
        "V-1",
    ):
        assert f"**{fixture}**" in ADR_TEXT, fixture
    assert "proves nothing about runtime correctness" in ADR_FLAT
    assert "none of these fixtures exists yet" in ADR_FLAT


def test_both_adrs_become_effective_on_one_merge_and_0035_depends_on_0034() -> None:
    assert "proposed on the same pull request as ADR-0034 and depends on it" in ADR_FLAT
    assert "single independently reviewed merge" in ADR_FLAT
    assert "separate merge" not in ADR_FLAT.lower()


def test_the_gated_uses_of_adr_0034_are_enforced_by_the_design() -> None:
    assert "never adjusted for" in ADR_FLAT
    assert "no announcement anchor exists" in ADR_FLAT
    assert vocabulary.AdjustmentPolicy.SPLIT_ONLY.value in ADR_TEXT


def test_the_acceptance_criteria_are_all_present_and_labelled() -> None:
    for label in ("G2-A", "G2-B", "G2-C", "G2-D", "G2-E", "G2-F", "G2-G", "G2-H"):
        assert f"**{label}**" in ADR_TEXT, label
    for n in range(1, 13):
        assert f"**I-{n}**" in ADR_TEXT, f"I-{n}"
    assert "Implementable now" in ADR_TEXT and "Needs additional sources" in ADR_TEXT


# -- the privacy boundary -----------------------------------------------------


def test_the_adr_carries_no_evaluative_finding_or_private_value() -> None:
    for token in EVALUATIVE_TOKENS:
        assert re.search(rf"\b{token}\b", ADR_TEXT) is None, token
    assert "nothing is taken from the private combined report" in ADR_FLAT
    assert IDENTIFIER_SHAPED.search(ADR_TEXT) is None
    assert TWELVE_DIGITS.search(ADR_TEXT) is None
    assert HEX_64.search(ADR_TEXT) is None
    assert ARN.search(ADR_TEXT) is None


# -- the status documents -----------------------------------------------------


@pytest.mark.parametrize("path", [README, CLAUDE])
def test_status_documents_record_the_adr_as_accepted_on_pr_92(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert (
        re.search(r"ADR-0035[^\n]{0,400}ACCEPTED / IN FORCE[^\n]{0,80}PR #92 merged", text)
        is not None
    )
    assert "dependent on ADR-0034" in text or "dependent on it" in text
