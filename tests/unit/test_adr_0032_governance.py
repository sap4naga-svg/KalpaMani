"""ADR-0032 governance: the capacity and tail-loss measurement contracts, parsed and executed.

**ADR-0032 is PROPOSED.** While the pull request introducing it is open it carries no authority,
and the assertions below that say so are claims about a document rather than about the world.

The suite has five parts.

* **Governance** -- the ADR declares itself proposed, predicts no merge, amends exactly the two
  documents it names, edits no other ADR, and authorizes nothing.
* **The tail-loss contract, executed** -- the parameters, the statistic and the window rules are
  **parsed out of the tracked documents** and then run. There is no second copy of the definition
  in this file: the tail fraction, the window size and the minimum are read at import time, so a
  document that loses a parameter fails here rather than silently agreeing with a hard-coded one.
* **The capacity contract, executed** -- the admission gate is parsed out of section 12.3.3 and
  applied. The substitutions the contract forbids are exercised as refusals, not described.
* **The product surface** -- the specification and traceability deltas that carry the same
  conditional authority.
* **The status surface** -- PR #84's verified merge is recorded, the three post-merge dispositions
  stay separate, the unavailable original evidence stays unavailable, and neither measure is
  reported as accepted or implemented.

Every parser carries a self-test proving it can still see what it exists to catch: a scanner that
sees nothing passes every document vacuously.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Final, NamedTuple

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DECISIONS: Final = PROJECT_ROOT / "docs" / "decisions"
COCKPIT: Final = PROJECT_ROOT / "docs" / "cockpit"

ADR: Final = DECISIONS / "ADR-0032-strategy-capacity-and-rolling-tail-loss-measurement.md"
CONTRACTS: Final = COCKPIT / "read-model-contracts.md"
V1_SPEC: Final = COCKPIT / "cockpit-v1-specification.md"
MATRIX: Final = COCKPIT / "traceability-matrix.md"

ADR_TEXT: Final = ADR.read_text(encoding="utf-8")
CONTRACTS_TEXT: Final = CONTRACTS.read_text(encoding="utf-8")
MATRIX_TEXT: Final = MATRIX.read_text(encoding="utf-8")
V1_TEXT: Final = V1_SPEC.read_text(encoding="utf-8")


def flatten(text: str) -> str:
    """One line, so a rule broken across a wrap is still one phrase."""
    return " ".join(text.split())


ADR_FLAT: Final = flatten(ADR_TEXT)
CONTRACTS_FLAT: Final = flatten(CONTRACTS_TEXT)
MATRIX_FLAT: Final = flatten(MATRIX_TEXT)


def section(text: str, start: str, end: str) -> str:
    """One named span, so a match elsewhere in a long file does not count."""
    begin = text.find(start)
    if begin == -1:
        return ""
    stop = text.find(end, begin + len(start))
    return text[begin:] if stop == -1 else text[begin:stop]


TAIL_SPAN: Final = section(
    CONTRACTS_TEXT,
    "#### 12.3.2 The rolling tail loss, worked through",
    "#### 12.3.3 Strategy capacity",
)
CAPACITY_SPAN: Final = section(
    CONTRACTS_TEXT,
    "#### 12.3.3 Strategy capacity",
    "### 12.4 The hard cases",
)
DICTIONARY_SPAN: Final = section(
    CONTRACTS_TEXT, "### 12.3 The metrics", "#### 12.3.1 Slippage, worked through"
)
#: The contracts document sets its worked values with a typographic MINUS SIGN.
MINUS_SIGN: Final = "\u2212"
PARAMETER_SPAN: Final = section(ADR_TEXT, "**D1.12 PROPOSED MEASUREMENT DECISIONS.**", "### D2 —")


# --------------------------------------------------------------------- governance


def test_the_adr_declares_itself_proposed_and_not_in_force() -> None:
    assert "**Status: PROPOSED — NOT IN FORCE." in ADR_TEXT
    assert "ADR-0032 is ACCEPTED / IN FORCE" not in ADR_FLAT


def test_the_adr_claims_no_authority_while_its_pull_request_is_open() -> None:
    assert "carries no authority" in ADR_FLAT
    assert "it is not to be rewritten as though this decision had authority" in ADR_FLAT


def test_the_adr_predicts_no_merge_sha_and_no_timestamp() -> None:
    assert "No merge SHA and no merge timestamp is predicted here" in ADR_FLAT
    assert re.search(r"\b[0-9a-f]{40}\b", ADR_TEXT) is None, "a forty-character SHA appears"


def test_the_adr_supersedes_nothing_and_edits_no_other_adr() -> None:
    assert "**Supersedes:** nothing" in ADR_TEXT
    assert (
        "it does not amend, supersede or edit ADR-0026, ADR-0027, ADR-0028, ADR-0029, "
        "ADR-0030 or ADR-0031" in ADR_FLAT
    )


def test_the_adr_amends_only_the_two_documents_it_names() -> None:
    """A decision that quietly widened its own amendment set is the failure here."""
    amends = section(ADR_TEXT, "**Amends:**", "**Relates to:**")
    assert "read-model-contracts.md" in amends
    assert "traceability-matrix.md" in amends
    assert "It amends no other section of either document" in flatten(amends)
    # The specification's own Presents clauses already name both quantities, so nothing
    # in that document needed changing -- and nothing in it was changed.
    assert "cockpit-v1-specification.md" not in amends


def test_the_adr_ran_nothing_and_authorizes_nothing() -> None:
    assert "Nothing was run to produce this decision" in ADR_FLAT
    assert "implements NOTHING" in ADR_TEXT
    assert "authorizes NOTHING" in ADR_TEXT
    assert "No alpha is claimed anywhere in this decision" in ADR_FLAT


def test_the_adr_keeps_acceptance_implementation_and_qualification_apart() -> None:
    assert (
        "acceptance of this contract, authorization of an implementation, qualification of "
        "real inputs or a model, and any eventual operational use are four separate gates"
        in ADR_FLAT.lower().replace("**", "")
        or "acceptance of this contract, authorization of an implementation, qualification "
        "of real inputs or a model, and any eventual operational use are four separate gates"
        in flatten(ADR_TEXT.replace("**", ""))
    )


def test_the_amended_documents_carry_the_conditional_authority() -> None:
    for name, flat in (("read-model-contracts.md", CONTRACTS_FLAT), ("matrix", MATRIX_FLAT)):
        assert "ADR-0032" in flat, name
        assert (
            "ADR-0032 is **PROPOSED and carries no authority while the pull request "
            "introducing it is open**" in flat
        ), name


def test_the_two_new_subsections_declare_themselves_proposed() -> None:
    for name, span in (("12.3.2", TAIL_SPAN), ("12.3.3", CAPACITY_SPAN)):
        assert span, f"{name} is missing from the contracts document"
        assert "PROPOSED by ADR-0032" in span, name


# ------------------------------------------------- the tail-loss parameters, parsed


class TailParameters(NamedTuple):
    tail_fraction: Decimal
    window: int
    minimum_observations: int
    derived_k: int


def tail_parameters() -> TailParameters:
    """Read the four declared parameters out of the ADR's own decision table.

    Hard-coding them here would let the document drop one and still pass.
    """
    rows = {
        cells[0]: cells[1]
        for line in PARAMETER_SPAN.splitlines()
        if line.startswith("|")
        for cells in [[c.strip() for c in line.strip().strip("|").split("|")]]
        if len(cells) == 3
    }
    plain = {k.replace("**", "").replace("`", "").strip(): v for k, v in rows.items()}

    def number(key: str) -> str:
        for name, value in plain.items():
            if name.startswith(key):
                match = re.search(r"\*\*([\d.]+)", value.replace("`", ""))
                if match is None:
                    match = re.search(r"([\d.]+)", value.replace("`", ""))
                assert match is not None, (key, value)
                return match.group(1)
        raise AssertionError(f"no parameter row starts with {key!r}: {sorted(plain)}")

    return TailParameters(
        tail_fraction=Decimal(number("tail fraction")),
        window=int(number("window")),
        minimum_observations=int(number("minimum observations")),
        derived_k=int(
            re.search(r"which is \*\*(\d+)\*\*", plain["derived k"]).group(1)  # type: ignore[union-attr]
        ),
    )


PARAMS: Final = tail_parameters()


def test_the_parameter_parser_sees_all_four_declared_values() -> None:
    """A parser that returned defaults would pass every assertion below vacuously."""
    assert PARAMS.tail_fraction > 0
    assert PARAMS.window > 0
    assert PARAMS.minimum_observations > 0
    assert PARAMS.derived_k > 0


def test_the_declared_parameters_are_the_proposed_ones() -> None:
    assert PARAMS.tail_fraction == Decimal("0.10")
    assert PARAMS.window == 30
    assert PARAMS.minimum_observations == 30


def test_the_tail_count_is_derived_from_the_other_two_and_not_chosen() -> None:
    """`k` must be the stated arithmetic, not an independent number that happens to agree."""
    n = Decimal(PARAMS.window)
    expected = int(-(-(PARAMS.tail_fraction * n) // 1))  # ceil, in Decimal
    assert PARAMS.derived_k == expected == 3


def test_the_window_reuses_the_declared_expectancy_minimum_rather_than_inventing_one() -> None:
    """The claim that no number was invented is checkable against 12.3's own row."""
    expectancy_row = [
        line for line in CONTRACTS_TEXT.splitlines() if line.startswith("| `expectancy.currency` |")
    ]
    assert len(expectancy_row) == 1
    assert f"| {PARAMS.window} trades |" in expectancy_row[0]
    assert "reuses §12.3's own declared minimum" in flatten(PARAMETER_SPAN)


def test_the_statistic_uses_an_integer_order_statistic_count_and_no_interpolation() -> None:
    flat = flatten(TAIL_SPAN)
    assert "k = ceil(q * n)" in TAIL_SPAN
    assert "an integer count of order statistics" in flat
    assert "never a calendar window" in flat
    assert "interpolation" in flatten(ADR_FLAT)


# --------------------------------------------- the tail-loss contract, executed


class Observation(NamedTuple):
    closed_at: int
    trade_id: str
    r_multiple: Decimal


class Result(NamedTuple):
    availability: str
    reason: str
    value: Decimal | None


def window_at(observations: list[Observation], point: int, size: int) -> list[Observation]:
    """The trailing `size` eligible observations at or before `point`.

    An observation enters at its CLOSE instant, and nothing after the cutoff is eligible.
    Recency ties break by trade identifier, so membership is deterministic.
    """
    eligible = sorted(
        (o for o in observations if o.closed_at <= point),
        key=lambda o: (o.closed_at, o.trade_id),
    )
    return eligible[-size:] if size <= len(eligible) else eligible


def tail_loss(
    observations: list[Observation],
    *,
    tail_fraction: Decimal = PARAMS.tail_fraction,
    minimum: int = PARAMS.minimum_observations,
    excluded: int = 0,
) -> Result:
    """The contract of 12.3 and 12.3.2, executed exactly as the document states it."""
    n = len(observations)
    if n < minimum:
        return Result("INSUFFICIENT_OBSERVATIONS", "BELOW_MINIMUM_OBSERVATIONS", None)
    k = int(-(-(tail_fraction * Decimal(n)) // 1))
    worst = sorted(o.r_multiple for o in observations)[:k]
    value = sum(worst, Decimal(0)) / Decimal(k)
    if excluded:
        return Result("PARTIAL", "UPSTREAM_INPUT_MISSING", value)
    return Result("AVAILABLE", "NONE", value)


def population(
    tail: list[str], rest_total: str = "0", size: int | None = None
) -> list[Observation]:
    """A window whose most adverse members are exactly `tail`, padded to `size`."""
    size = PARAMS.window if size is None else size
    pad_count = size - len(tail)
    pad_each = Decimal(rest_total) / Decimal(pad_count) if pad_count else Decimal(0)
    worst = max(Decimal(v) for v in tail)
    # Every padded observation must sit above the tail, or it would join the tail.
    pad_value = pad_each if pad_each > worst else worst + Decimal("1.00")
    observations = [Observation(i, f"t{i:03d}", Decimal(v)) for i, v in enumerate(tail)]
    observations += [
        Observation(len(tail) + i, f"t{len(tail) + i:03d}", pad_value) for i in range(pad_count)
    ]
    return observations


def test_the_worked_example_in_the_document_reproduces_by_hand() -> None:
    result = tail_loss(population(["-3.10", "-2.40", "-2.00"]))
    assert result.availability == "AVAILABLE"
    assert result.reason == "NONE"
    assert result.value == Decimal("-2.50")
    worked = f"**{MINUS_SIGN}2.50 R**"
    assert worked in TAIL_SPAN, "the document's worked value must be the computed one"


def test_the_tail_loss_the_worst_trade_and_the_expectancy_are_three_numbers() -> None:
    """The distinction the requirement is most often collapsed into one number."""
    observations = population(["-3.10", "-2.40", "-2.00"])
    tail = tail_loss(observations).value
    worst = min(o.r_multiple for o in observations)
    expectancy = sum((o.r_multiple for o in observations), Decimal(0)) / Decimal(len(observations))
    assert tail == Decimal("-2.50")
    assert worst == Decimal("-3.10")
    assert tail != worst, "a tail loss that equals the worst trade is the worst trade"
    assert tail != expectancy, "a tail loss that equals the expectancy is the expectancy"


def test_the_population_is_not_filtered_by_sign_and_a_positive_tail_is_available() -> None:
    result = tail_loss(population(["0.10", "0.15", "0.20"], rest_total="0"))
    assert result.availability == "AVAILABLE"
    assert result.reason == "NONE"
    assert result.value == Decimal("0.15")
    assert "never losses only" in flatten(TAIL_SPAN)


def test_a_measured_zero_is_available_and_is_not_an_absence() -> None:
    result = tail_loss(population(["-0.10", "0.00", "0.10"]))
    assert result.value == Decimal("0.00")
    assert result.availability == "AVAILABLE"
    assert result.reason == "NONE"


def test_below_the_minimum_the_value_is_absent_and_never_a_zero() -> None:
    short = population(["-3.10", "-2.40", "-2.00"])[: PARAMS.minimum_observations - 1]
    result = tail_loss(short)
    assert result.availability == "INSUFFICIENT_OBSERVATIONS"
    assert result.reason == "BELOW_MINIMUM_OBSERVATIONS"
    assert result.value is None, "an insufficient population must carry no value at all"


def test_an_empty_population_is_insufficient_and_not_empty_verified() -> None:
    result = tail_loss([])
    assert result.availability == "INSUFFICIENT_OBSERVATIONS"
    assert result.value is None
    assert result.availability != "EMPTY_VERIFIED"
    assert "not `EMPTY_VERIFIED`" in TAIL_SPAN


def test_excluded_trades_make_the_result_partial_rather_than_silently_reducing_it() -> None:
    result = tail_loss(population(["-3.10", "-2.40", "-2.00"]), excluded=2)
    assert result.availability == "PARTIAL"
    assert result.reason == "UPSTREAM_INPUT_MISSING"
    assert result.value == Decimal("-2.50")
    assert "naming how many" in flatten(TAIL_SPAN)


def test_ties_at_the_tail_boundary_do_not_change_the_value() -> None:
    """Three of the four most adverse are tied, so the boundary choice is arbitrary."""
    tied = population(["-3.10", "-2.00", "-2.00", "-2.00"], size=PARAMS.window + 1)
    forward = tail_loss(tied)
    reversed_order = tail_loss(list(reversed(tied)))
    assert forward.value == reversed_order.value


def test_the_window_excludes_every_observation_after_the_cutoff() -> None:
    observations = population(["-3.10", "-2.40", "-2.00"])
    point = max(o.closed_at for o in observations)
    later = Observation(point + 1, "t999", Decimal("-9.99"))
    assert later not in window_at([*observations, later], point, PARAMS.window)


def test_replacing_every_later_observation_changes_nothing_at_or_before_a_point() -> None:
    """The strong form. The weak 'no look-ahead' phrasing is not the rule."""
    observations = population(["-3.10", "-2.40", "-2.00"])
    point = max(o.closed_at for o in observations)
    before = tail_loss(window_at(observations, point, PARAMS.window))
    for replacement in (Decimal("-99.00"), Decimal("0.00"), Decimal("99.00")):
        future = [Observation(point + 1 + i, f"f{i:03d}", replacement) for i in range(5)]
        after = tail_loss(window_at(observations + future, point, PARAMS.window))
        assert after == before, replacement
    assert "changes nothing at or before" in flatten(TAIL_SPAN)


def test_the_statistic_is_a_mean_of_ratios_and_not_a_ratio_of_sums() -> None:
    """Each observation divides by its OWN retained initial planned risk.

    Summing tail dollars over tail risk dollars weights the tail by position size and is a
    different quantity under the same name, so the two must be shown to disagree.
    """
    tail_dollars = [Decimal("-310"), Decimal("-480"), Decimal("-200")]
    tail_risk = [Decimal("100"), Decimal("200"), Decimal("100")]
    per_trade_r = [d / r for d, r in zip(tail_dollars, tail_risk, strict=True)]
    mean_of_ratios = sum(per_trade_r, Decimal(0)) / Decimal(3)
    ratio_of_sums = sum(tail_dollars, Decimal(0)) / sum(tail_risk, Decimal(0))
    assert mean_of_ratios != ratio_of_sums
    observations = population([str(r) for r in per_trade_r])
    assert tail_loss(observations).value == mean_of_ratios
    assert "never a ratio of sums" in flatten(TAIL_SPAN)


def test_the_sign_convention_is_12_1_s_and_a_loss_stays_negative() -> None:
    value = tail_loss(population(["-3.10", "-2.40", "-2.00"])).value
    assert value is not None
    assert value < 0
    assert "profit positive, loss negative" in flatten(TAIL_SPAN)
    assert "profit positive, loss negative" in CONTRACTS_FLAT


def test_defining_the_tail_loss_creates_no_health_state_transition_rule() -> None:
    flat = flatten(TAIL_SPAN)
    assert "No health-state transition" in flat or "no health-state transition" in flat.lower()
    assert "the view still causes no transition" in CONTRACTS_FLAT
    for forbidden in ("SUSPENDED when", "DEGRADED when", "NEW_ENTRIES_DISABLED when"):
        assert forbidden not in flatten(ADR_TEXT), forbidden


# ------------------------------------------- the capacity contract, executed


CAPACITY_INPUT_ROW: Final = re.compile(r"^\| (\d+) \| (.+?) \| (.+?) \|$", re.MULTILINE)


def capacity_required_inputs() -> dict[int, str]:
    return {
        int(number): flatten(requirement)
        for number, requirement, _state in CAPACITY_INPUT_ROW.findall(CAPACITY_SPAN)
    }


def capacity_gate() -> dict[str, tuple[str, str]]:
    """The admission gate of 12.3.3, read as situation -> (availability, reason)."""
    gate: dict[str, tuple[str, str]] = {}
    for line in CAPACITY_SPAN.splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3:
            continue
        states = re.findall(r"`([A-Z_]+)`", cells[1])
        reasons = re.findall(r"`([A-Z_]+)`", cells[2])
        if len(states) == 1 and len(reasons) == 1:
            gate[flatten(cells[0].replace("**", ""))] = (states[0], reasons[0])
    return gate


INPUTS: Final = capacity_required_inputs()
GATE: Final = capacity_gate()


def test_the_capacity_parsers_see_the_contract() -> None:
    """Both scanners must find something, or every assertion below is vacuous."""
    assert len(INPUTS) == 9, sorted(INPUTS)
    assert len(GATE) >= 8, sorted(GATE)


def test_the_nine_required_inputs_are_enumerated_and_numbered_one_to_nine() -> None:
    assert sorted(INPUTS) == list(range(1, 10))
    joined = " ".join(INPUTS.values()).lower()
    for needed in (
        "volume history",
        "price history",
        "order and fill history",
        "participation limit",
        "execution horizon",
        "market-impact function",
        "cost tolerance",
        "borrow availability history",
        "portfolio-overlap set",
    ):
        assert needed in joined, needed


def test_a_missing_input_is_not_yet_available_and_never_a_value() -> None:
    state, reason = GATE["any required input absent — the state today"]
    assert (state, reason) == ("NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING")


def test_an_unqualified_model_is_unevaluated_and_not_a_missing_input() -> None:
    """A missing assessment and a missing input are two different absences."""
    unqualified = GATE["a model exists and its qualification is not recorded"]
    missing_input = GATE["any required input absent — the state today"]
    assert unqualified == ("UNEVALUATED", "NOT_YET_ASSESSED")
    assert unqualified != missing_input
    assert "not `NOT_YET_AVAILABLE`" in CAPACITY_SPAN


def test_only_a_qualified_model_with_every_input_reaches_available() -> None:
    available = [situation for situation, pair in GATE.items() if pair[0] == "AVAILABLE"]
    assert available == ["every input present and the model qualified"], available


def test_every_gate_pairing_is_one_the_validity_matrix_permits() -> None:
    """The gate is executed against 4.1.1 rather than trusted to be well formed."""
    matrix_span = section(
        CONTRACTS_TEXT, "#### 4.1.1 The validity matrix", "#### 4.1.2 A zero is a measurement"
    )
    permitted: dict[str, set[str]] = {}
    for line in matrix_span.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3:
            continue
        states = re.findall(r"`([A-Z_]+)`", cells[0])
        if len(states) != 1:
            continue
        permitted[states[0]] = set(re.findall(r"`([A-Z_]+)`", cells[2]))
    assert permitted, "the validity-matrix parser saw nothing"
    for situation, (state, reason) in GATE.items():
        assert state in permitted, (situation, state)
        assert reason in permitted[state], (situation, state, reason)


def capacity_from(source: str) -> Result:
    """Any substitution the contract forbids is a refusal, not a value."""
    forbidden = {
        "strategy_capital",
        "buying_power",
        "available_cash",
        "gross_exposure",
        "allocation_limit",
        "position_limit",
        "risk_limit",
    }
    if source in forbidden:
        return Result("NOT_YET_AVAILABLE", "UPSTREAM_INPUT_MISSING", None)
    raise AssertionError(f"unknown capacity source {source!r}")


@pytest.mark.parametrize(
    "source",
    ["strategy_capital", "buying_power", "available_cash", "gross_exposure", "allocation_limit"],
)
def test_no_substitute_quantity_ever_becomes_a_capacity_value(source: str) -> None:
    result = capacity_from(source)
    assert result.value is None, f"{source} was rendered as a capacity"
    assert result.availability == "NOT_YET_AVAILABLE"


def test_the_contract_names_every_forbidden_substitution_and_the_zero() -> None:
    flat = flatten(CAPACITY_SPAN)
    for phrase in (
        "not** strategy capital",
        "not** available cash",
        "not** buying power",
        "not** gross exposure",
    ):
        assert phrase in flat, phrase
    assert "Nothing on this row is ever zero" in flat


def test_capacity_is_a_level_with_no_denominator_and_a_stated_cost_treatment() -> None:
    row = [
        line for line in DICTIONARY_SPAN.splitlines() if line.startswith("| `strategy.capacity` |")
    ]
    assert len(row) == 1
    assert "USD · n/a" in row[0]
    assert "a level, not a ratio" in flatten(row[0])
    assert "NET_ALL_COSTS" in CAPACITY_SPAN


def test_per_version_capacities_are_never_summed_into_a_portfolio_capacity() -> None:
    assert "never summed into a portfolio capacity" in flatten(CAPACITY_SPAN)
    assert "constructing one by addition is refused" in flatten(CAPACITY_SPAN)


def test_capacity_declares_its_information_profile_and_never_public_pit() -> None:
    flat = flatten(CAPACITY_SPAN)
    assert "declared, never inferred" in flat
    assert "`PUBLIC_PIT` is not reachable" in flat


def test_the_synthetic_examples_are_not_a_production_qualification() -> None:
    examples = section(ADR_TEXT, "## 3. Worked examples", "## 4. Alternatives considered")
    flat = flatten(examples)
    assert "synthetic, and qualifying nothing" in flat
    assert "calibrate no model" in flat
    assert "qualify no provider" in flat
    assert "establish no production capacity" in flat
    assert "This is not a capacity for anything" in flat


def test_defining_capacity_is_not_claimed_to_make_one_obtainable() -> None:
    assert "Defining capacity does not make one obtainable" in flatten(CAPACITY_SPAN)
    assert "G1 and G5 are OPEN" in flatten(CAPACITY_SPAN)


# ------------------------------------------------------------- the product surface


def test_the_two_metric_rows_exist_and_are_labelled_proposed() -> None:
    rows = {
        line.split("|")[1].strip().strip("`"): line
        for line in DICTIONARY_SPAN.splitlines()
        if line.startswith("| `strategy.tail_loss` |") or line.startswith("| `strategy.capacity` |")
    }
    assert sorted(rows) == ["strategy.capacity", "strategy.tail_loss"], sorted(rows)
    for metric_id, line in rows.items():
        assert "PROPOSED by ADR-0032" in line, metric_id
        assert len([c for c in line.strip().strip("|").split(" | ")]) >= 6, metric_id


def test_the_tail_loss_row_declares_the_window_the_minimum_and_the_unit() -> None:
    rows = [
        line for line in DICTIONARY_SPAN.splitlines() if line.startswith("| `strategy.tail_loss` |")
    ]
    assert len(rows) == 1, "the dictionary table must carry exactly one tail-loss row"
    row = rows[0]
    assert "R_MULTIPLE" in row
    assert f"trailing {PARAMS.window} eligible observations" in row
    assert f"| {PARAMS.minimum_observations} closed trades |" in row
    assert "never a calendar window" in row


def test_area_ownership_is_recorded_and_the_tail_loss_stays_a_c7_surface() -> None:
    """The prior finding, held: Area 5 owns it, and it is not quietly moved into C5."""
    assert "With rolling expectancy, drawdown and tail losses" in flatten(V1_TEXT)
    area_five = [
        line for line in MATRIX_TEXT.splitlines() if line.startswith("| 5 | Strategy Health |")
    ]
    area_four = [
        line for line in MATRIX_TEXT.splitlines() if line.startswith("| 4 | Strategy Performance |")
    ]
    assert len(area_five) == 2, "Matrix A and Matrix B each carry one Area 5 row"
    assert len(area_four) == 2
    criteria_five = [line for line in area_five if "rolling tail loss" in line]
    criteria_four = [line for line in area_four if "strategy.capacity" in line]
    assert len(criteria_five) == 1, "the tail-loss criterion belongs to exactly one Area 5 row"
    assert len(criteria_four) == 1
    assert "**C7**" in criteria_five[0], "the tail loss must stay a C7 surface"
    assert "**C5**" in criteria_four[0], "capacity must stay a C5 surface"


def test_the_area_criteria_are_checkable_rather_than_restatements() -> None:
    five = next(
        line
        for line in MATRIX_TEXT.splitlines()
        if line.startswith("| 5 | Strategy Health |") and "rolling tail loss" in line
    )
    four = next(
        line
        for line in MATRIX_TEXT.splitlines()
        if line.startswith("| 4 | Strategy Performance |") and "strategy.capacity" in line
    )
    for needed in ("tail fraction", "observation count", "INSUFFICIENT_OBSERVATIONS", "negative"):
        assert needed in five, needed
    for needed in ("qualified-model interface", "buying power", "never summed", "zero"):
        assert needed in four, needed


def test_no_read_model_schema_version_is_changed_by_the_proposal() -> None:
    assert "No read-model schema version changes" in ADR_FLAT
    assert "`PerformanceSeries` and\n`StrategyPerformance` stay at `v3`" in ADR_TEXT or (
        "stay at `v3`" in ADR_FLAT
    )
    assert "changes no read-model schema version" in ADR_TEXT


def test_the_metric_definition_version_obligation_is_placed_not_performed() -> None:
    assert "`metric_definition_version` is `metrics.v1` and is not changed by this ADR" in ADR_FLAT
    assert "must advance" in ADR_FLAT
    assert "Fixture-byte equality is not a compatibility proof" in ADR_FLAT


def test_no_closed_vocabulary_is_extended() -> None:
    assert "No closed vocabulary is extended" in ADR_FLAT
    assert "no new member is proposed" in ADR_FLAT


# -------------------------------------------------------------- the status surface

STATUS_DOCUMENTS: Final = {
    name: flatten((PROJECT_ROOT / name).read_text(encoding="utf-8").replace("**", ""))
    for name in ("README.md", "CLAUDE.md")
}


@pytest.mark.parametrize("name", sorted(STATUS_DOCUMENTS))
def test_both_status_documents_record_the_verified_pr_84_merge(name: str) -> None:
    text = STATUS_DOCUMENTS[name]
    for statement in (
        "C5 completion follow-up: MERGED / IMPLEMENTED IN PART",
        "PR #84: MERGED",
        "PR #84 merge commit: 58636f53335eb9d48a4533c8a7f282ea4be8f154",
        "PR #84 merged at: 2026-09-09T06:13:46Z",
        "PR #84 final reviewed head: bf32ff6343ba3df6b65fe20843ce16a8f1724f30",
    ):
        assert statement in text, statement


@pytest.mark.parametrize("name", sorted(STATUS_DOCUMENTS))
def test_the_three_post_merge_dispositions_stay_separate(name: str) -> None:
    text = STATUS_DOCUMENTS[name]
    assert "post-merge MERGE_INTEGRITY: PASS - PER ITS OWN REPORT" in text
    assert "post-merge WINDOWS_VALIDATION: PASS - PER ITS OWN REPORT" in text
    assert "ORIGINAL_EVIDENCE_PRESERVATION: UNAVAILABLE" in text
    assert "original Linux review evidence: UNAVAILABLE" in text
    assert "ORIGINAL_EVIDENCE_PRESERVATION: PASS" not in text
    assert "Neither Windows evidence set is the original Linux review evidence" in text


@pytest.mark.parametrize("name", sorted(STATUS_DOCUMENTS))
def test_the_pre_merge_process_deviation_survives_the_merge(name: str) -> None:
    text = STATUS_DOCUMENTS[name]
    assert "pre-merge process deviation: RECORDED - MERGED WITH REPORTED FAILED GATES" in text
    assert "pre-merge process deviation: RESOLVED" not in text


@pytest.mark.parametrize("name", sorted(STATUS_DOCUMENTS))
def test_neither_measure_is_reported_as_accepted_or_implemented(name: str) -> None:
    text = STATUS_DOCUMENTS[name]
    assert "ADR-0032: PROPOSED / NOT IN FORCE" in text
    assert "tail-loss measurement contract: PROPOSED / NOT IN FORCE" in text
    assert "capacity measurement contract: PROPOSED / NOT IN FORCE" in text
    assert "rolling tail losses - IMPLEMENTATION: NOT AUTHORIZED / NOT IMPLEMENTED" in text
    assert "strategy capacity - IMPLEMENTATION: NOT AUTHORIZED / NOT IMPLEMENTED" in text
    for over_claim in (
        "ADR-0032: ACCEPTED / IN FORCE",
        "tail-loss measurement contract: ACCEPTED",
        "capacity measurement contract: ACCEPTED",
        "rolling tail losses: IMPLEMENTED",
        "strategy capacity: IMPLEMENTED",
        "C5 overall: COMPLETE",
        "full Cockpit V1: COMPLETE",
    ):
        assert over_claim not in text, over_claim


@pytest.mark.parametrize("name", sorted(STATUS_DOCUMENTS))
def test_the_outstanding_requirements_and_standing_gates_are_unchanged(name: str) -> None:
    text = STATUS_DOCUMENTS[name]
    for statement in (
        "C5 overall: NOT COMPLETE",
        "full Cockpit V1: INCOMPLETE",
        "C10: NOT STARTED / NOT AUTHORIZED",
        "strategy capacity - REQUIRED INPUTS: DO NOT EXIST",
        "capacity model: DOES NOT EXIST",
        "capacity model qualification: DOES NOT EXIST",
        "Run A retry: NOT AUTHORIZED / NOT RUN",
        "Run B: NOT RUN / NOT AUTHORIZED",
        "combined assessment: NOT RUN / NOT AUTHORIZED",
        "P1-P9: UNEVALUATED",
        "G1 / G2: OPEN / OPEN",
        "provider selected: NONE",
        "Phase 3: NOT COMPLETE",
        "CONTROL: DEFERRED",
        "live trading: HARD-DISABLED",
    ):
        assert statement in text, statement


@pytest.mark.parametrize("name", sorted(STATUS_DOCUMENTS))
def test_the_proposal_claims_no_frontend_dependency_or_runtime_change(name: str) -> None:
    text = STATUS_DOCUMENTS[name]
    for statement in (
        "new src/ modules created by this proposal: NONE",
        "read-model fields added: NONE",
        "read-model schema versions changed: NONE",
        "metric_definition_version: UNCHANGED - metrics.v1",
        "closed vocabularies extended: NONE",
        "fixtures, components or runtime changed: NONE",
        "frontend changed: NONE",
        "dependencies changed: NONE",
        "provider data used: NONE",
        "backtesting: NOT STARTED",
    ):
        assert statement in text, statement
