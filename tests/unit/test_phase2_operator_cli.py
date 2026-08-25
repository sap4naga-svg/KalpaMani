"""The operator CLI is a safety surface, so it is tested like one.

These drive the REAL functions in `scripts/phase2_arm.py` and
`scripts/phase2_preflight.py` — not re-implementations of what they are supposed
to do. A review found that `main.py` supported certification runs while the arm
script had no way to select one, so a normal arm still deployed run 1: the wiring
between the two was the defect, and only a test that crosses it can see that.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from kalpamani.execution.envelope import (
    PHASE2_CONFIRMATION_PHRASE,
    certification_identity,
)
from kalpamani.execution.halt import (
    HaltClearanceError,
    HaltKind,
    OperationalHalt,
    assert_halt_belongs_to,
)
from kalpamani.execution.identity import OrderRole
from kalpamani.execution.lifecycle import TradeState
from kalpamani.execution.session import (
    ArmReceipt,
    ArmReceiptError,
    BrokerSessionEvidence,
    account_fingerprint,
    arm_receipt_paths,
    assert_arm_matches_record,
    read_arm_receipts,
    write_arm_receipt,
)
from kalpamani.execution.state_store import (
    JsonTradeStateStore,
    ResolutionKind,
    TradeRecord,
    fence_dispatch,
    record_order_intent,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
PAPER_ACCOUNT_ID = "DU1234567"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


#: The actual operator scripts, imported by path because `scripts/` is not a package.
ARM = _load("phase2_arm_under_test", REPO_ROOT / "scripts" / "phase2_arm.py")
PREFLIGHT = _load("phase2_preflight_under_test", REPO_ROOT / "scripts" / "phase2_preflight.py")


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the real scripts at a throwaway runtime workspace."""
    project = tmp_path / "phase2_order_lifecycle"
    storage = tmp_path / "storage"
    project.mkdir()
    storage.mkdir()
    (project / "config.json").write_text(json.dumps({"parameters": {}}), encoding="utf-8")
    deployment = tmp_path / "lean.json"
    deployment.write_text(json.dumps({"ib-account": PAPER_ACCOUNT_ID}), encoding="utf-8")

    for module in (ARM, PREFLIGHT):
        monkeypatch.setattr(module, "RUNTIME_PROJECT", project, raising=False)
        monkeypatch.setattr(module, "RUNTIME_STORAGE", storage, raising=False)
        monkeypatch.setattr(module, "RUNTIME_CONFIG", project / "config.json", raising=False)
        monkeypatch.setattr(
            module, "RUNTIME_STATE", storage / "phase2_trade_state.json", raising=False
        )
        monkeypatch.setattr(module, "LEAN_DEPLOYMENT_CONFIG", deployment, raising=False)
    monkeypatch.setattr(ARM, "is_git_ignored", lambda _path: True, raising=False)
    return tmp_path


def params(workspace: Path) -> dict[str, str]:
    config = json.loads((workspace / "phase2_order_lifecycle" / "config.json").read_text("utf-8"))
    return dict(config.get("parameters", {}))


def evidence(account_id: str = PAPER_ACCOUNT_ID) -> BrokerSessionEvidence:
    return BrokerSessionEvidence(account_id=account_id, trading_mode="paper", source="test")


def store(workspace: Path) -> JsonTradeStateStore:
    return JsonTradeStateStore(workspace / "storage" / "phase2_trade_state.json")


def record_for(run: int, *, state: TradeState = TradeState.PROTECTED) -> TradeRecord:
    identity = certification_identity(run)
    record = TradeRecord(
        trade_intent_id=identity.trade_intent_id,
        execution_id=identity.execution_id,
        natural_key=identity.natural_key,
        attempt=identity.attempt,
        symbol="SPY",
        state=state,
        requested_quantity=1,
        arm_consumed=True,
        account_fingerprint=account_fingerprint(PAPER_ACCOUNT_ID),
    )
    return record_order_intent(
        record,
        client_order_id=identity.entry_order_id,
        role=OrderRole.ENTRY,
        symbol="SPY",
        side="BUY",
        quantity=1,
    )


# ---------------------------------------------------------------------------
# 1. The run selector reaches the CLI
# ---------------------------------------------------------------------------


def test_arming_without_a_run_is_refused(workspace: Path) -> None:
    """`main.py` reads phase2_run_number; without this the CLI never wrote one,
    so every arm silently deployed run 1."""
    assert ARM.arm(PHASE2_CONFIRMATION_PHRASE, None) == 1
    assert params(workspace) == {}, "nothing was written"


@pytest.mark.parametrize("run", [0, -1, -99])
def test_arming_with_a_non_positive_run_is_refused(workspace: Path, run: int) -> None:
    assert ARM.arm(PHASE2_CONFIRMATION_PHRASE, run) == 1
    assert params(workspace) == {}


def test_arming_run_2_writes_the_run_and_derives_a_new_identity(workspace: Path) -> None:
    store(workspace).put(record_for(1, state=TradeState.FAILED))

    assert ARM.arm(PHASE2_CONFIRMATION_PHRASE, 2) == 0

    written = params(workspace)
    assert written[ARM.RUN_NUMBER_KEY] == "2"
    assert written["explicit_execution_arm"] == "true"
    assert written[ARM.ACCOUNT_FINGERPRINT_KEY] == account_fingerprint(PAPER_ACCOUNT_ID)

    # The engine derives its identity from exactly this parameter.
    engine_identity = certification_identity(int(written[ARM.RUN_NUMBER_KEY]))
    assert engine_identity.trade_intent_id == certification_identity(2).trade_intent_id
    assert engine_identity.trade_intent_id != certification_identity(1).trade_intent_id
    assert engine_identity.entry_order_id != certification_identity(1).entry_order_id


def test_a_malformed_run_selector_makes_the_arm_invalid(workspace: Path) -> None:
    """Not "defaults to 1" -- run 1 is a failed certification, not a fallback."""
    for raw in ("", "two", "0", "-1", "1.5"):
        assert ARM.selected_run({ARM.RUN_NUMBER_KEY: raw}) is None
    assert ARM.selected_run({ARM.RUN_NUMBER_KEY: "2"}) == 2


def test_arming_is_refused_while_an_earlier_run_is_unresolved(workspace: Path) -> None:
    store(workspace).put(record_for(1, state=TradeState.PROTECTED))
    assert ARM.arm(PHASE2_CONFIRMATION_PHRASE, 2) == 1
    assert params(workspace) == {}


def test_a_run_cannot_be_armed_twice(workspace: Path) -> None:
    store(workspace).put(record_for(1, state=TradeState.FAILED))
    store(workspace).put(record_for(2, state=TradeState.FAILED))
    assert ARM.arm(PHASE2_CONFIRMATION_PHRASE, 2) == 1


# ---------------------------------------------------------------------------
# 2. Clearing a halt inspects the halted run -- the fail-open regression
# ---------------------------------------------------------------------------


def test_clear_halt_refuses_when_the_halt_belongs_to_another_run() -> None:
    """THE regression. Run 2 holds an unresolved SEND FENCE and owns the halt;
    run 1 was manually resolved and would sail through every gate.

    With the loader hard-coded to run 1, clearing would have validated the wrong
    trade and deleted a halt protecting a live one.
    """
    run_two = certification_identity(2)
    halt = OperationalHalt(
        "run 2 send fence unresolved",
        HaltKind.MANUAL_CLEARANCE_REQUIRED,
        trade_intent_id=run_two.trade_intent_id,
    )
    resolved_run_one = replace(
        record_for(1, state=TradeState.FAILED),
        resolution=ResolutionKind.MANUAL_BROKER_CLOSE,
    )

    with pytest.raises(HaltClearanceError, match="belongs to run"):
        assert_halt_belongs_to(halt, resolved_run_one)


def test_clear_halt_accepts_the_run_that_raised_it() -> None:
    run_two = certification_identity(2)
    halt = OperationalHalt(
        "run 2 halted", HaltKind.MANUAL_CLEARANCE_REQUIRED, trade_intent_id=run_two.trade_intent_id
    )
    assert_halt_belongs_to(halt, record_for(2, state=TradeState.FAILED))


def test_a_trade_bound_halt_refuses_a_missing_run() -> None:
    halt = OperationalHalt(
        "bound", HaltKind.MANUAL_CLEARANCE_REQUIRED, trade_intent_id="ti-whatever"
    )
    with pytest.raises(HaltClearanceError, match="no run was selected"):
        assert_halt_belongs_to(halt, None)


def test_an_unbound_legacy_halt_does_not_pretend_to_belong_to_a_run() -> None:
    """A v1 halt predates run binding. It is UNBOUND, not "yours"."""
    halt = OperationalHalt("legacy", HaltKind.MANUAL_CLEARANCE_REQUIRED)
    assert halt.is_trade_bound is False
    assert_halt_belongs_to(halt, record_for(1))  # permitted, but only because it is unbound


def test_run_2_unresolved_send_fence_cannot_be_bypassed(workspace: Path) -> None:
    """Even with the right run selected, the fence still blocks clearance."""
    identity = certification_identity(2)
    fenced = fence_dispatch(record_for(2), identity.entry_order_id)
    with pytest.raises(HaltClearanceError, match="unresolved SEND FENCE"):
        ARM.assert_halt_clearable(fenced, evidence())


@pytest.mark.parametrize("bound", ["ti-x", ""], ids=["trade-bound", "unbound"])
def test_clear_halt_without_a_run_is_refused(workspace: Path, bound: str) -> None:
    """--run is REQUIRED, with no fallback to the deployment config.

    An earlier version read the run from `phase2_run_number` when --run was
    omitted. That made the selector effectively optional, and it cleared a halt
    during a smoke test that passed no run at all. An unbound halt must be
    refused too: "no run stated" is not "any run will do".
    """
    halt_store = ARM.JsonHaltStore(ARM.halt_state_path(workspace / "storage"))
    halt_store.put(OperationalHalt("x", HaltKind.MANUAL_CLEARANCE_REQUIRED, trade_intent_id=bound))
    config = workspace / "phase2_order_lifecycle" / "config.json"
    config.write_text(json.dumps({"parameters": {"phase2_run_number": "1"}}), encoding="utf-8")

    assert ARM.clear_halt("CLEAR PHASE2 HALT", None) == 1
    assert halt_store.get() is not None, "the halt survives a run-less clearance attempt"


def test_clear_halt_loads_the_selected_run(workspace: Path) -> None:
    store(workspace).put(record_for(2, state=TradeState.FAILED))
    loaded = ARM.load_trade_record_for_run(2)
    assert loaded is not None
    assert loaded.trade_intent_id == certification_identity(2).trade_intent_id
    assert ARM.load_trade_record_for_run(1) is None


# ---------------------------------------------------------------------------
# 3. Preflight receipts follow the selected run
# ---------------------------------------------------------------------------


def consumed_receipt(run: int) -> ArmReceipt:
    return ArmReceipt(
        trade_intent_id=certification_identity(run).trade_intent_id,
        account_fingerprint=account_fingerprint(PAPER_ACCOUNT_ID),
        consumed=True,
    )


def select_run(workspace: Path, run: int | None) -> None:
    config = workspace / "phase2_order_lifecycle" / "config.json"
    payload = json.loads(config.read_text("utf-8"))
    payload["parameters"] = {} if run is None else {"phase2_run_number": str(run)}
    config.write_text(json.dumps(payload), encoding="utf-8")


def test_preflight_derives_receipt_paths_from_the_selected_run(workspace: Path) -> None:
    select_run(workspace, 2)
    assert PREFLIGHT.selected_run_number() == 2
    paths = PREFLIGHT.runtime_arm_receipts(2)
    assert all(certification_identity(2).trade_intent_id in p.name for p in paths)
    assert set(paths).isdisjoint(set(PREFLIGHT.runtime_arm_receipts(1)))


def test_a_run_1_receipt_never_stands_in_for_run_2(workspace: Path) -> None:
    write_arm_receipt(consumed_receipt(1), PREFLIGHT.runtime_arm_receipts(1))
    select_run(workspace, 2)

    assert read_arm_receipts(PREFLIGHT.runtime_arm_receipts(2)) == []
    assert read_arm_receipts(PREFLIGHT.runtime_arm_receipts(1))[0].consumed is True
    assert PREFLIGHT.check_arm_receipts(state_present=False) is True


def test_run_2_receipt_and_record_must_agree(workspace: Path) -> None:
    write_arm_receipt(consumed_receipt(2), PREFLIGHT.runtime_arm_receipts(2))
    run_two = record_for(2, state=TradeState.FAILED)

    assert_arm_matches_record(
        PREFLIGHT.runtime_arm_receipts(2),
        trade_intent_id=run_two.trade_intent_id,
        account_fingerprint_value=run_two.account_fingerprint,
        arm_consumed=run_two.arm_consumed,
    )

    with pytest.raises(ArmReceiptError):
        assert_arm_matches_record(
            PREFLIGHT.runtime_arm_receipts(2),
            trade_intent_id=run_two.trade_intent_id,
            account_fingerprint_value=account_fingerprint("DU7654321"),
            arm_consumed=True,
        )


def test_run_1_legacy_receipt_paths_are_preserved(workspace: Path) -> None:
    """Run 1 keeps the filenames it actually wrote; that is where its evidence is."""
    legacy = arm_receipt_paths(
        workspace / "storage",
        workspace / "phase2_order_lifecycle",
        certification_identity(1).trade_intent_id,
        legacy=True,
    )
    assert [p.name for p in legacy] == [
        "phase2_arm_receipt.json",
        ".phase2_arm_receipt.json",
    ]
    assert set(PREFLIGHT.runtime_arm_receipts(1)) == set(legacy)


def test_an_unselected_run_makes_the_preflight_arm_invalid(workspace: Path) -> None:
    select_run(workspace, None)
    assert PREFLIGHT.selected_run_number() is None
