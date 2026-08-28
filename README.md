# KalpaMani

An autonomous long/short **U.S. equity swing & momentum trading system** with deterministic
risk and selective, bounded AI research.

> **Architecture authority: Blueprint V3.0, adopted 2026-08-27.**
> [`docs/architecture/KalpaMani_Blueprint_V3_0.pdf`](docs/architecture/KalpaMani_Blueprint_V3_0.pdf),
> adopted by [ADR-0006](docs/decisions/ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md).
> Blueprint V2.1 is **preserved unaltered as historical architecture evidence** and is no
> longer in the authority order. The V2.1→V3 delta is indexed in
> [BLUEPRINT_V3_ADOPTION.md](docs/architecture/BLUEPRINT_V3_ADOPTION.md).
>
> **Status: Phase 3A A1 ACCEPTED (2026-08-27). Sharadar provider-integration Slice 1
> AUTHORIZED, CODE ONLY (2026-08-28). Phase 3 overall NOT COMPLETE.**
> Phase 1 (Paper connectivity) and Phase 2 (a narrowly certified one-share SPY Paper order
> lifecycle) are complete and accepted; the vendor-neutral point-in-time foundation kernel
> is accepted **on synthetic fixtures only**. Adopting V3 is a governance change — it is
> **not** Phase 3 completion and authorizes no implementation.
>
> **Next governed work: the remainder of Phase 3A, and the still-open provider decisions.**
> **No provider is connected — the adapter authorized by
> [ADR-0009](docs/decisions/ADR-0009-sharadar-provider-realistic-implementation.md) has never
> sent a request.** No subscription, no vendor account, no private credential, no Services Data,
> no production ingestion. No real production data exists. Short research is not authorized. No
> strategy or Brain implementation is authorized. Live trading is hard-disabled.

---

## Mission

Trade liquid U.S. common stocks long and short over a primary **2–30 trading-day horizon** —
automatically discovering, ranking, entering, pyramiding, monitoring and exiting positions —
while humans govern models, capital scaling, parameter releases, exceptions, broker
authentication and an independent kill switch rather than individual trades.

**Locked principle (Blueprint V3.0 §2, carried unchanged from V2.1 §1):**

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

The Strategy Brain ends at **`CandidateIntent`** — which may carry thesis, evidence,
lineage and risk context, but never shares, dollar size, order type, route or any order ID.
Portfolio construction, sizing, risk, order approval and execution stay deterministic and
downstream. **None of this is implemented or authorized** (Blueprint V3.0 §8, Appendix A).

**Alpha families (V3.0 §9):** Momentum Continuation — containing the *Breakout* and
*Pullback* modules under one shared factor-risk budget · Event / Information Drift (PEAD) ·
Fundamental Deterioration Short. **Different labels do not constitute diversification**;
whether Breakout and Pullback are economically distinct is open gate **G7**.
**Universe:** ~1,200 liquid U.S. common stocks.
**Engine:** QuantConnect LEAN. **Broker:** IBKR Pro behind a `BrokerAdapter`.
**Database:** PostgreSQL (planned).
**Preferred historical PIT stack:** Sharadar + SEC EDGAR. Sharadar is the **implementation
target** for provider-realistic Phase-3A work (ADR-0009) and is **still not the selected
production provider** — gate **G1** is open, and G3 is closed for personal use only (ADR-0008).

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

Initial configuration defaults (Blueprint V3.0 §11.1, unchanged from V2.1 §10) —
**research parameters, not performance expectations**:

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
│   ├── architecture/         KalpaMani_Blueprint_V3_0.pdf  (AUTHORITY, never edited)
│   │                         KalpaMani_Blueprint_V2_1.pdf  (historical, never edited)
│   │                         BLUEPRINT_V3_ADOPTION.md  (V2.1->V3 delta + doc control)
│   │                         BLUEPRINT_ERRATA.md  (V2.1 empirical corrections index)
│   ├── decisions/            Architecture Decision Records
│   ├── phase3/               Point-in-time data foundation plan
│   └── runbooks/             Operational procedures
├── infra/
│   └── aws/research-data-plane/   Terraform DESCRIPTION of the private research
│                                  data plane. NEVER APPLIED; no AWS resource exists
├── src/kalpamani/
│   ├── common/               Environment, strategy capital, settings, errors  [IMPLEMENTED]
│   ├── broker/               BrokerAdapter abstraction                        [IMPLEMENTED — read-only + bounded orders]
│   ├── data/                 Point-in-time data platform                      [Phase 3 planning accepted; A1 kernel ACCEPTED on synthetic fixtures only]
│   │   ├── objectstore.py    Provider-neutral logical object contract         [ADR-0009 — in-memory implementation only; no cloud writer]
│   │   └── ingest/sharadar/  The one provider package                         [ADR-0009 — CODE ONLY; has never sent a request]
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
- Purchased market data
- **Any AWS resource.** The research data plane is a Terraform *description* that has never
  been applied — no AWS account exists, nothing is provisioned, and nothing has been spent

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

## Current phase

**PHASE 3 — POINT-IN-TIME DATA FOUNDATION**

| | |
|---|---|
| Planning | **ACCEPTED / MERGED** |
| Stage 3A A1 — point-in-time foundation kernel | **ACCEPTED (2026-08-27)** |
| Stage 3A — Sharadar provider-integration Slice 1 | **AUTHORIZED / IN IMPLEMENTATION (2026-08-28, ADR-0009) — CODE ONLY** |
| Phase 3 overall | **NOT COMPLETE** |
| Full Stage 3A real-data ingestion | **NOT AUTHORIZED** |
| Stage 3A A2 / A3 — subscription / purchase | **NOT STARTED / NOT AUTHORIZED** |
| Phase 3B / 3C / 3D | **NOT STARTED / NOT AUTHORIZED** |
| ADR-0005 | **PROPOSED** |
| ADR-0006 — Blueprint V3.0 adoption | **ACCEPTED (2026-08-27)** |
| ADR-0007 — cloud-first research data plane | **ACCEPTED on merge (2026-08-27)** |
| [ADR-0008](docs/decisions/ADR-0008-sharadar-personal-use-license-and-private-qualification.md) — Sharadar personal-use licence | **ACCEPTED on merge (2026-08-27)** |
| [ADR-0009](docs/decisions/ADR-0009-sharadar-provider-realistic-implementation.md) — Sharadar provider-realistic implementation | **ACCEPTED on merge (2026-08-28)** |
| G1 provider selection · G2 production information-set profile | **OPEN** |
| G3 vendor licensing — Sharadar personal use | **CLOSED (2026-08-27, ADR-0008)** |
| G4 analyst revisions · G5 historical borrow | **OPEN** |
| G6 options overlay · G7 strategy-taxonomy evidence | **OPEN (added by V3.0)** |
| AWS account | **EXISTING** — pre-dates this work; configured for the KalpaMani foundation 2026-08-27 |
| AWS research foundation | **PROVISIONED (2026-08-27)** — [status](docs/operations/aws-foundation-status.md) |
| Cloud spend beyond the idle foundation | **NOT AUTHORIZED** |
| Provider purchase / trial / credentialing | **NOT AUTHORIZED** |
| Real external-data acquisition | **NOT STARTED** |
| Short research | **NOT AUTHORIZED** |
| Strategies / Brain / AI / portfolio / risk | **NOT IMPLEMENTED / NOT AUTHORIZED** |
| Live trading | **HARD-DISABLED** |

The plan lives in [docs/phase3/](docs/phase3/phase3-pit-data-foundation-charter.md), with
[ADR-0005](docs/decisions/ADR-0005-point-in-time-data-architecture.md).

**One implementation slice is accepted: the vendor-neutral A1 foundation kernel** — [docs/phase3/phase3a-a1-foundation-kernel.md](docs/phase3/phase3a-a1-foundation-kernel.md).
It implements the merged point-in-time contract as executable, type-checked Python and proves it
against **repository-owned synthetic fixtures**. That is a proof the contract can be *mechanised*,
which is a different claim from proving that anyone's data satisfies it.

**A1 is not provider qualification.** Provider tests P1–P9 remain **unrun**, and no real provider
satisfies the contract merely because A1 passed. **Merging A1 grants no authority for A2, A3,
Phase 3B, 3C or 3D.**

> **No provider is connected. No production data exists. No short research is authorized.**
> The A1 slice adds no runtime dependency, makes no network call, and touches no brokerage.
> Nothing in it is vendor qualification or production evidence.

**Phase 3 planning is accepted; implementation beyond the A1 kernel is NOT AUTHORIZED.**

**Phase 3 is not complete.** The proposed architecture and provider decisions remain subject to
ADR-0005's five open gates — provider selection, the production information-set profile,
vendor licensing, the analyst-estimate gap, and borrow-history qualification. None is resolved
by this slice.

Phase 3B, 3C and 3D carry no authority from it, and beginning any of them requires explicit
written authorization.

### Research data plane — private AWS cloud-first, and nothing built

[ADR-0007](docs/decisions/ADR-0007-cloud-first-research-data-plane.md) makes a **private AWS
account the intended authoritative location** for licensed research data and heavy deterministic
research compute, replacing the laptop-authoritative store proposed in ADR-0005 §11. Parquet,
DuckDB and Python are unchanged; only the location moves, and PostgreSQL's operational role under
ADR-0001 is untouched. The **laptop remains the development and control workstation** — an
optional cache, never the authority.

Two private buckets, split by one question — *can vendor rows be recovered from this artifact?*
Yes, **or uncertain**, means licensed:

| | |
|---|---|
| **Licensed** bucket | bronze / silver / gold / qualification. **Deletion-first:** no versioning, no Object Lock, no replication, no archival lifecycle, no backup |
| **Control** bucket | manifests, lineage, receipts, approved non-reconstructable outputs |

The licensed bucket runs *against* conventional cloud durability practice on purpose. A vendor
licence may require destroying every copy within 30 days of a termination that arrives without
notice, and every one of those features would defeat that. Bronze immutability does not depend on
them: it comes from content-addressed names and append-only publication, which the A1 kernel
already implements. The termination procedure exists in advance and has never been run —
[vendor-data-cloud-deletion.md](docs/runbooks/vendor-data-cloud-deletion.md).

> **The foundation exists; nothing uses it.**
> [`infra/aws/research-data-plane/`](infra/aws/research-data-plane/) was applied on 2026-08-27 —
> 36 resources, verified 66/66 against the live account
> ([status](docs/operations/aws-foundation-status.md)). At foundation closeout it was an empty,
> idle platform: both research-data buckets held nothing, the image registry was empty, no task
> definition existed and nothing ran. **Bucket emptiness is a closeout observation, not a
> standing invariant** — owner-authorized Phase-3 qualification may place private licensed
> material under the licensed bucket's `qualification/` prefix.
>
> Provisioning a platform is not permission to use it. **No provider is selected, no provider
> credential exists, no vendor data has been retrieved and no ingestion has run.** Provider
> purchase, credentialing, ingestion and any further cloud spend each remain a **separate written
> authorization**. **G1 OPEN · G2 OPEN · G3 CLOSED (Sharadar personal use, ADR-0008) · G4 OPEN · G5 OPEN · G6 OPEN · G7 OPEN**, ADR-0005 **remains PROPOSED**, and Phase 3
> remains **NOT COMPLETE**.

### Sharadar personal-use licence and private qualification — G3 closed

[ADR-0008](docs/decisions/ADR-0008-sharadar-personal-use-license-and-private-qualification.md) records the owner's acceptance of the **published** Sharadar Personal Use
License for personal research, personal backtesting, programmatic API use and automated trading of
the owner's own account. The drafted Q1–Q8 vendor clarification is **CANCELLED — NOT SENT —
historical evidence only** and is retained, because Q7 (bar construction) and Q8 (Full History
depth) must still be answered before any purchase.

**G3 is CLOSED for Sharadar personal use. Every other gate is OPEN**, Sharadar is **not selected**
as the production provider, nothing has been purchased, no vendor account exists and no private
credential exists.

[`scripts/sharadar_private_qualification.py`](scripts/sharadar_private_qualification.py) is a
standalone P1–P9 qualification harness using **only the vendor's published public test key**. Its
methodology is public; **its output is not**. Network access is off unless `--private-live-run` is
passed and the AWS identity gate passes; it refuses to run under pytest or CI; stdout is an
allowlist; and the exit code reports harness success or failure only, never a provider verdict.
Results live in the licensed S3 bucket and in git-ignored `.runtime/`, and never in this
repository. It is **not** a production provider adapter and adds no dependency.

### Sharadar provider-integration Slice 1 — authorized, code only, never run

[ADR-0009](docs/decisions/ADR-0009-sharadar-provider-realistic-implementation.md) records the
owner's authorization of the first provider-realistic Phase-3A slice, and its exact boundary.

**Authorized:** provider-specific code, provider-neutral interfaces, deterministic request
construction from public documentation, credential-**injection** interfaces, redaction, pacing,
bounded retries, Bronze publication mechanics, content addressing, synthetic-only tests.

**Not authorized:** a subscription, a purchase, a trial, a vendor account, billing details, a
private credential, **any API call**, Services Data, production ingestion, Silver or Gold
real-data work, the real S3 writer, ECR or ECS, `terraform apply`, any AWS mutation, broker or
LEAN activity, Paper expansion, live trading.

`src/kalpamani/data/ingest/sharadar/` is the one place vendor knowledge lives; the A1 kernel and
every vendor-neutral package stay vendor-neutral, and no other production module names the
provider. **No API key value exists anywhere under `src/`** — not a private one, and not the
vendor's published test token, which stays in the manual harness. **The package has never sent a
request**: one module is network-capable, no production module, script or runner constructs it,
and importing the package opens no socket. Static tests prove each of those.

The transport is **pinned to one origin by parsing** the URL — scheme, host, port, empty userinfo,
empty fragment and the documented path prefix — because `startswith("https://")` admits both a
lookalike host and a userinfo prefix. Redirects are refused rather than followed (a 3xx would hand
the query string, and so the key, to the `Location` host), ambient proxy discovery is off, no
opener is installed globally, and a successful body is bounded. A dedicated synthetic test builds
the transport with a **fake opener** and proves each of those without opening a socket: *dormant*
is not allowed to mean *untested*.

Storage goes through a provider-neutral `ResearchObjectStore` contract offering **immutable
logical names with a content-integrity binding**: a key is a name *and* the digest the object must
hold, so a forged key cannot read another object's bytes. Keys are **deeply frozen** — segments are
copied into a fresh plain tuple of plain strings and subclassing is refused — and payloads must be
exact immutable `bytes`, because a caller-held list or buffer could otherwise change a key or its
content after it had been validated and filed.

**`LICENSED` is the only classification this slice publishes.** `ObjectKey.control` was withdrawn:
a free-text attestation accepted whenever it was merely non-blank is not auditable clearance, and
there is no permitted-output artifact to publish yet. Acquisition identity — `(digest, run id)` —
is claimed under the reserved `bronze/_acquisition_claims/`, so two providers cannot claim one
retrieval; the leading underscore is refused by the path grammar, so no provider can collide with
it, and the deletion runbook's existing `bronze/` step already covers it. Payloads and acquisition
records stay separable by provider prefix; **claims are not**, and the design says so rather than
implying otherwise. Durable metadata has **no free-text field at all**, and ranges and instants are
*parsed* rather than pattern-matched. Only an in-memory store implementation exists — the real S3
writer is a separate, later, separately authorized slice, and the project still declares **no
runtime dependency**.

**Naming an implementation target is not selecting a production provider. G1 remains OPEN.** A
public-source re-check on 2026-08-28 answered neither Q7 (bar construction and origin) nor Q8
(Full History depth per table) — `PSR-SHD-122` and `PSR-SHD-123` in
[provider-source-register.md](docs/phase3/provider-source-register.md) §R4, with the vendor not
contacted and the API not called. **Both remain pre-purchase blockers.**

**Blueprint V3.0 is ADOPTED and is the current architecture authority (2026-08-27),** by
owner authorization through a documentation-only pull request —
[ADR-0006](docs/decisions/ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md).
Blueprint V2.1 is preserved unaltered as historical evidence.

**That is a governance change, not a phase milestone.** V3 adoption does not complete
Phase 3, does not resolve any gate, and authorizes no implementation: A2, A3, Phase 3B/3C/3D,
the Phase-4 Brain, strategies, AI agents, provider access, Paper expansion, live trading,
capital changes and leverage each still require their own written authorization.

Two non-blocking follow-ups are carried forward, neither of which is authorization to begin
work: `TradeRecord.orders` deep immutability is a separately governed **Phase-2 hardening**
matter; and future provider qualification may expose additional contract requirements, which
would create a **new reviewed version** rather than rewrite A1's evidence.

---

## Governance

Authority order: **Blueprint V3.0 → approved ADRs → CLAUDE.md → approved task spec →
implementation judgment.** Architectural deviations require an approved ADR. See
[CLAUDE.md](CLAUDE.md) for the binding rules.

Blueprint V2.1 remains historical architecture evidence and is not deleted, but it is no
longer in the authority order. **Neither Blueprint PDF is ever edited** — corrections are
recorded in an ADR and indexed beside the document.

**License:** Proprietary. All rights reserved.
