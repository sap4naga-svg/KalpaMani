"""ADR-0033 governance: the remaining C10 acceptance decisions, parsed and held to the code.

**ADR-0033 is ACCEPTED / IN FORCE.** PR #88 was independently reviewed and merged. **The ADR's own
document is not edited** -- an accepted decision keeps the conditional status line it was written
with, as history -- so the assertions that read it still find "PROPOSED", and they are claims about
the document, not about the decision's authority. **The amended specification and the status
documents DO say ACCEPTED**, and the assertions below hold them to it. **Decision M is now
IMPLEMENTED, in an open pull request**, and the tests at the end hold that implementation to the
page: every deferred section of the M3 table has a disclosure with the accepted label, the four
Decision VC expanded rows exist at the mobile width only, and the nine pre-existing baselines are
byte-identical by digest.

These tests hold the decision to four obligations that prose alone cannot keep:

* **Governance** -- the ADR document declares itself proposed, predicts no merge, amends exactly
  the one document it names, edits no other ADR, ran nothing, and moves no disposition; the
  documents around it record the acceptance and keep the proposed period as history.
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
* **The status surface** -- PR #87's and PR #88's verified merges are recorded, the C10 section
  and the ADR-0033 section are byte-identical in both status documents, and the acceptance record
  still reads one of four.

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
    """An accepted decision keeps the status line it was written with, as history.

    ADR-0033 is ACCEPTED / IN FORCE because PR #88 merged, and the merge is the acceptance
    event the document itself names. The document is not rewritten after the fact: it records
    what was reviewed, which is the rule every accepted decision in this repository follows.
    """
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


def test_the_amended_specification_marks_every_new_subsection_accepted() -> None:
    """`PROPOSED by ADR-0033` is provenance and stays; `ACCEPTED with it` is the status.

    Both halves matter. A document still calling an accepted decision a proposal is stale, and
    a document that erased the proposed period would claim the deltas had authority before the
    review that gave it to them.
    """
    for marker in (
        "### 12.1 The mobile executive summary — PROPOSED by ADR-0033, ACCEPTED with it",
        "### 15.1 Performance budgets — PROPOSED by ADR-0033, ACCEPTED with it",
        "### 15.2 Visual regression coverage — PROPOSED by ADR-0033, ACCEPTED with it",
        "### 15.3 The manual screen-reader assessment protocol — PROPOSED by ADR-0033, "
        "ACCEPTED with it",
        "### 15.4 What accepting §15.1–§15.3 establishes — ACCEPTED with ADR-0033",  # noqa: RUF001
    ):
        assert marker in UIUX_TEXT, marker
    assert "Further amended by** [ADR-0033]" in UIUX_TEXT
    assert "ADR-0033 is ACCEPTED / IN FORCE" in UIUX_FLAT
    assert (
        "ADR-0033 is PROPOSED — NOT IN FORCE while the pull request introducing it is open"
        not in UIUX_FLAT
    )
    assert "HISTORICAL" in UIUX_FLAT
    assert "ADR-0033 was PROPOSED and carried no authority" in UIUX_FLAT
    # Accepting the definitions satisfied nothing, and the specification says so.
    assert "Accepting the definition does not satisfy the row" in UIUX_FLAT
    assert "acceptance of a budget establishes no compliance with it" in UIUX_FLAT
    assert "no new baseline is created by it" in UIUX_FLAT
    assert "No assessment has occurred, no assessor is assigned" in UIUX_FLAT


def test_the_amended_subsections_carry_the_review_corrections() -> None:
    """The specification deltas say what the corrected ADR says, in the same words."""
    for phrase in (
        "one availability badge per distinct non-`AVAILABLE` state",
        "never a precedence the contract does not define",
        "the route's own read-model readiness",
        "this row reads at most `PARTIAL`, however PB1–PB5 report",  # noqa: RUF001
        "`PASS — ON RE-RUN`",
        "The inventory is 439 nominal snapshots over 32 route identifiers",
        "`NOT YET CONSTRUCTIBLE`",
        "VC-R1 to VC-R6",
        "every registered route and both deep destinations",
        "`BLOCKED` until §12.1 is implemented, never `NOT APPLICABLE`",
        "the blocked mobile journey included",
    ):
        assert phrase in UIUX_FLAT, phrase
    assert "401 nominal snapshots" not in UIUX_FLAT
    assert "worst availability badge" not in UIUX_FLAT


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
    assert rules == {"VC-R1", "VC-R2", "VC-R3", "VC-R4", "VC-R5", "VC-R6"}
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
    assert total == 439
    assert "Nominal total: 76 + 26 × 12 + 2 × 18 + 2 × 6 + 3 = 439 snapshots" in ADR_FLAT  # noqa: RUF001
    assert "of which nine exist today" in ADR_FLAT


def test_the_inventory_is_derived_from_the_axes_the_code_exposes() -> None:
    """The review re-derived the rows from `scope.ts`, `adapter.ts` and `page.tsx`.

    The `changes` variants follow the scenario and not the mode, so they exist in both modes;
    a deep destination has three renderings under VC-I1; and the M expanded state has both
    scenarios and both modes. Each is asserted against the code that makes it so.
    """
    scope = (APP / "src" / "lib" / "scope.ts").read_text(encoding="utf-8")
    assert (
        'export const CHANGE_VARIANTS = ["auto", "valid", "none", "no-baseline", "degraded"]'
        in scope
    )
    assert 'withVariants={scope.scenario === "demo"}' in PAGE_TEXT
    rows = {row[0]: row for row in table_rows(VC_SPAN)}
    root = rows["`root`"]
    assert "in both modes" in root[4] and "+8" in root[4]
    assert root[6].endswith("= **76** |") or root[6].endswith("= **76**")
    for detail in ("`portfolio-trades-detail`", "`signals-candidates-detail`"):
        assert rows[detail][2].startswith("**3 — VC-I1**"), detail
        assert "VC-R4" in rows[detail][2]
        assert rows[detail][6] == "**18**"
    adapter = (APP / "src" / "data" / "fixtures" / "adapter.ts").read_text(encoding="utf-8")
    assert 'producer === "NOT_IMPLEMENTED_FOR_SCOPE" || trade === undefined' in adapter
    assert "`demo-trade-arb-0001`" in ADR_TEXT and "`demo-candidate-0001`" in ADR_TEXT
    assert "`vc-absent-identifier`" in ADR_TEXT


def test_every_url_axis_of_the_scope_is_disposed_of() -> None:
    """`scope.ts` carries six URL axes; VC-I2 must say what happens to each of them."""
    scope = (APP / "src" / "lib" / "scope.ts").read_text(encoding="utf-8")
    for key in ("mode", "env", "scenario", "period", "gran", "changes"):
        assert f'read("{key}")' in scope, key
    vc_i2 = next(
        row for row in table_rows(section(ADR_TEXT, "### 4.1", "### 4.2")) if "VC-I2" in row[0]
    )
    for phrase in (
        "`env`",
        "`period`",
        "`gran`",
        "held at their defaults",
        "NOT YET CONSTRUCTIBLE",
    ):
        assert phrase in vc_i2[2], phrase


def test_a_cited_inapplicability_is_coverage_and_an_unconstructible_state_bars_completion() -> None:
    closure = flatten(section(ADR_TEXT, "**What closes the row, exactly.**", "## 5."))
    assert "a cited inapplicability is coverage" in closure
    assert "no combination is `NOT YET CONSTRUCTIBLE`" in closure
    assert "Only the first permits completion" in ADR_FLAT


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
    assert len(list(baseline_dir.rglob("*.png"))) == 9 + len(EXPANDED_ROWS)


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
    assert (
        "While PB-Q reads `DEFERRED — requires a read-model boundary`, the §15 performance row "
        "can read at most `PARTIAL`"
    ) in ADR_FLAT


def test_pb1_ends_at_the_route_and_not_at_the_shell() -> None:
    """The shell's freshness indicator is fed by the executive-overview read on every route."""
    shell = (APP / "src" / "components" / "shell" / "app-shell.tsx").read_text(encoding="utf-8")
    assert "const overview = useExecutiveOverview(scope);" in shell
    assert "<FreshnessIndicator" in shell
    marks = table_rows(section(ADR_TEXT, "#### 3.3.1", "#### 3.3.2"))
    assert [row[0].strip("`") for row in marks] == [
        "/",
        "/portfolio/trades",
        "/portfolio/performance",
        "/governance/qualification",
        "/system/alerts",
        "/strategy/performance",
        "/portfolio/trades/demo-trade-arb-0001",
    ]
    for route, marker in (
        ("/portfolio/trades", "trades-panel"),
        ("/portfolio/performance", "performance-curves"),
        ("/system/alerts", "alert-panel"),
        ("/strategy/performance", "strategy-modules"),
    ):
        row = next(r for r in marks if r[0].strip("`") == route)
        assert f"`{marker}`" in row[1], route
        page = APP / "src" / "app" / route.lstrip("/") / "page.tsx"
        assert f'testId="{marker}"' in page.read_text(encoding="utf-8"), marker
    assert "Not the shell's freshness indicator" in ADR_FLAT
    assert "does not exclude the runner's latency" in ADR_FLAT


def test_a_passing_rerun_never_erases_a_failure_and_zero_stays_valid_elsewhere() -> None:
    assert "PASS — ON RE-RUN" in ADR_FLAT
    assert "never as a clean pass" in ADR_FLAT
    assert "changes no contract semantics" in ADR_FLAT
    assert "The read-model validity rules (`contracts/validity.ts`) are untouched" in ADR_FLAT


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


def test_the_journey_count_is_ten_and_the_mobile_journey_is_blocked_not_inapplicable() -> None:
    assert "ten journeys get the full protocol" in flatten(SR_SPAN)
    assert "eight journeys" not in flatten(SR_SPAN).replace('read "eight journeys"', "")
    j8 = next(row for row in table_rows(section(SR_SPAN, "### 5.3", "### 5.4")) if "J8" in row[0])
    assert "BLOCKED — M NOT IMPLEMENTED" in j8[1]
    assert "NOT APPLICABLE — M NOT IMPLEMENTED" not in ADR_TEXT
    closure = next(
        row for row in table_rows(section(SR_SPAN, "### 5.6", "### 5.7")) if "closure" in row[0]
    )
    assert "J8 included" in closure[1]
    assert "ASSESSED — PARTIAL — J8 BLOCKED ON M" in closure[1]


def test_the_state_journey_respects_value_bearing_states() -> None:
    validity = (APP / "src" / "contracts" / "validity.ts").read_text(encoding="utf-8")
    assert '"AVAILABLE",\n  "STALE",\n  "PARTIAL",\n  "EMPTY_VERIFIED",' in validity
    j5 = next(row for row in table_rows(section(SR_SPAN, "### 5.3", "### 5.4")) if "J5" in row[0])
    for state in ("`AVAILABLE`", "`STALE`", "`PARTIAL`", "`EMPTY_VERIFIED`"):
        assert state in j5[1], state
    assert "hear that none reads as a value" not in j5[1]


def test_the_structural_pass_covers_the_deep_destinations_too() -> None:
    sr_a = next(
        row for row in table_rows(section(SR_SPAN, "### 5.3", "### 5.4")) if "SR-A" in row[0]
    )
    assert "each of the two deep destinations" in sr_a[1]
    assert "thirty-two route identifiers" in sr_a[1]


def test_the_disclosure_badge_rule_invents_no_precedence() -> None:
    freshness = (APP / "src" / "contracts" / "freshness.ts").read_text(encoding="utf-8")
    assert "NO PRECEDENCE POLICY IS INVENTED HERE" in freshness
    m5 = flatten(M5_SPAN)
    assert "not a precedence policy" in m5
    assert "one existing `AvailabilityBadge`" in m5
    assert "A pending read contributes nothing" in m5
    assert "worst" not in m5
    assert "every distinct provenance badge" in m5


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
        "ADR-0033: ACCEPTED / IN FORCE",
        "PR #88: MERGED",
        "PR #88 merge commit: 948dcf4e6c9a8606134adbfde067047bdb170d6e",
        "PR #88 merged at: 2026-09-10T11:55:50Z",
        "PR #88 final reviewed head: 44d90a1f57b12d7590f20d69c5ba55a4ee54c502",
        "ed1e4c54d7ac670d6eab21133a960cef7af71fc5",
        "assessor assigned: NONE - OUTSTANDING",
        # PR #89 MERGED, read from the commit objects and the live repository like every other.
        "PR #89: MERGED",
        "PR #89 merge commit: 893a33d4f129d91fbdc630b89dc445d503302105",
        "PR #89 merged at: 2026-09-10T19:36:19Z",
        "PR #89 final reviewed head: eb348dcb76163ce2e58dbc2a4ff6af6dd18c6101",
        "9ecf721763cabc43dea62dcb20056099b7718827",
        "new screenshot baselines created: 4 - THE DECISION M EXPANDED ROWS AT 390 X 844, "
        "MERGED AS PR #89",
        "decision M implementation: MERGED AS PR #89 - INDEPENDENTLY REVIEWED BEFORE MERGE",
        # ONE ROW MOVED. The review read the M8 evidence against section 12.1 and found it
        # sufficient; the synchronization reads that disposition into the record, and no other.
        "mobile executive summary - section 12: SATISFIED - EFFECTIVE ON THE MERGE OF PR #89, "
        "READ INTO THE RECORD FROM ITS INDEPENDENT REVIEW",
        "J8 - mobile summary journey: IMPLEMENTATION BLOCKER REMOVED BY PR #89 - NOT ASSESSED",
        "performance row: PARTIAL - PB-Q DEFERRED, NO PB RUN TAKEN",
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
    # The stale under-claims, and the over-claims one satisfied row invites. PR #89 merged, so
    # "in an open pull request" is stale for Decision M and "MERGED" is its truth -- and a merged
    # mobile summary still satisfies exactly one row, assesses no journey and completes nothing.
    flat = flatten(text)
    assert "ADR-0033: PROPOSED / NOT IN FORCE" not in flat
    assert "decision M implementation: NOT STARTED" not in flat
    assert "decision M implementation: IMPLEMENTED IN AN OPEN PULL REQUEST" not in flat
    assert "mobile executive summary - section 12: NOT SATISFIED" not in flat
    assert "mobile executive summary - section 12: SATISFIED - C10 ACCEPTED" not in flat
    assert "section 15 criteria satisfied: 2 OF 4" not in flat
    assert "J8 - mobile summary journey: ASSESSED" not in flat
    assert "J8 - mobile summary journey: PASSED" not in flat


def test_the_c10_and_adr_0033_sections_are_identical_in_both_status_documents() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    claude = (PROJECT_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    c10 = "### The C10 Cockpit polish and acceptance cycle — MERGED, and not an acceptance"
    adr33 = (
        "### The remaining C10 acceptance decisions, and ADR-0033 — ACCEPTED, and Decision M "
        "MERGED as PR #89"
    )
    followup = "### The C5 completion follow-up — MERGED"
    assert section(readme, c10, adr33) == section(claude, c10, adr33)
    assert section(readme, adr33, followup) == section(claude, adr33, followup)
    assert section(readme, adr33, followup).count("ACCEPTED") >= 5
    # The proposed period is kept as history, not erased.
    assert "HISTORICAL" in section(readme, adr33, followup)


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
    # And PR #88's merge, recorded the same way, with the dispositions still unmoved.
    assert "PR #88 has since MERGED, and ADR-0033 is ACCEPTED / IN FORCE" in RECORD_FLAT
    assert "948dcf4e6c9a8606134adbfde067047bdb170d6e" in RECORD_TEXT
    assert "## 13. After ADR-0033's acceptance" in RECORD_TEXT
    thirteen = section(RECORD_TEXT, "## 13. After ADR-0033's acceptance", "\n**Implemented is not")
    assert "IMPLEMENTED IN AN OPEN PULL REQUEST" in thirteen
    assert "NOT SATISFIED" in thirteen and "NOT ASSESSED" in thirteen
    assert "section 15 criteria satisfied:                    1 OF 4" in thirteen
    # Section 13 is history now, marked as such, and section 14 reads PR #89's review in.
    assert "HISTORICAL — the state as of the open pull request" in thirteen
    assert "PR #89 has since MERGED" in RECORD_FLAT
    assert "893a33d4f129d91fbdc630b89dc445d503302105" in RECORD_TEXT
    fourteen = section(
        RECORD_TEXT, "## 14. After PR #89", "\n**One satisfied row is one satisfied row"
    )
    assert "SATISFIED — effective on the merge of PR #89" in fourteen
    assert "the supported disposition of the §12 mobile row is SATISFIED" in flatten(fourteen)
    assert "section 15 criteria satisfied:                    1 OF 4" in fourteen
    assert "manual screen-reader pass:                        NOT ASSESSED" in fourteen
    assert "IMPLEMENTATION BLOCKER REMOVED BY PR #89 - NOT ASSESSED" in fourteen
    assert "PARTIAL - PB-Q DEFERRED, NO PB RUN TAKEN" in status_lines(fourteen, "performance row")
    assert "browser chunk-failure cause:                      NOT ESTABLISHED" in fourteen
    assert "original PR #84 Linux review evidence is UNAVAILABLE" in flatten(fourteen)
    # The refinement is recorded as an open pull request, not as a change to any disposition.
    assert "IN AN OPEN PULL REQUEST - PENDING OWNER ASSESSMENT AND INDEPENDENT REVIEW" in fourteen
    assert "moves no row of this record" in flatten(fourteen)


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
    "ADR-0033": "ACCEPTED / IN FORCE",
    "decision M implementation": "MERGED AS PR #89 - INDEPENDENTLY REVIEWED BEFORE MERGE",
    "mobile executive summary - section 12": (
        "SATISFIED - EFFECTIVE ON THE MERGE OF PR #89, READ INTO THE RECORD FROM ITS "
        "INDEPENDENT REVIEW"
    ),
    "J8 - mobile summary journey": "IMPLEMENTATION BLOCKER REMOVED BY PR #89 - NOT ASSESSED",
    "performance row": "PARTIAL - PB-Q DEFERRED, NO PB RUN TAKEN",
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


# ------------------------------------------------- decision M, implemented and held to the page


MOBILE_COMPONENT: Final = COMPONENTS / "mobile-summary.tsx"
MOBILE_LIB: Final = APP / "src" / "lib" / "mobile-summary.ts"
MOBILE_SPEC: Final = APP / "e2e" / "adr-0033-mobile-summary.spec.ts"
EXPANDED_SPEC: Final = APP / "e2e" / "c10-visual-regression-mobile-expanded.spec.ts"
PLAYWRIGHT_CONFIG: Final = APP / "playwright.config.ts"

#: The four Decision VC rows the M implementation adds (ADR-0033 §4.2, the `root` row), at the
#: mobile width only.
EXPANDED_ROWS: Final[tuple[str, ...]] = (
    "VC-root-demo-executive-expanded",
    "VC-root-demo-operator-expanded",
    "VC-root-project-executive-expanded",
    "VC-root-project-operator-expanded",
)

#: EVERY committed comparison, pinned by digest.
#:
#: TWO FACTS, KEPT APART. The nine C10 images were byte-identical from their creation through the
#: merge of PR #89 -- ADR-0033 required them "kept, byte-identical, under their existing names" for
#: the Decision M implementation, and this pin is how that was proved: a count cannot see a
#: regenerated image; a digest can. The Executive Overview readability refinement then re-captured
#: all thirteen deliberately, with each diff reviewed and its reason recorded in the acceptance
#: record section 14.4, and re-pinned them here -- the nine AND the four Decision M rows -- so the
#: continuing constraint is the same as it always was: a later change to any committed baseline is
#: a review item by construction, never a silent regeneration. The historical byte-identity proof
#: is recorded in the acceptance record; it is not a property of the current images.
EXISTING_BASELINE_DIGESTS: Final[dict[str, str]] = {
    "desktop-1440/availability-states-win32.png": (
        "7104097270f5ae19db6969f0fb5b85a4f694427f3577bace487d50d3926b1045"
    ),
    "desktop-1440/overview-demo-executive-win32.png": (
        "5ab0219335d99f5c308979c33b12c8971c27069f4ee45d9ab46e5383b7d413d2"
    ),
    "desktop-1440/overview-project-win32.png": (
        "96a345fe895e75fb1d7ee3ea17f9b0514ffc387e766f40b472dd3e83f0e05afc"
    ),
    "mobile-390/VC-root-demo-executive-expanded-win32.png": (
        "126b8510f2242dee4f1138b74d0d4213ef6ec0e517555b793d18edddcd024983"
    ),
    "mobile-390/VC-root-demo-operator-expanded-win32.png": (
        "f46c55a6e9b0eb4a5f873595896d70973a78f62235c6d61a3aedc6d9254c99d0"
    ),
    "mobile-390/VC-root-project-executive-expanded-win32.png": (
        "945b40b7331306cff4b1a031d4b41d3e6699627b0e1eac17c46312c9ce2d20f6"
    ),
    "mobile-390/VC-root-project-operator-expanded-win32.png": (
        "4eace0c59a23b96671be4f5cb6de8fedeef5100d34fd8a034e5668f15cc5dab3"
    ),
    "mobile-390/availability-states-win32.png": (
        "e9bb2149cb67f2d5e81282986b0b93a04a2d321b8be81ca9ee5bb6e06d84865c"
    ),
    "mobile-390/overview-demo-executive-win32.png": (
        "7010a6ade19882a3118deb14f2b9a17e12a8c0fbcf7cff7d480619b0e64c0787"
    ),
    "mobile-390/overview-project-win32.png": (
        "eb89fc1b524178ed4746e666928443bc6f29dd57755dfb144b0f2159d604b879"
    ),
    "tablet-1024/availability-states-win32.png": (
        "2cf89b10dfa9e66fc9279ce10af95f10114b366da724c86daa2157f08e89ea88"
    ),
    "tablet-1024/overview-demo-executive-win32.png": (
        "4aaf8079f2233ec3a4ce7962901767ee28363956fed739ad44c3fb84280de0ff"
    ),
    "tablet-1024/overview-project-win32.png": (
        "bf5eac222e7f99091167dc5b144abb083739fb404dac5aefb24f60cfad97646b"
    ),
}

DISCLOSURE_TAG: Final = re.compile(r'<SummaryDisclosure\s+id="([a-z-]+)"')
LABEL_ENTRY: Final = re.compile(r'"([a-z-]+)": "([^"]+)",')


def test_every_deferred_section_of_the_m3_table_has_a_disclosure_with_its_accepted_label() -> None:
    """The M3 table names four disclosures; the page composes exactly those four, by id."""
    ids = DISCLOSURE_TAG.findall(PAGE_TEXT)
    assert sorted(ids) == sorted(
        ["what-changed", "performance-overview", "supporting-context", "response-evidence"]
    ), ids
    component = MOBILE_COMPONENT.read_text(encoding="utf-8")
    labels = dict(LABEL_ENTRY.findall(section(component, "SUMMARY_DISCLOSURE_LABEL", "};")))
    assert labels == {
        "what-changed": "What changed — details",
        "performance-overview": "Performance overview",
        "supporting-context": "Supporting context",
        "response-evidence": "Response evidence",
    }
    for label in labels.values():
        assert f"`{label}`" in M5_SPAN, f"{label} is not the label M5 fixes"
        assert re.search(r"[0-9]", label) is None, "a label is never a number"


def test_the_deferred_ids_of_the_m3_table_are_inside_the_disclosures() -> None:
    """Each id the M3 table defers sits inside the disclosure the table names, in the source."""
    inside: dict[str, str] = {}
    for match in re.finditer(
        r"<SummaryDisclosure\s+id=\"([a-z-]+)\"(.*?)</SummaryDisclosure>", PAGE_TEXT, re.S
    ):
        inside[match.group(1)] = match.group(2)
    assert set(inside) == {
        "what-changed",
        "performance-overview",
        "supporting-context",
        "response-evidence",
    }
    assert "<WhatChangedPanel" in inside["what-changed"]
    assert "<PerformanceOverview" in inside["performance-overview"]
    for identifier in ("tile-open-gates", "tile-exposure", "tile-last-runs"):
        assert f'data-testid="{identifier}"' in inside["supporting-context"], identifier
    assert "Response evidence fields" in inside["response-evidence"]
    # And the summary set is NOT inside any disclosure.
    for identifier in (
        "tile-strategy-capital",
        "answer-performance",
        "answer-risk",
        "answer-health",
        "answer-changed",
        "answer-attention",
    ):
        assert not any(f'testId="{identifier}"' in body for body in inside.values()), identifier
    assert not any("<AttentionPanel" in body for body in inside.values())
    assert not any("Why these tiles are empty" in body for body in inside.values())


def test_the_breakpoint_is_a_viewport_rule_at_640_pixels_on_the_landing_page_only() -> None:
    lib = MOBILE_LIB.read_text(encoding="utf-8")
    assert "export const SUMMARY_BREAKPOINT_PX = 640;" in lib
    assert "(width < ${SUMMARY_BREAKPOINT_PX}px)" in lib
    component = MOBILE_COMPONENT.read_text(encoding="utf-8")
    assert "window.matchMedia(SUMMARY_MEDIA_QUERY)" in component
    assert "useSyncExternalStore" in component
    # No other route composes the disclosure: `/` only (M1).
    pages = [
        path
        for path in (APP / "src" / "app").rglob("page.tsx")
        if "SummaryDisclosure" in path.read_text(encoding="utf-8")
    ]
    assert [path.relative_to(APP / "src" / "app").as_posix() for path in pages] == ["page.tsx"]


def test_the_badge_rule_is_the_vocabulary_order_and_invents_no_precedence() -> None:
    lib = MOBILE_LIB.read_text(encoding="utf-8")
    assert "AVAILABILITY_STATES.filter((state) => present.has(state))" in lib
    assert "DATA_PROVENANCES.filter((provenance) => present.has(provenance))" in lib
    assert "not a precedence policy" in " ".join(lib.replace(" * ", " ").split())
    for forbidden in ("worst", "severity", "priority", "rank"):
        assert (
            re.search(
                rf"\b{forbidden}\b", lib.lower().replace("asserts nothing about severity", "")
            )
            is None
        ), forbidden


def test_the_m8_obligations_each_have_a_test_and_the_spec_runs_in_all_six_projects() -> None:
    spec = MOBILE_SPEC.read_text(encoding="utf-8")
    for obligation in (
        "M8.1",
        "M8.2",
        "M8.3",
        "M8.4",
        "M8.5",
        "M8.6",
        "M8.7",
        "M8.8",
        "M8.9",
        "M8.10",
    ):
        assert re.search(rf"test\(\s*[`\"]{re.escape(obligation)} —", spec), obligation
    config = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")
    assert "const MOBILE_SUMMARY = /adr-0033-mobile-summary\\.spec\\.ts/;" in config
    assert config.count("testMatch: [REFERENCE_VIEWPORTS, MOBILE_SUMMARY]") == 3
    # The original three projects run it by default: they ignore only the named files.
    assert "testIgnore: [REFERENCE_VIEWPORTS, MOBILE_EXPANDED_BASELINE]" in config
    assert "MOBILE_SUMMARY" not in section(config, 'name: "desktop-1440"', 'name: "desktop-1920"')
    # No skip, no early return: the spec asserts the other half of the requirement instead.
    assert "test.skip" not in spec and "test.fixme" not in spec and "test.fail" not in spec


def test_the_four_expanded_rows_exist_at_mobile_only_and_every_baseline_is_digest_pinned() -> None:
    import hashlib

    baseline_dir = APP / "e2e" / "visual-baseline"
    for name in EXPANDED_ROWS:
        assert (baseline_dir / "mobile-390" / f"{name}-win32.png").is_file(), name
        for other in ("desktop-1440", "tablet-1024"):
            assert not (baseline_dir / other / f"{name}-win32.png").exists(), (name, other)
    for relative, digest in EXISTING_BASELINE_DIGESTS.items():
        actual = hashlib.sha256((baseline_dir / relative).read_bytes()).hexdigest()
        assert actual == digest, f"{relative} changed: {actual}"
    spec = EXPANDED_SPEC.read_text(encoding="utf-8")
    assert (
        "const STRICT = { threshold: 0, maxDiffPixels: 0, maxDiffPixelRatio: 0 } as const;" in spec
    )
    assert "fullPage: true" in spec
    assert (
        "mask"
        not in spec.replace("nothing masked", "")
        .replace("NOTHING MASKED", "")
        .replace("No masking", "")
        .lower()
    )
    for name in EXPANDED_ROWS:
        assert f'"{name}"' in spec, name
    config = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")
    assert "MOBILE_EXPANDED_BASELINE" in section(
        config, 'name: "desktop-1440"', 'name: "mobile-390"'
    )
    assert "MOBILE_EXPANDED_BASELINE" not in section(
        config, 'name: "mobile-390"', 'name: "desktop-1920"'
    )


def test_the_digest_pin_would_see_a_regenerated_image() -> None:
    """The negative control: a digest of different bytes is not the pinned digest."""
    import hashlib

    relative, digest = next(iter(EXISTING_BASELINE_DIGESTS.items()))
    original = (APP / "e2e" / "visual-baseline" / relative).read_bytes()
    assert hashlib.sha256(original + b"\x00").hexdigest() != digest
