# CLAUDE.md — KalpaMani Operating Rules

This file governs **all** work in this repository, in every session. Read it before
making any change. It is binding on humans and AI assistants alike.

---

## 1. Project mission

KalpaMani is an autonomous long/short **U.S. equity swing & momentum trading system**.
It trades liquid U.S. common stocks over a primary **2–30 trading-day horizon**, using
deterministic discovery, ranking, risk and execution, with AI confined to qualitative
information processing and thesis challenge.

**Locked principle (Blueprint V3.0 §2, carried unchanged from V2.1 §1):**

> AI may improve information processing. Mathematics and deterministic software control
> money, risk and broker actions.

---

## 2. Authority order

When instructions conflict, the higher-numbered authority wins:

1. **Blueprint V3.0** — `docs/architecture/KalpaMani_Blueprint_V3_0.pdf`
2. **Approved Architecture Decision Records** — `docs/decisions/`
3. **This CLAUDE.md**
4. **The approved task specification** for the current session
5. **Implementation judgment**

If a lower-level instruction appears to conflict with Blueprint V3.0, **do not silently
redesign the system.** Stop, report the conflict, and propose the change as an ADR.
Architectural deviations require an approved ADR before implementation.

**Blueprint V2.1 remains historical architecture evidence and is not deleted.** It stays
at `docs/architecture/KalpaMani_Blueprint_V2_1.pdf`, unaltered, as the record of the
architecture under which Phase 1, Phase 2 and early Phase 3 were designed and accepted —
but it is **no longer in the authority order**. V3.0 was adopted by
[ADR-0006](docs/decisions/ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md);
the delta and the Document Control override are indexed in
[`docs/architecture/BLUEPRINT_V3_ADOPTION.md`](docs/architecture/BLUEPRINT_V3_ADOPTION.md).

Neither Blueprint PDF is ever edited. Corrections are recorded in an ADR and indexed
beside the document — `BLUEPRINT_ERRATA.md` for V2.1, `BLUEPRINT_V3_ADOPTION.md` for V3.0.

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
> brokerage configuration · **AWS account ids, access keys, secret keys, session tokens,
> ARNs containing a real account id, real bucket names, `terraform.tfstate`, `*.tfvars`,
> `.terraform/`, plan files** · **licensed vendor data of any layer, and any artifact from
> which vendor rows could be reconstructed**

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
21. **Cloud spending requires explicit written authorization.** `terraform apply`, creating
    AWS resources, creating an AWS account and changing billing are each separately
    authorized. Describing infrastructure is not authorization to build it.
22. **Licensed vendor data never leaves the private deployment boundary.** Deterministic code
    may process it inside the private AWS account. It may not be committed to Git, placed in
    third-party SaaS, or sent to any external LLM API — **including by an AI assistant
    session reading such a file into its context**. No raw vendor row enters an external AI
    prompt (§7, [ADR-0007](docs/decisions/ADR-0007-cloud-first-research-data-plane.md) §9).
23. **Licensed data must remain deletable, and provably so.** A vendor licence may require
    destroying every copy within 30 days of a termination that arrives without notice, so the
    licensed store carries no versioning, Object Lock, replication, archival lifecycle or
    backup. Enabling any of them is an ADR-level change, not a durability improvement.
24. **Every AWS task must prove its identity before it acts.** This workstation holds AWS
    profiles for an unrelated project, and `default` is what an unpinned command falls back
    to — the AWS form of the wrong-account hazard §3 guards against for GitHub.

    Before any AWS-mutating command, any `terraform` command that reads or writes remote
    state, and any verification run, a session **MUST** in this order:

    1. pin the intended profile explicitly (`AWS_PROFILE=kalpamani-foundation`);
    2. call `sts:GetCallerIdentity` and compare the returned account against the local
       account binding in the git-ignored `terraform.tfvars`;
    3. **STOP** on a missing binding, an unusable or expired session, an unreadable
       identity, or an account mismatch.

    Only then may remote state be read or any resource be touched. The check reports
    **PASS/FAIL only** and must never print the account id, an ARN, a user or role ARN, or
    an SSO URL. `scripts/aws_foundation_verify.py` implements this gate and refuses before
    reading state; a task that cannot run it has not established its identity and must stop.

    Verification must also **fail closed**: an absence may be concluded only from a specific,
    declared AWS error code, and an IAM decision only from an explicit `allowed`,
    `implicitDeny` or `explicitDeny`. Any other outcome is a verification failure, never a
    satisfied invariant.

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

Initial configuration defaults (Blueprint V3.0 §11.1, unchanged from V2.1 §10) —
**research parameters, not performance expectations**:

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
**PHASE 3A A1 — POINT-IN-TIME FOUNDATION KERNEL: ACCEPTED (2026-08-27).**
**PHASE 3A — SHARADAR PROVIDER-INTEGRATION SLICE 1: IMPLEMENTED / ACCEPTED — PR #13 MERGED — CODE ONLY.**
**PHASE 3A — LICENSED S3 RESEARCH OBJECT STORE: IMPLEMENTED / ACCEPTED — PR #16 MERGED — CODE ONLY, NEVER RUN AGAINST AWS.**
**PHASE 3A — SHARADAR QUALIFICATION RUNTIME CORE: IMPLEMENTED — ACCEPTED EFFECTIVE ON MERGE OF PR #17 — CODE ONLY, NEVER RUN AGAINST SHARADAR OR AWS.**
**PHASE 3 OVERALL: NOT COMPLETE.**

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
agents; the portfolio/risk engine; the scanner and factor pipeline; **any point-in-time data
platform beyond the vendor-neutral A1 kernel and the code-only Sharadar integration slice** —
**no ingestion from a real provider**, no filings, fundamentals, earnings, estimates or borrow;
database schema, dashboard, alerting, kill switch; data purchases; production cloud
infrastructure; options; leverage; X/social signals. Live trading remains **hard-disabled**.

The provider adapter authorized by ADR-0009 is **code that has never run against a vendor**. A
subscription now exists (ADR-0010); a private credential, any API call, Services Data retrieval and
production ingestion are each still **separately unauthorized**.

The licensed S3 object store authorized by
[ADR-0011](docs/decisions/ADR-0011-implement-the-licensed-s3-research-object-store.md) is **code
that has never run against AWS** — see *The licensed S3 object store* below.

### Current phase state

**PHASE 3 — POINT-IN-TIME DATA FOUNDATION.**

| | |
|---|---|
| **PHASE 3 PLANNING** | **ACCEPTED / MERGED** |
| **PHASE 3A — A1 FOUNDATION KERNEL** | **ACCEPTED (2026-08-27)** |
| **PHASE 3A — SHARADAR PROVIDER-INTEGRATION SLICE 1** | **IMPLEMENTED / ACCEPTED (ADR-0009, PR #13 merged) — CODE ONLY** |
| **PHASE 3A — LICENSED S3 RESEARCH OBJECT STORE** | **IMPLEMENTED / ACCEPTED — PR #16 MERGED — CODE ONLY, NEVER RUN AGAINST AWS** |
| **PHASE 3A — SHARADAR QUALIFICATION RUNTIME CORE** | **IMPLEMENTED — ACCEPTED EFFECTIVE ON MERGE OF PR #17 — CODE ONLY, NEVER RUN AGAINST SHARADAR OR AWS** |
| **PHASE 3 OVERALL** | **NOT COMPLETE** |
| **Full Stage 3A real-data ingestion** | **NOT AUTHORIZED** |
| **PHASE 3A — A2 / A3 subscription / purchase** | **AUTHORIZED AND PURCHASED (2026-08-28, ADR-0010)** — one month, Full History Bundle, Personal Use, **for qualification only** |
| **Credential setup · provider API access · Services Data ingestion** | **NOT AUTHORIZED** — a subscription existing is not permission to use it |
| **PHASE 3B** | **NOT STARTED / NOT AUTHORIZED** |
| **PHASE 3C** | **NOT STARTED / NOT AUTHORIZED** |
| **PHASE 3D** | **NOT STARTED / NOT AUTHORIZED** |
| **ADR-0005** | **PROPOSED** |
| **ADR-0006 — Blueprint V3.0 adoption** | **ACCEPTED (2026-08-27)** |
| **ADR-0007 — cloud-first research data plane** | **ACCEPTED on merge (2026-08-27)** |
| **[ADR-0008](docs/decisions/ADR-0008-sharadar-personal-use-license-and-private-qualification.md) — Sharadar personal-use licence** | **ACCEPTED on merge (2026-08-27)** |
| **[ADR-0009](docs/decisions/ADR-0009-sharadar-provider-realistic-implementation.md) — Sharadar provider-realistic implementation** | **ACCEPTED / IN FORCE** — PR #13 merged |
| **[ADR-0010](docs/decisions/ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md) — bounded Sharadar semantics, qualification subscription** | **ACCEPTED / IN FORCE (2026-08-28)** — PR #15 merged |
| **[ADR-0011](docs/decisions/ADR-0011-implement-the-licensed-s3-research-object-store.md) — licensed S3 research object store** | **ACCEPTED / IN FORCE** — PR #16 merged |
| **[ADR-0012](docs/decisions/ADR-0012-implement-the-dormant-sharadar-qualification-runtime-core.md) — dormant Sharadar qualification runtime core** | **ACCEPTED / IN FORCE** — PR #17 merged |
| **[ADR-0013](docs/decisions/ADR-0013-introduce-acquisition-mode-and-retire-is-backfill.md) — acquisition mode, `is_backfill` retired** | **ACCEPTED EFFECTIVE ON MERGE OF THE PR INTRODUCING IT** — carries no authority before it |
| **G1** provider selection · **G2** production information-set profile | **OPEN** |
| **G3** vendor licensing — Sharadar personal use | **CLOSED (2026-08-27, ADR-0008)** |
| **G4** analyst revisions · **G5** historical borrow | **OPEN** |
| **G6 options overlay · G7 strategy-taxonomy evidence** | **OPEN (added by V3.0)** |
| **AWS account** | **EXISTING** — pre-dates this work; configured for the KalpaMani foundation 2026-08-27 |
| **AWS research foundation** | **PROVISIONED (2026-08-27)** — 36 resources, verified 66/66 |
| **Cloud spend beyond the idle foundation** | **NOT AUTHORIZED** |
| **Any AWS mutation, read, verifier run or Terraform command** | **NOT AUTHORIZED** — implementing a client-shaped adapter is not permission to run one |
| **Real bucket binding · SDK client construction · credential source** | **NOT AUTHORIZED** — none exists, and a static test keeps it that way |
| **[ADR-0014](docs/decisions/ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md) — dormant composition root + offline preflight** | **ACCEPTED EFFECTIVE ON MERGE OF THE PR INTRODUCING IT** — carries no authority before it. One dormant composition root exists; **execution surface NONE**, **runner NONE**, provider and AWS requests **ZERO** |
| **Ingestion runner · ECS task or image · authenticated qualification run** | **NOT AUTHORIZED** |
| **CONTROL-classification publication** | **DEFERRED / NOT AUTHORIZED** |
| **Provider purchase — qualification subscription** | **PURCHASED / ACTIVE (2026-08-28, ADR-0010)** |
| **Provider credentialing / API access / Services Data** | **NOT AUTHORIZED** |
| **Real external-data acquisition** | **NOT STARTED** |
| **Short research** | **NOT AUTHORIZED** |
| **Strategies / Brain / AI / portfolio / risk** | **NOT IMPLEMENTED / NOT AUTHORIZED** |
| **Live trading** | **HARD-DISABLED** |

The planning package is accepted and lives in
[`docs/phase3/`](docs/phase3/phase3-pit-data-foundation-charter.md), with
[ADR-0005](docs/decisions/ADR-0005-point-in-time-data-architecture.md).

### A1 — accepted, and what acceptance means

[`docs/phase3/phase3a-a1-foundation-kernel.md`](docs/phase3/phase3a-a1-foundation-kernel.md)
records what it built and what it deliberately did not. It is **vendor-neutral**: the merged
point-in-time contract as executable, type-checked Python, proven against repository-owned
**synthetic** fixtures. It adds **no runtime dependency**, makes **no network call**, and has
**no brokerage boundary**.

```
no provider connected   ·   no production data   ·   no short research
no Phase 3B / 3C / 3D authority   ·   no gate resolved by A1   ·   ADR-0005 still PROPOSED
```

**A1 proves the vendor-neutral point-in-time mechanism using repository-owned synthetic
data. It is not provider qualification.** Provider tests P1–P9 remain **unrun**, and cannot be
run without a provider that has not been selected. **No real provider satisfies the contract
merely because A1 passed**, and no synthetic result in the slice is production evidence.

**Merging A1 grants no authority for A2, A3, Phase 3B, 3C or 3D.** Phase 3 itself is **not
complete**. The proposed architecture and provider selections remain subject to
ADR-0005's five open decision gates —

> G1 provider selection · G2 production information-set profile · G3 vendor licensing ·
> G4 the analyst-estimate gap · G5 borrow-history qualification

**No *production* provider has been selected or credentialed, and no external data has been
acquired.** A bounded Sharadar qualification subscription was later purchased under ADR-0010
(2026-08-28) — for qualification only, selecting nothing and closing no gate. Beginning any further
implementation requires explicit written authorization, per §8.

**Blueprint V3.0 is ADOPTED and is repository authority (2026-08-27).** It was adopted by
owner authorization through a documentation-only pull request, and the authority order in
§2 now names it first. See
[ADR-0006](docs/decisions/ADR-0006-adopt-blueprint-v3-and-strategy-brain-governance.md) and
[`docs/architecture/BLUEPRINT_V3_ADOPTION.md`](docs/architecture/BLUEPRINT_V3_ADOPTION.md).

**Adoption is a governance change, not a phase milestone.** It grants **no** implementation
authority for A2, A3, Phase 3B/3C/3D, the Phase-4 Brain, strategies, AI agents, provider
access, Paper expansion, live trading, capital or leverage — each still requires its own
written authorization, per §8. Phase 3 remains **NOT COMPLETE**, ADR-0005 remains
**PROPOSED**, and **V3 adoption resolved no decision gate** — the current gate map is in
*Decision gates* below.

The adopted PDF is byte-identical to the document the owner reviewed (SHA-256
`2726b96dd69c8982788b1c2bd646ce7a52879c649994a31858dc41666761996d`). Because a Blueprint PDF
is never edited, its Document Control page still reads as drafted for review; those fields
are **superseded** by the override table in `BLUEPRINT_V3_ADOPTION.md`.

### Research data plane — private AWS cloud-first, and nothing built

**[ADR-0007](docs/decisions/ADR-0007-cloud-first-research-data-plane.md) makes a private AWS
account the *intended* authoritative location** for licensed research data and heavy
deterministic research compute, replacing the laptop-authoritative store proposed in ADR-0005
§11. Parquet, DuckDB and Python are unchanged; only the location moves. PostgreSQL's operational
role under ADR-0001 is untouched.

| | |
|---|---|
| Laptop | **development and control workstation**; optional cache, staging, synthetic fixtures, local testing |
| Laptop | **not** the authoritative licensed-data store, not required to stay powered on for ingestion, not required for heavy backtests |
| Licensed-data bucket | bronze / silver / gold / qualification — **deletion-first**: no versioning, no Object Lock, no replication, no archival lifecycle, no backup |
| Control bucket | manifests, lineage, receipts, approved non-reconstructable outputs |
| Classification rule | *can vendor rows be recovered from this artifact?* Yes **or uncertain** → licensed |
| Compute | **ephemeral** — one-off tasks. No always-on server |
| Network | **zero inbound rules**, outbound HTTPS only, no listener, no load balancer |

**The foundation is PROVISIONED; nothing uses it (2026-08-27).**
[`infra/aws/research-data-plane/`](infra/aws/research-data-plane/) was applied — 36 resources,
`0 changed, 0 destroyed`, verified 66/66 against the live account. Full record:
[docs/operations/aws-foundation-status.md](docs/operations/aws-foundation-status.md).

```
AWS account EXISTING   ·   foundation PROVISIONED   ·   verification 66/66 PASS
at closeout: licensed bucket EMPTY · control bucket EMPTY · ECR EMPTY
no task definition   ·   nothing running   ·   no always-on billable resource
production provider SELECTED: NONE   ·   G1 OPEN
credential stored, configured or bound by this repository: NONE
vendor data in this repository: NONE   ·   ingestion runs: ZERO
```

**These are claims about this repository and about the foundation as provisioned**, not about the
owner's accounts. A Sharadar qualification subscription is **purchased and active** (ADR-0010) and
its clock is running; whether a vendor API key exists in the owner's possession is outside what
this repository establishes, and nothing here may infer it. What *is* checkable: no credential is
stored, configured or bound anywhere in this repository, and no ingestion has run.

**Provisioning a platform is not permission to use it.** Production-provider **selection**,
credentialing, provider API access, Services Data, ingestion, image builds, task execution and any
further cloud spend are each a **separate written authorization** (§4.21). The one purchase that
*has* been authorized and completed is the bounded qualification subscription under ADR-0010, and
it authorizes no access. ADR-0005 **remains PROPOSED**, no production provider is selected, and
Phase 3 remains **NOT COMPLETE**. The gate map is in *Decision gates* below; neither provisioning
the foundation nor buying the qualification subscription resolved any of them.

Deletion authority stayed separated through provisioning. The routine research role cannot
delete. The deletion role can delete licensed objects but cannot read or write them and cannot
reach the control bucket.

Its trust policy **does** admit `ecs-tasks.amazonaws.com` — it is not "unassumable", and describing
it that way would overstate the control. The property that actually holds it inert is narrower and
worth stating exactly: **no human can directly assume it, no deletion task definition exists, no
deletion workflow exists, and no authorized principal holds `iam:PassRole` for it — so no current
path can launch an ECS task running as it.** Every one of those is verified against the live
account, not merely declared.

The termination procedure exists in advance and has **never been run**:
[docs/runbooks/vendor-data-cloud-deletion.md](docs/runbooks/vendor-data-cloud-deletion.md).

### Decision gates — the exact map

**No blanket "G1–G7 are all OPEN" statement is correct any more.** [ADR-0008](docs/decisions/ADR-0008-sharadar-personal-use-license-and-private-qualification.md) closed
**G3** and nothing else.

| Gate | Subject | Status |
|---|---|---|
| **G1** | provider selection / qualification | **OPEN** |
| **G2** | production information-set profile | **OPEN** |
| **G3** | vendor licensing — Sharadar personal use | **CLOSED (2026-08-27)** |
| **G4** | analyst estimates and revisions | **OPEN** |
| **G5** | historical borrow | **OPEN** |
| **G6** | options overlay | **OPEN** |
| **G7** | strategy-taxonomy evidence | **OPEN** |

ADR-0006 and ADR-0007 each state that all seven were open. **That was true when each was
accepted; neither is edited**, on the same rule that keeps a Blueprint PDF unedited. Their gate
statements are historical and superseded for G3 alone.

**If the provider changes away from Sharadar, G3 reopens for the replacement provider.**

### Sharadar personal-use licence — accepted, and what it constrains

[ADR-0008](docs/decisions/ADR-0008-sharadar-personal-use-license-and-private-qualification.md) records the owner's acceptance of the **published** Sharadar Personal Use
License for individual personal research, personal backtesting, programmatic API use, and
automated trading of the owner's own account where the published documentation permits it. The
previously drafted Q1–Q8 vendor clarification is **CANCELLED — NOT SENT — historical evidence
only**, and is retained rather than deleted. **Q7 remained publicly unresolved; Q8 was publicly
bounded but not empirically verified. The owner accepted both dispositions for qualification** —
see [ADR-0010](docs/decisions/ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md).

Accepting the licence means accepting these, in every session:

| | |
|---|---|
| **Personal use only** | owner as a natural person. No employer, client, entity, fund or institutional use. No redistribution. An LLC or trust would void it |
| **Services Data stays private** | deterministic KalpaMani code inside the private boundary may process vendor rows. Git, an AI chat, a Claude context, an external LLM API and shared SaaS may not receive them |
| **Empirical evaluation is private** | Terms §8 bars disclosing fitness conclusions. P1–P9 results, sampled rows, provider-quality conclusions and the private recommendation live **only** in the licensed S3 `qualification/` prefix and git-ignored `.runtime/` — never in Git, a PR, an issue, a commit message or an AI session |
| **Public documentation may describe** | methodology, public vendor documentation, architecture, and limitations already apparent from public documentation |
| **Termination** | qualification material is licensed and sits inside the 30-day deletion surface of [the deletion runbook](docs/runbooks/vendor-data-cloud-deletion.md) |
| **Third-party AI** | vendor *documentation* may be read by an AI assistant. **Services Data and private evaluation results may not.** |

**What ADR-0008 does not do:** it selects no provider, closes no other gate, purchases nothing,
creates no vendor account, holds no private credential, and authorizes no production ingestion,
no A2/A3 implementation and no further cloud spend. That is a statement about **ADR-0008's own
scope**, not about the world today: the qualification subscription was authorized and purchased
separately, later, under [ADR-0010](docs/decisions/ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md).

### Private Sharadar qualification harness — built, never run by an AI

[`scripts/sharadar_private_qualification.py`](scripts/sharadar_private_qualification.py) is a
standalone P1–P9 harness. It is **not** a production provider adapter: it adds no runtime
dependency, imports no cloud SDK, writes nothing under `src/`, and does not widen the A1 package
surface.

```
credential   the harness reads ONLY the vendor's PUBLISHED public test key
             no private credential is stored, configured or bound by this repository
network      OFF by default -- --private-live-run required, plus the AWS identity gate
refuses      pytest, CI, import, preflight, docs audit
stdout       an allowlist -- no P-status, no recommendation, no bucket, no URL, no vendor row
exit code    harness success/failure ONLY -- never a provider verdict
storage      raw + private report to the LICENSED bucket under qualification/sharadar/<run-id>/
report       .runtime/phase3/sharadar/ -- git-ignored, owner-readable, never committed
```

**The owner runs it manually.** No AI session may run it, and no AI session may receive its
output. `PROCEED` / `HOLD` / `REJECT` is computed inside the private report and is never printed,
never returned and never encoded in the exit status.

**Research-bucket emptiness is no longer a standing invariant.** Both research-data buckets were
empty *at AWS-foundation closeout*, and that record stands as evidence of that day. Once
qualification begins, the licensed bucket may legitimately hold private material. Object counts,
row counts and pass/fail results are private and are never published.

### The licensed S3 object store — implemented, code only, never run against AWS

[ADR-0011](docs/decisions/ADR-0011-implement-the-licensed-s3-research-object-store.md) authorized
one thing: the **LICENSED-only S3 backend** of the provider-neutral `ResearchObjectStore`, written
and reviewed **while the store still has nothing bound to it** — no bucket identifier, no
credential, no client. `src/kalpamani/data/storage/s3.py` is the whole of it.

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

What it guarantees, each with a test behind it rather than an intention:

| | |
|---|---|
| **Append-only** | one `PutObject` with `IfNoneMatch="*"`. **No preflight `HEAD`** — a check-then-write is a race, and the bucket carries no versioning to absorb it (§4.23) |
| **412 vs 409** | only `412 PreconditionFailed` means occupied. `409 ConditionalRequestConflict` is a retryable conflict in which the condition was never resolved: it is `TRANSIENT`, sends no `HeadObject`, and yields no idempotency or collision verdict |
| **Integrity** | full-object **SHA-256**, sent and verified, and S3 must state `ChecksumType="FULL_OBJECT"`. **Never an ETag, and never a `COMPOSITE` checksum** — both depend on how the object was uploaded rather than on its bytes |
| **Encryption** | SSE-S3 requested explicitly on every write, never inherited from a bucket default |
| **Collisions** | resolved by `HeadObject` metadata. **The bytes are never downloaded** — this store has no read surface, and pulling vendor payloads back would spread licensed rows |
| **Ambiguity** | an unverifiable response is `INVALID_RESPONSE`, a refusal — including an absent or unrecognised checksum type. A permission failure is never absence |
| **Errors** | sanitized into closed `StrEnum` vocabularies and raised `from None`. No bucket, key, endpoint, request id, host id or credential-shaped text can reach a log or a traceback |
| **Surface** | `put_object` and `head_object` only. No read, list, delete, copy or multipart path exists to reach. **Deletion stays with the separately roled path** under ADR-0007 |
| **CONTROL** | refused at admission. CONTROL publication remains **deferred** |

**One runtime dependency, and nothing imports it.** `boto3>=1.36.0,<2.0` is declared because a real
deployment must *construct* a signed client, and request signing, credential resolution and retry
behaviour must be the official SDK's. **No module under `src/` imports it**: the client is injected
and backend errors are classified structurally, so importing the data platform pulls in no AWS
code, opens no socket and performs no ambient credential discovery. A static test permits only
`data/storage/s3.py` — the only application module under `src/` permitted to do so — to name the
SDK at all, and asserts that even it imports none of it today.

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
publication remains **separately unauthorized** (§4.21, §4.24). **G1 and G2 stay OPEN**, ADR-0005
stays **PROPOSED**, and Phase 3 stays **NOT COMPLETE**.

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
it has no execution surface and changes nothing about that authorization.)
`BACKFILL` and `UPDATE` exist as production modes and **neither production operation is
authorized**.

**G1 OPEN · G2 OPEN · G3 CLOSED · G4–G7 OPEN**, ADR-0005 **PROPOSED**, INC-0002 **OPEN**, Phase 3
**NOT COMPLETE**, CONTROL publication **DEFERRED**, live trading **HARD-DISABLED**.

### The Sharadar qualification composition root — dormant, and the offline preflight

[ADR-0014](docs/decisions/ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md)
authorized the wiring the five previous slices deliberately did without: one module that receives
every dependency explicitly and builds the accepted client, licensed store and qualification runtime
from them. `data/ingest/sharadar/composition.py`, and no second module.

**This supersedes the standing "composition root: NONE" claim, and nothing else.** That claim was
true of every earlier slice and is quoted in their historical text, which is not rewritten. What
holds now is narrower and is checked rather than declared:

```
composition root      EXISTS   one module, named individually, and no second
offline preflight     EXISTS   validate() only -- no fetch, no publication
execution surface     NONE     no execute, run, fetch, publish or upload, public or private
runner                NONE     no CLI, no entry point, no console script, no task, no image
credential retrieval  NONE     no environment read, no file read, no reveal() call
real credential binding: NONE   ·   real bucket binding: NONE
AWS SDK session or client construction: NONE   ·   no module under src/ imports the SDK
constructed or imported outside its own tests: NEVER
Sharadar requests: ZERO   ·   AWS requests: ZERO   ·   Services Data: NONE
```

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
| **The result is closed** | frozen, slotted, subclass-refusing: a status, five bounded counts, `AcquisitionMode.QUALIFICATION` and `PROVIDER_REALISTIC_PIT`. **No credential, bucket, URL, region, account, subject, payload, backend-message or free-text field** — none has anywhere to be, and `__post_init__` enforces that rather than the annotations |
| **The numbers are derived** | request count from the plan's generator, attempt ceiling from the injected client's retry policy, response ceiling from the stricter of client and plan. A preflight reporting declared intentions would describe a different run |
| **The status word is a control** | one member, **`VALIDATED_OFFLINE`**. `READY`, `PROCEED`, `APPROVED`, `QUALIFIED` and `AUTHORIZED` are each refused anywhere in the module. **Preflight is not a verdict**: it says a plan is internally consistent, and nothing about the provider, the data, or whether a run should happen |
| **One member, on purpose** | a *failure* status that can be returned is a failure a caller can ignore. Every refusal raises, in an existing closed vocabulary |
| **Nothing leaks** | a secret-shaped, bucket-shaped, backend-message-shaped and subject-shaped canary, each proven absent from the result, its fields, both reprs, every refusal and captured output |
| **Zero activity, counted** | the transport and the S3 client raise if called, and their call counts are asserted at zero through a real `S3ResearchObjectStore`. `reveal()` is counted by patching the credential class |
| **`QUALIFICATION` is fixed** | no mode parameter on the composition, on preflight, on the plan or on the limits. The result reports the mode; it does not choose it ([ADR-0013](docs/decisions/ADR-0013-introduce-acquisition-mode-and-retire-is-backfill.md)) |

**The first authenticated qualification run remains separately gated, and this slice does not
approach it.** What would still be needed: an authorization, a credential source, a real credential,
a constructed SDK client, a bound bucket, and code that calls something other than `preflight`.
**None of those exists.**

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
credential source: NONE   ·   SDK client construction: NONE   ·   real bucket binding: NONE
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

### Sharadar provider-integration Slice 1 — implemented, code only, never run

[ADR-0009](docs/decisions/ADR-0009-sharadar-provider-realistic-implementation.md) records the
owner's instruction — *"Authorize the next Sharadar implementation phase"* — and its exact
boundary. It supersedes one repository rule and nothing else: **"no production module may name a
provider"**, which was correct while no provider-specific implementation was authorized.

**PR #13 is merged. ADR-0009 is ACCEPTED and IN FORCE**, and Slice 1 is
**IMPLEMENTED / ACCEPTED — CODE ONLY**: the adapter is reviewed, merged code that has never sent a
request to a vendor.

**ADR-0009 holds the historical scope of Slice 1**, including what that decision did not cover on
2026-08-27. It is not reproduced here. Later owner decisions moved the boundary — the qualification
subscription was authorized and completed under
[ADR-0010](docs/decisions/ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md),
and the licensed S3 writer was authorized under
[ADR-0011](docs/decisions/ADR-0011-implement-the-licensed-s3-research-object-store.md) — so a
verbatim copy of the older list in a *current-status* document would be a second, stale matrix
sitting beside the real one. **The matrix below is the only one that governs a session now.**

It is also narrower than a historical list can be. An older prohibition on *a vendor account* or
*billing* described what an implementation slice was permitted to do; it never described the owner's
private affairs, and this repository neither governs nor records them. Completing an authorized
purchase necessarily involved owner-side account and billing activity, and nothing here may forbid,
infer or deny it.

```
IN FORCE       ADR-0009 provider-specific code (PR #13 merged)
               ADR-0010 bounded semantics + qualification subscription PURCHASED / ACTIVE
               ADR-0011 licensed S3 object store (PR #16 merged) -- CODE ONLY,
                        NEVER RUN AGAINST AWS
               ADR-0012 dormant qualification runtime core -- ACCEPTED EFFECTIVE ON
                        MERGE OF PR #17, CODE ONLY, NEVER RUN AGAINST SHARADAR OR AWS
               ADR-0014 dormant composition root + offline preflight -- ACCEPTED EFFECTIVE
                        ON MERGE, CODE ONLY, NO EXECUTION SURFACE, NEVER RUN

NOT AUTHORIZED credential retrieval, setup, configuration or binding · Secrets Manager use
               a credential source · real credential or bucket binding · SDK client construction
               an execution surface on the composition root · a second composition root
               ANY provider API call · the published test token · Services Data · bulk download
               empirical qualification · production backfill · production ingestion
               Silver/Gold real data · production-provider SELECTION
               ANY AWS mutation, read, verifier run or terraform command · ECR/ECS · image builds
               an ingestion runner · an authenticated qualification run · CONTROL publication
               broker/LEAN activity · Paper expansion · live trading

UNCHANGED      G1 OPEN · G2 OPEN · G3 CLOSED · G4 OPEN · G5 OPEN · G6 OPEN · G7 OPEN
               ADR-0005 PROPOSED · INC-0002 OPEN · Phase 3 NOT COMPLETE
               CONTROL publication DEFERRED · live trading HARD-DISABLED
```

**The published test token stays unauthorized deliberately.** The manual qualification harness is
*able* to read it; that is not permission to run the harness, which only the owner runs and no AI
session may.

**The adapter has never sent a request, and cannot send one by accident.** Only one module is
network-capable, and importing the package opens no socket. A client *is* now constructed — by the
dormant composition root
([ADR-0014](docs/decisions/ADR-0014-implement-the-dormant-sharadar-qualification-composition-root.md)),
from an **injected** transport and an **injected** credential, in a class whose only operation
validates a plan offline. **No credential source exists**, so nothing can hand it a real key; nothing
outside its own tests constructs it; and it has no execution surface to reach a transport through.
Static tests prove each of those rather than asserting them.

| | |
|---|---|
| **Vendor knowledge is confined** | `src/kalpamani/data/ingest/sharadar/` only. The A1 kernel and every neutral package stay vendor-neutral, and no other production module names the provider |
| **No key value exists under `src/`** | not a private one, and **not the vendor's published test token either** — that stays in the manual harness. A credential is injected, renders as a placeholder everywhere, and is reachable only through `reveal()` |
| **Errors disclose nothing** | assembled from closed vocabularies, so a URL, a query string and a response body have **no parameter to arrive through**. The key travels in the query string (`PSR-SHD-109`), so a request URL *is* a credential |
| **Requests are explicit** | HTTPS, stated format, stated pagination, explicit date window — **no implicit one-year default** (`PSR-SHD-121`), no window on the snapshot table (`PSR-SHD-119`), and **no constructible table-wide bulk download** |
| **The transport is origin-pinned** | the URL is **parsed**, not prefix-matched: scheme, host, port, empty userinfo, empty fragment and the documented path prefix must all match. Redirects are refused rather than followed, ambient proxy discovery is off, no opener is installed globally, and a successful body is bounded (64 MiB default, 256 MiB hard cap) |
| **LICENSED is the only publishable class** | `ObjectKey.licensed(...)` is the sole constructor and takes no classification parameter; `CONTROL` is refused outright. The free-text attestation was withdrawn -- `"x"` would have passed it, and nothing bound it to the object it cleared |
| **Object identity is name + digest** | `exists` is `False` when a name holds different content, and a forged key cannot read another object's bytes |
| **Keys and payloads are deeply frozen** | segments are copied into a fresh plain tuple of plain `str`, subclassing is refused, and a payload must be exact immutable `bytes` -- a caller-held `list` or `bytearray` could otherwise change a key or its content after it was validated |
| **Acquisition identity is global** | `(digest, run id)` is claimed under the reserved `bronze/_acquisition_claims/`, so two providers cannot claim one retrieval. The leading underscore is refused by `safe_component`, so no provider can collide with it, and the deletion runbook's `bronze/` step already covers it. Payloads and records stay provider-separable; **claims are not**, and that is stated rather than implied |
| **Durable metadata has no free-text field** | not a filtered one — an absent one. Every recorded field is validated against its own grammar, and the provider bridge offers no `notes` parameter |
| **Closed vocabularies are normalised** | at construction, running no code belonging to the value, so a bare string, a sibling enum or a hostile `str` subclass cannot reach `.value` and raise from inside an error |
| **No caller text reaches a header** | the client takes no `user_agent`; the transport validates header names and values itself, because `Request` stores them unchecked and CR/LF is only rejected at send time |

**Naming an implementation target is not selecting a production provider. G1 stays OPEN.**

**Neither Q7 nor Q8 is a remaining pre-purchase blocker, and their evidence states differ**
([ADR-0010](docs/decisions/ADR-0010-accept-bounded-sharadar-semantics-and-authorize-qualification-subscription.md), 2026-08-28). **Q7 remained publicly unresolved; Q8 was publicly bounded but not empirically verified. The owner accepted both dispositions for qualification.**

| | |
|---|---|
| **Q7** — daily price-bar origin | **`PUBLICLY_UNRESOLVED`**, owner-accepted for qualification. All Sharadar price data stays **`PROVIDER_DERIVED`**, usable only under **`PROVIDER_REALISTIC_PIT`**, and **never represented as `PUBLIC_PIT`** |
| **Q8** — Full History depth | **`PUBLICLY_BOUNDED`**, owner-accepted for qualification. The documented per-table depths are **planning boundaries, not certified earliest records**; actual minimum dates, coverage and completeness **must be measured from the subscribed data** under a separate authorization |

The vendor was not contacted and the API was not called for either decision; the evidence is public documentation recorded as `PSR-SHD-122`–`PSR-SHD-128` in
[provider-source-register.md](docs/phase3/provider-source-register.md) §R4–§R5, each table's depth cited to that table's own page.

### Non-blocking follow-ups carried forward

Neither blocks A1 acceptance, and neither is authorization to begin work:

- `TradeRecord.orders` deep immutability is a separately governed **Phase-2 hardening** matter,
  outside the A1 data-kernel scope.
- Future provider qualification may expose additional contract requirements. Such a requirement
  creates a **new reviewed version** — it does not rewrite A1's evidence.
