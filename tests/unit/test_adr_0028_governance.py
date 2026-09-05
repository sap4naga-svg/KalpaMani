"""ADR-0028 governance: the four corrections, guarded structurally where a structure exists.

ADR-0027's specifications were accepted with four defects, and none of them is the kind a
substring check would have caught:

* a **deferral** where field-level contracts should be -- so the guards here **parse** the
  read-model catalog, the payload contracts, the endpoint catalog and the reference table,
  and compare them as sets. A read model with no contract, an endpoint with no per-endpoint
  row and a ``_ref`` with no declared resolution each fail;
* a reuse rule a **rename** defeated -- so the guards check the corrected invariant at its
  strictly stronger form, including the unknown-history case that must fail closed;
* a classification vocabulary that contradicted its own hosting rule -- so the guards check
  the two lists are separated, the label is not the publication gate, and the real
  governance provenance exists in every document that defines or uses it;
* one phrase doing four jobs -- so the guards check the four risk quantities are separately
  named, that the R denominator is the immutable one, and that a missing value is
  unavailable rather than inapplicable.

Every parser carries a self-test proving it can still see the defect it exists to catch: a
scanner that sees nothing passes every document vacuously.

What this suite does **not** do is re-assert ADR-0027's own invariants -- those are
``test_adr_0027_governance``'s, they still run, and duplicating them here would inflate a
count without protecting anything.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
COCKPIT: Final = PROJECT_ROOT / "docs" / "cockpit"

ADR: Final = DECISIONS / "ADR-0028-cockpit-contract-completion-and-boundary-corrections.md"
ADR_0027: Final = DECISIONS / "ADR-0027-cockpit-and-feedback-architecture-and-governance.md"
EXTENSION: Final = PROJECT_ROOT / "docs" / "architecture" / "COCKPIT_FEEDBACK_EXTENSION.md"
SPEC: Final = COCKPIT / "cockpit-v1-specification.md"
CONTRACTS: Final = COCKPIT / "read-model-contracts.md"
FEEDBACK: Final = COCKPIT / "feedback-self-maturation-specification.md"
UIUX: Final = COCKPIT / "ui-ux-specification.md"
MATRIX: Final = COCKPIT / "traceability-matrix.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _flat(text: str) -> str:
    """One document as a single line, read the way a reader reads it."""
    lines = [line.lstrip().removeprefix("> ").removeprefix(">") for line in text.splitlines()]
    return " ".join(" ".join(lines).replace("**", "").split())


ADR_TEXT: Final = _read(ADR)
ADR_FLAT: Final = _flat(ADR_TEXT)
CONTRACTS_TEXT: Final = _read(CONTRACTS)
CONTRACTS_FLAT: Final = _flat(CONTRACTS_TEXT)
FEEDBACK_TEXT: Final = _read(FEEDBACK)
FEEDBACK_FLAT: Final = _flat(FEEDBACK_TEXT)
EXTENSION_TEXT: Final = _read(EXTENSION)
EXTENSION_FLAT: Final = _flat(EXTENSION_TEXT)
SPEC_TEXT: Final = _read(SPEC)
SPEC_FLAT: Final = _flat(SPEC_TEXT)
UIUX_TEXT: Final = _read(UIUX)
MATRIX_TEXT: Final = _read(MATRIX)

#: The documents ADR-0028 amends, and which must therefore name it as their amender.
AMENDED: Final[dict[str, str]] = {
    "contracts": CONTRACTS_TEXT,
    "feedback": FEEDBACK_TEXT,
    "extension": EXTENSION_TEXT,
    "specification": SPEC_TEXT,
    "ui-ux": UIUX_TEXT,
    "matrix": MATRIX_TEXT,
}


# -- the decision itself -----------------------------------------------------------------


def test_the_decision_exists_at_its_exact_path() -> None:
    assert ADR.is_file()


def test_the_decision_declares_itself_proposed_and_not_in_force() -> None:
    assert "Status: PROPOSED — NOT IN FORCE" in ADR_TEXT


def test_the_decision_does_not_report_itself_as_in_force() -> None:
    assert "ADR-0028 is ACCEPTED / IN FORCE" not in ADR_FLAT
    assert "ADR-0028: ACCEPTED" not in ADR_FLAT


def test_the_corrections_carry_no_authority_while_the_pull_request_is_open() -> None:
    """The edits ship with the decision, so they are proposed with it."""
    assert "carries no authority" in ADR_FLAT
    assert "so are the corrections it makes to the Cockpit specifications" in ADR_FLAT
    for name, text in AMENDED.items():
        assert "PROPOSED and carries no authority while the pull request" in _flat(text), name


def test_the_decision_records_that_its_own_days_are_not_rewritten_later() -> None:
    assert "not to be rewritten as though this decision had authority" in ADR_FLAT


def test_acceptance_authorizes_no_implementation_and_no_execution() -> None:
    assert "Acceptance authorizes no implementation and no execution" in ADR_FLAT


def test_the_acceptance_event_is_stated_without_predicting_a_merge() -> None:
    assert "The acceptance event is exact" in ADR_FLAT
    assert "No merge SHA and no merge timestamp is predicted here" in ADR_FLAT


def test_the_decision_amends_no_adr_document() -> None:
    assert "**Supersedes:** nothing" in ADR_TEXT
    assert "It does not amend, supersede or edit ADR-0027 itself" in ADR_FLAT
    assert "No ADR is amended or superseded" in ADR_TEXT


def test_adr_0027_is_recorded_as_accepted_rather_than_reopened() -> None:
    """PR #71 merged. A correction must not restate the decision it corrects as proposed."""
    assert "ADR-0027 is ACCEPTED / IN FORCE" in ADR_FLAT
    assert "does not revert, reopen or restate ADR-0027 as proposed" in ADR_FLAT
    assert "751bf759fd6516149421a99ebf6c2c997c6c6766" in ADR_TEXT


def test_adr_0027_keeps_its_own_text_and_its_own_status() -> None:
    """The corrected decision is not edited, and does not learn about its successor."""
    text = _read(ADR_0027)
    assert "Status: PROPOSED — NOT IN FORCE" in text
    assert "ADR-0028" not in text


@pytest.mark.parametrize("name", sorted(AMENDED))
def test_every_amended_document_names_the_amending_decision(name: str) -> None:
    assert "ADR-0028" in AMENDED[name], name


def test_nothing_was_run_to_produce_the_decision() -> None:
    for claim in (
        "No AWS, STS, SSO, IAM, Secrets Manager or S3 call",
        "no Terraform command of any kind",
        "no `.runtime/` inspection",
        "no provider request",
        "no backtest",
        "No Blueprint PDF was opened or edited",
        "No dependency was installed",
    ):
        assert claim in ADR_FLAT, claim


def test_no_alpha_is_claimed() -> None:
    assert "No alpha is claimed anywhere in this decision" in ADR_TEXT


# -- A. the read-model contracts are complete, parsed rather than asserted ----------------


def _fenced(text: str) -> list[str]:
    return re.findall(r"```text\n(.*?)```", text, flags=re.DOTALL)


def _section(text: str, start: str, end: str) -> str:
    begin = text.find(start)
    if begin == -1:
        return ""
    stop = text.find(end, begin + len(start))
    return text[begin:] if stop == -1 else text[begin:stop]


CATALOG: Final = _section(CONTRACTS_TEXT, "## 4. Read-model catalog", "### 4.1 How to read")
PAYLOADS: Final = _section(CONTRACTS_TEXT, "### 4.5 The payload contracts", "### 4.6 Synthetic")
REFS: Final = _section(CONTRACTS_TEXT, "### 4.3 Resolving a reference", "### 4.4 The four risk")
ENDPOINT_SECTION: Final = _section(
    CONTRACTS_TEXT, "## 5. Endpoint catalog", "### 5.2 Cursor, snapshot"
)
METRICS: Final = _section(CONTRACTS_TEXT, "### 12.3 The metrics", "### 12.4 The hard cases")

#: ``| `ReadModelName` | owner | ...`` -- the first cell of a catalog row.
CATALOG_ROW: Final = re.compile(r"^\| `([A-Z][A-Za-z]+)` \| ", re.MULTILINE)
#: ``ReadModelName.payload {`` -- the opening line of a payload contract block.
PAYLOAD_BLOCK: Final = re.compile(r"^([A-Z][A-Za-z]+)\.payload \{", re.MULTILINE)


def catalogued_read_models(text: str) -> set[str]:
    return set(CATALOG_ROW.findall(text))


def contracted_read_models(text: str) -> set[str]:
    return {name for block in _fenced(text) for name in PAYLOAD_BLOCK.findall(block)}


def test_the_catalog_parser_sees_the_catalog() -> None:
    assert len(catalogued_read_models(CATALOG)) >= 35


def test_every_catalogued_read_model_has_a_payload_contract() -> None:
    missing = sorted(catalogued_read_models(CATALOG) - contracted_read_models(PAYLOADS))
    assert missing == [], missing


def test_every_payload_contract_belongs_to_a_catalogued_read_model() -> None:
    """A contract for a model nobody serves is a contract nobody reviews."""
    orphans = sorted(contracted_read_models(PAYLOADS) - catalogued_read_models(CATALOG))
    assert orphans == [], orphans


def test_the_contract_parsers_would_notice_a_missing_contract() -> None:
    catalog = "| `Widget` | owner | input | `SYNTHETIC` |\n"
    payloads = "```text\nOther.payload {\n    x  Y  required\n}\n```"
    assert catalogued_read_models(catalog) - contracted_read_models(payloads) == {"Widget"}


def test_the_field_level_deferral_is_gone() -> None:
    for deferral in (
        "Selected payload shapes",
        "Full field-level definitions belong to the implementation cycle",
        "metric-defined",
    ):
        assert deferral not in CONTRACTS_TEXT, deferral


def test_every_field_contract_states_type_unit_requiredness_and_absence() -> None:
    assert "**Every field below carries four things**" in CONTRACTS_TEXT
    for dimension in ("**type**", "**unit**", "**requiredness**", "**absence**"):
        assert dimension in CONTRACTS_TEXT, dimension
    assert "never a bare `null`, and never a zero" in CONTRACTS_TEXT


def test_a_nullable_value_arrives_only_in_a_metric_value() -> None:
    assert "The ONLY wrapper a nullable number arrives in" in CONTRACTS_TEXT


def test_reusable_types_are_defined_once() -> None:
    for defined in (
        "SafeId",
        "Money",
        "Ratio",
        "Magnitude",
        "MetricValue",
        "Ref",
        "RefList",
        "VersionPins",
        "PolicyRef",
        "Series",
        "ReasonCoded",
    ):
        assert defined in CONTRACTS_TEXT, defined


# -- references resolve, and none dangles ------------------------------------------------

#: ``| `candidate` | resolves to | resolution | cardinality |`` -- the resolution table.
REF_ROW: Final = re.compile(r"^\| `([a-z_]+)` \| ", re.MULTILINE)
#: ``kind candidate`` / ``kind evidence or source_fact`` inside a payload contract.
REF_USE: Final = re.compile(r"\bkind ([a-z_]+)(?: or ([a-z_]+))?")


def declared_ref_kinds(text: str) -> set[str]:
    return set(REF_ROW.findall(text))


def used_ref_kinds(text: str) -> set[str]:
    used: set[str] = set()
    for block in _fenced(text):
        for first, second in REF_USE.findall(block):
            used.add(first)
            if second:
                used.add(second)
    return used


def test_the_reference_table_declares_a_substantial_set() -> None:
    assert len(declared_ref_kinds(REFS)) >= 20


def test_no_reference_used_in_a_payload_lacks_a_declared_resolution() -> None:
    dangling = sorted(used_ref_kinds(PAYLOADS) - declared_ref_kinds(REFS))
    assert dangling == [], dangling


def test_the_reference_parsers_would_notice_a_dangling_ref() -> None:
    declared = "| `candidate` | CandidateDetail | ENDPOINT | ZERO_OR_ONE |\n"
    used = "```text\nX.payload {\n    a_ref  Ref  required, kind mystery\n}\n```"
    assert used_ref_kinds(used) - declared_ref_kinds(declared) == {"mystery"}


def test_every_resolution_mode_is_defined() -> None:
    for mode in ("ENDPOINT", "EMBEDDED", "AUTHORIZED_READ", "UNRESOLVABLE_V1"):
        assert mode in CONTRACTS_TEXT, mode
    assert "is a stated resolution, not a gap" in CONTRACTS_FLAT


def test_resolving_a_reference_widens_no_producing_contract() -> None:
    assert "Resolving a reference is an authorized read, not a widening" in CONTRACTS_FLAT
    assert "Every `_ref` is a **safe internal reference**" in CONTRACTS_TEXT


# -- endpoints declare their contract -----------------------------------------------------

#: ``GET  /api/v1/portfolio/trades`` in the fenced catalog.
CATALOG_ENDPOINT: Final = re.compile(r"^GET\s+/api/v1(\S*)", re.MULTILINE)
#: ``| `/portfolio/trades` | response | ...`` in the per-endpoint table.
CONTRACT_ENDPOINT: Final = re.compile(r"^\| `(/[^`]*)` \| ", re.MULTILINE)


def catalogued_endpoints(text: str) -> set[str]:
    return {match for block in _fenced(text) for match in CATALOG_ENDPOINT.findall(block)}


def contracted_endpoints(text: str) -> set[str]:
    return set(CONTRACT_ENDPOINT.findall(text))


def test_the_endpoint_parsers_see_the_catalog_and_the_table() -> None:
    assert len(catalogued_endpoints(ENDPOINT_SECTION)) >= 35
    assert len(contracted_endpoints(ENDPOINT_SECTION)) >= 35


def test_every_catalogued_endpoint_declares_its_contract() -> None:
    catalogued = catalogued_endpoints(ENDPOINT_SECTION)
    contracted = contracted_endpoints(ENDPOINT_SECTION)
    assert sorted(catalogued - contracted) == []


def test_every_contracted_endpoint_is_in_the_catalog() -> None:
    catalogued = catalogued_endpoints(ENDPOINT_SECTION)
    contracted = contracted_endpoints(ENDPOINT_SECTION)
    assert sorted(contracted - catalogued) == []


def test_the_endpoint_parsers_would_notice_an_undeclared_endpoint() -> None:
    catalog = "```text\nGET  /api/v1/widgets\n```"
    table = "| `/gadgets` | Gadget page | — | — | 25 / 100 | 10 |\n"
    assert catalogued_endpoints(catalog) - contracted_endpoints(table) == {"/widgets"}


def test_read_resource_limits_are_not_trading_limits() -> None:
    assert "They are not trading risk limits" in CONTRACTS_TEXT
    assert "They are not trading risk limits" in ADR_TEXT


def test_a_bound_owned_by_a_policy_is_a_reference_and_not_a_number() -> None:
    assert "POLICY_REFERENCE_MISSING" in CONTRACTS_TEXT
    assert "rather than served under a default nobody approved" in CONTRACTS_FLAT


def test_cursor_snapshot_and_error_semantics_are_declared() -> None:
    for clause in (
        "A cursor is never a row offset",
        "it never silently continues across two snapshots",
        "A silently truncated result is a wrong answer wearing a correct one's shape",
    ):
        assert clause in CONTRACTS_FLAT, clause
    for code in (
        "UNKNOWN_SCHEMA_VERSION",
        "PAGE_SIZE_EXCEEDED",
        "EXTENT_EXCEEDED",
        "CURSOR_SNAPSHOT_SUPERSEDED",
        "CLASSIFICATION_WITHHELD",
    ):
        assert code in CONTRACTS_TEXT, code


# -- the metric dictionary ----------------------------------------------------------------

#: ``| `metric.id` | formula | unit | basis | minimum | unavailable |`` -- six cells.
METRIC_ROW: Final = re.compile(r"^\| `([a-z_.]+(?:` · `\.[a-z_]+)*)` \| (.+)$", re.MULTILINE)


def metric_rows(text: str) -> list[tuple[str, list[str]]]:
    rows: list[tuple[str, list[str]]] = []
    for name, rest in METRIC_ROW.findall(text):
        cells = [cell.strip() for cell in rest.split(" | ")]
        rows.append((name, cells))
    return rows


def test_the_metric_parser_sees_the_dictionary() -> None:
    assert len(metric_rows(METRICS)) >= 25


def test_every_metric_states_all_five_remaining_dimensions() -> None:
    """Formula, unit and denominator, basis, minimum observations, unavailable outcome."""
    thin = [name for name, cells in metric_rows(METRICS) if len(cells) < 5 or not all(cells[:5])]
    assert thin == [], thin


def test_the_metric_parser_would_notice_a_thin_row() -> None:
    sample = "| `thing.value` | a rule |  | | | |\n"
    assert [name for name, cells in metric_rows(sample) if not all(cells[:5])] == ["thing.value"]


@pytest.mark.parametrize(
    "metric_id",
    [
        "return.time_weighted",
        "return.money_weighted",
        "drawdown.max",
        "expectancy.currency",
        "profit_factor",
        "win_rate",
        "sharpe",
        "r_multiple",
        "mfe",
        "mae",
        "capture_ratio",
        "slippage",
        "latency.order_to_fill",
        "benchmark.movement",
    ],
)
def test_each_required_metric_is_defined(metric_id: str) -> None:
    assert f"| `{metric_id}` |" in METRICS, metric_id


def test_naive_return_is_refused_rather_than_offered() -> None:
    assert "`return.naive` | **not defined, and not offered.**" in METRICS
    assert "`return.naive` does not exist" in CONTRACTS_FLAT


def test_external_cash_flows_are_never_reported_as_performance() -> None:
    assert "deposits and withdrawals are `cashflow.external` and **are never profit**" in (
        CONTRACTS_TEXT
    )
    assert "an external flow produces **no** drawdown and **no** new peak" in CONTRACTS_TEXT


def test_realized_costs_are_not_subtracted_twice() -> None:
    assert "already incorporates the spread crossed and the slippage realized" in CONTRACTS_FLAT
    assert "no modelled spread or slippage estimate is applied on top of an actual fill" in (
        CONTRACTS_FLAT
    )
    assert "no modelled spread" in ADR_FLAT


def test_capture_ratio_requires_compatible_units() -> None:
    assert "same unit, frequency and price basis" in CONTRACTS_FLAT
    assert "is refused rather than divided" in CONTRACTS_FLAT


def test_display_sufficiency_is_not_evidence_of_validity() -> None:
    assert "Display sufficiency is not evidence of validity" in CONTRACTS_TEXT
    assert "A metric that passes every rule here is still not a finding" in CONTRACTS_FLAT
    assert "Display sufficiency is not evidence of strategy validity" in ADR_FLAT


# -- B. out-of-sample exposure is tracked across registrations -----------------------------


def test_consumption_is_per_locked_set_and_not_per_registration() -> None:
    assert "consumed **once per locked set**" in FEEDBACK_TEXT
    assert "not once per registration" in FEEDBACK_FLAT


def test_a_new_identity_does_not_clear_exposure() -> None:
    assert (
        "a new hypothesis, registration or Challenger identity does not make exposed data "
        "untouched again" in FEEDBACK_FLAT
    )
    assert "A registration identity is not a reset button" in FEEDBACK_TEXT


def test_exposure_is_inherited_through_related_research_lineage() -> None:
    for lineage in (
        "parent registration",
        "amendment chain",
        "shared named baseline",
        "shared queue trigger or failure cluster",
        "shared Challenger derivation",
    ):
        assert lineage in FEEDBACK_FLAT, lineage
    assert "A derived experiment does not get a clean set because it was given a new name" in (
        FEEDBACK_FLAT
    )


def test_unknown_exposure_history_fails_closed() -> None:
    assert "Unknown exposure history cannot support a fresh out-of-sample claim" in FEEDBACK_FLAT
    assert "An absence of recorded exposure is not evidence of absent exposure" in FEEDBACK_FLAT


def test_budgets_and_multiple_testing_records_do_not_reset_through_renaming() -> None:
    assert "do not reset through renaming" in FEEDBACK_FLAT
    assert "even on its first run of its own" in FEEDBACK_FLAT


@pytest.mark.parametrize(
    "evaluation_class",
    ["DETERMINISTIC_REPRODUCTION", "EXPLORATORY_REUSE", "CONFIRMATORY"],
)
def test_each_evaluation_class_is_defined(evaluation_class: str) -> None:
    assert evaluation_class in FEEDBACK_TEXT, evaluation_class
    assert evaluation_class in ADR_TEXT, evaluation_class


def test_the_three_classes_claim_exactly_what_they_may() -> None:
    assert "no new confirmation of anything" in FEEDBACK_FLAT.lower()
    assert "disclosed, and never presented as fresh out-of-sample" in FEEDBACK_FLAT
    assert "the **only** class that may be described as out-of-sample confirmation" in (
        FEEDBACK_TEXT
    )


@pytest.mark.parametrize(
    "refusal",
    [
        "OUT_OF_SAMPLE_ALREADY_CONSUMED",
        "EXPOSURE_HISTORY_UNKNOWN",
        "RELATED_LINEAGE_EXPOSED",
        "BUDGET_EXHAUSTED_ACROSS_LINEAGE",
        "REUSE_METHODOLOGY_UNAUTHORIZED",
        "REPRODUCTION_MISMATCH",
    ],
)
def test_each_reuse_refusal_is_named(refusal: str) -> None:
    assert refusal in FEEDBACK_TEXT, refusal


def test_the_negative_control_for_a_renamed_reuse_is_required() -> None:
    assert "The negative control this rule exists for" in FEEDBACK_TEXT
    assert "That case is a required test of any implementation" in FEEDBACK_FLAT


def test_preregistration_and_failed_trials_are_preserved_unchanged() -> None:
    assert "Preregistration stays immutable" in FEEDBACK_TEXT
    assert "failed and abandoned trials are still retained and still count" in FEEDBACK_FLAT
    assert "None of that is relaxed here" in FEEDBACK_FLAT


def test_governance_packets_carry_the_exposure_disclosure() -> None:
    assert "EXPOSURE_DISCLOSURE_INCOMPLETE" in FEEDBACK_TEXT
    assert "the exposure ledger of every locked set the evidence rests on" in FEEDBACK_FLAT
    assert "exposure_disclosure" in CONTRACTS_TEXT


# -- C. licensed-data admission, and the label that is not a gate --------------------------


def test_credentials_and_payload_content_are_two_separate_lists() -> None:
    assert "List A — credentials and infrastructure identifiers" in CONTRACTS_TEXT
    assert "List B — classified payload content" in CONTRACTS_TEXT
    assert "at any classification, in any environment, on any host, under any authorization" in (
        CONTRACTS_FLAT
    )


def test_a_licensed_derived_projection_is_legitimate_inside_the_boundary() -> None:
    assert "Licensed-derived is not a defect; publishing it is" in CONTRACTS_TEXT
    assert "is legitimate inside the private boundary" in EXTENSION_FLAT
    assert "belongs inside the\nboundary" in ADR_TEXT


@pytest.mark.parametrize(
    "destination",
    ["public Git", "external LLM", "third-party hosting", "external cache", "telemetry"],
)
def test_licensed_content_still_leaves_for_nowhere(destination: str) -> None:
    assert destination in CONTRACTS_FLAT, destination
    assert destination in ADR_FLAT, destination


def test_classification_is_a_label_and_publication_is_a_gate() -> None:
    assert "Classification is a label; publication is a gate" in CONTRACTS_TEXT
    assert "A `PUBLIC_SAFE` label does not authorize publication" in CONTRACTS_TEXT
    assert "It does not bypass a required release" in ADR_FLAT
    assert "Classification is a sensitivity label; publication is a separate authorization" in (
        EXTENSION_FLAT
    )


def test_the_repository_tracked_provenance_exists_wherever_it_is_used() -> None:
    for name, text in (
        ("contracts", CONTRACTS_TEXT),
        ("extension", EXTENSION_TEXT),
        ("decision", ADR_TEXT),
        ("specification", SPEC_TEXT),
    ):
        assert "REPOSITORY_TRACKED" in text, name


def test_a_real_fact_is_never_relabelled_synthetic() -> None:
    assert "REAL, and never relabelled SYNTHETIC" in CONTRACTS_FLAT
    assert "A real fact is never relabelled to fit a hosting rule" in CONTRACTS_FLAT
    assert "a real fact is never relabelled `SYNTHETIC` to get" in CONTRACTS_TEXT
    assert "never relabelled `SYNTHETIC` to satisfy a hosting rule" in ADR_TEXT


def test_the_public_edge_admission_is_enumerated_rather_than_implied() -> None:
    assert "What may be displayed on `PUBLIC_EDGE`, exactly" in CONTRACTS_TEXT
    for read_model in ("QualificationStatus", "AttentionItem", "WhatChangedEntry"):
        assert read_model in _section(
            CONTRACTS_TEXT, "### 7.1 Classification is a label", "**Nothing else"
        ), read_model


def test_uncertain_classification_fails_closed_as_licensed() -> None:
    assert "treated as `LICENSED_DERIVED` for the purpose of every" in CONTRACTS_TEXT
    assert "refused rather than downgraded" in CONTRACTS_FLAT
    assert "Uncertain classification fails closed" in EXTENSION_FLAT


def test_a_render_proxy_or_build_path_cannot_bypass_the_boundary() -> None:
    assert "an edge cache and a build-time fetch are each a copy" in CONTRACTS_FLAT
    assert "cannot bypass the private boundary" in ADR_FLAT


def test_control_publication_stays_deferred_and_refused() -> None:
    assert "CONTROL publication remains DEFERRED" in CONTRACTS_FLAT
    assert "refused at admission regardless of host, label, authorization or scope" in (
        CONTRACTS_FLAT
    )


def test_audit_corrections_and_deletions_append_rather_than_mutate() -> None:
    assert "Deletion and correction append; they never mutate" in CONTRACTS_TEXT
    assert "Corrections and deletions append; they never mutate" in EXTENSION_TEXT
    assert "The original event is not edited, redacted in place or overwritten" in EXTENSION_FLAT
    assert "The governance evidence is preserved; the vendor data is not retained" in CONTRACTS_TEXT


def test_an_audit_event_carries_evidence_and_never_a_licensed_copy() -> None:
    assert "never a copy of deletable licensed content" in CONTRACTS_FLAT
    assert "never a copy of deletable licensed content" in ADR_FLAT


def test_cached_copies_carry_the_deletion_obligation_without_implementing_it() -> None:
    assert "carry the deletion obligation with them" in CONTRACTS_FLAT
    assert "This document states that obligation and implements no deletion" in CONTRACTS_FLAT
    assert "grants no operational authority to delete, retain or copy anything" in (EXTENSION_FLAT)


def test_deletion_never_depends_on_a_locator_to_find_licensed_objects() -> None:
    assert "Deletion must never depend on an audit event, a projection or a locator" in (
        CONTRACTS_FLAT
    )


# -- D. initial risk and current risk are separate facts ------------------------------------


@pytest.mark.parametrize(
    "quantity",
    ["InitialPlannedRisk", "CurrentOpenPlannedRisk", "PermittedRisk", "GapEventRisk"],
)
def test_each_risk_quantity_has_its_own_type(quantity: str) -> None:
    assert quantity in CONTRACTS_TEXT, quantity


def test_the_four_risk_quantities_are_kept_apart_in_both_documents() -> None:
    assert "The four risk quantities, kept apart" in CONTRACTS_TEXT
    assert "The four risk quantities, kept apart" in EXTENSION_TEXT
    assert "was doing four jobs" in ADR_FLAT


def test_initial_planned_risk_is_immutable_and_is_the_r_denominator() -> None:
    assert "risk_money            Money         required, IMMUTABLE" in CONTRACTS_TEXT
    assert "the only denominator an R multiple may use" in CONTRACTS_FLAT
    assert "A moving stop does not move it" in CONTRACTS_FLAT
    assert "a moving stop does not move it" in EXTENSION_FLAT.lower()


def test_current_open_planned_risk_carries_its_as_of_and_its_source() -> None:
    assert "meaningless without its `as_of`" in CONTRACTS_TEXT
    assert "The Cockpit displays it and computes none of it" in CONTRACTS_FLAT
    assert "RISK_ENGINE_ASSESSMENT" in CONTRACTS_TEXT


def test_a_permitted_value_never_appears_without_its_policy_reference() -> None:
    assert "A permitted value with no versioned reference is `POLICY_REFERENCE_MISSING`" in (
        CONTRACTS_TEXT
    )
    assert "never appears without its versioned policy reference" in EXTENSION_FLAT


def test_gap_and_event_risk_is_modelled_separately() -> None:
    assert "a SEPARATE model, never folded" in CONTRACTS_TEXT
    assert "never added into either planned-risk figure" in CONTRACTS_FLAT


@pytest.mark.parametrize(
    "case",
    [
        "partial fill",
        "partial exit",
        "add or pyramid",
        "protection change",
        "closed portion",
        "stale assessment",
        "missing assessment",
        "missing initial risk",
        "aggregation",
    ],
)
def test_each_risk_lifecycle_case_is_decided(case: str) -> None:
    assert f"**{case}**" in CONTRACTS_TEXT, case


def test_an_add_carries_its_own_record_and_the_original_is_retained() -> None:
    assert "The trade's original record is retained unchanged" in CONTRACTS_FLAT
    assert "the sum of the retained per-stage initial planned risks" in CONTRACTS_FLAT


def test_aggregation_counts_each_position_once() -> None:
    assert "over **open** exposure only, **once per position**" in CONTRACTS_TEXT
    assert "An add is part of its trade and is not counted a second time" in CONTRACTS_FLAT


def test_missing_initial_risk_is_unavailable_rather_than_inapplicable() -> None:
    assert "It is unavailable, not inapplicable" in CONTRACTS_FLAT
    assert "`NOT_DEFINED_FOR_SUBJECT` is the only route to `NOT_APPLICABLE`" in CONTRACTS_TEXT
    assert "Missing initial planned risk is unavailable, not inapplicable" in EXTENSION_FLAT


def test_the_cockpit_invents_no_trading_permission() -> None:
    assert "invents no trading permission" in CONTRACTS_FLAT
    assert "invents no trading permission" in EXTENSION_FLAT
    assert "Showing a permitted limit is not granting it" in CONTRACTS_FLAT


def test_no_risk_limit_or_capital_value_changes() -> None:
    for text, name in ((CONTRACTS_FLAT, "contracts"), (EXTENSION_FLAT, "extension")):
        assert "changes no risk limit" in text, name
    assert "no risk limit, capital value, leverage setting, sizing rule or stop policy changes" in (
        ADR_FLAT
    )


# -- what the correction preserves ----------------------------------------------------------


def test_all_thirty_six_areas_and_the_delivery_sequence_survive() -> None:
    assert len(re.findall(r"^## Area (\d+) — ", SPEC_TEXT, re.MULTILINE)) == 36
    assert "all 36 product areas stay in V1 scope" in ADR_FLAT
    assert "the C1-C10 delivery sequence is unchanged" in ADR_FLAT


def test_the_four_trade_concepts_stay_separate() -> None:
    for concept in ("Trade History", "Trade Detail", "Execution History", "Audit Trail"):
        assert concept in SPEC_TEXT, concept
    assert "stay four separate screens" in ADR_FLAT


def test_the_brain_contract_is_untouched() -> None:
    assert "the Brain ends at CandidateIntent" in ADR_FLAT
    assert "`CandidateIntent` gains nothing" in ADR_TEXT
    assert "no sizing or execution field is added to CandidateIntent" in ADR_TEXT
    assert "no share count, dollar amount, final position size" in CONTRACTS_FLAT


def test_trade_status_and_data_completeness_stay_separate() -> None:
    assert "BUSINESS\n                                            status only" in CONTRACTS_TEXT
    assert "business status and data completeness are separate fields" in CONTRACTS_FLAT
    assert "neither is inferred from the other" in SPEC_FLAT


def test_no_cross_environment_or_cross_provenance_blend() -> None:
    assert "no trade blends environments or provenances" in CONTRACTS_FLAT
    assert (
        "a `BACKTEST_SIMULATED` series and a `SYSTEM_RECORDED` series never share a"
        in CONTRACTS_TEXT
    )


def test_health_recovery_authority_is_displayed_and_not_widened() -> None:
    assert "RESTORATION IS NOT" in CONTRACTS_TEXT
    assert "is neither strengthened nor widened by this contract" in CONTRACTS_FLAT


def test_governance_stays_read_only_and_controls_stay_inert() -> None:
    assert "V1 stays observational and READ-ONLY is still defined by absence" in ADR_FLAT
    assert "no executable handler and no control API route" in ADR_FLAT
    assert "still originate no authoritative approval record" in ADR_FLAT


def test_no_source_module_dependency_or_scaffolding_is_created() -> None:
    assert "no source module is created" in ADR_FLAT.lower()
    assert "no dependency is installed" in ADR_FLAT.lower()
    assert "no application is scaffolded" in ADR_FLAT.lower()
    assert not (PROJECT_ROOT / "src" / "kalpamani" / "cockpit").exists()


# -- continuing governance state -------------------------------------------------------------


@pytest.mark.parametrize(
    "claim",
    [
        "G1 OPEN · G2 OPEN · G3 CLOSED · G4 OPEN · G5 OPEN · G6 OPEN · G7 OPEN",
        "Run A COMPLETED ONCE, 2026-09-04 · Run A retry NOT AUTHORIZED",
        "Run B NOT RUN / NOT AUTHORIZED · earliest approved target 2026-09-12",
        "combined assessment NOT RUN / NOT AUTHORIZED · P1–P9 UNEVALUATED",  # noqa: RUF001
        "provider selected NONE · backtesting NOT STARTED",
    ],
)
def test_the_decision_reports_the_continuing_state(claim: str) -> None:
    assert claim in ADR_TEXT, claim


def test_each_gate_is_read_independently() -> None:
    assert "No blanket statement about all seven is correct" in ADR_TEXT


def test_the_run_a_to_run_b_separation_is_unchanged() -> None:
    assert "at least\neight calendar day Run A to Run B separation is unchanged" in ADR_TEXT
    assert "seven calendar day" not in ADR_TEXT.lower()


def test_passing_the_date_gate_is_not_execution_authorization() -> None:
    assert "Passing the 2026-09-12 date gate is not execution authorization" in ADR_TEXT


def test_live_trading_stays_hard_disabled_everywhere() -> None:
    assert "HARD-DISABLED" in ADR_TEXT
    for name, text in AMENDED.items():
        assert "HARD-DISABLED" in text, name


def test_the_five_gates_stay_separate() -> None:
    assert "five separate gates" in ADR_FLAT
