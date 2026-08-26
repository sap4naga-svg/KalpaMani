# KalpaMani

An autonomous long/short **U.S. equity swing & momentum trading system** with deterministic
risk and selective, bounded AI research.

> **Status: PHASE 2 COMPLETE AND ACCEPTED (2026-08-26).** The controlled IBKR **Paper**
> order lifecycle is certified end to end: one `BUY 1 SPY`, actual fill, protective stop,
> a genuine LEAN/Gateway restart, recovery by durable broker-native identity, controlled
> exit, flat. **Execution plumbing, not a strategy** — no scanner, no signals, no alpha.
> Live trading remains hard-disabled. Certified scope is narrow and stated in
> [the certification record](docs/certification/phase2-paper-order-lifecycle.md).

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
| Brokerage connectivity | IBKR **Paper** only — read-only connectivity validated 2026-08-24; bounded order lifecycle certified 2026-08-26 |
| Order path | **Exists, and is bounded and certified** — IBKR Paper, SPY, long, exactly 1 share ([certification](docs/certification/phase2-paper-order-lifecycle.md)) |
| Order submission | Requires an **explicit run-scoped human arm** that is consumed on use. **No arm is currently active**, so the system can reconcile but cannot order |
| Strategy-generated orders | **None authorized.** No scanner, no signals, no strategy can reach the order path |
| Default environment | `RESEARCH` (cannot reach a broker even in principle) |
| Leverage | None |
| Options | Not V1 |
| Social / X signals | Not V1 |
| Averaging down | Disabled by design |
| Secrets in repo | None; `.env` is git-ignored, only `.env.example` is committed |
| Broker-side order guards | **Not a control** — LEAN disables them at startup ([ADR-0003](docs/decisions/ADR-0003-broker-side-order-controls-are-not-safety-invariants.md)) |

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

**Proven against the live paper account (2026-08-25):**

```
[BROKER-STATE:scheduled-1] equity_usd=1000000.0 cash_usd=1000000.0 holdings=0 open_orders=0
[CAPITAL-SEPARATION]   broker reported equity : USD 1000000.0
[CAPITAL-SEPARATION]   KalpaMani allocation   : USD 80000
[CAPITAL-SEPARATION]   CONFIRMED DISTINCT: broker equity is 12.50x the KalpaMani allocation.
```

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
│   ├── architecture/         KalpaMani_Blueprint_V2_1.pdf  (authoritative, never edited)
│   │                         BLUEPRINT_ERRATA.md  (empirical corrections index)
│   ├── decisions/            Architecture Decision Records
│   └── runbooks/             Operational procedures
├── src/kalpamani/
│   ├── common/               Environment, strategy capital, settings, errors  [IMPLEMENTED]
│   ├── broker/               BrokerAdapter abstraction                        [IMPLEMENTED — read-only + bounded orders]
│   ├── data/                 Market data + fundamentals ingestion             [empty — Phase 3 planning accepted, implementation not authorized]
│   ├── execution/            Orders, fill protection, reconciliation          [IMPLEMENTED — Phase 2 certified scope only]
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

- Live order submission (paper order submission is certified; see the narrow scope below)
- Breakout, Pullback and PEAD strategy logic
- Short-selling logic, borrow checks, SSR/squeeze controls
- AI Research Agent and Challenger Agent
- The portfolio and deterministic risk engine (only the *parameters* exist)
- Scanner, factor pipeline, point-in-time data platform
- Database schema, dashboard, alerting, kill switch
- Purchased market data; production cloud infrastructure

---

## Phase 2 — certified, and what that does and does not mean

```
IBKR PAPER only · SPY only · long only · exactly 1 share · FULL-FILL lifecycle
```

Certified: one ENTRY, actual `+1` fill, one protective stop sized from the actual fill,
durable broker-native identity captured **before** a restart, a genuine LEAN and IB Gateway
restart, ownership recovered by `BROKER_ID` with the LEAN tag absent, exactly one cancellation
of the owned protective order, one `EXIT SELL 1`, a signed `-1` fill, and a flat final
reconciliation. Zero duplicate orders at any point; no accidental short.

Two runs are retained. **Run 1 FAILED** and is kept as negative evidence: it could not prove
ownership of its own stop across a restart, so it halted and left the order alone —
fail-closed, by design. **Run 2 RECONCILED.**

**Not certified** — future requirements, not defects in a deliberately narrow certification:
partial fills, multiple fill accumulation, a stop actually triggering, short lifecycle,
multiple simultaneous positions, pyramiding, strategy generation, alpha or profitability,
live brokerage execution, real-money operation.

## Next planned phase

**PHASE 3 — POINT-IN-TIME DATA FOUNDATION**

| | |
|---|---|
| Planning | **ACCEPTED / MERGED** |
| Implementation | **NOT STARTED / NOT AUTHORIZED** |
| ADR-0005 | **PROPOSED** |
| Provider purchase / trial / credentialing | **NOT AUTHORIZED** |

The plan lives in [docs/phase3/](docs/phase3/phase3-pit-data-foundation-charter.md), with
[ADR-0005](docs/decisions/ADR-0005-point-in-time-data-architecture.md).

**The planning package is accepted; Phase 3 is not complete.** Its proposed architecture and
provider decisions remain subject to ADR-0005's five open gates — provider selection, the
production information-set profile, vendor licensing, the analyst-estimate gap, and
borrow-history qualification. **No implementation authority follows from merging the plan.** No
data provider has been purchased, trialled or credentialed, and no ingestion code exists.

Beginning implementation requires explicit written authorization.

---

## Governance

Authority order: **Blueprint V2.1 → approved ADRs → CLAUDE.md → approved task spec →
implementation judgment.** Architectural deviations require an approved ADR. See
[CLAUDE.md](CLAUDE.md) for the binding rules.

**License:** Proprietary. All rights reserved.
