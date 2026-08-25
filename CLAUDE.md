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
VISIBILITY:               PRIVATE
DEFAULT BRANCH:           main
```

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

**PHASE 1 — IBKR PAPER CONNECTIVITY: COMPLETE AND VALIDATED (2026-08-25).**

Bootstrap complete. Phase 1 read-only connectivity **proven against the live IBKR Paper
account**: LEAN -> IBKR Paper connected, account confirmed PAPER three ways, SPY subscribed
(exactly one symbol, delayed data), broker account state observed, and — the point of the
exercise — the broker reported **USD 1,000,000** while KalpaMani strategy capital stayed at
**USD 80,000** (12.50x divergence, logged explicitly). **Zero orders, zero positions.**

Market data confirmed: a SPY bar was received at **05:15 ET pre-market** (close 766.38,
volume 360) within a minute of connecting, on delayed IBKR data. All thirteen Phase 1
acceptance criteria are satisfied.

**Operational finding — read this.** LEAN's IBAutomater unselects IB Gateway's
**[Read-Only API]** checkbox and selects every **[Bypass ... for API Orders]** precaution on
every start. Enabling IBKR Read-Only Access does **not** protect an automated deployment.
The zero-order guarantee rests entirely on our own code having no order path, which is why
that is enforced statically by `scripts/phase1_preflight.py` and
`tests/unit/test_phase1_broker_safety.py` rather than trusted to a broker setting.

**Still not implemented and not authorized:** order submission of any kind (paper or live);
Breakout / Pullback / PEAD strategy logic; short-selling logic; AI Research or Challenger
agents; the portfolio/risk engine; data purchases; production cloud infrastructure; options;
leverage; X/social signals.

**Next phase (requires explicit approval): PHASE 1 — IBKR PAPER CONNECTIVITY.**
Objective: LEAN → IBKR Paper → subscribe to one liquid U.S. equity → receive market data
→ read brokerage/account state → **NO ORDER SUBMISSION** → clean shutdown and
reconciliation. Phase 1 must also prove that KalpaMani strategy capital remains **$80,000**
even when IBKR Paper reports a NetLiquidation of **$1,000,000**.
