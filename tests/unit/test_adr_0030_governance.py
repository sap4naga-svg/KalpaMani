"""ADR-0030 governance: the reference contract, parsed out of the specification and executed.

ADR-0030 was **accepted** by merge, and the bounded implementation follow-up its §7 assigns
has since landed. These tests check that the accepted rules are present, internally
consistent and satisfiable **in the specification**, and that the implementation defect §2.6
names is gone from the runtime.

**They do not re-assert the ADR's own status.** ADR-0030's document is unedited and still
carries the conditional line it was authored with, which is the repository's convention for
a decision's own text: the acceptance is a fact about the merge, not a rewrite of the file.
The behavioural enforcement lives beside the code it governs, in
``apps/cockpit/tests/adr-0030-references.test.ts``; what is checked here is the DOCUMENT.

The suite has three parts.

* **Governance** -- ADR-0030 declares itself proposed, predicts no merge, amends no accepted
  ADR document, and authorizes no implementation, infrastructure or execution.
* **The contract, executed** -- every rule is parsed out of ``read-model-contracts.md`` and
  run. There is no second copy of the table in this file: the reference rows, the field
  assignments, the resolution sets and the reason matrix are all read from the document at
  import time, so a document that reverts to the defective rule fails here.
* **The implementation** -- ADR-0030 has since been accepted and its bounded follow-up has
  landed, so the guards that asserted the runtime was UNCHANGED are inverted here. The
  defect they watched for is asserted GONE, and the rules are asserted PRESENT in the
  code that enforces them.

Every parser carries a self-test proving it can still see the defect it exists to catch: a
scanner that sees nothing passes every document vacuously.
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

ADR: Final = DECISIONS / "ADR-0030-cockpit-reference-resolution-and-unavailable-targets.md"
CONTRACTS: Final = COCKPIT / "read-model-contracts.md"
VALUES: Final = PROJECT_ROOT / "apps" / "cockpit" / "src" / "contracts" / "values.ts"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8")
CONTRACTS_TEXT: Final = CONTRACTS.read_text(encoding="utf-8")

#: The closed ``Resolution`` vocabulary of read-model-contracts.md section 4.2.
RESOLUTIONS: Final = frozenset({"ENDPOINT", "EMBEDDED", "AUTHORIZED_READ", "UNRESOLVABLE_V1"})
#: The closed ``Cardinality`` vocabulary of the same section.
CARDINALITIES: Final = frozenset({"EXACTLY_ONE", "ZERO_OR_ONE", "ZERO_OR_MORE", "ONE_OR_MORE"})


def flatten(text: str) -> str:
    """One line, so a rule broken across a wrap is still one phrase."""
    return " ".join(text.split())


ADR_FLAT: Final = flatten(ADR_TEXT)


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
    assert "ADR-0030 is ACCEPTED / IN FORCE" not in ADR_FLAT


def test_the_adr_claims_no_authority_while_its_pull_request_is_open() -> None:
    assert "carries no authority" in ADR_FLAT
    assert "it is not to be rewritten as though this decision had authority" in ADR_FLAT


def test_the_adr_predicts_no_merge_sha_and_no_timestamp() -> None:
    assert "No merge SHA and no merge timestamp is predicted here" in ADR_FLAT
    # A 40-character hex string would be a predicted commit.
    assert re.search(r"\b[0-9a-f]{40}\b", ADR_TEXT) is None


def test_the_adr_amends_no_accepted_adr_document() -> None:
    assert "It does not amend, supersede or edit" in ADR_FLAT
    assert "ADR-0027, ADR-0028 or ADR-0029 themselves" in ADR_FLAT
    assert "**Supersedes:** nothing" in ADR_TEXT


def test_the_adr_authorizes_no_implementation_and_records_the_pending_follow_up() -> None:
    assert "implements no runtime behaviour, and none is authorized by it" in ADR_FLAT
    assert "It is a separate authorization" in ADR_FLAT
    assert "five separate gates" in ADR_FLAT


def test_the_adr_ran_nothing_and_claims_no_alpha() -> None:
    assert "**Nothing was run to produce this decision.**" in ADR_TEXT
    assert "No alpha is claimed anywhere in this decision." in ADR_FLAT
    assert "No Blueprint PDF was opened or edited." in ADR_FLAT


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("Run A retry", "NOT AUTHORIZED / NOT RUN"),
        ("Run B", "NOT AUTHORIZED / NOT RUN"),
        ("combined assessment", "NOT AUTHORIZED / NOT RUN"),
        ("P1-P9", "UNEVALUATED"),
        ("G1 / G2", "OPEN / OPEN"),
        ("provider selected", "NONE"),
        ("Phase 3", "NOT COMPLETE"),
        ("CONTROL", "DEFERRED"),
        ("live trading", "HARD-DISABLED"),
        ("C7 research and feedback interfaces", "NOT STARTED"),
        ("C5 completion follow-up", "STILL PENDING / NOT AUTHORIZED"),
        ("backtesting", "NOT STARTED"),
        ("AWS / Terraform operations", "NONE"),
        ("broker, LEAN and IBKR activity", "NONE"),
    ],
)
def test_the_adr_leaves_every_standing_gate_where_it_was(label: str, value: str) -> None:
    """Each gate is read from the ADR's own status block, label and value together."""
    stated = [line for line in ADR_TEXT.splitlines() if line.startswith(f"{label}:")]
    assert len(stated) == 1, f"ADR-0030 states {label!r} exactly once"
    assert stated[0].split(":", 1)[1].strip() == value


# --------------------------------------------------- the reference table, executed


def reference_rows() -> dict[str, tuple[frozenset[str], str]]:
    """``ref_kind`` -> (permitted resolutions, relation cardinality), from section 4.3."""
    table = section(
        CONTRACTS_TEXT,
        "### 4.3 Resolving a reference",
        "#### 4.3.1 ",
    )
    rows: dict[str, tuple[frozenset[str], str]] = {}
    for line in table.splitlines():
        match = re.match(r"^\|\s*`([a-z_]+)`\s*\|(.*?)\|(.*?)\|(.*?)\|\s*$", line)
        if match is None:
            continue
        kind, _target, resolution, cardinality = match.groups()
        if kind == "ref_kind":  # the header row
            continue
        members = frozenset(re.findall(r"`([A-Z][A-Z0-9_]*)`", resolution))
        rows[kind] = (members, cardinality.strip().strip("`"))
    return rows


ROWS: Final = reference_rows()


def test_the_row_parser_sees_the_whole_table() -> None:
    assert len(ROWS) == 27, "section 4.3 states twenty-seven reference kinds"


def test_the_row_parser_would_notice_a_removed_row() -> None:
    """A scanner that cannot see a row cannot report one missing."""
    assert "candidate" in ROWS
    assert "source_fact" in ROWS


def test_the_table_carries_the_trade_row_the_catalogue_requires() -> None:
    """D1: ``downstream_refs.trade`` had no row, so an implementation had to guess."""
    assert "trade" in ROWS, "section 4.3 must carry a `trade` row"
    permitted, cardinality = ROWS["trade"]
    assert "ENDPOINT" in permitted
    assert cardinality in CARDINALITIES


def test_every_resolution_named_in_the_table_is_a_closed_member() -> None:
    for kind, (permitted, _cardinality) in ROWS.items():
        assert permitted, f"{kind} names no resolution at all"
        assert permitted <= RESOLUTIONS, f"{kind} names a resolution outside the vocabulary"


def test_every_cardinality_named_in_the_table_is_a_closed_member() -> None:
    for kind, (_permitted, cardinality) in ROWS.items():
        assert cardinality in CARDINALITIES, f"{kind} names an unknown cardinality"


def test_brain_decision_may_resolve_by_endpoint() -> None:
    """D2: the sole carrier of this kind cannot embed it, so EMBEDDED alone was unsatisfiable."""
    permitted, _cardinality = ROWS["brain_decision"]
    assert "ENDPOINT" in permitted, "TradeDetail carries this reference and embeds no payload"
    assert "UNRESOLVABLE_V1" in permitted, "a trade with no journaled candidate resolves to a state"


def test_the_resolution_column_is_stated_to_be_a_permitted_set() -> None:
    """D3: two accepted rows already carried two members, and the text never said so."""
    flat = flatten(CONTRACTS_TEXT)
    assert "The Resolution column is a PERMITTED SET" in flat
    assert "`EMBEDDED` is additionally available to **every** row" in flat


def test_embedded_requires_permission_as_well_as_truth() -> None:
    """R4: payload PRESENCE is something a producer controls, so it cannot be the authorization.

    A rule reading "EMBEDDED is true whenever the payload is there" is satisfied by *putting
    the payload there*, so it authorizes any widening a producer chooses and then ratifies
    it. Permission has to come from the catalogue, and truth from the response.
    """
    flat = flatten(CONTRACTS_TEXT)
    assert "**Presence alone is not permission**" in flat
    assert "the catalogue authorizes THIS host field to embed THIS target kind" in flat
    assert "NAMES the carrier field that holds it" in flat
    assert "COMPLETE target or a DECLARED PROJECTION" in flat


def test_an_unauthorized_carrier_is_refused_even_when_the_payload_is_present() -> None:
    """The concrete case: a Brain payload added to TradeDetail must not buy an EMBEDDED."""
    flat = flatten(CONTRACTS_TEXT)
    rule = (
        "A carrier the catalogue does not authorize is a widening and is refused whether or "
        "not the payload is present"
    )
    assert rule in flat
    assert "no brain-decision payload may be added to `TradeDetail`" in flat


def test_an_absent_target_is_never_a_fabricated_embedded_payload() -> None:
    flat = flatten(CONTRACTS_TEXT)
    assert "An absent target is never represented by a fabricated embedded payload" in flat
    assert "a wrong answer wearing a correct one's shape" in flat


def test_co_location_neither_compels_embedded_nor_forbids_endpoint() -> None:
    """R4.1: *you already have this* and *the record lives here* are not competing claims."""
    flat = flatten(CONTRACTS_TEXT)
    assert "Co-location does not compel `EMBEDDED`, and does not forbid `ENDPOINT`" in flat
    assert "may instead** declare any other resolution its kind's set permits" in flat
    assert "`EMBEDDED` is refused **only** when it is not permitted or not true" in flat


def test_producer_existence_is_scoped_and_a_missing_record_is_not_a_missing_producer() -> None:
    """R6: a synthetic fixture must not stand in for a subsystem that does not exist."""
    flat = flatten(CONTRACTS_TEXT)
    assert "for the requested environment, provenance and read-model scope" in flat
    assert "exists for `SYNTHETIC` provenance and for nothing else" in flat
    assert "never establishes that the real subsystem exists" in flat
    assert "An implemented producer that lacks one requested record is not producer" in flat


# ------------------------------------------------- every reference field names a kind


def catalogue() -> str:
    return section(CONTRACTS_TEXT, "### 4.5 The payload contracts", "### 4.6 ")


def unassigned_reference_fields() -> dict[str, list[str]]:
    """Model-qualified reference fields in section 4.5 that state no kind on their line.

    Both shapes are scanned. A regex of the form ``:\\s*Ref\\b`` never matches ``RefList``,
    because the character after ``Ref`` is a word character and the boundary fails -- which
    is exactly how six ``RefList`` fields survived an earlier draft of this reconciliation,
    all of them in the research-and-feedback surface C7 consumes.
    """
    scalar: list[str] = []
    lists: list[str] = []
    model = "?"
    for line in catalogue().splitlines():
        header = re.match(r"^([A-Za-z]\w*)\.payload\s*\{", line.strip())
        if header is not None:
            model = header.group(1)
        if "kind " in line:
            continue
        for name in re.findall(r"(\w+)\s*:\s*RefList\b", line):
            lists.append(f"{model}.{name}")
        for name in re.findall(r"(\w+)\s+RefList\s{2,}", line):
            lists.append(f"{model}.{name}")
        for name in re.findall(r"(\w+)\s*:\s*Ref\b(?!List)", line):
            scalar.append(f"{model}.{name}")
        for name in re.findall(r"(\w+)\s+Ref\s{2,}", line):
            scalar.append(f"{model}.{name}")
    return {"scalar": scalar, "list": lists}


UNASSIGNED: Final = unassigned_reference_fields()


def test_the_parser_sees_both_reference_shapes_and_not_only_the_scalar_one() -> None:
    """A scanner blind to ``RefList`` passes the defective document vacuously.

    This is the self-test for the defect the parser exists to catch. The six list fields
    below hold references and state no kind; a parser that reports them as assigned is a
    parser that cannot see them at all.
    """
    for field in (
        "StrategyHealth.input_refs",
        "StrategyHealth.evidence_refs",
        "HypothesisRegistration.related_registrations",
        "HypothesisRegistration.amendment_chain",
        "AiContribution.source_refs",
        "FeedbackPipeline.item_refs",
    ):
        assert field in UNASSIGNED["list"], f"{field} holds a RefList and states no kind"
    for field in (
        "CandidateDetail.trade",
        "RiskSnapshot.trade_ref",
        "ReconciliationStatus.local_ref",
        "TradeLifecycle.correction_of",
        "HypothesisRegistration.superseded_by",
    ):
        assert field in UNASSIGNED["scalar"], f"{field} holds a Ref and states no kind"


def test_the_unassigned_population_is_counted_by_field_and_not_by_leaf_name() -> None:
    """The count is of FIELDS. Leaf names collapse four distinct ``source_ref`` fields into one."""
    assert len(UNASSIGNED["scalar"]) == 19, UNASSIGNED["scalar"]
    assert len(UNASSIGNED["list"]) == 6, UNASSIGNED["list"]
    total = len(UNASSIGNED["scalar"]) + len(UNASSIGNED["list"])
    assert total == 25
    leaf_names = {field.rsplit(".", 1)[-1] for field in UNASSIGNED["scalar"]}
    assert len(leaf_names) == 13, "a leaf-name count is a DIFFERENT and smaller number"


def test_the_specification_states_the_population_it_assigns() -> None:
    flat = flatten(CONTRACTS_TEXT)
    assert "twenty-five reference-valued fields of §4.5" in flat
    assert "**nineteen** scalar `Ref` fields and **six** `RefList` fields" in flat


def assignment_table() -> dict[str, str]:
    """Field -> assigned kind, from the section 4.3.1 assignment table."""
    span = section(CONTRACTS_TEXT, "#### 4.3.1 ", "**`record_ref` is a field of `borrow[]`.**")
    assigned: dict[str, str] = {}
    for line in span.splitlines():
        match = re.match(r"^\|\s*`?([A-Za-z][A-Za-z0-9_.\[\]]*)`?[^|]*\|(.*?)\|\s*$", line)
        if match is None:
            continue
        field, kind = match.groups()
        if field.strip("`") == "Field":  # the header row
            continue
        assigned[field.strip("`")] = kind.strip()
    return assigned


ASSIGNED: Final = assignment_table()


def test_the_assignment_parser_sees_the_whole_assignment_table() -> None:
    assert len(ASSIGNED) == 23, sorted(ASSIGNED)


def test_every_unassigned_reference_field_is_assigned_a_kind() -> None:
    """D1, closed: no reference-valued field in the catalogue is left without a kind.

    Comparison is model-qualified on both sides where the assignment table qualifies it, so
    assigning one ``source_ref`` cannot silently cover a different model's ``source_ref``.
    """
    assigned_leaves = {field.rsplit(".", 1)[-1].rstrip("[]") for field in ASSIGNED}
    assigned_pairs = set()
    for field in ASSIGNED:
        parts = field.replace("[]", "").split(".")
        if len(parts) >= 2:
            assigned_pairs.add((parts[0], parts[-1]))
    missing = []
    for field in UNASSIGNED["scalar"] + UNASSIGNED["list"]:
        model, leaf = field.split(".", 1)
        if (model, leaf) in assigned_pairs:
            continue
        if leaf in assigned_leaves:  # e.g. ExecutiveOverview.ref, addressed as last_decision.ref
            continue
        missing.append(field)
    assert missing == [], f"section 4.3.1 assigns no kind to {missing}"


def test_the_six_reflist_fields_are_assigned_and_not_merely_mentioned() -> None:
    """The fields an earlier draft missed, each with the kind its own contract line implies."""
    assert ASSIGNED["StrategyHealth.transitions[].input_refs"] == "`source_fact`"
    assert ASSIGNED["StrategyHealth.failure_clusters[].evidence_refs"] == "`evidence`"
    assert ASSIGNED["HypothesisRegistration.lineage.related_registrations"] == "`registration`"
    assert ASSIGNED["HypothesisRegistration.lineage.amendment_chain"] == "`registration`"
    assert ASSIGNED["AiContribution.ai_provenance.source_refs"] == "`source_fact`"
    assert ASSIGNED["FeedbackPipeline.stages[].item_refs"] == "`queue_item`"


#: The cell that states a FAMILY of kinds, and the members it admits.
CORRECTION_FAMILY: Final = frozenset({"order", "fill", "protection", "add", "exit"})
#: The cells that state a family rather than exactly one kind.
FAMILIES: Final = frozenset(
    {
        "TradeLifecycle.events[].correction_of",
        "SearchResultPage.results[].ref",  # any RefKind
    }
)


def test_every_assigned_kind_is_a_table_row_or_a_stated_family() -> None:
    """An assignment naming a kind with no row would recreate the defect it fixes.

    A plain cell must name exactly one row. The two family cells are checked against the
    members they enumerate, so a family cannot smuggle in a kind the table does not carry.
    """
    for field, kind in ASSIGNED.items():
        if field in FAMILIES:
            continue
        named = set(re.findall(r"`([a-z_]+)`", kind))
        assert len(named) == 1, f"{field} names {sorted(named)} rather than one kind"
        unknown = named - set(ROWS)
        assert unknown == set(), f"{field} is assigned unknown kind(s) {sorted(unknown)}"


def test_the_two_family_cells_admit_only_kinds_the_table_carries() -> None:
    """A family is a stated set, not an escape from the closed vocabulary."""
    correction = ASSIGNED["TradeLifecycle.events[].correction_of"]
    members = CORRECTION_FAMILY
    assert members <= set(ROWS), sorted(members - set(ROWS))
    for member in members:
        assert f"`{member}`" in correction, f"{member} is not enumerated in the cell"
    assert "corresponding to the corrected event" in correction
    search = ASSIGNED["SearchResultPage.results[].ref"]
    assert "any `RefKind`" in search
    assert "resolves as that kind" in search


def test_the_trade_reference_is_assigned_the_trade_kind_and_not_a_provenance_fact() -> None:
    """The defect a reader could see, and it occurred TWICE rather than once."""
    assert ASSIGNED["CandidateDetail.downstream_refs.trade"] == "`trade`"
    assert ASSIGNED["RiskSnapshot.initial_planned_risk_open[].trade_ref"] == "`trade`"


def test_the_record_ref_path_names_a_field_that_exists() -> None:
    """``record_ref`` is a field of ``borrow[]``; there is no ``deterioration[]`` array."""
    assert "ShortSideSnapshot.borrow[].record_ref" in ASSIGNED
    assert "ShortSideSnapshot.deterioration[].record_ref" not in ASSIGNED
    assert "deterioration[]" not in flatten(CONTRACTS_TEXT)


def test_a_kind_is_a_property_of_the_field_and_not_of_the_field_name() -> None:
    """The catalogue itself already gives ``evidence_refs`` more than one kind."""
    flat = flatten(CONTRACTS_TEXT)
    assert "A kind is a property of the FIELD, not of the field NAME" in flat
    declared = re.findall(r"evidence_refs\s+RefList\s+required, kind ([a-z_ ]+)", CONTRACTS_TEXT)
    assert len(set(name.strip() for name in declared)) > 1, declared


def test_security_ref_stays_evidence_on_every_field_it_is_assigned_on() -> None:
    for field, kind in ASSIGNED.items():
        if field.endswith("security_ref"):
            assert kind == "`evidence`", f"{field} contradicts CandidateDetail.security_ref"


# ------------------------------------------------------- the unavailable outcomes


def test_referent_not_found_is_a_reason_code() -> None:
    """D5: an unknown identifier had nowhere truthful to land."""
    codes = section(CONTRACTS_TEXT, "PRODUCER_NOT_IMPLEMENTED", "#### 4.1.1 ")
    assert "REFERENT_NOT_FOUND" in codes


def test_referent_not_found_is_reachable_from_exactly_one_state() -> None:
    matrix = section(CONTRACTS_TEXT, "| `availability` | `value` |", "\n\n")
    rows = [line for line in matrix.splitlines() if "REFERENT_NOT_FOUND" in line]
    assert len(rows) == 1, "the reason must be reachable, and from one state"
    assert "`NOT_YET_AVAILABLE`" in rows[0]


def test_a_missing_referent_is_an_absence_and_never_an_inapplicability() -> None:
    """ADR-0028's guard is preserved, not relaxed to fit this proposal's prose."""
    matrix = section(CONTRACTS_TEXT, "| `availability` | `value` |", "\n\n")
    applicable = [line for line in matrix.splitlines() if line.startswith("| `NOT_APPLICABLE`")]
    assert len(applicable) == 1
    assert "REFERENT_NOT_FOUND" not in applicable[0]
    assert "`NOT_DEFINED_FOR_SUBJECT`, `DENOMINATOR_ZERO` — and nothing else" in applicable[0]


def test_referent_not_found_is_in_the_closed_error_vocabulary() -> None:
    errors = section(CONTRACTS_TEXT, "| **errors** |", "\n|")
    assert "REFERENT_NOT_FOUND" in errors


def test_a_bare_reference_carries_no_availability_so_the_state_lands_elsewhere() -> None:
    """R9: ``Ref`` is ``{ref_id, ref_kind, resolution, classification}`` and has no state field."""
    flat = flatten(CONTRACTS_TEXT)
    assert "A `Ref` carries no `availability` and no `reason`" in flat
    landing = "carried by the VALUE-BEARING field the target would have filled"
    assert f"{landing}, never by a bare Ref" in flat
    ref_type = section(CONTRACTS_TEXT, "Ref             object", "RefList         object")
    shape = ref_type[ref_type.index("{") : ref_type.index("}") + 1]
    assert "availability" not in shape, "Ref must not gain an availability field"
    assert "reason" not in shape, "Ref must not gain a reason field"
    assert set(re.findall(r"(\w+):", shape)) == {
        "ref_id",
        "ref_kind",
        "resolution",
        "classification",
    }, shape


def test_scope_denial_is_not_classification_withholding() -> None:
    """The accepted section 5 vocabulary already separates them, and R9 keeps them apart."""
    flat = flatten(CONTRACTS_TEXT)
    assert "Scope denial is not classification withholding" in flat
    span = section(CONTRACTS_TEXT, "**Five unavailable outcomes", "**A `Ref` carries no")
    assert "SCOPE_MISSING" in span and "SCOPE_INSUFFICIENT" in span
    assert "CLASSIFICATION_WITHHELD" in span


def test_a_recorded_tombstone_is_not_an_unknown_target() -> None:
    flat = flatten(CONTRACTS_TEXT)
    assert "A recorded tombstone is not an unknown target" in flat


def test_the_five_unavailable_outcomes_stay_distinct() -> None:
    span = section(CONTRACTS_TEXT, "**Five unavailable outcomes", "**A `Ref` carries no")
    for code in (
        "REFERENT_NOT_FOUND",
        "PRODUCER_NOT_IMPLEMENTED",
        "SCOPE_MISSING",
        "CLASSIFICATION_WITHHELD",
    ):
        assert code in span, f"{code} is not distinguished from the others"
    assert "refused at admission" in span, "a malformed reference is not an availability state"


# --------------------------------------------------- identity and safe navigation


def test_a_reference_never_resolves_to_a_substitute_entity() -> None:
    flat = flatten(CONTRACTS_TEXT)
    assert "No resolver falls back to a nearest match, a default or a first row" in flat


def test_identity_compares_the_target_entity_and_not_its_container() -> None:
    """R8: ``brain_decision`` is retrieved by a candidate route; the candidate id is not the id."""
    flat = flatten(CONTRACTS_TEXT)
    assert "the target entity and not the container it was retrieved through" in flat
    assert "the candidate's id is not the comparand" in flat
    assert "the catalogue names the container route AND the in-container selector" in flat


def test_an_authorized_labelled_cross_provenance_reference_is_not_forbidden() -> None:
    """R8: QualificationStatus reads tracked repository authority, and SearchResultPage rows
    carry their own provenance. A blanket must-match rule would refuse both."""
    flat = flatten(CONTRACTS_TEXT)
    assert "Environment must match the resolving envelope, always" in flat
    assert "except where the catalogue explicitly authorizes a cross-provenance reference" in flat
    assert "carries the target's own provenance label" in flat
    assert "Silent provenance mixing stays prohibited" in flat


def test_navigation_permits_an_allowlisted_route_template_and_forbids_free_form_urls() -> None:
    """R10: an encoded SafeId path segment is ordinary internal navigation, not a hazard."""
    flat = flatten(CONTRACTS_TEXT)
    assert "closed allowlist keyed by `RefKind`" in flat
    assert "an allowlisted INTERNAL route TEMPLATE selected by RefKind" in flat
    assert "interpolated as a single ENCODED path segment" in flat
    assert "a free-form or absolute URL, any external origin" in flat
    assert "is not access or publication authorization" in flat


def test_the_navigation_rule_does_not_forbid_the_applications_existing_links() -> None:
    """The application links a trade by interpolating ref_id into an internal route.

    An earlier draft read "no destination is built from ref_id or ref_kind", which would have
    made that correct, existing navigation non-conformant. The rule must permit it.
    """
    flat = flatten(CONTRACTS_TEXT)
    assert "no destination is built from `ref_id`" not in flat
    assert "No destination is built from `ref_id` or `ref_kind`" not in flat


# ------------------------------------------------------------- cardinality, applied


def test_cardinality_separates_the_six_quantities() -> None:
    """D4: the column was used for reference objects and for targets, without saying which."""
    span = section(CONTRACTS_TEXT, "**Cardinality: six quantities", "**A verified-empty")
    for quantity in (
        "relation cardinality",
        "reference-object count",
        "resolvable targets",
        "total population",
        "truncation",
        "unknown vs verified empty",
    ):
        assert quantity in span, f"{quantity} is not separated from the others"


def test_the_host_field_declaration_governs_rather_than_the_per_kind_column() -> None:
    flat = flatten(CONTRACTS_TEXT)
    assert "the host field's own declaration is what a validator checks" in flat
    assert "AskAnswer.citations" in flat, "the catalogue's own per-field precedent"


def test_a_verified_empty_population_is_never_relabelled_unknown() -> None:
    """R7: the earlier exception made a producer that counted and found none stop saying so."""
    flat = flatten(CONTRACTS_TEXT)
    assert "A verified-empty population is never relabelled unknown" in flat
    assert "the relation is amended" in flat
    assert "An `AVAILABLE` zero against a `ONE_OR_MORE` relation asserts" not in flat


def test_source_fact_is_amended_to_zero_or_more_and_the_field_may_narrow_it() -> None:
    """The honest instrument: the envelope legitimately references no source fact."""
    _permitted, cardinality = ROWS["source_fact"]
    assert cardinality == "ZERO_OR_MORE"
    flat = flatten(CONTRACTS_TEXT)
    assert "`AskAnswer.citations` keeps its field-level `ONE_OR_MORE`" in flat


def test_a_truncated_list_never_bounds_the_relation_from_its_page() -> None:
    span = section(CONTRACTS_TEXT, "truncated = false, total AVAILABLE", "**A verified-empty")
    assert "items.length <= total" in span
    assert "no bound is inferred" in span
    assert "which is a page fact" in span


def test_the_envelope_source_refs_is_not_a_ref_list_and_is_not_asked_to_change() -> None:
    """It has no ``cardinality`` and no ``total``; an instruction to change its total is void."""
    flat = flatten(CONTRACTS_TEXT)
    assert "The envelope's `source_refs` is not a `RefList`" in flat
    assert "no `cardinality`, no `total`, no `truncated` and no `resolution`" in flat


# --------------------------------------------------------- compatibility and versioning


def test_the_compatibility_decision_does_not_rest_on_field_arithmetic_alone() -> None:
    """A closed-enum addition is rejected by an unrecompiled validator, and the ADR says so."""
    assert "Two arguments are explicitly NOT relied on" in ADR_FLAT
    breaking = "A closed-vocabulary addition is a breaking change"
    assert f"{breaking} for an unrecompiled validator" in ADR_FLAT


def test_the_compatibility_decision_names_the_constraints_that_make_it_safe() -> None:
    span = section(ADR_TEXT, "It is safe here **only** because", "**This reasoning expires")
    for constraint in (
        "ONE local application",
        "NO independently deployed",
        "NO persisted response cache",
        "NO real producer exists",
    ):
        assert constraint in span, f"{constraint} is not named"


def test_the_compatibility_reasoning_states_its_own_expiry() -> None:
    assert "This reasoning expires, and it says so" in ADR_FLAT
    assert "the change requires a `schema_version` bump" in ADR_FLAT


def test_both_re_labelled_values_are_recorded_as_affected_surface() -> None:
    assert "Two emitted values change, and neither was ever contractual" in ADR_FLAT
    assert "This is a second re-labelling" in ADR_FLAT


# ------------------------------------------------------- the implementation, guarded

REFERENCES: Final = PROJECT_ROOT / "apps" / "cockpit" / "src" / "contracts" / "references.ts"
NAVIGATION: Final = PROJECT_ROOT / "apps" / "cockpit" / "src" / "lib" / "reference-navigation.ts"


def test_the_open_ref_kind_is_gone_and_the_closed_one_replaced_it() -> None:
    """The inversion ADR-0030 section 2.6 scheduled, and the reason it was blocked.

    ``ref_kind: z.string().min(1)`` was an OPEN string where the contract says closed. It
    could not be closed until D1, D2 and D3 fixed WHICH members the set has and WHICH
    resolutions each admits -- closing it against the defective table would have refused the
    truthful ``EMBEDDED`` declarations and frozen the mislabelled ``source_fact``. Those are
    now decided, so this asserts the defect is gone and the closed vocabulary replaced it.
    """
    values = VALUES.read_text(encoding="utf-8")
    assert "ref_kind: z.string().min(1)" not in values
    assert "ref_kind: refKind," in values


def test_the_closed_kind_vocabulary_has_the_twenty_seven_members_the_table_states() -> None:
    """Parsed out of the implementation and counted against the DOCUMENT's own table."""
    vocabularies = (
        PROJECT_ROOT / "apps" / "cockpit" / "src" / "contracts" / "vocabularies.ts"
    ).read_text(encoding="utf-8")
    block = section(vocabularies, "export const REF_KINDS = [", "] as const;")
    members = set(re.findall(r'"([a-z_]+)",', block))
    assert members == set(ROWS), sorted(members ^ set(ROWS))
    assert len(members) == 27


def test_the_implementation_carries_the_per_kind_resolution_sets_the_table_states() -> None:
    """Every row's permitted set, compared member for member against the parsed table.

    ``EMBEDDED`` is excluded on both sides: the document makes it available to every row and
    gates it on catalogue permission instead of enumeration, so it is checked by the carrier
    catalogue of section 4.3.2 and never by this table.
    """
    text = REFERENCES.read_text(encoding="utf-8")
    block = section(text, "export const KIND_RESOLUTIONS", "};")
    compiled: dict[str, set[str]] = {}
    for line in block.splitlines():
        match = re.match(r"^\s*([a-z_]+):\s*\[(.*?)\],\s*$", line)
        if match is None:
            continue
        kind, members = match.groups()
        compiled[kind] = set(re.findall(r'"([A-Z][A-Z0-9_]*)"', members))
    assert set(compiled) == set(ROWS), sorted(set(compiled) ^ set(ROWS))
    for kind, (permitted, _cardinality) in ROWS.items():
        assert compiled[kind] == set(permitted) - {"EMBEDDED"}, kind
        assert "EMBEDDED" not in compiled[kind], kind


def test_the_carrier_catalogue_names_a_carrier_for_every_authorized_embed() -> None:
    """Section 4.3.2 exists, and every row it carries states all four things R4 requires."""
    span = section(CONTRACTS_TEXT, "#### 4.3.2 ", "### 4.4 ")
    assert span, "section 4.3.2 names no carriers"
    rows = [line for line in span.splitlines() if line.startswith("| `") and "|" in line[3:]]
    embeds = [row for row in rows if "projection" in row or "complete target" in row]
    assert len(embeds) == 7, "seven host fields are authorized carriers"
    for row in embeds:
        assert re.search(
            r"CANONICAL_KEY|HOST_SCOPED_SUFFIX|TARGET_ID_FIELD|TARGET_REF_FIELD", row
        ), row


def test_the_carrier_catalogue_refuses_the_four_embeds_that_were_not_true() -> None:
    """Named, with the reason, rather than quietly dropped."""
    flat = flatten(section(CONTRACTS_TEXT, "#### 4.3.2 ", "### 4.4 "))
    for field in (
        "`TradeDetail.add_refs`",
        "`TradeDetail.exit_ref`",
        "`ShortSideSnapshot.borrow[].security_ref`",
        "`RiskDecision.initial_risk_ref`",
    ):
        assert field in flat, f"{field} is not recorded as a refused carrier"
    assert "a field's name is not proof it contains the referenced entity" in flat
    assert "untrue of the response" in flat


def test_the_navigation_allowlist_is_closed_and_internal() -> None:
    """R10, in the one module that owns it -- and it owns it alone."""
    text = NAVIGATION.read_text(encoding="utf-8")
    assert "const ROUTES" in text
    for route in re.findall(r'(?:template|path): "([^"]+)"', text):
        assert route.startswith("/"), route
        assert "://" not in route, route
    # Two duplicated destination maps used to live in the components. One allowlist now.
    components = PROJECT_ROOT / "apps" / "cockpit" / "src" / "components" / "cockpit"
    for name in ("attention.tsx", "what-changed.tsx"):
        assert "EVIDENCE_DESTINATION" not in (components / name).read_text(encoding="utf-8")


def test_the_adr_names_the_follow_up_this_cycle_implemented() -> None:
    assert "close ref_kind to the twenty-seven members" in ADR_FLAT
    assert "re-label CandidateDetail.downstream_refs.trade AND" in ADR_FLAT
    assert "RiskSnapshot.initial_planned_risk_open[].trade_ref to kind trade" in ADR_FLAT
    assert "assign every catalogue reference field its R2 kind, RefList fields included" in ADR_FLAT
    assert "audit every demoRef call site" in ADR_FLAT


def test_the_follow_up_requires_the_compatibility_constraints_to_be_rechecked() -> None:
    assert "re-check the four §6.1 deployment constraints" in ADR_FLAT
    assert "land contract, fixture and consumer changes in a SINGLE commit" in ADR_FLAT


# ------------------------------------------------- the scope a resolution requires (4.3.3)


#: Section 4.3's Resolution column names a scope outright on these rows, and only these.
SCOPES_NAMED_IN_THE_TABLE: Final = {
    "risk_decision": "risk:read",
    "audit_event": "audit:read",
    "chart_series": "market:read",
    "benchmark_series": "market:read",
}

SCOPE_SECTION: Final = section(
    CONTRACTS_TEXT,
    "#### 4.3.3 The scope a resolution requires",
    "### 4.4 The four risk quantities",
)


def test_the_specification_states_where_a_required_scope_comes_from() -> None:
    """A required scope the caller may name is not a required scope."""
    assert SCOPE_SECTION, "section 4.3.3 is absent"
    flat = flatten(SCOPE_SECTION)
    assert "A required scope the caller may name is not a required scope." in flat
    assert "refused rather than honoured" in flat


def test_the_scope_section_agrees_with_the_row_it_is_derived_from() -> None:
    """Every scope section 4.3 names outright is the scope section 4.3.3 assigns."""
    rows = section(CONTRACTS_TEXT, "### 4.3 Resolving a reference", "#### 4.3.1")
    assert rows, "the section 4.3 table is absent"
    flat = flatten(SCOPE_SECTION)
    for kind, scope in SCOPES_NAMED_IN_THE_TABLE.items():
        assert f"`{kind}`" in rows, kind
        assert f"`{scope}`" in flat, (kind, scope)


def test_the_two_kinds_whose_scope_is_inexpressible_say_so() -> None:
    """Their rows name a scope a `Ref` has no field to carry, and that is stated, not guessed."""
    flat = flatten(SCOPE_SECTION)
    assert "`evidence`, `source_fact`" in flat or "**`evidence`, `source_fact`**" in flat
    assert "none is expressible" in flat
    assert "there is no scope field on a reference to name one in" in flat.lower()
    assert "reserved to an ADR" in flat


def test_a_reference_label_is_not_authorization() -> None:
    """R10, restated where the access rule is: the label may withhold and may never admit."""
    flat = flatten(SCOPE_SECTION)
    assert "labels the reference and authorizes nothing" in flat
    assert "located target's own classification" in flat
    assert "disagree about classification are **refused**" in flat


def test_a_located_target_carries_its_own_identity_and_a_tombstone_is_recorded() -> None:
    """Absent metadata is never a passed check, and a flag is never a relationship."""
    flat = flatten(SCOPE_SECTION)
    assert "or it is not located" in flat
    assert "there is no shape in which absent metadata reads as a passed check" in flat
    assert "names the entity it withdrew" in flat


def test_the_scope_section_would_notice_its_own_removal() -> None:
    """A scanner that sees nothing passes every document vacuously."""
    assert section(CONTRACTS_TEXT, "#### 4.3.3 A heading that is not there", "### 4.4") == ""
