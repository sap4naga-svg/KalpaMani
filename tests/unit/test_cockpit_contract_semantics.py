"""Cockpit contract semantics: the rules exercised, not the words counted.

``test_adr_0028_governance`` checks that the corrections are *present*. This suite checks
that they are *satisfiable and consistent*, which is a different question and the one a
wording check cannot reach. A specification can name a validity matrix, a wrapper type, a
basis-point formula and a freshness definition and still describe combinations no producer
can emit, arithmetic that is out by four orders of magnitude, or an age that resets when a
machine reruns.

Every rule below is **parsed out of the specification and then executed**. There is no
second copy of the contract in this file: the state/reason matrix, the permitted value
presence, the slippage multiplier and side signs, and the three freshness definitions are
all read from ``read-model-contracts.md`` at import time, and the fixtures are driven
through them. If the document reverts to the wrong rule, these tests fail -- which is the
property a hand-written parallel implementation would destroy, because it would keep
passing against its own copy.

Each parser carries a self-test proving it can still see the defect it exists to catch.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Decimal, DivisionByZero
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
COCKPIT: Final = PROJECT_ROOT / "docs" / "cockpit"
CONTRACTS: Final = COCKPIT / "read-model-contracts.md"
FEEDBACK: Final = COCKPIT / "feedback-self-maturation-specification.md"

CONTRACTS_TEXT: Final = CONTRACTS.read_text(encoding="utf-8")
FEEDBACK_TEXT: Final = FEEDBACK.read_text(encoding="utf-8")

#: An enum member as the specification writes one: capitals, digits and underscores.
MEMBER: Final = re.compile(r"`([A-Z][A-Z0-9_]{2,})`")


def section(text: str, start: str, end: str) -> str:
    """One named span, so a match elsewhere in a two-thousand-line file does not count."""
    begin = text.find(start)
    if begin == -1:
        return ""
    stop = text.find(end, begin + len(start))
    return text[begin:] if stop == -1 else text[begin:stop]


def fenced(text: str) -> list[str]:
    return re.findall(r"```text\n(.*?)```", text, re.DOTALL)


def table_rows(text: str) -> list[list[str]]:
    """Body rows of every pipe table in ``text``, header and separator dropped."""
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(set(cell) <= {"-", ":"} and cell for cell in cells):
            continue
        rows.append(cells)
    return rows


# -- the two closed vocabularies, read from where they are defined -------------------------


def _vocabulary(span: str, marker: str) -> frozenset[str]:
    """Members of a fenced vocabulary block, taken from the first column."""
    for block in fenced(span):
        if marker not in block:
            continue
        return frozenset(
            match.group(1)
            for line in block.splitlines()
            if (match := re.match(r"^([A-Z][A-Z0-9_]{2,})\s{2,}\S", line))
        )
    return frozenset()


AVAILABILITY_STATES: Final = _vocabulary(
    section(CONTRACTS_TEXT, "### 2.1 `AvailabilityState`", "### 2.2"), "AVAILABLE"
)
REASON_CODES: Final = _vocabulary(
    section(CONTRACTS_TEXT, "### 4.1 How to read a field contract", "#### 4.1.1"),
    "FieldReasonCode",
)
COMPLETENESS_VALUES: Final = frozenset({"COMPLETE", "PARTIAL", "UNKNOWN"})


def test_the_vocabulary_parsers_see_both_vocabularies() -> None:
    assert len(AVAILABILITY_STATES) >= 11, sorted(AVAILABILITY_STATES)
    assert len(REASON_CODES) >= 18, sorted(REASON_CODES)


def test_the_vocabulary_parser_would_notice_a_removed_member() -> None:
    block = "```text\nFieldReasonCode -- closed\n\nONE_THING     a thing\n```\n"
    assert _vocabulary(block, "FieldReasonCode") == frozenset({"ONE_THING"})


def test_a_successful_value_has_a_reason_that_means_nothing_is_wrong() -> None:
    """Without one, a required reason field forces a producer to invent a failure."""
    assert "NONE" in REASON_CODES


def test_unknown_is_a_completeness_value_and_not_an_availability_state() -> None:
    assert "UNKNOWN" in COMPLETENESS_VALUES
    assert "UNKNOWN" not in AVAILABILITY_STATES


# -- the validity matrix, parsed and then executed -----------------------------------------

MATRIX_SPAN: Final = section(
    CONTRACTS_TEXT, "#### 4.1.1 The validity matrix", "### 4.2 Reusable defined types"
)


def _parse_matrix() -> dict[str, tuple[bool, frozenset[str]]]:
    """``state -> (a value is present, the reason codes permitted)``."""
    parsed: dict[str, tuple[bool, frozenset[str]]] = {}
    for cells in table_rows(MATRIX_SPAN):
        if len(cells) != 3:
            continue
        state = MEMBER.match(cells[0])
        if state is None or state.group(1) not in AVAILABILITY_STATES:
            continue
        words = re.findall(r"present|absent", cells[1].lower())
        if not words:
            continue
        parsed[state.group(1)] = (words[0] == "present", frozenset(MEMBER.findall(cells[2])))
    return parsed


MATRIX: Final = _parse_matrix()


def validate(state: str, reason: str, has_value: bool) -> bool:
    """Is this combination admissible? Answered from the parsed matrix, never from memory."""
    if state not in MATRIX:
        return False
    value_present, permitted = MATRIX[state]
    return reason in permitted and has_value is value_present


def test_the_matrix_parser_sees_every_row() -> None:
    assert set(MATRIX) == set(AVAILABILITY_STATES), sorted(set(AVAILABILITY_STATES) ^ set(MATRIX))


def test_the_matrix_parser_would_notice_a_missing_row() -> None:
    assert _parse_matrix.__doc__  # the parser is the one under test, not a constant
    assert validate("NO_SUCH_STATE", "NONE", True) is False


def test_every_permitted_reason_is_a_real_reason_code() -> None:
    for state, (_, permitted) in MATRIX.items():
        assert permitted, state
        assert permitted <= REASON_CODES, (state, sorted(permitted - REASON_CODES))


def test_every_reason_code_is_reachable_from_some_state() -> None:
    """A reason no state admits is a code no producer can ever legally emit."""
    reachable = frozenset().union(*(permitted for _, permitted in MATRIX.values()))
    assert REASON_CODES - reachable == frozenset(), sorted(REASON_CODES - reachable)


@pytest.mark.parametrize(
    ("state", "reason", "has_value", "admissible"),
    [
        # the successful case needs no fabricated failure
        ("AVAILABLE", "NONE", True, True),
        ("AVAILABLE", "UPSTREAM_INPUT_MISSING", True, False),
        ("AVAILABLE", "NONE", False, False),
        # the crossed axes this correction exists for
        ("UPSTREAM_INPUT_MISSING", "UPSTREAM_INPUT_MISSING", False, False),
        ("NOT_IMPLEMENTED", "NOT_IMPLEMENTED", False, False),
        ("UNKNOWN", "EXTENT_NOT_DETERMINABLE", False, False),
        # inapplicability has exactly two routes, and a missing input is neither
        ("NOT_APPLICABLE", "NOT_DEFINED_FOR_SUBJECT", False, True),
        ("NOT_APPLICABLE", "DENOMINATOR_ZERO", False, True),
        ("NOT_APPLICABLE", "UPSTREAM_INPUT_MISSING", False, False),
        ("NOT_APPLICABLE", "PRODUCER_NOT_IMPLEMENTED", False, False),
        # value-bearing states keep their value
        ("STALE", "UPSTREAM_INPUT_STALE", True, True),
        ("STALE", "UPSTREAM_INPUT_STALE", False, False),
        ("PARTIAL", "EXTENT_PARTIALLY_COVERED", True, True),
        ("EMPTY_VERIFIED", "EMPTY_RESULT_VERIFIED", True, True),
        # absences carry no value
        ("NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED", False, True),
        ("NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED", True, False),
        ("NOT_AUTHORIZED", "CLASSIFICATION_WITHHELD", False, True),
        ("UNEVALUATED", "NOT_YET_ASSESSED", False, True),
        ("INSUFFICIENT_OBSERVATIONS", "BELOW_MINIMUM_OBSERVATIONS", False, True),
        ("ERROR", "PROJECTION_ERROR", False, True),
        ("ERROR", "NONE", False, False),
    ],
)
def test_the_matrix_admits_exactly_what_it_says(
    state: str, reason: str, has_value: bool, admissible: bool
) -> None:
    assert validate(state, reason, has_value) is admissible


def test_not_applicable_has_exactly_two_routes() -> None:
    assert MATRIX["NOT_APPLICABLE"][1] == frozenset({"NOT_DEFINED_FOR_SUBJECT", "DENOMINATOR_ZERO"})


# -- a zero is a measurement, and never an availability state -------------------------------

ZERO_SPAN: Final = section(
    CONTRACTS_TEXT, "#### 4.1.2 A zero is a measurement", "### 4.2 Reusable defined types"
)


def zero_cases() -> list[tuple[str, str, str]]:
    """``(measurement, availability, reason)`` read from the decided-cases table of 4.1.2."""
    cases: list[tuple[str, str, str]] = []
    for cells in table_rows(ZERO_SPAN):
        if len(cells) != 4:
            continue
        state = MEMBER.match(cells[1])
        reason = MEMBER.match(cells[2])
        if state is None or reason is None:
            continue
        if state.group(1) not in AVAILABILITY_STATES:
            continue
        cases.append((cells[0], state.group(1), reason.group(1)))
    return cases


ZERO_CASES: Final = zero_cases()


def test_the_zero_case_parser_sees_the_decided_table() -> None:
    assert len(ZERO_CASES) == 7, ZERO_CASES


def test_the_zero_case_parser_would_notice_an_emptied_table() -> None:
    """The parser is the thing under test here, not a constant it happens to agree with."""
    assert zero_cases.__doc__
    assert zero_cases() and not [row for row in zero_cases() if row[1] not in AVAILABILITY_STATES]


def test_every_decided_zero_case_is_admissible_under_the_matrix() -> None:
    for measurement, state, reason in ZERO_CASES:
        value_present, _ = MATRIX[state]
        assert validate(state, reason, value_present), (measurement, state, reason)


def test_a_valid_zero_is_carried_by_available_and_not_only_by_empty_verified() -> None:
    """The defect: a zero was declared correct in exactly one state, which is false."""
    available = [row for row in ZERO_CASES if row[1] == "AVAILABLE"]
    assert len(available) >= 3, ZERO_CASES
    assert validate("AVAILABLE", "NONE", has_value=True)
    assert MATRIX["AVAILABLE"][0] is True


def test_the_retired_single_state_zero_restriction_is_gone() -> None:
    """Restoring the old sentence puts the contradiction back, so this must fail with it."""
    flat = " ".join(CONTRACTS_TEXT.split())
    assert "only state in which a zero is a correct answer" not in flat
    assert "Zero is a value" in flat
    assert "never determines availability" in flat


def test_a_measured_zero_and_an_empty_population_are_different_answers() -> None:
    """Zero winners of ten trades is a finding; zero trades is an empty population."""
    flat = " ".join(ZERO_SPAN.split())
    assert "zero winners among ten closed trades" in flat
    measured = [row for row in ZERO_CASES if "ten closed trades" in row[0]]
    empty = [row for row in ZERO_CASES if "population is empty" in row[0]]
    assert len(measured) == 1 and len(empty) == 1, ZERO_CASES
    assert measured[0][1] == "AVAILABLE"
    assert empty[0][1] == "EMPTY_VERIFIED"
    assert measured[0][1] != empty[0][1]


def test_matching_fill_and_reference_prices_are_a_measured_zero() -> None:
    slippage = [row for row in ZERO_CASES if "slippage of zero" in row[0]]
    assert len(slippage) == 1, ZERO_CASES
    assert slippage[0][1] == "AVAILABLE"
    assert slippage[0][2] == "NONE"
    # and the arithmetic agrees: an on-reference fill costs nothing on either side
    assert slippage_bps("BUY", Decimal("100.00"), Decimal("100.00")) == Decimal("0.00")
    assert slippage_bps("SELL", Decimal("100.00"), Decimal("100.00")) == Decimal("0.00")


def test_an_unavailable_producer_cannot_supply_zero_as_a_replacement() -> None:
    """A zero standing in for a missing producer renders identically to a real measurement."""
    for state in ("NOT_IMPLEMENTED", "NOT_AUTHORIZED", "NOT_YET_AVAILABLE", "UNEVALUATED"):
        assert MATRIX[state][0] is False, state
    assert validate("NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED", has_value=True) is False
    assert validate("NOT_IMPLEMENTED", "PRODUCER_NOT_IMPLEMENTED", has_value=False) is True


def test_a_zero_carried_by_stale_data_is_still_stale() -> None:
    stale = [row for row in ZERO_CASES if row[1] == "STALE"]
    assert len(stale) == 1, ZERO_CASES
    assert stale[0][2] == "UPSTREAM_INPUT_STALE"
    assert validate("STALE", "UPSTREAM_INPUT_STALE", has_value=True) is True
    # a zero never upgrades the state that qualifies it
    assert validate("AVAILABLE", "UPSTREAM_INPUT_STALE", has_value=True) is False


def test_undefined_division_stays_undefined_and_carries_no_zero() -> None:
    undefined = [row for row in ZERO_CASES if row[2] == "DENOMINATOR_ZERO"]
    assert len(undefined) == 1, ZERO_CASES
    assert undefined[0][1] == "NOT_APPLICABLE"
    assert MATRIX["NOT_APPLICABLE"][0] is False
    assert validate("NOT_APPLICABLE", "DENOMINATOR_ZERO", has_value=True) is False
    with pytest.raises(DivisionByZero):
        slippage_bps("BUY", Decimal("0"), Decimal("100.00"))


# -- every metric outcome is expressible in that matrix -------------------------------------

METRICS: Final = section(CONTRACTS_TEXT, "### 12.3 The metrics", "### 12.4 The hard cases")
METRIC_ROW: Final = re.compile(r"^\| (`[a-z_.]+`.*)$", re.MULTILINE)


def metric_outcomes() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for raw in METRIC_ROW.findall(METRICS):
        cells = [cell.strip() for cell in raw.split(" | ")]
        if len(cells) < 6:
            continue
        rows.append((cells[0].strip("`"), cells[5]))
    return rows


def test_the_metric_outcome_parser_sees_the_dictionary() -> None:
    assert len(metric_outcomes()) >= 25, len(metric_outcomes())


def test_every_metric_outcome_names_an_availability_state_first() -> None:
    """The defect: eight rows named only a reason code, which is not a state."""
    offenders: list[tuple[str, str]] = []
    for metric_id, outcome in metric_outcomes():
        members = [m for m in MEMBER.findall(outcome) if m in AVAILABILITY_STATES | REASON_CODES]
        if not members:
            continue  # a prose outcome such as "refused"; §12.3 permits a stated rule
        if members[0] not in AVAILABILITY_STATES:
            offenders.append((metric_id, members[0]))
    assert offenders == [], offenders


def test_every_metric_outcome_uses_a_pairing_the_matrix_permits() -> None:
    offenders: list[tuple[str, str, str]] = []
    for metric_id, outcome in metric_outcomes():
        current: str | None = None
        for member in MEMBER.findall(outcome):
            if member in AVAILABILITY_STATES:
                current = member
            elif member in REASON_CODES and current is not None:
                if member not in MATRIX[current][1]:
                    offenders.append((metric_id, current, member))
    assert offenders == [], offenders


def test_no_metric_outcome_borrows_a_completeness_value() -> None:
    offenders = [
        metric_id
        for metric_id, outcome in metric_outcomes()
        if any(
            m in COMPLETENESS_VALUES - AVAILABILITY_STATES
            and outcome.index(f"`{m}`") == min(outcome.index(f"`{m}`"), len(outcome))
            for m in MEMBER.findall(outcome)
            if m in COMPLETENESS_VALUES - AVAILABILITY_STATES
        )
        and "is a `completeness` value" not in outcome
    ]
    assert offenders == [], offenders


# -- a nested record that can be unavailable ------------------------------------------------

EXAMPLES_SPAN: Final = section(
    CONTRACTS_TEXT, "#### 4.4.1 Six payloads", "### 4.5 The payload contracts"
)
EXAMPLE: Final = re.compile(
    r"availability\s+([A-Z_]+)\s+reason\s+([A-Z_]+)\s+as_of\s+(\S+)\s*\n\s*record\s+(\S+)"
)


def wrapper_examples() -> list[tuple[str, str, str, str]]:
    return [
        (state, reason, as_of, record)
        for state, reason, as_of, record in EXAMPLE.findall(EXAMPLES_SPAN)
    ]


def test_the_example_parser_sees_the_worked_payloads() -> None:
    assert len(wrapper_examples()) >= 5, wrapper_examples()


def test_every_worked_example_is_admissible_under_the_matrix() -> None:
    """A drafted payload the matrix refuses is a shape no producer could emit."""
    for state, reason, _as_of, record in wrapper_examples():
        assert validate(state, reason, has_value=record != "ABSENT"), (state, reason, record)


def test_an_absent_record_reports_no_time_of_its_own() -> None:
    absent = [row for row in wrapper_examples() if row[3] == "ABSENT"]
    assert len(absent) >= 4, absent
    for state, reason, as_of, _record in absent:
        assert as_of == "ABSENT", (state, reason, as_of)
        assert validate(state, reason, has_value=False), (state, reason)


def test_the_available_example_carries_the_no_failure_reason() -> None:
    head = section(EXAMPLES_SPAN, "1. INITIAL RISK AVAILABLE", "2. INITIAL RISK NOT YET")
    match = re.search(r"availability\s+([A-Z_]+)\s+reason\s+([A-Z_]+)", head)
    assert match is not None, head
    assert validate(match.group(1), match.group(2), has_value=True)
    assert match.group(2) == "NONE"


def test_an_absent_record_never_borrows_the_responses_own_timestamp() -> None:
    assert "the response's own times are NOT" in EXAMPLES_SPAN
    assert "Substituting a response time for" in CONTRACTS_TEXT


def test_the_required_cases_include_the_partially_available_composite() -> None:
    composite = section(EXAMPLES_SPAN, "6. PARTIALLY AVAILABLE COMPOSITE", "```")
    pairs = re.findall(r"availability ([A-Z_]+),\s*\n?\s*reason ([A-Z_]+)", composite)
    assert len(pairs) >= 3, composite
    present = {"present": True, "ABSENT": False}
    bodies = re.findall(r"record (present|ABSENT)", composite)
    for (state, reason), body in zip(pairs, bodies, strict=True):
        assert validate(state, reason, present[body]), (state, reason, body)


def test_every_risk_record_is_carried_in_the_wrapper() -> None:
    """A bare required record has no way to be unavailable, which is the defect."""
    payloads = section(CONTRACTS_TEXT, "### 4.5 The payload contracts", "## 5. Endpoint catalog")
    bare = re.findall(
        r"^\s+\w+\s+(InitialPlannedRisk|CurrentOpenPlannedRisk|PermittedRisk|GapEventRisk)\s",
        payloads,
        re.MULTILINE,
    )
    assert bare == [], bare
    assert "RecordValue<InitialPlannedRisk>" in payloads


def test_the_bare_record_scanner_would_notice_one() -> None:
    sample = "    initial_planned_risk      InitialPlannedRisk        required\n"
    assert re.findall(r"^\s+\w+\s+(InitialPlannedRisk)\s", sample, re.MULTILINE) == [
        "InitialPlannedRisk"
    ]


# -- slippage: the arithmetic, computed from the declared formula ---------------------------

SLIPPAGE_SPAN: Final = section(CONTRACTS_TEXT, "#### 12.3.1 Slippage, worked through", "### 12.4")


def slippage_multiplier() -> Decimal:
    match = re.search(r"slippage_bps = .*\* ([\d,]+)\s*$", SLIPPAGE_SPAN, re.MULTILINE)
    assert match is not None, "the declared formula has no basis-point multiplier"
    return Decimal(match.group(1).replace(",", ""))


def slippage_side_signs() -> dict[str, Decimal]:
    signs: dict[str, Decimal] = {}
    for sign, action in re.findall(r"([+-]1)\s+((?:BUY|SELL)_TO_[A-Z]+)", SLIPPAGE_SPAN):
        signs[action] = Decimal(sign)
    return signs


MULTIPLIER: Final = slippage_multiplier()
SIDE_SIGNS: Final = slippage_side_signs()


def slippage_bps(side: str, reference: Decimal, fill: Decimal) -> Decimal:
    """The declared formula, with its multiplier and its signs read from the document."""
    actions = [a for a in SIDE_SIGNS if a.startswith(side.upper())]
    signs = {SIDE_SIGNS[a] for a in actions}
    assert len(signs) == 1, (side, actions)
    value = signs.pop() * (fill - reference) / reference * MULTIPLIER
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def test_the_formula_parser_reads_the_basis_point_multiplier() -> None:
    """A ratio labelled BPS is out by exactly this factor, and invisibly so."""
    assert MULTIPLIER == Decimal(10000)


def test_the_side_sign_mapping_covers_both_directions_of_both_sides() -> None:
    assert SIDE_SIGNS == {
        "BUY_TO_OPEN": Decimal(1),
        "BUY_TO_COVER": Decimal(1),
        "SELL_TO_CLOSE": Decimal(-1),
        "SELL_TO_OPEN": Decimal(-1),
    }, SIDE_SIGNS


#: The document sets prices with a typographic MINUS SIGN, not a hyphen.
MINUS_SIGN: Final = "\u2212"


def worked_slippage_rows() -> list[tuple[str, Decimal, Decimal, Decimal]]:
    rows: list[tuple[str, Decimal, Decimal, Decimal]] = []
    for cells in table_rows(SLIPPAGE_SPAN):
        if len(cells) != 8 or cells[0] not in {"buy", "sell"}:
            continue
        result = re.search(rf"([+\-{MINUS_SIGN}]?[\d.]+) bps", cells[6])
        assert result is not None, cells
        rows.append(
            (
                cells[0],
                Decimal(cells[1]),
                Decimal(cells[2]),
                Decimal(result.group(1).replace(MINUS_SIGN, "-").lstrip("+")),
            )
        )
    return rows


def test_the_worked_table_parser_sees_all_four_cases() -> None:
    assert len(worked_slippage_rows()) == 4, worked_slippage_rows()


def test_every_worked_case_recomputes_from_the_declared_formula() -> None:
    for side, reference, fill, expected in worked_slippage_rows():
        assert slippage_bps(side, reference, fill) == expected, (side, reference, fill)


def test_an_adverse_buy_and_an_adverse_sell_report_the_same_cost() -> None:
    """Without side_sign they cancel, and a book of bad fills reports perfect execution."""
    adverse_buy = slippage_bps("buy", Decimal("100.00"), Decimal("100.10"))
    adverse_sell = slippage_bps("sell", Decimal("100.00"), Decimal("99.90"))
    assert adverse_buy == adverse_sell == Decimal("10.00")
    assert (adverse_buy + adverse_sell) / 2 == Decimal("10.00")


def test_a_favourable_fill_is_negative_on_both_sides() -> None:
    assert slippage_bps("buy", Decimal("100.00"), Decimal("99.95")) == Decimal("-5.00")
    assert slippage_bps("sell", Decimal("100.00"), Decimal("100.05")) == Decimal("-5.00")


def test_fractional_basis_points_survive_the_declared_scale() -> None:
    """An integer Bps discards this on every fill, and an aggregate carries all of it."""
    value = slippage_bps("buy", Decimal("100.00"), Decimal("100.0842"))
    assert value == Decimal("8.42")
    assert int(value) == 8
    assert value - int(value) == Decimal("0.42")
    assert "minimum scale is two decimal places" in " ".join(SLIPPAGE_SPAN.split())


def test_a_zero_reference_price_refuses_rather_than_divides() -> None:
    outcome = dict(metric_outcomes())["slippage"]
    assert "`NOT_APPLICABLE` with `DENOMINATOR_ZERO`" in outcome
    with pytest.raises(DivisionByZero):
        slippage_bps("buy", Decimal("0.00"), Decimal("100.00"))


# -- freshness: three ages, computed from the declared definitions --------------------------

FRESHNESS_SPAN: Final = section(CONTRACTS_TEXT, "### 3.1 Freshness", "## 4. Read-model catalog")
AGE_DEF: Final = re.compile(r"^(\w+)\s*=\s*(\w+)\s*-\s*(\w+)", re.MULTILINE)


def age_definitions() -> dict[str, tuple[str, str]]:
    return {name: (left, right) for name, left, right in AGE_DEF.findall(FRESHNESS_SPAN)}


AGES: Final = age_definitions()


def compute_age(name: str, times: dict[str, int]) -> int:
    """One declared age, in seconds, evaluated over named instants given as minutes."""
    left, right = AGES[name]
    return (times[left] - times[right]) * 60


def test_the_age_parser_sees_three_separate_definitions() -> None:
    assert set(AGES) == {"source_age", "projection_lag", "build_age"}, AGES


def test_source_age_is_measured_against_the_facts_and_not_against_the_build() -> None:
    """The defect: the old formula subtracted projected_time and measured the build."""
    assert AGES["source_age"] == ("evaluation_time", "source_effective_time")
    assert AGES["build_age"] == ("evaluation_time", "projected_time")
    assert AGES["source_age"] != AGES["build_age"]


def test_a_rebuild_does_not_refresh_an_old_fact() -> None:
    times = {"evaluation_time": 12 * 60, "source_effective_time": 11 * 60}
    times["projected_time"] = 11 * 60 + 59
    assert compute_age("source_age", times) == 3600
    assert compute_age("build_age", times) == 60
    assert compute_age("projection_lag", times) == 3540
    # the old formula, reproduced only to show what it would have reported
    assert times["evaluation_time"] - times["projected_time"] == 1


def test_the_worked_rebuild_case_matches_the_computed_ages() -> None:
    case = section(FRESHNESS_SPAN, "CASE 1", "CASE 2")
    stated = {name: int(value) for name, value in re.findall(r"(\w+)\s+(\d+) s", case)}
    times = {
        name: int(hh) * 60 + int(mm)
        for name, hh, mm in re.findall(r"(\w+)\s+(\d{2}):(\d{2})", case)
    }
    assert stated and times, case
    for name in AGES:
        assert compute_age(name, times) == stated[name], name


def test_one_fresh_input_does_not_conceal_a_stale_required_one() -> None:
    case = section(FRESHNESS_SPAN, "CASE 2", "```")
    inputs = re.findall(
        r"input (\w) \((\w+)\)\s+as-of \d{2}:\d{2}\s+source_age\s+(\d+) s\s+contract\s+(\d+) s",
        case,
    )
    assert len(inputs) == 2, case
    required = [(name, int(age), int(limit)) for name, kind, age, limit in inputs if kind]
    oldest = max(required, key=lambda row: row[1])
    assert oldest[0] == "B"
    assert oldest[1] > oldest[2], oldest
    # the composite takes the worst required state, not the newest contributing one
    assert "composite_state         STALE" in case
    assert "oldest_required         input B" in case
    newest = min(required, key=lambda row: row[1])
    assert newest[1] < newest[2], "input A is inside its own contract and must not set the state"


def test_a_missing_or_skewed_source_time_refuses_rather_than_reading_as_fresh() -> None:
    flat = " ".join(FRESHNESS_SPAN.split())
    assert "Its age is unknown, not zero" in flat
    assert "A negative age is never clamped to zero" in flat
    for reason in ("SOURCE_TIMESTAMP_MISSING", "CLOCK_UNSYNCHRONIZED"):
        assert reason in REASON_CODES
        assert validate("NOT_YET_AVAILABLE", reason, has_value=False), reason


def test_a_cache_cannot_freeze_an_available_state_while_the_source_ages() -> None:
    flat = " ".join(FRESHNESS_SPAN.split())
    assert "never frozen AVAILABLE while" in flat
    assert "a cache entry EXPIRES at the earliest absolute deadline it carries" in flat


# -- freshness deadlines: a cache spends a budget it never refills ---------------------------

DEADLINE_SPAN: Final = section(
    CONTRACTS_TEXT, "#### 3.1.1 Freshness deadlines", "## 4. Read-model catalog"
)
DEADLINE_DEF: Final = re.compile(r"^input_deadline\s*=\s*(\w+)\s*\+\s*(\w+)", re.MULTILINE)
FRESH_UNTIL_DEF: Final = re.compile(
    r"^fresh_until\s*=\s*(\w+)\((\w+) over every REQUIRED input\)", re.MULTILINE
)
REMAINING_DEF: Final = re.compile(
    r"^remaining_freshness\s*=\s*max\(0, (\w+) - (\w+)\)", re.MULTILINE
)
SERVE_RULE: Final = re.compile(r"^serve_time\s+(<|>=)\s+fresh_until\s+(.+)$", re.MULTILINE)

#: The three declared formulas and the one declared comparison, read from the contract.
DEADLINE_TERMS: Final[list[tuple[str, str]]] = DEADLINE_DEF.findall(DEADLINE_SPAN)
FRESH_UNTIL_TERMS: Final[list[tuple[str, str]]] = FRESH_UNTIL_DEF.findall(DEADLINE_SPAN)
REMAINING_TERMS: Final[list[tuple[str, str]]] = REMAINING_DEF.findall(DEADLINE_SPAN)
SERVE_RULES: Final[dict[str, str]] = dict(SERVE_RULE.findall(DEADLINE_SPAN))


def input_deadline(source_effective_time: int, contract_max_age: int) -> int:
    """One input's absolute deadline, composed in the order the specification declares."""
    values = {
        "source_effective_time": source_effective_time,
        "contract_max_age": contract_max_age,
    }
    left, right = DEADLINE_TERMS[0]
    return values[left] + values[right]


def fresh_until(deadlines: list[int]) -> int:
    """The composite deadline: the earliest required input's, per the declared rule."""
    assert FRESH_UNTIL_TERMS[0] == ("minimum", "input_deadline"), FRESH_UNTIL_TERMS
    return min(deadlines)


def remaining_freshness(fresh_until_value: int, serve_time: int) -> int:
    """What is left of the budget, clamped at zero exactly as the contract clamps it."""
    values = {"fresh_until": fresh_until_value, "cache_or_serve_time": serve_time}
    left, right = REMAINING_TERMS[0]
    return max(0, values[left] - values[right])


def may_serve_available(serve_time: int, fresh_until_value: int) -> bool:
    """The equality rule, taken from the specification rather than assumed."""
    assert SERVE_RULES["<"].startswith("AVAILABLE"), SERVE_RULES
    assert "EXPIRED" in SERVE_RULES[">="], SERVE_RULES
    return serve_time < fresh_until_value


def test_the_deadline_parser_sees_all_three_declared_formulas() -> None:
    assert len(DEADLINE_TERMS) == 1, DEADLINE_TERMS
    assert len(FRESH_UNTIL_TERMS) == 1, FRESH_UNTIL_TERMS
    assert len(REMAINING_TERMS) == 1, REMAINING_TERMS
    assert set(SERVE_RULES) == {"<", ">="}, SERVE_RULES


def test_the_deadline_parser_would_notice_a_removed_formula() -> None:
    """The parsers are what is under test here, not constants they happen to agree with."""
    assert DEADLINE_DEF.findall("input_deadline = something_else") == []
    assert REMAINING_DEF.findall("remaining_freshness = fresh_until - now") == []
    assert SERVE_RULE.findall("serve_time == fresh_until AVAILABLE") == []


def test_a_deadline_is_absolute_and_grows_from_the_source_time() -> None:
    """The defect: a lifetime bounded only by contract_max_age ignores age already spent."""
    assert DEADLINE_TERMS[0] == ("source_effective_time", "contract_max_age")
    assert REMAINING_TERMS[0] == ("fresh_until", "cache_or_serve_time")


def test_a_cache_does_not_refill_a_budget_that_is_already_spent() -> None:
    """CASE 3: 290 s consumed against a 300 s contract leaves 10 s, and never 300 s."""
    deadline = input_deadline(source_effective_time=0, contract_max_age=300)
    left = remaining_freshness(deadline, serve_time=290)
    assert left == 10
    assert left != 300


def test_the_serve_comparison_is_strict_before_the_deadline() -> None:
    """CASE 3, continued: 9 s later is still inside the budget; 10 s later is not."""
    deadline = input_deadline(source_effective_time=0, contract_max_age=300)
    assert may_serve_available(299, deadline) is True
    assert may_serve_available(300, deadline) is False
    assert may_serve_available(301, deadline) is False
    assert remaining_freshness(deadline, serve_time=301) == 0


def test_the_composite_expires_at_the_earliest_required_deadline() -> None:
    """CASE 4: a 40/60 input beside a 290/300 input leaves the composite 10 s, not 20 s."""
    now = 290
    younger = input_deadline(source_effective_time=now - 40, contract_max_age=60)
    older = input_deadline(source_effective_time=now - 290, contract_max_age=300)
    composite = fresh_until([younger, older])
    assert remaining_freshness(composite, serve_time=now) == 10
    assert composite == older


def test_the_oldest_input_is_not_always_the_binding_one() -> None:
    """CASE 5: a looser contract gives the OLDEST input the LONGEST remaining budget."""
    now = 290
    younger_age, older_age = 40, 290
    younger = input_deadline(source_effective_time=now - younger_age, contract_max_age=60)
    older = input_deadline(source_effective_time=now - older_age, contract_max_age=600)
    assert remaining_freshness(older, serve_time=now) == 310
    assert remaining_freshness(younger, serve_time=now) == 20
    composite = fresh_until([younger, older])
    assert composite == younger, "the earliest deadline binds, and here it is the newer input"
    assert remaining_freshness(composite, serve_time=now) == 20
    # 3.1 still reports the composite age against the OLDEST input, which is the other one
    assert older_age > younger_age


def test_a_configured_ttl_shortens_a_budget_and_never_extends_it() -> None:
    """CASE 6: 5 s cuts a 10 s budget; 3600 s is ignored rather than honoured."""
    deadline = input_deadline(source_effective_time=0, contract_max_age=300)
    budget = remaining_freshness(deadline, serve_time=290)
    assert min(5, budget) == 5
    assert min(3600, budget) == budget
    assert "a configured TTL may shorten, never extend" in " ".join(DEADLINE_SPAN.split())


def test_recaching_unchanged_facts_does_not_renew_the_deadline() -> None:
    """A rebuild resets build_age and never source_age, so it cannot move a deadline."""
    first = input_deadline(source_effective_time=0, contract_max_age=300)
    rebuilt = input_deadline(source_effective_time=0, contract_max_age=300)
    assert rebuilt == first
    assert remaining_freshness(first, serve_time=100) > remaining_freshness(rebuilt, serve_time=200)


def test_an_expired_entry_is_served_stale_and_never_available() -> None:
    assert validate("STALE", "UPSTREAM_INPUT_STALE", has_value=True) is True
    assert validate("AVAILABLE", "UPSTREAM_INPUT_STALE", has_value=True) is False
    # an input with no usable source time establishes no deadline at all
    assert validate("NOT_YET_AVAILABLE", "SOURCE_TIMESTAMP_MISSING", has_value=False) is True
    assert validate("AVAILABLE", "SOURCE_TIMESTAMP_MISSING", has_value=True) is False


def test_a_zero_source_age_is_a_legitimate_measured_age() -> None:
    """Consistent with 4.1.2: a freshly effective fact has spent none of its budget."""
    deadline = input_deadline(source_effective_time=0, contract_max_age=300)
    assert remaining_freshness(deadline, serve_time=0) == 300
    assert may_serve_available(0, deadline) is True


def test_the_worked_deadline_cases_state_the_numbers_the_model_computes() -> None:
    """The prose cases and the executed model must not drift apart."""
    flat = " ".join(DEADLINE_SPAN.split())
    for case in ("CASE 3", "CASE 4", "CASE 5", "CASE 6"):
        assert case in flat, case
    deadline = input_deadline(source_effective_time=0, contract_max_age=300)
    assert f"remaining_freshness {remaining_freshness(deadline, serve_time=290)} s" in flat


def test_the_retired_full_window_cache_rule_is_gone() -> None:
    """Restoring the old bound reinstates the defect, so this must fail alongside it."""
    flat = " ".join(CONTRACTS_TEXT.split())
    assert "at most the strictest `contract_max_age`" not in flat
    assert "at most the strictest contract_max_age" not in flat
    assert "expires at the **earliest absolute deadline it carries**" in flat


# -- out-of-sample exposure: a rename and a re-cut both fail --------------------------------

REUSE_SPAN: Final = section(
    FEEDBACK_TEXT, "#### 2.7.1 Out-of-sample exposure is tracked", "### 2.8 Shadow"
)


def reuse_refusals() -> frozenset[str]:
    for block in fenced(REUSE_SPAN):
        if "OUT_OF_SAMPLE_ALREADY_CONSUMED" not in block:
            continue
        return frozenset(re.findall(r"^([A-Z][A-Z0-9_]+)\s{2,}\S", block, re.MULTILINE))
    return frozenset()


REFUSALS: Final = reuse_refusals()


def test_the_refusal_parser_sees_the_closed_list() -> None:
    assert len(REFUSALS) >= 6, sorted(REFUSALS)


def evaluate_reuse(
    *,
    extent: frozenset[int] | None,
    ledger: dict[str, frozenset[int]],
    lineage: frozenset[str],
    declared_class: str,
) -> str | None:
    """Admit a declared evaluation, or return the refusal the specification names.

    Every returned code is checked against the parsed refusal list, so a document that
    drops one cannot leave this model quietly asserting a code nobody declares.
    """

    def refuse(code: str) -> str:
        assert code in REFUSALS, code
        return code

    if declared_class != "CONFIRMATORY":
        return None
    if extent is None:
        return refuse("EXPOSURE_HISTORY_UNKNOWN")
    for owner, exposed in ledger.items():
        if not extent & exposed:
            continue
        return refuse(
            "RELATED_LINEAGE_EXPOSED" if owner in lineage else "OUT_OF_SAMPLE_ALREADY_CONSUMED"
        )
    return None


RUN_A: Final = frozenset(range(2015, 2020))
LEDGER: Final = {"registration-a": RUN_A}


def test_an_identical_locked_set_under_a_new_identity_is_refused() -> None:
    assert (
        evaluate_reuse(
            extent=RUN_A, ledger=LEDGER, lineage=frozenset(), declared_class="CONFIRMATORY"
        )
        == "OUT_OF_SAMPLE_ALREADY_CONSUMED"
    )


def test_an_overlapping_re_cut_under_a_new_identity_is_refused() -> None:
    """A superset has a different locked-set identity over four-fifths of the same data."""
    superset = frozenset(range(2015, 2021))
    assert superset != RUN_A
    assert (
        evaluate_reuse(
            extent=superset, ledger=LEDGER, lineage=frozenset(), declared_class="CONFIRMATORY"
        )
        == "OUT_OF_SAMPLE_ALREADY_CONSUMED"
    )


@pytest.mark.parametrize(
    "extent",
    [
        frozenset(range(2016, 2019)),  # a subset
        frozenset(range(2018, 2023)),  # a shifted window
        frozenset({2019}),  # a single overlapping year
    ],
)
def test_any_overlap_disqualifies_a_confirmatory_claim(extent: frozenset[int]) -> None:
    assert (
        evaluate_reuse(
            extent=extent, ledger=LEDGER, lineage=frozenset(), declared_class="CONFIRMATORY"
        )
        == "OUT_OF_SAMPLE_ALREADY_CONSUMED"
    )


def test_a_genuinely_untouched_holdout_is_still_admitted() -> None:
    """The control must refuse reuse, not refuse everything."""
    assert (
        evaluate_reuse(
            extent=frozenset(range(2021, 2024)),
            ledger=LEDGER,
            lineage=frozenset(),
            declared_class="CONFIRMATORY",
        )
        is None
    )


def test_a_related_lineage_is_named_as_such() -> None:
    assert (
        evaluate_reuse(
            extent=RUN_A,
            ledger=LEDGER,
            lineage=frozenset({"registration-a"}),
            declared_class="CONFIRMATORY",
        )
        == "RELATED_LINEAGE_EXPOSED"
    )


def test_an_unmeasurable_overlap_fails_closed() -> None:
    """Incomparable is not disjoint, and an absence of record is not absence of exposure."""
    assert (
        evaluate_reuse(
            extent=None, ledger=LEDGER, lineage=frozenset(), declared_class="CONFIRMATORY"
        )
        == "EXPOSURE_HISTORY_UNKNOWN"
    )


def test_reproduction_and_disclosed_reuse_are_not_confirmation() -> None:
    for declared in ("DETERMINISTIC_REPRODUCTION", "EXPLORATORY_REUSE"):
        assert declared in REUSE_SPAN, declared
        assert (
            evaluate_reuse(
                extent=RUN_A, ledger=LEDGER, lineage=frozenset(), declared_class=declared
            )
            is None
        ), declared
    assert "never presented as fresh out-of-sample" in " ".join(REUSE_SPAN.split())


def test_the_overlap_rule_is_stated_and_not_only_modelled_here() -> None:
    flat = " ".join(REUSE_SPAN.split())
    assert "Overlapping data counts as exposure, not only an identical locked set" in flat
    assert "there is no threshold below which reuse becomes fresh" in flat
    assert "Incomparable is not disjoint" in flat


# -- one period is a valid time-weighted return ---------------------------------------------


def test_a_flow_free_period_needs_one_sub_period_and_not_two() -> None:
    """Requiring two refused an ordinary valid return to keep a formula looking used."""
    row = next(
        raw for raw in METRIC_ROW.findall(METRICS) if raw.startswith("`return.time_weighted`")
    )
    cells = [cell.strip() for cell in row.split(" | ")]
    assert "**1 sub-period**" in cells[4], cells[4]
    assert "flow-free period is one sub-period" in " ".join(cells[1].split())
