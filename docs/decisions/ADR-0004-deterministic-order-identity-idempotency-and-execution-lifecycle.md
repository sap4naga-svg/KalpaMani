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

### 11. A trade is bound to an ACCOUNT, and the binding is re-proven — added 2026-08-25

Verifying the session at arming time proves the account was right *then*. Arming happens
only when no trade exists, so every subsequent cycle — recovery, reconciliation, a
protective re-dispatch, a controlled exit — was running against whatever session the
process happened to be connected to now, with nothing tying the two together.

The gap that opens:

```
paper account A fills the entry
the protective intent is durable but unfenced
the process restarts against account B
recovery sees a local unfenced intent -- and dispatches it into B
```

Local state knows nothing about B, so nothing else would have stopped it.

**Decision.** `TradeRecord.account_fingerprint` (schema v4) records the fingerprint of the
brokerage account the trade was **armed** against, taken from the verified
`BrokerSessionEvidence` — never from a parameter. A fingerprint, never the raw identifier,
so persisting it spreads no account id into state files, logs or Git.

The binding is re-proven **twice**, at two different distances from the broker:

| Where | When | On failure |
|---|---|---|
| `_on_cycle` | every cycle that has a trade, **before any broker state is read** | abort |
| `Phase2Coordinator.fence_dispatch` | immediately before *every* broker order call | refuse to fence, so no call |

The second is not redundant. A check made several methods earlier proves nothing about the
moment an order actually leaves, and `fence_dispatch` is the only door every order passes
through. Order of operations there: re-read durable state → refuse a stale caller → prove
the account → **persist the fence** → *then* the caller contacts the broker. The fence
stays before the broker call (§4a); nothing about this weakens it.

LIVE, UNKNOWN, a different paper account, and a record carrying **no** binding at all are
all abort conditions. A missing binding fails closed rather than skipping the check.

### 12. Recovery reconciles before it re-dispatches — added 2026-08-25

Recovery is the only path that can put an order on the wire without a human, and it was
deciding to re-send *before* reconciling. The required order is now:

```
prove the same PAPER account
    -> load broker truth
    -> adopt positive broker evidence
    -> reconcile position and protection
    -> only then decide what may be re-dispatched
```

An unfenced PROTECTIVE or EXIT may be re-dispatched **only** when local long equals the
broker position, the broker shows no working protection for this execution, and the account
is proven. Otherwise the plan raises and nothing is sent: re-dispatching a stop for a
position the broker does not show could sell what we do not hold, and that is a short.

### 13. Failing closed does not mean going blind — added 2026-08-25

The abort latch dropped broker events. That is not failing closed, it is failing *deaf*:

```
ENTRY fenced, broker call made
an unrelated error latches the abort
the ENTRY then FILLS
the event is dropped -- no fill recorded, no protective intent
the broker holds a naked SPY long this process cannot see
```

**Decision.** Two separate concepts, deliberately not one flag:

- **normal progression** — new trading decisions. Halted by the latch.
- **broker event ingestion** — acknowledgements, fills, cancellations, rejections for orders
  already sent. **Never** halted. Dropping them would not stop anything happening at the
  broker; it would only stop us knowing about it.

One action survives the halt, because it *reduces* risk rather than taking it: if an already
dispatched ENTRY fills afterwards, the fill and its protective intent are written (one
atomic write, §4a), the account binding is re-proven at the fence, broker truth must be
unambiguous, and the protective stop is dispatched. It never submits another entry, never
clears the halt, and never resumes autonomous trading. If protection cannot be dispatched
safely, the position is surfaced as **UNPROTECTED POSITION** for manual handling.

### 14. Regular hours are enforced, not recommended — added 2026-08-25

The entry is a MARKET order, which asks the book for whatever price it has. Outside a liquid
regular session that is not a meaningful certification, and a "1 share of SPY" reference
guard stops being a realistic bound on what fills. The runbook said "market hours only";
that was an instruction to a human, in a system whose subscription uses
`extended_market_hours=True`.

**Decision.** Three gates, all required, checked **before** the arm is consumed:

1. the exchange says the regular session is open (`QCAlgorithm.is_market_open`, which knows
   holidays, half days and early closes — we do not re-implement a calendar);
2. the clock is at or after **09:45 America/New_York**, excluding the opening auction;
3. the day's **actual** regular close is still at least **30 minutes** away.

Gate 3 is *derived*, and that correction matters — **amended 2026-08-25**. The first version
hardcoded a 15:30 upper bound, which is right only on a normal 16:00 close. On a 13:00 early
close — before Thanksgiving, Christmas Eve, Independence Day — 12:59 satisfied both "the
session is open" and "before 15:30", so the entry could have fired **one minute before the
close**, with no time to observe the protective stop, let alone exit. The close now comes from
the exchange calendar (`SecurityExchangeHours.get_next_market_close`), so a half day narrows
the window by itself and 15:30 is a consequence rather than an assumption. An unknown close
fails closed: an unknown close is not a distant one.

The window gates the **entry** only. Protection and exit are never gated on it — refusing to
reduce risk because of the time of day would turn a liquidity precaution into a risk.

Outside the window the deployment stays read-only and says why; the one-time arm is **not**
consumed, so a mistimed launch costs nothing. TEST parameter — not production strategy logic.

### 15. Three separate notions of "stop" — added 2026-08-25

Conflating these is how a system either resumes when it should not, or goes blind when it
should not. They are now distinct pieces of state:

| | Scope | Durable? | Cleared by |
|---|---|---|---|
| `TradeState.FAILED` | this **trade's lifecycle** | yes, terminal | nothing — terminal means terminal |
| `OperationalHalt` | this **deployment's** freedom to act | when the cause is a safety violation | an explicit human action |
| broker fact ingestion | — | — | **never stops** |

**The halt was RAM-only**, so a restart cleared it — while the log had just promised "normal
progression REMAINS halted". It is now persisted, and `Phase2Cycle` reads it at construction,
so a restart does not resume.

**Unknown failures fail toward safety — revised 2026-08-25.** The first version of this rule
read "a `SafetyViolationError` is durable, anything else is transient until proven otherwise".
That is **fail-open** the moment the system is order-capable, and this review cycle produced the
counter-example: a `TypeError` from .NET's `System.Decimal` shadowing Python's, sitting on the
armed path, invisible to a fully green test suite. Under the old rule it would have halted the
session and then **cleared itself on the next restart** — with an entry possibly live at IBKR.

The rule is now inverted:

> Once anything is at stake, **every** halt is durable. An unrecognised failure is durable
> whether anything is at stake or not. Only an explicitly enumerated, known-benign **pre-trade**
> condition may be session-scoped.

"At stake" is `ExecutionRisk`, and it is deliberately broad — any one of these makes the halt
survive a restart:

| Condition | |
|---|---|
| the execution arm has been consumed | a `TradeRecord` exists at all |
| an order intent is recorded | a send fence is held |
| the broker acknowledged one of our orders | a fill has been applied |
| a position may exist | protective or exit processing is under way |
| **durable state could not be read** | |

`TRANSIENT_PRE_TRADE_ERRORS` is a short allowlist **by type** — `ConnectionError`,
`TimeoutError` — and it applies only before anything exists to lose. Nothing joins it by
default, and the classifier never reasons by exclusion. Making every hiccup a permanent chore
is still a real failure mode (an operator who clears halts reflexively has stopped reading
them), which is why the allowlist exists at all; it is simply no longer the default branch.

`TradeState.FAILED` raises a *session* halt, because the durable record of it is the trade state
itself — a second durable halt would only add a manual chore for a condition already permanent,
and the cycle re-halts on `FAILED` every time regardless.

### 16. Broker facts survive a terminal lifecycle — added 2026-08-25

Round 7 kept event ingestion alive across a halt. That was necessary and not sufficient,
because `FAILED` is terminal:

```
ENTRY already dispatched
some failure latches the lifecycle FAILED
a late ENTRY fill arrives
apply_entry_fill_and_prepare_protection() attempts FAILED -> PROTECTION_SUBMITTED
LifecycleError -- and neither the fill nor the protective intent ever becomes durable
```

A real long, invisible to the process holding the record of it.

**Decision.** A terminal record still accepts **facts** and simply does not **transition**.
Fills, acknowledgements, cancellations and rejections are recorded; the lifecycle stays
terminal. A late ENTRY fill therefore still writes the fill and exactly one protective intent,
still proves the account at the send fence, still requires broker truth to reconcile, and
still dispatches exactly one protective stop as risk reduction. It never submits another
entry and never clears the halt.

### 17. Orchestration lives where it can be tested — added 2026-08-25

`main.py` cannot be imported outside a LEAN container, so logic living there could only ever
be reviewed by reading it — and a review found exactly that: an integration test performing
transitions production never did.

**Decision.** Every decision moves to `kalpamani.execution.cycle.Phase2Cycle`, and LEAN
supplies broker I/O through a `BrokerPort`. `main.py` becomes an adapter that translates LEAN
types and makes no decisions; the preflight asserts structurally that no lifecycle call
appears in it. Tests now construct the same `Phase2Cycle` the container schedules, so an
orchestration test cannot pass while production takes a different path.

The same boundary fixed a live defect: `on_cycle` captured **one** broker snapshot, and
recovery dispatched a protective stop into that same cycle. Confirmation then compared a
just-sent order against a view taken before it existed and reported a false **UNPROTECTED
POSITION** — a durable halt for a system that was working. The cycle now **returns** after any
recovery dispatch, and confirmation waits for a fresh snapshot.

### 18. The account-binding digest is sensitive — added 2026-08-25

`account_fingerprint()` was documented as a "non-reversible fingerprint". That claim was too
strong. It is an unsalted SHA-256 over a **structured, low-entropy** brokerage account id:
anyone holding a candidate id can confirm a match by recomputing it. It is a **pseudonymous
identifier**, not anonymised data.

Treating it as anonymous had a consequence: a real dry-run digest was pasted out of a container
log into the runbook and committed while the repository was public.

**Decision.** The digest is handled as sensitive in its own right — compared in memory,
persisted only under the git-ignored runtime directory, and **never** logged, printed or
committed. Output reports `account_binding=present`, `MATCHES this deployment`, or `DIFFER`; a
verdict, never a value. Asserted by test on both `describe()` methods and on the mismatch
message.

Arm receipts are also now cross-checked against the trade record — same intent, same account
binding, same consumed flag. Two receipts that agree with each other but describe a different
trade are contradictory evidence, and fail closed.

### 19. Clearing a halt is gated, and never overrides broker or lifecycle truth — added 2026-08-25

The confirmation phrase is an assertion of **intent**, not of fact. On its own it must never make
an unsafe trade resumable, so `--clear-halt` re-establishes every invariant it can before the
phrase is even considered (`assert_halt_clearable`):

| Gate | On failure |
|---|---|
| deployment session classifies PAPER, never LIVE or unknown | REFUSED |
| durable state readable and internally coherent | REFUSED |
| the trade is bound to *this* deployment account | REFUSED |
| no order left holding an unresolved `SEND_FENCED` | REFUSED |
| no long recorded without confirmed protection | REFUSED |
| no short recorded at all | REFUSED |

**What it deliberately does not claim.** `--clear-halt` runs on the host, with no brokerage
connection: local-versus-broker position agreement, unexpected working SPY orders and an
accidental short at IBKR cannot be checked there. They are checked where they can be — inside a
deployment, on every cycle, by `reconcile()` and `assert_eligible_to_arm()`. So clearing lifts
the **deployment latch and nothing else**: the next run still re-proves the account, still
reconciles, and still halts if anything disagrees. The script prints those caveats rather than
implying a completeness it does not have.

Clearing also never revives a lifecycle. `TradeState.FAILED` is terminal; a cleared halt on a
FAILED trade buys a read-only reconciliation pass, and the cycle halts again on the next tick.

### 20. Fill quantities are signed; the sign is a safety signal — added 2026-08-25

LEAN reports fill quantities **signed by direction**: a BUY fills positive, a SELL negative.
The cycle filtered fill events with `fill_quantity <= 0`, which meant **every protective and
every exit SELL fill was silently discarded**. Durable state went on believing it held a
position the broker had already closed, and the next reconciliation halted on a disagreement
the system had caused itself.

Found by independent review of the Round-9 bundle, and reproduced on both paths. The test suite
could not see it: the event fixture defaulted to `+1` for BUY and SELL alike, so the tests were
feeding the cycle a direction the broker never sends.

**Decision.** Three layers, each with one job:

| Layer | Responsibility |
|---|---|
| `LeanBrokerPort` (`main.py`) | Preserves `OrderEvent.fill_quantity` **including its sign**. Never calls `abs()`. |
| `Phase2Cycle` | **Validates** the sign against the durable order, then drops it. |
| `state_store` | Receives **absolute** quantities only. |

The last row is why the sign cannot simply be passed through: `open_long_quantity` derives
direction from the order's *role*, so a signed quantity reaching it would double-count
direction.

Validation is not a formality — a fill in the wrong direction means our record and the broker
disagree about what an order *is*:

| Role | Expected | A contradiction means |
|---|---|---|
| ENTRY | positive | a BUY that filled short |
| PROTECTIVE | negative | a stop that filled long |
| EXIT | negative | a close that filled long |

A contradiction is **not applied** and raises a durable, manual-clearance halt. Side and role
are cross-checked against each other too: they are independent facts, and a record where they
disagree is not one to act on.

The fixture now requires an explicit sign at every call site — no default — and the preflight
asserts structurally that the adapter never takes `abs()` of a fill quantity.

### 21. Order ownership is broker-native, not tag-based — added 2026-08-25

Phase 2 used LEAN's `Order.Tag` as the durable ownership key. That assumption is invalid across
a restart, and it stranded a live protected paper position on the first certification run.

LEAN does not send the tag to IBKR, so an order LEAN re-hydrates from the broker comes back with
a **blank** tag. Observed directly, read-only, against the order still open at IBKR:

```
[IDENTITY-DIAG] order 0: symbol=SPY side=SELL qty=1 type=STOP_MARKET
                tag_present=False  broker_id_present=True  lean_id_present=True
```

| Identity | Survives a restart | Role |
|---|---|---|
| `Order.Tag` (our client order id) | **NO** | primary only within the submitting process |
| `Order.BrokerId` | **YES** — same value before and after | **the restart identity** |
| `Order.Id` (LEAN-local) | **NO** — reassigned | addresses a cancellation in *this* process only |
| IB `PermId` | visible in IB brokerage trace; **not proven** reachable from `QCAlgorithm` | not used |

**Decision — a strict hierarchy.** `resolve_ownership()` attributes an open order by evidence:

1. **Tag** — if present and ours.
2. **Broker id** — exact intersection with exactly **one** durable order. More than one is
   ambiguous and fails closed.
3. **Attributes** (symbol, side, quantity, order type, stop price) then **validate** whichever
   identity was established. They may never *create* one: a manual SELL stop for 1 SPY at the
   same price is indistinguishable by shape, and adopting on resemblance would let KalpaMani
   cancel a stranger's order, or believe a stranger's order was protecting it.
4. Otherwise **foreign** — never adopted, never cancelled, never answered with a compensating
   order. Still counted, so any working order on the symbol blocks a new entry.

A tag and a broker id naming *different* durable orders is a contradiction, not a tie-break.

**Consequences.** `SubmittedOrder.broker_order_ids` is a durable collection (schema **v5**, with
an explicit v4 migration), captured at acknowledgement and from positive broker evidence, and
refused if it would ever change. `BrokerOrderView` carries raw identity and the adapter no longer
decides ownership — the cycle resolves it, because only durable state knows which broker ids are
ours. Event routing uses the same resolver, since a re-hydrated order's events are also anonymous.
Cancellation targets the resolved order's **current** LEAN order id: never by tag, never by
symbol, never "the first SELL stop".

**Known limit.** A durable order whose broker id was never recorded has *no* restart identity and
resolves to foreign — correctly. That is the state of the position open at the time of writing:
it predates this capture, so the repair cannot retroactively identify it.
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
