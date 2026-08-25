# ADR-0003 — Broker-Side Order Controls Are Not Safety Invariants

- **Status:** Accepted
- **Date:** 2026-08-25
- **Deciders:** Project owner (human governance)
- **Relates to:** ADR-0001 (System Foundation), ADR-0002 (BrokerAdapter and the Brokerage Boundary)
- **Corrects:** An assumption in Blueprint V2.1 §25 — see *Errata* below
- **Evidence:** Phase 1 IBKR Paper connectivity runs, 2026-08-24 / 2026-08-25

---

## Context

Blueprint V2.1 §25 recorded the observed IBKR account configuration, including that
**Read-Only Access** was enabled, and assessed it as benign:

> *"Read-Only Access | May stay enabled | It only provides a quick read-only mode; full login
> is still required to trade."*

That assessment was made from account settings, before any automated deployment existed. It
left open the reasonable-sounding inference that a broker-side read-only posture contributes
something to KalpaMani's order safety.

**Phase 1 tested that inference empirically. It does not hold.**

### What was actually observed

On **every** IBKR Paper deployment through LEAN (four runs, 2026-08-24 and 2026-08-25),
QuantConnect's **IBAutomater** drove the IB Gateway configuration dialog and made these
changes automatically, before the algorithm ever ran:

```
Window title: [<ACCOUNT> Trader Workstation Configuration (Simulated Trading)]
Unselect checkbox: [Read-Only API]
Set API port textbox value: [4002]
Select checkbox: [Create API message log file]
Select checkbox: [Bypass Order Precautions for API Orders]
Select checkbox: [Bypass Bond warning for API Orders.]
Select checkbox: [Bypass negative yield to worst confirmation for API Orders.]
Select checkbox: [Bypass Called Bond warning for API Orders]
Select checkbox: [Bypass "same action pair trade" warning for API orders.]
Select checkbox: [Bypass price-based volatility risk warning for API Orders.]
Select checkbox: [Bypass Redirect Order warning for Stock API Orders]
Select checkbox: [Bypass No Overfill Protection precaution for destinations where implied natively.]
Configuration settings updated.
```

Two distinct things are worth separating, because conflating them is how this assumption
survives:

| Setting | Where it lives | What Phase 1 observed |
|---|---|---|
| **Read-Only Access** | IBKR account / user settings (a login mode) | Enabled, per Blueprint §25. Governs interactive login, not the API session LEAN opens. |
| **Read-Only API** | IB Gateway / TWS API configuration | **Actively unselected by IBAutomater on every start.** This is the one that would have blocked API order submission. |

So the account-level setting never protected the API path, and the API-level setting that
*would* have is switched off automatically. Neither survives as a control.

This behaviour is **required for LEAN to function** — an order-capable engine cannot run
against a read-only API — and it is **not configurable from the LEAN CLI**. It is not a
misconfiguration to be corrected; it is how the officially supported integration works.

---

## Decision

1. **IBKR "Read-Only API" MUST NOT be treated as an independent KalpaMani safety control.**
   Neither must "Read-Only Access", nor any IB Gateway order-precaution checkbox. They are
   reset by the deployment path itself, so a KalpaMani safety argument may never depend on
   them.

2. **Order safety is enforced internally and deterministically by KalpaMani.** Every
   invariant about what KalpaMani will and will not send to a broker must be provable from
   this repository alone — from code, static analysis and tests — with no appeal to broker
   configuration.

3. **Broker UI precautions are defense-in-depth only.** They may be enabled, and their state
   may be observed and logged. They must never appear as a required element of a safety
   invariant, an acceptance criterion, or a risk assessment.

4. **No safety claim may rest on a control the deployment path can silently reset.** This
   generalises beyond IBKR: any control owned by a third party, mutable without our
   involvement, is at most defense-in-depth. Before relying on any external control, verify
   empirically that the automated path preserves it.

5. **The Blueprint PDF is not to be edited.** It is the authoritative architecture record as
   issued. Empirical corrections are recorded in ADRs and indexed in
   [`docs/architecture/BLUEPRINT_ERRATA.md`](../architecture/BLUEPRINT_ERRATA.md).

---

## How order safety is actually enforced

Phase 1 already implements this, which is why the finding changed nothing about the outcome:

| Control | Mechanism | Where |
|---|---|---|
| No order-submission API in the algorithm | Static AST/regex scan over the source, matching snake_case **and** legacy PascalCase | `kalpamani.common.phase_guards`, run by `tests/unit/test_phase1_broker_safety.py` |
| Deployment blocked if a scan fails | Non-zero exit before any container starts | `scripts/phase1_preflight.py` |
| Broker interface cannot express an order | `ReadOnlyBrokerAccount` Protocol exposes exactly `{account_snapshot}` | `kalpamani.broker.account` |
| Live execution refused | Two independent gates, Gate 2 unimplemented, `LIVE_TRADING_HARD_DISABLED` | `kalpamani.common.settings` |
| Ambiguous account mode refused | `BrokerAccountMode.classify()` returns `UNKNOWN`, `require_paper_account()` raises | `kalpamani.broker.account` |
| Order tripwire | `on_order_event` logs a safety violation if it ever fires | smoke-test algorithm |
| Shutdown proof | Reconciliation asserts zero orders / holdings / open orders | smoke-test algorithm |

**Phase 1 result:** zero orders, zero positions, zero open orders — with the broker-side
read-only guard demonstrably disabled the entire time. The guarantee held because it never
depended on the broker.

---

## Consequences

**Positive**

- A safety argument that was partly imaginary has been replaced with one that is testable
  in CI, without a brokerage.
- The finding was cheap to absorb because ADR-0002 had already placed the guarantee in our
  own code. This validates that choice.
- Phase 2 inherits an accurate threat model: once an order path exists, **nothing on the
  IBKR side will stop it.**

**Negative / accepted**

- One genuine layer of defense-in-depth is unavailable in automated deployments. Accepted:
  it is inherent to the supported integration, and the alternative — not using LEAN's IB
  integration — costs far more than it buys.
- Our guards must be maintained with real discipline, since they are now the only guards.

**Neutral**

- IBKR's daily (23:45 local) and weekly (Sunday 21:00 UTC) restarts re-apply these settings
  each time. There is no drift to detect and no state to reconcile.

---

## Errata to Blueprint V2.1

| Blueprint | Assumption as written | Empirical correction |
|---|---|---|
| §25, *IBKR Account Configuration Baseline* | Read-Only Access observed as enabled; *"May stay enabled … full login is still required to trade."* | Accurate for interactive login, but it does not constrain the API session LEAN opens. The API-level **Read-Only API** setting, which would constrain it, is **unselected by IBAutomater on every automated start**, together with all API order-precaution bypasses. Neither may be treated as a KalpaMani safety control. |

The Blueprint PDF remains unmodified. This ADR supersedes the §25 assumption under the
authority order in CLAUDE.md §2 (approved ADRs rank above CLAUDE.md and below the
Blueprint; where an ADR records an empirical finding that contradicts a Blueprint
*assumption*, the finding governs and is recorded here rather than by editing the PDF).

---

## Verification

Reproducible from any deployment log:

```bash
grep -E "Read-Only API|Bypass .* for API|Trading mode:" \
  .runtime/lean/ibkr_connectivity_smoke/live/<run>/log.txt
```

Expected: `Unselect checkbox: [Read-Only API]` on every run.

Documented for operators in
[`docs/runbooks/phase1-ibkr-paper-connectivity.md`](../runbooks/phase1-ibkr-paper-connectivity.md)
§8.1 and summarised in `CLAUDE.md` §9.

---

## Follow-ups

Listed by topic, **not** by number. Numbers are assigned when an ADR is written, by taking
the next unused number in `docs/decisions/`. Pre-assigning them has twice produced conflicts.

- **Order idempotency and deterministic client/order IDs** — required by ADR-0002 §12
  *before* any automated order testing, i.e. before Phase 2 implementation.
- **Point-in-time data provider selection** — after the Phase-0 data audit.
- **Live-execution Gate 2 authorization mechanism** — before live trading is considered.
