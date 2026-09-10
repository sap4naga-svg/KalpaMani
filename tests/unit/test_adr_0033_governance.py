"""ADR-0033 governance: the remaining C10 acceptance decisions, parsed and held to the code.

**ADR-0033 is PROPOSED — NOT IN FORCE** while the pull request introducing it is open. These tests
hold the proposal to four obligations that prose alone cannot keep:

* **Governance** -- the ADR declares itself proposed, predicts no merge, amends exactly the one
  document it names, edits no other ADR, ran nothing, and moves no disposition.
* **Decision M, held to the page** -- the Executive Overview's section inventory is **parsed out of
  `page.tsx` and the components it composes**, and every section must appear in the ADR's
  content-to-location table with a location that is either VISIBLE or DEFERRED behind one of the
  four named disclosures. A section that fell out of the table, or a row that said OMITTED, fails
  here -- which is the control against deferred mobile content becoming inaccessible.
* **Decision VC, held to the registry** -- every `href` in `NAV_ROUTES` and every deep destination
  is parsed out of `registry.ts` and must appear in the inventory; every axis declared inapplicable
  must cite a rule; the nominal total is re-derived from the rows; and the nine existing comparisons
  are read from the visual spec and must still be zero-tolerance.
* **Decisions PB and SR, held to their own rules** -- every budget carries a unit; the not-obtained
  rule is stated; the performance spec still asserts no budget, so the proposal fails no accepted
  contract; an axe pass is stated not to be a screen-reader assessment; the assessor is outstanding.
* **The status surface** -- PR #87's verified merge is recorded, the C10 section and the ADR-0033
  section are byte-identical in both status documents, and the acceptance record still reads one
  of four.

Every parser carries a self-test proving it can still see what it exists to catch.
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
APP: Final = PROJECT_ROOT / "apps" / "cockpit"

ADR: Final = DECISIONS / "ADR-0033-c10-remaining-acceptance-decisions.md"
UIUX: Final = COCKPIT / "ui-ux-specification.md"
RECORD: Final = COCKPIT / "c10-acceptance-record.md"
PAGE: Final = APP / "src" / "app" / "page.tsx"
REGISTRY: Final = APP / "src" / "nav" / "registry.ts"
VISUAL_SPEC: Final = APP / "e2e" / "c10-visual-regression.spec.ts"
PERF_SPEC: Final = APP / "e2e" / "c10-performance.spec.ts"
COMPONENTS: Final = APP / "src" / "components" / "cockpit"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8")
UIUX_TEXT: Final = UIUX.read_text(encoding="utf-8")
RECORD_TEXT: Final = RECORD.read_text(encoding="utf-8")
PAGE_TEXT: Final = PAGE.read_text(encoding="utf-8")
REGISTRY_TEXT: Final = REGISTRY.read_text(encoding="utf-8")
VISUAL_TEXT: Final = VISUAL_SPEC.read_text(encoding="utf-8")
PERF_TEXT: Final = PERF_SPEC.read_text(encoding="utf-8")


def flatten(text: str) -> str:
    """One line, ``**`` and blockquote markers stripped, so a wrapped rule is one phrase."""
    return " ".join(text.replace("**", "").replace(chr(10) + "> ", chr(10)).split())


ADR_FLAT: Final = flatten(ADR_TEXT)
UIUX_FLAT: Final = flatten(UIUX_TEXT)
RECORD_FLAT: Final = flatten(RECORD_TEXT)


def section(text: str, start: str, end: str) -> str:
    """One named span, so a match elsewhere in a long file does not count."""
    begin = text.find(start)
    if begin == -1:
        return ""
    stop = text.find(end, begin + len(start))
    return text[begin:] if stop == -1 else text[begin:stop]


def table_rows(span: str) -> list[list[str]]:
    """Every pipe-table body row in a span, as a list of stripped cells."""
    rows: list[list[str]] = []
    for line in span.splitlines():
        if not line.startswith("|") or set(line.replace("|", "").strip()) <= {"-", " "}:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows.append(cells)
    return rows[1:] if rows else []  # drop the header row


M_SPAN: Final = section(
    ADR_TEXT, "### M3 — where every deferred section remains accessible", "### M4"
)
M5_SPAN: Final = section(ADR_TEXT, "### M5 —", "### M6")
VC_SPAN: Final = section(ADR_TEXT, "### 4.2 The inventory", "### 4.3 The applicability rules")
VC_RULES_SPAN: Final = section(ADR_TEXT, "### 4.3 The applicability rules", "### 4.4")
PB_SPAN: Final = section(ADR_TEXT, "### 3.2 The budgets", "**Bounded query time")
SR_SPAN: Final = section(ADR_TEXT, "## 5. Decision SR", "## 6. Acceptance accounting")


# --------------------------------------------------------------------- governance


def test_the_adr_declares_itself_proposed_and_not_in_force() -> None:
    assert "**Status: PROPOSED — NOT IN FORCE." in ADR_TEXT
    assert "carries no authority" in ADR_FLAT
    assert "it is not to be rewritten as though this decision had authority" in ADR_FLAT
    assert "ADR-0033 is ACCEPTED / IN FORCE" not in ADR_FLAT


def test_the_adr_predicts_no_merge_sha_and_no_timestamp() -> None:
    assert "No merge SHA and no merge timestamp is predicted here" in ADR_FLAT
    assert re.search(r"\b[0-9a-f]{40}\b", ADR_TEXT) is None, "a forty-character SHA appears"


def test_the_adr_supersedes_nothing_and_amends_only_the_ui_specification() -> None:
    assert "**Supersedes:** nothing" in ADR_TEXT
    amends = section(ADR_TEXT, "**Amends:**", "**Relates to:**")
    assert "ui-ux-specification.md" in amends
    assert "§12" in amends and "§15" in amends
    assert "amends no other section of that document, and no other document" in flatten(amends)
    for other in (
        "ADR-0026",
        "ADR-0027",
        "ADR-0028",
        "ADR-0029",
        "ADR-0030",
        "ADR-0031",
        "ADR-0032",
    ):
        assert other in amends, f"{other} is not named as unedited"
    assert "edits no read-model contract, no traceability-matrix row" in flatten(amends)


def test_the_adr_ran_nothing_and_changed_no_interface() -> None:
    for phrase in (
        "Nothing was run to produce this decision",
        "no browser suite was launched",
        "no screenshot baseline was created or regenerated",
        "no performance measurement was taken",
        "no CI configuration was touched",
        "no user interface was changed",
        "No human accessibility assessment occurred",
        "No Blueprint PDF was opened or edited",
    ):
        assert phrase in ADR_FLAT, phrase


def test_acceptance_is_stated_to_establish_definitions_and_no_result() -> None:
    assert "Accepting a budget is not meeting it" in ADR_FLAT
    assert "one satisfied criterion of four" in ADR_FLAT
    assert "every row below is at the first column at most" in ADR_FLAT.lower()


def test_the_amended_specification_marks_every_new_subsection_proposed() -> None:
    for marker in (
        "### 12.1 The mobile executive summary — PROPOSED by ADR-0033, NOT IN FORCE",
        "### 15.1 Performance budgets — PROPOSED by ADR-0033, NOT IN FORCE",
        "### 15.2 Visual regression coverage — PROPOSED by ADR-0033, NOT IN FORCE",
        "### 15.3 The manual screen-reader assessment protocol — PROPOSED by ADR-0033, "
        "NOT IN FORCE",
        "### 15.4 What accepting §15.1–§15.3 establishes — PROPOSED, NOT IN FORCE",  # noqa: RUF001
    ):
        assert marker in UIUX_TEXT, marker
    assert "Further amended by** [ADR-0033]" in UIUX_TEXT
    assert (
        "ADR-0033 is PROPOSED — NOT IN FORCE while the pull request introducing it is open"
        in UIUX_FLAT
    )


def test_the_accepted_section_12_row_and_section_15_rows_are_unchanged() -> None:
    """The proposal clarifies the accepted rows; it may not rewrite them."""
    assert (
        "| **390 × 844** | mobile; **executive summary only** — tier 1, "  # noqa: RUF001
        "Attention Required and search. "
        "Operator tables are reachable and explicitly narrow |"
    ) in UIUX_TEXT
    assert (
        "a stable baseline per route and per state. A diff is a review item, not an auto-accept"
        in UIUX_TEXT
    )
    assert (
        "with **manual keyboard and screen-reader passes**, because an automated pass is not an "
        "accessible interface" in UIUX_TEXT
    )
    assert "**This cycle measures nothing and claims nothing** |" in UIUX_TEXT


# --------------------------------------------------------------- decision M, held to the page


TEST_ID: Final = re.compile(r'(?:data-testid|testId)="([a-z][a-z0-9.-]*)"')
PANEL_IMPORT: Final = re.compile(
    r"^import \{ (\w+) \} from \"@/components/cockpit/([a-z-]+)\";", re.MULTILINE
)
DEFAULT_TEST_ID: Final = re.compile(r'testId = "([a-z-]+)"')
SECTION_ID: Final = re.compile(r'<section[^>]*aria-labelledby="([a-z-]+)"')


def page_test_ids() -> set[str]:
    """Every stable test id the Executive Overview renders directly, skeletons excluded."""
    return {match for match in TEST_ID.findall(PAGE_TEXT) if match != "skeleton"}


def composed_panel_test_ids() -> set[str]:
    """The default test ids of the panel components the page composes by tag."""
    found: set[str] = set()
    for name, module in PANEL_IMPORT.findall(PAGE_TEXT):
        if f"<{name}" not in PAGE_TEXT or not name.endswith(("Panel", "Overview")):
            continue
        source = (COMPONENTS / f"{module}.tsx").read_text(encoding="utf-8")
        default = DEFAULT_TEST_ID.search(source)
        if default is not None:
            found.add(default.group(1))
            continue
        literal = re.search(rf'data-testid="({name[0].lower() + name[1:]}|[a-z-]+-panel)"', source)
        assert literal is not None, f"{name} renders no test id"
        found.add(literal.group(1))
    return found


def page_section_ids() -> set[str]:
    return set(SECTION_ID.findall(PAGE_TEXT))


def test_the_page_parsers_see_the_executive_overview() -> None:
    ids = page_test_ids()
    for expected in (
        "tile-strategy-capital",
        "answer-performance",
        "answer-risk",
        "answer-health",
        "answer-changed",
        "answer-attention",
        "tile-open-gates",
        "tile-exposure",
        "tile-last-runs",
    ):
        assert expected in ids, expected
    assert {
        "attention-panel",
        "what-changed-panel",
        "performance-overview",
    } <= composed_panel_test_ids()
    assert "operator-evidence" in page_section_ids()


def test_every_section_of_the_executive_overview_is_in_the_content_to_location_table() -> None:
    inventory = page_test_ids() | composed_panel_test_ids() | {"operator-evidence"}
    missing = sorted(identifier for identifier in inventory if f"`{identifier}`" not in M_SPAN)
    assert not missing, f"sections absent from the M3 table: {missing}"


def test_no_section_is_omitted_and_every_deferred_section_names_a_disclosure() -> None:
    rows = table_rows(M_SPAN)
    assert len(rows) >= 18, "the M3 table parser sees too few rows"
    labels = {
        "What changed — details",
        "Performance overview",
        "Supporting context",
        "Response evidence",
    }
    for row in rows:
        mobile = row[2]
        assert not re.search(r"\b(OMITTED|REMOVED|HIDDEN|DROPPED)\b", mobile), row[0]
        assert mobile.startswith(("**VISIBLE**", "**DEFERRED")), row[0]
        if mobile.startswith("**DEFERRED"):
            assert any(label in mobile for label in labels), f"{row[0]} names no disclosure"
    for label in labels:
        assert f"`{label}`" in M5_SPAN, f"{label} is not defined in M5"


def test_a_row_that_omitted_content_would_fail_the_table_check() -> None:
    """The negative control, run against a mutated copy rather than described."""
    mutated = M_SPAN.replace(
        "**DEFERRED — disclosure `What changed — details`**", "**OMITTED at mobile**", 1
    )
    assert mutated != M_SPAN
    offending = [row for row in table_rows(mutated) if "OMITTED" in row[2]]
    assert offending, "the mutation was not visible to the parser"


def test_the_deferred_sections_have_no_owning_route_invented() -> None:
    for identifier in ("what-changed-panel", "Broker-reported equity"):
        row = next(r for r in table_rows(M_SPAN) if identifier in r[0])
        assert row[3].startswith("**none**"), f"{identifier} was given a destination"
    assert "no route is invented" in ADR_FLAT.lower() or "no destination is created" in ADR_FLAT


def test_decision_m_keeps_the_exceptions_visible_and_puts_no_value_on_a_control() -> None:
    m4 = section(ADR_TEXT, "### M4 —", "### M5")
    for exception in (
        "page-level state badge",
        "freshness indicator",
        "`answer-health`",
        "two highest-ranked attention items",
    ):
        assert exception in m4, exception
    assert "never carries a metric value" in flatten(M5_SPAN)
    assert "focus stays on the control" in flatten(M5_SPAN)
    assert "collapsed" in M5_SPAN and "aria-expanded" in M5_SPAN


def test_decision_m_is_not_reported_as_satisfying_the_row() -> None:
    assert "stays `NOT SATISFIED` until an implementation meets M8" in ADR_TEXT
    assert "None of these tests exists, and this ADR writes none" in ADR_FLAT


# ------------------------------------------------------------- decision VC, held to the registry


HREF: Final = re.compile(r'^\s+href: "(/[^"]*)",', re.MULTILINE)
DEEP_ROUTE: Final = re.compile(r'^\s+route: "(/[^"]*)",', re.MULTILINE)
BOLD_INT: Final = re.compile(r"\*\*(\d+)\*\*")


def registry_routes() -> list[str]:
    return HREF.findall(REGISTRY_TEXT) + DEEP_ROUTE.findall(REGISTRY_TEXT)


def test_the_registry_parser_sees_the_thirty_routes_and_two_deep_destinations() -> None:
    routes = registry_routes()
    assert len(HREF.findall(REGISTRY_TEXT)) == 30
    assert DEEP_ROUTE.findall(REGISTRY_TEXT) == [
        "/portfolio/trades/[tradeId]",
        "/signals/candidates/[candidateId]",
    ]
    assert len(routes) == len(set(routes))


def test_every_registered_route_and_deep_destination_is_in_the_inventory() -> None:
    rows = table_rows(VC_SPAN)
    listed = {row[1].strip("`") for row in rows}
    missing = [route for route in registry_routes() if route not in listed]
    assert not missing, f"routes absent from the VC inventory: {missing}"
    extra = listed - set(registry_routes())
    assert not extra, f"inventory names routes the registry does not have: {sorted(extra)}"


def test_every_inapplicable_axis_cites_a_rule() -> None:
    rows = table_rows(VC_SPAN)
    assert len(rows) == 32
    rules = set(re.findall(r"\*\*(VC-R\d)\*\*", VC_RULES_SPAN))
    assert rules == {"VC-R1", "VC-R2", "VC-R3", "VC-R4", "VC-R5"}
    for row in rows:
        for axis in (row[2], row[3]):
            if axis.startswith("**1"):
                cited = re.search(r"VC-R\d", axis)
                assert cited is not None, f"{row[0]} declares an axis inapplicable without a rule"
                assert cited.group(0) in rules


def test_an_uncited_inapplicability_would_fail() -> None:
    mutated = VC_SPAN.replace(
        "**1 — VC-R2**: inert specification, no read model", "**1** — not needed", 1
    )
    assert mutated != VC_SPAN
    row = next(r for r in table_rows(mutated) if r[0] == "`governance-controls`")
    assert row[2].startswith("**1") and re.search(r"VC-R\d", row[2]) is None


def test_the_nominal_total_is_the_sum_of_the_rows() -> None:
    rows = table_rows(VC_SPAN)
    total = 0
    for row in rows:
        counts = BOLD_INT.findall(row[6])
        assert counts, f"{row[0]} states no nominal count"
        total += int(counts[-1])
    assert total == 401
    assert "Nominal total: 50 + 28 × 12 + 2 × 6 + 3 = 401 snapshots" in ADR_FLAT  # noqa: RUF001
    assert "of which nine exist today" in ADR_FLAT


def test_no_rule_exempts_a_viewport_or_a_mode() -> None:
    assert "No rule exempts a viewport in VC-I3's list, and no rule exempts a mode" in ADR_FLAT
    for row in table_rows(VC_SPAN):
        assert row[5] in {"3", "**6** (VC-I3)"}, f"{row[0]} has an unexpected viewport count"


def test_the_nine_existing_comparisons_stay_zero_tolerance_in_the_spec_and_in_the_adr() -> None:
    assert (
        "const STRICT = { threshold: 0, maxDiffPixels: 0, maxDiffPixelRatio: 0 } as const;"
        in VISUAL_TEXT
    )
    assert VISUAL_TEXT.count("...STRICT,") == 3
    assert "`threshold: 0`, `maxDiffPixels: 0`, `maxDiffPixelRatio: 0` for every image" in ADR_TEXT
    assert "This ADR proposes no other tolerance for any image" in ADR_FLAT
    baseline_dir = APP / "e2e" / "visual-baseline"
    assert len(list(baseline_dir.rglob("*.png"))) == 9


def test_the_interpretations_are_marked_as_requiring_acceptance() -> None:
    for interpretation in ("VC-I1", "VC-I2", "VC-I3", "VC-I4"):
        assert f"**{interpretation}**" in ADR_TEXT
    assert "neither silently requires nor silently waives a Cartesian product" in ADR_FLAT
    assert "no masking, no tolerance increase and no automatic regeneration" in ADR_FLAT.lower()
    assert "`--update-snapshots` is never run to make a failing comparison pass" in ADR_FLAT


# ------------------------------------------------------------- decision PB, held to its own rules


def test_every_budget_carries_a_unit_and_an_aggregation() -> None:
    rows = table_rows(PB_SPAN)
    ids = [row[0].strip("*") for row in rows]
    assert ids == ["PB1", "PB2", "PB3", "PB4", "PB5"]
    for row in rows[:4]:
        assert "ms" in row[2] and "p50" in row[2] and "no sample" in row[2], row[0]
    assert "KB" in rows[4][2]
    bare = [
        row[0]
        for row in rows
        if re.search(
            r"(?<![\d ])\d{2,}(?![\d ]*(ms|KB|×))",  # noqa: RUF001
            row[2].replace("1 000", "1000").replace("1 500", "1500").replace("1 200", "1200"),
        )
        and "ms" not in row[2]
        and "KB" not in row[2]
    ]
    assert not bare, f"a budget states a bare number: {bare}"


def test_a_missing_measurement_is_never_zero_and_never_passing() -> None:
    for phrase in (
        "NOT OBTAINED -- the paint entry was absent on every route",
        "never zero, never a pass, and never excluded from the denominator",
        "NEVER zero, NEVER passing, NEVER dropped from the denominator",
        "FAILED NAVIGATION",
        "INVALID SAMPLE",
    ):
        assert phrase in ADR_FLAT, phrase


def test_local_timings_do_not_establish_production_performance() -> None:
    assert "local timings do not establish production service performance" in ADR_FLAT
    assert "No budget is evaluated against a development server" in ADR_FLAT.replace(
        "no budget is evaluated", "No budget is evaluated"
    )
    assert "F — field / deployed" in ADR_TEXT and "no budget is set" in ADR_FLAT


def test_the_quoted_production_figures_match_the_acceptance_record() -> None:
    for figure in ("618 ms", "462 ms", "384 ms", "269 ms", "311 ms", "51 ms", "211 ms"):
        assert figure in ADR_FLAT and figure in RECORD_FLAT, figure
    assert (
        "first contentful paint NOT OBTAINED" in ADR_FLAT
        or "first contentful paint       NOT OBTAINED" in ADR_TEXT
    )


def test_the_proposal_makes_the_current_performance_spec_fail_no_accepted_contract() -> None:
    """A proposed budget is asserted only once accepted, by a cycle authorized to assert it."""
    assert "toBeLessThan" not in PERF_TEXT
    assert "NO BUDGET IS ASSERTED" in PERF_TEXT
    assert "Acceptance establishes the budgets. It establishes no compliance" in ADR_FLAT


def test_bounded_query_time_is_deferred_rather_than_invented() -> None:
    assert "PB-Q is recorded as `DEFERRED — requires a read-model boundary`" in ADR_FLAT


# ------------------------------------------------------------- decision SR, held to its own rules


def test_an_automated_pass_is_stated_not_to_be_a_screen_reader_assessment() -> None:
    assert "An automated axe pass is not a screen-reader assessment" in flatten(SR_SPAN)
    assert "source inspection is not one" in flatten(SR_SPAN)
    assert "Not the author, not an axe run, not a reviewer reading source, not this ADR" in flatten(
        SR_SPAN
    )


def test_the_assessor_is_outstanding_and_no_technology_is_claimed_available() -> None:
    assert "the assignment is OUTSTANDING" in flatten(SR_SPAN)
    assert "nothing here invents one" in flatten(SR_SPAN)
    assert "No availability of any assistive technology is claimed here" in flatten(SR_SPAN)
    assert "nothing is installed by this adr" in flatten(SR_SPAN).lower()
    assert "The manual screen-reader pass stays `NOT_ASSESSED`" in flatten(SR_SPAN)


def test_the_protocol_records_versions_at_execution_and_separates_the_keyboard_pass() -> None:
    assert "recorded at execution" in flatten(SR_SPAN)
    assert "Two sessions, two evidence sheets" in flatten(SR_SPAN)
    assert "A passing keyboard pass is not a screen-reader pass" in flatten(SR_SPAN)
    assert "zero S1 and zero S2" in flatten(SR_SPAN)


def test_the_journeys_are_traced_to_accepted_clauses() -> None:
    rows = table_rows(section(SR_SPAN, "### 5.3", "### 5.4"))
    assert len(rows) == 11  # J1-J10 and SR-A
    for row in rows:
        assert re.search(r"§\d+|U\d+|Area \d+|ADR-00\d\d|M\d", row[2]), (
            f"{row[0]} is traced to nothing"
        )


# ------------------------------------------------------------------------- the status surface


@pytest.fixture(params=["README.md", "CLAUDE.md"])
def status_document(request: pytest.FixtureRequest) -> tuple[str, str]:
    name = request.param
    return name, (PROJECT_ROOT / name).read_text(encoding="utf-8")


def test_both_status_documents_record_the_verified_pr_87_merge(
    status_document: tuple[str, str],
) -> None:
    name, text = status_document
    flat = flatten(text)
    for statement in (
        "C10 polish and acceptance cycle: MERGED / NOT AN ACCEPTANCE",
        "PR #87: MERGED",
        "PR #87 merge commit: 28e27a99b6dcf9d947c209e47fe319f914bf243b",
        "PR #87 merged at: 2026-09-10T02:49:20Z",
        "PR #87 final reviewed head: 34be5a4a2b9c29fbc7ac19f754273733035bd67d",
        "ad64f3723cf0b8406461539513189596cb653a56",
        "section 15 criteria satisfied: 1 OF 4",
        "manual screen-reader pass: NOT ASSESSED",
        "ADR-0033: PROPOSED / NOT IN FORCE",
        "assessor assigned: NONE - OUTSTANDING",
        "new screenshot baselines created: NONE",
        "C5: NOT COMPLETE",
        "C7: NOT COMPLETE",
        "full Cockpit V1: INCOMPLETE",
    ):
        assert statement in flat, f"{name}: {statement}"


def test_no_status_document_still_calls_c10_an_open_pull_request(
    status_document: tuple[str, str],
) -> None:
    name, text = status_document
    stale = [
        line
        for line in text.splitlines()
        if "IMPLEMENTED IN AN OPEN PULL REQUEST" in line and line.startswith("C10")
    ]
    assert not stale, f"{name}: {stale}"
    assert "C10 polish and acceptance cycle: IMPLEMENTED IN AN OPEN PULL REQUEST" not in flatten(
        text
    )
    assert "ADR-0033: ACCEPTED" not in flatten(text)


def test_the_c10_and_adr_0033_sections_are_identical_in_both_status_documents() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    claude = (PROJECT_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    c10 = "### The C10 Cockpit polish and acceptance cycle — MERGED, and not an acceptance"
    adr33 = (
        "### The remaining C10 acceptance decisions, and ADR-0033 — PROPOSED, and nothing is "
        "implemented"
    )
    followup = "### The C5 completion follow-up — MERGED"
    assert section(readme, c10, adr33) == section(claude, c10, adr33)
    assert section(readme, adr33, followup) == section(claude, adr33, followup)
    assert section(readme, adr33, followup).count("PROPOSED") >= 5


def test_the_acceptance_record_records_the_merge_and_keeps_its_dispositions() -> None:
    assert "PR #87 has since MERGED" in RECORD_FLAT
    assert "28e27a99b6dcf9d947c209e47fe319f914bf243b" in RECORD_TEXT
    assert "merge tree identical to the reviewed head's tree" in RECORD_FLAT
    assert "section 15 criteria satisfied:                    1 OF 4" in RECORD_TEXT
    assert "manual screen-reader pass:                        NOT ASSESSED" in RECORD_TEXT
    assert (
        "No historical failure in this record is rewritten into a pass by the merge" in RECORD_FLAT
    )
    assert "## 12. After the merge" in RECORD_TEXT


def test_the_three_causes_wording_is_corrected_to_match_its_four_rows() -> None:
    span = section(
        RECORD_TEXT, "**Four causes that were offered", "**The cause is NOT ESTABLISHED.**"
    )
    assert span, "the corrected sentence is missing"
    assert "Three causes that were offered" not in RECORD_TEXT.replace('read *"Three\ncauses"*', "")
    rows = table_rows(span)
    assert len(rows) == 4


def test_the_carried_forward_limitations_are_named_and_unabsorbed() -> None:
    carried = section(ADR_TEXT, "## 7. Carried forward", "## 8. Alternatives")
    for item in (
        "rejected reads render like pending reads",
        "reuseExistingServer provenance risk",
        "the cause is NOT ESTABLISHED",
        "capacity diagnostic limitations",
        "original PR #84 Linux review evidence",
        "UNAVAILABLE",
        "C5 and C7",
        "NOT COMPLETE",
    ):
        assert item in flatten(carried), item
    assert "none is resolved by this ADR" in flatten(carried)


def test_the_standing_limits_are_unchanged() -> None:
    for line in (
        "Run A:                                    COMPLETED ONCE, 2026-09-04 -- retry NOT "
        "AUTHORIZED",
        "Run B:                                    NOT RUN / NOT AUTHORIZED -- 2026-09-12 is "
        "eligibility, not permission",
        "combined assessment:                      NOT RUN / NOT AUTHORIZED",
        "P1-P9:                                    UNEVALUATED",
        "G1 / G2:                                  OPEN / OPEN",
        "live trading:                             HARD-DISABLED",
        "C5 / C7 / C10 / full Cockpit V1:          INCOMPLETE",
    ):
        assert line in ADR_TEXT, line


STATUS_LINE: Final = re.compile(
    r"^(?P<key>[A-Za-z0-9 ,./()#'-]+?):\s{2,}(?P<value>\S.*)$", re.MULTILINE
)

#: Status lines that appear in more than one block and must agree everywhere they appear. A block
#: that moved and a block that did not is the drift this repository's own history records, and a
#: substring test over the whole document cannot see it -- the correct spelling in one block hides
#: the wrong spelling in another.
AGREEING_LINES: Final[dict[str, str]] = {
    "section 15 criteria satisfied": "1 OF 4",
    "manual screen-reader pass": "NOT ASSESSED",
    "C10 polish and acceptance cycle": "MERGED / NOT AN ACCEPTANCE",
    "ADR-0033": "PROPOSED / NOT IN FORCE",
    "first contentful paint, production run": "NOT OBTAINED - NEVER ZERO, NEVER PASSING",
    "assessor assigned": "NONE - OUTSTANDING",
}


def status_lines(text: str, key: str) -> list[str]:
    return [m.group("value").strip() for m in STATUS_LINE.finditer(text) if m.group("key") == key]


def test_the_status_line_parser_sees_repeated_lines() -> None:
    claude = (PROJECT_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert len(status_lines(claude, "section 15 criteria satisfied")) >= 2
    assert len(status_lines(claude, "manual screen-reader pass")) >= 2


def test_every_repeated_status_line_agrees_across_blocks(status_document: tuple[str, str]) -> None:
    name, text = status_document
    for key, expected in AGREEING_LINES.items():
        values = status_lines(text, key)
        assert values, f"{name}: no '{key}:' status line"
        assert all(value == expected for value in values), f"{name}: {key} -> {values}"
