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
> IMPLEMENTED / ACCEPTED — PR #13 MERGED — CODE ONLY. Licensed S3 research object store
> IMPLEMENTED / ACCEPTED — PR #16 MERGED — CODE ONLY, NEVER RUN AGAINST AWS.
> Sharadar qualification runtime core IMPLEMENTED — ACCEPTED EFFECTIVE ON MERGE OF PR #17 — CODE ONLY, NEVER RUN AGAINST SHARADAR OR AWS.
> Phase 3 overall NOT COMPLETE.**
> Phase 1 (Paper connectivity) and Phase 2 (a narrowly certified one-share SPY Paper order
> lifecycle) are complete and accepted; the vendor-neutral point-in-time foundation kernel
> is accepted **on synthetic fixtures only**. Adopting V3 is a governance change — it is
> **not** Phase 3 completion and authorizes no implementation.
>
> **Next governed work: the remainder of Phase 3A, and the still-open provider decisions.**
> **No provider is connected — the adapter authorized by
> [ADR-0009](docs/decisions/ADR-0009-sharadar-provider-realistic-implementation.md) has never
> sent a request.** A qualification subscription exists (ADR-0010), and its clock is running; no
> private credential, Services Data or production ingestion has entered this repository. **The
> licensed S3 object store has never run against AWS** — the adapter has no bucket identifier and
> no credential bound to it, and has sent zero AWS requests. No real production data exists. Short
> research is not authorized. No strategy or Brain implementation is authorized. Live trading is
> hard-disabled.

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
│   │   ├── objectstore.py    Provider-neutral logical object contract         [ADR-0009 — the contract and its in-memory backend]
│   │   ├── storage/s3.py     Licensed S3 backend of that contract             [ADR-0011 — CODE ONLY; has never run against AWS]
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
- **Any use of the AWS research foundation by this repository.** It is provisioned and idle. The
  licensed S3 object store exists as reviewed code and has **never run against AWS**: nothing binds
  a bucket identifier or a credential to the adapter, nothing constructs a client or calls the
  store, and the adapter has sent zero AWS requests

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
| Stage 3A — Sharadar provider-integration Slice 1 | **IMPLEMENTED / ACCEPTED (ADR-0009, PR #13 merged) — CODE ONLY** |
| Stage 3A — licensed S3 research object store | **IMPLEMENTED / ACCEPTED — PR #16 MERGED — CODE ONLY, NEVER RUN AGAINST AWS** |
| Stage 3A — Sharadar qualification runtime core | **IMPLEMENTED / ACCEPTED — PR #17 MERGED — CODE ONLY, NEVER RUN AGAINST SHARADAR OR AWS** |
| Phase 3 overall | **NOT COMPLETE** |
| Full Stage 3A real-data ingestion | **NOT AUTHORIZED** |
| Stage 3A A2 / A3 — subscription / purchase | **AUTHORIZED AND PURCHASED (2026-08-28, ADR-0010)** — one month, Full History Bundle, for qualification only |
| Owner-side credential setup · application credential retrieval · provider API access · Services Data ingestion | Owner-side Sharadar secret creation and identifier configuration **OWNER-CONFIGURED / NOT YET VERIFIED BY THE ENTRY POINT**. Application credential retrieval **NOT AUTHORIZED**, provider API access **NOT AUTHORIZED**, Services Data access and ingestion **NOT AUTHORIZED**, authenticated qualification **NOT AUTHORIZED** — a subscription existing is not permission to use it, and a configured secret is not permission to read it |
| Phase 3B / 3C / 3D | **NOT STARTED / NOT AUTHORIZED** |
| ADR-0005 | **PROPOSED** |
| ADR-0006 — Blueprint V3.0 adoption | **ACCEPTED (2026-08-27)** |
| ADR-0007 — cloud-first research data plane | **ACCEPTED on merge (2026-08-27)** |
| [ADR-0008](docs/decisions/ADR-0008-sharadar-personal-use-license-and-private-qualification.md) — Sharadar personal-use licence | **ACCEPTED on merge (2026-08-27)** |
| [ADR-0009](docs/decisions/ADR-0009-sharadar-provider-realistic-implementation.md) — Sharadar provider-realistic implementation | **ACCEPTED / IN FORCE** — PR #13 merged |
| [ADR-0010](docs/decisions/ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md) — bounded Sharadar semantics, qualification subscription | **ACCEPTED / IN FORCE (2026-08-28)** — PR #15 merged |
| [ADR-0011](docs/decisions/ADR-0011-implement-the-licensed-s3-research-object-store.md) — licensed S3 research object store | **ACCEPTED / IN FORCE** — PR #16 merged |
| [ADR-0012](docs/decisions/ADR-0012-implement-the-dormant-sharadar-qualification-runtime-core.md) — dormant Sharadar qualification runtime core | **ACCEPTED / IN FORCE** — PR #17 merged |
| [ADR-0013](docs/decisions/ADR-0013-introduce-acquisition-mode-and-retire-is-backfill.md) — acquisition mode, `is_backfill` retired | **ACCEPTED / IN FORCE** — PR #18 merged |
| G1 provider selection · G2 production information-set profile | **OPEN** |
| G3 vendor licensing — Sharadar personal use | **CLOSED (2026-08-27, ADR-0008)** |
| G4 analyst revisions · G5 historical borrow | **OPEN** |
| G6 options overlay · G7 strategy-taxonomy evidence | **OPEN (added by V3.0)** |
| AWS account | **EXISTING** — pre-dates this work; configured for the KalpaMani foundation 2026-08-27 |
| AWS research foundation | **PROVISIONED (2026-08-27)** — [status](docs/operations/aws-foundation-status.md) |
| Cloud spend beyond the idle foundation | **NOT AUTHORIZED** |
| Any AWS mutation, read, verifier run or Terraform command | **NOT AUTHORIZED** — writing a client-shaped adapter is not permission to run one |
| Real bucket binding · SDK client construction · credential source | Real bucket binding **NONE**, operational secret-identifier configuration **OWNER-CONFIGURED / NOT YET VERIFIED BY THE ENTRY POINT**, Secrets Manager client constructions **ZERO**. A provider-neutral credential-source boundary **exists**, and the **ADR-0015 operator entry point is the sole permitted construction boundary** — invoked four times under separate authorization, and no invocation constructed a client or created a binding. A fifth binding-preflight attempt **NOT AUTHORIZED**, further AWS authentication diagnosis **NOT AUTHORIZED**, AWS SSO refresh/login **SEPARATELY GATED / NOT AUTHORIZED**; SDK or client construction outside that boundary **NOT AUTHORIZED** |
| [ADR-0014](docs/decisions/ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md) — dormant composition root + offline preflight | **ACCEPTED / IN FORCE** — PR #19 merged. One dormant composition root exists and **offline preflight exists**; **qualification-run execution surface NONE**, **provider-fetch operation NONE**, **object-publication operation NONE**, **runner NONE**, provider and AWS requests **ZERO** |
| [ADR-0015](docs/decisions/ADR-0015-implement-the-dormant-sharadar-private-binding-preflight.md) — dormant private-binding preflight | **ACCEPTED / IN FORCE** — PR #22 merged. One operator entry point exists and is **refused by default**; **binding preflight only**. **Four separately authorized attempts occurred and all four refused** — at the identity gate, on a missing local AWS SDK, at the fixed secret-identifier source with **`REFUSED_SECRET_IDENTIFIER`**, and at the identity gate again with **`REFUSED_IDENTITY`** — so **AWS identity-gate activity occurred** and total AWS activity was not zero, while **AWS network requests on the fourth attempt are UNKNOWN** and no **standalone** diagnosis was performed as part of the attempt — though its governed identity gate **invoked its own STS identity operation once**. A **separately authorized post-fourth standalone AWS identity diagnosis has since COMPLETED** with **`REFUSED_SSO_SESSION_MISSING_OR_EXPIRED`** — one process, one `aws sts get-caller-identity` command, exit code **255**, **missing and expired not distinguished**, the governed profile pinned in the child environment and never disclosed, its **own** underlying AWS network-request count **UNKNOWN**, **SSO-login invocations ZERO**, **authentication-repair actions ZERO**, **fifth binding-preflight attempts ZERO**. The fourth attempt **reached neither licensed-bucket resolution nor the secret-identifier source** and **did not read `KALPAMANI_SHARADAR_SECRET_ID`**. Operational secret-identifier configuration **OWNER-CONFIGURED / NOT YET VERIFIED BY THE ENTRY POINT**, owner setup having occurred **after the third attempt** and **before the fourth**, and **not read by the fourth**; Secrets Manager client constructions **ZERO**, `get_secret_value` invocations **ZERO**, Secrets Manager network requests **ZERO**, S3 client constructions **ZERO**, S3 object operations **ZERO**, provider transport constructions **ZERO**, Sharadar/provider requests **ZERO**, credential retrieval **NONE**, qualification runs **ZERO**, real bucket binding **NONE**. A fifth attempt, **further AWS authentication diagnosis**, **an AWS SSO refresh or login**, **credential access by the application** and an **authenticated qualification run stay separately gated and NOT AUTHORIZED** |
| [ADR-0016](docs/decisions/ADR-0016-correct-private-binding-preflight-failure-boundaries.md) — corrected private-binding failure boundaries | **ACCEPTED / IN FORCE** — PR #24 merged. Separates **secret-identifier**, **local dependency**, **unclassified** and **credential** refusals. Secrets Manager client constructions **ZERO**, `get_secret_value` invocations **ZERO**, Secrets Manager network requests **ZERO**, real credential retrieval **NONE**. Operational environment **SYNCHRONIZED AND VERIFIED**, Python dependency lock **ABSENT**, environment **RANGE-CONFORMANT NOT LOCK-CONFORMANT**, further environment resynchronization **SEPARATELY GATED**, a fifth binding-preflight attempt **NOT AUTHORIZED**, authenticated qualification **NOT AUTHORIZED** |
| Ingestion runner · ECS task or image · authenticated qualification run | **NOT AUTHORIZED** |
| CONTROL-classification publication | **DEFERRED / NOT AUTHORIZED** |
| Provider purchase — qualification subscription | **PURCHASED / ACTIVE (2026-08-28, ADR-0010)** |
| Provider credential state · repository consumption · provider API access · Services Data | Provider credential state **OWNER API KEY EXISTS / OWNER-ATTESTED / NOT VERIFIED BY THE ENTRY POINT**; repository/application credential retrieval or consumption **NONE / NOT AUTHORIZED**; provider API access **NOT AUTHORIZED**; Services Data access and ingestion **NOT AUTHORIZED**; authenticated qualification **NOT AUTHORIZED** — an owner-held key is not repository access, and a subscription existing is not permission to use it |
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
> Provisioning a platform is not permission to use it. **No production provider is selected, no
> credential is stored, configured or bound by this repository, no vendor data has been retrieved
> into it and no ingestion has run.** Those are claims about this repository, not about the owner's
> accounts — a qualification subscription is purchased and active (ADR-0010), and what exists in a
> vendor account is not something this repository establishes or may infer. Production-provider
> selection, credentialing, provider API access, ingestion and any further cloud spend each remain a
> **separate written authorization**. **G1 OPEN · G2 OPEN · G3 CLOSED (Sharadar personal use, ADR-0008) · G4 OPEN · G5 OPEN · G6 OPEN · G7 OPEN**, ADR-0005 **remains PROPOSED**, and Phase 3
> remains **NOT COMPLETE**.

### Sharadar personal-use licence and private qualification — G3 closed

[ADR-0008](docs/decisions/ADR-0008-sharadar-personal-use-license-and-private-qualification.md) records the owner's acceptance of the **published** Sharadar Personal Use
License for personal research, personal backtesting, programmatic API use and automated trading of
the owner's own account. The drafted Q1–Q8 vendor clarification is **CANCELLED — NOT SENT —
historical evidence only** and is retained. Q7 (bar construction) and Q8 (Full History depth) were
once described here as pre-purchase blockers; **[ADR-0010](docs/decisions/ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md)
decided both on 2026-08-28**, in different evidence states, and the owner accepted both dispositions
*for qualification*:

| | |
|---|---|
| **Q7** — daily price-bar origin | **`PUBLICLY_UNRESOLVED`**, owner-accepted for qualification. Sharadar price data stays **`PROVIDER_DERIVED`**, usable only under **`PROVIDER_REALISTIC_PIT`**, and **never represented as `PUBLIC_PIT`** |
| **Q8** — Full History depth | **`PUBLICLY_BOUNDED`**, owner-accepted for qualification. The documented per-table depths are planning boundaries, **not certified earliest records**; actual minimum dates, coverage and completeness must be **measured from the subscribed data under a separate authorization** |

**The qualification subscription is PURCHASED and ACTIVE** — Personal Use, Full History Bundle, one
month, for qualification only (ADR-0010). **Buying it selected no production provider and closed no
gate.** **G3 is CLOSED for Sharadar personal use; G1, G2 and G4–G7 remain OPEN**, and Sharadar is
**not selected** as the production provider.

What this repository can state about credentials, and all it states: **credential retrieval and
setup are not authorized; no credential is stored, configured or bound by this repository or any
slice in it; and no credential was inspected while writing this.** Whether a key exists in the
owner's vendor account is outside what this repository establishes, and nothing here infers it.

[`scripts/sharadar_private_qualification.py`](scripts/sharadar_private_qualification.py) is a
standalone P1–P9 qualification harness using **only the vendor's published public test key**. Its
methodology is public; **its output is not**. Network access is off unless `--private-live-run` is
passed and the AWS identity gate passes; it refuses to run under pytest or CI; stdout is an
allowlist; and the exit code reports harness success or failure only, never a provider verdict.
Results live in the licensed S3 bucket and in git-ignored `.runtime/`, and never in this
repository. It is **not** a production provider adapter and adds no dependency.

### Sharadar provider-integration Slice 1 — implemented, code only, never run

[ADR-0009](docs/decisions/ADR-0009-sharadar-provider-realistic-implementation.md) records the
owner's authorization of the first provider-realistic Phase-3A slice, and its exact boundary.
**PR #13 is merged, ADR-0009 is ACCEPTED and IN FORCE**, and the slice is **IMPLEMENTED / ACCEPTED —
CODE ONLY**: reviewed, merged code that has never sent a request to a vendor.

**ADR-0009 authorized:** provider-specific code, provider-neutral interfaces, deterministic request
construction from public documentation, credential-**injection** interfaces, redaction, pacing,
bounded retries, Bronze publication mechanics, content addressing, synthetic-only tests.

**The original Slice-1 boundary lives in
[ADR-0009](docs/decisions/ADR-0009-sharadar-provider-realistic-implementation.md)** and is not
reproduced here: a verbatim copy of a superseded list, sitting in a current-status document, is a
second matrix a reader can mistake for the live one.
[ADR-0010](docs/decisions/ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md)
and [ADR-0011](docs/decisions/ADR-0011-implement-the-licensed-s3-research-object-store.md)
subsequently added their own narrowly defined authorities — the bounded qualification subscription,
and the licensed S3 writer. **The list below is what governs today.**

That older list also described what an *implementation slice* could do; it never described the
owner's private affairs. A purchase the owner was authorized to make necessarily involved
owner-side account and billing activity, which this repository neither governs nor records — and
therefore neither forbids nor denies.

**Currently NOT AUTHORIZED**, and this is the list that governs a session now: credential retrieval,
setup, configuration or binding · Secrets Manager use · any provider API call · the published test
token · Services Data · bulk download · empirical qualification · production backfill · production
ingestion · Silver or Gold real data · production-provider selection · any AWS mutation, read,
verifier run or Terraform command · ECR or ECS · image builds · real bucket binding · SDK client
construction · a credential source · a qualification-run execution surface on the composition root
· a second composition root · an ingestion runner · CONTROL publication · broker or LEAN activity · Paper expansion · live
trading. **G1 and G2 stay OPEN**, ADR-0005 stays **PROPOSED**, and Phase 3 stays **NOT COMPLETE**.

**The published test token stays unauthorized deliberately.** The manual qualification harness is
*able* to read it; that is not permission to run the harness, which only the owner runs.

`src/kalpamani/data/ingest/sharadar/` is the one place vendor knowledge lives; the A1 kernel and
every vendor-neutral package stay vendor-neutral, and no other production module names the
provider. **No API key value exists anywhere under `src/`** — not a private one, and not the
vendor's published test token, which stays in the manual harness. **The package has never sent a
request**: one module is network-capable, and importing the package opens no socket. A client *is*
now constructed — by the dormant composition root (ADR-0014), from an **injected** transport and an
**injected** credential, in a class whose only operation validates a plan offline. **No credential
source exists**, so nothing can hand it a real key; nothing outside its own tests constructs it; and
its only exposed operation is offline plan validation, which reaches no transport. Static tests
prove each of those.

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
*parsed* rather than pattern-matched. The in-memory store was the only backend that
existed at Slice 1; the real S3 writer arrived as its own separately authorized slice, described
below.

**Naming an implementation target is not selecting a production provider. G1 remains OPEN.**

**Q7 and Q8 reached different evidence states, and the owner accepted both for qualification**
([ADR-0010](docs/decisions/ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md), 2026-08-28).

**Q7 — the origin of the daily bars — remained publicly unresolved.** No first-party page answers the
provenance question, so all Sharadar price data stays `PROVIDER_DERIVED`, is usable only under
`PROVIDER_REALISTIC_PIT`, and is **never represented as** `PUBLIC_PIT`. No artifact may be classified
`PUBLIC_PIT` **solely on the basis of** Sharadar price data.

**Q8 — Full History depth — was publicly bounded but not empirically verified.** The documentation
does establish per-table planning boundaries; it cannot establish actual earliest records,
completeness or point-in-time behaviour, and those must be **measured from the subscribed data**
under a separate authorization.

The vendor was not contacted and the API was not called; the evidence is public documentation
recorded as `PSR-SHD-122`–`PSR-SHD-128` in
[provider-source-register.md](docs/phase3/provider-source-register.md) §R4–§R5, with each table's
depth cited to that table's own page.

**A one-month Full History Bundle qualification subscription is purchased and active.** That is
access to *evaluate* a provider, not a choice of one: **G1 and G2 remain OPEN**, and credential
setup, any API call, Services Data access and ingestion each remain **separately unauthorized**.

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

### The licensed S3 object store — implemented, code only, never run against AWS

[ADR-0011](docs/decisions/ADR-0011-implement-the-licensed-s3-research-object-store.md) authorized
one thing: the **LICENSED-only S3 backend** of the provider-neutral `ResearchObjectStore`, written
and reviewed **while the store still has nothing bound to it** — no bucket identifier, no
credential, no client — and therefore before any of those has to be got right in a hurry. Race
conditions, checksum semantics and error sanitisation are exactly the work that goes badly when it
is in the way of something else.

```
adapter EXISTS   ·   client INJECTED   ·   no client is constructed anywhere
adapter bucket binding: NONE   ·   adapter credential binding: NONE
no profile, endpoint or region is named   ·   runner NONE   ·   __main__ NONE
callers: the dormant qualification runtime, and the dormant composition root
        that constructs it -- both on INJECTED dependencies (ADR-0014)
composition root: ONE, dormant, offline-preflight only -- see ADR-0014
AWS requests sent by the adapter: ZERO
adapter-attributable request or object-storage activity: NONE
```

**Append-only is one conditional request, not a look-first.** Publication is a single `PutObject`
carrying `IfNoneMatch="*"`, with **no preflight `HEAD`**. A `HEAD`-then-`PUT` is a
time-of-check/time-of-use race: another writer can land an object in between, and the `PUT` would
destroy evidence that verified a moment earlier. The licensed bucket carries **no versioning** by
design — a vendor termination arriving without notice must be honourable inside 30 days — so
conditional publication in software is the immutability boundary, with nothing behind it.

**Only a 412 means occupied.** A conditional `PutObject` answers `412 PreconditionFailed` when the
key exists — the condition was evaluated and it failed. `409 ConditionalRequestConflict` means a
conflicting operation was in flight and the upload is retryable; the condition was never resolved,
so it proves nothing about what is stored. Only a 412 reaches the occupancy resolution. A 409 sends
no `HeadObject`, returns no outcome and makes no idempotency or collision determination — it is a
`TRANSIENT` refusal. This slice adds **no retry loop**; a caller may retry the whole publication,
and that is safe only because every attempt stays conditional.

**Integrity is a full-object SHA-256, never an ETag and never a composite.** An ETag is a
multipart-dependent opaque token, not a content hash. S3's `COMPOSITE` SHA-256 has the same defect
wearing the right algorithm's name: it is a digest of a multipart upload's *part digests*, so it
varies with the part size. Every read-back therefore requires S3 to state
`ChecksumType="FULL_OBJECT"`, and an absent, misspelled, composite or unrecognised type is refused —
an allowlist of one, matched exactly, because a denylist would admit every checksum type AWS has not
invented yet. SSE-S3 is requested explicitly on every write rather than inherited from a bucket
default, so an object is encrypted because this code asked.

**A collision is resolved by metadata, never by downloading.** When the conditional write reports
the name occupied, `HeadObject` supplies the stored checksum and length. Identical digest *and*
length means the publication is a no-op; anything else is a refusal. The bytes are never retrieved:
this store has no read surface, and pulling vendor payloads back to compare them would put licensed
rows into a process with no business holding them.

**Ambiguity fails closed.** An unverifiable response — not a mapping, an unproven checksum type, a
missing or non-canonical checksum, a missing or negative length — is a typed refusal, never a guess
in either direction. A
permission failure is never read as absence. Every backend failure is sanitized into closed
`StrEnum` vocabularies and raised `from None`, so no bucket, key, endpoint, request id, host id or
credential-shaped text can reach a log or a traceback.

**The write surface is the whole surface.** The injected client protocol declares `put_object` and
`head_object` and nothing else — there is no read, list, delete, copy or multipart path to reach.
**Deletion stays with the separately roled path** under ADR-0007. `CONTROL` publication is refused
at admission and remains **deferred**.

**One runtime dependency, and nothing imports it.** `boto3>=1.36.0,<2.0` is declared because a real
deployment must *construct* a signed client. The floor is substantiated rather than guessed: the S3
service model bundled with `boto3==1.36.0` and `botocore==1.36.0` — the lowest `botocore` that
release permits — carries every member this store uses, including `IfNoneMatch` on `PutObject` and
`ChecksumType` on the `HeadObject` response, whose enum there is exactly
`["COMPOSITE", "FULL_OBJECT"]`. It was read from the installed model in a throwaway environment,
offline with respect to AWS. Request signing, credential resolution and retry behaviour must be the
official SDK's rather than anything written here. **No module under `src/`
imports it**: the client is injected and backend errors are classified structurally, so importing
the data platform pulls in no AWS code, opens no socket and performs no ambient credential
discovery. A static test permits only `data/storage/s3.py` — the only application module under
`src/` permitted to do so — to name the SDK at all, and asserts that even it imports none of it
today. `moto` and LocalStack were rejected — an emulator is a second
implementation of S3's semantics to be wrong about; the synthetic client instead makes its
conditional put genuinely atomic, so a check-then-write adapter would *fail* the concurrency tests
rather than pass them by luck.

**The control is absence, not care.** No credential is retrieved, inspected, created, configured
or bound anywhere in this repository; no bucket identifier is bound to the adapter or recorded
here; and no module constructs an SDK client. The store **is** called now — by the dormant
qualification runtime (ADR-0012), on an injected store — and it is now also *constructed*, by the
dormant composition root
([ADR-0014](docs/decisions/ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md)),
from an injected client and a caller-supplied bucket string. **What remains absent is what would
make either real**: a credential source, a real credential, a constructed SDK client, a bound
bucket, a runner, and any code that calls something other than the offline preflight. Each is
verified by a static test rather than asserted here.

**What that does and does not claim.** It is a statement about this repository and this slice, not
about the world: the AWS research foundation and its buckets already exist and were provisioned in
August 2026, and what exists outside this repository is not something this slice examined or may
infer. The adapter has sent **zero AWS requests** and incurred **no adapter-attributable request or
object-storage activity** — which is a claim about the adapter, not a claim that nothing anywhere
is billable.

**Writing this backend authorized nothing else.** Every AWS action, Terraform command, verifier
run, bucket binding, credential, client construction, ingestion runner, ECS task and CONTROL
publication remains **separately unauthorized**. **G1 and G2 stay OPEN**, ADR-0005 stays
**PROPOSED**, and Phase 3 stays **NOT COMPLETE**.

---

### The acquisition-mode contract — `is_backfill` retired

[ADR-0013](docs/decisions/ADR-0013-introduce-acquisition-mode-and-retire-is-backfill.md) replaced the
provider-neutral `is_backfill: bool` with a closed **`AcquisitionMode`** vocabulary of exactly three
members. **Accepted on merge of the PR introducing it**, and carrying no authority before.

| | |
|---|---|
| `QUALIFICATION` | a bounded provider-validation retrieval |
| `BACKFILL` | historical production loading |
| `UPDATE` | incremental production refresh |

The boolean could express only two of the three, so a qualification retrieval had to claim to be a
production backfill or an incremental update — and it is neither. This is an **intentional breaking
pre-data correction**: no real Services Data has ever been ingested under the retired schema, so
there is nothing to migrate. **No default, no boolean conversion, no inference, no alias, no legacy
reader and no dual-write** exists, and the retired key is refused by the durable field allowlist.

**Declared, never inferred.** Not from dates, ranges, record counts, payload contents, first-seen
times, prior coverage, the provider or the dataset. `record_count` and `new_record_count` do not
determine it, and the §4.2.4 historical-coverage check **observes** late-arriving or newly-covered
data without setting, confirming or contradicting it.

**It proves nothing on its own** — not PIT admissibility, public availability, provider availability,
row chronology, or whether a provider silently supplied revised historical rows. `BACKFILL` grants
no earlier PIT availability; `UPDATE` does not establish that the rows carry no historical
revisions; `QUALIFICATION` neither selects a provider nor qualifies the data.

**Single source of truth.** `RetrievalMetadata.acquisition_mode` is required and has no default.
`IngestionRun` derives it, `BronzePublication` does not duplicate it, the Sharadar bridge requires it
explicitly, and the dormant runtime passes `QUALIFICATION` with no override. Durable records carry
`"acquisition_mode": "QUALIFICATION"` as a plain exact string; `"is_backfill"` is gone.

**The `is_backfill` metadata blocker is CLOSED effective on merge**, and only if the complete
removal is accepted. **Real Sharadar qualification remains NOT AUTHORIZED and has never run** —
closing this blocker removed one obstacle in front of *asking* for authorization, and changed
nothing else: no credential, no client construction, no bucket binding, no runner. (A dormant
composition root was authorized separately and later, under
[ADR-0014](docs/decisions/ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md);
its only exposed operation is offline plan validation, it has no qualification-run execution
surface, and it changes nothing about that authorization.)
`BACKFILL` and `UPDATE` exist as production modes and **neither production operation is
authorized**.

**G1 OPEN · G2 OPEN · G3 CLOSED · G4–G7 OPEN**, ADR-0005 **PROPOSED**, INC-0002 **OPEN**, Phase 3
**NOT COMPLETE**, CONTROL publication **DEFERRED**, live trading **HARD-DISABLED**.

### The private-binding failure boundaries — corrected, and the environment that is not

[ADR-0016](docs/decisions/ADR-0016-correct-private-binding-preflight-failure-boundaries.md) corrects
one thing ADR-0015 produced, and **supersedes only that**: a single `REFUSED_CREDENTIAL` outcome
covered the secret-identifier source, the local SDK and client construction, and the one
`get_secret_value` call. **ADR-0015 is not edited** — it is the immutable record of the decision that
was accepted.

**Status: ACCEPTED / IN FORCE — PR #24 merged.**

Two authorized operator attempts were made against the real governed foundation. The first refused
with `REFUSED_IDENTITY`; the owner refreshed the approved AWS SSO session; the second passed the
profile pin, the identity gate and licensed-bucket resolution, and refused with `REFUSED_CREDENTIAL`.
A read-only diagnostic then established that the operational virtual environment contains **neither
`boto3` nor `botocore`** — so `_secrets_client()` raised `ModuleNotFoundError` inside the constructor,
inside the same broad exception boundary that mapped every failure in the stage to the credential.
**No Secrets Manager client existed, so there was no `get_secret_value` invocation and no Secrets Manager network request.** The identity gate had already passed on that attempt, so AWS activity did occur — just not here.

The command reported a private-credential failure for a missing local package. That would have sent
an operator to inspect a secret, a policy and an account for a problem in none of them, and it
implied AWS had been contacted when it had not. Because the identifier source was not separately
classified, whether it is configured at all **remains unknown** — the run cannot say, and nothing
here guesses.

```
outcome                                       identifier   client   invocations
authorization / profile / identity / bucket            0        0             0
secrets-boundary import refusal                        0        0             0
REFUSED_SECRET_IDENTIFIER                              1        0             0
REFUSED_DEPENDENCY at client construction              1        1             0
REFUSED_CREDENTIAL                                     1        1             1
REFUSED_DEPENDENCY after the credential                1        1             1
completed synthetic offline preflight                  1        1             1

get_secret_value invocations by this repository: ZERO
Secrets Manager client constructions: ZERO
Secrets Manager network requests: ZERO
S3 object operations: ZERO   ·   Sharadar/provider requests: ZERO
AWS identity-gate activity: OCCURRED -- total AWS activity was not zero
real credential retrieval: NONE
operational environment synchronized: DONE AND VERIFIED -- see the environment section
Python dependency lock: ABSENT   ·   environment: RANGE-CONFORMANT, NOT LOCK-CONFORMANT
a fifth binding-preflight attempt: NOT AUTHORIZED
```

**A method invocation is not a proven AWS network request.** The third column counts calls into the
injected client's `get_secret_value` method, which is what a counter can see. A real client validates
parameters locally and can reject a call after the method is entered and before anything leaves the
machine, so `REFUSED_CREDENTIAL` establishes **one admitted invocation** and not that AWS received
anything. The historical missing-SDK run establishes **zero invocations and zero AWS network
Secrets Manager network requests**, because no Secrets Manager client existed to make either — a
stronger fact, resting on absence rather than on a counter. It says nothing about the identity gate,
which had already passed on that attempt.

| | |
|---|---|
| **`REFUSED_SECRET_IDENTIFIER`** | the configured source is unavailable, raises, returns the wrong exact type, returns an empty value, or returns a value the identifier grammar refuses. **No client is built, so nothing is invoked and nothing can reach AWS.** The rule is `is_usable_secret_identifier` — the secrets boundary's own, imported rather than restated, because two spellings of one rule is how a value one stage admits becomes a value the next refuses |
| **`REFUSED_DEPENDENCY`** | the SDK is unavailable, an import fails, the client factory is unavailable or raises, construction fails, the constructed client cannot serve the one operation, the secrets boundary will not import, an exception of an unknown type escapes the retrieval, or a dependency built after the credential fails. **It never implies credential retrieval, and on its own it fixes no invocation count** — it occurs both before a client exists (zero invocations) and after a successful retrieval (one), so only the witnessed stage-specific count says which. The renamed `REFUSED_DEPENDENCIES` — a rename, not a synonym, and no alias survives |
| **`REFUSED_CREDENTIAL`** | **and only this** follows an admitted `get_secret_value` invocation: the call raised or was refused, the response is structurally invalid, `SecretString` is absent, binary came back, or the returned string is empty or invalid under the existing credential contract |
| **`REFUSED_UNCLASSIFIED`** | this program could not work out what the boundary refused — no `failure`, a `failure` with no `value`, a non-string token, an unrecognised token, or attribute access that raises. Added in correction round 1, because the two places that needed a word for *I do not know* were answering `REFUSED_CREDENTIAL` and `REFUSED_DEPENDENCY`, each a positive claim about a boundary that may never have been reached. Round 2 added the boundary member behind it: `SecretRetrievalError` normalised **any** non-member to `RESPONSE_MALFORMED`, which is credential-mapped, so a bare string or a future member could manufacture a credential claim the classifier had been proved unable to make. Non-members normalise to `SecretRetrievalFailure.UNCLASSIFIED` now |
| **No credential default** | `REFUSED_CREDENTIAL` is reachable **only** through an explicit mapping entry naming a member known to follow an admitted invocation. No `.get` default, no `else` branch, no catch-all. A vocabulary member added later by someone who did not run the totality test is `REFUSED_UNCLASSIFIED`, never a credential claim |
| **A real identifier grammar** | the identifier must be **a well-formed secret name or a complete secret ARN** — name characters exactly `A–Z a–z 0–9 / _ + = . @ -` within 512, or seven ARN fields with a recognised partition, the `secretsmanager` service, a syntactically valid Region, a twelve-digit account, the `secret` resource type and the generated six-character suffix. The earlier rule was "printable, and unspaced", which admitted shapes a client rejects locally *after* the method was entered — one invocation, then read as a credential failure |
| **The name ceiling is the name's** | round 2 corrected a boundary that ran the whole ARN resource — name **plus** the generated `-XXXXXX` — through the 512-character *name* check. AWS permits a 512-character name and appends seven characters of its own, so a legitimate ARN for a maximum-length secret has a 519-character resource and was refused. The resource is split before it is measured. The suffix check establishes **structure, not provenance**: a name ending in a hyphen and six alphanumerics is lexically identical to a generated suffix, and nothing can separate them |
| **Nothing is transformed** | the grammar answers a question about the identifier. It does not trim, normalise, rebuild, return or render it: a verdict about a normalised string is a verdict about a different string |
| **Counts are witnessed** | the synthetic suite drives the preflight with factories and a client that count what was asked of them, and every count above is read from those counters. A count argued from which line raised is the inference that produced a false report against the real foundation |
| **The classification is total** | `SECRET_FAILURE_OUTCOME` maps every `SecretRetrievalFailure` member to an outcome and a test asserts it. The two the boundary raises *before* it calls the backend map to the dependency and identifier outcomes, never to the credential |
| **Nothing leaks, still** | an import error names a path, a client constructor names a profile or a region, a backend exception quotes the secret name. Every refusal is a closed member raised `from None`, and canaries prove the dependency exception, the identifier and the backend message are absent from every refusal, both reprs, stdout and stderr |
| **The refusing default path** | needs neither the SDK nor the data platform. Every `kalpamani` import in the entry point sits inside a function body, so a machine with a broken environment still gets a clean refusal rather than a traceback — which is the class of machine this defect was found on |

**Two findings, and only one belongs in this repository.** The absent SDK is an operational-environment
drift finding, recorded as evidence; the declared `boto3>=1.36.0,<2.0` runtime dependency is unchanged
and was already correct. The mislabelling is the implementation defect, and it is what is corrected.
**The dependency was deliberately not installed *by this correction*** — installing it would have
made the symptom disappear and left the defect in place, on a path that only runs when something has
already gone wrong. That was the right order, and it has since been followed: a **separately
authorized environment action installed the AWS SDK afterwards**, and a later synchronization review
installed nothing. Both are recorded in *The operational environment* above; neither changes anything
this ADR decided.

**Nothing else moved.** Secret-identifier access, SDK construction and credential retrieval all still
sit behind the identity and bucket gates. The guarded secrets-boundary import runs before the
identifier source, which is why an import refusal shows zero identifier resolutions rather than one —
stated rather than rounded off. The singleton authorization capability, the operator flag, the
identifier staying out of `argv`, the fixed environment-variable name, the profile and region pins,
the governed identity gate and state read, the licensed-bucket output, `SystemClock` in the operator
path, `reveal()` at **zero** during preflight, offline composition only, no provider-fetch operation
and no object-publication operation are all unchanged. **G1 OPEN · G2 OPEN · G3 CLOSED · G4–G7 OPEN**,
ADR-0005 **PROPOSED**, INC-0002 **OPEN**, Phase 3 **NOT COMPLETE**, CONTROL **DEFERRED**, live
trading **HARD-DISABLED**.

### The operational environment — synchronized and verified, and not reproducibly locked

The local operational `.venv` exists and is usable, and the AWS SDK this repository has declared since
[ADR-0011](docs/decisions/ADR-0011-implement-the-licensed-s3-research-object-store.md) is **present and
locally verified**. That is a new fact: the second authorized binding-preflight attempt refused
precisely because this environment lacked it.

```
operational .venv                     EXISTS AND USABLE
interpreter                           Python 3.11.9
boto3                                 1.43.83   (declared range >=1.36.0,<2.0)
botocore                              1.43.83   (boto3 requires >=1.43.83,<1.44.0)
importable and mutually compatible    YES
pip check                             no broken requirements
boto3.client                          EXISTS AND CALLABLE -- not invoked during verification
synthetic/local validation suite      PASSED in full
Python dependency lock                ABSENT
conformance                           RANGE-CONFORMANT, NOT LOCK-CONFORMANT
one future bounded attempt            TECHNICALLY READY FOR SEPARATE AUTHORIZATION
```

**The chronology matters, and these are four different events.** Collapsing them is how a status
document starts asserting that an installation nobody authorized took place, or that a review did
work it deliberately did not do.

| | |
|---|---|
| **the historical refusal** | the second authorized binding-preflight attempt refused because this environment lacked the AWS SDK. That was true then, ADR-0016 records it, and it is not rewritten |
| **an earlier, separately authorized environment action** | installed the AWS SDK using the range already declared in `pyproject.toml`, resolving `boto3 1.43.83` and `botocore 1.43.83` with five transitive packages. It changed no repository file |
| **the latest environment-synchronization review** | **installed nothing.** Its authorization required a frozen/locked operation, and this repository has no Python dependency lock, so that path was not executable. It verified the already-populated environment and made **no change** |
| **now** | the environment is verified and usable — and **not reproducible from tracked metadata** |

**No Python dependency lock currently exists.** The installed environment is therefore
**range-conformant, not lock-conformant**: every version satisfies what `pyproject.toml` declares, and
nothing pins which version a rebuild would choose. A clean rebuild on another date could resolve
different, still-compatible package versions.

**Introducing a Python dependency lock is DEFERRED to a separately reviewed dependency-governance
slice.** No lock, manifest or dependency declaration is changed here, and the missing lock is
**not** resolved by recording it. For **one** future bounded binding-preflight diagnostic, the exact
validated fingerprint above may be treated as **provisionally acceptable**. That provisional
acceptance is **not** approval for production qualification, ingestion, CONTROL publication or live
operation.

**A usable environment is not a permission.** Everything the earlier slices established is unchanged,
and the boundaries below are restated rather than relaxed:

```
binding-preflight entry point         SOLE PERMITTED SDK/CLIENT-CONSTRUCTION BOUNDARY
real bucket binding: NONE
operational secret-identifier configuration: OWNER-CONFIGURED / NOT YET VERIFIED BY THE ENTRY POINT
authorized binding-preflight attempts to date: FOUR -- all refused
Secrets Manager client constructions: ZERO   ·   get_secret_value invocations: ZERO
Secrets Manager network requests: ZERO   ·   S3 object operations: ZERO
Sharadar/provider requests: ZERO   ·   credential retrieved: NONE   ·   qualification runs: ZERO
AWS credential-provider chain invoked during environment verification: NONE
AWS requests during environment verification: ZERO
binding preflight or composition preflight run during environment verification: NEITHER
composition preflight run: NEVER
a fifth binding-preflight attempt: NOT AUTHORIZED
further AWS authentication diagnosis: NOT AUTHORIZED
AWS SSO refresh/login: SEPARATELY GATED / NOT AUTHORIZED
credential access: NOT AUTHORIZED   ·   authenticated qualification: NOT AUTHORIZED
further dependency installation or environment resynchronization: SEPARATELY GATED
```

Environment verification imported `boto3` and `botocore` with socket constructors replaced by raising
stubs and `builtins.open` recording every path opened: **no socket was created, no file under an
`.aws` directory was opened, `boto3.DEFAULT_SESSION` stayed `None`**, and `boto3.client` was checked
for existence by attribute lookup and never called. No environment-variable value, AWS profile, SSO
cache, credential, account identifier, bucket value or secret identifier was read.

**TECHNICALLY READY FOR SEPARATE AUTHORIZATION** — and that is a statement about the machine, not a
permission. **G1 OPEN · G2 OPEN · G3 CLOSED · G4–G7 OPEN**, ADR-0005 **PROPOSED**, INC-0002 **OPEN**,
Phase 3 **NOT COMPLETE**, CONTROL publication **DEFERRED**, live trading **HARD-DISABLED**.

### The Sharadar private-binding preflight — refused by default, and four times refused in operation

[ADR-0015](docs/decisions/ADR-0015-implement-the-dormant-sharadar-private-binding-preflight.md) authorized the last piece nobody had written: the path that will eventually
supply the private bindings every accepted slice takes by injection. One operator entry point,
`scripts/sharadar_binding_preflight.py`, and one boundary module,
`data/ingest/sharadar/secrets.py`.

**Status: ACCEPTED / IN FORCE — PR #22 merged.** **Merging it bound nothing** — but the entry
point has since been run. Four separately authorized operator attempts occurred and **all four
refused** — one at the AWS identity gate, one on a missing AWS SDK dependency, one at the fixed
secret-identifier source, and — after the owner's secret creation and identifier configuration —
one again at the AWS identity gate with **`REFUSED_IDENTITY`**. No credential was retrieved, no
bucket was bound, no provider was accessed and no qualification or ingestion occurred.

```
entry points          ONE      scripts/ only; the installed package re-exports nothing
default behaviour     REFUSE   no flag, no work -- no lookup, no client, no socket, no read
authorization         ONE      --i-am-the-operator-authorizing-binding-preflight
what it authorizes    BINDING PREFLIGHT ONLY -- never a qualification run
authorized attempts   FOUR     all refused; none reached a Secrets Manager client
third attempt         REFUSED_SECRET_IDENTIFIER at the fixed secret-identifier source
fourth attempt        REFUSED_IDENTITY at the AWS identity gate
AWS identity-gate activity: OCCURRED -- total AWS activity was not zero
identity-gate invocations on the fourth attempt: ONE -- the gate runs its own STS identity operation
standalone diagnostic commands during the fourth attempt: ZERO
AWS network requests on the fourth attempt: UNKNOWN -- no numeric count is established
post-fourth AWS identity diagnosis: COMPLETED -- REFUSED_SSO_SESSION_MISSING_OR_EXPIRED
diagnosis process invocations: ONE   ·   STS command invocations: ONE   ·   exit code: 255
diagnosis underlying AWS network requests: UNKNOWN
missing vs expired: NOT DISTINGUISHED by the diagnosis
governed profile: PINNED IN THE CHILD ENVIRONMENT, NEVER DISCLOSED
SSO-login invocations: ZERO   ·   authentication-repair actions: ZERO
fifth binding-preflight attempts: ZERO
operational secret-identifier configuration: OWNER-CONFIGURED / NOT YET VERIFIED BY THE ENTRY POINT
owner credential setup occurred AFTER the third attempt and BEFORE the fourth
identifier-source resolutions on the third attempt: ONE
identifier-source resolutions on the fourth attempt: ZERO
licensed-bucket resolutions on the fourth attempt: ZERO
KALPAMANI_SHARADAR_SECRET_ID read by the fourth attempt: NO
Secrets Manager client constructions: ZERO
get_secret_value invocations: ZERO
Secrets Manager network requests: ZERO
S3 client constructions: ZERO   ·   S3 object operations: ZERO
provider transport constructions: ZERO   ·   Sharadar/provider requests: ZERO
offline composition-preflight invocations: ZERO
credential retrieval: NONE   ·   qualification runs: ZERO
owner-side Secrets Manager secret creation: ATTESTED / NOT VERIFIED BY THE ENTRY POINT
Secrets Manager secret reads by this repository: ZERO
real bucket binding performed: NONE
qualification-run execution surface: NONE
provider-fetch operation: NONE   ·   object-publication operation: NONE
runner, task, image, scheduler or service: NONE
fifth binding-preflight attempt: NOT AUTHORIZED
further AWS authentication diagnosis: NOT AUTHORIZED
AWS SSO refresh/login: SEPARATELY GATED / NOT AUTHORIZED
further environment resynchronization: SEPARATELY GATED / NOT AUTHORIZED
authenticated qualification: NOT AUTHORIZED
```

**Implementing and merging it executed nothing. Four later, separately authorized operator
attempts did.** Those are different facts, and this section keeps them apart — an earlier revision
recorded only the first, which was true of the merge and false of the operation.

| | |
|---|---|
| **at implementation and merge** | no attempt was made; code and synthetic validation only |
| **first authorized attempt** | reached the AWS identity gate and **refused there** |
| **separately authorized diagnosis** | one `sts:GetCallerIdentity` request, which classified the session as missing or expired |
| **after an AWS SSO login** | the second authorized attempt passed the identity gate and licensed-bucket resolution |
| **second authorized attempt** | **refused before constructing a Secrets Manager client**, because the project environment lacked the required AWS SDK dependency |
| **a later, separately authorized environment action** | installed and verified the AWS SDK. It changed no repository file — see the environment section |
| **third authorized attempt** | one process invocation. Passed operator authorization, the governed profile contract, the identity gate and licensed-bucket resolution, **reached the fixed secret-identifier source exactly once**, and refused there with **`REFUSED_SECRET_IDENTIFIER`** — public output `binding preflight refused: no usable secret identifier was resolved`, exit code 1 |
| **owner credential setup, after the third attempt** | the owner attests that an AWS Secrets Manager secret was created for the existing Sharadar API key and that `KALPAMANI_SHARADAR_SECRET_ID` was configured. **OWNER-CONFIGURED / NOT YET VERIFIED BY THE ENTRY POINT** |
| **fourth authorized attempt**, after that setup | one process invocation, from a fresh post-restart process. Passed operator authorization and the governed profile contract, **invoked the application AWS identity gate once**, and refused there with **`REFUSED_IDENTITY`** — public output `binding preflight refused: the AWS identity gate did not pass`, exit code 1. It **never reached licensed-bucket resolution and never reached the secret-identifier source**, so it did not read `KALPAMANI_SHARADAR_SECRET_ID`, constructed no AWS service client and retrieved no credential. **No retry and no standalone authentication diagnosis followed** |
| **a second, separately authorized diagnosis**, after the fourth attempt and after PR #28 merged | **one** process invocation of **one** `aws sts get-caller-identity` command, exit code **255**, closed outcome **`REFUSED_SSO_SESSION_MISSING_OR_EXPIRED`** — the governed SSO session or cached token was classified unavailable or expired, and the classification **does not distinguish missing from expired**. The governed profile was pinned in the child environment and never disclosed; no identity, raw output or error text was disclosed or persisted. Its **own** underlying AWS network-request count is **UNKNOWN**. **No retry, no `aws sso login`, no authentication repair, no identity-gate invocation and no fifth attempt followed** |

**AWS identity-gate activity occurred, so total AWS activity was not zero.** What stayed at zero is
narrower and is stated in scope: Secrets Manager client constructions, `get_secret_value`
invocations and Secrets Manager network requests; S3 object operations; Sharadar and provider
requests; S3 client constructions and provider transport constructions. No attempt reached
composition validation, and **no credential was retrieved or revealed**.

**Whether the fourth attempt sent an AWS network request is UNKNOWN**, and this document does not
guess. The identity gate was invoked once and did not pass; a gate can fail before anything leaves
the machine, so neither zero nor one network request may be claimed.

**No standalone diagnosis was performed as part of attempt 4** — and that is narrower than an
earlier revision of this section claimed. **Its governed identity gate invoked its own STS
identity operation once**: `identity_gate()` in `scripts/aws_foundation_verify.py` runs
`sts get-caller-identity` itself, so it is false to say the attempt made no STS identity call.
What it did **not** do is run an *additional* diagnostic command or any SSO inspection, and no
authentication repair occurred during it. So nothing the attempt did **beyond its own gate**
establishes why that gate refused — and the gate's internal operation is **not** the later
standalone diagnosis, which was a separate command run under its own authorization.

**A separately authorized diagnosis has since answered that. It is an additional standalone
command — neither the gate's own STS operation above, nor the diagnosis that followed the first
attempt.** Run after the fourth attempt and after PR #28 merged, it
invoked **one** process and **one** `aws sts get-caller-identity` command, which exited **255** and
classified as **`REFUSED_SSO_SESSION_MISSING_OR_EXPIRED`** — the governed SSO session or cached
token was unavailable or expired. **It does not distinguish missing from expired**, and nothing
here guesses which. This is the **first direct diagnostic evidence explaining the fourth attempt's
identity refusal**, and it revises no count: the attempt's own network-request total stays
**UNKNOWN**, and so does the diagnosis command's, because a CLI call may resolve credentials
locally and fail before anything leaves the machine. **SSO-login invocations ZERO**,
**authentication-repair actions ZERO**, **fifth binding-preflight attempts ZERO**. Further AWS
authentication diagnosis is **NOT AUTHORIZED**, and an AWS SSO refresh or login is **SEPARATELY
GATED / NOT AUTHORIZED**.

**The diagnosis pinned the governed profile itself, and that was a correction rather than a
deviation.** A shell-level `AWS_PROFILE` pin does not persist across separate tool invocations, so
the command could not rely on inheriting one; an unpinned CLI call would have fallen back to an
unrelated default profile, which is the wrong-account hazard §4.24 exists to prevent. The child
process was therefore pinned to the repository's governed profile, whose value was obtained by
**statically parsing the repository-owned `EXPECTED_PROFILE` constant** — the entry-point module was
neither imported nor executed. **That constant already existed in tracked executable source**, so
the supportable claim is about what the **diagnosis** did rather than about the repository: it
**did not print, log, disclose or newly write it**, added it to no document, comment, output or
new file, and left the parent environment unmodified. This is the governed profile, not an alternate
one.

**`KALPAMANI_SHARADAR_SECRET_ID` is now OWNER-CONFIGURED / NOT YET VERIFIED BY THE ENTRY
POINT.** It was **UNKNOWN at the time of the second attempt**, which refused on the
dependency path without reading it — and ADR-0016 exists
because that refusal was reported as a credential failure, which is what made the two
indistinguishable. It was **still UNKNOWN at the time of the third attempt**, which resolved the
fixed source exactly once and refused with `REFUSED_SECRET_IDENTIFIER` because no usable identifier
came back. **The owner created the secret and configured the variable only after the third
attempt**, so none of the first three could have seen it — and the **fourth attempt refused at
the AWS identity gate, two stages before the identifier source**, so it did not read the variable
either. **No attempt has resolved the identifier.**

**Owner-attested is not entry-point verified.** None of the following is established, and none may
be claimed: inheritance of the variable by the existing Claude Code process; resolution of the
identifier by the entry point; that the identifier points to the intended secret; AWS verification
of the secret through this repository; inspection of the payload format or value; construction of a
Secrets Manager client; invocation of `get_secret_value`; retrieval of the credential; or
compatibility of the credential with Sharadar. **Credential access by the application
remains NOT AUTHORIZED**, and so do a fifth binding-preflight attempt, any **further** AWS
authentication diagnosis, and an AWS SSO refresh or login.

**A real binding preflight is no longer a purely future event.** Four occurred. What remains
future, and separately authorized: a fifth attempt, **further** AWS authentication
diagnosis, an AWS SSO refresh or login, further environment resynchronization, application
credential access, and an authenticated Sharadar qualification run. **Authenticated qualification remains NOT AUTHORIZED and
has never run.**

| | |
|---|---|
| **Refused by default** | an ordinary import or invocation performs no environment lookup, no credential lookup, no SDK construction, no state read, no bucket resolution, no socket and no provider or object-store call. The real factories import what they need *inside their own bodies*, so importing the module pulls in no SDK, no verifier and no `os` |
| **One unmistakable flag** | `--run`, `--live`, `--execute` and `--force` are each **refused by name**, with a reason, so a wrong reflex fails loudly |
| **One object, admitted by identity** | two revisions got this wrong. The first took `binding_authorized: bool`, so any importer could pass `True`. The second took an object of an exact type carrying a module-private *mint field* — and **a field is copyable**: `copy.copy` returned a distinct object holding the same field, and admission accepted it, so copying manufactured a second bearer. Review caught the closeout claiming both "copying cannot forge one" and "a shallow copy stays genuine", which cannot both be true |
| **Nothing to copy, and no route to a second** | admission is now identity against **one** module-level object. `__slots__` is empty; `__new__` refuses once the singleton exists; `__copy__`, `__deepcopy__` and `__reduce__` each refuse, so copying and pickling yield **no object at all**; subclassing refuses. An `object.__new__` instance can still be built and is refused for the reason that matters — it is not *this* object. Unexported, handed over at one place. **Not a claim about hostile runtime introspection** — a process that can reach the module's private names already holds the singleton |
| **The secret identifier never enters argv** | `--secret-id` put a private identifier in shell history and every process listing, whether or not the program printed it. It now comes from an **injected zero-argument source**, called once, after every gate has passed and immediately before the credential. The production source reads one fixed, non-secret variable **name**, `KALPAMANI_SHARADAR_SECRET_ID`; six command-line spellings are refused by name. The default path and every earlier refusal read **no credential-bearing variable** — `argparse` reads locale and terminal-width variables of its own, which is why the claim is scoped rather than "zero lookups" |
| **Order is the security property** | authorization → profile → identity gate → licensed bucket → secret identifier → secrets client → one credential retrieval → dependencies → offline preflight → closed result. No later stage runs after an earlier refusal, so **a wrong-account session never reaches a secret and a failed gate never reaches a credential**. Proven by counting which stages ran. The identifier, the client and the retrieval were **one stage with one outcome** in this slice as merged, which is the defect [ADR-0016](docs/decisions/ADR-0016-correct-private-binding-preflight-failure-boundaries.md) corrects; nothing moved earlier |
| **No gate is reimplemented** | `AWS_PROFILE` pinning, account matching and the state read come from the existing governed verifier. The entry point contains no `sts` call, no `get-caller-identity`, no `allowed_account_ids` parse and no `terraform` invocation of its own |
| **Licensed, never CONTROL** | one named Terraform output. The control bucket has a different key, and the entry point never names it — nor the word `CONTROL` |
| **One secrets operation** | `get_secret_value`, injected. No listing, describing, writing, rotating or deleting exists in the shape. **`SecretString` only** — binary is refused rather than decoded — with no JSON parsing, key guessing, alias, default or fallback |
| **Straight into the credential** | the value is handed immediately to `SharadarCredential`, never logged, returned or included in a refusal. `reveal()` is called **zero** times during preflight |
| **Fail closed, say nothing** | every refusal is a closed member raised `from None`; a backend exception quotes the secret name, usually the ARN and often the account |
| **Offline composition only** | it calls `preflight_qualification_composition` and nothing else. No `execute`, no transport `get`, no `put_object`, no `head_object`, no publication helper |
| **Output is allowlisted** | a fixed set of sentences through one function that takes a vocabulary member, not a string. No credential, secret identifier, bucket, account, ARN, profile, region, Terraform output, URL, subject or empirical result. `READY`, `APPROVED`, `AUTHORIZED`, `PROCEED`, `QUALIFIED` and `BOUND` are refused anywhere in it |
| **Exit status** | command success or refusal only — never a qualification verdict, never provider suitability |
| **Five leak canaries** | a key, a secret identifier, a bucket, an account and a backend message, each proven absent from every stage's refusal, the result, both reprs, stdout and stderr |

**The SDK stays out of the platform.** `boto3` remains the only runtime dependency and **no module
under `src/` imports it**. The one authorized construction lives in the script, inside the authorized
branch — so importing the data platform still opens no socket and performs no ambient credential
discovery.

**Three standing claims are narrowed, not deleted.** *"Nothing constructs an SDK client"*, *"no
credential source exists"* and *"nothing calls the composition preflight"* were each true while no
binding path was authorized. What holds now: **exactly one module may construct an SDK client,
exactly one may call the composition, the credential source refuses by default, and none of it has
ever been run.** Each clause is a test, and the existing dormancy guards were narrowed rather than
removed.

**Nothing accepted changed.** `AcquisitionMode.QUALIFICATION` · `PROVIDER_REALISTIC_PIT` · Q7 and Q8
· `permaticker` · append-only S3 semantics · acquisition identity · the response and run ceilings ·
no-resume semantics · three-write reporting · CONTROL deferral · provider-neutral contracts · every
production-ingestion boundary. **G1 OPEN · G2 OPEN · G3 CLOSED · G4–G7 OPEN**, ADR-0005
**PROPOSED**, INC-0002 **OPEN**, Phase 3 **NOT COMPLETE**, CONTROL **DEFERRED**, live trading
**HARD-DISABLED**.

### The Sharadar qualification composition root — dormant, and the offline preflight

[ADR-0014](docs/decisions/ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md)
authorized the wiring the five previous slices deliberately did without: one module that receives
every dependency explicitly and builds the accepted client, licensed store and qualification runtime
from them. `data/ingest/sharadar/composition.py`, and no second module — **one function**,
`preflight_qualification_composition`, and no stateful object.

**This supersedes the standing "composition root: NONE" claim, and nothing else.** That claim was
true of every earlier slice and is quoted in their historical text, which is not rewritten. What
holds now is narrower and is checked rather than declared:

```
composition           ONE function, and no stateful object
exposed operation     offline preflight -- plan validation, and only that
components            LOCALS, built inside one call, not returned and not retained
qualification-run execution surface: NONE
provider-fetch operation: NONE   ·   object-publication operation: NONE
runner                NONE     no CLI, no entry point, no console script, no task, no image
retained state        NONE     no module global, no closure, no instance, no attribute
caller-owned arguments          the caller's, before and after -- unchanged by this
credential retrieval  NONE     in this module; the operator entry point is the only
                               place a credential source exists, and it refuses by default
real credential binding: NONE   ·   real bucket binding: NONE
AWS SDK session / S3-client construction: NONE in src/; no module under src/ imports the SDK
called or imported outside its own synthetic tests and the ADR-0015 operator entry point: NEVER
Sharadar requests: ZERO   ·   AWS requests: ZERO   ·   Services Data: NONE
```

**Two things that block reads exactly, and are worth stating rather than rounding off.** *Offline
preflight is work* — it validates a plan — so "no way to run anything" would be false; what is
absent is a **qualification-run** execution surface, a provider fetch and an object publication.
And the **caller keeps ownership of every argument it passes in**: its credential, transport, S3
client, bucket string, clock and plan are its own objects both before and after. The guarantee here
is about what *this function and its result* retain, not about object lifetimes, and it is not
asserted on an exception path where a traceback may hold a frame.

**The first revision of this slice was a stateful object, and its dormancy claim was false.** It
held `_client`, `_store` and `_runtime`, so `composition._runtime.execute(plan)` ran, and its own
tests reached those attributes to prove the components had been built. **A leading underscore is a
naming convention, not an execution barrier.** The replacement is a module-level function: there is
no `self` to attach a runtime to and no instance for a caller to hold, so *no executable component
escapes* is a property of the shape rather than a rule someone must remember.

**Precisely what the absences mean.** A `SharadarClient`, an `S3ResearchObjectStore` and a
`QualificationRuntime` **are** constructed — as local variables, inside one call, from values a
caller hands in — and a synthetic bucket string and synthetic store are constructed in tests. What
does **not** exist is a *real* bucket binding, a *real* credential binding, any **AWS SDK session or
S3-client construction**, and any credential source. The credential is handed to a client that lives
for one call; it stays the caller's object, and neither the function nor the result retains it.

**It constructs from injected values only.** A credential, a transport, a pacer, a retry policy, a
timeout, an S3 client, a licensed-bucket string and a clock — each a **required keyword parameter
with no default**, so nothing here can reach a real service because a caller forgot one. Validation
is delegated to the constructor that owns each rule rather than copied. The one addition is that
`pacer` is required and exactly typed: `SharadarClient` accepts `None` and builds one from
`time.monotonic` and `time.sleep`, which is the right default for a client and the wrong one for a
composition root.

**`preflight(plan)` calls `QualificationRuntime.validate` and nothing else.** That checks the plan's
own rules, the retry budget against the *injected client's* attempt policy, the request count, the
distinctness of every derived acquisition identity, both byte ceilings against what the client could
actually return, and the clock — issuing **no provider request and no store call**. A composition
holding real dependencies is still inert while only this method exists.

| | |
|---|---|
| **The result is closed** | frozen, slotted, subclass-refusing: a status, five bounded counts, the acquisition mode and the profile. **No credential, bucket, URL, region, account, subject, payload, backend-message or free-text field** — none has anywhere to be, and `__post_init__` enforces that rather than the annotations |
| **The result must be possible** | every count is bounded by the *same compiled constants* the plan and the client are held to, and the two cross-field rules the runtime applies — response ceiling ≤ run ceiling, and `requests × (attempts − 1) ≤ retry budget` — are re-checked. An earlier revision accepted zero for every count while still reporting `VALIDATED_OFFLINE`; no plan produces those numbers |
| **The transport contract is enforced where it is owned** | `SharadarClient` now requires a callable `get`, so an object carrying only a plausible `max_response_bytes` can no longer compose and validate cleanly while being unable to perform a request. The response ceiling is **resolved once at construction** and stored: a bound read from a mutable dependency on every access is not a bound |
| **The numbers are derived** | request count from the plan's generator, attempt ceiling from the injected client's retry policy, response ceiling from the stricter of client and plan. A preflight reporting declared intentions would describe a different run |
| **The status word is a control** | one member, **`VALIDATED_OFFLINE`**. `READY`, `PROCEED`, `APPROVED`, `QUALIFIED` and `AUTHORIZED` are each refused anywhere in the module. **Preflight is not a verdict**: it says a plan is internally consistent, and nothing about the provider, the data, or whether a run should happen |
| **One member, on purpose** | a *failure* status that can be returned is a failure a caller can ignore. Every refusal raises, in an existing closed vocabulary |
| **Nothing leaks** | a secret-shaped, bucket-shaped, backend-message-shaped and subject-shaped canary, each proven absent from the result, its fields, both reprs, every refusal and captured output |
| **Zero activity, counted** | the transport and the S3 client raise if called, and their call counts are asserted at zero through a real `S3ResearchObjectStore`. `reveal()` is counted by patching the credential class |
| **`QUALIFICATION` is fixed, once** | `QUALIFICATION_ACQUISITION_MODE` is defined in `qualification.py` and imported by both the runtime and the preflight result — **one statement, not two that could drift**. No mode parameter on the composition, on preflight, on the plan or on the limits ([ADR-0013](docs/decisions/ADR-0013-introduce-acquisition-mode-and-retire-is-backfill.md)) |

**The first authenticated qualification run remains separately gated, and this slice does not
approach it.** What would still be needed: an authorization, a credential source, a real credential,
a constructed **AWS SDK** client, a real bucket binding, and code that calls something other than
`preflight_qualification_composition`. **None of those exists.**

**The architecture guards were narrowed, not deleted.** Exactly one module may construct the
licensed store, the client and the runtime; a second one fails. **SDK construction stays forbidden
everywhere, the composition root included** — the S3 client is injected there too, so importing the
data platform still pulls in no AWS code and performs no ambient credential discovery.

**Merging this selects no provider.** **G1 OPEN · G2 OPEN · G3 CLOSED · G4–G7 OPEN**, ADR-0005
**PROPOSED**, INC-0002 **OPEN**, Phase 3 **NOT COMPLETE**, CONTROL publication **DEFERRED**, live
trading **HARD-DISABLED**.

### The Sharadar qualification runtime core — dormant, and what that means exactly

[ADR-0012](docs/decisions/ADR-0012-implement-the-dormant-sharadar-qualification-runtime-core.md)
authorized the piece that joins the five existing slices: a **bounded qualification plan** and an
**executor that acts only on dependencies a caller hands it**. Two modules,
`data/ingest/sharadar/qualification.py` and `data/ingest/sharadar/runtime.py`, and no third.

**This narrowed one standing claim, and the narrower one is what now holds.** Until this slice,
nothing in this repository called the object store. That is no longer true — the runtime calls it,
through the neutral Bronze bridge, with an **injected** store. What is still true, and checkable:

```
plan model EXISTS   ·   executor EXISTS   ·   dependencies INJECTED
credential source: the ADR-0015 operator entry point ONLY, refused by default
SDK client construction: that entry point ONLY   ·   real bucket binding: NONE, never performed
runner: NONE   ·   module entry point in either module: NONE
constructed only by the dormant composition root (ADR-0014) and its own tests
Sharadar requests sent: ZERO   ·   AWS requests sent: ZERO
```

That claim once ended *"and no composition root exists"*.
[ADR-0014](docs/decisions/ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md)
built one, so the accurate statement is narrower: a dormant composition root constructs this runtime
from injected values and exposes **offline preflight only**. What still stands between it and a live
run is a separately gated authorization plus the real private bindings — a credential source, a
constructed SDK client, a bound bucket — and code that calls something other than `preflight`.
**Each of those is a separate decision, and none exists.**

**Seven ceilings, compiled in, lowerable and never raisable:** 8 subjects · 3 datasets · 4 pages per
request · 96 requests · the transport's own per-response byte ceiling · 512 MiB per run · 32
retries, checked against the *injected client's own attempt policy* so the budget bounds what will
happen rather than describing an intention. A limit above its constant is **refused**, not clamped:
clamping would let a plan claim a budget it does not have and then behave differently from what it
says.

| | |
|---|---|
| **Three datasets** | `tickers`, `stocks`, `actions`. `fundamentals`, `daily`, the `SF*` tables, events, metrics, holdings and funds are refused **by name** — real vendor tables owned by a later phase. Everything else is refused as unknown |
| **No default subject** | every request names an explicitly supplied one, and **no real ticker is compiled into the module** |
| **No implicit window** | required on a windowed dataset, forbidden on the snapshot one. The vendor defaults `from` to a year ago and `to` to the prior day (`PSR-SHD-121`) |
| **No bulk route** | `years`, `fields`, `sort`, `columns`, `order` and `lastupdated` are refused a step before the request builder would refuse them |
| **One canonical order** | dataset, then subject, then page offset — independent of input order, so two plans holding the same content derive the same acquisition identities and reconcile with the same durable evidence |
| **One request, one acquisition** | each request derives its own identity from the execution, provider, dataset, subject, range, format and both page values — so byte-identical responses from two datasets, two subjects or two pages are three retrievals, not a collision and not a collapse |
| **Validation is complete and first** | a partly-wrong plan is refused whole; a refused plan issues **zero** provider and **zero** store calls |
| **Failures report, not raise** | published objects are immutable and have no rollback, so a halted run returns the outcomes that completed and states `partial` rather than leaving it to arithmetic |
| **Three writes, three dispositions** | a publication appends a claim, a payload and an acquisition record. All three are reported separately, because *the payload was already there* and *this acquisition was already recorded* are different facts |
| **No resume** | re-running a halted execution is **not** a resume: a second execution reads a new instant, so the acquisition record differs and the store refuses it. Review the halt and refetch under a **new explicit execution id**. Durable checkpointing is deferred |
| **Unknown durable state** | a publication that raises may have committed some of its three appends, and an ambiguous backend failure may not prove whether any committed. The result carries `publication_state_unknown` and **claims to know nothing more** |
| **Run-byte ceiling** | bounds **successful provider payload bytes handed to the runtime**, counted the moment they arrive and before publication — not HTTP framing, failed-response bodies or wire traffic, none of which the client exposes. Enforced as *headroom* before each request, so the run never asks for an answer it cannot afford |
| **Result integrity** | a result must describe one valid execution: unique acquisition identities, unique request coordinates, every counter and both byte totals re-derived from the outcomes, and `HALTED` requiring strictly fewer completed than planned |
| **Acquisition mode** | the runtime records `AcquisitionMode.QUALIFICATION` — a bounded provider-validation retrieval, with its own name rather than a borrowed one ([ADR-0013](docs/decisions/ADR-0013-introduce-acquisition-mode-and-retire-is-backfill.md)). Fixed, with no plan field and no caller override. The mode is **declared, never inferred** from counts, ranges, payloads or prior coverage, and it **proves nothing on its own** about PIT availability or row chronology |
| **Nothing leaks** | every failure is one closed `StrEnum` member, raised `from None`. A response body, a URL carrying the key, a bucket name and a backend error string have no parameter to arrive through |
| **PIT is in the type** | `PROVIDER_REALISTIC_PIT` is the only admitted profile; `PUBLIC_PIT` is refused and is not named in the runtime at all |
| **`permaticker` is untouched** | never named, never derived from. Payloads are opaque bytes and are never parsed |

**An offline plan-check command exists and cannot run a plan.**
[`scripts/sharadar_plan_check.py`](scripts/sharadar_plan_check.py) validates a plan and prints a
fixed-schema summary. It imports no client, no transport, no store and no executor, so the absence
of an execution mode is **structural rather than a policy**; `--execute`, `--live`, `--api-key`,
`--secret`, `--bucket`, `--aws-profile`, `--endpoint` and `--token` are refused by name. No subject
symbol is printed. It is **not** the private qualification harness, which is untouched, unimported
and still unauthorized to execute.

**Q7, Q8 and `permaticker` are unchanged and unresolved by this slice**, and **G1 and G2 stay
OPEN**, ADR-0005 stays **PROPOSED**, INC-0002 stays **OPEN**, and Phase 3 stays **NOT COMPLETE**.

---

## Governance

Authority order: **Blueprint V3.0 → approved ADRs → CLAUDE.md → approved task spec →
implementation judgment.** Architectural deviations require an approved ADR. See
[CLAUDE.md](CLAUDE.md) for the binding rules.

Blueprint V2.1 remains historical architecture evidence and is not deleted, but it is no
longer in the authority order. **Neither Blueprint PDF is ever edited** — corrections are
recorded in an ADR and indexed beside the document.

**License:** Proprietary. All rights reserved.
