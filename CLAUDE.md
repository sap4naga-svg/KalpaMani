# CLAUDE.md — KalpaMani Operating Rules

This file governs **all** work in this repository, in every session. Read it before
making any change. It is binding on humans and AI assistants alike.

---

## 1. Project mission

KalpaMani is an autonomous long/short **U.S. equity swing & momentum trading system**.
It trades liquid U.S. common stocks over a primary **2–30 trading-day horizon**, using
deterministic discovery, ranking, risk and execution, with AI confined to qualitative
information processing and thesis challenge.

**Locked principle (Blueprint V2.1 §1):**

> AI may improve information processing. Mathematics and deterministic software control
> money, risk and broker actions.

---

## 2. Authority order

When instructions conflict, the higher-numbered authority wins:

1. **Blueprint V2.1** — `docs/architecture/KalpaMani_Blueprint_V2_1.pdf`
2. **Approved Architecture Decision Records** — `docs/decisions/`
3. **This CLAUDE.md**
4. **The approved task specification** for the current session
5. **Implementation judgment**

If a lower-level instruction appears to conflict with Blueprint V2.1, **do not silently
redesign the system.** Stop, report the conflict, and propose the change as an ADR.
Architectural deviations require an approved ADR before implementation.

---

## 3. GitHub account isolation — MANDATORY

```
AUTHORIZED GITHUB OWNER:  sap4naga-svg
EXPECTED REMOTE:          sap4naga-svg/KalpaMani
VISIBILITY:               PUBLIC  (development only -- see below)
DEFAULT BRANCH:           main
```

### Visibility — PUBLIC during development

**Current visibility: PUBLIC.** Purpose: direct code review and collaboration while the
system is being built. This is a deliberate, owner-authorised state, not a default.

**Owner-accepted residual risk.** An account-binding digest was committed while the
repository was public and later removed by rewriting branch history. A rewrite does not
delete anything from GitHub: the pre-rewrite objects remain retrievable **by exact SHA**, and
pull-request description edit history retains an earlier revision containing the same value.
The GitHub Support purge has **not** been performed and is optional for now. The owner has
reviewed this and accepted the residual privacy exposure for the development period.

Public visibility is **not** a claim that the exposure was remediated. See
[INC-0002](docs/incidents/INC-0002-account-binding-digest-exposure.md), which stays **OPEN**.

### Never commit — public or private

The list below is unchanged by visibility, and public visibility makes it unforgiving: a
mistake is immediately world-readable and cannot be recalled.

> brokerage account identifiers · account-binding digests · broker-native order ids
> (BrokerIds) · IBKR or LEAN vendor logs containing identifiers · credentials · API tokens ·
> passwords · 2FA or passkey material · `.env` files · anything under `.runtime/` ·
> brokerage configuration

`.runtime/` is git-ignored and holds every sensitive operational artifact. It stays that way.

### MANDATORY return to PRIVATE

The repository **must** be private again before any of:

- micro-live operation of any size;
- real-money trading;
- production broker credentials or configuration existing anywhere in the workflow;
- earlier, if proprietary strategy logic warrants it.

Returning to private is a governed change: flip the visibility **and** this section together,
so policy and reality never disagree. Resuming the Support purge remains available and is
recommended before any real-money phase.

KalpaMani is **exclusively** owned by the GitHub account `sap4naga-svg`. It must never be
created, pushed, forked or configured under any other account or organization — in
particular not under the account used for car-wash software.

**Before any repository creation, remote change or push, every session MUST:**

1. Run `gh auth status` and determine the **active** account.
2. Verify it is exactly `sap4naga-svg`.
3. Run `git remote -v` and verify `origin` points to `sap4naga-svg/KalpaMani`.
4. **If either check fails: STOP.** Do not create a repository. Do not push. Report that
   GitHub CLI authentication must be switched to `sap4naga-svg`.

Never print OAuth tokens, PATs, passwords or credential contents. Never ask the operator
to paste a GitHub password, PAT, token or OAuth secret into an AI chat session.

Do **not** modify global Git identity. If KalpaMani needs a distinct identity, set it with
`git config --local` only.

---

## 4. Non-negotiable system safety rules

1. **Live trading is HARD-DISABLED** until an explicitly approved future deployment phase.
2. The initial brokerage environment is **IBKR PAPER ONLY**.
3. **Never connect to the IBKR live account** during bootstrap or initial development.
4. **Never request, print, store, log or commit** brokerage passwords, 2FA secrets, GitHub
   tokens, QuantConnect API tokens, data-provider API keys, private keys, session secrets
   or any other credential.
5. Secrets come from **environment variables or an external secrets manager** — never from
   source, never from a committed file.
6. `.env` and all real credential files are **git-ignored**. Only `.env.example`
   (variable names and placeholders) is committed.
7. **AI/LLMs MAY:** extract qualitative evidence; research approved candidates; summarize
   filings and news; challenge trade theses; generate structured research evidence.
8. **AI/LLMs MAY NOT:** choose dollar position size; override risk rules; bypass portfolio
   limits; bypass broker controls; arbitrarily submit trades; disable safety systems.
9. **Deterministic software controls:** candidate gating; quantitative ranking; portfolio
   allocation constraints; position sizing; risk; borrow validation; order approval;
   execution; stops; pyramiding rules; reconciliation; circuit breakers.
10. **No averaging down.** Ever.
11. **Pyramiding** is allowed only into confirmed winning trades under deterministic rules.
12. **Initial leverage = NONE.**
13. V1 trades **liquid U.S. common stocks**, long and short.
14. **Automated options trading is NOT V1**, even if IBKR grants options permission.
15. **Social/X signals are NOT V1.**
16. Broker-specific logic must live behind a **`BrokerAdapter`** abstraction.
17. **Market-data/provider code must remain separate** from brokerage execution.
18. **Duplicate-order prevention and idempotency are mandatory** before any automated
    order testing (deterministic client/order IDs).
19. Broker, market-data, database or AI failures must **fail safely** (fail closed).
20. **Humans govern:** models; capital scaling; parameter releases; exceptions;
    broker-required authentication/session maintenance; the kill switch. Humans should
    **not** routinely approve individual trades in mature production.

---

## 5. Environment restrictions

Three environments are distinguished from day one:

| Environment | Brokerage | Orders | Status |
|---|---|---|---|
| `RESEARCH` | none | none | **Default.** Backtests and offline analysis only. |
| `PAPER` | IBKR Paper only | only after a separately approved phase | Development and forward validation. |
| `LIVE` | IBKR live | **HARD DISABLED** | Requires approved phase + second gate. |

**Live trading must never be reachable by setting a single value.**
`environment = "live"` is *not* sufficient and never will be. Live execution requires
**two independent gates**:

- **Gate 1** — `Environment.LIVE` is selected.
- **Gate 2** — a separate, out-of-band authorization mechanism (deliberately **not
  implemented**).

`LIVE_TRADING_HARD_DISABLED = True` in `src/kalpamani/common/settings.py` short-circuits
both. Any attempt to enable or perform live execution **fails closed** with
`LiveTradingDisabledError`. Clearing that flag is a governed change requiring an approved
ADR, a working Gate-2 mechanism, and written human sign-off.

---

## 6. The $80K strategy-capital rule — CRITICAL

```
Broker account equity            (observed; informational only)
        |
        v
KalpaMani allocated strategy capital   (AUTHORITATIVE — USD 80,000)
        |
        v
Strategy risk budgets
```

**KalpaMani strategy capital is separate from broker-reported account equity.**

The IBKR paper account may report **USD 1,000,000**. That simulated balance **MUST NEVER**
silently become KalpaMani strategy capital — doing so would inflate every position by
12.5x. Broker equity may be *observed* (via `StrategyCapital.observe_broker_equity`) for
reconciliation and alerting; it never participates in sizing.

Initial configuration defaults (Blueprint V2.1 §10) — **research parameters, not
performance expectations**:

| Control | Value | On USD 80,000 |
|---|---|---|
| Strategy capital | — | **$80,000** |
| Long planned risk / trade | 0.50% | $400 |
| Short planned risk / trade | 0.25% | $200 |
| Max open planned risk | ~5% | $4,000 |
| Max individual position | ~8–10% | $6,400–$8,000 |
| Max gross short exposure | ≤25% | $20,000 |
| Leverage | none | — |

---

## 7. Deterministic vs AI boundary

```
Deterministic  ->  scanning, ranking, gating, sizing, risk, borrow checks,
                   order approval, execution, stops, pyramiding, reconciliation,
                   circuit breakers, kill switch
AI             ->  qualitative evidence extraction, candidate research,
                   filing/news summarization, thesis challenge
```

Every AI output requires **timestamped source provenance, model version and prompt
version**. AI influence stays bounded and auditable. The kill switch must remain
**independent of the AI**.

---

## 8. Working expectations

- **Small, reviewable commits.** No giant omnibus commits. Use conventional prefixes
  (`chore:`, `docs:`, `feat:`, `test:`, `fix:`, `refactor:`).
- **Run the tests before claiming completion.** A task is not done until
  `pytest`, `ruff check`, `ruff format --check` and `mypy` all pass, and the results are
  reported honestly. If something fails, say so and show the output.
- **Never claim a phase is complete when it is not.** Report skipped or blocked work
  explicitly.
- **Architectural deviations require an ADR** in `docs/decisions/` before implementation.
- **Do not begin a new phase without explicit written authorization.**

### Standard verification commands

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m mypy
```

---

## 9. Current phase

**PHASE 1 — IBKR PAPER CONNECTIVITY: COMPLETE AND ACCEPTED (2026-08-25).**
**PHASE 2 — CONTROLLED IBKR PAPER ORDER LIFECYCLE: COMPLETE AND ACCEPTED (2026-08-26).**

### Phase 1 — accepted

Read-only connectivity proven against the live IBKR Paper account: LEAN → IBKR Paper
connected, account confirmed PAPER three ways, SPY subscribed (exactly one symbol, delayed
data), broker account state observed, and — the point of the exercise — the broker reported
**USD 1,000,000** while KalpaMani strategy capital stayed at **USD 80,000** (12.50x
divergence, logged explicitly). **Zero orders, zero positions.** All thirteen acceptance
criteria satisfied.

### Phase 2 — accepted

**Execution plumbing, certified. Not a strategy.** See
[docs/certification/phase2-paper-order-lifecycle.md](docs/certification/phase2-paper-order-lifecycle.md).

Certified scope, and nothing wider:

```
IBKR PAPER only · SPY only · long only · exactly 1 share · FULL-FILL lifecycle
entry -> actual fill -> protective stop -> durable broker-native identity
     -> genuine LEAN / IB Gateway restart -> tagless recovery by BrokerId
     -> controlled protective cancellation -> signed SELL exit fill
     -> final flat reconciliation
```

**Certification runs.** Both are retained; neither may be modified.

| | Run 1 | Run 2 |
|---|---|---|
| final state | `FAILED` | **`RECONCILED`** |
| resolution | `MANUAL_BROKER_CLOSE` | `AUTOMATED` |
| role | **negative certification evidence** | **accepted certification run** |

Run 1 failed at restart ownership recovery — `Order.Tag` is not sent to IBKR, so a
re-hydrated protective order returns anonymous. It **failed closed**: halted, submitted
nothing, left the working stop alone. The position was closed by hand and the run recorded
terminal `FAILED`, never `RECONCILED`. Run 2 proved recovery by durable broker-native
identity across a real restart. See ADR-0004 §21–22.

**Phase 2 does NOT certify** — these are future requirements, not defects in a deliberately
narrow certification:

> partial fills · multiple fill accumulation · a protective stop actually triggering ·
> short lifecycle · multiple simultaneous positions · pyramiding · strategy generation ·
> alpha or profitability · live brokerage execution · real-money operation

### Current operational state

| | |
|---|---|
| broker | **flat** — SPY position 0, open SPY orders 0 |
| arm | none |
| operational halt | none |
| `LIVE_TRADING_HARD_DISABLED` | **True** |

### Security status

Repository visibility is **PUBLIC for development** (§3), by explicit owner decision.
[INC-0002](docs/incidents/INC-0002-account-binding-digest-exposure.md) remains **OPEN**:
pre-sanitization objects still carry an account-binding digest and stay retrievable by exact
SHA, and pull-request description edit history retains an earlier revision. The GitHub purge
has not been performed; the owner has accepted that residual exposure for the development
period.

The repository **must return to PRIVATE** before micro-live, real-money trading, or any
production broker credentials or configuration — see §3. Resuming the purge, and running
`scripts/verify_purge.py` until it exits 0, remains the path to closing INC-0002.

### Operational finding — binding, see [ADR-0003](docs/decisions/ADR-0003-broker-side-order-controls-are-not-safety-invariants.md)

LEAN's IBAutomater unselects IB Gateway's **[Read-Only API]** checkbox and selects every
**[Bypass ... for API Orders]** precaution on every start. **IBKR Read-Only API MUST NOT be
treated as an independent KalpaMani safety control**, and neither may any broker UI
precaution. Broker-side controls are defense-in-depth only and must never be a required
safety invariant. Order safety is enforced internally and deterministically, provable from
this repository alone. This corrects an assumption in Blueprint V2.1 §25; the PDF is not
edited, the correction is indexed in `docs/architecture/BLUEPRINT_ERRATA.md`.

### Still not implemented, and not authorized

Breakout / Pullback / PEAD strategy logic; short-selling logic; AI Research or Challenger
agents; the portfolio/risk engine; the scanner and factor pipeline; the point-in-time data
platform; database schema, dashboard, alerting, kill switch; data purchases; production cloud
infrastructure; options; leverage; X/social signals. Live trading remains **hard-disabled**.

### Next phase

**PHASE 3 — POINT-IN-TIME DATA FOUNDATION.**

**Phase 3 planning is IN REVIEW. Phase 3 implementation is NOT STARTED and is NOT
AUTHORIZED. Data-provider purchase is NOT AUTHORIZED.**

Planning and architecture only, under review on `docs/phase3-pit-data-foundation-plan`:
[`docs/phase3/`](docs/phase3/phase3-pit-data-foundation-charter.md) and
[ADR-0005](docs/decisions/ADR-0005-point-in-time-data-architecture.md) (**Proposed**, not
accepted). No provider has been purchased, trialled or credentialed; no ingestion code
exists.

Recording the plan names what comes next; it does not approve it. Beginning implementation
requires explicit written authorization, per §8.
