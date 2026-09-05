"""ADR-0026 governance: a specification with nothing behind it, and the guards that keep it so.

Every earlier decision in this repository was checked against something that runs. This one
is not: ADR-0026 introduces a **specification**, and there is no Brain to execute it
against. That makes it the easiest document in the repository to weaken, because nothing
breaks when a clause loosens -- no test fails, no run refuses, nobody notices.

So the checks here are about text, deliberately, and about two things in particular.

**What the specification forbids must be forbidden by name.** A `CandidateIntent` that
"should not really carry a size" acquires one; a `CandidateIntent` whose forbidden fields
are enumerated does not. The same holds for the decision states that read as instructions,
for the short-side inversion, and for the AI rescue path.

**What the specification is must not drift into what it authorizes.** The failure mode is
not that someone writes a bad Brain; it is that a later session reads a specification as a
permission and starts building. The scaffolding checks below are the direct guard on that:
the five packages the Brain would eventually live in must still hold nothing but their
``__init__.py``.

The document-consistency side is checked by ``scripts/phase3_docs_audit.py`` section 22.
This module checks the decision itself, the claims it makes about its own authority, and
the repository state it says it left alone.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
ADR: Final = DECISIONS / "ADR-0026-strategy-brain-architecture-and-governance.md"
ADR_0006: Final = DECISIONS / "ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md"
SPEC: Final = PROJECT_ROOT / "docs" / "phase4" / "strategy-brain-specification.md"
README: Final = PROJECT_ROOT / "README.md"
CLAUDE: Final = PROJECT_ROOT / "CLAUDE.md"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8") if ADR.is_file() else ""
SPEC_TEXT: Final = SPEC.read_text(encoding="utf-8") if SPEC.is_file() else ""


def _flat(text: str) -> str:
    """One document as a single line, read the way a reader reads it.

    Emphasis markers and the leading ``>`` of a block quote are dropped before the
    lines are joined: both are layout, and a clause wrapped across two quoted lines
    would otherwise be invisible to an exact-substring check. That is a real defect,
    not a hypothetical -- the forbidden-activity list below is a wrapped block quote.
    """
    lines = [line.lstrip().removeprefix("> ").removeprefix(">") for line in text.splitlines()]
    return " ".join(" ".join(lines).replace("**", "").split())


#: Each document with its line wrapping and quote markers removed, so neither a rewrap
#: nor a block quote can hide a clause.
ADR_FLAT: Final = _flat(ADR_TEXT)
SPEC_FLAT: Final = _flat(SPEC_TEXT)


def _section(document: Path, heading: str) -> str:
    """One ``###`` section of a status document, up to the next ``###`` heading.

    Scoped on purpose: a status line found somewhere else in a four-thousand-line
    document does not establish that this section carries it.
    """
    text = document.read_text(encoding="utf-8")
    start = text.find(heading)
    if start == -1:
        return ""
    end = text.find("\n### ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


README_SECTION: Final = _section(README, "### The Strategy Brain specification, and ADR-0026")
CLAUDE_SECTION: Final = _section(CLAUDE, "### The Strategy Brain specification — PROPOSED")


#: Looked up by name rather than parametrized by value: a parametrized document body
#: becomes the test id, and a thousand-line id is unreadable in every report.
DOCUMENTS: Final[dict[str, str]] = {
    "specification": SPEC_TEXT,
    "adr": ADR_TEXT,
    "readme-section": README_SECTION,
    "claude-section": CLAUDE_SECTION,
}


# -- the decision exists, and claims no authority it has not been given ------------------


def test_the_adr_exists_at_its_exact_path() -> None:
    assert ADR.is_file()


def test_the_specification_exists_at_its_exact_path() -> None:
    assert SPEC.is_file()


def test_the_adr_declares_itself_proposed_and_not_in_force() -> None:
    """A decision that does not say it is proposed will be read as accepted."""
    assert "Status: PROPOSED — NOT IN FORCE" in ADR_TEXT


def test_the_adr_does_not_report_itself_as_in_force() -> None:
    assert "ADR-0026 is ACCEPTED / IN FORCE" not in ADR_FLAT
    assert "ADR-0026: ACCEPTED" not in ADR_FLAT


def test_the_adr_records_that_its_own_days_are_not_rewritten_later() -> None:
    """The repository's standing rule: a proposed period stays a proposed period."""
    assert "not to be rewritten as though this decision had authority" in ADR_FLAT


def test_the_adr_authorizes_no_implementation_and_no_execution() -> None:
    assert "authorizes no implementation and no execution" in ADR_FLAT


def test_both_status_documents_carry_a_brain_section() -> None:
    assert README_SECTION
    assert CLAUDE_SECTION


@pytest.mark.parametrize("name", ["readme-section", "claude-section"])
def test_each_status_section_reports_the_decision_as_proposed(name: str) -> None:
    section = DOCUMENTS[name]
    flat = " ".join(section.split())
    assert "PROPOSED" in section
    assert "carries no authority" in flat


# -- the CandidateIntent boundary --------------------------------------------------------


#: Everything ``CandidateIntent`` may never carry. ADR-0006 §E named the first six; the
#: specification adds the four that would otherwise arrive through a "for reference only"
#: field. A suggested size is a size, and something eventually treats it as one.
FORBIDDEN_INTENT_FIELDS: Final[tuple[str, ...]] = (
    "shares",
    "dollar amount",
    "final position size",
    "final broker order type",
    "broker route",
    "client order ID",
    "broker order ID",
    "credential",
    "account number",
    "arbitrary free-form execution instruction",
)


@pytest.mark.parametrize("field_name", FORBIDDEN_INTENT_FIELDS)
def test_the_specification_refuses_each_forbidden_intent_field_by_name(field_name: str) -> None:
    """A field refused only in spirit is a field the next author adds."""
    assert field_name.lower() in SPEC_FLAT.lower()


def test_brain_output_is_not_an_order() -> None:
    assert "produces no broker order and no position size" in SPEC_FLAT
    assert "produces no broker order and no position size" in ADR_FLAT


def test_the_intent_exclusion_is_required_to_be_structural() -> None:
    """A convention can be relaxed by the next author; a type cannot."""
    assert "structurally impossible for Brain output to be treated as a broker ticket" in SPEC_FLAT
    assert "structural, not conventional" in ADR_FLAT


def test_the_technical_stop_is_a_reference_and_not_an_order() -> None:
    assert "technical stop is a reference, not an order" in SPEC_FLAT
    assert "reference to an invalidation level, not an order" in ADR_FLAT


def test_the_compiler_emits_a_status_and_nothing_else() -> None:
    assert "output is a `CandidateIntent` status, and nothing else" in SPEC_TEXT
    for forbidden in ("share count", "broker route", "client order ID", "take-profit order"):
        assert forbidden in SPEC_TEXT


# -- the closed decision vocabulary ------------------------------------------------------


DECISION_STATES: Final[tuple[str, ...]] = (
    "READY_FOR_RISK_REVIEW",
    "WATCHLIST",
    "REJECTED",
    "BLOCKED_DATA",
    "BLOCKED_EVENT",
    "BLOCKED_AI",
    "BLOCKED_CONTRADICTION",
    "BLOCKED_BORROW",
)

#: States that read as instructions. Each is refused **by name**, because a vocabulary
#: that merely omits ``EXECUTE`` invites the next author to add it.
FORBIDDEN_STATES: Final[tuple[str, ...]] = ("MAYBE", "BUY", "SELL", "EXECUTE", "APPROVED_ORDER")


@pytest.mark.parametrize("state", DECISION_STATES)
def test_the_closed_decision_vocabulary_is_recorded(state: str) -> None:
    assert state in SPEC_TEXT
    assert state in ADR_TEXT


@pytest.mark.parametrize("state", FORBIDDEN_STATES)
def test_each_instruction_shaped_state_is_refused_by_name(state: str) -> None:
    assert state in SPEC_TEXT
    assert state in ADR_TEXT


def test_ready_for_risk_review_is_not_an_approval_to_trade() -> None:
    """The risk engine decides independently, and must be able to refuse."""
    assert "`READY_FOR_RISK_REVIEW` is not an approval to trade" in SPEC_TEXT
    assert "`READY_FOR_RISK_REVIEW` is not an approval to trade" in ADR_TEXT


# -- the AI boundary ---------------------------------------------------------------------


def test_a_deterministic_failure_cannot_be_rescued_by_ai() -> None:
    assert "deterministic failure cannot be rescued by AI" in SPEC_FLAT
    assert "deterministic failure cannot be rescued by AI" in ADR_FLAT


def test_ai_may_remove_a_candidate_and_never_restore_one() -> None:
    """The asymmetry is the whole of the AI boundary."""
    assert "may remove a candidate; it may never restore one" in SPEC_FLAT


def test_the_research_agent_cannot_choose_what_to_look_at() -> None:
    """An AI that selects securities is a scanner, and the scanner is deterministic."""
    assert "only already shortlisted" in SPEC_FLAT
    assert "full-universe scanning" in SPEC_FLAT


def test_neither_ai_role_may_size_or_send_an_order() -> None:
    assert "choosing dollar size" in SPEC_FLAT
    assert "sending orders" in SPEC_FLAT
    assert "sending an order" in SPEC_FLAT
    assert "selecting a broker action" in SPEC_FLAT


def test_ai_dependent_new_entries_fail_closed_on_an_outage() -> None:
    assert "AI-dependent new entries | fail closed" in SPEC_FLAT


def test_every_ai_output_must_carry_provenance_and_versions() -> None:
    for required in ("source provenance", "source publish time", "model version", "prompt version"):
        assert required in SPEC_FLAT


# -- lifecycle, promotion authority and versioning ---------------------------------------


LIFECYCLE_STAGES: Final[tuple[str, ...]] = (
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
    "RETIRED",
)


@pytest.mark.parametrize("stage", LIFECYCLE_STAGES)
def test_the_lifecycle_stage_is_specified(stage: str) -> None:
    assert stage in SPEC_TEXT


def test_no_stage_is_advanced_by_code_a_backtest_or_an_ai_recommendation() -> None:
    for phrase in (
        "a code module | existing is not evidence",
        "a result is not a promotion",
        "input to a human decision, never the decision",
    ):
        assert phrase in SPEC_FLAT


def test_promotion_to_order_producing_paper_requires_a_human() -> None:
    assert "AUTOMATED_PAPER` is the first order-producing stage" in SPEC_TEXT
    assert "strategy promotion to order-producing Paper" in SPEC_TEXT
    assert "Human approval required" in SPEC_TEXT


def test_promotion_to_micro_live_and_scaled_live_requires_a_human() -> None:
    assert "Paper to micro-live" in SPEC_FLAT
    assert "micro-live to scaled live" in SPEC_FLAT


def test_self_maturing_is_not_self_governing() -> None:
    assert "Self-maturing is not self-governing" in SPEC_TEXT
    assert "Self-maturing, not self-governing" in ADR_TEXT
    assert "may prepare, evidence and recommend every item" in SPEC_FLAT


def test_a_challenger_may_not_silently_replace_a_champion() -> None:
    assert "silently replace the Champion" in SPEC_FLAT
    assert "Promotion requires a governance packet" in SPEC_TEXT


def test_production_strategy_versions_are_immutable() -> None:
    assert "production strategy versions are IMMUTABLE" in SPEC_TEXT
    assert "a modification creates a NEW CHALLENGER VERSION" in SPEC_TEXT


def test_open_positions_stay_pinned_to_the_versions_that_opened_them() -> None:
    assert "stays governed by the exact versions that opened it" in SPEC_FLAT
    for pinned in (
        "strategy version",
        "factor-definition version",
        "risk-policy version",
        "entry-policy version",
        "exit-policy version",
    ):
        assert pinned in SPEC_FLAT


def test_no_implicit_fallback_to_a_latest_strategy_model_or_prompt() -> None:
    assert "No implicit fallback to a latest strategy, model or prompt exists" in SPEC_FLAT


def test_health_degradation_does_not_automatically_mutate_parameters() -> None:
    assert "It does not automatically mutate strategy parameters" in SPEC_FLAT
    assert "Recovery toward `HEALTHY` is never automatic past a governed suspension" in SPEC_FLAT


# -- taxonomy and the short-side asymmetry -----------------------------------------------


def test_breakout_and_pullback_share_family_exposure_and_keep_attribution() -> None:
    assert "share a family exposure cap" in SPEC_FLAT
    assert "separate module attribution" in SPEC_FLAT
    assert "Different labels do not constitute diversification" in SPEC_TEXT


def test_whether_breakout_and_pullback_are_distinct_stays_gate_g7() -> None:
    """The specification records the question as open rather than answering it."""
    assert "open gate" in SPEC_FLAT
    assert "G7" in SPEC_TEXT
    assert "this document does not decide it" in SPEC_FLAT


def test_deterioration_short_is_not_an_inverted_breakout() -> None:
    assert 'No generic "Breakdown Short" is authorized' in SPEC_TEXT
    assert 'No generic "Breakdown Short" is authorized' in ADR_TEXT
    assert "may not be produced by inverting a long breakout" in SPEC_FLAT
    assert "Bottom-decile momentum alone is not short authorization" in SPEC_TEXT


def test_short_alpha_is_recorded_as_asymmetric() -> None:
    assert "Short alpha is asymmetric" in SPEC_TEXT
    assert "have no long-side mirror" in SPEC_FLAT


def test_short_borrow_context_is_mandatory_and_never_inferred() -> None:
    assert "BLOCKED_BORROW" in SPEC_TEXT
    assert "may not infer borrow from price behaviour" in SPEC_FLAT
    for required in (
        "borrow availability state",
        "borrow fee state",
        "squeeze and crowding state",
        "SSR state",
        "recall and buy-in state",
    ):
        assert required in SPEC_FLAT


def test_the_live_pre_submit_borrow_recheck_is_not_the_brains() -> None:
    assert "belongs to execution and risk, not to the Brain" in SPEC_FLAT


def test_consolidation_preserves_attribution_and_is_not_sizing() -> None:
    assert "Module attribution survives consolidation" in SPEC_TEXT
    assert "Consolidation is not netting and not sizing" in SPEC_TEXT


def test_the_point_in_time_gate_blocks_rather_than_defaulting() -> None:
    for phrase in ("no default information profile", "no default as-of", 'no "latest"'):
        assert phrase in SPEC_FLAT
    assert "BLOCK / REFUSE" in SPEC_TEXT


def test_no_single_module_answers_all_three_handoff_question_classes() -> None:
    assert "No single module may answer all three classes of question" in SPEC_TEXT


# -- no alpha is claimed -----------------------------------------------------------------


#: Wording that marks a sentence as a disclaimer rather than a claim. Both documents are
#: largely *about* not making these claims, so the same words appear on both sides of the
#: negation, and only the sentence they sit in separates them.
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
    """Every alpha claim a document asserts rather than disclaims, sentence-scoped."""
    found: list[str] = []
    reading = " ".join(text.replace("**", "").replace("`", "").split())
    for sentence in re.split(r"(?<=[.;:])\s+|\s*\|\s*", reading):
        lowered = sentence.lower()
        if any(marker in lowered for marker in CLAIM_DISCLAIMERS):
            continue
        found.extend(label for label, pattern in ALPHA_CLAIMS if re.search(pattern, lowered))
    return found


@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_no_document_asserts_an_alpha_claim(name: str) -> None:
    assert _asserted_alpha_claims(DOCUMENTS[name]) == [], name


def test_the_disclaimer_scan_can_still_see_a_real_claim() -> None:
    """A negation-aware scanner that saw nothing would pass every document vacuously."""
    assert _asserted_alpha_claims("Breakout works and residual momentum is superior.") == [
        "breakout works",
        "residual momentum superior",
    ]


def test_the_specification_states_that_no_alpha_is_claimed() -> None:
    assert "No alpha is claimed anywhere in this document" in SPEC_TEXT
    assert "No alpha is claimed" in ADR_TEXT


def test_the_experiment_matrix_asserts_no_result() -> None:
    assert "No result is asserted by this document, and none exists" in SPEC_TEXT


def test_no_backtest_is_claimed_to_have_been_run_or_passed() -> None:
    assert "No strategy currently passes any of these tests, because none has been run" in SPEC_TEXT
    assert "Backtesting | **NOT STARTED**" in SPEC_TEXT


# -- the qualification gates are reported as still open ----------------------------------


def test_the_specification_records_that_p1_to_p9_are_unevaluated() -> None:
    # The documents write P1-P9 with an en dash, and the assertion must match what they
    # actually contain rather than a hyphenated paraphrase of it.
    assert "P1–P9 are UNEVALUATED" in SPEC_FLAT  # noqa: RUF001
    assert "P1–P9 UNEVALUATED" in ADR_FLAT  # noqa: RUF001


def test_no_provider_is_selected() -> None:
    assert "no provider is selected" in SPEC_FLAT
    assert "no provider selected" in ADR_FLAT


def test_run_b_and_the_combined_assessment_stay_unauthorized() -> None:
    assert "Run B has not run and is not authorized" in SPEC_FLAT
    assert "the combined assessment has not run and is not authorized" in SPEC_FLAT
    assert "Run B NOT RUN / NOT AUTHORIZED" in ADR_FLAT


def test_data_correctness_and_quality_stay_unestablished() -> None:
    assert "data correctness and quality are NOT ESTABLISHED" in SPEC_FLAT


def test_the_adr_closes_no_gate() -> None:
    assert "G1 OPEN · G2 OPEN · G3 CLOSED · G4 OPEN · G5 OPEN · G6 OPEN · G7 OPEN" in ADR_TEXT


def test_live_trading_stays_hard_disabled_in_both_documents() -> None:
    assert "HARD-DISABLED" in SPEC_TEXT
    assert "LIVE_TRADING_HARD_DISABLED` | **True**" in ADR_TEXT


# -- the decision changed nothing it says it changed nothing about -----------------------


def test_the_adr_supersedes_and_amends_nothing() -> None:
    assert "**Supersedes:** nothing" in ADR_TEXT
    assert "No ADR is amended or superseded" in ADR_TEXT


def test_adr_0006_is_refined_rather_than_altered() -> None:
    assert "refines ADR-0006 §D and §E into checkable contracts" in SPEC_FLAT
    assert "refined into checkable contracts, not altered" in ADR_FLAT


def test_adr_0006_itself_is_unchanged_by_this_decision() -> None:
    """The accepted decision this one builds on keeps its own text and its own status."""
    text = ADR_0006.read_text(encoding="utf-8")
    assert "**Status:** **Accepted**" in text
    assert "ADR-0026" not in text


def test_adr_0005_is_still_reported_as_proposed() -> None:
    assert "still PROPOSED" in SPEC_TEXT
    assert "ADR-0005 **PROPOSED**" in ADR_TEXT


# -- nothing was implemented, and the guard is repository state --------------------------


#: The packages a Brain would eventually live in. Each must still hold exactly its
#: ``__init__.py``: scaffolding is not progress, and an empty package is an invitation for
#: a later session to fill it without an authorization.
EMPTY_PACKAGES: Final[tuple[str, ...]] = (
    "src/kalpamani/strategies",
    "src/kalpamani/research",
    "src/kalpamani/portfolio",
    "src/kalpamani/risk",
    "src/kalpamani/monitoring",
)


def _tracked(prefix: str) -> list[str]:
    """Files git actually tracks under `prefix`.

    Tracked rather than on-disk: the claim being made is about what is committed, and a
    stray local file is neither evidence for nor against it.
    """
    result = subprocess.run(  # noqa: S603
        ["git", "ls-files", "--", prefix],  # noqa: S607
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


@pytest.mark.parametrize("package", EMPTY_PACKAGES)
def test_the_specification_left_its_future_package_empty(package: str) -> None:
    modules = [path for path in _tracked(package) if not path.endswith("__init__.py")]
    assert modules == [], package


def test_no_brain_runtime_module_exists_under_src() -> None:
    """A specification read as a permission is the one failure this decision guards."""
    brain_modules = [
        path
        for path in _tracked("src/kalpamani")
        if Path(path).name in {"brain.py", "candidate_intent.py", "strategy_spec.py"}
    ]
    assert brain_modules == []


def test_the_adr_records_that_it_creates_no_source_module() -> None:
    assert "No source module is created by this decision" in ADR_TEXT
    assert "no placeholder strategy package is created" in ADR_FLAT


def test_specification_and_implementation_stay_separate_gates() -> None:
    assert "five separate gates" in ADR_FLAT
    assert "five separate gates" in SPEC_FLAT


def test_the_adr_authorizes_no_operational_activity() -> None:
    for forbidden in (
        "Brain runtime implementation",
        "backtesting of any kind",
        "provider data usage",
        "a Terraform command",
        "private-artifact access",
        "a Run A retry",
        "Run B",
        "the combined assessment",
        "live trading",
    ):
        assert forbidden in ADR_FLAT


def test_the_adr_records_that_nothing_was_run_to_produce_it() -> None:
    assert "Nothing was run to produce this decision" in ADR_TEXT
    assert "No Blueprint PDF was opened" in ADR_FLAT


# -- the new documents carry no identifier -----------------------------------------------


#: A twelve-digit run is an AWS account id and an ``AKIA``/``ASIA`` prefix an access-key
#: id. Neither belongs in a document that says it carries none, and a placeholder in angle
#: brackets matches neither.
ACCOUNT_ID: Final = re.compile(r"(?<!\d)\d{12}(?!\d)")
ACCESS_KEY_ID: Final = re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA)[A-Z0-9]{12,}\b")
CONCRETE_ARN: Final = re.compile(r"arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:\d{12}:")
SSO_START_URL: Final = re.compile(r"https://[A-Za-z0-9-]+\.awsapps\.com/start")


IDENTIFIER_SHAPES: Final[dict[str, re.Pattern[str]]] = {
    "account-id": ACCOUNT_ID,
    "access-key-id": ACCESS_KEY_ID,
    "concrete-arn": CONCRETE_ARN,
    "sso-start-url": SSO_START_URL,
}


@pytest.mark.parametrize("name", ["specification", "adr"])
@pytest.mark.parametrize("label", sorted(IDENTIFIER_SHAPES))
def test_the_new_documents_carry_no_identifier(name: str, label: str) -> None:
    assert IDENTIFIER_SHAPES[label].search(DOCUMENTS[name]) is None, f"{name}: {label}"


#: A private artifact path, as opposed to a mention of the directory it lives in. Both
#: documents legitimately state that no ``.runtime/`` inspection occurred; what neither
#: may carry is a path *into* one, which is where an owner-side filename would appear.
PRIVATE_PATH: Final = re.compile(r"\.runtime/[A-Za-z0-9_.\-]|terraform\.tfvars[/\\]")


@pytest.mark.parametrize("name", ["specification", "adr"])
def test_the_new_documents_name_no_private_path_or_secret_variable(name: str) -> None:
    text = DOCUMENTS[name]
    assert "KALPAMANI_SHARADAR_SECRET_ID" not in text
    assert PRIVATE_PATH.search(text) is None


def test_the_private_path_scan_can_still_see_a_real_path() -> None:
    """A scanner that matched nothing would pass both documents vacuously."""
    assert PRIVATE_PATH.search(".runtime/phase3/anything.json") is not None
