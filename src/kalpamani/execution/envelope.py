"""The Phase 2 safety envelope and one-time execution arm (ADR-0004 §Scope).

Phase 2 is allowed to place exactly one order that establishes a position:
**BUY 1 SPY on IBKR Paper**, long only, under USD 1,000 notional, once.

Every constraint here is checked before an order can even be named, and each one
fails closed. ADR-0003 is the reason this is thorough: IBAutomater disables IB
Gateway's ``[Read-Only API]`` and bypasses its order precautions on every start,
so there is no broker-side backstop. These checks are the only thing between the
system and an unintended order.

The arm is **one-time**. Once a trade intent is authorised, the arm is consumed
and recorded durably. A restart, reconnect or redeploy re-reads that record and
finds the arm spent -- recovery reconciles, it never re-arms.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from kalpamani.broker.account import BrokerAccountMode
from kalpamani.common.capital import DEFAULT_STRATEGY_CAPITAL_USD, StrategyCapital
from kalpamani.common.environment import Environment
from kalpamani.common.errors import SafetyViolationError
from kalpamani.common.settings import Settings
from kalpamani.execution.identity import TradeIdentity
from kalpamani.execution.session import BrokerSessionEvidence, verify_paper_session
from kalpamani.execution.state_store import TradeRecord, TradeStateStore

# ---------------------------------------------------------------------------
# The envelope. These are hard limits for Phase 2 certification, not defaults.
# ---------------------------------------------------------------------------

#: The only symbol Phase 2 may trade.
PHASE2_SYMBOL = "SPY"
#: The only side Phase 2 may open.
PHASE2_SIDE = "BUY"
#: Exactly one share. Not a maximum to size up to -- the only permitted value.
PHASE2_QUANTITY = 1
#: Outer notional we are willing to tolerate on the resulting fill, in USD.
#:
#: NOTE ON SEMANTICS. Phase 2 submits a MARKET order, and a market order cannot
#: mathematically guarantee its fill notional -- the fill price is whatever the
#: book gives. So this is NOT a hard maximum fill notional, and calling it one
#: would be false. It is the tolerance the certification accepts.
PHASE2_FILL_NOTIONAL_TOLERANCE_USD = Decimal("1000")

#: Fraction of the tolerance reserved as slippage headroom.
PHASE2_NOTIONAL_SAFETY_BUFFER = Decimal("0.20")

#: PRE-SUBMISSION REFERENCE-NOTIONAL GUARD, in USD.
#:
#: This is what is actually enforced, and it is enforced against the *reference*
#: price observed before submission -- not against the fill. The 20% buffer means
#: the fill would have to slip more than a fifth above the observed price to
#: breach the tolerance above, which for 1 share of SPY in liquid hours is not a
#: realistic outcome.
PHASE2_MAX_REFERENCE_NOTIONAL_USD = PHASE2_FILL_NOTIONAL_TOLERANCE_USD * (
    Decimal(1) - PHASE2_NOTIONAL_SAFETY_BUFFER
)
#: One trade intent, one entry order. Ever.
PHASE2_MAX_TRADE_INTENTS = 1
PHASE2_MAX_ENTRY_ORDERS = 1

#: Natural key of certification RUN 1. Historical: it predates run scoping, and
#: it is NOT rewritten -- run 1 is the durable evidence of a failed certification
#: and changing its key would orphan the record we are required to preserve.
PHASE2_RUN_1_NATURAL_KEY = "phase2-certification/SPY/long/1"

#: Kept as the run-1 alias so existing callers and evidence keep resolving.
PHASE2_INTENT_NATURAL_KEY = PHASE2_RUN_1_NATURAL_KEY

#: The operator phrase that records a manual broker close. Distinct from the arm
#: phrase on purpose: acknowledging a cleanup and authorising an order are not
#: the same act and must not share a confirmation.
PHASE2_MANUAL_RESOLUTION_PHRASE = "RESOLVE PHASE2 MANUAL CLOSE"

#: Why a run was resolved by hand. Deliberately not "reconciled".
MANUAL_CLOSE_REASON = "MANUAL_BROKER_CLOSE_AFTER_RESTART_IDENTITY_FAILURE"

#: Deliberately wide TEST stop distance, expressed as a fraction below fill price.
#:
#: TEST PARAMETER -- NOT PRODUCTION STRATEGY LOGIC.
#: Chosen only to be unlikely to trigger during a short certification run. It
#: encodes no view on volatility, risk or SPY, and must never be reused as a
#: strategy parameter. Real stops come from the deterministic risk engine, which
#: does not exist yet.
PHASE2_TEST_STOP_FRACTION = Decimal("0.10")


class Phase2EnvelopeError(SafetyViolationError):
    """A proposed Phase 2 action falls outside the certification envelope."""


class ExecutionArmError(SafetyViolationError):
    """The execution arm is absent, already consumed, or cannot be trusted."""


@dataclass(frozen=True, slots=True)
class ExecutionArmRequest:
    """An explicit, one-time human authorization to place the Phase 2 entry.

    Every field must be supplied deliberately. There are no defaults that would
    let an arm come into existence by accident.
    """

    #: Operator's explicit intent. Must be exactly the confirmation phrase.
    confirmation: str
    settings: Settings
    #: Evidence read from LEAN's own deployment configuration -- NOT an operator
    #: parameter. This is what ties the arm to the session actually connected.
    session_evidence: BrokerSessionEvidence
    symbol: str
    quantity: int
    reference_price: Decimal
    phase2_test_mode: bool
    explicit_execution_arm: bool

    @property
    def notional_usd(self) -> Decimal:
        return self.reference_price * Decimal(self.quantity)


#: The operator must type this exactly. A boolean flag can be set by a stray
#: environment variable; a specific phrase cannot be arrived at by accident.
PHASE2_CONFIRMATION_PHRASE = "ARM PHASE2 PAPER BUY 1 SPY"


def certification_natural_key(run_number: int) -> str:
    """The deterministic natural key for one certification run.

    Deterministic on purpose -- no timestamp, no UUID -- so every restart of the
    same run derives the same identifiers, while a *different* run derives
    genuinely different ones. A failed run keeps its identity forever; the next
    attempt does not inherit it.

    Raises:
        Phase2EnvelopeError: if ``run_number`` is not a positive integer.
    """
    if run_number < 1:
        raise Phase2EnvelopeError(
            f"Certification run number must be >= 1, got {run_number}. A run number is a "
            "deliberate human choice, not something to default into."
        )
    if run_number == 1:
        return PHASE2_RUN_1_NATURAL_KEY
    return f"{PHASE2_RUN_1_NATURAL_KEY}/run-{run_number}"


def require_run_number(raw: object) -> int:
    """Parse an explicitly selected certification run, or fail closed.

    There is deliberately no default. ``or 1`` in the engine looked harmless and
    meant that a deployment with a missing, empty or malformed run selector
    would quietly run as **run 1** -- a failed certification whose identity is
    audit evidence. A run number is a human decision; absence of one is an
    error, not a hint.

    Raises:
        Phase2EnvelopeError: if the value is absent, empty, non-integer, or < 1.
    """
    text = str(raw if raw is not None else "").strip()
    if not text:
        raise Phase2EnvelopeError(
            "No certification run was selected. Phase 2 never defaults to a run: run 1 is a "
            "completed certification and its identity is evidence, not a fallback. Set "
            "phase2_run_number explicitly."
        )
    try:
        run = int(text)
    except ValueError as exc:
        raise Phase2EnvelopeError(
            f"Certification run {text!r} is not an integer. Refusing to guess what was meant."
        ) from exc
    if run < 1:
        raise Phase2EnvelopeError(
            f"Certification run must be >= 1, got {run}. A run number is a deliberate human "
            "choice, not something to default into."
        )
    return run


def certification_identity(run_number: int) -> TradeIdentity:
    """Derive the full identity for a certification run."""
    return TradeIdentity.derive(certification_natural_key(run_number), attempt=1)


def check_envelope(request: ExecutionArmRequest) -> None:
    """Validate a proposed entry against every Phase 2 hard limit.

    Raises:
        Phase2EnvelopeError: on the first violation found.
    """
    if request.symbol != PHASE2_SYMBOL:
        raise Phase2EnvelopeError(
            f"Phase 2 permits {PHASE2_SYMBOL} only, got {request.symbol!r}. "
            "The certification envelope is one symbol; anything else is out of scope."
        )
    if request.quantity != PHASE2_QUANTITY:
        raise Phase2EnvelopeError(
            f"Phase 2 permits exactly {PHASE2_QUANTITY} share, got {request.quantity}. "
            "This is an exact value, not a ceiling to size up to."
        )
    if request.reference_price <= 0:
        raise Phase2EnvelopeError(
            f"Reference price must be positive, got {request.reference_price}. Without a "
            "trustworthy price the notional ceiling cannot be enforced."
        )
    if request.notional_usd > PHASE2_MAX_REFERENCE_NOTIONAL_USD:
        raise Phase2EnvelopeError(
            f"Reference notional {request.notional_usd} USD exceeds the pre-submission guard "
            f"of {PHASE2_MAX_REFERENCE_NOTIONAL_USD} USD "
            f"(tolerance {PHASE2_FILL_NOTIONAL_TOLERANCE_USD} USD less a "
            f"{PHASE2_NOTIONAL_SAFETY_BUFFER:%} slippage buffer). Aborting rather than "
            "reducing size: the permitted quantity is already the minimum."
        )


def check_authorization(request: ExecutionArmRequest) -> None:
    """Validate the authorization itself: mode, environment, session, intent.

    Raises:
        ExecutionArmError: if any authorization condition is unmet.
        BrokerModeError: if the broker session is not provably paper.
    """
    if not request.phase2_test_mode:
        raise ExecutionArmError(
            "phase2_test_mode is not enabled. Normal startup is read/reconcile only; "
            "an order path does not open without it."
        )
    if not request.explicit_execution_arm:
        raise ExecutionArmError("explicit_execution_arm is not set. Phase 2 never arms implicitly.")
    if request.confirmation != PHASE2_CONFIRMATION_PHRASE:
        raise ExecutionArmError(
            "Execution arm confirmation phrase does not match. A deliberate phrase is "
            "required precisely because a boolean can be set by accident."
        )
    if request.settings.environment is not Environment.PAPER:
        raise ExecutionArmError(
            f"Phase 2 requires environment={Environment.PAPER.value!r}, got "
            f"{request.settings.environment.value!r}. LIVE can never arm Phase 2."
        )
    if request.settings.live_trading_enabled:
        raise ExecutionArmError(
            "live_trading_enabled is true. Phase 2 must never run against live trading."
        )
    # Deployment-derived evidence, refusing LIVE and UNKNOWN alike.
    verify_paper_session(request.session_evidence)


def check_no_prior_test_trade(store: TradeStateStore, trade_intent_id: str) -> None:
    """Refuse to arm if an unresolved prior Phase 2 trade exists.

    A previous certification run that did not reach a terminal state may still
    hold a position or a working order. Arming on top of it would be the second
    entry this whole design exists to prevent.

    Raises:
        ExecutionArmError: if a prior record exists for this intent, or if any
            other record is still unresolved.
    """
    from kalpamani.execution.lifecycle import is_terminal  # local import: avoids cycle

    existing = store.get(trade_intent_id)
    if existing is not None:
        raise ExecutionArmError(
            f"A record already exists for trade intent {trade_intent_id} "
            f"(state={existing.state.value}, arm_consumed={existing.arm_consumed}). "
            "The Phase 2 arm is one-time. Recovery reconciles; it never re-arms."
        )
    unresolved = [r for r in store.all_records() if not is_terminal(r.state)]
    if unresolved:
        states = ", ".join(f"{r.trade_intent_id}={r.state.value}" for r in unresolved)
        raise ExecutionArmError(
            f"Unresolved prior trade(s) present: {states}. Resolve them before arming: an "
            "unresolved trade may still hold a position or a working order."
        )


def authorize_trade_intent(
    request: ExecutionArmRequest,
    store: TradeStateStore,
    *,
    identity: TradeIdentity,
    capital: StrategyCapital | None = None,
) -> tuple[TradeIdentity, TradeRecord]:
    """Run every gate and, if all pass, create the single authorised trade intent.

    The arm is consumed here: the returned record has ``arm_consumed=True`` and
    is persisted by the caller before any broker contact. A restart reads that
    flag and knows not to arm again.

    Returns:
        The derived identity and a ``CREATED``->``AUTHORIZED`` trade record.

    Raises:
        ExecutionArmError, Phase2EnvelopeError, BrokerModeError: on any failure.
    """
    from kalpamani.execution.lifecycle import TradeState, transition

    check_authorization(request)
    check_envelope(request)

    check_no_prior_test_trade(store, identity.trade_intent_id)

    allocated = (capital or StrategyCapital()).allocated_usd
    if allocated != DEFAULT_STRATEGY_CAPITAL_USD:
        raise ExecutionArmError(
            f"Strategy capital is {allocated} USD, expected {DEFAULT_STRATEGY_CAPITAL_USD}. "
            "Phase 2 must run against the standard allocation, and broker equity never "
            "sets it."
        )

    record = TradeRecord(
        trade_intent_id=identity.trade_intent_id,
        execution_id=identity.execution_id,
        natural_key=identity.natural_key,
        attempt=identity.attempt,
        symbol=request.symbol,
        state=transition(TradeState.CREATED, TradeState.AUTHORIZED),
        requested_quantity=request.quantity,
        arm_consumed=True,
        # Bind the trade to the account it was armed against. The fingerprint
        # comes from the VERIFIED deployment evidence, never from a parameter,
        # so the arm and the session cannot be two independent values that
        # disagree. Every later broker contact re-proves this binding.
        account_fingerprint=request.session_evidence.fingerprint,
    )
    return identity, record


def assert_arm_not_reusable(record: TradeRecord) -> None:
    """Assert a recovered record cannot be used to place another entry.

    Called on every recovery path. Restart means reconcile, never re-submit.

    Raises:
        ExecutionArmError: if anything would permit a second entry.
    """
    if not record.arm_consumed:
        raise ExecutionArmError(
            f"Recovered record {record.trade_intent_id} does not have the arm marked "
            "consumed. Contradictory state; failing closed rather than guessing."
        )
    if not record.account_fingerprint:
        raise ExecutionArmError(
            f"Recovered record {record.trade_intent_id} is not bound to a brokerage account. "
            "An unbound record cannot be proven to belong to the connected session, so it "
            "must never reach the broker. Failing closed."
        )
    if record.entry_count > PHASE2_MAX_ENTRY_ORDERS:
        raise ExecutionArmError(
            f"Recovered record has {record.entry_count} entry orders, limit is "
            f"{PHASE2_MAX_ENTRY_ORDERS}. This indicates a duplicate entry already occurred."
        )


def protective_stop_price(fill_price: Decimal) -> Decimal:
    """Compute the deliberately wide Phase 2 TEST stop price.

    **TEST PARAMETER -- NOT PRODUCTION STRATEGY LOGIC.** Chosen only to be
    unlikely to trigger during a short certification run. It encodes no view on
    volatility or risk and must never be reused as a strategy parameter.
    """
    if fill_price <= 0:
        raise Phase2EnvelopeError(
            f"Cannot derive a protective stop from a non-positive fill price {fill_price}."
        )
    return (fill_price * (Decimal(1) - PHASE2_TEST_STOP_FRACTION)).quantize(Decimal("0.01"))


def describe_envelope() -> str:
    """Log-safe summary of the envelope, for the preflight banner."""
    return (
        f"symbol={PHASE2_SYMBOL} side={PHASE2_SIDE} quantity={PHASE2_QUANTITY} "
        f"max_reference_notional_usd={PHASE2_MAX_REFERENCE_NOTIONAL_USD} "
        f"fill_notional_tolerance_usd={PHASE2_FILL_NOTIONAL_TOLERANCE_USD} "
        f"max_intents={PHASE2_MAX_TRADE_INTENTS} max_entries={PHASE2_MAX_ENTRY_ORDERS} "
        f"account_mode={BrokerAccountMode.PAPER.value}"
    )


__all__ = [
    "MANUAL_CLOSE_REASON",
    "PHASE2_CONFIRMATION_PHRASE",
    "PHASE2_FILL_NOTIONAL_TOLERANCE_USD",
    "PHASE2_INTENT_NATURAL_KEY",
    "PHASE2_MANUAL_RESOLUTION_PHRASE",
    "PHASE2_MAX_ENTRY_ORDERS",
    "PHASE2_MAX_REFERENCE_NOTIONAL_USD",
    "PHASE2_MAX_TRADE_INTENTS",
    "PHASE2_NOTIONAL_SAFETY_BUFFER",
    "PHASE2_QUANTITY",
    "PHASE2_RUN_1_NATURAL_KEY",
    "PHASE2_SIDE",
    "PHASE2_SYMBOL",
    "PHASE2_TEST_STOP_FRACTION",
    "ExecutionArmError",
    "ExecutionArmRequest",
    "Phase2EnvelopeError",
    "assert_arm_not_reusable",
    "authorize_trade_intent",
    "certification_identity",
    "certification_natural_key",
    "check_authorization",
    "check_envelope",
    "check_no_prior_test_trade",
    "describe_envelope",
    "protective_stop_price",
    "require_run_number",
]
