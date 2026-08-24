"""Phase 1 brokerage safety guards.

Phase 1 is read-only. These tests make that structural rather than
aspirational, covering:

1. Strategy capital stays USD 80,000 after observing arbitrary broker equity.
2. Broker equity cannot mutate StrategyCapital.
3. LIVE mode cannot authorize order submission.
4. The connectivity smoke test contains no order-submission path.
5. Phase 1 cannot instantiate an order-capable live broker adapter.
6. Ambiguous brokerage/account mode fails closed.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from pathlib import Path

import pytest

from kalpamani.broker import account as broker_account
from kalpamani.broker.account import (
    BrokerAccountMode,
    BrokerAccountSnapshot,
    ReadOnlyBrokerAccount,
    reconcile_capital,
    redact_account_id,
    require_paper_account,
)
from kalpamani.common.capital import DEFAULT_STRATEGY_CAPITAL_USD, StrategyCapital
from kalpamani.common.environment import Environment
from kalpamani.common.errors import BrokerModeError, CapitalIntegrityError
from kalpamani.common.phase_guards import (
    PROHIBITED_ORDER_API_PATTERNS,
    scan_source_for_order_apis,
    scan_tree_for_order_apis,
)
from kalpamani.common.settings import Settings, load_settings

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SMOKE_TEST_DIR = PROJECT_ROOT / "lean" / "projects" / "ibkr_connectivity_smoke"
SMOKE_TEST_MAIN = SMOKE_TEST_DIR / "main.py"

IBKR_PAPER_SIMULATED_EQUITY_USD = Decimal("1000000")
PAPER_ACCOUNT_ID = "DU1234567"
LIVE_ACCOUNT_ID = "U7654321"


def paper_snapshot(equity: Decimal = IBKR_PAPER_SIMULATED_EQUITY_USD) -> BrokerAccountSnapshot:
    return BrokerAccountSnapshot(
        account_id=PAPER_ACCOUNT_ID,
        mode=BrokerAccountMode.PAPER,
        equity_usd=equity,
        cash_usd=equity,
        holdings_count=0,
        open_orders_count=0,
    )


# ---------------------------------------------------------------------------
# 1. Strategy capital survives observing arbitrary broker equity
# ---------------------------------------------------------------------------


def test_strategy_capital_survives_ibkr_paper_equity() -> None:
    """The headline Phase 1 assertion: 1,000,000 observed, 80,000 allocated."""
    reconciled = reconcile_capital(paper_snapshot(), StrategyCapital())

    assert reconciled.allocated_usd == Decimal("80000")
    assert reconciled.observed_broker_equity_usd == IBKR_PAPER_SIMULATED_EQUITY_USD
    assert reconciled.unallocated_broker_equity_usd == Decimal("920000")


@pytest.mark.parametrize(
    "broker_equity",
    [
        Decimal("80000"),
        Decimal("80000.01"),
        Decimal("1000000"),
        Decimal("999999999.99"),
    ],
)
def test_strategy_capital_is_invariant_across_broker_equities(broker_equity: Decimal) -> None:
    reconciled = reconcile_capital(paper_snapshot(broker_equity), StrategyCapital())
    assert reconciled.allocated_usd == DEFAULT_STRATEGY_CAPITAL_USD


def test_risk_budgets_never_scale_with_broker_equity() -> None:
    reconciled = reconcile_capital(paper_snapshot(), StrategyCapital())
    assert reconciled.long_risk_per_trade_usd == Decimal("400")
    assert reconciled.short_risk_per_trade_usd == Decimal("200")
    assert reconciled.max_open_planned_risk_usd == Decimal("4000")
    assert reconciled.max_position_usd == Decimal("8000")
    assert reconciled.max_gross_short_exposure_usd == Decimal("80000") * Decimal("0.25")


# ---------------------------------------------------------------------------
# 2. Broker equity cannot mutate StrategyCapital
# ---------------------------------------------------------------------------


def test_reconcile_returns_a_new_object_and_leaves_the_original_alone() -> None:
    original = StrategyCapital()
    reconciled = reconcile_capital(paper_snapshot(), original)

    assert reconciled is not original
    assert original.observed_broker_equity_usd is None
    assert original.allocated_usd == Decimal("80000")


def test_strategy_capital_allocation_cannot_be_assigned() -> None:
    capital = StrategyCapital()
    with pytest.raises(dataclasses.FrozenInstanceError):
        capital.allocated_usd = IBKR_PAPER_SIMULATED_EQUITY_USD  # type: ignore[misc]


def test_broker_snapshot_is_immutable() -> None:
    snapshot = paper_snapshot()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.equity_usd = Decimal("1")  # type: ignore[misc]


def test_underfunded_broker_fails_closed_rather_than_shrinking_budgets() -> None:
    with pytest.raises(CapitalIntegrityError):
        reconcile_capital(paper_snapshot(Decimal("79999.99")), StrategyCapital())


# ---------------------------------------------------------------------------
# 3. LIVE mode cannot authorize order submission
# ---------------------------------------------------------------------------


def test_live_environment_cannot_authorize_order_submission() -> None:
    settings = Settings(environment=Environment.LIVE)
    assert settings.order_submission_permitted is False
    assert settings.live_trading_enabled is False
    assert settings.broker_connection_permitted is False


def test_no_environment_permits_order_submission_in_phase_1() -> None:
    for environment in Environment:
        assert Settings(environment=environment).order_submission_permitted is False


def test_live_env_var_cannot_authorize_order_submission() -> None:
    settings = load_settings(env={"KALPAMANI_ENV": "live"})
    assert settings.order_submission_permitted is False


# ---------------------------------------------------------------------------
# 4. The smoke test contains no order-submission path
# ---------------------------------------------------------------------------


def test_smoke_test_project_exists() -> None:
    assert SMOKE_TEST_MAIN.is_file(), f"Expected the smoke test at {SMOKE_TEST_MAIN}."


def test_smoke_test_contains_no_order_submission_api() -> None:
    findings = scan_tree_for_order_apis(SMOKE_TEST_DIR)
    assert findings == [], "Prohibited order API in a read-only phase:\n" + "\n".join(
        f.describe() for f in findings
    )


def test_smoke_test_subscribes_to_exactly_one_symbol() -> None:
    source = SMOKE_TEST_MAIN.read_text(encoding="utf-8")
    assert source.count("add_equity(") == 1
    for forbidden in ("add_option(", "add_future(", "add_forex(", "add_crypto(", "add_universe("):
        assert forbidden not in source, f"Phase 1 must not use {forbidden}"


def test_smoke_test_capital_constant_matches_the_config_module() -> None:
    """The LEAN container has no kalpamani package, so the constant is duplicated.

    This test is what stops the copy from drifting away from the real one.
    """
    source = SMOKE_TEST_MAIN.read_text(encoding="utf-8")
    expected = f"KALPAMANI_STRATEGY_CAPITAL_USD = {int(DEFAULT_STRATEGY_CAPITAL_USD)}"
    assert expected in source, (
        f"Expected {expected!r} in the smoke test so it cannot drift from "
        f"kalpamani.common.capital.DEFAULT_STRATEGY_CAPITAL_USD."
    )


def test_order_api_guard_actually_detects_violations(tmp_path: Path) -> None:
    """Guard the guard: a scanner that never fires would be worthless."""
    offending = tmp_path / "bad_algo.py"
    offending.write_text(
        "class X:\n"
        "    def on_data(self, data):\n"
        "        self.set_holdings('SPY', 1)\n"
        "        self.market_order('SPY', 10)\n",
        encoding="utf-8",
    )
    findings = scan_source_for_order_apis(offending)
    found = {f.api_name for f in findings}
    assert "set_holdings" in found
    assert "market_order" in found


def test_order_api_guard_ignores_comments_naming_the_apis(tmp_path: Path) -> None:
    """Documentation that names a banned API must not trip the guard."""
    documented = tmp_path / "documented.py"
    documented.write_text(
        "# This algorithm never calls set_holdings( or market_order(.\nclass X:\n    pass\n",
        encoding="utf-8",
    )
    assert scan_source_for_order_apis(documented) == []


def test_order_api_guard_covers_both_naming_conventions() -> None:
    names = {name for name, _ in PROHIBITED_ORDER_API_PATTERNS}
    for required in ("market_order", "limit_order", "set_holdings", "liquidate"):
        assert required in names


# ---------------------------------------------------------------------------
# 5. Phase 1 cannot instantiate an order-capable broker adapter
# ---------------------------------------------------------------------------


def test_readonly_broker_protocol_exposes_no_order_capability() -> None:
    """The Phase 1 broker interface must be incapable of expressing an order."""
    members = {name for name in dir(ReadOnlyBrokerAccount) if not name.startswith("_")}
    forbidden_fragments = ("order", "buy", "sell", "liquidat", "submit", "cancel", "execute")
    offenders = {m for m in members if any(frag in m.lower() for frag in forbidden_fragments)}
    assert offenders == set(), f"Read-only broker protocol exposes order capability: {offenders}"

    assert members == {"account_snapshot"}


def test_broker_package_exports_no_order_capability() -> None:
    exported = set(broker_account.__all__)
    forbidden_fragments = ("submit", "cancel", "liquidat", "place")
    offenders = {n for n in exported if any(frag in n.lower() for frag in forbidden_fragments)}
    assert offenders == set(), f"broker.account exports order capability: {offenders}"


def test_broker_module_source_contains_no_order_submission_api() -> None:
    findings = scan_source_for_order_apis(
        PROJECT_ROOT / "src" / "kalpamani" / "broker" / "account.py"
    )
    assert findings == [], "\n".join(f.describe() for f in findings)


def test_no_order_capable_adapter_class_exists() -> None:
    """No class anywhere in the broker package may advertise order submission."""
    broker_dir = PROJECT_ROOT / "src" / "kalpamani" / "broker"
    for source in broker_dir.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        for banned in ("def submit_order", "def place_order", "def cancel_order", "def liquidate"):
            assert banned not in text, f"{source} defines {banned!r} during a read-only phase."


# ---------------------------------------------------------------------------
# 6. Ambiguous brokerage/account mode fails closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("account_id", "expected"),
    [
        ("DU1234567", BrokerAccountMode.PAPER),
        ("du1234567", BrokerAccountMode.PAPER),
        ("DF1234567", BrokerAccountMode.PAPER),
        ("U1234567", BrokerAccountMode.LIVE),
        ("F1234567", BrokerAccountMode.LIVE),
        ("", BrokerAccountMode.UNKNOWN),
        ("   ", BrokerAccountMode.UNKNOWN),
        ("XX999", BrokerAccountMode.UNKNOWN),
        ("12345", BrokerAccountMode.UNKNOWN),
    ],
)
def test_account_mode_classification(account_id: str, expected: BrokerAccountMode) -> None:
    assert BrokerAccountMode.classify(account_id) is expected


def test_paper_prefix_is_not_mistaken_for_live() -> None:
    """DU1234567 contains 'U1234567'; a careless match would call it live."""
    assert BrokerAccountMode.classify(PAPER_ACCOUNT_ID) is BrokerAccountMode.PAPER


def test_live_account_is_refused() -> None:
    snapshot = dataclasses.replace(
        paper_snapshot(), account_id=LIVE_ACCOUNT_ID, mode=BrokerAccountMode.LIVE
    )
    with pytest.raises(BrokerModeError):
        require_paper_account(snapshot)


def test_unknown_account_mode_fails_closed() -> None:
    """Ambiguity is a failure, never an assumed paper account."""
    snapshot = dataclasses.replace(
        paper_snapshot(), account_id="???", mode=BrokerAccountMode.UNKNOWN
    )
    with pytest.raises(BrokerModeError):
        require_paper_account(snapshot)


def test_reconcile_refuses_a_live_account_before_touching_capital() -> None:
    snapshot = dataclasses.replace(
        paper_snapshot(), account_id=LIVE_ACCOUNT_ID, mode=BrokerAccountMode.LIVE
    )
    with pytest.raises(BrokerModeError):
        reconcile_capital(snapshot, StrategyCapital())


def test_paper_account_is_accepted() -> None:
    require_paper_account(paper_snapshot())  # must not raise


# ---------------------------------------------------------------------------
# Account identifiers stay out of logs
# ---------------------------------------------------------------------------


def test_account_id_is_redacted_for_logs() -> None:
    assert redact_account_id("DU1234567") == "DU*******"
    assert redact_account_id("U7654321") == "U*******"
    assert redact_account_id("") == "<empty>"


def test_snapshot_description_never_leaks_the_full_account_id() -> None:
    description = paper_snapshot().describe()
    assert PAPER_ACCOUNT_ID not in description
    assert "DU*******" in description
    assert "1234567" not in description


def test_snapshot_reports_flat_account() -> None:
    assert paper_snapshot().is_flat is True
    busy = dataclasses.replace(paper_snapshot(), holdings_count=1)
    assert busy.is_flat is False
