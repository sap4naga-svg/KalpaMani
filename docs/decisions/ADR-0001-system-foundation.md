# ADR-0001 — System Foundation

- **Status:** Accepted
- **Date:** 2026-08-24
- **Deciders:** Project owner (human governance)
- **Supersedes:** —
- **Authority:** Blueprint V2.1 (`docs/architecture/KalpaMani_Blueprint_V2_1.pdf`)

---

## Context

KalpaMani is a new autonomous long/short U.S. equity swing & momentum trading system.
Blueprint V2.1 locks the architecture; this ADR records the foundational technology and
governance decisions that the bootstrap implements, so that later sessions have a stable,
citable baseline and any deviation is visible as a new ADR.

The overriding constraint is Blueprint V2.1 §1: *AI may improve information processing.
Mathematics and deterministic software control money, risk and broker actions.*

---

## Decision

### Project identity

| Item | Decision |
|---|---|
| Project | **KalpaMani** |
| Primary language | **Python** (≥3.11, src-layout package `kalpamani`) |
| Runtime | **Python + Docker** |
| Initial research/backtest engine | **QuantConnect LEAN** |
| Primary broker | **Interactive Brokers (IBKR Pro)**, behind a `BrokerAdapter` |
| Initial broker environment | **IBKR Paper** |
| Live trading | **Disabled** (hard-disabled in code; two-gate design) |
| Database | **PostgreSQL** (planned; optional TimescaleDB) |
| Source control | **GitHub, private**, owner `sap4naga-svg` |
| Default branch | `main` |

### Capital

| Item | Decision |
|---|---|
| Strategy capital | **USD 80,000** |
| Source of truth | Explicit human allocation — **never** broker-reported equity |
| Long planned risk / trade | 0.50% → $400 |
| Short planned risk / trade | 0.25% → $200 |
| Max open planned risk | ~5% → $4,000 |
| Max individual position | ~8–10% → $6,400–$8,000 |
| Initial gross short exposure | ≤25% → $20,000 |
| Initial leverage | **None** |

Broker equity and strategy capital are separate concepts by construction. A simulated
IBKR paper NetLiquidation of USD 1,000,000 must never become strategy capital.

### Strategy scope

| Item | Decision |
|---|---|
| Core V1 strategies | **Momentum Breakout**, **Momentum Pullback**, **PEAD** |
| Phase 2 strategy | **Peer Catalyst Momentum** |
| Direction | Long **and** short (short is a separate strategy family, not the inverse of the long book) |
| Universe | ~1,200 liquid U.S. common stocks (NYSE/NASDAQ, price >$10, cap >~$1.5B, ADDV >~$25M, >250 days history) |
| Horizon | Primary **2–30 trading days** |
| Scanner | **Deterministic Python/SQL** — no AI scanner |
| Ranking | Cross-sectional rank/Z-score composites: earnings/revision momentum (~35–40%), relative/residual momentum (~35–40%), price/volume quality (~20–30%) |
| Automated options | **Excluded** from V1 |
| Social / X signals | **Excluded** from V1 |

### AI scope

| Item | Decision |
|---|---|
| AI components | **Research Agent** + **Challenger Agent** only |
| AI output | Bounded structured evidence with timestamped source provenance, model version and prompt version |
| AI may not | Size positions, override risk, bypass portfolio or broker controls, submit trades, disable safety systems |

### Risk and execution

| Item | Decision |
|---|---|
| Risk engine | **Deterministic**, plus an explicit gap/event-risk layer |
| Averaging down | **Disabled** |
| Pyramiding | Winners only, confirmation required |
| Execution | **Automatic only after deterministic approval** (in mature production) |
| Human trade approval | Not required in mature production; humans govern models, capital, parameters, exceptions, broker authentication/session maintenance and the kill switch |

---

## Consequences

**Positive**

- The money-control path is deterministic and auditable end to end; AI sits outside it.
- Broker replaceability is preserved by the `BrokerAdapter` boundary from day one.
- The two-gate live-trading design makes accidental live execution structurally
  impossible rather than merely discouraged.
- Separating strategy capital from broker equity removes the single most dangerous
  paper-to-live sizing error before any code can depend on it.

**Negative / accepted costs**

- LEAN constrains some engine choices; mitigated by keeping strategy and risk logic in
  our own package rather than inside LEAN algorithm classes.
- Point-in-time analyst revisions and historical borrow conditions are the hardest data
  problems and are **Phase-0 blocking items**; they are not solved by this ADR.
- Requiring an ADR for architectural deviation adds friction. This is intentional.

---

## Bootstrap scope boundary

This ADR covers **foundation only**. The bootstrap deliberately implements **no**
brokerage connectivity, **no** strategy logic, **no** risk engine and **no** order path.
`src/kalpamani/{broker,data,execution,risk,portfolio,research,monitoring}` and the three
strategy packages are empty by design, and a test enforces that.

---

## Follow-ups

> **Numbering corrected twice.** This list originally pre-assigned ADR-0002 to point-in-time
> data provider selection; the `BrokerAdapter` boundary needed it first. It then pre-assigned
> ADR-0003 to the same item; the Read-Only-API errata needed that. Pre-assignment is the
> problem, so it has been dropped.

**Written:** ADR-0002 (BrokerAdapter and the brokerage boundary) ·
ADR-0003 (Broker-side order controls are not safety invariants).

> **Numbers are assigned at write time**, by taking the next unused number in
> `docs/decisions/`. Follow-ups are listed by topic only. Pre-assigning numbers here caused
> two conflicts already (ADR-0002 and ADR-0003 were both claimed in advance by items that
> had not been written yet), so this list deliberately does not do it.

- **Order idempotency and deterministic client/order IDs** — required by ADR-0002 §12
  *before* any automated order testing, i.e. before Phase 2 implementation.
- **Point-in-time data provider selection** — after the Phase-0 data audit.
- **Live-execution Gate 2 authorization mechanism** — before live trading is considered.
