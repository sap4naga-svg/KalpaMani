# INC-0001 — Transient SPY short during Run-1 manual cleanup

- **Date:** 2026-08-25
- **Environment:** IBKR **PAPER** (bound Phase-2 certification account)
- **Classification:** **MANUAL OPERATOR INCIDENT** — not a KalpaMani-generated order defect
- **Severity:** high (a short position existed, however briefly, in a long-only phase)
- **Status:** closed — account verified flat, zero open SPY orders
- **Related:** [ADR-0004](../decisions/ADR-0004-deterministic-order-identity-idempotency-and-execution-lifecycle.md)
  §21 (broker-native ownership), §22 (manual resolution);
  [Phase-2 runbook](../runbooks/phase2-paper-order-lifecycle.md) §13.0

> No brokerage identifiers appear in this record: no account id, no account-binding
> digest, no broker order ids. That is deliberate and permanent.

---

## What happened

Certification **Run 1** placed `BUY 1 SPY` on IBKR Paper and protected it with a SELL stop.
The automated lifecycle then failed at **restart ownership recovery**: LEAN re-hydrated the
protective stop correctly, but the order tag carrying our client order id is not sent to IBKR,
so the re-hydrated order came back anonymous. KalpaMani could not prove the stop was its own,
reconciliation disagreed with itself, and the deployment **failed closed** with a durable halt.
That is the defect ADR-0004 §21 repairs.

The position therefore had to be closed by hand. During that cleanup:

1. The protective stop was **manually cancelled successfully**.
2. In the subsequent manual flattening attempt, a **SELL of an incorrect quantity** was
   submitted, which **temporarily created a SPY short position**.
3. The short was **manually corrected**, and the paper account was ultimately verified
   **flat, with zero open SPY orders**.

## What KalpaMani did during the cleanup: nothing

This matters, so it is stated with evidence rather than asserted. Across every deployment in
this window, the container logs record:

```
Submit Order 0 · CancelOrder 0 · ENTRY-SUBMIT 0 · PROTECTIVE-SUBMIT 0 · EXIT-SUBMIT 0 · fences 0
```

KalpaMani was **halted** for the entire period (`MANUAL_CLEARANCE_REQUIRED`), and for most of
it was not connected at all. It did not cancel the stop, did not submit the SELL that created
the short, and did not submit the correction. Every order in this incident was entered by a
human in the broker UI.

The short also existed while KalpaMani was not watching it. Had the system been running and
unhalted, a negative position is precisely what `reconcile()` and `assert_flat()` fail closed
on — but it was not running, so that guard was never exercised. **The automated path has
guardrails; the manual path had none.** That is the substance of this incident.

## Why it was possible

A generic SELL ticket does not know what position you hold. It will happily sell more than you
own, and selling more than you own is not an error the ticket reports — it is simply a short.
The quantity was the only thing standing between "flat" and "short", and it was entered by
hand under time pressure, immediately after an unrelated failure. There was no procedure
requiring the projected resulting position to be checked before submitting.

## Trade evidence is unchanged

Run 1 remains exactly as the automated lifecycle left it:

- state **`FAILED`**, resolution **`MANUAL_BROKER_CLOSE`**,
  reason `MANUAL_BROKER_CLOSE_AFTER_RESTART_IDENTITY_FAILURE`
- ENTRY `FILLED` 1, PROTECTIVE `ACKNOWLEDGED` with its original stop price
- original trade intent, execution id, natural key, arm consumption and revision history

**The manual trades are deliberately NOT recorded as KalpaMani orders.** They were not
KalpaMani orders. Folding them into the `TradeRecord` would corrupt the evidence of what the
automated system actually did — which is the whole reason the record is kept — and would make
a failed certification read as though the software had closed its own position. It did not.

This incident record is the correct home for those facts, and it is separate from the trade
record on purpose.

## Corrective actions

| # | Action | Status |
|---|---|---|
| 1 | Manual flattening procedure added to the runbook (§13.0), with a pre-submission checklist and a hard "do not submit" rule when the projected position is not exactly zero | done |
| 2 | Prefer IBKR's **Close Position** action over a generic SELL ticket wherever available | done (§13.0) |
| 3 | A manual cleanup that creates a short is itself a recordable operational incident | done (§13.0) |
| 4 | Restart ownership repaired so this class of manual cleanup is not needed again | done (ADR-0004 §21) |
| 5 | Pre-restart identity checkpoint, so a position can never again become unrecoverable | done (ADR-0004 §22) |

## Lesson

The failure that started this was a software defect, and it failed **safely** — closed, halted,
nothing sent. The failure that created a short was a human one, and it had nothing to fail
closed *with*. Corrective actions 1–3 give the manual path the same kind of pre-submission
check the automated path has had since Phase 2 began: state the expected result, and refuse
when the projected result is not it.
