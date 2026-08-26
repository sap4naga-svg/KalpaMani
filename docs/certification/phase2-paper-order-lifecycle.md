# Phase 2 — Controlled IBKR Paper Order Lifecycle

## STATUS: **ACCEPTED**

Independent final certification review passed. This certifies **execution
plumbing**, not a strategy: that KalpaMani can place one order, protect it,
survive a restart, close it under control, and end flat — provably, and failing
closed when it cannot.

---

## Scope certified

| | |
|---|---|
| brokerage | IBKR **PAPER** only |
| symbol | SPY |
| side | long only |
| quantity | exactly **1** share |
| fills | **full-fill only** |
| lifecycle | entry → protection → restart → recovery → controlled exit → flat |

## Runs

### Run 1 — `FAILED` / `MANUAL_BROKER_CLOSE`

Retained deliberately as **negative certification evidence**.

The entry filled and was protected. Recovery then failed across a restart:
LEAN re-hydrated the protective stop correctly, but `Order.Tag` — where the
KalpaMani client order id lives — is **not sent to IBKR**, so the order came back
anonymous. Ownership could not be proven, reconciliation disagreed with itself,
and the deployment **failed closed**: it halted, submitted nothing, and left the
stop working.

That is the important part. The design's response to an identity it could not
prove was to stop, not to guess. The position was later closed by hand and the
run recorded as terminal `FAILED` — **never** `RECONCILED`, because the automated
lifecycle did not close it.

See [ADR-0004](../decisions/ADR-0004-deterministic-order-identity-idempotency-and-execution-lifecycle.md)
§21–22, [INC-0001](../incidents/INC-0001-run1-manual-cleanup-transient-short.md).

### Run 2 — `RECONCILED` / `AUTOMATED`

The full lifecycle, completed.

## Proofs

**Authorization**
- explicit run-scoped authorization (`--arm --run 2`); no default, no auto-increment
- arm consumed durably; a restart re-arms nothing

**Entry and protection**
- exactly **one** ENTRY · actual **+1** fill · reference notional within the pre-submission guard
- exactly **one** protective stop, sized from the *actual* filled quantity
- **durable broker-native identity captured before the restart** — the gate Run 1 could not pass

**Restart and recovery**
- genuine fresh LEAN process **and** fresh IB Gateway session
- re-hydrated tag **ABSENT**
- LEAN-local order identity **changed** across the restart
- ownership recovered by **`BROKER_ID`**
- **zero** duplicate ENTRY · **zero** duplicate PROTECTIVE · **zero** EXIT and **zero** cancellation before authorization

**Controlled exit**
- exactly one cancellation, targeting the *resolved current* owned protective order
- `CANCEL_PENDING` correctly **not** treated as `CANCELED`
- exactly one `EXIT SELL 1`, fenced before the broker call
- signed SELL fill `-1` handled correctly
- final broker position **0** · open SPY orders **0** · **no accidental short**
- lifecycle **`RECONCILED`**

## Certification limitations

This does **not** certify:

- partial or multi-fill execution
- a protective stop actually triggering
- any short lifecycle
- pyramiding
- multiple simultaneous positions
- live brokerage execution
- strategy alpha or performance of any kind

Nothing here says the system makes money. It says the plumbing does what it
claims and stops when it cannot.

## Security

- no brokerage account identifiers
- no account-binding digest
- no raw broker-native order ids
- no credentials, tokens or 2FA material
- raw runtime evidence (logs, durable state, LEAN configuration) remains
  **git-ignored** and untracked

## Open items

**[INC-0002](../incidents/INC-0002-account-binding-digest-exposure.md) — OPEN.**
Orphaned pre-sanitization Git objects still carry an account-binding digest and
remain retrievable by SHA.

**The repository was PRIVATE at the time of this certification.** Current
development visibility is governed by [CLAUDE.md §3](../../CLAUDE.md) and is not
restated here, so that policy and this record cannot drift apart again.

The residual historical exposure is **accepted, not remediated**: the purge has
not been performed, and INC-0002 stays **OPEN** until every object is gone and
`scripts/verify_purge.py` exits 0. The repository **must return to PRIVATE**
before micro-live operation, real-money trading, or production broker
credentials or configuration existing anywhere in the workflow.

Live trading remains **hard-disabled**. Phase 3 implementation is not authorized.
