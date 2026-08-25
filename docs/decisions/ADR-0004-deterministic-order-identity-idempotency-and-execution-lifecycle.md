# ADR-0004 — Deterministic Order Identity, Idempotency, and Execution Lifecycle

- **Status:** Accepted
- **Date:** 2026-08-25
- **Deciders:** Project owner (human governance)
- **Relates to:** ADR-0002 (BrokerAdapter and the Brokerage Boundary), ADR-0003 (Broker-Side Order Controls Are Not Safety Invariants)
- **Authority:** Blueprint V2.1 §16 — *"Deterministic client/order IDs for idempotency and duplicate-order prevention"*
- **Required by:** ADR-0002 §12, which forbids automated order testing until this exists

---

## Context

Phase 1 proved the read-only path. Phase 2 opens the first write path: a single
**BUY 1 SPY** on IBKR Paper, protected, reconciled, restarted, and closed.

The moment an order path exists, three assumptions that carried Phase 1 stop holding:

1. **The broker will not stop us.** ADR-0003 established that IBAutomater unselects
   IB Gateway's `[Read-Only API]` and bypasses every API order precaution on every start.
   There is no broker-side backstop. Whatever prevents a duplicate order must be ours.
2. **Restarts are normal, not exceptional.** IBKR forces a weekly restart (Sunday 21:00 UTC)
   and a daily one (23:45 local). LEAN reconnects. IB Gateway reconnects. Any of these can
   land mid-lifecycle, and each is an opportunity to re-run the same code against the same
   inputs.
3. **Process memory is not a record.** A duplicate-prevention scheme held only in RAM is
   erased by exactly the event it must survive.

The failure this ADR exists to prevent is narrow and severe: **the same trade intent
producing more than one entry order.** In Phase 2 that is one unwanted share of SPY. In
production it is an unbounded position built by a restart loop.

---

## Decision

### 1. Four identity levels, each with a distinct job

| Identifier | Scope | Lifetime | Derivation |
|---|---|---|---|
| `trade_intent_id` | One decision to establish one position | Permanent | Deterministic from a stable natural key |
| `execution_id` | One attempt to realise that intent through a broker | Permanent per attempt | Deterministic from `trade_intent_id` + `attempt` |
| `client_order_id` | One order sent to the broker | Permanent | Deterministic from `execution_id` + role + ordinal |
| Broker order id | The broker's own handle | Broker-assigned | **Never** derived; recorded, never branched on |

The broker's identifier is deliberately last and deliberately inert. Per ADR-0002 §4,
strategy and lifecycle logic must not depend on broker-assigned identifiers; they are
carried for reconciliation and audit only.

### 2. Identity is derived, never generated

No `uuid4()`. No timestamps. No counters that live in memory. Every identifier is a pure
function of durable inputs:

```
trade_intent_id  = "km-" + sha256("v1|" + intent_natural_key)[:16]
execution_id     = "ex-" + sha256("v1|" + trade_intent_id + "|" + attempt)[:16]
client_order_id  = "km-" + intent_short + "-" + role + "-" + ordinal
```

The consequence is the property Phase 2 must prove: **a restarted process recomputes
byte-identical identifiers from durable state.** It can therefore recognise its own prior
orders at the broker rather than issuing new ones.

`attempt` increments **only** on an explicit new human authorization. A restart, reconnect,
crash or redeploy must never increment it. That single rule is what makes
*restart ≠ replay intent* true.

`client_order_id` is carried to LEAN as the order **tag**, so broker-side orders remain
attributable to a KalpaMani intent without depending on broker-assigned numbering.

### 3. Roles are closed

```
ENTRY       — establishes the position. At most ONE per execution.
PROTECTIVE  — protects filled quantity. Sized from actual fills only.
EXIT        — closes remaining quantity.
```

`ENTRY` is capped at one per execution structurally, not by convention: requesting a second
entry for an execution that already has one raises rather than returning an identifier.

### 4. Idempotency is enforced by durable state, then confirmed against the broker

Before any submission, both gates must pass:

1. **Durable check** — is a `client_order_id` for this (execution, role, ordinal) already
   recorded as submitted? If yes, **do not resubmit**.
2. **Broker check** — does an order or position attributable to this identity already exist?
   If yes, **adopt it**; do not create another.

Neither alone is sufficient. Durable state can be stale if the process died between
submission and write; the broker can lag. Requiring agreement is what makes the crash window
survivable, and disagreement is a **fail-closed** condition, not something to reconcile
optimistically.

### 4a. The send fence — amended 2026-08-25

An earlier version of this ADR said the write-ahead rule made the reverse case (order at
broker, no record) *impossible*. **That was wrong**, and the correction matters enough to
state plainly.

No transaction spans "call the broker" and "record that we called it". Whichever order those
happen in, a crash can fall between them. Recording *after* the call would leave a state
meaning "definitely not sent" **after a successful send** — and recovery acting on that claim
would issue a second order. For a protective stop or an exit, that is a second SELL and a
possible short position.

So the durable marker is written **before** the broker call, and its meaning is deliberately
weaker than "we sent it":

```
INTENT_RECORDED   the dispatcher has NOT committed to contacting the broker.
                  We can defend the claim that the order does not exist.

SEND_FENCED       the SEND FENCE is durable. From here a broker call MAY have
                  happened. Automatic resend is FORBIDDEN.
```

The mandatory ordering is:

1. record the order intent (durable)
2. **acquire the send fence (durable)**
3. only then call the broker
4. broker events and reconciliation promote to `ACKNOWLEDGED` / `FILLED` / `CANCELLED` /
   `REJECTED`

**A crash immediately before the broker call and a crash immediately after it are
indistinguishable from durable state.** Both leave `SEND_FENCED`, and both halt for human
reconciliation. That conservative ambiguity is the intended trade: safety over automatic
liveness.

Crucially, **absence from the broker's open-order list is not evidence the order never
arrived** — it may have filled, been cancelled, or simply not be visible yet. Only positive
broker evidence may resolve a fenced order, and only into `ACKNOWLEDGED` or `FILLED`.

### 5. Durable state is required; its absence fails closed

Phase 2 uses a **local append-safe JSON store** under `.runtime/` (git-ignored). It is
deliberately minimal, and deliberately behind a `TradeStateStore` Protocol so PostgreSQL can
replace it without touching lifecycle logic.

Rules:

- Writes are **atomic** (temp file + `os.replace`), so a crash mid-write cannot corrupt state.
- A **schema version** is recorded; an unrecognised version fails closed.
- If state is **missing, unreadable or corrupt** while a trade is expected to exist, the
  system **fails closed**. It never assumes "no record" means "nothing happened" — that
  assumption is precisely how a restart becomes a duplicate order.

### 6. Lifecycle states, and the transitions between them

```
CREATED -> AUTHORIZED -> ENTRY_SUBMITTED -> ENTRY_ACKNOWLEDGED
                                              |
                                    +---------+---------+
                                    v                   v
                            PARTIALLY_FILLED    ->    FILLED
                                                        |
                                                        v
                                             PROTECTION_SUBMITTED
                                                        |
                                                        v
                                                    PROTECTED
                                                        |
                                                        v
                                                  EXIT_REQUESTED
                                                        |
                                                        v
                                                   EXIT_SUBMITTED
                                                        |
                                                        v
                                                      CLOSED
                                                        |
                                                        v
                                                    RECONCILED   (terminal, success)

RECOVERING  — entered on restart from any non-terminal state; must reconcile before acting
FAILED      — terminal. Unknown or contradictory state lands here and stays.
```

**Rules that make this a safety mechanism rather than documentation:**

- Transitions are explicit and **validated**. An undeclared transition raises.
- `FAILED` and `RECONCILED` are **terminal**. Nothing leaves them.
- Any state not recognised by this version of the code is treated as **contradictory** and
  fails closed — it is never coerced to the nearest known state.
- `RECOVERING` may only be entered from a non-terminal state on restart, and may only be
  left after successful broker reconciliation.
- Reaching `FILLED` without reaching `PROTECTED` within the protection window is a
  **highest-severity failure** surfaced as `UNPROTECTED POSITION`. It never triggers another
  entry.

### 7. Fill handling is driven by actual filled quantity

Protection is sized from **filled quantity reported by the broker**, never requested
quantity. Zero filled means **no protective order is created** — a stop for a position that
does not exist is a fabricated safety claim, and would itself be capable of opening a short.

Fill events are **idempotent by broker fill identity**: a repeated event for a fill already
recorded changes nothing and creates no second protective order.

### 8. A position is "protected" only when the broker says so

`PROTECTED` requires broker reconciliation confirming **all** of:

- protective order acknowledged and working
- correct symbol
- `SELL` side
- quantity equal to the actual filled long quantity
- attributable to the correct `trade_intent_id`

LEAN events alone do not establish this. Explicit broker reconciliation does.

### 9. Exit must not be able to create a short

The ordering is mandatory and non-negotiable:

1. reconcile current position and protective order
2. **cancel protection first**, and confirm the cancellation
3. only then submit the closing `SELL` for the **remaining long quantity**
4. reconcile to flat

An exit quantity may never exceed the current long position. Leaving a working stop after
the long is closed would let it fill and open an unintended short — so removing protection
before closing is a safety requirement, not tidiness.

Broad `Liquidate()` is forbidden: it acts on the whole account, not on our trade intent, and
would touch positions KalpaMani does not own.

### 10. Strategy code gains nothing

The order-capable boundary lives in `kalpamani.execution` and `kalpamani.broker`. Modules
under `strategies/`, `research/`, `portfolio/` and `risk/` **must not** import it. Enforced
by test, not convention. Phase 2 adds execution plumbing and **no** strategy logic.

---

## Consequences

**Positive**

- Duplicate entry becomes structurally impossible rather than unlikely: identity is derived,
  submission is write-ahead-logged, and two independent sources must agree.
- Restart, reconnect and redeploy converge to the same identifiers, so recovery is adoption
  rather than re-issue.
- The `TradeStateStore` boundary means the PostgreSQL migration is an implementation swap.

**Negative / accepted**

- Every submission costs a durable write and a broker query. Irrelevant at swing-trading
  cadence; would matter for high-frequency work, which this system is not.
- Fail-closed on ambiguity means the system will sometimes stop when a human would have
  judged it safe. That is the intended trade: a halted system is recoverable, a duplicated
  position is not.
- A JSON file is not a database. Accepted for Phase 2 only, behind a Protocol.

---

## Scope limits

This ADR authorises the **minimum** order-capable boundary for Phase 2 certification:
one intent, one entry, one protective order, one exit, on **SPY only**, **long only**,
**exactly 1 share**, **IBKR Paper only**, under a one-time human execution arm that expires
on use.

It does **not** authorise strategy-generated orders, shorts, options, leverage, pyramiding,
averaging down, autonomous retries, or live trading. `LIVE_TRADING_HARD_DISABLED` remains
`True` and both gates from ADR-0001 remain closed.

---

## Verification

Enforced by `tests/unit/test_phase2_order_safety.py` and `scripts/phase2_preflight.py`:

deterministic identity reproducibility · send fence durable **before** the broker call ·
crash on either side of the broker call never resends · duplicate submission refused ·
restart adopts rather than re-issues · SPY-only · long-only · quantity
exactly 1 · notional ceiling USD 1,000 · single intent · single entry · zero-fill creates no
protection · protection equals actual filled quantity · duplicate fill events create no
second stop · exit cannot exceed long quantity · protection cancelled before close · missing
or corrupt durable state fails closed · contradictory broker/internal state fails closed ·
strategy modules cannot import execution · strategy capital remains USD 80,000 · live
remains hard-disabled.

---

## Follow-ups

Listed by topic. Numbers are taken when the ADR is written, from the next unused number in
`docs/decisions/`.

- **PostgreSQL-backed trade state store** — replacing the Phase 2 JSON implementation.
- **Point-in-time data provider selection** — after the Phase-0 data audit.
- **Live-execution Gate 2 authorization mechanism** — before live trading is considered.
