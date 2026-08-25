# Runbook — Phase 2: Controlled IBKR Paper Order Lifecycle

> ## ⚠ PAPER ONLY — THIS RUNBOOK PLACES A REAL ORDER
> Phase 2 submits a genuine order to a genuine brokerage account. It must **never**
> be used against IBKR **live**. If the connected account cannot be positively
> proven to be a paper account, **abort before submission**.

**Objective — execution plumbing certification, not a strategy:**

```
explicit human arm -> BUY 1 SPY (IBKR PAPER) -> ack -> actual fill
  -> protect ACTUAL FILLED quantity -> reconcile -> restart/reconnect
  -> recover WITHOUT duplicating -> controlled exit -> remove protection
  -> prove completely flat
```

---

## 0. ADR-0003 — read this before anything else

> **IBKR broker-side Read-Only / API precautions are NOT KalpaMani safety invariants.**

LEAN's IBAutomater **unselects** IB Gateway's `[Read-Only API]` checkbox and **selects every**
`[Bypass … for API Orders]` precaution, on **every start**. This is required for LEAN to
function and is not configurable.

**There is no broker-side backstop.** Enabling IBKR Read-Only Access does nothing for an
automated deployment. The internal deterministic controls — the execution arm, the envelope,
the durable state store, the static order-surface check — are **authoritative and sole**.
See [ADR-0003](../decisions/ADR-0003-broker-side-order-controls-are-not-safety-invariants.md).

---

## 1. The envelope — hard limits

| Constraint | Value |
|---|---|
| Brokerage | **IBKR PAPER only** |
| Symbol | **SPY only** |
| Direction | **LONG only** |
| Entry quantity | **exactly 1 share** (an exact value, not a ceiling) |
| Notional ceiling | **USD 1,000** — if SPY trades above this, **ABORT** |
| Trade intents | **1** |
| Entry orders | **1** |
| Strategy capital | **USD 80,000**, unaffected by the ~USD 1,000,000 paper balance |

Forbidden: any second symbol · shorts · options · leverage · pyramiding · averaging down ·
recurring entries · strategy-generated entries · autonomous retries that submit another entry.

Associated protective and closing orders for the *same* trade intent are permitted.

---

## 2. Identity and idempotency (ADR-0004)

Identifiers are **derived, never generated** — no `uuid4`, no timestamps, no in-memory
counters:

```
trade_intent_id  = f(natural_key)
execution_id     = f(trade_intent_id, attempt)
client_order_id  = f(execution_id, role, ordinal)   -> sent as the LEAN order tag
```

A restarted process recomputes **byte-identical** ids and therefore recognises its own prior
orders instead of issuing new ones. `attempt` increments **only** on a new human
authorization — never on a restart. That is what makes **restart ≠ replay intent**.

Durable state lives at `.runtime/lean/storage/phase2_order_lifecycle/phase2_trade_state.json`
(git-ignored). Submission intent is written **before** the order is sent. Missing or corrupt
state **fails closed** — it is never read as "nothing happened".

---

## 3. Preflight (run before every deployment)

```bash
cd C:\Trading\KalpaMani
.venv\Scripts\python.exe scripts\phase2_preflight.py
```

Must exit **0**. It proves `.runtime` is invisible to git, ships the tracked algorithm **and
the `kalpamani` package** into the runtime workspace, statically checks the order surface,
reports any unresolved durable state, and prints the arm state.

`EXECUTION ARM : NO (read/reconcile only)` means the deployment **cannot place an order**.
That is the normal, safe state.

---

## 4. Pre-order broker reconciliation

Start the deployment **disarmed** first and let it reconcile:

```bash
cd .runtime\lean
..\tools\leanvenv\Scripts\lean.exe live deploy phase2_order_lifecycle
```

Watch for `[RECONCILE:no-trade]` and confirm **all** of:

- SPY position **0**
- no KalpaMani-owned open orders
- no unresolved prior Phase 2 trade
- broker equity observed, strategy capital still USD 80,000

**Abort if** an unexpected SPY position exists, a prior trade is unresolved, or ownership of
any order or position is uncertain.

> **Never auto-liquidate.** Do not alter unrelated broker positions or orders. Orders whose
> tag is not a KalpaMani client order id belong to someone else and are never adopted or
> touched. If ownership is uncertain: **STOP** and resolve it manually.

Then `Ctrl+C` to stop cleanly.

---

## 5. Verify the account is PAPER

Three independent confirmations, all of which must agree (Phase 1 evidence model):

1. **Account id prefix** — `DU` / `DF` / `DI` = paper. `U` / `F` / `I` = **live → ABORT**.
2. **LEAN trading mode** — the log must show `Trading mode: paper`.
3. **IB Gateway** — window title contains `(Simulated Trading)`.

`BrokerAccountMode.classify()` returns `UNKNOWN` for anything unrecognised, and both the arm
script and the algorithm refuse `UNKNOWN` as well as `LIVE`. **Ambiguity is an abort
condition, never an assumption of safety.**

---

## 6. Arm the execution gate — the one deliberate act

```bash
.venv\Scripts\python.exe scripts\phase2_arm.py --status

.venv\Scripts\python.exe scripts\phase2_arm.py --arm ^
    --account-id <YOUR-PAPER-ACCOUNT-ID> ^
    --confirm "ARM PHASE2 PAPER BUY 1 SPY"
```

The phrase must be typed **exactly**. A boolean can be set by a stray environment variable;
a specific phrase cannot be arrived at by accident.

The arm is refused — with a non-zero exit — if the account classifies as live or unknown, if
the account id is missing, or if the phrase does not match. Account ids are **redacted** in
all output.

**Re-run the preflight** and confirm `EXECUTION ARM : YES` before deploying.

Disarm at any time:

```bash
.venv\Scripts\python.exe scripts\phase2_arm.py --disarm
```

---

## 7. Entry lifecycle

Deploy during **liquid trading hours** (a market order needs a real book):

```bash
cd .runtime\lean
..\tools\leanvenv\Scripts\lean.exe live deploy phase2_order_lifecycle
```

Expected log sequence:

```
[PHASE2-ARM]     envelope, identity, flags
[RECONCILE:no-trade]   spy_position=0 owned_open_orders=0
[TRADE-INTENT]   authorized ... arm_consumed=True
[ENTRY-SUBMIT]   BUY 1 SPY as km-xxxxxxxx-ENTRY-0
[ENTRY-ACK]      order=... status=... 
[FILL]           km-xxxxxxxx-ENTRY-0 filled=1 price=...
```

The arm is consumed **durably before** the order is sent.

---

## 8. Protective stop lifecycle

```
[PROTECTION-SUBMIT] SELL 1 SPY stop=... as km-xxxxxxxx-PROTECTIVE-0
                    (TEST PARAMETER -- NOT PRODUCTION STRATEGY LOGIC)
[PROTECTION-ACK]    broker confirms protection matches filled quantity
```

The stop is **10% below fill** — deliberately wide so it is unlikely to trigger during a short
certification run.

> **TEST PARAMETER — NOT PRODUCTION STRATEGY LOGIC.** It encodes no view on volatility, risk
> or SPY, and must never be reused as a strategy parameter. Real stops come from the
> deterministic risk engine, which does not exist yet.

Protection is sized from the **ACTUAL filled quantity**:

| Filled | Protective quantity |
|---|---|
| 0 | **0 — no stop is created** |
| 1 | 1 |

A stop for a position that does not exist would itself be capable of opening a short.

A position counts as **PROTECTED** only when broker reconciliation confirms the order is
acknowledged, on SPY, **SELL** side, correct quantity, and attributable to this trade intent.

### If entry fills but protection fails

```
[PHASE2-ABORT] UNPROTECTED POSITION: SPY long 1 with protective quantity 0
```

**Highest-severity Phase 2 failure.**

1. **Do NOT submit another entry.** The abort latches; the session stops.
2. Surface it immediately.
3. Decide manually: place protection by hand in IBKR, or close the position by hand.
4. Do not restart hoping it resolves itself.

---

## 9. Reconciliation

`[RECONCILE]` lines show internal vs broker truth on every cycle:

```
internal_filled=1 broker_position=1 internal_protected=1 broker_protective=1 matches=True
```

Any mismatch **fails closed** — see §12. LEAN events alone never establish broker truth;
explicit reconciliation does.

---

## 10. Restart / reconnect idempotency test — mandatory

Once the position is filled and protected, `Ctrl+C` and redeploy. On recovery expect:

```
[RECOVERY]          recovered intent=... state=PROTECTED ... entries=1 arm_consumed=True
[RECOVERY]          entry_orders_before_restart=1
[RECOVERY]          entry_orders_submitted_this_session=0
[IDEMPOTENCY-PASS]  recovery adopts existing state; no entry replay
[RECONCILE]         ... matches=True
[PROTECTION-ACK]    broker confirms protection matches filled quantity
```

**Acceptance proof:**

```
entry orders before restart = 1
entry orders after restart  = 0
```

Recovery **discovers** the position and the protective order, reconstructs lifecycle state,
recomputes the same deterministic ids, and reconciles **before** doing anything else. It does
not re-arm, does not re-enter, and does not duplicate protection.

---

## 11. Controlled exit

```bash
.venv\Scripts\python.exe scripts\phase2_arm.py --request-exit
```

Then redeploy. Ordering is **mandatory**:

```
[EXIT-REQUEST]  cancel_first=km-xxxxxxxx-PROTECTIVE-0 then_sell=1 SPY
[EXIT-REQUEST]  protection cancellation requested; will verify next cycle
[EXIT-SUBMIT]   SELL 1 SPY
[EXIT-FILL]     ...
[FINAL-RECONCILE] flat: no position, no open KalpaMani orders
```

1. reconcile position and protective order
2. **cancel protection and confirm the cancellation**
3. only then submit the closing SELL for the **remaining long quantity**
4. reconcile to flat

> **Why the order matters.** A protective SELL stop left working after the long is closed can
> fill on its own and **open an unintended SHORT position**. Cancelling first is a safety
> requirement, not tidiness. The code refuses to send the close while the stop is still live.

`Liquidate()` is **forbidden** — it acts on the whole account, including positions KalpaMani
does not own.

---

## 12. Final acceptance state

Phase 2 is complete only when IBKR confirms **all** of:

- [ ] SPY test position = **0**
- [ ] KalpaMani entry orders open = **0**
- [ ] KalpaMani protective orders open = **0**
- [ ] KalpaMani exit orders open = **0**
- [ ] accidental short SPY position = **0**
- [ ] duplicate entries = **0**
- [ ] unrelated broker positions changed = **0**
- [ ] final lifecycle state = **CLOSED → RECONCILED**

Verify independently in the IBKR account manager, not only from logs.

---

## 13. Emergency handling

| Situation | Response |
|---|---|
| **UNPROTECTED POSITION** | Do not re-enter. Protect or close by hand in IBKR. Investigate before any restart. |
| **Broker/internal mismatch** | The system fails closed and halts. Do **not** force it forward. Compare the durable state file against IBKR by hand and resolve deliberately. |
| **Accidental short** | Close it manually in IBKR immediately, then investigate how the stop outlived the long. |
| **Duplicate entry observed** | Stop everything. This is the failure ADR-0004 exists to prevent; treat it as a design defect, not an operational hiccup. |
| **Unknown / ambiguous account** | Abort. Never proceed on an unclassified account. |
| **Corrupt durable state** | The store fails closed. Do not delete it to "start clean" — that destroys the record of what was already sent. Inspect it, reconcile against IBKR, resolve by hand. |
| **2FA / weekly restart mid-trade** | Expected. On recovery the system reconciles; confirm `entry_orders_after_restart = 0`. |
| **Stop triggered during the run** | The wide TEST stop makes this unlikely. If it fills, the position is flat — reconcile and record it; do not re-enter. |

**Never** respond to a failure by submitting another entry.

---

## 14. Phase boundary

Phase 2 certifies execution plumbing. It is **not** a strategy and produces no alpha.

Not authorized here: any second symbol · any second entry · shorts · options · leverage ·
pyramiding · strategy logic (Breakout / Pullback / PEAD) · scanner · ranking · portfolio
allocator · production risk engine · borrow logic · AI agents · PostgreSQL infrastructure ·
IBKR live · real money.
