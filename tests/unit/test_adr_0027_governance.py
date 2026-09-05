"""ADR-0027 governance: a Cockpit that does not exist, and the guards that keep it honest.

The Cockpit is a specification. Nothing executes it, so nothing breaks when a clause loosens --
the same exposure ``test_adr_0026_governance`` was written for, one subsystem later and with a
larger surface: 36 product areas, a read-only boundary, a private-data boundary and a feedback
authority matrix.

The checks here are deliberately **structural** wherever a structure exists, because a
specification guarded only by substring matches is guarded by whoever last rewrapped a
paragraph:

* the 36 areas are **parsed and counted**, not spot-checked -- a missing area 19 fails, and so
  does a duplicated one;
* the traceability matrix is **parsed on both halves**, so an area specified but never traced
  is a failure rather than an omission nobody notices;
* the closed vocabularies are compared as **sets across documents**, so a value added in one
  place and forgotten in another fails;
* the endpoint catalog is **parsed for its HTTP verb**, so the first ``POST`` route fails the
  suite rather than the review;
* the maturity mapping is checked against the **real runtime enum** and the **real ADR-0026
  lifecycle vocabulary**, so a presentation stage cannot quietly invent a runtime environment;
* two claim scanners are **sentence-scoped and negation-aware**, and each carries a self-test
  proving it can still see a real violation -- a scanner that sees nothing passes every
  document vacuously.

Repository state is checked where the claim is about repository state: the Blueprint PDF
digests, the runtime dependency list, the absence of application scaffolding, and the two
runtime constants the specification says it did not touch.

The document-consistency side is checked by ``scripts/phase3_docs_audit.py`` section 23.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Final

import pytest

from kalpamani.common.environment import Environment
from kalpamani.common.settings import LIVE_TRADING_HARD_DISABLED

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
ARCHITECTURE: Final = PROJECT_ROOT / "docs" / "architecture"
COCKPIT: Final = PROJECT_ROOT / "docs" / "cockpit"

ADR: Final = DECISIONS / "ADR-0027-cockpit-and-feedback-architecture-and-governance.md"
ADR_0026: Final = DECISIONS / "ADR-0026-strategy-brain-architecture-and-governance.md"
EXTENSION: Final = ARCHITECTURE / "COCKPIT_FEEDBACK_EXTENSION.md"
SPEC: Final = COCKPIT / "cockpit-v1-specification.md"
CONTRACTS: Final = COCKPIT / "read-model-contracts.md"
FEEDBACK: Final = COCKPIT / "feedback-self-maturation-specification.md"
UIUX: Final = COCKPIT / "ui-ux-specification.md"
MATRIX: Final = COCKPIT / "traceability-matrix.md"
BRAIN_SPEC: Final = PROJECT_ROOT / "docs" / "phase4" / "strategy-brain-specification.md"
README: Final = PROJECT_ROOT / "README.md"
CLAUDE: Final = PROJECT_ROOT / "CLAUDE.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _flat(text: str) -> str:
    """One document as a single line, read the way a reader reads it.

    Emphasis markers and the leading ``>`` of a block quote are dropped before the lines are
    joined: both are layout, and a clause wrapped across two lines would otherwise be
    invisible to an exact-substring check.
    """
    lines = [line.lstrip().removeprefix("> ").removeprefix(">") for line in text.splitlines()]
    return " ".join(" ".join(lines).replace("**", "").split())


ADR_TEXT: Final = _read(ADR)
EXTENSION_TEXT: Final = _read(EXTENSION)
SPEC_TEXT: Final = _read(SPEC)
CONTRACTS_TEXT: Final = _read(CONTRACTS)
FEEDBACK_TEXT: Final = _read(FEEDBACK)
UIUX_TEXT: Final = _read(UIUX)
MATRIX_TEXT: Final = _read(MATRIX)

ADR_FLAT: Final = _flat(ADR_TEXT)
EXTENSION_FLAT: Final = _flat(EXTENSION_TEXT)
SPEC_FLAT: Final = _flat(SPEC_TEXT)
CONTRACTS_FLAT: Final = _flat(CONTRACTS_TEXT)
FEEDBACK_FLAT: Final = _flat(FEEDBACK_TEXT)
UIUX_FLAT: Final = _flat(UIUX_TEXT)
MATRIX_FLAT: Final = _flat(MATRIX_TEXT)

#: The six specification documents this decision introduces, plus the decision itself.
PACKAGE: Final[dict[str, Path]] = {
    "adr": ADR,
    "extension": EXTENSION,
    "specification": SPEC,
    "contracts": CONTRACTS,
    "feedback": FEEDBACK,
    "ui-ux": UIUX,
    "matrix": MATRIX,
}

PACKAGE_TEXT: Final[dict[str, str]] = {name: _read(path) for name, path in PACKAGE.items()}


def _section(document: Path, heading: str) -> str:
    """One ``###`` section of a status document, up to the next ``###`` heading.

    Scoped on purpose: a status line found somewhere else in a four-thousand-line document
    does not establish that this section carries it.
    """
    text = _read(document)
    start = text.find(heading)
    if start == -1:
        return ""
    end = text.find("\n### ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


README_SECTION: Final = _section(README, "### The Cockpit and Feedback specification, and ADR-0027")
CLAUDE_SECTION: Final = _section(CLAUDE, "### The Cockpit and Feedback specification — ACCEPTED")

STATUS_SECTIONS: Final[dict[str, str]] = {
    "readme-section": README_SECTION,
    "claude-section": CLAUDE_SECTION,
}


# -- the documents exist, and the decision claims no authority it has not been given -----


@pytest.mark.parametrize("name", sorted(PACKAGE))
def test_every_package_document_exists_at_its_exact_path(name: str) -> None:
    assert PACKAGE[name].is_file(), name


def test_the_adr_declares_itself_proposed_and_not_in_force() -> None:
    """A decision that does not say it is proposed will be read as accepted."""
    assert "Status: PROPOSED — NOT IN FORCE" in ADR_TEXT


def test_the_adr_does_not_report_itself_as_in_force() -> None:
    assert "ADR-0027 is ACCEPTED / IN FORCE" not in ADR_FLAT
    assert "ADR-0027: ACCEPTED" not in ADR_FLAT


def test_the_adr_records_that_its_own_days_are_not_rewritten_later() -> None:
    assert "not to be rewritten as though this decision had authority" in ADR_FLAT


def test_the_adr_authorizes_no_implementation_and_no_execution() -> None:
    assert "Acceptance authorizes no implementation and no execution" in ADR_FLAT


def test_the_adr_supersedes_and_amends_nothing() -> None:
    assert "**Supersedes:** nothing" in ADR_TEXT
    assert "No ADR is amended or superseded" in ADR_TEXT


def test_adr_0026_is_consumed_unchanged_and_keeps_its_own_text() -> None:
    """The accepted decision this one builds on keeps its own text and its own status."""
    text = _read(ADR_0026)
    assert "Status: PROPOSED — NOT IN FORCE" in text
    assert "ADR-0027" not in text
    assert "ADR-0027" not in _read(BRAIN_SPEC)


def test_the_merge_acceptance_event_is_stated_without_predicting_a_merge() -> None:
    assert "The acceptance event is exact" in ADR_FLAT
    assert "No merge SHA and no merge timestamp is predicted here" in ADR_FLAT


@pytest.mark.parametrize("name", sorted(PACKAGE))
def test_no_document_still_carries_the_authoring_placeholder(name: str) -> None:
    """``PR #NNN`` is the authoring placeholder; a merged tree must carry the real number."""
    assert "PR #NNN" not in PACKAGE_TEXT[name], name


@pytest.mark.parametrize("name", sorted(PACKAGE))
def test_every_package_document_names_its_merge_acceptance_pull_request(name: str) -> None:
    assert re.search(r"MERGE OF PR #\d+", PACKAGE_TEXT[name].upper()), name


@pytest.mark.parametrize("name", sorted(STATUS_SECTIONS))
def test_both_status_documents_carry_the_cockpit_section(name: str) -> None:
    assert STATUS_SECTIONS[name]


@pytest.mark.parametrize("name", sorted(STATUS_SECTIONS))
def test_each_status_section_reports_the_decision_as_proposed(name: str) -> None:
    """The acceptance must be merge-conditional, so the status is true on both sides."""
    section = STATUS_SECTIONS[name]
    assert "PROPOSED" in section
    assert "carries no authority" in " ".join(section.split())
    assert re.search(r"MERGE OF PR #\d+", section.upper()), name


# -- all 36 areas, parsed rather than spot-checked ---------------------------------------


AREA_HEADING: Final = re.compile(r"^## Area (\d+) — ", re.MULTILINE)
#: A traceability row opens with the area number in its first cell.
MATRIX_ROW: Final = re.compile(r"^\| (\d+) \| ", re.MULTILINE)

EXPECTED_AREAS: Final[frozenset[int]] = frozenset(range(1, 37))


def _specified_areas() -> list[int]:
    return [int(match) for match in AREA_HEADING.findall(SPEC_TEXT)]


def _matrix_half(marker: str, end_marker: str) -> str:
    start = MATRIX_TEXT.find(marker)
    end = MATRIX_TEXT.find(end_marker, start + len(marker)) if start != -1 else -1
    if start == -1:
        return ""
    return MATRIX_TEXT[start:] if end == -1 else MATRIX_TEXT[start:end]


MATRIX_A: Final = _matrix_half("## 1. Matrix A", "## 2. Matrix B")
MATRIX_B: Final = _matrix_half("## 2. Matrix B", "## 3. Delivery sequencing")


def test_the_specification_defines_exactly_thirty_six_areas() -> None:
    areas = _specified_areas()
    assert len(areas) == 36
    assert sorted(areas) == sorted(EXPECTED_AREAS)


def test_no_area_number_is_specified_twice() -> None:
    areas = _specified_areas()
    assert len(set(areas)) == len(areas)


def test_the_areas_are_specified_in_order() -> None:
    """Out-of-order headings are how an area gets duplicated under two numbers."""
    assert _specified_areas() == list(range(1, 37))


@pytest.mark.parametrize("half", ["A", "B"])
def test_the_traceability_matrix_traces_every_area(half: str) -> None:
    text = MATRIX_A if half == "A" else MATRIX_B
    assert text, half
    traced = {int(match) for match in MATRIX_ROW.findall(text)}
    assert traced == EXPECTED_AREAS, sorted(EXPECTED_AREAS - traced)


def test_matrix_and_specification_agree_on_the_area_set() -> None:
    assert {int(m) for m in MATRIX_ROW.findall(MATRIX_A)} == set(_specified_areas())


def test_the_area_parser_would_notice_a_missing_area() -> None:
    """A parser that matched nothing would pass every document vacuously."""
    sample = "## Area 1 — First\n\n## Area 3 — Third\n"
    assert [int(m) for m in AREA_HEADING.findall(sample)] == [1, 3]


def test_trade_history_and_trade_detail_are_area_thirty_six() -> None:
    assert "## Area 36 — Trade History and Trade Detail" in SPEC_TEXT


def test_area_thirty_six_keeps_four_concepts_apart() -> None:
    for concept in ("Trade History", "Trade Detail", "Execution History", "Audit Trail"):
        assert concept in SPEC_TEXT, concept
        assert concept in EXTENSION_TEXT, concept
    assert "They share identifiers and never share a screen" in SPEC_TEXT
    assert "They share identifiers and do not share screens" in EXTENSION_TEXT


def test_a_fill_is_never_counted_as_a_trade() -> None:
    assert "A fill is never counted as a separate trade" in SPEC_FLAT
    assert "partial exits | reduce a trade; they do not close it" in SPEC_FLAT


def test_manual_owner_activity_is_not_adopted_as_platform_evidence() -> None:
    assert "manual activity is not silently adopted as platform evidence" in SPEC_FLAT
    assert "real manual trades and holdings are never used as demonstration inputs" in SPEC_FLAT


# -- read-only authority, and the future control plane -----------------------------------


#: Every action Cockpit V1 may not take. Each is refused **by name** in the decision and in
#: the specification, because a boundary described in spirit is a boundary the next author
#: reasons their way past.
FORBIDDEN_ACTIONS: Final[tuple[str, ...]] = (
    "place or cancel an order",
    "change a stop",
    "change risk or capital",
    "activate or promote a strategy",
    "enable leverage",
    "change the provider",
    "execute Run B or an assessment",
    "publish CONTROL",
    "alter production strategy state",
    "approve or reject a governance release",
)


@pytest.mark.parametrize("action", FORBIDDEN_ACTIONS)
def test_each_forbidden_action_is_refused_by_name(action: str) -> None:
    assert action in ADR_FLAT, action
    assert action in SPEC_FLAT, action


def test_read_only_is_defined_by_absence_rather_than_discouragement() -> None:
    assert "READY-ONLY" not in ADR_TEXT
    assert "READ-ONLY is defined by what is absent" in ADR_FLAT
    assert "READ-ONLY is defined by what is absent" in SPEC_FLAT


def test_governance_screens_do_not_originate_approval_records() -> None:
    phrase = "do not originate authoritative approval records in V1"
    assert phrase in ADR_FLAT
    assert phrase in SPEC_FLAT
    assert phrase in EXTENSION_FLAT


def test_the_cockpit_inherits_no_authority_from_what_it_observes() -> None:
    assert "Do not grant the Cockpit safety-reduction authority" in ADR_FLAT
    assert "inherits no authority from what it observes" in EXTENSION_FLAT


#: The future control plane. Each control is specified so it can be designed deliberately,
#: and each is inert.
FUTURE_CONTROLS: Final[tuple[str, ...]] = (
    "global trading ON / OFF",
    "disable new entries",
    "long-only",
    "short-disable",
    "strategy disable",
    "risk reduction",
    "cancel unfilled orders",
    "emergency flatten",
    "independent kill switch",
)


@pytest.mark.parametrize("control", FUTURE_CONTROLS)
def test_each_future_control_is_specified_and_inert(control: str) -> None:
    assert control in SPEC_TEXT, control


def test_every_future_control_has_no_handler_and_no_route() -> None:
    phrase = "no executable handler and no control API route"
    assert phrase in ADR_FLAT
    assert phrase in SPEC_FLAT
    assert "a disabled button whose handler exists is not inert" in UIUX_FLAT.lower()


def test_a_cockpit_kill_switch_representation_is_not_a_kill_switch() -> None:
    assert "A Cockpit representation of a kill switch is not a kill switch" in SPEC_TEXT
    assert "kill switch remains independent of the AI" in SPEC_FLAT


# -- the endpoint catalog is read-only, parsed rather than asserted ----------------------


def _fenced_blocks(text: str) -> list[str]:
    return re.findall(r"```text\n(.*?)```", text, flags=re.DOTALL)


def _endpoint_lines(text: str) -> list[str]:
    lines: list[str] = []
    for block in _fenced_blocks(text):
        for raw in block.splitlines():
            line = raw.strip()
            if "/api/v" in line:
                lines.append(line)
    return lines


def _non_get_endpoints(text: str) -> list[str]:
    return [line for line in _endpoint_lines(text) if not line.startswith("GET ")]


def test_the_endpoint_catalog_exists_and_is_substantial() -> None:
    assert len(_endpoint_lines(CONTRACTS_TEXT)) >= 30


def test_every_catalogued_endpoint_is_a_read() -> None:
    """The first state-changing route fails the suite rather than the review."""
    assert _non_get_endpoints(CONTRACTS_TEXT) == []


def test_the_endpoint_scanner_would_notice_a_write_route() -> None:
    sample = "```text\nGET  /api/v1/thing\nPOST /api/v1/orders\n```"
    assert _non_get_endpoints(sample) == ["POST /api/v1/orders"]


def test_the_catalog_states_that_no_control_route_exists() -> None:
    assert "Every endpoint is read-only" in CONTRACTS_FLAT
    assert "no control route exists" in CONTRACTS_FLAT


# -- the read-model boundary -------------------------------------------------------------


def test_the_boundary_applies_to_the_backend_as_well_as_the_browser() -> None:
    phrase = "boundary applies to the backend as well as the browser"
    assert phrase in ADR_FLAT
    assert phrase in EXTENSION_FLAT
    assert phrase in SPEC_FLAT


def test_an_api_proxy_may_not_become_a_disguised_integration() -> None:
    phrase = "An API proxy must not become a disguised provider or broker integration"
    assert phrase in ADR_FLAT
    assert phrase in EXTENSION_FLAT
    assert phrase in CONTRACTS_FLAT


@pytest.mark.parametrize(
    "target",
    [
        "provider credentials or AWS secrets",
        "IBKR trading APIs or brokerage credentials",
        "mutable Brain internals",
        "private qualification artifacts",
    ],
)
def test_the_cockpit_has_no_direct_access_to(target: str) -> None:
    assert target in ADR_FLAT, target
    assert target in EXTENSION_FLAT, target


# -- the CandidateIntent boundary, preserved and not widened -----------------------------


#: Everything ``CandidateIntent`` may never carry, exactly as ADR-0026 fixes it. The Cockpit
#: consumes that contract; a screen that needed one of these would be a screen that widened it.
FORBIDDEN_INTENT_FIELDS: Final[tuple[str, ...]] = (
    "shares",
    "dollars",
    "position size",
    "broker order type",
    "route",
    "client order ID",
    "broker order ID",
)


@pytest.mark.parametrize("field_name", FORBIDDEN_INTENT_FIELDS)
def test_the_brain_never_chooses_each_forbidden_value(field_name: str) -> None:
    sentence = (
        "The Brain never chooses final shares, dollars, position size, broker order type, "
        "route, client order ID or broker order ID"
    )
    assert sentence in ADR_FLAT
    assert field_name in sentence, field_name


def test_no_sizing_or_execution_field_is_added_to_candidate_intent() -> None:
    phrase = "No sizing or execution field is added to `CandidateIntent` to simplify a screen"
    assert phrase in ADR_FLAT
    assert phrase in EXTENSION_FLAT.replace("a screen.", "a screen")
    assert "safe internal references" in SPEC_FLAT


def test_trade_detail_joins_by_reference_rather_than_widening_a_contract() -> None:
    assert "joins separately owned downstream facts" in SPEC_FLAT
    assert "Every `_ref` is a **safe internal reference**" in CONTRACTS_TEXT


#: A sentence claiming ``CandidateIntent`` carries an execution value is the drift this
#: guards. The disclaimers are the words that mark a sentence as a refusal rather than a claim.
INTENT_CLAIM_DISCLAIMERS: Final[tuple[str, ...]] = (
    "never",
    "no ",
    "not ",
    "may never",
    "forbidden",
    "refuse",
    "without",
    "structurally impossible",
)

INTENT_CLAIM_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    ("intent carries size", r"candidateintent (?:carries|includes|holds|has) [^.]*size"),
    ("intent carries shares", r"candidateintent (?:carries|includes|holds|has) [^.]*shares"),
    ("intent carries route", r"candidateintent (?:carries|includes|holds|has) [^.]*route"),
    ("intent carries order id", r"candidateintent (?:carries|includes|holds|has) [^.]*order id"),
)


def _asserted_intent_claims(text: str) -> list[str]:
    found: list[str] = []
    reading = " ".join(text.replace("**", "").replace("`", "").split())
    for sentence in re.split(r"(?<=[.;:])\s+|\s*\|\s*", reading):
        lowered = sentence.lower()
        if any(marker in lowered for marker in INTENT_CLAIM_DISCLAIMERS):
            continue
        found.extend(
            label for label, pattern in INTENT_CLAIM_PATTERNS if re.search(pattern, lowered)
        )
    return found


@pytest.mark.parametrize("name", sorted(PACKAGE))
def test_no_document_claims_candidate_intent_carries_an_execution_value(name: str) -> None:
    assert _asserted_intent_claims(PACKAGE_TEXT[name]) == [], name


def test_the_intent_claim_scanner_can_still_see_a_real_claim() -> None:
    assert _asserted_intent_claims("CandidateIntent carries the final position size.") == [
        "intent carries size"
    ]


def test_the_brain_status_vocabulary_is_not_extended_with_downstream_states() -> None:
    assert "The Brain status enum is not extended with downstream states" in ADR_FLAT
    assert "never be merged into it" in CONTRACTS_FLAT
    assert "not extended here" in SPEC_FLAT


# -- closed vocabularies, compared as sets across documents ------------------------------


AVAILABILITY_STATES: Final[frozenset[str]] = frozenset(
    {
        "AVAILABLE",
        "NOT_YET_AVAILABLE",
        "NOT_IMPLEMENTED",
        "NOT_AUTHORIZED",
        "UNEVALUATED",
        "STALE",
        "PARTIAL",
        "ERROR",
        "NOT_APPLICABLE",
        "EMPTY_VERIFIED",
        "INSUFFICIENT_OBSERVATIONS",
    }
)

#: ADR-0028 added ``REPOSITORY_TRACKED`` -- a real fact read from tracked repository
#: authority. It is here rather than in the ADR-0028 suite because this parametrization is
#: what proves a provenance value is defined in the extension *and* the contracts; a member
#: added to one document and forgotten in the other is the drift it exists to catch.
PROVENANCE_VALUES: Final[frozenset[str]] = frozenset(
    {
        "SYNTHETIC",
        "REPOSITORY_TRACKED",
        "SYSTEM_RECORDED",
        "BACKTEST_SIMULATED",
        "BROKER_REPORTED",
    }
)

CLASSIFICATIONS: Final[frozenset[str]] = frozenset(
    {"PUBLIC_SAFE", "PRIVATE_OPERATIONAL", "LICENSED_DERIVED", "UNCLASSIFIED", "CONTROL"}
)

MATURITY_STAGES: Final[tuple[str, ...]] = (
    "RESEARCH",
    "SHADOW",
    "AUTOMATED_PAPER",
    "MICRO_LIVE",
    "SCALED_LIVE",
)

#: ADR-0026 owns these. They are consumed, never extended.
BRAIN_DECISION_STATES: Final[frozenset[str]] = frozenset(
    {
        "READY_FOR_RISK_REVIEW",
        "WATCHLIST",
        "REJECTED",
        "BLOCKED_DATA",
        "BLOCKED_EVENT",
        "BLOCKED_AI",
        "BLOCKED_CONTRADICTION",
        "BLOCKED_BORROW",
    }
)

HEALTH_STATES: Final[frozenset[str]] = frozenset(
    {
        "HEALTHY",
        "WATCH",
        "DEGRADED",
        "NEW_ENTRIES_REDUCED",
        "NEW_ENTRIES_DISABLED",
        "SUSPENDED",
        "RETIRED",
    }
)

DOWNSTREAM_STAGES: Final[frozenset[str]] = frozenset(
    {
        "RISK_REVIEW_PENDING",
        "RISK_APPROVED",
        "RISK_REJECTED",
        "ORDER_SUBMITTED",
        "ORDER_ACKNOWLEDGED",
        "ORDER_PARTIALLY_FILLED",
        "ORDER_FILLED",
        "ORDER_CANCELLED",
        "ORDER_REJECTED",
    }
)

INFORMATION_PROFILES: Final[frozenset[str]] = frozenset(
    {"PUBLIC_PIT", "PROVIDER_REALISTIC_PIT", "FORWARD_SYSTEM"}
)


@pytest.mark.parametrize("state", sorted(AVAILABILITY_STATES))
def test_every_availability_state_is_defined_in_all_three_places(state: str) -> None:
    """A vocabulary defined in one document and used in another is two vocabularies."""
    assert state in EXTENSION_TEXT, state
    assert state in CONTRACTS_TEXT, state
    assert state in SPEC_TEXT, state


def test_the_availability_vocabulary_has_exactly_eleven_members() -> None:
    assert len(AVAILABILITY_STATES) == 11


@pytest.mark.parametrize("value", sorted(PROVENANCE_VALUES))
def test_every_provenance_value_is_defined_in_both_places(value: str) -> None:
    assert value in EXTENSION_TEXT, value
    assert value in CONTRACTS_TEXT, value


@pytest.mark.parametrize("value", sorted(CLASSIFICATIONS))
def test_every_classification_is_defined_in_all_three_places(value: str) -> None:
    assert value in EXTENSION_TEXT, value
    assert value in CONTRACTS_TEXT, value
    assert value in ADR_TEXT, value


@pytest.mark.parametrize("state", sorted(BRAIN_DECISION_STATES))
def test_the_brain_vocabulary_is_consumed_unchanged(state: str) -> None:
    assert state in CONTRACTS_TEXT, state
    assert state in _read(BRAIN_SPEC), state


@pytest.mark.parametrize("state", sorted(HEALTH_STATES))
def test_the_health_vocabulary_is_consumed_unchanged(state: str) -> None:
    assert state in SPEC_TEXT, state
    assert state in CONTRACTS_TEXT, state
    assert state in _read(BRAIN_SPEC), state


@pytest.mark.parametrize("stage", sorted(DOWNSTREAM_STAGES))
def test_every_downstream_stage_is_defined_in_the_contracts(stage: str) -> None:
    assert stage in CONTRACTS_TEXT, stage


def test_the_downstream_vocabulary_is_disjoint_from_the_brain_vocabulary() -> None:
    """One vocabulary spanning two authority domains is the defect this prevents."""
    assert DOWNSTREAM_STAGES.isdisjoint(BRAIN_DECISION_STATES)


@pytest.mark.parametrize("profile", sorted(INFORMATION_PROFILES))
def test_the_information_profiles_are_consumed_unchanged(profile: str) -> None:
    assert profile in SPEC_TEXT, profile
    assert profile in CONTRACTS_TEXT, profile


def test_no_default_information_profile_is_invented() -> None:
    assert "No default profile is invented" in SPEC_FLAT
    assert "No default profile is invented" in CONTRACTS_FLAT
    assert "never represented as `PUBLIC_PIT`" in SPEC_TEXT


# -- the maturity mapping, checked against the real runtime enum -------------------------


def _mapping_rows() -> list[tuple[str, str]]:
    """(stage, row) for every maturity-mapping row in the architecture extension."""
    rows: list[tuple[str, str]] = []
    for line in EXTENSION_TEXT.splitlines():
        stripped = line.strip()
        if not stripped.startswith("| `"):
            continue
        for stage in MATURITY_STAGES:
            if stripped.startswith(f"| `{stage}` |"):
                rows.append((stage, stripped))
    return rows


def test_the_mapping_table_covers_every_maturity_stage() -> None:
    assert [stage for stage, _ in _mapping_rows()] == list(MATURITY_STAGES)


@pytest.mark.parametrize("stage", MATURITY_STAGES)
def test_each_maturity_stage_maps_to_a_real_runtime_environment(stage: str) -> None:
    """A presentation stage must not be able to invent a runtime environment."""
    row = next(row for name, row in _mapping_rows() if name == stage)
    named = {member.name for member in Environment if f"`{member.name}`" in row}
    assert named, stage
    assert named <= {member.name for member in Environment}


def test_the_runtime_environment_enum_is_unchanged() -> None:
    assert {member.name for member in Environment} == {"RESEARCH", "PAPER", "LIVE"}
    assert "The runtime `Environment` enum is unchanged" in EXTENSION_TEXT
    assert "No runtime enum is changed, added to or renamed" in EXTENSION_FLAT


#: Every ADR-0026 lifecycle value the mapping presents. Each must exist in the Brain
#: specification, so a presentation stage cannot present a lifecycle that was never accepted.
MAPPED_LIFECYCLE_VALUES: Final[tuple[str, ...]] = (
    "IDEA",
    "REGISTERED_HYPOTHESIS",
    "TAXONOMY_OVERLAP_REVIEW",
    "DATA_FEASIBILITY",
    "BASELINE_RESEARCH",
    "LOCKED_OUT_OF_SAMPLE_VALIDATION",
    "SHADOW",
    "AUTOMATED_PAPER",
    "MICRO_LIVE_CANARY",
    "SCALED",
)


@pytest.mark.parametrize("value", MAPPED_LIFECYCLE_VALUES)
def test_every_mapped_lifecycle_value_exists_in_the_brain_specification(value: str) -> None:
    assert value in _read(BRAIN_SPEC), value
    assert value in EXTENSION_TEXT, value


def test_watch_suspended_and_retired_are_not_maturity_stages() -> None:
    assert "`WATCH`, `SUSPENDED` and `RETIRED` are not maturity stages" in EXTENSION_TEXT


def test_shadow_has_no_order_authority_and_paper_is_the_first_producing_stage() -> None:
    assert "Shadow produces no order" in EXTENSION_FLAT
    assert "`SHADOW` has no order authority" in ADR_FLAT
    assert "`AUTOMATED_PAPER` remains the first order-producing stage" in ADR_FLAT


def test_selecting_an_environment_advances_no_maturity() -> None:
    assert "Selecting a stage in the interface advances nothing" in EXTENSION_TEXT
    assert "No maturity advancement from selecting an environment" in SPEC_FLAT


def test_the_five_separated_concepts_are_named() -> None:
    for concept in (
        "deployment identity",
        "trading and runtime environment",
        "strategy maturity",
        "source provenance",
        "data availability",
    ):
        assert concept in EXTENSION_FLAT, concept


# -- synthetic, real and unavailable stay distinguishable --------------------------------


def test_synthetic_is_provenance_and_not_an_environment() -> None:
    assert "SYNTHETIC/DEMO is provenance, not a live trading environment" in SPEC_FLAT
    assert "SYNTHETIC/DEMO is provenance, not an environment" in EXTENSION_FLAT
    assert "does not imply synthetic data" in EXTENSION_FLAT


def test_a_missing_value_is_never_rendered_as_a_healthy_one() -> None:
    phrase = "never converted to zero, healthy, passed or no incidents"
    assert phrase in ADR_FLAT
    assert phrase in EXTENSION_FLAT
    assert "never rendered as zero, healthy, passed or no incidents" in SPEC_FLAT


def test_availability_is_typed_rather_than_an_overloaded_number() -> None:
    assert "a numeric null is never used to carry an availability meaning" in SPEC_FLAT.lower()
    assert "Availability is a typed field, never an overloaded number" in CONTRACTS_FLAT


def test_the_worked_unavailable_examples_are_present() -> None:
    for example in (
        "PEAD Short backtest",
        "P1–P9",  # noqa: RUF001 -- the documents use an en dash
        "Brain candidate stream",
        "Run B",
    ):
        assert example in SPEC_TEXT, example


def test_run_b_authorization_and_its_date_gate_stay_separate_facts() -> None:
    assert "passing the date does not change the authorization" in SPEC_FLAT.lower()
    assert "Passing the 2026-09-12 date gate is not execution authorization" in ADR_TEXT


def test_a_historical_success_carries_its_as_of_time() -> None:
    phrase = "past identity preflight is not proof of current authentication health"
    assert phrase in ADR_FLAT
    assert phrase in EXTENSION_FLAT


def test_synthetic_examples_are_deterministic_and_labelled() -> None:
    for requirement in (
        "deterministic",
        "reproducible",
        "internally consistent",
        "visibly labelled",
    ):
        assert requirement in SPEC_FLAT, requirement
    assert "A synthetic result is not evidence" in SPEC_TEXT


def test_no_threshold_is_adopted_from_a_synthetic_example() -> None:
    phrase = "becomes a production rule merely because it appears in a synthetic example"
    assert phrase in ADR_FLAT
    assert phrase in FEEDBACK_FLAT
    assert "No numerical value appearing in a synthetic example" in SPEC_FLAT


def test_no_silent_cross_environment_aggregation() -> None:
    assert "No silent cross-environment aggregation exists" in ADR_FLAT
    assert "presents no combined result" in UIUX_FLAT
    assert "never implies a meaningful combined profit and loss" in UIUX_FLAT


# -- the feedback authority matrix -------------------------------------------------------


FEEDBACK_STAGES: Final[tuple[str, ...]] = (
    "Journal",
    "Outcome and attribution",
    "Strategy health, drift and failure clusters",
    "Research queue",
    "Preregistered hypothesis",
    "Immutable challenger",
    "Authorized backtest, locked out-of-sample and stress",
    "Shadow",
    "Governance packet",
    "Human-authorized release",
)


@pytest.mark.parametrize("stage", FEEDBACK_STAGES)
def test_every_feedback_stage_has_a_contract(stage: str) -> None:
    assert f"### 2.{FEEDBACK_STAGES.index(stage) + 1} {stage}" in FEEDBACK_TEXT, stage


#: Everything only a human may do. Automation may prepare and recommend each; it may take none.
HUMAN_ONLY_ACTIONS: Final[tuple[str, ...]] = (
    "promotion into order-producing Paper",
    "Micro-Live",
    "production model or parameter replacement",
    "capital",
    "leverage",
    "short-exposure increase",
    "provider purchase",
    "resumption after a governed suspension",
    "kill-switch behaviour",
)


@pytest.mark.parametrize("action", HUMAN_ONLY_ACTIONS)
def test_each_human_only_action_is_named_in_the_decision(action: str) -> None:
    assert action in ADR_FLAT, action


def test_self_maturing_is_not_self_governing() -> None:
    assert "Self-maturing is not self-governing" in ADR_TEXT
    assert "Self-maturing is not self-governing" in FEEDBACK_TEXT
    assert "Self-maturing is not self-governing" in EXTENSION_TEXT


def test_preregistration_is_immutable_and_results_append() -> None:
    assert "Preregistration is immutable" in ADR_TEXT
    assert "Preregistration is immutable" in FEEDBACK_TEXT
    assert "linked amendment or a new registration" in FEEDBACK_FLAT
    assert "never edit the preregistration" in FEEDBACK_FLAT


def test_every_trial_counts_including_failed_and_abandoned_runs() -> None:
    assert "including failed and abandoned runs" in ADR_FLAT
    assert "All trials are tracked, including failed and abandoned runs" in FEEDBACK_TEXT


def test_a_failure_criterion_is_mandatory() -> None:
    assert "A failure criterion is mandatory" in FEEDBACK_TEXT
    assert "A hypothesis that cannot fail has not been stated" in FEEDBACK_TEXT


def test_no_automatic_production_parameter_mutation() -> None:
    assert "No automatic production parameter mutation exists" in ADR_FLAT
    assert "no automatic production parameter mutation" in FEEDBACK_FLAT.lower()
    assert "last-ten-trades threshold optimization in place" in ADR_FLAT
    assert "last-ten-trades threshold optimization in place" in FEEDBACK_FLAT


def test_the_champion_is_unchanged_until_an_authorized_promotion() -> None:
    assert "Champion is unchanged until an authorized promotion" in ADR_FLAT
    assert "the Champion is unchanged until an authorized promotion" in FEEDBACK_FLAT


def test_open_positions_stay_pinned_to_the_versions_that_opened_them() -> None:
    assert "open positions stay pinned to the versions that opened them" in ADR_FLAT.lower()
    for pinned in ("strategy", "factor-definition", "risk-policy", "entry-policy", "exit-policy"):
        assert pinned in FEEDBACK_FLAT, pinned


def test_leakage_and_out_of_sample_reuse_protections_are_specified() -> None:
    """ADR-0028 replaced the per-registration consumption rule, and this guard follows it.

    The clause this used to assert -- consumed once *per registration* -- was the defect:
    re-registration is free, so a new identity bought a fresh out-of-sample claim over
    exposed data. The invariant is protected here at its corrected and strictly stronger
    form: consumption is per *locked set*, a new identity does not clear it, and the
    unknown-history case fails closed instead of passing quietly.
    """
    assert "the locked set is locked" in FEEDBACK_FLAT
    assert "consumed **once per locked set**" in FEEDBACK_TEXT
    assert "not once per registration" in FEEDBACK_FLAT
    assert (
        "a new hypothesis, registration or Challenger identity does not make exposed data "
        "untouched again" in FEEDBACK_FLAT
    )
    assert "Unknown exposure history cannot support a fresh out-of-sample claim" in FEEDBACK_FLAT
    assert "purging and embargo" in FEEDBACK_FLAT
    assert "reproducibility evidence" in FEEDBACK_FLAT
    assert "without a network" in FEEDBACK_FLAT


def test_the_learning_engine_writes_and_the_cockpit_reads() -> None:
    assert "The Cockpit reads this loop; it does not drive it" in ADR_TEXT
    assert "Writes and reads are different systems" in FEEDBACK_TEXT
    assert "neither is implemented by this cycle" in FEEDBACK_FLAT.lower()


# -- the private-data, hosting and audit boundary ----------------------------------------


def test_read_model_does_not_mean_safe_to_publish() -> None:
    assert '"Read model" and "derived" do not mean "safe to publish"' in ADR_TEXT
    assert '"Read model" and "derived" do not mean safe to publish' in EXTENSION_TEXT


def test_unknown_classification_fails_closed() -> None:
    assert "it fails closed" in ADR_FLAT
    assert "it FAILS CLOSED" in CONTRACTS_TEXT


def test_control_publication_is_refused_and_deferred() -> None:
    assert "refused at admission" in ADR_FLAT
    assert "CONTROL publication remains **DEFERRED**" in ADR_TEXT
    assert "REFUSED AT ADMISSION" in CONTRACTS_TEXT


def test_external_hosting_admits_only_public_safe_synthetic_output() -> None:
    """ADR-0028 widened the admitted provenance by exactly one member, and no further.

    ``QualificationStatus`` is real, tracked and public-safe, so the old rule forced a
    choice between not displaying it and relabelling it ``SYNTHETIC`` -- which would be
    false. The replacement admits ``REPOSITORY_TRACKED`` beside ``SYNTHETIC`` and refuses
    the other three by name, so the protection is checked at its boundary rather than at
    one sentence, and the three that would leak a real operating figure are asserted
    individually.
    """
    assert "admits PUBLIC_SAFE payloads ONLY, and within that only" in CONTRACTS_TEXT
    assert "SYNTHETIC or REPOSITORY_TRACKED provenance" in CONTRACTS_FLAT
    refusal = CONTRACTS_FLAT[CONTRACTS_FLAT.index("admits exactly two provenances") :][:400]
    for refused in ("SYSTEM_RECORDED", "BACKTEST_SIMULATED", "BROKER_REPORTED"):
        assert refused in refusal, refused
    assert "never admitted to an externally hosted deployment" in refusal
    assert "must not silently receive a licensed payload" in ADR_FLAT
    assert "must not silently receive a licensed payload" in EXTENSION_FLAT


def test_a_render_proxy_cache_or_build_fetch_is_treated_as_a_copy() -> None:
    phrase = "an edge cache and a build-time fetch are each a copy"
    assert phrase in EXTENSION_FLAT
    assert phrase in CONTRACTS_FLAT


def test_licensed_content_never_enters_an_immutable_audit_payload() -> None:
    assert "never copied into a permanent immutable audit payload" in ADR_FLAT
    assert "never putting one inside the other" in EXTENSION_FLAT
    assert "never embedding one in the other" in CONTRACTS_FLAT
    assert "A reference is not a row" in EXTENSION_TEXT


def test_deletion_uses_tombstone_semantics_that_preserve_governance_evidence() -> None:
    assert "tombstone semantics" in ADR_FLAT
    assert "tombstone semantics" in EXTENSION_FLAT
    assert "The governance evidence is preserved; the vendor data is not retained" in CONTRACTS_TEXT


def test_a_projection_rebuild_never_mutates_a_source_event() -> None:
    assert "never mutates a source event" in CONTRACTS_FLAT
    assert "must never mutate a source event" in SPEC_FLAT


#: Values that must never reach a read model, a URL, a cache key, an export or a log line.
NEVER_RENDERED: Final[tuple[str, ...]] = (
    "brokerage account identifier",
    "broker-native order id",
    "AWS account id",
    "bucket name",
    "secret identifier",
    "execution identifier",
    "vendor row",
)


@pytest.mark.parametrize("value", NEVER_RENDERED)
def test_each_forbidden_identifier_is_refused_by_name(value: str) -> None:
    assert value.lower() in CONTRACTS_FLAT.lower(), value


# -- Ask KalpaMani -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "restriction",
    [
        "no arbitrary SQL or code execution",
        "no unrestricted data access",
        "no state mutation",
        "no broker action",
        "no external LLM transmission of licensed data",
    ],
)
def test_ask_kalpamani_carries_each_restriction(restriction: str) -> None:
    assert restriction in SPEC_FLAT, restriction


def test_ask_kalpamani_abstains_rather_than_inventing() -> None:
    assert "abstention over invention" in SPEC_FLAT
    assert "abstains when data is missing" in MATRIX_FLAT


def test_ask_kalpamani_inherits_the_licensed_data_boundary() -> None:
    assert "Ask KalpaMani inherits every rule in this section" in CONTRACTS_TEXT
    assert (
        "no read model derived from licensed rows may be transmitted to an external model"
        in CONTRACTS_FLAT
    )


def test_the_command_palette_has_no_execution_verb() -> None:
    assert "No execution commands, ever" in SPEC_TEXT
    assert "no state-changing verb exists" in MATRIX_FLAT
    assert "palette has no execution verb" in UIUX_FLAT


# -- continuing qualification state -------------------------------------------------------


@pytest.mark.parametrize("name", sorted(PACKAGE))
def test_every_document_reports_live_trading_hard_disabled(name: str) -> None:
    assert "HARD-DISABLED" in PACKAGE_TEXT[name], name


def test_the_runtime_kill_switch_is_still_set() -> None:
    """The claim is about a constant, so it is checked against the constant."""
    assert LIVE_TRADING_HARD_DISABLED is True
    assert "`LIVE_TRADING_HARD_DISABLED` | **True**" in ADR_TEXT


def test_the_adr_closes_no_gate() -> None:
    assert "G1 OPEN · G2 OPEN · G3 CLOSED · G4 OPEN · G5 OPEN · G6 OPEN · G7 OPEN" in ADR_TEXT


def test_each_gate_is_read_independently() -> None:
    assert "Each gate is read on its own" in ADR_TEXT
    assert "No blanket statement about all seven is correct" in ADR_TEXT


def test_p1_to_p9_stay_unevaluated() -> None:
    assert "P1–P9 UNEVALUATED" in ADR_FLAT  # noqa: RUF001 -- en dash, as the documents write it
    assert "P1–P9 are UNEVALUATED" in SPEC_FLAT  # noqa: RUF001


def test_run_b_and_the_combined_assessment_stay_unauthorized() -> None:
    assert "Run B NOT RUN / NOT AUTHORIZED" in ADR_FLAT
    assert "Run B has not run and is not authorized" in SPEC_FLAT
    assert "the combined assessment has not run and is not authorized" in SPEC_FLAT


def test_the_run_a_to_run_b_separation_is_at_least_eight_calendar_days() -> None:
    """Seven would be a quietly relaxed governance rule."""
    assert "at least eight calendar day Run A to Run B separation is unchanged" in ADR_FLAT
    assert "AT LEAST 8 CALENDAR DAYS" in MATRIX_TEXT
    for name, text in PACKAGE_TEXT.items():
        assert "seven calendar day" not in text.lower(), name


def test_no_provider_is_selected_and_phase_three_is_incomplete() -> None:
    assert "provider selected NONE" in ADR_FLAT
    assert "Phase 3 NOT COMPLETE" in ADR_FLAT
    assert "data correctness and quality are NOT ESTABLISHED" in SPEC_FLAT


def test_the_september_target_is_a_planning_target_and_not_a_readiness_claim() -> None:
    assert "It is a planning target and nothing more" in MATRIX_TEXT
    assert "not a claim of real-data readiness" in MATRIX_FLAT


# -- no alpha is claimed ------------------------------------------------------------------


CLAIM_DISCLAIMERS: Final[tuple[str, ...]] = (
    "does not claim",
    "do not claim",
    "no alpha is claimed",
    "must not claim",
    "claims no",
    "not claimed",
    "hypothesis",
    "hypotheses",
    "no result is asserted",
    "without evidence",
)

ALPHA_CLAIMS: Final[tuple[tuple[str, str], ...]] = (
    ("breakout works", r"breakout (?:strategy )?(?:is proven|works|outperforms)"),
    ("pullback works", r"pullback (?:strategy )?(?:is proven|works|outperforms)"),
    ("pead works", r"pead (?:strategy )?(?:is proven|works|outperforms)"),
    ("ai adds alpha", r"ai (?:adds|generates|produces) alpha"),
    ("residual momentum superior", r"residual momentum is (?:superior|better|proven)"),
    ("expected return established", r"expected returns? (?:are|is) established"),
    ("proven edge", r"proven (?:edge|alpha|profitability)"),
    ("will outperform", r"will outperform"),
)


def _asserted_alpha_claims(text: str) -> list[str]:
    found: list[str] = []
    reading = " ".join(text.replace("**", "").replace("`", "").split())
    for sentence in re.split(r"(?<=[.;:])\s+|\s*\|\s*", reading):
        lowered = sentence.lower()
        if any(marker in lowered for marker in CLAIM_DISCLAIMERS):
            continue
        found.extend(label for label, pattern in ALPHA_CLAIMS if re.search(pattern, lowered))
    return found


@pytest.mark.parametrize("name", sorted(PACKAGE))
def test_no_document_asserts_an_alpha_claim(name: str) -> None:
    assert _asserted_alpha_claims(PACKAGE_TEXT[name]) == [], name


@pytest.mark.parametrize("name", sorted(STATUS_SECTIONS))
def test_no_status_section_asserts_an_alpha_claim(name: str) -> None:
    assert _asserted_alpha_claims(STATUS_SECTIONS[name]) == [], name


def test_the_alpha_scanner_can_still_see_a_real_claim() -> None:
    assert _asserted_alpha_claims("Breakout works and residual momentum is superior.") == [
        "breakout works",
        "residual momentum superior",
    ]


def test_the_decision_states_that_no_alpha_is_claimed() -> None:
    assert "No alpha is claimed anywhere in this decision" in ADR_TEXT
    assert "No alpha is claimed anywhere in this document" in SPEC_TEXT
    assert "No alpha is claimed anywhere in this document" in FEEDBACK_TEXT


def test_no_third_party_stack_is_claimed() -> None:
    assert "claims no knowledge of the Atlas or SIRE internal technology stack" in ADR_FLAT
    assert "No claim is made about Atlas or SIRE's internal technology stack" in UIUX_TEXT
    assert "no retrieval was performed in this cycle" in UIUX_FLAT


# -- the repository state the decision says it left alone --------------------------------


def _tracked(prefix: str) -> list[str]:
    """Files git actually tracks under `prefix`.

    Tracked rather than on-disk: the claim is about what is committed, and a stray local
    file is neither evidence for nor against it.
    """
    result = subprocess.run(  # noqa: S603
        ["git", "ls-files", "--", prefix],  # noqa: S607
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


#: The Blueprint PDFs and the digests `BLUEPRINT_V3_ADOPTION.md` records for them. A
#: specification cycle that touched either would change a digest, and that is checkable
#: without opening the file.
BLUEPRINT_DIGESTS: Final[dict[str, str]] = {
    "KalpaMani_Blueprint_V2_1.pdf": (
        "3adaf59f01616c3b491ee988e2f60c43e863578edca74241c12b6b0b1c1495d2"
    ),
    "KalpaMani_Blueprint_V3_0.pdf": (
        "2726b96dd69c8982788b1c2bd646ce7a52879c649994a31858dc41666761996d"
    ),
}


@pytest.mark.parametrize("name", sorted(BLUEPRINT_DIGESTS))
def test_the_blueprint_pdf_is_byte_identical(name: str) -> None:
    path = ARCHITECTURE / name
    assert path.is_file(), name
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == BLUEPRINT_DIGESTS[name], name


def test_the_adoption_record_still_carries_both_recorded_digests() -> None:
    adoption = _read(ARCHITECTURE / "BLUEPRINT_V3_ADOPTION.md")
    for digest in BLUEPRINT_DIGESTS.values():
        assert digest in adoption


def test_the_extension_does_not_pretend_the_pdf_contains_the_cockpit() -> None:
    assert "The adopted Blueprint V3.0 PDF does not describe the Cockpit" in EXTENSION_TEXT
    assert "No claim is made anywhere that the adopted PDF already contains this material" in (
        EXTENSION_FLAT
    )
    assert "it is not edited" in EXTENSION_FLAT


def test_the_runtime_dependency_list_is_unchanged() -> None:
    """The stack is decided in prose. Nothing was installed, and nothing was declared."""
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        manifest = tomllib.load(handle)
    assert manifest["project"]["dependencies"] == ["boto3>=1.36.0,<2.0"]


#: Package names the technology decision NAMES and must not have DECLARED. The decision is a
#: reviewed choice for a later cycle; declaring one here would make it a dependency change.
UNDECLARED_STACK_PACKAGES: Final[tuple[str, ...]] = (
    "next",
    "react",
    "tailwindcss",
    "fastapi",
    "pydantic",
    "recharts",
    "echarts",
    "zod",
    "duckdb",
    "psycopg",
    "sqlalchemy",
)


@pytest.mark.parametrize("package", UNDECLARED_STACK_PACKAGES)
def test_no_stack_package_is_declared_anywhere_in_the_manifest(package: str) -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        manifest = tomllib.load(handle)
    declared = list(manifest["project"]["dependencies"])
    for extra in manifest["project"].get("optional-dependencies", {}).values():
        declared.extend(extra)
    assert not [spec for spec in declared if spec.lower().startswith(package)], package


def test_no_version_is_pinned_by_the_technology_decision() -> None:
    assert "No version is pinned here" in ADR_TEXT
    assert "installs no dependency" in ADR_FLAT


#: Application scaffolding. An empty project is an invitation for a later session to fill it
#: without an authorization, which is exactly what "specification only" must exclude.
SCAFFOLD_FILENAMES: Final[frozenset[str]] = frozenset(
    {
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "next.config.js",
        "next.config.mjs",
        "next.config.ts",
        "tsconfig.json",
        "tailwind.config.js",
        "tailwind.config.ts",
        "postcss.config.js",
        "components.json",
        "requirements.txt",
        "poetry.lock",
    }
)


def test_no_application_scaffolding_is_tracked_anywhere() -> None:
    tracked = {Path(path).name for path in _tracked(".")}
    assert not (tracked & SCAFFOLD_FILENAMES), sorted(tracked & SCAFFOLD_FILENAMES)


#: The packages a Cockpit backend would eventually live in. None may exist yet -- not even
#: as an ``__init__.py``.
ABSENT_PACKAGES: Final[tuple[str, ...]] = (
    "src/kalpamani/cockpit",
    "src/kalpamani/api",
    "src/kalpamani/readmodels",
    "src/kalpamani/projections",
    "src/kalpamani/feedback",
    "web",
    "app",
    "frontend",
)


@pytest.mark.parametrize("package", ABSENT_PACKAGES)
def test_the_specification_created_no_application_package(package: str) -> None:
    assert _tracked(package) == [], package


def test_no_cockpit_runtime_module_exists_under_src() -> None:
    """A specification read as a permission is the one failure this decision guards."""
    names = {"cockpit.py", "read_model.py", "read_models.py", "projection.py", "projections.py"}
    modules = [path for path in _tracked("src/kalpamani") if Path(path).name in names]
    assert modules == []


def test_the_decision_records_that_it_creates_no_source_module() -> None:
    assert "No source module is created by this decision" in ADR_FLAT
    assert "no placeholder application package is created" in ADR_FLAT


def test_specification_and_implementation_stay_separate_gates() -> None:
    for name, text in PACKAGE_TEXT.items():
        assert "five separate gates" in _flat(text), name


def test_the_decision_authorizes_no_operational_activity() -> None:
    for forbidden in (
        "Cockpit application implementation",
        "Brain runtime implementation",
        "Database, migration, scheduler and deployment",
        "Backtesting",
        "Run A retry",
        "Run B",
        "Combined assessment",
        "Provider selected",
        "Live trading",
    ):
        assert forbidden in ADR_TEXT, forbidden


def test_nothing_was_run_to_produce_the_decision() -> None:
    assert "Nothing was run to produce this decision" in ADR_TEXT
    assert "No Blueprint PDF was opened" in ADR_FLAT
    assert "no application was scaffolded" in ADR_FLAT
