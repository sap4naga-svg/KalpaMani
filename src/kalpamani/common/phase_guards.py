"""Static guards that keep a phase inside its authorized scope.

Phase 1 is read-only (ADR-0002 §11): the IBKR Paper connectivity smoke test must
contain no order-submission path at all. Reviewing for that by eye is not good
enough, so the prohibition is expressed once here and enforced both by the unit
tests and by the pre-launch preflight script.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: LEAN order-submission APIs that must never appear in a Phase 1 algorithm.
#:
#: Matched in both snake_case (current LEAN Python idiom) and PascalCase (the
#: retained legacy aliases), so renaming the call style cannot slip one past.
#: Deliberately does NOT match observation-only callbacks such as
#: ``on_order_event``, which are permitted and act as a safety net.
PROHIBITED_ORDER_API_PATTERNS: tuple[tuple[str, str], ...] = (
    ("market_order", r"\b(market_order|MarketOrder)\s*\("),
    ("limit_order", r"\b(limit_order|LimitOrder)\s*\("),
    ("stop_market_order", r"\b(stop_market_order|StopMarketOrder)\s*\("),
    ("stop_limit_order", r"\b(stop_limit_order|StopLimitOrder)\s*\("),
    ("limit_if_touched_order", r"\b(limit_if_touched_order|LimitIfTouchedOrder)\s*\("),
    ("market_on_open_order", r"\b(market_on_open_order|MarketOnOpenOrder)\s*\("),
    ("market_on_close_order", r"\b(market_on_close_order|MarketOnCloseOrder)\s*\("),
    ("trailing_stop_order", r"\b(trailing_stop_order|TrailingStopOrder)\s*\("),
    ("combo_order", r"\b(combo_market_order|combo_limit_order|ComboMarketOrder)\s*\("),
    ("exercise_option", r"\b(exercise_option|ExerciseOption)\s*\("),
    ("set_holdings", r"\b(set_holdings|SetHoldings)\s*\("),
    ("liquidate", r"\b(liquidate|Liquidate)\s*\("),
    ("submit_order", r"\b(submit_order|SubmitOrder)\s*\("),
    ("calculate_order_quantity", r"\b(calculate_order_quantity|CalculateOrderQuantity)\s*\("),
    ("buy", r"\.\s*(buy|Buy)\s*\("),
    ("sell", r"\.\s*(sell|Sell)\s*\("),
    ("order", r"\.\s*(order|Order)\s*\("),
)

#: Comment prefixes whose lines are exempt: prose that merely *names* a
#: forbidden API (for example the file header listing what is banned) is not a
#: call site.
_COMMENT_PREFIXES = ("#",)


@dataclass(frozen=True, slots=True)
class OrderApiFinding:
    """A prohibited order-submission call site found in source."""

    path: Path
    line_number: int
    api_name: str
    line: str

    def describe(self) -> str:
        return (
            f"{self.path}:{self.line_number}: prohibited '{self.api_name}' -> {self.line.strip()}"
        )


def _is_effective_comment(line: str) -> bool:
    return line.lstrip().startswith(_COMMENT_PREFIXES)


def scan_source_for_order_apis(path: Path) -> list[OrderApiFinding]:
    """Return every prohibited order-submission call site in one source file.

    Comment lines are skipped so that documentation naming the banned APIs does
    not trip the guard. Docstrings are not skipped -- a call inside a docstring
    is dead code, but leaving it would still mislead a reader about what this
    algorithm can do.
    """
    findings: list[OrderApiFinding] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if _is_effective_comment(line):
            continue
        for api_name, pattern in PROHIBITED_ORDER_API_PATTERNS:
            if re.search(pattern, line):
                findings.append(
                    OrderApiFinding(
                        path=path, line_number=line_number, api_name=api_name, line=line
                    )
                )
    return findings


def scan_tree_for_order_apis(root: Path) -> list[OrderApiFinding]:
    """Scan every ``*.py`` file under ``root`` for prohibited order APIs."""
    findings: list[OrderApiFinding] = []
    for source in sorted(root.rglob("*.py")):
        findings.extend(scan_source_for_order_apis(source))
    return findings


__all__ = [
    "PROHIBITED_ORDER_API_PATTERNS",
    "OrderApiFinding",
    "scan_source_for_order_apis",
    "scan_tree_for_order_apis",
]
