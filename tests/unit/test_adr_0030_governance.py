"""ADR-0030 governance: the reference contract, parsed out of the specification and executed.

ADR-0030 is a **proposal**. These are therefore **proposal tests**: they check that the
proposed rules are present, internally consistent and satisfiable, and they check that the
application's runtime has **not** been changed to implement them. Nothing here asserts that
the Cockpit behaves this way today, because it does not and is not authorized to.

The suite has three parts.

* **Governance** -- ADR-0030 declares itself proposed, predicts no merge, amends no accepted
  ADR document, and authorizes no implementation, infrastructure or execution.
* **The contract, executed** -- every rule is parsed out of ``read-model-contracts.md`` and
  run. There is no second copy of the table in this file: the reference rows, the field
  assignments, the resolution sets and the reason matrix are all read from the document at
  import time, so a document that reverts to the defective rule fails here.
* **The pending gap** -- the runtime is asserted to be **unchanged**, so a later reader can
  tell that the proposal was documented and not silently implemented.

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
    assert "`EMBEDDED` is additionally permitted for **every** row" in flat


def test_embedded_is_constrained_by_truth_rather_than_by_enumeration() -> None:
    flat = flatten(CONTRACTS_TEXT)
    rule = "a response may declare it exactly when that response carries the referenced payload"
    assert rule in flat


def test_unresolvable_v1_is_refused_over_an_implemented_synthetic_producer() -> None:
    """R6: an implemented fixture-backed producer exists, and is not a missing one."""
    flat = flatten(CONTRACTS_TEXT)
    rule = "a producer implemented against repository-owned synthetic fixtures exists"
    assert rule in flat.lower()


# ------------------------------------------------- every reference field names a kind


def catalogue() -> str:
    return section(CONTRACTS_TEXT, "### 4.5 The payload contracts", "### 4.6 ")


def unassigned_ref_fields() -> list[str]:
    """Field names in section 4.5 that hold a ``Ref`` without stating a kind on the line."""
    names: list[str] = []
    for line in catalogue().splitlines():
        if "kind" in line or not re.search(r":\s*Ref\b", line):
            continue
        names.extend(re.findall(r"([a-z_]+)\s*:\s*Ref\b", line))
    return sorted(set(names))


UNASSIGNED: Final = unassigned_ref_fields()


def test_the_unassigned_field_parser_sees_the_fields_the_defect_was_about() -> None:
    """A scanner blind to these fields would pass the defective document vacuously."""
    for field in ("trade", "trade_ref", "local_ref", "correction_of", "superseded_by"):
        assert field in UNASSIGNED, f"{field} holds a Ref and states no kind on its own line"


def assignment_table() -> dict[str, str]:
    """Field -> assigned kind, from the section 4.3.1 assignment table."""
    span = section(CONTRACTS_TEXT, "#### 4.3.1 ", "**`security_ref` is `evidence` everywhere.**")
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


def test_the_assignment_parser_sees_the_assignment_table() -> None:
    assert len(ASSIGNED) >= 17, "section 4.3.1 assigns every unassigned reference field"


def test_every_unassigned_reference_field_is_assigned_a_kind() -> None:
    """D1, closed: no Ref-valued field in the catalogue is left without a kind."""
    leaf_names = {field.rsplit(".", 1)[-1].rstrip("[]") for field in ASSIGNED}
    missing = [field for field in UNASSIGNED if field not in leaf_names]
    assert missing == [], f"section 4.3.1 assigns no kind to {missing}"


def test_every_assigned_kind_is_a_table_row_or_a_stated_family() -> None:
    """An assignment naming a kind with no row would recreate the defect it fixes."""
    for field, kind in ASSIGNED.items():
        named = set(re.findall(r"`([a-z_]+)`", kind))
        if not named:
            continue
        unknown = named - set(ROWS)
        assert unknown == set(), f"{field} is assigned unknown kind(s) {sorted(unknown)}"


def test_the_trade_reference_is_assigned_the_trade_kind_and_not_a_provenance_fact() -> None:
    """The defect a reader could see: a trade reference labelled `source_fact`."""
    assert ASSIGNED["CandidateDetail.downstream_refs.trade"] == "`trade`"
    assert ASSIGNED["RiskSnapshot.initial_planned_risk_open[].trade_ref"] == "`trade`"


def test_one_field_name_never_means_two_kinds() -> None:
    """`security_ref` is `evidence` in the catalogue, and stays `evidence` in the assignments."""
    for field, kind in ASSIGNED.items():
        if field.endswith("security_ref"):
            assert kind == "`evidence`", f"{field} contradicts CandidateDetail.security_ref"


# ------------------------------------------------------- the four unavailable outcomes


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
    """ADR-0028's guard is preserved, not relaxed to fit this proposal's prose.

    An earlier draft placed ``REFERENT_NOT_FOUND`` under ``NOT_APPLICABLE``. ADR-0028 holds
    that inapplicability is a property of the subject or of the arithmetic and never a
    synonym for "we do not have it", and a reference naming nothing is exactly the latter.
    """
    matrix = section(CONTRACTS_TEXT, "| `availability` | `value` |", "\n\n")
    applicable = [line for line in matrix.splitlines() if line.startswith("| `NOT_APPLICABLE`")]
    assert len(applicable) == 1
    assert "REFERENT_NOT_FOUND" not in applicable[0]
    assert "`NOT_DEFINED_FOR_SUBJECT`, `DENOMINATOR_ZERO` — and nothing else" in applicable[0]


def test_referent_not_found_is_in_the_closed_error_vocabulary() -> None:
    errors = section(CONTRACTS_TEXT, "| **errors** |", "\n|")
    assert "REFERENT_NOT_FOUND" in errors


def test_the_four_unavailable_outcomes_stay_distinct() -> None:
    span = section(CONTRACTS_TEXT, "**Four unavailable outcomes", "**A malformed reference")
    for code in (
        "REFERENT_NOT_FOUND",
        "PRODUCER_NOT_IMPLEMENTED",
        "CLASSIFICATION_WITHHELD",
    ):
        assert code in span, f"{code} is not distinguished from the others"
    assert "refused at admission" in span, "a malformed reference is not an availability state"


def test_a_reference_never_resolves_to_a_substitute_entity() -> None:
    flat = flatten(CONTRACTS_TEXT)
    assert "No resolver falls back to a nearest match, a default or a first row" in flat


def test_navigation_is_an_allowlist_and_never_a_constructed_url() -> None:
    flat = flatten(CONTRACTS_TEXT)
    assert "closed allowlist keyed by `RefKind`" in flat
    assert "no generic external URL fetcher, proxy or unrestricted resolver exists" in flat
    assert "is not access or publication authorization" in flat


# ------------------------------------------------------------- cardinality, applied


def test_cardinality_is_stated_to_describe_the_relation() -> None:
    """D4: the column was used for reference objects and for targets, without saying which."""
    flat = flatten(CONTRACTS_TEXT)
    assert "The Cardinality column describes the RELATION" in flat
    assert "not how many reference objects a field carries" in flat


def test_an_empty_one_or_more_list_may_not_assert_an_available_zero() -> None:
    flat = flatten(CONTRACTS_TEXT)
    assert "An `AVAILABLE` zero against a `ONE_OR_MORE` relation asserts" in flat


def test_source_fact_is_still_a_one_or_more_relation() -> None:
    """The exception exists because the envelope's `source_refs` is legitimately empty."""
    _permitted, cardinality = ROWS["source_fact"]
    assert cardinality == "ONE_OR_MORE"


# ------------------------------------------------------------ the pending gap, guarded


def test_the_runtime_reference_kind_is_still_open_and_the_gap_is_pending() -> None:
    """ADR-0030 is a proposal. Implementing it here would be implementing an unaccepted rule.

    This is the guard that keeps the two apart. It asserts the defect ADR-0030 section 2.6
    names is **still present** in the application, so a reader can tell that the proposal was
    documented and not silently enacted. It is expected to be inverted by the bounded
    implementation cycle that follows acceptance.
    """
    assert "ref_kind: z.string().min(1)" in VALUES.read_text(encoding="utf-8")


def test_the_adr_names_the_gap_it_leaves_open() -> None:
    assert "close ref_kind to the twenty-seven members" in ADR_FLAT
    assert "re-label CandidateDetail.downstream_refs.trade to kind trade" in ADR_FLAT
