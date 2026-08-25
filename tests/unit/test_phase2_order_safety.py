"""Phase 2 order-safety guards (ADR-0004).

Phase 2 opens the first write path to a broker. ADR-0003 established there is no
broker-side backstop: IBAutomater disables IB Gateway's `[Read-Only API]` and
bypasses its order precautions on every start. So every guard that stops an
unintended or duplicated order lives here and in the code these tests cover.

The 20 required proofs, in order:

 1. LIVE session cannot arm Phase 2
 2. UNKNOWN account mode cannot arm Phase 2
 3. non-SPY symbol rejected
 4. quantity != 1 rejected
 5. notional > $1,000 rejected
 6. second trade intent rejected
 7. second entry rejected
 8. duplicate event cannot duplicate entry
 9. restart cannot resubmit entry
10. zero fill creates no protection
11. partial/full fill protection equals actual filled quantity
12. duplicate fill event cannot duplicate stop
13. exit quantity cannot exceed current long position
14. closing cannot leave an active stop capable of creating a short
15. strategy capital remains $80,000
16. broker $1M simulated balance cannot control sizing
17. LIVE_TRADING_HARD_DISABLED remains intact
18. strategy modules cannot directly invoke Phase 2 execution
19. missing durable state fails closed
20. contradictory broker/internal state fails closed
"""

from __future__ import annotations

import ast
import json
from datetime import time
from decimal import Decimal
from pathlib import Path

import pytest

from kalpamani.broker.orders import OrderRequest, OrderRequestError, OrderSide, OrderType
from kalpamani.common.capital import DEFAULT_STRATEGY_CAPITAL_USD, StrategyCapital
from kalpamani.common.environment import Environment
from kalpamani.common.settings import LIVE_TRADING_HARD_DISABLED, Settings
from kalpamani.execution.envelope import (
    PHASE2_CONFIRMATION_PHRASE,
    PHASE2_INTENT_NATURAL_KEY,
    PHASE2_MAX_REFERENCE_NOTIONAL_USD,
    ExecutionArmError,
    ExecutionArmRequest,
    Phase2EnvelopeError,
    assert_arm_not_reusable,
    authorize_trade_intent,
    protective_stop_price,
)
from kalpamani.execution.identity import (
    OrderIdentityError,
    OrderRole,
    TradeIdentity,
    client_order_id,
    is_valid_client_order_id,
)
from kalpamani.execution.lifecycle import (
    LifecycleError,
    TradeState,
    is_terminal,
    validate_transition,
)
from kalpamani.execution.reconciliation import (
    BrokerOrderView,
    BrokerPositionView,
    BrokerView,
    ReconciliationError,
    UnprotectedPositionError,
    assert_flat,
    assert_protected,
    assert_safe_to_close,
    plan_exit,
    reconcile,
    required_protection_quantity,
)
from kalpamani.execution.session import (
    BrokerSessionEvidence,
    SessionVerificationError,
    account_fingerprint,
    verify_paper_session,
)
from kalpamani.execution.state_store import (
    STATE_SCHEMA_VERSION,
    JsonTradeStateStore,
    StateCorruptError,
    StateMissingError,
    StateStoreError,
    TradeRecord,
    apply_fill,
    record_order_intent,
)
from kalpamani.execution.trading_window import (
    PHASE2_TIME_ZONE,
    PHASE2_WINDOW_CLOSE,
    PHASE2_WINDOW_OPEN,
    TradingWindowError,
    assert_within_certification_window,
)

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PHASE2_MAIN = PROJECT_ROOT / "lean" / "projects" / "phase2_order_lifecycle" / "main.py"
PAPER_ACCOUNT_ID = "DU1234567"
LIVE_ACCOUNT_ID = "U7654321"
IBKR_PAPER_SIMULATED_EQUITY_USD = Decimal("1000000")
SPY_PRICE = Decimal("766.38")


# --------------------------------------------------------------------------
# Fixtures / builders
# --------------------------------------------------------------------------


def evidence(
    account_id: str = PAPER_ACCOUNT_ID,
    trading_mode: str = "paper",
) -> BrokerSessionEvidence:
    """Session evidence as read from LEAN's own deployment configuration."""
    return BrokerSessionEvidence(
        account_id=account_id, trading_mode=trading_mode, source="test-deployment-config"
    )


def arm_request(**overrides: object) -> ExecutionArmRequest:
    defaults: dict[str, object] = {
        "confirmation": PHASE2_CONFIRMATION_PHRASE,
        "settings": Settings(environment=Environment.PAPER),
        "session_evidence": evidence(),
        "symbol": "SPY",
        "quantity": 1,
        "reference_price": SPY_PRICE,
        "phase2_test_mode": True,
        "explicit_execution_arm": True,
    }
    defaults.update(overrides)
    return ExecutionArmRequest(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def store(tmp_path: Path) -> JsonTradeStateStore:
    return JsonTradeStateStore(tmp_path / "phase2_state.json")


@pytest.fixture
def identity() -> TradeIdentity:
    return TradeIdentity.derive(PHASE2_INTENT_NATURAL_KEY, attempt=1)


def filled_record(identity: TradeIdentity, filled: int = 1) -> TradeRecord:
    """A record that has entered and filled `filled` shares."""
    record = TradeRecord(
        trade_intent_id=identity.trade_intent_id,
        execution_id=identity.execution_id,
        natural_key=identity.natural_key,
        attempt=identity.attempt,
        symbol="SPY",
        state=TradeState.ENTRY_ACKNOWLEDGED,
        requested_quantity=1,
        arm_consumed=True,
        account_fingerprint=account_fingerprint(PAPER_ACCOUNT_ID),
    )
    record = record_order_intent(
        record,
        client_order_id=identity.entry_order_id,
        role=OrderRole.ENTRY,
        symbol="SPY",
        side="BUY",
        quantity=1,
    )
    if filled:
        record = apply_fill(
            record,
            client_order_id=identity.entry_order_id,
            fill_id="fill-1",
            fill_quantity=filled,
        )
    return record


# --------------------------------------------------------------------------
# 1. LIVE session cannot arm Phase 2
# --------------------------------------------------------------------------


def test_live_account_cannot_arm_phase2(store: JsonTradeStateStore) -> None:
    with pytest.raises(SessionVerificationError):
        authorize_trade_intent(
            arm_request(session_evidence=evidence(LIVE_ACCOUNT_ID, "live")), store
        )


def test_live_trading_mode_cannot_arm_even_with_paper_looking_id(
    store: JsonTradeStateStore,
) -> None:
    """A paper-looking id does not override LEAN's own trading-mode evidence."""
    with pytest.raises(SessionVerificationError):
        authorize_trade_intent(
            arm_request(session_evidence=evidence(PAPER_ACCOUNT_ID, "live")), store
        )


def test_live_environment_cannot_arm_phase2(store: JsonTradeStateStore) -> None:
    with pytest.raises(ExecutionArmError):
        authorize_trade_intent(arm_request(settings=Settings(environment=Environment.LIVE)), store)


def test_research_environment_cannot_arm_phase2(store: JsonTradeStateStore) -> None:
    with pytest.raises(ExecutionArmError):
        authorize_trade_intent(
            arm_request(settings=Settings(environment=Environment.RESEARCH)), store
        )


# --------------------------------------------------------------------------
# 2. UNKNOWN account mode cannot arm Phase 2
# --------------------------------------------------------------------------


def test_unknown_account_mode_cannot_arm_phase2(store: JsonTradeStateStore) -> None:
    """Ambiguity is an abort condition, never an assumption of safety."""
    with pytest.raises(SessionVerificationError):
        authorize_trade_intent(arm_request(session_evidence=evidence("XX999", "paper")), store)


def test_armed_account_must_match_deployed_account() -> None:
    """The arm and the deployment must never be two values that can disagree."""
    deployed = evidence("DU1111111")
    armed_fingerprint = account_fingerprint("DU2222222")
    with pytest.raises(SessionVerificationError, match="does not match"):
        verify_paper_session(deployed, expected_fingerprint=armed_fingerprint)


def test_matching_account_fingerprint_passes() -> None:
    deployed = evidence(PAPER_ACCOUNT_ID)
    verify_paper_session(deployed, expected_fingerprint=account_fingerprint(PAPER_ACCOUNT_ID))


def test_fingerprint_never_reveals_the_account_id() -> None:
    fingerprint = account_fingerprint(PAPER_ACCOUNT_ID)
    assert PAPER_ACCOUNT_ID not in fingerprint
    assert "1234567" not in fingerprint
    assert evidence().describe().count(PAPER_ACCOUNT_ID) == 0


def test_arm_requires_test_mode_and_explicit_flag(store: JsonTradeStateStore) -> None:
    with pytest.raises(ExecutionArmError):
        authorize_trade_intent(arm_request(phase2_test_mode=False), store)
    with pytest.raises(ExecutionArmError):
        authorize_trade_intent(arm_request(explicit_execution_arm=False), store)


def test_arm_requires_exact_confirmation_phrase(store: JsonTradeStateStore) -> None:
    """A boolean can be set by a stray env var; a phrase cannot be typed by accident."""
    for wrong in ("", "yes", "arm phase2 paper buy 1 spy", PHASE2_CONFIRMATION_PHRASE + "!"):
        with pytest.raises(ExecutionArmError):
            authorize_trade_intent(arm_request(confirmation=wrong), store)


# --------------------------------------------------------------------------
# 3-5. Symbol, quantity and notional envelope
# --------------------------------------------------------------------------


@pytest.mark.parametrize("symbol", ["QQQ", "AAPL", "SPXL", "spy", "SPY "])
def test_non_spy_symbol_rejected(store: JsonTradeStateStore, symbol: str) -> None:
    with pytest.raises(Phase2EnvelopeError):
        authorize_trade_intent(arm_request(symbol=symbol), store)


@pytest.mark.parametrize("quantity", [0, 2, 10, 100, -1])
def test_quantity_other_than_one_rejected(store: JsonTradeStateStore, quantity: int) -> None:
    with pytest.raises(Phase2EnvelopeError):
        authorize_trade_intent(arm_request(quantity=quantity), store)


def test_notional_above_ceiling_rejected(store: JsonTradeStateStore) -> None:
    """If SPY trades above the ceiling we abort; we do not size down, because 1 is minimum."""
    with pytest.raises(Phase2EnvelopeError):
        authorize_trade_intent(
            arm_request(reference_price=PHASE2_MAX_REFERENCE_NOTIONAL_USD + Decimal("0.01")), store
        )


def test_notional_at_ceiling_allowed(store: JsonTradeStateStore) -> None:
    identity, record = authorize_trade_intent(
        arm_request(reference_price=PHASE2_MAX_REFERENCE_NOTIONAL_USD), store
    )
    assert record.state is TradeState.AUTHORIZED
    assert identity.trade_intent_id


def test_non_positive_price_rejected(store: JsonTradeStateStore) -> None:
    with pytest.raises(Phase2EnvelopeError):
        authorize_trade_intent(arm_request(reference_price=Decimal("0")), store)


# --------------------------------------------------------------------------
# 6-7. Single intent, single entry
# --------------------------------------------------------------------------


def test_second_trade_intent_rejected(store: JsonTradeStateStore) -> None:
    _, record = authorize_trade_intent(arm_request(), store)
    store.put(record)
    with pytest.raises(ExecutionArmError):
        authorize_trade_intent(arm_request(), store)


def test_unresolved_prior_trade_blocks_arming(
    store: JsonTradeStateStore, identity: TradeIdentity
) -> None:
    stale = TradeRecord(
        trade_intent_id="ti-someotherintent",
        execution_id="ex-someotherexec",
        natural_key="prior",
        attempt=1,
        symbol="SPY",
        state=TradeState.FILLED,
        requested_quantity=1,
        arm_consumed=True,
    )
    store.put(stale)
    with pytest.raises(ExecutionArmError):
        authorize_trade_intent(arm_request(), store)


def test_second_entry_order_id_cannot_even_be_derived(identity: TradeIdentity) -> None:
    """Refusing at the identity layer means a second entry cannot be named, let alone sent."""
    with pytest.raises(OrderIdentityError):
        client_order_id(identity.execution_id, OrderRole.ENTRY, ordinal=1)


def test_second_entry_order_rejected_by_state_store(identity: TradeIdentity) -> None:
    record = filled_record(identity, filled=0)
    with pytest.raises(StateStoreError):
        record_order_intent(
            record,
            client_order_id=identity.entry_order_id,
            role=OrderRole.ENTRY,
            symbol="SPY",
            side="BUY",
            quantity=1,
        )


# --------------------------------------------------------------------------
# 8-9. Duplicate events and restart cannot resubmit
# --------------------------------------------------------------------------


def test_duplicate_event_cannot_duplicate_entry(identity: TradeIdentity) -> None:
    record = filled_record(identity, filled=1)
    assert record.entry_count == 1
    for _ in range(5):
        with pytest.raises(StateStoreError):
            record_order_intent(
                record,
                client_order_id=identity.entry_order_id,
                role=OrderRole.ENTRY,
                symbol="SPY",
                side="BUY",
                quantity=1,
            )
    assert record.entry_count == 1


def test_identity_is_reproducible_across_restart() -> None:
    """The whole recovery model rests on this: same inputs, byte-identical ids."""
    first = TradeIdentity.derive(PHASE2_INTENT_NATURAL_KEY, attempt=1)
    second = TradeIdentity.derive(PHASE2_INTENT_NATURAL_KEY, attempt=1)
    assert first == second
    assert first.entry_order_id == second.entry_order_id
    assert first.protective_order_id == second.protective_order_id
    assert first.exit_order_id == second.exit_order_id


def test_restart_recovers_record_and_cannot_resubmit_entry(
    tmp_path: Path, identity: TradeIdentity
) -> None:
    """Entry orders before restart = 1; entry orders after restart = 0."""
    path = tmp_path / "state.json"
    JsonTradeStateStore(path).put(filled_record(identity, filled=1))

    # A brand new store object stands in for a restarted process.
    recovered = JsonTradeStateStore(path).require(identity.trade_intent_id)
    assert recovered.entry_count == 1
    assert_arm_not_reusable(recovered)

    entries_submitted_after_restart = 0
    try:
        record_order_intent(
            recovered,
            client_order_id=identity.entry_order_id,
            role=OrderRole.ENTRY,
            symbol="SPY",
            side="BUY",
            quantity=1,
        )
        entries_submitted_after_restart = 1
    except StateStoreError:
        pass
    assert entries_submitted_after_restart == 0
    assert recovered.entry_count == 1


def test_restart_cannot_rearm(store: JsonTradeStateStore) -> None:
    _, record = authorize_trade_intent(arm_request(), store)
    store.put(record)
    assert record.arm_consumed is True
    with pytest.raises(ExecutionArmError):
        authorize_trade_intent(arm_request(), store)


def test_record_without_consumed_arm_fails_closed(identity: TradeIdentity) -> None:
    record = TradeRecord(
        trade_intent_id=identity.trade_intent_id,
        execution_id=identity.execution_id,
        natural_key=identity.natural_key,
        attempt=1,
        symbol="SPY",
        state=TradeState.FILLED,
        requested_quantity=1,
        arm_consumed=False,
    )
    with pytest.raises(ExecutionArmError):
        assert_arm_not_reusable(record)


# --------------------------------------------------------------------------
# 10-12. Fill handling and protection
# --------------------------------------------------------------------------


def test_zero_fill_creates_no_protection(identity: TradeIdentity) -> None:
    """A stop for a position that does not exist could itself open a short."""
    record = filled_record(identity, filled=0)
    assert required_protection_quantity(record) == 0


@pytest.mark.parametrize(("filled", "expected"), [(0, 0), (1, 1)])
def test_protection_equals_actual_filled_quantity(
    identity: TradeIdentity, filled: int, expected: int
) -> None:
    record = filled_record(identity, filled=filled)
    assert required_protection_quantity(record) == expected


def test_protection_uses_actual_not_requested_quantity(identity: TradeIdentity) -> None:
    """Requested 1, filled 0 -> protect 0. Never protect what was merely asked for."""
    record = filled_record(identity, filled=0)
    assert record.requested_quantity == 1
    assert required_protection_quantity(record) == 0


def test_duplicate_fill_event_is_idempotent(identity: TradeIdentity) -> None:
    record = filled_record(identity, filled=1)
    for _ in range(5):
        record = apply_fill(
            record,
            client_order_id=identity.entry_order_id,
            fill_id="fill-1",
            fill_quantity=1,
        )
    assert record.filled_quantity == 1
    assert required_protection_quantity(record) == 1


def test_overfill_fails_closed(identity: TradeIdentity) -> None:
    record = filled_record(identity, filled=1)
    with pytest.raises(StateStoreError):
        apply_fill(
            record,
            client_order_id=identity.entry_order_id,
            fill_id="fill-2",
            fill_quantity=1,
        )


def test_fill_for_unknown_order_fails_closed(identity: TradeIdentity) -> None:
    record = filled_record(identity, filled=0)
    with pytest.raises(StateStoreError):
        apply_fill(
            record,
            client_order_id="km-deadbeef-ENTRY-0",
            fill_id="fill-x",
            fill_quantity=1,
        )


def test_unprotected_position_is_highest_severity(identity: TradeIdentity) -> None:
    record = filled_record(identity, filled=1)
    broker = BrokerView(positions=(BrokerPositionView("SPY", 1),), open_orders=())
    with pytest.raises(UnprotectedPositionError):
        assert_protected(record, identity, broker)


def test_protection_of_wrong_side_is_not_protection(identity: TradeIdentity) -> None:
    record = filled_record(identity, filled=1)
    broker = BrokerView(
        positions=(BrokerPositionView("SPY", 1),),
        open_orders=(BrokerOrderView(identity.protective_order_id, "SPY", "BUY", 1, is_open=True),),
    )
    with pytest.raises(UnprotectedPositionError):
        assert_protected(record, identity, broker)


def test_correct_protection_satisfies_assert_protected(identity: TradeIdentity) -> None:
    record = filled_record(identity, filled=1)
    broker = BrokerView(
        positions=(BrokerPositionView("SPY", 1),),
        open_orders=(
            BrokerOrderView(identity.protective_order_id, "SPY", "SELL", 1, is_open=True),
        ),
    )
    assert_protected(record, identity, broker)  # must not raise


# --------------------------------------------------------------------------
# 13-14. Exit safety and stale-stop prevention
# --------------------------------------------------------------------------


def test_exit_quantity_cannot_exceed_long_position(identity: TradeIdentity) -> None:
    record = filled_record(identity, filled=1)
    broker = BrokerView(positions=(BrokerPositionView("SPY", 1),))
    plan = plan_exit(record, identity, broker)
    assert plan.exit_quantity == 1

    shrunk = BrokerView(positions=(BrokerPositionView("SPY", 0),))
    with pytest.raises(ReconciliationError):
        assert_safe_to_close(plan, identity, shrunk)


def test_exit_refused_when_no_long_position(identity: TradeIdentity) -> None:
    record = filled_record(identity, filled=0)
    broker = BrokerView(positions=(BrokerPositionView("SPY", 0),))
    with pytest.raises(ReconciliationError):
        plan_exit(record, identity, broker)


def test_exit_plan_cancels_protection_first(identity: TradeIdentity) -> None:
    record = filled_record(identity, filled=1)
    broker = BrokerView(
        positions=(BrokerPositionView("SPY", 1),),
        open_orders=(
            BrokerOrderView(identity.protective_order_id, "SPY", "SELL", 1, is_open=True),
        ),
    )
    plan = plan_exit(record, identity, broker)
    assert plan.cancel_client_order_id == identity.protective_order_id


def test_closing_with_live_stop_is_refused(identity: TradeIdentity) -> None:
    """A stop left working after the long closes can fill and open a SHORT."""
    record = filled_record(identity, filled=1)
    still_protected = BrokerView(
        positions=(BrokerPositionView("SPY", 1),),
        open_orders=(
            BrokerOrderView(identity.protective_order_id, "SPY", "SELL", 1, is_open=True),
        ),
    )
    plan = plan_exit(record, identity, still_protected)
    with pytest.raises(ReconciliationError):
        assert_safe_to_close(plan, identity, still_protected)


def test_closing_allowed_once_protection_cancelled(identity: TradeIdentity) -> None:
    record = filled_record(identity, filled=1)
    before = BrokerView(
        positions=(BrokerPositionView("SPY", 1),),
        open_orders=(
            BrokerOrderView(identity.protective_order_id, "SPY", "SELL", 1, is_open=True),
        ),
    )
    plan = plan_exit(record, identity, before)
    after_cancel = BrokerView(
        positions=(BrokerPositionView("SPY", 1),),
        open_orders=(
            BrokerOrderView(identity.protective_order_id, "SPY", "SELL", 1, is_open=False),
        ),
    )
    assert_safe_to_close(plan, identity, after_cancel)  # must not raise


def test_accidental_short_is_detected_by_final_reconcile(identity: TradeIdentity) -> None:
    record = filled_record(identity, filled=1)
    shorted = BrokerView(positions=(BrokerPositionView("SPY", -1),))
    with pytest.raises(ReconciliationError, match="ACCIDENTAL SHORT"):
        assert_flat(record, identity, shorted)


def test_flat_state_accepted(identity: TradeIdentity) -> None:
    record = filled_record(identity, filled=1)
    flat = BrokerView(positions=(BrokerPositionView("SPY", 0),), open_orders=())
    assert_flat(record, identity, flat)  # must not raise


# --------------------------------------------------------------------------
# 15-17. Capital and live-trading invariants
# --------------------------------------------------------------------------


def test_strategy_capital_remains_80000(store: JsonTradeStateStore) -> None:
    identity, record = authorize_trade_intent(arm_request(), store)
    assert StrategyCapital().allocated_usd == Decimal("80000")
    assert DEFAULT_STRATEGY_CAPITAL_USD == Decimal("80000")
    assert record.requested_quantity == 1
    assert identity.attempt == 1


def test_broker_million_cannot_control_sizing(store: JsonTradeStateStore) -> None:
    """The paper account reports 1,000,000. Phase 2 still buys exactly 1 share."""
    _, record = authorize_trade_intent(arm_request(), store)
    assert record.requested_quantity == 1

    observed = StrategyCapital().observe_broker_equity(IBKR_PAPER_SIMULATED_EQUITY_USD)
    assert observed.allocated_usd == Decimal("80000")


def test_capital_mismatch_refuses_to_arm(store: JsonTradeStateStore) -> None:
    with pytest.raises(ExecutionArmError):
        authorize_trade_intent(
            arm_request(), store, capital=StrategyCapital(allocated_usd=Decimal("1000000"))
        )


def test_live_trading_hard_disabled_remains_intact() -> None:
    assert LIVE_TRADING_HARD_DISABLED is True
    for environment in Environment:
        settings = Settings(environment=environment)
        assert settings.live_trading_enabled is False
        assert settings.order_submission_permitted is False


# --------------------------------------------------------------------------
# 18. Strategy modules cannot invoke execution
# --------------------------------------------------------------------------


def test_strategy_modules_cannot_import_execution_or_orders() -> None:
    """Order capability must be unreachable from strategy, risk, portfolio, research."""
    forbidden_importers = ["strategies", "risk", "portfolio", "research"]
    banned = ("kalpamani.execution", "kalpamani.broker.orders", "AlgorithmImports")
    package_root = PROJECT_ROOT / "src" / "kalpamani"
    for area in forbidden_importers:
        for source in (package_root / area).rglob("*.py"):
            text = source.read_text(encoding="utf-8")
            for token in banned:
                assert f"import {token}" not in text and f"from {token}" not in text, (
                    f"{source} imports {token!r}. Strategy-side modules must reach the broker "
                    "only through the execution boundary (ADR-0002 §3, ADR-0004 §10)."
                )


def test_execution_package_does_not_import_strategies() -> None:
    """The dependency arrow points one way."""
    execution_root = PROJECT_ROOT / "src" / "kalpamani" / "execution"
    for source in execution_root.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "kalpamani.strategies" not in text, f"{source} must not depend on strategies."


# --------------------------------------------------------------------------
# 19-20. Durable state and contradiction fail closed
# --------------------------------------------------------------------------


def test_missing_durable_state_fails_closed(tmp_path: Path) -> None:
    """Absent state must never be read as 'nothing happened'."""
    store = JsonTradeStateStore(tmp_path / "absent.json")
    with pytest.raises(StateMissingError):
        store.require("ti-doesnotexist")


def test_corrupt_durable_state_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.json"
    path.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(StateCorruptError):
        JsonTradeStateStore(path).all_records()


def test_unknown_schema_version_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "future.json"
    path.write_text(
        json.dumps({"schema_version": STATE_SCHEMA_VERSION + 99, "trades": {}}), encoding="utf-8"
    )
    with pytest.raises(StateCorruptError):
        JsonTradeStateStore(path).all_records()


def test_unknown_lifecycle_state_fails_closed() -> None:
    with pytest.raises(LifecycleError):
        TradeState.parse("DEFINITELY_NOT_A_STATE")


def test_contradictory_broker_state_fails_closed(identity: TradeIdentity) -> None:
    """Internal says 1 long; broker says 0. Failing closed, not reconciling optimistically."""
    record = filled_record(identity, filled=1)
    disagreeing = BrokerView(positions=(BrokerPositionView("SPY", 0),))
    with pytest.raises(ReconciliationError):
        reconcile(record, identity, disagreeing)


def test_matching_broker_state_reconciles(identity: TradeIdentity) -> None:
    record = filled_record(identity, filled=1)
    agreeing = BrokerView(positions=(BrokerPositionView("SPY", 1),))
    result = reconcile(record, identity, agreeing)
    assert result.matches is True


def test_atomic_write_survives_reload(tmp_path: Path, identity: TradeIdentity) -> None:
    path = tmp_path / "state.json"
    store = JsonTradeStateStore(path)
    store.put(filled_record(identity, filled=1))
    reloaded = JsonTradeStateStore(path).require(identity.trade_intent_id)
    assert reloaded.filled_quantity == 1
    assert reloaded.entry_count == 1
    assert reloaded.arm_consumed is True


# --------------------------------------------------------------------------
# Lifecycle, identity and order-request hygiene
# --------------------------------------------------------------------------


def test_terminal_states_never_resume() -> None:
    for terminal in (TradeState.RECONCILED, TradeState.FAILED):
        assert is_terminal(terminal)
        with pytest.raises(LifecycleError):
            validate_transition(terminal, TradeState.ENTRY_SUBMITTED)


def test_illegal_transition_rejected() -> None:
    with pytest.raises(LifecycleError):
        validate_transition(TradeState.CREATED, TradeState.FILLED)


def test_every_non_terminal_state_can_fail_closed() -> None:
    for state in TradeState:
        if is_terminal(state):
            continue
        validate_transition(state, TradeState.FAILED)


def test_client_order_ids_are_role_distinct(identity: TradeIdentity) -> None:
    ids = {identity.entry_order_id, identity.protective_order_id, identity.exit_order_id}
    assert len(ids) == 3
    for candidate in ids:
        assert is_valid_client_order_id(candidate)
        assert identity.owns(candidate)


def test_foreign_orders_are_never_adopted(identity: TradeIdentity) -> None:
    """An order we did not tag belongs to someone else and is left alone."""
    foreign = BrokerOrderView("SOMEONE-ELSES-ORDER", "SPY", "SELL", 100, is_open=True)
    view = BrokerView(open_orders=(foreign,))
    assert view.orders_owned_by(identity) == ()


def test_order_request_rejects_untagged_id() -> None:
    with pytest.raises(OrderRequestError):
        OrderRequest(
            client_order_id="not-a-kalpamani-id",
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=1,
            order_type=OrderType.MARKET,
            role=OrderRole.ENTRY,
        )


def test_order_request_rejects_non_positive_quantity(identity: TradeIdentity) -> None:
    for quantity in (0, -1):
        with pytest.raises(OrderRequestError):
            OrderRequest(
                client_order_id=identity.entry_order_id,
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=quantity,
                order_type=OrderType.MARKET,
                role=OrderRole.ENTRY,
            )


def test_stop_order_requires_stop_price(identity: TradeIdentity) -> None:
    with pytest.raises(OrderRequestError):
        OrderRequest(
            client_order_id=identity.protective_order_id,
            symbol="SPY",
            side=OrderSide.SELL,
            quantity=1,
            order_type=OrderType.STOP_MARKET,
            role=OrderRole.PROTECTIVE,
        )


def test_protective_stop_is_below_fill_and_wide() -> None:
    """TEST PARAMETER: deliberately wide, so it is unlikely to trigger mid-run."""
    stop = protective_stop_price(SPY_PRICE)
    assert stop < SPY_PRICE
    assert stop == (SPY_PRICE * Decimal("0.90")).quantize(Decimal("0.01"))


def test_recovered_record_without_an_account_binding_is_refused(
    identity: TradeIdentity,
) -> None:
    """State written before accounts were bound, or tampered with, is not usable.

    Refusing is the point: an unbound record cannot be proven to belong to the
    session that is connected now, so it must never reach a broker.
    """
    from dataclasses import replace

    unbound = replace(filled_record(identity), account_fingerprint=None)
    with pytest.raises(ExecutionArmError, match="not bound to a brokerage account"):
        assert_arm_not_reusable(unbound)


def test_protective_stop_rejects_bad_price() -> None:
    with pytest.raises(Phase2EnvelopeError):
        protective_stop_price(Decimal("0"))


# --------------------------------------------------------------------------
# Round 7 -- the regular-hours certification window is CODE, not a runbook line
# --------------------------------------------------------------------------


def test_window_accepts_the_liquid_middle_of_the_session() -> None:
    for moment in (time(9, 45), time(12, 0), time(15, 30)):
        assert_within_certification_window(moment, regular_session_open=True)


@pytest.mark.parametrize(
    "moment",
    [time(4, 0), time(9, 29), time(9, 44), time(15, 31), time(16, 1), time(19, 30)],
)
def test_window_rejects_the_auctions_and_extended_hours(moment: time) -> None:
    with pytest.raises(TradingWindowError, match="outside the Phase 2 certification window"):
        assert_within_certification_window(moment, regular_session_open=True)


def test_a_closed_exchange_is_refused_however_good_the_clock_looks() -> None:
    """Only the calendar knows about holidays and early closes."""
    with pytest.raises(TradingWindowError, match="regular session is not open"):
        assert_within_certification_window(time(12, 0), regular_session_open=False)


def test_window_bounds_are_the_documented_test_window() -> None:
    assert (PHASE2_WINDOW_OPEN, PHASE2_WINDOW_CLOSE) == (time(9, 45), time(15, 30))
    assert PHASE2_TIME_ZONE == "America/New_York"


# --------------------------------------------------------------------------
# Round 7 -- main.py structure: a halt must not drop broker events
# --------------------------------------------------------------------------


def _phase2_function(name: str) -> ast.FunctionDef:
    tree = ast.parse(PHASE2_MAIN.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {PHASE2_MAIN}")


def _attributes(node: ast.AST) -> set[str]:
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}


def _called_methods(node: ast.AST) -> set[str]:
    return {
        n.func.attr
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }


def _first_line_calling(node: ast.AST, method: str) -> int:
    lines = [
        n.lineno
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == method
    ]
    assert lines, f"{method} is never called"
    return min(lines)


def test_broker_event_ingestion_is_not_gated_on_the_halt_latch() -> None:
    """An order already at the broker can still fill after a halt. Returning
    early would not stop that -- it would only stop us recording it."""
    assert "_normal_progression_halted" not in _attributes(_phase2_function("on_order_event"))


def test_the_reconcile_cycle_is_gated_on_the_halt_latch() -> None:
    """The other half of the same rule: no NEW normal decisions after a halt."""
    assert "_normal_progression_halted" in _attributes(_phase2_function("_on_cycle"))


def test_an_entry_fill_routes_protection_through_the_guarded_path() -> None:
    called = _called_methods(_phase2_function("on_order_event"))
    assert "_dispatch_protection" in called
    assert "_dispatch" not in called, "protection must not bypass the post-halt guard"


def test_the_fence_is_acquired_before_any_broker_order_call() -> None:
    """Round 4, asserted structurally so it cannot be reordered by accident."""
    dispatch_fn = _phase2_function("_dispatch")
    fence_line = _first_line_calling(dispatch_fn, "fence_dispatch")
    for order_api in ("market_order", "stop_market_order"):
        assert fence_line < _first_line_calling(dispatch_fn, order_api)


def test_every_cycle_with_a_trade_re_proves_the_account_binding() -> None:
    cycle = _phase2_function("_on_cycle")
    called = _called_methods(cycle)
    assert "assert_session_binding" in called
    assert _first_line_calling(cycle, "assert_session_binding") < _first_line_calling(
        cycle, "assess_recovery"
    )


def test_arming_checks_the_window_before_consuming_the_arm() -> None:
    arm = _phase2_function("_maybe_arm")
    assert "_window_eligible" in _called_methods(arm)
    assert _first_line_calling(arm, "_window_eligible") < _first_line_calling(arm, "authorize")
