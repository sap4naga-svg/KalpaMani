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
**PHASE 3A — SHARADAR PROVIDER-INTEGRATION SLICE 1: IMPLEMENTED, CODE ONLY — ACCEPTED ON MERGE OF PR #13.**
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
subscription, a private credential, any API call, Services Data retrieval, the real S3 writer and
production ingestion are each still **separately unauthorized**.

### Current phase state

**PHASE 3 — POINT-IN-TIME DATA FOUNDATION.**

| | |
|---|---|
| **PHASE 3 PLANNING** | **ACCEPTED / MERGED** |
| **PHASE 3A — A1 FOUNDATION KERNEL** | **ACCEPTED (2026-08-27)** |
| **PHASE 3A — SHARADAR PROVIDER-INTEGRATION SLICE 1** | **IMPLEMENTED / ACCEPTED (ADR-0009, PR #13 merged) — CODE ONLY** |
| **PHASE 3 OVERALL** | **NOT COMPLETE** |
| **Full Stage 3A real-data ingestion** | **NOT AUTHORIZED** |
| **PHASE 3A — A2 / A3 (subscription / purchase)** | **NOT STARTED / NOT AUTHORIZED** |
| **PHASE 3B** | **NOT STARTED / NOT AUTHORIZED** |
| **PHASE 3C** | **NOT STARTED / NOT AUTHORIZED** |
| **PHASE 3D** | **NOT STARTED / NOT AUTHORIZED** |
| **ADR-0005** | **PROPOSED** |
| **ADR-0006 — Blueprint V3.0 adoption** | **ACCEPTED (2026-08-27)** |
| **ADR-0007 — cloud-first research data plane** | **ACCEPTED on merge (2026-08-27)** |
| **[ADR-0008](docs/decisions/ADR-0008-sharadar-personal-use-license-and-private-qualification.md) — Sharadar personal-use licence** | **ACCEPTED on merge (2026-08-27)** |
| **[ADR-0009](docs/decisions/ADR-0009-sharadar-provider-realistic-implementation.md) — Sharadar provider-realistic implementation** | **ACCEPTED on merge of PR #13 — carries no authority before it** |
| **G1** provider selection · **G2** production information-set profile | **OPEN** |
| **G3** vendor licensing — Sharadar personal use | **CLOSED (2026-08-27, ADR-0008)** |
| **G4** analyst revisions · **G5** historical borrow | **OPEN** |
| **G6 options overlay · G7 strategy-taxonomy evidence** | **OPEN (added by V3.0)** |
| **AWS account** | **EXISTING** — pre-dates this work; configured for the KalpaMani foundation 2026-08-27 |
| **AWS research foundation** | **PROVISIONED (2026-08-27)** — 36 resources, verified 66/66 |
| **Cloud spend beyond the idle foundation** | **NOT AUTHORIZED** |
| **Provider purchase / trial / credentialing** | **NOT AUTHORIZED** |
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

No provider has been purchased, trialled or credentialed. No external data has been acquired.
Beginning any further implementation requires explicit written authorization, per §8.

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
licensed bucket EMPTY   ·   control bucket EMPTY   ·   ECR EMPTY
no task definition   ·   nothing running   ·   no always-on billable resource
provider NONE   ·   provider credentials NONE   ·   vendor data NONE
```

**Provisioning a platform is not permission to use it.** Provider purchase, provider
credentialing, ingestion, image builds, task execution and any further cloud spend are each a
**separate written authorization** (§4.21). ADR-0005 **remains PROPOSED**, no provider is
selected, and Phase 3 remains **NOT COMPLETE**. The gate map is in *Decision gates* below;
provisioning the foundation resolved none of them.

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
only**, and is retained rather than deleted: **Q7 (bar construction) and Q8 (Full History depth)
must still be answered before any purchase.**

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
no A2/A3 implementation and no further cloud spend.

### Private Sharadar qualification harness — built, never run by an AI

[`scripts/sharadar_private_qualification.py`](scripts/sharadar_private_qualification.py) is a
standalone P1–P9 harness. It is **not** a production provider adapter: it adds no runtime
dependency, imports no cloud SDK, writes nothing under `src/`, and does not widen the A1 package
surface.

```
credential   vendor-PUBLISHED public test key only   ·   subscription NONE   ·   account NONE
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

### Sharadar provider-integration Slice 1 — implemented, code only, never run

[ADR-0009](docs/decisions/ADR-0009-sharadar-provider-realistic-implementation.md) records the
owner's instruction — *"Authorize the next Sharadar implementation phase"* — and its exact
boundary. It supersedes one repository rule and nothing else: **"no production module may name a
provider"**, which was correct while no provider-specific implementation was authorized.

**The branch implementation is complete and awaiting acceptance.** ADR-0009 is *accepted on merge
of PR #13* and **carries no authority before it**; nothing below is in force until that merge.

```
AUTHORIZED     provider-specific code · provider-neutral interfaces · request construction
               credential-INJECTION interfaces · redaction · pacing · bounded retries
               Bronze mechanics · content addressing · synthetic tests · docs

NOT AUTHORIZED subscription · purchase · trial · vendor account · billing · private credential
               ANY API call · Services Data · production ingestion · Silver/Gold real data
               the real S3 writer · ECR/ECS · terraform apply · ANY AWS mutation
               broker/LEAN activity · Paper expansion · live trading
```

**The adapter has never sent a request, and cannot send one by accident.** Only one module is
network-capable, **nothing in the repository constructs it**, no runner exists, and importing the
package opens no socket. Static tests prove each of those rather than asserting them.

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

**Naming an implementation target is not selecting a production provider. G1 stays OPEN**, and it
cannot close while **Q7** (are the daily bars officially disseminated or provider-aggregated?) and
**Q8** (what depth does Full History actually deliver, per table?) are unanswered. A public-source
re-check on **2026-08-28** answered **neither** — recorded as `PSR-SHD-122` and `PSR-SHD-123` in
[provider-source-register.md](docs/phase3/provider-source-register.md) §R4, with the vendor not
contacted and the API not called. **Both remain pre-purchase blockers.**

### Non-blocking follow-ups carried forward

Neither blocks A1 acceptance, and neither is authorization to begin work:

- `TradeRecord.orders` deep immutability is a separately governed **Phase-2 hardening** matter,
  outside the A1 data-kernel scope.
- Future provider qualification may expose additional contract requirements. Such a requirement
  creates a **new reviewed version** — it does not rewrite A1's evidence.
