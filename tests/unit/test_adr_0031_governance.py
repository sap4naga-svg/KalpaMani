"""ADR-0031 governance: the owning-area navigation contract, parsed and executed.

ADR-0031 is a **proposal**. These are therefore **proposal tests**: they check that the
proposed rules are present, internally consistent and satisfiable, and they check that the
application's runtime has **not** been changed to implement them. Nothing here asserts that
the Cockpit behaves this way today, because it does not and is not authorized to.

The suite has four parts.

* **Governance** -- ADR-0031 declares itself proposed, predicts no merge, amends ADR-0030 at
  R10 only, edits no ADR document, and authorizes no implementation.
* **The contract, executed** -- the ``OwningArea`` table, the association rules, the
  availability states and the access boundary are parsed out of ``read-model-contracts.md``
  and run. There is no second copy of the route table in this file: it is read from the
  document at import time, so a document that loses a row fails here.
* **The product surface** -- the specification, UI and traceability deltas that carry the
  same conditional authority, and the two limitations that stay open.
* **The pending gap** -- the runtime is asserted to be **unchanged**, so a later reader can
  tell that the proposal was documented and not silently implemented.

Every parser carries a self-test proving it can still see what it exists to catch: a scanner
that sees nothing passes every document vacuously.
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
COCKPIT_APP: Final = PROJECT_ROOT / "apps" / "cockpit" / "src"

ADR: Final = DECISIONS / "ADR-0031-reference-owning-area-navigation.md"
CONTRACTS: Final = COCKPIT / "read-model-contracts.md"
V1_SPEC: Final = COCKPIT / "cockpit-v1-specification.md"
UI_SPEC: Final = COCKPIT / "ui-ux-specification.md"
MATRIX: Final = COCKPIT / "traceability-matrix.md"
VALUES: Final = COCKPIT_APP / "contracts" / "values.ts"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8")
CONTRACTS_TEXT: Final = CONTRACTS.read_text(encoding="utf-8")


def flatten(text: str) -> str:
    """One line, so a rule broken across a wrap is still one phrase."""
    return " ".join(text.split())


ADR_FLAT: Final = flatten(ADR_TEXT)
CONTRACTS_FLAT: Final = flatten(CONTRACTS_TEXT)


def section(text: str, start: str, end: str) -> str:
    """One named span, so a match elsewhere in a long file does not count."""
    begin = text.find(start)
    if begin == -1:
        return ""
    stop = text.find(end, begin + len(start))
    return text[begin:] if stop == -1 else text[begin:stop]


# --------------------------------------------------------------------- governance


def test_the_adr_declares_itself_proposed_and_not_in_force() -> None:
    assert "**Status: PROPOSED — NOT IN FORCE." in ADR_TEXT
    assert "ADR-0031 is ACCEPTED / IN FORCE" not in ADR_FLAT


def test_the_adr_claims_no_authority_while_its_pull_request_is_open() -> None:
    assert "carries no authority" in ADR_FLAT
    assert "it is not to be rewritten as though this decision had authority" in ADR_FLAT


def test_the_adr_predicts_no_merge_sha_and_no_timestamp() -> None:
    assert "No merge SHA and no merge timestamp is predicted here" in ADR_FLAT
    assert re.search(r"\b[0-9a-f]{40}\b", ADR_TEXT) is None, "a forty-character SHA appears"


def test_the_adr_binds_its_acceptance_event_to_one_actual_pull_request() -> None:
    """Bound to the pull request that actually introduces it, and to exactly one number.

    An acceptance event naming no pull request is not checkable, and one naming two is not an
    event. The number is bound by an ordinary commit once the pull request exists, so no
    placeholder survives; the merge SHA and timestamp are still not predicted.
    """
    assert "**The acceptance event is exact:**" in ADR_TEXT
    span = flatten(section(ADR_TEXT, "**The acceptance event is exact:**", "**Date:**"))
    assert "independent review and merge of **pull request #" in span
    numbers = set(re.findall(r"pull request #(\d+)", ADR_TEXT))
    assert len(numbers) == 1, f"exactly one pull-request number is bound, found {numbers}"


def test_both_status_documents_bind_the_same_pull_request_number() -> None:
    """A status document naming a different number would send a reader to another review."""
    (bound,) = set(re.findall(r"pull request #(\d+)", ADR_TEXT))
    for name in ("CLAUDE.md", "README.md"):
        status = flatten((PROJECT_ROOT / name).read_text(encoding="utf-8"))
        span = section(
            status,
            "[ADR-0031](docs/decisions/ADR-0031-reference-owning-area-navigation.md)",
            "On independent review and merge",
        )
        assert f"PR #{bound}" in span, f"{name} does not bind ADR-0031 to PR #{bound}"


def test_the_adr_amends_adr_0030_at_r10_only_and_edits_no_adr_document() -> None:
    assert "at **R10\nonly**" in ADR_TEXT or "at **R10 only**" in ADR_FLAT
    assert "It amends no other rule of ADR-0030" in ADR_FLAT
    assert "whose R1" in ADR_FLAT and "R9 and R4.1 are untouched" in ADR_FLAT
    assert (
        "it does not amend, supersede or edit ADR-0026, ADR-0027, ADR-0028 or ADR-0029" in ADR_FLAT
    )
    assert "**Supersedes:** nothing" in ADR_TEXT


def test_the_adr_authorizes_no_implementation_and_records_the_pending_follow_up() -> None:
    assert "This decision implements no runtime behaviour, and none is authorized by it" in ADR_FLAT
    assert "It is a separate authorization**, and it is not opened by merging this decision" in (
        ADR_FLAT
    )
    assert (
        "Specification, implementation, research, deployment and execution stay five separate gates"
        in ADR_FLAT
    )


def test_the_adr_ran_nothing_and_claims_no_alpha() -> None:
    assert "Nothing was run to produce this decision." in ADR_FLAT
    assert "No alpha is claimed anywhere in this decision." in ADR_FLAT
    assert "No Blueprint PDF was opened or edited." in ADR_FLAT


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("Cockpit runtime behaviour changed by this decision", "NONE"),
        ("new src/ or apps/cockpit/src/ modules created", "NONE"),
        ("routes, fixtures or dependencies added", "NONE"),
        ("schema_version values changed by this decision", "NONE"),
        ("the pending reference-enforcement pull request", "NOT EDITED / NOT MERGED"),
        ("a general evidence retrieval endpoint", "NOT CREATED / STILL OPEN"),
        ("a reference-carried scope expression", "NOT CREATED / STILL OPEN"),
        ("C7 research and feedback interfaces", "NOT STARTED"),
        ("C5 completion follow-up", "STILL PENDING / NOT AUTHORIZED"),
        ("Run A retry", "NOT AUTHORIZED / NOT RUN"),
        ("Run B", "NOT AUTHORIZED / NOT RUN"),
        ("combined assessment", "NOT AUTHORIZED / NOT RUN"),
        ("P1-P9", "UNEVALUATED"),
        ("G1 / G2", "OPEN / OPEN"),
        ("provider selected", "NONE"),
        ("backtesting", "NOT STARTED"),
        ("Phase 3", "NOT COMPLETE"),
        ("CONTROL", "DEFERRED"),
        ("live trading", "HARD-DISABLED"),
        ("AWS / Terraform operations", "NONE"),
        ("broker, LEAN and IBKR activity", "NONE"),
    ],
)
def test_the_adr_leaves_every_standing_gate_where_it_was(label: str, value: str) -> None:
    """Each gate is read from the ADR's own status block, label and value together."""
    stated = [line for line in ADR_TEXT.splitlines() if line.startswith(f"{label}:")]
    assert len(stated) == 1, f"ADR-0031 states {label!r} exactly once"
    assert stated[0].split(":", 1)[1].strip() == value


# ------------------------------------------------- the owning-area table, executed


def owning_area_rows() -> dict[str, tuple[str, str]]:
    """``owning_area`` -> (area number, route), parsed from the section 4.3.2 table."""
    table = section(
        CONTRACTS_TEXT,
        "| `owning_area` | Area | Route | Authority for the ownership |",
        "**`AUDIT_TRAIL` is a member",
    )
    rows: dict[str, tuple[str, str]] = {}
    for line in table.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or not cells[0].startswith("`"):
            continue
        member = cells[0].strip("`")
        if member == "owning_area":
            continue
        rows[member] = (cells[1], cells[2].strip("`"))
    return rows


AREAS: Final = owning_area_rows()

#: Every member the vocabulary declaration in section 4.2 promises.
EXPECTED_MEMBERS: Final = frozenset(
    {
        "DATA_QUALITY",
        "STRATEGY_HEALTH",
        "RECONCILIATION",
        "SHORT_SIDE",
        "ALERTS",
        "SYSTEM_OPERATIONS",
        "AUDIT_TRAIL",
    }
)


def test_the_row_parser_sees_the_whole_table() -> None:
    """A scanner that sees nothing passes every document, so it is checked first."""
    assert len(AREAS) == 7, f"seven rows are parsed, saw {sorted(AREAS)}"


def test_the_row_parser_would_notice_a_removed_row() -> None:
    """The self-test: the parser is run over a table one row short."""
    mutated = CONTRACTS_TEXT.replace("| `SHORT_SIDE` | 13 | `/risk/short-side` |", "| `NOT_A_ROW`")
    table = section(
        mutated,
        "| `owning_area` | Area | Route | Authority for the ownership |",
        "**`AUDIT_TRAIL` is a member",
    )
    parsed = [
        line
        for line in table.splitlines()
        if len([c for c in line.strip().strip("|").split("|")]) == 4
        and line.strip().startswith("| `")
    ]
    assert len(parsed) < 8, "the mutated table must parse fewer rows than the real one"


def test_the_vocabulary_and_the_table_name_the_same_seven_members() -> None:
    assert set(AREAS) == EXPECTED_MEMBERS


def test_section_four_two_declares_the_vocabulary_closed_at_seven() -> None:
    span = section(CONTRACTS_TEXT, "OwningArea      the SEVEN members", "```")
    flat = flatten(span)
    assert "rows of the §4.3.2 table" in flat
    assert "refused at the boundary, never rendered and never coerced" in flat
    assert "SECOND, SEPARATE axis from RefKind and is never a substitute for one" in flat


def test_every_route_is_an_internal_area_landing_path_with_no_entity_segment() -> None:
    for member, (_area, route) in AREAS.items():
        assert route.startswith("/"), f"{member} route is not an internal absolute path"
        assert "{" not in route and "}" not in route, f"{member} route carries a segment template"
        assert "://" not in route, f"{member} route names an origin"


def test_every_area_number_is_a_plain_cockpit_area_number() -> None:
    for member, (area, _route) in AREAS.items():
        assert area.isdigit(), f"{member} does not name one area number"
        assert 1 <= int(area) <= 36, f"{member} names an area outside Cockpit V1"


def test_no_two_members_claim_the_same_area() -> None:
    numbers = [area for area, _route in AREAS.values()]
    assert len(numbers) == len(set(numbers)), "one area is claimed by two members"


def test_the_borrow_case_resolves_to_the_short_side_area_and_not_to_audit() -> None:
    """Resolved from repository authority, and named as such."""
    assert AREAS["SHORT_SIDE"] == ("13", "/risk/short-side")
    assert "The borrow case is resolved explicitly" in ADR_FLAT
    assert "`SHORT_SIDE` is therefore its owning area**, and it is not `AUDIT_TRAIL`" in ADR_FLAT


def test_the_short_side_route_and_area_agree_with_the_traceability_matrix() -> None:
    """The authority is read, not asserted: area 13 is the Short-Side Dashboard."""
    matrix = MATRIX.read_text(encoding="utf-8")
    assert "| 13 | Short-Side Dashboard |" in matrix
    assert "/risk/short-side" in flatten(CONTRACTS_TEXT)


def test_audit_trail_is_a_member_and_is_never_a_default() -> None:
    for text in (ADR_FLAT, CONTRACTS_FLAT):
        assert "`AUDIT_TRAIL` is a member and is NEVER a default" in text or (
            "`AUDIT_TRAIL` is a member and is never a default" in text
        )
        assert "never resolves to it" in text
    assert "no rule may use it as a fallback" in CONTRACTS_FLAT


def test_no_member_is_added_merely_because_a_route_exists() -> None:
    assert "No member is added because a route exists" in CONTRACTS_FLAT
    assert "A route is not evidence that an area owns a disclosed reference class" in (
        CONTRACTS_FLAT
    )


# ------------------------------------------------------ association and validation


def test_the_association_is_a_field_inside_the_reference() -> None:
    span = section(CONTRACTS_TEXT, "### 4.3.2 Owning-area navigation", "### 4.4")
    flat = flatten(span)
    assert "carried INSIDE the reference" in flat
    assert "The reference it describes is the object it is a field of" in flat


@pytest.mark.parametrize(
    "refused",
    [
        "Association by array position",
        "by display text",
        "by an identifier prefix or naming convention",
        "by a runtime filesystem, module or route search",
    ],
)
def test_the_forbidden_associations_are_each_refused_by_name(refused: str) -> None:
    span = flatten(section(CONTRACTS_TEXT, "### 4.3.2 Owning-area navigation", "### 4.4"))
    assert refused in span, f"{refused!r} is not refused by name"


def test_the_ref_type_declares_the_field_optional_and_closed() -> None:
    span = section(CONTRACTS_TEXT, "Ref             object", "RefList         object")
    assert "owning_area: <closed OwningArea> or ABSENT" in span
    flat = flatten(span)
    assert "OPTIONAL DESCRIPTIVE metadata" in flat
    assert "NEVER an access grant" in flat
    assert "NEVER changes what the reference means or how it resolves" in flat


@pytest.mark.parametrize(
    ("label", "phrase"),
    [
        ("MULTIPLICITY", "at most ONE per Ref"),
        ("MULTIPLICITY", "never a list, never a first-of, never a nearest match"),
        ("DUPLICATES", "They stay two references, they are not collapsed"),
        ("CONTRADICTION", "REFUSED AT ADMISSION"),
        ("VALIDATION", "never mapped to a nearest member"),
        ("KIND UNCHANGED", "may NEVER change a reference's ref_kind to obtain a link"),
    ],
)
def test_the_association_rules_are_each_stated(label: str, phrase: str) -> None:
    span = flatten(section(CONTRACTS_TEXT, "MULTIPLICITY    at most ONE per Ref", "```"))
    assert label in span, f"{label} is not stated"
    assert phrase in span, f"{label} does not state {phrase!r}"


def test_a_contradictory_duplicate_pair_is_refused_rather_than_resolved() -> None:
    span = flatten(section(CONTRACTS_TEXT, "CONTRADICTION", "VALIDATION"))
    assert "sharing a ref_id AND a ref_kind" in span
    assert "DIFFERENT owning_area values are REFUSED AT ADMISSION" in span
    assert "admitting it lets a renderer choose" in span


def test_two_references_in_one_item_keep_their_own_areas() -> None:
    assert "Two references in one item keep their own areas" in ADR_FLAT
    assert (
        "its references may declare DIFFERENT `owning_area` values (§4.3.2) and each keeps its own"
        in CONTRACTS_FLAT
    )


# ------------------------------------------------------------- the R10 relationship


def test_r10_is_amended_rather_than_left_prohibiting_the_new_attribute() -> None:
    """A field alone is insufficient while R10 still forbids using it."""
    assert "R10 is narrowly amended to permit a SECOND closed navigation attribute" in ADR_FLAT
    assert "a new field alone would be insufficient" in ADR_FLAT
    assert "This rule governs TARGET navigation" in CONTRACTS_FLAT
    assert "amended by ADR-0031" in CONTRACTS_FLAT


def test_the_existing_ref_kind_allowlist_is_left_intact() -> None:
    span = flatten(
        section(
            CONTRACTS_TEXT,
            "**Navigation is an allowlisted internal ROUTE TEMPLATE",
            "### 4.3.2",
        )
    )
    assert "**closed allowlist keyed by `RefKind`**" in span
    assert "an unknown or unmapped kind yields **no link**" in span
    assert "an unmapped `RefKind` still yields **no target link**" in span


def test_neither_attribute_is_a_fallback_for_the_other() -> None:
    for text in (ADR_FLAT, CONTRACTS_FLAT):
        assert "Neither is a fallback for the other" in text or (
            "neither is a fallback for the other" in text
        )
    assert "an absent `owning_area` still yields **no area link**" in CONTRACTS_FLAT


def test_the_two_affordances_carry_different_labels_and_are_never_merged() -> None:
    span = flatten(section(CONTRACTS_TEXT, "**The label distinguishes", "**Reference status"))
    assert "Owning-area navigation names the AREA and says so" in span
    assert (
        "may never be phrased as resolving, opening, retrieving, viewing or showing the reference"
        in span
    )
    assert "distinct controls and are never merged" in span


def test_an_area_control_is_not_labelled_as_evidence_retrieval() -> None:
    ui = flatten(UI_SPEC.read_text(encoding="utf-8"))
    assert 'may never be labelled "view evidence"' in ui
    assert "never a claim that the reference was resolved, opened or retrieved" in ui


# --------------------------------------------------- availability and presentation


@pytest.mark.parametrize("state", ["DECLARED", "ABSENT", "WITHHELD", "INVALID"])
def test_each_availability_state_is_stated_in_both_documents(state: str) -> None:
    adr = flatten(section(ADR_TEXT, "### A4 — availability and honest presentation", "### A5"))
    contracts = flatten(
        section(CONTRACTS_TEXT, "**Four availability states", "**No owning area is ever invented")
    )
    assert state in adr, f"{state} is not stated in ADR-0031 A4"
    assert state in contracts, f"{state} is not stated in section 4.3.2"


def test_an_absent_area_is_not_a_claim_that_none_exists() -> None:
    for text in (ADR_FLAT, CONTRACTS_FLAT):
        assert "NOT** a claim that no area owns" in text or "NOT a claim that no area owns" in text
    assert 'no renderer may report "no owning area exists"' in CONTRACTS_FLAT


def test_no_owning_area_is_invented_to_satisfy_a_link_assertion() -> None:
    for text in (ADR_FLAT, CONTRACTS_FLAT):
        assert "No owning area is ever invented to satisfy a link assertion" in text


def test_an_unbuilt_destination_stays_visibly_not_yet_implemented() -> None:
    for text in (ADR_FLAT, CONTRACTS_FLAT):
        assert "stays visibly not yet implemented" in text
        assert "asserts nothing about whether the producing subsystem exists" in text


def test_reference_status_and_area_navigability_are_separate_axes() -> None:
    span = flatten(section(CONTRACTS_TEXT, "**Reference status and area", "**Evidence-kind"))
    assert "separate axes, displayed separately" in span
    assert "An `UNRESOLVABLE_V1` reference may carry a navigable area" in span
    assert "Neither is evidence about the other" in span


def test_the_evidence_kind_filter_is_unchanged_and_admits_a_zero_result_category() -> None:
    span = flatten(section(CONTRACTS_TEXT, "**Evidence-kind filters are unchanged", "**Navigation"))
    assert "declared** `ref_kind` vocabulary of the host field" in span
    assert 'selecting zero rows is a **true "none of these"**' in span
    assert "is not folded into that filter and does not become a kind" in span


def test_navigation_metadata_is_evidence_about_nothing_else() -> None:
    span = flatten(
        section(CONTRACTS_TEXT, "**Navigation metadata is evidence about", "**The access")
    )
    for claim in ("completeness", "freshness", "materiality", "severity", "authorization"):
        assert claim in span, f"{claim} is not excluded"


# -------------------------------------------------------------- the access boundary


@pytest.mark.parametrize(
    "refusal",
    [
        "an area link does NOT authorize retrieval of the referenced artefact",
        "an area link does NOT reveal a withheld identifier, key, locator or vendor value",
        "an area link does NOT bypass the destination's own scope and classification checks",
        "an area link does NOT convert AUTHORIZED_READ into a read the caller may perform",
        "a caller denied the artefact may still see the area link, and is still denied",
    ],
)
def test_the_access_boundary_is_stated_as_refusals_in_both_documents(refusal: str) -> None:
    assert refusal in ADR_FLAT, "ADR-0031 A5 omits a refusal"
    assert refusal in CONTRACTS_FLAT, "section 4.3.2 omits a refusal"


def test_the_adr_preserves_the_adr_0030_rules_it_touches() -> None:
    span = flatten(
        section(ADR_TEXT, "**Every ADR-0030 rule this touches is preserved", "**The general")
    )
    for preserved in (
        "R8 identity comparison",
        "the tombstone rule",
        "five §4.3.1 unavailable outcomes",
        "`REFERENT_NOT_FOUND`'s two landing places",
        "the permitted resolution sets",
        "the R7 cardinality quantities",
    ):
        assert preserved in span, f"{preserved} is not named as preserved"


def test_no_evidence_endpoint_is_manufactured_and_evidence_is_not_mapped_to_audit() -> None:
    assert "No evidence endpoint is manufactured" in ADR_FLAT
    assert "no kind is remapped to `audit_event`" in ADR_FLAT
    assert "`evidence` is **not** given a destination by mapping it to the Audit Trail" in ADR_FLAT


def test_the_two_general_limitations_are_named_as_unresolved_in_both_documents() -> None:
    for text in (ADR_FLAT, CONTRACTS_FLAT):
        assert "no general destination at which an evidence artefact can be retrieved" in text
        assert "a reference-carried scope is not expressible" in text
        assert "Working area links are not a repair of either" in text


def test_the_endpoint_catalogue_still_lists_no_evidence_endpoint() -> None:
    """The limitation is checked against the document, not merely asserted in prose."""
    catalogue = section(CONTRACTS_TEXT, "## 5. Endpoint catalog and versioning", "### 5.1")
    assert "GET  /api/v1/audit/events" in catalogue, "the catalogue parser sees nothing"
    assert "/evidence" not in catalogue


def test_the_new_field_is_not_a_state_field_and_r9_still_holds() -> None:
    """The one field added is descriptive, and it does not smuggle availability back in.

    ADR-0030 R9 keeps a `Ref` free of `availability` and `reason`, and the enumeration in the
    ADR-0030 suite stays exact. This asserts the same property from this side, so the strength
    is proven under the amended shape rather than merely moved to another file.
    """
    span = section(CONTRACTS_TEXT, "Ref             object", "RefList         object")
    shape = span[span.index("{") : span.index("}") + 1]
    assert "owning_area" in shape
    assert "availability" not in shape
    assert "reason" not in shape
    assert "A `Ref` carries no `availability` and no `reason`" in CONTRACTS_FLAT
    assert "indistinguishable from **ABSENT**, because a `Ref` carries no availability" in (
        CONTRACTS_FLAT
    )


def test_the_ref_type_still_has_no_scope_field() -> None:
    span = section(CONTRACTS_TEXT, "Ref             object", "RefList         object")
    assert "scope" not in span, "a reference-carried scope would close a limitation A5 leaves open"


# ------------------------------------------------------------ compatibility and versioning


def test_the_compatibility_assessment_is_a_contract_assessment() -> None:
    assert "This is assessed as a contract change, not as fixture byte equality" in ADR_FLAT
    assert "Shared types are shared blast radius" in ADR_FLAT


def test_the_old_no_bump_exception_is_not_inherited() -> None:
    span = flatten(
        section(ADR_TEXT, "**The four §6.1 deployment constraints are NOT", "**The pending")
    )
    assert "are NOT assumed, and the old no-bump exception is not inherited" in span
    assert "re-check all four against the tree it lands in" in span
    assert "bump rather than proceed if any has changed" in span


def test_the_pending_v2_change_is_accounted_for_and_not_treated_as_authority() -> None:
    span = flatten(section(ADR_TEXT, "**The pending all-nineteen-model", "---"))
    assert "While it is open it carries no authority" in span
    assert "no version value is predicted here" in span
    for branch in ("INSIDE", "AFTER", "REFUSED"):
        assert branch in span, f"the integration rule omits the {branch} branch"


def test_the_adr_asserts_no_schema_version_value() -> None:
    """A version number in this document would be exactly the decision A6 refuses to make."""
    assert re.search(r"cockpit\.[a-z_]+\.v\d", ADR_TEXT) is None


# ------------------------------------------------- the product surface, and its authority


@pytest.mark.parametrize(
    "document",
    [CONTRACTS, V1_SPEC, UI_SPEC, MATRIX],
)
def test_every_amended_specification_carries_the_same_conditional_authority(
    document: Path,
) -> None:
    flat = flatten(document.read_text(encoding="utf-8"))
    assert "ADR-0031" in flat, f"{document.name} does not name ADR-0031"
    assert (
        "ADR-0031 is **PROPOSED and carries no authority while the pull request introducing it is "
        "open**" in flat
    ), f"{document.name} does not carry the conditional authority statement"


def test_the_matrix_area_28_criterion_records_the_restored_behaviour() -> None:
    rows = [
        line
        for line in MATRIX.read_text(encoding="utf-8").splitlines()
        if line.startswith("| 28 | Executive Attention Required | **full**")
    ]
    assert len(rows) == 1, "area 28 appears exactly once in matrix B"
    row = rows[0]
    assert "never through a relabelled kind and never defaulted to the Audit Trail" in row
    assert "never claims the evidence was resolved or retrieved" in row
    assert "renders visibly not yet implemented" in row


def test_the_v1_specification_area_28_boundary_records_the_same_rule() -> None:
    span = flatten(section(V1_SPEC.read_text(encoding="utf-8"), "## Area 28 —", "## Area 29 —"))
    assert "never by relabelling the reference's kind" in span
    assert "never defaulted to the Audit Trail" in span


def test_the_ui_specification_keeps_the_two_affordances_apart() -> None:
    span = flatten(
        section(UI_SPEC.read_text(encoding="utf-8"), "**Two navigation affordances", "## 4.")
    )
    assert "they are never merged" in span
    assert "A reference is never relabelled with a different kind to obtain a link" in span


# ------------------------------------------------------------ the pending gap, guarded


def test_the_runtime_carries_no_owning_area_and_the_gap_is_pending() -> None:
    """ADR-0031 is a proposal. Implementing it here would be implementing an unaccepted rule.

    This is the guard that keeps the two apart. It asserts the field the proposal introduces is
    **still absent** from the application, so a reader can tell that the proposal was documented
    and not silently enacted. It is expected to be inverted by the bounded implementation cycle
    that follows acceptance.
    """
    assert "owning_area" not in VALUES.read_text(encoding="utf-8")


def test_no_application_module_declares_an_owning_area_route_table() -> None:
    offenders = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in COCKPIT_APP.rglob("*.ts*")
        if "owning_area" in path.read_text(encoding="utf-8")
        or "OwningArea" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"the proposal is implemented in {offenders}"


def test_the_follow_up_names_the_regression_it_must_replace() -> None:
    span = flatten(section(ADR_TEXT, "## 5. The bounded implementation follow-up", "\n## 6."))
    assert "replace the known-narrowing regression" in span
    assert "positive AND negative behavioural tests" in span
    assert "complete a fresh independent review before any merge" in span
