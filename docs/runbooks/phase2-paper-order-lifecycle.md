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
| Pre-submission notional guard | **USD 800** on the *reference* price — abort above |
| Fill notional tolerance | USD 1,000 — **not enforceable** by a market order (see below) |
| Trade intents | **1** |
| Entry orders | **1** |
| Strategy capital | **USD 80,000**, unaffected by the ~USD 1,000,000 paper balance |

Forbidden: any second symbol · shorts · options · leverage · pyramiding · averaging down ·
recurring entries · strategy-generated entries · autonomous retries that submit another entry.

> **On the notional numbers.** Phase 2 submits a **market** order, and a market order cannot
> mathematically guarantee its fill notional — the fill price is whatever the book gives. So
> USD 1,000 is a *tolerance*, not a hard maximum, and calling it one would be false. What is
> actually enforced is a **pre-submission reference guard of USD 800**, reserving a 20%
> slippage buffer. For 1 share of SPY in liquid hours, a fill would have to slip more than a
> fifth above the observed price to breach the tolerance.

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

Durable state lives at `.runtime/lean/storage/phase2_trade_state.json` (git-ignored).
`/Storage` in the container binds to `<cli-root>/storage`, **not** a per-project
subdirectory — verified against the LEAN CLI and confirmed bidirectionally on the dry run.

Submission intent is written **before** the order is sent. Missing or corrupt state **fails
closed** — it is never read as "nothing happened".

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

### The trade is bound to the account it was armed on

`TradeRecord.account_fingerprint` records **which** paper account authorised the trade. From
then on, every cycle that has a trade re-proves the connected session against it *before*
reading any broker state, and every single order re-proves it again at the send fence,
immediately before the broker call.

| Restart lands on | Result |
|---|---|
| the same paper account | normal recovery |
| a **different paper** account | abort — zero orders |
| a **live** account | abort — zero orders |
| an unclassifiable account | abort — zero orders |
| a record with **no** binding | abort — zero orders |

A pseudonymous binding digest is stored, never the account id — and the digest is sensitive
too, so it is never logged or printed either. `[SESSION-BOUND] same PAPER account as armed:`
in the log is this check passing.

### Where the algorithm's evidence actually comes from

Configuration you supply is **not** evidence. The algorithm reads LEAN's own merged
deployment configuration inside the container at `/Lean/Launcher/bin/Debug/config.json`, and
there is **no fallback** — if it cannot be read, Phase 2 aborts.

Confirmed on the 2026-08-25 disarmed dry run:

```
[RECONCILE] session verified PAPER: account=DU******* account_binding=present
            classified=paper trading_mode='paper' (derived-from-account-id)
            source=/Lean/Launcher/bin/Debug/config.json
```

**Known limitation, stated rather than hidden.** `QCAlgorithm` exposes no brokerage account
identifier — verified against the QuantConnect stubs, the account lives on `LiveNodePacket`
which the algorithm cannot reach. The deployment configuration is therefore the strongest
in-algorithm evidence available, and the preflight verifies the same source independently
before deployment.

**Container logs are themselves sensitive — never paste one into a tracked file.** LEAN's
IBAutomater logs IB Gateway window titles, and those titles contain the **full IBKR account
identifier** (`[<ACCOUNT> Trader Workstation Configuration (Simulated Trading)]`). Nothing
KalpaMani does can prevent that; it is LEAN's own logging. The logs live under `.runtime/`,
which is git-ignored, and that is where they must stay. Quote a log line in documentation only
after redacting it by hand.

**The account-binding digest is never printed.** It is a *pseudonymous* digest of the account
id, not anonymised data: brokerage account ids are structured and low-entropy, so anyone with
a candidate id can confirm a match by recomputing it. Earlier revisions of this runbook
pasted a real one out of a dry-run log; that was a leak, and it has been redacted. Output now
reports `account_binding=present` and the preflight reports `MATCHES this deployment` — a
verdict, not a value. If you need to compare bindings by hand, do it outside Git.

`ib-trading-mode` is an *internal-input* that the LEAN CLI derives at deploy time, so it is
often absent from the config file. When absent, the mode is derived using LEAN's own rule and
the log says `(derived-from-account-id)` rather than `(stated)`. An `UNKNOWN` account derives
to `unknown` and still fails.

---

## 6. Arm the execution gate — the one deliberate act

```bash
.venv\Scripts\python.exe scripts\phase2_arm.py --status

.venv\Scripts\python.exe scripts\phase2_arm.py --arm --confirm "ARM PHASE2 PAPER BUY 1 SPY"
```

**You do not type an account id.** The arm reads `ib-account` from the LEAN deployment
configuration — the same file the engine uses — so the armed account and the deployed
account cannot be two independent values that disagree. The algorithm re-checks the
fingerprint at runtime anyway.

The phrase must be typed **exactly**. A boolean can be set by a stray environment variable;
a specific phrase cannot be arrived at by accident.

The arm is refused — with a non-zero exit — if the deployment has no account configured, if
the session does not verify as paper, or if the phrase does not match. Account ids are
**redacted** in all output, and the account-binding digest it derives is stored only under
the git-ignored runtime directory — never logged, never printed, never committed.

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
| **`SEND_FENCED`, broker silent** | Ambiguous — the order may be live. Do **not** resend. Check the IBKR order history by hand, then reconcile deliberately. |
| **Protective intent never fenced** | The long is unprotected and the stop was never sent. Recovery re-dispatches it; verify the stop appears at IBKR before doing anything else. |
| **Order rejected (`INVALID`)** | See §13.3. Never answer a rejection with another entry. |
| **Arm refused: receipt could not be written** | Both receipt locations must be writable. Check the object-store mount and the project directory before retrying. |
| **Corrupt durable state** | The store fails closed. Do not delete it to "start clean" — that destroys the record of what was already sent. Inspect it, reconcile against IBKR, resolve by hand. |
| **2FA / weekly restart mid-trade** | Expected. On recovery the system reconciles; confirm `entry_orders_after_restart = 0`. |
| **Stop triggered during the run** | The wide TEST stop makes this unlikely. If it fills, the position is flat — reconcile and record it; do not re-enter. |

**Never** respond to a failure by submitting another entry.

---

## 13.1 Disarmed dry run — do this before ever arming

Proven on 2026-08-25 with a detached deployment:

```bash
.venv\Scripts\python.exe scripts\phase2_preflight.py       # EXECUTION ARM must read NO
cd .runtime\lean
..	ools\leanvenv\Scripts\lean.exe live deploy phase2_order_lifecycle ^
    --brokerage "Interactive Brokers" --data-provider-live "Interactive Brokers" --detach
```

Confirm, then stop with `lean live stop phase2_order_lifecycle`:

| Check | Dry-run result |
|---|---|
| `kalpamani` package imports in the container | ✅ zero import errors |
| Durable state path | `/Storage/phase2_trade_state.json` |
| `/Storage` ↔ host mount | ✅ `.runtime/lean/storage/`, verified bidirectionally |
| Session proven PAPER from deployment config | ✅ binding matched the preflight |
| SPY subscribed | ✅ |
| Reconciliation ran | ✅ `spy_position=0 owned_open_orders=0` |
| Execution arm | ✅ `test_mode=False arm_flag=False` |
| Orders / positions | ✅ **0 / 0** |
| Clean shutdown | ✅ `RESULT: FLAT`, no container left |

If any row differs, **stop and fix it** before arming.

---

## 13.2 Order dispatch states — what the log is telling you

Every order carries a **dispatch state**, because "submitted" is too coarse a
word to be safe:

| State | Meaning | If the process dies here |
|---|---|---|
| `INTENT_RECORDED` | Written durably. **The dispatcher has not committed to calling the broker.** | We can defend "the broker has nothing". Safe to re-dispatch. |
| `SEND_FENCED` | The **send fence** is durable. A broker call **may** have happened. | Ambiguous — **never resend**. Halts for a human. |
| `ACKNOWLEDGED` | The broker confirms it is working. | Reconcile normally. |
| `FILLED` / `CANCELLED` / `REJECTED` | Terminal broker outcome. | Nothing pending. |

**Why the fence is written before the call.** Nothing makes "call the broker" and "record
that we called it" atomic, so a crash can fall between them either way round. Writing the
record afterwards would leave a state meaning *definitely not sent* after a successful send —
and recovery would then issue a second order. For a stop or an exit that is a second SELL and
a possible short. So the fence goes first, and it claims only that a send *may* have occurred.

A crash immediately **before** the broker call and one immediately **after** it therefore look
identical, and both halt. That is intentional.

**`protected_quantity` counts a stop only at `ACKNOWLEDGED`.** A protective
intent that was recorded but never dispatched is **not** protection, and the
system says so rather than looking healthy.

On recovery you will see `[RECOVERY] dispatch assessment: …`:

- **PROTECTIVE or EXIT intent never *fenced*, long still open** — re-dispatched
  automatically. The fence was never acquired, so the order was never sent; this
  is provably not a duplicate, and it is the only way out of an unprotected
  position.
- **ENTRY intent never fenced** — **fails closed.** No position is at risk, and
  re-entering is not a decision to take unattended. Resolve manually.
- **Any order `SEND_FENCED` with no broker acknowledgement** — **fails closed.**
  Reconcile against the broker's order history by hand. Never resend on this
  basis, and never conclude the order is absent just because it is missing from
  the open-order list — it may have filled or been cancelled.

---

## 13.3 Rejected orders (`OrderStatus.INVALID`)

| Rejected order | Response |
|---|---|
| **PROTECTIVE, long open** | **UNPROTECTED POSITION — highest severity.** Session aborts. Protect or close the position by hand in IBKR. **Never** submit another entry. |
| **EXIT, long open** | **UNPROTECTED POSITION — highest severity.** Protection has already been cancelled, so the long is bare. Close it by hand. |
| **ENTRY** | Recorded as rejected. No fill, no position, no exposure. **No automatic second entry, ever.** Investigate the rejection reason before re-arming. |

These are never treated as ordinary zero-fill events that quietly return.

---

## 13.4 Two behaviours worth knowing before you watch a live run

**A cancellation request is not a cancellation.** After `--request-exit`, the log shows
`cancel requested ONCE; awaiting CANCELED event` and then *returns*. Subsequent cycles log
`awaiting broker cancellation confirmation` and send **nothing** — the broker is asked
exactly once. Internal state still records the stop as protecting the position, so
reconciliation continues to agree with the broker.

LEAN emits **`CANCEL_PENDING` before `CANCELED`**, and only the latter confirms:

```
[EXIT-REQUEST] km-…-PROTECTIVE-0 CANCEL_PENDING -- NOT confirmation; still working
[EXIT-REQUEST] protective cancellation CONFIRMED for km-…-PROTECTIVE-0
```

Only the second line drops `protected_quantity` to zero and makes the close eligible.
**A cycle that appears to "do nothing" after a cancel request is correct behaviour.**

**A protective stop firing is a legitimate exit.** If the stop fills, the long is closed by
the stop. The system recognises this, moves to `CLOSED`, and will **not** send an exit SELL
for a position that no longer exists — which would open a short. Expect
`[EXIT-FILL] protective stop filled; the long is closed by the stop`, then final
reconciliation to flat.

---

## 13.5 The execution window — the entry will not fire outside it

Phase 2 submits a MARKET order, so it only runs in a liquid regular session.

```
from 09:45 America/New_York, until 30 minutes before the day's ACTUAL regular close
    normal 16:00 close  ->  09:45 - 15:30
    13:00 half day      ->  09:45 - 12:30
regular session only   (TEST window)
```

Three gates, all required: the **exchange calendar** says the regular session is open, the
**clock** is at or after 09:45, and the day's **actual** close is still at least 30 minutes
away. The close is read from the calendar, not assumed — that is what makes a half day narrow
the window by itself. If the calendar cannot answer, the entry is refused: an unknown close is
not a distant one.

Outside the window you will see, once per cycle:

```
[PHASE2-ARM] entry not eligible: ... Staying read-only.
```

**The arm is not consumed.** A launch at the wrong time costs nothing — leave it running and
it will arm when the window opens, or stop it and relaunch later. The preflight prints
`Window open right now` as a convenience; the algorithm's check is the one that decides, and
it is the only one that knows the exchange calendar.

**The window gates the entry only.** Protection and the controlled exit are never gated on it.
A stop is dispatched whenever an entry fills, and `--request-exit` works outside market hours
— refusing to reduce risk because of the clock would turn a liquidity precaution into a risk.

---

## 13.6 The operational halt — and clearing it

Three different things can be "stopped", and they are not interchangeable:

| | What it means | Survives restart? |
|---|---|---|
| `TradeState.FAILED` | this **trade's** lifecycle is over | yes — terminal |
| operational halt | this **deployment** may take no new normal action | **when the cause is a safety violation** |
| broker fact ingestion | — | **never stops** |

A safety halt — unprotected position, reconciliation mismatch, account-binding failure,
contradictory arm evidence — is written to `/Storage/phase2_operational_halt.json` and read
back at startup. **Redeploying does not clear it.** The preflight fails while one is in force,
and `--status` shows it.

A transient fault (a transport error, an unexpected runtime fault) halts that deployment only
and a restart may retry it. That distinction is deliberate: an operator who has to clear a
halt after every hiccup stops reading them.

To clear one, reconcile against IBKR **by hand first**, then:

```bash
.venv\Scripts\python.exe scripts\phase2_arm.py --clear-halt --confirm "CLEAR PHASE2 HALT"
```

The phrase must be exact. Clearing a halt asserts that a human has looked at the broker and
resolved what caused it. It does **not** change the trade lifecycle: a `FAILED` trade stays
`FAILED`.

---

## 13.7 What a halt does and does not stop

A halt (`[PHASE2-ABORT]`) stops **new normal activity**. It does **not** stop KalpaMani
recording what the broker does with orders already sent.

| After a halt | Behaviour |
|---|---|
| Reconcile cycle | stops |
| New entry | impossible |
| Autonomous progression | stops |
| Acknowledgements, fills, cancellations, rejections | **still recorded durably** |
| An already-dispatched ENTRY that then fills | fill + protective intent written, and the **stop is dispatched** |
| The same, after the lifecycle latched `FAILED` | identical — a terminal lifecycle records facts, it just does not transition |

That last row is deliberate. Declining to protect a position that has actually filled would
leave it naked — the outcome halting exists to avoid. It is a one-off risk-reducing action:
no second entry, the halt is never cleared, and autonomous trading does not resume.

```
[POST-HALT-PROTECT] entry filled after normal progression was halted. Dispatching the
protective stop as a deterministic risk-reducing action; normal progression REMAINS halted
```

If broker truth is ambiguous at that moment, nothing is sent and you get instead:

```
[UNPROTECTED-POSITION] PROTECT OR CLOSE THE POSITION MANUALLY.
```

Do exactly that, in IBKR, by hand. Do not restart hoping it resolves itself.

---

## 14. Phase boundary

Phase 2 certifies execution plumbing. It is **not** a strategy and produces no alpha.

Not authorized here: any second symbol · any second entry · shorts · options · leverage ·
pyramiding · strategy logic (Breakout / Pullback / PEAD) · scanner · ranking · portfolio
allocator · production risk engine · borrow logic · AI agents · PostgreSQL infrastructure ·
IBKR live · real money.
