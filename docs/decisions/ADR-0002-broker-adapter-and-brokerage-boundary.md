# ADR-0002 — BrokerAdapter and the Brokerage Boundary

- **Status:** Accepted
- **Date:** 2026-08-24
- **Deciders:** Project owner (human governance)
- **Supersedes:** —
- **Relates to:** ADR-0001 (System Foundation)
- **Authority:** Blueprint V2.1 (`docs/architecture/KalpaMani_Blueprint_V2_1.pdf`), §16, §17, §26

---

## Context

Phase 1 introduces the first real contact between KalpaMani and a brokerage: a read-only
IBKR **Paper** connectivity smoke test through QuantConnect LEAN. Before any brokerage
code exists, the boundary that keeps IBKR replaceable and keeps broker state from leaking
into strategy logic must be written down.

Blueprint V2.1 §26 requires: *"Keep the same broker-adapter abstraction so IBKR can be
replaced or supplemented later."* §17 keeps market data deliberately independent of the
broker. §16 requires deterministic client/order IDs for idempotency before automation.

The single most dangerous coupling this ADR prevents is the one already identified in
ADR-0001: the IBKR Paper account reports roughly **USD 1,000,000** of simulated equity,
while KalpaMani strategy capital is **USD 80,000**. Any code path that lets broker equity
reach a sizing calculation inflates every position by 12.5x.

---

## Decision

### 1. IBKR is the initial production broker

Interactive Brokers (IBKR Pro) is the primary long/short execution venue for V1, reached
through QuantConnect LEAN's officially supported Interactive Brokers brokerage
integration. We do not write a custom IBKR connection layer.

### 2. IBKR-specific behavior stays behind a `BrokerAdapter` boundary

All broker-specific behavior — connection lifecycle, authentication/session maintenance,
symbol mapping, order translation, fill semantics, account-state polling, error and
disconnect handling — lives behind a `BrokerAdapter` abstraction in
`src/kalpamani/broker/`. Everything above that boundary is broker-agnostic.

### 3. Strategy code must not call IBKR APIs directly

No module under `src/kalpamani/strategies/`, `risk/`, `portfolio/` or `research/` may
import or invoke an IBKR client, an IB Gateway/TWS API, or a LEAN brokerage class. The
only permitted path to the broker is through `BrokerAdapter`.

### 4. Strategy logic must not depend on broker-specific identifiers or structures

Strategy and risk code must not depend on:

- IBKR account IDs
- IBKR order identifiers (`permId`, `orderId`, `execId`)
- IBKR data structures (`Contract`, `Order`, `Execution`, `AccountValue`)
- IBKR-specific market-data structures (tick types, `reqMktData` payloads)

The adapter translates these into KalpaMani domain types at the boundary. Broker
identifiers may be *carried* for reconciliation and audit, but never *branched on* by
strategy logic.

### 5. Broker account equity and allocated strategy capital are separate concepts

These are two different quantities and are never interchangeable:

```
Broker account equity            (observed; informational; broker-authoritative)
        |
        v
KalpaMani allocated strategy capital   (configured; KalpaMani-authoritative)
        |
        v
Strategy risk budgets
```

### 6. Strategy capital remains USD 80,000 regardless of the IBKR Paper balance

KalpaMani strategy capital is **USD 80,000** whatever the brokerage reports. The
simulated paper balance of ~USD 1,000,000 has no effect on it. `StrategyCapital` is
immutable and offers no path from an observed broker equity to `allocated_usd`; the only
supported operation, `observe_broker_equity()`, returns a new value with the allocation
unchanged. Enforced by unit tests.

### 7. Broker account state is authoritative for execution reality

The broker is the source of truth for:

- actual positions
- actual open orders
- brokerage cash
- fills
- borrow availability / shortability (later phases)
- execution reconciliation

Blueprint V2.1 §26: *"Use broker account state as the execution source of truth; reconcile
frequently against internal state."* Where internal state disagrees with the broker, the
broker wins and the discrepancy is an alertable reconciliation event.

### 8. KalpaMani configuration is authoritative for intent

KalpaMani configuration is the source of truth for:

- allocated strategy capital
- risk budgets
- strategy permissions
- portfolio exposure constraints

The broker never overrides these. A broker that cannot fund the allocation fails closed
rather than silently shrinking budgets.

> **The split in one line:** the broker owns *what is*, KalpaMani configuration owns *what
> is allowed*. Neither may overwrite the other.

### 9. V1 automation environment is IBKR PAPER only

Automated operation targets the IBKR Paper account exclusively. Before any deployment
proceeds, the connected account identifier must be verified as a paper account. Ambiguity
about paper-vs-live is an abort condition, not a warning.

### 10. Live IBKR remains hard-disabled

The two independent gates from ADR-0001 remain in force. `LIVE_TRADING_HARD_DISABLED`
stays `True`; Gate 2 remains unimplemented. Selecting `Environment.LIVE` authorizes
nothing. Enabling live trading is a governed change requiring a further approved ADR, a
working Gate-2 mechanism and written human sign-off.

### 11. Phase 1 contains no order-submission capability

The Phase 1 smoke test is **read-only**. It contains no order-submission path of any kind:
no `MarketOrder`, `LimitOrder`, `StopMarketOrder`, `StopLimitOrder`, `SetHoldings`,
`Liquidate`, or any other order API. This is enforced by a static test over the smoke-test
source, not merely by review.

### 12. Future order interfaces must support deterministic IDs and idempotency

When an order interface is eventually introduced (Phase 2 at the earliest), it must carry
a deterministic, reproducible client order ID so that a retry, reconnect or restart can
never produce a duplicate order. Duplicate-order prevention is a precondition for any
automated order testing, per Blueprint V2.1 §16, and will be specified in a dedicated ADR
taking the next available number at the time it is written.

### 13. Market-data architecture stays separable from brokerage execution

Market-data and provider code lives in `src/kalpamani/data/`, independent of
`src/kalpamani/broker/`. Broker-supplied market data may be used for operational
verification and connectivity proofs, but Blueprint V2.1 §26 forbids using broker data as
the sole source for universe ranking or backtests. Delayed broker data is acceptable for
connectivity testing and is **never** acceptable as the basis for any performance claim.

---

## Scope of this ADR

This ADR establishes the **boundary**, not the implementation. The full `BrokerAdapter` is
deliberately **not** built in Phase 1.

A minimal, read-only Protocol may be introduced to make the boundary real and testable —
specifically a `BrokerAccountSnapshot` value type and a read-only account-state Protocol.
It must expose **no** order-submission method. Adding one is an ADR-level change.

---

## Consequences

**Positive**

- IBKR is replaceable; a second broker means a second adapter, not a rewrite.
- Strategy logic stays testable without a brokerage, since it never sees broker types.
- The 12.5x paper-equity sizing error is structurally impossible rather than merely
  documented.
- Making the read-only interface literally incapable of expressing an order means Phase 1
  cannot submit one even by mistake.

**Negative / accepted costs**

- Translation at the boundary costs code and a little latency. Accepted: the alternative
  is broker types leaking into risk and strategy logic.
- LEAN already provides its own brokerage abstraction, so there is some conceptual overlap.
  We keep ours because LEAN's abstraction is not ours to control, and because strategy code
  must remain runnable outside LEAN.

---

## Verification

- Static test: the smoke-test source contains no order-submission API.
- Static test: no order-capable adapter can be instantiated in Phase 1.
- Unit test: strategy capital stays USD 80,000 after observing USD 1,000,000 broker equity.
- Unit test: broker equity cannot mutate `StrategyCapital`.
- Unit test: `Environment.LIVE` cannot authorize order submission.
- Unit test: ambiguous brokerage/account mode fails closed.

---

## Follow-ups

> **Numbers are assigned at write time**, by taking the next unused number in
> `docs/decisions/`. Follow-ups are listed by topic only. Pre-assigning numbers here caused
> two conflicts already (ADR-0002 and ADR-0003 were both claimed in advance by items that
> had not been written yet), so this list deliberately does not do it.

- **Order idempotency and deterministic client/order IDs** — required by ADR-0002 §12
  *before* any automated order testing, i.e. before Phase 2 implementation.
- **Point-in-time data provider selection** — after the Phase-0 data audit.
- **Live-execution Gate 2 authorization mechanism** — before live trading is considered.
