# KalpaMani

An autonomous long/short **U.S. equity swing & momentum trading system** with deterministic
risk and selective, bounded AI research.

> **Status: BOOTSTRAP / FOUNDATION.** No brokerage connectivity, no strategy logic and no
> order path exists. Live trading is hard-disabled. This repository currently contains
> architecture, governance, security posture and a safe configuration foundation only.

---

## Mission

Trade liquid U.S. common stocks long and short over a primary **2–30 trading-day horizon** —
automatically discovering, ranking, entering, pyramiding, monitoring and exiting positions —
while humans govern models, capital scaling, parameter releases, exceptions, broker
authentication and an independent kill switch rather than individual trades.

**Locked principle (Blueprint V2.1 §1):**

> AI may improve information processing. Mathematics and deterministic software control
> money, risk and broker actions.

This is a research and engineering project. Any performance figure in the blueprint is a
**hypothesis for validation, not a guarantee**. Nothing here is investment advice.

---

## Architecture summary

```
MARKET DATA + FUNDAMENTALS + NEWS/EVENTS
        v
POINT-IN-TIME DATA PLATFORM
        v
DETERMINISTIC UNIVERSE / FACTOR SCANNER      (Python/SQL — no AI scanner)
        v            long ranks / short ranks
STRATEGY ENGINE      Breakout | Pullback | PEAD
        v            top candidates only
AI RESEARCH  ->  AI CHALLENGER               (bounded structured evidence + provenance)
        v
DETERMINISTIC FINAL SCORE
        v
STRATEGY RISK BUDGET
        v
MARKET / EVENT / GAP PERMISSION
        v
BORROW CHECK IF SHORT
        v
DETERMINISTIC RISK ENGINE
        v
ORDER MANAGER -> LEAN -> BROKER ADAPTER -> IBKR PRO
        v
PARTIAL/FULL FILL PROTECTION
        v
POSITION MANAGEMENT -> RECONCILIATION
        v
JOURNAL + ATTRIBUTION + HEALTH
```

**Core V1 strategies:** Momentum Breakout, Momentum Pullback, PEAD (post-earnings drift).
**Phase 2:** Peer Catalyst Momentum.
**Universe:** ~1,200 liquid U.S. common stocks.
**Engine:** QuantConnect LEAN. **Broker:** IBKR Pro behind a `BrokerAdapter`.
**Database:** PostgreSQL (planned).

---

## Current safety posture

| Control | State |
|---|---|
| Live trading | **HARD-DISABLED** (two independent gates; Gate 2 not implemented) |
| Brokerage connectivity | **None implemented** |
| Order submission | **Impossible** — no order path exists |
| Default environment | `RESEARCH` (cannot reach a broker even in principle) |
| Leverage | None |
| Options | Not V1 |
| Social / X signals | Not V1 |
| Averaging down | Disabled by design |
| Secrets in repo | None; `.env` is git-ignored, only `.env.example` is committed |

Live execution is deliberately **not** reachable by setting a single value. Selecting
`KALPAMANI_ENV=live` is accepted, reported honestly, and still authorizes nothing.

---

## Environments

| Environment | Brokerage | Orders | Purpose |
|---|---|---|---|
| **RESEARCH** *(default)* | none | none | Backtests, factor research, offline analysis. |
| **PAPER** | IBKR Paper only | only after a separately approved phase | Development and forward validation. |
| **LIVE** | IBKR live | **hard-disabled** | Requires an approved phase **and** a second independent authorization gate. |

---

## Strategy capital

```
Broker account equity                    (observed; informational only)
        v
KalpaMani allocated strategy capital     (AUTHORITATIVE — USD 80,000)
        v
Strategy risk budgets
```

Strategy capital is a **deliberate human allocation**, not the broker balance. The IBKR
paper account may report **USD 1,000,000**; that simulated number must never become
KalpaMani strategy capital. `StrategyCapital` is immutable and offers no path by which an
observed broker equity can overwrite the allocation.

Initial configuration defaults (Blueprint V2.1 §10) — **research parameters, not
performance expectations**:

| Control | Value | On USD 80,000 |
|---|---|---|
| Long planned risk / trade | 0.50% | $400 |
| Short planned risk / trade | 0.25% | $200 |
| Max open planned risk | ~5% | $4,000 |
| Max individual position | ~8–10% | $6,400–$8,000 |
| Max gross short exposure | ≤25% | $20,000 |
| Leverage | none | — |

---

## Repository layout

```
KalpaMani/
├── CLAUDE.md                 Binding operating rules (read first)
├── README.md
├── .gitignore                Security-first exclusions
├── .env.example              Variable names + placeholders ONLY
├── pyproject.toml
├── docs/
│   ├── architecture/         KalpaMani_Blueprint_V2_1.pdf  (authoritative)
│   ├── decisions/            Architecture Decision Records
│   └── runbooks/             Operational procedures
├── src/kalpamani/
│   ├── common/               Environment, strategy capital, settings, errors  [IMPLEMENTED]
│   ├── broker/               BrokerAdapter abstraction                        [empty by design]
│   ├── data/                 Market data + fundamentals ingestion             [empty by design]
│   ├── execution/            Orders, fill protection, reconciliation          [empty by design]
│   ├── risk/                 Deterministic risk engine                        [empty by design]
│   ├── portfolio/            Allocation and exposure limits                   [empty by design]
│   ├── research/             AI Research + Challenger agents                  [empty by design]
│   ├── monitoring/           Health, journal, alerts, kill switch             [empty by design]
│   └── strategies/           breakout/ pullback/ pead/                        [empty by design]
├── lean/                     config/  projects/
├── tests/                    unit/  integration/  broker/
├── config/                   research/  paper/  live/
├── scripts/  docker/  logs/
```

---

## Prerequisites

| Tool | Required | Purpose |
|---|---|---|
| Python ≥3.11 | **yes** | Primary language |
| Git | **yes** | Source control |
| GitHub CLI (`gh`) | **yes** | Repository management (account `sap4naga-svg` only) |
| Docker | Phase 1+ | LEAN runtime and reproducible deployment |
| QuantConnect LEAN CLI | Phase 1+ | Backtests and paper/live algorithm engine |
| PostgreSQL | later | Features, signals, trades, audit state |

### Setup

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"     # Windows
# source .venv/bin/activate && pip install -e ".[dev]"  # POSIX
```

### Verify

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m mypy
```

---

## Configuration

Configuration is read from **environment variables**, with safe defaults when unset.
Copy `.env.example` to `.env` and fill in locally — `.env` is git-ignored and must never
be committed.

```python
from kalpamani import load_settings

settings = load_settings()
settings.environment  # Environment.RESEARCH
settings.strategy_capital_usd  # Decimal("80000")
settings.live_trading_enabled  # False — always, at bootstrap
print(settings.describe_safety_posture())
```

**Secrets never live in this repository.** Brokerage passwords, 2FA secrets, API tokens
and private keys come from environment variables or an external secrets manager, and are
never printed, logged, committed or pasted into an AI chat session.

---

## What is NOT implemented

Nothing below exists yet, and none of it is authorized:

- IBKR connectivity of any kind (no TWS/IB Gateway, no live or paper connection)
- LEAN brokerage connection or any algorithm project
- Order submission — paper or live
- Breakout, Pullback and PEAD strategy logic
- Short-selling logic, borrow checks, SSR/squeeze controls
- AI Research Agent and Challenger Agent
- The portfolio and deterministic risk engine (only the *parameters* exist)
- Scanner, factor pipeline, point-in-time data platform
- Database schema, dashboard, alerting, kill switch
- Purchased market data; production cloud infrastructure

---

## Next planned phase

**PHASE 1 — IBKR PAPER CONNECTIVITY** *(requires explicit written approval)*

```
LEAN -> IBKR PAPER -> subscribe to one liquid U.S. equity -> receive market data
     -> read brokerage/account state -> NO ORDER SUBMISSION -> clean shutdown + reconciliation
```

Phase 1 must also prove that KalpaMani strategy capital remains **$80,000** even when the
IBKR Paper account reports a NetLiquidation of **$1,000,000**.

---

## Governance

Authority order: **Blueprint V2.1 → approved ADRs → CLAUDE.md → approved task spec →
implementation judgment.** Architectural deviations require an approved ADR. See
[CLAUDE.md](CLAUDE.md) for the binding rules.

**License:** Proprietary. All rights reserved.
